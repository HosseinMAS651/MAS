import re
import time
from pathlib import Path

from fastapi.testclient import TestClient

from mas_app.config import Settings
from mas_app.main import create_app
from mas_app.models import Room, RoomState, Speaker, SpeechFile, User
from mas_app.services import now, state_snapshot


def make_app(tmp_path: Path):
    db_path = tmp_path / "test.db"
    storage = tmp_path / "uploads"
    storage.mkdir()
    cfg = Settings(
        env="test", secret_key="x" * 64, database_url=f"sqlite:///{db_path}", storage_dir=storage,
        cookie_secure=False, public_base_url="", session_seconds=86400, max_upload_bytes=2 * 1024 * 1024,
        max_total_upload_bytes=5 * 1024 * 1024, max_files_per_request=20,
        max_room_storage_bytes=20 * 1024 * 1024, max_recording_seconds=1800,
        login_max_failures=10, login_window_seconds=600, register_max_attempts=50,
        register_window_seconds=600,
    )
    return create_app(cfg), cfg


def form_token(client: TestClient, path: str) -> str:
    r = client.get(path)
    assert r.status_code == 200
    m = re.search(r'name="auth_token" value="([^"]+)"', r.text)
    assert m
    return m.group(1)


def login(client: TestClient, username="tester", password="Password123"):
    token = form_token(client, "/login")
    r = client.post("/login", data={"username": username, "password": password, "auth_token": token}, follow_redirects=False)
    assert r.status_code == 303
    return r


def complete_profile(client: TestClient):
    r = client.get("/profile")
    assert r.status_code == 200
    m = re.search(r'name="csrf" value="([^"]+)"', r.text)
    assert m
    csrf = m.group(1)
    r = client.post("/profile", data={"csrf": csrf, "account_name": "Test User", "age": "20", "job": "Student"}, follow_redirects=False)
    assert r.status_code == 303


