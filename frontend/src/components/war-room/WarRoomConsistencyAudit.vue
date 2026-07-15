<template>
  <section class="war-room-consistency-audit" data-testid="consistency-audit-panel">
    <header>
      <div>
        <span class="section-kicker">一致性评估器 · Shadow Mode</span>
        <h2>只读确定性审计</h2>
      </div>
      <b :class="statusTone" data-testid="consistency-status">{{ statusLabel }}</b>
    </header>

    <template v-if="report">
      <p class="consistency-summary">{{ report.summary?.message_zh }}</p>
      <dl>
        <div><dt>已评估规则</dt><dd>{{ report.evaluated_rule_count || 0 }}</dd></div>
        <div><dt>未评估规则</dt><dd>{{ report.skipped_rule_count || 0 }}</dd></div>
        <div><dt>错误 / 警告</dt><dd>{{ report.summary?.error_count || 0 }} / {{ report.summary?.warning_count || 0 }}</dd></div>
        <div><dt>Agent 动作</dt><dd>{{ report.summary?.agent_action_count || 0 }}</dd></div>
      </dl>
      <div class="consistency-finding-list" data-testid="consistency-findings">
        <article
          v-for="finding in report.findings || []"
          :key="finding.finding_id"
          :class="finding.severity"
          data-testid="consistency-finding"
        >
          <div><strong>{{ finding.rule_id }}</strong><span>{{ finding.status }}</span></div>
          <p>{{ finding.message_zh }}</p>
          <small v-if="finding.evidence_refs?.length">证据：{{ finding.evidence_refs.join(' / ') }}</small>
        </article>
        <p v-if="!report.findings?.length" class="consistency-empty">所有可用规则均通过，没有 finding。</p>
      </div>
      <footer>
        <span>审计 Hash</span>
        <code data-testid="consistency-artifact-hash">{{ report.audit_hash }}</code>
      </footer>
    </template>
    <template v-else>
      <div class="consistency-pending" data-testid="consistency-findings">
        <strong>待评估</strong>
        <p>等待 v2 lifecycle 生成 consistency_audit artifact。历史运行不会被推测为已通过。</p>
      </div>
    </template>

    <p class="consistency-readonly">该评估器只读取结果，不修改风险数值、供应链压力、时间线或因果图。</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, default: null }
})

const statusLabel = computed(() => ({
  passed: '通过', warning: '部分评估', failed: '失败', not_evaluated: '未评估'
}[props.report?.overall_status] || '待评估'))

const statusTone = computed(() => props.report?.overall_status || 'pending')
</script>
