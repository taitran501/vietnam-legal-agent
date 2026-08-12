"""
Semantic-first legal document retrieval with rule-based boost and fast re-ranking.

Design:
1. Semantic search (PRIMARY) — handles ANY query, no manual rules
2. Rule-based boost (SECONDARY) — ONLY for explicit "Điều X", "Chương Y" mentions
3. Fast BM25-style re-ranking — no LLM dependency, scores by keyword overlap + metadata match

Speed targets:
- Semantic search: ~50-200ms (Qdrant vector search)
- Rule-based boost: ~5ms (O(1) lookup)
- Re-ranking: ~5-10ms (pure Python scoring)
- Total: <300ms for retrieval phase
"""

from __future__ import annotations

import logging
import math
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from functools import lru_cache
from typing import TypeVar

from langchain_core.documents import Document

from backend.api import metrics
from backend.config import get_settings
from backend.core.llm_instances import get_embeddings
from backend.core.retrieval import (
    _get_law_vectorstore,
    _get_qdrant_client,
)
from epr_agent.domain.legal import LegalAnchor, explicit_anchors, normalise_embedding_text

logger = logging.getLogger(__name__)

_QDRANT_RETRY_ATTEMPTS = 3
_QDRANT_RETRY_BASE_DELAY_SEC = 0.35
_RERANK_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ce-rerank")
_RETRIEVAL_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retrieval")

T = TypeVar("T")


def _is_retryable_qdrant_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    retry_markers = (
        "timed out",
        "handshake",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "network",
    )
    return any(marker in msg for marker in retry_markers)


def _with_qdrant_retry(op_name: str, fn: Callable[[], T]) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, _QDRANT_RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= _QDRANT_RETRY_ATTEMPTS or not _is_retryable_qdrant_error(exc):
                raise
            sleep_s = _QDRANT_RETRY_BASE_DELAY_SEC * attempt
            logger.warning(
                "Qdrant %s failed (attempt %d/%d): %s; retrying in %.2fs",
                op_name,
                attempt,
                _QDRANT_RETRY_ATTEMPTS,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)
    # Defensive fallback; loop always returns/raises.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Qdrant operation {op_name} failed without exception")


def _doc_label(doc: Document) -> str:
    return str(
        doc.metadata.get("Dieu")
        or doc.metadata.get("Chuong")
        or doc.metadata.get("Muc")
        or "unknown"
    )


def _debug_top_docs(stage: str, query: str, docs: list[Document], limit: int = 5) -> None:
    """Log a compact trace of the top docs for one retrieval stage."""
    if not docs:
        logger.info("%s trace for query=%r: no docs", stage, query)
        return

    preview = []
    for idx, doc in enumerate(docs[:limit], 1):
        preview.append({
            "rank": idx,
            "label": _doc_label(doc),
            "semantic": round(float(doc.metadata.get("semantic_score", 0.0) or 0.0), 4),
            "lexical": round(float(doc.metadata.get("lexical_score", 0.0) or 0.0), 4),
            "rerank": round(float(doc.metadata.get("rerank_score", 0.0) or 0.0), 4),
            "source": doc.metadata.get("retrieval_source", ""),
            "explicit": bool(doc.metadata.get("explicit_match", False)),
        })
    logger.info("%s trace for query=%r: %s", stage, query, preview)

# ---------------------------------------------------------------------------
# Article Index for O(1) lookup (used only for explicit article mentions)
# ---------------------------------------------------------------------------

_article_index: dict[str, list[str]] = {}  # article_name -> [point_id, ...]
_anchor_index: dict[str, list[str]] = {}  # article/clause/point exact key -> [point_id, ...]
_index_built = False
_article_index_lock = threading.Lock()
_article_index_collection = ""
_lexical_corpus: list[dict] = []
_lexical_index_built = False
_lexical_index_lock = threading.Lock()
_lexical_index_collection = ""
_global_idf: dict[str, float] = {}


def _canonical_article_keys(label: str) -> list[str]:
    """Return exact and shortened keys for article headings."""
    label = str(label or "").strip()
    if not label:
        return []

    keys = [label]
    match = re.match(r"^(điều\s+\d+)", label, flags=re.IGNORECASE)
    if match:
        short = match.group(1)
        if short not in keys:
            keys.append(short)
        normalized = short[0].upper() + short[1:]
        if normalized not in keys:
            keys.append(normalized)
    return keys


def _anchor_key(article: str, clause: str = "", point: str = "") -> str:
    return "|".join(" ".join(str(value or "").casefold().split()) for value in (article, clause, point))


def _build_article_index():
    """Build in-memory index mapping article names to point IDs.

    Only used when user explicitly mentions "Điều X" or "Chương Y".
    Built once at startup, O(N) cost.
    """
    global _anchor_index, _article_index, _index_built, _article_index_collection

    collection = _get_law_vectorstore().collection_name
    if _index_built and _article_index_collection == collection:
        return

    with _article_index_lock:
        if _index_built and _article_index_collection == collection:
            return
        _article_index = {}
        _anchor_index = {}
        client = _get_qdrant_client()
        vs = _get_law_vectorstore()

        offset = None
        while True:
            records, next_offset = _with_qdrant_retry(
                "scroll(article_index)",
                lambda offset=offset: client.scroll(
                    collection_name=vs.collection_name,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                ),
            )

            if not records:
                break

            for record in records:
                payload = record.payload or {}
                dieu = payload.get("Dieu", "")
                chuong = payload.get("Chuong", "")
                if dieu:
                    for key in _canonical_article_keys(dieu):
                        if key not in _article_index:
                            _article_index[key] = []
                        _article_index[key].append(record.id)
                    anchor_key = _anchor_key(dieu, payload.get("Khoan", ""), payload.get("Diem", ""))
                    _anchor_index.setdefault(anchor_key, []).append(record.id)
                if chuong:
                    chuong_key = f"chuong:{chuong}"
                    if chuong_key not in _article_index:
                        _article_index[chuong_key] = []
                    _article_index[chuong_key].append(record.id)

            if next_offset is None:
                break
            offset = next_offset

        _article_index_collection = vs.collection_name
        _index_built = True
        logger.info("Article index built: %d entries", len(_article_index))


def _get_point_ids_for_articles(article_names: list[str]) -> list[str]:
    """Get point IDs for given article names using O(1) index lookup."""
    _build_article_index()

    point_ids = []
    for article_name in article_names:
        if article_name in _article_index:
            point_ids.extend(_article_index[article_name])

    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for pid in point_ids:
        if pid not in seen:
            seen.add(pid)
            unique_ids.append(pid)

    return unique_ids


