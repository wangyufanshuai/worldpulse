<template>
  <section class="guided-research-host" data-testid="guided-research-host">
    <header class="workspace-head guided-head">
      <div class="workspace-title">
        <div class="section-kicker"><ShieldAlert :size="16" /> 研究工作台 · Guided Flow</div>
        <h1>{{ model.detail.project.title }}</h1>
        <p>{{ model.detail.project.question }}</p>
      </div>
      <div class="head-actions">
        <span :class="['status-badge', model.detail.project.status]">{{ model.statusText }}</span>
        <label class="mode-switch">
          <span>运行模式</span>
          <select :value="model.runMode" data-testid="guided-run-mode" @change="onRunModeChange">
            <option value="fast">快速研究</option>
            <option value="full">完整真实数据</option>
          </select>
        </label>
        <button class="primary" data-testid="guided-run-action" :disabled="model.running" @click="$emit('run')">
          <Play :size="16" /> {{ model.running ? '运行中…' : '运行研究' }}
        </button>
      </div>
    </header>

    <nav class="guided-stage-rail" data-testid="guided-research-flow" aria-label="Guided Research Flow">
      <article
        v-for="stage in model.projection.stages"
        :key="stage.stage_key"
        :class="['guided-stage', stage.status]"
        :data-testid="`guided-stage-${stage.stage_key}`"
        :aria-current="stage.status === 'in_progress' ? 'step' : undefined"
      >
        <div class="stage-index">{{ stage.index }}</div>
        <div class="stage-copy">
          <div class="stage-heading">
            <strong>{{ stage.title }}</strong>
            <span :class="['stage-status', stage.status]">{{ stageStatusLabel(stage.status) }}</span>
          </div>
          <p>{{ stage.description }}</p>
          <small v-if="stage.unavailable_reasons.length">{{ stage.unavailable_reasons.join('；') }}</small>
          <small v-else class="lineage-label">{{ lineageLabel(stage.lineage) }}</small>
        </div>
      </article>
    </nav>

    <section class="governance-context" data-testid="guided-governance-context" aria-labelledby="guided-governance-title" :aria-busy="model.governance.busy">
      <header class="governance-banner" :class="`governance-${model.governance.banner.state}`">
        <div>
          <div class="section-kicker"><ShieldAlert :size="16" /> 治理上下文</div>
          <h2 id="guided-governance-title">{{ model.governance.banner.title }}</h2>
          <p>{{ model.governance.banner.detail }}</p>
        </div>
        <div class="governance-permissions" data-testid="guided-governance-permissions">
          <span :class="['permission-pill', { allowed: model.governance.permissions.write.allowed }]">
            写入：{{ model.governance.permissions.write.allowed ? '可发起' : '不可用' }}
          </span>
          <span :class="['permission-pill', { allowed: model.governance.permissions.review.allowed }]">
            审阅：{{ model.governance.permissions.review.allowed ? '可发起' : '不可用' }}
          </span>
          <small data-testid="guided-write-permission-reason">{{ model.governance.permissions.write.reason }}</small>
          <small data-testid="guided-review-permission-reason">{{ model.governance.permissions.review.reason }}</small>
        </div>
      </header>

      <div v-if="model.governance.error" class="governance-alert" data-testid="guided-governance-error">
        {{ model.governance.error }}
      </div>

      <div class="governance-grid">
        <article class="governance-card" data-testid="guided-evidence-governance">
          <div class="section-title">
            <div><div class="section-kicker"><Database :size="16" /> Evidence</div><h3>证据摘要与检索</h3></div>
            <span :class="['quality-pill', `integrity-${model.governance.evidence.summary?.integrity_status || 'empty'}`]">
              {{ evidenceIntegrityLabel(model.governance.evidence.summary?.integrity_status) }}
            </span>
          </div>
          <div v-if="model.governance.evidence.summary" class="governance-metrics">
            <span>来源 <strong>{{ model.governance.evidence.summary.source_count }}</strong></span>
            <span>快照 <strong>{{ model.governance.evidence.summary.snapshot_count }}</strong></span>
            <span>声明 <strong>{{ model.governance.evidence.summary.claim_count }}</strong></span>
            <span>覆盖 <strong>{{ Math.round(model.governance.evidence.summary.coverage * 100) }}%</strong></span>
          </div>
          <ul v-if="model.governance.evidence.gate_reasons.length" class="gate-reasons" data-testid="guided-evidence-gates">
            <li v-for="reason in model.governance.evidence.gate_reasons" :key="reason">{{ reason }}</li>
          </ul>
          <div class="governance-actions">
            <label class="governance-search">
              <span class="sr-only">检索 Evidence</span>
              <input v-model="evidenceQuery" data-testid="guided-evidence-search" placeholder="检索事实、快照或声明" @keyup.enter="searchEvidence" />
            </label>
            <button class="secondary" type="button" :disabled="model.governance.loading" data-testid="guided-evidence-search-action" @click="searchEvidence">检索</button>
            <button
              v-if="model.governance.permissions.write.allowed"
              class="secondary"
              type="button"
              :disabled="model.governance.loading || model.governance.busy"
              data-testid="guided-evidence-sync"
              @click="$emit('sync-evidence')"
            >同步</button>
          </div>
          <p v-if="model.governance.evidence.searchResult.total" class="governance-result-count" data-testid="guided-evidence-results">
            检索到 {{ model.governance.evidence.searchResult.total }} 条结果（快照 {{ model.governance.evidence.searchResult.snapshots.length }}，声明 {{ model.governance.evidence.searchResult.claims.length }}）。
          </p>
          <p v-else class="empty-line">{{ model.governance.evidence.summary ? '尚未检索 Evidence。' : 'Evidence summary 不可用。' }}</p>
        </article>

        <article class="governance-card" data-testid="guided-scenario-governance">
          <div class="section-title">
            <div><div class="section-kicker"><GitCompareArrows :size="16" /> Scenario</div><h3>候选到冻结修订</h3></div>
            <span class="quality-pill">{{ scenarioStateLabel(model.governance.scenario.state) }}</span>
          </div>
          <ol class="governance-state-rail" data-testid="guided-scenario-state-rail">
            <li v-for="step in model.governance.scenario.steps" :key="step.key" :class="step.status">
              <strong>{{ step.label }}</strong><small>{{ stepStatusLabel(step.status) }}</small>
            </li>
          </ol>
          <ul v-if="model.governance.scenario.gate_reasons.length" class="gate-reasons" data-testid="guided-scenario-gates">
            <li v-for="reason in model.governance.scenario.gate_reasons" :key="reason">{{ reason }}</li>
          </ul>
          <div class="governance-draft-list" v-if="model.governance.scenario.drafts.length">
            <button
              v-for="draft in model.governance.scenario.drafts"
              :key="draft.draft_id"
              type="button"
              :class="['draft-row', { selected: model.governance.scenario.activeDraft?.draft_id === draft.draft_id }]"
              :data-testid="`guided-draft-${draft.draft_id}`"
              @click="$emit('select-draft', draft.draft_id)"
            >
              <span><strong>{{ draft.name }}</strong><small>v{{ draft.version }} · {{ draft.draft_id }}</small></span>
              <em>{{ draftStatusLabel(draft.status) }}</em>
            </button>
          </div>
          <p v-else class="empty-line">尚无 Scenario Draft；候选必须先经人工接受并通过现有场景编译器形成草稿。</p>
          <article v-if="model.governance.scenario.activeDraft" class="active-draft-detail" data-testid="guided-scenario-active-detail">
            <header>
              <div>
                <strong>{{ model.governance.scenario.activeDraft.name }}</strong>
                <small>{{ draftStatusLabel(model.governance.scenario.activeDraft.status) }} · 只读修订详情</small>
              </div>
              <span>v{{ model.governance.scenario.activeDraft.version }}</span>
            </header>
            <dl class="draft-lineage">
              <div><dt>Draft ID</dt><dd><code>{{ model.governance.scenario.activeDraft.draft_id }}</code></dd></div>
              <div><dt>Parent</dt><dd><code>{{ model.governance.scenario.activeDraft.parent_draft_id || 'ROOT' }}</code></dd></div>
              <div><dt>Draft Hash</dt><dd><code data-testid="guided-active-draft-hash">{{ model.governance.scenario.activeDraft.draft_hash || '未冻结' }}</code></dd></div>
              <div><dt>Evidence Pack ID</dt><dd><code>{{ model.governance.scenario.activeDraft.evidence_pack_id || '未绑定' }}</code></dd></div>
              <div><dt>Evidence Pack Hash</dt><dd><code data-testid="guided-active-pack-hash">{{ model.governance.scenario.activeDraft.evidence_pack_hash || '未绑定' }}</code></dd></div>
              <div><dt>Compiler</dt><dd><code>{{ model.governance.scenario.activeDraft.compiler_version }}</code></dd></div>
            </dl>
            <div class="draft-payloads">
              <div><strong>Scenario</strong><pre>{{ prettyJson(model.governance.scenario.activeDraft.scenario) }}</pre></div>
              <div><strong>Manual assumptions</strong><pre>{{ prettyJson(model.governance.scenario.activeDraft.manual_assumptions) }}</pre></div>
            </div>
            <p :class="['pack-verification', `verification-${model.governance.scenario.activePackVerification.status}`]" data-testid="guided-active-pack-verification">
              {{ verificationStatusLabel(model.governance.scenario.activePackVerification.status) }}：{{ model.governance.scenario.activePackVerification.reason }}
            </p>
          </article>
          <div v-if="model.governance.scenario.activeDraft" class="draft-actions">
            <button
              v-if="model.governance.permissions.write.allowed && model.governance.scenario.activeDraft.status === 'draft'"
              class="secondary"
              type="button"
              :disabled="model.governance.busy"
              data-testid="guided-draft-submit"
              @click="$emit('submit-draft', model.governance.scenario.activeDraft.draft_id)"
            >提交审阅</button>
            <template v-if="model.governance.scenario.activeDraft.status === 'submitted'">
              <button v-if="model.governance.permissions.review.allowed" class="secondary" type="button" :disabled="model.governance.busy" data-testid="guided-draft-approve" @click="$emit('review-draft', { draftId: model.governance.scenario.activeDraft.draft_id, decision: 'approve' })">批准</button>
              <button v-if="model.governance.permissions.review.allowed" class="secondary" type="button" :disabled="model.governance.busy" data-testid="guided-draft-revision" @click="$emit('review-draft', { draftId: model.governance.scenario.activeDraft.draft_id, decision: 'request_revision' })">请求修订</button>
            </template>
            <button
              v-if="model.governance.permissions.write.allowed && ['approved', 'revision_requested', 'rejected'].includes(model.governance.scenario.activeDraft.status)"
              class="secondary"
              type="button"
              :disabled="model.governance.busy"
              data-testid="guided-draft-clone"
              @click="$emit('clone-draft', model.governance.scenario.activeDraft.draft_id)"
            >Clone 新修订</button>
          </div>
          <div v-if="model.governance.scenario.diff.available" class="draft-diff" data-testid="guided-scenario-diff">
            <div>
              <strong>父修订 · v{{ model.governance.scenario.diff.original?.version }}</strong>
              <code>{{ model.governance.scenario.diff.parent_draft_id }}</code>
              <small>Draft Hash</small><code data-testid="guided-parent-draft-hash">{{ model.governance.scenario.diff.original?.draft_hash || '未冻结' }}</code>
              <small>Pack {{ model.governance.scenario.diff.original?.evidence_pack_id || '未绑定' }}</small><code data-testid="guided-parent-pack-hash">{{ model.governance.scenario.diff.original?.evidence_pack_hash || '未绑定' }}</code>
              <pre>{{ prettyJson({ scenario: model.governance.scenario.diff.original?.scenario, manual_assumptions: model.governance.scenario.diff.original?.manual_assumptions }) }}</pre>
            </div>
            <div>
              <strong>当前修订 · v{{ model.governance.scenario.diff.current?.version }}</strong>
              <code>{{ model.governance.scenario.diff.current_draft_id }}</code>
              <small>Draft Hash</small><code data-testid="guided-current-draft-hash">{{ model.governance.scenario.diff.current?.draft_hash || '未冻结' }}</code>
              <small>Pack {{ model.governance.scenario.diff.current?.evidence_pack_id || '未绑定' }}</small><code data-testid="guided-current-pack-hash">{{ model.governance.scenario.diff.current?.evidence_pack_hash || '未绑定' }}</code>
              <pre>{{ prettyJson({ scenario: model.governance.scenario.diff.current?.scenario, manual_assumptions: model.governance.scenario.diff.current?.manual_assumptions }) }}</pre>
            </div>
            <p>变更字段：{{ model.governance.scenario.diff.changed_fields.join('、') || '无' }}</p>
          </div>
          <p v-else class="empty-line" data-testid="guided-scenario-diff-unavailable">修订对照不可用：{{ model.governance.scenario.diff.unavailable_reason }}</p>
        </article>
      </div>
    </section>

    <section class="split-lab guided-world-model" data-testid="guided-world-model">
      <div class="graph-panel">
        <div class="section-title">
          <div><div class="section-kicker"><Network :size="16" /> 世界模型</div><h2>事件到市场的确定性推理路径</h2></div>
          <span v-if="model.detail.graph" class="quality-pill">置信度 {{ Math.round(model.detail.graph.confidence) }}</span>
        </div>
        <slot name="graph">
          <div class="graph-canvas empty">世界模型尚不可用。</div>
        </slot>
      </div>
      <aside class="insight-panel">
        <div class="section-title">
          <div><div class="section-kicker"><ListChecks :size="16" /> 运行台账</div><h2>当前研究快照</h2></div>
          <span class="quality-pill">{{ model.currentModeText }}</span>
        </div>
        <p class="summary-box">{{ model.detail.latest_run?.summary || '尚未运行。完成首次运行后，这里显示快照、世界模型与引证简报。' }}</p>
        <div v-if="model.detail.graph" class="metric-grid">
          <article><span>节点</span><strong>{{ model.detail.graph.nodes.length }}</strong></article>
          <article><span>因果边</span><strong>{{ model.detail.graph.edges.length }}</strong></article>
          <article><span>证据源</span><strong>{{ model.detail.graph.evidence_sources.length }}</strong></article>
        </div>
        <div class="ledger-strip">
          <span>Project</span><code>{{ model.projection.project_id || '--' }}</code>
          <span>Run</span><code>{{ model.projection.run_id || '--' }}</code>
        </div>
      </aside>
    </section>

    <section class="report-chat guided-report-chat">
      <article class="report-panel" data-testid="guided-cited-brief">
        <div class="section-title">
          <div><div class="section-kicker"><FileText :size="16" /> 引证简报</div><h2>{{ model.detail.report?.title || '等待报告' }}</h2></div>
          <span v-if="model.detail.report" class="quality-pill">{{ model.detail.report.mode }}</span>
        </div>
        <template v-if="model.detail.report">
          <p class="report-summary">{{ model.detail.report.summary }}</p>

          <section class="brief-section" data-testid="guided-findings">
            <h3>核心结论</h3>
            <ul class="finding-list">
              <li v-for="(item, index) in model.detail.report.key_findings" :key="`finding-${index}-${item}`">
                <button @click="openEvidence(item, index, $event)">
                  <span>{{ item }}</span>
                  <small>{{ model.projection.citationsByFinding[index]?.length || 0 }} 条引用</small>
                </button>
              </li>
            </ul>
          </section>

          <section
            v-if="model.projection.unboundCitations.length"
            class="brief-section citation-contract-alert"
            data-testid="guided-unbound-citations"
            aria-labelledby="guided-citation-contract-title"
          >
            <h3 id="guided-citation-contract-title"><ShieldAlert :size="16" /> 引用合同异常</h3>
            <p>以下引用来自报告引用列表，但 finding_index 未绑定到现有结论；系统没有静默丢弃它们。</p>
            <article
              v-for="(citation, index) in model.projection.unboundCitations"
              :key="`unbound-citation-${index}-${citation.citation_id || 'missing'}`"
            >
              <strong>{{ citation.citation_id || `引用 ${index + 1}` }} · {{ citation.title }}</strong>
              <span>finding_index={{ citation.finding_index }} · {{ citation.kind }}</span>
              <p>{{ citation.summary }}</p>
            </article>
          </section>

          <div class="brief-grid">
            <section class="brief-section" data-testid="guided-evidence-section">
              <h3><Database :size="16" /> 事实证据</h3>
              <article v-for="(item, index) in model.projection.reportSections.evidence" :key="`evidence-${index}-${item.title}-${item.source}`">
                <strong>{{ item.title }}</strong><span>{{ item.source }}</span>
                <p>{{ item.interpretation }}</p>
              </article>
              <p v-if="!model.projection.reportSections.evidence.length" class="empty-line">暂无结构化证据。</p>
            </section>
            <section class="brief-section uncertainty-section" data-testid="guided-uncertainty-section">
              <h3><ShieldAlert :size="16" /> 不确定性</h3>
              <ul><li v-for="(item, index) in model.projection.reportSections.uncertainties" :key="`uncertainty-${index}-${item}`">{{ item }}</li></ul>
              <p v-if="!model.projection.reportSections.uncertainties.length" class="empty-line">未提供不确定性说明。</p>
            </section>
            <section class="brief-section" data-testid="guided-watch-section">
              <h3><Activity :size="16" /> 观察信号</h3>
              <article v-for="(item, index) in model.projection.reportSections.watchSignals" :key="`watch-signal-${index}-${item.name}`">
                <strong>{{ item.name }}</strong><span>{{ item.direction }} · {{ item.current_status }}</span>
                <p>{{ item.why_it_matters }}</p>
              </article>
              <p v-if="!model.projection.reportSections.watchSignals.length" class="empty-line">暂无观察信号。</p>
            </section>
            <section class="brief-section" data-testid="guided-scenario-section">
              <h3><GitCompareArrows :size="16" /> 场景建议</h3>
              <article v-for="(item, index) in model.projection.reportSections.scenarioSuggestions" :key="`scenario-suggestion-${index}-${item.name}`">
                <strong>{{ item.name }}</strong><span>{{ item.shock_type }}</span>
                <p>{{ item.rationale }}</p>
              </article>
              <p v-if="!model.projection.reportSections.scenarioSuggestions.length" class="empty-line">暂无场景建议。</p>
            </section>
          </div>

          <p class="sandbox-note">{{ model.detail.report.disclaimer }}</p>
          <a class="download" :href="model.markdownUrl" download="worldpulse_report.md"><Download :size="16" /> 导出 Markdown 报告</a>
        </template>
        <div v-else class="empty">运行后生成带证据、推导与不确定性的正式简报。</div>
      </article>

      <aside class="chat-panel" data-testid="guided-research-chat">
        <div class="section-title"><div><div class="section-kicker"><MessagesSquare :size="16" /> 研究追问</div><h2>追问证据与边界</h2></div></div>
        <div class="quick-prompts"><button v-for="prompt in model.prompts" :key="prompt" @click="$emit('update:message', prompt)">{{ prompt }}</button></div>
        <div class="chat-log"><div v-for="msg in model.detail.chat_messages" :key="msg.message_id" :class="['chat-msg', msg.role]"><span>{{ msg.role === 'user' ? '你' : 'WorldPulse' }}</span><p>{{ msg.content }}</p></div></div>
        <div class="chat-input">
          <label class="sr-only" for="guided-research-question">研究追问</label>
          <textarea id="guided-research-question" :value="model.message" rows="3" placeholder="追问证据、反例、情景或结论边界" @input="onMessageInput" />
          <button :disabled="model.chatting || !model.message" @click="$emit('send')"><Send :size="16" /> {{ model.chatting ? '分析中…' : '发送' }}</button>
        </div>
      </aside>
    </section>

    <aside
      v-if="model.evidenceDrawer"
      ref="citationDrawerRef"
      class="evidence-drawer guided-citation-drawer"
      data-testid="guided-citation-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="guided-citation-drawer-title"
      tabindex="-1"
      @keydown.esc.stop.prevent="closeCitationDrawer"
      @keydown.tab="trapCitationFocus"
    >
      <button ref="citationDrawerCloseRef" class="drawer-close" @click="closeCitationDrawer"><X :size="16" /> 关闭</button>
      <div class="section-kicker"><FileSearch :size="16" /> 证据到结论</div>
      <h2 id="guided-citation-drawer-title">{{ model.evidenceDrawer.finding }}</h2>
      <p>{{ model.evidenceDrawer.summary }}</p>
      <div class="citation-ledger">
        <article v-for="(citation, index) in model.evidenceDrawer.citations" :key="`citation-${index}-${citation.citation_id || 'missing'}`">
          <div><code>{{ citation.citation_id }}</code><strong>{{ citation.title }}</strong></div>
          <span>{{ citation.kind_label }} · {{ citation.source }} · {{ Math.round(citation.confidence) }}/100</span>
          <p>{{ citation.summary }}</p>
        </article>
        <p v-if="!model.evidenceDrawer.citations.length" class="empty-line">没有与该结论直接绑定的引用。</p>
      </div>
    </aside>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch, type PropType } from 'vue'
