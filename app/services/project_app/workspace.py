from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException

from app.core.models import ResearchProject, ResearchRun, WarRoomWorkspaceState
from app.services.world_model import WORLD_MODEL_DISCLAIMER as WAR_ROOM_DISCLAIMER


def is_war_room_run(run: ResearchRun) -> bool:
    return bool((run.simulation_snapshot or {}).get("scenario") or (run.data_snapshot or {}).get("run_mode") == "war_room")


def build_war_room_workspace_state(project: ResearchProject, runs: list[ResearchRun], selected_run: ResearchRun | None) -> WarRoomWorkspaceState:
    war_room_runs = [run for run in runs if is_war_room_run(run)]
    if selected_run and not is_war_room_run(selected_run):
        raise HTTPException(status_code=422, detail="Workspace requires a War Room run")

    previous_run = next((run for run in war_room_runs if selected_run and run.run_id != selected_run.run_id), None)
    sim = deepcopy(selected_run.simulation_snapshot or {}) if selected_run else {}
    ui_state = workspace_ui_state(sim)
    entity_index = workspace_entity_index(ui_state, sim)
    entity_details = workspace_entity_details(ui_state, sim, entity_index)
    command_actions = workspace_command_actions(selected_run, previous_run)
    run_control = workspace_run_control(selected_run, previous_run, war_room_runs, sim)
    insight_cards = ui_state.get("insight_cards") or workspace_insight_cards(ui_state, sim)
    ui_state.update(
        {
            "entity_index": entity_index,
            "entity_details": entity_details,
            "command_actions": command_actions,
            "run_control": run_control,
            "insight_cards": insight_cards,
        }
    )
    return WarRoomWorkspaceState(
        project_id=project.project_id,
        run_id=selected_run.run_id if selected_run else None,
        project={"project_id": project.project_id, "title": project.title, "mode": project.mode, "status": project.status},
        run_control=run_control,
        ui_state=ui_state,
        entity_index=entity_index,
        command_actions=command_actions,
        insight_cards=insight_cards,
        entity_details=entity_details,
        compare_ready=bool(selected_run and previous_run),
        replay_ready=bool(selected_run and sim.get("scenario")),
        disclaimer=sim.get("disclaimer") or WAR_ROOM_DISCLAIMER,
    )


def workspace_ui_state(sim: dict) -> dict:
    ui_state = deepcopy(sim.get("ui_state") or {})
    ui_state.setdefault("display", {"title_zh": "War Room 指挥沙盘", "subtitle_zh": "等待运行或选择历史 run", "disclaimer_zh": WAR_ROOM_DISCLAIMER})
    ui_state.setdefault("kpis", [])
    ui_state.setdefault("map_layers", [])
    ui_state.setdefault("map_entities", [])
    ui_state.setdefault("timeline_events", [])
    ui_state.setdefault("agent_panels", {})
    return ui_state


def workspace_run_control(selected: ResearchRun | None, previous: ResearchRun | None, runs: list[ResearchRun], sim: dict) -> dict:
    scenario = sim.get("scenario") or {}
    policy_actions = scenario.get("policy_actions") or []
    return {
        "current_run_id": selected.run_id if selected else None,
        "current_completed_at": selected.completed_at if selected else None,
        "previous_run_id": previous.run_id if previous else None,
        "compare_ready": bool(selected and previous),
        "replay_ready": bool(selected and scenario),
        "run_count": len(runs),
        "scenario_title_zh": scenario.get("name") or "War Room 沙盘",
        "duration_days": scenario.get("duration_days"),
        "policy_actions": policy_actions,
        "policy_actions_zh": [workspace_policy_label(action) for action in policy_actions],
        "status_zh": "可对比复盘" if selected and previous else ("可导出复盘" if selected else "等待首次运行"),
    }


def workspace_command_actions(selected: ResearchRun | None, previous: ResearchRun | None) -> list[dict]:
    has_run = selected is not None
    has_compare = selected is not None and previous is not None
    return [
        {"key": "command_search", "label_zh": "指挥搜索", "action_type": "panel", "enabled": True, "status": "active"},
        {"key": "run_scenario", "label_zh": "运行沙盘", "action_type": "run", "enabled": True, "status": "active"},
        {"key": "clone_run", "label_zh": "克隆本次运行", "action_type": "clone", "enabled": has_run, "status": "active" if has_run else "disabled"},
        {"key": "compare_runs", "label_zh": "反事实对比", "action_type": "compare", "enabled": has_compare, "status": "active" if has_compare else "disabled"},
        {"key": "export_replay", "label_zh": "导出复盘包", "action_type": "replay", "enabled": has_run, "status": "active" if has_run else "disabled"},
        {"key": "delta_overlay", "label_zh": "反事实图层", "action_type": "toggle", "enabled": has_compare, "status": "active" if has_compare else "disabled"},
        {"key": "three_d", "label_zh": "3D 地球视图", "action_type": "upcoming", "enabled": False, "status": "upcoming"},
    ]


