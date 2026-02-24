import client, { unwrapResponse, type ApiResponse } from '../http'
import type { SessionDetail, SessionListResult } from '../types'

export async function listSessions(page = 1, pageSize = 20, query = '') {
  const { data } = await client.get<ApiResponse<SessionListResult>>('/session', {
    params: { page, page_size: pageSize, query },
  })
  return unwrapResponse(data)
}

export async function getSessionDetail(sessionKey: string, previewLimit = 8) {
  const { data } = await client.get<ApiResponse<SessionDetail>>(
    `/session/${encodeURIComponent(sessionKey)}`,
    { params: { preview_limit: previewLimit } },
  )
  return unwrapResponse(data)
}

export async function clearSession(sessionKey: string, purgeArchive = true, purgeTopicState = true) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(
    `/session/${encodeURIComponent(sessionKey)}`,
    {
      params: {
        purge_archive: purgeArchive,
        purge_topic_state: purgeTopicState,
      },
    },
  )
  return unwrapResponse(data)
}
