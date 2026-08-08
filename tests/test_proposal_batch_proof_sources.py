from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract.mock_agent import build_mock_agent_batch
from app.services.consistency.hashing import stable_hash
from app.services.negotiation.proof_sources import (
    MockAgentBatchSource,
    extract_pb_claims,
    mock_agent_batch_source_hash,
)
from app.services.war_room_engine import run_war_room


RUN_ID = "proposal-batch-proof-run"
RUNTIME_HASH = stable_hash({"runtime": "verified"})


def _proposal(ordinal: int = 1) -> dict:
    return {
        "proposal_id": f"proposal-{ordinal:04d}",
        "schema_version": "agent-action-proposal.v1",
        "run_id": RUN_ID,
        "turn": 1,
        "actor_id": f"agent-{ordinal:04d}",
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


def _rehash(payload: dict) -> None:
    payload["batch_hash"] = stable_hash(
        {
            "schema_version": payload["schema_version"],
            "run_id": payload["run_id"],
            "source_kind": payload["source_kind"],
            "source_runtime_hash": payload["source_runtime_hash"],
            "source_mock_batch_hash": payload["source_mock_batch_hash"],
            "proposal_ids": payload["proposal_ids"],
            "proposal_hashes": payload["proposal_hashes"],
            "proposals": payload["proposals"],
            "proposal_count": payload["proposal_count"],
        }
    )


def _context() -> dict:
    return {
        "schema_version": "agent-constraint-context.v1",
        "actor_capabilities": {},
        "action_budgets": {},
        "known_entities": ["country:USA"],
        "known_evidence_refs": ["evidence-0001"],
        "source_label": "explicit simulation capability envelope",
    }


def _mock_batch(proposals: list[dict]) -> dict:
    context = _context()
    identity: dict[str, object] = {
        "provider": "mock-deterministic",
        "seed": 42,
        "proposal_ids": [item["proposal_id"] for item in proposals],
    }
    if proposals:
        identity["constraint_context"] = context
    return {
        "schema_version": "mock-agent-batch.v1",
        "provider": "mock-deterministic",
        "seed": 42,
        "proposals": deepcopy(proposals),
        "constraint_context": context,
        "batch_hash": stable_hash(identity),
    }


def _mock_source_hash(proposals: list[dict]) -> str:
    source = MockAgentBatchSource.model_validate(_mock_batch(proposals))
    return mock_agent_batch_source_hash(source)


def _payload(*, source_kind: str = "agent_runtime", populated: bool = True) -> dict:
    proposals = [_proposal(1), _proposal(2)] if populated else []
    payload = {
        "schema_version": "kernel-proposal-batch.v1",
        "run_id": RUN_ID,
        "source_kind": source_kind,
        "source_runtime_hash": RUNTIME_HASH if source_kind == "agent_runtime" else None,
        "source_mock_batch_hash": _mock_source_hash(proposals) if source_kind == "mock_batch" else None,
        "proposal_ids": [item["proposal_id"] for item in proposals],
        "proposal_hashes": [stable_hash(item) for item in proposals],
        "proposals": proposals,
        "proposal_count": len(proposals),
        "batch_hash": "",
    }
    _rehash(payload)
    return payload


@pytest.mark.parametrize("source_kind", ["agent_runtime", "mock_batch"])
def test_extract_pb_claims_verifies_complete_source(source_kind: str) -> None:
    payload = _payload(source_kind=source_kind)

    claims = extract_pb_claims(
        payload,
        run_id=RUN_ID,
        expected_runtime_hash=RUNTIME_HASH if source_kind == "agent_runtime" else None,
        mock_batch_payload=_mock_batch(payload["proposals"])
        if source_kind == "mock_batch"
        else None,
    )

    assert claims.proposal_ids == ("proposal-0001", "proposal-0002")
    assert claims.proposal_hashes == tuple(payload["proposal_hashes"])
    assert claims.proposal_count == 2
    assert claims.batch_hash == payload["batch_hash"]


@pytest.mark.parametrize("source_kind", ["agent_runtime", "mock_batch"])
def test_extract_pb_claims_accepts_complete_empty_batch(source_kind: str) -> None:
    payload = _payload(source_kind=source_kind, populated=False)

    claims = extract_pb_claims(
        payload,
        run_id=RUN_ID,
        expected_runtime_hash=RUNTIME_HASH if source_kind == "agent_runtime" else None,
        mock_batch_payload=_mock_batch(payload["proposals"])
        if source_kind == "mock_batch"
        else None,
    )

    assert claims.proposal_ids == ()
    assert claims.proposal_count == 0


def test_pb_source_rejects_extra_or_missing_fields() -> None:
    extra = _payload()
    extra["unexpected"] = True
    missing = _payload()
    del missing["proposal_count"]

    with pytest.raises(ValidationError):
        extract_pb_claims(extra, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)
    with pytest.raises(ValidationError):
        extract_pb_claims(missing, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


@pytest.mark.parametrize(
    ("runtime_hash", "mock_hash"),
    [(None, None), (RUNTIME_HASH, stable_hash({"mock": "unexpected"}))],
)
def test_pb_source_rejects_invalid_source_hash_cardinality(
    runtime_hash: str | None, mock_hash: str | None
) -> None:
    payload = _payload()
    payload["source_runtime_hash"] = runtime_hash
    payload["source_mock_batch_hash"] = mock_hash
    _rehash(payload)

    with pytest.raises(ValueError, match="exactly one source hash"):
        extract_pb_claims(payload, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


def test_pb_source_rejects_outer_source_binding_drift() -> None:
    with pytest.raises(ValueError, match="source binding mismatch"):
        extract_pb_claims(
            _payload(),
            run_id=RUN_ID,
            expected_runtime_hash=stable_hash({"other": True}),
        )
    mock_pb = _payload(source_kind="mock_batch")
    with pytest.raises(ValueError, match="mock"):
        extract_pb_claims(
            mock_pb,
            run_id=RUN_ID,
            mock_batch_payload=_mock_batch([_proposal(3)]),
        )


def test_pb_source_rejects_canonical_run_drift() -> None:
    with pytest.raises(ValueError, match="source run_id mismatch"):
        extract_pb_claims(
            _payload(), run_id="other-run", expected_runtime_hash=RUNTIME_HASH
        )


@pytest.mark.parametrize("field", ["proposal_ids", "proposal_hashes", "proposal_count"])
def test_pb_source_rejects_proposal_vector_drift(field: str) -> None:
    payload = _payload()
    if field == "proposal_count":
        payload[field] = 1
    else:
        payload[field] = list(reversed(payload[field]))
    _rehash(payload)

    with pytest.raises(ValueError):
        extract_pb_claims(payload, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


def test_pb_source_rejects_duplicate_or_out_of_order_proposals() -> None:
    duplicate = _payload()
    duplicate["proposals"][1] = deepcopy(duplicate["proposals"][0])
    duplicate["proposal_ids"][1] = duplicate["proposal_ids"][0]
    duplicate["proposal_hashes"][1] = duplicate["proposal_hashes"][0]
    _rehash(duplicate)
    out_of_order = _payload()
    out_of_order["proposals"].reverse()
    out_of_order["proposal_ids"].reverse()
    out_of_order["proposal_hashes"].reverse()
    _rehash(out_of_order)

    with pytest.raises(ValueError):
        extract_pb_claims(duplicate, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)
    with pytest.raises(ValueError):
        extract_pb_claims(out_of_order, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


def test_pb_source_rejects_nested_proposal_run_and_extra_field() -> None:
    run_drift = _payload()
    run_drift["proposals"][0]["run_id"] = "other-run"
    _rehash(run_drift)
    extra = _payload()
    extra["proposals"][0]["unexpected"] = True
    _rehash(extra)

    with pytest.raises(ValueError, match="run_id mismatch"):
        extract_pb_claims(run_drift, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)
    with pytest.raises(ValueError, match="exactly"):
        extract_pb_claims(extra, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


def test_pb_source_rejects_batch_hash_and_numeric_authority_drift() -> None:
    hash_drift = _payload()
    hash_drift["batch_hash"] = stable_hash({"tampered": True})
    numeric = _payload()
    numeric["proposals"][0]["parameters"]["risk_score"] = 99
    _rehash(numeric)

    with pytest.raises(ValueError, match="batch_hash mismatch"):
        extract_pb_claims(hash_drift, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)
    with pytest.raises(ValidationError, match="numeric authority"):
        extract_pb_claims(numeric, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", 70),
        ("public", 0),
        ("public", "false"),
    ],
)
def test_pb_source_rejects_proposal_normalization_aliases(
    field: str, value: object
) -> None:
    payload = _payload()
    if field == "confidence":
        payload["proposals"][0][field] = value
    else:
        payload["proposals"][0]["parameters"][field] = value
    payload["proposal_hashes"][0] = stable_hash(payload["proposals"][0])
    _rehash(payload)

    with pytest.raises((ValueError, ValidationError), match="canonical|boolean"):
        extract_pb_claims(payload, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)


def test_pb_mock_source_binds_complete_proposals_not_only_hash() -> None:
    payload = _payload(source_kind="mock_batch")
    mock_source = _mock_batch(payload["proposals"])
    payload["proposals"][0]["justification"] = (
        "Different but structurally valid evidence-backed governed action."
    )
    payload["proposal_hashes"][0] = stable_hash(payload["proposals"][0])
    _rehash(payload)

    with pytest.raises(ValueError, match="proposals drift"):
        extract_pb_claims(
            payload,
            run_id=RUN_ID,
            mock_batch_payload=mock_source,
        )


def test_pb_mock_source_recomputes_legacy_and_complete_source_hashes() -> None:
    payload = _payload(source_kind="mock_batch")
    mock_source = _mock_batch(payload["proposals"])
    mock_source["batch_hash"] = stable_hash({"tampered": True})

    with pytest.raises(ValueError, match="legacy batch_hash mismatch"):
        extract_pb_claims(
            payload,
            run_id=RUN_ID,
            mock_batch_payload=mock_source,
        )


def test_pb_accepts_real_mock_builder_generation_order() -> None:
    result = run_war_room(
        WarRoomScenarioRequest(scenario_key="strait_blockade_30d", seed=42)
    )
    mock = build_mock_agent_batch(result, run_id=RUN_ID, seed=42)
    mock_payload = mock.model_dump(mode="json")
    source = MockAgentBatchSource.model_validate(mock_payload)
    proposals = sorted(
        deepcopy(mock_payload["proposals"]),
        key=lambda item: item["proposal_id"].encode("utf-8"),
    )
    payload = {
        "schema_version": "kernel-proposal-batch.v1",
        "run_id": RUN_ID,
        "source_kind": "mock_batch",
        "source_runtime_hash": None,
        "source_mock_batch_hash": mock_agent_batch_source_hash(source),
        "proposal_ids": [item["proposal_id"] for item in proposals],
        "proposal_hashes": [stable_hash(item) for item in proposals],
        "proposals": proposals,
        "proposal_count": len(proposals),
        "batch_hash": "",
    }
    _rehash(payload)

    claims = extract_pb_claims(
        payload,
        run_id=RUN_ID,
        mock_batch_payload=mock_payload,
    )

    assert claims.proposal_ids == tuple(item["proposal_id"] for item in proposals)
    assert set(claims.proposal_ids) == {
        item["proposal_id"] for item in mock_payload["proposals"]
    }


def test_pb_source_rejects_wrong_discriminator_and_conflicting_inputs() -> None:
    wrong_kind = _payload()
    wrong_kind["source_kind"] = "unknown"
    wrong_kind["batch_hash"] = stable_hash({"irrelevant": True})
    wrong_schema = _payload()
    wrong_schema["schema_version"] = "kernel-proposal-batch.v2"

    with pytest.raises(ValidationError):
        extract_pb_claims(wrong_kind, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)
    with pytest.raises(ValidationError):
        extract_pb_claims(wrong_schema, run_id=RUN_ID, expected_runtime_hash=RUNTIME_HASH)
    with pytest.raises(ValueError, match="source binding mismatch"):
        extract_pb_claims(
            _payload(),
            run_id=RUN_ID,
            expected_runtime_hash=RUNTIME_HASH,
            mock_batch_payload=_mock_batch([_proposal(1), _proposal(2)]),
        )
