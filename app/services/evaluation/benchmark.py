from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.evaluation_models import (
    HistoricalBenchmarkCase,
    HistoricalBenchmarkSuite,
    HistoricalEvidenceItem,
    LabelPackImportRequest,
    LabelPackReviewRequest,
    SealedLabelPack,
)
from app.services.consistency.hashing import stable_hash
from app.services.evaluation.benchmark_rights import validate_rights_review
from app.services.project_store import connect, dumps, loads


OFFICIAL_PUBLISHERS = {
    "UN", "WTO", "World Bank", "IMF", "BIS", "FAO", "WFP", "IEA", "EIA",
    "OFAC", "Federal Reserve", "ECB", "Eurostat",
}
DOMAINS = {"strait", "energy", "food", "sanctions", "trade", "finance"}


def benchmark_root() -> Path:
    return Path(os.getenv("WORLDPULSE_BENCHMARK_ROOT", "data/benchmarks")).resolve()


def ingest_manifest(payload: dict[str, Any], actor: Any) -> HistoricalBenchmarkSuite:
    """Import a reviewed manifest only when all 120 external evidence blobs exist.

    This deliberately performs no crawling. Official material must be acquired and
    licensed outside the API, then placed in the content-addressed benchmark store.
    """

    if payload.get("curation_profile", "release") != "release":
        raise HTTPException(status_code=409, detail="Only a release-profile benchmark manifest can be activated")
    suite_id = str(payload.get("suite_id") or "")
    version = str(payload.get("version") or "")
    cases = payload.get("cases")
    if suite_id != "historical-benchmark.v1" or version != "1" or not isinstance(cases, list):
        raise HTTPException(status_code=422, detail="Historical benchmark manifest identity is invalid")
    from .benchmark_tools import preflight_manifest

    preflight = preflight_manifest(payload, "release")
    if preflight["status"] != "passed":
        raise HTTPException(
            status_code=422,
            detail={"message": "Historical benchmark release preflight failed", "errors": preflight["errors"]},
        )
    _validate_case_matrix(cases)
    normalized_cases = [_validate_case(item, suite_id) for item in cases]
    manifest_body = {
        "suite_id": suite_id,
        "version": version,
        "purpose": payload.get("purpose", "official-source historical observation benchmark"),
        "curation_profile": "release",
        "source_plan_hash": payload.get("source_plan_hash"),
        "acquisition_lock_hash": payload.get("acquisition_lock_hash"),
        "case_hashes": [item["case_hash"] for item in normalized_cases],
        "development_count": 90,
        "blind_count": 30,
    }
    manifest_hash = stable_hash(manifest_body)
    supplied = payload.get("manifest_hash")
    if supplied and supplied != manifest_hash:
        raise HTTPException(status_code=409, detail="Historical benchmark manifest hash mismatch")
    now = _now()
    with connect() as conn:
        existing = conn.execute("SELECT manifest_hash FROM historical_benchmark_suites WHERE suite_id = ?", (suite_id,)).fetchone()
        if existing:
            if existing["manifest_hash"] != manifest_hash:
                raise HTTPException(status_code=409, detail="Historical benchmark suite is immutable")
            return get_suite(suite_id)
        conn.execute(
            """INSERT INTO historical_benchmark_suites
               (suite_id,version,status,manifest_json,manifest_hash,development_count,blind_count,created_by_user_id,created_at,activated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (suite_id, version, "active", dumps(manifest_body), manifest_hash, 90, 30, getattr(actor, "user_id", None), now, now),
        )
        for item in normalized_cases:
            conn.execute(
                """INSERT INTO historical_benchmark_cases
                   (case_id,suite_id,version,domain,split,title,cutoff_at,observation_window_days,scenario_json,evidence_manifest_json,development_labels_json,label_confidence,case_hash,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["case_id"], suite_id, item["version"], item["domain"], item["split"], item["title"],
                    item["cutoff_at"], item["observation_window_days"], dumps(item["scenario"]),
                    dumps(item["evidence_manifest"]), dumps(item.get("development_labels")) if item.get("development_labels") is not None else None,
                    item["label_confidence"], item["case_hash"], now,
                ),
            )
            for evidence in item["evidence"]:
                conn.execute(
                    """INSERT INTO historical_benchmark_evidence
                       (evidence_id,case_id,evidence_role,publisher,license_name,source_url,observed_at,cutoff_at,blob_sha256,locator_json,evidence_hash,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        evidence["evidence_id"], item["case_id"], evidence["evidence_role"], evidence["publisher"],
                        evidence["license_name"], evidence["source_url"], evidence["observed_at"], evidence["cutoff_at"],
                        evidence["blob_sha256"], dumps(evidence["locator"]), evidence["evidence_hash"], now,
                    ),
                )
    return get_suite(suite_id)


def get_suite(suite_id: str) -> HistoricalBenchmarkSuite:
    with connect() as conn:
        row = conn.execute("SELECT * FROM historical_benchmark_suites WHERE suite_id = ?", (suite_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown historical benchmark suite")
    return HistoricalBenchmarkSuite(
        suite_id=row["suite_id"], version=row["version"], status=row["status"],
        manifest=loads(row["manifest_json"], {}), manifest_hash=row["manifest_hash"],
        development_count=int(row["development_count"]), blind_count=int(row["blind_count"]),
        created_at=row["created_at"], activated_at=row["activated_at"],
    )


def list_suites() -> list[HistoricalBenchmarkSuite]:
    with connect() as conn:
        ids = [row["suite_id"] for row in conn.execute("SELECT suite_id FROM historical_benchmark_suites ORDER BY created_at")]
    return [get_suite(item) for item in ids]


def list_cases(suite_id: str) -> list[HistoricalBenchmarkCase]:
    get_suite(suite_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM historical_benchmark_cases WHERE suite_id = ? ORDER BY domain, split, case_id", (suite_id,)).fetchall()
        evidence_rows = conn.execute(
            """SELECT e.* FROM historical_benchmark_evidence e
               JOIN historical_benchmark_cases c ON c.case_id=e.case_id
               WHERE c.suite_id=? ORDER BY e.case_id,e.evidence_id""", (suite_id,)
        ).fetchall()
    evidence: dict[str, list[HistoricalEvidenceItem]] = {}
    for item in evidence_rows:
        evidence.setdefault(item["case_id"], []).append(HistoricalEvidenceItem(
            evidence_id=item["evidence_id"], case_id=item["case_id"], evidence_role=item["evidence_role"],
            publisher=item["publisher"], license_name=item["license_name"], source_url=item["source_url"],
            observed_at=item["observed_at"], cutoff_at=item["cutoff_at"], blob_sha256=item["blob_sha256"],
            locator=loads(item["locator_json"], {}), evidence_hash=item["evidence_hash"],
        ))
    return [HistoricalBenchmarkCase(
        case_id=row["case_id"], suite_id=row["suite_id"], version=row["version"], domain=row["domain"],
        split=row["split"], title=row["title"], cutoff_at=row["cutoff_at"], observation_window_days=int(row["observation_window_days"]),
        scenario=loads(row["scenario_json"], {}), evidence_manifest=loads(row["evidence_manifest_json"], {}),
        labels=None if row["split"] == "blind" else loads(row["development_labels_json"], {}),
        label_confidence=float(row["label_confidence"]), case_hash=row["case_hash"], evidence=evidence.get(row["case_id"], []),
    ) for row in rows]


def import_label_pack(organization_id: str, payload: LabelPackImportRequest, actor: Any) -> SealedLabelPack:
    if getattr(actor, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Only admin can import sealed blind label packs")
    suite = get_suite(payload.suite_id)
    if suite.status != "active" or payload.case_count != suite.blind_count:
        raise HTTPException(status_code=409, detail="Label pack does not match the active blind suite")
    try:
        ciphertext = base64.b64decode(payload.ciphertext_b64, validate=True)
        nonce = base64.b64decode(payload.nonce_b64, validate=True)
        signature = base64.b64decode(payload.signature, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Label pack encoding is invalid") from exc
    if len(nonce) != 12:
        raise HTTPException(status_code=422, detail="AES-256-GCM nonce must be 12 bytes")
    blob_sha256 = hashlib.sha256(ciphertext).hexdigest()
    signed = _signature_payload(payload.manifest_hash, payload.evidence_hash, blob_sha256, payload.nonce_b64, payload.encryption_key_id)
    _verify_signature(payload.signer_key_id, signed, signature)
    _store_blob(ciphertext, blob_sha256)
    pack_id = f"labels_{uuid4().hex[:16]}"
    now = _now()
    with connect() as conn:
        conn.execute(
            """INSERT INTO historical_label_packs
               (label_pack_id,organization_id,suite_id,status,blob_sha256,manifest_hash,signature,signer_key_id,encryption_key_id,nonce_b64,evidence_hash,case_count,imported_by_user_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pack_id, organization_id, payload.suite_id, "reviewing", blob_sha256, payload.manifest_hash, payload.signature, payload.signer_key_id, payload.encryption_key_id, payload.nonce_b64, payload.evidence_hash, payload.case_count, actor.user_id, now),
        )
    return get_label_pack(organization_id, pack_id)


