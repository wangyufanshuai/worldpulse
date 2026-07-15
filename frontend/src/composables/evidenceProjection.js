export function evidenceVerdict(summary) {
  if (summary?.integrity_status === 'failed') return { title: '证据完整性校验失败', label: 'FAIL CLOSED', className: 'blocked' }
  if (summary?.integrity_status === 'empty') return { title: '等待建立项目证据链', label: 'NOT INDEXED', className: 'blocked' }
  if (!summary?.cutoff_safe) return { title: '检测到时间截点违规', label: 'CUTOFF VIOLATION', className: 'blocked' }
  return { title: '证据链完整且时间截点安全', label: 'INTEGRITY VERIFIED', className: 'passed' }
}

export function evidenceCoverage(summary) {
  const claims = Number(summary?.claim_count || 0)
  const linked = Number(summary?.linked_claim_count || 0)
  return claims ? linked / claims : 0
}

export function evidenceSearchParams(projectId, query = '', cutoffAt = null) {
  return { query: query.trim(), project_id: projectId, cutoff_at: cutoffAt || undefined, limit: 100 }
}

export function canMutateEvidence(role) {
  return ['admin', 'analyst'].includes(role)
}
