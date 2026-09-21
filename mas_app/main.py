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
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import (
    DUMMY_PASSWORD_HASH,
    clear_rate_limit,
    cleanup_expired_sessions,
    create_session,
    get_auth_context,
    hash_password,
    invalidate_session,
    invalidate_user_sessions,
    new_guest_csrf,
    normalize_username,
    password_needs_rehash,
    rate_limit_allow,
    require_csrf,
    require_guest_csrf,
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
    collect_speaker_storage,
    enqueue_cleanup,
    now,
    now_ms,
    ordered_speakers,
    goto_speaker,
    process_cleanup_queue,
    release_room_storage,
    reserve_room_storage,
    state_snapshot,
    timer_for,
    timer_limit_ms,
    validate_capacity,
    validate_room_name,
    validate_speaker_name,
    ensure_room_state,
)
from .storage import (
    ALLOWED_EXTENSIONS,
    RECORDING_EXTENSIONS,
    content_disposition,
    reconcile_orphans,
    safe_storage_path,
    safe_filename,
    store_upload,
    validate_recording_type,
)

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
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
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

    async def maintenance_worker():
        interval = 300
        while True:
            await asyncio.sleep(interval)
            try:
                cleanup_expired_sessions(SessionLocal)
                with SessionLocal() as db:
                    process_cleanup_queue(db, cfg, limit=100)
                    referenced = set(db.scalars(select(SpeechFile.storage_name)).all())
                reconcile_orphans(cfg, referenced, cfg.storage_orphan_grace_seconds)
            except Exception:
                logger.exception("maintenance worker failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(engine)
        cleanup_expired_sessions(SessionLocal)
        try:
            with SessionLocal() as db:
                referenced = set(db.scalars(select(SpeechFile.storage_name)).all())
            reconcile_orphans(cfg, referenced, cfg.storage_orphan_grace_seconds)
            # Remove interrupted transaction temp files immediately.
            for path in cfg.storage_dir.glob(".upload-*.tmp"):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("could not remove stale temp file: %s", path)
        except Exception:
            logger.exception("startup storage reconciliation failed")
        task = asyncio.create_task(maintenance_worker())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            engine.dispose()

    app = FastAPI(title="ماس | مدیریت اتاق سخنرانی", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
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

    def page_context(request: Request, user: User, *, active: str = "", flash: str = "", error: str = "") -> dict:
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        return {"request": request, "user": user, "csrf": ctx.csrf_token, "active": active, "flash": flash, "error": error}

    def require_page_user(request: Request, *, require_profile: bool = True) -> User:
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        if require_profile and not ctx.user.profile_completed and request.url.path not in {"/profile"}:
            raise HTTPException(status_code=303, headers={"Location": "/profile?first=1"})
        return ctx.user

    def owned_room(request: Request, room_id: int, *, api: bool = False) -> tuple[User, Room]:
        ctx = get_auth_context(request, SessionLocal, cfg, api=api)
        if not ctx.user.profile_completed and not api:
            raise HTTPException(303, headers={"Location": "/profile?first=1"})
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            db.expunge(room)
            return ctx.user, room

    def make_cookie_response(response: Response, raw_token: str):
        response.set_cookie("mas_session", raw_token, max_age=cfg.session_seconds, httponly=True,
                            secure=cfg.cookie_secure, samesite="lax", path="/")

    def guest_token(request: Request) -> str:
        return request.cookies.get("mas_guest_csrf") or new_guest_csrf()

    def validate_username(username: str) -> str:
        username = normalize_username(username)
        if not re.fullmatch(rf"[A-Za-z0-9_]{{{cfg.min_username_length},{cfg.max_username_length}}}", username):
            raise HTTPException(400, f"نام کاربری باید فقط شامل حروف انگلیسی، عدد و _ و بین {cfg.min_username_length} تا {cfg.max_username_length} کاراکتر باشد.")
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
        if length > limit_bytes + 5 * 1024 * 1024:
            raise HTTPException(413, "حجم کل درخواست بیش از حد مجاز است.")

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 303:
            return RedirectResponse(exc.headers.get("Location", "/login"), status_code=303)
        if is_api(request) or "application/json" in request.headers.get("Accept", ""):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if exc.status_code == 401:
            return RedirectResponse("/login", status_code=303)
        title = {404: "پیدا نشد", 403: "دسترسی غیرمجاز", 429: "تعداد درخواست زیاد است"}.get(exc.status_code, "خطا")
        return render(request, "error.html", {"title": title, "status_code": exc.status_code, "message": str(exc.detail), "request": request}, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        if is_api(request):
            return JSONResponse(status_code=422, content={"detail": "ورودی نامعتبر است.", "errors": exc.errors()})
        return render(request, "error.html", {"title": "ورودی نامعتبر", "status_code": 422, "message": "یکی از اطلاعات ارسالی معتبر نیست.", "request": request}, 422)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled request error: %s %s", request.method, request.url.path)
        if is_api(request):
            return JSONResponse(status_code=500, content={"detail": "خطای داخلی سرور."})
        return render(request, "error.html", {"title": "خطای داخلی", "status_code": 500, "message": "خطای داخلی رخ داد. دوباره تلاش کنید.", "request": request}, 500)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        token = guest_token(request)
        if request.cookies.get("mas_session"):
            try:
                user = get_auth_context(request, SessionLocal, cfg, api=False).user
                resp = RedirectResponse("/" if user.profile_completed else "/profile?first=1", status_code=303)
            except HTTPException:
                resp = render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "", "guest_csrf": token})
        else:
            resp = render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "", "guest_csrf": token})
        resp.set_cookie("mas_guest_csrf", token, max_age=3600, httponly=False, secure=cfg.cookie_secure, samesite="lax", path="/")
        return resp

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), guest_csrf: str = Form(...)):
        require_guest_csrf(request, guest_csrf)
        token = request.cookies.get("mas_guest_csrf") or guest_csrf
        try:
            username = validate_username(username)
            password = validate_password(password)
        except HTTPException as exc:
            resp = render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": str(exc.detail), "guest_csrf": token}, exc.status_code)
            resp.set_cookie("mas_guest_csrf", token, max_age=3600, secure=cfg.cookie_secure, samesite="lax")
            return resp

        ip_key = _bucket_hash("login-ip", client_key(request))
        combo_key = _bucket_hash("login-combo", client_key(request), username)
        if not rate_limit_allow(SessionLocal, key=ip_key, max_count=cfg.login_max_failures * 4, window_seconds=cfg.login_window_seconds):
            resp = render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "تعداد تلاش‌های ورود از این شبکه زیاد است. بعداً دوباره تلاش کنید.", "guest_csrf": token}, 429)
            return resp
        if not rate_limit_allow(SessionLocal, key=combo_key, max_count=cfg.login_max_failures, window_seconds=cfg.login_window_seconds):
            resp = render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "تلاش‌های ورود برای این نام کاربری زیاد است. بعداً دوباره تلاش کنید.", "guest_csrf": token}, 429)
            return resp

        user_id = None
        valid = False
        rounds = 0
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
            return render(request, "login.html", {"title": "ورود به حساب کاربری", "subtitle": "ورود به مدیریت اتاق سخنرانی", "error": "نام کاربری یا رمز عبور اشتباه است.", "guest_csrf": token}, 401)

        clear_rate_limit(SessionLocal, combo_key)
        clear_rate_limit(SessionLocal, ip_key)
        cleanup_expired_sessions(SessionLocal)
        raw, _sid, _csrf = create_session(user_id, SessionLocal, cfg)
        with SessionLocal() as db:
            user = db.get(User, user_id)
        response = RedirectResponse("/" if user.profile_completed else "/profile?first=1", status_code=303)
        make_cookie_response(response, raw)
        response.delete_cookie("mas_guest_csrf", path="/")
        return response

    @app.get("/register", response_class=HTMLResponse)
    def register_page(request: Request):
        token = guest_token(request)
        response = render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "", "guest_csrf": token})
        response.set_cookie("mas_guest_csrf", token, max_age=3600, secure=cfg.cookie_secure, samesite="lax", path="/")
        return response

    @app.post("/register")
    def register(request: Request, username: str = Form(...), password: str = Form(...), password2: str = Form(...), guest_csrf: str = Form(...)):
        require_guest_csrf(request, guest_csrf)
        token = request.cookies.get("mas_guest_csrf") or guest_csrf
        if not rate_limit_allow(SessionLocal, key=_bucket_hash("register", client_key(request)), max_count=cfg.register_max_attempts, window_seconds=cfg.register_window_seconds):
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "تعداد تلاش‌های ثبت‌نام زیاد است. بعداً دوباره تلاش کنید.", "guest_csrf": token}, 429)
        try:
            username = validate_username(username)
            password = validate_password(password)
            validate_password(password2)
        except HTTPException as exc:
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": str(exc.detail), "guest_csrf": token}, exc.status_code)
        if password != password2:
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "رمزها یکسان نیستند.", "guest_csrf": token}, 400)
        try:
            with SessionLocal() as db:
                user = User(username=username, password_hash=hash_password(password), created_at=now(), profile_completed=False)
                db.add(user)
                db.commit()
                db.refresh(user)
                user_id = user.id
        except IntegrityError:
            return render(request, "register.html", {"title": "ایجاد حساب کاربری", "subtitle": "مرحله اول: ساخت نام کاربری و رمز عبور", "error": "این نام کاربری قبلاً ثبت شده است.", "guest_csrf": token}, 409)
        raw, _sid, _csrf = create_session(user_id, SessionLocal, cfg)
        response = RedirectResponse("/profile?first=1", status_code=303)
        make_cookie_response(response, raw)
        response.delete_cookie("mas_guest_csrf", path="/")
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
            recording_count = db.scalar(select(func.count(SpeechFile.id)).join(Room).where(Room.owner_id == user.id, SpeechFile.upload_type == "recording")) or 0
        return render(request, "home.html", {**page_context(request, user, active="home"), "title": "ماس | خانه", "rooms": rooms,
                                               "total_capacity": sum(max(0, room.capacity) for room in rooms), "recordings_count": recording_count})

    @app.get("/profile", response_class=HTMLResponse)
    def profile(request: Request):
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        first = request.query_params.get("first") == "1" or not ctx.user.profile_completed
        flash = "رمز عبور با موفقیت تغییر کرد." if request.query_params.get("password") == "changed" else ""
        return render(request, "profile.html", {**page_context(request, ctx.user, active="profile", flash=flash), "title": "ماس | پروفایل", "first": first, "password_error": ""})

    @app.post("/profile")
    def profile_save(request: Request, csrf: str = Form(...), account_name: str = Form(...), age: int = Form(...), job: str = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        account_name, job = account_name.strip(), job.strip()
        if not account_name or len(account_name) > 120 or not job or len(job) > 120 or not 1 <= age <= 120:
            raise HTTPException(400, "اطلاعات پروفایل نامعتبر است.")
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        with SessionLocal() as db:
            user = db.get(User, ctx.user.id)
            user.account_name, user.age, user.job, user.profile_completed = account_name, age, job, True
            db.commit()
        return RedirectResponse("/", status_code=303)

    @app.post("/profile/password")
    def password_change(request: Request, csrf: str = Form(...), current_password: str = Form(...), new_password: str = Form(...), new_password2: str = Form(...)):
        ctx = require_csrf(request, csrf, SessionLocal, cfg)
        try:
            new_password = validate_password(new_password)
            validate_password(new_password2)
        except HTTPException as exc:
            return render(request, "profile.html", {**page_context(request, ctx.user, active="profile"), "title": "ماس | پروفایل", "first": False,
                                                      "password_error": str(exc.detail)}, exc.status_code)
        with SessionLocal() as db:
            user = db.get(User, ctx.user.id)
            valid, _rounds = verify_password(current_password, user.password_hash)
            if not valid:
                return render(request, "profile.html", {**page_context(request, user, active="profile"), "title": "ماس | پروفایل", "first": False,
                                                          "password_error": "رمز عبور فعلی صحیح نیست."}, 400)
            if new_password != new_password2:
                return render(request, "profile.html", {**page_context(request, user, active="profile"), "title": "ماس | پروفایل", "first": False,
                                                          "password_error": "رمز عبور جدید و تکرار آن یکسان نیستند."}, 400)
            if hmac_compare(new_password, current_password):
                return render(request, "profile.html", {**page_context(request, user, active="profile"), "title": "ماس | پروفایل", "first": False,
                                                          "password_error": "رمز عبور جدید باید با رمز فعلی متفاوت باشد."}, 400)
            user.password_hash = hash_password(new_password)
            db.commit()
        invalidate_user_sessions(ctx.user.id, SessionLocal)
        raw, _sid, _csrf = create_session(ctx.user.id, SessionLocal, cfg)
        response = RedirectResponse("/profile?password=changed", status_code=303)
        make_cookie_response(response, raw)
        return response

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
        validate_capacity(capacity, cfg.min_room_capacity, cfg.max_room_capacity)
        with SessionLocal() as db:
            room = Room(owner_id=user.id, name=name, capacity=capacity, recording_enabled=False, live_files_enabled=False,
                        timing_mode="global", global_seconds=300, order_mode="manual", storage_used_bytes=0, version=1, created_at=now())
            db.add(room)
            db.flush()
            for i in range(capacity):
                db.add(Speaker(room_id=room.id, name="", order_index=i, speaking_seconds=300, is_finished=False))
            db.add(RoomState(room_id=room.id, updated_at=now(), version=1))
            db.commit()
            room_id = room.id
        return RedirectResponse(f"/rooms/{room_id}", status_code=303)

    @app.get("/rooms/{room_id}/edit", response_class=HTMLResponse)
    def edit_room(request: Request, room_id: int):
        user, room_obj = owned_room(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            speakers = sorted(room.speakers, key=lambda s: (s.order_index, s.id))
            common_files = [f for f in room.files if f.upload_type == "common"]
        return render(request, "edit_room.html", {**page_context(request, user, active="rooms"), "title": f"ماس | ویرایش {room.name}",
                                                    "room": room, "speakers": speakers, "common_files": common_files,
                                                    "genders": sorted(GENDERS), "timing_modes": TIMING_MODES, "order_modes": ORDER_MODES,
                                                    "csrf": get_auth_context(request, SessionLocal, cfg, api=False).csrf_token})

    @app.post("/rooms/{room_id}/edit")
    async def edit_room_save(request: Request, room_id: int):
        ctx = get_auth_context(request, SessionLocal, cfg, api=False)
        if not ctx.user.profile_completed:
            raise HTTPException(303, headers={"Location": "/profile?first=1"})
        preflight_content_length(request, cfg.max_total_upload_bytes)
        async with request.form(max_files=cfg.max_files_per_request, max_fields=max(1200, cfg.max_room_capacity * 8 + 100), max_part_size=cfg.max_upload_bytes) as form:
            require_csrf(request, str(form.get("csrf", "")), SessionLocal, cfg)
            newly_stored: list[str] = []
            total_new_bytes = 0
            try:
                timing_mode = str(form.get("timing_mode", "global"))
                order_mode = str(form.get("order_mode", "manual"))
                if timing_mode not in TIMING_MODES or order_mode not in ORDER_MODES:
                    raise HTTPException(400, "تنظیمات زمان‌بندی یا ترتیب نامعتبر است.")
                global_min = int(str(form.get("global_min", "5")))
                if not 1 <= global_min <= 1440:
                    raise HTTPException(400, "زمان همگانی باید بین ۱ تا ۱۴۴۰ دقیقه باشد.")
                room_name = validate_room_name(str(form.get("room_name", "")))
                try:
                    capacity = int(str(form.get("capacity", "0")))
                except ValueError:
                    raise HTTPException(400, "ظرفیت نامعتبر است.")
                if not 0 <= capacity <= cfg.max_room_capacity:
                    raise HTTPException(400, f"ظرفیت باید بین ۰ تا {cfg.max_room_capacity} باشد.")

                with SessionLocal() as db:
                    room = db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
                    if not room:
                        raise HTTPException(404, "اتاق پیدا نشد.")
                    state = ensure_room_state(db, room.id, lock=True)
                    speakers = sorted(list(room.speakers), key=lambda s: (s.order_index, s.id))
                    old_current_id = state.current_speaker_id

                    if state.running and old_current_id:
                        old_current = next((s for s in speakers if s.id == old_current_id), None)
                        if old_current:
                            t = timer_for(db, room.id, old_current.id, lock=True)
                            limit = timer_limit_ms(room, old_current)
                            from .services import persist_running_elapsed
                            persist_running_elapsed(state, t, limit)

                    # Shrinking capacity deletes the last slots by current order.
                    if capacity < len(speakers):
                        removed = speakers[capacity:]
                        for speaker in removed:
                            names, amount = collect_speaker_storage(db, speaker.id)
                            release_room_storage(db, room.id, amount)
                            enqueue_cleanup(db, names)
                            db.delete(speaker)
                        speakers = speakers[:capacity]

                    if capacity > len(speakers):
                        next_index = len(speakers)
                        for i in range(next_index, capacity):
                            speaker = Speaker(room_id=room.id, name="", order_index=i, speaking_seconds=global_min * 60,
                                              is_finished=False)
                            db.add(speaker)
                            speakers.append(speaker)
                        db.flush()

                    room.name = room_name
                    room.capacity = capacity
                    room.timing_mode = timing_mode
                    room.global_seconds = global_min * 60
                    room.order_mode = order_mode
                    room.recording_enabled = str(form.get("recording", "")) == "on"
                    room.live_files_enabled = str(form.get("live_files", "")) == "on"

                    for speaker in speakers:
                        sid = speaker.id
                        name = validate_speaker_name(str(form.get(f"name_{sid}", "")))
                        gender = str(form.get(f"gender_{sid}", ""))
                        if gender not in GENDERS:
                            gender = ""
                        age_raw = str(form.get(f"age_{sid}", "")).strip()
                        time_raw = str(form.get(f"time_{sid}", str(global_min))).strip()
                        try:
                            age = int(age_raw) if age_raw else None
                        except ValueError:
                            raise HTTPException(400, "سن یکی از سخنران‌ها نامعتبر است.")
                        try:
                            minutes = int(time_raw or global_min)
                        except ValueError:
                            raise HTTPException(400, "زمان یکی از سخنران‌ها نامعتبر است.")
                        if age is not None and not 1 <= age <= 120:
                            raise HTTPException(400, "سن سخنران باید بین ۱ تا ۱۲۰ باشد.")
                        if not 1 <= minutes <= 1440:
                            raise HTTPException(400, "زمان سخنرانی باید بین ۱ تا ۱۴۴۰ دقیقه باشد.")
                        desc = str(form.get(f"desc_{sid}", "")).strip()
                        if len(desc) > 4000:
                            raise HTTPException(400, "توضیحات سخنران بیش از حد طولانی است.")
                        speaker.name, speaker.gender, speaker.age, speaker.description = name, gender, age, desc
                        speaker.speaking_seconds = minutes * 60
                        if not name:
                            # A cleared slot cannot remain frozen.
                            speaker.is_finished = False
                            speaker.finished_at_ms = None

                    # Manual ordering uses ids in the client-created hidden field. Other modes are deterministic.
                    manual_ids = [int(x.strip()) for x in str(form.get("manual_order", "")).split(",") if x.strip().isdigit()]
                    ordered = ordered_speakers(speakers, order_mode, manual_ids)
                    for i, speaker in enumerate(speakers):
                        speaker.order_index = -(i + 1)
                    db.flush()
                    for i, speaker in enumerate(ordered):
                        speaker.order_index = i
                    db.flush()

                    named = [s for s in ordered if s.name]
                    current = next((s for s in named if s.id == old_current_id), None)
                    if current is None:
                        current = next((s for s in named if not s.is_finished), None) or (named[0] if named else None)
                        state.current_speaker_id = current.id if current else None
                        state.current_index = named.index(current) if current else 0
                        state.running = False
                        state.started_at_ms = None
                    else:
                        state.current_speaker_id = current.id
                        state.current_index = named.index(current)
                        if current.is_finished:
                            state.running = False
                            state.started_at_ms = None

                    # Newly uploaded common/speaker files.
                    upload_items = []
                    for key, value in form.multi_items():
                        if not hasattr(value, "filename") or not value.filename:
                            continue
                        if key == "common_files":
                            upload_items.append(("common", None, value))
                        elif key.startswith("speaker_files_"):
                            raw_sid = key.split("_", 2)[-1]
                            if raw_sid.isdigit() and any(s.id == int(raw_sid) for s in speakers):
                                upload_items.append(("speaker", int(raw_sid), value))
                    for upload_type, speaker_id, upload in upload_items:
                        try:
                            stored = await store_upload(upload, cfg, request_bytes_used=total_new_bytes, allowed_extensions=ALLOWED_EXTENSIONS)
                        except ValueError as exc:
                            raise HTTPException(400, str(exc)) from exc
                        newly_stored.append(stored.storage_name)
                        total_new_bytes += stored.size_bytes
                        reserve_room_storage(db, room.id, stored.size_bytes, cfg.max_room_storage_bytes)
                        db.add(SpeechFile(room_id=room.id, speaker_id=speaker_id, filename=stored.original_name,
                                         storage_name=stored.storage_name, content_type=stored.content_type, size_bytes=stored.size_bytes,
                                         upload_type=upload_type, created_at=now()))

                    db.flush()
                    db.commit()
                return RedirectResponse(f"/rooms/{room_id}", status_code=303)
            except (StaleDataError, IntegrityError) as exc:
                for storage_name in newly_stored:
                    try:
                        safe_storage_path(cfg, storage_name).unlink(missing_ok=True)
                    except OSError:
                        pass
                raise HTTPException(409, "این اتاق همزمان در جای دیگری تغییر کرده است. صفحه را تازه کنید و دوباره ذخیره کنید.") from exc
            except Exception:
                for storage_name in newly_stored:
                    try:
                        safe_storage_path(cfg, storage_name).unlink(missing_ok=True)
                    except OSError:
                        pass
                raise

    @app.post("/rooms/{room_id}/delete")
    def delete_room(request: Request, room_id: int, csrf: str = Form(...)):
        require_csrf(request, csrf, SessionLocal, cfg)
        user, _room = owned_room(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == user.id).with_for_update())
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
        user, _room = owned_room(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            speakers = sorted(room.speakers, key=lambda s: (s.order_index, s.id))
            common_files = [f for f in room.files if f.upload_type == "common"]
            state = db.scalar(select(RoomState).where(RoomState.room_id == room.id))
            return render(request, "room.html", {**page_context(request, user, active="room"), "title": f"ماس | {room.name}",
                                                   "room": room, "speakers": speakers, "common_files": common_files,
                                                   "state": state})

    @app.get("/rooms/{room_id}/play", response_class=HTMLResponse)
    def play(request: Request, room_id: int):
        user, _room = owned_room(request, room_id)
        with SessionLocal() as db:
            room = db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files), selectinload(Room.files)).where(Room.id == room_id, Room.owner_id == user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            speakers = [s for s in sorted(room.speakers, key=lambda s: (s.order_index, s.id)) if s.name]
            common = [f for f in room.files if f.upload_type == "common"]
            recordings = [f for f in room.files if f.upload_type == "recording"]
            state = state_snapshot(db, room)
            page_data = {
                "room_id": room.id, "room": room.name, "timing_mode": room.timing_mode, "global_seconds": room.global_seconds,
                "live_files": room.live_files_enabled, "recording": room.recording_enabled,
                "max_recording_seconds": cfg.max_recording_seconds, "max_upload_bytes": cfg.max_upload_bytes,
                "recording_bitrate_bps": cfg.recording_bitrate_bps,
                "csrf": get_auth_context(request, SessionLocal, cfg, api=False).csrf_token,
                "speakers": [{"id": s.id, "name": s.name, "seconds": room.global_seconds if room.timing_mode == "global" else s.speaking_seconds,
                              "gender": s.gender, "age": s.age, "description": s.description, "is_finished": bool(s.is_finished),
                              "files": [{"id": f.id, "name": f.filename} for f in s.files]} for s in speakers],
                "common": [{"id": f.id, "name": f.filename} for f in common],
                "recordings": [{"id": f.id, "name": f.filename} for f in recordings],
                "initial_state": state,
            }
        return render(request, "play.html", {**page_context(request, user, active="play"), "title": f"ماس | پخش {room.name}", "room": room, "page_data": page_data})

    @app.get("/api/rooms/{room_id}/state")
    def api_state(request: Request, room_id: int):
        ctx = get_auth_context(request, SessionLocal, cfg, api=True)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id))
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            return JSONResponse(state_snapshot(db, room))

    @app.post("/api/rooms/{room_id}/goto/{speaker_id}")
    def playback_goto(request: Request, room_id: int, speaker_id: int, csrf: str = Form(...)):
        ctx = require_csrf(request, csrf, SessionLocal, cfg)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            return JSONResponse(goto_speaker(db, room, speaker_id))

    @app.post("/api/rooms/{room_id}/recording")
    async def save_recording(request: Request, room_id: int):
        ctx = get_auth_context(request, SessionLocal, cfg, api=True)
        preflight_content_length(request, cfg.max_upload_bytes)
        stored = None
        try:
            async with request.form(max_files=2, max_fields=8, max_part_size=cfg.max_upload_bytes) as form:
                require_csrf(request, str(form.get("csrf", "")), SessionLocal, cfg)
                try:
                    duration = int(str(form.get("duration_seconds", "0")))
                except ValueError:
                    raise HTTPException(400, "مدت ضبط نامعتبر است.")
                if duration < 1 or duration > cfg.max_recording_seconds:
                    raise HTTPException(400, "مدت ضبط خارج از محدوده مجاز است.")
                with SessionLocal() as db:
                    room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
                    if not room:
                        raise HTTPException(404, "اتاق پیدا نشد.")
                    if not room.recording_enabled:
                        raise HTTPException(400, "ضبط صدا برای این اتاق فعال نیست.")
                    upload = form.get("file")
                    if not hasattr(upload, "filename") or not upload.filename:
                        raise HTTPException(400, "فایل ضبط‌شده ارسال نشده است.")
                    try:
                        validate_recording_type(upload)
                        stored = await store_upload(upload, cfg, allowed_extensions=RECORDING_EXTENSIONS, max_bytes=cfg.max_upload_bytes)
                    except ValueError as exc:
                        raise HTTPException(400, str(exc)) from exc
                    reserve_room_storage(db, room.id, stored.size_bytes, cfg.max_room_storage_bytes)
                    saved_file = SpeechFile(room_id=room.id, speaker_id=None, filename=stored.original_name, storage_name=stored.storage_name,
                                            content_type=stored.content_type, size_bytes=stored.size_bytes, upload_type="recording",
                                            duration_seconds=duration, created_at=now())
                    db.add(saved_file)
                    db.flush()
                    saved_payload = {"id": saved_file.id, "name": saved_file.filename}
                    db.commit()
            with SessionLocal() as db:
                process_cleanup_queue(db, cfg, limit=5)
            return JSONResponse({"ok": True, "file": saved_payload})
        except Exception:
            if stored:
                try:
                    safe_storage_path(cfg, stored.storage_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise


    @app.post("/api/rooms/{room_id}/{action}")
    def playback_control(request: Request, room_id: int, action: str, csrf: str = Form(...)):
        ctx = require_csrf(request, csrf, SessionLocal, cfg)
        with SessionLocal() as db:
            room = db.scalar(select(Room).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            result = apply_timer_action(db, room, action)
            return JSONResponse(result)

    @app.post("/api/rooms/{room_id}/speakers/{speaker_id}/delete")
    def delete_speaker(request: Request, room_id: int, speaker_id: int, csrf: str = Form(...)):
        ctx = require_csrf(request, csrf, SessionLocal, cfg)
        with SessionLocal() as db:
            room = db.scalar(select(Room).options(selectinload(Room.speakers).selectinload(Speaker.files)).where(Room.id == room_id, Room.owner_id == ctx.user.id).with_for_update())
            if not room:
                raise HTTPException(404, "اتاق پیدا نشد.")
            state = ensure_room_state(db, room.id, lock=True)
            speakers = sorted([s for s in room.speakers if s.name], key=lambda s: (s.order_index, s.id))
            target = next((s for s in speakers if s.id == speaker_id), None)
            if target is None:
                raise HTTPException(404, "سخنران پیدا نشد.")
            target_index = speakers.index(target)
            if state.current_speaker_id == target.id and state.running:
                timer = timer_for(db, room.id, target.id, lock=True)
                from .services import persist_running_elapsed
                persist_running_elapsed(state, timer, timer_limit_ms(room, target))
            names, amount = collect_speaker_storage(db, target.id)
            release_room_storage(db, room.id, amount)
            enqueue_cleanup(db, names)
            db.delete(target)
            room.capacity = max(0, int(room.capacity) - 1)
            remaining = [s for s in speakers if s.id != speaker_id]
            for i, speaker in enumerate(remaining):
                speaker.order_index = -(i + 1)
            db.flush()
            for i, speaker in enumerate(remaining):
                speaker.order_index = i
            # Current speaker deleted => automatically choose the next active speaker, then previous active if no next exists.
            if state.current_speaker_id == speaker_id:
                next_active = next((s for s in remaining[target_index:] if not s.is_finished), None)
                if next_active is None:
                    prev_active = next((s for s in reversed(remaining[:target_index]) if not s.is_finished), None)
                selected = next_active or prev_active
                state.current_speaker_id = selected.id if selected else None
                state.current_index = remaining.index(selected) if selected else 0
                state.running = False
                state.started_at_ms = None
                if selected:
                    t = timer_for(db, room.id, selected.id, lock=True)
                    lim = timer_limit_ms(room, selected)
                    state.elapsed_ms = t.elapsed_ms
                    state.overtime_ms = max(0, t.elapsed_ms - lim)
                    state.elapsed_seconds = t.elapsed_ms // 1000
                    state.overtime_seconds = state.overtime_ms // 1000
                else:
                    state.elapsed_ms = state.overtime_ms = state.elapsed_seconds = state.overtime_seconds = 0
            else:
                current = next((s for s in remaining if s.id == state.current_speaker_id and not s.is_finished), None)
                if current:
                    state.current_index = remaining.index(current)
                else:
                    selected = next((s for s in remaining if not s.is_finished), None)
                    state.current_speaker_id = selected.id if selected else None
                    state.current_index = remaining.index(selected) if selected else 0
                    state.running = False
                    state.started_at_ms = None
            state.updated_at = now()
            db.commit()
            result = state_snapshot(db, room)
        with SessionLocal() as cleanup_db:
            process_cleanup_queue(cleanup_db, cfg, limit=20)
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
            for base, label in ((1024**3, "GB"), (1024**2, "MB"), (1024, "KB")):
                if n >= base:
                    return f"{n / base:.1f} {label}"
            return f"{n} B"
        def human_time(ts: int) -> str:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        items = [{"id": f.id, "room_name": room_name, "filename": f.filename, "size_label": human_size(f.size_bytes), "created_label": human_time(f.created_at)} for f, room_name in rows]
        return render(request, "recordings.html", {**page_context(request, user, active="recordings"), "title": "ماس | فایل‌های ضبط‌شده", "recordings": items})

    @app.post("/files/{file_id}/delete")
    def delete_file(request: Request, file_id: int, csrf: str = Form(...)):
        ctx = require_csrf(request, csrf, SessionLocal, cfg)
        with SessionLocal() as db:
            file_obj = db.scalar(select(SpeechFile).join(Room).where(SpeechFile.id == file_id, Room.owner_id == ctx.user.id).with_for_update())
            if not file_obj:
                raise HTTPException(404, "فایل پیدا نشد.")
            storage_name, size = file_obj.storage_name, file_obj.size_bytes
            release_room_storage(db, file_obj.room_id, size)
            enqueue_cleanup(db, [storage_name])
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
            try:
                path = safe_storage_path(cfg, file_obj.storage_name)
            except ValueError:
                raise HTTPException(404, "فایل نامعتبر است.")
            if not path.exists() or not path.is_file():
                raise HTTPException(404, "فایل روی سرور وجود ندارد.")
            disposition = content_disposition(file_obj.filename, "attachment" if download else "inline")
            return FileResponse(path, filename=None, media_type=file_obj.content_type,
                                headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"})

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
            raise HTTPException(503, "فضای ذخیره‌سازی قابل نوشتن نیست.")
        return {"ok": True, "db": True, "storage": True}

    return app


def hmac_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


app = create_app()
