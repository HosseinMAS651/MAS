"""برنامهٔ اصلی FastAPI با میان‌افزارهای امنیتی، مدیریت خطاها و سرویس‌دهی SPA."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from .api.routers.admin import router as admin_router
from .api.routers.auth import router as auth_router
from .api.routers.health import router as health_router
from .api.routers.public import router as public_router
from .api.routers.recording import router as recording_router
from .api.routers.rooms import router as rooms_router
from .api.routers.speakers import router as speakers_router
from .api.routers.timer import router as timer_router
from .config import Settings, get_settings
from .core.errors import AppError
from .db.migrator import run_database_migrations
from .db.session import Database
from .services.cleanup_service import CleanupService
from .storage.factory import create_storage

logger = logging.getLogger("mas")

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """افزودن هدرهای امنیتی به کلیهٔ پاسخ‌های سرور."""

    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.settings = settings

    async def dispatch(self, request: Request, call_next: object) -> Response:  # type: ignore[override]
        response = await call_next(request)  # type: ignore[misc]

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"

        # سیاست محتوای امن (CSP)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' blob: https:; "
            "connect-src 'self' blob: https:; "
            "font-src 'self' data:; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp

        if self.settings.is_production and self.settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # جلوگیری از افشای نوع سرور
        if "server" in response.headers:
            del response.headers["server"]

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """چرخهٔ عمر برنامه: اجرای مهاجرت‌ها، آماده‌سازی ذخیره‌سازی و ورکر پس‌زمینه."""
    settings: Settings = app.state.settings
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))

    logger.info("در حال راه‌اندازی MAS در محیط %s...", settings.env)

    database = Database(settings)
    app.state.database = database
    app.state.storage = create_storage(settings)

    # ۱. اجرای مهاجرت‌های دیتابیس
    if settings.run_migrations_on_startup:
        run_database_migrations(database, settings)

    # ۲. ایجاد پوشه ذخیره‌سازی محلی
    if settings.storage_backend == "local":
        settings.resolved_storage_dir.mkdir(parents=True, exist_ok=True)

    # ۳. ورکر پس‌زمینه برای پاک‌سازی صف فایل‌ها و ضبط‌های متروکه
    cleanup_task = None
    if settings.maintenance_enabled:

        async def _background_maintenance():
            cleanup_svc = CleanupService(settings, app.state.storage)
            while True:
                try:
                    await asyncio.sleep(settings.maintenance_interval_seconds)
                    with database.session() as s:
                        await cleanup_svc.process_queue(s, limit=settings.cleanup_queue_batch)
                        await cleanup_svc.clean_abandoned_recordings(s)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("خطا در ورکر پس‌زمینه نگهداری: %s", exc)

        cleanup_task = asyncio.create_task(_background_maintenance())

    yield

    # خروج تمیز
    if cleanup_task:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task

    database.dispose()
    logger.info("خاموش‌سازی MAS با موفقیت انجام شد.")


def create_app(settings: Settings | None = None) -> FastAPI:
    current_settings = settings or get_settings()

    app = FastAPI(
        title="MAS Platform API",
        version="2.0.0",
        docs_url="/docs" if current_settings.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = current_settings

    # میان‌افزارهای امنیتی
    app.add_middleware(SecurityHeadersMiddleware, settings=current_settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not current_settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── مدیریت یکپارچهٔ خطاها با پاسخ فارسی استاندارد (رفع BE-07/08/09) ──
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first_err = exc.errors()[0] if exc.errors() else {}
        loc = " -> ".join(str(x) for x in first_err.get("loc", []))
        msg = first_err.get("msg", "ورودی نامعتبر است.")
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"اطلاعات ارسالی نامعتبر است: {msg}",
                    "details": {"field": loc, "errors": exc.errors()},
                },
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        msg = exc.detail if isinstance(exc.detail, str) else "درخواست نامعتبر است."
        if exc.status_code == 404:
            msg = "صفحه یا منبع مورد نظر یافت نشد."
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": msg,
                    "details": {},
                },
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("خطای غیرمنتظره سرور در %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "خطای داخلی سرور رخ داده است. لطفاً بعداً تلاش کنید.",
                    "details": {},
                },
            },
        )

    # اتصال روترهای API
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(rooms_router)
    app.include_router(speakers_router)
    app.include_router(timer_router)
    app.include_router(recording_router)
    app.include_router(public_router)
    app.include_router(admin_router)

    # سرویس‌دهی فرانت‌اند SPA (Assets و Fallback به index.html)
    if FRONTEND_DIST_DIR.exists():
        assets_dir = FRONTEND_DIST_DIR / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir), html=False),
                name="assets",
            )

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            fav = FRONTEND_DIST_DIR / "favicon.ico"
            if fav.exists():
                return FileResponse(fav)
            return Response(status_code=204)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # اگر درخواستی به مسیرهای api یا health ارسال شد و route پیدا نشد، به fallback نرود
            if full_path.startswith("api/") or full_path == "health":
                return JSONResponse(
                    status_code=404,
                    content={
                        "ok": False,
                        "error": {
                            "code": "NOT_FOUND",
                            "message": "آدرس مورد نظر یافت نشد.",
                            "details": {},
                        },
                    },
                )
            target = FRONTEND_DIST_DIR / full_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(FRONTEND_DIST_DIR / "index.html")

    return app


app = create_app()
