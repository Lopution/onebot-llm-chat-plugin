"""WebUI backup/restore APIs."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..config import Config
from ..runtime import get_config as get_runtime_config
from ..runtime import set_config as set_runtime_config
from ..utils.context_db import close_database, get_db_path, init_database
from .auth import create_webui_auth_dependency
from .base_route import BaseRouteHelper
from .config_env import build_config_from_env_file

# Backward-compatible alias used by tests/monkeypatch.
_build_config_from_env_file = build_config_from_env_file


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_env_path() -> Path:
    env_path = str(os.getenv("DOTENV_PATH", "") or "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _repo_root() / ".env"


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def _safe_name(value: str) -> str:
    return str(value or "").replace("/", "_").replace("\\", "_")


def _remove_file_silent(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        return


def _multipart_available() -> bool:
    return importlib.util.find_spec("multipart") is not None


def create_backup_router(
    *,
    settings_getter: Callable[[], Config] = get_runtime_config,
) -> APIRouter:
    auth_dependency = create_webui_auth_dependency(settings_getter=settings_getter)
    router = APIRouter(
        prefix="/backup",
        tags=["mika-webui-backup"],
        dependencies=[Depends(auth_dependency)],
    )

    @router.get("/export")
    async def export_backup() -> FileResponse:
        timestamp = int(time.time())
        fd, backup_path = tempfile.mkstemp(prefix="mika-backup-", suffix=".zip")
        os.close(fd)
        backup_file = Path(backup_path)
        backup_name = f"mika-backup-{timestamp}.zip"
        db_path = get_db_path()
        env_path = _resolve_env_path()
        prompts_dir = _prompts_dir()

        with zipfile.ZipFile(backup_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if db_path.exists() and db_path.is_file():
                archive.write(db_path, arcname="contexts.db")
            if env_path.exists() and env_path.is_file():
                archive.write(env_path, arcname=".env")
            if prompts_dir.exists() and prompts_dir.is_dir():
                for prompt_file in sorted(prompts_dir.glob("*.yaml")):
                    archive.write(prompt_file, arcname=f"prompts/{prompt_file.name}")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "created_at": timestamp,
                        "db_path": str(db_path),
                        "env_path": str(env_path),
                        "prompt_count": len(list(prompts_dir.glob('*.yaml'))) if prompts_dir.exists() else 0,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        return FileResponse(
            path=backup_file,
            filename=backup_name,
            media_type="application/zip",
            background=BackgroundTask(_remove_file_silent, backup_file),
        )

    if _multipart_available():

        @router.post("/import")
        async def import_backup(
            file: UploadFile = File(...),
            apply_runtime: bool = Form(True),
        ) -> Dict[str, Any]:
            filename = str(file.filename or "").strip()
            if not filename.lower().endswith(".zip"):
                return BaseRouteHelper.error_response("backup file must be .zip")

            try:
                payload = await file.read()
            finally:
                await file.close()
            if not payload:
                return BaseRouteHelper.error_response("backup file is empty")

            restored_db = False
            restored_env = False
            restored_prompts = 0

            db_path = get_db_path()
            env_path = _resolve_env_path()
            prompts_dir = _prompts_dir()
            prompts_dir.mkdir(parents=True, exist_ok=True)
            env_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            with tempfile.TemporaryDirectory(prefix="mika-backup-import-") as workdir:
                uploaded = Path(workdir) / "uploaded.zip"
                uploaded.write_bytes(payload)

                with zipfile.ZipFile(uploaded, "r") as archive:
                    names = archive.namelist()
                    db_member = next(
                        (name for name in names if PurePosixPath(name).name == "contexts.db"),
                        None,
                    )
                    env_member = next(
                        (name for name in names if PurePosixPath(name).name == ".env"),
                        None,
                    )
                    prompt_members = [
                        name
                        for name in names
                        if str(PurePosixPath(name)).startswith("prompts/")
                        and PurePosixPath(name).suffix.lower() == ".yaml"
                    ]

                    if db_member:
                        await close_database()
                        db_path.write_bytes(archive.read(db_member))
                        await init_database()
                        restored_db = True

                    if env_member:
                        env_path.write_bytes(archive.read(env_member))
                        restored_env = True

                    for member in prompt_members:
                        posix = PurePosixPath(member)
                        prompt_name = _safe_name(posix.name)
                        if not prompt_name.endswith(".yaml"):
                            continue
                        target = prompts_dir / prompt_name
                        target.write_bytes(archive.read(member))
                        restored_prompts += 1

            if bool(apply_runtime) and restored_env:
                current_config = settings_getter()
                loaded = _build_config_from_env_file(env_path, current_config=current_config)
                set_runtime_config(loaded)

            return BaseRouteHelper.ok(
                {
                    "ok": True,
                    "restored_db": restored_db,
                    "restored_env": restored_env,
                    "restored_prompts": restored_prompts,
                    "applied_runtime": bool(apply_runtime and restored_env),
                }
            )

    else:

        @router.post("/import")
        async def import_backup_unavailable() -> Dict[str, Any]:
            return BaseRouteHelper.error_response(
                'backup import requires optional dependency "python-multipart"'
            )

    return router


__all__ = ["create_backup_router"]
