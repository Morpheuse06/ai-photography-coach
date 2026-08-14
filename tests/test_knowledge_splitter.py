"""Tests for deterministic Markdown manual splitting."""

from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from photography_coach.knowledge.schemas import KnowledgeCorpus, KnowledgeSource
from photography_coach.knowledge.splitter import (
    load_and_split_manual,
    split_markdown_manual,
    write_corpus,
)


def _source(**overrides) -> KnowledgeSource:
    payload = {
        "source_id": "test-handbook",
        "title": "测试手册",
        "kind": "project_authored",
        "version": "1.0",
        "authors": ["Test Project"],
        "usage_rights": "project_owned",
        "source_uri": None,
        "description": "用于验证 Markdown 章节切分的测试手册。",
    }
    payload.update(overrides)
    return KnowledgeSource.model_validate(payload)


def _manual(**overrides: str) -> str:
    values = {
        "title": "测试手册",
        "chunk_key": "composition-subject",
        "dimension": "composition",
        "difficulty": "beginner",
        "tags": "subject, visual-weight",
        "core": "先确定画面的主要对象，再检查最亮区域和清晰边缘是否把注意力带向主体。",
    }
    values.update(overrides)
    return f"""# {values['title']}

这段前言不进入知识块。

## 1.1 确定主体
- chunk_key: {values['chunk_key']}
- dimension: {values['dimension']}
- difficulty: {values['difficulty']}
- tags: {values['tags']}

### 适用场景
- 主体不够明确

### 核心知识
{values['core']}

### 可执行指导
- 缩小预览后确认第一眼落点

### 限制
- 不能只用主体位置判断构图质量
"""


class KnowledgeSplitterTests(unittest.TestCase):
    def test_splits_h2_section_and_preserves_traceability(self) -> None:
        corpus = split_markdown_manual(_source(), _manual())

        self.assertEqual(len(corpus.chunks), 1)
        chunk = corpus.chunks[0]
        self.assertEqual(chunk.chunk_id, "test-handbook-composition-subject")
        self.assertEqual(chunk.chunk_index, 0)
        self.assertEqual(chunk.section_path, ["测试手册", "1.1 确定主体"])
        self.assertIn("第", chunk.source_locator)
        self.assertIn("先确定画面的主要对象", chunk.content)
        self.assertEqual(chunk.tags, ["subject", "visual-weight"])

    def test_rejects_a_title_that_does_not_match_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "H1 title"):
            split_markdown_manual(_source(), _manual(title="另一份手册"))

    def test_rejects_missing_required_block(self) -> None:
        manual = _manual().replace("### 限制\n- 不能只用主体位置判断构图质量\n", "")

        with self.assertRaisesRegex(ValueError, "missing blocks"):
            split_markdown_manual(_source(), manual)

    def test_schema_rejects_unknown_dimension_from_markdown(self) -> None:
        with self.assertRaises(ValidationError):
            split_markdown_manual(_source(), _manual(dimension="camera_brand"))

    def test_schema_rejects_content_that_is_too_short(self) -> None:
        with self.assertRaises(ValidationError):
            split_markdown_manual(_source(), _manual(core="太短。"))

    def test_rejects_duplicate_stable_chunk_keys(self) -> None:
        first_section = _manual()
        second_section = _manual().split("## 1.1 确定主体", maxsplit=1)[1]
        duplicate_manual = first_section + "\n## 1.2 重复主体" + second_section

        with self.assertRaisesRegex(ValidationError, "chunk_id values must be unique"):
            split_markdown_manual(_source(), duplicate_manual)

    def test_loads_source_and_writes_repeatable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.json"
            manual_path = root / "manual.md"
            first_output = root / "first.json"
            second_output = root / "second.json"
            source_path.write_text(_source().model_dump_json(), encoding="utf-8")
            manual_path.write_text(_manual(), encoding="utf-8")

            corpus = load_and_split_manual(source_path, manual_path)
            write_corpus(corpus, first_output)
            write_corpus(corpus, second_output)

            self.assertEqual(
                first_output.read_text(encoding="utf-8"),
                second_output.read_text(encoding="utf-8"),
            )
            self.assertIn("确定主体", first_output.read_text(encoding="utf-8"))


class ProjectHandbookTests(unittest.TestCase):
    def test_committed_chunks_match_the_current_manual(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        source_path = (
            project_root / "knowledge/sources/ai-photography-coach-handbook.json"
        )
        manual_path = (
            project_root / "knowledge/manuals/ai-photography-coach-handbook.md"
        )
        chunk_path = (
            project_root / "knowledge/chunks/ai-photography-coach-handbook.json"
        )

        generated = load_and_split_manual(source_path, manual_path)
        committed = KnowledgeCorpus.model_validate_json(
            chunk_path.read_text(encoding="utf-8")
        )

        self.assertEqual(generated, committed)
        self.assertEqual(len(generated.chunks), 12)
        self.assertEqual(
            {chunk.dimension for chunk in generated.chunks},
            {
                "general",
                "composition",
                "lighting",
                "color",
                "subject_expression",
                "visual_storytelling",
            },
        )


if __name__ == "__main__":
    unittest.main()
