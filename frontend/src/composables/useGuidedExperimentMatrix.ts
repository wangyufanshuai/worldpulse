import {
  computed,
  getCurrentScope,
  onScopeDispose,
  ref,
  watch,
  type ComputedRef,
  type Ref,
} from 'vue'
import { researchExperimentClient } from '../api/researchExperimentClient'
import type {
  EvaluationBatch,
  EvaluationMember,
  EvaluationMetric,
  EvidencePackVerification,
  ResearchOrganization,
  ScenarioDraft,
} from '../contracts/researchWorkspace'
import { buildGuidedExperimentMatrixProjection } from './guidedExperimentMatrixProjection'

type MaybeRefOrGetter<T> = Ref<T> | ComputedRef<T> | (() => T) | T
const TERMINAL_POLL_INTERVAL_MS = 2_000

interface MatrixLoadContext {
  projectId: string
  organizationId: string
  draftId: string
  draftOrganizationId: string
  draftProjectId: string
  draftStatus: string
  draftHash: string
  evidencePackId: string
  evidencePackHash: string
  verificationDraftId: string
  verificationPackId: string
  verificationExpectedHash: string
  verificationStatus: string
  verifiedPackId: string
  verifiedPackProjectId: string
  verifiedPackManifestHash: string
  phase4BGateSignature: string
}

function valueOf<T>(source: MaybeRefOrGetter<T>): T {
  if (typeof source === 'function') return (source as () => T)()
  if (source && typeof source === 'object' && 'value' in source) return (source as Ref<T>).value
  return source as T
}

function errorDetail(cause: unknown): string {
  const error = cause as { response?: { data?: { detail?: string } }; message?: string }
  return error?.response?.data?.detail || error?.message || '受治理实验矩阵读取失败。'
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0
}

function selectNewestBatch(batches: EvaluationBatch[]): EvaluationBatch | null {
  return [...batches].sort((left, right) => (
    compareText(right.created_at || '', left.created_at || '')
    || compareText(right.batch_id || '', left.batch_id || '')
  ))[0] || null
}

function sameContext(left: MatrixLoadContext, right: MatrixLoadContext): boolean {
  return Object.keys(left).every(key => (
    left[key as keyof MatrixLoadContext] === right[key as keyof MatrixLoadContext]
  ))
}

function contextToken(context: MatrixLoadContext | null): string {
  return context ? JSON.stringify(context) : ''
}

function detailDriftReasons(
  detail: EvaluationBatch,
  listed: EvaluationBatch,
  context: MatrixLoadContext,
): string[] {
  const reasons: string[] = []
  if (detail.batch_id !== listed.batch_id) reasons.push('detail.batch_id 与选中批次不一致')
  if (detail.organization_id !== context.organizationId) reasons.push('detail.organization_id 漂移')
  if (detail.project_id !== context.projectId) reasons.push('detail.project_id 漂移')
  if (detail.scenario_draft_id !== context.draftId) reasons.push('detail.scenario_draft_id 漂移')
  if (detail.scenario_draft_hash !== context.draftHash) reasons.push('detail.scenario_draft_hash 漂移')
  if (detail.evidence_pack_hash !== context.evidencePackHash) reasons.push('detail.evidence_pack_hash 漂移')
  if (detail.evaluation_track !== 'project_experiment' || detail.source_type !== 'project') {
    reasons.push('detail 不再是 project_experiment/project')
  }
  for (const key of [
    'organization_id', 'project_id', 'scenario_draft_id', 'scenario_draft_hash', 'evidence_pack_hash',
    'suite_id', 'suite_hash', 'rule_pack_id', 'rule_pack_hash', 'runtime_profile_hash',
    'evaluation_track', 'source_type', 'gate_manifest_hash', 'root_batch_id',
  ] as const) {
    if (detail[key] !== listed[key]) reasons.push(`detail.${key} 与列表快照不一致`)
  }
  return [...new Set(reasons)]
}

function responseDriftReasons(
  detail: EvaluationBatch,
  members: EvaluationMember[],
  metrics: EvaluationMetric[],
): string[] {
  const reasons: string[] = []
  if (members.some(member => member.batch_id !== detail.batch_id)) reasons.push('成员响应包含跨批次 batch_id')
  const memberIds = members.map(member => member.member_id)
  const knownMemberIds = new Set(memberIds)
  if (knownMemberIds.size !== memberIds.length) reasons.push('成员响应包含重复 member_id')
  if (members.length !== detail.total_members) reasons.push('成员响应数量与 detail.total_members 不一致')
  if (metrics.some(metric => metric.batch_id !== detail.batch_id)) reasons.push('指标响应包含跨批次 batch_id')
  if (metrics.some(metric => metric.member_id && !knownMemberIds.has(metric.member_id))) {
    reasons.push('指标响应引用了当前成员集合之外的 member_id')
  }
  return reasons
}