def _round_robin_anchor_ids(groups: list[list[str]], *, limit: int) -> list[str]:
    """Allocate explicit-retrieval capacity fairly across named anchors."""

    selected: list[str] = []
    seen: set[str] = set()
    cursors = [0] * len(groups)
    while len(selected) < limit:
        progressed = False
        for group_index, group in enumerate(groups):
            while cursors[group_index] < len(group) and group[cursors[group_index]] in seen:
                cursors[group_index] += 1
            if cursors[group_index] >= len(group):
                continue
            point_id = group[cursors[group_index]]
            cursors[group_index] += 1
            seen.add(point_id)
            selected.append(point_id)
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


def _get_point_ids_for_anchors(anchors: list[LegalAnchor], *, limit: int = 20) -> list[str]:
    """Resolve the most specific declared legal anchors before semantic search."""

    _build_article_index()
    groups: list[list[str]] = []
    for anchor in anchors:
        if not anchor.article:
            continue
        full_key = _anchor_key(anchor.article, anchor.clause, anchor.point)
        exact = _anchor_index.get(full_key, []) if (anchor.clause or anchor.point) else []
        # A clause/point can be absent because the raw source did not label it
        # cleanly. In that case Article chunks are candidates only; the V3
        # evidence gate later rejects them if the requested address is missing.
        groups.append(exact or _get_point_ids_for_articles([anchor.article]))
    return _round_robin_anchor_ids(groups, limit=limit)


def _build_lexical_index() -> None:
    """Build an in-memory lexical index for lightweight BM25-style retrieval."""
    global _lexical_corpus, _lexical_index_built, _global_idf, _lexical_index_collection

    collection = _get_law_vectorstore().collection_name
    if _lexical_index_built and _lexical_index_collection == collection:
        return

    with _lexical_index_lock:
        if _lexical_index_built and _lexical_index_collection == collection:
            return
        _lexical_corpus = []
        _global_idf = {}
        client = _get_qdrant_client()
        vs = _get_law_vectorstore()

        records = []
        offset = None
        while True:
            batch, next_offset = _with_qdrant_retry(
                "scroll(lexical_index)",
                lambda offset=offset: client.scroll(
                    collection_name=vs.collection_name,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                ),
            )
            if not batch:
                break
            records.extend(batch)
            if next_offset is None:
                break
            offset = next_offset

        doc_freq: Counter[str] = Counter()
        corpus: list[dict] = []
        for record in records:
            payload = record.payload or {}
            full_text = str(payload.get("lexical_text") or " ".join(
                str(part) for part in (
                    payload.get("Dieu", ""),
                    payload.get("Chuong", ""),
                    payload.get("Muc", ""),
                    payload.get("Text", ""),
                ) if part
            ))
            tokens = _tokenize_vietnamese(full_text)
            if not tokens:
                continue
            token_counts = Counter(re.findall(r"[\w]+", full_text.lower(), re.UNICODE))
            corpus.append({
                "id": record.id,
                "payload": payload,
                "tokens": tokens,
                "token_counts": token_counts,
                "doc_len": max(1, sum(token_counts.values())),
                "text": full_text.lower(),
            })
            doc_freq.update(tokens)

        num_docs = max(1, len(corpus))
        avg_doc_len = sum(doc["doc_len"] for doc in corpus) / num_docs
        _global_idf = {
            token: math.log(1 + (num_docs - freq + 0.5) / (freq + 0.5))
            for token, freq in doc_freq.items()
        }

        for doc in corpus:
            doc["avg_doc_len"] = avg_doc_len
            doc["idf"] = {
                token: _global_idf[token]
                for token in doc["tokens"]
            }

        _lexical_corpus = corpus
        _lexical_index_collection = vs.collection_name
        _lexical_index_built = True
        logger.info("Lexical index built: %d docs", len(_lexical_corpus))


def warmup_retrieval_indexes() -> None:
    """Warm lexical/article indexes to avoid first-query cold-start latency."""
    started = time.perf_counter()
    try:
        _build_lexical_index()
        _build_article_index()
        logger.info(
            "Retrieval indexes warmed in %.1fms (lexical_docs=%d article_keys=%d)",
            (time.perf_counter() - started) * 1000,
            len(_lexical_corpus),
            len(_article_index),
        )
    except Exception as exc:  # noqa: BLE001 - cold-start failure must not prevent the API starting
        logger.warning("Retrieval index warmup failed: %s", exc)


# ---------------------------------------------------------------------------
# Fast BM25-style re-ranking (no LLM dependency)
# ---------------------------------------------------------------------------

# Vietnamese stop words for scoring
_VIET_STOP_WORDS = {
    "là", "và", "của", "cho", "với", "trong", "có", "được", "không",
    "các", "những", "về", "để", "tại", "này", "đó", "cái",
    "một", "theo", "khi", "như", "từ", "đến", "vào", "ra", "lên",
    "xuống", "qua", "lại", "còn", "đã", "đang", "sẽ", "thì",
    "người", "tổ", "chức", "cá", "nhân", "thực", "hiện",
    "tôi", "mình", "ta", "bạn", "chúng", "họ", "anh", "chị",
    "công", "ty", "giờ", "phải", "cần", "gì", "nào", "đâu",
    "quy", "định", "liên", "quan", "điều", "chương", "mục",
    "nghị", "luật", "bảo", "vệ", "môi", "trường",
}


def _tokenize_vietnamese(text: str) -> set[str]:
    """Tokenize Vietnamese text into meaningful keywords (excluding stop words)."""
    text = text.lower()
    # Split on whitespace and punctuation
    tokens = re.findall(r'[\w]+', text, re.UNICODE)
    # Keep numeric legal references (e.g., "77", "79"), remove noisy short words otherwise.
    return {
        t
        for t in tokens
        if (t.isdigit() and len(t) <= 4) or (t not in _VIET_STOP_WORDS and len(t) > 2)
    }


_GENERIC_HEADING_MARKERS = (
    "điều khoản thi hành",
    "điều khoản chuyển tiếp",
    "sửa đổi, bổ sung",
)


def _extract_legal_references(query: str) -> dict[str, str]:
    """Extract explicit legal references (Điều/Chương/Mục) from query text."""
    q = query.lower()
    refs: dict[str, str] = {}
    dieu = re.search(r"\b(?:điều|dieu)\s+(\d+)\b", q)
    muc = re.search(r"\b(?:mục|muc)\s+(\d+)\b", q)
    chuong_num = re.search(r"\b(?:chương|chuong)\s+(\d+)\b", q)
    chuong_roman = re.search(r"\b(?:chương|chuong)\s+([ivxlcdm]+)\b", q)
    if dieu:
        refs["dieu"] = dieu.group(1)
    if muc:
        refs["muc"] = muc.group(1)
    if chuong_num:
        refs["chuong"] = chuong_num.group(1)
    elif chuong_roman:
        refs["chuong"] = chuong_roman.group(1)
    return refs


