"""Tests for process-local sharing of idempotent analysis responses."""

import asyncio
import unittest

from photography_coach.services.in_flight import AnalysisResponseRegistry


class AnalysisResponseRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_is_observed_and_still_reaches_waiters(self) -> None:
        registry = AnalysisResponseRegistry()
        future = registry.register_future("same-request")
        failure = RuntimeError("model failed")

        registry.fail_future("same-request", failure)
        await asyncio.sleep(0)

        # The done callback has marked the exception as observed, preventing
        # asyncio's "Future exception was never retrieved" warning.
        self.assertFalse(future._log_traceback)
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            await future


if __name__ == "__main__":
    unittest.main()
