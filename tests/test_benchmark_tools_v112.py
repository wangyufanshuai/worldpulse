from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from app.services.evaluation.benchmark_tools import pack_labels, preflight_manifest, source_status, validate_label_payload, validate_source_plan
from app.services.evaluation.service import _agent_outcome_observation, _aggregate_agent_observations, _historical_case_metrics
from app.services.war_room.data import SUPPLY_CHAINS


def test_historical_metrics_do_not_default_missing_direction_to_up():
    baseline = next(item for item in SUPPLY_CHAINS if item.key == "energy").pressure_score
    result = {
        "country_agents": [{"code": "USA", "risk_score": 40}],
        "supply_chains": [{"key": "energy", "pressure_score": baseline}],
        "timeline": [],
    }
    metrics = _historical_case_metrics(
        result,
        {
            "risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"],
            "top3_countries": ["USA", "CHN", "JPN"],
            "supply_chain_directions": {"energy": "up"},
            "turning_points": [],
        },
        0.7,
        2,
    )
    assert metrics["supply_chain_direction_accuracy"] == 0
    assert metrics["agent_outcome_agreement"] is None
    assert metrics["data_coverage"] > 0


def test_label_contract_rejects_invalid_top3():
    with pytest.raises(HTTPException):
        validate_label_payload(
            {
                "suite_id": "historical-benchmark.v1",
                "labels": {"hist_blind_01": {"risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"], "top3_countries": ["USA", "EU", "JPN"], "supply_chain_directions": {"energy": "up"}, "turning_points": [], "label_confidence": 0.7}},
            },
            {"hist_blind_01"},
        )


def test_source_plan_requires_exact_matrix():
    with pytest.raises(HTTPException):
        validate_source_plan({"suite_id": "historical-benchmark.v1", "version": "1", "cases": []})


def test_pilot_profile_requires_two_cases_per_domain():
    cases = []
    for domain in ("strait", "energy", "food", "sanctions", "trade", "finance"):
        for index in range(2):
            cases.append(_source_case(domain, index + 1))
    result = validate_source_plan({"suite_id": "historical-benchmark.v1", "version": "1", "cases": cases}, "pilot")
    assert len(result["cases"]) == 12
    assert all(item["split"] == "development" for item in result["cases"])


def test_partial_manifest_cannot_pass_release_preflight():
    report = preflight_manifest({"cases": []}, "release")
    assert report["status"] == "failed"
    assert report["case_count"] == 0


def test_wave_profile_enforces_balanced_blind_positions():
    cases = []
    for domain in ("strait", "energy", "food", "sanctions", "trade", "finance"):
        for index in range(1, 9):
            case = _source_case(domain, index)
            case["split"] = "blind" if index in {4, 8} else "development"
            if case["split"] == "blind":
                case.pop("development_labels")
            cases.append(case)
    result = validate_source_plan(
        {"suite_id": "historical-benchmark.v1", "version": "1", "cases": cases},
        "wave",
    )
    assert len(result["cases"]) == 48
    assert sum(item["split"] == "blind" for item in result["cases"]) == 12


def test_source_plan_requires_evidence_backed_assumptions():
    cases = [
        _source_case(domain, index)
        for domain in ("strait", "energy", "food", "sanctions", "trade", "finance")
        for index in (1, 2)
    ]
    cases[0].pop("assumptions")
    with pytest.raises(HTTPException, match="contract"):
        validate_source_plan(
            {"suite_id": "historical-benchmark.v1", "version": "1", "cases": cases},
            "pilot",
        )


def test_source_status_is_incomplete_without_entries():
    result = source_status({"entries": []})
    assert result["status"] == "incomplete"
    assert result["verified_count"] == 0


def test_offline_label_pack_is_encrypted_and_signed():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    aes_key = base64.b64encode(b"x" * 32).decode("ascii")
    signer_key = base64.b64encode(private.private_bytes_raw()).decode("ascii")
    blind_ids = {f"hist_blind_{index:02d}" for index in range(30)}
    labels = {
        case_id: {
            "risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"],
            "top3_countries": ["USA", "CHN", "JPN"],
            "supply_chain_directions": {"energy": "up"},
            "turning_points": [3],
            "label_confidence": 0.7,
        }
        for case_id in blind_ids
    }
    packed = pack_labels(
        {"suite_id": "historical-benchmark.v1", "labels": labels},
        blind_ids,
        evidence_coverage_by_case={
            case_id: {
                "countries": {"USA", "CHN", "JPN", "KOR", "TWN"},
                "supply_chains": {"energy"},
            }
            for case_id in blind_ids
        },
        aes_key_b64=aes_key,
        signer_private_key_b64=signer_key,
        signer_key_id="test",
        encryption_key_id="test-aes",
        evidence_hash="e" * 64,
    )
    assert packed["case_count"] == 30
    assert packed["ciphertext_sha256"]
    assert packed["signature"]


