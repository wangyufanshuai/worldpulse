"""Application port for the Run Control Plane bounded context."""

from __future__ import annotations

from typing import Any, Protocol

from app.core.models import (
    LifecycleHealthSummary,
    RunArtifactSummary,
    RunJobCreateRequest,
    RunJobStatus,
    RunLifecycleEvent,
    RunStepRecord,
)


class RunControlApplicationPort(Protocol):
    def create_job(
        self,
        project_id: str,
        request: RunJobCreateRequest,
        *,
        idempotency_key: str | None = None,
        pinned_rule_pack_id: str | None = None,
        evaluation_batch_id: str | None = None,
        evaluation_member_id: str | None = None,
        runtime_profile: dict | None = None,
    ) -> RunJobStatus: ...

    def get_job(self, run_id: str) -> RunJobStatus: ...

    def get_events(self, run_id: str, after_seq: int = 0) -> list[RunLifecycleEvent]: ...

    def pause_job(self, run_id: str) -> RunJobStatus: ...

    def resume_job(self, run_id: str) -> RunJobStatus: ...

    def cancel_job(self, run_id: str) -> RunJobStatus: ...

    def retry_job(self, run_id: str) -> RunJobStatus: ...

    def get_artifacts(self, run_id: str) -> list[RunArtifactSummary]: ...

    def get_steps(self, run_id: str) -> list[RunStepRecord]: ...

    def get_audit(self, run_id: str) -> dict: ...

    def get_health_summary(self) -> LifecycleHealthSummary: ...

    def recover_stale_jobs(self, *, recovered_by: str = "worker-recovery", now: str | None = None) -> list[RunJobStatus]: ...

    def process_one_queued_job(self, worker_id: str | None = None, *, prefer_evaluation: bool | None = None) -> RunJobStatus | None: ...


class RunControlApplicationService:
    """Compatibility adapter over the existing lifecycle repository."""

    def create_job(self, project_id: str, request: RunJobCreateRequest, *, idempotency_key: str | None = None, pinned_rule_pack_id: str | None = None, evaluation_batch_id: str | None = None, evaluation_member_id: str | None = None, runtime_profile: dict | None = None) -> RunJobStatus:
        return _repository().create_job(project_id, request, idempotency_key=idempotency_key, pinned_rule_pack_id=pinned_rule_pack_id, evaluation_batch_id=evaluation_batch_id, evaluation_member_id=evaluation_member_id, runtime_profile=runtime_profile)

    def get_job(self, run_id: str) -> RunJobStatus:
        return _repository().get_job(run_id)

    def get_events(self, run_id: str, after_seq: int = 0) -> list[RunLifecycleEvent]:
        return _repository().get_events(run_id, after_seq=after_seq)

    def pause_job(self, run_id: str) -> RunJobStatus:
        return _repository().pause_job(run_id)

    def resume_job(self, run_id: str) -> RunJobStatus:
        return _repository().resume_job(run_id)

    def cancel_job(self, run_id: str) -> RunJobStatus:
        return _repository().cancel_job(run_id)

    def retry_job(self, run_id: str) -> RunJobStatus:
        return _repository().retry_job(run_id)

    def get_artifacts(self, run_id: str) -> list[RunArtifactSummary]:
        return _repository().get_artifacts(run_id)

    def get_steps(self, run_id: str) -> list[RunStepRecord]:
        return _repository().get_steps(run_id)

    def get_audit(self, run_id: str) -> dict:
        return _repository().get_audit(run_id)

    def get_health_summary(self) -> LifecycleHealthSummary:
        return _repository().get_health_summary()

    def recover_stale_jobs(self, *, recovered_by: str = "worker-recovery", now: str | None = None) -> list[RunJobStatus]:
        return _repository().recover_stale_jobs(recovered_by=recovered_by, now=now)

    def process_one_queued_job(self, worker_id: str | None = None, *, prefer_evaluation: bool | None = None) -> RunJobStatus | None:
        from .executor import process_one_queued_job

        return process_one_queued_job(worker_id=worker_id, prefer_evaluation=prefer_evaluation)


def _repository() -> Any:
    from . import repository

    return repository


run_control_service: RunControlApplicationPort = RunControlApplicationService()
