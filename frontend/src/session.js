import { reactive } from 'vue'
import {
  apiRequest,
  clearCsrfToken,
  fetchSession,
  setCsrfToken,
} from './api'

export const session = reactive({
  user: null,
  ready: false,
  loading: false,
  error: null,
})

let pendingLoad = null

export async function loadSession(force = false) {
  if (session.ready && !force) {
    return session
  }
  if (pendingLoad) {
    return pendingLoad
  }
  pendingLoad = (async () => {
    session.loading = true
    session.error = null
    try {
      const data = await fetchSession()
      session.user = data.user
      session.ready = true
      return session
    } catch (error) {
      session.user = null
      session.error = error
      session.ready = true
      throw error
    } finally {
      session.loading = false
      pendingLoad = null
    }
  })()
  return pendingLoad
}

export async function login(credentials) {
  const data = await apiRequest('/api/auth/login', {
    method: 'POST',
    body: credentials,
  })
  setCsrfToken(data.csrf_token)
  session.user = data.user
  session.ready = true
  session.error = null
  return data
}

export async function register(payload) {
  return apiRequest('/api/auth/register', { method: 'POST', body: payload })
}

export async function logout() {
  await apiRequest('/api/auth/logout', { method: 'POST' })
  clearCsrfToken()
  session.user = null
  await loadSession(true)
}

export function setUser(user) {
  session.user = user
  session.ready = true
  session.error = null
}
