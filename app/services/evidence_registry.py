from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException

from app.core.evidence_models import (
    EvidenceClaim,
    EvidenceClaimCreate,
    EvidencePack,
    EvidencePackCreate,
    EvidenceSearchResult,
    EvidenceSnapshot,
    EvidenceSnapshotCreate,
    EvidenceSnapshotSummary,
    EvidenceSource,
    EvidenceSourceCreate,
    EvidenceSyncResult,
    ProjectEvidenceSummary,
)
from app.core.trust_models import UserIdentity
from app.services.project_store import connect, dumps, init_db, loads
from app.services.organizations import require_resource_scope, scope_resource, scoped_resource_ids


def create_source(payload: EvidenceSourceCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidenceSource:
    init_db()
    now = _now()
    source_id = f"src_{uuid4().hex[:20]}"
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_sources
                (source_id, source_type, name, locator, publisher, status, trust_tier, metadata_json,
                 created_by_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (source_id, payload.source_type, payload.name, payload.locator, payload.publisher,
                 payload.trust_tier, dumps(payload.metadata), actor.user_id, now),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM evidence_sources WHERE source_type = ? AND locator = ?",
                    (payload.source_type, payload.locator),
                ).fetchone()
            if row:
                source = _source(row)
                if organization_id:
                    scope_resource(organization_id, "evidence_source", source.source_id)
                return source
        raise
    if organization_id:
        scope_resource(organization_id, "evidence_source", source_id)
    return get_source(source_id, organization_id=organization_id)


def list_sources(*, status: str | None = None, source_type: str | None = None, organization_id: str | None = None) -> list[EvidenceSource]:
    init_db()
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if organization_id:
        identifiers = sorted(scoped_resource_ids(organization_id, "evidence_source"))
        if not identifiers:
            return []
        clauses.append(f"source_id IN ({', '.join('?' for _ in identifiers)})")
        params.extend(identifiers)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM evidence_sources{where} ORDER BY created_at DESC", params).fetchall()
    return [_source(row) for row in rows]


def get_source(source_id: str, *, organization_id: str | None = None) -> EvidenceSource:
    init_db()
    if organization_id:
        require_resource_scope(organization_id, "evidence_source", source_id)
    with connect() as conn:
        row = conn.execute("SELECT * FROM evidence_sources WHERE source_id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence source: {source_id}")
    return _source(row)


def create_snapshot(payload: EvidenceSnapshotCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidenceSnapshot:
    init_db()
    get_source(payload.source_id, organization_id=organization_id)
    observed_at = _normalize_time(payload.observed_at)
    cutoff_at = _normalize_time(payload.cutoff_at)
    if _as_datetime(observed_at) > _as_datetime(cutoff_at):
        raise HTTPException(status_code=422, detail="Evidence observed_at cannot be after cutoff_at")
    if payload.project_id:
        _require_project(payload.project_id)
        if organization_id:
            require_resource_scope(organization_id, "project", payload.project_id)
    canonical = _canonical(payload.content)
    content_hash = _snapshot_digest(
        payload.source_id, payload.project_id, payload.external_ref, payload.title, payload.category,
        canonical, observed_at, cutoff_at,
    )
    snapshot_id = f"evs_{uuid4().hex[:20]}"
    captured_at = _now()
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_snapshots
                (snapshot_id, source_id, project_id, external_ref, title, category, content_json,
                 content_text, observed_at, cutoff_at, captured_at, content_hash, created_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, payload.source_id, payload.project_id, payload.external_ref, payload.title,
                 payload.category, canonical, payload.content_text, observed_at, cutoff_at, captured_at,
                 content_hash, actor.user_id),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM evidence_snapshots WHERE source_id = ? AND external_ref = ? AND content_hash = ?",
                    (payload.source_id, payload.external_ref, content_hash),
                ).fetchone()
            if row:
                snapshot = _snapshot(row)
                if organization_id:
                    scope_resource(organization_id, "evidence_snapshot", snapshot.snapshot_id)
                return snapshot
        raise
    if organization_id:
        scope_resource(organization_id, "evidence_snapshot", snapshot_id)
    return get_snapshot(snapshot_id, organization_id=organization_id)


def get_snapshot(snapshot_id: str, *, organization_id: str | None = None) -> EvidenceSnapshot:
    init_db()
    if organization_id:
        require_resource_scope(organization_id, "evidence_snapshot", snapshot_id)
    with connect() as conn:
        row = conn.execute("SELECT * FROM evidence_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence snapshot: {snapshot_id}")
    return _snapshot(row)


def create_claim(payload: EvidenceClaimCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidenceClaim:
    init_db()
    cutoff_at = _normalize_time(payload.cutoff_at)
    if payload.project_id:
        _require_project(payload.project_id)
        if organization_id:
            require_resource_scope(organization_id, "project", payload.project_id)
    snapshots = [get_snapshot(snapshot_id, organization_id=organization_id) for snapshot_id in payload.snapshot_ids]
    if any(_as_datetime(item.observed_at) > _as_datetime(cutoff_at) for item in snapshots):
        raise HTTPException(status_code=422, detail="Claim references evidence newer than its cutoff")
    claim_material = {
        "project_id": payload.project_id,
        "run_id": payload.run_id,
        "statement": payload.statement.strip(),
        "claim_type": payload.claim_type,
        "confidence": payload.confidence,
        "valid_from": payload.valid_from,
        "valid_to": payload.valid_to,
        "cutoff_at": cutoff_at,
    }
    claim_hash = _sha256(_canonical(claim_material))
    claim_id = f"clm_{uuid4().hex[:20]}"
    now = _now()
    created = True
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_claims
                (claim_id, project_id, run_id, statement, claim_type, confidence, valid_from, valid_to,
                 cutoff_at, claim_hash, created_by_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (claim_id, payload.project_id, payload.run_id, payload.statement.strip(), payload.claim_type,
                 payload.confidence, payload.valid_from, payload.valid_to, cutoff_at, claim_hash, actor.user_id, now),
            )
    except Exception as exc:
        if "UNIQUE" not in str(exc).upper():
            raise
        created = False
        with connect() as conn:
            row = conn.execute("SELECT claim_id FROM evidence_claims WHERE claim_hash = ?", (claim_hash,)).fetchone()
        if row is None:
            raise
        claim_id = row["claim_id"]
    for snapshot in snapshots:
        _link_claim(claim_id, snapshot.snapshot_id, payload.relation, "", "", {})
    if organization_id:
        scope_resource(organization_id, "evidence_claim", claim_id)
    return get_claim(claim_id, organization_id=organization_id)


def get_claim(claim_id: str, *, organization_id: str | None = None) -> EvidenceClaim:
    init_db()
    if organization_id:
        require_resource_scope(organization_id, "evidence_claim", claim_id)
    with connect() as conn:
        row = conn.execute("SELECT * FROM evidence_claims WHERE claim_id = ?", (claim_id,)).fetchone()
        links = conn.execute(
            "SELECT snapshot_id, relation, citation_label, excerpt, locator_json FROM evidence_links WHERE claim_id = ? ORDER BY created_at",
            (claim_id,),
        ).fetchall()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence claim: {claim_id}")
    return _claim(row, links)


def search_evidence(
    *, query: str = "", project_id: str | None = None, category: str | None = None,
    cutoff_at: str | None = None, limit: int = 50, organization_id: str | None = None,
) -> EvidenceSearchResult:
    init_db()
    limit = max(1, min(limit, 200))
    normalized_cutoff = _normalize_time(cutoff_at) if cutoff_at else None
    snapshot_clauses, snapshot_params = [], []
    claim_clauses, claim_params = [], []
    if organization_id:
        snapshot_ids = sorted(scoped_resource_ids(organization_id, "evidence_snapshot"))
        claim_ids = sorted(scoped_resource_ids(organization_id, "evidence_claim"))
        snapshot_clauses.append(f"snapshot_id IN ({', '.join('?' for _ in snapshot_ids)})" if snapshot_ids else "1 = 0")
        claim_clauses.append(f"claim_id IN ({', '.join('?' for _ in claim_ids)})" if claim_ids else "1 = 0")
        snapshot_params.extend(snapshot_ids)
        claim_params.extend(claim_ids)
    if project_id:
        snapshot_clauses.append("project_id = ?")
        claim_clauses.append("project_id = ?")
        snapshot_params.append(project_id)
        claim_params.append(project_id)
    if category:
        snapshot_clauses.append("category = ?")
        snapshot_params.append(category)
    if normalized_cutoff:
        snapshot_clauses.extend(["observed_at <= ?", "cutoff_at <= ?"])
        snapshot_params.extend([normalized_cutoff, normalized_cutoff])
        claim_clauses.append("cutoff_at <= ?")
        claim_params.append(normalized_cutoff)
    if query.strip():
        token = f"%{query.strip()}%"
        snapshot_clauses.append("(title LIKE ? OR content_text LIKE ? OR external_ref LIKE ?)")
        snapshot_params.extend([token, token, token])
        claim_clauses.append("statement LIKE ?")
        claim_params.append(token)
    snapshot_where = f" WHERE {' AND '.join(snapshot_clauses)}" if snapshot_clauses else ""
    claim_where = f" WHERE {' AND '.join(claim_clauses)}" if claim_clauses else ""
    with connect() as conn:
        snapshot_rows = conn.execute(
            f"SELECT * FROM evidence_snapshots{snapshot_where} ORDER BY cutoff_at DESC, captured_at DESC LIMIT ?",
            [*snapshot_params, limit],
        ).fetchall()
        claim_rows = conn.execute(
            f"SELECT * FROM evidence_claims{claim_where} ORDER BY cutoff_at DESC, created_at DESC LIMIT ?",
            [*claim_params, limit],
        ).fetchall()
    snapshots = [_snapshot_summary(row) for row in snapshot_rows]
    claims = [get_claim(row["claim_id"], organization_id=organization_id) for row in claim_rows]
    return EvidenceSearchResult(query=query, cutoff_at=normalized_cutoff, total=len(snapshots) + len(claims), snapshots=snapshots, claims=claims)


def create_pack(payload: EvidencePackCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidencePack:
    init_db()
    cutoff_at = _normalize_time(payload.cutoff_at)
    if payload.project_id:
        _require_project(payload.project_id)
        if organization_id:
            require_resource_scope(organization_id, "project", payload.project_id)
    snapshot_ids = list(dict.fromkeys(payload.snapshot_ids))
    claim_ids = list(dict.fromkeys(payload.claim_ids))
    if not snapshot_ids and payload.project_id:
        results = search_evidence(project_id=payload.project_id, cutoff_at=cutoff_at, limit=200, organization_id=organization_id)
        snapshot_ids = [item.snapshot_id for item in results.snapshots]
        claim_ids = [item.claim_id for item in results.claims]
    snapshots = [get_snapshot(item, organization_id=organization_id) for item in snapshot_ids]
    claims = [get_claim(item, organization_id=organization_id) for item in claim_ids]
    if any(_as_datetime(item.observed_at) > _as_datetime(cutoff_at) for item in snapshots):
        raise HTTPException(status_code=422, detail="Evidence pack contains a future snapshot")
    if any(_as_datetime(item.cutoff_at) > _as_datetime(cutoff_at) for item in claims):
        raise HTTPException(status_code=422, detail="Evidence pack contains a future claim")
    manifest = {
        "schema_version": "evidence-pack.v1",
        "project_id": payload.project_id,
        "run_id": payload.run_id,
        "cutoff_at": cutoff_at,
        "snapshot_hashes": [
            {item.snapshot_id: item.content_hash} for item in sorted(snapshots, key=lambda item: item.snapshot_id)
        ],
        "claim_hashes": [
            {item.claim_id: item.claim_hash} for item in sorted(claims, key=lambda item: item.claim_id)
        ],
    }
    manifest_json = _canonical(manifest)
    manifest_hash = _sha256(manifest_json)
    pack_id = f"evp_{uuid4().hex[:20]}"
    now = _now()
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_packs
                (pack_id, project_id, run_id, name, cutoff_at, manifest_json, manifest_hash, created_by_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pack_id, payload.project_id, payload.run_id, payload.name, cutoff_at, manifest_json,
                 manifest_hash, actor.user_id, now),
            )
            positions = {snapshot.snapshot_id: index for index, snapshot in enumerate(snapshots)}
            linked_claims = {link["snapshot_id"]: claim.claim_id for claim in claims for link in claim.links}
            for snapshot in snapshots:
                conn.execute(
                    "INSERT INTO evidence_pack_items(pack_id, snapshot_id, claim_id, position, created_at) VALUES (?, ?, ?, ?, ?)",
                    (pack_id, snapshot.snapshot_id, linked_claims.get(snapshot.snapshot_id), positions[snapshot.snapshot_id], now),
                )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            with connect() as conn:
                row = conn.execute("SELECT pack_id FROM evidence_packs WHERE manifest_hash = ?", (manifest_hash,)).fetchone()
            if row:
                if organization_id:
                    scope_resource(organization_id, "evidence_pack", row["pack_id"])
                return get_pack(row["pack_id"], organization_id=organization_id)
        raise
    if organization_id:
        scope_resource(organization_id, "evidence_pack", pack_id)
    return get_pack(pack_id, organization_id=organization_id)


def get_pack(pack_id: str, *, organization_id: str | None = None) -> EvidencePack:
    init_db()
    if organization_id:
        require_resource_scope(organization_id, "evidence_pack", pack_id)
    with connect() as conn:
        row = conn.execute("SELECT * FROM evidence_packs WHERE pack_id = ?", (pack_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence pack: {pack_id}")
    pack = _pack(row)
    if _sha256(_canonical(pack.manifest)) != pack.manifest_hash:
        raise HTTPException(status_code=409, detail="Evidence pack integrity verification failed")
    return pack


def sync_project_evidence(project_id: str, actor: UserIdentity, *, run_id: str | None = None, organization_id: str | None = None) -> EvidenceSyncResult:
    init_db()
    _require_project(project_id)
    if organization_id:
        require_resource_scope(organization_id, "project", project_id)
    with connect() as conn:
        run = conn.execute(
            "SELECT * FROM research_runs WHERE project_id = ? " + ("AND run_id = ? " if run_id else "") + "ORDER BY completed_at DESC, run_id DESC LIMIT 1",
            (project_id, run_id) if run_id else (project_id,),
        ).fetchone()
    if run is None:
        return EvidenceSyncResult(project_id=project_id, summary=project_evidence_summary(project_id))
    run_id = run["run_id"]
    before = _counts(project_id)
    run_source = create_source(EvidenceSourceCreate(
        source_type="deterministic_run", name="WorldPulse deterministic run",
        locator=f"worldpulse://projects/{project_id}/runs/{run_id}", publisher="WorldPulse",
        trust_tier="deterministic", metadata={"run_id": run_id, "immutable": True},
    ), actor, organization_id=organization_id)
    run_content = {
        "data_snapshot": loads(run["data_snapshot"], {}),
        "risk_snapshot": loads(run["risk_snapshot"], {}),
        "event_snapshot": loads(run["event_snapshot"], []),
        "simulation_snapshot": loads(run["simulation_snapshot"], {}),
        "backtest_snapshot": loads(run["backtest_snapshot"], {}),
    }
    run_snapshot = create_snapshot(EvidenceSnapshotCreate(
        source_id=run_source.source_id, project_id=project_id, external_ref=run_id,
        title=f"Deterministic run {run_id}", category="deterministic_run", content=run_content,
        content_text=str(run["summary"]), observed_at=run["completed_at"] or run["started_at"],
        cutoff_at=run["completed_at"] or run["started_at"],
    ), actor, organization_id=organization_id)
    with connect() as conn:
        graph = conn.execute("SELECT * FROM causal_graph_snapshots WHERE project_id = ? AND run_id = ? ORDER BY generated_at DESC LIMIT 1", (project_id, run_id)).fetchone()
        report = conn.execute("SELECT * FROM ai_reports WHERE project_id = ? AND run_id = ? ORDER BY generated_at DESC LIMIT 1", (project_id, run_id)).fetchone()
    snapshot_by_kind = {"evidence": run_snapshot, "backtest": run_snapshot}
    if graph:
        source = create_source(EvidenceSourceCreate(
            source_type="causal_graph", name="WorldPulse causal graph",
            locator=f"worldpulse://projects/{project_id}/graphs/{graph['graph_id']}", publisher="WorldPulse",
            trust_tier="derived", metadata={"run_id": run_id, "immutable": True},
        ), actor, organization_id=organization_id)
        snapshot_by_kind["causal_edge"] = create_snapshot(EvidenceSnapshotCreate(
            source_id=source.source_id, project_id=project_id, external_ref=graph["graph_id"],
            title=f"Causal graph {graph['graph_id']}", category="causal_graph",
            content={"nodes": loads(graph["nodes"], []), "edges": loads(graph["edges"], []), "confidence": graph["confidence"], "evidence_sources": loads(graph["evidence_sources"], [])},
            content_text=" ".join(loads(graph["evidence_sources"], [])), observed_at=graph["generated_at"], cutoff_at=graph["generated_at"],
        ), actor, organization_id=organization_id)
    if report:
        report_source = create_source(EvidenceSourceCreate(
            source_type="report", name="WorldPulse project report",
            locator=f"worldpulse://projects/{project_id}/reports/{report['report_id']}", publisher="WorldPulse",
            trust_tier="explanatory", metadata={"run_id": run_id, "immutable": True},
        ), actor, organization_id=organization_id)
        report_snapshot = create_snapshot(EvidenceSnapshotCreate(
            source_id=report_source.source_id, project_id=project_id, external_ref=report["report_id"],
            title=report["title"], category="report", content={
                "summary": report["summary"], "key_findings": loads(report["key_findings"], []),
                "evidence": loads(report["evidence"], []), "citations": loads(report["citations"], []),
                "disclaimer": report["disclaimer"],
            }, content_text=f"{report['title']}\n{report['summary']}\n{report['markdown']}",
            observed_at=report["generated_at"], cutoff_at=report["generated_at"],
        ), actor, organization_id=organization_id)
        findings = loads(report["key_findings"], [])
        citations = loads(report["citations"], [])
        for index, finding in enumerate(findings):
            matching = [item for item in citations if int(item.get("finding_index", -1)) == index]
            snapshots = [snapshot_by_kind.get(item.get("kind"), report_snapshot) for item in matching] or [report_snapshot]
            claim = create_claim(EvidenceClaimCreate(
                project_id=project_id, run_id=run_id, statement=str(finding), claim_type="report_finding",
                confidence=max([float(item.get("confidence", 72)) / 100 for item in matching] or [0.72]),
                cutoff_at=report["generated_at"], snapshot_ids=list(dict.fromkeys(item.snapshot_id for item in snapshots)),
            ), actor, organization_id=organization_id)
            for citation in matching:
                snapshot = snapshot_by_kind.get(citation.get("kind"), report_snapshot)
                _link_claim(claim.claim_id, snapshot.snapshot_id, "supports", str(citation.get("citation_id", "")), str(citation.get("summary", "")), citation)
    after = _counts(project_id)
    if organization_id:
        _scope_project_evidence(organization_id, project_id)
    return EvidenceSyncResult(
        project_id=project_id, run_id=run_id,
        sources_created=after["sources"] - before["sources"], snapshots_created=after["snapshots"] - before["snapshots"],
        claims_created=after["claims"] - before["claims"], links_created=after["links"] - before["links"],
        summary=project_evidence_summary(project_id),
    )


def sync_calibration_evidence(actor: UserIdentity, *, organization_id: str | None = None) -> dict:
    init_db()
    from app.services.calibration import ensure_calibration_cases

    ensure_calibration_cases()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM calibration_cases WHERE is_active = 1 ORDER BY case_id").fetchall()
    source = create_source(EvidenceSourceCreate(
        source_type="calibration_corpus", name="WorldPulse V1.2 frozen benchmark corpus",
        locator="worldpulse://calibration/v1", publisher="WorldPulse", trust_tier="frozen_benchmark",
        metadata={"version": "calibration-case.v1", "future_data_prohibited": True},
    ), actor, organization_id=organization_id)
    before = _global_counts()
    for row in rows:
        content = {
            "input_snapshot": loads(row["input_snapshot"], {}), "labels": loads(row["labels_json"], {}),
            "evidence": loads(row["evidence_json"], []), "case_hash": row["case_hash"],
            "observation_window_days": row["observation_window_days"], "label_confidence": row["label_confidence"],
        }
        create_snapshot(EvidenceSnapshotCreate(
            source_id=source.source_id, external_ref=row["case_id"], title=row["title"], category="calibration_case",
            content=content, content_text=f"{row['category']} {row['title']} {row['case_id']}",
            observed_at=row["cutoff_date"], cutoff_at=row["cutoff_date"],
        ), actor, organization_id=organization_id)
    after = _global_counts()
    return {"case_count": len(rows), "snapshots_created": after["snapshots"] - before["snapshots"], "source_id": source.source_id}


def project_evidence_summary(project_id: str) -> ProjectEvidenceSummary:
    init_db()
    _require_project(project_id)
    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM evidence_snapshots WHERE project_id = ?) AS snapshots,
              (SELECT COUNT(*) FROM evidence_claims WHERE project_id = ?) AS claims,
              (SELECT COUNT(DISTINCT c.claim_id) FROM evidence_claims c JOIN evidence_links l ON l.claim_id = c.claim_id WHERE c.project_id = ?) AS linked_claims,
              (SELECT COUNT(*) FROM evidence_packs WHERE project_id = ?) AS packs,
              (SELECT MAX(cutoff_at) FROM evidence_snapshots WHERE project_id = ?) AS latest_cutoff
            """, (project_id, project_id, project_id, project_id, project_id),
        ).fetchone()
        source_rows = conn.execute(
            "SELECT DISTINCT s.* FROM evidence_sources s JOIN evidence_snapshots e ON e.source_id = s.source_id WHERE e.project_id = ? ORDER BY s.name",
            (project_id,),
        ).fetchall()
        snapshot_rows = conn.execute("SELECT * FROM evidence_snapshots WHERE project_id = ? ORDER BY cutoff_at DESC, captured_at DESC LIMIT 20", (project_id,)).fetchall()
        claim_rows = conn.execute("SELECT claim_id FROM evidence_claims WHERE project_id = ? ORDER BY cutoff_at DESC, created_at DESC LIMIT 20", (project_id,)).fetchall()
        pack_row = conn.execute("SELECT * FROM evidence_packs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
    snapshots = [_snapshot_summary(row) for row in snapshot_rows]
    failed = [item for item in snapshots if item.integrity_status == "failed"]
    claims = int(counts["claims"] or 0)
    linked = int(counts["linked_claims"] or 0)
    return ProjectEvidenceSummary(
        project_id=project_id, source_count=len(source_rows), snapshot_count=int(counts["snapshots"] or 0),
        claim_count=claims, linked_claim_count=linked, pack_count=int(counts["packs"] or 0),
        coverage=round(linked / claims, 4) if claims else 0.0,
        integrity_status="failed" if failed else "verified" if snapshots else "empty",
        cutoff_safe=not any(_as_datetime(item.observed_at) > _as_datetime(item.cutoff_at) for item in snapshots),
        latest_cutoff_at=counts["latest_cutoff"], latest_pack=_pack(pack_row) if pack_row else None,
        sources=[_source(row) for row in source_rows], recent_snapshots=snapshots,
        recent_claims=[get_claim(row["claim_id"]) for row in claim_rows], generated_at=_now(),
    )


def evidence_manifest_for_run(project_id: str, run_id: str) -> dict | None:
    init_db()
    with connect() as conn:
        pack = conn.execute("SELECT * FROM evidence_packs WHERE project_id = ? AND (run_id = ? OR run_id IS NULL) ORDER BY created_at DESC LIMIT 1", (project_id, run_id)).fetchone()
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
    return {
        "schema_version": "evidence-manifest.v1",
        "pack_id": pack["pack_id"] if pack else None,
        "pack_hash": pack["manifest_hash"] if pack else None,
        "snapshot_hashes": {row["snapshot_id"]: row["content_hash"] for row in snapshots},
        "cutoff_at": max((row["cutoff_at"] for row in snapshots), default=pack["cutoff_at"] if pack else None),
        "integrity": "verified",
    }


def _scope_project_evidence(organization_id: str, project_id: str) -> None:
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
    for resource_type, rows, key in (
        ("evidence_source", source_rows, "source_id"),
        ("evidence_snapshot", snapshot_rows, "snapshot_id"),
        ("evidence_claim", claim_rows, "claim_id"),
        ("evidence_pack", pack_rows, "pack_id"),
    ):
        for row in rows:
            scope_resource(organization_id, resource_type, row[key])


def _link_claim(claim_id: str, snapshot_id: str, relation: str, citation_label: str, excerpt: str, locator: dict) -> bool:
    link_id = f"evl_{uuid4().hex[:20]}"
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO evidence_links(link_id, claim_id, snapshot_id, relation, citation_label, excerpt, locator_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (link_id, claim_id, snapshot_id, relation, citation_label, excerpt, dumps(locator), _now()),
            )
        return True
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            return False
        raise


def _source(row) -> EvidenceSource:
    return EvidenceSource(
        source_id=row["source_id"], source_type=row["source_type"], name=row["name"], locator=row["locator"],
        publisher=row["publisher"], status=row["status"], trust_tier=row["trust_tier"],
        metadata=loads(row["metadata_json"], {}), created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"], retired_at=row["retired_at"],
    )


def _snapshot(row) -> EvidenceSnapshot:
    content = loads(row["content_json"], {})
    integrity = "verified" if _snapshot_digest(
        row["source_id"], row["project_id"], row["external_ref"], row["title"], row["category"],
        _canonical(content), row["observed_at"], row["cutoff_at"],
    ) == row["content_hash"] else "failed"
    return EvidenceSnapshot(
        snapshot_id=row["snapshot_id"], source_id=row["source_id"], project_id=row["project_id"],
        external_ref=row["external_ref"], title=row["title"], category=row["category"], content=content,
        content_text=row["content_text"], observed_at=row["observed_at"], cutoff_at=row["cutoff_at"],
        captured_at=row["captured_at"], content_hash=row["content_hash"], created_by_user_id=row["created_by_user_id"],
        integrity_status=integrity,
    )


def _snapshot_summary(row) -> EvidenceSnapshotSummary:
    full = _snapshot(row)
    return EvidenceSnapshotSummary(**full.model_dump(exclude={"content", "content_text"}))


def _claim(row, links: Iterable | None = None) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=row["claim_id"], project_id=row["project_id"], run_id=row["run_id"], statement=row["statement"],
        claim_type=row["claim_type"], confidence=float(row["confidence"]), valid_from=row["valid_from"], valid_to=row["valid_to"],
        cutoff_at=row["cutoff_at"], claim_hash=row["claim_hash"], created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"], links=[{
            "snapshot_id": item["snapshot_id"], "relation": item["relation"], "citation_label": item["citation_label"],
            "excerpt": item["excerpt"], "locator": loads(item["locator_json"], {}),
        } for item in (links or [])],
    )


def _pack(row) -> EvidencePack:
    return EvidencePack(
        pack_id=row["pack_id"], project_id=row["project_id"], run_id=row["run_id"], name=row["name"],
        cutoff_at=row["cutoff_at"], manifest=loads(row["manifest_json"], {}), manifest_hash=row["manifest_hash"],
        created_by_user_id=row["created_by_user_id"], created_at=row["created_at"],
    )


def _require_project(project_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")


def _counts(project_id: str) -> dict[str, int]:
    with connect() as conn:
        row = conn.execute(
            """SELECT
            (SELECT COUNT(DISTINCT source_id) FROM evidence_snapshots WHERE project_id = ?) sources,
            (SELECT COUNT(*) FROM evidence_snapshots WHERE project_id = ?) snapshots,
            (SELECT COUNT(*) FROM evidence_claims WHERE project_id = ?) claims,
            (SELECT COUNT(*) FROM evidence_links l JOIN evidence_claims c ON c.claim_id = l.claim_id WHERE c.project_id = ?) links""",
            (project_id, project_id, project_id, project_id),
        ).fetchone()
    return {key: int(row[key] or 0) for key in ("sources", "snapshots", "claims", "links")}


def _global_counts() -> dict[str, int]:
    with connect() as conn:
        row = conn.execute("SELECT (SELECT COUNT(*) FROM evidence_sources) sources, (SELECT COUNT(*) FROM evidence_snapshots) snapshots").fetchone()
    return {"sources": int(row["sources"]), "snapshots": int(row["snapshots"])}


def _canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot_digest(
    source_id: str, project_id: str | None, external_ref: str, title: str, category: str,
    canonical_content: str, observed_at: str, cutoff_at: str,
) -> str:
    return _sha256(_canonical({
        "schema_version": "evidence-snapshot.v1", "source_id": source_id, "project_id": project_id,
        "external_ref": external_ref, "title": title, "category": category,
        "content": json.loads(canonical_content), "observed_at": observed_at, "cutoff_at": cutoff_at,
    }))


def _normalize_time(value: str | None) -> str:
    if not value:
        raise HTTPException(status_code=422, detail="A valid evidence timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid evidence timestamp: {value}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="milliseconds")


def _as_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
