from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.services.negotiation.agent_pack import build_agent_pack
from app.services.simulation_kernel.resolver_contracts import (
    AGENT_PACK_RESOLVER_PAYLOAD_SCHEMA,
    AGENT_PACK_RESOLVER_VERSION,
    CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA,
    CONSTRAINT_CONTEXT_RESOLVER_VERSION,
    DETERMINISTIC_RUN_RESOLVER_OUTPUT_SCHEMA,
    RESOLVER_CREATED_AT,
    AgentPackResolverPayload,
    AgentPackResolverProfile,
    ConstraintContextResolverPayload,
    DeterministicRunResolverOutput,
    ResolverArtifactReference,
    agent_pack_resolver_payload_hash,
    build_agent_pack_resolver_payload,
    build_constraint_context_resolver_payload,
    build_deterministic_run_resolver_output,
    constraint_context_resolver_payload_hash,
    deterministic_run_resolver_output_hash,
    extract_resolver_artifact_refs,
    parse_agent_pack_resolver_payload,
    parse_constraint_context_resolver_payload,
    parse_deterministic_run_resolver_output,
    parse_resolver_artifact_ref,
    resolver_artifact_ref_tuple,
    verify_agent_pack_resolver_payload,
    verify_constraint_context_resolver_payload,
    verify_deterministic_run_resolver_output,
)
from app.services.war_room_engine import run_war_room


Mutation = Callable[[dict[str, Any]], None]


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _replace_output_hash_binding(
    value: dict[str, Any],
    *,
    field: str,
    ref_index: int,
    digest: str,
) -> None:
    value[field] = digest
    value["artifact_refs"][ref_index][3] = digest


def _replace_output_attempt(value: dict[str, Any], attempt: str) -> None:
    value["attempt"] = attempt
    for reference in value["artifact_refs"]:
        reference[5] = attempt


def _legacy_profile(
    *,
    agent_id: str,
    actor_type: str,
    country_code: str,
    country_name: str,
    capabilities: list[str],
) -> dict[str, Any]:
    core = {
        "agent_id": agent_id,
        "actor_type": actor_type,
        "country_code": country_code,
        "country_name": country_name,
        "capabilities": capabilities,
        "action_budget": 6,
    }
    return {**core, "profile_hash": _canonical_hash(core)}


def _legacy_manifest() -> dict[str, Any]:
    profiles = [
        _legacy_profile(
            agent_id="agent:\u4e2d",
            actor_type="country_policy",
            country_code="CN",
            country_name="China",
            capabilities=["trade_reroute_request", "sanction_proposal"],
        ),
        _legacy_profile(
            agent_id="agent:\u00e9",
            actor_type="diplomacy",
            country_code="FR",
            country_name="France",
            capabilities=["humanitarian_offer", "diplomatic_signal"],
        ),
    ]
    manifest_core = {
        "schema_version": "agent-pack-manifest.v1",
        "seed": 42,
        "profiles": profiles,
    }
    manifest_hash = _canonical_hash(manifest_core)
    return {
        **manifest_core,
        "agent_pack_id": f"agent_pack_{manifest_hash[:20]}",
        "status": "active",
        "manifest_hash": manifest_hash,
        "created_at": RESOLVER_CREATED_AT,
    }


def _agent_pack() -> AgentPackResolverPayload:
    return build_agent_pack_resolver_payload(_legacy_manifest())


def _war_room_result() -> WarRoomRun:
    return run_war_room(WarRoomScenarioRequest(scenario_key="strait_blockade_30d", seed=42))


def _constraint_context(
    agent_pack: AgentPackResolverPayload | None = None,
) -> ConstraintContextResolverPayload:
    pack = agent_pack or _agent_pack()
    profiles = list(reversed(pack.profiles))
    source = {
        "schema_version": CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA,
        "actor_capabilities": {profile.agent_id: list(reversed(profile.capabilities)) for profile in profiles},
        "action_budgets": {profile.agent_id: profile.action_budget for profile in profiles},
        "known_entities": ["entity:\u4e2d", "entity:a", "entity:\u00e9"],
        "known_evidence_refs": ["evidence:\u4e2d", "evidence:a"],
        "source_label": "resolver fixture",
    }
    return build_constraint_context_resolver_payload(source, agent_pack=pack)


