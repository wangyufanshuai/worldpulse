<template>
  <main v-if="detail" :class="['workspace', { 'war-room-page': isWarRoom }]">
    <template v-if="isWarRoom">
      <section class="war-room-command-shell">
        <WarRoomTopNav
          :active-section="activeSection"
          :section-path="sectionPath"
          :top-sections="topSections"
          @open-command-search="commandSearchOpen = true"
          @show-upcoming="showUpcoming"
        />

        <WarRoomLifecycleRail :stages="lifecycleStages" />

        <WarRoomOverviewConsole
          v-if="activeSection === 'overview'"
          :active-agents="lifecycleAgentStatus"
          :active-replay-day="activeReplayDay"
          :causal-edges="mapCausalEdges"
          :control="lifecycleControl"
          :countries="mapCountries"
          :current-replay-time="currentReplayTime"
          :events="mapEvents"
          :image-src="worldMapCommand"
          :consistency-audit="consistencyAudit"
          :kpis="lifecycleKpis"
          :lifecycle-event-mode="lifecycleEventMode"
          :lifecycle-events="lifecycleEventsForDisplay"
          :processed-events="lifecycleEventsForDisplay.length"
          :replay-speed="replaySpeed"
          :routes="supplyRoutes"
          :show-delta-overlay="showDeltaOverlay"
          @cancel="cancelLifecycleRun"
          @clone="cloneFromCurrentRun"
          @compare="openCompareShortcut"
          @open-country-analysis="openEntityAnalysis"
          @pause="pauseLifecycleRun"
          @replay="openReplayShortcut"
          @resume="resumeLifecycleRun"
          @retry="retryLifecycleRun"
          @run="run"
          @select-causal-edge="selectCausalEdge"
          @select-country="selectMapCountry"
          @select-day="selectReplayDay"
          @select-event="selectMapEvent"
          @select-supply-chain="selectSupplyChain"
          @show-causal="navigateSection('graph')"
          @show-upcoming="showUpcoming"
          @toggle-delta="toggleDeltaOverlay"
        />

        <section v-if="activeSection !== 'overview'" class="war-room-section-board" :data-section="activeSection">
          <div class="section-title">
            <div>
              <div class="section-kicker"><component :is="activeSectionMeta.icon" :size="16" /> {{ activeSectionMeta.label }}</div>
              <h2>{{ activeSectionMeta.title }}</h2>
              <p class="sandbox-note">{{ activeSectionMeta.desc }}</p>
            </div>
            <button class="secondary" type="button" @click="navigateSection('overview')">返回战情总览</button>
          </div>

          <WarRoomSandboxModule
            v-if="activeSection === 'sandbox'"
            :chain-name="chainName"
            :chain-options="chainOptions"
            :country-name-short="countryNameShort"
            :country-options="countryOptions"
            :on-clear-policy-actions="clearPolicyActions"
            :on-clone="cloneFromCurrentRun"
            :on-load-run="load"
            :on-run="run"
            :on-select-all-countries="selectAllCountries"
            :on-toggle-draft-list="toggleDraftList"
            :policy-action-label="policyActionLabel"
            :policy-actions="policyActions"
            :preset-scenarios="presetScenarios"
            :run-versions="runVersions"
            :running="running"
            :scenario-draft="scenarioDraft"
            :scenario-label="scenarioLabel"
            :selected-run-id="selectedRunId"
            :short-run-id="shortRunId"
            :version-label="versionLabel"
          />

          <WarRoomAnalysisModule
            v-else-if="activeSection === 'analysis'"
            :active-agent="activeAgent"
            :active-agent-decision-confidence="activeAgentDecisionConfidence"
            :active-entity-detail="activeEntityDetail"
            :analysis-filter="analysisFilter"
            :country-name-short="countryNameShort"
            :filtered-analysis-countries="filteredAnalysisCountries"
            :on-analysis-filter-change="value => analysisFilter = value"
            :on-open-decision-drawer="openDecisionDrawer"
            :on-set-analysis-country="setAnalysisCountry"
            :risk-channel="riskChannel"
          />

          <WarRoomGraphModule
            v-else-if="activeSection === 'graph'"
            :active-graph-edge="activeGraphEdge"
            :chain-name="chainName"
            :country-name-short="countryNameShort"
            :edge-label="edgeLabel"
            :filtered-graph-edges="filteredGraphEdges"
            :focused-graph-edge-id="focusedGraphEdgeId"
            :graph-type-filters="graphTypeFilters"
            :graph-type-options="graphTypeOptions"
            :on-focus-graph-edge="focusGraphEdge"
            :on-open-entity-detail="openEntityDetail"
            :on-render-section-graph="renderSectionGraph"
            :on-toggle-graph-type-filter="toggleGraphTypeFilter"
          />

          <WarRoomDataModule
            v-else-if="activeSection === 'data'"
            :active-data-tab="activeDataTab"
            :chain-name="chainName"
            :command-actions="commandActions"
            :country-name-short="countryNameShort"
            :data-json-preview="dataJsonPreview"
            :entity-details="entityDetails"
            :entity-index="entityIndex"
            :map-countries="mapCountries"
            :on-copy-run-id="copyRunId"
            :on-download-ui-state="downloadUiState"
            :on-open-replay-shortcut="openReplayShortcut"
            :on-set-active-data-tab="value => activeDataTab = value"
            :risk-channel="riskChannel"
            :selected-run-id="selectedRunId"
            :short-run-id="shortRunId"
            :signed="signed"
            :timeline-events="timelineEvents"
            :ui-map-entities="uiMapEntities"
            :war-room="warRoom"
          />

          <WarRoomSettingsModule
            v-else-if="activeSection === 'settings'"
            :engine-mode="lifecycleEngineMode"
            :layer-label="layerLabel"
            :on-engine-mode-change="value => lifecycleEngineMode = value"
            :visible-map-layers="visibleMapLayers"
          />

          <WarRoomReplayModule
            v-else-if="activeSection === 'replay'"
            :replay-pack="replayPack"
            :selected-run-id="selectedRunId"
            :war-room-diff="warRoomDiff"
          />

        </section>
      </section>

      <div v-if="toastMessage" class="war-room-toast">{{ toastMessage }}</div>

      <aside v-if="commandSearchOpen" class="feature-drawer command-search-drawer" data-testid="war-room-command-search">
        <button class="drawer-close" type="button" @click="commandSearchOpen = false"><X :size="16" /> 关闭</button>
        <div class="section-kicker"><Search :size="16" /> 指挥搜索</div>
        <h2>定位国家、链路、事件和运行</h2>
        <label class="command-search-box">
          搜索实体
          <input v-model="commandQuery" type="search" placeholder="输入：中国 / chips / D+14 / run id" data-testid="war-room-command-search-input" />
        </label>
        <div class="command-result-list">
          <button v-for="item in commandSearchResults" :key="item.id" type="button" :data-entity-id="item.id" @click="activateCommandResult(item)">
            <span>{{ entityTypeLabel(item.type) }}</span>
            <strong>{{ item.title_zh }}</strong>
            <small>{{ item.subtitle_zh }}</small>
          </button>
        </div>
        <p v-if="!commandSearchResults.length" class="sandbox-note">没有匹配结果。可以搜索国家代码、供应链、D+天数或 Agent 决策。</p>
      </aside>

      <aside v-if="entityDetailDrawer" class="feature-drawer entity-detail-drawer" data-testid="war-room-entity-detail-drawer" :data-entity-id="entityDetailDrawer.id">
        <button class="drawer-close" type="button" @click="entityDetailDrawer = null"><X :size="16" /> 关闭</button>
        <div class="section-kicker"><FileSearch :size="16" /> 实体详情</div>
        <h2>{{ entityDetailDrawer.title_zh || entityDetailDrawer.title }}</h2>
        <p>{{ entityDetailDrawer.summary_zh || entityDetailDrawer.summary }}</p>
        <dl>
          <div v-for="metric in entityDetailDrawer.metrics || []" :key="metric.label_zh || metric.label">
            <dt>{{ metric.label_zh || metric.label }}</dt>
            <dd>{{ metric.value }}</dd>
          </div>
        </dl>
        <section v-if="entityDetailDrawer.related_events?.length" class="drawer-mini-section">
          <h3>关联事件</h3>
          <p>{{ entityDetailDrawer.related_events.join(' / ') }}</p>
        </section>
        <section v-if="entityDetailDrawer.decision_basis_zh" class="drawer-mini-section">
          <h3>决策依据</h3>
          <p>{{ entityDetailDrawer.decision_basis_zh }}</p>
        </section>
        <div class="drawer-action-row">
          <button v-for="action in entityDetailDrawer.actions || []" :key="action.key" type="button" :disabled="action.enabled === false" @click="handleEntityAction(action, entityDetailDrawer)">
            {{ action.label_zh }}
          </button>
        </div>
      </aside>

      <aside v-if="upcomingFeature" class="feature-drawer">
        <button class="drawer-close" type="button" @click="upcomingFeature = null"><X :size="16" /> 关闭</button>
        <div class="section-kicker"><Info :size="16" /> 即将推出</div>
        <h2>{{ upcomingFeature.title }}</h2>
        <p>{{ upcomingFeature.body }}</p>
        <p class="sandbox-note">当前按钮已明确标记为说明入口，不再作为无反馈控件处理。</p>
      </aside>

      <aside v-if="decisionDrawer" class="feature-drawer decision-drawer">
        <button class="drawer-close" type="button" @click="decisionDrawer = null"><X :size="16" /> 关闭</button>
        <div class="section-kicker"><ListChecks :size="16" /> Agent 决策详情</div>
        <h2>{{ decisionDrawer.title }}</h2>
        <p>{{ decisionDrawer.rationale }}</p>
        <dl>
          <div><dt>国家 Agent</dt><dd>{{ decisionDrawer.country }}</dd></div>
          <div><dt>置信度</dt><dd>{{ decisionDrawer.confidence }}</dd></div>
          <div><dt>驱动因素</dt><dd>{{ decisionDrawer.drivers }}</dd></div>
          <div><dt>预期代价</dt><dd>{{ decisionDrawer.tradeoff }}</dd></div>
        </dl>
      </aside>

      <section v-if="activeSection === 'replay' && runVersions.length > 1" ref="comparePanelEl" class="compare-panel immersive-compare">
        <div class="section-title">
          <div>
            <div class="section-kicker"><GitCompareArrows :size="16" /> 反事实对比</div>
            <h2>运行对比</h2>
            <p class="sandbox-note">策略沙盘对比，不是现实战争预测。</p>
          </div>
          <span class="quality-pill">{{ runDiffLoading ? '加载对比中' : warRoomDiff ? '对比已生成' : '请选择两次运行' }}</span>
        </div>
        <div class="compare-controls">
          <label>基准运行<select v-model="compareBaseRunId" @change="loadRunDiff"><option v-for="run in runVersions" :key="`base-${run.run_id}`" :value="run.run_id">{{ versionLabel(run) }}</option></select></label>
          <label>目标运行<select v-model="compareTargetRunId" @change="loadRunDiff"><option v-for="run in runVersions" :key="`target-${run.run_id}`" :value="run.run_id">{{ versionLabel(run) }}</option></select></label>
        </div>
        <div v-if="warRoomDiff" class="diff-metrics">
          <article><span>总体风险</span><strong :class="deltaClass(warRoomDiff.global_risk_delta)">{{ signed(warRoomDiff.global_risk_delta) }}</strong></article>
          <article><span>国家风险变化</span><strong :class="deltaClass(warRoomDiff.top_country_risk_delta?.delta)">{{ signed(warRoomDiff.top_country_risk_delta?.delta) }}</strong><small>{{ warRoomDiff.top_country_risk_delta?.country_code }}</small></article>
          <article><span>供应链压力变化</span><strong :class="deltaClass(warRoomDiff.top_chain_pressure_delta?.delta)">{{ signed(warRoomDiff.top_chain_pressure_delta?.delta) }}</strong><small>{{ chainName(warRoomDiff.top_chain_pressure_delta?.key) }}</small></article>
          <article><span>图谱置信度</span><strong :class="deltaClass(warRoomDiff.graph_confidence_delta)">{{ signed(warRoomDiff.graph_confidence_delta) }}</strong></article>
        </div>
      </section>

      <section v-if="activeSection === 'replay' && detail.latest_run" class="replay-pack-panel">
        <div class="section-title">
          <div>
            <div class="section-kicker"><PackageCheck :size="16" /> 复盘包</div>
            <h2>导出 War Room 复盘包</h2>
            <p class="sandbox-note">确定性 Markdown 与 JSON 审计清单。</p>
          </div>
          <button class="secondary" type="button" :disabled="replayPackLoading" @click="exportReplayPack">
            <PackageCheck :size="16" /> {{ replayPackLoading ? '导出中...' : '导出复盘包' }}
          </button>
        </div>
        <div v-if="replayPack" class="replay-summary-grid">
          <article><span>运行 ID</span><strong>{{ replayPack.run_id }}</strong></article>
          <article><span>政策动作</span><strong>{{ replayPack.policy_actions?.map(policyActionLabel).join(', ') || '无' }}</strong></article>
          <article><span>最高风险国家</span><strong>{{ replayPack.summary?.top_risk_country?.country_code || '--' }} · {{ Math.round(replayPack.summary?.top_risk_country?.risk || 0) }}</strong></article>
          <article><span>最大链路变化</span><strong :class="deltaClass(replayPack.summary?.top_chain_delta?.delta)">{{ signed(replayPack.summary?.top_chain_delta?.delta) }}</strong></article>
          <article><span>峰值风险变化</span><strong :class="deltaClass(replayPack.summary?.timeline_peak_delta)">{{ signed(replayPack.summary?.timeline_peak_delta) }}</strong></article>
        </div>
        <div v-if="replayPack" class="replay-actions">
          <button class="secondary" type="button" @click="replayPreviewOpen = true"><PanelRightOpen :size="16" /> 打开预览</button>
          <a class="download" :href="replayPackUrl" :download="replayPackFilename"><Download :size="16" /> 下载 Markdown</a>
          <a class="download" :href="replayPackJsonUrl" :download="replayPackJsonFilename"><Download :size="16" /> 下载 JSON 清单</a>
        </div>
        <div v-else class="empty">运行 War Room 场景后可导出单次或反事实复盘包。</div>
      </section>
    </template>

    <template v-else>
      <section class="workspace-head">
        <div class="workspace-title">
          <div class="section-kicker"><ShieldAlert :size="16" /> 研究工作台</div>
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
            <Play :size="16" /> {{ running ? '运行中...' : '运行研究' }}
          </button>
        </div>
      </section>
    </template>

    <aside v-if="replayPreviewOpen && replayPack" class="replay-preview-drawer">
      <button class="drawer-close" type="button" @click="replayPreviewOpen = false"><X :size="16" /> 关闭</button>
      <div class="section-kicker"><PackageCheck :size="16" /> 复盘包预览</div>
      <h2>{{ replayPack.title }}</h2>
      <p class="sandbox-note">{{ replayPack.disclaimer }}</p>
      <div class="replay-preview-grid">
        <article><span>包版本</span><strong>{{ replayPack.manifest?.pack_version }}</strong></article>
        <article><span>运行 ID</span><strong>{{ replayPack.manifest?.run_id }}</strong></article>
        <article><span>基准运行</span><strong>{{ replayPack.manifest?.base_run_id || '无' }}</strong></article>
        <article><span>反事实</span><strong>{{ replayPack.manifest?.is_counterfactual ? '是' : '否' }}</strong></article>
      </div>
      <h3>审计轨迹</h3>
      <div class="audit-list"><article v-for="item in replayPack.audit_trail" :key="item.step"><span>{{ item.step }} · {{ item.source }}</span><p>{{ item.detail }}</p></article></div>
      <h3>Markdown 预览</h3>
      <pre class="markdown-preview">{{ markdownPreview }}</pre>
    </aside>

    <section class="workflow-rail">
      <article v-for="step in steps" :key="step.key" :class="{ done: step.done }">
        <span>{{ step.index }}</span><strong>{{ step.title }}</strong><p>{{ step.desc }}</p>
      </article>
    </section>

    <section class="split-lab">
      <div class="graph-panel">
        <div class="section-title">
          <div><div class="section-kicker"><Network :size="16" /> 因果链路</div><h2>{{ isWarRoom ? '沙盘影响图' : '事件到市场的推理路径' }}</h2></div>
          <span v-if="detail.graph" class="quality-pill">置信度 {{ Math.round(detail.graph.confidence) }}</span>
        </div>
        <div ref="graphEl" class="graph-canvas"></div>
      </div>
      <aside class="insight-panel">
        <div class="section-title">
          <div><div class="section-kicker"><ListChecks :size="16" /> 运行过程</div><h2>工作流时间线</h2></div>
          <span class="quality-pill">{{ currentModeText }}</span>
        </div>
        <p class="summary-box">{{ detail.latest_run?.summary || '尚未运行。点击运行生成快照、因果图和报告。' }}</p>
        <div class="metric-grid" v-if="detail.graph">
          <article><span>节点</span><strong>{{ detail.graph.nodes.length }}</strong></article>
          <article><span>因果边</span><strong>{{ detail.graph.edges.length }}</strong></article>
          <article><span>证据源</span><strong>{{ detail.graph.evidence_sources.length }}</strong></article>
        </div>
      </aside>
    </section>

    <section ref="reportPanelEl" class="report-chat">
      <article class="report-panel">
        <div class="section-title">
          <div><div class="section-kicker"><FileText :size="16" /> 研判报告</div><h2>{{ detail.report?.title || '等待报告' }}</h2></div>
          <span v-if="detail.report" class="quality-pill">{{ detail.report.mode }}</span>
        </div>
        <template v-if="detail.report">
          <p class="report-summary">{{ detail.report.summary }}</p>
          <h3>核心结论</h3>
          <ul class="finding-list">
            <li v-for="(item, index) in detail.report.key_findings" :key="item">
              <button @click="openEvidenceDrawer(item, index)">{{ item }}</button>
            </li>
          </ul>
          <p class="sandbox-note">{{ detail.report.disclaimer }}</p>
          <a class="download" :href="markdownUrl" download="worldpulse_report.md"><Download :size="16" /> 导出 Markdown 报告</a>
        </template>
        <div v-else class="empty">运行后生成报告。</div>
      </article>
      <aside class="chat-panel">
        <div class="section-title"><div><div class="section-kicker"><MessagesSquare :size="16" /> 继续追问</div><h2>追问证据与边界</h2></div></div>
        <div class="quick-prompts"><button v-for="prompt in prompts" :key="prompt" @click="message = prompt">{{ prompt }}</button></div>
        <div class="chat-log"><div v-for="msg in detail.chat_messages" :key="msg.message_id" :class="['chat-msg', msg.role]"><span>{{ msg.role === 'user' ? '你' : 'WorldPulse' }}</span><p>{{ msg.content }}</p></div></div>
        <div class="chat-input"><textarea v-model="message" rows="3" placeholder="追问证据、反例、情景或结论边界"></textarea><button :disabled="chatting || !message" @click="send"><Send :size="16" /> {{ chatting ? '分析中...' : '发送' }}</button></div>
      </aside>
    </section>

    <aside v-if="evidenceDrawer" class="evidence-drawer">
      <button class="drawer-close" @click="evidenceDrawer = null"><X :size="16" /> 关闭</button>
      <div class="section-kicker"><FileSearch :size="16" /> 证据抽屉</div>
      <h2>{{ evidenceDrawer.finding }}</h2>
      <p>{{ evidenceDrawer.summary }}</p>
    </aside>
  </main>
  <main v-else class="loading-page">加载研究工作台...</main>
