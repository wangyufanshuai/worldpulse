<template>
  <section class="scenario-compiler" data-testid="war-room-scenario-compiler">
    <header class="compiler-hero">
      <div>
        <span class="compiler-eyebrow"><ScanText :size="16" /> EVIDENCE-DRIVEN SCENARIO COMPILER</span>
        <h3>证据驱动场景编译</h3>
        <p>材料只生成带定位的定性候选；权威风险、供应链压力及 override 始终由确定性引擎控制。</p>
      </div>
      <button type="button" class="secondary" :disabled="loading" @click="$emit('refresh')"><RefreshCw :size="14" /> 刷新</button>
    </header>

    <nav class="compiler-steps" aria-label="场景编译阶段">
      <button v-for="step in steps" :key="step[0]" type="button" :class="stepState(step[0])" :data-testid="`compiler-step-${step[0]}`" @click="activeStep = step[0]">
        <span>{{ step[1] }}</span><strong>{{ step[2] }}</strong><CheckCircle2 v-if="stepState(step[0]) === 'done'" :size="15" />
      </button>
    </nav>

    <div v-if="error" class="compiler-alert error">{{ error }}</div>
    <div v-if="actionError" class="compiler-alert error">{{ actionError }}</div>

    <section v-show="activeStep === 'upload'" class="compiler-panel" data-testid="compiler-upload-panel">
      <header><div><span>STEP 01</span><h3>安全材料上传</h3></div><UploadCloud :size="24" /></header>
      <form v-if="canWrite" class="compiler-form" @submit.prevent="submitUpload">
        <label class="drop-zone form-span" @dragover.prevent @drop.prevent="setDroppedFile">
          <input ref="fileInput" type="file" accept=".pdf,.txt,.md,.markdown,.csv" required data-testid="compiler-file-input" @change="setSelectedFile" />
          <FileUp :size="28" /><strong>{{ selectedFile?.name || '拖拽或选择 PDF / TXT / Markdown / CSV' }}</strong>
          <small>单文件 ≤ 25 MB；扫描、加密或损坏 PDF 将 fail-closed</small>
        </label>
        <label>材料标题<input v-model="uploadDraft.title" required /></label>
        <label>分类<input v-model="uploadDraft.category" required placeholder="energy / trade / sanctions" /></label>
        <label>发布机构<input v-model="uploadDraft.publisher" required /></label>
        <label>许可/授权<input v-model="uploadDraft.license_name" required /></label>
        <label>许可链接<input v-model="uploadDraft.license_url" type="url" /></label>
        <label>观察时间<input v-model="uploadDraft.observed_at" type="datetime-local" required /></label>
        <label>截止时间<input v-model="uploadDraft.cutoff_at" type="datetime-local" required /></label>
        <button type="submit" :disabled="busy || !selectedFile || !organization" data-testid="compiler-upload-submit"><ShieldCheck :size="15" /> 校验并上传</button>
      </form>
      <p v-else class="compiler-empty">当前角色只能查看和下载材料。</p>
      <div class="compiler-list">
        <article v-for="document in documents" :key="document.document_id">
          <span :class="['status', document.status]">{{ document.status }}</span>
          <div><strong>{{ document.title }}</strong><small>{{ document.original_filename }} · {{ formatBytes(document.size_bytes) }} · cutoff {{ shortTime(document.cutoff_at) }}</small></div>
          <code>{{ compactHash(document.content_hash) }}</code>
          <div class="actions"><a :href="downloadUrl(document.document_id)">下载</a><button v-if="canWrite" type="button" class="secondary" :disabled="busy || document.status === 'extracting'" @click="runAction(() => $emit('extract', document.document_id))">抽取</button></div>
        </article>
        <p v-if="!documents.length" class="compiler-empty">尚无版本化材料。</p>
      </div>
    </section>

    <section v-show="activeStep === 'extract'" class="compiler-panel" data-testid="compiler-extraction-panel">
      <header><div><span>STEP 02</span><h3>版本化文本抽取</h3></div><Braces :size="24" /></header>
      <div class="compiler-list">
        <article v-for="job in jobs" :key="job.job_id">
          <span :class="['status', job.status]">{{ job.status }}</span>
          <div><strong>{{ job.extractor_version }}</strong><small>{{ job.provider }} · attempt {{ job.attempt_count }} · {{ shortTime(job.updated_at) }}</small></div>
          <code>{{ compactHash(job.request_hash) }}</code>
          <div class="actions">
            <button type="button" class="secondary" @click="$emit('events', job.job_id)">事件</button>
            <button v-if="canWrite && job.status === 'queued'" type="button" class="secondary" @click="$emit('cancel', job.job_id)">取消</button>
            <button v-if="canWrite && ['failed', 'cancelled'].includes(job.status)" type="button" class="secondary" @click="$emit('retry', job.job_id)">重试</button>
          </div>
        </article>
        <p v-if="!jobs.length" class="compiler-empty">上传材料并点击“抽取”后，任务由现有 ingestion worker 公平领取。</p>
      </div>
      <div v-if="events.length" class="compiler-events" data-testid="compiler-extraction-events">
        <article v-for="event in events" :key="event.seq"><code>#{{ event.seq }}</code><strong>{{ event.title }}</strong><p>{{ event.detail }}</p></article>
      </div>
    </section>

    <section v-show="activeStep === 'candidates'" class="compiler-panel" data-testid="compiler-candidates-panel">
      <header><div><span>STEP 03</span><h3>候选核验与原文定位</h3></div><ListChecks :size="24" /></header>
      <div class="candidate-filters"><button v-for="item in candidateFilters" :key="item" type="button" :class="{ active: candidateFilter === item }" @click="candidateFilter = item">{{ item === 'all' ? '全部' : typeLabel(item) }}</button></div>
      <div class="candidate-grid">
        <article v-for="candidate in filteredCandidates" :key="candidate.candidate_id" :class="['candidate-card', candidate.validation_status]">
          <header><span>{{ typeLabel(candidate.candidate_type) }}</span><strong>{{ candidate.display_value }}</strong><small>{{ Math.round(candidate.confidence * 100) }}%</small></header>
          <blockquote>“{{ candidate.excerpt }}”</blockquote>
          <p>{{ locatorLabel(candidate.locator) }} · {{ candidate.extractor_source }}</p>
          <code>{{ candidate.canonical_value }} · {{ compactHash(candidate.candidate_hash) }}</code>
          <div v-if="candidate.latest_decision" class="decision-line">已{{ candidate.latest_decision.decision === 'accepted' ? '接受' : '拒绝' }}<span v-if="candidate.latest_decision.normalized_value"> → {{ candidate.latest_decision.normalized_value }}</span></div>
          <div v-if="canWrite && candidate.validation_status === 'valid'" class="actions">
            <button type="button" class="secondary accept" @click="$emit('decision', candidate.candidate_id, { decision: 'accepted', normalized_value: candidate.canonical_value, comment: '场景编译台确认' })">接受</button>
            <button type="button" class="secondary" @click="$emit('decision', candidate.candidate_id, { decision: 'rejected', comment: '场景编译台排除' })">拒绝</button>
          </div>
          <div v-else-if="candidate.validation_status === 'invalid'" class="compiler-alert error">{{ candidate.validation_reason }}</div>
        </article>
        <p v-if="!filteredCandidates.length" class="compiler-empty">没有匹配的候选。</p>
      </div>
    </section>

    <section v-show="activeStep === 'draft'" class="compiler-panel" data-testid="compiler-draft-panel">
      <header><div><span>STEP 04</span><h3>场景草稿与人工假设 Diff</h3></div><FileJson2 :size="24" /></header>
      <form v-if="canWrite" class="compiler-form" @submit.prevent="submitDraft">
        <label class="form-span">草稿名称<input v-model="draftForm.name" required /></label>
        <label>持续天数<input v-model.number="draftForm.duration_days" type="number" min="7" max="90" /></label>
        <label>强度<input v-model.number="draftForm.intensity" type="number" min="0.05" max="1" step="0.05" /></label>
        <label>传播系数<input v-model.number="draftForm.propagation" type="number" min="0.05" max="0.9" step="0.05" /></label>
        <label class="form-span">人工假设理由<textarea v-model="draftForm.assumption_reason" rows="3" placeholder="修改默认持续时间、强度或传播系数时必填" /></label>
        <p class="form-span assumption-note">将固定 {{ acceptedIds.length }} 个已接受候选；编译器不会生成 country_overrides 或 chain_overrides。</p>
        <button type="submit" :disabled="busy || !acceptedIds.length" data-testid="compiler-create-draft"><FilePlus2 :size="15" /> 编译草稿</button>
      </form>
      <DraftList :drafts="drafts" :can-write="canWrite" @submit="$emit('submit-draft', $event)" @clone="$emit('clone-draft', $event)" />
    </section>

    <section v-show="activeStep === 'review'" class="compiler-panel" data-testid="compiler-review-panel">
      <header><div><span>STEP 05</span><h3>双人审批与 Evidence Pack</h3></div><UserCheck :size="24" /></header>
      <div class="review-list">
        <article v-for="draft in drafts" :key="draft.draft_id">
          <span :class="['status', draft.status]">{{ draft.status }}</span>
          <div><strong>{{ draft.name }} · v{{ draft.version }}</strong><small>Draft {{ compactHash(draft.draft_hash) }} · Evidence {{ compactHash(draft.evidence_pack_hash) }}</small></div>
          <pre>{{ JSON.stringify(draft.scenario, null, 2) }}</pre>
          <div v-if="canReview && draft.status === 'submitted'" class="actions">
            <button type="button" class="secondary accept" data-testid="compiler-approve-draft" @click="$emit('review-draft', draft.draft_id, { decision: 'approve', comment: '证据与人工假设已复核' })">批准</button>
            <button type="button" class="secondary" @click="$emit('review-draft', draft.draft_id, { decision: 'request_revision', comment: '需要修订材料或候选' })">请求修订</button>
            <button type="button" class="secondary danger" @click="$emit('review-draft', draft.draft_id, { decision: 'reject', comment: '证据不足，拒绝' })">拒绝</button>
          </div>
        </article>
        <p v-if="!drafts.length" class="compiler-empty">尚无待审批草稿。</p>
      </div>
    </section>

    <section v-show="activeStep === 'run'" class="compiler-panel" data-testid="compiler-run-panel">
      <header><div><span>STEP 06</span><h3>从批准草稿创建运行</h3></div><PlayCircle :size="24" /></header>
      <form v-if="canWrite && approvedDrafts.length" class="run-form" @submit.prevent="$emit('run-draft', runForm.draft_id, { engine_mode: runForm.engine_mode, seed: runForm.seed, max_attempts: 3 })">
        <label>批准草稿<select v-model="runForm.draft_id"><option v-for="draft in approvedDrafts" :key="draft.draft_id" :value="draft.draft_id">{{ draft.name }} · v{{ draft.version }}</option></select></label>
        <label>运行模式<select v-model="runForm.engine_mode" data-testid="compiler-engine-mode"><option value="deterministic">deterministic</option><option value="hybrid">hybrid</option><option value="negotiation">negotiation</option></select></label>
        <label>Seed<input v-model.number="runForm.seed" type="number" /></label>
        <button type="submit" data-testid="compiler-create-run"><Play :size="15" /> 创建受控运行</button>
      </form>
      <p v-else class="compiler-empty">需要一个经异人审批的草稿才能创建运行。</p>
      <article v-if="lastRun" class="run-created"><CheckCircle2 :size="20" /><div><strong>运行已进入生命周期队列</strong><code>{{ lastRun.run_id }}</code><small>{{ lastRun.engine_mode }} · Draft {{ compactHash(lastRun.scenario_draft_hash) }}</small></div></article>
    </section>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, reactive, ref, watch } from 'vue'
