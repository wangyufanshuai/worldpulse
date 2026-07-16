<template>
  <section class="evaluation-center" data-testid="evaluation-center">
    <div class="evaluation-toolbar">
      <div>
        <span class="section-kicker">EVALUATION INTEGRITY V2</span>
        <h3>跨模式评估与历史盲测</h3>
        <p class="sandbox-note">安全与完整性为硬门禁；历史方向、排名与协商质量仅作观察，不宣称真实世界预测准确率。</p>
      </div>
      <div class="evaluation-actions">
        <button class="primary" type="button" data-testid="evaluation-create-standard" :disabled="loading" @click="$emit('create-standard')">创建 84 成员工程批次</button>
        <button type="button" data-testid="evaluation-create-historical" :disabled="loading || !activeLabelPack" @click="$emit('create-historical', activeLabelPack?.label_pack_id)">创建 330 成员历史批次</button>
      </div>
    </div>

    <nav class="evaluation-tabs" aria-label="评估轨道">
      <button v-for="item in tabItems" :key="item.key" type="button" :class="{ active: activeTab === item.key }" :data-testid="`evaluation-tab-${item.key}`" @click="activeTab = item.key">
        {{ item.label }} <b>{{ item.count }}</b>
      </button>
    </nav>

    <div class="evaluation-grid">
      <article><span>Engineering Suite</span><strong>{{ suite?.version || '--' }}</strong><small>{{ suite?.case_count || 0 }} 案例 · 84 Members</small></article>
      <article><span>Historical Suite</span><strong>{{ benchmarkSuite?.status || '未导入' }}</strong><small>{{ benchmarkSuite ? `${benchmarkSuite.development_count}/${benchmarkSuite.blind_count} 开发/盲测` : '官方材料 Blob 未齐时禁止激活' }}</small></article>
      <article><span>安全门禁</span><strong :class="latest?.safety_status === 'passed' ? 'passed' : 'blocked'">{{ latest?.safety_status || 'pending' }}</strong><small>{{ failedChecks }} 项真实 Artifact 验证失败</small></article>
      <article><span>密封标签包</span><strong>{{ activeLabelPack?.status || '不可用' }}</strong><small>{{ activeLabelPack ? `${activeLabelPack.case_count} 个 blind labels` : '需 Reviewer + Admin 双人审批' }}</small></article>
    </div>

    <div v-if="latest" class="evaluation-batch-bar">
      <div><span>当前批次</span><b>{{ latest.batch_id }}</b><small>{{ latest.evaluation_track }} · {{ latest.completed_members }}/{{ latest.total_members }}</small></div>
      <div class="evaluation-actions">
        <button v-if="['queued','running'].includes(latest.status)" type="button" data-testid="evaluation-pause" @click="$emit('control', latest.batch_id, 'pause')">暂停</button>
        <button v-if="latest.status === 'paused'" type="button" data-testid="evaluation-resume" @click="$emit('control', latest.batch_id, 'resume')">恢复</button>
        <button v-if="['queued','running','paused'].includes(latest.status)" type="button" data-testid="evaluation-cancel" @click="$emit('control', latest.batch_id, 'cancel')">取消</button>
        <button v-if="['failed','cancelled'].includes(latest.status)" type="button" data-testid="evaluation-retry" @click="$emit('control', latest.batch_id, 'retry')">重试</button>
      </div>
    </div>

    <div class="evaluation-members" data-testid="evaluation-member-matrix">
      <button v-for="member in visibleMembers" :key="member.member_id" type="button" :class="['evaluation-member', member.status, member.verification_status]" @click="$emit('inspect', member.batch_id)">
        <span>{{ member.engine_mode }}</span>
        <b>{{ shortCase(member.case_id) }}</b>
        <small>seed {{ member.seed }} · {{ member.status }} · {{ member.verification_status }}</small>
      </button>
    </div>

    <div v-if="verification.length" class="evaluation-verification" data-testid="evaluation-verification">
      <article v-for="item in verification.slice(0, 30)" :key="item.verification_id" :class="item.status">
        <span>{{ item.check_key }}</span><b>{{ item.status }}</b>
        <small>{{ item.evidence_artifact_ids.length }} Artifact 依据 · {{ item.verifier_version }}</small>
      </article>
    </div>

    <div v-if="historicalReport" class="evaluation-historical-report" data-testid="historical-report">
      <h4>历史观察基线</h4>
      <p>120 案例 · blind 标签保持遮蔽 · {{ historicalReport.aggregate_metrics?.promotion_effect || 'observation_only' }}</p>
      <code>{{ historicalReport.report_hash }}</code>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>
    <p v-else class="sandbox-note">所有子运行复用真实 v2 lifecycle；离线 Replay 的 Provider 调用必须为 0，任何 Hash、作用域或 lineage 异常均 fail-closed。</p>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  suite: Object,
  benchmarkSuites: { type: Array, default: () => [] },
  labelPacks: { type: Array, default: () => [] },
  batchesByTab: { type: Object, default: () => ({}) },
  latest: Object,
  report: Object,
  historicalReport: Object,
  members: { type: Array, default: () => [] },
  verification: { type: Array, default: () => [] },
  loading: Boolean,
  error: String
})
defineEmits(['create-standard', 'create-historical', 'inspect', 'control'])

const activeTab = ref('engineering')
const benchmarkSuite = computed(() => props.benchmarkSuites.find(item => item.status === 'active') || props.benchmarkSuites[0])
const activeLabelPack = computed(() => props.labelPacks.find(item => item.status === 'active'))
const failedChecks = computed(() => props.verification.filter(item => item.status === 'failed').length)
const tabItems = computed(() => [
  { key: 'engineering', label: 'Engineering', count: props.batchesByTab.engineering?.length || 0 },
  { key: 'historical', label: 'Historical', count: props.batchesByTab.historical?.length || 0 },
  { key: 'project', label: 'Project', count: props.batchesByTab.project?.length || 0 },
  { key: 'live', label: 'Live', count: props.batchesByTab.live?.length || 0 }
])
const visibleMembers = computed(() => props.members.slice(0, activeTab.value === 'historical' ? 60 : 42))
const shortCase = value => String(value || '').replace(/^eval_/, '').replace(/^hist_blind_/, 'blind/').replace(/^hist_/, '')
</script>
