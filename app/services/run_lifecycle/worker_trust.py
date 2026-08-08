"""PostgreSQL-backed worker identity and V2 rollout gates for ADR-0007."""

from __future__ import annotations

from collections.abc import Mapping
import os

from app.db import postgres as postgres_db
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import CONSISTENCY_EVALUATOR_VERSION
from app.services.project_store import loads
from app.services.simulation_kernel.resolver_contracts import (
    AGENT_PACK_RESOLVER_VERSION,
    CONSTRAINT_CONTEXT_RESOLVER_VERSION,
)

from .execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    WORKER_EXECUTION_IDENTITY_METADATA_KEY,
    ExecutionContractSelection,
    KernelModeFencingEpoch,
    UncredentialedWorkerExecutionRegistration,
    V2ExecutionPathNotEnabledError,
    WorkerExecutionCapability,
    WorkerExecutionRegistration,
    build_worker_execution_capability,
    build_kernel_mode_fencing_epoch,
    expected_postgres_worker_principal,
    parse_worker_execution_registration,
    pin_legacy_execution_contract,
    select_execution_contract,
)


V2_CREATION_ENABLED_ENV = "WORLDPULSE_V2_CREATION_ENABLED"
V2_MINIMUM_WORKER_GENERATION_ENV = "WORLDPULSE_V2_MINIMUM_WORKER_GENERATION"
WORKER_ID_ENV = "WORLDPULSE_WORKER_ID"
WORKER_GENERATION_ENV = "WORLDPULSE_WORKER_GENERATION"
WORKER_EXECUTION_CONTRACTS_ENV = "WORLDPULSE_WORKER_EXECUTION_CONTRACT_VERSIONS"
CLAIM_READY_STATUS = "ready"


def worker_execution_capability_from_env(
    worker_id: str,
    environ: Mapping[str, str] | None = None,
) -> WorkerExecutionCapability | None:
    """Build deployment-assigned capability facts; partial configuration fails."""

    source = os.environ if environ is None else environ
    generation_raw = source.get(WORKER_GENERATION_ENV, "").strip()
    versions_raw = source.get(WORKER_EXECUTION_CONTRACTS_ENV, "").strip()
    if not generation_raw and not versions_raw:
        return None
    if not generation_raw or not versions_raw:
        raise V2ExecutionPathNotEnabledError(
            "V2 worker generation and execution-contract versions must be configured together"
        )
    generation = _strict_positive_integer(
        generation_raw,
        setting=WORKER_GENERATION_ENV,
    )
    version_parts = versions_raw.split(",")
    if any(not item or item != item.strip() for item in version_parts):
        raise V2ExecutionPathNotEnabledError(
            f"{WORKER_EXECUTION_CONTRACTS_ENV} must be a canonical comma-separated tuple"
        )
    versions = tuple(version_parts)
    return build_worker_execution_capability(
        worker_id=worker_id,
        worker_generation=generation,
        execution_contract_versions=versions,
    )


def authenticate_v2_worker_connection(
    connection,
    capability: WorkerExecutionCapability,
) -> str:
    """Bind a worker epoch to its non-elevated PostgreSQL login role."""

    if not postgres_db.is_postgres_url():
        raise V2ExecutionPathNotEnabledError(
            "kernel-mode-execution.v2 workers require PostgreSQL; direct SQLite remains disabled"
        )
    identity = postgres_db.postgres_session_identity(connection)
    if identity.session_user != identity.current_user:
        raise V2ExecutionPathNotEnabledError(
            "V2 worker PostgreSQL session may not assume a different current role"
        )
    if not identity.can_login:
        raise V2ExecutionPathNotEnabledError(
            "V2 worker PostgreSQL session role is not a login role"
        )
    if any(
        (
            identity.is_superuser,
            identity.can_create_role,
            identity.can_create_database,
            identity.can_replicate,
            identity.can_bypass_rls,
        )
    ):
        raise V2ExecutionPathNotEnabledError(
            "V2 worker PostgreSQL role has forbidden elevated privileges"
        )
    expected = expected_postgres_worker_principal(
        worker_id=capability.worker_id,
        worker_generation=capability.worker_generation,
    )
    if identity.session_user != expected:
        raise V2ExecutionPathNotEnabledError(
            "V2 worker PostgreSQL login role does not match its worker identity and generation"
        )
    return identity.session_user


