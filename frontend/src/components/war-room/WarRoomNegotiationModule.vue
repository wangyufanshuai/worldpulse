<template>
  <div class="negotiation-console" data-testid="war-room-negotiation-module">
    <section v-if="props.error" class="negotiation-empty error">{{ props.error }}</section>
    <section v-else-if="!props.detail" class="negotiation-empty">
      <h3>尚无多轮外交博弈记录</h3>
      <p>在系统设置中选择“多轮外交博弈”，然后从战情总览或推演沙盘创建运行。</p>
    </section>
    <template v-else>
      <section class="negotiation-ticks" data-testid="negotiation-timeline">
        <button v-for="tick in tickCards" :key="tick.tick" type="button" :class="{ active: selectedTick === tick.tick, completed: tick.status === 'completed' }" @click="selectedTick = tick.tick">
          <span>Tick {{ tick.tick }}</span><strong>D+{{ tick.simulation_day }}</strong><small>{{ statusLabel(tick.status) }}</small>
        </button>
      </section>

      <section class="negotiation-kpis">
        <article><span>当前轮次</span><strong>{{ props.summary.currentTick }}/6</strong></article>
        <article><span>受控 Agent</span><strong>{{ props.summary.agentCount }}/12</strong></article>
        <article><span>消息哈希链</span><strong>{{ props.summary.messageCount }}</strong></article>
        <article><span>有效承诺</span><strong>{{ props.summary.activeCommitments }}</strong></article>
        <article><span>拒绝/失效</span><strong>{{ props.summary.rejectedCommitments }}</strong></article>
        <article><span>数值权威</span><strong>确定性引擎</strong></article>
      </section>

      <section class="negotiation-grid">
        <article class="negotiation-panel network" data-testid="negotiation-agent-network">
          <header><div><span>Agent Network</span><h3>12 Agent 外交关系网</h3></div><code>{{ shortHash(props.detail.agent_pack?.manifest_hash) }}</code></header>
          <div class="agent-network">
            <button v-for="agent in props.detail.agent_pack?.profiles || []" :key="agent.agent_id" type="button" :class="['agent-node', agent.actor_type, { active: activeAgentIds.has(agent.agent_id) }]" @click="agentFilter = agent.agent_id">
              <strong>{{ roleLabel(agent.actor_type) }}</strong><span>{{ agent.country_code }}</span>
            </button>
          </div>
          <footer>青色节点参与当前 Tick；所有连接均来自已保存消息，不推测现实外交关系。</footer>
        </article>

        <article class="negotiation-panel stream" data-testid="negotiation-message-stream">
          <header><div><span>Message Stream</span><h3>结构化协商消息</h3></div><button type="button" @click="agentFilter = ''">清除筛选</button></header>
          <div class="message-filters">
            <button v-for="type in messageTypes" :key="type" type="button" :class="{ active: typeFilter === type }" @click="typeFilter = typeFilter === type ? '' : type">{{ typeLabel(type) }}</button>
          </div>
          <div class="message-list">
            <article v-for="message in filteredMessages" :key="message.message_id" :class="message.message_type" data-testid="negotiation-message">
              <header><b>{{ typeLabel(message.message_type) }}</b><span>#{{ message.seq }} · Tick {{ message.tick }}</span></header>
              <strong>{{ shortAgent(message.sender_agent_id) }} → {{ message.recipient_agent_ids.length ? message.recipient_agent_ids.map(shortAgent).join(' / ') : '公开频道' }}</strong>
              <p>{{ message.narrative }}</p>
              <footer><code>{{ shortHash(message.message_hash) }}</code><span>{{ message.provider }} · {{ message.estimated_tokens }} tokens</span></footer>
            </article>
          </div>
        </article>

        <article class="negotiation-panel ledger" data-testid="negotiation-commitment-ledger">
          <header><div><span>Commitment Ledger</span><h3>不可变承诺账本</h3></div></header>
          <div v-if="!props.commitments.length" class="ledger-empty">当前 Tick 尚未形成双边承诺。</div>
          <article v-for="item in props.commitments" :key="item.commitment_id" class="commitment-card">
            <header><strong>{{ actionLabel(item.action_type) }}</strong><b :class="item.status">{{ commitmentLabel(item.status) }}</b></header>
            <p>{{ item.party_agent_ids.map(shortAgent).join(' ↔ ') }}</p>
            <footer><code>{{ shortHash(item.commitment_hash) }}</code><span>{{ item.events.length }} 次状态记录</span></footer>
          </article>
        </article>

        <article class="negotiation-panel diffusion" data-testid="negotiation-diffusion-audit">
          <header><div><span>Narrative Diffusion</span><h3>确定性舆论扩散</h3></div></header>
          <template v-if="activeRound?.output?.narrative_diffusion?.applications?.length">
            <article v-for="(item, index) in activeRound.output.narrative_diffusion.applications" :key="`${item.proposal_id}-${item.receiver_country}-${index}`">
              <strong>{{ item.target_country }} → {{ item.receiver_country }}</strong><span>{{ signed(item.applied_delta) }}</span>
              <small>{{ item.tone }} · {{ item.audience }} · {{ item.effective_multiplier }}×</small>
            </article>
          </template>
          <div v-else class="ledger-empty">当前 Tick 没有通过准入的公共叙事投影。</div>
          <footer>固定公式：稳定 -4 / 信息 -1 / 强硬 +3；单次运行每国累计限制为 ±8。</footer>
        </article>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { filterNegotiationMessages, negotiationTickCards } from '../../composables/negotiationProjection'

