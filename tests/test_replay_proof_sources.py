from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.services.consistency.hashing import stable_hash
from app.services.negotiation import extract_hr_claims, extract_nr_claims


RUN_ID = "replay-proof-run"
SESSION_ID = "replay-proof-session"
DIGESTS = tuple(stable_hash({"digest": index}) for index in range(80))


def _rehash(payload: dict) -> None:
    payload["replay_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "replay_hash"}
    )


def _hr_payload(*, engine_mode: str = "hybrid") -> dict:
    payload = {
        "schema_version": "hybrid-replay-record.v2",
        "run_id": RUN_ID,
        "engine_mode": engine_mode,
        "replay_source_kind": "stored_only",
        "provider_calls_required": 0,
        "replay_hash": "pending",
        "baseline_result_hash": DIGESTS[0],
        "final_result_hash": DIGESTS[1],
        "full_source_run_hash": DIGESTS[2],
        "proposal_batch_hash": DIGESTS[3],
        "consistency_audit_hash": DIGESTS[4],
        "modifier_bundle_hash": DIGESTS[5],
        "projection_audit_hash": DIGESTS[6],
        "ledger_hash": DIGESTS[7],
        "accepted_proposal_ids": ["proposal-0001", "proposal-0002"],
    }
    _rehash(payload)
    return payload


def _nr_payload(*, message_chain_head: str | None = DIGESTS[70]) -> dict:
    payload = {
        "schema_version": "negotiation-replay.v2",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "baseline_result_hash": DIGESTS[0],
        "final_result_hash": DIGESTS[1],
        "round_hashes": list(DIGESTS[8:14]),
        "proposal_batch_hashes": list(DIGESTS[14:20]),
        "admission_audit_hashes": list(DIGESTS[20:26]),
        "ledger_hashes": list(DIGESTS[26:32]),
        "eligibility_hashes": list(DIGESTS[32:38]),
        "projection_consistency_hashes": [
            DIGESTS[38],
            None,
            DIGESTS[39],
            None,
            DIGESTS[40],
            None,
        ],
        "modifier_bundle_hashes": [
            DIGESTS[41],
            None,
            DIGESTS[42],
            None,
            DIGESTS[43],
            None,
        ],
        "diffusion_evidence_hashes": list(DIGESTS[44:50]),
        "projection_audit_hashes": [
            DIGESTS[50],
            None,
            DIGESTS[51],
            None,
            DIGESTS[52],
            None,
        ],
        "message_chain_head": message_chain_head,
        "provider_calls_required": 0,
        "replay_hash": "pending",
    }
    _rehash(payload)
    return payload


@pytest.mark.parametrize("engine_mode", ["hybrid", "hybrid_recorded"])
def test_hr_extracts_complete_provider_free_replay_claims(engine_mode: str):
    payload = _hr_payload(engine_mode=engine_mode)

    claims = extract_hr_claims(
        payload,
        run_id=RUN_ID,
        engine_mode=engine_mode,
    )

    assert claims.replay_hash == payload["replay_hash"]
    assert claims.engine_mode == engine_mode
    assert claims.replay_source_kind == "stored_only"
    assert claims.provider_calls_required == 0
    assert claims.accepted_proposal_ids == ("proposal-0001", "proposal-0002")


def test_hr_rejects_closed_schema_and_fixed_field_drift():
    mutations = []

    extra = _hr_payload()
    extra["unexpected"] = True
    mutations.append(extra)

    missing = _hr_payload()
    del missing["ledger_hash"]
    mutations.append(missing)

    wrong_schema = _hr_payload()
    wrong_schema["schema_version"] = "hybrid-replay-record.v1"
    mutations.append(wrong_schema)

    wrong_source = _hr_payload()
    wrong_source["replay_source_kind"] = "provider"
    mutations.append(wrong_source)

    boolean_provider_calls = _hr_payload()
    boolean_provider_calls["provider_calls_required"] = False
    mutations.append(boolean_provider_calls)

    for payload in mutations:
        with pytest.raises(ValidationError):
            extract_hr_claims(payload, run_id=RUN_ID, engine_mode="hybrid")


def test_hr_recomputes_hash_and_rejects_id_ordering_or_coordinate_drift():
    hash_drift = _hr_payload()
    hash_drift["full_source_run_hash"] = DIGESTS[79]
    with pytest.raises(ValidationError, match="replay_hash mismatch"):
        extract_hr_claims(hash_drift, run_id=RUN_ID, engine_mode="hybrid")

    unordered = _hr_payload()
    unordered["accepted_proposal_ids"] = ["proposal-0002", "proposal-0001"]
    _rehash(unordered)
    with pytest.raises(ValidationError, match="ascending"):
        extract_hr_claims(unordered, run_id=RUN_ID, engine_mode="hybrid")

    duplicate = _hr_payload()
    duplicate["accepted_proposal_ids"] = ["proposal-0001", "proposal-0001"]
    _rehash(duplicate)
    with pytest.raises(ValidationError, match="unique"):
        extract_hr_claims(duplicate, run_id=RUN_ID, engine_mode="hybrid")

    payload = _hr_payload()
    with pytest.raises(ValueError, match="run/mode"):
        extract_hr_claims(payload, run_id="other-run", engine_mode="hybrid")
    with pytest.raises(ValueError, match="run/mode"):
        extract_hr_claims(
            payload,
            run_id=RUN_ID,
            engine_mode="hybrid_recorded",
        )


