"""Versioned, provider-free Artifact envelopes for Simulation Kernel replay."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

from app.core.models import WarRoomPresetBundle, WarRoomRun
from app.services.consistency.hashing import stable_hash

from .contracts import KernelContract, ReplayRequest, WorldState
from .event_log import replay_event_log
from .war_room_trace import WarRoomShadowRun, build_war_room_shadow_run


KERNEL_SHADOW_ARTIFACT_SCHEMA = "kernel-shadow-artifact.v1"
KERNEL_SHADOW_BASELINE_SCOPE = "deterministic_pre_agent"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _KernelShadowArtifactHeader(BaseModel):
    """Validate the envelope once while leaving checkpoint snapshots deduplicable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["kernel-shadow-artifact.v1"]
    baseline_scope: Literal["deterministic_pre_agent"]
    run_id: str = Field(min_length=1, max_length=160)
    seed: int
    rule_pack_hash: str = Field(min_length=1, max_length=128)
    source_artifact_type: Literal["war_room_result"]
    source_artifact_schema_version: str = Field(min_length=1, max_length=120)
    source_artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    source_run_hash: str = Field(pattern=SHA256_PATTERN)
    shadow_run: SkipValidation[dict[str, Any]]
    shadow_run_hash: str = Field(pattern=SHA256_PATTERN)
    event_log_hash: str = Field(pattern=SHA256_PATTERN)
    final_state_hash: str = Field(pattern=SHA256_PATTERN)


@dataclass(frozen=True)
class VerifiedKernelShadowArtifact:
    """Validated stored view without materializing duplicate checkpoint states."""

    schema_version: str
    baseline_scope: str
    run_id: str
    seed: int
    rule_pack_hash: str
    source_artifact_type: str
    source_artifact_schema_version: str
    source_artifact_sha256: str
    source_run_hash: str
    shadow_run_hash: str
    event_log_hash: str
    final_state_hash: str
    initial_checkpoint_id: str
    checkpoint_count: int
    _replayed_state: WorldState
    _content_hash: str

    def verify_source_result(self, result: WarRoomRun) -> None:
        source_hash = stable_hash(result.model_dump(mode="json"))
        if source_hash != self.source_run_hash:
            raise ValueError("Kernel shadow Artifact source run hash mismatch")

    def replay_stored(self) -> WorldState:
        return self._replayed_state

    def content_hash(self) -> str:
        return self._content_hash


class KernelShadowArtifact(KernelContract):
    """Self-validating envelope linking one stored result to Kernel replay."""

    schema_version: Literal["kernel-shadow-artifact.v1"] = "kernel-shadow-artifact.v1"
    baseline_scope: Literal["deterministic_pre_agent"] = "deterministic_pre_agent"
    run_id: str = Field(min_length=1, max_length=160)
    seed: int
    rule_pack_hash: str = Field(min_length=1, max_length=128)
    source_artifact_type: Literal["war_room_result"] = "war_room_result"
    source_artifact_schema_version: str = Field(min_length=1, max_length=120)
    source_artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    source_run_hash: str = Field(pattern=SHA256_PATTERN)
    shadow_run: WarRoomShadowRun
    shadow_run_hash: str = Field(pattern=SHA256_PATTERN)
    event_log_hash: str = Field(pattern=SHA256_PATTERN)
    final_state_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def verify_internal_lineage_and_replay(self) -> Self:
        shadow = self.shadow_run
        if shadow.initial_state.run_id != self.run_id:
            raise ValueError("Kernel shadow Artifact run id mismatch")
        if shadow.initial_state.seed != self.seed:
            raise ValueError("Kernel shadow Artifact seed mismatch")
        if shadow.initial_state.rule_pack_hash != self.rule_pack_hash:
            raise ValueError("Kernel shadow Artifact Rule Pack hash mismatch")
        if shadow.content_hash() != self.shadow_run_hash:
            raise ValueError("Kernel shadow Artifact shadow-run hash mismatch")
        if shadow.event_log.content_hash() != self.event_log_hash:
            raise ValueError("Kernel shadow Artifact Event Log hash mismatch")
        if shadow.event_log.final_state_hash != self.final_state_hash:
            raise ValueError("Kernel shadow Artifact final state hash mismatch")
        replayed = self.replay_stored()
        if replayed.content_hash() != self.final_state_hash:
            raise ValueError("Kernel shadow Artifact stored replay hash mismatch")
        return self

    def verify_source_result(self, result: WarRoomRun) -> None:
        source_hash = stable_hash(result.model_dump(mode="json"))
        if source_hash != self.source_run_hash:
            raise ValueError("Kernel shadow Artifact source run hash mismatch")

    def replay_stored(self) -> WorldState:
        initial_checkpoint = self.shadow_run.checkpoints[0]
        return replay_event_log(
            self.shadow_run.initial_state,
            self.shadow_run.event_log,
            ReplayRequest(checkpoint_id=initial_checkpoint.checkpoint_id),
        )

    def content_hash(self) -> str:
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))


