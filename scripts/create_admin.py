"""Create or update the first management console administrator.

Usage:
    python scripts/create_admin.py --username owner
    ADMIN_USERNAME=owner ADMIN_PASSWORD='...' python scripts/create_admin.py

Passwords are hashed with Argon2id and never printed or stored in plaintext.
"""

import argparse
import asyncio
import getpass
import os

from photography_coach.config import get_settings
from photography_coach.persistence.admin_auth import SqlAdminAuthService
from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update a management console administrator."
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("ADMIN_USERNAME"),
        help="Admin username; falls back to the ADMIN_USERNAME environment variable.",
    )
    return parser.parse_args()


async def _run(username: str, password: str) -> None:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    await create_schema(engine)
    async with session_factory_for(engine)() as session:
        service = SqlAdminAuthService(
            session,
            session_ttl_hours=settings.admin_session_ttl_hours,
        )
        await service.create_admin_user(username, password)
    await engine.dispose()
    print(f"Admin user '{username}' is ready.")


def main() -> None:
    args = _parse_args()
    username = (args.username or input("Admin username: ")).strip()
    if not username:
        raise SystemExit("A username is required.")
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass(
        "Admin password (at least 12 characters): "
    )
    if len(password) < 12:
        raise SystemExit("The password must be at least 12 characters.")
    asyncio.run(_run(username, password))


if __name__ == "__main__":
    main()
