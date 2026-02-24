/**
 * Unified API re-export hub.
 *
 * Consumers can import from '@/api' (or '../api') instead of reaching
 * into individual module files.
 */

// HTTP client & helpers
export { default as client, unwrapResponse, type ApiResponse } from './http'

// All DTO types
export type {
  DashboardHealth,
  DashboardTimeline,
  DashboardTimelinePoint,
  ConfigField,
  ConfigSection,
  SessionListItem,
  SessionListResult,
  SessionPreviewItem,
  SessionDetail,
  Persona,
  ToolItem,
  ToolListResult,
  UserProfileListItem,
  UserProfileListResult,
  LiveChatReply,
} from './types'

// Domain modules
export { requestTicket } from './modules/auth'
export {
  getDashboardHealth,
  getDashboardMetrics,
  getDashboardStats,
  getDashboardTimeline,
} from './modules/dashboard'
export {
  getConfigSections,
  updateConfig,
  reloadConfig,
  exportConfig,
  importConfig,
} from './modules/config'
export {
  listCorpora,
  listDocuments,
  listChunks,
  ingestKnowledge,
  deleteDocument,
} from './modules/knowledge'
export {
  listMemorySessions,
  listMemoryFacts,
  deleteMemory,
  cleanupMemory,
} from './modules/memory'
export {
  listSessions,
  getSessionDetail,
  clearSession,
} from './modules/session'
export {
  listPersonas,
  createPersona,
  updatePersona,
  activatePersona,
  deletePersona,
} from './modules/persona'
export { listTools, toggleTool } from './modules/tools'
export {
  listUserProfiles,
  getUserProfile,
  updateUserProfile,
  deleteUserProfile,
} from './modules/user-profile'
export { getLogHistory, buildLogSseUrlWithTicket } from './modules/log'
export { importBackup, buildBackupExportUrl } from './modules/backup'
export {
  sendLiveChatMessage,
  buildLiveChatWsUrl,
} from './modules/live-chat'
