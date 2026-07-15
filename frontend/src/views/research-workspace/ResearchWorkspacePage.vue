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
          :active-agents="`${Math.min(20, Math.max(0, warRoom?.agent_decisions?.length || 0) + 8)}/20`"
          :active-replay-day="activeReplayDay"
          :causal-edges="mapCausalEdges"
          :control="lifecycleControl"
          :countries="mapCountries"
          :current-replay-time="currentReplayTime"
          :events="mapEvents"
          :image-src="worldMapCommand"
          :kpis="lifecycleProjection.kpis"
          :lifecycle-event-mode="lifecycleEventMode"
          :lifecycle-events="lifecycleEventsForDisplay"
          :processed-events="Math.max(0, timelineEvents.length * 208)"
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
            :layer-label="layerLabel"
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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
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
import { useWarRoomData } from '../../composables/useWarRoomData'

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
const selectedRunId = ref('')
const evidenceDrawer = ref(null)
const focusedEdgeKey = ref('')
const presets = ref(null)
const runDiff = ref(null)
const runDiffLoading = ref(false)
const compareBaseRunId = ref('')
const compareTargetRunId = ref('')
const replayPack = ref(null)
const replayPackLoading = ref(false)
const replayPreviewOpen = ref(false)
const comparePanelEl = ref(null)
const reportPanelEl = ref(null)
const visibleMapLayers = ref(['military', 'economic', 'diplomatic', 'events', 'risk', 'causal'])
const mapZoom = ref(1)
const layerMenuOpen = ref(true)
const eventFilterOpen = ref(false)
const eventFilters = ref([])
const upcomingFeature = ref(null)
const toastMessage = ref('')
const decisionDrawer = ref(null)
const entityDetailDrawer = ref(null)
const commandSearchOpen = ref(false)
const commandQuery = ref('')
const hoveredMapEntity = ref(null)
const showDeltaOverlay = ref(false)
const focusedEntityId = ref('')
const focusedGraphEdgeId = ref('')
const activeDataTab = ref('tables')
const analysisFilter = ref('')
const graphTypeFilters = ref([])
const replayPlaying = ref(false)
const replaySpeed = ref(1)
const activeReplayIndex = ref(0)
const selectedMapEntity = ref(null)
let replayTimer = null
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
const eventFilterOptions = [
  { key: 'military', label: '军事事件', tone: 'blue' },
  { key: 'diplomatic', label: '外交事件', tone: 'green' },
  { key: 'economic', label: '经济事件', tone: 'orange' },
  { key: 'social', label: '社会事件', tone: 'purple' },
  { key: 'turning', label: '关键拐点', tone: 'red' },
  { key: 'selected_entity', label: '只看选中实体', tone: 'green' }
]
const graphTypeOptions = [
  { key: 'event', label: '事件' },
  { key: 'country', label: '国家' },
  { key: 'supply_chain', label: '供应链' },
  { key: 'market', label: '市场' },
  { key: 'public_opinion', label: '舆论' },
  { key: 'alliance', label: '联盟' },
  { key: 'policy_response', label: '政策' }
]

