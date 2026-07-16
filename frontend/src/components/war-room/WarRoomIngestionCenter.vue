<template>
  <section class="ingestion-center" data-testid="war-room-ingestion-center">
    <div v-if="loading && !summary" class="trust-empty">正在加载组织与采集治理状态…</div>
    <div v-else-if="error && !summary" class="trust-empty error-text">{{ error }} <button type="button" @click="$emit('refresh')">重试</button></div>
    <template v-else-if="summary">
      <section class="ingestion-hero">
        <div>
          <span class="trust-eyebrow"><Building2 :size="16" /> ORGANIZATION DATA PLANE</span>
          <h3>{{ organization.name }}</h3>
          <p>连接器只登记公开配置和许可元数据；原始记录通过大小、类别、时间截点与策略 Hash 门禁后，才写入不可变 Evidence Registry。</p>
        </div>
        <div class="ingestion-org-badge">
          <span>{{ organization.member_role }}</span>
          <strong>{{ organization.slug }}</strong>
          <small>{{ members.length }} 名成员</small>
        </div>
      </section>

      <section class="ingestion-kpis">
        <article><span>连接器</span><strong>{{ summary.connector_count }}</strong><small>manual_json only</small></article>
        <article><span>活动策略</span><strong>{{ summary.active_policy_count }}</strong><small>immutable manifests</small></article>
        <article><span>完成任务</span><strong>{{ summary.completed_jobs }}</strong><small>{{ summary.queued_jobs }} queued / {{ summary.running_jobs }} running</small></article>
        <article><span>接纳记录</span><strong>{{ summary.accepted_records }}</strong><small>{{ summary.rejected_records }} rejected</small></article>
      </section>

      <section class="ingestion-grid">
        <article class="trust-panel">
          <header><div><span>版本化连接器</span><h3>Connector Registry</h3></div><Cable :size="22" /></header>
          <form v-if="allowedToWrite" class="ingestion-form" data-testid="connector-form" @submit.prevent="submitConnector">
            <label>连接器名称<input v-model="connectorDraft.name" required placeholder="例如：能源月报冻结导入" /></label>
            <label>来源定位符<input v-model="connectorDraft.source_locator" required placeholder="manual://energy-monthly" /></label>
            <label>发布方<input v-model="connectorDraft.publisher" required placeholder="数据发布机构" /></label>
            <label>许可/授权<input v-model="connectorDraft.license" required placeholder="license 或内部授权编号" /></label>
            <button type="submit" class="secondary" :disabled="loading" data-testid="connector-create"><Plus :size="15" /> 创建受控连接器</button>
          </form>
          <div class="connector-list">
            <article v-for="connector in summary.connectors" :key="connector.connector_id">
              <span :class="['source-health', connector.status]">{{ connector.status }}</span>
              <div><strong>{{ connector.name }}</strong><small>{{ connector.connector_type }} · {{ connector.config.publisher }}</small></div>
              <code>{{ shortHash(connector.config_hash) }}</code>
            </article>
            <div v-if="!summary.connectors.length" class="trust-empty">尚未登记连接器。</div>
          </div>
        </article>

        <article class="trust-panel">
          <header><div><span>单记录冻结导入</span><h3>Governed Manual Ingestion</h3></div><FileJson2 :size="22" /></header>
          <form v-if="allowedToWrite" class="ingestion-form record-form" data-testid="ingestion-record-form" @submit.prevent="submitRecord">
            <label>连接器<select v-model="recordDraft.connector_id" required><option value="" disabled>选择连接器</option><option v-for="item in summary.connectors" :key="item.connector_id" :value="item.connector_id">{{ item.name }}</option></select></label>
            <label>外部引用<input v-model="recordDraft.external_ref" required placeholder="ENERGY-2026-07" /></label>
            <label>标题<input v-model="recordDraft.title" required placeholder="冻结快照标题" /></label>
            <label>分类<select v-model="recordDraft.category"><option v-for="item in categories" :key="item" :value="item">{{ item }}</option></select></label>
            <label>观测日期<input v-model="recordDraft.observed_at" type="date" required /></label>
            <label>截止日期<input v-model="recordDraft.cutoff_at" type="date" required /></label>
            <label class="form-span">JSON 内容<textarea v-model="recordDraft.content" rows="5" required data-testid="ingestion-json-input" /></label>
            <label class="form-span">检索文本<textarea v-model="recordDraft.content_text" rows="2" /></label>
            <p v-if="draftError" class="error-text form-span">{{ draftError }}</p>
            <button type="submit" class="secondary form-span" :disabled="loading || !summary.connectors.length" data-testid="ingestion-submit"><ShieldCheck :size="15" /> 校验、提交并执行</button>
          </form>
          <div v-else class="trust-empty">当前组织角色为只读。</div>
        </article>
      </section>

      <section class="trust-panel ingestion-jobs-panel">
        <header><div><span>可恢复采集任务</span><h3>Ingestion Lifecycle</h3></div><ListChecks :size="22" /></header>
        <div class="ingestion-job-list">
          <article v-for="job in summary.latest_jobs" :key="job.job_id" :data-testid="`ingestion-job-${job.job_id}`">
            <span :class="['ingestion-status', job.status]">{{ job.status }}</span>
            <div><strong>{{ job.job_id }}</strong><small>{{ job.accepted_count }}/{{ job.record_count }} accepted · {{ shortTime(job.created_at) }}</small></div>
            <code>{{ shortHash(job.manifest_hash || job.request_hash) }}</code>
            <div class="job-actions">
              <button type="button" class="secondary" @click="$emit('events', job.job_id)">事件</button>
              <button v-if="allowedToWrite && job.status === 'queued'" type="button" class="secondary" @click="$emit('cancel', job.job_id)">取消</button>
              <button v-if="allowedToWrite && ['failed', 'cancelled'].includes(job.status)" type="button" class="secondary" @click="$emit('retry', job.job_id)">重试</button>
            </div>
          </article>
          <div v-if="!summary.latest_jobs.length" class="trust-empty">尚无采集任务。</div>
        </div>
      </section>

      <section v-if="events.length" class="trust-panel ingestion-events-panel" data-testid="ingestion-events">
        <header><div><span>事件审计</span><h3>Monotonic Event Stream</h3></div><ScrollText :size="22" /></header>
        <article v-for="event in events" :key="event.seq"><code>#{{ event.seq }}</code><strong>{{ event.title }}</strong><p>{{ event.detail }}</p></article>
      </section>

      <section class="trust-panel policy-manifest-panel">
        <header><div><span>不可变采集策略</span><h3>Policy Manifests</h3></div><Fingerprint :size="22" /></header>
        <article v-for="policy in summary.policies" :key="policy.policy_id">
          <span :class="['rule-status', policy.status]">{{ policy.status }}</span><strong>{{ policy.name }} · {{ policy.version }}</strong>
          <small>{{ policy.max_records }} records / {{ Math.round(policy.max_bytes / 1000) }} KB / cutoff {{ policy.require_cutoff ? 'required' : 'optional' }}</small>
          <code>{{ shortHash(policy.manifest_hash) }}</code>
        </article>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { Building2, Cable, FileJson2, Fingerprint, ListChecks, Plus, ScrollText, ShieldCheck } from 'lucide-vue-next'
