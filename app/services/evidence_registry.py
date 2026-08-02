from __future__ import annotations

from datetime import datetime, timezone
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
    EvidenceSource,
    EvidenceSourceCreate,
    EvidenceSyncResult,
    ProjectEvidenceSummary,
)
from app.core.trust_models import UserIdentity
from app.services.evidence.hashing import (
    canonical_json as _canonical,
    sha256_text as _sha256,
    snapshot_digest as _snapshot_digest,
)
from app.services.evidence.mappers import snapshot_from_row
from app.services.evidence.repository import EvidenceRepository
from app.services.project_store import connect, dumps, init_db, loads
from app.services.organizations import require_resource_scope, scope_resource, scoped_resource_ids


_repository = EvidenceRepository()


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
            source = _repository.find_source(payload.source_type, payload.locator)
            if source:
                if organization_id:
                    scope_resource(organization_id, "evidence_source", source.source_id)
                return source
        raise
    if organization_id:
        scope_resource(organization_id, "evidence_source", source_id)
    return get_source(source_id, organization_id=organization_id)


def list_sources(*, status: str | None = None, source_type: str | None = None, organization_id: str | None = None) -> list[EvidenceSource]:
    identifiers = sorted(scoped_resource_ids(organization_id, "evidence_source")) if organization_id else None
    return _repository.list_sources(status=status, source_type=source_type, source_ids=identifiers)


def get_source(source_id: str, *, organization_id: str | None = None) -> EvidenceSource:
    if organization_id:
        require_resource_scope(organization_id, "evidence_source", source_id)
    source = _repository.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence source: {source_id}")
    return source


def create_snapshot(
    payload: EvidenceSnapshotCreate,
    actor: UserIdentity,
    *,
    organization_id: str | None = None,
    quota_reserved: bool = False,
) -> EvidenceSnapshot:
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
    existing_snapshot = None
    try:
        with connect() as conn:
            if organization_id:
                from app.db.postgres import is_postgres_url
                from app.services.operations import enforce_quota, lock_organization_quota

                if not is_postgres_url():
                    conn.execute("BEGIN IMMEDIATE")
                lock_organization_quota(organization_id, conn)
            existing = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE source_id = ? AND external_ref = ? AND content_hash = ?",
                (payload.source_id, payload.external_ref, content_hash),
            ).fetchone()
            if existing:
                existing_snapshot = snapshot_from_row(existing)
            else:
                if organization_id and not quota_reserved:
                    enforce_quota(organization_id, "evidence_snapshot", connection=conn)
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
            snapshot = _repository.find_snapshot(payload.source_id, payload.external_ref, content_hash)
            if snapshot:
                if organization_id:
                    scope_resource(organization_id, "evidence_snapshot", snapshot.snapshot_id)
                return snapshot
        raise
    if existing_snapshot is not None:
        if organization_id:
            scope_resource(organization_id, "evidence_snapshot", existing_snapshot.snapshot_id)
        return existing_snapshot
    if organization_id:
        scope_resource(organization_id, "evidence_snapshot", snapshot_id)
    return get_snapshot(snapshot_id, organization_id=organization_id)


def get_snapshot(snapshot_id: str, *, organization_id: str | None = None) -> EvidenceSnapshot:
    if organization_id:
        require_resource_scope(organization_id, "evidence_snapshot", snapshot_id)
    snapshot = _repository.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence snapshot: {snapshot_id}")
    return snapshot


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
        existing_claim_id = _repository.find_claim_id(claim_hash)
        if existing_claim_id is None:
            raise
        claim_id = existing_claim_id
    for snapshot in snapshots:
        _link_claim(claim_id, snapshot.snapshot_id, payload.relation, "", "", {})
    if organization_id:
        scope_resource(organization_id, "evidence_claim", claim_id)
    return get_claim(claim_id, organization_id=organization_id)


