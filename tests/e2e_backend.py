"""Deterministic FastAPI host for browser-level frontend/backend acceptance.

This process exercises the production chat route, SSE presenter, LangGraph,
React SSE parser, and UI without requiring paid APIs or live infrastructure.
Only tool adapters are deterministic doubles.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.api.routes import chat as chat_routes
from backend.api.routes.chat import router as chat_router
from fastapi import FastAPI, HTTPException

from vietnam_legal_agent.agent.graph import WorkflowDependencies
from vietnam_legal_agent.agent.planner import BoundedPlanner
from vietnam_legal_agent.agent.v4 import V4WorkflowRuntime
from vietnam_legal_agent.domain.legal import EMBEDDING_PROFILE, explicit_anchors, parse_required_anchors
from vietnam_legal_agent.domain.models import AgentState, DocumentRecord
from vietnam_legal_agent.infra.admission import AdmissionLease
from vietnam_legal_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from vietnam_legal_agent.tools.evidence import (
    EvidenceEvaluator,
    document_matches_anchor,
    filter_universal_retrieval_neighbors,
    legal_relevance_checker,
)
from vietnam_legal_agent.tools.generation import EvidenceGenerationGateway
from vietnam_legal_agent.tools.history import ContextSnapshot
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway


async def _deterministic_ready() -> tuple[dict[str, object], str]:
    """Keep browser acceptance isolated from Docker/Qdrant readiness.

    This dedicated browser host exercises the same SSE route with deterministic
    adapters, so it supplies the fast chat-admission contract without
    requiring the real local stack during UI tests.
    """

    return (
        {
            "status": "ready",
            "runtime_mode": "preview",
            "preview": True,
            "dependencies": {},
            "capabilities": {
                "history": {"status": "ready", "reason": "ok"},
                "legal_chat": {"status": "ready", "reason": "preview_snapshot"},
                "feedback": {"status": "ready", "reason": "ok"},
                "web_research": {"status": "degraded", "reason": "provider_not_configured"},
            },
            "corpus": {"status": "preview_ready"},
        },
        "",
    )


chat_routes.chat_admission_readiness = _deterministic_ready


class BrowserHistoryGateway:
    """Conversation-scoped in-memory history used only by Playwright."""

    def __init__(self) -> None:
        self.messages: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.cases: dict[tuple[str, str], dict[str, Any]] = {}
        self.turns: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.created_at: dict[tuple[str, str], float] = {}
        self.runs: list[dict[str, Any]] = []
        self.next_message_id = 1

    def _new_message(
        self,
        *,
        role: str,
        content: str,
        turn_id: str | None,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        message = {
            "id": self.next_message_id,
            "role": role,
            "content": content,
            "timestamp": now,
            "updated_at": now,
            "turn_id": turn_id,
            "status": status,
            "metadata": dict(metadata or {}),
        }
        self.next_message_id += 1
        return message
    def _conversation(self, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
        key = (user_id, conversation_id)
        self.created_at.setdefault(key, datetime.now(UTC).timestamp())
        return self.messages.setdefault(key, [])

    def _find_message(self, user_id: str, conversation_id: str, message_id: int) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.messages.get((user_id, conversation_id), [])
                if int(item["id"]) == message_id
            ),
            None,
        )

    async def initialize(self) -> None:
        return None

    async def load(self, user_id: str, conversation_id: str, max_messages: int) -> ContextSnapshot:
        key = (user_id, conversation_id)
        conversation = list(self.messages.get(key, []))
        pending_turn_ids = {
            str(item.get("turn_id"))
            for item in conversation
            if item.get("status") in {"pending", "streaming"} and item.get("turn_id")
        }
        # Mirror PersistenceStore.get_recent_history: the current durable
        # turn (including its already-complete user message) is not context
        # for itself, and unfinished turns never enter follow-up rewriting.
        completed = [
            item
            for item in conversation
            if item.get("status") == "complete"
            and str(item.get("turn_id") or "") not in pending_turn_ids
        ]
        return ContextSnapshot(
            history=completed[-max_messages:],
            active_case=self.cases.get(key),
        )

    async def save_exchange(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
    ) -> int:
        conversation = self._conversation(user_id, conversation_id)
        user = self._new_message(
            role="user", content=user_message, turn_id=None, status="complete"
        )
        assistant = self._new_message(
            role="assistant",
            content=assistant_message,
            turn_id=None,
            status="complete",
            metadata=metadata,
        )
        conversation.extend(
            [user, assistant]
        )
        return int(assistant["id"])

    async def begin_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        query: str,
        *,
        mode: str,
        operation: str,
        replay_metadata: dict[str, Any],
        target_assistant_message_id: int | None,
    ) -> dict[str, Any]:
        key = (user_id, conversation_id, turn_id)
        existing = self.turns.get(key)
        if existing is not None:
            return dict(existing)
        conversation = self._conversation(user_id, conversation_id)
        user_message: dict[str, Any] | None = None
        descriptor = dict(replay_metadata)
        if target_assistant_message_id is not None:
            target = self._find_message(user_id, conversation_id, target_assistant_message_id)
            if target is None or target["role"] != "assistant" or target["status"] not in {
                "complete",
                "stopped",
                "failed",
            }:
                raise ValueError("target assistant message is not available for replay")
            target_index = conversation.index(target)
            user_message = next(
                (item for item in reversed(conversation[:target_index]) if item["role"] == "user"),
                None,
            )
            if user_message is None:
                raise ValueError("target assistant message has no preceding user message")
            query = str(user_message["content"])
            descriptor = dict(target.get("metadata", {}).get("replay_metadata") or descriptor)
        else:
            user_message = self._new_message(
                role="user", content=query, turn_id=turn_id, status="complete"
            )
            conversation.append(user_message)
        assistant = self._new_message(
            role="assistant",
            content="",
            turn_id=turn_id,
            status="pending",
            metadata={"replay_metadata": descriptor},
        )
        conversation.append(assistant)
        handle = {
            "turn_id": turn_id,
            "conversation_id": conversation_id,
            "query": query,
            "mode": mode,
            "operation": operation,
            "status": "pending",
            "user_message_id": int(user_message["id"]),
            "assistant_message_id": int(assistant["id"]),
            "target_assistant_message_id": target_assistant_message_id,
            "replay_metadata": descriptor,
        }
        self.turns[key] = handle
        return dict(handle)

    async def update_turn_content(
        self, user_id: str, conversation_id: str, turn_id: str, content: str
    ) -> bool:
        turn = self.turns.get((user_id, conversation_id, turn_id))
        if turn is None or turn["status"] not in {"pending", "streaming"}:
            return False
        assistant = self._find_message(user_id, conversation_id, int(turn["assistant_message_id"]))
        if assistant is None:
            return False
        turn["status"] = "streaming"
        assistant.update(
            content=content,
            status="streaming",
            updated_at=datetime.now(UTC).isoformat(),
        )
        return True

    async def is_turn_cancelled(self, user_id: str, conversation_id: str, turn_id: str) -> bool:
        turn = self.turns.get((user_id, conversation_id, turn_id))
        return bool(turn and turn["status"] == "stopped")

    async def cancel_turn(
        self, user_id: str, conversation_id: str, turn_id: str
    ) -> dict[str, Any] | None:
        turn = self.turns.get((user_id, conversation_id, turn_id))
        if turn is None:
            return None
        if turn["status"] in {"pending", "streaming"}:
            turn["status"] = "stopped"
            assistant = self._find_message(user_id, conversation_id, int(turn["assistant_message_id"]))
            if assistant is not None:
                assistant["status"] = "stopped"
                assistant["metadata"] = {**assistant["metadata"], "turn_status": "stopped"}
        return dict(turn)

    async def finish_turn(
        self,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        *,
        content: str,
        metadata: dict[str, Any] | None,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        turn = self.turns.get((user_id, conversation_id, turn_id))
        if turn is None:
            return None
        assistant = self._find_message(user_id, conversation_id, int(turn["assistant_message_id"]))
        if assistant is None:
            return None
        was_stopped = turn["status"] == "stopped"
        terminal_status = "stopped" if was_stopped else status
        if not (was_stopped and status == "complete"):
            assistant["content"] = content
        assistant["status"] = terminal_status
        assistant["updated_at"] = datetime.now(UTC).isoformat()
        assistant["metadata"] = {
            **assistant["metadata"],
            **dict(metadata or {}),
            "turn_status": terminal_status,
        }
        if error_code:
            assistant["metadata"]["error_code"] = error_code
        turn["status"] = terminal_status
        if terminal_status == "complete" and turn.get("target_assistant_message_id"):
            target = self._find_message(
                user_id, conversation_id, int(turn["target_assistant_message_id"])
            )
            if target is not None:
                target["status"] = "superseded"
        return dict(turn)

    async def save_case(
        self,
        user_id: str,
        conversation_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        saved = {
            **state,
            "status": "collecting" if state.get("missing_facts") else "ready",
        }
        self.cases[(user_id, conversation_id)] = saved
        return saved

    async def clear_case(self, user_id: str, conversation_id: str) -> None:
        case = self.cases.get((user_id, conversation_id))
        if case:
            case.update({"status": "completed", "missing_facts": []})

    async def record_run(self, state: AgentState, started_at: float, ended_at: float) -> None:
        self.runs.append(dict(state))


class DeterministicGenerationGateway(EvidenceGenerationGateway):
    """Keep browser acceptance independent from paid provider credentials.

    Legal lookup still uses the evidence-first formatter from the production
    gateway, while chitchat is deliberately static so the deterministic host
    cannot accidentally call OpenAI in CI or local smoke runs.
    """

    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str:
        return "Xin chào! Tôi có thể hỗ trợ tra cứu pháp luật Việt Nam."

    async def answer(
        self,
        task_type: str,
        query: str,
        documents: list[DocumentRecord],
        facts: dict[str, str],
    ) -> str:
        """Use extractive legal output even when a developer has an API key.

        The deterministic host must exercise the same evidence contract on
        every machine; otherwise a local ``.env`` could silently turn this
        acceptance path into a provider-backed test.
        """

        if task_type in {"case_assessment", "build_compliance_checklist"}:
            return await super().answer(task_type, query, documents, facts)
        return self._compose_legal_route_answer(documents)


history = BrowserHistoryGateway()
chat_routes.cancel_turn_persistent = history.cancel_turn


def _canonical_legal_documents() -> list[DocumentRecord]:
    """Load source-grounded, multi-domain legal fixtures for browser tests."""

    fixture_path = Path(__file__).parent / "fixtures" / "multi_domain_legal_sources.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    documents: list[DocumentRecord] = []
    for row in fixture.get("sources", []):
        number = str(row["document_number"])
        official_title = str(row["document_title"])
        article_anchor = f"Điều {int(row['article'])}"
        source_uri = str(row.get("official_url") or "")
        effective_status = str(row.get("effective_status") or "unknown")
        current_law_support = row.get("current_law_support")
        metadata = {
            "Dieu": article_anchor,
            "Parent_Dieu": article_anchor,
            "legal_anchor": str(row["legal_anchor"]),
            "Document_Number": number,
            "source": official_title,
            "source_title": official_title,
            "Source_Title": official_title,
            "source_file": "tests/fixtures/multi_domain_legal_sources.json",
            "Source_File": "tests/fixtures/multi_domain_legal_sources.json",
            "source_uri": source_uri,
            "Source_URI": source_uri,
            "Corpus_Version": "multi-domain-browser-sources-v1",
            "Corpus_SHA256": "browser-multi-domain-fixtures-v1",
            "Embedding_Profile": EMBEDDING_PROFILE,
            "Effective_From": "",
            "Effective_Status": effective_status,
            "Amendment_Relationship": [],
            "Amendment_Resolution_Status": "",
            "Amendment_Operations": [],
            "Current_Law_Support": current_law_support,
            "official_url": source_uri,
            "legal_domain": str(row["domain"]),
            "corpus_source": "universal_legal",
        }
        documents.append(
            DocumentRecord(
                content=str(row["content"]),
                metadata=metadata,
                document_id=str(row["document_id"]),
                score=None,
                source="legal",
                effective_status=effective_status,
                current_law_support=current_law_support,
            )
        )
    return documents


class PreviewRetrievalGateway(StaticRetrievalGateway):
    """Deterministic preview retrieval over real corpus text.

    Exact legal addresses use the same structural anchor matcher as production.
    Natural queries use SQLite FTS5 BM25 over the loaded source text; this keeps
    browser acceptance repeatable without pretending that it is a production
    embedding or cross-encoder evaluation.
    """

    _checker = staticmethod(legal_relevance_checker(min_rerank_score=0.40))

    def __init__(self, *, legal_documents: list[DocumentRecord]) -> None:
        super().__init__(legal_documents=legal_documents)
        self._fts = sqlite3.connect(":memory:")
        self._fts.execute(
            "CREATE VIRTUAL TABLE preview_legal_fts USING fts5(document_id UNINDEXED, body)"
        )
        self._fts.executemany(
            "INSERT INTO preview_legal_fts(document_id, body) VALUES (?, ?)",
            [
                (
                    document.document_id,
                    " ".join(
                        (
                            str(document.metadata.get("legal_anchor") or ""),
                            str(document.metadata.get("source_title") or ""),
                            document.content,
                        )
                    ),
                )
                for document in legal_documents
            ],
        )
        self._documents_by_id = {
            document.document_id: document for document in legal_documents
        }

    async def legal(self, query):
        documents = await super().legal(query)
        query_text = query.query if hasattr(query, "query") else str(query)
        required_anchors = list(getattr(query, "required_anchors", []) or [])
        if required_anchors:
            anchors, _invalid = parse_required_anchors(required_anchors)
        else:
            anchors = explicit_anchors(query_text)
        if anchors:
            exact = [
                document
                for document in documents
                if any(document_matches_anchor(document, anchor) for anchor in anchors)
            ]
            return exact

        terms = list(
            dict.fromkeys(
                token
                for token in re.findall(r"[\wÀ-ỹĐđ]+", query_text.casefold())
                if len(token) >= 3 and not token.isdigit()
            )
        )
        if not terms:
            return []
        match_query = " OR ".join(f'"{term}"' for term in terms)
        try:
            ranked = self._fts.execute(
                """
                SELECT document_id, bm25(preview_legal_fts) AS rank
                FROM preview_legal_fts
                WHERE preview_legal_fts MATCH ?
                ORDER BY rank ASC
                LIMIT 20
                """,
                (match_query,),
            ).fetchall()
        except sqlite3.Error:
            return []

        selected: list[DocumentRecord] = []
        for document_id, _rank in ranked:
            document = self._documents_by_id.get(str(document_id))
            if document is None:
                continue
            candidate = DocumentRecord.from_dict(document.to_dict())
            candidate.score = None
            candidate.metadata["bm25_rank"] = float(_rank)
            if self._checker(query_text, [candidate]):
                selected.append(candidate)
        return filter_universal_retrieval_neighbors(query_text, selected)


legal_documents = [
    *_canonical_legal_documents(),
]
dependencies = WorkflowDependencies(
    history=history,
    cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="browser-e2e"),
    retrieval=PreviewRetrievalGateway(legal_documents=legal_documents),
    evidence=EvidenceEvaluator(
        min_chars=20,
        relevance_checker=legal_relevance_checker(min_rerank_score=0.40),
    ),
    generation=DeterministicGenerationGateway(),
    planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
)
class DeterministicAdmissionController:
    async def acquire(self, scope: str, **_kwargs: object) -> AdmissionLease:
        return AdmissionLease(scope=scope, token="browser-e2e", ttl_seconds=300)

    async def heartbeat(self, _lease: AdmissionLease, interval_seconds: float) -> None:
        await asyncio.sleep(interval_seconds)

    async def release(self, _lease: AdmissionLease) -> None:
        return None

app = FastAPI(title="Vietnam Legal Agent deterministic browser acceptance")
app.state.admission_controller = DeterministicAdmissionController()
app.state.workflow_runtime = V4WorkflowRuntime(
    dependencies,
    answer_chunk_size=90,
    # Keep the deterministic stop-control window wide enough for a real
    # browser click even when the full Playwright suite is CPU-constrained.
    answer_chunk_delay_s=0.2,
)
app.include_router(chat_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/me")
async def me() -> dict[str, object]:
    """Provide the same identity shape as the local backend auth mode."""

    return {
        "principal_type": "local",
        "principal_id": "dev-local",
        "display_name": "Tài khoản thử nghiệm",
        "email": None,
        "roles": [],
        "scopes": ["chat", "feedback"],
    }


@app.get("/api/v1/ready")
async def ready() -> dict[str, object]:
    """Frontend readiness contract for deterministic browser acceptance."""

    payload, _ = await _deterministic_ready()
    return payload


@app.get("/api/v1/sessions")
async def sessions() -> list[dict[str, Any]]:
    result = []
    for (user_id, conversation_id), messages in history.messages.items():
        if user_id != "dev-local":
            continue
        first_user = next((item for item in messages if item["role"] == "user"), None)
        result.append(
            {
                "id": conversation_id,
                "title": str((first_user or {}).get("content") or "Cuộc trò chuyện")[:72],
                "created_at": history.created_at[(user_id, conversation_id)],
                "message_count": len([item for item in messages if item["status"] != "superseded"]),
            }
        )
    return sorted(result, key=lambda item: item["created_at"], reverse=True)


@app.get("/api/v1/sessions/{session_id}")
async def session_detail(session_id: str) -> dict[str, Any]:
    if ("dev-local", session_id) not in history.messages:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = history.messages.get(("dev-local", session_id), [])
    return {
        "id": session_id,
        "title": next(
            (str(item["content"])[:72] for item in messages if item["role"] == "user"),
            "Cuộc trò chuyện",
        ),
        "created_at": history.created_at.get(("dev-local", session_id), datetime.now(UTC).timestamp()),
        "message_count": len([item for item in messages if item["status"] != "superseded"]),
        "messages": [dict(item) for item in messages if item["status"] != "superseded"],
    }


@app.put("/api/v1/conversations/{conversation_id}/messages/{message_id}/feedback")
async def save_feedback(conversation_id: str, message_id: int, body: dict[str, Any]) -> dict[str, str]:
    message = history._find_message("dev-local", conversation_id, message_id)
    if message is None or message["role"] != "assistant" or message["status"] != "complete":
        return {"status": "error"}
    message["metadata"] = {
        **message["metadata"],
        "feedback": {"rating": int(body["rating"]), "comment": body.get("comment")},
    }
    return {"status": "ok"}
