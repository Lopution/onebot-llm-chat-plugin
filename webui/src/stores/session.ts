import { defineStore } from 'pinia'
import {
  listSessions,
  getSessionDetail,
  clearSession,
} from '../api/modules/session'
import type { SessionDetail, SessionListItem } from '../api/types'

export const useSessionStore = defineStore('session', {
  state: () => ({
    loading: false,
    error: '',
    lastLoadedAt: 0,
    items: [] as SessionListItem[],
    total: 0,
    page: 1,
    pageSize: 20,
    query: '',
    selectedKey: '',
    detail: null as SessionDetail | null,
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const data = await listSessions(this.page, this.pageSize, this.query)
        this.items = data.items || []
        this.total = Number(data.total || 0)
        this.lastLoadedAt = Date.now()
        if (this.selectedKey) {
          const exists = this.items.some((item) => item.session_key === this.selectedKey)
          if (!exists) {
            this.selectedKey = ''
            this.detail = null
          }
        }
        if (!this.selectedKey && this.items.length > 0) {
          this.selectedKey = this.items[0].session_key
          await this.loadDetail()
        }
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async loadDetail() {
      if (!this.selectedKey) {
        this.detail = null
        return
      }
      this.detail = await getSessionDetail(this.selectedKey, 10)
    },
    async select(key: string) {
      this.selectedKey = key
      await this.loadDetail()
    },
    async search(query: string) {
      this.query = query
      this.page = 1
      await this.load()
    },
    async changePage(page: number) {
      this.page = page
      await this.load()
    },
    async clearCurrent() {
      if (!this.selectedKey) return
      await clearSession(this.selectedKey, true, true)
      this.selectedKey = ''
      this.detail = null
      await this.load()
    },
    resetError() {
      this.error = ''
    },
  },
})
