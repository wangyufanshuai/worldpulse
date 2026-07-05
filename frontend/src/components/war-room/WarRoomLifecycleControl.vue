<template>
  <aside class="war-room-lifecycle-control" data-testid="war-room-lifecycle-control">
    <section class="lifecycle-card current-scenario">
      <div class="lifecycle-card-head">
        <span>当前场景</span>
        <button type="button" data-testid="war-room-scenario-edit" @click="$emit('show-upcoming', '场景编辑', '生命周期视图复用当前 War Room 场景配置。')">编辑</button>
      </div>
      <h2>{{ control.scenarioTitle }}</h2>
      <p>{{ control.scenarioVersion }}</p>
      <dl>
        <div><dt>运行 ID</dt><dd>{{ shortRunId(control.runId) }}</dd></div>
        <div><dt>启动时间</dt><dd>{{ formatDate(control.startedAt) }}</dd></div>
        <div><dt>约束模型</dt><dd>确定性规则（默认）</dd></div>
        <div><dt>执行模式</dt><dd>{{ control.engineMode || 'deterministic' }}</dd></div>
      </dl>
    </section>

    <section class="lifecycle-card run-state-card">
      <div class="lifecycle-card-head">
        <span>运行控制</span>
        <b :class="control.runStatus">{{ control.statusZh }}</b>
      </div>
      <dl>
        <div><dt>当前阶段</dt><dd>{{ control.currentPhaseZh || control.currentPhase || '--' }}</dd></div>
        <div><dt>进度</dt><dd>{{ Math.round(control.progress || 0) }}%</dd></div>
        <div><dt>结果 Run</dt><dd>{{ shortRunId(control.resultRunId) }}</dd></div>
      </dl>
      <div class="lifecycle-actions">
        <button type="button" class="primary-lifecycle" data-testid="war-room-run-action" :disabled="control.busy" @click="$emit('run')">▶ 运行</button>
        <button type="button" data-testid="war-room-pause-action" :disabled="!control.canPause" @click="$emit('pause')">Ⅱ 暂停</button>
        <button type="button" data-testid="war-room-cancel-action" :disabled="!control.canCancel" @click="$emit('cancel')">✕ 取消</button>
        <button type="button" data-testid="war-room-resume-action" :disabled="!control.canResume" @click="$emit('resume')">↻ 恢复</button>
        <button type="button" data-testid="war-room-retry-action" :disabled="!control.canRetry" @click="$emit('retry')">⟳ 重试</button>
      </div>
      <p class="lifecycle-disclaimer">{{ control.disclaimer }}</p>
    </section>

    <section class="lifecycle-card checkpoint-card">
      <div class="lifecycle-card-head">
        <span>检查点</span>
        <b :class="control.checkpointStatus">{{ control.checkpointStatus }}</b>
      </div>
      <dl>
        <div><dt>最近检查点</dt><dd>{{ formatDate(control.checkpointAt) }}</dd></div>
        <div><dt>快照 ID</dt><dd>{{ control.checkpointId }}</dd></div>
      </dl>
      <div class="lifecycle-secondary-actions">
        <button type="button" data-testid="war-room-clone-action" :disabled="!control.resultRunId && !control.runId" @click="$emit('clone')">克隆</button>
        <button type="button" data-testid="war-room-compare-action" :disabled="!control.compareReady" @click="$emit('compare')">对比</button>
        <button type="button" data-testid="war-room-replay-action" :disabled="!control.replayReady" @click="$emit('replay')">复盘</button>
        <button type="button" data-testid="war-room-delta-action" :class="{ active: showDeltaOverlay }" :disabled="!control.compareReady" @click="$emit('toggle-delta')">Delta</button>
      </div>
    </section>
  </aside>
</template>

<script setup>
defineProps({
  control: { type: Object, required: true },
  showDeltaOverlay: { type: Boolean, default: false }
})

defineEmits(['cancel', 'clone', 'compare', 'pause', 'replay', 'resume', 'retry', 'run', 'show-upcoming', 'toggle-delta'])

function shortRunId(runId) {
  const text = String(runId || '')
  return text ? text.replace(/^run_/, '#').replace(/^job_/, '#job-').slice(0, 16) : '--'
}

function formatDate(value) {
  if (!value || value === '--') return '--'
  return String(value).replace('T', ' ').slice(0, 16)
}
</script>
