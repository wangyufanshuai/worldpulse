from __future__ import annotations

from math import sin

from .data import (
    CHANNEL_ZH,
    CHAIN_ZH,
    COUNTRY_ZH,
    MAP_COORDINATES,
    MAP_EVENTS,
    MILITARY_UNITS,
    SUPPLY_CHAINS,
    TEXT_ZH,
    WAR_ROOM_DISCLAIMER,
)
from .utils import _top_drivers

from app.core.models import (
    AgentDecision,
    ConflictEvent,
    SupplyChainLink,
    WarRoomCountryAgent,
    WarRoomHeatmapCell,
    WarRoomImpactGraph,
    WarRoomPresetBundle,
    WarRoomRun,
    WarRoomScenario,
    WarRoomScenarioRequest,
    WarRoomTimelinePoint,
)


def _ui_state(
    scenario: WarRoomScenario,
    timeline: list[WarRoomTimelinePoint],
    agents: list[WarRoomCountryAgent],
    chains: list[SupplyChainLink],
    heatmap: list[WarRoomHeatmapCell],
    decisions: list[AgentDecision],
    graph: WarRoomImpactGraph,
) -> dict:
    kpis = _ui_kpis(timeline, agents, chains, heatmap, graph)
    map_layers = _ui_map_layers()
    map_entities = _ui_map_entities(scenario, agents, chains, heatmap, decisions, graph)
    timeline_events = _ui_timeline_events(scenario, timeline)
    agent_panels = _ui_agent_panels(agents, heatmap, decisions, scenario)
    entity_details = _ui_entity_details(map_entities, timeline_events, agent_panels)
    return {
        "display": {
            "title_zh": _scenario_title_zh(scenario),
            "subtitle_zh": f"{scenario.duration_days} 天策略推演 · 强度 {scenario.intensity:.2f} · 传播 {scenario.propagation:.2f}",
            "disclaimer_zh": WAR_ROOM_DISCLAIMER,
        },
        "kpis": kpis,
        "map_layers": map_layers,
        "map_entities": map_entities,
        "timeline_events": timeline_events,
        "agent_panels": agent_panels,
        "entity_relations": _ui_entity_relations(chains, graph),
        "entity_index": _ui_entity_index(map_entities, timeline_events, decisions),
        "command_actions": _ui_command_actions(scenario),
        "insight_cards": _ui_insight_cards(kpis, agents, chains, timeline),
        "entity_details": entity_details,
    }


def _ui_kpis(
    timeline: list[WarRoomTimelinePoint],
    agents: list[WarRoomCountryAgent],
    chains: list[SupplyChainLink],
    heatmap: list[WarRoomHeatmapCell],
    graph: WarRoomImpactGraph,
) -> list[dict]:
    start = timeline[0] if timeline else None
    end = timeline[-1] if timeline else None
    global_risk = _normalize_percent(end.global_risk if end else 0)
    risk_delta = round(global_risk - _normalize_percent(start.global_risk if start else 0), 1)
    affected = len({agent.code for agent in agents if agent.risk_score >= 45} | {cell.country_code for cell in heatmap if cell.risk >= 45})
    chain_peak = max((chain.pressure_score for chain in chains), default=0)
    economic_delta = round(-1 * min(3.8, (sum(chain.pressure_score for chain in chains) / max(1, len(chains))) / 65), 1)
    turning_points = sum(1 for point in timeline if point.turning_point)
    return [
        {"key": "global_risk", "label_zh": "全球风险指数", "value": round(global_risk, 1), "unit": "/100", "detail_zh": "当前回放节点综合风险", "delta": risk_delta, "tone": "risk", "sparkline": _sparkline(timeline, "global_risk")},
        {"key": "volatility", "label_zh": "局势波动", "value": "高" if global_risk >= 72 else "中高", "detail_zh": "关键拐点密度", "delta": turning_points, "tone": "alert" if turning_points >= 3 else "warning", "sparkline": _sparkline(timeline, "public_opinion_pressure")},
        {"key": "events", "label_zh": "关键事件", "value": len(timeline), "detail_zh": f"{turning_points} 个拐点", "delta": turning_points, "tone": "neutral", "sparkline": _sparkline(timeline, "military_pressure")},
        {"key": "countries", "label_zh": "影响国家/地区", "value": affected, "detail_zh": "风险分值超过监测阈值", "delta": max(0, affected - 5), "tone": "neutral", "sparkline": []},
        {"key": "economy", "label_zh": "经济影响", "value": f"{economic_delta:.1f}%", "detail_zh": "全球 GDP 预期影响", "delta": economic_delta, "tone": "positive" if economic_delta < 0 else "neutral", "sparkline": _sparkline(timeline, "financial_stress")},
        {"key": "reaction", "label_zh": "连锁反应强度", "value": "强" if chain_peak >= 68 else "中高", "detail_zh": f"图谱置信度 {graph.confidence:.1f}", "delta": round(chain_peak / 10, 1), "tone": "warning", "sparkline": [round(chain.pressure_score, 1) for chain in chains]},
    ]


