from __future__ import annotations

from copy import deepcopy

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


WAR_ROOM_DISCLAIMER = "策略沙盘 / Not a prediction. 不是现实战争预测、投资建议或政策建议。"

COUNTRY_ZH = {
    "USA": "美国",
    "CHN": "中国",
    "JPN": "日本",
    "KOR": "韩国",
    "TWN": "台湾",
    "IND": "印度",
    "EU": "欧盟",
    "RUS": "俄罗斯",
    "SAU": "中东",
    "BRA": "巴西",
}

CHANNEL_ZH = {
    "energy": "能源",
    "food": "粮食",
    "trade": "贸易",
    "chips": "芯片",
    "financial": "金融",
    "public_opinion": "舆论",
    "military": "军事",
    "settlement": "结算",
    "shipping": "海运",
    "social_stability": "社会稳定",
}

CHAIN_ZH = {
    "energy": "能源",
    "food": "粮食",
    "chips": "关键芯片",
    "shipping": "海运贸易",
    "settlement": "金融结算",
}

MAP_COORDINATES = {
    "USA": {"x": 728, "y": 216},
    "BRA": {"x": 830, "y": 430},
    "EU": {"x": 214, "y": 232},
    "RUS": {"x": 322, "y": 140},
    "SAU": {"x": 322, "y": 330},
    "IND": {"x": 438, "y": 322},
    "CHN": {"x": 497, "y": 276},
    "JPN": {"x": 603, "y": 255},
    "KOR": {"x": 576, "y": 250},
    "TWN": {"x": 565, "y": 304},
}

MAP_EVENTS = [
    {"key": "taiwan", "label_zh": "台湾", "title_zh": "经济封锁加码", "x": 586, "y": 332, "tone": "red", "day": 21, "country_code": "TWN", "related_countries": ["TWN", "CHN", "JPN"], "related_chains": ["shipping", "chips", "settlement"]},
    {"key": "china", "label_zh": "中国", "title_zh": "军事演习升级", "x": 531, "y": 249, "tone": "blue", "day": 3, "country_code": "CHN", "related_countries": ["CHN", "TWN", "USA"], "related_chains": ["shipping", "chips"]},
    {"key": "japan", "label_zh": "日本", "title_zh": "加强西南部署", "x": 632, "y": 230, "tone": "orange", "day": 14, "country_code": "JPN", "related_countries": ["JPN", "TWN", "USA"], "related_chains": ["energy", "shipping"]},
    {"key": "us", "label_zh": "美国", "title_zh": "宣布对台警戒", "x": 760, "y": 236, "tone": "blue", "day": 7, "country_code": "USA", "related_countries": ["USA", "TWN", "CHN"], "related_chains": ["chips", "settlement"]},
]

MILITARY_UNITS = [
    {"key": "carrier-1", "label_zh": "航母", "x": 584, "y": 320, "related_countries": ["USA", "TWN"]},
    {"key": "ship-1", "label_zh": "舰队", "x": 740, "y": 386, "related_countries": ["USA", "JPN"]},
    {"key": "air-1", "label_zh": "空巡", "x": 630, "y": 382, "related_countries": ["JPN", "TWN"]},
    {"key": "ship-2", "label_zh": "护航", "x": 456, "y": 392, "related_countries": ["CHN", "TWN"]},
]

TEXT_ZH = {
    "Scenario initialized; baseline dependencies and alliance posture locked.": "场景初始化，基线依赖与联盟姿态已锁定。",
    "First-order logistics, deterrence, and market repricing begin.": "一阶物流、威慑与市场重定价开始显现。",
    "Supply-chain substitution and public narrative become dominant uncertainties.": "供应链替代与公共叙事成为主要不确定性。",
    "Second-order policy responses, sanctions, and financial stress propagate.": "二阶政策响应、制裁与金融压力继续扩散。",
    "End-state comparison: bottlenecks, agent actions, and risk heatmap stabilized.": "终局对比：瓶颈、Agent 行动与风险热力进入稳定复盘窗口。",
    "High import dependency and rising supply-chain pressure make energy substitution the first stabilizer.": "高进口依赖与供应链压力上升，使能源替代成为首要稳定动作。",
    "Lowers energy exposure but may increase shipping and settlement costs.": "降低能源暴露，但可能增加海运与结算成本。",
    "Semiconductor exposure dominates the simulated causal chain.": "半导体暴露成为当前因果链中的主导压力。",
    "Protects critical capacity while raising trade friction.": "保护关键产能，但会抬高贸易摩擦。",
    "Military pressure is elevated, so de-escalation channels reduce second-order risk.": "军事压力处于高位，危机沟通渠道可降低二阶风险。",
    "Improves deterrence but can keep public and market stress elevated.": "增强威慑，但可能维持舆论和市场压力。",
    "Financial stress is becoming the main propagation channel.": "金融压力正在成为主要传播通道。",
    "Buffers markets but does not resolve physical bottlenecks.": "缓冲市场波动，但不能直接解决实体瓶颈。",
    "Risk remains manageable but linked supply chains require contingency buffers.": "风险仍可管理，但关联供应链需要预案缓冲。",
    "Preserves options but may lag fast-moving disruption.": "保留行动空间，但可能滞后于快速扩散的冲击。",
}

