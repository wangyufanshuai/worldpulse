from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any
from urllib.parse import urljoin

import requests
from fastapi import HTTPException

from app.core.models import WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.continuous_intelligence.feed import validate_remote_url
from app.services.war_room.data import POLICY_ACTIONS
from . import benchmark
from .benchmark_rights import ARCHIVABLE_LICENSES, validate_rights_review


MAX_SOURCE_BYTES = 25 * 1024 * 1024
ALLOWED_MIME = {
    "application/pdf",
    "application/json",
    "text/csv",
    "text/plain",
    "text/markdown",
}
ALLOWED_DOMAINS = {"strait", "energy", "food", "sanctions", "trade", "finance"}
COUNTRY_CODES = {"USA", "CHN", "JPN", "KOR", "TWN", "IND", "EU", "RUS", "SAU", "BRA"}
CHAIN_KEYS = {"energy", "food", "chips", "shipping", "settlement"}
ACTION_TYPES = {
    "alliance_request", "alliance_response", "deescalation_offer", "humanitarian_offer",
    "diplomatic_signal", "sanction_proposal", "trade_reroute_request", "public_narrative",
    "intelligence_request",
}
COMMITMENT_ACTION_TYPES = {"alliance_request", "deescalation_offer", "humanitarian_offer"}
BLIND_POSITIONS = {4, 8, 12, 16, 20}