def _ui_map_layers() -> list[dict]:
    return [
        {"key": "military", "label_zh": "军事部署", "enabled": True},
        {"key": "economic", "label_zh": "经济联系", "enabled": True},
        {"key": "diplomatic", "label_zh": "外交关系", "enabled": True},
        {"key": "events", "label_zh": "事件热点", "enabled": True},
        {"key": "risk", "label_zh": "风险区域", "enabled": True},
        {"key": "causal", "label_zh": "因果链路", "enabled": True},
    ]


def _ui_map_entities(
    scenario: WarRoomScenario,
    agents: list[WarRoomCountryAgent],
    chains: list[SupplyChainLink],
    heatmap: list[WarRoomHeatmapCell],
    decisions: list[AgentDecision],
    graph: WarRoomImpactGraph,
) -> list[dict]:
    agent_by_code = {agent.code: agent for agent in agents}
    decision_by_code = {decision.country_code: decision for decision in decisions}
    entities: list[dict] = []

    for index, cell in enumerate(heatmap):
        code = cell.country_code
        coords = _map_coordinates(code, index)
        agent = agent_by_code.get(code)
        decision = decision_by_code.get(code)
        entities.append({
            "id": f"country:{code}",
            "key": code,
            "type": "country",
            "layer": "risk",
            "label_zh": _country_zh(code),
            "x": coords["x"],
            "y": coords["y"],
            "tone": _risk_tone(cell.risk),
            "risk": round(cell.risk, 1),
            "dominant_channel": cell.dominant_channel,
            "dominant_channel_zh": _channel_zh(cell.dominant_channel),
            "risk_breakdown": {_channel_zh(key): value for key, value in cell.risk_breakdown.items()},
            "related_countries": [code],
            "related_chains": _chains_for_country(code, chains),
            "agent_action_zh": _decision_action_zh(decision.action if decision else ""),
            "status_zh": "活跃" if agent and agent.risk_score >= 70 else "观察",
        })

    for index, chain in enumerate(chains):
        countries = chain.affected_countries or scenario.target_countries
        start = _map_coordinates(countries[0] if countries else "USA", index)
        end = _map_coordinates(countries[-1] if countries else "CHN", index + 2)
        entities.append({
            "id": f"chain:{chain.key}",
            "key": chain.key,
            "type": "supply_chain",
            "layer": "economic",
            "label_zh": _chain_zh(chain.key),
            "x": round((start["x"] + end["x"]) / 2, 1),
            "y": round((start["y"] + end["y"]) / 2, 1),
            "tone": _risk_tone(chain.pressure_score),
            "pressure": round(chain.pressure_score, 1),
            "capacity": chain.capacity,
            "substitution": chain.substitution,
            "lag_days": chain.lag_days,
            "related_countries": countries,
            "related_chains": [chain.key],
            "detail_zh": f"{_chain_zh(chain.key)}压力 {chain.pressure_score:.1f}/100，替代率 {chain.substitution:.0f}%，滞后 {chain.lag_days} 天。",
        })

    for index, event in enumerate(MAP_EVENTS):
        day = min(int(event["day"]), scenario.duration_days)
        entities.append({
            "id": f"event:{event['key']}",
            "key": event["key"],
            "type": "event",
            "layer": "events",
            "label_zh": event["label_zh"],
            "title_zh": event["title_zh"],
            "detail_zh": _event_detail_zh(event, scenario),
            "x": event["x"],
            "y": event["y"],
            "day": day,
            "tone": event["tone"],
            "related_countries": event["related_countries"],
            "related_chains": [chain for chain in event["related_chains"] if chain in scenario.target_chains or chain in {item.key for item in chains}],
        })

    for unit in MILITARY_UNITS:
        entities.append({
            "id": f"unit:{unit['key']}",
            "key": unit["key"],
            "type": "unit",
            "layer": "military",
            "label_zh": unit["label_zh"],
            "x": unit["x"],
            "y": unit["y"],
            "tone": "blue",
            "related_countries": unit["related_countries"],
            "related_chains": ["shipping"],
            "detail_zh": f"{unit['label_zh']}用于展示军事压力的模拟部署点。",
        })

    for index, edge in enumerate(graph.edges[:24]):
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        source_point = _entity_coordinates(source, index)
        target_point = _entity_coordinates(target, index + 3)
        entities.append({
            "id": _edge_entity_id(edge),
            "key": _edge_entity_id(edge).replace("edge:", ""),
            "type": "causal_edge",
            "layer": "causal",
            "label_zh": _edge_label_zh(edge),
            "x": round((source_point["x"] + target_point["x"]) / 2, 1),
            "y": round((source_point["y"] + target_point["y"]) / 2, 1),
            "source": source,
            "target": target,
            "source_label_zh": _entity_label_zh(source),
            "target_label_zh": _entity_label_zh(target),
            "tone": "red" if float(edge.get("weight", 0) or 0) >= 0.62 else "blue",
            "weight": edge.get("weight"),
            "lag_days": edge.get("lag_days", 0),
            "mechanism_zh": _mechanism_zh(edge.get("mechanism") or edge.get("explanation") or edge.get("relation")),
            "related_countries": _countries_for_edge(edge),
            "related_chains": _chains_for_edge(edge),
        })

    return entities


