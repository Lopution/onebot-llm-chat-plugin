import { defineStore } from 'pinia'
import {
  exportConfig,
  getConfigSections,
  importConfig,
  reloadConfig,
  updateConfig,
} from '../api/modules/config'
import type { ConfigSection } from '../api/types'

export const useConfigStore = defineStore('config', {
  state: () => ({
    loading: false,
    sections: [] as ConfigSection[],
    error: '',
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const data = await getConfigSections()
        this.sections = data.sections || []
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async save(values: Record<string, unknown>) {
      return await updateConfig(values)
    },
    async reload() {
      return await reloadConfig()
    },
    async export(includeSecrets = false) {
      return await exportConfig(includeSecrets)
    },
    async import(values: Record<string, unknown>, applyRuntime = true) {
      return await importConfig(values, applyRuntime)
    },
  },
})
