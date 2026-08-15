"""Tests for public access, rating, and problem-report contracts."""

import unittest
from uuid import uuid4

from pydantic import ValidationError

from photography_coach.image_validation import ValidatedImage
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.schemas.interaction import (
    AccessMode,
    AnalysisAccess,
    AnalysisInteraction,
    ProblemReportCreate,
    RatingUpsertRequest,
)
from photography_coach.services.analysis import AnalysisService


class InteractionSchemaTests(unittest.IsolatedAsyncioTestCase):
    def test_accepts_a_bounded_anonymous_rating(self) -> None:
        rating = RatingUpsertRequest.model_validate(
            {
                "vote": "down",
                "reason_codes": ["generic_advice", "not_grounded"],
                "comment": "建议没有对应到画面中可以指出的位置。",
            }
        )

        self.assertEqual(rating.vote, "down")
        self.assertEqual(len(rating.reason_codes), 2)

    def test_rejects_duplicate_reasons_and_unknown_fields(self) -> None:
        with self.assertRaisesRegex(ValidationError, "reason_codes"):
            RatingUpsertRequest.model_validate(
                {
                    "vote": "down",
                    "reason_codes": ["inaccurate", "inaccurate"],
                }
            )
        with self.assertRaises(ValidationError):
            ProblemReportCreate.model_validate(
                {
                    "category": "bug",
                    "message": "页面在提交照片以后一直没有显示任何分析结果。",
                    "email": "not-part-of-v1@example.com",
                }
            )

    def test_requires_a_high_entropy_sized_feedback_token(self) -> None:
        with self.assertRaises(ValidationError):
            AnalysisInteraction(
                analysis_id=uuid4(),
                feedback_token="too-short",
                access=AnalysisAccess(mode=AccessMode.OPEN),
            )

    async def test_current_analysis_response_omits_disabled_interaction(self) -> None:
        service = AnalysisService(MockPhotographyProvider(), timeout_seconds=1)
        image = ValidatedImage(
            format="JPEG",
            media_type="image/jpeg",
            width=20,
            height=10,
            size_bytes=200,
        )

        response = await service.analyze(b"image", image, None)

        self.assertIsNone(response.interaction)
        self.assertNotIn("interaction", response.model_dump())

    def test_interaction_serializes_when_control_plane_populates_it(self) -> None:
        interaction = AnalysisInteraction(
            analysis_id=uuid4(),
            feedback_token="f" * 32,
            access=AnalysisAccess(
                mode=AccessMode.CODE_REQUIRED,
                remaining_uses=4,
            ),
        )

        payload = interaction.model_dump(mode="json")

        self.assertEqual(payload["access"]["remaining_uses"], 4)


if __name__ == "__main__":
    unittest.main()
