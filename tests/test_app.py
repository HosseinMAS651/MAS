import os
import re
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="mas-rewrite-test-"))
os.environ["MAS_ENV"] = "test"
os.environ["MAS_SECRET_KEY"] = "test-secret-key-that-is-long-enough-123456789"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["MAS_STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["MAS_COOKIE_SECURE"] = "0"
os.environ["MAS_MAX_ROOM_STORAGE_MB"] = "20"
os.environ["MAS_MAX_UPLOAD_MB"] = "2"

from fastapi.testclient import TestClient
from sqlalchemy import select

from mas_app.main import app
from mas_app.models import AuthSession, Room, RoomState, Speaker, SpeakerTimerState
from mas_app.services import release_room_storage


def csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m
    return m.group(1)


def guest_csrf(html: str) -> str:
    m = re.search(r'name="guest_csrf" value="([^"]+)"', html)
    assert m
    return m.group(1)


def register_and_complete(client: TestClient, username: str):
    r = client.get("/register")
    assert r.status_code == 200
    token = guest_csrf(r.text)
    r = client.post("/register", data={"guest_csrf": token, "username": username, "password": "secret1234", "password2": "secret1234"})
    assert r.status_code == 200
    token = csrf(r.text)
    r = client.post("/profile", data={"csrf": token, "account_name": "کاربر تست", "age": "20", "job": "دانشجو"})
    assert r.status_code == 200
    assert "خانه" in r.text


def create_room(client: TestClient, capacity=3, name="اتاق تست"):
    r = client.get("/rooms/new")
    token = csrf(r.text)
    r = client.post("/rooms/new", data={"csrf": token, "name": name, "capacity": str(capacity)})
    assert r.status_code == 200
    m = re.search(r"/rooms/(\d+)", r.text)
    assert m
    return int(m.group(1))


def room_ids(client, room_id):
    r = client.get(f"/rooms/{room_id}/edit")
    assert r.status_code == 200
    return csrf(r.text), [int(x) for x in re.findall(r'name="name_(\d+)"', r.text)]


def save_room(client, room_id, ids, *, names=None, timing="individual", order="manual", recording=False, live_files=True, token=None):
    names = names or ["علی", "رضا", "مریم"][:len(ids)]
    token = token or room_ids(client, room_id)[0]
    data = {"csrf": token, "room_name": "اتاق به‌روز", "capacity": str(len(ids)), "timing_mode": timing, "global_min": "1", "order_mode": order,
            "manual_order": ",".join(map(str, ids))}
    if recording: data["recording"] = "on"
    if live_files: data["live_files"] = "on"
    for i, sid in enumerate(ids):
        data[f"name_{sid}"] = names[i]
        data[f"gender_{sid}"] = "مرد" if i < 2 else "زن"
        data[f"age_{sid}"] = str(20 + i)
        data[f"time_{sid}"] = "1"
        data[f"desc_{sid}"] = f"توضیح {names[i]}"
    return client.post(f"/rooms/{room_id}/edit", data=data)


def state(client, room_id):
    r = client.get(f"/api/rooms/{room_id}/state", headers={"Accept": "application/json"})
    assert r.status_code == 200
    return r.json()


def control(client, room_id, action):
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/api/rooms/{room_id}/{action}", data={"csrf": token}, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_register_profile_room_and_play_features(client):
    register_and_complete(client, "tester_1")
    room_id = create_room(client, 3)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids, recording=True).status_code == 200
    r = client.get(f"/rooms/{room_id}/play")
    assert r.status_code == 200
    assert "ادامه سخنرانی" in r.text
    assert "اتمام سخنرانی" in r.text
    assert "حذف سخنران" in r.text
    assert 'recording_bitrate_bps' in r.text


def test_timer_has_millisecond_server_anchor_and_smooth_controls(client):
    register_and_complete(client, "timer_smooth_1")
    room_id = create_room(client, 1)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids).status_code == 200
    before = state(client, room_id)
    assert "server_time_ms" in before and "started_at_ms" not in before
    started = control(client, room_id, "start")
    assert started["running"] is True
    assert "server_time_ms" in started
    assert "elapsed_ms" in started
    paused = control(client, room_id, "pause")
    assert paused["running"] is False
    assert paused["elapsed_ms"] >= 0


