import type {
  EvidencePackVerification,
  EvidenceSearchResult,
  GuidedGovernancePermission,
  GuidedGovernanceProjection,
  GuidedGovernanceState,
  GuidedGovernanceStep,
  GuidedResearchGovernanceState,
  GuidedScenarioDiff,
  OrganizationRole,
  ScenarioDraft,
} from '../contracts/researchWorkspace'

const EMPTY_SEARCH_RESULT: EvidenceSearchResult = {
  query: '',
  cutoff_at: null,
  total: 0,
  snapshots: [],
  claims: [],
}

const STEP_ORDER: GuidedGovernanceState[] = ['candidate', 'draft', 'review', 'approved', 'frozen']
const STEP_LABELS: Record<GuidedGovernanceState, string> = {
  candidate: '候选',
  draft: '草稿',
  review: '审阅',
  approved: '批准',
  frozen: '冻结',
}
const ORGANIZATION_WRITE_ROLES = new Set<OrganizationRole>(['owner', 'admin', 'analyst'])
const ORGANIZATION_REVIEW_ROLES = new Set<OrganizationRole>(['owner', 'admin', 'reviewer'])

function firstActiveDraft(drafts: ScenarioDraft[]): ScenarioDraft | null {
  return drafts.find(draft => draft.status !== 'superseded') || drafts[0] || null
}

function firstApprovedDraft(drafts: ScenarioDraft[]): ScenarioDraft | null {
  return drafts.find(draft => draft.status === 'approved') || null
}

function governanceState(draft: ScenarioDraft | null): GuidedGovernanceState {
  if (!draft) return 'candidate'
  if (draft.status === 'submitted') return 'review'
  if (draft.status === 'approved') return 'frozen'
  return 'draft'
}

function stateSteps(state: GuidedGovernanceState, draft: ScenarioDraft | null): GuidedGovernanceStep[] {
  const currentIndex = STEP_ORDER.indexOf(state)
  return STEP_ORDER.map((key, index) => ({
    key,
    label: STEP_LABELS[key],
    status: index < currentIndex ? 'complete' : index === currentIndex ? 'current' : 'pending',
    reason: stepReason(key, state, draft),
  }))
}

function stepReason(
  key: GuidedGovernanceState,
  state: GuidedGovernanceState,
  draft: ScenarioDraft | null,
): string {
  if (key === 'candidate') {
    return '抽取结果仅为候选，必须经人工接受后才能进入草稿；候选本身不是已批准 Evidence。'
  }
  if (key === 'draft') {
    if (!draft) return '尚无受治理 Scenario Draft。'
    if (draft.status === 'revision_requested') return '审阅者已请求修订；须经 clone 路径创建新版本。'
    if (draft.status === 'rejected') return '该修订已被拒绝；须经 clone 路径创建新版本。'
    if (draft.status === 'superseded') return '该修订已被后续 clone 版本取代。'
    return '草稿仅可提交冻结，不能作为已批准场景。'
  }
  if (key === 'review') {
    return state === 'review'
      ? '草稿已提交，等待独立审阅者决定。'
      : '独立审阅由后端组织 RBAC 与异人审批规则强制执行。'
  }
  if (key === 'approved') {
    return draft?.status === 'approved'
      ? '后端已记录批准决定。'
      : '只有 approved 状态可通过场景门禁。'
  }
  return draft?.status === 'approved'
    ? '批准修订只读；任何修改都必须 clone 为新修订。'
    : '批准后固定 Draft 与 Evidence Pack Hash。'
}

function bannerFor(state: GuidedGovernanceState, draft: ScenarioDraft | null) {
  if (!draft) return {
    state,
    title: '候选治理上下文',
    detail: '尚无 Scenario Draft。抽取候选不是已批准 Evidence，也不会自动形成场景修订。',
  }
  const revision = `${draft.name} · v${draft.version}`
  if (draft.status === 'approved') return {
    state,
    title: `已批准并冻结：${revision}`,
    detail: '当前修订只读；任何修改只能通过受治理 clone 端点创建新版本。',
  }
  if (draft.status === 'submitted') return {
    state,
    title: `审阅中：${revision}`,
    detail: 'Draft 与 Evidence Pack 已冻结，等待具有审阅权限且非提交人的成员决定。',
  }
  if (draft.status === 'revision_requested') return {
    state,
    title: `请求修订：${revision}`,
    detail: '原修订保持只读；请通过受治理 clone 路径创建后继版本。',
  }
  if (draft.status === 'rejected') return {
    state,
    title: `已拒绝：${revision}`,
    detail: '该修订不能运行或原地编辑；如需继续，只能 clone 为新修订。',
  }
  if (draft.status === 'superseded') return {
    state,
    title: `已取代：${revision}`,
    detail: '该修订已被后续版本取代，保留为只读 lineage。',
  }
  return {
    state,
    title: `草稿上下文：${revision}`,
    detail: '草稿尚未批准；提交会冻结 Evidence Pack 与 Draft Hash。',
  }
}

