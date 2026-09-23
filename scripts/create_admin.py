"""Create or promote an admin account explicitly; never grant admin through public registration."""
from __future__ import annotations

import getpass

from mas_app.config import get_settings
from mas_app.core.security import SecurityManager, normalize_username, username_to_key
from mas_app.db.session import Database
from mas_app.db.migrator import run_database_migrations
from mas_app.db.models import User
from sqlalchemy import select


def main() -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        run_database_migrations(database, settings)
        username = normalize_username(input("Admin username: ").strip())
        password = getpass.getpass("Admin password: ")
        if len(password) < 8:
            raise SystemExit("Password must be at least 8 characters.")
        security = SecurityManager(settings)
        with database.session() as session:
            user = session.execute(select(User).where(User.username_key == username_to_key(username))).scalar_one_or_none()
            if user is None:
                raise SystemExit("User does not exist; register the account first, then rerun this tool.")
            user.role = "admin"
            user.is_active = True
            user.failed_login_count = 0
            user.locked_until_ms = 0
            user.password_hash = security.hash_password(password)
        print("Admin account updated.")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
