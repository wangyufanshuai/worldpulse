from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from urllib.parse import urljoin

import requests
from fastapi import HTTPException

from app.services.consistency.hashing import stable_hash
from app.services.continuous_intelligence.feed import validate_remote_url

from . import benchmark
from .benchmark_contracts import ALLOWED_MIME, MAX_SOURCE_BYTES
from .benchmark_manifests import validate_source_plan
from .benchmark_rights import validate_rights_review


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
    lock["acquisition_lock_hash"] = stable_hash({key: value for key, value in lock.items() if key != "acquisition_lock_hash"})
    return lock


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