def pin_execution_contract_for_creation(
    connection,
    runtime_profile: dict | None,
    *,
    effective_seed: int,
    now: str,
) -> dict:
    """Apply the server-owned V2 pin only after the complete worker-first gate."""

    profile = pin_legacy_execution_contract(runtime_profile)
    if not _strict_boolean_setting(V2_CREATION_ENABLED_ENV, default=False):
        return profile
    if type(effective_seed) is not int:
        raise ValueError("effective_seed must be a strict integer")
    if not postgres_db.is_postgres_url():
        raise V2ExecutionPathNotEnabledError(
            "V2 job creation requires PostgreSQL; direct SQLite remains V1-only"
        )
    minimum_generation = _strict_positive_integer(
        os.getenv(V2_MINIMUM_WORKER_GENERATION_ENV, "").strip(),
        setting=V2_MINIMUM_WORKER_GENERATION_ENV,
    )
    require_v2_creation_eligibility(
        connection,
        minimum_worker_generation=minimum_generation,
        now=now,
    )
    return {
        **profile,
        "execution_contract_version": KERNEL_MODE_EXECUTION_V2,
        "effective_seed": effective_seed,
        "minimum_worker_generation": minimum_generation,
        "agent_pack_resolver_version": AGENT_PACK_RESOLVER_VERSION,
        "constraint_context_resolver_version": CONSTRAINT_CONTEXT_RESOLVER_VERSION,
        "evaluator_version": CONSISTENCY_EVALUATOR_VERSION,
    }


def require_v2_creation_eligibility(
    connection,
    *,
    minimum_worker_generation: int,
    now: str,
) -> tuple[WorkerExecutionRegistration, ...]:
    """Require a nonempty fresh pool whose complete active set meets generation G."""

    rows = connection.execute(
        """
        SELECT worker_id, worker_kind, status, current_job_id,
               lease_expires_at, metadata_json
        FROM worker_nodes
        WHERE worker_kind = 'lifecycle'
          AND status IN ('ready', 'busy', 'draining')
        ORDER BY worker_id ASC
        """
    ).fetchall()
    registrations: list[WorkerExecutionRegistration] = []
    ready_count = 0
    principals: set[str] = set()
    for row in rows:
        if row["lease_expires_at"] <= now:
            continue
        registration = _credential_bound_registration(row["metadata_json"])
        if registration.identity_status != "active":
            raise V2ExecutionPathNotEnabledError(
                "fresh lifecycle worker has a retired V2 identity"
            )
        capability = registration.capability
        if not capability.supports_v2:
            raise V2ExecutionPathNotEnabledError(
                "fresh lifecycle worker does not advertise kernel-mode-execution.v2"
            )
        if capability.worker_generation < minimum_worker_generation:
            raise V2ExecutionPathNotEnabledError(
                "fresh lifecycle worker generation is below the requested V2 minimum"
            )
        if registration.database_principal in principals:
            raise V2ExecutionPathNotEnabledError(
                "V2 worker database principal is not unique"
            )
        principals.add(registration.database_principal)
        registrations.append(registration)
        if row["status"] in {"ready", "busy"}:
            ready_count += 1
    if not registrations or ready_count == 0:
        raise V2ExecutionPathNotEnabledError(
            "V2 creation requires at least one fresh active credential-bound lifecycle worker"
        )
    return tuple(registrations)


