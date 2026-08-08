from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.consistency.hashing import stable_hash
from app.services.simulation_kernel import (
    ARClaims,
    FCClaims,
    Entity,
    KernelModeFinalizationError,
    KernelModeExecutionProof,
    KernelModeExecutionRecord,
    KernelModeExecutionRequest,
    KernelModeProofReference,
    KernelModeProofRelationship,
    ModifierReference,
    PAClaims,
    PBClaims,
    WorldState,
    empty_commitment_ledger_hash,
    finalize_execution,
    normalize_kernel_mode,
)
from app.services.simulation_kernel.mode_contracts import (
    ACClaims,
    CLClaims,
    ELClaims,
    HRClaims,
    MBClaims,
    NDClaims,
    NPClaims,
    NRClaims,
    PCClaims,
    RRClaims,
)
from app.services.simulation_kernel.war_room_projection import WarRoomProjection


def _projection():
    world_state = WorldState(
        run_id="mode-contract-run",
        seed=17,
        rule_pack_hash="a" * 64,
        entities={"country:USA": Entity(entity_id="country:USA", entity_type="country")},
    )
    return WarRoomProjection(
        source_run_hash="1" * 64,
        deterministic_source_hash="2" * 64,
        world_state_hash=world_state.content_hash(),
        world_state=world_state,
    )


def _consistency_fields(
    proposal_ids: tuple[str, ...],
    proposal_hashes: tuple[str, ...],
    accepted_ids: tuple[str, ...] = (),
    *,
    agent_context: bool,
) -> dict:
    accepted = set(accepted_ids)
    decisions = tuple(
        (
            proposal_id,
            proposal_hashes[index],
            "accepted" if proposal_id in accepted else "rejected",
            proposal_hashes[index],
            "worldpulse-consistency.v1.2",
            "accepted" if proposal_id in accepted else "rejected",
            None if proposal_id in accepted else "rejected-by-test",
            "not_projected" if proposal_id in accepted else "blocked",
            None,
        )
        for index, proposal_id in enumerate(proposal_ids)
    )
    return {
        "evaluator_version": "worldpulse-consistency.v0.8",
        "agent_pack_id": "agent-pack-test" if agent_context else None,
        "agent_pack_hash": "d" * 64 if agent_context else None,
        "constraint_context_hash": "e" * 64 if agent_context else None,
        "inner_audit_hash": "f" * 64,
        "decision_tuples": decisions,
    }
def _reference() -> KernelModeProofReference:
    claims = FCClaims(
        run_id="mode-contract-run",
        audit_hash="b" * 64,
        deterministic_result_hash="c" * 64,
        proposal_ids=(),
        proposal_hashes=(),
        accepted_proposal_ids=(),
        decision_count=0,
        **_consistency_fields((), (), agent_context=False),
    )
    claims_hash = stable_hash({"claims": claims.model_dump(mode="json"), "proof_schema": "kp.final-consistency.v1"})
    return KernelModeProofReference(
        proof_schema="kp.final-consistency.v1",
        artifact_type="consistency_audit",
        schema_version="consistency-audit.v3",
        artifact_id="artifact-final-consistency",
        run_id="mode-contract-run",
        session_id=None,
        attempt="attempt-1",
        ordinal=0,
        tick=None,
        artifact_sha256="d" * 64,
        content_hash="e" * 64,
        claims=claims,
        claims_hash=claims_hash,
        relationships=(),
    )


def test_mode_contracts_are_closed_and_deeply_immutable():
    reference = _reference()
    with pytest.raises(ValidationError, match="frozen"):
        reference.claims.proposal_ids += ("proposal-1",)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FCClaims(
            run_id="mode-contract-run",
            audit_hash="b" * 64,
            deterministic_result_hash="c" * 64,
            proposal_ids=(),
            proposal_hashes=(),
            accepted_proposal_ids=(),
            decision_count=0,
            **_consistency_fields((), (), agent_context=False),
            unexpected=True,
        )


