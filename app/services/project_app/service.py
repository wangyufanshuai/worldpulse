from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
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
    WarRoomRun,
    WarRoomReplayPack,
    WarRoomScenarioRequest,
    WarRoomWorkspaceState,
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
from app.services.war_room_engine import WAR_ROOM_DISCLAIMER, run_war_room
from app.services.project_app.repository import (
    chat_messages as _chat_messages,
    get_project as _get_project,
    graph_for_run as _graph_for_run,
    latest_graph as _latest_graph,
    latest_report as _latest_report,
    latest_run as _latest_run,
    project_from_row as _project_from_row,
    project_runs as _project_runs,
    report_for_run as _report_for_run,
    run_by_id as _run_by_id,
    run_from_row as _run_from_row,
)


def create_project(payload: ResearchProjectCreate) -> ResearchProject:
    init_db()
    now = _now()
    project_mode = "war_room" if str(payload.mode).lower() == "war_room" else "research"
    project = ResearchProject(
        project_id=f"proj_{uuid4().hex[:12]}",
        title=payload.title.strip() or "未命名研究",
        question=payload.question.strip(),
        region=payload.region.strip() or "global",
        asset_scope=payload.asset_scope,
        event_window_days=max(7, min(payload.event_window_days, 90)),
        event_types=payload.event_types,
        mode=project_mode,
        scenario_config=payload.scenario_config or {},
        status="created",
        created_at=now,
        updated_at=now,
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO research_projects
            (project_id, title, question, region, asset_scope, event_window_days, event_types, mode, scenario_config, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.project_id,
                project.title,
                project.question,
                project.region,
                dumps(project.asset_scope),
                project.event_window_days,
                dumps(project.event_types),
                project.mode,
                dumps(project.scenario_config),
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


def war_room_workspace(project_id: str, run_id: str | None = None) -> WarRoomWorkspaceState:
    project = _get_project(project_id)
    runs = _project_runs(project_id)
    war_room_runs = [run for run in runs if _is_war_room_run(run)]
    selected_run = _run_by_id(project_id, run_id) if run_id else (war_room_runs[0] if war_room_runs else None)
    if selected_run and not _is_war_room_run(selected_run):
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Workspace requires a War Room run")

    previous_run = next((run for run in war_room_runs if selected_run and run.run_id != selected_run.run_id), None)
    sim = deepcopy(selected_run.simulation_snapshot or {}) if selected_run else {}
    ui_state = _workspace_ui_state(sim)
    entity_index = _workspace_entity_index(ui_state, sim)
    entity_details = _workspace_entity_details(ui_state, sim, entity_index)
    command_actions = _workspace_command_actions(selected_run, previous_run)
    run_control = _workspace_run_control(selected_run, previous_run, war_room_runs, sim)
    insight_cards = ui_state.get("insight_cards") or _workspace_insight_cards(ui_state, sim)
    ui_state.update(
        {
            "entity_index": entity_index,
            "entity_details": entity_details,
            "command_actions": command_actions,
            "run_control": run_control,
            "insight_cards": insight_cards,
        }
    )
    return WarRoomWorkspaceState(
        project_id=project_id,
        run_id=selected_run.run_id if selected_run else None,
        project={"project_id": project.project_id, "title": project.title, "mode": project.mode, "status": project.status},
        run_control=run_control,
        ui_state=ui_state,
        entity_index=entity_index,
        command_actions=command_actions,
        insight_cards=insight_cards,
        entity_details=entity_details,
        compare_ready=bool(selected_run and previous_run),
        replay_ready=bool(selected_run and sim.get("scenario")),
        disclaimer=sim.get("disclaimer") or WAR_ROOM_DISCLAIMER,
    )


def run_project(project_id: str, mode: str = "fast") -> ProjectDetail:
    project = _get_project(project_id)
    if project.mode == "war_room":
        return run_project_war_room(project_id, WarRoomScenarioRequest(**(project.scenario_config or {})))
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


def run_project_war_room(project_id: str, request: WarRoomScenarioRequest | None = None) -> ProjectDetail:
    project = _get_project(project_id)
    scenario_request = request or WarRoomScenarioRequest(**(project.scenario_config or {}))
    result = run_war_room(scenario_request)
    return persist_war_room_result(project_id, result)


def persist_war_room_result(
    project_id: str,
    result: WarRoomRun,
    *,
    run_id: str | None = None,
    started: str | None = None,
    completed: str | None = None,
    lifecycle_job_id: str | None = None,
) -> ProjectDetail:
    project = _get_project(project_id)
    started = started or _now()
    completed = completed or _now()
    run_id = run_id or f"run_{uuid4().hex[:12]}"
    workflow_events: list[dict] = []
    _append_workflow_event(workflow_events, "project", "War Room scenario", "completed", "Loaded scenario parameters, country agents, supply chains, and strategy-sandbox disclaimer.")
    _append_workflow_event(workflow_events, "scenario", "Scenario Sandbox", "completed", f"{result.scenario.name} for {result.scenario.duration_days} days at intensity {result.scenario.intensity:.2f}.")
    _append_workflow_event(workflow_events, "agents", "Agent Decisions", "completed", f"Generated {len(result.agent_decisions)} deterministic country-agent decisions.")
    _append_workflow_event(workflow_events, "graph", "Causal Chain", "completed", f"Generated {len(result.impact_graph.nodes)} nodes and {len(result.impact_graph.edges)} causal edges.")
    _append_workflow_event(workflow_events, "heatmap", "Risk Heatmap", "completed", f"Generated {len(result.risk_heatmap)} country heatmap cells.")
    _append_workflow_event(workflow_events, "report", "War Room Report", "completed", "Generated a local strategy-sandbox report with citation hooks and disclaimer.")

    risk = _war_room_risk_overview(result)
    run = ResearchRun(
        run_id=run_id,
        project_id=project.project_id,
        status="completed",
        started_at=started,
        completed_at=completed,
        summary=result.summary,
        data_snapshot={
            "question": project.question,
            "region": project.region,
            "asset_scope": project.asset_scope,
            "event_types": project.event_types,
            "run_mode": "war_room",
            "project_mode": "war_room",
            "scenario_config": result.scenario.model_dump(),
            "war_room": result.model_dump(),
            "assumptions": result.assumptions,
            "workflow_events": workflow_events,
            "sources": ["WorldPulse War Room deterministic sandbox", "WorldPulse built-in country agents", "WorldPulse supply-chain rules"],
            "disclaimer": result.disclaimer,
            "lifecycle_job_id": lifecycle_job_id,
        },
        risk_snapshot=risk.model_dump(),
        event_snapshot=[_war_room_event_snapshot(result)],
        simulation_snapshot=_war_room_simulation_snapshot(result),
        backtest_snapshot={"event_type": result.scenario.key, "sample_count": 0, "hit_rate": 0, "max_error": 0, "error_attribution": [WAR_ROOM_DISCLAIMER]},
    )
    graph = _war_room_graph_snapshot(project.project_id, run_id, result)
    report = _war_room_project_report(project, run, graph, result)

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
        conn.execute(
            "UPDATE research_projects SET status = ?, updated_at = ?, scenario_config = ? WHERE project_id = ?",
            ("completed", completed, dumps(result.scenario.model_dump()), project.project_id),
        )
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
    changed_metrics = {
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
    }
    war_room_diff = _war_room_run_diff(base, target, base_graph, target_graph)
    if war_room_diff:
        changed_metrics["war_room"] = war_room_diff
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
        changed_metrics=changed_metrics,
    )


def war_room_replay_pack(project_id: str, run_id: str | None = None, base_run_id: str | None = None, target_run_id: str | None = None) -> WarRoomReplayPack:
    project = _get_project(project_id)
    target = _run_by_id(project_id, target_run_id or run_id) if (target_run_id or run_id) else _latest_run(project_id)
    if target is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="No run available for replay pack")
    target_graph = _graph_for_run(project_id, target.run_id)
    target_sim = target.simulation_snapshot or {}
    if not target_sim.get("scenario"):
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Replay Pack requires a War Room run")

    base = _run_by_id(project_id, base_run_id) if base_run_id else None
    base_graph = _graph_for_run(project_id, base.run_id) if base else None
    diff = _war_room_run_diff(base, target, base_graph, target_graph) if base else None
    summary = _replay_pack_summary(target, diff)
    generated_at = _now()
    manifest = _replay_pack_manifest(project_id, project.title, target, base, diff, generated_at)
    model_inputs = _replay_pack_model_inputs(target_sim)
    model_outputs = _replay_pack_model_outputs(target_sim, target_graph, diff)
    audit_trail = _replay_pack_audit_trail(base, target, diff)
    markdown = _render_war_room_replay_markdown(project.title, target, target_graph, diff, summary, manifest, model_inputs, audit_trail)
    json_manifest = json.dumps(
        {
            "manifest": manifest,
            "model_inputs": model_inputs,
            "model_outputs": model_outputs,
            "audit_trail": audit_trail,
            "summary": summary,
            "counterfactual_observations": diff.get("counterfactual_observations", []) if diff else [],
            "disclaimer": WAR_ROOM_DISCLAIMER,
        },
        ensure_ascii=False,
        indent=2,
    )
    return WarRoomReplayPack(
        project_id=project_id,
        run_id=target.run_id,
        base_run_id=base.run_id if base else None,
        target_run_id=target.run_id if base else None,
        title=f"{project.title} Replay Pack",
        scenario=target_sim.get("scenario", {}),
        policy_actions=target_sim.get("scenario", {}).get("policy_actions", []),
        risk_heatmap=target_sim.get("risk_heatmap", []),
        supply_chain_delta=diff.get("supply_chain_delta", []) if diff else [],
        agent_decisions=target_sim.get("agent_decisions", []),
        timeline=target_sim.get("timeline", []),
        timeline_delta=diff.get("timeline_delta", {}) if diff else {},
        impact_graph=target_sim.get("impact_graph", target_graph.model_dump() if target_graph else {}),
        assumptions=target_sim.get("assumptions", []),
        counterfactual_observations=diff.get("counterfactual_observations", []) if diff else [],
        summary=summary,
        manifest=manifest,
        model_inputs=model_inputs,
        model_outputs=model_outputs,
        audit_trail=audit_trail,
        artifacts={"markdown": markdown, "json_manifest": json_manifest},
        markdown=markdown,
        disclaimer=WAR_ROOM_DISCLAIMER,
    )


