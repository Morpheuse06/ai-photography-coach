"""Tests for provider-independent reranking contracts and local behavior."""

import unittest

from photography_coach.knowledge.reranking import (
    DeterministicRerankingProvider,
    RerankDocument,
    RerankedItem,
    RerankResult,
    validate_rerank_result,
)


class RerankContractTests(unittest.TestCase):
    def test_rejects_blank_documents_and_non_finite_scores(self) -> None:
        with self.assertRaisesRegex(ValueError, "text cannot be blank"):
            RerankDocument(document_id="chunk-1", text="  ")
        with self.assertRaisesRegex(ValueError, "finite"):
            RerankedItem(document_index=0, relevance_score=float("nan"))

    def test_rejects_duplicate_or_out_of_range_result_indexes(self) -> None:
        cases = [
            (
                RerankResult(
                    items=(
                        RerankedItem(0, 0.9),
                        RerankedItem(0, 0.8),
                    )
                ),
                "duplicate",
            ),
            (
                RerankResult(items=(RerankedItem(2, 0.9),)),
                "out-of-range",
            ),
        ]

        for result, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_rerank_result(
                        result,
                        document_count=2,
                        top_n=2,
                    )


class DeterministicRerankingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranks_the_more_relevant_document_first(self) -> None:
        provider = DeterministicRerankingProvider()
        documents = [
            RerankDocument(
                document_id="color",
                text="建立主色、辅助色和强调色之间的层级关系。",
            ),
            RerankDocument(
                document_id="lighting",
                text="高反差场景要比较主体细节与剪影轮廓。",
            ),
        ]

        result = await provider.rerank(
            "高反差场景怎样保留主体细节",
            documents,
            top_n=1,
        )

        self.assertEqual(result.items[0].document_index, 1)
        self.assertGreater(result.items[0].relevance_score, 0)
        validate_rerank_result(result, document_count=2, top_n=1)

    async def test_uses_original_order_to_break_equal_scores(self) -> None:
        provider = DeterministicRerankingProvider()
        documents = [
            RerankDocument(document_id="first", text="完全无关甲"),
            RerankDocument(document_id="second", text="完全无关乙"),
        ]

        result = await provider.rerank("高光阴影", documents, top_n=2)

        self.assertEqual(
            [item.document_index for item in result.items],
            [0, 1],
        )

    async def test_rejects_invalid_requests(self) -> None:
        provider = DeterministicRerankingProvider()
        documents = [RerankDocument(document_id="one", text="有效文本")]

        cases = [
            ("", documents, 1, "query"),
            ("有效问题", [], 1, "documents"),
            ("有效问题", documents, 2, "top_n"),
            (
                "有效问题",
                [documents[0], RerankDocument(document_id="one", text="另一段")],
                1,
                "unique",
            ),
        ]
        for query, candidate_documents, top_n, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    await provider.rerank(
                        query,
                        candidate_documents,
                        top_n=top_n,
                    )


if __name__ == "__main__":
    unittest.main()
