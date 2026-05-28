"""
Structure-aware markdown chunker.

Respects document structure when splitting:
  - Section boundaries (H1-H4) — never splits a heading from its content
  - Tables — kept as single atomic chunks
  - Fenced code blocks — kept as single atomic chunks
  - Each chunk carries a heading breadcrumb for contextual grounding

For PDF / Word / HTML documents, swap this module's entry point for a
Docling-based parser (https://github.com/DS4SD/docling) that produces the
same ChunkResult schema — the rest of the pipeline is agnostic to source format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ChunkResult:
    text: str
    heading_path: str        # e.g. "Bid Modifier Playbook > When to Increase > Examples"
    chunk_type: str          # paragraph | table | code | heading_section
    char_start: int = 0
    level: int = 0           # deepest heading level (1-4) that owns this chunk


# ── Parsing helpers ───────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
_FENCE_RE   = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_TABLE_RE   = re.compile(r"(\|.+\|\n?)+", re.MULTILINE)


def _extract_blocks(text: str) -> list[tuple[str, str, int]]:
    """
    Walk the markdown text and yield (block_text, block_type, start_pos) tuples.
    Fenced code blocks and tables are emitted as single units so the chunker
    never bisects them.
    """
    protected: list[tuple[int, int, str, str]] = []  # (start, end, type, content)

    for m in _FENCE_RE.finditer(text):
        protected.append((m.start(), m.end(), "code", m.group()))
    for m in _TABLE_RE.finditer(text):
        # Skip if already inside a code block
        if any(s <= m.start() < e for s, e, _, _ in protected if _ == "code"):
            continue
        protected.append((m.start(), m.end(), "table", m.group()))

    protected.sort(key=lambda x: x[0])

    blocks: list[tuple[str, str, int]] = []
    pos = 0
    for start, end, btype, content in protected:
        if pos < start:
            prose = text[pos:start]
            if prose.strip():
                blocks.append((prose, "prose", pos))
        blocks.append((content, btype, start))
        pos = end
    if pos < len(text) and text[pos:].strip():
        blocks.append((text[pos:], "prose", pos))

    return blocks


# ── Main chunker ─────────────────────────────────────────────────────────────

def chunk_markdown(
    text: str,
    source: str = "",
    max_chars: int = 900,
    overlap_chars: int = 80,
) -> list[ChunkResult]:
    """
    Split a markdown document into semantically coherent chunks.

    Strategy
    --------
    1. Walk H1-H4 headings to segment the document into sections.
    2. Within each section, extract tables and code blocks as atomic chunks.
    3. Split remaining prose by paragraph, merging short paragraphs up to
       *max_chars*.  Long paragraphs are split at sentence boundaries with
       *overlap_chars* of trailing context carried forward.

    Each ChunkResult carries a ``heading_path`` breadcrumb so the LLM can
    tell which section a retrieved chunk came from without seeing the full doc.
    """
    if not text.strip():
        return []

    # Split into heading-anchored sections
    sections = _split_by_headings(text)
    chunks: list[ChunkResult] = []

    for section in sections:
        heading_path = section["heading_path"]
        level = section["level"]
        body = section["body"]

        if not body.strip():
            continue

        for block_text, block_type, block_pos in _extract_blocks(body):
            if block_type in ("code", "table"):
                # Atomic chunks — emit as-is (truncate only if absurdly large)
                chunks.append(ChunkResult(
                    text=f"{heading_path}\n\n{block_text.strip()}",
                    heading_path=heading_path,
                    chunk_type=block_type,
                    level=level,
                ))
            else:
                # Prose — paragraph-merge then sentence-split
                paragraphs = [p.strip() for p in block_text.split("\n\n") if p.strip()]
                prose_chunks = _merge_and_split(paragraphs, max_chars, overlap_chars)
                for prose in prose_chunks:
                    chunks.append(ChunkResult(
                        text=f"{heading_path}\n\n{prose}",
                        heading_path=heading_path,
                        chunk_type="paragraph",
                        level=level,
                    ))

    return [c for c in chunks if len(c.text) > 40]


def _split_by_headings(text: str) -> list[dict]:
    """
    Return a list of {heading_path, level, body} dicts, one per section.
    The leading content before the first heading gets heading_path = "(preamble)".
    """
    heading_positions = [
        (m.start(), len(m.group(1)), m.group(2).strip())
        for m in _HEADING_RE.finditer(text)
    ]

    if not heading_positions:
        return [{"heading_path": "", "level": 0, "body": text}]

    sections = []
    breadcrumb: list[tuple[int, str]] = []  # [(level, title), ...]

    # Preamble before first heading
    first_start = heading_positions[0][0]
    if first_start > 0 and text[:first_start].strip():
        sections.append({"heading_path": "(preamble)", "level": 0,
                         "body": text[:first_start]})

    for i, (pos, level, title) in enumerate(heading_positions):
        # Pop breadcrumb entries at or deeper than current level
        breadcrumb = [(l, t) for l, t in breadcrumb if l < level]
        breadcrumb.append((level, title))
        heading_path = " > ".join(t for _, t in breadcrumb)

        end = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(text)
        # Body is everything after the heading line itself
        body_start = text.index("\n", pos) + 1 if "\n" in text[pos:] else end
        body = text[body_start:end]

        sections.append({"heading_path": heading_path, "level": level, "body": body})

    return sections


def _merge_and_split(paragraphs: list[str], max_chars: int, overlap: int) -> list[str]:
    """Merge short paragraphs together; split long ones at sentence boundaries."""
    merged: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                merged.append(current)
            if len(para) > max_chars:
                merged.extend(_split_long(para, max_chars, overlap))
                current = ""
            else:
                current = para

    if current:
        merged.append(current)

    return merged


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split a single long paragraph at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= max_chars:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            # Carry a small overlap window forward
            tail = current[-overlap:] if len(current) > overlap else current
            current = (tail + " " + sent).strip() if tail else sent
    if current:
        chunks.append(current)
    return chunks
