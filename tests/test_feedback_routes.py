"""HTTP tests for anonymous ratings and problem feedback routes."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from photography_coach.api import public_routes
from photography_coach.config import Settings
from photography_coach.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=(40, 80, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


class FeedbackRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            _env_file=None,
            model_provider="mock",
            rag_enabled=True,
            control_plane_enabled=True,
            database_url=(
                f"sqlite+aiosqlite:///{Path(cls._tmp.name) / 'feedback.db'}"
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
        cls._key_counter = 0

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()

    def _analyze(self) -> dict:
        self.__class__._key_counter += 1
        response = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
            headers={
                "Idempotency-Key": f"feedback-analyze-{self._key_counter}"
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["interaction"]

    def _put_rating(
        self,
        analysis_id: str,
        target: str,
        token: str,
        *,
        vote: str = "up",
    ):
        return self.client.put(
            f"/api/v2/analyses/{analysis_id}/ratings/{target}",
            json={"vote": vote, "reason_codes": [], "comment": None},
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_upsert_and_replace_rating(self) -> None:
        interaction = self._analyze()
        target = "lighting"

        first = self._put_rating(
            interaction["analysis_id"], target, interaction["feedback_token"]
        )
        self.assertEqual(first.status_code, 200)
        receipt = first.json()
        self.assertEqual(receipt["target"], target)
        self.assertEqual(receipt["vote"], "up")

        replaced = self._put_rating(
            interaction["analysis_id"],
            target,
            interaction["feedback_token"],
            vote="down",
        )
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(replaced.json()["rating_id"], receipt["rating_id"])
        self.assertEqual(replaced.json()["vote"], "down")

    def test_delete_rating_is_always_204(self) -> None:
        interaction = self._analyze()
        target = "composition"
        headers = {"Authorization": f"Bearer {interaction['feedback_token']}"}

        first = self.client.delete(
            f"/api/v2/analyses/{interaction['analysis_id']}/ratings/{target}",
            headers=headers,
        )
        second = self.client.delete(
            f"/api/v2/analyses/{interaction['analysis_id']}/ratings/{target}",
            headers=headers,
        )
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)

    def test_token_cannot_rate_other_analyses(self) -> None:
        first_interaction = self._analyze()
        second_interaction = self._analyze()

        response = self._put_rating(
            second_interaction["analysis_id"],
            "color",
            first_interaction["feedback_token"],
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["code"], "feedback_forbidden"
        )

    def test_invalid_token_and_unknown_analysis(self) -> None:
        interaction = self._analyze()

        invalid = self._put_rating(
            interaction["analysis_id"], "color", "Z" * 43
        )
        self.assertEqual(invalid.status_code, 403)

        missing_analysis = self.client.put(
            "/api/v2/analyses/00000000-0000-0000-0000-000000000000/ratings/color",
            json={"vote": "up", "reason_codes": []},
            headers={
                "Authorization": f"Bearer {interaction['feedback_token']}"
            },
        )
        self.assertEqual(missing_analysis.status_code, 404)
        self.assertEqual(
            missing_analysis.json()["error"]["code"], "analysis_not_found"
        )

    def test_invalid_target_and_payload_are_422(self) -> None:
        interaction = self._analyze()

        bad_target = self.client.put(
            f"/api/v2/analyses/{interaction['analysis_id']}/ratings/not_a_target",
            json={"vote": "up"},
            headers={
                "Authorization": f"Bearer {interaction['feedback_token']}"
            },
        )
        self.assertEqual(bad_target.status_code, 422)

        duplicate_reasons = self.client.put(
            f"/api/v2/analyses/{interaction['analysis_id']}/ratings/color",
            json={
                "vote": "down",
                "reason_codes": ["generic_advice", "generic_advice"],
            },
            headers={
                "Authorization": f"Bearer {interaction['feedback_token']}"
            },
        )
        self.assertEqual(duplicate_reasons.status_code, 422)

    def test_problem_report_flow(self) -> None:
        interaction = self._analyze()

        created = self.client.post(
            "/api/v2/problem-reports",
            json={
                "analysis_id": interaction["analysis_id"],
                "category": "report_quality",
                "message": "光影建议没有考虑画面中主体已经处于剪影状态。",
                "include_runtime_metadata": True,
            },
        )
        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()["status"], "new")

        too_short = self.client.post(
            "/api/v2/problem-reports",
            json={"category": "bug", "message": "太短"},
        )
        self.assertEqual(too_short.status_code, 422)

    def test_all_eight_targets_accept_upsert_and_delete(self) -> None:
        interaction = self._analyze()
        targets = [
            "composition",
            "lighting",
            "color",
            "subject_expression",
            "visual_storytelling",
            "priority_actions",
            "shooting_exercise",
            "overall",
        ]
        headers = {"Authorization": f"Bearer {interaction['feedback_token']}"}
        analysis_id = interaction["analysis_id"]

        for target in targets:
            created = self.client.put(
                f"/api/v2/analyses/{analysis_id}/ratings/{target}",
                json={"vote": "up", "reason_codes": []},
                headers=headers,
            )
            self.assertEqual(created.status_code, 200, target)
            self.assertEqual(created.json()["target"], target)

            deleted = self.client.delete(
                f"/api/v2/analyses/{analysis_id}/ratings/{target}",
                headers=headers,
            )
            self.assertEqual(deleted.status_code, 204, target)

    def test_feedback_rate_limiting(self) -> None:
        interaction = self._analyze()
        with patch.object(
            public_routes, "RATINGS_PER_TOKEN_HOUR", 1
        ):
            first = self._put_rating(
                interaction["analysis_id"], "overall", interaction["feedback_token"]
            )
            self.assertEqual(first.status_code, 200)

            second = self._put_rating(
                interaction["analysis_id"], "color", interaction["feedback_token"]
            )
            self.assertEqual(second.status_code, 429)
            self.assertEqual(
                second.json()["error"]["code"], "feedback_rate_limited"
            )


if __name__ == "__main__":
    unittest.main()
