from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from fastapi import HTTPException

from app.services.consistency.hashing import stable_hash

from . import benchmark
from .benchmark_contracts import validate_label


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
        normalized["labels"][case_id] = validate_label(
            labels[case_id], evidence_coverage=(evidence_coverage_by_case or {}).get(case_id)
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
    ciphertext = AESGCM(aes_key).encrypt(
        nonce,
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        manifest_hash.encode("ascii"),
    )
    blob_sha256 = hashlib.sha256(ciphertext).hexdigest()
    signature_payload = benchmark._signature_payload(
        manifest_hash, evidence_hash, blob_sha256,
        base64.b64encode(nonce).decode("ascii"), encryption_key_id,
    )
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
