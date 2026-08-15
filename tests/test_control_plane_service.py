"""Tests for the quota-protected control-plane analysis orchestration."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AccessCodeRequiredError,
    IdempotencyConflictError,
    ModelTimeoutError,
    RequestRateLimitedError,
)
from photography_coach.image_validation import validate_image
from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)
from photography_coach.persistence.models import (
    AccessCode,
    AccessCodeBatch,
    AnalysisRun,
    UsageReservation as UsageReservationRow,
)
from photography_coach.persistence.usage import PolicyDefaults
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.schemas.analysis import (
    AnalysisMetadata,
    AnalysisResponse,
    ImageMetadata,
    ModelUsage,
    RetrievalMetadata,
)
from photography_coach.schemas.interaction import AccessMode
from photography_coach.security import hash_secret
from photography_coach.services.control_plane import ControlPlaneAnalysisService
from photography_coach.services.rag_analysis import RagAnalysisResult
from photography_coach.services.rate_limiting import SourceRateLimiter

RAW_CODE = "PXC-AAAA-BBBB-CCCC-DDDD"


def _png_bytes(color: tuple[int, int, int] = (40, 80, 120)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _validated_image() -> "object":
    return validate_image(_png_bytes(), "image/png")


def _metadata() -> AnalysisMetadata:
    return AnalysisMetadata(
        provider="mock",
        model="mock-model",
        prompt_version="photography-coach-rag-v1.2",
        latency_ms=42,
        image=ImageMetadata(
            media_type="image/png",
            width=16,
            height=12,
            size_bytes=len(_png_bytes()),
        ),
        usage=ModelUsage(total_tokens=9),
        retrieval=RetrievalMetadata(
            knowledge_source_id="src-1",
            knowledge_source_version="1.0",
            planner_model="mock-planner",
            planner_prompt_version="photography-retrieval-v1.4",
            planner_attempts=1,
            embedding_model="deterministic",
            reranker_model="deterministic",
            latency_ms=3,
            retrieved_chunk_ids=["chunk-1"],
        ),
    )


class _CountingRagService:
    """Records model calls and returns deterministic reports."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail_with: Exception | None = None
        self._provider = MockPhotographyProvider()

    async def analyze(self, image_bytes, image, shooting_intent):
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        provider_result = await self._provider.analyze(
            image_bytes, image.media_type, shooting_intent, None
        )
        return RagAnalysisResult(
            response=AnalysisResponse(
                report=provider_result.report,
                metadata=_metadata(),
            ),
            prepared_knowledge=None,
        )


class ControlPlaneServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'control.db'}"
        self.engine = create_db_engine(url)
        self.session_factory = session_factory_for(self.engine)
        await create_schema(self.engine)
        self._sessions: list[AsyncSession] = []
        self.rag_service = _CountingRagService()

    async def asyncTearDown(self) -> None:
        for session in self._sessions:
            await session.close()
        await self.engine.dispose()
        self._tmp.cleanup()

    def service(
        self,
        *,
        mode: AccessMode = AccessMode.OPEN,
        per_source_hour_limit: int | None = 1000,
    ) -> tuple[ControlPlaneAnalysisService, AsyncSession]:
        session = self.session_factory()
        self._sessions.append(session)
        service = ControlPlaneAnalysisService(
            session=session,
            rag_service=self.rag_service,
            reservation_ttl_minutes=30,
            policy_defaults=PolicyDefaults(
                mode=mode,
                per_source_hour_limit=per_source_hour_limit,
                global_daily_limit=None,
                concurrent_analysis_limit=10,
            ),
            source_rate_limiter=SourceRateLimiter(),
        )
        return service, session

    async def _run(
        self,
        service: ControlPlaneAnalysisService,
        *,
        key: str,
        color: tuple[int, int, int] = (40, 80, 120),
        access_code: str | None = None,
        source: str = "test-client",
    ):
        image_bytes = _png_bytes(color)
        return await service.analyze(
            image_bytes,
            validate_image(image_bytes, "image/png"),
            "安静的人像",
            idempotency_key=key,
            access_code=access_code,
            source=source,
        )

    async def _seed_code(self, session: AsyncSession) -> None:
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
                uses_total=1,
                status="active",
            )
        )
        await session.commit()

    async def test_success_fills_interaction_and_records_consumption(self) -> None:
        service, session = self.service()
        response = await self._run(service, key="success-1")

        interaction = response.interaction
        self.assertIsNotNone(interaction)
        assert interaction is not None
        self.assertIsInstance(interaction.analysis_id, UUID)
        self.assertGreaterEqual(len(interaction.feedback_token), 32)
        self.assertEqual(interaction.access.mode, AccessMode.OPEN)

        run = await session.get(AnalysisRun, interaction.analysis_id)
        self.assertEqual(run.status, "succeeded")
        self.assertIsNotNone(run.report_json)
        self.assertEqual(
            run.feedback_token_hash, hash_secret(interaction.feedback_token)
        )

        reservation = await session.scalar(
            select(UsageReservationRow).where(
                UsageReservationRow.analysis_id == interaction.analysis_id
            )
        )
        self.assertEqual(reservation.status, "consumed")

    async def test_model_failure_records_and_releases_quota(self) -> None:
        service, session = self.service(mode=AccessMode.CODE_REQUIRED)
        await self._seed_code(session)
        self.rag_service.fail_with = ModelTimeoutError()

        with self.assertRaises(ModelTimeoutError):
            await self._run(service, key="failure-1", access_code=RAW_CODE)

        reservation = await session.scalar(
            select(UsageReservationRow)
        )
        self.assertEqual(reservation.status, "released")
        self.assertEqual(reservation.release_reason, "model_timeout")
        run = await session.get(AnalysisRun, reservation.analysis_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "model_timeout")
        code = await session.scalar(select(AccessCode))
        self.assertEqual(code.uses_reserved, 0)
        self.assertEqual(code.uses_consumed, 0)

    async def test_retry_after_success_replays_without_model_call(self) -> None:
        service, session = self.service()
        first = await self._run(service, key="replay-1")
        assert first.interaction is not None

        second = await self._run(service, key="replay-1")
        assert second.interaction is not None

        self.assertEqual(self.rag_service.calls, 1)
        self.assertEqual(second.interaction.analysis_id, first.interaction.analysis_id)
        self.assertEqual(
            second.report.model_dump_json(), first.report.model_dump_json()
        )
        self.assertNotEqual(
            second.interaction.feedback_token, first.interaction.feedback_token
        )
        reservations = (
            await session.scalars(select(UsageReservationRow))
        ).all()
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0].status, "consumed")

    async def test_same_key_with_different_photo_is_a_conflict(self) -> None:
        service, _ = self.service()
        await self._run(service, key="conflict-1")

        with self.assertRaises(IdempotencyConflictError):
            await self._run(service, key="conflict-1", color=(200, 10, 10))

    async def test_retry_after_failure_raises_recorded_error(self) -> None:
        service, _ = self.service()
        self.rag_service.fail_with = ModelTimeoutError()
        with self.assertRaises(ModelTimeoutError):
            await self._run(service, key="retry-failure-1")

        self.rag_service.fail_with = None
        with self.assertRaises(ModelTimeoutError):
            await self._run(service, key="retry-failure-1")
        self.assertEqual(self.rag_service.calls, 1)

    async def test_source_rate_limit_applies_before_reservation(self) -> None:
        service, session = self.service(per_source_hour_limit=1)
        await self._run(service, key="rate-1")

        with self.assertRaises(RequestRateLimitedError):
            await self._run(service, key="rate-2")

        reservations = (
            await session.scalars(select(UsageReservationRow))
        ).all()
        self.assertEqual(len(reservations), 1)

    async def test_code_required_mode_requires_a_code(self) -> None:
        service, _ = self.service(mode=AccessMode.CODE_REQUIRED)

        with self.assertRaises(AccessCodeRequiredError):
            await self._run(service, key="code-required-1")


if __name__ == "__main__":
    unittest.main()
