import { ref } from 'vue'
import { createEvidencePack, getProjectEvidenceSummary, searchEvidence, syncProjectEvidence } from '../api'
import { evidenceSearchParams } from './evidenceProjection'

export function useEvidenceRegistry(projectIdRef) {
  const summary = ref(null)
  const searchResult = ref({ query: '', total: 0, snapshots: [], claims: [] })
  const loading = ref(false)
  const searching = ref(false)
  const error = ref('')

  const projectId = () => typeof projectIdRef === 'function' ? projectIdRef() : projectIdRef?.value || projectIdRef

  async function load() {
    if (!projectId()) return null
    loading.value = true
    error.value = ''
    try {
      summary.value = await getProjectEvidenceSummary(projectId())
      return summary.value
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause.message
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function sync(runId = null) {
    loading.value = true
    error.value = ''
    try {
      const result = await syncProjectEvidence(projectId(), runId)
      summary.value = result.summary
      return result
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause.message
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function search(query = '', cutoffAt = null) {
    searching.value = true
    try {
      searchResult.value = await searchEvidence(evidenceSearchParams(projectId(), query, cutoffAt))
      return searchResult.value
    } finally {
      searching.value = false
    }
  }

  async function createPack(runId = null) {
    const cutoffAt = summary.value?.latest_cutoff_at || new Date().toISOString()
    const pack = await createEvidencePack({
      project_id: projectId(), run_id: runId || null,
      name: `WorldPulse evidence pack ${new Date().toISOString().slice(0, 10)}`,
      cutoff_at: cutoffAt, snapshot_ids: [], claim_ids: [],
    })
    await load()
    return pack
  }

  return { summary, searchResult, loading, searching, error, load, sync, search, createPack }
}
