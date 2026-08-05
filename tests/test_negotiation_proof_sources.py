from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.services.consistency.hashing import stable_hash
from app.services.negotiation.proof_sources import (
    extract_cl_claims,
    extract_consistency_claims,
    extract_el_claims,
    extract_mb_claims,
    extract_nd_claims,
    extract_np_claims,
    extract_pa_claims,
)


RUN_ID = "proof-source-run"
SESSION_ID = "proof-source-session"
DIGESTS = tuple(stable_hash({"digest": index}) for index in range(8))


def _proposal(*, action_type: str = "diplomatic_signal", turn: int = 1) -> dict:
    parameters = (
        {"signal": "firm", "channel": "backchannel", "public": False}
        if action_type == "diplomatic_signal"
        else {
            "objective": "coordinate regional defense",
            "requested_support": ["diplomatic"],
            "duration_days": 14,
        }
    )
    return {
        "proposal_id": "proposal-0001",
        "schema_version": "agent-action-proposal.v1",
        "run_id": RUN_ID,
        "turn": turn,
        "actor_id": "agent-alpha",
        "actor_type": "diplomacy",
        "action_type": action_type,
        "target_ids": ["country:USA"],
        "parameters": parameters,
        "justification": "Verified evidence supports this governed action.",
        "evidence_refs": ["evidence-0001"],
        "expected_direction": "coordinate",
        "confidence": 70.0,
        "created_at": "2000-01-01T00:00:01.000Z",
        "expires_after_turn": 3,
    }


def _np_payload(*, action_type: str = "diplomatic_signal") -> dict:
    proposal = _proposal(action_type=action_type)
    proposal_hash = stable_hash(proposal)
    action_class = {
        "diplomatic_signal": "deterministic_modifier",
        "alliance_request": "bilateral_commitment",
    }[action_type]
    semantic_hash = stable_hash(
        {
            "actor_id": proposal["actor_id"],
            "action_type": proposal["action_type"],
            "target_ids": tuple(proposal["target_ids"]),
            "parameters": proposal["parameters"],
        }
    )
    claim = (
        proposal["proposal_id"],
        proposal_hash,
        "message-0001",
        DIGESTS[0],
        action_type,
        action_class,
        semantic_hash,
        "current_message",
        None,
        1,
        DIGESTS[1],
    )
    payload = {
        "schema_version": "negotiation-proposal-batch.v1",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "tick": 1,
        "source_hashes": [DIGESTS[2], DIGESTS[1], DIGESTS[3]],
        "proposal_claim_tuples": [claim],
        "proposal_count": 1,
        "proposals": [proposal],
    }
    payload["batch_hash"] = stable_hash(payload)
    return payload


def _el_payload(np_payload: dict) -> dict:
    proposal_claim = tuple(np_payload["proposal_claim_tuples"][0])
    decision_hash = stable_hash(
        {"decision": [proposal_claim, False, "eligible"]}
    )
    payload = {
        "schema_version": "negotiation-eligibility.v1",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "tick": 1,
        "decisions": [
            {
                "proposal_claim_tuple": proposal_claim,
                "prior_projected": False,
                "outcome": "eligible",
                "decision_hash": decision_hash,
            }
        ],
        "decision_count": 1,
        "eligible_proposal_ids": [proposal_claim[0]],
        "eligible_proposal_count": 1,
    }
    payload["eligibility_hash"] = stable_hash(
        {
            "schema_version": "negotiation-eligibility.v1",
            "run_id": RUN_ID,
            "session_id": SESSION_ID,
            "tick": 1,
            "decision_hashes": (decision_hash,),
            "eligible_proposal_ids": (proposal_claim[0],),
        }
    )
    return payload


