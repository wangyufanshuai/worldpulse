from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.services.consistency.hashing import stable_hash
from app.services.negotiation.proof_sources import extract_ar_claims


RUN_ID = "agent-runtime-proof-run"


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


def _invocation(ordinal: int = 1) -> dict:
    return {
        "schema_version": "agent-invocation-audit.v1",
        "invocation_id": f"invoke-{ordinal:04d}",
        "run_id": RUN_ID,
        "turn": 1,
        "actor_id": f"agent-{ordinal:04d}",
        "role_id": "diplomacy",
        "provider": "mock",
        "model": "mock-deterministic-v1",
        "mode": "mock",
        "model_parameters": {"seed": 42},
        "prompt_version": "worldpulse-agent.v1",
        "prompt_hash": stable_hash({"prompt": ordinal}),
        "response_hash": stable_hash({"response": ordinal}),
        "status": "completed",
        "input_chars": 120,
        "output_chars": 80,
        "estimated_tokens": 50,
        "duration_ms": 2,
        "error_code": None,
        "error_message": None,
        "secret_redacted": True,
        "created_at": "2000-01-01T00:00:01.000Z",
    }


def _runtime_hash(payload: dict) -> str:
    return stable_hash(
        {
            "provider": payload["provider"],
            "model": payload["model"],
            "mode": payload["mode"],
            "proposal_ids": [item["proposal_id"] for item in payload["proposals"]],
            "invocations": [
                {
                    "turn": item["turn"],
                    "actor_id": item["actor_id"],
                    "role_id": item["role_id"],
                    "provider": item["provider"],
                    "model": item["model"],
                    "prompt_version": item["prompt_version"],
                    "prompt_hash": item["prompt_hash"],
                    "response_hash": item["response_hash"],
                    "status": item["status"],
                    "error_code": item["error_code"],
                }
                for item in payload["invocations"]
            ],
        }
    )


def _payload(*, populated: bool = True) -> dict:
    proposals = [_proposal(2), _proposal(1)] if populated else []
    invocations = [_invocation(2), _invocation(1)] if populated else []
    payload = {
        "schema_version": "agent-runtime-result.v1",
        "run_id": RUN_ID,
        "provider": "mock",
        "model": "mock-deterministic-v1",
        "mode": "mock" if populated else "skipped",
        "fallback_reason": None,
        "runtime_config": {"seed": 42, "max_calls": 8},
        "proposals": proposals,
        "constraint_context": {
            "schema_version": "agent-constraint-context.v1",
            "actor_capabilities": {},
            "action_budgets": {},
            "known_entities": ["country:USA"],
            "known_evidence_refs": ["evidence-0001"],
            "source_label": "explicit simulation capability envelope",
        },
        "invocations": invocations,
        "total_calls": len(invocations),
        "total_estimated_tokens": sum(item["estimated_tokens"] for item in invocations),
        "failed_calls": 0,
        "runtime_hash": "",
    }
    payload["runtime_hash"] = _runtime_hash(payload)
    return payload


def test_extract_ar_claims_recomputes_complete_vectors_and_sorts_ids() -> None:
    payload = _payload()

    claims = extract_ar_claims(payload, run_id=RUN_ID)

    assert claims.runtime_hash == payload["runtime_hash"]
    assert claims.proposal_ids == ("proposal-0001", "proposal-0002")
    assert claims.invocation_ids == ("invoke-0001", "invoke-0002")
    assert claims.proposal_count == claims.invocation_count == 2
    by_proposal = {item["proposal_id"]: stable_hash(item) for item in payload["proposals"]}
    by_invocation = {item["invocation_id"]: stable_hash(item) for item in payload["invocations"]}
    assert claims.proposal_hashes == tuple(by_proposal[item] for item in claims.proposal_ids)
    assert claims.invocation_hashes == tuple(by_invocation[item] for item in claims.invocation_ids)


def test_extract_ar_claims_accepts_complete_empty_runtime() -> None:
    claims = extract_ar_claims(_payload(populated=False), run_id=RUN_ID)

    assert claims.proposal_ids == ()
    assert claims.invocation_ids == ()
    assert claims.proposal_count == claims.invocation_count == 0


@pytest.mark.parametrize("field", ["run_id", "constraint_context", "runtime_hash"])
def test_ar_source_rejects_missing_outer_fields(field: str) -> None:
    payload = _payload()
    del payload[field]

    with pytest.raises(ValidationError):
        extract_ar_claims(payload, run_id=RUN_ID)


def test_ar_source_rejects_extra_outer_field() -> None:
    payload = _payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        extract_ar_claims(payload, run_id=RUN_ID)


@pytest.mark.parametrize("nested", ["proposals", "invocations"])
def test_ar_source_rejects_extra_nested_field(nested: str) -> None:
    payload = _payload()
    payload[nested][0]["unexpected"] = True

    with pytest.raises(ValueError, match="exactly"):
        extract_ar_claims(payload, run_id=RUN_ID)


def test_ar_source_rejects_extra_context_field() -> None:
    payload = _payload()
    payload["constraint_context"]["unexpected"] = True

    with pytest.raises(ValueError, match="exactly"):
        extract_ar_claims(payload, run_id=RUN_ID)


@pytest.mark.parametrize("nested", ["proposals", "invocations"])
def test_ar_source_rejects_nested_run_drift(nested: str) -> None:
    payload = _payload()
    payload[nested][0]["run_id"] = "other-run"

    with pytest.raises(ValueError, match="run_id mismatch"):
        extract_ar_claims(payload, run_id=RUN_ID)


def test_ar_source_rejects_envelope_run_drift() -> None:
    with pytest.raises(ValueError, match="source run_id mismatch"):
        extract_ar_claims(_payload(), run_id="other-run")


@pytest.mark.parametrize(
    ("nested", "id_field"),
    [("proposals", "proposal_id"), ("invocations", "invocation_id")],
)
def test_ar_source_rejects_duplicate_ids(nested: str, id_field: str) -> None:
    payload = _payload()
    payload[nested][1][id_field] = payload[nested][0][id_field]

    with pytest.raises(ValueError, match="IDs must be unique"):
        extract_ar_claims(payload, run_id=RUN_ID)


def test_ar_source_rejects_runtime_hash_drift() -> None:
    payload = _payload()
    payload["invocations"][0]["prompt_hash"] = stable_hash({"tampered": True})

    with pytest.raises(ValueError, match="runtime_hash mismatch"):
        extract_ar_claims(payload, run_id=RUN_ID)


def test_ar_source_rejects_numeric_authority_in_proposal() -> None:
    payload = deepcopy(_payload())
    payload["proposals"][0]["parameters"]["risk_score"] = 99

    with pytest.raises(ValidationError, match="numeric authority"):
        extract_ar_claims(payload, run_id=RUN_ID)