def test_claims_hash_is_recomputed_and_arbitrary_digest_is_not_a_proof():
    payload = _reference().model_dump(mode="json")
    payload["claims_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="claims_hash mismatch"):
        KernelModeProofReference.model_validate(payload)
    with pytest.raises(ValidationError):
        KernelModeExecutionProof.model_validate({"proof_hash": "a" * 64, "references": ()})


def test_engine_mode_normalization_rejects_unknown_values():
    assert normalize_kernel_mode("hybrid_recorded") == "hybrid"
    with pytest.raises(ValueError, match="Unknown Kernel engine mode"):
        normalize_kernel_mode("offline")


def test_request_requires_projection_identity_basics():
    reference = _reference()
    request = _execution_request("deterministic", (reference,))
    assert request.baseline.world_state_hash == request.final.world_state_hash
    with pytest.raises(ValidationError, match="projection seed"):
        request.model_copy(update={"effective_seed": 18})


def _mode_reference(*, proof_schema: str, artifact_type: str, schema_version: str, artifact_id: str, claims, ordinal: int, relationships=(), tick=None, session_id=None):
    return KernelModeProofReference(
        proof_schema=proof_schema,
        artifact_type=artifact_type,
        schema_version=schema_version,
        artifact_id=artifact_id,
        run_id="mode-contract-run",
        session_id=session_id,
        attempt="attempt-1",
        ordinal=ordinal,
        tick=tick,
        artifact_sha256=(str(ordinal + 3) * 64)[:64],
        content_hash=(str(ordinal + 4) * 64)[:64],
        claims=claims,
        claims_hash=stable_hash({"claims": claims.model_dump(mode="json"), "proof_schema": proof_schema}),
        relationships=relationships,
    )


def _replace_mode_claims(reference: KernelModeProofReference, claims) -> KernelModeProofReference:
    return reference.model_copy(update={
        "claims": claims,
        "claims_hash": stable_hash({"claims": claims.model_dump(mode="json"), "proof_schema": reference.proof_schema}),
    })


def _execution_request(
    engine_mode: str,
    references: tuple[KernelModeProofReference, ...],
    *,
    baseline: WarRoomProjection | None = None,
    final: WarRoomProjection | None = None,
) -> KernelModeExecutionRequest:
    proof = KernelModeExecutionProof(
        schema_version="kernel-mode-execution-proof.v1",
        references=references,
        proof_hash=stable_hash(
            {"references": [reference.model_dump(mode="json") for reference in references], "schema_version": "kernel-mode-execution-proof.v1"}
        ),
    )
    agent_context = engine_mode != "deterministic"
    values = {
        "schema_version": "kernel-mode-execution-request.v1",
        "execution_contract_version": "kernel-mode-execution.v2",
        "organization_id": "organization-test",
        "project_id": "project-test",
        "lifecycle_job_id": "mode-contract-run",
        "run_id": "mode-contract-run",
        "session_id": "session-1" if engine_mode == "negotiation" else None,
        "attempt": "attempt-1",
        "engine_mode": engine_mode,
        "kernel_mode": normalize_kernel_mode(engine_mode),
        "effective_seed": 17,
        "rule_pack_id": "rule-pack-test",
        "rule_pack_hash": "a" * 64,
        "agent_pack_id": "agent-pack-test" if agent_context else None,
        "agent_pack_hash": "d" * 64 if agent_context else None,
        "constraint_context_hash": "e" * 64 if agent_context else None,
        "evaluator_version": "worldpulse-consistency.v0.8",
        "runtime_profile_hash": "8" * 64,
        "fencing_epoch_hash": "9" * 64,
        "baseline_projection": (baseline or _projection()).model_dump(mode="json"),
        "final_projection": (final or _projection()).model_dump(mode="json"),
        "proof": proof.model_dump(mode="json"),
        "proof_hash": proof.proof_hash,
    }
    return KernelModeExecutionRequest.model_validate(
        {**values, "request_hash": stable_hash(values)}
    )


def _rehash_request_payload(payload: dict) -> None:
    payload["request_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "request_hash"}
    )


def test_request_and_record_use_the_exact_normative_identity_contract():
    claims = FCClaims(
        run_id="mode-contract-run",
        audit_hash="6" * 64,
        deterministic_result_hash="1" * 64,
        proposal_ids=(),
        proposal_hashes=(),
        accepted_proposal_ids=(),
        decision_count=0,
        **_consistency_fields((), (), agent_context=False),
    )
    reference = _mode_reference(
        proof_schema="kp.final-consistency.v1",
        artifact_type="consistency_audit",
        schema_version="consistency-audit.v3",
        artifact_id="fc",
        claims=claims,
        ordinal=0,
    )
    request = _execution_request("deterministic", (reference,))
    record = finalize_execution(request)

    assert set(request.model_dump(mode="json")) == {
        "schema_version",
        "execution_contract_version",
        "organization_id",
        "project_id",
        "lifecycle_job_id",
        "run_id",
        "session_id",
        "attempt",
        "engine_mode",
        "kernel_mode",
        "effective_seed",
        "rule_pack_id",
        "rule_pack_hash",
        "agent_pack_id",
        "agent_pack_hash",
        "constraint_context_hash",
        "evaluator_version",
        "runtime_profile_hash",
        "fencing_epoch_hash",
        "baseline_projection",
        "final_projection",
        "proof",
        "proof_hash",
        "request_hash",
    }
    assert set(record.model_dump(mode="json")) == {
        "schema_version",
        "execution_contract_version",
        "request_hash",
        "organization_id",
        "project_id",
        "lifecycle_job_id",
        "run_id",
        "session_id",
        "attempt",
        "engine_mode",
        "kernel_mode",
        "effective_seed",
        "rule_pack_id",
        "rule_pack_hash",
        "agent_pack_id",
        "agent_pack_hash",
        "constraint_context_hash",
        "evaluator_version",
        "runtime_profile_hash",
        "baseline_source_run_hash",
        "baseline_deterministic_source_hash",
        "baseline_world_state_hash",
        "final_source_run_hash",
        "final_deterministic_source_hash",
        "final_world_state_hash",
        "fencing_epoch_hash",
        "authority_path",
        "proof_hash",
        "record_hash",
    }
    for field in (
        "organization_id",
        "project_id",
        "lifecycle_job_id",
        "run_id",
        "session_id",
        "attempt",
        "engine_mode",
        "kernel_mode",
        "effective_seed",
        "rule_pack_id",
        "rule_pack_hash",
        "agent_pack_id",
        "agent_pack_hash",
        "constraint_context_hash",
        "evaluator_version",
        "runtime_profile_hash",
        "fencing_epoch_hash",
        "proof_hash",
        "request_hash",
    ):
        assert getattr(record, field) == getattr(request, field)


def test_request_rejects_hash_context_session_and_removed_retry_field_drift():
    deterministic = _execution_request("deterministic", (_reference(),))

    identity_drift = deterministic.model_dump(mode="json")
    identity_drift["organization_id"] = "other-organization"
    with pytest.raises(ValidationError, match="request_hash mismatch"):
        KernelModeExecutionRequest.model_validate(identity_drift)

    proof_drift = deterministic.model_dump(mode="json")
    proof_drift["proof_hash"] = "f" * 64
    _rehash_request_payload(proof_drift)
    with pytest.raises(ValidationError, match="proof_hash"):
        KernelModeExecutionRequest.model_validate(proof_drift)

    deterministic_context = deterministic.model_dump(mode="json")
    deterministic_context.update(
        {
            "agent_pack_id": "agent-pack-test",
            "agent_pack_hash": "d" * 64,
            "constraint_context_hash": "e" * 64,
        }
    )
    _rehash_request_payload(deterministic_context)
    with pytest.raises(ValidationError, match="null Agent context"):
        KernelModeExecutionRequest.model_validate(deterministic_context)

    hybrid = _execution_request("hybrid", _hybrid_references())
    incomplete_context = hybrid.model_dump(mode="json")
    incomplete_context["constraint_context_hash"] = None
    _rehash_request_payload(incomplete_context)
    with pytest.raises(ValidationError, match="complete Agent context"):
        KernelModeExecutionRequest.model_validate(incomplete_context)

    wrong_session = hybrid.model_dump(mode="json")
    wrong_session["session_id"] = "session-not-allowed"
    _rehash_request_payload(wrong_session)
    with pytest.raises(ValidationError, match="non-null only for negotiation"):
        KernelModeExecutionRequest.model_validate(wrong_session)

    removed_retry_field = deterministic.model_dump(mode="json")
    removed_retry_field["retry_completed_ticks"] = [1]
    _rehash_request_payload(removed_retry_field)
    with pytest.raises(ValidationError, match="Extra inputs"):
        KernelModeExecutionRequest.model_validate(removed_retry_field)


def test_finalizer_binds_reference_session_and_consistency_to_request_identity():
    negotiation = list(_negotiation_references())
    negotiation[0] = negotiation[0].model_copy(update={"session_id": "other-session"})
    with pytest.raises(KernelModeFinalizationError, match="session_id"):
        finalize_execution(_execution_request("negotiation", tuple(negotiation)))

    hybrid = list(_hybrid_references())
    drifted_fc = hybrid[2].claims.model_copy(
        update={"evaluator_version": "other-evaluator.v1"}
    )
    hybrid[2] = _replace_mode_claims(hybrid[2], drifted_fc)
    with pytest.raises(KernelModeFinalizationError, match="resolver identity"):
        finalize_execution(_execution_request("hybrid", tuple(hybrid)))


def _audit_references(engine_mode: str, proposal_ids: tuple[str, ...] = ()) -> tuple[KernelModeProofReference, ...]:
    runtime_hash = "3" * 64
    batch_hash = "4" * 64
    proposal_hashes = tuple("5" * 64 for _ in proposal_ids)
    references: list[KernelModeProofReference] = []
    if engine_mode == "controlled_agent":
        ar_claims = ARClaims(
            run_id="mode-contract-run", runtime_hash=runtime_hash, proposal_ids=proposal_ids,
            proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
            invocation_ids=(), invocation_hashes=(), invocation_count=0,
        )
        references.append(_mode_reference(
            proof_schema="kp.agent-runtime.v1", artifact_type="agent_runtime_audit", schema_version="agent-runtime-result.v1",
            artifact_id="ar", claims=ar_claims, ordinal=0,
        ))
    pb_claims = PBClaims(
        run_id="mode-contract-run", source_kind=("mock_batch" if engine_mode == "mock_agent" else "agent_runtime"),
        source_mock_batch_hash=(batch_hash if engine_mode == "mock_agent" else None),
        source_runtime_hash=(runtime_hash if engine_mode == "controlled_agent" else None), batch_hash=batch_hash,
        proposal_ids=proposal_ids,
        proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
    )
    pb_relationships = () if engine_mode == "mock_agent" else (
        KernelModeProofRelationship(
            relationship_type="generated_by", target_artifact_id="ar", target_content_hash=references[0].content_hash,
        ),
    )
    pb = _mode_reference(
        proof_schema="kp.proposal-batch.v1", artifact_type="agent_action_proposals",
        schema_version="kernel-proposal-batch.v1",
        artifact_id="pb", claims=pb_claims, ordinal=len(references), relationships=pb_relationships,
    )
    references.append(pb)
    fc_claims = FCClaims(
        run_id="mode-contract-run", audit_hash="6" * 64, deterministic_result_hash="1" * 64,
        proposal_ids=proposal_ids, proposal_hashes=proposal_hashes,
        accepted_proposal_ids=(), decision_count=len(proposal_ids),
        **_consistency_fields(
            proposal_ids, proposal_hashes, agent_context=True
        ),
    )
    fc = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v3",
        artifact_id="fc", claims=fc_claims, ordinal=len(references), relationships=(
            KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id="pb", target_content_hash=pb.content_hash),
        ),
    )
    references.append(fc)
    if proposal_ids:
        pa_claims = PAClaims(
            run_id="mode-contract-run", session_id=None, projection_mode="audit_only", audit_hash="7" * 64, consistency_audit_hash=fc_claims.audit_hash,
            proposal_ids=proposal_ids, proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
            record_input_hashes=proposal_hashes,
            record_claim_tuples=tuple(
                (item, proposal_hashes[index], proposal_hashes[index], "rejected", "worldpulse-consistency.v1.2", "rejected", "rejected-by-test", "blocked", None, None, "1" * 64)
                for index, item in enumerate(proposal_ids)
            ),
            projected_proposal_ids=(), projected_semantic_key_hashes=(), projected_count=0,
            modifier_tuples=(), modifier_count=0,
            record_count=len(proposal_ids), before_result_hash="1" * 64, final_result_hash="1" * 64,
        )
        references.append(_mode_reference(
            proof_schema="kp.projection-audit.v1", artifact_type="agent_action_projection_audit",
            schema_version="agent-action-projection-audit.v2", artifact_id="pa", claims=pa_claims, ordinal=len(references),
            relationships=(
                KernelModeProofRelationship(relationship_type="covers", target_artifact_id="pb", target_content_hash=pb.content_hash),
                KernelModeProofRelationship(relationship_type="governed_by", target_artifact_id="fc", target_content_hash=fc.content_hash),
            ),
        ))
    return tuple(references)