def _ui_timeline_events(scenario: WarRoomScenario, timeline: list[WarRoomTimelinePoint]) -> list[dict]:
    total = max(1, len(timeline) - 1)
    events = []
    previous_risk = None
    for index, point in enumerate(timeline):
        risk = _normalize_percent(point.global_risk)
        delta = 0 if previous_risk is None else round(risk - previous_risk, 1)
        previous_risk = risk
        event_keys = _event_keys_for_day(point.day, scenario)
        related_countries = _countries_for_day(point.day, scenario)
        related_chains = _chains_for_day(point.day, scenario)
        events.append({
            "key": f"day-{point.day}",
            "day": int(point.day),
            "time": f"D+{point.day}",
            "title_zh": _timeline_title_zh(point, index),
            "detail_zh": _zh(point.key_development),
            "tone": _timeline_tone(point, delta, index),
            "position": round(index / total * 100, 1),
            "turning_point": bool(point.turning_point),
            "event_keys": event_keys,
            "related_countries": related_countries,
            "related_chains": related_chains,
            "global_risk": round(risk, 1),
            "global_risk_delta": delta,
        })
    return events


def _ui_agent_panels(
    agents: list[WarRoomCountryAgent],
    heatmap: list[WarRoomHeatmapCell],
    decisions: list[AgentDecision],
    scenario: WarRoomScenario,
) -> dict:
    heat_by_code = {cell.country_code: cell for cell in heatmap}
    decision_by_code = {decision.country_code: decision for decision in decisions}
    panels = {}
    for agent in agents:
        heat = heat_by_code.get(agent.code)
        decision = decision_by_code.get(agent.code)
        drivers = decision.drivers if decision else _top_drivers(heat.risk_breakdown if heat else {})
        panels[agent.code] = {
            "country_code": agent.code,
            "country_name_zh": _country_zh(agent.code),
            "country_name": agent.name,
            "status_zh": "活跃" if agent.risk_score >= 70 else "观察",
            "strategic_intent_zh": _strategic_intent_zh(agent, heat),
            "trigger_source_zh": _trigger_source_zh(agent.code, scenario),
            "decision_basis_zh": _decision_basis_zh(agent, heat, drivers),
            "expected_tradeoff_zh": _zh(decision.expected_tradeoff if decision else ""),
            "metrics": [
                {"label_zh": "综合国力", "value": round(agent.risk_score, 1)},
                {"label_zh": "军事能力", "value": round(agent.military_pressure, 1)},
                {"label_zh": "经济实力", "value": round(100 - agent.financial_stress * 0.35, 1)},
                {"label_zh": "科技水平", "value": round(max(40, 100 - agent.chip_dependency * 0.25), 1)},
                {"label_zh": "外交影响力", "value": round(100 - agent.public_opinion_pressure * 0.3, 1)},
                {"label_zh": "社会稳定性", "value": round(agent.stability, 1)},
            ],
            "decisions": [_decision_action_zh(decision.action if decision else "Monitor alliances and prepare substitution")],
            "drivers_zh": [_channel_zh(driver) for driver in drivers],
            "relations": _relations_zh(agent.code),
            "recent_actions": _recent_actions_zh(agent.code, scenario),
            "related_events": _related_event_titles(agent.code),
            "related_chains": _chains_for_country(agent.code, [chain for chain in SUPPLY_CHAINS]),
        }
    return panels


