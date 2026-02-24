import { defineStore } from 'pinia'
import {
  listUserProfiles,
  getUserProfile,
  updateUserProfile,
  deleteUserProfile,
} from '../api/modules/user-profile'
import type { UserProfileListItem } from '../api/types'

export const useUserProfileStore = defineStore('userProfile', {
  state: () => ({
    loading: false,
    error: '',
    lastLoadedAt: 0,
    items: [] as UserProfileListItem[],
    total: 0,
    page: 1,
    pageSize: 20,
    query: '',
    selectedId: '',
    detail: null as UserProfileListItem | null,
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const data = await listUserProfiles(this.page, this.pageSize, this.query)
        this.items = data.items || []
        this.total = Number(data.total || 0)
        this.lastLoadedAt = Date.now()
        if (this.selectedId) {
          const exists = this.items.some((item) => item.platform_user_id === this.selectedId)
          if (!exists) {
            this.selectedId = ''
            this.detail = null
          }
        }
        if (!this.selectedId && this.items.length > 0) {
          this.selectedId = this.items[0].platform_user_id
          await this.loadDetail(this.selectedId)
        }
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async loadDetail(platformUserId: string) {
      this.detail = await getUserProfile(platformUserId)
    },
    async select(platformUserId: string) {
      this.selectedId = platformUserId
      await this.loadDetail(platformUserId)
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
    async update(platformUserId: string, payload: Record<string, unknown>) {
      this.detail = await updateUserProfile(platformUserId, payload)
      await this.load()
    },
    async remove(platformUserId: string) {
      await deleteUserProfile(platformUserId)
      this.selectedId = ''
      this.detail = null
      await this.load()
    },
    resetError() {
      this.error = ''
    },
  },
})
