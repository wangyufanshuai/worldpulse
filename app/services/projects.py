from __future__ import annotations

from datetime import datetime
import os
from uuid import uuid4

from app.core.models import (
    AIAnalysisRequest,
    AIAnalysisResult,
    CausalAnalysisRequest,
    CausalBacktestResult,
    CausalEvent,
    CausalGraphEdge,
    CausalGraphNode,
    CausalChain,
    CausalGraphSnapshot,
    CompositeRisk,
    EvidenceItem,
    MarketImpact,
    PolicyShock,
    ProjectAIReport,
    ProjectChatMessage,
    ProjectChatRequest,
    ProjectDetail,
    GraphEditRequest,
    ReportCitation,
    ResearchProject,
    ResearchProjectCreate,
    ResearchRun,
    ResearchRunDiff,
    RiskComponent,
    RiskOverview,
    RiskPoint,
    ScenarioSuggestion,
    SimulationDriver,
    SimulationMapPoint,
    SimulationPathPoint,
    SimulationPropagationEdge,
    SimulationResult,
    SimulationRequest,
    WatchSignal,
)
from app.services.ai_analysis import analyze_current_risk, render_ai_markdown
from app.services.ai_client import request_structured_analysis
from app.services.causal_analysis import analyze_causal_world
from app.services.causal_backtest import run_causal_backtest
from app.services.causal_data import build_causal_events, select_event
from app.services.causal_graph import build_causal_chain
from app.services.project_store import connect, dumps, init_db, loads
from app.services.risk_engine import build_risk_overview
from app.services.simulation_engine import run_simulation


def create_project(payload: ResearchProjectCreate) -> ResearchProject:
    init_db()
    now = _now()
    project = ResearchProject(
        project_id=f"proj_{uuid4().hex[:12]}",
        title=payload.title.strip() or "未命名研究",
        question=payload.question.strip(),
        region=payload.region.strip() or "global",
        asset_scope=payload.asset_scope,
        event_window_days=max(7, min(payload.event_window_days, 90)),
        event_types=payload.event_types,
        status="created",
        created_at=now,
        updated_at=now,
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO research_projects
            (project_id, title, question, region, asset_scope, event_window_days, event_types, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.project_id,
                project.title,
                project.question,
                project.region,
                dumps(project.asset_scope),
                project.event_window_days,
                dumps(project.event_types),
                project.status,
                project.created_at,
                project.updated_at,
            ),
        )
    return project


def list_projects(limit: int = 50) -> list[ResearchProject]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM research_projects ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [_project_from_row(row) for row in rows]


def get_project_detail(project_id: str, run_id: str | None = None) -> ProjectDetail:
    project = _get_project(project_id)
    runs = _project_runs(project_id)
    selected_run = _run_by_id(project_id, run_id) if run_id else (runs[0] if runs else None)
    return ProjectDetail(
        project=project,
        latest_run=selected_run,
        runs=runs,
        graph=_graph_for_run(project_id, selected_run.run_id) if selected_run else None,
        report=_report_for_run(project_id, selected_run.run_id) if selected_run else None,
        chat_messages=_chat_messages(project_id),
    )


