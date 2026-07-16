export const compilerSteps = [
  ['upload', '01', '材料上传'],
  ['extract', '02', '文本抽取'],
  ['candidates', '03', '候选核验'],
  ['draft', '04', '场景草稿'],
  ['review', '05', '双人审批'],
  ['run', '06', '创建运行'],
]

export function scenarioCompilerSummary(documents = [], candidates = [], drafts = []) {
  const latestApproved = drafts.find(item => item.status === 'approved') || null
  return {
    documentCount: documents.length,
    pendingCandidateCount: candidates.filter(item => item.validation_status === 'valid' && !item.latest_decision).length,
    pendingDraftCount: drafts.filter(item => item.status === 'submitted').length,
    latestApproved,
  }
}

export function acceptedCandidateIds(candidates = []) {
  return candidates.filter(item => item.validation_status === 'valid' && item.latest_decision?.decision === 'accepted').map(item => item.candidate_id)
}

export function compilerStepState(step, state) {
  const approved = state.drafts?.some(item => item.status === 'approved')
  const submitted = state.drafts?.some(item => item.status === 'submitted')
  const accepted = acceptedCandidateIds(state.candidates).length > 0
  const completedJob = state.jobs?.some(item => item.status === 'completed')
  const hasDocument = state.documents?.length > 0
  const done = { upload: hasDocument, extract: completedJob, candidates: accepted, draft: state.drafts?.length > 0, review: approved, run: Boolean(state.lastRun) }
  const active = step === 'upload' ? !hasDocument
    : step === 'extract' ? hasDocument && !completedJob
      : step === 'candidates' ? completedJob && !accepted
        : step === 'draft' ? accepted && !state.drafts?.length
          : step === 'review' ? Boolean(state.drafts?.length) && !approved
            : approved && !state.lastRun
  return done[step] ? 'done' : active || (step === 'review' && submitted) ? 'active' : 'pending'
}

export function compactCompilerHash(value) {
  return value ? `${String(value).slice(0, 12)}…` : '--'
}

export function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(2)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}
