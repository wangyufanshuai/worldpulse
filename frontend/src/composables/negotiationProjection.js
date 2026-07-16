const DEFAULT_DAYS = [0, 3, 7, 14, 21, 30]

export function negotiationTickCards(rounds = []) {
  return Array.from({ length: 6 }, (_, index) => rounds.find(item => Number(item.tick) === index + 1) || ({
    tick: index + 1,
    simulation_day: DEFAULT_DAYS[index],
    status: 'queued',
    scheduled_agents: [],
    output: {},
  }))
}

export function filterNegotiationMessages(messages = [], { tick = 1, type = '', agentId = '' } = {}) {
  return messages.filter(item => Number(item.tick) === Number(tick)
    && (!type || item.message_type === type)
    && (!agentId || item.sender_agent_id === agentId || (item.recipient_agent_ids || []).includes(agentId)))
}

export function negotiationSummary(detail, commitments = [], messages = []) {
  return {
    currentTick: Number(detail?.session?.current_tick || 0),
    agentCount: detail?.agent_pack?.profiles?.length || 0,
    activeCommitments: commitments.filter(item => item.status === 'active').length,
    rejectedCommitments: commitments.filter(item => ['rejected', 'expired', 'withdrawn'].includes(item.status)).length,
    messageCount: messages.length,
  }
}
