from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from fastapi import HTTPException

from app.services.consistency.hashing import stable_hash
from app.services.continuous_intelligence.feed import validate_remote_url


ARCHIVABLE_LICENSES = {
    "Public Domain",
    "CC BY 4.0",
    "CC BY 3.0 IGO",
    "CC BY-NC-SA 3.0 IGO",
    "Open Government Licence v3.0",
}
RIGHTS_REVIEW_SCOPE = "local_archive_and_evaluation"


def validate_rights_review(
    review: Any,
    *,
    publisher: str,
    source_url: str,
    license_name: str,
    license_url: str,
) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise HTTPException(status_code=422, detail="Evidence rights review is required")
    if review.get("decision") != "approved":
        raise HTTPException(status_code=409, detail="Evidence rights review is not approved")
    reviewer = str(review.get("reviewed_by") or "").strip()
    basis = str(review.get("decision_basis") or "").strip()
    if not reviewer or len(basis) < 20:
        raise HTTPException(status_code=422, detail="Evidence rights review is incomplete")
    if review.get("scope") != RIGHTS_REVIEW_SCOPE:
        raise HTTPException(status_code=422, detail="Evidence rights review scope is invalid")
    reviewed_at = _parse_reviewed_at(review.get("reviewed_at"))
    normalized_source = validate_remote_url(source_url, resolve_dns=False)
    normalized_license = validate_remote_url(license_url, resolve_dns=False)
    bindings = {
        "publisher": publisher,
        "source_url": normalized_source,
        "license_name": license_name,
        "license_url": normalized_license,
    }
    if any(review.get(key) is not None and review.get(key) != value for key, value in bindings.items()):
        raise HTTPException(status_code=409, detail="Evidence rights review binding mismatch")
    allowed = ARCHIVABLE_LICENSES | {
        value.strip()
        for value in os.getenv("WORLDPULSE_BENCHMARK_LICENSES", "").split(",")
        if value.strip()
    }
    if license_name not in allowed:
        raise HTTPException(status_code=422, detail="Evidence license is not approved for local archival")
    body = {
        "decision": "approved",
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at.isoformat(),
        "scope": RIGHTS_REVIEW_SCOPE,
        "decision_basis": basis,
        **bindings,
    }
    body["review_hash"] = stable_hash(body)
    if review.get("review_hash") and review["review_hash"] != body["review_hash"]:
        raise HTTPException(status_code=409, detail="Evidence rights review hash mismatch")
    return body


def _parse_reviewed_at(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Evidence rights review time must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Evidence rights review cannot be in the future")
    return parsed