def _ui_entity_relations(chains: list[SupplyChainLink], graph: WarRoomImpactGraph) -> dict:
    relations: dict[str, list[str]] = {}
    for chain in chains:
        relations[f"chain:{chain.key}"] = [f"country:{code}" for code in chain.affected_countries]
        for code in chain.affected_countries:
            relations.setdefault(f"country:{code}", []).append(f"chain:{chain.key}")
    for edge in graph.edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        relations.setdefault(source, []).append(target)
    return relations


def _ui_entity_index(map_entities: list[dict], timeline_events: list[dict], decisions: list[AgentDecision]) -> list[dict]:
    index: list[dict] = []
    for entity in map_entities:
        entity_id = str(entity.get("id") or "")
        entity_type = str(entity.get("type") or "entity")
        title = entity.get("title_zh") or entity.get("label_zh") or entity.get("source_label_zh") or entity_id
        subtitle = entity.get("detail_zh") or entity.get("mechanism_zh") or _entity_index_subtitle(entity)
        index.append({
            "id": entity_id,
            "type": entity_type,
            "title_zh": title,
            "subtitle_zh": subtitle,
            "section": _section_for_entity_type(entity_type),
            "layer": entity.get("layer", ""),
            "day": entity.get("day"),
            "ref": entity_id,
            "tokens": _entity_tokens(entity, title, subtitle),
        })
    for event in timeline_events:
        event_id = f"timeline:{event.get('key')}"
        index.append({
            "id": event_id,
            "type": "timeline",
            "title_zh": event.get("title_zh") or event.get("title") or event_id,
            "subtitle_zh": event.get("detail_zh") or "",
            "section": "overview",
            "layer": "events",
            "day": event.get("day"),
            "ref": event.get("key"),
            "tokens": [str(event.get("key", "")), str(event.get("time", "")), str(event.get("day", "")), *(event.get("related_countries") or []), *(event.get("related_chains") or [])],
        })
    for decision in decisions:
        index.append({
            "id": f"decision:{decision.country_code}",
            "type": "decision",
            "title_zh": _decision_action_zh(decision.action),
            "subtitle_zh": f"{_country_zh(decision.country_code)} · 置信度 {decision.confidence:.0f}/100",
            "section": "analysis",
            "layer": "risk",
            "day": None,
            "ref": f"country:{decision.country_code}",
            "tokens": [decision.country_code, decision.country_name, decision.action, *decision.drivers],
        })
    return index


def _ui_command_actions(scenario: WarRoomScenario) -> list[dict]:
    has_policy = bool(scenario.policy_actions)
    return [
        {"key": "run_scenario", "label_zh": "运行沙盘", "action_type": "run", "enabled": True, "status": "active"},
        {"key": "clone_run", "label_zh": "克隆本次运行", "action_type": "clone", "enabled": True, "status": "active"},
        {"key": "compare_runs", "label_zh": "反事实对比", "action_type": "compare", "enabled": True, "status": "active"},
        {"key": "export_replay", "label_zh": "导出复盘包", "action_type": "replay", "enabled": True, "status": "active"},
        {"key": "policy_focus", "label_zh": "政策动作已启用" if has_policy else "无政策动作基线", "action_type": "note", "enabled": False, "status": "active" if has_policy else "baseline"},
        {"key": "three_d", "label_zh": "3D 地球视图", "action_type": "upcoming", "enabled": False, "status": "upcoming"},
    ]


def _ui_insight_cards(
    kpis: list[dict],
    agents: list[WarRoomCountryAgent],
    chains: list[SupplyChainLink],
    timeline: list[WarRoomTimelinePoint],
) -> list[dict]:
    top_agent = max(agents, key=lambda item: item.risk_score) if agents else None
    top_chain = max(chains, key=lambda item: item.pressure_score) if chains else None
    turning_points = [point for point in timeline if point.turning_point]
    return [
        {
            "key": "top_country",
            "label_zh": "最高风险国家",
            "value_zh": f"{_country_zh(top_agent.code)} {top_agent.risk_score:.0f}/100" if top_agent else "--",
            "tone": _risk_tone(top_agent.risk_score if top_agent else 0),
            "detail_zh": "点击国家节点查看 Agent 决策和关系网络。",
        },
        {
            "key": "top_chain",
            "label_zh": "供应链瓶颈",
            "value_zh": f"{_chain_zh(top_chain.key)} {top_chain.pressure_score:.0f}/100" if top_chain else "--",
            "tone": _risk_tone(top_chain.pressure_score if top_chain else 0),
            "detail_zh": "压力由容量、替代率、滞后天数和政策动作共同决定。",
        },
        {
            "key": "turning_points",
            "label_zh": "关键拐点",
            "value_zh": f"{len(turning_points)} 个",
            "tone": "orange" if turning_points else "green",
            "detail_zh": "时间线筛选可只查看关键拐点和选中实体相关事件。",
        },
    ]


