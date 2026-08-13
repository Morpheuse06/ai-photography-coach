"""Tests for repeatable local evaluation datasets."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pydantic import ValidationError

from photography_coach.evals.dataset import EvaluationDataset, load_dataset


def _manifest(image_digest: str) -> dict:
    return {
        "dataset_id": "test-set",
        "description": "Small test dataset.",
        "cases": [
            {
                "case_id": "test-01",
                "image_path": "Photos/test/photo.jpg",
                "sha256": image_digest,
                "category": "portrait",
                "intent": None,
                "tags": ["portrait", "window-light"],
            }
        ],
    }


class EvaluationDatasetTests(unittest.TestCase):
    def test_loads_existing_file_when_digest_matches(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "Photos/test/photo.jpg"
            image_path.parent.mkdir(parents=True)
            image_bytes = b"stable photo bytes"
            image_path.write_bytes(image_bytes)
            manifest_path = root / "dataset.json"
            manifest_path.write_text(
                json.dumps(_manifest(sha256(image_bytes).hexdigest())),
                encoding="utf-8",
            )

            dataset = load_dataset(manifest_path, root)

            self.assertEqual(dataset.dataset_id, "test-set")
            self.assertEqual(dataset.cases[0].case_id, "test-01")

    def test_rejects_duplicate_case_ids(self) -> None:
        payload = _manifest("0" * 64)
        duplicate = {**payload["cases"][0], "image_path": "Photos/test/other.jpg"}
        payload["cases"].append(duplicate)

        with self.assertRaises(ValidationError):
            EvaluationDataset.model_validate(payload)

    def test_rejects_unknown_category(self) -> None:
        payload = _manifest("0" * 64)
        payload["cases"][0]["category"] = "food"

        with self.assertRaises(ValidationError):
            EvaluationDataset.model_validate(payload)

    def test_rejects_missing_image(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "dataset.json"
            manifest_path.write_text(json.dumps(_manifest("0" * 64)), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not exist"):
                load_dataset(manifest_path, root)

    def test_rejects_changed_image_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "Photos/test/photo.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"changed bytes")
            manifest_path = root / "dataset.json"
            manifest_path.write_text(json.dumps(_manifest("0" * 64)), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_dataset(manifest_path, root)


if __name__ == "__main__":
    unittest.main()