def _hybrid_references(
    proposal_ids: tuple[str, ...] = ("proposal-1",),
    accepted_ids: tuple[str, ...] = ("proposal-1",),
    engine_mode: str = "hybrid",
) -> tuple[KernelModeProofReference, ...]:
    runtime_hash = "3" * 64
    audit_hash = "6" * 64
    bundle_hash = "7" * 64
    projection_audit_hash = "8" * 64
    final_result_hash = "9" * 64
    proposal_hashes = tuple("5" * 64 for _ in proposal_ids)
    modifiers = tuple(
        ModifierReference(proposal_id=item, modifier_id=f"modifier-{item}", modifier_hash="a" * 64)
        for item in accepted_ids
    )
    ar = _mode_reference(
        proof_schema="kp.agent-runtime.v1", artifact_type="agent_runtime_audit", schema_version="agent-runtime-result.v1",
        artifact_id="ar", ordinal=0,
        claims=ARClaims(
            run_id="mode-contract-run", runtime_hash=runtime_hash, proposal_ids=proposal_ids,
            proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
            invocation_ids=(), invocation_hashes=(), invocation_count=0,
        ),
    )
    pb = _mode_reference(
        proof_schema="kp.proposal-batch.v1", artifact_type="agent_action_proposals", schema_version="kernel-proposal-batch.v1",
        artifact_id="pb", ordinal=1,
        claims=PBClaims(
            run_id="mode-contract-run", source_kind="agent_runtime", source_runtime_hash=runtime_hash,
            source_mock_batch_hash=None, batch_hash="4" * 64,
            proposal_ids=proposal_ids, proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="generated_by", target_artifact_id=ar.artifact_id, target_content_hash=ar.content_hash),
        ),
    )
    fc = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v3",
        artifact_id="fc", ordinal=2,
        claims=FCClaims(
            run_id="mode-contract-run", audit_hash=audit_hash, deterministic_result_hash="1" * 64,
            proposal_ids=proposal_ids, proposal_hashes=proposal_hashes,
            accepted_proposal_ids=accepted_ids, decision_count=len(proposal_ids),
            **_consistency_fields(
                proposal_ids, proposal_hashes, accepted_ids, agent_context=True
            ),
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=pb.artifact_id, target_content_hash=pb.content_hash),
        ),
    )
    mb = _mode_reference(
        proof_schema="kp.action-modifier-bundle.v1", artifact_type="deterministic_action_modifiers",
        schema_version="hybrid-modifier-bundle.v2", artifact_id="mb", ordinal=3,
        claims=MBClaims(
            run_id="mode-contract-run", bundle_hash=bundle_hash, inner_bundle_hash="0" * 64,
            consistency_audit_hash=audit_hash,
            accepted_proposal_ids=accepted_ids, modifier_tuples=modifiers, modifier_count=len(modifiers),
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="maps", target_artifact_id=pb.artifact_id, target_content_hash=pb.content_hash),
            KernelModeProofRelationship(relationship_type="admitted_by", target_artifact_id=fc.artifact_id, target_content_hash=fc.content_hash),
        ),
    )
    cl = _mode_reference(
        proof_schema="kp.commitment-ledger.v1", artifact_type="commitment_ledger", schema_version="commitment-ledger.v2",
        artifact_id="cl", ordinal=4,
        claims=CLClaims(run_id="mode-contract-run", session_id=None, tick=None,
                        ledger_hash=empty_commitment_ledger_hash("mode-contract-run"), ledger_entry_count=0),
        relationships=(
            KernelModeProofRelationship(relationship_type="ledger_for", target_artifact_id=mb.artifact_id, target_content_hash=mb.content_hash),
        ),
    )
    pa = _mode_reference(
        proof_schema="kp.projection-audit.v1", artifact_type="agent_action_projection_audit",
        schema_version="agent-action-projection-audit.v2", artifact_id="pa", ordinal=5,
        claims=PAClaims(
            run_id="mode-contract-run", session_id=None, projection_mode="hybrid", audit_hash=projection_audit_hash,
            consistency_audit_hash=audit_hash, modifier_bundle_hash=bundle_hash,
            proposal_ids=proposal_ids, proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
            record_input_hashes=proposal_hashes,
            record_claim_tuples=tuple(
                (item, proposal_hashes[index], proposal_hashes[index],
                 ("accepted" if item in accepted_ids else "rejected"),
                 "worldpulse-consistency.v1.2",
                 ("accepted" if item in accepted_ids else "rejected"),
                 (None if item in accepted_ids else "rejected-by-test"),
                 ("projected" if item in accepted_ids else "blocked"),
                 ("a" * 64 if item in accepted_ids else None),
                 (f"modifier-{item}" if item in accepted_ids else None), final_result_hash)
                for index, item in enumerate(proposal_ids)
            ),
            projected_proposal_ids=accepted_ids,
            projected_semantic_key_hashes=tuple("c" * 64 for _ in accepted_ids), projected_count=len(accepted_ids),
            modifier_tuples=modifiers, modifier_count=len(modifiers),
            record_count=len(proposal_ids), before_result_hash="1" * 64, final_result_hash=final_result_hash,
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="covers", target_artifact_id=pb.artifact_id, target_content_hash=pb.content_hash),
            KernelModeProofRelationship(relationship_type="governed_by", target_artifact_id=fc.artifact_id, target_content_hash=fc.content_hash),
            KernelModeProofRelationship(relationship_type="audits", target_artifact_id=mb.artifact_id, target_content_hash=mb.content_hash),
            KernelModeProofRelationship(relationship_type="ledger_snapshot", target_artifact_id=cl.artifact_id, target_content_hash=cl.content_hash),
        ),
    )
    hr = _mode_reference(
        proof_schema="kp.hybrid-replay.v1", artifact_type="hybrid_replay_record", schema_version="hybrid-replay-record.v2",
        artifact_id="hr", ordinal=6,
        claims=HRClaims(
            run_id="mode-contract-run", engine_mode=engine_mode, replay_source_kind="stored_only", provider_calls_required=0,
            replay_hash="b" * 64, baseline_result_hash="1" * 64,
            final_result_hash=final_result_hash, full_source_run_hash="1" * 64,
            proposal_batch_hash="4" * 64, consistency_audit_hash=audit_hash,
            modifier_bundle_hash=bundle_hash, projection_audit_hash=projection_audit_hash,
            ledger_hash=empty_commitment_ledger_hash("mode-contract-run"), accepted_proposal_ids=accepted_ids,
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="observations", target_artifact_id=pb.artifact_id, target_content_hash=pb.content_hash),
            KernelModeProofRelationship(relationship_type="governed_by", target_artifact_id=fc.artifact_id, target_content_hash=fc.content_hash),
            KernelModeProofRelationship(relationship_type="replays", target_artifact_id=mb.artifact_id, target_content_hash=mb.content_hash),
            KernelModeProofRelationship(relationship_type="ledger_snapshot", target_artifact_id=cl.artifact_id, target_content_hash=cl.content_hash),
            KernelModeProofRelationship(relationship_type="audit", target_artifact_id=pa.artifact_id, target_content_hash=pa.content_hash),
        ),
    )
    return ar, pb, fc, mb, cl, pa, hr


