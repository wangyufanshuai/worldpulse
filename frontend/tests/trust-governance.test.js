import { describe, expect, it } from 'vitest'

import { lifecycleControlMatrix } from '../src/composables/useRunLifecycleConsole'
import { permissionsForRole } from '../src/composables/useAuthSession'
import { calibrationGateRows, calibrationLabel, percent, reportGate, reviewActionKeys } from '../src/composables/trustProjection'

describe('RBAC projections', () => {
  it.each([
    ['admin', true, true, true],
    ['analyst', true, false, false],
    ['reviewer', false, true, false],
    ['viewer', false, false, false],
  ])('%s permissions are least-privilege', (role, canRun, canReview, canActivateRules) => {
    expect(permissionsForRole(role)).toMatchObject({ canRun, canReview, canActivateRules })
  })
})

describe('Trust Summary projection', () => {
  it.each([
    ['passed', '已通过'], ['failed', '未通过'], ['pending', '等待运行'], ['not_calibrated', '未校准'],
  ])('localizes calibration status %s', (status, expected) => expect(calibrationLabel(status)).toBe(expected))

  it.each([
    [1, '100%'], [0.7, '70%'], [0, '0%'], [null, '--'],
  ])('formats coverage %s', (value, expected) => expect(percent(value)).toBe(expected))

  it('projects all six promotion gates', () => {
    const rows = calibrationGateRows({ calibration: { metrics: {
      deterministic_regression: 1, critical_violation_recall: 1, critical_false_accept: 0,
      supply_chain_direction_accuracy: .8, top3_overlap: .7, max_regression_pp: 2,
      gates: { deterministic_regression: true, critical_violation_recall: true, critical_false_accept: true, historical_direction_accuracy: true, top3_overlap: true, no_material_regression: true },
    } } })
    expect(rows).toHaveLength(6)
    expect(rows.every(item => item.passed)).toBe(true)
  })

  it.each([[true, 'passed'], [false, 'blocked']])('uses fail-closed report gate for %s', (allowed, key) => {
    expect(reportGate({ report_allowed: allowed }).key).toBe(key)
  })
})

describe('Review and lifecycle error states', () => {
  it('hides review actions from analysts and viewers', () => expect(reviewActionKeys({ review_type: 'artifact_integrity' }, false)).toEqual([]))
  it('offers acknowledgement without an override action', () => expect(reviewActionKeys({ review_type: 'agent_action_admission' }, true)).toEqual(['confirmed', 'request_revision']))
  it('offers rejection for Rule Pack promotion', () => expect(reviewActionKeys({ review_type: 'rule_pack_promotion' }, true)).toContain('reject_promotion'))
  it('never offers direct action approval', () => expect(reviewActionKeys({ review_type: 'agent_action_admission' }, true)).not.toContain('approve_promotion'))
  it('failed lifecycle enables retry only', () => expect(lifecycleControlMatrix('failed')).toMatchObject({ canRetry: true, canResume: false }))
  it('cancelled lifecycle enables retry only', () => expect(lifecycleControlMatrix('cancelled')).toMatchObject({ canRetry: true, canPause: false }))
  it('pausing lifecycle remains busy', () => expect(lifecycleControlMatrix('pausing').busy).toBe(true))
})