const props = defineProps({
  detail: { type: Object, default: null }, rounds: { type: Array, default: () => [] },
  messages: { type: Array, default: () => [] }, commitments: { type: Array, default: () => [] },
  summary: { type: Object, default: () => ({}) }, loading: Boolean, error: { type: String, default: '' }
})
const selectedTick = ref(1)
const typeFilter = ref('')
const agentFilter = ref('')
const messageTypes = ['proposal', 'counteroffer', 'accept', 'reject', 'withdrawal', 'public_statement']
const tickCards = computed(() => negotiationTickCards(props.rounds))
const activeRound = computed(() => props.rounds.find(item => item.tick === selectedTick.value))
const activeAgentIds = computed(() => new Set(activeRound.value?.scheduled_agents || []))
const filteredMessages = computed(() => filterNegotiationMessages(props.messages, { tick: selectedTick.value, type: typeFilter.value, agentId: agentFilter.value }))
watch(() => props.summary.currentTick, value => { if (value) selectedTick.value = value }, { immediate: true })
const statusLabel = value => ({ completed: '已固化', running: '执行中', failed: '失败', queued: '待执行' }[value] || value)
const roleLabel = value => ({ country_policy: '国家政策', diplomacy: '外交', alliance: '联盟', public_opinion: '舆论' }[value] || value)
const typeLabel = value => ({ proposal: '提案', counteroffer: '反提案', accept: '接受', reject: '拒绝', withdrawal: '撤回', public_statement: '公开声明' }[value] || value)
const actionLabel = value => ({ alliance_request: '联盟协调', deescalation_offer: '降级机制', humanitarian_offer: '人道援助' }[value] || value)
const commitmentLabel = value => ({ proposed: '待回应', active: '已生效', rejected: '已拒绝', withdrawn: '已撤回', expired: '已过期' }[value] || value)
const shortAgent = value => String(value || '').replace('agent:', '').replaceAll(':', ' / ')
const shortHash = value => String(value || '').slice(0, 14)
const signed = value => `${Number(value) >= 0 ? '+' : ''}${Number(value || 0).toFixed(2)}`
</script>

<style scoped>
.negotiation-console{display:grid;gap:14px;color:#dceef2}.negotiation-empty{padding:42px;border:1px solid #24434a;background:#081318;text-align:center}.negotiation-empty.error{color:#ff8e8e}.negotiation-ticks,.negotiation-kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.negotiation-ticks button,.negotiation-kpis article{border:1px solid #24434a;background:#09171c;padding:12px;color:inherit;text-align:left}.negotiation-ticks button{display:grid;gap:4px}.negotiation-ticks button.completed{border-color:#276d6f}.negotiation-ticks button.active{box-shadow:inset 0 0 0 1px #55dce1;background:#0c252b}.negotiation-ticks span,.negotiation-kpis span,.negotiation-panel header span{font-size:11px;color:#70a3ad;text-transform:uppercase}.negotiation-ticks strong,.negotiation-kpis strong{font-size:20px}.negotiation-ticks small{color:#57d8b2}.negotiation-kpis article{display:grid;gap:6px}.negotiation-grid{display:grid;grid-template-columns:1.15fr 1.35fr;gap:12px}.negotiation-panel{border:1px solid #24434a;background:#071217;padding:14px;min-height:240px}.negotiation-panel>header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.negotiation-panel h3{margin:3px 0 0}.negotiation-panel code{color:#55dce1}.agent-network{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.agent-node{display:grid;gap:3px;padding:10px;border:1px solid #263f46;background:#0a181d;color:#bad1d6;text-align:left}.agent-node.active{border-color:#55dce1;box-shadow:0 0 14px #1c8f9440}.agent-node.diplomacy{border-left:3px solid #4aa9ff}.agent-node.alliance{border-left:3px solid #b18cff}.agent-node.public_opinion{border-left:3px solid #f6b75f}.negotiation-panel footer{margin-top:10px;color:#6f959d;font-size:11px}.message-filters{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:9px}.message-filters button,.stream>header button{border:1px solid #294950;background:#0b1d22;color:#9bbac1;padding:5px 8px}.message-filters button.active{border-color:#55dce1;color:#55dce1}.message-list{display:grid;gap:8px;max-height:440px;overflow:auto}.message-list article,.commitment-card{padding:10px;border:1px solid #203d44;background:#0a181d}.message-list article>header,.message-list article>footer,.commitment-card header,.commitment-card footer{display:flex;justify-content:space-between}.message-list p{margin:6px 0;color:#9db7bd}.message-list b,.commitment-card b.active{color:#57d8b2}.commitment-card{margin-bottom:8px}.commitment-card b.rejected,.commitment-card b.expired{color:#ff8e8e}.ledger-empty{padding:24px;color:#789aa2;text-align:center}.diffusion>article{display:grid;grid-template-columns:1fr auto;gap:3px;padding:8px;border-bottom:1px solid #19333a}.diffusion>article span{color:#f6b75f}.diffusion>article small{grid-column:1/-1;color:#6f959d}@media(max-width:1050px){.negotiation-grid{grid-template-columns:1fr}.negotiation-ticks,.negotiation-kpis{grid-template-columns:repeat(3,1fr)}}
</style>
