"""تست‌های مدیریت سخنران‌ها و رفع باگ‌های بحرانی C-01 و C-05."""

from fastapi.testclient import TestClient


def _setup_room(client: TestClient, username: str = "sp_user"):
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "password1234"},
    )
    res = client.post(
        "/api/rooms",
        json={"name": "اتاق سخنرانان", "capacity": 3, "global_seconds": 300},
    )
    return res.json()["room"]["id"]


def test_delete_speaker_empty_slot_collision_c01(client: TestClient):
    """بررسی رفع باگ C-01: حذف سخنران وقتی اسلات خالی قبل از آن وجود دارد (بدون خطای ۵۰۰ یونیک)."""
    room_id = _setup_room(client, "user_c01")

    # دریافت ۳ اسلات اولیه
    room_data = client.get(f"/api/rooms/{room_id}").json()["room"]
    sp1 = room_data["speakers"][1]
    sp2 = room_data["speakers"][2]

    # اسلات اول را خالی می‌گذاریم؛ اسلات دوم و سوم را نام‌گذاری می‌کنیم
    # وضعیت: [(0, ''), (1, 'آقای ب'), (2, 'آقای پ')]
    client.put(
        f"/api/rooms/{room_id}/speakers/{sp1['id']}",
        json={"name": "آقای ب", "speaking_seconds": 300},
    )
    client.put(
        f"/api/rooms/{room_id}/speakers/{sp2['id']}",
        json={"name": "آقای پ", "speaking_seconds": 300},
    )

    # حذف اسلات دوم ('آقای ب')
    # در نسخهٔ قدیم این کار منجر به خطای IntegrityError و HTTP 500 می‌شد
    res_del = client.delete(f"/api/rooms/{room_id}/speakers/{sp1['id']}")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True

    # بررسی شماره‌گذاری مجدد ترتیبی
    updated_room = client.get(f"/api/rooms/{room_id}").json()["room"]
    remaining = updated_room["speakers"]
    assert len(remaining) == 2
    assert remaining[0]["order_index"] == 0
    assert remaining[1]["order_index"] == 1
    assert remaining[1]["name"] == "آقای پ"


def test_unfreeze_and_reset_all_c05(client: TestClient):
    """بررسی رفع باگ C-05: امکان خروج سخنران از فریز و بازنشانی کلیه سخنرانان."""
    room_id = _setup_room(client, "user_c05")

    room_data = client.get(f"/api/rooms/{room_id}").json()["room"]
    sp0 = room_data["speakers"][0]

    # شروع و اتمام سخنران اول (فریز شدن)
    client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})
    client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "finish"})

    # بررسی فریز بودن
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    assert detail["speakers"][0]["is_finished"] is True

    # خروج از فریز
    res_unfreeze = client.post(f"/api/rooms/{room_id}/speakers/{sp0['id']}/unfreeze")
    assert res_unfreeze.status_code == 200
    assert res_unfreeze.json()["speaker"]["is_finished"] is False

    # بازنشانی همه
    res_reset_all = client.post(f"/api/rooms/{room_id}/reset-all")
    assert res_reset_all.status_code == 200
    assert res_reset_all.json()["ok"] is True
