from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from fastapi import HTTPException

from app.core.models import WarRoomScenarioRequest
from app.services.continuous_intelligence.feed import validate_remote_url
from app.services.war_room.data import POLICY_ACTIONS

from . import benchmark
from .benchmark_rights import ARCHIVABLE_LICENSES, validate_rights_review


MAX_SOURCE_BYTES = 25 * 1024 * 1024
ALLOWED_MIME = {
    "application/pdf",
    "application/json",
    "text/csv",
    "text/plain",
    "text/markdown",
}
ALLOWED_DOMAINS = {"strait", "energy", "food", "sanctions", "trade", "finance"}
COUNTRY_CODES = {"USA", "CHN", "JPN", "KOR", "TWN", "IND", "EU", "RUS", "SAU", "BRA"}
CHAIN_KEYS = {"energy", "food", "chips", "shipping", "settlement"}
ACTION_TYPES = {
    "alliance_request", "alliance_response", "deescalation_offer", "humanitarian_offer",
    "diplomatic_signal", "sanction_proposal", "trade_reroute_request", "public_narrative",
    "intelligence_request",
}
COMMITMENT_ACTION_TYPES = {"alliance_request", "deescalation_offer", "humanitarian_offer"}
BLIND_POSITIONS = {4, 8, 12, 16, 20}


def validate_profile(profile: str) -> None:
    if profile not in {"pilot", "wave", "release"}:
        raise HTTPException(status_code=422, detail="Benchmark curation profile is invalid")


def validate_domain_matrix(cases: list[dict[str, Any]], profile: str) -> None:
    validate_profile(profile)
    counts = {domain: len([item for item in cases if item.get("domain") == domain]) for domain in ALLOWED_DOMAINS}
    if profile == "pilot" and (len(cases) != 12 or any(count != 2 for count in counts.values())):
        raise HTTPException(status_code=422, detail="Pilot source plan requires exactly 12 cases (two per domain)")
    if profile == "release" and (len(cases) != 120 or any(count != 20 for count in counts.values())):
        raise HTTPException(status_code=422, detail="Release source plan requires exactly 120 cases (twenty per domain)")
    if profile == "wave":
        unique_counts = set(counts.values())
        if len(unique_counts) != 1 or not unique_counts or next(iter(unique_counts)) < 2 or next(iter(unique_counts)) >= 20:
            raise HTTPException(status_code=422, detail="Wave source plan requires the same 2-19 case count in every domain")
    for domain in ALLOWED_DOMAINS:
        items = sorted(
            [item for item in cases if item.get("domain") == domain],
            key=lambda item: (str(item.get("cutoff_at", "")), str(item.get("case_id", ""))),
        )
        expected_blind = {
            item.get("case_id")
            for index, item in enumerate(items, start=1)
            if index in BLIND_POSITIONS
        }
        actual_blind = {item.get("case_id") for item in items if item.get("split") == "blind"}
        if actual_blind != expected_blind:
            raise HTTPException(status_code=422, detail=f"Source plan split is invalid for domain: {domain}")


