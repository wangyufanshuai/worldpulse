from __future__ import annotations

from app.core.models import CausalEvent
from app.services.event_digest import build_event_digest


EVENT_LABELS = {
    "conflict": "冲突升级",
    "sanctions": "制裁与出口管制",
    "energy": "能源冲击",
    "food": "粮食压力",
    "rates": "利率与央行",
    "trade": "贸易摩擦",
    "climate": "气候灾害",
}


def list_causal_event_types() -> list[str]:
    return list(EVENT_LABELS.keys())


def build_causal_events(window_days: int = 30, region: str = "global") -> list[CausalEvent]:
    window_days = max(7, min(int(window_days), 90))
    digest = build_event_digest(window_days=window_days, region=region)
    events = []
    for topic in digest.topics:
        event_type = topic.key
        if event_type not in EVENT_LABELS:
            continue
        confidence = _event_confidence(topic.intensity, topic.source)
        events.append(
            CausalEvent(
                event_type=event_type,
                name=EVENT_LABELS[event_type],
                region=digest.scope,
                window_days=window_days,
                intensity=round(float(topic.intensity), 2),
                event_count=int(topic.event_count),
                source=topic.source,
                summary=topic.summary,
                confidence=confidence,
            )
        )
    return sorted(events, key=lambda item: (item.intensity, item.confidence), reverse=True)


def select_event(events: list[CausalEvent], event_type: str | None = None) -> CausalEvent:
    if event_type:
        for event in events:
            if event.event_type == event_type:
                return event
        return CausalEvent(
            event_type=event_type,
            name=EVENT_LABELS.get(event_type, event_type),
            region=events[0].region if events else "global",
            window_days=events[0].window_days if events else 30,
            intensity=35,
            event_count=0,
            source="rule fallback",
            summary=f"{EVENT_LABELS.get(event_type, event_type)}暂无足够事件样本，使用规则兜底。",
            confidence=35,
        )
    if events:
        return events[0]
    return CausalEvent(
        event_type="conflict",
        name=EVENT_LABELS["conflict"],
        region="global",
        window_days=30,
        intensity=35,
        event_count=0,
        source="rule fallback",
        summary="暂无事件摘要，使用冲突升级规则兜底。",
        confidence=35,
    )


def _event_confidence(intensity: float, source: str) -> float:
    source_score = 18 if "GDELT" in source else 10
    return round(min(92, 35 + float(intensity) * 0.42 + source_score), 1)
