"""Run Control policy and preparation adapter for Kernel shadow Artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core.models import RunArtifactSummary, RunJobStatus, WarRoomRun
from app.services.consistency.hashing import stable_hash
from app.services.project_store import dumps
from app.services.simulation_kernel import (
    KernelShadowArtifact,
    VerifiedKernelShadowArtifact,
    build_kernel_shadow_artifact,
    verify_kernel_shadow_artifact_payload,
)
from app.services.world_model import world_model_service


KERNEL_SHADOW_ARTIFACT_TYPE = "kernel_shadow_run"
KERNEL_SHADOW_ENV = "WORLDPULSE_KERNEL_SHADOW_ARTIFACTS"
KERNEL_SHADOW_POLICY_KEY = "_worldpulse_kernel_shadow_artifact"
KERNEL_SHADOW_POLICY_SCHEMA = "kernel-shadow-artifact-policy.v1"
KERNEL_SHADOW_MAX_BYTES = 524_288

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})


class KernelShadowArtifactPolicy(BaseModel):
    """Hashed job-time policy; all values are intentionally non-configurable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["kernel-shadow-artifact-policy.v1"] = "kernel-shadow-artifact-policy.v1"
    enabled: Literal[True] = True
    artifact_schema_version: Literal["kernel-shadow-artifact.v1"] = "kernel-shadow-artifact.v1"
    max_bytes: Literal[524288] = 524_288


@dataclass(frozen=True)
class PreparedKernelShadowArtifact:
    envelope: KernelShadowArtifact
    payload: dict[str, Any]
    payload_bytes: int


def pin_kernel_shadow_policy(runtime_profile: dict | None) -> dict:
    """Remove caller control of the reserved key and pin the deployment choice."""

    profile = dict(runtime_profile or {})
    profile.pop(KERNEL_SHADOW_POLICY_KEY, None)
    if kernel_shadow_artifacts_enabled_from_env():
        profile[KERNEL_SHADOW_POLICY_KEY] = KernelShadowArtifactPolicy().model_dump(
            mode="json"
        )
    return profile


def kernel_shadow_artifacts_enabled_from_env() -> bool:
    raw = os.getenv(KERNEL_SHADOW_ENV, "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{KERNEL_SHADOW_ENV} must be one of: 0, 1, false, true, no, yes, off, on"
    )


def kernel_shadow_policy_for_job(
    job: RunJobStatus,
) -> KernelShadowArtifactPolicy | None:
    raw = job.runtime_profile.get(KERNEL_SHADOW_POLICY_KEY)
    if raw is None:
        return None
    if not job.runtime_profile_hash:
        raise ValueError("Kernel shadow job policy is missing runtime profile hash")
    if stable_hash(job.runtime_profile) != job.runtime_profile_hash:
        raise ValueError("Kernel shadow job runtime profile hash mismatch")
    return KernelShadowArtifactPolicy.model_validate(raw)


def prepare_kernel_shadow_artifact(
    *,
    job: RunJobStatus,
    result: WarRoomRun,
    source_artifact: RunArtifactSummary,
    policy: KernelShadowArtifactPolicy,
) -> PreparedKernelShadowArtifact:
    if job.seed is None:
        raise ValueError("Kernel shadow Artifact requires a pinned seed")
    if not job.rule_pack_hash:
        raise ValueError("Kernel shadow Artifact requires a pinned Rule Pack hash")
    if source_artifact.run_id != job.run_id:
        raise ValueError("Kernel shadow source Artifact run id mismatch")
    if source_artifact.artifact_type != "war_room_result":
        raise ValueError("Kernel shadow source Artifact type mismatch")

    envelope = build_kernel_shadow_artifact(
        result,
        world_model_service.war_room_presets(),
        run_id=job.run_id,
        seed=job.seed,
        rule_pack_hash=job.rule_pack_hash,
        source_artifact_schema_version=source_artifact.schema_version,
        source_artifact_sha256=source_artifact.sha256,
    )
    payload = envelope.model_dump(mode="json")
    payload_bytes = len(dumps(payload).encode("utf-8"))
    if payload_bytes > policy.max_bytes:
        raise ValueError(
            "Kernel shadow Artifact exceeds fixed size budget: "
            f"{payload_bytes} > {policy.max_bytes} bytes"
        )
    return PreparedKernelShadowArtifact(
        envelope=envelope,
        payload=payload,
        payload_bytes=payload_bytes,
    )


def verify_persisted_kernel_shadow_artifact(
    payload: dict,
    *,
    job: RunJobStatus,
    source_result: WarRoomRun,
    source_artifact: RunArtifactSummary,
) -> VerifiedKernelShadowArtifact:
    envelope = verify_kernel_shadow_artifact_payload(payload)
    if envelope.run_id != job.run_id:
        raise ValueError("Persisted Kernel shadow Artifact run id mismatch")
    if envelope.seed != job.seed:
        raise ValueError("Persisted Kernel shadow Artifact seed mismatch")
    if envelope.rule_pack_hash != job.rule_pack_hash:
        raise ValueError("Persisted Kernel shadow Artifact Rule Pack hash mismatch")
    if envelope.source_artifact_type != source_artifact.artifact_type:
        raise ValueError("Persisted Kernel shadow source Artifact type mismatch")
    if envelope.source_artifact_schema_version != source_artifact.schema_version:
        raise ValueError("Persisted Kernel shadow source schema mismatch")
    if envelope.source_artifact_sha256 != source_artifact.sha256:
        raise ValueError("Persisted Kernel shadow source SHA-256 mismatch")
    envelope.verify_source_result(source_result)
    return envelope