function compareStoredFields(parent: ScenarioDraft, current: ScenarioDraft): string[] {
  const changed: string[] = []
  for (const section of ['scenario', 'manual_assumptions'] as const) {
    const keys = new Set([...Object.keys(parent[section] || {}), ...Object.keys(current[section] || {})])
    for (const key of [...keys].sort()) {
      if (JSON.stringify(parent[section]?.[key]) !== JSON.stringify(current[section]?.[key])) {
        changed.push(`${section}.${key}`)
      }
    }
  }
  if (parent.draft_hash !== current.draft_hash) changed.push('draft_hash')
  if (parent.evidence_pack_id !== current.evidence_pack_id) changed.push('evidence_pack_id')
  if (parent.evidence_pack_hash !== current.evidence_pack_hash) changed.push('evidence_pack_hash')
  return changed
}

function draftSnapshot(draft: ScenarioDraft) {
  return {
    version: draft.version,
    draft_hash: draft.draft_hash || '',
    evidence_pack_id: draft.evidence_pack_id || '',
    evidence_pack_hash: draft.evidence_pack_hash || '',
    scenario: draft.scenario,
    manual_assumptions: draft.manual_assumptions,
  }
}

export function buildGuidedScenarioDiff(
  current: ScenarioDraft | null,
  parent: ScenarioDraft | null,
): GuidedScenarioDiff {
  const empty: GuidedScenarioDiff = {
    available: false,
    unavailable_reason: '',
    parent_draft_id: current?.parent_draft_id || '',
    current_draft_id: current?.draft_id || '',
    original: null,
    current: null,
    changed_fields: [],
  }
  if (!current) return { ...empty, unavailable_reason: '尚未选择 Scenario Draft detail。' }
  if (!current.parent_draft_id) {
    return { ...empty, unavailable_reason: '当前为根修订，没有 parent_draft_id；完整修订详情仍在上方只读展示。' }
  }
  if (!parent || parent.draft_id !== current.parent_draft_id) {
    return { ...empty, unavailable_reason: '父修订 detail 不可用；不构造推测性 Diff。' }
  }
  return {
    available: true,
    unavailable_reason: '',
    parent_draft_id: parent.draft_id,
    current_draft_id: current.draft_id,
    original: draftSnapshot(parent),
    current: draftSnapshot(current),
    changed_fields: compareStoredFields(parent, current),
  }
}

function evidenceGateReasons(state: GuidedResearchGovernanceState): string[] {
  const summary = state.evidenceSummary
  if (state.error) return [`治理上下文加载失败：${state.error}`]
  if (!summary) return ['Evidence summary 不可用。']
  if (summary.integrity_status === 'failed') return ['Evidence 完整性校验失败。']
  if (summary.integrity_status === 'empty') return ['尚无受治理 Evidence 快照或声明。']
  if (!summary.cutoff_safe) return ['Evidence cutoff 校验未通过。']
  if (!summary.snapshot_count && !summary.claim_count) return ['Evidence summary 未包含可验证快照或声明。']
  return []
}

function emptyPackVerification(draft: ScenarioDraft | null): EvidencePackVerification {
  return {
    draft_id: draft?.draft_id || '',
    pack_id: draft?.evidence_pack_id || '',
    expected_manifest_hash: draft?.evidence_pack_hash || '',
    status: draft?.evidence_pack_id || draft?.evidence_pack_hash ? 'unavailable' : 'not_required',
    reason: draft?.evidence_pack_id || draft?.evidence_pack_hash
      ? '尚未通过后端读取验证 Evidence Pack。'
      : '该 Draft 尚未绑定 Evidence Pack。',
    pack: null,
  }
}

