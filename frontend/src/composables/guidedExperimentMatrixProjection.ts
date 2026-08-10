import type {
  EvaluationBatch,
  EvaluationMember,
  EvaluationMetric,
  EvidencePackVerification,
  GuidedExperimentMatrixProjection,
  GuidedExperimentMatrixRow,
  ScenarioDraft,
} from '../contracts/researchWorkspace'

const FIXED_V10_POPULATION = 7
const VISIBLE_ROW_CAP = 6 as const
const MODE_ORDER: Record<EvaluationMember['engine_mode'], number> = {
  deterministic: 0,
  hybrid: 1,
  negotiation: 2,
}
const FIXED_MEMBER_SIGNATURES = [
  'deterministic:1',
  'hybrid:11',
  'hybrid:29',
  'hybrid:47',
  'negotiation:11',
  'negotiation:29',
  'negotiation:47',
]
const CANONICAL_PARAMETER_SEEDS = [11, 29, 47] as const

export interface GuidedExperimentMatrixState {
  projectId: string
  organizationId: string
  approvedDraft: ScenarioDraft | null
  approvedPackVerification: EvidencePackVerification
  phase4BGateReasons: string[]
  batch: EvaluationBatch | null
  members: EvaluationMember[]
  metrics: EvaluationMetric[]
  loading: boolean
  error: string
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0
}

export function canonicalExperimentMembers(members: EvaluationMember[]): EvaluationMember[] {
  return [...members].sort((left, right) => (
    MODE_ORDER[left.engine_mode] - MODE_ORDER[right.engine_mode]
    || left.seed - right.seed
    || compareText(left.case_id || '', right.case_id || '')
    || compareText(left.input_hash || '', right.input_hash || '')
    || compareText(left.member_id || '', right.member_id || '')
  ))
}

function canonicalMetrics(metrics: EvaluationMetric[]): EvaluationMetric[] {
  return [...metrics].sort((left, right) => (
    compareText(left.member_id || '', right.member_id || '')
    || compareText(left.scope || '', right.scope || '')
    || compareText(left.metric_key || '', right.metric_key || '')
    || compareText(left.metric_hash || '', right.metric_hash || '')
    || compareText(left.metric_id || '', right.metric_id || '')
  ))
}

function approvedDraftAndPackReasons(state: GuidedExperimentMatrixState): string[] {
  const reasons = [...state.phase4BGateReasons]
  const draft = state.approvedDraft
  const verification = state.approvedPackVerification
  if (!draft) return [...reasons, '缺少 approved/frozen Scenario Draft。']
  if (draft.status !== 'approved') reasons.push(`Scenario Draft 状态 ${draft.status} 尚未 approved/frozen。`)
  if (draft.organization_id !== state.organizationId) reasons.push('Scenario Draft organization_id 与当前组织不一致。')
  if (draft.project_id !== state.projectId) reasons.push('Scenario Draft project_id 与当前项目不一致。')
  if (!draft.draft_hash) reasons.push('Scenario 修订缺少 Draft Hash。')
  if (!draft.evidence_pack_id || !draft.evidence_pack_hash) {
    reasons.push('Scenario 修订缺少冻结 Evidence Pack ID/Hash。')
    return reasons
  }
  if (
    verification.draft_id !== draft.draft_id
    || verification.pack_id !== draft.evidence_pack_id
    || verification.expected_manifest_hash !== draft.evidence_pack_hash
  ) {
    reasons.push('Evidence Pack 验证结果未绑定当前 Scenario Draft lineage。')
  }
  if (verification.status !== 'verified') {
    reasons.push(verification.reason || `Evidence Pack 验证状态 ${verification.status} 未通过。`)
  }
  if (!verification.pack) {
    reasons.push('Evidence Pack detail 未加载，不能验证冻结 lineage。')
  } else {
    if (verification.pack.pack_id !== draft.evidence_pack_id) reasons.push('Evidence Pack detail ID 与 Scenario Draft 不一致。')
    if (verification.pack.project_id !== state.projectId) reasons.push('Evidence Pack detail project_id 与当前项目不一致。')
    if (verification.pack.manifest_hash !== draft.evidence_pack_hash) reasons.push('Evidence Pack detail manifest_hash 与 Scenario Draft 不一致。')
  }
  return [...new Set(reasons)]
}

