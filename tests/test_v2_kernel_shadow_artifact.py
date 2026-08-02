from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.services.project_store import dumps
from app.services.consistency.hashing import stable_hash
from app.services.run_lifecycle.integrity import artifact_digest
from app.services.simulation_kernel import (
    KernelShadowArtifact,
    build_kernel_shadow_artifact,
    verify_kernel_shadow_artifact_payload,
)
from app.services.war_room_engine import run_war_room
from app.services.world_model import world_model_service
from app.services.simulation_runtime import simulation_runtime_service


GOLDEN_FIXTURES = sorted(Path("tests/golden_scenarios").glob("*.json"))


def _artifact() -> tuple[KernelShadowArtifact, WarRoomRun]:
    result = run_war_room(
        WarRoomScenarioRequest(
            scenario_key="strait_blockade_30d",
            intensity=0.8,
            propagation=0.55,
            policy_actions=["sanctions"],
            seed=7,
        )
    )
    source_payload = result.model_dump()
    artifact = build_kernel_shadow_artifact(
        result,
        world_model_service.war_room_presets(),
        run_id="job_kernel_artifact_contract",
        seed=7,
        rule_pack_hash="a" * 64,
        source_artifact_schema_version="war-room-result.v1",
        source_artifact_sha256=artifact_digest(dumps(source_payload)),
    )
    return artifact, result


def test_kernel_shadow_artifact_is_source_linked_and_provider_free_replayable():
    artifact, result = _artifact()

    artifact.verify_source_result(result)
    replayed = artifact.replay_stored()
    assert artifact.schema_version == "kernel-shadow-artifact.v1"
    assert artifact.baseline_scope == "deterministic_pre_agent"
    assert artifact.source_artifact_type == "war_room_result"
    assert replayed.content_hash() == artifact.final_state_hash
    assert artifact.shadow_run.event_log.content_hash() == artifact.event_log_hash
    assert artifact.shadow_run.content_hash() == artifact.shadow_run_hash
    assert len(artifact.content_hash()) == 64
    stored = verify_kernel_shadow_artifact_payload(artifact.model_dump(mode="json"))
    assert stored.content_hash() == artifact.content_hash()
    assert stored.replay_stored().content_hash() == artifact.final_state_hash


@pytest.mark.parametrize(
    "field",
    ["shadow_run_hash", "event_log_hash", "final_state_hash"],
)
def test_kernel_shadow_artifact_rejects_tampered_nested_hashes(field):
    artifact, _result = _artifact()
    payload = deepcopy(artifact.model_dump(mode="json"))
    payload[field] = "0" * 64

    with pytest.raises(ValidationError, match="hash mismatch"):
        KernelShadowArtifact.model_validate(payload)


def test_kernel_shadow_artifact_rejects_wrong_source_result_and_unknown_fields():
    artifact, result = _artifact()
    payload = deepcopy(artifact.model_dump(mode="json"))
    payload["source_run_hash"] = "0" * 64
    changed_source = KernelShadowArtifact.model_validate(payload)

    with pytest.raises(ValueError, match="source run hash mismatch"):
        changed_source.verify_source_result(result)

    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="extra"):
        KernelShadowArtifact.model_validate(payload)


@pytest.mark.parametrize("tamper", ["checkpoint_state", "checkpoint_parent"])
def test_fast_stored_verifier_rejects_rehashed_checkpoint_tampering(tamper):
    artifact, _result = _artifact()
    payload = deepcopy(artifact.model_dump(mode="json"))
    checkpoints = payload["shadow_run"]["checkpoints"]
    if tamper == "checkpoint_state":
        checkpoints[1]["world_state"]["tick"] += 1
    else:
        checkpoints[1]["parent_checkpoint_hash"] = "0" * 64
    payload["shadow_run_hash"] = stable_hash(payload["shadow_run"])

    with pytest.raises(ValueError, match="checkpoint .* mismatch"):
        verify_kernel_shadow_artifact_payload(payload)


@pytest.mark.parametrize("fixture_path", GOLDEN_FIXTURES, ids=lambda path: path.stem)
def test_raw_stored_replay_matches_full_kernel_contract_for_all_golden_runs(
    fixture_path: Path,
):
    record = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = WarRoomScenarioRequest(**record["scenario"])
    result = simulation_runtime_service.run_war_room(request)
    artifact = build_kernel_shadow_artifact(
        result,
        world_model_service.war_room_presets(),
        run_id=f"artifact:{fixture_path.stem}",
        seed=record["scenario"]["seed"],
        rule_pack_hash="a" * 64,
        source_artifact_schema_version="war-room-result.v1",
        source_artifact_sha256="b" * 64,
    )

    stored = verify_kernel_shadow_artifact_payload(
        artifact.model_dump(mode="json")
    )
    stored.verify_source_result(result)
    assert stored.content_hash() == artifact.content_hash()
    assert stored.replay_stored().content_hash() == artifact.replay_stored().content_hash()
    assert stored.final_state_hash == artifact.final_state_hash
