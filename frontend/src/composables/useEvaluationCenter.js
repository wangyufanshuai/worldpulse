import { computed, onBeforeUnmount, ref } from 'vue'
import {
  controlEvaluation,
  createHistoricalEvaluation,
  createStandardEvaluation,
  getEvaluationMembers,
  getEvaluationReport,
  getEvaluationVerification,
  getHistoricalEvaluationReport,
  listEvaluationBatches,
  listEvaluationLabelPacks,
  listEvaluationSuites,
  listHistoricalBenchmarkSuites
} from '../api'

export function useEvaluationCenter() {
  const suites = ref([])
  const benchmarkSuites = ref([])
  const labelPacks = ref([])
  const batches = ref([])
  const members = ref([])
  const verification = ref([])
  const report = ref(null)
  const historicalReport = ref(null)
  const loading = ref(false)
  const error = ref('')
  const selectedBatchId = ref('')
  const activeOrganizationId = ref('')
  let stream = null
  let polling = null
  let subscribedBatchId = ''

  const latest = computed(() => batches.value.find(item => item.batch_id === selectedBatchId.value) || batches.value[0] || null)
  const tabs = computed(() => ({
    engineering: batches.value.filter(item => item.evaluation_track === 'engineering_standard'),
    historical: batches.value.filter(item => item.evaluation_track?.startsWith('historical')),
    project: batches.value.filter(item => item.evaluation_track === 'project_experiment'),
    live: batches.value.filter(item => item.evaluation_track === 'live_observation')
  }))

  const load = async organizationId => {
    activeOrganizationId.value = organizationId
    loading.value = true
    error.value = ''
    try {
      [suites.value, benchmarkSuites.value, labelPacks.value, batches.value] = await Promise.all([
        listEvaluationSuites(),
        listHistoricalBenchmarkSuites(),
        listEvaluationLabelPacks(organizationId),
        listEvaluationBatches(organizationId)
      ])
      if (!selectedBatchId.value && batches.value[0]) selectedBatchId.value = batches.value[0].batch_id
      if (selectedBatchId.value) await inspect(selectedBatchId.value)
    } catch (e) {
      error.value = e?.response?.data?.detail || e.message || '评估中心加载失败'
    } finally {
      loading.value = false
    }
  }

  const createStandard = async organizationId => {
    const batch = await createStandardEvaluation(organizationId, { provider: 'mock' })
    batches.value = [batch, ...batches.value]
    selectedBatchId.value = batch.batch_id
    subscribe(batch.batch_id)
    return batch
  }

  const createHistorical = async (organizationId, labelPackId) => {
    const batch = await createHistoricalEvaluation(organizationId, {
      suite_id: 'historical-benchmark.v1',
      label_pack_id: labelPackId,
      provider: 'mock'
    })
    batches.value = [batch, ...batches.value]
    selectedBatchId.value = batch.batch_id
    subscribe(batch.batch_id)
    return batch
  }

  const inspect = async batchId => {
    selectedBatchId.value = batchId
    const selected = batches.value.find(item => item.batch_id === batchId)
    const requests = [getEvaluationMembers(batchId), getEvaluationReport(batchId), getEvaluationVerification(batchId)]
    if (selected?.evaluation_track === 'historical_blind') requests.push(getHistoricalEvaluationReport(batchId))
    const values = await Promise.all(requests)
    members.value = values[0]
    report.value = values[1]
    verification.value = values[2]
    historicalReport.value = values[3] || null
    subscribe(batchId)
  }

  const control = async (batchId, action) => {
    const batch = await controlEvaluation(batchId, action)
    batches.value = batches.value.map(item => item.batch_id === batch.batch_id ? batch : item)
    await inspect(batch.batch_id)
    return batch
  }

  const refreshSelected = async () => {
    if (!selectedBatchId.value) return
    try {
      await inspect(selectedBatchId.value)
    } catch (e) {
      error.value = e?.response?.data?.detail || e.message || '评估状态刷新失败'
    }
  }

  const subscribe = batchId => {
    if (typeof window === 'undefined' || !batchId) return
    if (shouldReuseEvaluationSubscription(subscribedBatchId, Boolean(stream), Boolean(polling), batchId)) return
    closeSubscription()
    subscribedBatchId = batchId
    const query = activeOrganizationId.value ? `?organization_id=${encodeURIComponent(activeOrganizationId.value)}` : ''
    stream = new EventSource(`/api/v10/evaluations/${batchId}/events/stream${query}`)
    stream.addEventListener('evaluation', refreshSelected)
    stream.onerror = () => {
      stream?.close()
      stream = null
      if (!polling) polling = window.setInterval(refreshSelected, 2500)
    }
  }

  const closeSubscription = () => {
    stream?.close()
    stream = null
    if (polling) window.clearInterval(polling)
    polling = null
    subscribedBatchId = ''
  }

  onBeforeUnmount(() => {
    closeSubscription()
  })

  return {
    suites, benchmarkSuites, labelPacks, batches, members, verification, report,
    historicalReport, latest, tabs, loading, error, selectedBatchId,
    load, createStandard, createHistorical, inspect, control
  }
}

export function shouldReuseEvaluationSubscription(currentId, hasStream, hasPolling, nextId) {
  return currentId === nextId && (hasStream || hasPolling)
}
