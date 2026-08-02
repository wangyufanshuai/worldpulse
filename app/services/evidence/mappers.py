"""Persistence-to-domain mapping for the Evidence bounded context.

Mappers accept SQLite rows, PostgreSQL ``HybridRow`` objects, or ordinary
mapping-shaped test doubles.  They never open a connection or make access
control decisions.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from app.core.evidence_models import (
    EvidenceClaim,
    EvidencePack,
    EvidenceSnapshot,
    EvidenceSnapshotSummary,
    EvidenceSource,
)
from app.services.evidence.hashing import canonical_json, snapshot_digest
from app.services.project_store import loads


def source_from_row(row: Any) -> EvidenceSource:
    return EvidenceSource(
        source_id=row["source_id"],
        source_type=row["source_type"],
        name=row["name"],
        locator=row["locator"],
        publisher=row["publisher"],
        status=row["status"],
        trust_tier=row["trust_tier"],
        metadata=loads(row["metadata_json"], {}),
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        retired_at=row["retired_at"],
    )


def snapshot_from_row(row: Any) -> EvidenceSnapshot:
    content = loads(row["content_json"], {})
    integrity: Literal["verified", "failed"] = "verified" if snapshot_digest(
        row["source_id"],
        row["project_id"],
        row["external_ref"],
        row["title"],
        row["category"],
        canonical_json(content),
        row["observed_at"],
        row["cutoff_at"],
    ) == row["content_hash"] else "failed"
    return EvidenceSnapshot(
        snapshot_id=row["snapshot_id"],
        source_id=row["source_id"],
        project_id=row["project_id"],
        external_ref=row["external_ref"],
        title=row["title"],
        category=row["category"],
        content=content,
        content_text=row["content_text"],
        observed_at=row["observed_at"],
        cutoff_at=row["cutoff_at"],
        captured_at=row["captured_at"],
        content_hash=row["content_hash"],
        created_by_user_id=row["created_by_user_id"],
        integrity_status=integrity,
    )


def snapshot_summary_from_row(row: Any) -> EvidenceSnapshotSummary:
    full = snapshot_from_row(row)
    return EvidenceSnapshotSummary(**full.model_dump(exclude={"content", "content_text"}))


def claim_from_row(row: Any, links: Iterable[Any] | None = None) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=row["claim_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        statement=row["statement"],
        claim_type=row["claim_type"],
        confidence=float(row["confidence"]),
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        cutoff_at=row["cutoff_at"],
        claim_hash=row["claim_hash"],
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        links=[{
            "snapshot_id": item["snapshot_id"],
            "relation": item["relation"],
            "citation_label": item["citation_label"],
            "excerpt": item["excerpt"],
            "locator": loads(item["locator_json"], {}),
        } for item in (links or [])],
    )


def pack_from_row(row: Any) -> EvidencePack:
    return EvidencePack(
        pack_id=row["pack_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        name=row["name"],
        cutoff_at=row["cutoff_at"],
        manifest=loads(row["manifest_json"], {}),
        manifest_hash=row["manifest_hash"],
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
    )
