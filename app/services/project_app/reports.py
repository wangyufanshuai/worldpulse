from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.core.models import (
    AIAnalysisRequest,
    AIAnalysisResult,
    CausalGraphSnapshot,
    EvidenceItem,
    ProjectAIReport,
    ReportCitation,
    ResearchProject,
    ResearchRun,
    ScenarioSuggestion,
    WarRoomRun,
    WatchSignal,
)
from app.services.ai_analysis import analyze_current_risk, render_ai_markdown
from app.services.war_room_engine import WAR_ROOM_DISCLAIMER


def build_project_report(project: ResearchProject, run: ResearchRun, graph: CausalGraphSnapshot, causal, analyze_fn=analyze_current_risk) -> ProjectAIReport:
    run_mode = str(run.data_snapshot.get("run_mode", "fast"))
    ai = fast_ai_report(project, run, graph) if run_mode == "fast" else analyze_fn(AIAnalysisRequest(focus=project.question, window_days=project.event_window_days))
    ai.title = f"{project.title} 研究报告"
    if run.summary not in ai.summary:
        ai.summary = f"{run.summary}\n\n{ai.summary}"
    leading_findings = [
        f"主导事件链：{causal.chains[0].title}，图谱置信度 {graph.confidence:.1f}/100。",
        f"研究问题：{project.question}",
    ]
    ai.key_findings = dedupe_texts([*leading_findings, *ai.key_findings])[:6]
    citations = build_report_citations(ai.key_findings, ai.evidence, graph, run.backtest_snapshot)
    markdown = render_project_markdown(ai, citations)
    return ProjectAIReport(
        report_id=f"report_{uuid4().hex[:12]}",
        project_id=project.project_id,
        run_id=run.run_id,
        generated_at=now(),
        mode=ai.mode,
        title=ai.title,
        summary=ai.summary,
        key_findings=ai.key_findings,
        evidence=ai.evidence,
        uncertainties=ai.uncertainties,
        watch_signals=ai.watch_signals,
        scenario_suggestions=ai.scenario_suggestions,
        citations=citations,
        markdown=markdown,
        disclaimer=ai.disclaimer,
    )


def build_war_room_project_report(project: ResearchProject, run: ResearchRun, graph: CausalGraphSnapshot, result: WarRoomRun) -> ProjectAIReport:
    top_agents = result.country_agents[:3]
    top_chains = result.supply_chains[:3]
    key_findings = [
        f"Scenario setting: {result.scenario.name}, {result.scenario.duration_days} days, intensity {result.scenario.intensity:.2f}.",
        f"User controls: target countries {', '.join(result.scenario.target_countries)}; target chains {', '.join(result.scenario.target_chains)}; policy actions {', '.join(result.scenario.policy_actions) if result.scenario.policy_actions else 'none'}.",
        f"Primary causal chain: {top_chains[0].name} pressure reaches {top_chains[0].pressure_score:.1f}/100 and propagates to {top_agents[0].name}.",
        f"Highest-risk country agent: {top_agents[0].name} at {top_agents[0].risk_score:.1f}/100.",
        f"Agent decision focus: {result.agent_decisions[0].country_name} should {result.agent_decisions[0].action.lower()} because of {', '.join(result.agent_decisions[0].drivers)}.",
        f"Risk heatmap: {len(result.risk_heatmap)} countries scored; dominant channel for the top cell is {result.risk_heatmap[0].dominant_channel} with breakdown {result.risk_heatmap[0].risk_breakdown}.",
        f"Boundary condition: {WAR_ROOM_DISCLAIMER}",
    ]
    evidence = [
        EvidenceItem(title="Scenario Sandbox", source="WorldPulse War Room", value=result.scenario.name, interpretation=result.scenario.description),
        EvidenceItem(title="Supply Chain Bottleneck", source="WorldPulse supply-chain rules", value=f"{top_chains[0].pressure_score:.1f}/100", interpretation=f"{top_chains[0].name} is the highest-pressure chain after substitution and lag effects."),
        EvidenceItem(title="Policy Actions", source="WorldPulse scenario builder", value=", ".join(result.scenario.policy_actions) or "none", interpretation="User-selected actions are deterministic inputs that shift supply-chain and agent pressure."),
        EvidenceItem(title="Agent Decisions", source="WorldPulse country-agent rules", value=str(len(result.agent_decisions)), interpretation="Country-agent decisions are deterministic rule outputs based on dependency, stress channels, drivers, and expected tradeoffs."),
        EvidenceItem(title="Model Assumptions", source="WorldPulse War Room", value=str(len(result.assumptions)), interpretation="Assumptions separate deterministic rules, user controls, and non-prediction boundaries."),
    ]
    citations = build_report_citations(key_findings, evidence, graph, run.backtest_snapshot)
    ai = AIAnalysisResult(
        enabled=False,
        mode="war-room-local",
        title=f"{project.title} War Room Report",
        summary=result.summary,
        key_findings=key_findings,
        evidence=evidence,
        uncertainties=[
            "The model is a strategy sandbox with local rules, not live intelligence or a predictive forecast.",
            "Agent decisions are rule-based and should be treated as inspectable assumptions.",
            "Supply-chain substitution, escalation, and public opinion are simplified for MVP use.",
            "User overrides can stress-test assumptions but do not represent verified real-world intelligence.",
        ],
        watch_signals=[
            WatchSignal(name="Energy pressure", direction="scenario", why_it_matters="Energy is a first-order inflation and stability channel.", current_status=f"{chain_pressure(result, 'energy'):.1f}/100"),
            WatchSignal(name="Critical chips", direction="scenario", why_it_matters="Chip disruption connects trade, industry, and alliance response.", current_status=f"{chain_pressure(result, 'chips'):.1f}/100"),
            WatchSignal(name="Public opinion", direction="scenario", why_it_matters="Opinion pressure affects stability and diplomatic room for maneuver.", current_status=f"{result.timeline[-1].public_opinion_pressure:.1f}/100"),
        ],
        scenario_suggestions=[
            ScenarioSuggestion(name="Lower intensity de-escalation", shock_type="war_room", target_codes=result.scenario.target_countries, rationale="Compare whether lower intensity changes bottleneck ranking."),
            ScenarioSuggestion(name="Higher propagation sanctions case", shock_type="war_room", target_codes=result.scenario.target_countries, rationale="Stress-test countermeasure and financial-settlement propagation."),
        ],
        disclaimer=WAR_ROOM_DISCLAIMER,
    )
    markdown = render_project_markdown(ai, citations)
    return ProjectAIReport(
        report_id=f"report_{uuid4().hex[:12]}",
        project_id=project.project_id,
        run_id=run.run_id,
        generated_at=now(),
        mode=ai.mode,
        title=ai.title,
        summary=ai.summary,
        key_findings=ai.key_findings,
        evidence=ai.evidence,
        uncertainties=ai.uncertainties,
        watch_signals=ai.watch_signals,
        scenario_suggestions=ai.scenario_suggestions,
        citations=citations,
        markdown=markdown,
        disclaimer=ai.disclaimer,
    )


