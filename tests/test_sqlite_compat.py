"""Tests for the project-local SQLite compatibility selection."""

import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

from photography_coach.sqlite_compat import configure_sqlite_for_chroma


class SqliteCompatibilityTests(unittest.TestCase):
    def test_current_sqlite_binding_is_kept_when_new_enough(self) -> None:
        original = sys.modules["sqlite3"]

        configure_sqlite_for_chroma()

        self.assertIs(sys.modules["sqlite3"], original)

    def test_project_binding_replaces_unsupported_system_sqlite(self) -> None:
        original = sys.modules["sqlite3"]
        original_dbapi2 = sys.modules.get("sqlite3.dbapi2")
        compatible = types.ModuleType("pysqlite3")
        compatible.dbapi2 = types.ModuleType("pysqlite3.dbapi2")
        try:
            with (
                patch.object(sqlite3, "sqlite_version_info", (3, 34, 1)),
                patch.dict(sys.modules, {"pysqlite3": compatible}),
            ):
                configure_sqlite_for_chroma()
                self.assertIs(sys.modules["sqlite3"], compatible)
                self.assertIs(sys.modules["sqlite3.dbapi2"], compatible.dbapi2)
        finally:
            sys.modules["sqlite3"] = original
            if original_dbapi2 is None:
                sys.modules.pop("sqlite3.dbapi2", None)
            else:
                sys.modules["sqlite3.dbapi2"] = original_dbapi2


if __name__ == "__main__":
    unittest.main()
