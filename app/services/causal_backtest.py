from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.models import CausalBacktestResult, MarketImpact, SimilarEvent
from app.services.causal_graph import IMPACT_RULES
from app.services.data_sources import load_world_data


EVENT_SIGNAL_COLUMNS = {
    "conflict": "conflict_intensity",
    "sanctions": "policy_uncertainty",
    "energy": "oil",
    "food": "food_pressure",
    "rates": "yield_curve",
    "trade": "policy_uncertainty",
    "climate": "drought_stress",
}

ASSET_COLUMNS = {
    "sp500": "sp500",
    "nasdaq": "nasdaq",
    "gold": "gold",
    "oil": "oil",
    "vix": "vix",
    "dollar": "dollar_stress",
}


def run_causal_backtest(event_type: str = "conflict", window_days: int = 120, horizon_days: int = 20) -> CausalBacktestResult:
    window_days = max(60, min(int(window_days), 420))
    horizon_days = max(5, min(int(horizon_days), 60))
    frame, _sources = load_world_data(days=420)
    frame = frame.reset_index(drop=True)
    events = _event_indices(frame, event_type)
    impacts = _asset_impacts(frame, event_type, events, horizon_days)
    similar = _similar_events(frame, event_type, events, horizon_days)
    hit_rate = _hit_rate(impacts)
    average_impact = float(np.mean([abs(item.expected_return_pct) for item in impacts])) if impacts else 0
    max_error = _max_direction_error(frame, event_type, events, horizon_days)
    return CausalBacktestResult(
        event_type=event_type,
        window_days=window_days,
        sample_count=len(events),
        hit_rate=round(hit_rate, 2),
        average_impact=round(average_impact, 2),
        max_error=round(max_error, 2),
        impacts=impacts,
        similar_events=similar,
        error_attribution=_error_attribution(len(events), hit_rate),
    )


def _event_indices(frame: pd.DataFrame, event_type: str) -> list[int]:
    column = EVENT_SIGNAL_COLUMNS.get(event_type, "conflict_intensity")
    if column not in frame.columns:
        return [len(frame) - 80, len(frame) - 40]
    series = frame[column].pct_change().abs() if column in {"oil"} else frame[column]
    threshold = float(series.quantile(0.82))
    indices = [idx for idx, value in enumerate(series.fillna(0)) if value >= threshold and 20 <= idx < len(frame) - 25]
    sampled = []
    last = -999
    for idx in indices:
        if idx - last >= 12:
            sampled.append(idx)
            last = idx
    return sampled[-18:] or [max(20, len(frame) - 80), max(25, len(frame) - 40)]


def _asset_impacts(frame: pd.DataFrame, event_type: str, indices: list[int], horizon_days: int) -> list[MarketImpact]:
    impacts = []
    rules = IMPACT_RULES.get(event_type, IMPACT_RULES["conflict"])
    for asset_key, asset_name, expected_direction, _base in rules:
        column = ASSET_COLUMNS.get(asset_key)
        if column not in frame.columns:
            continue
        moves = [_forward_move(frame, column, idx, horizon_days) for idx in indices]
        avg = float(np.mean(moves)) if moves else 0
        direction = "up" if avg > 0 else "down" if avg < 0 else "mixed"
        confidence = _direction_confidence(moves, expected_direction)
        impacts.append(
            MarketImpact(
                asset_key=asset_key,
                asset_name=asset_name,
                direction=direction,
                expected_return_pct=round(avg, 2),
                confidence=confidence,
                rationale=f"历史相似 {len(indices)} 个窗口后 {horizon_days} 日平均变化为 {avg:.2f}%。",
            )
        )
    return impacts


def _similar_events(frame: pd.DataFrame, event_type: str, indices: list[int], horizon_days: int) -> list[SimilarEvent]:
    column = EVENT_SIGNAL_COLUMNS.get(event_type, "conflict_intensity")
    if column not in frame.columns:
        column = "conflict_intensity"
    current = float(frame[column].iloc[-1])
    scored = []
    for idx in indices:
        value = float(frame[column].iloc[idx])
        similarity = 100 - min(100, abs(current - value) * 100)
        sp_move = _forward_move(frame, "sp500", idx, horizon_days) if "sp500" in frame.columns else 0
        oil_move = _forward_move(frame, "oil", idx, horizon_days) if "oil" in frame.columns else 0
        scored.append(
            SimilarEvent(
                date=frame["date"].iloc[idx].strftime("%Y-%m-%d"),
                event_type=event_type,
                title=f"{event_type} 高强度历史窗口",
                similarity=round(max(10, similarity), 1),
                market_move=f"SP500 {sp_move:+.2f}%，WTI {oil_move:+.2f}%",
                notes=f"事件后 {horizon_days} 日用于相似事件回测，不代表未来必然重复。",
            )
        )
    return sorted(scored, key=lambda item: item.similarity, reverse=True)[:6]


def _forward_move(frame: pd.DataFrame, column: str, idx: int, horizon_days: int) -> float:
    start = float(frame[column].iloc[idx])
    end_idx = min(idx + horizon_days, len(frame) - 1)
    end = float(frame[column].iloc[end_idx])
    if column in {"vix", "dollar_stress"}:
        return (end - start) * 100
    return (end / start - 1) * 100 if start else 0


def _direction_confidence(moves: list[float], expected_direction: str) -> float:
    if not moves:
        return 25
    signs = np.array(moves) > 0
    if expected_direction == "down":
        hit_rate = float((~signs).mean())
    elif expected_direction == "up":
        hit_rate = float(signs.mean())
    else:
        hit_rate = 0.5
    dispersion = float(np.std(moves))
    return round(max(20, min(92, hit_rate * 70 + max(0, 20 - dispersion))), 1)


def _hit_rate(impacts: list[MarketImpact]) -> float:
    if not impacts:
        return 0
    return float(np.mean([item.confidence for item in impacts]) / 100)


def _max_direction_error(frame: pd.DataFrame, event_type: str, indices: list[int], horizon_days: int) -> float:
    rules = IMPACT_RULES.get(event_type, IMPACT_RULES["conflict"])
    errors = []
    for asset_key, _asset_name, expected_direction, _base in rules:
        column = ASSET_COLUMNS.get(asset_key)
        if column not in frame.columns:
            continue
        for idx in indices:
            move = _forward_move(frame, column, idx, horizon_days)
            if (expected_direction == "up" and move < 0) or (expected_direction == "down" and move > 0):
                errors.append(abs(move))
    return float(max(errors)) if errors else 0


def _error_attribution(sample_count: int, hit_rate: float) -> list[str]:
    notes = []
    if sample_count < 8:
        notes.append("历史样本数偏少，置信度应下调。")
    if hit_rate < 0.55:
        notes.append("事件类型与资产方向的一致性较弱，可能存在错误归因。")
    notes.extend(
        [
            "事件常与利率、美元、财报和政策预期同时发生，单因子归因可能过度简化。",
            "市场可能提前反应，新闻事件时间戳不一定等于价格冲击起点。",
            "使用宽基指数和商品作为代理资产，行业 ETF 与个股影响需要后续细化。",
        ]
    )
    return notes