def _reference(
    *,
    schema: str = "agent-pack-resolver-output.v1",
    artifact_id: str = "agent-artifact",
    content_hash: str = "b" * 64,
    attempt: str = "attempt-2",
) -> ResolverArtifactReference:
    return parse_resolver_artifact_ref(["resolver", artifact_id, "a" * 64, content_hash, schema, attempt])


def _output() -> tuple[
    DeterministicRunResolverOutput,
    AgentPackResolverPayload,
    ConstraintContextResolverPayload,
    ResolverArtifactReference,
    ResolverArtifactReference,
]:
    pack = _agent_pack()
    context = _constraint_context(pack)
    agent_ref = _reference(content_hash=agent_pack_resolver_payload_hash(pack))
    context_ref = _reference(
        schema="constraint-context-resolver-output.v1",
        artifact_id="context-artifact",
        content_hash=constraint_context_resolver_payload_hash(context),
    )
    output = build_deterministic_run_resolver_output(
        run_id="run-1",
        attempt="attempt-2",
        agent_pack_resolver_version=AGENT_PACK_RESOLVER_VERSION,
        constraint_context_resolver_version=CONSTRAINT_CONTEXT_RESOLVER_VERSION,
        effective_seed=42,
        baseline_result_hash="1" * 64,
        scenario_hash="2" * 64,
        rule_pack_hash="3" * 64,
        agent_pack=pack,
        constraint_context=context,
        agent_pack_artifact_ref=agent_ref,
        constraint_context_artifact_ref=context_ref,
    )
    return output, pack, context, agent_ref, context_ref


def _value(schema: str = "agent-pack-resolver-output.v1") -> list[str]:
    return ["resolver", "artifact-1", "a" * 64, "b" * 64, schema, "attempt-2"]


@pytest.mark.parametrize(
    "schema",
    ["agent-pack-resolver-output.v1", "constraint-context-resolver-output.v1"],
)
def test_resolver_reference_round_trips_exact_closed_tuple(schema: str) -> None:
    reference = parse_resolver_artifact_ref(_value(schema))

    assert resolver_artifact_ref_tuple(reference) == tuple(_value(schema))


def test_resolver_reference_rejects_proof_discriminator() -> None:
    with pytest.raises(ValueError, match="discriminator"):
        parse_resolver_artifact_ref(["proof", *_value()[1:]])


@pytest.mark.parametrize(
    "value",
    [
        _value()[:-1],
        [*_value(), "unexpected"],
        _value()[:2] + ["A" * 64, "b" * 64, "agent-pack-resolver-output.v1", "attempt-2"],
        ["resolver", "artifact-1", "a" * 64, "b" * 64, "unknown.v1", "attempt-2"],
        [
            "resolver",
            "artifact-1",
            "a" * 64,
            "b" * 64,
            "agent-pack-resolver-output.v1",
            "",
        ],
    ],
)
def test_resolver_reference_rejects_malformed_or_unknown_members(
    value: list[str],
) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_resolver_artifact_ref(value)


def test_resolver_reference_is_closed_frozen_and_has_no_field_defaults() -> None:
    reference = ResolverArtifactReference.model_validate(
        {
            "discriminator": "resolver",
            "artifact_id": "artifact-1",
            "artifact_sha256": "a" * 64,
            "content_hash": "b" * 64,
            "resolver_schema": "agent-pack-resolver-output.v1",
            "attempt": "attempt-2",
        },
        strict=True,
    )
    assert all(field.is_required() for field in ResolverArtifactReference.model_fields.values())
    with pytest.raises(ValidationError):
        ResolverArtifactReference.model_validate(
            {key: value for key, value in reference.model_dump().items() if key != "discriminator"},
            strict=True,
        )
    with pytest.raises(ValidationError):
        ResolverArtifactReference.model_validate({**reference.model_dump(), "unexpected": True}, strict=True)
    with pytest.raises(ValidationError):
        reference.artifact_id = "mutated"  # type: ignore[misc]


