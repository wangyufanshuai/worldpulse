from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.models import CausalAnalysisRequest, CausalAnalysisResult, ReportExport
from app.services.ai_client import request_structured_analysis
from app.services.causal_backtest import run_causal_backtest
from app.services.causal_data import build_causal_events, select_event
from app.services.causal_graph import build_causal_chain, estimate_market_impacts


DISCLAIMER = "CausalWorldQuant 只做数据解释、历史类比和情景推演，不构成投资、政治或安全决策建议。"


def analyze_causal_world(request: CausalAnalysisRequest) -> CausalAnalysisResult:
    events = build_causal_events(window_days=request.window_days, region=request.region)
    event = select_event(events, request.event_type)
    backtest = run_causal_backtest(event_type=event.event_type, window_days=max(120, request.window_days * 4), horizon_days=request.horizon_days)
    chain = build_causal_chain(event)
    impacts = estimate_market_impacts(event, backtest_confidence=backtest.hit_rate * 100)
    reasoning_path = _reasoning_path(event, chain, impacts)
    ai_text = _local_ai_text(event, chain, backtest)
    if request.use_ai:
        ai_text = _try_ai_explanation(event, chain, backtest, impacts) or ai_text
    return CausalAnalysisResult(
        title="CausalWorldQuant 因果研判",
        summary=_summary(event, backtest, impacts),
        events=events,
        chains=[chain],
        impacts=impacts,
        similar_events=backtest.similar_events,
        backtest=backtest,
        uncertainty=_uncertainty(backtest),
        error_attribution=backtest.error_attribution,
        reasoning_path=reasoning_path,
        ai_explanation=ai_text,
        disclaimer=DISCLAIMER,
    )


def export_causal_report(request: CausalAnalysisRequest) -> ReportExport:
    result = analyze_causal_world(request)
    markdown = render_causal_markdown(result)
    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"causal_world_quant_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return ReportExport(path=str(path), markdown=markdown)


def render_causal_markdown(result: CausalAnalysisResult) -> str:
    lines = [
        f"# {result.title}",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 免责声明：{result.disclaimer}",
        "",
        "## 摘要",
        "",
        result.summary,
        "",
        "## 因果链",
        "",
    ]
    for chain in result.chains:
        lines.append(f"### {chain.title}，置信度 {chain.confidence:.1f}")
        lines.append(chain.explanation)
        for edge in chain.edges:
            lines.append(f"- {edge.source} -> {edge.target}：{edge.relation}，置信度 {edge.confidence:.1f}。{edge.explanation}")
    lines.extend(["", "## 市场影响", ""])
    for impact in result.impacts:
        lines.append(f"- {impact.asset_name}：{impact.direction}，期望变化 {impact.expected_return_pct:+.2f}%，置信度 {impact.confidence:.1f}。{impact.rationale}")
    lines.extend(["", "## 历史相似事件", ""])
    for item in result.similar_events:
        lines.append(f"- {item.date}：相似度 {item.similarity:.1f}，{item.market_move}。{item.notes}")
    lines.extend(["", "## 错误归因分析", ""])
    lines.extend(f"- {item}" for item in result.error_attribution)
    lines.extend(["", "## 推理路径", ""])
    lines.extend(f"- {item}" for item in result.reasoning_path)
    return "\n".join(lines) + "\n"


def _summary(event, backtest, impacts) -> str:
    top_impact = max(impacts, key=lambda item: abs(item.expected_return_pct)) if impacts else None
    top_text = f"最强市场代理影响是 {top_impact.asset_name} {top_impact.expected_return_pct:+.2f}%。" if top_impact else "暂无足够市场代理影响。"
    return (
        f"当前主导事件为{event.name}，事件强度 {event.intensity:.1f}/100，事件置信度 {event.confidence:.1f}/100。"
        f"历史回测样本 {backtest.sample_count} 个，方向一致性约 {backtest.hit_rate:.0%}。{top_text}"
    )


def _reasoning_path(event, chain, impacts) -> list[str]:
    steps = [f"识别事件：{event.name}，来源 {event.source}，近 {event.window_days} 天事件数 {event.event_count}。"]
    steps.extend([f"因果边：{edge.source} -> {edge.target}，机制为{edge.relation}。" for edge in chain.edges[:4]])
    steps.extend([f"市场代理：{impact.asset_name} 方向 {impact.direction}，置信度 {impact.confidence:.1f}。" for impact in impacts[:4]])
    steps.append("最终输出保留置信度、相似事件和错误归因，不把路径当成确定性预测。")
    return steps


def _uncertainty(backtest) -> list[str]:
    items = [
        "新闻热度不等于真实事件严重程度，需要和价格、宏观数据交叉验证。",
        "因果方向可能被市场提前定价或多事件重叠扭曲。",
        "当前版本使用代理资产，不直接等同于具体个股或 ETF 的真实收益。",
    ]
    if backtest.sample_count < 8:
        items.insert(0, "历史样本偏少，分位和胜率稳定性不足。")
    return items


def _local_ai_text(event, chain, backtest) -> str:
    return (
        f"本地解释：{event.name}的主要路径是“{chain.edges[0].source} -> {chain.edges[0].target}”，"
        f"链条置信度 {chain.confidence:.1f}/100。历史相似窗口显示方向一致性约 {backtest.hit_rate:.0%}，"
        "因此应把结论视为可检验假设，而不是确定预测。"
    )


def _try_ai_explanation(event, chain, backtest, impacts) -> str | None:
    context = {
        "event": event.model_dump(),
        "chain": chain.model_dump(),
        "backtest": backtest.model_dump(),
        "impacts": [item.model_dump() for item in impacts],
    }
    result = request_structured_analysis(
        "请用中文解释这条世界事件到市场影响的因果链，必须强调证据、置信度、历史相似事件和错误归因边界。",
        {"causal_world_quant": context},
    )
    if result.mode == "disabled":
        return None
    return result.summary