def _replay_pack_manifest(project_id: str, project_title: str, target: ResearchRun, base: ResearchRun | None, diff: dict | None, generated_at: str) -> dict:
    return {
        "pack_version": "war-room-replay-pack.audit.v1",
        "project_id": project_id,
        "project_title": project_title,
        "run_id": target.run_id,
        "base_run_id": base.run_id if base else None,
        "target_run_id": target.run_id if base else None,
        "generated_at": generated_at,
        "run_started_at": target.started_at,
        "run_completed_at": target.completed_at,
        "is_counterfactual": bool(diff),
        "artifact_types": ["markdown", "json_manifest"],
        "disclaimer": WAR_ROOM_DISCLAIMER,
    }


def _replay_pack_model_inputs(sim: dict) -> dict:
    scenario = sim.get("scenario", {}) or {}
    return {
        "scenario": {
            "key": scenario.get("key") or scenario.get("scenario_key"),
            "name": scenario.get("name"),
            "description": scenario.get("description"),
        },
        "duration_days": scenario.get("duration_days"),
        "intensity": scenario.get("intensity"),
        "propagation": scenario.get("propagation"),
        "target_countries": scenario.get("target_countries", []),
        "target_chains": scenario.get("target_chains", []),
        "policy_actions": scenario.get("policy_actions", []),
        "country_overrides": scenario.get("country_overrides", {}),
        "chain_overrides": scenario.get("chain_overrides", {}),
    }