def validate_source_plan(payload: dict[str, Any], profile: str = "release") -> dict[str, Any]:
    _validate_profile(profile)
    if payload.get("suite_id") != "historical-benchmark.v1" or str(payload.get("version")) != "1":
        raise HTTPException(status_code=422, detail="Source plan identity is invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise HTTPException(status_code=422, detail="Source plan cases are required")
    _validate_domain_matrix(cases, profile)
    seen_evidence: set[str] = set()
    normalized_cases: list[dict[str, Any]] = []
    for case in cases:
        normalized_cases.append(_validate_source_case(case, seen_evidence))
    normalized = {
        "suite_id": "historical-benchmark.v1",
        "version": "1",
        "curation_profile": profile,
        "purpose": payload.get("purpose", "official-source historical observation benchmark"),
        "source_plan_hash": stable_hash({"suite_id": "historical-benchmark.v1", "version": "1", "curation_profile": profile, "cases": normalized_cases}),
        "cases": normalized_cases,
    }
    if payload.get("source_plan_hash") and payload["source_plan_hash"] != normalized["source_plan_hash"]:
        raise HTTPException(status_code=409, detail="Source plan hash mismatch")
    return normalized


def fetch_sources(payload: dict[str, Any], profile: str = "release") -> dict[str, Any]:
    plan = validate_source_plan(payload, profile)
    lock_entries: list[dict[str, Any]] = []
    session = requests.Session()
    session.trust_env = False
    try:
        for case in plan["cases"]:
            for evidence in case["evidence"]:
                lock_entries.append(_fetch_one(session, case, evidence))
    finally:
        session.close()
    lock = {
        "suite_id": plan["suite_id"],
        "version": plan["version"],
        "curation_profile": profile,
        "source_plan_hash": plan["source_plan_hash"],
        "fetched_at": _now(),
        "entries": lock_entries,
    }
    lock["acquisition_lock_hash"] = stable_hash({k: v for k, v in lock.items() if k != "acquisition_lock_hash"})
    return lock


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
    expected_ids = {
        item["evidence_id"]
        for case in plan["cases"]
        for item in case["evidence"]
    }
    if len(lock_by_id) != len(lock_entries) or set(lock_by_id) != expected_ids:
        raise HTTPException(status_code=409, detail="Acquisition lock evidence set mismatch")
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
    _validate_profile(profile)
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
        _validate_domain_matrix(cases, profile)
    except HTTPException as exc:
        errors.append(str(exc.detail))
    domain_counts = {domain: sum(item.get("domain") == domain for item in cases) for domain in sorted(ALLOWED_DOMAINS)}
    publisher_cases: dict[str, set[str]] = {}
    domain_publisher_cases: dict[str, dict[str, set[str]]] = {}
    for raw in cases:
        case_id = str(raw.get("case_id") or "")
        try:
            normalized = benchmark._validate_case(raw, "historical-benchmark.v1")
            WarRoomScenarioRequest.model_validate(normalized["scenario"])
            _validate_manifest_governance(normalized)
            labels = normalized.get("development_labels")
            roles: dict[str, str] = {}
            for evidence in normalized["evidence"]:
                configured_licenses = {
                    value.strip()
                    for value in os.getenv("WORLDPULSE_BENCHMARK_LICENSES", "").split(",")
                    if value.strip()
                }
                if evidence["license_name"] not in ARCHIVABLE_LICENSES and evidence["license_name"] not in configured_licenses:
                    errors.append(f"{case_id}: evidence license is not approved for local archival")
                publisher_cases.setdefault(evidence["publisher"], set()).add(case_id)
                domain_publisher_cases.setdefault(str(raw.get("domain")), {}).setdefault(
                    evidence["publisher"], set()
                ).add(case_id)
                roles[evidence["evidence_role"]] = evidence["blob_sha256"]
            if roles.get("input") == roles.get("outcome"):
                errors.append(f"{case_id}: input and outcome must use different blobs")
            if raw.get("split") == "development":
                _validate_label(
                    labels,
                    observation_window_days=int(raw.get("observation_window_days", 0)),
                    evidence_coverage=_evidence_coverage(normalized["evidence"]),
                )
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            errors.append(f"{case_id or 'unknown'}: {detail}")
    publisher_counts = {key: len(value) for key, value in sorted(publisher_cases.items())}
    if profile == "release":
        for domain in ALLOWED_DOMAINS:
            domain_publishers = {
                evidence.get("publisher")
                for case in cases if case.get("domain") == domain
                for evidence in case.get("evidence", [])
                if evidence.get("publisher")
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


def source_status(lock_payload: dict[str, Any]) -> dict[str, Any]:
    entries = lock_payload.get("entries")
    if not isinstance(entries, list):
        entries = []
    supplied_lock_hash = lock_payload.get("acquisition_lock_hash")
    acquisition_lock_hash_valid = bool(supplied_lock_hash) and supplied_lock_hash == stable_hash(
        {key: value for key, value in lock_payload.items() if key != "acquisition_lock_hash"}
    )
    missing: list[str] = []
    license_errors: list[str] = []
    hash_errors: list[str] = []
    verified = 0
    publisher_counts: dict[str, int] = {}
    domain_publisher_cases: dict[str, dict[str, set[str]]] = {}
    for item in entries:
        evidence_id = str(item.get("evidence_id") or "")
        publisher = str(item.get("publisher") or "")
        publisher_counts[publisher] = publisher_counts.get(publisher, 0) + 1
        domain = str(item.get("domain") or "")
        case_id = str(item.get("case_id") or "")
        if domain and publisher and case_id:
            domain_publisher_cases.setdefault(domain, {}).setdefault(publisher, set()).add(case_id)
        sha256 = str(item.get("blob_sha256") or "")
        if not sha256:
            missing.append(evidence_id)
            continue
        try:
            validate_rights_review(
                item.get("rights_review") or item.get("locator", {}).get("rights_review"),
                publisher=publisher,
                source_url=str(item.get("source_url") or ""),
                license_name=str(item.get("license_name") or ""),
                license_url=str(item.get("license_url") or ""),
            )
        except HTTPException:
            license_errors.append(evidence_id)
            continue
        if len(sha256) != 64:
            hash_errors.append(evidence_id)
            continue
        try:
            path = benchmark._blob_path(sha256)
        except HTTPException:
            hash_errors.append(evidence_id)
            continue
        if not path.is_file():
            missing.append(evidence_id)
        elif benchmark._sha256_file(path) != sha256:
            hash_errors.append(evidence_id)
        elif not item.get("license_name") or not item.get("license_url"):
            license_errors.append(evidence_id)
        else:
            verified += 1
    domain_counts = {
        domain: {publisher: len(case_ids) for publisher, case_ids in sorted(publishers.items())}
        for domain, publishers in sorted(domain_publisher_cases.items())
    }
    concentration_warnings = [
        f"{domain}:{publisher}:{count}"
        for domain, publishers in domain_counts.items()
        for publisher, count in publishers.items()
        if count > 8
    ]
    invalid = sorted(set(license_errors + hash_errors))
    status = (
        "complete"
        if entries and acquisition_lock_hash_valid and not missing and not invalid
        else "failed"
        if invalid or (entries and not acquisition_lock_hash_valid)
        else "incomplete"
    )
    body = {
        "status": status,
        "acquisition_lock_hash_valid": acquisition_lock_hash_valid,
        "entry_count": len(entries),
        "verified_count": verified,
        "missing_count": len(missing),
        "invalid_count": len(invalid),
        "publisher_counts": dict(sorted(publisher_counts.items())),
        "domain_publisher_counts": domain_counts,
        "missing_evidence_ids": sorted(missing),
        "invalid_evidence_ids": invalid,
        "license_error_evidence_ids": sorted(license_errors),
        "hash_error_evidence_ids": sorted(hash_errors),
        "concentration_warnings": concentration_warnings,
    }
    return {**body, "status_hash": stable_hash(body)}


def validate_label_payload(
    payload: dict[str, Any],
    blind_case_ids: set[str],
    evidence_coverage_by_case: dict[str, dict[str, set[str]]] | None = None,
) -> dict[str, Any]:
    if payload.get("suite_id") != "historical-benchmark.v1":
        raise HTTPException(status_code=422, detail="Label pack suite is invalid")
    labels = payload.get("labels")
    if not isinstance(labels, dict) or set(labels) != blind_case_ids:
        raise HTTPException(status_code=422, detail="Label pack must contain exactly the 30 blind cases")
    if evidence_coverage_by_case is not None and set(evidence_coverage_by_case) != blind_case_ids:
        raise HTTPException(status_code=422, detail="Blind label evidence coverage is incomplete")
    normalized: dict[str, Any] = {"suite_id": payload["suite_id"], "labels": {}}
    for case_id in sorted(blind_case_ids):
        normalized["labels"][case_id] = _validate_label(
            labels[case_id],
            evidence_coverage=(evidence_coverage_by_case or {}).get(case_id),
        )
    return normalized


def pack_labels(
    payload: dict[str, Any],
    blind_case_ids: set[str],
    *,
    evidence_coverage_by_case: dict[str, dict[str, set[str]]],
    aes_key_b64: str,
    signer_private_key_b64: str,
    signer_key_id: str,
    encryption_key_id: str,
    evidence_hash: str,
) -> dict[str, Any]:
    normalized = validate_label_payload(payload, blind_case_ids, evidence_coverage_by_case)
    manifest_hash = stable_hash(normalized)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes_key = base64.b64decode(aes_key_b64, validate=True)
        private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(signer_private_key_b64, validate=True))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Offline label key material is invalid") from exc
    if len(aes_key) != 32:
        raise HTTPException(status_code=422, detail="AES label key must be 256 bits")
    nonce = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"), manifest_hash.encode("ascii"))
    blob_sha256 = hashlib.sha256(ciphertext).hexdigest()
    signature_payload = benchmark._signature_payload(manifest_hash, evidence_hash, blob_sha256, base64.b64encode(nonce).decode("ascii"), encryption_key_id)
    signature = private_key.sign(signature_payload)
    return {
        "suite_id": "historical-benchmark.v1",
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "manifest_hash": manifest_hash,
        "signature": base64.b64encode(signature).decode("ascii"),
        "signer_key_id": signer_key_id,
        "encryption_key_id": encryption_key_id,
        "evidence_hash": evidence_hash,
        "case_count": len(blind_case_ids),
        "ciphertext_sha256": blob_sha256,
    }


def _validate_profile(profile: str) -> None:
    if profile not in {"pilot", "wave", "release"}:
        raise HTTPException(status_code=422, detail="Benchmark curation profile is invalid")


def _validate_domain_matrix(cases: list[dict[str, Any]], profile: str) -> None:
    _validate_profile(profile)
    counts = {domain: len([item for item in cases if item.get("domain") == domain]) for domain in ALLOWED_DOMAINS}
    if profile == "pilot" and (len(cases) != 12 or any(count != 2 for count in counts.values())):
        raise HTTPException(status_code=422, detail="Pilot source plan requires exactly 12 cases (two per domain)")
    if profile == "release" and (len(cases) != 120 or any(count != 20 for count in counts.values())):
        raise HTTPException(status_code=422, detail="Release source plan requires exactly 120 cases (twenty per domain)")
    if profile == "wave":
        unique_counts = set(counts.values())
        if len(unique_counts) != 1 or not unique_counts or next(iter(unique_counts)) < 2 or next(iter(unique_counts)) >= 20:
            raise HTTPException(status_code=422, detail="Wave source plan requires the same 2-19 case count in every domain")
    for domain in ALLOWED_DOMAINS:
        items = sorted(
            [item for item in cases if item.get("domain") == domain],
            key=lambda item: (str(item.get("cutoff_at", "")), str(item.get("case_id", ""))),
        )
        expected_blind = {
            item.get("case_id")
            for index, item in enumerate(items, start=1)
            if index in BLIND_POSITIONS
        }
        actual_blind = {item.get("case_id") for item in items if item.get("split") == "blind"}
        if actual_blind != expected_blind:
            raise HTTPException(status_code=422, detail=f"Source plan split is invalid for domain: {domain}")


def _validate_source_case(case: dict[str, Any], seen_evidence: set[str]) -> dict[str, Any]:
    required = {
        "case_id",
        "version",
        "domain",
        "split",
        "title",
        "cutoff_at",
        "observation_window_days",
        "scenario",
        "label_confidence",
        "evidence",
        "assumptions",
        "target_country_evidence",
        "policy_action_evidence_ids",
    }
    if not required.issubset(case) or case["domain"] not in ALLOWED_DOMAINS or case["split"] not in {"development", "blind"}:
        raise HTTPException(status_code=422, detail="Source plan case contract is invalid")
    cutoff = _parse_date(case["cutoff_at"])
    observation_days = int(case["observation_window_days"])
    if cutoff.year < 2010 or cutoff.year > 2025:
        raise HTTPException(status_code=422, detail=f"Case cutoff must be between 2010 and 2025: {case['case_id']}")
    if cutoff > datetime.now(timezone.utc) or cutoff.timestamp() + observation_days * 86400 > datetime.now(timezone.utc).timestamp():
        raise HTTPException(status_code=409, detail="Source plan cutoff cannot be in the future")
    scenario = case["scenario"]
    if scenario.get("country_overrides") or scenario.get("chain_overrides"):
        raise HTTPException(status_code=422, detail=f"Scenario overrides are forbidden: {case['case_id']}")
    countries = set(scenario.get("target_countries", []))
    chains = set(scenario.get("target_chains", []))
    if len(countries) > 6 or not countries.issubset(COUNTRY_CODES) or not chains.issubset(CHAIN_KEYS):
        raise HTTPException(status_code=422, detail=f"Scenario target is not in the fixed WorldPulse universe: {case['case_id']}")
    if set(scenario.get("policy_actions", [])).difference(POLICY_ACTIONS):
        raise HTTPException(status_code=422, detail=f"Scenario policy action is invalid: {case['case_id']}")
    if scenario.get("intensity") not in {0.45, 0.65, 0.82} or scenario.get("propagation") not in {0.3, 0.45, 0.6}:
        raise HTTPException(status_code=422, detail=f"Scenario rubric value is invalid: {case['case_id']}")
    if scenario.get("duration_days") not in {30, 45, 60, 90} or int(scenario["duration_days"]) > observation_days:
        raise HTTPException(status_code=422, detail=f"Scenario duration is invalid: {case['case_id']}")
    WarRoomScenarioRequest.model_validate(scenario)
    evidence = case["evidence"]
    if not isinstance(evidence, list) or {item.get("evidence_role") for item in evidence} != {"input", "outcome"}:
        raise HTTPException(status_code=422, detail=f"Each case requires input and outcome evidence: {case['case_id']}")
    normalized_evidence = []
    input_evidence_ids: set[str] = set()
    for item in evidence:
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in seen_evidence:
            raise HTTPException(status_code=409, detail=f"Duplicate evidence id: {evidence_id}")
        seen_evidence.add(evidence_id)
        publisher = str(item.get("publisher") or "")
        configured_publishers = {
            value.strip() for value in os.getenv("WORLDPULSE_BENCHMARK_PUBLISHERS", "").split(",") if value.strip()
        }
        if (
            not publisher
            or (publisher not in benchmark.OFFICIAL_PUBLISHERS and publisher not in configured_publishers and not publisher.startswith("Official:"))
            or not str(item.get("license_name") or "")
            or not str(item.get("license_url") or "")
        ):
            raise HTTPException(status_code=422, detail=f"Evidence license metadata is incomplete: {evidence_id}")
        configured_licenses = {
            value.strip() for value in os.getenv("WORLDPULSE_BENCHMARK_LICENSES", "").split(",") if value.strip()
        }
        if item["license_name"] not in ARCHIVABLE_LICENSES and item["license_name"] not in configured_licenses:
            raise HTTPException(status_code=422, detail=f"Evidence license is not approved for local archival: {evidence_id}")
        url = validate_remote_url(str(item.get("source_url") or ""), resolve_dns=False)
        rights_review = validate_rights_review(
            item.get("rights_review"),
            publisher=publisher,
            source_url=url,
            license_name=str(item["license_name"]),
            license_url=str(item["license_url"]),
        )
        observed = _parse_date(item.get("observed_at"))
        if item["evidence_role"] == "input" and observed > cutoff:
            raise HTTPException(status_code=409, detail=f"Input evidence is after case cutoff: {evidence_id}")
        if item["evidence_role"] == "outcome" and observed < cutoff:
            raise HTTPException(status_code=409, detail=f"Outcome evidence predates the case cutoff: {evidence_id}")
        if item["evidence_role"] == "input":
            input_evidence_ids.add(evidence_id)
        normalized_evidence.append({
            "evidence_id": evidence_id,
            "evidence_role": item["evidence_role"],
            "publisher": publisher,
            "license_name": item["license_name"],
            "license_url": item["license_url"],
            "source_url": url,
            "observed_at": observed.isoformat(),
            "cutoff_at": cutoff.isoformat(),
            "expected_mime": item.get("expected_mime", ""),
            "locator": item.get("locator", {}),
            "rights_review": rights_review,
        })
    target_country_evidence = case["target_country_evidence"]
    if not isinstance(target_country_evidence, dict) or set(target_country_evidence) != countries:
        raise HTTPException(status_code=422, detail=f"Each target country requires input evidence: {case['case_id']}")
    if any(
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or not set(evidence_ids).issubset(input_evidence_ids)
        for evidence_ids in target_country_evidence.values()
    ):
        raise HTTPException(status_code=422, detail=f"Target country evidence must reference input material: {case['case_id']}")
    policy_evidence = case["policy_action_evidence_ids"]
    if not isinstance(policy_evidence, list) or not set(policy_evidence).issubset(input_evidence_ids):
        raise HTTPException(status_code=422, detail=f"Policy action evidence must reference input material: {case['case_id']}")
    if scenario.get("policy_actions") and not policy_evidence:
        raise HTTPException(status_code=422, detail=f"Policy actions require cutoff-time official evidence: {case['case_id']}")
    assumptions = _validate_assumptions(case["assumptions"], scenario, input_evidence_ids, str(case["case_id"]))
    development_labels = case.get("development_labels")
    if case["split"] == "blind" and development_labels is not None:
        raise HTTPException(status_code=409, detail="Blind labels cannot appear in a source plan")
    return {
        **{key: case[key] for key in required if key != "evidence"},
        "scenario": scenario,
        "assumptions": assumptions,
        "target_country_evidence": {
            code: sorted(set(evidence_ids))
            for code, evidence_ids in sorted(target_country_evidence.items())
        },
        "policy_action_evidence_ids": sorted(set(policy_evidence)),
        "development_labels": development_labels,
        "evidence": normalized_evidence,
    }


def _validate_manifest_governance(case: dict[str, Any]) -> None:
    scenario = case["scenario"]
    cutoff = _parse_date(case["cutoff_at"])
    observation_days = int(case["observation_window_days"])
    if cutoff.year < 2010 or cutoff.year > 2025 or cutoff > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail=f"Manifest cutoff is invalid: {case['case_id']}")
    if cutoff.timestamp() + observation_days * 86400 > datetime.now(timezone.utc).timestamp():
        raise HTTPException(status_code=409, detail=f"Manifest observation window is not closed: {case['case_id']}")
    if scenario.get("country_overrides") or scenario.get("chain_overrides"):
        raise HTTPException(status_code=422, detail=f"Manifest scenario overrides are forbidden: {case['case_id']}")
    if (
        len(set(scenario.get("target_countries", []))) > 6
        or not set(scenario.get("target_countries", [])).issubset(COUNTRY_CODES)
        or not set(scenario.get("target_chains", [])).issubset(CHAIN_KEYS)
        or set(scenario.get("policy_actions", [])).difference(POLICY_ACTIONS)
        or scenario.get("intensity") not in {0.45, 0.65, 0.82}
        or scenario.get("propagation") not in {0.3, 0.45, 0.6}
        or scenario.get("duration_days") not in {30, 45, 60, 90}
        or int(scenario["duration_days"]) > observation_days
    ):
        raise HTTPException(status_code=422, detail=f"Manifest scenario rubric is invalid: {case['case_id']}")
    input_evidence_ids = {
        item["evidence_id"]
        for item in case["evidence"]
        if item["evidence_role"] == "input"
    }
    target_country_evidence = case.get("target_country_evidence")
    target_countries = set(scenario.get("target_countries", []))
    if not isinstance(target_country_evidence, dict) or set(target_country_evidence) != target_countries:
        raise HTTPException(status_code=422, detail=f"Each target country requires input evidence: {case['case_id']}")
    if any(
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or not set(evidence_ids).issubset(input_evidence_ids)
        for evidence_ids in target_country_evidence.values()
    ):
        raise HTTPException(status_code=422, detail=f"Target country evidence must reference input material: {case['case_id']}")
    if any(
        item["evidence_role"] == "outcome" and _parse_date(item["observed_at"]) < cutoff
        for item in case["evidence"]
    ):
        raise HTTPException(status_code=409, detail=f"Outcome evidence predates case cutoff: {case['case_id']}")
    policy_evidence = case.get("policy_action_evidence_ids")
    if not isinstance(policy_evidence, list) or not set(policy_evidence).issubset(input_evidence_ids):
        raise HTTPException(status_code=422, detail=f"Policy action evidence must reference input material: {case['case_id']}")
    if scenario.get("policy_actions") and not policy_evidence:
        raise HTTPException(status_code=422, detail=f"Policy actions require cutoff-time official evidence: {case['case_id']}")
    _validate_assumptions(case.get("assumptions"), scenario, input_evidence_ids, str(case["case_id"]))


