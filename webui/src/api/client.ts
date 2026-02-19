import axios from 'axios'

const client = axios.create({
  baseURL: '/webui/api',
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

function unwrapResponse<T>(payload: ApiResponse<T>): T {
  if (!payload || payload.status !== 'ok') {
    const message = payload?.message || 'request failed'
    throw new Error(message)
  }
  return payload.data
}

export interface DashboardHealth {
  status: string
  database: string
  mika_client: string
  version: string
  api_probe: Record<string, unknown>
}

export interface ConfigField {
  key: string
  value: unknown
  type: string
  description?: string
  hint?: string
  options?: string[]
  labels?: string[]
  secret?: boolean
  advanced?: boolean
}

export interface ConfigSection {
  name: string
  fields: ConfigField[]
}

export async function getDashboardHealth() {
  const { data } = await client.get<ApiResponse<DashboardHealth>>('/dashboard/health')
  return unwrapResponse(data)
}

export async function getDashboardMetrics() {
  const { data } = await client.get<ApiResponse<Record<string, number>>>('/dashboard/metrics')
  return unwrapResponse(data)
}

export async function getDashboardStats() {
  const { data } = await client.get<ApiResponse<Record<string, unknown>>>('/dashboard/stats')
  return unwrapResponse(data)
}

export interface DashboardTimelinePoint {
  timestamp: number
  messages: number
  llm_count: number
  llm_p50_ms: number
  llm_p95_ms: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface DashboardTimeline {
  hours: number
  bucket_seconds: number
  points: DashboardTimelinePoint[]
}

export async function getDashboardTimeline(hours = 24, bucketSeconds = 3600) {
  const { data } = await client.get<ApiResponse<DashboardTimeline>>('/dashboard/timeline', {
    params: { hours, bucket_seconds: bucketSeconds },
  })
  return unwrapResponse(data)
}

export async function getConfigSections() {
  const { data } = await client.get<ApiResponse<{ sections: ConfigSection[] }>>('/config')
  return unwrapResponse(data)
}

export async function updateConfig(values: Record<string, unknown>) {
  const { data } = await client.put<ApiResponse<Record<string, unknown>>>('/config', values)
  return unwrapResponse(data)
}

export async function reloadConfig() {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/config/reload')
  return unwrapResponse(data)
}

export async function exportConfig(includeSecrets = false) {
  const { data } = await client.get<ApiResponse<{ config: Record<string, unknown> }>>('/config/export', {
    params: { include_secrets: includeSecrets },
  })
  return unwrapResponse(data)
}

export async function importConfig(configValues: Record<string, unknown>, applyRuntime = true) {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/config/import', {
    config: configValues,
    apply_runtime: applyRuntime,
  })
  return unwrapResponse(data)
}

export async function listCorpora() {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/knowledge/corpora')
  return unwrapResponse(data)
}

export async function listDocuments(corpusId: string) {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/knowledge/documents', {
    params: { corpus_id: corpusId },
  })
  return unwrapResponse(data)
}

