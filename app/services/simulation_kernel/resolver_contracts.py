"""Closed, provider-free resolver lineage contracts required by ADR-0007.

The models in this module are private V2 Run Control contracts.  They do not
replace the legacy Agent Pack or constraint-context public models and they do
not enable the V2 lifecycle path.  Every helper is a pure canonicalization or
verification function: no storage, provider, network, or wall-clock access is
permitted here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Self, TypeAlias, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.negotiation_models import AgentPackManifest
from app.services.agent_contract.models import (
    ActionType,
    ActorType,
    AgentConstraintContext,
)
from app.services.consistency.hashing import stable_hash


SHA256_PATTERN = r"^[0-9a-f]{64}$"
Digest: TypeAlias = Annotated[str, Field(pattern=SHA256_PATTERN)]
AGENT_PACK_RESOLVER_VERSION: Literal["agent-pack-resolver.v1"] = "agent-pack-resolver.v1"
CONSTRAINT_CONTEXT_RESOLVER_VERSION: Literal["constraint-context-resolver.v1"] = "constraint-context-resolver.v1"
AGENT_PACK_RESOLVER_PAYLOAD_SCHEMA: Literal["agent-pack-resolver-payload.v1"] = "agent-pack-resolver-payload.v1"
CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA: Literal["agent-constraint-context.v1"] = "agent-constraint-context.v1"
DETERMINISTIC_RUN_RESOLVER_OUTPUT_SCHEMA: Literal["deterministic-run-resolver-output.v1"] = (
    "deterministic-run-resolver-output.v1"
)
RESOLVER_CREATED_AT: Literal["2000-01-01T00:00:00.000Z"] = "2000-01-01T00:00:00.000Z"

ResolverSchema: TypeAlias = Literal[
    "agent-pack-resolver-output.v1",
    "constraint-context-resolver-output.v1",
]
ResolverArtifactRefTuple: TypeAlias = tuple[
    Literal["resolver"],
    str,
    Digest,
    Digest,
    ResolverSchema,
    str,
]
ActorCapabilityTuple: TypeAlias = tuple[str, tuple[ActionType, ...]]
ActionBudgetTuple: TypeAlias = tuple[str, int]
ACTION_TYPES = frozenset(get_args(ActionType))


def _utf8_sort_key(value: str) -> bytes:
    return value.encode("utf-8")


def _require_ascending_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must be unique")
    if values != tuple(sorted(values, key=_utf8_sort_key)):
        raise ValueError(f"{field_name} must be ascending UTF-8 byte order")


def _agent_pack_id_from_legacy_hash(legacy_manifest_hash: str) -> str:
    """Preserve the production resolver's deterministic legacy ID scheme."""

    return f"agent_pack_{legacy_manifest_hash[:20]}"


def _restore_json_arrays(value: object) -> object:
    if isinstance(value, list):
        return tuple(_restore_json_arrays(item) for item in value)
    if isinstance(value, dict):
        return {key: _restore_json_arrays(item) for key, item in value.items()}
    return value