def validate_source_case(case: dict[str, Any], seen_evidence: set[str]) -> dict[str, Any]:
    required = {
        "case_id", "version", "domain", "split", "title", "cutoff_at",
        "observation_window_days", "scenario", "label_confidence", "evidence",
        "assumptions", "target_country_evidence", "policy_action_evidence_ids",
    }
    if not required.issubset(case) or case["domain"] not in ALLOWED_DOMAINS or case["split"] not in {"development", "blind"}:
        raise HTTPException(status_code=422, detail="Source plan case contract is invalid")
    cutoff = parse_date(case["cutoff_at"])
    observation_days = int(case["observation_window_days"])
    if cutoff.year < 2010 or cutoff.year > 2025:
        raise HTTPException(status_code=422, detail=f"Case cutoff must be between 2010 and 2025: {case['case_id']}")
    if cutoff > datetime.now(timezone.utc) or cutoff.timestamp() + observation_days * 86400 > datetime.now(timezone.utc).timestamp():
        raise HTTPException(status_code=409, detail="Source plan cutoff cannot be in the future")
    scenario = case["scenario"]
    if scenario.get("country_overrides") or scenario.get("chain_overrides"):
        raise HTTPException(status_code=422, detail=f"Scenario overrides are forbidden: {case['case_id']}")
    countries = set(scenario.get("target_countries", []))
    chains = set(scenario.get("target_chains", []))
    if len(countries) > 6 or not countries.issubset(COUNTRY_CODES) or not chains.issubset(CHAIN_KEYS):
        raise HTTPException(status_code=422, detail=f"Scenario target is not in the fixed WorldPulse universe: {case['case_id']}")
    if set(scenario.get("policy_actions", [])).difference(POLICY_ACTIONS):
        raise HTTPException(status_code=422, detail=f"Scenario policy action is invalid: {case['case_id']}")
    if scenario.get("intensity") not in {0.45, 0.65, 0.82} or scenario.get("propagation") not in {0.3, 0.45, 0.6}:
        raise HTTPException(status_code=422, detail=f"Scenario rubric value is invalid: {case['case_id']}")
    if scenario.get("duration_days") not in {30, 45, 60, 90} or int(scenario["duration_days"]) > observation_days:
        raise HTTPException(status_code=422, detail=f"Scenario duration is invalid: {case['case_id']}")
    WarRoomScenarioRequest.model_validate(scenario)
    evidence = case["evidence"]
    if not isinstance(evidence, list) or {item.get("evidence_role") for item in evidence} != {"input", "outcome"}:
        raise HTTPException(status_code=422, detail=f"Each case requires input and outcome evidence: {case['case_id']}")
    normalized_evidence = []
    input_evidence_ids: set[str] = set()
    for item in evidence:
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in seen_evidence:
            raise HTTPException(status_code=409, detail=f"Duplicate evidence id: {evidence_id}")
        seen_evidence.add(evidence_id)
        publisher = str(item.get("publisher") or "")
        configured_publishers = {
            value.strip() for value in os.getenv("WORLDPULSE_BENCHMARK_PUBLISHERS", "").split(",") if value.strip()
        }
        if (
            not publisher
            or (publisher not in benchmark.OFFICIAL_PUBLISHERS and publisher not in configured_publishers and not publisher.startswith("Official:"))
            or not str(item.get("license_name") or "")
            or not str(item.get("license_url") or "")
        ):
            raise HTTPException(status_code=422, detail=f"Evidence license metadata is incomplete: {evidence_id}")
        configured_licenses = {
            value.strip() for value in os.getenv("WORLDPULSE_BENCHMARK_LICENSES", "").split(",") if value.strip()
        }
        if item["license_name"] not in ARCHIVABLE_LICENSES and item["license_name"] not in configured_licenses:
            raise HTTPException(status_code=422, detail=f"Evidence license is not approved for local archival: {evidence_id}")
        url = validate_remote_url(str(item.get("source_url") or ""), resolve_dns=False)
        rights_review = validate_rights_review(
            item.get("rights_review"), publisher=publisher, source_url=url,
            license_name=str(item["license_name"]), license_url=str(item["license_url"]),
        )
        observed = parse_date(item.get("observed_at"))
        if item["evidence_role"] == "input" and observed > cutoff:
            raise HTTPException(status_code=409, detail=f"Input evidence is after case cutoff: {evidence_id}")
        if item["evidence_role"] == "outcome" and observed < cutoff:
            raise HTTPException(status_code=409, detail=f"Outcome evidence predates the case cutoff: {evidence_id}")
        if item["evidence_role"] == "input":
            input_evidence_ids.add(evidence_id)
        normalized_evidence.append({
            "evidence_id": evidence_id,
            "evidence_role": item["evidence_role"],
            "publisher": publisher,
            "license_name": item["license_name"],
            "license_url": item["license_url"],
            "source_url": url,
            "observed_at": observed.isoformat(),
            "cutoff_at": cutoff.isoformat(),
            "expected_mime": item.get("expected_mime", ""),
            "locator": item.get("locator", {}),
            "rights_review": rights_review,
        })
    target_country_evidence = case["target_country_evidence"]
    if not isinstance(target_country_evidence, dict) or set(target_country_evidence) != countries:
        raise HTTPException(status_code=422, detail=f"Each target country requires input evidence: {case['case_id']}")
    if any(
        not isinstance(evidence_ids, list) or not evidence_ids or not set(evidence_ids).issubset(input_evidence_ids)
        for evidence_ids in target_country_evidence.values()
    ):
        raise HTTPException(status_code=422, detail=f"Target country evidence must reference input material: {case['case_id']}")
    policy_evidence = case["policy_action_evidence_ids"]
    if not isinstance(policy_evidence, list) or not set(policy_evidence).issubset(input_evidence_ids):
        raise HTTPException(status_code=422, detail=f"Policy action evidence must reference input material: {case['case_id']}")
    if scenario.get("policy_actions") and not policy_evidence:
        raise HTTPException(status_code=422, detail=f"Policy actions require cutoff-time official evidence: {case['case_id']}")
    assumptions = validate_assumptions(case["assumptions"], scenario, input_evidence_ids, str(case["case_id"]))
    development_labels = case.get("development_labels")
    if case["split"] == "blind" and development_labels is not None:
        raise HTTPException(status_code=409, detail="Blind labels cannot appear in a source plan")
    return {
        **{key: case[key] for key in required if key != "evidence"},
        "scenario": scenario,
        "assumptions": assumptions,
        "target_country_evidence": {code: sorted(set(ids)) for code, ids in sorted(target_country_evidence.items())},
        "policy_action_evidence_ids": sorted(set(policy_evidence)),
        "development_labels": development_labels,
        "evidence": normalized_evidence,
    }


