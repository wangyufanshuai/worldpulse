from __future__ import annotations

from copy import deepcopy

from app.core.models import WarRoomRun
from app.services.agent_contract.models import AgentActionProposal
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import AgentActionDecision

from .models import DeterministicActionModifier, HybridModifierBundle


POLICY_ORDER = (
    "sanctions",
    "counter_sanctions",
    "energy_reroute",
    "food_export_limit",
    "alliance_deterrence",
    "liquidity_support",
    "public_messaging",
)
POLICY_INDEX = {value: index for index, value in enumerate(POLICY_ORDER)}


def build_modifier_bundle(
    baseline: WarRoomRun,
    proposals: list[AgentActionProposal],
    decisions: list[AgentActionDecision],
    *,
    seed: int = 42,
) -> HybridModifierBundle:
    accepted = {decision.proposal_id for decision in decisions if decision.decision == "accepted"}
    proposal_by_id = {proposal.proposal_id: proposal for proposal in proposals}
    missing = sorted(accepted - set(proposal_by_id))
    if missing:
        raise ValueError(f"Accepted decisions reference missing proposals: {', '.join(missing)}")
    selected = sorted((proposal_by_id[item] for item in accepted), key=lambda item: (item.turn, item.proposal_id))
    modifiers = [_modifier_for(proposal) for proposal in selected]
    scenario_patch = _scenario_patch(baseline, modifiers, seed=seed)
    payload = {
        "schema_version": "hybrid-modifier-bundle.v1",
        "adapter_version": "worldpulse-action-adapter.v0.11",
        "accepted_proposal_ids": [proposal.proposal_id for proposal in selected],
        "modifiers": [modifier.model_dump(mode="json") for modifier in modifiers],
        "scenario_patch": scenario_patch,
    }
    return HybridModifierBundle(**payload, bundle_hash=stable_hash(payload))


def verify_modifier_bundle(bundle: HybridModifierBundle) -> None:
    payload = bundle.model_dump(mode="json", exclude={"bundle_hash"})
    if stable_hash(payload) != bundle.bundle_hash:
        raise ValueError("Hybrid modifier bundle hash mismatch")
    for modifier in bundle.modifiers:
        modifier_payload = modifier.model_dump(mode="json", exclude={"modifier_hash", "modifier_id"})
        if stable_hash(modifier_payload) != modifier.modifier_hash:
            raise ValueError(f"Deterministic modifier hash mismatch: {modifier.modifier_id}")


def _modifier_for(proposal: AgentActionProposal) -> DeterministicActionModifier:
    policies: list[str] = []
    chain_adjustments: dict[str, dict[str, float]] = {}
    no_effect = None

    if proposal.action_type == "trade_reroute_request":
        chain = str(proposal.parameters.get("chain_key"))
        if chain == "energy":
            policies.append("energy_reroute")
        elif chain == "settlement":
            policies.append("liquidity_support")
        elif chain in {"food", "chips", "shipping"}:
            chain_adjustments[chain] = {"substitution_delta": 8.0, "lag_days_delta": -2.0}
        else:
            no_effect = "未知供应链没有确定性映射。"
    elif proposal.action_type == "diplomatic_signal":
        policies.append("alliance_deterrence" if proposal.parameters.get("signal") == "firm" else "public_messaging")
    elif proposal.action_type in {"alliance_request", "alliance_response"}:
        if proposal.action_type == "alliance_response" and proposal.parameters.get("response") == "decline":
            no_effect = "拒绝联盟请求不产生额外确定性动作。"
        else:
            policies.append("alliance_deterrence")
    elif proposal.action_type == "sanction_proposal":
        policies.append("sanctions")
    elif proposal.action_type in {"public_narrative", "deescalation_offer"}:
        policies.append("public_messaging")
    elif proposal.action_type in {"humanitarian_offer", "intelligence_request"}:
        no_effect = "该动作在 v0.11 中仅记录与解释，没有经过批准的数值映射。"
    else:  # pragma: no cover - Pydantic action enum protects this branch
        no_effect = "动作没有确定性映射。"

    modifier_payload = {
        "schema_version": "deterministic-action-modifier.v1",
        "adapter_version": "worldpulse-action-adapter.v0.11",
        "proposal_id": proposal.proposal_id,
        "turn": proposal.turn,
        "action_type": proposal.action_type,
        "policy_actions": sorted(set(policies), key=_policy_sort_key),
        "chain_adjustments": chain_adjustments,
        "rationale_refs": sorted(set(proposal.evidence_refs)),
        "no_numeric_effect_reason": no_effect,
    }
    modifier_hash = stable_hash(modifier_payload)
    return DeterministicActionModifier(
        **modifier_payload,
        modifier_id=f"modifier_{modifier_hash[:16]}",
        modifier_hash=modifier_hash,
    )


def _scenario_patch(baseline: WarRoomRun, modifiers: list[DeterministicActionModifier], *, seed: int) -> dict:
    policies = set(baseline.scenario.policy_actions)
    chain_deltas: dict[str, dict[str, float]] = {}
    for modifier in modifiers:
        policies.update(modifier.policy_actions)
        for chain_key, adjustments in modifier.chain_adjustments.items():
            target = chain_deltas.setdefault(chain_key, {"substitution_delta": 0.0, "lag_days_delta": 0.0})
            target["substitution_delta"] += float(adjustments.get("substitution_delta", 0))
            target["lag_days_delta"] += float(adjustments.get("lag_days_delta", 0))

    chain_overrides = deepcopy(baseline.scenario.chain_overrides)
    chains = {chain.key: chain for chain in baseline.supply_chains}
    for chain_key, deltas in sorted(chain_deltas.items()):
        if chain_key not in chains:
            continue
        chain = chains[chain_key]
        current = dict(chain_overrides.get(chain_key, {}))
        substitution_delta = _clamp(deltas["substitution_delta"], -20, 20)
        lag_delta = _clamp(deltas["lag_days_delta"], -7, 7)
        current["substitution"] = round(_clamp(chain.substitution + substitution_delta, 0, 100), 1)
        current["lag_days"] = int(round(_clamp(chain.lag_days + lag_delta, 0, 60)))
        chain_overrides[chain_key] = current

    return {
        "scenario_key": baseline.scenario.key,
        "duration_days": baseline.scenario.duration_days,
        "intensity": baseline.scenario.intensity,
        "propagation": baseline.scenario.propagation,
        "target_countries": list(baseline.scenario.target_countries),
        "target_chains": list(baseline.scenario.target_chains),
        "policy_actions": sorted(policies, key=_policy_sort_key),
        "country_overrides": deepcopy(baseline.scenario.country_overrides),
        "chain_overrides": chain_overrides,
        "seed": int(seed),
    }


def _policy_sort_key(value: str) -> tuple[int, str]:
    return POLICY_INDEX.get(value, len(POLICY_INDEX)), value


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
