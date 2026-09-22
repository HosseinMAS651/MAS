"""ساخت engine و session دیتابیس.

نکتهٔ مهم برای SQLite: کلیدهای خارجی به‌صورت پیش‌فرض **اعمال نمی‌شوند**؛ بدون
``PRAGMA foreign_keys=ON`` روی هر اتصال، ``ON DELETE CASCADE/SET NULL`` بی‌اثر
است و همان ردیف‌های یتیمی تولید می‌شود که در گزارش audit (DB-03) دیده شد.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from ..config import Settings

logger = logging.getLogger("mas.db")


def make_engine(settings: Settings, *, poolclass: type | None = None) -> Engine:
    """ساخت engine متناسب با نوع دیتابیس."""
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")

    kwargs: dict[str, object] = {
        "echo": settings.db_echo,
        "future": True,
        "pool_pre_ping": not is_sqlite,
    }
    if poolclass is not None:
        kwargs["poolclass"] = poolclass
    elif is_sqlite:
        # SQLite با :memory: نیاز به StaticPool دارد تا تمام نشست‌ها همان دیتابیس مشترک حافظه را ببینند.
        kwargs["poolclass"] = StaticPool if ":memory:" in url else QueuePool
        if kwargs["poolclass"] is QueuePool:
            kwargs.update(
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout_seconds,
            )
    else:
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
        )

    if is_sqlite and ":memory:" not in url:
        # check_same_thread=False لازم است چون FastAPI routeهای همگام را در threadpool اجرا می‌کند.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": settings.db_pool_timeout_seconds}
    elif is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                if ":memory:" not in url:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Database:
    """نگهدارندهٔ engine + session factory + تنظیمات (به‌جای وضعیت سراسری)."""

    def __init__(self, settings: Settings, *, poolclass: type | None = None) -> None:
        self.settings = settings
        self.engine = make_engine(settings, poolclass=poolclass)
        self.session_factory = make_session_factory(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """یک نشست با commit/rollback خودکار."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def unit_of_work(self) -> Iterator[Session]:
        """نشست بدون commit خودکار (وقتی سرویس می‌خواهد خودش کنترل کند)."""
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> tuple[bool, str]:
        """بررسی سلامت اتصال (برای health check)."""
        try:
            with self.engine.connect() as connection:
                connection.execute(select(1))
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 - هر خطای DB باید گزارش شود
            logger.warning("database ping failed: %s", exc)
            return False, f"{type(exc).__name__}: {exc}"

    def table_names(self) -> set[str]:
        from sqlalchemy import inspect

        return set(inspect(self.engine).get_table_names())

    def scalar(self, statement: object) -> object:
        with self.engine.connect() as connection:
            return connection.execute(statement).scalar()  # type: ignore[arg-type]

    def execute_text(self, sql: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(sql))

    def dispose(self) -> None:
        self.engine.dispose()

    @property
    def dialect_name(self) -> str:
        return self.engine.dialect.name

    @property
    def is_sqlite(self) -> bool:
        return self.dialect_name == "sqlite"


__all__ = ["Database", "make_engine", "make_session_factory", "text"]