def validate_manifest_governance(case: dict[str, Any]) -> None:
    scenario = case["scenario"]
    cutoff = parse_date(case["cutoff_at"])
    observation_days = int(case["observation_window_days"])
    if cutoff.year < 2010 or cutoff.year > 2025 or cutoff > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail=f"Manifest cutoff is invalid: {case['case_id']}")
    if cutoff.timestamp() + observation_days * 86400 > datetime.now(timezone.utc).timestamp():
        raise HTTPException(status_code=409, detail=f"Manifest observation window is not closed: {case['case_id']}")
    if scenario.get("country_overrides") or scenario.get("chain_overrides"):
        raise HTTPException(status_code=422, detail=f"Manifest scenario overrides are forbidden: {case['case_id']}")
    if (
        len(set(scenario.get("target_countries", []))) > 6
        or not set(scenario.get("target_countries", [])).issubset(COUNTRY_CODES)
        or not set(scenario.get("target_chains", [])).issubset(CHAIN_KEYS)
        or set(scenario.get("policy_actions", [])).difference(POLICY_ACTIONS)
        or scenario.get("intensity") not in {0.45, 0.65, 0.82}
        or scenario.get("propagation") not in {0.3, 0.45, 0.6}
        or scenario.get("duration_days") not in {30, 45, 60, 90}
        or int(scenario["duration_days"]) > observation_days
    ):
        raise HTTPException(status_code=422, detail=f"Manifest scenario rubric is invalid: {case['case_id']}")
    input_ids = {item["evidence_id"] for item in case["evidence"] if item["evidence_role"] == "input"}
    target_map = case.get("target_country_evidence")
    if not isinstance(target_map, dict) or set(target_map) != set(scenario.get("target_countries", [])):
        raise HTTPException(status_code=422, detail=f"Each target country requires input evidence: {case['case_id']}")
    if any(not isinstance(ids, list) or not ids or not set(ids).issubset(input_ids) for ids in target_map.values()):
        raise HTTPException(status_code=422, detail=f"Target country evidence must reference input material: {case['case_id']}")
    if any(item["evidence_role"] == "outcome" and parse_date(item["observed_at"]) < cutoff for item in case["evidence"]):
        raise HTTPException(status_code=409, detail=f"Outcome evidence predates case cutoff: {case['case_id']}")
    policy_evidence = case.get("policy_action_evidence_ids")
    if not isinstance(policy_evidence, list) or not set(policy_evidence).issubset(input_ids):
        raise HTTPException(status_code=422, detail=f"Policy action evidence must reference input material: {case['case_id']}")
    if scenario.get("policy_actions") and not policy_evidence:
        raise HTTPException(status_code=422, detail=f"Policy actions require cutoff-time official evidence: {case['case_id']}")
    validate_assumptions(case.get("assumptions"), scenario, input_ids, str(case["case_id"]))


def validate_assumptions(assumptions: Any, scenario: dict[str, Any], input_ids: set[str], case_id: str) -> dict[str, Any]:
    if not isinstance(assumptions, dict):
        raise HTTPException(status_code=422, detail=f"Scenario assumptions are required: {case_id}")
    normalized: dict[str, Any] = {}
    for key in ("duration_days", "intensity", "propagation"):
        item = assumptions.get(key)
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"Scenario assumption is incomplete: {case_id}/{key}")
        evidence_ids = item.get("evidence_ids")
        reason = str(item.get("reason") or "").strip()
        reviewer = str(item.get("reviewer") or "").strip()
        if (
            item.get("value") != scenario.get(key) or not reason or not reviewer
            or not isinstance(evidence_ids, list) or not evidence_ids or not set(evidence_ids).issubset(input_ids)
        ):
            raise HTTPException(status_code=422, detail=f"Scenario assumption evidence is invalid: {case_id}/{key}")
        normalized[key] = {
            "value": item["value"], "reason": reason,
            "evidence_ids": sorted(set(evidence_ids)), "reviewer": reviewer,
        }
    return normalized