export async function listChunks(corpusId: string, docId: string) {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks`,
    {
    params: { corpus_id: corpusId },
    },
  )
  return unwrapResponse(data)
}

export async function ingestKnowledge(payload: Record<string, unknown>) {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/knowledge/ingest', payload)
  return unwrapResponse(data)
}

export async function deleteDocument(corpusId: string, docId: string) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(
    `/knowledge/documents/${encodeURIComponent(docId)}`,
    {
    params: { corpus_id: corpusId },
    },
  )
  return unwrapResponse(data)
}

export async function listMemorySessions() {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/memory/sessions')
  return unwrapResponse(data)
}

export async function listMemoryFacts(sessionKey: string) {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/memory/facts', {
    params: { session_key: sessionKey },
  })
  return unwrapResponse(data)
}

export async function deleteMemory(id: number) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(`/memory/${id}`)
  return unwrapResponse(data)
}

export async function cleanupMemory(maxAgeDays: number) {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/memory/cleanup', {
    max_age_days: maxAgeDays,
  })
  return unwrapResponse(data)
}

export interface SessionListItem {
  session_key: string
  updated_at: string | null
  message_count: number
  last_message_at: number
  is_group: boolean
}

export interface SessionListResult {
  items: SessionListItem[]
  total: number
  page: number
  page_size: number
  query: string
}

export interface SessionPreviewItem {
  role: string
  content: string
  message_id: string
  timestamp: number
}

export interface SessionDetail {
  exists: boolean
  session_key: string
  updated_at: string | null
  snapshot_message_count: number
  message_count: number
  user_message_count: number
  assistant_message_count: number
  tool_message_count: number
  memory_count: number
  topic_count: number
  last_message_at: number
  preview: SessionPreviewItem[]
}

export async function listSessions(page = 1, pageSize = 20, query = '') {
  const { data } = await client.get<ApiResponse<SessionListResult>>('/session', {
    params: {
      page,
      page_size: pageSize,
      query,
    },
  })
  return unwrapResponse(data)
}

export async function getSessionDetail(sessionKey: string, previewLimit = 8) {
  const { data } = await client.get<ApiResponse<SessionDetail>>(
    `/session/${encodeURIComponent(sessionKey)}`,
    {
      params: { preview_limit: previewLimit },
    },
  )
  return unwrapResponse(data)
}

export async function clearSession(sessionKey: string, purgeArchive = true, purgeTopicState = true) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(
    `/session/${encodeURIComponent(sessionKey)}`,
    {
      params: {
        purge_archive: purgeArchive,
        purge_topic_state: purgeTopicState,
      },
    },
  )
  return unwrapResponse(data)
}

export async function getLogHistory(limit = 100, sinceId = 0, minLevel = 'INFO') {
  const { data } = await client.get<ApiResponse<{ events: Array<Record<string, unknown>>; next_id: number }>>(
    '/log/history',
    { params: { limit, since_id: sinceId, min_level: minLevel } },
  )
  return unwrapResponse(data)
}

export function buildLogSseUrl(minLevel = 'INFO'): string {
  const base = '/webui/api/log/live'
  const params = new URLSearchParams()
  const token = (localStorage.getItem('mika_webui_token') || '').trim()
  if (!token) {
    params.set('min_level', minLevel)
  } else {
    params.set('token', token)
    params.set('min_level', minLevel)
  }
  const query = params.toString()
  if (!query) {
    return base
  }
  return `${base}?${query}`
}

export interface Persona {
  id: number
  name: string
  character_prompt: string
  dialogue_examples: Array<Record<string, unknown>>
  error_messages: Record<string, string>
  is_active: boolean
  temperature_override?: number | null
  model_override?: string
}

export async function listPersonas() {
  const { data } = await client.get<ApiResponse<Array<Persona>>>('/persona')
  return unwrapResponse(data)
}

export async function getActivePersona() {
  const { data } = await client.get<ApiResponse<Persona | null>>('/persona/active')
  return unwrapResponse(data)
}

export async function createPersona(payload: Record<string, unknown>) {
  const { data } = await client.post<ApiResponse<Persona>>('/persona', payload)
  return unwrapResponse(data)
}

export async function updatePersona(personaId: number, payload: Record<string, unknown>) {
  const { data } = await client.put<ApiResponse<Persona>>(`/persona/${personaId}`, payload)
  return unwrapResponse(data)
}

export async function activatePersona(personaId: number) {
  const { data } = await client.post<ApiResponse<Persona>>(`/persona/${personaId}/activate`)
  return unwrapResponse(data)
}

export async function deletePersona(personaId: number) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(`/persona/${personaId}`)
  return unwrapResponse(data)
}

export interface ToolItem {
  name: string
  description: string
  source: string
  enabled: boolean
  parameters: Record<string, unknown>
  meta: Record<string, unknown>
}

export interface ToolListResult {
  tools: ToolItem[]
  total: number
  enabled_total: number
}

export async function listTools(includeDisabled = true) {
  const { data } = await client.get<ApiResponse<ToolListResult>>('/tools', {
    params: { include_disabled: includeDisabled },
  })
  return unwrapResponse(data)
}

export async function toggleTool(toolName: string, enabled: boolean) {
  const { data } = await client.post<ApiResponse<{ name: string; enabled: boolean; persisted: boolean }>>(
    `/tools/${encodeURIComponent(toolName)}/toggle`,
    { enabled },
  )
  return unwrapResponse(data)
}

export interface UserProfileListItem {
  platform_user_id: string
  nickname: string
  real_name: string
  identity: string
  occupation: string
  age: string
  location: string
  birthday: string
  preferences: string[]
  dislikes: string[]
  extra_info: Record<string, unknown>
  last_updated: number
  created_at?: string
  updated_at?: string
}

export interface UserProfileListResult {
  items: UserProfileListItem[]
  total: number
  page: number
  page_size: number
  query: string
}

export async function listUserProfiles(page = 1, pageSize = 20, query = '') {
  const { data } = await client.get<ApiResponse<UserProfileListResult>>('/user-profile', {
    params: { page, page_size: pageSize, query },
  })
  return unwrapResponse(data)
}

export async function getUserProfile(platformUserId: string) {
  const { data } = await client.get<ApiResponse<UserProfileListItem>>(
    `/user-profile/${encodeURIComponent(platformUserId)}`,
  )
  return unwrapResponse(data)
}

export async function updateUserProfile(platformUserId: string, payload: Record<string, unknown>) {
  const { data } = await client.put<ApiResponse<UserProfileListItem>>(
    `/user-profile/${encodeURIComponent(platformUserId)}`,
    payload,
  )
  return unwrapResponse(data)
}

export async function deleteUserProfile(platformUserId: string) {
  const { data } = await client.delete<ApiResponse<{ ok: boolean }>>(
    `/user-profile/${encodeURIComponent(platformUserId)}`,
  )
  return unwrapResponse(data)
}

export async function importBackup(file: File, applyRuntime = true) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('apply_runtime', String(Boolean(applyRuntime)))
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/backup/import', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return unwrapResponse(data)
}

export interface LiveChatReply {
  session_id: string
  user_id: string
  group_id: string
  reply: string
}

export async function sendLiveChatMessage(
  message: string,
  sessionId = 'private:webui_admin',
  userId = 'webui_admin',
  groupId = '',
) {
  const { data } = await client.post<ApiResponse<LiveChatReply>>('/live-chat/message', {
    message,
    session_id: sessionId,
    user_id: userId,
    group_id: groupId,
  })
  return unwrapResponse(data)
}

function _extractToken(): string {
  return (localStorage.getItem('mika_webui_token') || '').trim()
}

export function buildBackupExportUrl(): string {
  const token = _extractToken()
  const base = '/webui/api/backup/export'
  if (!token) {
    return base
  }
  return `${base}?token=${encodeURIComponent(token)}`
}

export function buildLiveChatWsUrl(): string {
  const token = _extractToken()
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = new URL(`${protocol}//${window.location.host}/webui/api/live-chat/ws`)
  if (token) {
    url.searchParams.set('token', token)
  }
  return url.toString()
}

export default client
