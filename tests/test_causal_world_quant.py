from fastapi.testclient import TestClient

from app.main import app
from app.services import event_digest


def _fake_gdelt_count(query: str, window_days: int) -> int:
    return max(5, len(query) % 31 + window_days)


def test_causal_events_and_graph_contract(monkeypatch):
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    events_response = client.get("/api/causal/events?window_days=7&region=global")
    graph_response = client.get("/api/causal/graph?window_days=7&region=global&event_type=conflict")

    assert events_response.status_code == 200
    events = events_response.json()
    assert events
    assert {"event_type", "intensity", "confidence", "source"} <= set(events[0])
    assert graph_response.status_code == 200
    graph = graph_response.json()
    assert graph["nodes"]
    assert graph["edges"]
    assert graph["confidence"] > 0


def test_causal_backtest_contains_error_attribution(monkeypatch):
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.get("/api/causal/backtest?event_type=energy&window_days=120&horizon_days=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sample_count"] > 0
    assert 0 <= payload["hit_rate"] <= 1
    assert payload["impacts"]
    assert payload["similar_events"]
    assert payload["error_attribution"]


def test_causal_analysis_uses_local_explanation_without_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.post(
        "/api/causal/analyze",
        json={"event_type": "conflict", "region": "global", "window_days": 7, "horizon_days": 10, "use_ai": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"]
    assert payload["chains"]
    assert payload["impacts"]
    assert payload["reasoning_path"]
    assert "本地解释" in payload["ai_explanation"]
    assert "不构成" in payload["disclaimer"]


def test_causal_report_export(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.post(
        "/api/causal/report/export",
        json={"event_type": "trade", "region": "global", "window_days": 7, "horizon_days": 10, "use_ai": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"].endswith(".md")
    assert "CausalWorldQuant" in payload["markdown"]


def test_causal_ai_smoke_test_without_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.post("/api/causal/ai-smoke-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["live"] is False
    assert payload["explanation_preview"]
