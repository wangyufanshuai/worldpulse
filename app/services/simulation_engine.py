from __future__ import annotations

from collections import defaultdict

import numpy as np

from app.core.models import (
    AgentState,
    CountryAgent,
    CountrySimulationResult,
    PolicyShock,
    SimulationDriver,
    SimulationMapPoint,
    SimulationPathPoint,
    SimulationPropagationEdge,
    SimulationRequest,
    SimulationResult,
)
from app.services.simulation_data import list_country_agents, network_edges, simulation_scenarios

STATE_KEYS = [
    "gdp_pressure",
    "trade_exposure",
    "energy_vulnerability",
    "military_pressure",
    "sentiment_pressure",
    "rate_pressure",
    "conflict_pressure",
]

STATE_WEIGHTS = np.array([0.18, 0.16, 0.16, 0.13, 0.12, 0.13, 0.12])

SHOCK_VECTORS = {
    "sanction": np.array([10, 16, 10, 8, 12, 8, 12], dtype=float),
    "tariff": np.array([8, 18, 6, 2, 8, 5, 3], dtype=float),
    "energy": np.array([8, 5, 22, 4, 10, 8, 6], dtype=float),
    "rate_hike": np.array([12, 4, 3, 1, 10, 22, 2], dtype=float),
    "rate_cut": np.array([-8, 1, 1, 0, -4, -14, 0], dtype=float),
}

CHANNEL_TO_STATE = {
    "trade": {"trade_exposure": 0.45, "gdp_pressure": 0.25, "sentiment_pressure": 0.12},
    "energy": {"energy_vulnerability": 0.55, "gdp_pressure": 0.18, "rate_pressure": 0.14},
    "financial": {"rate_pressure": 0.48, "gdp_pressure": 0.22, "sentiment_pressure": 0.16},
    "conflict": {"conflict_pressure": 0.50, "military_pressure": 0.28, "sentiment_pressure": 0.14},
}


def list_agents() -> list[CountryAgent]:
    return list_country_agents()


def list_scenarios():
    return simulation_scenarios()


def run_simulation(request: SimulationRequest) -> SimulationResult:
    agents = list_country_agents()
    horizon = int(np.clip(request.horizon_months, 3, 36))
    runs = int(np.clip(request.runs, 50, 2000))
    rng = np.random.default_rng(request.seed)
    codes = [agent.code for agent in agents]
    weights = _normalized_weights(agents)
    initial = np.array([_state_vector(agent.state) for agent in agents], dtype=float)
    quality = np.array([agent.data_quality_score for agent in agents], dtype=float)
    graph = _edge_graph()

    all_paths = np.zeros((runs, horizon + 1, len(agents)), dtype=float)
    impact_totals: defaultdict[str, float] = defaultdict(float)
    edge_impacts: defaultdict[tuple[str, str, str], float] = defaultdict(float)

    for run in range(runs):
        state = initial.copy()
        all_paths[run, 0, :] = _risk_scores(state)
        memory = np.zeros_like(state)
        for month in range(1, horizon + 1):
            direct = _direct_shock_matrix(request.shocks, codes, state, month)
            propagated, edge_month_impacts = _propagate(state, direct, graph, codes, request.shocks)
            feedback = _system_feedback(state)
            noise_scale = 1.05 + (100 - quality).reshape(-1, 1) / 100 * 1.25 + month * 0.04
            noise = rng.normal(0, noise_scale, size=state.shape)
            memory = memory * 0.55 + direct * 0.45
            state = np.clip(state * 0.965 + initial * 0.035 + memory * 0.08 + direct + propagated + feedback + noise, 0, 100)
            all_paths[run, month, :] = _risk_scores(state)
            if run < min(runs, 200):
                for key, value in _driver_impacts(direct, propagated, feedback).items():
                    impact_totals[key] += value
                for edge_key, value in edge_month_impacts.items():
                    edge_impacts[edge_key] += value

    global_paths = all_paths @ weights
    global_path = [
        SimulationPathPoint(
            month=month,
            p10=round(float(np.percentile(global_paths[:, month], 10)), 2),
            p50=round(float(np.percentile(global_paths[:, month], 50)), 2),
            p90=round(float(np.percentile(global_paths[:, month], 90)), 2),
        )
        for month in range(horizon + 1)
    ]
    country_results = _country_results(agents, all_paths)
    map_points = [
        SimulationMapPoint(code=item.code, name=item.name, latitude=item.latitude, longitude=item.longitude, risk=item.p50, uncertainty=item.uncertainty, region=item.region)
        for item in country_results
    ]
    drivers = _top_drivers(impact_totals)
    return SimulationResult(
        summary=_summary(global_path, country_results, drivers),
        horizon_months=horizon,
        runs=runs,
        global_path=global_path,
        countries=country_results,
        map_points=map_points,
        propagation_edges=_top_edges(edge_impacts),
        drivers=drivers,
    )


