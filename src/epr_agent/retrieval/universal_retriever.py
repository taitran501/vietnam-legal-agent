"""
Universal Vietnamese Legal Retriever.
Provides high-precision retrieval over 84,900+ Codified Legal Articles (Pháp điển)
and 318 National Codes & Laws across all Vietnamese legal domains.
"""

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

DEFAULT_DB_PATH = os.path.join(os.getcwd(), "data", "corpus", "universal_legal", "universal_legal.db")

# Conversational stop words in Vietnamese QA
LEGAL_STOP_WORDS = {
    "và", "của", "các", "có", "được", "trong", "cho", "về", "theo", "tại", "khi", "để", "là", 
    "những", "thì", "tôi", "muốn", "biết", "như", "thế", "nào", "gì", "bao", "nhiêu", "phải", 
    "không", "hướng", "dẫn", "với", "hãy", "em", "mình", "anh", "chị", "giúp", "bạn", "ạ", "nhỉ",
    "xin", "hỏi", "quy", "định", "như_thế_nào", "ra_sao", "bao_nhiêu", "cho_tôi", "làm_sao"
}

# Domain keyword boosts for Vietnamese law
KNOWN_LAW_NAMES = [
    ("đất đai", "Luật Đất đai"),
    ("sổ đỏ", "Luật Đất đai"),
    ("lao động", "Bộ luật Lao động"),
    ("thử việc", "Bộ luật Lao động"),
    ("hợp đồng lao động", "Bộ luật Lao động"),
    ("thương mại", "Luật Thương mại"),
    ("phạt vi phạm hợp đồng", "Luật Thương mại"),
    ("doanh nghiệp", "Luật Doanh nghiệp"),
    ("công ty tnhh", "Luật Doanh nghiệp"),
    ("cổ phần", "Luật Doanh nghiệp"),
    ("hình sự", "Bộ luật Hình sự"),
    ("buôn lậu", "Bộ luật Hình sự"),
    ("bảo vệ môi trường", "Luật Bảo vệ môi trường"),
    ("tái chế", "Luật Bảo vệ môi trường"),
    ("nghị định 08", "Nghị định số 08/2022/NĐ-CP"),
]


class UniversalLegalRetriever:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._available = os.path.exists(self.db_path)

    @property
    def is_available(self) -> bool:
        return self._available and os.path.exists(self.db_path)

    def _extract_search_terms(self, query: str) -> List[str]:
        q_lower = query.lower()
        
        # 1. Check for specific law or topic signals
        injected_terms = []
        for kw, law_name in KNOWN_LAW_NAMES:
            if kw in q_lower:
                injected_terms.append(law_name)
                
        # 2. Extract words
        raw_words = re.findall(r"\b[\w\.]+\b", query)
        content_words = [w for w in raw_words if w.lower() not in LEGAL_STOP_WORDS and len(w) > 1]
        
        # Merge unique terms
        all_terms = []
        for item in injected_terms + content_words:
            if item and item not in all_terms:
                all_terms.append(item)
                
        return all_terms[:12]

    def search(self, query: str, limit: int = 5, topic_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Executes a high-relevance BM25 search over 84,900+ Vietnamese legal articles.
        Returns a list of structured document dictionaries compatible with Agent pipelines.
        """
        if not self.is_available:
            return []

        clean_query = query.strip()
        if not clean_query:
            return []

        terms = self._extract_search_terms(clean_query)
        if not terms:
            terms = re.findall(r"\b[\w\.]+\b", clean_query)[:4]

        # Build FTS5 OR search query with quotes for precision
        fts_query = " OR ".join(f'"{t}"' for t in terms)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Execute FTS match with rank ordering
            sql = """
            SELECT 
                a.id, a.topic, a.subject, a.article_title, a.chapter_title, 
                a.source_note, a.source_url, a.content_text, bm25(legal_articles_fts) AS rank
            FROM legal_articles_fts fts
            JOIN legal_articles a ON fts.id = a.id
            WHERE legal_articles_fts MATCH ?
            ORDER BY rank ASC
            LIMIT ?;
            """
            
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

                # Clean official URL
                final_url = src_url.strip() if src_url else "https://vbpl.vn"
                if not final_url.startswith("http"):
                    final_url = "https://vbpl.vn"

                # Extract friendly short source label
                source_label = src_note if src_note else (subject if subject else (topic if topic else "Cơ sở dữ liệu Pháp luật Quốc gia"))
                source_label = re.sub(r"^\s*\(|\)\s*$", "", source_label)

                results.append({
                    "document_id": rec_id,
                    "page_content": formatted_content,
                    "metadata": {
                        "Dieu": art_title if art_title else "Quy định pháp luật",
                        "source": source_label[:120],
                        "official_url": final_url,
                        "topic": topic,
                        "subject": subject,
                        "chapter": chap_title,
                        "law_ref": src_note
                    },
                    "score": abs(float(rank))
                })

                if len(results) >= limit:
                    break

            return results
        except Exception as e:
            print(f"Error in UniversalLegalRetriever: {e}")
            return []


# Global singleton
universal_retriever = UniversalLegalRetriever()
