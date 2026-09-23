"""Non-invasive startup patches needed by the current MAS repository."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

_applied = False


def apply_patches() -> None:
    global _applied
    if _applied:
        return

    # Patch the recording dependency before router modules import it.
    import mas_app.api.deps as deps
    from .config import Settings
    from .storage.base import StorageBackend
    from .storage.factory import create_storage
    from .services.recording_security_service import SecureRecordingService

    def secure_get_recording_service(
        settings: Annotated[Settings, Depends(deps.get_app_settings)],
        storage: Annotated[StorageBackend, Depends(deps.get_storage_backend)],
    ) -> SecureRecordingService:
        return SecureRecordingService(settings, storage)

    deps.get_recording_service = secure_get_recording_service

    # Make the current process fail cleanly if a stale repository copy contains
    # the old Python-version default; .python-version is the primary guard for Render.
    _applied = True
