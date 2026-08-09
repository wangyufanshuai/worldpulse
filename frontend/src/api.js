import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  withCredentials: true
})

const ORGANIZATION_STORAGE_KEY = 'worldpulse_organization'

export function getActiveOrganization() {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(ORGANIZATION_STORAGE_KEY) || ''
}

export function setActiveOrganization(organizationId) {
  if (typeof window === 'undefined') return
  if (organizationId) window.localStorage.setItem(ORGANIZATION_STORAGE_KEY, organizationId)
  else window.localStorage.removeItem(ORGANIZATION_STORAGE_KEY)
}

api.interceptors.request.use((config) => {
  config.headers ||= {}
  const organizationId = getActiveOrganization()
  if (organizationId && !config.skipOrganization) config.headers['X-WorldPulse-Org'] = organizationId
  const method = String(config.method || 'get').toLowerCase()
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const token = document.cookie.split('; ').find(item => item.startsWith('worldpulse_csrf='))?.split('=').slice(1).join('=')
    if (token) config.headers['X-CSRF-Token'] = decodeURIComponent(token)
  }
  return config
})

export async function login(username, password) {
  const { data } = await api.post('/v3/auth/login', { username, password })
  return data
}

export async function logout() {
  const { data } = await api.post('/v3/auth/logout')
  return data
}

export async function getCurrentUser() {
  const { data } = await api.get('/v3/auth/me')
  return data
}

export async function getTrustSummary(projectId) {
  const { data } = await api.get(`/v3/projects/${projectId}/trust-summary`)
  return data
}

export async function getProjectEvidenceSummary(projectId) {
  const { data } = await api.get(`/v4/projects/${projectId}/evidence-summary`)
  return data
}

export async function syncProjectEvidence(projectId, runId = null) {
  const { data } = await api.post(`/v4/projects/${projectId}/evidence/sync`, null, { params: runId ? { run_id: runId } : {} })
  return data
}

export async function searchEvidence(params = {}) {
  const { data } = await api.get('/v4/evidence/search', { params })
  return data
}

export async function createEvidencePack(payload) {
  const { data } = await api.post('/v4/evidence/packs', payload)
  return data
}

export async function getEvidencePack(packId) {
  const { data } = await api.get(`/v4/evidence/packs/${packId}`)
  return data
}

export async function syncCalibrationEvidence() {
  const { data } = await api.post('/v4/evidence/calibration/sync')
  return data
}

export async function listOrganizations() {
  const { data } = await api.get('/v5/organizations', { skipOrganization: true })
  return data
}

export async function getCurrentOrganization() {
  const { data } = await api.get('/v5/organizations/current')
  return data
}

export async function listOrganizationMembers(organizationId) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/members`)
  return data
}

export async function listOrganizationProjects(organizationId) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/projects`)
  return data
}

export async function getIngestionSummary(organizationId) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/ingestion/summary`)
  return data
}

export async function createDataConnector(organizationId, payload) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/connectors`, payload)
  return data
}

export async function createIngestionJob(organizationId, payload) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs`, payload)
  return data
}

export async function executeIngestionJob(organizationId, jobId) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/execute`)
  return data
}

export async function cancelIngestionJob(organizationId, jobId) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/cancel`)
  return data
}

export async function retryIngestionJob(organizationId, jobId) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/retry`)
  return data
}

