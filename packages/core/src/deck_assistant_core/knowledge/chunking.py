"""Deterministic Markdown/plain-text chunking with source citations.

Markdown ATX headings update the citation heading stack; plain text yields
chunks without headings. Chunk identity and line ranges are deterministic for a
given document and ``max_chars`` so indexes built from the same content match.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from deck_assistant_core.knowledge._helpers import (
    KnowledgeValidationError,
    _require_instance,
)
from deck_assistant_core.knowledge.contracts import (
    ContentHash,
    KnowledgeChunk,
    KnowledgeCitation,
    KnowledgeDocument,
    SourceMetadata,
)


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")
_FENCE_MARKERS = ("```", "~~~")


@dataclass(frozen=True)
class _Section:
    headings: tuple[str, ...]
    lines: tuple[tuple[int, str], ...]


def chunk_document(
    source: SourceMetadata,
    document: KnowledgeDocument,
    content: str,
    *,
    max_chars: int = 1200,
) -> tuple[KnowledgeChunk, ...]:
    """Split text or Markdown into deterministic cited chunks.

    Markdown ATX headings update the citation heading stack. Plain text yields
    chunks without headings.
    """

    _require_instance(source, SourceMetadata, "source")
    _require_instance(document, KnowledgeDocument, "document")
    if source.source_id != document.source_id:
        raise KnowledgeValidationError("document source_id does not match source id")
    if not isinstance(content, str):
        raise KnowledgeValidationError("document content must be a string")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        raise KnowledgeValidationError("max_chars must be an integer")
    if max_chars <= 0:
        raise KnowledgeValidationError("max_chars must be positive")

    chunks: list[KnowledgeChunk] = []
    detect_headings = document.content_type == "text/markdown"
    for section in _sections(content, detect_headings=detect_headings):
        for part in _split_lines(section.lines, max_chars):
            trimmed = _trim_blank_edges(part)
            if not trimmed:
                continue
            chunk_id = f"{document.document_id}#chunk-{len(chunks) + 1:04d}"
            text = "\n".join(line for _, line in trimmed)
            start_line = trimmed[0][0]
            end_line = trimmed[-1][0]
            citation = KnowledgeCitation(
                source_id=source.source_id,
                source_type=source.source_type,
                source_title=source.title,
                source_uri=source.uri,
                document_id=document.document_id,
                document_title=document.title,
                document_path=document.path,
                chunk_id=chunk_id,
                headings=section.headings,
                start_line=start_line,
                end_line=end_line,
                license=source.license,
                revision=source.revision,
            )
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    source_id=source.source_id,
                    document_id=document.document_id,
                    text=text,
                    headings=section.headings,
                    start_line=start_line,
                    end_line=end_line,
                    content_hash=ContentHash.sha256_text(text),
                    citation=citation,
                )
            )

    return tuple(chunks)


def _sections(content: str, *, detect_headings: bool) -> tuple[_Section, ...]:
    sections: list[_Section] = []
    heading_stack: tuple[tuple[int, str], ...] = ()
    current_heading_titles: tuple[str, ...] = ()
    current_lines: list[tuple[int, str]] = []
    in_fence = False
    fence_marker: str | None = None

    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        fence = _fence_marker(stripped)
        heading_match = None if in_fence or not detect_headings else _ATX_HEADING_RE.match(line)

        if heading_match is not None:
            _append_section(sections, current_heading_titles, current_lines)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = tuple(item for item in heading_stack if item[0] < level) + (
                (level, title),
            )
            current_heading_titles = tuple(title for _, title in heading_stack)
            current_lines = [(line_number, line)]
            continue

        current_lines.append((line_number, line))
        if fence is not None:
            if in_fence and fence == fence_marker:
                in_fence = False
                fence_marker = None
            elif not in_fence:
                in_fence = True
                fence_marker = fence

    _append_section(sections, current_heading_titles, current_lines)
    return tuple(sections)


def _append_section(
    sections: list[_Section],
    headings: tuple[str, ...],
    lines: Sequence[tuple[int, str]],
) -> None:
    trimmed = _trim_blank_edges(lines)
    if trimmed:
        sections.append(_Section(headings=headings, lines=tuple(trimmed)))


def _split_lines(
    lines: Sequence[tuple[int, str]],
    max_chars: int,
) -> tuple[tuple[tuple[int, str], ...], ...]:
    chunks: list[tuple[tuple[int, str], ...]] = []
    current: list[tuple[int, str]] = []
    current_length = 0

    for line in lines:
        line_length = len(line[1])
        next_length = line_length if not current else current_length + 1 + line_length
        if current and next_length > max_chars:
            chunks.append(tuple(current))
            current = [line]
            current_length = line_length
        else:
            current.append(line)
            current_length = next_length

    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _trim_blank_edges(lines: Sequence[tuple[int, str]]) -> tuple[tuple[int, str], ...]:
    start = 0
    end = len(lines)
    while start < end and not lines[start][1].strip():
        start += 1
    while end > start and not lines[end - 1][1].strip():
        end -= 1
    return tuple(lines[start:end])


def _fence_marker(stripped_line: str) -> str | None:
    for marker in _FENCE_MARKERS:
        if stripped_line.startswith(marker):
            return marker
    return None