def test_agent_pack_builder_emits_exact_ordered_closed_payload() -> None:
    payload = _agent_pack()
    dumped = payload.model_dump(mode="json")

    assert dumped == {
        "schema_version": AGENT_PACK_RESOLVER_PAYLOAD_SCHEMA,
        "agent_pack_id": _legacy_manifest()["agent_pack_id"],
        "status": "active",
        "seed": 42,
        "profiles": [
            {
                **_legacy_manifest()["profiles"][1],
                "capabilities": ["diplomatic_signal", "humanitarian_offer"],
            },
            {
                **_legacy_manifest()["profiles"][0],
                "capabilities": ["sanction_proposal", "trade_reroute_request"],
            },
        ],
        "legacy_manifest_hash": _legacy_manifest()["manifest_hash"],
        "created_at": RESOLVER_CREATED_AT,
    }
    assert "agent_pack_hash" not in dumped


def test_agent_pack_resolver_accepts_real_legacy_builder_output() -> None:
    legacy_pack = build_agent_pack(_war_room_result(), 42)

    payload = build_agent_pack_resolver_payload(legacy_pack)

    assert payload.agent_pack_id == legacy_pack.agent_pack_id
    assert payload.legacy_manifest_hash == legacy_pack.manifest_hash
    assert payload.seed == legacy_pack.seed
    assert {profile.agent_id for profile in payload.profiles} == {
        profile.agent_id for profile in legacy_pack.profiles
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("unexpected", True),
        lambda value: value.pop("profiles"),
        lambda value: value.__setitem__("agent_pack_id", "agent_pack_unbound"),
        lambda value: value.__setitem__("manifest_hash", "f" * 64),
        lambda value: value["profiles"][0].__setitem__("profile_hash", "e" * 64),
        lambda value: value.__setitem__("created_at", "2026-01-01T00:00:00.000Z"),
    ],
    ids=[
        "extra",
        "missing",
        "unbound-id",
        "manifest-hash-drift",
        "profile-hash-drift",
        "wall-clock-time",
    ],
)
def test_agent_pack_builder_rejects_invalid_legacy_source(mutation: Mutation) -> None:
    value = deepcopy(_legacy_manifest())
    mutation(value)

    with pytest.raises((ValueError, ValidationError)):
        build_agent_pack_resolver_payload(value)


def test_agent_pack_hash_is_over_the_complete_payload() -> None:
    payload = _agent_pack()
    expected = _canonical_hash(payload.model_dump(mode="json"))

    assert agent_pack_resolver_payload_hash(payload) == expected
    assert (
        verify_agent_pack_resolver_payload(
            payload.model_dump(mode="json"),
            expected_agent_pack_hash=expected,
            expected_agent_pack_id=payload.agent_pack_id,
            expected_seed=payload.seed,
            expected_legacy_manifest_hash=payload.legacy_manifest_hash,
        )
        == payload
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_agent_pack_resolver_payload(payload.model_dump(mode="json"), expected_agent_pack_hash="f" * 64)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_agent_pack_id": "agent_pack_unbound"}, "ID mismatch"),
        ({"expected_seed": 43}, "seed mismatch"),
        ({"expected_legacy_manifest_hash": "f" * 64}, "legacy manifest hash mismatch"),
    ],
    ids=["id", "seed", "legacy-hash"],
)
def test_agent_pack_verifier_rejects_pinned_binding_drift(
    override: dict[str, object],
    message: str,
) -> None:
    payload = _agent_pack()

    with pytest.raises(ValueError, match=message):
        verify_agent_pack_resolver_payload(
            payload.model_dump(mode="json"),
            expected_agent_pack_hash=agent_pack_resolver_payload_hash(payload),
            **override,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("unexpected", True),
        lambda value: value.pop("created_at"),
        lambda value: value.__setitem__("created_at", "2026-01-01T00:00:00.000Z"),
        lambda value: value.__setitem__("schema_version", "agent-pack-resolver-payload.v2"),
        lambda value: value.__setitem__("status", "retired"),
        lambda value: value.__setitem__("agent_pack_id", "agent_pack_unbound"),
        lambda value: value.__setitem__("seed", "42"),
        lambda value: value.__setitem__("seed", True),
        lambda value: value.__setitem__("profiles", list(reversed(value["profiles"]))),
        lambda value: value["profiles"].append(deepcopy(value["profiles"][0])),
        lambda value: value["profiles"][0].__setitem__(
            "capabilities", list(reversed(value["profiles"][0]["capabilities"]))
        ),
        lambda value: value["profiles"][0]["capabilities"].append(value["profiles"][0]["capabilities"][0]),
        lambda value: value["profiles"][0].__setitem__("action_budget", "6"),
        lambda value: value["profiles"][0].__setitem__("action_budget", True),
        lambda value: value["profiles"][0].__setitem__("unexpected", "closed"),
    ],
    ids=[
        "top-level-extra",
        "missing-fixed-time",
        "wall-clock-time",
        "unknown-schema",
        "inactive-status",
        "unbound-agent-pack-id",
        "quoted-seed",
        "boolean-seed",
        "profile-order",
        "duplicate-profile",
        "capability-order",
        "duplicate-capability",
        "quoted-budget",
        "boolean-budget",
        "nested-extra",
    ],
)
def test_agent_pack_payload_mutations_fail_closed(mutation: Mutation) -> None:
    value = deepcopy(_agent_pack().model_dump(mode="json"))
    mutation(value)

    with pytest.raises(ValidationError):
        parse_agent_pack_resolver_payload(value)


