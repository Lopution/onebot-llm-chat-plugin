import client, { unwrapResponse, type ApiResponse } from '../http'
import type { ConfigSection } from '../types'

export async function getConfigEnvPath() {
  const { data } = await client.get<ApiResponse<{ path: string }>>('/config/env-path')
  return unwrapResponse(data)
}

export async function getConfigSections() {
  const { data } = await client.get<ApiResponse<{ sections: ConfigSection[] }>>('/config')
  return unwrapResponse(data)
}

export async function getEffectiveConfigSnapshot() {
  const { data } = await client.get<ApiResponse<Record<string, unknown>>>('/config/effective')
  return unwrapResponse(data)
}

export async function updateConfig(values: Record<string, unknown>) {
  const { data } = await client.put<ApiResponse<Record<string, unknown>>>('/config', values)
  return unwrapResponse(data)
}

export async function reloadConfig() {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/config/reload')
  return unwrapResponse(data)
}

export async function exportConfig(includeSecrets = false) {
  const { data } = await client.get<ApiResponse<{ config: Record<string, unknown> }>>('/config/export', {
    params: { include_secrets: includeSecrets },
  })
  return unwrapResponse(data)
}

export async function importConfig(configValues: Record<string, unknown>, applyRuntime = true) {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/config/import', {
    config: configValues,
    apply_runtime: applyRuntime,
  })
  return unwrapResponse(data)
}
