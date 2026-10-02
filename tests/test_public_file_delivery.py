from pathlib import Path
from fastapi.testclient import TestClient


def _post(client: TestClient, path: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    csrf = client.cookies.get("mas_csrf")
    if csrf:
        headers.setdefault("X-CSRF-Token", csrf)
    return client.post(path, headers=headers, **kwargs)


def test_public_file_delivery_supports_inline_and_range(client: TestClient, settings):
    r = _post(client, "/api/auth/register", json={"username": "publicfile1", "password": "password1234"})
    assert r.status_code == 200
    r = _post(client, "/api/rooms", json={
        "name": "اتاق فایل",
        "capacity": 1,
        "public_enabled": True,
        "live_files_enabled": True,
    })
    assert r.status_code == 200
    room_id = r.json()["room"]["id"]
    token = client.get(f"/api/rooms/{room_id}").json()["room"]["public_token"]

    content = b"%PDF-1.4\n0123456789abcdefghijklmnopqrstuvwxyz"
    r = _post(client, f"/api/rooms/{room_id}/files", files={"file": ("slides.pdf", content, "application/pdf")}, data={"upload_type": "common"})
    assert r.status_code == 200
    file_id = r.json()["file"]["id"]

    _post(client, "/api/auth/logout")

    r = client.get(f"/api/public/{token}/files/{file_id}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert b"frame-ancestors self" in r.headers["content-security-policy"].encode()
    assert r.content == content

    r = client.get(f"/api/public/{token}/files/{file_id}", headers={"Range": "bytes=5-14"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 5-14/{len(content)}"
    assert r.content == content[5:15]


def test_public_file_missing_returns_404_not_500(client: TestClient, settings):
    r = _post(client, "/api/auth/register", json={"username": "publicfile2", "password": "password1234"})
    assert r.status_code == 200
    r = _post(client, "/api/rooms", json={
        "name": "اتاق فایل گمشده",
        "capacity": 1,
        "public_enabled": True,
        "live_files_enabled": True,
    })
    room_id = r.json()["room"]["id"]
    token = client.get(f"/api/rooms/{room_id}").json()["room"]["public_token"]
    r = _post(client, f"/api/rooms/{room_id}/files", files={"file": ("slides.pdf", b"123", "application/pdf")}, data={"upload_type": "common"})
    file_id = r.json()["file"]["id"]
    from sqlalchemy import select
    from mas_app.db.models import SpeechFile
    with client.app.state.database.session() as db:
        speech_file = db.execute(select(SpeechFile).where(SpeechFile.id == file_id)).scalar_one()
        storage_file = client.app.state.storage.get_file_path(speech_file.storage_key)
        assert storage_file is not None
        storage_file.unlink()
    _post(client, "/api/auth/logout")

    r = client.get(f"/api/public/{token}/files/{file_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
