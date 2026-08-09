from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from app.core.models import AIAnalysisResult, ReportCitation
from app.main import app
from app.services import project_store
from app.services.plugin_sdk import build_plugin_input, canonical_hash
from app.services.plugin_sdk.builtins.report_renderer import (
    MarkdownRenderOutputV1,
    ReportRendererAdapter,
    build_renderer_lineage,
    verify_renderer_lineage,
)
from app.services.project_app.replay_application import (
    verify_replay_pack_plugin_lineage,
)
from app.services.project_app.repository import report_for_run
from app.services.project_app.reports import render_project_markdown
from app.services.project_store import connect, dumps


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "worldpulse_plugin_renderer_test.db",
    )
    return TestClient(app)


def _analysis() -> AIAnalysisResult:
    return AIAnalysisResult(
        enabled=False,
        mode="test",
        title="中文研究报告",
        summary="区分事实证据、确定性推导、Agent 观察与不确定性。",
        key_findings=["确定性引擎仍是数值唯一权威。"],
        evidence=[],
        uncertainties=["这是情景推演，不是对未来的确定性预测。"],
        watch_signals=[],
        scenario_suggestions=[],
        disclaimer="不构成投资、政治或安全决策建议。",
    )


def _citation() -> ReportCitation:
    return ReportCitation(
        citation_id="E1",
        finding_index=0,
        kind="evidence",
        target_id="evidence:test",
        title="测试证据",
        summary="本地确定性测试证据。",
        source="WorldPulse tests",
        confidence=100.0,
    )


def _create_project_run(client: TestClient) -> tuple[str, str, dict]:
    created = client.post(
        "/api/projects",
        json={
            "title": "Renderer 中文兼容研究",
            "question": "报告渲染插件是否保持现有中文语义？",
            "event_types": ["conflict"],
        },
    )
    assert created.status_code == 200
    project_id = created.json()["project_id"]
    completed = client.post(f"/api/projects/{project_id}/run?mode=fast")
    assert completed.status_code == 200
    payload = completed.json()
    return project_id, payload["latest_run"]["run_id"], payload


def _create_war_room_run(client: TestClient) -> tuple[str, str, dict]:
    created = client.post(
        "/api/projects",
        json={
            "title": "Renderer Replay 中文兼容研究",
            "question": "Replay Renderer lineage 是否可离线验证？",
            "mode": "war_room",
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    assert created.status_code == 200
    project_id = created.json()["project_id"]
    completed = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={
            "scenario_key": "strait_blockade_30d",
            "duration_days": 30,
            "intensity": 0.7,
            "propagation": 0.45,
        },
    )
    assert completed.status_code == 200
    payload = completed.json()
    return project_id, payload["latest_run"]["run_id"], payload


def test_report_renderer_is_byte_identical_to_existing_markdown_renderer():
    analysis = _analysis()
    citations = [_citation()]
    expected = render_project_markdown(analysis, citations)
    renderer = ReportRendererAdapter(project_renderer=render_project_markdown)
    request = build_plugin_input(
        renderer.manifest,
        {
            "schema_version": "markdown-render-request.v1",
            "render_kind": "project_report",
            "payload": {
                "project_id": "project_test",
                "run_id": "run_test",
                "analysis": analysis.model_dump(mode="json"),
                "citations": [item.model_dump(mode="json") for item in citations],
            },
        },
        run_id="run_test",
    )

    stored = renderer.execute(request)
    rendered = MarkdownRenderOutputV1.model_validate(stored.payload)
    lineage = build_renderer_lineage(renderer.manifest, request, stored)

    assert rendered.markdown == expected
    assert rendered.content_hash == canonical_hash(expected)
    assert stored.provider_calls == 0
    assert verify_renderer_lineage(
        lineage,
        expected,
        render_kind="project_report",
    ) == lineage


def test_project_report_persists_matching_citation_and_run_lineage(client):
    project_id, run_id, payload = _create_project_run(client)
    report = payload["report"]
    citations = [
        item
        for item in report["citations"]
        if item["kind"] == "plugin_manifest"
    ]

    assert len(citations) == 1
    citation_lineage = json.loads(citations[0]["summary"])
    run_lineage = payload["latest_run"]["data_snapshot"]["plugin_lineage"]
    assert run_lineage["report_renderer"] == citation_lineage
    assert citation_lineage["provider_calls"] == 0
    assert "Renderer 中文兼容研究" in report["markdown"]
    assert report_for_run(project_id, run_id) is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("markdown", "content hash mismatch"),
        ("duplicate", "duplicate Renderer lineage"),
        ("malformed", "lineage citation is malformed"),
        ("missing", "lineage citation is missing"),
    ],
)
def test_project_report_read_fails_closed_on_renderer_lineage_tampering(
    client,
    mutation,
    message,
):
    project_id, run_id, payload = _create_project_run(client)
    citations = payload["report"]["citations"]
    plugin_citation = next(
        item for item in citations if item["kind"] == "plugin_manifest"
    )
    with connect() as connection:
        if mutation == "markdown":
            connection.execute(
                "UPDATE ai_reports SET markdown = markdown || ? WHERE run_id = ?",
                ("\n篡改", run_id),
            )
        else:
            altered = list(citations)
            if mutation == "duplicate":
                altered.append(deepcopy(plugin_citation))
            elif mutation == "malformed":
                altered = [
                    {
                        **item,
                        "summary": "{not-json",
                    }
                    if item["kind"] == "plugin_manifest"
                    else item
                    for item in altered
                ]
            else:
                altered = [
                    item for item in altered if item["kind"] != "plugin_manifest"
                ]
            connection.execute(
                "UPDATE ai_reports SET citations = ? WHERE run_id = ?",
                (dumps(altered), run_id),
            )

    with pytest.raises(ValueError, match=message):
        report_for_run(project_id, run_id)


