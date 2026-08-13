"""Tests for the human report-evaluation contract."""

import unittest

from pydantic import ValidationError

from photography_coach.evals.schemas import (
    CriterionScore,
    EvaluationIssue,
    EvaluationScores,
    ReportEvaluation,
)


def _criterion(score: int = 4) -> CriterionScore:
    return CriterionScore(score=score, rationale="判断有具体依据。")


def _evaluation(
    *,
    scores: EvaluationScores | None = None,
    issues: list[EvaluationIssue] | None = None,
) -> ReportEvaluation:
    return ReportEvaluation(
        report_id="portrait-001-qwen3.7-plus-v1",
        model="qwen3.7-plus",
        prompt_version="photography-coach-v1.0",
        evaluator="Morpheuse06",
        scores=scores or EvaluationScores(
            visual_grounding=_criterion(),
            factual_reliability=_criterion(5),
            actionability=_criterion(),
            problem_solution_alignment=_criterion(),
            priority_quality=_criterion(),
            exercise_quality=_criterion(),
        ),
        critical_issues=issues or [],
        notes="报告整体具体，可以指导下一次拍摄。",
    )


class ReportEvaluationTests(unittest.TestCase):
    def test_calculates_total_and_passes_a_good_evaluation(self) -> None:
        evaluation = _evaluation()

        self.assertEqual(evaluation.total_score, 25)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.model_dump()["total_score"], 25)

    def test_rejects_scores_outside_one_to_five(self) -> None:
        for score in (0, 6):
            with self.subTest(score=score):
                with self.assertRaises(ValidationError):
                    CriterionScore(score=score, rationale="有理由。")

    def test_rejects_an_empty_rationale(self) -> None:
        with self.assertRaises(ValidationError):
            CriterionScore(score=4, rationale="   ")

    def test_fails_when_the_total_is_below_twenty_two(self) -> None:
        scores = EvaluationScores(
            visual_grounding=_criterion(3),
            factual_reliability=_criterion(4),
            actionability=_criterion(3),
            problem_solution_alignment=_criterion(3),
            priority_quality=_criterion(3),
            exercise_quality=_criterion(3),
        )

        evaluation = _evaluation(scores=scores)

        self.assertEqual(evaluation.total_score, 19)
        self.assertFalse(evaluation.passed)

    def test_fails_when_factual_reliability_is_below_four(self) -> None:
        scores = EvaluationScores(
            visual_grounding=_criterion(5),
            factual_reliability=_criterion(3),
            actionability=_criterion(5),
            problem_solution_alignment=_criterion(5),
            priority_quality=_criterion(5),
            exercise_quality=_criterion(5),
        )

        evaluation = _evaluation(scores=scores)

        self.assertEqual(evaluation.total_score, 28)
        self.assertFalse(evaluation.passed)

    def test_fails_when_visual_grounding_is_below_three(self) -> None:
        scores = EvaluationScores(
            visual_grounding=_criterion(2),
            factual_reliability=_criterion(5),
            actionability=_criterion(5),
            problem_solution_alignment=_criterion(5),
            priority_quality=_criterion(5),
            exercise_quality=_criterion(5),
        )

        evaluation = _evaluation(scores=scores)

        self.assertEqual(evaluation.total_score, 27)
        self.assertFalse(evaluation.passed)

    def test_disqualifying_issue_fails_an_otherwise_good_report(self) -> None:
        issue = EvaluationIssue(
            category="invented_equipment",
            description="报告虚构了镜头焦段。",
            evidence="报告声称照片使用了 85mm 镜头。",
        )

        evaluation = _evaluation(issues=[issue])

        self.assertEqual(evaluation.total_score, 25)
        self.assertFalse(evaluation.passed)

    def test_non_disqualifying_issue_can_still_pass(self) -> None:
        issue = EvaluationIssue(
            category="generic_advice",
            description="一条建议不够具体。",
            evidence="报告只写了尝试调整构图。",
        )

        evaluation = _evaluation(issues=[issue])

        self.assertTrue(evaluation.passed)

    def test_rejects_unknown_fields(self) -> None:
        payload = _evaluation().model_dump(exclude={"total_score", "passed"})
        payload["unexpected"] = "not allowed"

        with self.assertRaises(ValidationError):
            ReportEvaluation.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
