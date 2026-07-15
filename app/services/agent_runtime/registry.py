from __future__ import annotations

from .models import AgentRoleDefinition


ROLE_REGISTRY: tuple[AgentRoleDefinition, ...] = (
    AgentRoleDefinition(
        role_id="country_policy",
        actor_type="country_policy",
        title_zh="国家政策 Agent",
        allowed_actions=["trade_reroute_request", "sanction_proposal", "humanitarian_offer"],
        system_prompt="根据显式仿真能力信封提出政策行动，不得输出或修改风险数值。",
    ),
    AgentRoleDefinition(
        role_id="diplomacy",
        actor_type="diplomacy",
        title_zh="外交协商 Agent",
        allowed_actions=["diplomatic_signal", "deescalation_offer", "humanitarian_offer"],
        system_prompt="提出外交信号或降级方案，只能引用提供的确定性实体和证据。",
    ),
    AgentRoleDefinition(
        role_id="alliance",
        actor_type="alliance",
        title_zh="联盟协调 Agent",
        allowed_actions=["alliance_request", "alliance_response", "intelligence_request"],
        system_prompt="提出联盟协调动作，不得假设未提供的现实国家承诺或资源。",
    ),
    AgentRoleDefinition(
        role_id="public_opinion",
        actor_type="public_opinion",
        title_zh="舆论传播 Agent",
        allowed_actions=["public_narrative"],
        system_prompt="提出可审计的叙事方向，不得把叙事文本伪装为事实证据。",
    ),
    AgentRoleDefinition(
        role_id="explanation",
        actor_type="explanation",
        title_zh="行动解释 Agent",
        allowed_actions=[],
        system_prompt="仅解释已保存动作，不创建世界状态或新的动作提案。",
    ),
)


def role_for_actor_type(actor_type: str) -> AgentRoleDefinition | None:
    return next((role for role in ROLE_REGISTRY if role.actor_type == actor_type), None)
