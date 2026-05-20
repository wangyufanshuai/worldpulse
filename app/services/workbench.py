from __future__ import annotations

from pathlib import Path
from time import time

from app.core.models import AlertItem, DataSourceHealth, IndicatorLibraryItem, ReportTemplate, WorkbenchStatus
from app.services.risk_engine import build_latest_risk, build_risk_analysis


def build_workbench_status() -> WorkbenchStatus:
    analysis = build_risk_analysis()
    latest = build_latest_risk()
    return WorkbenchStatus(
        indicators=_indicator_library(analysis),
        alerts=_alerts_from_analysis(analysis),
        data_sources=_data_source_health(latest),
    )


def report_templates() -> list[ReportTemplate]:
    return [
        ReportTemplate(
            key="daily",
            title="今日综合风险简报",
            description="综合风险、分项风险、当前驱动因素和方法说明。",
            endpoint="/api/report.md",
        ),
        ReportTemplate(
            key="analysis",
            title="详细归因报告",
            description="分项贡献、指标级变化、上升/下降驱动排行。",
            endpoint="/api/report/analysis.md",
        ),
        ReportTemplate(
            key="system",
            title="系统健康报告",
            description="指标数量、当前预警、数据源缓存和兜底状态。",
            endpoint="/api/report/system.md",
        ),
    ]


