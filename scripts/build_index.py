"""
Offline index builder for the law collection.

Run ONCE before starting the backend:
    python -m scripts.build_index

What it does
------------
1. Load data/law.json (list of article dicts with Điều/Chương/Mục/Text keys)
2. Summarise each article with gpt-3.5-turbo (batch=5, bounded input)
3. Chunk each article with sliding window (overlap) for long-form legal recall
4. Embed chunk-level hybrid text with text-embedding-3-small
5. Upsert into Qdrant `law_collection` (create if absent)

The resulting collection is used at runtime by backend/core/retrieval.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap path so we can import backend modules
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env so OPENAI_API_KEY and other vars are available to all libraries
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.config import get_settings
from backend.core.llm_instances import get_embeddings, get_llm_fast

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUMMARY_BATCH_SIZE = 5  # articles summarised per LLM call
EMBED_BATCH_SIZE = max(1, int(os.getenv("EMBED_BATCH_SIZE", "32")))
VECTOR_DIM = 1536       # text-embedding-3-small

_SUMMARISE_PROMPT = """Tóm tắt quy định pháp luật Việt Nam sau đây thành 3-4 đoạn văn bằng tiếng Việt.
Bao gồm: yêu cầu pháp lý chính, đối tượng áp dụng, nghĩa vụ/quyền lợi quan trọng.

---
{text}
---
Tóm tắt:"""

# Embedding and chunking controls.
_EMBED_TEXT_MAX_CHARS = max(1000, int(os.getenv("EMBED_TEXT_MAX_CHARS", "7000")))
_SUMMARY_INPUT_MAX_CHARS = max(2000, int(os.getenv("SUMMARY_INPUT_MAX_CHARS", "12000")))
_CHUNK_SIZE_CHARS = max(500, int(os.getenv("CHUNK_SIZE_CHARS", "1800")))
_CHUNK_OVERLAP_CHARS = max(100, int(os.getenv("CHUNK_OVERLAP_CHARS", "300")))
_CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "sliding_window").strip().lower()
_SUMMARY_CACHE_VERSION = "legal-summary-v1"

ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\uFEFF]")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTIBLANK_RE = re.compile(r"\n{3,}")
PUNCT_FIX_RE = re.compile(r"([,;:])(?=\S)")
ENUM_FIX_RE = re.compile(r"(?<=\d)\.(?=[A-Za-zÀ-ỹà-ỹ])")


# ---------------------------------------------------------------------------
# Load law data
# ---------------------------------------------------------------------------

def load_articles() -> list[dict[str, Any]]:
    settings = get_settings()
    law_json_path = Path(os.getenv("LAW_JSON_PATH", str(settings.law_data_path))).resolve()
    logger.info("Loading %s…", law_json_path)
    with open(law_json_path, encoding="utf-8") as f:
        raw = json.load(f)

    # Support both list-of-dicts and {"meta": [...]} wrapper
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "meta" in raw:
        return raw["meta"]
    raise ValueError(f"Unexpected law.json format: {type(raw)}")


def _clean_heading(text: Any) -> str:
    if text is None:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = ZERO_WIDTH_RE.sub("", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = " ".join(part.strip() for part in t.split("\n") if part.strip())
    t = MULTISPACE_RE.sub(" ", t)
    return t.strip()


def _clean_legal_text(text: Any) -> str:
    if text is None:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = ZERO_WIDTH_RE.sub("", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\t", " ")

    # Join wrapped lines inside paragraphs; keep blank lines between paragraphs.
    lines = [ln.strip() for ln in t.split("\n")]
    paragraphs: list[str] = []
    cur: list[str] = []
    for ln in lines:
        if not ln:
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
            continue
        cur.append(ln)
    if cur:
        paragraphs.append(" ".join(cur))

    cleaned = []
    for p in paragraphs:
        s = MULTISPACE_RE.sub(" ", p.strip())
        s = PUNCT_FIX_RE.sub(r"\1 ", s)
        s = ENUM_FIX_RE.sub(". ", s)
        cleaned.append(s.strip())

    t = "\n\n".join(x for x in cleaned if x)
    t = MULTIBLANK_RE.sub("\n\n", t)
    return t.strip()


def _clean_structural_source(text: Any) -> str:
    """Normalize OCR noise while retaining line starts used by legal list markers."""
    if text is None:
        return ""
    source = unicodedata.normalize("NFKC", str(text))
    source = ZERO_WIDTH_RE.sub("", source)
    source = source.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    lines = [MULTISPACE_RE.sub(" ", line.strip()) for line in source.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def normalise_articles(articles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Normalize headings/text before summarization + embedding.
    Returns (cleaned_articles, stats).
    """
    cleaned_articles: list[dict[str, Any]] = []
    stats = {
        "records_in": len(articles),
        "records_out": 0,
        "changed_records": 0,
        "empty_text_records": 0,
    }

    for article in articles:
        if not isinstance(article, dict):
            continue

        src_dieu = article.get("Điều", article.get("Dieu", article.get("Điều_Number", "")))
        src_chuong = article.get("Chương", article.get("Chuong", article.get("Chương_Number", "")))
        src_muc = article.get("Mục", article.get("Muc", article.get("Mục_Number", "")))
        src_pages = article.get("Pages", "")
        src_text = article.get("Text", article.get("text", ""))

        dieu = _clean_heading(src_dieu)
        chuong = _clean_heading(src_chuong)
        muc = _clean_heading(src_muc)
        pages = _clean_heading(src_pages)
        text = _clean_legal_text(src_text)

        if not text:
            stats["empty_text_records"] += 1
            continue

        changed = any([
            str(src_dieu or "") != dieu,
            str(src_chuong or "") != chuong,
            str(src_muc or "") != muc,
            str(src_pages or "") != pages,
            str(src_text or "") != text,
        ])
        if changed:
            stats["changed_records"] += 1

        cleaned_articles.append({
            **article,
            "Điều": dieu,
            "Chương": chuong,
            "Mục": muc,
            "Pages": pages,
            "Text": text,
            "_Structural_Text": _clean_structural_source(src_text),
        })

    stats["records_out"] = len(cleaned_articles)
    return cleaned_articles, stats


