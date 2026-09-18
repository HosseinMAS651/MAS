from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import (
    DUMMY_PASSWORD_HASH,
    clear_rate_limit,
    cleanup_expired_sessions,
    create_session,
    get_auth_context,
    hash_password,
    invalidate_session,
    normalize_username,
    password_needs_rehash,
    rate_limit_allow,
    require_csrf,
    verify_password,
    client_key,
    _bucket_hash,
)
from .config import Settings, load_settings
from .db import configure_sqlite, initialize_database, make_engine, session_factory
from .models import FileCleanupQueue, Room, RoomState, Speaker, SpeechFile, User
from .services import (
    GENDERS,
    ORDER_MODES,
    TIMING_MODES,
    apply_timer_action,
    collect_room_storage,
    enqueue_cleanup,
    now,
    ordered_speakers,
    process_cleanup_queue,
    room_speakers,
    state_snapshot,
    timer_for,
    persist_running_elapsed,
    release_room_storage,
    reserve_room_storage,
    validate_capacity,
    validate_room_name,
    validate_speaker_name,
    ensure_room_state,
)
from .storage import content_disposition, safe_storage_path, store_upload


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "mas_app" / "templates"
STATIC_DIR = BASE_DIR / "mas_app" / "static"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mas")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "microphone=(self)"
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if self.settings.env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    engine = make_engine(cfg)
    configure_sqlite(engine)
    SessionLocal = session_factory(engine)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    async def cleanup_worker():
        while True:
            await asyncio.sleep(300)
            try:
                with SessionLocal() as db:
                    process_cleanup_queue(db, cfg, limit=100)
            except Exception:
                logger.exception("storage cleanup worker failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(engine)
        cleanup_expired_sessions(SessionLocal)
        # Remove only temporary uploads left by an interrupted transaction.
        for path in cfg.storage_dir.glob(".upload-*.tmp"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("could not remove stale temp file: %s", path)
        task = asyncio.create_task(cleanup_worker())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            engine.dispose()

    app = FastAPI(title="ماس | مدیریت اتاق سخنرانی", lifespan=lifespan)
    app.state.settings = cfg
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.state.templates = templates
    app.add_middleware(SecurityHeadersMiddleware, settings=cfg)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def is_api(request: Request) -> bool:
        return request.url.path.startswith("/api/")

    def render(request: Request, name: str, context: dict, status_code: int = 200):
        return templates.TemplateResponse(request=request, name=name, context=context, status_code=status_code)

    def page_context(request: Request, user: User, *, active: str = "", flash: str = "") -> dict:
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        return {"request": request, "user": user, "csrf": ctx.csrf_token, "active": active, "flash": flash}

    def require_page_user(request: Request, *, require_profile: bool = True) -> User:
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        if require_profile and not ctx.user.profile_completed and request.url.path not in {"/profile"}:
            raise HTTPException(status_code=303, headers={"Location": "/profile?first=1"})
        return ctx.user

    def owned_room_id(request: Request, room_id: int, *, api: bool = False) -> tuple[User, Room]:
        ctx = get_auth_context(request, SessionLocal, cfg, api=api)
        if not ctx.user.profile_completed and not api:
            raise HTTPException(status_code=303, headers={"Location": "/profile?first=1"})
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            db.expunge(room)
            return ctx.user, room

    def make_cookie_response(response: Response, raw_token: str):
        response.set_cookie(
            "mas_session",
            raw_token,
            max_age=cfg.session_seconds,
            httponly=True,
            secure=cfg.cookie_secure,
            samesite="lax",
            path="/",
        )

    def validate_username(username: str) -> str:
        username = normalize_username(username)
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
            raise HTTPException(400, "نام کاربری باید فقط شامل حروف انگلیسی، عدد و _ و بین ۳ تا ۳۲ کاراکتر باشد.")
        return username

    def validate_password(password: str) -> str:
        if len(password) < cfg.min_password_length:
            raise HTTPException(400, f"رمز عبور باید حداقل {cfg.min_password_length} کاراکتر باشد.")
        if len(password) > cfg.max_password_length:
            raise HTTPException(400, f"رمز عبور حداکثر {cfg.max_password_length} کاراکتر است.")
        return password

    def preflight_content_length(request: Request, limit_bytes: int) -> None:
        raw = request.headers.get("content-length")
        if not raw:
            return
        try:
            length = int(raw)
        except ValueError:
            raise HTTPException(400, "اندازهٔ درخواست نامعتبر است.")
        # Multipart framing and text fields need a small overhead budget.
        if length > limit_bytes + 5 * 1024 * 1024:
            raise HTTPException(413, "حجم کل درخواست بیش از حد مجاز است.")

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 303:
            return RedirectResponse(exc.headers.get("Location", "/login"), status_code=303)
        if is_api(request) or request.headers.get("Accept", "").find("application/json") >= 0:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        title = "خطا"
        if exc.status_code == 404:
            title = "پیدا نشد"
        elif exc.status_code == 403:
            title = "دسترسی غیرمجاز"
        elif exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        elif exc.status_code == 429:
            title = "تعداد درخواست زیاد است"
        return render(request, "error.html", {
            "title": title,
            "status_code": exc.status_code,
            "message": str(exc.detail),
            **({} if exc.status_code == 401 else {}),
        }, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        if is_api(request):
            return JSONResponse(status_code=422, content={"detail": "ورودی نامعتبر است.", "errors": exc.errors()})
        return render(request, "error.html", {"title": "ورودی نامعتبر", "status_code": 422, "message": "یکی از اطلاعات ارسالی معتبر نیست."}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
        if is_api(request):
            return JSONResponse(status_code=500, content={"detail": "خطای داخلی سرور."})
        return render(request, "error.html", {"title": "خطای داخلی", "status_code": 500, "message": "خطای داخلی رخ داد. دوباره تلاش کنید."}, 500)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if request.cookies.get("mas_session"):
            try:
                user = get_auth_context(request, SessionLocal, cfg, api=False).user
                return RedirectResponse("/" if user.profile_completed else "/profile?first=1", status_code=303)
            except HTTPException:
                pass
        return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": ""})

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...)):
        username = normalize_username(username)
        try:
            username = validate_username(username)
        except HTTPException as exc:
            return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": str(exc.detail)}, exc.status_code)
        try:
            password = validate_password(password)
        except HTTPException as exc:
            return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": str(exc.detail)}, exc.status_code)
        ip_key = _bucket_hash("login-ip", client_key(request))
        combo_key = _bucket_hash("login-combo", client_key(request), username)
        if not rate_limit_allow(SessionLocal, key=ip_key, max_count=cfg.login_max_failures * 4, window_seconds=cfg.login_window_seconds):
            return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "تعداد تلاش‌های ورود از این شبکه زیاد است. بعداً دوباره تلاش کنید."}, 429)
        if not rate_limit_allow(SessionLocal, key=combo_key, max_count=cfg.login_max_failures, window_seconds=cfg.login_window_seconds):
            return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "تلاش‌های ورود برای این نام کاربری زیاد است. بعداً دوباره تلاش کنید."}, 429)

        valid = False
        user_id = None
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username))
            password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
            valid, rounds = verify_password(password, password_hash)
            if valid and user:
                user_id = user.id
                if password_needs_rehash(rounds):
                    user.password_hash = hash_password(password)
                    db.commit()
        if not valid or user_id is None:
            return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "نام کاربری یا رمز عبور اشتباه است."}, 401)

        clear_rate_limit(SessionLocal, combo_key)
        clear_rate_limit(SessionLocal, ip_key)
        cleanup_expired_sessions(SessionLocal)
        raw, _sid, _csrf = create_session(user_id, SessionLocal, cfg)
        with SessionLocal() as db:
            user = db.get(User, user_id)
        response = RedirectResponse("/" if user.profile_completed else "/profile?first=1", status_code=303)
        make_cookie_response(response, raw)
        return response

    @app.get("/register", response_class=HTMLResponse)
    def register_page(request: Request):
        return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": ""})

    @app.post("/register")
    def register(request: Request, username: str = Form(...), password: str = Form(...), password2: str = Form(...)):
        if not rate_limit_allow(SessionLocal, key=_bucket_hash("register", client_key(request)), max_count=cfg.register_max_attempts, window_seconds=cfg.register_window_seconds):
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "تعداد تلاش‌های ثبت‌نام زیاد است. بعداً دوباره تلاش کنید."}, 429)
        try:
            username = validate_username(username)
            password = validate_password(password)
            validate_password(password2)
        except HTTPException as exc:
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": str(exc.detail)}, exc.status_code)
        if password != password2:
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "رمزها یکسان نیستند."}, 400)

        user_id = None
        try:
            with SessionLocal() as db:
                user = User(username=username, password_hash=hash_password(password), created_at=now(), profile_completed=False)
                db.add(user)
                db.commit()
                db.refresh(user)
                user_id = user.id
        except IntegrityError:
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "این نام کاربری قبلاً ثبت شده است."}, 409)

        raw, _sid, _csrf = create_session(user_id, SessionLocal, cfg)
        response = RedirectResponse("/profile?first=1", status_code=303)
        make_cookie_response(response, raw)
        return response

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        invalidate_session(request, SessionLocal, cfg)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("mas_session", path="/")
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        user = require_page_user(request)
        with SessionLocal() as db:
            rooms = db.scalars(select(Room).where(Room.owner_id == user.id).order_by(Room.id.desc())).all()
            recording_count = db.scalar(
                select(func.count(SpeechFile.id)).join(Room).where(Room.owner_id == user.id, SpeechFile.upload_type == "recording")
            ) or 0
        total_capacity = sum(room.capacity for room in rooms)
        return render(request, "home.html", {**page_context(request, user, active="home"), "title": "ماس | خانه", "rooms": rooms, "total_capacity": total_capacity, "recordings_count": recording_count})

    @app.get("/profile", response_class=HTMLResponse)
    def profile(request: Request):
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        first = request.query_params.get("first") == "1" or not ctx.user.profile_completed
        return render(request, "profile.html", {**page_context(request, ctx.user, active="profile"), "title": "ماس | پروفایل", "first": first})

    @app.post("/profile")
    def profile_save(request: Request, csrf: str = Form(...), account_name: str = Form(...), age: int = Form(...), job: str = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        account_name = account_name.strip()
        job = job.strip()
        if not account_name or len(account_name) > 120 or not job or len(job) > 120 or not 1 <= age <= 120:
            raise HTTPException(400, "اطلاعات پروفایل نامعتبر است.")
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        with SessionLocal() as db:
            user = db.get(User, ctx.user.id)
            user.account_name = account_name
            user.age = age
            user.job = job
            user.profile_completed = True
            db.commit()
        return RedirectResponse("/", status_code=303)

    @app.get("/rooms", response_class=HTMLResponse)
    def rooms(request: Request):
        user = require_page_user(request)
        with SessionLocal() as db:
            room_list = db.scalars(select(Room).where(Room.owner_id == user.id).order_by(Room.id.desc())).all()
        return render(request, "rooms.html", {**page_context(request, user, active="rooms"), "title": "ماس | اتاق‌ها", "rooms": room_list})

    @app.get("/rooms/new", response_class=HTMLResponse)
    def new_room(request: Request):
        user = require_page_user(request)
        return render(request, "new_room.html", {**page_context(request, user, active="rooms"), "title": "ماس | ایجاد اتاق"})

    @app.post("/rooms/new")
    def new_room_save(request: Request, csrf: str = Form(...), name: str = Form(...), capacity: int = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        user = require_page_user(request)
        name = validate_room_name(name)
        validate_capacity(capacity, 1, cfg.max_room_capacity)
        with SessionLocal() as db:
            room = Room(
                owner_id=user.id,
                name=name,
                capacity=capacity,
                recording_enabled=False,
                live_files_enabled=False,
                timing_mode="global",
                global_seconds=300,
                order_mode="manual",
                version=1,
                created_at=now(),
            )
            db.add(room)
            db.flush()
            for i in range(capacity):
                db.add(Speaker(room_id=room.id, name="", order_index=i, speaking_seconds=300))
            db.add(RoomState(room_id=room.id, updated_at=now(), version=1))
            db.commit()
            room_id = room.id
        return RedirectResponse(f"/rooms/{room_id}", status_code=303)

    @app.get("/rooms/{room_id}/edit", response_class=HTMLResponse)
    def edit_room(request: Request, room_id: int):
        user, room = owned_room_id(request, room_id)
        return render(request, "edit_room.html", {**page_context(request, user, active="rooms"), "title": "ماس | ویرایش اتاق", "room": room})

    @app.post("/rooms/{room_id}/edit")
    def edit_room_save(request: Request, room_id: int, csrf: str = Form(...), name: str = Form(...), capacity: int = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        user, _ = owned_room_id(request, room_id)
        name = validate_room_name(name)
        validate_capacity(capacity, 1, cfg.max_room_capacity)
        removed_storage: list[str] = []
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            old = room.capacity
            room.name = name
            room.capacity = capacity
            if capacity > old:
                for i in range(old, capacity):
                    db.add(Speaker(room_id=room.id, name="", order_index=i, speaking_seconds=room.global_seconds))
            elif capacity < old:
                extra = db.scalars(select(Speaker).where(Speaker.room_id == room.id, Speaker.order_index >= capacity)).all()
                removed_bytes = 0
                for speaker in extra:
                    removed_storage.extend(f.storage_name for f in speaker.files)
                    removed_bytes += sum(f.size_bytes for f in speaker.files)
                    db.delete(speaker)
                release_room_storage(db, room.id, removed_bytes)
                enqueue_cleanup(db, removed_storage)

            state = ensure_room_state(db, room.id)
            remaining = room_speakers(db, room.id, named_only=True)
            if state.current_speaker_id not in {s.id for s in remaining}:
                state.current_speaker_id = remaining[0].id if remaining else None
                state.current_index = 0
                state.running = False
                state.started_at = None
            db.commit()
        with SessionLocal() as db:
            process_cleanup_queue(db, cfg, limit=100)
        return RedirectResponse(f"/rooms/{room_id}", status_code=303)

    @app.post("/rooms/{room_id}/delete")
    def delete_room(request: Request, room_id: int, csrf: str = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        user, _ = owned_room_id(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            files = collect_room_storage(db, room.id)
            enqueue_cleanup(db, files)
            db.delete(room)
            db.commit()
        with SessionLocal() as db:
            process_cleanup_queue(db, cfg, limit=200)
        return RedirectResponse("/rooms", status_code=303)

    @app.get("/rooms/{room_id}", response_class=HTMLResponse)
    def room_page(request: Request, room_id: int):
        user, room_obj = owned_room_id(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(
                select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == user.id)
            )
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            speakers = list(sorted(room.speakers, key=lambda s: (s.order_index, s.id)))
            common_files = [f for f in room.files if f.upload_type == "common"]
        return render(request, "room.html", {**page_context(request, user, active="room"), "title": f"ماس | {room.name}", "room": room, "speakers": speakers, "common_files": common_files})

    @app.post("/rooms/{room_id}/save")
    async def save_room(request: Request, room_id: int):
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        if not ctx.user.profile_completed:
            raise HTTPException(303, headers={"Location": "/profile?first=1"})
        preflight_content_length(request, cfg.max_total_upload_bytes)
        async with request.form(
            max_files=cfg.max_files_per_request,
            max_fields=max(800, cfg.max_room_capacity * 7 + 50),
            max_part_size=cfg.max_upload_bytes,
        ) as form:
            require_csrf(request, str(form.get("csrf", "")), SessionLocal, cfg)
            newly_stored: list[str] = []
            total_new_bytes = 0
            try:
                mode = str(form.get("timing_mode", "global"))
                if mode not in TIMING_MODES:
                    raise HTTPException(400, "حالت زمان‌بندی نامعتبر است.")
                try:
                    global_min = int(str(form.get("global_min", "5")))
                except ValueError:
                    raise HTTPException(400, "زمان همگانی نامعتبر است.")
                if not 1 <= global_min <= 1440:
                    raise HTTPException(400, "زمان همگانی باید بین ۱ تا ۱۴۴۰ دقیقه باشد.")
                order_mode = str(form.get("order_mode", "manual"))
                if order_mode not in ORDER_MODES:
                    raise HTTPException(400, "حالت ترتیب نامعتبر است.")
                room_name = validate_room_name(str(form.get("room_name", "")))

                with SessionLocal() as db:
                    room = db.scalar(
                        select(Room).options(selectinload(Room.speakers), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == ctx.user.id)
                    )
                    if not room:
                        raise HTTPException(404, "اتاق پیدا نشد.")

                    state = ensure_room_state(db, room.id)
                    speakers = sorted(room.speakers, key=lambda s: (s.order_index, s.id))
                    old_current_id = state.current_speaker_id
                    old_current = next((s for s in speakers if s.id == old_current_id and s.name), None)
                    if state.running and old_current is not None:
                        old_limit = room.global_seconds if room.timing_mode == "global" else (old_current.speaking_seconds or room.global_seconds)
                        old_timer = timer_for(db, room.id, old_current.id)
                        persist_running_elapsed(state, old_timer, old_limit)

                    room.name = room_name
                    room.recording_enabled = bool(form.get("recording"))
                    room.live_files_enabled = bool(form.get("live_files"))
                    room.timing_mode = mode
                    room.global_seconds = global_min * 60
                    room.order_mode = order_mode

                    speaker_ids = {s.id for s in speakers}
                    for speaker in speakers:
                        speaker.name = validate_speaker_name(str(form.get(f"name_{speaker.id}", "")))
                        gender = str(form.get(f"gender_{speaker.id}", ""))
                        speaker.gender = gender if gender in GENDERS else ""
                        raw_age = str(form.get(f"age_{speaker.id}", "")).strip()
                        speaker.age = int(raw_age) if raw_age.isdigit() and 1 <= int(raw_age) <= 120 else None
                        description = str(form.get(f"desc_{speaker.id}", ""))
                        if len(description) > 1000:
                            raise HTTPException(400, "توضیحات هر سخنران حداکثر ۱۰۰۰ کاراکتر است.")
                        speaker.description = description
                        raw_time = str(form.get(f"time_{speaker.id}", "5")).strip()
                        if not raw_time.isdigit() or not 1 <= int(raw_time) <= 1440:
                            raise HTTPException(400, "زمان اختصاصی سخنران باید بین ۱ تا ۱۴۴۰ دقیقه باشد.")
                        # Keep the individual time even while global mode is selected.
                        speaker.speaking_seconds = int(raw_time) * 60

                    uploaded_count = 0
                    upload_items: list[tuple[UploadFile, int | None, str]] = []
                    for speaker in speakers:
                        for item in form.getlist(f"file_{speaker.id}"):
                            if isinstance(item, StarletteUploadFile) and item.filename:
                                upload_items.append((item, speaker.id, "speaker"))
                    for item in form.getlist("common_files"):
                        if isinstance(item, StarletteUploadFile) and item.filename:
                            upload_items.append((item, None, "common"))

                    uploaded_count = len(upload_items)
                    if uploaded_count > cfg.max_files_per_request:
                        raise HTTPException(400, f"در هر ذخیره حداکثر {cfg.max_files_per_request} فایل مجاز است.")

                    for upload, speaker_id, upload_type in upload_items:
                        stored = await store_upload(upload, cfg, request_bytes_used=total_new_bytes)
                        newly_stored.append(stored.storage_name)
                        total_new_bytes += stored.size_bytes
                        reserve_room_storage(db, room.id, stored.size_bytes, cfg.max_room_storage_bytes)
                        db.add(
                            SpeechFile(
                                room_id=room.id,
                                speaker_id=speaker_id,
                                filename=stored.original_name,
                                storage_name=stored.storage_name,
                                content_type=stored.content_type,
                                size_bytes=stored.size_bytes,
                                upload_type=upload_type,
                                created_at=now(),
                            )
                        )

                    # Preserve the current speaker by ID, independent of ordering mode.
                    current_named = {s.id for s in speakers if s.name}
                    if old_current_id not in current_named:
                        state.running = False
                        state.started_at = None
                        old_current_id = None

                    manual_raw = str(form.get("manual_order", ""))
                    manual_ids = []
                    for raw in manual_raw.split(","):
                        raw = raw.strip()
                        if raw.isdigit() and int(raw) in speaker_ids:
                            manual_ids.append(int(raw))
                    ordered = ordered_speakers(speakers, order_mode, manual_ids)
                    # Two-phase renumbering avoids transient UNIQUE(room_id, order_index) collisions.
                    for index, speaker in enumerate(speakers):
                        speaker.order_index = -(index + 1)
                    db.flush()
                    for index, speaker in enumerate(ordered):
                        speaker.order_index = index
                    db.flush()

                    named_after = [s for s in ordered if s.name]
                    if old_current_id and old_current_id in {s.id for s in named_after}:
                        state.current_speaker_id = old_current_id
                        state.current_index = next(i for i, s in enumerate(named_after) if s.id == old_current_id)
                    else:
                        state.current_speaker_id = named_after[0].id if named_after else None
                        state.current_index = 0
                        state.running = False
                        state.started_at = None
                    state.updated_at = now()
                    room.version += 1
                    db.commit()

                return RedirectResponse(f"/rooms/{room_id}", status_code=303)
            except StaleDataError:
                for storage_name in newly_stored:
                    try:
                        safe_storage_path(cfg, storage_name).unlink(missing_ok=True)
                    except OSError:
                        pass
                raise HTTPException(409, "این اتاق همزمان در جای دیگری تغییر کرده است. ابتدا صفحه را تازه کنید و دوباره ذخیره کنید.")
            except Exception:
                for storage_name in newly_stored:
                    try:
                        safe_storage_path(cfg, storage_name).unlink(missing_ok=True)
                    except OSError:
                        pass
                raise

    @app.get("/rooms/{room_id}/play", response_class=HTMLResponse)
    def play(request: Request, room_id: int):
        user, room_obj = owned_room_id(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            speakers = [s for s in sorted(room.speakers, key=lambda s: (s.order_index, s.id)) if s.name]
            common = [f for f in room.files if f.upload_type == "common"]
            recordings = [f for f in room.files if f.upload_type == "recording"]
            page_data = {
                "room_id": room.id,
                "room": room.name,
                "timing_mode": room.timing_mode,
                "global_seconds": room.global_seconds,
                "live_files": room.live_files_enabled,
                "recording": room.recording_enabled,
                "max_recording_seconds": cfg.max_recording_seconds,
                "csrf": get_auth_context(request, SessionLocal, cfg, api=False).csrf_token,
                "speakers": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "seconds": room.global_seconds if room.timing_mode == "global" else s.speaking_seconds,
                        "gender": s.gender,
                        "age": s.age,
                        "description": s.description,
                        "files": [{"id": f.id, "name": f.filename} for f in s.files],
                    }
                    for s in speakers
                ],
                "common": [{"id": f.id, "name": f.filename} for f in common],
                "recordings": [{"id": f.id, "name": f.filename} for f in recordings],
            }
        return render(request, "play.html", {**page_context(request, user, active="play"), "title": f"ماس | پخش {room.name}", "room": room, "page_data": page_data})

    @app.get("/api/rooms/{room_id}/state")
    def api_state(request: Request, room_id: int):
        ctx = get_auth_context(request, SessionLocal, cfg, api=True)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            # GET /state is read-only; it does not create timer rows or commit state changes.
            snapshot = state_snapshot(db, room)
            return JSONResponse(snapshot)

    @app.post("/api/rooms/{room_id}/recording")
    async def save_recording(request: Request, room_id: int):
        ctx = get_auth_context(request, SessionLocal, cfg, api=True)
        preflight_content_length(request, cfg.max_upload_bytes)
        try:
            async with request.form(max_files=2, max_fields=8, max_part_size=cfg.max_upload_bytes) as form:
                csrf = str(form.get("csrf", ""))
                require_csrf(request, csrf, SessionLocal, cfg)
                raw_duration = str(form.get("duration_seconds", "0")).strip()
                try:
                    duration_seconds = int(raw_duration)
                except ValueError:
                    raise HTTPException(400, "مدت ضبط نامعتبر است.")
                if duration_seconds < 0 or duration_seconds > cfg.max_recording_seconds:
                    raise HTTPException(400, "مدت ضبط نامعتبر است.")
                file = form.get("file")
                if not isinstance(file, StarletteUploadFile) or not file.filename:
                    raise HTTPException(400, "فایل ضبط ارسال نشده است.")

                with SessionLocal() as db:
                    room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
                    if not room:
                        raise HTTPException(404, "اتاق پیدا نشد.")
                    if not room.recording_enabled:
                        raise HTTPException(403, "ضبط برای این اتاق فعال نیست.")

                stored = None
                try:
                    stored = await store_upload(file, cfg, request_bytes_used=0)
                    with SessionLocal() as db:
                        room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
                        if not room or not room.recording_enabled:
                            raise HTTPException(403, "ضبط برای این اتاق فعال نیست.")
                        reserve_room_storage(db, room.id, stored.size_bytes, cfg.max_room_storage_bytes)
                        recording_type = stored.content_type
                        if Path(stored.original_name).suffix.lower() == ".webm":
                            recording_type = "audio/webm"
                        elif Path(stored.original_name).suffix.lower() == ".ogg":
                            recording_type = "audio/ogg"
                        db.add(
                            SpeechFile(
                                room_id=room_id, speaker_id=None, filename=stored.original_name,
                                storage_name=stored.storage_name, content_type=recording_type,
                                size_bytes=stored.size_bytes, upload_type="recording",
                                duration_seconds=duration_seconds, created_at=now(),
                            )
                        )
                        db.commit()
                    return JSONResponse({"ok": True})
                except Exception:
                    if stored:
                        safe_storage_path(cfg, stored.storage_name).unlink(missing_ok=True)
                    raise
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/rooms/{room_id}/{action}")
    def playback_control(request: Request, room_id: int, action: str, csrf: str = Form(...)):
        ctx = get_auth_context(request, SessionLocal, cfg, api=True)
        require_csrf(request, csrf, SessionLocal, cfg)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            result = apply_timer_action(db, room, action)
            return JSONResponse(result)

    @app.get("/recordings", response_class=HTMLResponse)
    def recordings(request: Request, room_id: int | None = None):
        user = require_page_user(request)
        with SessionLocal() as db:
            stmt = select(SpeechFile, Room.name).join(Room).where(Room.owner_id == user.id, SpeechFile.upload_type == "recording").order_by(SpeechFile.id.desc())
            if room_id is not None:
                stmt = stmt.where(SpeechFile.room_id == room_id)
            rows = db.execute(stmt).all()
        def human_size(n: int) -> str:
            units = [(1024**3, "GB"), (1024**2, "MB"), (1024, "KB")]
            for base, label in units:
                if n >= base:
                    return f"{n / base:.1f} {label}"
            return f"{n} B"
        def human_time(ts: int) -> str:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        items = []
        for file_obj, room_name in rows:
            items.append({
                "id": file_obj.id,
                "room_name": room_name,
                "filename": file_obj.filename,
                "size_label": human_size(file_obj.size_bytes),
                "created_label": human_time(file_obj.created_at),
            })
        return render(request, "recordings.html", {**page_context(request, user, active="recordings"), "title": "ماس | فایل‌های ضبط‌شده", "recordings": items})

    @app.post("/files/{file_id}/delete")
    def delete_file(request: Request, file_id: int, csrf: str = Form(...)):
        ctx = get_auth_context(request, SessionLocal, cfg, api=True)
        require_csrf(request, csrf, SessionLocal, cfg)
        with SessionLocal() as db:
            file_obj = db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id == file_id, Room.owner_id == ctx.user.id))
            if not file_obj:
                raise HTTPException(404, "فایل پیدا نشد.")
            storage_name = file_obj.storage_name
            file_size = file_obj.size_bytes
            release_room_storage(db, file_obj.room_id, file_size)
            db.add(FileCleanupQueue(storage_name=storage_name, attempts=0, next_attempt_at=now(), created_at=now()))
            db.delete(file_obj)
            db.commit()
        with SessionLocal() as db:
            process_cleanup_queue(db, cfg, limit=10)
        return JSONResponse({"ok": True})

    def _file_response(request: Request, file_id: int, *, download: bool):
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        with SessionLocal() as db:
            file_obj = db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id == file_id, Room.owner_id == ctx.user.id))
            if not file_obj:
                raise HTTPException(404, "فایل پیدا نشد.")
            path = safe_storage_path(cfg, file_obj.storage_name)
            if not path.exists() or not path.is_file():
                raise HTTPException(404, "فایل روی سرور وجود ندارد.")
            disposition = content_disposition(file_obj.filename, "attachment" if download else "inline")
            return FileResponse(
                path,
                filename=None,
                media_type=file_obj.content_type,
                headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
            )

    @app.get("/files/{file_id}")
    def get_file(request: Request, file_id: int):
        return _file_response(request, file_id, download=False)

    @app.get("/files/{file_id}/download")
    def download_file(request: Request, file_id: int):
        return _file_response(request, file_id, download=True)

    @app.get("/health")
    def health():
        with SessionLocal() as db:
            db.execute(select(1))
        writable = False
        probe = cfg.storage_dir / f".health-{time.time_ns()}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            writable = True
        except OSError:
            writable = False
        if not writable:
            return JSONResponse(status_code=503, content={"status": "degraded", "database": "ok", "storage_writable": False})
        return {"status": "ok", "database": "ok", "storage_writable": True}

    return app


app = create_app()
