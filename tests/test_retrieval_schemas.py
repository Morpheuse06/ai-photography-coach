"""Tests for photo observation and RAG retrieval-plan contracts."""

import unittest

from pydantic import ValidationError

from photography_coach.knowledge.retrieval import (
    PhotoObservation,
    RetrievalPlan,
    RetrievalQuery,
    VisibleEvidence,
)


def _evidence(**overrides) -> VisibleEvidence:
    payload = {
        "evidence_id": "lighting-window-contrast",
        "dimension": "lighting",
        "description": "画面右侧窗户区域明显亮于人物面部，人物面部的明暗细节相对较弱。",
        "location": "画面右侧窗户与中部人物面部",
    }
    payload.update(overrides)
    return VisibleEvidence.model_validate(payload)


def _observation(**overrides) -> PhotoObservation:
    payload = {
        "scene_summary": "一名人物靠近粉色花束，右侧窗户提供了画面中最明亮的区域。",
        "evidence": [_evidence()],
        "unknowns": ["无法仅凭图片确定相机、镜头和曝光参数"],
    }
    payload.update(overrides)
    return PhotoObservation.model_validate(payload)


def _query(**overrides) -> RetrievalQuery:
    payload = {
        "query_id": "lighting-backlight-balance",
        "dimension": "lighting",
        "evidence_ids": ["lighting-window-contrast"],
        "query_text": "窗边逆光人像中，怎样保留人物面部细节并控制明亮背景的视觉干扰？",
        "teaching_goal": "学习处理主体与背景之间的亮度关系",
        "top_k": 2,
    }
    payload.update(overrides)
    return RetrievalQuery.model_validate(payload)


def _plan(**overrides) -> RetrievalPlan:
    payload = {
        "user_intent": "表现人物与花束之间温柔、安静的关系",
        "observation": _observation(),
        "queries": [_query()],
        "max_total_chunks": 6,
    }
    payload.update(overrides)
    return RetrievalPlan.model_validate(payload)


class PhotoObservationTests(unittest.TestCase):
    def test_accepts_visible_evidence_and_explicit_unknowns(self) -> None:
        observation = _observation()

        self.assertEqual(observation.evidence[0].dimension, "lighting")
        self.assertIn("无法", observation.unknowns[0])

    def test_rejects_duplicate_evidence_ids(self) -> None:
        evidence = _evidence()

        with self.assertRaisesRegex(ValidationError, "evidence_id"):
            _observation(evidence=[evidence, evidence])

    def test_requires_at_least_one_unknown(self) -> None:
        with self.assertRaises(ValidationError):
            _observation(unknowns=[])

    def test_rejects_non_photography_dimension(self) -> None:
        with self.assertRaises(ValidationError):
            _evidence(dimension="camera_brand")


class RetrievalQueryTests(unittest.TestCase):
    def test_accepts_a_standalone_embedding_query(self) -> None:
        query = _query()

        self.assertEqual(query.top_k, 2)
        self.assertIn("逆光", query.query_text)

    def test_rejects_duplicate_evidence_references(self) -> None:
        evidence_id = "lighting-window-contrast"

        with self.assertRaisesRegex(ValidationError, "evidence_ids"):
            _query(evidence_ids=[evidence_id, evidence_id])

    def test_limits_each_query_to_three_results(self) -> None:
        with self.assertRaises(ValidationError):
            _query(top_k=4)


class RetrievalPlanTests(unittest.TestCase):
    def test_accepts_queries_grounded_in_the_observation(self) -> None:
        plan = _plan()

        self.assertEqual(plan.queries[0].evidence_ids[0], "lighting-window-contrast")
        self.assertEqual(plan.max_total_chunks, 6)

    def test_rejects_query_that_references_missing_evidence(self) -> None:
        query = _query(evidence_ids=["missing-evidence"])

        with self.assertRaisesRegex(ValidationError, "unknown evidence_ids"):
            _plan(queries=[query])

    def test_rejects_query_with_mismatched_dimension(self) -> None:
        query = _query(dimension="composition")

        with self.assertRaisesRegex(ValidationError, "from its dimension"):
            _plan(queries=[query])

    def test_allows_general_query_to_use_any_visible_evidence(self) -> None:
        query = _query(
            query_id="general-practice",
            dimension="general",
            query_text="如何围绕照片中可见的主体明暗关系设计一次单变量对照拍摄练习？",
        )

        plan = _plan(queries=[query])

        self.assertEqual(plan.queries[0].dimension, "general")

    def test_rejects_duplicate_query_text(self) -> None:
        first = _query()
        second = _query(query_id="lighting-backlight-copy")

        with self.assertRaisesRegex(ValidationError, "query_text"):
            _plan(queries=[first, second])

    def test_rejects_more_than_five_queries(self) -> None:
        queries = [
            _query(
                query_id=f"lighting-query-{index}",
                query_text=(
                    "窗边逆光人像中，怎样根据画面证据处理主体和背景亮度关系？"
                    f"练习版本 {index}。"
                ),
            )
            for index in range(6)
        ]

        with self.assertRaises(ValidationError):
            _plan(queries=queries)


if __name__ == "__main__":
    unittest.main()
