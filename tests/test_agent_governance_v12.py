from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract import AgentActionProposal, build_mock_agent_batch
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.war_room_engine import run_war_room


def _fixture():
    result = run_war_room(WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d",
        duration_days=30,
        intensity=0.7,
        propagation=0.45,
        seed=42,
    ))
    batch = build_mock_agent_batch(result, run_id="job_v12", seed=42)
    return result, batch


def test_v12_action_audit_records_hash_rule_and_projection_defaults():
    result, batch = _fixture()
    report = evaluate_war_room_result(
        result,
        run_id="job_v12",
        proposals=batch.proposals,
        constraint_context=batch.constraint_context,
    )

    assert report.summary["action_audit_rule_version"] == "worldpulse-consistency.v1.2"
    assert report.summary["action_audit_count"] == len(batch.proposals)
    assert report.summary["action_pass_rate"] == 1.0
    proposals = {proposal.proposal_id: proposal for proposal in batch.proposals}
    for decision in report.proposal_decisions:
        proposal = proposals[decision.proposal_id]
        assert decision.input_hash == stable_hash(proposal.model_dump(mode="json"))
        assert decision.rule_version == "worldpulse-consistency.v1.2"
        assert decision.outcome == "accepted"
        assert decision.projection_status == "not_projected"
        assert decision.rejection_reason is None


def test_v12_supports_constrained_and_expired_without_authority_mutation():
    result, batch = _fixture()
    constrained = batch.proposals[0].model_copy(update={"evidence_refs": ["source:missing"]})
    expired = batch.proposals[1].model_copy(update={"expires_after_turn": 0})
    report = evaluate_war_room_result(
        result,
        run_id="job_v12_statuses",
        proposals=[constrained, expired],
        constraint_context=batch.constraint_context,
    )

    by_id = {item.proposal_id: item for item in report.proposal_decisions}
    assert by_id[constrained.proposal_id].decision == "needs_revision"
    assert by_id[constrained.proposal_id].outcome == "constrained"
    assert by_id[constrained.proposal_id].rejection_reason == "CONSISTENCY.ACTION_EVIDENCE.V1"
    assert by_id[expired.proposal_id].decision == "not_evaluated"
    assert by_id[expired.proposal_id].outcome == "expired"
    assert by_id[expired.proposal_id].rejection_reason == "proposal_expired"
    assert report.summary["constrained_action_count"] == 1
    assert report.summary["expired_action_count"] == 1
    assert report.summary["action_pass_rate"] == 0.0


def test_v12_proposal_expiry_field_is_optional_and_serializable():
    result, batch = _fixture()
    payload = batch.proposals[0].model_dump(mode="json")
    payload["expires_after_turn"] = 4
    proposal = AgentActionProposal(**payload)
    assert proposal.expires_after_turn == 4
    assert proposal.model_dump(mode="json")["expires_after_turn"] == 4
