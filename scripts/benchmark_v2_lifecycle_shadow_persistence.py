"""Measure actual opt-in Kernel shadow persistence under ADR-0006."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
from time import perf_counter_ns
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.models import (  # noqa: E402
    ResearchProjectCreate,
    RunJobCreateRequest,
    WarRoomRun,
    WarRoomScenarioRequest,
)
from app.db.migrations import verify_schema  # noqa: E402
from app.services import project_store  # noqa: E402
from app.services.consistency.hashing import stable_hash  # noqa: E402
from app.services.project_app import research_workspace_service  # noqa: E402
from app.services.rule_packs import active_rule_pack  # noqa: E402
from app.services.run_lifecycle import repository, run_control_service  # noqa: E402
from app.services.run_lifecycle.kernel_shadow import (  # noqa: E402
    KERNEL_SHADOW_ARTIFACT_TYPE,
    KERNEL_SHADOW_ENV,
    KERNEL_SHADOW_MAX_BYTES,
    KERNEL_SHADOW_POLICY_KEY,
    verify_persisted_kernel_shadow_artifact,
)
from scripts.benchmark_v2_lifecycle_shadow import (  # noqa: E402
    isolated_sqlite,
    present_measurement,
    round_metric,
    summarize_samples,
)


INTEGRATION_P95_LIMIT_MS = 100.0
STORED_REPLAY_P95_LIMIT_MS = 20.0
OPT_IN_TO_CONTROL_P95_LIMIT = 1.15
DEFAULT_PAIRS = 30
DEFAULT_WARMUP_PAIRS = 3
BENCHMARK_SEED = 7

SCENARIO = WarRoomScenarioRequest(
    scenario_key="strait_blockade_30d",
    intensity=0.8,
    propagation=0.55,
    policy_actions=["sanctions"],
    seed=BENCHMARK_SEED,
)


def run_persistence_benchmark(
    *,
    pairs: int = DEFAULT_PAIRS,
    warmup_pairs: int = DEFAULT_WARMUP_PAIRS,
    temp_root: Path | None = None,
) -> dict[str, Any]:
    if pairs < 1:
        raise ValueError("Kernel shadow persistence benchmark pairs must be positive")
    if warmup_pairs < 0:
        raise ValueError("Kernel shadow persistence warmup pairs cannot be negative")

    configured_db_path = project_store.DB_PATH
    feature_was_present = KERNEL_SHADOW_ENV in os.environ
    configured_feature_value = os.environ.get(KERNEL_SHADOW_ENV)
    temporary_database_path: Path | None = None
    migration_evidence: dict[str, Any] = {}
    control_lifecycle_ms: list[float] = []
    opt_in_lifecycle_ms: list[float] = []
    integration_ms: list[float] = []
    stored_replay_ms: list[float] = []
    payload_bytes: list[float] = []
    source_hashes: set[str] = set()
    control_profiles: list[tuple[tuple[str, int], ...]] = []
    opt_in_profiles: list[tuple[tuple[str, int], ...]] = []
    first_lineage: dict[str, Any] | None = None

    try:
        with isolated_sqlite(temp_root) as database_path:
            temporary_database_path = database_path
            migration_evidence = verify_schema(database_path)
            project = research_workspace_service.create_project(
                ResearchProjectCreate(
                    title="WorldPulse V2 persisted Kernel shadow benchmark",
                    question="What is the cost of the opt-in durable Kernel replay chain?",
                    mode="war_room",
                )
            )
            rule_pack = active_rule_pack()
            for pair_index in range(warmup_pairs + pairs):
                measured = pair_index >= warmup_pairs
                order = (
                    (False, True) if pair_index % 2 == 0 else (True, False)
                )
                pair: dict[bool, dict[str, Any]] = {}
                for opt_in in order:
                    pair[opt_in] = _run_sample(
                        project_id=project.project_id,
                        pinned_rule_pack_id=rule_pack.rule_pack_id,
                        expected_rule_pack_hash=rule_pack.manifest_hash,
                        opt_in=opt_in,
                    )
                if not measured:
                    continue

                control = pair[False]
                treatment = pair[True]
                _verify_pair_contract(control, treatment)
                control_lifecycle_ms.append(control["lifecycle_ms"])
                opt_in_lifecycle_ms.append(treatment["lifecycle_ms"])
                integration_ms.append(treatment["integration_ms"])
                stored_replay_ms.append(treatment["stored_replay_ms"])
                payload_bytes.append(float(treatment["payload_bytes"]))
                source_hashes.update(
                    (control["source_run_hash"], treatment["source_run_hash"])
                )
                control_profiles.append(control["artifact_profile"])
                opt_in_profiles.append(treatment["artifact_profile"])
                if first_lineage is None:
                    first_lineage = treatment["lineage"]
    finally:
        if feature_was_present and configured_feature_value is not None:
            os.environ[KERNEL_SHADOW_ENV] = configured_feature_value
        else:
            os.environ.pop(KERNEL_SHADOW_ENV, None)

    if temporary_database_path is None or first_lineage is None:
        raise RuntimeError("Kernel shadow persistence benchmark produced no evidence")
    if len(source_hashes) != 1:
        raise RuntimeError("Kernel shadow persistence cohorts changed deterministic output")
    if len(set(control_profiles)) != 1 or len(set(opt_in_profiles)) != 1:
        raise RuntimeError("Kernel shadow persistence Artifact profile drifted")

    measurements = {
        "control_lifecycle": summarize_samples(control_lifecycle_ms),
        "opt_in_lifecycle": summarize_samples(opt_in_lifecycle_ms),
        "kernel_build_serialize_persist": summarize_samples(integration_ms),
        "stored_validation_replay": summarize_samples(stored_replay_ms),
    }
    payload_measurement = summarize_samples(payload_bytes)
    gates = evaluate_persistence_gates(
        control_p95_ms=measurements["control_lifecycle"]["p95_ms_raw"],
        opt_in_p95_ms=measurements["opt_in_lifecycle"]["p95_ms_raw"],
        integration_p95_ms=measurements["kernel_build_serialize_persist"][
            "p95_ms_raw"
        ],
        stored_replay_p95_ms=measurements["stored_validation_replay"][
            "p95_ms_raw"
        ],
        max_payload_bytes=max(payload_bytes),
    )
    control_p95 = measurements["control_lifecycle"]["p95_ms_raw"]
    opt_in_p95 = measurements["opt_in_lifecycle"]["p95_ms_raw"]

    return {
        "schema_version": "lifecycle-kernel-shadow-persistence-ab.v1",
        "methodology": {
            "adr": "ADR-0006",
            "pairs": pairs,
            "warmup_pairs": warmup_pairs,
            "cohort_order": "alternating default-off/opt-in first",
            "feature_pinned_at_job_creation": True,
            "worker_environment_flipped_after_creation": True,
            "p95_method": "nearest-rank ceil(0.95 * n)",
            "stored_artifact_lookup_timed": False,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "database_kind": "temporary_sqlite",
            "configured_database_path_restored": project_store.DB_PATH
            == configured_db_path,
            "configured_feature_value_restored": os.environ.get(
                KERNEL_SHADOW_ENV
            )
            == configured_feature_value,
            "temporary_database_removed": not temporary_database_path.exists(),
            "migration_count": migration_evidence["migrations"],
            "table_count": migration_evidence["tables"],
        },
        "measurements": {
            name: present_measurement(value) for name, value in measurements.items()
        },
        "payload_bytes": {
            "sample_count": len(payload_bytes),
            "min": int(payload_measurement["min_ms_raw"]),
            "median": round_metric(payload_measurement["median_ms_raw"]),
            "p95": int(payload_measurement["p95_ms_raw"]),
            "max": int(max(payload_bytes)),
            "limit": KERNEL_SHADOW_MAX_BYTES,
        },
        "overhead": {
            "opt_in_minus_control_p95_ms": round_metric(opt_in_p95 - control_p95),
            "opt_in_to_control_p95_ratio": round_metric(opt_in_p95 / control_p95),
            "relative_p95_overhead": round_metric(
                opt_in_p95 / control_p95 - 1.0
            ),
        },
        "gates": gates,
        "performance_gate_passed": all(item["passed"] for item in gates.values()),
        "artifact_contract": {
            "control_profile": dict(control_profiles[0]),
            "opt_in_profile": dict(opt_in_profiles[0]),
            "additive_artifact_type": KERNEL_SHADOW_ARTIFACT_TYPE,
            "additive_artifact_count": 1,
            "additive_event_count": 1,
        },
        "lineage": {
            "source_run_hash": next(iter(source_hashes)),
            **first_lineage,
        },
        "production_default_changed": False,
        "database_or_openapi_changed": False,
    }


def evaluate_persistence_gates(
    *,
    control_p95_ms: float,
    opt_in_p95_ms: float,
    integration_p95_ms: float,
    stored_replay_p95_ms: float,
    max_payload_bytes: float,
) -> dict[str, dict[str, Any]]:
    if min(
        control_p95_ms,
        opt_in_p95_ms,
        integration_p95_ms,
        stored_replay_p95_ms,
        max_payload_bytes,
    ) <= 0:
        raise ValueError("Kernel shadow persistence gate inputs must be positive")
    ratio = opt_in_p95_ms / control_p95_ms
    return {
        "artifact_size": {
            "operator": "<=",
            "limit_bytes": KERNEL_SHADOW_MAX_BYTES,
            "observed_bytes": int(max_payload_bytes),
            "passed": max_payload_bytes <= KERNEL_SHADOW_MAX_BYTES,
        },
        "integration_p95": {
            "operator": "<=",
            "limit_ms": INTEGRATION_P95_LIMIT_MS,
            "observed_ms": round_metric(integration_p95_ms),
            "passed": integration_p95_ms <= INTEGRATION_P95_LIMIT_MS,
        },
        "stored_replay_p95": {
            "operator": "<=",
            "limit_ms": STORED_REPLAY_P95_LIMIT_MS,
            "observed_ms": round_metric(stored_replay_p95_ms),
            "passed": stored_replay_p95_ms <= STORED_REPLAY_P95_LIMIT_MS,
        },
        "opt_in_to_control_p95": {
            "operator": "<=",
            "limit_ratio": OPT_IN_TO_CONTROL_P95_LIMIT,
            "observed_ratio": round_metric(ratio),
            "passed": ratio <= OPT_IN_TO_CONTROL_P95_LIMIT,
        },
    }


def _run_sample(
    *,
    project_id: str,
    pinned_rule_pack_id: str,
    expected_rule_pack_hash: str,
    opt_in: bool,
) -> dict[str, Any]:
    os.environ[KERNEL_SHADOW_ENV] = "1" if opt_in else "0"
    job = run_control_service.create_job(
        project_id,
        RunJobCreateRequest(
            engine_mode="deterministic",
            scenario=SCENARIO,
            seed=BENCHMARK_SEED,
            max_attempts=1,
        ),
        pinned_rule_pack_id=pinned_rule_pack_id,
    )
    # Execution must honor the hashed job policy, not mutable worker env.
    os.environ[KERNEL_SHADOW_ENV] = "0" if opt_in else "1"
    pinned = KERNEL_SHADOW_POLICY_KEY in job.runtime_profile
    if pinned != opt_in:
        raise RuntimeError("Kernel shadow persistence policy was not pinned")
    if job.rule_pack_hash != expected_rule_pack_hash or job.seed != BENCHMARK_SEED:
        raise RuntimeError("Kernel shadow persistence input pinning failed")

    started = perf_counter_ns()
    completed = run_control_service.process_one_queued_job()
    lifecycle_ms = (perf_counter_ns() - started) / 1_000_000
    if completed is None or completed.run_id != job.run_id or completed.status != "completed":
        raise RuntimeError("Kernel shadow persistence lifecycle did not complete")

    source_payload = repository.get_latest_artifact_content(job.run_id, "war_room_result")
    if source_payload is None:
        raise RuntimeError("Kernel shadow persistence source result is missing")
    source_result = WarRoomRun.model_validate(source_payload)
    artifacts = repository.get_artifacts(job.run_id)
    events = repository.get_events(job.run_id)
    response: dict[str, Any] = {
        "lifecycle_ms": lifecycle_ms,
        "source_run_hash": stable_hash(source_result.model_dump(mode="json")),
        "artifact_profile": _profile(item.artifact_type for item in artifacts),
        "event_count": len(events),
    }
    shadow_payload = repository.get_latest_artifact_content(
        job.run_id, KERNEL_SHADOW_ARTIFACT_TYPE
    )
    shadow_events = [
        event for event in events if event.title == "Kernel shadow Artifact recorded"
    ]
    if not opt_in:
        if shadow_payload is not None or shadow_events:
            raise RuntimeError("Default-off cohort persisted Kernel shadow evidence")
        return response

    source_summary = repository.get_latest_artifact_summary(
        job.run_id, "war_room_result"
    )
    if shadow_payload is None or source_summary is None or len(shadow_events) != 1:
        raise RuntimeError("Opt-in cohort is missing Kernel shadow evidence")
    payload_size = len(project_store.dumps(shadow_payload).encode("utf-8"))
    event_payload = shadow_events[0].payload
    if event_payload.get("payload_bytes") != payload_size:
        raise RuntimeError("Kernel shadow Artifact byte evidence mismatch")

    pinned_job = repository.get_job(job.run_id)
    replay_started = perf_counter_ns()
    envelope = verify_persisted_kernel_shadow_artifact(
        shadow_payload,
        job=pinned_job,
        source_result=source_result,
        source_artifact=source_summary,
    )
    stored_replay_ms = (perf_counter_ns() - replay_started) / 1_000_000
    response.update(
        {
            "integration_ms": float(event_payload["integration_duration_ms"]),
            "stored_replay_ms": stored_replay_ms,
            "payload_bytes": payload_size,
            "lineage": {
                "run_id": job.run_id,
                "runtime_profile_hash": job.runtime_profile_hash,
                "source_artifact_sha256": envelope.source_artifact_sha256,
                "kernel_artifact_sha256": event_payload["kernel_artifact_sha256"],
                "kernel_envelope_hash": envelope.content_hash(),
                "event_log_hash": envelope.event_log_hash,
                "final_state_hash": envelope.final_state_hash,
            },
        }
    )
    return response


def _verify_pair_contract(control: dict[str, Any], treatment: dict[str, Any]) -> None:
    control_profile = dict(control["artifact_profile"])
    treatment_profile = dict(treatment["artifact_profile"])
    expected = dict(control_profile)
    expected[KERNEL_SHADOW_ARTIFACT_TYPE] = 1
    if treatment_profile != expected:
        raise RuntimeError("Opt-in cohort did not add exactly one Kernel Artifact")
    if treatment["event_count"] != control["event_count"] + 1:
        raise RuntimeError("Opt-in cohort did not add exactly one lifecycle event")


def _profile(artifact_types: Iterable[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(artifact_types).items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS)
    parser.add_argument("--warmup-pairs", type=int, default=DEFAULT_WARMUP_PAIRS)
    parser.add_argument("--temp-root", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_persistence_benchmark(
                pairs=args.pairs,
                warmup_pairs=args.warmup_pairs,
                temp_root=args.temp_root,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
