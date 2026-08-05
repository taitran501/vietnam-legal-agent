"""Answer composition adapters.

Legal lookup keeps the existing streaming LLM prompt through an adapter.  Case
assessment and checklist output is structured and conservative in the MVP so a
missing or unverifiable fact cannot become an invented legal conclusion.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from epr_agent.domain.models import DocumentRecord, TaskType


class GenerationGateway(Protocol):
    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str: ...

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str: ...

    async def web(self, query: str) -> tuple[str, DocumentRecord | None]: ...

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str: ...


def _as_langchain_documents(documents: list[DocumentRecord]) -> list[Any]:
    from langchain_core.documents import Document

    return [Document(page_content=doc.content, metadata=doc.metadata) for doc in documents]


class LegacyGenerationGateway:
    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str:
        from backend.core.generation import chitchat_response

        history_text = "\n".join(
            f"{item.get('role', '')}: {item.get('content', '')}" for item in history[-6:]
        )
        return await asyncio.to_thread(chitchat_response, query, history_text)

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        task = TaskType(task_type)
        if task == TaskType.CHITCHAT:
            return await self.chitchat(query, [])
        if task == TaskType.ASSESS_EPR_OBLIGATION:
            return self._compose_assessment(query, facts, documents)
        if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return self._compose_checklist(query, facts, documents)

        from backend.core.generation import stream_faq_answer, stream_legal_answer

        langchain_documents = _as_langchain_documents(documents)
        if documents and documents[0].source == "faq":
            chunks = [chunk async for chunk in stream_faq_answer(query, langchain_documents[0])]
        else:
            chunks = [chunk async for chunk in stream_legal_answer(query, langchain_documents)]
        return "".join(chunks)

    async def web(self, query: str) -> tuple[str, DocumentRecord | None]:
        from backend.core.generation import web_fallback

        answer = await asyncio.to_thread(web_fallback, query)
        if not answer:
            return "", None
        return answer, DocumentRecord(
            content=answer,
            document_id="web-fallback-1",
            source="web",
            metadata={"source": "web_search", "query": query},
        )

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str:
        """Return a source-only safe answer when the generated citations fail."""

        if not documents:
            return "Tôi chưa thể xác minh câu trả lời vì chưa có tài liệu hỗ trợ."
        labels = []
        for index, document in enumerate(documents[:3], start=1):
            label = document.metadata.get("Dieu") or document.metadata.get("Câu_hỏi") or document.source
            labels.append(f"- [{index}] {label}")
        return (
            "Tôi chưa thể xác minh đầy đủ câu trả lời từ các tài liệu đã truy xuất. "
            "Bạn có thể đối chiếu các nguồn sau trước khi đưa ra quyết định:\n"
            + "\n".join(labels)
        )

    @staticmethod
    def _compose_assessment(query: str, facts: dict[str, str], documents: list[DocumentRecord]) -> str:
        fact_text = ", ".join(f"{key}: {value}" for key, value in facts.items())
        source = "[1]"
        return (
            "Đánh giá sơ bộ dựa trên thông tin bạn cung cấp: "
            f"{fact_text}. Theo tài liệu được truy xuất {source}, trường hợp này cần "
            "đối chiếu nghĩa vụ EPR tương ứng với vai trò và nhóm sản phẩm/bao bì. "
            "Đây là đánh giá hỗ trợ tra cứu, không thay thế việc kiểm tra hồ sơ pháp lý đầy đủ."
        )

    @staticmethod
    def _compose_checklist(query: str, facts: dict[str, str], documents: list[DocumentRecord]) -> str:
        return (
            "Checklist sơ bộ cho trường hợp đã cung cấp:\n"
            f"1. Xác nhận vai trò doanh nghiệp ({facts.get('business_role', 'chưa rõ')}) và phạm vi hoạt động [1].\n"
            f"2. Lập danh mục sản phẩm/bao bì ({facts.get('product_or_packaging', 'chưa rõ')}) và vật liệu ({facts.get('material', 'chưa rõ')}) [1].\n"
            "3. Đối chiếu ngưỡng, thời điểm và hình thức thực hiện trong điều khoản nguồn [1].\n"
            "4. Lưu hồ sơ chứng minh số lượng, vật liệu và phương án thực hiện để kiểm tra nội bộ [1]."
        )


class StaticGenerationGateway:
    """Injectable generation double for graph and trajectory tests."""

    def __init__(self, answer_text: str = "Câu trả lời dựa trên tài liệu [1].") -> None:
        self.answer_text = answer_text
        self.web_text = "Thông tin web cần kiểm tra thêm [1]."
        self.calls: list[str] = []

    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str:
        self.calls.append("chitchat")
        return "Xin chào! Tôi có thể hỗ trợ tra cứu EPR."

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        self.calls.append(f"answer:{task_type}")
        if TaskType(task_type) == TaskType.ASSESS_EPR_OBLIGATION:
            return LegacyGenerationGateway._compose_assessment(query, facts, documents)
        if TaskType(task_type) == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return LegacyGenerationGateway._compose_checklist(query, facts, documents)
        return self.answer_text

    async def web(self, query: str) -> tuple[str, DocumentRecord | None]:
        self.calls.append("web")
        return self.web_text, DocumentRecord(
            content=self.web_text,
            document_id="web-1",
            source="web",
            metadata={"source": "web_search", "query": query},
        )

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str:
        self.calls.append("repair")
        return "Đã kiểm tra lại nội dung theo nguồn [1]."
