"""Project-local SQLite compatibility for Chroma on older Linux systems."""

import importlib
import sqlite3
import sys

CHROMA_MINIMUM_SQLITE = (3, 35, 0)


def configure_sqlite_for_chroma() -> None:
    """Use the bundled SQLite binding only when the system one is too old.

    Replacing the operating system SQLite could break unrelated applications.
    The optional Linux dependency instead provides a recent SQLite build only
    inside this project's virtual environment.
    """

    if sqlite3.sqlite_version_info >= CHROMA_MINIMUM_SQLITE:
        return

    try:
        compatible_sqlite = importlib.import_module("pysqlite3")
    except ImportError as exc:
        current_version = ".".join(map(str, sqlite3.sqlite_version_info))
        raise RuntimeError(
            "Chroma requires SQLite 3.35 or newer; "
            f"the current Python provides {current_version}. "
            "Install the project's Linux dependencies to enable its "
            "project-local pysqlite3 compatibility binding."
        ) from exc

    sys.modules["sqlite3"] = compatible_sqlite
    if hasattr(compatible_sqlite, "dbapi2"):
        sys.modules["sqlite3.dbapi2"] = compatible_sqlite.dbapi2