def build_report_citations(
    findings: list[str],
    evidence: list[EvidenceItem],
    graph: CausalGraphSnapshot,
    backtest: dict,
) -> list[ReportCitation]:
    citations: list[ReportCitation] = []
    edges = graph.edges or []
    node_labels = {str(node.get("id")): str(node.get("label") or node.get("id")) for node in graph.nodes or []}
    for index, finding in enumerate(findings):
        evidence_item = evidence[index % len(evidence)] if evidence else None
        if evidence_item is not None:
            citations.append(
                ReportCitation(
                    citation_id=f"E{index + 1}",
                    finding_index=index,
                    kind="evidence",
                    target_id=f"evidence:{index % len(evidence)}",
                    title=evidence_item.title,
                    summary=evidence_item.interpretation,
                    source=evidence_item.source,
                    confidence=72.0,
                )
            )
        edge = best_edge_for_finding(finding, edges) if edges else None
        if edge is not None:
            citations.append(
                ReportCitation(
                    citation_id=f"G{index + 1}",
                    finding_index=index,
                    kind="causal_edge",
                    target_id=edge_target_id(edge),
                    title=f"{edge_label(edge.get('source'), node_labels)} -> {edge_label(edge.get('target'), node_labels)}",
                    summary=str(edge.get("explanation") or edge.get("relation") or "因果边引用"),
                    source="WorldPulse causal graph",
                    confidence=float(edge.get("confidence") or graph.confidence or 50.0),
                )
            )
        if backtest:
            sample_count = backtest.get("sample_count", 0)
            hit_rate = backtest.get("hit_rate", 0)
            max_error = backtest.get("max_error", 0)
            citations.append(
                ReportCitation(
                    citation_id=f"B{index + 1}",
                    finding_index=index,
                    kind="backtest",
                    target_id=f"backtest:{backtest.get('event_type', 'event')}",
                    title="历史窗口回测",
                    summary=f"样本数 {sample_count}，方向一致性 {float(hit_rate):.0%}，最大误差 {float(max_error):.2f}。",
                    source="WorldPulse historical backtest",
                    confidence=max(35.0, min(85.0, float(hit_rate or 0) * 100)),
                )
            )
    return citations


