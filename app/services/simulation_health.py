from __future__ import annotations

from app.core.models import SimulationDataHealth
from app.services.country_data import country_data_cache_health
from app.services.simulation_data import list_country_agents


def build_simulation_data_health() -> list[SimulationDataHealth]:
    agents = list_country_agents()
    real_count = sum(len(agent.source_breakdown) - len(agent.fallback_fields) for agent in agents)
    fallback_count = sum(len(agent.fallback_fields) for agent in agents)
    cache_file, age, note = country_data_cache_health()
    status = "真实数据+兜底" if real_count and fallback_count else "真实数据" if real_count else "兜底"
    return [
        SimulationDataHealth(
            source="World Bank Indicators API",
            status=status,
            cache_file=str(cache_file) if cache_file else None,
            cache_age_hours=age,
            agent_count=len(agents),
            real_field_count=max(real_count, 0),
            fallback_field_count=fallback_count,
            note=note,
        ),
        SimulationDataHealth(
            source="全球公共风险代理",
            status="复用现有数据源",
            cache_file="data/cache",
            cache_age_hours=None,
            agent_count=len(agents),
            real_field_count=len(agents) * 3,
            fallback_field_count=0,
            note="舆情、利率、冲突压力复用 WUI、FRED、UCDP/GDELT 等全局或区域代理信号。",
        ),
    ]
