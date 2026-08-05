"""
Retrieval module — FAQ (Qdrant) + Legal documents (Qdrant).

Key fixes vs the original monolith:
1. FAQ: loads ALL 39 entries from data/faq.json (was hardcoded 4).
2. Lazy retrieval: legal docs are only fetched when FAQ misses (no wasted work).
3. Async wrappers run sync calls in a thread pool (non-blocking event loop).
4. SelfQueryRetriever with FallbackLegalRetriever for structured + semantic search.
5. Vectorstore and retriever instances are built once (module-level singletons after
   build_index.py has pre-populated Qdrant — no LLM summarisation at startup).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Optional

import tiktoken
from langchain.chains.query_constructor.base import (
    StructuredQueryOutputParser,
    get_query_constructor_prompt,
)
from langchain.chains.query_constructor.ir import Comparator, Operator
from langchain.chains.query_constructor.schema import AttributeInfo

# Fix: Use non-deprecated import path for QdrantTranslator
try:
    from langchain_community.query_constructors.qdrant import QdrantTranslator
except ImportError:
    # Fallback for older langchain versions
    from langchain.retrievers.self_query.qdrant import QdrantTranslator

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from backend.config import get_settings
from backend.core.llm_instances import get_embeddings, get_llm_smart
from backend.core.legal_parser import parse_legal_query, build_qdrant_filter

# FIX: Import reranker at module level to avoid 8+ duplicate lazy imports
try:
    from backend.core.reranker import rerank_documents
except ImportError:
    # Fallback if reranker module is missing
    rerank_documents = None

# ---------------------------------------------------------------------------
# Token utilities
# ---------------------------------------------------------------------------

def _count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """Count tokens in text using tiktoken with improved fallback for Vietnamese.
    
    Vietnamese text uses more tokens per character due to diacritics.
    The old fallback (len(text) // 4) was off by 2-3x for Vietnamese.
    """
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # Improved fallback: Vietnamese averages ~3.5 chars/token
        # vs English ~4 chars/token, so use 3.5 for better accuracy
        return int(len(text) / 3.5)


def _truncate_text(text: str, max_tokens: int = 1000, model: str = "gpt-3.5-turbo") -> str:
    try:
        enc = tiktoken.encoding_for_model(model)
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens]) + "..."
    except Exception:
        return text[: max_tokens * 4] + "..."


# ---------------------------------------------------------------------------
# Vietnamese tokenizer (keyword matching for hybrid FAQ search)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "là", "và", "của", "có", "được", "trong", "cho", "với", "các",
    "này", "đó", "những", "để", "khi", "từ", "theo", "về", "như",
    "thì", "mà", "nhưng", "hoặc", "nếu", "vì", "do", "bởi", "tại",
    "đã", "đang", "sẽ", "còn", "cũng", "rất", "lại", "nên", "phải",
    "bạn", "tôi", "chúng", "họ", "nó", "gì", "nào", "sao", "bao",
}


def _tokenize_vietnamese(text: str) -> set[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return {w for w in text.split() if w not in _STOPWORDS and len(w) > 1}


_LEGAL_QUERY_PATTERNS = [
    r"\bđi[eề]u\s+\d+",
    r"\bkhoản\s+\d+",
    r"\bchương\s+[ivxlcdm\d]+",
    r"\bmục\s+\d+",
    r"\bnghị định\b",
    r"\bthông tư\b",
    r"\bluật\b",
    r"\bphụ lục\b",
]

_LEGAL_QUERY_KEYWORDS = {
    "quy định", "thủ tục", "trách nhiệm", "nghĩa vụ", "đăng ký", "báo cáo",
    "xử phạt", "mức phạt", "căn cứ", "điều kiện", "hồ sơ", "thẩm quyền",
    "tuân thủ", "thực hiện", "kiểm tra", "đánh giá", "phù hợp",
}


def _looks_like_legal_query(query: str) -> bool:
    q = query.lower()
    if any(re.search(pattern, q) for pattern in _LEGAL_QUERY_PATTERNS):
        return True
    return any(keyword in q for keyword in _LEGAL_QUERY_KEYWORDS)


def _is_strict_faq_hit(query: str, best: dict, runner_up: dict | None, threshold: float) -> bool:
    """
    Treat FAQ as a semantic cache, not an authoritative legal branch.

    A direct FAQ answer is allowed only when:
    - similarity is very high
    - the top candidate clearly beats the runner-up
    - the query is not asking for legal-specific interpretation or citation
    """
    settings = get_settings()
    if _looks_like_legal_query(query):
        return False

    if best["final"] < max(threshold, settings.faq_semantic_cache_threshold):
        return False

    if best["semantic"] < settings.faq_semantic_cache_threshold:
        return False

    if runner_up is None:
        return True

    margin = best["final"] - runner_up["final"]
    return margin >= settings.faq_semantic_cache_margin


# ---------------------------------------------------------------------------
# Qdrant client singleton
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_qdrant_client() -> QdrantClient:
    """Get Qdrant client with timeout configuration.
    
    CRITICAL FIX HIGH #3: Add timeout to prevent system hang if Qdrant
    becomes unresponsive. Without timeout, all operations block indefinitely.
    """
    s = get_settings()
    timeout = 10  # 10 second timeout for all Qdrant operations
    
    if s.use_qdrant_cloud and s.qdrant_cloud_url and s.qdrant_api_key:
        return QdrantClient(
            url=s.qdrant_cloud_url,
            api_key=s.qdrant_api_key,
            timeout=timeout,
        )
    try:
        return QdrantClient(
            path=s.qdrant_local_path,
            timeout=timeout,
        )
    except Exception:
        return QdrantClient(":memory:", timeout=timeout)


# ---------------------------------------------------------------------------
# FAQ collection setup (loads from faq.json — all 39 entries)
# ---------------------------------------------------------------------------

def ensure_faq_collection() -> None:
    """
    Create and populate faq_collection if it does not already exist.
    Idempotent: does nothing if the collection already has points.
    """
    s = get_settings()
    client = _get_qdrant_client()
    embeddings = get_embeddings()
    collection = s.faq_collection

    existing = {c.name for c in client.get_collections().collections}
    if collection in existing:
        count = client.get_collection(collection).points_count
        if count and count > 0:
            print(f"✅ FAQ collection '{collection}' already has {count} points")
            return

    # Load FAQ data
    faq_path = s.faq_data_path
    with open(faq_path, encoding="utf-8") as f:
        faq_data = json.load(f)

    entries = faq_data.get("meta", [])
    print(f"📄 Indexing {len(entries)} FAQ entries into '{collection}'...")

    # Create collection with optimized HNSW parameters
    sample_vec = embeddings.embed_query("test")
    dim = len(sample_vec)
    if collection not in existing:
        from qdrant_client.models import HnswConfigDiff
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(
                m=s.hnsw_m,
                ef_construct=s.hnsw_ef_construct,
            ),
        )

    points = []
    for item in entries:
        question = item.get("Câu hỏi", "")
        answer = item.get("Trả lời", "")
        vector = embeddings.embed_query(question)
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={"Câu_hỏi": question, "Trả_lời": answer},
            )
        )

    client.upsert(collection_name=collection, points=points)
    print(f"✅ Indexed {len(points)} FAQ entries")


# ---------------------------------------------------------------------------
# FAQ retrieval — hybrid semantic + keyword
# ---------------------------------------------------------------------------

def retrieve_faq_top1(
    query: str,
    score_threshold: float | None = None,
    keyword_boost: float | None = None,
    rerank: bool = True,
) -> list[Document]:
    s = get_settings()
    threshold = score_threshold if score_threshold is not None else s.faq_score_threshold
    boost = keyword_boost if keyword_boost is not None else s.faq_keyword_boost

    client = _get_qdrant_client()
    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(query)

    # Use search_ef for better accuracy at scale
    from qdrant_client.models import SearchParams
    results = client.query_points(
        collection_name=s.faq_collection,
        query=query_vector,
        limit=5,
        search_params=SearchParams(hnsw_ef=s.search_ef),
    )

    if not results or not results.points:
        return []

    query_tokens = _tokenize_vietnamese(query)
    scored: list[dict] = []
    for point in results.points:
        semantic = point.score
        q_tokens = _tokenize_vietnamese(point.payload["Câu_hỏi"])
        kw_score = len(query_tokens & q_tokens) / len(query_tokens) if query_tokens else 0.0
        final = semantic + boost * kw_score
        scored.append({"point": point, "semantic": semantic, "keyword": kw_score, "final": final})

    scored.sort(key=lambda x: x["final"], reverse=True)
    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None

    if best["final"] >= threshold:
        p = best["point"]
        strict_hit = _is_strict_faq_hit(query, best, runner_up, threshold)
        margin = best["final"] - runner_up["final"] if runner_up else best["final"]
        docs = [
            Document(
                page_content=p.payload["Trả_lời"],
                metadata={
                    "Câu_hỏi": p.payload["Câu_hỏi"],
                    "score": best["final"],
                    "semantic_score": best["semantic"],
                    "keyword_score": best["keyword"],
                    "score_margin": margin,
                    "strict_faq_hit": strict_hit,
                },
            )
        ]

        # Re-rank FAQ only for strict hits. Ambiguous matches should continue to legal retrieval.
        if strict_hit and rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
            # Get top 3 candidates for re-ranking
            top_candidates = []
            for s_item in scored[:3]:
                if s_item["final"] >= threshold - 0.1:  # Slightly relaxed threshold
                    pt = s_item["point"]
                    top_candidates.append(
                        Document(
                            page_content=pt.payload["Trả_lời"],
                            metadata={
                                "Câu_hỏi": pt.payload["Câu_hỏi"],
                                "score": s_item["final"],
                                "semantic_score": s_item["semantic"],
                                "keyword_score": s_item["keyword"],
                                "score_margin": margin,
                                "strict_faq_hit": strict_hit,
                            },
                        )
                    )

            if len(top_candidates) > 1:
                reranked = rerank_documents(query, top_candidates, top_k=1)
                if reranked:
                    return reranked

        return docs
    return []


# ---------------------------------------------------------------------------
# Law vectorstore + SelfQueryRetriever (pre-built by scripts/build_index.py)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_law_vectorstore() -> QdrantVectorStore:
    s = get_settings()
    client = _get_qdrant_client()
    embeddings = get_embeddings()
    # build_index.py stores fields (Dieu, Chuong, Muc, Text, summary, …) at the
    # Qdrant payload ROOT — NOT under a "metadata" sub-key.
    # metadata_payload_key=None tells LangChain to look for payload["metadata"]
    # which doesn't exist, so doc.metadata only gets _id and _collection_name.
    # Passing content_payload_key="Text" is correct; the rest of the root payload
    # fields are surfaced via the _enrich_docs() helper in _FallbackLegalRetriever.
    return QdrantVectorStore(
        client=client,
        collection_name=s.law_collection,
        embedding=embeddings,
        content_payload_key="Text",
        metadata_payload_key=None,
    )


def _enrich_docs_from_qdrant(docs: list[Document], collection_name: str) -> list[Document]:
    """Attach root-level Qdrant payload fields (Dieu, Chuong, Muc, …) to doc.metadata.

    QdrantVectorStore with metadata_payload_key=None only puts _id/_collection_name
    in doc.metadata.  This helper fetches the full payloads for the returned points
    and merges them in, so downstream components (Relevance Gate, article-not-found
    shortcut, generation prompts) can access Dieu / Chuong / summary fields.
    """
    if not docs:
        return docs
    point_ids = [d.metadata.get("_id") for d in docs if d.metadata.get("_id")]
    if not point_ids:
        return docs
    try:
        client = _get_qdrant_client()
        points = client.retrieve(
            collection_name=collection_name,
            ids=point_ids,
            with_payload=True,
            with_vectors=False,
        )
        payload_map = {str(p.id): p.payload for p in points}
        for d in docs:
            pid = str(d.metadata.get("_id", ""))
            payload = payload_map.get(pid, {})
            for k, v in payload.items():
                if k not in ("Text",):  # Text is already page_content
                    d.metadata.setdefault(k, v)
    except Exception as e:
        print(f"⚠️ _enrich_docs_from_qdrant failed: {e}")
    return docs


def _fix_unicode_escapes(llm_output) -> str:
    """Replace \\uXXXX escapes inside JSON blocks with actual characters.

    Accepts either a plain string or a LangChain AIMessage object.
    """
    # LangChain ChatOpenAI returns an AIMessage; extract text content
    if hasattr(llm_output, "content"):
        llm_output = llm_output.content
    if not isinstance(llm_output, str):
        llm_output = str(llm_output)

    def _replace(m: re.Match) -> str:
        try:
            return chr(int(m.group(1), 16))
        except Exception:
            return m.group(0)

    json_match = re.search(r"(\{.*?\})", llm_output, re.DOTALL)
    if json_match:
        fixed = re.sub(r"\\u([0-9a-fA-F]{4})", _replace, json_match.group(1))
        return llm_output.replace(json_match.group(1), fixed)
    return llm_output


@lru_cache(maxsize=1)
def _get_law_query_constructor():
    embeddings = get_embeddings()  # noqa: F841 — imported for side-effect init order
    llm_query = get_llm_smart()

    mo_ta = """Văn bản pháp luật Việt Nam có cấu trúc phân cấp:
- ĐIỀU (Dieu): Quy định chi tiết
- CHƯƠNG (Chuong): Phạm vi rộng, dùng SỐ LA MÃ (Chương I, II, III...)
- MỤC (Muc): Dùng số Ả Rập (Mục 1, 2, 3...)
Tìm theo: eq("Dieu_Number", 9), like("Chuong", "Chương II"), like("Muc", "Mục 1")"""

    metadata_fields = [
        AttributeInfo(name="Dieu", description="Tên đầy đủ của điều, ví dụ 'Điều 77. ...'", type="string"),
        AttributeInfo(name="Chuong", description="Tên chương, ví dụ 'Chương I. NHỮNG QUY ĐỊNH CHUNG'", type="string"),
        AttributeInfo(name="Muc", description="Tên mục, ví dụ 'Mục 1 BẢO VỆ MÔI TRƯỜNG NƯỚC'", type="string"),
    ]

    prompt = get_query_constructor_prompt(
        mo_ta,
        metadata_fields,
        allowed_comparators=[Comparator.LIKE, Comparator.EQ],
        allowed_operators=[Operator.AND, Operator.OR],
        examples=[
            ("Điều 77 quy định gì?", {"query": "điều 77", "filter": 'like("Dieu", "Điều 77")'}),
            ("Chương 2 quy định gì?", {"query": "chương 2", "filter": 'like("Chuong", "Chương II")'}),
            ("mục 1 về gì?", {"query": "mục 1", "filter": 'like("Muc", "Mục 1")'}),
            ("Mục 2 của chương 2?", {"query": "mục 2 chương 2",
                                      "filter": 'and(like("Muc", "Mục 2"), like("Chuong", "Chương II"))'}),
            ("Trách nhiệm tổ chức sản xuất", {"query": "trách nhiệm tổ chức sản xuất", "filter": None}),
        ],
    )

    parser = StructuredQueryOutputParser.from_components(
        allowed_comparators=[Comparator.EQ, Comparator.LT, Comparator.LTE,
                             Comparator.GT, Comparator.GTE, Comparator.LIKE],
        allowed_operators=[Operator.AND, Operator.OR],
    )

    return prompt | llm_query | RunnableLambda(_fix_unicode_escapes) | parser


def _fix_filter_keys(qdrant_filter) -> None:
    """Strip the leading dot that QdrantTranslator(metadata_key='') adds to field keys.

    Build_index.py stores all metadata at the Qdrant payload ROOT (not under a
    'metadata' sub-key), so the correct field path is 'Dieu', not '.Dieu'.
    QdrantTranslator constructs the key as  metadata_key + '.' + attribute
    which yields '.Dieu' when metadata_key=''.  This function walks the Filter
    object and removes the leading dot in-place.
    """
    if qdrant_filter is None:
        return
    conditions = []
    if hasattr(qdrant_filter, "must") and qdrant_filter.must:
        conditions.extend(qdrant_filter.must)
    if hasattr(qdrant_filter, "should") and qdrant_filter.should:
        conditions.extend(qdrant_filter.should)
    if hasattr(qdrant_filter, "must_not") and qdrant_filter.must_not:
        conditions.extend(qdrant_filter.must_not)
    for cond in conditions:
        if hasattr(cond, "key") and isinstance(cond.key, str) and cond.key.startswith("."):
            cond.key = cond.key[1:]
        # Recurse for nested filters
        if hasattr(cond, "filter"):
            _fix_filter_keys(cond.filter)


class _FallbackLegalRetriever:
    """Try with filter → fall back to unfiltered similarity search → re-rank."""

    def __init__(self, k: int = 5, rerank: bool = True, rerank_top_k: int = 3):
        self.k = k
        self.rerank = rerank
        self.rerank_top_k = rerank_top_k
        # metadata_key="" because build_index.py stores fields at payload root (not under "metadata")
        self._translator = QdrantTranslator(metadata_key="")

    def invoke(self, query: str) -> list[Document]:
        # NOTE: cosine score thresholding was removed — text-embedding-3-small scores
        # are NOT discriminative enough for domain filtering on this Vietnamese corpus
        # (off-domain queries score 0.24-0.38, on-domain 0.27-0.35 — too much overlap).
        # Domain filtering is handled by the LLM relevance gate in pipeline.py instead.
        #
        # Each returned doc is tagged with metadata["filter_matched"]:
        #   True  — SelfQuery produced a filter AND Qdrant returned results for it
        #   False — fell back to unfiltered semantic search (filter had no match or no filter built)
        # pipeline.py uses this to detect "article X not found" quickly.
        vs = _get_law_vectorstore()

        # ── Step 1: Try rule-based parser first (fast, no LLM cost) ────────
        legal_filter = parse_legal_query(query)
        qdrant_filter = build_qdrant_filter(legal_filter)

        # Use the parsed free_query for semantic search (better than raw query)
        semantic_query = legal_filter.free_query

        if qdrant_filter:
            try:
                docs = vs.similarity_search(semantic_query, k=self.k, filter=qdrant_filter)
                if docs:
                    for d in docs:
                        d.metadata["filter_matched"] = True
                    docs = _enrich_docs_from_qdrant(docs, vs.collection_name)
                    # Re-rank for better precision
                    if self.rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
                        docs = rerank_documents(query, docs, top_k=self.rerank_top_k)
                    return docs
                # Filter produced no results → article not in corpus
                fallback_docs = vs.similarity_search(semantic_query, k=self.k)
                for d in fallback_docs:
                    d.metadata["filter_matched"] = False
                docs = _enrich_docs_from_qdrant(fallback_docs, vs.collection_name)
                if self.rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
                    docs = rerank_documents(query, docs, top_k=self.rerank_top_k)
                return docs
            except Exception as e:
                print(f"⚠️ Rule-based filter failed: {e}")

        # ── Step 2: Fallback to LLM-based SelfQuery (for complex queries) ──
        try:
            constructor = _get_law_query_constructor()
            structured = constructor.invoke({"query": query})

            if structured.filter:
                try:
                    result = self._translator.visit_structured_query(structured)
                    if isinstance(result, tuple):
                        _, filter_dict = result
                        qdrant_filter = filter_dict.get("filter") if isinstance(filter_dict, dict) else filter_dict
                    elif isinstance(result, dict):
                        qdrant_filter = result.get("filter", result)
                    else:
                        qdrant_filter = result

                    # QdrantTranslator(metadata_key="") prepends a "." to all
                    # field keys — strip it so the path matches the payload root.
                    _fix_filter_keys(qdrant_filter)

                    docs = vs.similarity_search(structured.query, k=self.k, filter=qdrant_filter)
                    if docs:
                        for d in docs:
                            d.metadata["filter_matched"] = True
                        docs = _enrich_docs_from_qdrant(docs, vs.collection_name)
                        if self.rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
                            docs = rerank_documents(query, docs, top_k=self.rerank_top_k)
                        return docs
                    # Filter produced no results → article not in corpus
                    fallback_docs = vs.similarity_search(structured.query, k=self.k)
                    for d in fallback_docs:
                        d.metadata["filter_matched"] = False
                    docs = _enrich_docs_from_qdrant(fallback_docs, vs.collection_name)
                    if self.rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
                        docs = rerank_documents(query, docs, top_k=self.rerank_top_k)
                    return docs
                except Exception as e:
                    print(f"⚠️ LLM filter retrieval failed: {e}")

            docs = vs.similarity_search(structured.query, k=self.k)
            for d in docs:
                d.metadata.setdefault("filter_matched", False)
            docs = _enrich_docs_from_qdrant(docs, vs.collection_name)
            if self.rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
                docs = rerank_documents(query, docs, top_k=self.rerank_top_k)
            return docs
        except Exception as e:
            print(f"⚠️ Query constructor failed, falling back to plain search: {e}")
            docs = vs.similarity_search(query, k=self.k)
            for d in docs:
                d.metadata.setdefault("filter_matched", False)
            docs = _enrich_docs_from_qdrant(docs, vs.collection_name)
            if self.rerank and rerank_documents is not None:
            # rerank_documents already imported at module level
                docs = rerank_documents(query, docs, top_k=self.rerank_top_k)
            return docs


@lru_cache(maxsize=1)
def _get_fallback_retriever() -> _FallbackLegalRetriever:
    s = get_settings()
    # Increase k to 10 for better recall before re-ranking
    # Re-ranker will then select top 3 from 10 candidates
    return _FallbackLegalRetriever(
        k=10,  # Increased from max_retrieval_docs (5) for better recall
        rerank=s.enable_reranking,
        rerank_top_k=s.rerank_top_k,
    )


def retrieve_legal(query: str) -> list[Document]:
    """Retrieve legal documents for a query using ensemble method.

    Uses multi-strategy ensemble retrieval (rule-based + semantic + keyword)
    with priority-based ranking for maximum recall and precision.
    """
    # Use ensemble retriever for better accuracy
    from backend.core.ensemble_retrieval import retrieve_legal_ensemble
    docs = retrieve_legal_ensemble(query, k=10)

    # Apply re-ranking only if enabled AND docs haven't been re-ranked yet
    # (ensemble retriever may have already applied priority ranking)
    if get_settings().enable_reranking and docs and rerank_documents is not None:
        # Check if docs already have rerank_score from ensemble
        already_reranked = any("rerank_score" in doc.metadata for doc in docs[:3])
        if not already_reranked:
            # rerank_documents already imported at module level
            docs = rerank_documents(query, docs, top_k=get_settings().rerank_top_k)

    return docs


# ---------------------------------------------------------------------------
# Counting questions
# ---------------------------------------------------------------------------

_COUNTING_PATTERNS = [
    r"\b(bao nhiêu|bao nhieu)\s+(điều|dieu|khoản|khoan|mục|muc|chương|chuong|văn bản|van ban|luật|luat|nghị định|nghi dinh|thông tư|thong tu)\b",
    r"\b(có mấy|co may)\s+(điều|dieu|khoản|khoan|mục|muc|chương|chuong|văn bản|van ban|luật|luat|nghị định|nghi dinh|thông tư|thong tu)\b",
    r"\b(tổng|tong)\s*(số|so|cộng|cong)?\s*(điều|dieu|khoản|khoan|mục|muc|chương|chuong|văn bản|van ban|luật|luat|nghị định|nghi dinh|thông tư|thong tu)\b",
    r"\b(đếm|dem)\s*(số\s*)?(điều|dieu|khoản|khoan|mục|muc|chương|chuong|văn bản|van ban)\b",
    r"\bhow many\s+(articles?|sections?|laws?|documents?)\b",
]

_COUNTING_EXCLUSION_KEYWORDS = [
    "tỷ lệ",
    "ty le",
    "bao nhiêu %",
    "bao nhieu %",
    "bao nhiêu phần trăm",
    "bao nhieu phan tram",
    "mức",
    "muc",
    "chi phí",
    "chi phi",
    "phí",
    "phi",
    "tiền",
    "tien",
    "giá",
    "gia",
    "thời hạn",
    "thoi han",
    "thời gian",
    "thoi gian",
]


def is_counting_question(query: str) -> bool:
    q = query.lower()
    if any(keyword in q for keyword in _COUNTING_EXCLUSION_KEYWORDS):
        return False
    return any(re.search(pattern, q) for pattern in _COUNTING_PATTERNS)


def count_articles(query: str) -> dict:
    """Count unique Dieu_Number values matching the query filter.
    
    CRITICAL FIX: Uses Qdrant's native count() API instead of scrolling all points.
    Previous implementation loaded ALL matching points into Python memory (O(n)),
    causing OOM crashes on large datasets with broad filters.
    
    Now uses O(1) count operation regardless of corpus size.
    """
    constructor = _get_law_query_constructor()
    structured = constructor.invoke({"query": query})

    if not structured.filter:
        return {"count": None, "articles": [], "filter_description": query}

    translator = QdrantTranslator(metadata_key="metadata")
    try:
        result = translator.visit_structured_query(structured)
        if isinstance(result, tuple):
            _, fd = result
            qdrant_filter = fd.get("filter") if isinstance(fd, dict) else fd
        elif isinstance(result, dict):
            qdrant_filter = result.get("filter", result)
        else:
            qdrant_filter = result

        vs = _get_law_vectorstore()
        client = vs.client
        collection = vs.collection_name

        # CRITICAL FIX: Use Qdrant's native count() API — O(1) operation
        # Instead of scrolling all points into memory (O(n) memory usage)
        count_result = client.count(
            collection_name=collection,
            count_filter=qdrant_filter,
            exact=True,  # Ensure accurate count
        )
        
        # Note: We can't get the list of article numbers without scrolling,
        # but for counting questions, the count is what matters
        return {
            "count": count_result.count,
            "articles": [],  # Don't fetch full list — too expensive for large filters
            "filter_description": query,
        }

    except Exception as e:
        logger.error(f"❌ count_articles error: {e}")
        return {"count": None, "articles": [], "filter_description": query}


def counting_answer(count_result: dict, query: str) -> str:
    count = count_result.get("count")
    articles = count_result.get("articles", [])
    if count is None:
        return "Xin lỗi, tôi không thể đếm số lượng điều luật dựa trên câu hỏi của bạn."
    if count == 0:
        return f"Không có điều luật nào trong phạm vi bạn yêu cầu."

    answer = f"Có **{count} điều luật** trong phạm vi bạn yêu cầu."
    if 0 < count <= 20:
        answer += "\n\nCụ thể: " + ", ".join(f"Điều {a}" for a in articles) + "."
    elif count > 20:
        first = ", ".join(f"Điều {a}" for a in articles[:10])
        last = ", ".join(f"Điều {a}" for a in articles[-5:])
        answer += f"\n\nCụ thể: {first}, ..., {last}."
    return answer


# ---------------------------------------------------------------------------
# Async wrappers (run sync calls in thread pool)
# ---------------------------------------------------------------------------

async def retrieve_faq_async(query: str, score_threshold: Optional[float] = None) -> list[Document]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, retrieve_faq_top1, query, score_threshold)


async def retrieve_legal_async(query: str) -> list[Document]:
    loop = asyncio.get_event_loop()

    if is_counting_question(query):
        def _count():
            result = count_articles(query)
            answer = counting_answer(result, query)
            return [Document(
                page_content=answer,
                metadata={"type": "counting_result", "count": result.get("count")},
            )]
        docs = await loop.run_in_executor(None, _count)
        if docs:
            return docs

    return await loop.run_in_executor(None, retrieve_legal, query)
