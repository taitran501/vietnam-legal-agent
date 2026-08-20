"""Answer composition adapters.

Legal lookup keeps the existing streaming LLM prompt through an adapter.  Case
assessment and checklist output is structured and conservative in the MVP so a
missing or unverifiable fact cannot become an invented legal conclusion.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from epr_agent.domain.models import DocumentRecord, TaskType

logger = logging.getLogger(__name__)

_WEB_ARTICLE_RE = re.compile(r"\bđiều\s+(\d+[a-zđ]?)\b", re.IGNORECASE)
_WEB_INSTRUMENT_RE = re.compile(r"\b\d{1,3}/\d{4}/n[dđ]-cp\b", re.IGNORECASE)
_WEB_LEGAL_SIGNALS = (
    "luat",
    "nghi dinh",
    "thong tu",
    "quyet dinh",
    "dieu le",
    "chinh phu",
    "quoc hoi",
    "thu tuong",
    "bo tai chinh",
    "epr",
    "tai che",
    "bao ve moi truong",
)


def _fold_web_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char))
        .replace("đ", "d")
        .replace("Đ", "D")
        .casefold()
        .split()
    )


def _official_domains(raw: str) -> list[str]:
    return sorted({value.strip().casefold().lstrip(".") for value in raw.split(",") if value.strip()})


def _normalize_official_url(raw_url: str, allowed_domains: list[str]) -> str:
    try:
        parsed = urlsplit(raw_url.strip())
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme.casefold() not in {"http", "https"} or not hostname:
        return ""
    if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains):
        return ""
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        )
    )
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit(("https", hostname, path, query, ""))


def _web_result_matches_query(query: str, title: str, excerpt: str, url: str) -> bool:
    folded_query = _fold_web_text(query)
    folded_result = _fold_web_text(f"{title} {excerpt} {url}")
    articles = {_fold_web_text(value) for value in _WEB_ARTICLE_RE.findall(query)}
    if articles and not all(f"dieu {article}" in folded_result for article in articles):
        return False
    instruments = {_fold_web_text(value) for value in _WEB_INSTRUMENT_RE.findall(folded_query)}
    if instruments and not all(value in folded_result for value in instruments):
        return False
    return bool(articles or instruments or any(signal in folded_result for signal in _WEB_LEGAL_SIGNALS))


def _clean_web_excerpt(value: str, limit: int) -> str:
    without_markup = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(without_markup.split())[:limit]


class GenerationGateway(Protocol):
    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str: ...

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str: ...

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]: ...

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str: ...


class LegalAnswerClaim(BaseModel):
    """A claim that is anchored to one or more selected evidence chunks."""

    text: str = Field(min_length=1, max_length=12000)
    evidence_indices: list[int] = Field(min_length=1)


class LegalRouteAnswer(BaseModel):
    """Route-specific, source-faithful answer contract for legal retrieval."""

    claims: list[LegalAnswerClaim] = Field(min_length=1, max_length=6)

    def render(self, documents: list[DocumentRecord]) -> str:
        answer_lines = ["### Trả lời"]
        for claim in self.claims:
            citations = " ".join(f"[{index}]" for index in claim.evidence_indices)
            answer_lines.append(f"{claim.text} {citations}".strip())

        answer_lines.extend(["", "### Nguồn tham khảo:"])
        cited_indices = sorted({index for claim in self.claims for index in claim.evidence_indices})
        for index in cited_indices:
            document = documents[index - 1]
            metadata = document.metadata or {}
            anchor = str(metadata.get("Dieu") or metadata.get("Parent_Dieu") or metadata.get("legal_anchor") or "Văn bản pháp luật")
            title = str(metadata.get("source_title") or metadata.get("Document_Number") or "")
            label = f"{anchor} — {title}".rstrip(" —")
            answer_lines.append(f"- [{index}] {label}")
        return "\n\n".join(answer_lines[:1]) + "\n\n" + "\n\n".join(answer_lines[1:])


def _as_langchain_documents(documents: list[DocumentRecord]) -> list[Any]:
    from langchain_core.documents import Document

    return [Document(page_content=doc.content, metadata=doc.metadata) for doc in documents]


def chitchat_response(question: str, chat_history: str) -> str:
    """Non-streaming chitchat (legacy, kept for backward compatibility)."""

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from epr_agent.infra.llm_instances import get_llm_fast

    _chitchat_system = """Bạn là **Trợ lý Pháp luật Việt Nam** — hệ thống tư vấn và tra cứu pháp luật thông minh, toàn diện.

