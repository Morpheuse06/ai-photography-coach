"""Tests for the SQL anonymous feedback repository."""

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AnalysisNotFoundError,
    FeedbackForbiddenError,
)
from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)
from photography_coach.persistence.feedback import SqlFeedbackRepository
from photography_coach.persistence.models import (
    AnalysisRun,
    DimensionRating,
    ProblemReport,
)
from photography_coach.schemas.interaction import (
    ProblemCategory,
    ProblemReportCreate,
    RatingReasonCode,
    RatingTarget,
    RatingUpsertRequest,
    RatingVote,
)
from photography_coach.security import hash_secret

TOKEN = "7B1DgR5NwP2kL9xQa4Vm8Yc3Hs6Jt0UfEeZiKpAo"


class SqlFeedbackRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'feedback.db'}"
        self.engine = create_db_engine(url)
        self.session_factory = session_factory_for(self.engine)
        await create_schema(self.engine)
        self._sessions: list[AsyncSession] = []

    async def asyncTearDown(self) -> None:
        for session in self._sessions:
            await session.close()
        await self.engine.dispose()
        self._tmp.cleanup()

    def session(self) -> AsyncSession:
        session = self.session_factory()
        self._sessions.append(session)
        return session

    def repository(self, session: AsyncSession) -> SqlFeedbackRepository:
        return SqlFeedbackRepository(session)

    async def seed_run(self, session: AsyncSession, *, token: str = TOKEN):
        analysis_id = uuid4()
        session.add(
            AnalysisRun(
                analysis_id=analysis_id,
                api_version="v2",
                status="succeeded",
                started_at=datetime.now(UTC).replace(tzinfo=None),
                completed_at=datetime.now(UTC).replace(tzinfo=None),
                media_type="image/png",
                width=8,
                height=6,
                size_bytes=100,
                provider="mock",
                model="mock-model",
                prompt_version="photography-coach-rag-v1.2",
                latency_ms=50,
                total_tokens=7,
                feedback_token_hash=hash_secret(token),
            )
        )
        await session.commit()
        return analysis_id

    async def test_upsert_creates_then_replaces_in_place(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(session)
        repository = self.repository(session)
        rating = RatingUpsertRequest(
            vote=RatingVote.DOWN,
            reason_codes=[RatingReasonCode.GENERIC_ADVICE],
            comment="建议不够具体。",
        )

        first = await repository.upsert_rating(
            analysis_id=analysis_id,
            feedback_token=TOKEN,
            target=RatingTarget.LIGHTING,
            rating=rating,
        )
        second = await repository.upsert_rating(
            analysis_id=analysis_id,
            feedback_token=TOKEN,
            target=RatingTarget.LIGHTING,
            rating=RatingUpsertRequest(vote=RatingVote.UP),
        )

        self.assertEqual(second.rating_id, first.rating_id)
        self.assertEqual(second.vote, RatingVote.UP)
        count = await session.scalar(
            select(func.count()).select_from(DimensionRating)
        )
        self.assertEqual(count, 1)

    async def test_token_must_match_the_analysis(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(session)
        repository = self.repository(session)
        rating = RatingUpsertRequest(vote=RatingVote.UP)

        with self.assertRaises(FeedbackForbiddenError):
            await repository.upsert_rating(
                analysis_id=analysis_id,
                feedback_token="Z".join(["9"] * 43),
                target=RatingTarget.COLOR,
                rating=rating,
            )
        with self.assertRaises(FeedbackForbiddenError):
            await repository.delete_rating(
                analysis_id=analysis_id,
                feedback_token="Z".join(["9"] * 43),
                target=RatingTarget.COLOR,
            )

        other_id = await self.seed_run(session, token="other-token-value-0123456789012345678901")
        with self.assertRaises(FeedbackForbiddenError):
            await repository.upsert_rating(
                analysis_id=other_id,
                feedback_token=TOKEN,
                target=RatingTarget.COLOR,
                rating=rating,
            )

    async def test_unknown_analysis_is_not_found(self) -> None:
        session = self.session()
        repository = self.repository(session)

        with self.assertRaises(AnalysisNotFoundError):
            await repository.upsert_rating(
                analysis_id=uuid4(),
                feedback_token=TOKEN,
                target=RatingTarget.COLOR,
                rating=RatingUpsertRequest(vote=RatingVote.UP),
            )

    async def test_delete_is_idempotent(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(session)
        repository = self.repository(session)
        await repository.upsert_rating(
            analysis_id=analysis_id,
            feedback_token=TOKEN,
            target=RatingTarget.OVERALL,
            rating=RatingUpsertRequest(vote=RatingVote.UP),
        )

        self.assertTrue(
            await repository.delete_rating(
                analysis_id=analysis_id,
                feedback_token=TOKEN,
                target=RatingTarget.OVERALL,
            )
        )
        self.assertFalse(
            await repository.delete_rating(
                analysis_id=analysis_id,
                feedback_token=TOKEN,
                target=RatingTarget.OVERALL,
            )
        )

    async def test_problem_report_stores_only_approved_metadata(self) -> None:
        session = self.session()
        analysis_id = await self.seed_run(session)
        repository = self.repository(session)

        receipt = await repository.create_problem_report(
            ProblemReportCreate(
                analysis_id=analysis_id,
                category=ProblemCategory.REPORT_QUALITY,
                message="光影建议没有考虑画面中主体已经处于剪影状态。",
                include_runtime_metadata=True,
            )
        )

        self.assertEqual(receipt.status.value, "new")
        row = await session.scalar(
            select(ProblemReport).where(
                ProblemReport.id == receipt.problem_report_id
            )
        )
        self.assertIn('"provider"', row.runtime_metadata_json)
        self.assertIn("mock", row.runtime_metadata_json)
        self.assertNotIn("image", row.runtime_metadata_json.lower())

    async def test_problem_report_with_unknown_analysis_fails(self) -> None:
        session = self.session()
        repository = self.repository(session)

        with self.assertRaises(AnalysisNotFoundError):
            await repository.create_problem_report(
                ProblemReportCreate(
                    analysis_id=uuid4(),
                    category=ProblemCategory.BUG,
                    message="分析一直失败，页面总是提示系统错误。",
                )
            )

    async def test_problem_report_without_analysis_is_stored(self) -> None:
        session = self.session()
        repository = self.repository(session)

        receipt = await repository.create_problem_report(
            ProblemReportCreate(
                category=ProblemCategory.USABILITY,
                message="页面的反馈入口不够明显。",
            )
        )
        self.assertIsNotNone(receipt.problem_report_id)


if __name__ == "__main__":
    unittest.main()
