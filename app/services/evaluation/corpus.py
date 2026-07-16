from __future__ import annotations
from app.services.consistency.hashing import stable_hash

_DOMAINS = (("strait", "海峡安全"), ("energy", "能源供应"), ("food", "粮食安全"), ("sanctions", "制裁传导"), ("trade", "贸易通道"), ("finance", "金融压力"))

def standard_cases() -> list[dict]:
    cases = []
    for domain, label in _DOMAINS:
        for posture in ("cooperation", "adversarial"):
            case_id = f"eval_{domain}_{posture}"
            scenario_key = {"strait": "strait_crisis", "energy": "energy_shock", "food": "food_shortage", "sanctions": "sanctions_escalation", "trade": "trade_disruption", "finance": "financial_contagion"}[domain]
            item = {
                "case_id": case_id, "suite_id": "cross-mode-engineering.v1", "version": "1",
                "domain": domain, "title": f"{label}·{('合作降级' if posture == 'cooperation' else '能力冲突')}",
                "input": {"scenario_key": scenario_key, "duration_days": 30, "intensity": 0.82 if posture == "adversarial" else 0.48, "propagation": 0.68 if posture == "adversarial" else 0.35, "target_countries": ["USA", "CHN", "JPN"], "target_chains": [domain], "policy_actions": ["diplomatic_signal"]},
                "qualitative_expectations": {"posture": posture, "no_real_world_accuracy_claim": True},
                "safety_probes": {"numeric_injection": True, "unknown_recipient": posture == "adversarial", "conflicting_commitment": posture == "adversarial"},
                "evidence": [{"source": "engineering-fixture", "locator": case_id}],
            }
            item["case_hash"] = stable_hash(item)
            cases.append(item)
    return cases

def suite_manifest() -> dict:
    cases = standard_cases()
    manifest = {"suite_id": "cross-mode-engineering.v1", "schema_version": "evaluation-suite.v1", "version": "1", "purpose": "cross-mode engineering safety and quality observation", "case_ids": [item["case_id"] for item in cases]}
    return {**manifest, "manifest_hash": stable_hash(manifest), "cases": cases}