def require_v2_claim_eligibility(
    connection,
    *,
    selection: ExecutionContractSelection,
    worker_id: str,
    now: str,
    lock_worker: bool,
) -> WorkerExecutionCapability | None:
    """Authenticate and validate a V2 claimant before any owner/attempt write."""

    if not selection.is_v2:
        return None
    if selection.profile is None:
        raise ValueError("V2 execution selection is missing its validated profile")
    lock_clause = " FOR UPDATE" if lock_worker else ""
    row = connection.execute(
        f"""
        SELECT worker_id, worker_kind, status, current_job_id,
               lease_expires_at, metadata_json
        FROM worker_nodes
        WHERE worker_id = ?{lock_clause}
        """,
        (worker_id,),
    ).fetchone()
    if row is None:
        raise V2ExecutionPathNotEnabledError("V2 claiming worker is not registered")
    if row["worker_kind"] != "lifecycle":
        raise V2ExecutionPathNotEnabledError("V2 claimant is not a lifecycle worker")
    if row["status"] != CLAIM_READY_STATUS or row["current_job_id"] is not None:
        raise V2ExecutionPathNotEnabledError("V2 claiming worker is not ready")
    if row["lease_expires_at"] <= now:
        raise V2ExecutionPathNotEnabledError("V2 claiming worker heartbeat is stale")
    registration = _credential_bound_registration(row["metadata_json"])
    if registration.identity_status != "active":
        raise V2ExecutionPathNotEnabledError("V2 claiming worker identity is retired")
    capability = registration.capability
    if capability.worker_id != worker_id:
        raise V2ExecutionPathNotEnabledError("V2 worker registration identity mismatch")
    if not capability.supports_v2:
        raise V2ExecutionPathNotEnabledError(
            "V2 claiming worker does not advertise kernel-mode-execution.v2"
        )
    if capability.worker_generation < selection.profile.minimum_worker_generation:
        raise V2ExecutionPathNotEnabledError(
            "V2 claiming worker generation is below the pinned minimum"
        )
    principal = authenticate_v2_worker_connection(connection, capability)
    if principal != registration.database_principal:
        raise V2ExecutionPathNotEnabledError(
            "V2 claim database principal does not match immutable registration"
        )
    return capability


