from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.services import data_sources
from app.services.plugin_sdk import (
    build_plugin_input,
    canonical_hash,
    verify_stored_plugin_output,
)
from app.services.plugin_sdk.builtins import (
    FredConnector,
    NoaaNasaConnector,
    WorldBankConnector,
    built_in_data_connector_registry,
)
from app.services.plugin_sdk.builtins.data_connectors import (
    TimeSeriesConnectorOutputV1,
)


CONNECTOR_CASES = (
    (FredConnector, "SP500", "FRED:SP500"),
    (WorldBankConnector, "GOLD", "World Bank Pink Sheet:GOLD"),
    (NoaaNasaConnector, "nasa_temperature", "NASA GISTEMP"),
)


def _request_payload(dataset: str) -> dict:
    return {
        "schema_version": "timeseries-connector-request.v1",
        "dataset": dataset,
        "start_date": "2026-08-03",
        "end_date": "2026-08-07",
        "cutoff_at": "2026-08-09T00:00:00+00:00",
    }


@pytest.mark.parametrize(("connector_type", "dataset", "source_name"), CONNECTOR_CASES)
def test_three_builtin_connectors_emit_closed_lineage(
    monkeypatch,
    connector_type,
    dataset: str,
    source_name: str,
) -> None:
    connector = connector_type()

    def fake_loader(selected: str, dates: pd.DatetimeIndex):
        assert selected == dataset
        return pd.Series(range(1, len(dates) + 1), dtype="float64"), source_name

    monkeypatch.setattr(connector_type, "loader", staticmethod(fake_loader))
    envelope = build_plugin_input(
        connector.manifest,
        _request_payload(dataset),
        organization_id="org_default",
        run_id="run_connector_contract",
    )
    stored = connector.execute(envelope)
    output = TimeSeriesConnectorOutputV1.model_validate(stored.payload)

    assert stored.provider_calls == 0
    assert output.source.source_name == source_name
    assert output.source.plugin_id == connector.manifest.plugin_id
    assert output.source.plugin_manifest_hash == connector.manifest.manifest_hash
    assert (
        output.source.plugin_configuration_hash
        == connector.manifest.configuration_hash
    )
    records = [item.model_dump(mode="json") for item in output.observations]
    assert output.source.content_hash == canonical_hash(records)
    assert output.source.observed_at == date(2026, 8, 7)
    assert verify_stored_plugin_output(
        connector.manifest,
        stored,
        require_provider_free=True,
    ) == stored


def test_builtin_registry_contains_three_real_connector_manifests() -> None:
    manifests = built_in_data_connector_registry().list_manifests()
    assert [item.plugin_id for item in manifests] == [
        "connector.fred",
        "connector.noaa_nasa",
        "connector.world_bank",
    ]
    assert all(item.kind == "connector" for item in manifests)
    assert all(item.permissions == ("network.read",) for item in manifests)
    assert all("timeseries.extract" in item.capabilities for item in manifests)
    assert all(item.verify_hash() == item for item in manifests)


def test_connector_input_cannot_override_url_or_cutoff(monkeypatch) -> None:
    connector = FredConnector()
    called = {"count": 0}

    def forbidden_loader(_selected: str, _dates: pd.DatetimeIndex):
        called["count"] += 1
        raise AssertionError("invalid connector input must fail before loading")

    monkeypatch.setattr(FredConnector, "loader", staticmethod(forbidden_loader))
    url_payload = {
        **_request_payload("SP500"),
        "url": "http://169.254.169.254/latest/meta-data",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        connector.execute(build_plugin_input(connector.manifest, url_payload))

    cutoff_payload = {
        **_request_payload("SP500"),
        "cutoff_at": "2026-08-06T00:00:00+00:00",
    }
    with pytest.raises(ValidationError, match="exceeds cutoff_at"):
        connector.execute(build_plugin_input(connector.manifest, cutoff_payload))

    unknown_payload = {**_request_payload("SP500"), "dataset": "CALLER_URL"}
    with pytest.raises(ValueError, match="not allowlisted"):
        connector.execute(build_plugin_input(connector.manifest, unknown_payload))
    assert called["count"] == 0


def test_connector_failure_is_single_attempt_and_stored_replay_uses_no_loader(
    monkeypatch,
) -> None:
    connector = FredConnector()
    calls = {"count": 0}

    def failing_loader(_selected: str, _dates: pd.DatetimeIndex):
        calls["count"] += 1
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(FredConnector, "loader", staticmethod(failing_loader))
    envelope = build_plugin_input(connector.manifest, _request_payload("SP500"))
    with pytest.raises(RuntimeError, match="source unavailable"):
        connector.execute(envelope)
    assert calls["count"] == 1

    def successful_loader(_selected: str, dates: pd.DatetimeIndex):
        return pd.Series([1.0] * len(dates)), "FRED:SP500"

    monkeypatch.setattr(FredConnector, "loader", staticmethod(successful_loader))
    stored = connector.execute(envelope)
    monkeypatch.setattr(FredConnector, "loader", staticmethod(failing_loader))
    assert verify_stored_plugin_output(
        connector.manifest,
        stored,
        require_provider_free=True,
    ) == stored
    assert calls["count"] == 1

    tampered = stored.model_copy(
        update={"payload": {**stored.payload, "observations": []}}
    )
    with pytest.raises(ValueError, match="payload hash mismatch"):
        verify_stored_plugin_output(connector.manifest, tampered)


def test_fred_compatibility_reader_preserves_cache_and_fixed_timeout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    calls: list[tuple[str, int]] = []

    class Response:
        text = (
            "observation_date,SP500\n"
            "2026-08-03,100\n"
            "2026-08-04,101\n"
            "2026-08-05,102\n"
            "2026-08-06,103\n"
            "2026-08-07,104\n"
        )

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_get(url: str, *, timeout: int):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(data_sources.requests, "get", fake_get)
    dates = pd.bdate_range("2026-08-03", "2026-08-07")
    first, first_source = data_sources.read_fred_series("SP500", dates)
    second, second_source = data_sources.read_fred_series("SP500", dates)

    assert first.tolist() == second.tolist() == [100, 101, 102, 103, 104]
    assert first_source == second_source == "FRED:SP500"
    assert calls == [(f"{data_sources.FRED_CSV_URL}?id=SP500", 30)]
    assert (tmp_path / "fred_SP500.csv").exists()
