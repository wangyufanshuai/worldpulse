"""Pure, fail-closed finalization for deterministic Kernel executions.

Artifact storage, extraction, replay, and run-control state are deliberately
outside this module.  Callers provide immutable, typed proof references; this
gate only verifies their identity, order, provenance, and ADR-0007 authority
rules before constructing a deterministic execution record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NoReturn, Protocol, TypeVar, cast

from app.services.consistency.hashing import stable_hash

from .contracts import NUMERIC_AUTHORITY_COMPONENTS
from .mode_contracts import (
    AUTHORITY_PATH_BY_ENGINE_MODE,
    ARClaims,
    ACClaims,
    CLClaims,
    ConsistencyClaims,
    ConsistencyDecisionClaimTuple,
    ConsistencyPreProjectionTuple,
    ELClaims,
    FCClaims,
    HRClaims,
    MBClaims,
    NDClaims,
    NPClaims,
    NRClaims,
    PAClaims,
    PBClaims,
    PCClaims,
    ProjectionRecordClaimTuple,
    RRClaims,
    KernelModeExecutionRecord,
    KernelModeExecutionRequest,
    KernelModeProofReference,
    ProofToken,
)
from .war_room_projection import DETERMINISTIC_AUTHORITY_OWNER, WarRoomProjection


class KernelModeFinalizationError(ValueError):
    """A supplied proof cannot cross the pure Kernel boundary."""


class KernelModeFinalizationNotImplementedError(KernelModeFinalizationError, NotImplementedError):
    """A future ADR mode was intentionally not admitted by this slice."""


def empty_commitment_ledger_hash(run_id: str) -> str:
    """Return the run-bound canonical empty commitment-ledger.v2 digest."""

    return stable_hash(
        {
            "schema_version": "commitment-ledger.v2",
            "run_id": run_id,
            "session_id": None,
            "tick": None,
            "entries": (),
        }
    )
_IMPLEMENTED_ENGINE_MODES = frozenset(
    {"deterministic", "mock_agent", "controlled_agent", "hybrid", "hybrid_recorded", "negotiation"}
)


def finalize_execution(request: KernelModeExecutionRequest) -> KernelModeExecutionRecord:
    """Finalize one normalized deterministic execution without mutating input.

    Exact accepted sequences are mode-specific ADR-0007 proof chains.  Hybrid
    paths always require their complete seven-reference evidence chain.
    """

    if request.engine_mode not in _IMPLEMENTED_ENGINE_MODES:
        _fail(f"unsupported engine mode: {request.engine_mode}")
    if request.kernel_mode not in {"deterministic", "hybrid", "negotiation"}:
        _fail("this finalization slice only admits deterministic, hybrid, or negotiation Kernel modes")

    _validate_request_contract(request)
    _validate_projection_pair(request)
    references = request.proof.references
    _validate_reference_identities(request, references)
    _validate_consistency_request_bindings(request, references)

    if request.engine_mode == "deterministic":
        _finalize_deterministic(request, references)
    elif request.engine_mode in {"mock_agent", "controlled_agent"}:
        _finalize_audit_only(request, references)
    elif request.engine_mode in {"hybrid", "hybrid_recorded"}:
        _finalize_hybrid(request, references)
    else:
        _finalize_negotiation(request, references)
    return _build_record(request)


def _build_record(request: KernelModeExecutionRequest) -> KernelModeExecutionRecord:
    """Construct the record from a fixed deterministic authority path."""

    values = {
        "request_hash": request.request_hash,
        "organization_id": request.organization_id,
        "project_id": request.project_id,
        "lifecycle_job_id": request.lifecycle_job_id,
        "engine_mode": request.engine_mode,
        "kernel_mode": request.kernel_mode,
        "run_id": request.run_id,
        "session_id": request.session_id,
        "attempt": request.attempt,
        "effective_seed": request.effective_seed,
        "rule_pack_id": request.rule_pack_id,
        "rule_pack_hash": request.rule_pack_hash,
        "agent_pack_id": request.agent_pack_id,
        "agent_pack_hash": request.agent_pack_hash,
        "constraint_context_hash": request.constraint_context_hash,
        "evaluator_version": request.evaluator_version,
        "runtime_profile_hash": request.runtime_profile_hash,
        "authority_path": AUTHORITY_PATH_BY_ENGINE_MODE[request.engine_mode],
        "baseline_source_run_hash": request.baseline.source_run_hash,
        "baseline_deterministic_source_hash": request.baseline.deterministic_source_hash,
        "baseline_world_state_hash": request.baseline.world_state_hash,
        "final_source_run_hash": request.final.source_run_hash,
        "final_deterministic_source_hash": request.final.deterministic_source_hash,
        "final_world_state_hash": request.final.world_state_hash,
        "fencing_epoch_hash": request.fencing_epoch_hash,
        "proof_hash": request.proof_hash,
    }
    record_payload = {
        "schema_version": "kernel-mode-execution-record.v1",
        "execution_contract_version": "kernel-mode-execution.v2",
        **values,
    }
    return KernelModeExecutionRecord.model_validate(
        {**record_payload, "record_hash": stable_hash(record_payload)}
    )


def _validate_request_contract(request: KernelModeExecutionRequest) -> None:
    """Recheck closed request identity when callers used unchecked model_copy."""

    try:
        KernelModeExecutionRequest.model_validate(request.model_dump(mode="python"))
    except ValueError as error:
        _fail(f"request contract validation failed: {error}")
    if request.proof_hash != request.proof.proof_hash:
        _fail("request proof_hash mismatch")
    expected_hash = stable_hash(
        request.model_dump(mode="json", exclude={"request_hash"})
    )
    if request.request_hash != expected_hash:
        _fail("request_hash mismatch")
    if (request.engine_mode == "negotiation") != (request.session_id is not None):
        _fail("request session_id does not match engine mode")
    context = (
        request.agent_pack_id,
        request.agent_pack_hash,
        request.constraint_context_hash,
    )
    if request.engine_mode == "deterministic":
        if any(value is not None for value in context):
            _fail("deterministic request Agent context must be null")
    elif any(value is None for value in context):
        _fail("Agent-capable request context must be complete")


def _validate_projection_pair(request: KernelModeExecutionRequest) -> None:
    """Validate projection identity, topology, hashes, and numeric authority."""

    for projection in (request.baseline, request.final):
        if projection.schema_version != "war-room-projection.v1":
            _fail("projection schema_version is not supported")
        if projection.world_state.schema_version != "kernel-world-state.v1":
            _fail("WorldState schema_version is not supported")
        if projection.world_state_hash != projection.world_state.content_hash():
            _fail("projection WorldState hash mismatch")
        _validate_numeric_authority(projection)
    if _projection_topology(request.baseline) != _projection_topology(request.final):
        _fail("baseline/final entity topology mismatch")


def _projection_topology(projection: WarRoomProjection) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((entity_id, entity.entity_type) for entity_id, entity in projection.world_state.entities.items())
    )


def _validate_numeric_authority(projection: WarRoomProjection) -> None:
    for entity in projection.world_state.entities.values():
        authoritative = tuple(
            key
            for key in entity.components
            if key in NUMERIC_AUTHORITY_COMPONENTS or key.startswith("numeric.")
        )
        if not authoritative:
            continue
        raw_provenance = entity.components.get("authority_provenance")
        if not isinstance(raw_provenance, Mapping):
            _fail(f"numeric authority provenance missing for {entity.entity_id}")
        provenance = cast(Mapping[str, object], raw_provenance)
        if provenance.get("owner") != DETERMINISTIC_AUTHORITY_OWNER:
            _fail(f"numeric authority owner mismatch for {entity.entity_id}")
        scope = provenance.get("components")
        if not isinstance(scope, (tuple, list)) or not set(authoritative).issubset(scope):
            _fail(f"numeric authority component scope mismatch for {entity.entity_id}")


def _validate_reference_identities(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    """Ensure canonical ordinal/order and one run/attempt namespace."""

    if not references:
        _fail("execution proof must contain at least one reference")
    artifact_ids: set[str] = set()
    for ordinal, reference in enumerate(references):
        if reference.ordinal != ordinal:
            _fail("proof ordinals must be contiguous and match canonical order")
        if reference.run_id != request.run_id or reference.claims.run_id != request.run_id:
            _fail("proof reference run_id mismatch")
        if reference.session_id != request.session_id:
            _fail("proof reference session_id mismatch")
        if reference.attempt != request.attempt:
            _fail("proof reference attempt mismatch")
        if reference.artifact_id in artifact_ids:
            _fail("duplicate proof artifact reference")
        artifact_ids.add(reference.artifact_id)
        if request.engine_mode != "negotiation" and any(
            item.relationship_type == "supersedes" for item in reference.relationships
        ):
            _fail("supersedes is only admitted by negotiation finalization")
        _validate_supersedes_relationships(request, reference)


def _validate_consistency_request_bindings(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    expected = (
        request.evaluator_version,
        request.agent_pack_id,
        request.agent_pack_hash,
        request.constraint_context_hash,
    )
    for reference in references:
        if isinstance(reference.claims, ConsistencyClaims):
            actual = (
                reference.claims.evaluator_version,
                reference.claims.agent_pack_id,
                reference.claims.agent_pack_hash,
                reference.claims.constraint_context_hash,
            )
            if actual != expected:
                _fail("Consistency claims do not match request resolver identity")


def _finalize_deterministic(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    _require_projection_identity(request)
    _require_sequence(references, (("FC", None),))
    fc_ref = references[0]
    fc = _claims(fc_ref, FCClaims)
    _require_consistency_context(fc, agent_context=False)
    _require_source_schema(fc_ref, "consistency-audit.v3")
    _require_relationships(fc_ref, ())
    if fc.proposal_ids or fc.accepted_proposal_ids or fc.decision_count:
        _fail("deterministic FC must contain no Agent proposals")
    if fc.deterministic_result_hash != request.baseline.source_run_hash:
        _fail("deterministic FC result hash must bind both projections")


def _finalize_audit_only(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    """Validate mock/controlled Agent evidence as strictly audit-only."""

    _require_projection_identity(request)
    by_token = _index_references(references)
    pb_ref = _single(by_token, "PB", "audit-only proof requires exactly one PB")
    pb = _claims(pb_ref, PBClaims)
    has_proposals = pb.proposal_count > 0
    expected: list[tuple[ProofToken, int | None]] = []
    if request.engine_mode == "controlled_agent":
        expected.append(("AR", None))
    expected.extend((("PB", None), ("FC", None)))
    if has_proposals:
        expected.append(("PA", None))
    _require_sequence(references, tuple(expected))

    fc_ref = _single(by_token, "FC", "audit-only proof requires exactly one FC")
    fc = _claims(fc_ref, FCClaims)
    _require_consistency_context(fc, agent_context=True)
    _require_source_schema(fc_ref, "consistency-audit.v3")
    if request.engine_mode == "mock_agent":
        _require_source_schema(pb_ref, "kernel-proposal-batch.v1")
        if (
            pb.source_kind != "mock_batch"
            or pb.source_mock_batch_hash is None
            or pb.source_runtime_hash is not None
        ):
            _fail("mock_agent PB source claims mismatch")
        _require_relationships(pb_ref, ())
    else:
        ar_ref = _single(by_token, "AR", "controlled_agent proof requires exactly one AR")
        ar = _claims(ar_ref, ARClaims)
        _require_source_schema(ar_ref, "agent-runtime-result.v1")
        _require_source_schema(pb_ref, "kernel-proposal-batch.v1")
        if (
            pb.source_kind != "agent_runtime"
            or pb.source_runtime_hash != ar.runtime_hash
            or pb.source_mock_batch_hash is not None
        ):
            _fail("controlled_agent PB runtime binding mismatch")
        if ar.proposal_ids != pb.proposal_ids or ar.proposal_hashes != pb.proposal_hashes:
            _fail("AR/PB proposal ids mismatch")
        _require_relationships(ar_ref, ())
        _require_relationships(pb_ref, (("generated_by", ar_ref),))

    if fc.proposal_ids != pb.proposal_ids:
        _fail("PB/FC proposal ids mismatch")
    if fc.deterministic_result_hash != request.baseline.source_run_hash:
        _fail("audit-only FC result hash must bind both projections")
    _require_relationships(fc_ref, (("evaluates", pb_ref),))
    if not has_proposals:
        if fc.decision_count != 0 or fc.accepted_proposal_ids:
            _fail("zero-proposal audit-only proof must have zero decisions and no acceptances")
        return

    pa_ref = _single(by_token, "PA", "nonzero-proposal audit-only proof requires exactly one PA")
    pa = _claims(pa_ref, PAClaims)
    _require_projection_decision_alignment(pa, fc.decision_tuples)
    _require_projection_audit_source(pa_ref)
    _require_relationships(pa_ref, (("covers", pb_ref), ("governed_by", fc_ref)))
    if (
        pa.projection_mode != "audit_only"
        or pa.session_id is not None
        or pa.tick is not None
        or pa.consistency_audit_hash != fc.audit_hash
        or pa.modifier_bundle_hash is not None
        or pa.proposal_ids != pb.proposal_ids
        or pa.projected_proposal_ids
        or pa.modifier_tuples
        or pa.modifier_count != 0
        or pa.record_count != pb.proposal_count
        or pa.before_result_hash != request.baseline.source_run_hash
        or pa.final_result_hash != request.final.source_run_hash
    ):
        _fail("audit-only Projection Audit claims mismatch")


def _finalize_hybrid(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    """Validate the fixed, deterministic ADR-0007 hybrid authority chain."""

    _require_sequence(
        references,
        (("AR", None), ("PB", None), ("FC", None), ("MB", None), ("CL", None), ("PA", None), ("HR", None)),
    )
    ar_ref, pb_ref, fc_ref, mb_ref, cl_ref, pa_ref, hr_ref = references
    ar = _claims(ar_ref, ARClaims)
    pb = _claims(pb_ref, PBClaims)
    fc = _claims(fc_ref, FCClaims)
    mb = _claims(mb_ref, MBClaims)
    cl = _claims(cl_ref, CLClaims)
    pa = _claims(pa_ref, PAClaims)
    hr = _claims(hr_ref, HRClaims)
    _require_consistency_context(fc, agent_context=True)
    _require_projection_decision_alignment(pa, fc.decision_tuples)

    _require_source_schema(ar_ref, "agent-runtime-result.v1")
    _require_source_schema(pb_ref, "kernel-proposal-batch.v1")
    _require_source_schema(fc_ref, "consistency-audit.v3")
    _require_source_schema(mb_ref, "hybrid-modifier-bundle.v2")
    _require_source_schema(cl_ref, "commitment-ledger.v2")
    _require_projection_audit_source(pa_ref)
    _require_source_schema(hr_ref, "hybrid-replay-record.v2")

    _require_relationships(ar_ref, ())
    _require_relationships(pb_ref, (("generated_by", ar_ref),))
    _require_relationships(fc_ref, (("evaluates", pb_ref),))
    _require_relationships(mb_ref, (("maps", pb_ref), ("admitted_by", fc_ref)))
    _require_relationships(cl_ref, (("ledger_for", mb_ref),))
    _require_relationships(
        pa_ref,
        (("covers", pb_ref), ("governed_by", fc_ref), ("audits", mb_ref), ("ledger_snapshot", cl_ref)),
    )
    _require_relationships(
        hr_ref,
        (
            ("observations", pb_ref),
            ("governed_by", fc_ref),
            ("replays", mb_ref),
            ("ledger_snapshot", cl_ref),
            ("audit", pa_ref),
        ),
    )

    if (
        pb.source_kind != "agent_runtime"
        or pb.source_runtime_hash != ar.runtime_hash
        or pb.source_mock_batch_hash is not None
    ):
        _fail("hybrid PB runtime binding mismatch")
    if ar.proposal_ids != pb.proposal_ids or ar.proposal_hashes != pb.proposal_hashes:
        _fail("AR/PB proposal ids mismatch")
    if fc.proposal_ids != pb.proposal_ids:
        _fail("PB/FC proposal ids mismatch")
    if fc.deterministic_result_hash != request.baseline.source_run_hash:
        _fail("hybrid FC result hash must bind the baseline projection")
    if mb.accepted_proposal_ids != fc.accepted_proposal_ids or mb.consistency_audit_hash != fc.audit_hash:
        _fail("hybrid Modifier Bundle claims mismatch")
    if (
        cl.session_id is not None
        or cl.tick is not None
        or cl.ledger_entry_count != 0
        or cl.commitments
        or cl.ledger_hash != empty_commitment_ledger_hash(request.run_id)
    ):
        _fail("hybrid Commitment Ledger must be the canonical empty ledger")
    if (
        mb.tick is not None
        or pa.session_id is not None
        or pa.tick is not None
        or pa.projection_mode != "hybrid"
        or pa.consistency_audit_hash != fc.audit_hash
        or pa.modifier_bundle_hash != mb.bundle_hash
        or pa.proposal_ids != pb.proposal_ids
        or pa.projected_proposal_ids != fc.accepted_proposal_ids
        or pa.modifier_tuples != mb.modifier_tuples
        or pa.modifier_count != mb.modifier_count
        or pa.record_count != pb.proposal_count
        or pa.before_result_hash != request.baseline.source_run_hash
    ):
        _fail("hybrid Projection Audit claims mismatch")
    if (
        hr.engine_mode != request.engine_mode
        or hr.replay_source_kind != "stored_only"
        or hr.provider_calls_required != 0
        or hr.baseline_result_hash != request.baseline.source_run_hash
        or hr.final_result_hash != pa.final_result_hash
        or hr.full_source_run_hash != request.final.source_run_hash
        or hr.proposal_batch_hash != pb.batch_hash
        or hr.consistency_audit_hash != fc.audit_hash
        or hr.modifier_bundle_hash != mb.bundle_hash
        or hr.projection_audit_hash != pa.audit_hash
        or hr.ledger_hash != cl.ledger_hash
        or hr.accepted_proposal_ids != fc.accepted_proposal_ids
    ):
        _fail("hybrid Replay claims mismatch")

    # Empty acceptance is an ADR numeric no-op, whether there were no proposals
    # at all or every proposal was rejected.  All seven proofs remain mandatory.
    if not fc.accepted_proposal_ids:
        _require_projection_identity(request)
        if mb.modifier_tuples or mb.modifier_count or pa.projected_proposal_ids or pa.modifier_tuples or pa.modifier_count:
            _fail("unaccepted hybrid proposals may not produce modifiers or projections")
        if not pb.proposal_ids and (fc.decision_count or pa.record_count or pa.proposal_ids):
            _fail("zero-proposal hybrid proof must contain empty decision and audit tuples")


def _finalize_negotiation(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    """Validate the closed six-tick NP/EL-governed negotiation proof."""

    tick_count = 6
    fixed_prefix_count = 5 * tick_count
    if len(references) < 38:
        _fail("negotiation proof is shorter than the mandatory 38-reference chain")

    round_refs = references[0:6]
    proposal_refs = references[6:12]
    admission_refs = references[12:18]
    ledger_refs = references[18:24]
    eligibility_refs = references[24:30]
    for block, token in (
        (round_refs, "RR"),
        (proposal_refs, "NP"),
        (admission_refs, "AC"),
        (ledger_refs, "CL"),
        (eligibility_refs, "EL"),
    ):
        _require_token_ticks(block, token)  # type: ignore[arg-type]

    cursor = fixed_prefix_count
    projection_refs: list[KernelModeProofReference] = []
    while cursor < len(references) and references[cursor].token == "PC":
        projection_refs.append(references[cursor])
        cursor += 1
    if cursor >= len(references) or references[cursor].token != "FC":
        _fail("negotiation FC must follow the projection-consistency block")
    final_ref = references[cursor]
    cursor += 1

    modifier_refs: list[KernelModeProofReference] = []
    while cursor < len(references) and references[cursor].token == "MB":
        modifier_refs.append(references[cursor])
        cursor += 1
    diffusion_refs = references[cursor : cursor + tick_count]
    cursor += tick_count
    projection_audit_refs: list[KernelModeProofReference] = []
    while cursor < len(references) and references[cursor].token == "PA":
        projection_audit_refs.append(references[cursor])
        cursor += 1
    if cursor >= len(references) or references[cursor].token != "NR" or cursor + 1 != len(references):
        _fail("negotiation NR must be the final proof reference")
    replay_ref = references[cursor]
    _require_token_ticks(diffusion_refs, "ND")
    if final_ref.tick is not None or replay_ref.tick is not None:
        _fail("negotiation FC and NR references may not carry ticks")

    rounds = tuple(_claims(reference, RRClaims) for reference in round_refs)
    proposals = tuple(_claims(reference, NPClaims) for reference in proposal_refs)
    admissions = tuple(_claims(reference, ACClaims) for reference in admission_refs)
    ledgers = tuple(_claims(reference, CLClaims) for reference in ledger_refs)
    eligibilities = tuple(_claims(reference, ELClaims) for reference in eligibility_refs)
    projections = tuple(_claims(reference, PCClaims) for reference in projection_refs)
    final_audit = _claims(final_ref, FCClaims)
    modifiers = tuple(_claims(reference, MBClaims) for reference in modifier_refs)
    diffusions = tuple(_claims(reference, NDClaims) for reference in diffusion_refs)
    projection_audits = tuple(_claims(reference, PAClaims) for reference in projection_audit_refs)
    replay = _claims(replay_ref, NRClaims)

    _require_consistency_context(final_audit, agent_context=True)
    expected_context = (
        final_audit.evaluator_version,
        final_audit.agent_pack_id,
        final_audit.agent_pack_hash,
        final_audit.constraint_context_hash,
    )
    if any(
        (
            item.evaluator_version,
            item.agent_pack_id,
            item.agent_pack_hash,
            item.constraint_context_hash,
        )
        != expected_context
        for item in (*admissions, *projections)
    ):
        _fail("negotiation Consistency context identity mismatch")

    for claims, token in (
        (rounds, "RR"),
        (proposals, "NP"),
        (admissions, "AC"),
        (ledgers, "CL"),
        (eligibilities, "EL"),
        (diffusions, "ND"),
    ):
        _require_claim_ticks(claims, tuple(range(1, 7)), token)  # type: ignore[arg-type]
    _require_claim_ticks(projections, tuple(reference.tick for reference in projection_refs), "PC")
    _require_claim_ticks(modifiers, tuple(reference.tick for reference in modifier_refs), "MB")
    _require_claim_ticks(projection_audits, tuple(reference.tick for reference in projection_audit_refs), "PA")

    projected_ticks = tuple(
        tick for tick, eligibility in enumerate(eligibilities, start=1)
        if eligibility.eligible_proposal_ids
    )
    _require_tick_set(projection_refs, projected_ticks, "PC")
    _require_tick_set(modifier_refs, projected_ticks, "MB")
    _require_tick_set(projection_audit_refs, projected_ticks, "PA")
    if len(references) != 38 + 3 * len(projected_ticks):
        _fail("negotiation proof count does not match 38 + 3P")

    projection_by_tick = _by_tick(projection_refs)
    modifier_by_tick = _by_tick(modifier_refs)
    audit_by_tick = _by_tick(projection_audit_refs)
    _require_retry_supersession_completeness(
        request,
        round_refs=round_refs,
        proposal_refs=proposal_refs,
        admission_refs=admission_refs,
        ledger_refs=ledger_refs,
        eligibility_refs=eligibility_refs,
        projection_by_tick=projection_by_tick,
        modifier_by_tick=modifier_by_tick,
        diffusion_refs=diffusion_refs,
        audit_by_tick=audit_by_tick,
        final_ref=final_ref,
        replay_ref=replay_ref,
    )

    schema_blocks: tuple[tuple[Sequence[KernelModeProofReference], str], ...] = (
        (round_refs, "negotiation-round.v2"),
        (proposal_refs, "negotiation-proposal-batch.v1"),
        (admission_refs, "consistency-audit.v3"),
        (ledger_refs, "commitment-ledger.v2"),
        (eligibility_refs, "negotiation-eligibility.v1"),
        (projection_refs, "consistency-audit.v3"),
        (modifier_refs, "hybrid-modifier-bundle.v2"),
        (diffusion_refs, "narrative-diffusion.v2"),
    )
    for schema_references, schema in schema_blocks:
        for reference in schema_references:
            _require_source_schema(reference, schema)
    _require_source_schema(final_ref, "consistency-audit.v3")
    for reference in projection_audit_refs:
        _require_negotiation_projection_audit_source(reference)
    _require_source_schema(replay_ref, "negotiation-replay.v2")

    session_id = rounds[0].session_id
    if (
        replay.session_id != session_id
        or any(item.session_id != session_id for item in rounds)
        or any(item.session_id != session_id for item in proposals)
        or any(item.session_id != session_id for item in eligibilities)
        or any(item.session_id != session_id for item in diffusions)
    ):
        _fail("negotiation session_id mismatch")
    if any(item.session_id != session_id for item in ledgers):
        _fail("negotiation Commitment Ledger session_id mismatch")

    for tick in range(1, tick_count + 1):
        index = tick - 1
        rr_ref = round_refs[index]
        np_ref = proposal_refs[index]
        ac_ref = admission_refs[index]
        cl_ref = ledger_refs[index]
        el_ref = eligibility_refs[index]
        nd_ref = diffusion_refs[index]
        rr, np, ac, cl, el, nd = (
            rounds[index], proposals[index], admissions[index], ledgers[index],
            eligibilities[index], diffusions[index],
        )

        previous = () if tick == 1 else (("previous_round", round_refs[index - 1]),)
        _require_relationships(rr_ref, previous)
        _require_relationships(np_ref, (("source_for", rr_ref),))
        _require_relationships(ac_ref, (("evaluates", np_ref),))
        _require_relationships(cl_ref, (("snapshot_after", ac_ref),))
        prior_pa = tuple(audit_by_tick[prior] for prior in projected_ticks if prior < tick)
        origin_ticks = sorted(
            {item[9] for item in np.proposal_claim_tuples if item[7] == "active_commitment_origin"}
        )
        _require_relationships(
            el_ref,
            (("sources", np_ref), ("admitted_by", ac_ref), ("current_ledger", cl_ref))
            + tuple(("prior_projection", reference) for reference in prior_pa)
            + tuple(("origin_admission", admission_refs[origin_tick - 1]) for origin_tick in origin_ticks),
        )

        current_sources = tuple(item for item in np.proposal_claim_tuples if item[7] == "current_message")
        current_ids = tuple(item[0] for item in current_sources)
        current_hashes = tuple(item[1] for item in current_sources)
        if (
            rr.proposal_ids != current_ids
            or ac.proposal_ids != current_ids
            or ac.proposal_hashes != current_hashes
            or rr.accepted_proposal_ids != ac.accepted_proposal_ids
            or rr.proposal_batch_hash != np.batch_hash
            or np.source_hashes != (rr.messages_hash, ac.audit_hash, cl.ledger_hash)
            or rr.admission_audit_hash != ac.audit_hash
            or rr.ledger_hash != cl.ledger_hash
            or rr.eligibility_hash != el.eligibility_hash
            or rr.eligible_proposal_ids != el.eligible_proposal_ids
            or ac.deterministic_result_hash != rr.before_result_hash
        ):
            _fail("negotiation RR/NP/AC/CL/EL bindings mismatch")
        if cl.tick != tick:
            _fail("negotiation Commitment Ledger tick mismatch")
        _validate_eligibility_claims(
            tick=tick,
            proposal=np,
            admission=ac,
            ledger=cl,
            eligibility=el,
            admissions=admissions,
            prior_audits=tuple(
                _claims(audit_by_tick[prior], PAClaims)
                for prior in projected_ticks if prior < tick
            ),
        )

        _validate_message_coordinates(rr, tick=tick, session_id=session_id)
        if rr.diffusion_evidence_hash != nd.diffusion_evidence_hash:
            _fail("negotiation RR/ND diffusion evidence hash mismatch")

        is_projected = tick in projected_ticks
        if not is_projected:
            _require_relationships(nd_ref, (("inputs", el_ref),))
            if (
                nd.attempted
                or nd.input_proposal_ids
                or rr.no_projection_reason != "no_projection"
                or rr.projection_consistency_hash is not None
                or rr.modifier_bundle_hash is not None
                or rr.projection_audit_hash is not None
                or rr.before_result_hash != rr.after_result_hash
                or nd.before_result_hash != rr.before_result_hash
                or nd.after_result_hash != rr.after_result_hash
            ):
                _fail("no-projection negotiation tick claims mismatch")
            continue

        pc_ref = projection_by_tick[tick]
        mb_ref = modifier_by_tick[tick]
        pa_ref = audit_by_tick[tick]
        pc = _claims(pc_ref, PCClaims)
        mb = _claims(mb_ref, MBClaims)
        pa = _claims(pa_ref, PAClaims)
        _require_projection_decision_alignment(pa, pc.decision_tuples)
        _require_relationships(pc_ref, (("filters", el_ref),))
        _require_relationships(mb_ref, (("admitted_by", pc_ref),))
        _require_relationships(nd_ref, (("inputs", el_ref), ("bounded_by", mb_ref)))
        _require_relationships(
            pa_ref,
            (("round", rr_ref), ("governed_by", pc_ref), ("audits", mb_ref),
             ("diffusion", nd_ref), ("ledger_snapshot", cl_ref)),
        )

        proposal_by_id = {item[0]: item for item in np.proposal_claim_tuples}
        selected_hashes = tuple(proposal_by_id[item][1] for item in el.eligible_proposal_ids)
        projected_semantics = tuple(proposal_by_id[item][6] for item in pc.accepted_proposal_ids)
        narrative_ids = tuple(
            item for item in pc.accepted_proposal_ids if proposal_by_id[item][5] == "public_narrative"
        )
        narrative_hashes = tuple(proposal_by_id[item][1] for item in narrative_ids)
        if (
            rr.no_projection_reason is not None
            or pc.candidate_proposal_ids != el.eligible_proposal_ids
            or pc.proposal_hashes != selected_hashes
            or pc.deterministic_result_hash != rr.before_result_hash
            or rr.projection_consistency_hash != pc.audit_hash
            or mb.accepted_proposal_ids != pc.accepted_proposal_ids
            or mb.consistency_audit_hash != pc.audit_hash
            or rr.modifier_bundle_hash != mb.bundle_hash
            or pa.projection_mode != "negotiation"
            or pa.session_id != session_id
            or pa.consistency_audit_hash != pc.audit_hash
            or pa.modifier_bundle_hash != mb.bundle_hash
            or pa.proposal_ids != pc.candidate_proposal_ids
            or pa.proposal_hashes != pc.proposal_hashes
            or pa.record_input_hashes != pc.proposal_hashes
            or pa.projected_proposal_ids != pc.accepted_proposal_ids
            or pa.projected_semantic_key_hashes != projected_semantics
            or pa.modifier_tuples != mb.modifier_tuples
            or pa.modifier_count != mb.modifier_count
            or pa.before_result_hash != rr.before_result_hash
            or nd.input_proposal_ids != narrative_ids
            or nd.input_proposal_hashes != narrative_hashes
            or nd.after_result_hash != pa.final_result_hash
            or pa.final_result_hash != rr.after_result_hash
            or rr.projection_audit_hash != pa.audit_hash
        ):
            _fail("projected negotiation tick claims mismatch")

    if rounds[0].before_result_hash != request.baseline.source_run_hash:
        _fail("negotiation first round must bind the baseline projection")
    if rounds[-1].after_result_hash != request.final.source_run_hash:
        _fail("negotiation final round must bind the final projection")
    if any(rounds[index].before_result_hash != rounds[index - 1].after_result_hash for index in range(1, 6)):
        _fail("negotiation round result hash chain mismatch")

    all_messages = tuple(item for round_item in rounds for item in round_item.message_tuples)
    sequences = tuple(item[0] for item in all_messages)
    if sequences != tuple(range(1, len(all_messages) + 1)):
        _fail("negotiation message sequence must be one global contiguous chain")
    expected_message_head = all_messages[-1][2] if all_messages else None

    _require_relationships(final_ref, (("evaluates", round_refs[-1]),))
    if (
        final_audit.proposal_ids
        or final_audit.proposal_hashes
        or final_audit.accepted_proposal_ids
        or final_audit.decision_count != 0
        or final_audit.deterministic_result_hash != request.final.source_run_hash
    ):
        _fail("negotiation FC must be the empty terminal-state audit")

    _require_relationships(
        replay_ref,
        tuple(("replays", reference) for reference in round_refs)
        + tuple(("proposal_sources", reference) for reference in proposal_refs)
        + tuple(("admission", reference) for reference in admission_refs)
        + tuple(("ledgers", reference) for reference in ledger_refs)
        + tuple(("eligibility", reference) for reference in eligibility_refs)
        + tuple(("projection", projection_by_tick[tick]) for tick in projected_ticks)
        + (("final_audit", final_ref),)
        + tuple(("modifiers", modifier_by_tick[tick]) for tick in projected_ticks)
        + tuple(("diffusion", reference) for reference in diffusion_refs)
        + tuple(("audits", audit_by_tick[tick]) for tick in projected_ticks),
    )
    if (
        replay.baseline_result_hash != request.baseline.source_run_hash
        or replay.final_result_hash != request.final.source_run_hash
        or replay.round_hashes != tuple(item.round_hash for item in rounds)
        or replay.proposal_batch_hashes != tuple(item.batch_hash for item in proposals)
        or replay.admission_audit_hashes != tuple(item.audit_hash for item in admissions)
        or replay.ledger_hashes != tuple(item.ledger_hash for item in ledgers)
        or replay.eligibility_hashes != tuple(item.eligibility_hash for item in eligibilities)
        or replay.projection_consistency_hashes != tuple(item.projection_consistency_hash for item in rounds)
        or replay.modifier_bundle_hashes != tuple(item.modifier_bundle_hash for item in rounds)
        or replay.diffusion_evidence_hashes != tuple(item.diffusion_evidence_hash for item in diffusions)
        or replay.projection_audit_hashes != tuple(item.projection_audit_hash for item in rounds)
        or replay.message_chain_head != expected_message_head
        or replay.provider_calls_required != 0
    ):
        _fail("negotiation replay claims mismatch")


def _validate_message_coordinates(rr: RRClaims, *, tick: int, session_id: str) -> None:
    expected_round_id = f"round_{stable_hash({'session': session_id, 'tick': tick})[:20]}"
    if rr.round_id != expected_round_id:
        _fail("negotiation round_id is not the canonical session/tick derivation")


def _validate_eligibility_claims(
    *,
    tick: int,
    proposal: NPClaims,
    admission: ACClaims,
    ledger: CLClaims,
    eligibility: ELClaims,
    admissions: Sequence[ACClaims],
    prior_audits: Sequence[PAClaims],
) -> None:
    """Recompute GOV-EL-1 from immutable NP/AC/CL/prior-PA claims."""

    decision_sources = tuple(item[0] for item in eligibility.decision_tuples)
    if decision_sources != proposal.proposal_claim_tuples:
        _fail("EL decisions must reproduce every NP proposal tuple field-for-field")

    prior_ids = {
        proposal_id for audit in prior_audits for proposal_id in audit.projected_proposal_ids
    }
    prior_semantics = {
        semantic_hash
        for audit in prior_audits
        for semantic_hash in audit.projected_semantic_key_hashes
    }
    admission_hashes = dict(zip(admission.proposal_ids, admission.proposal_hashes, strict=True))
    accepted_ids = set(admission.accepted_proposal_ids)
    ledger_by_id = {item[0]: item for item in ledger.commitments}

    expected: dict[str, str | None] = {}
    preliminary_by_semantic: dict[str, list[str]] = {}
    for item in proposal.proposal_claim_tuples:
        proposal_id, proposal_hash = item[0], item[1]
        source_kind, commitment_id = item[7], item[8]
        action_class, semantic_hash = item[5], item[6]

        if source_kind == "current_message" and (
            proposal_id not in accepted_ids or admission_hashes.get(proposal_id) != proposal_hash
        ):
            expected[proposal_id] = "not_admitted"
            continue

        active_entry = None
        if source_kind == "active_commitment_origin":
            if commitment_id is None:
                _fail("active commitment origin must carry a commitment id")
            active_entry = ledger_by_id.get(commitment_id)
            source_tick = item[9]
            if source_tick < 1 or source_tick >= tick:
                _fail("active commitment origin admission tick is invalid")
            origin_admission = admissions[source_tick - 1]
            origin_hashes = dict(
                zip(origin_admission.proposal_ids, origin_admission.proposal_hashes, strict=True)
            )
            if (
                active_entry is None
                or active_entry[2] != "active"
                or active_entry[3] != item[4]
                or active_entry[6] != proposal_id
                or active_entry[7] != proposal_hash
                or active_entry[8] != item[2]
                or active_entry[9] != item[3]
                or active_entry[10] != source_tick
                or active_entry[11] != item[10]
                or origin_admission.audit_hash != item[10]
                or proposal_id not in origin_admission.accepted_proposal_ids
                or origin_hashes.get(proposal_id) != proposal_hash
            ):
                _fail("active commitment origin is not bound to CL and its accepting AC")

        if action_class == "audit_only":
            expected[proposal_id] = "audit_only"
            continue
        if action_class == "alliance_response":
            expected[proposal_id] = "alliance_response"
            continue
        if action_class == "bilateral_commitment" and active_entry is None:
            active_matches = tuple(
                item
                for item in ledger.commitments
                if item[2] == "active" and item[6] == proposal_id and item[7] == proposal_hash
            )
            if len(active_matches) != 1:
                expected[proposal_id] = "inactive_commitment"
                continue
        if proposal_id in prior_ids:
            expected[proposal_id] = "already_projected"
            continue
        if semantic_hash in prior_semantics:
            expected[proposal_id] = "semantic_duplicate"
            continue
        expected[proposal_id] = None
        preliminary_by_semantic.setdefault(semantic_hash, []).append(proposal_id)

    for group in preliminary_by_semantic.values():
        winner = min(group, key=lambda value: value.encode("utf-8"))
        for proposal_id in group:
            expected[proposal_id] = "eligible" if proposal_id == winner else "semantic_duplicate"

    for decision in eligibility.decision_tuples:
        proposal_item, prior_projected, outcome, _ = decision
        proposal_id = proposal_item[0]
        if prior_projected != (proposal_id in prior_ids):
            _fail("EL prior_projected flag does not match prior PA membership")
        if outcome != expected[proposal_id]:
            _fail("EL outcome does not match canonical eligibility precedence")


def _require_consistency_context(
    claims: ConsistencyClaims, *, agent_context: bool
) -> None:
    values = (
        claims.agent_pack_id,
        claims.agent_pack_hash,
        claims.constraint_context_hash,
    )
    if agent_context and any(value is None for value in values):
        _fail("Agent-capable FC requires complete Consistency context identity")
    if not agent_context and any(value is not None for value in values):
        _fail("deterministic FC requires null Consistency context identity")


class _TickedClaim(Protocol):
    @property
    def tick(self) -> int | None: ...


def _require_projection_decision_alignment(
    audit: PAClaims,
    decisions: Sequence[ConsistencyDecisionClaimTuple],
) -> None:
    """Compare only the pre-projection fields governed by Consistency."""

    def projection_fields(
        record: ProjectionRecordClaimTuple,
    ) -> ConsistencyPreProjectionTuple:
        return (
            record[0],
            record[1],
            record[3],
            record[2],
            record[4],
            record[5],
            record[6],
        )

    audit_fields = tuple(
        projection_fields(record) for record in audit.record_claim_tuples
    )
    consistency_fields = tuple(
        (
            decision[0],
            decision[1],
            decision[2],
            decision[3],
            decision[4],
            decision[5],
            decision[6],
        )
        for decision in decisions
    )
    if audit_fields != consistency_fields:
        _fail("Projection Audit pre-projection decisions do not match Consistency")


def _require_projection_identity(request: KernelModeExecutionRequest) -> None:
    if (
        request.baseline.source_run_hash != request.final.source_run_hash
        or request.baseline.deterministic_source_hash != request.final.deterministic_source_hash
        or request.baseline.world_state_hash != request.final.world_state_hash
    ):
        _fail("deterministic/audit-only numeric state must be unchanged")


def _index_references(
    references: tuple[KernelModeProofReference, ...],
) -> dict[ProofToken, tuple[KernelModeProofReference, ...]]:
    """Return token-indexed references while preserving proof order."""

    grouped: dict[ProofToken, list[KernelModeProofReference]] = {}
    for reference in references:
        grouped.setdefault(reference.token, []).append(reference)
    return {token: tuple(items) for token, items in grouped.items()}


def _single(
    grouped: Mapping[ProofToken, tuple[KernelModeProofReference, ...]],
    token: ProofToken,
    message: str,
) -> KernelModeProofReference:
    references = grouped.get(token, ())
    if len(references) != 1:
        _fail(message)
    return references[0]


_ModeClaim = TypeVar(
    "_ModeClaim",
    ARClaims,
    PBClaims,
    FCClaims,
    RRClaims,
    NPClaims,
    ACClaims,
    ELClaims,
    PCClaims,
    MBClaims,
    NDClaims,
    CLClaims,
    PAClaims,
    HRClaims,
    NRClaims,
)


def _claims(reference: KernelModeProofReference, expected_type: type[_ModeClaim]) -> _ModeClaim:
    """Typed claim access kept at the finalizer boundary for extension."""

    if not isinstance(reference.claims, expected_type):
        _fail(f"{reference.token} claims do not match the finalization schema")
    return reference.claims


def _require_sequence(
    references: tuple[KernelModeProofReference, ...],
    expected: Sequence[tuple[ProofToken, int | None]],
) -> None:
    actual = tuple((reference.token, reference.tick) for reference in references)
    if actual != tuple(expected):
        _fail(f"proof reference sequence mismatch: expected {tuple(expected)!r}, got {actual!r}")
    if any(reference.tick is not None for reference in references):
        _fail("deterministic finalization proof references may not carry ticks")


def _require_token_ticks(references: Sequence[KernelModeProofReference], token: ProofToken) -> None:
    """Require exactly one reference for each fixed negotiation tick."""

    if len(references) != 6 or any(
        reference.token != token or reference.tick != index
        for index, reference in enumerate(references, start=1)
    ):
        _fail(f"negotiation {token} references must cover ticks 1..6 in order")


def _require_claim_ticks(
    claims: Sequence[_TickedClaim],
    expected_ticks: Sequence[int | None],
    token: ProofToken,
) -> None:
    if tuple(claim.tick for claim in claims) != tuple(expected_ticks):
        _fail(f"negotiation {token} claim ticks must match reference ticks")


def _require_tick_set(
    references: Sequence[KernelModeProofReference],
    expected_ticks: tuple[int, ...],
    token: ProofToken,
) -> None:
    actual = tuple(reference.tick for reference in references)
    if any(reference.token != token for reference in references) or actual != expected_ticks:
        _fail(f"negotiation {token} references must match derived projection ticks")


def _by_tick(references: Sequence[KernelModeProofReference]) -> dict[int, KernelModeProofReference]:
    """Index already-validated tick references without silently accepting duplicates."""

    result: dict[int, KernelModeProofReference] = {}
    for reference in references:
        tick = reference.tick
        if tick is None or tick in result:
            _fail("negotiation tick reference is missing or duplicated")
        result[tick] = reference
    return result


def _require_source_schema(reference: KernelModeProofReference, *versions: str) -> None:
    if reference.schema_version not in versions:
        _fail(f"{reference.token} source schema is not admitted in this mode")


def _require_projection_audit_source(reference: KernelModeProofReference) -> None:
    _require_source_schema(reference, "agent-action-projection-audit.v2")
    if reference.artifact_type != "agent_action_projection_audit":
        _fail("Projection Audit artifact_type does not match audit-only execution mode")


def _require_negotiation_projection_audit_source(reference: KernelModeProofReference) -> None:
    _require_source_schema(reference, "negotiation-projection-audit.v2")
    if reference.artifact_type != "negotiation_projection_audit":
        _fail("Projection Audit artifact_type does not match negotiation execution mode")


def _require_relationships(
    reference: KernelModeProofReference,
    expected: Sequence[tuple[str, KernelModeProofReference]],
) -> None:
    relationships = reference.relationships
    if relationships and relationships[-1].relationship_type == "supersedes":
        relationships = relationships[:-1]
    if len(relationships) != len(expected):
        _fail(f"{reference.token} relationship cardinality mismatch")
    for actual, (relationship_type, target) in zip(relationships, expected, strict=True):
        if (
            actual.relationship_type != relationship_type
            or actual.target_artifact_id != target.artifact_id
            or actual.target_content_hash != target.content_hash
            or actual.target_attempt is not None
        ):
            _fail(f"{reference.token} relationship target mismatch")


def _validate_supersedes_relationships(
    request: KernelModeExecutionRequest,
    reference: KernelModeProofReference,
) -> None:
    """Validate retry shape only; historic artifacts are authenticated later."""

    supersedes = tuple(
        relationship
        for relationship in reference.relationships
        if relationship.relationship_type == "supersedes"
    )
    if not supersedes:
        return
    if request.engine_mode != "negotiation":
        _fail("supersedes is only admitted by negotiation finalization")
    if len(supersedes) != 1 or reference.relationships[-1] != supersedes[0]:
        _fail("supersedes must be the sole final retry relationship")
    if reference.token not in {"RR", "NP", "AC", "CL", "EL", "PC", "MB", "ND", "PA"} or reference.tick is None:
        _fail("supersedes is only allowed on ticked negotiation proof references")
    target_attempt = supersedes[0].target_attempt
    if target_attempt == request.attempt:
        _fail("supersedes target attempt must differ from the current attempt")


def _require_retry_supersession_completeness(
    request: KernelModeExecutionRequest,
    *,
    round_refs: Sequence[KernelModeProofReference],
    proposal_refs: Sequence[KernelModeProofReference],
    admission_refs: Sequence[KernelModeProofReference],
    ledger_refs: Sequence[KernelModeProofReference],
    eligibility_refs: Sequence[KernelModeProofReference],
    projection_by_tick: Mapping[int, KernelModeProofReference],
    modifier_by_tick: Mapping[int, KernelModeProofReference],
    diffusion_refs: Sequence[KernelModeProofReference],
    audit_by_tick: Mapping[int, KernelModeProofReference],
    final_ref: KernelModeProofReference,
    replay_ref: KernelModeProofReference,
) -> None:
    """Require a complete supersession prefix for a negotiation retry."""

    if any(
        relationship.relationship_type == "supersedes"
        for reference in (final_ref, replay_ref)
        for relationship in reference.relationships
    ):
        _fail("negotiation FC and NR references may not supersede retry evidence")

    completed_ticks: set[int] = set()
    for tick in range(1, 7):
        index = tick - 1
        reemitted = [
            round_refs[index],
            proposal_refs[index],
            admission_refs[index],
            ledger_refs[index],
            eligibility_refs[index],
            diffusion_refs[index],
        ]
        for references_by_tick in (projection_by_tick, modifier_by_tick, audit_by_tick):
            if tick in references_by_tick:
                reemitted.append(references_by_tick[tick])
        superseded = []
        for reference in reemitted:
            supersedes = tuple(
                relationship
                for relationship in reference.relationships
                if relationship.relationship_type == "supersedes"
            )
            superseded.append(
                len(supersedes) == 1 and reference.relationships[-1] == supersedes[0]
            )
        if any(superseded):
            if not all(superseded):
                _fail("every re-emitted completed retry proof must end with supersedes")
            completed_ticks.add(tick)
    if tuple(sorted(completed_ticks)) != tuple(range(1, len(completed_ticks) + 1)):
        _fail("supersedes is only allowed on a contiguous retry prefix")


def _fail(message: str) -> NoReturn:
    raise KernelModeFinalizationError(message)
