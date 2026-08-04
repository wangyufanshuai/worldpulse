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
    finalize_execution,
    normalize_kernel_mode,
)
from app.services.simulation_kernel.mode_contracts import (
    ACClaims,
    CLClaims,
    HRClaims,
    MBClaims,
    NDClaims,
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


def _reference() -> KernelModeProofReference:
    claims = FCClaims(
        run_id="mode-contract-run",
        audit_hash="b" * 64,
        deterministic_result_hash="c" * 64,
        proposal_ids=(),
        accepted_proposal_ids=(),
        decision_count=0,
    )
    claims_hash = stable_hash({"claims": claims.model_dump(mode="json"), "proof_schema": "kp.final-consistency.v1"})
    return KernelModeProofReference(
        proof_schema="kp.final-consistency.v1",
        artifact_type="consistency_audit",
        schema_version="consistency-audit.v2",
        artifact_id="artifact-final-consistency",
        run_id="mode-contract-run",
        attempt="attempt-1",
        ordinal=0,
        artifact_sha256="d" * 64,
        content_hash="e" * 64,
        claims=claims,
        claims_hash=claims_hash,
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
            accepted_proposal_ids=(),
            decision_count=0,
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
    projection = _projection()
    reference = _reference()
    proof_hash = stable_hash(
        {"references": [reference.model_dump(mode="json")], "schema_version": "kernel-mode-execution-proof.v1"}
    )
    proof = KernelModeExecutionProof(references=(reference,), proof_hash=proof_hash)
    request = KernelModeExecutionRequest(
        engine_mode="deterministic",
        kernel_mode="deterministic",
        run_id="mode-contract-run",
        attempt="attempt-1",
        effective_seed=17,
        rule_pack_hash="a" * 64,
        baseline=projection,
        final=projection,
        proof=proof,
    )
    assert request.baseline.world_state_hash == request.final.world_state_hash
    with pytest.raises(ValidationError, match="projection seed"):
        request.model_copy(update={"effective_seed": 18})


def _mode_reference(*, proof_schema: str, artifact_type: str, schema_version: str, artifact_id: str, claims, ordinal: int, relationships=(), tick=None):
    return KernelModeProofReference(
        proof_schema=proof_schema,
        artifact_type=artifact_type,
        schema_version=schema_version,
        artifact_id=artifact_id,
        run_id="mode-contract-run",
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
    final: WarRoomProjection | None = None,
) -> KernelModeExecutionRequest:
    proof = KernelModeExecutionProof(
        references=references,
        proof_hash=stable_hash(
            {"references": [reference.model_dump(mode="json") for reference in references], "schema_version": "kernel-mode-execution-proof.v1"}
        ),
    )
    return KernelModeExecutionRequest(
        engine_mode=engine_mode,
        kernel_mode=normalize_kernel_mode(engine_mode),
        run_id="mode-contract-run",
        attempt="attempt-1",
        effective_seed=17,
        rule_pack_hash="a" * 64,
        baseline=_projection(),
        final=final or _projection(),
        proof=proof,
    )


def _audit_references(engine_mode: str, proposal_ids: tuple[str, ...] = ()) -> tuple[KernelModeProofReference, ...]:
    runtime_hash = "3" * 64
    batch_hash = "4" * 64
    proposal_hashes = tuple("5" * 64 for _ in proposal_ids)
    references: list[KernelModeProofReference] = []
    if engine_mode == "controlled_agent":
        ar_claims = ARClaims(
            run_id="mode-contract-run", runtime_hash=runtime_hash, proposal_ids=proposal_ids,
            proposal_count=len(proposal_ids), invocation_ids=(), invocation_count=0,
        )
        references.append(_mode_reference(
            proof_schema="kp.agent-runtime.v1", artifact_type="agent_runtime_audit", schema_version="agent-runtime-result.v1",
            artifact_id="ar", claims=ar_claims, ordinal=0,
        ))
    pb_claims = PBClaims(
        run_id="mode-contract-run", source_kind=engine_mode, batch_hash=(batch_hash if engine_mode == "mock_agent" else None),
        runtime_hash=(runtime_hash if engine_mode == "controlled_agent" else None), proposal_ids=proposal_ids,
        proposal_hashes=proposal_hashes, proposal_count=len(proposal_ids),
    )
    pb_relationships = () if engine_mode == "mock_agent" else (
        KernelModeProofRelationship(
            relationship_type="generated_by", target_artifact_id="ar", target_content_hash=references[0].content_hash,
        ),
    )
    pb = _mode_reference(
        proof_schema="kp.proposal-batch.v1", artifact_type="agent_action_proposals",
        schema_version=("mock-agent-batch.v1" if engine_mode == "mock_agent" else "agent-action-batch.v1"),
        artifact_id="pb", claims=pb_claims, ordinal=len(references), relationships=pb_relationships,
    )
    references.append(pb)
    fc_claims = FCClaims(
        run_id="mode-contract-run", audit_hash="6" * 64, deterministic_result_hash="1" * 64,
        proposal_ids=proposal_ids, accepted_proposal_ids=(), decision_count=len(proposal_ids),
    )
    fc = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
        artifact_id="fc", claims=fc_claims, ordinal=len(references), relationships=(
            KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id="pb", target_content_hash=pb.content_hash),
        ),
    )
    references.append(fc)
    if proposal_ids:
        pa_claims = PAClaims(
            run_id="mode-contract-run", projection_mode="audit_only", audit_hash="7" * 64, consistency_audit_hash=fc_claims.audit_hash,
            proposal_ids=proposal_ids, projected_proposal_ids=(), modifier_tuples=(), modifier_count=0,
            record_count=len(proposal_ids), before_result_hash="1" * 64, final_result_hash="1" * 64,
        )
        references.append(_mode_reference(
            proof_schema="kp.projection-audit.v1", artifact_type="agent_action_projection_audit",
            schema_version="agent-action-projection-audit.v1", artifact_id="pa", claims=pa_claims, ordinal=len(references),
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
    modifiers = tuple(
        ModifierReference(proposal_id=item, modifier_id=f"modifier-{item}", modifier_hash="a" * 64)
        for item in accepted_ids
    )
    ar = _mode_reference(
        proof_schema="kp.agent-runtime.v1", artifact_type="agent_runtime_audit", schema_version="agent-runtime-result.v1",
        artifact_id="ar", ordinal=0,
        claims=ARClaims(
            run_id="mode-contract-run", runtime_hash=runtime_hash, proposal_ids=proposal_ids,
            proposal_count=len(proposal_ids), invocation_ids=(), invocation_count=0,
        ),
    )
    pb = _mode_reference(
        proof_schema="kp.proposal-batch.v1", artifact_type="agent_action_proposals", schema_version="agent-action-batch.v1",
        artifact_id="pb", ordinal=1,
        claims=PBClaims(
            run_id="mode-contract-run", source_kind="controlled_agent", runtime_hash=runtime_hash,
            proposal_ids=proposal_ids, proposal_hashes=tuple("5" * 64 for _ in proposal_ids), proposal_count=len(proposal_ids),
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="generated_by", target_artifact_id=ar.artifact_id, target_content_hash=ar.content_hash),
        ),
    )
    fc = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
        artifact_id="fc", ordinal=2,
        claims=FCClaims(
            run_id="mode-contract-run", audit_hash=audit_hash, deterministic_result_hash="1" * 64,
            proposal_ids=proposal_ids, accepted_proposal_ids=accepted_ids, decision_count=len(proposal_ids),
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=pb.artifact_id, target_content_hash=pb.content_hash),
        ),
    )
    mb = _mode_reference(
        proof_schema="kp.action-modifier-bundle.v1", artifact_type="deterministic_action_modifiers",
        schema_version="hybrid-modifier-bundle.v1", artifact_id="mb", ordinal=3,
        claims=MBClaims(
            run_id="mode-contract-run", bundle_hash=bundle_hash, consistency_audit_hash=audit_hash,
            accepted_proposal_ids=accepted_ids, modifier_tuples=modifiers, modifier_count=len(modifiers),
        ),
        relationships=(
            KernelModeProofRelationship(relationship_type="maps", target_artifact_id=pb.artifact_id, target_content_hash=pb.content_hash),
            KernelModeProofRelationship(relationship_type="admitted_by", target_artifact_id=fc.artifact_id, target_content_hash=fc.content_hash),
        ),
    )
    cl = _mode_reference(
        proof_schema="kp.commitment-ledger.v1", artifact_type="commitment_ledger", schema_version="commitment-ledger.v1",
        artifact_id="cl", ordinal=4,
        claims=CLClaims(run_id="mode-contract-run", ledger_hash=stable_hash({"commitments": []}), ledger_entry_count=0),
        relationships=(
            KernelModeProofRelationship(relationship_type="ledger_for", target_artifact_id=mb.artifact_id, target_content_hash=mb.content_hash),
        ),
    )
    pa = _mode_reference(
        proof_schema="kp.projection-audit.v1", artifact_type="agent_action_projection_audit",
        schema_version="agent-action-projection-audit.v1", artifact_id="pa", ordinal=5,
        claims=PAClaims(
            run_id="mode-contract-run", projection_mode="hybrid", audit_hash=projection_audit_hash,
            consistency_audit_hash=audit_hash, modifier_bundle_hash=bundle_hash, proposal_ids=proposal_ids,
            projected_proposal_ids=accepted_ids, modifier_tuples=modifiers, modifier_count=len(modifiers),
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
        proof_schema="kp.hybrid-replay.v1", artifact_type="hybrid_replay_record", schema_version="hybrid-replay-record.v1",
        artifact_id="hr", ordinal=6,
        claims=HRClaims(
            run_id="mode-contract-run", engine_mode=engine_mode, replay_source_kind="stored_only", provider_calls_required=0,
            replay_hash="b" * 64, baseline_result_hash="1" * 64,
            final_result_hash=final_result_hash, full_source_run_hash="1" * 64, consistency_audit_hash=audit_hash,
            modifier_bundle_hash=bundle_hash, projection_audit_hash=projection_audit_hash,
            ledger_hash=stable_hash({"commitments": []}), accepted_proposal_ids=accepted_ids,
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
    """Build a complete ADR-0007 proof with optional numeric no-op projections."""

    def digest(name: str) -> str:
        return stable_hash({"negotiation-test": name})

    projected_ticks = tuple(sorted(set(accepted_ticks) | set(diffusion_ticks)))
    rounds: list[KernelModeProofReference] = []
    admissions: list[KernelModeProofReference] = []
    projections: dict[int, KernelModeProofReference] = {}
    modifiers: dict[int, KernelModeProofReference] = {}
    diffusions: list[KernelModeProofReference] = []
    ledgers: list[KernelModeProofReference] = []
    audits: dict[int, KernelModeProofReference] = {}
    for tick in range(1, 7):
        projected = tick in projected_ticks
        proposal_ids = (f"proposal-{tick}",) if tick in accepted_ticks else ()
        accepted_ids = proposal_ids
        before = "1" * 64
        after = "1" * 64
        rr = _mode_reference(
            proof_schema="kp.negotiation-round.v1", artifact_type="negotiation_round", schema_version="negotiation-round.v1",
            artifact_id=f"rr-{tick}", ordinal=tick - 1, tick=tick,
            claims=RRClaims(
                run_id="mode-contract-run", session_id="session-1", round_id=f"round-{tick}", tick=tick,
                input_hash=digest(f"input-{tick}"), output_hash=digest(f"output-{tick}"), before_result_hash=before,
                after_result_hash=after, proposal_ids=proposal_ids, accepted_proposal_ids=accepted_ids,
                admission_audit_hash=digest(f"ac-{tick}"), projection_consistency_hash=(digest(f"pc-{tick}") if projected else None),
                modifier_bundle_hash=(digest(f"mb-{tick}") if projected else None), diffusion_hash=digest(f"nd-{tick}"),
                ledger_hash=digest(f"cl-{tick}"), projection_audit_hash=(digest(f"pa-{tick}") if projected else None),
                no_projection_reason=(None if projected else "no_projection"),
            ),
            relationships=(() if tick == 1 else (
                KernelModeProofRelationship(relationship_type="previous_round", target_artifact_id=rounds[-1].artifact_id, target_content_hash=rounds[-1].content_hash),
            )),
        )
        rounds.append(rr)
    for tick, rr in enumerate(rounds, start=1):
        proposal_ids = (f"proposal-{tick}",) if tick in accepted_ticks else ()
        ac = _mode_reference(
            proof_schema="kp.negotiation-admission-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
            artifact_id=f"ac-{tick}", ordinal=6 + tick - 1, tick=tick,
            claims=ACClaims(run_id="mode-contract-run", tick=tick, audit_hash=digest(f"ac-{tick}"), deterministic_result_hash="1" * 64,
                            proposal_ids=proposal_ids, accepted_proposal_ids=proposal_ids, decision_count=len(proposal_ids)),
            relationships=(KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),),
        )
        admissions.append(ac)
    ordinal = 12
    for tick in projected_ticks:
        rr, ac = rounds[tick - 1], admissions[tick - 1]
        proposal_ids = (f"proposal-{tick}",) if tick in accepted_ticks else ()
        projections[tick] = _mode_reference(
            proof_schema="kp.negotiation-projection-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
            artifact_id=f"pc-{tick}", ordinal=ordinal, tick=tick,
            claims=PCClaims(run_id="mode-contract-run", tick=tick, audit_hash=digest(f"pc-{tick}"), deterministic_result_hash="1" * 64,
                            candidate_proposal_ids=proposal_ids, accepted_proposal_ids=proposal_ids, decision_count=len(proposal_ids)),
            relationships=(
                KernelModeProofRelationship(relationship_type="filters", target_artifact_id=ac.artifact_id, target_content_hash=ac.content_hash),
                KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),
            ),
        )
        ordinal += 1
    final_audit = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
        artifact_id="fc", ordinal=ordinal,
        claims=FCClaims(run_id="mode-contract-run", audit_hash=digest("fc"), deterministic_result_hash="1" * 64,
                        proposal_ids=(("proposal-6",) if 6 in accepted_ticks else ()),
                        accepted_proposal_ids=(("proposal-6",) if 6 in accepted_ticks else ()), decision_count=(1 if 6 in accepted_ticks else 0)),
        relationships=(KernelModeProofRelationship(relationship_type="evaluates", target_artifact_id=rounds[-1].artifact_id, target_content_hash=rounds[-1].content_hash),),
    )
    ordinal += 1
    for tick in projected_ticks:
        rr, pc = rounds[tick - 1], projections[tick]
        modifiers[tick] = _mode_reference(
            proof_schema="kp.action-modifier-bundle.v1", artifact_type="deterministic_action_modifiers", schema_version="hybrid-modifier-bundle.v1",
            artifact_id=f"mb-{tick}", ordinal=ordinal, tick=tick,
            claims=MBClaims(run_id="mode-contract-run", tick=tick, bundle_hash=digest(f"mb-{tick}"), consistency_audit_hash=digest(f"pc-{tick}"),
                            accepted_proposal_ids=((f"proposal-{tick}",) if tick in accepted_ticks else ()), modifier_tuples=(), modifier_count=0),
            relationships=(
                KernelModeProofRelationship(relationship_type="maps", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),
                KernelModeProofRelationship(relationship_type="admitted_by", target_artifact_id=pc.artifact_id, target_content_hash=pc.content_hash),
            ),
        )
        ordinal += 1
    for tick, rr in enumerate(rounds, start=1):
        projected = tick in projected_ticks
        nd = _mode_reference(
            proof_schema="kp.narrative-diffusion.v1", artifact_type="narrative_diffusion", schema_version="narrative-diffusion.v1",
            artifact_id=f"nd-{tick}", ordinal=ordinal, tick=tick,
            claims=NDClaims(run_id="mode-contract-run", tick=tick, attempted=tick in diffusion_ticks, diffusion_hash=digest(f"nd-{tick}"),
                            application_count=0, proposal_ids=(), before_result_hash="1" * 64, after_result_hash="1" * 64),
            relationships=(KernelModeProofRelationship(
                relationship_type=("bounded_by" if projected else "no_projection_for"),
                target_artifact_id=(modifiers[tick].artifact_id if projected else rr.artifact_id),
                target_content_hash=(modifiers[tick].content_hash if projected else rr.content_hash),
            ),),
        )
        diffusions.append(nd)
        ordinal += 1
    for tick, rr in enumerate(rounds, start=1):
        ledgers.append(_mode_reference(
            proof_schema="kp.commitment-ledger.v1", artifact_type="commitment_ledger", schema_version="commitment-ledger.v1",
            artifact_id=f"cl-{tick}", ordinal=ordinal, tick=tick,
            claims=CLClaims(run_id="mode-contract-run", tick=tick, ledger_hash=digest(f"cl-{tick}"), ledger_entry_count=0),
            relationships=(KernelModeProofRelationship(relationship_type="snapshot_for", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),),
        ))
        ordinal += 1
    for tick in projected_ticks:
        rr, pc, mb, nd, cl = rounds[tick - 1], projections[tick], modifiers[tick], diffusions[tick - 1], ledgers[tick - 1]
        audits[tick] = _mode_reference(
            proof_schema="kp.projection-audit.v1", artifact_type="negotiation_projection_audit", schema_version="agent-action-projection-audit.v1",
            artifact_id=f"pa-{tick}", ordinal=ordinal, tick=tick,
            claims=PAClaims(run_id="mode-contract-run", tick=tick, projection_mode="negotiation", audit_hash=digest(f"pa-{tick}"),
                            consistency_audit_hash=digest(f"pc-{tick}"), modifier_bundle_hash=digest(f"mb-{tick}"),
                            proposal_ids=((f"proposal-{tick}",) if tick in accepted_ticks else ()),
                            projected_proposal_ids=((f"proposal-{tick}",) if tick in accepted_ticks else ()), modifier_tuples=(), modifier_count=0,
                            record_count=(1 if tick in accepted_ticks else 0), before_result_hash="1" * 64, final_result_hash="1" * 64),
            relationships=(
                KernelModeProofRelationship(relationship_type="round", target_artifact_id=rr.artifact_id, target_content_hash=rr.content_hash),
                KernelModeProofRelationship(relationship_type="governed_by", target_artifact_id=pc.artifact_id, target_content_hash=pc.content_hash),
                KernelModeProofRelationship(relationship_type="audits", target_artifact_id=mb.artifact_id, target_content_hash=mb.content_hash),
                KernelModeProofRelationship(relationship_type="diffusion", target_artifact_id=nd.artifact_id, target_content_hash=nd.content_hash),
                KernelModeProofRelationship(relationship_type="ledger_snapshot", target_artifact_id=cl.artifact_id, target_content_hash=cl.content_hash),
            ),
        )
        ordinal += 1
    nr_targets = (
        tuple(("replays", item) for item in rounds) + tuple(("admission", item) for item in admissions)
        + (("final_audit", final_audit),) + tuple(("projection", projections[tick]) for tick in projected_ticks)
        + tuple(("modifiers", modifiers[tick]) for tick in projected_ticks) + tuple(("diffusion", item) for item in diffusions)
        + tuple(("ledgers", item) for item in ledgers) + tuple(("audits", audits[tick]) for tick in projected_ticks)
    )
    nr = _mode_reference(
        proof_schema="kp.negotiation-replay.v1", artifact_type="negotiation_replay", schema_version="negotiation-replay.v1",
        artifact_id="nr", ordinal=ordinal,
        claims=NRClaims(run_id="mode-contract-run", session_id="session-1", replay_hash=digest("nr"), baseline_result_hash="1" * 64,
                        final_result_hash="1" * 64, round_hashes=tuple(item.claims.output_hash for item in rounds),
                        admission_audit_hashes=tuple(item.claims.audit_hash for item in admissions),
                        projection_consistency_hashes=tuple(item.claims.projection_consistency_hash for item in rounds),
                        diffusion_hashes=tuple(item.claims.diffusion_hash for item in diffusions), ledger_hashes=tuple(item.claims.ledger_hash for item in ledgers),
                        projection_audit_hashes=tuple(item.claims.projection_audit_hash for item in rounds), message_chain_head=digest("messages")),
        relationships=tuple(KernelModeProofRelationship(relationship_type=kind, target_artifact_id=target.artifact_id, target_content_hash=target.content_hash) for kind, target in nr_targets),
    )
    return (*rounds, *admissions, *(projections[tick] for tick in projected_ticks), final_audit, *(modifiers[tick] for tick in projected_ticks), *diffusions, *ledgers, *(audits[tick] for tick in projected_ticks), nr)


