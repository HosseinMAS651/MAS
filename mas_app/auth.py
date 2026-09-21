from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from .config import Settings
from .models import AuthSession, RateLimitBucket, User

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ROUNDS = 310_000
DUMMY_PASSWORD_HASH = "pbkdf2_sha256$310000$00000000000000000000000000000000$" + ("00" * 32)
AUTH_FORM_COOKIE = "mas_auth_form"

@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: int
    csrf_token: str


def normalize_username(raw: str) -> str:
    return (raw or "").strip()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ROUNDS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> tuple[bool, int]:
    try:
        scheme, rounds_raw, salt_hex, digest_hex = encoded.split("$")
        if scheme != PASSWORD_SCHEME:
            return False, 0
        rounds = int(rounds_raw)
        if rounds <= 0 or len(salt_hex) % 2:
            return False, 0
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), rounds).hex()
        return hmac.compare_digest(candidate, digest_hex), rounds
    except (ValueError, TypeError):
        return False, 0


def password_needs_rehash(rounds: int) -> bool:
    return rounds < PASSWORD_ROUNDS


def token_digest(secret_key: str, raw_token: str) -> str:
    return hmac.new(secret_key.encode(), raw_token.encode(), hashlib.sha256).hexdigest()


def client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return host[:100]


def _bucket_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8", "ignore")).hexdigest()


def rate_limit_allow(session_factory, *, key: str, max_count: int, window_seconds: int) -> bool:
    now = time.time()
    with session_factory() as db:
        try:
            bucket = db.scalar(select(RateLimitBucket).where(RateLimitBucket.bucket_key == key).with_for_update())
            if bucket is None:
                db.add(RateLimitBucket(bucket_key=key, window_started_at=int(now), count=1))
                db.commit()
                return True
            if now - bucket.window_started_at >= window_seconds:
                bucket.window_started_at = int(now)
                bucket.count = 1
                db.commit()
                return True
            if bucket.count >= max_count:
                db.rollback()
                return False
            bucket.count += 1
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return True


def clear_rate_limit(session_factory, key: str) -> None:
    with session_factory() as db:
        db.execute(delete(RateLimitBucket).where(RateLimitBucket.bucket_key == key))
        db.commit()


def cleanup_expired_sessions(session_factory) -> None:
    now = int(time.time())
    with session_factory() as db:
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
        db.execute(delete(RateLimitBucket).where(RateLimitBucket.window_started_at < now - 86400))
        db.commit()


def create_session(user_id: int, session_factory, settings: Settings):
    raw = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    now = int(time.time())
    session = AuthSession(user_id=user_id, token_hash=token_digest(settings.secret_key, raw), csrf_token=csrf,
                          created_at=now, expires_at=now + settings.session_seconds, last_seen_at=now)
    with session_factory() as db:
        db.add(session)
        db.commit()
        db.refresh(session)
        return raw, session.id, csrf


def get_auth_context(request: Request, session_factory, settings: Settings, *, api: bool = False) -> AuthContext:
    raw = request.cookies.get("mas_session")
    if not raw:
        raise HTTPException(401 if api else 303, detail="جلسهٔ ورود وجود ندارد." if api else None,
                            headers={} if api else {"Location": "/login"})
    now = int(time.time())
    token = token_digest(settings.secret_key, raw)
    with session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token))
        if not session or session.expires_at <= now:
            if session:
                db.delete(session); db.commit()
            raise HTTPException(401 if api else 303, detail="جلسهٔ ورود منقضی شده است." if api else None,
                                headers={} if api else {"Location": "/login"})
        user = db.get(User, session.user_id)
        if not user:
            db.delete(session); db.commit()
            raise HTTPException(401 if api else 303, detail="کاربر پیدا نشد." if api else None,
                                headers={} if api else {"Location": "/login"})
        if now - session.last_seen_at >= 300:
            session.last_seen_at = now
            db.commit()
        db.expunge(user)
        return AuthContext(user=user, session_id=session.id, csrf_token=session.csrf_token)


def require_csrf(request: Request, token: str, session_factory, settings: Settings) -> None:
    ctx = get_auth_context(request, session_factory, settings, api=True)
    supplied = token or request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(ctx.csrf_token, supplied):
        raise HTTPException(403, "درخواست نامعتبر است.")


def issue_auth_form_token(response, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(AUTH_FORM_COOKIE, token, max_age=3600, httponly=False, secure=settings.cookie_secure, samesite="lax", path="/")
    return token


def require_auth_form(request: Request, token: str) -> None:
    stored = request.cookies.get(AUTH_FORM_COOKIE, "")
    if not stored or not token or not hmac.compare_digest(stored, token):
        raise HTTPException(403, "درخواست فرم ورود/ثبت‌نام نامعتبر است.")


def invalidate_session(request: Request, session_factory, settings: Settings) -> None:
    raw = request.cookies.get("mas_session")
    if not raw:
        return
    with session_factory() as db:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(settings.secret_key, raw)))
        db.commit()
