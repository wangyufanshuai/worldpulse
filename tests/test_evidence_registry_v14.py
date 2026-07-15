from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.core.evidence_models import EvidenceClaimCreate, EvidencePackCreate, EvidenceSnapshotCreate, EvidenceSourceCreate
from app.main import app
from app.services import evidence_registry, project_store
from app.services.auth import create_user, ensure_system_user


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "evidence.db")
    actor = ensure_system_user()
    with project_store.connect() as conn:
        conn.execute(
            """
            INSERT INTO research_projects
            (project_id, title, question, region, asset_scope, event_window_days, event_types,
             mode, scenario_config, status, created_at, updated_at)
            VALUES ('project_evidence', 'Evidence project', 'What changed?', 'global', '[]', 30,
                    '[]', 'war_room', '{}', 'ready', '2026-07-01', '2026-07-01')
            """
        )
    return actor


def test_snapshot_hash_cutoff_search_and_pack(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    source = evidence_registry.create_source(EvidenceSourceCreate(
        source_type="dataset", name="Frozen dataset", locator="worldpulse://test/frozen",
    ), actor)
    snapshot = evidence_registry.create_snapshot(EvidenceSnapshotCreate(
        source_id=source.source_id, project_id="project_evidence", external_ref="record-1",
        title="Energy pressure snapshot", category="energy", content={"pressure": 72.5},
        content_text="Energy pressure rose", observed_at="2026-06-01", cutoff_at="2026-06-30",
    ), actor)
    assert snapshot.integrity_status == "verified"
    assert len(snapshot.content_hash) == 64
    same = evidence_registry.create_snapshot(EvidenceSnapshotCreate(
        source_id=source.source_id, project_id="project_evidence", external_ref="record-1",
        title="Energy pressure snapshot", category="energy", content={"pressure": 72.5},
        content_text="Energy pressure rose", observed_at="2026-06-01", cutoff_at="2026-06-30",
    ), actor)
    assert same.snapshot_id == snapshot.snapshot_id

    claim = evidence_registry.create_claim(EvidenceClaimCreate(
        project_id="project_evidence", statement="Energy pressure reached 72.5.", cutoff_at="2026-06-30",
        snapshot_ids=[snapshot.snapshot_id], confidence=0.88,
    ), actor)
    assert claim.links[0]["snapshot_id"] == snapshot.snapshot_id
    assert evidence_registry.search_evidence(query="Energy", cutoff_at="2026-06-30").total == 2
    assert evidence_registry.search_evidence(query="Energy", cutoff_at="2026-05-31").total == 0

    pack = evidence_registry.create_pack(EvidencePackCreate(
        project_id="project_evidence", name="June evidence", cutoff_at="2026-06-30",
        snapshot_ids=[snapshot.snapshot_id], claim_ids=[claim.claim_id],
    ), actor)
    assert pack.manifest["schema_version"] == "evidence-pack.v1"
    assert evidence_registry.get_pack(pack.pack_id).manifest_hash == pack.manifest_hash


def test_future_evidence_and_tampering_fail_closed(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    source = evidence_registry.create_source(EvidenceSourceCreate(
        source_type="dataset", name="Source", locator="worldpulse://test/future",
    ), actor)
    with pytest.raises(Exception) as exc:
        evidence_registry.create_snapshot(EvidenceSnapshotCreate(
            source_id=source.source_id, project_id="project_evidence", external_ref="future",
            title="Future record", category="trade", content={"value": 1},
            observed_at="2026-07-02", cutoff_at="2026-07-01",
        ), actor)
    assert getattr(exc.value, "status_code", None) == 422

    snapshot = evidence_registry.create_snapshot(EvidenceSnapshotCreate(
        source_id=source.source_id, project_id="project_evidence", external_ref="safe",
        title="Safe record", category="trade", content={"value": 1},
        observed_at="2026-06-01", cutoff_at="2026-07-01",
    ), actor)
    with project_store.connect() as conn:
        conn.execute("UPDATE evidence_snapshots SET content_json = '{\"value\":2}' WHERE snapshot_id = ?", (snapshot.snapshot_id,))
    assert evidence_registry.get_snapshot(snapshot.snapshot_id).integrity_status == "failed"
    assert evidence_registry.project_evidence_summary("project_evidence").integrity_status == "failed"


def test_v4_api_in_local_development_mode(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "disabled")
    with TestClient(app) as client:
        created = client.post("/api/v4/evidence/sources", json={
            "source_type": "internal", "name": "API source", "locator": "worldpulse://api/source",
        })
        assert created.status_code == 200
        assert client.get("/api/v4/evidence/sources").json()[0]["name"] == "API source"
        summary = client.get("/api/v4/projects/project_evidence/evidence-summary")
        assert summary.status_code == 200
        assert summary.json()["integrity_status"] == "empty"


def test_v4_viewer_can_read_but_cannot_write(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "local")
    create_user("evidence-viewer", "viewer evidence phrase", "Evidence Viewer", "viewer")
    with TestClient(app) as client:
        login = client.post("/api/v3/auth/login", json={"username": "evidence-viewer", "password": "viewer evidence phrase"})
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        assert client.get("/api/v4/projects/project_evidence/evidence-summary").status_code == 200
        denied = client.post("/api/v4/evidence/sources", headers={"X-CSRF-Token": csrf}, json={
            "source_type": "internal", "name": "Forbidden source", "locator": "worldpulse://forbidden",
        })
        assert denied.status_code == 403


def test_project_sync_populates_trust_and_replay_manifests(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "disabled")
    with TestClient(app) as client:
        run = client.post("/api/projects/project_evidence/war-room/run", json={
            "scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.7,
            "propagation": 0.45, "seed": 42,
        })
        assert run.status_code == 200
        run_id = run.json()["latest_run"]["run_id"]
        synced = client.post(f"/api/v4/projects/project_evidence/evidence/sync?run_id={run_id}")
        assert synced.status_code == 200
        assert synced.json()["snapshots_created"] >= 3
        assert synced.json()["summary"]["coverage"] == 1.0

        trust = client.get("/api/v3/projects/project_evidence/trust-summary").json()
        assert trust["evidence_registry"]["integrity_status"] == "verified"
        replay = client.get(f"/api/projects/project_evidence/war-room/replay-pack?run_id={run_id}").json()
        manifest = replay["manifest"]["evidence_manifest"]
        assert manifest["integrity"] == "verified"
        assert manifest["snapshot_hashes"]


def test_calibration_sync_is_idempotent_and_frozen(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    first = evidence_registry.sync_calibration_evidence(actor)
    second = evidence_registry.sync_calibration_evidence(actor)
    assert first["case_count"] >= 30
    assert first["snapshots_created"] >= 30
    assert second["snapshots_created"] == 0
    results = evidence_registry.search_evidence(category="calibration_case", cutoff_at="2026-01-01", limit=100)
    assert len(results.snapshots) >= 30
    assert all(item.observed_at <= item.cutoff_at for item in results.snapshots)
