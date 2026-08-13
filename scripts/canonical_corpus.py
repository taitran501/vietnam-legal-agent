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


_TEXT_HASH_SUFFIXES = frozenset({".json", ".jsonl", ".txt", ".md", ".csv"})


def sha256_file(path: Path) -> str:
    """Hash a source deterministically across Windows and POSIX checkouts.

    Git may materialize checked-in text as CRLF on Windows and LF on Linux.
    Corpus identity must represent the logical source, not the checkout's
    newline convention, while signed PDFs/DOC files must remain byte-exact.
    """

    payload = path.read_bytes()
    if path.suffix.lower() in _TEXT_HASH_SUFFIXES:
        payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(payload).hexdigest()


def load_amendment_map(path: Path | None = None) -> dict[str, Any]:
    """Load the operation-level amendment map used by ingestion metadata.

    This is deliberately metadata-only.  It records which signed instrument
    owns the substantive provision and which later instruments apply narrow
    operations (for example a ministry-name replacement).  It does not claim
    that the base extraction has been legally consolidated.
    """

    if path is None:
        manifest_path = ROOT / "data" / "corpus_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reference = str(manifest.get("amendment_map_file") or "").strip()
        path = ROOT / reference if reference else None
    if path is None or not path.exists() or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _anchor_key(value: Any) -> str:
    """Normalize article/appendix labels for amendment-map lookup."""

    text = _clean(value)
    match = re.search(r"(?:Điều|Dieu)\s+\d+[a-zđ]?", text, re.IGNORECASE)
    if match:
        return match.group(0).replace("Dieu", "Điều").strip()
    if "xxii" in text.casefold():
        return "Phụ lục XXII"
    return text


def _amendment_entry_for_anchor(amendment_map: dict[str, Any], anchor: Any) -> dict[str, Any] | None:
    key = _anchor_key(anchor)
    for entry in amendment_map.get("entries") or []:
        entry_anchor = _clean(entry.get("anchor"))
        if entry_anchor == key:
            return dict(entry)
        if entry_anchor == "Điều 78-86" and re.fullmatch(r"Điều (?:7[89]|8[0-6])", key):
            return dict(entry)
    return None


