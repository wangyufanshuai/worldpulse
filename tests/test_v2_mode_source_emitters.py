from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomScenarioRequest
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.negotiation import (
    build_audit_only_projection_source,
    build_consistency_audit_source,
    build_kernel_proposal_batch_source,
    extract_consistency_claims,
    extract_pa_claims,
    extract_pb_claims,
)
from app.services.simulation_runtime import simulation_runtime_service
from app.services.run_lifecycle.mode_context import (
    build_resolved_mock_agent_batch,
    resolve_mode_context,
)


RUN_ID = "job_v2_mock_emitter"
def _mock_sources():
    result = simulation_runtime_service.run_war_room(
        WarRoomScenarioRequest(seed=37)
    )
    context = resolve_mode_context(result, effective_seed=37)
    batch = build_resolved_mock_agent_batch(
        result,
        run_id=RUN_ID,
        effective_seed=37,
        context=context,
    )
    proposals = tuple(batch.proposals)
    pb = build_kernel_proposal_batch_source(
        run_id=RUN_ID,
        proposals=proposals,
        source_kind="mock_batch",
        mock_batch=batch,
    )
    report = evaluate_war_room_result(
        result,
        run_id=RUN_ID,
        created_at="2026-08-08T00:00:00.000",
        proposals=list(proposals),
        constraint_context=batch.constraint_context,
    )
    fc = build_consistency_audit_source(
        report,
        run_id=RUN_ID,
        role="final",
        tick=None,
        evaluator_version=report.evaluator_version,
        agent_pack_id=context.agent_pack.agent_pack_id,
        agent_pack_hash=context.agent_pack_hash,
        constraint_context_hash=context.constraint_context_hash,
        complete_proposals=proposals,
    )
    result_hash = stable_hash(result.model_dump(mode="json"))
    pa = build_audit_only_projection_source(
        run_id=RUN_ID,
        consistency_audit_hash=fc.audit_hash,
        final_result_hash=result_hash,
        proposals=proposals,
        decisions=tuple(report.proposal_decisions),
    )
    return result, context, batch, pb, fc, pa


def test_mock_emitters_build_complete_kernel_sources() -> None:
    result, context, batch, pb, fc, pa = _mock_sources()
    complete_proposals = tuple(pb.proposals)

    pb_claims = extract_pb_claims(
        pb.model_dump(mode="json"),
        run_id=RUN_ID,
        mock_batch_payload=batch.model_dump(mode="json"),
    )
    fc_claims = extract_consistency_claims(
        fc.model_dump(mode="json"),
        run_id=RUN_ID,
        role="final",
        tick=None,
        evaluator_version=fc.evaluator_version,
        agent_pack_id=context.agent_pack.agent_pack_id,
        agent_pack_hash=context.agent_pack_hash,
        constraint_context_hash=context.constraint_context_hash,
        complete_proposals=complete_proposals,
    )
    pa_claims = extract_pa_claims(
        pa.model_dump(mode="json"),
        run_id=RUN_ID,
        session_id=None,
        tick=None,
        projection_mode="audit_only",
        consistency_audit_hash=fc.audit_hash,
        complete_proposals=complete_proposals,
        modifier_claims=None,
    )

    result_hash = stable_hash(result.model_dump(mode="json"))
    assert pb_claims.proposal_ids == fc_claims.proposal_ids == pa_claims.proposal_ids
    assert pb_claims.proposal_hashes == fc_claims.proposal_hashes == pa_claims.proposal_hashes
    assert pa_claims.projected_proposal_ids == ()
    assert pa_claims.modifier_tuples == ()
    assert pa_claims.before_result_hash == pa_claims.final_result_hash == result_hash


def test_mock_pb_emitter_rejects_transcript_substitution() -> None:
    _, _, batch, _, _, _ = _mock_sources()
    substituted = batch.model_copy(deep=True)
    substituted.proposals[0].justification += " drift"

    with pytest.raises(
        (ValueError, ValidationError),
        match="batch_hash|drift|mock source",
    ):
        build_kernel_proposal_batch_source(
            run_id=RUN_ID,
            proposals=tuple(substituted.proposals),
            source_kind="mock_batch",
            mock_batch=batch,
        )


def test_audit_only_emitter_rejects_decision_input_hash_drift() -> None:
    _, _, batch, _, fc, _ = _mock_sources()
    result = simulation_runtime_service.run_war_room(
        WarRoomScenarioRequest(seed=37)
    )
    report = evaluate_war_room_result(
        result,
        run_id=RUN_ID,
        created_at="2026-08-08T00:00:00.000",
        proposals=batch.proposals,
        constraint_context=batch.constraint_context,
    )
    decisions = list(report.proposal_decisions)
    decisions[0] = decisions[0].model_copy(update={"input_hash": "f" * 64})

    with pytest.raises(ValueError, match="input hash"):
        build_audit_only_projection_source(
            run_id=RUN_ID,
            consistency_audit_hash=fc.audit_hash,
            final_result_hash=stable_hash(result.model_dump(mode="json")),
            proposals=tuple(batch.proposals),
            decisions=tuple(decisions),
        )
