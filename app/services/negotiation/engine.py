from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from time import perf_counter

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.core.negotiation_models import NegotiationEnvelope, NegotiationReplayManifest
from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext
from app.services.agent_runtime.action_parser import parse_action_proposal
from app.services.agent_runtime.context_builder import build_provider_request
from app.services.agent_runtime.provider import ConfiguredLLMAgentProvider, ProviderUnavailable
from app.services.agent_runtime.registry import role_for_actor_type
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.hybrid_simulation.adapter import build_modifier_bundle, verify_modifier_bundle
from app.services.reviews import create_review_case
from app.services.run_lifecycle import repository as lifecycle_repository
from app.services.simulation_runtime import SimulationRuntimeApplicationPort, simulation_runtime_service

from .agent_pack import build_agent_pack, scheduled_profiles
from .diffusion import apply_narrative_diffusion
from .repository import NegotiationRepository
from .semantics import alliance_commitment_conflicts, proposal_semantic_key, response_is_authorized


simulation_runtime: SimulationRuntimeApplicationPort = simulation_runtime_service


TICK_PROGRESS = (0.0, 0.10, 0.23, 0.47, 0.70, 1.0)
BILATERAL_ACTIONS = {"alliance_request", "deescalation_offer", "humanitarian_offer"}
AUDIT_ONLY_ACTIONS = {"intelligence_request"}


