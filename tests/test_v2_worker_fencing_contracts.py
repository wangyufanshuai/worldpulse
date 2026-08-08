from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.services.consistency.hashing import stable_hash
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    KernelModeFencingEpoch,
    WorkerExecutionCapability,
    build_kernel_mode_fencing_epoch,
    build_worker_execution_capability,
)


def _capability(*, generation: int = 4) -> WorkerExecutionCapability:
    return build_worker_execution_capability(
        worker_id="worker-generation-4",
        worker_generation=generation,
        execution_contract_versions=(KERNEL_MODE_EXECUTION_V2,),
    )


def _epoch_payload() -> dict:
    epoch = build_kernel_mode_fencing_epoch(
        current_attempt_id="attempt-current",
        attempt_number=3,
        worker=_capability(),
        minimum_worker_generation=4,
    )
    return epoch.model_dump(mode="json")


def test_worker_capability_uses_the_exact_version_tuple_hash():
    capability = _capability()

    assert capability.worker_capability_hash == stable_hash(
        {"execution_contract_versions": (KERNEL_MODE_EXECUTION_V2,)}
    )
    assert capability.supports_v2 is True
    assert capability.worker_generation == 4


def test_worker_capability_rejects_noncanonical_or_unknown_registration_facts():
    valid = _capability().model_dump(mode="json")

    duplicate = deepcopy(valid)
    duplicate["execution_contract_versions"] = [
        KERNEL_MODE_EXECUTION_V2,
        KERNEL_MODE_EXECUTION_V2,
    ]
    duplicate["worker_capability_hash"] = stable_hash(
        {"execution_contract_versions": duplicate["execution_contract_versions"]}
    )
    with pytest.raises(ValidationError, match="unique"):
        WorkerExecutionCapability.model_validate(duplicate)

    unknown = deepcopy(valid)
    unknown["execution_contract_versions"] = ["kernel-mode-execution.v3"]
    unknown["worker_capability_hash"] = stable_hash(
        {"execution_contract_versions": unknown["execution_contract_versions"]}
    )
    with pytest.raises(ValidationError, match="unknown execution contract"):
        WorkerExecutionCapability.model_validate(unknown)

    empty = deepcopy(valid)
    empty["execution_contract_versions"] = []
    empty["worker_capability_hash"] = stable_hash(
        {"execution_contract_versions": ()}
    )
    with pytest.raises(ValidationError, match="non-empty"):
        WorkerExecutionCapability.model_validate(empty)

    wrong_hash = deepcopy(valid)
    wrong_hash["worker_capability_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="worker_capability_hash"):
        WorkerExecutionCapability.model_validate(wrong_hash)

    boolean_generation = deepcopy(valid)
    boolean_generation["worker_generation"] = True
    with pytest.raises(ValidationError):
        WorkerExecutionCapability.model_validate(boolean_generation)


def test_fencing_epoch_matches_the_exact_adr_preimage_and_is_stable():
    worker = _capability()
    first = build_kernel_mode_fencing_epoch(
        current_attempt_id="attempt-current",
        attempt_number=3,
        worker=worker,
        minimum_worker_generation=4,
    )
    second = build_kernel_mode_fencing_epoch(
        current_attempt_id="attempt-current",
        attempt_number=3,
        worker=worker,
        minimum_worker_generation=4,
    )

    expected = stable_hash(
        {
            "schema_version": "kernel-mode-fencing-epoch.v1",
            "current_attempt_id": "attempt-current",
            "attempt_number": 3,
            "worker_id": "worker-generation-4",
            "minimum_worker_generation": 4,
            "worker_capability_hash": worker.worker_capability_hash,
        }
    )
    assert first == second
    assert first.fencing_epoch_hash == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_attempt_id", "attempt-other"),
        ("attempt_number", 4),
        ("worker_id", "worker-other"),
        ("minimum_worker_generation", 3),
        ("worker_capability_hash", "e" * 64),
    ],
)
def test_fencing_epoch_hash_covers_every_immutable_epoch_input(
    field: str,
    value: object,
):
    payload = _epoch_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match="fencing_epoch_hash mismatch"):
        KernelModeFencingEpoch.model_validate(payload)


def test_fencing_epoch_rejects_ineligible_generation_and_strict_integer_drift():
    with pytest.raises(ValueError, match="below the pinned minimum"):
        build_kernel_mode_fencing_epoch(
            current_attempt_id="attempt-current",
            attempt_number=1,
            worker=_capability(generation=3),
            minimum_worker_generation=4,
        )

    payload = _epoch_payload()
    payload["attempt_number"] = True
    payload["fencing_epoch_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "fencing_epoch_hash"}
    )
    with pytest.raises(ValidationError):
        KernelModeFencingEpoch.model_validate(payload)


def test_fencing_epoch_is_closed_and_does_not_accept_lease_identity():
    payload = _epoch_payload()
    payload["lease_expires_at"] = "2099-01-01T00:00:00.000"

    with pytest.raises(ValidationError, match="Extra inputs"):
        KernelModeFencingEpoch.model_validate(payload)
