"""Tests for one-time application resource initialization."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from photography_coach.config import Settings
from photography_coach.dependencies import get_rag_analysis_service
from photography_coach.errors import ModelUnavailableError
from photography_coach.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _request_for(application: FastAPI) -> Request:
    return Request({"type": "http", "app": application})


class ApplicationLifespanTests(unittest.TestCase):
    def test_builds_rag_service_once_and_reuses_it(self) -> None:
        settings = Settings(
            _env_file=None,
            model_provider="mock",
            rag_enabled=True,
            knowledge_corpus_path=(
                PROJECT_ROOT
                / "knowledge/chunks/ai-photography-coach-handbook.json"
            ),
        )
        shared_service = object()
        build_service = AsyncMock(return_value=shared_service)

        with (
            patch("photography_coach.main.get_settings", return_value=settings),
            patch(
                "photography_coach.main.build_rag_analysis_service",
                build_service,
            ),
        ):
            application = create_app()
            with TestClient(application):
                first = asyncio.run(
                    get_rag_analysis_service(_request_for(application))
                )
                second = asyncio.run(
                    get_rag_analysis_service(_request_for(application))
                )

                self.assertIs(first, shared_service)
                self.assertIs(second, shared_service)
                build_service.assert_awaited_once_with(settings)

            self.assertIsNone(application.state.rag_analysis_service)

    def test_keeps_rag_unavailable_when_switch_is_off(self) -> None:
        settings = Settings(_env_file=None, rag_enabled=False)
        build_service = AsyncMock()

        with (
            patch("photography_coach.main.get_settings", return_value=settings),
            patch(
                "photography_coach.main.build_rag_analysis_service",
                build_service,
            ),
        ):
            application = create_app()
            with TestClient(application):
                with self.assertRaisesRegex(
                    ModelUnavailableError,
                    "not enabled",
                ):
                    asyncio.run(
                        get_rag_analysis_service(_request_for(application))
                    )

            build_service.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
