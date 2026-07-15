export function hybridSummaryMetrics(trace) {
  const diff = trace?.baseline_diff || {}
  return {
    acceptedCount: trace?.accepted_proposal_ids?.length || 0,
    topChains: (diff.supply_chain_pressure || []).filter(item => Number(item.delta)).slice(0, 3),
    topCountries: (diff.country_risk || []).filter(item => Number(item.delta)).slice(0, 3),
  }
}
