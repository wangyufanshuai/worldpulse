from __future__ import annotations

import os

import pytest

from app.services import project_store
from app.services.run_lifecycle.kernel_shadow import (
    KERNEL_SHADOW_ARTIFACT_TYPE,
    KERNEL_SHADOW_ENV,
    KERNEL_SHADOW_MAX_BYTES,
)
from scripts.benchmark_v2_lifecycle_shadow_persistence import (
    evaluate_persistence_gates,
    run_persistence_benchmark,
)


def test_persistence_gates_use_precommitted_inclusive_limits():
    passing = evaluate_persistence_gates(
        control_p95_ms=1000.0,
        opt_in_p95_ms=1150.0,
        integration_p95_ms=100.0,
        stored_replay_p95_ms=20.0,
        max_payload_bytes=KERNEL_SHADOW_MAX_BYTES,
    )
    failing = evaluate_persistence_gates(
        control_p95_ms=1000.0,
        opt_in_p95_ms=1150.001,
        integration_p95_ms=100.001,
        stored_replay_p95_ms=20.001,
        max_payload_bytes=KERNEL_SHADOW_MAX_BYTES + 1,
    )

    assert all(gate["passed"] for gate in passing.values())
    assert not any(gate["passed"] for gate in failing.values())


def test_persistence_benchmark_uses_pinned_policy_and_isolated_sqlite(
    monkeypatch,
    tmp_path,
):
    configured_path = tmp_path / "configured-must-remain-absent.sqlite3"
    monkeypatch.setattr(project_store, "DB_PATH", configured_path)
    monkeypatch.setenv(KERNEL_SHADOW_ENV, "off")

    report = run_persistence_benchmark(
        pairs=1,
        warmup_pairs=0,
        temp_root=tmp_path / "persistence-benchmarks",
    )

    assert report["schema_version"] == "lifecycle-kernel-shadow-persistence-ab.v1"
    assert report["methodology"]["feature_pinned_at_job_creation"] is True
    assert report["methodology"]["worker_environment_flipped_after_creation"] is True
    assert report["environment"]["database_kind"] == "temporary_sqlite"
    assert report["environment"]["configured_database_path_restored"] is True
    assert report["environment"]["configured_feature_value_restored"] is True
    assert report["environment"]["temporary_database_removed"] is True
    assert report["environment"]["migration_count"] == 10
    assert report["environment"]["table_count"] == 83
    assert project_store.DB_PATH == configured_path
    assert os.environ[KERNEL_SHADOW_ENV] == "off"
    assert not configured_path.exists()

    control = report["artifact_contract"]["control_profile"]
    opt_in = report["artifact_contract"]["opt_in_profile"]
    assert KERNEL_SHADOW_ARTIFACT_TYPE not in control
    assert opt_in[KERNEL_SHADOW_ARTIFACT_TYPE] == 1
    assert report["artifact_contract"]["additive_artifact_count"] == 1
    assert report["artifact_contract"]["additive_event_count"] == 1
    assert report["payload_bytes"]["max"] <= KERNEL_SHADOW_MAX_BYTES
    assert report["payload_bytes"]["sample_count"] == 1
    assert report["lineage"]["source_run_hash"] == (
        "a3ab67f74a9c8058f15ad96ac99c989f63471cb0b2eed5928f0eaee621ba0082"
    )
    assert report["production_default_changed"] is False
    assert report["database_or_openapi_changed"] is False
    assert set(report["gates"]) == {
        "artifact_size",
        "integration_p95",
        "stored_replay_p95",
        "opt_in_to_control_p95",
    }
    assert all(
        measurement["sample_count"] == 1 and measurement["p95_ms"] > 0
        for measurement in report["measurements"].values()
    )


def test_persistence_benchmark_rejects_invalid_counts(tmp_path):
    with pytest.raises(ValueError, match="pairs must be positive"):
        run_persistence_benchmark(pairs=0, warmup_pairs=0, temp_root=tmp_path)
    with pytest.raises(ValueError, match="warmup pairs cannot be negative"):
        run_persistence_benchmark(pairs=1, warmup_pairs=-1, temp_root=tmp_path)
