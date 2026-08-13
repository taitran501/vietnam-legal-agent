"""Answer composition adapters.

Legal lookup keeps the existing streaming LLM prompt through an adapter.  Case
assessment and checklist output is structured and conservative in the MVP so a
missing or unverifiable fact cannot become an invented legal conclusion.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from epr_agent.domain.models import DocumentRecord, TaskType

_WEB_ARTICLE_RE = re.compile(r"\bđiều\s+(\d+[a-zđ]?)\b", re.IGNORECASE)
_WEB_INSTRUMENT_RE = re.compile(r"\b\d{1,3}/\d{4}/n[dđ]-cp\b", re.IGNORECASE)
_WEB_EPR_SIGNALS = (
    "epr",
    "trach nhiem mo rong cua nha san xuat",
    "tai che",
    "bao bi",
    "bao ve moi truong",
    "nghi dinh 08/2022",
    "dong gop tai chinh",
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
    return bool(articles or instruments or any(signal in folded_result for signal in _WEB_EPR_SIGNALS))


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

    text: str = Field(min_length=1, max_length=2200)
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


class EvidenceGenerationGateway:
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

        return self._compose_legal_route_answer(documents)

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        """Run explicit Tavily research and preserve each returned source.

        The previous fallback manufactured one ``example.invalid`` document
        from an already-synthesised answer.  This route instead returns the
        actual title/URL/snippet so the response can be checked structurally.
        """

        from backend.config import get_settings

        settings = get_settings()
        key = (settings.tavily_api_key or "").strip()
        if not key or key.startswith("your-"):
            return "", []
        domains = _official_domains(settings.web_official_domains)
        if not domains:
            return "", []
        scoped_query = f"{query} EPR Việt Nam văn bản pháp luật chính thức"

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

        results = await asyncio.to_thread(_search)
        documents: list[DocumentRecord] = []
        for index, result in enumerate(results, start=1):
            title = str(result.get("title") or "").strip()
            url = _normalize_official_url(str(result.get("url") or ""), domains)
            content = _clean_web_excerpt(
                str(result.get("content") or ""), settings.web_excerpt_max_chars
            )
            if not title or not url or not content:
                continue
            if not _web_result_matches_query(query, title, content, url):
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
            source_text = " ".join((document.content or "").split()).strip()
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
        return "Xin chào! Tôi có thể hỗ trợ tra cứu EPR."

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        self.calls.append(f"answer:{task_type}")
        if TaskType(task_type) == TaskType.ASSESS_EPR_OBLIGATION:
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
