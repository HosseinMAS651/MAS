import os
import re
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="mas-test-"))
os.environ["MAS_ENV"] = "test"
os.environ["MAS_SECRET_KEY"] = "test-secret-key-that-is-long-enough-123456789"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["MAS_STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["MAS_COOKIE_SECURE"] = "0"
os.environ["MAS_MAX_ROOM_STORAGE_MB"] = "20"

from fastapi.testclient import TestClient
from sqlalchemy import select
from mas_app.main import app


def csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "CSRF token missing"
    return m.group(1)


def register_and_complete(client: TestClient, username: str):
    r = client.post("/register", data={"username": username, "password": "secret1234", "password2": "secret1234"})
    assert r.status_code == 200
    token = csrf(r.text)
    r = client.post("/profile", data={"csrf": token, "account_name": "کاربر تست", "age": "20", "job": "دانشجو"})
    assert r.status_code == 200
    assert "خانه" in r.text


def create_room(client: TestClient, name="اتاق تست", capacity=2):
    r = client.get("/rooms/new")
    token = csrf(r.text)
    r = client.post("/rooms/new", data={"csrf": token, "name": name, "capacity": str(capacity)})
    assert r.status_code == 200
    m = re.search(r'/rooms/(\d+)(?:/|")', r.text)
    assert m
    room_id = int(m.group(1))
    page = client.get(f"/rooms/{room_id}")
    assert page.status_code == 200
    return room_id


def room_csrf_and_speaker_ids(client: TestClient, room_id: int):
    r = client.get(f"/rooms/{room_id}")
    assert r.status_code == 200
    ids = [int(x) for x in re.findall(r'name="sid" value="(\d+)"', r.text)]
    assert ids
    return csrf(r.text), ids


def room_form(room_id, speaker_ids, *, name="اتاق تست", recording=False, live_files=False, timing="global", order="manual", names=None):
    names = names or ["علی", "رضا"][:len(speaker_ids)]
    data = {
        "csrf": "",
        "room_name": name,
        "timing_mode": timing,
        "global_min": "5",
        "order_mode": order,
        "manual_order": ",".join(map(str, speaker_ids)),
    }
    if recording:
        data["recording"] = "on"
    if live_files:
        data["live_files"] = "on"
    for i, sid in enumerate(speaker_ids):
        data[f"name_{sid}"] = names[i]
        data[f"gender_{sid}"] = "مرد"
        data[f"age_{sid}"] = str(20 + i)
        data[f"time_{sid}"] = str(5 + i)
        data[f"desc_{sid}"] = f"توضیحات {names[i]}"
    return data


def test_register_profile_and_room_creation():
    with TestClient(app) as client:
        register_and_complete(client, "tester_1")
        room_id = create_room(client, "اتاق تست", 2)
        r = client.get(f"/rooms/{room_id}")
        assert r.status_code == 200
        assert "اتاق تست" in r.text


def test_file_upload_delete_and_download_are_bound_to_exact_file():
    with TestClient(app) as client:
        register_and_complete(client, "files_1")
        room_id = create_room(client, "اتاق فایل", 2)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق فایل")
        data["csrf"] = token
        r = client.post(f"/rooms/{room_id}/save", data=data, files={"common_files": ("slides.pdf", b"%PDF-1.7 test", "application/pdf")})
        assert r.status_code == 200
        r = client.get(f"/rooms/{room_id}")
        assert "slides.pdf" in r.text
        m = re.search(r'/files/(\d+)', r.text)
        assert m
        file_id = int(m.group(1))
        r = client.get(f"/files/{file_id}")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
        r = client.get(f"/files/{file_id}/download")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        token, _ = room_csrf_and_speaker_ids(client, room_id)
        r = client.post(f"/files/{file_id}/delete", data={"csrf": token})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert client.get(f"/files/{file_id}").status_code == 404


def test_timer_keeps_identity_when_manual_order_changes():
    with TestClient(app) as client:
        register_and_complete(client, "timer_1")
        room_id = create_room(client, "اتاق زمان", 2)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق زمان", timing="individual")
        data["csrf"] = token
        data["manual_order"] = ",".join(map(str, speaker_ids))
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        state = client.get(f"/api/rooms/{room_id}/state")
        assert state.status_code == 200
        current_id = state.json()["current_speaker_id"]
        assert current_id == speaker_ids[0]

        token, speaker_ids2 = room_csrf_and_speaker_ids(client, room_id)
        assert speaker_ids2 == speaker_ids
        data["csrf"] = token
        data["manual_order"] = f"{speaker_ids[1]},{speaker_ids[0]}"
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        state = client.get(f"/api/rooms/{room_id}/state").json()
        assert state["current_speaker_id"] == current_id
        assert state["current_index"] == 1


def test_recording_path_works_end_to_end():
    with TestClient(app) as client:
        register_and_complete(client, "rec_1")
        room_id = create_room(client, "اتاق ضبط", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق ضبط", recording=True, live_files=True)
        data["csrf"] = token
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        token, _ = room_csrf_and_speaker_ids(client, room_id)
        r = client.post(
            f"/api/rooms/{room_id}/recording",
            data={"csrf": token, "duration_seconds": "2"},
            files={"file": ("recording.webm", b"WEBMTEST", "audio/webm")},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        r = client.get("/recordings")
        assert r.status_code == 200
        assert "recording.webm" in r.text


def test_live_file_flag_is_exposed_and_frontend_uses_it():
    with TestClient(app) as client:
        register_and_complete(client, "live_1")
        room_id = create_room(client, "اتاق فایل", 1)
        r = client.get(f"/rooms/{room_id}/play")
        assert r.status_code == 200
        compact = re.sub(r"\s+", "", r.text)
        assert '"live_files":false' in compact
    js = Path("mas_app/static/play.js").read_text(encoding="utf-8")
    assert "speakerFilesSection.hidden = !DATA.live_files" in js


def test_xss_payload_is_not_executable_in_page_data():
    with TestClient(app) as client:
        register_and_complete(client, "xss_1")
        room_id = create_room(client, "اتاق XSS", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        sid = speaker_ids[0]
        payload = room_form(room_id, speaker_ids, name="</script><script>alert(1)</script>")
        payload["csrf"] = token
        payload[f"name_{sid}"] = "</script><script>alert(2)</script>"
        payload[f"desc_{sid}"] = "</script><script>alert(3)</script>"
        assert client.post(f"/rooms/{room_id}/save", data=payload).status_code == 200
        r = client.get(f"/rooms/{room_id}/play")
        assert r.status_code == 200
        assert "</script><script>" not in r.text


def test_timer_run_pause_and_overtime_are_server_based():
    import time
    from mas_app.main import app
    from mas_app.models import RoomState, SpeakerTimerState

    with TestClient(app) as client:
        register_and_complete(client, "timer_live_1")
        room_id = create_room(client, "اتاق تایمر", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق تایمر", timing="individual")
        data["csrf"] = token
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        assert client.post(f"/api/rooms/{room_id}/start", data={"csrf": csrf(client.get(f'/rooms/{room_id}').text)}).status_code == 200
        time.sleep(1.1)
        state = client.get(f"/api/rooms/{room_id}/state").json()
        assert state["elapsed_seconds"] >= 1
        token = csrf(client.get(f"/rooms/{room_id}").text)
        assert client.post(f"/api/rooms/{room_id}/pause", data={"csrf": token}).status_code == 200
        paused = client.get(f"/api/rooms/{room_id}/state").json()["elapsed_seconds"]
        time.sleep(1.1)
        paused_again = client.get(f"/api/rooms/{room_id}/state").json()["elapsed_seconds"]
        assert paused_again == paused

        # Force an overtime case in the persisted timer and verify GET calculates it without a browser clock.
        session_factory = app.state.SessionLocal
        with session_factory() as db:
            state_row = db.scalar(select(RoomState).where(RoomState.room_id == room_id))
            timer_row = db.scalar(select(SpeakerTimerState).where(SpeakerTimerState.room_id == room_id, SpeakerTimerState.speaker_id == speaker_ids[0]))
            timer_row.elapsed_seconds = 301
            state_row.current_speaker_id = speaker_ids[0]
            state_row.running = False
            db.commit()
        state = client.get(f"/api/rooms/{room_id}/state").json()
        assert state["overtime_seconds"] >= 1


def test_global_mode_does_not_destroy_individual_times():
    with TestClient(app) as client:
        register_and_complete(client, "timing_modes_1")
        room_id = create_room(client, "اتاق زمان‌بندی", 2)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق زمان‌بندی", timing="individual")
        data["csrf"] = token
        data[f"time_{speaker_ids[0]}"] = "9"
        data[f"time_{speaker_ids[1]}"] = "11"
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        token, _ = room_csrf_and_speaker_ids(client, room_id)
        data["csrf"] = token
        data["timing_mode"] = "global"
        data["global_min"] = "3"
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        token, _ = room_csrf_and_speaker_ids(client, room_id)
        data["csrf"] = token
        data["timing_mode"] = "individual"
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        r = client.get(f"/rooms/{room_id}/play")
        assert '"seconds":540' in re.sub(r"\s+", "", r.text)
        assert '"seconds":660' in re.sub(r"\s+", "", r.text)


def test_cross_user_access_is_denied():
    with TestClient(app) as owner:
        register_and_complete(owner, "owner_1")
        room_id = create_room(owner, "اتاق خصوصی", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(owner, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق خصوصی")
        data["csrf"] = token
        r = owner.post(f"/rooms/{room_id}/save", data=data, files={"common_files": ("private.txt", b"private", "text/plain")})
        assert r.status_code == 200
        page = owner.get(f"/rooms/{room_id}")
        file_id = int(re.search(r'/files/(\d+)', page.text).group(1))

    with TestClient(app) as other:
        register_and_complete(other, "other_1")
        assert other.get(f"/rooms/{room_id}").status_code == 404
        assert other.get(f"/rooms/{room_id}/play").status_code == 404
        assert other.get(f"/files/{file_id}").status_code == 404
        assert other.get(f"/api/rooms/{room_id}/state").status_code == 404


def test_capacity_reduction_removes_speaker_files_and_uses_cleanup_queue():
    from mas_app.models import FileCleanupQueue
    with TestClient(app) as client:
        register_and_complete(client, "capacity_1")
        room_id = create_room(client, "اتاق ظرفیت", 2)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق ظرفیت")
        data["csrf"] = token
        r = client.post(
            f"/rooms/{room_id}/save",
            data=data,
            files={f"file_{speaker_ids[1]}": ("speaker.pdf", b"%PDF-1.7", "application/pdf")},
        )
        assert r.status_code == 200
        page = client.get(f"/rooms/{room_id}")
        m = re.search(r'/files/(\d+)', page.text)
        assert m
        file_id = int(m.group(1))
        token = csrf(page.text)
        r = client.post(f"/rooms/{room_id}/edit", data={"csrf": token, "name": "اتاق ظرفیت", "capacity": "1"})
        assert r.status_code == 200
        assert client.get(f"/files/{file_id}").status_code == 404
        with app.state.SessionLocal() as db:
            assert db.scalar(select(FileCleanupQueue).where(FileCleanupQueue.storage_name.like('%pdf'))) is None


def test_security_headers_and_csrf():
    with TestClient(app) as client:
        r = client.get("/login")
        assert r.status_code == 200
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert "script-src 'self'" in r.headers["content-security-policy"]
        register_and_complete(client, "csrf_1")
        # Missing CSRF must not execute a state change.
        r = client.post("/logout", data={})
        assert r.status_code in {401, 403, 422}
        assert client.get("/").status_code == 200


def test_legacy_database_migration_adds_new_fields_and_binds_current_speaker():
    from sqlalchemy import create_engine, text, select, inspect
    from sqlalchemy.orm import Session
    from mas_app.config import load_settings
    from mas_app.db import configure_sqlite, initialize_database, session_factory
    from mas_app.models import RoomState, Speaker, SpeakerTimerState

    legacy_root = Path(tempfile.mkdtemp(prefix="mas-legacy-"))
    db_path = legacy_root / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    configure_sqlite(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32) UNIQUE NOT NULL, password_hash VARCHAR(256) NOT NULL, account_name VARCHAR(120) DEFAULT '', age INTEGER, job VARCHAR(120) DEFAULT '', created_at INTEGER NOT NULL)")
        conn.exec_driver_sql("CREATE TABLE rooms (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name VARCHAR(160) NOT NULL, capacity INTEGER NOT NULL, recording_enabled BOOLEAN DEFAULT 0, live_files_enabled BOOLEAN DEFAULT 0, timing_mode VARCHAR(20) DEFAULT 'global', global_seconds INTEGER DEFAULT 300, order_mode VARCHAR(20) DEFAULT 'manual', created_at INTEGER NOT NULL)")
        conn.exec_driver_sql("CREATE TABLE speakers (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, name VARCHAR(120) DEFAULT '', gender VARCHAR(20) DEFAULT '', age INTEGER, description TEXT DEFAULT '', speaking_seconds INTEGER DEFAULT 300, order_index INTEGER DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE room_states (id INTEGER PRIMARY KEY, room_id INTEGER UNIQUE NOT NULL, current_index INTEGER DEFAULT 0, elapsed_seconds INTEGER DEFAULT 0, overtime_seconds INTEGER DEFAULT 0, running BOOLEAN DEFAULT 0, started_at INTEGER, updated_at INTEGER)")
        conn.exec_driver_sql("CREATE TABLE auth_sessions (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, token_hash VARCHAR(64) UNIQUE NOT NULL, csrf_token VARCHAR(64) NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)")
        conn.exec_driver_sql("INSERT INTO users(id, username, password_hash, created_at) VALUES(1,'legacy','x',1)")
        conn.exec_driver_sql("INSERT INTO rooms(id, owner_id, name, capacity, created_at) VALUES(1,1,'legacy room',2,1)")
        conn.exec_driver_sql("INSERT INTO speakers(id, room_id, name, order_index, speaking_seconds) VALUES(10,1,'اول',0,300),(11,1,'دوم',1,300)")
        conn.exec_driver_sql("INSERT INTO room_states(id, room_id, current_index, elapsed_seconds, overtime_seconds, running, updated_at) VALUES(1,1,1,120,0,0,1)")

    initialize_database(engine)
    cols = {c['name'] for c in inspect(engine).get_columns('room_states')}
    assert 'current_speaker_id' in cols and 'version' in cols
    cols = {c['name'] for c in inspect(engine).get_columns('rooms')}
    assert 'storage_used_bytes' in cols and 'version' in cols
    cols = {c['name'] for c in inspect(engine).get_columns('auth_sessions')}
    assert 'last_seen_at' in cols
    SessionLocal = session_factory(engine)
    with SessionLocal() as db:
        state = db.scalar(select(RoomState).where(RoomState.room_id == 1))
        assert state.current_speaker_id == 11
        timer = db.scalar(select(SpeakerTimerState).where(SpeakerTimerState.room_id == 1, SpeakerTimerState.speaker_id == 11))
        assert timer is not None and timer.elapsed_seconds == 120
    engine.dispose()


def test_capacity_100_speakers_saves_without_form_limit_failure():
    with TestClient(app) as client:
        register_and_complete(client, "capacity_100")
        room_id = create_room(client, "اتاق صد نفره", 100)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        names = [f"سخنران {i+1}" for i in range(100)]
        data = room_form(room_id, speaker_ids, name="اتاق صد نفره", timing="individual", names=names)
        data["csrf"] = token
        data["manual_order"] = ",".join(map(str, speaker_ids))
        r = client.post(f"/rooms/{room_id}/save", data=data)
        assert r.status_code == 200
        r = client.get(f"/rooms/{room_id}/play")
        assert r.status_code == 200
        import json
        m = re.search(r'<script type="application/json" id="play-data">(.*?)</script>', r.text, re.S)
        assert m
        payload = json.loads(m.group(1))
        assert len(payload["speakers"]) == 100
        assert payload["speakers"][-1]["name"] == "سخنران 100"


def test_storage_quota_is_tracked_and_released():
    from mas_app.models import Room, SpeechFile
    with TestClient(app) as client:
        register_and_complete(client, "quota_1")
        room_id = create_room(client, "اتاق سهمیه", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق سهمیه")
        data["csrf"] = token
        payload = b"%PDF-1.7 quota-test"
        r = client.post(f"/rooms/{room_id}/save", data=data, files={"common_files": ("q.pdf", payload, "application/pdf")})
        assert r.status_code == 200
        with app.state.SessionLocal() as db:
            room = db.get(Room, room_id)
            file_obj = db.scalar(select(SpeechFile).where(SpeechFile.room_id == room_id))
            assert file_obj is not None
            assert room.storage_used_bytes == len(payload)
            stored_name = file_obj.storage_name
        stored_path = app.state.settings.storage_dir / stored_name
        assert stored_path.exists()
        token, _ = room_csrf_and_speaker_ids(client, room_id)
        r = client.post(f"/files/{file_obj.id}/delete", data={"csrf": token})
        assert r.status_code == 200
        assert not stored_path.exists()
        with app.state.SessionLocal() as db:
            room = db.get(Room, room_id)
            assert room.storage_used_bytes == 0


def test_empty_room_state_get_does_not_create_database_state_row():
    from mas_app.models import RoomState
    with TestClient(app) as client:
        register_and_complete(client, "empty_state")
        room_id = create_room(client, "اتاق خالی", 2)
        with app.state.SessionLocal() as db:
            before = db.scalar(select(RoomState).where(RoomState.room_id == room_id))
            assert before is not None
            before_id, before_version = before.id, before.version
        r = client.get(f"/api/rooms/{room_id}/state")
        assert r.status_code == 200
        assert r.json()["current_speaker_id"] is None
        with app.state.SessionLocal() as db:
            after = db.scalar(select(RoomState).where(RoomState.room_id == room_id))
            assert after is not None
            assert after.id == before_id and after.version == before_version


def test_invalid_global_time_is_a_controlled_400():
    with TestClient(app) as client:
        register_and_complete(client, "invalid_global")
        room_id = create_room(client, "اتاق خطا", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق خطا")
        data["csrf"] = token
        data["global_min"] = "abc"
        r = client.post(f"/rooms/{room_id}/save", data=data)
        assert r.status_code == 400


def test_disallowed_recording_type_leaves_no_database_or_physical_file():
    from mas_app.models import SpeechFile
    with TestClient(app) as client:
        register_and_complete(client, "bad_recording")
        room_id = create_room(client, "اتاق ضبط بد", 1)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق ضبط بد", recording=True)
        data["csrf"] = token
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        token, _ = room_csrf_and_speaker_ids(client, room_id)
        r = client.post(
            f"/api/rooms/{room_id}/recording",
            data={"csrf": token, "duration_seconds": "1"},
            files={"file": ("evil.exe", b"not-audio", "application/octet-stream")},
        )
        assert r.status_code == 400
        with app.state.SessionLocal() as db:
            assert db.scalar(select(SpeechFile).where(SpeechFile.room_id == room_id, SpeechFile.upload_type == "recording")) is None


def test_room_optimistic_lock_rejects_concurrent_stale_save():
    from sqlalchemy import select
    from sqlalchemy.orm.exc import StaleDataError
    from mas_app.models import Room
    with TestClient(app) as client:
        register_and_complete(client, "room_lock_1")
        room_id = create_room(client, "اتاق قفل", 1)
        SessionLocal = app.state.SessionLocal
        db1, db2 = SessionLocal(), SessionLocal()
        try:
            r1 = db1.scalar(select(Room).where(Room.id == room_id))
            r2 = db2.scalar(select(Room).where(Room.id == room_id))
            r1.name = "تغییر اول"
            r2.name = "تغییر دوم"
            db1.commit()
            try:
                db2.commit()
            except StaleDataError:
                db2.rollback()
            else:
                raise AssertionError("stale Room update unexpectedly committed")
        finally:
            db1.close()
            db2.close()


def test_two_timer_clients_serialize_next_actions_without_lost_state():
    from sqlalchemy import select
    from mas_app.models import Room, RoomState
    from mas_app.services import apply_timer_action
    with TestClient(app) as client:
        register_and_complete(client, "timer_lock_1")
        room_id = create_room(client, "اتاق تایمر همزمان", 3)
        token, speaker_ids = room_csrf_and_speaker_ids(client, room_id)
        data = room_form(room_id, speaker_ids, name="اتاق تایمر همزمان", names=["علی", "رضا", "حسین"])
        data["csrf"] = token
        assert client.post(f"/rooms/{room_id}/save", data=data).status_code == 200
        SessionLocal = app.state.SessionLocal
        db1, db2 = SessionLocal(), SessionLocal()
        try:
            room1 = db1.scalar(select(Room).where(Room.id == room_id))
            room2 = db2.scalar(select(Room).where(Room.id == room_id))
            apply_timer_action(db1, room1, "next")
            apply_timer_action(db2, room2, "next")
            with SessionLocal() as verify:
                room_state = verify.scalar(select(RoomState).where(RoomState.room_id == room_id))
                assert room_state.current_speaker_id == speaker_ids[2]
        finally:
            db1.close()
            db2.close()


def test_static_css_and_javascript_are_served():
    with TestClient(app) as client:
        for path, marker in [
            ("/static/app.css", b"body"),
            ("/static/play.js", b"MediaRecorder"),
            ("/static/room_editor.js", b"speaker-list"),
            ("/static/files.js", b"delete-file"),
        ]:
            r = client.get(path)
            assert r.status_code == 200, path
            assert marker in r.content, path
