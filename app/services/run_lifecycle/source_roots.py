"""Closed current-attempt roots for V2 resolver and proof-source steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.consistency.hashing import stable_hash
from app.services.negotiation import (
    AgentRuntimeResultSource,
    ConsistencyAuditSource,
    KernelProposalBatchSource,
    ProjectionAuditSource,
)
from app.services.simulation_kernel import (
    DeterministicRunResolverOutput,
    ResolverArtifactReference,
    agent_pack_resolver_payload_hash,
    constraint_context_resolver_payload_hash,
    parse_agent_pack_resolver_payload,
    parse_constraint_context_resolver_payload,
    parse_deterministic_run_resolver_output,
    parse_resolver_artifact_ref,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
EngineMode = Literal[
    "deterministic",
    "mock_agent",
    "controlled_agent",
    "hybrid",
    "hybrid_recorded",
    "negotiation",
]
ProofSchema = Literal[
    "kp.agent-runtime.v1",
    "kp.proposal-batch.v1",
    "kp.final-consistency.v1",
    "kp.negotiation-round.v1",
    "kp.negotiation-proposal-batch.v1",
    "kp.negotiation-admission-consistency.v1",
    "kp.negotiation-eligibility.v1",
    "kp.negotiation-projection-consistency.v1",
    "kp.action-modifier-bundle.v1",
    "kp.narrative-diffusion.v1",
    "kp.commitment-ledger.v1",
    "kp.projection-audit.v1",
    "kp.hybrid-replay.v1",
    "kp.negotiation-replay.v1",
]
ProofArtifactRefTuple = tuple[
    Literal["proof"],
    str,
    str,
    str,
    ProofSchema,
    str,
]


class SourceRootError(ValueError):
    """A completed V2 source step does not match its immutable Artifact root."""


def _restore_json_arrays(value: object) -> object:
    if isinstance(value, list):
        return tuple(_restore_json_arrays(item) for item in value)
    if isinstance(value, dict):
        return {key: _restore_json_arrays(item) for key, item in value.items()}
    return value


class _ClosedRootModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def restore_json_arrays(cls, value: object) -> object:
        return _restore_json_arrays(value)


class ProofArtifactReference(_ClosedRootModel):
    discriminator: Literal["proof"]
    artifact_id: str = Field(min_length=1, max_length=160)
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    content_hash: str = Field(pattern=SHA256_PATTERN)
    proof_schema: ProofSchema
    attempt: str = Field(min_length=1, max_length=160)

    def as_tuple(self) -> ProofArtifactRefTuple:
        return (
            self.discriminator,
            self.artifact_id,
            self.artifact_sha256,
            self.content_hash,
            self.proof_schema,
            self.attempt,
        )


class ModeProofStepOutput(_ClosedRootModel):
    schema_version: Literal["mode-proof-step-output.v1"]
    run_id: str = Field(min_length=1, max_length=160)
    attempt: str = Field(min_length=1, max_length=160)
    engine_mode: EngineMode
    artifact_refs: tuple[ProofArtifactRefTuple, ...]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        references = tuple(
            parse_proof_artifact_ref(item) for item in self.artifact_refs
        )
        artifact_ids = tuple(item.artifact_id for item in references)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("proof-step Artifact IDs must be unique")
        if any(item.attempt != self.attempt for item in references):
            raise ValueError("proof-step refs must bind the current attempt")
        return self


@dataclass(frozen=True)
class RootArtifact:
    artifact_id: str
    artifact_type: str
    schema_version: str
    sha256: str
    attempt_id: str | None
    supersedes_artifact_id: str | None
    payload: dict[str, Any]


def parse_proof_artifact_ref(value: object) -> ProofArtifactReference:
    if not isinstance(value, (tuple, list)) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise SourceRootError("proof Artifact ref must be a six-member tuple/list")
    if len(value) != 6 or value[0] != "proof":
        raise SourceRootError("proof Artifact ref discriminator/width mismatch")
    if any(not isinstance(item, str) for item in value):
        raise SourceRootError("proof Artifact ref members must be strings")
    return ProofArtifactReference.model_validate(
        {
            "discriminator": value[0],
            "artifact_id": value[1],
            "artifact_sha256": value[2],
            "content_hash": value[3],
            "proof_schema": value[4],
            "attempt": value[5],
        },
        strict=True,
    )


def build_proof_artifact_ref(
    artifact: RootArtifact,
    *,
    proof_schema: ProofSchema,
    content_hash: str,
) -> ProofArtifactReference:
    if artifact.attempt_id is None:
        raise SourceRootError("V2 proof Artifact is missing its attempt")
    return ProofArtifactReference(
        discriminator="proof",
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        content_hash=content_hash,
        proof_schema=proof_schema,
        attempt=artifact.attempt_id,
    )


def build_mode_proof_step_output(
    *,
    run_id: str,
    attempt: str,
    engine_mode: EngineMode,
    references: tuple[ProofArtifactReference, ...],
) -> ModeProofStepOutput:
    return ModeProofStepOutput(
        schema_version="mode-proof-step-output.v1",
        run_id=run_id,
        attempt=attempt,
        engine_mode=engine_mode,
        artifact_refs=tuple(item.as_tuple() for item in references),
    )


def validate_resolver_step_root(
    value: object,
    *,
    run_id: str,
    attempt: str,
    engine_mode: str,
    effective_seed: int,
    agent_pack_resolver_version: str,
    constraint_context_resolver_version: str,
    scenario_hash: str,
    rule_pack_hash: str,
    artifacts: tuple[RootArtifact, ...],
) -> DeterministicRunResolverOutput:
    if engine_mode == "deterministic":
        raise SourceRootError("deterministic mode may not carry a resolver root")
    output = parse_deterministic_run_resolver_output(value)
    if (
        output.run_id != run_id
        or output.attempt != attempt
        or output.effective_seed != effective_seed
        or output.agent_pack_resolver_version != agent_pack_resolver_version
        or output.constraint_context_resolver_version
        != constraint_context_resolver_version
        or output.scenario_hash != scenario_hash
        or output.rule_pack_hash != rule_pack_hash
    ):
        raise SourceRootError("deterministic-run resolver coordinates drift")
    by_type: dict[str, list[RootArtifact]] = {}
    for artifact in artifacts:
        by_type.setdefault(artifact.artifact_type, []).append(artifact)
    if set(by_type) != {
        "war_room_result",
        "agent_pack",
        "agent_constraint_context",
    } or any(len(items) != 1 for items in by_type.values()):
        raise SourceRootError("resolver step must bind baseline plus exactly two resolvers")
    baseline = by_type["war_room_result"][0]
    agent_pack = by_type["agent_pack"][0]
    context = by_type["agent_constraint_context"][0]
    if any(item.attempt_id != attempt for item in artifacts):
        raise SourceRootError("resolver step contains a cross-attempt Artifact")
    if any(item.supersedes_artifact_id is not None for item in artifacts):
        raise SourceRootError("fresh resolver root may not carry implicit supersedes")
    if (
        baseline.schema_version != "war-room-result.v1"
        or stable_hash(baseline.payload) != output.baseline_result_hash
        or agent_pack.schema_version != "agent-pack-resolver-output.v1"
        or context.schema_version != "constraint-context-resolver-output.v1"
    ):
        raise SourceRootError("resolver step Artifact schema/result binding mismatch")
    agent_payload = parse_agent_pack_resolver_payload(agent_pack.payload)
    context_payload = parse_constraint_context_resolver_payload(context.payload)
    if (
        agent_pack_resolver_payload_hash(agent_payload) != output.agent_pack_hash
        or constraint_context_resolver_payload_hash(context_payload)
        != output.constraint_context_hash
        or agent_payload.agent_pack_id != output.agent_pack_id
    ):
        raise SourceRootError("resolver step content hashes do not match output")
    expected_artifacts = (agent_pack, context)
    for raw_ref, artifact, expected_schema, expected_hash in zip(
        output.artifact_refs,
        expected_artifacts,
        (
            "agent-pack-resolver-output.v1",
            "constraint-context-resolver-output.v1",
        ),
        (output.agent_pack_hash, output.constraint_context_hash),
        strict=True,
    ):
        reference = parse_resolver_artifact_ref(raw_ref)
        if (
            reference.artifact_id != artifact.artifact_id
            or reference.artifact_sha256 != artifact.sha256
            or reference.content_hash != expected_hash
            or reference.resolver_schema != expected_schema
            or reference.attempt != attempt
        ):
            raise SourceRootError("resolver Artifact tuple does not match its row")
    return output


def validate_mode_proof_step_root(
    value: object,
    *,
    run_id: str,
    attempt: str,
    engine_mode: str,
    artifacts: tuple[RootArtifact, ...],
) -> ModeProofStepOutput:
    output = ModeProofStepOutput.model_validate(value, strict=True)
    if (
        output.run_id != run_id
        or output.attempt != attempt
        or output.engine_mode != engine_mode
    ):
        raise SourceRootError("proof-step coordinates drift")
    references = tuple(
        parse_proof_artifact_ref(item) for item in output.artifact_refs
    )
    if tuple(item.artifact_id for item in references) != tuple(
        artifact.artifact_id for artifact in artifacts
    ):
        raise SourceRootError("proof-step order does not match stored Artifact refs")
    for reference, artifact in zip(references, artifacts, strict=True):
        expected_type, expected_schema, expected_hash = _proof_source_identity(
            reference.proof_schema,
            artifact.payload,
        )
        supersedes_allowed = (
            engine_mode == "controlled_agent"
            and reference.proof_schema == "kp.agent-runtime.v1"
        )
        if artifact.supersedes_artifact_id is not None and not supersedes_allowed:
            raise SourceRootError(
                "implicit or mode-inapplicable proof supersedes is forbidden"
            )
        if (
            artifact.attempt_id != attempt
            or artifact.artifact_type != expected_type
            or artifact.schema_version != expected_schema
            or artifact.sha256 != reference.artifact_sha256
            or expected_hash != reference.content_hash
        ):
            raise SourceRootError("proof Artifact tuple does not match its row/payload")
    tokens = tuple(item.proof_schema for item in references)
    if engine_mode == "deterministic" and tokens != (
        "kp.final-consistency.v1",
    ):
        raise SourceRootError("deterministic proof-step sequence must be FC only")
    if engine_mode == "mock_agent" and tokens not in {
        ("kp.proposal-batch.v1", "kp.final-consistency.v1"),
        (
            "kp.proposal-batch.v1",
            "kp.final-consistency.v1",
            "kp.projection-audit.v1",
        ),
    }:
        raise SourceRootError("mock_agent proof-step sequence is not canonical")
    if engine_mode == "controlled_agent" and tokens not in {
        (
            "kp.agent-runtime.v1",
            "kp.proposal-batch.v1",
            "kp.final-consistency.v1",
        ),
        (
            "kp.agent-runtime.v1",
            "kp.proposal-batch.v1",
            "kp.final-consistency.v1",
            "kp.projection-audit.v1",
        ),
    }:
        raise SourceRootError("controlled_agent proof-step sequence is not canonical")
    return output


def _proof_source_identity(
    proof_schema: str,
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    if proof_schema == "kp.agent-runtime.v1":
        source = AgentRuntimeResultSource.model_validate(payload)
        return "agent_runtime_audit", source.schema_version, source.runtime_hash
    if proof_schema == "kp.proposal-batch.v1":
        source = KernelProposalBatchSource.model_validate(payload)
        return "agent_action_proposals", source.schema_version, source.batch_hash
    if proof_schema == "kp.final-consistency.v1":
        source = ConsistencyAuditSource.model_validate(payload)
        if source.role != "final" or source.tick is not None:
            raise SourceRootError("FC root must select final/null-tick Consistency")
        return "consistency_audit", source.schema_version, source.audit_hash
    if proof_schema == "kp.projection-audit.v1":
        source = ProjectionAuditSource.model_validate(payload)
        if source.schema_version != "agent-action-projection-audit.v2":
            raise SourceRootError("non-negotiation PA root has the wrong schema")
        return "agent_action_projection_audit", source.schema_version, source.audit_hash
    raise SourceRootError(f"proof-step schema is not enabled: {proof_schema}")


def root_artifact_from_summary(summary, payload: dict[str, Any]) -> RootArtifact:
    return RootArtifact(
        artifact_id=summary.artifact_id,
        artifact_type=summary.artifact_type,
        schema_version=summary.schema_version,
        sha256=summary.sha256,
        attempt_id=summary.attempt_id,
        supersedes_artifact_id=summary.supersedes_artifact_id,
        payload=payload,
    )


def resolver_reference_from_artifact(
    artifact: RootArtifact,
    *,
    content_hash: str,
    resolver_schema: Literal[
        "agent-pack-resolver-output.v1",
        "constraint-context-resolver-output.v1",
    ],
) -> ResolverArtifactReference:
    if artifact.attempt_id is None:
        raise SourceRootError("V2 resolver Artifact is missing its attempt")
    return ResolverArtifactReference(
        discriminator="resolver",
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.sha256,
        content_hash=content_hash,
        resolver_schema=resolver_schema,
        attempt=artifact.attempt_id,
    )
