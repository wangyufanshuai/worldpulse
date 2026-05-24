from fastapi.testclient import TestClient

from app.main import app
from app.services import event_digest, llm_client
from app.services.llm_client import LLMMessage, extract_json


def _fake_gdelt_count(query: str, window_days: int) -> int:
    return max(1, len(query) % 25 + window_days)


def _mock_response(payload):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    return Response()


def test_ai_status_disabled_without_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/api/ai/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["provider"] == "siliconflow"
    assert payload["fallback_provider"] == "deepseek"


def test_ai_status_enabled_with_siliconflow_key(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(app)

    payload = client.get("/api/ai/status").json()

    assert payload["enabled"] is True
    assert payload["provider"] == "siliconflow"
    assert payload["provider_enabled"] is True


def test_llm_json_parses_plain_and_fenced_json():
    assert extract_json('{"title":"ok"}') == {"title": "ok"}
    assert extract_json('```json\n{"title":"ok"}\n```') == {"title": "ok"}


def test_llm_falls_back_to_deepseek_when_primary_fails(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")

    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "siliconflow" in url:
            raise RuntimeError("primary failed")
        return _mock_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"ok","summary":"s","key_findings":[],"evidence":[],"uncertainties":[],"watch_signals":[],"scenario_suggestions":[],"disclaimer":"d"}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)

    result = llm_client.call_llm_json([LLMMessage(role="user", content="x")], {"required": ["title", "summary"]})

    assert result.enabled is True
    assert result.provider == "deepseek"
    assert any("siliconflow" in url for url in calls)
    assert any("deepseek" in url for url in calls)


def test_llm_uses_reasoning_content_when_content_empty(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")

    def fake_post(url, **kwargs):
        return _mock_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": '{"title":"ok","summary":"from reasoning"}',
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)

    result = llm_client.call_llm_json([LLMMessage(role="user", content="json")], {"required": ["title", "summary"]})

    assert result.enabled is True
    assert result.provider == "deepseek"
    assert "from reasoning" in result.content


def test_llm_retries_without_json_mode_when_content_empty(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return _mock_response({"choices": [{"message": {"content": ""}}]})
        return _mock_response({"choices": [{"message": {"content": '{"title":"ok","summary":"retry"}'}}]})

    monkeypatch.setattr(llm_client.requests, "post", fake_post)

    result = llm_client.call_llm_json([LLMMessage(role="user", content="json")], {"required": ["title", "summary"]})

    assert result.enabled is True
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_ai_smoke_test_api_without_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post("/api/ai/smoke-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["error"]


def test_event_digest_contract(monkeypatch):
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.get("/api/events/digest?window_days=7&region=global")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "global"
    assert payload["window_days"] == 7
    assert payload["total_events"] > 0
    assert {topic["key"] for topic in payload["topics"]} >= {"conflict", "energy", "trade"}


def test_agent_event_digest_contract(monkeypatch):
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.get("/api/events/agent/USA?window_days=7")

    assert response.status_code == 200
    payload = response.json()
    assert "USA" in payload["scope"]
    assert payload["topics"]


def test_ai_risk_analysis_uses_local_fallback_without_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.post("/api/ai/analyze-risk", json={"focus": "global", "window_days": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["mode"] == "disabled"
    assert payload["evidence"]
    assert payload["watch_signals"]
    assert "不构成" in payload["disclaimer"]


def test_ai_report_export(monkeypatch, tmp_path):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(event_digest, "_gdelt_count", _fake_gdelt_count)
    client = TestClient(app)

    response = client.post("/api/ai/report/export", json={"focus": "global", "window_days": 7})

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"].endswith(".md")
    assert "WorldPulse AI" in payload["markdown"]