function packLineageGateReasons(
  draft: ScenarioDraft,
  packVerification: EvidencePackVerification,
): string[] {
  const reasons: string[] = []
  if (!draft.draft_hash) reasons.push('Scenario 修订缺少 Draft Hash。')
  if (!draft.evidence_pack_id || !draft.evidence_pack_hash) {
    reasons.push('Scenario 修订缺少冻结 Evidence Pack ID/Hash。')
  } else if (
    packVerification.draft_id !== draft.draft_id
    || packVerification.pack_id !== draft.evidence_pack_id
    || packVerification.expected_manifest_hash !== draft.evidence_pack_hash
  ) {
    reasons.push('Evidence Pack 验证结果未绑定当前 Scenario Draft lineage。')
  } else if (packVerification.status !== 'verified') {
    reasons.push(packVerification.reason || 'Evidence Pack 后端验证未通过。')
  }
  return reasons
}

function scenarioGateReasons(
  draft: ScenarioDraft | null,
  evidenceReasons: string[],
  packVerification: EvidencePackVerification,
): string[] {
  if (!draft) return ['尚无受治理 Scenario Draft。']
  const statusReason = {
    draft: 'Scenario Draft 尚未提交审批。',
    submitted: 'Scenario Draft 正在等待独立审阅。',
    revision_requested: 'Scenario Draft 被请求修订；必须 clone 后重新提交。',
    rejected: 'Scenario Draft 已被拒绝。',
    superseded: 'Scenario Draft 已被后续修订取代。',
  }[draft.status] || `Scenario Draft 状态 ${draft.status} 尚未批准。`
  const reasons = draft.status === 'approved'
    ? [...evidenceReasons]
    : [statusReason]
  if (draft.status === 'approved' || draft.status === 'submitted') {
    reasons.push(...packLineageGateReasons(draft, packVerification))
  }
  return reasons
}

function effectivePermission(
  organizationRole: OrganizationRole | null | undefined,
  globalAllowed: boolean,
  allowedRoles: Set<OrganizationRole>,
  actionLabel: string,
): GuidedGovernancePermission {
  if (!organizationRole) {
    return { allowed: false, reason: `当前组织尚未加载成员角色；${actionLabel}默认拒绝。` }
  }
  if (!globalAllowed) {
    return { allowed: false, reason: `当前全局 Session 无${actionLabel}权限。` }
  }
  if (!allowedRoles.has(organizationRole)) {
    return { allowed: false, reason: `当前组织角色 ${organizationRole} 无${actionLabel}权限。` }
  }
  return {
    allowed: true,
    reason: `全局 Session 与组织角色 ${organizationRole} 均允许发起${actionLabel}；后端仍独立校验 RBAC 与资源作用域。`,
  }
}

export function buildGuidedGovernanceProjection(
  state: GuidedResearchGovernanceState,
): GuidedGovernanceProjection {
  const current = state.activeDraft || firstActiveDraft(state.drafts)
  const approved = state.approvedDraft || firstApprovedDraft(state.drafts)
  const currentState = governanceState(current)
  const evidenceReasons = evidenceGateReasons(state)
  const activeVerification = state.activePackVerification || emptyPackVerification(current)
  const approvedVerification = approved?.draft_id === current?.draft_id
    ? activeVerification
    : (state.approvedPackVerification || emptyPackVerification(approved))
  const scenarioDraft = approved || current
  const scenarioVerification = approved ? approvedVerification : activeVerification
  const organizationRole = state.organization?.member_role
  return {
    schema_version: 'guided-governance-projection.v1',
    loading: state.loading,
    busy: Boolean(state.mutationBusy),
    error: state.actionError || state.error,
    banner: bannerFor(currentState, current),
    evidence: {
      summary: state.evidenceSummary,
      searchResult: state.searchResult || EMPTY_SEARCH_RESULT,
      gate_reasons: evidenceReasons,
    },
    scenario: {
      candidates: state.candidates,
      drafts: state.drafts,
      activeDraft: current,
      approvedDraft: approved,
      parentDraft: state.parentDraft,
      activePackVerification: activeVerification,
      approvedPackVerification: approvedVerification,
      state: currentState,
      steps: stateSteps(currentState, current),
      gate_reasons: scenarioGateReasons(scenarioDraft, evidenceReasons, scenarioVerification),
      diff: buildGuidedScenarioDiff(current, state.parentDraft),
    },
    permissions: {
      write: effectivePermission(organizationRole, state.canWrite, ORGANIZATION_WRITE_ROLES, '写入'),
      review: effectivePermission(organizationRole, state.canReview, ORGANIZATION_REVIEW_ROLES, '审阅'),
    },
  }
}
