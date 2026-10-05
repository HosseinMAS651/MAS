from fastapi.testclient import TestClient
from sqlalchemy import select

from mas_app.db.models import SpeechFile


def _post(client: TestClient, path: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    csrf = client.cookies.get("mas_csrf")
    if csrf:
        headers.setdefault("X-CSRF-Token", csrf)
    return client.post(path, headers=headers, **kwargs)


def test_public_state_supports_conditional_etag_requests(client: TestClient):
    _post(client, "/api/auth/register", json={"username": "publicetaguser", "password": "password1234"})
    created = _post(
        client,
        "/api/rooms",
        json={"name": "اتاق ETag", "capacity": 1, "public_enabled": True},
    )
    room_id = created.json()["room"]["id"]
    token = client.get(f"/api/rooms/{room_id}").json()["room"]["public_token"]

    initial = client.get(f"/api/public/{token}/state")
    assert initial.status_code == 200
    etag = initial.headers["etag"]
    unchanged = client.get(
        f"/api/public/{token}/state", headers={"If-None-Match": etag}
    )
    assert unchanged.status_code == 304
    assert unchanged.headers["etag"] == etag


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
    r = _post(
        client,
        f"/api/rooms/{room_id}/files",
        files={"file": ("slides.pdf", content, "application/pdf")},
        data={"upload_type": "common"},
    )
    assert r.status_code == 200
    file_id = r.json()["file"]["id"]

    _post(client, "/api/auth/logout")

    r = client.get(f"/api/public/{token}/files/{file_id}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert b"frame-ancestors 'self'" in r.headers["content-security-policy"].encode()
    assert r.content == content

    r = client.get(f"/api/public/{token}/files/{file_id}", headers={"Range": "bytes=5-14"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 5-14/{len(content)}"
    assert r.content == content[5:15]


def test_public_report_hides_attachment_names_when_live_files_are_disabled(client: TestClient, monkeypatch):
    registered = _post(
        client,
        "/api/auth/register",
        json={"username": "publicreportprivacy", "password": "password1234"},
    )
    assert registered.status_code == 200
    created = _post(
        client,
        "/api/rooms",
        json={
            "name": "گزارش خصوصی",
            "capacity": 1,
            "public_enabled": True,
            "live_files_enabled": False,
        },
    )
    room_id = created.json()["room"]["id"]
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    token = detail["public_token"]
    speaker_id = detail["speakers"][0]["id"]

    for upload_type, speaker_id_value, filename in (
        ("common", None, "private-common-name.txt"),
        ("speaker", speaker_id, "private-speaker-name.txt"),
    ):
        form_data = {"upload_type": upload_type}
        if speaker_id_value is not None:
            form_data["speaker_id"] = str(speaker_id_value)
        uploaded = _post(
            client,
            f"/api/rooms/{room_id}/files",
            files={"file": (filename, b"private attachment", "text/plain")},
            data=form_data,
        )
        assert uploaded.status_code == 200

    from mas_app.services.pdf_report_service import PdfReportService

    captured: dict[str, object] = {}

    def fake_generate(cls, room, audit_events, reaction_counts, *, include_files=True):
        captured["include_files"] = include_files
        captured["filenames"] = [file.filename for file in room.files]
        return b"%PDF-1.4 privacy test"

    monkeypatch.setattr(PdfReportService, "generate_room_report", classmethod(fake_generate))
    report = client.get(f"/api/public/{token}/report/pdf")
    assert report.status_code == 200
    assert report.content.startswith(b"%PDF-")
    assert captured["include_files"] is False
    assert "private-common-name.txt" in captured["filenames"]
    assert "private-speaker-name.txt" in captured["filenames"]


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
    r = _post(
        client,
        f"/api/rooms/{room_id}/files",
        files={"file": ("slides.pdf", b"123", "application/pdf")},
        data={"upload_type": "common"},
    )
    file_id = r.json()["file"]["id"]
    with client.app.state.database.session() as db:
        speech_file = db.execute(select(SpeechFile).where(SpeechFile.id == file_id)).scalar_one()
        storage_file = client.app.state.storage.get_local_path(speech_file.storage_key)
        assert storage_file is not None
        storage_file.unlink()
    _post(client, "/api/auth/logout")

    r = client.get(f"/api/public/{token}/files/{file_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
