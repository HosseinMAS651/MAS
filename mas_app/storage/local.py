"""پیاده‌سازی ذخیره‌سازی محلی (Local FileSystem)."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import StorageBackend

if TYPE_CHECKING:
    from ..config import Settings


class LocalStorage(StorageBackend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_dir = settings.resolved_storage_dir

    def _resolve_path(self, key: str) -> Path:
        # پاک‌سازی کلید برای جلوگیری از Directory Traversal
        clean_key = str(Path(key)).lstrip("/\\")
        full_path = (self.base_dir / clean_key).resolve()
        # اطمینان از اینکه مسیر درون پوشه مجاز است
        if not str(full_path).startswith(str(self.base_dir.resolve())):
            raise ValueError(f"مسیر غیرمجاز برای ذخیره‌سازی: {key}")
        return full_path

    async def check_health(self) -> tuple[bool, str | None]:
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.base_dir / ".health_check"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def get_presigned_download_url(
        self, key: str, filename: str | None = None
    ) -> str | None:
        return None

    def open_stream(
        self, key: str, chunk_size: int = 65536
    ) -> Generator[bytes, None, None]:
        path = self._resolve_path(key)
        if not path.is_file():
            raise FileNotFoundError(f"فایل یافت نشد: {key}")
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    async def save_bytes(self, key: str, data: bytes) -> tuple[int, str]:
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(data)
        with open(path, "wb") as f:
            f.write(data)
        return len(data), h.hexdigest()

    async def save_stream(self, key: str, stream: Any) -> tuple[int, str]:
        path = self._resolve_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        total_size = 0

        with open(path, "wb") as f:
            if hasattr(stream, "read"):
                if asyncio.iscoroutinefunction(stream.read):
                    while chunk := await stream.read(65536):
                        f.write(chunk)
                        h.update(chunk)
                        total_size += len(chunk)
                else:
                    while chunk := stream.read(65536):
                        f.write(chunk)
                        h.update(chunk)
                        total_size += len(chunk)
            elif hasattr(stream, "__aiter__"):
                async for chunk in stream:
                    f.write(chunk)
                    h.update(chunk)
                    total_size += len(chunk)
            elif hasattr(stream, "__iter__"):
                for chunk in stream:
                    f.write(chunk)
                    h.update(chunk)
                    total_size += len(chunk)
            else:
                raise TypeError("شیء ورودی یک جریان داده معتبر نیست.")

        return total_size, h.hexdigest()

    async def assemble_chunks(
        self, target_key: str, chunk_keys: list[str]
    ) -> tuple[int, str]:
        target_path = self._resolve_path(target_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        total_size = 0

        with open(target_path, "wb") as out_f:
            for ck in chunk_keys:
                chunk_path = self._resolve_path(ck)
                if not chunk_path.is_file():
                    continue
                with open(chunk_path, "rb") as in_f:
                    while block := in_f.read(65536):
                        out_f.write(block)
                        h.update(block)
                        total_size += len(block)

        return total_size, h.hexdigest()

    async def delete(self, key: str) -> bool:
        try:
            path = self._resolve_path(key)
            if path.is_file():
                path.unlink(missing_ok=True)
                return True
            return False
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        try:
            return self._resolve_path(key).is_file()
        except Exception:
            return False
