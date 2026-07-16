import { computed, reactive } from 'vue'
import { getCurrentOrganization, listOrganizations, setActiveOrganization } from '../api'

const state = reactive({ organizations: [], current: null, loading: false, error: '', epoch: 0 })

export function resolveOrganization(organizations, preferredId = '') {
  return organizations.find(item => item.organization_id === preferredId)
    || organizations.find(item => item.organization_id === 'org_default')
    || organizations[0]
    || null
}

export function useOrganizationContext() {
  const currentId = computed(() => state.current?.organization_id || '')

  async function load() {
    state.loading = true
    state.error = ''
    try {
      const organizations = await listOrganizations()
      const preferredId = typeof window === 'undefined' ? '' : window.localStorage.getItem('worldpulse_organization') || ''
      const selected = resolveOrganization(organizations, preferredId)
      state.organizations = organizations
      setActiveOrganization(selected?.organization_id || '')
      state.current = selected ? await getCurrentOrganization() : null
      return state.current
    } catch (error) {
      state.error = error?.response?.data?.detail || error.message
      state.current = null
      throw error
    } finally {
      state.loading = false
    }
  }

  async function select(organizationId) {
    const selected = resolveOrganization(state.organizations, organizationId)
    if (!selected || selected.organization_id !== organizationId) throw new Error('无权访问所选组织')
    setActiveOrganization(organizationId)
    state.current = await getCurrentOrganization()
    state.epoch += 1
    return state.current
  }

  function clear() {
    setActiveOrganization('')
    state.organizations = []
    state.current = null
    state.error = ''
    state.epoch += 1
  }

  return { state, currentId, load, select, clear }
}