@pytest.mark.parametrize("message_chain_head", [None, DIGESTS[70]])
def test_nr_extracts_six_tick_provider_free_replay_claims(
    message_chain_head: str | None,
):
    payload = _nr_payload(message_chain_head=message_chain_head)

    claims = extract_nr_claims(
        payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
    )

    assert claims.replay_hash == payload["replay_hash"]
    assert len(claims.round_hashes) == 6
    assert claims.projection_consistency_hashes[1] is None
    assert claims.message_chain_head == message_chain_head
    assert claims.provider_calls_required == 0


def test_nr_rejects_closed_schema_hash_and_coordinate_drift():
    extra = _nr_payload()
    extra["unexpected"] = True
    with pytest.raises(ValidationError):
        extract_nr_claims(extra, run_id=RUN_ID, session_id=SESSION_ID)

    missing = _nr_payload()
    del missing["message_chain_head"]
    with pytest.raises(ValidationError):
        extract_nr_claims(missing, run_id=RUN_ID, session_id=SESSION_ID)

    wrong_schema = _nr_payload()
    wrong_schema["schema_version"] = "negotiation-replay.v1"
    _rehash(wrong_schema)
    with pytest.raises(ValidationError):
        extract_nr_claims(wrong_schema, run_id=RUN_ID, session_id=SESSION_ID)

    hash_drift = _nr_payload()
    hash_drift["final_result_hash"] = DIGESTS[79]
    with pytest.raises(ValidationError, match="replay_hash mismatch"):
        extract_nr_claims(hash_drift, run_id=RUN_ID, session_id=SESSION_ID)

    valid = _nr_payload()
    with pytest.raises(ValueError, match="run/session"):
        extract_nr_claims(valid, run_id="other-run", session_id=SESSION_ID)
    with pytest.raises(ValueError, match="run/session"):
        extract_nr_claims(valid, run_id=RUN_ID, session_id="other-session")


def test_nr_rejects_vector_shape_digest_and_provider_call_coercion():
    short_vector = _nr_payload()
    short_vector["round_hashes"].pop()
    _rehash(short_vector)
    with pytest.raises(ValidationError, match="six entries"):
        extract_nr_claims(short_vector, run_id=RUN_ID, session_id=SESSION_ID)

    null_unconditional = _nr_payload()
    null_unconditional["ledger_hashes"][2] = None
    _rehash(null_unconditional)
    with pytest.raises(ValidationError):
        extract_nr_claims(
            null_unconditional,
            run_id=RUN_ID,
            session_id=SESSION_ID,
        )

    invalid_conditional = _nr_payload()
    invalid_conditional["modifier_bundle_hashes"][1] = "not-a-digest"
    _rehash(invalid_conditional)
    with pytest.raises(ValidationError):
        extract_nr_claims(
            invalid_conditional,
            run_id=RUN_ID,
            session_id=SESSION_ID,
        )

    boolean_provider_calls = _nr_payload()
    boolean_provider_calls["provider_calls_required"] = False
    _rehash(boolean_provider_calls)
    with pytest.raises(ValidationError, match="integer 0"):
        extract_nr_claims(
            boolean_provider_calls,
            run_id=RUN_ID,
            session_id=SESSION_ID,
        )


def test_nr_replay_hash_covers_every_tick_vector_and_nullable_head():
    fields = (
        "round_hashes",
        "proposal_batch_hashes",
        "admission_audit_hashes",
        "ledger_hashes",
        "eligibility_hashes",
        "projection_consistency_hashes",
        "modifier_bundle_hashes",
        "diffusion_evidence_hashes",
        "projection_audit_hashes",
    )
    for field in fields:
        payload = _nr_payload()
        payload[field][0] = DIGESTS[79]
        with pytest.raises(ValidationError, match="replay_hash mismatch"):
            extract_nr_claims(payload, run_id=RUN_ID, session_id=SESSION_ID)

    head_drift = deepcopy(_nr_payload())
    head_drift["message_chain_head"] = None
    with pytest.raises(ValidationError, match="replay_hash mismatch"):
        extract_nr_claims(head_drift, run_id=RUN_ID, session_id=SESSION_ID)