def _negotiation_references(
    accepted_ticks: tuple[int, ...] = (),
    diffusion_ticks: tuple[int, ...] = (),
) -> tuple[KernelModeProofReference, ...]:
    """Build the canonical 38 + 3P negotiation evidence chain."""

    def digest(name: str) -> str:
        return stable_hash({"negotiation-test": name})

    projected_ticks = tuple(sorted(set(accepted_ticks) | set(diffusion_ticks)))
    projection_ordinal = {tick: 30 + index for index, tick in enumerate(projected_ticks)}
    modifier_ordinal = {
        tick: 31 + len(projected_ticks) + index for index, tick in enumerate(projected_ticks)
    }
    audit_ordinal = {
        tick: 37 + 2 * len(projected_ticks) + index for index, tick in enumerate(projected_ticks)
    }
    message_seq = 0
    tick_data: dict[int, dict[str, object]] = {}
    for tick in range(1, 7):
        projected = tick in projected_ticks
        proposal_id = f"proposal-{tick}"
        proposal_ids = (proposal_id,) if projected else ()
        proposal_hash = digest(f"proposal-{tick}")
        proposal_hashes = (proposal_hash,) if projected else ()
        ac_hash = digest(f"ac-{tick}")
        cl_hash = digest(f"cl-{tick}")
        message_tuples = ()
        source_tuples = ()
        if projected:
            message_seq += 1
            message_id = f"msg-{tick}"
            message_hash = digest(f"message-{tick}")
            message_tuples = ((message_seq, message_id, message_hash),)
            action_class = "public_narrative" if tick in diffusion_ticks else "deterministic_modifier"
            action_type = "public_narrative" if tick in diffusion_ticks else "diplomatic_signal"
            source_tuples = ((
                proposal_id, proposal_hash, message_id, message_hash, action_type,
                action_class, digest(f"semantic-{tick}"), "current_message", None, tick, ac_hash,
            ),)
        messages_hash = digest(f"messages-{tick}")
        batch_hash = digest(f"np-{tick}")
        decision_tuples = ()
        eligible_ids = ()
        if projected:
            decision_hash = stable_hash({"decision": [source_tuples[0], False, "eligible"]})
            decision_tuples = ((source_tuples[0], False, "eligible", decision_hash),)
            eligible_ids = proposal_ids
        eligibility_hash = stable_hash({
            "schema_version": "negotiation-eligibility.v1",
            "run_id": "mode-contract-run",
            "session_id": "session-1",
            "tick": tick,
            "decision_hashes": tuple(item[3] for item in decision_tuples),
            "eligible_proposal_ids": eligible_ids,
        })
        tick_data[tick] = {
            "proposal_ids": proposal_ids,
            "proposal_hashes": proposal_hashes,
            "source_tuples": source_tuples,
            "message_tuples": message_tuples,
            "messages_hash": messages_hash,
            "ac_hash": ac_hash,
            "cl_hash": cl_hash,
            "batch_hash": batch_hash,
            "decision_tuples": decision_tuples,
            "eligible_ids": eligible_ids,
            "eligibility_hash": eligibility_hash,
        }

    rounds: list[KernelModeProofReference] = []
    for tick in range(1, 7):
        data = tick_data[tick]
        projected = tick in projected_ticks
        rr = _mode_reference(
            proof_schema="kp.negotiation-round.v1", artifact_type="negotiation_round",
            schema_version="negotiation-round.v2", artifact_id=f"rr-{tick}", ordinal=tick - 1, tick=tick,
            claims=RRClaims(
                run_id="mode-contract-run", session_id="session-1",
                round_id=f"round_{stable_hash({'session': 'session-1', 'tick': tick})[:20]}", tick=tick,
                input_hash=digest(f"input-{tick}"), output_hash=digest(f"output-{tick}"),
                round_hash=digest(f"round-{tick}"), before_result_hash="1" * 64, after_result_hash="1" * 64,
                message_tuples=data["message_tuples"], messages_hash=data["messages_hash"],
                message_count=len(data["message_tuples"]), proposal_ids=data["proposal_ids"],
                accepted_proposal_ids=data["proposal_ids"], proposal_batch_hash=data["batch_hash"],
                admission_audit_hash=data["ac_hash"], ledger_hash=data["cl_hash"],
                eligibility_hash=data["eligibility_hash"], eligible_proposal_ids=data["eligible_ids"],
                projection_consistency_hash=(digest(f"pc-{tick}") if projected else None),
                modifier_bundle_hash=(digest(f"mb-{tick}") if projected else None),
                diffusion_evidence_hash=digest(f"nd-{tick}"),
                projection_audit_hash=(digest(f"pa-{tick}") if projected else None),
                no_projection_reason=(None if projected else "no_projection"),
            ),
            relationships=(() if tick == 1 else (
                KernelModeProofRelationship(relationship_type="previous_round", target_artifact_id=rounds[-1].artifact_id, target_content_hash=rounds[-1].content_hash),
            )),
        )
        rounds.append(rr)

    proposals: list[KernelModeProofReference] = []
    admissions: list[KernelModeProofReference] = []
    ledgers: list[KernelModeProofReference] = []
    eligibilities: list[KernelModeProofReference] = []
    projections: dict[int, KernelModeProofReference] = {}
    modifiers: dict[int, KernelModeProofReference] = {}
    diffusions: list[KernelModeProofReference] = []
    audits: dict[int, KernelModeProofReference] = {}
    for tick in range(1, 7):
        data = tick_data[tick]
        rr = rounds[tick - 1]
        np = _mode_reference(
            proof_schema="kp.negotiation-proposal-batch.v1", artifact_type="negotiation_proposal_batch",
            schema_version="negotiation-proposal-batch.v1", artifact_id=f"np-{tick}", ordinal=6 + tick - 1, tick=tick,
            claims=NPClaims(
                run_id="mode-contract-run", session_id="session-1", tick=tick,
                source_hashes=(data["messages_hash"], data["ac_hash"], data["cl_hash"]),
                proposal_claim_tuples=data["source_tuples"], proposal_count=len(data["source_tuples"]),
                batch_hash=data["batch_hash"],
            ),
            relationships=(KernelModeProofRelationship(relationship_type="source_for", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),),
        )
        proposals.append(np)
        ac = _mode_reference(
            proof_schema="kp.negotiation-admission-consistency.v1", artifact_type="consistency_audit",
            schema_version="consistency-audit.v3", artifact_id=f"ac-{tick}", ordinal=12 + tick - 1, tick=tick,
            claims=ACClaims(
                run_id="mode-contract-run", tick=tick, audit_hash=data["ac_hash"], deterministic_result_hash="1" * 64,
                proposal_ids=data["proposal_ids"], proposal_hashes=data["proposal_hashes"],
                accepted_proposal_ids=data["proposal_ids"], decision_count=len(data["proposal_ids"]),
                **_consistency_fields(
                    data["proposal_ids"],
                    data["proposal_hashes"],
                    data["proposal_ids"],
                    agent_context=True,
                ),
            ),
            relationships=(KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=np.artifact_id, target_content_hash=np.content_hash),),
        )
        admissions.append(ac)
        cl = _mode_reference(
            proof_schema="kp.commitment-ledger.v1", artifact_type="commitment_ledger",
            schema_version="commitment-ledger.v2", artifact_id=f"cl-{tick}", ordinal=18 + tick - 1, tick=tick,
            claims=CLClaims(
                run_id="mode-contract-run", session_id="session-1", tick=tick,
                ledger_hash=data["cl_hash"], ledger_entry_count=0,
            ),
            relationships=(KernelModeProofRelationship(relationship_type="snapshot_after", target_artifact_id=ac.artifact_id, target_content_hash=ac.content_hash),),
        )
        ledgers.append(cl)
        prior_pa = tuple(audits[prior] for prior in projected_ticks if prior < tick)
        el = _mode_reference(
            proof_schema="kp.negotiation-eligibility.v1", artifact_type="negotiation_eligibility",
            schema_version="negotiation-eligibility.v1", artifact_id=f"el-{tick}", ordinal=24 + tick - 1, tick=tick,
            claims=ELClaims(
                run_id="mode-contract-run", session_id="session-1", tick=tick,
                decision_tuples=data["decision_tuples"], decision_count=len(data["decision_tuples"]),
                eligible_proposal_ids=data["eligible_ids"], eligible_proposal_count=len(data["eligible_ids"]),
                eligibility_hash=data["eligibility_hash"],
            ),
            relationships=(
                KernelModeProofRelationship(relationship_type="sources", target_artifact_id=np.artifact_id, target_content_hash=np.content_hash),
                KernelModeProofRelationship(relationship_type="admitted_by", target_artifact_id=ac.artifact_id, target_content_hash=ac.content_hash),
                KernelModeProofRelationship(relationship_type="current_ledger", target_artifact_id=cl.artifact_id, target_content_hash=cl.content_hash),
                *(KernelModeProofRelationship(relationship_type="prior_projection", target_artifact_id=item.artifact_id, target_content_hash=item.content_hash) for item in prior_pa),
            ),
        )
        eligibilities.append(el)

        projected = tick in projected_ticks
        modifier_refs = ()
        if projected:
            proposal_id = data["proposal_ids"][0]
            proposal_hash = data["proposal_hashes"][0]
            modifier = ModifierReference(
                proposal_id=proposal_id, modifier_id=f"modifier-{tick}", modifier_hash=digest(f"modifier-{tick}")
            )
            pc = _mode_reference(
                proof_schema="kp.negotiation-projection-consistency.v1", artifact_type="consistency_audit",
                schema_version="consistency-audit.v3", artifact_id=f"pc-{tick}", ordinal=projection_ordinal[tick], tick=tick,
                claims=PCClaims(
                    run_id="mode-contract-run", tick=tick, audit_hash=digest(f"pc-{tick}"), deterministic_result_hash="1" * 64,
                    candidate_proposal_ids=data["eligible_ids"], proposal_hashes=data["proposal_hashes"],
                    accepted_proposal_ids=data["proposal_ids"], decision_count=len(data["proposal_ids"]),
                    **_consistency_fields(
                        data["eligible_ids"],
                        data["proposal_hashes"],
                        data["proposal_ids"],
                        agent_context=True,
                    ),
                ),
                relationships=(KernelModeProofRelationship(relationship_type="filters", target_artifact_id=el.artifact_id, target_content_hash=el.content_hash),),
            )
            projections[tick] = pc
            mb = _mode_reference(
                proof_schema="kp.action-modifier-bundle.v1", artifact_type="deterministic_action_modifiers",
                schema_version="hybrid-modifier-bundle.v2", artifact_id=f"mb-{tick}", ordinal=modifier_ordinal[tick], tick=tick,
                claims=MBClaims(
                    run_id="mode-contract-run", tick=tick, bundle_hash=digest(f"mb-{tick}"),
                    inner_bundle_hash=digest(f"inner-mb-{tick}"),
                    consistency_audit_hash=digest(f"pc-{tick}"), accepted_proposal_ids=data["proposal_ids"],
                    modifier_tuples=(modifier,), modifier_count=1,
                ),
                relationships=(KernelModeProofRelationship(relationship_type="admitted_by", target_artifact_id=pc.artifact_id, target_content_hash=pc.content_hash),),
            )
            modifiers[tick] = mb
            modifier_refs = (KernelModeProofRelationship(relationship_type="bounded_by", target_artifact_id=mb.artifact_id, target_content_hash=mb.content_hash),)

        attempted = tick in diffusion_ticks
        application_hash = digest(f"application-{tick}")
        application_tuples = ((
            data["proposal_ids"][0], "USA", "USA", "informational", "global",
            -10000, 10000, 10000, 10000, -10000, -10000, application_hash,
        ),) if attempted else ()
        nd = _mode_reference(
            proof_schema="kp.narrative-diffusion.v1", artifact_type="narrative_diffusion",
            schema_version="narrative-diffusion.v2", artifact_id=f"nd-{tick}",
            ordinal=31 + 2 * len(projected_ticks) + tick - 1, tick=tick,
            claims=NDClaims(
                run_id="mode-contract-run", session_id="session-1", tick=tick, attempted=attempted,
                input_proposal_ids=(data["proposal_ids"] if attempted else ()),
                input_proposal_hashes=(data["proposal_hashes"] if attempted else ()),
                narrative_diffusion_audit_hash=digest(f"core-{tick}"), diffusion_request_hash=digest(f"request-{tick}"),
                before_result_hash="1" * 64, after_result_hash="1" * 64,
                tone_delta_tuples=(("firm", 30000), ("informational", -10000), ("stabilizing", -40000)),
                country_delta_tuples=(("USA", -10000),) if attempted else (),
                application_tuples=application_tuples, application_count=len(application_tuples),
                diffusion_evidence_hash=digest(f"nd-{tick}"),
            ),
            relationships=(
                KernelModeProofRelationship(relationship_type="inputs", target_artifact_id=el.artifact_id, target_content_hash=el.content_hash),
                *modifier_refs,
            ),
        )
        diffusions.append(nd)
        if projected:
            modifier = modifiers[tick].claims.modifier_tuples[0]
            pa = _mode_reference(
                proof_schema="kp.projection-audit.v1", artifact_type="negotiation_projection_audit",
                schema_version="negotiation-projection-audit.v2", artifact_id=f"pa-{tick}", ordinal=audit_ordinal[tick], tick=tick,
                claims=PAClaims(
                    run_id="mode-contract-run", session_id="session-1", tick=tick,
                    projection_mode="negotiation", audit_hash=digest(f"pa-{tick}"),
                    consistency_audit_hash=digest(f"pc-{tick}"), modifier_bundle_hash=digest(f"mb-{tick}"),
                    proposal_ids=data["proposal_ids"], proposal_hashes=data["proposal_hashes"], proposal_count=1,
                    record_input_hashes=data["proposal_hashes"],
                    record_claim_tuples=((
                        data["proposal_ids"][0], data["proposal_hashes"][0], data["proposal_hashes"][0],
                        "accepted", "worldpulse-consistency.v1.2", "accepted", None, "projected", modifier.modifier_hash,
                        modifier.modifier_id, "1" * 64,
                    ),),
                    projected_proposal_ids=data["proposal_ids"],
                    projected_semantic_key_hashes=(data["source_tuples"][0][6],), projected_count=1,
                    modifier_tuples=(modifier,), modifier_count=1, record_count=1,
                    before_result_hash="1" * 64, final_result_hash="1" * 64,
                ),
                relationships=(
                    KernelModeProofRelationship(relationship_type="round", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),
                    KernelModeProofRelationship(relationship_type="governed_by", target_artifact_id=projections[tick].artifact_id, target_content_hash=projections[tick].content_hash),
                    KernelModeProofRelationship(relationship_type="audits", target_artifact_id=modifiers[tick].artifact_id, target_content_hash=modifiers[tick].content_hash),
                    KernelModeProofRelationship(relationship_type="diffusion", target_artifact_id=nd.artifact_id, target_content_hash=nd.content_hash),
                    KernelModeProofRelationship(relationship_type="ledger_snapshot", target_artifact_id=cl.artifact_id, target_content_hash=cl.content_hash),
                ),
            )
            audits[tick] = pa

    final_audit = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v3",
        artifact_id="fc", ordinal=30 + len(projected_ticks),
        claims=FCClaims(
            run_id="mode-contract-run", audit_hash=digest("fc"), deterministic_result_hash="1" * 64,
            proposal_ids=(), proposal_hashes=(), accepted_proposal_ids=(), decision_count=0,
            **_consistency_fields((), (), agent_context=True),
        ),
        relationships=(KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=rounds[-1].artifact_id, target_content_hash=rounds[-1].content_hash),),
    )
    nr_targets = (
        tuple(("replays", item) for item in rounds)
        + tuple(("proposal_sources", item) for item in proposals)
        + tuple(("admission", item) for item in admissions)
        + tuple(("ledgers", item) for item in ledgers)
        + tuple(("eligibility", item) for item in eligibilities)
        + tuple(("projection", projections[tick]) for tick in projected_ticks)
        + (("final_audit", final_audit),)
        + tuple(("modifiers", modifiers[tick]) for tick in projected_ticks)
        + tuple(("diffusion", item) for item in diffusions)
        + tuple(("audits", audits[tick]) for tick in projected_ticks)
    )
    all_messages = tuple(item for data in tick_data.values() for item in data["message_tuples"])
    nr = _mode_reference(
        proof_schema="kp.negotiation-replay.v1", artifact_type="negotiation_replay",
        schema_version="negotiation-replay.v2", artifact_id="nr", ordinal=37 + 3 * len(projected_ticks),
        claims=NRClaims(
            run_id="mode-contract-run", session_id="session-1", replay_hash=digest("nr"),
            baseline_result_hash="1" * 64, final_result_hash="1" * 64,
            round_hashes=tuple(item.claims.round_hash for item in rounds),
            proposal_batch_hashes=tuple(item.claims.batch_hash for item in proposals),
            admission_audit_hashes=tuple(item.claims.audit_hash for item in admissions),
            ledger_hashes=tuple(item.claims.ledger_hash for item in ledgers),
            eligibility_hashes=tuple(item.claims.eligibility_hash for item in eligibilities),
            projection_consistency_hashes=tuple(item.claims.projection_consistency_hash for item in rounds),
            modifier_bundle_hashes=tuple(item.claims.modifier_bundle_hash for item in rounds),
            diffusion_evidence_hashes=tuple(item.claims.diffusion_evidence_hash for item in diffusions),
            projection_audit_hashes=tuple(item.claims.projection_audit_hash for item in rounds),
            message_chain_head=(all_messages[-1][2] if all_messages else None),
        ),
        relationships=tuple(
            KernelModeProofRelationship(relationship_type=kind, target_artifact_id=target.artifact_id, target_content_hash=target.content_hash)
            for kind, target in nr_targets
        ),
    )
    assembled = (
        *rounds, *proposals, *admissions, *ledgers, *eligibilities,
        *(projections[tick] for tick in projected_ticks), final_audit,
        *(modifiers[tick] for tick in projected_ticks), *diffusions,
        *(audits[tick] for tick in projected_ticks), nr,
    )
    return tuple(
        reference.model_copy(update={"session_id": "session-1"})
        for reference in assembled
    )


