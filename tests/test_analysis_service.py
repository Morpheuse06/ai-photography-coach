"""Tests for provider orchestration and total timeout behavior."""

import asyncio
import unittest

from photography_coach.errors import ModelTimeoutError
from photography_coach.image_validation import ValidatedImage
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.services.analysis import AnalysisService


class _SlowProvider(MockPhotographyProvider):
    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ):
        await asyncio.sleep(0.05)
        return await super().analyze(image_bytes, media_type, shooting_intent)


class _AlternativeVendorProvider(MockPhotographyProvider):
    name = "alternative_vendor"
    model = "alternative-vision-model"


class AnalysisServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_enforces_a_total_model_timeout(self) -> None:
        service = AnalysisService(_SlowProvider(), timeout_seconds=0.001)
        image = ValidatedImage(
            format="PNG",
            media_type="image/png",
            width=16,
            height=12,
            size_bytes=100,
        )

        with self.assertRaises(ModelTimeoutError):
            await service.analyze(b"image", image, None)

    async def test_accepts_any_provider_that_implements_the_contract(self) -> None:
        service = AnalysisService(_AlternativeVendorProvider(), timeout_seconds=1)
        image = ValidatedImage(
            format="JPEG",
            media_type="image/jpeg",
            width=20,
            height=10,
            size_bytes=200,
        )

        response = await service.analyze(b"image", image, "测试其他模型接口")

        self.assertEqual(response.metadata.provider, "alternative_vendor")
        self.assertEqual(response.metadata.model, "alternative-vision-model")
        self.assertIsNone(response.metadata.retrieval)


if __name__ == "__main__":
    unittest.main()
