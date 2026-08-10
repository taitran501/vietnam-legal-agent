"""
Ingest a Vietnamese legal .doc file into law.json-like structure.

Goal:
- Convert .doc -> plain text (via Word COM on Windows)
- Parse Chương / Mục / Điều blocks
- Export JSON with schema:
  {"meta": [{"Điều": ..., "Chương": ..., "Mục": ..., "Pages": "", "Text": ...}, ...]}

This script is intentionally conservative:
- It focuses on Điều-level parsing for Nghị định body.
- Optional appendices can be merged from an existing law.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

CHAPTER_RE = re.compile(r"^\s*Chương\s+([IVXLCM]+|\d+)\b.*$", re.IGNORECASE)
SECTION_RE = re.compile(r"^\s*Mục\s+\d+\b.*$", re.IGNORECASE)
ARTICLE_RE = re.compile(r"^\s*Điều\s+(\d+)\.\s*(.+)?$", re.IGNORECASE)

ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\uFEFF]")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTIBLANK_RE = re.compile(r"\n{3,}")
logger = logging.getLogger(__name__)


def _read_text_with_fallback(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1258", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (OSError, UnicodeError) as exc:
            logger.debug("Unable to read %s as %s: %s", path, enc, exc)
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _clean_text(text: str) -> str:
    t = ZERO_WIDTH_RE.sub("", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\t", " ")
    lines = [MULTISPACE_RE.sub(" ", ln).strip() for ln in t.split("\n")]
    t = "\n".join(lines)
    t = MULTIBLANK_RE.sub("\n\n", t)
    return t.strip()


def extract_doc_to_txt(doc_path: Path, out_txt: Path) -> None:
    """
    Extract .doc to UTF-8 text via MS Word COM (Windows).
    """
    if os.name != "nt":
        raise RuntimeError("DOC extraction via Word COM is supported only on Windows.")

    ps = (
        "$ErrorActionPreference='Stop'; "
        f"$docPath='{doc_path!s}'; "
        f"$tmpOut='{out_txt!s}'; "
        "$word=New-Object -ComObject Word.Application; "
        "$word.Visible=$false; "
        "$doc=$word.Documents.Open($docPath,$false,$true); "
        "$fmt=7; "  # wdFormatUnicodeText
        "$doc.SaveAs([ref]$tmpOut,[ref]$fmt); "
        "$doc.Close(); "
        "$word.Quit(); "
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True,
        capture_output=True,
        text=True,
    )


def parse_articles(text: str) -> list[dict[str, Any]]:
    current_chapter = ""
    current_section = ""

    records: list[dict[str, Any]] = []
    current_record: dict[str, Any] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current_record, body_lines
        if current_record is None:
            return
        body = _clean_text("\n".join(body_lines))
        current_record["Text"] = body
        if body:
            records.append(current_record)
        current_record = None
        body_lines = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            if current_record is not None:
                body_lines.append("")
            continue

        if CHAPTER_RE.match(line):
            current_chapter = line
            continue
        if SECTION_RE.match(line):
            current_section = line
            continue

        m_article = ARTICLE_RE.match(line)
        if m_article:
            flush()
            dieu_num = m_article.group(1)
            suffix = (m_article.group(2) or "").strip()
            dieu_heading = f"Điều {dieu_num}." + (f" {suffix}" if suffix else "")
            current_record = {
                "Điều": dieu_heading.strip(),
                "Chương": current_chapter,
                "Mục": current_section,
                "Pages": "",
                "Text": "",
            }
            continue

        if current_record is not None:
            body_lines.append(line)

    flush()
    return records


def merge_appendices(parsed: list[dict[str, Any]], source_json: Path) -> list[dict[str, Any]]:
    if not source_json.exists():
        return parsed

    raw = json.loads(source_json.read_text(encoding="utf-8"))
    meta = raw.get("meta", raw if isinstance(raw, list) else [])
    if not isinstance(meta, list):
        return parsed

    existing = {str(r.get("Điều", "")).strip() for r in parsed}
    for rec in meta:
        dieu = str(rec.get("Điều", "")).strip()
        if not dieu:
            continue
        if dieu.lower().startswith("phụ lục") and dieu not in existing:
            parsed.append(rec)
            existing.add(dieu)
    return parsed


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Deduplicate parsed records:
    - For numbered Điều, keep one record per number (prefer longer Text).
    - For non-numbered headings (appendix), keep one record per exact heading.
    """
    article_pat = re.compile(r"Điều\s+(\d+)", flags=re.IGNORECASE)
    best_by_article: dict[int, dict[str, Any]] = {}
    appendix_by_heading: dict[str, dict[str, Any]] = {}

    for rec in records:
        dieu = str(rec.get("Điều", "")).strip()
        text_len = len(str(rec.get("Text", "")))
        m = article_pat.search(dieu)
        if m:
            n = int(m.group(1))
            prev = best_by_article.get(n)
            if prev is None or text_len > len(str(prev.get("Text", ""))):
                best_by_article[n] = rec
            continue

        if dieu:
            prev = appendix_by_heading.get(dieu)
            if prev is None or text_len > len(str(prev.get("Text", ""))):
                appendix_by_heading[dieu] = rec

    merged = list(best_by_article.values()) + list(appendix_by_heading.values())
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest .doc to law.json format")
    parser.add_argument(
        "--doc",
        default="data/08_2022_ND-CP_479457.doc",
        help="Path to .doc file",
    )
    parser.add_argument(
        "--output",
        default="artifacts/law_from_doc.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--appendix-from-json",
        default="data/law.json",
        help="Optional existing law.json to merge Phụ lục records",
    )
    parser.add_argument(
        "--no-appendix-merge",
        action="store_true",
        help="Disable appendix merge from existing JSON",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    doc_path = (root / args.doc).resolve() if not Path(args.doc).is_absolute() else Path(args.doc)
    out_path = (root / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    appendix_src = (
        (root / args.appendix_from_json).resolve()
        if not Path(args.appendix_from_json).is_absolute()
        else Path(args.appendix_from_json)
    )

    if not doc_path.exists():
        raise FileNotFoundError(f"Doc not found: {doc_path}")

    with tempfile.TemporaryDirectory(prefix="doc_ingest_") as tmpdir:
        tmp_txt = Path(tmpdir) / "doc_extract.txt"
        extract_doc_to_txt(doc_path, tmp_txt)
        text = _read_text_with_fallback(tmp_txt)

    text = _clean_text(text)
    records = parse_articles(text)
    if not args.no_appendix_merge:
        records = merge_appendices(records, appendix_src)
    records = dedupe_records(records)

    # sort by numeric Điều first, then keep appendices after
    def _sort_key(rec: dict[str, Any]) -> tuple[int, int, str]:
        dieu = str(rec.get("Điều", ""))
        m = re.search(r"Điều\s+(\d+)", dieu, flags=re.IGNORECASE)
        if m:
            return (0, int(m.group(1)), dieu)
        return (1, 10**9, dieu)

    records = sorted(records, key=_sort_key)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"meta": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    nums = []
    for r in records:
        m = re.search(r"Điều\s+(\d+)", str(r.get("Điều", "")), flags=re.IGNORECASE)
        if m:
            nums.append(int(m.group(1)))
    uniq = sorted(set(nums))

    print(f"[ingest] doc={doc_path}")
    print(f"[ingest] output={out_path}")
    print(f"[ingest] records={len(records)}")
    if uniq:
        print(f"[ingest] dieu_range={uniq[0]}..{uniq[-1]} unique={len(uniq)}")
    else:
        print("[ingest] no dieu parsed")


if __name__ == "__main__":
    main()
