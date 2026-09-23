"""CSRF protection for cookie-authenticated state-changing API requests."""

from __future__ import annotations

from typing import Final

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.security import SecurityManager
from ..db.models import AuthSession

SAFE_METHODS: Final = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT_PATHS: Final = {"/api/auth/login", "/api/auth/register"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validate CSRF for browser-cookie authenticated mutation requests.

    Bearer-token API calls are exempt because the credential is not sent
    automatically by browsers. Login/register are exempt because they create the
    session and CSRF token.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        settings = request.app.state.settings
        if not getattr(settings, "csrf_protection_enabled", True):
            return await call_next(request)
        if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        session_token = request.cookies.get(settings.cookie_name)
        if not session_token:
            # Let the normal auth dependency return 401 where authentication is required.
            return await call_next(request)

        # A caller explicitly using a Bearer token is not exposed to cookie CSRF.
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer ") and not request.cookies.get(settings.cookie_name):
            return await call_next(request)

        csrf_token = request.headers.get("x-csrf-token", "").strip()
        if not csrf_token:
            return self._reject("CSRF_TOKEN_MISSING")

        database = request.app.state.database
        security = SecurityManager(settings)
        token_hash = security.hash_token(session_token)
        with database.session() as session:
            auth_session = session.query(AuthSession).filter(AuthSession.token_hash == token_hash).one_or_none()
            if not auth_session or not security.verify_csrf(csrf_token, auth_session.csrf_hash):
                return self._reject("CSRF_TOKEN_INVALID")

        return await call_next(request)

    @staticmethod
    def _reject(code: str) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": {
                    "code": code,
                    "message": "درخواست امنیتی معتبر نیست. لطفاً صفحه را تازه‌سازی کنید.",
                    "details": {},
                },
            },
        )