def build_kernel_shadow_artifact(
    result: WarRoomRun,
    presets: WarRoomPresetBundle,
    *,
    run_id: str,
    seed: int,
    rule_pack_hash: str,
    source_artifact_schema_version: str,
    source_artifact_sha256: str,
) -> KernelShadowArtifact:
    """Build a fully verified envelope without storage or Provider access."""

    shadow = build_war_room_shadow_run(
        result,
        presets,
        run_id=run_id,
        seed=seed,
        rule_pack_hash=rule_pack_hash,
    )
    artifact = KernelShadowArtifact(
        run_id=run_id,
        seed=seed,
        rule_pack_hash=rule_pack_hash,
        source_artifact_schema_version=source_artifact_schema_version,
        source_artifact_sha256=source_artifact_sha256,
        source_run_hash=stable_hash(result.model_dump(mode="json")),
        shadow_run=shadow,
        shadow_run_hash=shadow.content_hash(),
        event_log_hash=shadow.event_log.content_hash(),
        final_state_hash=shadow.event_log.final_state_hash,
    )
    artifact.verify_source_result(result)
    return artifact


def verify_kernel_shadow_artifact_payload(
    payload: dict[str, Any],
) -> VerifiedKernelShadowArtifact:
    """Verify stored JSON without re-parsing duplicated checkpoint WorldStates.

    Checkpoint snapshots are content-addressed by Event Log output hashes. The
    verifier validates their raw canonical hashes and reconstructs authority by
    replaying the independently parsed initial state and Event Log.
    """

    header = _KernelShadowArtifactHeader.model_validate(payload)
    shadow = header.shadow_run
    if not isinstance(shadow, dict):
        raise ValueError("Kernel shadow Artifact shadow run must be an object")
    _require_exact_keys(
        shadow,
        {"schema_version", "initial_state", "event_log", "checkpoints"},
        "War Room shadow run",
    )
    if shadow["schema_version"] != "war-room-shadow-run.v1":
        raise ValueError("Kernel shadow Artifact shadow-run schema mismatch")
    if stable_hash(shadow) != header.shadow_run_hash:
        raise ValueError("Kernel shadow Artifact shadow-run hash mismatch")

    initial_state_payload = shadow["initial_state"]
    event_log_payload = shadow["event_log"]
    _verify_raw_world_state(initial_state_payload)
    if not isinstance(event_log_payload, dict):
        raise ValueError("Kernel shadow Artifact Event Log must be an object")
    if stable_hash(event_log_payload) != header.event_log_hash:
        raise ValueError("Kernel shadow Artifact Event Log hash mismatch")
    replayed = _replay_raw_event_log(initial_state_payload, event_log_payload)
    if initial_state_payload["run_id"] != header.run_id or event_log_payload["run_id"] != header.run_id:
        raise ValueError("Kernel shadow Artifact run id mismatch")
    if initial_state_payload["seed"] != header.seed:
        raise ValueError("Kernel shadow Artifact seed mismatch")
    if initial_state_payload["rule_pack_hash"] != header.rule_pack_hash:
        raise ValueError("Kernel shadow Artifact Rule Pack hash mismatch")
    if event_log_payload["final_state_hash"] != header.final_state_hash:
        raise ValueError("Kernel shadow Artifact final state hash mismatch")

    checkpoints = shadow["checkpoints"]
    if not isinstance(checkpoints, list) or len(checkpoints) < 2:
        raise ValueError("Kernel shadow Artifact checkpoints are malformed")
    _verify_raw_checkpoints(
        initial_state_payload,
        event_log_payload,
        checkpoints,
    )
    initial_checkpoint_id = checkpoints[0]["checkpoint_id"]
    if replayed.content_hash() != header.final_state_hash:
        raise ValueError("Kernel shadow Artifact stored replay hash mismatch")

    return VerifiedKernelShadowArtifact(
        schema_version=header.schema_version,
        baseline_scope=header.baseline_scope,
        run_id=header.run_id,
        seed=header.seed,
        rule_pack_hash=header.rule_pack_hash,
        source_artifact_type=header.source_artifact_type,
        source_artifact_schema_version=header.source_artifact_schema_version,
        source_artifact_sha256=header.source_artifact_sha256,
        source_run_hash=header.source_run_hash,
        shadow_run_hash=header.shadow_run_hash,
        event_log_hash=header.event_log_hash,
        final_state_hash=header.final_state_hash,
        initial_checkpoint_id=initial_checkpoint_id,
        checkpoint_count=len(checkpoints),
        _replayed_state=replayed,
        _content_hash=stable_hash(payload),
    )


