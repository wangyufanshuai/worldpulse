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
  onOpenReplayShortcut: { type: Function, default: null }
})
</script>
