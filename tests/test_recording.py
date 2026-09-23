"""تست‌های جامع ضبط خودکار صدا، آپلود تکه‌ای و نام‌گذاری استاندارد (خواستهٔ اصلی کاربر)."""

import io

from fastapi.testclient import TestClient


def _setup_recording_room(client: TestClient, username: str = "rec_user"):
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "password1234"},
    )
    # ساخت اتاق با ضبط فعال
    res = client.post(
        "/api/rooms",
        json={
            "name": "جلسه هیئت مدیره",
            "capacity": 2,
            "recording_enabled": True,
            "global_seconds": 60,
        },
    )
    room_id = res.json()["room"]["id"]

    # نام‌گذاری سخنران اول
    detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    sp0 = detail["speakers"][0]
    client.put(
        f"/api/rooms/{room_id}/speakers/{sp0['id']}",
        json={"name": "مهندس کمالی", "speaking_seconds": 60},
    )
    return room_id, sp0["id"]


def test_automatic_recording_lifecycle(client: TestClient):
    """بررسی چرخهٔ حیات ضبط خودکار همگام با تایمر و ذخیره در اتمام سخنرانی."""
    room_id, speaker_id = _setup_recording_room(client, "user_auto_rec")

    # ۱. شروع تایمر -> ایجاد خودکار نشست ضبط در وضعیت recording
    res_start = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})
    assert res_start.status_code == 200

    rec_status = client.get(f"/api/rooms/{room_id}/recording/status").json()
    assert rec_status["active"] is True
    session_id = rec_status["session"]["session_id"]
    assert rec_status["session"]["status"] == "recording"
    assert rec_status["session"]["speaker_name"] == "مهندس کمالی"

    # ۲. ارسال دو تکهٔ صوتی
    chunk1 = b"fake-audio-chunk-1-webm-header"
    chunk2 = b"fake-audio-chunk-2-audio-data"

    res_c1 = client.post(
        f"/api/rooms/{room_id}/recording/chunk",
        data={"session_id": session_id, "seq": 0},
        files={"chunk": ("chunk_0.bin", io.BytesIO(chunk1), "application/octet-stream")},
    )
    assert res_c1.status_code == 200

    res_c2 = client.post(
        f"/api/rooms/{room_id}/recording/chunk",
        data={"session_id": session_id, "seq": 1},
        files={"chunk": ("chunk_1.bin", io.BytesIO(chunk2), "application/octet-stream")},
    )
    assert res_c2.status_code == 200

    # ۳. توقف تایمر (Pause) -> وضعیت ضبط باید paused شود
    client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "pause"})
    rec_status_pause = client.get(f"/api/rooms/{room_id}/recording/status").json()
    assert rec_status_pause["session"]["status"] == "paused"

    # ۴. اتمام سخنرانی (Finish) -> مونتاژ و ذخیرهٔ خودکار ضبط در آرشیو
    res_finish = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "finish"})
    assert res_finish.status_code == 200

    # بررسی وجود فایل در آرشیو ضبط‌ها با فرمت نام استاندارد: "نام اتاق - نام سخنران"
    room_detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    recordings = room_detail["recordings"]
    assert len(recordings) == 1
    rec_file = recordings[0]

    # شرط کاربر: نام فایل با اسم سخنران و اتاق
    assert "جلسه هیئت مدیره" in rec_file["filename"]
    assert "مهندس کمالی" in rec_file["filename"]
    assert rec_file["size_bytes"] == len(chunk1) + len(chunk2)


def test_delete_speaker_recording_prompt(client: TestClient):
    """بررسی شرط کاربر:

    با زدن دکمه حذف سخنران در صورت فعال بودن ضبط و انجام مدتی از ضبط،
    از کاربر پرسیده شود که فایل ذخیره شود یا خیر.
    """
    room_id, speaker_id = _setup_recording_room(client, "user_del_prompt")

    # شروع تایمر و ارسال تکه ضبط
    client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})
    status = client.get(f"/api/rooms/{room_id}/recording/status").json()
    session_id = status["session"]["session_id"]

    client.post(
        f"/api/rooms/{room_id}/recording/chunk",
        data={"session_id": session_id, "seq": 0},
        files={"chunk": ("chunk_1.bin", io.BytesIO(b"audio-data"), "application/octet-stream")},
    )

    # تلاش برای حذف سخنران بدون مشخص کردن تکلیف ضبط
    res_del_no_prompt = client.delete(f"/api/rooms/{room_id}/speakers/{speaker_id}")
    assert res_del_no_prompt.status_code == 409
    err = res_del_no_prompt.json()["error"]
    assert err["code"] == "RECORDING_ACTIVE_PROMPT_REQUIRED"

    # حذف سخنران با انتخاب ذخیرهٔ فایل (save_recording=true)
    res_del_save = client.delete(f"/api/rooms/{room_id}/speakers/{speaker_id}?save_recording=true")
    assert res_del_save.status_code == 200

    # بررسی اینکه فایل ضبط‌شده حتی پس از حذف سخنران باقی مانده است
    room_detail = client.get(f"/api/rooms/{room_id}").json()["room"]
    assert len(room_detail["recordings"]) == 1
    assert "مهندس کمالی" in room_detail["recordings"][0]["filename"]
