"""Tests that future adapters can satisfy the control-plane interfaces."""

from datetime import UTC, datetime, timedelta
import unittest
from uuid import UUID, uuid4

from photography_coach.ports.control_plane import (
    AnalysisRecorder,
    AnalysisRunFailure,
    AnalysisRunStart,
    FeedbackRepository,
    UsageAuthorizer,
    UsageReservation,
)
from photography_coach.schemas.analysis import AnalysisMetadata, ImageMetadata
from photography_coach.schemas.interaction import (
    AccessMode,
    AnalysisAccess,
    ProblemReportCreate,
    ProblemReportReceipt,
    RatingReceipt,
    RatingTarget,
    RatingUpsertRequest,
)
from photography_coach.schemas.report import PhotographyReport


class _ControlPlaneAdapter:
    async def reserve(
        self,
        *,
        analysis_id: UUID,
        access_code: str | None,
        idempotency_key: str,
    ) -> UsageReservation:
        del access_code, idempotency_key
        return UsageReservation(
            reservation_id=uuid4(),
            analysis_id=analysis_id,
            mode=AccessMode.OPEN,
            access_code_id=None,
            remaining_uses_after_reservation=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def commit(
        self,
        reservation_id: UUID,
        *,
        analysis_id: UUID,
    ) -> AnalysisAccess:
        del reservation_id, analysis_id
        return AnalysisAccess(mode=AccessMode.OPEN)

    async def release(
        self,
        reservation_id: UUID,
        *,
        analysis_id: UUID,
        reason: str,
    ) -> None:
        del reservation_id, analysis_id, reason

    async def start(self, run: AnalysisRunStart) -> None:
        del run

    async def succeed(
        self,
        analysis_id: UUID,
        *,
        completed_at: datetime,
        report: PhotographyReport,
        metadata: AnalysisMetadata,
    ) -> None:
        del analysis_id, completed_at, report, metadata

    async def fail(self, failure: AnalysisRunFailure) -> None:
        del failure

    async def upsert_rating(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
        target: RatingTarget,
        rating: RatingUpsertRequest,
    ) -> RatingReceipt:
        del analysis_id, feedback_token, target, rating
        raise NotImplementedError

    async def delete_rating(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
        target: RatingTarget,
    ) -> bool:
        del analysis_id, feedback_token, target
        return False

    async def create_problem_report(
        self,
        report: ProblemReportCreate,
        *,
        runtime_metadata=None,
    ) -> ProblemReportReceipt:
        del report, runtime_metadata
        raise NotImplementedError


class ControlPlanePortTests(unittest.TestCase):
    def test_one_adapter_can_implement_all_three_ports(self) -> None:
        adapter = _ControlPlaneAdapter()

        self.assertIsInstance(adapter, UsageAuthorizer)
        self.assertIsInstance(adapter, AnalysisRecorder)
        self.assertIsInstance(adapter, FeedbackRepository)

    def test_analysis_start_cannot_receive_photo_bytes(self) -> None:
        run = AnalysisRunStart(
            analysis_id=uuid4(),
            api_version="v2",
            started_at=datetime.now(UTC),
            image=ImageMetadata(
                media_type="image/jpeg",
                width=100,
                height=80,
                size_bytes=2_000,
            ),
            shooting_intent=None,
            reservation_id=None,
        )

        self.assertNotIn("image_bytes", run.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