@pytest.mark.parametrize("engine_mode", ["deterministic", "mock_agent", "controlled_agent"])
def test_finalization_admits_exact_deterministic_mode_sequences_without_mutation(engine_mode):
    if engine_mode == "deterministic":
        claims = FCClaims(
            run_id="mode-contract-run", audit_hash="6" * 64, deterministic_result_hash="1" * 64,
            proposal_ids=(), accepted_proposal_ids=(), decision_count=0,
        )
        references = (_mode_reference(
            proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
            artifact_id="fc", claims=claims, ordinal=0,
        ),)
    else:
        references = _audit_references(engine_mode, ("proposal-1",))
    request = _execution_request(engine_mode, references)
    before = request.model_dump(mode="json")

    first = finalize_execution(request)
    second = finalize_execution(request)

    assert first == second
    assert first.authority_path == ("deterministic_rule_engine", "consistency_evaluator", "simulation_kernel")
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
    assert first.authority_path == ("deterministic_rule_engine", "consistency_evaluator", "simulation_kernel")


@pytest.mark.parametrize("projected_ticks", [(), (2, 5)])
def test_finalization_admits_negotiation_six_tick_chains(projected_ticks):
    references = _negotiation_references(projected_ticks)
    record = finalize_execution(_execution_request("negotiation", references))

    assert len(references) == 26 + 3 * len(projected_ticks)
    assert record.authority_path == (
        "deterministic_rule_engine",
        "consistency_evaluator",
        "negotiation_engine",
        "simulation_kernel",
    )


