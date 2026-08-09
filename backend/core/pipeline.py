"""
Optimized chatbot pipeline — async generator.

Flow
----
query
  → semantic cache lookup       (skip everything on hit — no LLM cost)
  → question rewrite            (gpt-4o-mini, only when session history exists AND
                                 query looks like a follow-up, not a fresh question)
  → 2-way router                (gpt-4o-mini structured output)
    ├── chitchat → friendly response (gpt-3.5-turbo) → END   [NOT cached]
    └── epr_query
          → FAQ hybrid search   (Qdrant, threshold 0.75, no LLM cost)
            ├── hit  → stream FAQ answer (gpt-3.5-turbo stream) → cache → END
            └── miss
                  → Legal retrieval (Qdrant + SelfQuery)
                    ├── article not found (filter_matched=False + specific Điều) → "not found" → cache → END
                    ├── hit + relevance gate pass → stream legal answer → cache → END
                    ├── hit + relevance gate fail → EPR-scoped web search (Tavily) → cache → END
                    └── miss → EPR-scoped web search (Tavily) → cache → END

Cache policy:
  - Substantive answers (faq / legal / web) ARE cached
  - Chitchat is NOT cached (personalised, session-dependent, low reuse value)
  - out_of_domain concept removed: corpus miss drives web fallback, not the router

Yield format
------------
{"type": "status",           "message": str, "stage": str}
{"type": "response_chunk",   "chunk": str,   "stage": "streaming"}
{"type": "response_complete","text": str, "documents": list, "source": str, "stage": "complete"}
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import AsyncIterator, Dict, Any, List

from langchain_core.documents import Document

from backend.config import get_settings
from backend.cache import semantic_cache
from backend.core import router, rewriter, retrieval, generation
from backend.history import (
    ensure_conversation,
    get_recent_history,
    append_exchange as append_history_exchange,
)
from backend.memory import session_store
from backend.api import metrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistence helper - await tasks with timeout to prevent data loss
# ---------------------------------------------------------------------------

async def _await_persistence(tasks: list, session_id: str, timeout: float = 5.0):
    """
    Await persistence tasks with timeout to prevent data loss on shutdown.
    
    This ensures session history and cache writes complete before yielding
    the response, preventing silent data loss under high load or shutdown.
    """
    if not tasks:
        return
    
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    
    # Cancel pending tasks that didn't complete
    for task in pending:
        task.cancel()
        logger.warning(
            "Persistence task timed out after %.1fs for session=%s",
            timeout, session_id
        )
    
    # Log any exceptions from completed tasks
    for task in done:
        try:
            exc = task.exception()
            if exc:
                logger.error("Persistence task failed: %s", exc)
        except asyncio.CancelledError:
            pass  # Task was cancelled, not an error


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _status(message: str, stage: str) -> Dict[str, Any]:
    return {"type": "status", "message": message, "stage": stage}


def _chunk(text: str) -> Dict[str, Any]:
    return {"type": "response_chunk", "chunk": text, "stage": "streaming"}


def _complete(text: str, docs: List[Document], source: str) -> Dict[str, Any]:
    return {
        "type": "response_complete",
        "text": text,
        "documents": [
            {
                "page_content": d.page_content,
                "metadata": d.metadata,
            }
            for d in docs
        ],
        "source": source,
        "stage": "complete",
    }


_REWRITE_CUE_PATTERNS = [
    r"\b(nó|đó|này)\b",
    r"\b(điều đó|luật đó|ở trên|vừa rồi)\b",
    r"\b(cái này|cái đó|việc này|việc đó)\b",
]

_EPR_INTENT_TERMS = (
    "epr",
    "trách nhiệm mở rộng",
    "nhà sản xuất",
    "tái chế",
    "bao bì",
    "mức đóng góp",
    "quỹ bảo vệ môi trường",
)

_LEGAL_HEADING_TERMS = (
    "trách nhiệm",
    "tái chế",
    "đối tượng",
    "lộ trình",
    "đóng góp",
    "bao bì",
    "phụ lục",
)

_FOLLOWUP_MARKER = "**💡 Bạn có thể hỏi tiếp:**"

_LEGAL_DEFAULT_FOLLOWUPS = [
    "Điều 77 quy định đối tượng nào phải thực hiện trách nhiệm tái chế?",
    "Điều 78 quy định tỷ lệ và quy cách tái chế bắt buộc ra sao?",
    "Điều 79 có những hình thức thực hiện trách nhiệm tái chế nào?",
]

_WEB_DEFAULT_FOLLOWUPS = [
    "Bạn có thể trích đúng Điều/Chương liên quan trong Nghị định 08/2022/NĐ-CP không?",
    "Đối tượng nào phải đóng góp tài chính vào Quỹ theo Điều 83?",
    "Tôi thuộc doanh nghiệp nhập khẩu thì cần bắt đầu từ bước nào để tuân thủ EPR?",
]


def _needs_contextual_rewrite(query: str, chat_history: str) -> bool:
    """Rewrite only when the query likely depends on previous context."""
    if not chat_history or chat_history == "(trống)":
        return False

    q = query.lower().strip()
    if not q:
        return False

    # Explicit legal references are already specific enough; avoid rewriting.
    if re.search(r"\b(đi[eề]u|khoản|chương|mục)\s+\d+", q):
        return False

    # Typical short follow-up shape ("vậy...", "thế còn...", "còn nữa không"...).
    followup_leads = ("vậy", "thế", "còn", "nếu vậy", "trường hợp đó")
    if len(q) <= 40 and any(q.startswith(prefix) for prefix in followup_leads):
        return True

    return any(re.search(pattern, q) for pattern in _REWRITE_CUE_PATTERNS)


def _should_skip_relevance_gate(query: str, docs: List[Document]) -> bool:
    """Skip expensive relevance gate for clearly on-domain EPR queries."""
    if not docs:
        return False

    q = (query or "").lower()
    if not any(term in q for term in _EPR_INTENT_TERMS):
        return False

    top_doc = docs[0]
    heading = " ".join(
        str(part).lower()
        for part in (
            top_doc.metadata.get("Dieu", ""),
            top_doc.metadata.get("Chuong", ""),
            top_doc.metadata.get("Muc", ""),
        )
        if part
    )
    return any(term in heading for term in _LEGAL_HEADING_TERMS)


def _append_followup_block(text: str, suggestions: List[str]) -> str:
    """Append a follow-up suggestions section once, if suggestions are available."""
    if not suggestions:
        return text
    if _FOLLOWUP_MARKER in text:
        return text
    block = "\n\n---\n\n" + _FOLLOWUP_MARKER + "\n" + "\n".join(f"- {s}" for s in suggestions)
    return text + block


def _default_followups(source: str) -> List[str]:
    if source == "web_search":
        return _WEB_DEFAULT_FOLLOWUPS
    if source in {"legal", "faq"}:
        return _LEGAL_DEFAULT_FOLLOWUPS
    return []


async def _decorate_with_followups(
    query: str,
    response_text: str,
    source: str,
    *,
    enable_llm_suggestions: bool,
) -> str:
    """
    Attach follow-up suggestions.

    - If LLM suggestions are enabled, try generating contextual suggestions.
    - For legal/web sources, always fall back to deterministic suggestions so
      users are never left without guidance.
    """
    suggestions: List[str] = []
    if enable_llm_suggestions:
        try:
            suggestions = await generation.generate_follow_ups(query, response_text)
        except Exception as exc:
            logger.debug("follow-up generation failed for source=%s: %s", source, exc)

    if not suggestions:
        suggestions = _default_followups(source)

    return _append_followup_block(response_text, suggestions)


async def _persist_exchange(
    user_id: str,
    conversation_id: str,
    legacy_session_id: str | None,
    user_msg: str,
    assistant_msg: str,
) -> None:
    """Persist one exchange to durable history and optional legacy session store."""
    settings = get_settings()

    if settings.history_enabled:
        await append_history_exchange(
            user_id=user_id,
            conversation_id=conversation_id,
            user_msg=user_msg,
            assistant_msg=assistant_msg,
        )

    # Redis no longer receives a durable conversation copy.  It remains a
    # short-lived cache/rate-limit layer; SQLAlchemy persistence owns history.


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def optimized_chatbot_pipeline(
    query: str,
    user_id: str = "dev-local",
    conversation_id: str = "default",
    session_id: str | None = None,
    legacy_session_id: str | None = None,
    faq_threshold: float = 0.75,
    *,
    skip_cache: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Async generator — yields status updates then streamed response chunks.

    skip_cache: when True, skip only the initial cache lookup so retrieval runs
    (eval uses this so LLM-as-judge receives `documents`). FAQ/Legal/Web paths
    still call semantic_cache.store() at the end.
    """
    start_time = time.time()
    settings = get_settings()

    def _observe_stage_latency(stage: str, started_at: float) -> None:
        metrics.track_stage_latency(stage, time.perf_counter() - started_at)
    
    # Fix: Trim query to prevent whitespace-only queries
    query = query.strip()
    if not query:
        yield _status("❌ Empty query", "error")
        yield _complete("Vui lòng nhập câu hỏi.", [], "error")
        return

    # ── 0. Load conversation history ─────────────────────────────────────
    legacy_session_id = legacy_session_id or session_id
    conversation_id = conversation_id or legacy_session_id or "default"

    if settings.history_enabled:
        try:
            conversation_id = await ensure_conversation(user_id, conversation_id, title_seed=query)
            messages = await get_recent_history(
                user_id=user_id,
                conversation_id=conversation_id,
                max_messages=max(2, settings.history_context_messages),
            )
        except Exception as exc:
            logger.warning(
                "Persistent history load failed for conversation=%s: %s; falling back to session store",
                conversation_id,
                exc,
            )
            fallback_sid = legacy_session_id or conversation_id
            messages = await session_store.get_history(fallback_sid)
    else:
        fallback_sid = legacy_session_id or conversation_id
        messages = await session_store.get_history(fallback_sid)

    chat_history = session_store.format_history_for_llm(messages)

    # ── 1. Semantic cache lookup ─────────────────────────────────────────
    if not skip_cache:
        yield _status("🔍 Checking cache…", "cache")
        cache_stage_start = time.perf_counter()
        cached = await semantic_cache.lookup(query)
        _observe_stage_latency("cache", cache_stage_start)
        if cached:
            logger.info("Cache hit for conversation=%s", conversation_id)
            metrics.track_pipeline_stage("cache")
            
            # CRITICAL PERF FIX: Yield cached response immediately.
            # Skip Redis append when this session already has history (repeat / follow-up)
            # so we do not double-store the same cached answer for the same session.
            # First turn + cache hit: must append so registry / sidebar list updates.
            yield _chunk(cached)
            persist_tasks = [
                asyncio.create_task(
                    _persist_exchange(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        legacy_session_id=legacy_session_id,
                        user_msg=query,
                        assistant_msg=cached,
                    )
                ),
            ]
            await _await_persistence(persist_tasks, conversation_id)
            yield _complete(cached, [], "cache")
            return

    # ── 2. Route first (cheap) — skip rewrite for chitchat ──────────────
    yield _status("🔀 Routing question…", "routing")
    routing_stage_start = time.perf_counter()
    route = router.route_query(query)
    _observe_stage_latency("routing", routing_stage_start)

    if route == "chitchat":
        # Check for vague follow-ups before generating a full chitchat response
        if generation._is_vague_followup(query, chat_history):
            response_text = generation.get_vague_followup_response()
            response_text = await _decorate_with_followups(
                query,
                response_text,
                "chitchat",
                enable_llm_suggestions=settings.enable_followup_suggestions,
            )
            yield _chunk(response_text)

            persist_tasks = [
                asyncio.create_task(
                    _persist_exchange(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        legacy_session_id=legacy_session_id,
                        user_msg=query,
                        assistant_msg=response_text,
                    )
                ),
            ]
            await _await_persistence(persist_tasks, conversation_id)

            yield _complete(response_text, [], "chitchat")
            return

        # Personalised response — use original query, inject history for context.
        # NOT cached: chitchat answers are session-specific and have near-zero reuse.
        yield _status("💬 Generating friendly response…", "chitchat")
        chitchat_stage_start = time.perf_counter()

        # CRITICAL PERF FIX: Stream tokens instead of waiting for full response
        full_response = ""
        async for token in generation.stream_chitchat_response(query, chat_history):
            full_response += token
            yield _chunk(token)
        _observe_stage_latency("chitchat_generation", chitchat_stage_start)

        metrics.track_pipeline_stage("chitchat")

        # FIX: Await persistence with timeout to prevent data loss
        persist_tasks = [
            asyncio.create_task(
                _persist_exchange(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    legacy_session_id=legacy_session_id,
                    user_msg=query,
                    assistant_msg=full_response,
                )
            ),
        ]
        await _await_persistence(persist_tasks, conversation_id)

        full_response = await _decorate_with_followups(
            query,
            full_response,
            "chitchat",
            enable_llm_suggestions=settings.enable_followup_suggestions,
        )

        yield _complete(full_response, [], "chitchat")
        return

    # ── 3. Rewrite only for context-dependent substantive queries ─────────
    effective_query = query
    if settings.enable_query_rewrite and _needs_contextual_rewrite(query, chat_history):
        yield _status("✏️ Rewriting question…", "rewrite")
        rewrite_stage_start = time.perf_counter()
        effective_query = rewriter.rewrite_question(query, chat_history)
        _observe_stage_latency("rewrite", rewrite_stage_start)
        logger.debug("Rewritten: %r → %r", query, effective_query)
        # Log if rewriting significantly changed the query
        if len(set(effective_query.lower()) - set(query.lower())) > 10:
            logger.info("Question rewriting significantly changed query: %r → %r", query[:50], effective_query[:80])

    # Handle vague follow-up even on substantive route so it doesn't fall into web timeout.
    if generation._is_vague_followup(effective_query, chat_history):
        followup_msg = (
            "Mình có thể đi tiếp theo các nhóm nội dung EPR quan trọng, "
            "bạn chọn 1 hướng để mình trả lời sâu và trích đúng điều luật."
        )
        followup_msg = await _decorate_with_followups(
            query,
            followup_msg,
            "legal",
            enable_llm_suggestions=settings.enable_followup_suggestions,
        )
        yield _chunk(followup_msg)
        persist_tasks = [
            asyncio.create_task(
                _persist_exchange(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    legacy_session_id=legacy_session_id,
                    user_msg=query,
                    assistant_msg=followup_msg,
                )
            ),
        ]
        await _await_persistence(persist_tasks, conversation_id)
        yield _complete(followup_msg, [], "legal")
        return

    # ── 4. Strict FAQ semantic cache ─────────────────────────────────────
    faq_start = time.time()
    faq_stage_start = time.perf_counter()
    yield _status("📚 Searching FAQ…", "faq_retrieval")
    faq_docs = await retrieval.retrieve_faq_async(effective_query, faq_threshold)
    faq_latency = time.time() - faq_start
    _observe_stage_latency("faq_retrieval", faq_stage_start)
    metrics.RETRIEVAL_LATENCY.labels(retriever="faq").observe(faq_latency)

    faq_is_strict_hit = bool(
        faq_docs and (
            not settings.enable_strict_faq_gate or
            faq_docs[0].metadata.get("strict_faq_hit")
        )
    )

    if faq_docs and faq_is_strict_hit:
        source = "faq"
        metrics.track_retrieval("faq", "hit")
        metrics.track_pipeline_stage("faq")
        logger.info(
            "Strict FAQ hit for query=%r, score=%.3f, margin=%.3f",
            effective_query,
            faq_docs[0].metadata.get("score", 0),
            faq_docs[0].metadata.get("score_margin", 0),
        )
        yield _status("✅ Found match in FAQ — generating answer…", "generation")
        faq_gen_stage_start = time.perf_counter()
        full_response = ""
        async for token in generation.stream_faq_answer(effective_query, faq_docs[0]):
            full_response += token
            yield _chunk(token)
        _observe_stage_latency("faq_generation", faq_gen_stage_start)

        # FIX: Await persistence with timeout to prevent data loss
        persist_tasks = [
            asyncio.create_task(
                _persist_exchange(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    legacy_session_id=legacy_session_id,
                    user_msg=query,
                    assistant_msg=full_response,
                )
            ),
            asyncio.create_task(semantic_cache.store(query, full_response)),
        ]
        await _await_persistence(persist_tasks, conversation_id)

        full_response = await _decorate_with_followups(
            query,
            full_response,
            "faq",
            enable_llm_suggestions=settings.enable_followup_suggestions,
        )

        yield _complete(full_response, faq_docs, source)
        return

    metrics.track_retrieval("faq", "miss")
    if faq_docs:
        logger.info(
            "FAQ candidate rejected as non-strict for query=%r, score=%.3f, margin=%.3f",
            effective_query,
            faq_docs[0].metadata.get("score", 0),
            faq_docs[0].metadata.get("score_margin", 0),
        )
    else:
        logger.info("FAQ miss for query=%r, falling back to legal retrieval", effective_query)

    # ── 5. Legal retrieval (only when FAQ misses) ─────────────────────────
    legal_start = time.time()
    legal_stage_start = time.perf_counter()
    yield _status("⚖️ Searching legal documents…", "legal_retrieval")
    legal_docs = await retrieval.retrieve_legal_async(effective_query)
    legal_latency = time.time() - legal_start
    _observe_stage_latency("legal_retrieval", legal_stage_start)
    metrics.RETRIEVAL_LATENCY.labels(retriever="legal").observe(legal_latency)

    # Diagnostic logging for retrieval
    if legal_docs:
        logger.info(
            "Legal retrieval returned %d docs for query=%r, first doc Dieu=%r, filter_matched=%r",
            len(legal_docs),
            effective_query,
            legal_docs[0].metadata.get("Dieu", ""),
            legal_docs[0].metadata.get("filter_matched", False),
        )
        top_trace = [
            {
                "rank": idx + 1,
                "dieu": doc.metadata.get("Dieu", ""),
                "source": doc.metadata.get("retrieval_source", ""),
                "semantic": doc.metadata.get("semantic_score", 0),
                "lexical": doc.metadata.get("lexical_score", 0),
                "rerank": doc.metadata.get("rerank_score", 0),
            }
            for idx, doc in enumerate(legal_docs[:5])
        ]
        logger.info("Legal final ranking for query=%r: %s", effective_query, top_trace)
    else:
        logger.warning("Legal retrieval returned NO docs for query=%r", effective_query)

    # ── 5-pre. "Article not found" shortcut ──────────────────────────────
    # If the user asked for a specific Điều number (e.g. "điều 160") but the
    # SelfQuery filter returned no matches (filter_matched=False on all docs),
    # it means that article doesn't exist in the corpus.  Short-circuit here
    # with a clear "not found" message — cheaper than running the Relevance
    # Gate and more informative than the generic web fallback.
    _dieu_match = re.search(r"đi[eề]u\s+(\d+)", effective_query, re.IGNORECASE)
    if _dieu_match:
        _requested_dieu = _dieu_match.group(1)
        _all_fallback = legal_docs and all(
            not d.metadata.get("filter_matched", True) for d in legal_docs
        )
        if _all_fallback:
            metrics.track_retrieval("legal", "miss")
            not_found_msg = (
                f"**Điều {_requested_dieu} không có trong Nghị định 08/2022/NĐ-CP.**\n\n"
                f"Nghị định này quy định từ Điều 1 đến Điều 154. "
                f"Điều {_requested_dieu} vượt ngoài phạm vi văn bản.\n\n"
                "Bạn có thể hỏi về:\n"
                "- Một điều khoản cụ thể trong khoảng Điều 1–154\n"
                "- Các chương/mục của Nghị định (ví dụ: Chương III về trách nhiệm tái chế)\n"
                "- Quy định về tỷ lệ tái chế, đối tượng thực hiện EPR, mức đóng góp tài chính"
            )
            # Stream the not-found message for better UX
            yield _chunk(not_found_msg)

            # FIX: Await persistence with timeout to prevent data loss
            persist_tasks = [
                asyncio.create_task(
                    _persist_exchange(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        legacy_session_id=legacy_session_id,
                        user_msg=query,
                        assistant_msg=not_found_msg,
                    )
                ),
                asyncio.create_task(semantic_cache.store(query, not_found_msg)),
            ]
            await _await_persistence(persist_tasks, conversation_id)

            yield _complete(not_found_msg, [], "legal")
            return

    if legal_docs:
        metrics.track_retrieval("legal", "hit")
        if settings.enable_legal_evidence_guardrail:
            evidence_ok, evidence_reason = generation.check_legal_evidence(
                legal_docs,
                min_docs=settings.min_legal_evidence_docs,
                min_chars=settings.min_legal_evidence_chars,
            )
            if not evidence_ok:
                metrics.track_pipeline_stage("legal_guardrail")
                logger.warning(
                    "Legal evidence guardrail blocked generation for query=%r: %s",
                    effective_query,
                    evidence_reason,
                )
                guardrail_msg = (
                    "Tôi chưa đủ căn cứ pháp lý rõ ràng để trả lời chắc chắn cho câu hỏi này từ dữ liệu hiện có.\n\n"
                    "Bạn vui lòng nêu cụ thể hơn (ví dụ số Điều/Chương hoặc chủ đề EPR cụ thể) để tôi truy xuất chính xác hơn."
                )
                guardrail_msg = await _decorate_with_followups(
                    query,
                    guardrail_msg,
                    "legal",
                    enable_llm_suggestions=settings.enable_followup_suggestions,
                )
                yield _chunk(guardrail_msg)

                persist_tasks = [
                    asyncio.create_task(
                        _persist_exchange(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            legacy_session_id=legacy_session_id,
                            user_msg=query,
                            assistant_msg=guardrail_msg,
                        )
                    ),
                ]
                await _await_persistence(persist_tasks, conversation_id)
                yield _complete(guardrail_msg, legal_docs, "legal")
                return

        # ── 5a. Relevance gate — verify docs actually answer the question ──
        # Embedding scores alone can't distinguish domain (tested: off-domain
        # queries score 0.24-0.38, on-domain 0.27-0.35 — indistinguishable).
        # A fast LLM binary check catches cases like "thị trường chứng khoán"
        # that retrieve EPR docs by coincidental word overlap.
        if settings.enable_relevance_gate:
            if _should_skip_relevance_gate(effective_query, legal_docs):
                is_relevant = True
                logger.info(
                    "Relevance gate skipped for clear EPR query=%r top_doc=%r",
                    effective_query,
                    legal_docs[0].metadata.get("Dieu", ""),
                )
            else:
                relevance_gate_start = time.perf_counter()
                loop = asyncio.get_running_loop()
                is_relevant = await loop.run_in_executor(
                    None, generation.is_retrieval_relevant, effective_query, legal_docs
                )
                _observe_stage_latency("relevance_gate", relevance_gate_start)
        else:
            is_relevant = True

        if is_relevant:
            source = "legal"
            metrics.track_pipeline_stage("legal")
            yield _status("✅ Found legal documents — generating answer…", "generation")
            legal_gen_stage_start = time.perf_counter()
            full_response = ""
            async for token in generation.stream_legal_answer(effective_query, legal_docs):
                full_response += token
                yield _chunk(token)
            _observe_stage_latency("legal_generation", legal_gen_stage_start)

            # FIX: Await persistence with timeout to prevent data loss
            persist_tasks = [
                asyncio.create_task(
                    _persist_exchange(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        legacy_session_id=legacy_session_id,
                        user_msg=query,
                        assistant_msg=full_response,
                    )
                ),
                asyncio.create_task(semantic_cache.store(query, full_response)),
            ]
            await _await_persistence(persist_tasks, conversation_id)

            full_response = await _decorate_with_followups(
                query,
                full_response,
                "legal",
                enable_llm_suggestions=settings.enable_followup_suggestions,
            )

            yield _complete(full_response, legal_docs, source)
            return
        else:
            logger.warning(
                "Relevance gate REJECTED docs for query=%r, first doc Dieu=%r",
                effective_query,
                legal_docs[0].metadata.get("Dieu", "") if legal_docs else "N/A",
            )
            metrics.track_retrieval("legal", "miss")

    if not settings.enable_web_fallback:
        no_fallback_msg = (
            "Không tìm thấy đủ thông tin trong dữ liệu nội bộ và web fallback hiện đang tắt.\n\n"
            "Bạn có thể hỏi lại với phạm vi cụ thể hơn theo Điều/Chương/Mục để tôi tra cứu chính xác hơn."
        )
        no_fallback_msg = await _decorate_with_followups(
            query,
            no_fallback_msg,
            "legal",
            enable_llm_suggestions=settings.enable_followup_suggestions,
        )
        yield _chunk(no_fallback_msg)
        persist_tasks = [
            asyncio.create_task(
                _persist_exchange(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    legacy_session_id=legacy_session_id,
                    user_msg=query,
                    assistant_msg=no_fallback_msg,
                )
            ),
        ]
        await _await_persistence(persist_tasks, conversation_id)
        yield _complete(no_fallback_msg, [], "legal")
        return

    # ── 6. EPR-scoped web fallback ────────────────────────────────────────
    yield _status("🌐 Searching EPR web sources…", "web_search")
    web_stage_start = time.perf_counter()
    # CRITICAL: Run sync Tavily call in thread executor
    loop = asyncio.get_running_loop()
    try:
        web_response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                generation.web_fallback,
                effective_query,
            ),
            timeout=max(1.0, settings.web_fallback_timeout_seconds),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Web fallback timed out after %.1fs for query=%r",
            settings.web_fallback_timeout_seconds,
            effective_query,
        )
        web_response = (
            "Hiện chưa thể truy vấn nguồn web kịp thời. "
            "Bạn vui lòng hỏi lại với phạm vi cụ thể hơn theo Điều/Chương/Mục EPR."
        )
    web_response = await _decorate_with_followups(
        query,
        web_response,
        "web_search",
        enable_llm_suggestions=settings.enable_followup_suggestions,
    )
    _observe_stage_latency("web_search", web_stage_start)
    metrics.track_pipeline_stage("web_search")
    # Stream web response for better UX
    yield _chunk(web_response)

    # FIX: Await persistence with timeout to prevent data loss
    persist_tasks = [
        asyncio.create_task(
            _persist_exchange(
                user_id=user_id,
                conversation_id=conversation_id,
                legacy_session_id=legacy_session_id,
                user_msg=query,
                assistant_msg=web_response,
            )
        ),
        asyncio.create_task(semantic_cache.store(query, web_response)),
    ]
    await _await_persistence(persist_tasks, conversation_id)

    yield _complete(web_response, [], "web_search")

    # Log total pipeline latency
    total_latency = time.time() - start_time
    logger.info("Pipeline completed in %.2fs for conversation=%s", total_latency, conversation_id)