def run_negotiation(
    baseline: WarRoomRun,
    *,
    run_id: str,
    seed: int = 42,
    should_stop=None,
    repository: NegotiationRepository | None = None,
    runtime_profile: dict | None = None,
    persist_legacy_artifacts: bool = True,
) -> tuple[WarRoomRun, dict]:
    repo = repository or NegotiationRepository()
    runtime = _runtime_config(runtime_profile)
    live_provider = _configured_provider(runtime)
    pack = repo.save_agent_pack(build_agent_pack(baseline, seed))
    session = repo.create_session(run_id, pack, stable_hash(baseline.model_dump(mode="json")))
    completed_rounds = [item for item in repo.list_rounds(session.session_id) if item.status == "completed"]
    state = WarRoomRun(**completed_rounds[-1].output["result"]) if completed_rounds else baseline
    cumulative_deltas = dict(session.cumulative_patch.get("narrative_deltas", {}))
    semantic_keys = set(session.cumulative_patch.get("semantic_keys", []))
    applied_ids = set(session.applied_proposal_ids)

    for tick in range(session.current_tick + 1, 7):
        if should_stop and should_stop():
            break
        profiles = scheduled_profiles(pack, tick)
        day = int(round(baseline.scenario.duration_days * TICK_PROGRESS[tick - 1]))
        state_hash = stable_hash(state.model_dump(mode="json"))
        round_input = {
            "tick": tick,
            "simulation_day": day,
            "state_hash": state_hash,
            "agent_pack_hash": pack.manifest_hash,
            "scheduled_agents": [item.agent_id for item in profiles],
            "active_commitment_hashes": [item.commitment_hash for item in repo.list_commitments(session.session_id) if item.status == "active"],
        }
        round_record = repo.create_round(session, tick, day, round_input["scheduled_agents"], round_input, state_hash)
        existing_senders = {item.sender_agent_id for item in repo.list_messages(session.session_id, tick=tick)}
        pending_profiles = [profile for profile in profiles if profile.agent_id not in existing_senders]
        all_messages = repo.list_messages(session.session_id)
        provider_tokens_used = sum(item.estimated_tokens for item in all_messages if item.provider != "mock-deterministic")
        generated = _generate_tick_envelopes(
            state, pack, pending_profiles, tick, run_id, seed, repo.list_messages(session.session_id),
            runtime=runtime, provider=live_provider,
            token_budget_remaining=max(0, runtime["token_budget"] - provider_tokens_used),
        )
        for profile, envelope, invocation in sorted(generated, key=lambda item: item[0].agent_id):
            message = repo.add_message(
                session.session_id, round_record.round_id, tick, envelope,
                provider=invocation["provider"], model=invocation["model"], latency_ms=invocation["latency_ms"],
                estimated_tokens=invocation["estimated_tokens"], fallback_used=invocation["fallback_used"],
            )
            lifecycle_repository.append_event(
                run_id, "AGENT", "consistency_audit", f"Negotiation tick {tick}: {message.message_type}",
                "受控 Agent 已提交结构化定性消息；数值权威仍由确定性规则引擎持有。",
                tick=tick, payload={"message_id": message.message_id, "sender_agent_id": message.sender_agent_id, "message_hash": message.message_hash},
            )

        messages = repo.list_messages(session.session_id, tick=tick)
        proposals = [AgentActionProposal(**item.payload["proposal"]) for item in messages if item.payload.get("proposal")]
        context = _constraint_context(state, pack)
        audit = evaluate_war_room_result(state, run_id=f"{run_id}:tick:{tick}", proposals=proposals, constraint_context=context)
        decisions = {item.proposal_id: item for item in audit.proposal_decisions}
        semantic_issues = _update_commitments(repo, session.session_id, messages, proposals, decisions, pack)
        _create_negotiation_review_cases(run_id, tick, audit.proposal_decisions, semantic_issues)

        active_commitments = {item.source_proposal_id: item for item in repo.list_commitments(session.session_id) if item.status == "active"}
        eligible: list[AgentActionProposal] = []
        for proposal in proposals:
            decision = decisions.get(proposal.proposal_id)
            if not decision or decision.outcome != "accepted" or proposal.proposal_id in applied_ids:
                continue
            if proposal.action_type in BILATERAL_ACTIONS and proposal.proposal_id not in active_commitments:
                continue
            if proposal.action_type in AUDIT_ONLY_ACTIONS or proposal.action_type == "alliance_response":
                continue
            eligible.append(proposal)
        # A commitment may activate in a later tick; project its original proposal exactly once.
        for commitment in active_commitments.values():
            if commitment.source_proposal_id not in applied_ids and not any(item.proposal_id == commitment.source_proposal_id for item in eligible):
                eligible.append(AgentActionProposal(**commitment.terms))
        eligible = [item for item in eligible if proposal_semantic_key(item) not in semantic_keys]

        modifier_hash = None
        modifier_payload = None
        diffusion_payload = {"schema_version": "narrative-diffusion.v1", "country_deltas": {}, "applications": []}
        if eligible:
            projection_audit = evaluate_war_room_result(state, run_id=f"{run_id}:projection:{tick}", proposals=eligible, constraint_context=context)
            bundle = build_modifier_bundle(state, eligible, projection_audit.proposal_decisions, seed=seed)
            verify_modifier_bundle(bundle)
            modifier_hash = bundle.bundle_hash
            modifier_payload = bundle.model_dump(mode="json")
            projected = simulation_runtime.run_war_room(WarRoomScenarioRequest(**bundle.scenario_patch))
            narrative = [item for item in eligible if item.action_type == "public_narrative"]
            if narrative:
                diffusion_request, diffusion_audit, cumulative_deltas = apply_narrative_diffusion(projected, narrative, cumulative_deltas, seed=seed)
                projected = simulation_runtime.run_war_room(diffusion_request)
                diffusion_payload = diffusion_audit.model_dump(mode="json")
            state = projected
            applied_ids.update(item.proposal_id for item in eligible)
            semantic_keys.update(proposal_semantic_key(item) for item in eligible)

        result_hash = stable_hash(state.model_dump(mode="json"))
        output = {
            "tick": tick,
            "simulation_day": day,
            "message_ids": [item.message_id for item in messages],
            "message_hashes": [item.message_hash for item in messages],
            "proposal_decisions": [item.model_dump(mode="json") for item in audit.proposal_decisions],
            "semantic_issues": semantic_issues,
            "consistency_audit_hash": audit.audit_hash,
            "active_commitment_ids": sorted(item.commitment_id for item in repo.list_commitments(session.session_id) if item.status == "active"),
            "applied_proposal_ids": sorted(item.proposal_id for item in eligible),
            "modifier_bundle_hash": modifier_hash,
            "modifier_bundle": modifier_payload,
            "narrative_diffusion": diffusion_payload,
            "result": state.model_dump(mode="json"),
            "result_hash": result_hash,
        }
        completed = repo.complete_round(round_record.round_id, output, modifier_hash, result_hash)
        session = repo.update_session(session.session_id, tick=tick, result_hash=result_hash, patch={"narrative_deltas": cumulative_deltas, "semantic_keys": sorted(semantic_keys)}, applied_ids=sorted(applied_ids), completed=tick == 6)
        if persist_legacy_artifacts:
            lifecycle_repository.add_artifact(run_id, "negotiation_round", "negotiation-round.v1", completed.model_dump(mode="json"))
            lifecycle_repository.add_artifact(run_id, "negotiation_checkpoint", "negotiation-checkpoint.v1", {"session_id": session.session_id, "tick": tick, "round_output_hash": completed.output_hash, "result_state_hash": result_hash})
            lifecycle_repository.add_artifact(run_id, "commitment_ledger", "commitment-ledger.v1", {"tick": tick, "commitments": [item.model_dump(mode="json") for item in repo.list_commitments(session.session_id)]})
            lifecycle_repository.add_artifact(run_id, "narrative_diffusion", "narrative-diffusion.v1", diffusion_payload)
        lifecycle_repository.append_event(
            run_id, "SNAPSHOT", "consistency_audit", f"Negotiation tick {tick} committed",
            f"D+{day} 协商检查点已固化；通过准入的行动已由确定性适配器投影。", tick=tick,
            payload={"round_id": completed.round_id, "output_hash": completed.output_hash, "result_state_hash": result_hash, "active_commitments": len(output["active_commitment_ids"])},
        )

    rounds = repo.list_rounds(session.session_id)
    messages = repo.list_messages(session.session_id)
    commitments = repo.list_commitments(session.session_id)
    final_hash = stable_hash(state.model_dump(mode="json"))
    replay_core = {
        "schema_version": "negotiation-replay.v1",
        "session_id": session.session_id,
        "agent_pack_hash": pack.manifest_hash,
        "baseline_result_hash": session.baseline_result_hash,
        "final_result_hash": final_hash,
        "round_hashes": [item.output_hash for item in rounds if item.output_hash],
        "message_chain_head": messages[-1].message_hash if messages else None,
        "commitment_hashes": [item.commitment_hash for item in commitments],
        "provider_calls_required": 0,
    }
    replay = NegotiationReplayManifest(**replay_core, replay_hash=stable_hash(replay_core))
    if len(rounds) == 6 and all(item.status == "completed" for item in rounds):
        proposal_types = {
            item.proposal_id: item.payload["proposal"]["action_type"]
            for item in messages
            if item.proposal_id and isinstance(item.payload.get("proposal"), dict) and item.payload["proposal"].get("action_type")
        }
        applied_types = sorted({proposal_types[item] for item in applied_ids if item in proposal_types})
        decision_outcomes = {
            decision["proposal_id"]: decision.get("outcome")
            for round_item in rounds
            for decision in round_item.output.get("proposal_decisions", [])
            if decision.get("proposal_id")
        }
        active_commitment_types = sorted({item.action_type for item in commitments if item.status == "active"})
        if persist_legacy_artifacts:
            lifecycle_repository.add_artifact(
                run_id,
                "negotiation_action_observation",
                "agent-outcome-observation-source.v1",
                {
                    "proposal_types": proposal_types,
                    "decision_outcomes": decision_outcomes,
                    "applied_proposal_ids": sorted(applied_ids),
                    "applied_action_types": applied_types,
                    "active_commitment_types": active_commitment_types,
                },
            )
            lifecycle_repository.add_artifact(run_id, "negotiation_replay", replay.schema_version, replay.model_dump(mode="json"))
    summary = {
        "session": repo.get_session(run_id).model_dump(mode="json"),
        "agent_pack": pack.model_dump(mode="json"),
        "rounds": [item.model_dump(mode="json", exclude={"input", "output"}) for item in rounds],
        "message_count": len(messages),
        "active_commitment_count": sum(1 for item in commitments if item.status == "active"),
        "accepted_action_count": len(applied_ids),
        "rejected_action_count": sum(1 for item in rounds for decision in item.output.get("proposal_decisions", []) if decision.get("outcome") in {"rejected", "constrained", "expired"}),
        "runtime": runtime,
        "replay": replay.model_dump(mode="json"),
    }
    return state, summary


