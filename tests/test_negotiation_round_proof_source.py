from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.consistency.hashing import stable_hash
from app.services.negotiation import extract_rr_claims


RUN_ID = "round-proof-run"
SESSION_ID = "round-proof-session"
DIGESTS = tuple(stable_hash({"digest": index}) for index in range(16))


def _proposal(*, proposal_id: str = "proposal-0001") -> dict:
    return {
        "proposal_id": proposal_id,
        "schema_version": "agent-action-proposal.v1",
        "run_id": RUN_ID,
        "turn": 1,
        "actor_id": "agent-alpha",
        "actor_type": "diplomacy",
        "action_type": "diplomatic_signal",
        "target_ids": ["country:USA"],
        "parameters": {
            "signal": "firm",
            "channel": "backchannel",
            "public": False,
        },
        "justification": "Verified evidence supports this governed action.",
        "evidence_refs": ["evidence-0001"],
        "expected_direction": "coordinate",
        "confidence": 70.0,
        "created_at": "2000-01-01T00:00:01.000Z",
        "expires_after_turn": 3,
    }


def _round_id(tick: int) -> str:
    return f"round_{stable_hash({'session': SESSION_ID, 'tick': tick})[:20]}"


def _message_identity(message: dict) -> str:
    proposal = (
        message["payload"]["proposal"]
        if message["proposal_id"] is not None
        else None
    )
    return stable_hash(
        {
            "tick": message["tick"],
            "seq": message["seq"],
            "sender_agent_id": message["sender_agent_id"],
            "recipient_agent_ids": message["recipient_agent_ids"],
            "message_type": message["message_type"],
            "visibility": message["visibility"],
            "parent_message_id": message["parent_message_id"],
            "proposal": proposal,
            "narrative": message["narrative"],
            "previous_hash": message["previous_hash"],
        }
    )


def _message(
    *,
    tick: int = 1,
    seq: int = 1,
    previous_hash: str | None = None,
    proposal: dict | None = None,
) -> dict:
    complete_proposal = _proposal() if proposal is None else proposal
    message = {
        "message_id": "pending",
        "session_id": SESSION_ID,
        "round_id": _round_id(tick),
        "tick": tick,
        "seq": seq,
        "sender_agent_id": "agent-alpha",
        "recipient_agent_ids": ["agent-beta"],
        "message_type": "proposal",
        "visibility": "direct",
        "parent_message_id": None,
        "proposal_id": complete_proposal["proposal_id"],
        "narrative": "Coordinate a governed diplomatic response.",
        "payload": {"proposal": complete_proposal},
        "provider": "mock-deterministic",
        "model": "negotiation-test",
        "latency_ms": 4,
        "estimated_tokens": 12,
        "fallback_used": False,
        "previous_hash": previous_hash,
        "message_hash": "pending",
        "created_at": "2000-01-01T00:00:02.000Z",
    }
    message_hash = _message_identity(message)
    message["message_hash"] = message_hash
    message["message_id"] = f"msg_{message_hash[:20]}"
    return message


def _rehash_outer(payload: dict) -> None:
    payload["input_hash"] = stable_hash(
        {
            "schema_version": payload["schema_version"],
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "round_id": payload["round_id"],
            "tick": payload["tick"],
            "input": payload["input"],
        }
    )
    payload["output_hash"] = stable_hash(
        {
            "schema_version": payload["schema_version"],
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "round_id": payload["round_id"],
            "tick": payload["tick"],
            "output": payload["output"],
        }
    )
    payload["round_hash"] = stable_hash(
        {
            "schema_version": payload["schema_version"],
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "round_id": payload["round_id"],
            "tick": payload["tick"],
            "input_hash": payload["input_hash"],
            "output_hash": payload["output_hash"],
        }
    )


def _sync_messages(payload: dict) -> None:
    messages = payload["input"]["messages"]
    for message in messages:
        message_hash = _message_identity(message)
        message["message_hash"] = message_hash
        message["message_id"] = f"msg_{message_hash[:20]}"
    payload["input"]["message_tuples"] = [
        [message["seq"], message["message_id"], message["message_hash"]]
        for message in messages
    ]
    payload["input"]["message_count"] = len(messages)
    payload["input"]["proposal_ids"] = sorted(
        message["proposal_id"]
        for message in messages
        if message["proposal_id"] is not None
    )
    payload["input"]["messages_hash"] = stable_hash(
        {
            "schema_version": payload["schema_version"],
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "tick": payload["tick"],
            "message_tuples": payload["input"]["message_tuples"],
        }
    )
    _rehash_outer(payload)


