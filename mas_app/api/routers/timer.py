"""مسیریاب وضعیت زنده و اکشن‌های تایمر اتاق پخش."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from ...db.models import Room, User
from ...schemas.file import FileResponse
from ...schemas.speaker import SpeakerResponse
from ...schemas.timer import TimerActionRequest, TimerStateResponse
from ..deps import (
    get_current_active_user,
    get_db,
    get_room_service,
    get_timer_service,
)

router = APIRouter(prefix="/api/rooms/{room_id}/timer", tags=["timer"])


def _format_timer_state(room: Room, snapshot: dict) -> TimerStateResponse:
    sp_responses = []
    for s in snapshot["speakers"]:
        el = s.timer.elapsed_ms if s.timer else 0
        ot = s.timer.overtime_ms if s.timer else 0
        sp_responses.append(
            SpeakerResponse(
                id=s.id,
                room_id=s.room_id,
                order_index=s.order_index,
                name=s.name,
                gender=s.gender,
                age=s.age,
                description=s.description,
                speaking_seconds=s.speaking_seconds,
                is_finished=s.is_finished,
                finished_at_ms=s.finished_at_ms,
                elapsed_ms=el,
                overtime_ms=ot,
            )
        )

    cur_sp = snapshot["current_speaker"]
    cur_sp_resp = None
    if cur_sp:
        cur_sp_resp = SpeakerResponse(
            id=cur_sp.id,
            room_id=cur_sp.room_id,
            order_index=cur_sp.order_index,
            name=cur_sp.name,
            gender=cur_sp.gender,
            age=cur_sp.age,
            description=cur_sp.description,
            speaking_seconds=cur_sp.speaking_seconds,
            is_finished=cur_sp.is_finished,
            finished_at_ms=cur_sp.finished_at_ms,
            elapsed_ms=snapshot["elapsed_ms"],
            overtime_ms=snapshot["overtime_ms"],
        )

    live_files = []
    if room.live_files_enabled:
        live_files = [
            FileResponse.model_validate(f)
            for f in room.files
            if f.upload_type in ["common", "speaker"]
        ]

    return TimerStateResponse(
        room_id=room.id,
        version=snapshot["version"],
        running=snapshot["running"],
        awaiting_decision=snapshot["awaiting_decision"],
        stop_reason=snapshot["stop_reason"],
        current_index=snapshot["current_index"],
        current_speaker_id=snapshot["current_speaker_id"],
        current_speaker=cur_sp_resp,
        elapsed_ms=snapshot["elapsed_ms"],
        remaining_ms=snapshot["remaining_ms"],
        overtime_ms=snapshot["overtime_ms"],
        limit_ms=snapshot["limit_ms"],
        total_speakers=snapshot["total_speakers"],
        finished_speakers=snapshot["finished_speakers"],
        speakers=sp_responses,
        live_files=live_files,
        recording_status=snapshot["recording_status"],
    )


@router.get("/state")
def get_timer_state(
    room_id: int,
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    timer_service: Annotated[object, Depends(get_timer_service)],
    if_none_match: Annotated[str | None, Header()] = None,
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    snapshot = timer_service.get_snapshot(session, room)

    # استفاده از ETag جهت بهینه‌سازی پهنای باند و جلوگیری از کوئری‌های تکراری
    etag = (
        f'"{snapshot["version"]}_{snapshot["running"]}_{snapshot["awaiting_decision"]}_'
        f'{snapshot["current_speaker_id"]}_{snapshot["elapsed_ms"] // 1000}"'
    )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache, must-revalidate"

    if if_none_match and if_none_match == etag:
        response.status_code = 304
        return {}

    state_resp = _format_timer_state(room, snapshot)
    return {"ok": True, "state": state_resp}


@router.post("/action")
async def timer_action(
    room_id: int,
    payload: TimerActionRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    timer_service: Annotated[object, Depends(get_timer_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    snapshot = await timer_service.handle_action(
        session, room, payload.action, speaker_id=payload.speaker_id
    )
    state_resp = _format_timer_state(room, snapshot)
    return {"ok": True, "state": state_resp}
