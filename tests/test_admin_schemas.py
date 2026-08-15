"""Tests for management API request and response contracts."""

from datetime import UTC, datetime
import unittest
from uuid import uuid4

from pydantic import ValidationError

from photography_coach.schemas.admin import (
    AccessCodeBatchCreate,
    AccessCodeRecord,
    AccessPolicyUpdate,
    ProblemReportUpdate,
)


class AdminSchemaTests(unittest.TestCase):
    def test_accepts_a_bounded_access_code_batch(self) -> None:
        request = AccessCodeBatchCreate(
            quantity=20,
            uses_per_code=5,
            label="摄影社体验批次",
        )

        self.assertEqual(request.quantity, 20)
        self.assertEqual(request.uses_per_code, 5)

    def test_rejects_empty_partial_updates(self) -> None:
        with self.assertRaisesRegex(ValidationError, "at least one"):
            AccessPolicyUpdate()
        with self.assertRaisesRegex(ValidationError, "at least one"):
            ProblemReportUpdate()

    def test_explicit_null_can_clear_an_optional_limit(self) -> None:
        update = AccessPolicyUpdate(per_source_hour_limit=None)

        self.assertIn("per_source_hour_limit", update.model_fields_set)
        self.assertIsNone(update.per_source_hour_limit)

    def test_rejects_access_code_usage_above_total(self) -> None:
        now = datetime.now(UTC)

        with self.assertRaisesRegex(ValidationError, "uses_total"):
            AccessCodeRecord(
                code_id=uuid4(),
                batch_id=uuid4(),
                prefix="PHOTO-ABCD",
                status="active",
                uses_total=5,
                uses_consumed=4,
                uses_reserved=2,
                created_at=now,
                updated_at=now,
            )


if __name__ == "__main__":
    unittest.main()