def _ui_entity_details(map_entities: list[dict], timeline_events: list[dict], agent_panels: dict) -> dict:
    details: dict[str, dict] = {}
    event_by_key = {str(event.get("key")): event for event in timeline_events}
    for entity in map_entities:
        entity_id = str(entity.get("id") or "")
        entity_type = str(entity.get("type") or "entity")
        title = entity.get("title_zh") or entity.get("label_zh") or entity.get("source_label_zh") or entity_id
        metrics = _entity_detail_metrics(entity)
        related_events = [
            f"D+{event_by_key[key].get('day')} {event_by_key[key].get('title_zh')}"
            for key in entity.get("event_keys", []) or []
            if key in event_by_key
        ]
        if not related_events:
            related_events = [
                f"D+{event.get('day')} {event.get('title_zh')}"
                for event in timeline_events
                if _entity_related_to_event(entity, event)
            ][:4]
        details[entity_id] = {
            "id": entity_id,
            "type": entity_type,
            "title_zh": title,
            "summary_zh": entity.get("detail_zh") or entity.get("mechanism_zh") or _entity_index_subtitle(entity),
            "metrics": metrics,
            "related_events": related_events,
            "related_countries": [_country_zh(code) for code in entity.get("related_countries", [])],
            "related_chains": [_chain_zh(key) for key in entity.get("related_chains", [])],
            "actions": _entity_detail_actions(entity_type),
        }
    for code, panel in agent_panels.items():
        entity_id = f"country:{code}"
        if entity_id in details:
            details[entity_id]["agent_panel"] = panel
            details[entity_id]["decision_basis_zh"] = panel.get("decision_basis_zh", "")
            details[entity_id]["expected_tradeoff_zh"] = panel.get("expected_tradeoff_zh", "")
    return details


def _entity_index_subtitle(entity: dict) -> str:
    entity_type = entity.get("type")
    if entity_type == "country":
        return f"风险 {entity.get('risk', '--')}/100 · 主导通道 {_channel_zh(str(entity.get('dominant_channel', '')))}"
    if entity_type == "supply_chain":
        return f"压力 {entity.get('pressure', '--')}/100 · 滞后 {entity.get('lag_days', 0)} 天"
    if entity_type == "causal_edge":
        return f"权重 {entity.get('weight', '--')} · 滞后 {entity.get('lag_days', 0)} 天"
    if entity_type == "event":
        return f"D+{entity.get('day', 0)} · 事件热点"
    return "War Room 地图实体"


def _entity_tokens(entity: dict, title: str, subtitle: str) -> list[str]:
    return [
        str(entity.get("id", "")),
        str(entity.get("key", "")),
        str(entity.get("type", "")),
        str(entity.get("layer", "")),
        title,
        subtitle,
        *(entity.get("related_countries") or []),
        *(entity.get("related_chains") or []),
    ]


def _section_for_entity_type(entity_type: str) -> str:
    return {
        "country": "analysis",
        "supply_chain": "sandbox",
        "causal_edge": "graph",
        "event": "overview",
        "unit": "overview",
        "timeline": "overview",
        "decision": "analysis",
    }.get(entity_type, "overview")


def _entity_detail_metrics(entity: dict) -> list[dict]:
    entity_type = entity.get("type")
    if entity_type == "country":
        return [
            {"label_zh": "风险分值", "value": f"{entity.get('risk', 0)}/100"},
            {"label_zh": "主导通道", "value": entity.get("dominant_channel_zh") or _channel_zh(str(entity.get("dominant_channel", "")))},
            {"label_zh": "Agent 动作", "value": entity.get("agent_action_zh") or "观察态势"},
        ]
    if entity_type == "supply_chain":
        return [
            {"label_zh": "链路压力", "value": f"{entity.get('pressure', 0)}/100"},
            {"label_zh": "容量", "value": f"{entity.get('capacity', 0)}%"},
            {"label_zh": "替代率", "value": f"{entity.get('substitution', 0)}%"},
            {"label_zh": "滞后", "value": f"{entity.get('lag_days', 0)} 天"},
        ]
    if entity_type == "causal_edge":
        return [
            {"label_zh": "边权重", "value": entity.get("weight", "--")},
            {"label_zh": "滞后", "value": f"{entity.get('lag_days', 0)} 天"},
            {"label_zh": "机制", "value": entity.get("mechanism_zh", "因果传导")},
        ]
    if entity_type == "event":
        return [
            {"label_zh": "发生日", "value": f"D+{entity.get('day', 0)}"},
            {"label_zh": "类型", "value": "关键风险" if entity.get("tone") == "red" else "态势事件"},
        ]
    return [{"label_zh": "类型", "value": entity_type or "entity"}]