</template>

<script setup>
import * as d3 from 'd3'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronsLeft,
  Copy,
  Crosshair,
  Database,
  Download,
  FileSearch,
  FileText,
  GitCompareArrows,
  Home,
  Info,
  Layers3,
  ListChecks,
  MapPinned,
  MessagesSquare,
  Network,
  PackageCheck,
  PanelRightOpen,
  Pause,
  Play,
  Search,
  Send,
  Settings,
  ShieldAlert,
  UsersRound,
  X
} from 'lucide-vue-next'
import { chatWithProject, getProject, getProjectRun, runProject } from '../../api'
import worldMapCommand from '../../assets/war-room/world-map-command.png'
import WarRoomAnalysisModule from '../../components/war-room/WarRoomAnalysisModule.vue'
import WarRoomDataModule from '../../components/war-room/WarRoomDataModule.vue'
import WarRoomGraphModule from '../../components/war-room/WarRoomGraphModule.vue'
import WarRoomLifecycleRail from '../../components/war-room/WarRoomLifecycleRail.vue'
import WarRoomOverviewConsole from '../../components/war-room/WarRoomOverviewConsole.vue'
import WarRoomReplayModule from '../../components/war-room/WarRoomReplayModule.vue'
import WarRoomSandboxModule from '../../components/war-room/WarRoomSandboxModule.vue'
import WarRoomSettingsModule from '../../components/war-room/WarRoomSettingsModule.vue'
import WarRoomTopNav from '../../components/war-room/WarRoomTopNav.vue'
import { useRunLifecycle } from '../../composables/useRunLifecycle'
import { useRunLifecycleConsole } from '../../composables/useRunLifecycleConsole'
import { useWarRoomArtifacts } from '../../composables/useWarRoomArtifacts'
import { useWarRoomData } from '../../composables/useWarRoomData'
import { useWarRoomMapProjection } from '../../composables/useWarRoomMapProjection'
import { useWarRoomReplayControls } from '../../composables/useWarRoomReplayControls'
import { useWarRoomScenarioDraft } from '../../composables/useWarRoomScenarioDraft'
import { decisionLabels, eventFilterOptions, graphTypeOptions, localizedText, prompts } from './warRoomWorkspaceConfig'