import { Braces, CheckCircle2, FileJson2, FilePlus2, FileUp, ListChecks, Play, PlayCircle, RefreshCw, ScanText, ShieldCheck, UploadCloud, UserCheck } from 'lucide-vue-next'
import { acceptedCandidateIds, compactCompilerHash, compilerSteps, compilerStepState, formatBytes as bytesLabel } from '../../composables/scenarioCompilerProjection'

const props = defineProps({ organization: Object, documents: { type: Array, default: () => [] }, jobs: { type: Array, default: () => [] }, candidates: { type: Array, default: () => [] }, drafts: { type: Array, default: () => [] }, events: { type: Array, default: () => [] }, lastRun: Object, loading: Boolean, error: String, canWrite: Boolean, canReview: Boolean })
const emit = defineEmits(['refresh', 'upload', 'extract', 'events', 'cancel', 'retry', 'decision', 'create-draft', 'submit-draft', 'review-draft', 'clone-draft', 'run-draft'])
const steps = compilerSteps
const activeStep = ref('upload')
const busy = ref(false)
const actionError = ref('')
const selectedFile = ref(null)
const fileInput = ref(null)
const now = new Date().toISOString().slice(0, 16)
const uploadDraft = reactive({ title: '', category: 'other', publisher: '', license_name: '', license_url: '', observed_at: now, cutoff_at: now })
const draftForm = reactive({ name: '证据驱动场景', duration_days: 30, intensity: 0.65, propagation: 0.35, assumption_reason: '' })
const runForm = reactive({ draft_id: '', engine_mode: 'deterministic', seed: 42 })
const candidateFilter = ref('all')
const candidateFilters = ['all', 'scenario_preset', 'country', 'supply_chain', 'policy_action', 'relationship', 'event_date']
const acceptedIds = computed(() => acceptedCandidateIds(props.candidates))
const approvedDrafts = computed(() => props.drafts.filter(item => item.status === 'approved'))
const filteredCandidates = computed(() => candidateFilter.value === 'all' ? props.candidates : props.candidates.filter(item => item.candidate_type === candidateFilter.value))
watch(approvedDrafts, items => { if (items.length && !items.some(item => item.draft_id === runForm.draft_id)) runForm.draft_id = items[0].draft_id }, { immediate: true })

