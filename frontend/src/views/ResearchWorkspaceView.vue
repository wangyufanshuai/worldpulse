<template>
  <main class="workspace" v-if="detail">
    <section class="workspace-head">
      <div>
        <p class="eyebrow">Research Workspace</p>
        <h1>{{ detail.project.title }}</h1>
        <p>{{ detail.project.question }}</p>
      </div>
      <div class="head-actions">
        <span :class="['status-badge', detail.project.status]">{{ statusText }}</span>
        <label class="mode-switch">
          <span>运行模式</span>
          <select v-model="runMode">
            <option value="fast">快速研究</option>
            <option value="full">完整真实数据</option>
          </select>
        </label>
        <button class="primary" :disabled="running" @click="run">
          {{ running ? '研究运行中...' : '运行研究' }}
        </button>
      </div>
    </section>

    <section class="workflow-rail">
      <article v-for="step in steps" :key="step.key" :class="{ done: step.done }">
        <span>{{ step.index }}</span>
        <strong>{{ step.title }}</strong>
        <p>{{ step.desc }}</p>
      </article>
    </section>

    <section class="split-lab">
      <div class="graph-panel">
        <div class="section-title">
          <div>
            <p class="eyebrow">Causal Graph</p>
            <h2>事件到市场的推理路径</h2>
          </div>
          <span v-if="detail.graph" class="quality-pill">置信度 {{ detail.graph.confidence.toFixed(1) }}</span>
        </div>
        <div ref="graphEl" class="graph-canvas"></div>
        <div v-if="selected" class="detail-drawer">
          <button @click="selected = null">关闭</button>
          <p class="eyebrow">{{ selected.kind || selected.relation || 'Evidence' }}</p>
          <h3>{{ selected.label || `${selected.source} -> ${selected.target}` }}</h3>
          <p>{{ selected.explanation || selected.id }}</p>
          <ul v-if="selected.evidence">
            <li v-for="item in selected.evidence" :key="item">{{ item }}</li>
          </ul>
          <div v-if="selected.backtest" class="edge-meta">
            <span>样本 {{ selected.backtest.sample_count }}</span>
            <span>一致性 {{ Math.round(selected.backtest.hit_rate * 100) }}%</span>
            <span>最大误差 {{ selected.backtest.max_error }}</span>
          </div>
        </div>
      </div>

      <aside class="insight-panel">
        <div class="section-title">
          <div>
            <p class="eyebrow">Run Timeline</p>
            <h2>研究过程</h2>
          </div>
          <span class="quality-pill">{{ currentModeText }}</span>
        </div>
        <p class="summary-box">{{ detail.latest_run?.summary || '尚未运行。点击“运行研究”生成数据快照、因果图谱和报告。' }}</p>
        <div class="timeline-list" v-if="workflowEvents.length">
          <article v-for="event in workflowEvents" :key="`${event.key}-${event.timestamp}`">
            <span>{{ event.status }}</span>
            <strong>{{ event.title }}</strong>
            <p>{{ event.detail }}</p>
            <small>{{ event.timestamp }}</small>
          </article>
        </div>
        <div class="metric-grid" v-if="detail.graph">
          <div><span>节点</span><strong>{{ detail.graph.nodes.length }}</strong></div>
          <div><span>因果边</span><strong>{{ detail.graph.edges.length }}</strong></div>
          <div><span>证据源</span><strong>{{ detail.graph.evidence_sources.length }}</strong></div>
        </div>
        <div class="source-list" v-if="detail.graph">
          <strong>证据来源</strong>
          <span v-for="source in detail.graph.evidence_sources" :key="source">{{ source }}</span>
        </div>
      </aside>
    </section>

    <section class="report-chat">
      <article class="report-panel">
        <div class="section-title">
          <div>
            <p class="eyebrow">AI Report</p>
            <h2>{{ detail.report?.title || '等待报告' }}</h2>
          </div>
          <span v-if="detail.report" class="quality-pill">{{ detail.report.mode }}</span>
        </div>
        <template v-if="detail.report">
          <p class="report-summary">{{ detail.report.summary }}</p>
          <h3>核心结论</h3>
          <ul><li v-for="item in detail.report.key_findings" :key="item">{{ item }}</li></ul>
          <h3>证据链</h3>
          <div class="evidence-list">
            <div v-for="item in detail.report.evidence" :key="item.title">
              <strong>{{ item.title }}</strong>
              <span>{{ item.source }} · {{ item.value }}</span>
              <p>{{ item.interpretation }}</p>
            </div>
          </div>
          <h3>不确定性</h3>
          <ul><li v-for="item in detail.report.uncertainties" :key="item">{{ item }}</li></ul>
          <a class="download" :href="markdownUrl" download="worldpulse_report.md">导出 Markdown 报告</a>
        </template>
        <div v-else class="empty">运行研究后生成报告。</div>
      </article>

      <aside class="chat-panel">
        <div class="section-title">
          <div>
            <p class="eyebrow">Interaction</p>
            <h2>继续追问</h2>
          </div>
        </div>
        <div class="quick-prompts">
          <button v-for="prompt in prompts" :key="prompt" @click="message = prompt">{{ prompt }}</button>
        </div>
        <div class="chat-log">
          <div v-for="msg in detail.chat_messages" :key="msg.message_id" :class="['chat-msg', msg.role]">
            <span>{{ msg.role === 'user' ? '你' : 'WorldPulse' }}</span>
            <p>{{ msg.content }}</p>
          </div>
        </div>
        <div class="chat-input">
          <textarea v-model="message" rows="3" placeholder="追问证据、反例、情景或结论边界"></textarea>
          <button :disabled="chatting || !message" @click="send">{{ chatting ? '分析中...' : '发送' }}</button>
        </div>
      </aside>
    </section>
  </main>
  <main v-else class="loading-page">加载研究工作台...</main>
