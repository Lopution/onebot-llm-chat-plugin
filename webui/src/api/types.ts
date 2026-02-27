/* DTO / interface definitions for all API domains. */

// -- Dashboard --

export interface DashboardHealth {
  health_status: string
  status: string
  database: string
  mika_client: string
  version: string
  api_probe: Record<string, unknown>
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

// -- Config --

export interface ConfigField {
  key: string
  value: unknown
  type: string
  description?: string
  hint?: string
  env_key?: string
  default?: unknown
  options?: string[]
  labels?: string[]
  secret?: boolean
  advanced?: boolean
}

export interface ConfigSection {
  name: string
  fields: ConfigField[]
}

// -- Session --

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

// -- Persona --

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

// -- Tools --

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

// -- User Profile --

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

// -- Live Chat --

export interface LiveChatReply {
  session_id: string
  user_id: string
  group_id: string
  reply: string
}