function stepState(step) { return compilerStepState(step, props) }
function setSelectedFile(event) { selectedFile.value = event.target.files?.[0] || null; if (selectedFile.value && !uploadDraft.title) uploadDraft.title = selectedFile.value.name.replace(/\.[^.]+$/, '') }
function setDroppedFile(event) { const file = event.dataTransfer.files?.[0]; if (file) { selectedFile.value = file; uploadDraft.title ||= file.name.replace(/\.[^.]+$/, '') } }
async function runAction(action) { actionError.value = ''; busy.value = true; try { await action() } catch (cause) { actionError.value = cause?.response?.data?.detail || cause.message } finally { busy.value = false } }
function submitUpload() { runAction(async () => { await emit('upload', selectedFile.value, { ...uploadDraft, observed_at: new Date(uploadDraft.observed_at).toISOString(), cutoff_at: new Date(uploadDraft.cutoff_at).toISOString() }); selectedFile.value = null; if (fileInput.value) fileInput.value.value = ''; activeStep.value = 'extract' }) }
function submitDraft() { emit('create-draft', { name: draftForm.name, candidate_ids: acceptedIds.value, duration_days: draftForm.duration_days, intensity: draftForm.intensity, propagation: draftForm.propagation, assumption_reason: draftForm.assumption_reason }) }
function downloadUrl(documentId) { return `/api/v8/organizations/${props.organization?.organization_id}/projects/${props.documents.find(item => item.document_id === documentId)?.project_id}/documents/${documentId}/download` }
function compactHash(value) { return compactCompilerHash(value) }
function formatBytes(value) { return bytesLabel(value) }
function shortTime(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '--' }
function locatorLabel(locator = {}) { return locator.page ? `第 ${locator.page} 页` : locator.start_line ? `第 ${locator.start_line}-${locator.end_line || locator.start_line} 行` : locator.start_row ? `CSV ${locator.start_row}-${locator.end_row || locator.start_row} 行` : '版本化快照' }
function typeLabel(type) { return ({ scenario_preset: '场景预设', country: '国家', supply_chain: '供应链', policy_action: '政策动作', relationship: '关系', event_date: '事件日期' })[type] || type }