def _entity_related_to_event(entity: dict, event: dict) -> bool:
    countries = set(entity.get("related_countries") or [])
    chains = set(entity.get("related_chains") or [])
    return bool(countries.intersection(event.get("related_countries") or []) or chains.intersection(event.get("related_chains") or []))


def _entity_detail_actions(entity_type: str) -> list[dict]:
    actions = [{"key": "focus", "label_zh": "在地图中定位", "action_type": "focus", "enabled": True}]
    if entity_type == "country":
        actions.append({"key": "analysis", "label_zh": "进入智能分析", "action_type": "section", "section": "analysis", "enabled": True})
    if entity_type == "causal_edge":
        actions.append({"key": "graph", "label_zh": "查看因果链路", "action_type": "section", "section": "graph", "enabled": True})
    actions.append({"key": "replay", "label_zh": "导出复盘包", "action_type": "replay", "enabled": True})
    return actions


def _sparkline(timeline: list[WarRoomTimelinePoint], attr: str) -> list[float]:
    if not timeline:
        return []
    values = [getattr(point, attr, 0) for point in timeline]
    return [round(_normalize_percent(value), 1) for value in values[:8]]


def _map_coordinates(code: str, index: int = 0) -> dict:
    normalized = str(code or "").replace("country:", "").upper()
    if normalized in MAP_COORDINATES:
        return MAP_COORDINATES[normalized]
    angle = index / 10 * 6.283
    return {"x": round(500 + sin(angle) * 270, 1), "y": round(280 + sin(angle + 1.4) * 150, 1)}


def _entity_coordinates(entity_id: str, index: int = 0) -> dict:
    value = str(entity_id or "")
    if value.startswith("country:"):
        return _map_coordinates(value.split(":", 1)[1], index)
    if value.startswith("chain:"):
        chain = next((item for item in SUPPLY_CHAINS if item.key == value.split(":", 1)[1]), None)
        code = chain.affected_countries[0] if chain and chain.affected_countries else ""
        return _map_coordinates(code, index)
    if value == "scenario":
        return {"x": 586, "y": 332}
    if value == "market":
        return {"x": 710, "y": 250}
    if value == "opinion":
        return {"x": 528, "y": 352}
    if value == "alliance":
        return {"x": 246, "y": 232}
    if value == "policy":
        return {"x": 604, "y": 278}
    for code in MAP_COORDINATES:
        if code in value.upper():
            return _map_coordinates(code, index)
    return _map_coordinates("", index)


def _normalize_percent(value: float | int | None) -> float:
    number = float(value or 0)
    return number * 100 if 0 < number <= 1 else number


def _scenario_title_zh(scenario: WarRoomScenario) -> str:
    labels = {
        "strait_blockade_30d": "海峡危机升级推演",
        "energy_export_cut": "能源出口中断推演",
        "food_shortfall": "粮食减产与出口限制推演",
    }
    return labels.get(scenario.key, scenario.name)


def _country_zh(code: str) -> str:
    return COUNTRY_ZH.get(str(code or "").replace("country:", "").upper(), str(code or ""))


def _channel_zh(key: str) -> str:
    return CHANNEL_ZH.get(str(key or ""), str(key or ""))


def _chain_zh(key: str) -> str:
    return CHAIN_ZH.get(str(key or ""), str(key or ""))


def _zh(text: str | None) -> str:
    value = str(text or "").strip()
    return TEXT_ZH.get(value, value)


def _decision_action_zh(action: str) -> str:
    labels = {
        "Diversify emergency energy cargoes": "分散能源应急货源",
        "Prioritize chip allocation and export controls": "优先保障芯片分配与出口管制",
        "Signal deterrence while opening crisis channel": "释放威慑信号并开启危机沟通",
        "Coordinate liquidity and settlement safeguards": "协调流动性与结算保护",
        "Monitor alliances and prepare substitution": "监测联盟变化并准备替代方案",
    }
    return labels.get(str(action or ""), str(action or "准备替代方案"))