def _round_payload(
    *,
    tick: int = 1,
    messages: list[dict] | None = None,
    projected: bool = True,
) -> dict:
    complete_messages = [_message(tick=tick)] if messages is None else messages
    proposal_ids = sorted(
        message["proposal_id"]
        for message in complete_messages
        if message["proposal_id"] is not None
    )
    message_tuples = [
        [message["seq"], message["message_id"], message["message_hash"]]
        for message in complete_messages
    ]
    before_hash = DIGESTS[0]
    payload = {
        "schema_version": "negotiation-round.v2",
        "run_id": RUN_ID,
        "session_id": SESSION_ID,
        "round_id": _round_id(tick),
        "tick": tick,
        "input": {
            "before_result_hash": before_hash,
            "message_tuples": message_tuples,
            "messages": complete_messages,
            "messages_hash": stable_hash(
                {
                    "schema_version": "negotiation-round.v2",
                    "run_id": RUN_ID,
                    "session_id": SESSION_ID,
                    "tick": tick,
                    "message_tuples": message_tuples,
                }
            ),
            "message_count": len(complete_messages),
            "proposal_ids": proposal_ids,
            "accepted_proposal_ids": proposal_ids,
            "proposal_batch_hash": DIGESTS[1],
            "admission_audit_hash": DIGESTS[2],
            "ledger_hash": DIGESTS[3],
            "eligibility_hash": DIGESTS[4],
            "eligible_proposal_ids": proposal_ids,
        },
        "input_hash": "pending",
        "output": {
            "projection_consistency_hash": DIGESTS[5] if projected else None,
            "modifier_bundle_hash": DIGESTS[6] if projected else None,
            "diffusion_evidence_hash": DIGESTS[7],
            "projection_audit_hash": DIGESTS[8] if projected else None,
            "no_projection_reason": None if projected else "no_projection",
            "after_result_hash": DIGESTS[9] if projected else before_hash,
        },
        "output_hash": "pending",
        "round_hash": "pending",
    }
    _rehash_outer(payload)
    return payload


def _extract(
    payload: dict,
    *,
    tick: int = 1,
    expected_first_seq: int = 1,
    expected_previous_hash: str | None = None,
):
    return extract_rr_claims(
        payload,
        run_id=RUN_ID,
        session_id=SESSION_ID,
        tick=tick,
        expected_first_seq=expected_first_seq,
        expected_previous_hash=expected_previous_hash,
    )


@pytest.mark.parametrize("projected", [False, True])
def test_rr_extracts_complete_round_claims(projected: bool):
    payload = _round_payload(projected=projected)

    claims = _extract(payload)

    assert claims.round_hash == payload["round_hash"]
    assert claims.message_count == 1
    assert claims.message_tuples[0][1] == payload["input"]["messages"][0]["message_id"]
    assert claims.projection_consistency_hash == (
        DIGESTS[5] if projected else None
    )
    assert claims.no_projection_reason == (None if projected else "no_projection")


def test_rr_accepts_empty_tick_without_advancing_the_authenticated_chain():
    payload = _round_payload(tick=2, messages=[], projected=False)

    claims = _extract(
        payload,
        tick=2,
        expected_first_seq=2,
        expected_previous_hash=DIGESTS[10],
    )

    assert claims.message_count == 0
    assert claims.message_tuples == ()
    assert claims.proposal_ids == ()


def test_rr_rejects_extra_and_missing_keys_at_every_closed_layer():
    mutations = []

    outer_extra = _round_payload()
    outer_extra["unexpected"] = True
    mutations.append(outer_extra)

    outer_missing = _round_payload()
    del outer_missing["round_hash"]
    mutations.append(outer_missing)

    input_extra = _round_payload()
    input_extra["input"]["unexpected"] = True
    mutations.append(input_extra)

    input_missing = _round_payload()
    del input_missing["input"]["ledger_hash"]
    mutations.append(input_missing)

    output_extra = _round_payload()
    output_extra["output"]["unexpected"] = True
    mutations.append(output_extra)

    output_missing = _round_payload()
    del output_missing["output"]["projection_audit_hash"]
    mutations.append(output_missing)

    message_extra = _round_payload()
    message_extra["input"]["messages"][0]["unexpected"] = True
    mutations.append(message_extra)

    message_missing = _round_payload()
    del message_missing["input"]["messages"][0]["provider"]
    mutations.append(message_missing)

    proposal_extra = _round_payload()
    proposal_extra["input"]["messages"][0]["payload"]["proposal"][
        "unexpected"
    ] = True
    mutations.append(proposal_extra)

    for payload in mutations:
        with pytest.raises(ValidationError):
            _extract(payload)


