from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.core.models import WarRoomRun
from app.main import app
from app.services import project_store
from app.services.consistency.hashing import stable_hash
from app.services.negotiation.proof_materialization import (
    materialize_negotiation_proof,
    negotiation_proof_artifact_specs,
)
from app.services.negotiation.proof_sources import extract_rr_claims
from app.services.negotiation.repository import NegotiationRepository
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle import repository as lifecycle_repository


def _completed_negotiation(monkeypatch, tmp_path) -> tuple[str, WarRoomRun]:
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "materialization.db")
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={
            "title": "V2 negotiation proof",
            "question": "provider transcript rematerialization",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "strait_blockade_30d"},
        },
    )
    assert project.status_code == 200
    created = client.post(
        f"/api/v2/projects/{project.json()['project_id']}/runs",
        json={
            "engine_mode": "negotiation",
            "scenario": {
                "scenario_key": "strait_blockade_30d",
                "duration_days": 30,
            },
            "seed": 42,
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    completed = process_one_queued_job()
    assert completed is not None and completed.status == "completed"
    baseline_payload = lifecycle_repository.get_latest_artifact_content(run_id, "war_room_result")
    assert baseline_payload is not None
    return run_id, WarRoomRun.model_validate(baseline_payload)


def test_materializer_rebuilds_closed_proof_and_ignores_v1_decision_payloads(
    monkeypatch,
    tmp_path,
):
    run_id, baseline = _completed_negotiation(monkeypatch, tmp_path)
    repo = NegotiationRepository()
    proof = materialize_negotiation_proof(run_id, baseline, repository=repo)

    projected_ticks = tuple(item.tick for item in proof.ticks if item.projected)
    assert len(proof.ticks) == 6
    assert len(proof.ordered_sources()) == 38 + 3 * len(projected_ticks)
    specs = negotiation_proof_artifact_specs(proof)
    assert len(specs) == len(proof.ordered_sources())
    assert [item.source for item in specs] == list(proof.ordered_sources())
    assert specs[0].proof_schema == "kp.negotiation-round.v1"
    assert specs[-1].proof_schema == "kp.negotiation-replay.v1"
    assert stable_hash(proof.final.model_dump(mode="json")) == proof.replay.final_result_hash
    assert proof.replay.provider_calls_required == 0
    assert any(
        event.status == "expired"
        for item in proof.ticks
        for entry in item.ledger.entries
        for event in entry.events
    )

    next_seq = 1
    previous_hash = None
    for item in proof.ticks:
        claims = extract_rr_claims(
            item.round.model_dump(mode="json"),
            run_id=run_id,
            session_id=proof.session.session_id,
            tick=item.tick,
            expected_first_seq=next_seq,
            expected_previous_hash=previous_hash,
        )
        next_seq += claims.message_count
        if claims.message_tuples:
            previous_hash = claims.message_tuples[-1][2]

    first_round = repo.list_rounds(proof.session.session_id)[0]
    altered_output = deepcopy(first_round.output)
    altered_output["proposal_decisions"] = []
    altered_output["consistency_audit_hash"] = "f" * 64
    with project_store.connect() as conn:
        conn.execute(
            "UPDATE negotiation_rounds SET output_json = ?, output_hash = ? WHERE round_id = ?",
            (
                project_store.dumps(altered_output),
                stable_hash(altered_output),
                first_round.round_id,
            ),
        )
    regenerated = materialize_negotiation_proof(run_id, baseline, repository=repo)
    assert regenerated.replay.replay_hash == proof.replay.replay_hash

    first_message = repo.list_messages(proof.session.session_id)[0]
    with project_store.connect() as conn:
        conn.execute(
            "UPDATE negotiation_messages SET narrative = ? WHERE message_id = ?",
            ("tampered provider transcript", first_message.message_id),
        )
    with pytest.raises(ValueError, match="message hash-chain mismatch"):
        materialize_negotiation_proof(run_id, baseline, repository=repo)