def _validate_assumptions(
    assumptions: Any,
    scenario: dict[str, Any],
    input_evidence_ids: set[str],
    case_id: str,
) -> dict[str, Any]:
    if not isinstance(assumptions, dict):
        raise HTTPException(status_code=422, detail=f"Scenario assumptions are required: {case_id}")
    normalized: dict[str, Any] = {}
    for key in ("duration_days", "intensity", "propagation"):
        item = assumptions.get(key)
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"Scenario assumption is incomplete: {case_id}/{key}")
        evidence_ids = item.get("evidence_ids")
        reason = str(item.get("reason") or "").strip()
        reviewer = str(item.get("reviewer") or "").strip()
        if (
            item.get("value") != scenario.get(key)
            or not reason
            or not reviewer
            or not isinstance(evidence_ids, list)
            or not evidence_ids
            or not set(evidence_ids).issubset(input_evidence_ids)
        ):
            raise HTTPException(status_code=422, detail=f"Scenario assumption evidence is invalid: {case_id}/{key}")
        normalized[key] = {
            "value": item["value"],
            "reason": reason,
            "evidence_ids": sorted(set(evidence_ids)),
            "reviewer": reviewer,
        }
    return normalized


def _validate_label(
    label: dict[str, Any] | None,
    *,
    observation_window_days: int | None = None,
    evidence_coverage: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    if not isinstance(label, dict):
        raise HTTPException(status_code=422, detail="Historical label must be an object")
    ranking = list(label.get("risk_ranking", []))
    top3 = list(label.get("top3_countries", []))
    if len(ranking) < 5 or len(set(ranking)) != len(ranking) or not set(ranking).issubset(COUNTRY_CODES):
        raise HTTPException(status_code=422, detail="Historical risk ranking must contain at least five known countries")
    deviation_reason = str(label.get("top3_deviation_reason") or "").strip()
    if len(top3) != 3 or len(set(top3)) != 3 or not set(top3).issubset(set(ranking)) or (top3 != ranking[:3] and not deviation_reason):
        raise HTTPException(status_code=422, detail="Historical top3 label is invalid")
    directions = label.get("supply_chain_directions", {})
    if not isinstance(directions, dict) or not directions or not set(directions).issubset(CHAIN_KEYS) or not set(directions.values()).issubset({"up", "down", "flat"}):
        raise HTTPException(status_code=422, detail="Historical supply-chain labels are invalid")
    turning_points = label.get("turning_points", [])
    if not isinstance(turning_points, list) or any(int(value) < 0 or (observation_window_days is not None and int(value) > observation_window_days) for value in turning_points):
        raise HTTPException(status_code=422, detail="Historical turning points are invalid")
    expectations = label.get("agent_outcome_expectations", {})
    if not isinstance(expectations, dict):
        raise HTTPException(status_code=422, detail="Agent outcome expectations are invalid")
    allowed = set(expectations.get("allowed_action_types", []))
    forbidden = set(expectations.get("forbidden_action_types", []))
    commitments = set(expectations.get("expected_commitment_patterns", []))
    if allowed & forbidden or not (allowed | forbidden).issubset(ACTION_TYPES) or not commitments.issubset(COMMITMENT_ACTION_TYPES):
        raise HTTPException(status_code=422, detail="Agent action expectation contract is invalid")
    coverage_countries = list(label.get("coverage_countries", ranking))
    coverage_chains = list(label.get("coverage_supply_chains", directions))
    if not set(coverage_countries).issubset(set(ranking)) or not set(coverage_chains).issubset(set(directions)):
        raise HTTPException(status_code=422, detail="Historical label coverage is inconsistent")
    if evidence_coverage is not None and (
        not set(coverage_countries).issubset(evidence_coverage["countries"])
        or not set(coverage_chains).issubset(evidence_coverage["supply_chains"])
    ):
        raise HTTPException(status_code=422, detail="Historical label coverage exceeds its official evidence")
    confidence = float(label.get("label_confidence", 0))
    if not 0.5 <= confidence <= 1:
        raise HTTPException(status_code=422, detail="Historical label confidence must be between 0.5 and 1")
    return {
        "risk_ranking": ranking,
        "top3_countries": top3,
        "top3_deviation_reason": deviation_reason,
        "supply_chain_directions": directions,
        "turning_points": [int(value) for value in turning_points],
        "agent_outcome_expectations": {
            "allowed_action_types": sorted(allowed),
            "forbidden_action_types": sorted(forbidden),
            "expected_commitment_patterns": sorted(commitments),
        },
        "coverage_countries": coverage_countries,
        "coverage_supply_chains": coverage_chains,
        "label_confidence": confidence,
    }


def _evidence_coverage(evidence: list[dict[str, Any]]) -> dict[str, set[str]]:
    countries: set[str] = set()
    supply_chains: set[str] = set()
    for item in evidence:
        locator = item.get("locator", {})
        if not isinstance(locator, dict):
            continue
        countries.update(code for code in locator.get("coverage_countries", []) if code in COUNTRY_CODES)
        supply_chains.update(key for key in locator.get("coverage_supply_chains", []) if key in CHAIN_KEYS)
    return {"countries": countries, "supply_chains": supply_chains}


def _fetch_one(session: requests.Session, case: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    current = validate_remote_url(evidence["source_url"], resolve_dns=True)
    headers = {"Accept": ", ".join(sorted(ALLOWED_MIME)), "User-Agent": "WorldPulse/1.12 benchmark-acquirer"}
    for _ in range(4):
        response = session.get(current, headers=headers, timeout=(5, 30), stream=True, allow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise HTTPException(status_code=422, detail="Benchmark redirect is missing a location")
            current = validate_remote_url(urljoin(current, location), resolve_dns=True)
            continue
        if response.status_code < 200 or response.status_code >= 300:
            response.close()
            raise HTTPException(status_code=422, detail=f"Benchmark source returned HTTP {response.status_code}")
        media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media not in ALLOWED_MIME or (evidence.get("expected_mime") and media != evidence["expected_mime"]):
            response.close()
            raise HTTPException(status_code=415, detail="Benchmark source media type is not allowed")
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_SOURCE_BYTES:
            response.close()
            raise HTTPException(status_code=413, detail="Benchmark source exceeds the 25 MB limit")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                response.close()
                raise HTTPException(status_code=413, detail="Benchmark source exceeds the 25 MB limit")
            digest.update(chunk)
            chunks.append(chunk)
        content = b"".join(chunks)
        _validate_source_bytes(content, media)
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        response.close()
        blob_sha256 = digest.hexdigest()
        benchmark._store_blob(content, blob_sha256)
        return {
            **evidence,
            "case_id": case["case_id"],
            "domain": case["domain"],
            "final_url": current,
            "content_type": media,
            "size_bytes": size,
            "blob_sha256": blob_sha256,
            "etag": etag,
            "last_modified": last_modified,
            "fetched_at": _now(),
        }
    raise HTTPException(status_code=422, detail="Benchmark source exceeded the redirect limit")


def _validate_source_bytes(content: bytes, media: str) -> None:
    if not content:
        raise HTTPException(status_code=422, detail="Benchmark source is empty")
    if media == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail="Benchmark PDF signature is invalid")
        return
    if media == "application/json":
        try:
            json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=415, detail="Benchmark JSON content is invalid") from exc
        return
    if media in {"text/csv", "text/plain", "text/markdown"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Benchmark text content must be UTF-8") from exc
        prefix = text.lstrip().lower()[:64]
        if prefix.startswith("<!doctype html") or prefix.startswith("<html"):
            raise HTTPException(status_code=415, detail="Benchmark source returned HTML content")


def _parse_date(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Benchmark timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
