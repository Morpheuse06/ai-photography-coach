"""Tests for RAG knowledge source and chunk contracts."""

import unittest

from pydantic import ValidationError

from photography_coach.knowledge.schemas import (
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeSource,
)


def _source(**overrides) -> KnowledgeSource:
    payload = {
        "source_id": "project-lighting-guide",
        "title": "摄影教练光线手册",
        "kind": "project_authored",
        "version": "1.0",
        "authors": ["AI Photography Coach Project"],
        "usage_rights": "project_owned",
        "source_uri": None,
        "description": "为初学者整理的现场用光知识。",
    }
    payload.update(overrides)
    return KnowledgeSource.model_validate(payload)


def _chunk(**overrides) -> KnowledgeChunk:
    payload = {
        "chunk_id": "project-lighting-guide-001",
        "source_id": "project-lighting-guide",
        "source_version": "1.0",
        "section_path": ["第 2 章 光线", "2.3 逆光下的主体亮度"],
        "chunk_index": 1,
        "source_locator": "第 2 章 > 2.3，第 1—3 段",
        "dimension": "lighting",
        "difficulty": "beginner",
        "content": "当背景明显亮于主体时，先确定是要保留主体细节，还是有意表现轮廓。两种目标需要不同的拍摄位置。",
        "applicable_scenarios": ["背景明显亮于人物或物体"],
        "actionable_guidance": ["移动拍摄位置，观察主体朝向改变后的亮度"],
        "limitations": ["不能据此推断照片使用了闪光灯或具体曝光参数"],
        "tags": ["backlight", "subject-exposure"],
    }
    payload.update(overrides)
    return KnowledgeChunk.model_validate(payload)


class KnowledgeSourceTests(unittest.TestCase):
    def test_accepts_a_project_authored_manual(self) -> None:
        source = _source()

        self.assertEqual(source.kind, "project_authored")
        self.assertEqual(source.usage_rights, "project_owned")

    def test_external_source_requires_a_traceable_uri(self) -> None:
        with self.assertRaisesRegex(ValidationError, "source_uri"):
            _source(kind="book", usage_rights="licensed")

    def test_project_authored_source_must_be_project_owned(self) -> None:
        with self.assertRaisesRegex(ValidationError, "project_owned"):
            _source(usage_rights="licensed")

    def test_rejects_duplicate_authors(self) -> None:
        with self.assertRaisesRegex(ValidationError, "authors must be unique"):
            _source(authors=["Editor", "Editor"])

    def test_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            _source(copyright_note="unknown")


class KnowledgeChunkTests(unittest.TestCase):
    def test_accepts_a_traceable_chunk_from_a_manual_section(self) -> None:
        chunk = _chunk()

        self.assertEqual(chunk.section_path[-1], "2.3 逆光下的主体亮度")
        self.assertEqual(chunk.dimension, "lighting")

    def test_rejects_content_that_is_too_short_to_be_useful(self) -> None:
        with self.assertRaises(ValidationError):
            _chunk(content="逆光要注意曝光。")

    def test_rejects_an_unknown_dimension(self) -> None:
        with self.assertRaises(ValidationError):
            _chunk(dimension="exposure_triangle")

    def test_rejects_duplicate_guidance(self) -> None:
        guidance = "移动拍摄位置，观察主体亮度变化"
        with self.assertRaisesRegex(ValidationError, "actionable_guidance"):
            _chunk(actionable_guidance=[guidance, guidance])

    def test_requires_at_least_one_limitation(self) -> None:
        with self.assertRaises(ValidationError):
            _chunk(limitations=[])

    def test_rejects_invalid_version_format(self) -> None:
        with self.assertRaises(ValidationError):
            _chunk(source_version="latest")


class KnowledgeCorpusTests(unittest.TestCase):
    def test_accepts_ordered_chunks_from_the_same_source(self) -> None:
        corpus = KnowledgeCorpus(
            source=_source(),
            chunks=[_chunk(chunk_index=0)],
        )

        self.assertEqual(corpus.chunks[0].source_version, corpus.source.version)

    def test_rejects_chunk_from_another_source(self) -> None:
        with self.assertRaisesRegex(ValidationError, "source_id"):
            KnowledgeCorpus(
                source=_source(),
                chunks=[_chunk(source_id="another-source", chunk_index=0)],
            )

    def test_rejects_non_continuous_chunk_indexes(self) -> None:
        with self.assertRaisesRegex(ValidationError, "continuous"):
            KnowledgeCorpus(source=_source(), chunks=[_chunk(chunk_index=2)])


if __name__ == "__main__":
    unittest.main()