@pytest.mark.parametrize("engine_mode", ["deterministic", "mock_agent", "controlled_agent"])
def test_finalization_admits_exact_deterministic_mode_sequences_without_mutation(engine_mode):
    if engine_mode == "deterministic":
        claims = FCClaims(
            run_id="mode-contract-run", audit_hash="6" * 64, deterministic_result_hash="1" * 64,
            proposal_ids=(), proposal_hashes=(), accepted_proposal_ids=(), decision_count=0,
            **_consistency_fields((), (), agent_context=False),
        )
        references = (_mode_reference(
            proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v3",
            artifact_id="fc", claims=claims, ordinal=0,
        ),)
    else:
        references = _audit_references(engine_mode, ("proposal-1",))
    request = _execution_request(engine_mode, references)
    before = request.model_dump(mode="json")

    first = finalize_execution(request)
    second = finalize_execution(request)

    assert first == second
    assert first.authority_path == {
        "deterministic": "deterministic_audit_only",
        "mock_agent": "mock_action_adapter_deterministic",
        "controlled_agent": "controlled_action_adapter_deterministic",
    }[engine_mode]
    assert request.model_dump(mode="json") == before


@pytest.mark.parametrize("engine_mode", ["hybrid", "hybrid_recorded"])
@pytest.mark.parametrize("proposal_ids, accepted_ids", [(("proposal-1",), ("proposal-1",)), ((), ())])
def test_finalization_admits_hybrid_and_recorded_with_required_noop_chain(engine_mode, proposal_ids, accepted_ids):
    references = _hybrid_references(proposal_ids, accepted_ids, engine_mode)
    request = _execution_request(engine_mode, references)

    first = finalize_execution(request)
    second = finalize_execution(request)

    assert first == second
    assert first.kernel_mode == "hybrid"
    assert first.authority_path == {
        "hybrid": "hybrid_action_adapter_replay",
        "hybrid_recorded": "hybrid_recorded_action_adapter_replay",
    }[engine_mode]


