"""Storage backend factory."""
from __future__ import annotations

from ..config import Settings
from .base import StorageBackend
from .local import LocalStorageBackend


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.resolved_storage_dir)
    raise RuntimeError(
        "MAS_STORAGE_BACKEND=s3 requires the optional S3 backend. "
        "For the current Render configuration use MAS_STORAGE_BACKEND=local."
    )
