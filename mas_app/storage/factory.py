"""Storage backend factory."""
from __future__ import annotations

from ..config import Settings
from .base import StorageBackend
from .local import LocalStorageBackend


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.resolved_storage_dir)
    if settings.storage_backend == "s3":
        from .s3 import S3StorageBackend

        return S3StorageBackend(settings)
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
