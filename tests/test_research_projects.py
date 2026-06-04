from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.models import (
    AIAnalysisResult,
    CausalBacktestResult,
    CausalChain,
    CausalEvent,
    CausalGraphEdge,
    CausalGraphNode,
    CompositeRisk,
    EvidenceItem,
    MarketImpact,
    RiskComponent,
    RiskOverview,
    RiskPoint,
    ScenarioSuggestion,
    SimulationDriver,
    SimulationMapPoint,
    SimulationPathPoint,
    SimulationPropagationEdge,
    SimulationResult,
    WatchSignal,
)
from app.main import app
from app.services import project_store, projects


def _setup_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "worldpulse_test.db")


def _fake_risk_overview():
    component = RiskComponent(
        key="geopolitical",
        name="geopolitical",
        display_name="地缘压力",
        score=62,
        weight=0.25,
        trend="up",
        display_trend="上升",
        source="test",
        drivers=["冲突事件升温"],
    )
    latest = CompositeRisk(
        date="2026-06-04",
        score=61.5,
        level="medium",
        display_level="中等风险",
        trend="up",
        display_trend="上升",
        forecast_30d=58,
        forecast_label="uncertain",
        display_forecast_label="方向不明确",
        components=[component],
        summary="测试风险摘要",
    )
    return RiskOverview(
        latest=latest,
        history=[RiskPoint(date="2026-06-04", score=61.5, financial=55, climate=48, geopolitical=62, ecology=40, macro=52)],
    )


def _fake_events():
    return [
        CausalEvent(
            event_type="conflict",
            name="冲突升级",
            region="global",
            window_days=30,
            intensity=64,
            event_count=120,
            source="mock GDELT",
            summary="冲突相关新闻热度上升",
            confidence=72,
        )
    ]


def _fake_chain(event):
    return CausalChain(
        event_type=event.event_type,
        title="冲突升级因果链",
        nodes=[
            CausalGraphNode(id="event", label="冲突升级", kind="event", score=64),
            CausalGraphNode(id="oil", label="原油风险溢价", kind="commodity", score=54),
            CausalGraphNode(id="risk", label="全球风险偏好", kind="macro", score=52),
        ],
        edges=[
            CausalGraphEdge(source="event", target="oil", relation="供应中断预期", weight=0.82, confidence=78, explanation="冲突推高能源风险溢价。"),
            CausalGraphEdge(source="oil", target="risk", relation="通胀与避险传导", weight=0.65, confidence=68, explanation="油价和避险情绪传导到风险资产。"),
        ],
        confidence=74,
        explanation="测试因果链解释",
    )


def _fake_backtest(event_type="conflict", window_days=120, horizon_days=20):
    return CausalBacktestResult(
        event_type=event_type,
        window_days=window_days,
        sample_count=12,
        hit_rate=0.67,
        average_impact=1.2,
        max_error=2.4,
        impacts=[MarketImpact(asset_key="oil", asset_name="WTI 原油", direction="up", expected_return_pct=1.8, confidence=70, rationale="测试影响")],
        similar_events=[],
        error_attribution=["样本重叠", "市场可能提前定价"],
    )


def _fake_simulation(_request):
    return SimulationResult(
        summary="测试模拟摘要",
        horizon_months=12,
        runs=180,
        global_path=[SimulationPathPoint(month=1, p10=40, p50=52, p90=66)],
        countries=[],
        map_points=[SimulationMapPoint(code="USA", name="United States", latitude=38, longitude=-97, risk=52, uncertainty=12, region="North America")],
        propagation_edges=[SimulationPropagationEdge(source="USA", target="EU", channel="financial", weight=0.4, impact=2.2)],
        drivers=[SimulationDriver(name="能源冲击", contribution=3.2, explanation="测试驱动")],
    )


def _fake_ai(_request):
    return AIAnalysisResult(
        enabled=True,
        mode="mock",
        title="测试报告",
        summary="测试 AI 摘要",
        key_findings=["结论一"],
        evidence=[EvidenceItem(title="证据", source="mock", value="1", interpretation="测试证据")],
        uncertainties=["不确定性"],
        watch_signals=[WatchSignal(name="信号", direction="上升", why_it_matters="重要", current_status="观察")],
        scenario_suggestions=[ScenarioSuggestion(name="情景", shock_type="energy", target_codes=["EU"], rationale="测试情景")],
        disclaimer="不构成建议",
    )


