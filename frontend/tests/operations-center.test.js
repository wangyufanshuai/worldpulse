import { describe, expect, it } from 'vitest'

import { permissionsForRole } from '../src/composables/useAuthSession'
import { operationsQuotaRatio, operationsQuotaRows, operationsReadinessLabel } from '../src/composables/operationsProjection'

describe('V1.7 operations center projection', () => {
  it('localizes all readiness states without changing their contract keys', () => {
    expect(['ready', 'degraded', 'not_ready'].map(operationsReadinessLabel))
      .toEqual(['平台就绪', '容量降级', '平台未就绪'])
  })

  it('projects organization usage against all four enforced quotas', () => {
    const rows = operationsQuotaRows({
      usage: { projects: 3, active_runs: 2, ingestion_jobs_today: 5, evidence_snapshots: 11 },
      quota: { max_projects: 10, max_active_runs: 4, max_ingestion_jobs_per_day: 20, max_evidence_snapshots: 100 },
    })
    expect(rows.map(item => [item.key, item.used, item.limit])).toEqual([
      ['max_projects', 3, 10], ['max_active_runs', 2, 4],
      ['max_ingestion_jobs_per_day', 5, 20], ['max_evidence_snapshots', 11, 100],
    ])
  })

  it('clamps quota utilization and keeps operations least-privilege', () => {
    expect(operationsQuotaRatio(12, 10)).toBe(1)
    expect(operationsQuotaRatio(-1, 10)).toBe(0)
    expect(permissionsForRole('admin').canOperate).toBe(true)
    expect(permissionsForRole('analyst').canOperate).toBe(false)
    expect(permissionsForRole('viewer').canOperate).toBe(false)
  })
})
