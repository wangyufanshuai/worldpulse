from __future__ import annotations

import pytest

from app.core.models import (
    ResearchProjectCreate,
    RunJobCreateRequest,
    WarRoomScenarioRequest,
)
from app.db import postgres as postgres_db
from app.db.postgres import PostgresSessionIdentity
from app.services import operations, project_store
from app.services.auth import ensure_system_user
from app.services.consistency.hashing import stable_hash
from app.services.project_app.service import create_project
from app.services.run_lifecycle import repository, worker_trust
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    V2ExecutionPathNotEnabledError,
    build_worker_execution_capability,
    expected_postgres_worker_principal,
)


def _setup(monkeypatch, tmp_path) -> str:
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "v2-worker-claim-gates.db",
    )
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    monkeypatch.delenv(worker_trust.V2_CREATION_ENABLED_ENV, raising=False)
    monkeypatch.delenv(
        worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV,
        raising=False,
    )
    ensure_system_user()
    return create_project(
        ResearchProjectCreate(
            title="V2 worker claim gates",
            question="Does authenticated PostgreSQL claiming fail closed?",
            mode="war_room",
        )
    ).project_id


def _capability(worker_id: str = "worker-v2-g4", *, generation: int = 4):
    return build_worker_execution_capability(
        worker_id=worker_id,
        worker_generation=generation,
        execution_contract_versions=(KERNEL_MODE_EXECUTION_V2,),
    )


def _identity_for(capability, **overrides) -> PostgresSessionIdentity:
    principal = expected_postgres_worker_principal(
        worker_id=capability.worker_id,
        worker_generation=capability.worker_generation,
    )
    payload = {
        "session_user": principal,
        "current_user": principal,
        "can_login": True,
        "is_superuser": False,
        "can_create_role": False,
        "can_create_database": False,
        "can_replicate": False,
        "can_bypass_rls": False,
    }
    payload.update(overrides)
    return PostgresSessionIdentity(**payload)


def _simulate_postgres_session(monkeypatch, identity: PostgresSessionIdentity) -> None:
    # The repository still uses SQLite transaction syntax in this unit seam;
    # only the database-authenticated identity boundary is simulated.
    monkeypatch.setattr(postgres_db, "is_postgres_url", lambda _value=None: True)
    monkeypatch.setattr(
        postgres_db,
        "postgres_session_identity",
        lambda _connection: identity,
    )


def _v2_profile(*, seed: int = 17, minimum_generation: int = 4) -> dict:
    return {
        "execution_contract_version": KERNEL_MODE_EXECUTION_V2,
        "effective_seed": seed,
        "minimum_worker_generation": minimum_generation,
        "agent_pack_resolver_version": "agent-pack-resolver.v1",
        "constraint_context_resolver_version": "constraint-context-resolver.v1",
        "evaluator_version": "worldpulse-consistency.v0.8",
    }


def _queued_job(project_id: str, *, seed: int = 17):
    return repository.create_job(
        project_id,
        RunJobCreateRequest(
            seed=seed,
            scenario=WarRoomScenarioRequest(seed=seed),
        ),
    )


