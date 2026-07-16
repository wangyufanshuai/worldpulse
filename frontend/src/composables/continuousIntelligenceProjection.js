export function continuousIntelligenceCandidates(candidates = []) {
  return candidates.filter(item => item?.origin?.kind === 'continuous_intelligence')
}

export function unreadNotificationCount(notifications = []) {
  return notifications.filter(item => !item.read_at).length
}

export function alertLineageReady(alert) {
  const lineage = alert?.lineage || {}
  return Boolean(lineage.document_id && lineage.extraction_id && lineage.candidate_ids?.length)
}

export function sourceHealthLabel(status) {
  return ({ active: '正常', paused: '已暂停', degraded: '已降级', retired: '已退役' })[status] || status || '--'
}