def _cl_payload() -> dict:
    proposal = _proposal(action_type="alliance_request")
    proposal_hash = stable_hash(proposal)
    terms = {
        "session_id": SESSION_ID,
        "action_type": "alliance_request",
        "proposal": proposal,
    }
    terms_hash = stable_hash(
        {"schema_version": "commitment-ledger.v2", "terms": terms}
    )
    commitment_preimage = {
        "schema_version": "commitment-ledger.v2",
        "session_id": SESSION_ID,
        "action_type": "alliance_request",
        "party_agent_ids": ("agent-alpha", "agent-beta"),
        "terms_hash": terms_hash,
        "source_proposal_id": proposal["proposal_id"],
        "source_proposal_hash": proposal_hash,
        "source_message_id": "message-0001",
        "source_message_hash": DIGESTS[0],
        "source_admission_tick": 1,
        "source_admission_audit_hash": DIGESTS[1],
    }
    commitment_hash = stable_hash(commitment_preimage)
    commitment_id = f"commit_{commitment_hash[:20]}"
    event_preimage = {
        "schema_version": "commitment-ledger.v2",
        "commitment_id": commitment_id,
        "tick": 1,
        "seq": 1,
        "status": "proposed",
        "actor_agent_id": "agent-alpha",
        "source_message_id": "message-0001",
        "source_message_hash": DIGESTS[0],
        "previous_event_hash": None,
    }
    event = {
        "tick": 1,
        "seq": 1,
        "status": "proposed",
        "actor_agent_id": "agent-alpha",
        "source_message_id": "message-0001",
        "source_message_hash": DIGESTS[0],
        "previous_event_hash": None,
        "event_hash": stable_hash(event_preimage),
    }
    entry = {
        "commitment_id": commitment_id,
        "commitment_hash": commitment_hash,
        "status": "proposed",
        "action_type": "alliance_request",
        "party_agent_ids": ["agent-alpha", "agent-beta"],
        "terms": terms,
        "terms_hash": terms_hash,
        "source_proposal_id": proposal["proposal_id"],
        "source_proposal_hash": proposal_hash,
        "source_message_id": "message-0001",
        "source_message_hash": DIGESTS[0],
        "source_admission_tick": 1,
        "source_admission_audit_hash": DIGESTS[1],
        "events": [event],
    }
    payload = {
        "schema_version": "commitment-ledger.v2",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "tick": 1,
        "entries": [entry],
        "ledger_entry_count": 1,
    }
    payload["ledger_hash"] = stable_hash(
        {
            "schema_version": "commitment-ledger.v2",
            "run_id": RUN_ID,
            "session_id": SESSION_ID,
            "tick": 1,
            "entries": (entry,),
        }
    )
    return payload


def _nd_payload(*, attempted: bool) -> dict:
    application = {
        "proposal_id": "proposal-0001",
        "target_country": "USA",
        "receiver_country": "USA",
        "tone": "informational",
        "audience": "global",
        "base_delta": -1.0,
        "propagation_multiplier": 0.25,
        "alliance_multiplier": 1.25,
        "effective_multiplier": 0.3125,
        "applied_delta": -0.3125,
        "cumulative_delta": -0.3125,
    }
    core = {
        "schema_version": "narrative-diffusion.v1",
        "seed": 17,
        "tone_deltas": {
            "firm": 3.0,
            "informational": -1.0,
            "stabilizing": -4.0,
        },
        "country_deltas": {"USA": -0.3125} if attempted else {},
        "applications": [application] if attempted else [],
    }
    request = {
        "scenario_key": "baseline",
        "duration_days": 30,
        "intensity": 0.5,
        "propagation": 0.4,
        "target_countries": ["USA"],
        "target_chains": ["shipping"],
        "policy_actions": [],
        "country_overrides": {},
        "chain_overrides": {},
        "seed": 17,
    }
    application_hash = stable_hash(
        {
            "schema_version": "narrative-diffusion.v2",
            "application": application,
        }
    )
    proposal_hash = stable_hash(_proposal(action_type="diplomatic_signal"))
    payload = {
        "schema_version": "narrative-diffusion.v2",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "tick": 1,
        "attempted": attempted,
        "input_proposal_ids": ["proposal-0001"] if attempted else [],
        "input_proposal_hashes": [proposal_hash] if attempted else [],
        "core_audit": core,
        "narrative_diffusion_audit_hash": stable_hash(core),
        "diffusion_request": request,
        "diffusion_request_hash": stable_hash(
            {
                "schema_version": "narrative-diffusion.v2",
                "diffusion_request": request,
            }
        ),
        "before_result_hash": DIGESTS[4],
        "after_result_hash": DIGESTS[5] if attempted else DIGESTS[4],
        "tone_delta_tuples": [
            ("firm", 30000),
            ("informational", -10000),
            ("stabilizing", -40000),
        ],
        "country_delta_tuples": [("USA", -3125)] if attempted else [],
        "application_tuples": [
            (
                "proposal-0001",
                "USA",
                "USA",
                "informational",
                "global",
                -10000,
                2500,
                12500,
                3125,
                -3125,
                -3125,
                application_hash,
            )
        ]
        if attempted
        else [],
        "application_count": 1 if attempted else 0,
    }
    payload["diffusion_evidence_hash"] = stable_hash(payload)
    return payload


