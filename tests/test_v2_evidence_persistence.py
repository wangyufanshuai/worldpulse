from __future__ import annotations

import json

from app.core.evidence_models import EvidenceSource
from app.services import evidence_registry
from app.services.evidence.hashing import canonical_json, snapshot_digest
from app.services.evidence.mappers import (
    claim_from_row,
    pack_from_row,
    snapshot_from_row,
    snapshot_summary_from_row,
    source_from_row,
)
from app.services.evidence.repository import EvidenceRepository


def test_evidence_row_mappers_preserve_hash_lineage_and_detect_tampering():
    content = {"pressure": 72.5, "region": "global"}
    canonical = canonical_json(content)
    digest = snapshot_digest(
        "src_1",
        "project_1",
        "record_1",
        "Energy pressure",
        "energy",
        canonical,
        "2026-06-01T00:00:00.000",
        "2026-06-30T00:00:00.000",
    )
    row = {
        "snapshot_id": "evs_1",
        "source_id": "src_1",
        "project_id": "project_1",
        "external_ref": "record_1",
        "title": "Energy pressure",
        "category": "energy",
        "content_json": canonical,
        "content_text": "Energy pressure rose",
        "observed_at": "2026-06-01T00:00:00.000",
        "cutoff_at": "2026-06-30T00:00:00.000",
        "captured_at": "2026-06-30T01:00:00.000",
        "content_hash": digest,
        "created_by_user_id": "user_1",
    }

    snapshot = snapshot_from_row(row)
    summary = snapshot_summary_from_row(row)
    tampered = snapshot_from_row({**row, "content_json": json.dumps({"pressure": 99})})

    assert snapshot.content == content
    assert snapshot.integrity_status == "verified"
    assert summary.content_hash == digest
    assert tampered.integrity_status == "failed"


def test_evidence_source_claim_and_pack_mappers_preserve_contract_fields():
    source = source_from_row({
        "source_id": "src_1",
        "source_type": "dataset",
        "name": "Frozen source",
        "locator": "worldpulse://source/1",
        "publisher": "WorldPulse",
        "status": "active",
        "trust_tier": "deterministic",
        "metadata_json": json.dumps({"immutable": True}),
        "created_by_user_id": "user_1",
        "created_at": "2026-06-30T00:00:00.000",
        "retired_at": None,
    })
    claim = claim_from_row({
        "claim_id": "clm_1",
        "project_id": "project_1",
        "run_id": "run_1",
        "statement": "Pressure rose.",
        "claim_type": "finding",
        "confidence": 0.88,
        "valid_from": None,
        "valid_to": None,
        "cutoff_at": "2026-06-30T00:00:00.000",
        "claim_hash": "a" * 64,
        "created_by_user_id": "user_1",
        "created_at": "2026-06-30T00:00:00.000",
    }, [{
        "snapshot_id": "evs_1",
        "relation": "supports",
        "citation_label": "E1",
        "excerpt": "Pressure rose",
        "locator_json": json.dumps({"page": 1}),
    }])
    pack = pack_from_row({
        "pack_id": "evp_1",
        "project_id": "project_1",
        "run_id": "run_1",
        "name": "Frozen pack",
        "cutoff_at": "2026-06-30T00:00:00.000",
        "manifest_json": json.dumps({"schema_version": "evidence-pack.v1"}),
        "manifest_hash": "b" * 64,
        "created_by_user_id": "user_1",
        "created_at": "2026-06-30T00:00:00.000",
    })

    assert source.metadata == {"immutable": True}
    assert claim.links[0]["locator"] == {"page": 1}
    assert pack.manifest["schema_version"] == "evidence-pack.v1"


def test_legacy_evidence_facade_routes_reads_through_repository(monkeypatch):
    expected = EvidenceSource(
        source_id="src_1",
        source_type="dataset",
        name="Frozen source",
        locator="worldpulse://source/1",
        publisher="WorldPulse",
        status="active",
        trust_tier="deterministic",
        metadata={},
        created_at="2026-06-30T00:00:00.000",
    )

    class RepositoryDouble:
        def get_source(self, source_id: str):
            assert source_id == "src_1"
            return expected

    monkeypatch.setattr(evidence_registry, "_repository", RepositoryDouble())

    assert evidence_registry.get_source("src_1") is expected
    assert callable(EvidenceRepository().get_snapshot)