def _verify_raw_checkpoints(
    initial_state_payload: dict[str, Any],
    event_log: dict[str, Any],
    checkpoints: list[Any],
) -> None:
    expected_keys = {
        "schema_version",
        "checkpoint_id",
        "branch_id",
        "parent_checkpoint_hash",
        "event_cursor",
        "world_state",
        "artifact_hashes",
    }
    previous: dict[str, Any] | None = None
    first_branch: str | None = None
    for index, raw in enumerate(checkpoints):
        if not isinstance(raw, dict):
            raise ValueError("Kernel shadow Artifact checkpoint must be an object")
        _require_exact_keys(raw, expected_keys, "Kernel checkpoint")
        if raw["schema_version"] != "kernel-checkpoint.v1":
            raise ValueError("Kernel shadow Artifact checkpoint schema mismatch")
        _require_string(
            raw["checkpoint_id"], "Kernel shadow Artifact checkpoint id", 160
        )
        _require_string(
            raw["branch_id"], "Kernel shadow Artifact checkpoint branch", 160
        )
        if not isinstance(raw["event_cursor"], int) or isinstance(raw["event_cursor"], bool):
            raise ValueError("Kernel shadow Artifact checkpoint cursor is malformed")
        if not isinstance(raw["world_state"], dict):
            raise ValueError("Kernel shadow Artifact checkpoint state is malformed")
        if not isinstance(raw["artifact_hashes"], list) or not all(
            isinstance(item, str) for item in raw["artifact_hashes"]
        ):
            raise ValueError("Kernel shadow Artifact checkpoint hashes are malformed")

        cursor = raw["event_cursor"]
        if index == 0:
            if cursor != 0 or raw["parent_checkpoint_hash"] is not None:
                raise ValueError("Kernel shadow Artifact initial checkpoint is malformed")
            if raw["world_state"] != initial_state_payload:
                raise ValueError("Kernel shadow Artifact initial checkpoint state mismatch")
            expected_state_hash: str | None = None
            first_branch = raw["branch_id"]
        else:
            if previous is None or cursor <= previous["event_cursor"]:
                raise ValueError("Kernel shadow Artifact checkpoint cursors must increase")
            if cursor > len(event_log["transitions"]):
                raise ValueError("Kernel shadow Artifact checkpoint cursor exceeds Event Log")
            if raw["parent_checkpoint_hash"] != stable_hash(previous):
                raise ValueError("Kernel shadow Artifact checkpoint parent hash mismatch")
            if raw["branch_id"] != first_branch:
                raise ValueError("Kernel shadow Artifact checkpoint branch mismatch")
            expected_state_hash = event_log["transitions"][cursor - 1]["event"]["output_state_hash"]
        if (
            expected_state_hash is not None
            and stable_hash(raw["world_state"]) != expected_state_hash
        ):
            raise ValueError("Kernel shadow Artifact checkpoint state hash mismatch")
        previous = raw

    final = checkpoints[-1]
    if final["event_cursor"] != len(event_log["transitions"]):
        raise ValueError("Kernel shadow Artifact final checkpoint cursor mismatch")


