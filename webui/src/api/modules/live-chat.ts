import client, { toWebUiApiPath, unwrapResponse, type ApiResponse } from '../http'
import type { LiveChatReply } from '../types'
import { _extractToken, requestTicket } from './auth'

export async function sendLiveChatMessage(
  message: string,
  sessionId = 'private:webui_admin',
  userId = 'webui_admin',
  groupId = '',
) {
  const { data } = await client.post<ApiResponse<LiveChatReply>>('/live-chat/message', {
    message,
    session_id: sessionId,
    user_id: userId,
    group_id: groupId,
  })
  return unwrapResponse(data)
}

export async function buildLiveChatWsUrl(): Promise<string> {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = new URL(toWebUiApiPath('/live-chat/ws'), window.location.origin)
  url.protocol = protocol
  try {
    const ticket = await requestTicket('live_chat_ws')
    url.searchParams.set('ticket', ticket)
    url.searchParams.set('scope', 'live_chat_ws')
  } catch {
    const token = _extractToken()
    if (token) {
      url.searchParams.set('token', token)
    }
  }
  return url.toString()
}
