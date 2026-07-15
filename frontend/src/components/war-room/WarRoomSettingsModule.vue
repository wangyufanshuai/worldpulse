<template>
  <div class="section-card-grid settings-grid" data-testid="war-room-settings-module">
    <article><span>策略边界</span><strong>策略沙盘</strong><p>不是现实战争预测、投资建议或政策建议。</p></article>
    <article><span>显示设置</span><strong>{{ props.visibleMapLayers.length }} 个图层</strong><p>当前可见：{{ props.visibleMapLayers.map(layerLabel).join('、') }}</p></article>
    <article class="upcoming-card"><span>待上线</span><strong>3D 地球</strong><p>后续接入独立 3D 视图，本版不做伪交互。</p></article>
    <article class="upcoming-card"><span>待上线</span><strong>告警订阅</strong><p>通知中心和团队协作将作为后续能力。</p></article>
  </div>
</template>

<script setup>
const props = defineProps({
  visibleMapLayers: { type: Array, default: () => [] },
  layerLabel: { type: Function, default: null }
})
</script>
