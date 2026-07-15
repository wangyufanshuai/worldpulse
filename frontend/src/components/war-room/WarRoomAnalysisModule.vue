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
  onOpenDecisionDrawer: { type: Function, default: null }
})
</script>
