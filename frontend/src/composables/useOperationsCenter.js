import { ref } from 'vue'
import {
  drainWorkerNode,
  getCurrentOrganization,
  getOrganizationOperations,
  updateOrganizationQuota,
} from '../api'

export function useOperationsCenter() {
  const organization = ref(null)
  const summary = ref(null)
  const loading = ref(false)
  const error = ref('')

  async function load() {
    loading.value = true
    error.value = ''
    try {
      organization.value = await getCurrentOrganization()
      summary.value = await getOrganizationOperations(organization.value.organization_id)
      return summary.value
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause.message
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function saveQuota(payload) {
    await updateOrganizationQuota(organization.value.organization_id, payload)
    return load()
  }

  async function drain(workerId) {
    await drainWorkerNode(workerId)
    return load()
  }

  return { organization, summary, loading, error, load, saveQuota, drain }
}
