from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.core.trust_models import UserIdentity
from app.services.consistency.hashing import stable_hash

from .benchmark_contracts import evidence_coverage, validate_label
from .pilot_curation import validate_pilot_dossier


WORKSHEET_VERSION = "pilot-review-worksheet.v1"


def export_pilot_review(dossier_payload: dict[str, Any]) -> dict[str, Any]:
    dossier = validate_pilot_dossier(dossier_payload, require_review=False, verify_hash=True)
    if dossier["status"] != "draft":
        raise HTTPException(status_code=409, detail="Pilot review worksheet can only be exported from a draft dossier")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    worksheet = {
        "version": WORKSHEET_VERSION,
        "dossier_hash": dossier["dossier_hash"],
        "generated_at": generated_at,
        "status": "draft",
        "evidence_reviews": [
            {
                **_evidence_identity(item),
                "decision": None,
                "third_party_exception": None,
                "decision_basis": "",
            }
            for case in dossier["cases"]
            for item in case["evidence"]
        ],
        "case_reviews": [
            {
                **_case_identity(case),
                "decision": None,
                "decision_basis": "",
                "assumption_reasons": {
                    "duration_days": "",
                    "intensity": "",
                    "propagation": "",
                },
                "development_labels": {},
                "label_confidence": None,
            }
            for case in dossier["cases"]
        ],
    }
    return validate_pilot_review(worksheet, dossier, verify_hash=False)


def validate_pilot_review(
    worksheet_payload: dict[str, Any],
    dossier_payload: dict[str, Any],
    *,
    require_complete: bool = False,
    verify_hash: bool = False,
) -> dict[str, Any]:
    dossier = validate_pilot_dossier(dossier_payload, require_review=False, verify_hash=True)
    if dossier["status"] != "draft":
        raise HTTPException(status_code=409, detail="Pilot review worksheet requires the original draft dossier")
    if worksheet_payload.get("version") != WORKSHEET_VERSION:
        raise HTTPException(status_code=422, detail="Pilot review worksheet version is invalid")
    if worksheet_payload.get("dossier_hash") != dossier["dossier_hash"]:
        raise HTTPException(status_code=409, detail="Pilot review worksheet dossier hash mismatch")

    expected_evidence = {
        item["evidence_id"]: (case, item)
        for case in dossier["cases"]
        for item in case["evidence"]
    }
    expected_cases = {case["case_id"]: case for case in dossier["cases"]}
    evidence_payloads = _index_reviews(worksheet_payload.get("evidence_reviews"), "evidence_id", "Evidence")
    case_payloads = _index_reviews(worksheet_payload.get("case_reviews"), "case_id", "case")
    if set(evidence_payloads) != set(expected_evidence) or len(evidence_payloads) != 24:
        raise HTTPException(status_code=409, detail="Pilot review worksheet must bind all 24 Evidence items")
    if set(case_payloads) != set(expected_cases) or len(case_payloads) != 12:
        raise HTTPException(status_code=409, detail="Pilot review worksheet must bind all 12 cases")

    evidence_reviews = [
        _normalize_evidence_review(evidence_payloads[item_id], expected_evidence[item_id][1])
        for item_id in expected_evidence
    ]
    case_reviews = [
        _normalize_case_review(case_payloads[case_id], expected_cases[case_id])
        for case_id in expected_cases
    ]
    decisions = [item["decision"] for item in evidence_reviews + case_reviews]
    revision_requested = decisions.count("request_revision")
    missing_decisions = decisions.count(None)
    status = "blocked" if revision_requested else "draft" if missing_decisions else "ready"
    if require_complete and missing_decisions:
        raise HTTPException(status_code=422, detail="Pilot review worksheet has missing decisions")
    if require_complete and revision_requested:
        raise HTTPException(status_code=409, detail="Pilot review worksheet is blocked by request_revision")

    normalized = {
        "version": WORKSHEET_VERSION,
        "dossier_hash": dossier["dossier_hash"],
        "generated_at": str(worksheet_payload.get("generated_at") or ""),
        "status": status,
        "evidence_reviews": evidence_reviews,
        "case_reviews": case_reviews,
        "validation": {
            "status": status,
            "evidence_total": len(evidence_reviews),
            "evidence_approved": sum(item["decision"] == "approved" for item in evidence_reviews),
            "case_total": len(case_reviews),
            "case_approved": sum(item["decision"] == "approved" for item in case_reviews),
            "revision_requested": revision_requested,
            "missing_decisions": missing_decisions,
            "worksheet_hash": "",
        },
    }
    if not normalized["generated_at"]:
        raise HTTPException(status_code=422, detail="Pilot review worksheet generation time is required")
    expected_hash = _worksheet_hash(normalized)
    if verify_hash and (
        worksheet_payload.get("worksheet_hash") != expected_hash
        or (worksheet_payload.get("validation") or {}).get("worksheet_hash") != expected_hash
    ):
        raise HTTPException(status_code=409, detail="Pilot review worksheet hash mismatch")
    normalized["worksheet_hash"] = expected_hash
    normalized["validation"]["worksheet_hash"] = expected_hash
    return normalized


