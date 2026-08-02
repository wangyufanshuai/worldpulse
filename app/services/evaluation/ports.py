"""Application port for the Evaluation & Governance bounded context.

HTTP routes, CLI commands and workers depend on this protocol rather than on
the storage-heavy ``EvaluationService`` implementation. The concrete service
remains the compatibility adapter during the V2 strangler migration.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.evaluation_models import (
    EvaluationBatch,
    EvaluationBatchCreateRequest,
    EvaluationCase,
    EvaluationMember,
    EvaluationMetric,
    EvaluationReport,
    EvaluationSuiteManifest,
    HistoricalBenchmarkReport,
    HistoricalEvaluationCreateRequest,
)


class EvaluationApplicationPort(Protocol):
    def ensure_suite(self) -> EvaluationSuiteManifest: ...

    def get_suite(self, suite_id: str) -> EvaluationSuiteManifest: ...

    def list_suites(self) -> list[EvaluationSuiteManifest]: ...

    def list_cases(self, suite_id: str | None = None) -> list[EvaluationCase]: ...

    def create_batch(
        self,
        organization_id: str,
        actor: Any,
        payload: EvaluationBatchCreateRequest,
        *,
        source_type: str = "standard",
        project_id: str | None = None,
        scenario_draft_id: str | None = None,
        suite_id: str | None = None,
    ) -> EvaluationBatch: ...

    def create_standard_batch(
        self,
        organization_id: str,
        actor: Any,
        payload: EvaluationBatchCreateRequest | None = None,
    ) -> EvaluationBatch: ...

    def create_historical_batch(
        self,
        organization_id: str,
        actor: Any,
        payload: HistoricalEvaluationCreateRequest,
    ) -> EvaluationBatch: ...

    def create_project_experiment(
        self,
        organization_id: str,
        project_id: str,
        draft_id: str,
        actor: Any,
        payload: EvaluationBatchCreateRequest,
    ) -> EvaluationBatch: ...

    def get_batch(self, batch_id: str, organization_id: str | None = None) -> EvaluationBatch: ...

    def list_batches(self, organization_id: str) -> list[EvaluationBatch]: ...

    def list_members(self, batch_id: str, organization_id: str | None = None) -> list[EvaluationMember]: ...

    def list_metrics(self, batch_id: str, organization_id: str | None = None) -> list[EvaluationMetric]: ...

    def list_events(self, batch_id: str, after_seq: int = 0, organization_id: str | None = None) -> list[dict]: ...

    def control(self, batch_id: str, action: str, organization_id: str | None = None) -> EvaluationBatch: ...

    def retry(self, batch_id: str, actor: Any, organization_id: str | None = None) -> EvaluationBatch: ...

    def report(self, batch_id: str, organization_id: str | None = None) -> EvaluationReport: ...

    def historical_report(self, batch_id: str, organization_id: str) -> HistoricalBenchmarkReport: ...

    def reconcile(self, *, worker_id: str | None = None) -> int: ...
