import { computed, ref } from 'vue'
import { getNegotiationCommitments, getNegotiationMessages, getNegotiationRounds, getRunNegotiation } from '../api'
import { negotiationSummary } from './negotiationProjection'

export function useNegotiation(runIdRef) {
  const detail = ref(null)
  const rounds = ref([])
  const messages = ref([])
  const commitments = ref([])
  const loading = ref(false)
  const error = ref('')

  const runId = () => String(typeof runIdRef === 'function' ? runIdRef() || '' : runIdRef?.value || '')

  async function load({ quiet = false } = {}) {
    const id = runId()
    if (!id) {
      clear()
      return
    }
    if (!quiet) loading.value = true
    error.value = ''
    try {
      const [nextDetail, nextRounds, nextMessages, nextCommitments] = await Promise.all([
        getRunNegotiation(id), getNegotiationRounds(id), getNegotiationMessages(id), getNegotiationCommitments(id)
      ])
      detail.value = nextDetail
      rounds.value = nextRounds
      messages.value = nextMessages
      commitments.value = nextCommitments
    } catch (requestError) {
      if (requestError?.response?.status !== 404) error.value = requestError?.response?.data?.detail || requestError.message || '协商数据加载失败'
      else clear()
    } finally {
      loading.value = false
    }
  }

  function clear() {
    detail.value = null
    rounds.value = []
    messages.value = []
    commitments.value = []
    error.value = ''
  }

  const summary = computed(() => negotiationSummary(detail.value, commitments.value, messages.value))

  return { detail, rounds, messages, commitments, loading, error, summary, load, clear }
}
