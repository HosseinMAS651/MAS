"""Persistent local-disk storage backend suitable for Render persistent disks."""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from .base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        key = (key or "").replace("\\", "/").lstrip("/")
        path = (self.root / key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("storage key خارج از محدودهٔ storage است") from exc
        return path

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> tuple[int, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        digest = hashlib.sha256(data).hexdigest()
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return len(data), digest

    @staticmethod
    def _delete(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return

    async def save_bytes(self, key: str, data: bytes) -> tuple[int, str]:
        if not data:
            raise ValueError("empty data")
        path = self._safe_path(key)
        return await asyncio.to_thread(self._write_bytes, path, data)

    async def save_stream(self, key: str, stream: AsyncIterator[bytes]) -> tuple[int, str]:
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        size = 0
        digest = hashlib.sha256()
        try:
            with tmp.open("wb") as fh:
                async for chunk in stream:
                    if not chunk:
                        continue
                    fh.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                if size <= 0:
                    raise ValueError("empty data")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            return size, digest.hexdigest()
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    async def delete(self, key: str) -> None:
        path = self._safe_path(key)
        await asyncio.to_thread(self._delete, path)

    def open_stream(self, key: str) -> Iterator[bytes]:
        path = self._safe_path(key)
        if not path.is_file():
            raise FileNotFoundError(key)

        def iterator() -> Iterator[bytes]:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return iterator()

    def _assemble(self, target: Path, sources: list[Path]) -> tuple[int, str]:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        size = 0
        digest = hashlib.sha256()
        try:
            with tmp.open("wb") as out:
                for source in sources:
                    with source.open("rb") as fh:
                        while True:
                            chunk = fh.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                if size <= 0:
                    raise ValueError("no chunks to assemble")
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, target)
            return size, digest.hexdigest()
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    async def assemble_chunks(self, target_key: str, chunk_keys: list[str]) -> tuple[int, str]:
        if not chunk_keys:
            raise ValueError("no chunks to assemble")
        target = self._safe_path(target_key)
        sources = [self._safe_path(k) for k in chunk_keys]
        return await asyncio.to_thread(self._assemble, target, sources)

    def available_bytes(self) -> int | None:
        try:
            return shutil.disk_usage(self.root).free
        except OSError:
            return None

    async def check_health(self) -> tuple[bool, str]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".healthcheck"
            await asyncio.to_thread(probe.write_bytes, b"ok")
            await asyncio.to_thread(probe.unlink)
            return True, "ok"
        except Exception as exc:
            return False, str(exc)[:250]