def apply_pilot_review(
    dossier_payload: dict[str, Any],
    worksheet_payload: dict[str, Any],
    reviewer: UserIdentity,
) -> dict[str, Any]:
    if reviewer.role != "reviewer" or reviewer.username != "benchmark-reviewer":
        raise HTTPException(status_code=403, detail="Pilot review requires the benchmark-reviewer account")
    dossier = validate_pilot_dossier(dossier_payload, require_review=False, verify_hash=True)
    if dossier["status"] != "draft":
        raise HTTPException(status_code=409, detail="Pilot review can only be applied once to a draft dossier")
    worksheet = validate_pilot_review(
        worksheet_payload,
        dossier,
        require_complete=True,
        verify_hash=True,
    )
    evidence_reviews = {item["evidence_id"]: item for item in worksheet["evidence_reviews"]}
    case_reviews = {item["case_id"]: item for item in worksheet["case_reviews"]}
    reviewed = deepcopy(dossier)
    reviewed.pop("dossier_hash", None)
    reviewed["status"] = "review_ready"
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    reviewed["reviewer"] = {
        "user_id": reviewer.user_id,
        "username": reviewer.username,
        "role": reviewer.role,
        "reviewed_at": reviewed_at,
    }
    reviewed["review_worksheet_hash"] = worksheet["worksheet_hash"]
    for case in reviewed["cases"]:
        case_review = case_reviews[case["case_id"]]
        case["label_confidence"] = case_review["label_confidence"]
        case["label_review"] = {
            "decision": "approved",
            "decision_basis": case_review["decision_basis"],
            "assumption_reasons": case_review["assumption_reasons"],
            "development_labels": case_review["development_labels"],
        }
        for item in case["evidence"]:
            evidence_review = evidence_reviews[item["evidence_id"]]
            item["rights_decision"] = {
                "decision": "approved",
                "third_party_exception": "none_identified",
                "decision_basis": evidence_review["decision_basis"],
            }
    return validate_pilot_dossier(reviewed, require_review=True, verify_hash=False)


