"""Extract citation-ready Appendix XXII rows from the official DOC source.

The old nine hand-written appendix summaries are deliberately never accepted
as legal evidence.  This one-shot extractor converts the authoritative DOC to
PDF, then stores page and table/row provenance for every extracted row.  It
fails closed when LibreOffice or PDF table extraction cannot establish that
provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_APPENDIX = re.compile(r"PHỤ\s+LỤC\s+XXII|PHU\s+LUC\s+XXII", re.IGNORECASE)
_NEXT_APPENDIX = re.compile(r"PHỤ\s+LỤC\s+XXIII|PHU\s+LUC\s+XXIII", re.IGNORECASE)


def _compact(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _row_text(cells: list[str]) -> str:
    """Flatten table cells into the same whitespace-normalized text we audit."""

    return _compact(" ".join(cell for cell in cells if cell))


def _normalize_pdf_cell(value: str) -> str:
    """Correct a verified glyph-order error in this source PDF's table text."""

    text = _compact(value)
    # The rendered Appendix says "flash"; PyMuPDF 1.26 may extract it as
    # "falsh" because of the source PDF's glyph ordering.
    return re.sub(r"\bfalsh\b", "flash", text, flags=re.IGNORECASE)


def _has_appendix_heading(text: str, pattern: re.Pattern[str]) -> bool:
    """Match a standalone appendix heading, not an article's cross-reference."""

    return any(pattern.fullmatch(_compact(line)) for line in text.splitlines())


def _convert_to_pdf(source: Path, work_dir: Path) -> Path:
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if office is None:
        raise RuntimeError("appendix_extractor_requires_libreoffice")
    result = subprocess.run(
        [office, "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(source)],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    target = work_dir / f"{source.stem}.pdf"
    if result.returncode or not target.exists():
        raise RuntimeError(f"appendix_doc_to_pdf_failed:{result.stderr.strip()[:240]}")
    return target


def _appendix_pages(pdf_path: Path) -> tuple[Any, list[int]]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - Docker dependency gate
        raise RuntimeError("appendix_extractor_requires_pymupdf") from exc
    pdf = fitz.open(pdf_path)
    pages = [index for index, page in enumerate(pdf) if _has_appendix_heading(page.get_text("text"), _APPENDIX)]
    if not pages:
        pdf.close()
        raise RuntimeError("appendix_xxii_heading_not_found")
    # A table frequently flows over the following pages.  Include pages until
    # the next appendix heading, but never silently include the whole decree.
    start = pages[0]
    selected = [start]
    for index in range(start + 1, len(pdf)):
        text = pdf[index].get_text("text")
        if _has_appendix_heading(text, _NEXT_APPENDIX):
            break
        selected.append(index)
    return pdf, selected


def extract(source: Path, output: Path) -> dict[str, Any]:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    with tempfile.TemporaryDirectory(prefix="epr-appendix-") as temp:
        pdf_path = _convert_to_pdf(source, Path(temp))
        pdf_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        pdf, pages = _appendix_pages(pdf_path)
        rows: list[dict[str, Any]] = []
        try:
            for page_index in pages:
                page = pdf[page_index]
                finder = page.find_tables()
                tables = list(getattr(finder, "tables", []) or [])
                for table_index, table in enumerate(tables):
                    for row_index, cells in enumerate(table.extract() or []):
                        cells = [_normalize_pdf_cell(cell or "") for cell in cells]
                        text = _row_text(cells)
                        if len(text) < 12:
                            continue
                        # PyMuPDF table rows do not expose a stable row bbox in
                        # all supported versions.  The table bbox plus row ID is
                        # still a deterministic locater, while every cell text
                        # is preserved for audit against the PDF.
                        bbox = [round(float(value), 2) for value in table.bbox]
                        rows.append(
                            {
                                "Document_Id": "nd-08-2022-nd-cp",
                                "Điều": "Phụ lục XXII",
                                "Pages": str(page_index + 1),
                                "Text": text,
                                "Original_Text": text,
                                "Source_File": str(source.relative_to(ROOT)).replace("\\", "/"),
                                "Source_SHA256": source_sha,
                                "PDF_SHA256": pdf_sha,
                                "Source_Page": page_index + 1,
                                "Source_BBox": bbox,
                                "Table_Id": f"p{page_index + 1}-t{table_index}",
                                "Row_Id": f"p{page_index + 1}-t{table_index}-r{row_index}",
                                "Cell_Text": cells,
                            }
                        )
        finally:
            pdf.close()
    unique = {row["Row_Id"] for row in rows}
    if not rows or len(unique) != len(rows):
        raise RuntimeError("appendix_table_provenance_audit_failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    return {"rows": len(rows), "pages": [page + 1 for page in pages], "source_sha256": source_sha, "pdf_sha256": pdf_sha}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data" / "08_2022_ND-CP_479457.doc")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "appendix_xxii.jsonl")
    args = parser.parse_args()
    print(json.dumps(extract(args.source, args.output), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