def review_label_pack(organization_id: str, pack_id: str, payload: LabelPackReviewRequest, actor: Any) -> SealedLabelPack:
    if getattr(actor, "role", None) not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Reviewer or admin role is required")
    pack = get_label_pack(organization_id, pack_id)
    if pack.status not in {"reviewing", "uploaded"}:
        raise HTTPException(status_code=409, detail="Label pack is not awaiting review")
    if actor.user_id == pack.imported_by_user_id:
        raise HTTPException(status_code=403, detail="Label pack importer cannot approve the same pack")
    now = _now()
    review_payload = {"label_pack_id": pack_id, "reviewer": actor.user_id, "role": actor.role, "decision": payload.decision, "comment": payload.comment}
    with connect() as conn:
        conn.execute(
            """INSERT INTO historical_label_pack_reviews
               (review_id,label_pack_id,reviewer_user_id,reviewer_role,decision,comment,review_hash,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (f"label_review_{uuid4().hex[:16]}", pack_id, actor.user_id, actor.role, payload.decision, payload.comment, stable_hash(review_payload), now),
        )
        reviews = conn.execute("SELECT reviewer_role,decision FROM historical_label_pack_reviews WHERE label_pack_id = ?", (pack_id,)).fetchall()
        if payload.decision == "reject":
            status = "rejected"
        else:
            approved_roles = {row["reviewer_role"] for row in reviews if row["decision"] == "approve"}
            approved_count = sum(row["decision"] == "approve" for row in reviews)
            status = "active" if approved_count >= 2 and {"reviewer", "admin"}.issubset(approved_roles) else "reviewing"
        conn.execute("UPDATE historical_label_packs SET status = ? WHERE label_pack_id = ?", (status, pack_id))
    return get_label_pack(organization_id, pack_id)


def get_label_pack(organization_id: str, pack_id: str) -> SealedLabelPack:
    with connect() as conn:
        row = conn.execute("SELECT * FROM historical_label_packs WHERE label_pack_id = ? AND organization_id = ?", (pack_id, organization_id)).fetchone()
        reviews = conn.execute("SELECT reviewer_user_id,reviewer_role,decision,comment,created_at FROM historical_label_pack_reviews WHERE label_pack_id = ? ORDER BY created_at", (pack_id,)).fetchall() if row else []
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown sealed label pack")
    return SealedLabelPack(
        label_pack_id=row["label_pack_id"], organization_id=row["organization_id"], suite_id=row["suite_id"], status=row["status"],
        blob_sha256=row["blob_sha256"], manifest_hash=row["manifest_hash"], signature=row["signature"], signer_key_id=row["signer_key_id"], encryption_key_id=row["encryption_key_id"],
        evidence_hash=row["evidence_hash"], case_count=int(row["case_count"]), imported_by_user_id=row["imported_by_user_id"],
        bound_root_batch_id=row["bound_root_batch_id"], comparison_started_at=row["comparison_started_at"], consumed_at=row["consumed_at"], created_at=row["created_at"],
        approvals=[dict(item) for item in reviews],
    )


def list_label_packs(organization_id: str) -> list[SealedLabelPack]:
    with connect() as conn:
        ids = [row["label_pack_id"] for row in conn.execute("SELECT label_pack_id FROM historical_label_packs WHERE organization_id = ? ORDER BY created_at DESC", (organization_id,))]
    return [get_label_pack(organization_id, item) for item in ids]


def decrypt_labels(pack: SealedLabelPack) -> dict[str, Any]:
    if pack.status not in {"active", "consuming"}:
        raise HTTPException(status_code=409, detail="Sealed label pack is not active")
    keys = _json_env("WORLDPULSE_BLIND_LABEL_KEYS")
    encoded_key = keys.get(pack.encryption_key_id)
    if not encoded_key:
        raise HTTPException(status_code=409, detail="Blind label decryption key is unavailable")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = base64.b64decode(encoded_key, validate=True)
        ciphertext = _blob_path(pack.blob_sha256).read_bytes()
        plaintext = AESGCM(key).decrypt(base64.b64decode(_nonce_for_pack(pack.label_pack_id)), ciphertext, pack.manifest_hash.encode("ascii"))
        result = json.loads(plaintext)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Blind label pack decryption failed") from exc
    if stable_hash(result) != pack.manifest_hash:
        raise HTTPException(status_code=409, detail="Blind label manifest hash mismatch")
    return result


def verify_benchmarks() -> dict[str, Any]:
    suites = list_suites()
    missing: list[str] = []
    invalid: list[str] = []
    case_count = 0
    for suite in suites:
        cases = list_cases(suite.suite_id)
        case_count += len(cases)
        for case in cases:
            for evidence in case.evidence:
                path = _blob_path(evidence.blob_sha256)
                if not path.is_file():
                    missing.append(evidence.blob_sha256)
                elif _sha256_file(path) != evidence.blob_sha256:
                    invalid.append(evidence.blob_sha256)
    status = "ok" if suites and case_count == 120 and not missing and not invalid else "failed"
    return {"status": status, "suite_count": len(suites), "case_count": case_count, "missing_blobs": sorted(set(missing)), "invalid_blobs": sorted(set(invalid))}


def _validate_case_matrix(cases: list[dict[str, Any]]) -> None:
    if len(cases) != 120:
        raise HTTPException(status_code=422, detail="Historical benchmark requires exactly 120 cases")
    for domain in DOMAINS:
        domain_cases = [item for item in cases if item.get("domain") == domain]
        if len(domain_cases) != 20 or sum(item.get("split") == "development" for item in domain_cases) != 15 or sum(item.get("split") == "blind" for item in domain_cases) != 5:
            raise HTTPException(status_code=422, detail=f"Historical benchmark split is invalid for domain: {domain}")


def _validate_case(item: dict[str, Any], suite_id: str) -> dict[str, Any]:
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
    if not required.issubset(item) or item["domain"] not in DOMAINS or item["split"] not in {"development", "blind"}:
        raise HTTPException(status_code=422, detail="Historical benchmark case contract is invalid")
    if item["split"] == "blind" and item.get("development_labels") is not None:
        raise HTTPException(status_code=409, detail="Blind labels cannot appear in the online benchmark manifest")
    evidence = [_validate_evidence(raw, item["case_id"], item["cutoff_at"]) for raw in item["evidence"]]
    roles = {raw["evidence_role"] for raw in evidence}
    if roles != {"input", "outcome"}:
        raise HTTPException(status_code=422, detail="Each case requires official input and outcome evidence")
    normalized = {key: item.get(key) for key in sorted(required - {"evidence"})}
    normalized.update({
        "suite_id": suite_id,
        "evidence": evidence,
        "evidence_manifest": {
            "evidence_hashes": [raw["evidence_hash"] for raw in evidence],
            "assumptions": item["assumptions"],
            "target_country_evidence": item["target_country_evidence"],
            "policy_action_evidence_ids": item["policy_action_evidence_ids"],
        },
        "development_labels": item.get("development_labels"),
    })
    case_body = {key: value for key, value in normalized.items() if key != "case_hash"}
    normalized["case_hash"] = stable_hash(case_body)
    if item.get("case_hash") and item["case_hash"] != normalized["case_hash"]:
        raise HTTPException(status_code=409, detail=f"Historical case hash mismatch: {item['case_id']}")
    return normalized


def _validate_evidence(item: dict[str, Any], case_id: str, case_cutoff: str) -> dict[str, Any]:
    configured_publishers = {
        value.strip() for value in os.getenv("WORLDPULSE_BENCHMARK_PUBLISHERS", "").split(",") if value.strip()
    }
    publisher = str(item.get("publisher", ""))
    if (publisher not in OFFICIAL_PUBLISHERS and publisher not in configured_publishers and not publisher.startswith("Official:")) or not str(item.get("source_url", "")).startswith("https://"):
        raise HTTPException(status_code=422, detail="Benchmark evidence must use an approved official HTTPS publisher")
    if item.get("evidence_role") not in {"input", "outcome"} or len(str(item.get("blob_sha256", ""))) != 64:
        raise HTTPException(status_code=422, detail="Benchmark evidence contract is invalid")
    observed_at = _parse_iso_utc(item.get("observed_at"), "evidence observed_at")
    cutoff_at = _parse_iso_utc(case_cutoff, "case cutoff")
    if item["evidence_role"] == "input" and observed_at > cutoff_at:
        raise HTTPException(status_code=409, detail="Input evidence leaks information after the case cutoff")
    if item["evidence_role"] == "outcome" and observed_at < cutoff_at:
        raise HTTPException(status_code=409, detail="Outcome evidence predates the case cutoff")
    rights_review = validate_rights_review(
        item.get("rights_review") or item.get("locator", {}).get("rights_review"),
        publisher=publisher,
        source_url=str(item["source_url"]),
        license_name=str(item.get("license_name") or ""),
        license_url=str(item.get("license_url") or ""),
    )
    path = _blob_path(item["blob_sha256"])
    if not path.is_file() or _sha256_file(path) != item["blob_sha256"]:
        raise HTTPException(status_code=409, detail=f"Benchmark evidence blob is missing or invalid: {item['blob_sha256']}")
    body = {
        "case_id": case_id,
        "evidence_role": item["evidence_role"], "publisher": item["publisher"], "license_name": item.get("license_name", ""),
        "license_url": item.get("license_url", ""),
        "source_url": item["source_url"], "observed_at": item["observed_at"], "cutoff_at": item["cutoff_at"],
        "blob_sha256": item["blob_sha256"], "locator": {**item.get("locator", {}), "rights_review": rights_review},
    }
    body["locator"] = {**body["locator"], "license_url": body["license_url"]}
    result = {"evidence_id": item.get("evidence_id") or f"he_{stable_hash(body)[:20]}", **body, "evidence_hash": stable_hash(body)}
    if item.get("evidence_hash") and item["evidence_hash"] != result["evidence_hash"]:
        raise HTTPException(status_code=409, detail="Historical evidence hash mismatch")
    return result


def _parse_iso_utc(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Benchmark {field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _verify_signature(key_id: str, payload: bytes, signature: bytes) -> None:
    keys = _json_env("WORLDPULSE_BLIND_SIGNER_PUBLIC_KEYS")
    encoded = keys.get(key_id)
    if not encoded:
        raise HTTPException(status_code=409, detail="Blind label signer key is unavailable")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded, validate=True)).verify(signature, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Blind label signature verification failed") from exc


def _signature_payload(manifest_hash: str, evidence_hash: str, blob_sha256: str, nonce_b64: str, encryption_key_id: str) -> bytes:
    return dumps({"manifest_hash": manifest_hash, "evidence_hash": evidence_hash, "blob_sha256": blob_sha256, "nonce_b64": nonce_b64, "encryption_key_id": encryption_key_id}).encode("utf-8")


def _store_blob(content: bytes, sha256: str) -> None:
    path = _blob_path(sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _sha256_file(path) != sha256:
            raise HTTPException(status_code=409, detail="Existing benchmark blob failed integrity verification")
        return
    temporary = path.with_suffix(f".{uuid4().hex}.part")
    temporary.write_bytes(content)
    temporary.replace(path)


def _blob_path(sha256: str) -> Path:
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise HTTPException(status_code=409, detail="Benchmark blob hash is invalid")
    root = benchmark_root()
    path = (root / "sha256" / sha256[:2] / sha256).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=409, detail="Benchmark blob path is invalid")
    return path


def _nonce_for_pack(pack_id: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT nonce_b64 FROM historical_label_packs WHERE label_pack_id = ?", (pack_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown sealed label pack")
    return row["nonce_b64"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_env(name: str) -> dict[str, str]:
    try:
        value = json.loads(os.getenv(name, "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail=f"{name} is invalid") from exc
    return value if isinstance(value, dict) else {}


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