def test_auth_room_public_and_files(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token = form_token(client, "/register")
        r = client.post("/register", data={"username": "tester", "password": "Password123", "password2": "Password123", "auth_token": token}, follow_redirects=False)
        assert r.status_code == 303
        complete_profile(client)
        r = client.get("/rooms")
        assert r.status_code == 200
        r = client.get("/rooms/new")
        csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
        r = client.post("/rooms/new", data={"csrf": csrf, "name": "Room One", "capacity": "2"}, follow_redirects=False)
        assert r.status_code == 303
        room_id = int(r.headers["location"].rsplit("/", 1)[1])
        r = client.get(f"/rooms/{room_id}")
        assert r.status_code == 200
        pub = re.search(r'href="(/p/[^\"]+)"[^>]*>👁 نمایش عمومی', r.text).group(1)
        r = client.get(pub)
        assert r.status_code == 200
        qr = client.get(pub + "/qr.svg")
        assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")


def test_timer_timeout_continue_and_finish(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token = form_token(client, "/register")
        client.post("/register", data={"username": "tester", "password": "Password123", "password2": "Password123", "auth_token": token})
        complete_profile(client)
        csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/rooms/new").text).group(1)
        r = client.post("/rooms/new", data={"csrf": csrf, "name": "Timer Room", "capacity": "2"}, follow_redirects=False)
        rid = int(r.headers["location"].rsplit("/", 1)[1])
        with app.state.SessionLocal() as db:
            room = db.get(Room, rid)
            speakers = sorted(room.speakers, key=lambda s: s.order_index)
            speakers[0].name = "Ali"; speakers[1].name = "Reza"
            room.global_seconds = 5
            state = db.scalar(RoomState and __import__('sqlalchemy').select(RoomState).where(RoomState.room_id == rid))
            state.current_speaker_id = speakers[0].id
            state.current_index = 0
            db.commit()
        r = client.get(f"/rooms/{rid}/play")
        csrf_play = re.search(r'id="play-data">(.*?)</script>', r.text).group(1)
        import json
        data = json.loads(__import__('html').unescape(csrf_play))
        csrf_live = data["csrf"]
        r = client.post(f"/api/rooms/{rid}/start", data={"csrf": csrf_live})
        assert r.status_code == 200
        with app.state.SessionLocal() as db:
            room = db.get(Room, rid)
            state = db.get(RoomState, room.state.id)
            state.started_at = now() - 10
            db.commit()
            snapshot = state_snapshot(db, room, auto_expire=True)
            assert snapshot["awaiting_decision"] is True
            assert snapshot["running"] is False
            assert snapshot["remaining_seconds"] == 0
        r = client.post(f"/api/rooms/{rid}/continue", data={"csrf": csrf_live})
        assert r.status_code == 200
        assert r.json()["running"] is True
        r = client.post(f"/api/rooms/{rid}/pause", data={"csrf": csrf_live})
        assert r.status_code == 200 and r.json()["running"] is False
        r = client.post(f"/api/rooms/{rid}/finish", data={"csrf": csrf_live})
        assert r.status_code == 200
        assert r.json()["current_speaker_id"] is not None
        assert r.json()["current_index"] == 1


def test_recording_links_speaker_and_public_cannot_access_it(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token = form_token(client, "/register")
        client.post("/register", data={"username": "tester", "password": "Password123", "password2": "Password123", "auth_token": token})
        complete_profile(client)
        csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/rooms/new").text).group(1)
        rid = int(client.post("/rooms/new", data={"csrf": csrf, "name": "Record Room", "capacity": "1"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1])
        page = client.get(f"/rooms/{rid}")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        form = {"csrf": csrf, "room_name": "Record Room", "timing_mode": "global", "global_min": "5", "order_mode": "manual", "recording": "on"}
        with app.state.SessionLocal() as db:
            room = db.get(Room, rid); sp = sorted(room.speakers, key=lambda s: s.order_index)[0]
            form.update({f"name_{sp.id}": "Speaker A", f"gender_{sp.id}": "", f"age_{sp.id}": "20", f"time_{sp.id}": "5", f"desc_{sp.id}": ""})
        r = client.post(f"/rooms/{rid}/save", data=form, follow_redirects=False)
        assert r.status_code == 303
        with app.state.SessionLocal() as db:
            room = db.get(Room, rid); sp = sorted(room.speakers, key=lambda s: s.order_index)[0]
            state = db.get(RoomState, room.state.id); state.current_speaker_id=sp.id; db.commit()
            csrf = client.get(f"/rooms/{rid}/play").text
            csrf = __import__('json').loads(__import__('html').unescape(re.search(r'id="play-data">(.*?)</script>', csrf).group(1)))['csrf']
        audio = b'fake-webm-data'
        r = client.post(f"/api/rooms/{rid}/recording", data={"csrf": csrf, "speaker_id": str(sp.id), "duration_seconds": "3"}, files={"file": ("recording.webm", audio, "audio/webm")})
        assert r.status_code == 200
        with app.state.SessionLocal() as db:
            row = db.query(SpeechFile).filter(SpeechFile.room_id==rid, SpeechFile.upload_type=="recording").one()
            assert row.speaker_id == sp.id
            public_token = db.get(Room, rid).public_token
            fid = row.id
        r = client.get(f"/public-api/rooms/{public_token}/state")
        assert r.status_code == 200
        assert all(f["id"] != fid for f in r.json()["files"])
        r = client.get(f"/public-files/{public_token}/{fid}")
        assert r.status_code == 404


def test_delete_speaker_can_preserve_recording_snapshot(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token=form_token(client,"/register")
        client.post("/register",data={"username":"tester","password":"Password123","password2":"Password123","auth_token":token})
        complete_profile(client)
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get("/rooms/new").text).group(1)
        rid=int(client.post("/rooms/new",data={"csrf":csrf,"name":"Delete Room","capacity":"1"},follow_redirects=False).headers["location"].rsplit("/",1)[1])
        page=client.get(f"/rooms/{rid}")
        csrf=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
        # Enable recording and name the only speaker.
        data={"csrf":csrf,"room_name":"Delete Room","timing_mode":"global","global_min":"5","order_mode":"manual","recording":"on"}
        with app.state.SessionLocal() as db:
            room=db.get(Room,rid);sp=room.speakers[0]
            data.update({f"name_{sp.id}":"Delete Me",f"gender_{sp.id}":"",f"age_{sp.id}":"20",f"time_{sp.id}":"5",f"desc_{sp.id}":""})
        client.post(f"/rooms/{rid}/save",data=data)
        play=client.get(f"/rooms/{rid}/play")
        csrf=__import__('json').loads(__import__('html').unescape(re.search(r'id="play-data">(.*?)</script>',play.text).group(1)))['csrf']
        with app.state.SessionLocal() as db:
            sp=db.query(Speaker).filter(Speaker.room_id==rid).one()
        r=client.post(f"/api/rooms/{rid}/speakers/{sp.id}/delete",data={"csrf":csrf,"save_recording":"1","duration_seconds":"2"},files={"recording":("recording.webm",b'123','audio/webm')})
        assert r.status_code==200
        with app.state.SessionLocal() as db:
            assert db.query(Speaker).filter(Speaker.id==sp.id).count()==0
            row=db.query(SpeechFile).filter(SpeechFile.room_id==rid,SpeechFile.upload_type=="recording").one()
            assert row.speaker_id is None
            assert row.speaker_name_snapshot=="Delete Me"


def _get_play_csrf(client, rid):
    import json, html
    page = client.get(f"/rooms/{rid}/play")
    payload = json.loads(html.unescape(re.search(r'id="play-data">(.*?)</script>', page.text).group(1)))
    return payload["csrf"]


def test_delete_speaker_discard_removes_saved_recording(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token=form_token(client,"/register")
        client.post("/register",data={"username":"tester","password":"Password123","password2":"Password123","auth_token":token})
        complete_profile(client)
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get("/rooms/new").text).group(1)
        rid=int(client.post("/rooms/new",data={"csrf":csrf,"name":"Discard Room","capacity":"1"},follow_redirects=False).headers["location"].rsplit("/",1)[1])
        page=client.get(f"/rooms/{rid}")
        csrf=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
        data={"csrf":csrf,"room_name":"Discard Room","timing_mode":"global","global_min":"5","order_mode":"manual","recording":"on"}
        with app.state.SessionLocal() as db:
            room=db.get(Room,rid); sp=room.speakers[0]
            data.update({f"name_{sp.id}":"Discard Me",f"gender_{sp.id}":"",f"age_{sp.id}":"20",f"time_{sp.id}":"5",f"desc_{sp.id}":""})
        client.post(f"/rooms/{rid}/save",data=data)
        csrf=_get_play_csrf(client,rid)
        with app.state.SessionLocal() as db:
            room=db.get(Room,rid); sp=room.speakers[0]
            f=SpeechFile(room_id=rid,speaker_id=sp.id,filename="old.webm",storage_name="old.webm",content_type="audio/webm",size_bytes=3,upload_type="recording",duration_seconds=2,created_at=now(),speaker_name_snapshot=sp.name,room_name_snapshot=room.name)
            db.add(f); room.storage_used_bytes=3; db.commit(); fid=f.id
            (cfg.storage_dir/"old.webm").write_bytes(b"old")
        r=client.post(f"/api/rooms/{rid}/speakers/{sp.id}/delete",data={"csrf":csrf,"save_recording":"0"})
        assert r.status_code==200
        with app.state.SessionLocal() as db:
            assert db.get(Speaker,sp.id) is None
            assert db.query(SpeechFile).filter(SpeechFile.id==fid).count()==0
            assert db.get(Room,rid).storage_used_bytes==0
        assert not (cfg.storage_dir/"old.webm").exists()


def test_public_file_version_changes_after_delete(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token=form_token(client,"/register")
        client.post("/register",data={"username":"tester","password":"Password123","password2":"Password123","auth_token":token})
        complete_profile(client)
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get("/rooms/new").text).group(1)
        rid=int(client.post("/rooms/new",data={"csrf":csrf,"name":"Public File Room","capacity":"1"},follow_redirects=False).headers["location"].rsplit("/",1)[1])
        with app.state.SessionLocal() as db:
            room=db.get(Room,rid); room.live_files_enabled=True; room.speakers[0].name="Ali"; db.commit(); token=room.public_token
            f=SpeechFile(room_id=rid,speaker_id=room.speakers[0].id,filename="note.txt",storage_name="note.txt",content_type="text/plain",size_bytes=4,upload_type="speaker",created_at=now(),speaker_name_snapshot="Ali",room_name_snapshot=room.name)
            db.add(f); room.storage_used_bytes=4; db.commit(); fid=f.id; before=room.version
            (cfg.storage_dir/"note.txt").write_bytes(b"note")
        first=client.get(f"/public-api/rooms/{token}/state").json()
        assert any(x["id"]==fid for x in first["files"])
        owner_csrf=_get_play_csrf(client,rid)
        r=client.post(f"/files/{fid}/delete",data={"csrf":owner_csrf})
        assert r.status_code==200
        second=client.get(f"/public-api/rooms/{token}/state").json()
        assert second["room_version"] > first["room_version"] >= before
        assert all(x["id"]!=fid for x in second["files"])


def test_completed_room_rejects_restart(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        token=form_token(client,"/register")
        client.post("/register",data={"username":"tester","password":"Password123","password2":"Password123","auth_token":token})
        complete_profile(client)
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get("/rooms/new").text).group(1)
        rid=int(client.post("/rooms/new",data={"csrf":csrf,"name":"Complete Room","capacity":"1"},follow_redirects=False).headers["location"].rsplit("/",1)[1])
        with app.state.SessionLocal() as db:
            room=db.get(Room,rid)
            room.speakers[0].name="Only Speaker"
            db.commit()
        page=client.get(f"/rooms/{rid}/play")
        import json, html
        play_data=json.loads(html.unescape(re.search(r'id="play-data">(.*?)</script>',page.text).group(1)))
        r=client.post(f"/api/rooms/{rid}/finish",data={"csrf":play_data["csrf"]})
        assert r.status_code==200 and r.json()["completed"] is True
        r=client.post(f"/api/rooms/{rid}/start",data={"csrf":play_data["csrf"]})
        assert r.status_code==409
