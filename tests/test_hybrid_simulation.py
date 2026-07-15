from copy import deepcopy

import pytest

from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract import build_mock_agent_batch
from app.services.consistency import evaluate_war_room_result
from app.services.hybrid_simulation import replay_hybrid_from_artifacts, run_hybrid_simulation
from app.services.war_room_engine import run_war_room


def _fixture():
    baseline = run_war_room(WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d",
        duration_days=30,
        intensity=0.7,
        propagation=0.45,
        seed=42,
    ))
    batch = build_mock_agent_batch(baseline, run_id="job_hybrid", seed=42)
    audit = evaluate_war_room_result(
        baseline,
        run_id="job_hybrid",
        proposals=batch.proposals,
        constraint_context=batch.constraint_context,
    )
    return baseline, batch, audit


def test_hybrid_applies_only_accepted_actions_without_mutating_baseline():
    baseline, batch, audit = _fixture()
    before = deepcopy(baseline.model_dump(mode="json"))
    decisions = [
        decision.model_copy(update={"decision": "rejected"}) if index == 0 else decision
        for index, decision in enumerate(audit.proposal_decisions)
    ]
    restricted_audit = audit.model_copy(update={"proposal_decisions": decisions})

    outcome = run_hybrid_simulation(baseline, batch.proposals, restricted_audit, seed=42)

    assert baseline.model_dump(mode="json") == before
    assert outcome.modifier_bundle.accepted_proposal_ids == sorted(
        decision.proposal_id for decision in decisions if decision.decision == "accepted"
    )
    assert decisions[0].proposal_id not in outcome.modifier_bundle.accepted_proposal_ids
    assert outcome.final_result.ui_state["hybrid_trace"]["numeric_authority"] == "WorldPulse deterministic War Room engine"


def test_hybrid_mapping_is_order_independent_and_bounded():
    baseline, batch, audit = _fixture()
    forward = run_hybrid_simulation(baseline, batch.proposals, audit, seed=42)
    reversed_outcome = run_hybrid_simulation(
        baseline,
        list(reversed(batch.proposals)),
        audit.model_copy(update={"proposal_decisions": list(reversed(audit.proposal_decisions))}),
        seed=42,
    )

    assert forward.modifier_bundle.bundle_hash == reversed_outcome.modifier_bundle.bundle_hash
    assert forward.replay_record.final_result_hash == reversed_outcome.replay_record.final_result_hash
    for chain_key, override in forward.modifier_bundle.scenario_patch["chain_overrides"].items():
        assert 0 <= float(override.get("substitution", 0)) <= 100
        assert 0 <= float(override.get("lag_days", 0)) <= 60


def test_hybrid_offline_replay_reproduces_hash_and_rejects_tampering():
    baseline, batch, audit = _fixture()
    outcome = run_hybrid_simulation(baseline, batch.proposals, audit, seed=42)
    proposal_payload = {"proposals": [item.model_dump(mode="json") for item in batch.proposals]}

    replayed = replay_hybrid_from_artifacts(
        baseline.model_dump(mode="json"),
        proposal_payload,
        audit.model_dump(mode="json"),
        outcome.modifier_bundle.model_dump(mode="json"),
        outcome.replay_record.model_dump(mode="json"),
    )
    assert replayed.timeline[-1].global_risk == outcome.final_result.timeline[-1].global_risk

    tampered = outcome.modifier_bundle.model_dump(mode="json")
    tampered["scenario_patch"]["intensity"] = 0.99
    with pytest.raises(ValueError, match="bundle hash mismatch"):
        replay_hybrid_from_artifacts(
            baseline.model_dump(mode="json"),
            proposal_payload,
            audit.model_dump(mode="json"),
            tampered,
            outcome.replay_record.model_dump(mode="json"),
        )