def capture_v2_fencing_epoch(
    connection,
    *,
    run_id: str,
    now: str,
    lock_rows: bool,
    expected_fencing_epoch_hash: str | None = None,
) -> KernelModeFencingEpoch:
    """Rebuild one live V2 epoch from the authoritative ownership rows."""

    if not postgres_db.is_postgres_url():
        raise V2ExecutionPathNotEnabledError(
            "kernel-mode-execution.v2 fencing requires PostgreSQL"
        )
    lock_clause = " FOR UPDATE OF job, attempt, worker" if lock_rows else ""
    row = connection.execute(
        f"""
        SELECT job.current_attempt_id,
               job.worker_id AS job_worker_id,
               job.status AS job_status,
               job.lease_expires_at AS job_lease_expires_at,
               job.runtime_profile_json,
               job.runtime_profile_hash,
               attempt.attempt_id,
               attempt.attempt_number,
               attempt.worker_id AS attempt_worker_id,
               attempt.status AS attempt_status,
               worker.worker_kind,
               worker.status AS worker_status,
               worker.current_job_id,
               worker.lease_expires_at AS worker_lease_expires_at,
               worker.metadata_json
        FROM run_jobs AS job
        JOIN run_attempts AS attempt
          ON attempt.attempt_id = job.current_attempt_id
         AND attempt.run_id = job.run_id
        JOIN worker_nodes AS worker
          ON worker.worker_id = job.worker_id
        WHERE job.run_id = ?{lock_clause}
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise V2ExecutionPathNotEnabledError(
            "V2 fencing ownership tuple is missing or incomplete"
        )
    if row["job_status"] != "running" or row["attempt_status"] != "running":
        raise V2ExecutionPathNotEnabledError(
            "V2 fencing requires a running job and current attempt"
        )
    if not row["job_lease_expires_at"] or row["job_lease_expires_at"] <= now:
        raise V2ExecutionPathNotEnabledError("V2 job lease is not fresh")
    if row["worker_kind"] != "lifecycle":
        raise V2ExecutionPathNotEnabledError("V2 fencing worker is not lifecycle")
    if (
        row["worker_status"] != "busy"
        or row["current_job_id"] != run_id
        or row["worker_lease_expires_at"] <= now
    ):
        raise V2ExecutionPathNotEnabledError(
            "V2 fencing worker is not fresh and busy on the current job"
        )
    worker_id = row["job_worker_id"]
    if not worker_id or worker_id != row["attempt_worker_id"]:
        raise V2ExecutionPathNotEnabledError(
            "V2 job and attempt worker ownership do not match"
        )
    profile = loads(row["runtime_profile_json"], {})
    profile_hash = row["runtime_profile_hash"]
    selection = _verified_v2_selection(profile, profile_hash)
    assert selection.profile is not None
    registration = _credential_bound_registration(row["metadata_json"])
    if registration.identity_status != "active":
        raise V2ExecutionPathNotEnabledError("V2 fencing worker identity is retired")
    capability = registration.capability
    if capability.worker_id != worker_id:
        raise V2ExecutionPathNotEnabledError(
            "V2 fencing registration identity mismatch"
        )
    principal = authenticate_v2_worker_connection(connection, capability)
    if principal != registration.database_principal:
        raise V2ExecutionPathNotEnabledError(
            "V2 fencing database principal does not match registration"
        )
    epoch = build_kernel_mode_fencing_epoch(
        current_attempt_id=row["current_attempt_id"],
        attempt_number=int(row["attempt_number"]),
        worker=capability,
        minimum_worker_generation=selection.profile.minimum_worker_generation,
    )
    if (
        expected_fencing_epoch_hash is not None
        and epoch.fencing_epoch_hash != expected_fencing_epoch_hash
    ):
        raise V2ExecutionPathNotEnabledError("V2 fencing epoch changed")
    return epoch


def _credential_bound_registration(raw_metadata: object) -> WorkerExecutionRegistration:
    metadata = loads(raw_metadata, {}) if isinstance(raw_metadata, str) else raw_metadata
    if not isinstance(metadata, dict):
        raise V2ExecutionPathNotEnabledError("worker metadata is malformed")
    raw_registration = metadata.get(WORKER_EXECUTION_IDENTITY_METADATA_KEY)
    if raw_registration is None:
        raise V2ExecutionPathNotEnabledError(
            "worker has no authenticated V2 execution registration"
        )
    registration = parse_worker_execution_registration(raw_registration)
    if isinstance(registration, UncredentialedWorkerExecutionRegistration):
        raise V2ExecutionPathNotEnabledError(
            "worker has an uncredentialed pre-enablement V2 registration"
        )
    return registration


def _verified_v2_selection(
    profile: object,
    profile_hash: object,
) -> ExecutionContractSelection:
    if not isinstance(profile, dict):
        raise V2ExecutionPathNotEnabledError("V2 runtime profile is malformed")
    try:
        selected = select_execution_contract(profile)
    except ValueError as error:
        raise V2ExecutionPathNotEnabledError(
            f"V2 runtime profile selection failed: {error}"
        ) from error
    if not selected.is_v2 or selected.profile is None:
        raise V2ExecutionPathNotEnabledError("fencing is only valid for exact V2 jobs")
    if not isinstance(profile_hash, str) or stable_hash(profile) != profile_hash:
        raise V2ExecutionPathNotEnabledError("V2 runtime profile hash mismatch")
    return selected


def _strict_boolean_setting(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise V2ExecutionPathNotEnabledError(f"{name} must be an explicit boolean")


def _strict_positive_integer(raw: str, *, setting: str) -> int:
    if not raw or not raw.isascii() or not raw.isdigit() or raw.startswith("0"):
        raise V2ExecutionPathNotEnabledError(
            f"{setting} must be a canonical strict positive integer"
        )
    return int(raw)
