import { defineStore } from 'pinia'
import {
  listPersonas,
  createPersona,
  updatePersona,
  activatePersona,
  deletePersona,
} from '../api/modules/persona'
import type { Persona } from '../api/types'

export const usePersonaStore = defineStore('persona', {
  state: () => ({
    loading: false,
    error: '',
    lastLoadedAt: 0,
    items: [] as Persona[],
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        this.items = await listPersonas()
        this.lastLoadedAt = Date.now()
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
    async create(payload: Record<string, unknown>) {
      await createPersona(payload)
      await this.load()
    },
    async update(personaId: number, payload: Record<string, unknown>) {
      await updatePersona(personaId, payload)
      await this.load()
    },
    async activate(personaId: number) {
      await activatePersona(personaId)
      await this.load()
    },
    async remove(personaId: number) {
      await deletePersona(personaId)
      await this.load()
    },
    resetError() {
      this.error = ''
    },
  },
})
