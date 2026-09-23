"""مسیریاب آپلود تکه‌ای و مدیریت نشست‌های ضبط صدا."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ...core.errors import NotFoundError, ValidationAppError
from ...db.models import User
from ...schemas.file import FileResponse
from ...schemas.recording import (
    RecordingChunkResponse,
    RecordingFinishRequest,
    RecordingSessionStatusResponse,
)
from ..deps import (
    get_current_active_user,
    get_db,
    get_recording_service,
    get_room_service,
)

router = APIRouter(prefix="/api/rooms/{room_id}/recording", tags=["recording"])


@router.get("/status")
def get_recording_status(
    room_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    recording_service: Annotated[object, Depends(get_recording_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    rec = recording_service.get_active_session(session, room.id)
    if not rec:
        return {"ok": True, "active": False, "session": None}
    resp = RecordingSessionStatusResponse(
        session_id=rec.id,
        room_id=rec.room_id,
        speaker_id=rec.speaker_id,
        speaker_name=rec.speaker_name,
        status=rec.status,
        chunk_seq=rec.chunk_seq,
        bytes_received=rec.bytes_received,
        recorded_ms=rec.recorded_ms,
        active=rec.status in ["recording", "paused"],
    )
    return {"ok": True, "active": True, "session": resp}


@router.post("/chunk")
async def upload_recording_chunk(
    room_id: int,
    session_id: Annotated[int, Form()],
    seq: Annotated[int, Form()],
    chunk: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    recording_service: Annotated[object, Depends(get_recording_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    data = await chunk.read()
    if not data:
        raise ValidationAppError("تکهٔ ارسالی خالی است.")
    chunk_obj = await recording_service.save_chunk(
        session, session_id, seq, data, room_id=room.id
    )
    return {
        "ok": True,
        "chunk": RecordingChunkResponse(
            session_id=chunk_obj.session_id,
            seq=chunk_obj.seq,
            bytes_received=chunk_obj.size_bytes,
            status="saved",
        ),
    }


@router.post("/finish")
async def finish_recording(
    room_id: int,
    payload: RecordingFinishRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    recording_service: Annotated[object, Depends(get_recording_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    rec = recording_service.get_active_session(session, room.id)
    if not rec:
        raise NotFoundError("هیچ ضبط فعالی برای این اتاق یافت نشد.")
    if not payload.save:
        recording_service.discard_recording_sync(session, rec)
        return {"ok": True, "message": "ضبط با موفقیت دور ریخته شد."}

    final_file = await recording_service.finish_and_save(session, rec)
    return {
        "ok": True,
        "message": "ضبط با موفقیت مونتاژ و ذخیره شد.",
        "file": FileResponse.model_validate(final_file) if final_file else None,
    }
