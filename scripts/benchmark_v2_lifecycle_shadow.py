"""Measure Kernel shadow overhead against an isolated real SQLite lifecycle."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import gc
import json
from math import ceil
import os
from pathlib import Path
import platform
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.models import (  # noqa: E402
    ResearchProjectCreate,
    RunArtifactSummary,
    RunJobCreateRequest,
    WarRoomRun,
    WarRoomScenarioRequest,
)
from app.db.migrations import apply_migrations, verify_schema  # noqa: E402
from app.services import project_store  # noqa: E402
from app.services.consistency.hashing import stable_hash  # noqa: E402
from app.services.project_app import research_workspace_service  # noqa: E402
from app.services.rule_packs import active_rule_pack  # noqa: E402
from app.services.run_lifecycle import run_control_service  # noqa: E402
from app.services.run_lifecycle import repository as lifecycle_repository  # noqa: E402
from app.services.simulation_kernel import build_war_room_shadow_run  # noqa: E402
from app.services.world_model import world_model_service  # noqa: E402


SHADOW_P95_LIMIT_MS = 15.0
COMBINED_TO_CONTROL_P95_LIMIT = 1.15
DEFAULT_PAIRS = 30
DEFAULT_WARMUP_PAIRS = 3
DATABASE_URL_ENV = "WORLDPULSE_DATABASE_URL"
BENCHMARK_SEED = 7

SCENARIO = WarRoomScenarioRequest(
    scenario_key="strait_blockade_30d",
    intensity=0.8,
    propagation=0.55,
    policy_actions=["sanctions"],
    seed=BENCHMARK_SEED,
)


def run_benchmark(
    *,
    pairs: int = DEFAULT_PAIRS,
    warmup_pairs: int = DEFAULT_WARMUP_PAIRS,
    temp_root: Path | None = None,
) -> dict[str, Any]:
    """Run interleaved control/treatment jobs under the ADR-0005 contract."""

    if pairs < 1:
        raise ValueError("Lifecycle shadow benchmark pairs must be positive")
    if warmup_pairs < 0:
        raise ValueError("Lifecycle shadow benchmark warmup pairs cannot be negative")

    configured_db_path = project_store.DB_PATH
    configured_database_url = os.environ.get(DATABASE_URL_ENV)
    control_samples_ms: list[float] = []
    treatment_lifecycle_samples_ms: list[float] = []
    shadow_samples_ms: list[float] = []
    combined_samples_ms: list[float] = []
    result_hashes: set[str] = set()
    treatment_profiles: list[tuple[tuple[str, str, int], ...]] = []
    first_shadow: dict[str, Any] | None = None
    temporary_database_path: Path | None = None
    migration_evidence: dict[str, Any] = {}

    with _isolated_sqlite(temp_root) as database_path:
        temporary_database_path = database_path
        migration_evidence = verify_schema(database_path)
        project = research_workspace_service.create_project(
            ResearchProjectCreate(
                title="WorldPulse V2 Lifecycle shadow benchmark",
                question="What is the additive cost of provider-free Kernel shadow processing?",
                mode="war_room",
            )
        )
        rule_pack = active_rule_pack()
        presets = world_model_service.war_room_presets()
        total_pairs = warmup_pairs + pairs

        for pair_index in range(total_pairs):
            measured = pair_index >= warmup_pairs
            cohort_order = (
                ("control", "treatment")
                if pair_index % 2 == 0
                else ("treatment", "control")
            )
            pair_results: dict[str, dict[str, Any]] = {}
            for cohort in cohort_order:
                pair_results[cohort] = _run_job_sample(
                    project_id=project.project_id,
                    pinned_rule_pack_id=rule_pack.rule_pack_id,
                    expected_rule_pack_hash=rule_pack.manifest_hash,
                    presets=presets,
                    treatment=cohort == "treatment",
                )

            if not measured:
                continue

            control = pair_results["control"]
            treatment = pair_results["treatment"]
            if control["artifact_profile"] != treatment["artifact_profile"]:
                raise RuntimeError("Control and treatment Artifact profiles diverged")
            control_samples_ms.append(control["lifecycle_ms"])
            treatment_lifecycle_samples_ms.append(treatment["lifecycle_ms"])
            shadow_samples_ms.append(treatment["shadow_ms"])
            combined_samples_ms.append(
                treatment["lifecycle_ms"] + treatment["shadow_ms"]
            )
            result_hashes.update(
                (control["source_run_hash"], treatment["source_run_hash"])
            )
            treatment_profiles.append(treatment["artifact_profile"])
            if first_shadow is None:
                first_shadow = treatment["shadow_lineage"]

    if temporary_database_path is None or first_shadow is None:
        raise RuntimeError("Lifecycle shadow benchmark produced no evidence")
    if len(result_hashes) != 1:
        raise RuntimeError("Control and treatment deterministic result hashes diverged")
    if len(set(treatment_profiles)) != 1:
        raise RuntimeError("Treatment Artifact type/schema/count profile drifted")

    measurements = {
        "control_lifecycle": summarize_samples(control_samples_ms),
        "treatment_lifecycle": summarize_samples(treatment_lifecycle_samples_ms),
        "shadow_post_processing": summarize_samples(shadow_samples_ms),
        "combined_lifecycle_shadow": summarize_samples(combined_samples_ms),
    }
    gates = evaluate_gates(
        control_p95_ms=measurements["control_lifecycle"]["p95_ms_raw"],
        shadow_p95_ms=measurements["shadow_post_processing"]["p95_ms_raw"],
        combined_p95_ms=measurements["combined_lifecycle_shadow"]["p95_ms_raw"],
    )
    profile = treatment_profiles[0]
    artifact_type_counts: Counter[str] = Counter()
    for artifact_type, _schema_version, count in profile:
        artifact_type_counts[artifact_type] += count
    artifact_types = dict(sorted(artifact_type_counts.items()))
    kernel_artifact_persisted = any(
        artifact_type.startswith("kernel_") for artifact_type in artifact_types
    )
    if kernel_artifact_persisted:
        raise RuntimeError("Lifecycle benchmark persisted an unauthorized Kernel Artifact")
    report_measurements = {
        name: _present_measurement(value) for name, value in measurements.items()
    }
    control_p95 = measurements["control_lifecycle"]["p95_ms_raw"]
    combined_p95 = measurements["combined_lifecycle_shadow"]["p95_ms_raw"]
    shadow_p95 = measurements["shadow_post_processing"]["p95_ms_raw"]

    return {
        "schema_version": "lifecycle-kernel-shadow-ab.v1",
        "methodology": {
            "adr": "ADR-0005",
            "pairs": pairs,
            "warmup_pairs": warmup_pairs,
            "cohort_order": "alternating control-first/treatment-first",
            "p95_method": "nearest-rank ceil(0.95 * n)",
            "combined_sample": "treatment lifecycle + in-memory shadow segments",
            "artifact_lookup_timed": False,
            "assertions_timed": False,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "sqlite": sqlite3.sqlite_version,
            "database_kind": "temporary_sqlite",
            "isolated": True,
            "database_url_overridden": configured_database_url is not None,
            "configured_database_path_restored": project_store.DB_PATH
            == configured_db_path,
            "temporary_database_removed": not temporary_database_path.exists(),
            "migration_count": migration_evidence["migrations"],
            "table_count": migration_evidence["tables"],
        },
        "measurements": report_measurements,
        "overhead": {
            "shadow_p95_ms": _round(shadow_p95),
            "combined_minus_control_p95_ms": _round(combined_p95 - control_p95),
            "combined_to_control_p95_ratio": _round(combined_p95 / control_p95),
            "combined_relative_p95_overhead": _round(
                combined_p95 / control_p95 - 1.0
            ),
            "treatment_to_control_p95_ratio": _round(
                measurements["treatment_lifecycle"]["p95_ms_raw"] / control_p95
            ),
        },
        "gates": gates,
        "performance_gate_passed": all(item["passed"] for item in gates.values()),
        "artifact_contract": {
            "unchanged_before_after_shadow": True,
            "control_treatment_profile_equal": True,
            "profile_stable_across_treatments": True,
            "count": sum(artifact_types.values()),
            "types": artifact_types,
            "kernel_artifacts_persisted": kernel_artifact_persisted,
        },
        "lineage": {
            "source_run_hash": next(iter(result_hashes)),
            **first_shadow,
        },
        "production_path_changed": False,
        "kernel_artifact_persisted": kernel_artifact_persisted,
    }


def summarize_samples(samples_ms: Sequence[float]) -> dict[str, Any]:
    """Return raw samples plus precommitted nearest-rank summary statistics."""

    if not samples_ms:
        raise ValueError("Cannot summarize an empty benchmark sample")
    if any(value <= 0 for value in samples_ms):
        raise ValueError("Benchmark samples must be positive")
    ordered = sorted(float(value) for value in samples_ms)
    p95_index = ceil(0.95 * len(ordered)) - 1
    return {
        "samples_ms_raw": list(float(value) for value in samples_ms),
        "min_ms_raw": ordered[0],
        "median_ms_raw": median(ordered),
        "p95_ms_raw": ordered[p95_index],
    }


def evaluate_gates(
    *,
    control_p95_ms: float,
    shadow_p95_ms: float,
    combined_p95_ms: float,
) -> dict[str, dict[str, Any]]:
    """Evaluate the immutable ADR-0005 thresholds without raising on a miss."""

    if min(control_p95_ms, shadow_p95_ms, combined_p95_ms) <= 0:
        raise ValueError("Performance gate inputs must be positive")
    ratio = combined_p95_ms / control_p95_ms
    return {
        "shadow_p95": {
            "operator": "<=",
            "limit_ms": SHADOW_P95_LIMIT_MS,
            "observed_ms": _round(shadow_p95_ms),
            "passed": shadow_p95_ms <= SHADOW_P95_LIMIT_MS,
        },
        "combined_to_control_p95": {
            "operator": "<=",
            "limit_ratio": COMBINED_TO_CONTROL_P95_LIMIT,
            "observed_ratio": _round(ratio),
            "passed": ratio <= COMBINED_TO_CONTROL_P95_LIMIT,
        },
    }


def _run_job_sample(
    *,
    project_id: str,
    pinned_rule_pack_id: str,
    expected_rule_pack_hash: str,
    presets: Any,
    treatment: bool,
) -> dict[str, Any]:
    request = RunJobCreateRequest(
        engine_mode="deterministic",
        scenario=SCENARIO,
        seed=BENCHMARK_SEED,
        max_attempts=1,
    )
    job = run_control_service.create_job(
        project_id,
        request,
        pinned_rule_pack_id=pinned_rule_pack_id,
    )
    if job.seed != BENCHMARK_SEED:
        raise RuntimeError("Lifecycle benchmark job did not pin the requested seed")
    if not job.rule_pack_hash or job.rule_pack_hash != expected_rule_pack_hash:
        raise RuntimeError("Lifecycle benchmark job did not pin the requested Rule Pack")

    lifecycle_started = perf_counter_ns()
    completed = run_control_service.process_one_queued_job()
    lifecycle_ms = (perf_counter_ns() - lifecycle_started) / 1_000_000
    if completed is None or completed.run_id != job.run_id:
        raise RuntimeError("Lifecycle worker processed an unexpected benchmark job")
    if completed.status != "completed":
        raise RuntimeError(
            f"Lifecycle benchmark job did not complete: {completed.status}"
        )

    payload = lifecycle_repository.get_latest_artifact_content(
        job.run_id, "war_room_result"
    )
    if payload is None:
        raise RuntimeError("Lifecycle benchmark job has no stored war_room_result")
    result = WarRoomRun.model_validate(payload)
    source_run_hash = stable_hash(result.model_dump(mode="json"))
    artifacts_before = _artifact_manifest(run_control_service.get_artifacts(job.run_id))
    response: dict[str, Any] = {
        "lifecycle_ms": lifecycle_ms,
        "source_run_hash": source_run_hash,
        "artifact_profile": _artifact_profile(artifacts_before),
    }
    if not treatment:
        return response

    shadow_started = perf_counter_ns()
    shadow = build_war_room_shadow_run(
        result,
        presets,
        run_id=job.run_id,
        seed=BENCHMARK_SEED,
        rule_pack_hash=job.rule_pack_hash,
    )
    shadow_ms = (perf_counter_ns() - shadow_started) / 1_000_000
    artifacts_after = _artifact_manifest(run_control_service.get_artifacts(job.run_id))
    if artifacts_after != artifacts_before:
        raise RuntimeError("Kernel shadow processing changed lifecycle Artifacts")
    if shadow.initial_state.run_id != job.run_id:
        raise RuntimeError("Kernel shadow run id does not match its lifecycle job")
    if shadow.initial_state.seed != BENCHMARK_SEED:
        raise RuntimeError("Kernel shadow seed does not match its lifecycle job")
    if shadow.initial_state.rule_pack_hash != job.rule_pack_hash:
        raise RuntimeError("Kernel shadow Rule Pack hash does not match its lifecycle job")
    final_state = shadow.checkpoints[-1].world_state
    if final_state.content_hash() != shadow.event_log.final_state_hash:
        raise RuntimeError("Kernel shadow final checkpoint hash is invalid")

    response.update(
        {
            "shadow_ms": shadow_ms,
            "artifact_profile": _artifact_profile(artifacts_after),
            "shadow_lineage": {
                "run_id": job.run_id,
                "seed": job.seed,
                "rule_pack_hash": job.rule_pack_hash,
                "final_world_state_hash": final_state.content_hash(),
                "event_log_hash": shadow.event_log.content_hash(),
                "shadow_run_hash": shadow.content_hash(),
                "event_count": len(shadow.event_log.transitions),
                "checkpoint_count": len(shadow.checkpoints),
            },
        }
    )
    return response


def _artifact_manifest(
    artifacts: Sequence[RunArtifactSummary],
) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            item.artifact_id,
            item.artifact_type,
            item.schema_version,
            item.sha256,
            item.integrity_status,
            item.created_at,
            item.attempt_id,
            item.step_id,
            item.artifact_version,
            item.supersedes_artifact_id,
        )
        for item in artifacts
    )


def _artifact_profile(
    manifest: Sequence[tuple[Any, ...]],
) -> tuple[tuple[str, str, int], ...]:
    counts = Counter((str(item[1]), str(item[2])) for item in manifest)
    return tuple(
        sorted(
            (artifact_type, schema_version, count)
            for (artifact_type, schema_version), count in counts.items()
        )
    )


def _present_measurement(measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_count": len(measurement["samples_ms_raw"]),
        "samples_ms": [_round(value) for value in measurement["samples_ms_raw"]],
        "min_ms": _round(measurement["min_ms_raw"]),
        "median_ms": _round(measurement["median_ms_raw"]),
        "p95_ms": _round(measurement["p95_ms_raw"]),
    }


@contextmanager
def _isolated_sqlite(temp_root: Path | None) -> Iterator[Path]:
    original_path = project_store.DB_PATH
    database_url_present = DATABASE_URL_ENV in os.environ
    original_database_url = os.environ.get(DATABASE_URL_ENV)
    parent: str | None = None
    if temp_root is not None:
        temp_root.mkdir(parents=True, exist_ok=True)
        parent = str(temp_root)

    with TemporaryDirectory(prefix="worldpulse-v2-lifecycle-", dir=parent) as directory:
        database_path = Path(directory) / "lifecycle-ab.sqlite3"
        try:
            os.environ.pop(DATABASE_URL_ENV, None)
            project_store.DB_PATH = database_path
            apply_migrations(database_path)
            yield database_path
        finally:
            project_store.DB_PATH = original_path
            if database_url_present and original_database_url is not None:
                os.environ[DATABASE_URL_ENV] = original_database_url
            else:
                os.environ.pop(DATABASE_URL_ENV, None)
            # Migration status rows can retain cyclic SQLite references until a
            # collection. Release them before TemporaryDirectory removes the DB
            # on Windows, where an open handle makes cleanup fail closed.
            gc.collect()


def _round(value: float) -> float:
    return round(float(value), 6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS)
    parser.add_argument("--warmup-pairs", type=int, default=DEFAULT_WARMUP_PAIRS)
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args()
    report = run_benchmark(
        pairs=args.pairs,
        warmup_pairs=args.warmup_pairs,
        temp_root=args.temp_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
