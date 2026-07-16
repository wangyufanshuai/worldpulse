import { ref, computed } from 'vue'
import { listEvaluationBatches, listEvaluationSuites, createStandardEvaluation, getEvaluationMembers, getEvaluationReport, controlEvaluation } from '../api'

export function useEvaluationCenter() {
  const suites = ref([]); const batches = ref([]); const members = ref([]); const report = ref(null); const loading = ref(false); const error = ref('')
  const latest = computed(() => batches.value[0] || null)
  const load = async organizationId => { loading.value = true; error.value = ''; try { suites.value = await listEvaluationSuites(); batches.value = await listEvaluationBatches(organizationId); if (latest.value) members.value = await getEvaluationMembers(latest.value.batch_id) } catch (e) { error.value = e?.response?.data?.detail || e.message || '评估中心加载失败' } finally { loading.value = false } }
  const createStandard = async organizationId => { const batch = await createStandardEvaluation(organizationId, { provider: 'mock' }); batches.value = [batch, ...batches.value]; return batch }
  const inspect = async batchId => { members.value = await getEvaluationMembers(batchId); report.value = await getEvaluationReport(batchId) }
  const control = async (batchId, action) => { const batch = await controlEvaluation(batchId, action); batches.value = batches.value.map(item => item.batch_id === batch.batch_id ? batch : item); return batch }
  return { suites, batches, members, report, latest, loading, error, load, createStandard, inspect, control }
}
