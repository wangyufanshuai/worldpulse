"""Measure additive Kernel V2 shadow overhead without changing production."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from math import ceil
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.models import WarRoomScenarioRequest  # noqa: E402
from app.services.consistency.hashing import stable_hash  # noqa: E402
from app.services.simulation_kernel import (  # noqa: E402
    Checkpoint,
    ExperimentBranch,
    branch_world_state,
    compile_deterministic_transition,
    project_war_room_run,
)
from app.services.war_room_engine import run_war_room  # noqa: E402


RULE_PACK_HASH = stable_hash(
    {
        "benchmark": "kernel-shadow-overhead.v1",
        "rule_set_version": "war-room-rules.v1",
    }
)


def run_benchmark(*, iterations: int, repeats: int) -> dict[str, Any]:
    if iterations < 1 or repeats < 1:
        raise ValueError("Kernel shadow benchmark iterations and repeats must be positive")

    control_request = WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d",
        intensity=0.65,
        propagation=0.42,
        seed=42,
    )
    treatment_request = WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d",
        intensity=0.8,
        propagation=0.55,
        policy_actions=["sanctions"],
        seed=7,
    )
    control_result = run_war_room(control_request)
    treatment_result = run_war_room(treatment_request)
    control_state = project_war_room_run(
        control_result,
        run_id="benchmark_control",
        seed=42,
        rule_pack_hash=RULE_PACK_HASH,
    )
    checkpoint = Checkpoint(
        checkpoint_id="benchmark_checkpoint",
        branch_id="main",
        world_state=control_state,
    )
    branch = ExperimentBranch(
        branch_id="benchmark_treatment",
        parent_checkpoint_hash=checkpoint.content_hash(),
        treatment="treated",
        seed=7,
        scenario_diff=treatment_request.model_dump(mode="json"),
    )
    branch_state = branch_world_state(checkpoint, branch)

    def project_treatment():
        return project_war_room_run(
            treatment_result,
            run_id=branch_state.run_id,
            seed=branch_state.seed,
            rule_pack_hash=branch_state.rule_pack_hash,
        )

    target_state = project_treatment()

    def compile_transition():
        return compile_deterministic_transition(
            branch_state,
            target_state,
            event_id="benchmark_event",
            sequence=1,
            reducer_version="war-room-shadow-transition.v1",
        )

    def shadow_pipeline():
        result = run_war_room(treatment_request)
        projected = project_war_room_run(
            result,
            run_id=branch_state.run_id,
            seed=branch_state.seed,
            rule_pack_hash=branch_state.rule_pack_hash,
        )
        return compile_deterministic_transition(
            branch_state,
            projected,
            event_id="benchmark_event",
            sequence=1,
            reducer_version="war-room-shadow-transition.v1",
        )

    operations: dict[str, Callable[[], object]] = {
        "legacy_run": lambda: run_war_room(treatment_request),
        "world_state_projection": project_treatment,
        "transition_compile": compile_transition,
        "legacy_plus_kernel_shadow": shadow_pipeline,
    }
    measurements = {
        name: _measure(operation, iterations=iterations, repeats=repeats)
        for name, operation in operations.items()
    }
    legacy_median = measurements["legacy_run"]["median_ms"]
    shadow_median = measurements["legacy_plus_kernel_shadow"]["median_ms"]
    transition = compile_transition()
    return {
        "schema_version": "kernel-shadow-performance.v1",
        "iterations_per_repeat": iterations,
        "repeats": repeats,
        "measurements": measurements,
        "shadow_to_legacy_median_ratio": round(shadow_median / legacy_median, 4),
        "source_run_hash": stable_hash(treatment_result.model_dump(mode="json")),
        "target_world_state_hash": target_state.content_hash(),
        "compiled_transition_hash": transition.content_hash(),
        "production_path_changed": False,
    }


def _measure(operation: Callable[[], object], *, iterations: int, repeats: int) -> dict[str, float]:
    for _ in range(min(5, iterations)):
        operation()

    samples_ms: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        for _ in range(iterations):
            operation()
        samples_ms.append((perf_counter() - started) * 1000 / iterations)
    ordered = sorted(samples_ms)
    p95_index = min(len(ordered) - 1, max(0, ceil(len(ordered) * 0.95) - 1))
    return {
        "min_ms": round(ordered[0], 6),
        "median_ms": round(median(ordered), 6),
        "p95_ms": round(ordered[p95_index], 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(iterations=args.iterations, repeats=args.repeats), indent=2))


if __name__ == "__main__":
    main()