PHẠM VI NĂNG LỰC & CHỦ ĐỀ CHUYÊN MÔN:
Bạn hỗ trợ tra cứu, đối chiếu căn cứ và hướng dẫn thủ tục trên toàn bộ hệ thống Pháp luật Việt Nam:
- 🏡 **Đất đai & Bất động sản**: Cấp sổ đỏ/sổ hồng, đất khai hoang, tranh chấp, chuyển nhượng (Luật Đất đai 2024).
- 💼 **Lao động & Việc làm**: Hợp đồng lao động, thử việc, tiền lương, kỷ luật, chế độ BHXH/BHYT (Bộ luật Lao động 2019, Luật BHXH).
- ⚖️ **Dân sự & Hợp đồng**: Đặt cọc thuê nhà/mua bán, bồi thường, hợp đồng dân sự, thừa kế (Bộ luật Dân sự 2015).
- 🏢 **Doanh nghiệp & Thương mại**: Thành lập công ty, hộ kinh doanh, cổ phần, phạt hợp đồng (Luật Doanh nghiệp, Luật Thương mại).
- 💰 **Thuế & Tài chính**: Thuế TNCN, giảm trừ gia cảnh, thuế TNDN, thuế GTGT (Luật Quản lý thuế, Luật Thuế TNCN).
- 🌿 **Môi trường & Tuân thủ EPR**: Trách nhiệm tái chế bao bì/sản phẩm, đóng góp Quỹ BVMT, Nghị định 08/2022/NĐ-CP, Luật BVMT 2020.
- 🚗 **Giao thông, Hành chính, PCCC, An toàn thực phẩm**: Quy chuẩn VSATP, phòng cháy chữa cháy, khiếu nại quyết định hành chính.

QUY TẮC PHẢN HỒI:
1. Khi người dùng hỏi "bạn là ai / bạn có thể làm gì / bạn hỗ trợ những gì" → giới thiệu rõ bản thân là **Trợ lý Pháp luật Việt Nam**, tóm tắt các lĩnh vực chính bạn hỗ trợ và gợi ý 2-3 câu hỏi mẫu thực tế.
2. Với câu hỏi chào hỏi / cảm ơn / tạm biệt → phản hồi thân thiện, lịch sự và sẵn sàng hỗ trợ giải đáp bất kỳ vướng mắc pháp luật nào.
3. Với câu hỏi định hướng chung (ví dụ: "cái gì cần quan tâm nhất", "tôi nên bắt đầu từ đâu", "cần lưu ý gì", "hướng dẫn tôi") → Giải thích rằng vấn đề cần quan tâm hàng đầu tùy thuộc vào tư cách người hỏi (Cá nhân, Người lao động, Hộ kinh doanh hay Doanh nghiệp). Nêu ngắn gọn 2-3 điểm mấu chốt (ví dụ: Rà soát điều khoản hợp đồng & đặt cọc, Tuân thủ nghĩa vụ thuế & bảo hiểm lao động, hoặc Bảo đảm pháp lý tài sản/đất đai), sau đó chủ động mời người dùng chia sẻ cụ thể ngành nghề hoặc tình huống đang gặp phải.
4. Luôn đọc kỹ ngữ cảnh lịch sử hội thoại trước khi phản hồi.
5. Giọng điệu khách quan, chuẩn mực, dễ hiểu và tôn trọng người dân/doanh nghiệp.