const props = defineProps({ projectId: String, section: String })
const route = useRoute()
const router = useRouter()
const warRoomData = useWarRoomData(() => props.projectId)
const runLifecycle = useRunLifecycle(() => props.projectId)
const detail = ref(null)
const workspaceState = ref(null)
const graphEl = ref(null)
const sectionGraphEl = ref(null)
const selected = ref(null)
const running = ref(false)
const chatting = ref(false)
const message = ref('')
const runMode = ref('fast')
const lifecycleEngineMode = ref('deterministic')
const selectedRunId = ref('')
const evidenceDrawer = ref(null)
const focusedEdgeKey = ref('')
const presets = ref(null)
const comparePanelEl = ref(null)
const reportPanelEl = ref(null)
const upcomingFeature = ref(null)
const toastMessage = ref('')
const decisionDrawer = ref(null)
const entityDetailDrawer = ref(null)
const commandSearchOpen = ref(false)
const commandQuery = ref('')
const showDeltaOverlay = ref(false)
const focusedEntityId = ref('')
const focusedGraphEdgeId = ref('')
const activeDataTab = ref('tables')
const analysisFilter = ref('')
const graphTypeFilters = ref([])
let toastTimer = null
const shortRunId = (runId) => {
  const text = String(runId || '')
  return text ? text.replace(/^run_/, '#').slice(0, 13) : ''
}