export async function getIngestionEvents(organizationId, jobId, afterSeq = 0) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/events`, { params: { after_seq: afterSeq } })
  return data
}

export async function getPlatformReadiness() {
  const { data } = await api.get('/v6/platform/readiness')
  return data
}

export async function listWorkerNodes() {
  const { data } = await api.get('/v6/workers')
  return data
}

export async function drainWorkerNode(workerId) {
  const { data } = await api.post(`/v6/workers/${workerId}/drain`)
  return data
}

export async function getOrganizationOperations(organizationId) {
  const { data } = await api.get(`/v6/organizations/${organizationId}/operations`)
  return data
}

export async function updateOrganizationQuota(organizationId, payload) {
  const { data } = await api.put(`/v6/organizations/${organizationId}/quota`, payload)
  return data
}

export async function listReviews(status = null) {
  const { data } = await api.get('/v3/reviews', { params: status ? { status } : {} })
  return data
}

export async function decideReview(reviewId, decision, comment = '') {
  const { data } = await api.post(`/v3/reviews/${reviewId}/decision`, { decision, comment })
  return data
}

export async function listRulePacks() {
  const { data } = await api.get('/v3/rule-packs')
  return data
}

export async function listCalibrationCases() {
  const { data } = await api.get('/v3/calibration/cases')
  return data
}

export async function createCalibrationRun(rulePackId, caseIds = []) {
  const { data } = await api.post('/v3/calibration/runs', { rule_pack_id: rulePackId, case_ids: caseIds })
  return data
}

export async function getRiskOverview() {
  const { data } = await api.get('/risk/overview', { timeout: 8000 })
  return data
}

export async function listProjects() {
  const { data } = await api.get('/projects')
  return data
}

export async function createProject(payload) {
  const { data } = await api.post('/projects', payload)
  return data
}

export async function getProject(projectId) {
  const { data } = await api.get(`/projects/${projectId}`)
  return data
}

export async function getProjectRun(projectId, runId) {
  const { data } = await api.get(`/projects/${projectId}/runs/${runId}`)
  return data
}

export async function compareProjectRuns(projectId, baseRunId, targetRunId) {
  const { data } = await api.get(`/projects/${projectId}/runs/compare`, {
    params: { base_run_id: baseRunId, target_run_id: targetRunId }
  })
  return data
}

export async function listProjectRuns(projectId) {
  const { data } = await api.get(`/projects/${projectId}/runs`)
  return data
}

export async function runProject(projectId, mode = 'fast') {
  const { data } = await api.post(`/projects/${projectId}/run`, null, { params: { mode } })
  return data
}

export async function getWarRoomPresets() {
  const { data } = await api.get('/war-room/presets')
  return data
}

export async function runProjectWarRoom(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/war-room/run`, payload)
  return data
}

export async function createLifecycleRun(projectId, payload) {
  const { data } = await api.post(`/v2/projects/${projectId}/runs`, payload)
  return data
}

export async function getLifecycleRun(runId) {
  const { data } = await api.get(`/v2/runs/${runId}`)
  return data
}

export async function getLifecycleEvents(runId, afterSeq = 0) {
  const { data } = await api.get(`/v2/runs/${runId}/events`, { params: { after_seq: afterSeq } })
  return data
}

export async function getLifecycleAudit(runId) {
  const { data } = await api.get(`/v2/runs/${runId}/audit`)
  return data
}

export async function listAgentPacks() {
  const { data } = await api.get('/v7/agent-packs')
  return data
}

export async function getRunNegotiation(runId) {
  const { data } = await api.get(`/v7/runs/${runId}/negotiation`)
  return data
}

export async function getNegotiationRounds(runId) {
  const { data } = await api.get(`/v7/runs/${runId}/negotiation/rounds`)
  return data
}

export async function getNegotiationMessages(runId, params = {}) {
  const { data } = await api.get(`/v7/runs/${runId}/negotiation/messages`, { params })
  return data
}

export async function getNegotiationCommitments(runId) {
  const { data } = await api.get(`/v7/runs/${runId}/negotiation/commitments`)
  return data
}

export async function uploadSourceDocument(organizationId, projectId, formData) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/documents`, formData)
  return data
}

export async function listSourceDocuments(organizationId, projectId) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/documents`)
  return data
}

export function sourceDocumentDownloadUrl(organizationId, projectId, documentId) {
  return `/api/v8/organizations/${organizationId}/projects/${projectId}/documents/${documentId}/download`
}

export async function createDocumentExtraction(organizationId, projectId, documentId) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/documents/${documentId}/extract`)
  return data
}

export async function getDocumentExtractionJob(organizationId, projectId, jobId) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/extraction-jobs/${jobId}`)
  return data
}

