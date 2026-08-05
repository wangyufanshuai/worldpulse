"""Closed resolver lineage contracts required by ADR-0007.

This module deliberately models the checkpoint reference union only.  The
complete Agent Pack and constraint context payloads remain resolver outputs;
they are not inferred or reconstructed from a caller-provided reference.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


SHA256_PATTERN = r"^[0-9a-f]{64}$"
Digest: TypeAlias = Annotated[str, Field(pattern=SHA256_PATTERN)]
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


class ResolverArtifactReference(BaseModel):
    """One closed ``artifact_refs`` resolver tuple from ADR-0007."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    discriminator: Literal["resolver"] = "resolver"
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