@pytest.mark.parametrize("projected_ticks", [(), (2, 5)])
def test_finalization_admits_negotiation_six_tick_chains(projected_ticks):
    references = _negotiation_references(projected_ticks)
    record = finalize_execution(_execution_request("negotiation", references))

    assert len(references) == 38 + 3 * len(projected_ticks)
    assert record.authority_path == "negotiation_governed_deterministic"


def test_negotiation_rejects_surplus_projection():
    references = _negotiation_references()
    surplus = _negotiation_references((1,))
    malformed = tuple(
        reference.model_copy(update={"ordinal": ordinal})
        for ordinal, reference in enumerate((*references[:30], surplus[30], *references[30:]))
    )
    with pytest.raises(KernelModeFinalizationError, match="projection|count|sequence"):
        finalize_execution(_execution_request("negotiation", malformed))


def test_negotiation_rejects_wrong_p_derivation_modifier_replay_and_cross_attempt():
    missing_projection = list(_negotiation_references((1,)))
    del missing_projection[30]
    missing_projection = [
        item.model_copy(update={"ordinal": ordinal})
        for ordinal, item in enumerate(missing_projection)
    ]
    with pytest.raises(KernelModeFinalizationError, match="projection|sequence|FC"):
        finalize_execution(_execution_request("negotiation", tuple(missing_projection)))

    projected = list(_negotiation_references((1,)))
    projected[32] = _replace_mode_claims(
        projected[32], projected[32].claims.model_copy(update={"modifier_tuples": (
            ModifierReference(proposal_id="proposal-1", modifier_id="mismatch", modifier_hash="f" * 64),
        ), "modifier_count": 1})
    )
    with pytest.raises(KernelModeFinalizationError, match="projected negotiation tick claims"):
        finalize_execution(_execution_request("negotiation", tuple(projected)))

    with pytest.raises(ValidationError, match="provider_calls_required"):
        NRClaims(
            run_id="mode-contract-run", session_id="session-1", replay_hash="a" * 64,
            baseline_result_hash="1" * 64, final_result_hash="1" * 64,
            round_hashes=("a" * 64,) * 6, proposal_batch_hashes=("b" * 64,) * 6,
            admission_audit_hashes=("c" * 64,) * 6, ledger_hashes=("d" * 64,) * 6,
            eligibility_hashes=("e" * 64,) * 6, projection_consistency_hashes=(None,) * 6,
            modifier_bundle_hashes=(None,) * 6, diffusion_evidence_hashes=("f" * 64,) * 6,
            projection_audit_hashes=(None,) * 6,
            message_chain_head="e" * 64, provider_calls_required=1,
        )

    cross_attempt = _negotiation_references()
    with pytest.raises(KernelModeFinalizationError, match="attempt"):
        finalize_execution(_execution_request("negotiation", (cross_attempt[0].model_copy(update={"attempt": "attempt-2"}), *cross_attempt[1:])))



@pytest.mark.parametrize("missing_ordinal", [4, 5, 6])
def test_hybrid_finalization_requires_ledger_projection_audit_and_replay(missing_ordinal):
    references = _hybrid_references()
    incomplete = tuple(item for item in references if item.ordinal != missing_ordinal)
    with pytest.raises(KernelModeFinalizationError, match="ordinal|sequence"):
        finalize_execution(_execution_request("hybrid", incomplete))