def run_project(project_id: str, mode: str = "fast") -> ProjectDetail:
    project = _get_project(project_id)
    started = _now()
    run_id = f"run_{uuid4().hex[:12]}"
    run_mode = _resolve_run_mode(mode)
    workflow_events: list[dict] = []
    _append_workflow_event(workflow_events, "project", "研究任务", "completed", "已读取研究问题、地区、资产范围和事件类型。")

    if run_mode == "fast":
        risk, events, causal, backtest, simulation = _fast_research_bundle(project)
        event = events[0]
        chain = causal.chains[0]
        _append_workflow_event(workflow_events, "data", "快速数据快照", "completed", "使用可解释代理快照，避免首次运行被外部数据源阻塞。")
    else:
        risk = build_risk_overview()
        _append_workflow_event(workflow_events, "data", "真实数据抓取", "completed", "已读取风险、宏观、市场与事件数据源。")
        events = build_causal_events(window_days=project.event_window_days, region=project.region)
        event = select_event(events, _preferred_event_type(project, events))
        _append_workflow_event(workflow_events, "events", "事件识别", "completed", f"识别主导事件：{event.name}，事件强度 {event.intensity:.1f}/100。")
        causal = analyze_causal_world(
            CausalAnalysisRequest(
                event_type=event.event_type,
                region=project.region,
                window_days=project.event_window_days,
                horizon_days=20,
                use_ai=False,
            )
        )
        chain = causal.chains[0]
        backtest = run_causal_backtest(event_type=event.event_type, window_days=max(120, project.event_window_days * 4), horizon_days=20)
        simulation = run_simulation(_simulation_request_for_event(event.event_type))
    if run_mode == "fast":
        _append_workflow_event(workflow_events, "events", "事件识别", "completed", f"快速模式锁定主导事件：{event.name}。")
    _append_workflow_event(workflow_events, "graph", "因果图谱", "completed", f"生成 {len(chain.nodes)} 个节点、{len(chain.edges)} 条因果边，图谱置信度 {chain.confidence:.1f}/100。")
    _append_workflow_event(workflow_events, "backtest", "历史验证", "completed", f"回测样本 {backtest.sample_count} 个，方向一致性 {backtest.hit_rate:.0%}。")
    _append_workflow_event(workflow_events, "simulation", "情景模拟", "completed", f"生成 {simulation.horizon_months} 个月路径，运行次数 {simulation.runs}。")
    data_snapshot = {
        "question": project.question,
        "region": project.region,
        "asset_scope": project.asset_scope,
        "event_types": project.event_types,
        "run_mode": run_mode,
        "workflow_events": workflow_events,
        "sources": sorted({event.source for event in events} | {"WorldPulse risk engine", "WorldPulse simulation", "Causal backtest"}),
    }
    summary = _run_summary(project.title, event.name, risk.latest.score, chain.confidence)
    completed = _now()
    run = ResearchRun(
        run_id=run_id,
        project_id=project.project_id,
        status="completed",
        started_at=started,
        completed_at=completed,
        summary=summary,
        data_snapshot=data_snapshot,
        risk_snapshot=risk.model_dump(),
        event_snapshot=[item.model_dump() for item in events],
        simulation_snapshot=_simulation_snapshot(simulation.model_dump()),
        backtest_snapshot=backtest.model_dump(),
    )
    graph = _graph_snapshot(project.project_id, run_id, chain, backtest)
    report = _project_report(project, run, graph, causal)
    _append_workflow_event(workflow_events, "report", "AI 报告", "completed", f"生成报告：{report.title}，模式 {report.mode}。")
    run.data_snapshot["workflow_events"] = workflow_events

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO research_runs
            (run_id, project_id, status, started_at, completed_at, summary, data_snapshot, risk_snapshot, event_snapshot, simulation_snapshot, backtest_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.project_id,
                run.status,
                run.started_at,
                run.completed_at,
                run.summary,
                dumps(run.data_snapshot),
                dumps(run.risk_snapshot),
                dumps(run.event_snapshot),
                dumps(run.simulation_snapshot),
                dumps(run.backtest_snapshot),
            ),
        )
        conn.execute(
            """
            INSERT INTO causal_graph_snapshots
            (graph_id, project_id, run_id, generated_at, nodes, edges, confidence, evidence_sources)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                graph.graph_id,
                graph.project_id,
                graph.run_id,
                graph.generated_at,
                dumps(graph.nodes),
                dumps(graph.edges),
                graph.confidence,
                dumps(graph.evidence_sources),
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_reports
            (report_id, project_id, run_id, generated_at, mode, title, summary, key_findings, evidence, uncertainties, watch_signals, scenario_suggestions, citations, markdown, disclaimer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.project_id,
                report.run_id,
                report.generated_at,
                report.mode,
                report.title,
                report.summary,
                dumps(report.key_findings),
                dumps([item.model_dump() for item in report.evidence]),
                dumps(report.uncertainties),
                dumps([item.model_dump() for item in report.watch_signals]),
                dumps([item.model_dump() for item in report.scenario_suggestions]),
                dumps([item.model_dump() for item in report.citations]),
                report.markdown,
                report.disclaimer,
            ),
        )
        conn.execute("UPDATE research_projects SET status = ?, updated_at = ? WHERE project_id = ?", ("completed", completed, project.project_id))
    return get_project_detail(project.project_id, run_id=run_id)


def latest_project_graph(project_id: str) -> CausalGraphSnapshot:
    graph = _latest_graph(project_id)
    if graph is None:
        run_project(project_id)
        graph = _latest_graph(project_id)
    assert graph is not None
    return graph


def latest_project_report(project_id: str) -> ProjectAIReport:
    report = _latest_report(project_id)
    if report is None:
        run_project(project_id)
        report = _latest_report(project_id)
    assert report is not None
    return report


def project_runs(project_id: str) -> list[ResearchRun]:
    _get_project(project_id)
    return _project_runs(project_id)


def project_run_detail(project_id: str, run_id: str) -> ProjectDetail:
    return get_project_detail(project_id, run_id=run_id)


def project_run_citations(project_id: str, run_id: str) -> list[ReportCitation]:
    report = _report_for_run(project_id, run_id)
    if report is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Report not found for run: {run_id}")
    return report.citations


def edit_project_graph(project_id: str, payload: GraphEditRequest) -> ProjectDetail:
    _get_project(project_id)
    run = _run_by_id(project_id, payload.run_id) if payload.run_id else _latest_run(project_id)
    if run is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Project has no research run to edit")
    graph = _graph_for_run(project_id, run.run_id)
    if graph is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Graph not found for run: {run.run_id}")

    nodes = payload.nodes if payload.nodes is not None else graph.nodes
    edges = payload.edges if payload.edges is not None else graph.edges
    confidence = graph.confidence if payload.confidence is None else max(0.0, min(float(payload.confidence), 100.0))
    evidence_sources = payload.evidence_sources if payload.evidence_sources is not None else graph.evidence_sources
    note = (payload.note or "").strip()
    if note and "Manual analyst edit" not in evidence_sources:
        evidence_sources = [*evidence_sources, "Manual analyst edit"]
    nodes, edges = _validate_graph_payload(nodes, edges)

    with connect() as conn:
        conn.execute(
            """
            UPDATE causal_graph_snapshots
            SET nodes = ?, edges = ?, confidence = ?, evidence_sources = ?, generated_at = ?
            WHERE project_id = ? AND run_id = ?
            """,
            (dumps(nodes), dumps(edges), confidence, dumps(evidence_sources), _now(), project_id, run.run_id),
        )
        run_data = run.data_snapshot
        workflow = list(run_data.get("workflow_events") or [])
        _append_workflow_event(workflow, "graph_edit", "人工图谱校正", "completed", note or "已保存图谱节点、边或置信度调整。")
        run_data["workflow_events"] = workflow
        run_data["last_graph_edit"] = {"timestamp": _now(), "note": note or "graph updated"}
        conn.execute("UPDATE research_runs SET data_snapshot = ? WHERE project_id = ? AND run_id = ?", (dumps(run_data), project_id, run.run_id))
    return get_project_detail(project_id, run_id=run.run_id)


def compare_project_runs(project_id: str, base_run_id: str, target_run_id: str) -> ResearchRunDiff:
    _get_project(project_id)
    base = _run_by_id(project_id, base_run_id)
    target = _run_by_id(project_id, target_run_id)
    assert base is not None and target is not None
    base_graph = _graph_for_run(project_id, base.run_id)
    target_graph = _graph_for_run(project_id, target.run_id)

    base_risk = _risk_score(base)
    target_risk = _risk_score(target)
    base_events = _event_names(base)
    target_events = _event_names(target)
    base_sources = set(base.data_snapshot.get("sources") or [])
    target_sources = set(target.data_snapshot.get("sources") or [])
    base_confidence = base_graph.confidence if base_graph else None
    target_confidence = target_graph.confidence if target_graph else None

    risk_delta = None if base_risk is None or target_risk is None else round(target_risk - base_risk, 2)
    confidence_delta = None if base_confidence is None or target_confidence is None else round(target_confidence - base_confidence, 2)
    summary_parts = []
    if risk_delta is not None:
        summary_parts.append(f"综合风险变化 {risk_delta:+.1f} 点")
    if confidence_delta is not None:
        summary_parts.append(f"图谱置信度变化 {confidence_delta:+.1f} 点")
    if not summary_parts:
        summary_parts.append("两次运行可对比的数据不足")
    return ResearchRunDiff(
        project_id=project_id,
        base_run_id=base.run_id,
        target_run_id=target.run_id,
        summary="；".join(summary_parts) + "。",
        risk_delta=risk_delta,
        confidence_delta=confidence_delta,
        event_count_delta=len(target.event_snapshot) - len(base.event_snapshot),
        evidence_source_delta=len(target_sources) - len(base_sources),
        added_events=sorted(target_events - base_events),
        removed_events=sorted(base_events - target_events),
        added_sources=sorted(target_sources - base_sources),
        removed_sources=sorted(base_sources - target_sources),
        changed_metrics={
            "base": {
                "risk_score": base_risk,
                "graph_confidence": base_confidence,
                "event_count": len(base.event_snapshot),
                "source_count": len(base_sources),
                "completed_at": base.completed_at,
            },
            "target": {
                "risk_score": target_risk,
                "graph_confidence": target_confidence,
                "event_count": len(target.event_snapshot),
                "source_count": len(target_sources),
                "completed_at": target.completed_at,
            },
        },
    )


def chat_with_project(project_id: str, payload: ProjectChatRequest) -> ProjectChatMessage:
    detail = get_project_detail(project_id)
    now = _now()
    user_message = ProjectChatMessage(
        message_id=f"msg_{uuid4().hex[:12]}",
        project_id=project_id,
        role="user",
        content=payload.message.strip(),
        created_at=now,
        mode="user",
    )
    context = {
        "project": detail.project.model_dump(),
        "latest_run": detail.latest_run.model_dump() if detail.latest_run else None,
        "graph": detail.graph.model_dump() if detail.graph else None,
        "report": detail.report.model_dump(exclude={"markdown"}) if detail.report else None,
        "question": payload.message,
    }
    result = request_structured_analysis(
        "请围绕当前研究项目回答用户追问。回答必须基于证据、反例、情景或结论边界，不做确定性投资建议。",
        {"research_project_chat": context},
    )
    answer = ProjectChatMessage(
        message_id=f"msg_{uuid4().hex[:12]}",
        project_id=project_id,
        role="assistant",
        content=f"{result.summary}\n\n" + "\n".join(f"- {item}" for item in result.key_findings[:4]),
        created_at=_now(),
        mode=result.mode,
    )
    with connect() as conn:
        for message in [user_message, answer]:
            conn.execute(
                "INSERT INTO chat_messages (message_id, project_id, role, content, created_at, mode) VALUES (?, ?, ?, ?, ?, ?)",
                (message.message_id, message.project_id, message.role, message.content, message.created_at, message.mode),
            )
    return answer


def _get_project(project_id: str) -> ResearchProject:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")
    return _project_from_row(row)


def _latest_run(project_id: str) -> ResearchRun | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM research_runs WHERE project_id = ? ORDER BY started_at DESC, run_id DESC LIMIT 1", (project_id,)).fetchone()
    return _run_from_row(row) if row else None


def _project_runs(project_id: str, limit: int = 20) -> list[ResearchRun]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM research_runs WHERE project_id = ? ORDER BY started_at DESC, run_id DESC LIMIT ?",
            (project_id, max(1, min(limit, 50))),
        ).fetchall()
    return [_run_from_row(row) for row in rows]


def _run_by_id(project_id: str, run_id: str | None) -> ResearchRun | None:
    if not run_id:
        return None
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM research_runs WHERE project_id = ? AND run_id = ?", (project_id, run_id)).fetchone()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Unknown run for project: {run_id}")
    return _run_from_row(row)


def _latest_graph(project_id: str) -> CausalGraphSnapshot | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM causal_graph_snapshots WHERE project_id = ? ORDER BY generated_at DESC LIMIT 1", (project_id,)).fetchone()
    if not row:
        return None
    return CausalGraphSnapshot(
        graph_id=row["graph_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        generated_at=row["generated_at"],
        nodes=loads(row["nodes"], []),
        edges=loads(row["edges"], []),
        confidence=float(row["confidence"]),
        evidence_sources=loads(row["evidence_sources"], []),
    )


def _graph_for_run(project_id: str, run_id: str) -> CausalGraphSnapshot | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM causal_graph_snapshots WHERE project_id = ? AND run_id = ? ORDER BY generated_at DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
    if not row:
        return None
    return CausalGraphSnapshot(
        graph_id=row["graph_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        generated_at=row["generated_at"],
        nodes=loads(row["nodes"], []),
        edges=loads(row["edges"], []),
        confidence=float(row["confidence"]),
        evidence_sources=loads(row["evidence_sources"], []),
    )


def _latest_report(project_id: str) -> ProjectAIReport | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM ai_reports WHERE project_id = ? ORDER BY generated_at DESC LIMIT 1", (project_id,)).fetchone()
    if not row:
        return None
    return ProjectAIReport(
        report_id=row["report_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        generated_at=row["generated_at"],
        mode=row["mode"],
        title=row["title"],
        summary=row["summary"],
        key_findings=loads(row["key_findings"], []),
        evidence=loads(row["evidence"], []),
        uncertainties=loads(row["uncertainties"], []),
        watch_signals=loads(row["watch_signals"], []),
        scenario_suggestions=loads(row["scenario_suggestions"], []),
        citations=loads(row["citations"] if "citations" in row.keys() else None, []),
        markdown=row["markdown"],
        disclaimer=row["disclaimer"],
    )


def _report_for_run(project_id: str, run_id: str) -> ProjectAIReport | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM ai_reports WHERE project_id = ? AND run_id = ? ORDER BY generated_at DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
    if not row:
        return None
    return ProjectAIReport(
        report_id=row["report_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        generated_at=row["generated_at"],
        mode=row["mode"],
        title=row["title"],
        summary=row["summary"],
        key_findings=loads(row["key_findings"], []),
        evidence=loads(row["evidence"], []),
        uncertainties=loads(row["uncertainties"], []),
        watch_signals=loads(row["watch_signals"], []),
        scenario_suggestions=loads(row["scenario_suggestions"], []),
        citations=loads(row["citations"] if "citations" in row.keys() else None, []),
        markdown=row["markdown"],
        disclaimer=row["disclaimer"],
    )


def _chat_messages(project_id: str) -> list[ProjectChatMessage]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM chat_messages WHERE project_id = ? ORDER BY created_at ASC LIMIT 80", (project_id,)).fetchall()
    return [
        ProjectChatMessage(
            message_id=row["message_id"],
            project_id=row["project_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            mode=row["mode"],
        )
        for row in rows
    ]


def _project_from_row(row) -> ResearchProject:
    return ResearchProject(
        project_id=row["project_id"],
        title=row["title"],
        question=row["question"],
        region=row["region"],
        asset_scope=loads(row["asset_scope"], []),
        event_window_days=int(row["event_window_days"]),
        event_types=loads(row["event_types"], []),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_from_row(row) -> ResearchRun:
    return ResearchRun(
        run_id=row["run_id"],
        project_id=row["project_id"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        summary=row["summary"],
        data_snapshot=loads(row["data_snapshot"], {}),
        risk_snapshot=loads(row["risk_snapshot"], {}),
        event_snapshot=loads(row["event_snapshot"], []),
        simulation_snapshot=loads(row["simulation_snapshot"], {}),
        backtest_snapshot=loads(row["backtest_snapshot"], {}),
    )


def _validate_graph_payload(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    from fastapi import HTTPException

    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise HTTPException(status_code=422, detail="Graph nodes and edges must be arrays")
    normalized_nodes: list[dict] = []
    node_ids: set[str] = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="Each graph node must be an object")
        node_id = str(raw.get("id") or "").strip()
        label = str(raw.get("label") or node_id).strip()
        if not node_id or not label:
            raise HTTPException(status_code=422, detail="Each graph node requires id and label")
        if node_id in node_ids:
            raise HTTPException(status_code=422, detail=f"Duplicate graph node id: {node_id}")
        node_ids.add(node_id)
        normalized_nodes.append(
            {
                **raw,
                "id": node_id,
                "label": label[:80],
                "kind": str(raw.get("kind") or "custom")[:32],
                "score": max(0.0, min(float(raw.get("score", 50)), 100.0)),
            }
        )
    normalized_edges: list[dict] = []
    for raw in edges:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="Each graph edge must be an object")
        source = str(raw.get("source") or "").strip()
        target = str(raw.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            raise HTTPException(status_code=422, detail=f"Graph edge references unknown node: {source}->{target}")
        normalized_edges.append(
            {
                **raw,
                "source": source,
                "target": target,
                "relation": str(raw.get("relation") or "analyst link")[:80],
                "weight": max(0.0, min(float(raw.get("weight", 0.5)), 1.0)),
                "confidence": max(0.0, min(float(raw.get("confidence", 50)), 100.0)),
                "explanation": str(raw.get("explanation") or "人工校正的因果关系。")[:280],
            }
        )
    return normalized_nodes, normalized_edges


def _risk_score(run: ResearchRun) -> float | None:
    score = (run.risk_snapshot.get("latest") or {}).get("score")
    return float(score) if isinstance(score, int | float) else None


def _event_names(run: ResearchRun) -> set[str]:
    names: set[str] = set()
    for event in run.event_snapshot:
        if isinstance(event, dict):
            names.add(str(event.get("name") or event.get("event_type") or "unknown"))
    return names


def _preferred_event_type(project: ResearchProject, events) -> str | None:
    available = {event.event_type for event in events}
    for event_type in project.event_types:
        if event_type in available:
            return event_type
    return project.event_types[0] if project.event_types else None


def _simulation_request_for_event(event_type: str) -> SimulationRequest:
    mapping = {
        "energy": PolicyShock(shock_type="energy", target_codes=["EU", "JPN", "KOR", "IND"], intensity=0.52),
        "trade": PolicyShock(shock_type="tariff", target_codes=["USA", "CHN", "EU", "VNM"], intensity=0.46),
        "sanctions": PolicyShock(shock_type="sanction", target_codes=["RUS", "CHN", "EU"], intensity=0.48),
        "rates": PolicyShock(shock_type="rate_hike", target_codes=["USA", "EU", "JPN", "BRA"], intensity=0.42),
    }
    return SimulationRequest(shocks=[mapping.get(event_type, PolicyShock(shock_type="energy", target_codes=["EU", "JPN", "KOR", "IND"]))], runs=180, horizon_months=12, seed=31)


def _simulation_snapshot(simulation: dict) -> dict:
    return {
        "summary": simulation.get("summary"),
        "horizon_months": simulation.get("horizon_months"),
        "runs": simulation.get("runs"),
        "global_path": simulation.get("global_path", [])[-12:],
        "top_countries": (simulation.get("countries") or [])[:8],
        "drivers": simulation.get("drivers") or [],
        "propagation_edges": (simulation.get("propagation_edges") or [])[:10],
    }


def _graph_snapshot(project_id: str, run_id: str, chain, backtest) -> CausalGraphSnapshot:
    nodes = [node.model_dump() for node in chain.nodes]
    edges = []
    for edge in chain.edges:
        edges.append(
            {
                **edge.model_dump(),
                "evidence": [
                    f"历史样本数：{backtest.sample_count}",
                    f"方向一致性：{backtest.hit_rate:.0%}",
                    f"最大反向误差：{backtest.max_error:.2f}",
                ],
                "backtest": {
                    "sample_count": backtest.sample_count,
                    "hit_rate": backtest.hit_rate,
                    "max_error": backtest.max_error,
                },
            }
        )
    return CausalGraphSnapshot(
        graph_id=f"graph_{uuid4().hex[:12]}",
        project_id=project_id,
        run_id=run_id,
        generated_at=_now(),
        nodes=nodes,
        edges=edges,
        confidence=chain.confidence,
        evidence_sources=["GDELT/UCDP event digest", "WorldPulse causal rules", "WorldPulse historical backtest"],
    )


def _project_report(project: ResearchProject, run: ResearchRun, graph: CausalGraphSnapshot, causal) -> ProjectAIReport:
    run_mode = str(run.data_snapshot.get("run_mode", "fast"))
    ai = _fast_ai_report(project, run, graph) if run_mode == "fast" else analyze_current_risk(AIAnalysisRequest(focus=project.question, window_days=project.event_window_days))
    ai.title = f"{project.title} 研究报告"
    if run.summary not in ai.summary:
        ai.summary = f"{run.summary}\n\n{ai.summary}"
    leading_findings = [
        f"主导事件链：{causal.chains[0].title}，图谱置信度 {graph.confidence:.1f}/100。",
        f"研究问题：{project.question}",
    ]
    ai.key_findings = _dedupe_texts([*leading_findings, *ai.key_findings])[:6]
    citations = _build_report_citations(ai.key_findings, ai.evidence, graph, run.backtest_snapshot)
    markdown = _render_project_markdown(ai, citations)
    return ProjectAIReport(
        report_id=f"report_{uuid4().hex[:12]}",
        project_id=project.project_id,
        run_id=run.run_id,
        generated_at=_now(),
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


def _build_report_citations(
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
        edge = _best_edge_for_finding(finding, edges) if edges else None
        if edge is not None:
            edge_id = _edge_target_id(edge)
            citations.append(
                ReportCitation(
                    citation_id=f"G{index + 1}",
                    finding_index=index,
                    kind="causal_edge",
                    target_id=edge_id,
                    title=f"{_edge_label(edge.get('source'), node_labels)} -> {_edge_label(edge.get('target'), node_labels)}",
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


def _best_edge_for_finding(finding: str, edges: list[dict]) -> dict | None:
    tokens = _citation_tokens(finding)
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


def _citation_tokens(text: str) -> list[str]:
    lower = text.lower()
    hints = ["能源", "冲突", "原油", "黄金", "纳指", "风险", "利率", "通胀", "美元", "商品", "事件", "图谱", "回测"]
    ascii_words = [part for part in lower.replace("：", " ").replace("，", " ").replace("。", " ").split() if len(part) >= 2]
    return list(dict.fromkeys([*ascii_words, *[hint for hint in hints if hint in lower]]))


def _edge_target_id(edge: dict) -> str:
    return f"edge:{edge.get('source')}->{edge.get('target')}:{edge.get('relation', '')}"


def _edge_label(value, labels: dict[str, str] | None = None) -> str:
    key = str(value or "unknown")
    return (labels or {}).get(key, key)


def _render_project_markdown(ai: AIAnalysisResult, citations: list[ReportCitation]) -> str:
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


def _run_summary(title: str, event_name: str, risk_score: float, confidence: float) -> str:
    return f"{title} 已完成一次研究运行：当前综合风险 {risk_score:.1f}/100，主导事件为{event_name}，因果图谱置信度 {confidence:.1f}/100。"


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _fast_mode() -> bool:
    return os.getenv("WORLDPULSE_STUDIO_FAST_MODE", "true").lower() != "false"


def _resolve_run_mode(mode: str) -> str:
    normalized = (mode or "fast").lower()
    if normalized in {"full", "real", "complete"}:
        return "full"
    if normalized == "env":
        return "fast" if _fast_mode() else "full"
    return "fast"


def _append_workflow_event(events: list[dict], key: str, title: str, status: str, detail: str) -> None:
    events.append(
        {
            "key": key,
            "title": title,
            "status": status,
            "detail": detail,
            "timestamp": _now(),
        }
    )


def _fast_research_bundle(project: ResearchProject):
    component = RiskComponent(
        key="geopolitical",
        name="geopolitical",
        display_name="地缘与政策压力",
        score=64.0,
        weight=0.2,
        trend="up",
        display_trend="上升",
        source="WorldPulse studio fast snapshot",
        drivers=["事件热度上升", "能源与贸易链条存在外溢"],
    )
    risk = RiskOverview(
        latest=CompositeRisk(
            date=datetime.now().strftime("%Y-%m-%d"),
            score=62.4,
            level="medium",
            display_level="中等风险",
            trend="up",
            display_trend="上升",
            forecast_30d=56,
            forecast_label="uncertain",
            display_forecast_label="方向不明确",
            components=[component],
            summary="工作台快速研究快照：当前风险处于中等偏上区间，需重点观察事件热度、能源价格和风险资产联动。",
        ),
        history=[RiskPoint(date=datetime.now().strftime("%Y-%m-%d"), score=62.4, financial=55, climate=49, geopolitical=64, ecology=46, macro=52)],
    )
    event_type = project.event_types[0] if project.event_types else "conflict"
    event = CausalEvent(
        event_type=event_type,
        name={
            "conflict": "冲突升级",
            "sanctions": "制裁与出口管制",
            "energy": "能源冲击",
            "food": "粮食压力",
            "rates": "利率与央行信号",
            "trade": "贸易摩擦",
            "climate": "气候灾害",
        }.get(event_type, event_type),
        region=project.region,
        window_days=project.event_window_days,
        intensity=63,
        event_count=96,
        source="WorldPulse studio fast snapshot",
        summary="快速研究模式使用可解释兜底事件强度，避免首次工作台运行被外部数据源阻塞。",
        confidence=68,
    )
    chain = CausalChain(
        event_type=event.event_type,
        title=f"{event.name}因果链",
        nodes=[
            CausalGraphNode(id="event", label=event.name, kind="event", score=event.intensity),
            CausalGraphNode(id="commodity", label="商品与能源预期", kind="commodity", score=55),
            CausalGraphNode(id="macro", label="通胀/利率/美元压力", kind="macro", score=52),
            CausalGraphNode(id="asset", label="股指与行业代理资产", kind="asset", score=50),
            CausalGraphNode(id="risk", label="综合风险指数", kind="macro", score=62),
        ],
        edges=[
            CausalGraphEdge(source="event", target="commodity", relation="供需预期重定价", weight=0.78, confidence=72, explanation="事件热度先影响商品、能源或关键供应链预期。"),
            CausalGraphEdge(source="commodity", target="macro", relation="成本与通胀传导", weight=0.66, confidence=64, explanation="商品价格压力会传导到通胀、利率和美元路径。"),
            CausalGraphEdge(source="macro", target="asset", relation="折现率与盈利预期", weight=0.62, confidence=61, explanation="宏观压力影响股指、行业和避险资产定价。"),
            CausalGraphEdge(source="asset", target="risk", relation="市场波动反馈", weight=0.58, confidence=59, explanation="资产波动反馈到综合风险指数和观察清单。"),
        ],
        confidence=66,
        explanation="快速图谱用于建立研究路径，后续可关闭快速模式接入真实慢数据。",
    )
    backtest = CausalBacktestResult(
        event_type=event.event_type,
        window_days=max(120, project.event_window_days * 4),
        sample_count=14,
        hit_rate=0.64,
        average_impact=1.15,
        max_error=2.35,
        impacts=[
            MarketImpact(asset_key="oil", asset_name="WTI 原油", direction="up", expected_return_pct=1.6, confidence=66, rationale="历史相似窗口中商品代理资产对事件冲击更敏感。"),
            MarketImpact(asset_key="nasdaq", asset_name="纳斯达克100", direction="down", expected_return_pct=-0.8, confidence=58, rationale="风险偏好和折现率压力会影响成长资产。"),
        ],
        similar_events=[],
        error_attribution=["快速模式样本为代理统计，不能替代完整事件研究。", "市场可能提前反应，新闻时间戳不等于价格冲击起点。"],
    )
    simulation = SimulationResult(
        summary="快速模拟显示冲击主要通过商品、宏观和资产风险偏好链条扩散。",
        horizon_months=12,
        runs=180,
        global_path=[SimulationPathPoint(month=month, p10=45 + month * 0.2, p50=55 + month * 0.35, p90=66 + month * 0.45) for month in range(1, 13)],
        countries=[],
        map_points=[SimulationMapPoint(code="USA", name="United States", latitude=38, longitude=-97, risk=58, uncertainty=11, region="North America")],
        propagation_edges=[SimulationPropagationEdge(source="event", target="risk", channel="causal", weight=0.6, impact=3.2)],
        drivers=[SimulationDriver(name=event.name, contribution=3.2, explanation="事件强度是当前快速研究的主导输入。")],
    )
    causal = type("FastCausal", (), {"chains": [chain]})()
    return risk, [event], causal, backtest, simulation


def _fast_ai_report(project: ResearchProject, run: ResearchRun, graph: CausalGraphSnapshot) -> AIAnalysisResult:
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