def _normalize_evidence_review(review: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    expected = _evidence_identity(evidence)
    if review.get("evidence_contract_hash") != expected["evidence_contract_hash"]:
        raise HTTPException(status_code=409, detail=f"Pilot Evidence contract changed: {evidence['evidence_id']}")
    if review.get("source_url_hash") != expected["source_url_hash"]:
        raise HTTPException(status_code=409, detail=f"Pilot Evidence URL changed: {evidence['evidence_id']}")
    decision = review.get("decision")
    if decision not in {None, "approved", "request_revision"}:
        raise HTTPException(status_code=422, detail="Pilot Evidence review decision is invalid")
    basis = str(review.get("decision_basis") or "").strip()
    exception = review.get("third_party_exception")
    if decision is not None and len(basis) < 20:
        raise HTTPException(status_code=422, detail="Pilot Evidence review basis must contain at least 20 characters")
    if decision == "approved" and exception != "none_identified":
        raise HTTPException(status_code=422, detail="Approved Pilot Evidence cannot contain a third-party exception")
    if decision == "request_revision" and exception not in {"none_identified", "present", "unknown"}:
        raise HTTPException(status_code=422, detail="Pilot Evidence exception status is invalid")
    if decision is None:
        exception = None
        basis = ""
    return {**expected, "decision": decision, "third_party_exception": exception, "decision_basis": basis}


def _normalize_case_review(review: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    expected = _case_identity(case)
    if review.get("scenario_hash") != expected["scenario_hash"]:
        raise HTTPException(status_code=409, detail=f"Pilot case scenario changed: {case['case_id']}")
    decision = review.get("decision")
    if decision not in {None, "approved", "request_revision"}:
        raise HTTPException(status_code=422, detail="Pilot case review decision is invalid")
    basis = str(review.get("decision_basis") or "").strip()
    reasons = review.get("assumption_reasons") if isinstance(review.get("assumption_reasons"), dict) else {}
    labels = review.get("development_labels") if isinstance(review.get("development_labels"), dict) else {}
    confidence = review.get("label_confidence")
    if decision is not None and len(basis) < 20:
        raise HTTPException(status_code=422, detail="Pilot case review basis must contain at least 20 characters")
    if decision == "approved":
        if any(len(str(reasons.get(key) or "").strip()) < 20 for key in ("duration_days", "intensity", "propagation")):
            raise HTTPException(status_code=422, detail="Pilot case assumption review is incomplete")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Pilot case label confidence is required") from exc
        labels = validate_label(
            {**labels, "label_confidence": confidence},
            observation_window_days=int(case["observation_window_days"]),
            evidence_coverage=evidence_coverage(case["evidence"]),
        )
    elif decision is None:
        basis = ""
        confidence = None
        labels = {}
    return {
        **expected,
        "decision": decision,
        "decision_basis": basis,
        "assumption_reasons": {key: str(reasons.get(key) or "").strip() for key in ("duration_days", "intensity", "propagation")},
        "development_labels": labels,
        "label_confidence": confidence,
    }


def _evidence_identity(evidence: dict[str, Any]) -> dict[str, Any]:
    contract = {key: value for key, value in evidence.items() if key != "rights_decision"}
    return {
        "evidence_id": evidence["evidence_id"],
        "evidence_contract_hash": stable_hash(contract),
        "source_url_hash": stable_hash(evidence["source_url"]),
        "title": evidence["title"],
        "publisher": evidence["publisher"],
        "source_url": evidence["source_url"],
        "license_name": evidence["license_name"],
        "license_url": evidence["license_url"],
        "locator": evidence["locator"],
    }


def _case_identity(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "scenario_hash": stable_hash(case["scenario"]),
        "scenario_assumptions": {
            key: case["scenario"][key]
            for key in ("duration_days", "intensity", "propagation")
        },
    }


def _index_reviews(payload: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise HTTPException(status_code=422, detail=f"Pilot {label} reviews must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict) or not str(item.get(key) or ""):
            raise HTTPException(status_code=422, detail=f"Pilot {label} review identity is invalid")
        identifier = str(item[key])
        if identifier in indexed:
            raise HTTPException(status_code=409, detail=f"Pilot {label} review is duplicated: {identifier}")
        indexed[identifier] = item
    return indexed


def _worksheet_hash(worksheet: dict[str, Any]) -> str:
    body = deepcopy(worksheet)
    body.pop("worksheet_hash", None)
    if isinstance(body.get("validation"), dict):
        body["validation"].pop("worksheet_hash", None)
    return stable_hash(body)
