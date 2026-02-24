/**
 * Backward-compatible facade.
 *
 * All types and functions have moved to the `api/` sub-modules.
 * This file re-exports everything so that existing
 * `import { ... } from '../api/client'` statements keep working.
 */

export {
  // HTTP core
  client as default,
  type ApiResponse,
  // Types
  type DashboardHealth,
  type DashboardTimeline,
  type DashboardTimelinePoint,
  type ConfigField,
  type ConfigSection,
  type SessionListItem,
  type SessionListResult,
  type SessionPreviewItem,
  type SessionDetail,
  type Persona,
  type ToolItem,
  type ToolListResult,
  type UserProfileListItem,
  type UserProfileListResult,
  type LiveChatReply,
  // Dashboard
  getDashboardHealth,
  getDashboardMetrics,
  getDashboardStats,
  getDashboardTimeline,
  // Config
  getConfigSections,
  updateConfig,
  reloadConfig,
  exportConfig,
  importConfig,
  // Knowledge
  listCorpora,
  listDocuments,
  listChunks,
  ingestKnowledge,
  deleteDocument,
  // Memory
  listMemorySessions,
  listMemoryFacts,
  deleteMemory,
  cleanupMemory,
  // Session
  listSessions,
  getSessionDetail,
  clearSession,
  // Log
  getLogHistory,
  buildLogSseUrlWithTicket,
  // Persona
  listPersonas,
  createPersona,
  updatePersona,
  activatePersona,
  deletePersona,
  // Tools
  listTools,
  toggleTool,
  // User Profile
  listUserProfiles,
  getUserProfile,
  updateUserProfile,
  deleteUserProfile,
  // Backup
  importBackup,
  buildBackupExportUrl,
  // Live Chat
  sendLiveChatMessage,
  buildLiveChatWsUrl,
  // Auth
  requestTicket,
} from './index'
