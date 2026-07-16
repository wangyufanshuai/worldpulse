import { describe, expect, it } from 'vitest'

import { canWriteIngestion, compactManifestHash, ingestionKpis, validateIngestionDraft } from '../src/composables/ingestionProjection'

const validDraft = {
  connector_id: 'connector-1', external_ref: 'ENERGY-2026-07', title: '能源冻结快照',
  observed_at: '2026-07-10', cutoff_at: '2026-07-16', content: '{"risk": 0.72}',
}

describe('ingestion governance projection', () => {
  it.each([
    ['owner', true], ['admin', true], ['analyst', true], ['reviewer', false], ['viewer', false], [null, false],
  ])('keeps organization role %s least-privilege', (role, expected) => {
    expect(canWriteIngestion(role)).toBe(expected)
  })

  it('accepts cutoff-safe structured records', () => {
    expect(validateIngestionDraft(validDraft)).toEqual({ content: { risk: .72 } })
  })

  it('rejects future leakage before submitting', () => {
    expect(validateIngestionDraft({ ...validDraft, observed_at: '2026-07-17' })).toContain('不能晚于')
  })

  it('rejects malformed JSON before submitting', () => {
    expect(validateIngestionDraft({ ...validDraft, content: '{bad' })).toContain('JSON')
  })

  it('projects stable governance KPI keys', () => {
    expect(ingestionKpis({ connector_count: 2, active_policy_count: 1, completed_jobs: 4, accepted_records: 9 }))
      .toEqual([
        { key: 'connectors', label: '连接器', value: 2 },
        { key: 'policies', label: '活动策略', value: 1 },
        { key: 'completed', label: '完成任务', value: 4 },
        { key: 'accepted', label: '接纳记录', value: 9 },
      ])
  })

  it('keeps manifest hashes readable without exposing full content', () => {
    expect(compactManifestHash('1234567890abcdefghijkl')).toBe('1234567890…fghijkl')
    expect(compactManifestHash('')).toBe('--')
  })
})
