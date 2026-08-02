from .application import EvidenceApplicationService
from .ports import EvidenceApplicationPort


evidence_service: EvidenceApplicationPort = EvidenceApplicationService()

__all__ = ["EvidenceApplicationPort", "EvidenceApplicationService", "evidence_service"]
