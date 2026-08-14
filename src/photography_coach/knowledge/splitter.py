"""Split a structured Markdown manual into validated, retrievable chunks."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

from photography_coach.knowledge.schemas import (
    KnowledgeChunk,
    KnowledgeCorpus,
    KnowledgeSource,
)


_H1_PATTERN = re.compile(r"^#\s+(.+?)\s*$")
_H2_PATTERN = re.compile(r"^##\s+(.+?)\s*$")
_H3_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
_METADATA_PATTERN = re.compile(r"^-\s+([a-z_]+):\s*(.+?)\s*$")
_LIST_ITEM_PATTERN = re.compile(r"^-\s+(.+?)\s*$")
_REQUIRED_METADATA = {"chunk_key", "dimension", "difficulty", "tags"}
_REQUIRED_BLOCKS = {"适用场景", "核心知识", "可执行指导", "限制"}


@dataclass(frozen=True, slots=True)
class _MarkdownSection:
    title: str
    start_line: int
    end_line: int
    lines: list[str]


def split_markdown_manual(
    source: KnowledgeSource,
    markdown_text: str,
) -> KnowledgeCorpus:
    """Convert level-two manual sections into a validated knowledge corpus.

    A level-two section is the retrieval boundary. Its four level-three blocks
    keep the teaching content and its usage conditions together.
    """

    document_title, sections = _find_document_structure(markdown_text)
    if document_title != source.title:
        raise ValueError("the Markdown H1 title must match the source title")

    chunks = [
        _section_to_chunk(source, document_title, section, index)
        for index, section in enumerate(sections)
    ]
    return KnowledgeCorpus(source=source, chunks=chunks)


def load_and_split_manual(source_path: Path, manual_path: Path) -> KnowledgeCorpus:
    """Load a source manifest and its Markdown manual, then split them."""

    source = KnowledgeSource.model_validate_json(source_path.read_text(encoding="utf-8"))
    markdown_text = manual_path.read_text(encoding="utf-8")
    return split_markdown_manual(source, markdown_text)


def write_corpus(corpus: KnowledgeCorpus, output_path: Path) -> None:
    """Write deterministic, human-readable JSON for later embedding."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        corpus.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _find_document_structure(
    markdown_text: str,
) -> tuple[str, list[_MarkdownSection]]:
    lines = markdown_text.splitlines()
    h1_entries = [
        (line_number, match.group(1).strip())
        for line_number, line in enumerate(lines, start=1)
        if (match := _H1_PATTERN.match(line))
    ]
    if len(h1_entries) != 1:
        raise ValueError("the manual must contain exactly one H1 title")

    h2_entries = [
        (line_number, match.group(1).strip())
        for line_number, line in enumerate(lines, start=1)
        if (match := _H2_PATTERN.match(line))
    ]
    if not h2_entries:
        raise ValueError("the manual must contain at least one H2 knowledge section")

    sections: list[_MarkdownSection] = []
    for position, (start_line, title) in enumerate(h2_entries):
        end_line = (
            h2_entries[position + 1][0] - 1
            if position + 1 < len(h2_entries)
            else len(lines)
        )
        sections.append(
            _MarkdownSection(
                title=title,
                start_line=start_line,
                end_line=end_line,
                lines=lines[start_line:end_line],
            )
        )
    return h1_entries[0][1], sections


def _section_to_chunk(
    source: KnowledgeSource,
    document_title: str,
    section: _MarkdownSection,
    index: int,
) -> KnowledgeChunk:
    metadata: dict[str, str] = {}
    blocks: dict[str, list[str]] = {}
    active_block: str | None = None

    for line in section.lines:
        if heading_match := _H3_PATTERN.match(line):
            active_block = heading_match.group(1).strip()
            if active_block not in _REQUIRED_BLOCKS:
                raise ValueError(
                    f"section '{section.title}' has unsupported H3 block '{active_block}'"
                )
            blocks.setdefault(active_block, [])
            continue

        if active_block is None and (metadata_match := _METADATA_PATTERN.match(line)):
            key, value = metadata_match.groups()
            if key in metadata:
                raise ValueError(
                    f"section '{section.title}' repeats metadata key '{key}'"
                )
            metadata[key] = value.strip()
            continue

        if active_block is not None:
            blocks[active_block].append(line)
        elif line.strip():
            raise ValueError(
                f"section '{section.title}' contains text before its first H3 block"
            )

    missing_metadata = _REQUIRED_METADATA - metadata.keys()
    if missing_metadata:
        missing = ", ".join(sorted(missing_metadata))
        raise ValueError(f"section '{section.title}' is missing metadata: {missing}")
    unknown_metadata = metadata.keys() - _REQUIRED_METADATA
    if unknown_metadata:
        unknown = ", ".join(sorted(unknown_metadata))
        raise ValueError(f"section '{section.title}' has unknown metadata: {unknown}")

    missing_blocks = _REQUIRED_BLOCKS - blocks.keys()
    if missing_blocks:
        missing = ", ".join(sorted(missing_blocks))
        raise ValueError(f"section '{section.title}' is missing blocks: {missing}")

    core_knowledge = "\n".join(blocks["核心知识"]).strip()
    scenarios = _parse_list_block(section.title, "适用场景", blocks["适用场景"])
    guidance = _parse_list_block(section.title, "可执行指导", blocks["可执行指导"])
    limitations = _parse_list_block(section.title, "限制", blocks["限制"])
    tags = [tag.strip() for tag in metadata["tags"].split(",") if tag.strip()]

    return KnowledgeChunk(
        chunk_id=f"{source.source_id}-{metadata['chunk_key']}",
        source_id=source.source_id,
        source_version=source.version,
        section_path=[document_title, section.title],
        chunk_index=index,
        source_locator=(
            f"第 {section.start_line}—{section.end_line} 行；"
            f"{document_title} > {section.title}"
        ),
        dimension=metadata["dimension"],  # type: ignore[arg-type]
        difficulty=metadata["difficulty"],  # type: ignore[arg-type]
        content=f"{section.title}\n\n{core_knowledge}",
        applicable_scenarios=scenarios,
        actionable_guidance=guidance,
        limitations=limitations,
        tags=tags,
    )


def _parse_list_block(section_title: str, block_name: str, lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        match = _LIST_ITEM_PATTERN.match(line)
        if not match:
            raise ValueError(
                f"section '{section_title}' block '{block_name}' must use list items"
            )
        items.append(match.group(1).strip())
    if not items:
        raise ValueError(f"section '{section_title}' block '{block_name}' cannot be empty")
    return items


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split a photography Markdown manual into validated JSON chunks."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    corpus = load_and_split_manual(args.source, args.manual)
    write_corpus(corpus, args.output)
    print(f"Generated {len(corpus.chunks)} chunks at {args.output}")


if __name__ == "__main__":
    main()
