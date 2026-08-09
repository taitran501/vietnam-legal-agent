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
    r"(?im)(?=^\s*(?:Khoản\s+\d+\b|Điểm\s+[a-zđ]\b|\(\d+\)|[a-zđ]\)))"
)
_LABEL = re.compile(r"^\s*(Khoản\s+\d+\b|Điểm\s+[a-zđ]\b|\(\d+\)|[a-zđ]\))", re.IGNORECASE)


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
    if lower.startswith("khoản") or value.startswith("("):
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


def structural_chunks(text: str, *, max_chars: int = 1800) -> list[StructuralChunk]:
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
    return chunks


def structural_chunk_articles(
    articles: list[dict[str, Any]], summaries: list[str], *, max_chars: int = 1800
) -> tuple[list[dict[str, Any]], list[str], dict[str, int | float]]:
    """Expand source articles without losing hierarchy or citation provenance."""

    output_articles: list[dict[str, Any]] = []
    output_summaries: list[str] = []
    max_chunks = 0
    for article, summary in zip(articles, summaries):
        source = _article_value(article, "Text", "text")
        pieces = structural_chunks(source, max_chars=max_chars)
        if not pieces:
            continue
        max_chunks = max(max_chunks, len(pieces))
        dieu = _article_value(article, "Điều", "Dieu", "Điều_Number")
        chuong = _article_value(article, "Chương", "Chuong", "Chương_Number")
        muc = _article_value(article, "Mục", "Muc", "Mục_Number")
        for index, piece in enumerate(pieces):
            hierarchy = " → ".join(value for value in (dieu, chuong, muc, piece.clause, piece.point) if value)
            output_articles.append(
                {
                    **article,
                    "Text": piece.text,
                    "Parent_Dieu": dieu,
                    "Hierarchy": hierarchy,
                    "Khoan": piece.clause,
                    "Diem": piece.point,
                    "Source_Start": piece.source_start,
                    "Source_End": piece.source_end,
                    "Chunk_Index": index,
                    "Chunk_Count": len(pieces),
                    "Full_Text_Chars": len(source),
                    "Chunking_Strategy": "legal_structure_v1",
                }
            )
            output_summaries.append(summary)
    return output_articles, output_summaries, {
        "source_articles": len(articles),
        "chunked_records": len(output_articles),
        "avg_chunks_per_article": round(len(output_articles) / max(1, len(articles)), 2),
        "max_chunks_per_article": max_chunks,
        "strategy": "legal_structure_v1",
    }
