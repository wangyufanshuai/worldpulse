<template>
  <div class="section-card-grid settings-grid" data-testid="war-room-settings-module">
    <article class="settings-control-card">
      <span>生命周期执行模式</span>
      <strong>{{ engineModeLabel }}</strong>
      <select
        :value="props.engineMode"
        data-testid="lifecycle-engine-mode"
        @change="props.onEngineModeChange?.($event.target.value)"
      >
        <option value="deterministic">纯确定性模式</option>
        <option value="mock_agent">可重复 Mock Agent</option>
      </select>
      <p>{{ modeDescription }}</p>
    </article>
    <article><span>策略边界</span><strong>策略沙盘</strong><p>不是现实战争预测、投资建议或政策建议。</p></article>
    <article><span>显示设置</span><strong>{{ props.visibleMapLayers.length }} 个图层</strong><p>当前可见：{{ props.visibleMapLayers.map(layerLabel).join('、') }}</p></article>
    <article class="upcoming-card"><span>待上线</span><strong>3D 地球</strong><p>后续接入独立 3D 视图，本版不做伪交互。</p></article>
    <article class="upcoming-card"><span>待上线</span><strong>告警订阅</strong><p>通知中心和团队协作将作为后续能力。</p></article>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  visibleMapLayers: { type: Array, default: () => [] },
  layerLabel: { type: Function, default: null },
  engineMode: { type: String, default: 'deterministic' },
  onEngineModeChange: { type: Function, default: null }
})

const engineModeLabel = computed(() => props.engineMode === 'mock_agent' ? 'Mock Agent 合同模式' : '纯确定性模式')
const modeDescription = computed(() => props.engineMode === 'mock_agent'
  ? '生成可重复的结构化提案并执行一致性准入；不会修改确定性数值。'
  : '仅运行确定性引擎和只读一致性审计。')
</script>