def _replay_pack_model_outputs(sim: dict, graph: CausalGraphSnapshot | None, diff: dict | None) -> dict:
    return {
        "risk_heatmap": sim.get("risk_heatmap", []),
        "supply_chains": sim.get("supply_chains", []),
        "agent_decisions": sim.get("agent_decisions", []),
        "timeline": sim.get("timeline", []),
        "impact_graph": sim.get("impact_graph", graph.model_dump() if graph else {}),
        "ui_state": sim.get("ui_state", {}),
        "diff_metrics": diff or {},
    }


def _replay_pack_audit_trail(base: ResearchRun | None, target: ResearchRun, diff: dict | None) -> list[dict]:
    return [
        {
            "step": "stored_run_snapshot",
            "source": "research_runs.simulation_snapshot",
            "detail": f"Loaded target War Room run {target.run_id} from existing project storage.",
        },
        {
            "step": "user_controls",
            "source": "scenario_config",
            "detail": "Scenario builder inputs were copied from the stored run snapshot; no live intelligence or market feed was used.",
        },
        {
            "step": "deterministic_rules",
            "source": "war_room_engine.py",
            "detail": "Country risk, supply-chain pressure, timeline, and agent decisions were produced by local deterministic rules.",
        },
        {
            "step": "counterfactual_diff" if diff else "single_run_export",
            "source": "compare API" if diff else "target run only",
            "detail": f"Compared base run {base.run_id} with target run {target.run_id}." if diff and base else "No base run was selected; the pack audits one run only.",
        },
        {
            "step": "template_generated_artifacts",
            "source": "Replay Pack renderer",
            "detail": "Markdown and JSON manifest were generated from stored snapshots and deterministic diff data.",
        },
        {
            "step": "boundary",
            "source": "WorldPulse disclaimer",
            "detail": WAR_ROOM_DISCLAIMER,
        },
    ]


def _war_room_run_diff(base: ResearchRun, target: ResearchRun, base_graph: CausalGraphSnapshot | None, target_graph: CausalGraphSnapshot | None) -> dict | None:
    base_sim = base.simulation_snapshot or {}
    target_sim = target.simulation_snapshot or {}
    if not base_sim.get("risk_heatmap") or not target_sim.get("risk_heatmap"):
        return None

    country_risk_delta = _country_risk_delta(base_sim, target_sim)
    supply_chain_delta = _supply_chain_delta(base_sim, target_sim)
    agent_decision_changes = _agent_decision_changes(base_sim, target_sim)
    timeline_delta = _timeline_delta(base_sim, target_sim)
    causal_edge_delta = _causal_edge_delta(base_graph, target_graph)
    top_country = country_risk_delta[0] if country_risk_delta else None
    top_chain = supply_chain_delta[0] if supply_chain_delta else None
    base_peak = timeline_delta.get("base_peak_global_risk")
    target_peak = timeline_delta.get("target_peak_global_risk")
    confidence_delta = None
    if base_graph and target_graph:
        confidence_delta = round((target_graph.confidence or 0) - (base_graph.confidence or 0), 2)

    observations = []
    if top_chain:
        direction = "increased" if top_chain["delta"] > 0 else "decreased"
        observations.append(f"{top_chain['name']} pressure {direction} by {top_chain['delta']:+.1f} points.")
    if top_country:
        direction = "increased" if top_country["delta"] > 0 else "decreased"
        observations.append(f"{top_country['country_name']} country-agent risk {direction} by {top_country['delta']:+.1f} points.")
    if base_peak is not None and target_peak is not None:
        observations.append(f"Peak global risk changed by {target_peak - base_peak:+.1f} points across the timeline.")
    if not observations:
        observations.append("No material War Room counterfactual deltas were detected.")

    return {
        "base_run_id": base.run_id,
        "target_run_id": target.run_id,
        "base_policy_actions": base_sim.get("scenario", {}).get("policy_actions", []),
        "target_policy_actions": target_sim.get("scenario", {}).get("policy_actions", []),
        "global_risk_delta": _round_delta(target.simulation_snapshot.get("timeline", [])[-1].get("global_risk") if target.simulation_snapshot.get("timeline") else None, base.simulation_snapshot.get("timeline", [])[-1].get("global_risk") if base.simulation_snapshot.get("timeline") else None),
        "top_country_risk_delta": top_country,
        "top_chain_pressure_delta": top_chain,
        "graph_confidence_delta": confidence_delta,
        "country_risk_delta": country_risk_delta,
        "supply_chain_delta": supply_chain_delta,
        "agent_decision_changes": agent_decision_changes,
        "timeline_delta": timeline_delta,
        "causal_edge_delta": causal_edge_delta,
        "counterfactual_observations": observations,
        "disclaimer": WAR_ROOM_DISCLAIMER,
    }


def _country_risk_delta(base_sim: dict, target_sim: dict) -> list[dict]:
    base_items = {item.get("country_code"): item for item in base_sim.get("risk_heatmap", [])}
    rows = []
    for target_item in target_sim.get("risk_heatmap", []):
        code = target_item.get("country_code")
        base_item = base_items.get(code, {})
        base_risk = float(base_item.get("risk") or 0)
        target_risk = float(target_item.get("risk") or 0)
        rows.append({
            "country_code": code,
            "country_name": target_item.get("country_name"),
            "base": round(base_risk, 1),
            "target": round(target_risk, 1),
            "delta": round(target_risk - base_risk, 1),
            "base_dominant_channel": base_item.get("dominant_channel"),
            "target_dominant_channel": target_item.get("dominant_channel"),
        })
    return sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)


