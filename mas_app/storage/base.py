"""محیط انتزاعی ذخیره‌سازی فایل‌ها (محلی و ابری S3)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any


class StorageBackend(ABC):
    @abstractmethod
    async def check_health(self) -> tuple[bool, str | None]:
        """بررسی سلامت سرویس ذخیره‌سازی."""
        pass

    @abstractmethod
    def get_presigned_download_url(
        self, key: str, filename: str | None = None
    ) -> str | None:
        """تولید آدرس موقت دانلود برای سرویس‌های S3."""
        pass

    @abstractmethod
    def open_stream(
        self, key: str, chunk_size: int = 65536
    ) -> Generator[bytes, None, None]:
        """باز کردن فایل به صورت جریان بایت‌ها جهت پاسخ‌دهی HTTP."""
        pass

    @abstractmethod
    async def save_bytes(self, key: str, data: bytes) -> tuple[int, str]:
        """ذخیره بایت‌ها و محاسبه اندازه و هش SHA-256."""
        pass

    @abstractmethod
    async def save_stream(self, key: str, stream: Any) -> tuple[int, str]:
        """ذخیره استریم ورودی و محاسبه اندازه و هش SHA-256."""
        pass

    @abstractmethod
    async def assemble_chunks(
        self, target_key: str, chunk_keys: list[str]
    ) -> tuple[int, str]:
        """تجمیع تکه‌های ضبط در یک فایل نهایی."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """حذف فایل از فضای ذخیره‌سازی."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """بررسی وجود فایل."""
        pass
