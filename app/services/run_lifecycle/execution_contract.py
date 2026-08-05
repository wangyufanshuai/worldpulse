"""Pinned lifecycle execution-contract selection for ADR-0007 rollout.

This slice makes recovery/version selection executable while intentionally
keeping V2 creation and claiming disabled until the worker generation,
retirement, credential and direct-SQLite hard fences are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import RunJobStatus
from app.services.consistency.hashing import stable_hash


EXECUTION_CONTRACT_KEY = "execution_contract_version"
KERNEL_MODE_EXECUTION_V2: Literal["kernel-mode-execution.v2"] = (
    "kernel-mode-execution.v2"
)
V2_PROFILE_KEYS = frozenset(
    {
        EXECUTION_CONTRACT_KEY,
        "effective_seed",
        "minimum_worker_generation",
        "agent_pack_resolver_version",
        "constraint_context_resolver_version",
        "evaluator_version",
    }
)
FORBIDDEN_DERIVED_PROFILE_KEYS = frozenset(
    {"agent_pack_id", "agent_pack_hash", "constraint_context_hash"}
)
ExecutionContractKind = Literal["legacy-v1", "kernel-mode-execution.v2"]


class V2ExecutionPathNotEnabledError(RuntimeError):
    """A V2-pinned job reached a deployment that cannot safely claim it."""


class KernelModeExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution_contract_version: Literal["kernel-mode-execution.v2"]
    effective_seed: int
    minimum_worker_generation: int = Field(gt=0)
    agent_pack_resolver_version: str = Field(min_length=1, max_length=120)
    constraint_context_resolver_version: str = Field(min_length=1, max_length=120)
    evaluator_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def reject_boolean_seed(self) -> Self:
        if type(self.effective_seed) is not int:
            raise ValueError("effective_seed must be a strict integer")
        return self


@dataclass(frozen=True)
class ExecutionContractSelection:
    kind: ExecutionContractKind
    report_step_version: str
    replay_step_version: str
    profile: KernelModeExecutionProfile | None = None

    @property
    def is_v2(self) -> bool:
        return self.kind == KERNEL_MODE_EXECUTION_V2


LEGACY_EXECUTION = ExecutionContractSelection(
    kind="legacy-v1",
    report_step_version="report-generate.v1",
    replay_step_version="replay-archive.v1",
)


def select_execution_contract(runtime_profile: dict | None) -> ExecutionContractSelection:
    """Select exactly legacy-key-absent or complete V2; unknowns fail closed."""

    profile = dict(runtime_profile or {})
    marker_present = EXECUTION_CONTRACT_KEY in profile
    auxiliary_present = (V2_PROFILE_KEYS - {EXECUTION_CONTRACT_KEY}) & profile.keys()
    derived_present = FORBIDDEN_DERIVED_PROFILE_KEYS & profile.keys()
    if derived_present:
        raise ValueError(
            "runtime profile may not contain baseline-derived execution outputs"
        )
    if not marker_present:
        if auxiliary_present:
            raise ValueError("legacy runtime profile may not contain orphaned V2 keys")
        return LEGACY_EXECUTION
    if profile[EXECUTION_CONTRACT_KEY] != KERNEL_MODE_EXECUTION_V2:
        raise ValueError("unknown lifecycle execution contract version")
    missing = V2_PROFILE_KEYS - profile.keys()
    if missing:
        raise ValueError(
            f"V2 runtime profile is missing required keys: {', '.join(sorted(missing))}"
        )
    selected_payload = {key: profile[key] for key in V2_PROFILE_KEYS}
    pinned = KernelModeExecutionProfile.model_validate(selected_payload)
    return ExecutionContractSelection(
        kind=KERNEL_MODE_EXECUTION_V2,
        report_step_version="report-generate.v2",
        replay_step_version="replay-archive.v2",
        profile=pinned,
    )


def select_job_execution_contract(job: RunJobStatus) -> ExecutionContractSelection:
    selection = select_execution_contract(job.runtime_profile)
    if selection.is_v2 and not job.runtime_profile_hash:
        raise ValueError("V2 runtime profile is missing its hash")
    if job.runtime_profile_hash and stable_hash(job.runtime_profile) != job.runtime_profile_hash:
        raise ValueError("runtime profile hash mismatch")
    if selection.profile is not None and selection.profile.effective_seed != job.seed:
        raise ValueError("V2 runtime profile seed does not match the pinned job seed")
    return selection


def pin_legacy_execution_contract(runtime_profile: dict | None) -> dict:
    """Remove caller-controlled V2/derived keys while rollout creation is closed."""

    profile = dict(runtime_profile or {})
    for key in V2_PROFILE_KEYS | FORBIDDEN_DERIVED_PROFILE_KEYS:
        profile.pop(key, None)
    return profile


def require_claimable_execution_contract(runtime_profile: dict | None) -> None:
    selection = select_execution_contract(runtime_profile)
    if selection.is_v2:
        raise V2ExecutionPathNotEnabledError(
            "kernel-mode-execution.v2 claiming remains disabled until the worker "
            "generation, retirement, credential and database-isolation fences are active"
        )


def report_replay_step_versions(runtime_profile: dict | None) -> tuple[str, str]:
    selection = select_execution_contract(runtime_profile)
    return selection.report_step_version, selection.replay_step_version
