import { ref } from 'vue'
import {
  cancelIngestionJob,
  createDataConnector,
  createIngestionJob,
  executeIngestionJob,
  getCurrentOrganization,
  getIngestionEvents,
  getIngestionSummary,
  listOrganizationMembers,
  retryIngestionJob,
} from '../api'

export function useIngestionGovernance(projectIdRef) {
  const organization = ref(null)
  const members = ref([])
  const summary = ref(null)
  const selectedEvents = ref([])
  const loading = ref(false)
  const error = ref('')
  const projectId = () => typeof projectIdRef === 'function' ? projectIdRef() : projectIdRef?.value || projectIdRef

  async function load() {
    loading.value = true
    error.value = ''
    try {
      organization.value ||= await getCurrentOrganization()
      const orgId = organization.value.organization_id
      ;[summary.value, members.value] = await Promise.all([
        getIngestionSummary(orgId), listOrganizationMembers(orgId),
      ])
      return summary.value
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause.message
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function createConnector(payload) {
    const connector = await createDataConnector(organization.value.organization_id, payload)
    await load()
    return connector
  }

  async function ingest(record, connectorId) {
    const orgId = organization.value.organization_id
    const job = await createIngestionJob(orgId, {
      connector_id: connectorId, project_id: projectId() || null, records: [record],
      idempotency_key: `ui-${connectorId}-${record.external_ref}-${record.cutoff_at}`,
    })
    const completed = await executeIngestionJob(orgId, job.job_id)
    await load()
    return completed
  }

  async function cancel(jobId) {
    const result = await cancelIngestionJob(organization.value.organization_id, jobId)
    await load()
    return result
  }

  async function retry(jobId) {
    const retried = await retryIngestionJob(organization.value.organization_id, jobId)
    const completed = await executeIngestionJob(organization.value.organization_id, retried.job_id)
    await load()
    return completed
  }

  async function inspectEvents(jobId) {
    selectedEvents.value = await getIngestionEvents(organization.value.organization_id, jobId)
    return selectedEvents.value
  }

  return { organization, members, summary, selectedEvents, loading, error, load, createConnector, ingest, cancel, retry, inspectEvents }
}
