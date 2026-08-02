from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from app.core.models import (
    CausalGraphSnapshot,
    CompositeRisk,
    ProjectDetail,
    ResearchProject,
    ResearchRun,
    RiskComponent,
    RiskOverview,
    RiskPoint,
    WarRoomRun,
)
from app.services.project_app.report_application import report_service
from app.services.project_app.reports import chain_pressure
from app.services.project_store import connect, dumps
from app.services.rule_packs import trust_manifest_for_job
from app.services.world_model import WORLD_MODEL_DISCLAIMER as WAR_ROOM_DISCLAIMER


def persist_war_room_result(
    project_id: str,
    result: WarRoomRun,
    *,
    project_loader: Callable[[str], ResearchProject],
    detail_loader: Callable[..., ProjectDetail],
    now_factory: Callable[[], str],
    run_id: str | None = None,
    started: str | None = None,
    completed: str | None = None,
    lifecycle_job_id: str | None = None,
) -> ProjectDetail:
    project = project_loader(project_id)
    started = started or now_factory()
    completed = completed or now_factory()
    run_id = run_id or f"run_{uuid4().hex[:12]}"
    workflow_events = _war_room_workflow_events(result, now_factory)
    trust_manifest = trust_manifest_for_job(lifecycle_job_id)
    risk = build_war_room_risk_overview(result)
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
            "trust_manifest": trust_manifest,
        },
        risk_snapshot=risk.model_dump(),
        event_snapshot=[build_war_room_event_snapshot(result)],
        simulation_snapshot={**build_war_room_simulation_snapshot(result), "trust_manifest": trust_manifest},
        backtest_snapshot={"event_type": result.scenario.key, "sample_count": 0, "hit_rate": 0, "max_error": 0, "error_attribution": [WAR_ROOM_DISCLAIMER]},
    )
    graph = build_war_room_graph_snapshot(project.project_id, run_id, result, now_factory)
    report = report_service.build_war_room(project, run, graph, result)

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO research_runs
            (run_id, project_id, status, started_at, completed_at, summary, data_snapshot, risk_snapshot, event_snapshot, simulation_snapshot, backtest_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id, run.project_id, run.status, run.started_at, run.completed_at, run.summary,
                dumps(run.data_snapshot), dumps(run.risk_snapshot), dumps(run.event_snapshot),
                dumps(run.simulation_snapshot), dumps(run.backtest_snapshot),
            ),
        )
        conn.execute(
            """
            INSERT INTO causal_graph_snapshots
            (graph_id, project_id, run_id, generated_at, nodes, edges, confidence, evidence_sources)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                graph.graph_id, graph.project_id, graph.run_id, graph.generated_at,
                dumps(graph.nodes), dumps(graph.edges), graph.confidence, dumps(graph.evidence_sources),
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_reports
            (report_id, project_id, run_id, generated_at, mode, title, summary, key_findings, evidence, uncertainties, watch_signals, scenario_suggestions, citations, markdown, disclaimer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id, report.project_id, report.run_id, report.generated_at, report.mode,
                report.title, report.summary, dumps(report.key_findings),
                dumps([item.model_dump() for item in report.evidence]), dumps(report.uncertainties),
                dumps([item.model_dump() for item in report.watch_signals]),
                dumps([item.model_dump() for item in report.scenario_suggestions]),
                dumps([item.model_dump() for item in report.citations]), report.markdown, report.disclaimer,
            ),
        )
        conn.execute(
            "UPDATE research_projects SET status = ?, updated_at = ?, scenario_config = ? WHERE project_id = ?",
            ("completed", completed, dumps(result.scenario.model_dump()), project.project_id),
        )
    return detail_loader(project.project_id, run_id=run_id)


def _war_room_workflow_events(result: WarRoomRun, now_factory: Callable[[], str]) -> list[dict]:
    specs = [
        ("project", "War Room scenario", "Loaded scenario parameters, country agents, supply chains, and strategy-sandbox disclaimer."),
        ("scenario", "Scenario Sandbox", f"{result.scenario.name} for {result.scenario.duration_days} days at intensity {result.scenario.intensity:.2f}."),
        ("agents", "Agent Decisions", f"Generated {len(result.agent_decisions)} deterministic country-agent decisions."),
        ("graph", "Causal Chain", f"Generated {len(result.impact_graph.nodes)} nodes and {len(result.impact_graph.edges)} causal edges."),
        ("heatmap", "Risk Heatmap", f"Generated {len(result.risk_heatmap)} country heatmap cells."),
        ("report", "War Room Report", "Generated a local strategy-sandbox report with citation hooks and disclaimer."),
    ]
    return [
        {"key": key, "title": title, "status": "completed", "detail": detail, "timestamp": now_factory()}
        for key, title, detail in specs
    ]


def build_war_room_risk_overview(result: WarRoomRun) -> RiskOverview:
    latest_score = result.timeline[-1].global_risk if result.timeline else 50.0
    component_specs = [
        ("geopolitical", "Geopolitical", latest_score, ["deterrence", "alliances", "sanctions"]),
        ("energy", "Energy", chain_pressure(result, "energy"), ["energy imports", "rerouting", "substitution"]),
        ("food", "Food", chain_pressure(result, "food"), ["food availability", "export restrictions", "social stability"]),
        ("financial", "Financial", result.timeline[-1].financial_pressure if result.timeline else 40.0, ["settlement", "liquidity", "risk appetite"]),
    ]
    components = [
        RiskComponent(key=key, name=key, display_name=name, score=round(score, 1), weight=0.25,
                      trend="up", display_trend="up", source="WorldPulse War Room", drivers=drivers)
        for key, name, score, drivers in component_specs
    ]
    return RiskOverview(
        latest=CompositeRisk(
            date=datetime.now().strftime("%Y-%m-%d"), score=round(latest_score, 1), level="scenario",
            display_level="Strategy sandbox", trend="up", display_trend="scenario stress",
            forecast_30d=round(min(95, latest_score), 1), forecast_label="sandbox",
            display_forecast_label="Not a prediction", components=components, summary=result.summary,
        ),
        history=[
            RiskPoint(date=f"D+{point.day}", score=point.global_risk, financial=point.financial_pressure,
                      climate=0, geopolitical=point.trade_pressure, ecology=point.food_pressure,
                      macro=point.energy_pressure)
            for point in result.timeline
        ],
    )


def build_war_room_event_snapshot(result: WarRoomRun) -> dict:
    return {
        "event_type": "war_room", "name": result.scenario.name, "region": "global",
        "window_days": result.scenario.duration_days, "intensity": round(result.scenario.intensity * 100, 1),
        "event_count": len(result.timeline), "source": "WorldPulse War Room deterministic sandbox",
        "summary": result.scenario.description, "confidence": result.impact_graph.confidence,
    }


def build_war_room_simulation_snapshot(result: WarRoomRun) -> dict:
    snapshot = {
        "summary": result.summary, "scenario": result.scenario.model_dump(),
        "timeline": [item.model_dump() for item in result.timeline],
        "country_agents": [item.model_dump() for item in result.country_agents],
        "supply_chains": [item.model_dump() for item in result.supply_chains],
        "risk_heatmap": [item.model_dump() for item in result.risk_heatmap],
        "agent_decisions": [item.model_dump() for item in result.agent_decisions],
        "impact_graph": result.impact_graph.model_dump(), "disclaimer": result.disclaimer,
        "assumptions": result.assumptions, "ui_state": result.ui_state,
    }
    hybrid_trace = result.ui_state.get("hybrid_trace") if isinstance(result.ui_state, dict) else None
    if hybrid_trace:
        snapshot["hybrid_trace"] = hybrid_trace
    return snapshot


def build_war_room_graph_snapshot(
    project_id: str, run_id: str, result: WarRoomRun, now_factory: Callable[[], str]
) -> CausalGraphSnapshot:
    return CausalGraphSnapshot(
        graph_id=f"graph_{uuid4().hex[:12]}", project_id=project_id, run_id=run_id,
        generated_at=now_factory(), nodes=result.impact_graph.nodes,
        edges=[
            {
                **edge,
                "evidence": ["WorldPulse deterministic War Room rules", f"Scenario intensity: {result.scenario.intensity:.2f}", WAR_ROOM_DISCLAIMER],
                "backtest": {"sample_count": 0, "hit_rate": 0, "max_error": 0},
            }
            for edge in result.impact_graph.edges
        ],
        confidence=result.impact_graph.confidence,
        evidence_sources=["WorldPulse War Room deterministic sandbox", "WorldPulse supply-chain rules", "WorldPulse country-agent rules"],
    )