def test_negotiation_rejects_surplus_projection():
    references = _negotiation_references()
    surplus = _negotiation_references((1,))
    malformed = tuple(
        reference.model_copy(update={"ordinal": ordinal})
        for ordinal, reference in enumerate((*references[:12], surplus[12], *references[12:]))
    )
    with pytest.raises(KernelModeFinalizationError, match="ordinal|projection ticks|count|sequence"):
        finalize_execution(_execution_request("negotiation", malformed))


def test_negotiation_rejects_wrong_p_derivation_modifier_replay_and_cross_attempt():
    no_projection = list(_negotiation_references())
    no_projection[13] = _replace_mode_claims(
        no_projection[13], no_projection[13].claims.model_copy(update={"attempted": True})
    )
    with pytest.raises(KernelModeFinalizationError, match="projection ticks"):
        finalize_execution(_execution_request("negotiation", tuple(no_projection)))

    projected = list(_negotiation_references((1,)))
    projected[27] = _replace_mode_claims(
        projected[27], projected[27].claims.model_copy(update={"modifier_tuples": (
            ModifierReference(proposal_id="proposal-1", modifier_id="mismatch", modifier_hash="f" * 64),
        ), "modifier_count": 1})
    )
    with pytest.raises(KernelModeFinalizationError, match="projected negotiation tick claims"):
        finalize_execution(_execution_request("negotiation", tuple(projected)))

    with pytest.raises(ValidationError, match="provider_calls_required"):
        NRClaims(
            run_id="mode-contract-run", session_id="session-1", replay_hash="a" * 64,
            baseline_result_hash="1" * 64, final_result_hash="1" * 64,
            round_hashes=("a" * 64,) * 6, admission_audit_hashes=("b" * 64,) * 6,
            projection_consistency_hashes=(None,) * 6, diffusion_hashes=("c" * 64,) * 6,
            ledger_hashes=("d" * 64,) * 6, projection_audit_hashes=(None,) * 6,
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
        proof_schema="kp.commitment-ledger.v1", artifact_type="commitment_ledger", schema_version="commitment-ledger.v1",
        artifact_id="cl", ordinal=4,
        claims=CLClaims(run_id="mode-contract-run", ledger_hash="c" * 64, ledger_entry_count=1, commitments=(
            {"commitment_id": "commitment-1", "commitment_hash": "d" * 64, "status": "open"},
        )),
        relationships=references[4].relationships,
    )
    with pytest.raises(KernelModeFinalizationError, match="empty ledger"):
        finalize_execution(_execution_request("hybrid", (*references[:4], nonempty_ledger, *references[5:])))

    mismatched_pa = _mode_reference(
        proof_schema="kp.projection-audit.v1", artifact_type="agent_action_projection_audit",
        schema_version="agent-action-projection-audit.v1", artifact_id="pa", ordinal=5,
        claims=references[5].claims.model_copy(update={"modifier_tuples": (), "modifier_count": 0}),
        relationships=references[5].relationships,
    )
    mismatched_hr = _mode_reference(
        proof_schema="kp.hybrid-replay.v1", artifact_type="hybrid_replay_record", schema_version="hybrid-replay-record.v1",
        artifact_id="hr", ordinal=6, claims=references[6].claims,
        relationships=(*references[6].relationships[:-1], KernelModeProofRelationship(
            relationship_type="audit", target_artifact_id=mismatched_pa.artifact_id, target_content_hash=mismatched_pa.content_hash,
        )),
    )
    with pytest.raises(KernelModeFinalizationError, match="Projection Audit claims"):
        finalize_execution(_execution_request("hybrid", (*references[:5], mismatched_pa, mismatched_hr)))