const prompts = ['证据链最弱的一环是什么？', '有没有历史反例？', '如果传播系数降低，结论怎么变？', '哪些国家 Agent 最值得观察？']
const fallbackCountries = ['USA', 'CHN', 'JPN', 'KOR', 'TWN', 'IND', 'EU', 'RUS', 'SAU', 'BRA'].map(code => ({ code }))
const fallbackChains = ['energy', 'food', 'chips', 'shipping', 'settlement'].map(key => ({ key }))
const policyActions = [
  { key: 'sanctions', label: '制裁', desc: '提高金融结算和贸易压力。' },
  { key: 'counter_sanctions', label: '反制裁', desc: '触发互惠贸易与金融压力。' },
  { key: 'energy_reroute', label: '能源改道', desc: '降低能源风险，但增加物流负载。' },
  { key: 'food_export_limit', label: '粮食出口限制', desc: '提高粮食与舆论压力。' },
  { key: 'alliance_deterrence', label: '联盟威慑', desc: '把部分风险转向军事信号。' },
  { key: 'liquidity_support', label: '流动性支持', desc: '缓冲金融结算压力。' },
  { key: 'public_messaging', label: '舆论沟通', desc: '降低公众情绪压力。' }
]
const chainLabels = { energy: '能源', food: '粮食', chips: '关键芯片', shipping: '海运贸易', settlement: '金融结算' }
const channelLabels = { energy: '能源', food: '粮食', trade: '贸易', chips: '芯片', financial: '金融', public_opinion: '舆论', military: '军事', settlement: '结算', shipping: '海运', social_stability: '社会稳定' }
const scenarioLabels = { strait_blockade_30d: '海峡危机升级推演', energy_export_cut: '能源出口中断', food_shortfall: '粮食减产与出口限制' }
const decisionLabels = { changed: '已变化', new: '新增', unchanged: '未变化' }
const fallbackMapLayerButtons = [
  { key: 'military', label: '军事部署' },
  { key: 'economic', label: '经济联系' },
  { key: 'diplomatic', label: '外交关系' },
  { key: 'events', label: '事件热点' },
  { key: 'risk', label: '风险区域' }
]
const countryCoordinates = {
  USA: { x: 728, y: 216 },
  BRA: { x: 830, y: 430 },
  EU: { x: 214, y: 232 },
  RUS: { x: 322, y: 140 },
  SAU: { x: 322, y: 330 },
  IND: { x: 438, y: 322 },
  CHN: { x: 497, y: 276 },
  JPN: { x: 603, y: 255 },
  KOR: { x: 576, y: 250 },
  TWN: { x: 565, y: 304 }
}
const countryNames = { USA: '美国', CHN: '中国', JPN: '日本', KOR: '韩国', TWN: '台湾', IND: '印度', EU: '欧盟', RUS: '俄罗斯', SAU: '中东', BRA: '巴西' }
const localizedText = {
  'Scenario initialized; baseline dependencies and alliance posture locked.': '场景初始化，基线依赖与联盟姿态已锁定。',
  'First-order logistics, deterrence, and market repricing begin.': '一阶物流、威慑与市场重定价开始显现。',
  'Supply-chain substitution and public narrative become dominant uncertainties.': '供应链替代与公共叙事成为主要不确定性。',
  'Second-order policy responses, sanctions, and financial stress propagate.': '二阶政策响应、制裁与金融压力继续扩散。',
  'High import dependency and rising supply-chain pressure make energy substitution the first stabilizer.': '高进口依赖与供应链压力上升，使能源替代成为首要稳定动作。',
  'Semiconductor exposure dominates the simulated causal chain.': '半导体暴露成为当前因果链中的主导压力。',
  'Protects critical capacity while raising trade friction.': '保护关键产能，但会抬高贸易摩擦。'
}
const chainAnchors = { energy: ['SAU', 'JPN'], food: ['BRA', 'IND'], chips: ['TWN', 'USA'], shipping: ['CHN', 'EU'], settlement: ['USA', 'EU'] }
const fallbackMilitaryUnits = [
  { key: 'carrier-1', label: '航母', x: 584, y: 320 },
  { key: 'ship-1', label: '舰队', x: 740, y: 386 },
  { key: 'air-1', label: '空巡', x: 630, y: 382 },
  { key: 'ship-2', label: '护航', x: 456, y: 392 }
]