function requiredBatchLineageReasons(batch: EvaluationBatch): string[] {
  const reasons: string[] = []
  if (!batch.batch_id) reasons.push('批次缺少 batch_id。')
  if (!batch.suite_id || !batch.suite_hash) reasons.push('批次缺少 Evaluation Suite ID/Hash。')
  if (!batch.rule_pack_id || !batch.rule_pack_hash) reasons.push('批次缺少 Rule Pack ID/Hash。')
  if (!batch.runtime_profile_hash) reasons.push('批次缺少 runtime_profile_hash。')
  if (!batch.gate_manifest_hash) reasons.push('批次缺少 gate_manifest_hash。')
  if (!batch.root_batch_id) reasons.push('批次缺少 root_batch_id。')
  return reasons
}

function memberLineageReasons(batch: EvaluationBatch, member: EvaluationMember): string[] {
  const reasons: string[] = []
  if (!member.member_id) reasons.push('成员缺少 member_id。')
  if (member.batch_id !== batch.batch_id) reasons.push('成员 batch_id 与当前批次不一致。')
  if (!member.case_id) reasons.push('成员缺少 case_id。')
  if (!member.input_hash) reasons.push('缺少存储的 EvaluationMember.input_hash。')
  if (!member.run_id) reasons.push('成员尚未绑定已存 Run ID。')
  if (member.status !== 'completed') reasons.push(`成员状态 ${member.status || 'unknown'} 尚无可比较的完成结果。`)
  if (!member.completed_at) reasons.push('成员缺少 completed_at。')
  if (!member.baseline_result_hash) reasons.push('成员缺少 baseline_result_hash。')
  if (!member.expected_baseline_hash) reasons.push('成员缺少 expected_baseline_hash。')
  if (!member.result_hash) reasons.push('成员缺少 result_hash。')
  if (!member.artifact_refs?.length) reasons.push('成员缺少已存 artifact_refs。')
  if (member.verification_status !== 'passed') {
    reasons.push(`成员 verification_status 必须精确为 passed，当前为 ${member.verification_status || 'missing'}。`)
  }
  if (!member.verification_hash) reasons.push('成员缺少 verification_hash。')
  return reasons
}

function canonicalParameterIdentityReasons(members: EvaluationMember[]): string[] {
  const reasons: string[] = []
  for (const seed of CANONICAL_PARAMETER_SEEDS) {
    const seedMembers = members.filter(member => member.seed === seed)
    const inputHashes = new Set(seedMembers.map(member => member.input_hash).filter(Boolean))
    if (seedMembers.length !== 2 || inputHashes.size !== 1) {
      reasons.push(
        `seed ${seed} 的 hybrid/negotiation 成员必须共享同一存储 input_hash，当前 canonical parameter identity 不一致。`,
      )
    }
  }
  return reasons
}

function wholeBatchComparabilityReasons(
  batch: EvaluationBatch,
  members: EvaluationMember[],
): string[] {
  const reasons: string[] = []
  if (batch.status !== 'completed') {
    reasons.push(`批次状态必须精确为 completed，当前为 ${batch.status || 'unknown'}。`)
  }
  if (batch.safety_status !== 'passed') {
    reasons.push(`批次 safety_status 必须精确为 passed，当前为 ${batch.safety_status || 'missing'}。`)
  }
  if (batch.completed_members !== FIXED_V10_POPULATION || batch.failed_members !== 0) {
    reasons.push(`批次聚合计数必须为 completed=${FIXED_V10_POPULATION}、failed=0，当前为 completed=${batch.completed_members}、failed=${batch.failed_members}。`)
  }
  if (!batch.report_hash) reasons.push('批次缺少 report_hash。')
  if (!batch.completed_at) reasons.push('批次缺少 completed_at，尚无可比较的完成快照。')
  if (batch.total_members !== FIXED_V10_POPULATION || members.length !== FIXED_V10_POPULATION) {
    reasons.push(`批次必须包含完整 ${FIXED_V10_POPULATION} 成员后才可比较。`)
  }
  reasons.push(...requiredBatchLineageReasons(batch))
  const incompleteMembers = members.filter(member => memberLineageReasons(batch, member).length > 0)
  if (incompleteMembers.length) {
    reasons.push(`固定 7 成员中有 ${incompleteMembers.length} 个未达到 terminal/completed、verification passed 与完整 lineage 门禁。`)
  }
  reasons.push(...canonicalParameterIdentityReasons(members))
  return [...new Set(reasons)]
}