import {
  Activity,
  Database,
  Download,
  FileSearch,
  FileText,
  GitCompareArrows,
  ListChecks,
  MessagesSquare,
  Network,
  Play,
  Send,
  ShieldAlert,
  X,
} from 'lucide-vue-next'
import type { GuidedResearchHostModel, GuidedStageStatus, EvidenceIntegrityStatus, EvidencePackVerificationStatus, ScenarioDraftStatus, GuidedGovernanceStep } from '../../contracts/researchWorkspace'

const props = defineProps({
  model: { type: Object as PropType<GuidedResearchHostModel>, required: true },
})
const emit = defineEmits<{
  (event: 'update:run-mode', value: string): void
  (event: 'run'): void
  (event: 'update:message', value: string): void
  (event: 'send'): void
  (event: 'open-evidence', payload: { finding: string, index: number }): void
  (event: 'close-evidence'): void
  (event: 'sync-evidence'): void
  (event: 'search-evidence', query: string): void
  (event: 'select-draft', draftId: string): void
  (event: 'submit-draft', draftId: string): void
  (event: 'review-draft', payload: { draftId: string, decision: 'approve' | 'request_revision' }): void
  (event: 'clone-draft', draftId: string): void
}>()

const citationDrawerRef = ref<HTMLElement | null>(null)
const citationDrawerCloseRef = ref<HTMLButtonElement | null>(null)
const evidenceQuery = ref('')
let returnFocusElement: HTMLElement | null = null
let inertSnapshots: Array<{ element: HTMLElement; inert: boolean }> = []

