"""Pure evaluation metrics for the historical observation boundary.

This module intentionally has no database or provider dependency. It can be
used by batch aggregation, offline verification and future report renderers
without importing the run lifecycle or API layer.
"""

from __future__ import annotations

from app.services.war_room.data import SUPPLY_CHAINS


def historical_case_metrics(result: dict, expected: dict, label_confidence: float, evidence_count: int) -> dict:
    countries = sorted(result.get("country_agents", []), key=lambda item: float(item.get("risk_score", 0)), reverse=True)
    ranking = [item.get("code") for item in countries if item.get("code")]
    expected_ranking = list(expected.get("risk_ranking", []))
    expected_top3 = list(expected.get("top3_countries", []))
    baseline_pressure = {item.key: float(item.pressure_score) for item in SUPPLY_CHAINS}
    chain_actual = {}
    for item in result.get("supply_chains", []):
        key = item.get("key")
        if not key:
            continue
        direction = item.get("direction")
        if direction not in {"up", "down", "flat"}:
            pressure = item.get("pressure_score")
            if pressure is None or key not in baseline_pressure:
                direction = None
            else:
                delta = float(pressure) - baseline_pressure[key]
                direction = "up" if delta >= 2.0 else "down" if delta <= -2.0 else "flat"
        chain_actual[key] = direction
    chain_expected = expected.get("supply_chain_directions", {})
    actual_turns = [int(item.get("day", 0)) for item in result.get("timeline", []) if item.get("turning_point")]
    expected_turns = [int(item) for item in expected.get("turning_points", [])]
    ranked_country_coverage = len(set(expected_ranking) & set(ranking)) / 10
    chain_coverage = len(set(chain_expected) & set(chain_actual)) / 5
    return {
        "risk_spearman": spearman(ranking, expected_ranking),
        "top3_overlap": len(set(ranking[:3]) & set(expected_top3)) / 3 if expected_top3 else 1.0,
        "supply_chain_direction_accuracy": mapping_accuracy(chain_actual, chain_expected),
        "turning_point_error_days": turning_error(actual_turns, expected_turns),
        "agent_outcome_agreement": None,
        "data_coverage": round(min(1.0, 0.7 * ranked_country_coverage + 0.3 * chain_coverage) if evidence_count >= 2 else 0.0, 6),
        "label_confidence": float(label_confidence),
    }


def average(rows: list[dict], key: str) -> float:
    return round(sum(float(item[key]) for item in rows) / max(1, len(rows)), 6)


def average_optional(rows: list[dict], key: str) -> float | None:
    values = [float(item[key]) for item in rows if item.get(key) is not None]
    return round(sum(values) / len(values), 6) if values else None


def mapping_accuracy(actual: dict, expected: dict) -> float:
    keys = set(expected)
    return sum(actual.get(key) == expected.get(key) for key in keys) / len(keys) if keys else 0.0


def spearman(actual: list[str], expected: list[str]) -> float:
    common = [item for item in expected if item in actual]
    if len(common) < 2:
        return 0.0
    actual_rank = {item: actual.index(item) for item in common}
    expected_rank = {item: expected.index(item) for item in common}
    n = len(common)
    d2 = sum((actual_rank[item] - expected_rank[item]) ** 2 for item in common)
    return max(-1.0, min(1.0, 1 - (6 * d2) / (n * (n * n - 1))))


def turning_error(actual: list[int], expected: list[int]) -> float:
    if not expected:
        return 0.0 if not actual else float(max(actual))
    if not actual:
        return float(max(expected))
    return sum(abs(value - actual[min(index, len(actual) - 1)]) for index, value in enumerate(expected)) / len(expected)
