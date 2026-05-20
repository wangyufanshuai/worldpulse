from app.services.report import render_report
from app.services.risk_engine import build_latest_risk, build_replay, build_risk_history
from app.services.species_service import list_species_presets


def test_latest_risk_has_valid_score():
    risk = build_latest_risk()
    assert 0 <= risk.score <= 100
    assert risk.level in {"low", "medium", "high", "extreme"}
    assert risk.display_level in {"低风险", "中等风险", "高风险", "极高风险"}
    assert len(risk.components) == 5


def test_history_has_points():
    points, sources = build_risk_history(days=90)
    assert len(points) > 20
    assert sources
    assert all(0 <= point.score <= 100 for point in points)
    assert all(0 <= point.macro <= 100 for point in points)


def test_report_renders_markdown():
    markdown = render_report()
    assert "# WorldPulse 全球综合风险报告" in markdown
    assert "## 分项风险" in markdown


def test_species_presets_include_land_and_ocean_sources():
    presets = list_species_presets()
    assert any(item.source == "gbif" and item.region == "africa" for item in presets)
    assert any(item.source == "obis" and item.region == "ocean" for item in presets)


def test_replay_contains_assets_and_components():
    replay = build_replay(window_days=60)
    assert replay.history
    assert replay.components
    assert replay.assets
    assert replay.start_date <= replay.end_date
