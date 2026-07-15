import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { mergeLifecycleEvents } from '../src/composables/useRunLifecycle'
import { lifecycleControlMatrix } from '../src/composables/useRunLifecycleConsole'
import { useWarRoomArtifacts } from '../src/composables/useWarRoomArtifacts'
import { useWarRoomReplayControls } from '../src/composables/useWarRoomReplayControls'
import { hybridSummaryMetrics } from '../src/composables/hybridSummary'

describe('lifecycle contracts', () => {
  it('merges SSE and polling events by monotonic sequence', () => {
    expect(mergeLifecycleEvents([{ seq: 2, title: 'old' }, { seq: 1, title: 'first' }], [{ seq: 2, title: 'updated' }, { seq: 3, title: 'last' }]))
      .toEqual([{ seq: 1, title: 'first' }, { seq: 2, title: 'updated' }, { seq: 3, title: 'last' }])
  })

  it('exposes the intended pause/cancel/resume/retry status matrix', () => {
    expect(lifecycleControlMatrix('running')).toMatchObject({ canPause: true, canCancel: true, canResume: false, canRetry: false, busy: true })
    expect(lifecycleControlMatrix('paused')).toMatchObject({ canPause: false, canCancel: true, canResume: true, canRetry: false, busy: false })
    expect(lifecycleControlMatrix('failed')).toMatchObject({ canPause: false, canCancel: false, canResume: false, canRetry: true, busy: false })
    expect(lifecycleControlMatrix('completed')).toMatchObject({ canPause: false, canCancel: false, canResume: false, canRetry: false, busy: false })
  })
})

describe('War Room composables', () => {
  it('selects and advances replay timeline ticks', () => {
    const timelineEvents = ref([{ day: 0, position: 0 }, { day: 3, position: 20 }, { day: 7, position: 70 }])
    const selectedMapEntity = ref(null)
    const controls = useWarRoomReplayControls({ timelineEvents, selectedMapEntity, showToast: () => {} })
    controls.selectReplayDay(5)
    expect(controls.activeReplayDay.value).toBe(7)
    controls.advanceReplay()
    expect(controls.activeReplayDay.value).toBe(0)
  })

  it('keeps compare defaults and hybrid summary projections deterministic', () => {
    const runVersions = ref([{ run_id: 'run-2' }, { run_id: 'run-1' }])
    const artifacts = useWarRoomArtifacts({
      detail: ref({ project: { title: 'Test' } }),
      isWarRoom: ref(true),
      runVersions,
      selectedRunId: ref('run-2'),
      warRoomData: {},
      dataJsonPreview: ref('{}'),
      showToast: () => {},
    })
    artifacts.prepareCompareDefaults()
    expect(artifacts.compareTargetRunId.value).toBe('run-2')
    expect(artifacts.compareBaseRunId.value).toBe('run-1')
    expect(hybridSummaryMetrics({ accepted_proposal_ids: ['p1'], baseline_diff: { country_risk: [{ country_code: 'A', delta: 3 }], supply_chain_pressure: [{ key: 'energy', delta: 2 }] } })).toMatchObject({ acceptedCount: 1 })
  })
})
