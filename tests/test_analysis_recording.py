"""Tests for the SQL analysis run recorder."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    drop_schema,
    session_factory_for,
)
from photography_coach.persistence.models import AnalysisRun
from photography_coach.persistence.recording import (
    AnalysisRunMissingError,
    SqlAnalysisRecorder,
    stored_run_metadata,
)
from photography_coach.ports.control_plane import AnalysisRunFailure, AnalysisRunStart
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.schemas.analysis import (
    AnalysisMetadata,
    ImageMetadata,
    ModelUsage,
    RetrievalMetadata,
)


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _started_run(**overrides) -> AnalysisRunStart:
    values = {
        "analysis_id": uuid4(),
        "api_version": "v2",
        "started_at": datetime.now(UTC),
        "image": ImageMetadata(
            media_type="image/png",
            width=8,
            height=6,
            size_bytes=100,
        ),
        "shooting_intent": "安静的人像",
        "reservation_id": None,
    }
    values.update(overrides)
    return AnalysisRunStart(**values)


def _metadata() -> AnalysisMetadata:
    return AnalysisMetadata(
        provider="mock",
        model="mock-model",
        prompt_version="photography-coach-rag-v1.2",
        latency_ms=321,
        image=ImageMetadata(
            media_type="image/png",
            width=8,
            height=6,
            size_bytes=100,
        ),
        usage=ModelUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        retrieval=RetrievalMetadata(
            knowledge_source_id="src-1",
            knowledge_source_version="1.0",
            planner_model="mock-planner",
            planner_prompt_version="photography-retrieval-v1.4",
            planner_attempts=1,
            embedding_model="deterministic",
            reranker_model="deterministic",
            latency_ms=12,
            retrieved_chunk_ids=["chunk-1", "chunk-2"],
        ),
    )


class SqlAnalysisRecorderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'control.db'}"
        self.engine = create_db_engine(url)
        self.session_factory = session_factory_for(self.engine)
        await create_schema(self.engine)
        self.session: AsyncSession = self.session_factory()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await drop_schema(self.engine)
        await self.engine.dispose()
        self._tmp.cleanup()

    def recorder(self) -> SqlAnalysisRecorder:
        return SqlAnalysisRecorder(self.session)

    async def test_start_creates_running_row_without_photo_bytes(self) -> None:
        run = _started_run()
        await self.recorder().start(run)

        columns = {
            column.name
            for column in inspect(AnalysisRun).columns
        }
        self.assertNotIn("image_bytes", columns)
        self.assertNotIn("photo", columns)
        row = await self.session.get(AnalysisRun, run.analysis_id)
        self.assertEqual(row.status, "running")
        self.assertEqual(row.width, 8)
        self.assertEqual(row.height, 6)
        self.assertEqual(row.shooting_intent, "安静的人像")

    async def test_succeed_stores_report_metadata_and_retention_deadline(self) -> None:
        run = _started_run()
        recorder = self.recorder()
        await recorder.start(run)
        provider = MockPhotographyProvider()
        result = await provider.analyze(
            _png_bytes(), "image/png", None, None
        )
        completed_at = datetime.now(UTC) + timedelta(seconds=1)

        await recorder.succeed(
            run.analysis_id,
            completed_at=completed_at,
            report=result.report,
            metadata=_metadata(),
        )

        row = await self.session.get(AnalysisRun, run.analysis_id)
        self.assertEqual(row.status, "succeeded")
        self.assertEqual(row.provider, "mock")
        self.assertEqual(row.total_tokens, 30)
        self.assertEqual(row.embedding_model, "deterministic")
        self.assertEqual(row.report_retained_until, completed_at.replace(tzinfo=None) + timedelta(days=30))
        restored = stored_run_metadata(row)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.retrieval.retrieved_chunk_ids, ["chunk-1", "chunk-2"])

    async def test_fail_stores_terminal_error_without_report(self) -> None:
        run = _started_run()
        recorder = self.recorder()
        await recorder.start(run)

        await recorder.fail(
            AnalysisRunFailure(
                analysis_id=run.analysis_id,
                completed_at=datetime.now(UTC),
                error_code="model_timeout",
                latency_ms=45_000,
                sanitized_diagnostic="provider timed out",
            )
        )

        row = await self.session.get(AnalysisRun, run.analysis_id)
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.error_code, "model_timeout")
        self.assertIsNone(row.report_json)

    async def test_repeated_terminal_updates_are_no_ops(self) -> None:
        run = _started_run()
        recorder = self.recorder()
        await recorder.start(run)
        failure = AnalysisRunFailure(
            analysis_id=run.analysis_id,
            completed_at=datetime.now(UTC),
            error_code="model_timeout",
            latency_ms=1,
        )
        await recorder.fail(failure)

        # A late success cannot replace the first terminal state.
        provider = MockPhotographyProvider()
        result = await provider.analyze(_png_bytes(), "image/png", None, None)
        await recorder.succeed(
            run.analysis_id,
            completed_at=datetime.now(UTC),
            report=result.report,
            metadata=_metadata(),
        )
        await recorder.fail(failure)

        row = await self.session.get(AnalysisRun, run.analysis_id)
        self.assertEqual(row.status, "failed")
        self.assertIsNone(row.report_json)

    async def test_unknown_analysis_raises(self) -> None:
        with self.assertRaises(AnalysisRunMissingError):
            await self.recorder().succeed(
                uuid4(),
                completed_at=datetime.now(UTC),
                report=(await MockPhotographyProvider().analyze(
                    _png_bytes(), "image/png", None, None
                )).report,
                metadata=_metadata(),
            )


if __name__ == "__main__":
    unittest.main()
