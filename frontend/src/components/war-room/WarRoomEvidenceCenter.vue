<template>
  <section class="evidence-center" data-testid="war-room-evidence-center">
    <div v-if="loading && !summary" class="trust-empty">正在加载证据注册表…</div>
    <div v-else-if="error && !summary" class="trust-empty error-text">{{ error }} <button type="button" @click="$emit('refresh')">重试</button></div>
    <template v-else-if="summary">
      <section class="evidence-hero">
        <div>
          <span class="trust-eyebrow"><LibraryBig :size="16" /> EVIDENCE CONTROL PLANE</span>
          <h3>{{ verdict.title }}</h3>
          <p>所有条目来自已保存的确定性运行、因果图、报告或冻结校准案例。快照不可原地修改，查询受时间截点约束。</p>
        </div>
        <div class="evidence-hero-actions">
          <span :class="['trust-verdict', verdict.className]" data-testid="evidence-integrity-status">{{ verdict.label }}</span>
          <button v-if="canWrite" type="button" class="secondary" :disabled="loading" data-testid="evidence-sync" @click="$emit('sync')">
            <RefreshCw :size="15" /> 同步当前运行
          </button>
          <button v-if="canWrite" type="button" class="secondary" :disabled="loading || !summary.snapshot_count" data-testid="evidence-create-pack" @click="$emit('create-pack')">
            <PackageCheck :size="15" /> 冻结证据包
          </button>
        </div>
      </section>

      <section class="evidence-kpis">
        <article><span>证据源</span><strong>{{ summary.source_count }}</strong><small>已登记来源</small></article>
        <article><span>冻结快照</span><strong>{{ summary.snapshot_count }}</strong><small>{{ shortTime(summary.latest_cutoff_at) }}</small></article>
        <article><span>可追溯声明</span><strong>{{ summary.linked_claim_count }}/{{ summary.claim_count }}</strong><small>覆盖率 {{ percent(summary.coverage) }}</small></article>
        <article><span>证据包</span><strong>{{ summary.pack_count }}</strong><small>{{ summary.latest_pack ? shortHash(summary.latest_pack.manifest_hash) : '尚未冻结' }}</small></article>
      </section>

      <section class="evidence-search-panel">
        <div>
          <span class="section-kicker"><Search :size="15" /> 截点安全检索</span>
          <p>只返回不晚于所选时间截点的快照与声明，避免校准和复盘读取未来数据。</p>
        </div>
        <form @submit.prevent="$emit('search', query, cutoffAt)">
          <input v-model="query" type="search" placeholder="搜索能源、供应链、国家或结论" data-testid="evidence-search-input" />
          <input v-model="cutoffAt" type="date" aria-label="证据时间截点" data-testid="evidence-cutoff-input" />
          <button type="submit" class="secondary" :disabled="searching"><Search :size="15" /> 检索</button>
        </form>
      </section>

      <section v-if="searchResult?.total" class="evidence-results" data-testid="evidence-search-results">
        <header><div><span>SEARCH RESULTS</span><h3>{{ searchResult.total }} 条截点内记录</h3></div><Clock3 :size="21" /></header>
        <article v-for="snapshot in searchResult.snapshots" :key="snapshot.snapshot_id">
          <div><span class="evidence-kind">{{ snapshot.category }}</span><strong>{{ snapshot.title }}</strong></div>
          <code>{{ shortHash(snapshot.content_hash) }}</code><small>{{ shortTime(snapshot.cutoff_at) }}</small>
        </article>
        <article v-for="claim in searchResult.claims" :key="claim.claim_id">
          <div><span class="evidence-kind claim">CLAIM</span><strong>{{ claim.statement }}</strong></div>
          <code>{{ claim.links.length }} refs</code><small>{{ Math.round(claim.confidence * 100) }}% confidence</small>
        </article>
      </section>

      <section class="evidence-grid">
        <article class="trust-panel">
          <header><div><span>来源健康度</span><h3>Source Registry</h3></div><DatabaseZap :size="22" /></header>
          <div v-if="summary.sources.length" class="evidence-source-list">
            <article v-for="source in summary.sources" :key="source.source_id">
              <span :class="['source-health', source.status]">{{ source.status }}</span>
              <div><strong>{{ source.name }}</strong><small>{{ source.source_type }} · {{ source.trust_tier }}</small></div>
              <code>{{ source.locator }}</code>
            </article>
          </div>
          <div v-else class="trust-empty">尚未同步项目证据。</div>
        </article>

        <article class="trust-panel">
          <header><div><span>最近快照</span><h3>Immutable Snapshots</h3></div><Fingerprint :size="22" /></header>
          <div v-if="summary.recent_snapshots.length" class="evidence-snapshot-list">
            <article v-for="snapshot in summary.recent_snapshots.slice(0, 8)" :key="snapshot.snapshot_id">
              <div><strong>{{ snapshot.title }}</strong><small>{{ snapshot.category }} · cutoff {{ shortTime(snapshot.cutoff_at) }}</small></div>
              <span :class="['snapshot-integrity', snapshot.integrity_status]">{{ snapshot.integrity_status }}</span>
              <code>{{ shortHash(snapshot.content_hash) }}</code>
            </article>
          </div>
          <div v-else class="trust-empty">同步运行后将生成冻结快照。</div>
        </article>
      </section>

      <section class="trust-panel evidence-claims-panel">
        <header><div><span>声明与引用</span><h3>Claim Provenance</h3></div><GitBranch :size="22" /></header>
        <div v-if="summary.recent_claims.length" class="evidence-claim-list">
          <article v-for="claim in summary.recent_claims.slice(0, 12)" :key="claim.claim_id">
            <div><strong>{{ claim.statement }}</strong><small>{{ claim.claim_type }} · {{ Math.round(claim.confidence * 100) }}% · {{ claim.links.length }} 个证据引用</small></div>
            <code>{{ shortHash(claim.claim_hash) }}</code>
          </article>
        </div>
        <div v-else class="trust-empty">报告结论同步后会在此显示来源与哈希链。</div>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Clock3, DatabaseZap, Fingerprint, GitBranch, LibraryBig, PackageCheck, RefreshCw, Search } from 'lucide-vue-next'
import { evidenceVerdict } from '../../composables/evidenceProjection'

const props = defineProps({
  summary: { type: Object, default: null }, searchResult: { type: Object, default: null },
  loading: Boolean, searching: Boolean, error: { type: String, default: '' }, canWrite: Boolean,
})
defineEmits(['refresh', 'sync', 'create-pack', 'search'])

const query = ref('')
const cutoffAt = ref('')
const verdict = computed(() => evidenceVerdict(props.summary))

function percent(value) { return `${Math.round(Number(value || 0) * 100)}%` }
function shortHash(value) { return value ? `${String(value).slice(0, 10)}…${String(value).slice(-7)}` : '--' }
function shortTime(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '--' }
</script>
