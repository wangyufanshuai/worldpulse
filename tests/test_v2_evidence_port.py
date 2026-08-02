from __future__ import annotations

from app.api import v4
from app.services.evidence import EvidenceApplicationPort, EvidenceApplicationService, evidence_service
from app.services.evidence import application as evidence_application


def test_evidence_application_service_delegates_to_legacy_adapter(monkeypatch):
    captured = {}

    def list_sources(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(evidence_application.legacy_registry, "list_sources", list_sources)
    port: EvidenceApplicationPort = EvidenceApplicationService()

    assert port.list_sources(status="active", source_type="official", organization_id="org_1") == []
    assert captured == {"status": "active", "source_type": "official", "organization_id": "org_1"}


def test_v4_api_uses_the_evidence_application_port():
    assert v4.service is evidence_service
