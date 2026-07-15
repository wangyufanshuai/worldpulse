<template>
  <div class="module-workbench data-workbench" data-testid="war-room-data-module">
    <section class="module-panel primary">
      <div class="module-panel-head">
        <div><span>数据控制台</span><h3>运行快照与展示合同</h3></div>
        <div class="segmented-control">
          <button type="button" :class="{ active: props.activeDataTab === 'tables' }" @click="props.onSetActiveDataTab?.('tables')">表格</button>
          <button type="button" :class="{ active: props.activeDataTab === 'json' }" @click="props.onSetActiveDataTab?.('json')">JSON</button>
        </div>
      </div>
      <div class="data-summary-grid">
        <article><span>当前 run</span><strong>{{ props.shortRunId?.(props.selectedRunId) || '--' }}</strong><button type="button" @click="props.onCopyRunId?.()">复制 run id</button></article>
        <article><span>ui_state 实体</span><strong>{{ props.uiMapEntities.length }}</strong><small>地图、图层、时间线、Agent 面板</small></article>
        <article><span>时间线</span><strong>{{ props.timelineEvents.length }}</strong><small>{{ props.timelineEvents.map(item => item.time).join(' / ') }}</small></article>
        <article><span>免责声明</span><strong>Not a prediction</strong><small>{{ props.warRoom?.disclaimer }}</small></article>
      </div>

      <div v-if="props.activeDataTab === 'tables'" class="data-table-stack">
        <section>
          <h4>确定性规则输出</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>国家</th><th>风险</th><th>主导通道</th><th>Delta</th></tr></thead>
              <tbody><tr v-for="country in props.mapCountries" :key="country.code"><td>{{ props.countryNameShort?.(country.code) || country.code }}</td><td>{{ Math.round(country.risk) }}</td><td>{{ props.riskChannel?.(country.dominant_channel) || country.dominant_channel }}</td><td>{{ country.delta === null || country.delta === undefined ? '--' : props.signed?.(country.delta) }}</td></tr></tbody>
            </table>
          </div>
        </section>
        <section v-if="props.lifecycleAudit" data-testid="lifecycle-artifact-table">
          <h4>Lifecycle 制品与完整性</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>制品</th><th>Schema</th><th>SHA-256</th><th>完整性</th></tr></thead>
              <tbody><tr v-for="artifact in props.lifecycleAudit.artifacts || []" :key="artifact.artifact_id"><td>{{ artifact.artifact_type }}</td><td>{{ artifact.schema_version }}</td><td><code>{{ shortHash(artifact.sha256) }}</code></td><td :class="artifact.integrity_status === 'verified' ? 'positive' : 'negative'">{{ artifact.integrity_status }}</td></tr></tbody>
            </table>
          </div>
        </section>
        <section v-if="props.lifecycleAudit?.steps?.length" data-testid="lifecycle-step-table">
          <h4>阶段执行与检查点</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>阶段</th><th>Attempt</th><th>状态</th><th>耗时</th><th>输入/输出 Hash</th><th>Artifact refs</th></tr></thead>
              <tbody>
                <tr v-for="step in props.lifecycleAudit.steps" :key="step.step_id">
                  <td>{{ step.step_key }}<small>{{ step.step_version }}</small></td>
                  <td><code>{{ shortHash(step.attempt_id) }}</code></td>
                  <td :class="step.status === 'completed' ? 'positive' : 'negative'">{{ step.status }}</td>
                  <td>{{ step.duration_ms }} ms</td>
                  <td><code>{{ shortHash(step.input_hash) }} / {{ shortHash(step.output_hash) }}</code></td>
                  <td>{{ (step.artifact_refs || []).length }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section v-if="props.lifecycleAudit?.attempts?.length" data-testid="lifecycle-attempt-table">
          <h4>Worker Attempt 与恢复关系</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>Attempt</th><th>Worker</th><th>编号</th><th>状态</th><th>恢复阶段</th><th>失败原因</th></tr></thead>
              <tbody>
                <tr v-for="attempt in props.lifecycleAudit.attempts" :key="attempt.attempt_id">
                  <td><code>{{ shortHash(attempt.attempt_id) }}</code></td><td>{{ attempt.worker_id }}</td><td>{{ attempt.attempt_number }}</td>
                  <td>{{ attempt.status }}</td><td>{{ attempt.resume_from_step || '--' }}</td><td>{{ attempt.error_code || '--' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <section v-if="props.lifecycleAudit?.agent_runtime" data-testid="lifecycle-invocations">
          <h4>模型调用审计（不保存原始 Prompt / Response）</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>角色</th><th>Provider / Model</th><th>状态</th><th>耗时</th><th>Prompt Hash</th></tr></thead>
              <tbody><tr v-for="item in props.lifecycleAudit.agent_runtime.invocations || []" :key="item.invocation_id"><td>{{ item.role_id }}</td><td>{{ item.provider }} / {{ item.model }}</td><td>{{ item.status }}</td><td>{{ item.duration_ms }} ms</td><td><code>{{ shortHash(item.prompt_hash) }}</code></td></tr></tbody>
            </table>
          </div>
        </section>
        <section>
          <h4>供应链压力</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>链路</th><th>容量</th><th>中断</th><th>替代率</th><th>滞后</th></tr></thead>
              <tbody><tr v-for="chain in props.warRoom?.supply_chains || []" :key="chain.key"><td>{{ props.chainName?.(chain.key, chain.name) || chain.name || chain.key }}</td><td>{{ Math.round(Number(chain.capacity || 0)) }}</td><td>{{ Math.round(Number(chain.disruption || chain.pressure || 0)) }}</td><td>{{ Math.round(Number(chain.substitution || 0)) }}</td><td>{{ chain.lag_days }} 天</td></tr></tbody>
            </table>
          </div>
        </section>
        <section>
          <h4>展示合同</h4>
          <div class="data-table">
            <table>
              <thead><tr><th>类型</th><th>数量</th><th>说明</th></tr></thead>
              <tbody>
                <tr><td>entity_index</td><td>{{ props.entityIndex.length }}</td><td>指挥搜索可定位实体</td></tr>
                <tr><td>entity_details</td><td>{{ Object.keys(props.entityDetails).length }}</td><td>统一详情抽屉数据</td></tr>
                <tr><td>command_actions</td><td>{{ props.commandActions.length }}</td><td>可执行动作与状态</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <pre v-else class="json-preview">{{ props.dataJsonPreview }}</pre>
    </section>
    <aside class="module-panel side">
      <div class="module-panel-head">
        <div><span>审计</span><h3>审计操作</h3></div>
      </div>
      <button class="primary-action" type="button" @click="props.onDownloadUiState?.()"><Download :size="16" /> 下载 ui_state.json</button>
      <button class="secondary full" type="button" @click="props.onOpenReplayShortcut?.()"><PackageCheck :size="16" /> 导出复盘包</button>
      <div class="audit-note-list">
        <article><strong>用户输入</strong><p>场景、政策动作、国家和供应链参数来自 Scenario Builder。</p></article>
        <article><strong>确定性规则</strong><p>风险、Agent 决策和图谱边权重由本地规则引擎生成。</p></article>
        <article><strong>展示合同</strong><p>前端优先读取 workspace API 与 ui_state，旧字段作为 fallback。</p></article>
        <article v-if="props.lifecycleAudit?.metrics"><strong>运行可观测性</strong><p>总耗时 {{ props.lifecycleAudit.metrics.total_duration_ms }} ms；Worker 尝试 {{ props.lifecycleAudit.metrics.attempt_count }} 次。</p></article>
        <article v-if="props.lifecycleAudit?.integrity"><strong>制品完整性</strong><p>{{ props.lifecycleAudit.integrity.verified_count }} 个已验证，{{ props.lifecycleAudit.integrity.invalid_count }} 个异常。</p></article>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { Download, PackageCheck } from 'lucide-vue-next'

const props = defineProps({
  activeDataTab: { type: String, default: 'tables' },
  selectedRunId: { type: String, default: '' },
  shortRunId: { type: Function, default: null },
  countryNameShort: { type: Function, default: null },
  riskChannel: { type: Function, default: null },
  signed: { type: Function, default: null },
  chainName: { type: Function, default: null },
  mapCountries: { type: Array, default: () => [] },
  warRoom: { type: Object, default: null },
  uiMapEntities: { type: Array, default: () => [] },
  timelineEvents: { type: Array, default: () => [] },
  entityIndex: { type: Array, default: () => [] },
  entityDetails: { type: Object, default: () => ({}) },
  commandActions: { type: Array, default: () => [] },
  dataJsonPreview: { type: String, default: '' },
  onSetActiveDataTab: { type: Function, default: null },
  onCopyRunId: { type: Function, default: null },
  onDownloadUiState: { type: Function, default: null },
  onOpenReplayShortcut: { type: Function, default: null },
  lifecycleAudit: { type: Object, default: null }
})

const shortHash = value => String(value || '').slice(0, 16)
</script>
