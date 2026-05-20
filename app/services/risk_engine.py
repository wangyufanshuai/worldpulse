from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.core.models import (
    ComponentAnalysis,
    CompositeRisk,
    IndicatorAnalysis,
    ReplayAssetMove,
    ReplayComponentChange,
    ReplayResult,
    RiskComponent,
    RiskAnalysis,
    RiskOverview,
    RiskPoint,
)
from app.services.config import load_config
from app.services.data_sources import load_world_data


def build_risk_history(days: int = 420) -> tuple[list[RiskPoint], dict[str, str]]:
    frame, sources = load_world_data(days=days)
    scored = _score_frame(frame)
    return _points_from_scored(scored), sources


def build_risk_overview(days: int = 420) -> RiskOverview:
    frame, sources = load_world_data(days=days)
    scored = _score_frame(frame)
    return RiskOverview(latest=_latest_from_scored(frame, scored, sources), history=_points_from_scored(scored))


def _points_from_scored(scored: pd.DataFrame) -> list[RiskPoint]:
    return [
        RiskPoint(
            date=row.date.strftime("%Y-%m-%d"),
            score=round(float(row.composite), 2),
            financial=round(float(row.financial), 2),
            climate=round(float(row.climate), 2),
            geopolitical=round(float(row.geopolitical), 2),
            ecology=round(float(row.ecology), 2),
            macro=round(float(row.macro), 2),
        )
        for row in scored.itertuples(index=False)
    ]


def build_latest_risk() -> CompositeRisk:
    frame, sources = load_world_data(days=420)
    scored = _score_frame(frame)
    return _latest_from_scored(frame, scored, sources)


def build_risk_analysis(days: int = 420) -> RiskAnalysis:
    frame, sources = load_world_data(days=days)
    scored = _score_frame(frame)
    latest = scored.iloc[-1]
    previous = scored.iloc[-21] if len(scored) > 21 else scored.iloc[0]
    indicator_scores = _indicator_score_frame(frame)
    indicator_latest = indicator_scores.iloc[-1]
    indicator_previous = indicator_scores.iloc[-21] if len(indicator_scores) > 21 else indicator_scores.iloc[0]
    config = load_config()
    components = []
    all_indicators = []
    for key, name in _component_display_names().items():
        indicators = _indicator_analysis_for_component(key, indicator_latest, indicator_previous, sources)
        all_indicators.extend(indicators)
        contribution = float(latest[key]) * float(config[key]["weight"])
        components.append(
            ComponentAnalysis(
                key=key,
                name=name,
                score=round(float(latest[key]), 2),
                weight=float(config[key]["weight"]),
                contribution=round(contribution, 2),
                delta_30d=round(float(latest[key]) - float(previous[key]), 2),
                share_of_total=round(contribution / max(float(latest["composite"]), 0.01) * 100, 1),
                indicators=indicators,
            )
        )
    return RiskAnalysis(
        date=date.today().isoformat(),
        score=round(float(latest["composite"]), 2),
        level=_display_level(_risk_level(float(latest["composite"]))),
        components=components,
        top_positive_drivers=sorted(all_indicators, key=lambda item: item.delta_30d, reverse=True)[:5],
        top_negative_drivers=sorted(all_indicators, key=lambda item: item.delta_30d)[:5],
    )


