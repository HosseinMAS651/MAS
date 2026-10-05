"""Public speaker-device access for speaker mode (no account login required)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    QuotaExceededError,
    RateLimitExceededError,
    UnauthorizedError,
    ValidationAppError,
)
from ...core.security import SecurityManager
from ...db.models import RecordingSession, Room, Speaker
from ...schemas.file import FileResponse
from ...schemas.speaker_access import (
    SpeakerEnterRequest,
    SpeakerHeartbeatRequest,
    SpeakerRecordingFinishRequest,
    SpeakerRecordingStartRequest,
)
from ...services.rate_limiter import RateLimiter
from ...services.speaker_access_service import SpeakerAccessService
from ..deps import (
    get_client_ip,
    get_db,
    get_recording_service,
    get_room_service,
    get_security_manager,
    get_storage_backend,
    get_timer_service,
)

router = APIRouter(prefix="/api/public/{token}/speaker", tags=["public speaker"])


def _access_from_header(value: str | None) -> str:
    if value and value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _speaker_context(
    token: str,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    security: Annotated[SecurityManager, Depends(get_security_manager)],
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[Room, Speaker]:
    room = room_service.get_room_by_public_token(session, token)
    access = SpeakerAccessService(security)
    speaker = access.authenticate(session, room, _access_from_header(authorization))
    if not speaker:
        # authenticate() revokes an expired device token in the same transaction.
        session.commit()
        raise UnauthorizedError("نشست سخنران منقضی شده یا با ورود دستگاه دیگری جایگزین شده است.")
    return room, speaker


@router.post("/enter")
def enter_as_speaker(
    token: str,
    payload: SpeakerEnterRequest,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    security: Annotated[SecurityManager, Depends(get_security_manager)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    room = room_service.get_room_by_public_token(session, token)
    bucket_key = f"speaker-code:room:{room.id}:ip:{client_ip}"
    try:
        RateLimiter.check_and_increment(
            session,
            bucket_key,
            action="speaker_code_entry",
            max_attempts=room_service.settings.speaker_code_max_attempts,
            window_seconds=room_service.settings.speaker_code_window_seconds,
        )
    except RateLimitExceededError:
        session.commit()
        raise

    result = SpeakerAccessService(security).enter(session, room, payload.code)
    if result is None:
        session.commit()
        raise UnauthorizedError("کد سخنران نادرست است یا حالت سخنران فعال نیست.")
    speaker, raw_token = result
    RateLimiter.reset(session, bucket_key)
    return {
        "ok": True,
        "session_token": raw_token,
        "speaker": {"id": speaker.id, "name": speaker.name, "presence_status": speaker.presence_status},
        "speaker_uploads_enabled": room.speaker_uploads_enabled,
    }


@router.post("/heartbeat")
def speaker_heartbeat(
    token: str,
    payload: SpeakerHeartbeatRequest,
    context: Annotated[tuple[Room, Speaker], Depends(_speaker_context)],
    session: Annotated[Session, Depends(get_db)],
    security: Annotated[SecurityManager, Depends(get_security_manager)],
) -> dict:
    _room, speaker = context
    status = SpeakerAccessService(security).heartbeat(
        session, speaker, microphone_ready=payload.microphone_ready
    )
    return {"ok": True, "presence_status": status}


@router.post("/leave")
def leave_speaker_session(
    token: str,
    context: Annotated[tuple[Room, Speaker], Depends(_speaker_context)],
    session: Annotated[Session, Depends(get_db)],
) -> dict:
    _room, speaker = context
    SpeakerAccessService.leave(session, speaker)
    return {"ok": True}


@router.post("/recording/start")
def start_speaker_recording(
    token: str,
    payload: SpeakerRecordingStartRequest,
    context: Annotated[tuple[Room, Speaker], Depends(_speaker_context)],
    session: Annotated[Session, Depends(get_db)],
    recording_service: Annotated[object, Depends(get_recording_service)],
    timer_service: Annotated[object, Depends(get_timer_service)],
) -> dict:
    room, speaker = context
    if speaker.presence_status != "ready":
        raise ConflictError("برای ضبط ابتدا دسترسی میکروفون را فعال کنید.", code="MICROPHONE_NOT_READY")
    snapshot = timer_service.get_snapshot(session, room)
    if not snapshot["running"] or snapshot["current_speaker_id"] != speaker.id:
        raise ConflictError("ضبط فقط هنگام فعال بودن تایمر همین سخنران آغاز می‌شود.", code="SPEAKER_TURN_NOT_ACTIVE")

    recording = recording_service.start_or_resume(
        session,
        room,
        speaker,
        mime_type=payload.mime_type,
    )
    return {
        "ok": True,
        "session_id": recording.id,
        "status": recording.status,
        "mime_type": recording.mime_type,
        "next_seq": recording.chunk_seq,
    }


@router.post("/recording/chunk")
async def upload_speaker_recording_chunk(
    token: str,
    session_id: Annotated[int, Form()],
    seq: Annotated[int, Form()],
    chunk: Annotated[UploadFile, File()],
    context: Annotated[tuple[Room, Speaker], Depends(_speaker_context)],
    session: Annotated[Session, Depends(get_db)],
    recording_service: Annotated[object, Depends(get_recording_service)],
) -> dict:
    room, speaker = context
    data = await chunk.read(recording_service.settings.max_recording_chunk_bytes + 1)
    if not data:
        raise ValidationAppError("تکهٔ ارسالی خالی است.")
    if len(data) > recording_service.settings.max_recording_chunk_bytes:
        raise QuotaExceededError("اندازهٔ تکه از سقف مجاز بزرگ‌تر است.")

    belongs_to_speaker = session.execute(
        select(RecordingSession.id).where(
            RecordingSession.id == session_id,
            RecordingSession.room_id == room.id,
            RecordingSession.speaker_id == speaker.id,
        )
    ).scalar_one_or_none()
    if belongs_to_speaker is None:
        raise NotFoundError("نشست ضبط متعلق به این سخنران یافت نشد.")

    saved = await recording_service.save_chunk(
        session, session_id, seq, data, room_id=room.id
    )
    return {"ok": True, "session_id": saved.session_id, "seq": saved.seq, "bytes_received": saved.size_bytes}


@router.post("/recording/finish")
async def finish_speaker_recording(
    token: str,
    payload: SpeakerRecordingFinishRequest,
    context: Annotated[tuple[Room, Speaker], Depends(_speaker_context)],
    session: Annotated[Session, Depends(get_db)],
    recording_service: Annotated[object, Depends(get_recording_service)],
) -> dict:
    room, speaker = context
    recording = session.execute(
        select(RecordingSession).where(
            RecordingSession.id == payload.session_id,
            RecordingSession.room_id == room.id,
            RecordingSession.speaker_id == speaker.id,
        )
    ).scalar_one_or_none()
    if not recording:
        raise NotFoundError("نشست ضبط متعلق به این سخنران یافت نشد.")
    if recording.status in {"saved", "discarded"}:
        return {
            "ok": True,
            "file": FileResponse.model_validate(recording.final_file) if recording.final_file else None,
            "status": recording.status,
        }
    if not payload.save:
        recording_service.discard_recording_sync(session, recording)
        return {"ok": True, "file": None, "status": "discarded"}

    final_file = await recording_service.finish_and_save(session, recording)
    return {
        "ok": True,
        "file": FileResponse.model_validate(final_file) if final_file else None,
        "status": "saved" if final_file else "discarded",
    }


@router.post("/files")
async def upload_speaker_file(
    token: str,
    file: Annotated[UploadFile, File()],
    context: Annotated[tuple[Room, Speaker], Depends(_speaker_context)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    storage: Annotated[object, Depends(get_storage_backend)],
) -> dict:
    room, speaker = context
    if not room.speaker_uploads_enabled:
        raise ForbiddenError("مالک اتاق آپلود فایل توسط سخنران را فعال نکرده است.")

    async def file_stream() -> AsyncIterator[bytes]:
        while True:
            chunk = await file.read(65_536)
            if not chunk:
                break
            yield chunk

    speech_file = await room_service.upload_speech_file(
        session,
        room,
        upload_type="speaker",
        filename=file.filename or "file",
        content_type=file.content_type or "application/octet-stream",
        stream=file_stream(),
        speaker_id=speaker.id,
        approval_status="pending",
    )
    return {"ok": True, "file": FileResponse.model_validate(speech_file), "review": "pending"}
