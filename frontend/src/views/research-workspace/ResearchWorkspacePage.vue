<template>
  <main v-if="detail" :class="['workspace', { 'war-room-page': isWarRoom }]">
    <template v-if="isWarRoom">
      <section class="war-room-command-shell">
        <WarRoomTopNav
          :active-section="activeSection"
          :section-path="sectionPath"
          :top-sections="topSections"
          :notification-count="continuousIntelligence.unreadCount.value"
          @open-command-search="commandSearchOpen = true"
          @open-notifications="notificationDrawerOpen = true"
          @show-upcoming="showUpcoming"
        />

        <WarRoomLifecycleRail :stages="lifecycleStages" />

        <section v-if="activeSection === 'overview' && negotiation.detail.value" class="overview-trust-strip" data-testid="overview-negotiation-summary">
          <article><span>协商 Tick</span><strong>{{ negotiation.summary.value.currentTick }}/6</strong></article>
          <article><span>受控 Agent</span><strong>{{ negotiation.summary.value.agentCount }}/12</strong></article>
          <article><span>有效承诺</span><strong>{{ negotiation.summary.value.activeCommitments }}</strong></article>
          <article><span>结构化消息</span><strong>{{ negotiation.summary.value.messageCount }}</strong></article>
        </section>

        <section v-if="activeSection === 'overview' && trustSummary" class="overview-trust-strip" data-testid="overview-trust-summary">
          <article><span>当前规则版本</span><strong>{{ trustSummary.rule_pack?.version || '--' }}</strong></article>
          <article><span>校准状态</span><strong>{{ trustSummary.calibration_status }}</strong></article>
          <article><span>待复核数量</span><strong>{{ trustSummary.pending_review_count }}</strong></article>
          <article><span>正式报告</span><strong :class="trustSummary.report_allowed ? 'passed' : 'blocked'">{{ trustSummary.report_allowed ? '允许' : '禁止' }}</strong></article>
        </section>

        <section v-if="activeSection === 'overview'" class="overview-trust-strip" data-testid="overview-compiler-summary">
          <article><span>版本化材料</span><strong>{{ scenarioCompiler.summary.value.documentCount }}</strong></article>
          <article><span>待确认候选</span><strong>{{ scenarioCompiler.summary.value.pendingCandidateCount }}</strong></article>
          <article><span>待审批草稿</span><strong>{{ scenarioCompiler.summary.value.pendingDraftCount }}</strong></article>
          <article><span>最新批准草稿</span><strong>{{ scenarioCompiler.summary.value.latestApproved ? `v${scenarioCompiler.summary.value.latestApproved.version}` : '--' }}</strong></article>
        </section>

        <section v-if="activeSection === 'overview'" class="overview-trust-strip" data-testid="overview-intelligence-summary">
          <article><span>活跃情报源</span><strong>{{ continuousIntelligence.summary.value?.active_sources ?? 0 }}</strong></article>
          <article><span>开放告警</span><strong>{{ continuousIntelligence.summary.value?.open_alerts ?? 0 }}</strong></article>
          <article><span>高等级告警</span><strong>{{ continuousIntelligence.summary.value?.high_alerts ?? 0 }}</strong></article>
          <article><span>未读通知</span><strong>{{ continuousIntelligence.unreadCount.value }}</strong></article>
        </section>

        <WarRoomOverviewConsole
          v-if="activeSection === 'overview'"
          :active-agents="lifecycleAgentStatus"
          :active-replay-day="activeReplayDay"
          :causal-edges="mapCausalEdges"
          :control="lifecycleControlForRole"
          :countries="mapCountries"
          :current-replay-time="currentReplayTime"
          :events="mapEvents"
          :image-src="worldMapCommand"
          :consistency-audit="consistencyAudit"
          :hybrid-trace="hybridTrace"
          :hybrid-view-mode="hybridViewMode"
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
          @set-hybrid-view="hybridViewMode = $event"
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
            :runtime-audit="lifecycleAudit?.agent_runtime"
            :consistency-audit="consistencyAudit"
          />

          <WarRoomNegotiationModule
            v-else-if="activeSection === 'negotiation'"
            :detail="negotiation.detail.value"
            :rounds="negotiation.rounds.value"
            :messages="negotiation.messages.value"
            :commitments="negotiation.commitments.value"
            :summary="negotiation.summary.value"
            :loading="negotiation.loading.value"
            :error="negotiation.error.value"
          />

          <WarRoomEvaluationModule
            v-else-if="activeSection === 'evaluation'"
            :suite="evaluation.suites.value[0]"
            :benchmark-suites="evaluation.benchmarkSuites.value"
            :label-packs="evaluation.labelPacks.value"
            :batches-by-tab="evaluation.tabs.value"
            :latest="evaluation.latest.value"
            :report="evaluation.report.value"
            :historical-report="evaluation.historicalReport.value"
            :members="evaluation.members.value"
            :verification="evaluation.verification.value"
            :loading="evaluation.loading.value"
            :error="evaluation.error.value"
            @create-standard="createEvaluationStandard"
            @create-historical="createEvaluationHistorical"
            @inspect="inspectEvaluation"
            @control="controlEvaluationBatch"
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
            :on-open-run-details="() => { runDetailsDrawer = true }"
            :on-set-active-data-tab="value => activeDataTab = value"
            :risk-channel="riskChannel"
            :selected-run-id="selectedRunId"
            :short-run-id="shortRunId"
            :signed="signed"
            :timeline-events="timelineEvents"
            :ui-map-entities="uiMapEntities"
            :war-room="warRoom"
            :lifecycle-audit="lifecycleAudit"
          />

          <WarRoomSettingsModule
            v-else-if="activeSection === 'settings'"
            :engine-mode="lifecycleEngineMode"
            :layer-label="layerLabel"
            :on-engine-mode-change="value => lifecycleEngineMode = value"
            :visible-map-layers="visibleMapLayers"
            :runtime-audit="lifecycleAudit?.agent_runtime"
            :lifecycle-audit="lifecycleAudit"
          />

          <WarRoomReplayModule
            v-else-if="activeSection === 'replay'"
            :replay-pack="replayPack"
            :selected-run-id="selectedRunId"
            :war-room-diff="warRoomDiff"
          />

          <WarRoomTrustCenter
            v-else-if="activeSection === 'trust'"
            :summary="trustSummary"
            :loading="trustLoading"
            :error="trustError"
            :can-review="auth.permissions.value.canReview"
            :can-calibrate="auth.permissions.value.canCalibrate"
            @refresh="loadTrustSummary"
            @calibrate="startTrustCalibration"
            @decision="submitReviewDecision"
          />

          <WarRoomEvidenceCenter
            v-else-if="activeSection === 'evidence'"
            :summary="evidenceRegistry.summary.value"
            :search-result="evidenceRegistry.searchResult.value"
            :loading="evidenceRegistry.loading.value"
            :searching="evidenceRegistry.searching.value"
            :error="evidenceRegistry.error.value"
            :can-write="auth.permissions.value.canWrite"
            @refresh="loadEvidenceSummary"
            @sync="syncEvidence"
            @create-pack="freezeEvidencePack"
            @search="searchProjectEvidence"
          />

          <WarRoomIngestionCenter
            v-else-if="activeSection === 'ingestion'"
            :organization="ingestionGovernance.organization.value"
            :members="ingestionGovernance.members.value"
            :summary="ingestionGovernance.summary.value"
            :events="ingestionGovernance.selectedEvents.value"
            :loading="ingestionGovernance.loading.value"
            :error="ingestionGovernance.error.value"
            :can-write="auth.permissions.value.canWrite"
            @refresh="loadIngestionGovernance"
            @create-connector="createGovernedConnector"
            @ingest="submitGovernedIngestion"
            @events="inspectIngestionEvents"
            @cancel="cancelIngestion"
            @retry="retryIngestion"
          />

          <WarRoomIntelligenceModule
            v-else-if="activeSection === 'intelligence'"
            :summary="continuousIntelligence.summary.value"
            :sources="continuousIntelligence.sources.value"
            :watchlists="continuousIntelligence.watchlists.value"
            :alerts="continuousIntelligence.alerts.value"
            :loading="continuousIntelligence.loading.value"
            :error="continuousIntelligence.error.value"
            :can-write="auth.permissions.value.canWrite"
            @refresh="loadContinuousIntelligence"
            @create-source="createContinuousSource"
            @poll="pollContinuousSource"
            @source-status="setContinuousSourceStatus"
            @create-watchlist="createContinuousWatchlist"
            @watchlist-status="setContinuousWatchlistStatus"
            @alert-status="setContinuousAlertStatus"
          />

          <WarRoomScenarioCompiler
            v-else-if="activeSection === 'compiler'"
            :organization="scenarioCompiler.organization.value"
            :documents="scenarioCompiler.documents.value"
            :jobs="scenarioCompiler.jobs.value"
            :candidates="scenarioCompiler.candidates.value"
            :drafts="scenarioCompiler.drafts.value"
            :events="scenarioCompiler.selectedEvents.value"
            :last-run="scenarioCompiler.lastRun.value"
            :loading="scenarioCompiler.loading.value"
            :error="scenarioCompiler.error.value"
            :can-write="auth.permissions.value.canWrite"
            :can-review="auth.permissions.value.canReview"
            @refresh="loadScenarioCompiler"
            @upload="uploadScenarioDocument"
            @extract="extractScenarioDocument"
            @events="inspectScenarioExtractionEvents"
            @cancel="cancelScenarioExtraction"
            @retry="retryScenarioExtraction"
            @decision="decideScenarioCandidate"
            @create-draft="createCompiledScenarioDraft"
            @submit-draft="submitCompiledScenarioDraft"
            @review-draft="reviewCompiledScenarioDraft"
            @clone-draft="cloneCompiledScenarioDraft"
            @run-draft="runCompiledScenarioDraft"
          />

          <WarRoomOperationsCenter
            v-else-if="activeSection === 'operations'"
            :summary="operationsCenter.summary.value"
            :loading="operationsCenter.loading.value"
            :error="operationsCenter.error.value"
            :can-operate="auth.permissions.value.canOperate"
            @refresh="loadOperationsCenter"
            @save-quota="saveOperationsQuota"
            @drain="drainOperationsWorker"
          />

        </section>
      </section>

      <WarRoomWorkspaceOverlays
        :toast-message="toastMessage"
        :command-search-open="commandSearchOpen"
        :command-query="commandQuery"
        :command-search-results="commandSearchResults"
        :entity-type-label="entityTypeLabel"
        :entity-detail="entityDetailDrawer"
        :run-details-open="runDetailsDrawer"
        :lifecycle-audit="lifecycleAudit"
        :selected-run-id="selectedRunId"
        :notification-open="notificationDrawerOpen"
        :continuous-intelligence="continuousIntelligence"
        :upcoming-feature="upcomingFeature"
        :decision-drawer="decisionDrawer"
        @close-command="commandSearchOpen = false"
        @update-query="commandQuery = $event"
        @activate-command="activateCommandResult"
        @close-entity="entityDetailDrawer = null"
        @entity-action="handleEntityAction"
        @close-run="runDetailsDrawer = false"
        @close-notifications="notificationDrawerOpen = false"
        @open-intelligence="navigateSection('intelligence'); notificationDrawerOpen = false"
        @close-upcoming="upcomingFeature = null"
        @close-decision="decisionDrawer = null"
      />

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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Activity,
  BarChart3,
  BookOpen,
  Cable,
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
  ServerCog,
  ScanText,
  Settings,
  ShieldAlert,
  ShieldCheck,
  UsersRound,
  X
} from 'lucide-vue-next'
import worldMapCommand from '../../assets/war-room/world-map-command.png'
import WarRoomAnalysisModule from '../../components/war-room/WarRoomAnalysisModule.vue'
import WarRoomDataModule from '../../components/war-room/WarRoomDataModule.vue'
import WarRoomGraphModule from '../../components/war-room/WarRoomGraphModule.vue'
import WarRoomLifecycleRail from '../../components/war-room/WarRoomLifecycleRail.vue'
import WarRoomOverviewConsole from '../../components/war-room/WarRoomOverviewConsole.vue'
import WarRoomReplayModule from '../../components/war-room/WarRoomReplayModule.vue'
import WarRoomSandboxModule from '../../components/war-room/WarRoomSandboxModule.vue'
import WarRoomSettingsModule from '../../components/war-room/WarRoomSettingsModule.vue'
import WarRoomTrustCenter from '../../components/war-room/WarRoomTrustCenter.vue'
import WarRoomEvidenceCenter from '../../components/war-room/WarRoomEvidenceCenter.vue'
import WarRoomIngestionCenter from '../../components/war-room/WarRoomIngestionCenter.vue'
import WarRoomIntelligenceModule from '../../components/war-room/WarRoomIntelligenceModule.vue'
import WarRoomOperationsCenter from '../../components/war-room/WarRoomOperationsCenter.vue'
import WarRoomNegotiationModule from '../../components/war-room/WarRoomNegotiationModule.vue'
import WarRoomEvaluationModule from '../../components/war-room/WarRoomEvaluationModule.vue'
import WarRoomScenarioCompiler from '../../components/war-room/WarRoomScenarioCompiler.vue'
import WarRoomTopNav from '../../components/war-room/WarRoomTopNav.vue'
import WarRoomWorkspaceOverlays from '../../components/war-room/WarRoomWorkspaceOverlays.vue'
import { useRunLifecycle } from '../../composables/useRunLifecycle'
import { useRunLifecycleConsole } from '../../composables/useRunLifecycleConsole'
import { useWarRoomArtifacts } from '../../composables/useWarRoomArtifacts'
import { useWarRoomData } from '../../composables/useWarRoomData'
import { useWarRoomMapProjection } from '../../composables/useWarRoomMapProjection'
import { useWarRoomReplayControls } from '../../composables/useWarRoomReplayControls'
import { useWarRoomScenarioDraft } from '../../composables/useWarRoomScenarioDraft'
import { useAuthSession } from '../../composables/useAuthSession'
import { useNegotiation } from '../../composables/useNegotiation'
import { useWarRoomGraphRenderer } from '../../composables/useWarRoomGraphRenderer'
import { useWarRoomInteractions } from '../../composables/useWarRoomInteractions'
import { useWorkspaceGovernanceController } from '../../composables/useWorkspaceGovernanceController'
import { useWorkspaceRunController } from '../../composables/useWorkspaceRunController'
import { useWorkspaceShell } from '../../composables/useWorkspaceShell'
import { decisionLabels, eventFilterOptions, graphTypeOptions, localizedText, prompts } from './warRoomWorkspaceConfig'