def build_replay(window_days: int = 120) -> ReplayResult:
    window_days = max(30, min(window_days, 420))
    frame, _sources = load_world_data(days=420)
    scored = _score_frame(frame)
    start_index = max(0, len(scored) - window_days)
    start = scored.iloc[start_index]
    end = scored.iloc[-1]
    history = _points_from_scored(scored.iloc[start_index:].reset_index(drop=True))
    components = [
        ReplayComponentChange(
            key=key,
            name=name,
            start=round(float(start[key]), 2),
            end=round(float(end[key]), 2),
            change=round(float(end[key]) - float(start[key]), 2),
        )
        for key, name in _component_display_names().items()
    ]
    assets = [
        _asset_move(frame, start_index, "sp500", "标普500"),
        _asset_move(frame, start_index, "nasdaq", "纳斯达克100"),
        _asset_move(frame, start_index, "gold", "黄金"),
        _asset_move(frame, start_index, "oil", "WTI原油"),
    ]
    change = float(end["composite"]) - float(start["composite"])
    top = max(components, key=lambda item: abs(item.change))
    direction = "上升" if change > 0 else "下降" if change < 0 else "基本持平"
    interpretation = (
        f"过去约{window_days}个交易日，综合风险{direction} {abs(change):.1f} 分。"
        f"变化最大的分项是{top.name}，变化 {top.change:+.1f} 分。"
        "该复盘用于观察结构变化，不构成投资建议。"
    )
    return ReplayResult(
        start_date=start.date.strftime("%Y-%m-%d"),
        end_date=end.date.strftime("%Y-%m-%d"),
        start_score=round(float(start["composite"]), 2),
        end_score=round(float(end["composite"]), 2),
        change=round(change, 2),
        interpretation=interpretation,
        components=components,
        assets=assets,
        history=history,
    )


def _latest_from_scored(frame: pd.DataFrame, scored: pd.DataFrame, sources: dict[str, str]) -> CompositeRisk:
    latest = scored.iloc[-1]
    previous = scored.iloc[-21] if len(scored) > 21 else scored.iloc[0]
    config = load_config()
    components = [
        _component("financial", "Financial Market Stress", "金融市场压力", latest, previous, config, sources, _financial_drivers(frame)),
        _component("climate", "Climate Stress", "气候压力", latest, previous, config, sources, _climate_drivers(frame)),
        _component("geopolitical", "Geopolitical Stress", "地缘与政策压力", latest, previous, config, sources, _geopolitical_drivers(frame)),
        _component("ecology", "Ecology & Food Stress", "生态与粮食压力", latest, previous, config, sources, _ecology_drivers(frame)),
        _component("macro", "Macro Liquidity Stress", "宏观流动性压力", latest, previous, config, sources, _macro_drivers(frame)),
    ]
    forecast = _forecast_30d_probability(scored["composite"])
    score = float(latest["composite"])
    trend = _trend_label(score - float(previous["composite"]))
    return CompositeRisk(
        date=date.today().isoformat(),
        score=round(score, 2),
        level=_risk_level(score),
        display_level=_display_level(_risk_level(score)),
        trend=trend,
        display_trend=_display_trend(trend),
        forecast_30d=round(forecast, 3),
        forecast_label=_forecast_label(forecast),
        display_forecast_label=_display_forecast_label(_forecast_label(forecast)),
        components=components,
        summary=_summary(score, trend, forecast, components),
    )


def _score_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["financial"] = _financial_risk(out)
    out["climate"] = _mean_0_100(out, ["temp_anomaly", "ocean_heat", "co2_pressure", "enso_stress"])
    out["geopolitical"] = _mean_0_100(out, ["conflict_intensity", "policy_uncertainty"])
    out["ecology"] = _mean_0_100(out, ["drought_stress", "food_pressure", "fertilizer_pressure"])
    out["macro"] = _macro_risk(out)
    config = load_config()
    out["composite"] = (
        out["financial"] * config["financial"]["weight"]
        + out["climate"] * config["climate"]["weight"]
        + out["geopolitical"] * config["geopolitical"]["weight"]
        + out["ecology"] * config["ecology"]["weight"]
        + out["macro"] * config["macro"]["weight"]
    )
    return out


def _financial_risk(frame: pd.DataFrame) -> pd.Series:
    sp_ret = frame["sp500"].pct_change()
    ndx_ret = frame["nasdaq"].pct_change()
    oil_ret = frame["oil"].pct_change()
    gold_ret = frame["gold"].pct_change()
    vol_20 = ((sp_ret.rolling(20).std() + ndx_ret.rolling(20).std()) / 2 * np.sqrt(252)).fillna(0)
    drawdown = frame["sp500"] / frame["sp500"].cummax() - 1
    vix_score = _rolling_percentile(frame["vix"], 252)
    oil_shock = oil_ret.abs().rolling(10).mean().fillna(0)
    haven_bid = (gold_ret.rolling(20).mean() - sp_ret.rolling(20).mean()).fillna(0)
    score = (
        _scale_clip(vol_20, 0.08, 0.45) * 28
        + _scale_clip(-drawdown, 0, 0.30) * 28
        + vix_score * 26
        + _scale_clip(oil_shock, 0.005, 0.04) * 10
        + _scale_clip(haven_bid, -0.002, 0.006) * 8
    )
    return score.clip(0, 100)


