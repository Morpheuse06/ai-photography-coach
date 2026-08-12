"""Tests for the photography report contract."""

import copy
import unittest

from pydantic import ValidationError

from photography_coach.schemas import PhotographyReport


def _dimension_payload() -> dict[str, object]:
    return {
        "rating": 4,
        "summary": "The subject is placed clearly within the frame.",
        "visual_evidence": ["The subject sits close to the left third line."],
        "strengths": ["Negative space separates the subject from the background."],
        "main_issue": "A bright object near the right edge competes for attention.",
        "improvement_suggestions": ["Move slightly left to exclude the bright object."],
    }


def _valid_report_payload() -> dict[str, object]:
    return {
        "dimensions": {
            "composition": _dimension_payload(),
            "lighting": _dimension_payload(),
            "color": _dimension_payload(),
            "subject_expression": _dimension_payload(),
            "visual_storytelling": _dimension_payload(),
        },
        "priority_actions": [
            {
                "priority": 1,
                "action": "Remove the bright edge distraction.",
                "reason": "It pulls attention away from the subject.",
            },
            {
                "priority": 2,
                "action": "Wait for softer side light.",
                "reason": "It will add shape without harsh highlights.",
            },
            {
                "priority": 3,
                "action": "Include one contextual detail.",
                "reason": "It can make the scene's story clearer.",
            },
        ],
        "next_shooting_exercise": {
            "title": "Clean-frame practice",
            "objective": "Learn to notice distractions before pressing the shutter.",
            "steps": ["Photograph one subject from three positions."],
            "success_criteria": ["No bright object touches any frame edge."],
        },
    }


class PhotographyReportTests(unittest.TestCase):
    def test_accepts_a_complete_report(self) -> None:
        report = PhotographyReport.model_validate(_valid_report_payload())

        self.assertEqual(report.dimensions.composition.rating, 4)
        self.assertEqual([item.priority for item in report.priority_actions], [1, 2, 3])

    def test_rejects_a_rating_above_five(self) -> None:
        payload = _valid_report_payload()
        payload["dimensions"]["composition"]["rating"] = 6  # type: ignore[index]

        with self.assertRaises(ValidationError):
            PhotographyReport.model_validate(payload)

    def test_requires_exactly_three_priority_actions(self) -> None:
        payload = _valid_report_payload()
        payload["priority_actions"] = payload["priority_actions"][:2]  # type: ignore[index]

        with self.assertRaises(ValidationError):
            PhotographyReport.model_validate(payload)

    def test_requires_priority_actions_in_order(self) -> None:
        payload = _valid_report_payload()
        actions = payload["priority_actions"]  # type: ignore[assignment]
        actions[0]["priority"], actions[1]["priority"] = 2, 1  # type: ignore[index]

        with self.assertRaises(ValidationError):
            PhotographyReport.model_validate(payload)

    def test_rejects_unknown_fields(self) -> None:
        payload = copy.deepcopy(_valid_report_payload())
        payload["camera_model"] = "A model must not invent this value."

        with self.assertRaises(ValidationError):
            PhotographyReport.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