def workspace_entity_index(ui_state: dict, sim: dict) -> list[dict]:
    existing = ui_state.get("entity_index")
    if isinstance(existing, list) and existing:
        return existing
    index: list[dict] = []
    for entity in ui_state.get("map_entities") or []:
        entity_id = str(entity.get("id") or "")
        entity_type = str(entity.get("type") or "entity")
        title = entity.get("title_zh") or entity.get("label_zh") or entity.get("label") or entity_id
        subtitle = entity.get("detail_zh") or entity.get("mechanism_zh") or workspace_entity_subtitle(entity)
        index.append(
            {
                "id": entity_id,
                "type": entity_type,
                "title_zh": title,
                "subtitle_zh": subtitle,
                "section": workspace_section_for_entity(entity_type),
                "layer": entity.get("layer", ""),
                "day": entity.get("day"),
                "ref": entity_id,
                "tokens": [entity_id, str(entity.get("key", "")), str(entity.get("layer", "")), title, subtitle, *(entity.get("related_countries") or []), *(entity.get("related_chains") or [])],
            }
        )
    for event in ui_state.get("timeline_events") or []:
        key = str(event.get("key") or event.get("day") or "")
        index.append(
            {
                "id": f"timeline:{key}",
                "type": "timeline",
                "title_zh": event.get("title_zh") or "时间线事件",
                "subtitle_zh": event.get("detail_zh") or "",
                "section": "overview",
                "layer": "events",
                "day": event.get("day"),
                "ref": key,
                "tokens": [key, str(event.get("time", "")), str(event.get("day", "")), *(event.get("related_countries") or []), *(event.get("related_chains") or [])],
            }
        )
    for decision in sim.get("agent_decisions") or []:
        code = decision.get("country_code") or ""
        index.append(
            {
                "id": f"decision:{code}",
                "type": "decision",
                "title_zh": workspace_decision_label(decision.get("action")),
                "subtitle_zh": f"{workspace_country_label(code)} · 置信度 {round(float(decision.get('confidence') or 0))}/100",
                "section": "analysis",
                "layer": "risk",
                "day": None,
                "ref": f"country:{code}",
                "tokens": [code, decision.get("country_name", ""), decision.get("action", ""), *(decision.get("drivers") or [])],
            }
        )
    return index


def workspace_entity_details(ui_state: dict, sim: dict, entity_index: list[dict]) -> dict:
    existing = ui_state.get("entity_details")
    if isinstance(existing, dict) and existing:
        return existing
    entities = {str(entity.get("id") or ""): entity for entity in ui_state.get("map_entities") or []}
    details: dict[str, dict] = {}
    for item in entity_index:
        entity_id = item.get("ref") if str(item.get("id", "")).startswith("timeline:") else item.get("id")
        entity = entities.get(str(entity_id), {})
        details[item["id"]] = {
            "id": item["id"],
            "type": item.get("type", "entity"),
            "title_zh": item.get("title_zh", item["id"]),
            "summary_zh": item.get("subtitle_zh", ""),
            "metrics": workspace_detail_metrics(entity, item),
            "related_events": workspace_related_events(entity, ui_state.get("timeline_events") or []),
            "related_countries": [workspace_country_label(code) for code in entity.get("related_countries", [])],
            "related_chains": [workspace_chain_label(key) for key in entity.get("related_chains", [])],
            "actions": workspace_detail_actions(item.get("type", "entity")),
        }
    for code, panel in (ui_state.get("agent_panels") or {}).items():
        details.setdefault(f"country:{code}", {}).update({"agent_panel": panel, "decision_basis_zh": panel.get("decision_basis_zh", ""), "expected_tradeoff_zh": panel.get("expected_tradeoff_zh", "")})
    return details


def workspace_insight_cards(ui_state: dict, sim: dict) -> list[dict]:
    heatmap = sim.get("risk_heatmap") or []
    chains = sim.get("supply_chains") or []
    top_country: dict = max(heatmap, key=lambda item: float(item.get("risk") or 0), default={})
    top_chain: dict = max(chains, key=lambda item: float(item.get("pressure_score") or item.get("pressure") or item.get("disruption") or 0), default={})
    turning = [event for event in ui_state.get("timeline_events") or [] if event.get("turning_point")]
    return [
        {"key": "top_country", "label_zh": "最高风险国家", "value_zh": f"{workspace_country_label(top_country.get('country_code'))} {round(float(top_country.get('risk') or 0))}/100", "tone": "red", "detail_zh": "点击国家节点查看 Agent 决策。"},
        {"key": "top_chain", "label_zh": "供应链瓶颈", "value_zh": f"{workspace_chain_label(top_chain.get('key'))} {round(float(top_chain.get('pressure_score') or top_chain.get('pressure') or top_chain.get('disruption') or 0))}/100", "tone": "orange", "detail_zh": "压力由替代率、容量和滞后天数共同决定。"},
        {"key": "turning", "label_zh": "关键拐点", "value_zh": f"{len(turning)} 个", "tone": "blue", "detail_zh": "可用事件筛选聚焦关键拐点。"},
    ]