class _ClosedResolverModel(BaseModel):
    """Strict immutable model that accepts canonical JSON arrays as tuples."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def restore_json_arrays(cls, value: object) -> object:
        return _restore_json_arrays(value)


class ResolverArtifactReference(_ClosedResolverModel):
    """One closed ``artifact_refs`` resolver tuple from ADR-0007."""

    discriminator: Literal["resolver"]
    artifact_id: str = Field(min_length=1, max_length=160)
    artifact_sha256: Digest
    content_hash: Digest
    resolver_schema: ResolverSchema
    attempt: str = Field(min_length=1, max_length=160)

    def as_tuple(self) -> ResolverArtifactRefTuple:
        return (
            self.discriminator,
            self.artifact_id,
            self.artifact_sha256,
            self.content_hash,
            self.resolver_schema,
            self.attempt,
        )


class AgentPackResolverProfile(_ClosedResolverModel):
    """Closed canonical profile embedded in the V2 Agent Pack payload."""

    agent_id: str = Field(min_length=1, max_length=160)
    actor_type: ActorType
    country_code: str = Field(min_length=1, max_length=32)
    country_name: str = Field(min_length=1, max_length=160)
    capabilities: tuple[ActionType, ...] = Field(min_length=1)
    action_budget: int = Field(ge=1, le=12)
    profile_hash: Digest

    @model_validator(mode="after")
    def validate_canonical_capabilities(self) -> Self:
        _require_ascending_unique(self.capabilities, "profile capabilities")
        if type(self.action_budget) is not int:
            raise ValueError("profile action_budget must be a strict integer")
        return self


class AgentPackResolverPayload(_ClosedResolverModel):
    """Complete Agent Pack Artifact content; its authority hash is external."""

    schema_version: Literal["agent-pack-resolver-payload.v1"]
    agent_pack_id: str = Field(min_length=1, max_length=160)
    status: Literal["active"]
    seed: int
    profiles: tuple[AgentPackResolverProfile, ...] = Field(min_length=1)
    legacy_manifest_hash: Digest
    created_at: Literal["2000-01-01T00:00:00.000Z"]

    @model_validator(mode="after")
    def validate_complete_payload(self) -> Self:
        if type(self.seed) is not int:
            raise ValueError("Agent Pack seed must be a strict integer")
        if self.agent_pack_id != _agent_pack_id_from_legacy_hash(self.legacy_manifest_hash):
            raise ValueError("Agent Pack ID must bind the legacy manifest hash")
        _require_ascending_unique(
            tuple(profile.agent_id for profile in self.profiles),
            "Agent Pack profile IDs",
        )
        return self


class ConstraintContextResolverPayload(_ClosedResolverModel):
    """Closed tuple-map form of the V2 Agent constraint-context Artifact."""

    schema_version: Literal["agent-constraint-context.v1"]
    actor_capabilities: tuple[ActorCapabilityTuple, ...]
    action_budgets: tuple[ActionBudgetTuple, ...]
    known_entities: tuple[str, ...]
    known_evidence_refs: tuple[str, ...]
    source_label: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_complete_payload(self) -> Self:
        capability_ids = tuple(item[0] for item in self.actor_capabilities)
        budget_ids = tuple(item[0] for item in self.action_budgets)
        _require_ascending_unique(capability_ids, "actor_capabilities IDs")
        _require_ascending_unique(budget_ids, "action_budgets IDs")
        if capability_ids != budget_ids:
            raise ValueError("actor_capabilities and action_budgets IDs must match exactly")
        for agent_id, capabilities in self.actor_capabilities:
            if not agent_id:
                raise ValueError("constraint-context agent IDs must be non-empty")
            if not capabilities:
                raise ValueError("constraint-context capabilities must be non-empty")
            _require_ascending_unique(capabilities, f"constraint-context capabilities for {agent_id}")
        for agent_id, budget in self.action_budgets:
            if not agent_id:
                raise ValueError("constraint-context agent IDs must be non-empty")
            if type(budget) is not int or budget < 1 or budget > 12:
                raise ValueError("constraint-context action budgets must be strict integers in 1..12")
        _require_ascending_unique(self.known_entities, "known_entities")
        _require_ascending_unique(self.known_evidence_refs, "known_evidence_refs")
        return self


class DeterministicRunResolverOutput(_ClosedResolverModel):
    """Closed completed-step output binding both post-baseline resolvers."""

    schema_version: Literal["deterministic-run-resolver-output.v1"]
    run_id: str = Field(min_length=1, max_length=160)
    attempt: str = Field(min_length=1, max_length=160)
    agent_pack_resolver_version: Literal["agent-pack-resolver.v1"]
    constraint_context_resolver_version: Literal["constraint-context-resolver.v1"]
    effective_seed: int
    baseline_result_hash: Digest
    scenario_hash: Digest
    rule_pack_hash: Digest
    agent_pack_id: str = Field(min_length=1, max_length=160)
    agent_pack_hash: Digest
    constraint_context_hash: Digest
    artifact_refs: tuple[ResolverArtifactRefTuple, ResolverArtifactRefTuple]

    @model_validator(mode="after")
    def validate_complete_binding(self) -> Self:
        if type(self.effective_seed) is not int:
            raise ValueError("effective_seed must be a strict integer")
        agent_ref = parse_resolver_artifact_ref(self.artifact_refs[0])
        context_ref = parse_resolver_artifact_ref(self.artifact_refs[1])
        if agent_ref.resolver_schema != "agent-pack-resolver-output.v1":
            raise ValueError("first resolver ref must be the Agent Pack ref")
        if context_ref.resolver_schema != "constraint-context-resolver-output.v1":
            raise ValueError("second resolver ref must be the constraint-context ref")
        if agent_ref.artifact_id == context_ref.artifact_id:
            raise ValueError("resolver artifact refs must have unique Artifact IDs")
        if agent_ref.attempt != self.attempt or context_ref.attempt != self.attempt:
            raise ValueError("resolver artifact refs must bind the completed-step attempt")
        if agent_ref.content_hash != self.agent_pack_hash:
            raise ValueError("Agent Pack ref content_hash mismatch")
        if context_ref.content_hash != self.constraint_context_hash:
            raise ValueError("constraint-context ref content_hash mismatch")
        return self


class _LegacyAgentProfileSource(_ClosedResolverModel):
    """Strict view used only to verify an unchanged legacy profile."""

    agent_id: str = Field(min_length=1, max_length=160)
    actor_type: ActorType
    country_code: str = Field(min_length=1, max_length=32)
    country_name: str = Field(min_length=1, max_length=160)
    capabilities: tuple[ActionType, ...] = Field(min_length=1)
    action_budget: int = Field(ge=1, le=12)
    profile_hash: Digest

    @model_validator(mode="after")
    def validate_legacy_hash(self) -> Self:
        if type(self.action_budget) is not int:
            raise ValueError("legacy action_budget must be a strict integer")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("legacy profile capabilities must be unique")
        if self.profile_hash != stable_hash(self.core_dump()):
            raise ValueError("legacy profile_hash mismatch")
        return self

    def core_dump(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "actor_type": self.actor_type,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "capabilities": self.capabilities,
            "action_budget": self.action_budget,
        }


class _LegacyAgentPackSource(_ClosedResolverModel):
    """Strict view preserving the legacy manifest-hash preimage exactly."""

    schema_version: Literal["agent-pack-manifest.v1"]
    agent_pack_id: str = Field(min_length=1, max_length=160)
    status: Literal["active"]
    seed: int
    profiles: tuple[_LegacyAgentProfileSource, ...] = Field(min_length=1)
    manifest_hash: Digest
    created_at: Literal["2000-01-01T00:00:00.000Z"]

    @model_validator(mode="after")
    def validate_legacy_manifest(self) -> Self:
        if type(self.seed) is not int:
            raise ValueError("legacy Agent Pack seed must be a strict integer")
        profile_ids = tuple(profile.agent_id for profile in self.profiles)
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("legacy Agent Pack profile IDs must be unique")
        expected_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "seed": self.seed,
                "profiles": [profile.model_dump(mode="json") for profile in self.profiles],
            }
        )
        if self.manifest_hash != expected_hash:
            raise ValueError("legacy manifest_hash mismatch")
        if self.agent_pack_id != _agent_pack_id_from_legacy_hash(self.manifest_hash):
            raise ValueError("legacy Agent Pack ID must bind manifest_hash")
        return self


def parse_resolver_artifact_ref(value: object) -> ResolverArtifactReference:
    """Parse exactly the six-member resolver variant; reject union mixing."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("resolver artifact ref must be a six-member tuple/list")
    if len(value) != 6:
        raise ValueError("resolver artifact ref must contain exactly six members")
    if value[0] != "resolver":
        raise ValueError("resolver artifact ref discriminator must be resolver")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("resolver artifact ref members must be strings")
    return ResolverArtifactReference.model_validate(
        {
            "discriminator": value[0],
            "artifact_id": value[1],
            "artifact_sha256": value[2],
            "content_hash": value[3],
            "resolver_schema": value[4],
            "attempt": value[5],
        },
        strict=True,
    )