def _asset_move(frame: pd.DataFrame, start_index: int, key: str, name: str) -> ReplayAssetMove:
    start = float(frame[key].iloc[start_index])
    end = float(frame[key].iloc[-1])
    return ReplayAssetMove(
        key=key,
        name=name,
        start=round(start, 2),
        end=round(end, 2),
        return_pct=round((end / start - 1) * 100, 2) if start else 0,
    )


def _indicator_score_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"date": frame["date"]})
    sp_ret = frame["sp500"].pct_change()
    ndx_ret = frame["nasdaq"].pct_change()
    oil_ret = frame["oil"].pct_change()
    gold_ret = frame["gold"].pct_change()
    vol_20 = ((sp_ret.rolling(20).std() + ndx_ret.rolling(20).std()) / 2 * np.sqrt(252)).fillna(0)
    drawdown = frame["sp500"] / frame["sp500"].cummax() - 1
    haven_bid = (gold_ret.rolling(20).mean() - sp_ret.rolling(20).mean()).fillna(0)
    out["market_volatility"] = _scale_clip(vol_20, 0.08, 0.45) * 100
    out["equity_drawdown"] = _scale_clip(-drawdown, 0, 0.30) * 100
    out["vix_percentile"] = _rolling_percentile(frame["vix"], 252) * 100
    out["oil_shock"] = _scale_clip(oil_ret.abs().rolling(10).mean().fillna(0), 0.005, 0.04) * 100
    out["haven_bid"] = _scale_clip(haven_bid, -0.002, 0.006) * 100
    for column in [
        "temp_anomaly",
        "ocean_heat",
        "co2_pressure",
        "enso_stress",
        "conflict_intensity",
        "policy_uncertainty",
        "drought_stress",
        "food_pressure",
        "fertilizer_pressure",
        "credit_spread",
        "yield_curve",
        "dollar_stress",
        "gas_pressure",
    ]:
        out[column] = frame[column].clip(0, 1) * 100
    return out


def _indicator_analysis_for_component(
    component_key: str,
    latest: pd.Series,
    previous: pd.Series,
    sources: dict[str, str],
) -> list[IndicatorAnalysis]:
    indicators = []
    for key, name, source_key, explanation in _indicator_catalog()[component_key]:
        score = float(latest[key])
        prev = float(previous[key])
        indicators.append(
            IndicatorAnalysis(
                key=key,
                name=name,
                score=round(score, 2),
                previous_score=round(prev, 2),
                delta_30d=round(score - prev, 2),
                source=sources.get(source_key, "derived"),
                explanation=explanation,
            )
        )
    return indicators


def _component_display_names() -> dict[str, str]:
    return {
        "financial": "金融市场压力",
        "climate": "气候压力",
        "geopolitical": "地缘与政策压力",
        "ecology": "生态与粮食压力",
        "macro": "宏观流动性压力",
    }