const focusableSelector = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'object',
  'embed',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function onRunModeChange(event: Event) {
  emit('update:run-mode', (event.target as HTMLSelectElement).value)
}

function onMessageInput(event: Event) {
  emit('update:message', (event.target as HTMLTextAreaElement).value)
}

function searchEvidence() {
  emit('search-evidence', evidenceQuery.value)
}

function openEvidence(finding: string, index: number, event: MouseEvent) {
  returnFocusElement = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  emit('open-evidence', { finding, index })
}

function closeCitationDrawer() {
  emit('close-evidence')
}

function focusableCitationElements() {
  const drawer = citationDrawerRef.value
  if (!drawer) return []
  return Array.from(drawer.querySelectorAll<HTMLElement>(focusableSelector))
    .filter(element => !element.hidden && element.getAttribute('aria-hidden') !== 'true' && element.tabIndex >= 0)
}

function focusCitationStart() {
  const [firstFocusable] = focusableCitationElements()
  ;(citationDrawerCloseRef.value || firstFocusable || citationDrawerRef.value)?.focus()
}

function trapCitationFocus(event: KeyboardEvent) {
  const drawer = citationDrawerRef.value
  if (!drawer) return
  const focusable = focusableCitationElements()
  if (!focusable.length) {
    event.preventDefault()
    drawer.focus()
    return
  }

  const firstFocusable = focusable[0]
  const lastFocusable = focusable[focusable.length - 1]
  const activeElement = document.activeElement
  if (event.shiftKey && (activeElement === firstFocusable || !drawer.contains(activeElement))) {
    event.preventDefault()
    lastFocusable.focus()
  } else if (!event.shiftKey && (activeElement === lastFocusable || !drawer.contains(activeElement))) {
    event.preventDefault()
    firstFocusable.focus()
  }
}

