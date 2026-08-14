"""Tests for the reusable V2 real-provider smoke runner."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from photography_coach.config import Settings
from photography_coach.dependencies import build_rag_analysis_service
from scripts.smoke_test_rag_pipeline import run_photos


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (12, 8), color=(80, 100, 120)).save(
        buffer,
        format="JPEG",
    )
    return buffer.getvalue()


class RagSmokeRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_one_mock_service_for_multiple_photos(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            first_photo = temporary_root / "first.jpg"
            second_photo = temporary_root / "second.jpg"
            first_photo.write_bytes(_jpeg_bytes())
            second_photo.write_bytes(_jpeg_bytes())
            service = await build_rag_analysis_service(
                Settings(
                    _env_file=None,
                    model_provider="mock",
                    rag_enabled=True,
                    embedding_dimensions=128,
                    chroma_path=temporary_root / "chroma",
                )
            )

            records = await run_photos(
                [first_photo, second_photo],
                output_dir=temporary_root / "results",
                service=service,
            )

            self.assertEqual(
                [record["status"] for record in records],
                ["succeeded", "succeeded"],
            )
            self.assertEqual(len(list((temporary_root / "results").glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
