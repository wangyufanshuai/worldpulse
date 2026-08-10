<template>
  <section class="experiment-matrix" data-testid="guided-experiment-matrix" aria-labelledby="guided-experiment-matrix-title" :aria-busy="matrix.loading">
    <header class="matrix-head">
      <div>
        <div class="matrix-kicker">V10 · Governed Evaluation</div>
        <h2 id="guided-experiment-matrix-title">有限实验矩阵</h2>
        <p>只读投影现有七成员 project_experiment；当前最多显示 6 行，不是优化器、预测引擎或任意矩阵创建器。</p>
      </div>
      <div class="matrix-status">
        <span :class="['status-pill', matrix.gate.verdict]" role="status" aria-live="polite">{{ gateLabel(matrix.gate.verdict) }}</span>
        <small>{{ matrix.execution_status }}</small>
      </div>
    </header>

    <p v-if="matrix.error" class="matrix-request-error" role="alert" data-testid="guided-experiment-matrix-error">
      {{ matrix.error }}
    </p>

    <div v-if="matrix.gate.reasons.length" role="status" aria-live="polite">
      <ul class="matrix-gates" data-testid="guided-experiment-matrix-gates">
        <li v-for="reason in matrix.gate.reasons" :key="reason">{{ reason }}</li>
      </ul>
    </div>

    <div v-if="matrix.rows.length" class="matrix-table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">参数身份</th>
            <th scope="col">场景修订</th>
            <th scope="col">角色 / 模式</th>
            <th scope="col">Run / 状态</th>
            <th scope="col">可比较性</th>
            <th scope="col">存储指标与 lineage</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in matrix.rows" :key="row.row_id" data-testid="guided-experiment-row">
            <td>
              <code :title="row.parameter_set_hash">{{ shortHash(row.parameter_set_hash) }}</code>
              <small>seed {{ row.seed }}</small>
            </td>
            <td>
              <code>{{ row.scenario_revision_id || '缺失' }}</code>
              <small :title="row.scenario_revision_hash">{{ shortHash(row.scenario_revision_hash) }}</small>
            </td>
            <td>
              <strong v-if="row.role">{{ row.role }}</strong>
              <strong v-else class="unavailable" data-testid="guided-experiment-role-unavailable">未存储，不推断</strong>
              <small>{{ row.engine_mode }}</small>
              <small v-if="!row.role" :title="row.role_unavailable_reason">V10 无角色 lineage</small>
            </td>
            <td>
              <code>{{ row.run_id || '尚未绑定' }}</code>
              <small>{{ row.status }}</small>
            </td>
            <td>
              <strong :class="row.comparable ? 'comparable' : 'unavailable'">{{ row.comparable ? '可比较' : '不可比较' }}</strong>
              <ul v-if="row.non_comparable_reasons.length">
                <li v-for="reason in row.non_comparable_reasons" :key="reason">{{ reason }}</li>
              </ul>
            </td>
            <td>
              <details>
                <summary>查看原始存储投影</summary>
                <dl>
                  <div><dt>Metrics</dt><dd><pre>{{ pretty(row.metrics_projection) }}</pre></dd></div>
                  <div><dt>Evaluation metrics</dt><dd><pre>{{ pretty(row.evaluation_metrics) }}</pre></dd></div>
                  <div><dt>Uncertainty</dt><dd class="unavailable">{{ row.uncertainty_unavailable_reason }}</dd></div>
                  <div><dt>Plugin lineage</dt><dd class="unavailable">{{ row.plugin_lineage_unavailable_reason }}</dd></div>
                  <div><dt>Evidence Pack</dt><dd><code>{{ row.lineage.evidence_pack_hash || '缺失' }}</code></dd></div>
                  <div><dt>Result Hash</dt><dd><code>{{ row.lineage.result_hash || '缺失' }}</code></dd></div>
                  <div><dt>Verification Hash</dt><dd><code>{{ row.lineage.verification_hash || '缺失' }}</code></dd></div>
                  <div><dt>Artifacts</dt><dd><code>{{ row.lineage.artifact_refs.join(', ') || '无' }}</code></dd></div>
                </dl>
              </details>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="matrix-empty" role="status" aria-live="polite">{{ matrix.loading ? '正在读取受治理实验批次…' : '没有可显示的受治理实验行。' }}</p>
    <p v-if="matrix.hidden_row_count" class="matrix-budget" data-testid="guided-experiment-row-budget">
      受 4C 显示预算约束，另有 {{ matrix.hidden_row_count }} 行保留在 V10 固定七成员批次中；未改变后端成员数。
    </p>
  </section>
</template>

<script setup lang="ts">
import type { PropType } from 'vue'
import type { GuidedExperimentMatrixProjection, GuidedGateVerdict } from '../../contracts/researchWorkspace'

defineProps({
  matrix: { type: Object as PropType<GuidedExperimentMatrixProjection>, required: true },
})

function gateLabel(verdict: GuidedGateVerdict) {
  return ({ pass: 'lineage 已验证', block: 'fail-closed', unavailable: '不可用' })[verdict]
}

function shortHash(value: string) {
  return value ? `${value.slice(0, 12)}…` : '缺失'
}

function pretty(value: unknown) {
  return value === null || value === undefined ? '未存储' : JSON.stringify(value, null, 2)
}
</script>

<style scoped>
.experiment-matrix { display: grid; gap: 14px; border: 1px solid rgba(148, 163, 184, .28); border-radius: 18px; padding: 16px; background: rgba(9, 15, 26, .62); color: #eef4fb; }
.matrix-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.matrix-head h2 { margin: 4px 0 6px; }
.matrix-head p { margin: 0; max-width: 780px; color: #b7c4d3; line-height: 1.5; }
.matrix-kicker { color: #9dd6fa; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
.matrix-status { display: grid; justify-items: end; gap: 6px; color: #b7c4d3; }
.status-pill { border: 1px solid currentColor; border-radius: 999px; padding: 5px 9px; font-size: 12px; white-space: nowrap; }
.status-pill.pass, .comparable { color: #63d3a1; }
.status-pill.block, .unavailable, .matrix-gates, .matrix-request-error { color: #f2a2a2; }
.matrix-gates { margin: 0; padding: 10px 12px 10px 30px; border: 1px solid rgba(242, 139, 139, .4); border-radius: 12px; background: rgba(82, 29, 35, .3); line-height: 1.5; }
.matrix-request-error { margin: 0; }
.matrix-table-wrap { overflow-x: auto; }
table { width: 100%; min-width: 1180px; border-collapse: collapse; font-size: 12px; }
th, td { border-bottom: 1px solid rgba(148, 163, 184, .2); padding: 10px; text-align: left; vertical-align: top; }
th { color: #9dd6fa; font-weight: 600; }
td { color: #dce7f2; }
td > code, td > small, td > strong { display: block; margin-bottom: 5px; }
code { overflow-wrap: anywhere; color: #cde9fb; }
td ul { margin: 5px 0 0; padding-left: 16px; color: #b7c4d3; line-height: 1.45; }
details summary { cursor: pointer; color: #9dd6fa; }
details dl { display: grid; gap: 8px; max-width: 420px; }
details dl div { display: grid; gap: 3px; }
dt { color: #b7c4d3; }
dd { margin: 0; }
pre { max-height: 190px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; color: #cfe0ed; background: rgba(4, 9, 18, .5); border-radius: 8px; padding: 8px; }
.matrix-empty, .matrix-budget { margin: 0; color: #b7c4d3; }
@media (max-width: 760px) { .matrix-head { flex-direction: column; } .matrix-status { justify-items: start; } }
</style>