function containCitationFocus(event: FocusEvent) {
  const drawer = citationDrawerRef.value
  if (drawer && event.target instanceof Node && !drawer.contains(event.target)) focusCitationStart()
}

function restoreBackgroundInert() {
  for (const snapshot of inertSnapshots.reverse()) snapshot.element.inert = snapshot.inert
  inertSnapshots = []
}

function makeBackgroundInert(drawer: HTMLElement) {
  restoreBackgroundInert()
  if (!('inert' in HTMLElement.prototype)) return

  let modalBranch: HTMLElement = drawer
  let parent = modalBranch.parentElement
  while (parent) {
    for (const sibling of parent.children) {
      if (sibling !== modalBranch && sibling instanceof HTMLElement) {
        inertSnapshots.push({ element: sibling, inert: sibling.inert })
        sibling.inert = true
      }
    }
    if (parent === document.body) break
    modalBranch = parent
    parent = parent.parentElement
  }
}

function activateCitationModal() {
  const drawer = citationDrawerRef.value
  if (!drawer) return
  makeBackgroundInert(drawer)
  document.addEventListener('focusin', containCitationFocus)
}

function deactivateCitationModal() {
  document.removeEventListener('focusin', containCitationFocus)
  restoreBackgroundInert()
}

watch(
  () => props.model.evidenceDrawer,
  async (drawer, previousDrawer) => {
    if (!drawer) {
      deactivateCitationModal()
      await nextTick()
      if (previousDrawer && returnFocusElement?.isConnected) returnFocusElement.focus()
      returnFocusElement = null
      return
    }

    await nextTick()
    if (!props.model.evidenceDrawer) return
    activateCitationModal()
    focusCitationStart()
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  deactivateCitationModal()
  returnFocusElement = null
})

