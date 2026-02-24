import client, { unwrapResponse, type ApiResponse } from '../http'

export function _extractToken(): string {
  return (localStorage.getItem('mika_webui_token') || '').trim()
}

export async function requestTicket(scope = 'general'): Promise<string> {
  const { data } = await client.post<ApiResponse<{ ticket: string; scope: string; expires_in_seconds: number }>>(
    '/auth/ticket',
    { scope },
  )
  return unwrapResponse(data).ticket
}
