import { describe, expect, it } from 'vitest'

import {
  alertLineageReady, continuousIntelligenceCandidates, sourceHealthLabel, unreadNotificationCount,
} from '../src/composables/continuousIntelligenceProjection'
import { permissionsForRole } from '../src/composables/useAuthSession'

describe('V1.10 continuous intelligence projection', () => {
  it('keeps automated candidates distinguishable from manual uploads', () => {
    const candidates = [
      { candidate_id: 'manual', origin: { kind: 'document_upload' } },
      { candidate_id: 'feed', origin: { kind: 'continuous_intelligence', alert_id: 'a1' } },
    ]
    expect(continuousIntelligenceCandidates(candidates).map(item => item.candidate_id)).toEqual(['feed'])
  })

  it('counts unread notifications and recognizes completed lineage', () => {
    expect(unreadNotificationCount([{ read_at: null }, { read_at: '2026-07-16T00:00:00Z' }])).toBe(1)
    expect(alertLineageReady({ lineage: { document_id: 'd', extraction_id: 'e', candidate_ids: ['c'] } })).toBe(true)
    expect(alertLineageReady({ lineage: { document_id: 'd', candidate_ids: [] } })).toBe(false)
  })

  it('localizes source health and preserves least privilege', () => {
    expect(['active', 'paused', 'degraded', 'retired'].map(sourceHealthLabel)).toEqual(['正常', '已暂停', '已降级', '已退役'])
    expect(permissionsForRole('analyst').canWrite).toBe(true)
    expect(permissionsForRole('viewer').canWrite).toBe(false)
  })
})
