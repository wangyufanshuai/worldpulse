from __future__ import annotations

from copy import deepcopy

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.core.negotiation_models import NarrativeDiffusionAudit
from app.services.agent_contract.models import AgentActionProposal
from app.services.consistency.hashing import stable_hash


TONE_DELTAS = {"stabilizing": -4.0, "informational": -1.0, "firm": 3.0}


def apply_narrative_diffusion(
    state: WarRoomRun,
    proposals: list[AgentActionProposal],
    cumulative_deltas: dict[str, float] | None = None,
    *,
    seed: int = 42,
) -> tuple[WarRoomScenarioRequest, NarrativeDiffusionAudit, dict[str, float]]:
    cumulative = {key: float(value) for key, value in (cumulative_deltas or {}).items()}
    countries = {item.code: item for item in state.country_agents}
    applications: list[dict] = []
    tick_deltas: dict[str, float] = {}
    for proposal in sorted((item for item in proposals if item.action_type == "public_narrative"), key=lambda item: item.proposal_id):
        target_codes = [item.split(":", 1)[1] for item in proposal.target_ids if item.startswith("country:") and item.split(":", 1)[1] in countries]
        tone = proposal.parameters["tone"]
        audience = proposal.parameters["audience"]
        base = TONE_DELTAS[tone]
        for target_code in target_codes:
            target = countries[target_code]
            for receiver_code, receiver in sorted(countries.items()):
                if receiver_code == target_code:
                    multiplier = 1.0
                elif audience == "domestic":
                    continue
                elif audience == "regional" and receiver.region == target.region:
                    multiplier = 0.5
                elif audience == "global":
                    multiplier = 0.25
                else:
                    continue
                alliance_multiplier = 1.25 if receiver_code != target_code and receiver.alliance == target.alliance else 1.0
                effective_multiplier = min(1.0, multiplier * alliance_multiplier)
                delta = round(base * effective_multiplier, 4)
                before = cumulative.get(receiver_code, 0.0)
                after = _clamp(before + delta, -8.0, 8.0)
                applied = round(after - before, 4)
                cumulative[receiver_code] = after
                tick_deltas[receiver_code] = round(tick_deltas.get(receiver_code, 0.0) + applied, 4)
                applications.append({
                    "proposal_id": proposal.proposal_id, "target_country": target_code, "receiver_country": receiver_code,
                    "tone": tone, "audience": audience, "base_delta": base, "propagation_multiplier": multiplier,
                    "alliance_multiplier": alliance_multiplier, "effective_multiplier": effective_multiplier,
                    "applied_delta": applied, "cumulative_delta": after,
                })

    country_overrides = deepcopy(state.scenario.country_overrides)
    for code, cumulative_delta in cumulative.items():
        country = countries.get(code)
        if country is None:
            continue
        override = dict(country_overrides.get(code, {}))
        override["public_opinion_pressure"] = round(_clamp(country.public_opinion_pressure + tick_deltas.get(code, 0.0), 0.0, 100.0), 4)
        country_overrides[code] = override
    request = WarRoomScenarioRequest(
        scenario_key=state.scenario.key,
        duration_days=state.scenario.duration_days,
        intensity=state.scenario.intensity,
        propagation=state.scenario.propagation,
        target_countries=list(state.scenario.target_countries),
        target_chains=list(state.scenario.target_chains),
        policy_actions=list(state.scenario.policy_actions),
        country_overrides=country_overrides,
        chain_overrides=deepcopy(state.scenario.chain_overrides),
        seed=seed,
    )
    core = {
        "schema_version": "narrative-diffusion.v1",
        "seed": seed,
        "tone_deltas": TONE_DELTAS,
        "country_deltas": tick_deltas,
        "applications": applications,
    }
    return request, NarrativeDiffusionAudit(**core, audit_hash=stable_hash(core)), cumulative


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