const props = defineProps({ projectId: String, section: String })
const {
  router,
  sectionKeys,
  sectionMeta,
  topSections,
  railSections,
  activeSection,
  activeSectionMeta,
  upcomingFeature,
  toastMessage,
  decisionDrawer,
  entityDetailDrawer,
  runDetailsDrawer,
  commandSearchOpen,
  notificationDrawerOpen,
  commandQuery,
  sectionPath,
  navigateSection,
  showToast,
  showUpcoming,
  disposeShell,
} = useWorkspaceShell({ projectId: () => props.projectId, section: () => props.section })
const warRoomData = useWarRoomData(() => props.projectId)
const runLifecycle = useRunLifecycle(() => props.projectId)
const auth = useAuthSession()
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
const hybridViewMode = ref('hybrid')
const selectedRunId = ref('')
const evidenceDrawer = ref(null)
const focusedEdgeKey = ref('')
const presets = ref(null)
const comparePanelEl = ref(null)
const reportPanelEl = ref(null)
const showDeltaOverlay = ref(false)
const focusedEntityId = ref('')
const focusedGraphEdgeId = ref('')
const activeDataTab = ref('tables')
const analysisFilter = ref('')
const graphTypeFilters = ref([])
const shortRunId = (runId) => {
  const text = String(runId || '')
  return text ? text.replace(/^run_/, '#').slice(0, 13) : ''
}

