import { computed, onBeforeUnmount, ref } from 'vue'
import {
  createMonitoringSource, createMonitoringWatchlist, getContinuousIntelligenceSummary,
  getCurrentOrganization,
  listIntelligenceAlerts, listMonitoringPolls, listMonitoringSources, listMonitoringWatchlists,
  listNotifications, markAllNotificationsRead, markNotificationRead, notificationEventStreamUrl,
  pollMonitoringSource, updateIntelligenceAlert, updateMonitoringSourceStatus,
  updateMonitoringWatchlistStatus,
} from '../api'
import { unreadNotificationCount } from './continuousIntelligenceProjection'

export function useContinuousIntelligence(projectIdRef) {
  const organization = ref(null)
  const summary = ref(null)
  const sources = ref([])
  const watchlists = ref([])
  const alerts = ref([])
  const polls = ref([])
  const notifications = ref([])
  const loading = ref(false)
  const error = ref('')
  const stream = ref(null)
  const projectId = () => typeof projectIdRef === 'function' ? projectIdRef() : projectIdRef?.value || projectIdRef
  async function organizationId(value = null) {
    if (value) {
      organization.value = organization.value?.organization_id === value ? organization.value : { organization_id: value }
      return value
    }
    if (!organization.value?.organization_id) organization.value = await getCurrentOrganization()
    return organization.value.organization_id
  }

  async function load(orgId = null) {
    loading.value = true; error.value = ''
    try {
      const project = projectId()
      orgId = await organizationId(orgId)
      const [nextSummary, nextSources, nextWatchlists, nextAlerts, nextPolls] = await Promise.all([
        getContinuousIntelligenceSummary(orgId, project), listMonitoringSources(orgId, project),
        listMonitoringWatchlists(orgId, project), listIntelligenceAlerts(orgId, project), listMonitoringPolls(orgId, project),
      ])
      summary.value = nextSummary; sources.value = nextSources; watchlists.value = nextWatchlists; alerts.value = nextAlerts; polls.value = nextPolls
      return nextSummary
    } catch (cause) { error.value = cause?.response?.data?.detail || cause.message; throw cause }
    finally { loading.value = false }
  }
  async function createSource(payload, orgId) { orgId = await organizationId(orgId); const result = await createMonitoringSource(orgId, projectId(), payload); await load(orgId); return result }
  async function poll(sourceId, orgId) { orgId = await organizationId(orgId); const result = await pollMonitoringSource(orgId, projectId(), sourceId); await load(orgId); return result }
  async function setSourceStatus(sourceId, status, orgId) { orgId = await organizationId(orgId); const result = await updateMonitoringSourceStatus(orgId, projectId(), sourceId, status); await load(orgId); return result }
  async function createWatchlist(payload, orgId) { orgId = await organizationId(orgId); const result = await createMonitoringWatchlist(orgId, projectId(), payload); await load(orgId); return result }
  async function setWatchlistStatus(id, action, orgId) { orgId = await organizationId(orgId); const result = await updateMonitoringWatchlistStatus(orgId, projectId(), id, action); await load(orgId); return result }
  async function setAlertStatus(id, action, orgId) { orgId = await organizationId(orgId); const result = await updateIntelligenceAlert(orgId, projectId(), id, action); await load(orgId); return result }

  function subscribeNotifications() {
    if (stream.value) return
    let cursor = Math.max(0, ...notifications.value.map(item => item.seq || 0))
    try {
      const source = new EventSource(notificationEventStreamUrl(cursor))
      source.onmessage = event => { try { const item = JSON.parse(event.data); cursor = Math.max(cursor, item.seq || 0); notifications.value = [...notifications.value.filter(existing => existing.notification_id !== item.notification_id), item] } catch {} }
      source.onerror = () => { source.close(); stream.value = null }
      stream.value = source
    } catch { stream.value = null }
  }
  async function loadNotifications() {
    try { notifications.value = await listNotifications({ unread_only: false }) } catch { /* notification center is non-blocking */ }
  }
  async function readNotification(id) { await markNotificationRead(id); notifications.value = notifications.value.map(item => item.notification_id === id ? { ...item, read_at: new Date().toISOString() } : item) }
  async function readAllNotifications() { await markAllNotificationsRead(); notifications.value = notifications.value.map(item => ({ ...item, read_at: item.read_at || new Date().toISOString() })) }
  const unreadCount = computed(() => unreadNotificationCount(notifications.value))
  onBeforeUnmount(() => { stream.value?.close(); stream.value = null })
  return { organization, summary, sources, watchlists, alerts, polls, notifications, unreadCount, loading, error, load, createSource, poll, setSourceStatus, createWatchlist, setWatchlistStatus, setAlertStatus, loadNotifications, subscribeNotifications, readNotification, readAllNotifications }
}
