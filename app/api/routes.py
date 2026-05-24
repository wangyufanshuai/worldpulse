from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.core.models import (
    AIAnalysisRequest,
    AIAnalysisResult,
    CausalAnalysisRequest,
    CausalAnalysisResult,
    CausalBacktestResult,
    CausalChain,
    CausalEvent,
    CompositeRisk,
    CountryAgent,
    EventDigest,
    ReplayResult,
    ReportExport,
    ReportTemplate,
    RiskAnalysis,
    RiskOverview,
    RiskPoint,
    SimulationRequest,
    SimulationAgentDetail,
    SimulationDataHealth,
    SimulationResult,
    SimulationScenario,
    SpeciesPreset,
    SpeciesProfile,
    WorkbenchStatus,
)
from app.services.ai_analysis import analyze_current_risk, analyze_simulation, export_ai_report
from app.services.ai_client import ai_smoke_test, ai_status
from app.services.causal_analysis import analyze_causal_world, causal_ai_smoke_test, export_causal_report
from app.services.causal_backtest import run_causal_backtest
from app.services.causal_data import build_causal_events, select_event
from app.services.causal_graph import build_causal_chain
from app.services.event_digest import build_agent_event_digest, build_event_digest
from app.services.exports import alerts_csv, indicators_csv, replay_csv, risk_history_csv, species_occurrences_csv
from app.services.report import export_report, render_report
from app.services.risk_engine import build_latest_risk, build_replay, build_risk_analysis, build_risk_history, build_risk_overview
from app.services.simulation_engine import list_agents, list_scenarios, run_simulation
from app.services.simulation_data import agent_state_explanations, get_country_agent
from app.services.simulation_health import build_simulation_data_health
from app.services.species_service import build_species_profile, list_species_presets
from app.services.workbench import build_workbench_status, render_analysis_report, render_system_report, report_templates

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "worldpulse"}


@router.get("/risk/latest", response_model=CompositeRisk)
def latest_risk() -> CompositeRisk:
    return build_latest_risk()


@router.get("/risk/overview", response_model=RiskOverview)
def risk_overview() -> RiskOverview:
    return build_risk_overview()


@router.get("/risk/history", response_model=list[RiskPoint])
def risk_history() -> list[RiskPoint]:
    points, _sources = build_risk_history()
    return points


@router.get("/risk/analysis", response_model=RiskAnalysis)
def risk_analysis() -> RiskAnalysis:
    return build_risk_analysis()


@router.get("/risk/replay", response_model=ReplayResult)
def risk_replay(window_days: int = 120) -> ReplayResult:
    return build_replay(window_days=window_days)


@router.get("/workbench/status", response_model=WorkbenchStatus)
def workbench_status() -> WorkbenchStatus:
    return build_workbench_status()


@router.get("/reports/templates", response_model=list[ReportTemplate])
def reports_templates() -> list[ReportTemplate]:
    return report_templates()


@router.get("/ai/status")
def ai_service_status() -> dict:
    return ai_status()


@router.post("/ai/smoke-test")
def ai_service_smoke_test() -> dict:
    return ai_smoke_test()


@router.post("/ai/analyze-risk", response_model=AIAnalysisResult)
def ai_analyze_risk(request: AIAnalysisRequest) -> AIAnalysisResult:
    return analyze_current_risk(request)


@router.post("/ai/analyze-simulation", response_model=AIAnalysisResult)
def ai_analyze_simulation(request: AIAnalysisRequest) -> AIAnalysisResult:
    return analyze_simulation(request)


@router.post("/ai/report/export", response_model=ReportExport)
def ai_report_export(request: AIAnalysisRequest) -> ReportExport:
    return export_ai_report(request)


@router.get("/events/digest", response_model=EventDigest)
def events_digest(window_days: int = 30, region: str = "global") -> EventDigest:
    return build_event_digest(window_days=window_days, region=region)


@router.get("/events/agent/{code}", response_model=EventDigest)
def events_agent_digest(code: str, window_days: int = 30) -> EventDigest:
    return build_agent_event_digest(code=code, window_days=window_days)


@router.get("/causal/events", response_model=list[CausalEvent])
def causal_events(window_days: int = 30, region: str = "global") -> list[CausalEvent]:
    return build_causal_events(window_days=window_days, region=region)