const scenarioDraft = reactive({
  scenario_key: 'strait_blockade_30d',
  duration_days: 30,
  intensity: 0.65,
  propagation: 0.42,
  target_countries: [],
  target_chains: [],
  policy_actions: [],
  country_overrides: { JPN: { energy_dependency: 92 } },
  chain_overrides: { energy: { substitution: 38 }, settlement: { lag_days: 3 } }
})
const scenarioTitle = ref('台海危机升级推演 · 2025 Q3')
const scenarioBackground = ref('台湾局势持续紧张，周边军事活动增加，美中战略博弈加剧。')
const influenceFactor = ref(80)
const retaliationFactor = ref(70)
const supplyFactor = ref(60)
const pressureFactor = ref(40)

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
const uiMapEntities = computed(() => Array.isArray(warRoomUi.value?.map_entities) ? warRoomUi.value.map_entities : [])
const entityIndex = computed(() => Array.isArray(workspaceState.value?.entity_index) && workspaceState.value.entity_index.length ? workspaceState.value.entity_index : (Array.isArray(warRoomUi.value?.entity_index) ? warRoomUi.value.entity_index : []))
const commandActions = computed(() => Array.isArray(workspaceState.value?.command_actions) && workspaceState.value.command_actions.length ? workspaceState.value.command_actions : (Array.isArray(warRoomUi.value?.command_actions) ? warRoomUi.value.command_actions : []))
const runControl = computed(() => workspaceState.value?.run_control || warRoomUi.value?.run_control || {})
const lifecycleProjection = computed(() => warRoomData.buildLifecycleProjection(detail.value, workspaceState.value, runDiff.value, replayPack.value))
const activeLifecycleRun = computed(() => runLifecycle.activeRun.value)
const lifecycleStages = computed(() => {
  const job = activeLifecycleRun.value
  if (!job) return lifecycleProjection.value.stages
  const order = ['scenario_compile', 'environment_prepare', 'deterministic_run', 'consistency_audit', 'report_generate', 'replay_archive']
  const index = Math.max(0, order.indexOf(job.current_phase))
  const titles = {
    scenario_compile: ['01', '场景编译', '解析剧本与约束'],
    environment_prepare: ['02', '环境准备', '加载数据与初始化'],
    deterministic_run: ['03', '混合推演', '确定性规则推演中'],
    consistency_audit: ['04', '一致性审计', '规则校验与修正'],
    report_generate: ['05', '报告生成', '汇总洞察与图表'],
    replay_archive: ['06', '复盘归档', '固化结果与溯源'],
  }
  return order.map((phase, phaseIndex) => {
    const [stageIndex, title, desc] = titles[phase]
    const terminalDone = job.status === 'completed'
    const stopped = ['failed', 'cancelled', 'paused'].includes(job.status)
    return {
      key: phase,
      index: stageIndex,
      title,
      desc,
      status: terminalDone || phaseIndex < index ? 'done' : phaseIndex === index && !stopped ? 'current' : 'pending',
    }
  })
})
const lifecycleControl = computed(() => {
  const base = lifecycleProjection.value.control
  const job = activeLifecycleRun.value
  if (!job) {
    const historicalStatus = base.replayReady ? 'completed' : 'ready'
    return {
      ...base,
      statusZh: historicalStatus,
      runStatus: historicalStatus,
      currentPhaseZh: base.replayReady ? '历史完成' : '等待运行',
      progress: base.replayReady ? 100 : 0,
      resultRunId: base.runId,
      canPause: false,
      canCancel: false,
      canResume: false,
      canRetry: false,
      busy: running.value,
      disclaimer: base.replayReady
        ? '历史 v1 run：可复盘/对比；新运行将进入 v2 生命周期队列。'
        : base.disclaimer,
    }
  }
  const status = job.status
  const resultRunId = job.result_run_id
  const phaseZh = {
    scenario_compile: '场景编译',
    environment_prepare: '环境准备',
    deterministic_run: '确定性推演',
    consistency_audit: '一致性审计',
    report_generate: '报告生成',
    replay_archive: '复盘归档',
  }[job.current_phase] || job.current_phase
  return {
    ...base,
    runId: job.run_id,
    resultRunId,
    runStatus: status,
    statusZh: status,
    currentPhase: job.current_phase,
    currentPhaseZh: phaseZh,
    progress: job.progress,
    engineMode: job.engine_mode,
    startedAt: job.started_at || job.created_at,
    checkpointAt: job.updated_at,
    checkpointId: resultRunId ? `SNAP-${String(resultRunId).slice(-8)}` : `JOB-${String(job.run_id).slice(-8)}`,
    checkpointStatus: status,
    replayReady: status === 'completed' && !!resultRunId,
    compareReady: base.compareReady || (status === 'completed' && !!resultRunId && runVersions.value.length > 0),
    canPause: ['queued', 'preparing', 'running'].includes(status),
    canCancel: ['queued', 'preparing', 'running', 'pausing', 'paused'].includes(status),
    canResume: ['paused', 'pausing'].includes(status),
    canRetry: ['failed', 'cancelled'].includes(status),
    busy: ['queued', 'preparing', 'running', 'pausing', 'cancelling'].includes(status),
    disclaimer: status === 'completed'
      ? '真实生命周期任务已完成；结果已投影回 v1 workspace / Run Diff / Replay Pack。'
      : '当前为真实本地 Run Lifecycle：状态、事件、检查点来自 SQLite + 独立 worker。',
  }
})
const lifecycleEventsForDisplay = computed(() => runLifecycle.events.value.length ? runLifecycle.events.value : lifecycleProjection.value.events)
const lifecycleEventMode = computed(() => runLifecycle.events.value.length ? 'live' : 'projection')
const insightCards = computed(() => Array.isArray(workspaceState.value?.insight_cards) && workspaceState.value.insight_cards.length ? workspaceState.value.insight_cards : (Array.isArray(warRoomUi.value?.insight_cards) ? warRoomUi.value.insight_cards : []))
const entityDetails = computed(() => workspaceState.value?.entity_details || warRoomUi.value?.entity_details || {})
const warRoomDiff = computed(() => runDiff.value?.changed_metrics?.war_room || null)
const countryOptions = computed(() => presets.value?.countries || warRoom.value?.country_agents || fallbackCountries)
const chainOptions = computed(() => presets.value?.supply_chains || warRoom.value?.supply_chains || fallbackChains)
const topRiskCountry = computed(() => [...(warRoom.value?.risk_heatmap || [])].sort((a, b) => Number(b.risk || 0) - Number(a.risk || 0))[0] || null)
const topChainPressure = computed(() => [...(warRoom.value?.supply_chains || [])].sort((a, b) => Number(b.pressure || b.disruption || 0) - Number(a.pressure || a.disruption || 0))[0] || null)
const activeTimelineEvent = computed(() => timelineEvents.value[Math.min(activeReplayIndex.value, Math.max(0, timelineEvents.value.length - 1))] || timelineEvents.value[0] || null)
const activeReplayDay = computed(() => activeTimelineEvent.value?.day ?? 0)
const activeReplayProgress = computed(() => activeTimelineEvent.value?.position ?? 0)
const activeEventKeys = computed(() => activeTimelineEvent.value?.eventKeys || [])
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
const presetScenarios = computed(() => {
  const scenarios = presets.value?.scenarios || []
  return scenarios.length ? scenarios : [
    { key: 'strait_blockade_30d', name: '30-day Strait Blockade' },
    { key: 'energy_export_cut', name: 'Energy Export Interruption' },
    { key: 'food_shortfall', name: 'Food Shortfall / Export Controls' }
  ]
})
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
const mapLayerButtons = computed(() => {
  const layers = Array.isArray(warRoomUi.value?.map_layers) ? warRoomUi.value.map_layers : []
  return layers.length
    ? layers.map(layer => ({ key: layer.key, label: layer.label_zh || layer.label || layer.key, enabled: layer.enabled !== false }))
    : fallbackMapLayerButtons
})
const militaryUnits = computed(() => {
  const units = uiMapEntities.value.filter(entity => entity.type === 'unit')
  return units.length
    ? units.map(entity => ({ key: entity.key || entity.id?.replace('unit:', ''), label: entity.label_zh || entity.label, x: entity.x, y: entity.y, ...entity }))
    : fallbackMilitaryUnits
})
const kpiCards = computed(() => {
  const uiKpis = Array.isArray(warRoomUi.value?.kpis) ? warRoomUi.value.kpis : []
  if (uiKpis.length) {
    return uiKpis.map(card => ({
      key: card.key,
      label: card.label_zh || card.label || card.key,
      value: `${card.value}${card.unit || ''}`,
      detail: card.detail_zh || card.detail || '',
      tone: card.tone || 'neutral',
      delta: card.delta,
      active: true,
      sparkline: card.sparkline || []
    }))
  }
  return [
  { key: 'risk', label: '全球风险指数', value: `${Math.round(currentGlobalRisk.value)}/100`, detail: `D+${activeReplayDay.value} 动态态势`, tone: 'risk', delta: activeTimelineEvent.value?.riskDelta, active: true },
  { key: 'volatility', label: '局势波动', value: currentGlobalRisk.value > 70 ? '高' : '中高', detail: activeTimelineEvent.value?.turning ? '关键拐点' : '趋势上升', tone: 'alert', delta: activeTimelineEvent.value?.turning ? 3 : 1, active: activeTimelineEvent.value?.turning },
  { key: 'events', label: '关键事件 (7日内)', value: String(timelineEvents.value.length || 12), detail: `${activeTimelineEvent.value?.title || '态势更新'}`, tone: 'neutral', active: true },
  { key: 'countries', label: '影响国家/地区', value: String(warRoom.value?.risk_heatmap?.length ? Math.max(37, warRoom.value.risk_heatmap.length) : 37), detail: activeCountryCodes.value.map(countryNameShort).join(' / '), tone: 'neutral', active: !!activeCountryCodes.value.length },
  { key: 'economy', label: '经济影响 (全球)', value: '-1.2%', detail: 'GDP 预期影响', tone: 'positive', delta: warRoomDiff.value?.global_risk_delta ? -Math.abs(Number(warRoomDiff.value.global_risk_delta) / 10) : null },
  { key: 'reaction', label: '连锁反应强度', value: currentGlobalRisk.value > 70 ? '强' : '中高', detail: '多米诺效应显著', tone: 'warning', active: activeTimelineEvent.value?.turning }
  ]
})
const factorControls = computed(() => [
  { key: 'influence', label: '美国介入力度', value: influenceFactor.value, model: influenceFactor },
  { key: 'retaliation', label: '中国反制强度', value: retaliationFactor.value, model: retaliationFactor },
  { key: 'supply', label: '日本响应程度', value: supplyFactor.value, model: supplyFactor },
  { key: 'pressure', label: '全球舆论压力', value: pressureFactor.value, model: pressureFactor }
])
const mapCountries = computed(() => {
  const uiCountries = uiMapEntities.value.filter(entity => entity.type === 'country')
  if (uiCountries.length) {
    return uiCountries.map((entity, index) => {
      const code = entity.key || entity.id?.replace('country:', '') || entity.country_code
      return {
        ...entity,
        code,
        country_code: code,
        country_name: entity.label_zh || countryNameShort(code),
        x: Number(entity.x ?? coordinateForCode(code, index).x),
        y: Number(entity.y ?? coordinateForCode(code, index).y),
        risk: Number(entity.risk || 0),
        dominant_channel: entity.dominant_channel,
        radius: 7 + Math.min(20, Number(entity.risk || 0) / 5),
        delta: countryDelta(code)
      }
    })
  }
  const riskRows = warRoom.value?.risk_heatmap?.length ? warRoom.value.risk_heatmap : [
    { country_code: 'CHN', country_name: '中国', risk: 82, dominant_channel: 'military' },
    { country_code: 'TWN', country_name: '台湾', risk: 88, dominant_channel: 'military' },
    { country_code: 'USA', country_name: '美国', risk: 64, dominant_channel: 'financial' },
    { country_code: 'JPN', country_name: '日本', risk: 62, dominant_channel: 'energy' },
    { country_code: 'EU', country_name: '欧盟', risk: 41, dominant_channel: 'trade' },
    { country_code: 'RUS', country_name: '俄罗斯', risk: 45, dominant_channel: 'energy' },
    { country_code: 'IND', country_name: '印度', risk: 38, dominant_channel: 'trade' },
    { country_code: 'SAU', country_name: '中东', risk: 36, dominant_channel: 'energy' },
    { country_code: 'BRA', country_name: '巴西', risk: 28, dominant_channel: 'food' }
  ]
  return riskRows.map((cell, index) => {
    const code = cell.country_code || cell.code
    const point = coordinateForCode(code, index)
    return { ...cell, code, x: point.x, y: point.y, risk: Number(cell.risk || 0), radius: 7 + Math.min(20, Number(cell.risk || 0) / 5), delta: countryDelta(code) }
  })
})
const supplyRoutes = computed(() => {
  const chains = warRoom.value?.supply_chains?.length ? warRoom.value.supply_chains : fallbackChains
  return chains.map((chain, index) => {
    const [startCode, endCode] = chainRouteEndpoints(chain, index)
    const start = coordinateForCode(startCode, index)
    const end = coordinateForCode(endCode, index + 2)
    return {
      key: chain.key,
      chain,
      start,
      end,
      mid: { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 },
      path: arcPath(start, end, index % 2 === 0 ? -1 : 1)
    }
  })
})
const mapCausalEdges = computed(() => {
  const uiEdges = uiMapEntities.value.filter(entity => entity.type === 'causal_edge')
  if (uiEdges.length) {
    return uiEdges.slice(0, 24).map((entity, index) => ({
      id: entity.id || `edge:${entity.source}->${entity.target}`,
      entity,
      edge: {
        source: entity.source,
        target: entity.target,
        relation: entity.label_zh,
        mechanism: entity.mechanism_zh,
        weight: entity.weight,
        lag_days: entity.lag_days,
        related_countries: entity.related_countries,
        related_chains: entity.related_chains
      },
      path: arcPath(coordinateForEntity(entity.source, index), coordinateForEntity(entity.target, index + 4), index % 2 === 0 ? 1 : -1, 0.18)
    }))
  }
  const edges = warRoom.value?.impact_graph?.edges || detail.value?.graph?.edges || []
  const fallback = edges.length ? edges : [
    { source: 'CHN', target: 'TWN', relation: '军事压力', mechanism: '区域军事活动推升风险' },
    { source: 'USA', target: 'TWN', relation: '战略支援', mechanism: '外部支援改变威慑结构' },
    { source: 'TWN', target: 'JPN', relation: '供应链外溢', mechanism: '芯片与航运压力传导' }
  ]
  return fallback.slice(0, 12).map((edge, index) => ({ id: `${edgeKey(edge)}-${index}`, edge, path: arcPath(coordinateForEntity(edge.source, index), coordinateForEntity(edge.target, index + 4), index % 2 === 0 ? 1 : -1, 0.18) }))
})
const mapEvents = computed(() => {
  const uiEvents = uiMapEntities.value.filter(entity => entity.type === 'event')
  if (uiEvents.length) {
    return uiEvents.map(entity => ({
      ...entity,
      key: entity.key || entity.id?.replace('event:', ''),
      label: entity.label_zh || entity.label,
      title: entity.title_zh || entity.title || entity.label_zh,
      detail: entity.detail_zh || entity.detail,
      relatedCountries: entity.related_countries || [],
      relatedChains: entity.related_chains || []
    }))
  }
  return [
    { key: 'taiwan', label: '台湾', title: '经济封锁加码', x: 586, y: 332, tone: 'red', day: 21, country_code: 'TWN', relatedCountries: ['TWN', 'CHN', 'JPN'] },
    { key: 'china', label: '中国', title: '军事演习升级', x: 531, y: 249, tone: 'blue', day: 3, country_code: 'CHN', relatedCountries: ['CHN', 'TWN', 'USA'] },
    { key: 'japan', label: '日本', title: '加强西南部署', x: 632, y: 230, tone: 'orange', day: 14, country_code: 'JPN', relatedCountries: ['JPN', 'TWN', 'USA'] },
    { key: 'us', label: '美国', title: '宣布对台警戒', x: 760, y: 236, tone: 'blue', day: 7, country_code: 'USA', relatedCountries: ['USA', 'TWN', 'CHN'] }
  ]
})
const timelineEvents = computed(() => {
  const uiEvents = Array.isArray(warRoomUi.value?.timeline_events) ? warRoomUi.value.timeline_events : []
  if (uiEvents.length) {
    return uiEvents.map((event, index) => ({
      key: event.key || `day-${event.day ?? index}`,
      day: Number(event.day || index),
      time: event.time || `D+${event.day ?? index}`,
      title: event.title_zh || event.title || '态势更新',
      detail: event.detail_zh || event.detail || '',
      tone: event.tone || (event.turning_point ? 'red' : 'blue'),
      position: Number(event.position ?? Math.min(95, index / Math.max(1, uiEvents.length - 1) * 100)),
      globalRisk: normalizeRiskValue(event.global_risk ?? averageRisk()),
      riskDelta: Number(event.global_risk_delta || 0),
      turning: !!event.turning_point,
      eventKeys: event.event_keys || event.eventKeys || [],
      relatedCountries: event.related_countries || event.relatedCountries || [],
      relatedChains: event.related_chains || event.relatedChains || []
    }))
  }
  const timeline = warRoom.value?.timeline || []
  if (!timeline.length) {
    return [
      { key: 'e1', day: 0, time: 'D+0', title: '美国宣布对台警戒', detail: '扩大对台军事支援范围', tone: 'red', position: 6, globalRisk: 68, riskDelta: 0, turning: false, eventKeys: ['us'], relatedCountries: ['USA', 'TWN'] },
      { key: 'e2', day: 3, time: 'D+3', title: '中国军演升级', detail: '多军兵种联合演习', tone: 'blue', position: 24, globalRisk: 72, riskDelta: 4, turning: true, eventKeys: ['china'], relatedCountries: ['CHN', 'TWN'] },
      { key: 'e3', day: 7, time: 'D+7', title: '外交紧急磋商', detail: '联合国安理会紧急会议', tone: 'green', position: 42, globalRisk: 70, riskDelta: -2, turning: false, eventKeys: ['us', 'japan'], relatedCountries: ['USA', 'EU', 'JPN'] },
      { key: 'e4', day: 14, time: 'D+14', title: '日本加强西南部署', detail: '自卫队警戒级别提升', tone: 'orange', position: 64, globalRisk: 76, riskDelta: 6, turning: true, eventKeys: ['japan'], relatedCountries: ['JPN', 'TWN', 'USA'] },
      { key: 'e5', day: 21, time: 'D+21', title: '经济封锁加码', detail: '多国扩大对华出口限制', tone: 'red', position: 82, globalRisk: 81, riskDelta: 5, turning: true, eventKeys: ['taiwan'], relatedCountries: ['TWN', 'CHN', 'USA'] },
      { key: 'e6', day: 30, time: 'D+30', title: '二阶压力扩散', detail: '金融结算与供应链替代压力进入复盘窗口', tone: 'red', position: 95, globalRisk: 78, riskDelta: -3, turning: true, eventKeys: ['taiwan', 'china'], relatedCountries: ['CHN', 'TWN', 'JPN'] }
    ]
  }
  return timeline.slice(0, 6).map((point, index) => ({
    key: `day-${point.day}`,
    day: Number(point.day || index),
    time: `D+${point.day}`,
    title: point.turning_point ? '关键拐点' : '态势更新',
    detail: localizeText(point.key_development),
    tone: point.turning_point ? 'red' : index % 2 ? 'green' : 'blue',
    position: Math.min(95, (index / Math.max(1, Math.min(6, timeline.length) - 1)) * 100),
    globalRisk: normalizeRiskValue(point.global_risk ?? averageRisk()),
    riskDelta: index ? normalizeRiskValue(point.global_risk || 0) - normalizeRiskValue(timeline[index - 1]?.global_risk || 0) : 0,
    turning: !!point.turning_point,
    eventKeys: eventKeysForTimelineIndex(index),
    relatedCountries: countriesForTimelineIndex(index)
  }))
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
const markdownUrl = computed(() => URL.createObjectURL(new Blob([detail.value?.report?.markdown || ''], { type: 'text/markdown;charset=utf-8' })))
const replayPackUrl = computed(() => URL.createObjectURL(new Blob([replayPack.value?.markdown || ''], { type: 'text/markdown;charset=utf-8' })))
const replayPackJsonUrl = computed(() => URL.createObjectURL(new Blob([replayPack.value?.artifacts?.json_manifest || '{}'], { type: 'application/json;charset=utf-8' })))
const replayPackFilename = computed(() => `${String(detail.value?.project?.title || 'worldpulse').toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${replayPack.value?.run_id || 'war-room'}-replay-pack.md`)
const replayPackJsonFilename = computed(() => replayPackFilename.value.replace(/\.md$/, '-manifest.json'))
const markdownPreview = computed(() => (replayPack.value?.markdown || '').slice(0, 6000))

function chainName(key, fallback = '') { return chainLabels[key] || fallback || key || '--' }
function riskChannel(key) { return channelLabels[key] || key || '--' }
function scenarioLabel(scenario) { return scenario ? scenarioLabels[scenario.key || scenario.scenario_key] || scenario.name || scenario.key : '' }
function policyActionLabel(key) { return policyActions.find(item => item.key === key)?.label || key }
function decisionStatus(status) { return decisionLabels[status] || status || '--' }
function countryNameShort(code) { return countryNames[code] || code }
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
  mapZoom.value = Math.max(0.78, Math.min(1.42, Number((mapZoom.value + delta).toFixed(2))))
  showToast(`地图缩放 ${Math.round(mapZoom.value * 100)}%`)
}
function resetMapView() {
  mapZoom.value = 1
  selectedMapEntity.value = null
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
function layerLabel(key) { return mapLayerButtons.value.find(item => item.key === key)?.label || key }
function layerActive(key) { return visibleMapLayers.value.includes(key) }
function toggleMapLayer(key) {
  visibleMapLayers.value = layerActive(key) ? visibleMapLayers.value.filter(item => item !== key) : [...visibleMapLayers.value, key]
  showToast(`${layerLabel(key)}${layerActive(key) ? '已显示' : '已隐藏'}`)
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
function eventKeysForTimelineIndex(index) {
  const keys = ['us', 'china', 'us', 'japan', 'taiwan', 'taiwan']
  return [keys[index % keys.length]].filter(Boolean)
}
function countriesForTimelineIndex(index) {
  const presets = [
    ['USA', 'TWN'],
    ['CHN', 'TWN'],
    ['USA', 'EU', 'JPN'],
    ['JPN', 'TWN', 'USA'],
    ['TWN', 'CHN', 'USA'],
    ['CHN', 'TWN', 'JPN']
  ]
  return presets[index % presets.length]
}
function relatedEventLabels(countryCode) {
  const labels = timelineEvents.value
    .filter(event => event.relatedCountries?.includes(countryCode))
    .slice(0, 3)
    .map(event => `${event.time} ${event.title}`)
  return labels.length ? labels : [`D+${activeReplayDay.value} ${activeTimelineEvent.value?.title || '态势更新'}`]
}
function selectReplayDay(day) {
  const target = timelineEvents.value.findIndex(event => Number(event.day) >= Number(day))
  activeReplayIndex.value = target >= 0 ? target : Math.max(0, timelineEvents.value.length - 1)
  replayPlaying.value = false
  showToast(`已切换到 D+${day} 阶段`)
}
function toggleReplay() { replayPlaying.value = !replayPlaying.value }
function cycleReplaySpeed() {
  replaySpeed.value = replaySpeed.value === 1 ? 2 : replaySpeed.value === 2 ? 4 : 1
  if (replayPlaying.value) restartReplayTimer()
}
function advanceReplay() {
  if (!timelineEvents.value.length) return
  activeReplayIndex.value = (activeReplayIndex.value + 1) % timelineEvents.value.length
  selectedMapEntity.value = null
}
function stopReplayTimer() {
  if (replayTimer) {
    window.clearInterval(replayTimer)
    replayTimer = null
  }
}
function restartReplayTimer() {
  stopReplayTimer()
  if (!replayPlaying.value) return
  replayTimer = window.setInterval(advanceReplay, Math.max(650, 1800 / replaySpeed.value))
}
function coordinateForCode(code, index = 0) {
  const normalized = String(code || '').toUpperCase()
  if (countryCoordinates[normalized]) return countryCoordinates[normalized]
  const angle = (index / 10) * Math.PI * 2
  return { x: 500 + Math.cos(angle) * 260, y: 280 + Math.sin(angle) * 150 }
}
function coordinateForEntity(entity, index = 0) {
  const raw = typeof entity === 'object' ? entity.id || entity.code || entity.key || entity.label : entity
  const value = String(raw || '').toUpperCase()
  const countryCode = Object.keys(countryCoordinates).find(code => value.includes(code))
  if (countryCode) return countryCoordinates[countryCode]
  return coordinateForCode('', index)
}
function chainRouteEndpoints(chain, index = 0) {
  const affected = (chain.affected_countries || chain.affected_country_codes || []).filter(Boolean)
  const defaults = chainAnchors[chain.key] || ['USA', 'CHN']
  return [affected[0] || defaults[0], affected[affected.length - 1] || defaults[1] || defaults[0]]
}
function arcPath(start, end, direction = 1, lift = 0.28) {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const mx = (start.x + end.x) / 2
  const my = (start.y + end.y) / 2
  return `M ${start.x} ${start.y} Q ${mx - dy * lift * direction} ${my + dx * lift * direction} ${end.x} ${end.y}`
}
function riskColor(value) {
  const risk = Number(value || 0)
  if (risk >= 72) return '#ff4d5f'
  if (risk >= 52) return '#f59e32'
  if (risk >= 35) return '#36a7ff'
  return '#21d69b'
}
function riskOpacity(value) { return Math.min(0.86, Math.max(0.18, Number(value || 0) / 100)) }
function selectAllCountries() {
  scenarioDraft.target_countries = countryOptions.value.map(item => item.code || item.country_code).filter(Boolean).slice(0, 10)
  showToast('已添加全部国家 Agent 可变因素')
}
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
      await runLifecycle.create({ engine_mode: 'deterministic', scenario: scenarioPayload(), seed: scenarioDraft.seed || 42 })
      showToast('生命周期任务已排队；请启动或保持 worker 运行')
      return
    }
    detail.value = await runProject(props.projectId, runMode.value)
    selectedRunId.value = detail.value?.latest_run?.run_id || ''
    await loadWorkspaceState(selectedRunId.value)
    replayPack.value = null
    replayPreviewOpen.value = false
    syncScenarioDraft()
    prepareCompareDefaults(true)
    await loadRunDiff()
    await nextTick()
    renderGraph()
  } finally {
    running.value = false
  }
}

