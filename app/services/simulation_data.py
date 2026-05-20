from __future__ import annotations

from app.core.models import CountryAgent, PolicyShock, SimulationScenario
from app.services.agent_calibration import calibrate_state, explain_state, risk_from_state
from app.services.country_data import load_country_indicator_table

_AGENT_CACHE: list[CountryAgent] | None = None


def list_country_agents() -> list[CountryAgent]:
    global _AGENT_CACHE
    if _AGENT_CACHE is not None:
        return _AGENT_CACHE
    indicator_table = load_country_indicator_table([item["code"] for item in _AGENT_ROWS])
    agents = []
    for item in _AGENT_ROWS:
        indicators = indicator_table.get(item["code"], {})
        defaults = {key: item[key] for key in _STATE_DEFAULTS}
        state, source_breakdown, fallback_fields, data_quality = calibrate_state(defaults, indicators)
        raw_indicators = {**indicators, "baseline_note": item["baseline_note"]}
        agent = CountryAgent(
            code=item["code"],
            name=item["name"],
            region=item["region"],
            latitude=item["latitude"],
            longitude=item["longitude"],
            gdp_weight=item["gdp_weight"],
            state=state,
            risk_score=risk_from_state(state),
            data_quality_score=data_quality,
            source_breakdown=source_breakdown,
            fallback_fields=fallback_fields,
            raw_indicators=raw_indicators,
        )
        agents.append(agent)
    _AGENT_CACHE = agents
    return agents


def get_country_agent(code: str) -> CountryAgent | None:
    code = code.upper()
    return next((agent for agent in list_country_agents() if agent.code == code), None)


def agent_state_explanations(agent: CountryAgent) -> dict[str, str]:
    return explain_state(agent.name, agent.state, agent.source_breakdown)


def simulation_scenarios() -> list[SimulationScenario]:
    return [
        SimulationScenario(
            key="energy_squeeze",
            name="能源价格冲击",
            description="原油和天然气价格上行，能源进口经济体承压，外溢到通胀、利率和社会情绪。",
            shocks=[PolicyShock(shock_type="energy", target_codes=["EU", "JPN", "KOR", "IND", "CHN", "TUR", "VNM"], intensity=0.52, duration_months=8, propagation=0.38)],
        ),
        SimulationScenario(
            key="tariff_wall",
            name="关税壁垒升温",
            description="主要经济体提高关税，贸易暴露较高的制造业和出口型经济体受到第一轮影响。",
            shocks=[PolicyShock(shock_type="tariff", target_codes=["CHN", "USA", "EU", "MEX", "KOR", "JPN", "VNM", "TWN"], intensity=0.46, duration_months=6, propagation=0.42)],
        ),
        SimulationScenario(
            key="rate_shock",
            name="全球利率再定价",
            description="美元利率和全球融资成本上行，金融脆弱和外债压力较高的经济体风险放大。",
            shocks=[PolicyShock(shock_type="rate_hike", target_codes=["USA", "EU", "BRA", "ZAF", "TUR", "ARG", "EGY", "NGA"], intensity=0.42, duration_months=5, propagation=0.30)],
        ),
        SimulationScenario(
            key="sanctions_chain",
            name="制裁链条扩散",
            description="制裁从目标经济体向能源、金融和贸易伙伴传播，形成二阶连锁反应。",
            shocks=[PolicyShock(shock_type="sanction", target_codes=["RUS", "IRN"], intensity=0.60, duration_months=10, propagation=0.48)],
        ),
        SimulationScenario(
            key="regional_conflict",
            name="区域冲突外溢",
            description="热点地区冲突升温，通过能源、避险、贸易和邻近冲突边向周边经济体扩散。",
            shocks=[PolicyShock(shock_type="sanction", target_codes=["UKR", "ISR", "IRN", "EGY"], intensity=0.50, duration_months=7, propagation=0.44)],
        ),
    ]


def network_edges() -> list[dict[str, float | str]]:
    edges: list[dict[str, float | str]] = []
    for source, targets in _NETWORK.items():
        for target, channels in targets.items():
            for channel, weight in channels.items():
                edges.append({"source": source, "target": target, "channel": channel, "weight": weight})
    return edges