export function useGuidedExperimentMatrix(
  projectIdSource: MaybeRefOrGetter<string>,
  organizationSource: MaybeRefOrGetter<ResearchOrganization | null>,
  approvedDraftSource: MaybeRefOrGetter<ScenarioDraft | null>,
  approvedPackVerificationSource: MaybeRefOrGetter<EvidencePackVerification>,
  phase4BGateReasonsSource: MaybeRefOrGetter<string[]>,
) {
  const batch = ref<EvaluationBatch | null>(null)
  const members = ref<EvaluationMember[]>([])
  const metrics = ref<EvaluationMetric[]>([])
  const loading = ref(false)
  const error = ref('')
  const loadedContextToken = ref('')
  let loadGeneration = 0
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let inFlightToken = ''
  let inFlightPromise: Promise<ReturnType<typeof buildGuidedExperimentMatrixProjection>> | null = null
  let disposed = false

  const projectId = () => valueOf(projectIdSource)
  const organization = () => valueOf(organizationSource)
  const approvedDraft = () => valueOf(approvedDraftSource)
  const approvedPackVerification = () => valueOf(approvedPackVerificationSource)
  const phase4BGateReasons = () => valueOf(phase4BGateReasonsSource)

  function clear() {
    batch.value = null
    members.value = []
    metrics.value = []
    loadedContextToken.value = ''
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function captureContext(): MatrixLoadContext | null {
    const selectedProjectId = projectId()
    const selectedOrganization = organization()
    const selectedDraft = approvedDraft()
    const verification = approvedPackVerification()
    if (!selectedProjectId || !selectedOrganization?.organization_id || !selectedDraft) return null
    return {
      projectId: selectedProjectId,
      organizationId: selectedOrganization.organization_id,
      draftId: selectedDraft.draft_id || '',
      draftOrganizationId: selectedDraft.organization_id || '',
      draftProjectId: selectedDraft.project_id || '',
      draftStatus: selectedDraft.status || '',
      draftHash: selectedDraft.draft_hash || '',
      evidencePackId: selectedDraft.evidence_pack_id || '',
      evidencePackHash: selectedDraft.evidence_pack_hash || '',
      verificationDraftId: verification.draft_id || '',
      verificationPackId: verification.pack_id || '',
      verificationExpectedHash: verification.expected_manifest_hash || '',
      verificationStatus: verification.status || '',
      verifiedPackId: verification.pack?.pack_id || '',
      verifiedPackProjectId: verification.pack?.project_id || '',
      verifiedPackManifestHash: verification.pack?.manifest_hash || '',
      phase4BGateSignature: JSON.stringify(phase4BGateReasons()),
    }
  }

  function isLoadableContext(context: MatrixLoadContext | null): context is MatrixLoadContext {
    return Boolean(
      context
      && context.draftId
      && context.draftStatus === 'approved'
      && context.draftOrganizationId === context.organizationId
      && context.draftProjectId === context.projectId
      && context.draftHash
      && context.evidencePackId
      && context.evidencePackHash
      && context.verificationStatus === 'verified'
      && context.verificationDraftId === context.draftId
      && context.verificationPackId === context.evidencePackId
      && context.verificationExpectedHash === context.evidencePackHash
      && context.verifiedPackId === context.evidencePackId
      && context.verifiedPackProjectId === context.projectId
      && context.verifiedPackManifestHash === context.evidencePackHash
      && context.phase4BGateSignature === '[]'
    )
  }

  function contextIsCurrent(context: MatrixLoadContext, generation: number): boolean {
    const current = captureContext()
    return !disposed && generation === loadGeneration && Boolean(current && sameContext(context, current))
  }

  function abortStaleContext(context: MatrixLoadContext, generation: number): boolean {
    if (contextIsCurrent(context, generation)) return false
    if (generation === loadGeneration) {
      loadGeneration += 1
      stopPolling()
      clear()
      error.value = '研究项目、组织或 Scenario/Evidence Pack lineage 在读取期间发生变化；矩阵已清空。'
      loading.value = false
    }
    return true
  }

  function detachInFlight() {
    inFlightToken = ''
    inFlightPromise = null
  }

  async function performLoad(
    context: MatrixLoadContext,
    generation: number,
  ): Promise<ReturnType<typeof buildGuidedExperimentMatrixProjection>> {
    try {
      const batches = await researchExperimentClient.listEvaluationBatches(context.organizationId)
      if (abortStaleContext(context, generation)) return projection.value
      const selectedBatch = selectNewestBatch(batches.filter(item => (
        item.evaluation_track === 'project_experiment'
        && item.source_type === 'project'
        && item.organization_id === context.organizationId
        && item.project_id === context.projectId
        && item.scenario_draft_id === context.draftId
        && item.scenario_draft_hash === context.draftHash
        && item.evidence_pack_hash === context.evidencePackHash
      )))
      if (!selectedBatch) {
        clear()
        loadedContextToken.value = contextToken(context)
        return projection.value
      }

      // Validate the captured project/org/draft/pack context after every
      // awaited contract. Nothing is committed to Vue refs until the complete
      // response set is coherent.
      const detail = await researchExperimentClient.getEvaluation(selectedBatch.batch_id)
      if (abortStaleContext(context, generation)) return projection.value
      const detailDrift = detailDriftReasons(detail, selectedBatch, context)
      if (detailDrift.length) throw new Error(`V10 批次 detail lineage 漂移：${detailDrift.join('；')}`)

      const nextMembers = await researchExperimentClient.getEvaluationMembers(selectedBatch.batch_id)
      if (abortStaleContext(context, generation)) return projection.value
      const memberDrift = responseDriftReasons(detail, nextMembers, [])
      if (memberDrift.length) throw new Error(`V10 成员 lineage 漂移：${memberDrift.join('；')}`)

      const nextMetrics = await researchExperimentClient.getEvaluationMetrics(selectedBatch.batch_id)
      if (abortStaleContext(context, generation)) return projection.value
      const responseDrift = responseDriftReasons(detail, nextMembers, nextMetrics)
      if (responseDrift.length) throw new Error(`V10 指标 lineage 漂移：${responseDrift.join('；')}`)
      if (abortStaleContext(context, generation)) return projection.value

      batch.value = detail
      members.value = nextMembers
      metrics.value = nextMetrics
      loadedContextToken.value = contextToken(context)
      scheduleTerminalPoll(detail, context)
      return projection.value
    } catch (cause) {
      if (!contextIsCurrent(context, generation)) return projection.value
      clear()
      error.value = errorDetail(cause)
      throw cause
    } finally {
      if (generation === loadGeneration) loading.value = false
    }
  }

  async function loadForContext(forceRefresh: boolean) {
    if (disposed) return projection.value

    const context = captureContext()
    const token = contextToken(context)
    if (!isLoadableContext(context)) {
      loadGeneration += 1
      stopPolling()
      detachInFlight()
      clear()
      error.value = ''
      loading.value = false
      return projection.value
    }

    if (inFlightPromise && inFlightToken === token) return inFlightPromise
    if (!forceRefresh && loadedContextToken.value === token && !error.value) return projection.value

    stopPolling()
    const generation = ++loadGeneration
    error.value = ''
    clear()
    loading.value = true

    const request = performLoad(context, generation)
    inFlightToken = token
    inFlightPromise = request
    try {
      return await request
    } finally {
      if (inFlightPromise === request) detachInFlight()
    }
  }

  function load() {
    return loadForContext(false)
  }

  function scheduleTerminalPoll(detail: EvaluationBatch, context: MatrixLoadContext) {
    stopPolling()
    if (
      disposed
      || !['queued', 'running'].includes(detail.status)
      || loadedContextToken.value !== contextToken(context)
    ) return
    pollTimer = setTimeout(() => {
      pollTimer = null
      if (disposed) return
      const current = captureContext()
      if (!current || !sameContext(context, current)) return
      void loadForContext(true).catch(() => undefined)
    }, TERMINAL_POLL_INTERVAL_MS)
  }

  const projection = computed(() => {
    const currentContext = captureContext()
    const storedDataIsCurrent = Boolean(
      currentContext
      && loadedContextToken.value
      && loadedContextToken.value === contextToken(currentContext),
    )
    return buildGuidedExperimentMatrixProjection({
      projectId: projectId(),
      organizationId: organization()?.organization_id || '',
      approvedDraft: approvedDraft(),
      approvedPackVerification: approvedPackVerification(),
      phase4BGateReasons: phase4BGateReasons(),
      batch: storedDataIsCurrent ? batch.value : null,
      members: storedDataIsCurrent ? members.value : [],
      metrics: storedDataIsCurrent ? metrics.value : [],
      loading: loading.value,
      error: error.value,
    })
  })

  const stopContextWatcher = watch(
    () => contextToken(captureContext()),
    (nextToken, previousToken) => {
      if (nextToken === previousToken || disposed) return
      loadGeneration += 1
      stopPolling()
      detachInFlight()
      clear()
      loading.value = false
      error.value = ''
      const nextContext = captureContext()
      if (isLoadableContext(nextContext)) void load().catch(() => undefined)
    },
    { flush: 'sync' },
  )

  function dispose() {
    if (disposed) return
    disposed = true
    loadGeneration += 1
    stopPolling()
    detachInFlight()
    stopContextWatcher()
    clear()
    error.value = ''
    loading.value = false
  }

  if (getCurrentScope()) onScopeDispose(dispose)

  return {
    batch,
    members,
    metrics,
    loading,
    error,
    projection,
    load,
    dispose,
  }
}