def test_hybrid_finalization_rejects_nonempty_ledger_and_modifier_mismatch():
    references = _hybrid_references()
    nonempty_ledger = _mode_reference(
        proof_schema="kp.commitment-ledger.v1", artifact_type="commitment_ledger", schema_version="commitment-ledger.v2",
        artifact_id="cl", ordinal=4,
        claims=CLClaims(run_id="mode-contract-run", ledger_hash="c" * 64, ledger_entry_count=1, commitments=(
            ("commitment-1", "d" * 64, "active", "alliance_request", ("agent-a", "agent-b"),
             "e" * 64, "proposal-1", "f" * 64, "message-1", "a" * 64, 1, "b" * 64),
        )),
        relationships=references[4].relationships,
    )
    with pytest.raises(KernelModeFinalizationError, match="empty ledger"):
        finalize_execution(_execution_request("hybrid", (*references[:4], nonempty_ledger, *references[5:])))

    with pytest.raises(ValidationError, match="exactly one modifier tuple"):
        references[5].claims.model_copy(update={"modifier_tuples": (), "modifier_count": 0})


def test_projection_claims_and_finalizer_reject_truth_table_or_consistency_drift():
    references = _hybrid_references()
    pa_payload = references[5].claims.model_dump(mode="python")
    invalid_record = list(pa_payload["record_claim_tuples"][0])
    invalid_record[7] = "not_projected"
    pa_payload["record_claim_tuples"] = (tuple(invalid_record),)
    with pytest.raises(ValidationError, match="truth table"):
        PAClaims.model_validate(pa_payload)

    drifted_payload = references[5].claims.model_dump(mode="python")
    drifted_record = list(drifted_payload["record_claim_tuples"][0])
    drifted_record[4] = "different-rule-version"
    drifted_payload["record_claim_tuples"] = (tuple(drifted_record),)
    drifted_claims = PAClaims.model_validate(drifted_payload)
    drifted_reference = _replace_mode_claims(references[5], drifted_claims)
    with pytest.raises(KernelModeFinalizationError, match="pre-projection decisions"):
        finalize_execution(
            _execution_request(
                "hybrid", (*references[:5], drifted_reference, references[6])
            )
        )


def test_hybrid_finalization_rejects_bad_hash_relationship_cross_attempt_and_numeric_owner():
    references = _hybrid_references()
    bad_hr = _mode_reference(
        proof_schema="kp.hybrid-replay.v1", artifact_type="hybrid_replay_record", schema_version="hybrid-replay-record.v2",
        artifact_id="hr", ordinal=6, claims=references[6].claims.model_copy(update={"ledger_hash": "c" * 64}),
        relationships=references[6].relationships,
    )
    with pytest.raises(KernelModeFinalizationError, match="Replay claims"):
        finalize_execution(_execution_request("hybrid", (*references[:6], bad_hr)))

    bad_mb = references[3].model_copy(update={"relationships": ()})
    with pytest.raises(KernelModeFinalizationError, match="relationship"):
        finalize_execution(_execution_request("hybrid", (*references[:3], bad_mb, *references[4:])))

    wrong_attempt = references[0].model_copy(update={"attempt": "attempt-2"})
    with pytest.raises(KernelModeFinalizationError, match="attempt"):
        finalize_execution(_execution_request("hybrid", (wrong_attempt, *references[1:])))

    invalid_state = WorldState(
        run_id="mode-contract-run", seed=17, rule_pack_hash="a" * 64,
        entities={"country:USA": Entity(
            entity_id="country:USA", entity_type="country",
            components={"risk_score": 1.0, "authority_provenance": {"owner": "agent", "components": ("risk_score",)}},
        )},
    )
    invalid_projection = WarRoomProjection(
        source_run_hash="1" * 64, deterministic_source_hash="2" * 64,
        world_state_hash=invalid_state.content_hash(), world_state=invalid_state,
    )
    with pytest.raises(KernelModeFinalizationError, match="numeric authority owner"):
        finalize_execution(
            _execution_request(
                "hybrid",
                _hybrid_references((), ()),
                baseline=invalid_projection,
                final=invalid_projection,
            )
        )


def test_finalization_rejects_wrong_audit_relationship_and_cross_attempt_reference():
    references = _audit_references("mock_agent", ("proposal-1",))
    invalid_fc = references[1].model_copy(update={"relationships": ()})
    with pytest.raises(KernelModeFinalizationError, match="relationship"):
        finalize_execution(_execution_request("mock_agent", (references[0], invalid_fc, references[2])))

    wrong_attempt = references[0].model_copy(update={"attempt": "attempt-2"})
    with pytest.raises(KernelModeFinalizationError, match="attempt"):
        finalize_execution(_execution_request("mock_agent", (wrong_attempt, references[1], references[2])))

def test_finalization_rejects_empty_or_arbitrary_admitted_proof():
    with pytest.raises(KernelModeFinalizationError, match="at least one"):
        finalize_execution(_execution_request("deterministic", ()))

    arbitrary_audit_proof = _audit_references("mock_agent")
    deterministic_request = _execution_request(
        "deterministic", arbitrary_audit_proof
    )
    with pytest.raises(KernelModeFinalizationError, match="resolver identity|sequence"):
        finalize_execution(deterministic_request)


def _append_supersedes(
    reference: KernelModeProofReference,
    *,
    target_attempt: str = "attempt-0",
) -> KernelModeProofReference:
    return reference.model_copy(update={
        "relationships": (*reference.relationships, KernelModeProofRelationship(
            relationship_type="supersedes",
            target_artifact_id="historic-artifact",
            target_content_hash="f" * 64,
            target_attempt=target_attempt,
        )),
    })


def _supersede_retry_tick(
    references: tuple[KernelModeProofReference, ...],
    tick: int,
) -> tuple[KernelModeProofReference, ...]:
    """Append retry provenance to every re-emitted proof for one tick."""

    return tuple(
        _append_supersedes(reference)
        if reference.tick == tick and reference.token in {"RR", "NP", "AC", "CL", "EL", "PC", "MB", "ND", "PA"}
        else reference
        for reference in references
    )


def test_execution_record_requires_fixed_authority_path():
    claims = FCClaims(
        run_id="mode-contract-run", audit_hash="b" * 64, deterministic_result_hash="1" * 64,
        proposal_ids=(), proposal_hashes=(), accepted_proposal_ids=(), decision_count=0,
        **_consistency_fields((), (), agent_context=False),
    )
    reference = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v3",
        artifact_id="fc", claims=claims, ordinal=0,
    )
    record = finalize_execution(_execution_request("deterministic", (reference,)))
    payload = record.model_dump()
    payload["authority_path"] = "caller_supplied_path"
    with pytest.raises(ValidationError, match="fixed engine-mode authority path"):
        KernelModeExecutionRecord.model_validate(payload)


def test_hybrid_replay_claims_bind_stored_only_engine_execution():
    references = _hybrid_references()
    mismatched = _replace_mode_claims(
        references[-1], references[-1].claims.model_copy(update={"engine_mode": "hybrid_recorded"})
    )
    with pytest.raises(KernelModeFinalizationError, match="Replay claims"):
        finalize_execution(_execution_request("hybrid", (*references[:-1], mismatched)))
    with pytest.raises(ValidationError, match="provider_calls_required"):
        references[-1].claims.model_copy(update={"provider_calls_required": 0.0})


def test_mode_proof_boundary_is_strict_without_coercion():
    digest = "a" * 64
    with pytest.raises(ValidationError, match="int_type"):
        FCClaims(
            run_id="mode-contract-run", audit_hash=digest, deterministic_result_hash=digest,
            proposal_ids=(), proposal_hashes=(), accepted_proposal_ids=(), decision_count=0.0,
            **_consistency_fields((), (), agent_context=False),
        )
    with pytest.raises(ValidationError, match="bool_type"):
        NDClaims(
            run_id="mode-contract-run", session_id="session-1", tick=1, attempted=0,
            input_proposal_ids=(), input_proposal_hashes=(), narrative_diffusion_audit_hash=digest,
            diffusion_request_hash=digest, before_result_hash=digest, after_result_hash=digest,
            tone_delta_tuples=(("firm", 30000), ("informational", -10000), ("stabilizing", -40000)),
            country_delta_tuples=(), application_tuples=(), application_count=0,
            diffusion_evidence_hash=digest,
        )
    with pytest.raises(ValidationError, match="int_type"):
        _reference().model_copy(update={"ordinal": 0.0})
    request = _execution_request("deterministic", (_reference(),))
    with pytest.raises(ValidationError, match="int_type"):
        request.model_copy(update={"effective_seed": 17.0})