def test_agent_observation_scores_only_projected_hybrid_actions(monkeypatch):
    artifacts = {
        "agent_action_proposals": {
            "proposals": [
                {"proposal_id": "p1", "action_type": "diplomatic_signal"},
                {"proposal_id": "p2", "action_type": "sanction_proposal"},
            ]
        },
        "agent_action_projection_audit": {
            "records": [
                {"proposal_id": "p1", "outcome": "accepted", "projection_status": "projected"},
                {"proposal_id": "p2", "outcome": "constrained", "projection_status": "constrained"},
            ]
        },
    }
    monkeypatch.setattr(
        "app.services.evaluation.service.lifecycle_repository.get_latest_artifact_content",
        lambda _run, artifact_type: artifacts.get(artifact_type),
    )
    result = _agent_outcome_observation(
        "run_test",
        "hybrid",
        {"agent_outcome_expectations": {"allowed_action_types": ["diplomatic_signal"], "forbidden_action_types": ["sanction_proposal"], "expected_commitment_patterns": []}},
    )
    assert result["score"] == 1
    assert result["actual_action_types"] == ["diplomatic_signal"]


def test_agent_observation_uses_na_for_unlabelled_components(monkeypatch):
    monkeypatch.setattr(
        "app.services.evaluation.service.lifecycle_repository.get_latest_artifact_content",
        lambda _run, _artifact_type: {"proposals": []} if _artifact_type == "agent_action_proposals" else {"records": []},
    )
    result = _agent_outcome_observation(
        "run_test",
        "hybrid",
        {"agent_outcome_expectations": {"allowed_action_types": [], "forbidden_action_types": [], "expected_commitment_patterns": []}},
    )
    assert result["score"] is None
    assert result["allowed_action_recall"] is None
    assert result["forbidden_action_pass"] is None


def test_agent_observation_aggregates_seeds_before_modes():
    rows = [
        {
            "case_id": "blind_1",
            "mode": mode,
            "seed": seed,
            "score": score,
            "allowed_action_recall": score,
            "forbidden_action_pass": 1.0,
            "commitment_pattern_match": score if mode == "negotiation" else None,
        }
        for mode in ("hybrid", "negotiation")
        for seed, score in ((11, 1.0), (29, 0.5), (47, 0.0))
    ]
    result = _aggregate_agent_observations(rows)
    assert result["case_count"] == 1
    assert result["modes"]["hybrid"]["member_count"] == 3
    assert result["modes"]["hybrid"]["score"] == 0.5
    assert len(result["case_mode_observations"]) == 2


def _source_case(domain: str, index: int) -> dict:
    scenario_key = "energy_export_cut" if domain in {"energy", "finance"} else "food_shortfall" if domain == "food" else "strait_blockade_30d"
    input_evidence_id = f"ev_{domain}_{index}_input"
    year = 2010 + index
    return {
        "case_id": f"pilot_{domain}_{index:02d}",
        "version": "historical-case.v1",
        "domain": domain,
        "split": "development",
        "title": f"{domain} pilot {index}",
        "cutoff_at": f"{year}-01-01T00:00:00Z",
        "observation_window_days": 90,
        "scenario": {
            "scenario_key": scenario_key,
            "duration_days": 30,
            "intensity": 0.45,
            "propagation": 0.3,
            "target_countries": ["USA"],
            "target_chains": ["energy"],
            "policy_actions": [],
            "country_overrides": {},
            "chain_overrides": {},
            "seed": 42,
        },
        "label_confidence": 0.7,
        "assumptions": {
            "duration_days": {
                "value": 30,
                "reason": "The official input supports a bounded thirty-day observation scenario.",
                "evidence_ids": [input_evidence_id],
                "reviewer": "benchmark-reviewer",
            },
            "intensity": {
                "value": 0.45,
                "reason": "The input describes a localized single-market disruption.",
                "evidence_ids": [input_evidence_id],
                "reviewer": "benchmark-reviewer",
            },
            "propagation": {
                "value": 0.3,
                "reason": "The input identifies one primary transmission channel.",
                "evidence_ids": [input_evidence_id],
                "reviewer": "benchmark-reviewer",
            },
        },
        "target_country_evidence": {"USA": [input_evidence_id]},
        "policy_action_evidence_ids": [],
        "development_labels": {
            "risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"],
            "top3_countries": ["USA", "CHN", "JPN"],
            "supply_chain_directions": {"energy": "up"},
            "turning_points": [30],
            "agent_outcome_expectations": {
                "allowed_action_types": ["diplomatic_signal"],
                "forbidden_action_types": ["sanction_proposal"],
                "expected_commitment_patterns": [],
            },
            "label_confidence": 0.7,
        },
        "evidence": [
            {
                "evidence_id": input_evidence_id,
                "evidence_role": "input",
                "publisher": "World Bank",
                "license_name": "CC BY 4.0",
                "license_url": "https://datacatalog.worldbank.org/public-licenses",
                "source_url": "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json",
                "observed_at": f"{year}-01-01T00:00:00Z",
                "expected_mime": "application/json",
                "locator": {
                    "coverage_countries": ["USA", "CHN", "JPN", "KOR", "TWN"],
                    "coverage_supply_chains": ["energy"],
                },
            },
            {
                "evidence_id": f"ev_{domain}_{index}_outcome",
                "evidence_role": "outcome",
                "publisher": "World Bank",
                "license_name": "CC BY 4.0",
                "license_url": "https://datacatalog.worldbank.org/public-licenses",
                "source_url": "https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.MKTP.CD?format=json",
                "observed_at": f"{year}-06-01T00:00:00Z",
                "expected_mime": "application/json",
                "locator": {
                    "coverage_countries": ["USA", "CHN", "JPN", "KOR", "TWN"],
                    "coverage_supply_chains": ["energy"],
                },
            },
        ],
    }