const isWarRoom = computed(() => detail.value?.project?.mode === 'war_room')
const {
  evidenceRegistry,
  ingestionGovernance,
  continuousIntelligence,
  operationsCenter,
  scenarioCompiler,
  evaluation,
  trustSummary,
  trustLoading,
  trustError,
  loadTrustSummary,
  loadEvaluationCenter,
  createEvaluationStandard,
  createEvaluationHistorical,
  inspectEvaluation,
  controlEvaluationBatch,
  loadEvidenceSummary,
  syncEvidence,
  freezeEvidencePack,
  searchProjectEvidence,
  loadIngestionGovernance,
  createGovernedConnector,
  submitGovernedIngestion,
  inspectIngestionEvents,
  cancelIngestion,
  retryIngestion,
  loadContinuousIntelligence,
  createContinuousSource,
  pollContinuousSource,
  setContinuousSourceStatus,
  createContinuousWatchlist,
  setContinuousWatchlistStatus,
  setContinuousAlertStatus,
  loadOperationsCenter,
  saveOperationsQuota,
  drainOperationsWorker,
  loadScenarioCompiler,
  uploadScenarioDocument,
  extractScenarioDocument,
  inspectScenarioExtractionEvents,
  cancelScenarioExtraction,
  retryScenarioExtraction,
  decideScenarioCandidate,
  createCompiledScenarioDraft,
  submitCompiledScenarioDraft,
  reviewCompiledScenarioDraft,
  cloneCompiledScenarioDraft,
  runCompiledScenarioDraft,
  startTrustCalibration,
  submitReviewDecision,
} = useWorkspaceGovernanceController({
  projectId: () => props.projectId,
  isWarRoom,
  selectedRunId,
  showToast,
})
const runVersions = computed(() => detail.value?.runs || [])
const workflowEvents = computed(() => detail.value?.latest_run?.data_snapshot?.workflow_events || [])
const persistedWarRoom = computed(() => detail.value?.latest_run?.simulation_snapshot || detail.value?.latest_run?.data_snapshot?.war_room || null)
const lifecycleAudit = computed(() => runLifecycle.audit.value)
const warRoom = computed(() => hybridViewMode.value === 'baseline'
  ? (lifecycleAudit.value?.hybrid?.baseline_result || persistedWarRoom.value)
  : persistedWarRoom.value)