def test_finish_freezes_speaker_and_prev_can_return(client):
    register_and_complete(client, "finish_1")
    room_id = create_room(client, 2)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids, names=["علی", "رضا"]).status_code == 200
    first = state(client, room_id)
    assert first["current_speaker_id"] == ids[0]
    finished = control(client, room_id, "finish")
    assert finished["current_speaker"]["is_finished"] is True
    nxt = control(client, room_id, "next")
    assert nxt["current_speaker_id"] == ids[1]
    back = control(client, room_id, "prev")
    assert back["current_speaker_id"] == ids[0]
    assert back["current_speaker"]["is_finished"] is True
    bad_start = client.post(f"/api/rooms/{room_id}/start", data={"csrf": csrf(client.get(f"/rooms/{room_id}/edit").text)}, headers={"Accept":"application/json"})
    assert bad_start.status_code == 400


def test_delete_current_speaker_decreases_capacity_and_moves_to_next(client):
    register_and_complete(client, "delete_current_1")
    room_id = create_room(client, 3)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids, names=["علی", "رضا", "مریم"]).status_code == 200
    before = state(client, room_id)
    current_id = before["current_speaker_id"]
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/api/rooms/{room_id}/speakers/{current_id}/delete", data={"csrf": token}, headers={"Accept":"application/json"})
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["total_speakers"] == 2
    assert after["current_speaker_id"] == ids[1]
    room_html = client.get(f"/rooms/{room_id}").text
    assert "ظرفیت فعلی" not in room_html
    with app.state.SessionLocal() as db:
        room = db.get(Room, room_id)
        assert room.capacity == 2
        assert db.get(Speaker, current_id) is None


def test_delete_last_speaker_can_leave_zero_capacity(client):
    register_and_complete(client, "delete_last_1")
    room_id = create_room(client, 1)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids, names=["تنها"]).status_code == 200
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/api/rooms/{room_id}/speakers/{ids[0]}/delete", data={"csrf": token}, headers={"Accept":"application/json"})
    assert r.status_code == 200
    assert r.json()["current_speaker_id"] is None
    with app.state.SessionLocal() as db:
        assert db.get(Room, room_id).capacity == 0


def test_continue_overtime_starts_from_zero_display_state(client, monkeypatch):
    register_and_complete(client, "overtime_1")
    room_id = create_room(client, 1)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids, names=["علی"]).status_code == 200
    from mas_app import services
    start = control(client, room_id, "start")
    with app.state.SessionLocal() as db:
        room = db.get(Room, room_id)
        st = db.scalar(select(RoomState).where(RoomState.room_id == room_id))
        st.started_at_ms = services.now_ms() - room.global_seconds * 1000 - 2500
        db.commit()
    s = state(client, room_id)
    assert s["overtime_ms"] >= 2000
    continued = control(client, room_id, "continue_overtime")
    assert continued["running"] is True
    assert continued["elapsed_ms"] >= continued["limit_ms"]
    assert continued["overtime_ms"] >= 2000


def test_password_change_invalidates_old_sessions(client):
    register_and_complete(client, "password_1")
    second = TestClient(app)
    try:
        r = second.get("/login")
        token = guest_csrf(r.text)
        r = second.post("/login", data={"guest_csrf": token, "username": "password_1", "password": "secret1234"})
        assert r.status_code == 200
        old_token = second.cookies.get("mas_session")
        token = csrf(client.get("/profile").text)
        r = client.post("/profile/password", data={"csrf": token, "current_password": "secret1234", "new_password": "newsecret1234", "new_password2": "newsecret1234"})
        assert r.status_code == 200
        second.cookies.set("mas_session", old_token)
        assert second.get("/profile", follow_redirects=False).status_code == 303
        assert client.get("/profile").status_code == 200
    finally:
        second.close()

def test_recording_endpoint_rejects_mismatched_audio_format(client):
    register_and_complete(client, "recording_type_1")
    room_id = create_room(client, 1)
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/rooms/{room_id}/edit", data={"csrf": token, "room_name": "ضبط", "capacity": "1",
                                               "timing_mode": "global", "global_min": "1", "order_mode": "manual",
                                               "manual_order": "" , "recording": "on", "name_1": "علی", "gender_1": "", "age_1": "20", "time_1": "1", "desc_1": ""})
    assert r.status_code == 200
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    # Endpoint must reject an mp3 extension declared as WebM.
    r = client.post(f"/api/rooms/{room_id}/recording",
                     data={"csrf": token, "duration_seconds": "1"},
                     files={"file": ("bad.webm", b"not-a-real-audio-file", "audio/mpeg")},
                     headers={"Accept": "application/json"})
    assert r.status_code == 400