def validate_index_contract(articles: list[dict[str, Any]]) -> None:
    """Validate minimal legal index schema before embedding/upsert.

    This keeps the build pipeline robust by failing early when the source
    data is missing critical legal fields used by retrieval and filtering.
    """
    if not articles:
        raise ValueError("law.json contains no records to index")

    bad_rows: list[str] = []
    for idx, article in enumerate(articles, start=1):
        if not isinstance(article, dict):
            bad_rows.append(f"row {idx}: not an object")
            continue

        dieu = article.get("Điều") or article.get("Dieu") or article.get("Điều_Number")
        chuong = article.get("Chương") or article.get("Chuong") or article.get("Chương_Number")
        muc = article.get("Mục") or article.get("Muc") or article.get("Mục_Number")
        text = article.get("Text") or article.get("text")

        if not (dieu or chuong or muc):
            bad_rows.append(f"row {idx}: missing legal heading (Dieu/Chuong/Muc)")
        if not str(text or "").strip():
            bad_rows.append(f"row {idx}: missing Text")

        if len(bad_rows) >= 20:
            break

    if bad_rows:
        sample = "\n  - " + "\n  - ".join(bad_rows[:10])
        raise ValueError(
            "Index contract validation failed. Fix source records before build." + sample
        )


# ---------------------------------------------------------------------------
# Summarise articles
# ---------------------------------------------------------------------------

def _summary_cache_path() -> Path:
    configured = os.getenv("SUMMARY_CACHE_PATH", "artifacts/index_summary_cache.json").strip()
    return (ROOT / configured).resolve() if not Path(configured).is_absolute() else Path(configured)


def _summary_cache_key(article: dict[str, Any]) -> str:
    prepared = _prepare_summary_input(article.get("Text", article.get("text", "")))
    payload = f"{_SUMMARY_CACHE_VERSION}\n{_SUMMARISE_PROMPT}\n{prepared}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_summary_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable summary cache %s: %s", path, exc)
        return {}
    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    if not isinstance(entries, dict):
        return {}
    return {str(key): str(value) for key, value in entries.items() if str(value).strip()}


