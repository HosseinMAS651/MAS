"""تست‌های مدیریت اتاق‌ها و رفع باگ‌های C-04 و C-07."""

from fastapi.testclient import TestClient


def _create_user_and_login(client: TestClient, username: str = "room_owner"):
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "password1234"},
    )


def test_create_and_list_rooms(client: TestClient):
    _create_user_and_login(client, "user_rooms_1")

    # ساخت اتاق
    res = client.post(
        "/api/rooms",
        json={
            "name": "همایش ملی هوش مصنوعی",
            "capacity": 5,
            "description": "بررسی دستاوردهای جدید",
            "recording_enabled": True,
            "live_files_enabled": True,
            "global_seconds": 600,
        },
    )
    assert res.status_code == 200
    room_id = res.json()["room"]["id"]

    # مشاهده لیست اتاق‌ها
    res_list = client.get("/api/rooms")
    assert res_list.status_code == 200
    rooms = res_list.json()["rooms"]
    assert any(r["id"] == room_id for r in rooms)


def test_capacity_shrink_protection_c04(client: TestClient):
    """بررسی رفع باگ C-04: جلوگیری از حذف بی‌صدای سخنران‌های نام‌دار در زمان کاهش ظرفیت."""
    _create_user_and_login(client, "user_shrink")

    # ساخت اتاق با ظرفیت ۳
    res = client.post(
        "/api/rooms",
        json={"name": "اتاق تست ظرفیت", "capacity": 3, "global_seconds": 300},
    )
    room_id = res.json()["room"]["id"]

    # نام‌گذاری سخنران سوم
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    sp3 = detail["speakers"][2]
    client.put(
        f"/api/rooms/{room_id}/speakers/{sp3['id']}",
        json={"name": "دکتر حسینی", "speaking_seconds": 300},
    )

    # تلاش برای کاهش ظرفیت به ۲ بدون تأییدیه صریح -> باید خطای 409 بدهد
    res_shrink = client.put(
        f"/api/rooms/{room_id}",
        json={"name": "اتاق تست ظرفیت", "capacity": 2, "confirm_shrink": False},
    )
    assert res_shrink.status_code == 409
    err = res_shrink.json()["error"]
    assert err["code"] == "CONFIRM_CAPACITY_SHRINK_REQUIRED"
    assert "دکتر حسینی" in err["message"]

    # ارسال با تأیید صریح کاربر -> موفقیت‌آمیز
    res_shrink_ok = client.put(
        f"/api/rooms/{room_id}",
        json={"name": "اتاق تست ظرفیت", "capacity": 2, "confirm_shrink": True},
    )
    assert res_shrink_ok.status_code == 200
    updated = res_shrink_ok.json()["room"]
    assert updated["capacity"] == 2


def test_public_token_and_qr(client: TestClient):
    """بررسی تولید توکن عمومی و کیوآرکد برای تماشاگران."""
    _create_user_and_login(client, "user_qr")

    res = client.post(
        "/api/rooms",
        json={"name": "اتاق پخش عمومی", "capacity": 4, "public_enabled": True},
    )
    room_id = res.json()["room"]["id"]

    # دریافت جزئیات و توکن عمومی
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    assert detail["public_token"] is not None

    # چرخش توکن عمومی (تولید لینک جدید)
    res_rot = client.post(f"/api/rooms/{room_id}/rotate-public-token")
    assert res_rot.status_code == 200
    new_token = res_rot.json()["public_token"]
    assert new_token != detail["public_token"]

    # دریافت تصویر SVG کیوآرکد
    res_qr = client.get(f"/api/rooms/{room_id}/qr")
    assert res_qr.status_code == 200
    assert "image/svg+xml" in res_qr.headers["content-type"]
    assert "<svg" in res_qr.text