def _mb_payload() -> dict:
    modifier_without_identity = {
        "schema_version": "deterministic-action-modifier.v1",
        "adapter_version": "worldpulse-action-adapter.v0.11",
        "proposal_id": "proposal-0001",
        "turn": 1,
        "action_type": "diplomatic_signal",
        "policy_actions": ["alliance_deterrence"],
        "chain_adjustments": {},
        "rationale_refs": ["evidence-0001"],
        "no_numeric_effect_reason": None,
    }
    modifier_hash = stable_hash(modifier_without_identity)
    modifier = {
        **modifier_without_identity,
        "modifier_id": f"modifier_{modifier_hash[:16]}",
        "modifier_hash": modifier_hash,
    }
    scenario_patch = {
        "seed": 17,
        "policy_actions": ["alliance_deterrence"],
        "chain_overrides": {},
    }
    inner = {
        "schema_version": "hybrid-modifier-bundle.v1",
        "adapter_version": "worldpulse-action-adapter.v0.11",
        "accepted_proposal_ids": ["proposal-0001"],
        "modifiers": [modifier],
        "scenario_patch": scenario_patch,
    }
    inner["bundle_hash"] = stable_hash(inner)
    payload = {
        "schema_version": "hybrid-modifier-bundle.v2",
        "run_id": RUN_ID,
        "tick": 1,
        "consistency_audit_hash": DIGESTS[1],
        "inner_bundle": inner,
        "inner_bundle_hash": inner["bundle_hash"],
        "accepted_proposal_ids": ["proposal-0001"],
        "modifiers": [modifier],
        "scenario_patch": scenario_patch,
        "modifier_tuples": [
            {
                "proposal_id": "proposal-0001",
                "modifier_id": modifier["modifier_id"],
                "modifier_hash": modifier_hash,
            }
        ],
        "modifier_count": 1,
    }
    payload["bundle_hash"] = stable_hash(payload)
    return payload


def _pa_payload(mb_payload: dict) -> dict:
    proposal = _proposal()
    proposal_hash = stable_hash(proposal)
    modifier = mb_payload["modifier_tuples"][0]
    semantic_hash = stable_hash(
        {
            "actor_id": proposal["actor_id"],
            "action_type": proposal["action_type"],
            "target_ids": tuple(proposal["target_ids"]),
            "parameters": proposal["parameters"],
        }
    )
    record = {
        "proposal_id": proposal["proposal_id"],
        "proposal_hash": proposal_hash,
        "input_hash": proposal_hash,
        "decision": "accepted",
        "rule_version": "worldpulse-consistency.v1.2",
        "outcome": "accepted",
        "rejection_reason": None,
        "projection_status": "projected",
        "projection_hash": modifier["modifier_hash"],
        "modifier_id": modifier["modifier_id"],
        "final_result_hash": DIGESTS[5],
    }
    payload = {
        "schema_version": "negotiation-projection-audit.v2",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "tick": 1,
        "projection_mode": "negotiation",
        "consistency_audit_hash": DIGESTS[1],
        "modifier_bundle_hash": mb_payload["bundle_hash"],
        "proposal_ids": [proposal["proposal_id"]],
        "proposal_hashes": [proposal_hash],
        "proposal_count": 1,
        "projected_proposal_ids": [proposal["proposal_id"]],
        "projected_semantic_key_hashes": [semantic_hash],
        "projected_count": 1,
        "modifier_tuples": [modifier],
        "modifier_count": 1,
        "records": [record],
        "record_count": 1,
        "before_result_hash": DIGESTS[4],
        "final_result_hash": DIGESTS[5],
    }
    payload["audit_hash"] = stable_hash(payload)
    return payload


