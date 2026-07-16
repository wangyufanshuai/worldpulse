import { describe, expect, it } from 'vitest'

import { filterNegotiationMessages, negotiationSummary, negotiationTickCards } from '../src/composables/negotiationProjection'


describe('V1.8 negotiation projections', () => {
  it('always projects the six fixed lifecycle ticks', () => {
    const ticks = negotiationTickCards([{ tick: 2, simulation_day: 4, status: 'completed' }])
    expect(ticks.map(item => item.tick)).toEqual([1, 2, 3, 4, 5, 6])
    expect(ticks.map(item => item.simulation_day)).toEqual([0, 4, 7, 14, 21, 30])
    expect(ticks[0].status).toBe('queued')
  })

  it('filters saved messages by tick, type and either endpoint', () => {
    const messages = [
      { tick: 2, message_type: 'proposal', sender_agent_id: 'a', recipient_agent_ids: ['b'] },
      { tick: 2, message_type: 'accept', sender_agent_id: 'b', recipient_agent_ids: ['a'] },
      { tick: 3, message_type: 'proposal', sender_agent_id: 'c', recipient_agent_ids: [] },
    ]
    expect(filterNegotiationMessages(messages, { tick: 2, type: 'proposal' })).toEqual([messages[0]])
    expect(filterNegotiationMessages(messages, { tick: 2, agentId: 'a' })).toEqual([messages[0], messages[1]])
  })

  it('derives commitment and Agent KPIs without inventing values', () => {
    const detail = { session: { current_tick: 5 }, agent_pack: { profiles: Array.from({ length: 12 }) } }
    const commitments = [{ status: 'active' }, { status: 'rejected' }, { status: 'expired' }, { status: 'proposed' }]
    const summary = negotiationSummary(detail, commitments, [{}, {}, {}])
    expect(summary).toEqual({ currentTick: 5, agentCount: 12, activeCommitments: 1, rejectedCommitments: 2, messageCount: 3 })
  })
})
