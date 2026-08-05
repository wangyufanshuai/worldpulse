from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.simulation_kernel.resolver_contracts import (
    ResolverArtifactReference,
    parse_resolver_artifact_ref,
    resolver_artifact_ref_tuple,
)


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
        ["resolver", "artifact-1", "a" * 64, "b" * 64, "agent-pack-resolver-output.v1", ""],
    ],
)
def test_resolver_reference_rejects_malformed_or_unknown_members(value: list[str]) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_resolver_artifact_ref(value)


def test_resolver_reference_is_frozen_and_extra_fields_are_forbidden() -> None:
    reference = ResolverArtifactReference.model_validate(
        {
            "artifact_id": "artifact-1",
            "artifact_sha256": "a" * 64,
            "content_hash": "b" * 64,
            "resolver_schema": "agent-pack-resolver-output.v1",
            "attempt": "attempt-2",
        },
        strict=True,
    )
    with pytest.raises(ValidationError):
        ResolverArtifactReference.model_validate(
            {**reference.model_dump(), "unexpected": True}, strict=True
        )
    with pytest.raises(ValidationError):
        reference.artifact_id = "mutated"  # type: ignore[misc]
