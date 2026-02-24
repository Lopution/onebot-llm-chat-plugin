import client, { toWebUiApiPath, unwrapResponse, type ApiResponse } from '../http'
import { _extractToken, requestTicket } from './auth'

export async function importBackup(file: File, applyRuntime = true) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('apply_runtime', String(Boolean(applyRuntime)))
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/backup/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return unwrapResponse(data)
}

export async function buildBackupExportUrl(): Promise<string> {
  const base = toWebUiApiPath('/backup/export')
  try {
    const ticket = await requestTicket('backup_export')
    return `${base}?ticket=${encodeURIComponent(ticket)}&scope=backup_export`
  } catch {
    const token = _extractToken()
    return token ? `${base}?token=${encodeURIComponent(token)}` : base
  }
}
