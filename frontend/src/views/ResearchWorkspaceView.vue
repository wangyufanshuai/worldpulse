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
        <label v-if="runVersions.length" class="mode-switch">
          <span>研究版本</span>
          <select v-model="selectedRunId" @change="selectRun">
            <option v-for="run in runVersions" :key="run.run_id" :value="run.run_id">
              {{ versionLabel(run) }}
            </option>
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
          <div class="graph-actions" v-if="detail.graph">
            <span class="quality-pill">置信度 {{ graphConfidence.toFixed(1) }}</span>
            <button @click="toggleGraphEdit">{{ graphEditMode ? '退出编辑' : '编辑图谱' }}</button>
            <label v-if="graphEditMode" class="inline-edit">置信度<input v-model.number="editableGraph.confidence" type="number" min="0" max="100" /></label>
            <button v-if="graphEditMode" @click="addGraphNode">添加节点</button>
            <button v-if="graphEditMode" @click="addGraphEdge">添加边</button>
            <button v-if="graphEditMode" :disabled="savingGraph" @click="saveGraph">{{ savingGraph ? '保存中...' : '保存校正' }}</button>
          </div>
        </div>
        <div ref="graphEl" class="graph-canvas"></div>
        <div v-if="selected" class="detail-drawer">
          <button @click="selected = null">关闭</button>
          <p class="eyebrow">{{ selected.kind || selected.relation || 'Evidence' }}</p>
          <h3>{{ selected.label || `${selected.source} -> ${selected.target}` }}</h3>
          <template v-if="graphEditMode">
            <label>标签/关系<input v-model="selectedEdit.label" /></label>
            <label>类型/说明<input v-model="selectedEdit.kind" /></label>
            <label>分数/权重<input v-model.number="selectedEdit.score" type="number" min="0" max="100" /></label>
            <label>解释<textarea v-model="selectedEdit.explanation" rows="3"></textarea></label>
            <button class="drawer-action" @click="applySelectedEdit">应用到图谱</button>
          </template>
          <p v-else>{{ selected.explanation || selected.id }}</p>
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
        <div class="trace-panel" v-if="detail.latest_run">
          <strong>证据追溯</strong>
          <div><span>运行编号</span><code>{{ detail.latest_run.run_id }}</code></div>
          <div><span>运行时间</span><code>{{ detail.latest_run.completed_at || detail.latest_run.started_at }}</code></div>
          <div><span>事件样本</span><code>{{ detail.latest_run.event_snapshot?.length || 0 }}</code></div>
          <div><span>风险读数</span><code>{{ riskScoreText }}</code></div>
          <div><span>数据源</span><code>{{ sourceCount }} 个</code></div>
        </div>
        <div class="trace-panel" v-if="runVersions.length > 1">
          <strong>历史运行对比</strong>
          <label class="compact-field">
            <span>对比基准</span>
            <select v-model="compareBaseRunId" @change="loadRunDiff">
              <option v-for="run in compareCandidates" :key="run.run_id" :value="run.run_id">{{ versionLabel(run) }}</option>
            </select>
          </label>
          <template v-if="runDiff">
            <p class="diff-summary">{{ runDiff.summary }}</p>
            <div><span>风险变化</span><code>{{ signed(runDiff.risk_delta) }}</code></div>
            <div><span>置信度变化</span><code>{{ signed(runDiff.confidence_delta) }}</code></div>
            <div><span>事件变化</span><code>{{ signed(runDiff.event_count_delta) }}</code></div>
            <div><span>证据源变化</span><code>{{ signed(runDiff.evidence_source_delta) }}</code></div>
          </template>
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
          <ul class="finding-list">
            <li v-for="item in detail.report.key_findings" :key="item">
              <button @click="openEvidenceDrawer(item)">{{ item }}</button>
            </li>
          </ul>
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
    <aside v-if="evidenceDrawer" class="evidence-drawer">
      <button @click="evidenceDrawer = null">关闭</button>
      <p class="eyebrow">Evidence Drawer</p>
      <h2>{{ evidenceDrawer.finding }}</h2>
      <p>{{ evidenceDrawer.summary }}</p>
      <h3>直接证据</h3>
      <div class="evidence-list">
        <div v-for="item in evidenceDrawer.evidence" :key="`${item.title}-${item.source}`">
          <strong>{{ item.title }}</strong>
          <span>{{ item.source }} · {{ item.value }}</span>
          <p>{{ item.interpretation }}</p>
        </div>
      </div>
      <h3>相关因果边</h3>
      <ul>
        <li v-for="edge in evidenceDrawer.edges" :key="`${edge.source}-${edge.target}-${edge.relation}`">
          {{ edge.source }} → {{ edge.target }} · {{ edge.relation }} · 置信度 {{ Math.round(edge.confidence || 0) }}
        </li>
      </ul>
      <h3>结论边界</h3>
      <ul><li v-for="item in evidenceDrawer.uncertainties" :key="item">{{ item }}</li></ul>
    </aside>
  </main>
  <main v-else class="loading-page">加载研究工作台...</main>