def _supply_chain_delta(base_sim: dict, target_sim: dict) -> list[dict]:
    base_items = {item.get("key"): item for item in base_sim.get("supply_chains", [])}
    rows = []
    for target_item in target_sim.get("supply_chains", []):
        key = target_item.get("key")
        base_item = base_items.get(key, {})
        base_pressure = float(base_item.get("pressure_score") or 0)
        target_pressure = float(target_item.get("pressure_score") or 0)
        rows.append({
            "key": key,
            "name": target_item.get("name"),
            "base_pressure": round(base_pressure, 1),
            "target_pressure": round(target_pressure, 1),
            "delta": round(target_pressure - base_pressure, 1),
            "base_capacity": base_item.get("capacity"),
            "target_capacity": target_item.get("capacity"),
        })
    return sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)


def _agent_decision_changes(base_sim: dict, target_sim: dict) -> list[dict]:
    base_items = {item.get("country_code"): item for item in base_sim.get("agent_decisions", [])}
    rows = []
    for target_item in target_sim.get("agent_decisions", []):
        code = target_item.get("country_code")
        base_item = base_items.get(code)
        if base_item is None:
            status = "new"
            base_action = None
        else:
            base_action = base_item.get("action")
            status = "changed" if base_action != target_item.get("action") else "unchanged"
        rows.append({
            "country_code": code,
            "country_name": target_item.get("country_name"),
            "status": status,
            "base_action": base_action,
            "target_action": target_item.get("action"),
            "base_risk_delta": base_item.get("risk_delta") if base_item else None,
            "target_risk_delta": target_item.get("risk_delta"),
            "drivers": target_item.get("drivers", []),
        })
    return sorted(rows, key=lambda item: {"changed": 0, "new": 1, "unchanged": 2}.get(item["status"], 3))


def _timeline_delta(base_sim: dict, target_sim: dict) -> dict:
    base_items = {item.get("day"): item for item in base_sim.get("timeline", [])}
    points = []
    for target_item in target_sim.get("timeline", []):
        day = target_item.get("day")
        base_item = base_items.get(day, {})
        base_risk = float(base_item.get("global_risk") or 0)
        target_risk = float(target_item.get("global_risk") or 0)
        points.append({
            "day": day,
            "base_global_risk": round(base_risk, 1),
            "target_global_risk": round(target_risk, 1),
            "delta": round(target_risk - base_risk, 1),
            "turning_point": bool(target_item.get("turning_point") or base_item.get("turning_point")),
        })
    base_peak = max((float(item.get("global_risk") or 0) for item in base_sim.get("timeline", [])), default=None)
    target_peak = max((float(item.get("global_risk") or 0) for item in target_sim.get("timeline", [])), default=None)
    return {
        "base_peak_global_risk": round(base_peak, 1) if base_peak is not None else None,
        "target_peak_global_risk": round(target_peak, 1) if target_peak is not None else None,
        "peak_delta": _round_delta(target_peak, base_peak),
        "points": points,
    }


def _causal_edge_delta(base_graph: CausalGraphSnapshot | None, target_graph: CausalGraphSnapshot | None) -> list[dict]:
    if not base_graph or not target_graph:
        return []
    base_edges = {_edge_signature(edge): edge for edge in base_graph.edges or []}
    rows = []
    for edge in target_graph.edges or []:
        signature = _edge_signature(edge)
        base_edge = base_edges.get(signature, {})
        base_weight = float(base_edge.get("weight") or 0)
        target_weight = float(edge.get("weight") or 0)
        rows.append({
            "source": edge.get("source"),
            "target": edge.get("target"),
            "relation": edge.get("relation"),
            "base_weight": round(base_weight, 3),
            "target_weight": round(target_weight, 3),
            "delta": round(target_weight - base_weight, 3),
            "mechanism": edge.get("mechanism") or edge.get("explanation"),
        })
    return sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)[:8]


def _edge_signature(edge: dict) -> str:
    return f"{edge.get('source')}->{edge.get('target')}:{edge.get('relation')}"


def _round_delta(target_value: float | None, base_value: float | None) -> float | None:
    if target_value is None or base_value is None:
        return None
    return round(float(target_value) - float(base_value), 1)


def _replay_pack_summary(target: ResearchRun, diff: dict | None) -> dict:
    sim = target.simulation_snapshot or {}
    heatmap = sim.get("risk_heatmap", [])
    chains = sim.get("supply_chains", [])
    timeline = sim.get("timeline", [])
    top_country = max(heatmap, key=lambda item: float(item.get("risk") or 0), default={})
    top_chain = max(chains, key=lambda item: float(item.get("pressure_score") or 0), default={})
    peak = max((float(item.get("global_risk") or 0) for item in timeline), default=None)
    return {
        "run_id": target.run_id,
        "policy_actions": sim.get("scenario", {}).get("policy_actions", []),
        "top_risk_country": top_country,
        "top_chain": top_chain,
        "timeline_peak_global_risk": round(peak, 1) if peak is not None else None,
        "top_chain_delta": diff.get("top_chain_pressure_delta") if diff else None,
        "timeline_peak_delta": diff.get("timeline_delta", {}).get("peak_delta") if diff else None,
        "is_counterfactual": bool(diff),
    }


