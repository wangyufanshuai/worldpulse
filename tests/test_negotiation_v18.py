from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.main import app
from app.services import project_store
from app.services.consistency.hashing import stable_hash
from app.services.negotiation.agent_pack import build_agent_pack, scheduled_profiles
from app.services.negotiation.diffusion import apply_narrative_diffusion
from app.services.negotiation import replay_negotiation_from_storage
from app.services.negotiation.engine import _create_negotiation_review_cases, _generate_tick_envelopes, _runtime_config
from app.services.reviews import list_reviews
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle import repository as lifecycle_repository
from app.services.negotiation.repository import NegotiationRepository
from app.services.war_room_engine import run_war_room
from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract.models import AgentActionProposal


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "v18.db")
    client = TestClient(app)
    project = client.post("/api/projects", json={
        "title": "V1.8 Negotiation", "question": "controlled diplomacy", "mode": "war_room",
        "scenario_config": {"scenario_key": "strait_blockade_30d"},
    })
    assert project.status_code == 200
    return client, project.json()["project_id"]


def test_v18_migration_creates_negotiation_tables(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "schema.db")
    project_store.init_db()
    with project_store.connect() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(run_jobs)")}
    assert {"agent_packs", "negotiation_sessions", "negotiation_rounds", "negotiation_messages", "negotiation_commitments", "negotiation_commitment_events"} <= tables
    assert {"agent_pack_id", "agent_pack_hash"} <= columns


def test_agent_pack_has_twelve_profiles_and_six_per_tick():
    result = run_war_room(WarRoomScenarioRequest(seed=42))
    pack = build_agent_pack(result, 42)
    assert len(pack.profiles) == 12
    assert len({item.agent_id for item in pack.profiles}) == 12
    selected = [item.agent_id for tick in range(1, 7) for item in scheduled_profiles(pack, tick)]
    assert len(selected) == 36
    assert {item.agent_id for item in pack.profiles} <= set(selected)
    assert stable_hash({"schema_version": pack.schema_version, "seed": pack.seed, "profiles": [item.model_dump(mode="json") for item in pack.profiles]}) == pack.manifest_hash