def amendment_metadata_for_anchor(anchor: Any, *, amendment_map: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return safe, serialisable amendment metadata for one legal anchor."""

    entry = _amendment_entry_for_anchor(amendment_map or load_amendment_map(), anchor)
    if not entry:
        return {
            "active_source_document_id": "",
            "active_source_pages": "",
            "amendment_document_ids": [],
            "amendment_resolution_status": "unmapped",
            "amendment_operations": [],
            "current_law_support": False,
        }
    return {
        "active_source_document_id": str(entry.get("substantive_source_document_id") or entry.get("active_source_document_id") or ""),
        "active_source_pages": str(entry.get("substantive_source_pages") or ""),
        "amendment_document_ids": list(entry.get("amendment_document_ids") or []),
        "amendment_resolution_status": str(entry.get("resolution_status") or "unresolved"),
        "amendment_operations": list(entry.get("operations") or []),
        "current_law_support": bool(entry.get("current_law_support", False)),
    }


def corpus_readiness_audit(
    *,
    manifest_path: Path | None = None,
    rule_pack_path: Path | None = None,
    amendment_map_path: Path | None = None,
    appendix_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the complete amendment chain before an index can be promoted."""

    manifest_path = manifest_path or ROOT / "data" / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = {str(item.get("document_id")): dict(item) for item in manifest.get("documents") or []}
    source_errors: list[str] = []
    for document_id, document in documents.items():
        for field in ("source_file", "source_sha256", "source_uri", "signed_source_file", "signed_source_sha256"):
            if not document.get(field):
                source_errors.append(f"{document_id}:{field}_missing")
        if document.get("source_uri") and not str(document["source_uri"]).startswith(("https://", "http://")):
            source_errors.append(f"{document_id}:source_uri_invalid")
        source_path = ROOT / str(document.get("source_file") or "")
        if not source_path.exists():
            source_errors.append(f"{document_id}:source_missing")
        elif str(document.get("source_sha256", "")).lower() != sha256_file(source_path).lower():
            source_errors.append(f"{document_id}:source_hash_mismatch")
        signed_path_value = document.get("signed_source_file")
        if signed_path_value:
            signed_path = ROOT / str(signed_path_value)
            expected_signed = str(document.get("signed_source_sha256") or "").lower()
            if not signed_path.exists():
                source_errors.append(f"{document_id}:signed_source_missing")
            elif expected_signed and expected_signed != sha256_file(signed_path).lower():
                source_errors.append(f"{document_id}:signed_source_hash_mismatch")
        for amended_id in document.get("amends") or []:
            if str(amended_id) not in documents:
                source_errors.append(f"{document_id}:amends_missing:{amended_id}")
            elif int(document.get("precedence") or 0) <= int(documents[str(amended_id)].get("precedence") or 0):
                source_errors.append(f"{document_id}:precedence_not_above:{amended_id}")
        records_value = document.get("records_file")
        if records_value:
            records_path = ROOT / str(records_value)
            expected_records = str(document.get("records_sha256") or "").lower()
            if not records_path.is_file():
                source_errors.append(f"{document_id}:records_missing")
            elif not expected_records:
                source_errors.append(f"{document_id}:records_sha256_missing")
            elif expected_records != sha256_file(records_path).lower():
                source_errors.append(f"{document_id}:records_hash_mismatch")

    amendment_map_reference = str(manifest.get("amendment_map_file") or "").strip()
    amendment_map_path = amendment_map_path or (ROOT / amendment_map_reference if amendment_map_reference else None)
    amendment_errors: list[str] = []
    amendment_map: dict[str, Any] = {}
    if amendment_map_path is None or not amendment_map_path.exists() or not amendment_map_path.is_file():
        amendment_errors.append("amendment_map_missing")
    else:
        amendment_map = json.loads(amendment_map_path.read_text(encoding="utf-8"))
        if str(amendment_map.get("technical_validation_status") or "") != "complete":
            amendment_errors.append("amendment_map_technical_validation_incomplete")
        if amendment_map.get("generated_consolidated_text") is not False:
            amendment_errors.append("amendment_map_generated_text_policy_missing")
        known_anchors = {
            _clean(entry.get("anchor"))
            for entry in amendment_map.get("entries") or []
            if isinstance(entry, dict)
        }
        expected_anchors = {f"Điều {number}" for number in range(77, 87)} | {"Phụ lục XXII"}
        for missing_anchor in sorted(expected_anchors - known_anchors):
            amendment_errors.append(f"anchor_missing:{missing_anchor}")
        if str(amendment_map.get("review_status") or "") != "approved":
            amendment_errors.append("amendment_map_legal_review_pending")
        for index, entry in enumerate(amendment_map.get("entries") or []):
            active_id = str(entry.get("substantive_source_document_id") or entry.get("active_source_document_id") or "")
            if active_id not in documents:
                amendment_errors.append(f"entry_{index}:active_source_missing")
            elif not documents[active_id].get("signed_source_sha256"):
                amendment_errors.append(f"entry_{index}:active_source_not_signed")
            if not str(entry.get("substantive_source_pages") or "").strip():
                amendment_errors.append(f"entry_{index}:active_source_pages_missing")
            operations = entry.get("operations") or []
            if not isinstance(operations, list) or not operations:
                amendment_errors.append(f"entry_{index}:operations_missing")
            else:
                operation_precedence: list[int] = []
                allowed_operations = {
                    "repeal_provision",
                    "replace_appendix",
                    "replace_provision",
                    "replace_provision_part",
                    "replace_provision_parts",
                    "replace_term",
                }
                for operation_index, operation in enumerate(operations):
                    if not isinstance(operation, dict):
                        amendment_errors.append(f"entry_{index}:operation_{operation_index}_invalid")
                        continue
                    operation_document = str(operation.get("document_id") or "")
                    if operation_document not in documents:
                        amendment_errors.append(f"entry_{index}:operation_{operation_index}_document_missing")
                    else:
                        operation_precedence.append(int(documents[operation_document].get("precedence") or 0))
                    if not str(operation.get("source_pages") or "").strip():
                        amendment_errors.append(f"entry_{index}:operation_{operation_index}_pages_missing")
                    if not str(operation.get("operation") or "").strip():
                        amendment_errors.append(f"entry_{index}:operation_{operation_index}_kind_missing")
                    elif str(operation.get("operation")) not in allowed_operations:
                        amendment_errors.append(f"entry_{index}:operation_{operation_index}_kind_unsupported")
                    for field in ("target", "effective_from", "summary"):
                        if not str(operation.get(field) or "").strip():
                            amendment_errors.append(f"entry_{index}:operation_{operation_index}_{field}_missing")
                if operation_precedence != sorted(operation_precedence):
                    amendment_errors.append(f"entry_{index}:operation_precedence_invalid")
            if str(entry.get("resolution_status") or "").endswith("pending") or "pending" in str(entry.get("resolution_status") or ""):
                amendment_errors.append(f"entry_{index}:resolution_pending")
            if not entry.get("verified_by"):
                amendment_errors.append(f"entry_{index}:legal_review_missing")

    rule_pack_reference = str(manifest.get("rule_pack_file") or "").strip()
    rule_pack_path = rule_pack_path or (ROOT / rule_pack_reference if rule_pack_reference else None)
    rule_pack_errors: list[str] = []
    rule_pack: dict[str, Any] = {}
    expected_corpus_sha = corpus_sha256(manifest_path=manifest_path, appendix_path=appendix_path)
    if rule_pack_path is None or not rule_pack_path.exists() or not rule_pack_path.is_file():
        rule_pack_errors.append("rule_pack_missing")
    else:
        rule_pack = json.loads(rule_pack_path.read_text(encoding="utf-8"))
        if str(rule_pack.get("corpus_version") or "") != str(manifest.get("corpus_version") or ""):
            rule_pack_errors.append("rule_pack_corpus_version_mismatch")
        if str(rule_pack.get("corpus_sha256") or "").lower() != expected_corpus_sha.lower():
            rule_pack_errors.append("rule_pack_corpus_hash_mismatch")
        if str(rule_pack.get("legal_review_status") or "") != "approved":
            rule_pack_errors.append("rule_pack_legal_review_pending")

    approval_errors: list[str] = []
    if str(manifest.get("legal_review_status") or "") != "approved":
        approval_errors.append("manifest_legal_review_pending")
    else:
        for field in ("legal_reviewed_by", "legal_reviewed_at", "corpus_as_of_date"):
            if not str(manifest.get(field) or "").strip():
                approval_errors.append(f"manifest_{field}_missing")
    if str(amendment_map.get("review_status") or "") == "approved":
        for field in ("reviewed_by", "reviewed_at"):
            if not str(amendment_map.get(field) or "").strip():
                approval_errors.append(f"amendment_map_{field}_missing")
        for index, entry in enumerate(amendment_map.get("entries") or []):
            for field in ("verified_by", "verified_at"):
                if not str(entry.get(field) or "").strip():
                    approval_errors.append(f"entry_{index}:{field}_missing")
    if str(rule_pack.get("legal_review_status") or "") == "approved":
        for field in ("legal_reviewed_by", "legal_reviewed_at"):
            if not str(rule_pack.get(field) or "").strip():
                approval_errors.append(f"rule_pack_{field}_missing")

    legal_review_markers = ("legal_review_pending", "legal_review_missing", "resolution_pending")
    technical_errors = [
        error
        for error in [*source_errors, *amendment_errors, *rule_pack_errors]
        if not any(marker in error for marker in legal_review_markers)
    ]
    technical_ready = not technical_errors
    ready_for_promotion = (
        technical_ready
        and not amendment_errors
        and not rule_pack_errors
        and not approval_errors
        and manifest.get("legal_review_status") == "approved"
    )

    return {
        "source_errors": source_errors,
        "amendment_errors": amendment_errors,
        "rule_pack_errors": rule_pack_errors,
        "approval_errors": approval_errors,
        "technical_errors": technical_errors,
        "technical_ready": technical_ready,
        "manifest_legal_review_status": manifest.get("legal_review_status"),
        "promotion_status": manifest.get("promotion_status"),
        "expected_corpus_sha": expected_corpus_sha,
        "ready_for_promotion": ready_for_promotion,
        "amendment_map_sha256": sha256_file(amendment_map_path) if amendment_map_path and amendment_map_path.is_file() else "",
        "rule_pack_sha256": sha256_file(rule_pack_path) if rule_pack_path and rule_pack_path.is_file() else "",
        "document_count": len(documents),
        "documents": sorted(documents),
    }


def corpus_sha256(
    *, law_path: Path | None = None, manifest_path: Path | None = None, appendix_path: Path | None = None
) -> str:
    """Fingerprint all checked-in inputs which define the active legal corpus."""

    law_path = law_path or ROOT / "data" / "law.json"
    manifest_path = manifest_path or ROOT / "data" / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return corpus_sha256_from_manifest(
        manifest,
        law_path=law_path,
        appendix_path=appendix_path,
        root=ROOT,
    )


def corpus_sha256_from_manifest(
    manifest: dict[str, Any],
    *,
    law_path: Path | None = None,
    appendix_path: Path | None = None,
    root: Path | None = None,
) -> str:
    """Fingerprint a manifest payload without requiring a temporary file.

    The corpus synchronization command uses this function to compute the hash
    of the *desired* manifest before writing it.  Keeping one implementation
    avoids a check/write loop where updating source hashes changes the corpus
    identity a second time.
    """

    root = root or ROOT
    law_path = law_path or root / "data" / "law.json"
    payload: dict[str, Any] = {
        "law_json_sha256": sha256_file(law_path) if law_path.exists() else "missing",
        "manifest": manifest,
        "chunking_profile": CHUNKING_PROFILE,
        "embedding_profile": EMBEDDING_PROFILE,
    }
    appendix = appendix_path or root / "data" / "appendix_xxii.jsonl"
    if appendix.exists():
        payload["appendix_xxii_sha256"] = sha256_file(appendix)
    amendment_map_reference = str(manifest.get("amendment_map_file") or "").strip()
    amendment_map = root / amendment_map_reference if amendment_map_reference else None
    if amendment_map and amendment_map.is_file():
        payload["amendment_map_sha256"] = sha256_file(amendment_map)
    for document in manifest.get("documents", []):
        source = root / str(document["source_file"])
        payload.setdefault("source_sha256", {})[str(document["document_id"])] = sha256_file(source) if source.is_file() else "missing"
        records_file = document.get("records_file")
        if records_file:
            records_path = root / str(records_file)
            if records_path.is_file():
                payload.setdefault("records_sha256", {})[str(document["document_id"])] = sha256_file(records_path)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_document_manifests(path: Path | None = None) -> tuple[str, str, list[LegalDocument]]:
    path = path or ROOT / "data" / "corpus_manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    documents = raw.get("documents") or []
    if not documents:
        raise ValueError("corpus manifest must contain at least one source document")
    validated: list[LegalDocument] = []
    for item in documents:
        entry = dict(item)
        source_path = ROOT / str(entry["source_file"])
        if not source_path.exists():
            raise FileNotFoundError(f"corpus source is missing: {source_path}")
        # The manifest carries an auditable expected hash.  Recompute it so a
        # changed source cannot silently retain the old identity.
        actual_hash = sha256_file(source_path)
        expected_hash = str(entry.get("source_sha256") or actual_hash).upper()
        if expected_hash != actual_hash.upper():
            raise ValueError(f"source hash mismatch for {entry['document_id']}")
        entry["source_sha256"] = actual_hash
        validated.append(LegalDocument.model_validate(entry))
    return str(raw["corpus_id"]), str(raw["corpus_version"]), validated


def load_document_manifest(path: Path | None = None) -> tuple[str, str, LegalDocument]:
    """Compatibility helper returning the document with checked-in records."""

    corpus_id, corpus_version, documents = load_document_manifests(path)
    for document in documents:
        if document.document_id == "nd-08-2022-nd-cp":
            return corpus_id, corpus_version, document
    return corpus_id, corpus_version, min(documents, key=lambda item: item.effective_from or "")


def _records_document_map(path: Path | None = None) -> dict[str, LegalDocument]:
    _, _, documents = load_document_manifests(path)
    result: dict[str, LegalDocument] = {}
    for document in documents:
        # Amendment PDFs are source evidence but are not promoted as chunks
        # until their page-level text extraction has passed legal review.
        if document.document_id == "nd-08-2022-nd-cp":
            result[str(document.document_id)] = document
    return result


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
    digest = corpus_sha256(appendix_path=appendix_path)
    amendment_map = load_amendment_map()
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
        amendment_metadata = amendment_metadata_for_anchor(article, amendment_map=amendment_map)
        if amendment_metadata["amendment_resolution_status"] == "unmapped":
            amendment_metadata["current_law_support"] = not bool(document.amends)
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
                "Effective_From": document.effective_from.isoformat() if document.effective_from else "",
                "Effective_Status": "pending_amendment_review" if document.amends else document.status,
                "Amendment_Relationship": amendment_metadata["amendment_document_ids"] or list(document.amends),
                "Active_Source_Document_Id": amendment_metadata["active_source_document_id"],
                "Active_Source_Pages": amendment_metadata["active_source_pages"],
                "Amendment_Resolution_Status": amendment_metadata["amendment_resolution_status"],
                "Amendment_Operations": amendment_metadata["amendment_operations"],
                "Current_Law_Support": amendment_metadata["current_law_support"],
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
    amendment_map = load_amendment_map()
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
        amendment_metadata = amendment_metadata_for_anchor(anchor.article, amendment_map=amendment_map)
        if amendment_metadata["amendment_resolution_status"] == "unmapped":
            amendment_metadata["current_law_support"] = not bool(document.amends)
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
                source_sha256=document.source_sha256,
                effective_from=document.effective_from,
                effective_to=document.effective_to,
                effective_status="pending_amendment_review" if document.amends else document.status,
                amendment_relationship=amendment_metadata["amendment_document_ids"] or list(document.amends),
                active_source_document_id=amendment_metadata["active_source_document_id"],
                active_source_pages=amendment_metadata["active_source_pages"],
                amendment_resolution_status=amendment_metadata["amendment_resolution_status"],
                amendment_operations=amendment_metadata["amendment_operations"],
                current_law_support=amendment_metadata["current_law_support"],
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
