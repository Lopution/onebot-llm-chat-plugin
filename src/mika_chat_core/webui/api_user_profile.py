"""WebUI user profile viewer APIs."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..utils.user_profile import get_user_profile_store
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper


class UserProfilePatchPayload(BaseModel):
    nickname: Optional[str] = None
    real_name: Optional[str] = None
    identity: Optional[str] = None
    occupation: Optional[str] = None
    age: Optional[str] = None
    location: Optional[str] = None
    birthday: Optional[str] = None
    preferences: Optional[list[str]] = None
    dislikes: Optional[list[str]] = None
    extra_info: Optional[dict[str, Any]] = None


def create_user_profile_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/user-profile",
        tags=["mika-webui-user-profile"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("")
    async def list_profiles(
        page: int = 1,
        page_size: int = 20,
        query: str = "",
    ) -> Dict[str, Any]:
        store = get_user_profile_store()
        return BaseRouteHelper.ok(
            await store.list_profiles(page=page, page_size=page_size, query=query)
        )

    @router.get("/{platform_user_id}")
    async def get_profile(platform_user_id: str) -> Dict[str, Any]:
        user_id = str(platform_user_id or "").strip()
        if not user_id:
            return BaseRouteHelper.error_response("platform_user_id is required")
        store = get_user_profile_store()
        profile = await store.get_profile(user_id)
        if not profile:
            return BaseRouteHelper.error_response("profile not found", status_code=404)
        return BaseRouteHelper.ok(profile)

    @router.put("/{platform_user_id}")
    async def update_profile(
        platform_user_id: str,
        payload: UserProfilePatchPayload,
    ) -> Dict[str, Any]:
        user_id = str(platform_user_id or "").strip()
        if not user_id:
            return BaseRouteHelper.error_response("platform_user_id is required")
        update_payload = payload.model_dump(exclude_none=True)
        if not update_payload:
            return BaseRouteHelper.error_response("no fields to update")
        store = get_user_profile_store()
        ok = await store.update_profile(user_id, update_payload)
        if not ok:
            return BaseRouteHelper.error_response("update failed", status_code=500)
        profile = await store.get_profile(user_id)
        return BaseRouteHelper.ok(profile)

    @router.delete("/{platform_user_id}")
    async def delete_profile(platform_user_id: str) -> Dict[str, Any]:
        user_id = str(platform_user_id or "").strip()
        if not user_id:
            return BaseRouteHelper.error_response("platform_user_id is required")
        store = get_user_profile_store()
        ok = await store.clear_profile(user_id)
        return BaseRouteHelper.ok({"ok": bool(ok)})

    return router


__all__ = ["UserProfilePatchPayload", "create_user_profile_router"]

