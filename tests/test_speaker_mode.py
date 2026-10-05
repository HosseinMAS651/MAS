"""Integration tests for public speaker access, upload review and device recording."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

SPEAKER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _create_speaker_room(
    client: TestClient,
    username: str,
    *,
    speaker_uploads_enabled: bool = False,
    recording_enabled: bool = False,
):
    registered = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password1234"},
    )
    assert registered.status_code == 200
    created = client.post(
        "/api/rooms",
        json={
            "name": "اتاق سخنران",
            "capacity": 1,
            "public_enabled": True,
            "live_files_enabled": True,
            "recording_enabled": recording_enabled,
            "speaker_mode_enabled": True,
            "speaker_uploads_enabled": speaker_uploads_enabled,
        },
    )
    assert created.status_code == 200
    room_id = created.json()["room"]["id"]
    room = client.get(f"/api/rooms/{room_id}").json()["room"]
    return room_id, room["public_token"], room["speakers"][0]


def _enter_speaker(client: TestClient, token: str, code: str) -> tuple[str, int]:
    response = client.post(f"/api/public/{token}/speaker/enter", json={"code": code})
    assert response.status_code == 200
    body = response.json()
    return body["session_token"], body["speaker"]["id"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_speaker_code_presence_and_one_active_device(client: TestClient):
    room_id, public_token, first_speaker = _create_speaker_room(client, "speaker_presence_user")
    code = first_speaker["speaker_code"]
    assert len(code) == 4
    assert set(code) <= set(SPEAKER_CODE_ALPHABET)

    first_session, speaker_id = _enter_speaker(client, public_token, code.lower())
    ready = client.post(
        f"/api/public/{public_token}/speaker/heartbeat",
        json={"microphone_ready": True},
        headers=_bearer(first_session),
    )
    assert ready.status_code == 200
    assert ready.json()["presence_status"] == "ready"

    room = client.get(f"/api/rooms/{room_id}").json()["room"]
    assert room["speakers"][0]["presence_status"] == "ready"

    # Entering the same code on a second device replaces the previous bearer token.
    second_session, second_speaker_id = _enter_speaker(client, public_token, code)
    assert second_speaker_id == speaker_id
    stale = client.post(
        f"/api/public/{public_token}/speaker/heartbeat",
        json={"microphone_ready": True},
        headers=_bearer(first_session),
    )
    assert stale.status_code == 401

    connected = client.post(
        f"/api/public/{public_token}/speaker/heartbeat",
        json={"microphone_ready": False},
        headers=_bearer(second_session),
    )
    assert connected.status_code == 200
    assert connected.json()["presence_status"] == "connected"

    left = client.post(
        f"/api/public/{public_token}/speaker/leave",
        json={},
        headers=_bearer(second_session),
    )
    assert left.status_code == 200
    assert client.get(f"/api/rooms/{room_id}").json()["room"]["speakers"][0]["presence_status"] == "offline"


def test_speaker_code_survives_mode_toggle_until_owner_rotates_it(client: TestClient):
    room_id, public_token, speaker = _create_speaker_room(client, "speaker_code_rotate_user")
    original_code = speaker["speaker_code"]
    room = client.get(f"/api/rooms/{room_id}").json()["room"]
    update_data = {
        "name": room["name"],
        "capacity": room["capacity"],
        "description": room["description"],
        "recording_enabled": room["recording_enabled"],
        "live_files_enabled": room["live_files_enabled"],
        "speaker_mode_enabled": False,
        "speaker_uploads_enabled": room["speaker_uploads_enabled"],
        "timing_mode": room["timing_mode"],
        "global_seconds": room["global_seconds"],
        "order_mode": room["order_mode"],
        "public_enabled": room["public_enabled"],
    }
    disabled = client.put(f"/api/rooms/{room_id}", json=update_data)
    assert disabled.status_code == 200
    update_data["speaker_mode_enabled"] = True
    enabled = client.put(f"/api/rooms/{room_id}", json=update_data)
    assert enabled.status_code == 200

    current_room = client.get(f"/api/rooms/{room_id}").json()["room"]
    assert current_room["speakers"][0]["speaker_code"] == original_code
    rotated = client.post(
        f"/api/rooms/{room_id}/speakers/{speaker['id']}/rotate-code", json={}
    )
    assert rotated.status_code == 200
    new_code = rotated.json()["speaker_code"]
    assert new_code != original_code

    old_code_attempt = client.post(
        f"/api/public/{public_token}/speaker/enter", json={"code": original_code}
    )
    assert old_code_attempt.status_code == 401
    new_code_attempt = client.post(
        f"/api/public/{public_token}/speaker/enter", json={"code": new_code}
    )
    assert new_code_attempt.status_code == 200


def test_speaker_presence_expires_after_one_minute_without_heartbeat(client: TestClient):
    from sqlalchemy import select

    from mas_app.core.timeutil import utc_now_ms
    from mas_app.db.models import Speaker

    room_id, public_token, speaker = _create_speaker_room(client, "speaker_expiry_user")
    session_token, speaker_id = _enter_speaker(client, public_token, speaker["speaker_code"])
    with client.app.state.database.session() as session:
        speaker_row = session.execute(select(Speaker).where(Speaker.id == speaker_id)).scalar_one()
        speaker_row.presence_status = "ready"
        speaker_row.presence_last_seen_at_ms = utc_now_ms() - 61_000
        session.commit()

    room = client.get(f"/api/rooms/{room_id}").json()["room"]
    assert room["speakers"][0]["presence_status"] == "offline"

    stale_heartbeat = client.post(
        f"/api/public/{public_token}/speaker/heartbeat",
        json={"microphone_ready": True},
        headers=_bearer(session_token),
    )
    assert stale_heartbeat.status_code == 401


def test_speaker_file_stays_private_until_owner_approves(client: TestClient):
    _room_id, public_token, speaker = _create_speaker_room(
        client,
        "speaker_upload_user",
        speaker_uploads_enabled=True,
    )
    session_token, _ = _enter_speaker(client, public_token, speaker["speaker_code"])

    uploaded = client.post(
        f"/api/public/{public_token}/speaker/files",
        headers=_bearer(session_token),
        files={"file": ("speaker-slides.pdf", io.BytesIO(b"%PDF-1.4\nslides"), "application/pdf")},
    )
    assert uploaded.status_code == 200
    file_info = uploaded.json()["file"]
    assert file_info["approval_status"] == "pending"

    state = client.get(f"/api/public/{public_token}/state").json()["state"]
    assert all(item["id"] != file_info["id"] for item in state["live_files"])
    private_file = client.get(f"/api/public/{public_token}/files/{file_info['id']}")
    assert private_file.status_code == 404

    approved = client.post(
        f"/api/rooms/{_room_id}/files/{file_info['id']}/review",
        json={"approved": True},
    )
    assert approved.status_code == 200
    assert approved.json()["file"]["approval_status"] == "approved"

    state_after_review = client.get(f"/api/public/{public_token}/state").json()["state"]
    assert any(item["id"] == file_info["id"] for item in state_after_review["live_files"])
    public_file = client.get(f"/api/public/{public_token}/files/{file_info['id']}")
    assert public_file.status_code == 200
    assert public_file.content == b"%PDF-1.4\nslides"


def test_speaker_recording_preserves_mp4_mime_type_and_extension(client: TestClient):
    room_id, public_token, speaker = _create_speaker_room(client, "speaker_mp4_user")
    session_token, _ = _enter_speaker(client, public_token, speaker["speaker_code"])
    ready = client.post(
        f"/api/public/{public_token}/speaker/heartbeat",
        json={"microphone_ready": True},
        headers=_bearer(session_token),
    )
    assert ready.status_code == 200
    started_timer = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})
    assert started_timer.status_code == 200

    started = client.post(
        f"/api/public/{public_token}/speaker/recording/start",
        json={"mime_type": "audio/mp4;codecs=mp4a.40.2"},
        headers=_bearer(session_token),
    )
    assert started.status_code == 200
    assert started.json()["mime_type"] == "audio/mp4"
    recording_id = started.json()["session_id"]
    chunk_data = b"mp4-audio-data"
    uploaded = client.post(
        f"/api/public/{public_token}/speaker/recording/chunk",
        headers=_bearer(session_token),
        data={"session_id": str(recording_id), "seq": "0"},
        files={"chunk": ("speaker-0.m4a", io.BytesIO(chunk_data), "audio/mp4")},
    )
    assert uploaded.status_code == 200
    finalized = client.post(
        f"/api/public/{public_token}/speaker/recording/finish",
        json={"session_id": recording_id, "save": True},
        headers=_bearer(session_token),
    )
    assert finalized.status_code == 200
    assert finalized.json()["file"]["content_type"] == "audio/mp4"
    assert finalized.json()["file"]["filename"].endswith(".m4a")


def test_speaker_device_recording_uses_owner_timer_and_is_playable(client: TestClient):
    room_id, public_token, speaker = _create_speaker_room(
        client,
        "speaker_recording_user",
        recording_enabled=True,
    )
    room = client.get(f"/api/rooms/{room_id}").json()["room"]
    # Speaker mode is authoritative; the owner's-device recording toggle is disabled.
    assert room["speaker_mode_enabled"] is True
    assert room["recording_enabled"] is False

    session_token, _ = _enter_speaker(client, public_token, speaker["speaker_code"])
    heartbeat = client.post(
        f"/api/public/{public_token}/speaker/heartbeat",
        json={"microphone_ready": True},
        headers=_bearer(session_token),
    )
    assert heartbeat.status_code == 200

    started_timer = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "start"})
    assert started_timer.status_code == 200
    assert started_timer.json()["state"]["running"] is True

    started_recording = client.post(
        f"/api/public/{public_token}/speaker/recording/start",
        json={"mime_type": "audio/webm;codecs=opus"},
        headers=_bearer(session_token),
    )
    assert started_recording.status_code == 200
    recording_id = started_recording.json()["session_id"]
    assert started_recording.json()["next_seq"] == 0

    chunk_data = b"speaker-device-audio-chunk"
    uploaded_chunk = client.post(
        f"/api/public/{public_token}/speaker/recording/chunk",
        headers=_bearer(session_token),
        data={"session_id": str(recording_id), "seq": "0"},
        files={"chunk": ("speaker-0.webm", io.BytesIO(chunk_data), "audio/webm")},
    )
    assert uploaded_chunk.status_code == 200
    assert uploaded_chunk.json()["seq"] == 0

    finished_timer = client.post(f"/api/rooms/{room_id}/timer/action", json={"action": "finish"})
    assert finished_timer.status_code == 200
    assert finished_timer.json()["state"]["running"] is False

    finalized = client.post(
        f"/api/public/{public_token}/speaker/recording/finish",
        json={"session_id": recording_id, "save": True},
        headers=_bearer(session_token),
    )
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "saved"
    recorded_file = finalized.json()["file"]
    assert recorded_file["upload_type"] == "recording"
    assert recorded_file["content_type"] == "audio/webm"
    assert recorded_file["size_bytes"] == len(chunk_data)

    playback = client.get(f"/api/rooms/{room_id}/files/{recorded_file['id']}/play")
    assert playback.status_code == 200
    assert playback.headers["content-type"].startswith("audio/webm")
    assert playback.content == chunk_data