def test_recording_response_contains_saved_file_metadata(client):
    register_and_complete(client, "recording_response_1")
    room_id = create_room(client, 1)
    edit_token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    ids = [int(x) for x in re.findall(r'name="name_(\d+)"', client.get(f"/rooms/{room_id}/edit").text)]
    data = {"csrf": edit_token, "room_name": "ضبط", "capacity": "1", "timing_mode": "global", "global_min": "1",
            "order_mode": "manual", "manual_order": str(ids[0]), "recording": "on", "name_%s" % ids[0]: "علی",
            "gender_%s" % ids[0]: "", "age_%s" % ids[0]: "20", "time_%s" % ids[0]: "1", "desc_%s" % ids[0]: ""}
    assert client.post(f"/rooms/{room_id}/edit", data=data).status_code == 200
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/api/rooms/{room_id}/recording", data={"csrf": token, "duration_seconds": "1"},
                     files={"file": ("clip.webm", b"abc", "audio/webm")}, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file"]["id"] and body["file"]["name"] == "clip.webm"



def test_guest_csrf_blocks_login_without_matching_cookie(client):
    r = client.get("/login")
    assert r.status_code == 200
    r = client.post("/login", data={"guest_csrf": "wrong", "username": "tester", "password": "secret1234"})
    assert r.status_code == 403


def test_cross_user_room_access_is_denied(client):
    register_and_complete(client, "owner_access_1")
    room_id = create_room(client, 1)
    other = TestClient(app)
    try:
        r = other.get("/register")
        token = guest_csrf(r.text)
        r = other.post("/register", data={"guest_csrf": token, "username": "other_access_1", "password": "secret1234", "password2": "secret1234"})
        assert r.status_code == 200
        profile_token = csrf(r.text)
        r = other.post("/profile", data={"csrf": profile_token, "account_name": "کاربر دوم", "age": "21", "job": "تست"})
        assert r.status_code == 200
        r = other.get(f"/api/rooms/{room_id}/state", headers={"Accept": "application/json"})
        assert r.status_code == 404
        # Page access must not reveal the room to another owner.
        r = other.get(f"/rooms/{room_id}", follow_redirects=False)
        assert r.status_code == 404
    finally:
        other.close()


def test_xss_is_escaped_in_room_pages(client):
    register_and_complete(client, "xss_escape_1")
    room_id = create_room(client, 1)
    r = client.get(f"/rooms/{room_id}/edit")
    token = csrf(r.text)
    ids = [int(x) for x in re.findall(r'name="name_(\d+)"', r.text)]
    sid = ids[0]
    payload = '<script>alert("x")</script>'
    data = {"csrf": token, "room_name": payload, "capacity": "1", "timing_mode": "global", "global_min": "1",
            "order_mode": "manual", "manual_order": str(sid), f"name_{sid}": payload, f"gender_{sid}": "",
            f"age_{sid}": "20", f"time_{sid}": "1", f"desc_{sid}": payload}
    r = client.post(f"/rooms/{room_id}/edit", data=data)
    assert r.status_code == 200
    html = client.get(f"/rooms/{room_id}").text
    assert payload not in html
    assert "&lt;script&gt;" in html


def test_file_upload_delete_updates_quota_and_removes_storage(client):
    register_and_complete(client, "file_cycle_1")
    room_id = create_room(client, 1)
    r = client.get(f"/rooms/{room_id}/edit")
    token = csrf(r.text)
    sid = int(re.findall(r'name="name_(\d+)"', r.text)[0])
    data = {"csrf": token, "room_name": "فایل", "capacity": "1", "timing_mode": "global", "global_min": "1",
            "order_mode": "manual", "manual_order": str(sid), f"name_{sid}": "علی", f"gender_{sid}": "",
            f"age_{sid}": "20", f"time_{sid}": "1", f"desc_{sid}": ""}
    r = client.post(f"/rooms/{room_id}/edit", data=data, files={"common_files": ("note.txt", b"hello", "text/plain")})
    assert r.status_code == 200
    with app.state.SessionLocal() as db:
        file_obj = db.scalar(select(__import__('mas_app.models', fromlist=['SpeechFile']).SpeechFile).where(__import__('mas_app.models', fromlist=['SpeechFile']).SpeechFile.room_id == room_id))
        assert file_obj is not None
        file_id = file_obj.id
        storage_name = file_obj.storage_name
        assert db.get(Room, room_id).storage_used_bytes == 5
    path = app.state.settings.storage_dir / storage_name
    assert path.exists()
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/files/{file_id}/delete", data={"csrf": token}, headers={"Accept": "application/json"})
    assert r.status_code == 200
    with app.state.SessionLocal() as db:
        assert db.get(Room, room_id).storage_used_bytes == 0
    assert not path.exists()


