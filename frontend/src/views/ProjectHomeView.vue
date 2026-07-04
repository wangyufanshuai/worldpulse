<template>
  <main class="home-grid">
    <section class="home-intro">
      <div>
        <div class="section-kicker"><Radar :size="16" /> 指挥中心</div>
        <h1>把全球局势问题变成可复盘的研判工作流</h1>
        <p>
          创建研究任务或 War Room 策略沙盘后，WorldPulse 会生成事件快照、因果链、模拟结果、风险热力图和可追问报告。
        </p>
      </div>
      <div class="risk-strip" v-if="risk">
        <article>
          <span>全局风险</span>
          <strong>{{ risk.latest.score.toFixed(1) }}</strong>
        </article>
        <article>
          <span>趋势</span>
          <strong>{{ risk.latest.display_trend }}</strong>
        </article>
        <article>
          <span>30 天概率</span>
          <strong>{{ risk.latest.forecast_30d.toFixed(0) }}%</strong>
        </article>
      </div>
      <div class="risk-strip" v-else>
        <article><span>全局风险</span><strong>--</strong></article>
        <article><span>状态</span><strong>待同步</strong></article>
        <article><span>数据</span><strong>稍后刷新</strong></article>
      </div>
    </section>

    <section class="create-panel">
      <div class="section-title">
        <div>
          <div class="section-kicker"><PlusCircle :size="16" /> 新建项目</div>
          <h2>创建工作流</h2>
        </div>
      </div>

      <div class="mode-tabs" role="tablist" aria-label="项目模式">
        <button type="button" :class="{ active: form.mode === 'research' }" @click="form.mode = 'research'">
          <FileSearch :size="16" /> 新建研究
        </button>
        <button type="button" :class="{ active: form.mode === 'war_room' }" @click="form.mode = 'war_room'">
          <ShieldAlert :size="16" /> War Room 沙盘
        </button>
      </div>

      <label>项目标题<input v-model="form.title" :placeholder="titlePlaceholder" /></label>
      <label>研判问题<textarea v-model="form.question" rows="4" :placeholder="questionPlaceholder"></textarea></label>

      <template v-if="form.mode === 'research'">
        <div class="form-row">
          <label>地区范围<input v-model="form.region" /></label>
          <label>事件窗口<select v-model.number="form.event_window_days"><option :value="7">7 天</option><option :value="30">30 天</option><option :value="90">90 天</option></select></label>
        </div>
        <div class="chip-list">
          <button v-for="type in eventTypes" :key="type.key" :class="{ active: form.event_types.includes(type.key) }" @click="toggleEvent(type.key)" type="button">{{ type.name }}</button>
        </div>
      </template>

      <template v-else>
        <div class="scenario-card">
          <label>
            预设场景
            <select v-model="scenario.scenario_key" @change="applyScenarioPreset">
              <option v-for="item in warRoomScenarios" :key="item.key" :value="item.key">{{ scenarioName(item.key, item.name) }}</option>
            </select>
          </label>
          <p>{{ selectedScenario?.description || '正在加载 War Room 场景。' }}</p>
          <span>策略沙盘 / Not a prediction。不是现实战争预测、投资建议或政策建议。</span>
        </div>
        <div class="slider-grid">
          <label>推演天数 <b>{{ scenario.duration_days }}</b><input v-model.number="scenario.duration_days" type="range" min="7" max="90" step="1" /></label>
          <label>冲击强度 <b>{{ scenario.intensity.toFixed(2) }}</b><input v-model.number="scenario.intensity" type="range" min="0.05" max="1" step="0.05" /></label>
          <label>传播系数 <b>{{ scenario.propagation.toFixed(2) }}</b><input v-model.number="scenario.propagation" type="range" min="0.05" max="0.9" step="0.05" /></label>
        </div>
        <div class="war-room-preview" v-if="presets">
          <article><span>国家 Agent</span><strong>{{ presets.countries.length }}</strong></article>
          <article><span>供应链</span><strong>{{ presets.supply_chains.length }}</strong></article>
          <article><span>冲突事件</span><strong>{{ presets.conflict_events.length }}</strong></article>
        </div>
      </template>

      <button class="primary" :disabled="creating || !form.title || !form.question" @click="submit">
        <Rocket :size="16" /> {{ creating ? '创建中...' : '创建并进入工作台' }}
      </button>
      <p v-if="error" class="error-text">{{ error }}</p>
    </section>

    <section class="project-panel">
      <div class="section-title">
        <div>
          <div class="section-kicker"><Clock3 :size="16" /> 最近项目</div>
          <h2>工作流列表</h2>
        </div>
        <span class="quality-pill">Studio workflow</span>
      </div>
      <div v-if="projects.length" class="project-list">
        <RouterLink v-for="project in projects" :key="project.project_id" :to="`/projects/${project.project_id}`" class="project-card">
          <span>{{ project.mode === 'war_room' ? 'War Room' : statusText(project.status) }}</span>
          <strong>{{ project.title }}</strong>
          <p>{{ project.question }}</p>
          <small>{{ project.region }} · {{ project.event_window_days }} 天 · {{ project.updated_at }}</small>
        </RouterLink>
      </div>
      <div v-else class="empty">还没有研究项目。先创建一个任务。</div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Clock3, FileSearch, PlusCircle, Radar, Rocket, ShieldAlert } from 'lucide-vue-next'
