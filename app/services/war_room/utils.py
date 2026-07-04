from __future__ import annotations

from .data import COUNTRIES

from app.core.models import (
    AgentDecision,
    ConflictEvent,
    SupplyChainLink,
    WarRoomCountryAgent,
    WarRoomHeatmapCell,
    WarRoomImpactGraph,
    WarRoomPresetBundle,
    WarRoomRun,
    WarRoomScenario,
    WarRoomScenarioRequest,
    WarRoomTimelinePoint,
)


def _base_agent(code: str) -> WarRoomCountryAgent:
    return next(agent for agent in COUNTRIES if agent.code == code)


def _valid_codes(values: list[str], allowed: set[str]) -> list[str]:
    seen = []
    for value in values or []:
        key = str(value)
        if key in allowed and key not in seen:
            seen.append(key)
    return seen


def _clean_overrides(raw: dict[str, dict[str, float]], allowed_keys: set[str]) -> dict[str, dict[str, float]]:
    clean: dict[str, dict[str, float]] = {}
    if not isinstance(raw, dict):
        return clean
    for key, fields in raw.items():
        if key not in allowed_keys or not isinstance(fields, dict):
            continue
        clean[key] = {str(field): _clamp(float(value), 0, 100) for field, value in fields.items() if _is_number(value)}
    return clean


def _top_drivers(breakdown: dict[str, float]) -> list[str]:
    return [key for key, _ in sorted(breakdown.items(), key=lambda item: item[1], reverse=True)[:3]]


def _is_number(value: object) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))