const DraftList = defineComponent({
  props: { drafts: Array, canWrite: Boolean }, emits: ['submit', 'clone'],
  setup(draftProps, { emit: childEmit }) { return () => h('div', { class: 'compiler-list draft-list' }, (draftProps.drafts || []).map(draft => h('article', { key: draft.draft_id }, [h('span', { class: ['status', draft.status] }, draft.status), h('div', [h('strong', `${draft.name} · v${draft.version}`), h('small', `preset ${draft.scenario?.scenario_key || '--'} · ${draft.candidate_ids?.length || 0} candidates`)]), h('code', compactCompilerHash(draft.draft_hash)), h('div', { class: 'actions' }, [draftProps.canWrite && draft.status === 'draft' ? h('button', { type: 'button', class: 'secondary', 'data-testid': 'compiler-submit-draft', onClick: () => childEmit('submit', draft.draft_id) }, '提交并冻结') : null, draftProps.canWrite && ['approved', 'revision_requested', 'rejected'].includes(draft.status) ? h('button', { type: 'button', class: 'secondary', onClick: () => childEmit('clone', draft.draft_id) }, '克隆修订') : null])])) ) }
})
</script>

<style scoped>
.scenario-compiler{display:grid;gap:16px;color:#d9e9f2}.compiler-hero,.compiler-panel>header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.compiler-hero{padding:22px;border:1px solid rgba(72,202,228,.26);background:linear-gradient(135deg,rgba(10,31,47,.96),rgba(7,17,29,.98));border-radius:14px}.compiler-hero h3,.compiler-panel h3{margin:5px 0 7px;font-size:22px}.compiler-hero p{margin:0;max-width:820px;color:#8faabc}.compiler-eyebrow,.compiler-panel header span{display:flex;gap:7px;align-items:center;color:#50d7ef;font-size:12px;letter-spacing:.11em}.compiler-steps{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.compiler-steps button{display:grid;grid-template-columns:auto 1fr auto;align-items:center;text-align:left;gap:8px;padding:12px;border:1px solid #243f53;background:#0a1724;color:#8da8b9;border-radius:8px}.compiler-steps button.active{border-color:#31ccea;color:#e6faff;box-shadow:0 0 18px rgba(49,204,234,.12)}.compiler-steps button.done{border-color:rgba(42,215,157,.45);color:#72e3bd}.compiler-steps button span{font-family:monospace;color:#50d7ef}.compiler-panel{padding:18px;border:1px solid #203a4d;background:rgba(6,17,28,.94);border-radius:12px;display:grid;gap:16px}.compiler-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.compiler-form label,.run-form label{display:grid;gap:6px;color:#9bb3c2;font-size:12px}.compiler-form input,.compiler-form textarea,.run-form input,.run-form select{box-sizing:border-box;width:100%;border:1px solid #29485c;background:#07131e;color:#e5f2f8;border-radius:7px;padding:9px}.form-span{grid-column:1/-1}.drop-zone{border:1px dashed #2a8da2;border-radius:10px;padding:24px;text-align:center;place-items:center;background:rgba(30,157,183,.06);cursor:pointer}.drop-zone input{position:absolute;opacity:0;pointer-events:none}.compiler-list,.review-list{display:grid;gap:8px}.compiler-list>article,.review-list>article{display:grid;grid-template-columns:auto minmax(180px,1fr) auto auto;align-items:center;gap:12px;padding:11px;border:1px solid #1d3445;background:#081722;border-radius:8px}.compiler-list small,.review-list small{display:block;color:#7592a5;margin-top:4px}.compiler-list code,.review-list code,.candidate-card code{color:#6dcfe2;font-size:11px}.status{padding:4px 7px;border:1px solid #365064;border-radius:999px;font-size:10px;text-transform:uppercase}.status.ready,.status.completed,.status.approved{border-color:#2ad79d;color:#65e8bd}.status.failed,.status.rejected{border-color:#ff6372;color:#ff8190}.status.extracting,.status.running,.status.submitted{border-color:#f6b84a;color:#f8c968}.actions{display:flex;gap:6px;align-items:center}.actions a{color:#58d8ee}.compiler-events{display:grid;gap:6px}.compiler-events article{display:grid;grid-template-columns:45px 180px 1fr;gap:9px;padding:8px;border-left:2px solid #2aaec8}.compiler-events p{margin:0;color:#819cac}.candidate-filters{display:flex;gap:6px;flex-wrap:wrap}.candidate-filters button{padding:6px 9px;background:#0a1a27;border:1px solid #294458;color:#87a5b7;border-radius:999px}.candidate-filters button.active{color:#60e4f5;border-color:#39cde6}.candidate-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.candidate-card{display:grid;gap:9px;padding:13px;border:1px solid #203d50;background:#081824;border-radius:9px}.candidate-card.invalid{border-color:rgba(255,91,109,.45)}.candidate-card header{display:grid;grid-template-columns:auto 1fr auto;gap:8px}.candidate-card header span{color:#4ed6ed}.candidate-card blockquote{margin:0;padding:8px;border-left:2px solid #37c9e3;color:#a7c0cd;background:#07121c}.candidate-card p{margin:0;color:#809bab;font-size:12px}.decision-line{color:#65e8bd;font-size:12px}.review-list>article{grid-template-columns:auto 1fr}.review-list pre{grid-column:1/-1;overflow:auto;max-height:240px;padding:10px;background:#050d14;color:#8ad9e7}.review-list .actions{grid-column:1/-1}.run-form{display:grid;grid-template-columns:2fr 1fr 1fr auto;align-items:end;gap:10px}.run-created{display:flex;gap:10px;padding:13px;border:1px solid #2a9d78;background:rgba(42,215,157,.07);border-radius:8px}.run-created code,.run-created small{display:block}.compiler-alert{padding:9px;border-radius:7px}.compiler-alert.error{color:#ff93a0;background:rgba(255,70,91,.08);border:1px solid rgba(255,70,91,.25)}.compiler-empty,.assumption-note{color:#7895a6}.accept{border-color:#2a9d78!important;color:#67e7be!important}.danger{border-color:#a94454!important;color:#ff8c98!important}@media(max-width:950px){.compiler-steps{grid-template-columns:repeat(3,1fr)}.candidate-grid{grid-template-columns:1fr}.run-form{grid-template-columns:1fr 1fr}.compiler-list>article{grid-template-columns:auto 1fr}.compiler-list .actions{grid-column:1/-1}}@media(max-width:600px){.compiler-steps,.compiler-form,.run-form{grid-template-columns:1fr}}
</style>