def test_hybrid_finalization_rejects_bad_hash_relationship_cross_attempt_and_numeric_owner():
    references = _hybrid_references()
    bad_hr = _mode_reference(
        proof_schema="kp.hybrid-replay.v1", artifact_type="hybrid_replay_record", schema_version="hybrid-replay-record.v1",
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
        finalize_execution(_execution_request("hybrid", _hybrid_references((), ()), final=invalid_projection).model_copy(
            update={"baseline": invalid_projection}
        ))


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
    deterministic_request = _execution_request("mock_agent", arbitrary_audit_proof).model_copy(
        update={"engine_mode": "deterministic", "kernel_mode": "deterministic"}
    )
    with pytest.raises(KernelModeFinalizationError, match="sequence"):
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
        if reference.tick == tick and reference.token in {"RR", "AC", "PC", "MB", "ND", "CL", "PA"}
        else reference
        for reference in references
    )


def _proof_for(references: tuple[KernelModeProofReference, ...]) -> KernelModeExecutionProof:
    return KernelModeExecutionProof(
        references=references,
        proof_hash=stable_hash({
            "references": [reference.model_dump(mode="json") for reference in references],
            "schema_version": "kernel-mode-execution-proof.v1",
        }),
    )


def test_execution_record_requires_fixed_authority_path():
    claims = FCClaims(
        run_id="mode-contract-run", audit_hash="b" * 64, deterministic_result_hash="1" * 64,
        proposal_ids=(), accepted_proposal_ids=(), decision_count=0,
    )
    reference = _mode_reference(
        proof_schema="kp.final-consistency.v1", artifact_type="consistency_audit", schema_version="consistency-audit.v2",
        artifact_id="fc", claims=claims, ordinal=0,
    )
    record = finalize_execution(_execution_request("deterministic", (reference,)))
    payload = record.model_dump()
    payload["authority_path"] = ("caller", "supplied", "path")
    with pytest.raises(ValidationError, match="fixed Kernel mode authority path"):
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
            decision_count=0.0,
        )
    with pytest.raises(ValidationError, match="bool_type"):
        NDClaims(
            run_id="mode-contract-run", tick=1, attempted=0, diffusion_hash=digest,
            application_count=0, before_result_hash=digest, after_result_hash=digest,
        )
    with pytest.raises(ValidationError, match="int_type"):
        _reference().model_copy(update={"ordinal": 0.0})
    request = _execution_request("deterministic", (_reference(),))
    with pytest.raises(ValidationError, match="int_type"):
        request.model_copy(update={"effective_seed": 17.0})


