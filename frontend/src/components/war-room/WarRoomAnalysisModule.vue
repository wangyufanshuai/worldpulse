<template>
  <div class="module-workbench analysis-workbench" data-testid="war-room-analysis-module">
    <aside class="module-panel list">
      <div class="module-panel-head">
        <div><span>Agent 排行</span><h3>国家风险排行</h3></div>
      </div>
      <label class="compact-search">
        筛选 Agent
        <input
          :value="props.analysisFilter"
          type="search"
          placeholder="中国 / USA / 芯片"
          data-testid="analysis-filter"
          @input="props.onAnalysisFilterChange?.($event.target.value)"
        />
      </label>
      <div class="agent-rank-list">
        <button
          v-for="country in props.filteredAnalysisCountries"
          :key="country.code"
          type="button"
          :class="{ active: props.activeAgent.code === country.code }"
          @click="props.onSetAnalysisCountry?.(country.code)"
        >
          <span>{{ props.countryNameShort?.(country.code) || country.code }}</span>
          <strong>{{ Math.round(country.risk) }}</strong>
          <small>{{ props.riskChannel?.(country.dominant_channel) || country.dominant_channel }}</small>
        </button>
      </div>
    </aside>

    <section class="module-panel primary">
      <div class="agent-analysis-head">
        <span class="flag-card" :class="`flag-${props.activeAgent.code}`">{{ props.activeAgent.flag }}</span>
        <div>
          <span>当前 Agent</span>
          <h3>{{ props.activeAgent.name }}</h3>
          <p>{{ props.activeAgent.intent }}</p>
        </div>
        <em>{{ props.activeAgent.status }}</em>
      </div>
      <div class="analysis-metric-grid">
        <article><span>综合状态</span><strong>{{ props.activeAgent.power }}/100</strong></article>
        <article><span>触发源</span><strong>{{ props.activeAgent.triggerSource }}</strong></article>
        <article><span>决策置信度</span><strong>{{ props.activeAgentDecisionConfidence }}</strong></article>
        <article><span>主导风险</span><strong>{{ props.activeEntityDetail.metrics?.[1]?.value || '--' }}</strong></article>
      </div>
      <div class="analysis-detail-grid">
        <article><h4>决策依据</h4><p>{{ props.activeAgent.decisionBasis }}</p></article>
        <article><h4>预期代价</h4><p>{{ props.activeAgent.expectedTradeoff }}</p></article>
        <article><h4>关联事件</h4><ul><li v-for="event in props.activeAgent.relatedEvents" :key="event">{{ event }}</li></ul></article>
        <article><h4>行动倾向</h4><div class="decision-chips"><button v-for="chip in props.activeAgent.decisions" :key="chip" type="button" @click="props.onOpenDecisionDrawer?.(chip)">{{ chip }}</button></div></article>
      </div>
    </section>
    <section v-if="props.runtimeAudit" class="module-panel agent-negotiation-panel" data-testid="agent-negotiation-panel">
      <div class="module-panel-head">
        <div><span>受控协商</span><h3>Agent Action Proposal 审计链</h3></div>
        <b>{{ props.runtimeAudit.mode }} · {{ props.runtimeAudit.provider }}</b>
      </div>
      <p class="sandbox-note">以下内容是结构化行动提案，不是风险数值。最终数值仅由确定性引擎生成。</p>
      <div class="agent-negotiation-grid">
        <article v-for="proposal in props.runtimeAudit.proposals || []" :key="proposal.proposal_id" data-testid="agent-negotiation-proposal">
          <header><code>{{ shortId(proposal.proposal_id) }}</code><b :class="decisionFor(proposal.proposal_id)?.decision">{{ decisionLabel(decisionFor(proposal.proposal_id)?.decision) }}</b></header>
          <strong>{{ actionLabel(proposal.action_type) }}</strong>
          <p>{{ proposal.justification }}</p>
          <small>{{ proposal.actor_id }} → {{ proposal.target_ids?.join(' / ') }}</small>
        </article>
      </div>
      <footer>调用 {{ props.runtimeAudit.total_calls || 0 }} 次 · 估算 {{ props.runtimeAudit.total_estimated_tokens || 0 }} tokens · 失败 {{ props.runtimeAudit.failed_calls || 0 }} 次 · Runtime Hash {{ shortHash(props.runtimeAudit.runtime_hash) }}</footer>
    </section>
  </div>
</template>

<script setup>
const props = defineProps({
  analysisFilter: { type: String, default: '' },
  filteredAnalysisCountries: { type: Array, default: () => [] },
  activeAgent: { type: Object, required: true },
  activeEntityDetail: { type: Object, required: true },
  activeAgentDecisionConfidence: { type: String, default: '' },
  countryNameShort: { type: Function, default: null },
  riskChannel: { type: Function, default: null },
  onAnalysisFilterChange: { type: Function, default: null },
  onSetAnalysisCountry: { type: Function, default: null },
  onOpenDecisionDrawer: { type: Function, default: null },
  runtimeAudit: { type: Object, default: null },
  consistencyAudit: { type: Object, default: null }
})

const decisionFor = proposalId => (props.consistencyAudit?.proposal_decisions || []).find(item => item.proposal_id === proposalId)
const decisionLabel = value => ({ accepted: '已接受', rejected: '已拒绝', needs_revision: '需修订', not_evaluated: '未评估' }[value] || '待评估')
const actionLabel = value => ({ diplomatic_signal: '外交信号', alliance_request: '联盟请求', alliance_response: '联盟回应', sanction_proposal: '制裁提案', trade_reroute_request: '贸易改道', public_narrative: '公共叙事', humanitarian_offer: '人道援助', deescalation_offer: '降级提议', intelligence_request: '情报请求' }[value] || value)
const shortId = value => String(value || '').replace(/^proposal_/, '#').slice(0, 18)
const shortHash = value => String(value || '').slice(0, 16)
</script>
