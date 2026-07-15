export function percent(value) {
  return value === undefined || value === null ? '--' : `${Math.round(Number(value) * 100)}%`
}

export function calibrationLabel(status) {
  return ({ passed: '已通过', failed: '未通过', pending: '等待运行', not_calibrated: '未校准' }[status] || status || '--')
}

export function reportGate(summary) {
  return summary?.report_allowed
    ? { key: 'passed', label: 'REPORT READY', text: '允许进入正式报告' }
    : { key: 'blocked', label: 'FAIL CLOSED', text: '尚未满足正式报告门槛' }
}

export function calibrationGateRows(summary) {
  const metrics = summary?.calibration?.metrics || {}
  return [
    { key: 'deterministic', label: '确定性回归', value: percent(metrics.deterministic_regression), passed: metrics.gates?.deterministic_regression === true },
    { key: 'critical', label: '关键违规召回', value: percent(metrics.critical_violation_recall), passed: metrics.gates?.critical_violation_recall === true },
    { key: 'false_accept', label: '关键误放行', value: String(metrics.critical_false_accept ?? '--'), passed: metrics.gates?.critical_false_accept === true },
    { key: 'direction', label: '供应链方向', value: percent(metrics.supply_chain_direction_accuracy), passed: metrics.gates?.historical_direction_accuracy === true },
    { key: 'top3', label: 'Top-3 重合', value: percent(metrics.top3_overlap), passed: metrics.gates?.top3_overlap === true },
    { key: 'regression', label: '相对版本退化', value: `${Number(metrics.max_regression_pp || 0).toFixed(1)}pp`, passed: metrics.gates?.no_material_regression === true },
  ]
}

export function reviewActionKeys(review, canReview) {
  if (!canReview) return []
  const actions = ['confirmed', 'request_revision']
  if (review?.review_type === 'rule_pack_promotion') actions.push('reject_promotion')
  return actions
}
