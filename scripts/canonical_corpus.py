"""Build and audit the canonical legal corpus before it reaches Qdrant.

The checked-in ``law.json`` is an extraction artifact.  This module makes its
relationship with the original legal file explicit and prevents derived rows
without source locations from becoming production evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epr_agent.domain.legal import (
    CHUNKING_PROFILE,
    EMBEDDING_PROFILE,
    LegalAnchor,
    LegalChunk,
    LegalDocument,
)
from epr_agent.domain.legal import (
    explicit_anchors as parse_explicit_anchors,
)

_SPACE = re.compile(r"[ \t]+")


def explicit_anchors(query: str) -> list[LegalAnchor]:
    """Compatibility export for corpus-audit callers.

    Runtime query parsing lives in :mod:`epr_agent.domain.legal` so index
    construction, query rewriting, retrieval and evidence validation share one
    canonical legal-anchor definition.
    """

    return parse_explicit_anchors(query)


@dataclass(frozen=True, slots=True)
class CorpusAudit:
    input_records: int
    accepted_records: int
    excluded_records: int
    duplicate_chunk_ids: int
    missing_provenance: int
    invalid_offsets: int
    excluded: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_records": self.input_records,
            "accepted_records": self.accepted_records,
            "excluded_records": self.excluded_records,
            "duplicate_chunk_ids": self.duplicate_chunk_ids,
            "missing_provenance": self.missing_provenance,
            "invalid_offsets": self.invalid_offsets,
            "excluded": list(self.excluded),
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_sha256(
    *, law_path: Path | None = None, manifest_path: Path | None = None, appendix_path: Path | None = None
) -> str:
    """Fingerprint all checked-in inputs which define the active legal corpus."""

    law_path = law_path or ROOT / "data" / "law.json"
    manifest_path = manifest_path or ROOT / "data" / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload: dict[str, Any] = {
        "law_json_sha256": sha256_file(law_path),
        "manifest": manifest,
        "chunking_profile": CHUNKING_PROFILE,
        "embedding_profile": EMBEDDING_PROFILE,
    }
    appendix = appendix_path or ROOT / "data" / "appendix_xxii.jsonl"
    if appendix.exists():
        payload["appendix_xxii_sha256"] = sha256_file(appendix)
    for document in manifest.get("documents", []):
        source = ROOT / str(document["source_file"])
        payload.setdefault("source_sha256", {})[str(document["document_id"])] = sha256_file(source)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_document_manifest(path: Path | None = None) -> tuple[str, str, LegalDocument]:
    path = path or ROOT / "data" / "corpus_manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    documents = raw.get("documents") or []
    if len(documents) != 1:
        raise ValueError("EPR V3 currently requires exactly one canonical source document")
    item = dict(documents[0])
    item["source_sha256"] = sha256_file(ROOT / item["source_file"])
    return str(raw["corpus_id"]), str(raw["corpus_version"]), LegalDocument.model_validate(item)


def load_extracted_records(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or ROOT / "data" / "law.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("meta", raw) if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise TypeError("law.json must be a list or an object containing 'meta'")
    return [dict(record) for record in records if isinstance(record, dict)]


def load_appendix_xxii_records(path: Path | None = None, *, required: bool = False) -> list[dict[str, Any]]:
    """Load only row-level Appendix data produced by the source extractor."""

    path = path or ROOT / "data" / "appendix_xxii.jsonl"
    if not path.exists():
        if required:
            raise RuntimeError("appendix_xxii_provenance_missing")
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        required_fields = ("Text", "Pages", "Source_Page", "Source_BBox", "Table_Id", "Row_Id", "Cell_Text", "Source_SHA256")
        if not isinstance(record, dict) or any(record.get(field) in (None, "", []) for field in required_fields):
            raise RuntimeError(f"appendix_xxii_invalid_provenance_row:{number}")
        if _clean(" ".join(str(cell) for cell in record["Cell_Text"])) != _clean(record["Text"]):
            raise RuntimeError(f"appendix_xxii_cell_text_mismatch:{number}")
        rows.append(dict(record))
    ids = [str(row["Row_Id"]) for row in rows]
    if required and not rows:
        raise RuntimeError("appendix_xxii_empty")
    if len(ids) != len(set(ids)):
        raise RuntimeError("appendix_xxii_duplicate_row_id")
    return rows


def _clean(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return _SPACE.sub(" ", value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")).strip()


def _raw_text(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _article_value(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if record.get(key):
            return _clean(record[key])
    return ""


def _record_is_traceable(record: dict[str, Any]) -> tuple[bool, str]:
    text = _raw_text(record.get("Text", record.get("text", "")))
    pages = _article_value(record, "Pages")
    heading = _article_value(record, "Điều", "Dieu", "Điều_Number", "Chương", "Chuong")
    if not heading:
        return False, "missing_legal_heading"
    if not text:
        return False, "missing_text"
    # The extracted primary document has page references.  Hand-authored
    # appendix summaries do not, so they stay outside the production corpus.
    if not pages:
        return False, "missing_source_pages"
    return True, ""


def canonical_articles(
    *, require_appendix: bool = False, appendix_path: Path | None = None
) -> tuple[list[dict[str, Any]], CorpusAudit]:
    corpus_id, corpus_version, document = load_document_manifest()
    digest = corpus_sha256()
    accepted: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    source_records = load_extracted_records()
    appendix_rows = load_appendix_xxii_records(appendix_path, required=require_appendix)
    for index, record in enumerate([*source_records, *appendix_rows], start=1):
        valid, reason = _record_is_traceable(record)
        if not valid:
            excluded.append({"row": str(index), "reason": reason, "anchor": _article_value(record, "Điều", "Dieu")})
            continue
        text = _raw_text(record.get("Text", record.get("text", "")))
        article = _article_value(record, "Điều", "Dieu", "Điều_Number")
        chapter = _article_value(record, "Chương", "Chuong", "Chương_Number")
        section = _article_value(record, "Mục", "Muc", "Mục_Number")
        item: dict[str, Any] = (
            {
                "Document_Id": document.document_id,
                "Corpus_Id": corpus_id,
                "Corpus_Version": corpus_version,
                "Corpus_SHA256": digest,
                "Source_File": document.source_file,
                "Source_URI": document.source_uri or "",
                "Source_SHA256": document.source_sha256,
                "Source_Title": document.title,
                "Document_Number": document.number,
                "Điều": article,
                "Chương": chapter,
                "Mục": section,
                "Pages": _article_value(record, "Pages"),
                "Text": text,
                "_Structural_Text": text,
            }
        )
        if record.get("Row_Id"):
            item.update(
                {
                    "Appendix_Table_Id": str(record["Table_Id"]),
                    "Appendix_Row_Id": str(record["Row_Id"]),
                    "Appendix_Cell_Text": list(record["Cell_Text"]),
                    "Appendix_BBox": list(record["Source_BBox"]),
                }
            )
        accepted.append(item)
    audit = CorpusAudit(
        input_records=len(source_records) + len(appendix_rows),
        accepted_records=len(accepted),
        excluded_records=len(excluded),
        duplicate_chunk_ids=0,
        missing_provenance=0,
        invalid_offsets=0,
        excluded=tuple(excluded),
    )
    return accepted, audit


def _heading_path(article: dict[str, Any]) -> list[str]:
    return [
        value
        for value in (
            _article_value(article, "Chương", "Chuong"),
            _article_value(article, "Mục", "Muc"),
            _article_value(article, "Parent_Dieu", "Điều", "Dieu"),
            _article_value(article, "Khoan"),
            _article_value(article, "Diem"),
        )
        if value
    ]


def build_retrieval_text(*, document: LegalDocument, article: dict[str, Any]) -> str:
    hierarchy = "\n".join(_heading_path(article))
    return "\n".join(
        part
        for part in (
            f"Văn bản: {document.number} — {document.title}",
            f"Phân cấp: {hierarchy}" if hierarchy else "",
            f"Nội dung: {_clean(article.get('Text'))}",
        )
        if part
    )


def build_lexical_text(*, document: LegalDocument, article: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            document.number,
            document.title,
            *_heading_path(article),
            _clean(article.get("Text")),
        )
        if part
    )


def canonical_chunks(
    chunked_articles: list[dict[str, Any]], *, appendix_path: Path | None = None
) -> tuple[list[LegalChunk], CorpusAudit]:
    corpus_id, corpus_version, document = load_document_manifest()
    digest = corpus_sha256(appendix_path=appendix_path)
    chunks: list[LegalChunk] = []
    seen: set[str] = set()
    duplicate_count = 0
    invalid_offsets = 0
    for fallback_index, article in enumerate(chunked_articles, start=1):
        original = str(article.get("Original_Text") or article.get("Text") or "").strip()
        start = int(article.get("Source_Start") or 0)
        end = int(article.get("Source_End") or len(original))
        parent_source = str(article.get("_Parent_Source_Text") or "")
        offset_text = parent_source[start:end] if parent_source and end >= start else original
        if end < start or not original or _clean(offset_text) != _clean(original):
            invalid_offsets += 1
            continue
        parent_seed = "|".join((document.document_id, _article_value(article, "Parent_Dieu", "Điều", "Dieu"), _article_value(article, "Pages")))
        parent_id = str(article.get("Parent_Id") or uuid.uuid5(uuid.NAMESPACE_URL, parent_seed))
        chunk_seed = "|".join((parent_id, str(article.get("Chunk_Index", fallback_index)), str(start), str(end), hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]))
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_seed))
        if chunk_id in seen:
            duplicate_count += 1
            continue
        seen.add(chunk_id)
        anchor = LegalAnchor(
            document_number=document.number,
            article=_article_value(article, "Parent_Dieu", "Điều", "Dieu"),
            clause=_article_value(article, "Khoan"),
            point=_article_value(article, "Diem"),
        )
        chunks.append(
            LegalChunk(
                chunk_id=chunk_id,
                document_id=document.document_id,
                parent_id=parent_id,
                corpus_id=corpus_id,
                corpus_version=corpus_version,
                corpus_sha256=digest,
                anchor=anchor,
                heading_path=_heading_path(article),
                pages=_article_value(article, "Pages"),
                source_start=start,
                source_end=end,
                original_text=original,
                retrieval_text=build_retrieval_text(document=document, article=article),
                lexical_text=build_lexical_text(document=document, article=article),
                source_file=document.source_file,
                source_uri=document.source_uri,
                appendix_table_id=str(article.get("Appendix_Table_Id") or ""),
                appendix_row_id=str(article.get("Appendix_Row_Id") or ""),
                appendix_bbox=[float(value) for value in list(article.get("Appendix_BBox") or [])],
                appendix_cell_text=[str(value) for value in list(article.get("Appendix_Cell_Text") or [])],
            )
        )
    audit = CorpusAudit(
        input_records=len(chunked_articles),
        accepted_records=len(chunks),
        excluded_records=invalid_offsets,
        duplicate_chunk_ids=duplicate_count,
        missing_provenance=0,
        invalid_offsets=invalid_offsets,
        excluded=(),
    )
    return chunks, audit


if __name__ == "__main__":
    articles, source_audit = canonical_articles()
    print(json.dumps({"source": source_audit.to_dict(), "accepted_articles": len(articles)}, ensure_ascii=False, indent=2))
