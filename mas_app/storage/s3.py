"""S3-compatible object storage backend (AWS S3, R2, MinIO, etc.)."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator, Iterator
from urllib.parse import quote

from ..config import Settings
from .base import StorageBackend


class S3StorageBackend(StorageBackend):
    def __init__(self, settings: Settings, *, client=None) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "MAS_STORAGE_BACKEND=s3 requires boto3; install requirements-s3.txt."
            ) from exc

        self.settings = settings
        self.bucket = settings.s3_bucket
        self.prefix = self._clean_prefix(settings.s3_prefix)
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            config=Config(s3={"addressing_style": settings.s3_addressing_style}),
        )

    @staticmethod
    def _clean_prefix(prefix: str) -> str:
        parts = [part for part in (prefix or "").replace("\\", "/").split("/") if part and part != "."]
        if any(part == ".." for part in parts):
            raise ValueError("S3 prefix may not contain parent-directory segments.")
        return "/".join(parts) + ("/" if parts else "")

    def _key(self, key: str) -> str:
        parts = [part for part in (key or "").replace("\\", "/").split("/") if part and part != "."]
        if not parts or any(part == ".." for part in parts):
            raise ValueError("Unsafe or empty S3 storage key.")
        clean = "/".join(parts)
        return f"{self.prefix}{clean}"

    async def save_bytes(self, key: str, data: bytes) -> tuple[int, str]:
        if not data:
            raise ValueError("empty data")
        object_key = self._key(key)
        digest = hashlib.sha256(data).hexdigest()
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
        )
        return len(data), digest

    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> tuple[int, str]:
        object_key = self._key(key)
        digest = hashlib.sha256()
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as spool:
            async for chunk in stream:
                if not chunk:
                    continue
                size += len(chunk)
                digest.update(chunk)
                spool.write(chunk)
            if size <= 0:
                raise ValueError("empty data")
            spool.seek(0)
            await asyncio.to_thread(
                self.client.upload_fileobj,
                spool,
                self.bucket,
                object_key,
            )
        return size, digest.hexdigest()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=self.bucket,
            Key=self._key(key),
        )

    def open_stream(self, key: str) -> Iterator[bytes]:
        object_key = self._key(key)
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=object_key)["Body"]
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
            if code in {"NoSuchKey", "NotFound", "404"} or isinstance(exc, KeyError):
                raise FileNotFoundError(key) from exc
            raise

        def iterator() -> Iterator[bytes]:
            try:
                while True:
                    chunk = body.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                body.close()

        return iterator()

    def _assemble_sync(self, target_key: str, chunk_keys: list[str]) -> tuple[int, str]:
        object_key = self._key(target_key)
        digest = hashlib.sha256()
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as spool:
            for chunk_key in chunk_keys:
                body = self.client.get_object(Bucket=self.bucket, Key=self._key(chunk_key))["Body"]
                try:
                    while True:
                        chunk = body.read(1024 * 1024)
                        if not chunk:
                            break
                        spool.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                finally:
                    body.close()
            if size <= 0:
                raise ValueError("no chunks to assemble")
            spool.seek(0)
            self.client.upload_fileobj(spool, self.bucket, object_key)
        return size, digest.hexdigest()

    async def assemble_chunks(self, target_key: str, chunk_keys: list[str]) -> tuple[int, str]:
        if not chunk_keys:
            raise ValueError("no chunks to assemble")
        return await asyncio.to_thread(self._assemble_sync, target_key, chunk_keys)

    async def check_health(self) -> tuple[bool, str]:
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)
            return True, "ok"
        except Exception as exc:  # pragma: no cover - vendor/network dependent
            return False, f"{type(exc).__name__}: {exc}"[:250]

    def get_presigned_download_url(self, key: str, filename: str) -> str | None:
        if not self.settings.s3_use_presigned_download:
            return None
        disposition = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self._key(key),
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=self.settings.s3_presigned_ttl_seconds,
        )
