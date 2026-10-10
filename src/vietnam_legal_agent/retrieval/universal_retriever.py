"""Universal Vietnamese Legal Retriever.

Provides high-precision retrieval over 84,900+ Codified Legal Articles (Pháp điển)
and 318 National Codes & Laws across all Vietnamese legal domains.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from vietnam_legal_agent.domain.legal import LegalAnchor, explicit_anchors, instrument_name_tokens

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
    "ai", "đâu", "sao", "lại", "đã", "sẽ", "cũng", "đều", "rồi", "ngay", "bị", "làm",
}
_EXACT_ANCHOR_FTS_STOPWORDS = {
    "bộ", "luật", "nghị", "định", "thông", "tư", "quyết", "pháp", "lệnh",
}


def _escape_fts5_term(term: str) -> str:
    """Escape double-quote characters for SQLite FTS5 MATCH syntax."""
    return term.replace('"', '""')


class LegalQueryExpander:
    """Dynamic query analyzer and expansion engine for Vietnamese legal queries."""

    ARTICLE_PATTERN = re.compile(r"(?:điều|khoản|điểm)\s+\d+[a-zĐđ]?", re.IGNORECASE)
    INSTRUMENT_PATTERN = re.compile(r"\b\d{1,5}/\d{4}/(?:NĐ-CP|TT-[A-ZĐ]+|QH\d+|UBTVQH\d+|QĐ-[A-ZĐ]+)\b", re.IGNORECASE)
    LAW_PREFIX_PATTERN = re.compile(r"\b(?:Bộ luật|Luật|Nghị định|Thông tư|Nghị quyết|Quyết định)\s+[\w\sÀ-ỹĐđ]{2,40}\b", re.IGNORECASE)
    NON_TITLE_PREFIX_WORDS: ClassVar[set[str]] = {
        "áp", "bao", "có", "được", "gì", "hướng", "làm", "nào", "phải",
        "quy", "sao", "thế", "thực", "trong", "về",
    }

    @classmethod
    def extract_legal_entities(cls, query: str) -> list[str]:
        """Dynamically extract legal articles, instrument IDs, and legislative names."""
        entities: list[str] = []
        for m in cls.ARTICLE_PATTERN.finditer(query):
            val = m.group(0).strip()
            if val not in entities:
                entities.append(val)
        for m in cls.INSTRUMENT_PATTERN.finditer(query):
            val = m.group(0).strip()
            if val not in entities:
                entities.append(val)
        for m in cls.LAW_PREFIX_PATTERN.finditer(query):
            val = m.group(0).strip()
            if query[:m.start()].casefold().rstrip().endswith("pháp"):
                continue
            title_words = [word.casefold() for word in val.split()]
            kind_words = 2 if title_words[:2] == ["bộ", "luật"] else 1
            if len(title_words) <= kind_words or title_words[kind_words] in cls.NON_TITLE_PREFIX_WORDS:
                continue
            if val not in entities and len(val.split()) <= 6:
                entities.append(val)
        return entities

    @classmethod
    def extract_ngrams(cls, text: str, min_n: int = 2, max_n: int = 4) -> list[str]:
        """Extract multi-word noun phrases and legal concepts dynamically within natural spans."""
        tokens = re.findall(r"[\wÀ-ỹĐđ]+", text)
        spans: list[list[str]] = []
        current_span: list[str] = []
        for tok in tokens:
            if tok.lower() in LEGAL_STOP_WORDS or tok.isdigit():
                if current_span:
                    spans.append(current_span)
                    current_span = []
            else:
                current_span.append(tok)
        if current_span:
            spans.append(current_span)

        ngrams: list[str] = []
        for span in spans:
            for n in range(min_n, min(len(span) + 1, max_n + 1)):
                for i in range(len(span) - n + 1):
                    phrase = " ".join(span[i : i + n])
                    if len(phrase) >= 4 and phrase not in ngrams:
                        ngrams.append(phrase)
        return ngrams


# Generic words that are filtered out unless reinforced with legal terms
GENERIC_QUERY_WORDS = {
    "ban", "bản", "có", "định", "hiệu", "hành", "lực", "luật", "mới", "năm",
    "pháp", "quy", "quyết", "quyền", "thế", "văn", "được", "gì", "không",
    "nay", "hôm", "từ", "đến", "nào", "những", "các", "một", "số", "theo",
}


class UniversalLegalRetriever:
    def __init__(self, db_path: str | Path | None = None):
        configured_path = db_path or os.getenv("UNIVERSAL_CORPUS_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured_path)
        manifest_path = PROJECT_ROOT / "data" / "universal_corpus_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        self.corpus_id = str(manifest.get("corpus_id") or "universal-vietnamese-legal")
        self.corpus_version = str(manifest.get("corpus_version") or "content-locked")

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
            if not {"legal_articles", "legal_articles_fts"}.issubset(tables):
                return False
            return connection.execute(
                "SELECT 1 FROM legal_articles LIMIT 1"
            ).fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if connection is not None:
                connection.close()

    def _extract_components(self, query: str) -> tuple[list[str], list[str], list[str]]:
        # 1. Dynamic statutory entity and anchor extraction
        injected_law_names = LegalQueryExpander.extract_legal_entities(query)

        # 2. Dynamic concept n-grams
        matched_phrases = list(LegalQueryExpander.extract_ngrams(query))

        # 3. Extract meaningful content words — exclude conversational stop words
        raw_words = re.findall(r"[\wÀ-ỹĐđ]+", query, flags=re.UNICODE)
        content_words = [
            w for w in raw_words
            if w.lower() not in LEGAL_STOP_WORDS
            and len(w) > 1
            and not w.isdigit()
        ]

        return injected_law_names, matched_phrases, content_words

    @staticmethod
    def _has_specific_retrieval_signal(query: str) -> bool:
        """Reject generic legal/year prompts before they hit the catalogue."""
        clean_query = " ".join((query or "").split())
        if not clean_query or explicit_anchors(clean_query):
            return bool(clean_query)
        lowered = clean_query.casefold()

        words = re.findall(r"[\wÀ-ỹĐđ]+", lowered, flags=re.UNICODE)
        meaningful = {
            word
            for word in words
            if len(word) >= 2
            and not word.isdigit()
            and word not in LEGAL_STOP_WORDS
            and word not in GENERIC_QUERY_WORDS
        }
        return len(meaningful) >= 2 or any(len(word) >= 7 for word in meaningful)

    def _detect_corpus_topic(self, query: str, cursor: sqlite3.Cursor) -> str | None:
        """Dynamically detect if query references an indexed corpus domain without hardcoding."""
        try:
            if not hasattr(self, "_cached_topics"):
                rows = cursor.execute(
                    "SELECT DISTINCT topic FROM legal_articles WHERE topic IS NOT NULL AND topic != 'Luật Quốc gia'"
                ).fetchall()
                self._cached_topics = [str(r[0]) for r in rows if r[0]]
            q_lower = query.casefold()
            for topic in self._cached_topics:
                top_lower = topic.casefold()
                if re.search(rf"\b{re.escape(top_lower)}\b", q_lower):
                    return topic
                for part in re.split(r"[,/]", top_lower):
                    part = part.strip()
                    if len(part) >= 4 and re.search(rf"\b{re.escape(part)}\b", q_lower):
                        return topic
        except sqlite3.Error:
            pass
        return None

    def _extract_search_terms(self, query: str, cursor: sqlite3.Cursor | None = None) -> list[str]:
        laws, _phrases, words = self._extract_components(query)
        all_terms: list[str] = []
        for item in laws + words:
            if item and item not in all_terms:
                all_terms.append(item)
        if cursor is None:
            return all_terms[:12]

        # Rank generic terms by corpus document frequency. Long user queries
        # can produce dozens of overlapping n-grams; choosing the first dozen
        # is position-biased and can drop the rare event/outcome words that
        # identify the applicable provision. FTS5 already exposes the corpus
        # vocabulary and per-term document counts, so use its IDF signal to
        # preserve the most informative, non-redundant terms.
        try:
            cursor.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS temp.universal_legal_vocab "
                "USING fts5vocab(main, legal_articles_fts, 'row')"
            )
            tokens = {
                token.casefold()
                for candidate in all_terms
                for token in re.findall(r"[\wÀ-ỹĐđ]+", candidate, flags=re.UNICODE)
                if token.casefold() not in LEGAL_STOP_WORDS
            }
            frequencies: dict[str, int] = {}
            token_list = list(tokens)
            for offset in range(0, len(token_list), 800):
                batch = token_list[offset : offset + 800]
                placeholders = ",".join("?" for _ in batch)
                rows = cursor.execute(
                    f"SELECT term, doc FROM temp.universal_legal_vocab WHERE term IN ({placeholders})",
                    batch,
                ).fetchall()
                frequencies.update({str(term).casefold(): int(doc_count) for term, doc_count in rows})
            document_count = max(1, int(cursor.execute("SELECT COUNT(*) FROM legal_articles").fetchone()[0]))

            def idf(token: str) -> float:
                frequency = frequencies.get(token, 0)
                return math.log((document_count + 1) / (frequency + 1))

            selected = [term for term in laws if term][:12]
            covered = {
                token
                for term in selected
                for token in re.findall(r"[\wÀ-ỹĐđ]+", term, flags=re.UNICODE)
            }
            remaining = [term for term in all_terms if term not in selected]
            while remaining and len(selected) < 12:
                best_index = 0
                best_score = float("-inf")
                for index, term in enumerate(remaining):
                    term_tokens = [
                        token.casefold()
                        for token in re.findall(r"[\wÀ-ỹĐđ]+", term, flags=re.UNICODE)
                        if token.casefold() not in LEGAL_STOP_WORDS
                    ]
                    new_tokens = [token for token in term_tokens if token not in covered]
                    score = (
                        sum(idf(token) for token in new_tokens) / math.sqrt(len(new_tokens))
                        if new_tokens
                        else float("-inf")
                    )
                    if score > best_score:
                        best_index, best_score = index, score
                term = remaining.pop(best_index)
                if best_score == float("-inf"):
                    break
                selected.append(term)
                covered.update(
                    token.casefold()
                    for token in re.findall(r"[\wÀ-ỹĐđ]+", term, flags=re.UNICODE)
                )
            return selected
        except sqlite3.Error:
            # A corpus build without FTS5 vocabulary support can still use the
            # deterministic, bounded candidate order.
            return all_terms[:12]

    @staticmethod
    def _row_matches_anchor(row: tuple[Any, ...], anchor: LegalAnchor) -> bool:
        _record_id, topic, subject, article_title, chapter_title, source_note, source_url, _content, _rank = row
        source_note_text = str(source_note or "").casefold()
        source_text = " ".join(
            str(value or "")
            for value in (topic, subject, article_title, chapter_title, source_note, source_url)
        )
        source_anchors = explicit_anchors(f"{source_note or ''}\n{article_title or ''}")
        if anchor.article and not any(item.article.casefold() == anchor.article.casefold() for item in source_anchors):
            return False
        if anchor.document_number and anchor.document_number.casefold() not in str(source_note or "").casefold():
            return False
        if anchor.document_title:
            title_tokens = instrument_name_tokens(anchor.document_title)
            if not title_tokens or not all(token in source_text.casefold() for token in title_tokens):
                return False
            kind_match = re.match(
                r"\s*(bộ\s+luật|luật|nghị\s*định|thông\s*tư|quyết\s*định|nghị\s*quyết|pháp\s*lệnh)",
                anchor.document_title,
                re.IGNORECASE,
            )
            if kind_match:
                kind = " ".join(kind_match.group(1).casefold().split())
                if kind == "bộ luật" and "bộ luật" not in source_note_text:
                    return False
                if kind != "bộ luật" and kind not in source_note_text:
                    return False
        return not anchor.appendix or anchor.appendix.casefold() in source_text.casefold()

    @classmethod
    def _search_exact_anchors(
        cls,
        cursor: sqlite3.Cursor,
        anchors: Sequence[LegalAnchor],
        limit: int,
    ) -> list[tuple[Any, ...]]:
        """Use legal source addresses to find exact articles before fuzzy FTS."""

        candidates: dict[str, tuple[Any, ...]] = {}
        for anchor in anchors:
            article_match = re.search(r"\b(?:điều|dieu)\s+(\d+[a-zđ]?)\b", anchor.article, re.IGNORECASE)
            if not article_match or not (anchor.document_number or anchor.document_title):
                continue
            article_number = article_match.group(1)
            identifying_tokens = (
                instrument_name_tokens(anchor.document_number)
                if anchor.document_number
                else instrument_name_tokens(anchor.document_title)
            )
            identifying_tokens = [
                token
                for token in identifying_tokens
                if token not in _EXACT_ANCHOR_FTS_STOPWORDS
            ]
            fts_terms = [f'"Điều {article_number}"']
            fts_terms.extend(f'"{_escape_fts5_term(token)}"' for token in identifying_tokens)
            fts_query = " AND ".join(dict.fromkeys(fts_terms))

            cursor.execute(
                """
                SELECT a.id, a.topic, a.subject, a.article_title, a.chapter_title,
                       a.source_note, a.source_url, a.content_text, 0.0
                FROM legal_articles_fts
                JOIN legal_articles a ON legal_articles_fts.id = a.id
                WHERE legal_articles_fts MATCH ?
                LIMIT 5000
                """,
                (fts_query,),
            )
            for row in cursor.fetchall():
                if cls._row_matches_anchor(row, anchor):
                    candidates[str(row[0])] = row

        return list(candidates.values())[: max(1, limit)]

    def search(
        self,
        query: str,
        limit: int = 5,
        topic_filter: str | None = None,
        required_anchors: Sequence[LegalAnchor] | None = None,
    ) -> list[dict[str, Any]]:
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

        anchors = list(required_anchors) if required_anchors is not None else explicit_anchors(clean_query)
        has_named_article_anchor = any(
            anchor.article and (anchor.document_number or anchor.document_title)
            for anchor in anchors
        )

        selected_scope = topic_filter
        scope_sql = ""
        scope_params: tuple[str, ...] = ()

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if not selected_scope:
                selected_scope = self._detect_corpus_topic(clean_query, cursor)
            if selected_scope:
                scope = selected_scope.casefold()
                scope_sql = " AND lower(a.topic) = ?"
                scope_params = (scope,)

            laws, phrases, _words = self._extract_components(clean_query)
            terms = self._extract_search_terms(clean_query, cursor)
            if not terms:
                terms = re.findall(r"\b[\w\.]+\b", clean_query)[:4]

            # Build Tier 1 (concept phrase) and Tier 2 (broad lexical) queries.
            tier1_query = None
            if laws and phrases:
                laws_clause = " OR ".join(f'"{_escape_fts5_term(t)}"' for t in laws)
                phrases_clause = " OR ".join(f'"{_escape_fts5_term(p)}"' for p in phrases)
                tier1_query = f"({laws_clause}) AND ({phrases_clause})"
            fts_query = " OR ".join(f'"{_escape_fts5_term(t)}"' for t in terms)

            # Execute FTS match with column weights (article_title: 10.0, source_note: 8.0, topic: 5.0)
            # and National Assembly primary statute priority bonus (2.0x multiplier on negative BM25 rank)
            sql = f"""
            SELECT 
                a.id, a.topic, a.subject, a.article_title, a.chapter_title, 
                a.source_note, a.source_url, a.content_text,
                (CASE 
                    WHEN a.topic = 'Luật Quốc gia' 
                      OR a.source_note LIKE '%Bộ luật%' 
                      OR a.source_note LIKE '%/QH%' 
                      OR a.source_note LIKE '%Luật số%'
                    THEN bm25(legal_articles_fts, 0.0, 5.0, 3.0, 10.0, 2.0, 8.0, 1.0) * 2.0 
                    ELSE bm25(legal_articles_fts, 0.0, 5.0, 3.0, 10.0, 2.0, 8.0, 1.0) 
                 END) AS adjusted_rank
            FROM legal_articles_fts fts
            JOIN legal_articles a ON fts.id = a.id
            WHERE legal_articles_fts MATCH ?
            {scope_sql}
            ORDER BY adjusted_rank ASC
            LIMIT ?;
            """
            
            if has_named_article_anchor:
                rows = self._search_exact_anchors(cursor, anchors, limit)
            else:
                rows = []
                if tier1_query:
                    try:
                        cursor.execute(sql, (tier1_query, *scope_params, limit * 3))
                        rows = cursor.fetchall()
                    except sqlite3.Error:
                        rows = []

                # Keep focused candidates first when supplementing with broad
                # matches. Replacing them with the broad result set discarded
                # the only exact concept hits whenever they numbered < limit.
                if len(rows) < limit:
                    cursor.execute(sql, (fts_query, *scope_params, limit * 4))
                    broad_rows = cursor.fetchall()
                    seen_ids = {str(row[0]) for row in rows}
                    rows.extend(row for row in broad_rows if str(row[0]) not in seen_ids)

                # Domain-agnostic 2nd-stage alignment: re-rank candidate articles by IDF-weighted
                # query term coverage in article titles to counter BM25 field length normalization
                # bias on compound entities without hardcoded rules
                if not has_named_article_anchor and rows:
                    q_words = [
                        w.casefold()
                        for w in re.findall(r"[\wÀ-ỹĐđ]+", clean_query, flags=re.UNICODE)
                        if w.casefold() not in LEGAL_STOP_WORDS and len(w) > 1
                    ]
                    if q_words:
                        try:
                            placeholders = ",".join("?" for _ in q_words)
                            vocab_rows = cursor.execute(
                                f"SELECT term, doc FROM temp.universal_legal_vocab WHERE term IN ({placeholders})",
                                q_words,
                            ).fetchall()
                            doc_count = max(1, int(cursor.execute("SELECT COUNT(*) FROM legal_articles").fetchone()[0]))
                            freq_map = {str(t).casefold(): int(d) for t, d in vocab_rows}
                            idfs = {
                                w: math.log((doc_count + 1) / (freq_map.get(w, 0) + 1))
                                for w in q_words
                            }
                            total_idf = sum(idfs.values()) or 1.0

                            def _rank_key(row: tuple[Any, ...]) -> float:
                                art_title = str(row[3] or "").casefold()
                                matched_idf = sum(idfs[w] for w in q_words if w in art_title)
                                weighted_cov = matched_idf / total_idf
                                raw_rank = float(row[8])
                                return raw_rank * (1.0 + 0.3 * weighted_cov)

                            rows.sort(key=_rank_key)
                        except sqlite3.Error:
                            pass

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

                source_anchors = explicit_anchors(f"{src_note or ''} {art_title or ''}")
                source_article = next(
                    (anchor.article for anchor in source_anchors if anchor.article),
                    "",
                )
                display_article_title = art_title if art_title else "Quy định pháp luật"
                if source_article:
                    heading = re.match(r"^Điều\s+[\w.]+\.\s*(.+)$", str(art_title or ""), re.IGNORECASE)
                    if heading:
                        display_article_title = f"{source_article}. {heading.group(1)}"
                    else:
                        display_article_title = source_article

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
                if display_article_title:
                    header_parts.append(f"[ĐIỀU KHOẢN]: {display_article_title}")

                formatted_content = " | ".join(header_parts) + "\n\n" + content

                # Keep only a document URL supplied by the corpus.
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
                if not instrument_number and rec_id:
                    id_match = re.search(
                        r"(?<![\w/])\d{1,5}/\d{4}/[A-ZĐ0-9][A-ZĐ0-9-]*(?![\w/])",
                        str(rec_id),
                        flags=re.IGNORECASE,
                    )
                    if id_match:
                        instrument_number = id_match.group(0)
                if source_label.casefold().startswith("căn cứ "):
                    source_label = source_label[7:].strip()

                results.append({
                    "document_id": rec_id,
                    "page_content": formatted_content,
                    "metadata": {
                        "Dieu": display_article_title,
                        "source_article": source_article,
                        "codified_anchor": art_title if art_title else "",
                        "source": source_label[:120],
                        "source_title": source_label[:500],
                        "Source_Title": source_label[:500],
                        "document_title": source_label[:500],
                        "Document_Number": instrument_number,
                        "instrument_number": instrument_number,
                        "legal_anchor": display_article_title,
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
                    # This is a raw BM25 rank (lower is better), not a
                    # normalized relevance score. Keep it separate so the
                    # verifier does not mistake a large magnitude for 0-1.
                    "bm25_rank": float(rank),
                })

                if len(results) >= limit:
                    break

            return results
        except (sqlite3.Error, OSError) as e:
            logger.debug("UniversalLegalRetriever search error: %s", e)
            return []


# Global singleton
universal_retriever = UniversalLegalRetriever()
