from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.models import AIAnalysisRequest, AIAnalysisResult, PolicyShock, ReportExport, SimulationRequest
from app.services.ai_client import request_structured_analysis
from app.services.ai_client import ai_status
from app.services.event_digest import build_agent_event_digest, build_event_digest
from app.services.risk_engine import build_risk_overview
from app.services.simulation_data import agent_state_explanations, get_country_agent
from app.services.simulation_engine import run_simulation
from app.services.simulation_health import build_simulation_data_health


def analyze_current_risk(request: AIAnalysisRequest) -> AIAnalysisResult:
    context = _base_context(request)
    return request_structured_analysis(
        "请生成当前全球局势结构化研判报告，重点包含核心结论、风险评分解释、证据链、催化因素、风险警报、未来观察清单和可运行情景建议。",
        context,
    )


def analyze_simulation(request: AIAnalysisRequest) -> AIAnalysisResult:
    context = _base_context(request)
    context["simulation"] = _simulation_summary(
        request.simulation.model_dump()
        if request.simulation is not None
        else run_simulation(
            SimulationRequest(
                shocks=[
                    PolicyShock(
                        shock_type="energy",
                        target_codes=["EU", "JPN", "KOR", "IND"],
                        intensity=0.5,
                        duration_months=6,
                        propagation=0.35,
                    )
                ],
                runs=120,
                horizon_months=12,
                seed=17,
            )
        ).model_dump()
    )
    return request_structured_analysis(
        "请解释这个模拟情景的连锁反应，区分数据证据、模型假设、风险警报和后续观察信号。",
        context,
    )


def export_ai_report(request: AIAnalysisRequest) -> ReportExport:
    result = analyze_simulation(request) if request.simulation is not None else analyze_current_risk(request)
    markdown = render_ai_markdown(result)
    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"ai_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return ReportExport(path=str(path), markdown=markdown)


def render_ai_markdown(result: AIAnalysisResult) -> str:
    status = ai_status()
    lines = [
        f"# {result.title}",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Provider：{status.get('provider')} / {status.get('model')}",
        f"- Fallback：{status.get('fallback_provider')} / {status.get('fallback_model')}",
        f"- 模式：{result.mode}",
        "",
        "## 摘要",
        "",
        result.summary,
        "",
        "## 核心结论",
        "",
    ]
    lines.extend(f"- {item}" for item in result.key_findings)
    lines.extend(["", "## 证据链", ""])
    for item in result.evidence:
        lines.append(f"- **{item.title}**（{item.source}，{item.value}）：{item.interpretation}")
    lines.extend(["", "## 关键不确定性", ""])
    lines.extend(f"- {item}" for item in result.uncertainties)
    lines.extend(["", "## 未来观察信号", ""])
    for item in result.watch_signals:
        lines.append(f"- **{item.name}**（{item.direction}）：{item.why_it_matters} 当前状态：{item.current_status}")
    lines.extend(["", "## 可运行情景建议", ""])
    for item in result.scenario_suggestions:
        lines.append(f"- **{item.name}**：`{item.shock_type}` -> {', '.join(item.target_codes)}。{item.rationale}")
    lines.extend(["", "## 免责声明", "", result.disclaimer, ""])
    return "\n".join(lines)


def _base_context(request: AIAnalysisRequest) -> dict:
    overview = build_risk_overview()
    events = build_agent_event_digest(request.agent_code, request.window_days) if request.agent_code else build_event_digest(request.window_days)
    context = {
        "focus": request.focus,
        "risk": {
            "latest": overview.latest.model_dump(),
            "history_tail": [point.model_dump() for point in overview.history[-7:]],
        },
        "events": {
            **events.model_dump(exclude={"topics"}),
            "topics": [topic.model_dump() for topic in events.topics[:5]],
        },
        "simulation_data_health": [item.model_dump() for item in build_simulation_data_health()[:5]],
    }
    if request.agent_code:
        agent = get_country_agent(request.agent_code)
        if agent is not None:
            context["agent"] = {
                "detail": agent.model_dump(),
                "state_explanations": agent_state_explanations(agent),
            }
    return context


def _simulation_summary(simulation: dict) -> dict:
    return {
        "summary": simulation.get("summary"),
        "horizon_months": simulation.get("horizon_months"),
        "runs": simulation.get("runs"),
        "global_path_tail": (simulation.get("global_path") or [])[-6:],
        "top_countries": (simulation.get("countries") or [])[:10],
        "drivers": simulation.get("drivers") or [],
        "propagation_edges": (simulation.get("propagation_edges") or [])[:12],
    }