def _pin_job_to_v2(run_id: str, profile: dict) -> None:
    with project_store.connect() as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET runtime_profile_json = ?, runtime_profile_hash = ?, seed = ?, scenario_json = ?
            WHERE run_id = ?
            """,
            (
                project_store.dumps(profile),
                stable_hash(profile),
                profile["effective_seed"],
                project_store.dumps(
                    WarRoomScenarioRequest(
                        seed=profile["effective_seed"]
                    ).model_dump()
                ),
                run_id,
            ),
        )


def _assert_zero_claim_writes(run_id: str) -> None:
    job = repository.get_job(run_id)
    assert job.status == "queued"
    assert job.worker_id is None
    assert job.lease_expires_at is None
    assert job.current_attempt_id is None
    assert job.attempt_count == 0
    with project_store.connect() as connection:
        attempts = connection.execute(
            "SELECT COUNT(*) AS count FROM run_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert int(attempts["count"]) == 0


def test_authenticated_postgres_worker_claims_v2_atomically(monkeypatch, tmp_path):
    project_id = _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(monkeypatch, _identity_for(capability))
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    queued = _queued_job(project_id)
    _pin_job_to_v2(queued.run_id, _v2_profile())

    claimed = repository.claim_next_job(worker_id=capability.worker_id)

    assert claimed is not None
    assert claimed.run_id == queued.run_id
    assert claimed.status == "preparing"
    assert claimed.attempt_count == 1
    assert claimed.current_attempt_id is not None
    worker = operations.get_worker(capability.worker_id)
    assert worker.status == "busy"
    assert worker.current_job_id == queued.run_id


def test_wrong_postgres_principal_refuses_v2_claim_with_zero_writes(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(monkeypatch, _identity_for(capability))
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    queued = _queued_job(project_id)
    _pin_job_to_v2(queued.run_id, _v2_profile())
    wrong = _identity_for(
        capability,
        session_user="worldpulse_v2_wrong",
        current_user="worldpulse_v2_wrong",
    )
    _simulate_postgres_session(monkeypatch, wrong)

    with pytest.raises(V2ExecutionPathNotEnabledError, match="does not match"):
        repository.claim_next_job(worker_id=capability.worker_id)

    _assert_zero_claim_writes(queued.run_id)
    worker = operations.get_worker(capability.worker_id)
    assert worker.status == "ready"
    assert worker.current_job_id is None


def test_lower_generation_and_nonready_worker_refuse_without_attempt_mutation(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(monkeypatch, _identity_for(capability))
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    queued = _queued_job(project_id)
    _pin_job_to_v2(queued.run_id, _v2_profile(minimum_generation=5))

    with pytest.raises(V2ExecutionPathNotEnabledError, match="below the pinned"):
        repository.claim_next_job(worker_id=capability.worker_id)
    _assert_zero_claim_writes(queued.run_id)

    _pin_job_to_v2(queued.run_id, _v2_profile(minimum_generation=4))
    operations.request_worker_drain(capability.worker_id)
    with pytest.raises(V2ExecutionPathNotEnabledError, match="not ready"):
        repository.claim_next_job(worker_id=capability.worker_id)
    _assert_zero_claim_writes(queued.run_id)


def test_direct_sqlite_refuses_v2_claim_even_with_registered_metadata(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    capability = _capability()
    with monkeypatch.context() as simulated:
        simulated.setattr(
            worker_trust,
            "authenticate_v2_worker_connection",
            lambda _connection, _capability: expected_postgres_worker_principal(
                worker_id=_capability.worker_id,
                worker_generation=_capability.worker_generation,
            ),
        )
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=capability,
        )
    queued = _queued_job(project_id)
    _pin_job_to_v2(queued.run_id, _v2_profile())

    with pytest.raises(V2ExecutionPathNotEnabledError, match="require PostgreSQL"):
        repository.claim_next_job(worker_id=capability.worker_id)

    _assert_zero_claim_writes(queued.run_id)


def test_server_creation_gate_pins_complete_v2_profile_and_seed(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(monkeypatch, _identity_for(capability))
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    monkeypatch.setenv(worker_trust.V2_CREATION_ENABLED_ENV, "1")
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "4")

    created = repository.create_job(
        project_id,
        RunJobCreateRequest(
            seed=None,
            scenario=WarRoomScenarioRequest(seed=0),
        ),
        runtime_profile={
            "provider": "mock",
            "agent_pack_hash": "a" * 64,
            "minimum_worker_generation": 999,
        },
    )

    assert created.seed == 0
    assert created.scenario["seed"] == 0
    assert created.runtime_profile == {
        "provider": "mock",
        **_v2_profile(seed=0, minimum_generation=4),
    }
    assert created.runtime_profile_hash == stable_hash(created.runtime_profile)


def test_idempotent_v2_retry_does_not_reopen_worker_availability_gate(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(monkeypatch, _identity_for(capability))
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    monkeypatch.setenv(worker_trust.V2_CREATION_ENABLED_ENV, "1")
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "4")
    request = RunJobCreateRequest(seed=19, scenario=WarRoomScenarioRequest(seed=19))
    first = repository.create_job(
        project_id,
        request,
        idempotency_key="v2-idempotent",
    )
    operations.stop_worker(capability.worker_id)

    second = repository.create_job(
        project_id,
        request,
        idempotency_key="v2-idempotent",
    )

    assert second.run_id == first.run_id
    assert second.runtime_profile == first.runtime_profile


def test_creation_gate_rejects_empty_or_legacy_pool_without_inserting_job(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(postgres_db, "is_postgres_url", lambda _value=None: True)
    monkeypatch.setenv(worker_trust.V2_CREATION_ENABLED_ENV, "true")
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "4")

    with pytest.raises(V2ExecutionPathNotEnabledError, match="at least one"):
        _queued_job(project_id)

    operations.register_worker("legacy-worker", "lifecycle")
    with pytest.raises(
        V2ExecutionPathNotEnabledError,
        match="no authenticated V2 execution registration",
    ):
        _queued_job(project_id)

    with project_store.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_jobs WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    assert int(count["count"]) == 0


def test_creation_gate_rejects_direct_sqlite_and_lower_generation(
    monkeypatch,
    tmp_path,
):
    project_id = _setup(monkeypatch, tmp_path)
    monkeypatch.setenv(worker_trust.V2_CREATION_ENABLED_ENV, "1")
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "5")

    with pytest.raises(V2ExecutionPathNotEnabledError, match="requires PostgreSQL"):
        _queued_job(project_id)

    capability = _capability(generation=4)
    _simulate_postgres_session(monkeypatch, _identity_for(capability))
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    with pytest.raises(V2ExecutionPathNotEnabledError, match="below the requested"):
        _queued_job(project_id)
    with project_store.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_jobs WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    assert int(count["count"]) == 0


def test_worker_environment_contract_is_complete_and_canonical():
    worker_id = "worker-configured-v2"
    capability = worker_trust.worker_execution_capability_from_env(
        worker_id,
        {
            worker_trust.WORKER_GENERATION_ENV: "7",
            worker_trust.WORKER_EXECUTION_CONTRACTS_ENV: KERNEL_MODE_EXECUTION_V2,
        },
    )
    assert capability is not None
    assert capability.worker_generation == 7
    assert capability.worker_id == worker_id
    assert worker_trust.worker_execution_capability_from_env(worker_id, {}) is None

    with pytest.raises(V2ExecutionPathNotEnabledError, match="configured together"):
        worker_trust.worker_execution_capability_from_env(
            worker_id,
            {worker_trust.WORKER_GENERATION_ENV: "7"},
        )
    with pytest.raises(V2ExecutionPathNotEnabledError, match="strict positive"):
        worker_trust.worker_execution_capability_from_env(
            worker_id,
            {
                worker_trust.WORKER_GENERATION_ENV: "07",
                worker_trust.WORKER_EXECUTION_CONTRACTS_ENV: KERNEL_MODE_EXECUTION_V2,
            },
        )
    with pytest.raises(V2ExecutionPathNotEnabledError, match="canonical"):
        worker_trust.worker_execution_capability_from_env(
            worker_id,
            {
                worker_trust.WORKER_GENERATION_ENV: "7",
                worker_trust.WORKER_EXECUTION_CONTRACTS_ENV: (
                    f"{KERNEL_MODE_EXECUTION_V2},"
                ),
            },
        )


@pytest.mark.parametrize(
    "privilege",
    [
        "is_superuser",
        "can_create_role",
        "can_create_database",
        "can_replicate",
        "can_bypass_rls",
    ],
)
def test_postgres_worker_role_rejects_elevated_privilege(
    monkeypatch,
    tmp_path,
    privilege,
):
    _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(
        monkeypatch,
        _identity_for(capability, **{privilege: True}),
    )

    with pytest.raises(V2ExecutionPathNotEnabledError, match="elevated"):
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=capability,
        )


def test_postgres_worker_role_rejects_assumed_current_role(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    capability = _capability()
    _simulate_postgres_session(
        monkeypatch,
        _identity_for(capability, current_user="assumed-role"),
    )

    with pytest.raises(V2ExecutionPathNotEnabledError, match="may not assume"):
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=capability,
        )
