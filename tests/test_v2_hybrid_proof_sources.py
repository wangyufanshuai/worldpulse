from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract import build_mock_agent_batch
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.hybrid_simulation import run_hybrid_simulation
from app.services.negotiation import (
    HybridReplaySource,
    ProjectionAuditSource,
    build_consistency_audit_source,
    build_empty_commitment_ledger_source,
    build_hybrid_modifier_bundle_source,
    build_hybrid_projection_source,
    build_hybrid_replay_source,
    extract_cl_claims,
    extract_hr_claims,
    extract_mb_claims,
    extract_pa_claims,
)
from app.services.war_room_engine import run_war_room


RUN_ID = "v2-hybrid-proof-source-run"


def _sources(engine_mode: str = "hybrid"):
    baseline = run_war_room(
        WarRoomScenarioRequest(
            scenario_key="strait_blockade_30d",
            duration_days=30,
            intensity=0.7,
            propagation=0.45,
            seed=42,
        )
    )
    batch = build_mock_agent_batch(baseline, run_id=RUN_ID, seed=42)
    report = evaluate_war_room_result(
        baseline,
        run_id=RUN_ID,
        proposals=batch.proposals,
        constraint_context=batch.constraint_context,
    )
    consistency = build_consistency_audit_source(
        report,
        run_id=RUN_ID,
        role="final",
        tick=None,
        evaluator_version="worldpulse-consistency.v0.8",
        agent_pack_id="agent-pack-test",
        agent_pack_hash="a" * 64,
        constraint_context_hash="b" * 64,
        complete_proposals=tuple(batch.proposals),
    )
    outcome = run_hybrid_simulation(
        baseline,
        batch.proposals,
        consistency.inner_report(),
        seed=42,
    )
    modifier = build_hybrid_modifier_bundle_source(
        run_id=RUN_ID,
        consistency_audit_hash=consistency.audit_hash,
        bundle=outcome.modifier_bundle,
    )
    ledger = build_empty_commitment_ledger_source(run_id=RUN_ID)
    projection = build_hybrid_projection_source(
        run_id=RUN_ID,
        consistency_audit_hash=consistency.audit_hash,
        before_result_hash=stable_hash(baseline.model_dump(mode="json")),
        final_result_hash=outcome.replay_record.final_result_hash,
        proposals=tuple(batch.proposals),
        decisions=tuple(consistency.inner_report().proposal_decisions),
        modifier_bundle=modifier,
    )
    replay = build_hybrid_replay_source(
        run_id=RUN_ID,
        engine_mode=engine_mode,
        baseline_result_hash=stable_hash(baseline.model_dump(mode="json")),
        final_result_hash=outcome.replay_record.final_result_hash,
        full_source_run_hash=stable_hash(outcome.final_result.model_dump(mode="json")),
        proposal_batch_hash="c" * 64,
        consistency_audit_hash=consistency.audit_hash,
        modifier_bundle_hash=modifier.bundle_hash,
        projection_audit_hash=projection.audit_hash,
        ledger_hash=ledger.ledger_hash,
        accepted_proposal_ids=modifier.accepted_proposal_ids,
    )
    return batch, consistency, modifier, ledger, projection, replay


@pytest.mark.parametrize("engine_mode", ["hybrid", "hybrid_recorded"])
def test_hybrid_builders_close_complete_provider_free_sources(engine_mode):
    batch, consistency, modifier, ledger, projection, replay = _sources(engine_mode)

    mb = extract_mb_claims(
        modifier.model_dump(mode="json"),
        run_id=RUN_ID,
        tick=None,
        consistency_audit_hash=consistency.audit_hash,
    )
    assert extract_cl_claims(
        ledger.model_dump(mode="json"),
        run_id=RUN_ID,
        session_id=None,
        tick=None,
    ).ledger_entry_count == 0
    pa = extract_pa_claims(
        projection.model_dump(mode="json"),
        run_id=RUN_ID,
        session_id=None,
        tick=None,
        projection_mode="hybrid",
        consistency_audit_hash=consistency.audit_hash,
        complete_proposals=tuple(
            item.model_dump(mode="json")
            for item in sorted(
                batch.proposals,
                key=lambda proposal: proposal.proposal_id.encode("utf-8"),
            )
        ),
        modifier_claims=mb,
    )
    hr = extract_hr_claims(
        replay.model_dump(mode="json"),
        run_id=RUN_ID,
        engine_mode=engine_mode,
    )

    assert pa.projected_proposal_ids == mb.accepted_proposal_ids
    assert hr.provider_calls_required == 0
    assert hr.ledger_hash == ledger.ledger_hash


def test_hybrid_sources_reject_rehashed_cross_source_drift():
    batch, consistency, modifier, _, projection, replay = _sources()

    pa_payload = projection.model_dump(mode="json")
    pa_payload["modifier_bundle_hash"] = "f" * 64
    pa_payload["audit_hash"] = stable_hash(
        {key: value for key, value in pa_payload.items() if key != "audit_hash"}
    )
    with pytest.raises(ValueError, match="PA/MB claims binding"):
        extract_pa_claims(
            pa_payload,
            run_id=RUN_ID,
            session_id=None,
            tick=None,
            projection_mode="hybrid",
            consistency_audit_hash=consistency.audit_hash,
            complete_proposals=tuple(
                item.model_dump(mode="json")
                for item in sorted(
                    batch.proposals,
                    key=lambda proposal: proposal.proposal_id.encode("utf-8"),
                )
            ),
            modifier_claims=modifier.extract_claims(),
        )

    replay_payload = deepcopy(replay.model_dump(mode="json"))
    replay_payload["provider_calls_required"] = 1
    replay_payload["replay_hash"] = stable_hash(
        {key: value for key, value in replay_payload.items() if key != "replay_hash"}
    )
    with pytest.raises(ValidationError, match="provider_calls_required"):
        HybridReplaySource.model_validate(replay_payload)

    projection_payload = projection.model_dump(mode="json")
    projection_payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProjectionAuditSource.model_validate(projection_payload)
