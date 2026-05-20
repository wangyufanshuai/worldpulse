from __future__ import annotations

import csv
import io

from app.services.risk_engine import build_replay, build_risk_history
from app.services.species_service import build_species_profile
from app.services.workbench import build_workbench_status


def risk_history_csv() -> str:
    points, _sources = build_risk_history()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "score", "financial", "climate", "geopolitical", "ecology", "macro"])
    for point in points:
        writer.writerow([point.date, point.score, point.financial, point.climate, point.geopolitical, point.ecology, point.macro])
    return output.getvalue()


def indicators_csv() -> str:
    status = build_workbench_status()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["key", "name", "component", "score", "delta_30d", "source", "frequency", "formula", "status"])
    for item in status.indicators:
        writer.writerow([item.key, item.name, item.component, item.score, item.delta_30d, item.source, item.frequency, item.formula, item.status])
    return output.getvalue()


def alerts_csv() -> str:
    status = build_workbench_status()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["level", "title", "message", "metric", "score"])
    for item in status.alerts:
        writer.writerow([item.level, item.title, item.message, item.metric, item.score])
    return output.getvalue()


def replay_csv(window_days: int = 120) -> str:
    replay = build_replay(window_days=window_days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "score", "financial", "climate", "geopolitical", "ecology", "macro"])
    for point in replay.history:
        writer.writerow([point.date, point.score, point.financial, point.climate, point.geopolitical, point.ecology, point.macro])
    return output.getvalue()


def species_occurrences_csv(scientific_name: str, source: str, region: str, limit: int = 240) -> str:
    profile = build_species_profile(scientific_name=scientific_name, source=source, region=region, limit=limit)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["source", "scientific_name", "common_name", "latitude", "longitude", "event_date", "year", "country", "locality", "dataset", "basis_of_record"])
    for item in profile.occurrences:
        writer.writerow([
            item.source,
            item.scientific_name,
            item.common_name,
            item.latitude,
            item.longitude,
            item.event_date,
            item.year,
            item.country,
            item.locality,
            item.dataset,
            item.basis_of_record,
        ])
    return output.getvalue()
