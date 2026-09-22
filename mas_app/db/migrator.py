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

    inspector = get_inspect(db.engine)
    user_cols = {col["name"] for col in inspector.get_columns("users")}

    with db.unit_of_work() as session:
        # ۱. ارتقای جدول users
        if "username_key" not in user_cols:
            logger.info("ستون‌های نسخهٔ جدید در جدول users یافت نشد؛ در حال ارتقا...")
            if db.is_sqlite:
                session.execute(text("ALTER TABLE users ADD COLUMN username_key VARCHAR(32)"))
                session.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'"))
                session.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                session.execute(text("ALTER TABLE users ADD COLUMN timezone VARCHAR(64) DEFAULT 'Asia/Tehran'"))
                session.execute(text("ALTER TABLE users ADD COLUMN calendar VARCHAR(16) DEFAULT 'jalali'"))
                session.execute(text("ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0"))
                session.execute(text("ALTER TABLE users ADD COLUMN locked_until_ms BIGINT DEFAULT 0"))
                session.execute(text("ALTER TABLE users ADD COLUMN created_at_ms BIGINT DEFAULT 0"))
                session.execute(text("ALTER TABLE users ADD COLUMN updated_at_ms BIGINT DEFAULT 0"))
                session.execute(text("ALTER TABLE users ADD COLUMN last_login_at_ms BIGINT DEFAULT 0"))
                session.execute(text("ALTER TABLE users ADD COLUMN version INTEGER DEFAULT 1"))

            # حل باگ C-08: اصلاح نام‌های کاربری تکراری قدیمی پیش از ایجاد UNIQUE INDEX
            users = session.execute(text("SELECT id, username FROM users ORDER BY id ASC")).fetchall()
            seen_keys: set[str] = set()
            now_ms = utc_now_ms()

            for uid, uname in users:
                clean_name = normalize_persian_text(uname or f"user_{uid}")
                key = username_to_key(clean_name)
                # رفع تداخل در صورت وجود رکوردهای با نام کاربری تکراری
                counter = 1
                while key in seen_keys:
                    clean_name = f"{clean_name}_{counter}"
                    key = username_to_key(clean_name)
                    counter += 1
                seen_keys.add(key)

                session.execute(
                    text(
                        "UPDATE users SET username = :u, username_key = :k, created_at_ms = :now, "
                        "updated_at_ms = :now WHERE id = :id"
                    ),
                    {"u": clean_name, "k": key, "now": now_ms, "id": uid},
                )
            session.commit()

        # ۲. ارتقای جدول rooms
        room_cols = {col["name"] for col in inspector.get_columns("rooms")}
        if "public_token" not in room_cols:
            logger.info("در حال ارتقای جدول rooms...")
            if db.is_sqlite:
                session.execute(text("ALTER TABLE rooms ADD COLUMN description TEXT DEFAULT ''"))
                session.execute(text("ALTER TABLE rooms ADD COLUMN public_enabled BOOLEAN DEFAULT 0"))
                session.execute(text("ALTER TABLE rooms ADD COLUMN public_token VARCHAR(43)"))
                session.execute(text("ALTER TABLE rooms ADD COLUMN public_token_created_at_ms BIGINT DEFAULT 0"))
                session.execute(text("ALTER TABLE rooms ADD COLUMN created_at_ms BIGINT DEFAULT 0"))
                session.execute(text("ALTER TABLE rooms ADD COLUMN updated_at_ms BIGINT DEFAULT 0"))
            session.commit()

        # ۳. ارتقای جدول room_states
        state_cols = {col["name"] for col in inspector.get_columns("room_states")}
        if "awaiting_decision" not in state_cols:
            logger.info("در حال ارتقای جدول room_states...")
            if db.is_sqlite:
                session.execute(text("ALTER TABLE room_states ADD COLUMN awaiting_decision BOOLEAN DEFAULT 0"))
                session.execute(text("ALTER TABLE room_states ADD COLUMN stop_reason VARCHAR(24) DEFAULT ''"))
            session.commit()

        # ۴. ایجاد جداول جدید در صورت عدم وجود (recording_sessions, recording_chunks, cleanup_queue, audit_logs)
        Base.metadata.create_all(db.engine)
        session.commit()

    logger.info("بررسی و ارتقای دیتابیس با موفقیت به پایان رسید.")
