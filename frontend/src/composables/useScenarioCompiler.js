import { computed, ref } from 'vue'
import {
  cancelDocumentExtraction,
  cloneScenarioDraft,
  createDocumentExtraction,
  createScenarioDraft,
  decideScenarioCandidate,
  getCurrentOrganization,
  getDocumentExtractionEvents,
  getDocumentExtractionJob,
  listScenarioCandidates,
  listScenarioDrafts,
  listDocumentExtractionJobs,
  listSourceDocuments,
  retryDocumentExtraction,
  reviewScenarioDraft,
  runScenarioDraft,
  submitScenarioDraft,
  uploadSourceDocument,
} from '../api'
import { scenarioCompilerSummary } from './scenarioCompilerProjection'

export function useScenarioCompiler(projectIdRef) {
  const organization = ref(null)
  const documents = ref([])
  const jobs = ref([])
  const candidates = ref([])
  const drafts = ref([])
  const selectedEvents = ref([])
  const lastRun = ref(null)
  const loading = ref(false)
  const error = ref('')
  const projectId = () => typeof projectIdRef === 'function' ? projectIdRef() : projectIdRef?.value || projectIdRef
  const organizationId = () => organization.value?.organization_id
  async function scope() {
    organization.value ||= await getCurrentOrganization()
    return [organizationId(), projectId()]
  }
  const summary = computed(() => scenarioCompilerSummary(documents.value, candidates.value, drafts.value))

  async function load({ quiet = false } = {}) {
    if (!quiet) loading.value = true
    error.value = ''
    try {
      const args = await scope()
      ;[documents.value, jobs.value, candidates.value, drafts.value] = await Promise.all([
        listSourceDocuments(...args), listDocumentExtractionJobs(...args), listScenarioCandidates(...args), listScenarioDrafts(...args),
      ])
      if (jobs.value.length) jobs.value = await Promise.all(jobs.value.map(job => getDocumentExtractionJob(...args, job.job_id)))
      return summary.value
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause.message
      throw cause
    } finally {
      if (!quiet) loading.value = false
    }
  }

  async function upload(file, metadata) {
    const form = new FormData()
    form.append('file', file)
    Object.entries(metadata).forEach(([key, value]) => form.append(key, value ?? ''))
    const args = await scope()
    const result = await uploadSourceDocument(...args, form)
    await load({ quiet: true })
    return result
  }

  async function extract(documentId) {
    const args = await scope()
    const job = await createDocumentExtraction(...args, documentId)
    jobs.value = [job, ...jobs.value.filter(item => item.job_id !== job.job_id)]
    return job
  }

  async function events(jobId) {
    const args = await scope()
    selectedEvents.value = await getDocumentExtractionEvents(...args, jobId)
    return selectedEvents.value
  }

  async function cancel(jobId) {
    const args = await scope()
    const job = await cancelDocumentExtraction(...args, jobId)
    jobs.value = jobs.value.map(item => item.job_id === jobId ? job : item)
    return job
  }

  async function retry(jobId) {
    const args = await scope()
    const job = await retryDocumentExtraction(...args, jobId)
    jobs.value = [job, ...jobs.value]
    return job
  }

  async function decide(candidateId, payload) {
    const args = await scope()
    const decision = await decideScenarioCandidate(...args, candidateId, payload)
    await load({ quiet: true })
    return decision
  }

  async function createDraft(payload) {
    const args = await scope()
    const draft = await createScenarioDraft(...args, payload)
    await load({ quiet: true })
    return draft
  }

  async function submit(draftId) {
    const args = await scope()
    const draft = await submitScenarioDraft(...args, draftId)
    await load({ quiet: true })
    return draft
  }

  async function review(draftId, payload) {
    const args = await scope()
    const draft = await reviewScenarioDraft(...args, draftId, payload)
    await load({ quiet: true })
    return draft
  }

  async function clone(draftId) {
    const args = await scope()
    const draft = await cloneScenarioDraft(...args, draftId)
    await load({ quiet: true })
    return draft
  }

  async function run(draftId, payload) {
    const args = await scope()
    lastRun.value = await runScenarioDraft(...args, draftId, payload)
    return lastRun.value
  }

  return { organization, documents, jobs, candidates, drafts, selectedEvents, lastRun, summary, loading, error, load, upload, extract, events, cancel, retry, decide, createDraft, submit, review, clone, run }
}