def _patch_project_dependencies(monkeypatch):
    monkeypatch.setattr(projects, "build_risk_overview", _fake_risk_overview)
    monkeypatch.setattr(projects, "build_causal_events", lambda window_days, region: _fake_events())
    monkeypatch.setattr(projects, "build_causal_chain", _fake_chain)
    monkeypatch.setattr(projects, "run_causal_backtest", _fake_backtest)
    monkeypatch.setattr(projects, "run_simulation", _fake_simulation)
    monkeypatch.setattr(projects, "analyze_current_risk", _fake_ai)
    monkeypatch.setattr(
        projects,
        "analyze_causal_world",
        lambda request: SimpleNamespace(chains=[_fake_chain(_fake_events()[0])]),
    )


def test_project_api_lifecycle(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    _patch_project_dependencies(monkeypatch)
    client = TestClient(app)

    created = client.post(
        "/api/projects",
        json={"title": "能源冲击研究", "question": "能源冲击如何影响纳指？", "region": "global"},
    )
    assert created.status_code == 200
    project_id = created.json()["project_id"]

    assert client.get("/api/projects").json()[0]["project_id"] == project_id

    run = client.post(f"/api/projects/{project_id}/run")
    assert run.status_code == 200
    detail = run.json()
    assert detail["latest_run"]["status"] == "completed"
    assert len(detail["runs"]) == 1
    assert detail["graph"]["nodes"]
    assert detail["graph"]["edges"][0]["evidence"]
    assert detail["report"]["key_findings"]
    first_run_id = detail["latest_run"]["run_id"]

    second_run = client.post(f"/api/projects/{project_id}/run?mode=fast")
    assert second_run.status_code == 200
    second_detail = second_run.json()
    assert len(second_detail["runs"]) == 2

    runs = client.get(f"/api/projects/{project_id}/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 2

    historical = client.get(f"/api/projects/{project_id}/runs/{first_run_id}")
    assert historical.status_code == 200
    assert historical.json()["latest_run"]["run_id"] == first_run_id
    assert historical.json()["graph"]["run_id"] == first_run_id
    assert historical.json()["report"]["run_id"] == first_run_id

    latest_run_id = second_detail["latest_run"]["run_id"]
    diff = client.get(
        f"/api/projects/{project_id}/runs/compare",
        params={"base_run_id": first_run_id, "target_run_id": latest_run_id},
    )
    assert diff.status_code == 200
    assert diff.json()["base_run_id"] == first_run_id
    assert "changed_metrics" in diff.json()

    graph_payload = second_detail["graph"]
    graph_payload["nodes"][0]["label"] = "人工校正冲突事件"
    graph_payload["confidence"] = 81
    edited = client.patch(
        f"/api/projects/{project_id}/graph",
        json={
            "run_id": latest_run_id,
            "nodes": graph_payload["nodes"],
            "edges": graph_payload["edges"],
            "confidence": graph_payload["confidence"],
            "evidence_sources": graph_payload["evidence_sources"],
            "note": "测试校正",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["graph"]["nodes"][0]["label"] == "人工校正冲突事件"
    assert edited.json()["graph"]["confidence"] == 81
    assert "Manual analyst edit" in edited.json()["graph"]["evidence_sources"]

    invalid = client.patch(
        f"/api/projects/{project_id}/graph",
        json={
            "run_id": latest_run_id,
            "nodes": graph_payload["nodes"],
            "edges": [{"source": "missing", "target": "event", "relation": "bad"}],
        },
    )
    assert invalid.status_code == 422

    graph = client.get(f"/api/projects/{project_id}/graph")
    assert graph.status_code == 200
    assert graph.json()["confidence"] > 0

    report = client.get(f"/api/projects/{project_id}/report")
    assert report.status_code == 200
    assert "markdown" in report.json()


def test_project_chat_uses_stored_context(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    _patch_project_dependencies(monkeypatch)

    def fake_structured(prompt, context):
        assert context["research_project_chat"]["project"]["title"] == "追问测试"
        return AIAnalysisResult(
            enabled=True,
            mode="mock",
            title="追问回答",
            summary="基于证据链，最弱环节是事件到资产的时间滞后。",
            key_findings=["需要观察油价", "需要检查反例"],
            evidence=[],
            uncertainties=[],
            watch_signals=[],
            scenario_suggestions=[],
            disclaimer="不构成建议",
        )

    monkeypatch.setattr(projects, "request_structured_analysis", fake_structured)
    client = TestClient(app)

    project_id = client.post("/api/projects", json={"title": "追问测试", "question": "哪里最弱？"}).json()["project_id"]
    client.post(f"/api/projects/{project_id}/run")
    response = client.post(f"/api/projects/{project_id}/chat", json={"message": "证据链最弱在哪里？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "assistant"
    assert "最弱环节" in payload["content"]

    detail = client.get(f"/api/projects/{project_id}").json()
    assert len(detail["chat_messages"]) == 2
