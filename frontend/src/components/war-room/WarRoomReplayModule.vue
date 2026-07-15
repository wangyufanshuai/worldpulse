<template>
  <div class="section-card-grid replay-route-grid" data-testid="war-room-replay-module">
    <article><span>当前运行</span><strong>{{ props.selectedRunId || '--' }}</strong><p>导出后可预览 Markdown 与 JSON 审计清单。</p></article>
    <article><span>复盘包</span><strong>{{ props.replayPack ? '已生成' : '未生成' }}</strong><p>{{ props.replayPack?.title || '点击下方导出复盘包生成审计材料。' }}</p></article>
    <article><span>反事实</span><strong>{{ props.warRoomDiff ? '可用' : '未选择' }}</strong><p>有 base/target 对比时会导出反事实复盘包。</p></article>
  </div>
</template>

<script setup>
const props = defineProps({
  selectedRunId: { type: String, default: '' },
  replayPack: { type: Object, default: null },
  warRoomDiff: { type: Object, default: null }
})
</script>