def test_legacy_report_without_renderer_lineage_remains_readable(client):
    project_id, run_id, payload = _create_project_run(client)
    legacy_citations = [
        item
        for item in payload["report"]["citations"]
        if item["kind"] != "plugin_manifest"
    ]
    with connect() as connection:
        row = connection.execute(
            "SELECT data_snapshot FROM research_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        run_data = json.loads(row["data_snapshot"])
        run_data.pop("plugin_lineage", None)
        connection.execute(
            "UPDATE research_runs SET data_snapshot = ? WHERE run_id = ?",
            (dumps(run_data), run_id),
        )
        connection.execute(
            "UPDATE ai_reports SET citations = ? WHERE run_id = ?",
            (dumps(legacy_citations), run_id),
        )

    report = report_for_run(project_id, run_id)
    assert report is not None
    assert all(item.kind != "plugin_manifest" for item in report.citations)


def test_replay_pack_binds_report_and_replay_renderer_lineage(client, monkeypatch):
    project_id, run_id, payload = _create_war_room_run(client)
    replay_response = client.get(
        f"/api/projects/{project_id}/war-room/replay-pack",
        params={"run_id": run_id},
    )
    assert replay_response.status_code == 200
    replay = replay_response.json()
    lineage = replay["manifest"]["plugin_lineage"]

    assert lineage["report_renderer"] == (
        payload["latest_run"]["data_snapshot"]["plugin_lineage"][
            "report_renderer"
        ]
    )
    assert lineage["replay_renderer"]["provider_calls"] == 0
    assert replay["manifest"]["manifest_hash"]
    assert "策略沙盘" in replay["markdown"]
    assert verify_replay_pack_plugin_lineage(
        replay["manifest"],
        replay["markdown"],
    ) == replay["manifest"]

    monkeypatch.setattr(
        ReportRendererAdapter,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stored verification must not execute a Renderer")
        ),
    )
    verify_replay_pack_plugin_lineage(replay["manifest"], replay["markdown"])


def test_war_room_renderer_hashes_the_complete_trust_manifest(client, monkeypatch):
    from app.services.project_app import war_room_persistence

    monkeypatch.setattr(
        war_room_persistence,
        "trust_manifest_for_job",
        lambda _job_id: {
            "rule_pack_version": "1.2.3",
            "rule_pack_id": "rule_pack_test",
            "rule_pack_hash": "a" * 64,
        },
    )
    project_id, run_id, payload = _create_war_room_run(client)

    assert "## Trust Manifest" in payload["report"]["markdown"]
    assert "`rule_pack_test`" in payload["report"]["markdown"]
    assert report_for_run(project_id, run_id) is not None


def test_replay_pack_verifier_fails_closed_on_manifest_or_renderer_tampering(client):
    project_id, run_id, _payload = _create_war_room_run(client)
    replay = client.get(
        f"/api/projects/{project_id}/war-room/replay-pack",
        params={"run_id": run_id},
    ).json()

    with pytest.raises(ValueError, match="content hash mismatch"):
        verify_replay_pack_plugin_lineage(
            replay["manifest"],
            replay["markdown"] + "\n篡改",
        )

    bad_manifest = deepcopy(replay["manifest"])
    bad_manifest["manifest_hash"] = "0" * 64
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        verify_replay_pack_plugin_lineage(bad_manifest, replay["markdown"])

    bad_lineage = deepcopy(replay["manifest"])
    bad_lineage["plugin_lineage"]["replay_renderer"]["provider_calls"] = 1
    bad_lineage["manifest_hash"] = canonical_hash(
        {
            key: value
            for key, value in bad_lineage.items()
            if key != "manifest_hash"
        }
    )
    with pytest.raises(ValueError, match="lineage identity mismatch"):
        verify_replay_pack_plugin_lineage(bad_lineage, replay["markdown"])
