from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract import AgentActionProposal, build_mock_agent_batch
from app.services.consistency import evaluate_war_room_result
from app.services.war_room_engine import run_war_room


def _war_room_result():
    return run_war_room(WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d",
        duration_days=30,
        intensity=0.7,
        propagation=0.45,
        seed=42,
    ))


def _valid_proposal(**overrides):
    payload = {
        "proposal_id": "proposal_contract_001",
        "run_id": "job_contract",
        "turn": 1,
        "actor_id": "country:CHN",
        "actor_type": "diplomacy",
        "action_type": "diplomatic_signal",
        "target_ids": ["country:TWN"],
        "parameters": {"signal": "deescalatory", "channel": "backchannel", "public": False},
        "justification": "通过受控私下渠道提出降级信号。",
        "evidence_refs": ["country:CHN", "country:TWN"],
        "expected_direction": "deescalate",
        "confidence": 72,
        "created_at": "2000-01-01T00:00:01.000Z",
    }
    payload.update(overrides)
    return AgentActionProposal(**payload)


def test_agent_action_contract_rejects_unknown_types_and_numeric_authority_fields():
    with pytest.raises(ValidationError):
        _valid_proposal(action_type="invented_action")
    with pytest.raises(ValidationError, match="risk_score"):
        _valid_proposal(parameters={"signal": "firm", "channel": "public", "public": True, "risk_score": 88})
    with pytest.raises(ValidationError):
        _valid_proposal(target_ids=[])
    with pytest.raises(ValidationError):
        _valid_proposal(evidence_refs=[])


def test_mock_agent_batch_is_repeatable_across_lifecycle_run_ids():
    result = _war_room_result()
    first = build_mock_agent_batch(result, run_id="job_first", seed=42, turn=1)
    second = build_mock_agent_batch(result, run_id="job_second", seed=42, turn=1)

    assert first.batch_hash == second.batch_hash
    assert [item.proposal_id for item in first.proposals] == [item.proposal_id for item in second.proposals]
    assert [item.created_at for item in first.proposals] == ["2000-01-01T00:00:01.000Z"] * 4
    for left, right in zip(first.proposals, second.proposals, strict=True):
        assert left.model_dump(exclude={"run_id"}) == right.model_dump(exclude={"run_id"})
        assert "risk_score" not in left.model_dump_json()
        assert "supply_chain_pressure" not in left.model_dump_json()


def test_mock_actions_are_audited_without_mutating_authoritative_result():
    result = _war_room_result()
    before = deepcopy(result.model_dump())
    batch = build_mock_agent_batch(result, run_id="job_mock", seed=42)

    report = evaluate_war_room_result(
        result,
        run_id="job_mock",
        proposals=batch.proposals,
        constraint_context=batch.constraint_context,
    )

    assert result.model_dump() == before
    assert report.schema_version == "consistency-audit.v2"
    assert report.summary["agent_action_count"] == 4
    assert report.summary["accepted_action_count"] == 4
    assert {decision.decision for decision in report.proposal_decisions} == {"accepted"}


def test_action_decisions_reject_unknown_targets_and_request_evidence_revision():
    result = _war_room_result()
    batch = build_mock_agent_batch(result, run_id="job_invalid", seed=42)
    unknown_target = batch.proposals[0].model_copy(update={"target_ids": ["country:UNKNOWN"]})
    unknown_evidence = batch.proposals[1].model_copy(update={"evidence_refs": ["source:missing"]})

    report = evaluate_war_room_result(
        result,
        run_id="job_invalid",
        proposals=[unknown_target, unknown_evidence],
        constraint_context=batch.constraint_context,
    )
    decisions = {item.proposal_id: item.decision for item in report.proposal_decisions}

    assert decisions[unknown_target.proposal_id] == "rejected"
    assert decisions[unknown_evidence.proposal_id] == "needs_revision"
    assert report.summary["rejected_action_count"] == 1
    assert report.summary["needs_revision_action_count"] == 1


def test_action_without_explicit_capability_context_is_not_evaluated():
    result = _war_room_result()
    proposal = _valid_proposal()
    report = evaluate_war_room_result(result, run_id="job_no_context", proposals=[proposal])

    assert report.proposal_decisions[0].decision == "not_evaluated"
    assert report.summary["not_evaluated_action_count"] == 1
