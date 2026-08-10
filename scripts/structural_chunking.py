"""Legal-structure chunking for a candidate EPR index.

The candidate never modifies the existing sliding-window collection.  It keeps
the parent legal hierarchy and source character offsets so a retrieved chunk can
be traced to its original Điều/Khoản/Điểm text before it is cited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CLAUSE_OR_POINT = re.compile(
    r"(?im)(?=^\s*(?:Khoản\s+\d+(?=[.:)])|\d+[.)]|Điểm\s+[a-zđ](?=[.:)])|\(\d+\)|[a-zđ]\)))"
)
_LABEL = re.compile(
    r"^\s*(Khoản\s+\d+(?=[.:)])|\d+[.)]|Điểm\s+[a-zđ](?=[.:)])|\(\d+\)|[a-zđ]\))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StructuralChunk:
    text: str
    source_start: int
    source_end: int
    clause: str = ""
    point: str = ""


def _article_value(article: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = article.get(key)
        if value:
            return str(value).strip()
    return ""


def _segments(text: str) -> list[tuple[int, int]]:
    matches = list(_CLAUSE_OR_POINT.finditer(text))
    if not matches:
        return [(0, len(text))]
    starts = [match.start() for match in matches]
    if starts[0] > 0:
        starts.insert(0, 0)
    return [(start, starts[index + 1] if index + 1 < len(starts) else len(text)) for index, start in enumerate(starts)]


def _label(segment: str, current_clause: str) -> tuple[str, str]:
    match = _LABEL.match(segment)
    value = match.group(1) if match else ""
    lower = value.lower()
    if lower.startswith("khoản") or value.startswith("(") or (value and value[0].isdigit()):
        return value, ""
    if lower.startswith("điểm") or (value and value[0].isalpha()):
        return current_clause, value
    return current_clause, ""


def _bounded_piece(text: str, start: int, end: int, clause: str, point: str, max_chars: int) -> list[StructuralChunk]:
    source = text[start:end]
    if len(source) <= max_chars:
        cleaned = " ".join(source.split())
        return [StructuralChunk(cleaned, start, end, clause, point)] if cleaned else []
    pieces: list[StructuralChunk] = []
    cursor = start
    while cursor < end:
        piece_end = min(cursor + max_chars, end)
        if piece_end < end:
            preferred = max(text.rfind(". ", cursor, piece_end), text.rfind("; ", cursor, piece_end))
            if preferred > cursor + max_chars // 3:
                piece_end = preferred + 1
        cleaned = " ".join(text[cursor:piece_end].split())
        if cleaned:
            pieces.append(StructuralChunk(cleaned, cursor, piece_end, clause, point))
        cursor = piece_end
    return pieces


def _merge_short_neighbors(chunks: list[StructuralChunk], *, min_chars: int) -> list[StructuralChunk]:
    """Merge short adjacent units while retaining the enclosing article offsets.

    Legal points can be only a sentence long.  They are useful evidence but too
    sparse for dense retrieval on their own, so V3 merges them with the next
    adjacent unit in the same Điều.  When labels differ, the combined chunk
    deliberately drops the overly-specific clause/point label and remains
    addressable through its parent Điều and source offsets.
    """

    if min_chars <= 0 or len(chunks) < 2:
        return chunks
    merged: list[StructuralChunk] = []
    index = 0
    while index < len(chunks):
        current = chunks[index]
        if len(current.text) >= min_chars or index + 1 >= len(chunks):
            merged.append(current)
            index += 1
            continue
        following = chunks[index + 1]
        clause = current.clause if current.clause == following.clause else ""
        point = current.point if current.point == following.point else ""
        merged.append(
            StructuralChunk(
                text=f"{current.text} {following.text}".strip(),
                source_start=current.source_start,
                source_end=following.source_end,
                clause=clause,
                point=point,
            )
        )
        index += 2
    return merged


def structural_chunks(text: str, *, max_chars: int = 1800, min_chars: int = 0) -> list[StructuralChunk]:
    """Split one Điều into clause/point-aware chunks with original offsets."""

    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []
    chunks: list[StructuralChunk] = []
    current_clause = ""
    for start, end in _segments(raw):
        segment = raw[start:end]
        clause, point = _label(segment, current_clause)
        if clause:
            current_clause = clause
        chunks.extend(_bounded_piece(raw, start, end, clause or current_clause, point, max_chars))
    return _merge_short_neighbors(chunks, min_chars=min_chars)


def structural_chunk_articles(
    articles: list[dict[str, Any]],
    summaries: list[str],
    *,
    max_chars: int = 1800,
    min_chars: int = 0,
    strategy: str = "legal_structure_v1",
) -> tuple[list[dict[str, Any]], list[str], dict[str, int | float]]:
    """Expand source articles without losing hierarchy or citation provenance."""

    output_articles: list[dict[str, Any]] = []
    output_summaries: list[str] = []
    max_chunks = 0
    for article, summary in zip(articles, summaries):
        source = _article_value(article, "_Structural_Text", "Text", "text")
        pieces = structural_chunks(source, max_chars=max_chars, min_chars=min_chars)
        if not pieces:
            continue
        max_chunks = max(max_chunks, len(pieces))
        dieu = _article_value(article, "Điều", "Dieu", "Điều_Number")
        chuong = _article_value(article, "Chương", "Chuong", "Chương_Number")
        muc = _article_value(article, "Mục", "Muc", "Mục_Number")
        for index, piece in enumerate(pieces):
            hierarchy = " → ".join(value for value in (dieu, chuong, muc, piece.clause, piece.point) if value)
            source_article = {key: value for key, value in article.items() if key != "_Structural_Text"}
            output_articles.append(
                {
                    **source_article,
                    "Text": piece.text,
                    "Parent_Dieu": dieu,
                    "Hierarchy": hierarchy,
                    "Khoan": piece.clause,
                    "Diem": piece.point,
                    "Source_Start": piece.source_start,
                    "Source_End": piece.source_end,
                    "_Parent_Source_Text": source,
                    "Original_Text": source[piece.source_start:piece.source_end].strip(),
                    "Chunk_Index": index,
                    "Chunk_Count": len(pieces),
                    "Full_Text_Chars": len(source),
                    "Chunking_Strategy": strategy,
                }
            )
            output_summaries.append(summary)
    return output_articles, output_summaries, {
        "source_articles": len(articles),
        "chunked_records": len(output_articles),
        "avg_chunks_per_article": round(len(output_articles) / max(1, len(articles)), 2),
        "max_chunks_per_article": max_chunks,
        "strategy": strategy,
    }