def test_agent_pack_models_are_frozen_and_have_no_field_defaults() -> None:
    payload = _agent_pack()

    assert all(field.is_required() for field in AgentPackResolverProfile.model_fields.values())
    assert all(field.is_required() for field in AgentPackResolverPayload.model_fields.values())
    with pytest.raises(ValidationError):
        payload.agent_pack_id = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        payload.profiles[0].agent_id = "mutated"  # type: ignore[misc]


def test_constraint_context_builder_emits_exact_utf8_ordered_tuple_maps() -> None:
    pack = _agent_pack()
    payload = _constraint_context(pack)

    assert payload.actor_capabilities == tuple((profile.agent_id, profile.capabilities) for profile in pack.profiles)
    assert payload.action_budgets == tuple((profile.agent_id, profile.action_budget) for profile in pack.profiles)
    assert payload.known_entities == ("entity:a", "entity:\u00e9", "entity:\u4e2d")
    assert payload.known_evidence_refs == ("evidence:a", "evidence:\u4e2d")


def test_constraint_context_hash_uses_exact_schema_context_wrapper() -> None:
    payload = _constraint_context()
    dumped = payload.model_dump(mode="json")
    context = {key: value for key, value in dumped.items() if key != "schema_version"}
    expected = _canonical_hash({"schema_version": CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA, "context": context})

    assert constraint_context_resolver_payload_hash(payload) == expected
    assert expected != _canonical_hash(dumped)
    assert "constraint_context_hash" not in dumped
    assert (
        verify_constraint_context_resolver_payload(
            dumped,
            expected_constraint_context_hash=expected,
            agent_pack=_agent_pack(),
        )
        == payload
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        verify_constraint_context_resolver_payload(
            dumped,
            expected_constraint_context_hash="f" * 64,
            agent_pack=_agent_pack(),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("unexpected", True),
        lambda value: value.pop("source_label"),
        lambda value: value.__setitem__("schema_version", "agent-constraint-context.v2"),
        lambda value: value["actor_capabilities"].__setitem__(
            next(iter(value["actor_capabilities"])),
            ["intelligence_request"],
        ),
        lambda value: value["action_budgets"].__setitem__(
            next(iter(value["action_budgets"])),
            5,
        ),
    ],
    ids=["extra", "missing", "version", "capability-drift", "budget-drift"],
)
def test_constraint_context_builder_rejects_invalid_source_or_pack_drift(mutation: Mutation) -> None:
    pack = _agent_pack()
    source = {
        "schema_version": CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA,
        "actor_capabilities": {profile.agent_id: list(profile.capabilities) for profile in pack.profiles},
        "action_budgets": {profile.agent_id: profile.action_budget for profile in pack.profiles},
        "known_entities": ["entity:a"],
        "known_evidence_refs": ["evidence:a"],
        "source_label": "resolver fixture",
    }
    mutation(source)

    with pytest.raises((ValueError, ValidationError)):
        build_constraint_context_resolver_payload(source, agent_pack=pack)


