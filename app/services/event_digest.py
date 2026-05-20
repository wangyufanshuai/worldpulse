from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from time import time

import requests

from app.core.models import EventDigest, EventTopic
from app.services.simulation_data import get_country_agent

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
CACHE_DIR = Path("data/cache/events")
TTL_SECONDS = 6 * 3600

TOPICS = {
    "conflict": ("冲突", "(war OR conflict OR missile OR attack OR troops OR ceasefire)"),
    "sanctions": ("制裁", "(sanction OR sanctions OR export controls OR embargo)"),
    "energy": ("能源", "(oil OR gas OR energy prices OR refinery OR LNG OR OPEC)"),
    "food": ("粮食", "(food prices OR wheat OR grain OR fertilizer OR famine)"),
    "rates": ("利率", "(interest rates OR central bank OR inflation OR bond yields)"),
    "trade": ("贸易", "(tariff OR trade war OR supply chain OR exports OR imports)"),
    "climate": ("气候灾害", "(flood OR drought OR wildfire OR heatwave OR hurricane OR climate disaster)"),
}

AGENT_QUERY_HINTS = {
    "USA": "United States",
    "CHN": "China",
    "EU": "European Union",
    "RUS": "Russia",
    "UKR": "Ukraine",
    "ISR": "Israel",
    "IRN": "Iran",
    "SAU": "Saudi Arabia",
    "TWN": "Taiwan",
    "JPN": "Japan",
    "KOR": "South Korea",
    "IND": "India",
    "VNM": "Vietnam",
    "SGP": "Singapore",
    "ARE": "United Arab Emirates",
    "NGA": "Nigeria",
    "EGY": "Egypt",
}


def build_event_digest(window_days: int = 30, region: str = "global") -> EventDigest:
    window_days = max(7, min(int(window_days), 90))
    scope = region.upper() if region.lower() != "global" else "global"
    query_prefix = _scope_query(scope)
    topics: list[EventTopic] = []
    notes = []
    with ThreadPoolExecutor(max_workers=min(7, len(TOPICS))) as executor:
        futures = {}
        for key, (name, query) in TOPICS.items():
            scoped_query = f"{query_prefix} {query}".strip()
            futures[executor.submit(_topic_count, key, scoped_query, window_days, scope)] = (key, name)
        for future in as_completed(futures):
            key, name = futures[future]
            count, source, note = future.result()
            if note:
                notes.append(note)
            topics.append(
                EventTopic(
                    key=key,
                    name=name,
                    event_count=count,
                    intensity=round(min(100, count / max(window_days, 1) * 8), 2),
                    source=source,
                    summary=_topic_summary(name, count, window_days, scope),
                )
            )
    total = sum(item.event_count for item in topics)
    return EventDigest(
        scope=scope,
        window_days=window_days,
        source="GDELT/UCDP/兜底事件代理",
        total_events=total,
        generated_at=datetime.now(timezone.utc).isoformat(),
        topics=sorted(topics, key=lambda item: item.intensity, reverse=True),
        notes=sorted(set(notes))[:6],
    )


def build_agent_event_digest(code: str, window_days: int = 30) -> EventDigest:
    agent = get_country_agent(code)
    if agent is None:
        return build_event_digest(window_days=window_days, region=code)
    digest = build_event_digest(window_days=window_days, region=agent.code)
    digest.scope = f"{agent.name} / {agent.code}"
    return digest


def _scope_query(scope: str) -> str:
    if scope == "global":
        return ""
    label = AGENT_QUERY_HINTS.get(scope, scope)
    return f'("{label}")'


def _topic_count(topic_key: str, query: str, window_days: int, scope: str) -> tuple[int, str, str | None]:
    cache_path = _cache_path(topic_key, window_days, scope)
    if cache_path.exists() and time() - cache_path.stat().st_mtime < TTL_SECONDS:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return int(payload["count"]), payload["source"], None
    try:
        count = _gdelt_count(query, window_days)
        cache_path.write_text(json.dumps({"count": count, "source": "GDELT DOC API"}, ensure_ascii=False), encoding="utf-8")
        return count, "GDELT DOC API", None
    except Exception as exc:
        count = _ucdp_or_demo_count(topic_key, window_days, scope)
        return count, "UCDP/确定性兜底", f"{topic_key} 使用兜底事件代理：{type(exc).__name__}"


def _gdelt_count(query: str, window_days: int) -> int:
    params = {
        "query": query,
        "mode": "timelinevolraw",
        "format": "json",
        "timespan": f"{window_days}d",
    }
    response = requests.get(GDELT_DOC_URL, params=params, timeout=12)
    response.raise_for_status()
    payload = response.json()
    total = 0
    for timeline in payload.get("timeline", []):
        for point in timeline.get("data", []):
            value = point.get("value") or point.get("count") or 0
            total += int(float(value))
    if total == 0 and "data" in payload:
        for point in payload.get("data", []):
            value = point.get("value") or point.get("count") or 0
            total += int(float(value))
    return total


def _ucdp_or_demo_count(topic_key: str, window_days: int, scope: str) -> int:
    if topic_key == "conflict":
        path = Path("data/cache/ucdp_ged_monthly.csv")
        if path.exists():
            try:
                import pandas as pd

                frame = pd.read_csv(path)
                if "events" in frame.columns:
                    return int(frame["events"].tail(3).mean() / 30 * window_days)
            except Exception:
                pass
    seed = sum(ord(char) for char in f"{topic_key}:{scope}:{window_days}")
    base = {
        "conflict": 52,
        "sanctions": 24,
        "energy": 38,
        "food": 21,
        "rates": 34,
        "trade": 30,
        "climate": 27,
    }[topic_key]
    return int(base + seed % 17)


def _topic_summary(name: str, count: int, window_days: int, scope: str) -> str:
    if count <= 0:
        return f"{scope} 在近 {window_days} 天内未形成明显{name}事件信号。"
    return f"{scope} 近 {window_days} 天{name}相关事件约 {count} 条，用于辅助判断舆情和事件压力。"


def _cache_path(topic_key: str, window_days: int, scope: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_scope = "".join(char if char.isalnum() else "_" for char in scope.lower())
    return CACHE_DIR / f"{safe_scope}_{window_days}_{topic_key}.json"
