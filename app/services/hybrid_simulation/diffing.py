from __future__ import annotations

from app.core.models import WarRoomRun


def build_hybrid_snapshot_diff(baseline: WarRoomRun, final: WarRoomRun) -> dict:
    base_countries = {item.country_code: item for item in baseline.risk_heatmap}
    country_rows = []
    for item in final.risk_heatmap:
        base = base_countries.get(item.country_code)
        if base is None:
            continue
        country_rows.append({
            "country_code": item.country_code,
            "country_name": item.country_name,
            "baseline": round(base.risk, 1),
            "hybrid": round(item.risk, 1),
            "delta": round(item.risk - base.risk, 1),
        })
    base_chains = {item.key: item for item in baseline.supply_chains}
    chain_rows = []
    for item in final.supply_chains:
        base = base_chains.get(item.key)
        if base is None:
            continue
        chain_rows.append({
            "key": item.key,
            "name": item.name,
            "baseline": round(base.pressure_score, 1),
            "hybrid": round(item.pressure_score, 1),
            "delta": round(item.pressure_score - base.pressure_score, 1),
        })
    baseline_end = baseline.timeline[-1].global_risk if baseline.timeline else None
    final_end = final.timeline[-1].global_risk if final.timeline else None
    return {
        "global_risk": {
            "baseline": baseline_end,
            "hybrid": final_end,
            "delta": round(final_end - baseline_end, 1) if baseline_end is not None and final_end is not None else None,
        },
        "country_risk": sorted(country_rows, key=lambda item: (-abs(item["delta"]), item["country_code"])),
        "supply_chain_pressure": sorted(chain_rows, key=lambda item: (-abs(item["delta"]), item["key"])),
        "baseline_policy_actions": list(baseline.scenario.policy_actions),
        "hybrid_policy_actions": list(final.scenario.policy_actions),
    }