</template>

<script setup>
import * as d3 from 'd3'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { chatWithProject, getProject, runProject } from '../api'

const props = defineProps({ projectId: String })
const detail = ref(null)
const graphEl = ref(null)
const selected = ref(null)
const running = ref(false)
const chatting = ref(false)
const message = ref('')
const runMode = ref('fast')
const prompts = ['证据链最弱的一环是什么？', '有没有历史反例？', '如果能源冲击减弱，结论怎么变？', '哪些指标最值得未来7天观察？']

const workflowEvents = computed(() => detail.value?.latest_run?.data_snapshot?.workflow_events || [])
const currentModeText = computed(() => {
  const mode = detail.value?.latest_run?.data_snapshot?.run_mode || runMode.value
  return mode === 'full' ? '完整真实数据' : '快速研究'
})
const statusText = computed(() => ({ created: '已创建', completed: '已完成' }[detail.value?.project?.status] || detail.value?.project?.status || '未知'))
const steps = computed(() => [
  { index: '01', key: 'project', title: '研究任务', desc: '问题、地区和事件范围已锁定', done: !!detail.value?.project },
  { index: '02', key: 'events', title: '事件识别', desc: '聚合新闻、冲突和宏观信号', done: !!detail.value?.latest_run?.event_snapshot?.length },
  { index: '03', key: 'graph', title: '因果图谱', desc: '生成可解释节点和边', done: !!detail.value?.graph },
  { index: '04', key: 'backtest', title: '历史验证', desc: '相似事件窗口回测', done: !!detail.value?.latest_run?.backtest_snapshot?.sample_count },
  { index: '05', key: 'report', title: '报告追问', desc: '生成报告并继续对话', done: !!detail.value?.report }
])

const markdownUrl = computed(() => {
  const markdown = detail.value?.report?.markdown || ''
  return URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
})

async function load() {
  detail.value = await getProject(props.projectId)
  runMode.value = detail.value?.latest_run?.data_snapshot?.run_mode || runMode.value
  await nextTick()
  renderGraph()
}

async function run() {
  running.value = true
  try {
    detail.value = await runProject(props.projectId, runMode.value)
    await nextTick()
    renderGraph()
  } finally {
    running.value = false
  }
}

async function send() {
  chatting.value = true
  try {
    await chatWithProject(props.projectId, message.value)
    message.value = ''
    await load()
  } finally {
    chatting.value = false
  }
}

function renderGraph() {
  const graph = detail.value?.graph
  const el = graphEl.value
  if (!graph || !el) return
  el.innerHTML = ''
  const width = el.clientWidth || 760
  const height = 540
  const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${width} ${height}`)
  const nodes = graph.nodes.map(node => ({ ...node }))
  const edges = graph.edges.map(edge => ({ ...edge }))
  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(120).strength(0.55))
    .force('charge', d3.forceManyBody().strength(-520))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(52))

  const link = svg.append('g').selectAll('line').data(edges).enter().append('line')
    .attr('class', 'edge-line')
    .attr('stroke-width', d => 1 + d.weight * 2)
    .on('click', (_, d) => { selected.value = d })

  const node = svg.append('g').selectAll('g').data(nodes).enter().append('g')
    .attr('class', d => `node node-${d.kind}`)
    .call(d3.drag()
      .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null }))
    .on('click', (_, d) => { selected.value = d })

  node.append('circle').attr('r', d => 18 + d.score / 8)
  node.append('text').text(d => d.label).attr('dy', 44).attr('text-anchor', 'middle')
  node.append('title').text(d => `${d.label} · ${d.kind} · ${d.score}`)

  simulation.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })
}

watch(() => detail.value?.graph?.graph_id, () => nextTick(renderGraph))
onMounted(load)
</script>
