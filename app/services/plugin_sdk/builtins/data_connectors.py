"""Read-only adapters for three existing WorldPulse data-source paths."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from math import isfinite
from typing import Any, ClassVar, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.data_sources import (
    BUILTIN_CLIMATE_DATASETS,
    BUILTIN_FRED_DATASETS,
    BUILTIN_WORLD_BANK_DATASETS,
    FRED_CSV_URL,
    FRED_CACHE_TTL_SECONDS,
    NASA_GISTEMP_URL,
    NASA_CACHE_TTL_SECONDS,
    NOAA_CO2_URL,
    NOAA_CACHE_TTL_SECONDS,
    NOAA_ONI_URL,
    WORLD_BANK_PINK_SHEET_URL,
    WORLD_BANK_CACHE_TTL_SECONDS,
    read_climate_series,
    read_fred_series,
    read_world_bank_series,
)

from ..contracts import (
    PluginInputEnvelope,
    PluginManifest,
    PluginOutputEnvelope,
    build_plugin_manifest,
    build_plugin_output,
    canonical_hash,
)
from ..registry import PluginRegistry
from ..verification import verify_plugin_input


class TimeSeriesConnectorRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["timeseries-connector-request.v1"] = (
        "timeseries-connector-request.v1"
    )
    dataset: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date
    cutoff_at: datetime

    @model_validator(mode="after")
    def _validate_window(self) -> "TimeSeriesConnectorRequestV1":
        if self.cutoff_at.tzinfo is None:
            raise ValueError("connector cutoff_at must be timezone-aware")
        if self.start_date > self.end_date:
            raise ValueError("connector start_date must not exceed end_date")
        if self.end_date > self.cutoff_at.date():
            raise ValueError("connector end_date exceeds cutoff_at")
        if (self.end_date - self.start_date).days > 3660:
            raise ValueError("connector window exceeds ten years")
        return self


class TimeSeriesObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    date: date
    value: float = Field(allow_inf_nan=False)


class DataSourceIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_name: str
    locator: str
    observed_at: date
    cutoff_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plugin_id: str
    plugin_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plugin_configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TimeSeriesConnectorOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["timeseries-connector-output.v1"] = (
        "timeseries-connector-output.v1"
    )
    source: DataSourceIdentityV1
    observations: tuple[TimeSeriesObservationV1, ...] = Field(min_length=1)


SeriesLoader = Callable[[str, pd.DatetimeIndex], tuple[pd.Series, str]]


class _TimeSeriesConnector:
    plugin_id: ClassVar[str]
    implementation_id: ClassVar[str]
    datasets: ClassVar[tuple[str, ...]]
    locators: ClassVar[dict[str, str]]
    cache_ttl_seconds: ClassVar[dict[str, int]]
    loader: ClassVar[SeriesLoader]

    def __init__(self) -> None:
        configuration = self.configuration()
        self._manifest = build_plugin_manifest(
            plugin_id=self.plugin_id,
            kind="connector",
            version="1.0.0",
            implementation_id=self.implementation_id,
            capabilities=("source.read", "timeseries.extract"),
            permissions=("network.read",),
            input_schema="timeseries-connector-request.v1",
            output_schema="timeseries-connector-output.v1",
            configuration=configuration,
        )

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @classmethod
    def configuration(cls) -> dict[str, Any]:
        return {
            "datasets": list(cls.datasets),
            "locators": {key: cls.locators[key] for key in sorted(cls.locators)},
            "cache_ttl_seconds": {
                key: cls.cache_ttl_seconds[key]
                for key in sorted(cls.cache_ttl_seconds)
            },
            "caller_url_override": False,
            "evidence_write": False,
        }

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope:
        self.manifest.verify_configuration(self.configuration())
        verified = verify_plugin_input(self.manifest, envelope)
        request = TimeSeriesConnectorRequestV1.model_validate(verified.payload)
        if request.schema_version != self.manifest.input_schema:
            raise ValueError("connector request schema does not match manifest")
        if request.dataset not in self.datasets:
            raise ValueError(
                f"dataset is not allowlisted for {self.plugin_id}: {request.dataset}"
            )
        dates = pd.bdate_range(start=request.start_date, end=request.end_date)
        if dates.empty:
            raise ValueError("connector request produced an empty business-day window")
        series, source_name = self.__class__.loader(request.dataset, dates)
        if len(series) != len(dates):
            raise ValueError("connector loader returned an unexpected series length")
        records: list[dict[str, Any]] = []
        for observed_date, raw_value in zip(dates, series, strict=True):
            value = float(raw_value)
            if not isfinite(value):
                raise ValueError("connector loader returned a non-finite observation")
            records.append({"date": observed_date.date().isoformat(), "value": value})
        content_hash = canonical_hash(records)
        output = TimeSeriesConnectorOutputV1(
            source=DataSourceIdentityV1(
                source_id=f"{self.plugin_id}.{request.dataset.lower()}",
                source_name=source_name,
                locator=self.locators[request.dataset],
                observed_at=dates.max().date(),
                cutoff_at=request.cutoff_at,
                content_hash=content_hash,
                plugin_id=self.manifest.plugin_id,
                plugin_manifest_hash=self.manifest.manifest_hash,
                plugin_configuration_hash=self.manifest.configuration_hash,
            ),
            observations=tuple(TimeSeriesObservationV1.model_validate(item) for item in records),
        )
        return build_plugin_output(
            self.manifest,
            verified.invocation,
            output.model_dump(mode="json"),
            provider_calls=0,
        )


class FredConnector(_TimeSeriesConnector):
    plugin_id = "connector.fred"
    implementation_id = "builtin.connector.fred"
    datasets = BUILTIN_FRED_DATASETS
    locators = {key: f"{FRED_CSV_URL}?id={key}" for key in datasets}
    cache_ttl_seconds = {key: FRED_CACHE_TTL_SECONDS for key in datasets}
    loader = staticmethod(read_fred_series)


class WorldBankConnector(_TimeSeriesConnector):
    plugin_id = "connector.world_bank"
    implementation_id = "builtin.connector.world_bank"
    datasets = BUILTIN_WORLD_BANK_DATASETS
    locators = {key: WORLD_BANK_PINK_SHEET_URL for key in datasets}
    cache_ttl_seconds = {
        key: WORLD_BANK_CACHE_TTL_SECONDS for key in datasets
    }
    loader = staticmethod(read_world_bank_series)


class NoaaNasaConnector(_TimeSeriesConnector):
    plugin_id = "connector.noaa_nasa"
    implementation_id = "builtin.connector.noaa_nasa"
    datasets = BUILTIN_CLIMATE_DATASETS
    locators = {
        "nasa_ocean_heat": NASA_GISTEMP_URL,
        "nasa_temperature": NASA_GISTEMP_URL,
        "noaa_co2": NOAA_CO2_URL,
        "noaa_enso": NOAA_ONI_URL,
    }
    cache_ttl_seconds = {
        "nasa_ocean_heat": NASA_CACHE_TTL_SECONDS,
        "nasa_temperature": NASA_CACHE_TTL_SECONDS,
        "noaa_co2": NOAA_CACHE_TTL_SECONDS,
        "noaa_enso": NOAA_CACHE_TTL_SECONDS,
    }
    loader = staticmethod(read_climate_series)


def built_in_data_connectors() -> tuple[_TimeSeriesConnector, ...]:
    return FredConnector(), WorldBankConnector(), NoaaNasaConnector()


def built_in_data_connector_registry() -> PluginRegistry:
    return PluginRegistry(item.manifest for item in built_in_data_connectors())
