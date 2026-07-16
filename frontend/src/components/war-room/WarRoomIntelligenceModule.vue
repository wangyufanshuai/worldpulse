<template>
  <section class="continuous-intelligence" data-testid="war-room-intelligence-module">
    <div class="intelligence-hero">
      <div><span class="trust-eyebrow">CONTINUOUS INTELLIGENCE / V1.10</span><h3>持续情报监测与告警闭环</h3><p>公开 Feed 只生成有证据定位的待核验候选，不会自动改变风险数值、创建 Draft 或启动推演。</p></div>
      <span :class="['intelligence-state', summary?.enabled ? 'enabled' : 'disabled']">{{ summary?.enabled ? '网络采集已启用' : '网络采集未启用' }}</span>
    </div>
    <div v-if="error" class="compiler-alert error">{{ error }} <button type="button" @click="$emit('refresh')">重试</button></div>
    <div class="intelligence-kpis">
      <article><span>活跃 Source</span><strong>{{ summary?.active_sources ?? 0 }}</strong><small>持续轮询</small></article>
      <article><span>降级 Source</span><strong>{{ summary?.degraded_sources ?? 0 }}</strong><small>连续失败</small></article>
      <article><span>开放告警</span><strong>{{ summary?.open_alerts ?? 0 }}</strong><small>待处置</small></article>
      <article><span>高等级告警</span><strong>{{ summary?.high_alerts ?? 0 }}</strong><small>high / critical</small></article>
      <article><span>待核验候选</span><strong>{{ summary?.pending_candidates ?? 0 }}</strong><small>沿用场景编译器</small></article>
    </div>
    <div class="intelligence-grid">
      <article class="trust-panel"><header><div><span>MONITORING SOURCES</span><h3>数据源与健康度</h3></div></header>
        <form v-if="canWrite" class="intelligence-form" data-testid="monitoring-source-form" @submit.prevent="submitSource"><input v-model="sourceForm.name" placeholder="Source 名称" required /><select v-model="sourceForm.source_type" aria-label="Feed 类型"><option value="rss_atom">RSS / Atom</option><option value="json_feed">JSON Feed</option></select><input v-model="sourceForm.feed_url" type="url" placeholder="https://example.org/feed.xml" required /><input v-model="sourceForm.publisher" placeholder="Publisher" required /><input v-model="sourceForm.license_name" placeholder="License" required /><select v-model="sourceForm.category" aria-label="材料分类"><option value="conflict">冲突</option><option value="sanctions">制裁</option><option value="trade">贸易</option><option value="energy">能源</option><option value="food">粮食</option><option value="finance">金融</option><option value="climate">气候</option><option value="other">其他</option></select><button type="submit" :disabled="busy" data-testid="monitoring-source-create">创建 Source</button></form>
        <div class="intelligence-list"><article v-for="source in sources" :key="source.source_id"><span :class="['status', source.status]">{{ source.status }}</span><div><strong>{{ source.name }}</strong><small>{{ source.source_type }} · {{ source.feed_url }}</small><small>下次轮询 {{ formatTime(source.next_poll_at) }}</small></div><div class="actions"><button v-if="canWrite && source.status !== 'retired'" type="button" class="secondary" @click="$emit('poll', source.source_id)">立即轮询</button><button v-if="canWrite && source.status === 'paused'" type="button" class="secondary accept" @click="$emit('source-status', source.source_id, 'active')">启用</button><button v-else-if="canWrite && source.status === 'active'" type="button" class="secondary" @click="$emit('source-status', source.source_id, 'paused')">暂停</button></div></article><p v-if="!sources.length" class="compiler-empty">尚未配置公开 Feed。</p></div>
      </article>
      <article class="trust-panel"><header><div><span>WATCHLISTS</span><h3>确定性监测规则</h3></div></header>
        <form v-if="canWrite" class="intelligence-form" data-testid="monitoring-watchlist-form" @submit.prevent="submitWatchlist"><input v-model="watchForm.name" placeholder="监测清单名称" required /><select v-model="watchForm.candidate_type" aria-label="候选类型"><option value="country">国家</option><option value="supply_chain">供应链</option><option value="policy_action">政策动作</option><option value="scenario_preset">场景预设</option></select><input v-model="watchForm.canonical_value" placeholder="规范值，例如 CHN" required /><select v-model="watchForm.severity" aria-label="告警级别"><option value="warning">warning</option><option value="high">high</option><option value="critical">critical</option></select><button type="submit" :disabled="busy" data-testid="monitoring-watchlist-create">创建清单</button></form>
        <div class="intelligence-list"><article v-for="watchlist in watchlists" :key="watchlist.watchlist_id"><span :class="['status', watchlist.status]">{{ watchlist.status }}</span><div><strong>{{ watchlist.name }} · v{{ watchlist.version }}</strong><small>{{ watchlist.rules.length }} 条规则 · {{ compact(watchlist.manifest_hash) }}</small></div><div class="actions"><button v-if="canWrite && watchlist.status === 'draft'" type="button" class="secondary accept" @click="$emit('watchlist-status', watchlist.watchlist_id, 'activate')">激活</button><button v-if="canWrite && watchlist.status === 'active'" type="button" class="secondary" @click="$emit('watchlist-status', watchlist.watchlist_id, 'pause')">暂停</button></div></article><p v-if="!watchlists.length" class="compiler-empty">尚未配置监测清单。</p></div>
      </article>
    </div>
    <article class="trust-panel"><header><div><span>ALERT STREAM</span><h3>告警与证据 lineage</h3></div><button type="button" class="secondary" @click="$emit('refresh')">刷新</button></header><div class="intelligence-alerts"><article v-for="alert in alerts" :key="alert.alert_id" :class="['intelligence-alert', alert.severity]"><div><span :class="['severity', alert.severity]">{{ alert.severity }}</span><strong>{{ alert.title }}</strong><small>{{ alert.summary }}</small><small>Alert {{ compact(alert.alert_hash) }} · Pipeline {{ alert.lineage.pipeline_status }}</small></div><div class="actions"><button v-if="canWrite && alert.status === 'open'" type="button" class="secondary" @click="$emit('alert-status', alert.alert_id, 'acknowledge')">确认</button><button v-if="canWrite && ['open','acknowledged'].includes(alert.status)" type="button" class="secondary danger" @click="$emit('alert-status', alert.alert_id, 'dismiss')">忽略</button></div></article><p v-if="!alerts.length" class="compiler-empty">暂无命中告警。Feed 只会在匹配确定性规范值后生成告警。</p></div></article>
  </section>
</template>
<script setup>
import { reactive, ref } from 'vue'
defineProps({ summary: Object, sources: { type: Array, default: () => [] }, watchlists: { type: Array, default: () => [] }, alerts: { type: Array, default: () => [] }, error: { type: String, default: '' }, canWrite: Boolean })
const emit = defineEmits(['refresh', 'create-source', 'poll', 'source-status', 'create-watchlist', 'watchlist-status', 'alert-status'])
const busy = ref(false)
const sourceForm = reactive({ name: '', source_type: 'rss_atom', feed_url: '', publisher: '', license_name: 'public-feed', license_url: '', category: 'conflict', poll_interval_minutes: 60 })
const watchForm = reactive({ name: '', candidate_type: 'country', canonical_value: '', severity: 'warning' })
function submitSource() { emit('create-source', { ...sourceForm }) }
function submitWatchlist() { emit('create-watchlist', { name: watchForm.name, rules: [{ candidate_type: watchForm.candidate_type, canonical_value: watchForm.canonical_value, severity: watchForm.severity }] }) }
function compact(value) { return value ? `${String(value).slice(0, 10)}…` : '--' }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--' }
</script>