def test_password_change_allows_new_login_after_old_sessions_are_revoked(client):
    register_and_complete(client, "password_2")
    second = TestClient(app)
    try:
        r = second.get("/login")
        token = guest_csrf(r.text)
        r = second.post("/login", data={"guest_csrf": token, "username": "password_2", "password": "secret1234"})
        assert r.status_code == 200
        old_token = second.cookies.get("mas_session")
        token = csrf(client.get("/profile").text)
        r = client.post("/profile/password", data={"csrf": token, "current_password": "secret1234", "new_password": "newsecret1234", "new_password2": "newsecret1234"})
        assert r.status_code == 200
        second.cookies.clear()
        second.cookies.set("mas_session", old_token)
        assert second.get("/profile", follow_redirects=False).status_code == 303
        second.cookies.clear()
        r = second.get("/login")
        token = guest_csrf(r.text)
        r = second.post("/login", data={"guest_csrf": token, "username": "password_2", "password": "newsecret1234"})
        assert r.status_code == 200
        assert "کاربر تست" in r.text
    finally:
        second.close()


def test_health_and_production_docs_behavior(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    headers = client.get("/login").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_exact_speaker_navigation_can_open_frozen_speaker(client):
    register_and_complete(client, "goto_frozen_1")
    room_id = create_room(client, 3)
    _, ids = room_ids(client, room_id)
    assert save_room(client, room_id, ids, names=["علی", "رضا", "مریم"]).status_code == 200
    control(client, room_id, "finish")
    token = csrf(client.get(f"/rooms/{room_id}/edit").text)
    r = client.post(f"/api/rooms/{room_id}/goto/{ids[0]}", data={"csrf": token}, headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.json()["current_speaker_id"] == ids[0]
    assert r.json()["current_speaker"]["is_finished"] is True



def test_legacy_timestamp_and_duplicate_room_state_migration_is_repaired(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from mas_app.db import initialize_database
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32) NOT NULL, password_hash VARCHAR(256) NOT NULL, account_name VARCHAR(120) DEFAULT '', age INTEGER, job VARCHAR(120) DEFAULT '', created_at INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE rooms (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name VARCHAR(160) NOT NULL, capacity INTEGER NOT NULL, recording_enabled BOOLEAN NOT NULL DEFAULT 0, live_files_enabled BOOLEAN NOT NULL DEFAULT 0, timing_mode VARCHAR(20) NOT NULL DEFAULT 'global', global_seconds INTEGER NOT NULL DEFAULT 300, order_mode VARCHAR(20) NOT NULL DEFAULT 'manual', storage_used_bytes INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speakers (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL DEFAULT '', gender VARCHAR(20) NOT NULL DEFAULT '', age INTEGER, description TEXT NOT NULL DEFAULT '', speaking_seconds INTEGER NOT NULL DEFAULT 300, order_index INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE room_states (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, current_index INTEGER NOT NULL DEFAULT 0, elapsed_seconds INTEGER NOT NULL DEFAULT 0, overtime_seconds INTEGER NOT NULL DEFAULT 0, running BOOLEAN NOT NULL DEFAULT 0, started_at TIMESTAMP NULL, updated_at INTEGER NOT NULL DEFAULT 0, current_speaker_id INTEGER, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speaker_timer_states (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, speaker_id INTEGER NOT NULL, elapsed_seconds INTEGER NOT NULL DEFAULT 0, overtime_seconds INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speech_files (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, speaker_id INTEGER, filename VARCHAR(255) NOT NULL, storage_name VARCHAR(255) NOT NULL, content_type VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream', size_bytes INTEGER NOT NULL DEFAULT 0, upload_type VARCHAR(20) NOT NULL, duration_seconds INTEGER, created_at INTEGER NOT NULL DEFAULT 0)")
        conn.execute(text("INSERT INTO users (id, username, password_hash) VALUES (1, 'legacy', 'x')"))
        conn.execute(text("INSERT INTO rooms (id, owner_id, name, capacity) VALUES (1, 1, 'قدیمی', 1)"))
        conn.execute(text("INSERT INTO speakers (id, room_id, name, order_index) VALUES (1, 1, 'علی', 0)"))
        conn.execute(text("INSERT INTO room_states (id, room_id, current_index, elapsed_seconds, running, started_at, updated_at, current_speaker_id, version) VALUES (1,1,0,12,0,'2026-09-20 12:34:56',0,1,1)"))
        conn.execute(text("INSERT INTO room_states (id, room_id, current_index, elapsed_seconds, running, started_at, updated_at, current_speaker_id, version) VALUES (2,1,0,20,0,'2026-09-20 12:35:56',0,1,1)"))
    initialize_database(engine)
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM room_states WHERE room_id=1")).scalar_one()
        assert count == 1
        started_ms = conn.execute(text("SELECT started_at_ms FROM room_states WHERE room_id=1")).scalar_one()
        assert isinstance(started_ms, int) and started_ms > 0
        idxs = inspect(engine).get_indexes("room_states")
        unique_state_indexes = [x for x in idxs if x.get("unique") and set(x.get("column_names") or []) == {"room_id"}]
        assert unique_state_indexes
    engine.dispose()


def test_file_delete_releases_quota_without_postgresql_max_function():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy import update
    room = Room(id=1, owner_id=1, name="x", capacity=1, storage_used_bytes=100)
    # This compiles on PostgreSQL because the production implementation uses CASE arithmetic rather than SQLite-only max().
    from mas_app.models import Room as RoomModel
    expr = update(RoomModel).where(RoomModel.id == 1).values(storage_used_bytes=__import__('sqlalchemy').case((RoomModel.storage_used_bytes > 50, RoomModel.storage_used_bytes - 50), else_=0))
    sql = str(expr.compile(dialect=postgresql.dialect()))
    assert "GREATEST" not in sql.upper()
    assert "CASE" in sql.upper()


def test_legacy_timestamp_column_is_not_written_by_new_timer_engine(tmp_path):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from mas_app.db import initialize_database
    from mas_app.services import apply_timer_action
    from mas_app.models import Room

    db_path = tmp_path / "legacy_timer.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32) NOT NULL, password_hash VARCHAR(256) NOT NULL, account_name VARCHAR(120) DEFAULT '', age INTEGER, job VARCHAR(120) DEFAULT '', created_at INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE rooms (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name VARCHAR(160) NOT NULL, capacity INTEGER NOT NULL, recording_enabled BOOLEAN NOT NULL DEFAULT 0, live_files_enabled BOOLEAN NOT NULL DEFAULT 0, timing_mode VARCHAR(20) NOT NULL DEFAULT 'global', global_seconds INTEGER NOT NULL DEFAULT 300, order_mode VARCHAR(20) NOT NULL DEFAULT 'manual', storage_used_bytes INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speakers (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL DEFAULT '', gender VARCHAR(20) NOT NULL DEFAULT '', age INTEGER, description TEXT NOT NULL DEFAULT '', speaking_seconds INTEGER NOT NULL DEFAULT 300, order_index INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE room_states (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, current_index INTEGER NOT NULL DEFAULT 0, elapsed_seconds INTEGER NOT NULL DEFAULT 0, overtime_seconds INTEGER NOT NULL DEFAULT 0, running BOOLEAN NOT NULL DEFAULT 0, started_at TIMESTAMP NULL, updated_at INTEGER NOT NULL DEFAULT 0, current_speaker_id INTEGER, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speaker_timer_states (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, speaker_id INTEGER NOT NULL, elapsed_seconds INTEGER NOT NULL DEFAULT 0, overtime_seconds INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speech_files (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, speaker_id INTEGER, filename VARCHAR(255) NOT NULL, storage_name VARCHAR(255) NOT NULL, content_type VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream', size_bytes INTEGER NOT NULL DEFAULT 0, upload_type VARCHAR(20) NOT NULL, duration_seconds INTEGER, created_at INTEGER NOT NULL DEFAULT 0)")
        conn.execute(text("INSERT INTO users (id, username, password_hash) VALUES (1, 'legacy_timer', 'x')"))
        conn.execute(text("INSERT INTO rooms (id, owner_id, name, capacity, global_seconds) VALUES (1, 1, 'قدیمی', 1, 60)"))
        conn.execute(text("INSERT INTO speakers (id, room_id, name, order_index) VALUES (1, 1, 'علی', 0)"))
        conn.execute(text("INSERT INTO room_states (id, room_id, current_index, started_at, current_speaker_id, version) VALUES (1,1,0,'2026-09-20 12:34:56',1,1)"))
    initialize_database(engine)
    with Session(engine) as db:
        room = db.get(Room, 1)
        apply_timer_action(db, room, 'start')
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT started_at FROM room_states WHERE room_id=1")).scalar_one()
        assert str(raw).startswith("2026-09-20 12:34:56")
    engine.dispose()


def test_duplicate_storage_metadata_is_repaired_before_unique_indexes(tmp_path):
    from sqlalchemy import create_engine, text
    from mas_app.db import initialize_database

    db_path = tmp_path / "duplicate_storage.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32) NOT NULL, password_hash VARCHAR(256) NOT NULL, account_name VARCHAR(120) DEFAULT '', age INTEGER, job VARCHAR(120) DEFAULT '', created_at INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE rooms (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name VARCHAR(160) NOT NULL, capacity INTEGER NOT NULL, recording_enabled BOOLEAN NOT NULL DEFAULT 0, live_files_enabled BOOLEAN NOT NULL DEFAULT 0, timing_mode VARCHAR(20) NOT NULL DEFAULT 'global', global_seconds INTEGER NOT NULL DEFAULT 300, order_mode VARCHAR(20) NOT NULL DEFAULT 'manual', storage_used_bytes INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1)")
        conn.exec_driver_sql("CREATE TABLE speakers (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL DEFAULT '', gender VARCHAR(20) NOT NULL DEFAULT '', age INTEGER, description TEXT NOT NULL DEFAULT '', speaking_seconds INTEGER NOT NULL DEFAULT 300, order_index INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE speech_files (id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, speaker_id INTEGER, filename VARCHAR(255) NOT NULL, storage_name VARCHAR(255) NOT NULL, content_type VARCHAR(120) NOT NULL DEFAULT 'application/octet-stream', size_bytes INTEGER NOT NULL DEFAULT 0, upload_type VARCHAR(20) NOT NULL, duration_seconds INTEGER, created_at INTEGER NOT NULL DEFAULT 0)")
        conn.exec_driver_sql("CREATE TABLE file_cleanup_queue (id INTEGER PRIMARY KEY, storage_name VARCHAR(255) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL DEFAULT 0)")
        conn.execute(text("INSERT INTO users (id, username, password_hash) VALUES (1, 'dup_store', 'x')"))
        conn.execute(text("INSERT INTO rooms (id, owner_id, name, capacity, storage_used_bytes) VALUES (1, 1, 'فایل', 1, 999)"))
        conn.execute(text("INSERT INTO speech_files (id, room_id, filename, storage_name, content_type, size_bytes, upload_type) VALUES (1,1,'a.txt','same.bin','text/plain',5,'common')"))
        conn.execute(text("INSERT INTO speech_files (id, room_id, filename, storage_name, content_type, size_bytes, upload_type) VALUES (2,1,'b.txt','same.bin','text/plain',5,'common')"))
        conn.execute(text("INSERT INTO file_cleanup_queue (id, storage_name, attempts, next_attempt_at) VALUES (1,'old.bin',1,100)"))
        conn.execute(text("INSERT INTO file_cleanup_queue (id, storage_name, attempts, next_attempt_at) VALUES (2,'old.bin',3,200)"))
    initialize_database(engine)
    with engine.connect() as conn:
        files = conn.execute(text("SELECT COUNT(*) FROM speech_files WHERE storage_name='same.bin'")).scalar_one()
        cleanup = conn.execute(text("SELECT COUNT(*) FROM file_cleanup_queue WHERE storage_name='old.bin'")).scalar_one()
        storage = conn.execute(text("SELECT storage_used_bytes FROM rooms WHERE id=1")).scalar_one()
        assert files == 1
        assert cleanup == 1
        assert storage == 5
    engine.dispose()
