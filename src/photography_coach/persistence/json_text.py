"""Small JSON text helpers for database columns.

JSON-shaped columns are stored as compact JSON text so that SQLite and
PostgreSQL behave identically without dialect-specific JSON types.
"""

import json
from typing import Any


def dumps(value: Any) -> str:
    """Serialize one value to compact JSON text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(text: str | None, default: Any) -> Any:
    """Parse JSON text, falling back to ``default`` when empty or corrupt."""
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
