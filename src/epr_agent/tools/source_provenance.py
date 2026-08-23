"""Normalize retrieved chunks into citation-ready source records.

Retrieval engines intentionally return chunks because that is the unit used by
ranking and evidence verification.  The UI, persistence layer and report
exporter need a different unit: a stable legal source with a precise excerpt.
This module is the boundary between those two representations.  It accepts
legacy metadata aliases emitted by the current corpus/indexes, but never uses
the chunk text as a document title when a canonical value is unavailable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

_INSTRUMENT_RE = re.compile(
    r"(?<![\w/])\d{1,5}/\d{4}/[A-ZĐ0-9][A-ZĐ0-9-]*(?![\w/])",
    re.IGNORECASE,
)
_LEADING_HEADER_RE = re.compile(
    r"^(?:\s*\[[^\]]+\]\s*:\s*[^|\n]*(?:\s*\|\s*|\n+))+",
    re.IGNORECASE,
)
_PLACEHOLDERS = {
    "",
    "unknown",
    "none",
    "null",
    "n/a",
    "chưa có trong metadata",
    "chưa xác định",
}
_GENERIC_SOURCE_LABELS = {
    "legal",
    "web",
    "official_web",
    "cache",
    "error",
    "hệ thống văn bản",
    "pháp điển & luật quốc gia",
    "cơ sở dữ liệu pháp luật quốc gia",
    "vietnamese legal corpus",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(part for part in (_text(item) for item in value) if part)
    if isinstance(value, Mapping):
        return ""
    return str(value).strip()


def _meaningful(value: Any) -> str:
    text = _text(value)
    if text.casefold() in _PLACEHOLDERS:
        return ""
    return text


def _first(metadata: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _meaningful(metadata.get(key))
        if value:
            return value
    return ""


def _compact_label(value: Any) -> str:
    """Turn a legacy source note into a readable one-line label."""

    text = _meaningful(value)
    if not text:
        return ""
    text = re.sub(r"\s*\|\|+\s*", " ", text)
    text = re.sub(r"\s*\|\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ()")
    text = re.sub(r"^(?:căn cứ|can cu)\s+", "", text, flags=re.IGNORECASE)
    return text[:500].strip()


def clean_excerpt(raw: Any) -> str:
    """Remove retrieval-only headers while preserving the legal passage."""

    text = _text(raw).strip()
    if not text:
        return ""
    # A legacy index occasionally flattened multiple metadata fields with
    # ``||``.  Keep all text, but separate those fields so the drawer does not
    # render one unreadable line that looks like a document title.
    text = re.sub(r"\s*\|\|+\s*", "\n\n", text)
    # Universal corpus records place [CHỦ ĐỀ], [CĂN CỨ VĂN BẢN], … before a
    # blank line.  Do not expose those routing headers as the citation excerpt.
    text = _LEADING_HEADER_RE.sub("", text, count=1).strip()
    if "\n\n" in text and text.startswith("["):
        prefix, body = text.split("\n\n", 1)
        if re.search(r"\[[^\]]+\]\s*:", prefix):
            text = body.strip()
    return text[:2000].strip()


def _instrument_number(*values: Any) -> str:
    for value in values:
        text = _meaningful(value)
        if not text:
            continue
        match = _INSTRUMENT_RE.search(text)
        if match:
            return match.group(0)
    return ""


def _official_url(*values: Any) -> str:
    for value in values:
        candidate = _meaningful(value)
        if not candidate:
            continue
        try:
            parsed = urlparse(candidate)
        except ValueError:
            continue
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            # A bare host is a catalogue homepage, not a source snapshot.
            if not parsed.path.strip("/") and not parsed.query and not parsed.fragment:
                continue
            return candidate
    return ""


def _source_kind(item: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    explicit = _first(metadata, "source_kind", "Source_Kind")
    if explicit:
        return explicit
    source = _meaningful(item.get("source"))
    if source.casefold() in {"web", "official_web", "legal", "cache", "error"}:
        return "official_web" if source.casefold() == "web" else source
    return "legal_corpus"


def _source_title(
    metadata: Mapping[str, Any],
    *,
    instrument_number: str,
) -> str:
    explicit = _first(
        metadata,
        "source_title",
        "Source_Title",
        "document_title",
        "Document_Title",
        "title",
        "ten_van_ban",
        "law_title",
    )
    explicit_label = _compact_label(explicit)
    if explicit_label and explicit_label.casefold() not in _GENERIC_SOURCE_LABELS:
        return explicit_label

    # ``law_ref`` and ``source`` are legacy aliases.  They are useful when
    # they contain a real instrument, but labels such as ``legal`` are not.
    for candidate in (
        _first(metadata, "law_ref", "Law_Ref"),
        _first(metadata, "source", "Source"),
    ):
        compact = _compact_label(candidate)
        if compact and compact.casefold() not in _GENERIC_SOURCE_LABELS:
            return compact
    if instrument_number:
        return f"Văn bản số {instrument_number}"
    # Keep the missing state explicit.  The client can show the stable id and
    # excerpt without pretending that a chunk is a document title.
    return ""


def _source_id(metadata: Mapping[str, Any], item: Mapping[str, Any]) -> tuple[str, str]:
    chunk_id = _first(metadata, "chunk_id", "Chunk_Id", "chunkId")
    document_id = _first(
        metadata,
        "source_document_id",
        "Source_Document_Id",
        "parent_id",
        "Parent_Id",
        "Active_Source_Document_Id",
        "_id",
        "id",
        "Document_Id",
        "document_id",
    )
    item_document_id = _meaningful(item.get("document_id") or item.get("id"))
    if not document_id:
        document_id = item_document_id
    if not document_id:
        document_id = _first(metadata, "source_file", "Source_File")
    if not chunk_id:
        chunk_id = item_document_id or document_id
    return document_id or chunk_id, chunk_id


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    if text in {"true", "1", "yes", "y", "đúng"}:
        return True
    if text in {"false", "0", "no", "n", "sai"}:
        return False
    return None


def normalize_source(
    item: Mapping[str, Any],
    *,
    citation_index: int,
    corpus_as_of_date: str = "",
    excerpt_limit: int = 2000,
) -> dict[str, Any]:
    """Return the canonical source snapshot for one retrieved chunk."""

    metadata = dict(item.get("metadata") or {})
    source_id, chunk_id = _source_id(metadata, item)
    raw_content = item.get("content", item.get("page_content", ""))
    excerpt = clean_excerpt(raw_content)[:excerpt_limit]
    instrument = _instrument_number(
        _first(metadata, "instrument_number", "Instrument_Number", "Document_Number", "number"),
        _first(metadata, "source_title", "Source_Title", "document_title", "title"),
        _first(metadata, "law_ref", "source"),
        raw_content,
    )
    title = _source_title(metadata, instrument_number=instrument)
    anchor = _first(
        metadata,
        "legal_anchor",
        "anchor",
        "Dieu",
        "Điều",
        "article_title",
        "article",
    )
    official_url = _official_url(
        _first(metadata, "official_url", "official_uri"),
        _first(metadata, "source_uri", "Source_URI", "url", "source_url", "link"),
    )
    status = _first(metadata, "effective_status", "Effective_Status") or _meaningful(item.get("effective_status")) or "unknown"
    effective_from = _first(metadata, "effective_from", "Effective_From") or _text(item.get("effective_from"))
    effective_to = _first(metadata, "effective_to", "Effective_To") or _text(item.get("effective_to"))
    source_kind = _source_kind(item, metadata)
    authority = _first(metadata, "authority") or ("official" if source_kind in {"legal", "legal_corpus", "official_web"} else "unknown")
    current_law_support = _as_bool(
        metadata.get("current_law_support", metadata.get("Current_Law_Support", item.get("current_law_support")))
    )
    relationship = metadata.get("amendment_relationship", metadata.get("Amendment_Relationship", item.get("amendment_relationship", [])))
    if not isinstance(relationship, (list, dict)):
        relationship = [_text(relationship)] if _text(relationship) else []
    snapshot: dict[str, Any] = {
        "citation_index": citation_index,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "title": title,
        "instrument_number": instrument,
        "anchor": anchor,
        "page": metadata.get("Pages", metadata.get("page")),
        "offset_start": metadata.get("Source_Start", metadata.get("offset_start")),
        "offset_end": metadata.get("Source_End", metadata.get("offset_end")),
        "official_url": official_url,
        "source_kind": source_kind,
        "authority": authority,
        "effective_status": status,
        "effective_from": effective_from or None,
        "effective_to": effective_to or None,
        "amendment_relationship": relationship,
        "active_source_document_id": _first(metadata, "Active_Source_Document_Id", "active_source_document_id"),
        "active_source_pages": _first(metadata, "Active_Source_Pages", "active_source_pages"),
        "amendment_resolution_status": _first(metadata, "Amendment_Resolution_Status", "amendment_resolution_status"),
        "amendment_operations": metadata.get("Amendment_Operations", metadata.get("amendment_operations", [])) or [],
        "current_law_support": current_law_support,
        "corpus_as_of_date": corpus_as_of_date or _first(metadata, "corpus_as_of_date", "Corpus_As_Of_Date"),
        "excerpt": excerpt,
    }
    return snapshot


def normalized_document_metadata(snapshot: Mapping[str, Any], *, original: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build safe legacy-compatible metadata for the response ``documents``."""

    source = dict(original or {})
    metadata = dict(source.get("metadata") or {})
    title = _meaningful(snapshot.get("title"))
    instrument = _meaningful(snapshot.get("instrument_number"))
    anchor = _meaningful(snapshot.get("anchor"))
    source_label = title or instrument or _compact_label(_first(metadata, "law_ref", "source"))
    normalized: dict[str, Any] = {
        "source_id": snapshot.get("source_id", ""),
        "chunk_id": snapshot.get("chunk_id", ""),
        "source_title": title,
        "Source_Title": title,
        "document_title": title,
        "Document_Number": instrument,
        "instrument_number": instrument,
        "legal_anchor": anchor,
        "anchor": anchor,
        "Pages": snapshot.get("page"),
        "page": snapshot.get("page"),
        "Source_Start": snapshot.get("offset_start"),
        "offset_start": snapshot.get("offset_start"),
        "Source_End": snapshot.get("offset_end"),
        "offset_end": snapshot.get("offset_end"),
        "source": source_label,
        "law_ref": _compact_label(_first(metadata, "law_ref", "Law_Ref")),
        "official_url": snapshot.get("official_url", ""),
        "source_uri": snapshot.get("official_url", ""),
        "source_kind": snapshot.get("source_kind", "legal_corpus"),
        "authority": snapshot.get("authority", "unknown"),
        "effective_status": snapshot.get("effective_status", "unknown"),
        "effective_from": snapshot.get("effective_from"),
        "effective_to": snapshot.get("effective_to"),
        "amendment_relationship": snapshot.get("amendment_relationship", []),
        "active_source_document_id": snapshot.get("active_source_document_id", ""),
        "active_source_pages": snapshot.get("active_source_pages", ""),
        "amendment_resolution_status": snapshot.get("amendment_resolution_status", ""),
        "amendment_operations": snapshot.get("amendment_operations", []),
        "current_law_support": snapshot.get("current_law_support"),
        "citation_index": snapshot.get("citation_index"),
        "excerpt": snapshot.get("excerpt", ""),
    }
    for key in ("topic", "subject", "chapter", "source_file", "Source_File", "Corpus_Version", "Corpus_SHA256", "rule_id"):
        if metadata.get(key) not in (None, ""):
            normalized[key] = metadata[key]
    if snapshot.get("corpus_as_of_date"):
        normalized["corpus_as_of_date"] = snapshot["corpus_as_of_date"]
    return {key: value for key, value in normalized.items() if value not in (None, "")}
