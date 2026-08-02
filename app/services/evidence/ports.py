"""Application port for the Evidence & Ingestion bounded context."""

from __future__ import annotations

from typing import Protocol

from app.core.evidence_models import (
    EvidenceClaim,
    EvidenceClaimCreate,
    EvidencePack,
    EvidencePackCreate,
    EvidenceSearchResult,
    EvidenceSnapshot,
    EvidenceSnapshotCreate,
    EvidenceSource,
    EvidenceSourceCreate,
    EvidenceSyncResult,
    ProjectEvidenceSummary,
)
from app.core.trust_models import UserIdentity


class EvidenceApplicationPort(Protocol):
    def create_source(
        self,
        payload: EvidenceSourceCreate,
        actor: UserIdentity,
        *,
        organization_id: str | None = None,
    ) -> EvidenceSource: ...

    def list_sources(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        organization_id: str | None = None,
    ) -> list[EvidenceSource]: ...

    def get_source(self, source_id: str, *, organization_id: str | None = None) -> EvidenceSource: ...

    def create_snapshot(
        self,
        payload: EvidenceSnapshotCreate,
        actor: UserIdentity,
        *,
        organization_id: str | None = None,
        quota_reserved: bool = False,
    ) -> EvidenceSnapshot: ...

    def get_snapshot(self, snapshot_id: str, *, organization_id: str | None = None) -> EvidenceSnapshot: ...

    def create_claim(
        self,
        payload: EvidenceClaimCreate,
        actor: UserIdentity,
        *,
        organization_id: str | None = None,
    ) -> EvidenceClaim: ...

    def get_claim(self, claim_id: str, *, organization_id: str | None = None) -> EvidenceClaim: ...

    def search_evidence(
        self,
        *,
        query: str = "",
        project_id: str | None = None,
        category: str | None = None,
        cutoff_at: str | None = None,
        limit: int = 50,
        organization_id: str | None = None,
    ) -> EvidenceSearchResult: ...

    def create_pack(
        self,
        payload: EvidencePackCreate,
        actor: UserIdentity,
        *,
        organization_id: str | None = None,
    ) -> EvidencePack: ...

    def get_pack(self, pack_id: str, *, organization_id: str | None = None) -> EvidencePack: ...

    def sync_project_evidence(
        self,
        project_id: str,
        actor: UserIdentity,
        *,
        run_id: str | None = None,
        organization_id: str | None = None,
    ) -> EvidenceSyncResult: ...

    def sync_calibration_evidence(self, actor: UserIdentity, *, organization_id: str | None = None) -> dict: ...

    def project_evidence_summary(self, project_id: str) -> ProjectEvidenceSummary: ...

    def evidence_manifest_for_run(self, project_id: str, run_id: str) -> dict | None: ...
