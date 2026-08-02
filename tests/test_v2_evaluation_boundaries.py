from __future__ import annotations

from app.services.evaluation.metrics import historical_case_metrics
from app.services.evaluation.observation import agent_outcome_observation
from app.services.evaluation.service import _agent_outcome_observation, _historical_case_metrics


def test_evaluation_metrics_have_a_stable_public_module_boundary():
    assert _historical_case_metrics is historical_case_metrics

    result = historical_case_metrics(
        {
            "country_agents": [{"code": "USA", "risk_score": 80}, {"code": "CHN", "risk_score": 40}],
            "supply_chains": [{"key": "energy", "direction": "up"}],
            "timeline": [{"day": 30, "turning_point": True}],
        },
        {
            "risk_ranking": ["USA", "CHN"],
            "top3_countries": ["USA", "CHN"],
            "supply_chain_directions": {"energy": "up"},
            "turning_points": [30],
        },
        0.8,
        2,
    )

    assert result["risk_spearman"] == 1.0
    assert result["supply_chain_direction_accuracy"] == 1.0
    assert result["agent_outcome_agreement"] is None


def test_observation_reads_only_projected_artifacts():
    artifacts = {
        ("run-1", "agent_action_proposals"): {
            "proposals": [
                {"proposal_id": "p1", "action_type": "diplomatic_signal"},
                {"proposal_id": "p2", "action_type": "sanction_proposal"},
            ]
        },
        ("run-1", "agent_action_projection_audit"): {
            "records": [
                {"proposal_id": "p1", "outcome": "accepted", "projection_status": "projected"},
                {"proposal_id": "p2", "outcome": "accepted", "projection_status": "rejected"},
            ]
        },
    }

    observation = agent_outcome_observation(
        "run-1",
        "hybrid",
        {
            "agent_outcome_expectations": {
                "allowed_action_types": ["diplomatic_signal"],
                "forbidden_action_types": ["sanction_proposal"],
            }
        },
        artifact_reader=lambda run_id, artifact_type: artifacts.get((run_id, artifact_type)),
    )

    assert observation["actual_action_types"] == ["diplomatic_signal"]
    assert observation["allowed_action_recall"] == 1.0
    assert observation["forbidden_action_pass"] == 1.0
    assert _agent_outcome_observation is agent_outcome_observation
