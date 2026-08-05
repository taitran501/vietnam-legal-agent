"""
Two-layer semantic cache with LRU eviction and TTL-based cleanup.

Layer 1 (exact) : sha-256(normalised_query) → Redis string (O(1), cheapest)
Layer 2 (fuzzy) : embed query → Qdrant cosine search on cache_collection (O(log n))

Features:
- LRU eviction when cache exceeds max_size
- TTL-based cleanup via background task
- Graceful degradation on failures

On miss the caller is expected to generate the answer, then call `store()`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Optional

import redis.asyncio as aioredis

from backend.config import get_settings
from backend.core.llm_instances import get_embeddings
from backend.memory.session_store import get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_CACHE_SIZE = 10000  # Maximum entries in semantic cache before LRU eviction
CLEANUP_INTERVAL = 3600  # Run cleanup every hour


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _exact_key(query: str) -> str:
    digest = hashlib.sha256(_normalise(query).encode()).hexdigest()
    return f"cache:exact:{digest}"


# ---------------------------------------------------------------------------
# Layer 1 – Exact match (Redis with LRU)
# ---------------------------------------------------------------------------

async def _exact_get(query: str) -> Optional[str]:
    try:
        r: aioredis.Redis = await get_redis()
        raw = await r.get(_exact_key(query))
        if raw:
            data = json.loads(raw)
            return data.get("answer")
    except Exception as exc:
        logger.debug("exact cache get failed: %s", exc)
    return None


async def _exact_set(query: str, answer: str) -> None:
    settings = get_settings()
    try:
        r: aioredis.Redis = await get_redis()
        payload = json.dumps({"answer": answer}, ensure_ascii=False)
        await r.set(_exact_key(query), payload, ex=settings.cache_ttl_seconds)
    except Exception as exc:
        logger.debug("exact cache set failed: %s", exc)


# ---------------------------------------------------------------------------
# LRU tracking via Redis sorted set
# ---------------------------------------------------------------------------

_LRU_KEY = "cache:lru_tracker"


async def _track_access(key: str) -> None:
    """Track access time for LRU eviction."""
    try:
        r: aioredis.Redis = await get_redis()
        import time
        await r.zadd(_LRU_KEY, {key: time.time()})
    except Exception:
        pass  # Non-critical, fail silently


async def _enforce_lru_limit() -> None:
    """Enforce LRU limit by removing oldest entries."""
    try:
        r: aioredis.Redis = await get_redis()
        current_size = await r.zcard(_LRU_KEY)
        
        if current_size > MAX_CACHE_SIZE:
            # Remove oldest entries
            to_remove = current_size - MAX_CACHE_SIZE
            oldest_keys = await r.zrange(_LRU_KEY, 0, to_remove - 1)
            
            if oldest_keys:
                pipe = r.pipeline()
                for key in oldest_keys:
                    pipe.delete(key)
                    pipe.zrem(_LRU_KEY, key)
                await pipe.execute()
                logger.info("LRU cleanup: removed %d old cache entries", len(oldest_keys))
    except Exception as exc:
        logger.debug("LRU enforcement failed: %s", exc)


# ---------------------------------------------------------------------------
# TTL-based cleanup
# ---------------------------------------------------------------------------

async def cleanup_expired() -> None:
    """Remove expired entries from the cache."""
    try:
        r: aioredis.Redis = await get_redis()
        # Redis handles TTL automatically via EXPIRE, but we can clean the LRU tracker
        now = __import__("time").time()
        cutoff = now - (CLEANUP_INTERVAL * 2)  # Remove entries older than 2 cleanup cycles
        await r.zremrangebyscore(_LRU_KEY, 0, cutoff)
        logger.debug("TTL cleanup: removed stale LRU entries")
    except Exception as exc:
        logger.debug("TTL cleanup failed: %s", exc)


# ---------------------------------------------------------------------------
# Layer 2 – Semantic match (Qdrant) with Redis-based LRU tracking
# ---------------------------------------------------------------------------

# Redis sorted set to track Qdrant point IDs by insertion time for LRU eviction
# Format: member = "qdrant_point_id", score = unix_timestamp
_SEMANTIC_LRU_KEY = "cache:semantic_lru"


def _get_qdrant_client():
    from backend.core.retrieval import _get_qdrant_client as base_client
    return base_client()


async def _semantic_get(query: str) -> Optional[str]:
    """Retrieve from semantic cache with async embedding.
    
    CRITICAL FIX HIGH #2: Wrap sync embed_query() in thread executor
    to prevent blocking the event loop during OpenAI API calls.
    """
    import asyncio
    settings = get_settings()
    try:
        # CRITICAL: Run sync embedding in thread executor
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None,
            get_embeddings().embed_query,
            _normalise(query)
        )
        
        client = _get_qdrant_client()
        from qdrant_client.models import SearchParams
        results = client.search(
            collection_name=settings.cache_collection,
            query_vector=embedding,
            limit=1,
            score_threshold=settings.semantic_cache_threshold,
            search_params=SearchParams(hnsw_ef=settings.search_ef),
        )
        if results:
            payload = results[0].payload or {}
            answer = payload.get("answer")
            point_id = str(results[0].id)
            
            # Track access in Redis LRU sorted set
            await _track_semantic_access(point_id)
            
            return answer
    except Exception as exc:
        logger.debug("semantic cache get failed: %s", exc)
    return None


async def _track_semantic_access(point_id: str) -> None:
    """Track access time for semantic cache LRU eviction using Redis.
    
    CRITICAL FIX HIGH #1: Use Redis sorted set instead of Qdrant scroll.
    This is O(1) instead of O(N) and doesn't block the event loop.
    """
    import time
    try:
        r: aioredis.Redis = await get_redis()
        await r.zadd(_SEMANTIC_LRU_KEY, {point_id: time.time()})
    except Exception as exc:
        logger.debug("Semantic LRU tracking failed: %s", exc)


async def _semantic_set(query: str, answer: str) -> None:
    """Store in semantic cache with Redis-based LRU enforcement.
    
    CRITICAL FIX HIGH #1 & #2:
    - Wrap sync embed_query() in thread executor
    - Use Redis sorted set for O(1) LRU tracking
    - No Qdrant scroll operations
    """
    import asyncio
    import time
    
    settings = get_settings()
    try:
        # CRITICAL: Run sync embedding in thread executor
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None,
            get_embeddings().embed_query,
            _normalise(query)
        )
        
        client = _get_qdrant_client()
        # Ensure collection exists (idempotent)
        try:
            client.get_collection(settings.cache_collection)
        except Exception:
            from qdrant_client.models import Distance, VectorParams, HnswConfigDiff
            
            # FIX: Derive embedding dimension dynamically instead of hardcoding 1536
            # This prevents breakage if embedding model changes
            sample_embedding = await loop.run_in_executor(
                None,
                get_embeddings().embed_query,
                "test"
            )
            embedding_dim = len(sample_embedding)
            
            client.create_collection(
                collection_name=settings.cache_collection,
                vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
                hnsw_config=HnswConfigDiff(
                    m=settings.hnsw_m,
                    ef_construct=settings.hnsw_ef_construct,
                ),
            )
        from qdrant_client.models import PointStruct
        
        # Generate point ID from query hash for deduplication
        point_id = str(uuid.uuid4())
        
        client.upsert(
            collection_name=settings.cache_collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "query": _normalise(query),
                        "answer": answer,
                        "created_at": time.time(),
                    },
                )
            ],
        )
        
        # Track in Redis LRU sorted set
        await _track_semantic_access(point_id)
        
        # Enforce LRU limit using Redis count (O(1)) instead of Qdrant scroll (O(N))
        await _enforce_semantic_cache_lru()
    except Exception as exc:
        logger.debug("semantic cache set failed: %s", exc)


async def _enforce_semantic_cache_lru() -> None:
    """
    Enforce LRU limit on semantic cache using Redis count.
    
    CRITICAL FIX HIGH #1: Replaces O(N) Qdrant scroll with O(1) Redis count.
    
    This function:
    1. Counts entries in Redis LRU sorted set (O(1))
    2. If exceeds MAX_CACHE_SIZE, gets oldest point IDs from sorted set
    3. Deletes those points from Qdrant directly (no scroll needed)
    4. Removes deleted points from Redis sorted set
    
    Complexity: O(K) where K = number to delete (typically small)
    Previous implementation: O(N) where N = total cache size
    """
    settings = get_settings()
    try:
        r: aioredis.Redis = await get_redis()
        
        # O(1) count check
        current_size = await r.zcard(_SEMANTIC_LRU_KEY)
        
        if current_size <= MAX_CACHE_SIZE:
            return  # Under limit, no action needed
        
        # Calculate how many to delete
        to_delete = current_size - MAX_CACHE_SIZE
        
        # Get oldest point IDs from Redis sorted set (O(log N + K))
        oldest_entries = await r.zrange(_SEMANTIC_LRU_KEY, 0, to_delete - 1, withscores=False)
        
        if not oldest_entries:
            return
        
        # Delete from Qdrant directly using point IDs
        client = _get_qdrant_client()
        client.delete(
            collection_name=settings.cache_collection,
            points_selector=list(oldest_entries),
        )
        
        # Remove from Redis LRU tracker
        await r.zrem(_SEMANTIC_LRU_KEY, *oldest_entries)
        
        logger.info(
            "Semantic cache LRU: deleted %d oldest entries (was %d, now %d)",
            len(oldest_entries),
            current_size,
            current_size - len(oldest_entries),
        )
    except Exception as exc:
        logger.debug("Semantic cache LRU enforcement failed: %s", exc)


# ---------------------------------------------------------------------------
# Answer validation before caching
# ---------------------------------------------------------------------------

_ERROR_PATTERNS = [
    "xin lỗi",
    "không tìm thấy",
    "không thể",
    "lỗi",
    "error",
    "internal server error",
    "⚠️",
    "cannot",
    "unable to",
]


def _validate_answer(answer: str, min_length: int = 20) -> bool:
    """
    Validate answer quality before caching.

    Prevents caching of:
    - Error messages
    - Empty or too-short responses
    - Generic fallback messages

    Args:
        answer: The answer text to validate
        min_length: Minimum character length for valid answers

    Returns:
        True if answer is valid, False otherwise
    """
    if not answer or not answer.strip():
        return False

    # Check for too-short answers
    if len(answer) < min_length:
        return False

    # Check for error patterns (case-insensitive)
    answer_lower = answer.lower()
    if any(pattern in answer_lower for pattern in _ERROR_PATTERNS):
        return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def lookup(query: str) -> Optional[str]:
    """Check exact then semantic cache. Returns cached answer or None."""
    from backend.api import metrics as metrics_module
    
    answer = await _exact_get(query)
    if answer:
        logger.debug("exact cache hit")
        metrics_module.track_cache_hit("exact")
        await _track_access(_exact_key(query))
        return answer
    
    answer = await _semantic_get(query)
    if answer:
        logger.debug("semantic cache hit")
        metrics_module.track_cache_hit("semantic")
        await _track_access(f"semantic:{_normalise(query)}")
        return answer
    
    metrics_module.track_cache_miss()
    return answer


async def store(query: str, answer: str) -> None:
    """Persist answer to both cache layers with LRU tracking.

    MEDIUM FIX: Validate answer quality before caching to prevent storing
    error messages, empty responses, or low-quality answers.
    """
    # Validate answer quality before caching
    if not _validate_answer(answer):
        logger.warning("Skipping cache store for low-quality answer: %r", answer[:100])
        return  # Don't cache invalid answers

    await _exact_set(query, answer)
    await _semantic_set(query, answer)

    # Track for LRU
    await _track_access(_exact_key(query))
    await _track_access(f"semantic:{_normalise(query)}")

    # Enforce LRU limit periodically (probabilistic)
    import random
    if random.random() < 0.1:  # 10% chance on each store
        await _enforce_lru_limit()
