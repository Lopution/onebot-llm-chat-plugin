import { defineStore } from 'pinia'
import { listTools, toggleTool } from '../api/modules/tools'
import type { ToolItem } from '../api/types'

export const useToolsStore = defineStore('tools', {
  state: () => ({
    loading: false,
    error: '',
    lastLoadedAt: 0,
    items: [] as ToolItem[],
    total: 0,
    enabledTotal: 0,
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const data = await listTools(true)
        this.items = data.tools || []
        this.total = Number(data.total || this.items.length)
        this.enabledTotal = Number(data.enabled_total || this.items.filter((t) => t.enabled).length)
        this.lastLoadedAt = Date.now()
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async toggle(toolName: string, enabled: boolean) {
      const index = this.items.findIndex((item) => item.name === toolName)
      const previous = index >= 0 ? Boolean(this.items[index].enabled) : !enabled
      if (index >= 0) {
        this.items[index].enabled = enabled
      }
      try {
        await toggleTool(toolName, enabled)
        await this.load()
      } catch (error) {
        if (index >= 0) {
          this.items[index].enabled = previous
        }
        throw error
      }
    },
    resetError() {
      this.error = ''
    },
  },
})