def _mock_envelope(state, pack, profile, tick: int, run_id: str, seed: int, prior_messages) -> NegotiationEnvelope:
    country_id = f"country:{profile.country_code}"
    children = {item.parent_message_id for item in prior_messages if item.parent_message_id}
    pending = []
    for item in prior_messages:
        proposal = item.payload.get("proposal")
        if item.message_id in children or not proposal or proposal.get("action_type") not in BILATERAL_ACTIONS:
            continue
        if country_id in proposal.get("target_ids", []):
            pending.append(item)
    if pending:
        parent = sorted(pending, key=lambda item: item.seq)[0]
        original = AgentActionProposal(**parent.payload["proposal"])
        if original.action_type == "alliance_request" and tick == 3:
            params = deepcopy(original.parameters)
            params["duration_days"] = max(1, min(int(params["duration_days"]), 14))
            proposal = _proposal(profile, run_id, tick, "alliance_request", [_country_for_agent(pack, parent.sender_agent_id)], params, "coordinate", [country_id, *original.evidence_refs[:2]], "提出期限更短、范围不变的联盟协调反提案。")
            return NegotiationEnvelope(message_type="counteroffer", visibility="direct", sender_agent_id=profile.agent_id, recipient_agent_ids=[parent.sender_agent_id], parent_message_id=parent.message_id, narrative="原提案需要缩短期限后方可接受。", proposal=proposal)
        return NegotiationEnvelope(message_type="accept", visibility="direct", sender_agent_id=profile.agent_id, recipient_agent_ids=[parent.sender_agent_id], parent_message_id=parent.message_id, narrative="在能力、资源与证据约束内接受该提案。")

    countries = sorted(state.country_agents, key=lambda item: (-item.risk_score, item.code))
    target = next(item for item in countries if item.code != profile.country_code)
    target_country = f"country:{target.code}"
    timeline_ref = f"timeline:{state.timeline[-1].day}" if state.timeline else "scenario"
    evidence = [country_id, target_country, timeline_ref]
    if profile.actor_type == "public_opinion":
        tone = ("stabilizing", "informational", "firm")[(tick + seed) % 3]
        proposal = _proposal(profile, run_id, tick, "public_narrative", [target_country], {"theme": "公开说明供应链、人道与降级风险", "audience": "global" if tick >= 4 else "regional", "tone": tone}, "inform", evidence, "发布不含权威数值的受控公共叙事。")
        return NegotiationEnvelope(message_type="public_statement", visibility="public", sender_agent_id=profile.agent_id, narrative="公共叙事已提交确定性扩散器计算。", proposal=proposal)
    if profile.actor_type == "alliance":
        recipient = _agent_for_country(pack, target.code)
        proposal = _proposal(profile, run_id, tick, "alliance_request", [target_country], {"objective": "协调外交、情报和人道保障", "requested_support": ["diplomatic", "intelligence"], "duration_days": min(21, state.scenario.duration_days)}, "coordinate", evidence, "请求建立需要对方明确接受的受控联盟承诺。")
        return NegotiationEnvelope(message_type="proposal", visibility="direct", sender_agent_id=profile.agent_id, recipient_agent_ids=[recipient], narrative="联盟请求等待接收方回应。", proposal=proposal)
    if profile.actor_type == "diplomacy" and tick >= 4:
        recipient = _agent_for_country(pack, target.code)
        proposal = _proposal(profile, run_id, tick, "deescalation_offer", [target_country], {"measure": "hotline", "verification": "third_party", "duration_days": min(14, state.scenario.duration_days)}, "deescalate", evidence, "提出需要对方接受并经过一致性检查的降级机制。")
        return NegotiationEnvelope(message_type="proposal", visibility="direct", sender_agent_id=profile.agent_id, recipient_agent_ids=[recipient], narrative="降级提案等待接收方回应。", proposal=proposal)
    if profile.actor_type == "diplomacy":
        proposal = _proposal(profile, run_id, tick, "diplomatic_signal", [target_country], {"signal": "deescalatory", "channel": "backchannel", "public": False}, "deescalate", evidence, "通过受控渠道发出降级信号。")
    else:
        chain = sorted(state.supply_chains, key=lambda item: (-item.pressure_score, item.key))[0]
        if tick % 3 == 1:
            proposal = _proposal(profile, run_id, tick, "sanction_proposal", [target_country], {"sector": chain.key if chain.key in {"energy", "food", "chips", "shipping", "settlement"} else "shipping", "scope": "targeted", "review_days": min(30, state.scenario.duration_days)}, "deter", evidence, "提交受审计的定性制裁提案。")
        elif tick % 3 == 2:
            chain_id = f"chain:{chain.key}"
            proposal = _proposal(profile, run_id, tick, "trade_reroute_request", [chain_id], {"chain_key": chain.key, "alternative_route": "规则沙盘备用通道", "duration_days": min(30, state.scenario.duration_days)}, "reroute", [country_id, chain_id, timeline_ref], "请求启用确定性规则定义的备用供应路径。")
        else:
            proposal = _proposal(profile, run_id, tick, "intelligence_request", [target_country], {"topic": "公开来源态势变化", "classification": "open_source", "horizon_days": min(30, state.scenario.duration_days)}, "observe", evidence, "记录只读情报请求，不产生数值映射。")
    return NegotiationEnvelope(message_type="proposal", visibility="public", sender_agent_id=profile.agent_id, narrative="定性行动提案已提交一致性评估。", proposal=proposal)