@pytest.mark.parametrize(
    "malformed_capability",
    [1, {"action_type": "diplomatic_signal"}, "unknown_action"],
    ids=["integer", "object", "unknown-string"],
)
def test_constraint_context_builder_rejects_malformed_capability_elements(
    malformed_capability: object,
) -> None:
    pack = _agent_pack()
    source = {
        "schema_version": CONSTRAINT_CONTEXT_PAYLOAD_SCHEMA,
        "actor_capabilities": {profile.agent_id: list(profile.capabilities) for profile in pack.profiles},
        "action_budgets": {profile.agent_id: profile.action_budget for profile in pack.profiles},
        "known_entities": ["entity:a"],
        "known_evidence_refs": ["evidence:a"],
        "source_label": "resolver fixture",
    }
    first_agent_id = next(iter(source["actor_capabilities"]))
    source["actor_capabilities"][first_agent_id].append(malformed_capability)

    with pytest.raises(ValueError, match="recognized ActionType strings"):
        build_constraint_context_resolver_payload(source, agent_pack=pack)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("unexpected", True),
        lambda value: value.pop("source_label"),
        lambda value: value.__setitem__("schema_version", "agent-constraint-context.v2"),
        lambda value: value["actor_capabilities"].reverse(),
        lambda value: value["actor_capabilities"].append(deepcopy(value["actor_capabilities"][0])),
        lambda value: value["action_budgets"].reverse(),
        lambda value: value["action_budgets"].append(deepcopy(value["action_budgets"][0])),
        lambda value: value["action_budgets"][0].__setitem__(0, "different-agent"),
        lambda value: value["actor_capabilities"][0][1].reverse(),
        lambda value: value["actor_capabilities"][0][1].append(value["actor_capabilities"][0][1][0]),
        lambda value: value.__setitem__("known_entities", list(reversed(value["known_entities"]))),
        lambda value: value["known_entities"].append(value["known_entities"][0]),
        lambda value: value["known_evidence_refs"].reverse(),
        lambda value: value["known_evidence_refs"].append(value["known_evidence_refs"][0]),
        lambda value: value["action_budgets"][0].__setitem__(1, "6"),
        lambda value: value["action_budgets"][0].__setitem__(1, True),
    ],
    ids=[
        "extra",
        "missing",
        "unknown-schema",
        "capability-map-order",
        "duplicate-capability-actor",
        "budget-map-order",
        "duplicate-budget-actor",
        "actor-id-mismatch",
        "action-order",
        "duplicate-action",
        "entity-order",
        "duplicate-entity",
        "evidence-order",
        "duplicate-evidence",
        "quoted-budget",
        "boolean-budget",
    ],
)
def test_constraint_context_payload_mutations_fail_closed(mutation: Mutation) -> None:
    value = deepcopy(_constraint_context().model_dump(mode="json"))
    mutation(value)

    with pytest.raises(ValidationError):
        parse_constraint_context_resolver_payload(value)


def test_constraint_context_verification_rejects_agent_pack_substitution() -> None:
    pack = _agent_pack()
    value = _constraint_context(pack).model_dump(mode="json")
    value["actor_capabilities"][0][1] = ["intelligence_request"]
    substituted = parse_constraint_context_resolver_payload(value)

    with pytest.raises(ValueError, match="drift from the Agent Pack"):
        verify_constraint_context_resolver_payload(
            value,
            expected_constraint_context_hash=constraint_context_resolver_payload_hash(substituted),
            agent_pack=pack,
        )


