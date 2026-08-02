from __future__ import annotations

from pathlib import Path

import pytest

from app.services import project_store
from scripts.benchmark_v2_lifecycle_shadow import (
    evaluate_gates,
    run_benchmark,
    summarize_samples,
)


def test_lifecycle_shadow_statistics_use_precommitted_nearest_rank_p95():
    measurement = summarize_samples(list(range(1, 21)))

    assert measurement["median_ms_raw"] == 10.5
    assert measurement["p95_ms_raw"] == 19.0
    assert measurement["samples_ms_raw"] == [float(value) for value in range(1, 21)]

    passing = evaluate_gates(
        control_p95_ms=100.0,
        shadow_p95_ms=15.0,
        combined_p95_ms=115.0,
    )
    failing = evaluate_gates(
        control_p95_ms=100.0,
        shadow_p95_ms=15.000001,
        combined_p95_ms=115.000001,
    )
    assert all(gate["passed"] for gate in passing.values())
    assert not any(gate["passed"] for gate in failing.values())


@pytest.mark.parametrize(
    ("samples", "message"),
    [([], "empty"), ([0.0], "positive"), ([-1.0], "positive")],
)
def test_lifecycle_shadow_statistics_fail_closed(samples, message):
    with pytest.raises(ValueError, match=message):
        summarize_samples(samples)


def test_lifecycle_shadow_ab_uses_temporary_sqlite_and_preserves_artifacts(
    monkeypatch,
    tmp_path,
):
    configured_path = tmp_path / "configured-must-not-be-created.sqlite3"
    configured_url = "postgresql://must-not-connect.invalid/worldpulse"
    monkeypatch.setattr(project_store, "DB_PATH", configured_path)
    monkeypatch.setenv("WORLDPULSE_DATABASE_URL", configured_url)

    report = run_benchmark(
        pairs=1,
        warmup_pairs=0,
        temp_root=tmp_path / "temporary-benchmarks",
    )

    assert report["schema_version"] == "lifecycle-kernel-shadow-ab.v1"
    assert report["methodology"]["pairs"] == 1
    assert report["methodology"]["warmup_pairs"] == 0
    assert report["methodology"]["artifact_lookup_timed"] is False
    assert report["environment"]["database_kind"] == "temporary_sqlite"
    assert report["environment"]["isolated"] is True
    assert report["environment"]["database_url_overridden"] is True
    assert report["environment"]["configured_database_path_restored"] is True
    assert report["environment"]["temporary_database_removed"] is True
    assert report["environment"]["migration_count"] == 10
    assert report["environment"]["table_count"] == 83
    assert project_store.DB_PATH == configured_path
    assert report["artifact_contract"]["control_treatment_profile_equal"] is True
    assert not configured_path.exists()

    assert report["artifact_contract"]["unchanged_before_after_shadow"] is True
    assert report["artifact_contract"]["profile_stable_across_treatments"] is True
    assert report["artifact_contract"]["count"] > 0
    assert report["artifact_contract"]["kernel_artifacts_persisted"] is False
    assert "war_room_result" in report["artifact_contract"]["types"]
    assert report["kernel_artifact_persisted"] is False
    assert report["production_path_changed"] is False

    assert report["lineage"]["seed"] == 7
    assert report["lineage"]["rule_pack_hash"]
    assert report["lineage"]["event_count"] == 5
    assert report["lineage"]["checkpoint_count"] == 5
    assert len(report["lineage"]["source_run_hash"]) == 64
    assert len(report["lineage"]["final_world_state_hash"]) == 64
    assert len(report["lineage"]["event_log_hash"]) == 64

    assert set(report["gates"]) == {"shadow_p95", "combined_to_control_p95"}
    assert report["performance_gate_passed"] == all(
        gate["passed"] for gate in report["gates"].values()
    )
    assert all(
        measurement["sample_count"] == 1
        and measurement["min_ms"] > 0
        and measurement["median_ms"] > 0
        and measurement["p95_ms"] > 0
        for measurement in report["measurements"].values()
    )


def test_lifecycle_shadow_benchmark_rejects_invalid_sample_counts(tmp_path: Path):
    with pytest.raises(ValueError, match="pairs must be positive"):
        run_benchmark(pairs=0, warmup_pairs=0, temp_root=tmp_path)
    with pytest.raises(ValueError, match="warmup pairs cannot be negative"):
        run_benchmark(pairs=1, warmup_pairs=-1, temp_root=tmp_path)
