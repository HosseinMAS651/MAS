"""مسیریاب اتاق تماشاگران عمومی (بدون نیاز به لاگین)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import FileResponse as FastAPIFileResponse
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ForbiddenError, NotFoundError
from ...db.models import RoomState, SpeechFile
from ...schemas.file import FileResponse
from ...schemas.public import PublicRoomStateResponse
from ...schemas.speaker import SpeakerResponse
from ...services.rate_limiter import RateLimiter
from ...services.room_service import SAFE_MIME_BY_EXTENSION
from ..deps import (
    get_client_ip,
    get_db,
    get_room_service,
    get_storage_backend,
    get_timer_service,
)

router = APIRouter(prefix="/api/public/{token}", tags=["public"])

INLINE_SAFE_TYPES = {
    "application/pdf",
    "text/plain; charset=utf-8",
    "text/markdown; charset=utf-8",
    "text/csv; charset=utf-8",
}


def _public_content_type(file: SpeechFile) -> str:
    extension = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    return SAFE_MIME_BY_EXTENSION.get(extension, "application/octet-stream")


def _public_file_response(file: SpeechFile) -> FileResponse:
    response = FileResponse.model_validate(file)
    response.content_type = _public_content_type(file)
    return response


def _public_disposition(file: SpeechFile, content_type: str) -> str:
    safe_inline = (
        content_type in INLINE_SAFE_TYPES
        or content_type.startswith(("image/", "audio/", "video/"))
    )
    disposition = "inline" if safe_inline else "attachment"
    quoted = urllib.parse.quote(file.filename)
    return f"{disposition}; filename*=UTF-8''{quoted}"


@router.get("/state")
def get_public_state(
    token: str,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    timer_service: Annotated[object, Depends(get_timer_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
    if_none_match: Annotated[str | None, Header()] = None,
) -> dict:
    room = room_service.get_room_by_public_token(session, token)
    settings = room_service.settings
    snapshot = timer_service.get_snapshot(session, room)

    payload_for_etag = {
        "room_version": room.version, "state_version": snapshot["version"],
        "running": snapshot["running"], "awaiting": snapshot["awaiting_decision"],
        "current": snapshot["current_speaker_id"], "elapsed_s": snapshot["elapsed_ms"] // 1000,
        "overtime_s": snapshot["overtime_ms"] // 1000,
        "limit_ms": snapshot["limit_ms"],
        "speaker_mode_enabled": room.speaker_mode_enabled,
        "speaker_uploads_enabled": room.speaker_uploads_enabled,
        "speakers": [
            (
                speaker.id,
                speaker.order_index,
                speaker.is_finished,
                speaker.timer.elapsed_ms if speaker.timer else 0,
                speaker.timer.overtime_ms if speaker.timer else 0,
                speaker.updated_at_ms,
            )
            for speaker in snapshot["speakers"]
        ],
        "live_files_version": [
            (speech_file.id, speech_file.updated_at_ms)
            for speech_file in room.files
            if speech_file.upload_type in {"common", "speaker"}
            and speech_file.approval_status == "approved"
        ] if room.live_files_enabled else [],
    }
    etag_digest = hashlib.sha256(
        json.dumps(payload_for_etag, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    etag = f'"{etag_digest}"'
    cache_control = f"public, max-age={settings.public_state_max_age_seconds}, must-revalidate"
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = cache_control

    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})

    # Count only changed snapshots. Conditional polling shares no state/file/QR
    # bucket, which avoids one busy room exhausting unrelated public pages.
    RateLimiter.check_and_increment(
        session,
        f"public:room:{room.id}:state:ip:{client_ip}",
        action="public_state",
        max_attempts=settings.public_max_per_ip,
        window_seconds=settings.public_window_seconds,
    )

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
        current_sp_id = snapshot.get("current_speaker_id")
        live_files = [
            _public_file_response(f)
            for f in room.files
            if f.approval_status == "approved"
            and (
                f.upload_type == "common"
                or (
                    f.upload_type == "speaker"
                    and current_sp_id is not None
                    and f.speaker_id == current_sp_id
                )
            )
        ]

    public_state = PublicRoomStateResponse(
        room_name=room.name,
        public_enabled=room.public_enabled,
        speaker_mode_enabled=room.speaker_mode_enabled,
        speaker_uploads_enabled=room.speaker_uploads_enabled,
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
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> Response:
    """ارائهٔ فایل زنده به تماشاگر، با پشتیبانی درست از مرورگر و فایل اختصاصی سخنران."""
    room = room_service.get_room_by_public_token(session, token)
    if not room.live_files_enabled:
        raise ForbiddenError("نمایش فایل‌های زنده در این اتاق مجاز نیست.")

    RateLimiter.check_and_increment(
        session,
        f"public:room:{room.id}:file:ip:{client_ip}",
        action="public_file",
        max_attempts=room_service.settings.public_max_per_ip,
        window_seconds=room_service.settings.public_window_seconds,
    )

    file = session.execute(
        select(SpeechFile).where(
            SpeechFile.id == file_id,
            SpeechFile.room_id == room.id,
            SpeechFile.upload_type.in_(["common", "speaker"]),
            SpeechFile.approval_status == "approved",
        )
    ).scalar_one_or_none()
    if not file:
        raise NotFoundError("فایل مورد نظر یافت نشد.")

    # فایل اختصاصی فقط وقتی عمومی است که همان سخنران در حال اجرا باشد.
    if file.upload_type == "speaker":
        current_speaker_id = session.execute(
            select(RoomState.current_speaker_id).where(RoomState.room_id == room.id)
        ).scalar_one_or_none()
        if current_speaker_id != file.speaker_id:
            raise NotFoundError("فایل مورد نظر در حال حاضر برای تماشاگران قابل نمایش نیست.")

    content_type = _public_content_type(file)
    headers = {
        "Content-Disposition": _public_disposition(file, content_type),
        "Cache-Control": "no-store, max-age=0",
        "X-Content-Type-Options": "nosniff",
    }

    # LocalStorage را مستقیماً با FileResponse سرو می‌کنیم تا FastAPI/Starlette
    # وجود فایل، Content-Length و رفتار مرورگر برای فایل‌های PDF/تصویر/رسانه را
    # درست مدیریت کند. این مسیر همچنین خطای خام FileNotFoundError را به ۵۰۰ تبدیل نمی‌کند.
    local_path = storage.get_local_path(file.storage_key)
    if local_path is not None:
        if not local_path.is_file():
            raise NotFoundError("فایل روی سرور یافت نشد؛ ممکن است فایل فیزیکی حذف شده باشد.")
        return FastAPIFileResponse(
            path=str(local_path),
            media_type=content_type,
            headers=headers,
        )

    # پشتیبان برای storage backendهایی که local path ندارند.
    try:
        stream = await asyncio.to_thread(storage.open_stream, file.storage_key)
    except FileNotFoundError as exc:
        raise NotFoundError("فایل روی سرور یافت نشد.") from exc
    return StreamingResponse(stream, media_type=content_type, headers=headers)


@router.get("/qr")
def get_public_qr(
    token: str,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> Response:
    room = room_service.get_room_by_public_token(session, token)
    RateLimiter.check_and_increment(
        session,
        f"public:room:{room.id}:qr:ip:{client_ip}",
        action="public_qr",
        max_attempts=room_service.settings.public_max_per_ip,
        window_seconds=room_service.settings.public_window_seconds,
    )
    base_url = room_service.settings.public_base_url or str(request.base_url).rstrip("/")
    public_url = f"{base_url}/public/{room.public_token}"
    svg_data = room_service.generate_qr_svg(public_url)
    return Response(content=svg_data, media_type="image/svg+xml")


@router.post("/reactions")
def send_reaction(
    token: str,
    payload: dict,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    """ثبت واکنش آنلاین تماشاگر (Instagram Live style)."""
    room = room_service.get_room_by_public_token(session, token)
    from ...services.reaction_service import reaction_manager
    if not reaction_manager.is_enabled(room.id):
        raise ForbiddenError("ارسال واکنش برای این جلسه موقتاً غیرفعال است.")

    RateLimiter.check_and_increment(
        session,
        f"reaction:room:{room.id}:ip:{client_ip}",
        action="reaction_post",
        max_attempts=room_service.settings.reaction_max_per_minute,
        window_seconds=60,
    )
    emoji = str(payload.get("emoji", "heart")).strip()
    item = reaction_manager.add_reaction(room.id, emoji)
    return {"ok": True, "reaction": item}


@router.get("/reactions")
def get_recent_reactions(
    token: str,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    """دریافت واکنش‌های ثانیه‌های اخیر جهت انیمیشن شناور در نمای تماشاگر."""
    room = room_service.get_room_by_public_token(session, token)
    RateLimiter.check_and_increment(
        session,
        f"reaction-poll:room:{room.id}:ip:{client_ip}",
        action="reaction_poll",
        max_attempts=room_service.settings.reaction_poll_max_per_minute,
        window_seconds=60,
    )
    from ...services.reaction_service import reaction_manager
    items = reaction_manager.get_recent(room.id, since_seconds=3.0)
    return {
        "ok": True,
        "reactions_enabled": reaction_manager.is_enabled(room.id),
        "reactions": items,
        "totals": reaction_manager.get_totals(room.id),
    }


@router.get("/report/pdf")
def download_public_report_pdf(
    token: str,
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> Response:
    """دانلود نسخه PDF گزارش اتاق از دیدگاه تماشاگر."""
    room = room_service.get_room_by_public_token(session, token)
    RateLimiter.check_and_increment(
        session,
        f"public:room:{room.id}:report:ip:{client_ip}",
        action="public_report",
        max_attempts=room_service.settings.public_max_per_ip,
        window_seconds=room_service.settings.public_window_seconds,
    )
    from ...services.pdf_report_service import PdfReportService
    from ...services.reaction_service import reaction_manager
    totals = reaction_manager.get_totals(room.id)
    pdf_bytes = PdfReportService.generate_room_report(
        room, [], totals, include_files=room.live_files_enabled
    )

    filename = f"report-room-{room.id}.pdf"
    quoted = urllib.parse.quote(filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Cache-Control": "no-cache",
        },
    )
