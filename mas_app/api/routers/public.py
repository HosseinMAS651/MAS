"""مسیریاب اتاق تماشاگران عمومی (بدون نیاز به لاگین)."""

from __future__ import annotations

import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ForbiddenError, NotFoundError
from ...db.models import SpeechFile
from ...schemas.file import FileResponse
from ...schemas.public import PublicRoomStateResponse
from ...schemas.speaker import SpeakerResponse
from ..deps import (
    get_db,
    get_room_service,
    get_storage_backend,
    get_timer_service,
)

router = APIRouter(prefix="/api/public/{token}", tags=["public"])


@router.get("/state")
def get_public_state(
    token: str,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    timer_service: Annotated[object, Depends(get_timer_service)],
    if_none_match: Annotated[str | None, Header()] = None,
) -> dict:
    room = room_service.get_room_by_public_token(session, token)
    snapshot = timer_service.get_snapshot(session, room)

    etag = (
        f'"{snapshot["version"]}_{snapshot["running"]}_{snapshot["awaiting_decision"]}_'
        f'{snapshot["current_speaker_id"]}_{snapshot["elapsed_ms"] // 1000}"'
    )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache, must-revalidate"

    if if_none_match and if_none_match == etag:
        response.status_code = 304
        return {}

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

    public_state = PublicRoomStateResponse(
        room_name=room.name,
        public_enabled=room.public_enabled,
        running=snapshot["running"],
        awaiting_decision=snapshot["awaiting_decision"],
        current_index=snapshot["current_index"],
        current_speaker=cur_sp_resp,
        elapsed_ms=snapshot["elapsed_ms"],
        remaining_ms=snapshot["remaining_ms"],
        overtime_ms=snapshot["overtime_ms"],
        limit_ms=snapshot["limit_ms"],
        total_speakers=snapshot["total_speakers"],
        finished_speakers=snapshot["finished_speakers"],
        speakers=sp_responses,
        live_files=live_files,
    )
    return {"ok": True, "state": public_state}


@router.get("/files/{file_id}")
async def get_public_file(
    token: str,
    file_id: int,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    storage: Annotated[object, Depends(get_storage_backend)],
) -> Response:
    room = room_service.get_room_by_public_token(session, token)
    if not room.live_files_enabled:
        raise ForbiddenError("نمایش فایل‌های زنده در این اتاق مجاز نیست.")

    file = session.execute(
        select(SpeechFile).where(
            SpeechFile.id == file_id,
            SpeechFile.room_id == room.id,
            SpeechFile.upload_type.in_(["common", "speaker"]),
        )
    ).scalar_one_or_none()
    if not file:
        raise NotFoundError("فایل مورد نظر یافت نشد.")

    presigned = storage.get_presigned_download_url(file.storage_key, file.filename)
    if presigned:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(presigned, status_code=303)

    quoted_filename = urllib.parse.quote(file.filename)
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{quoted_filename}",
        "Content-Length": str(file.size_bytes),
    }
    stream = storage.open_stream(file.storage_key)
    return StreamingResponse(stream, media_type=file.content_type, headers=headers)


@router.get("/qr")
def get_public_qr(
    token: str,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
) -> Response:
    room = room_service.get_room_by_public_token(session, token)
    base_url = room_service.settings.public_base_url or str(request.base_url).rstrip("/")
    public_url = f"{base_url}/public/{room.public_token}"
    svg_data = room_service.generate_qr_svg(public_url)
    return Response(content=svg_data, media_type="image/svg+xml")