Lịch sử hội thoại:
{chat_history}"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", _chitchat_system),
        ("human", "{question}"),
    ])
    chain = prompt | get_llm_fast() | StrOutputParser()
    return chain.invoke({
        "question": question,
        "chat_history": chat_history or "(không có hội thoại trước)",
    })


class EvidenceGenerationGateway:
    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str:
        history_text = "\n".join(
            f"{item.get('role', '')}: {item.get('content', '')}" for item in history[-6:]
        )
        return await asyncio.to_thread(chitchat_response, query, history_text)

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        task = TaskType(task_type)
        if task == TaskType.CHITCHAT:
            return await self.chitchat(query, [])
        if task == TaskType.CASE_ASSESSMENT:
            return self._compose_assessment(query, facts, documents)
        if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return self._compose_checklist(query, facts, documents)

        # 1. Primary: Intelligent LLM Legal RAG Synthesis
        synthesized = await self._synthesize_legal_route_answer(query, documents)
        if synthesized:
            return synthesized

        # 2. Fallback: Extractive summary
        return self._compose_legal_route_answer(documents)

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        """Run explicit Tavily research and preserve each returned source.

        The previous fallback manufactured one ``example.invalid`` document
        from an already-synthesised answer.  This route instead returns the
        actual title/URL/snippet so the response can be checked structurally.
        """

        from epr_agent.config import get_settings

        settings = get_settings()
        key = (settings.tavily_api_key or "").strip()
        if not key or key.startswith("your-"):
            return "", []
        domains = _official_domains(settings.web_official_domains)
        if not domains:
            return "", []
        scoped_query = f"{query} Việt Nam văn bản pháp luật chính thức"

        def _search() -> list[dict[str, Any]]:
            from tavily import TavilyClient  # type: ignore[import-untyped]

            result = TavilyClient(api_key=key).search(
                query=scoped_query,
                search_depth="advanced",
                max_results=5,
                include_answer=False,
                include_domains=domains,
            )
            return list(result.get("results") or [])

        try:
            results = await asyncio.to_thread(_search)
        except Exception:
            from epr_agent.infra import metrics

            metrics.track_web_result_rejection("provider_error")
            raise
        documents: list[DocumentRecord] = []
        for index, result in enumerate(results, start=1):
            title = str(result.get("title") or "").strip()
            url = _normalize_official_url(str(result.get("url") or ""), domains)
            content = _clean_web_excerpt(
                str(result.get("content") or ""), settings.web_excerpt_max_chars
            )
            if not title or not url or not content:
                from epr_agent.infra import metrics

                metrics.track_web_result_rejection("invalid_or_untrusted_source")
                continue
            if not _web_result_matches_query(query, title, content, url):
                from epr_agent.infra import metrics

                metrics.track_web_result_rejection("relevance_or_anchor_mismatch")
                continue
            article_match = _WEB_ARTICLE_RE.search(query)
            instrument_match = _WEB_INSTRUMENT_RE.search(_fold_web_text(query))
            document_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
            documents.append(
                DocumentRecord(
                    content=content,
                    document_id=f"web:{index}:{document_id}",
                    source="web",
                    metadata={
                        "source": "web_research",
                        "source_kind": "official_web",
                        "authority": "official",
                        "title": title,
                        "url": url,
                        "official_url": url,
                        "anchor": f"Điều {article_match.group(1)}" if article_match else "",
                        "instrument_number": instrument_match.group(0).upper() if instrument_match else "",
                        "effective_status": "unknown",
                        "amendment_relationship": [],
                    },
                )
            )
        if not documents:
            from epr_agent.infra import metrics

            metrics.track_web_result_rejection("no_accepted_results")
            return "", []
        lines = ["### Nguồn chính thức ngoài corpus", "", "Tôi đã tìm thấy các nguồn chính thức để bạn đối chiếu:"]
        for index, document in enumerate(documents, start=1):
            lines.append(f"- [{index}] {document.metadata['title']} — {document.metadata['url']}")
        lines.append("Các nguồn này nằm ngoài corpus đã duyệt, không được dùng để hoàn tất đánh giá tình huống.")
        return "\n".join(lines), documents

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str:
        """Return a source-only safe answer when the generated citations fail."""

        if not documents:
            return "Tôi chưa thể xác minh câu trả lời vì chưa có tài liệu hỗ trợ."
        extractive = self._compose_legal_route_answer(documents)
        if extractive:
            return extractive
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
            "đối chiếu quy định pháp luật tương ứng với vai trò và tình huống đã nêu. "
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

    @classmethod
    async def _synthesize_legal_route_answer(cls, query: str, documents: list[DocumentRecord]) -> str:
        """Synthesize a structured, high-readability legal advisory answer using LLM RAG."""
        if not documents:
            return ""

        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        from epr_agent.config import get_settings
        from epr_agent.infra.llm_instances import get_llm_smart

        settings = get_settings()
        if not settings.openai_api_key or settings.openai_api_key.startswith("your-"):
            return ""

        context_parts = []
        for index, document in enumerate(documents[:4], start=1):
            metadata = document.metadata or {}
            anchor = str(metadata.get("Dieu") or metadata.get("Parent_Dieu") or metadata.get("legal_anchor") or "Điều luật")
            source_title = str(metadata.get("source_title") or metadata.get("source") or metadata.get("law_ref") or "Văn bản pháp luật")
            raw_content = document.content or ""
            if "\n\n" in raw_content:
                parts = raw_content.split("\n\n", 1)
                if parts[0].startswith("[") and "]" in parts[0]:
                    raw_content = parts[1]
            content = " ".join(raw_content.split())[:4500]
            context_parts.append(f"--- TÀI LIỆU [{index}] ---\nĐiều khoản: {anchor}\nNguồn: {source_title}\nNội dung:\n{content}\n")

        context = "\n".join(context_parts)
        system_prompt = (
            "Bạn là Trợ lý Pháp luật Việt Nam chuyên nghiệp.\n\n"
            "Nhiệm vụ của bạn là đọc kỹ các điều khoản pháp luật được cung cấp dưới đây và trả lời tình huống thực tế của người dùng một cách CHÍNH XÁC, DỄ HIỂU, CÓ CẤU TRÚC RÕ RÀNG.\n\n"
            "CẤU TRÚC BẮT BUỘC CỦA CÂU TRẢ LỜI:\n"
            "### ✅ Kết luận sơ bộ\n"
            "- Trả lời TRỰC DIỆN câu hỏi của người dùng ngay từ 1-2 câu đầu tiên (CÓ THỂ / KHÔNG THỂ / ĐƯỢC PHÉP / KHÔNG ĐƯỢC PHÉP / THUỘC DIỆN NÀO) kèm trích dẫn nguồn [1].\n\n"
            "### 📋 Điều kiện & Phân tích tình huống\n"
            "- Liệt kê các điều kiện cụ thể để người dùng đối chiếu dưới dạng gạch đầu dòng rõ ràng, mỗi ý đều có trích dẫn [1] hoặc [2].\n"
            "- Về đối chiếu mốc năm: Phải đọc kỹ các khoản của điều luật và chọn đúng khoản chứa mốc năm của người dùng (ví dụ: năm 1996 thuộc giai đoạn từ ngày 15/10/1993 đến trước ngày 01/7/2014 theo Khoản 3 Điều 138), tuyệt đối không nhầm sang mốc trước năm 1980 [2].\n\n"
            "### 💰 Nghĩa vụ tài chính & Thủ tục cần làm\n"
            "- Nêu các bước tiếp theo người dùng cần làm (nơi nộp hồ sơ, giấy tờ cần chuẩn bị) [1].\n"
            "- Nêu nghĩa vụ tài chính hoặc lệ phí nếu có theo quy định [1] hoặc [2].\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "- LUÔN gắn chỉ số trích dẫn [1], [2], [3] tương ứng với tài liệu nguồn ở cuối mỗi ý hoặc phát biểu quan trọng.\n"
            "- Tuyệt đối không copy-paste nguyên khối văn bản thô, hãy giải thích bằng ngôn ngữ tự nhiên, súc tích, mạch lạc cho người dân.\n\n"
            "TÀI LIỆU PHÁP LUẬT ĐÃ TRUY XUẤT:\n"
            f"{context}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}"),
        ])

        try:
            chain = prompt | get_llm_smart() | StrOutputParser()
            answer = await asyncio.to_thread(chain.invoke, {"question": query})
            return (answer or "").strip()
        except Exception:
            logger.debug("Legal RAG synthesis failed, falling back to extractive answer", exc_info=True)
            return ""

    @staticmethod
    def _compose_legal_route_answer(documents: list[DocumentRecord]) -> str:
        """Render selected legal chunks without adding unsupported interpretation.

        The prior legacy prompt encouraged a general LLM answer, which could
        add penalties, thresholds, or exceptions that were absent from the
        retrieved chunks. V3's legal lookup contract is extractive-first: each
        displayed claim is source text tied to its exact chunk ID. The bounded
        verifier still runs after this formatter as an independent gate.
        """

        claims: list[LegalAnswerClaim] = []
        for index, document in enumerate(documents, start=1):
            metadata = document.metadata or {}
            anchor = str(metadata.get("Dieu") or metadata.get("Parent_Dieu") or metadata.get("legal_anchor") or "văn bản được truy xuất")
            raw_content = document.content or ""
            if "\n\n" in raw_content:
                parts = raw_content.split("\n\n", 1)
                if parts[0].startswith("[") and "]" in parts[0]:
                    raw_content = parts[1]
            source_text = " ".join(raw_content.split()).strip()
            if not source_text:
                continue
            claims.append(
                LegalAnswerClaim(
                    text=f"Theo {anchor}, văn bản quy định: {source_text}",
                    evidence_indices=[index],
                )
            )
        if not claims:
            return ""
        return LegalRouteAnswer(claims=claims).render(documents)


