"""تست‌های لینک عمومی تماشاگران (بدون نیاز به لاگین)."""

from fastapi.testclient import TestClient


def test_public_room_spectator_access(client: TestClient):
    # ۱. ایجاد اتاق با لینک عمومی توسط ارائه‌کننده
    client.post(
        "/api/auth/register",
        json={"username": "host_user", "password": "password1234"},
    )
    res_room = client.post(
        "/api/rooms",
        json={
            "name": "سمینار آزاد علمی",
            "capacity": 3,
            "public_enabled": True,
            "live_files_enabled": True,
        },
    )
    room_id = res_room.json()["room"]["id"]
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    public_token = detail["public_token"]
    assert public_token is not None

    # ۲. خروج کاربر (شبیه‌سازی تماشاگر بدون لاگین)
    client.post("/api/auth/logout")

    # ۳. دسترسی تماشاگر به وضعیت عمومی با توکن
    res_pub = client.get(f"/api/public/{public_token}/state")
    assert res_pub.status_code == 200
    data = res_pub.json()["state"]
    assert data["room_name"] == "سمینار آزاد علمی"
    assert data["public_enabled"] is True
    assert "running" in data
    assert "speakers" in data

    # ۴. تماشاگر اجازهٔ دسترسی به endpointهای ادمین یا ایجاد اتاق ندارد
    res_unauth = client.post("/api/rooms", json={"name": "اتاق غیرمجاز"})
    assert res_unauth.status_code == 401



def test_public_file_serving_inline_and_speaker_scope(client: TestClient):
    """فایل مشترک باید مستقیم سرو شود و فایل اختصاصی فقط برای سخنران جاری قابل دسترسی باشد."""
    client.post(
        "/api/auth/register",
        json={"username": "public_files", "password": "password1234"},
    )
    res_room = client.post(
        "/api/rooms",
        json={
            "name": "اتاق فایل عمومی",
            "capacity": 2,
            "public_enabled": True,
            "live_files_enabled": True,
        },
    )
    room_id = res_room.json()["room"]["id"]
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    token = detail["public_token"]
    speaker_id = detail["speakers"][1]["id"]

    shared = client.post(
        f"/api/rooms/{room_id}/files",
        files={"file": ("shared.txt", b"hello public", "text/plain")},
        data={"upload_type": "common"},
    )
    assert shared.status_code == 200
    shared_id = shared.json()["file"]["id"]

    public_shared = client.get(f"/api/public/{token}/files/{shared_id}")
    assert public_shared.status_code == 200
    assert public_shared.content == b"hello public"
    assert public_shared.headers["content-disposition"].startswith("inline;")

    private = client.post(
        f"/api/rooms/{room_id}/files",
        files={"file": ("speaker.txt", b"private", "text/plain")},
        data={"upload_type": "speaker", "speaker_id": str(speaker_id)},
    )
    assert private.status_code == 200
    private_id = private.json()["file"]["id"]

    # هنوز اجرای جلسه آغاز نشده است؛ فایل اختصاصی نباید public باشد.
    hidden = client.get(f"/api/public/{token}/files/{private_id}")
    assert hidden.status_code == 404


def test_public_file_missing_storage_returns_404_not_500(client: TestClient):
    """رکورد DB بدون فایل فیزیکی نباید به خطای داخلی سرور تبدیل شود."""
    client.post(
        "/api/auth/register",
        json={"username": "public_missing", "password": "password1234"},
    )
    res_room = client.post(
        "/api/rooms",
        json={
            "name": "اتاق فایل گمشده",
            "capacity": 1,
            "public_enabled": True,
            "live_files_enabled": True,
        },
    )
    room_id = res_room.json()["room"]["id"]
    token = client.get(f"/api/rooms/{room_id}").json()["room"]["public_token"]


    uploaded = client.post(
        f"/api/rooms/{room_id}/files",
        files={"file": ("gone.txt", b"will disappear", "text/plain")},
        data={"upload_type": "common"},
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()["file"]["id"]

    from mas_app.db.models import SpeechFile

    with client.app.state.database.session() as session:
        file = session.get(SpeechFile, file_id)
        storage = client.app.state.storage
        path = storage.get_local_path(file.storage_key)
        assert path is not None
        path.unlink()

    missing = client.get(f"/api/public/{token}/files/{file_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