def _render_war_room_replay_markdown(project_title: str, target: ResearchRun, graph: CausalGraphSnapshot | None, diff: dict | None, summary: dict, manifest: dict, model_inputs: dict, audit_trail: list[dict]) -> str:
    sim = target.simulation_snapshot or {}
    scenario = sim.get("scenario", {})
    policy_actions = scenario.get("policy_actions", [])
    heatmap = sim.get("risk_heatmap", [])
    chains = diff.get("supply_chain_delta", []) if diff else sim.get("supply_chains", [])
    decisions = sim.get("agent_decisions", [])
    timeline = sim.get("timeline", [])
    assumptions = sim.get("assumptions", [])
    edges = (graph.edges if graph else sim.get("impact_graph", {}).get("edges", [])) or []
    observations = diff.get("counterfactual_observations", []) if diff else ["Single-run Replay Pack; no base run was selected for counterfactual comparison."]

    lines = [
        f"# {project_title} War Room Replay Pack",
        "",
        f"> {WAR_ROOM_DISCLAIMER}",
        "",
        "## Replay Pack Manifest",
        f"- Pack version: `{manifest.get('pack_version')}`",
        f"- Project ID: `{manifest.get('project_id')}`",
        f"- Run ID: `{manifest.get('run_id')}`",
        f"- Base run ID: `{manifest.get('base_run_id') or 'none'}`",
        f"- Target run ID: `{manifest.get('target_run_id') or manifest.get('run_id')}`",
        f"- Generated at: {manifest.get('generated_at')}",
        f"- Counterfactual: {manifest.get('is_counterfactual')}",
        "",
        "## Scenario Setup",
        f"- Run ID: `{target.run_id}`",
        f"- Scenario: {scenario.get('name') or scenario.get('key') or 'War Room scenario'}",
        f"- Duration: {scenario.get('duration_days')} days",
        f"- Intensity: {scenario.get('intensity')}",
        f"- Propagation: {scenario.get('propagation')}",
        f"- Target countries: {', '.join(scenario.get('target_countries') or []) or 'none'}",
        f"- Target chains: {', '.join(scenario.get('target_chains') or []) or 'none'}",
        "",
        "## Policy Actions",
        *(f"- {item}" for item in (policy_actions or ["none"])),
        "",
        "## Model Inputs",
        f"- Duration: {model_inputs.get('duration_days')} days",
        f"- Intensity: {model_inputs.get('intensity')}",
        f"- Propagation: {model_inputs.get('propagation')}",
        f"- Target countries: {', '.join(model_inputs.get('target_countries') or []) or 'none'}",
        f"- Target chains: {', '.join(model_inputs.get('target_chains') or []) or 'none'}",
        f"- Policy actions: {', '.join(model_inputs.get('policy_actions') or []) or 'none'}",
        "",
        "## User Overrides",
        f"- Country overrides: `{json.dumps(model_inputs.get('country_overrides') or {}, ensure_ascii=False)}`",
        f"- Chain overrides: `{json.dumps(model_inputs.get('chain_overrides') or {}, ensure_ascii=False)}`",
        "",
        "## Risk Hotspots",
        *[
            f"- {item.get('country_name')} ({item.get('country_code')}): {float(item.get('risk') or 0):.1f}/100, dominant channel `{item.get('dominant_channel')}`"
            for item in heatmap[:8]
        ],
        "",
        "## Supply Chain Bottlenecks",
    ]
    if diff:
        lines.extend(
            f"- {item.get('name')}: {item.get('base_pressure')} -> {item.get('target_pressure')} ({float(item.get('delta') or 0):+.1f})"
            for item in chains[:8]
        )
    else:
        lines.extend(
            f"- {item.get('name')}: pressure {float(item.get('pressure_score') or 0):.1f}/100, capacity {item.get('capacity')}"
            for item in chains[:8]
        )
    lines.extend(
        [
            "",
            "## Agent Decisions",
            *[
                f"- {item.get('country_name')} ({item.get('country_code')}): {item.get('action')} | drivers: {', '.join(item.get('drivers') or []) or 'none'}"
                for item in decisions[:8]
            ],
            "",
            "## Timeline Turning Points",
            *[
                f"- D+{item.get('day')}: global risk {float(item.get('global_risk') or 0):.1f}/100 - {item.get('key_development')}"
                for item in timeline
                if item.get("turning_point") or item.get("day") in {0, scenario.get("duration_days")}
            ],
            "",
            "## Causal Mechanisms",
            *[
                f"- {edge.get('source')} -> {edge.get('target')}: {edge.get('relation')} | weight {edge.get('weight')} | {edge.get('mechanism') or edge.get('explanation')}"
                for edge in edges[:10]
            ],
            "",
            "## Deterministic Rule Trace",
            "- Scenario inputs were normalized before simulation.",
            "- Policy actions adjusted supply-chain pressure and country-agent risk through local rule deltas.",
            "- Risk heatmap, agent decisions, timeline, and causal edges were rendered from stored deterministic outputs.",
            "- AI text, when present elsewhere in the project, is explanatory and does not determine core numeric results.",
            "",
            "## Counterfactual Observations",
            *(f"- {item}" for item in observations),
            "",
            "## Audit Trail",
            *[f"- `{item.get('step')}` ({item.get('source')}): {item.get('detail')}" for item in audit_trail],
            "",
            "## Model Assumptions",
            *(f"- {item}" for item in assumptions),
            "",
            "## Replay Summary",
            f"- Top risk country: {summary.get('top_risk_country', {}).get('country_name')} ({summary.get('top_risk_country', {}).get('risk')})",
            f"- Top chain: {summary.get('top_chain', {}).get('name')} ({summary.get('top_chain', {}).get('pressure_score')})",
            f"- Timeline peak global risk: {summary.get('timeline_peak_global_risk')}",
            f"- Timeline peak delta: {summary.get('timeline_peak_delta')}",
            "",
            f"_{WAR_ROOM_DISCLAIMER}_",
            "",
        ]
    )
    return "\n".join(lines)


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


def _is_war_room_run(run: ResearchRun) -> bool:
    return bool((run.simulation_snapshot or {}).get("scenario") or (run.data_snapshot or {}).get("run_mode") == "war_room")


