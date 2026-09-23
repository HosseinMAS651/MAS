"""Database migration bootstrap for fresh, versioned and legacy MAS databases."""
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


def _alembic_config(settings: Settings) -> Config:
    cfg = Config(str(Path(__file__).resolve().parent.parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _table_columns(db: Database, table: str) -> set[str]:
    inspector = inspect(db.engine)
    return {c["name"] for c in inspector.get_columns(table)} if table in inspector.get_table_names() else set()


def _legacy_add_columns(db: Database) -> None:
    """Add missing columns to a legacy install before stamping the current baseline.

    This deliberately performs only additive, data-preserving changes. New tables
    and new indexes are created from the declarative metadata. Existing rows are
    normalized before the unique username key is created.
    """
    now_ms = utc_now_ms()
    bool_default = "1" if db.is_sqlite else "TRUE"
    specs: dict[str, list[tuple[str, str]]] = {
        "users": [
            ("username_key", "VARCHAR(32)"),
            ("account_name", "VARCHAR(120) DEFAULT ''"),
            ("age", "INTEGER"),
            ("job", "VARCHAR(120) DEFAULT ''"),
            ("profile_completed", f"BOOLEAN DEFAULT {bool_default}"),
            ("role", "VARCHAR(16) DEFAULT 'user'"),
            ("is_active", f"BOOLEAN DEFAULT {bool_default}"),
            ("timezone", "VARCHAR(64) DEFAULT 'Asia/Tehran'"),
            ("calendar", "VARCHAR(16) DEFAULT 'jalali'"),
            ("storage_used_bytes", "BIGINT DEFAULT 0"),
            ("failed_login_count", "INTEGER DEFAULT 0"),
            ("locked_until_ms", "BIGINT DEFAULT 0"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("updated_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("last_login_at_ms", "BIGINT DEFAULT 0"),
            ("version", "INTEGER DEFAULT 1"),
        ],
        "rooms": [
            ("description", "TEXT DEFAULT ''"),
            ("recording_enabled", f"BOOLEAN DEFAULT {bool_default}"),
            ("live_files_enabled", f"BOOLEAN DEFAULT {bool_default}"),
            ("public_enabled", f"BOOLEAN DEFAULT {bool_default}"),
            ("public_token", "VARCHAR(43)"),
            ("public_token_created_at_ms", "BIGINT DEFAULT 0"),
            ("timing_mode", "VARCHAR(16) DEFAULT 'global'"),
            ("global_seconds", "INTEGER DEFAULT 300"),
            ("order_mode", "VARCHAR(16) DEFAULT 'manual'"),
            ("storage_used_bytes", "BIGINT DEFAULT 0"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("updated_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("version", "INTEGER DEFAULT 1"),
        ],
        "room_states": [
            ("current_index", "INTEGER DEFAULT 0"),
            ("running", f"BOOLEAN DEFAULT {bool_default}"),
            ("awaiting_decision", f"BOOLEAN DEFAULT {bool_default}"),
            ("started_at_ms", "BIGINT DEFAULT 0"),
            ("overtime_ms", "BIGINT DEFAULT 0"),
            ("stop_reason", "VARCHAR(24) DEFAULT ''"),
            ("updated_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("version", "INTEGER DEFAULT 1"),
        ],
        "speakers": [
            ("gender", "VARCHAR(16) DEFAULT ''"),
            ("age", "INTEGER"),
            ("description", "TEXT DEFAULT ''"),
            ("speaking_seconds", "INTEGER DEFAULT 300"),
            ("is_finished", f"BOOLEAN DEFAULT {bool_default}"),
            ("finished_at_ms", "BIGINT DEFAULT 0"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("updated_at_ms", f"BIGINT DEFAULT {now_ms}"),
        ],
        "speech_files": [
            ("room_id", "INTEGER"),
            ("speaker_id", "INTEGER"),
            ("filename", "VARCHAR(255) DEFAULT 'file'"),
            ("storage_key", "VARCHAR(400)"),
            ("backend", "VARCHAR(16) DEFAULT 'local'"),
            ("content_type", "VARCHAR(120) DEFAULT 'application/octet-stream'"),
            ("size_bytes", "BIGINT DEFAULT 0"),
            ("upload_type", "VARCHAR(16) DEFAULT 'common'"),
            ("duration_ms", "BIGINT"),
            ("speaker_name", "VARCHAR(120) DEFAULT ''"),
            ("sha256", "VARCHAR(64) DEFAULT ''"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("updated_at_ms", f"BIGINT DEFAULT {now_ms}"),
        ],
        "auth_sessions": [
            ("csrf_hash", "VARCHAR(64) DEFAULT ''"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("expires_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("last_seen_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("ip", "VARCHAR(64) DEFAULT ''"),
            ("user_agent", "VARCHAR(255) DEFAULT ''"),
        ],
        "rate_limit_buckets": [
            ("action", "VARCHAR(32) DEFAULT ''"),
            ("count", "INTEGER DEFAULT 0"),
            ("window_started_at_ms", "BIGINT DEFAULT 0"),
            ("blocked_until_ms", "BIGINT DEFAULT 0"),
        ],
        "recording_sessions": [
            ("speaker_name", "VARCHAR(120) DEFAULT ''"),
            ("mime_type", "VARCHAR(60) DEFAULT 'audio/webm'"),
            ("chunk_seq", "INTEGER DEFAULT 0"),
            ("bytes_received", "BIGINT DEFAULT 0"),
            ("recorded_ms", "BIGINT DEFAULT 0"),
            ("active_since_ms", "BIGINT DEFAULT 0"),
            ("started_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("last_chunk_at_ms", "BIGINT DEFAULT 0"),
            ("ended_at_ms", "BIGINT DEFAULT 0"),
            ("final_file_id", "INTEGER"),
            ("error", "VARCHAR(255) DEFAULT ''"),
            ("version", "INTEGER DEFAULT 1"),
        ],
        "recording_chunks": [
            ("seq", "INTEGER DEFAULT 0"),
            ("storage_key", "VARCHAR(400)"),
            ("backend", "VARCHAR(16) DEFAULT 'local'"),
            ("size_bytes", "BIGINT DEFAULT 0"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
        ],
        "cleanup_queue": [
            ("backend", "VARCHAR(16) DEFAULT 'local'"),
            ("reason", "VARCHAR(32) DEFAULT ''"),
            ("attempts", "INTEGER DEFAULT 0"),
            ("next_attempt_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("last_error", "VARCHAR(255) DEFAULT ''"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
        ],
        "audit_logs": [
            ("actor_user_id", "INTEGER"),
            ("actor_username", "VARCHAR(32) DEFAULT ''"),
            ("action", "VARCHAR(48) DEFAULT ''"),
            ("severity", "VARCHAR(16) DEFAULT 'info'"),
            ("target_type", "VARCHAR(32) DEFAULT ''"),
            ("target_id", "VARCHAR(64) DEFAULT ''"),
            ("detail", "TEXT DEFAULT ''"),
            ("ip", "VARCHAR(64) DEFAULT ''"),
            ("user_agent", "VARCHAR(255) DEFAULT ''"),
            ("created_at_ms", f"BIGINT DEFAULT {now_ms}"),
        ],
        "speaker_timer_states": [
            ("elapsed_ms", "BIGINT DEFAULT 0"),
            ("overtime_ms", "BIGINT DEFAULT 0"),
            ("started_at_ms", "BIGINT DEFAULT 0"),
            ("updated_at_ms", f"BIGINT DEFAULT {now_ms}"),
            ("version", "INTEGER DEFAULT 1"),
        ],
    }

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if not tables:
        return

    with db.engine.begin() as conn:
        for table, columns in specs.items():
            if table not in tables:
                continue
            current = {c["name"] for c in inspect(db.engine).get_columns(table)}
            for name, sql_type in columns:
                if name not in current:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'))

    # Some old MAS databases retain columns that the v2 ORM no longer writes.
    # PostgreSQL still enforces NOT NULL on those columns, so make them nullable
    # before current inserts are attempted. Existing values are preserved.
    legacy_not_null_columns = {
        "users": ("created_at", "updated_at"),
        "auth_sessions": ("csrf_token",),
        "rate_limit_buckets": ("window_started_at", "blocked_until"),
    }
    with db.engine.begin() as conn:
        insp = inspect(db.engine)
        for table, legacy_names in legacy_not_null_columns.items():
            if table not in tables or db.is_sqlite:
                continue
            columns = {c["name"]: c for c in insp.get_columns(table)}
            for legacy_name in legacy_names:
                col = columns.get(legacy_name)
                if col and not col.get("nullable", True):
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table}" '
                            f'ALTER COLUMN "{legacy_name}" DROP NOT NULL'
                        )
                    )

    # Normalize legacy usernames and assign collision-free normalized keys.
    if "users" in tables:
        with db.engine.begin() as conn:
            rows = conn.execute(text("SELECT id, username, username_key FROM users ORDER BY id")).fetchall()
            used: set[str] = set()
            for row_id, username, current_key in rows:
                base_name = normalize_persian_text(username or f"user_{row_id}")[:32]
                key = username_to_key(base_name)
                candidate = key
                counter = 1
                while candidate in used or (current_key and candidate != current_key and candidate in used):
                    candidate = username_to_key(f"{base_name}_{counter}")
                    counter += 1
                used.add(candidate)
                conn.execute(
                    text("UPDATE users SET username=:username, username_key=:key WHERE id=:id"),
                    {"username": base_name, "key": candidate, "id": row_id},
                )

    # Create missing tables without changing existing legacy rows.
    Base.metadata.create_all(db.engine, checkfirst=True)

    # Safe post-conditions. We intentionally do not add potentially destructive
    # foreign-key constraints to an already-populated legacy table automatically.
    inspector = inspect(db.engine)
    required = set(Base.metadata.tables)
    missing = required - set(inspector.get_table_names())
    if missing:
        raise RuntimeError(f"مهاجرت legacy ناقص ماند؛ جداول گمشده: {', '.join(sorted(missing))}")

    if "users" in inspector.get_table_names():
        with db.engine.begin() as conn:
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_key_legacy ON users(username_key)"))
            except Exception as exc:
                raise RuntimeError("نام‌های کاربری legacy حتی پس از نرمال‌سازی یکتا نشدند.") from exc


def run_database_migrations(db: Database, settings: Settings) -> None:
    if ":memory:" in settings.database_url:
        Base.metadata.create_all(db.engine)
        return

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    alembic_tables = "alembic_version" in tables

    if not tables:
        logger.info("fresh database: alembic upgrade head")
        command.upgrade(_alembic_config(settings), "head")
    elif alembic_tables:
        logger.info("versioned database: alembic upgrade head")
        command.upgrade(_alembic_config(settings), "head")
    elif "users" in tables:
        logger.info("legacy database detected; applying additive data-preserving migration")
        _legacy_add_columns(db)
        command.stamp(_alembic_config(settings), "head")
    else:
        raise RuntimeError("ساختار دیتابیس ناشناخته است و بدون مهاجرت امن نمی‌توان برنامه را اجرا کرد.")

    # Final compatibility check. Alembic owns versioned DB changes; metadata
    # check is a guard against broken deploys rather than a runtime schema builder.
    inspector = inspect(db.engine)
    missing = set(Base.metadata.tables) - set(inspector.get_table_names())
    if missing:
        raise RuntimeError(f"پس از migration جداول زیر وجود ندارند: {', '.join(sorted(missing))}")