def _indicator_catalog() -> dict[str, list[tuple[str, str, str, str]]]:
    return {
        "financial": [
            ("market_volatility", "股票市场波动", "sp500", "标普与纳指20日年化波动率越高，市场脆弱性越强。"),
            ("equity_drawdown", "股票回撤压力", "sp500", "标普500相对阶段高点回撤越深，风险偏好越弱。"),
            ("vix_percentile", "VIX分位压力", "vix", "VIX处在自身历史高分位时，说明市场避险需求上升。"),
            ("oil_shock", "原油冲击", "oil", "原油短期剧烈波动会同时影响通胀、利润和地缘预期。"),
            ("haven_bid", "黄金相对避险", "gold", "黄金相对股票走强时，常反映资金偏防御。"),
        ],
        "climate": [
            ("temp_anomaly", "全球温度异常", "temp_anomaly", "温度异常越高，气候系统偏离长期均值越明显。"),
            ("ocean_heat", "海洋热压力", "ocean_heat", "海洋热代理反映热量积累和长期气候压力。"),
            ("co2_pressure", "大气CO2压力", "co2_pressure", "CO2水平和增速构成长期气候风险背景。"),
            ("enso_stress", "ENSO异常压力", "enso_stress", "厄尔尼诺/拉尼娜异常会影响粮食、灾害和区域气候。"),
        ],
        "geopolitical": [
            ("conflict_intensity", "冲突事件强度", "conflict_intensity", "冲突事件和伤亡强度越高，区域外溢风险越强。"),
            ("policy_uncertainty", "政策不确定性", "policy_uncertainty", "全球政策不确定性越高，投资和贸易决策越难稳定。"),
        ],
        "ecology": [
            ("drought_stress", "农业/干旱压力", "drought_stress", "农业商品压力可作为干旱和供给扰动的代理信号。"),
            ("food_pressure", "粮食价格压力", "food_pressure", "粮食价格上行会影响民生、通胀和社会稳定。"),
            ("fertilizer_pressure", "化肥价格压力", "fertilizer_pressure", "化肥价格影响下一季粮食生产成本和供给弹性。"),
        ],
        "macro": [
            ("credit_spread", "高收益信用利差", "credit_spread", "信用利差扩大说明融资环境收紧、违约预期上升。"),
            ("yield_curve", "收益率曲线倒挂", "yield_curve", "收益率曲线倒挂通常反映增长预期走弱。"),
            ("dollar_stress", "美元压力", "dollar_stress", "美元走强会抬升全球美元融资和新兴市场压力。"),
            ("gas_pressure", "天然气价格压力", "gas_pressure", "天然气价格冲击会影响能源成本和欧洲/工业链压力。"),
        ],
    }


