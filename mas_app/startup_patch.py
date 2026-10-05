"""Non-invasive startup patches needed by the current MAS repository."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends

_applied = False


def apply_patches() -> None:
    global _applied
    if _applied:
        return

    # Patch the recording dependency before router modules import it.
    import mas_app.api.deps as deps

    from .config import Settings
    from .services.recording_security_service import SecureRecordingService
    from .storage.base import StorageBackend

    def secure_get_recording_service(
        settings: Annotated[Settings, Depends(deps.get_app_settings)],
        storage: Annotated[StorageBackend, Depends(deps.get_storage_backend)],
    ) -> SecureRecordingService:
        return SecureRecordingService(settings, storage)

    deps.get_recording_service = secure_get_recording_service

    # Make the current process fail cleanly if a stale repository copy contains
    # the old Python-version default; .python-version is the primary guard for Render.
    _applied = True
