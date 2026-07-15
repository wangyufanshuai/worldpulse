import { computed, reactive } from 'vue'
import { getCurrentUser, login as loginRequest, logout as logoutRequest } from '../api'

const state = reactive({ ready: false, loading: false, session: null, error: '' })

export function permissionsForRole(role) {
  return {
    canWrite: ['admin', 'analyst'].includes(role),
    canRun: ['admin', 'analyst'].includes(role),
    canCalibrate: ['admin', 'analyst'].includes(role),
    canReview: ['admin', 'reviewer'].includes(role),
    canActivateRules: role === 'admin',
  }
}

export function useAuthSession() {
  const user = computed(() => state.session?.user || null)
  const role = computed(() => user.value?.role || null)
  const permissions = computed(() => permissionsForRole(role.value))

  async function initialize() {
    state.loading = true
    state.error = ''
    try {
      state.session = await getCurrentUser()
    } catch (error) {
      if (error?.response?.status !== 401) state.error = error?.response?.data?.detail || error.message
      state.session = null
    } finally {
      state.ready = true
      state.loading = false
    }
  }

  async function signIn(username, password) {
    state.loading = true
    state.error = ''
    try {
      state.session = await loginRequest(username, password)
      return state.session
    } catch (error) {
      state.error = error?.response?.data?.detail || '登录失败'
      throw error
    } finally {
      state.loading = false
      state.ready = true
    }
  }

  async function signOut() {
    await logoutRequest()
    state.session = null
  }

  return { state, user, role, permissions, initialize, signIn, signOut }
}
