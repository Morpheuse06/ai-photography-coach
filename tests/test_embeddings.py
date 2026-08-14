"""Tests for provider-independent embeddings and the local test provider."""

from math import isclose, sqrt
import unittest

from photography_coach.knowledge.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingResult,
)


class EmbeddingResultTests(unittest.TestCase):
    def test_reports_vector_dimensions(self) -> None:
        result = EmbeddingResult(vectors=((0.1, 0.2), (0.3, 0.4)))

        self.assertEqual(result.dimensions, 2)

    def test_rejects_vectors_with_different_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "same dimensions"):
            EmbeddingResult(vectors=((0.1, 0.2), (0.3,)))

    def test_rejects_non_finite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            EmbeddingResult(vectors=((0.1, float("nan")),))

    def test_rejects_negative_token_usage(self) -> None:
        with self.assertRaisesRegex(ValueError, "input_tokens"):
            EmbeddingResult(vectors=((0.1, 0.2),), input_tokens=-1)


class DeterministicEmbeddingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_text_produces_the_same_vector(self) -> None:
        provider = DeterministicEmbeddingProvider(dimensions=32)

        first = await provider.embed_query("窗边逆光人物")
        second = await provider.embed_query("窗边逆光人物")

        self.assertEqual(first.vectors[0], second.vectors[0])

    async def test_query_and_document_share_one_vector_space(self) -> None:
        provider = DeterministicEmbeddingProvider(dimensions=32)

        query = await provider.embed_query("主体与背景的亮度关系")
        document = await provider.embed_documents(["主体与背景的亮度关系"])

        self.assertEqual(query.vectors[0], document.vectors[0])

    async def test_different_text_produces_a_different_vector(self) -> None:
        provider = DeterministicEmbeddingProvider(dimensions=32)

        result = await provider.embed_documents(["窗边逆光", "重复图案构图"])

        self.assertNotEqual(result.vectors[0], result.vectors[1])

    async def test_vectors_have_configured_dimensions_and_unit_length(self) -> None:
        provider = DeterministicEmbeddingProvider(dimensions=48)

        result = await provider.embed_query("观察画面的光线方向和阴影边界")
        vector = result.vectors[0]
        magnitude = sqrt(sum(value * value for value in vector))

        self.assertEqual(result.dimensions, 48)
        self.assertTrue(isclose(magnitude, 1.0, abs_tol=1e-9))

    async def test_preserves_document_order_in_a_batch(self) -> None:
        provider = DeterministicEmbeddingProvider(dimensions=16)

        batch = await provider.embed_documents(["第一段文字", "第二段文字"])
        first = await provider.embed_query("第一段文字")
        second = await provider.embed_query("第二段文字")

        self.assertEqual(batch.vectors, (first.vectors[0], second.vectors[0]))

    async def test_rejects_empty_or_blank_text(self) -> None:
        provider = DeterministicEmbeddingProvider()

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            await provider.embed_documents([])
        with self.assertRaisesRegex(ValueError, "cannot be blank"):
            await provider.embed_query("   ")

    def test_rejects_too_few_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 8"):
            DeterministicEmbeddingProvider(dimensions=4)

    async def test_implements_the_provider_contract(self) -> None:
        provider: EmbeddingProvider = DeterministicEmbeddingProvider()

        result = await provider.embed_query("验证供应商无关接口")

        self.assertEqual(result.dimensions, provider.dimensions)


if __name__ == "__main__":
    unittest.main()