async function pauseLifecycleRun() {
  await runLifecycle.pause()
  showToast('暂停请求已写入生命周期状态')
}

async function resumeLifecycleRun() {
  await runLifecycle.resume()
  showToast('生命周期任务已恢复排队')
}

async function cancelLifecycleRun() {
  await runLifecycle.cancel()
  showToast('取消请求已写入生命周期状态')
}

async function retryLifecycleRun() {
  await runLifecycle.retry()
  showToast('已创建 retry 生命周期任务')
}
async function loadRunDiff() {
  if (!isWarRoom.value || !compareBaseRunId.value || !compareTargetRunId.value || compareBaseRunId.value === compareTargetRunId.value) {
    runDiff.value = null
    return
  }
  runDiffLoading.value = true
  try {
    runDiff.value = await warRoomData.compareRuns(compareBaseRunId.value, compareTargetRunId.value)
  } finally {
    runDiffLoading.value = false
  }
}
async function exportReplayPack() {
  if (!isWarRoom.value || !detail.value?.latest_run) return
  replayPackLoading.value = true
  try {
    const params = warRoomDiff.value ? { base_run_id: compareBaseRunId.value, target_run_id: compareTargetRunId.value } : { run_id: selectedRunId.value || detail.value.latest_run.run_id }
    replayPack.value = await warRoomData.exportReplayPack(params)
    replayPreviewOpen.value = true
  } finally {
    replayPackLoading.value = false
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
function syncScenarioDraft() {
  const config = detail.value?.latest_run?.data_snapshot?.scenario_config || detail.value?.project?.scenario_config || {}
  Object.assign(scenarioDraft, {
    scenario_key: config.scenario_key || config.key || scenarioDraft.scenario_key,
    duration_days: Number(config.duration_days || scenarioDraft.duration_days),
    intensity: Number(config.intensity ?? scenarioDraft.intensity),
    propagation: Number(config.propagation ?? scenarioDraft.propagation),
    target_countries: [...(config.target_countries || scenarioDraft.target_countries || [])],
    target_chains: [...(config.target_chains || scenarioDraft.target_chains || [])],
    policy_actions: [...(config.policy_actions || scenarioDraft.policy_actions || [])],
    country_overrides: { ...scenarioDraft.country_overrides, ...(config.country_overrides || {}) },
    chain_overrides: { ...scenarioDraft.chain_overrides, ...(config.chain_overrides || {}) }
  })
}
function scenarioPayload() { return JSON.parse(JSON.stringify(scenarioDraft)) }
function prepareCompareDefaults(forceLatest = false) {
  if (!isWarRoom.value || runVersions.value.length < 2) return
  const runs = [...runVersions.value]
  const latest = selectedRunId.value || runs[0]?.run_id
  const previous = runs.find(run => run.run_id !== latest)?.run_id
  if (forceLatest || !compareTargetRunId.value) compareTargetRunId.value = latest
  if (forceLatest || !compareBaseRunId.value || compareBaseRunId.value === compareTargetRunId.value) compareBaseRunId.value = previous || ''
}
function toggleDraftList(field, value) {
  const list = scenarioDraft[field]
  scenarioDraft[field] = list.includes(value) ? list.filter(item => item !== value) : [...list, value]
  if (field === 'policy_actions') showToast(`${policyActionLabel(value)}${scenarioDraft[field].includes(value) ? '已启用' : '已移除'}`)
}
function clearPolicyActions() {
  scenarioDraft.policy_actions = []
  showToast('触发条件已重置')
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
function applySelectedScenarioDefaults() {
  const scenario = presets.value?.scenarios?.find(item => item.key === scenarioDraft.scenario_key)
  if (!scenario) return
  scenarioDraft.duration_days = Number(scenario.duration_days || scenarioDraft.duration_days)
  scenarioDraft.target_countries = [...(scenario.target_countries || [])]
  scenarioDraft.target_chains = [...(scenario.target_chains || [])]
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

async function copyRunId() {
  const runId = selectedRunId.value || detail.value?.latest_run?.run_id
  if (!runId) {
    showToast('当前没有可复制的运行 ID')
    return
  }
  try {
    await navigator.clipboard.writeText(runId)
  } catch {
    const input = document.createElement('textarea')
    input.value = runId
    input.style.position = 'fixed'
    input.style.opacity = '0'
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    input.remove()
  }
  showToast('运行 ID 已复制')
}

function downloadUiState() {
  const runId = selectedRunId.value || detail.value?.latest_run?.run_id
  if (!runId) {
    showToast('请先运行一次沙盘')
    return
  }
  const payload = JSON.stringify({
    project_id: props.projectId,
    run_id: runId,
    ui_state: warRoomUi.value,
    disclaimer: warRoom.value?.disclaimer || workspaceState.value?.disclaimer
  }, null, 2)
  const url = URL.createObjectURL(new Blob([payload], { type: 'application/json;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `worldpulse_${props.projectId}_${runId}_ui_state.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  showToast('ui_state.json 已生成')
}

watch(() => detail.value?.graph?.graph_id, () => nextTick(renderGraph))
watch(() => activeLifecycleRun.value?.status, async (status, previous) => {
  const job = activeLifecycleRun.value
  if (status === 'completed' && previous !== 'completed' && job?.result_run_id) {
    await load(job.result_run_id)
    showToast('生命周期任务已完成，workspace 已刷新')
  }
})
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
watch(replayPlaying, restartReplayTimer)
watch(replaySpeed, () => {
  if (replayPlaying.value) restartReplayTimer()
})
watch(() => timelineEvents.value.length, length => {
  if (!length) {
    activeReplayIndex.value = 0
    replayPlaying.value = false
    return
  }
  if (activeReplayIndex.value >= length) activeReplayIndex.value = length - 1
})
onMounted(load)
onUnmounted(() => {
  stopReplayTimer()
  runLifecycle.stop()
  if (toastTimer) window.clearTimeout(toastTimer)
})
</script>
