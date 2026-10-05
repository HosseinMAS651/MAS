"""Public speaker-code access and device-presence lifecycle."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.security import SecurityManager
from ..core.timeutil import utc_now_ms
from ..db.models import Room, Speaker

PRESENCE_TIMEOUT_MS = 60_000


class SpeakerAccessService:
    def __init__(self, security: SecurityManager) -> None:
        self.security = security

    @staticmethod
    def normalize_code(code: str) -> str:
        return (code or "").strip().upper()

    def enter(self, session: Session, room: Room, code: str) -> tuple[Speaker, str] | None:
        locked_room = session.execute(
            select(Room).where(Room.id == room.id).with_for_update()
        ).scalar_one_or_none()
        if not locked_room or not locked_room.speaker_mode_enabled:
            return None
        normalized = self.normalize_code(code)
        if len(normalized) != 4:
            return None
        code_hash = self.security.hash_token(f"speaker-code:{locked_room.id}:{normalized}")
        speaker = session.execute(
            select(Speaker)
            .where(Speaker.room_id == locked_room.id, Speaker.speaker_code_hash == code_hash)
            .with_for_update()
        ).scalar_one_or_none()
        if not speaker:
            return None

        raw_token = self.security.generate_session_token()
        speaker.speaker_session_hash = self.security.hash_token(f"speaker-session:{raw_token}")
        speaker.presence_status = "connected"
        speaker.presence_last_seen_at_ms = utc_now_ms()
        speaker.updated_at_ms = speaker.presence_last_seen_at_ms
        session.flush()
        return speaker, raw_token

    def authenticate(self, session: Session, room: Room, raw_token: str) -> Speaker | None:
        locked_room = session.execute(
            select(Room).where(Room.id == room.id).with_for_update()
        ).scalar_one_or_none()
        if not locked_room or not locked_room.speaker_mode_enabled or not raw_token:
            return None
        digest = self.security.hash_token(f"speaker-session:{raw_token}")
        speaker = session.execute(
            select(Speaker)
            .where(Speaker.room_id == locked_room.id, Speaker.speaker_session_hash == digest)
            .with_for_update()
        ).scalar_one_or_none()
        if not speaker:
            return None

        now_ms = utc_now_ms()
        if now_ms - speaker.presence_last_seen_at_ms >= PRESENCE_TIMEOUT_MS:
            speaker.speaker_session_hash = None
            speaker.presence_status = "offline"
            speaker.updated_at_ms = now_ms
            session.flush()
            return None
        return speaker

    @staticmethod
    def heartbeat(session: Session, speaker: Speaker, *, microphone_ready: bool) -> str:
        now_ms = utc_now_ms()
        speaker.presence_status = "ready" if microphone_ready else "connected"
        speaker.presence_last_seen_at_ms = now_ms
        speaker.updated_at_ms = now_ms
        session.flush()
        return speaker.presence_status

    @staticmethod
    def leave(session: Session, speaker: Speaker) -> None:
        speaker.speaker_session_hash = None
        speaker.presence_status = "offline"
        speaker.updated_at_ms = utc_now_ms()
        session.flush()
