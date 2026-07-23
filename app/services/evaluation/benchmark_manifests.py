from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException

from app.core.models import WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash

from . import benchmark
from .benchmark_contracts import (
    ALLOWED_DOMAINS,
    evidence_coverage,
    validate_domain_matrix,
    validate_label,
    validate_manifest_governance,
    validate_profile,
    validate_source_case,
)
from .benchmark_rights import ARCHIVABLE_LICENSES


def validate_source_plan(payload: dict[str, Any], profile: str = "release") -> dict[str, Any]:
    validate_profile(profile)
    if payload.get("suite_id") != "historical-benchmark.v1" or str(payload.get("version")) != "1":
        raise HTTPException(status_code=422, detail="Source plan identity is invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise HTTPException(status_code=422, detail="Source plan cases are required")
    validate_domain_matrix(cases, profile)
    seen_evidence: set[str] = set()
    normalized_cases = [validate_source_case(case, seen_evidence) for case in cases]
    normalized = {
        "suite_id": "historical-benchmark.v1",
        "version": "1",
        "curation_profile": profile,
        "purpose": payload.get("purpose", "official-source historical observation benchmark"),
        "curation_dossier_hash": payload.get("curation_dossier_hash"),
        "review_worksheet_hash": payload.get("review_worksheet_hash"),
        "reviewer": payload.get("reviewer"),
        "cases": normalized_cases,
    }
    hash_body = {
        "suite_id": normalized["suite_id"],
        "version": normalized["version"],
        "curation_profile": profile,
        "cases": normalized_cases,
    }
    if normalized["curation_dossier_hash"] or normalized["reviewer"] or normalized["review_worksheet_hash"]:
        hash_body.update({
            "purpose": normalized["purpose"],
            "curation_dossier_hash": normalized["curation_dossier_hash"],
            "review_worksheet_hash": normalized["review_worksheet_hash"],
            "reviewer": normalized["reviewer"],
        })
    normalized["source_plan_hash"] = stable_hash(hash_body)
    if payload.get("source_plan_hash") and payload["source_plan_hash"] != normalized["source_plan_hash"]:
        raise HTTPException(status_code=409, detail="Source plan hash mismatch")
    return normalized


def build_manifest_from_lock(lock_payload: dict[str, Any], source_plan: dict[str, Any], profile: str = "release") -> dict[str, Any]:
    plan = validate_source_plan(source_plan, profile)
    lock_hash = lock_payload.get("acquisition_lock_hash")
    expected_lock_hash = stable_hash({key: value for key, value in lock_payload.items() if key != "acquisition_lock_hash"})
    if not lock_hash or lock_hash != expected_lock_hash:
        raise HTTPException(status_code=409, detail="Acquisition lock hash mismatch")
    if lock_payload.get("curation_profile") != profile:
        raise HTTPException(status_code=409, detail="Acquisition lock profile mismatch")
    if lock_payload.get("source_plan_hash") != plan["source_plan_hash"]:
        raise HTTPException(status_code=409, detail="Acquisition lock does not match source plan")
    lock_entries = lock_payload.get("entries", [])
    if not isinstance(lock_entries, list):
        raise HTTPException(status_code=422, detail="Acquisition lock entries are invalid")
    lock_by_id = {item.get("evidence_id"): item for item in lock_entries}
    expected_ids = {item["evidence_id"] for case in plan["cases"] for item in case["evidence"]}
    if len(lock_by_id) != len(lock_entries) or set(lock_by_id) != expected_ids:
        raise HTTPException(status_code=409, detail="Acquisition lock evidence set mismatch")
    if profile == "pilot" and len({str(item.get("blob_sha256") or "") for item in lock_entries}) != 24:
        raise HTTPException(status_code=409, detail="Pilot requires 24 distinct Evidence blobs")
    cases: list[dict[str, Any]] = []
    for case in plan["cases"]:
        evidence: list[dict[str, Any]] = []
        for item in case["evidence"]:
            lock = lock_by_id.get(item["evidence_id"])
            if not lock or not lock.get("blob_sha256"):
                raise HTTPException(status_code=409, detail=f"Missing acquisition lock entry: {item['evidence_id']}")
            evidence.append({**item, "blob_sha256": lock["blob_sha256"]})
        cases.append(benchmark._validate_case({**case, "evidence": evidence}, plan["suite_id"]))
    manifest = {
        "suite_id": plan["suite_id"],
        "version": plan["version"],
        "curation_profile": profile,
        "purpose": plan["purpose"],
        "source_plan_hash": plan["source_plan_hash"],
        "acquisition_lock_hash": lock_payload.get("acquisition_lock_hash"),
        "cases": cases,
    }
    case_hashes = [case["case_hash"] for case in cases]
    manifest["manifest_hash"] = stable_hash({
        "suite_id": manifest["suite_id"],
        "version": manifest["version"],
        "purpose": manifest["purpose"],
        "curation_profile": profile,
        "source_plan_hash": manifest["source_plan_hash"],
        "acquisition_lock_hash": manifest["acquisition_lock_hash"],
        "case_hashes": case_hashes,
        "development_count": sum(case["split"] == "development" for case in cases),
        "blind_count": sum(case["split"] == "blind" for case in cases),
    })
    return manifest


def preflight_manifest(payload: dict[str, Any], profile: str = "release") -> dict[str, Any]:
    validate_profile(profile)
    errors: list[str] = []
    if payload.get("suite_id") != "historical-benchmark.v1" or str(payload.get("version")) != "1":
        errors.append("Manifest identity is invalid")
    if payload.get("curation_profile", profile) != profile:
        errors.append("Manifest curation profile does not match the requested preflight")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        cases = []
        errors.append("Manifest cases are required")
    try:
        validate_domain_matrix(cases, profile)
    except HTTPException as exc:
        errors.append(str(exc.detail))
    domain_counts = {domain: sum(item.get("domain") == domain for item in cases) for domain in sorted(ALLOWED_DOMAINS)}
    publisher_cases: dict[str, set[str]] = {}
    domain_publisher_cases: dict[str, dict[str, set[str]]] = {}
    pilot_blob_hashes: list[str] = []
    for raw in cases:
        case_id = str(raw.get("case_id") or "")
        try:
            normalized = benchmark._validate_case(raw, "historical-benchmark.v1")
            WarRoomScenarioRequest.model_validate(normalized["scenario"])
            validate_manifest_governance(normalized)
            labels = normalized.get("development_labels")
            roles: dict[str, str] = {}
            for evidence in normalized["evidence"]:
                configured_licenses = {
                    value.strip() for value in os.getenv("WORLDPULSE_BENCHMARK_LICENSES", "").split(",") if value.strip()
                }
                if evidence["license_name"] not in ARCHIVABLE_LICENSES and evidence["license_name"] not in configured_licenses:
                    errors.append(f"{case_id}: evidence license is not approved for local archival")
                publisher_cases.setdefault(evidence["publisher"], set()).add(case_id)
                domain_publisher_cases.setdefault(str(raw.get("domain")), {}).setdefault(evidence["publisher"], set()).add(case_id)
                roles[evidence["evidence_role"]] = evidence["blob_sha256"]
                pilot_blob_hashes.append(evidence["blob_sha256"])
            if roles.get("input") == roles.get("outcome"):
                errors.append(f"{case_id}: input and outcome must use different blobs")
            if raw.get("split") == "development":
                validate_label(
                    labels,
                    observation_window_days=int(raw.get("observation_window_days", 0)),
                    evidence_coverage=evidence_coverage(normalized["evidence"]),
                )
        except Exception as exc:
            errors.append(f"{case_id or 'unknown'}: {getattr(exc, 'detail', str(exc))}")
    if profile == "pilot" and len(pilot_blob_hashes) == 24 and len(set(pilot_blob_hashes)) != 24:
        errors.append("Pilot requires 24 distinct Evidence blobs")
    publisher_counts = {key: len(value) for key, value in sorted(publisher_cases.items())}
    if profile == "release":
        for domain in ALLOWED_DOMAINS:
            domain_publishers = {
                evidence.get("publisher")
                for case in cases if case.get("domain") == domain
                for evidence in case.get("evidence", []) if evidence.get("publisher")
            }
            if len(domain_publishers) < 3:
                errors.append(f"{domain}: at least three official publishers are required")
            concentrated = {
                publisher: len(case_ids)
                for publisher, case_ids in domain_publisher_cases.get(domain, {}).items()
                if len(case_ids) > 8
            }
            if concentrated:
                errors.append(f"{domain}: a single publisher cannot cover more than eight release cases")
    checks = {
        "profile_matrix": not any("split is invalid" in item or "requires" in item for item in errors),
        "scenario_contract": not any("scenario" in item.lower() or "override" in item.lower() for item in errors),
        "evidence_contract": not any("evidence" in item.lower() or "blob" in item.lower() for item in errors),
        "labels": not any("label" in item.lower() or "ranking" in item.lower() or "top3" in item.lower() for item in errors),
        "publisher_distribution": not any("publisher" in item.lower() for item in errors),
    }
    body = {
        "status": "passed" if not errors else "failed",
        "profile": profile,
        "case_count": len(cases),
        "domain_counts": domain_counts,
        "blind_count": sum(item.get("split") == "blind" for item in cases),
        "publisher_counts": publisher_counts,
        "checks": checks,
        "errors": errors,
    }
    return {**body, "report_hash": stable_hash(body)}