class StaticGenerationGateway:
    """Injectable generation double for graph and trajectory tests."""

    def __init__(self, answer_text: str = "Theo Điều 77, nội dung được đối chiếu theo tài liệu nguồn [1].") -> None:
        self.answer_text = answer_text
        self.web_text = "Theo nguồn web, nghĩa vụ cần được kiểm tra thêm [1]."
        self.calls: list[str] = []

    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str:
        self.calls.append("chitchat")
        return "Xin chào! Tôi có thể hỗ trợ tra cứu pháp luật Việt Nam."

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        self.calls.append(f"answer:{task_type}")
        if TaskType(task_type) == TaskType.CASE_ASSESSMENT:
            return EvidenceGenerationGateway._compose_assessment(query, facts, documents)
        if TaskType(task_type) == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return EvidenceGenerationGateway._compose_checklist(query, facts, documents)
        return self.answer_text

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        self.calls.append("web")
        return self.web_text, [
            DocumentRecord(
                content="Nguồn công khai mô phỏng dùng riêng cho test.",
                document_id="web-test-1",
                source="web",
                metadata={
                    "source": "web_research",
                    "source_kind": "official_web",
                    "authority": "official",
                    "query": query,
                    "title": "Nguồn công khai kiểm thử",
                    "url": "https://vanban.chinhphu.vn/",
                    "official_url": "https://vanban.chinhphu.vn/",
                },
            )
        ]

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str:
        self.calls.append("repair")
        return "Theo tài liệu nguồn, nội dung cần được đối chiếu theo Điều 77 [1]."
