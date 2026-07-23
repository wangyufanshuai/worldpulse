from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.trust_models import UserIdentity
from app.services.evaluation.pilot_curation import (
    finalize_pilot_dossier,
    prepare_pilot_dossier,
    validate_pilot_dossier,
)
from app.services.evaluation.pilot_review import (
    apply_pilot_review,
    export_pilot_review,
    validate_pilot_review,
)


DOMAINS = ("strait", "energy", "food", "sanctions", "trade", "finance")


def test_tracked_pilot_dossier_is_real_unapproved_candidate_matrix():
    path = Path("benchmarks/historical-benchmark.v1/work/pilot-curation-dossier.json")
    dossier = prepare_pilot_dossier(json.loads(path.read_text(encoding="utf-8")))
    evidence = [item for case in dossier["cases"] for item in case["evidence"]]
    assert len(dossier["cases"]) == 12
    assert len(evidence) == 24
    assert len({item["evidence_id"] for item in evidence}) == 24
    assert len({item["source_url"] for item in evidence}) == 24
    assert all(case["split"] == "development" for case in dossier["cases"])
    assert all(case["label_review"] is None and case["label_confidence"] is None for case in dossier["cases"])
    assert all(item["rights_decision"] is None for item in evidence)
    assert not any("unctad.org" in item["source_url"] or "wto.org" in item["source_url"] for item in evidence)


def test_prepare_pilot_requires_twelve_cases_and_twenty_four_sources():
    payload = _candidate_payload()
    for case in payload["cases"]:
        case["label_confidence"] = None
    dossier = prepare_pilot_dossier(payload)
    assert dossier["status"] == "draft"
    assert dossier["cases"][0]["label_confidence"] is None
    assert len(dossier["cases"]) == 12
    assert len({item["source_url"] for case in dossier["cases"] for item in case["evidence"]}) == 24
    assert len(dossier["dossier_hash"]) == 64


def test_finalize_pilot_binds_real_reviewer_identity():
    draft = prepare_pilot_dossier(_candidate_payload())
    reviewed = _approve(draft)
    normalized = validate_pilot_dossier(reviewed, require_review=True)
    reviewer = UserIdentity(
        user_id="usr_reviewer",
        username="benchmark-reviewer",
        display_name="Benchmark Reviewer",
        role="reviewer",
    )
    plan = finalize_pilot_dossier(normalized, reviewer)
    assert plan["curation_profile"] == "pilot"
    assert plan["curation_dossier_hash"] == normalized["dossier_hash"]
    assert plan["reviewer"]["user_id"] == "usr_reviewer"
    rights = plan["cases"][0]["evidence"][0]["rights_review"]
    assert rights["reviewed_by_user_id"] == "usr_reviewer"
    assert rights["reviewer_role"] == "reviewer"


def test_finalize_pilot_rejects_admin_or_wrong_reviewer_name():
    dossier = validate_pilot_dossier(_approve(prepare_pilot_dossier(_candidate_payload())), require_review=True)
    with pytest.raises(HTTPException, match="benchmark-reviewer"):
        finalize_pilot_dossier(
            dossier,
            UserIdentity(user_id="usr_admin", username="release-admin", display_name="Admin", role="admin"),
        )


def test_reviewed_dossier_hash_detects_changes():
    dossier = validate_pilot_dossier(_approve(prepare_pilot_dossier(_candidate_payload())), require_review=True)
    dossier["cases"][0]["evidence"][0]["rights_decision"]["decision_basis"] = "Tampered after review and before finalization."
    reviewer = UserIdentity(
        user_id="usr_reviewer",
        username="benchmark-reviewer",
        display_name="Benchmark Reviewer",
        role="reviewer",
    )
    with pytest.raises(HTTPException, match="dossier hash mismatch"):
        finalize_pilot_dossier(dossier, reviewer)


