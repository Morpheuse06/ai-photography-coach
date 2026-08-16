"""Share in-flight analyses and recent responses within one server process.

Concurrent retries of the same idempotency key must not re-run the model:
the first request registers a future keyed by the idempotency hash, later
requests await that future and receive the identical response (including
the same feedback token). Completed responses are cached briefly so
sequential retries also return the original response without rotating the
feedback token.

The registry is process-local; a multi-worker deployment would need a
shared store or a request-affinity layer.
"""

import asyncio
from time import monotonic

from photography_coach.schemas.analysis import AnalysisResponse

DEFAULT_CACHE_TTL_SECONDS = 600
MAX_CACHE_ENTRIES = 1_000


class AnalysisResponseRegistry:
    """In-flight futures plus a bounded cache of recent responses."""

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._cache_ttl_seconds = cache_ttl_seconds
        self._futures: dict[str, asyncio.Future[AnalysisResponse]] = {}
        self._cache: dict[str, tuple[float, AnalysisResponse]] = {}

    def get_future(self, key: str) -> asyncio.Future[AnalysisResponse] | None:
        """Return the in-flight future for one idempotency hash, if any."""
        return self._futures.get(key)

    def register_future(self, key: str) -> asyncio.Future[AnalysisResponse]:
        """Claim one key for the current request; later requests will wait."""
        future = asyncio.get_running_loop().create_future()
        # The owner request also receives failures directly from _execute().
        # When no retry is waiting, explicitly retrieving the Future's
        # exception prevents asyncio from reporting an unhandled exception.
        # Awaiting this Future still raises the same exception to real waiters.
        future.add_done_callback(_consume_future_exception)
        self._futures[key] = future
        return future

    def get_response(self, key: str) -> AnalysisResponse | None:
        """Return a recently completed response for the same request."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, response = entry
        if monotonic() - stored_at > self._cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        return response

    def store_response(self, key: str, response: AnalysisResponse) -> None:
        """Cache a completed response and resolve the in-flight future."""
        self._prune_cache()
        self._cache[key] = (monotonic(), response)
        future = self._futures.get(key)
        if future is not None and not future.done():
            future.set_result(response)

    def fail_future(self, key: str, exc: BaseException) -> None:
        """Propagate one request's failure to every waiter."""
        future = self._futures.get(key)
        if future is not None and not future.done():
            future.set_exception(exc)

    def remove_future(self, key: str, future: asyncio.Future) -> None:
        """Drop the in-flight entry when its owner request finishes."""
        if self._futures.get(key) is future:
            self._futures.pop(key, None)
            if not future.done():
                future.cancel()

    def _prune_cache(self) -> None:
        if len(self._cache) < MAX_CACHE_ENTRIES:
            return
        oldest = sorted(self._cache, key=lambda k: self._cache[k][0])
        for key in oldest[: MAX_CACHE_ENTRIES // 2]:
            self._cache.pop(key, None)


def _consume_future_exception(future: asyncio.Future[AnalysisResponse]) -> None:
    """Mark an owner-only failure as observed without hiding it from waiters."""
    if not future.cancelled():
        future.exception()
