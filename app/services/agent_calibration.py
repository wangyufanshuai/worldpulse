from __future__ import annotations

from app.core.models import AgentState


def calibrate_state(defaults: dict[str, float], indicators: dict[str, float | str | None]) -> tuple[AgentState, dict[str, str], list[str], float]:
    fallback_fields: list[str] = []
    sources: dict[str, str] = {}

    def real_or_default(field: str, value: float | None) -> float:
        if value is None:
            fallback_fields.append(field)
            sources[field] = "内置可解释兜底"
            return float(defaults[field])
        sources[field] = "World Bank 指标校准"
        return float(max(0, min(100, value)))

    gdp_pressure = real_or_default(
        "gdp_pressure",
        _blend(
            _inverse_scale(_num(indicators.get("gdp_growth")), low=-4, high=7),
            _scale(_num(indicators.get("inflation")), low=1, high=18),
            _scale(_num(indicators.get("external_debt_pct_gni")), low=20, high=120),
            weights=(0.45, 0.35, 0.20),
        ),
    )
    trade_exposure = real_or_default("trade_exposure", _scale(_num(indicators.get("trade_pct_gdp")), low=20, high=140))
    energy_vulnerability = real_or_default("energy_vulnerability", _energy_score(_num(indicators.get("energy_imports_pct")), defaults["energy_vulnerability"]))
    military_pressure = real_or_default("military_pressure", _scale(_num(indicators.get("military_pct_gdp")), low=0.4, high=6.0))

    sentiment_pressure = float(defaults["sentiment_pressure"])
    rate_pressure = float(defaults["rate_pressure"])
    conflict_pressure = float(defaults["conflict_pressure"])
    for field in ["sentiment_pressure", "rate_pressure", "conflict_pressure"]:
        sources[field] = "全球/区域公共风险代理"

    risk = _risk_from_values(gdp_pressure, trade_exposure, energy_vulnerability, military_pressure, sentiment_pressure, rate_pressure, conflict_pressure)
    state = AgentState(
        gdp_pressure=round(gdp_pressure, 2),
        trade_exposure=round(trade_exposure, 2),
        energy_vulnerability=round(energy_vulnerability, 2),
        military_pressure=round(military_pressure, 2),
        sentiment_pressure=round(sentiment_pressure, 2),
        rate_pressure=round(rate_pressure, 2),
        conflict_pressure=round(conflict_pressure, 2),
        stability=round(max(0, 100 - risk), 2),
    )
    measured = 4 - sum(1 for field in ["gdp_pressure", "trade_exposure", "energy_vulnerability", "military_pressure"] if field in fallback_fields)
    data_quality = round((measured / 4) * 72 + 18, 1)
    return state, sources, fallback_fields, data_quality


def explain_state(agent_name: str, state: AgentState, sources: dict[str, str]) -> dict[str, str]:
    return {
        "gdp_pressure": f"{agent_name} 的增长、通胀和外债代理映射为 {state.gdp_pressure:.1f}/100。来源：{sources.get('gdp_pressure')}",
        "trade_exposure": f"贸易开放度映射为 {state.trade_exposure:.1f}/100，越高表示关税和贸易阻断更敏感。来源：{sources.get('trade_exposure')}",
        "energy_vulnerability": f"能源净进口依赖映射为 {state.energy_vulnerability:.1f}/100，越高表示油气冲击更敏感。来源：{sources.get('energy_vulnerability')}",
        "military_pressure": f"军费占 GDP 及区域压力映射为 {state.military_pressure:.1f}/100。来源：{sources.get('military_pressure')}",
        "sentiment_pressure": f"舆情/政策不确定性代理为 {state.sentiment_pressure:.1f}/100。来源：{sources.get('sentiment_pressure')}",
        "rate_pressure": f"融资和利率压力代理为 {state.rate_pressure:.1f}/100。来源：{sources.get('rate_pressure')}",
        "conflict_pressure": f"冲突暴露代理为 {state.conflict_pressure:.1f}/100。来源：{sources.get('conflict_pressure')}",
    }


def risk_from_state(state: AgentState) -> float:
    return round(
        state.gdp_pressure * 0.18
        + state.trade_exposure * 0.16
        + state.energy_vulnerability * 0.16
        + state.military_pressure * 0.13
        + state.sentiment_pressure * 0.12
        + state.rate_pressure * 0.13
        + state.conflict_pressure * 0.12,
        2,
    )


def _num(value: float | str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _scale(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    return max(0, min(100, (value - low) / (high - low) * 100))


def _inverse_scale(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    return max(0, min(100, (high - value) / (high - low) * 100))


def _energy_score(value: float | None, default: float) -> float | None:
    if value is None:
        return None
    if value < 0:
        return max(5, min(35, 25 + value * 0.2))
    return max(0, min(100, value))


def _blend(*values: float | None, weights: tuple[float, ...]) -> float | None:
    available = [(value, weights[index]) for index, value in enumerate(values) if value is not None]
    if not available:
        return None
    total_weight = sum(weight for _value, weight in available)
    return sum(value * weight for value, weight in available) / total_weight


def _risk_from_values(*values: float) -> float:
    weights = [0.18, 0.16, 0.16, 0.13, 0.12, 0.13, 0.12]
    return sum(value * weight for value, weight in zip(values, weights))