def _replay_raw_event_log(
    initial_state: dict[str, Any],
    event_log: dict[str, Any],
) -> WorldState:
    _require_exact_keys(
        event_log,
        {
            "schema_version",
            "run_id",
            "initial_state_hash",
            "final_state_hash",
            "transitions",
        },
        "Kernel Event Log",
    )
    if event_log["schema_version"] != "kernel-event-log.v1":
        raise ValueError("Kernel shadow Artifact Event Log schema mismatch")
    _require_string(event_log["run_id"], "Kernel Event Log run id", 160)
    _require_hash(event_log["initial_state_hash"], "Kernel Event Log initial state hash")
    _require_hash(event_log["final_state_hash"], "Kernel Event Log final state hash")
    transitions = event_log["transitions"]
    if not isinstance(transitions, list) or not transitions:
        raise ValueError("Kernel shadow Artifact Event Log transitions are malformed")
    if initial_state["run_id"] != event_log["run_id"]:
        raise ValueError("Kernel shadow Artifact Event Log run id mismatch")

    working = deepcopy(initial_state)
    current_hash = stable_hash(working)
    if current_hash != event_log["initial_state_hash"]:
        raise ValueError("Kernel shadow Artifact Event Log initial state hash mismatch")
    previous_tick = -1
    for expected_sequence, transition in enumerate(transitions, start=1):
        _require_exact_keys(
            transition,
            {"schema_version", "delta", "event"},
            "Kernel compiled transition",
        )
        if transition["schema_version"] != "kernel-compiled-transition.v1":
            raise ValueError("Kernel shadow Artifact transition schema mismatch")
        delta = transition["delta"]
        event = transition["event"]
        _verify_raw_delta(delta, event_log["run_id"])
        _verify_raw_event(event)
        if event["sequence"] != expected_sequence:
            raise ValueError("Kernel shadow Artifact Event Log sequence mismatch")
        if event["tick"] <= previous_tick or event["tick"] != delta["tick"]:
            raise ValueError("Kernel shadow Artifact Event Log tick mismatch")
        if delta["parent_state_hash"] != current_hash or event["input_state_hash"] != current_hash:
            raise ValueError("Kernel shadow Artifact Event Log state hash chain mismatch")
        delta_hash = stable_hash(delta)
        if event["delta_hash"] != delta_hash:
            raise ValueError("Kernel shadow Artifact Event Log Delta hash mismatch")

        _apply_raw_delta(working, delta)
        output_hash = stable_hash(working)
        if event["output_state_hash"] != output_hash:
            raise ValueError("Kernel shadow Artifact replay output hash mismatch")
        if output_hash == current_hash and delta["changes"]:
            raise ValueError("Kernel shadow Artifact changed Delta retained input hash")
        current_hash = output_hash
        previous_tick = event["tick"]

    if current_hash != event_log["final_state_hash"]:
        raise ValueError("Kernel shadow Artifact Event Log final state hash mismatch")
    return WorldState.model_validate(working)


def _verify_raw_world_state(state: Any) -> None:
    if not isinstance(state, dict):
        raise ValueError("Kernel shadow Artifact initial state must be an object")
    _require_exact_keys(
        state,
        {"schema_version", "run_id", "tick", "seed", "rule_pack_hash", "entities"},
        "Kernel WorldState",
    )
    if state["schema_version"] != "kernel-world-state.v1":
        raise ValueError("Kernel shadow Artifact WorldState schema mismatch")
    _require_string(state["run_id"], "Kernel WorldState run id", 160)
    _require_int(state["tick"], "Kernel WorldState tick", minimum=0)
    _require_int(state["seed"], "Kernel WorldState seed")
    _require_string(state["rule_pack_hash"], "Kernel WorldState Rule Pack hash", 128)
    entities = state["entities"]
    if not isinstance(entities, dict):
        raise ValueError("Kernel shadow Artifact WorldState entities are malformed")
    for entity_id, entity in entities.items():
        _require_string(entity_id, "Kernel Entity key", 160)
        if not isinstance(entity, dict):
            raise ValueError("Kernel shadow Artifact Entity must be an object")
        _require_exact_keys(
            entity,
            {"entity_id", "entity_type", "components"},
            "Kernel Entity",
        )
        if entity["entity_id"] != entity_id:
            raise ValueError("Kernel shadow Artifact Entity id mismatch")
        _require_string(entity["entity_type"], "Kernel Entity type", 80)
        if not isinstance(entity["components"], dict):
            raise ValueError("Kernel shadow Artifact Entity components are malformed")


