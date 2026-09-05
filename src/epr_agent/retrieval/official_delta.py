"""Strict retrieval over a small, repository-managed official-law delta.

The delta is deliberately separate from the broad universal corpus.  It is
used only when a query names an exact instrument number and the local
manifest contains that instrument.  This keeps a metadata-only preview
record from becoming a generic legal fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from epr_agent.domain.legal import LegalAnchor, explicit_anchors
from epr_agent.domain.models import DocumentRecord

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "corpus" / "official_delta" / "manifest.json"

_INSTRUMENT_RE = re.compile(r"(?<![\w/])\d{1,5}/\d{4}/[A-ZĐ0-9][A-ZĐ0-9-]*(?![\w/])", re.IGNORECASE)
_METADATA_QUERY_TERMS = (
    "hiệu lực",
    "hieu luc",
    "ban hành",
    "ban hanh",
    "số ký hiệu",
    "so ky hieu",
    "trích yếu",
    "trich yeu",
    "tên luật",
    "ten luat",
    "ngày nào",
    "ngay nao",
)


def _normalise(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _query_instrument_numbers(query: str, anchors: list[LegalAnchor]) -> set[str]:
    numbers = {
        _normalise(anchor.document_number)
        for anchor in anchors
        if str(anchor.document_number or "").strip()
    }
    if numbers:
        return numbers
    return {_normalise(value) for value in _INSTRUMENT_RE.findall(query or "")}


class OfficialDeltaRetriever:
    """Read exact-instrument records from a local official delta manifest."""

    def __init__(self, manifest_path: str | Path | None = None) -> None:
        configured_path = manifest_path or os.getenv("OFFICIAL_DELTA_MANIFEST_PATH") or DEFAULT_MANIFEST_PATH
        self.manifest_path = Path(configured_path)
        self._manifest: dict[str, Any] | None = None
        self._signature: tuple[int, int] | None = None

    def _load(self) -> dict[str, Any] | None:
        try:
            stat = self.manifest_path.stat()
        except OSError:
            return None
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        if self._manifest is not None and self._signature == signature:
            return self._manifest
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Official delta manifest is unreadable: %s", exc)
            return None
        if not isinstance(payload, dict) or payload.get("schema_version") != "official-law-delta-v1":
            logger.warning("Official delta manifest schema is unsupported: %s", self.manifest_path)
            return None
        documents = payload.get("documents")
        if not isinstance(documents, list):
            logger.warning("Official delta manifest has no document list: %s", self.manifest_path)
            return None
        self._manifest = payload
        self._signature = signature
        return payload

    @property
    def is_available(self) -> bool:
        return self._load() is not None

    def covers_instrument(
        self,
        query: str,
        *,
        required_anchors: list[LegalAnchor] | None = None,
    ) -> bool:
        """Return whether the delta owns the query's single exact instrument.

        The gateway uses this only to fail closed for an unsupported query
        about a document that the delta claims to cover.  Queries for other
        instruments can continue through the canonical retrieval path.
        """

        manifest = self._load()
        if manifest is None:
            return False
        parsed_anchors = list(required_anchors or explicit_anchors(query))
        numbers = _query_instrument_numbers(query, parsed_anchors)
        if len(numbers) != 1:
            return False
        return any(
            isinstance(document, dict)
            and self._document_matches(next(iter(numbers)), document)
            for document in manifest.get("documents") or []
        )

    @staticmethod
    def _metadata_query(query: str) -> bool:
        lowered = _normalise(query)
        return any(term in lowered for term in _METADATA_QUERY_TERMS)

    @staticmethod
    def _anchor_matches(chunk: dict[str, Any], requested: list[LegalAnchor]) -> bool:
        article_requests = {_normalise(anchor.article) for anchor in requested if anchor.article}
        clause_requests = {_normalise(anchor.clause) for anchor in requested if anchor.clause}
        point_requests = {_normalise(anchor.point) for anchor in requested if anchor.point}
        if article_requests and _normalise(chunk.get("legal_anchor")) not in article_requests:
            return False
        if clause_requests and not clause_requests.issubset({_normalise(chunk.get("clause"))}):
            return False
        return not point_requests or point_requests.issubset({_normalise(chunk.get("point"))})

    @staticmethod
    def _document_matches(number: str, document: dict[str, Any]) -> bool:
        return _normalise(document.get("instrument_number")) == number

    @staticmethod
    def _record(document: dict[str, Any], chunk: dict[str, Any], manifest: dict[str, Any]) -> DocumentRecord:
        number = str(document.get("instrument_number") or "").strip()
        document_id = str(document.get("document_id") or f"official-{number}").strip()
        chunk_id = str(chunk.get("chunk_id") or f"{document_id}-metadata").strip()
        title = str(document.get("title") or "").strip()
        official_url = str(document.get("official_url") or "").strip()
        pdf_url = str(document.get("pdf_url") or "").strip()
        source_sha256 = str(document.get("source_sha256") or "").strip().lower()
        corpus_version = str(manifest.get("corpus_version") or "official-law-delta-v1").strip()
        corpus_sha256 = str(manifest.get("corpus_sha256") or source_sha256).strip().lower()
        legal_anchor = str(chunk.get("legal_anchor") or "").strip()
        content = str(chunk.get("text") or "").strip()
        metadata = {
            "Dieu": legal_anchor,
            "legal_anchor": legal_anchor,
            "source": title,
            "source_title": title,
            "Source_Title": title,
            "document_title": title,
            "title": title,
            "Document_Number": number,
            "Instrument_Number": number,
            "instrument_number": number,
            "number": number,
            "law_ref": f"Luật số {number}",
            "official_url": official_url,
            "source_uri": official_url,
            "pdf_url": pdf_url,
            "source_file": document.get("local_file", ""),
            "source_sha256": source_sha256,
            "retrieved_at_utc": document.get("retrieved_at_utc", manifest.get("retrieved_at_utc", "")),
            "source_kind": "official_delta",
            "authority": "official",
            "source_document_id": f"official:{number}",
            "document_id": document_id,
            "chunk_id": chunk_id,
            "page": chunk.get("page"),
            "issue_date": document.get("issue_date", ""),
            "Issue_Date": document.get("issue_date", ""),
            "effective_from": document.get("effective_from", ""),
            "Effective_From": document.get("effective_from", ""),
            "effective_status": document.get("effective_status", "active"),
            "current_law_support": True,
            "Current_Law_Support": True,
            "corpus_as_of_date": manifest.get("snapshot_date", ""),
            "Corpus_As_Of_Date": manifest.get("snapshot_date", ""),
            "Corpus_Version": corpus_version,
            "corpus_version": corpus_version,
            "Corpus_SHA256": corpus_sha256,
            "corpus_sha": corpus_sha256,
            "Embedding_Profile": "official-law-delta-v1",
            "embedding_profile": "official-law-delta-v1",
            "corpus_source": "official_delta",
            "coverage": document.get("coverage", "metadata_and_targeted_clause"),
            "explicit_match": True,
        }
        return DocumentRecord(
            content=content,
            metadata=metadata,
            document_id=chunk_id,
            score=float(chunk.get("score") or 0.99),
            source="legal",
            effective_from=str(document.get("effective_from") or "") or None,
            effective_status=str(document.get("effective_status") or "active"),
            current_law_support=True,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        required_anchors: list[LegalAnchor] | None = None,
    ) -> list[DocumentRecord]:
        """Return records only for an exact instrument and supported query shape.

        The first delta is intentionally metadata-plus-effective-date only.
        A query asking for general substantive content therefore returns no
        record until a full-text source is added and audited.
        """

        clean_query = " ".join(str(query or "").split())
        if not clean_query or limit < 1:
            return []
        manifest = self._load()
        if manifest is None:
            return []
        parsed_anchors = list(required_anchors or explicit_anchors(clean_query))
        numbers = _query_instrument_numbers(clean_query, parsed_anchors)
        if len(numbers) != 1:
            return []
        number = next(iter(numbers))
        has_article = any(anchor.article for anchor in parsed_anchors)
        if not has_article and not self._metadata_query(clean_query):
            return []

        matches: list[DocumentRecord] = []
        for raw_document in manifest.get("documents") or []:
            if not isinstance(raw_document, dict) or not self._document_matches(number, raw_document):
                continue
            for raw_chunk in raw_document.get("chunks") or []:
                if not isinstance(raw_chunk, dict):
                    continue
                if has_article and not self._anchor_matches(raw_chunk, parsed_anchors):
                    continue
                if not has_article and str(raw_chunk.get("kind") or "") != "metadata":
                    continue
                if not str(raw_chunk.get("text") or "").strip():
                    continue
                matches.append(self._record(raw_document, raw_chunk, manifest))
        return matches[:limit]


official_delta_retriever = OfficialDeltaRetriever()