def _workspace_ui_state(sim: dict) -> dict:
    ui_state = deepcopy(sim.get("ui_state") or {})
    ui_state.setdefault("display", {"title_zh": "War Room 指挥沙盘", "subtitle_zh": "等待运行或选择历史 run", "disclaimer_zh": WAR_ROOM_DISCLAIMER})
    ui_state.setdefault("kpis", [])
    ui_state.setdefault("map_layers", [])
    ui_state.setdefault("map_entities", [])
    ui_state.setdefault("timeline_events", [])
    ui_state.setdefault("agent_panels", {})
    return ui_state


def _workspace_run_control(selected: ResearchRun | None, previous: ResearchRun | None, runs: list[ResearchRun], sim: dict) -> dict:
    scenario = sim.get("scenario") or {}
    policy_actions = scenario.get("policy_actions") or []
    return {
        "current_run_id": selected.run_id if selected else None,
        "current_completed_at": selected.completed_at if selected else None,
        "previous_run_id": previous.run_id if previous else None,
        "compare_ready": bool(selected and previous),
        "replay_ready": bool(selected and scenario),
        "run_count": len(runs),
        "scenario_title_zh": scenario.get("name") or "War Room 沙盘",
        "duration_days": scenario.get("duration_days"),
        "policy_actions": policy_actions,
        "policy_actions_zh": [_workspace_policy_label(action) for action in policy_actions],
        "status_zh": "可对比复盘" if selected and previous else ("可导出复盘" if selected else "等待首次运行"),
    }


def _workspace_command_actions(selected: ResearchRun | None, previous: ResearchRun | None) -> list[dict]:
    has_run = selected is not None
    has_compare = selected is not None and previous is not None
    return [
        {"key": "command_search", "label_zh": "指挥搜索", "action_type": "panel", "enabled": True, "status": "active"},
        {"key": "run_scenario", "label_zh": "运行沙盘", "action_type": "run", "enabled": True, "status": "active"},
        {"key": "clone_run", "label_zh": "克隆本次运行", "action_type": "clone", "enabled": has_run, "status": "active" if has_run else "disabled"},
        {"key": "compare_runs", "label_zh": "反事实对比", "action_type": "compare", "enabled": has_compare, "status": "active" if has_compare else "disabled"},
        {"key": "export_replay", "label_zh": "导出复盘包", "action_type": "replay", "enabled": has_run, "status": "active" if has_run else "disabled"},
        {"key": "delta_overlay", "label_zh": "反事实图层", "action_type": "toggle", "enabled": has_compare, "status": "active" if has_compare else "disabled"},
        {"key": "three_d", "label_zh": "3D 地球视图", "action_type": "upcoming", "enabled": False, "status": "upcoming"},
    ]


def _workspace_entity_index(ui_state: dict, sim: dict) -> list[dict]:
    existing = ui_state.get("entity_index")
    if isinstance(existing, list) and existing:
        return existing
    index: list[dict] = []
    for entity in ui_state.get("map_entities") or []:
        entity_id = str(entity.get("id") or "")
        entity_type = str(entity.get("type") or "entity")
        title = entity.get("title_zh") or entity.get("label_zh") or entity.get("label") or entity_id
        subtitle = entity.get("detail_zh") or entity.get("mechanism_zh") or _workspace_entity_subtitle(entity)
        index.append(
            {
                "id": entity_id,
                "type": entity_type,
                "title_zh": title,
                "subtitle_zh": subtitle,
                "section": _workspace_section_for_entity(entity_type),
                "layer": entity.get("layer", ""),
                "day": entity.get("day"),
                "ref": entity_id,
                "tokens": [entity_id, str(entity.get("key", "")), str(entity.get("layer", "")), title, subtitle, *(entity.get("related_countries") or []), *(entity.get("related_chains") or [])],
            }
        )
    for event in ui_state.get("timeline_events") or []:
        key = str(event.get("key") or event.get("day") or "")
        index.append(
            {
                "id": f"timeline:{key}",
                "type": "timeline",
                "title_zh": event.get("title_zh") or "时间线事件",
                "subtitle_zh": event.get("detail_zh") or "",
                "section": "overview",
                "layer": "events",
                "day": event.get("day"),
                "ref": key,
                "tokens": [key, str(event.get("time", "")), str(event.get("day", "")), *(event.get("related_countries") or []), *(event.get("related_chains") or [])],
            }
        )
    for decision in sim.get("agent_decisions") or []:
        code = decision.get("country_code") or ""
        index.append(
            {
                "id": f"decision:{code}",
                "type": "decision",
                "title_zh": _workspace_decision_label(decision.get("action")),
                "subtitle_zh": f"{_workspace_country_label(code)} · 置信度 {round(float(decision.get('confidence') or 0))}/100",
                "section": "analysis",
                "layer": "risk",
                "day": None,
                "ref": f"country:{code}",
                "tokens": [code, decision.get("country_name", ""), decision.get("action", ""), *(decision.get("drivers") or [])],
            }
        )
    return index


def _workspace_entity_details(ui_state: dict, sim: dict, entity_index: list[dict]) -> dict:
    existing = ui_state.get("entity_details")
    if isinstance(existing, dict) and existing:
        return existing
    entities = {str(entity.get("id") or ""): entity for entity in ui_state.get("map_entities") or []}
    details: dict[str, dict] = {}
    for item in entity_index:
        entity_id = item.get("ref") if str(item.get("id", "")).startswith("timeline:") else item.get("id")
        entity = entities.get(str(entity_id), {})
        details[item["id"]] = {
            "id": item["id"],
            "type": item.get("type", "entity"),
            "title_zh": item.get("title_zh", item["id"]),
            "summary_zh": item.get("subtitle_zh", ""),
            "metrics": _workspace_detail_metrics(entity, item),
            "related_events": _workspace_related_events(entity, ui_state.get("timeline_events") or []),
            "related_countries": [_workspace_country_label(code) for code in entity.get("related_countries", [])],
            "related_chains": [_workspace_chain_label(key) for key in entity.get("related_chains", [])],
            "actions": _workspace_detail_actions(item.get("type", "entity")),
        }
    for code, panel in (ui_state.get("agent_panels") or {}).items():
        details.setdefault(f"country:{code}", {}).update({"agent_panel": panel, "decision_basis_zh": panel.get("decision_basis_zh", ""), "expected_tradeoff_zh": panel.get("expected_tradeoff_zh", "")})
    return details


