<template>
  <div class="module-workbench sandbox-workbench" data-testid="war-room-sandbox-module">
    <section class="module-panel primary">
      <div class="module-panel-head">
        <div>
          <span>场景构建器</span>
          <h3>推演沙盘配置</h3>
        </div>
        <button class="secondary compact" type="button" @click="props.onClone?.()">
          <Copy :size="14" /> 克隆本次运行
        </button>
      </div>

      <div class="form-grid two">
        <label>
          预设场景
          <select v-model="props.scenarioDraft.scenario_key">
            <option v-for="scenario in props.presetScenarios" :key="scenario.key" :value="scenario.key">
              {{ props.scenarioLabel?.(scenario) || scenario.name || scenario.key }}
            </option>
          </select>
        </label>
        <label>
          推演天数
          <input v-model.number="props.scenarioDraft.duration_days" type="number" min="7" max="180" step="1" />
        </label>
        <label>
          冲击强度 {{ Math.round(props.scenarioDraft.intensity * 100) }}%
          <input v-model.number="props.scenarioDraft.intensity" type="range" min="0.1" max="1" step="0.05" />
        </label>
        <label>
          传播系数 {{ Math.round(props.scenarioDraft.propagation * 100) }}%
          <input v-model.number="props.scenarioDraft.propagation" type="range" min="0.1" max="1" step="0.05" />
        </label>
      </div>

      <div class="selector-block">
        <div class="module-panel-head slim">
          <div><span>国家 Agent</span><h3>目标国家</h3></div>
          <button type="button" class="text-action" @click="props.onSelectAllCountries?.()">全选 10 国</button>
        </div>
        <div class="token-grid">
          <button
            v-for="country in props.countryOptions"
            :key="country.code || country.country_code"
            type="button"
            :class="{ active: props.scenarioDraft.target_countries.includes(country.code || country.country_code) }"
            @click="props.onToggleDraftList?.('target_countries', country.code || country.country_code)"
          >
            {{ props.countryNameShort?.(country.code || country.country_code) || country.code || country.country_code }}
          </button>
        </div>
      </div>

      <div class="selector-block">
        <div class="module-panel-head slim">
          <div><span>供应链</span><h3>目标链路</h3></div>
          <button type="button" class="text-action" @click="props.scenarioDraft.target_chains = props.chainOptions.map(item => item.key).filter(Boolean)">全选链路</button>
        </div>
        <div class="token-grid">
          <button
            v-for="chain in props.chainOptions"
            :key="chain.key"
            type="button"
            :class="{ active: props.scenarioDraft.target_chains.includes(chain.key) }"
            @click="props.onToggleDraftList?.('target_chains', chain.key)"
          >
            {{ props.chainName?.(chain.key, chain.name) || chain.name || chain.key }}
          </button>
        </div>
      </div>

      <div class="selector-block">
        <div class="module-panel-head slim">
          <div><span>策略干预</span><h3>政策动作</h3></div>
          <button type="button" class="text-action" @click="props.onClearPolicyActions?.()">清空</button>
        </div>
        <div class="policy-grid">
          <button
            v-for="action in props.policyActions"
            :key="action.key"
            type="button"
            :class="{ active: props.scenarioDraft.policy_actions.includes(action.key) }"
            @click="props.onToggleDraftList?.('policy_actions', action.key)"
          >
            <strong>{{ action.label }}</strong>
            <span>{{ action.desc }}</span>
          </button>
        </div>
      </div>
    </section>

    <aside class="module-panel side">
      <div class="module-panel-head">
        <div><span>运行控制</span><h3>运行预览</h3></div>
      </div>
      <div class="run-preview-list">
        <article><span>场景</span><strong>{{ props.scenarioLabel?.({ key: props.scenarioDraft.scenario_key }) || props.scenarioDraft.scenario_key }}</strong></article>
        <article><span>国家</span><strong>{{ props.scenarioDraft.target_countries.length || props.countryOptions.length }}</strong><small>{{ props.scenarioDraft.target_countries.map(code => props.countryNameShort?.(code) || code).join('、') || '使用预设' }}</small></article>
        <article><span>供应链</span><strong>{{ props.scenarioDraft.target_chains.length || props.chainOptions.length }}</strong><small>{{ props.scenarioDraft.target_chains.map(item => props.chainName?.(item)).join('、') || '使用预设' }}</small></article>
        <article><span>政策动作</span><strong>{{ props.scenarioDraft.policy_actions.length }}</strong><small>{{ props.scenarioDraft.policy_actions.map(item => props.policyActionLabel?.(item) || item).join('、') || '基线运行' }}</small></article>
      </div>
      <button class="primary-action" type="button" :disabled="props.running" data-testid="sandbox-run-scenario" @click="props.onRun?.()">
        <Play :size="16" /> {{ props.running ? '推演中...' : '运行沙盘' }}
      </button>
      <div class="recent-run-list">
        <h4>最近运行</h4>
        <button
          v-for="runItem in props.runVersions.slice(0, 5)"
          :key="runItem.run_id"
          type="button"
          :class="{ active: props.selectedRunId === runItem.run_id }"
          @click="props.onLoadRun?.(runItem.run_id)"
        >
          <span>{{ props.shortRunId?.(runItem.run_id) || runItem.run_id }}</span>
          <small>{{ props.versionLabel?.(runItem) || runItem.completed_at || runItem.started_at || '' }}</small>
        </button>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { Copy, Play } from 'lucide-vue-next'

const props = defineProps({
  scenarioDraft: { type: Object, required: true },
  presetScenarios: { type: Array, default: () => [] },
  countryOptions: { type: Array, default: () => [] },
  chainOptions: { type: Array, default: () => [] },
  policyActions: { type: Array, default: () => [] },
  running: { type: Boolean, default: false },
  selectedRunId: { type: String, default: '' },
  runVersions: { type: Array, default: () => [] },
  shortRunId: { type: Function, default: null },
  versionLabel: { type: Function, default: null },
  countryNameShort: { type: Function, default: null },
  chainName: { type: Function, default: null },
  policyActionLabel: { type: Function, default: null },
  scenarioLabel: { type: Function, default: null },
  onClone: { type: Function, default: null },
  onSelectAllCountries: { type: Function, default: null },
  onToggleDraftList: { type: Function, default: null },
  onClearPolicyActions: { type: Function, default: null },
  onRun: { type: Function, default: null },
  onLoadRun: { type: Function, default: null }
})
</script>
