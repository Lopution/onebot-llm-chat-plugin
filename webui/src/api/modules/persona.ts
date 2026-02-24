import client, { unwrapResponse, type ApiResponse } from '../http'
import type { Persona } from '../types'

export async function listPersonas() {
  const { data } = await client.get<ApiResponse<Array<Persona>>>('/persona')
  return unwrapResponse(data)
}

export async function createPersona(payload: Record<string, unknown>) {
  const { data } = await client.post<ApiResponse<Persona>>('/persona', payload)
  return unwrapResponse(data)
}

export async function updatePersona(personaId: number, payload: Record<string, unknown>) {
  const { data } = await client.put<ApiResponse<Persona>>(`/persona/${personaId}`, payload)
  return unwrapResponse(data)
}

export async function activatePersona(personaId: number) {
  const { data } = await client.post<ApiResponse<Persona>>(`/persona/${personaId}/activate`)
  return unwrapResponse(data)
}

export async function deletePersona(personaId: number) {
  const { data } = await client.delete<ApiResponse<Record<string, unknown>>>(`/persona/${personaId}`)
  return unwrapResponse(data)
}