export async function listDocumentExtractionJobs(organizationId, projectId) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/extraction-jobs`)
  return data
}

export async function getDocumentExtractionEvents(organizationId, projectId, jobId, afterSeq = 0) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/extraction-jobs/${jobId}/events`, { params: { after_seq: afterSeq } })
  return data
}

export async function cancelDocumentExtraction(organizationId, projectId, jobId) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/extraction-jobs/${jobId}/cancel`)
  return data
}

export async function retryDocumentExtraction(organizationId, projectId, jobId) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/extraction-jobs/${jobId}/retry`)
  return data
}

export async function listScenarioCandidates(organizationId, projectId) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-candidates`)
  return data
}

export async function decideScenarioCandidate(organizationId, projectId, candidateId, payload) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-candidates/${candidateId}/decision`, payload)
  return data
}

export async function listScenarioDrafts(organizationId, projectId) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts`)
  return data
}

export async function getScenarioDraft(organizationId, projectId, draftId) {
  const { data } = await api.get(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts/${draftId}`)
  return data
}

export async function createScenarioDraft(organizationId, projectId, payload) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts`, payload)
  return data
}

export async function submitScenarioDraft(organizationId, projectId, draftId) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts/${draftId}/submit`)
  return data
}

export async function reviewScenarioDraft(organizationId, projectId, draftId, payload) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts/${draftId}/review`, payload)
  return data
}

export async function cloneScenarioDraft(organizationId, projectId, draftId) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts/${draftId}/clone`)
  return data
}

export async function runScenarioDraft(organizationId, projectId, draftId, payload) {
  const { data } = await api.post(`/v8/organizations/${organizationId}/projects/${projectId}/scenario-drafts/${draftId}/runs`, payload)
  return data
}

export async function listMonitoringSources(organizationId, projectId) {
  const { data } = await api.get(`/v9/organizations/${organizationId}/projects/${projectId}/monitoring/sources`)
  return data
}
export async function createMonitoringSource(organizationId, projectId, payload) {
  const { data } = await api.post(`/v9/organizations/${organizationId}/projects/${projectId}/monitoring/sources`, payload)
  return data
}
export async function pollMonitoringSource(organizationId, projectId, sourceId) {
  const { data } = await api.post(`/v9/organizations/${organizationId}/projects/${projectId}/monitoring/sources/${sourceId}/poll`)
  return data
}
export async function updateMonitoringSourceStatus(organizationId, projectId, sourceId, status) {
  const { data } = await api.post(`/v9/organizations/${organizationId}/projects/${projectId}/monitoring/sources/${sourceId}/status`, { status })
  return data
}
export async function listMonitoringPolls(organizationId, projectId) {
  const { data } = await api.get(`/v9/organizations/${organizationId}/projects/${projectId}/monitoring/polls`)
  return data
}
export async function listMonitoringWatchlists(organizationId, projectId) {
  const { data } = await api.get(`/v9/organizations/${organizationId}/projects/${projectId}/watchlists`)
  return data
}
export async function createMonitoringWatchlist(organizationId, projectId, payload) {
  const { data } = await api.post(`/v9/organizations/${organizationId}/projects/${projectId}/watchlists`, payload)
  return data
}
export async function updateMonitoringWatchlistStatus(organizationId, projectId, watchlistId, action) {
  const { data } = await api.post(`/v9/organizations/${organizationId}/projects/${projectId}/watchlists/${watchlistId}/${action}`)
  return data
}
export async function listIntelligenceAlerts(organizationId, projectId, params = {}) {
  const { data } = await api.get(`/v9/organizations/${organizationId}/projects/${projectId}/alerts`, { params })
  return data
}
export async function updateIntelligenceAlert(organizationId, projectId, alertId, action) {
  const { data } = await api.post(`/v9/organizations/${organizationId}/projects/${projectId}/alerts/${alertId}/${action}`)
  return data
}
export async function getContinuousIntelligenceSummary(organizationId, projectId) {
  const { data } = await api.get(`/v9/organizations/${organizationId}/projects/${projectId}/intelligence/summary`)
  return data
}
export async function listNotifications(params = {}) {
  const { data } = await api.get('/v9/notifications', { params })
  return data
}

