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
import type { GuidedResearchHostModel, GuidedStageStatus } from '../../contracts/researchWorkspace'

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
}>()

const citationDrawerRef = ref<HTMLElement | null>(null)
const citationDrawerCloseRef = ref<HTMLButtonElement | null>(null)
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
}

@media (max-width: 640px) {
  .guided-stage { padding: 14px; }
  .guided-head { padding: 16px; }
  .stage-heading { align-items: flex-start; flex-wrap: wrap; }
  .finding-list button { align-items: flex-start; flex-wrap: wrap; }
  .citation-ledger article div { align-items: flex-start; flex-direction: column; }
}
</style>
