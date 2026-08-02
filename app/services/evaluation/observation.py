"""Artifact-backed Agent outcome observations.

The reader is resolved at call time so existing tests and the compatibility
façade can still patch the lifecycle repository. No provider response or
blind label is accepted as a substitute for a stored projection Artifact.
"""

from __future__ import annotations

from collections.abc import Callable

from .metrics import average_optional

ArtifactReader = Callable[[str, str], dict | None]


def _default_artifact_reader(run_id: str, artifact_type: str) -> dict | None:
    from app.services.run_lifecycle import repository as lifecycle_repository

    return lifecycle_repository.get_latest_artifact_content(run_id, artifact_type)


def agent_outcome_observation(
    run_id: str,
    engine_mode: str,
    labels: dict,
    *,
    artifact_reader: ArtifactReader | None = None,
) -> dict:
    read_artifact = artifact_reader or _default_artifact_reader
    expectations = labels.get("agent_outcome_expectations", {})
    allowed = set(expectations.get("allowed_action_types", []))
    forbidden = set(expectations.get("forbidden_action_types", []))
    expected_commitments = set(expectations.get("expected_commitment_patterns", []))
    actual: set[str] = set()
    active_commitments: set[str] = set()
    if engine_mode == "hybrid":
        proposals = read_artifact(run_id, "agent_action_proposals") or {}
        proposal_types: dict[str, str] = {}
        for item in proposals.get("proposals", []):
            proposal_id = item.get("proposal_id")
            action_type = item.get("action_type")
            if isinstance(proposal_id, str) and isinstance(action_type, str):
                proposal_types[proposal_id] = action_type
        projection = read_artifact(run_id, "agent_action_projection_audit") or {}
        for item in projection.get("records", []):
            proposal_id = item.get("proposal_id")
            if item.get("outcome") == "accepted" and item.get("projection_status") == "projected" and isinstance(proposal_id, str):
                action_type = proposal_types.get(proposal_id)
                if action_type:
                    actual.add(action_type)
    elif engine_mode == "negotiation":
        source = read_artifact(run_id, "negotiation_action_observation")
        if not source:
            raise ValueError("Negotiation action observation Artifact is missing")
        actual = set(source.get("applied_action_types", []))
        active_commitments = set(source.get("active_commitment_types", []))
    else:
        return {
            "engine_mode": engine_mode,
            "score": None,
            "allowed_action_recall": None,
            "forbidden_action_pass": None,
            "commitment_pattern_match": None,
            "actual_action_types": [],
            "active_commitment_types": [],
            "verifier_version": "agent-outcome-observation.v1",
        }
    allowed_recall = len(actual & allowed) / len(allowed) if allowed else None
    forbidden_pass = (1.0 if not (actual & forbidden) else 0.0) if forbidden else None
    commitment_match = len(active_commitments & expected_commitments) / len(expected_commitments) if expected_commitments else None
    components = [(allowed_recall, 50), (forbidden_pass, 30)]
    if engine_mode == "negotiation":
        components.append((commitment_match, 20))
    weighted = [(value, weight) for value, weight in components if value is not None]
    score = sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted) if weighted else None
    return {
        "engine_mode": engine_mode,
        "score": round(score, 6) if score is not None else None,
        "allowed_action_recall": round(allowed_recall, 6) if allowed_recall is not None else None,
        "forbidden_action_pass": forbidden_pass,
        "commitment_pattern_match": round(commitment_match, 6) if commitment_match is not None else None,
        "actual_action_types": sorted(actual),
        "active_commitment_types": sorted(active_commitments),
        "verifier_version": "agent-outcome-observation.v1",
    }


def aggregate_agent_observations(rows: list[dict]) -> dict:
    case_mode_rows: list[dict] = []
    for (case_id, mode) in sorted({(item["case_id"], item["mode"]) for item in rows}):
        selected = [item for item in rows if item["case_id"] == case_id and item["mode"] == mode]
        case_mode_rows.append({
            "case_id": case_id,
            "mode": mode,
            "seed_count": len(selected),
            "score": average_optional(selected, "score"),
            "allowed_action_recall": average_optional(selected, "allowed_action_recall"),
            "forbidden_action_pass": average_optional(selected, "forbidden_action_pass"),
            "commitment_pattern_match": average_optional(selected, "commitment_pattern_match"),
            "not_applicable": {
                key: sum(item.get(key) is None for item in selected)
                for key in ("score", "allowed_action_recall", "forbidden_action_pass", "commitment_pattern_match")
            },
        })
    modes: dict[str, dict] = {}
    result = {
        "verifier_version": "agent-outcome-observation.v1",
        "member_count": len(rows),
        "case_count": len({item["case_id"] for item in rows}),
        "case_mode_observations": case_mode_rows,
        "modes": modes,
    }
    for mode in ("hybrid", "negotiation"):
        selected = [item for item in case_mode_rows if item["mode"] == mode]
        modes[mode] = {
            "case_count": len(selected),
            "member_count": sum(item["seed_count"] for item in selected),
            "score": average_optional(selected, "score"),
            "allowed_action_recall": average_optional(selected, "allowed_action_recall"),
            "forbidden_action_pass": average_optional(selected, "forbidden_action_pass"),
            "commitment_pattern_match": average_optional(selected, "commitment_pattern_match"),
            "not_applicable": {
                key: sum(item["not_applicable"][key] for item in selected)
                for key in ("score", "allowed_action_recall", "forbidden_action_pass", "commitment_pattern_match")
            },
        }
    return result