const warRoomUi = computed(() => hybridViewMode.value === 'baseline'
  ? (warRoom.value?.ui_state || {})
  : (workspaceState.value?.ui_state || warRoom.value?.ui_state || {}))
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
let reloadWorkspace = async () => {}
const {
  activeLifecycleRun,
  consistencyAudit,
  hybridTrace,
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
} = useRunLifecycleConsole({ runLifecycle, lifecycleProjection, runVersions, running, showToast, onCompleted: (...args) => reloadWorkspace(...args) })
const lifecycleControlForRole = computed(() => auth.permissions.value.canRun ? lifecycleControl.value : {
  ...lifecycleControl.value,
  busy: true,
  canPause: false,
  canCancel: false,
  canResume: false,
  canRetry: false,
  disclaimer: '当前账户为只读/审阅角色；运行控制由后端 RBAC 禁止。',
})
const negotiationRunId = computed(() => {
  if (activeLifecycleRun.value?.engine_mode === 'negotiation' && Number(activeLifecycleRun.value?.progress || 0) >= 74) return activeLifecycleRun.value.run_id
  const latest = detail.value?.latest_run?.data_snapshot || {}
  return latest.trust_manifest?.agent_pack_id ? latest.lifecycle_job_id : ''
})
const negotiation = useNegotiation(() => negotiationRunId.value)
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
  lifecycle_audit: lifecycleAudit.value,
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
const {
  fullEntityId, detailForSelectedEntity, openEntityDetail, mapTooltipFor,
  activateCommandResult, handleEntityAction, cloneFromCurrentRun,
  openCompareShortcut, openReplayShortcut, toggleDeltaOverlay, toggleEventFilter,
  eventMatchesFilters, eventVisible, setAnalysisCountry, entityActive,
  entityTypeLabel, isCountryHot, relatedEventLabels, riskColor, riskOpacity,
  goDeepAnalysis, openEntityAnalysis, openDecisionDrawer, selectMapCountry,
  selectSupplyChain, selectCausalEdge, selectMilitaryUnit, selectMapEvent,
  selectTimelineEvent,
} = useWarRoomInteractions({
  selectedMapEntity, entityDetails, entityDetailDrawer, activeReplayDay, mapZoom,
  replayPlaying, selected, countryNameShort, riskChannel, chainName,
  focusedGraphEdgeId, focusedEdgeKey, edgeKey, edgeLabel, timelineEvents,
  activeReplayIndex, currentGlobalRisk, commandSearchOpen, commandQuery,
  mapCountries, warRoom, mapEvents, mapCausalEdges, navigateSection,
  activeSection, sectionMeta, showToast, syncScenarioDraft, lifecycleControl,
  runControl, loadRunDiff, comparePanelEl, exportReplayPack, showDeltaOverlay,
  eventFilters, focusedEntityId, activeCountryCodes, activeTimelineEvent,
  activeAgent, decisionDrawer, localizeText,
})

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
const { renderGraph, renderSectionGraph, stopGraphs } = useWarRoomGraphRenderer({
  detail,
  graphEl,
  sectionGraphEl,
  selected,
  focusedEdgeKey,
  filteredGraphEdges,
  focusedGraphEdgeId,
  edgeKey,
  edgeLabel,
  graphEntityType,
  focusGraphEdge,
})
const { load, loadWorkspaceState, loadPresets, run, send } = useWorkspaceRunController({
  projectId: () => props.projectId,
  detail, selectedRunId, workspaceState, isWarRoom, warRoomData, presets,
  scenarioDraft, syncScenarioDraft, prepareCompareDefaults, loadRunDiff,
  loadTrustSummary, loadEvidenceSummary, loadIngestionGovernance,
  loadContinuousIntelligence, loadScenarioCompiler, loadOperationsCenter,
  activeSection, negotiation, loadEvaluationCenter, renderGraph, auth, running,
  runLifecycle, lifecycleEngineMode, scenarioPayload, runMode,
  resetReplayArtifacts, showToast, chatting, message,
})
reloadWorkspace = load

watch(() => detail.value?.graph?.graph_id, () => nextTick(renderGraph))
watch(activeSection, section => {
  if (!sectionKeys.includes(section)) router.replace(sectionPath('overview'))
  if (section === 'graph') nextTick(renderSectionGraph)
  if (section === 'negotiation') negotiation.load()
  if (section === 'evaluation') loadEvaluationCenter()
  if (section === 'compiler') scenarioCompiler.load({ quiet: true })
})
watch(() => activeLifecycleRun.value?.updated_at, () => {
  if (activeLifecycleRun.value?.engine_mode === 'negotiation') negotiation.load({ quiet: true })
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
  stopGraphs()
  disposeShell()
})
</script>
