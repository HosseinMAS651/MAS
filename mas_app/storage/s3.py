"""پیاده‌سازی ذخیره‌سازی ابری S3-compatible (سازگار با MinIO، ابر آروان، Cloudflare R2 و AWS)."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from .base import StorageBackend

if TYPE_CHECKING:
    from ..config import Settings

try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


class S3Storage(StorageBackend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not HAS_BOTO3:
            raise RuntimeError(
                "برای استفاده از ذخیره‌سازی S3، نصب پکیج‌های boto3 الزامی است: pip install -r requirements-s3.txt"
            )

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "aws_access_key_id": settings.s3_access_key,
            "aws_secret_access_key": settings.s3_secret_key,
            "region_name": settings.s3_region or "us-east-1",
            "config": Config(signature_version="s3v4"),
        }
        if settings.s3_endpoint_url:
            client_kwargs["endpoint_url"] = settings.s3_endpoint_url

        self.client = boto3.client(**client_kwargs)
        self.bucket = settings.s3_bucket

    async def check_health(self) -> tuple[bool, str | None]:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: self.client.head_bucket(Bucket=self.bucket)
            )
            return True, None
        except Exception as exc:
            return False, str(exc)

    def get_presigned_download_url(
        self, key: str, filename: str | None = None
    ) -> str | None:
        params = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=3600,
            )
        except Exception:
            return None

    def open_stream(
        self, key: str, chunk_size: int = 65536
    ) -> Generator[bytes, None, None]:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            body = resp["Body"]
            while chunk := body.read(chunk_size):
                yield chunk
        except Exception as exc:
            raise FileNotFoundError(f"خطا در خواندن فایل S3: {exc}") from exc

    async def save_bytes(self, key: str, data: bytes) -> tuple[int, str]:
        loop = asyncio.get_running_loop()
        h = hashlib.sha256(data)
        await loop.run_in_executor(
            None,
            lambda: self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
            ),
        )
        return len(data), h.hexdigest()

    async def save_stream(self, key: str, stream: Any) -> tuple[int, str]:
        # جمع‌آوری بایت‌ها از جریان ورودی
        chunks = []
        h = hashlib.sha256()
        total_size = 0

        if hasattr(stream, "read"):
            if asyncio.iscoroutinefunction(stream.read):
                while chunk := await stream.read(65536):
                    chunks.append(chunk)
                    h.update(chunk)
                    total_size += len(chunk)
            else:
                while chunk := stream.read(65536):
                    chunks.append(chunk)
                    h.update(chunk)
                    total_size += len(chunk)
        elif hasattr(stream, "__aiter__"):
            async for chunk in stream:
                chunks.append(chunk)
                h.update(chunk)
                total_size += len(chunk)
        elif hasattr(stream, "__iter__"):
            for chunk in stream:
                chunks.append(chunk)
                h.update(chunk)
                total_size += len(chunk)

        full_data = b"".join(chunks)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=full_data,
            ),
        )
        return total_size, h.hexdigest()

    async def assemble_chunks(
        self, target_key: str, chunk_keys: list[str]
    ) -> tuple[int, str]:
        loop = asyncio.get_running_loop()

        def _assemble():
            parts = []
            h = hashlib.sha256()
            size = 0
            for k in chunk_keys:
                obj = self.client.get_object(Bucket=self.bucket, Key=k)
                data = obj["Body"].read()
                parts.append(data)
                h.update(data)
                size += len(data)
            full_data = b"".join(parts)
            self.client.put_object(Bucket=self.bucket, Key=target_key, Body=full_data)
            return size, h.hexdigest()

        return await loop.run_in_executor(None, _assemble)

    async def delete(self, key: str) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self.client.delete_object(Bucket=self.bucket, Key=key)
            )
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self.client.head_object(Bucket=self.bucket, Key=key)
            )
            return True
        except Exception:
            return False