function stageStatusLabel(status: GuidedStageStatus) {
  return ({ complete: '已完成', in_progress: '进行中', ready: '可继续', blocked: '被阻塞' })[status] || status
}

function lineageLabel(lineage: Record<string, string> = {}) {
  const entries = Object.entries(lineage).filter(([, value]) => value)
  return entries.length ? entries.map(([key, value]) => `${key}: ${value}`).join(' · ') : '已通过当前合同校验'
}

function evidenceIntegrityLabel(status?: EvidenceIntegrityStatus) {
  return ({ verified: '已校验', failed: '校验失败', empty: '暂无 Evidence' }[status || 'empty'])
}

function scenarioStateLabel(state: string) {
  return ({ candidate: '候选', draft: '草稿', review: '审阅中', approved: '已批准', frozen: '已冻结' }[state] || state)
}

function stepStatusLabel(status: GuidedGovernanceStep['status']) {
  return ({ complete: '完成', current: '当前', pending: '待处理', unavailable: '不可用' }[status] || status)
}

function draftStatusLabel(status: ScenarioDraftStatus) {
  return ({ draft: '草稿', submitted: '审阅中', approved: '已批准', revision_requested: '请求修订', rejected: '已拒绝', superseded: '已取代' }[status] || status)
}

function verificationStatusLabel(status: EvidencePackVerificationStatus) {
  return ({
    not_required: '尚未冻结',
    verified: '已验证',
    missing: '缺失',
    unavailable: '不可用',
    mismatch: 'Hash/ID 不匹配',
    project_mismatch: '项目漂移',
  }[status])
}