def _legal_reference_score(query: str, doc: Document) -> float:
    """Hard score for explicit legal references, especially Điều X queries."""
    refs = _extract_legal_references(query)
    if not refs:
        return 0.0

    dieu = str(doc.metadata.get("Dieu", "")).lower()
    chuong = str(doc.metadata.get("Chuong", "")).lower()
    muc = str(doc.metadata.get("Muc", "")).lower()
    heading = f"{dieu} {chuong} {muc}"

    score = 0.0
    if "dieu" in refs:
        expected = refs["dieu"]
        if re.search(rf"\bđiều\s+{re.escape(expected)}\b", heading):
            score += 1.0
        elif re.search(r"\bđiều\s+\d+\b", heading):
            score -= 0.35
    if "chuong" in refs:
        expected = refs["chuong"]
        if expected in heading:
            score += 0.45
    if "muc" in refs:
        expected = refs["muc"]
        if re.search(rf"\bmục\s+{re.escape(expected)}\b", heading):
            score += 0.45

    return max(-1.0, min(1.0, score))


def _intent_heading_score(query: str, doc: Document) -> float:
    """Boost heading/content that directly answers legal-intent queries."""
    q = query.lower()
    heading = " ".join(
        str(part).lower()
        for part in (
            doc.metadata.get("Dieu", ""),
            doc.metadata.get("Chuong", ""),
            doc.metadata.get("Muc", ""),
        )
        if part
    )
    content = (doc.page_content or "").lower()

    score = 0.0
    asks_subject_scope = any(kw in q for kw in ("đối tượng", "lộ trình"))
    if asks_subject_scope and any(kw in heading for kw in ("đối tượng", "lộ trình")):
        score += 0.75
    asks_rate_spec = any(kw in q for kw in ("tỷ lệ", "quy cách"))
    if asks_rate_spec and any(kw in heading for kw in ("tỷ lệ", "quy cách")):
        score += 0.6
    if any(kw in q for kw in ("chi phí", "đóng góp", "f")) and any(kw in heading for kw in ("chi phí", "đóng góp", "f")):
        score += 0.5

    product_terms = ("ắc quy", "dầu nhớt", "săm lốp", "pet", "hdpe", "bao bì")
    matched_product = next((term for term in product_terms if term in q), "")
    if matched_product and "phụ lục xxii" in heading and matched_product in content:
        score += 0.9
    if asks_subject_scope and "phụ lục xxii" in heading and not matched_product:
        score -= 0.45

    if any(marker in heading for marker in _GENERIC_HEADING_MARKERS) and "thi hành" not in q and "sửa đổi" not in q and "chuyển tiếp" not in q:
        score -= 0.55

    # Strongly demote broad terminal clauses for specific EPR questions.
    if "điều 169" in heading and "điều khoản thi hành" in heading and any(kw in q for kw in ("tỷ lệ", "quy cách", "đối tượng", "trách nhiệm", "tái chế")):
        score -= 0.75

    return max(-1.0, min(1.0, score))


def _extract_query_phrases(text: str, max_phrases: int = 8) -> list[str]:
    """
    Extract meaningful multi-word phrases from the query.

    Exact legal phrases are often the difference between the right article and a
    nearby-but-wrong article. This keeps the reranker generic while rewarding
    contiguous phrase matches such as "đánh giá sự phù hợp" or
    "chất ô nhiễm khó phân hủy".
    """
    raw_tokens = re.findall(r"[\w]+", text.lower(), re.UNICODE)
    filtered = [t for t in raw_tokens if t not in _VIET_STOP_WORDS and len(t) > 2]
    phrases: list[str] = []
    seen: set[str] = set()

    for size in range(5, 1, -1):
        if len(filtered) < size:
            continue
        for i in range(len(filtered) - size + 1):
            phrase = " ".join(filtered[i:i + size]).strip()
            if phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
            if len(phrases) >= max_phrases:
                return phrases
    return phrases