def resolver_artifact_ref_tuple(
    reference: ResolverArtifactReference,
) -> ResolverArtifactRefTuple:
    """Return the canonical ordered tuple committed by a checkpoint root."""

    return reference.as_tuple()


def _source_dump(value: BaseModel | Mapping[str, object]) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    return value


def parse_agent_pack_resolver_payload(value: object) -> AgentPackResolverPayload:
    """Validate a complete stored Agent Pack resolver payload fail-closed."""

    return AgentPackResolverPayload.model_validate(value, strict=True)


def agent_pack_resolver_payload_hash(
    payload: AgentPackResolverPayload,
) -> str:
    """Return ``H(complete_agent_pack)`` without self-including a hash field."""

    return stable_hash(payload.model_dump(mode="json"))


def build_agent_pack_resolver_payload(
    manifest: AgentPackManifest | Mapping[str, object],
) -> AgentPackResolverPayload:
    """Verify a legacy manifest, then canonicalize its complete V2 payload."""

    source = _LegacyAgentPackSource.model_validate(_source_dump(manifest), strict=True)
    profiles = tuple(
        AgentPackResolverProfile(
            agent_id=profile.agent_id,
            actor_type=profile.actor_type,
            country_code=profile.country_code,
            country_name=profile.country_name,
            capabilities=tuple(sorted(profile.capabilities, key=_utf8_sort_key)),
            action_budget=profile.action_budget,
            profile_hash=profile.profile_hash,
        )
        for profile in sorted(source.profiles, key=lambda item: _utf8_sort_key(item.agent_id))
    )
    return AgentPackResolverPayload(
        schema_version=AGENT_PACK_RESOLVER_PAYLOAD_SCHEMA,
        agent_pack_id=source.agent_pack_id,
        status="active",
        seed=source.seed,
        profiles=profiles,
        legacy_manifest_hash=source.manifest_hash,
        created_at=RESOLVER_CREATED_AT,
    )