def _state_vector(state: AgentState) -> np.ndarray:
    return np.array([getattr(state, key) for key in STATE_KEYS], dtype=float)


def _risk_scores(states: np.ndarray) -> np.ndarray:
    return np.clip(states @ STATE_WEIGHTS, 0, 100)


def _normalized_weights(agents: list[CountryAgent]) -> np.ndarray:
    raw = np.array([max(agent.gdp_weight, 0.002) for agent in agents], dtype=float)
    return raw / raw.sum()


def _edge_graph() -> dict[str, list[dict[str, float | str]]]:
    graph: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    for edge in network_edges():
        graph[str(edge["source"])].append(edge)
    return graph


def _direct_shock_matrix(shocks: list[PolicyShock], codes: list[str], state: np.ndarray, month: int) -> np.ndarray:
    matrix = np.zeros((len(codes), len(STATE_KEYS)), dtype=float)
    index = {code: idx for idx, code in enumerate(codes)}
    for shock in shocks:
        if month > max(1, shock.duration_months):
            continue
        vector = SHOCK_VECTORS.get(shock.shock_type, SHOCK_VECTORS["tariff"]) * float(np.clip(shock.intensity, 0, 1.5))
        decay = max(1 - (month - 1) / max(shock.duration_months * 1.45, 1), 0.22)
        for code in shock.target_codes:
            if code not in index:
                continue
            idx = index[code]
            sensitivity = _shock_sensitivity(shock.shock_type, state[idx])
            matrix[idx] += vector * decay * sensitivity
    return matrix


def _shock_sensitivity(shock_type: str, state_row: np.ndarray) -> float:
    values = dict(zip(STATE_KEYS, state_row))
    if shock_type == "energy":
        return 0.7 + values["energy_vulnerability"] / 100 * 0.75
    if shock_type == "tariff":
        return 0.75 + values["trade_exposure"] / 100 * 0.70
    if shock_type == "rate_hike":
        return 0.75 + values["rate_pressure"] / 100 * 0.65 + values["gdp_pressure"] / 100 * 0.20
    if shock_type == "rate_cut":
        return 0.65 + values["rate_pressure"] / 100 * 0.55
    if shock_type == "sanction":
        return 0.75 + values["trade_exposure"] / 100 * 0.28 + values["conflict_pressure"] / 100 * 0.38
    return 1.0


def _propagate(
    state: np.ndarray,
    direct: np.ndarray,
    graph: dict[str, list[dict[str, float | str]]],
    codes: list[str],
    shocks: list[PolicyShock],
) -> tuple[np.ndarray, dict[tuple[str, str, str], float]]:
    index = {code: idx for idx, code in enumerate(codes)}
    propagated = np.zeros_like(state)
    edge_impacts: dict[tuple[str, str, str], float] = defaultdict(float)
    propagation_scale = np.mean([shock.propagation for shock in shocks]) if shocks else 0.32
    source_pressure = _risk_scores(direct + state * 0.18)
    for source, edges in graph.items():
        if source not in index:
            continue
        source_idx = index[source]
        for edge in edges:
            target = str(edge["target"])
            channel = str(edge["channel"])
            if target not in index:
                continue
            target_idx = index[target]
            weight = float(edge["weight"])
            impact = source_pressure[source_idx] * weight * propagation_scale * 0.055
            for state_key, channel_weight in CHANNEL_TO_STATE[channel].items():
                propagated[target_idx, STATE_KEYS.index(state_key)] += impact * channel_weight
            edge_impacts[(source, target, channel)] += impact
    return propagated, edge_impacts