def _workspace_insight_cards(ui_state: dict, sim: dict) -> list[dict]:
    heatmap = sim.get("risk_heatmap") or []
    chains = sim.get("supply_chains") or []
    top_country = max(heatmap, key=lambda item: float(item.get("risk") or 0), default={})
    top_chain = max(chains, key=lambda item: float(item.get("pressure_score") or item.get("pressure") or item.get("disruption") or 0), default={})
    turning = [event for event in ui_state.get("timeline_events") or [] if event.get("turning_point")]
    return [
        {"key": "top_country", "label_zh": "最高风险国家", "value_zh": f"{_workspace_country_label(top_country.get('country_code'))} {round(float(top_country.get('risk') or 0))}/100", "tone": "red", "detail_zh": "点击国家节点查看 Agent 决策。"},
        {"key": "top_chain", "label_zh": "供应链瓶颈", "value_zh": f"{_workspace_chain_label(top_chain.get('key'))} {round(float(top_chain.get('pressure_score') or top_chain.get('pressure') or top_chain.get('disruption') or 0))}/100", "tone": "orange", "detail_zh": "压力由替代率、容量和滞后天数共同决定。"},
        {"key": "turning", "label_zh": "关键拐点", "value_zh": f"{len(turning)} 个", "tone": "blue", "detail_zh": "可用事件筛选聚焦关键拐点。"},
    ]


def _workspace_entity_subtitle(entity: dict) -> str:
    entity_type = entity.get("type")
    if entity_type == "country":
        return f"风险 {entity.get('risk', '--')}/100"
    if entity_type == "supply_chain":
        return f"压力 {entity.get('pressure', '--')}/100 · 滞后 {entity.get('lag_days', 0)} 天"
    if entity_type == "causal_edge":
        return f"权重 {entity.get('weight', '--')} · 滞后 {entity.get('lag_days', 0)} 天"
    if entity_type == "event":
        return f"D+{entity.get('day', 0)} · 事件热点"
    return "War Room 实体"


def _workspace_section_for_entity(entity_type: str) -> str:
    return {"country": "analysis", "supply_chain": "sandbox", "causal_edge": "graph", "event": "overview", "timeline": "overview", "decision": "analysis"}.get(entity_type, "overview")


def _workspace_detail_metrics(entity: dict, item: dict) -> list[dict]:
    entity_type = item.get("type")
    if entity_type == "country":
        return [{"label_zh": "风险分值", "value": f"{entity.get('risk', '--')}/100"}, {"label_zh": "主导通道", "value": entity.get("dominant_channel_zh") or entity.get("dominant_channel") or "--"}]
    if entity_type == "supply_chain":
        return [{"label_zh": "链路压力", "value": f"{entity.get('pressure', '--')}/100"}, {"label_zh": "替代率", "value": f"{entity.get('substitution', '--')}%"}, {"label_zh": "滞后", "value": f"{entity.get('lag_days', 0)} 天"}]
    if entity_type == "causal_edge":
        return [{"label_zh": "边权重", "value": entity.get("weight", "--")}, {"label_zh": "滞后", "value": f"{entity.get('lag_days', 0)} 天"}]
    return [{"label_zh": "类型", "value": item.get("type", "entity")}]


def _workspace_related_events(entity: dict, timeline_events: list[dict]) -> list[str]:
    countries = set(entity.get("related_countries") or [])
    chains = set(entity.get("related_chains") or [])
    matches = []
    for event in timeline_events:
        if countries.intersection(event.get("related_countries") or []) or chains.intersection(event.get("related_chains") or []):
            matches.append(f"D+{event.get('day')} {event.get('title_zh') or event.get('title')}")
    return matches[:4]


def _workspace_detail_actions(entity_type: str) -> list[dict]:
    actions = [{"key": "focus", "label_zh": "在地图中定位", "action_type": "focus", "enabled": True}]
    if entity_type == "country":
        actions.append({"key": "analysis", "label_zh": "进入智能分析", "action_type": "section", "section": "analysis", "enabled": True})
    if entity_type == "causal_edge":
        actions.append({"key": "graph", "label_zh": "查看因果链路", "action_type": "section", "section": "graph", "enabled": True})
    actions.append({"key": "replay", "label_zh": "导出复盘包", "action_type": "replay", "enabled": True})
    return actions


def _workspace_country_label(code: str | None) -> str:
    return {"USA": "美国", "CHN": "中国", "JPN": "日本", "KOR": "韩国", "TWN": "台湾", "IND": "印度", "EU": "欧盟", "RUS": "俄罗斯", "SAU": "中东", "BRA": "巴西"}.get(str(code or ""), str(code or "--"))


def _workspace_chain_label(key: str | None) -> str:
    return {"energy": "能源", "food": "粮食", "chips": "关键芯片", "shipping": "海运贸易", "settlement": "金融结算"}.get(str(key or ""), str(key or "--"))


def _workspace_policy_label(key: str) -> str:
    return {"sanctions": "制裁", "counter_sanctions": "反制裁", "energy_reroute": "能源改道", "food_export_limit": "粮食出口限制", "alliance_deterrence": "联盟威慑", "liquidity_support": "流动性支持", "public_messaging": "舆论沟通"}.get(str(key or ""), str(key or ""))


