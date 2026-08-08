from typing import Any

from .application import NegotiationReadApplicationService, negotiation_read_service
from .ports import NegotiationReadApplicationPort
from .proof_sources import (
    AgentRuntimeResultSource,
    CommitmentLedgerSource,
    ConsistencyAuditSource,
    HybridModifierBundleSource,
    HybridReplaySource,
    KernelProposalBatchSource,
    MockAgentBatchSource,
    NegotiationEligibilitySource,
    NegotiationProposalBatchSource,
    NegotiationReplaySource,
    NarrativeDiffusionSource,
    NegotiationRoundSource,
    ProjectionAuditSource,
    extract_ar_claims,
    extract_cl_claims,
    extract_consistency_claims,
    extract_el_claims,
    extract_hr_claims,
    extract_mb_claims,
    extract_nd_claims,
    extract_nr_claims,
    extract_np_claims,
    extract_pa_claims,
    extract_pb_claims,
    extract_rr_claims,
    mock_agent_batch_source_hash,
)
from .repository import NegotiationRepository


def run_negotiation(*args: Any, **kwargs: Any):
    """Lazy compatibility export that avoids package import cycles."""
    from .engine import run_negotiation as implementation

    return implementation(*args, **kwargs)


def replay_negotiation_from_storage(*args: Any, **kwargs: Any):
    """Lazy compatibility export for provider-free negotiation replay."""
    from .replay import replay_negotiation_from_storage as implementation

    return implementation(*args, **kwargs)

__all__ = [
    "NegotiationReadApplicationPort",
    "NegotiationReadApplicationService",
    "NegotiationRepository",
    "AgentRuntimeResultSource",
    "CommitmentLedgerSource",
    "ConsistencyAuditSource",
    "HybridModifierBundleSource",
    "HybridReplaySource",
    "KernelProposalBatchSource",
    "MockAgentBatchSource",
    "NegotiationEligibilitySource",
    "NegotiationProposalBatchSource",
    "NegotiationReplaySource",
    "NarrativeDiffusionSource",
    "NegotiationRoundSource",
    "ProjectionAuditSource",
    "extract_ar_claims",
    "extract_cl_claims",
    "extract_consistency_claims",
    "extract_el_claims",
    "extract_hr_claims",
    "extract_mb_claims",
    "extract_nd_claims",
    "extract_nr_claims",
    "extract_np_claims",
    "extract_pa_claims",
    "extract_pb_claims",
    "extract_rr_claims",
    "mock_agent_batch_source_hash",
    "negotiation_read_service",
    "replay_negotiation_from_storage",
    "run_negotiation",
]
