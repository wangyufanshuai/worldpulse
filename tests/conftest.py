from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services import causal_backtest, risk_engine


@pytest.fixture(autouse=True)
def deterministic_world_data(monkeypatch):
    def fake_load_world_data(days: int = 420):
        end = date(2026, 6, 4)
        dates = pd.bdate_range(start=end - timedelta(days=days), end=end)
        n = len(dates)
        wave = np.sin(np.linspace(0, 8 * np.pi, n))
        trend = np.linspace(0, 1, n)
        frame = pd.DataFrame(
            {
                "date": dates,
                "sp500": 4200 + trend * 260 + wave * 55,
                "nasdaq": 14500 + trend * 620 + wave * 140,
                "gold": 1850 + trend * 180 - wave * 18,
                "oil": 72 + trend * 10 + wave * 5,
                "vix": 18 + wave * 3 + trend * 2,
                "temp_anomaly": np.clip(0.48 + trend * 0.18 + wave * 0.04, 0, 1),
                "ocean_heat": np.clip(0.52 + trend * 0.14 + wave * 0.03, 0, 1),
                "co2_pressure": np.clip(0.56 + trend * 0.12, 0, 1),
                "enso_stress": np.clip(0.38 + np.abs(wave) * 0.18, 0, 1),
                "conflict_intensity": np.clip(0.42 + trend * 0.18 + np.maximum(wave, 0) * 0.22, 0, 1),
                "policy_uncertainty": np.clip(0.40 + trend * 0.16 + np.abs(wave) * 0.12, 0, 1),
                "drought_stress": np.clip(0.36 + trend * 0.10 + np.abs(wave) * 0.15, 0, 1),
                "food_pressure": np.clip(0.44 + trend * 0.12 + wave * 0.06, 0, 1),
                "fertilizer_pressure": np.clip(0.43 + trend * 0.10 + wave * 0.05, 0, 1),
                "credit_spread": np.clip(0.34 + np.abs(wave) * 0.18, 0, 1),
                "yield_curve": np.clip(0.50 + wave * 0.15, 0, 1),
                "dollar_stress": np.clip(0.45 + trend * 0.08 + wave * 0.05, 0, 1),
                "gas_pressure": np.clip(0.40 + np.abs(wave) * 0.16, 0, 1),
            }
        )
        sources = {column: "pytest deterministic fixture" for column in frame.columns if column != "date"}
        return frame, sources

    monkeypatch.setattr(risk_engine, "load_world_data", fake_load_world_data)
    monkeypatch.setattr(causal_backtest, "load_world_data", fake_load_world_data)
