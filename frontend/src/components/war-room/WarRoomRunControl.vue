<template>
  <section class="war-room-run-control" data-testid="war-room-run-control">
    <div class="run-control-summary">
      <span>运行控制台</span>
      <strong>{{ runControl.scenario_title_zh || scenarioTitle }}</strong>
      <small>{{ runControl.policy_actions_zh?.length ? `政策动作：${runControl.policy_actions_zh.join('、')}` : '基线运行：未启用政策动作' }}</small>
    </div>
    <div class="run-control-metrics">
      <article v-for="item in activeRunControlItems" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </article>
    </div>
    <div class="run-control-actions">
      <button type="button" data-testid="war-room-run-action" @click="$emit('run')"><Play :size="14" />运行</button>
      <button type="button" :disabled="!runControl.current_run_id" data-testid="war-room-clone-action" @click="$emit('clone')"><Copy :size="14" />克隆</button>
      <button type="button" :disabled="!runControl.compare_ready" data-testid="war-room-compare-action" @click="$emit('compare')"><GitCompareArrows :size="14" />对比</button>
      <button type="button" :disabled="!runControl.replay_ready" data-testid="war-room-replay-action" @click="$emit('replay')"><PackageCheck :size="14" />复盘</button>
      <button type="button" :class="{ active: showDeltaOverlay }" :disabled="!runControl.compare_ready" data-testid="war-room-delta-overlay" @click="$emit('toggle-delta')">Delta</button>
    </div>
  </section>
</template>

<script setup>
import { Copy, GitCompareArrows, PackageCheck, Play } from 'lucide-vue-next'

defineProps({
  activeRunControlItems: { type: Array, required: true },
  runControl: { type: Object, required: true },
  scenarioTitle: { type: String, required: true },
  showDeltaOverlay: { type: Boolean, default: false }
})

defineEmits(['clone', 'compare', 'replay', 'run', 'toggle-delta'])
</script>