function matrixLineageReasons(state: GuidedExperimentMatrixState): string[] {
  const reasons = approvedDraftAndPackReasons(state)
  const { approvedDraft, batch } = state
  if (!batch) {
    reasons.push('当前项目与修订没有已存储的 V10 project_experiment 批次。')
    return [...new Set(reasons)]
  }
  if (batch.evaluation_track !== 'project_experiment' || batch.source_type !== 'project') {
    reasons.push('批次不是 V10 受治理的 project_experiment。')
  }
  if (batch.organization_id !== state.organizationId) reasons.push('批次 organization_id 与当前组织不一致。')
  if (batch.project_id !== state.projectId) reasons.push('批次 project_id 与当前项目不一致。')
  if (approvedDraft && batch.scenario_draft_id !== approvedDraft.draft_id) {
    reasons.push('批次 Scenario Draft ID 与当前 approved 修订不一致。')
  }
  if (approvedDraft && (!batch.scenario_draft_hash || batch.scenario_draft_hash !== approvedDraft.draft_hash)) {
    reasons.push('批次 Scenario Draft Hash 缺失或与当前 approved 修订不一致。')
  }
  if (approvedDraft && (!batch.evidence_pack_hash || batch.evidence_pack_hash !== approvedDraft.evidence_pack_hash)) {
    reasons.push('批次 Evidence Pack Hash 缺失或与当前 approved 修订不一致。')
  }
  reasons.push(...requiredBatchLineageReasons(batch))
  if (batch.total_members !== FIXED_V10_POPULATION) {
    reasons.push(`V10 project_experiment 固定成员数应为 ${FIXED_V10_POPULATION}，当前合同值为 ${batch.total_members}。`)
  }
  if (state.members.length !== FIXED_V10_POPULATION || state.members.length !== batch.total_members) {
    reasons.push(`固定七成员读取不完整：批次声明 ${batch.total_members}，实际读取 ${state.members.length}。`)
  }
  const memberIds = state.members.map(member => member.member_id)
  if (new Set(memberIds).size !== memberIds.length) reasons.push('成员列表包含重复 member_id。')
  if (state.members.some(member => member.batch_id !== batch.batch_id)) reasons.push('成员列表包含跨批次 lineage。')
  const caseIds = new Set(state.members.map(member => member.case_id).filter(Boolean))
  if (state.members.length && caseIds.size !== 1) reasons.push('project_experiment 固定成员未绑定同一已存 case_id。')
  const signatures = canonicalExperimentMembers(state.members).map(member => `${member.engine_mode}:${member.seed}`)
  if (signatures.join('|') !== FIXED_MEMBER_SIGNATURES.join('|')) {
    reasons.push('V10 project_experiment 成员模式/seed 不符合固定七成员合同。')
  }
  reasons.push(...canonicalParameterIdentityReasons(state.members))
  const knownMemberIds = new Set(memberIds)
  if (state.metrics.some(metric => metric.batch_id !== batch.batch_id)) reasons.push('指标列表包含跨批次 lineage。')
  if (state.metrics.some(metric => metric.member_id && !knownMemberIds.has(metric.member_id))) {
    reasons.push('指标列表引用了当前批次之外的 member_id。')
  }
  if (batch.status === 'completed') {
    if (batch.safety_status !== 'passed') {
      reasons.push(`完成批次的 safety_status 必须为 passed，当前为 ${batch.safety_status || 'missing'}。`)
    }
    if (batch.completed_members !== FIXED_V10_POPULATION || batch.failed_members !== 0) {
      reasons.push(`完成批次聚合计数不一致：completed=${batch.completed_members}，failed=${batch.failed_members}。`)
    }
    if (!batch.report_hash) reasons.push('完成批次缺少 report_hash。')
    const incompleteMembers = state.members.filter(member => memberLineageReasons(batch, member).length > 0)
    if (incompleteMembers.length) {
      reasons.push(`完成批次的固定 7 成员中有 ${incompleteMembers.length} 个未通过完整行级 lineage 门禁。`)
    }
  }
  return [...new Set(reasons)]
}

