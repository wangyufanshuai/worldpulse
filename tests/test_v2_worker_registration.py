from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import operations, project_store
from app.services.auth import ensure_system_user
from app.services.run_lifecycle import worker_trust
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    WORKER_EXECUTION_IDENTITY_METADATA_KEY,
    V2ExecutionPathNotEnabledError,
    WorkerExecutionRegistration,
    build_worker_execution_capability,
    expected_postgres_worker_principal,
)


def _setup(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "v2-worker-registration.db",
    )
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        worker_trust,
        "authenticate_v2_worker_connection",
        lambda _connection, capability: expected_postgres_worker_principal(
            worker_id=capability.worker_id,
            worker_generation=capability.worker_generation,
        ),
    )
    ensure_system_user()


def _capability(
    worker_id: str = "worker-v2-generation-4",
    *,
    generation: int = 4,
):
    return build_worker_execution_capability(
        worker_id=worker_id,
        worker_generation=generation,
        execution_contract_versions=(KERNEL_MODE_EXECUTION_V2,),
    )


def _registration(worker_id: str) -> WorkerExecutionRegistration:
    worker = operations.get_worker(worker_id)
    return WorkerExecutionRegistration.model_validate(
        worker.metadata[WORKER_EXECUTION_IDENTITY_METADATA_KEY]
    )


def test_direct_sqlite_rejects_v2_worker_registration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "v2-worker-sqlite-disabled.db",
    )
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    ensure_system_user()
    capability = _capability()

    with pytest.raises(V2ExecutionPathNotEnabledError, match="require PostgreSQL"):
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=capability,
        )


def test_v2_worker_registration_persists_and_preserves_immutable_capability(
    monkeypatch,
    tmp_path,
):
    _setup(monkeypatch, tmp_path)
    capability = _capability()

    first = operations.register_worker(
        capability.worker_id,
        "lifecycle",
        metadata={"pool": "v2"},
        execution_capability=capability,
    )
    first_registration = _registration(first.worker_id)
    second = operations.register_worker(
        capability.worker_id,
        "lifecycle",
        metadata={"pool": "v2-restarted"},
        execution_capability=capability,
    )
    second_registration = _registration(second.worker_id)

    assert first_registration == second_registration
    assert first_registration.capability == capability
    assert first_registration.identity_status == "active"
    assert second.metadata["pool"] == "v2-restarted"

    different_generation = _capability(generation=5)
    with pytest.raises(ValueError, match="capability is immutable"):
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=different_generation,
        )
    assert _registration(capability.worker_id) == first_registration


def test_worker_identity_cannot_upgrade_downgrade_or_inject_reserved_metadata(
    monkeypatch,
    tmp_path,
):
    _setup(monkeypatch, tmp_path)

    operations.register_worker("worker-legacy", "lifecycle")
    with pytest.raises(ValueError, match="cannot be upgraded"):
        operations.register_worker(
            "worker-legacy",
            "lifecycle",
            execution_capability=_capability("worker-legacy"),
        )

    capability = _capability()
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    with pytest.raises(ValueError, match="cannot re-register as legacy"):
        operations.register_worker(capability.worker_id, "lifecycle")

    with pytest.raises(ValueError, match="control-plane owned"):
        operations.register_worker(
            "worker-injected",
            "lifecycle",
            metadata={WORKER_EXECUTION_IDENTITY_METADATA_KEY: {}},
        )
    with pytest.raises(ValueError, match="only lifecycle"):
        operations.register_worker(
            "worker-ingestion-v2",
            "ingestion",
            execution_capability=_capability("worker-ingestion-v2"),
        )
    with pytest.raises(ValueError, match="identity mismatch"):
        operations.register_worker(
            "worker-other-id",
            "lifecycle",
            execution_capability=capability,
        )


def test_v2_worker_retirement_is_monotonic_and_blocks_late_heartbeats(
    monkeypatch,
    tmp_path,
):
    _setup(monkeypatch, tmp_path)
    capability = _capability()
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )

    with pytest.raises(ValueError, match="stopped and drained"):
        operations.retire_worker_identity(capability.worker_id)

    operations.stop_worker(capability.worker_id)
    with pytest.raises(ValueError, match="inactive V2 worker"):
        operations.heartbeat_worker(capability.worker_id)
    with pytest.raises(ValueError, match="inactive V2 worker"):
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=capability,
        )
    retired = operations.retire_worker_identity(capability.worker_id)
    registration = _registration(capability.worker_id)

    assert retired.status == "stopped"
    assert registration.identity_status == "retired"
    assert registration.retired_at is not None
    assert operations.retire_worker_identity(capability.worker_id).status == "stopped"

    with pytest.raises(ValueError, match="cannot heartbeat"):
        operations.heartbeat_worker(capability.worker_id)
    with pytest.raises(ValueError, match="cannot be reactivated"):
        operations.register_worker(
            capability.worker_id,
            "lifecycle",
            execution_capability=capability,
        )
    assert _registration(capability.worker_id) == registration


def test_corrupt_execution_registration_fails_closed_before_heartbeat_mutation(
    monkeypatch,
    tmp_path,
):
    _setup(monkeypatch, tmp_path)
    capability = _capability()
    worker = operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    before = worker.heartbeat_at
    metadata = deepcopy(worker.metadata)
    metadata[WORKER_EXECUTION_IDENTITY_METADATA_KEY]["capability"][
        "worker_capability_hash"
    ] = "f" * 64
    with project_store.connect() as connection:
        connection.execute(
            "UPDATE worker_nodes SET metadata_json = ? WHERE worker_id = ?",
            (project_store.dumps(metadata), worker.worker_id),
        )

    with pytest.raises(ValueError, match="worker_capability_hash mismatch"):
        operations.heartbeat_worker(worker.worker_id)
    with project_store.connect() as connection:
        row = connection.execute(
            "SELECT heartbeat_at FROM worker_nodes WHERE worker_id = ?",
            (worker.worker_id,),
        ).fetchone()
    assert row["heartbeat_at"] == before