import { canWriteIngestion, compactManifestHash, validateIngestionDraft } from '../../composables/ingestionProjection'

const props = defineProps({ organization: Object, members: { type: Array, default: () => [] }, summary: Object, events: { type: Array, default: () => [] }, loading: Boolean, error: String, canWrite: Boolean })
const emit = defineEmits(['refresh', 'create-connector', 'ingest', 'events', 'cancel', 'retry'])
const allowedToWrite = computed(() => props.canWrite && canWriteIngestion(props.organization?.member_role))
const today = new Date().toISOString().slice(0, 10)
const categories = ['energy', 'food', 'trade', 'finance', 'sanctions', 'conflict', 'climate', 'other']
const connectorDraft = reactive({ name: '', source_locator: '', publisher: '', license: '' })
const recordDraft = reactive({ connector_id: '', external_ref: '', title: '', category: 'energy', observed_at: today, cutoff_at: today, content: '{\n  "value": 0\n}', content_text: '' })
const draftError = ref('')

function submitConnector() {
  emit('create-connector', { name: connectorDraft.name, connector_type: 'manual_json', source_locator: connectorDraft.source_locator, config: { publisher: connectorDraft.publisher, license: connectorDraft.license } })
}
function submitRecord() {
  draftError.value = ''
  const validation = validateIngestionDraft(recordDraft)
  if (typeof validation === 'string') {
    draftError.value = validation
    return
  }
  emit('ingest', { connectorId: recordDraft.connector_id, record: { external_ref: recordDraft.external_ref, title: recordDraft.title, category: recordDraft.category, observed_at: recordDraft.observed_at, cutoff_at: recordDraft.cutoff_at, content: validation.content, content_text: recordDraft.content_text } })
}
function shortHash(value) { return compactManifestHash(value) }
function shortTime(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '--' }
</script>