def test_rr_rejects_authoritative_coordinate_and_round_id_drift():
    payload = _round_payload()
    with pytest.raises(ValueError, match="coordinate"):
        extract_rr_claims(
            payload,
            run_id="other-run",
            session_id=SESSION_ID,
            tick=1,
            expected_first_seq=1,
            expected_previous_hash=None,
        )

    with pytest.raises(ValueError, match="coordinate"):
        _extract(payload, tick=2)

    wrong_round = _round_payload()
    wrong_round["round_id"] = "round_caller_selected"
    wrong_round["input"]["messages"][0]["round_id"] = "round_caller_selected"
    _sync_messages(wrong_round)
    with pytest.raises(ValidationError, match="canonical session/tick"):
        _extract(wrong_round)

    wrong_message = _round_payload()
    wrong_message["input"]["messages"][0]["session_id"] = "other-session"
    _sync_messages(wrong_message)
    with pytest.raises(ValidationError, match="message session/round"):
        _extract(wrong_message)


def test_rr_recomputes_message_identity_and_wrapper_proposal_binding():
    wrong_hash = _round_payload()
    wrong_hash["input"]["messages"][0]["sender_agent_id"] = "agent-tampered"
    _rehash_outer(wrong_hash)
    with pytest.raises(ValidationError, match="message_hash mismatch"):
        _extract(wrong_hash)

    wrong_id = _round_payload()
    wrong_id["input"]["messages"][0]["message_id"] = "msg_wrong"
    wrong_id["input"]["message_tuples"][0][1] = "msg_wrong"
    wrong_id["input"]["messages_hash"] = stable_hash(
        {
            "schema_version": wrong_id["schema_version"],
            "run_id": wrong_id["run_id"],
            "session_id": wrong_id["session_id"],
            "tick": wrong_id["tick"],
            "message_tuples": wrong_id["input"]["message_tuples"],
        }
    )
    _rehash_outer(wrong_id)
    with pytest.raises(ValidationError, match="message_id mismatch"):
        _extract(wrong_id)

    wrong_proposal_id = _round_payload()
    wrong_proposal_id["input"]["messages"][0]["proposal_id"] = "proposal-9999"
    _rehash_outer(wrong_proposal_id)
    with pytest.raises(ValidationError, match="proposal_id mismatch"):
        _extract(wrong_proposal_id)


def test_rr_rejects_noncanonical_and_numeric_authority_proposals_after_rehash():
    noncanonical = _round_payload()
    noncanonical["input"]["messages"][0]["payload"]["proposal"]["confidence"] = 70
    _sync_messages(noncanonical)
    with pytest.raises(ValidationError, match="already be canonical"):
        _extract(noncanonical)

    numeric_authority = _round_payload()
    numeric_authority["input"]["messages"][0]["payload"]["proposal"][
        "parameters"
    ]["risk_score"] = 99.0
    _sync_messages(numeric_authority)
    with pytest.raises(ValidationError, match="numeric authority"):
        _extract(numeric_authority)


def test_rr_rejects_tuple_sequence_and_local_predecessor_drift():
    tuple_drift = _round_payload()
    tuple_drift["input"]["message_tuples"][0][0] = 2
    tuple_drift["input"]["messages_hash"] = stable_hash(
        {
            "schema_version": tuple_drift["schema_version"],
            "run_id": tuple_drift["run_id"],
            "session_id": tuple_drift["session_id"],
            "tick": tuple_drift["tick"],
            "message_tuples": tuple_drift["input"]["message_tuples"],
        }
    )
    _rehash_outer(tuple_drift)
    with pytest.raises(ValidationError, match="tuples must align"):
        _extract(tuple_drift)

    first = _message(tick=2, seq=2, previous_hash=DIGESTS[10])
    second = _message(
        tick=2,
        seq=3,
        previous_hash=DIGESTS[11],
        proposal=_proposal(proposal_id="proposal-0002"),
    )
    broken_chain = _round_payload(
        tick=2,
        messages=[first, second],
        projected=True,
    )
    with pytest.raises(ValidationError, match="predecessor chain"):
        _extract(
            broken_chain,
            tick=2,
            expected_first_seq=2,
            expected_previous_hash=DIGESTS[10],
        )

    gap_second = _message(
        tick=2,
        seq=4,
        previous_hash=first["message_hash"],
        proposal=_proposal(proposal_id="proposal-0002"),
    )
    sequence_gap = _round_payload(tick=2, messages=[first, gap_second])
    with pytest.raises(ValidationError, match="seq must be contiguous"):
        _extract(
            sequence_gap,
            tick=2,
            expected_first_seq=2,
            expected_previous_hash=DIGESTS[10],
        )


