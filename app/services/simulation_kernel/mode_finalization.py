"""Pure, fail-closed finalization for deterministic Kernel executions.

Artifact storage, extraction, replay, and run-control state are deliberately
outside this module.  Callers provide immutable, typed proof references; this
gate only verifies their identity, order, provenance, and ADR-0007 authority
rules before constructing a deterministic execution record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NoReturn, TypeVar, cast

from app.services.consistency.hashing import stable_hash

from .contracts import AUTHORITY_PATH_BY_KERNEL_MODE, NUMERIC_AUTHORITY_COMPONENTS
from .mode_contracts import (
    ARClaims,
    CLClaims,
    ACClaims,
    FCClaims,
    HRClaims,
    MBClaims,
    NDClaims,
    NRClaims,
    PAClaims,
    PBClaims,
    PCClaims,
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


EMPTY_COMMITMENT_LEDGER_HASH = stable_hash({"commitments": []})
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

    _validate_retry_context(request)
    _validate_projection_pair(request)
    references = request.proof.references
    _validate_reference_identities(request, references)

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
        "engine_mode": request.engine_mode,
        "kernel_mode": request.kernel_mode,
        "run_id": request.run_id,
        "attempt": request.attempt,
        "effective_seed": request.effective_seed,
        "rule_pack_hash": request.rule_pack_hash,
        "authority_path": AUTHORITY_PATH_BY_KERNEL_MODE[request.kernel_mode],
        "baseline_source_run_hash": request.baseline.source_run_hash,
        "baseline_deterministic_source_hash": request.baseline.deterministic_source_hash,
        "baseline_world_state_hash": request.baseline.world_state_hash,
        "final_source_run_hash": request.final.source_run_hash,
        "final_deterministic_source_hash": request.final.deterministic_source_hash,
        "final_world_state_hash": request.final.world_state_hash,
        "proof_hash": request.proof.proof_hash,
    }
    record_payload = {
        "schema_version": "kernel-mode-execution-record.v1",
        "execution_contract_version": "kernel-mode-execution.v2",
        **values,
    }
    return KernelModeExecutionRecord.model_validate({**values, "record_hash": stable_hash(record_payload)})


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


def _validate_retry_context(request: KernelModeExecutionRequest) -> None:
    """Recheck retry shape for callers that bypass model validation via copy."""

    origins = request.retry_origin_attempt_ids
    completed_ticks = request.retry_completed_ticks
    if bool(origins) != bool(completed_ticks):
        _fail("retry origins and completed ticks must be supplied together")
    if request.engine_mode != "negotiation" and (origins or completed_ticks):
        _fail("retry context is only allowed for negotiation")
    if completed_ticks != tuple(range(1, len(completed_ticks) + 1)):
        _fail("retry_completed_ticks must be a contiguous prefix beginning at 1")
    if request.attempt in origins:
        _fail("retry origin attempts must differ from the current attempt")


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


def _finalize_deterministic(
    request: KernelModeExecutionRequest,
    references: tuple[KernelModeProofReference, ...],
) -> None:
    _require_projection_identity(request)
    _require_sequence(references, (("FC", None),))
    fc_ref = references[0]
    fc = _claims(fc_ref, FCClaims)
    _require_source_schema(fc_ref, "consistency-audit.v1", "consistency-audit.v2")
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
    _require_source_schema(fc_ref, "consistency-audit.v1", "consistency-audit.v2")
    if request.engine_mode == "mock_agent":
        _require_source_schema(pb_ref, "mock-agent-batch.v1")
        if pb.source_kind != "mock_agent" or pb.batch_hash is None or pb.runtime_hash is not None:
            _fail("mock_agent PB source claims mismatch")
        _require_relationships(pb_ref, ())
    else:
        ar_ref = _single(by_token, "AR", "controlled_agent proof requires exactly one AR")
        ar = _claims(ar_ref, ARClaims)
        _require_source_schema(ar_ref, "agent-runtime-result.v1")
        _require_source_schema(pb_ref, "agent-action-batch.v1")
        if pb.source_kind != "controlled_agent" or pb.runtime_hash != ar.runtime_hash or pb.batch_hash is not None:
            _fail("controlled_agent PB runtime binding mismatch")
        if ar.proposal_ids != pb.proposal_ids:
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
    _require_projection_audit_source(pa_ref)
    _require_relationships(pa_ref, (("covers", pb_ref), ("governed_by", fc_ref)))
    if (
        pa.projection_mode != "audit_only"
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

    _require_source_schema(ar_ref, "agent-runtime-result.v1")
    _require_source_schema(pb_ref, "agent-action-batch.v1")
    _require_source_schema(fc_ref, "consistency-audit.v1", "consistency-audit.v2")
    _require_source_schema(mb_ref, "hybrid-modifier-bundle.v1")
    _require_source_schema(cl_ref, "commitment-ledger.v1")
    _require_projection_audit_source(pa_ref)
    _require_source_schema(hr_ref, "hybrid-replay-record.v1")

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

    if pb.source_kind != "controlled_agent" or pb.runtime_hash != ar.runtime_hash or pb.batch_hash is not None:
        _fail("hybrid PB runtime binding mismatch")
    if ar.proposal_ids != pb.proposal_ids:
        _fail("AR/PB proposal ids mismatch")
    if fc.proposal_ids != pb.proposal_ids:
        _fail("PB/FC proposal ids mismatch")
    if fc.deterministic_result_hash != request.baseline.source_run_hash:
        _fail("hybrid FC result hash must bind the baseline projection")
    if mb.accepted_proposal_ids != fc.accepted_proposal_ids or mb.consistency_audit_hash != fc.audit_hash:
        _fail("hybrid Modifier Bundle claims mismatch")
    if cl.ledger_entry_count != 0 or cl.commitments or cl.ledger_hash != EMPTY_COMMITMENT_LEDGER_HASH:
        _fail("hybrid Commitment Ledger must be the canonical empty ledger")
    if (
        pa.projection_mode != "hybrid"
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
    """Validate the six-tick ADR-0007 negotiation authority chain.

    The input is deliberately already-extracted typed evidence.  This function
    neither replays negotiation nor loads artifacts: it proves that the fixed
    evidence topology and its explicit claim bindings admit the final Kernel
    projection.
    """

    tick_count = 6
    if len(references) < 26:
        _fail("negotiation proof is shorter than the mandatory six-tick chain")

    round_refs = references[:tick_count]
    admission_refs = references[tick_count : 2 * tick_count]
    _require_token_ticks(round_refs, "RR")
    _require_token_ticks(admission_refs, "AC")

    cursor = 2 * tick_count
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
    ledger_refs = references[cursor : cursor + tick_count]
    cursor += tick_count
    projection_audit_refs: list[KernelModeProofReference] = []
    while cursor < len(references) and references[cursor].token == "PA":
        projection_audit_refs.append(references[cursor])
        cursor += 1
    if cursor >= len(references) or references[cursor].token != "NR" or cursor + 1 != len(references):
        _fail("negotiation NR must be the final proof reference")
    replay_ref = references[cursor]

    _require_token_ticks(diffusion_refs, "ND")
    _require_token_ticks(ledger_refs, "CL")
    if final_ref.tick is not None or replay_ref.tick is not None:
        _fail("negotiation FC and NR references may not carry ticks")

    rounds = tuple(_claims(reference, RRClaims) for reference in round_refs)
    admissions = tuple(_claims(reference, ACClaims) for reference in admission_refs)
    projections = tuple(_claims(reference, PCClaims) for reference in projection_refs)
    final_audit = _claims(final_ref, FCClaims)
    modifiers = tuple(_claims(reference, MBClaims) for reference in modifier_refs)
    diffusions = tuple(_claims(reference, NDClaims) for reference in diffusion_refs)
    ledgers = tuple(_claims(reference, CLClaims) for reference in ledger_refs)
    projection_audits = tuple(_claims(reference, PAClaims) for reference in projection_audit_refs)
    replay = _claims(replay_ref, NRClaims)

    _require_claim_ticks(rounds, tuple(range(1, tick_count + 1)), "RR")
    _require_claim_ticks(admissions, tuple(range(1, tick_count + 1)), "AC")
    _require_claim_ticks(projections, tuple(reference.tick for reference in projection_refs), "PC")
    _require_claim_ticks(modifiers, tuple(reference.tick for reference in modifier_refs), "MB")
    _require_claim_ticks(diffusions, tuple(range(1, tick_count + 1)), "ND")
    _require_claim_ticks(ledgers, tuple(range(1, tick_count + 1)), "CL")
    _require_claim_ticks(projection_audits, tuple(reference.tick for reference in projection_audit_refs), "PA")

    projected_ticks = tuple(
        tick
        for tick, (admission, diffusion) in enumerate(zip(admissions, diffusions, strict=True), start=1)
        if admission.accepted_proposal_ids or diffusion.attempted
    )
    _require_tick_set(projection_refs, projected_ticks, "PC")
    _require_tick_set(modifier_refs, projected_ticks, "MB")
    _require_tick_set(projection_audit_refs, projected_ticks, "PA")
    expected_count = 26 + 3 * len(projected_ticks)
    if len(references) != expected_count:
        _fail("negotiation proof count does not match 26 + 3P")

    projection_by_tick = _by_tick(projection_refs)
    modifier_by_tick = _by_tick(modifier_refs)
    audit_by_tick = _by_tick(projection_audit_refs)
    _require_retry_supersession_completeness(
        request,
        round_refs=round_refs,
        admission_refs=admission_refs,
        projection_by_tick=projection_by_tick,
        modifier_by_tick=modifier_by_tick,
        diffusion_refs=diffusion_refs,
        ledger_refs=ledger_refs,
        audit_by_tick=audit_by_tick,
        final_ref=final_ref,
        replay_ref=replay_ref,
    )

    for reference in round_refs:
        _require_source_schema(reference, "negotiation-round.v1")
    for reference in admission_refs:
        _require_source_schema(reference, "consistency-audit.v1", "consistency-audit.v2")
    for reference in projection_refs:
        _require_source_schema(reference, "consistency-audit.v2")
    _require_source_schema(final_ref, "consistency-audit.v1", "consistency-audit.v2")
    for reference in modifier_refs:
        _require_source_schema(reference, "hybrid-modifier-bundle.v1")
    for reference in diffusion_refs:
        _require_source_schema(reference, "narrative-diffusion.v1")
    for reference in ledger_refs:
        _require_source_schema(reference, "commitment-ledger.v1")
    for reference in projection_audit_refs:
        _require_negotiation_projection_audit_source(reference)
    _require_source_schema(replay_ref, "negotiation-replay.v1")

    session_id = rounds[0].session_id
    if replay.session_id != session_id or any(round_item.session_id != session_id for round_item in rounds):
        _fail("negotiation session_id mismatch")

    for tick in range(1, tick_count + 1):
        index = tick - 1
        rr_ref, ac_ref, nd_ref, cl_ref = (
            round_refs[index],
            admission_refs[index],
            diffusion_refs[index],
            ledger_refs[index],
        )
        rr, ac, nd, cl = rounds[index], admissions[index], diffusions[index], ledgers[index]
        previous = () if tick == 1 else (("previous_round", round_refs[index - 1]),)
        _require_relationships(rr_ref, previous)
        _require_relationships(ac_ref, (("evaluates", rr_ref),))
        _require_relationships(cl_ref, (("snapshot_for", rr_ref),))

        if rr.proposal_ids != ac.proposal_ids or rr.accepted_proposal_ids != ac.accepted_proposal_ids:
            _fail("negotiation RR/AC proposal bindings mismatch")
        if rr.admission_audit_hash != ac.audit_hash or ac.deterministic_result_hash != rr.before_result_hash:
            _fail("negotiation RR/AC audit binding mismatch")
        if nd.diffusion_hash != rr.diffusion_hash:
            _fail("negotiation RR/ND diffusion hash mismatch")
        if cl.ledger_hash != rr.ledger_hash:
            _fail("negotiation RR/CL ledger hash mismatch")
        if nd.before_result_hash != rr.before_result_hash or nd.after_result_hash != rr.after_result_hash:
            _fail("negotiation RR/ND result hash binding mismatch")

        is_projected = tick in projected_ticks
        if not is_projected:
            _require_relationships(nd_ref, (("no_projection_for", rr_ref),))
            if (
                nd.attempted
                or rr.no_projection_reason != "no_projection"
                or rr.projection_consistency_hash is not None
                or rr.modifier_bundle_hash is not None
                or rr.projection_audit_hash is not None
                or rr.before_result_hash != rr.after_result_hash
                or nd.before_result_hash != nd.after_result_hash
            ):
                _fail("no-projection negotiation tick claims mismatch")
            continue

        pc_ref = projection_by_tick[tick]
        mb_ref = modifier_by_tick[tick]
        pa_ref = audit_by_tick[tick]
        pc = _claims(pc_ref, PCClaims)
        mb = _claims(mb_ref, MBClaims)
        pa = _claims(pa_ref, PAClaims)
        _require_relationships(pc_ref, (("filters", ac_ref), ("evaluates", rr_ref)))
        _require_relationships(mb_ref, (("maps", rr_ref), ("admitted_by", pc_ref)))
        _require_relationships(nd_ref, (("bounded_by", mb_ref),))
        _require_relationships(
            pa_ref,
            (
                ("round", rr_ref),
                ("governed_by", pc_ref),
                ("audits", mb_ref),
                ("diffusion", nd_ref),
                ("ledger_snapshot", cl_ref),
            ),
        )
        if rr.no_projection_reason is not None:
            _fail("projected negotiation tick may not carry no_projection reason")
        if (
            pc.candidate_proposal_ids != rr.proposal_ids
            or pc.accepted_proposal_ids != rr.accepted_proposal_ids
            or pc.deterministic_result_hash != rr.before_result_hash
            or rr.projection_consistency_hash != pc.audit_hash
            or mb.accepted_proposal_ids != rr.accepted_proposal_ids
            or mb.consistency_audit_hash != pc.audit_hash
            or rr.modifier_bundle_hash != mb.bundle_hash
            or pa.projection_mode != "negotiation"
            or pa.consistency_audit_hash != pc.audit_hash
            or pa.modifier_bundle_hash != mb.bundle_hash
            or pa.proposal_ids != rr.proposal_ids
            or pa.projected_proposal_ids != rr.accepted_proposal_ids
            or pa.modifier_tuples != mb.modifier_tuples
            or pa.modifier_count != mb.modifier_count
            or pa.before_result_hash != rr.before_result_hash
            or pa.final_result_hash != rr.after_result_hash
            or rr.projection_audit_hash != pa.audit_hash
        ):
            _fail("projected negotiation tick claims mismatch")

    if rounds[0].before_result_hash != request.baseline.source_run_hash:
        _fail("negotiation first round must bind the baseline projection")
    if rounds[-1].after_result_hash != request.final.source_run_hash:
        _fail("negotiation final round must bind the final projection")
    if any(
        rounds[index].before_result_hash != rounds[index - 1].after_result_hash
        for index in range(1, tick_count)
    ):
        _fail("negotiation round result hash chain mismatch")

    _require_relationships(final_ref, (("evaluates", round_refs[-1]),))
    if (
        final_audit.proposal_ids != rounds[-1].proposal_ids
        or final_audit.accepted_proposal_ids != rounds[-1].accepted_proposal_ids
        or final_audit.deterministic_result_hash != request.final.source_run_hash
    ):
        _fail("negotiation FC/final projection binding mismatch")

    _require_relationships(
        replay_ref,
        tuple(("replays", reference) for reference in round_refs)
        + tuple(("admission", reference) for reference in admission_refs)
        + (("final_audit", final_ref),)
        + tuple(("projection", projection_by_tick[tick]) for tick in projected_ticks)
        + tuple(("modifiers", modifier_by_tick[tick]) for tick in projected_ticks)
        + tuple(("diffusion", reference) for reference in diffusion_refs)
        + tuple(("ledgers", reference) for reference in ledger_refs)
        + tuple(("audits", audit_by_tick[tick]) for tick in projected_ticks),
    )
    if (
        replay.baseline_result_hash != request.baseline.source_run_hash
        or replay.final_result_hash != request.final.source_run_hash
        or replay.round_hashes != tuple(item.output_hash for item in rounds)
        or replay.admission_audit_hashes != tuple(item.audit_hash for item in admissions)
        or replay.projection_consistency_hashes
        != tuple(rounds[tick - 1].projection_consistency_hash for tick in range(1, tick_count + 1))
        or replay.diffusion_hashes != tuple(item.diffusion_hash for item in diffusions)
        or replay.ledger_hashes != tuple(item.ledger_hash for item in ledgers)
        or replay.projection_audit_hashes
        != tuple(rounds[tick - 1].projection_audit_hash for tick in range(1, tick_count + 1))
        or replay.provider_calls_required != 0
    ):
        _fail("negotiation replay claims mismatch")


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
    ACClaims,
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
    claims: Sequence[object], expected_ticks: Sequence[int | None], token: ProofToken
) -> None:
    if tuple(getattr(claim, "tick", None) for claim in claims) != tuple(expected_ticks):
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
    _require_source_schema(reference, "agent-action-projection-audit.v1")
    if reference.artifact_type != "agent_action_projection_audit":
        _fail("Projection Audit artifact_type does not match audit-only execution mode")


def _require_negotiation_projection_audit_source(reference: KernelModeProofReference) -> None:
    _require_source_schema(reference, "agent-action-projection-audit.v1")
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
    if not request.retry_origin_attempt_ids or not request.retry_completed_ticks:
        _fail("supersedes requires closed negotiation retry context")
    if len(supersedes) != 1 or reference.relationships[-1] != supersedes[0]:
        _fail("supersedes must be the sole final retry relationship")
    if reference.token not in {"RR", "AC", "PC", "MB", "ND", "CL", "PA"} or reference.tick is None:
        _fail("supersedes is only allowed on ticked negotiation proof references")
    if reference.tick not in request.retry_completed_ticks:
        _fail("supersedes is only allowed for completed retry ticks")
    target_attempt = supersedes[0].target_attempt
    if target_attempt not in request.retry_origin_attempt_ids:
        _fail("supersedes target attempt is not a retry origin")
    if target_attempt == request.attempt:
        _fail("supersedes target attempt must differ from the current attempt")


def _require_retry_supersession_completeness(
    request: KernelModeExecutionRequest,
    *,
    round_refs: Sequence[KernelModeProofReference],
    admission_refs: Sequence[KernelModeProofReference],
    projection_by_tick: Mapping[int, KernelModeProofReference],
    modifier_by_tick: Mapping[int, KernelModeProofReference],
    diffusion_refs: Sequence[KernelModeProofReference],
    ledger_refs: Sequence[KernelModeProofReference],
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

    completed_ticks = set(request.retry_completed_ticks)
    for tick in range(1, 7):
        index = tick - 1
        reemitted = [
            round_refs[index],
            admission_refs[index],
            diffusion_refs[index],
            ledger_refs[index],
        ]
        for references_by_tick in (projection_by_tick, modifier_by_tick, audit_by_tick):
            if tick in references_by_tick:
                reemitted.append(references_by_tick[tick])
        for reference in reemitted:
            supersedes = tuple(
                relationship
                for relationship in reference.relationships
                if relationship.relationship_type == "supersedes"
            )
            if tick in completed_ticks:
                if len(supersedes) != 1 or reference.relationships[-1] != supersedes[0]:
                    _fail("every re-emitted completed retry proof must end with supersedes")
            elif supersedes:
                _fail("supersedes is forbidden after the completed retry prefix")


def _fail(message: str) -> NoReturn:
    raise KernelModeFinalizationError(message)