def test_constraint_context_model_is_frozen_and_has_no_field_defaults() -> None:
    payload = _constraint_context()

    assert all(field.is_required() for field in ConstraintContextResolverPayload.model_fields.values())
    with pytest.raises(ValidationError):
        payload.source_label = "mutated"  # type: ignore[misc]


def test_completed_step_output_binds_exact_two_ordered_refs_and_hashes() -> None:
    output, pack, context, agent_ref, context_ref = _output()

    assert output.schema_version == DETERMINISTIC_RUN_RESOLVER_OUTPUT_SCHEMA
    assert output.agent_pack_id == pack.agent_pack_id
    assert output.agent_pack_hash == agent_pack_resolver_payload_hash(pack)
    assert output.constraint_context_hash == constraint_context_resolver_payload_hash(context)
    assert output.artifact_refs == (agent_ref.as_tuple(), context_ref.as_tuple())
    assert tuple(ref.resolver_schema for ref in extract_resolver_artifact_refs(output)) == (
        "agent-pack-resolver-output.v1",
        "constraint-context-resolver-output.v1",
    )
    assert deterministic_run_resolver_output_hash(output) == _canonical_hash(output.model_dump(mode="json"))
    assert (
        verify_deterministic_run_resolver_output(
            output.model_dump(mode="json"),
            run_id="run-1",
            attempt="attempt-2",
            agent_pack_resolver_version=AGENT_PACK_RESOLVER_VERSION,
            constraint_context_resolver_version=CONSTRAINT_CONTEXT_RESOLVER_VERSION,
            effective_seed=42,
            baseline_result_hash="1" * 64,
            scenario_hash="2" * 64,
            rule_pack_hash="3" * 64,
            agent_pack=pack,
            constraint_context=context,
            agent_pack_artifact_ref=agent_ref,
            constraint_context_artifact_ref=context_ref,
        )
        == output
    )