def workspace_entity_subtitle(entity: dict) -> str:
    entity_type = entity.get("type")
    if entity_type == "country":
        return f"风险 {entity.get('risk', '--')}/100"
    if entity_type == "supply_chain":
        return f"压力 {entity.get('pressure', '--')}/100 · 滞后 {entity.get('lag_days', 0)} 天"
    if entity_type == "causal_edge":
        return f"权重 {entity.get('weight', '--')} · 滞后 {entity.get('lag_days', 0)} 天"
    if entity_type == "event":
        return f"D+{entity.get('day', 0)} · 事件热点"
    return "War Room 实体"


def workspace_section_for_entity(entity_type: str) -> str:
    return {"country": "analysis", "supply_chain": "sandbox", "causal_edge": "graph", "event": "overview", "timeline": "overview", "decision": "analysis"}.get(entity_type, "overview")


def workspace_detail_metrics(entity: dict, item: dict) -> list[dict]:
    entity_type = item.get("type")
    if entity_type == "country":
        return [{"label_zh": "风险分值", "value": f"{entity.get('risk', '--')}/100"}, {"label_zh": "主导通道", "value": entity.get("dominant_channel_zh") or entity.get("dominant_channel") or "--"}]
    if entity_type == "supply_chain":
        return [{"label_zh": "链路压力", "value": f"{entity.get('pressure', '--')}/100"}, {"label_zh": "替代率", "value": f"{entity.get('substitution', '--')}%"}, {"label_zh": "滞后", "value": f"{entity.get('lag_days', 0)} 天"}]
    if entity_type == "causal_edge":
        return [{"label_zh": "边权重", "value": entity.get("weight", "--")}, {"label_zh": "滞后", "value": f"{entity.get('lag_days', 0)} 天"}]
    return [{"label_zh": "类型", "value": item.get("type", "entity")}]


def workspace_related_events(entity: dict, timeline_events: list[dict]) -> list[str]:
    countries = set(entity.get("related_countries") or [])
    chains = set(entity.get("related_chains") or [])
    matches = []
    for event in timeline_events:
        if countries.intersection(event.get("related_countries") or []) or chains.intersection(event.get("related_chains") or []):
            matches.append(f"D+{event.get('day')} {event.get('title_zh') or event.get('title')}")
    return matches[:4]


def workspace_detail_actions(entity_type: str) -> list[dict]:
    actions = [{"key": "focus", "label_zh": "在地图中定位", "action_type": "focus", "enabled": True}]
    if entity_type == "country":
        actions.append({"key": "analysis", "label_zh": "进入智能分析", "action_type": "section", "section": "analysis", "enabled": True})
    if entity_type == "causal_edge":
        actions.append({"key": "graph", "label_zh": "查看因果链路", "action_type": "section", "section": "graph", "enabled": True})
    actions.append({"key": "replay", "label_zh": "导出复盘包", "action_type": "replay", "enabled": True})
    return actions


def workspace_country_label(code: str | None) -> str:
    return {"USA": "美国", "CHN": "中国", "JPN": "日本", "KOR": "韩国", "TWN": "台湾", "IND": "印度", "EU": "欧盟", "RUS": "俄罗斯", "SAU": "中东", "BRA": "巴西"}.get(str(code or ""), str(code or "--"))


def workspace_chain_label(key: str | None) -> str:
    return {"energy": "能源", "food": "粮食", "chips": "关键芯片", "shipping": "海运贸易", "settlement": "金融结算"}.get(str(key or ""), str(key or "--"))


def workspace_policy_label(key: str) -> str:
    return {"sanctions": "制裁", "counter_sanctions": "反制裁", "energy_reroute": "能源改道", "food_export_limit": "粮食出口限制", "alliance_deterrence": "联盟威慑", "liquidity_support": "流动性支持", "public_messaging": "舆论沟通"}.get(str(key or ""), str(key or ""))


def workspace_decision_label(action: str | None) -> str:
    return {
        "Diversify emergency energy cargoes": "分散能源应急货源",
        "Prioritize chip allocation and export controls": "优先保障芯片分配与出口管制",
        "Signal deterrence while opening crisis channel": "释放威慑信号并开启危机沟通",
        "Coordinate liquidity and settlement safeguards": "协调流动性与结算保护",
        "Monitor alliances and prepare substitution": "监测联盟变化并准备替代方案",
    }.get(str(action or ""), str(action or "观察态势"))
