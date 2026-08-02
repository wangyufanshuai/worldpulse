"""Compatibility application adapter for the Evidence bounded context.

The adapter delegates to the V1 evidence registry while callers migrate to the
public port. Storage extraction can proceed later without changing API,
compiler, ingestion or replay consumers again.
"""

from __future__ import annotations

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
from app.services import evidence_registry as legacy_registry


class EvidenceApplicationService:
    def create_source(self, payload: EvidenceSourceCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidenceSource:
        return legacy_registry.create_source(payload, actor, organization_id=organization_id)

    def list_sources(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        organization_id: str | None = None,
    ) -> list[EvidenceSource]:
        return legacy_registry.list_sources(status=status, source_type=source_type, organization_id=organization_id)

    def get_source(self, source_id: str, *, organization_id: str | None = None) -> EvidenceSource:
        return legacy_registry.get_source(source_id, organization_id=organization_id)

    def create_snapshot(
        self,
        payload: EvidenceSnapshotCreate,
        actor: UserIdentity,
        *,
        organization_id: str | None = None,
        quota_reserved: bool = False,
    ) -> EvidenceSnapshot:
        return legacy_registry.create_snapshot(
            payload,
            actor,
            organization_id=organization_id,
            quota_reserved=quota_reserved,
        )

    def get_snapshot(self, snapshot_id: str, *, organization_id: str | None = None) -> EvidenceSnapshot:
        return legacy_registry.get_snapshot(snapshot_id, organization_id=organization_id)

    def create_claim(self, payload: EvidenceClaimCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidenceClaim:
        return legacy_registry.create_claim(payload, actor, organization_id=organization_id)

    def get_claim(self, claim_id: str, *, organization_id: str | None = None) -> EvidenceClaim:
        return legacy_registry.get_claim(claim_id, organization_id=organization_id)

    def search_evidence(
        self,
        *,
        query: str = "",
        project_id: str | None = None,
        category: str | None = None,
        cutoff_at: str | None = None,
        limit: int = 50,
        organization_id: str | None = None,
    ) -> EvidenceSearchResult:
        return legacy_registry.search_evidence(
            query=query,
            project_id=project_id,
            category=category,
            cutoff_at=cutoff_at,
            limit=limit,
            organization_id=organization_id,
        )

    def create_pack(self, payload: EvidencePackCreate, actor: UserIdentity, *, organization_id: str | None = None) -> EvidencePack:
        return legacy_registry.create_pack(payload, actor, organization_id=organization_id)

    def get_pack(self, pack_id: str, *, organization_id: str | None = None) -> EvidencePack:
        return legacy_registry.get_pack(pack_id, organization_id=organization_id)

    def sync_project_evidence(
        self,
        project_id: str,
        actor: UserIdentity,
        *,
        run_id: str | None = None,
        organization_id: str | None = None,
    ) -> EvidenceSyncResult:
        return legacy_registry.sync_project_evidence(
            project_id,
            actor,
            run_id=run_id,
            organization_id=organization_id,
        )

    def sync_calibration_evidence(self, actor: UserIdentity, *, organization_id: str | None = None) -> dict:
        return legacy_registry.sync_calibration_evidence(actor, organization_id=organization_id)

    def project_evidence_summary(self, project_id: str) -> ProjectEvidenceSummary:
        return legacy_registry.project_evidence_summary(project_id)

    def evidence_manifest_for_run(self, project_id: str, run_id: str) -> dict | None:
        return legacy_registry.evidence_manifest_for_run(project_id, run_id)