function prettyJson(value: unknown) {
  return JSON.stringify(value || {}, null, 2)
}
</script>

<style scoped>
.guided-research-host {
  --ledger-ink: #eef4fb;
  --ledger-muted: #b7c4d3;
  --ledger-line: rgba(148, 163, 184, 0.28);
  --ledger-paper: rgba(17, 25, 39, 0.96);
  display: grid;
  gap: 22px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.guided-head {
  border-bottom: 1px solid var(--ledger-line);
}

.guided-stage-rail {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--ledger-line);
  border-radius: 18px;
  background: var(--ledger-line);
  box-shadow: 0 18px 40px rgba(30, 50, 41, 0.08);
}

.guided-stage {
  min-height: 156px;
  padding: 18px;
  background: var(--ledger-paper);
  position: relative;
}

.guided-stage::after {
  content: '';
  position: absolute;
  inset: auto 18px 0;
  height: 3px;
  background: #87938d;
}

.guided-stage.complete::after { background: #2f7d5c; }
.guided-stage.in_progress::after { background: #cb7b24; }
.guided-stage.ready::after { background: #5aa9d6; }
.guided-stage.blocked::after { background: #ad4545; }

.governance-context {
  display: grid;
  gap: 12px;
  border: 1px solid var(--ledger-line);
  border-radius: 18px;
  padding: 16px;
  background: rgba(9, 15, 26, 0.62);
}

.governance-banner {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding: 16px;
  border-radius: 14px;
  border: 1px solid rgba(157, 214, 250, 0.3);
  background: rgba(35, 73, 98, 0.26);
}

.governance-banner h2 { margin: 4px 0 6px; color: var(--ledger-ink); }
.governance-banner p { margin: 0; color: var(--ledger-muted); line-height: 1.5; }
.governance-approved, .governance-frozen { border-color: rgba(99, 211, 161, 0.42); background: rgba(26, 79, 63, 0.28); }
.governance-review { border-color: rgba(240, 173, 88, 0.45); background: rgba(94, 62, 29, 0.28); }
.governance-draft, .governance-candidate { border-color: rgba(157, 214, 250, 0.3); }
.governance-permissions { display: grid; grid-template-columns: repeat(2, auto); justify-content: end; gap: 8px; max-width: min(440px, 50%); }
.permission-pill { border: 1px solid rgba(242, 139, 139, 0.5); border-radius: 999px; padding: 5px 9px; color: #f2a2a2; font-size: 12px; white-space: nowrap; }
.permission-pill.allowed { border-color: rgba(99, 211, 161, 0.5); color: #63d3a1; }
.governance-permissions small { grid-column: 1 / -1; color: var(--ledger-muted); line-height: 1.45; }
.governance-alert, .gate-reasons { color: #f2a2a2; }
.governance-alert { border: 1px solid rgba(242, 139, 139, 0.45); border-radius: 12px; padding: 10px 12px; background: rgba(82, 29, 35, 0.38); }
.gate-reasons { margin: 10px 0; padding-left: 18px; line-height: 1.5; }
.governance-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.governance-card { min-width: 0; border: 1px solid var(--ledger-line); border-radius: 14px; padding: 14px; background: rgba(17, 25, 39, 0.72); }
.governance-card h3 { margin: 3px 0 0; color: var(--ledger-ink); }
.governance-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }
.governance-metrics span { display: grid; gap: 3px; color: var(--ledger-muted); font-size: 12px; }
.governance-metrics strong { color: var(--ledger-ink); font-size: 18px; }
.governance-actions, .draft-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; }
.governance-search { flex: 1 1 180px; }
.governance-search input { width: 100%; border: 1px solid var(--ledger-line); border-radius: 8px; padding: 9px 10px; color: var(--ledger-ink); background: rgba(9, 15, 26, 0.7); }
.governance-result-count { color: var(--ledger-muted); font-size: 12px; }
.governance-state-rail { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; margin: 14px 0 10px; padding: 0; list-style: none; }
.governance-state-rail li { display: grid; gap: 4px; border-top: 2px solid var(--ledger-line); padding-top: 7px; color: var(--ledger-muted); font-size: 12px; }
.governance-state-rail li.complete { border-color: #63d3a1; color: #63d3a1; }
.governance-state-rail li.current { border-color: #9dd6fa; color: #9dd6fa; }
.governance-state-rail li small { color: inherit; opacity: .82; }
.governance-draft-list { display: grid; gap: 6px; max-height: 150px; overflow: auto; }
.draft-row { display: flex; justify-content: space-between; gap: 10px; width: 100%; padding: 9px 10px; border: 1px solid var(--ledger-line); border-radius: 9px; color: var(--ledger-ink); text-align: left; background: rgba(9, 15, 26, 0.55); }
.draft-row:hover, .draft-row.selected { border-color: #9dd6fa; background: rgba(35, 73, 98, 0.35); }
.draft-row span { min-width: 0; display: grid; gap: 3px; }
.draft-row small, .draft-row em { color: var(--ledger-muted); font-size: 11px; font-style: normal; }
.draft-row small { overflow-wrap: anywhere; }
.active-draft-detail { display: grid; gap: 10px; margin-top: 12px; border: 1px solid var(--ledger-line); border-radius: 10px; padding: 11px; background: rgba(9, 15, 26, 0.48); }
.active-draft-detail > header { display: flex; justify-content: space-between; gap: 10px; color: var(--ledger-ink); }
.active-draft-detail > header div { display: grid; gap: 3px; }
.active-draft-detail > header small { color: var(--ledger-muted); }
.active-draft-detail > header > span { color: #9dd6fa; }
.draft-lineage { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 0; }
.draft-lineage div { min-width: 0; }
.draft-lineage dt, .draft-diff small { color: var(--ledger-muted); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
.draft-lineage dd { margin: 2px 0 0; }
.draft-lineage code, .draft-diff code { color: var(--ledger-muted); font-size: 11px; overflow-wrap: anywhere; }
.draft-payloads { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.draft-payloads > div { min-width: 0; }
.draft-payloads strong { color: var(--ledger-ink); font-size: 12px; }
.draft-payloads pre { max-height: 140px; overflow: auto; color: var(--ledger-muted); font: 11px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }
.pack-verification { margin: 0; color: var(--ledger-muted); font-size: 11px; line-height: 1.45; }
.verification-verified { color: #63d3a1; }
.verification-missing, .verification-unavailable, .verification-mismatch, .verification-project_mismatch { color: #f2a2a2; }
.draft-diff { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 14px; }
.draft-diff > div { min-width: 0; border: 1px solid var(--ledger-line); border-radius: 9px; padding: 9px; }
.draft-diff code { display: block; margin: 4px 0; color: var(--ledger-muted); font-size: 11px; overflow-wrap: anywhere; }
.draft-diff pre { max-height: 140px; margin: 0; overflow: auto; color: var(--ledger-muted); font: 11px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }
.draft-diff > p { grid-column: 1 / -1; margin: 0; color: var(--ledger-muted); font-size: 12px; }

.stage-index {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 30px;
  color: rgba(183, 196, 211, 0.58);
  line-height: 1;
}

.stage-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 14px;
}

.stage-heading strong { color: var(--ledger-ink); }
.stage-copy { min-width: 0; }
.stage-copy p, .stage-copy small { color: var(--ledger-muted); }
.stage-copy p { margin: 9px 0 6px; line-height: 1.55; }
.stage-copy small { display: block; line-height: 1.45; }

.stage-status {
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 11px;
  white-space: nowrap;
  color: #c1ccd8;
}

.stage-status.complete { color: #63d3a1; }
.stage-status.in_progress { color: #f0ad58; }
.stage-status.ready { color: #9dd6fa; }
.stage-status.blocked { color: #f28b8b; }
.lineage-label { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }

.ledger-strip {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 7px 12px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed var(--ledger-line);
  color: var(--ledger-muted);
}

.ledger-strip code { overflow-wrap: anywhere; color: var(--ledger-ink); }
.guided-report-chat { align-items: start; }
.brief-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
.brief-section { border: 1px solid var(--ledger-line); border-radius: 14px; padding: 14px; background: rgba(17, 25, 39, 0.72); }
.brief-section h3 { display: flex; align-items: center; gap: 7px; margin-top: 0; }
.brief-section article + article { border-top: 1px dashed var(--ledger-line); margin-top: 10px; padding-top: 10px; }
.brief-section article span { display: block; color: var(--ledger-muted); font-size: 12px; margin-top: 2px; }
.brief-section article p, .brief-section li { color: var(--ledger-muted); line-height: 1.55; }
.uncertainty-section { border-color: rgba(242, 139, 139, 0.38); background: rgba(82, 29, 35, 0.32); }
.finding-list button { display: flex; justify-content: space-between; gap: 14px; width: 100%; text-align: left; }
.finding-list button small { white-space: nowrap; color: var(--ledger-muted); }
.empty-line { color: var(--ledger-muted); font-style: italic; }
.citation-contract-alert { margin-top: 14px; border-color: rgba(242, 139, 139, 0.55); background: rgba(82, 29, 35, 0.38); }
.citation-contract-alert > p { color: var(--ledger-muted); }
.guided-citation-drawer:focus { outline: 2px solid #9dd6fa; outline-offset: -4px; }
.citation-ledger { display: grid; gap: 10px; margin-top: 18px; }
.citation-ledger article { border: 1px solid var(--ledger-line); border-radius: 12px; padding: 12px; background: rgba(17, 25, 39, 0.9); }
.citation-ledger article div { display: flex; gap: 9px; align-items: baseline; }
.citation-ledger article span { display: block; margin-top: 6px; color: var(--ledger-muted); font-size: 12px; }
.citation-ledger article p { margin-bottom: 0; line-height: 1.55; }

@media (max-width: 1080px) {
  .guided-stage-rail { grid-template-columns: 1fr; }
  .guided-stage { min-height: 0; }
  .brief-grid { grid-template-columns: 1fr; }
  .governance-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .guided-stage { padding: 14px; }
  .guided-head { padding: 16px; }
  .stage-heading { align-items: flex-start; flex-wrap: wrap; }
  .finding-list button { align-items: flex-start; flex-wrap: wrap; }
  .citation-ledger article div { align-items: flex-start; flex-direction: column; }
  .governance-banner { flex-direction: column; }
  .governance-permissions { justify-content: flex-start; max-width: none; }
  .governance-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .governance-state-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .draft-diff { grid-template-columns: 1fr; }
  .draft-diff > p { grid-column: auto; }
  .draft-lineage, .draft-payloads { grid-template-columns: 1fr; }
}
</style>