def _save_summary_cache(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "version": _SUMMARY_CACHE_VERSION,
        "entries": entries,
    }
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _summary_seed_collection(articles: list[dict[str, Any]]) -> dict[str, str]:
    """Reuse article summaries from an existing collection for controlled reindexing."""
    collection = os.getenv("SUMMARY_SOURCE_COLLECTION", "").strip()
    if not collection:
        return {}

    from qdrant_client import QdrantClient

    settings = get_settings()
    if settings.use_qdrant_cloud:
        client = QdrantClient(url=settings.qdrant_cloud_url, api_key=settings.qdrant_api_key)
    elif settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url)
    else:
        client = QdrantClient(path=str(ROOT / "qdrant_db"))

    parent_to_summary: dict[str, str] = {}
    offset = None
    try:
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                parent_id = str(payload.get("Parent_Id") or "")
                summary = str(payload.get("summary") or "").strip()
                if parent_id and summary:
                    parent_to_summary.setdefault(parent_id, summary)
            if offset is None:
                break
    finally:
        client.close()

    seeded: dict[str, str] = {}
    for article in articles:
        summary = parent_to_summary.get(_parent_id(article))
        if summary:
            seeded[_summary_cache_key(article)] = summary
    logger.info(
        "Reused %d/%d article summaries from collection '%s'",
        len(seeded),
        len(articles),
        collection,
    )
    return seeded


def summarise_articles(articles: list[dict[str, Any]]) -> list[str]:
    """Return one cached or generated summary per article in source order."""
    cache_path = _summary_cache_path()
    cache = _load_summary_cache(cache_path)
    cache.update(_summary_seed_collection(articles))
    keys = [_summary_cache_key(article) for article in articles]
    missing_indices = [index for index, key in enumerate(keys) if key not in cache]

    if not missing_indices:
        logger.info("Summary cache hit for all %d articles", len(articles))
        _save_summary_cache(cache_path, cache)
        return [cache[key] for key in keys]

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import PromptTemplate

    llm = get_llm_fast()                  # gpt-3.5-turbo, cheap
    prompt = PromptTemplate.from_template(_SUMMARISE_PROMPT)
    chain = prompt | llm | StrOutputParser()

    total = len(missing_indices)
    logger.info("Generating %d missing summaries (%d cache hits)", total, len(articles) - total)
    for i in range(0, total, SUMMARY_BATCH_SIZE):
        batch_indices = missing_indices[i: i + SUMMARY_BATCH_SIZE]
        batch = [articles[index] for index in batch_indices]
        batch_texts = [_prepare_summary_input(a.get("Text", a.get("text", ""))) for a in batch]

        logger.info("Summarising articles %d–%d / %d", i + 1, i + len(batch), total)
        try:
            results = chain.batch([{"text": t} for t in batch_texts])
        except Exception as exc:  # noqa: BLE001 - preserve indexing with source-text fallback
            logger.warning("Batch summarisation failed (%s); using truncated legal text", exc)
            results = batch_texts

        for article_index, summary in zip(batch_indices, results):
            cache[keys[article_index]] = str(summary)
        _save_summary_cache(cache_path, cache)
        # Polite rate-limit backoff
        if i + SUMMARY_BATCH_SIZE < total:
            time.sleep(1)

    return [cache[key] for key in keys]