def _consistency_payload(*, role: str = "admission") -> dict:
    proposal = _proposal()
    proposal_hash = stable_hash(proposal)
    tick = None if role == "final" else 1
    inner_run_id = (
        RUN_ID
        if role == "final"
        else f"{RUN_ID}:tick:1"
        if role == "admission"
        else f"{RUN_ID}:projection:1"
    )
    created_at = {
        "final": "2000-01-01T00:00:00.000Z",
        "admission": "2000-01-01T00:00:01.000Z",
        "projection": "2000-01-01T00:00:02.000Z",
    }[role]
    decision = {
        "proposal_id": proposal["proposal_id"],
        "decision": "accepted",
        "rule_findings": [],
        "evidence_refs": proposal["evidence_refs"],
        "explanation_zh": "受控提案通过一致性校验。",
        "outcome": "accepted",
        "input_hash": proposal_hash,
        "rule_version": "worldpulse-consistency.v1.2",
        "rejection_reason": None,
        "projection_status": "not_projected",
        "projection_hash": None,
    }
    decision["audit_hash"] = stable_hash(decision)
    inner = {
        "schema_version": "consistency-audit.v2",
        "evaluator_version": "worldpulse-consistency.v0.8",
        "run_id": inner_run_id,
        "overall_status": "passed",
        "summary": {},
        "findings": [],
        "proposal_decisions": [decision],
        "evaluated_rule_count": 1,
        "skipped_rule_count": 0,
        "deterministic_result_hash": DIGESTS[4],
        "created_at": created_at,
    }
    inner["audit_hash"] = stable_hash(
        {
            key: value
            for key, value in inner.items()
            if key not in {"run_id", "created_at", "audit_hash"}
        }
    )
    context = role != "final"
    payload = {
        "schema_version": "consistency-audit.v3",
        "run_id": RUN_ID,
        "role": role,
        "tick": tick,
        "evaluator_version": "worldpulse-consistency.v0.8",
        "agent_pack_id": "agent-pack-test" if context else None,
        "agent_pack_hash": DIGESTS[5] if context else None,
        "constraint_context_hash": DIGESTS[6] if context else None,
        "proposal_ids": [proposal["proposal_id"]],
        "proposal_hashes": [proposal_hash],
        "inner_audit": inner,
        "inner_audit_hash": inner["audit_hash"],
    }
    payload["audit_hash"] = stable_hash(payload)
    return payload


def test_np_source_verifies_complete_proposals_before_extracting_claims():
    payload = _np_payload()
    claims = extract_np_claims(
        payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        tick=1,
        messages_hash=DIGESTS[2],
        admission_audit_hash=DIGESTS[1],
        ledger_hash=DIGESTS[3],
    )
    assert claims.proposal_count == 1
    assert claims.proposal_claim_tuples[0][0] == "proposal-0001"

    tampered = deepcopy(payload)
    tampered["proposals"][0]["actor_id"] = "agent-tampered"
    tampered["batch_hash"] = stable_hash(
        {key: value for key, value in tampered.items() if key != "batch_hash"}
    )
    with pytest.raises(ValidationError, match="claim tuple does not match"):
        extract_np_claims(
            tampered,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            messages_hash=DIGESTS[2],
            admission_audit_hash=DIGESTS[1],
            ledger_hash=DIGESTS[3],
        )