</template>

<script setup>
import * as d3 from 'd3'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { chatWithProject, compareProjectRuns, getProject, getProjectRun, runProject, updateProjectGraph } from '../api'

const props = defineProps({ projectId: String })
const detail = ref(null)
const graphEl = ref(null)
const selected = ref(null)
const running = ref(false)
const chatting = ref(false)
const savingGraph = ref(false)
const message = ref('')
const runMode = ref('fast')
const selectedRunId = ref('')
const compareBaseRunId = ref('')
const runDiff = ref(null)
const graphEditMode = ref(false)
const editableGraph = ref(null)
const selectedType = ref('')
const selectedEdit = ref({ label: '', kind: '', score: 50, explanation: '' })
const evidenceDrawer = ref(null)
const prompts = ['证据链最弱的一环是什么？', '有没有历史反例？', '如果能源冲击减弱，结论怎么变？', '哪些指标最值得未来7天观察？']

const runVersions = computed(() => detail.value?.runs || [])
const compareCandidates = computed(() => runVersions.value.filter(run => run.run_id !== selectedRunId.value))
const workflowEvents = computed(() => detail.value?.latest_run?.data_snapshot?.workflow_events || [])
const sourceCount = computed(() => detail.value?.latest_run?.data_snapshot?.sources?.length || detail.value?.graph?.evidence_sources?.length || 0)
const graphConfidence = computed(() => editableGraph.value?.confidence ?? detail.value?.graph?.confidence ?? 0)
const riskScoreText = computed(() => {
  const score = detail.value?.latest_run?.risk_snapshot?.latest?.score
  return typeof score === 'number' ? `${score.toFixed(1)}/100` : '--'
})
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

async function load(runId = selectedRunId.value) {
  detail.value = runId ? await getProjectRun(props.projectId, runId) : await getProject(props.projectId)
  selectedRunId.value = detail.value?.latest_run?.run_id || ''
  runMode.value = detail.value?.latest_run?.data_snapshot?.run_mode || runMode.value
  prepareGraphDraft()
  prepareCompareBase()
  await loadRunDiff()
  await nextTick()
  renderGraph()
}

async function run() {
  running.value = true
  try {
    detail.value = await runProject(props.projectId, runMode.value)
    selectedRunId.value = detail.value?.latest_run?.run_id || ''
    prepareGraphDraft()
    prepareCompareBase()
    await loadRunDiff()
    await nextTick()
    renderGraph()
  } finally {
    running.value = false
  }
}

async function selectRun() {
  selected.value = null
  evidenceDrawer.value = null
  await load(selectedRunId.value)
}

async function send() {
  chatting.value = true
  try {
    await chatWithProject(props.projectId, message.value)
    message.value = ''
    await load(selectedRunId.value)
  } finally {
    chatting.value = false
  }
}

function versionLabel(run) {
  const mode = run.data_snapshot?.run_mode === 'full' ? '完整' : '快速'
  const time = run.completed_at || run.started_at
  return `${mode} · ${time}`
}

function prepareGraphDraft() {
  editableGraph.value = detail.value?.graph ? JSON.parse(JSON.stringify(detail.value.graph)) : null
}

function prepareCompareBase() {
  if (!compareBaseRunId.value || compareBaseRunId.value === selectedRunId.value) {
    compareBaseRunId.value = compareCandidates.value[0]?.run_id || ''
  }
}

