<template>
  <main class="home-grid">
    <section class="hero-panel">
      <p class="eyebrow">Research Workflow</p>
      <h1>把问题变成可追溯的局势研究任务</h1>
      <p class="hero-copy">
        创建研究项目后，WorldPulse 会自动整理风险、事件、因果链、回测和模拟结果，生成可继续追问的结构化报告。
      </p>
      <div class="risk-strip" v-if="risk">
        <div>
          <span>全球风险</span>
          <strong>{{ risk.latest.score.toFixed(1) }}</strong>
        </div>
        <div>
          <span>趋势</span>
          <strong>{{ risk.latest.display_trend }}</strong>
        </div>
        <div>
          <span>30天概率</span>
          <strong>{{ risk.latest.forecast_30d.toFixed(0) }}%</strong>
        </div>
      </div>
      <div class="risk-strip" v-else>
        <div>
          <span>全球风险</span>
          <strong>--</strong>
        </div>
        <div>
          <span>状态</span>
          <strong>同步中</strong>
        </div>
        <div>
          <span>说明</span>
          <strong>稍后刷新</strong>
        </div>
      </div>
    </section>

    <section class="create-panel">
      <div class="section-title">
        <div>
          <p class="eyebrow">New Project</p>
          <h2>新建研究</h2>
        </div>
      </div>
      <label>标题<input v-model="form.title" placeholder="例如：能源冲击对纳指和亚洲经济体的影响" /></label>
      <label>研究问题<textarea v-model="form.question" rows="4" placeholder="写清楚你想验证的因果链、地区、资产或风险边界"></textarea></label>
      <div class="form-row">
        <label>地区<input v-model="form.region" /></label>
        <label>窗口<select v-model.number="form.event_window_days"><option :value="7">7天</option><option :value="30">30天</option><option :value="90">90天</option></select></label>
      </div>
      <div class="chip-list">
        <button v-for="type in eventTypes" :key="type.key" :class="{ active: form.event_types.includes(type.key) }" @click="toggleEvent(type.key)" type="button">{{ type.name }}</button>
      </div>
      <button class="primary" :disabled="creating || !form.title || !form.question" @click="submit">
        {{ creating ? '创建中...' : '创建并进入工作台' }}
      </button>
      <p v-if="error" class="error-text">{{ error }}</p>
    </section>

    <section class="project-panel">
      <div class="section-title">
        <div>
          <p class="eyebrow">Recent Research</p>
          <h2>最近项目</h2>
        </div>
        <span class="quality-pill">快速研究默认开启</span>
      </div>
      <div v-if="projects.length" class="project-list">
        <RouterLink v-for="project in projects" :key="project.project_id" :to="`/projects/${project.project_id}`" class="project-card">
          <span>{{ statusText(project.status) }}</span>
          <strong>{{ project.title }}</strong>
          <p>{{ project.question }}</p>
          <small>{{ project.region }} · {{ project.event_window_days }}天 · {{ project.updated_at }}</small>
        </RouterLink>
      </div>
      <div v-else class="empty">还没有研究项目。先创建一个任务。</div>
    </section>
  </main>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createProject, getRiskOverview, listProjects } from '../api'

const router = useRouter()
const projects = ref([])
const risk = ref(null)
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
  asset_scope: ['sp500', 'nasdaq', 'oil', 'gold', 'dollar', 'vix']
})

function statusText(status) {
  return { created: '已创建', completed: '已完成' }[status] || status
}

function toggleEvent(key) {
  form.event_types = form.event_types.includes(key) ? form.event_types.filter(item => item !== key) : [...form.event_types, key]
}

async function submit() {
  creating.value = true
  error.value = ''
  try {
    const project = await createProject(form)
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
})
</script>