def render_analysis_report() -> str:
    analysis = build_risk_analysis()
    lines = [
        "# WorldPulse 详细归因报告",
        "",
        f"- 日期：{analysis.date}",
        f"- 综合风险：{analysis.score:.2f}/100",
        f"- 风险等级：{analysis.level}",
        "",
        "## 分项贡献",
        "",
        "| 分项 | 得分 | 权重 | 贡献 | 30天变化 |",
        "|---|---:|---:|---:|---:|",
    ]
    for component in analysis.components:
        lines.append(f"| {component.name} | {component.score:.2f} | {component.weight:.2f} | {component.contribution:.2f} | {component.delta_30d:+.2f} |")
    lines.extend(["", "## 上升最快指标", ""])
    lines.extend(f"- {item.name}: {item.delta_30d:+.2f}，当前 {item.score:.2f}" for item in analysis.top_positive_drivers)
    lines.extend(["", "## 下降最快指标", ""])
    lines.extend(f"- {item.name}: {item.delta_30d:+.2f}，当前 {item.score:.2f}" for item in analysis.top_negative_drivers)
    lines.extend(["", "## 指标说明", ""])
    for component in analysis.components:
        lines.append(f"### {component.name}")
        for item in component.indicators:
            lines.append(f"- **{item.name}**：{item.explanation} 当前 {item.score:.2f}，30天变化 {item.delta_30d:+.2f}。数据源：{item.source}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_system_report() -> str:
    status = build_workbench_status()
    alerts = status.alerts
    lines = [
        "# WorldPulse 系统健康报告",
        "",
        f"- 指标数量：{len(status.indicators)}",
        f"- 当前预警：{len(alerts)}",
        f"- 数据源数量：{len(status.data_sources)}",
        "",
        "## 当前预警",
        "",
    ]
    if alerts:
        lines.extend(f"- [{item.level}] {item.title}: {item.message}" for item in alerts)
    else:
        lines.append("- 暂无触发预警。")
    lines.extend(["", "## 数据源健康", "", "| 数据源 | 状态 | 缓存年龄 | 说明 |", "|---|---|---:|---|"])
    for item in status.data_sources:
        age = "" if item.cache_age_hours is None else f"{item.cache_age_hours:.1f}小时"
        lines.append(f"| {item.source} | {item.status} | {age} | {item.note} |")
    return "\n".join(lines) + "\n"


def _indicator_library(analysis) -> list[IndicatorLibraryItem]:
    rows: list[IndicatorLibraryItem] = []
    for component in analysis.components:
        for item in component.indicators:
            rows.append(
                IndicatorLibraryItem(
                    key=item.key,
                    name=item.name,
                    component=component.name,
                    score=item.score,
                    delta_30d=item.delta_30d,
                    source=item.source,
                    frequency=_frequency_for_source(item.source),
                    formula=_formula_for_indicator(item.key),
                    status="真实数据" if item.source != "deterministic-demo" else "兜底演示",
                    explanation=item.explanation,
                )
            )
    return rows


def _alerts_from_analysis(analysis) -> list[AlertItem]:
    alerts: list[AlertItem] = []
    if analysis.score >= 75:
        alerts.append(AlertItem(level="严重", title="综合风险进入极高区间", message=f"综合风险 {analysis.score:.1f}/100，需要重点复盘所有分项。", metric="composite", score=analysis.score))
    elif analysis.score >= 60:
        alerts.append(AlertItem(level="高", title="综合风险进入高风险区间", message=f"综合风险 {analysis.score:.1f}/100，建议降低乐观假设。", metric="composite", score=analysis.score))

    for component in analysis.components:
        if component.score >= 70:
            alerts.append(AlertItem(level="高", title=f"{component.name}偏高", message=f"{component.name}当前 {component.score:.1f}/100，对总分贡献 {component.contribution:.1f}。", metric=component.key, score=component.score))
        if component.delta_30d >= 10:
            alerts.append(AlertItem(level="中", title=f"{component.name}快速上升", message=f"近30天上升 {component.delta_30d:.1f} 分。", metric=component.key, score=component.score))

    for item in analysis.top_positive_drivers:
        if item.delta_30d >= 10:
            alerts.append(AlertItem(level="中", title=f"{item.name}异动", message=f"近30天上升 {item.delta_30d:.1f} 分，当前 {item.score:.1f}。", metric=item.key, score=item.score))
    return alerts[:12]


def _data_source_health(latest) -> list[DataSourceHealth]:
    seen = []
    for component in latest.components:
        for source in [item.strip() for item in component.source.split(",") if item.strip()]:
            if source not in seen:
                seen.append(source)
    return [_health_for_source(source) for source in seen]


def _health_for_source(source: str) -> DataSourceHealth:
    if source == "deterministic-demo":
        return DataSourceHealth(source=source, status="兜底", note="公共数据源不可用时的可复现演示数据。")
    cache_file = _cache_match(source)
    if cache_file is None:
        return DataSourceHealth(source=source, status="在线", note="当前运行成功返回数据，未找到直接对应缓存文件。")
    age = round((time() - cache_file.stat().st_mtime) / 3600, 1)
    status = "缓存新鲜" if age <= 24 else "缓存偏旧"
    return DataSourceHealth(source=source, status=status, cache_file=str(cache_file), cache_age_hours=age, note="本地缓存存在，接口会优先复用缓存以降低限流风险。")


def _cache_match(source: str) -> Path | None:
    cache_dir = Path("data/cache")
    if source.startswith("FRED:"):
        series_id = source.split(":", 1)[1].split()[0]
        exact = cache_dir / f"fred_{series_id}.csv"
        return exact if exact.exists() else None
    mapping = {
        "NASA GISTEMP": "nasa_gistemp",
        "NOAA Mauna Loa CO2": "noaa_co2",
        "NOAA CPC Oceanic Nino Index": "noaa_oni",
        "World Bank Pink Sheet": "world_bank_pink_sheet",
        "UCDP GED": "ucdp_ged",
        "World Uncertainty Index": "world_uncertainty",
        "GDELT": "gdelt_",
    }
    for prefix, pattern in mapping.items():
        if source.startswith(prefix) or source == prefix:
            files = list(cache_dir.glob(f"{pattern}*"))
            return max(files, key=lambda path: path.stat().st_mtime) if files else None
    return None


def _frequency_for_source(source: str) -> str:
    if source.startswith("FRED"):
        return "日频/交易日"
    if source.startswith("NASA") or source.startswith("NOAA") or source.startswith("World Bank") or source.startswith("World Uncertainty"):
        return "月频"
    if source.startswith("UCDP"):
        return "月度聚合"
    return "混合"


def _formula_for_indicator(key: str) -> str:
    formulas = {
        "market_volatility": "20日年化波动率标准化",
        "equity_drawdown": "阶段高点回撤标准化",
        "vix_percentile": "252日滚动分位数",
        "oil_shock": "10日原油绝对涨跌均值标准化",
        "haven_bid": "黄金相对股票20日收益差标准化",
        "temp_anomaly": "NASA温度异常线性缩放",
        "ocean_heat": "温度平滑值与同比加速度混合",
        "co2_pressure": "CO2水平与12月增速混合",
        "enso_stress": "ONI绝对异常缩放",
        "conflict_intensity": "GDELT/UCDP冲突强度分位",
        "policy_uncertainty": "WUI指数分位与动量",
        "drought_stress": "农业商品指数分位与动量",
        "food_pressure": "食品指数分位与动量",
        "fertilizer_pressure": "化肥指数分位与动量",
        "credit_spread": "高收益利差线性缩放",
        "yield_curve": "10Y-2Y倒挂压力缩放",
        "dollar_stress": "美元指数分位与动量",
        "gas_pressure": "天然气价格分位与动量",
    }
    return formulas.get(key, "标准化风险分")
