from __future__ import annotations

import pytest

from app.core.evaluation_models import EvaluationBatchCreateRequest
from app.services.auth import ensure_system_user
from app.services.evaluation import EvaluationService
from app.services.evaluation.benchmark import ingest_manifest
from app.services.evaluation.gates import ensure_gate_manifest
from app.services.evaluation import benchmark
import os


def test_v112_gate_manifest_is_versioned_and_immutable():
    first = ensure_gate_manifest()
    second = ensure_gate_manifest()
    assert first.manifest_hash == second.manifest_hash
    assert first.version == "evaluation-artifact-verifier.v2"
    assert first.manifest["fail_closed"] is True
    assert "offline_replay" in first.manifest["checks"]


def test_standard_batch_records_track_root_and_member_input_hashes():
    service = EvaluationService()
    batch = service.create_standard_batch("org_default", ensure_system_user(), EvaluationBatchCreateRequest(provider="mock"))
    members = service.list_members(batch.batch_id)
    assert batch.evaluation_track == "engineering_standard"
    assert batch.root_batch_id == batch.batch_id
    assert batch.gate_manifest_hash
    assert len(members) == 84
    assert all(item.input_hash and item.verification_status == "pending" for item in members)


def test_historical_manifest_rejects_missing_or_incomplete_official_corpus():
    payload = {
        "suite_id": "historical-benchmark.v1",
        "version": "1",
        "cases": [],
    }
    with pytest.raises(Exception) as exc:
        ingest_manifest(payload, ensure_system_user())
    assert "120" in str(exc.value)


@pytest.mark.evaluation_full
def test_release_gate_requires_external_official_corpus_and_sealed_labels():
    verification = benchmark.verify_benchmarks()
    if verification["status"] != "ok" or not os.getenv("WORLDPULSE_V112_LABEL_PACK_ID"):
        pytest.skip("V1.12 release evaluator requires the externally curated 120-case corpus and sealed label pack")
    assert verification["case_count"] == 120
