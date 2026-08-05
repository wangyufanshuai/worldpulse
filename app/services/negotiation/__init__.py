from typing import Any

from .application import NegotiationReadApplicationService, negotiation_read_service
from .ports import NegotiationReadApplicationPort
from .proof_sources import (
    CommitmentLedgerSource,
    NegotiationEligibilitySource,
    NegotiationProposalBatchSource,
    NarrativeDiffusionSource,
    extract_cl_claims,
    extract_el_claims,
    extract_nd_claims,
    extract_np_claims,
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
    "CommitmentLedgerSource",
    "NegotiationEligibilitySource",
    "NegotiationProposalBatchSource",
    "NarrativeDiffusionSource",
    "extract_cl_claims",
    "extract_el_claims",
    "extract_nd_claims",
    "extract_np_claims",
    "negotiation_read_service",
    "replay_negotiation_from_storage",
    "run_negotiation",
]
