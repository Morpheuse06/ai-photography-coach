"""Tests for the local retrieval planner used without external API calls."""

import unittest

from photography_coach.providers.mock_planner import MockRetrievalPlanner
from photography_coach.providers.planner import RetrievalPlanner
from photography_coach.knowledge.retrieval import REPORT_DIMENSIONS


class MockRetrievalPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_a_valid_grounded_plan(self) -> None:
        planner = MockRetrievalPlanner()

        result = await planner.create_plan(
            b"fake-image-bytes",
            "image/jpeg",
            "表现安静的环境人像",
        )

        self.assertEqual(result.plan.user_intent, "表现安静的环境人像")
        self.assertEqual(len(result.plan.queries), 5)
        self.assertEqual(
            {query.dimension for query in result.plan.queries},
            set(REPORT_DIMENSIONS),
        )
        self.assertEqual(result.plan.max_total_chunks, 6)
        self.assertTrue(
            all(query.evidence_ids for query in result.plan.queries)
        )

    async def test_implements_the_planner_contract(self) -> None:
        planner: RetrievalPlanner = MockRetrievalPlanner()

        result = await planner.create_plan(b"image", "image/png", None)

        self.assertEqual(planner.name, "mock")
        self.assertEqual(result.plan.user_intent, None)


if __name__ == "__main__":
    unittest.main()
