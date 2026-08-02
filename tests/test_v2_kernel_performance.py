from __future__ import annotations

from scripts.benchmark_v2_kernel_shadow import run_benchmark


def test_kernel_shadow_benchmark_measures_real_hash_linked_operations():
    report = run_benchmark(iterations=2, repeats=2)

    assert report["schema_version"] == "kernel-shadow-performance.v1"
    assert report["production_path_changed"] is False
    assert report["iterations_per_repeat"] == 2
    assert report["repeats"] == 2
    assert report["source_run_hash"] == "a3ab67f74a9c8058f15ad96ac99c989f63471cb0b2eed5928f0eaee621ba0082"
    assert report["target_world_state_hash"] == "64f037a297a81dda526808cbdd182e2b3d640426c84eb94eab7ce434a31751c5"
    assert report["compiled_transition_hash"] == "42431a1dfad849e3fc50002e3bf446a674495ea71ed3a83e27d5378f19c9c61c"
    assert report["shadow_to_legacy_median_ratio"] > 0
    assert all(
        metrics["min_ms"] > 0
        and metrics["median_ms"] > 0
        and metrics["p95_ms"] > 0
        for metrics in report["measurements"].values()
    )
