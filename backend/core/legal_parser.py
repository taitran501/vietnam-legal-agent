"""
Rule-based legal query parser — replaces LLM-based SelfQueryRetriever.

Parses Vietnamese legal queries to extract structured filters for:
- Dieu (Article numbers): "Điều 77", "điều 77", "dieu 77"
- Chuong (Chapter): "Chương II", "chương 2", "chuong II"
- Muc (Section): "Mục 1", "mục 1"
- Product types: maps to specific articles
- Concepts: maps to specific articles

This eliminates the 1-3s LLM latency per query and removes OpenAI API costs
for query construction.

ENHANCED: Now includes keyword-based article mapping for broader coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from qdrant_client.models import Condition, FieldCondition, Filter, MatchText, MatchValue, MinShould

# ---------------------------------------------------------------------------
# Roman numeral conversion
# ---------------------------------------------------------------------------

_ROMAN_TO_INT = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
    'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
    'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15,
    'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20,
}


def _roman_to_int(roman: str) -> int | None:
    """Convert Roman numeral string to integer."""
    return _ROMAN_TO_INT.get(roman.upper().strip())


# ---------------------------------------------------------------------------
# Query parser
# ---------------------------------------------------------------------------

@dataclass
class LegalFilter:
    """Extracted filter conditions from a legal query."""
    dieu_number: int | None = None      # e.g., 77 from "Điều 77"
    dieu_text: str | None = None        # Full match: "Điều 77"
    chuong_number: int | None = None    # e.g., 2 from "Chương II" or "Chương 2"
    chuong_text: str | None = None      # Full match: "Chương II"
    muc_number: int | None = None       # e.g., 1 from "Mục 1"
    muc_text: str | None = None         # Full match: "Mục 1"
    free_query: str = ""                   # Remaining text for semantic search
    # NEW: Keyword-based article hints for broader coverage
    related_articles: list[str] = field(default_factory=list)  # e.g., ["Điều 77", "Điều 78"]


def parse_legal_query(query: str) -> LegalFilter:
    """
    Parse a Vietnamese legal query and extract structured filters.
    
    Examples:
        "Điều 77 quy định gì?" → LegalFilter(dieu_number=77, free_query="quy định gì")
        "Chương 2 về tái chế" → LegalFilter(chuong_number=2, free_query="về tái chế")
        "Mục 1 của chương 2" → LegalFilter(muc_number=1, chuong_number=2, free_query="của")
        "Trách nhiệm tái chế" → LegalFilter(free_query="trách nhiệm tái chế")
    """
    original = query
    query_lower = query.lower()
    
    result = LegalFilter(free_query=query)
    
    # -----------------------------------------------------------------------
    # 1. Extract "Điều X" (article number)
    # -----------------------------------------------------------------------
    # Pattern: "điều" + optional whitespace + number
    dieu_pattern = re.search(r'\bđiều\s+(\d+)', query_lower)
    if dieu_pattern:
        result.dieu_number = int(dieu_pattern.group(1))
        result.dieu_text = f"Điều {result.dieu_number}"
        # Remove matched part from free query
        result.free_query = query[:dieu_pattern.start()] + query[dieu_pattern.end():]
        result.free_query = result.free_query.strip()
    
    # -----------------------------------------------------------------------
    # 2. Extract "Chương X" (chapter) — supports Roman or Arabic numerals
    # -----------------------------------------------------------------------
    # Pattern: "chương" + optional whitespace + Roman numeral OR Arabic number
    chuong_roman_pattern = re.search(r'(?:^|\s)chương\s+([ivxlcdmIVXLCDM]+)', query_lower)
    chuong_arabic_pattern = re.search(r'(?:^|\s)chương\s+(\d+)', query_lower)
    
    if chuong_roman_pattern:
        roman = chuong_roman_pattern.group(1)
        result.chuong_number = _roman_to_int(roman)
        if result.chuong_number:
            result.chuong_text = f"Chương {roman.upper()}"
            start, end = chuong_roman_pattern.span()
            result.free_query = (result.free_query[:start] + result.free_query[end:]).strip()
    elif chuong_arabic_pattern:
        result.chuong_number = int(chuong_arabic_pattern.group(1))
        result.chuong_text = f"Chương {result.chuong_number}"
        start, end = chuong_arabic_pattern.span()
        result.free_query = (result.free_query[:start] + result.free_query[end:]).strip()
    
    # -----------------------------------------------------------------------
    # 3. Extract "Mục X" (section)
    # -----------------------------------------------------------------------
    muc_pattern = re.search(r'\bmục\s+(\d+)', query_lower)
    if muc_pattern:
        result.muc_number = int(muc_pattern.group(1))
        result.muc_text = f"Mục {result.muc_number}"
        start, end = muc_pattern.span()
        result.free_query = (result.free_query[:start] + result.free_query[end:]).strip()
    
    # Clean up free query
    result.free_query = ' '.join(result.free_query.split()) or original

    # ── NEW: Keyword-based article mapping for broader coverage ─────────
    # This significantly improves retrieval recall by mapping query keywords
    # to likely relevant articles, even when no explicit "Điều X" is mentioned.
    # IMPORTANT: Concept matching runs BEFORE product matching to ensure
    # specific concepts like "tỷ lệ" override general product terms.

    query_lower = query.lower()

    # Concept → article mapping (CHECKED FIRST for priority)
    concept_map = {
        'xử phạt': ['Điều 81', 'Điều 82'],
        'vi phạm': ['Điều 81'],
        'đăng ký': ['Điều 79', 'Điều 80'],
        'kế hoạch': ['Điều 79', 'Điều 80'],
        'báo cáo': ['Điều 80'],
        'tài chính': ['Điều 81', 'Điều 80'],
        'đóng góp': ['Điều 81', 'Điều 80'],
        'quỹ': ['Điều 81'],
        'cơ sở': ['Điều 80'],
        'điều kiện': ['Điều 80'],
        'quy cách': ['Điều 78'],
        'tỷ lệ': ['Phụ lục XXII', 'Điều 78'],  # Must come first!
        'lộ trình': ['Điều 77'],
        '2024': ['Điều 77'],
        '2025': ['Điều 77'],
        '2027': ['Điều 77'],
        'tái chế': ['Điều 77', 'Điều 78', 'Điều 79'],
        'nghĩa vụ': ['Điều 77', 'Điều 78'],
        'trách nhiệm': ['Điều 77'],
        'nhà sản xuất': ['Điều 77'],
        'nhập khẩu': ['Điều 77'],
        'ủy quyền': ['Điều 79', 'Điều 80'],
        'tiêu chuẩn': ['Điều 80'],
        'công nhận': ['Điều 80'],
        'bộ tài nguyên': ['Điều 82'],
        'quản lý': ['Điều 82'],
        'hỗ trợ': ['Điều 82'],
        # Environmental impact assessment (ĐTM)
        'tham vấn': ['Điều 29', 'Điều 30', 'Điều 31', 'Điều 32', 'Điều 33'],
        'đánh giá tác động': ['Điều 25', 'Điều 26', 'Điều 27', 'Điều 28', 'Điều 29', 'Điều 30', 'Điều 31', 'Điều 32', 'Điều 33'],
        'đánh giá môi trường': ['Điều 25', 'Điều 26', 'Điều 27', 'Điều 28', 'Điều 29'],
        'đtm': ['Điều 25', 'Điều 26', 'Điều 27', 'Điều 28', 'Điều 29'],
        'môi trường chiến lược': ['Điều 17', 'Điều 18', 'Điều 19', 'Điều 20', 'Điều 21', 'Điều 22', 'Điều 23', 'Điều 24'],
        'đối tượng': ['Điều 25', 'Điều 26', 'Điều 27', 'Điều 28', 'Điều 29', 'Điều 30', 'Điều 31', 'Điều 32', 'Điều 33'],
        'phụ lục': ['Phụ lục XXII', 'Phụ lục II', 'Phụ lục III', 'Phụ lục IV', 'Phụ lục V', 'Phụ lục VI', 'Phụ lục VII'],
        'giấy phép': ['Điều 39', 'Điều 40', 'Điều 41', 'Điều 42', 'Điều 43', 'Điều 44', 'Điều 45', 'Điều 46', 'Điều 47', 'Điều 48', 'Điều 49', 'Điều 50'],
        'quan trắc': ['Điều 57', 'Điều 58', 'Điều 59', 'Điều 60'],
        'chất thải': ['Điều 61', 'Điều 62', 'Điều 63', 'Điều 64', 'Điều 65', 'Điều 66', 'Điều 67', 'Điều 68', 'Điều 69', 'Điều 70', 'Điều 71', 'Điều 72', 'Điều 73', 'Điều 74', 'Điều 75', 'Điều 76'],
        'khí thải': ['Điều 65', 'Điều 66', 'Điều 67'],
        'nước thải': ['Điều 61', 'Điều 62', 'Điều 63', 'Điều 64'],
        'chất thải nguy hại': ['Điều 68', 'Điều 69', 'Điều 70'],
        'chất thải rắn': ['Điều 71', 'Điều 72', 'Điều 73', 'Điều 74', 'Điều 75', 'Điều 76'],
    }
    for concept, articles in concept_map.items():
        if concept in query_lower:
            result.related_articles.extend(articles)

    # Product type → article mapping (checked SECOND)
    product_map = {
        'ắc quy': ['Điều 77', 'Điều 78'],
        'pin sạc': ['Điều 77', 'Điều 78'],
        'pin': ['Điều 77', 'Điều 78'],
        'dầu nhớt': ['Điều 77', 'Phụ lục XXII'],
        'săm lốp': ['Điều 77', 'Điều 78', 'Phụ lục XXII'],
        'bao bì': ['Phụ lục XXII', 'Điều 77'],  # FIX: Phụ lục first for bao bì
        'phương tiện giao thông': ['Điều 77', 'Điều 78'],
        'phương tiện': ['Điều 77', 'Điều 78'],
        'xe': ['Điều 77', 'Điều 78'],
        'điện tử': ['Điều 77', 'Điều 78'],
        'điện thoại': ['Điều 77'],
        'ô tô': ['Điều 77', 'Điều 78'],
        'xe máy': ['Điều 77', 'Điều 78'],
        'xe đạp điện': ['Điều 77', 'Điều 78'],
    }
    for product, articles in product_map.items():
        if product in query_lower:
            result.related_articles.extend(articles)

    # Remove duplicates while preserving order. Keep this explicit instead of
    # relying on ``set.add``'s always-None return value; the latter is concise
    # but obscures the invariant and is not type-safe.
    seen: set[str] = set()
    unique_articles: list[str] = []
    for article in result.related_articles:
        if article in seen:
            continue
        seen.add(article)
        unique_articles.append(article)
    result.related_articles = unique_articles

    return result


# ---------------------------------------------------------------------------
# Qdrant filter builder
# ---------------------------------------------------------------------------

def build_qdrant_filter(legal_filter: LegalFilter) -> Filter | None:
    """
    Convert a LegalFilter into a Qdrant Filter object.

    ENHANCED: Now uses related_articles from keyword mapping when
    no explicit dieu_number is present, significantly improving coverage.

    Returns None if no structured filters were extracted (pure semantic search).
    """
    conditions: list[Condition] = []

    # Match Dieu number exactly (explicit mention)
    if legal_filter.dieu_number is not None:
        # Support both formats: integer and "Điều X" string
        conditions.append(
            FieldCondition(
                key="Dieu",
                match=MatchValue(value=f"Điều {legal_filter.dieu_number}"),
            )
        )

    # Match Chuong text (like "Chương II", "Chương III")
    if legal_filter.chuong_text is not None:
        conditions.append(
            FieldCondition(
                key="Chuong",
                match=MatchText(text=legal_filter.chuong_text),
            )
        )

    # Match Muc text (like "Mục 1", "Mục 2")
    if legal_filter.muc_text is not None:
        conditions.append(
            FieldCondition(
                key="Muc",
                match=MatchValue(value=legal_filter.muc_text),
            )
        )

    # NEW: Use related_articles from keyword mapping when no explicit conditions
    # This is the critical fix that enables keyword-based retrieval
    if not conditions and legal_filter.related_articles:
        # Build OR filter for all related articles
        should_conditions: list[Condition] = []
        for article_name in legal_filter.related_articles[:5]:  # Limit to 5 articles
            # IMPORTANT: Use MatchText (substring) instead of MatchValue (exact)
            # because Dieu field is "Điều 80. <description>" not just "Điều 80"
            should_conditions.append(
                FieldCondition(
                    key="Dieu",
                    match=MatchText(text=article_name),
                )
            )
        
        if should_conditions:
            # Use "should" (OR) with min_should=1 to match ANY of the articles
            return Filter(
                should=should_conditions,
                min_should=MinShould(
                    min_count=1,
                    conditions=should_conditions,
                ),
            )

    if not conditions:
        return None

    return Filter(must=conditions)
