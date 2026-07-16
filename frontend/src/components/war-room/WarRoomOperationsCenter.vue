<template>
  <section class="operations-center" data-testid="war-room-operations-center">
    <div v-if="loading && !summary" class="trust-empty">正在读取平台运行状态…</div>
    <div v-else-if="error && !summary" class="trust-empty error-text">{{ error }} <button type="button" @click="$emit('refresh')">重试</button></div>
    <template v-else-if="summary">
      <section class="operations-hero">
        <div>
          <span class="trust-eyebrow"><ServerCog :size="16" /> OPERATIONS CONTROL PLANE</span>
          <h3>生产运维控制平面</h3>
          <p>监控数据库、规则基线、worker 心跳与组织资源边界。该控制面只管理容量和执行进程，不改写确定性风险数值。</p>
        </div>
        <span :class="['operations-verdict', summary.readiness.status]" data-testid="operations-readiness-status">
          {{ readinessLabel(summary.readiness.status) }}
        </span>
      </section>

      <section class="operations-readiness-grid">
        <article><span>数据库</span><strong>{{ summary.readiness.database_backend }}</strong><small>{{ summary.readiness.schema_ok ? 'Schema 已验证' : 'Schema 异常' }}</small></article>
        <article><span>规则基线</span><strong>{{ summary.readiness.rule_pack_ok ? 'ACTIVE' : 'MISSING' }}</strong><small>active Rule Pack</small></article>
        <article><span>生命周期 Worker</span><strong>{{ summary.readiness.lifecycle_workers_fresh }}</strong><small>新鲜心跳</small></article>
        <article><span>采集 Worker</span><strong>{{ summary.readiness.ingestion_workers_fresh }}</strong><small>新鲜心跳</small></article>
        <article><span>排队运行</span><strong>{{ summary.readiness.queued_runs }}</strong><small>run_jobs</small></article>
        <article><span>排队采集</span><strong>{{ summary.readiness.queued_ingestion_jobs }}</strong><small>ingestion_jobs</small></article>
        <article><span>排队抽取</span><strong>{{ summary.readiness.queued_document_jobs }}</strong><small>document_extraction_jobs</small></article>
        <article><span>材料共享卷</span><strong>{{ summary.readiness.blob_storage_ok ? 'WRITABLE' : 'FAILED' }}</strong><small>content-addressed blobs</small></article>
      </section>

      <section class="operations-grid">
        <article class="trust-panel operations-workers">
          <header><div><span>WORKER REGISTRY</span><h3>执行节点与排空</h3></div><button type="button" class="secondary" @click="$emit('refresh')"><RefreshCw :size="14" /> 刷新</button></header>
          <div class="worker-node-list" data-testid="operations-worker-list">
            <article v-for="worker in summary.workers" :key="worker.worker_id">
              <span :class="['worker-state', worker.status]">{{ worker.status }}</span>
              <div><strong>{{ worker.worker_kind === 'lifecycle' ? '生命周期 Worker' : '采集 Worker' }}</strong><code>{{ worker.worker_id }}</code></div>
              <div><small>{{ worker.hostname }} · PID {{ worker.process_id }}</small><small>心跳 {{ formatTime(worker.heartbeat_at) }} · 完成 {{ worker.jobs_completed }}</small></div>
              <button v-if="canOperate && ['ready', 'busy'].includes(worker.status)" type="button" class="secondary danger-action" :data-testid="`drain-worker-${worker.worker_id}`" @click="$emit('drain', worker.worker_id)">安全排空</button>
            </article>
            <div v-if="!summary.workers.length" class="trust-empty">尚无 worker 注册。独立进程启动后会在此出现。</div>
          </div>
        </article>

        <article class="trust-panel operations-quota">
          <header><div><span>ORGANIZATION QUOTA</span><h3>组织资源边界</h3></div><code>{{ summary.organization_id }}</code></header>
          <form @submit.prevent="submitQuota" data-testid="operations-quota-form">
            <label v-for="item in quotaRows" :key="item.key">
              <span><strong>{{ item.label }}</strong><small>{{ item.used }} / {{ quotaDraft[item.key] }}</small></span>
              <progress :value="Math.min(item.used, quotaDraft[item.key])" :max="quotaDraft[item.key] || 1"></progress>
              <input v-if="canOperate" v-model.number="quotaDraft[item.key]" type="number" min="1" required :data-testid="`quota-${item.key}`" />
            </label>
            <button v-if="canOperate" type="submit" :disabled="loading" data-testid="operations-save-quota"><Save :size="14" /> 保存配额</button>
            <p v-else class="sandbox-note">当前角色为只读；配额变更由管理员提交并追加审计记录。</p>
          </form>
        </article>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { RefreshCw, Save, ServerCog } from 'lucide-vue-next'
import { operationsQuotaRows, operationsReadinessLabel } from '../../composables/operationsProjection'

const props = defineProps({
  summary: { type: Object, default: null },
  loading: Boolean,
  error: { type: String, default: '' },
  canOperate: Boolean,
})
const emit = defineEmits(['refresh', 'save-quota', 'drain'])
const quotaDraft = reactive({ max_projects: 1, max_active_runs: 1, max_ingestion_jobs_per_day: 1, max_evidence_snapshots: 1, max_source_documents: 1, max_document_bytes: 1024 })

watch(() => props.summary?.quota, quota => {
  if (quota) Object.assign(quotaDraft, quota)
}, { immediate: true, deep: true })

const quotaRows = computed(() => operationsQuotaRows(props.summary || {}))

function submitQuota() {
  emit('save-quota', {
    max_projects: quotaDraft.max_projects,
    max_active_runs: quotaDraft.max_active_runs,
    max_ingestion_jobs_per_day: quotaDraft.max_ingestion_jobs_per_day,
    max_evidence_snapshots: quotaDraft.max_evidence_snapshots,
    max_source_documents: quotaDraft.max_source_documents,
    max_document_bytes: quotaDraft.max_document_bytes,
  })
}
const readinessLabel = operationsReadinessLabel
function formatTime(value) { return value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : '--' }
</script>
