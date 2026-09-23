"""تست‌های تایمر اتاق پخش و شرط توقف خودکار با پایان یافتن زمان (درخواست کاربر)."""

from fastapi.testclient import TestClient


def _setup_timer_room(client: TestClient, username: str = "timer_user"):
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "password1234"},
    )
    res = client.post(
        "/api/rooms",
        json={"name": "اتاق تایمر", "capacity": 2, "global_seconds": 10},
    )
    room_id = res.json()["room"]["id"]

    # نام‌گذاری سخنران
    room_data = client.get(f"/api/rooms/{room_id}").json()["room"]
    sp0 = room_data["speakers"][0]
    client.put(
        f"/api/rooms/{room_id}/speakers/{sp0['id']}",
        json={"name": "سخنران تستی", "speaking_seconds": 10},
    )
    return room_id


def test_timer_basic_actions(client: TestClient):
    room_id = _setup_timer_room(client, "user_timer_basic")

    # شروع تایمر
    res_start = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})
    assert res_start.status_code == 200
    assert res_start.json()["state"]["running"] is True

    # توقف موقت (Pause)
    res_pause = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "pause"})
    assert res_pause.status_code == 200
    assert res_pause.json()["state"]["running"] is False

    # از سرگیری (Resume)
    res_resume = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "resume"})
    assert res_resume.status_code == 200
    assert res_resume.json()["state"]["running"] is True


def test_timer_automatic_stop_on_time_up_and_overtime(client: TestClient, db_session):
    """بررسی شرط کاربر:

    با اتمام زمان هر سخنران در اتاق پخش و زمانی که اعلان اتمام تایم می‌آید،
    تایمر متوقف شود و فقط در صورت انتخاب گزینه ادامه سخنرانی زمان اضافه محاسبه شود.
    """
    from mas_app.core.timeutil import utc_now_ms
    from mas_app.db.models import RoomState

    room_id = _setup_timer_room(client, "user_timer_stop")

    # شروع تایمر با زمان مجاز ۱۰ ثانیه (10000ms)
    client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})

    # شبیه‌سازی سپری شدن بیش از ۱۰ ثانیه (مثلاً ۱۵ ثانیه)
    state = db_session.query(RoomState).filter_by(room_id=room_id).first()
    state.started_at_ms = utc_now_ms() - 15000  # ۱۵ ثانیه قبل شروع شده
    db_session.commit()

    # دریافت وضعیت تایمر: باید توقف خودکار رخ داده باشد
    res_poll = client.get(f"/api/rooms/{room_id}/timer/state")
    assert res_poll.status_code == 200
    state_data = res_poll.json()["state"]

    # شرط ۱: تایمر متوقف شده است
    assert state_data["running"] is False
    # شرط ۲: در انتظار تصمیم کاربر است (اعلان اتمام وقت)
    assert state_data["awaiting_decision"] is True
    assert state_data["elapsed_ms"] == 10000  # زمان اصلی پر شده
    assert state_data["overtime_ms"] == 0  # هنوز زمان اضافه محاسبه نشده

    # شرط ۳: کاربر گزینه «ادامه سخنرانی» را انتخاب می‌کند
    res_cont = client.post(
        f"/api/rooms/{room_id}/timer/action", json={"action": "continue_overtime"}
    )
    assert res_cont.status_code == 200
    cont_state = res_cont.json()["state"]
    assert cont_state["running"] is True
    assert cont_state["awaiting_decision"] is True
