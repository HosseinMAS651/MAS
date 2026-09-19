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


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: int
    csrf_token: str


def normalize_username(raw: str) -> str:
    return (raw or "").strip()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> tuple[bool, int]:
    try:
        scheme, rounds_raw, salt_hex, digest_hex = encoded.split("$")
        if scheme != PASSWORD_SCHEME:
            return False, 0
        rounds = int(rounds_raw)
        if rounds <= 0 or len(salt_hex) % 2 != 0:
            return False, 0
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), rounds).hex()
        return hmac.compare_digest(candidate, digest_hex), rounds
    except (ValueError, TypeError):
        return False, 0


def password_needs_rehash(rounds: int) -> bool:
    return rounds < PASSWORD_ROUNDS


def token_digest(secret_key: str, raw_token: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return host[:100]


def _bucket_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8", "ignore")).hexdigest()


def rate_limit_allow(session_factory, *, key: str, max_count: int, window_seconds: int) -> bool:
    current = time.time()
    with session_factory() as db:
        try:
            with db.begin():
                bucket = db.scalar(select(RateLimitBucket).where(RateLimitBucket.bucket_key == key).with_for_update())
                if bucket is None:
                    db.add(RateLimitBucket(bucket_key=key, window_started_at=int(current), count=1))
                    return True
                if current - float(bucket.window_started_at) >= window_seconds:
                    bucket.window_started_at = int(current)
                    bucket.count = 1
                    return True
                if bucket.count >= max_count:
                    return False
                bucket.count += 1
                return True
        except IntegrityError:
            db.rollback()
            with session_factory() as retry_db:
                bucket = retry_db.scalar(select(RateLimitBucket).where(RateLimitBucket.bucket_key == key))
                if bucket is None:
                    return True
                if current - float(bucket.window_started_at) >= window_seconds:
                    bucket.window_started_at = int(current)
                    bucket.count = 1
                    retry_db.commit()
                    return True
                if bucket.count >= max_count:
                    return False
                bucket.count += 1
                retry_db.commit()
                return True


def clear_rate_limit(session_factory, key: str) -> None:
    with session_factory() as db:
        db.execute(delete(RateLimitBucket).where(RateLimitBucket.bucket_key == key))
        db.commit()


def create_session(user_id: int, session_factory, settings: Settings) -> tuple[str, int, str]:
    raw_token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    now = int(time.time())
    session = AuthSession(
        user_id=user_id,
        token_hash=token_digest(settings.secret_key, raw_token),
        csrf_token=csrf,
        created_at=now,
        expires_at=now + settings.session_seconds,
        last_seen_at=now,
    )
    with session_factory() as db:
        db.add(session)
        db.commit()
        db.refresh(session)
        return raw_token, session.id, csrf


def invalidate_session(request: Request, session_factory, settings: Settings) -> None:
    raw = request.cookies.get("mas_session")
    if not raw:
        return
    digest = token_digest(settings.secret_key, raw)
    with session_factory() as db:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == digest))
        db.commit()


def invalidate_user_sessions(user_id: int, session_factory) -> None:
    with session_factory() as db:
        db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
        db.commit()


def cleanup_expired_sessions(session_factory) -> None:
    current = int(time.time())
    with session_factory() as db:
        db.execute(delete(AuthSession).where(AuthSession.expires_at < current))
        db.execute(delete(RateLimitBucket).where(RateLimitBucket.window_started_at < current - 86400))
        db.commit()


def get_auth_context(request: Request, session_factory, settings: Settings, *, api: bool) -> AuthContext:
    raw = request.cookies.get("mas_session")
    if not raw:
        raise HTTPException(401, "وارد حساب کاربری شوید.")
    digest = token_digest(settings.secret_key, raw)
    now = int(time.time())
    with session_factory() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest))
        if not session or session.expires_at <= now:
            if session:
                db.delete(session)
                db.commit()
            raise HTTPException(401, "نشست شما منقضی شده است.")
        user = db.get(User, session.user_id)
        if not user:
            db.delete(session)
            db.commit()
            raise HTTPException(401, "نشست نامعتبر است.")
        if now - int(session.last_seen_at or 0) >= 60:
            session.last_seen_at = now
            db.commit()
        db.expunge(user)
        csrf = session.csrf_token
        session_id = session.id
    return AuthContext(user=user, session_id=session_id, csrf_token=csrf)


def require_csrf(request: Request, submitted: str, session_factory, settings: Settings) -> AuthContext:
    ctx = get_auth_context(request, session_factory, settings, api=True)
    if not submitted or not hmac.compare_digest(submitted, ctx.csrf_token):
        raise HTTPException(403, "درخواست امنیتی نامعتبر است. صفحه را تازه کنید.")
    return ctx


def new_guest_csrf() -> str:
    return secrets.token_urlsafe(32)


def require_guest_csrf(request: Request, submitted: str) -> None:
    cookie = request.cookies.get("mas_guest_csrf", "")
    if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
        raise HTTPException(403, "درخواست امنیتی نامعتبر است. صفحه را تازه کنید.")
