"""مسیریاب مدیریت سخنران‌ها و اسلات‌های اتاق."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFoundError
from ...db.models import Speaker, User
from ...schemas.speaker import (
    SpeakerReorderRequest,
    SpeakerResponse,
    SpeakerUpdateRequest,
)
from ..deps import (
    get_current_active_user,
    get_db,
    get_recording_service,
    get_room_service,
    get_speaker_service,
)

router = APIRouter(prefix="/api/rooms/{room_id}", tags=["speakers"])


@router.post("/speakers")
def add_speaker(
    room_id: int,
    payload: SpeakerUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    speaker_service: Annotated[object, Depends(get_speaker_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    speaker = speaker_service.add_speaker(
        session,
        room,
        name=payload.name,
        gender=payload.gender,
        age=payload.age,
        description=payload.description,
        speaking_seconds=payload.speaking_seconds,
    )
    return {"ok": True, "speaker": SpeakerResponse.model_validate(speaker)}


@router.put("/speakers/{speaker_id}")
def update_speaker(
    room_id: int,
    speaker_id: int,
    payload: SpeakerUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    speaker_service: Annotated[object, Depends(get_speaker_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    speaker = session.execute(
        select(Speaker).where(Speaker.id == speaker_id, Speaker.room_id == room.id)
    ).scalar_one_or_none()
    if not speaker:
        raise NotFoundError("سخنران مورد نظر یافت نشد.")

    updated = speaker_service.update_speaker(
        session,
        speaker,
        name=payload.name,
        gender=payload.gender,
        age=payload.age,
        description=payload.description,
        speaking_seconds=payload.speaking_seconds,
    )
    return {"ok": True, "speaker": SpeakerResponse.model_validate(updated)}


@router.delete("/speakers/{speaker_id}")
async def delete_speaker(
    room_id: int,
    speaker_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    speaker_service: Annotated[object, Depends(get_speaker_service)],
    recording_service: Annotated[object, Depends(get_recording_service)],
    save_recording: Annotated[bool | None, Query()] = None,
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    await speaker_service.delete_speaker(
        session,
        room,
        speaker_id,
        save_recording=save_recording,
        recording_service=recording_service,
    )
    return {"ok": True, "message": "سخنران با موفقیت حذف شد."}


@router.post("/speakers/reorder")
def reorder_speakers(
    room_id: int,
    payload: SpeakerReorderRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    speaker_service: Annotated[object, Depends(get_speaker_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    speaker_service.reorder_speakers(session, room, payload.speaker_ids)
    return {"ok": True, "message": "ترتیب سخنران‌ها به‌روزرسانی شد."}


@router.post("/speakers/{speaker_id}/unfreeze")
def unfreeze_speaker(
    room_id: int,
    speaker_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    speaker_service: Annotated[object, Depends(get_speaker_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    speaker = speaker_service.unfreeze_speaker(session, room, speaker_id)
    return {"ok": True, "speaker": SpeakerResponse.model_validate(speaker)}


@router.post("/reset-all")
def reset_all_speakers(
    room_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    speaker_service: Annotated[object, Depends(get_speaker_service)],
    recording_service: Annotated[object, Depends(get_recording_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    speaker_service.reset_all_speakers(session, room, recording_service=recording_service)
    return {"ok": True, "message": "تمام سخنران‌ها و تایمرها بازنشانی شدند."}
