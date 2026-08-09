import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { researchGovernanceClient } from '../api/researchGovernanceClient'
import type {
  EvidencePack,
  EvidencePackVerification,
  EvidenceSearchResult,
  ProjectEvidenceSummary,
  ResearchOrganization,
  ScenarioCandidate,
  ScenarioDraft,
  ScenarioDraftReviewRequest,
} from '../contracts/researchWorkspace'
import { buildGuidedGovernanceProjection } from './guidedGovernanceProjection'

interface GuidedGovernancePermissionSource {
  canWrite: boolean
  canReview: boolean
}

type MaybeRefOrGetter<T> = Ref<T> | ComputedRef<T> | (() => T) | T

const EMPTY_SEARCH: EvidenceSearchResult = {
  query: '',
  cutoff_at: null,
  total: 0,
  snapshots: [],
  claims: [],
}

function valueOf<T>(source: MaybeRefOrGetter<T>): T {
  if (typeof source === 'function') return (source as () => T)()
  if (source && typeof source === 'object' && 'value' in source) return (source as Ref<T>).value
  return source as T
}

function responseStatus(cause: unknown): number | null {
  const status = (cause as { response?: { status?: unknown } })?.response?.status
  return typeof status === 'number' ? status : null
}

function errorDetail(cause: unknown): string {
  const error = cause as { response?: { data?: { detail?: string } }; message?: string }
  return error?.response?.data?.detail || error?.message || '治理上下文请求失败。'
}

function preferredActiveDraft(drafts: ScenarioDraft[]): ScenarioDraft | null {
  return drafts.find(draft => draft.status !== 'superseded') || drafts[0] || null
}

function emptyPackVerification(draft: ScenarioDraft | null): EvidencePackVerification {
  return {
    draft_id: draft?.draft_id || '',
    pack_id: draft?.evidence_pack_id || '',
    expected_manifest_hash: draft?.evidence_pack_hash || '',
    status: 'not_required',
    reason: draft ? '该 Draft 尚未绑定 Evidence Pack。' : '尚未选择 Scenario Draft。',
    pack: null,
  }
}

function unavailablePackVerification(
  draft: ScenarioDraft,
  reason: string,
  status: EvidencePackVerification['status'] = 'unavailable',
): EvidencePackVerification {
  return {
    draft_id: draft.draft_id,
    pack_id: draft.evidence_pack_id || '',
    expected_manifest_hash: draft.evidence_pack_hash || '',
    status,
    reason,
    pack: null,
  }
}