export async function listEvaluationSuites() { const { data } = await api.get('/v10/evaluation/suites'); return data }
export async function listEvaluationBatches(organizationId) { const { data } = await api.get(`/v10/organizations/${organizationId}/evaluations`); return data }
export async function createStandardEvaluation(organizationId, payload = {}) { const { data } = await api.post(`/v10/organizations/${organizationId}/evaluations/standard`, payload); return data }
export async function createObservationEvaluation(organizationId, payload = {}) { const { data } = await api.post(`/v10/organizations/${organizationId}/evaluations/observation`, payload); return data }
export async function getEvaluation(batchId) { const { data } = await api.get(`/v10/evaluations/${batchId}`); return data }
export async function getEvaluationMembers(batchId) { const { data } = await api.get(`/v10/evaluations/${batchId}/members`); return data }
export async function getEvaluationMetrics(batchId) { const { data } = await api.get(`/v10/evaluations/${batchId}/metrics`); return data }
export async function getEvaluationReport(batchId) { const { data } = await api.get(`/v10/evaluations/${batchId}/report`); return data }
export async function controlEvaluation(batchId, action) { const { data } = await api.post(`/v10/evaluations/${batchId}/${action}`); return data }
export async function listHistoricalBenchmarkSuites() { const { data } = await api.get('/v11/evaluation/benchmark-suites'); return data }
export async function listHistoricalBenchmarkCases(suiteId) { const { data } = await api.get(`/v11/evaluation/benchmark-suites/${suiteId}/cases`); return data }
export async function listEvaluationLabelPacks(organizationId) { const { data } = await api.get(`/v11/organizations/${organizationId}/evaluation/label-packs`); return data }
export async function createHistoricalEvaluation(organizationId, payload) { const { data } = await api.post(`/v11/organizations/${organizationId}/evaluations/historical`, payload); return data }
export async function getEvaluationVerification(batchId) { const { data } = await api.get(`/v11/evaluations/${batchId}/verification`); return data }
export async function getHistoricalEvaluationReport(batchId) { const { data } = await api.get(`/v11/evaluations/${batchId}/historical-report`); return data }
export async function markNotificationRead(notificationId) {
  const { data } = await api.post(`/v9/notifications/${notificationId}/read`)
  return data
}
export async function markAllNotificationsRead() {
  const { data } = await api.post('/v9/notifications/read-all')
  return data
}
export function notificationEventStreamUrl(afterSeq = 0) {
  const organizationId = getActiveOrganization()
  const organizationQuery = organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''
  return `/api/v9/notifications/stream?after_seq=${encodeURIComponent(afterSeq)}${organizationQuery}`
}

export async function pauseLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/pause`)
  return data
}

export async function resumeLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/resume`)
  return data
}

export async function cancelLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/cancel`)
  return data
}

export async function retryLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/retry`)
  return data
}

export function lifecycleEventStreamUrl(runId, afterSeq = 0) {
  const organizationId = getActiveOrganization()
  const organizationQuery = organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''
  return `/api/v2/runs/${runId}/events/stream?after_seq=${encodeURIComponent(afterSeq)}${organizationQuery}`
}

export async function getWarRoomReplayPack(projectId, params = {}) {
  const { data } = await api.get(`/projects/${projectId}/war-room/replay-pack`, { params })
  return data
}

export async function getWarRoomWorkspace(projectId, params = {}) {
  const { data } = await api.get(`/projects/${projectId}/war-room/workspace`, { params })
  return data
}

export async function updateProjectGraph(projectId, payload) {
  const { data } = await api.patch(`/projects/${projectId}/graph`, payload)
  return data
}

export async function getProjectGraph(projectId) {
  const { data } = await api.get(`/projects/${projectId}/graph`)
  return data
}

export async function getProjectReport(projectId) {
  const { data } = await api.get(`/projects/${projectId}/report`)
  return data
}

export async function chatWithProject(projectId, message) {
  const { data } = await api.post(`/projects/${projectId}/chat`, { message })
  return data
}