POLICY_ACTIONS = {
    "sanctions": {
        "label": "Sanctions package",
        "summary": "Raises settlement and trade pressure while signaling policy resolve.",
        "chain_delta": {"settlement": 12, "shipping": 5},
        "agent_delta": {"financial_stress": 4, "public_opinion_pressure": 2},
    },
    "counter_sanctions": {
        "label": "Counter-sanctions",
        "summary": "Adds reciprocal trade and financial stress with limited physical relief.",
        "chain_delta": {"settlement": 10, "shipping": 6},
        "agent_delta": {"financial_stress": 5, "trade_exposure": 1},
    },
    "energy_reroute": {
        "label": "Emergency energy reroute",
        "summary": "Reduces energy disruption through substitute cargoes but raises shipping and settlement load.",
        "chain_delta": {"energy": -14, "shipping": 5, "settlement": 4},
        "agent_delta": {"energy_dependency": -5, "financial_stress": 2},
    },
    "food_export_limit": {
        "label": "Food export restriction",
        "summary": "Protects domestic stocks while transmitting food and public-opinion pressure.",
        "chain_delta": {"food": 16, "shipping": 3},
        "agent_delta": {"food_dependency": 3, "public_opinion_pressure": 5},
    },
    "alliance_deterrence": {
        "label": "Alliance deterrence",
        "summary": "Lowers escalation risk for aligned agents while increasing visible military pressure.",
        "chain_delta": {"shipping": -3},
        "agent_delta": {"military_pressure": 5, "stability": 2},
    },
    "liquidity_support": {
        "label": "Liquidity support",
        "summary": "Buffers settlement stress and market repricing at the cost of policy bandwidth.",
        "chain_delta": {"settlement": -13},
        "agent_delta": {"financial_stress": -6},
    },
    "public_messaging": {
        "label": "Public messaging",
        "summary": "Reduces public-opinion pressure and stabilizes agent posture.",
        "chain_delta": {},
        "agent_delta": {"public_opinion_pressure": -7, "stability": 2},
    },
}


COUNTRIES = [
    WarRoomCountryAgent(code="USA", name="United States", region="North America", latitude=38.0, longitude=-97.0, alliance="Pacific security", energy_dependency=34, food_dependency=18, trade_exposure=55, chip_dependency=72, military_pressure=45, public_opinion_pressure=38, financial_stress=42, stability=76, risk_score=42),
    WarRoomCountryAgent(code="CHN", name="China", region="East Asia", latitude=35.9, longitude=104.1, alliance="Regional bloc", energy_dependency=78, food_dependency=42, trade_exposure=82, chip_dependency=66, military_pressure=58, public_opinion_pressure=46, financial_stress=48, stability=70, risk_score=51),
    WarRoomCountryAgent(code="JPN", name="Japan", region="East Asia", latitude=36.2, longitude=138.3, alliance="Pacific security", energy_dependency=92, food_dependency=61, trade_exposure=74, chip_dependency=70, military_pressure=42, public_opinion_pressure=40, financial_stress=36, stability=82, risk_score=44),
    WarRoomCountryAgent(code="KOR", name="South Korea", region="East Asia", latitude=36.5, longitude=127.9, alliance="Pacific security", energy_dependency=88, food_dependency=54, trade_exposure=77, chip_dependency=73, military_pressure=54, public_opinion_pressure=42, financial_stress=40, stability=78, risk_score=47),
    WarRoomCountryAgent(code="TWN", name="Taiwan", region="East Asia", latitude=23.7, longitude=121.0, alliance="Critical chip hub", energy_dependency=96, food_dependency=66, trade_exposure=90, chip_dependency=38, military_pressure=72, public_opinion_pressure=55, financial_stress=44, stability=74, risk_score=58),
    WarRoomCountryAgent(code="IND", name="India", region="South Asia", latitude=20.6, longitude=78.9, alliance="Non-aligned", energy_dependency=74, food_dependency=28, trade_exposure=49, chip_dependency=58, military_pressure=43, public_opinion_pressure=39, financial_stress=46, stability=68, risk_score=46),
    WarRoomCountryAgent(code="EU", name="European Union", region="Europe", latitude=50.1, longitude=9.5, alliance="Transatlantic", energy_dependency=69, food_dependency=30, trade_exposure=68, chip_dependency=64, military_pressure=34, public_opinion_pressure=44, financial_stress=52, stability=80, risk_score=45),
    WarRoomCountryAgent(code="RUS", name="Russia", region="Eurasia", latitude=61.5, longitude=105.3, alliance="Energy exporter", energy_dependency=21, food_dependency=22, trade_exposure=43, chip_dependency=74, military_pressure=64, public_opinion_pressure=48, financial_stress=62, stability=61, risk_score=54),
    WarRoomCountryAgent(code="SAU", name="Saudi Arabia", region="Middle East", latitude=23.9, longitude=45.1, alliance="Energy exporter", energy_dependency=16, food_dependency=72, trade_exposure=51, chip_dependency=53, military_pressure=39, public_opinion_pressure=34, financial_stress=34, stability=73, risk_score=39),
    WarRoomCountryAgent(code="BRA", name="Brazil", region="Latin America", latitude=-10.8, longitude=-52.9, alliance="Food exporter", energy_dependency=36, food_dependency=18, trade_exposure=46, chip_dependency=57, military_pressure=24, public_opinion_pressure=35, financial_stress=48, stability=66, risk_score=41),
]


