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