def test_nd_unattempted_claims_are_empty_numeric_noops():
    digest = "a" * 64
    with pytest.raises(ValidationError, match="empty numeric no-op"):
        NDClaims(
            run_id="mode-contract-run", tick=1, attempted=False, diffusion_hash=digest,
            application_count=0, before_result_hash=digest, after_result_hash="b" * 64,
        )
    with pytest.raises(ValidationError, match="empty numeric no-op"):
        NDClaims(
            run_id="mode-contract-run", tick=1, attempted=False, diffusion_hash=digest,
            application_count=1, proposal_ids=("proposal-1",), before_result_hash=digest, after_result_hash=digest,
        )


def test_negotiation_admits_diffusion_only_and_accepted_only_projected_ticks():
    accepted_only = _negotiation_references(accepted_ticks=(2,))
    diffusion_only = _negotiation_references(diffusion_ticks=(4,))

    assert accepted_only[15].claims.attempted is False
    assert finalize_execution(_execution_request("negotiation", accepted_only)).kernel_mode == "negotiation"
    assert finalize_execution(_execution_request("negotiation", diffusion_only)).kernel_mode == "negotiation"


@pytest.mark.parametrize("reference_index", [12, 25])
def test_negotiation_rejects_supersedes_on_final_or_replay_proofs(reference_index):
    references = list(_negotiation_references())
    references[reference_index] = _append_supersedes(references[reference_index])
    request = _execution_request("negotiation", tuple(references)).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    with pytest.raises(KernelModeFinalizationError, match="ticked negotiation"):
        finalize_execution(request)