def _article_field(article: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string field from an article dict."""
    for key in keys:
        value = article.get(key)
        if value:
            return str(value)
    return ""


def _prepare_summary_input(text: Any) -> str:
    """Bound summary input size; preserve both head and tail for very long articles."""
    source = " ".join(str(text or "").split())
    if len(source) <= _SUMMARY_INPUT_MAX_CHARS:
        return source

    head = source[: _SUMMARY_INPUT_MAX_CHARS // 2]
    tail = source[-(_SUMMARY_INPUT_MAX_CHARS // 2):]
    return f"{head}\n...\n{tail}"


def _split_text_sliding_window(text: str, *, size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks, trying to break at paragraph/newline boundaries."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []

    if len(raw) <= size:
        return [" ".join(raw.split())]

    chunks: list[str] = []
    start = 0
    text_len = len(raw)

    while start < text_len:
        end = min(start + size, text_len)
        if end < text_len:
            para_break = raw.rfind("\n\n", start, end)
            line_break = raw.rfind("\n", start, end)
            sentence_break = raw.rfind(". ", start, end)
            candidate = max(para_break, line_break, sentence_break)
            if candidate > start + max(200, size // 3):
                end = candidate + 1

        chunk = " ".join(raw[start:end].split()).strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break
        start = max(0, end - overlap)

    return chunks


def _parent_id(article: dict[str, Any]) -> str:
    """Stable parent id for all chunks of the same legal article."""
    dieu = _article_field(article, "Điều", "Dieu", "Điều_Number")
    chuong = _article_field(article, "Chương", "Chuong", "Chương_Number")
    muc = _article_field(article, "Mục", "Muc", "Mục_Number")
    pages = _article_field(article, "Pages")
    text = _article_field(article, "Text", "text")
    fp = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] if text else ""
    seed = f"{dieu}|{chuong}|{muc}|{pages}|{fp}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def chunk_articles(
    articles: list[dict[str, Any]],
    summaries: list[str],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Expand articles using the configured candidate-safe chunking strategy."""
    if _CHUNKING_STRATEGY == "legal_structure_v1":
        from scripts.structural_chunking import structural_chunk_articles

        return structural_chunk_articles(articles, summaries, max_chars=_CHUNK_SIZE_CHARS)
    if _CHUNKING_STRATEGY != "sliding_window":
        raise ValueError("CHUNKING_STRATEGY must be 'sliding_window' or 'legal_structure_v1'")
    chunked_articles: list[dict[str, Any]] = []
    chunked_summaries: list[str] = []
    max_chunks_per_article = 0

    for article, summary in zip(articles, summaries):
        text = _article_field(article, "Text", "text")
        chunks = _split_text_sliding_window(
            text,
            size=_CHUNK_SIZE_CHARS,
            overlap=min(_CHUNK_OVERLAP_CHARS, _CHUNK_SIZE_CHARS // 2),
        ) or [text]
        parent = _parent_id(article)
        max_chunks_per_article = max(max_chunks_per_article, len(chunks))

        for idx, chunk_text in enumerate(chunks):
            chunked_articles.append(
                {
                    **article,
                    "Text": chunk_text,
                    "Parent_Id": parent,
                    "Chunk_Index": idx,
                    "Chunk_Count": len(chunks),
                    "Full_Text_Chars": len(text),
                }
            )
            chunked_summaries.append(summary)

    stats = {
        "source_articles": len(articles),
        "chunked_records": len(chunked_articles),
        "avg_chunks_per_article": round(
            (len(chunked_articles) / max(1, len(articles))), 2
        ),
        "max_chunks_per_article": max_chunks_per_article,
    }
    return chunked_articles, chunked_summaries, stats


def _build_embedding_text(article: dict[str, Any], summary: str) -> str:
    """
    Build a richer embedding string than summary-only indexing.

    Using only LLM summaries loses article-specific legal phrases such as
    procedural triggers, exact conditions, and compliance actions. The vector
    text keeps the summary, but also carries the article heading hierarchy and
    a leading excerpt of the original law text so cosine retrieval can anchor
    on exact legal wording.
    """
    dieu = _article_field(article, "Điều", "Dieu", "Điều_Number")
    chuong = _article_field(article, "Chương", "Chuong", "Chương_Number")
    muc = _article_field(article, "Mục", "Muc", "Mục_Number")
    text = _article_field(article, "Text", "text")
    text_excerpt = " ".join(text.split())[:_EMBED_TEXT_MAX_CHARS]
    chunk_idx = article.get("Chunk_Index")
    chunk_count = article.get("Chunk_Count")

    parts = []
    if dieu:
        parts.append(f"Điều: {dieu}")
    if chuong:
        parts.append(f"Chương: {chuong}")
    if muc:
        parts.append(f"Mục: {muc}")
    if chunk_idx is not None and chunk_count is not None:
        parts.append(f"Chunk: {int(chunk_idx) + 1}/{int(chunk_count)}")
    if summary:
        parts.append(f"Tóm tắt: {summary}")
    if text_excerpt:
        parts.append(f"Toàn văn trích đoạn: {text_excerpt}")
    return "\n".join(parts)


def _stable_point_id(
    *,
    settings,
    article: dict[str, Any],
    fallback_seq: int,
) -> str:
    """Build deterministic, collision-safe point id for Qdrant."""
    dieu = _article_field(article, "Điều", "Dieu", "Điều_Number")
    chuong = _article_field(article, "Chương", "Chuong", "Chương_Number")
    muc = _article_field(article, "Mục", "Muc", "Mục_Number")
    pages = _article_field(article, "Pages")
    text = _article_field(article, "Text", "text")
    parent_id = _article_field(article, "Parent_Id")
    chunk_index = _article_field(article, "Chunk_Index")

    text_fingerprint = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] if text else ""

    seed = "|".join(
        [
            str(settings.law_collection),
            str(settings.law_citation_label or ""),
            dieu,
            chuong,
            muc,
            pages,
            parent_id,
            chunk_index,
            text_fingerprint,
            str(fallback_seq),
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


# ---------------------------------------------------------------------------
# Qdrant upsert
# ---------------------------------------------------------------------------

def upsert_to_qdrant(articles: list[dict], summaries: list[str]) -> None:
    settings = get_settings()
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, HnswConfigDiff, PointStruct, VectorParams

    if settings.use_qdrant_cloud:
        client = QdrantClient(url=settings.qdrant_cloud_url, api_key=settings.qdrant_api_key)
        logger.info("Connected to Qdrant Cloud at %s", settings.qdrant_cloud_url)
    elif settings.qdrant_url:
        client = QdrantClient(url=settings.qdrant_url)
        logger.info("Connected to self-hosted Qdrant at %s", settings.qdrant_url)
    else:
        local_path = str(ROOT / "qdrant_db")
        client = QdrantClient(path=local_path)
        logger.info("Using local Qdrant at %s", local_path)

    collection = settings.law_collection

    # Create collection with optimized HNSW parameters for 1M+ scale
    existing = {c.name for c in client.get_collections().collections}
    recreate_collection = os.getenv("RECREATE_COLLECTION", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if collection in existing and recreate_collection:
        logger.info("Recreating explicitly selected collection %s", collection)
        client.delete_collection(collection_name=collection)
        existing.remove(collection)
    if collection not in existing:
        logger.info("Creating collection %s with HNSW M=%d, ef_construct=%d", 
                    collection, settings.hnsw_m, settings.hnsw_ef_construct)
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(
                m=settings.hnsw_m,
                ef_construct=settings.hnsw_ef_construct,
                full_scan_threshold=10000,  # Use HNSW for collections > 10K vectors
            ),
        )
    else:
        logger.info("Collection %s already exists — will upsert", collection)
        # Update HNSW config if collection exists
        try:
            client.update_collection(
                collection_name=collection,
                hnsw_config=HnswConfigDiff(
                    m=settings.hnsw_m,
                    ef_construct=settings.hnsw_ef_construct,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - local Qdrant may not support runtime HNSW updates
            logger.debug("HNSW config update skipped (collection may not support runtime updates): %s", exc)

    # Ensure payload indexes for filtered queries (Dieu, Chuong, Muc stored at root level)
    try:
        from qdrant_client.models import PayloadSchemaType
        for field_name in ("Dieu", "Chuong", "Muc"):
            client.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        logger.info("Payload indexes ensured for Dieu, Chuong, Muc")
    except Exception as exc:  # noqa: BLE001 - payload indexes are an optional optimization
        logger.debug("Payload index creation skipped: %s", exc)

    embedder = get_embeddings()
    total = len(articles)

    for i in range(0, total, EMBED_BATCH_SIZE):
        batch_articles = articles[i: i + EMBED_BATCH_SIZE]
        batch_summaries = summaries[i: i + EMBED_BATCH_SIZE]

        logger.info("Embedding + upserting articles %d–%d / %d", i + 1, i + len(batch_articles), total)

        batch_embedding_texts = [
            _build_embedding_text(article, summary)
            for article, summary in zip(batch_articles, batch_summaries)
        ]
        vectors = embedder.embed_documents(batch_embedding_texts)

        points = []
        for j, (article, summary, vector) in enumerate(zip(batch_articles, batch_summaries, vectors)):
            # Normalise metadata keys (handle both raw and pre-transformed formats)
            dieu = article.get("Điều") or article.get("Dieu") or article.get("Điều_Number")
            chuong = article.get("Chương") or article.get("Chuong") or article.get("Chương_Number")
            muc = article.get("Mục") or article.get("Muc") or article.get("Mục_Number")

            # Content names
            dieu_name = article.get("Điều_Content") or article.get("Dieu_Name") or ""
            chuong_name = article.get("Chương_Content") or article.get("Chuong_Name") or ""
            muc_name = article.get("Mục_Content") or article.get("Muc_Name") or ""

            payload = {
                "source": "legal",
                "source_title": settings.law_citation_label,
                "Dieu": dieu,
                "Dieu_Name": dieu_name,
                "Chuong": chuong,
                "Chuong_Name": chuong_name,
                "Muc": muc,
                "Muc_Name": muc_name,
                "Pages": article.get("Pages", ""),
                "Parent_Id": article.get("Parent_Id", ""),
                "Chunk_Index": article.get("Chunk_Index", 0),
                "Chunk_Count": article.get("Chunk_Count", 1),
                "Full_Text_Chars": article.get("Full_Text_Chars", len(article.get("Text", article.get("text", "")))),
                "Parent_Dieu": article.get("Parent_Dieu", dieu),
                "Hierarchy": article.get("Hierarchy", ""),
                "Khoan": article.get("Khoan", ""),
                "Diem": article.get("Diem", ""),
                "Source_Start": article.get("Source_Start", 0),
                "Source_End": article.get("Source_End", len(article.get("Text", article.get("text", "")))),
                "Chunking_Strategy": article.get("Chunking_Strategy", _CHUNKING_STRATEGY),
                "Text": article.get("Text", article.get("text", "")),
                "summary": summary,
                "embedding_text": batch_embedding_texts[j],
                "Corpus_ID": settings.corpus_id,
                "Corpus_Version": settings.corpus_version,
                "Corpus_SHA256": os.getenv("CORPUS_SHA256", ""),
                "Index_Schema_Version": settings.index_schema_version,
                "provenance": "data/law.json",
            }

            point_id = _stable_point_id(
                settings=settings,
                article=article,
                fallback_seq=i + j + 1,
            )
            payload["document_id"] = point_id
            payload["legal_anchor"] = " / ".join(
                value for value in (str(article.get("Parent_Dieu") or dieu or ""), str(article.get("Khoan") or ""), str(article.get("Diem") or "")) if value
            )

            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        client.upsert(collection_name=collection, points=points)
        time.sleep(0.5)

    logger.info("✅ Upserted %d articles into '%s'", total, collection)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Embedding excerpt max chars: %d", _EMBED_TEXT_MAX_CHARS)
    logger.info(
        "Chunking config: chunk_size=%d overlap=%d summary_input_max=%d",
        _CHUNK_SIZE_CHARS,
        _CHUNK_OVERLAP_CHARS,
        _SUMMARY_INPUT_MAX_CHARS,
    )
    logger.info("Chunking strategy: %s; target collection: %s", _CHUNKING_STRATEGY, get_settings().law_collection)
    articles_raw = load_articles()
    validate_index_contract(articles_raw)
    logger.info("Loaded %d raw articles", len(articles_raw))

    articles, clean_stats = normalise_articles(articles_raw)
    logger.info("Cleaning stats: %s", clean_stats)
    validate_index_contract(articles)

    export_cleaned = os.getenv("EXPORT_CLEANED_LAW_JSON", "").strip()
    if export_cleaned:
        out_path = Path(export_cleaned).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"meta": articles}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Exported cleaned law dataset to %s", out_path)

    summaries = summarise_articles(articles)
    chunked_articles, chunked_summaries, chunk_stats = chunk_articles(articles, summaries)
    logger.info("Chunking stats: %s", chunk_stats)
    upsert_to_qdrant(chunked_articles, chunked_summaries)
    logger.info("Index build complete.")


if __name__ == "__main__":
    main()
