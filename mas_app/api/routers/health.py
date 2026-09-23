"""Health and readiness probes for deployment platforms."""
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
def health_check(settings: Annotated[Settings, Depends(get_app_settings)]) -> JSONResponse:
    """Lightweight process liveness probe; it must not depend on external services."""
    return JSONResponse(status_code=200, content={"ok": True, "version": "2.0.0"})


@router.get("/ready")
async def readiness_check(
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_app_database)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> JSONResponse:
    """Readiness probe for Render/Kubernetes-style dependency checks."""
    db_ok, db_msg = database.ping()
    storage_ok, storage_msg = await storage.check_health()
    ready = db_ok and storage_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "ok": ready,
            "version": "2.0.0",
            "db": db_ok,
            "db_error": None if db_ok else db_msg,
            "storage": storage_ok,
            "storage_error": None if storage_ok else storage_msg,
            "storage_backend": settings.storage_backend,
        },
    )
