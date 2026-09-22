"""پایهٔ declarative و قرارداد نام‌گذاری قیدها.

قرارداد نام‌گذاری برای Alembic ضروری است: بدون آن، نام قیدها در SQLite و
PostgreSQL متفاوت تولید می‌شود و مهاجرت‌ها روی دیتابیس موجود شکست می‌خورند.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """پایهٔ همهٔ مدل‌ها."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


__all__ = ["Base", "NAMING_CONVENTION"]