export function useGuidedResearchGovernance(
  projectIdSource: MaybeRefOrGetter<string>,
  permissionsSource: MaybeRefOrGetter<GuidedGovernancePermissionSource>,
) {
  const organization = ref<ResearchOrganization | null>(null)
  const evidenceSummary = ref<ProjectEvidenceSummary | null>(null)
  const searchResult = ref<EvidenceSearchResult>({ ...EMPTY_SEARCH })
  const candidates = ref<ScenarioCandidate[]>([])
  const drafts = ref<ScenarioDraft[]>([])
  const activeDraft = ref<ScenarioDraft | null>(null)
  const approvedDraft = ref<ScenarioDraft | null>(null)
  const parentDraft = ref<ScenarioDraft | null>(null)
  const activePackVerification = ref<EvidencePackVerification>(emptyPackVerification(null))
  const approvedPackVerification = ref<EvidencePackVerification>(emptyPackVerification(null))
  const loading = ref(false)
  const mutationBusy = ref(false)
  const error = ref('')
  const actionError = ref('')
  let mutationInFlight: Promise<unknown> | null = null
  let mutationInFlightKey = ''
  let selectionGeneration = 0
  let refreshGeneration = 0
  let loadGeneration = 0
  let searchGeneration = 0

  const projectId = () => valueOf(projectIdSource)
  const permissions = () => valueOf(permissionsSource)

  async function verifyDraftEvidencePack(
    draft: ScenarioDraft,
    expectedProjectId: string,
  ): Promise<EvidencePackVerification> {
    if (draft.project_id !== expectedProjectId) {
      return unavailablePackVerification(
        draft,
        `Scenario Draft project_id ${draft.project_id || '缺失'} 与当前项目 ${expectedProjectId} 不一致。`,
        'project_mismatch',
      )
    }
    if (!draft.evidence_pack_id && !draft.evidence_pack_hash) return emptyPackVerification(draft)
    if (!draft.evidence_pack_id || !draft.evidence_pack_hash) {
      return unavailablePackVerification(draft, 'Scenario Draft 缺少 Evidence Pack ID 或 Hash。', 'missing')
    }

    let pack: EvidencePack
    try {
      pack = await researchGovernanceClient.getEvidencePack(draft.evidence_pack_id)
    } catch (cause) {
      const status = responseStatus(cause)
      if (status === 409) {
        return unavailablePackVerification(
          draft,
          `Evidence Pack 后端完整性校验失败（409）：${errorDetail(cause)}`,
          'unavailable',
        )
      }
      if (status === 404) {
        return unavailablePackVerification(
          draft,
          `Evidence Pack 不存在或不可访问（404）：${errorDetail(cause)}`,
          'missing',
        )
      }
      return unavailablePackVerification(
        draft,
        `Evidence Pack 后端验证读取失败${status ? `（${status}）` : ''}：${errorDetail(cause)}`,
      )
    }

    if (!pack.pack_id || pack.pack_id !== draft.evidence_pack_id) {
      return unavailablePackVerification(
        draft,
        `Evidence Pack pack_id ${pack.pack_id || '缺失'} 与 Draft 绑定 ID ${draft.evidence_pack_id} 不一致。`,
        'mismatch',
      )
    }
    if (!pack.project_id) {
      return unavailablePackVerification(draft, 'Evidence Pack 缺少 project_id，无法验证项目绑定。', 'missing')
    }
    if (pack.project_id !== expectedProjectId || pack.project_id !== draft.project_id) {
      return unavailablePackVerification(
        draft,
        `Evidence Pack project_id ${pack.project_id} 与 Scenario Draft/当前项目不一致。`,
        'project_mismatch',
      )
    }
    if (!pack.manifest_hash || pack.manifest_hash !== draft.evidence_pack_hash) {
      return unavailablePackVerification(
        draft,
        'Evidence Pack manifest_hash 与 Scenario Draft evidence_pack_hash 不一致。',
        'mismatch',
      )
    }
    return {
      draft_id: draft.draft_id,
      pack_id: pack.pack_id,
      expected_manifest_hash: draft.evidence_pack_hash,
      status: 'verified',
      reason: 'Evidence Pack 已通过后端完整性读取，并与当前 Draft 的项目和 manifest_hash 一致。',
      pack,
    }
  }

  async function selectDraft(draftId: string) {
    const generation = ++selectionGeneration
    const organizationId = organization.value?.organization_id
    const selectedProjectId = projectId()
    if (!organizationId || !selectedProjectId || !draftId) {
      if (generation === selectionGeneration) {
        activeDraft.value = null
        parentDraft.value = null
        activePackVerification.value = emptyPackVerification(null)
      }
      return null
    }

    try {
      const selectedDraft = await researchGovernanceClient.getScenarioDraft(
        organizationId,
        selectedProjectId,
        draftId,
      )
      const [selectedParent, selectedPackVerification] = await Promise.all([
        selectedDraft.parent_draft_id
          ? researchGovernanceClient.getScenarioDraft(
            organizationId,
            selectedProjectId,
            selectedDraft.parent_draft_id,
          ).catch(() => null)
          : Promise.resolve(null),
        verifyDraftEvidencePack(selectedDraft, selectedProjectId),
      ])

      if (generation !== selectionGeneration) return selectedDraft
      activeDraft.value = selectedDraft
      parentDraft.value = selectedParent
      activePackVerification.value = selectedPackVerification
      actionError.value = ''
      if (selectedDraft.status === 'approved') {
        approvedDraft.value = selectedDraft
        approvedPackVerification.value = selectedPackVerification
      }
      return selectedDraft
    } catch (cause) {
      if (generation === selectionGeneration) {
        activeDraft.value = null
        parentDraft.value = null
        activePackVerification.value = emptyPackVerification(null)
        actionError.value = errorDetail(cause)
      }
      throw cause
    }
  }

  async function refreshApprovedDraft(
    approvedSummary: ScenarioDraft | null,
    generation: number,
    organizationId: string,
    selectedProjectId: string,
  ) {
    if (!approvedSummary) {
      if (generation === refreshGeneration) {
        approvedDraft.value = null
        approvedPackVerification.value = emptyPackVerification(null)
      }
      return
    }
    if (activeDraft.value?.draft_id === approvedSummary.draft_id) {
      if (generation === refreshGeneration) {
        approvedDraft.value = activeDraft.value
        approvedPackVerification.value = activePackVerification.value
      }
      return
    }

    let approvedDetail = approvedSummary
    let verification: EvidencePackVerification
    try {
      approvedDetail = await researchGovernanceClient.getScenarioDraft(
        organizationId,
        selectedProjectId,
        approvedSummary.draft_id,
      )
      verification = await verifyDraftEvidencePack(approvedDetail, selectedProjectId)
    } catch (cause) {
      verification = unavailablePackVerification(
        approvedSummary,
        `Approved Scenario Draft detail 无法验证：${errorDetail(cause)}`,
      )
    }
    if (generation !== refreshGeneration) return
    approvedDraft.value = approvedDetail
    approvedPackVerification.value = verification
  }

  async function refreshDrafts(preferredDraftId = '') {
    const generation = ++refreshGeneration
    const organizationId = organization.value?.organization_id
    const selectedProjectId = projectId()
    if (!organizationId || !selectedProjectId) return
    const [nextCandidates, nextDrafts] = await Promise.all([
      researchGovernanceClient.listScenarioCandidates(organizationId, selectedProjectId),
      researchGovernanceClient.listScenarioDrafts(organizationId, selectedProjectId),
    ])
    if (generation !== refreshGeneration) return
    candidates.value = nextCandidates
    drafts.value = nextDrafts
    const selected = nextDrafts.find(draft => draft.draft_id === preferredDraftId)
      || preferredActiveDraft(nextDrafts)
    if (selected) await selectDraft(selected.draft_id)
    else {
      ++selectionGeneration
      activeDraft.value = null
      parentDraft.value = null
      activePackVerification.value = emptyPackVerification(null)
    }
    await refreshApprovedDraft(
      nextDrafts.find(draft => draft.status === 'approved') || null,
      generation,
      organizationId,
      selectedProjectId,
    )
  }

  async function load() {
    const generation = ++loadGeneration
    const selectedProjectId = projectId()
    if (!selectedProjectId) return null
    loading.value = true
    error.value = ''
    actionError.value = ''
    organization.value = null
    try {
      const [nextOrganization, nextEvidenceSummary] = await Promise.all([
        researchGovernanceClient.getCurrentOrganization(),
        researchGovernanceClient.getProjectEvidenceSummary(selectedProjectId),
      ])
      if (generation !== loadGeneration || selectedProjectId !== projectId()) return null
      organization.value = nextOrganization
      evidenceSummary.value = nextEvidenceSummary
      await refreshDrafts(activeDraft.value?.draft_id || '')
      return projection.value
    } catch (cause) {
      if (generation === loadGeneration) {
        error.value = errorDetail(cause)
        organization.value = null
        evidenceSummary.value = null
        candidates.value = []
        drafts.value = []
        activeDraft.value = null
        approvedDraft.value = null
        parentDraft.value = null
        activePackVerification.value = emptyPackVerification(null)
        approvedPackVerification.value = emptyPackVerification(null)
      }
      throw cause
    } finally {
      if (generation === loadGeneration) loading.value = false
    }
  }

  function runReadAction<T>(action: () => Promise<T>, isCurrent: () => boolean = () => true): Promise<T> {
    actionError.value = ''
    return action().catch((cause) => {
      if (isCurrent()) actionError.value = errorDetail(cause)
      throw cause
    })
  }

  function rejectMutation<T>(reason: string): Promise<T> {
    actionError.value = reason
    return Promise.reject(new Error(reason))
  }

  function runMutation<T>(key: string, action: () => Promise<T>): Promise<T> {
    if (mutationInFlight) {
      return rejectMutation<T>(`治理写操作 ${mutationInFlightKey} 正在进行，请等待其完成。`)
    }
    actionError.value = ''
    mutationBusy.value = true
    const promise = Promise.resolve()
      .then(action)
      .catch((cause) => {
        actionError.value = errorDetail(cause)
        throw cause
      })
      .finally(() => {
        if (mutationInFlight === promise) {
          mutationInFlight = null
          mutationInFlightKey = ''
          mutationBusy.value = false
        }
      })
    mutationInFlight = promise
    mutationInFlightKey = key
    return promise
  }

  function deniedMutation(action: 'write' | 'review'): Promise<never> {
    const permission = projection.value.permissions[action]
    return rejectMutation<never>(permission.reason)
  }

  function syncEvidence(runId: string | null = null) {
    if (!projection.value.permissions.write.allowed) return deniedMutation('write')
    return runMutation(`syncEvidence:${runId || ''}`, async () => {
      const result = await researchGovernanceClient.syncProjectEvidence(projectId(), runId)
      evidenceSummary.value = result.summary
      return result
    })
  }

  function searchEvidence(query = '', cutoffAt: string | null = null) {
    const generation = ++searchGeneration
    const normalizedQuery = query.trim()
    return runReadAction(async () => {
      const result = await researchGovernanceClient.searchEvidence({
        query: normalizedQuery,
        project_id: projectId(),
        cutoff_at: cutoffAt || undefined,
        limit: 100,
      })
      if (generation === searchGeneration) searchResult.value = result
      return result
    }, () => generation === searchGeneration)
  }

  function submitDraft(draftId: string) {
    if (!projection.value.permissions.write.allowed) return deniedMutation('write')
    return runMutation(`submitDraft:${draftId}`, async () => {
      const organizationId = organization.value?.organization_id || ''
      const updated = await researchGovernanceClient.submitScenarioDraft(organizationId, projectId(), draftId)
      await refreshDrafts(updated.draft_id)
      return updated
    })
  }

  function reviewDraft(draftId: string, payload: ScenarioDraftReviewRequest) {
    if (!projection.value.permissions.review.allowed) return deniedMutation('review')
    if (payload.decision === 'approve') {
      const active = projection.value.scenario.activeDraft
      if (active?.draft_id !== draftId || projection.value.scenario.activePackVerification.status !== 'verified') {
        return rejectMutation<ScenarioDraft>('批准前必须完成当前 Scenario Draft 的 Evidence Pack 后端完整性与 lineage 验证。')
      }
    }
    return runMutation(`reviewDraft:${draftId}:${payload.decision}`, async () => {
      const organizationId = organization.value?.organization_id || ''
      const updated = await researchGovernanceClient.reviewScenarioDraft(
        organizationId,
        projectId(),
        draftId,
        payload,
      )
      await refreshDrafts(updated.draft_id)
      return updated
    })
  }

  function cloneDraft(draftId: string) {
    if (!projection.value.permissions.write.allowed) return deniedMutation('write')
    return runMutation(`cloneDraft:${draftId}`, async () => {
      const organizationId = organization.value?.organization_id || ''
      const cloned = await researchGovernanceClient.cloneScenarioDraft(organizationId, projectId(), draftId)
      await refreshDrafts(cloned.draft_id)
      return cloned
    })
  }

  const projection = computed(() => {
    const permission = permissions()
    return buildGuidedGovernanceProjection({
      organization: organization.value,
      evidenceSummary: evidenceSummary.value,
      searchResult: searchResult.value,
      candidates: candidates.value,
      drafts: drafts.value,
      activeDraft: activeDraft.value,
      approvedDraft: approvedDraft.value,
      parentDraft: parentDraft.value,
      activePackVerification: activePackVerification.value,
      approvedPackVerification: approvedPackVerification.value,
      loading: loading.value,
      mutationBusy: mutationBusy.value,
      error: error.value,
      actionError: actionError.value,
      canWrite: permission.canWrite,
      canReview: permission.canReview,
    })
  })

  return {
    organization,
    evidenceSummary,
    searchResult,
    candidates,
    drafts,
    activeDraft,
    approvedDraft,
    parentDraft,
    activePackVerification,
    approvedPackVerification,
    loading,
    mutationBusy,
    error,
    actionError,
    projection,
    load,
    selectDraft,
    syncEvidence,
    searchEvidence,
    submitDraft,
    reviewDraft,
    cloneDraft,
  }
}