def verify_agent_pack_resolver_payload(
    value: object,
    *,
    expected_agent_pack_hash: str,
    expected_agent_pack_id: str | None = None,
    expected_seed: int | None = None,
    expected_legacy_manifest_hash: str | None = None,
) -> AgentPackResolverPayload:
    """Verify the complete payload and its externally bound V2 authority hash."""

    payload = parse_agent_pack_resolver_payload(value)
    if agent_pack_resolver_payload_hash(payload) != expected_agent_pack_hash:
        raise ValueError("Agent Pack resolver payload hash mismatch")
    if expected_agent_pack_id is not None and payload.agent_pack_id != expected_agent_pack_id:
        raise ValueError("Agent Pack resolver payload ID mismatch")
    if expected_seed is not None and payload.seed != expected_seed:
        raise ValueError("Agent Pack resolver payload seed mismatch")
    if expected_legacy_manifest_hash is not None and payload.legacy_manifest_hash != expected_legacy_manifest_hash:
        raise ValueError("Agent Pack resolver legacy manifest hash mismatch")
    return payload


def parse_constraint_context_resolver_payload(
    value: object,
) -> ConstraintContextResolverPayload:
    """Validate one complete stored constraint-context resolver payload."""

    return ConstraintContextResolverPayload.model_validate(value, strict=True)


def constraint_context_resolver_payload_hash(
    payload: ConstraintContextResolverPayload,
) -> str:
    """Hash the exact ADR-0007 context wrapper preimage."""

    dumped = payload.model_dump(mode="json")
    context = {key: value for key, value in dumped.items() if key != "schema_version"}
    return stable_hash(
        {
            "schema_version": CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA,
            "context": context,
        }
    )


def _require_context_matches_agent_pack(
    context: ConstraintContextResolverPayload,
    agent_pack: AgentPackResolverPayload,
) -> None:
    expected_capabilities = tuple((profile.agent_id, profile.capabilities) for profile in agent_pack.profiles)
    expected_budgets = tuple((profile.agent_id, profile.action_budget) for profile in agent_pack.profiles)
    if context.actor_capabilities != expected_capabilities:
        raise ValueError("constraint-context capabilities drift from the Agent Pack")
    if context.action_budgets != expected_budgets:
        raise ValueError("constraint-context budgets drift from the Agent Pack")


