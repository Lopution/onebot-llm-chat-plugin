import client, { toWebUiApiPath, unwrapResponse, type ApiResponse } from '../http'
import { _extractToken, requestTicket } from './auth'

export async function getLogHistory(limit = 100, sinceId = 0, minLevel = 'INFO') {
  const { data } = await client.get<ApiResponse<{ events: Array<Record<string, unknown>>; next_id: number }>>(
    '/log/history',
    { params: { limit, since_id: sinceId, min_level: minLevel } },
  )
  return unwrapResponse(data)
}

export async function buildLogSseUrlWithTicket(minLevel = 'INFO'): Promise<string> {
  const base = toWebUiApiPath('/log/live')
  const params = new URLSearchParams()
  params.set('min_level', minLevel)
  try {
    const ticket = await requestTicket('log_live')
    params.set('ticket', ticket)
    params.set('scope', 'log_live')
  } catch {
    const token = _extractToken()
    if (token) {
      params.set('token', token)
    }
  }
  return `${base}?${params.toString()}`
}
