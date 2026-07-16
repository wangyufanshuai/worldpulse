from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import requests
from fastapi import HTTPException

from app.services.consistency.hashing import stable_hash
from app.services.continuous_intelligence.feed import validate_remote_url
from . import benchmark


MAX_SOURCE_BYTES = 25 * 1024 * 1024
ALLOWED_MIME = {
    "application/pdf",
    "application/json",
    "text/csv",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}
ALLOWED_DOMAINS = {"strait", "energy", "food", "sanctions", "trade", "finance"}
COUNTRY_CODES = {"USA", "CHN", "JPN", "KOR", "TWN", "IND", "EU", "RUS", "SAU", "BRA"}
CHAIN_KEYS = {"energy", "food", "chips", "shipping", "settlement"}


def validate_source_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("suite_id") != "historical-benchmark.v1" or str(payload.get("version")) != "1":
        raise HTTPException(status_code=422, detail="Source plan identity is invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise HTTPException(status_code=422, detail="Source plan cases are required")
    if len(cases) != 120:
        raise HTTPException(status_code=422, detail="Source plan requires exactly 120 cases")
    _validate_domain_matrix(cases)
    seen_evidence: set[str] = set()
    normalized_cases: list[dict[str, Any]] = []
    for case in cases:
        normalized_cases.append(_validate_source_case(case, seen_evidence))
    normalized = {
        "suite_id": "historical-benchmark.v1",
        "version": "1",
        "purpose": payload.get("purpose", "official-source historical observation benchmark"),
        "source_plan_hash": stable_hash({"suite_id": "historical-benchmark.v1", "version": "1", "cases": normalized_cases}),
        "cases": normalized_cases,
    }
    if payload.get("source_plan_hash") and payload["source_plan_hash"] != normalized["source_plan_hash"]:
        raise HTTPException(status_code=409, detail="Source plan hash mismatch")
    return normalized


def fetch_sources(payload: dict[str, Any]) -> dict[str, Any]:
    plan = validate_source_plan(payload)
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
        "source_plan_hash": plan["source_plan_hash"],
        "fetched_at": _now(),
        "entries": lock_entries,
    }
    lock["acquisition_lock_hash"] = stable_hash({k: v for k, v in lock.items() if k != "acquisition_lock_hash"})
    return lock


def build_manifest_from_lock(lock_payload: dict[str, Any], source_plan: dict[str, Any]) -> dict[str, Any]:
    plan = validate_source_plan(source_plan)
    if lock_payload.get("source_plan_hash") != plan["source_plan_hash"]:
        raise HTTPException(status_code=409, detail="Acquisition lock does not match source plan")
    lock_by_id = {item["evidence_id"]: item for item in lock_payload.get("entries", [])}
    cases: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
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
        "source_plan_hash": manifest["source_plan_hash"],
        "acquisition_lock_hash": manifest["acquisition_lock_hash"],
        "case_hashes": case_hashes,
        "development_count": 90,
        "blind_count": 30,
    })
    return manifest


def validate_label_payload(payload: dict[str, Any], blind_case_ids: set[str]) -> dict[str, Any]:
    if payload.get("suite_id") != "historical-benchmark.v1":
        raise HTTPException(status_code=422, detail="Label pack suite is invalid")
    labels = payload.get("labels")
    if not isinstance(labels, dict) or set(labels) != blind_case_ids:
        raise HTTPException(status_code=422, detail="Label pack must contain exactly the 30 blind cases")
    normalized: dict[str, Any] = {"suite_id": payload["suite_id"], "labels": {}}
    for case_id in sorted(blind_case_ids):
        normalized["labels"][case_id] = _validate_label(labels[case_id])
    return normalized


def pack_labels(payload: dict[str, Any], blind_case_ids: set[str], *, aes_key_b64: str, signer_private_key_b64: str, signer_key_id: str, encryption_key_id: str, evidence_hash: str) -> dict[str, Any]:
    normalized = validate_label_payload(payload, blind_case_ids)
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


def _validate_domain_matrix(cases: list[dict[str, Any]]) -> None:
    for domain in ALLOWED_DOMAINS:
        items = [item for item in cases if item.get("domain") == domain]
        if len(items) != 20 or sum(item.get("split") == "development" for item in items) != 15 or sum(item.get("split") == "blind" for item in items) != 5:
            raise HTTPException(status_code=422, detail=f"Source plan split is invalid for domain: {domain}")


