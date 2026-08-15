"""HTTP tests for the V2 endpoint with the control plane enabled."""

import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from photography_coach.config import Settings
from photography_coach.main import create_app
from photography_coach.persistence.engine import session_factory_for
from photography_coach.persistence.models import (
    AccessCode,
    AccessCodeBatch,
    AccessPolicyRow,
)
from photography_coach.security import hash_secret

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_CODE = "PXC-AAAA-BBBB-CCCC-DDDD"


def _png_bytes(color: tuple[int, int, int] = (40, 80, 120)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


class ControlPlaneEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            _env_file=None,
            model_provider="mock",
            rag_enabled=True,
            control_plane_enabled=True,
            database_url=(
                f"sqlite+aiosqlite:///{Path(cls._tmp.name) / 'endpoint.db'}"
            ),
            chroma_path=Path(cls._tmp.name) / "chroma",
            knowledge_corpus_path=(
                PROJECT_ROOT
                / "knowledge/chunks/ai-photography-coach-handbook.json"
            ),
            default_access_mode="open",
            default_per_source_hour_limit=1000,
        )
        cls.app = create_app(settings)
        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()

    def _post(self, *, key: str, color: tuple[int, int, int] = (40, 80, 120)):
        return self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(color), "image/png")},
            data={"intent": "表现安静的环境人像"},
            headers={
                "Idempotency-Key": key,
                "X-Access-Code": RAW_CODE,
            },
        )

    def _set_policy(
        self,
        *,
        mode: str,
        per_source_hour_limit: int | None = 1000,
        global_daily_limit: int | None = None,
    ) -> None:
        async def update() -> None:
            engine = self.app.state.db_engine
            async with session_factory_for(engine)() as session:
                row = await session.scalar(select(AccessPolicyRow).limit(1))
                if row is None:
                    session.add(
                        AccessPolicyRow(
                            id=1,
                            mode=mode,
                            per_source_hour_limit=per_source_hour_limit,
                            global_daily_limit=global_daily_limit,
                            concurrent_analysis_limit=10,
                            updated_by="test",
                        )
                    )
                else:
                    row.mode = mode
                    row.per_source_hour_limit = per_source_hour_limit
                    row.global_daily_limit = global_daily_limit
                await session.commit()

        asyncio.run(update())

    def _seed_code(self, *, uses_total: int = 1) -> None:
        async def insert() -> None:
            engine = self.app.state.db_engine
            async with session_factory_for(engine)() as session:
                batch = AccessCodeBatch(
                    label="batch", quantity=1, uses_per_code=1, created_by="test"
                )
                session.add(batch)
                await session.flush()
                session.add(
                    AccessCode(
                        batch_id=batch.id,
                        code_hash=hash_secret(RAW_CODE),
                        prefix="PXC-AAAA",
                        uses_total=uses_total,
                        status="active",
                    )
                )
                await session.commit()

        asyncio.run(insert())

    def test_success_fills_interaction(self) -> None:
        response = self._post(key="endpoint-success-1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("interaction", body)
        interaction = body["interaction"]
        self.assertEqual(interaction["access"]["mode"], "open")
        self.assertEqual(len(interaction["feedback_token"]), 43)

    def test_missing_idempotency_key_is_rejected(self) -> None:
        response = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_retry_replays_the_same_analysis(self) -> None:
        first = self._post(key="endpoint-replay-1")
        second = self._post(key="endpoint-replay-1")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.json()["interaction"]["analysis_id"],
            second.json()["interaction"]["analysis_id"],
        )
        self.assertEqual(
            first.json()["report"], second.json()["report"]
        )
        # The replay returns the original response, including the same
        # feedback token, so ratings from the first page keep working.
        self.assertEqual(
            first.json()["interaction"]["feedback_token"],
            second.json()["interaction"]["feedback_token"],
        )

    def test_same_key_with_different_photo_is_a_conflict(self) -> None:
        first = self._post(key="endpoint-conflict-1")
        self.assertEqual(first.status_code, 200)

        conflict = self._post(key="endpoint-conflict-1", color=(200, 10, 10))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            conflict.json()["error"]["code"], "idempotency_conflict"
        )

    def test_code_required_mode_returns_401_403_and_429(self) -> None:
        self._set_policy(mode="code_required")
        self._seed_code()

        missing = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
            headers={"Idempotency-Key": "endpoint-code-1"},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["error"]["code"], "access_code_required")

        invalid = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
            headers={
                "Idempotency-Key": "endpoint-code-2",
                "X-Access-Code": "PXC-WRONG-CODE-9999",
            },
        )
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(invalid.json()["error"]["code"], "access_denied")

        consumed = self._post(key="endpoint-code-3")
        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(
            consumed.json()["interaction"]["access"]["remaining_uses"], 0
        )

        exhausted = self._post(key="endpoint-code-4")
        self.assertEqual(exhausted.status_code, 429)
        self.assertEqual(
            exhausted.json()["error"]["code"], "access_quota_exhausted"
        )

        self._set_policy(mode="open")

    def test_closed_mode_rejects_new_analyses(self) -> None:
        self._set_policy(mode="closed")

        response = self._post(key="endpoint-closed-1")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "analysis_closed")

        self._set_policy(mode="open")


if __name__ == "__main__":
    unittest.main()
