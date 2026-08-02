from __future__ import annotations

from scripts.benchmark_v2_kernel_shadow import run_benchmark


def test_kernel_shadow_benchmark_measures_real_hash_linked_operations():
    report = run_benchmark(iterations=2, repeats=2)

    assert report["schema_version"] == "kernel-shadow-performance.v1"
    assert report["production_path_changed"] is False
    assert report["iterations_per_repeat"] == 2
    assert report["repeats"] == 2
    assert len(report["source_run_hash"]) == 64
    assert len(report["target_world_state_hash"]) == 64
    assert len(report["compiled_transition_hash"]) == 64
    assert report["shadow_to_legacy_median_ratio"] > 0
    assert all(
        metrics["min_ms"] > 0
        and metrics["median_ms"] > 0
        and metrics["p95_ms"] > 0
        for metrics in report["measurements"].values()
    )