def build_constraint_context_resolver_payload(
    context: AgentConstraintContext | Mapping[str, object],
    *,
    agent_pack: AgentPackResolverPayload,
) -> ConstraintContextResolverPayload:
    """Canonicalize a legacy context and bind it to the complete Agent Pack."""

    raw = _source_dump(context)
    if not isinstance(raw, Mapping):
        raise ValueError("constraint-context source must be an object")
    expected_keys = {
        "schema_version",
        "actor_capabilities",
        "action_budgets",
        "known_entities",
        "known_evidence_refs",
        "source_label",
    }
    if set(raw) != expected_keys:
        raise ValueError("constraint-context source must contain exactly its closed fields")
    if raw["schema_version"] != CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA:
        raise ValueError("unknown constraint-context schema version")
    capabilities = raw["actor_capabilities"]
    budgets = raw["action_budgets"]
    known_entities = raw["known_entities"]
    known_evidence_refs = raw["known_evidence_refs"]
    source_label = raw["source_label"]
    if not isinstance(capabilities, Mapping) or not isinstance(budgets, Mapping):
        raise ValueError("constraint-context capability and budget maps must be objects")
    if not isinstance(known_entities, (list, tuple)) or not isinstance(known_evidence_refs, (list, tuple)):
        raise ValueError("constraint-context known-value fields must be arrays")
    if not isinstance(source_label, str):
        raise ValueError("constraint-context source_label must be a string")
    if any(not isinstance(key, str) for key in capabilities) or any(not isinstance(key, str) for key in budgets):
        raise ValueError("constraint-context actor IDs must be strings")
    if any(not isinstance(value, (list, tuple)) for value in capabilities.values()):
        raise ValueError("constraint-context capabilities must be arrays")
    if any(
        not isinstance(action_type, str) or action_type not in ACTION_TYPES
        for action_types in capabilities.values()
        for action_type in action_types
    ):
        raise ValueError("constraint-context capabilities must be recognized ActionType strings")
    if any(not isinstance(value, str) for value in known_entities) or any(
        not isinstance(value, str) for value in known_evidence_refs
    ):
        raise ValueError("constraint-context known values must be strings")
    if len(set(known_entities)) != len(known_entities) or len(set(known_evidence_refs)) != len(known_evidence_refs):
        raise ValueError("constraint-context known values must be unique")
    actor_capabilities = tuple(
        (
            agent_id,
            tuple(sorted(action_types, key=_utf8_sort_key)),
        )
        for agent_id, action_types in sorted(capabilities.items(), key=lambda item: _utf8_sort_key(item[0]))
    )
    if any(len(set(action_types)) != len(action_types) for action_types in capabilities.values()):
        raise ValueError("constraint-context capabilities must be unique per actor")
    action_budgets = tuple(
        (agent_id, budget) for agent_id, budget in sorted(budgets.items(), key=lambda item: _utf8_sort_key(item[0]))
    )
    payload = ConstraintContextResolverPayload(
        schema_version=CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA,
        actor_capabilities=actor_capabilities,
        action_budgets=action_budgets,
        known_entities=tuple(sorted(known_entities, key=_utf8_sort_key)),
        known_evidence_refs=tuple(sorted(known_evidence_refs, key=_utf8_sort_key)),
        source_label=source_label,
    )
    _require_context_matches_agent_pack(payload, agent_pack)
    return payload


def verify_constraint_context_resolver_payload(
    value: object,
    *,
    expected_constraint_context_hash: str,
    agent_pack: AgentPackResolverPayload,
) -> ConstraintContextResolverPayload:
    """Verify the context hash and its exact Agent Pack capability envelope."""

    payload = parse_constraint_context_resolver_payload(value)
    if constraint_context_resolver_payload_hash(payload) != expected_constraint_context_hash:
        raise ValueError("constraint-context resolver payload hash mismatch")
    _require_context_matches_agent_pack(payload, agent_pack)
    return payload