def _mechanism_zh(text: str | None) -> str:
    value = str(text or "").strip()
    translations = {
        "Shock intensity is multiplied by propagation, substitution gap, lag, target selection, and policy actions.": "冲击强度由传播系数、替代缺口、滞后天数、目标选择和政策动作共同放大。",
        "Country pressure is derived from dependency, trade exposure, financial stress, and limited substitution.": "国家压力由依赖度、贸易暴露、金融压力与替代能力限制共同决定。",
        "Policy actions reallocate physical pressure into market and settlement channels.": "政策动作会把部分实体压力重新分配到市场和结算通道。",
        "Messaging and economic stress shift public-opinion pressure.": "沟通动作与经济压力共同改变舆论压力。",
        "Alliance alignment changes sanctions, deterrence, and substitute routing.": "联盟协调改变制裁、威慑和替代路线。",
    }
    return translations.get(value, _zh(value))


def _entity_label_zh(entity_id: str) -> str:
    value = str(entity_id or "")
    if value.startswith("country:"):
        return _country_zh(value.split(":", 1)[1])
    if value.startswith("chain:"):
        return _chain_zh(value.split(":", 1)[1])
    return {
        "scenario": "场景冲击",
        "market": "金融市场",
        "opinion": "公共舆论",
        "alliance": "外交联盟",
        "policy": "政策响应",
    }.get(value, value)


def _edge_label_zh(edge: dict) -> str:
    return f"{_entity_label_zh(str(edge.get('source', '')))} → {_entity_label_zh(str(edge.get('target', '')))}"


def _edge_entity_id(edge: dict) -> str:
    return f"edge:{edge.get('source', 'unknown')}->{edge.get('target', 'unknown')}"


def _risk_tone(value: float) -> str:
    number = float(value or 0)
    if number >= 72:
        return "red"
    if number >= 58:
        return "orange"
    if number >= 44:
        return "blue"
    return "green"


def _timeline_title_zh(point: WarRoomTimelinePoint, index: int) -> str:
    if point.turning_point and point.day == 3:
        return "军事与市场一阶反应"
    if point.turning_point and point.day <= 14:
        return "供应链替代进入拐点"
    if point.turning_point:
        return "二阶压力扩散"
    return "态势更新"


def _timeline_tone(point: WarRoomTimelinePoint, delta: float, index: int) -> str:
    if point.turning_point and delta >= 2:
        return "red"
    if point.turning_point:
        return "orange"
    if delta < 0:
        return "green"
    return "blue" if index % 2 else "neutral"


def _event_keys_for_day(day: int, scenario: WarRoomScenario) -> list[str]:
    keys = [event["key"] for event in MAP_EVENTS if int(event["day"]) <= max(day, 1)]
    if day <= 0:
        return ["us"]
    if day <= 3:
        return ["china"]
    if day <= 14:
        return ["us", "japan"]
    if day >= scenario.duration_days:
        return ["taiwan", "china"]
    return keys[-2:] or ["taiwan"]


def _countries_for_day(day: int, scenario: WarRoomScenario) -> list[str]:
    if day <= 0:
        return scenario.target_countries[:2] or ["USA", "TWN"]
    if day <= 3:
        return [code for code in ["CHN", "TWN", "USA"] if code in scenario.target_countries or code in COUNTRY_ZH][:3]
    if day <= 14:
        return [code for code in ["JPN", "TWN", "USA", "CHN"] if code in COUNTRY_ZH]
    return scenario.target_countries[:4] or ["CHN", "TWN", "JPN"]


def _chains_for_day(day: int, scenario: WarRoomScenario) -> list[str]:
    if day <= 3:
        return [chain for chain in ["shipping", "chips"] if chain in scenario.target_chains] or scenario.target_chains[:2]
    if day <= 14:
        return [chain for chain in ["energy", "shipping", "chips"] if chain in scenario.target_chains] or scenario.target_chains[:3]
    return scenario.target_chains[:4]


def _chains_for_country(code: str, chains: list[SupplyChainLink]) -> list[str]:
    return [chain.key for chain in chains if code in chain.affected_countries]


def _countries_for_edge(edge: dict) -> list[str]:
    codes = []
    for value in (edge.get("source"), edge.get("target")):
        raw = str(value or "")
        if raw.startswith("country:"):
            codes.append(raw.split(":", 1)[1])
    return codes