def test_el_source_binds_every_decision_to_np_and_recomputes_hashes():
    np_payload = _np_payload()
    np_claims = extract_np_claims(
        np_payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        tick=1,
        messages_hash=DIGESTS[2],
        admission_audit_hash=DIGESTS[1],
        ledger_hash=DIGESTS[3],
    )
    payload = _el_payload(np_payload)
    claims = extract_el_claims(
        payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        tick=1,
        proposal_claims=np_claims,
    )
    assert claims.eligible_proposal_ids == ("proposal-0001",)

    tampered = deepcopy(payload)
    tampered["decisions"][0]["decision_hash"] = DIGESTS[7]
    with pytest.raises(ValidationError, match="decision_hash mismatch"):
        extract_el_claims(
            tampered,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            proposal_claims=np_claims,
        )


def test_cl_source_verifies_complete_proposal_event_chain_and_ledger_hash():
    payload = _cl_payload()
    claims = extract_cl_claims(
        payload, run_id=RUN_ID, session_id=SESSION_ID, tick=1
    )
    assert claims.ledger_entry_count == 1
    assert claims.commitments[0][2] == "proposed"

    tampered = deepcopy(payload)
    tampered["entries"][0]["events"][0]["event_hash"] = DIGESTS[7]
    tampered["ledger_hash"] = stable_hash(
        {
            "schema_version": "commitment-ledger.v2",
            "run_id": RUN_ID,
            "session_id": SESSION_ID,
            "tick": 1,
            "entries": tuple(tampered["entries"]),
        }
    )
    with pytest.raises(ValidationError, match="event_hash mismatch"):
        extract_cl_claims(
            tampered, run_id=RUN_ID, session_id=SESSION_ID, tick=1
        )


def test_source_extractors_reject_closed_schema_and_coordinate_drift():
    payload = _np_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        extract_np_claims(
            payload,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            messages_hash=DIGESTS[2],
            admission_audit_hash=DIGESTS[1],
            ledger_hash=DIGESTS[3],
        )

    empty = {
        "schema_version": "commitment-ledger.v2",
        "run_id": RUN_ID,
        "session_id": None,
        "tick": None,
        "entries": [],
        "ledger_entry_count": 0,
    }
    empty["ledger_hash"] = stable_hash(
        {
            "schema_version": "commitment-ledger.v2",
            "run_id": RUN_ID,
            "session_id": None,
            "tick": None,
            "entries": (),
        }
    )
    assert extract_cl_claims(
        empty, run_id=RUN_ID, session_id=None, tick=None
    ).ledger_entry_count == 0
    with pytest.raises(ValueError, match="coordinate"):
        extract_cl_claims(empty, run_id=RUN_ID, session_id=SESSION_ID, tick=1)


@pytest.mark.parametrize("attempted", [False, True])
def test_nd_source_recomputes_fixed_point_claims_and_preserves_empty_audit(attempted):
    payload = _nd_payload(attempted=attempted)
    claims = extract_nd_claims(
        payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        tick=1,
        effective_seed=17,
    )
    assert claims.attempted is attempted
    assert claims.tone_delta_tuples[0] == ("firm", 30000)
    assert claims.application_count == int(attempted)
    if not attempted:
        assert claims.before_result_hash == claims.after_result_hash
        assert claims.country_delta_tuples == ()


def test_nd_source_rejects_fixed_point_and_seed_tampering_even_with_local_rehash():
    payload = _nd_payload(attempted=True)
    payload["application_tuples"][0] = (
        *payload["application_tuples"][0][:8],
        5000,
        *payload["application_tuples"][0][9:],
    )
    payload["diffusion_evidence_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "diffusion_evidence_hash"}
    )
    with pytest.raises(ValidationError, match="application tuple/count mismatch"):
        extract_nd_claims(
            payload,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            effective_seed=17,
        )

    valid = _nd_payload(attempted=False)
    with pytest.raises(ValueError, match="coordinate/seed"):
        extract_nd_claims(
            valid,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            effective_seed=18,
        )


