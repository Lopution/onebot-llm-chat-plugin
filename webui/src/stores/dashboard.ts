import { defineStore } from 'pinia'
import {
  getDashboardHealth,
  getDashboardMetrics,
  getDashboardStats,
  getDashboardTimeline,
} from '../api/modules/dashboard'
import type { DashboardTimelinePoint } from '../api/types'

export const useDashboardStore = defineStore('dashboard', {
  state: () => ({
    loading: false,
    health: {} as Record<string, unknown>,
    metrics: {} as Record<string, number>,
    stats: {} as Record<string, unknown>,
    timeline: [] as DashboardTimelinePoint[],
    error: '',
  }),
  actions: {
    async refresh() {
      this.loading = true
      this.error = ''
      try {
        const [health, metrics, stats, timeline] = await Promise.all([
          getDashboardHealth(),
          getDashboardMetrics(),
          getDashboardStats(),
          getDashboardTimeline(24, 3600),
        ])
        this.health = health as unknown as Record<string, unknown>
        this.metrics = metrics
        this.stats = stats
        this.timeline = timeline.points || []
      } catch (error) {
        this.error = String(error)
      } finally {
        this.loading = false
      }
    },
  },
})