_STATE_DEFAULTS = [
    "gdp_pressure",
    "trade_exposure",
    "energy_vulnerability",
    "military_pressure",
    "sentiment_pressure",
    "rate_pressure",
    "conflict_pressure",
]

_AGENT_ROWS = [
    {"code": "USA", "name": "美国", "region": "北美", "latitude": 38.9, "longitude": -77.0, "gdp_weight": 0.245, "gdp_pressure": 35, "trade_exposure": 42, "energy_vulnerability": 28, "military_pressure": 58, "sentiment_pressure": 48, "rate_pressure": 62, "conflict_pressure": 42, "baseline_note": "G20核心金融与安全节点"},
    {"code": "CHN", "name": "中国", "region": "东亚", "latitude": 39.9, "longitude": 116.4, "gdp_weight": 0.175, "gdp_pressure": 45, "trade_exposure": 68, "energy_vulnerability": 66, "military_pressure": 44, "sentiment_pressure": 42, "rate_pressure": 38, "conflict_pressure": 36, "baseline_note": "制造业、贸易和能源进口关键节点"},
    {"code": "EU", "name": "欧盟", "region": "欧洲", "latitude": 50.8, "longitude": 4.4, "gdp_weight": 0.165, "gdp_pressure": 42, "trade_exposure": 64, "energy_vulnerability": 58, "military_pressure": 36, "sentiment_pressure": 45, "rate_pressure": 52, "conflict_pressure": 50, "baseline_note": "以 World Bank EUU 作为代理"},
    {"code": "JPN", "name": "日本", "region": "东亚", "latitude": 35.7, "longitude": 139.7, "gdp_weight": 0.042, "gdp_pressure": 48, "trade_exposure": 56, "energy_vulnerability": 78, "military_pressure": 34, "sentiment_pressure": 36, "rate_pressure": 34, "conflict_pressure": 34, "baseline_note": "高能源进口敏感经济体"},
    {"code": "DEU", "name": "德国", "region": "欧洲", "latitude": 52.5, "longitude": 13.4, "gdp_weight": 0.041, "gdp_pressure": 44, "trade_exposure": 72, "energy_vulnerability": 62, "military_pressure": 28, "sentiment_pressure": 40, "rate_pressure": 50, "conflict_pressure": 42, "baseline_note": "欧洲制造与贸易枢纽"},
    {"code": "IND", "name": "印度", "region": "南亚", "latitude": 28.6, "longitude": 77.2, "gdp_weight": 0.037, "gdp_pressure": 38, "trade_exposure": 48, "energy_vulnerability": 72, "military_pressure": 46, "sentiment_pressure": 44, "rate_pressure": 50, "conflict_pressure": 42, "baseline_note": "能源进口与增长敏感经济体"},
    {"code": "GBR", "name": "英国", "region": "欧洲", "latitude": 51.5, "longitude": -0.1, "gdp_weight": 0.032, "gdp_pressure": 44, "trade_exposure": 54, "energy_vulnerability": 50, "military_pressure": 34, "sentiment_pressure": 46, "rate_pressure": 56, "conflict_pressure": 40, "baseline_note": "金融与欧洲安全链条节点"},
    {"code": "FRA", "name": "法国", "region": "欧洲", "latitude": 48.9, "longitude": 2.3, "gdp_weight": 0.030, "gdp_pressure": 42, "trade_exposure": 52, "energy_vulnerability": 44, "military_pressure": 36, "sentiment_pressure": 48, "rate_pressure": 52, "conflict_pressure": 42, "baseline_note": "欧洲核心经济体"},
    {"code": "RUS", "name": "俄罗斯", "region": "欧亚", "latitude": 55.8, "longitude": 37.6, "gdp_weight": 0.021, "gdp_pressure": 62, "trade_exposure": 54, "energy_vulnerability": 18, "military_pressure": 82, "sentiment_pressure": 66, "rate_pressure": 58, "conflict_pressure": 86, "baseline_note": "能源出口与冲突高暴露节点"},
    {"code": "BRA", "name": "巴西", "region": "拉美", "latitude": -15.8, "longitude": -47.9, "gdp_weight": 0.021, "gdp_pressure": 46, "trade_exposure": 44, "energy_vulnerability": 32, "military_pressure": 22, "sentiment_pressure": 48, "rate_pressure": 60, "conflict_pressure": 28, "baseline_note": "大宗商品与新兴市场节点"},
    {"code": "CAN", "name": "加拿大", "region": "北美", "latitude": 45.4, "longitude": -75.7, "gdp_weight": 0.020, "gdp_pressure": 36, "trade_exposure": 58, "energy_vulnerability": 22, "military_pressure": 24, "sentiment_pressure": 34, "rate_pressure": 52, "conflict_pressure": 22, "baseline_note": "北美能源与贸易节点"},
    {"code": "KOR", "name": "韩国", "region": "东亚", "latitude": 37.6, "longitude": 127.0, "gdp_weight": 0.018, "gdp_pressure": 42, "trade_exposure": 78, "energy_vulnerability": 76, "military_pressure": 54, "sentiment_pressure": 42, "rate_pressure": 48, "conflict_pressure": 48, "baseline_note": "高贸易和能源进口敏感经济体"},
    {"code": "AUS", "name": "澳大利亚", "region": "大洋洲", "latitude": -35.3, "longitude": 149.1, "gdp_weight": 0.016, "gdp_pressure": 34, "trade_exposure": 54, "energy_vulnerability": 24, "military_pressure": 28, "sentiment_pressure": 34, "rate_pressure": 50, "conflict_pressure": 24, "baseline_note": "资源出口与亚太贸易节点"},
    {"code": "MEX", "name": "墨西哥", "region": "北美", "latitude": 19.4, "longitude": -99.1, "gdp_weight": 0.014, "gdp_pressure": 44, "trade_exposure": 74, "energy_vulnerability": 40, "military_pressure": 26, "sentiment_pressure": 52, "rate_pressure": 56, "conflict_pressure": 36, "baseline_note": "北美供应链节点"},
    {"code": "IDN", "name": "印度尼西亚", "region": "东南亚", "latitude": -6.2, "longitude": 106.8, "gdp_weight": 0.013, "gdp_pressure": 40, "trade_exposure": 50, "energy_vulnerability": 38, "military_pressure": 30, "sentiment_pressure": 42, "rate_pressure": 50, "conflict_pressure": 30, "baseline_note": "东南亚大宗商品与人口节点"},
    {"code": "SAU", "name": "沙特", "region": "中东", "latitude": 24.7, "longitude": 46.7, "gdp_weight": 0.011, "gdp_pressure": 38, "trade_exposure": 56, "energy_vulnerability": 12, "military_pressure": 52, "sentiment_pressure": 42, "rate_pressure": 42, "conflict_pressure": 58, "baseline_note": "全球能源出口关键节点"},
    {"code": "TUR", "name": "土耳其", "region": "中东", "latitude": 39.9, "longitude": 32.9, "gdp_weight": 0.010, "gdp_pressure": 58, "trade_exposure": 58, "energy_vulnerability": 68, "military_pressure": 54, "sentiment_pressure": 60, "rate_pressure": 72, "conflict_pressure": 54, "baseline_note": "欧亚能源与地缘通道"},
    {"code": "ZAF", "name": "南非", "region": "非洲", "latitude": -25.7, "longitude": 28.2, "gdp_weight": 0.004, "gdp_pressure": 58, "trade_exposure": 48, "energy_vulnerability": 54, "military_pressure": 24, "sentiment_pressure": 60, "rate_pressure": 66, "conflict_pressure": 34, "baseline_note": "非洲金融和资源节点"},
    {"code": "ARG", "name": "阿根廷", "region": "拉美", "latitude": -34.6, "longitude": -58.4, "gdp_weight": 0.006, "gdp_pressure": 72, "trade_exposure": 40, "energy_vulnerability": 42, "military_pressure": 20, "sentiment_pressure": 62, "rate_pressure": 80, "conflict_pressure": 26, "baseline_note": "高通胀和融资压力节点"},
    {"code": "IRN", "name": "伊朗", "region": "中东", "latitude": 35.7, "longitude": 51.4, "gdp_weight": 0.004, "gdp_pressure": 66, "trade_exposure": 46, "energy_vulnerability": 20, "military_pressure": 72, "sentiment_pressure": 68, "rate_pressure": 64, "conflict_pressure": 76, "baseline_note": "制裁与区域冲突高暴露节点"},
    {"code": "UKR", "name": "乌克兰", "region": "欧洲热点", "latitude": 50.5, "longitude": 30.5, "gdp_weight": 0.002, "gdp_pressure": 80, "trade_exposure": 58, "energy_vulnerability": 64, "military_pressure": 92, "sentiment_pressure": 76, "rate_pressure": 72, "conflict_pressure": 95, "baseline_note": "欧洲冲突热点"},
    {"code": "ISR", "name": "以色列", "region": "中东热点", "latitude": 31.8, "longitude": 35.2, "gdp_weight": 0.005, "gdp_pressure": 42, "trade_exposure": 60, "energy_vulnerability": 48, "military_pressure": 82, "sentiment_pressure": 62, "rate_pressure": 48, "conflict_pressure": 82, "baseline_note": "中东安全热点"},
    {"code": "EGY", "name": "埃及", "region": "中东非洲", "latitude": 30.0, "longitude": 31.2, "gdp_weight": 0.004, "gdp_pressure": 66, "trade_exposure": 44, "energy_vulnerability": 58, "military_pressure": 42, "sentiment_pressure": 62, "rate_pressure": 72, "conflict_pressure": 48, "baseline_note": "苏伊士和粮食能源敏感节点"},
    {"code": "VNM", "name": "越南", "region": "东南亚", "latitude": 21.0, "longitude": 105.8, "gdp_weight": 0.004, "gdp_pressure": 36, "trade_exposure": 88, "energy_vulnerability": 54, "military_pressure": 34, "sentiment_pressure": 40, "rate_pressure": 48, "conflict_pressure": 30, "baseline_note": "高贸易开放制造业节点"},
    {"code": "TWN", "name": "台湾", "region": "东亚热点", "latitude": 25.0, "longitude": 121.5, "gdp_weight": 0.008, "gdp_pressure": 40, "trade_exposure": 86, "energy_vulnerability": 82, "military_pressure": 62, "sentiment_pressure": 50, "rate_pressure": 42, "conflict_pressure": 58, "baseline_note": "World Bank 缺少台湾独立序列，使用可解释兜底"},
    {"code": "SGP", "name": "新加坡", "region": "东南亚", "latitude": 1.3, "longitude": 103.8, "gdp_weight": 0.004, "gdp_pressure": 32, "trade_exposure": 96, "energy_vulnerability": 82, "military_pressure": 36, "sentiment_pressure": 36, "rate_pressure": 44, "conflict_pressure": 24, "baseline_note": "贸易和金融枢纽"},
    {"code": "ARE", "name": "阿联酋", "region": "中东", "latitude": 24.5, "longitude": 54.4, "gdp_weight": 0.005, "gdp_pressure": 34, "trade_exposure": 78, "energy_vulnerability": 10, "military_pressure": 42, "sentiment_pressure": 38, "rate_pressure": 44, "conflict_pressure": 38, "baseline_note": "能源、贸易和金融枢纽"},
    {"code": "NGA", "name": "尼日利亚", "region": "非洲", "latitude": 9.1, "longitude": 7.5, "gdp_weight": 0.004, "gdp_pressure": 62, "trade_exposure": 42, "energy_vulnerability": 22, "military_pressure": 34, "sentiment_pressure": 66, "rate_pressure": 70, "conflict_pressure": 58, "baseline_note": "非洲人口、能源和安全节点"},
]