def test_negotiation_retry_requires_complete_supersession_prefix():
    no_supersedes = _execution_request("negotiation", _negotiation_references()).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    with pytest.raises(KernelModeFinalizationError, match="every re-emitted completed retry proof"):
        finalize_execution(no_supersedes)

    references = list(_negotiation_references())
    references[0] = _append_supersedes(references[0])
    with pytest.raises(KernelModeFinalizationError, match="closed negotiation retry context"):
        finalize_execution(_execution_request("negotiation", tuple(references)))

    partial = _execution_request("negotiation", tuple(references)).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    with pytest.raises(KernelModeFinalizationError, match="every re-emitted completed retry proof"):
        finalize_execution(partial)

    valid = _execution_request("negotiation", _supersede_retry_tick(_negotiation_references(), 1)).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    assert finalize_execution(valid).kernel_mode == "negotiation"

    unlisted = list(_negotiation_references())
    unlisted[1] = _append_supersedes(unlisted[1])
    unlisted_request = _execution_request("negotiation", tuple(unlisted)).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    with pytest.raises(KernelModeFinalizationError, match="completed retry ticks"):
        finalize_execution(unlisted_request)

    same_attempt = list(_negotiation_references())
    same_attempt[0] = _append_supersedes(same_attempt[0], target_attempt="attempt-1")
    same_attempt_request = _execution_request("negotiation", tuple(same_attempt)).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    with pytest.raises(KernelModeFinalizationError, match="not a retry origin"):
        finalize_execution(same_attempt_request)
    invalid_origin_payload = valid.model_dump(mode="json")
    invalid_origin_payload["retry_origin_attempt_ids"] = ("attempt-1",)
    with pytest.raises(ValidationError, match="differ from the current attempt"):
        KernelModeExecutionRequest.model_validate(invalid_origin_payload)


def test_negotiation_retry_rejects_missing_projected_tick_supersedes_and_nonprefix_context():
    fully_superseded = _supersede_retry_tick(_negotiation_references((1,)), 1)
    request = _execution_request("negotiation", fully_superseded).model_copy(update={
        "retry_origin_attempt_ids": ("attempt-0",),
        "retry_completed_ticks": (1,),
    })
    assert finalize_execution(request).kernel_mode == "negotiation"

    for token in ("PC", "CL", "PA"):
        incomplete = tuple(
            reference.model_copy(update={"relationships": reference.relationships[:-1]})
            if reference.tick == 1 and reference.token == token
            else reference
            for reference in fully_superseded
        )
        with pytest.raises(KernelModeFinalizationError, match="every re-emitted completed retry proof"):
            finalize_execution(request.model_copy(update={"proof": _proof_for(incomplete)}))

    payload = request.model_dump(mode="json")
    payload["retry_completed_ticks"] = (1, 3)
    with pytest.raises(ValidationError, match="contiguous prefix"):
        KernelModeExecutionRequest.model_validate(payload)
