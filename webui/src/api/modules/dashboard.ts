import client, { unwrapResponse, type ApiResponse } from '../http'
import type { DashboardHealth, DashboardTimeline } from '../types'

export async function getDashboardHealth() {
  const { data } = await client.get<ApiResponse<DashboardHealth>>('/dashboard/health')
  return unwrapResponse(data)
}

export async function getDashboardMetrics() {
  const { data } = await client.get<ApiResponse<Record<string, number>>>('/dashboard/metrics')
  return unwrapResponse(data)
}

export async function getDashboardStats() {
  const { data } = await client.get<ApiResponse<Record<string, unknown>>>('/dashboard/stats')
  return unwrapResponse(data)
}

export async function getDashboardTimeline(hours = 24, bucketSeconds = 3600) {
  const { data } = await client.get<ApiResponse<DashboardTimeline>>('/dashboard/timeline', {
    params: { hours, bucket_seconds: bucketSeconds },
  })
  return unwrapResponse(data)
}