@router.get("/causal/graph", response_model=CausalChain)
def causal_graph(window_days: int = 30, region: str = "global", event_type: str | None = None) -> CausalChain:
    events = build_causal_events(window_days=window_days, region=region)
    return build_causal_chain(select_event(events, event_type))


@router.post("/causal/analyze", response_model=CausalAnalysisResult)
def causal_analyze(request: CausalAnalysisRequest) -> CausalAnalysisResult:
    return analyze_causal_world(request)


@router.get("/causal/backtest", response_model=CausalBacktestResult)
def causal_backtest(event_type: str = "conflict", window_days: int = 120, horizon_days: int = 20) -> CausalBacktestResult:
    return run_causal_backtest(event_type=event_type, window_days=window_days, horizon_days=horizon_days)


@router.post("/causal/report/export", response_model=ReportExport)
def causal_report_export(request: CausalAnalysisRequest) -> ReportExport:
    return export_causal_report(request)


@router.post("/causal/ai-smoke-test")
def causal_ai_service_smoke_test() -> dict:
    return causal_ai_smoke_test()


@router.get("/simulation/agents", response_model=list[CountryAgent])
def simulation_agents() -> list[CountryAgent]:
    return list_agents()


@router.get("/simulation/scenarios", response_model=list[SimulationScenario])
def simulation_scenario_templates() -> list[SimulationScenario]:
    return list_scenarios()


@router.get("/simulation/data-health", response_model=list[SimulationDataHealth])
def simulation_data_health() -> list[SimulationDataHealth]:
    return build_simulation_data_health()


@router.get("/simulation/agent/{code}", response_model=SimulationAgentDetail)
def simulation_agent_detail(code: str) -> SimulationAgentDetail:
    agent = get_country_agent(code)
    if agent is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Unknown agent code: {code}")
    return SimulationAgentDetail(
        agent=agent,
        state_explanations=agent_state_explanations(agent),
        source_breakdown=agent.source_breakdown,
        fallback_fields=agent.fallback_fields,
        raw_indicators=agent.raw_indicators,
    )


@router.post("/simulation/run", response_model=SimulationResult)
def simulation_run(request: SimulationRequest) -> SimulationResult:
    return run_simulation(request)


@router.get("/exports/risk-history.csv")
def export_risk_history_csv() -> Response:
    return _csv_response(risk_history_csv(), "worldpulse_risk_history.csv")


@router.get("/exports/indicators.csv")
def export_indicators_csv() -> Response:
    return _csv_response(indicators_csv(), "worldpulse_indicators.csv")


@router.get("/exports/alerts.csv")
def export_alerts_csv() -> Response:
    return _csv_response(alerts_csv(), "worldpulse_alerts.csv")


@router.get("/exports/replay.csv")
def export_replay_csv(window_days: int = 120) -> Response:
    return _csv_response(replay_csv(window_days=window_days), f"worldpulse_replay_{window_days}d.csv")


@router.get("/exports/species-occurrences.csv")
def export_species_occurrences_csv(scientific_name: str, source: str = "gbif", region: str = "africa", limit: int = 240) -> Response:
    return _csv_response(
        species_occurrences_csv(scientific_name=scientific_name, source=source, region=region, limit=limit),
        "worldpulse_species_occurrences.csv",
    )


@router.get("/species/presets", response_model=list[SpeciesPreset])
def species_presets() -> list[SpeciesPreset]:
    return list_species_presets()


@router.get("/species/profile", response_model=SpeciesProfile)
def species_profile(scientific_name: str, source: str = "gbif", region: str = "africa", limit: int = 240) -> SpeciesProfile:
    return build_species_profile(scientific_name=scientific_name, source=source, region=region, limit=limit)


@router.get("/report.md", response_class=PlainTextResponse)
def report_markdown() -> str:
    return render_report()


@router.get("/report/analysis.md", response_class=PlainTextResponse)
def report_analysis_markdown() -> str:
    return render_analysis_report()


@router.get("/report/system.md", response_class=PlainTextResponse)
def report_system_markdown() -> str:
    return render_system_report()


@router.post("/report/export", response_model=ReportExport)
def save_report() -> ReportExport:
    path, markdown = export_report()
    return ReportExport(path=str(path), markdown=markdown)


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