def test_negotiation_lifecycle_completes_and_exposes_read_only_v7(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(f"/api/v2/projects/{project_id}/runs", json={
        "engine_mode": "negotiation", "scenario": {"scenario_key": "strait_blockade_30d", "duration_days": 30}, "seed": 42,
    })
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    completed = process_one_queued_job()
    assert completed.status == "completed"
    assert completed.engine_mode == "negotiation"
    assert completed.agent_pack_id and completed.agent_pack_hash

    detail = client.get(f"/api/v7/runs/{run_id}/negotiation")
    assert detail.status_code == 200
    assert detail.json()["summary"]["round_count"] == 6
    rounds = client.get(f"/api/v7/runs/{run_id}/negotiation/rounds").json()
    messages = client.get(f"/api/v7/runs/{run_id}/negotiation/messages").json()
    commitments = client.get(f"/api/v7/runs/{run_id}/negotiation/commitments").json()
    assert [item["tick"] for item in rounds] == [1, 2, 3, 4, 5, 6]
    assert len(messages) == 36
    assert [item["seq"] for item in messages] == list(range(1, 37))
    assert messages[0]["previous_hash"] is None
    assert all(messages[index]["previous_hash"] == messages[index - 1]["message_hash"] for index in range(1, len(messages)))
    assert commitments
    assert client.post(f"/api/v7/runs/{run_id}/negotiation/messages", json={}).status_code == 405

    audit = client.get(f"/api/v2/runs/{run_id}/audit").json()
    assert audit["negotiation"]["message_count"] == 36
    artifact_types = {item["artifact_type"] for item in audit["artifacts"]}
    assert {
        "negotiation_round",
        "negotiation_checkpoint",
        "commitment_ledger",
        "narrative_diffusion",
        "negotiation_action_observation",
        "negotiation_replay",
        "negotiation_final_result",
    } <= artifact_types
    replay = next(item for item in audit["artifacts"] if item["artifact_type"] == "negotiation_replay")
    assert replay["sha256"]
    replayed = replay_negotiation_from_storage(run_id)
    assert stable_hash(replayed.model_dump(mode="json")) == audit["negotiation"]["replay"]["final_result_hash"]


def test_message_filter_and_replay_require_no_provider(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    run_id = client.post(f"/api/v2/projects/{project_id}/runs", json={"engine_mode": "negotiation", "scenario": {}, "seed": 7}).json()["run_id"]
    process_one_queued_job()
    first = client.get(f"/api/v7/runs/{run_id}/negotiation/messages", params={"tick": 2}).json()
    later = client.get(f"/api/v7/runs/{run_id}/negotiation/messages", params={"after_seq": first[-1]["seq"]}).json()
    assert first and {item["tick"] for item in first} == {2}
    assert later and min(item["seq"] for item in later) > first[-1]["seq"]
    audit = client.get(f"/api/v2/runs/{run_id}/audit").json()
    replay_artifact = next(item for item in audit["artifacts"] if item["artifact_type"] == "negotiation_replay")
    assert replay_artifact["schema_version"] == "negotiation-replay.v1"


def test_narrative_diffusion_is_formula_bound_and_clamped():
    state = run_war_room(WarRoomScenarioRequest(seed=42))
    actor = state.country_agents[0]
    target = state.country_agents[1]
    proposal = AgentActionProposal(
        proposal_id="proposal_diffusion01", run_id="run_diffusion", turn=1,
        actor_id=f"agent:public_opinion:{actor.code}", actor_type="public_opinion", action_type="public_narrative",
        target_ids=[f"country:{target.code}"], parameters={"theme": "稳定公开沟通", "audience": "global", "tone": "firm"},
        justification="测试固定公式传播而非模型提供数值。", evidence_refs=[f"country:{target.code}"],
        expected_direction="inform", confidence=80, created_at="2000-01-01T00:00:01.000Z",
    )
    _, audit, cumulative = apply_narrative_diffusion(state, [proposal], {target.code: 7.5})
    assert audit.tone_deltas == {"stabilizing": -4.0, "informational": -1.0, "firm": 3.0}
    assert cumulative[target.code] == 8.0
    assert max(cumulative.values()) <= 8.0
    assert audit.audit_hash


def test_provider_budget_fails_closed_to_mock_without_calling_provider():
    state = run_war_room(WarRoomScenarioRequest(seed=42))
    pack = build_agent_pack(state, 42)
    provider = SimpleNamespace(generate=lambda request: (_ for _ in ()).throw(AssertionError("provider must not be called")))
    runtime = {**_runtime_config(), "provider": "deepseek", "fallback_mode": "mock"}
    generated = _generate_tick_envelopes(
        state, pack, scheduled_profiles(pack, 1), 1, "run_budget", 42, [],
        runtime=runtime, provider=provider, token_budget_remaining=0,
    )
    assert len(generated) == 6
    assert all(item[2]["fallback_used"] and item[2]["provider"] == "mock-deterministic" for item in generated)


def test_negotiation_rejection_opens_idempotent_review_case(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "reviews.db")
    decision = SimpleNamespace(
        proposal_id="proposal_review01", outcome="rejected", rule_version="consistency.v1",
        audit_hash="a" * 64, projection_status="blocked",
    )
    _create_negotiation_review_cases("run_review", 2, [decision], [])
    _create_negotiation_review_cases("run_review", 2, [decision], [])
    reviews = list_reviews()
    assert len(reviews) == 1
    assert reviews[0].review_type == "negotiation_action_admission"
    assert reviews[0].payload["outcome"] == "rejected"


def test_negotiation_session_tracks_pause_resume_and_cancel(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    run_id = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"engine_mode": "negotiation", "scenario": {}, "seed": 42},
    ).json()["run_id"]
    state = run_war_room(WarRoomScenarioRequest(seed=42))
    repo = NegotiationRepository()
    pack = repo.save_agent_pack(build_agent_pack(state, 42))
    repo.create_session(run_id, pack, stable_hash(state.model_dump(mode="json")))

    lifecycle_repository.update_job_status(run_id, status="paused")
    assert repo.get_session(run_id).status == "paused"
    lifecycle_repository.resume_job(run_id)
    assert repo.get_session(run_id).status == "running"
    lifecycle_repository.cancel_job(run_id)
    assert repo.get_session(run_id).status == "cancelled"