def _proposal(profile, run_id, tick, action_type, targets, parameters, direction, evidence, justification):
    core = {"run_id": run_id, "turn": tick, "actor_id": profile.agent_id, "actor_type": profile.actor_type, "action_type": action_type, "target_ids": targets, "parameters": parameters, "justification": justification, "evidence_refs": sorted(set(evidence)), "expected_direction": direction, "confidence": 72.0, "created_at": f"2000-01-01T00:00:{tick:02d}.000Z", "expires_after_turn": min(6, tick + 2)}
    return AgentActionProposal(proposal_id=f"proposal_{stable_hash(core)[:16]}", **core)


def _constraint_context(state, pack):
    entities = {f"country:{item.code}" for item in state.country_agents} | {f"chain:{item.key}" for item in state.supply_chains} | {f"timeline:{item.day}" for item in state.timeline} | {"scenario"}
    return AgentConstraintContext(actor_capabilities={item.agent_id: item.capabilities for item in pack.profiles}, action_budgets={item.agent_id: item.action_budget for item in pack.profiles}, known_entities=sorted(entities), known_evidence_refs=sorted(entities))


def _agent_for_country(pack, code: str) -> str:
    candidates = [item for item in pack.profiles if item.country_code == code]
    return sorted(candidates, key=lambda item: (item.actor_type != "country_policy", item.agent_id))[0].agent_id if candidates else sorted(pack.profiles, key=lambda item: item.agent_id)[0].agent_id