def _system_feedback(state: np.ndarray) -> np.ndarray:
    risk = _risk_scores(state)
    global_stress = float(np.mean(risk))
    feedback = np.zeros_like(state)
    if global_stress > 55:
        feedback[:, STATE_KEYS.index("sentiment_pressure")] += (global_stress - 55) * 0.028
        feedback[:, STATE_KEYS.index("rate_pressure")] += (global_stress - 55) * 0.018
    high_conflict = state[:, STATE_KEYS.index("conflict_pressure")]
    feedback[:, STATE_KEYS.index("energy_vulnerability")] += np.clip(high_conflict - 60, 0, 40) * 0.018
    return feedback


def _driver_impacts(direct: np.ndarray, propagated: np.ndarray, feedback: np.ndarray) -> dict[str, float]:
    return {
        "直接政策冲击": float(np.abs(direct).sum()),
        "网络外溢传播": float(np.abs(propagated).sum()),
        "系统动力学反馈": float(np.abs(feedback).sum()),
    }


def _country_results(agents: list[CountryAgent], all_paths: np.ndarray) -> list[CountrySimulationResult]:
    end = all_paths[:, -1, :]
    start = all_paths[:, 0, :]
    results = []
    for idx, agent in enumerate(agents):
        p10 = float(np.percentile(end[:, idx], 10))
        p50 = float(np.percentile(end[:, idx], 50))
        p90 = float(np.percentile(end[:, idx], 90))
        start_risk = float(np.percentile(start[:, idx], 50))
        results.append(
            CountrySimulationResult(
                code=agent.code,
                name=agent.name,
                region=agent.region,
                latitude=agent.latitude,
                longitude=agent.longitude,
                start_risk=round(start_risk, 2),
                p10=round(p10, 2),
                p50=round(p50, 2),
                p90=round(p90, 2),
                uncertainty=round(p90 - p10, 2),
                upside_probability=round(float((end[:, idx] > start_risk + 5).mean()), 3),
            )
        )
    return sorted(results, key=lambda item: item.p50 - item.start_risk, reverse=True)


def _top_edges(edge_impacts: dict[tuple[str, str, str], float]) -> list[SimulationPropagationEdge]:
    if not edge_impacts:
        return []
    max_impact = max(edge_impacts.values()) or 1
    return [
        SimulationPropagationEdge(source=source, target=target, channel=channel, weight=round(float(impact / max_impact), 3), impact=round(float(impact), 2))
        for (source, target, channel), impact in sorted(edge_impacts.items(), key=lambda item: item[1], reverse=True)[:16]
    ]


def _top_drivers(impact_totals: dict[str, float]) -> list[SimulationDriver]:
    total = sum(impact_totals.values()) or 1
    explanations = {
        "直接政策冲击": "政策本身对目标经济体的 GDP、贸易、能源、利率和舆情压力产生第一轮影响。",
        "网络外溢传播": "贸易、能源、金融和冲突边把目标经济体压力传导给相邻或高度互联经济体。",
        "系统动力学反馈": "当全球压力抬升后，风险偏好、融资环境和能源脆弱性出现二阶反馈。",
    }
    return [
        SimulationDriver(name=name, contribution=round(value / total * 100, 1), explanation=explanations[name])
        for name, value in sorted(impact_totals.items(), key=lambda item: item[1], reverse=True)
    ]


def _summary(path: list[SimulationPathPoint], countries: list[CountrySimulationResult], drivers: list[SimulationDriver]) -> str:
    start = path[0].p50
    end = path[-1].p50
    top = countries[0]
    driver = drivers[0].name if drivers else "网络传播"
    return (
        f"基线中位全球风险从 {start:.1f} 变化到 {end:.1f}。"
        f"最明显承压经济体是{top.name}，12个月中位风险较初始高 {top.p50 - top.start_risk:+.1f} 分。"
        f"主要解释来自{driver}；结果展示分位区间，不代表确定性预测。"
    )