def test_review_rejects_missing_label_or_third_party_exception():
    draft = prepare_pilot_dossier(_candidate_payload())
    reviewed = _approve(draft)
    reviewed["cases"][0]["evidence"][0]["rights_decision"]["third_party_exception"] = "unknown"
    with pytest.raises(HTTPException, match="rights decision"):
        validate_pilot_dossier(reviewed, require_review=True)


def test_prepare_rejects_duplicate_source_url():
    payload = _candidate_payload()
    payload["cases"][1]["evidence"][0]["source_url"] = payload["cases"][0]["evidence"][0]["source_url"]
    with pytest.raises(HTTPException, match="source URLs"):
        prepare_pilot_dossier(payload)


def test_offline_review_worksheet_applies_atomically_and_binds_source_plan():
    draft = prepare_pilot_dossier(_candidate_payload())
    worksheet = validate_pilot_review(_complete_worksheet(export_pilot_review(draft)), draft)
    assert worksheet["status"] == "ready"
    assert worksheet["validation"]["evidence_approved"] == 24
    assert worksheet["validation"]["case_approved"] == 12
    reviewer = _reviewer()
    reviewed = apply_pilot_review(draft, worksheet, reviewer)
    assert reviewed["status"] == "review_ready"
    assert reviewed["reviewer"]["user_id"] == reviewer.user_id
    assert reviewed["review_worksheet_hash"] == worksheet["worksheet_hash"]
    plan = finalize_pilot_dossier(reviewed, reviewer)
    assert plan["review_worksheet_hash"] == worksheet["worksheet_hash"]
    assert plan["reviewer"]["user_id"] == reviewer.user_id


def test_offline_review_worksheet_rejects_stale_dossier_and_tampered_binding():
    draft = prepare_pilot_dossier(_candidate_payload())
    worksheet = export_pilot_review(draft)
    changed = deepcopy(draft)
    changed["cases"][0]["scenario"]["seed"] = 77
    changed.pop("dossier_hash")
    changed = prepare_pilot_dossier(changed)
    with pytest.raises(HTTPException, match="dossier hash mismatch"):
        validate_pilot_review(worksheet, changed)
    tampered = deepcopy(worksheet)
    tampered["evidence_reviews"][0]["source_url_hash"] = "0" * 64
    with pytest.raises(HTTPException, match="URL changed"):
        validate_pilot_review(tampered, draft)


def test_offline_review_worksheet_blocks_revision_and_missing_decisions():
    draft = prepare_pilot_dossier(_candidate_payload())
    partial = export_pilot_review(draft)
    normalized = validate_pilot_review(partial, draft)
    assert normalized["status"] == "draft"
    with pytest.raises(HTTPException, match="missing decisions"):
        validate_pilot_review(normalized, draft, require_complete=True, verify_hash=True)
    blocked = _complete_worksheet(export_pilot_review(draft))
    blocked["evidence_reviews"][0].update({
        "decision": "request_revision",
        "third_party_exception": "unknown",
        "decision_basis": "The item requires a separate human review of third-party material.",
    })
    blocked = validate_pilot_review(blocked, draft)
    assert blocked["status"] == "blocked"
    with pytest.raises(HTTPException, match="blocked by request_revision"):
        apply_pilot_review(draft, blocked, _reviewer())


def test_offline_review_worksheet_requires_exact_reviewer_and_hash():
    draft = prepare_pilot_dossier(_candidate_payload())
    worksheet = validate_pilot_review(_complete_worksheet(export_pilot_review(draft)), draft)
    tampered = deepcopy(worksheet)
    tampered["case_reviews"][0]["decision_basis"] += " changed"
    with pytest.raises(HTTPException, match="worksheet hash mismatch"):
        apply_pilot_review(draft, tampered, _reviewer())
    with pytest.raises(HTTPException, match="benchmark-reviewer"):
        apply_pilot_review(
            draft,
            worksheet,
            UserIdentity(user_id="usr_admin", username="release-admin", display_name="Admin", role="admin"),
        )


