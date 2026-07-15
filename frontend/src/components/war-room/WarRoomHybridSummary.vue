<template>
  <section v-if="trace" class="war-room-hybrid-summary" data-testid="hybrid-result-summary">
    <header>
      <div>
        <span class="section-kicker">受控混合推演 · 可审计结果链</span>
        <h2>基线 → Agent 提案 → 一致性准入 → 确定性重算</h2>
      </div>
      <b>规则引擎数值权威</b>
    </header>
    <div class="hybrid-view-toggle" data-testid="hybrid-view-toggle">
      <button type="button" :class="{ active: viewMode === 'baseline' }" @click="$emit('set-view', 'baseline')">确定性基线</button>
      <button type="button" :class="{ active: viewMode === 'hybrid' }" @click="$emit('set-view', 'hybrid')">混合最终结果</button>
    </div>
    <p>Agent 仅提出结构化动作。只有已接受动作经固定适配器转换后，才由确定性 War Room 引擎重新计算最终数值。</p>
    <dl>
      <div><dt>已接受提案</dt><dd data-testid="hybrid-accepted-count">{{ trace.accepted_proposal_ids?.length || 0 }}</dd></div>
      <div><dt>基线全球风险</dt><dd>{{ signedRisk(diff.global_risk?.baseline) }}</dd></div>
      <div><dt>混合全球风险</dt><dd>{{ signedRisk(diff.global_risk?.hybrid) }}</dd></div>
      <div><dt>确定性变化</dt><dd :class="deltaTone(diff.global_risk?.delta)">{{ signedDelta(diff.global_risk?.delta) }}</dd></div>
    </dl>
    <div class="hybrid-change-grid">
      <article>
        <strong>供应链压力变化</strong>
        <span v-for="item in topChains" :key="item.key">{{ item.name }} <b :class="deltaTone(item.delta)">{{ signedDelta(item.delta) }}</b></span>
        <small v-if="!topChains.length">没有产生供应链数值变化。</small>
      </article>
      <article>
        <strong>国家风险变化</strong>
        <span v-for="item in topCountries" :key="item.country_code">{{ item.country_name }} <b :class="deltaTone(item.delta)">{{ signedDelta(item.delta) }}</b></span>
        <small v-if="!topCountries.length">没有产生国家风险数值变化。</small>
      </article>
    </div>
    <footer>
      <span>Baseline <code>{{ shortHash(trace.baseline_result_hash) }}</code></span>
      <span>Final <code data-testid="hybrid-final-hash">{{ trace.final_result_hash }}</code></span>
      <span>Replay <code>{{ shortHash(trace.replay_hash) }}</code></span>
    </footer>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { hybridSummaryMetrics } from '../../composables/hybridSummary'

const props = defineProps({
  trace: { type: Object, default: null },
  viewMode: { type: String, default: 'hybrid' }
})
defineEmits(['set-view'])
const diff = computed(() => props.trace?.baseline_diff || {})
const summaryMetrics = computed(() => hybridSummaryMetrics(props.trace))
const topChains = computed(() => summaryMetrics.value.topChains)
const topCountries = computed(() => summaryMetrics.value.topCountries)

const signedRisk = value => Number.isFinite(Number(value)) ? Number(value).toFixed(1) : '—'
const signedDelta = value => Number.isFinite(Number(value)) ? `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(1)}` : '—'
const deltaTone = value => Number(value) > 0 ? 'negative' : Number(value) < 0 ? 'positive' : 'neutral'
const shortHash = value => String(value || '').slice(0, 16)
</script>