function projectRow(
  batch: EvaluationBatch,
  member: EvaluationMember,
  metrics: EvaluationMetric[],
  matrixReasons: string[],
  batchComparabilityReasons: string[],
): GuidedExperimentMatrixRow {
  const memberMetrics = canonicalMetrics(metrics.filter(metric => metric.member_id === member.member_id))
  const reasons = [...matrixReasons, ...batchComparabilityReasons, ...memberLineageReasons(batch, member)]
  return {
    matrix_id: batch.batch_id,
    row_id: member.member_id,
    scenario_revision_id: batch.scenario_draft_id || '',
    scenario_revision_hash: batch.scenario_draft_hash || '',
    // input_hash is the immutable canonical scenario-parameter identity stored
    // by V10. The frontend aliases it and never recalculates numeric identity.
    parameter_set_hash: member.input_hash || '',
    role: null,
    role_unavailable_reason: 'V10 EvaluationMember 未存储 baseline/control/treated 角色；不得按数组顺序、engine_mode 或 seed 推断。',
    engine_mode: member.engine_mode,
    seed: member.seed,
    run_id: member.run_id || '',
    status: member.status,
    comparable: reasons.length === 0,
    non_comparable_reasons: [...new Set(reasons)],
    metrics_projection: member.metrics || {},
    evaluation_metrics: memberMetrics,
    uncertainty_unavailable_reason: 'V10 EvaluationMember/EvaluationMetric 未定义独立 uncertainty 字段；Phase 4C 不从通用 metrics 名称或内容推断。',
    plugin_lineage_unavailable_reason: 'V10 EvaluationMember 未定义 plugin lineage 字段；Phase 4C 不从通用 metrics 内容推断。',
    lineage: {
      evidence_pack_hash: batch.evidence_pack_hash || '',
      suite_id: batch.suite_id || '',
      suite_hash: batch.suite_hash || '',
      rule_pack_id: batch.rule_pack_id || '',
      rule_pack_hash: batch.rule_pack_hash || '',
      runtime_profile_hash: batch.runtime_profile_hash || '',
      gate_manifest_hash: batch.gate_manifest_hash || '',
      root_batch_id: batch.root_batch_id || '',
      report_hash: batch.report_hash || '',
      baseline_result_hash: member.baseline_result_hash || '',
      expected_baseline_hash: member.expected_baseline_hash || '',
      result_hash: member.result_hash || '',
      verification_hash: member.verification_hash || '',
      artifact_refs: member.artifact_refs || [],
    },
  }
}

export function buildGuidedExperimentMatrixProjection(
  state: GuidedExperimentMatrixState,
): GuidedExperimentMatrixProjection {
  const matrixReasons = matrixLineageReasons(state)
  const orderedMembers = canonicalExperimentMembers(state.members)
  const batchComparabilityReasons = state.batch
    ? wholeBatchComparabilityReasons(state.batch, state.members)
    : ['缺少已存储批次，当前行不可比较。']
  const rows = state.batch
    ? orderedMembers
      .slice(0, VISIBLE_ROW_CAP)
      .map(member => projectRow(
        state.batch as EvaluationBatch,
        member,
        state.metrics,
        matrixReasons,
        batchComparabilityReasons,
      ))
    : []
  const errorReasons = state.error ? [`V10 Experiment Matrix 读取失败：${state.error}`] : []
  const gateReasons = [...new Set([...errorReasons, ...matrixReasons])]

  return {
    schema_version: 'guided-experiment-matrix.v1',
    loading: state.loading,
    error: state.error,
    matrix_id: state.batch?.batch_id || '',
    project_id: state.projectId,
    execution_status: state.batch?.status || 'unavailable',
    fixed_population: FIXED_V10_POPULATION,
    visible_row_cap: VISIBLE_ROW_CAP,
    total_rows: state.members.length,
    hidden_row_count: Math.max(0, state.members.length - rows.length),
    rows,
    batch_metrics: canonicalMetrics(state.metrics.filter(metric => !metric.member_id)),
    gate: {
      verdict: gateReasons.length ? 'block' : 'pass',
      reasons: gateReasons,
    },
    source_contracts: [
      'GET /api/v10/organizations/{organization_id}/evaluations → EvaluationBatch[]',
      'GET /api/v10/evaluations/{batch_id} → EvaluationBatch',
      'GET /api/v10/evaluations/{batch_id}/members → EvaluationMember[]',
      'GET /api/v10/evaluations/{batch_id}/metrics → EvaluationMetric[]',
    ],
  }
}
