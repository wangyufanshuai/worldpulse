"""Compatibility façade for governed historical benchmark tooling.

Public imports remain stable while validation, acquisition, manifests, and
sealed-label responsibilities live in focused internal modules.
"""

from .benchmark_acquisition import fetch_sources, source_status
from .benchmark_contracts import (
    ACTION_TYPES,
    ALLOWED_DOMAINS,
    ALLOWED_MIME,
    BLIND_POSITIONS,
    CHAIN_KEYS,
    COMMITMENT_ACTION_TYPES,
    COUNTRY_CODES,
    MAX_SOURCE_BYTES,
    evidence_coverage,
    parse_date,
    validate_domain_matrix,
    validate_label,
    validate_manifest_governance,
    validate_profile,
    validate_source_case,
)
from .benchmark_labels import pack_labels, validate_label_payload
from .benchmark_manifests import (
    build_manifest_from_lock,
    preflight_manifest,
    validate_source_plan,
)


# Preserve the internal names used by V1.12 callers while new code migrates to
# the public helpers above. These aliases intentionally contain no behavior.
_evidence_coverage = evidence_coverage
_parse_date = parse_date
_validate_domain_matrix = validate_domain_matrix
_validate_label = validate_label
_validate_manifest_governance = validate_manifest_governance
_validate_profile = validate_profile
_validate_source_case = validate_source_case


__all__ = [
    "ACTION_TYPES",
    "ALLOWED_DOMAINS",
    "ALLOWED_MIME",
    "BLIND_POSITIONS",
    "CHAIN_KEYS",
    "COMMITMENT_ACTION_TYPES",
    "COUNTRY_CODES",
    "MAX_SOURCE_BYTES",
    "build_manifest_from_lock",
    "evidence_coverage",
    "fetch_sources",
    "pack_labels",
    "preflight_manifest",
    "source_status",
    "validate_label_payload",
    "validate_source_plan",
]
