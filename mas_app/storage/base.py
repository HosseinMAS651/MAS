"""Abstract storage interface used by uploads, recordings and cleanup."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from pathlib import Path


class StorageBackend(ABC):
    """Backend-independent file storage contract."""

    @abstractmethod
    async def save_bytes(self, key: str, data: bytes) -> tuple[int, str]:
        raise NotImplementedError

    @abstractmethod
    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> tuple[int, str]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def open_stream(self, key: str) -> Iterator[bytes]:
        raise NotImplementedError

    @abstractmethod
    async def assemble_chunks(self, target_key: str, chunk_keys: list[str]) -> tuple[int, str]:
        raise NotImplementedError

    @abstractmethod
    async def check_health(self) -> tuple[bool, str]:
        raise NotImplementedError

    def get_presigned_download_url(self, key: str, filename: str) -> str | None:
        """Local storage has no presigned URLs; cloud backends can override this."""
        return None

    def get_local_path(self, key: str) -> Path | None:
        """Return a safe local filesystem path when the backend is local.

        Cloud backends should leave this as ``None`` and use a presigned URL
        or the streaming interface instead.
        """
        return None

    def available_bytes(self) -> int | None:
        """Return currently available storage bytes when the backend can measure it."""
        return None
