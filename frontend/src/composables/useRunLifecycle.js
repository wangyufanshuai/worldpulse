import { ref } from 'vue'
import {
  cancelLifecycleRun,
  createLifecycleRun,
  getLifecycleAudit,
  getLifecycleEvents,
  getLifecycleRun,
  lifecycleEventStreamUrl,
  pauseLifecycleRun,
  resumeLifecycleRun,
  retryLifecycleRun,
} from '../api'

const TERMINAL = new Set(['completed', 'cancelled', 'failed'])

export function useRunLifecycle(projectId) {
  const activeRun = ref(null)
  const events = ref([])
  const audit = ref(null)
  const loading = ref(false)
  const error = ref('')
  let eventSource = null
  let pollTimer = null

  const projectIdValue = () => (typeof projectId === 'function' ? projectId() : projectId)

  function lastSeq() {
    return events.value.reduce((max, event) => Math.max(max, Number(event.seq || 0)), 0)
  }

  function mergeEvents(nextEvents = []) {
    const bySeq = new Map(events.value.map((event) => [Number(event.seq), event]))
    nextEvents.forEach((event) => bySeq.set(Number(event.seq), event))
    events.value = [...bySeq.values()].sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0))
  }

  async function refresh(runId = activeRun.value?.run_id) {
    if (!runId) return null
    const [run, nextEvents, nextAudit] = await Promise.all([
      getLifecycleRun(runId),
      getLifecycleEvents(runId, lastSeq()),
      getLifecycleAudit(runId),
    ])
    activeRun.value = run
    mergeEvents(nextEvents)
    audit.value = nextAudit
    return run
  }

  function stop() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    if (pollTimer) {
      window.clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function startPolling(runId) {
    if (pollTimer) window.clearInterval(pollTimer)
    pollTimer = window.setInterval(async () => {
      try {
        const run = await refresh(runId)
        if (run && TERMINAL.has(run.status)) stop()
      } catch (err) {
        error.value = err?.message || String(err)
      }
    }, 1400)
  }

  function subscribe(runId) {
    stop()
    if (!runId || typeof window === 'undefined' || !window.EventSource) {
      if (runId) startPolling(runId)
      return
    }
    eventSource = new window.EventSource(lifecycleEventStreamUrl(runId, lastSeq()))
    eventSource.onmessage = (message) => {
      if (!message.data) return
      try {
        mergeEvents([JSON.parse(message.data)])
      } catch {
        // ignore malformed keepalive/event payloads
      }
    }
    ;['WORKER', 'ENGINE', 'AGENT', 'CONSISTENCY', 'SNAPSHOT'].forEach((type) => {
      eventSource.addEventListener(type, (message) => {
        try {
          mergeEvents([JSON.parse(message.data)])
        } catch {
          // ignore malformed event payloads
        }
      })
    })
    eventSource.onerror = () => {
      if (eventSource) eventSource.close()
      eventSource = null
      startPolling(runId)
    }
    startPolling(runId)
  }

  async function create(payload) {
    loading.value = true
    error.value = ''
    try {
      const run = await createLifecycleRun(projectIdValue(), payload)
      activeRun.value = run
      const [nextEvents, nextAudit] = await Promise.all([
        getLifecycleEvents(run.run_id),
        getLifecycleAudit(run.run_id),
      ])
      events.value = nextEvents
      audit.value = nextAudit
      subscribe(run.run_id)
      return run
    } catch (err) {
      error.value = err?.message || String(err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function control(action) {
    if (!activeRun.value?.run_id) return null
    const runId = activeRun.value.run_id
    const fn = { pause: pauseLifecycleRun, resume: resumeLifecycleRun, cancel: cancelLifecycleRun, retry: retryLifecycleRun }[action]
    if (!fn) return null
    const response = await fn(runId)
    activeRun.value = response.run
    mergeEvents(response.events || [])
    if (action === 'retry' && response.run?.run_id) {
      events.value = response.events || []
      audit.value = await getLifecycleAudit(response.run.run_id)
      subscribe(response.run.run_id)
    } else if (!TERMINAL.has(response.run?.status)) {
      subscribe(response.run.run_id)
    }
    if (action !== 'retry') audit.value = await getLifecycleAudit(response.run.run_id)
    return response.run
  }

  return {
    activeRun,
    audit,
    cancel: () => control('cancel'),
    create,
    error,
    events,
    loading,
    pause: () => control('pause'),
    refresh,
    resume: () => control('resume'),
    retry: () => control('retry'),
    stop,
    subscribe,
  }
}
