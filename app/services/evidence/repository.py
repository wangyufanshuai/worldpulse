"""SQL persistence adapter for the Evidence bounded context.

This adapter owns Evidence table queries and row mapping.  It intentionally
does not own authorization, quota policy, timestamp validation, or sync
orchestration; those remain application concerns while the V1 compatibility
façade is migrated incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.evidence_models import (
    EvidenceClaim,
    EvidencePack,
    EvidenceSnapshot,
    EvidenceSnapshotSummary,
    EvidenceSource,
)
from app.services.evidence.mappers import (
    claim_from_row,
    pack_from_row,
    snapshot_from_row,
    snapshot_summary_from_row,
    source_from_row,
)
from app.services.project_store import connect, init_db


@dataclass(frozen=True)
class ProjectEvidenceReadModel:
    snapshot_count: int
    claim_count: int
    linked_claim_count: int
    pack_count: int
    latest_cutoff_at: str | None
    sources: list[EvidenceSource]
    recent_snapshots: list[EvidenceSnapshotSummary]
    recent_claims: list[EvidenceClaim]
    latest_pack: EvidencePack | None


@dataclass(frozen=True)
class EvidenceManifestReadModel:
    pack_id: str | None
    pack_hash: str | None
    pack_cutoff_at: str | None
    snapshot_hashes: dict[str, str]
    snapshot_cutoffs: list[str]


class EvidenceRepository:
    """Database-agnostic Evidence reads over the shared SQL connection port."""

    def find_source(self, source_type: str, locator: str) -> EvidenceSource | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_sources WHERE source_type = ? AND locator = ?",
                (source_type, locator),
            ).fetchone()
        return source_from_row(row) if row else None

    def list_sources(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        source_ids: list[str] | None = None,
    ) -> list[EvidenceSource]:
        init_db()
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if source_ids is not None:
            if not source_ids:
                return []
            clauses.append(f"source_id IN ({', '.join('?' for _ in source_ids)})")
            params.extend(source_ids)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM evidence_sources{where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [source_from_row(row) for row in rows]

    def get_source(self, source_id: str) -> EvidenceSource | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return source_from_row(row) if row else None

    def find_snapshot(self, source_id: str, external_ref: str, content_hash: str) -> EvidenceSnapshot | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE source_id = ? AND external_ref = ? AND content_hash = ?",
                (source_id, external_ref, content_hash),
            ).fetchone()
        return snapshot_from_row(row) if row else None

    def get_snapshot(self, snapshot_id: str) -> EvidenceSnapshot | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return snapshot_from_row(row) if row else None

    def get_claim(self, claim_id: str) -> EvidenceClaim | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_claims WHERE claim_id = ?",
                (claim_id,),
            ).fetchone()
            links = conn.execute(
                "SELECT snapshot_id, relation, citation_label, excerpt, locator_json "
                "FROM evidence_links WHERE claim_id = ? ORDER BY created_at",
                (claim_id,),
            ).fetchall()
        return claim_from_row(row, links) if row else None

    def find_claim_id(self, claim_hash: str) -> str | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT claim_id FROM evidence_claims WHERE claim_hash = ?",
                (claim_hash,),
            ).fetchone()
        return str(row["claim_id"]) if row else None

    def search_snapshots(
        self,
        *,
        query: str,
        project_id: str | None,
        category: str | None,
        cutoff_at: str | None,
        limit: int,
        snapshot_ids: list[str] | None,
    ) -> list[EvidenceSnapshotSummary]:
        init_db()
        clauses: list[str] = []
        params: list[Any] = []
        if snapshot_ids is not None:
            if not snapshot_ids:
                return []
            clauses.append(f"snapshot_id IN ({', '.join('?' for _ in snapshot_ids)})")
            params.extend(snapshot_ids)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if cutoff_at:
            clauses.extend(["observed_at <= ?", "cutoff_at <= ?"])
            params.extend([cutoff_at, cutoff_at])
        if query.strip():
            token = f"%{query.strip()}%"
            clauses.append("(title LIKE ? OR content_text LIKE ? OR external_ref LIKE ?)")
            params.extend([token, token, token])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM evidence_snapshots{where} "
                "ORDER BY cutoff_at DESC, captured_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [snapshot_summary_from_row(row) for row in rows]

    def search_claims(
        self,
        *,
        query: str,
        project_id: str | None,
        cutoff_at: str | None,
        limit: int,
        claim_ids: list[str] | None,
    ) -> list[EvidenceClaim]:
        init_db()
        clauses: list[str] = []
        params: list[Any] = []
        if claim_ids is not None:
            if not claim_ids:
                return []
            clauses.append(f"claim_id IN ({', '.join('?' for _ in claim_ids)})")
            params.extend(claim_ids)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if cutoff_at:
            clauses.append("cutoff_at <= ?")
            params.append(cutoff_at)
        if query.strip():
            clauses.append("statement LIKE ?")
            params.append(f"%{query.strip()}%")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"SELECT claim_id FROM evidence_claims{where} "
                "ORDER BY cutoff_at DESC, created_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        claims = [self.get_claim(row["claim_id"]) for row in rows]
        return [claim for claim in claims if claim is not None]

    def find_pack_id(self, manifest_hash: str) -> str | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT pack_id FROM evidence_packs WHERE manifest_hash = ?",
                (manifest_hash,),
            ).fetchone()
        return str(row["pack_id"]) if row else None

    def get_pack(self, pack_id: str) -> EvidencePack | None:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_packs WHERE pack_id = ?",
                (pack_id,),
            ).fetchone()
        return pack_from_row(row) if row else None

    def project_read_model(self, project_id: str) -> ProjectEvidenceReadModel:
        init_db()
        with connect() as conn:
            counts = conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM evidence_snapshots WHERE project_id = ?) AS snapshots,
                  (SELECT COUNT(*) FROM evidence_claims WHERE project_id = ?) AS claims,
                  (SELECT COUNT(DISTINCT c.claim_id) FROM evidence_claims c
                   JOIN evidence_links l ON l.claim_id = c.claim_id WHERE c.project_id = ?) AS linked_claims,
                  (SELECT COUNT(*) FROM evidence_packs WHERE project_id = ?) AS packs,
                  (SELECT MAX(cutoff_at) FROM evidence_snapshots WHERE project_id = ?) AS latest_cutoff
                """,
                (project_id, project_id, project_id, project_id, project_id),
            ).fetchone()
            source_rows = conn.execute(
                "SELECT DISTINCT s.* FROM evidence_sources s "
                "JOIN evidence_snapshots e ON e.source_id = s.source_id "
                "WHERE e.project_id = ? ORDER BY s.name",
                (project_id,),
            ).fetchall()
            snapshot_rows = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE project_id = ? "
                "ORDER BY cutoff_at DESC, captured_at DESC LIMIT 20",
                (project_id,),
            ).fetchall()
            claim_rows = conn.execute(
                "SELECT claim_id FROM evidence_claims WHERE project_id = ? "
                "ORDER BY cutoff_at DESC, created_at DESC LIMIT 20",
                (project_id,),
            ).fetchall()
            pack_row = conn.execute(
                "SELECT * FROM evidence_packs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        recent_claims = [self.get_claim(row["claim_id"]) for row in claim_rows]
        return ProjectEvidenceReadModel(
            snapshot_count=int(counts["snapshots"] or 0),
            claim_count=int(counts["claims"] or 0),
            linked_claim_count=int(counts["linked_claims"] or 0),
            pack_count=int(counts["packs"] or 0),
            latest_cutoff_at=counts["latest_cutoff"],
            sources=[source_from_row(row) for row in source_rows],
            recent_snapshots=[snapshot_summary_from_row(row) for row in snapshot_rows],
            recent_claims=[claim for claim in recent_claims if claim is not None],
            latest_pack=pack_from_row(pack_row) if pack_row else None,
        )

    def manifest_read_model(self, project_id: str, run_id: str) -> EvidenceManifestReadModel | None:
        init_db()
        with connect() as conn:
            pack = conn.execute(
                "SELECT * FROM evidence_packs WHERE project_id = ? "
                "AND (run_id = ? OR run_id IS NULL) ORDER BY created_at DESC LIMIT 1",
                (project_id, run_id),
            ).fetchone()
            snapshots = conn.execute(
                """
                SELECT e.snapshot_id, e.content_hash, e.cutoff_at
                FROM evidence_snapshots e JOIN evidence_sources s ON s.source_id = e.source_id
                WHERE e.project_id = ? AND (e.external_ref = ? OR s.metadata_json LIKE ?)
                ORDER BY e.captured_at
                """,
                (project_id, run_id, f'%"run_id": "{run_id}"%'),
            ).fetchall()
        if not pack and not snapshots:
            return None
        return EvidenceManifestReadModel(
            pack_id=pack["pack_id"] if pack else None,
            pack_hash=pack["manifest_hash"] if pack else None,
            pack_cutoff_at=pack["cutoff_at"] if pack else None,
            snapshot_hashes={row["snapshot_id"]: row["content_hash"] for row in snapshots},
            snapshot_cutoffs=[row["cutoff_at"] for row in snapshots],
        )

    def project_resource_ids(self, project_id: str) -> dict[str, list[str]]:
        init_db()
        with connect() as conn:
            source_rows = conn.execute(
                "SELECT DISTINCT source_id FROM evidence_snapshots WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            snapshot_rows = conn.execute(
                "SELECT snapshot_id FROM evidence_snapshots WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            claim_rows = conn.execute(
                "SELECT claim_id FROM evidence_claims WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            pack_rows = conn.execute(
                "SELECT pack_id FROM evidence_packs WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        return {
            "evidence_source": [row["source_id"] for row in source_rows],
            "evidence_snapshot": [row["snapshot_id"] for row in snapshot_rows],
            "evidence_claim": [row["claim_id"] for row in claim_rows],
            "evidence_pack": [row["pack_id"] for row in pack_rows],
        }

    def project_counts(self, project_id: str) -> dict[str, int]:
        init_db()
        with connect() as conn:
            row = conn.execute(
                """SELECT
                (SELECT COUNT(DISTINCT source_id) FROM evidence_snapshots WHERE project_id = ?) sources,
                (SELECT COUNT(*) FROM evidence_snapshots WHERE project_id = ?) snapshots,
                (SELECT COUNT(*) FROM evidence_claims WHERE project_id = ?) claims,
                (SELECT COUNT(*) FROM evidence_links l JOIN evidence_claims c ON c.claim_id = l.claim_id
                 WHERE c.project_id = ?) links""",
                (project_id, project_id, project_id, project_id),
            ).fetchone()
        return {key: int(row[key] or 0) for key in ("sources", "snapshots", "claims", "links")}

    def global_counts(self) -> dict[str, int]:
        init_db()
        with connect() as conn:
            row = conn.execute(
                "SELECT (SELECT COUNT(*) FROM evidence_sources) sources, "
                "(SELECT COUNT(*) FROM evidence_snapshots) snapshots",
            ).fetchone()
        return {"sources": int(row["sources"]), "snapshots": int(row["snapshots"])}
