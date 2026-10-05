"""Alembic environment configuration."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from mas_app.db.base import Base
from mas_app.db.models import ALL_TABLES  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Alembic's configured URL is the source of truth. This also makes tests and
# programmatic upgrades deterministic instead of silently using global settings.


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # برای سازگاری کامل با SQLite
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Render can briefly run more than one copy of a web process during a
        # deploy. Serialize PostgreSQL Alembic upgrades so two processes cannot
        # both observe the same old revision and race on CREATE/DROP operations.
        migration_lock_key = 732847159
        locked = False
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_lock(:migration_lock_key)"),
                {"migration_lock_key": migration_lock_key},
            )
            locked = True

        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            if locked:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:migration_lock_key)"),
                    {"migration_lock_key": migration_lock_key},
                )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