async function loadRunDiff() {
  if (!selectedRunId.value || !compareBaseRunId.value || selectedRunId.value === compareBaseRunId.value) {
    runDiff.value = null
    return
  }
  runDiff.value = await compareProjectRuns(props.projectId, compareBaseRunId.value, selectedRunId.value)
}

function signed(value) {
  if (value === null || value === undefined) return '--'
  const num = Number(value)
  return `${num >= 0 ? '+' : ''}${Number.isInteger(num) ? num : num.toFixed(1)}`
}

function toggleGraphEdit() {
  graphEditMode.value = !graphEditMode.value
  if (graphEditMode.value) prepareGraphDraft()
}

function selectGraphItem(item, type) {
  selected.value = item
  selectedType.value = type
  selectedEdit.value = {
    label: item.label || item.relation || '',
    kind: item.kind || item.explanation || '',
    score: item.score ?? Math.round((item.weight || 0.5) * 100),
    explanation: item.explanation || ''
  }
}

function applySelectedEdit() {
  if (!editableGraph.value || !selected.value) return
  if (selectedType.value === 'node') {
    const node = editableGraph.value.nodes.find(item => item.id === selected.value.id)
    if (!node) return
    node.label = selectedEdit.value.label || node.label
    node.kind = selectedEdit.value.kind || node.kind
    node.score = clamp(Number(selectedEdit.value.score), 0, 100)
  } else {
    const edge = editableGraph.value.edges.find(item => item.source === selected.value.source && item.target === selected.value.target)
    if (!edge) return
    edge.relation = selectedEdit.value.label || edge.relation
    edge.explanation = selectedEdit.value.explanation || selectedEdit.value.kind || edge.explanation
    edge.weight = clamp(Number(selectedEdit.value.score) / 100, 0, 1)
    edge.confidence = clamp(Number(selectedEdit.value.score), 0, 100)
  }
  renderGraph()
}

function addGraphNode() {
  if (!editableGraph.value) return
  const id = `analyst_${Date.now()}`
  editableGraph.value.nodes.push({ id, label: '人工节点', kind: 'analyst', score: 50 })
  renderGraph()
}

function addGraphEdge() {
  if (!editableGraph.value || editableGraph.value.nodes.length < 2) return
  const [source, target] = editableGraph.value.nodes.slice(-2)
  editableGraph.value.edges.push({
    source: source.id,
    target: target.id,
    relation: '人工假设',
    weight: 0.5,
    confidence: 50,
    explanation: '由研究者手动加入，需通过后续数据和回测验证。'
  })
  renderGraph()
}

async function saveGraph() {
  if (!editableGraph.value || !detail.value?.latest_run) return
  savingGraph.value = true
  try {
    detail.value = await updateProjectGraph(props.projectId, {
      run_id: detail.value.latest_run.run_id,
      nodes: editableGraph.value.nodes,
      edges: editableGraph.value.edges,
      confidence: editableGraph.value.confidence,
      evidence_sources: editableGraph.value.evidence_sources,
      note: '研究者在工作台中校正因果图谱。'
    })
    selectedRunId.value = detail.value?.latest_run?.run_id || selectedRunId.value
    prepareGraphDraft()
    await loadRunDiff()
    graphEditMode.value = false
    await nextTick()
    renderGraph()
  } finally {
    savingGraph.value = false
  }
}

function openEvidenceDrawer(finding) {
  const evidence = detail.value?.report?.evidence || []
  const edges = detail.value?.graph?.edges || []
  const uncertainties = detail.value?.report?.uncertainties || []
  evidenceDrawer.value = {
    finding,
    summary: '该结论由报告证据、因果边和不确定性共同支撑。若证据不足，应降低置信度或运行完整真实数据模式复核。',
    evidence,
    edges: edges.slice(0, 5),
    uncertainties
  }
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, value))
}

function renderGraph() {
  const graph = graphEditMode.value ? editableGraph.value : detail.value?.graph
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
    .on('click', (_, d) => {
      selectGraphItem({ ...d, source: d.source.id || d.source, target: d.target.id || d.target }, 'edge')
    })

  const node = svg.append('g').selectAll('g').data(nodes).enter().append('g')
    .attr('class', d => `node node-${d.kind}`)
    .call(d3.drag()
      .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null }))
    .on('click', (_, d) => { selectGraphItem(d, 'node') })

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