def test_nd_unattempted_claims_are_empty_numeric_noops():
    digest = "a" * 64
    with pytest.raises(ValidationError, match="application_count|empty numeric no-op"):
        NDClaims(
            run_id="mode-contract-run", session_id="session-1", tick=1, attempted=False,
            input_proposal_ids=(), input_proposal_hashes=(), narrative_diffusion_audit_hash=digest,
            diffusion_request_hash=digest, application_count=0,
            tone_delta_tuples=(("firm", 30000), ("informational", -10000), ("stabilizing", -40000)),
            country_delta_tuples=(), application_tuples=(), before_result_hash=digest,
            after_result_hash="b" * 64, diffusion_evidence_hash=digest,
        )
    with pytest.raises(ValidationError, match="application_count|empty numeric no-op"):
        NDClaims(
            run_id="mode-contract-run", session_id="session-1", tick=1, attempted=False,
            input_proposal_ids=(), input_proposal_hashes=(), narrative_diffusion_audit_hash=digest,
            diffusion_request_hash=digest, application_count=1,
            tone_delta_tuples=(("firm", 30000), ("informational", -10000), ("stabilizing", -40000)),
            country_delta_tuples=(), application_tuples=(), before_result_hash=digest,
            after_result_hash=digest, diffusion_evidence_hash=digest,
        )


def test_negotiation_admits_diffusion_only_and_accepted_only_projected_ticks():
    accepted_only = _negotiation_references(accepted_ticks=(2,))
    diffusion_only = _negotiation_references(diffusion_ticks=(4,))

    assert accepted_only[34].claims.attempted is False
    assert finalize_execution(_execution_request("negotiation", accepted_only)).kernel_mode == "negotiation"
    assert finalize_execution(_execution_request("negotiation", diffusion_only)).kernel_mode == "negotiation"


def test_negotiation_recomputes_eligibility_instead_of_trusting_local_hashes():
    references = list(_negotiation_references(accepted_ticks=(1,)))
    proposal = references[6].claims
    source = list(proposal.proposal_claim_tuples[0])
    source[5] = "audit_only"
    mutated_source = tuple(source)
    mutated_proposal = proposal.model_copy(update={"proposal_claim_tuples": (mutated_source,)})
    references[6] = _replace_mode_claims(references[6], mutated_proposal)

    eligibility = references[24].claims
    decision_hash = stable_hash({"decision": [mutated_source, False, "eligible"]})
    eligibility_hash = stable_hash({
        "schema_version": "negotiation-eligibility.v1",
        "run_id": eligibility.run_id,
        "session_id": eligibility.session_id,
        "tick": eligibility.tick,
        "decision_hashes": (decision_hash,),
        "eligible_proposal_ids": eligibility.eligible_proposal_ids,
    })
    references[24] = _replace_mode_claims(
        references[24],
        eligibility.model_copy(update={
            "decision_tuples": ((mutated_source, False, "eligible", decision_hash),),
            "eligibility_hash": eligibility_hash,
        }),
    )
    references[0] = _replace_mode_claims(
        references[0], references[0].claims.model_copy(update={"eligibility_hash": eligibility_hash})
    )
    with pytest.raises(KernelModeFinalizationError, match="eligibility precedence"):
        finalize_execution(_execution_request("negotiation", tuple(references)))


def test_np_cl_and_nd_claims_fail_closed_on_invalid_structural_evidence():
    digest = "a" * 64
    current_source = (
        "proposal-1", digest, "message-1", digest, "diplomatic_signal",
        "deterministic_modifier", digest, "current_message", None, 1, digest,
    )
    with pytest.raises(ValidationError, match="current-message NP source coordinates"):
        NPClaims(
            run_id="mode-contract-run", session_id="session-1", tick=2,
            source_hashes=(digest, digest, digest), proposal_claim_tuples=(current_source,),
            proposal_count=1, batch_hash=digest,
        )
    with pytest.raises(ValidationError, match="exactly two parties"):
        CLClaims(
            run_id="mode-contract-run", session_id="session-1", tick=2,
            ledger_hash=digest, ledger_entry_count=1,
            commitments=((
                "commitment-1", digest, "active", "alliance_request", ("agent-a",),
                digest, "proposal-1", digest, "message-1", digest, 1, digest,
            ),),
        )
    with pytest.raises(ValidationError, match="fixed Q=10000"):
        NDClaims(
            run_id="mode-contract-run", session_id="session-1", tick=1, attempted=False,
            input_proposal_ids=(), input_proposal_hashes=(),
            narrative_diffusion_audit_hash=digest, diffusion_request_hash=digest,
            before_result_hash=digest, after_result_hash=digest,
            tone_delta_tuples=(("firm", 3), ("informational", -1), ("stabilizing", -4)),
            country_delta_tuples=(), application_tuples=(), application_count=0,
            diffusion_evidence_hash=digest,
        )


@pytest.mark.parametrize("reference_index", [30, 37])
def test_negotiation_rejects_supersedes_on_final_or_replay_proofs(reference_index):
    references = list(_negotiation_references())
    references[reference_index] = _append_supersedes(references[reference_index])
    request = _execution_request("negotiation", tuple(references))
    with pytest.raises(KernelModeFinalizationError, match="ticked negotiation"):
        finalize_execution(request)


def test_negotiation_retry_requires_complete_supersession_prefix():
    references = list(_negotiation_references())
    references[0] = _append_supersedes(references[0])
    with pytest.raises(KernelModeFinalizationError, match="every re-emitted completed retry proof"):
        finalize_execution(_execution_request("negotiation", tuple(references)))

    valid = _execution_request(
        "negotiation", _supersede_retry_tick(_negotiation_references(), 1)
    )
    assert finalize_execution(valid).kernel_mode == "negotiation"

    unlisted = list(_negotiation_references())
    unlisted[1] = _append_supersedes(unlisted[1])
    with pytest.raises(
        KernelModeFinalizationError,
        match="every re-emitted completed retry proof",
    ):
        finalize_execution(_execution_request("negotiation", tuple(unlisted)))

    same_attempt = list(_negotiation_references())
    same_attempt[0] = _append_supersedes(same_attempt[0], target_attempt="attempt-1")
    same_attempt_request = _execution_request("negotiation", tuple(same_attempt))
    with pytest.raises(KernelModeFinalizationError, match="differ from the current"):
        finalize_execution(same_attempt_request)
    invalid_origin_payload = valid.model_dump(mode="json")
    invalid_origin_payload["retry_origin_attempt_ids"] = ("attempt-1",)
    with pytest.raises(ValidationError, match="Extra inputs"):
        KernelModeExecutionRequest.model_validate(invalid_origin_payload)


def test_negotiation_retry_rejects_missing_projected_tick_supersedes_and_nonprefix_context():
    fully_superseded = _supersede_retry_tick(_negotiation_references((1,)), 1)
    request = _execution_request("negotiation", fully_superseded)
    assert finalize_execution(request).kernel_mode == "negotiation"

    for token in ("PC", "CL", "PA"):
        incomplete = tuple(
            reference.model_copy(update={"relationships": reference.relationships[:-1]})
            if reference.tick == 1 and reference.token == token
            else reference
            for reference in fully_superseded
        )
        with pytest.raises(KernelModeFinalizationError, match="every re-emitted completed retry proof"):
            finalize_execution(_execution_request("negotiation", incomplete))

    nonprefix = _supersede_retry_tick(
        _supersede_retry_tick(_negotiation_references(), 1),
        3,
    )
    with pytest.raises(KernelModeFinalizationError, match="contiguous retry prefix"):
        finalize_execution(_execution_request("negotiation", nonprefix))