def parse_deterministic_run_resolver_output(
    value: object,
) -> DeterministicRunResolverOutput:
    """Validate a complete resolver completed-step output."""

    return DeterministicRunResolverOutput.model_validate(value, strict=True)


def deterministic_run_resolver_output_hash(
    output: DeterministicRunResolverOutput,
) -> str:
    """Hash the complete step output, including both ordered references."""

    return stable_hash(output.model_dump(mode="json"))


def extract_resolver_artifact_refs(
    output: DeterministicRunResolverOutput,
) -> tuple[ResolverArtifactReference, ResolverArtifactReference]:
    """Return the canonical Agent Pack then constraint-context references."""

    return (
        parse_resolver_artifact_ref(output.artifact_refs[0]),
        parse_resolver_artifact_ref(output.artifact_refs[1]),
    )


def build_deterministic_run_resolver_output(
    *,
    run_id: str,
    attempt: str,
    agent_pack_resolver_version: str,
    constraint_context_resolver_version: str,
    effective_seed: int,
    baseline_result_hash: str,
    scenario_hash: str,
    rule_pack_hash: str,
    agent_pack: AgentPackResolverPayload,
    constraint_context: ConstraintContextResolverPayload,
    agent_pack_artifact_ref: ResolverArtifactReference,
    constraint_context_artifact_ref: ResolverArtifactReference,
) -> DeterministicRunResolverOutput:
    """Build the only valid Agent-capable deterministic-step resolver output."""

    if type(effective_seed) is not int or effective_seed != agent_pack.seed:
        raise ValueError("effective_seed must equal the resolved Agent Pack seed")
    _require_context_matches_agent_pack(constraint_context, agent_pack)
    return DeterministicRunResolverOutput.model_validate(
        {
            "schema_version": DETERMINISTIC_RUN_RESOLVER_OUTPUT_SCHEMA,
            "run_id": run_id,
            "attempt": attempt,
            "agent_pack_resolver_version": agent_pack_resolver_version,
            "constraint_context_resolver_version": constraint_context_resolver_version,
            "effective_seed": effective_seed,
            "baseline_result_hash": baseline_result_hash,
            "scenario_hash": scenario_hash,
            "rule_pack_hash": rule_pack_hash,
            "agent_pack_id": agent_pack.agent_pack_id,
            "agent_pack_hash": agent_pack_resolver_payload_hash(agent_pack),
            "constraint_context_hash": constraint_context_resolver_payload_hash(constraint_context),
            "artifact_refs": (
                agent_pack_artifact_ref.as_tuple(),
                constraint_context_artifact_ref.as_tuple(),
            ),
        },
        strict=True,
    )


def verify_deterministic_run_resolver_output(
    value: object,
    *,
    run_id: str,
    attempt: str,
    agent_pack_resolver_version: str,
    constraint_context_resolver_version: str,
    effective_seed: int,
    baseline_result_hash: str,
    scenario_hash: str,
    rule_pack_hash: str,
    agent_pack: AgentPackResolverPayload,
    constraint_context: ConstraintContextResolverPayload,
    agent_pack_artifact_ref: ResolverArtifactReference,
    constraint_context_artifact_ref: ResolverArtifactReference,
) -> DeterministicRunResolverOutput:
    """Compare stored output with fully regenerated pinned resolver bindings."""

    actual = parse_deterministic_run_resolver_output(value)
    expected = build_deterministic_run_resolver_output(
        run_id=run_id,
        attempt=attempt,
        agent_pack_resolver_version=agent_pack_resolver_version,
        constraint_context_resolver_version=constraint_context_resolver_version,
        effective_seed=effective_seed,
        baseline_result_hash=baseline_result_hash,
        scenario_hash=scenario_hash,
        rule_pack_hash=rule_pack_hash,
        agent_pack=agent_pack,
        constraint_context=constraint_context,
        agent_pack_artifact_ref=agent_pack_artifact_ref,
        constraint_context_artifact_ref=constraint_context_artifact_ref,
    )
    if actual != expected:
        raise ValueError("deterministic-run resolver output field drift")
    return actual
