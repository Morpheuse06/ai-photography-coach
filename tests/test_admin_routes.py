"""HTTP tests for the management API routes."""

import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from PIL import Image

from photography_coach.config import Settings
from photography_coach.main import create_app
from photography_coach.persistence.admin_auth import SqlAdminAuthService
from photography_coach.persistence.engine import session_factory_for

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADMIN_USERNAME = "owner"
ADMIN_PASSWORD = "correct horse battery staple"


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color=(40, 80, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


class AdminRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            _env_file=None,
            model_provider="mock",
            rag_enabled=True,
            control_plane_enabled=True,
            database_url=(
                f"sqlite+aiosqlite:///{Path(cls._tmp.name) / 'admin.db'}"
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

        asyncio.run(cls._seed_admin_user())
        response = cls.client.post(
            "/api/admin/v1/sessions",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        if response.status_code != 201:
            raise AssertionError(f"admin login failed: {response.json()}")
        cls._token = response.json()["access_token"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()

    @staticmethod
    async def _seed_admin_user() -> None:
        engine = AdminRouteTests.app.state.db_engine
        async with session_factory_for(engine)() as session:
            service = SqlAdminAuthService(
                session,
                session_ttl_hours=12,
                password_hasher=PasswordHasher(time_cost=1, memory_cost=1_024),
            )
            await service.create_admin_user(ADMIN_USERNAME, ADMIN_PASSWORD)

    # ------------------------------------------------------------- helpers

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _analyze(self, key: str | None = None) -> dict:
        response = self.client.post(
            "/api/v2/analyze",
            files={"photo": ("sample.png", _png_bytes(), "image/png")},
            data={"intent": "表现安静的环境人像"},
            headers={"Idempotency-Key": key or str(uuid4())},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # --------------------------------------------------------------- tests

    def test_admin_routes_require_authentication(self) -> None:
        for path in [
            "/api/admin/v1/overview",
            "/api/admin/v1/access-policy",
            "/api/admin/v1/access-codes",
            "/api/admin/v1/analysis-runs",
            "/api/admin/v1/ratings/summary",
            "/api/admin/v1/problem-reports",
            "/api/admin/v1/system/status",
            "/api/admin/v1/audit-events",
        ]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)

        self.assertEqual(
            self.client.get("/api/admin/v1/overview", headers=self._headers()).status_code,
            200,
        )

    def test_login_failures_are_uniform(self) -> None:
        wrong_password = self.client.post(
            "/api/admin/v1/sessions",
            json={"username": ADMIN_USERNAME, "password": "wrong password!"},
        )
        unknown_user = self.client.post(
            "/api/admin/v1/sessions",
            json={"username": "nobody", "password": "whatever password"},
        )

        for response in (wrong_password, unknown_user):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["error"]["code"], "admin_authentication_failed"
            )

    def test_logout_revokes_the_current_session(self) -> None:
        response = self.client.post(
            "/api/admin/v1/sessions",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        self.assertEqual(
            self.client.delete(
                "/api/admin/v1/sessions/current", headers=headers
            ).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(
                "/api/admin/v1/overview", headers=headers
            ).status_code,
            401,
        )

    def test_patch_policy_creates_audit_event(self) -> None:
        patched = self.client.patch(
            "/api/admin/v1/access-policy",
            json={"mode": "closed"},
            headers=self._headers(),
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["mode"], "closed")

        self.client.patch(
            "/api/admin/v1/access-policy",
            json={"mode": "open"},
            headers=self._headers(),
        )

        events = self.client.get(
            "/api/admin/v1/audit-events",
            headers=self._headers(),
        ).json()["items"]
        self.assertTrue(
            any(
                event["action"] == "access_policy.updated"
                for event in events
            )
        )

    def test_access_code_batch_lifecycle(self) -> None:
        created = self.client.post(
            "/api/admin/v1/access-code-batches",
            json={"quantity": 2, "uses_per_code": 3, "label": "launch"},
            headers=self._headers(),
        )
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(len(body["codes"]), 2)
        raw_codes = [code["code"] for code in body["codes"]]
        self.assertTrue(all(code.startswith("PXC-") for code in raw_codes))
        code_ids = [code["code_id"] for code in body["codes"]]

        listed = self.client.get(
            "/api/admin/v1/access-codes", headers=self._headers()
        )
        self.assertEqual(listed.status_code, 200)
        page = listed.json()
        self.assertEqual(page["page"]["total_items"], 2)
        self.assertNotIn("code", page["items"][0])
        self.assertEqual(
            {item["prefix"] for item in page["items"]},
            {raw[:8] for raw in raw_codes},
        )

        single = self.client.get(
            f"/api/admin/v1/access-codes/{code_ids[0]}",
            headers=self._headers(),
        )
        self.assertEqual(single.status_code, 200)
        self.assertEqual(single.json()["uses_total"], 3)

        patched = self.client.patch(
            f"/api/admin/v1/access-codes/{code_ids[0]}",
            json={"label": "relaunch"},
            headers=self._headers(),
        )
        self.assertEqual(patched.json()["label"], "relaunch")

        granted = self.client.post(
            f"/api/admin/v1/access-codes/{code_ids[0]}/grants",
            json={"additional_uses": 2, "reason": "beta extension"},
            headers=self._headers(),
        )
        self.assertEqual(granted.json()["uses_total"], 5)

        revoked = self.client.post(
            f"/api/admin/v1/access-codes/{code_ids[0]}/revoke",
            json={"reason": "compromised"},
            headers=self._headers(),
        )
        self.assertEqual(revoked.json()["status"], "revoked")

        events = self.client.get(
            f"/api/admin/v1/access-codes/{code_ids[0]}/usage-events",
            headers=self._headers(),
        )
        self.assertEqual(events.status_code, 200)
        self.assertEqual(events.json()["page"]["total_items"], 0)

    def test_analysis_runs_list_and_detail(self) -> None:
        interaction = self._analyze()["interaction"]

        listed = self.client.get(
            "/api/admin/v1/analysis-runs",
            params={"status": "succeeded"},
            headers=self._headers(),
        )
        self.assertEqual(listed.status_code, 200)
        items = listed.json()["items"]
        self.assertTrue(
            any(item["analysis_id"] == interaction["analysis_id"] for item in items)
        )

        detail = self.client.get(
            f"/api/admin/v1/analysis-runs/{interaction['analysis_id']}",
            headers=self._headers(),
        )
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertIsNotNone(body["report"])
        self.assertIsNotNone(body["shooting_intent"])
        self.assertIsNotNone(body["metadata"])

    def test_ratings_summary_and_filters(self) -> None:
        interaction = self._analyze()["interaction"]
        headers = {
            "Authorization": f"Bearer {interaction['feedback_token']}"
        }
        down = self.client.put(
            f"/api/v2/analyses/{interaction['analysis_id']}/ratings/lighting",
            json={
                "vote": "down",
                "reason_codes": ["generic_advice"],
            },
            headers=headers,
        )
        self.assertEqual(down.status_code, 200)
        up = self.client.put(
            f"/api/v2/analyses/{interaction['analysis_id']}/ratings/color",
            json={"vote": "up", "reason_codes": []},
            headers=headers,
        )
        self.assertEqual(up.status_code, 200)

        summary = self.client.get(
            "/api/admin/v1/ratings/summary", headers=self._headers()
        ).json()
        self.assertEqual(len(summary["items"]), 8)
        by_target = {item["target"]: item for item in summary["items"]}
        self.assertEqual(by_target["lighting"]["down_votes"], 1)
        self.assertEqual(by_target["color"]["up_votes"], 1)

        down_only = self.client.get(
            "/api/admin/v1/ratings",
            params={"vote": "down"},
            headers=self._headers(),
        ).json()["items"]
        self.assertTrue(
            all(item["vote"] == "down" for item in down_only)
        )

        by_reason = self.client.get(
            "/api/admin/v1/ratings",
            params={"reason_code": "generic_advice"},
            headers=self._headers(),
        ).json()["items"]
        self.assertTrue(
            any(item["target"] == "lighting" for item in by_reason)
        )

    def test_problem_reports_admin_flow(self) -> None:
        created = self.client.post(
            "/api/v2/problem-reports",
            json={
                "category": "usability",
                "message": "页面的反馈入口不够明显，希望放在更靠前的位置。",
            },
        )
        report_id = created.json()["problem_report_id"]

        listed = self.client.get(
            "/api/admin/v1/problem-reports", headers=self._headers()
        ).json()["items"]
        self.assertTrue(
            any(item["problem_report_id"] == report_id for item in listed)
        )

        patched = self.client.patch(
            f"/api/admin/v1/problem-reports/{report_id}",
            json={"status": "in_progress", "priority": "high", "tags": ["ux"]},
            headers=self._headers(),
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["status"], "in_progress")
        self.assertEqual(patched.json()["priority"], "high")
        self.assertEqual(
            patched.json()["message"], "页面的反馈入口不够明显，希望放在更靠前的位置。"
        )

    def test_overview_window_and_totals(self) -> None:
        self._analyze()

        overview = self.client.get(
            "/api/admin/v1/overview", headers=self._headers()
        )
        self.assertEqual(overview.status_code, 200)
        body = overview.json()
        self.assertGreaterEqual(body["totals"]["analyses_total"], 1)
        self.assertGreater(len(body["series"]), 0)

        invalid_range = self.client.get(
            "/api/admin/v1/overview",
            params={"from": "2026-08-15T00:00:00Z", "to": "2026-08-14T00:00:00Z"},
            headers=self._headers(),
        )
        self.assertEqual(invalid_range.status_code, 422)
        self.assertEqual(
            invalid_range.json()["error"]["code"], "invalid_request"
        )

        too_long = self.client.get(
            "/api/admin/v1/overview",
            params={
                "from": "2025-01-01T00:00:00Z",
                "to": "2026-08-15T00:00:00Z",
            },
            headers=self._headers(),
        )
        self.assertEqual(too_long.status_code, 422)

    def test_system_status_and_versions(self) -> None:
        status = self.client.get(
            "/api/admin/v1/system/status", headers=self._headers()
        )
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["rag_enabled"])
        self.assertTrue(body["knowledge_index_ready"])

        versions = self.client.get(
            "/api/admin/v1/system/versions", headers=self._headers()
        )
        self.assertEqual(versions.status_code, 200)
        self.assertEqual(versions.json()["provider"], "mock")
        self.assertTrue(versions.json()["report_prompt_version"].startswith("photography-coach-rag"))

    def test_csv_exports_escape_formula_injection(self) -> None:
        injected = "=1+1 计算表格注入尝试文本"
        self.client.post(
            "/api/v2/problem-reports",
            json={"category": "other", "message": injected},
        )

        exported = self.client.get(
            "/api/admin/v1/exports/problem-reports.csv",
            headers=self._headers(),
        )
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported.headers["content-type"])
        self.assertIn(f",'{injected},", exported.text)
        self.assertNotIn(f",{injected},", exported.text)

        runs_csv = self.client.get(
            "/api/admin/v1/exports/analysis-runs.csv",
            headers=self._headers(),
        )
        self.assertEqual(runs_csv.status_code, 200)
        self.assertIn("analysis_id", runs_csv.text)

        ratings_csv = self.client.get(
            "/api/admin/v1/exports/ratings.csv",
            headers=self._headers(),
        )
        self.assertEqual(ratings_csv.status_code, 200)
        self.assertIn("rating_id", ratings_csv.text)

    def test_pagination_metadata(self) -> None:
        created = self.client.post(
            "/api/admin/v1/access-code-batches",
            json={"quantity": 2, "uses_per_code": 1},
            headers=self._headers(),
        )
        self.assertEqual(created.status_code, 201)
        batch_id = created.json()["batch_id"]

        page = self.client.get(
            "/api/admin/v1/access-codes",
            params={"batch_id": batch_id, "page": 1, "page_size": 1},
            headers=self._headers(),
        ).json()
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["page"]["total_items"], 2)
        self.assertEqual(page["page"]["total_pages"], 2)


if __name__ == "__main__":
    unittest.main()
