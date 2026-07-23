import { ref } from 'vue'
import { createCalibrationRun, decideReview, getTrustSummary } from '../api'
import { useContinuousIntelligence } from './useContinuousIntelligence'
import { useEvaluationCenter } from './useEvaluationCenter'
import { useEvidenceRegistry } from './useEvidenceRegistry'
import { useIngestionGovernance } from './useIngestionGovernance'
import { useOperationsCenter } from './useOperationsCenter'
import { useScenarioCompiler } from './useScenarioCompiler'

export function useWorkspaceGovernanceController({ projectId, isWarRoom, selectedRunId, showToast }) {
  const evidenceRegistry = useEvidenceRegistry(projectId)
  const ingestionGovernance = useIngestionGovernance(projectId)
  const continuousIntelligence = useContinuousIntelligence(projectId)
  const operationsCenter = useOperationsCenter()
  const scenarioCompiler = useScenarioCompiler(projectId)
  const evaluation = useEvaluationCenter()
  const trustSummary = ref(null)
  const trustLoading = ref(false)
  const trustError = ref('')
  const organizationId = () => ingestionGovernance.organization.value?.organization_id || 'org_default'

  async function loadTrustSummary() {
    if (!isWarRoom.value) return
    trustLoading.value = true
    trustError.value = ''
    try { trustSummary.value = await getTrustSummary(projectId()) }
    catch (error) { trustError.value = error?.response?.data?.detail || error.message }
    finally { trustLoading.value = false }
  }

  async function loadEvaluationCenter() {
    if (!isWarRoom.value) return
    await evaluation.load(organizationId())
    if (evaluation.latest.value) await evaluation.inspect(evaluation.latest.value.batch_id)
  }
  async function createEvaluationStandard() {
    const batch = await evaluation.createStandard(organizationId())
    showToast(`已创建评估批次 ${batch.batch_id}`)
    await evaluation.inspect(batch.batch_id)
  }
  async function createEvaluationHistorical(labelPackId) {
    try {
      const batch = await evaluation.createHistorical(organizationId(), labelPackId)
      showToast(`已创建历史盲测批次 ${batch.batch_id}`)
      await evaluation.inspect(batch.batch_id)
    } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function inspectEvaluation(batchId) { await evaluation.inspect(batchId) }
  async function controlEvaluationBatch(batchId, action) {
    try {
      const batch = await evaluation.control(batchId, action)
      showToast(`评估批次已${{ pause: '请求暂停', resume: '恢复', cancel: '请求取消', retry: '重试' }[action] || action}：${batch.status}`)
    } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  async function loadEvidenceSummary() {
    if (!isWarRoom.value) return
    try { await evidenceRegistry.load() } catch { /* module owns its scoped error */ }
  }
  async function syncEvidence() {
    try {
      const result = await evidenceRegistry.sync(selectedRunId.value || null)
      showToast(`证据链已同步：${result.snapshots_created} 个新快照，${result.claims_created} 条新声明`)
      await loadTrustSummary()
    } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function freezeEvidencePack() {
    try {
      const pack = await evidenceRegistry.createPack(selectedRunId.value || null)
      showToast(`证据包已冻结：${pack.manifest_hash.slice(0, 12)}`)
    } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function searchProjectEvidence(query, cutoffAt) {
    try { await evidenceRegistry.search(query, cutoffAt || null) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  async function loadIngestionGovernance() {
    if (!isWarRoom.value) return
    try { await ingestionGovernance.load() } catch { /* module owns its scoped error */ }
  }
  async function createGovernedConnector(payload) {
    try { const connector = await ingestionGovernance.createConnector(payload); showToast(`受控连接器已创建：${connector.name}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function submitGovernedIngestion({ record, connectorId }) {
    try {
      const job = await ingestionGovernance.ingest(record, connectorId)
      showToast(`采集完成：${job.accepted_count} 条记录，Manifest ${job.manifest_hash.slice(0, 12)}`)
      await loadEvidenceSummary(); await loadTrustSummary()
    } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function inspectIngestionEvents(jobId) {
    try { await ingestionGovernance.inspectEvents(jobId) } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function cancelIngestion(jobId) {
    try { await ingestionGovernance.cancel(jobId); showToast('采集任务已在写入快照前取消') }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function retryIngestion(jobId) {
    try { const job = await ingestionGovernance.retry(jobId); showToast(`重试完成：${job.job_id}`); await loadEvidenceSummary() }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  async function loadContinuousIntelligence() {
    if (!isWarRoom.value) return
    try {
      await continuousIntelligence.load(organizationId())
      await continuousIntelligence.loadNotifications()
      continuousIntelligence.subscribeNotifications()
    } catch { /* module owns its scoped error */ }
  }
  async function createContinuousSource(payload) {
    try { const result = await continuousIntelligence.createSource(payload, organizationId()); showToast(`持续情报 Source 已创建：${result.name}，请激活后开始轮询`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function pollContinuousSource(sourceId) {
    try { const result = await continuousIntelligence.poll(sourceId, organizationId()); showToast(`Feed 轮询已排队：${result.poll_id}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function setContinuousSourceStatus(sourceId, status) {
    try { await continuousIntelligence.setSourceStatus(sourceId, status, organizationId()); showToast(`Source 已${status === 'active' ? '启用' : '暂停'}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function createContinuousWatchlist(payload) {
    try { const result = await continuousIntelligence.createWatchlist(payload, organizationId()); showToast(`监测清单已创建：${result.name}，请激活后生效`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function setContinuousWatchlistStatus(id, action) {
    try { await continuousIntelligence.setWatchlistStatus(id, action, organizationId()); showToast(`监测清单已${action === 'activate' ? '激活' : '暂停'}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function setContinuousAlertStatus(id, action) {
    try { await continuousIntelligence.setAlertStatus(id, action, organizationId()); showToast('告警状态已更新') }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  async function loadOperationsCenter() {
    if (!isWarRoom.value) return
    try { await operationsCenter.load() } catch { /* module owns its scoped error */ }
  }
  async function saveOperationsQuota(payload) {
    try { await operationsCenter.saveQuota(payload); showToast('组织配额已更新，变更已追加审计记录') }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function drainOperationsWorker(workerId) {
    try { await operationsCenter.drain(workerId); showToast(`Worker ${workerId} 已进入安全排空状态`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  async function loadScenarioCompiler() {
    if (!isWarRoom.value) return
    try { await scenarioCompiler.load() } catch { /* module owns its scoped error */ }
  }
  async function uploadScenarioDocument(file, metadata) {
    try {
      const result = await scenarioCompiler.upload(file, metadata)
      showToast(result.deduplicated ? '相同材料已存在，已复用版本化文档' : `材料已安全保存：${result.document.title}`)
      await loadOperationsCenter()
    } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function extractScenarioDocument(documentId) {
    try { const job = await scenarioCompiler.extract(documentId); showToast(`抽取任务已排队：${job.job_id}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function inspectScenarioExtractionEvents(jobId) {
    try { await scenarioCompiler.events(jobId) } catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function cancelScenarioExtraction(jobId) {
    try { await scenarioCompiler.cancel(jobId); showToast('抽取任务将在安全阶段边界取消') }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function retryScenarioExtraction(jobId) {
    try { const job = await scenarioCompiler.retry(jobId); showToast(`抽取重试已创建：${job.job_id}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function decideScenarioCandidate(candidateId, payload) {
    try { await scenarioCompiler.decide(candidateId, payload); showToast(payload.decision === 'accepted' ? '候选已接受并追加审计' : '候选已拒绝并追加审计') }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function createCompiledScenarioDraft(payload) {
    try { const draft = await scenarioCompiler.createDraft(payload); showToast(`场景草稿已编译：v${draft.version}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function submitCompiledScenarioDraft(draftId) {
    try { const draft = await scenarioCompiler.submit(draftId); showToast(`Evidence Pack 已冻结：${String(draft.evidence_pack_hash).slice(0, 12)}`); await loadTrustSummary() }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function reviewCompiledScenarioDraft(draftId, payload) {
    try { await scenarioCompiler.review(draftId, payload); showToast('草稿复核决定已追加写入'); await loadTrustSummary() }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function cloneCompiledScenarioDraft(draftId) {
    try { const draft = await scenarioCompiler.clone(draftId); showToast(`已克隆为修订草稿 v${draft.version}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function runCompiledScenarioDraft(draftId, payload) {
    try { const job = await scenarioCompiler.run(draftId, payload); showToast(`受控运行已排队：${job.run_id}`) }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  async function startTrustCalibration(rulePackId) {
    try { const result = await createCalibrationRun(rulePackId); showToast(`校准任务已排队：${result.lifecycle_run_id}`); await loadTrustSummary() }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }
  async function submitReviewDecision(reviewId, decision) {
    try { await decideReview(reviewId, decision, '通过可信度中心提交'); showToast('复核决定已追加写入审计链'); await loadTrustSummary() }
    catch (error) { showToast(error?.response?.data?.detail || error.message) }
  }

  return {
    evidenceRegistry, ingestionGovernance, continuousIntelligence, operationsCenter,
    scenarioCompiler, evaluation, trustSummary, trustLoading, trustError,
    loadTrustSummary, loadEvaluationCenter, createEvaluationStandard,
    createEvaluationHistorical, inspectEvaluation, controlEvaluationBatch,
    loadEvidenceSummary, syncEvidence, freezeEvidencePack, searchProjectEvidence,
    loadIngestionGovernance, createGovernedConnector, submitGovernedIngestion,
    inspectIngestionEvents, cancelIngestion, retryIngestion,
    loadContinuousIntelligence, createContinuousSource, pollContinuousSource,
    setContinuousSourceStatus, createContinuousWatchlist, setContinuousWatchlistStatus,
    setContinuousAlertStatus, loadOperationsCenter, saveOperationsQuota,
    drainOperationsWorker, loadScenarioCompiler, uploadScenarioDocument,
    extractScenarioDocument, inspectScenarioExtractionEvents, cancelScenarioExtraction,
    retryScenarioExtraction, decideScenarioCandidate, createCompiledScenarioDraft,
    submitCompiledScenarioDraft, reviewCompiledScenarioDraft, cloneCompiledScenarioDraft,
    runCompiledScenarioDraft, startTrustCalibration, submitReviewDecision,
  }
}