def _verify_raw_delta(delta: Any, run_id: str) -> None:
    if not isinstance(delta, dict):
        raise ValueError("Kernel shadow Artifact Delta must be an object")
    _require_exact_keys(
        delta,
        {
            "schema_version",
            "run_id",
            "tick",
            "parent_state_hash",
            "reducer_version",
            "source",
            "changes",
        },
        "Kernel StateDelta",
    )
    if delta["schema_version"] != "kernel-state-delta.v1":
        raise ValueError("Kernel shadow Artifact Delta schema mismatch")
    if delta["run_id"] != run_id:
        raise ValueError("Kernel shadow Artifact Delta run id mismatch")
    _require_int(delta["tick"], "Kernel StateDelta tick", minimum=1)
    _require_hash(delta["parent_state_hash"], "Kernel StateDelta parent hash")
    _require_string(delta["reducer_version"], "Kernel StateDelta reducer", 120)
    if delta["source"] != "deterministic_reducer":
        raise ValueError("Kernel shadow Artifact Delta source is not deterministic")
    changes = delta["changes"]
    if not isinstance(changes, list):
        raise ValueError("Kernel shadow Artifact Delta changes are malformed")
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Kernel shadow Artifact StateChange must be an object")
        _require_exact_keys(
            change,
            {"entity_id", "component", "value"},
            "Kernel StateChange",
        )
        _require_string(change["entity_id"], "Kernel StateChange entity id", 160)
        _require_string(change["component"], "Kernel StateChange component", 160)


def _verify_raw_event(event: Any) -> None:
    if not isinstance(event, dict):
        raise ValueError("Kernel shadow Artifact Event must be an object")
    _require_exact_keys(
        event,
        {
            "schema_version",
            "event_id",
            "sequence",
            "tick",
            "event_type",
            "input_state_hash",
            "output_state_hash",
            "delta_hash",
            "payload",
        },
        "Kernel EventEnvelope",
    )
    if event["schema_version"] != "kernel-event-envelope.v1":
        raise ValueError("Kernel shadow Artifact Event schema mismatch")
    _require_string(event["event_id"], "Kernel Event id", 160)
    _require_int(event["sequence"], "Kernel Event sequence", minimum=1)
    _require_int(event["tick"], "Kernel Event tick", minimum=0)
    _require_string(event["event_type"], "Kernel Event type", 120)
    _require_hash(event["input_state_hash"], "Kernel Event input hash")
    _require_hash(event["output_state_hash"], "Kernel Event output hash")
    _require_hash(event["delta_hash"], "Kernel Event Delta hash")
    if not isinstance(event["payload"], dict):
        raise ValueError("Kernel shadow Artifact Event payload is malformed")


def _apply_raw_delta(state: dict[str, Any], delta: dict[str, Any]) -> None:
    if delta["tick"] <= state["tick"]:
        raise ValueError("Kernel shadow Artifact Delta did not advance state")
    entities = state["entities"]
    for change in delta["changes"]:
        entity = entities.get(change["entity_id"])
        if entity is None:
            raise ValueError("Kernel shadow Artifact Delta references unknown Entity")
        entity["components"][change["component"]] = change["value"]
    state["tick"] = delta["tick"]


def _require_string(value: Any, label: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} is malformed")


def _require_hash(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} is malformed")


def _require_int(value: Any, label: str, *, minimum: int | None = None) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} is malformed")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} is below minimum")


def _require_exact_keys(
    value: dict[str, Any], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields mismatch")
