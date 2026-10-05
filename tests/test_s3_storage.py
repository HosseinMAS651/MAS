"""S3-compatible storage tests using an in-memory client double."""
from __future__ import annotations

import asyncio
import hashlib
import io

import pytest

from mas_app.config import Settings
from mas_app.storage.factory import create_storage
from mas_app.storage.s3 import S3StorageBackend


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[(Bucket, Key)] = bytes(Body)

    def upload_fileobj(self, fileobj, bucket: str, key: str) -> None:
        self.objects[(bucket, key)] = fileobj.read()

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, io.BytesIO]:
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)

    def head_bucket(self, *, Bucket: str) -> None:
        assert Bucket == "mas-test"

    def generate_presigned_url(self, operation: str, *, Params: dict, ExpiresIn: int) -> str:
        assert operation == "get_object"
        assert ExpiresIn == 600
        return f"https://objects.example/{Params['Key']}?download=1"


def _settings(**overrides) -> Settings:
    values = {
        "env": "test",
        "database_url": "sqlite:///:memory:",
        "secret_key": "test-secret-key-at-least-32-characters-long",
        "storage_backend": "s3",
        "s3_bucket": "mas-test",
        "s3_access_key_id": "test-access",
        "s3_secret_access_key": "test-secret",
        "s3_prefix": "company/mas/",
        "s3_use_presigned_download": True,
        "s3_presigned_ttl_seconds": 600,
    }
    values.update(overrides)
    return Settings(**values)


def test_s3_storage_stream_assembly_cleanup_and_presigned_download():
    client = FakeS3Client()
    settings = _settings()
    backend = S3StorageBackend(settings, client=client)

    async def upload_stream():
        async def source():
            yield b"stream-"
            yield b"contents"

        return await backend.save_stream("files/report.txt", source())

    stream_size, stream_hash = asyncio.run(upload_stream())
    assert stream_size == len(b"stream-contents")
    assert stream_hash == hashlib.sha256(b"stream-contents").hexdigest()

    chunk_a = b"audio part one"
    chunk_b = b" and part two"
    asyncio.run(backend.save_bytes("chunks/1/2/00000000.bin", chunk_a))
    asyncio.run(backend.save_bytes("chunks/1/2/00000001.bin", chunk_b))
    final_size, final_hash = asyncio.run(
        backend.assemble_chunks(
            "recordings/1/final.webm",
            ["chunks/1/2/00000000.bin", "chunks/1/2/00000001.bin"],
        )
    )
    expected = chunk_a + chunk_b
    assert final_size == len(expected)
    assert final_hash == hashlib.sha256(expected).hexdigest()
    assert b"".join(backend.open_stream("recordings/1/final.webm")) == expected
    assert backend.get_presigned_download_url("recordings/1/final.webm", "audio file.webm").startswith(
        "https://objects.example/company/mas/recordings/1/final.webm?"
    )
    assert asyncio.run(backend.check_health()) == (True, "ok")

    asyncio.run(backend.delete("recordings/1/final.webm"))
    with pytest.raises(FileNotFoundError):
        next(backend.open_stream("recordings/1/final.webm"))


def test_s3_storage_rejects_parent_directory_keys():
    backend = S3StorageBackend(_settings(), client=FakeS3Client())
    with pytest.raises(ValueError, match="Unsafe or empty"):
        backend.open_stream("../private.txt")


def test_storage_factory_wires_s3_backend(monkeypatch):
    import boto3

    fake_client = FakeS3Client()
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: fake_client)
    backend = create_storage(_settings())
    assert isinstance(backend, S3StorageBackend)
    assert backend.client is fake_client
