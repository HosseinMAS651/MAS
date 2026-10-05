"""Reset an existing user's password from a trusted server/CLI when no recovery code exists."""
from __future__ import annotations

import getpass

from sqlalchemy import delete, select

from mas_app.config import get_settings
from mas_app.core.security import SecurityManager, normalize_username, username_to_key
from mas_app.core.timeutil import utc_now_ms
from mas_app.db.migrator import run_database_migrations
from mas_app.db.models import AuthSession, User
from mas_app.db.session import Database
from mas_app.services.audit import log_event


def main() -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        run_database_migrations(database, settings)
        username = normalize_username(input("Username: ").strip())
        password = getpass.getpass("New password (minimum 8 characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if len(password) < 8 or len(password) > 128:
            raise SystemExit("Password must contain 8 to 128 characters.")
        if password != confirmation:
            raise SystemExit("Passwords do not match.")

        security = SecurityManager(settings)
        with database.session() as session:
            user = session.execute(
                select(User).where(User.username_key == username_to_key(username)).with_for_update()
            ).scalar_one_or_none()
            if user is None:
                raise SystemExit("User does not exist.")
            user.password_hash = security.hash_password(password)
            user.recovery_code_hash = None
            user.failed_login_count = 0
            user.locked_until_ms = 0
            user.updated_at_ms = utc_now_ms()
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            log_event(
                session,
                action="password_reset_cli",
                actor_username="cli-admin",
                severity="security",
                target_type="user",
                target_id=str(user.id),
                detail={"sessions_invalidated": True, "recovery_code_cleared": True},
            )
        print("Password updated. All active sessions and the previous recovery code were invalidated.")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