def test_mb_and_pa_sources_bind_legacy_adapter_output_to_v2_projection_claims():
    mb_payload = _mb_payload()
    mb_claims = extract_mb_claims(
        mb_payload,
        run_id=RUN_ID,
        tick=1,
        consistency_audit_hash=DIGESTS[1],
    )
    pa_payload = _pa_payload(mb_payload)
    pa_claims = extract_pa_claims(
        pa_payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        tick=1,
        projection_mode="negotiation",
        consistency_audit_hash=DIGESTS[1],
        complete_proposals=(_proposal(),),
        modifier_claims=mb_claims,
    )
    assert mb_claims.inner_bundle_hash == mb_payload["inner_bundle_hash"]
    assert pa_claims.session_id == SESSION_ID
    assert pa_claims.proposal_count == 1
    assert pa_claims.projected_count == 1
    assert pa_claims.projected_proposal_ids == ("proposal-0001",)
    assert pa_claims.modifier_tuples == mb_claims.modifier_tuples


def test_mb_source_rejects_reidentified_or_duplicated_legacy_modifiers():
    reidentified = _mb_payload()
    reidentified["inner_bundle"]["modifiers"][0]["modifier_id"] = "modifier_reidentified"
    reidentified["modifiers"][0]["modifier_id"] = "modifier_reidentified"
    reidentified["modifier_tuples"][0]["modifier_id"] = "modifier_reidentified"
    reidentified["inner_bundle"]["bundle_hash"] = stable_hash(
        {
            key: value
            for key, value in reidentified["inner_bundle"].items()
            if key != "bundle_hash"
        }
    )
    reidentified["inner_bundle_hash"] = reidentified["inner_bundle"]["bundle_hash"]
    reidentified["bundle_hash"] = stable_hash(
        {key: value for key, value in reidentified.items() if key != "bundle_hash"}
    )
    with pytest.raises(ValidationError, match="outer modifier hash"):
        extract_mb_claims(
            reidentified,
            run_id=RUN_ID,
            tick=1,
            consistency_audit_hash=DIGESTS[1],
        )

    duplicated = _mb_payload()
    duplicated["inner_bundle"]["accepted_proposal_ids"].append("proposal-0001")
    duplicated["inner_bundle"]["modifiers"].append(
        deepcopy(duplicated["inner_bundle"]["modifiers"][0])
    )
    duplicated["inner_bundle"]["bundle_hash"] = stable_hash(
        {
            key: value
            for key, value in duplicated["inner_bundle"].items()
            if key != "bundle_hash"
        }
    )
    duplicated["inner_bundle_hash"] = duplicated["inner_bundle"]["bundle_hash"]
    duplicated["bundle_hash"] = stable_hash(
        {key: value for key, value in duplicated.items() if key != "bundle_hash"}
    )
    with pytest.raises(ValidationError, match="mapping mismatch"):
        extract_mb_claims(
            duplicated,
            run_id=RUN_ID,
            tick=1,
            consistency_audit_hash=DIGESTS[1],
        )


def test_pa_truth_table_and_semantic_hash_fail_closed_after_local_rehash():
    mb_payload = _mb_payload()
    mb_claims = extract_mb_claims(
        mb_payload,
        run_id=RUN_ID,
        tick=1,
        consistency_audit_hash=DIGESTS[1],
    )
    pa_payload = _pa_payload(mb_payload)
    pa_payload["records"][0]["rejection_reason"] = "not allowed for projected"
    pa_payload["audit_hash"] = stable_hash(
        {key: value for key, value in pa_payload.items() if key != "audit_hash"}
    )
    with pytest.raises(ValidationError, match="truth table"):
        extract_pa_claims(
            pa_payload,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            projection_mode="negotiation",
            consistency_audit_hash=DIGESTS[1],
            complete_proposals=(_proposal(),),
            modifier_claims=mb_claims,
        )

    semantic_tamper = _pa_payload(mb_payload)
    semantic_tamper["projected_semantic_key_hashes"] = [DIGESTS[7]]
    semantic_tamper["audit_hash"] = stable_hash(
        {key: value for key, value in semantic_tamper.items() if key != "audit_hash"}
    )
    with pytest.raises(ValueError, match="semantic hash mismatch"):
        extract_pa_claims(
            semantic_tamper,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=1,
            projection_mode="negotiation",
            consistency_audit_hash=DIGESTS[1],
            complete_proposals=(_proposal(),),
            modifier_claims=mb_claims,
        )

    wrong_schema_mode = _pa_payload(mb_payload)
    wrong_schema_mode["schema_version"] = "agent-action-projection-audit.v2"
    wrong_schema_mode["session_id"] = None
    wrong_schema_mode["tick"] = None
    wrong_schema_mode["audit_hash"] = stable_hash(
        {key: value for key, value in wrong_schema_mode.items() if key != "audit_hash"}
    )
    with pytest.raises(ValidationError, match="may not use negotiation"):
        extract_pa_claims(
            wrong_schema_mode,
            run_id=RUN_ID,
            session_id=None,
            tick=None,
            projection_mode="negotiation",
            consistency_audit_hash=DIGESTS[1],
            complete_proposals=(_proposal(),),
            modifier_claims=mb_claims,
        )