def test_rr_binds_first_message_to_run_control_chain_context():
    first = _message(tick=2, seq=2, previous_hash=DIGESTS[10])
    payload = _round_payload(tick=2, messages=[first])

    assert _extract(
        payload,
        tick=2,
        expected_first_seq=2,
        expected_previous_hash=DIGESTS[10],
    ).message_count == 1

    with pytest.raises(ValueError, match="authenticated chain"):
        _extract(
            payload,
            tick=2,
            expected_first_seq=3,
            expected_previous_hash=DIGESTS[10],
        )
    with pytest.raises(ValueError, match="authenticated chain"):
        _extract(
            payload,
            tick=2,
            expected_first_seq=2,
            expected_previous_hash=DIGESTS[11],
        )

    with pytest.raises(ValueError, match="message boundary"):
        _extract(
            _round_payload(tick=2, messages=[], projected=False),
            tick=2,
            expected_first_seq=2,
            expected_previous_hash=None,
        )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        extract_rr_claims(
            payload,
            run_id=RUN_ID,
            session_id=SESSION_ID,
            tick=2,
            expected_first_seq=2,
            expected_previous_hash=123,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="first tick"):
        _extract(
            _round_payload(),
            expected_first_seq=2,
            expected_previous_hash=DIGESTS[10],
        )


@pytest.mark.parametrize(
    "field",
    ["messages_hash", "input_hash", "output_hash", "round_hash"],
)
def test_rr_recomputes_every_local_digest(field: str):
    payload = _round_payload()
    if field == "messages_hash":
        payload["input"][field] = DIGESTS[15]
    else:
        payload[field] = DIGESTS[15]

    with pytest.raises(ValidationError, match=f"{field} mismatch"):
        _extract(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("modifier_bundle_hash", None),
        ("projection_audit_hash", None),
        ("no_projection_reason", "no_projection"),
    ],
)
def test_rr_rejects_incomplete_projected_output(field: str, value: object):
    payload = _round_payload(projected=True)
    payload["output"][field] = value
    _rehash_outer(payload)

    with pytest.raises(ValidationError, match="projected output"):
        _extract(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("projection_consistency_hash", DIGESTS[5]),
        ("modifier_bundle_hash", DIGESTS[6]),
        ("projection_audit_hash", DIGESTS[8]),
        ("no_projection_reason", None),
    ],
)
def test_rr_rejects_invalid_no_projection_output(field: str, value: object):
    payload = _round_payload(projected=False)
    payload["output"][field] = value
    _rehash_outer(payload)

    with pytest.raises(ValidationError, match="output binding"):
        _extract(payload)


def test_rr_rejects_strict_integer_and_claim_vector_coercions():
    boolean_seq = _round_payload()
    boolean_seq["input"]["messages"][0]["seq"] = True
    _sync_messages(boolean_seq)
    with pytest.raises(ValidationError):
        _extract(boolean_seq)

    boolean_count = _round_payload()
    boolean_count["input"]["message_count"] = True
    _rehash_outer(boolean_count)
    with pytest.raises(ValidationError):
        _extract(boolean_count)

    unordered = _round_payload()
    unordered["input"]["accepted_proposal_ids"] = ["proposal-z", "proposal-a"]
    _rehash_outer(unordered)
    with pytest.raises(ValidationError, match="unique and ascending"):
        _extract(unordered)

    scalar_ids = _round_payload()
    scalar_ids["input"]["accepted_proposal_ids"] = 7
    _rehash_outer(scalar_ids)
    with pytest.raises(ValidationError, match="array of strings"):
        _extract(scalar_ids)

    negative_runtime_counter = _round_payload()
    negative_runtime_counter["input"]["messages"][0]["latency_ms"] = -1
    _rehash_outer(negative_runtime_counter)
    with pytest.raises(ValidationError, match="runtime counters"):
        _extract(negative_runtime_counter)
