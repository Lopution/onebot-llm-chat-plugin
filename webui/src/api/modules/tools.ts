import client, { unwrapResponse, type ApiResponse } from '../http'
import type { ToolListResult } from '../types'

export async function listTools(includeDisabled = true) {
  const { data } = await client.get<ApiResponse<ToolListResult>>('/tools', {
    params: { include_disabled: includeDisabled },
  })
  return unwrapResponse(data)
}

export async function toggleTool(toolName: string, enabled: boolean) {
  const { data } = await client.post<ApiResponse<{ name: string; enabled: boolean; persisted: boolean }>>(
    `/tools/${encodeURIComponent(toolName)}/toggle`,
    { enabled },
  )
  return unwrapResponse(data)
}