@pytest.mark.parametrize("role", ["final", "admission", "projection"])
def test_consistency_v3_source_binds_inner_v2_context_and_synthetic_time(role):
    payload = _consistency_payload(role=role)
    context = role != "final"
    claims = extract_consistency_claims(
        payload,
        run_id=RUN_ID,
        role=role,
        tick=None if role == "final" else 1,
        evaluator_version="worldpulse-consistency.v0.8",
        agent_pack_id="agent-pack-test" if context else None,
        agent_pack_hash=DIGESTS[5] if context else None,
        constraint_context_hash=DIGESTS[6] if context else None,
        complete_proposals=(_proposal(),),
    )
    assert claims.accepted_proposal_ids == ("proposal-0001",)
    assert claims.decision_tuples[0][3] == claims.proposal_hashes[0]


def test_consistency_v3_rejects_inner_schema_and_time_drift_after_rehash():
    payload = _consistency_payload(role="admission")
    payload["inner_audit"]["created_at"] = "2000-01-01T00:00:09.000Z"
    payload["inner_audit"]["unexpected"] = True
    payload["inner_audit"]["audit_hash"] = stable_hash(
        {
            key: value
            for key, value in payload["inner_audit"].items()
            if key not in {"run_id", "created_at", "audit_hash"}
        }
    )
    payload["inner_audit_hash"] = payload["inner_audit"]["audit_hash"]
    payload["audit_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    with pytest.raises(ValidationError, match="exact closed field set"):
        extract_consistency_claims(
            payload,
            run_id=RUN_ID,
            role="admission",
            tick=1,
            evaluator_version="worldpulse-consistency.v0.8",
            agent_pack_id="agent-pack-test",
            agent_pack_hash=DIGESTS[5],
            constraint_context_hash=DIGESTS[6],
            complete_proposals=(_proposal(),),
        )


def test_consistency_v3_rejects_reordered_inner_decisions_after_local_rehash():
    first = _proposal()
    second = deepcopy(first)
    second["proposal_id"] = "proposal-0002"
    payload = _consistency_payload(role="admission")
    first_decision = payload["inner_audit"]["proposal_decisions"][0]
    second_decision = deepcopy(first_decision)
    second_decision["proposal_id"] = second["proposal_id"]
    second_decision["input_hash"] = stable_hash(second)
    second_decision["audit_hash"] = stable_hash(
        {key: value for key, value in second_decision.items() if key != "audit_hash"}
    )
    payload["proposal_ids"] = [first["proposal_id"], second["proposal_id"]]
    payload["proposal_hashes"] = [stable_hash(first), stable_hash(second)]
    payload["inner_audit"]["proposal_decisions"] = [second_decision, first_decision]
    payload["inner_audit"]["audit_hash"] = stable_hash(
        {
            key: value
            for key, value in payload["inner_audit"].items()
            if key not in {"run_id", "created_at", "audit_hash"}
        }
    )
    payload["inner_audit_hash"] = payload["inner_audit"]["audit_hash"]
    payload["audit_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    with pytest.raises(ValueError, match="decision order"):
        extract_consistency_claims(
            payload,
            run_id=RUN_ID,
            role="admission",
            tick=1,
            evaluator_version="worldpulse-consistency.v0.8",
            agent_pack_id="agent-pack-test",
            agent_pack_hash=DIGESTS[5],
            constraint_context_hash=DIGESTS[6],
            complete_proposals=(first, second),
        )
