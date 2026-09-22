"""مسیریاب بررسی سلامت سرویس (Health Check) — رفع کامل باگ OPS-03."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...config import Settings
from ...db.session import Database
from ...storage.base import StorageBackend
from ..deps import get_app_database, get_app_settings, get_storage_backend

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_app_database)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> JSONResponse:
    db_ok, db_msg = database.ping()
    storage_ok, storage_msg = await storage.check_health()

    is_healthy = db_ok and storage_ok
    status_code = 200 if is_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "ok": is_healthy,
            "version": "2.0.0",
            "db": db_ok,
            "db_error": None if db_ok else db_msg,
            "storage": storage_ok,
            "storage_error": None if storage_ok else storage_msg,
            "storage_backend": settings.storage_backend,
        },
    )
