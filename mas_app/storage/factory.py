"""کارخانهٔ ساخت ارائه‌دهنده ذخیره‌سازی."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import StorageBackend
from .local import LocalStorage
from .s3 import S3Storage

if TYPE_CHECKING:
    from ..config import Settings


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings)
