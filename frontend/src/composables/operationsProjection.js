export function operationsReadinessLabel(status) {
  return ({ ready: '平台就绪', degraded: '容量降级', not_ready: '平台未就绪' })[status] || status || '--'
}

export function operationsQuotaRows(summary = {}) {
  const usage = summary.usage || {}
  const quota = summary.quota || {}
  return [
    { key: 'max_projects', label: '项目数量', used: usage.projects || 0, limit: quota.max_projects || 1 },
    { key: 'max_active_runs', label: '活跃运行', used: usage.active_runs || 0, limit: quota.max_active_runs || 1 },
    { key: 'max_ingestion_jobs_per_day', label: '24 小时采集任务', used: usage.ingestion_jobs_today || 0, limit: quota.max_ingestion_jobs_per_day || 1 },
    { key: 'max_evidence_snapshots', label: '证据快照', used: usage.evidence_snapshots || 0, limit: quota.max_evidence_snapshots || 1 },
    { key: 'max_source_documents', label: '版本化文档', used: usage.source_documents || 0, limit: quota.max_source_documents || 1 },
    { key: 'max_document_bytes', label: '材料存储（Bytes）', used: usage.document_bytes || 0, limit: quota.max_document_bytes || 1 },
  ]
}

export function operationsQuotaRatio(used, limit) {
  if (!Number.isFinite(Number(limit)) || Number(limit) <= 0) return 0
  return Math.min(1, Math.max(0, Number(used) / Number(limit)))
}
