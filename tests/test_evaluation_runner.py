"""Tests for sequential evaluation runs and saved snapshots."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from photography_coach.evals.dataset import EvaluationCase, EvaluationDataset
from photography_coach.evals.runner import EvaluationRun, run_dataset
from photography_coach.providers.mock import MockPhotographyProvider
from photography_coach.services.analysis import AnalysisService


class _FailFirstService(AnalysisService):
    def __init__(self) -> None:
        super().__init__(MockPhotographyProvider(), timeout_seconds=1)
        self.calls = 0

    async def analyze(self, image_bytes, image, shooting_intent):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first case failed")
        return await super().analyze(image_bytes, image, shooting_intent)


class _ChainedFailureService(AnalysisService):
    def __init__(self) -> None:
        super().__init__(MockPhotographyProvider(), timeout_seconds=1)

    async def analyze(self, image_bytes, image, shooting_intent):
        try:
            raise ValueError("schema detail")
        except ValueError as cause:
            raise RuntimeError("public error") from cause


class EvaluationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_saves_successful_results(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "Photos/test/photo.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(_jpeg_bytes())
            dataset = _dataset(["case-01"])
            output_path = root / "results/run.json"

            run = await run_dataset(
                dataset,
                project_root=root,
                output_path=output_path,
                service=AnalysisService(MockPhotographyProvider(), timeout_seconds=1),
            )

            saved = EvaluationRun.model_validate_json(output_path.read_text(encoding="utf-8"))
            self.assertEqual(run.cases[0].status, "succeeded")
            self.assertEqual(saved.cases[0].response.metadata.provider, "mock")
            self.assertIsNotNone(saved.completed_at)

    async def test_records_failure_and_continues_to_later_cases(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = _dataset(["case-01", "case-02"])
            for case in dataset.cases:
                image_path = root / case.image_path
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(_jpeg_bytes())
            output_path = root / "results/run.json"

            run = await run_dataset(
                dataset,
                project_root=root,
                output_path=output_path,
                service=_FailFirstService(),
            )

            self.assertEqual([case.status for case in run.cases], ["failed", "succeeded"])
            self.assertEqual(run.cases[0].error_type, "RuntimeError")
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["cases"]), 2)

    async def test_resume_skips_successes_and_retries_failures(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = _dataset(["case-01", "case-02"])
            for case in dataset.cases:
                image_path = root / case.image_path
                image_path.parent.mkdir(parents=True, exist_ok=True)
                image_path.write_bytes(_jpeg_bytes())
            output_path = root / "results/run.json"
            first_service = _FailFirstService()
            first_run = await run_dataset(
                dataset,
                project_root=root,
                output_path=output_path,
                service=first_service,
            )
            retry_service = _CountingService()

            resumed = await run_dataset(
                dataset,
                project_root=root,
                output_path=output_path,
                service=retry_service,
                previous_run=first_run,
            )

            self.assertEqual([case.status for case in resumed.cases], ["succeeded", "succeeded"])
            self.assertEqual(retry_service.calls, 1)
            self.assertEqual(resumed.run_id, first_run.run_id)

    async def test_saves_bounded_cause_for_local_diagnosis(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = _dataset(["case-01"])
            image_path = root / dataset.cases[0].image_path
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(_jpeg_bytes())

            run = await run_dataset(
                dataset,
                project_root=root,
                output_path=root / "results/run.json",
                service=_ChainedFailureService(),
            )

            self.assertIn("public error", run.cases[0].error_message)
            self.assertIn("cause=ValueError: schema detail", run.cases[0].error_message)


def _dataset(case_ids: list[str]) -> EvaluationDataset:
    return EvaluationDataset(
        dataset_id="test-set",
        description="Runner tests.",
        cases=[
            EvaluationCase(
                case_id=case_id,
                image_path="Photos/test/photo.jpg" if index == 0 else f"Photos/test/photo-{index}.jpg",
                sha256="0" * 64,
                category="portrait",
                intent=None,
                tags=["portrait"],
            )
            for index, case_id in enumerate(case_ids)
        ],
    )


class _CountingService(AnalysisService):
    def __init__(self) -> None:
        super().__init__(MockPhotographyProvider(), timeout_seconds=1)
        self.calls = 0

    async def analyze(self, image_bytes, image, shooting_intent):
        self.calls += 1
        return await super().analyze(image_bytes, image, shooting_intent)


def _jpeg_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (8, 8), color="navy").save(output, format="JPEG")
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