def test_completed_step_builder_is_deterministic_and_rejects_seed_drift() -> None:
    output, pack, context, agent_ref, context_ref = _output()
    rebuilt = build_deterministic_run_resolver_output(
        run_id="run-1",
        attempt="attempt-2",
        agent_pack_resolver_version=AGENT_PACK_RESOLVER_VERSION,
        constraint_context_resolver_version=CONSTRAINT_CONTEXT_RESOLVER_VERSION,
        effective_seed=42,
        baseline_result_hash="1" * 64,
        scenario_hash="2" * 64,
        rule_pack_hash="3" * 64,
        agent_pack=pack,
        constraint_context=context,
        agent_pack_artifact_ref=agent_ref,
        constraint_context_artifact_ref=context_ref,
    )

    assert rebuilt == output
    assert deterministic_run_resolver_output_hash(rebuilt) == deterministic_run_resolver_output_hash(output)

    with pytest.raises(ValueError, match="Agent Pack seed"):
        build_deterministic_run_resolver_output(
            run_id="run-1",
            attempt="attempt-2",
            agent_pack_resolver_version=AGENT_PACK_RESOLVER_VERSION,
            constraint_context_resolver_version=CONSTRAINT_CONTEXT_RESOLVER_VERSION,
            effective_seed=43,
            baseline_result_hash="1" * 64,
            scenario_hash="2" * 64,
            rule_pack_hash="3" * 64,
            agent_pack=pack,
            constraint_context=context,
            agent_pack_artifact_ref=agent_ref,
            constraint_context_artifact_ref=context_ref,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("unexpected", True),
        lambda value: value.pop("rule_pack_hash"),
        lambda value: value.__setitem__("schema_version", "deterministic-run-resolver-output.v2"),
        lambda value: value.__setitem__("agent_pack_resolver_version", "agent-pack-resolver.v2"),
        lambda value: value.__setitem__("constraint_context_resolver_version", "constraint-context-resolver.v2"),
        lambda value: value.__setitem__("effective_seed", "42"),
        lambda value: value.__setitem__("effective_seed", True),
        lambda value: value.__setitem__("baseline_result_hash", "A" * 64),
        lambda value: value["artifact_refs"].reverse(),
        lambda value: value["artifact_refs"].pop(),
        lambda value: value["artifact_refs"].append(deepcopy(value["artifact_refs"][0])),
        lambda value: value["artifact_refs"].__setitem__(1, deepcopy(value["artifact_refs"][0])),
        lambda value: value["artifact_refs"][0].__setitem__(3, "f" * 64),
        lambda value: value["artifact_refs"][1].__setitem__(3, "e" * 64),
        lambda value: value["artifact_refs"][0].__setitem__(5, "attempt-other"),
        lambda value: value.__setitem__("attempt", "attempt-other"),
    ],
    ids=[
        "extra",
        "missing",
        "unknown-output-schema",
        "unknown-agent-resolver",
        "unknown-context-resolver",
        "quoted-seed",
        "boolean-seed",
        "noncanonical-hash",
        "ref-order",
        "missing-ref",
        "surplus-ref",
        "duplicate-ref",
        "agent-content-substitution",
        "context-content-substitution",
        "cross-attempt-ref",
        "cross-attempt-output",
    ],
)
def test_completed_step_output_mutations_fail_closed(mutation: Mutation) -> None:
    output, *_ = _output()
    value = deepcopy(output.model_dump(mode="json"))
    mutation(value)

    with pytest.raises(ValidationError):
        parse_deterministic_run_resolver_output(value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("run_id", "run-other"),
        lambda value: value.__setitem__("effective_seed", 43),
        lambda value: value.__setitem__("baseline_result_hash", "8" * 64),
        lambda value: value.__setitem__("scenario_hash", "9" * 64),
        lambda value: value.__setitem__("rule_pack_hash", "0" * 64),
        lambda value: value.__setitem__("agent_pack_id", "agent_pack_00000000000000000000"),
        lambda value: _replace_output_hash_binding(
            value,
            field="agent_pack_hash",
            ref_index=0,
            digest="6" * 64,
        ),
        lambda value: _replace_output_hash_binding(
            value,
            field="constraint_context_hash",
            ref_index=1,
            digest="7" * 64,
        ),
        lambda value: value["artifact_refs"][0].__setitem__(1, "agent-artifact-other"),
        lambda value: value["artifact_refs"][0].__setitem__(2, "c" * 64),
        lambda value: value["artifact_refs"][1].__setitem__(1, "context-artifact-other"),
        lambda value: value["artifact_refs"][1].__setitem__(2, "d" * 64),
        lambda value: _replace_output_attempt(value, "attempt-other"),
    ],
    ids=[
        "run",
        "seed",
        "baseline-hash",
        "scenario-hash",
        "rule-pack-hash",
        "agent-pack-id",
        "agent-pack-hash-and-ref",
        "context-hash-and-ref",
        "agent-ref-id",
        "agent-ref-sha",
        "context-ref-id",
        "context-ref-sha",
        "attempt-and-refs",
    ],
)
def test_completed_step_verification_rejects_validly_shaped_field_drift(mutation: Mutation) -> None:
    output, pack, context, agent_ref, context_ref = _output()
    value = output.model_dump(mode="json")
    mutation(value)

    with pytest.raises(ValueError, match="field drift"):
        verify_deterministic_run_resolver_output(
            value,
            run_id="run-1",
            attempt="attempt-2",
            agent_pack_resolver_version=AGENT_PACK_RESOLVER_VERSION,
            constraint_context_resolver_version=CONSTRAINT_CONTEXT_RESOLVER_VERSION,
            effective_seed=42,
            baseline_result_hash="1" * 64,
            scenario_hash="2" * 64,
            rule_pack_hash="3" * 64,
            agent_pack=pack,
            constraint_context=context,
            agent_pack_artifact_ref=agent_ref,
            constraint_context_artifact_ref=context_ref,
        )


def test_completed_step_model_is_frozen_and_has_no_field_defaults() -> None:
    output, *_ = _output()

    assert all(field.is_required() for field in DeterministicRunResolverOutput.model_fields.values())
    with pytest.raises(ValidationError):
        output.run_id = "mutated"  # type: ignore[misc]