def _country_for_agent(pack, agent_id: str) -> str:
    profile = next((item for item in pack.profiles if item.agent_id == agent_id), None)
    return f"country:{profile.country_code}" if profile else "country:UNKNOWN"


def _update_commitments(repo, session_id, messages, proposals, decisions, pack):
    issues: list[dict] = []
    proposal_by_id = {item.proposal_id: item for item in proposals}
    for message in messages:
        if message.proposal_id and message.proposal_id in proposal_by_id:
            proposal = proposal_by_id[message.proposal_id]
            decision = decisions.get(proposal.proposal_id)
            if proposal.action_type in BILATERAL_ACTIONS and decision and decision.outcome == "accepted":
                repo.create_commitment(session_id, message, proposal, [message.sender_agent_id, *message.recipient_agent_ids])
        if message.message_type not in {"accept", "reject", "withdrawal", "counteroffer"} or not message.parent_message_id:
            continue
        prior = repo.list_messages(session_id)
        parent = next((item for item in prior if item.message_id == message.parent_message_id), None)
        if not parent or not parent.proposal_id:
            issues.append({"code": "invalid_parent_message", "message_id": message.message_id, "parent_message_id": message.parent_message_id})
            continue
        commitment = next((item for item in repo.list_commitments(session_id) if item.source_proposal_id == parent.proposal_id), None)
        if not commitment:
            continue
        if not response_is_authorized(parent, message):
            issues.append({"code": "unauthorized_response", "message_id": message.message_id, "parent_message_id": parent.message_id})
            continue
        status = {"accept": "active", "reject": "rejected", "withdrawal": "withdrawn", "counteroffer": "rejected"}[message.message_type]
        if status == "active" and alliance_commitment_conflicts(commitment, repo.list_commitments(session_id)):
            status = "rejected"
            issues.append({"code": "conflicting_alliance_commitment", "message_id": message.message_id, "commitment_id": commitment.commitment_id})
        repo.add_commitment_event(commitment.commitment_id, session_id, message.tick, status, message.sender_agent_id, message.message_id, f"Negotiation response: {message.message_type}")
    return issues