import { createProject, getRiskOverview, getWarRoomPresets, listProjects } from '../api'

const router = useRouter()
const projects = ref([])
const risk = ref(null)
const presets = ref(null)
const creating = ref(false)
const error = ref('')

const eventTypes = [
  { key: 'conflict', name: '冲突' },
  { key: 'sanctions', name: '制裁' },
  { key: 'energy', name: '能源' },
  { key: 'food', name: '粮食' },
  { key: 'rates', name: '利率' },
  { key: 'trade', name: '贸易' },
  { key: 'climate', name: '气候' }
]

const form = reactive({
  title: '',
  question: '',
  region: 'global',
  event_window_days: 30,
  event_types: eventTypes.map(item => item.key),
  asset_scope: ['sp500', 'nasdaq', 'oil', 'gold', 'dollar', 'vix'],
  mode: 'research'
})

const scenario = reactive({
  scenario_key: 'strait_blockade_30d',
  duration_days: 30,
  intensity: 0.65,
  propagation: 0.42
})

const scenarioNames = {
  strait_blockade_30d: '海峡封锁 30 天',
  energy_export_cut: '能源出口中断',
  food_shortfall: '粮食减产与出口限制'
}

const warRoomScenarios = computed(() => presets.value?.scenarios || [])
const selectedScenario = computed(() => warRoomScenarios.value.find(item => item.key === scenario.scenario_key))
const titlePlaceholder = computed(() => form.mode === 'war_room' ? '例如：海峡封锁 30 天 War Room' : '例如：能源冲击对纳指和亚洲经济体的影响')
const questionPlaceholder = computed(() => form.mode === 'war_room' ? '例如：某海峡封锁 30 天会怎样？哪些国家、供应链和金融压力最先承压？' : '写清楚你想验证的因果链、地区、资产或风险边界')

function scenarioName(key, fallback) {
  return scenarioNames[key] || fallback
}

function statusText(status) {
  return { created: '已创建', completed: '已完成' }[status] || status
}

function toggleEvent(key) {
  form.event_types = form.event_types.includes(key) ? form.event_types.filter(item => item !== key) : [...form.event_types, key]
}

function applyScenarioPreset() {
  const preset = selectedScenario.value
  if (!preset) return
  scenario.duration_days = preset.duration_days
  scenario.intensity = preset.intensity
  scenario.propagation = preset.propagation
}

async function submit() {
  creating.value = true
  error.value = ''
  try {
    const payload = {
      ...form,
      scenario_config: form.mode === 'war_room' ? { ...scenario } : {},
      event_types: form.mode === 'war_room' ? ['conflict', 'energy', 'food', 'trade', 'sanctions'] : form.event_types,
      asset_scope: form.mode === 'war_room' ? ['energy', 'food', 'chips', 'shipping', 'settlement'] : form.asset_scope
    }
    const project = await createProject(payload)
    router.push(`/projects/${project.project_id}`)
  } catch (err) {
    error.value = err?.response?.data?.detail || err.message
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  try {
    projects.value = await listProjects()
  } catch (err) {
    error.value = err?.response?.data?.detail || err.message
  }
  try {
    risk.value = await getRiskOverview()
  } catch {
    risk.value = null
  }
  try {
    presets.value = await getWarRoomPresets()
    applyScenarioPreset()
  } catch {
    presets.value = null
  }
})
</script>
