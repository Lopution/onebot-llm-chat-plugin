import client, { unwrapResponse, type ApiResponse } from '../http'

export async function listMemorySessions() {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/memory/sessions')
  return unwrapResponse(data)
}

export async function listMemoryFacts(sessionKey: string) {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/memory/facts', {
    params: { session_key: sessionKey },
  })
  return unwrapResponse(data)
}

export async function deleteMemory(id: number) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(`/memory/${id}`)
  return unwrapResponse(data)
}

export async function cleanupMemory(maxAgeDays: number) {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/memory/cleanup', {
    max_age_days: maxAgeDays,
  })
  return unwrapResponse(data)
}
