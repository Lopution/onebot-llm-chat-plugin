import client, { unwrapResponse, type ApiResponse } from '../http'

export async function listCorpora() {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/knowledge/corpora')
  return unwrapResponse(data)
}

export async function listDocuments(corpusId: string) {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>('/knowledge/documents', {
    params: { corpus_id: corpusId },
  })
  return unwrapResponse(data)
}

export async function listChunks(corpusId: string, docId: string) {
  const { data } = await client.get<ApiResponse<Array<Record<string, unknown>>>>(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks`,
    { params: { corpus_id: corpusId } },
  )
  return unwrapResponse(data)
}

export async function ingestKnowledge(payload: Record<string, unknown>) {
  const { data } = await client.post<ApiResponse<Record<string, unknown>>>('/knowledge/ingest', payload)
  return unwrapResponse(data)
}

export async function deleteDocument(corpusId: string, docId: string) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(
    `/knowledge/documents/${encodeURIComponent(docId)}`,
    { params: { corpus_id: corpusId } },
  )
  return unwrapResponse(data)
}