def _create_negotiation_review_cases(run_id: str, tick: int, decisions, semantic_issues: list[dict]) -> None:
    for decision in decisions:
        if decision.outcome not in {"constrained", "rejected", "expired"}:
            continue
        create_review_case(
            "negotiation_action_admission",
            "negotiation_action",
            f"{run_id}:{decision.proposal_id}",
            f"Negotiation action requires acknowledgement: {decision.outcome}",
            severity="high" if decision.outcome == "rejected" else "warning",
            payload={
                "run_id": run_id,
                "tick": tick,
                "proposal_id": decision.proposal_id,
                "outcome": decision.outcome,
                "rule_version": decision.rule_version,
                "audit_hash": decision.audit_hash,
                "projection_status": decision.projection_status,
            },
        )
    for issue in semantic_issues:
        create_review_case(
            "negotiation_semantic_violation",
            "negotiation_message",
            f"{run_id}:{issue['message_id']}",
            f"Negotiation message failed semantic admission: {issue['code']}",
            severity="high",
            payload={"run_id": run_id, "tick": tick, **issue},
        )


def _estimate_tokens(envelope: NegotiationEnvelope) -> int:
    return max(32, len(str(envelope.model_dump(mode="json"))) // 4)


def _runtime_config(overrides: dict | None = None) -> dict:
    provider = str(os.getenv("AGENT_PROVIDER", "mock")).strip().lower()
    if provider not in {"mock", "deepseek", "siliconflow"}:
        provider = "mock"
    fallback = str(os.getenv("AGENT_FALLBACK_MODE", "mock")).strip().lower()
    values = {
        "provider": provider,
        "model": str(os.getenv("AGENT_MODEL", "mock-negotiation-v1" if provider == "mock" else "configured-provider-default"))[:120],
        "fallback_mode": fallback if fallback in {"mock", "skip"} else "mock",
        "max_agents": 12,
        "max_ticks": 6,
        "max_active_per_tick": 6,
        "max_calls": 36,
        "token_budget": 60000,
        "timeout_seconds": max(1.0, min(120.0, float(os.getenv("AGENT_TIMEOUT_SECONDS", "30")))),
        "max_input_chars": 16000,
        "concurrency": 2,
    }
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    return values


def _configured_provider(runtime: dict):
    if runtime["provider"] == "mock":
        return None
    provider = ConfiguredLLMAgentProvider(runtime["provider"])
    if not provider.enabled:
        if runtime["fallback_mode"] == "skip":
            raise ProviderUnavailable(f"{provider.name} is unavailable and negotiation fallback is disabled")
        return None
    return provider


def _generate_tick_envelopes(
    state, pack, profiles, tick, run_id, seed, prior_messages, *, runtime, provider,
    token_budget_remaining: int,
):
    templates = [(profile, _mock_envelope(state, pack, profile, tick, run_id, seed, prior_messages)) for profile in profiles]
    fallback_reason = runtime["provider"] != "mock" and provider is None
    if provider is None:
        return [
            (profile, envelope, {
                "provider": "mock-deterministic", "model": "mock-negotiation-v1", "latency_ms": 0,
                "estimated_tokens": _estimate_tokens(envelope), "fallback_used": bool(fallback_reason),
            })
            for profile, envelope in templates
        ]

    per_call_budget = min(
        runtime["token_budget"] // runtime["max_calls"],
        token_budget_remaining // max(1, len(templates)),
    )

    def invoke(profile, envelope):
        role = role_for_actor_type(profile.actor_type)
        if envelope.proposal is None or role is None or envelope.proposal.action_type not in role.allowed_actions:
            return profile, envelope, {"provider": "mock-deterministic", "model": "mock-negotiation-v1", "latency_ms": 0, "estimated_tokens": _estimate_tokens(envelope), "fallback_used": False}
        mock_payload = envelope.proposal.model_dump(mode="json", include={"action_type", "target_ids", "parameters", "justification", "evidence_refs", "expected_direction", "confidence"})
        request = build_provider_request(state, run_id=run_id, turn=tick, role=role, actor_id=profile.agent_id, timeout_seconds=runtime["timeout_seconds"], max_input_chars=runtime["max_input_chars"], mock_payload=mock_payload)
        input_tokens = max(1, (len(request.system_prompt) + len(request.user_prompt)) // 4)
        if input_tokens >= per_call_budget:
            if runtime["fallback_mode"] == "skip":
                raise RuntimeError("Negotiation provider token budget exhausted")
            return profile, envelope, {
                "provider": "mock-deterministic", "model": "mock-negotiation-v1", "latency_ms": 0,
                "estimated_tokens": _estimate_tokens(envelope), "fallback_used": True,
            }
        started = perf_counter()
        try:
            response = provider.generate(request)
            proposal = parse_action_proposal(response.payload, request, seed=seed)
            replacement = envelope.model_copy(update={"proposal": proposal})
            total_tokens = input_tokens + int(response.usage_tokens or max(32, len(response.output_text) // 4))
            if total_tokens > per_call_budget:
                raise RuntimeError("Negotiation provider response exceeded the per-call token budget")
            return profile, replacement, {
                "provider": response.provider, "model": response.model,
                "latency_ms": max(0, int((perf_counter() - started) * 1000)),
                "estimated_tokens": total_tokens, "fallback_used": False,
            }
        except Exception:
            if runtime["fallback_mode"] == "skip":
                raise
            return profile, envelope, {
                "provider": "mock-deterministic", "model": "mock-negotiation-v1",
                "latency_ms": max(0, int((perf_counter() - started) * 1000)),
                "estimated_tokens": _estimate_tokens(envelope), "fallback_used": True,
            }

    results = []
    with ThreadPoolExecutor(max_workers=runtime["concurrency"]) as pool:
        futures = [pool.submit(invoke, profile, envelope) for profile, envelope in templates]
        for future in as_completed(futures):
            results.append(future.result())
    return results
