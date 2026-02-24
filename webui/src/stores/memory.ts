import { defineStore } from 'pinia'
import {
  listMemorySessions,
  listMemoryFacts,
  deleteMemory,
  cleanupMemory,
} from '../api/modules/memory'

export const useMemoryStore = defineStore('memory', {
  state: () => ({
    loading: false,
    error: '',
    lastLoadedAt: 0,
    sessions: [] as Array<Record<string, any>>,
    selectedSession: '',
    facts: [] as Array<Record<string, any>>,
  }),
  actions: {
    async loadSessions() {
      this.loading = true
      this.error = ''
      try {
        this.sessions = await listMemorySessions()
        if (!this.selectedSession && this.sessions.length) {
          this.selectedSession = this.sessions[0].session_key
        }
        this.lastLoadedAt = Date.now()
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async loadFacts() {
      if (!this.selectedSession) {
        this.facts = []
        return
      }
      this.facts = await listMemoryFacts(this.selectedSession)
    },
    async selectSession(sessionKey: string) {
      this.selectedSession = sessionKey
      await this.loadFacts()
    },
    async removeFact(id: number) {
      await deleteMemory(id)
      await this.loadFacts()
      await this.loadSessions()
    },
    async cleanup(maxAgeDays = 90) {
      const result = await cleanupMemory(maxAgeDays)
      await this.loadSessions()
      await this.loadFacts()
      return result
    },
    resetError() {
      this.error = ''
    },
  },
})
