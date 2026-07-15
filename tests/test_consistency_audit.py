from copy import deepcopy

from app.core.models import WarRoomScenarioRequest
from app.services.consistency import evaluate_war_room_result
from app.services.war_room_engine import run_war_room


def _result():
    return run_war_room(WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d",
        duration_days=30,
        intensity=0.7,
        propagation=0.45,
        seed=42,
    ))


def test_consistency_audit_is_stable_and_does_not_mutate_result():
    result = _result()
    before = deepcopy(result.model_dump())

    first = evaluate_war_room_result(result, run_id="job_first", created_at="2026-07-15T00:00:00.000")
    second = evaluate_war_room_result(result, run_id="job_second", created_at="2026-07-16T00:00:00.000")

    assert result.model_dump() == before
    assert first.deterministic_result_hash == second.deterministic_result_hash
    assert first.audit_hash == second.audit_hash
    assert first.findings == second.findings
    assert first.overall_status == "warning"
    assert first.summary["read_only"] is True
    assert first.summary["agent_action_count"] == 0


def test_missing_action_and_resource_contracts_are_not_evaluated():
    report = evaluate_war_room_result(_result(), run_id="job_shadow")
    skipped = {finding.rule_id for finding in report.findings if finding.status == "not_evaluated"}

    assert "CONSISTENCY.CAPABILITY_ACTION_CONSTRAINT.V1" in skipped
    assert "CONSISTENCY.RESOURCE_BUDGET_CONSTRAINT.V1" in skipped
    assert "CONSISTENCY.STRUCTURED_EVIDENCE_REFERENCES.V1" in skipped
    assert report.skipped_rule_count >= 3


def test_numeric_and_graph_contract_violations_are_reported_without_repair():
    result = _result()
    result.risk_heatmap[0].risk = 120
    result.impact_graph.edges[0]["target"] = "country:UNKNOWN"

    report = evaluate_war_room_result(result, run_id="job_invalid")
    rules = {finding.rule_id for finding in report.findings if finding.status == "failed"}

    assert report.overall_status == "failed"
    assert "CONSISTENCY.NUMERIC_BOUNDS.V1" in rules
    assert "CONSISTENCY.REFERENTIAL_INTEGRITY.V1" in rules
    assert result.risk_heatmap[0].risk == 120
    assert result.impact_graph.edges[0]["target"] == "country:UNKNOWN"
