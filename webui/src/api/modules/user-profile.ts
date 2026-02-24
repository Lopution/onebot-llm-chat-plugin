import client, { unwrapResponse, type ApiResponse } from '../http'
import type { UserProfileListItem, UserProfileListResult } from '../types'

export async function listUserProfiles(page = 1, pageSize = 20, query = '') {
  const { data } = await client.get<ApiResponse<UserProfileListResult>>('/user-profile', {
    params: { page, page_size: pageSize, query },
  })
  return unwrapResponse(data)
}

export async function getUserProfile(platformUserId: string) {
  const { data } = await client.get<ApiResponse<UserProfileListItem>>(
    `/user-profile/${encodeURIComponent(platformUserId)}`,
  )
  return unwrapResponse(data)
}

export async function updateUserProfile(platformUserId: string, payload: Record<string, unknown>) {
  const { data } = await client.put<ApiResponse<UserProfileListItem>>(
    `/user-profile/${encodeURIComponent(platformUserId)}`,
    payload,
  )
  return unwrapResponse(data)
}

export async function deleteUserProfile(platformUserId: string) {
  const { data } = await client.delete<ApiResponse<{ ok: boolean }>>(
    `/user-profile/${encodeURIComponent(platformUserId)}`,
  )
  return unwrapResponse(data)
}
