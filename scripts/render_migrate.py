"""Run MAS Alembic migrations as a Render build step.

This is intentionally separate from Uvicorn startup so a failed migration
cancels the build while the last successful web deploy keeps serving traffic.
"""
from __future__ import annotations

import logging

from mas_app.config import get_settings
from mas_app.db.migrator import run_database_migrations
from mas_app.db.session import Database

logging.basicConfig(level=logging.INFO)


def main() -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        logging.getLogger("mas").info("Render build: اجرای migration دیتابیس...")
        run_database_migrations(database, settings)
        logging.getLogger("mas").info("Render build: migration با موفقیت تمام شد.")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