def render_project_markdown(ai: AIAnalysisResult, citations: list[ReportCitation]) -> str:
    base = render_ai_markdown(ai)
    if not citations:
        return base
    grouped: dict[int, list[ReportCitation]] = {}
    for citation in citations:
        grouped.setdefault(citation.finding_index, []).append(citation)
    lines = base.splitlines()
    rendered: list[str] = []
    in_findings = False
    finding_index = 0
    for line in lines:
        if line == "## 核心结论":
            in_findings = True
            rendered.append(line)
            continue
        if in_findings and line.startswith("## "):
            in_findings = False
        if in_findings and line.startswith("- "):
            suffix = " ".join(f"[^{item.citation_id}]" for item in grouped.get(finding_index, []))
            rendered.append(f"{line} {suffix}".rstrip())
            finding_index += 1
        else:
            rendered.append(line)
    rendered.extend(["", "## 引用脚注", ""])
    for citation in citations:
        rendered.append(f"[^{citation.citation_id}]: {citation.title}（{citation.kind}，{citation.source}，置信度 {citation.confidence:.0f}/100）：{citation.summary}")
    return "\n".join(rendered)


def fast_ai_report(project: ResearchProject, run: ResearchRun, graph: CausalGraphSnapshot) -> AIAnalysisResult:
    return AIAnalysisResult(
        enabled=False,
        mode="studio-fast",
        title=f"{project.title} 研究报告",
        summary=f"{run.summary} 快速模式优先保证工作台可交互，完整真实数据可通过设置 WORLDPULSE_STUDIO_FAST_MODE=false 启用。",
        key_findings=[
            f"研究问题：{project.question}",
            f"当前因果图谱置信度 {graph.confidence:.1f}/100，适合作为可检验假设。",
            "最需要验证的环节是事件热度到市场价格的时间滞后和方向一致性。",
        ],
        evidence=[
            EvidenceItem(title="图谱证据", source="WorldPulse causal graph", value=f"{len(graph.nodes)} nodes / {len(graph.edges)} edges", interpretation="图谱给出事件、宏观、资产和风险指数之间的可解释路径。"),
            EvidenceItem(title="回测证据", source="WorldPulse backtest proxy", value="样本与胜率已写入每条边", interpretation="边详情中包含历史样本数、方向一致性和最大反向误差。"),
        ],
        uncertainties=["快速模式使用代理快照，真实慢数据可能改变强度和排序。", "事件重叠、市场提前定价和代理资产不精确会带来错误归因。"],
        watch_signals=[
            WatchSignal(name="事件热度", direction="上升", why_it_matters="决定因果链起点强度。", current_status="需要继续观察"),
            WatchSignal(name="商品价格", direction="波动", why_it_matters="验证事件到宏观压力的传导。", current_status="需要和价格数据交叉验证"),
        ],
        scenario_suggestions=[
            ScenarioSuggestion(name="能源冲击复盘", shock_type="energy", target_codes=["EU", "JPN", "KOR", "IND"], rationale="检验进口能源脆弱经济体的承压路径。")
        ],
        disclaimer="AI 和快速工作台仅用于数据解释、假设生成和情景推演，不构成投资、政治或安全决策建议。",
    )


def best_edge_for_finding(finding: str, edges: list[dict]) -> dict | None:
    tokens = citation_tokens(finding)
    ranked = []
    for edge in edges:
        text = " ".join(
            str(edge.get(key, ""))
            for key in ["source", "target", "relation", "explanation"]
        ).lower()
        score = sum(1 for token in tokens if token in text) + float(edge.get("confidence") or 0) / 200
        ranked.append((score, edge))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] > 0 else edges[0] if edges else None


def citation_tokens(text: str) -> list[str]:
    lower = text.lower()
    hints = ["能源", "冲突", "原油", "黄金", "纳指", "风险", "利率", "通胀", "美元", "商品", "事件", "图谱", "回测"]
    ascii_words = [part for part in lower.replace("：", " ").replace("，", " ").replace("。", " ").split() if len(part) >= 2]
    return list(dict.fromkeys([*ascii_words, *[hint for hint in hints if hint in lower]]))


def edge_target_id(edge: dict) -> str:
    return f"edge:{edge.get('source')}->{edge.get('target')}:{edge.get('relation', '')}"


def edge_label(value, labels: dict[str, str] | None = None) -> str:
    key = str(value or "unknown")
    return (labels or {}).get(key, key)


def chain_pressure(result: WarRoomRun, key: str) -> float:
    return next((chain.pressure_score for chain in result.supply_chains if chain.key == key), 0.0)


def dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