_NETWORK = {
    "USA": {"CHN": {"trade": 0.72, "financial": 0.82}, "EU": {"trade": 0.64, "financial": 0.80}, "MEX": {"trade": 0.82}, "CAN": {"trade": 0.78, "energy": 0.34}, "JPN": {"financial": 0.45, "trade": 0.42}, "TWN": {"financial": 0.34, "trade": 0.28}},
    "CHN": {"USA": {"trade": 0.70}, "EU": {"trade": 0.62}, "KOR": {"trade": 0.68}, "JPN": {"trade": 0.58}, "AUS": {"trade": 0.52, "energy": 0.30}, "IDN": {"trade": 0.42}, "VNM": {"trade": 0.48}, "TWN": {"trade": 0.50, "conflict": 0.32}},
    "EU": {"USA": {"financial": 0.64, "trade": 0.56}, "RUS": {"energy": 0.62, "conflict": 0.52}, "DEU": {"trade": 0.84, "financial": 0.50}, "FRA": {"trade": 0.62}, "TUR": {"trade": 0.36, "conflict": 0.28}, "UKR": {"conflict": 0.60, "trade": 0.30}, "EGY": {"trade": 0.24, "energy": 0.20}},
    "DEU": {"EU": {"trade": 0.84}, "CHN": {"trade": 0.46}, "RUS": {"energy": 0.42}},
    "RUS": {"EU": {"energy": 0.66, "conflict": 0.56}, "TUR": {"energy": 0.38, "conflict": 0.26}, "CHN": {"energy": 0.42, "trade": 0.32}, "UKR": {"conflict": 0.82, "energy": 0.28}},
    "UKR": {"EU": {"conflict": 0.48, "trade": 0.26}, "RUS": {"conflict": 0.70}},
    "SAU": {"EU": {"energy": 0.44}, "CHN": {"energy": 0.48}, "IND": {"energy": 0.52}, "JPN": {"energy": 0.46}, "KOR": {"energy": 0.46}, "EGY": {"energy": 0.26}},
    "IRN": {"SAU": {"conflict": 0.46, "energy": 0.34}, "TUR": {"conflict": 0.32}, "EU": {"energy": 0.26}, "IND": {"energy": 0.28}, "ISR": {"conflict": 0.52}, "ARE": {"energy": 0.28, "conflict": 0.30}},
    "ISR": {"IRN": {"conflict": 0.52}, "EGY": {"conflict": 0.28, "trade": 0.18}, "TUR": {"conflict": 0.20}},
    "JPN": {"KOR": {"trade": 0.46}, "USA": {"financial": 0.42}, "CHN": {"trade": 0.52}, "TWN": {"trade": 0.32}},
    "KOR": {"CHN": {"trade": 0.58}, "USA": {"trade": 0.38}, "JPN": {"trade": 0.36}, "TWN": {"trade": 0.30}},
    "IND": {"CHN": {"trade": 0.30, "conflict": 0.26}, "SAU": {"energy": 0.34}, "EU": {"trade": 0.28}, "ARE": {"energy": 0.34, "trade": 0.26}},
    "BRA": {"CHN": {"trade": 0.44}, "USA": {"financial": 0.28}, "ARG": {"trade": 0.34}},
    "ARG": {"BRA": {"trade": 0.42}, "USA": {"financial": 0.22}},
    "TUR": {"EU": {"trade": 0.38}, "RUS": {"energy": 0.34, "conflict": 0.28}, "IRN": {"conflict": 0.26}, "EGY": {"trade": 0.18}},
    "ZAF": {"CHN": {"trade": 0.32}, "EU": {"trade": 0.28}, "USA": {"financial": 0.20}, "NGA": {"trade": 0.18}},
    "AUS": {"CHN": {"trade": 0.54}, "JPN": {"energy": 0.28}, "KOR": {"energy": 0.26}},
    "CAN": {"USA": {"trade": 0.76, "energy": 0.32}},
    "MEX": {"USA": {"trade": 0.82}},
    "IDN": {"CHN": {"trade": 0.36}, "JPN": {"energy": 0.22}, "IND": {"trade": 0.22}, "SGP": {"trade": 0.24}},
    "VNM": {"CHN": {"trade": 0.42}, "USA": {"trade": 0.36}, "KOR": {"trade": 0.30}, "SGP": {"trade": 0.24}},
    "TWN": {"CHN": {"trade": 0.48, "conflict": 0.30}, "USA": {"trade": 0.32, "financial": 0.24}, "JPN": {"trade": 0.28}},
    "SGP": {"CHN": {"trade": 0.32, "financial": 0.24}, "USA": {"financial": 0.28}, "IDN": {"trade": 0.24}, "VNM": {"trade": 0.22}},
    "ARE": {"IND": {"energy": 0.34, "trade": 0.26}, "IRN": {"conflict": 0.24}, "SAU": {"energy": 0.22}, "EGY": {"trade": 0.20}},
    "EGY": {"EU": {"trade": 0.24}, "SAU": {"energy": 0.24}, "ISR": {"conflict": 0.22}, "TUR": {"trade": 0.18}},
    "NGA": {"EU": {"energy": 0.22, "trade": 0.18}, "CHN": {"trade": 0.26}, "ZAF": {"trade": 0.18}},
}
