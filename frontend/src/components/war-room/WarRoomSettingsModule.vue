<template>
  <div class="section-card-grid settings-grid" data-testid="war-room-settings-module">
    <article data-testid="worldpulse-version-setting"><span>平台版本</span><strong>{{ WORLDPULSE_VERSION }}</strong><p>开发通道 · API contract v1</p></article>
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
        <option value="controlled_agent">受控 Agent Runtime</option>
        <option value="hybrid">受控混合推演（推荐）</option>
      </select>
      <p>{{ modeDescription }}</p>
    </article>
    <article><span>策略边界</span><strong>策略沙盘</strong><p>不是现实战争预测、投资建议或政策建议。</p></article>
    <article><span>显示设置</span><strong>{{ props.visibleMapLayers.length }} 个图层</strong><p>当前可见：{{ props.visibleMapLayers.map(layerLabel).join('、') }}</p></article>
    <article data-testid="agent-provider-setting"><span>Agent Provider（只读）</span><strong>{{ runtime.provider }}</strong><p>只允许 mock / siliconflow / deepseek；密钥永不回传前端。</p></article>
    <article data-testid="worker-status-setting"><span>本地 Worker 状态</span><strong>{{ workerStatus }}</strong><p>Attempt {{ props.lifecycleAudit?.run?.attempt_count || 0 }} / max {{ props.lifecycleAudit?.run?.max_attempts || 3 }}；当前阶段 {{ props.lifecycleAudit?.run?.current_phase || '尚无任务' }}。</p></article>
    <article><span>模型</span><strong>{{ runtime.model }}</strong><p>{{ runtime.fallbackReason }}</p></article>
    <article><span>调用预算</span><strong>{{ runtime.config.max_calls }} calls / {{ runtime.config.token_budget }} tokens</strong><p>最多 {{ runtime.config.max_turns }} 轮、{{ runtime.config.max_agents }} 个 Agent。</p></article>
    <article><span>超时与输出</span><strong>{{ runtime.config.timeout_seconds }}s</strong><p>输入 {{ runtime.config.max_input_chars }} 字符；输出 {{ runtime.config.max_output_chars }} 字符。</p></article>
    <article class="upcoming-card"><span>待上线</span><strong>3D 地球</strong><p>后续接入独立 3D 视图，本版不做伪交互。</p></article>
    <article class="upcoming-card"><span>待上线</span><strong>告警订阅</strong><p>通知中心和团队协作将作为后续能力。</p></article>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { WORLDPULSE_VERSION } from '../../version'

const props = defineProps({
  visibleMapLayers: { type: Array, default: () => [] },
  layerLabel: { type: Function, default: null },
  engineMode: { type: String, default: 'deterministic' },
  onEngineModeChange: { type: Function, default: null },
  runtimeAudit: { type: Object, default: null }
  ,lifecycleAudit: { type: Object, default: null }
})

const runtime = computed(() => ({
  provider: props.runtimeAudit?.provider || 'mock（默认）',
  model: props.runtimeAudit?.model || 'mock-deterministic-v1',
  fallbackReason: props.runtimeAudit?.fallback_reason || '尚无运行记录；显示安全默认值。',
  config: {
    max_calls: props.runtimeAudit?.runtime_config?.max_calls ?? 8,
    token_budget: props.runtimeAudit?.runtime_config?.token_budget ?? 12000,
    max_turns: props.runtimeAudit?.runtime_config?.max_turns ?? 1,
    max_agents: props.runtimeAudit?.runtime_config?.max_agents ?? 4,
    timeout_seconds: props.runtimeAudit?.runtime_config?.timeout_seconds ?? 30,
    max_input_chars: props.runtimeAudit?.runtime_config?.max_input_chars ?? 16000,
    max_output_chars: props.runtimeAudit?.runtime_config?.max_output_chars ?? 6000,
  }
}))

const engineModeLabel = computed(() => ({
  deterministic: '纯确定性模式',
  mock_agent: 'Mock Agent 合同模式',
  controlled_agent: '受控 Agent Runtime',
  hybrid: '受控混合推演',
}[props.engineMode] || props.engineMode))
const modeDescription = computed(() => ({
  deterministic: '仅运行确定性引擎和只读一致性审计。',
  mock_agent: '生成可重复的结构化提案并执行一致性准入；不会修改确定性数值。',
  controlled_agent: '使用 provider allowlist、调用预算、超时和审计；默认安全降级到 Mock Provider。',
  hybrid: 'Agent 只提出动作，经一致性准入和固定适配后，由确定性引擎重算并生成离线 Replay 证据链。',
}[props.engineMode] || '未知运行模式。'))
const workerStatus = computed(() => {
  const status = props.lifecycleAudit?.run?.status
  return status ? `${status} · ${props.lifecycleAudit.run.current_attempt_id ? '有 active attempt' : '待领取'}` : '待机（本地）'
})
</script>
