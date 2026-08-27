"""Universal Vietnamese Legal Retriever.

Provides high-precision retrieval over 84,900+ Codified Legal Articles (Pháp điển)
and 318 National Codes & Laws across all Vietnamese legal domains.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from epr_agent.domain.legal import explicit_anchors

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "corpus" / "universal_legal" / "universal_legal.db"

# Conversational stop words in Vietnamese QA (colloquial pronouns, particles, fillers)
LEGAL_STOP_WORDS = {
    "và", "của", "các", "có", "được", "trong", "cho", "về", "theo", "tại", "khi", "để", "là", 
    "những", "thì", "tôi", "muốn", "biết", "như", "thế", "nào", "gì", "bao", "nhiêu", "phải", 
    "không", "hướng", "dẫn", "với", "hãy", "em", "mình", "anh", "chị", "giúp", "bạn", "ạ", "nhỉ",
    "xin", "hỏi", "quy", "định", "như_thế_nào", "ra_sao", "bao_nhiêu", "cho_tôi", "làm_sao",
    "tui", "ba", "mẹ", "bố", "miếng", "ở", "từ", "năm", "hết", "giờ", "được_không", "chưa",
    "nhé", "bro", "nha", "vậy", "cho_em_hỏi", "mấy", "mới", "đang", "này", "đó", "kia", "thôi",
    "ai", "đâu", "sao", "lại", "đã", "sẽ", "cũng", "đều", "rồi", "ngay",
}


def _escape_fts5_term(term: str) -> str:
    """Escape double-quote characters for SQLite FTS5 MATCH syntax."""
    return term.replace('"', '""')


# Domain keyword boosts for Vietnamese law
KNOWN_LAW_NAMES = [
    ("đất đai", "Luật Đất đai"),
    ("sổ đỏ", "Luật Đất đai"),
    ("sổ hồng", "Luật Đất đai"),
    ("khai hoang", "Luật Đất đai"),
    ("đất khai hoang", "Luật Đất đai"),
    ("giấy chứng nhận quyền sử dụng đất", "Luật Đất đai"),
    ("cấp sổ", "Luật Đất đai"),
    ("quyền sử dụng đất", "Luật Đất đai"),
    ("lao động", "Lao động"),
    ("thử việc", "Lao động"),
    ("thử việc", "45/2019/QH14"),
    ("hợp đồng lao động", "Lao động"),
    ("sa thải", "Lao động"),
    ("kỷ luật lao động", "Lao động"),
    ("nghỉ phép", "Lao động"),
    ("tiền lương", "Lao động"),
    ("lương tối thiểu", "Lao động"),
    ("bảo hiểm xã hội", "Luật Bảo hiểm xã hội"),
    ("bhxh", "Luật Bảo hiểm xã hội"),
    ("bảo hiểm y tế", "Luật Bảo hiểm y tế"),
    ("bảo hiểm thất nghiệp", "Luật Bảo hiểm xã hội"),
    ("thương mại", "Luật Thương mại"),
    ("phạt vi phạm hợp đồng", "Luật Thương mại"),
    ("phạt hợp đồng", "Luật Thương mại"),
    ("dân sự", "Bộ luật Dân sự"),
    ("hợp đồng", "Bộ luật Dân sự"),
    ("đặt cọc", "Bộ luật Dân sự"),
    ("bùng cọc", "Bộ luật Dân sự"),
    ("phòng trọ", "Bộ luật Dân sự"),
    ("thuê nhà", "Bộ luật Dân sự"),
    ("thừa kế", "Bộ luật Dân sự"),
    ("di chúc", "Bộ luật Dân sự"),
    ("chia tài sản", "Bộ luật Dân sự"),
    ("hôn nhân", "Luật Hôn nhân và gia đình"),
    ("ly hôn", "Luật Hôn nhân và gia đình"),
    ("doanh nghiệp", "Luật Doanh nghiệp"),
    ("công ty tnhh", "Luật Doanh nghiệp"),
    ("hộ kinh doanh", "Nghị định về đăng ký kinh doanh"),
    ("thành lập công ty", "Luật Doanh nghiệp"),
    ("cổ phần", "Luật Doanh nghiệp"),
    ("cổ đông", "Luật Doanh nghiệp"),
    ("thuế", "Luật Quản lý thuế"),
    ("thuế tncn", "Luật Thuế thu nhập cá nhân"),
    ("thuế thu nhập cá nhân", "Luật Thuế thu nhập cá nhân"),
    ("thuế gtgt", "Luật Thuế giá trị gia tăng"),
    ("thuế vat", "Luật Thuế giá trị gia tăng"),
    ("người phụ thuộc", "Luật Thuế thu nhập cá nhân"),
    ("giảm trừ gia cảnh", "Luật Thuế thu nhập cá nhân"),
    ("hoàn thuế", "Luật Quản lý thuế"),
    ("thuế thu nhập doanh nghiệp", "Luật Thuế thu nhập doanh nghiệp"),
    ("thuế tndn", "Luật Thuế thu nhập doanh nghiệp"),
    ("pccc", "Luật Phòng cháy và chữa cháy"),
    ("phòng cháy", "Luật Phòng cháy và chữa cháy"),
    ("chữa cháy", "Luật Phòng cháy và chữa cháy"),
    ("an toàn thực phẩm", "Luật An toàn thực phẩm"),
    ("vsatp", "Luật An toàn thực phẩm"),
    ("vệ sinh an toàn thực phẩm", "Luật An toàn thực phẩm"),
    ("quán ăn", "Luật An toàn thực phẩm"),
    ("xây dựng", "Luật Xây dựng"),
    ("giấy phép xây dựng", "Luật Xây dựng"),
    ("môi trường", "Luật Bảo vệ môi trường"),
    ("epr", "Nghị định số 08/2022/NĐ-CP"),
    ("tái chế", "Luật Bảo vệ môi trường"),
    ("bao bì", "Nghị định số 08/2022/NĐ-CP"),
    ("rác thải", "Luật Bảo vệ môi trường"),
    ("xử lý rác", "Luật Bảo vệ môi trường"),
    ("nghị định 08", "Nghị định số 08/2022/NĐ-CP"),
    ("sở hữu trí tuệ", "Luật Sở hữu trí tuệ"),
    ("nhãn hiệu", "Luật Sở hữu trí tuệ"),
    ("bản quyền", "Luật Sở hữu trí tuệ"),
    ("bảo hiểm nhân thọ", "Luật Kinh doanh bảo hiểm"),
    ("giao thông", "Luật Giao thông đường bộ"),
    ("vi phạm giao thông", "Luật Giao thông đường bộ"),
    ("bằng lái", "Luật Giao thông đường bộ"),
    ("giấy phép lái xe", "Luật Giao thông đường bộ"),
    ("bảo vệ người tiêu dùng", "Luật Bảo vệ quyền lợi người tiêu dùng"),
    ("hàng giả", "Luật Bảo vệ quyền lợi người tiêu dùng"),
    ("khiếu nại", "Luật Khiếu nại"),
    ("tố cáo", "Luật Tố cáo"),
    ("hành chính", "Luật Tố tụng hành chính"),
]

# Domain synonym expansions for high-precision FTS5 matching
SYNONYM_EXPANSIONS: dict[str, list[str]] = {
    "khai hoang": ["138", "139", "tự khai hoang", "không có giấy tờ", "cấp Giấy chứng nhận"],
    "đất khai hoang": ["138", "139", "tự khai hoang", "không có giấy tờ", "cấp Giấy chứng nhận"],
    "sổ đỏ": ["cấp Giấy chứng nhận", "quyền sử dụng đất"],
    "sổ hồng": ["cấp Giấy chứng nhận", "quyền sử dụng đất"],
    "sa thải": ["kỷ luật sa thải", "chấm dứt hợp đồng lao động", "bồi thường"],
    "thử việc": ["24", "25", "26", "thời gian thử việc", "tiền lương thử việc", "hợp đồng thử việc"],
    "bùng cọc": ["đặt cọc", "phạt cọc", "hủy hợp đồng"],
    "phòng trọ": ["thuê nhà ở", "hợp đồng thuê"],
    "người phụ thuộc": ["giảm trừ gia cảnh", "thuế thu nhập cá nhân"],
    "quán ăn": ["an toàn thực phẩm", "cơ sở kinh doanh dịch vụ ăn uống"],
    "epr": ["77", "trách nhiệm tái chế", "bao bì", "08/2022/NĐ-CP"],
    "trách nhiệm tái chế": ["77", "bao bì", "08/2022/NĐ-CP"],
    "tái chế bao bì": ["77", "trách nhiệm tái chế", "08/2022/NĐ-CP"],
}


# These terms are useful for routing but are not retrieval keys on their own.
# Without this guard a broad prompt such as ``2026 có luật gì mới`` would
# match arbitrary rows that merely contain the word ``luật``.
GENERIC_QUERY_WORDS = {
    "ban", "bản", "có", "định", "hiệu", "hành", "lực", "luật", "mới", "năm",
    "pháp", "quy", "quyết", "quyền", "thế", "văn", "được", "gì", "không",
    "nay", "hôm", "từ", "đến", "nào", "những", "các", "một", "số", "theo",
}

_QUERY_PHRASE_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(
            r"(?:tối\s*thiểu|ít\s*nhất).{0,48}cổ\s*đông|"
            r"cổ\s*đông.{0,48}(?:tối\s*thiểu|ít\s*nhất)",
            re.IGNORECASE,
        ),
        ("cổ đông", "tối thiểu"),
    ),
    (
        re.compile(r"cổ\s*đông\s*sáng\s*lập", re.IGNORECASE),
        ("cổ đông sáng lập",),
    ),
)

# Some Pháp điển rows keep a catalogue-level source note (for example
# ``Căn cứ Luật Doanh nghiệp``) while a duplicate row carries the instrument
# number.  Fill that missing identity from the corpus' stable law label so a
# source drawer never exposes an anonymous chunk.
CANONICAL_SOURCE_HINTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "luật doanh nghiệp",
        "59/2020/QH14",
        "http://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=142881",
        "Luật Doanh nghiệp 2020",
    ),
)


def _canonical_source_hint(*values: object) -> tuple[str, str, str]:
    text = " ".join(str(value or "") for value in values).casefold()
    for label, number, url, title in CANONICAL_SOURCE_HINTS:
        if label in text:
            return number, url, title
    return "", "", ""


class UniversalLegalRetriever:
    def __init__(self, db_path: str | Path | None = None):
        configured_path = db_path or os.getenv("UNIVERSAL_CORPUS_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured_path)

    @property
    def is_available(self) -> bool:
        if not self.db_path.is_file():
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{self.db_path.resolve().as_posix()}?mode=ro", uri=True)
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            return {"legal_articles", "legal_articles_fts"}.issubset(tables)
        except sqlite3.Error:
            return False
        finally:
            if connection is not None:
                connection.close()

    def _extract_components(self, query: str) -> tuple[list[str], list[str], list[str]]:
        q_lower = query.lower()
        
        # 1. Inject law names and multi-word phrases for matched domain keywords
        injected_law_names = []
        matched_phrases = []
        for kw, law_name in KNOWN_LAW_NAMES:
            if kw in q_lower:
                if law_name not in injected_law_names:
                    injected_law_names.append(law_name)
                if " " in kw and kw not in matched_phrases:
                    matched_phrases.append(kw)

        # 2. Inject synonyms for specialized colloquial expressions
        for trigger_phrase, synonyms in SYNONYM_EXPANSIONS.items():
            if trigger_phrase in q_lower:
                for syn in synonyms:
                    if syn not in matched_phrases and syn not in injected_law_names:
                        matched_phrases.append(syn)

        # Add high-signal phrase constraints for common factual questions.
        # They are consumed by the strict Tier-1 query below; the broad Tier-2
        # query remains available as a bounded recall fallback.
        for pattern, phrases in _QUERY_PHRASE_RULES:
            if pattern.search(q_lower):
                for phrase in phrases:
                    if phrase not in matched_phrases:
                        matched_phrases.append(phrase)

        # 3. Extract meaningful content words — exclude conversational stop words
        raw_words = re.findall(r"[\w]+", query)
        content_words = [
            w for w in raw_words
            if w.lower() not in LEGAL_STOP_WORDS
            and len(w) > 2
            and not w.isdigit()
        ]

        # 4. Remove content words already captured in matched phrases
        phrase_tokens = set()
        for p in matched_phrases:
            for tok in p.split():
                phrase_tokens.add(tok.lower())
        content_words = [w for w in content_words if w.lower() not in phrase_tokens]

        return injected_law_names, matched_phrases, content_words

    @staticmethod
    def _has_specific_retrieval_signal(query: str) -> bool:
        """Reject generic legal/year prompts before they hit the catalogue."""

        clean_query = " ".join((query or "").split())
        if not clean_query or explicit_anchors(clean_query):
            return bool(clean_query)
        lowered = clean_query.casefold()
        if any(keyword.casefold() in lowered for keyword, _law_name in KNOWN_LAW_NAMES):
            return True
        if any(phrase.casefold() in lowered for phrase in SYNONYM_EXPANSIONS):
            return True

        words = re.findall(r"[\wÀ-ỹĐđ]+", lowered, flags=re.UNICODE)
        meaningful = {
            word
            for word in words
            if len(word) >= 3
            and not word.isdigit()
            and word not in LEGAL_STOP_WORDS
            and word not in GENERIC_QUERY_WORDS
        }
        return len(meaningful) >= 2 or any(len(word) >= 7 for word in meaningful)

    @staticmethod
    def _strict_query_phrases(query: str) -> list[str]:
        lowered = (query or "").casefold()
        phrases: list[str] = []
        for pattern, values in _QUERY_PHRASE_RULES:
            if pattern.search(lowered):
                phrases.extend(value for value in values if value not in phrases)
        return phrases

    def _extract_search_terms(self, query: str) -> list[str]:
        laws, phrases, words = self._extract_components(query)
        all_terms = []
        for item in laws + phrases + words:
            if item and item not in all_terms:
                all_terms.append(item)
        return all_terms[:12]

    def search(self, query: str, limit: int = 5, topic_filter: str | None = None) -> list[dict[str, Any]]:
        """Executes a high-relevance BM25 search over 84,900+ Vietnamese legal articles.
        
        Returns a list of structured document dictionaries compatible with Agent pipelines.
        """
        if not self.is_available:
            return []

        clean_query = query.strip()
        if not clean_query:
            return []
        if not self._has_specific_retrieval_signal(clean_query):
            logger.info("Universal retrieval skipped generic query: %r", clean_query)
            return []

        laws, phrases, _words = self._extract_components(clean_query)
        terms = self._extract_search_terms(clean_query)
        if not terms:
            terms = re.findall(r"\b[\w\.]+\b", clean_query)[:4]

        # Build Tier 1 (Strict Intersection) and Tier 2 (Broad Union) queries
        tier1_query = None
        strict_phrases = self._strict_query_phrases(clean_query)
        if laws and strict_phrases:
            laws_clause = " OR ".join(f'"{_escape_fts5_term(t)}"' for t in laws)
            strict_clause = " AND ".join(f'"{_escape_fts5_term(p)}"' for p in strict_phrases)
            tier1_query = f"({laws_clause}) AND ({strict_clause})"
        elif laws and phrases:
            laws_clause = " OR ".join(f'"{_escape_fts5_term(t)}"' for t in laws)
            phrases_clause = " OR ".join(f'"{_escape_fts5_term(p)}"' for p in phrases)
            tier1_query = f"({laws_clause}) AND ({phrases_clause})"
        
        fts_query = " OR ".join(f'"{_escape_fts5_term(t)}"' for t in terms)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Execute FTS match with column weights (article_title: 10.0, source_note: 8.0, topic: 5.0)
            # and National Law priority bonus (3.0x multiplier on negative BM25 rank)
            sql = """
            SELECT 
                a.id, a.topic, a.subject, a.article_title, a.chapter_title, 
                a.source_note, a.source_url, a.content_text,
                (CASE 
                    WHEN a.topic = 'Luật Quốc gia' OR a.source_note LIKE 'Căn cứ Luật%' OR a.source_note LIKE 'Căn cứ Bộ luật%' 
                    THEN bm25(legal_articles_fts, 0.0, 5.0, 3.0, 10.0, 2.0, 8.0, 1.0) * 3.0 
                    ELSE bm25(legal_articles_fts, 0.0, 5.0, 3.0, 10.0, 2.0, 8.0, 1.0) 
                 END) AS adjusted_rank
            FROM legal_articles_fts fts
            JOIN legal_articles a ON fts.id = a.id
            WHERE legal_articles_fts MATCH ?
            ORDER BY adjusted_rank ASC
            LIMIT ?;
            """
            
            rows = []
            if tier1_query:
                try:
                    cursor.execute(sql, (tier1_query, limit * 3))
                    rows = cursor.fetchall()
                except sqlite3.Error:
                    rows = []

            # If Tier 1 didn't yield enough, run Tier 2 broad query
            if len(rows) < limit:
                cursor.execute(sql, (fts_query, limit * 4))
                rows = cursor.fetchall()

            conn.close()

            results = []
            seen_titles = set()

            for row in rows:
                rec_id, topic, subject, art_title, chap_title, src_note, src_url, content, rank = row
                
                # Deduplicate similar headers
                title_key = f"{topic}_{art_title[:50]}"
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                # Format hierarchical context for the LLM
                header_parts = []
                if topic:
                    header_parts.append(f"[CHỦ ĐỀ]: {topic}")
                if subject and subject != topic:
                    header_parts.append(f"[ĐỀ MỤC]: {subject}")
                if src_note:
                    header_parts.append(f"[CĂN CỨ VĂN BẢN]: {src_note}")
                if chap_title:
                    header_parts.append(f"[CHƯƠNG]: {chap_title}")
                if art_title:
                    header_parts.append(f"[ĐIỀU KHOẢN]: {art_title}")

                formatted_content = " | ".join(header_parts) + "\n\n" + content

                # Keep only a document URL supplied by the corpus.  A generic
                # catalogue homepage is not a usable citation target.
                final_url = src_url.strip() if src_url and src_url.strip().startswith(("http://", "https://")) else ""
                if final_url.rstrip("/").casefold() in {"http://vbpl.vn", "https://vbpl.vn"}:
                    final_url = ""

                # Extract friendly short source label
                source_label = src_note if src_note else (subject if subject else (topic if topic else "Cơ sở dữ liệu Pháp luật Quốc gia"))
                source_label = re.sub(r"^\s*\(|\)\s*$", "", source_label)
                instrument_match = re.search(
                    r"(?<![\w/])\d{1,5}/\d{4}/[A-ZĐ0-9][A-ZĐ0-9-]*(?![\w/])",
                    source_label,
                    flags=re.IGNORECASE,
                )
                instrument_number = instrument_match.group(0) if instrument_match else ""
                hinted_number, hinted_url, hinted_title = _canonical_source_hint(
                    rec_id,
                    topic,
                    subject,
                    art_title,
                    src_note,
                )
                if not instrument_number and hinted_number:
                    instrument_number = hinted_number
                if not final_url and hinted_url:
                    final_url = hinted_url
                if hinted_title and source_label.casefold().startswith("căn cứ"):
                    source_label = hinted_title

                results.append({
                    "document_id": rec_id,
                    "page_content": formatted_content,
                    "metadata": {
                        "Dieu": art_title if art_title else "Quy định pháp luật",
                        "source": source_label[:120],
                        "source_title": source_label[:500],
                        "Source_Title": source_label[:500],
                        "document_title": source_label[:500],
                        "Document_Number": instrument_number,
                        "instrument_number": instrument_number,
                        "legal_anchor": art_title if art_title else "",
                        "law_ref": src_note or "",
                        "official_url": final_url,
                        "source_uri": final_url,
                        "source_kind": "legal_corpus",
                        "authority": "official" if final_url else "unknown",
                        "source_document_id": (
                            f"universal:{instrument_number}"
                            if instrument_number
                            else final_url or f"universal:{rec_id}"
                        ),
                        "chunk_id": rec_id,
                        "topic": topic,
                        "subject": subject,
                        "chapter": chap_title,
                        "corpus_source": "universal_legal",
                    },
                    "score": abs(float(rank))
                })

                if len(results) >= limit:
                    break

            return results
        except (sqlite3.Error, OSError) as e:
            logger.debug("UniversalLegalRetriever search error: %s", e)
            return []


# Global singleton
universal_retriever = UniversalLegalRetriever()
