"""Bounded document-upload reads and format-specific resource guards."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_DOCX_ENTRIES = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 2_000_000
UPLOAD_CHUNK_BYTES = 64 * 1024

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_WORDPROCESSINGML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": _DOCX_MIME,
    ".txt": "text/plain",
}


async def read_bounded_upload(file: UploadFile) -> bytes:
    """Read at most 10 MiB and stop consuming the request immediately after overflow."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 10 MiB size limit.")
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="File tải lên không có dữ liệu (rỗng)")
    return b"".join(chunks)


def validate_upload_format(*, content: bytes, filename: str, mime_type: str) -> str:
    """Require extension, declared MIME, magic bytes, and bounded container structure to agree."""
    extension = Path(filename).suffix.lower()
    expected_mime = _MIME_BY_EXTENSION.get(extension)
    normalized_mime = mime_type.split(";", 1)[0].strip().lower()
    if expected_mime is None or normalized_mime != expected_mime:
        raise HTTPException(
            status_code=415,
            detail="File extension and MIME type must identify the same supported PDF, DOCX, or TXT format.",
        )

    if extension == ".pdf":
        _validate_pdf(content)
    elif extension == ".docx":
        _validate_docx(content)
    else:
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="TXT uploads must contain valid UTF-8 text.") from exc
    return extension.removeprefix(".")


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="PDF signature does not match the declared format.")
    try:
        import fitz  # type: ignore[import-not-found]

        with fitz.open(stream=content, filetype="pdf") as document:
            page_count = len(document)
    except Exception as exc:
        raise HTTPException(status_code=415, detail="PDF structure is malformed or unreadable.") from exc
    if page_count > MAX_PDF_PAGES:
        raise HTTPException(status_code=422, detail=f"PDF exceeds the {MAX_PDF_PAGES}-page limit.")


def _validate_docx(content: bytes) -> None:
    if not content.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=415, detail="DOCX ZIP signature does not match the declared format.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise HTTPException(
                    status_code=422,
                    detail=f"DOCX exceeds the {MAX_DOCX_ENTRIES}-entry archive limit.",
                )
            if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=422, detail="DOCX expands beyond the 50 MiB limit.")
            names = {entry.filename for entry in entries}
            if len(names) != len(entries):
                raise HTTPException(status_code=415, detail="DOCX package contains duplicate entries.")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise HTTPException(status_code=415, detail="DOCX package is missing required Word structures.")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise HTTPException(status_code=415, detail="Encrypted DOCX uploads are not supported.")
            content_types = ET.fromstring(archive.read("[Content_Types].xml"))
            document = ET.fromstring(archive.read("word/document.xml"))
            if content_types.tag != f"{{{_CONTENT_TYPES_NS}}}Types":
                raise HTTPException(status_code=415, detail="DOCX content-types manifest is invalid.")
            if document.tag != f"{{{_WORDPROCESSINGML_NS}}}document":
                raise HTTPException(status_code=415, detail="DOCX main document structure is invalid.")
            document_type = next(
                (
                    node.attrib.get("ContentType")
                    for node in content_types.findall(f"{{{_CONTENT_TYPES_NS}}}Override")
                    if node.attrib.get("PartName") == "/word/document.xml"
                ),
                None,
            )
            if document_type != _WORD_DOCUMENT_CONTENT_TYPE:
                raise HTTPException(status_code=415, detail="DOCX main document content type is invalid.")
    except HTTPException:
        raise
    except (ET.ParseError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=415, detail="DOCX structure is malformed or unreadable.") from exc


def enforce_extracted_text_limit(total_chars: int) -> None:
    if total_chars > MAX_EXTRACTED_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Extracted document text exceeds {MAX_EXTRACTED_TEXT_CHARS:,} characters.",
        )