def _validate_source_case(case: dict[str, Any], seen_evidence: set[str]) -> dict[str, Any]:
    required = {"case_id", "version", "domain", "split", "title", "cutoff_at", "observation_window_days", "scenario", "label_confidence", "evidence"}
    if not required.issubset(case) or case["domain"] not in ALLOWED_DOMAINS or case["split"] not in {"development", "blind"}:
        raise HTTPException(status_code=422, detail="Source plan case contract is invalid")
    cutoff = _parse_date(case["cutoff_at"])
    if cutoff > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Source plan cutoff cannot be in the future")
    scenario = case["scenario"]
    if scenario.get("country_overrides") or scenario.get("chain_overrides"):
        raise HTTPException(status_code=422, detail=f"Scenario overrides are forbidden: {case['case_id']}")
    countries = set(scenario.get("target_countries", []))
    chains = set(scenario.get("target_chains", []))
    if not countries.issubset(COUNTRY_CODES) or not chains.issubset(CHAIN_KEYS):
        raise HTTPException(status_code=422, detail=f"Scenario target is not in the fixed WorldPulse universe: {case['case_id']}")
    evidence = case["evidence"]
    if not isinstance(evidence, list) or {item.get("evidence_role") for item in evidence} != {"input", "outcome"}:
        raise HTTPException(status_code=422, detail=f"Each case requires input and outcome evidence: {case['case_id']}")
    normalized_evidence = []
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
        url = validate_remote_url(str(item.get("source_url") or ""), resolve_dns=False)
        observed = _parse_date(item.get("observed_at"))
        if item["evidence_role"] == "input" and observed > cutoff:
            raise HTTPException(status_code=409, detail=f"Input evidence is after case cutoff: {evidence_id}")
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
        })
    return {
        **{key: case[key] for key in required if key != "evidence"},
        "scenario": scenario,
        "evidence": normalized_evidence,
    }


def _validate_label(label: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(label, dict):
        raise HTTPException(status_code=422, detail="Historical label must be an object")
    ranking = list(label.get("risk_ranking", []))
    top3 = list(label.get("top3_countries", []))
    if len(ranking) < 5 or len(set(ranking)) != len(ranking) or not set(ranking).issubset(COUNTRY_CODES):
        raise HTTPException(status_code=422, detail="Historical risk ranking must contain at least five known countries")
    if len(top3) != 3 or len(set(top3)) != 3 or not set(top3).issubset(set(ranking)):
        raise HTTPException(status_code=422, detail="Historical top3 label is invalid")
    directions = label.get("supply_chain_directions", {})
    if not isinstance(directions, dict) or not directions or not set(directions).issubset(CHAIN_KEYS) or not set(directions.values()).issubset({"up", "down", "flat"}):
        raise HTTPException(status_code=422, detail="Historical supply-chain labels are invalid")
    turning_points = label.get("turning_points", [])
    if not isinstance(turning_points, list) or any(int(value) < 0 for value in turning_points):
        raise HTTPException(status_code=422, detail="Historical turning points are invalid")
    confidence = float(label.get("label_confidence", 0))
    if not 0.5 <= confidence <= 1:
        raise HTTPException(status_code=422, detail="Historical label confidence must be between 0.5 and 1")
    return {
        "risk_ranking": ranking,
        "top3_countries": top3,
        "supply_chain_directions": directions,
        "turning_points": [int(value) for value in turning_points],
        "agent_outcome_expectations": label.get("agent_outcome_expectations", {}),
        "coverage_countries": list(label.get("coverage_countries", ranking)),
        "label_confidence": confidence,
    }


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
        response.close()
        blob_sha256 = digest.hexdigest()
        benchmark._store_blob(content, blob_sha256)
        return {
            **evidence,
            "case_id": case["case_id"],
            "final_url": current,
            "content_type": media,
            "size_bytes": size,
            "blob_sha256": blob_sha256,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "fetched_at": _now(),
        }
    raise HTTPException(status_code=422, detail="Benchmark source exceeded the redirect limit")


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
