"""Storage backends for MAS."""

from .base import StorageBackend
from .factory import create_storage
from .local import LocalStorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend", "create_storage"]