def _approve(draft: dict) -> dict:
    reviewed = deepcopy(draft)
    reviewed["status"] = "review_ready"
    for case in reviewed["cases"]:
        for item in case["evidence"]:
            item["rights_decision"] = {
                "decision": "approved",
                "third_party_exception": "none_identified",
                "decision_basis": "The item-level official license permits local archival and evaluation.",
            }
        case["label_review"] = {
            "decision": "approved",
            "assumption_reasons": {
                "duration_days": "The input evidence supports a bounded thirty-day scenario window.",
                "intensity": "The official input describes a localized single-market disruption.",
                "propagation": "The official input identifies one primary transmission channel.",
            },
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
                "coverage_countries": ["USA", "CHN", "JPN", "KOR", "TWN"],
                "coverage_supply_chains": ["energy"],
                "label_confidence": 0.7,
            },
        }
    reviewed.pop("dossier_hash", None)
    return reviewed


def _complete_worksheet(worksheet: dict) -> dict:
    completed = deepcopy(worksheet)
    for item in completed["evidence_reviews"]:
        item.update({
            "decision": "approved",
            "third_party_exception": "none_identified",
            "decision_basis": "The official item-level license permits local archival and evaluation.",
        })
    for item in completed["case_reviews"]:
        item.update({
            "decision": "approved",
            "decision_basis": "The official evidence supports the scenario assumptions and labels recorded here.",
            "assumption_reasons": {
                "duration_days": "The input evidence supports a bounded thirty-day scenario window.",
                "intensity": "The official input describes a localized single-market disruption.",
                "propagation": "The official input identifies one primary transmission channel.",
            },
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
                "coverage_countries": ["USA", "CHN", "JPN", "KOR", "TWN"],
                "coverage_supply_chains": ["energy"],
            },
            "label_confidence": 0.7,
        })
    return completed


def _reviewer() -> UserIdentity:
    return UserIdentity(
        user_id="usr_reviewer",
        username="benchmark-reviewer",
        display_name="Benchmark Reviewer",
        role="reviewer",
    )


def _candidate_payload() -> dict:
    cases = []
    for domain in DOMAINS:
        for index in (1, 2):
            year = 2010 + index
            input_id = f"ev_{domain}_{index}_input"
            cases.append({
                "case_id": f"pilot_{domain}_{index:02d}",
                "domain": domain,
                "split": "development",
                "title": f"{domain} governed pilot {index}",
                "cutoff_at": f"{year}-01-01T00:00:00Z",
                "observation_window_days": 90,
                "scenario": {
                    "scenario_key": "energy_export_cut" if domain in {"energy", "finance"} else "food_shortfall" if domain == "food" else "strait_blockade_30d",
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
                "target_country_evidence": {"USA": [input_id]},
                "policy_action_evidence_ids": [],
                "label_review": None,
                "evidence": [
                    _evidence(domain, index, "input", f"{year - 1}-12-01T00:00:00Z"),
                    _evidence(domain, index, "outcome", f"{year}-02-01T00:00:00Z"),
                ],
            })
    return {
        "version": "pilot-curation-dossier.v1",
        "suite_id": "historical-benchmark.v1",
        "profile": "pilot",
        "status": "draft",
        "cases": cases,
    }


def _evidence(domain: str, index: int, role: str, published_at: str) -> dict:
    suffix = f"{domain}-{index}-{role}"
    return {
        "evidence_id": f"ev_{domain}_{index}_{role}",
        "evidence_role": role,
        "publisher": "World Bank",
        "title": f"Versioned official {suffix}",
        "source_kind": "versioned_file",
        "version_label": f"release-{suffix}",
        "source_url": f"https://documents.worldbank.org/{suffix}.pdf",
        "published_at": published_at,
        "expected_mime": "application/pdf",
        "license_name": "CC BY 4.0",
        "license_url": "https://datacatalog.worldbank.org/public-licenses",
        "locator": {
            "location": "table 1",
            "coverage_countries": ["USA", "CHN", "JPN", "KOR", "TWN"],
            "coverage_supply_chains": ["energy"],
        },
        "rights_decision": None,
    }
