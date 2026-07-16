const WRITE_ROLES = new Set(['owner', 'admin', 'analyst'])

export function canWriteIngestion(role) {
  return WRITE_ROLES.has(String(role || '').toLowerCase())
}

export function validateIngestionDraft(draft) {
  if (!draft?.connector_id) return '请选择连接器。'
  if (!draft?.external_ref?.trim()) return '外部引用不能为空。'
  if (!draft?.title?.trim()) return '标题不能为空。'
  if (!draft?.observed_at || !draft?.cutoff_at) return '观察日期与截止日期不能为空。'
  if (draft.observed_at > draft.cutoff_at) return '观察日期不能晚于截止日期。'
  try {
    return { content: JSON.parse(draft.content) }
  } catch {
    return 'JSON 内容格式无效。'
  }
}

export function ingestionKpis(summary = {}) {
  return [
    { key: 'connectors', label: '连接器', value: summary.connector_count || 0 },
    { key: 'policies', label: '活动策略', value: summary.active_policy_count || 0 },
    { key: 'completed', label: '完成任务', value: summary.completed_jobs || 0 },
    { key: 'accepted', label: '接纳记录', value: summary.accepted_records || 0 },
  ]
}

export function compactManifestHash(value) {
  const text = String(value || '')
  return text ? `${text.slice(0, 10)}…${text.slice(-7)}` : '--'
}
