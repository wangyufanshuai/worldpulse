<template>
  <section class="trust-center" data-testid="war-room-trust-center">
    <div v-if="loading" class="trust-empty">正在加载可信度证据链…</div>
    <div v-else-if="error" class="trust-empty error-text">{{ error }} <button type="button" @click="$emit('refresh')">重试</button></div>
    <template v-else-if="summary">
      <section class="trust-hero">
        <div>
          <span class="trust-eyebrow"><ShieldCheck :size="16" /> TRUST CONTROL PLANE</span>
          <h3>{{ summary.report_allowed ? '允许进入正式报告' : '尚未满足正式报告门槛' }}</h3>
          <p>数值权威仍属于确定性引擎；人工复核只能确认、退回或拒绝晋升，不能绕过一致性评估器。</p>
        </div>
        <span :class="['trust-verdict', summary.report_allowed ? 'passed' : 'blocked']" data-testid="trust-report-gate">
          {{ summary.report_allowed ? 'REPORT READY' : 'FAIL CLOSED' }}
        </span>
      </section>

      <section class="trust-summary-grid">
        <article data-testid="trust-rule-version"><span>当前规则版本</span><strong>{{ summary.rule_pack.version }}</strong><small>{{ shortHash(summary.rule_pack.manifest_hash) }}</small></article>
        <article data-testid="trust-calibration-status"><span>校准状态</span><strong>{{ calibrationLabel }}</strong><small>{{ summary.calibration?.metrics?.case_count || 0 }} 个版本化案例</small></article>
        <article data-testid="trust-review-count"><span>待复核</span><strong>{{ summary.pending_review_count }}</strong><small>append-only 决策</small></article>
        <article data-testid="trust-data-coverage"><span>数据覆盖率</span><strong>{{ percent(summary.data_coverage) }}</strong><small>冻结快照与证据 Hash</small></article>
      </section>

      <section class="trust-grid">
        <article class="trust-panel">
          <header><div><span>规则治理</span><h3>Rule Pack Manifest</h3></div><Fingerprint :size="22" /></header>
          <dl class="trust-manifest">
            <div><dt>Rule Pack ID</dt><dd>{{ summary.rule_pack.rule_pack_id }}</dd></div>
            <div><dt>War Room</dt><dd>{{ summary.rule_pack.war_room_rule_version }}</dd></div>
            <div><dt>Consistency</dt><dd>{{ summary.rule_pack.consistency_rule_version }}</dd></div>
            <div><dt>Adapter</dt><dd>{{ summary.rule_pack.action_adapter_version }}</dd></div>
            <div><dt>Evidence</dt><dd>{{ summary.rule_pack.evidence_policy_version }}</dd></div>
            <div><dt>Manifest Hash</dt><dd class="hash-value">{{ summary.rule_pack.manifest_hash }}</dd></div>
          </dl>
          <button v-if="canCalibrate" type="button" class="secondary" data-testid="trust-start-calibration" @click="$emit('calibrate', summary.rule_pack.rule_pack_id)">
            <Gauge :size="15" /> 运行 30 案例校准
          </button>
        </article>

        <article class="trust-panel">
          <header><div><span>晋升门槛</span><h3>Calibration Gates</h3></div><BadgeCheck :size="22" /></header>
          <div class="trust-gate-list">
            <div v-for="gate in gates" :key="gate.key" :class="{ passed: gate.passed }">
              <CheckCircle2 v-if="gate.passed" :size="16" /><XCircle v-else :size="16" />
              <span>{{ gate.label }}</span><strong>{{ gate.value }}</strong>
            </div>
          </div>
        </article>
      </section>

      <section class="trust-panel admission-panel">
        <header><div><span>Agent 准入矩阵</span><h3>一致性评估器不可绕过</h3></div><Scale :size="22" /></header>
        <div class="admission-grid">
          <article v-for="(description, outcome) in summary.agent_admission_matrix" :key="outcome" :class="outcome">
            <strong>{{ outcome }}</strong><p>{{ description }}</p>
          </article>
        </div>
      </section>

      <section class="trust-panel review-panel">
        <header><div><span>人工复核队列</span><h3>Review Cases</h3></div><ClipboardCheck :size="22" /></header>
        <div v-if="summary.reviews?.length" class="review-list">
          <article v-for="review in summary.reviews" :key="review.review_id" :data-testid="`trust-review-${review.review_id}`">
            <div><span :class="['review-severity', review.severity]">{{ review.severity }}</span><strong>{{ review.review_type }}</strong><small>{{ review.resource_type }} · {{ review.resource_id }}</small></div>
            <p>{{ review.reason }}</p>
            <div v-if="canReview" class="review-actions">
              <button type="button" @click="$emit('decision', review.review_id, 'confirmed')">确认规则结论</button>
              <button type="button" @click="$emit('decision', review.review_id, 'request_revision')">要求修订</button>
              <button v-if="review.review_type === 'rule_pack_promotion'" type="button" @click="$emit('decision', review.review_id, 'reject_promotion')">拒绝晋升</button>
            </div>
          </article>
        </div>
        <div v-else class="trust-empty">当前没有待复核事项。</div>
      </section>

      <section class="trust-panel history-panel">
        <header><div><span>规则历史</span><h3>不可变版本链</h3></div><History :size="22" /></header>
        <div class="rule-history-row" v-for="pack in summary.rule_pack_history" :key="pack.rule_pack_id">
          <span :class="['rule-status', pack.status]">{{ pack.status }}</span><strong>{{ pack.version }}</strong><code>{{ shortHash(pack.manifest_hash) }}</code><small>{{ pack.created_at }}</small>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { BadgeCheck, CheckCircle2, ClipboardCheck, Fingerprint, Gauge, History, Scale, ShieldCheck, XCircle } from 'lucide-vue-next'
import { calibrationGateRows, calibrationLabel as statusLabel, percent } from '../../composables/trustProjection'

const props = defineProps({
  summary: { type: Object, default: null }, loading: Boolean, error: { type: String, default: '' },
  canReview: Boolean, canCalibrate: Boolean,
})
defineEmits(['calibrate', 'decision', 'refresh'])

const calibrationLabel = computed(() => statusLabel(props.summary?.calibration_status))
const gates = computed(() => calibrationGateRows(props.summary))
function shortHash(value) { return value ? `${String(value).slice(0, 12)}…${String(value).slice(-8)}` : '--' }
</script>