SUPPLY_CHAINS = [
    SupplyChainLink(key="energy", name="Energy", capacity=100, disruption=0, substitution=38, lag_days=5, affected_countries=["CHN", "JPN", "KOR", "TWN", "IND", "EU"], pressure_score=32),
    SupplyChainLink(key="food", name="Food", capacity=100, disruption=0, substitution=45, lag_days=12, affected_countries=["JPN", "KOR", "TWN", "SAU", "IND"], pressure_score=32),
    SupplyChainLink(key="chips", name="Critical chips", capacity=100, disruption=0, substitution=18, lag_days=21, affected_countries=["USA", "CHN", "JPN", "KOR", "EU", "TWN"], pressure_score=44),
    SupplyChainLink(key="shipping", name="Maritime trade", capacity=100, disruption=0, substitution=31, lag_days=8, affected_countries=["USA", "CHN", "JPN", "KOR", "TWN", "EU"], pressure_score=36),
    SupplyChainLink(key="settlement", name="Financial settlement", capacity=100, disruption=0, substitution=52, lag_days=3, affected_countries=["USA", "CHN", "EU", "JPN", "KOR", "RUS"], pressure_score=30),
]


CONFLICT_EVENTS = [
    ConflictEvent(key="strait_blockade_30d", name="30-day Strait Blockade", description="A maritime chokepoint disruption that stresses shipping, energy imports, chips, public opinion, and deterrence signaling.", default_duration_days=30, target_chains=["shipping", "chips", "energy", "settlement"], target_countries=["CHN", "TWN", "JPN", "KOR", "USA"]),
    ConflictEvent(key="energy_export_cut", name="Energy Export Interruption", description="A major exporter reduces outbound energy flows, transmitting pressure through import dependency, inflation, and financial stress.", default_duration_days=30, target_chains=["energy", "settlement", "shipping"], target_countries=["EU", "JPN", "KOR", "IND", "CHN"]),
    ConflictEvent(key="food_shortfall", name="Food Production Shock", description="A harvest shortfall and export restriction scenario that tests food supply, social stability, and public opinion channels.", default_duration_days=45, target_chains=["food", "shipping", "settlement"], target_countries=["SAU", "IND", "JPN", "KOR", "TWN"]),
]


SCENARIOS = [
    WarRoomScenario(key=event.key, name=event.name, description=event.description, duration_days=event.default_duration_days, target_countries=event.target_countries, target_chains=event.target_chains)
    for event in CONFLICT_EVENTS
]


def war_room_presets() -> WarRoomPresetBundle:
    return WarRoomPresetBundle(
        countries=deepcopy(COUNTRIES),
        supply_chains=deepcopy(SUPPLY_CHAINS),
        conflict_events=deepcopy(CONFLICT_EVENTS),
        scenarios=deepcopy(SCENARIOS),
        disclaimer=WAR_ROOM_DISCLAIMER,
    )

