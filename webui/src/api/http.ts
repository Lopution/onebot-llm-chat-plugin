import axios from 'axios'

const WEBUI_ROUTE_SEGMENTS = new Set([
  'dashboard',
  'logs',
  'config',
  'persona',
  'sessions',
  'profiles',
  'knowledge',
  'memory',
  'tools',
  'live-chat',
  'backup',
])

function normalizeBasePath(path: string): string {
  const text = String(path || '').trim()
  if (!text || text === '/') {
    return '/'
  }
  const withLeading = text.startsWith('/') ? text : `/${text}`
  const trimmed = withLeading.replace(/\/+$/, '')
  return trimmed || '/'
}

export function getWebUiBasePath(pathname = window.location.pathname): string {
  const cleanPath = String(pathname || '/').split('?')[0].split('#')[0]
  const segments = cleanPath.split('/').filter(Boolean)
  if (segments.length === 0) {
    return '/'
  }
  const last = segments[segments.length - 1] || ''
  if (WEBUI_ROUTE_SEGMENTS.has(last)) {
    segments.pop()
  }
  return normalizeBasePath(`/${segments.join('/')}`)
}

export function getWebUiApiBasePath(): string {
  const basePath = getWebUiBasePath()
  if (basePath === '/') {
    return '/api'
  }
  return `${basePath}/api`
}

export function toWebUiApiPath(path: string): string {
  const suffix = String(path || '').startsWith('/') ? String(path || '') : `/${path || ''}`
  return `${getWebUiApiBasePath()}${suffix}`
}

const client = axios.create({
  baseURL: getWebUiApiBasePath(),
  timeout: 20000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('mika_webui_token') || ''
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface ApiResponse<T = unknown> {
  status: 'ok' | 'error'
  message: string
  data: T
}

export function unwrapResponse<T>(payload: ApiResponse<T>): T {
  if (!payload || payload.status !== 'ok') {
    const message = payload?.message || 'request failed'
    throw new Error(message)
  }
  return payload.data
}

export default client
