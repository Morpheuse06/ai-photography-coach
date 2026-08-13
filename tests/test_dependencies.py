"""Tests for configuration-driven service construction."""

import unittest
from unittest.mock import patch

from photography_coach.config import Settings, get_settings
from photography_coach.dependencies import get_analysis_service
from photography_coach.errors import ModelUnavailableError
from photography_coach.providers.dashscope import DashScopePhotographyProvider


class DependencyFactoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_analysis_service.cache_clear()
        get_settings.cache_clear()

    def test_builds_dashscope_provider_from_settings(self) -> None:
        settings = Settings(
            model_provider="dashscope",
            model_api_key="test-key",
            model_name="qwen3.7-plus",
            model_base_url="https://workspace.example/compatible-mode/v1",
        )

        with patch(
            "photography_coach.dependencies.get_settings",
            return_value=settings,
        ):
            service = get_analysis_service()

        self.assertIsInstance(service._provider, DashScopePhotographyProvider)
        self.assertEqual(service._provider.model, "qwen3.7-plus")

    def test_requires_an_api_key_for_dashscope(self) -> None:
        settings = Settings(
            model_provider="dashscope",
            model_api_key=None,
            model_name="qwen3.7-plus",
        )

        with patch(
            "photography_coach.dependencies.get_settings",
            return_value=settings,
        ):
            with self.assertRaises(ModelUnavailableError):
                get_analysis_service()


if __name__ == "__main__":
    unittest.main()