def _workspace_decision_label(action: str | None) -> str:
    return {
        "Diversify emergency energy cargoes": "分散能源应急货源",
        "Prioritize chip allocation and export controls": "优先保障芯片分配与出口管制",
        "Signal deterrence while opening crisis channel": "释放威慑信号并开启危机沟通",
        "Coordinate liquidity and settlement safeguards": "协调流动性与结算保护",
        "Monitor alliances and prepare substitution": "监测联盟变化并准备替代方案",
    }.get(str(action or ""), str(action or "观察态势"))


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


def _war_room_risk_overview(result: WarRoomRun) -> RiskOverview:
    latest_score = result.timeline[-1].global_risk if result.timeline else 50.0
    component_specs = [
        ("geopolitical", "Geopolitical", latest_score, ["deterrence", "alliances", "sanctions"]),
        ("energy", "Energy", _chain_pressure(result, "energy"), ["energy imports", "rerouting", "substitution"]),
        ("food", "Food", _chain_pressure(result, "food"), ["food availability", "export restrictions", "social stability"]),
        ("financial", "Financial", result.timeline[-1].financial_pressure if result.timeline else 40.0, ["settlement", "liquidity", "risk appetite"]),
    ]
    components = [
        RiskComponent(
            key=key,
            name=key,
            display_name=name,
            score=round(score, 1),
            weight=0.25,
            trend="up",
            display_trend="up",
            source="WorldPulse War Room",
            drivers=drivers,
        )
        for key, name, score, drivers in component_specs
    ]
    return RiskOverview(
        latest=CompositeRisk(
            date=datetime.now().strftime("%Y-%m-%d"),
            score=round(latest_score, 1),
            level="scenario",
            display_level="Strategy sandbox",
            trend="up",
            display_trend="scenario stress",
            forecast_30d=round(min(95, latest_score), 1),
            forecast_label="sandbox",
            display_forecast_label="Not a prediction",
            components=components,
            summary=result.summary,
        ),
        history=[
            RiskPoint(
                date=f"D+{point.day}",
                score=point.global_risk,
                financial=point.financial_pressure,
                climate=0,
                geopolitical=point.trade_pressure,
                ecology=point.food_pressure,
                macro=point.energy_pressure,
            )
            for point in result.timeline
        ],
    )


def _war_room_event_snapshot(result: WarRoomRun) -> dict:
    return {
        "event_type": "war_room",
        "name": result.scenario.name,
        "region": "global",
        "window_days": result.scenario.duration_days,
        "intensity": round(result.scenario.intensity * 100, 1),
        "event_count": len(result.timeline),
        "source": "WorldPulse War Room deterministic sandbox",
        "summary": result.scenario.description,
        "confidence": result.impact_graph.confidence,
    }


def _war_room_simulation_snapshot(result: WarRoomRun) -> dict:
    return {
        "summary": result.summary,
        "scenario": result.scenario.model_dump(),
        "timeline": [item.model_dump() for item in result.timeline],
        "country_agents": [item.model_dump() for item in result.country_agents],
        "supply_chains": [item.model_dump() for item in result.supply_chains],
        "risk_heatmap": [item.model_dump() for item in result.risk_heatmap],
        "agent_decisions": [item.model_dump() for item in result.agent_decisions],
        "impact_graph": result.impact_graph.model_dump(),
        "disclaimer": result.disclaimer,
        "assumptions": result.assumptions,
        "ui_state": result.ui_state,
    }


def _war_room_graph_snapshot(project_id: str, run_id: str, result: WarRoomRun) -> CausalGraphSnapshot:
    return CausalGraphSnapshot(
        graph_id=f"graph_{uuid4().hex[:12]}",
        project_id=project_id,
        run_id=run_id,
        generated_at=_now(),
        nodes=result.impact_graph.nodes,
        edges=[
            {
                **edge,
                "evidence": [
                    "WorldPulse deterministic War Room rules",
                    f"Scenario intensity: {result.scenario.intensity:.2f}",
                    WAR_ROOM_DISCLAIMER,
                ],
                "backtest": {"sample_count": 0, "hit_rate": 0, "max_error": 0},
            }
            for edge in result.impact_graph.edges
        ],
        confidence=result.impact_graph.confidence,
        evidence_sources=["WorldPulse War Room deterministic sandbox", "WorldPulse supply-chain rules", "WorldPulse country-agent rules"],
    )


def _war_room_project_report(project: ResearchProject, run: ResearchRun, graph: CausalGraphSnapshot, result: WarRoomRun) -> ProjectAIReport:
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
    citations = _build_report_citations(key_findings, evidence, graph, run.backtest_snapshot)
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
            WatchSignal(name="Energy pressure", direction="scenario", why_it_matters="Energy is a first-order inflation and stability channel.", current_status=f"{_chain_pressure(result, 'energy'):.1f}/100"),
            WatchSignal(name="Critical chips", direction="scenario", why_it_matters="Chip disruption connects trade, industry, and alliance response.", current_status=f"{_chain_pressure(result, 'chips'):.1f}/100"),
            WatchSignal(name="Public opinion", direction="scenario", why_it_matters="Opinion pressure affects stability and diplomatic room for maneuver.", current_status=f"{result.timeline[-1].public_opinion_pressure:.1f}/100"),
        ],
        scenario_suggestions=[
            ScenarioSuggestion(name="Lower intensity de-escalation", shock_type="war_room", target_codes=result.scenario.target_countries, rationale="Compare whether lower intensity changes bottleneck ranking."),
            ScenarioSuggestion(name="Higher propagation sanctions case", shock_type="war_room", target_codes=result.scenario.target_countries, rationale="Stress-test countermeasure and financial-settlement propagation."),
        ],
        disclaimer=WAR_ROOM_DISCLAIMER,
    )
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


def _chain_pressure(result: WarRoomRun, key: str) -> float:
    return next((chain.pressure_score for chain in result.supply_chains if chain.key == key), 0.0)


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
