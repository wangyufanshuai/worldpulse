import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.models import WarRoomScenarioRequest
from app.services.agent_contract.models import AgentActionProposal
from app.services.negotiation.diffusion import apply_narrative_diffusion
from app.services.negotiation.semantics import alliance_commitment_conflicts, response_is_authorized
from app.services.war_room_engine import run_war_room


CASES = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path("tests/negotiation_golden").glob("*.json"))]


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["case_id"])
def test_v18_negotiation_golden_scenarios(case):
    if case["kind"] == "response":
        parent = SimpleNamespace(
            message_id="parent", tick=case["parent_tick"], sender_agent_id=case["recipient"],
            recipient_agent_ids=[case["sender"]],
        )
        response = SimpleNamespace(
            parent_message_id="parent", tick=case["response_tick"], sender_agent_id=case["sender"],
            recipient_agent_ids=[case["recipient"]],
        )
        assert response_is_authorized(parent, response) is case["authorized"]
        assert case["result_status"] == {"accept": "active", "reject": "rejected"}[case["message_type"]]
        return
    if case["kind"] == "conflict":
        candidate = SimpleNamespace(action_type=case["action_type"], party_agent_ids=case["parties"], status="proposed")
        existing = SimpleNamespace(action_type=case["action_type"], party_agent_ids=case["parties"], status=case["existing_status"])
        assert alliance_commitment_conflicts(candidate, [existing]) is case["conflicts"]
        return

    state = run_war_room(WarRoomScenarioRequest(seed=42))
    actor, target = state.country_agents[:2]
    proposal = AgentActionProposal(
        proposal_id=f"proposal_{case['case_id']}", run_id="run_golden", turn=1,
        actor_id=f"agent:public_opinion:{actor.code}", actor_type="public_opinion", action_type="public_narrative",
        target_ids=[f"country:{target.code}"], parameters={"theme": "版本化 Golden Scenario", "audience": case["audience"], "tone": case["tone"]},
        justification="验证固定舆论扩散公式和累计边界。", evidence_refs=[f"country:{target.code}"],
        expected_direction="inform", confidence=80, created_at="2000-01-01T00:00:01.000Z",
    )
    _, _, cumulative = apply_narrative_diffusion(state, [proposal], {target.code: case["initial_delta"]})
    assert cumulative[target.code] == case["expected_target_delta"]
