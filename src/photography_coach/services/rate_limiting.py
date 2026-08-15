"""In-memory rate limiting with rotating-salt source hashing.

Source addresses are never stored. Each source is hashed with a per-process
secret plus a daily-rotating salt, so hashes cannot be linked across days or
reversed without the secret. Counters live in short buckets that are
discarded once idle, which doubles as the retention cleanup for source
hashes.
"""

from collections import deque
from datetime import UTC, datetime
import hashlib
import hmac
from time import perf_counter
import secrets


class SourceRateLimiter:
    """Fixed-window limiter keyed by a daily-rotated hash of the source."""

    def __init__(self, window_seconds: float = 3_600.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = window_seconds
        self._secret = secrets.token_bytes(32)
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def allow(self, source: str, *, limit: int) -> bool:
        """Return True when the source stays under ``limit`` per window."""
        if limit <= 0:
            return False
        now = perf_counter()
        day = datetime.now(UTC).date().isoformat()
        key = (day, self._source_hash(source, day))
        self._drop_stale_buckets(day)

        bucket = self._buckets.setdefault(key, deque())
        while bucket and bucket[0] <= now - self._window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def _source_hash(self, source: str, day: str) -> str:
        daily_salt = hmac.new(self._secret, day.encode("utf-8"), hashlib.sha256)
        return hmac.new(
            daily_salt.digest(), source.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _drop_stale_buckets(self, current_day: str) -> None:
        for key in [key for key in self._buckets if key[0] != current_day]:
            del self._buckets[key]
