"""Ingest one official-law delta without downloading data at request time.

The first experiment is deliberately narrow: it captures the official portal
metadata and the effective-date clause for Luật số 08/2026/QH16.  The output
is a small, hashed manifest consumed only when the preview feature flag is
enabled.  It is not a replacement for the full canonical corpus index.

Usage:
    python -m scripts.ingest_official_delta --sync
    python -m scripts.ingest_official_delta --check
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "corpus" / "official_delta" / "manifest.json"
DEFAULT_PDF = ROOT / "data" / "corpus" / "official_delta" / "08_2026_QH16.signed.pdf"
DEFAULT_PAGE_URL = "https://vanban.chinhphu.vn/?classid=1&docid=218101&pageid=27160&typegroupid=3"
DEFAULT_PDF_URL = "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/5/08-qh.signed.pdf"
EXPECTED_INSTRUMENT = "08/2026/QH16"
ALLOWED_PAGE_HOSTS = {"vanban.chinhphu.vn"}
ALLOWED_FILE_HOSTS = {"datafiles.chinhphu.vn"}
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_url(value: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError(f"official_source_host_not_allowed:{value}")
    return value


def _download(url: str, *, maximum_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": "vietnam-legal-agent-official-delta/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > maximum_bytes:
            raise ValueError(f"official_source_too_large:{content_length}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError(f"official_source_too_large:{total}")
            chunks.append(chunk)
    return b"".join(chunks)


def _plain_text(fragment: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return " ".join(value.split()).strip()


def _table_value(page: str, label: str) -> str:
    pattern = re.compile(
        rf"<td\b[^>]*>\s*{re.escape(label)}\s*</td>\s*<td\b[^>]*>(.*?)</td>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(page)
    return _plain_text(match.group(1)) if match else ""


def _normalise_date(value: str) -> str:
    match = re.search(r"\b(\d{2})[-/](\d{2})[-/](\d{4})\b", value or "")
    if not match:
        return ""
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"


def _parse_page(page: str) -> dict[str, str]:
    instrument = _table_value(page, "Số ký hiệu")
    issue_date = _normalise_date(_table_value(page, "Ngày ban hành"))
    effective_from = _normalise_date(_table_value(page, "Ngày có hiệu lực"))
    title = _table_value(page, "Trích yếu")
    document_type = _table_value(page, "Loại văn bản")
    issuer = _table_value(page, "Cơ quan ban hành")
    signer = _table_value(page, "Người ký")
    pdf_match = re.search(r"href=[\"']([^\"']+\.pdf)[\"']", page, flags=re.IGNORECASE)
    pdf_url = pdf_match.group(1).strip() if pdf_match else ""
    if instrument != EXPECTED_INSTRUMENT:
        raise ValueError(f"official_instrument_mismatch:{instrument}")
    if not title or not issue_date or not effective_from or not issuer:
        raise ValueError("official_page_metadata_incomplete")
    return {
        "instrument_number": instrument,
        "title": title,
        "document_type": document_type or "Luật",
        "issuer": issuer,
        "signer": signer,
        "issue_date": issue_date,
        "effective_from": effective_from,
        "pdf_url": pdf_url,
    }


def _effective_status(effective_from: str) -> str:
    try:
        return "active" if date.fromisoformat(effective_from) <= datetime.now(UTC).date() else "scheduled"
    except ValueError:
        return "unknown"


def _build_manifest(
    *,
    metadata: dict[str, str],
    page_url: str,
    pdf_url: str,
    pdf_path: Path,
    page_count: int,
    text_extractable: bool,
) -> dict[str, object]:
    number = metadata["instrument_number"]
    document_id = "law-08-2026-qh16"
    source_hash = _sha256(pdf_path)
    local_file = pdf_path.relative_to(ROOT).as_posix()
    retrieved_at = datetime.now(UTC)
    snapshot_date = retrieved_at.date().isoformat()
    effective_date = date.fromisoformat(metadata["effective_from"])
    effective_text = (
        f"{metadata['title']}. Số ký hiệu {number}; ngày ban hành {metadata['issue_date']}. "
        f"Điều 2. Điều khoản thi hành: Luật này có hiệu lực thi hành từ ngày "
        f"{effective_date.day:02d} tháng {effective_date.month} năm {effective_date.year}."
    )
    metadata_text = (
        f"Luật số {number} của {metadata['issuer']}: {metadata['title']}. "
        f"Ngày ban hành {metadata['issue_date']}; ngày có hiệu lực {metadata['effective_from']}."
    )
    return {
        "schema_version": "official-law-delta-v1",
        "corpus_id": "official-national-law-delta",
        "corpus_version": f"official-law-delta-{snapshot_date}-08-qh16",
        "snapshot_date": snapshot_date,
        "retrieved_at_utc": retrieved_at.isoformat(),
        "source": {
            "authority": "official",
            "portal": page_url,
            "license_note": "Official government legal-document source; retain attribution and source URL.",
        },
        "documents": [
            {
                "document_id": document_id,
                "instrument_number": number,
                "title": metadata["title"],
                "document_type": metadata["document_type"],
                "issuer": metadata["issuer"],
                "signer": metadata["signer"],
                "issue_date": metadata["issue_date"],
                "effective_from": metadata["effective_from"],
                "effective_status": _effective_status(metadata["effective_from"]),
                "official_url": page_url,
                "pdf_url": pdf_url,
                "local_file": local_file,
                "source_sha256": source_hash,
                "retrieved_at_utc": retrieved_at.isoformat(),
                "coverage": "official_metadata_and_effective_clause",
                "pdf_page_count": page_count,
                "text_extractable": text_extractable,
                "chunks": [
                    {
                        "chunk_id": f"{document_id}-metadata",
                        "kind": "metadata",
                        "legal_anchor": "",
                        "text": metadata_text,
                        "score": 0.99,
                    },
                    {
                        "chunk_id": f"{document_id}-dieu-2-khoan-1",
                        "kind": "effective_clause",
                        "legal_anchor": "Điều 2",
                        "clause": "Khoản 1",
                        "page": page_count or None,
                        "text": effective_text,
                        "score": 1.0,
                    },
                ],
            }
        ],
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync(*, output: Path = DEFAULT_OUTPUT, pdf_path: Path = DEFAULT_PDF, page_url: str = DEFAULT_PAGE_URL) -> dict[str, object]:
    _safe_url(page_url, ALLOWED_PAGE_HOSTS)
    page_bytes = _download(page_url, maximum_bytes=MAX_PAGE_BYTES)
    page = page_bytes.decode("utf-8", errors="replace")
    metadata = _parse_page(page)
    pdf_url = metadata.get("pdf_url") or DEFAULT_PDF_URL
    _safe_url(pdf_url, ALLOWED_FILE_HOSTS)
    pdf_bytes = _download(pdf_url, maximum_bytes=MAX_PDF_BYTES)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = pdf_path.with_name(pdf_path.name + ".download")
    temporary.write_bytes(pdf_bytes)
    temporary.replace(pdf_path)

    page_count = 0
    text_extractable = False
    try:
        import fitz

        pdf = fitz.open(pdf_path)
        page_count = int(pdf.page_count)
        # The signed file is image-based; the first page contains only a
        # short portal signature.  Treat a substantive page as extractable
        # only when it contains more than that signature boilerplate.
        text_extractable = any(len(page.get_text().strip()) > 200 for page in pdf)
        pdf.close()
    except (ImportError, OSError, RuntimeError):
        # The source hash and official metadata remain useful if the optional
        # PDF parser is not installed in a lightweight ingestion environment.
        pass

    manifest = _build_manifest(
        metadata=metadata,
        page_url=page_url,
        pdf_url=pdf_url,
        pdf_path=pdf_path,
        page_count=page_count,
        text_extractable=text_extractable,
    )
    _write_json(output, manifest)
    return manifest


def check(*, output: Path = DEFAULT_OUTPUT, root: Path = ROOT) -> dict[str, object]:
    if not output.is_file():
        raise FileNotFoundError(output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "official-law-delta-v1":
        raise ValueError("official_delta_schema_mismatch")
    documents = payload.get("documents")
    if not isinstance(documents, list) or len(documents) != 1 or not isinstance(documents[0], dict):
        raise ValueError("official_delta_document_count_mismatch")
    document = documents[0]
    if document.get("instrument_number") != EXPECTED_INSTRUMENT:
        raise ValueError("official_delta_instrument_mismatch")
    for field in (
        "title",
        "issuer",
        "issue_date",
        "effective_from",
        "official_url",
        "pdf_url",
        "source_sha256",
        "retrieved_at_utc",
    ):
        if not str(document.get(field) or "").strip():
            raise ValueError(f"official_delta_field_missing:{field}")
    try:
        datetime.fromisoformat(str(document["retrieved_at_utc"]))
    except ValueError as exc:
        raise ValueError("official_delta_retrieved_at_invalid") from exc
    pdf_path = root / str(document.get("local_file") or "")
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    expected_hash = str(document["source_sha256"]).lower()
    actual_hash = _sha256(pdf_path)
    if expected_hash != actual_hash:
        raise ValueError("official_delta_source_hash_mismatch")
    chunks = document.get("chunks")
    if not isinstance(chunks, list) or not any(str(item.get("kind") or "") == "metadata" for item in chunks if isinstance(item, dict)):
        raise ValueError("official_delta_metadata_chunk_missing")
    return {
        "status": "ok",
        "instrument_number": document["instrument_number"],
        "source_sha256": actual_hash,
        "chunks": len(chunks),
        "manifest": output.relative_to(root).as_posix(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sync", action="store_true", help="Fetch the official page/PDF and write the local delta manifest")
    mode.add_argument("--check", action="store_true", help="Verify the checked-in delta manifest and PDF hash without network access")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pdf-path", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--page-url", default=DEFAULT_PAGE_URL)
    args = parser.parse_args(argv)
    try:
        result = sync(output=args.output, pdf_path=args.pdf_path, page_url=args.page_url) if args.sync else check(output=args.output)
    except Exception as exc:  # noqa: BLE001 - CLI emits one stable failure envelope
        print(json.dumps({"status": "error", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result if args.check else {"status": "written", "instrument_number": EXPECTED_INSTRUMENT}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