const sectionKeys = ['overview', 'sandbox', 'analysis', 'graph', 'data', 'settings', 'replay']
const sectionMeta = {
  overview: { key: 'overview', label: '战情总览', title: '全球态势总览', desc: '地图、KPI、Agent 和时间线的指挥台总览。', icon: ShieldAlert },
  sandbox: { key: 'sandbox', label: '推演沙盘', title: '场景构建与推演参数', desc: '集中管理目标国家、供应链、政策动作和高级假设。', icon: MapPinned },
  analysis: { key: 'analysis', label: '智能分析', title: 'Agent 决策与风险解释', desc: '解释当前国家 Agent 的触发源、驱动因素、预期代价和关联事件。', icon: Activity },
  graph: { key: 'graph', label: '知识图谱', title: '因果链路与机制', desc: '查看边权重、滞后天数和链路传播机制。', icon: BookOpen },
  data: { key: 'data', label: '数据中台', title: '运行快照与展示合同', desc: '审计 ui_state、时间线、供应链和快照数据。', icon: Database },
  settings: { key: 'settings', label: '系统设置', title: '显示设置与待上线能力', desc: '管理显示层、策略边界和未上线控件说明。', icon: Settings },
  replay: { key: 'replay', label: '复盘包', title: 'Replay Pack 导出', desc: '生成 Markdown 与 JSON 审计清单。', icon: PackageCheck }
}
const topSections = [sectionMeta.overview, sectionMeta.sandbox, sectionMeta.analysis, sectionMeta.graph, sectionMeta.data]
const railSections = [sectionMeta.overview, sectionMeta.sandbox, sectionMeta.graph, sectionMeta.analysis, sectionMeta.data, sectionMeta.replay, sectionMeta.settings]
const isWarRoom = computed(() => detail.value?.project?.mode === 'war_room')
const activeSection = computed(() => {
  const raw = String(route.params.section || props.section || 'overview')
  return sectionKeys.includes(raw) ? raw : 'overview'
})
const activeSectionMeta = computed(() => sectionMeta[activeSection.value] || sectionMeta.overview)
const runVersions = computed(() => detail.value?.runs || [])
const workflowEvents = computed(() => detail.value?.latest_run?.data_snapshot?.workflow_events || [])
const warRoom = computed(() => detail.value?.latest_run?.simulation_snapshot || detail.value?.latest_run?.data_snapshot?.war_room || null)
const warRoomUi = computed(() => workspaceState.value?.ui_state || warRoom.value?.ui_state || {})
const {
  chainLabels,
  countryNames,
  fallbackChains,
  policyActions,
  scenarioDraft,
  scenarioTitle,
  scenarioBackground,
  factorControls,
  countryOptions,
  chainOptions,
  presetScenarios,
  chainName,
  riskChannel,
  scenarioLabel,
  policyActionLabel,
  countryNameShort,
  scenarioPayload,
  toggleDraftList,
  clearPolicyActions,
  selectAllCountries,
  syncScenarioDraft: syncScenarioDraftFromDetail,
  applySelectedScenarioDefaults,
} = useWarRoomScenarioDraft({ presets, warRoom, showToast })
function syncScenarioDraft() { syncScenarioDraftFromDetail(detail.value) }
const {
  visibleMapLayers,
  mapZoom,
  layerMenuOpen,
  eventFilterOpen,
  eventFilters,
  hoveredMapEntity,
  selectedMapEntity,
  uiMapEntities,
  mapLayerButtons,
  militaryUnits,
  mapCountries,
  supplyRoutes,
  mapCausalEdges,
  mapEvents,
  timelineEvents,
  zoomMap: zoomMapProjection,
  resetMapView: resetMapProjection,
  layerLabel,
  layerActive,
  toggleMapLayer,
} = useWarRoomMapProjection({
  warRoomUi,
  warRoom,
  detail,
  fallbackChains,
  countryNameShort,
  localizeText,
  normalizeRiskValue,
  averageRisk,
  countryDelta,
  edgeKey,
  showToast,
})
const {
  replayPlaying,
  replaySpeed,
  activeReplayIndex,
  activeTimelineEvent,
  activeReplayDay,
  activeReplayProgress,
  activeEventKeys,
  selectReplayDay,
  toggleReplay,
  cycleReplaySpeed,
} = useWarRoomReplayControls({ timelineEvents, selectedMapEntity, showToast })
const entityIndex = computed(() => Array.isArray(workspaceState.value?.entity_index) && workspaceState.value.entity_index.length ? workspaceState.value.entity_index : (Array.isArray(warRoomUi.value?.entity_index) ? warRoomUi.value.entity_index : []))
const commandActions = computed(() => Array.isArray(workspaceState.value?.command_actions) && workspaceState.value.command_actions.length ? workspaceState.value.command_actions : (Array.isArray(warRoomUi.value?.command_actions) ? warRoomUi.value.command_actions : []))
const runControl = computed(() => workspaceState.value?.run_control || warRoomUi.value?.run_control || {})
const lifecycleProjection = computed(() => warRoomData.buildLifecycleProjection(detail.value, workspaceState.value, runDiff.value, replayPack.value))
const {
  activeLifecycleRun,
  consistencyAudit,
  lifecycleControl,
  lifecycleEventMode,
  lifecycleEventsForDisplay,
  lifecycleAgentStatus,
  lifecycleKpis,
  lifecycleStages,
  pauseLifecycleRun,
  resumeLifecycleRun,
  cancelLifecycleRun,
  retryLifecycleRun,
} = useRunLifecycleConsole({ runLifecycle, lifecycleProjection, runVersions, running, showToast, onCompleted: load })
const insightCards = computed(() => Array.isArray(workspaceState.value?.insight_cards) && workspaceState.value.insight_cards.length ? workspaceState.value.insight_cards : (Array.isArray(warRoomUi.value?.insight_cards) ? warRoomUi.value.insight_cards : []))
const entityDetails = computed(() => workspaceState.value?.entity_details || warRoomUi.value?.entity_details || {})
const topRiskCountry = computed(() => [...(warRoom.value?.risk_heatmap || [])].sort((a, b) => Number(b.risk || 0) - Number(a.risk || 0))[0] || null)
const topChainPressure = computed(() => [...(warRoom.value?.supply_chains || [])].sort((a, b) => Number(b.pressure || b.disruption || 0) - Number(a.pressure || a.disruption || 0))[0] || null)
const filteredTimelineEvents = computed(() => {
  if (!eventFilters.value.length) return timelineEvents.value
  return timelineEvents.value.filter(event => eventMatchesFilters(event))
})
const commandSearchResults = computed(() => {
  const query = commandQuery.value.trim().toLowerCase()
  const items = entityIndex.value
  if (!query) return items.slice(0, 8)
  return items
    .filter(item => {
      const text = [item.id, item.type, item.title_zh, item.subtitle_zh, item.section, item.layer, ...(item.tokens || [])].join(' ').toLowerCase()
      return text.includes(query)
    })
    .slice(0, 12)
})
const activeRunControlItems = computed(() => [
  { label: '当前运行', value: shortRunId(runControl.value.current_run_id || selectedRunId.value || detail.value?.latest_run?.run_id) },
  { label: '上一轮', value: shortRunId(runControl.value.previous_run_id) || '暂无' },
  { label: '运行数', value: String(runControl.value.run_count ?? runVersions.value.length) },
  { label: '状态', value: runControl.value.status_zh || (runVersions.value.length > 1 ? '可对比复盘' : '等待对比样本') }
])
const filteredAnalysisCountries = computed(() => {
  const query = analysisFilter.value.trim().toLowerCase()
  const countries = [...mapCountries.value].sort((a, b) => Number(b.risk || 0) - Number(a.risk || 0))
  if (!query) return countries
  return countries.filter(country => {
    const text = [country.code, countryNameShort(country.code), riskChannel(country.dominant_channel), country.dominant_channel].join(' ').toLowerCase()
    return text.includes(query)
  })
})
const activeAgentDecisionConfidence = computed(() => {
  const decision = warRoom.value?.agent_decisions?.find(item => item.country_code === activeAgent.value.code || item.code === activeAgent.value.code)
  return decision?.confidence !== undefined ? `${Math.round(Number(decision.confidence))}/100` : '规则解释'
})
const filteredGraphEdges = computed(() => {
  const edges = mapCausalEdges.value
  if (!graphTypeFilters.value.length) return edges
  return edges.filter(edge => {
    const types = graphEdgeTypes(edge.edge)
    return graphTypeFilters.value.some(type => types.includes(type))
  })
})
const activeGraphEdge = computed(() => {
  if (focusedGraphEdgeId.value) return mapCausalEdges.value.find(edge => edge.id === focusedGraphEdgeId.value) || null
  return filteredGraphEdges.value[0] || null
})
const dataJsonPreview = computed(() => JSON.stringify({
  project_id: props.projectId,
  run_id: selectedRunId.value,
  run_control: runControl.value,
  ui_state: warRoomUi.value,
  risk_heatmap: warRoom.value?.risk_heatmap || [],
  supply_chains: warRoom.value?.supply_chains || [],
  agent_decisions: warRoom.value?.agent_decisions || [],
  timeline_events: timelineEvents.value,
  disclaimer: warRoom.value?.disclaimer || workspaceState.value?.disclaimer
}, null, 2))
const {
  runDiff,
  runDiffLoading,
  compareBaseRunId,
  compareTargetRunId,
  replayPack,
  replayPackLoading,
  replayPreviewOpen,
  warRoomDiff,
  markdownUrl,
  replayPackUrl,
  replayPackJsonUrl,
  replayPackFilename,
  replayPackJsonFilename,
  markdownPreview,
  prepareCompareDefaults,
  loadRunDiff,
  exportReplayPack,
  copyRunId,
  downloadUiState,
  resetReplayArtifacts,
} = useWarRoomArtifacts({ detail, isWarRoom, runVersions, selectedRunId, warRoomData, dataJsonPreview, showToast })
const activeCountryCodes = computed(() => {
  if (selectedMapEntity.value?.type === 'country') return [selectedMapEntity.value.id]
  return activeTimelineEvent.value?.relatedCountries?.length ? activeTimelineEvent.value.relatedCountries : [topRiskCountry.value?.country_code || 'CHN']
})
const currentGlobalRisk = computed(() => {
  if (activeTimelineEvent.value?.globalRisk !== undefined) return normalizeRiskValue(activeTimelineEvent.value.globalRisk)
  const risks = warRoom.value?.risk_heatmap || []
  return risks.length ? risks.reduce((sum, item) => sum + Number(item.risk || 0), 0) / risks.length : 68
})
const currentReplayTime = computed(() => {
  return activeTimelineEvent.value?.time || '2025-05-16 14:30'
})
const activeAgent = computed(() => {
  const selectedCode = selectedMapEntity.value?.type === 'country' ? selectedMapEntity.value.id : selected.value?.country_code || selected.value?.code
  const topCode = selectedCode || activeCountryCodes.value[0] || topRiskCountry.value?.country_code || 'CHN'
  const decision = warRoom.value?.agent_decisions?.find(item => item.country_code === topCode || item.code === topCode)
  const heat = warRoom.value?.risk_heatmap?.find(item => item.country_code === topCode)
  const risk = Math.round(Number(heat?.risk || (topCode === 'CHN' ? 85 : 70)))
  const activeEvent = activeTimelineEvent.value
  const panel = warRoomUi.value?.agent_panels?.[topCode]
  if (panel) {
    const metrics = (panel.metrics || []).map(item => ({
      label: item.label_zh || item.label,
      value: Math.round(Number(item.value || 0))
    }))
    return {
      code: topCode,
      flag: topCode === 'CHN' ? '中国' : topCode,
      name: panel.country_name_zh || countryNameShort(topCode),
      enName: panel.country_name || topCode,
      status: panel.status_zh || (risk > 70 ? '活跃' : '观察'),
      intent: panel.strategic_intent_zh || '当前 Agent 正根据规则沙盘输出调整策略姿态。',
      power: metrics.find(item => item.label === '综合国力')?.value || Math.min(95, Math.max(45, risk)),
      metrics: metrics.length ? metrics.filter(item => item.label !== '综合国力') : [
        { label: '军事能力', value: Math.min(95, risk + 5) },
        { label: '经济实力', value: Math.min(94, risk + 3) },
        { label: '社会稳定性', value: Math.max(48, 100 - Math.round(risk / 4)) }
      ],
      decisions: panel.decisions?.length ? panel.decisions : (panel.drivers_zh || ['观察态势']),
      triggerSource: selectedMapEntity.value ? `${entityTypeLabel(selectedMapEntity.value.type)}：${activeEntityDetail.value.title}` : (panel.trigger_source_zh || `${activeEvent?.time || 'D+0'} · ${activeEvent?.title || '态势更新'}`),
      relatedEvents: panel.related_events?.length ? panel.related_events : relatedEventLabels(topCode),
      decisionBasis: panel.decision_basis_zh || '依据后端 ui_state 合同中的风险构成、供应链压力和 Agent 决策规则展示。',
      expectedTradeoff: panel.expected_tradeoff_zh || '短期降低部分通道风险，但可能转移压力到其他链路。',
      relations: panel.relations || [],
      actions: panel.recent_actions || []
    }
  }
  const drivers = decision?.drivers?.length ? decision.drivers.map(riskChannel) : ['强化反制', '外交斡旋', '经济施压', '舆论引导']
  return {
    code: topCode,
    flag: topCode === 'CHN' ? '中国' : topCode,
    name: countryNameShort(topCode),
    enName: topCode,
    status: risk > 70 ? '活跃' : '观察',
    intent: localizeText(decision?.rationale) || '维护国家主权和领土完整，反对外部干涉，推动局势向自身战略目标演化。',
    power: Math.min(95, Math.max(45, risk)),
    metrics: [
      { label: '军事能力', value: Math.min(95, risk + 5) },
      { label: '经济实力', value: Math.min(94, risk + 3) },
      { label: '科技水平', value: Math.max(55, risk - 3) },
      { label: '外交影响力', value: Math.max(50, risk - 7) },
      { label: '社会稳定性', value: Math.max(48, 100 - Math.round(risk / 4)) }
    ],
    decisions: drivers,
    triggerSource: selectedMapEntity.value ? `${entityTypeLabel(selectedMapEntity.value.type)}：${activeEntityDetail.value.title}` : `${activeEvent?.time || 'D+0'} · ${activeEvent?.title || '态势更新'}`,
    relatedEvents: relatedEventLabels(topCode),
    decisionBasis: drivers.length ? `主要依据：${drivers.join('、')}。当前风险通道为 ${riskChannel(heat?.dominant_channel || decision?.primary_driver || 'military')}。` : '依据当前风险热力、供应链压力和外交关系网络给出规则解释。',
    expectedTradeoff: localizeText(decision?.expected_tradeoff) || '短期可降低局部风险，但可能把压力转移到供应链、金融或舆论通道。',
    relations: [
      { country: '俄罗斯', role: '全面战略协作伙伴', label: '友好', score: 85, tone: 'friendly' },
      { country: '美国', role: '战略竞争对手', label: '对抗', score: 25, tone: 'hostile' },
      { country: '日本', role: '重要邻国', label: '竞争', score: 35, tone: 'warning' },
      { country: '欧盟', role: '全面战略伙伴', label: '合作', score: 70, tone: 'friendly' }
    ],
    actions: ['2025-05-15 在南海加强海上巡逻', '2025-05-14 举行台海周边军事演习', '2025-05-13 推动 RCEP 区域合作深化']
  }
})
const activeEntityDetail = computed(() => {
  const entity = selectedMapEntity.value
  const backendDetail = detailForSelectedEntity()
  if (backendDetail) {
    return {
      type: backendDetail.type || entity?.type || 'entity',
      id: backendDetail.id || entity?.id || 'entity',
      title: backendDetail.title_zh || backendDetail.title || '实体详情',
      summary: backendDetail.summary_zh || backendDetail.summary || '',
      metrics: (backendDetail.metrics || []).map(item => ({ label: item.label_zh || item.label, value: item.value })),
      raw: backendDetail
    }
  }
  if (!entity) {
    const event = activeTimelineEvent.value
    return {
      type: 'timeline',
      id: event?.key || 'current',
      title: event?.title || '当前态势',
      summary: event?.detail || '当前沙盘回放节点的综合态势。',
      metrics: [
        { label: '当前日', value: event?.time || 'D+0' },
        { label: '全球风险', value: `${Math.round(currentGlobalRisk.value)}/100` },
        { label: '关联国家', value: activeCountryCodes.value.map(countryNameShort).join('、') || '--' }
      ]
    }
  }
  if (entity.type === 'country') {
    const country = mapCountries.value.find(item => item.code === entity.id)
    return {
      type: 'country',
      id: entity.id,
      title: `${countryNameShort(entity.id)}风险节点`,
      summary: `${countryNameShort(entity.id)} 当前风险 ${Math.round(country?.risk || 0)}/100，主导通道为 ${riskChannel(country?.dominant_channel)}。`,
      metrics: [
        { label: '风险分值', value: `${Math.round(country?.risk || 0)}/100` },
        { label: '风险变化', value: country?.delta === null || country?.delta === undefined ? '暂无对比' : signed(country.delta) },
        { label: '关联事件', value: relatedEventLabels(entity.id).join('、') }
      ]
    }
  }
  if (entity.type === 'supply_chain') {
    const chain = (warRoom.value?.supply_chains || fallbackChains).find(item => item.key === entity.id) || entity.payload || {}
    return {
      type: 'supply_chain',
      id: entity.id,
      title: `${chainName(entity.id, chain.name)}链路`,
      summary: `供应链压力 ${Math.round(Number(chain.pressure || chain.disruption || 0))}/100，替代率 ${Math.round(Number(chain.substitution || 0))}%。`,
      metrics: [
        { label: '压力', value: `${Math.round(Number(chain.pressure || chain.disruption || 0))}/100` },
        { label: '容量', value: `${Math.round(Number(chain.capacity || 100))}%` },
        { label: '滞后', value: `${chain.lag_days ?? 0} 天` }
      ]
    }
  }
  if (entity.type === 'causal_edge') {
    const edge = entity.payload || {}
    return {
      type: 'causal_edge',
      id: entity.id,
      title: `${edgeLabel(edge.source)} → ${edgeLabel(edge.target)}`,
      summary: localizeText(edge.mechanism || edge.explanation || edge.relation || '该因果边来自当前沙盘快照。'),
      metrics: [
        { label: '机制', value: edge.relation || edge.kind || '因果传导' },
        { label: '权重', value: edge.weight !== undefined ? Number(edge.weight).toFixed(2) : '--' },
        { label: '滞后', value: `${edge.lag_days ?? 0} 天` }
      ]
    }
  }
  if (entity.type === 'event') {
    const event = mapEvents.value.find(item => item.key === entity.id) || entity.payload || {}
    return {
      type: 'event',
      id: entity.id,
      title: event.title || '事件热点',
      summary: event.detail || `关联 ${event.relatedCountries?.map(countryNameShort).join('、') || '关键国家'} 的事件热点。`,
      metrics: [
        { label: '发生日', value: `D+${event.day ?? activeReplayDay.value}` },
        { label: '关联国家', value: event.relatedCountries?.map(countryNameShort).join('、') || countryNameShort(event.country_code) },
        { label: '类型', value: event.tone === 'red' ? '风险事件' : '态势事件' }
      ]
    }
  }
  return {
    type: entity.type,
    id: entity.id,
    title: entity.payload?.label || '地图实体',
    summary: '该实体来自当前地图图层。',
    metrics: [{ label: '当前日', value: `D+${activeReplayDay.value}` }]
  }
})
const statusText = computed(() => ({ created: '已创建', completed: '已完成' }[detail.value?.project?.status] || detail.value?.project?.status || '未知'))
const currentModeText = computed(() => isWarRoom.value ? 'War Room' : (detail.value?.latest_run?.data_snapshot?.run_mode === 'full' ? '完整真实数据' : '快速研究'))
const steps = computed(() => isWarRoom.value ? [
  { index: '01', key: 'scenario', title: '场景设定', desc: '锁定场景、持续天数和传播参数', done: !!detail.value?.project },
  { index: '02', key: 'agents', title: '国家 Agent', desc: '计算国家压力与行动倾向', done: !!warRoom.value?.agent_decisions?.length },
  { index: '03', key: 'chains', title: '供应链', desc: '能源、粮食、芯片、贸易与金融结算', done: !!warRoom.value?.supply_chains?.length },
  { index: '04', key: 'heatmap', title: '风险热力', desc: '识别承压国家和主导通道', done: !!warRoom.value?.risk_heatmap?.length },
  { index: '05', key: 'report', title: '报告追问', desc: '生成沙盘报告和引用证据', done: !!detail.value?.report }
] : [
  { index: '01', key: 'project', title: '研究任务', desc: '问题、地区和事件范围已锁定', done: !!detail.value?.project },
  { index: '02', key: 'events', title: '事件识别', desc: '聚合新闻、冲突和宏观信号', done: !!detail.value?.latest_run?.event_snapshot?.length },
  { index: '03', key: 'graph', title: '因果图谱', desc: '生成可解释节点和边', done: !!detail.value?.graph },
  { index: '04', key: 'backtest', title: '历史验证', desc: '相似事件窗口回测', done: !!detail.value?.latest_run?.backtest_snapshot?.sample_count },
  { index: '05', key: 'report', title: '报告追问', desc: '生成报告并继续对话', done: !!detail.value?.report }
])
function decisionStatus(status) { return decisionLabels[status] || status || '--' }
function averageRisk() {
  const risks = warRoom.value?.risk_heatmap || []
  return risks.length ? risks.reduce((sum, item) => sum + Number(item.risk || 0), 0) / risks.length : 68
}
function normalizeRiskValue(value) {
  const num = Number(value || 0)
  if (!Number.isFinite(num)) return 0
  return num > 0 && num <= 1 ? num * 100 : num
}
function localizeText(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (localizedText[text]) return localizedText[text]
  const match = Object.entries(localizedText).find(([source]) => text.includes(source))
  return match ? text.replace(match[0], match[1]) : text
}
function sectionPath(section) { return `/projects/${props.projectId}/war-room/${section}` }
function navigateSection(section) { router.push(sectionPath(section)) }
function showToast(message) {
  toastMessage.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toastMessage.value = '' }, 2600)
}
function showUpcoming(title, body) {
  upcomingFeature.value = { title, body }
  showToast(`${title}：已打开说明`)
}
function zoomMap(delta) {
  zoomMapProjection(delta)
  showToast(`地图缩放 ${Math.round(mapZoom.value * 100)}%`)
}
function resetMapView() {
  resetMapProjection()
  selected.value = null
  entityDetailDrawer.value = null
  activeReplayIndex.value = 0
  replayPlaying.value = false
  showToast('地图视图已重置')
}
function fullEntityId(type, id) {
  if (!id) return ''
  const raw = String(id)
  if (raw.includes(':')) return raw
  if (type === 'country') return `country:${raw}`
  if (type === 'supply_chain') return `chain:${raw}`
  if (type === 'event') return `event:${raw}`
  if (type === 'unit') return `unit:${raw}`
  return raw
}
function detailForSelectedEntity() {
  const entity = selectedMapEntity.value
  if (!entity) return null
  const id = fullEntityId(entity.type, entity.id)
  return entityDetails.value[id] || entityDetails.value[entity.id] || null
}
function openEntityDetail(type, id, payload = {}) {
  const fullId = fullEntityId(type, id)
  const detail = entityDetails.value[fullId] || entityDetails.value[id]
  entityDetailDrawer.value = detail || {
    id: fullId || id,
    type,
    title_zh: payload.title || payload.label || payload.country_name || id,
    summary_zh: payload.detail || payload.explanation || '该实体来自当前 War Room 沙盘图层。',
    metrics: [{ label_zh: '当前日', value: `D+${activeReplayDay.value}` }],
    actions: [{ key: 'focus', label_zh: '在地图中定位', action_type: 'focus', enabled: true }]
  }
}
function mapTooltipFor(type, id, payload = {}) {
  const fullId = fullEntityId(type, id)
  const detail = entityDetails.value[fullId] || entityDetails.value[id]
  const point = payload || {}
  return {
    x: Math.max(18, Math.min(860, Number(point.x || 500) * mapZoom.value / 1.2)),
    y: Math.max(18, Math.min(470, Number(point.y || 280) * mapZoom.value / 1.25)),
    title: detail?.title_zh || point.title || point.label || point.country_name || point.key || id,
    detail: detail?.summary_zh || point.detail || point.mechanism || point.dominant_channel_zh || '点击查看详情'
  }
}
function activateCommandResult(item) {
  commandSearchOpen.value = false
  commandQuery.value = ''
  if (item.type === 'timeline' || String(item.id).startsWith('timeline:')) {
    const index = timelineEvents.value.findIndex(event => event.key === item.ref || `timeline:${event.key}` === item.id || Number(event.day) === Number(item.day))
    if (index >= 0) selectTimelineEvent(timelineEvents.value[index], index)
    showToast(`已定位时间线：${item.title_zh}`)
    return
  }
  const ref = item.ref || item.id
  if (String(ref).startsWith('country:')) {
    const code = String(ref).split(':')[1]
    const country = mapCountries.value.find(row => row.code === code) || { code, country_name: item.title_zh }
    selectMapCountry(country)
  } else if (String(ref).startsWith('chain:')) {
    const key = String(ref).split(':')[1]
    const chain = (warRoom.value?.supply_chains || []).find(row => row.key === key) || { key, name: item.title_zh }
    selectSupplyChain(chain)
  } else if (String(ref).startsWith('event:')) {
    const key = String(ref).split(':')[1]
    const event = mapEvents.value.find(row => row.key === key) || { key, title: item.title_zh }
    selectMapEvent(event)
  } else if (String(ref).startsWith('edge:')) {
    const edge = mapCausalEdges.value.find(row => row.id === ref)
    if (edge) selectCausalEdge(edge.edge, edge.id)
  } else if (String(ref).startsWith('decision:')) {
    navigateSection('analysis')
  }
  if (item.section && item.section !== activeSection.value) navigateSection(item.section)
  openEntityDetail(item.type, item.ref || item.id, item)
  showToast(`已定位：${item.title_zh}`)
}
function handleEntityAction(action, detail) {
  if (action.action_type === 'section' && action.section) {
    navigateSection(action.section)
    showToast(`已进入${sectionMeta[action.section]?.label || action.section}`)
    return
  }
  if (action.action_type === 'replay') {
    openReplayShortcut()
    return
  }
  showToast(`${detail.title_zh || detail.title} 已在地图中高亮`)
}
function cloneFromCurrentRun() {
  syncScenarioDraft()
  navigateSection('sandbox')
  showToast('已克隆当前运行参数到场景构建器')
}
function openCompareShortcut() {
  if (!lifecycleControl.value.compareReady && !runControl.value.compare_ready) {
    showToast('需要至少两次 War Room 运行才能对比')
    return
  }
  loadRunDiff()
  navigateSection('replay')
  nextTick(() => comparePanelEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  showToast('已打开反事实对比')
}
async function openReplayShortcut() {
  if (!lifecycleControl.value.replayReady && !runControl.value.replay_ready) {
    showToast('请先运行一次 War Room 沙盘')
    return
  }
  navigateSection('replay')
  await exportReplayPack()
  showToast('复盘包已生成')
}
function toggleDeltaOverlay() {
  showDeltaOverlay.value = !showDeltaOverlay.value
  showToast(showDeltaOverlay.value ? '已开启反事实变化图层' : '已关闭反事实变化图层')
}
function toggleEventFilter(key) {
  eventFilters.value = eventFilters.value.includes(key) ? eventFilters.value.filter(item => item !== key) : [...eventFilters.value, key]
  showToast(eventFilters.value.length ? `已应用 ${eventFilters.value.length} 个事件筛选` : '事件筛选已清除')
}
function eventMatchesFilters(event) {
  if (!eventFilters.value.length) return true
  if (eventFilters.value.includes('selected_entity') && selectedMapEntity.value) {
    const detail = entityDetailDrawer.value || detailForSelectedEntity()
    const relatedCountries = new Set(selectedMapEntity.value.payload?.relatedCountries || selectedMapEntity.value.payload?.related_countries || detail?.related_countries || [])
    const relatedChains = new Set(selectedMapEntity.value.payload?.relatedChains || selectedMapEntity.value.payload?.related_chains || detail?.related_chains || [])
    const countryMatch = (event.relatedCountries || []).some(code => relatedCountries.has(code) || relatedCountries.has(countryNameShort(code)))
    const chainMatch = (event.relatedChains || []).some(key => relatedChains.has(key) || relatedChains.has(chainName(key)))
    if (!countryMatch && !chainMatch) return false
  }
  const toneMap = { blue: 'military', green: 'diplomatic', orange: 'economic', purple: 'social', red: 'turning', neutral: 'military' }
  const derived = toneMap[event.tone] || 'military'
  const typeFilters = eventFilters.value.filter(item => item !== 'selected_entity')
  if (!typeFilters.length) return true
  return typeFilters.includes(derived) || (event.turning && typeFilters.includes('turning'))
}
function eventVisible(event) {
  if (!eventFilters.value.length) return true
  const linked = timelineEvents.value.filter(item => item.eventKeys?.includes(event.key))
  return linked.length ? linked.some(eventMatchesFilters) : eventFilters.value.includes(event.tone === 'red' ? 'turning' : 'military')
}
function setAnalysisCountry(code) {
  focusedEntityId.value = `country:${code}`
  const country = mapCountries.value.find(item => item.code === code) || { code, risk: 0 }
  selectMapCountry(country)
  showToast(`已定位 Agent：${countryNameShort(code)}`)
}
function graphEntityType(id) {
  const raw = String(id?.id || id || '')
  if (raw.startsWith('country:') || countryNames[raw]) return 'country'
  if (raw.startsWith('chain:')) return 'supply_chain'
  if (raw === 'scenario' || raw.startsWith('event:')) return 'event'
  if (raw === 'market') return 'market'
  if (raw === 'opinion') return 'public_opinion'
  if (raw === 'alliance') return 'alliance'
  if (raw === 'policy') return 'policy_response'
  return 'event'
}
function graphEdgeTypes(edge) {
  return [...new Set([graphEntityType(edge.source), graphEntityType(edge.target)])]
}
function toggleGraphTypeFilter(key) {
  graphTypeFilters.value = graphTypeFilters.value.includes(key) ? graphTypeFilters.value.filter(item => item !== key) : [...graphTypeFilters.value, key]
  showToast(graphTypeFilters.value.length ? `已应用 ${graphTypeFilters.value.length} 个图谱筛选` : '图谱筛选已清除')
  nextTick(renderSectionGraph)
}
function focusGraphEdge(edge) {
  focusedGraphEdgeId.value = edge.id
  focusedEdgeKey.value = edgeKey(edge.edge)
  selectCausalEdge(edge.edge, edge.id)
  nextTick(renderSectionGraph)
  showToast(`已高亮链路：${edgeLabel(edge.edge.source)} → ${edgeLabel(edge.edge.target)}`)
}
function entityActive(type, id) { return selectedMapEntity.value?.type === type && selectedMapEntity.value?.id === id }
function entityTypeLabel(type) {
  return ({ country: '国家节点', supply_chain: '供应链', causal_edge: '因果边', event: '事件热点', unit: '军事单元', timeline: '时间线' })[type] || '地图实体'
}
function isCountryHot(code) { return activeCountryCodes.value.includes(code) }
function relatedEventLabels(countryCode) {
  const labels = timelineEvents.value
    .filter(event => event.relatedCountries?.includes(countryCode))
    .slice(0, 3)
    .map(event => `${event.time} ${event.title}`)
  return labels.length ? labels : [`D+${activeReplayDay.value} ${activeTimelineEvent.value?.title || '态势更新'}`]
}
function riskColor(value) {
  const risk = Number(value || 0)
  if (risk >= 72) return '#ff4d5f'
  if (risk >= 52) return '#f59e32'
  if (risk >= 35) return '#36a7ff'
  return '#21d69b'
}
function riskOpacity(value) { return Math.min(0.86, Math.max(0.18, Number(value || 0) / 100)) }
function goDeepAnalysis() {
  navigateSection('analysis')
  showToast(`已进入深度分析：${activeAgent.value.name}`)
}
function openEntityAnalysis(code) {
  focusedEntityId.value = `country:${code}`
  const country = mapCountries.value.find(item => item.code === code) || { code }
  selectMapCountry(country)
  navigateSection('analysis')
  showToast(`已进入智能分析：${countryNameShort(code)}`)
}
function openDecisionDrawer(chip) {
  const decision = warRoom.value?.agent_decisions?.find(item => item.country_code === activeAgent.value.code || item.country_name === activeAgent.value.enName) || {}
  decisionDrawer.value = {
    title: chip,
    country: activeAgent.value.name,
    confidence: decision.confidence !== undefined ? `${Math.round(Number(decision.confidence))}/100` : '规则解释',
    drivers: decision.drivers?.map(riskChannel).join('、') || activeAgent.value.decisions.join('、'),
    rationale: localizeText(decision.rationale) || activeAgent.value.decisionBasis,
    tradeoff: localizeText(decision.expected_tradeoff) || activeAgent.value.expectedTradeoff
  }
  showToast('已打开 Agent 决策详情')
}

async function load(runId = selectedRunId.value) {
  detail.value = runId ? await getProjectRun(props.projectId, runId) : await getProject(props.projectId)
  selectedRunId.value = detail.value?.latest_run?.run_id || ''
  await loadWorkspaceState(selectedRunId.value)
  syncScenarioDraft()
  await loadPresets()
  prepareCompareDefaults()
  await loadRunDiff()
  await nextTick()
  renderGraph()
}
async function loadWorkspaceState(runId = selectedRunId.value) {
  if (!isWarRoom.value) {
    workspaceState.value = null
    return
  }
  try {
    workspaceState.value = await warRoomData.loadWorkspace(runId)
  } catch {
    workspaceState.value = null
  }
}
async function loadPresets() {
  if (!isWarRoom.value || presets.value) return
  try {
    presets.value = await warRoomData.loadPresets()
    if (!scenarioDraft.target_countries.length || !scenarioDraft.target_chains.length) {
      const scenario = presets.value.scenarios?.find(item => item.key === scenarioDraft.scenario_key)
      if (scenario) {
        scenarioDraft.target_countries = [...(scenario.target_countries || [])]
        scenarioDraft.target_chains = [...(scenario.target_chains || [])]
      }
    }
  } catch {
    presets.value = null
  }
}
async function run() {
  running.value = true
  try {
    if (isWarRoom.value) {
      await runLifecycle.create({ engine_mode: lifecycleEngineMode.value, scenario: scenarioPayload(), seed: scenarioDraft.seed || 42 })
      showToast('生命周期任务已排队；请启动或保持 worker 运行')
      return
    }
    detail.value = await runProject(props.projectId, runMode.value)
    selectedRunId.value = detail.value?.latest_run?.run_id || ''
    await loadWorkspaceState(selectedRunId.value)
    resetReplayArtifacts()
    syncScenarioDraft()
    prepareCompareDefaults(true)
    await loadRunDiff()
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
    await load(selectedRunId.value)
  } finally {
    chatting.value = false
  }
}
function selectMapCountry(country) {
  replayPlaying.value = false
  selectedMapEntity.value = { type: 'country', id: country.code, day: activeReplayDay.value, payload: country }
  selected.value = {
    ...country,
    kind: '国家风险',
    label: country.country_name || countryNameShort(country.code),
    country_code: country.code,
    explanation: `${country.country_name || countryNameShort(country.code)} 风险为 ${Math.round(country.risk)}/100，主导通道为 ${riskChannel(country.dominant_channel)}。`
  }
  openEntityDetail('country', country.code, country)
}
function selectSupplyChain(chain) {
  replayPlaying.value = false
  selectedMapEntity.value = { type: 'supply_chain', id: chain.key, day: activeReplayDay.value, payload: chain }
  selected.value = { ...chain, kind: '供应链瓶颈', label: chainName(chain.key, chain.name), explanation: `当前压力 ${Math.round(Number(chain.pressure || chain.disruption || 0))}/100。` }
  openEntityDetail('supply_chain', chain.key, chain)
}
function selectCausalEdge(edge, edgeId = edgeKey(edge)) {
  replayPlaying.value = false
  focusedGraphEdgeId.value = edgeId
  focusedEdgeKey.value = edgeKey(edge)
  selectedMapEntity.value = { type: 'causal_edge', id: edgeId, day: activeReplayDay.value, payload: edge }
  selected.value = { ...edge, kind: '因果边', label: `${edgeLabel(edge.source)} → ${edgeLabel(edge.target)}`, explanation: edge.explanation || edge.mechanism || edge.relation || '因果机制来自当前沙盘运行快照。' }
  openEntityDetail('causal_edge', edgeId, edge)
}
function selectMilitaryUnit(unit) {
  replayPlaying.value = false
  selectedMapEntity.value = { type: 'unit', id: unit.key, day: activeReplayDay.value, payload: unit }
  selected.value = { ...unit, kind: '军事单元', label: unit.label, explanation: `${unit.label} 用于表达当前态势中的军事部署信号。` }
  openEntityDetail('unit', unit.key, unit)
}
function selectMapEvent(event) {
  replayPlaying.value = false
  const index = timelineEvents.value.findIndex(item => item.eventKeys?.includes(event.key) || item.day === event.day)
  if (index >= 0) activeReplayIndex.value = index
  selectedMapEntity.value = { type: 'event', id: event.key, day: event.day ?? activeReplayDay.value, payload: event }
  selected.value = { ...event, kind: '事件热点', label: event.title, country_code: event.country_code || (event.key === 'china' ? 'CHN' : event.key === 'us' ? 'USA' : event.key === 'japan' ? 'JPN' : 'TWN'), explanation: event.detail || event.title }
  openEntityDetail('event', event.key, event)
}
function selectTimelineEvent(event, index = timelineEvents.value.findIndex(item => item.key === event.key)) {
  replayPlaying.value = false
  if (index >= 0) activeReplayIndex.value = index
  selectedMapEntity.value = null
  selected.value = { ...event, kind: '时间线事件', label: event.title, explanation: event.detail }
  entityDetailDrawer.value = entityDetails.value[`timeline:${event.key}`] || {
    id: `timeline:${event.key}`,
    type: 'timeline',
    title_zh: event.title,
    summary_zh: event.detail,
    metrics: [
      { label_zh: '发生日', value: event.time },
      { label_zh: '全局风险', value: `${Math.round(event.globalRisk || currentGlobalRisk.value)}/100` }
    ],
    related_events: [],
    actions: [{ key: 'focus', label_zh: '在时间线中定位', action_type: 'focus', enabled: true }]
  }
}
function scrollToReport() { reportPanelEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
function countryDelta(code) {
  const item = warRoomDiff.value?.country_risk_delta?.find(row => row.country_code === code)
  return item ? item.delta : null
}
function deltaClass(value) {
  const num = Number(value || 0)
  if (num > 0) return 'up'
  if (num < 0) return 'down'
  return 'flat'
}
function versionLabel(run) {
  const mode = run.data_snapshot?.run_mode === 'war_room' ? 'War Room' : run.data_snapshot?.run_mode === 'full' ? '完整' : '快速'
  return `${mode} · ${run.completed_at || run.started_at}`
}
function signed(value) {
  if (value === null || value === undefined) return '--'
  const num = Number(value)
  return `${num >= 0 ? '+' : ''}${Number.isInteger(num) ? num : num.toFixed(1)}`
}
function openEvidenceDrawer(finding, findingIndex = 0) {
  evidenceDrawer.value = {
    finding,
    summary: detail.value?.report?.citations?.[findingIndex]?.summary || '按结论内容匹配最相关的证据和因果边。'
  }
}
function edgeLabel(id) {
  const rawId = id?.id || id
  if (String(rawId || '').startsWith('country:')) return countryNameShort(String(rawId).split(':')[1])
  if (String(rawId || '').startsWith('chain:')) return chainName(String(rawId).split(':')[1])
  if (rawId === 'scenario') return '场景冲击'
  if (rawId === 'market') return '金融市场'
  if (rawId === 'opinion') return '公共舆论'
  if (rawId === 'alliance') return '外交联盟'
  if (rawId === 'policy') return '政策响应'
  const node = (detail.value?.graph?.nodes || []).find(item => item.id === rawId)
  return node?.label || countryNames[rawId] || rawId
}
function edgeKey(edge) {
  const source = edge.source?.id || edge.source
  const target = edge.target?.id || edge.target
  return `${source}->${target}:${edge.relation || ''}`
}
function renderGraph() {
  const graph = detail.value?.graph
  const el = graphEl.value
  if (!graph || !el) return
  el.innerHTML = ''
  const width = el.clientWidth || 760
  const height = 520
  const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${width} ${height}`)
  const nodes = graph.nodes.map(node => ({ ...node }))
  const edges = graph.edges.map(edge => ({ ...edge }))
  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(130).strength(0.55))
    .force('charge', d3.forceManyBody().strength(-560))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(56))
  const link = svg.append('g').selectAll('line').data(edges).enter().append('line')
    .attr('class', d => edgeKey(d) === focusedEdgeKey.value ? 'edge-line edge-focused' : 'edge-line')
    .attr('stroke-width', d => 1 + Number(d.weight || 0.5) * 2)
    .on('click', (_, d) => { selected.value = { ...d, source: d.source.id || d.source, target: d.target.id || d.target } })
  const node = svg.append('g').selectAll('g').data(nodes).enter().append('g')
    .attr('class', d => `node node-${d.kind}`)
    .call(d3.drag()
      .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null }))
    .on('click', (_, d) => { selected.value = d })
  node.append('circle').attr('r', d => 18 + Number(d.score || 50) / 8)
  node.append('text').text(d => d.label).attr('dy', 44).attr('text-anchor', 'middle')
  simulation.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y)
    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })
}

function renderSectionGraph() {
  const el = sectionGraphEl.value
  if (!el) return
  el.innerHTML = ''
  const edgeItems = filteredGraphEdges.value
  if (!edgeItems.length) {
    const empty = document.createElement('div')
    empty.className = 'graph-empty-state'
    empty.textContent = '当前筛选条件下没有因果链路'
    el.appendChild(empty)
    return
  }

  const width = el.clientWidth || 720
  const height = Math.max(420, Math.min(560, Math.round(width * 0.66)))
  const graphNodes = new Map()
  const links = edgeItems.map(item => {
    const sourceId = item.edge.source?.id || item.edge.source
    const targetId = item.edge.target?.id || item.edge.target
    if (!graphNodes.has(sourceId)) graphNodes.set(sourceId, { id: sourceId, label: edgeLabel(sourceId), kind: graphEntityType(sourceId) })
    if (!graphNodes.has(targetId)) graphNodes.set(targetId, { id: targetId, label: edgeLabel(targetId), kind: graphEntityType(targetId) })
    return { ...item.edge, source: sourceId, target: targetId, itemId: item.id }
  })
  const nodes = [...graphNodes.values()]
  const svg = d3.select(el)
    .append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img')
    .attr('aria-label', 'War Room 因果链路图')
  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(node => node.id).distance(120).strength(0.62))
    .force('charge', d3.forceManyBody().strength(-430))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(48))

  const link = svg.append('g')
    .attr('class', 'section-graph-links')
    .selectAll('line')
    .data(links)
    .enter()
    .append('line')
    .attr('class', item => item.itemId === focusedGraphEdgeId.value ? 'edge-line edge-focused' : 'edge-line')
    .attr('stroke-width', item => 1.4 + Number(item.weight || 0.5) * 2.6)
    .attr('data-entity-type', 'causal_edge')
    .attr('data-entity-id', item => item.itemId)
    .on('click', (_, item) => {
      const edgeItem = edgeItems.find(candidate => candidate.id === item.itemId)
      if (edgeItem) focusGraphEdge(edgeItem)
    })
  const node = svg.append('g')
    .attr('class', 'section-graph-nodes')
    .selectAll('g')
    .data(nodes)
    .enter()
    .append('g')
    .attr('class', item => `node node-${item.kind}`)
    .attr('data-entity-type', item => item.kind)
    .attr('data-entity-id', item => item.id)
    .call(d3.drag()
      .on('start', (event, item) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        item.fx = item.x
        item.fy = item.y
      })
      .on('drag', (event, item) => {
        item.fx = event.x
        item.fy = event.y
      })
      .on('end', (event, item) => {
        if (!event.active) simulation.alphaTarget(0)
        item.fx = null
        item.fy = null
      }))
  node.append('circle').attr('r', 21)
  node.append('text').text(item => item.label).attr('dy', 38).attr('text-anchor', 'middle')
  simulation.on('tick', () => {
    link
      .attr('x1', item => item.source.x)
      .attr('y1', item => item.source.y)
      .attr('x2', item => item.target.x)
      .attr('y2', item => item.target.y)
    node.attr('transform', item => `translate(${item.x},${item.y})`)
  })
}

watch(() => detail.value?.graph?.graph_id, () => nextTick(renderGraph))
watch(activeSection, section => {
  if (!sectionKeys.includes(section)) router.replace(sectionPath('overview'))
  if (section === 'graph') nextTick(renderSectionGraph)
})
watch(filteredGraphEdges, () => {
  if (activeSection.value === 'graph') nextTick(renderSectionGraph)
})
watch(focusedGraphEdgeId, () => {
  if (activeSection.value === 'graph') nextTick(renderSectionGraph)
})
watch(() => scenarioDraft.scenario_key, applySelectedScenarioDefaults)
onMounted(load)
onUnmounted(() => {
  runLifecycle.stop()
  if (toastTimer) window.clearTimeout(toastTimer)
})
</script>
