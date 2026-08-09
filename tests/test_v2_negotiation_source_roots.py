from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.run_lifecycle.source_roots import (
    ProofArtifactReference,
    RootArtifact,
    SourceRootError,
    _proof_source_identity,
    _validate_negotiation_proof_sequence,
)

from test_negotiation_proof_sources import (
    _cl_payload,
    _consistency_payload,
    _el_payload,
    _mb_payload,
    _nd_payload,
    _np_payload,
    _pa_payload,
)
from test_negotiation_round_proof_source import _round_payload
from test_replay_proof_sources import _nr_payload


def test_negotiation_source_root_identity_maps_every_closed_token():
    mb = _mb_payload()
    cases = (
        (
            "kp.negotiation-round.v1",
            _round_payload(),
            "negotiation_round",
            "negotiation-round.v2",
            "round_hash",
        ),
        (
            "kp.negotiation-proposal-batch.v1",
            _np_payload(),
            "negotiation_proposal_batch",
            "negotiation-proposal-batch.v1",
            "batch_hash",
        ),
        (
            "kp.negotiation-admission-consistency.v1",
            _consistency_payload(role="admission"),
            "consistency_audit",
            "consistency-audit.v3",
            "audit_hash",
        ),
        (
            "kp.commitment-ledger.v1",
            _cl_payload(),
            "commitment_ledger",
            "commitment-ledger.v2",
            "ledger_hash",
        ),
        (
            "kp.negotiation-eligibility.v1",
            _el_payload(_np_payload()),
            "negotiation_eligibility",
            "negotiation-eligibility.v1",
            "eligibility_hash",
        ),
        (
            "kp.negotiation-projection-consistency.v1",
            _consistency_payload(role="projection"),
            "consistency_audit",
            "consistency-audit.v3",
            "audit_hash",
        ),
        (
            "kp.final-consistency.v1",
            _consistency_payload(role="final"),
            "consistency_audit",
            "consistency-audit.v3",
            "audit_hash",
        ),
        (
            "kp.action-modifier-bundle.v1",
            mb,
            "deterministic_action_modifiers",
            "hybrid-modifier-bundle.v2",
            "bundle_hash",
        ),
        (
            "kp.narrative-diffusion.v1",
            _nd_payload(attempted=False),
            "narrative_diffusion",
            "narrative-diffusion.v2",
            "diffusion_evidence_hash",
        ),
        (
            "kp.projection-audit.v1",
            _pa_payload(mb),
            "negotiation_projection_audit",
            "negotiation-projection-audit.v2",
            "audit_hash",
        ),
        (
            "kp.negotiation-replay.v1",
            _nr_payload(),
            "negotiation_replay",
            "negotiation-replay.v2",
            "replay_hash",
        ),
    )

    for proof_schema, payload, artifact_type, schema_version, hash_field in cases:
        assert _proof_source_identity(proof_schema, payload) == (
            artifact_type,
            schema_version,
            payload[hash_field],
        )


def _matrix(projected_ticks: tuple[int, ...] = ()):
    coordinates = (
        tuple(("kp.negotiation-round.v1", tick) for tick in range(1, 7))
        + tuple(
            ("kp.negotiation-proposal-batch.v1", tick)
            for tick in range(1, 7)
        )
        + tuple(
            ("kp.negotiation-admission-consistency.v1", tick)
            for tick in range(1, 7)
        )
        + tuple(("kp.commitment-ledger.v1", tick) for tick in range(1, 7))
        + tuple(
            ("kp.negotiation-eligibility.v1", tick)
            for tick in range(1, 7)
        )
        + tuple(
            ("kp.negotiation-projection-consistency.v1", tick)
            for tick in projected_ticks
        )
        + (("kp.final-consistency.v1", None),)
        + tuple(
            ("kp.action-modifier-bundle.v1", tick)
            for tick in projected_ticks
        )
        + tuple(("kp.narrative-diffusion.v1", tick) for tick in range(1, 7))
        + tuple(("kp.projection-audit.v1", tick) for tick in projected_ticks)
        + (("kp.negotiation-replay.v1", None),)
    )
    references = tuple(
        ProofArtifactReference(
            discriminator="proof",
            artifact_id=f"artifact-{index}",
            artifact_sha256=f"{index + 1:064x}",
            content_hash=f"{index + 101:064x}",
            proof_schema=proof_schema,
            attempt="attempt-1",
        )
        for index, (proof_schema, _tick) in enumerate(coordinates)
    )
    artifacts = tuple(
        RootArtifact(
            artifact_id=reference.artifact_id,
            artifact_type="test",
            schema_version="test.v1",
            sha256=reference.artifact_sha256,
            attempt_id="attempt-1",
            supersedes_artifact_id=None,
            payload={"tick": tick, "session_id": "session-1"},
        )
        for reference, (_proof_schema, tick) in zip(
            references,
            coordinates,
            strict=True,
        )
    )
    return references, artifacts


@pytest.mark.parametrize("projected_ticks", [(), (2, 5), (1, 2, 3, 4, 5, 6)])
def test_negotiation_root_admits_only_the_conditional_canonical_matrix(
    projected_ticks,
):
    references, artifacts = _matrix(projected_ticks)

    _validate_negotiation_proof_sequence(references, artifacts)

    swapped = list(artifacts)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(SourceRootError, match="prefix"):
        _validate_negotiation_proof_sequence(references, tuple(swapped))


def test_negotiation_root_rejects_projection_set_or_session_drift():
    references, artifacts = _matrix((2, 5))
    missing_modifier = tuple(
        item
        for item in references
        if not (
            item.proof_schema == "kp.action-modifier-bundle.v1"
            and artifacts[references.index(item)].payload["tick"] == 5
        )
    )
    missing_artifacts = tuple(
        item
        for item in artifacts
        if not (
            item.payload["tick"] == 5
            and item.artifact_id
            == next(
                ref.artifact_id
                for ref in references
                if ref.proof_schema == "kp.action-modifier-bundle.v1"
                and artifacts[references.index(ref)].payload["tick"] == 5
            )
        )
    )
    with pytest.raises(SourceRootError, match="tail"):
        _validate_negotiation_proof_sequence(
            missing_modifier,
            missing_artifacts,
        )

    drifted = list(artifacts)
    drifted[0] = replace(
        drifted[0],
        payload={"tick": 1, "session_id": "other-session"},
    )
    with pytest.raises(SourceRootError, match="one session"):
        _validate_negotiation_proof_sequence(references, tuple(drifted))
