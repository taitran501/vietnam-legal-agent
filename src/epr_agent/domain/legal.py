"""Canonical, repository-neutral contracts for legal corpus data.

The workflow only receives :class:`LegalChunk` records.  This keeps source
provenance, citation anchors, and embedding settings explicit instead of
reconstructing them from Qdrant payloads at query time.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EMBEDDING_PROFILE = "openai-text-embedding-3-small-v1"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
CHUNKING_PROFILE = "legal-structure-v2"
_ARTICLE_RE = re.compile(r"\b(?:điều|dieu)\s+(\d+[a-zđ]?)\b", re.IGNORECASE)
_DOCUMENT_RE = re.compile(
    r"\b(?:nghị\s*định|nghi\s*dinh|thông\s*tư|thong\s*tu|quyết\s*định|quyet\s*dinh)"
    r"\s*(?:số\s*)?(\d+(?:/\d{4})?/[a-z0-9đ-]+)",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(r"\b(?:khoản|khoan)\s+(\d+[a-zđ]?)\b", re.IGNORECASE)
_POINT_RE = re.compile(r"\b(?:điểm|diem)\s+([a-zđ])\b", re.IGNORECASE)


class LegalDocument(BaseModel):
    """One source document which may contribute multiple legal chunks."""

    document_id: str = Field(min_length=3, max_length=160)
    title: str = Field(min_length=3, max_length=500)
    number: str = Field(min_length=2, max_length=120)
    issuer: str = Field(min_length=2, max_length=250)
    jurisdiction: str = Field(default="Việt Nam", min_length=2, max_length=120)
    effective_from: date | None = None
    effective_to: date | None = None
    scope: str = Field(default="", max_length=1000)
    source_file: str = Field(min_length=1, max_length=500)
    source_uri: str | None = None
    source_sha256: str = Field(min_length=64, max_length=64)
    signed_source_file: str | None = None
    signed_source_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    records_file: str | None = None
    precedence: int = Field(default=0, ge=0)
    amends: list[str] = Field(default_factory=list)
    status: str = "active"

    @field_validator("source_uri")
    @classmethod
    def _valid_uri(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        # The corpus accepts a local primary-source file, so a URI is optional.
        # When configured it must still be an HTTP(S) reference.
        if not value.startswith(("https://", "http://")):
            raise ValueError("source_uri must be HTTP(S)")
        return value.strip()


class LegalAnchor(BaseModel):
    """A legal address parsed from a query or attached to a chunk."""

    document_number: str = ""
    article: str = ""
    clause: str = ""
    point: str = ""

    def key(self) -> str:
        return " | ".join(part for part in (self.document_number, self.article, self.clause, self.point) if part)


def explicit_anchors(query: str) -> list[LegalAnchor]:
    """Parse named document, article, clause, and point anchors.

    The same parser is deliberately shared by query rewriting, retrieval,
    evidence evaluation, and corpus tests.  An LLM can therefore never erase
    an explicit ``Điều`` reference by changing the wording of a question.
    """

    text = query or ""
    document_numbers = [match.group(1).upper() for match in _DOCUMENT_RE.finditer(text)]
    default_document = document_numbers[0] if len(document_numbers) == 1 else ""
    article_matches = list(_ARTICLE_RE.finditer(text))
    anchors: list[LegalAnchor] = []
    for index, match in enumerate(article_matches):
        article = f"Điều {match.group(1)}"
        segment_end = article_matches[index + 1].start() if index + 1 < len(article_matches) else len(text)
        segment = text[match.end() : segment_end]
        clause_match = _CLAUSE_RE.search(segment)
        point_match = _POINT_RE.search(segment)
        anchor = LegalAnchor(
            document_number=default_document,
            article=article,
            clause=f"Khoản {clause_match.group(1)}" if clause_match else "",
            point=f"Điểm {point_match.group(1)}" if point_match else "",
        )
        # Retrieval diversity and explicit-article coverage operate at article
        # level.  Keep the first (usually most specific) reference rather than
        # creating a second anchor when the query repeats the same Điều without
        # its Khoản/Điểm suffix.
        if not any(existing.article.casefold() == anchor.article.casefold() for existing in anchors):
            anchors.append(anchor)
    # A document name by itself is still an explicit anchor: downstream
    # rewriting must preserve it even when no Article is mentioned.
    if not anchors and default_document:
        anchors.append(LegalAnchor(document_number=default_document))
    return anchors


def normalise_embedding_text(text: str) -> str:
    """Use the same deterministic normalization for corpus text and queries."""

    return " ".join(unicodedata.normalize("NFC", text or "").split())


class LegalChunk(BaseModel):
    """A citation-ready atomic unit used by retrieval and generation."""

    chunk_id: str = Field(min_length=3, max_length=160)
    document_id: str = Field(min_length=3, max_length=160)
    parent_id: str = Field(min_length=3, max_length=160)
    corpus_id: str = Field(min_length=2, max_length=80)
    corpus_version: str = Field(min_length=2, max_length=120)
    corpus_sha256: str = Field(min_length=64, max_length=64)
    anchor: LegalAnchor = Field(default_factory=LegalAnchor)
    heading_path: list[str] = Field(default_factory=list)
    pages: str = ""
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    original_text: str = Field(min_length=1)
    retrieval_text: str = Field(min_length=1)
    lexical_text: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_uri: str | None = None
    source_sha256: str = Field(default="", max_length=64)
    effective_from: date | None = None
    effective_to: date | None = None
    effective_status: str = "unknown"
    amendment_relationship: list[str] = Field(default_factory=list)
    active_source_document_id: str = ""
    active_source_pages: str = ""
    amendment_resolution_status: str = ""
    amendment_operations: list[dict[str, Any]] = Field(default_factory=list)
    current_law_support: bool = False
    appendix_table_id: str = ""
    appendix_row_id: str = ""
    appendix_bbox: list[float] = Field(default_factory=list)
    appendix_cell_text: list[str] = Field(default_factory=list)
    embedding_profile: Literal["openai-text-embedding-3-small-v1"] = "openai-text-embedding-3-small-v1"
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    embedding_dimensions: Literal[1536] = 1536
    chunking_profile: Literal["legal-structure-v2"] = "legal-structure-v2"

    @field_validator("source_end")
    @classmethod
    def _valid_offsets(cls, value: int, info) -> int:
        start = info.data.get("source_start", 0)
        if value < start:
            raise ValueError("source_end must not precede source_start")
        return value

    @property
    def legal_anchor(self) -> str:
        return self.anchor.key()
