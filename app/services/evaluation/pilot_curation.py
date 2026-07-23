from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.core.models import WarRoomScenarioRequest
from app.core.trust_models import UserIdentity
from app.services.consistency.hashing import stable_hash
from app.services.continuous_intelligence.feed import validate_remote_url
from app.services.war_room.data import POLICY_ACTIONS

from . import benchmark
from .benchmark_rights import ARCHIVABLE_LICENSES
from .benchmark_tools import (
    ALLOWED_DOMAINS,
    ALLOWED_MIME,
    CHAIN_KEYS,
    COUNTRY_CODES,
    _evidence_coverage,
    _parse_date,
    _validate_domain_matrix,
    _validate_label,
    validate_source_plan,
)


DOSSIER_VERSION = "pilot-curation-dossier.v1"


def prepare_pilot_dossier(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_dossier(payload, require_review=False)
    normalized["status"] = "draft"
    normalized["dossier_hash"] = _dossier_hash(normalized)
    return normalized


def validate_pilot_dossier(
    payload: dict[str, Any],
    *,
    require_review: bool = False,
    verify_hash: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_dossier(payload, require_review=require_review)
    normalized["status"] = "review_ready" if require_review else str(payload.get("status") or "draft")
    expected = _dossier_hash(normalized)
    if verify_hash and payload.get("dossier_hash") != expected:
        raise HTTPException(status_code=409, detail="Pilot curation dossier hash mismatch")
    normalized["dossier_hash"] = expected
    return normalized


def finalize_pilot_dossier(payload: dict[str, Any], reviewer: UserIdentity) -> dict[str, Any]:
    if reviewer.role != "reviewer" or reviewer.username != "benchmark-reviewer":
        raise HTTPException(status_code=403, detail="Pilot dossier requires the benchmark-reviewer account")
    dossier = validate_pilot_dossier(payload, require_review=True, verify_hash=True)
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    cases: list[dict[str, Any]] = []
    for case in dossier["cases"]:
        reasons = case["label_review"]["assumption_reasons"]
        evidence = []
        for item in case["evidence"]:
            decision = item["rights_decision"]
            evidence.append({
                "evidence_id": item["evidence_id"],
                "evidence_role": item["evidence_role"],
                "publisher": item["publisher"],
                "license_name": item["license_name"],
                "license_url": item["license_url"],
                "source_url": item["source_url"],
                "observed_at": item["published_at"],
                "expected_mime": item["expected_mime"],
                "locator": item["locator"],
                "rights_review": {
                    "decision": "approved",
                    "reviewed_by": reviewer.username,
                    "reviewed_by_user_id": reviewer.user_id,
                    "reviewer_role": reviewer.role,
                    "reviewed_at": reviewed_at,
                    "scope": "local_archive_and_evaluation",
                    "decision_basis": decision["decision_basis"],
                },
            })
        input_ids = [item["evidence_id"] for item in evidence if item["evidence_role"] == "input"]
        assumptions = {
            key: {
                "value": case["scenario"][key],
                "reason": reasons[key],
                "evidence_ids": input_ids,
                "reviewer": reviewer.username,
            }
            for key in ("duration_days", "intensity", "propagation")
        }
        cases.append({
            "case_id": case["case_id"],
            "version": "historical-case.v1",
            "domain": case["domain"],
            "split": "development",
            "title": case["title"],
            "cutoff_at": case["cutoff_at"],
            "observation_window_days": case["observation_window_days"],
            "scenario": case["scenario"],
            "label_confidence": case["label_confidence"],
            "assumptions": assumptions,
            "target_country_evidence": case["target_country_evidence"],
            "policy_action_evidence_ids": case["policy_action_evidence_ids"],
            "development_labels": case["label_review"]["development_labels"],
            "evidence": evidence,
        })
    plan = validate_source_plan({
        "suite_id": "historical-benchmark.v1",
        "version": "1",
        "purpose": "governed open-license 12-case historical pilot",
        "curation_dossier_hash": dossier["dossier_hash"],
        "reviewer": {
            "user_id": reviewer.user_id,
            "username": reviewer.username,
            "role": reviewer.role,
            "reviewed_at": reviewed_at,
        },
        "cases": cases,
    }, "pilot")
    if len({item["source_url"] for case in plan["cases"] for item in case["evidence"]}) != 24:
        raise HTTPException(status_code=409, detail="Pilot requires 24 distinct versioned source URLs")
    return plan


def _normalize_dossier(payload: dict[str, Any], *, require_review: bool) -> dict[str, Any]:
    if payload.get("version") != DOSSIER_VERSION or payload.get("suite_id") != "historical-benchmark.v1":
        raise HTTPException(status_code=422, detail="Pilot curation dossier identity is invalid")
    if payload.get("profile") != "pilot":
        raise HTTPException(status_code=422, detail="Pilot curation dossier profile is invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise HTTPException(status_code=422, detail="Pilot curation dossier cases are required")
    _validate_domain_matrix(cases, "pilot")
    evidence_ids: set[str] = set()
    source_urls: set[str] = set()
    normalized_cases = [
        _normalize_case(item, evidence_ids, source_urls, require_review=require_review)
        for item in cases
    ]
    if len(evidence_ids) != 24 or len(source_urls) != 24:
        raise HTTPException(status_code=422, detail="Pilot dossier requires 24 distinct Evidence IDs and source URLs")
    return {
        "version": DOSSIER_VERSION,
        "suite_id": "historical-benchmark.v1",
        "profile": "pilot",
        "status": str(payload.get("status") or "draft"),
        "source_strategy": "open-license-first",
        "prepared_at": str(payload.get("prepared_at") or datetime.now(timezone.utc).isoformat(timespec="milliseconds")),
        "cases": normalized_cases,
    }


def _normalize_case(
    case: dict[str, Any],
    evidence_ids: set[str],
    source_urls: set[str],
    *,
    require_review: bool,
) -> dict[str, Any]:
    required = {
        "case_id", "domain", "split", "title", "cutoff_at", "observation_window_days",
        "scenario", "label_confidence", "target_country_evidence", "policy_action_evidence_ids",
        "evidence",
    }
    if not required.issubset(case) or case.get("split") != "development" or case.get("domain") not in ALLOWED_DOMAINS:
        raise HTTPException(status_code=422, detail="Pilot case contract is invalid")
    cutoff = _parse_date(case["cutoff_at"])
    observation_days = int(case["observation_window_days"])
    if cutoff.year < 2010 or cutoff.year > 2025 or cutoff.timestamp() + observation_days * 86400 > datetime.now(timezone.utc).timestamp():
        raise HTTPException(status_code=409, detail=f"Pilot case window is invalid: {case['case_id']}")
    scenario = dict(case["scenario"])
    if scenario.get("country_overrides") or scenario.get("chain_overrides"):
        raise HTTPException(status_code=422, detail="Pilot scenarios cannot contain overrides")
    if (
        scenario.get("duration_days") not in {30, 45, 60, 90}
        or scenario.get("intensity") not in {0.45, 0.65, 0.82}
        or scenario.get("propagation") not in {0.3, 0.45, 0.6}
        or not set(scenario.get("target_countries", [])).issubset(COUNTRY_CODES)
        or not set(scenario.get("target_chains", [])).issubset(CHAIN_KEYS)
        or set(scenario.get("policy_actions", [])).difference(POLICY_ACTIONS)
    ):
        raise HTTPException(status_code=422, detail=f"Pilot scenario rubric is invalid: {case['case_id']}")
    WarRoomScenarioRequest.model_validate(scenario)
    raw_evidence = case.get("evidence")
    if not isinstance(raw_evidence, list) or len(raw_evidence) != 2 or {item.get("evidence_role") for item in raw_evidence} != {"input", "outcome"}:
        raise HTTPException(status_code=422, detail="Pilot cases require one input and one outcome Evidence")
    evidence = [
        _normalize_evidence(item, cutoff, evidence_ids, source_urls, require_review=require_review)
        for item in raw_evidence
    ]
    input_ids = {item["evidence_id"] for item in evidence if item["evidence_role"] == "input"}
    target_map = case["target_country_evidence"]
    if not isinstance(target_map, dict) or set(target_map) != set(scenario.get("target_countries", [])):
        raise HTTPException(status_code=422, detail="Pilot target countries require input Evidence")
    if any(not set(ids).issubset(input_ids) or not ids for ids in target_map.values()):
        raise HTTPException(status_code=422, detail="Pilot target country Evidence is invalid")
    policy_ids = case["policy_action_evidence_ids"]
    if not isinstance(policy_ids, list) or not set(policy_ids).issubset(input_ids):
        raise HTTPException(status_code=422, detail="Pilot policy Evidence is invalid")
    if scenario.get("policy_actions") and not policy_ids:
        raise HTTPException(status_code=422, detail="Pilot policy actions require input Evidence")
    label_review = case.get("label_review")
    label_confidence = case.get("label_confidence")
    if require_review:
        if not isinstance(label_review, dict) or label_review.get("decision") != "approved":
            raise HTTPException(status_code=409, detail="Pilot case label review is not approved")
        reasons = label_review.get("assumption_reasons")
        if not isinstance(reasons, dict) or any(len(str(reasons.get(key) or "").strip()) < 20 for key in ("duration_days", "intensity", "propagation")):
            raise HTTPException(status_code=422, detail="Pilot scenario assumption review is incomplete")
        labels = _validate_label(
            label_review.get("development_labels"),
            observation_window_days=observation_days,
            evidence_coverage=_evidence_coverage(evidence),
        )
        try:
            label_confidence = float(label_confidence)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Pilot label confidence is required") from exc
        if not 0 <= label_confidence <= 1:
            raise HTTPException(status_code=422, detail="Pilot label confidence is invalid")
        label_review = {"decision": "approved", "assumption_reasons": reasons, "development_labels": labels}
    return {
        "case_id": str(case["case_id"]),
        "domain": case["domain"],
        "split": "development",
        "title": str(case["title"]),
        "cutoff_at": cutoff.isoformat(),
        "observation_window_days": observation_days,
        "scenario": scenario,
        "label_confidence": label_confidence,
        "target_country_evidence": target_map,
        "policy_action_evidence_ids": policy_ids,
        "evidence": evidence,
        "label_review": label_review,
    }


def _normalize_evidence(
    item: dict[str, Any],
    cutoff: datetime,
    evidence_ids: set[str],
    source_urls: set[str],
    *,
    require_review: bool,
) -> dict[str, Any]:
    evidence_id = str(item.get("evidence_id") or "")
    if not evidence_id or evidence_id in evidence_ids:
        raise HTTPException(status_code=409, detail=f"Pilot Evidence ID is duplicated: {evidence_id}")
    evidence_ids.add(evidence_id)
    publisher = str(item.get("publisher") or "")
    if publisher not in benchmark.OFFICIAL_PUBLISHERS:
        raise HTTPException(status_code=422, detail=f"Pilot publisher is not approved: {publisher}")
    source_url = validate_remote_url(str(item.get("source_url") or ""), resolve_dns=False)
    if source_url in source_urls:
        raise HTTPException(status_code=409, detail="Pilot source URLs must be distinct")
    source_urls.add(source_url)
    if item.get("source_kind") not in {"versioned_file", "dated_publication"} or not str(item.get("version_label") or "").strip():
        raise HTTPException(status_code=422, detail="Pilot Evidence must be a dated or versioned publication")
    media = str(item.get("expected_mime") or "")
    if media not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail="Pilot Evidence MIME is not supported")
    license_name = str(item.get("license_name") or "")
    if license_name not in ARCHIVABLE_LICENSES:
        raise HTTPException(status_code=422, detail="Pilot Evidence license is not approved")
    license_url = validate_remote_url(str(item.get("license_url") or ""), resolve_dns=False)
    published = _parse_date(item.get("published_at"))
    role = item.get("evidence_role")
    if role == "input" and published > cutoff:
        raise HTTPException(status_code=409, detail="Pilot input Evidence is after cutoff")
    if role == "outcome" and published < cutoff:
        raise HTTPException(status_code=409, detail="Pilot outcome Evidence predates cutoff")
    locator = item.get("locator")
    if not isinstance(locator, dict) or not locator.get("location"):
        raise HTTPException(status_code=422, detail="Pilot Evidence locator is required")
    decision = item.get("rights_decision")
    if require_review:
        if (
            not isinstance(decision, dict)
            or decision.get("decision") != "approved"
            or decision.get("third_party_exception") != "none_identified"
            or len(str(decision.get("decision_basis") or "").strip()) < 20
        ):
            raise HTTPException(status_code=409, detail="Pilot Evidence rights decision is incomplete")
        decision = {
            "decision": "approved",
            "third_party_exception": "none_identified",
            "decision_basis": str(decision["decision_basis"]).strip(),
        }
    title = str(item.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Pilot Evidence title is required")
    return {
        "evidence_id": evidence_id,
        "evidence_role": role,
        "publisher": publisher,
        "title": title,
        "source_kind": item["source_kind"],
        "version_label": str(item["version_label"]).strip(),
        "source_url": source_url,
        "published_at": published.isoformat(),
        "expected_mime": media,
        "license_name": license_name,
        "license_url": license_url,
        "locator": locator,
        "rights_decision": decision,
    }


def _dossier_hash(dossier: dict[str, Any]) -> str:
    return stable_hash({key: value for key, value in dossier.items() if key != "dossier_hash"})
