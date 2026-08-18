"""Document Parser for PDF, DOCX, and Text contracts and legal instruments.

Supports:
- PDF extraction using PyMuPDF (fitz) with automatic page numbering and fallback.
- DOCX extraction using native XML / docx parsing.
- Structured clause boundary detector (identifying Điều, Khoản, Mục, Chương, Article).
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from typing import Any
from pydantic import BaseModel, Field

_CLAUSE_REGEX = re.compile(
    r"^(?:Điều|ĐIỀU|Article|ARTICLE)\s+(\d+[a-zA-Z]?)(?:\.|\:|\s+[-–—])?\s*(.*)$",
    re.MULTILINE,
)

_SUB_CLAUSE_REGEX = re.compile(
    r"^(\d+)\.\s+(.*)$",
    re.MULTILINE,
)


class ParsedClause(BaseModel):
    """Structured clause chunk extracted from a contract or legal document."""

    clause_id: str = Field(description="Định danh điều khoản (ví dụ: Dieu_1, Dieu_25)")
    clause_number: str = Field(description="Số điều (ví dụ: '1', '25', '77')")
    clause_title: str = Field(default="", description="Tiêu đề của điều khoản")
    full_text: str = Field(description="Toàn bộ nội dung điều khoản")
    page_number: int = Field(default=1, description="Trang chứa điều khoản")
    sub_clauses: list[dict[str, str]] = Field(default_factory=list, description="Danh sách các khoản con")


class DocumentParseResult(BaseModel):
    """Result of document parsing and structured clause extraction."""

    document_id: str = Field(description="Mã tài liệu")
    filename: str = Field(description="Tên file gốc")
    file_type: str = Field(description="Loại file (pdf, docx, txt)")
    total_pages: int = Field(default=1, description="Tổng số trang")
    total_chars: int = Field(description="Tổng số ký tự")
    raw_text: str = Field(description="Toàn bộ nội dung văn bản bóc tách")
    clauses: list[ParsedClause] = Field(default_factory=list, description="Danh sách các điều khoản trích xuất")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata bổ sung")


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> tuple[str, int, list[dict[str, Any]]]:
    """Extract text and per-page content from PDF bytes using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_content = []
        full_text_list = []
        total_pages = len(doc)
        for page_idx in range(total_pages):
            page = doc.load_page(page_idx)
            page_text = page.get_text("text") or ""
            full_text_list.append(page_text)
            pages_content.append({"page": page_idx + 1, "text": page_text})
        return "\n\n".join(full_text_list), total_pages, pages_content
    except Exception as exc:
        # Fallback if PyMuPDF has issue
        text = pdf_bytes.decode("utf-8", errors="ignore")
        return text, 1, [{"page": 1, "text": text}]


def extract_text_from_docx_bytes(docx_bytes: bytes) -> tuple[str, int]:
    """Extract text from DOCX bytes via zip/XML parsing without heavy external deps."""
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as docx_zip:
            xml_content = docx_zip.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            # Namespace for WordprocessingML
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for p in tree.iterfind(".//w:p", ns):
                texts = [node.text for node in p.iterfind(".//w:t", ns) if node.text]
                if texts:
                    paragraphs.append("".join(texts))
            full_text = "\n\n".join(paragraphs)
            return full_text, max(1, len(paragraphs) // 15)
    except Exception:
        text = docx_bytes.decode("utf-8", errors="ignore")
        return text, 1


def parse_contract_clauses(text: str) -> list[ParsedClause]:
    """Parse contract text into individual structured clauses."""
    clauses: list[ParsedClause] = []
    matches = list(_CLAUSE_REGEX.finditer(text))

    if not matches:
        # No formal "Điều X" pattern found; create logical sections
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 30]
        for idx, p in enumerate(paragraphs, start=1):
            clauses.append(
                ParsedClause(
                    clause_id=f"Section_{idx}",
                    clause_number=str(idx),
                    clause_title=f"Đoạn điều khoản {idx}",
                    full_text=p,
                    page_number=1,
                )
            )
        return clauses

    for i, match in enumerate(matches):
        clause_num = match.group(1).strip()
        clause_title = match.group(2).strip()
        start_pos = match.start()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        clause_body = text[start_pos:end_pos].strip()

        # Parse sub-clauses (Khoản 1, Khoản 2,...)
        sub_clauses: list[dict[str, str]] = []
        for sub_match in _SUB_CLAUSE_REGEX.finditer(clause_body):
            sub_num = sub_match.group(1)
            sub_text = sub_match.group(2).strip()
            sub_clauses.append({"sub_clause": sub_num, "text": sub_text})

        clauses.append(
            ParsedClause(
                clause_id=f"Dieu_{clause_num}",
                clause_number=clause_num,
                clause_title=clause_title or f"Điều {clause_num}",
                full_text=clause_body,
                page_number=1,
                sub_clauses=sub_clauses,
            )
        )

    return clauses


def parse_document_file(
    content_bytes: bytes,
    filename: str,
    mime_type: str = "application/pdf",
) -> DocumentParseResult:
    """Entrypoint to parse uploaded contract / legal file into structured clauses."""
    filename_lower = filename.lower()
    doc_id = f"doc_{uuid.uuid4().hex[:10]}"

    if filename_lower.endswith(".pdf") or "pdf" in mime_type:
        raw_text, pages, _ = extract_text_from_pdf_bytes(content_bytes)
        file_type = "pdf"
    elif filename_lower.endswith(".docx") or "word" in mime_type:
        raw_text, pages = extract_text_from_docx_bytes(content_bytes)
        file_type = "docx"
    else:
        raw_text = content_bytes.decode("utf-8", errors="replace")
        pages = 1
        file_type = "txt"

    clauses = parse_contract_clauses(raw_text)

    return DocumentParseResult(
        document_id=doc_id,
        filename=filename,
        file_type=file_type,
        total_pages=pages,
        total_chars=len(raw_text),
        raw_text=raw_text,
        clauses=clauses,
        metadata={"filename": filename, "file_type": file_type, "total_clauses": len(clauses)},
    )