def _mean_0_100(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    return frame[columns].mean(axis=1).clip(0, 1) * 100


def _macro_risk(frame: pd.DataFrame) -> pd.Series:
    columns = ["credit_spread", "yield_curve", "dollar_stress", "gas_pressure"]
    weights = pd.Series({"credit_spread": 0.35, "yield_curve": 0.25, "dollar_stress": 0.20, "gas_pressure": 0.20})
    return frame[columns].mul(weights).sum(axis=1).clip(0, 1) * 100


def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    def pct(values: np.ndarray) -> float:
        current = values[-1]
        return float((values <= current).mean())

    return series.rolling(window, min_periods=20).apply(pct, raw=True).fillna(0.5)


def _scale_clip(series: pd.Series, low: float, high: float) -> pd.Series:
    return ((series - low) / (high - low)).clip(0, 1).fillna(0)


def _component(
    key: str,
    name: str,
    display_name: str,
    latest: pd.Series,
    previous: pd.Series,
    config: dict,
    sources: dict[str, str],
    drivers: list[str],
) -> RiskComponent:
    score = float(latest[key])
    delta = score - float(previous[key])
    family_sources = sorted({value for source_key, value in sources.items() if _source_belongs(key, source_key)})
    return RiskComponent(
        key=key,
        name=name,
        display_name=display_name,
        score=round(score, 2),
        weight=float(config[key]["weight"]),
        trend=_trend_label(delta),
        display_trend=_display_trend(_trend_label(delta)),
        source=", ".join(family_sources[:5]) if family_sources else "mixed",
        drivers=drivers,
    )


def _source_belongs(family: str, source_key: str) -> bool:
    groups = {
        "financial": {"sp500", "nasdaq", "gold", "oil", "vix"},
        "climate": {"temp_anomaly", "ocean_heat", "co2_pressure", "enso_stress"},
        "geopolitical": {"conflict_intensity", "policy_uncertainty"},
        "ecology": {"drought_stress", "food_pressure", "fertilizer_pressure"},
        "macro": {"credit_spread", "yield_curve", "dollar_stress", "gas_pressure"},
    }
    return source_key in groups[family]


def _trend_label(delta: float) -> str:
    if delta >= 4:
        return "rising"
    if delta <= -4:
        return "falling"
    return "stable"


def _risk_level(score: float) -> str:
    if score >= 75:
        return "extreme"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _display_level(level: str) -> str:
    return {
        "low": "低风险",
        "medium": "中等风险",
        "high": "高风险",
        "extreme": "极高风险",
    }[level]


def _display_trend(trend: str) -> str:
    return {
        "rising": "上升",
        "falling": "下降",
        "stable": "稳定",
    }[trend]


def _forecast_30d_probability(composite: pd.Series) -> float:
    momentum = composite.iloc[-1] - composite.iloc[-21] if len(composite) > 21 else 0
    volatility = composite.diff().rolling(30).std().iloc[-1]
    volatility = 0 if np.isnan(volatility) else volatility
    z = -0.7 + 0.13 * momentum + 0.08 * volatility + 0.025 * (composite.iloc[-1] - 50)
    return float(1 / (1 + np.exp(-z)))


def _forecast_label(probability: float) -> str:
    if probability >= 0.70:
        return "risk likely to rise"
    if probability <= 0.35:
        return "risk likely to cool"
    return "uncertain"


def _display_forecast_label(label: str) -> str:
    return {
        "risk likely to rise": "未来30天风险可能继续上升",
        "risk likely to cool": "未来30天风险可能降温",
        "uncertain": "未来30天方向不明确",
    }[label]


def _summary(score: float, trend: str, forecast: float, components: list[RiskComponent]) -> str:
    top = max(components, key=lambda item: item.score)
    return (
        f"当前综合风险为 {score:.1f}/100，等级为{_display_level(_risk_level(score))}，趋势{_display_trend(trend)}。"
        f"分项中压力最高的是{top.display_name}，得分 {top.score:.1f}。"
        f"基线模型估计未来30天风险继续上升的概率约为 {forecast:.0%}。"
    )


def _financial_drivers(frame: pd.DataFrame) -> list[str]:
    sp_dd = frame["sp500"].iloc[-1] / frame["sp500"].cummax().iloc[-1] - 1
    vix = frame["vix"].iloc[-1]
    gold_rel = frame["gold"].pct_change().tail(20).mean() - frame["sp500"].pct_change().tail(20).mean()
    return [
        f"标普500相对阶段高点回撤：{sp_dd:.1%}",
        f"VIX波动率水平：{vix:.2f}",
        f"近20日黄金相对股票收益差：{gold_rel:.2%}",
    ]


def _climate_drivers(frame: pd.DataFrame) -> list[str]:
    return [
        f"全球温度异常压力：{frame['temp_anomaly'].iloc[-1] * 100:.1f}/100",
        f"海洋热压力代理：{frame['ocean_heat'].iloc[-1] * 100:.1f}/100",
        f"大气CO2压力：{frame['co2_pressure'].iloc[-1] * 100:.1f}/100",
        f"ENSO异常压力：{frame['enso_stress'].iloc[-1] * 100:.1f}/100",
    ]


def _geopolitical_drivers(frame: pd.DataFrame) -> list[str]:
    return [
        f"冲突事件强度：{frame['conflict_intensity'].iloc[-1] * 100:.1f}/100",
        f"全球政策/不确定性指数压力：{frame['policy_uncertainty'].iloc[-1] * 100:.1f}/100",
    ]


def _ecology_drivers(frame: pd.DataFrame) -> list[str]:
    return [
        f"农业/干旱压力代理：{frame['drought_stress'].iloc[-1] * 100:.1f}/100",
        f"粮食价格压力：{frame['food_pressure'].iloc[-1] * 100:.1f}/100",
        f"化肥价格压力：{frame['fertilizer_pressure'].iloc[-1] * 100:.1f}/100",
    ]


def _macro_drivers(frame: pd.DataFrame) -> list[str]:
    return [
        f"美国高收益信用利差压力：{frame['credit_spread'].iloc[-1] * 100:.1f}/100",
        f"美债收益率曲线倒挂压力：{frame['yield_curve'].iloc[-1] * 100:.1f}/100",
        f"贸易加权美元压力：{frame['dollar_stress'].iloc[-1] * 100:.1f}/100",
        f"天然气价格压力：{frame['gas_pressure'].iloc[-1] * 100:.1f}/100",
    ]
