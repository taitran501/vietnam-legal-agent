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


class LegalSearchResult(BaseModel):
    id: str
    topic: str = ""
    subject: str = ""
    article_title: str = ""
    chapter_title: str = ""
    source_note: str = ""
    source_url: str = ""
    content_text: str = ""
    score: float = 0.0


class UniversalLegalRetriever:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._available = os.path.exists(self.db_path)

    @property
    def is_available(self) -> bool:
        return self._available and os.path.exists(self.db_path)

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

        # Extract keywords and numbers (e.g., "Điều 44", "Luật Đất đai", "thử việc")
        # Tokenize query for FTS5
        tokens = re.findall(r"\b[\w\.]+\b", clean_query)
        stop_words = {"và", "của", "các", "có", "được", "trong", "cho", "về", "theo", "tại", "khi", "để", "là", "những", "thì", "tôi", "cho"}
        meaningful_tokens = [t for t in tokens if t.lower() not in stop_words and len(t) > 1]
        
        if not meaningful_tokens:
            meaningful_tokens = tokens[:3]

        fts_query = " OR ".join(f'"{t}"' for t in meaningful_tokens[:8])

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
            
            cursor.execute(sql, (fts_query, limit * 2))
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