def _normalize_text(text: str) -> str:
    """Normalize text for simple ordered phrase matching."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _extract_ordered_phrases(text: str, max_phrases: int = 8) -> list[str]:
    """
    Extract short ordered phrases without removing stop words.

    This helps capture procedural wording such as
    "trước khi bán ra thị trường" that gets weakened when stop words are
    stripped for keyword-only scoring.
    """
    tokens = re.findall(r"[\w]+", text.lower(), re.UNICODE)
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for size in range(5, 2, -1):
        if len(tokens) < size:
            continue
        for i in range(len(tokens) - size + 1):
            window = tokens[i:i + size]
            phrase = " ".join(window).strip()
            if len("".join(window)) < 10:
                continue
            if phrase in seen:
                continue
            seen.add(phrase)
            informative = sum(1 for token in window if token not in _VIET_STOP_WORDS and len(token) > 2)
            edge_bonus = 1 if i == 0 or i + size == len(tokens) else 0
            score = informative * 10 + size + edge_bonus
            candidates.append((score, phrase))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [phrase for _, phrase in candidates[:max_phrases]]


def _normalize_semantic_score(score: object) -> float:
    """Best-effort normalization for Qdrant cosine scores."""
    if score is None:
        return 0.0
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _normalize_lexical_score(score: float) -> float:
    """Squash unbounded lexical scores into [0, 1)."""
    if score <= 0:
        return 0.0
    return score / (score + 4.0)


def _salient_query_tokens(query_tokens: set[str], limit: int = 3) -> list[str]:
    """Return the rarest query tokens as high-signal anchors for reranking."""
    if not query_tokens:
        return []
    ranked = sorted(
        query_tokens,
        key=lambda token: (_global_idf.get(token, 0.0), len(token)),
        reverse=True,
    )
    return ranked[:limit]


def _weighted_token_ratio(tokens: set[str], text_tokens: set[str]) -> float:
    """Compute an IDF-weighted token coverage ratio in [0, 1]."""
    if not tokens:
        return 0.0
    weighted_total = sum(_global_idf.get(token, 1.0) for token in tokens)
    if weighted_total <= 0:
        return len(tokens & text_tokens) / len(tokens)
    weighted_hits = sum(_global_idf.get(token, 1.0) for token in tokens if token in text_tokens)
    return weighted_hits / weighted_total


def _bm25_score(query_tokens: list[str], doc: dict, k1: float = 1.5, b: float = 0.75) -> float:
    """Compute a lightweight BM25 score for one document."""
    if not query_tokens:
        return 0.0

    score = 0.0
    token_counts = doc["token_counts"]
    doc_len = doc["doc_len"]
    avg_doc_len = doc["avg_doc_len"]

    for token in query_tokens:
        tf = token_counts.get(token, 0)
        if tf <= 0:
            continue
        idf = doc["idf"].get(token, 0.0)
        denom = tf + k1 * (1 - b + b * (doc_len / avg_doc_len))
        score += idf * ((tf * (k1 + 1)) / denom)

    return score


def _score_breakdown(query: str, doc: Document, is_explicit_match: bool = False) -> dict[str, float | bool]:
    """Return the full relevance score breakdown for one document."""
    query_tokens = _tokenize_vietnamese(query)
    legal_ref_score = _legal_reference_score(query, doc)
    intent_heading_score = _intent_heading_score(query, doc)

    if not query_tokens:
        return {
            "overlap": 0.5,
            "metadata": 0.0,
            "tf": 0.0,
            "phrase": 0.0,
            "ordered_phrase": 0.0,
            "rare_token": 0.0,
            "salient_token": 0.0,
            "legal_ref": round(legal_ref_score, 4),
            "intent_heading": round(intent_heading_score, 4),
            "semantic": 0.0,
            "lexical": 0.0,
            "explicit_boost": is_explicit_match,
            "final": round(max(0.0, min(1.0, 0.5 + 0.35 * legal_ref_score + 0.25 * intent_heading_score)), 4),
        }

    doc_text = f"{doc.metadata.get('Dieu', '')} {doc.metadata.get('Chuong', '')} {doc.metadata.get('Muc', '')} {doc.page_content[:1000]}".lower()
    doc_tokens = _tokenize_vietnamese(doc_text)
    query_phrases = _extract_query_phrases(query)
    ordered_phrases = _extract_ordered_phrases(query)
    normalized_doc_text = _normalize_text(doc_text)
    lead_text = f"{doc.metadata.get('Dieu', '')} {doc.page_content[:320]}".lower()
    normalized_lead_text = _normalize_text(lead_text)

    # 1. Keyword overlap score (0-1)
    overlap = _weighted_token_ratio(query_tokens, doc_tokens)

    # 2. Metadata match score (0-1)
    metadata_text = f"{doc.metadata.get('Dieu', '')} {doc.metadata.get('Chuong', '')} {doc.metadata.get('Muc', '')}".lower()
    metadata_tokens = _tokenize_vietnamese(metadata_text)
    metadata_score = _weighted_token_ratio(query_tokens, metadata_tokens)

    # 3. Content term frequency score (0-1)
    weighted_tf = sum(
        min(2, doc_text.count(token)) * _global_idf.get(token, 1.0)
        for token in query_tokens
    )
    weighted_total = sum(_global_idf.get(token, 1.0) for token in query_tokens)
    tf_score = min(1.0, weighted_tf / max(1.0, weighted_total * 1.5))

    # 4. Phrase coverage score (0-1)
    if query_phrases:
        matched_phrases = sum(1 for phrase in query_phrases if phrase in doc_text)
        phrase_score = matched_phrases / len(query_phrases)
    else:
        phrase_score = overlap

    # 5. Ordered phrase score (0-1)
    if ordered_phrases:
        matched_ordered = sum(1 for phrase in ordered_phrases if phrase in normalized_doc_text)
        ordered_phrase_score = matched_ordered / len(ordered_phrases)
    else:
        ordered_phrase_score = phrase_score

    # 6. Rare-token coverage score (0-1)
    if _global_idf and query_tokens:
        weighted_total = sum(_global_idf.get(token, 0.0) for token in query_tokens)
        if weighted_total > 0:
            weighted_hits = sum(
                _global_idf.get(token, 0.0)
                for token in query_tokens
                if token in doc_tokens
            )
            rare_token_score = weighted_hits / weighted_total
        else:
            rare_token_score = overlap
    else:
        rare_token_score = overlap

    # 7. Salient-token score (0-1)
    salient_tokens = _salient_query_tokens(query_tokens)
    if salient_tokens:
        salient_hits = sum(1 for token in salient_tokens if token in doc_tokens)
        salient_token_score = salient_hits / len(salient_tokens)
    else:
        salient_token_score = rare_token_score

    # 8. Lead-text score (0-1)
    lead_tokens = _tokenize_vietnamese(lead_text)
    if lead_tokens:
        lead_overlap = _weighted_token_ratio(query_tokens, lead_tokens)
    else:
        lead_overlap = 0.0
    if ordered_phrases:
        lead_ordered = sum(1 for phrase in ordered_phrases if phrase in normalized_lead_text) / len(ordered_phrases)
    else:
        lead_ordered = ordered_phrase_score
    lead_score = 0.6 * lead_overlap + 0.4 * lead_ordered

    # 9. Semantic score from Qdrant retrieval (0-1)
    semantic_score = _normalize_semantic_score(
        doc.metadata.get("semantic_score", doc.metadata.get("score"))
    )

    # 10. Lexical score from BM25 candidate retrieval (0-1)
    lexical_score = _normalize_lexical_score(float(doc.metadata.get("lexical_score", 0.0)))

    # Combine scores
    final_score = (
        0.1 * overlap
        + 0.06 * metadata_score
        + 0.06 * tf_score
        + 0.12 * phrase_score
        + 0.1 * ordered_phrase_score
        + 0.08 * rare_token_score
        + 0.12 * salient_token_score
        + 0.12 * lead_score
        + 0.1 * semantic_score
        + 0.08 * lexical_score
        + 0.18 * legal_ref_score
        + 0.08 * intent_heading_score
    )

    # Boost explicit matches (user said "Điều X" and we found it)
    if is_explicit_match:
        final_score = min(1.0, final_score * 1.3)

    return {
        "overlap": round(overlap, 4),
        "metadata": round(metadata_score, 4),
        "tf": round(tf_score, 4),
        "phrase": round(phrase_score, 4),
        "ordered_phrase": round(ordered_phrase_score, 4),
        "rare_token": round(rare_token_score, 4),
        "salient_token": round(salient_token_score, 4),
        "lead": round(lead_score, 4),
        "legal_ref": round(legal_ref_score, 4),
        "intent_heading": round(intent_heading_score, 4),
        "semantic": round(semantic_score, 4),
        "lexical": round(lexical_score, 4),
        "explicit_boost": is_explicit_match,
        "final": round(final_score, 4),
    }


def _score_document(query: str, doc: Document, is_explicit_match: bool = False) -> float:
    """
    Score a document for relevance to query.

    If is_explicit_match (user said "Điều X"), boost score significantly.
    """
    return float(_score_breakdown(query, doc, is_explicit_match)["final"])


def _doc_identity(doc: Document) -> str:
    """Build a stable-ish identity for rank comparison in shadow mode."""
    return str(
        doc.metadata.get("_id")
        or doc.metadata.get("Dieu")
        or doc.metadata.get("Chuong")
        or doc.metadata.get("Muc")
        or doc.page_content[:80]
    )


class BaseReranker(ABC):
    """Unified reranker contract used by heuristic and cross-encoder engines."""

    name: str

    @abstractmethod
    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        raise NotImplementedError


class HeuristicReranker(BaseReranker):
    name = "heuristic"

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        if not docs:
            return []

        scored: list[tuple[Document, float]] = []
        for doc in docs:
            score = _score_document(
                query,
                doc,
                is_explicit_match=bool(doc.metadata.get("explicit_match", False)),
            )
            scored.append((doc, score))

        scored.sort(key=lambda item: item[1], reverse=True)

        result: list[Document] = []
        for rank, (doc, score) in enumerate(scored[:top_k], start=1):
            breakdown = _score_breakdown(
                query,
                doc,
                is_explicit_match=bool(doc.metadata.get("explicit_match", False)),
            )
            doc.metadata["rerank_score"] = round(score, 4)
            doc.metadata["heuristic_rerank_score"] = round(score, 4)
            doc.metadata.setdefault("retrieval_debug", {})
            doc.metadata["retrieval_debug"]["query"] = query
            doc.metadata["retrieval_debug"]["semantic_score"] = breakdown["semantic"]
            doc.metadata["retrieval_debug"]["lexical_score"] = breakdown["lexical"]
            doc.metadata["retrieval_debug"]["rerank_score"] = breakdown["final"]
            doc.metadata["retrieval_debug"]["retrieval_source"] = doc.metadata.get("retrieval_source", "")
            doc.metadata["retrieval_debug"]["explicit_match"] = breakdown["explicit_boost"]
            doc.metadata["retrieval_debug"]["breakdown"] = breakdown
            doc.metadata["retrieval_debug"]["primary_rank"] = rank
            result.append(doc)

        return result


class CrossEncoderReranker(BaseReranker):
    name = "cross_encoder"

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self.unavailable_reason: str | None = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if self.unavailable_reason is not None:
            raise RuntimeError(self.unavailable_reason)

        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except Exception as exc:
            self.unavailable_reason = "sentence-transformers is required for cross-encoder reranking"
            raise RuntimeError(self.unavailable_reason) from exc

        self._model = CrossEncoder(self.model_name)
        return self._model

    def _format_doc(self, doc: Document) -> str:
        header = " ".join(
            str(part)
            for part in (
                doc.metadata.get("Dieu", ""),
                doc.metadata.get("Chuong", ""),
                doc.metadata.get("Muc", ""),
            )
            if part
        ).strip()
        content = " ".join(doc.page_content.split())[:480]
        return f"{header}\n{content}".strip()

    def rerank(self, query: str, docs: list[Document], top_k: int) -> list[Document]:
        if not docs:
            return []

        model = self._ensure_model()
        pairs = [(query, self._format_doc(doc)) for doc in docs]
        raw_scores = model.predict(pairs, show_progress_bar=False)

        scored: list[tuple[Document, float]] = []
        for doc, score in zip(docs, raw_scores):
            score_f = float(score)
            doc.metadata["cross_encoder_score"] = round(score_f, 6)
            scored.append((doc, score_f))

        scored.sort(key=lambda item: item[1], reverse=True)

        ranked: list[Document] = []
        for rank, (doc, score) in enumerate(scored[:top_k], start=1):
            doc.metadata["rerank_score"] = round(score, 6)
            doc.metadata.setdefault("retrieval_debug", {})
            doc.metadata["retrieval_debug"]["cross_encoder_score"] = round(score, 6)
            doc.metadata["retrieval_debug"]["cross_rank"] = rank
            ranked.append(doc)
        return ranked


def _run_rerank_with_timeout(
    reranker: BaseReranker,
    query: str,
    docs: list[Document],
    top_k: int,
    timeout_ms: int,
) -> list[Document]:
    timeout_s = max(0.01, timeout_ms / 1000.0)
    future = _RERANK_EXECUTOR.submit(reranker.rerank, query, docs, top_k)
    return future.result(timeout=timeout_s)


# ---------------------------------------------------------------------------
# Semantic-First Ensemble Retriever
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_ensemble_retriever(k: int = 10):
    """Get ensemble retriever singleton."""
    return _EnsembleRetriever(k=k)


class _EnsembleRetriever:
    """
    Semantic-first retriever with rule-based boost for explicit article mentions.

    Flow:
    1. Always run semantic search (handles ANY query)
    2. If user explicitly mentions "Điều X" → fetch those articles and merge with boost
    3. Re-rank all candidates by relevance score
    """

    def __init__(self, k: int = 10):
        self.k = k
        settings = get_settings()
        candidate_k = max(k + 5, settings.rerank_top_n)
        self.semantic_k = max(candidate_k, 15)
        self.lexical_k = max(candidate_k, 15)
        self._heuristic_reranker = HeuristicReranker()
        self._cross_encoder_reranker = CrossEncoderReranker(settings.cross_encoder_model_name)
        # Shadow ranking is optional telemetry.  If its local dependency is
        # absent, detect that once and keep the active heuristic ranking quiet.
        self._cross_encoder_shadow_available = True

    def invoke(
        self,
        query: str,
        *,
        required_anchors: list[str] | None = None,
        metadata_filters: dict[str, str] | None = None,
    ) -> list[Document]:
        """Retrieve documents using semantic-first approach."""
        started = time.perf_counter()
        stage_ms: dict[str, float] = {}
        required_anchors = [str(anchor).strip() for anchor in (required_anchors or []) if str(anchor).strip()]
        metadata_filters = {str(key): str(value) for key, value in (metadata_filters or {}).items() if str(value).strip()}
        retrieval_query = " ".join([query, *required_anchors]).strip()

        # Step 1: Run semantic + lexical retrieval in parallel.
        def _timed_semantic() -> tuple[list[Document], float]:
            stage_started = time.perf_counter()
            docs = self._retrieve_semantic(retrieval_query, k=self.semantic_k)
            return docs, (time.perf_counter() - stage_started) * 1000

        def _timed_lexical() -> tuple[list[Document], float]:
            stage_started = time.perf_counter()
            docs = self._retrieve_lexical(retrieval_query, k=self.lexical_k)
            return docs, (time.perf_counter() - stage_started) * 1000

        stage_started = time.perf_counter()
        semantic_future = _RETRIEVAL_EXECUTOR.submit(_timed_semantic)
        lexical_future = _RETRIEVAL_EXECUTOR.submit(_timed_lexical)
        semantic_result = semantic_future.result()
        lexical_result = lexical_future.result()
        stage_ms["retrieve_parallel"] = round((time.perf_counter() - stage_started) * 1000, 1)
        semantic_docs, semantic_ms = semantic_result
        lexical_docs, lexical_ms = lexical_result
        stage_ms["semantic"] = round(semantic_ms, 1)
        stage_ms["lexical"] = round(lexical_ms, 1)

        # Step 2: Parse every explicit anchor before an LLM can rewrite it.
        stage_started = time.perf_counter()
        anchors = explicit_anchors(retrieval_query)
        stage_ms["parse"] = round((time.perf_counter() - stage_started) * 1000, 1)
        explicit_articles = [anchor.article for anchor in anchors if anchor.article]

        rule_docs = []
        if anchors:
            stage_started = time.perf_counter()
            rule_docs = self._retrieve_explicit_anchors(anchors)
            stage_ms["explicit"] = round((time.perf_counter() - stage_started) * 1000, 1)
        else:
            stage_ms["explicit"] = 0.0

        # Step 3: Merge results
        stage_started = time.perf_counter()
        final_docs = self._fuse_and_rerank(
            semantic_docs,
            lexical_docs,
            rule_docs,
            query,
            explicit_articles,
        )
        if metadata_filters:
            final_docs = [
                document
                for document in final_docs
                if all(
                    str(document.metadata.get(key, "")).casefold() == value.casefold()
                    for key, value in metadata_filters.items()
                )
            ]
        for document in final_docs:
            document.metadata.setdefault("typed_retrieval", {})
            document.metadata["typed_retrieval"].update({
                "required_anchors": required_anchors,
                "metadata_filters": metadata_filters,
            })
        stage_ms["rerank_merge"] = round((time.perf_counter() - stage_started) * 1000, 1)

        stage_ms["total"] = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "retrieval latency query=%r retrieve_parallel=%sms semantic=%sms lexical=%sms parse=%sms explicit=%sms rerank_merge=%sms total=%sms",
            query,
            stage_ms["retrieve_parallel"],
            stage_ms["semantic"],
            stage_ms["lexical"],
            stage_ms["parse"],
            stage_ms["explicit"],
            stage_ms["rerank_merge"],
            stage_ms["total"],
        )

        for doc in final_docs:
            doc.metadata.setdefault("retrieval_debug", {})
            doc.metadata["retrieval_debug"]["latency_ms"] = stage_ms

        return final_docs[:self.k]

    def _should_apply_cross_encoder(self) -> bool:
        settings = get_settings()
        if not settings.enable_cross_encoder_rerank:
            return False
        rollout = max(0, min(100, settings.cross_encoder_rollout_percent))
        if rollout <= 0:
            return False
        return random.random() * 100 < rollout

    def _annotate_shadow_ranks(self, final_docs: list[Document], shadow_docs: list[Document]) -> None:
        shadow_rank_map = {
            _doc_identity(doc): idx
            for idx, doc in enumerate(shadow_docs, start=1)
        }
        for idx, doc in enumerate(final_docs, start=1):
            doc.metadata.setdefault("retrieval_debug", {})
            doc.metadata["retrieval_debug"]["primary_rank"] = idx
            doc.metadata["retrieval_debug"]["shadow_rank"] = shadow_rank_map.get(_doc_identity(doc))
            doc.metadata["retrieval_debug"]["shadow_engine"] = self._cross_encoder_reranker.name

    def _select_with_explicit_coverage(
        self,
        ranked: list[Document],
        explicit_articles: list[str],
        *,
        limit: int,
    ) -> list[Document]:
        """Reserve one ranked chunk per named Article before filling top-k."""

        selected: list[Document] = []
        for article in explicit_articles:
            match = next((document for document in ranked if self._matches_article(document, article)), None)
            if match is not None and match not in selected:
                selected.append(match)
        for document in ranked:
            if len(selected) >= limit:
                break
            if document not in selected:
                selected.append(document)
        return selected[:limit]

    def _rerank_candidates(
        self,
        query: str,
        candidates: list[Document],
        explicit_articles: list[str],
    ) -> list[Document]:
        if not candidates:
            return []

        settings = get_settings()
        candidate_limit = max(1, settings.rerank_top_n)
        rerank_candidates = candidates[:candidate_limit]

        started = time.perf_counter()
        heuristic_ranked = self._heuristic_reranker.rerank(query, rerank_candidates, top_k=candidate_limit)
        heuristic_docs = self._select_with_explicit_coverage(
            heuristic_ranked,
            explicit_articles,
            limit=self.k,
        )
        heuristic_ms = (time.perf_counter() - started) * 1000
        metrics.track_rerank_latency_ms("apply", self._heuristic_reranker.name, heuristic_ms)
        for doc in heuristic_docs:
            doc.metadata.setdefault("retrieval_debug", {})
            doc.metadata["retrieval_debug"]["rerank_engine"] = self._heuristic_reranker.name
            doc.metadata["retrieval_debug"]["rerank_mode"] = "apply"
            doc.metadata["retrieval_debug"]["heuristic_rerank_latency_ms"] = round(heuristic_ms, 2)
            doc.metadata["retrieval_debug"]["cross_encoder_timeout"] = False
            doc.metadata["retrieval_debug"]["rerank_fallback"] = False

        if not settings.enable_cross_encoder_rerank:
            return heuristic_docs

        apply_cross_encoder = self._should_apply_cross_encoder()
        run_shadow = settings.cross_encoder_shadow_mode and not apply_cross_encoder

        if apply_cross_encoder:
            try:
                started = time.perf_counter()
                cross_docs = _run_rerank_with_timeout(
                    self._cross_encoder_reranker,
                    query,
                    rerank_candidates,
                    candidate_limit,
                    settings.rerank_timeout_ms,
                )
                cross_ms = (time.perf_counter() - started) * 1000
                metrics.track_rerank_latency_ms("apply", self._cross_encoder_reranker.name, cross_ms)
                for doc in cross_docs:
                    doc.metadata.setdefault("retrieval_debug", {})
                    doc.metadata["retrieval_debug"]["rerank_engine"] = self._cross_encoder_reranker.name
                    doc.metadata["retrieval_debug"]["rerank_mode"] = "apply"
                    doc.metadata["retrieval_debug"]["cross_encoder_latency_ms"] = round(cross_ms, 2)
                    doc.metadata["retrieval_debug"]["cross_encoder_timeout"] = False
                    doc.metadata["retrieval_debug"]["rerank_fallback"] = False
                return self._select_with_explicit_coverage(cross_docs, explicit_articles, limit=self.k)
            except FutureTimeoutError:
                metrics.track_rerank_timeout(self._cross_encoder_reranker.name)
                metrics.track_rerank_fallback("timeout", self._cross_encoder_reranker.name, self._heuristic_reranker.name)
                logger.warning(
                    "Cross-encoder timeout at %dms, fallback to heuristic",
                    settings.rerank_timeout_ms,
                )
                for doc in heuristic_docs:
                    doc.metadata.setdefault("retrieval_debug", {})
                    doc.metadata["retrieval_debug"]["cross_encoder_timeout"] = True
                    doc.metadata["retrieval_debug"]["rerank_fallback"] = True
                if settings.rerank_fallback_on_timeout:
                    return heuristic_docs
            except Exception as exc:  # noqa: BLE001 - optional cross-encoder must fall back safely
                metrics.track_rerank_fallback("error", self._cross_encoder_reranker.name, self._heuristic_reranker.name)
                logger.warning("Cross-encoder apply failed, fallback to heuristic: %s", exc)
                for doc in heuristic_docs:
                    doc.metadata.setdefault("retrieval_debug", {})
                    doc.metadata["retrieval_debug"]["cross_encoder_timeout"] = False
                    doc.metadata["retrieval_debug"]["rerank_fallback"] = True
                return heuristic_docs

        if run_shadow and self._cross_encoder_shadow_available:
            try:
                started = time.perf_counter()
                shadow_docs = _run_rerank_with_timeout(
                    self._cross_encoder_reranker,
                    query,
                    rerank_candidates,
                    candidate_limit,
                    settings.rerank_timeout_ms,
                )
                shadow_ms = (time.perf_counter() - started) * 1000
                metrics.track_rerank_latency_ms("shadow", self._cross_encoder_reranker.name, shadow_ms)
                self._annotate_shadow_ranks(heuristic_docs, shadow_docs)
                for doc in heuristic_docs:
                    doc.metadata.setdefault("retrieval_debug", {})
                    doc.metadata["retrieval_debug"]["cross_encoder_shadow_latency_ms"] = round(shadow_ms, 2)
            except FutureTimeoutError:
                metrics.track_rerank_timeout(self._cross_encoder_reranker.name)
                metrics.track_rerank_fallback("shadow_timeout", self._cross_encoder_reranker.name, self._heuristic_reranker.name)
                logger.warning(
                    "Cross-encoder shadow timeout at %dms for query=%r",
                    settings.rerank_timeout_ms,
                    query,
                )
                for doc in heuristic_docs:
                    doc.metadata.setdefault("retrieval_debug", {})
                    doc.metadata["retrieval_debug"]["cross_encoder_shadow_timeout"] = True
            except Exception as exc:  # noqa: BLE001 - shadow telemetry must not affect ranking
                metrics.track_rerank_fallback("shadow_error", self._cross_encoder_reranker.name, self._heuristic_reranker.name)
                if self._cross_encoder_reranker.unavailable_reason is not None:
                    self._cross_encoder_shadow_available = False
                    logger.info(
                        "Cross-encoder shadow disabled for this process: %s",
                        self._cross_encoder_reranker.unavailable_reason,
                    )
                else:
                    logger.warning("Cross-encoder shadow failed for query=%r: %s", query, exc)
                for doc in heuristic_docs:
                    doc.metadata.setdefault("retrieval_debug", {})
                    doc.metadata["retrieval_debug"]["cross_encoder_shadow_error"] = str(exc)

        return heuristic_docs

    def _retrieve_semantic(self, query: str, k: int = 15) -> list[Document]:
        """Primary retrieval: semantic vector search."""
        try:
            settings = get_settings()
            vs = _get_law_vectorstore()
            client = _get_qdrant_client()
            query_vector = get_embeddings().embed_query(normalise_embedding_text(query))

            try:
                from qdrant_client.models import SearchParams
                search_params = SearchParams(hnsw_ef=settings.search_ef)
            except Exception:  # noqa: BLE001 - older Qdrant clients may not expose SearchParams
                search_params = None

            def _query_points():
                kwargs = {
                    "collection_name": vs.collection_name,
                    "query": query_vector,
                    "limit": k,
                    "with_payload": True,
                    "with_vectors": False,
                }
                if search_params is not None:
                    kwargs["search_params"] = search_params
                try:
                    return client.query_points(**kwargs)
                except TypeError:
                    kwargs.pop("search_params", None)
                    return client.query_points(**kwargs)

            response = _with_qdrant_retry(
                "query_points(semantic)",
                _query_points,
            )

            points = getattr(response, "points", None) or []
            docs = []
            for point in points:
                payload = point.payload or {}
                metadata = {
                    key: value
                    for key, value in payload.items()
                    if key != "Text"
                }
                metadata.setdefault("filter_matched", False)
                metadata.setdefault("explicit_match", False)
                metadata["semantic_score"] = _normalize_semantic_score(getattr(point, "score", 0.0))
                metadata["retrieval_source"] = "semantic"
                metadata["_id"] = point.id
                docs.append(
                    Document(
                        page_content=str(payload.get("Text", "")),
                        metadata=metadata,
                    )
                )
            _debug_top_docs("semantic", query, docs)
            return docs
        except Exception as exc:  # noqa: BLE001 - retriever failure becomes an evidence-safe stop
            logger.warning("Semantic retrieval failed: %s", exc)
            return []

    def _retrieve_lexical(self, query: str, k: int = 15) -> list[Document]:
        """Secondary retrieval: lightweight BM25-style lexical matching."""
        try:
            _build_lexical_index()
        except Exception as exc:  # noqa: BLE001 - lexical failure leaves dense candidates available
            logger.warning("Lexical index build failed: %s", exc)
            return []
        query_tokens = [
            token
            for token in re.findall(r"[\w]+", query.lower(), re.UNICODE)
            if token not in _VIET_STOP_WORDS and len(token) > 2
        ]
        if not query_tokens or not _lexical_corpus:
            return []

        scored = []
        for doc in _lexical_corpus:
            score = _bm25_score(query_tokens, doc)
            if score <= 0:
                continue
            scored.append((doc, score))

        scored.sort(key=lambda item: item[1], reverse=True)

        docs: list[Document] = []
        for doc, score in scored[:k]:
            payload = doc["payload"]
            metadata = dict(payload)
            metadata.update(
                {
                    "filter_matched": False,
                    "explicit_match": False,
                    "lexical_score": score,
                    "retrieval_source": "lexical",
                    "_id": doc["id"],
                }
            )
            docs.append(
                Document(
                    page_content=payload.get("Text", ""),
                    metadata=metadata,
                )
            )

        _debug_top_docs("lexical", query, docs)
        return docs

    def _retrieve_explicit_anchors(self, anchors: list[LegalAnchor]) -> list[Document]:
        """Direct metadata lookup for named Article/Clause/Point addresses."""
        vs = _get_law_vectorstore()
        client = vs.client
        collection = vs.collection_name

        try:
            point_ids = _get_point_ids_for_anchors(anchors[:5], limit=20)
            if not point_ids:
                return []

            points = _with_qdrant_retry(
                "retrieve(explicit_articles)",
                lambda: client.retrieve(
                    collection_name=collection,
                    ids=point_ids,
                    with_payload=True,
                    with_vectors=False,
                ),
            )

            if not points:
                return []

            docs = []
            for point in points:
                payload = dict(point.payload or {})
                is_exact = any(
                    _anchor_key(
                        str(payload.get("Dieu") or ""),
                        str(payload.get("Khoan") or ""),
                        str(payload.get("Diem") or ""),
                    )
                    == _anchor_key(anchor.article, anchor.clause, anchor.point)
                    for anchor in anchors
                )
                metadata = dict(payload)
                metadata.update(
                    {
                        "filter_matched": True,
                        "explicit_match": is_exact or any(
                            anchor.article.casefold() in str(payload.get("Parent_Dieu") or payload.get("Dieu") or "").casefold()
                            for anchor in anchors
                            if anchor.article and not (anchor.clause or anchor.point)
                        ),
                        "explicit_anchor_match": is_exact,
                        "retrieval_source": "explicit",
                        "_id": point.id,
                    }
                )
                doc = Document(
                    page_content=payload.get("Text", ""),
                    metadata=metadata,
                )
                docs.append(doc)

            _debug_top_docs("explicit", " | ".join(anchor.key() for anchor in anchors), docs)
            return docs

        except Exception as exc:  # noqa: BLE001 - exact lookup failure must not fabricate an anchor
            logger.warning("Explicit article retrieval failed: %s", exc)
            return []

    @staticmethod
    def _article_label(document: Document) -> str:
        return str(document.metadata.get("Parent_Dieu") or document.metadata.get("Dieu") or "")

    @staticmethod
    def _matches_article(document: Document, article: str) -> bool:
        return article.lower() in _EnsembleRetriever._article_label(document).lower()

    def _fuse_and_rerank(
        self,
        semantic_docs: list[Document],
        lexical_docs: list[Document],
        rule_docs: list[Document],
        query: str,
        explicit_articles: list[str],
    ) -> list[Document]:
        """Fuse dense, BM25, and exact candidates by stable chunk identity.

        V3 intentionally deduplicates at chunk level.  A legal article can
        contain several relevant Khoản/Điểm units, so using ``Điều`` as a key
        silently lost evidence for compare and checklist routes.
        """

        merged: dict[str, Document] = {}

        def add_candidates(documents: list[Document], source: str) -> None:
            for rank, candidate in enumerate(documents, start=1):
                key = _doc_identity(candidate)
                if key not in merged:
                    merged[key] = Document(page_content=candidate.page_content, metadata=dict(candidate.metadata))
                target = merged[key]
                target.metadata.update({key: value for key, value in candidate.metadata.items() if value not in (None, "")})
                target.metadata[f"{source}_rank"] = rank
                if source == "explicit":
                    target.metadata["explicit_match"] = True

        add_candidates(semantic_docs, "dense")
        add_candidates(lexical_docs, "bm25")
        add_candidates(rule_docs, "explicit")

        candidates = list(merged.values())
        for document in candidates:
            dense_rank = document.metadata.get("dense_rank")
            bm25_rank = document.metadata.get("bm25_rank")
            explicit_rank = document.metadata.get("explicit_rank")
            rrf = sum(1.0 / (60.0 + float(rank)) for rank in (dense_rank, bm25_rank, explicit_rank) if rank)
            document.metadata["rrf_score"] = round(rrf, 8)
            document.metadata["combined_score"] = round(rrf, 8)
            document.metadata["score"] = round(rrf, 8)

        candidates.sort(
            key=lambda document: (
                0 if any(self._matches_article(document, article) for article in explicit_articles) else 1,
                -float(document.metadata.get("rrf_score") or 0.0),
            )
        )
        reranked = self._rerank_candidates(query, candidates, explicit_articles)
        final_docs = self._diversify(reranked, explicit_articles)
        _debug_top_docs("final", query, final_docs)
        return final_docs

    def _diversify(self, documents: list[Document], explicit_articles: list[str]) -> list[Document]:
        """Keep no more than two chunks per article after relevance ranking."""

        selected: list[Document] = []
        counts: Counter[str] = Counter()

        # Multi-anchor questions must retain a representative chunk per anchor.
        for article in explicit_articles:
            match = next((doc for doc in documents if self._matches_article(doc, article)), None)
            if match is not None and match not in selected:
                selected.append(match)
                counts[self._article_label(match)] += 1

        for document in documents:
            if document in selected:
                continue
            article = self._article_label(document) or _doc_identity(document)
            if counts[article] >= 2:
                document.metadata["rejection_reason"] = "diversity_cap_per_article"
                continue
            counts[article] += 1
            selected.append(document)
        return selected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve_legal_ensemble(
    query: str,
    k: int = 10,
    *,
    required_anchors: list[str] | None = None,
    metadata_filters: dict[str, str] | None = None,
) -> list[Document]:
    """
    Retrieve legal documents using semantic-first ensemble.

    This is the recommended retrieval method for production use.

    Args:
        query: User's question
        k: Number of documents to return

    Returns:
        List of relevant documents, ranked by relevance score
    """
    retriever = _get_ensemble_retriever(k=k)
    return retriever.invoke(
        query,
        required_anchors=required_anchors,
        metadata_filters=metadata_filters,
    )
