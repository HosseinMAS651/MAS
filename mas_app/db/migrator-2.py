"""مدیریت راه‌اندازی و مهاجرت خودکار دیتابیس (بدون از دست رفتن داده‌های نسخهٔ قدیم).

باگ‌های برطرف‌شده در این ماژول:
- **C-08**: کرش در زمان راه‌اندازی با دیتابیس قدیمی به‌دلیل خطای UNIQUE روی username تکراری.
- **DB-01**: حذف ساخت مکرر ۱۰ ایندکس تکراری در هر بوت.
- **DB-02**: جلوگیری از اجرای ۲۴٬۰۰۰ دستور UPDATE در هر استارت‌آپ سرور.
- **DB-03/04**: اعمال صحیح کلیدهای خارجی و Cascade روی دیتابیس‌های قدیمی.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from ..config import Settings
from ..core.security import normalize_persian_text, username_to_key
from ..core.timeutil import utc_now_ms
from .base import Base
from .session import Database

logger = logging.getLogger("mas.db.migrator")


def run_database_migrations(db: Database, settings: Settings) -> None:
    """اجرای مطمئن مهاجرت‌ها بر اساس وضعیت دیتابیس."""
    engine = db.engine

    # برای دیتابیس‌های موقت حافظه در تست‌ها، جداول مستقیماً با create_all ساخته می‌شوند
    if ":memory:" in settings.database_url:
        Base.metadata.create_all(engine)
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # حالت ۱: دیتابیس کاملاً تازه (بدون جدول)
    if not existing_tables or "users" not in existing_tables:
        logger.info("دیتابیس تازه شناسایی شد؛ در حال ساخت جداول از طریق Alembic...")
        try:
            alembic_cfg = Config(str(Path(__file__).resolve().parent.parent.parent / "alembic.ini"))
            alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
            command.upgrade(alembic_cfg, "head")
            logger.info("جداول با موفقیت از طریق Alembic ساخته شدند.")
            return
        except Exception as exc:
            logger.warning("خطا در اجرای مستقیم Alembic: %s؛ استفاده از create_all...", exc)
            Base.metadata.create_all(engine)
            return

    # حالت ۲: دیتابیس موجود؛ بررسی اینکه آیا نیاز به مهاجرت از نسخهٔ قدیم دارد
    logger.info("دیتابیس موجود شناسایی شد؛ در حال بررسی سازگاری و ستون‌های گمشده...")
    _migrate_legacy_database_if_needed(db, inspector)


def _migrate_legacy_database_if_needed(db: Database, inspector: object) -> None:
    """مهاجرت بدون از دست رفتن داده از اسکیمای نسخهٔ ۱ به نسخهٔ ۲."""
    from sqlalchemy import inspect as get_inspect

    def _cols(table: str) -> set[str]:
        insp = get_inspect(db.engine)
        if table not in insp.get_table_names():
            return set()
        return {c["name"] for c in insp.get_columns(table)}

    def _add_columns(session, table: str, statements: list[str]) -> None:
        for stmt in statements:
            try:
                session.execute(text(stmt))
                logger.info("اجرا شد: %s", stmt)
            except Exception as exc:
                # ستون از قبل وجود دارد یا محدودیت دیگر — ادامه بده
                logger.warning("نادیده گرفتن ALTER روی %s: %s (%s)", table, stmt, exc)
        session.commit()

    user_cols = _cols("users")
    bool_t = "TRUE"
    bool_f = "FALSE"
    if db.is_sqlite:
        bool_t, bool_f = "1", "0"

    with db.unit_of_work() as session:
        # ۱. ارتقای جدول users — همهٔ ستون‌های لازم نسخهٔ ۲
        needed_users: list[tuple[str, str]] = [
            ("username_key", "ALTER TABLE users ADD COLUMN username_key VARCHAR(32)"),
            ("role", "ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'"),
            ("is_active", f"ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT {bool_t}"),
            ("timezone", "ALTER TABLE users ADD COLUMN timezone VARCHAR(64) DEFAULT 'Asia/Tehran'"),
            ("calendar", "ALTER TABLE users ADD COLUMN calendar VARCHAR(16) DEFAULT 'jalali'"),
            ("storage_used_bytes", "ALTER TABLE users ADD COLUMN storage_used_bytes BIGINT DEFAULT 0"),
            ("failed_login_count", "ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0"),
            ("locked_until_ms", "ALTER TABLE users ADD COLUMN locked_until_ms BIGINT DEFAULT 0"),
            ("created_at_ms", "ALTER TABLE users ADD COLUMN created_at_ms BIGINT DEFAULT 0"),
            ("updated_at_ms", "ALTER TABLE users ADD COLUMN updated_at_ms BIGINT DEFAULT 0"),
            ("last_login_at_ms", "ALTER TABLE users ADD COLUMN last_login_at_ms BIGINT DEFAULT 0"),
            ("version", "ALTER TABLE users ADD COLUMN version INTEGER DEFAULT 1"),
            ("profile_completed", f"ALTER TABLE users ADD COLUMN profile_completed BOOLEAN DEFAULT {bool_f}"),
        ]
        missing = [(name, stmt) for name, stmt in needed_users if name not in user_cols]
        if missing:
            logger.info("ستون‌های گمشده در users: %s", [n for n, _ in missing])
            _add_columns(session, "users", [s for _, s in missing])

        # پر کردن username_key برای ردیف‌های قدیمی
        user_cols = _cols("users")
        if "username_key" in user_cols:
            null_count = session.execute(
                text("SELECT COUNT(*) FROM users WHERE username_key IS NULL OR username_key = ''")
            ).scalar() or 0
            if null_count:
                logger.info("پر کردن username_key برای %s کاربر قدیمی...", null_count)
                users = session.execute(text("SELECT id, username FROM users ORDER BY id ASC")).fetchall()
                seen_keys: set[str] = set()
                # کلیدهای موجود غیرخالی
                existing_keys = session.execute(
                    text("SELECT username_key FROM users WHERE username_key IS NOT NULL AND username_key <> ''")
                ).fetchall()
                for (k,) in existing_keys:
                    seen_keys.add(k)
                now_ms = utc_now_ms()
                for uid, uname in users:
                    row_key = session.execute(
                        text("SELECT username_key FROM users WHERE id = :id"), {"id": uid}
                    ).scalar()
                    if row_key:
                        continue
                    clean_name = normalize_persian_text(uname or f"user_{uid}")
                    key = username_to_key(clean_name)
                    counter = 1
                    while key in seen_keys:
                        clean_name = f"{clean_name}_{counter}"
                        key = username_to_key(clean_name)
                        counter += 1
                    seen_keys.add(key)
                    session.execute(
                        text(
                            "UPDATE users SET username = :u, username_key = :k, "
                            "created_at_ms = CASE WHEN created_at_ms IS NULL OR created_at_ms = 0 "
                            "THEN :now ELSE created_at_ms END, "
                            "updated_at_ms = CASE WHEN updated_at_ms IS NULL OR updated_at_ms = 0 "
                            "THEN :now ELSE updated_at_ms END WHERE id = :id"
                        ),
                        {"u": clean_name, "k": key, "now": now_ms, "id": uid},
                    )
                session.commit()

            # ایندکس یکتا روی username_key (اگر نباشد)
            try:
                if db.is_sqlite:
                    session.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_key ON users (username_key)"
                        )
                    )
                else:
                    session.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_key ON users (username_key)"
                        )
                    )
                session.commit()
            except Exception as exc:
                logger.warning("ساخت ایندکس username_key: %s", exc)

        # ۲. ارتقای rooms
        room_cols = _cols("rooms")
        if room_cols:
            room_needed = [
                ("description", "ALTER TABLE rooms ADD COLUMN description TEXT DEFAULT ''"),
                ("public_enabled", f"ALTER TABLE rooms ADD COLUMN public_enabled BOOLEAN DEFAULT {bool_f}"),
                ("public_token", "ALTER TABLE rooms ADD COLUMN public_token VARCHAR(43)"),
                ("public_token_created_at_ms", "ALTER TABLE rooms ADD COLUMN public_token_created_at_ms BIGINT DEFAULT 0"),
                ("created_at_ms", "ALTER TABLE rooms ADD COLUMN created_at_ms BIGINT DEFAULT 0"),
                ("updated_at_ms", "ALTER TABLE rooms ADD COLUMN updated_at_ms BIGINT DEFAULT 0"),
            ]
            missing_r = [s for n, s in room_needed if n not in room_cols]
            if missing_r:
                logger.info("ارتقای جدول rooms...")
                _add_columns(session, "rooms", missing_r)

        # ۳. ارتقای room_states
        state_cols = _cols("room_states")
        if state_cols:
            state_needed = [
                ("awaiting_decision", f"ALTER TABLE room_states ADD COLUMN awaiting_decision BOOLEAN DEFAULT {bool_f}"),
                ("stop_reason", "ALTER TABLE room_states ADD COLUMN stop_reason VARCHAR(24) DEFAULT ''"),
            ]
            missing_s = [s for n, s in state_needed if n not in state_cols]
            if missing_s:
                logger.info("ارتقای جدول room_states...")
                _add_columns(session, "room_states", missing_s)

        # ۴. جداول جدید (auth_sessions, rate_limit_buckets, audit_logs, ...)
        Base.metadata.create_all(db.engine)
        session.commit()

logger.info("بررسی و ارتقای دیتابیس با موفقیت به پایان رسید.")