def get_claim(claim_id: str, *, organization_id: str | None = None) -> EvidenceClaim:
    if organization_id:
        require_resource_scope(organization_id, "evidence_claim", claim_id)
    claim = _repository.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence claim: {claim_id}")
    return claim


def search_evidence(
    *, query: str = "", project_id: str | None = None, category: str | None = None,
    cutoff_at: str | None = None, limit: int = 50, organization_id: str | None = None,
) -> EvidenceSearchResult:
    limit = max(1, min(limit, 200))
    normalized_cutoff = _normalize_time(cutoff_at) if cutoff_at else None
    snapshot_ids = sorted(scoped_resource_ids(organization_id, "evidence_snapshot")) if organization_id else None
    claim_ids = sorted(scoped_resource_ids(organization_id, "evidence_claim")) if organization_id else None
    snapshots = _repository.search_snapshots(
        query=query,
        project_id=project_id,
        category=category,
        cutoff_at=normalized_cutoff,
        limit=limit,
        snapshot_ids=snapshot_ids,
    )
    claims = _repository.search_claims(
        query=query,
        project_id=project_id,
        cutoff_at=normalized_cutoff,
        limit=limit,
        claim_ids=claim_ids,
    )
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
            existing_pack_id = _repository.find_pack_id(manifest_hash)
            if existing_pack_id:
                if organization_id:
                    scope_resource(organization_id, "evidence_pack", existing_pack_id)
                return get_pack(existing_pack_id, organization_id=organization_id)
        raise
    if organization_id:
        scope_resource(organization_id, "evidence_pack", pack_id)
    return get_pack(pack_id, organization_id=organization_id)


def get_pack(pack_id: str, *, organization_id: str | None = None) -> EvidencePack:
    if organization_id:
        require_resource_scope(organization_id, "evidence_pack", pack_id)
    pack = _repository.get_pack(pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Unknown evidence pack: {pack_id}")
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
    _require_project(project_id)
    read_model = _repository.project_read_model(project_id)
    snapshots = read_model.recent_snapshots
    failed = [item for item in snapshots if item.integrity_status == "failed"]
    claims = read_model.claim_count
    linked = read_model.linked_claim_count
    return ProjectEvidenceSummary(
        project_id=project_id, source_count=len(read_model.sources), snapshot_count=read_model.snapshot_count,
        claim_count=claims, linked_claim_count=linked, pack_count=read_model.pack_count,
        coverage=round(linked / claims, 4) if claims else 0.0,
        integrity_status="failed" if failed else "verified" if snapshots else "empty",
        cutoff_safe=not any(_as_datetime(item.observed_at) > _as_datetime(item.cutoff_at) for item in snapshots),
        latest_cutoff_at=read_model.latest_cutoff_at, latest_pack=read_model.latest_pack,
        sources=read_model.sources, recent_snapshots=snapshots,
        recent_claims=read_model.recent_claims, generated_at=_now(),
    )


def evidence_manifest_for_run(project_id: str, run_id: str) -> dict | None:
    read_model = _repository.manifest_read_model(project_id, run_id)
    if read_model is None:
        return None
    return {
        "schema_version": "evidence-manifest.v1",
        "pack_id": read_model.pack_id,
        "pack_hash": read_model.pack_hash,
        "snapshot_hashes": read_model.snapshot_hashes,
        "cutoff_at": max(read_model.snapshot_cutoffs, default=read_model.pack_cutoff_at),
        "integrity": "verified",
    }


def _scope_project_evidence(organization_id: str, project_id: str) -> None:
    for resource_type, identifiers in _repository.project_resource_ids(project_id).items():
        for identifier in identifiers:
            scope_resource(organization_id, resource_type, identifier)


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


def _require_project(project_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")


def _counts(project_id: str) -> dict[str, int]:
    return _repository.project_counts(project_id)


def _global_counts() -> dict[str, int]:
    return _repository.global_counts()


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