def validate_label(
    label: dict[str, Any] | None,
    *,
    observation_window_days: int | None = None,
    evidence_coverage: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    if not isinstance(label, dict):
        raise HTTPException(status_code=422, detail="Historical label must be an object")
    ranking = list(label.get("risk_ranking", []))
    top3 = list(label.get("top3_countries", []))
    if len(ranking) < 5 or len(set(ranking)) != len(ranking) or not set(ranking).issubset(COUNTRY_CODES):
        raise HTTPException(status_code=422, detail="Historical risk ranking must contain at least five known countries")
    deviation_reason = str(label.get("top3_deviation_reason") or "").strip()
    if len(top3) != 3 or len(set(top3)) != 3 or not set(top3).issubset(set(ranking)) or (top3 != ranking[:3] and not deviation_reason):
        raise HTTPException(status_code=422, detail="Historical top3 label is invalid")
    directions = label.get("supply_chain_directions", {})
    if not isinstance(directions, dict) or not directions or not set(directions).issubset(CHAIN_KEYS) or not set(directions.values()).issubset({"up", "down", "flat"}):
        raise HTTPException(status_code=422, detail="Historical supply-chain labels are invalid")
    turning_points = label.get("turning_points", [])
    if not isinstance(turning_points, list) or any(int(value) < 0 or (observation_window_days is not None and int(value) > observation_window_days) for value in turning_points):
        raise HTTPException(status_code=422, detail="Historical turning points are invalid")
    expectations = label.get("agent_outcome_expectations", {})
    if not isinstance(expectations, dict):
        raise HTTPException(status_code=422, detail="Agent outcome expectations are invalid")
    allowed = set(expectations.get("allowed_action_types", []))
    forbidden = set(expectations.get("forbidden_action_types", []))
    commitments = set(expectations.get("expected_commitment_patterns", []))
    if allowed & forbidden or not (allowed | forbidden).issubset(ACTION_TYPES) or not commitments.issubset(COMMITMENT_ACTION_TYPES):
        raise HTTPException(status_code=422, detail="Agent action expectation contract is invalid")
    coverage_countries = list(label.get("coverage_countries", ranking))
    coverage_chains = list(label.get("coverage_supply_chains", directions))
    if not set(coverage_countries).issubset(set(ranking)) or not set(coverage_chains).issubset(set(directions)):
        raise HTTPException(status_code=422, detail="Historical label coverage is inconsistent")
    if evidence_coverage is not None and (
        not set(coverage_countries).issubset(evidence_coverage["countries"])
        or not set(coverage_chains).issubset(evidence_coverage["supply_chains"])
    ):
        raise HTTPException(status_code=422, detail="Historical label coverage exceeds its official evidence")
    confidence = float(label.get("label_confidence", 0))
    if not 0.5 <= confidence <= 1:
        raise HTTPException(status_code=422, detail="Historical label confidence must be between 0.5 and 1")
    return {
        "risk_ranking": ranking,
        "top3_countries": top3,
        "top3_deviation_reason": deviation_reason,
        "supply_chain_directions": directions,
        "turning_points": [int(value) for value in turning_points],
        "agent_outcome_expectations": {
            "allowed_action_types": sorted(allowed),
            "forbidden_action_types": sorted(forbidden),
            "expected_commitment_patterns": sorted(commitments),
        },
        "coverage_countries": coverage_countries,
        "coverage_supply_chains": coverage_chains,
        "label_confidence": confidence,
    }


def evidence_coverage(evidence: list[dict[str, Any]]) -> dict[str, set[str]]:
    countries: set[str] = set()
    supply_chains: set[str] = set()
    for item in evidence:
        locator = item.get("locator", {})
        if not isinstance(locator, dict):
            continue
        countries.update(code for code in locator.get("coverage_countries", []) if code in COUNTRY_CODES)
        supply_chains.update(key for key in locator.get("coverage_supply_chains", []) if key in CHAIN_KEYS)
    return {"countries": countries, "supply_chains": supply_chains}


def parse_date(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Benchmark timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
