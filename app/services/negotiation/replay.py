from __future__ import annotations

from copy import deepcopy

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.hybrid_simulation.adapter import verify_modifier_bundle
from app.services.hybrid_simulation.models import HybridModifierBundle
from app.services.run_lifecycle import repository as lifecycle_repository
from app.services.simulation_runtime import SimulationRuntimeApplicationPort, simulation_runtime_service

from .repository import NegotiationRepository


simulation_runtime: SimulationRuntimeApplicationPort = simulation_runtime_service


def replay_negotiation_from_storage(run_id: str, repository: NegotiationRepository | None = None) -> WarRoomRun:
    """Verify and replay stored negotiation state without invoking any Agent provider."""

    repo = repository or NegotiationRepository()
    session = repo.get_session(run_id)
    rounds = repo.list_rounds(session.session_id)
    messages = repo.list_messages(session.session_id)
    commitments = repo.list_commitments(session.session_id)
    if len(rounds) != 6 or any(item.status != "completed" for item in rounds):
        raise ValueError("Negotiation replay requires six completed rounds")

    previous_hash = None
    for message in messages:
        proposal = message.payload.get("proposal")
        identity = {
            "tick": message.tick,
            "seq": message.seq,
            "sender_agent_id": message.sender_agent_id,
            "recipient_agent_ids": message.recipient_agent_ids,
            "message_type": message.message_type,
            "visibility": message.visibility,
            "parent_message_id": message.parent_message_id,
            "proposal": proposal,
            "narrative": message.narrative,
            "previous_hash": previous_hash,
        }
        if message.previous_hash != previous_hash or stable_hash(identity) != message.message_hash:
            raise ValueError(f"Negotiation message hash chain mismatch at seq {message.seq}")
        previous_hash = message.message_hash

    baseline_payload = lifecycle_repository.get_latest_artifact_content(run_id, "war_room_result")
    if not baseline_payload:
        raise ValueError("Negotiation replay baseline artifact is missing")
    state = WarRoomRun.model_validate(baseline_payload)
    previous_state_hash = stable_hash(state.model_dump(mode="json"))
    if previous_state_hash != session.baseline_result_hash:
        raise ValueError("Negotiation baseline result hash mismatch")
    for round_record in rounds:
        if round_record.previous_state_hash != previous_state_hash:
            raise ValueError(f"Negotiation state chain mismatch at tick {round_record.tick}")
        if stable_hash(round_record.input) != round_record.input_hash or stable_hash(round_record.output) != round_record.output_hash:
            raise ValueError(f"Negotiation round hash mismatch at tick {round_record.tick}")
        raw_bundle = round_record.output.get("modifier_bundle")
        if raw_bundle:
            bundle = HybridModifierBundle.model_validate(raw_bundle)
            verify_modifier_bundle(bundle)
            if bundle.bundle_hash != round_record.modifier_bundle_hash:
                raise ValueError(f"Negotiation modifier hash mismatch at tick {round_record.tick}")
            state = simulation_runtime.run_war_room(WarRoomScenarioRequest(**bundle.scenario_patch))
            applications = round_record.output.get("narrative_diffusion", {}).get("applications", [])
            if applications:
                deltas: dict[str, float] = {}
                for item in applications:
                    code = item["receiver_country"]
                    deltas[code] = deltas.get(code, 0.0) + float(item["applied_delta"])
                overrides = deepcopy(state.scenario.country_overrides)
                countries = {item.code: item for item in state.country_agents}
                for code, delta in deltas.items():
                    if code not in countries:
                        raise ValueError(f"Narrative replay references unknown country: {code}")
                    override = dict(overrides.get(code, {}))
                    override["public_opinion_pressure"] = round(max(0.0, min(100.0, countries[code].public_opinion_pressure + delta)), 4)
                    overrides[code] = override
                state = simulation_runtime.run_war_room(WarRoomScenarioRequest(
                    scenario_key=state.scenario.key, duration_days=state.scenario.duration_days,
                    intensity=state.scenario.intensity, propagation=state.scenario.propagation,
                    target_countries=list(state.scenario.target_countries), target_chains=list(state.scenario.target_chains),
                    policy_actions=list(state.scenario.policy_actions), country_overrides=overrides,
                    chain_overrides=deepcopy(state.scenario.chain_overrides),
                    seed=int(round_record.output.get("narrative_diffusion", {}).get("seed", 42)),
                ))
        result_hash = stable_hash(state.model_dump(mode="json"))
        if result_hash != round_record.result_state_hash or result_hash != round_record.output.get("result_hash"):
            raise ValueError(f"Negotiation result hash mismatch at tick {round_record.tick}")
        previous_state_hash = result_hash

    for commitment in commitments:
        expected = stable_hash({
            "source_proposal_id": commitment.source_proposal_id,
            "parties": commitment.party_agent_ids,
            "terms": commitment.terms,
        })
        if expected != commitment.commitment_hash:
            raise ValueError(f"Negotiation commitment hash mismatch: {commitment.commitment_id}")

    final = state
    if stable_hash(final.model_dump(mode="json")) != session.final_result_hash:
        raise ValueError("Negotiation final result hash mismatch")
    return final
