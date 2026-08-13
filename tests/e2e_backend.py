"""Deterministic FastAPI host for browser-level frontend/backend acceptance.

This process exercises the production chat route, SSE presenter, LangGraph,
React SSE parser, and UI without requiring paid APIs or live infrastructure.
Only tool adapters are deterministic doubles.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.api.routes import chat as chat_routes
from backend.api.routes.chat import router as chat_router
from fastapi import FastAPI

from epr_agent.agent.graph import WorkflowDependencies
from epr_agent.agent.planner import BoundedPlanner
from epr_agent.agent.v4 import V4WorkflowRuntime
from epr_agent.domain.epr_rules import CaseFormResolver, case_fields, missing_fact_keys
from epr_agent.domain.models import DocumentRecord
from epr_agent.domain.v4 import CaseStateV4, FactSource, FactValue
from epr_agent.tools.cache import InMemoryAnswerCache, ScopedAnswerCache
from epr_agent.tools.evidence import EvidenceEvaluator
from epr_agent.tools.generation import EvidenceGenerationGateway
from epr_agent.tools.history import ContextSnapshot
from epr_agent.tools.retrieval import StaticRetrievalGateway


async def _deterministic_ready() -> tuple[dict[str, object], bool]:
    """Keep browser acceptance isolated from Docker/Qdrant readiness.

    The production router correctly checks the versioned corpus before every
    chat request.  This dedicated browser host exercises the same SSE route
    with deterministic adapters, so it supplies the ready contract without
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
                "legal_chat": {"status": "ready", "reason": "preview_unapproved_corpus"},
                "case_workflow": {"status": "ready", "reason": "preview_unapproved_corpus"},
                "feedback": {"status": "ready", "reason": "ok"},
                "web_research": {"status": "degraded", "reason": "provider_not_configured"},
            },
            "corpus": {"status": "preview_ready"},
        },
        True,
    )


chat_routes.readiness_payload = _deterministic_ready


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
        return ContextSnapshot(
            history=list(self.messages.get(key, []))[-max_messages:],
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

    async def get_case(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        return self.cases.get((user_id, conversation_id))

    async def record_run(self, state: dict[str, Any], started_at: float, ended_at: float) -> None:
        self.runs.append(dict(state))


history = BrowserHistoryGateway()
chat_routes.cancel_turn_persistent = history.cancel_turn


def _legal_document(anchor: str) -> DocumentRecord:
    title = "Phụ lục XXII - Tỷ lệ và quy cách tái chế" if anchor == "Phụ lục XXII" else "Nghị định 08/2022/NĐ-CP"
    content = (
        f"{anchor} quy định đối tượng, lộ trình và trách nhiệm tái chế đối với nhà sản xuất, "
        "nhập khẩu sản phẩm hoặc bao bì đưa ra thị trường Việt Nam. "
    ) * 4
    return DocumentRecord(
        content=content,
        metadata={
            "Dieu": anchor if anchor.startswith("Điều") else "",
            "Parent_Dieu": anchor if anchor.startswith("Điều") else "",
            "legal_anchor": anchor,
            "Document_Number": "08/2022/NĐ-CP",
            "source": title,
            "source_title": title,
            "source_file": "data/08_2022_ND-CP_479457.doc",
            "Corpus_Version": "browser-e2e-v4",
            "Corpus_SHA256": "browser-e2e-corpus-v4",
            "Embedding_Profile": "openai-text-embedding-3-small-v1",
            "official_url": "https://vanban.chinhphu.vn/?docid=205092&pageid=27160",
            "effective_status": "active",
            "corpus_as_of_date": "2026-08-14",
        },
        document_id=f"law-{anchor.replace(' ', '-')}",
        score=0.94,
        source="legal",
    )


legal_documents = [_legal_document(f"Điều {article}") for article in range(77, 93)] + [_legal_document("Phụ lục XXII")]
dependencies = WorkflowDependencies(
    history=history,
    cache=ScopedAnswerCache(InMemoryAnswerCache(), corpus_version="browser-e2e"),
    retrieval=StaticRetrievalGateway(legal_documents=legal_documents),
    evidence=EvidenceEvaluator(min_chars=20),
    generation=EvidenceGenerationGateway(),
    planner=BoundedPlanner(max_retrieval_actions=3, max_repairs=1, max_iterations=12),
)
case_form_resolver = CaseFormResolver()

app = FastAPI(title="EPR deterministic browser acceptance")
app.state.workflow_runtime = V4WorkflowRuntime(
    dependencies,
    answer_chunk_size=90,
    answer_chunk_delay_s=0.04,
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


@app.post("/api/v1/case-form/resolve")
async def resolve_case_form(body: dict[str, Any]) -> dict[str, Any]:
    state = case_form_resolver.resolve(
        str(body.get("task_type") or "assess_epr_obligation"),
        fact_updates=dict(body.get("fact_updates") or {}),
    )
    return state.model_dump(mode="json")


@app.get("/api/v1/sessions/{session_id}/case")
async def get_case(session_id: str) -> dict[str, Any] | None:
    return await history.get_case("dev-local", session_id)


@app.patch("/api/v1/sessions/{session_id}/case")
async def update_case(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Deterministic case-panel adapter used by the real browser suite."""

    existing = await history.get_case("dev-local", session_id) or {}
    task_type = str(body.get("task_type") or existing.get("task_type") or "assess_epr_obligation")
    raw_facts = dict(body.get("facts") or {})
    facts = {
        key: FactValue(value=str(value), source=FactSource.CASE_PANEL, verified=True)
        for key, value in raw_facts.items()
        if str(value).strip()
    }
    missing = missing_fact_keys(facts)
    case = CaseStateV4(
        task_type=task_type,
        status="ready" if not missing else "collecting",
        facts=facts,
        missing_facts=missing,
        last_query=str(existing.get("last_query") or ""),
    )
    payload = case.model_dump(mode="json")
    payload["fields"] = [field.model_dump() for field in case_fields(facts, missing)]
    return await history.save_case("dev-local", session_id, payload)


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