def _chains_for_edge(edge: dict) -> list[str]:
    chains = []
    for value in (edge.get("source"), edge.get("target")):
        raw = str(value or "")
        if raw.startswith("chain:"):
            chains.append(raw.split(":", 1)[1])
    return chains


def _event_detail_zh(event: dict, scenario: WarRoomScenario) -> str:
    countries = "、".join(_country_zh(code) for code in event["related_countries"][:3])
    chains = "、".join(_chain_zh(chain) for chain in event["related_chains"] if chain in scenario.target_chains) or "关键链路"
    return f"{event['title_zh']}，关联 {countries}，主要影响 {chains}。"


def _strategic_intent_zh(agent: WarRoomCountryAgent, heat: WarRoomHeatmapCell | None) -> str:
    channel = _channel_zh(heat.dominant_channel if heat else "military")
    if agent.code == "CHN":
        return f"维护核心利益与区域主动权，同时压低 {channel} 通道的外溢风险。"
    if agent.code == "USA":
        return f"维持联盟威慑与供应链安全，避免 {channel} 压力转化为系统性冲击。"
    if agent.code == "TWN":
        return f"稳定关键产能与社会预期，优先控制 {channel} 暴露。"
    return f"保持政策回旋空间，围绕 {channel} 风险准备替代和缓冲方案。"


def _trigger_source_zh(code: str, scenario: WarRoomScenario) -> str:
    matched = [event["title_zh"] for event in MAP_EVENTS if code in event["related_countries"]]
    if matched:
        return f"{_scenario_title_zh(scenario)} · {' / '.join(matched[:2])}"
    return f"{_scenario_title_zh(scenario)} · 供应链传播压力"


def _decision_basis_zh(agent: WarRoomCountryAgent, heat: WarRoomHeatmapCell | None, drivers: list[str]) -> str:
    driver_text = "、".join(_channel_zh(driver) for driver in drivers) or "综合风险"
    dominant = _channel_zh(heat.dominant_channel if heat else "military")
    return f"主要依据 {driver_text} 三类驱动，当前主导风险通道为 {dominant}，综合风险 {agent.risk_score:.1f}/100。"


def _relations_zh(code: str) -> list[dict]:
    relation_map = {
        "CHN": [("RUS", "全面战略协作伙伴", "友好", 85), ("USA", "战略竞争对手", "对抗", 25), ("JPN", "重要邻国", "竞争", 35), ("EU", "经贸伙伴", "合作", 70)],
        "USA": [("JPN", "安全盟友", "友好", 88), ("EU", "跨大西洋盟友", "合作", 86), ("CHN", "战略竞争对手", "对抗", 28), ("TWN", "关键供应链伙伴", "合作", 76)],
        "TWN": [("USA", "安全支持方", "合作", 78), ("JPN", "区域协作方", "合作", 72), ("CHN", "高压关系", "对抗", 20), ("EU", "技术与市场伙伴", "合作", 66)],
    }
    raw = relation_map.get(code, [("USA", "主要外部变量", "观察", 55), ("CHN", "主要外部变量", "观察", 55), ("EU", "市场伙伴", "合作", 64)])
    tone_map = {"友好": "friendly", "合作": "friendly", "竞争": "warning", "对抗": "hostile", "观察": "neutral"}
    return [{"country": _country_zh(country), "role": role, "label": label, "score": score, "tone": tone_map.get(label, "neutral")} for country, role, label, score in raw]


def _recent_actions_zh(code: str, scenario: WarRoomScenario) -> list[str]:
    generic = [
        f"D+3 评估 {_scenario_title_zh(scenario)} 的一阶影响",
        "D+7 调整供应链替代和外交沟通节奏",
        "D+14 更新金融与舆论压力监测阈值",
    ]
    specific = {
        "CHN": ["D+3 加强周边军事活动监测", "D+7 推动区域经贸沟通", "D+14 评估反制裁与舆论压力"],
        "USA": ["D+3 启动盟友协调", "D+7 评估技术出口与金融结算风险", "D+14 调整区域威慑信号"],
        "TWN": ["D+3 启动关键产能保障", "D+7 稳定能源与粮食库存", "D+14 加强市场沟通"],
    }
    return specific.get(code, generic)


def _related_event_titles(code: str) -> list[str]:
    titles = [f"D+{event['day']} {event['title_zh']}" for event in MAP_EVENTS if code in event["related_countries"]]
    return titles or ["D+0 场景初始化"]

