<template>
  <div class="module-workbench graph-workbench" data-testid="war-room-graph-module">
    <aside class="module-panel list">
      <div class="module-panel-head">
        <div><span>因果链路</span><h3>因果边列表</h3></div>
      </div>
      <div class="filter-chip-row">
        <button
          v-for="filter in props.graphTypeOptions"
          :key="filter.key"
          type="button"
          :class="{ active: props.graphTypeFilters.includes(filter.key) }"
          @click="props.onToggleGraphTypeFilter?.(filter.key)"
        >
          {{ filter.label }}
        </button>
      </div>
      <div class="edge-list">
        <button
          v-for="edge in props.filteredGraphEdges"
          :key="edge.id"
          type="button"
          :class="{ active: props.focusedGraphEdgeId === edge.id }"
          @click="props.onFocusGraphEdge?.(edge)"
        >
          <span>{{ props.edgeLabel?.(edge.edge.source) }} → {{ props.edgeLabel?.(edge.edge.target) }}</span>
          <strong>{{ Number(edge.edge.weight || 0).toFixed(2) }}</strong>
          <small>{{ edge.edge.mechanism || edge.edge.relation || '因果传导机制' }}</small>
        </button>
      </div>
    </aside>
    <section class="module-panel graph-stage-panel">
      <div class="module-panel-head">
        <div><span>图谱画布</span><h3>影响图谱</h3></div>
        <button class="secondary compact" type="button" @click="props.onRenderSectionGraph?.()"><Network :size="14" /> 重绘</button>
      </div>
      <div ref="sectionGraphEl" class="graph-canvas section-graph-canvas" data-testid="section-graph-canvas"></div>
    </section>
    <aside class="module-panel side">
      <div class="module-panel-head">
        <div><span>边详情</span><h3>链路机制</h3></div>
      </div>
      <template v-if="props.activeGraphEdge">
        <div class="edge-detail-title">
          <strong>{{ props.edgeLabel?.(props.activeGraphEdge.edge.source) }} → {{ props.edgeLabel?.(props.activeGraphEdge.edge.target) }}</strong>
          <span>权重 {{ Number(props.activeGraphEdge.edge.weight || 0).toFixed(2) }}</span>
        </div>
        <p>{{ props.activeGraphEdge.edge.mechanism || props.activeGraphEdge.edge.relation || props.activeGraphEdge.edge.explanation || '该边来自当前 War Room 影响图。' }}</p>
        <dl class="detail-dl">
          <div><dt>滞后天数</dt><dd>{{ props.activeGraphEdge.edge.lag_days ?? 0 }} 天</dd></div>
          <div><dt>关联国家</dt><dd>{{ (props.activeGraphEdge.edge.related_countries || []).map(props.countryNameShort).join('、') || '--' }}</dd></div>
          <div><dt>关联链路</dt><dd>{{ (props.activeGraphEdge.edge.related_chains || []).map(props.chainName).join('、') || '--' }}</dd></div>
        </dl>
        <button class="primary-action" type="button" @click="props.onOpenEntityDetail?.('causal_edge', props.activeGraphEdge.id, props.activeGraphEdge.edge)">打开详情抽屉</button>
      </template>
      <div v-else class="empty">选择一条因果边查看机制。</div>
    </aside>
  </div>
</template>

<script setup>
import { Network } from 'lucide-vue-next'

const props = defineProps({
  graphTypeOptions: { type: Array, default: () => [] },
  graphTypeFilters: { type: Array, default: () => [] },
  filteredGraphEdges: { type: Array, default: () => [] },
  focusedGraphEdgeId: { type: String, default: '' },
  activeGraphEdge: { type: Object, default: null },
  edgeLabel: { type: Function, default: null },
  countryNameShort: { type: Function, default: null },
  chainName: { type: Function, default: null },
  onToggleGraphTypeFilter: { type: Function, default: null },
  onFocusGraphEdge: { type: Function, default: null },
  onRenderSectionGraph: { type: Function, default: null },
  onOpenEntityDetail: { type: Function, default: null }
})
</script>
