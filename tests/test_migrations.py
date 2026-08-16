"""Database migration regression tests."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config

from photography_coach.config import get_settings


class MigrationTests(unittest.TestCase):
    def test_sqlite_database_upgrades_from_empty_to_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "migration-test.db"
            previous_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
            get_settings.cache_clear()
            try:
                command.upgrade(Config("alembic.ini"), "head")
            finally:
                if previous_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = previous_url
                get_settings.cache_clear()

            with sqlite3.connect(database_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(usage_reservations)"
                    )
                }
                revision = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()

            self.assertIn("request_hash", columns)
            self.assertEqual(revision, ("ffa62323f640",))


if __name__ == "__main__":
    unittest.main()
