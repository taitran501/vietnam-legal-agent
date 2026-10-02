"""Answer composition adapters.

Legal lookup keeps the existing streaming LLM prompt through an adapter. Case
assessment and checklist output is structured and conservative in the MVP so a
missing or unverifiable fact cannot become an invented legal conclusion.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from vietnam_legal_agent.domain.models import DocumentRecord, TaskType
from vietnam_legal_agent.tools.evidence import (
    auto_anchor_citations_in_answer,
    propagate_list_item_citations,
    split_answer_sentences,
    verify_citations,
)

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
    "toa an",
    "vien kiem sat",
    "bo tu phap",
    "bo cong an",
    "bo tai chinh",
    "bo lao dong",
    "bo tai nguyen",
    "hop dong",
    "lao dong",
    "dat dai",
    "dan su",
    "hinh su",
    "doanh nghiep",
    "thue",
    "hon nhan",
    "giao thong",
    "boi thuong",
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


class _VisibleHTMLTextParser(HTMLParser):
    """Extract bounded readable page text without retaining script or style data."""

    _BLOCK_TAGS = frozenset({"article", "br", "div", "h1", "h2", "h3", "h4", "li", "p", "section", "td", "tr"})
    _IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if self._ignored_depth:
            if tag in self._IGNORED_TAGS:
                self._ignored_depth += 1
            return
        if tag in self._IGNORED_TAGS:
            self._ignored_depth = 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            if tag in self._IGNORED_TAGS:
                self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


_PAGE_TEXT_STOPWORDS = frozenset({
    "bao", "bi", "boi", "cac", "can", "cho", "co", "cua", "de", "den", "duoc",
    "gi", "hay", "la", "luat", "ma", "mot", "moi", "nay", "ngay", "neu", "nhu",
    "ra", "tai", "theo", "thi", "trong", "tu", "va", "ve", "voi", "y",
})
_PAGE_TEXT_PHRASES = (
    "trach nhiem tai che",
    "bao bi",
    "nha san xuat",
    "dua ra thi truong",
    "tu ngay",
    "co hieu luc",
    "ngoai le",
    "khong phai thuc hien",
)


def _select_official_page_text(query: str, raw_html: str, max_chars: int) -> str:
    parser = _VisibleHTMLTextParser()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed official HTML falls back to the search excerpt
        return ""

    paragraphs: list[str] = []
    for raw_paragraph in "".join(parser.parts).splitlines():
        paragraph = " ".join(raw_paragraph.split()).strip()
        if len(paragraph) < 35:
            continue
        if len(paragraph) > 1200:
            paragraphs.extend(
                segment.strip()
                for segment in re.split(r"(?<=[.;:!?])\s+", paragraph)
                if len(segment.strip()) >= 35
            )
        else:
            paragraphs.append(paragraph)
    if not paragraphs:
        return ""

    folded_query = _fold_web_text(query)
    query_terms = [
        term
        for term in re.findall(r"[a-z0-9]+", folded_query)
        if len(term) >= 3 and term not in _PAGE_TEXT_STOPWORDS
    ]
    query_phrases = [phrase for phrase in _PAGE_TEXT_PHRASES if phrase in folded_query]
    ranked: list[tuple[int, int, str]] = []
    for index, paragraph in enumerate(paragraphs):
        folded_paragraph = _fold_web_text(paragraph)
        score = sum(1 for term in set(query_terms) if term in folded_paragraph)
        score += 3 * sum(1 for phrase in query_phrases if phrase in folded_paragraph)
        if score:
            ranked.append((score, index, paragraph))

    if not ranked:
        ranked = [(0, index, paragraph) for index, paragraph in enumerate(paragraphs)]
    selected_indices = {index for _, index, _ in sorted(ranked, key=lambda item: (-item[0], item[1]))[:8]}
    # Include adjacent paragraphs to preserve nearby conditions and exceptions.
    selected_indices.update(index - 1 for index in tuple(selected_indices) if index > 0)
    selected_indices.update(index + 1 for index in tuple(selected_indices) if index + 1 < len(paragraphs))

    output: list[str] = []
    used = 0
    for index in sorted(selected_indices):
        paragraph = paragraphs[index]
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(paragraph) > remaining:
            if not output:
                output.append(paragraph[:remaining])
            break
        output.append(paragraph)
        used += len(paragraph) + 1
    return "\n".join(output)


async def _fetch_official_page_text(
    url: str,
    query: str,
    allowed_domains: list[str],
    *,
    max_chars: int = 4000,
) -> str:
    """Best-effort fetch of readable text from an allowlisted official HTML page."""

    safe_url = _normalize_official_url(url, allowed_domains)
    if not safe_url:
        return ""
    try:
        import httpx

        timeout = httpx.Timeout(4.0, connect=2.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "VietnamLegalAgent/1.0"},
        ) as client:
            current_url = safe_url
            for _ in range(3):
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        redirect_url = _normalize_official_url(urljoin(current_url, location), allowed_domains)
                        if not redirect_url or redirect_url == current_url:
                            return ""
                        current_url = redirect_url
                        continue
                    if response.status_code != 200:
                        return ""
                    content_type = response.headers.get("content-type", "").casefold()
                    if content_type and "html" not in content_type:
                        return ""

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        remaining = 1_000_000 - len(body)
                        if remaining <= 0:
                            break
                        body.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            break
                    raw_html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                    return _select_official_page_text(query, raw_html, max_chars)
    except Exception as exc:  # noqa: BLE001 - source fetch failure falls back to the search snippet
        logger.debug("Official source page fetch skipped (%s)", type(exc).__name__)
    return ""


def _search_duckduckgo_free(query: str, domains: list[str]) -> list[dict[str, Any]]:
    """Free web search fallback querying public search engine with domain scoping."""
    import html

    import httpx

    site_filter = " OR ".join(f"site:{d}" for d in domains[:3]) if domains else ""
    full_query = f"{query} {site_filter}".strip() if site_filter else query
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    results: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": full_query}, headers=headers)
            if resp.status_code == 200:
                raw_html = resp.text
                blocks = re.findall(r'<div class="[^"]*result__body[^"]*">([\s\S]*?)</div>\s*</div>', raw_html)
                for block in blocks:
                    title_m = re.search(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</a>', block) or re.search(r'<a[^>]+class="[^"]*result__url[^"]*"[^>]*>([\s\S]*?)</a>', block)
                    link_m = re.search(r'<a[^>]+href="([^"]+)"', block)
                    snippet_m = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)</(?:a|td|div)>', block)

                    raw_href = link_m.group(1) if link_m else ""
                    if "uddg=" in raw_href:
                        parsed_href = urlsplit(raw_href)
                        qs = parse_qs(parsed_href.query)
                        actual_url = unquote(qs.get("uddg", [""])[0])
                    else:
                        actual_url = raw_href
                    if actual_url and not actual_url.startswith("http"):
                        actual_url = f"https://{actual_url}"

                    raw_title = re.sub(r"<[^>]+>", "", title_m.group(1) if title_m else "")
                    title = html.unescape(" ".join(raw_title.split()))
                    raw_snippet = re.sub(r"<[^>]+>", "", snippet_m.group(1) if snippet_m else "")
                    snippet = html.unescape(" ".join(raw_snippet.split()))

                    if title and actual_url:
                        results.append({
                            "title": title,
                            "url": actual_url,
                            "content": snippet,
                        })
                        if len(results) >= 5:
                            break
    except Exception as exc:  # noqa: BLE001 - optional web search failure should not crash agent
        logger.warning("Free web search provider encountered error: %s", exc)
    return results


class GenerationGateway(Protocol):
    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str: ...

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str: ...

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]: ...

    async def repair(
        self,
        answer: str,
        documents: list[DocumentRecord],
        task_type: str,
        *,
        query: str = "",
    ) -> str: ...


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
            sentences = split_answer_sentences(claim.text) or [claim.text]
            answer_lines.extend(f"{sentence} {citations}".strip() for sentence in sentences)

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


_MAX_EXTRACTIVE_SOURCE_CHARS = 10_000


def _as_langchain_documents(documents: list[DocumentRecord]) -> list[Any]:
    from langchain_core.documents import Document

    return [Document(page_content=doc.content, metadata=doc.metadata) for doc in documents]


def chitchat_response(question: str, chat_history: str) -> str:
    """Non-streaming chitchat (legacy, kept for backward compatibility)."""

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from vietnam_legal_agent.infra.llm_instances import get_llm_fast

    _chitchat_system = """Bạn là trợ lý tra cứu pháp luật Việt Nam.

Trả lời đúng trọng tâm, bằng tiếng Việt tự nhiên và ngắn gọn. Với lời chào hoặc cảm ơn, đáp lại lịch sự trong một câu. Nếu người dùng hỏi bạn có thể giúp gì, nói rằng bạn có thể tra cứu và giải thích các văn bản có trong nguồn dữ liệu hiện có; không tuyên bố bao quát toàn bộ pháp luật, không liệt kê lĩnh vực chưa được kiểm chứng, và không tự đưa câu hỏi mẫu. Mời người dùng nêu vấn đề cụ thể nếu phù hợp.

Không trả lời nội dung pháp lý như thể đã tra cứu nguồn khi lượt này chưa có căn cứ. Không bịa điều luật, thủ tục, mức phí hoặc phạm vi hỗ trợ. Dùng lịch sử hội thoại để hiểu lời nhắn ngắn; không lặp lại thông tin không cần thiết.

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
            synthesized = await self._synthesize_legal_route_answer(query, documents)
            if synthesized:
                return synthesized
            return self._compose_legal_route_answer(documents) or self._compose_assessment(query, facts, documents)
        if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return self._compose_checklist(query, facts, documents)

        # 1. Primary: Intelligent LLM Legal RAG Synthesis
        synthesized = await self._synthesize_legal_route_answer(query, documents)
        if synthesized:
            return synthesized

        # 2. Fallback: Extractive summary
        return self._compose_legal_route_answer(documents)

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        """Search allowlisted legal sites and enrich snippets with official page text."""

        from vietnam_legal_agent.config import get_settings

        settings = get_settings()
        domains = _official_domains(settings.web_official_domains)
        if not domains:
            return "", []
        scoped_query = f"{query} Việt Nam văn bản pháp luật chính thức"

        key = (getattr(settings, "tavily_api_key", None) or "").strip()
        use_tavily = bool(key and not key.startswith("your-"))

        def _search() -> list[dict[str, Any]]:
            if use_tavily:
                from tavily import TavilyClient  # type: ignore[import-untyped]

                result = TavilyClient(api_key=key).search(
                    query=scoped_query,
                    search_depth="advanced",
                    max_results=5,
                    include_answer=False,
                    include_domains=domains,
                )
                return list(result.get("results") or [])
            # Free search harness provider fallback
            return _search_duckduckgo_free(scoped_query, domains)

        try:
            results = await asyncio.to_thread(_search)
        except Exception:
            from vietnam_legal_agent.infra import metrics

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
                from vietnam_legal_agent.infra import metrics

                metrics.track_web_result_rejection("invalid_or_untrusted_source")
                continue
            if not _web_result_matches_query(query, title, content, url):
                from vietnam_legal_agent.infra import metrics

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
                        "content_origin": "search_result_snippet",
                        "anchor": f"Điều {article_match.group(1)}" if article_match else "",
                        "instrument_number": instrument_match.group(0).upper() if instrument_match else "",
                        "effective_status": "unknown",
                        "amendment_relationship": [],
                    },
                )
            )
        if not documents:
            from vietnam_legal_agent.infra import metrics

            metrics.track_web_result_rejection("no_accepted_results")
            return "", []

        page_text_limit = min(4000, max(2000, int(settings.web_excerpt_max_chars)))
        page_texts = await asyncio.gather(
            *(
                _fetch_official_page_text(
                    str(document.metadata.get("official_url") or ""),
                    query,
                    domains,
                    max_chars=page_text_limit,
                )
                for document in documents
            ),
            return_exceptions=True,
        )
        for document, page_text in zip(documents, page_texts):
            if isinstance(page_text, str) and page_text.strip():
                document.content = page_text
                document.metadata["content_origin"] = "official_html_page"

        lines = ["### Nguồn chính thức ngoài corpus", "", "Tôi đã tìm thấy các nguồn chính thức để bạn đối chiếu:"]
        for index, document in enumerate(documents, start=1):
            lines.append(f"- [{index}] {document.metadata['title']} — {document.metadata['url']}")
        lines.append("Các nguồn này nằm ngoài corpus đã duyệt, không được dùng để hoàn tất đánh giá tình huống.")
        return "\n".join(lines), documents

    async def repair(
        self,
        answer: str,
        documents: list[DocumentRecord],
        task_type: str,
        *,
        query: str = "",
    ) -> str:
        """Regenerate a rejected answer with the original question and evidence."""

        if not documents:
            return "Tôi chưa thể xác minh câu trả lời vì chưa có tài liệu hỗ trợ."
        if query.strip():
            try:
                repaired = await self._repair_legal_route_answer(query, answer, documents)
                repaired = auto_anchor_citations_in_answer(repaired or "", documents)
                repaired = propagate_list_item_citations(repaired)
                if repaired.strip():
                    return repaired
            except Exception as exc:  # noqa: BLE001 - fall back to source-only text, then final verification
                logger.warning("Evidence-grounded answer repair failed: %s", type(exc).__name__)
        citation_repaired = propagate_list_item_citations(answer)
        valid, _citations, _reason = verify_citations(citation_repaired, documents, task_type)
        if valid:
            # Prefer the user's direct answer after repairing citation
            # formatting; the independent claim verifier still checks it.
            return citation_repaired
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

    @classmethod
    async def _repair_legal_route_answer(
        cls,
        query: str,
        answer: str,
        documents: list[DocumentRecord],
    ) -> str:
        """Rewrite a rejected answer with the user's question and selected evidence in view."""

        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        from vietnam_legal_agent.config import get_settings
        from vietnam_legal_agent.infra.llm_instances import get_llm_smart

        settings = get_settings()
        if not settings.openai_api_key or settings.openai_api_key.startswith("your-"):
            return ""

        context_parts: list[str] = []
        for index, document in enumerate(documents[:8], start=1):
            metadata = document.metadata or {}
            anchor = str(
                metadata.get("Dieu")
                or metadata.get("Parent_Dieu")
                or metadata.get("legal_anchor")
                or "văn bản được truy xuất"
            )
            title = str(metadata.get("source_title") or metadata.get("source") or metadata.get("law_ref") or "")
            context_parts.append(f"[{index}] {anchor} — {title}\n{(document.content or '')[:8000]}")

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "Bạn là trợ lý tra cứu pháp luật Việt Nam đang sửa một bản nháp đã không qua kiểm chứng. "
                        "Hãy trả lời lại đúng câu hỏi ban đầu, chỉ dựa trên evidence được đưa vào. Bản nháp cũ có thể "
                        "sai; không cần giữ lại nội dung sai. Đối chiếu đúng chủ thể, sự kiện, giai đoạn thủ tục, "
                        "điều kiện và kết quả người dùng hỏi. Một quy định cho giai đoạn sau không thay thế quy định "
                        "cho giai đoạn ban đầu. Nếu evidence không trả lời một phần, nêu rõ giới hạn đó và chỉ trả lời "
                        "phần có căn cứ; không suy đoán. Với ngưỡng số lượng hoặc thời gian, áp dụng đúng so sánh "
                        "giữa ngưỡng trong nguồn và dữ kiện câu hỏi; giới hạn kết luận vào điều khoản đó. Không viết "
                        "kết luận chung rằng không có hoặc có mọi khoản bổ sung khi nguồn chỉ xác nhận một căn cứ; "
                        "nêu rõ phần nào chưa thể xác định. Gắn citation [n] đúng số evidence vào từng câu pháp lý và "
                        "từng mục danh sách. Nếu một điều khoản trực tiếp quy định sự kiện và kết quả người dùng hỏi, "
                        "hãy dùng điều khoản đó làm câu trả lời chính, cite đúng nguồn, và trả lời một lần trong câu "
                        "ngắn; không nối thêm kết luận 'do đó' chỉ để lặp lại quy tắc. Chỉ kết luận áp dụng cho tình "
                        "huống người dùng khi đủ điều kiện trong nguồn và dữ kiện họ đã nêu. Không viết [n] placeholder; "
                        "chỉ dùng chỉ số citation thực tế. Trả về câu "
                        "trả lời tiếng Việt ngắn gọn, không thêm lời dẫn về quá trình sửa."
                    ),
                ),
                (
                    "human",
                    (
                        "CÂU HỎI NGƯỜI DÙNG:\n{query}\n\n"
                        "BẢN NHÁP BỊ TỪ CHỐI:\n{answer}\n\n"
                        "EVIDENCE ĐÃ TRUY XUẤT:\n{context}"
                    ),
                ),
            ]
        )
        result = await (prompt | get_llm_smart() | StrOutputParser()).ainvoke(
            {
                "query": query[:3000],
                "answer": (answer or "")[:12000],
                "context": "\n\n".join(context_parts),
            }
        )
        return str(result or "").strip()

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
        """Use retrieved provisions as a fallback instead of inventing checklist steps."""
        del query, facts
        return EvidenceGenerationGateway._compose_legal_route_answer(documents)

    @classmethod
    async def _synthesize_legal_route_answer(cls, query: str, documents: list[DocumentRecord]) -> str:
        """Synthesize a structured, high-readability legal advisory answer using LLM RAG."""
        if not documents:
            return ""

        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        from vietnam_legal_agent.config import get_settings
        from vietnam_legal_agent.infra.llm_instances import get_llm_smart

        settings = get_settings()
        if not settings.openai_api_key or settings.openai_api_key.startswith("your-"):
            return ""

        from vietnam_legal_agent.tools.evidence import is_explicit_source_version_lookup

        source_scope_instruction = ""
        if is_explicit_source_version_lookup(query, documents, TaskType.LEGAL_LOOKUP):
            source_scope_instruction = (
                "Phạm vi nguồn: Chỉ mô tả điều khoản trong phiên bản nguồn được truy xuất. "
                "Nêu rõ đây là nội dung của nguồn đó và hiệu lực hiện hành chưa được xác minh; "
                "không diễn đạt như kết luận rằng đây chắc chắn là quy định đang áp dụng.\n\n"
            )

        context_parts = []
        # Keep the complete route evidence set in synthesis. Truncating here
        # can discard a directly relevant source selected from a later query.
        for index, document in enumerate(documents[:8], start=1):
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
            "Bạn là trợ lý tra cứu pháp luật Việt Nam. Trả lời trực tiếp đúng câu hỏi bằng tiếng Việt rõ ràng, ngắn gọn; giữ ngôn ngữ người dùng, không chuyển câu trả lời tiếng Việt sang tiếng Anh.\n\n"
            f"{source_scope_instruction}"
            "Chỉ dùng thông tin có trong tài liệu được cung cấp. Gắn chỉ số trích dẫn thực tế như [1], [2] theo đúng thứ tự tài liệu ở trên vào từng câu có nhận định pháp lý; mỗi câu pháp lý và từng mục đánh số/gạch đầu dòng cần citation riêng ngay trên mục đó, không dồn citation ở cuối danh sách; tuyệt đối không viết placeholder như [n]. Khi tóm tắt một danh sách, lược bỏ dòng chỉ nói chung rằng còn quyền/nghĩa vụ khác theo luật hoặc điều lệ nếu người dùng không yêu cầu nguyên văn hay liệt kê đầy đủ; không diễn giải dòng khái quát đó thành một quyền hoặc nghĩa vụ cụ thể. Không biến nghĩa vụ của một chủ thể thành quyền hoặc chế tài của chủ thể khác nếu nguồn không nêu quan hệ đó. Giữ nguyên điều kiện, ngoại lệ, ngưỡng, thời điểm, đối tượng áp dụng và các lựa chọn thay thế nêu trong nguồn; không biến nghĩa vụ có điều kiện thành nghĩa vụ chung. Khi nguồn và câu hỏi đều nêu một ngưỡng số lượng hoặc thời gian, hãy so sánh trực tiếp hai giá trị, kết luận trong phạm vi nghĩa vụ gắn với ngưỡng đó và giữ điều kiện có thể làm thay đổi kết quả. Ví dụ logic: nếu nghĩa vụ chỉ phát sinh từ N ngày trở lên và câu hỏi nêu M ngày với M < N, hãy nói nghĩa vụ gắn với ngưỡng đó chưa phát sinh; không suy rộng thành khẳng định rằng không có biện pháp pháp lý nào khác. Không kết luận chung rằng một bên không phải trả thêm bất kỳ khoản nào nếu nguồn chỉ mô tả một căn cứ; hãy giới hạn kết luận vào căn cứ đã trích dẫn và nói rõ khi nguồn chưa làm rõ căn cứ riêng khác. Khi nguồn dẫn chiếu sang điểm hoặc khoản khác, hãy đọc phần được dẫn chiếu rồi nêu ngắn gọn ngoại lệ ngay trong cùng câu với nghĩa vụ. Nếu không thể xác định ngoại lệ, bỏ nhận định tuyệt đối đó hoặc nói rõ giới hạn. Không tự thêm thủ tục, cơ quan tiếp nhận, giấy tờ, phí, thời hạn, ngoại lệ hoặc hướng xử lý nếu tài liệu không nêu. Không suy đoán hiệu lực hiện hành hay sửa đổi về sau khi nguồn không xác nhận.\n\n"
            "Không tự gán vai trò của người dùng hoặc bên còn lại vào thuật ngữ pháp lý trong nguồn. Ví dụ, chỉ gọi ai là bên đặt cọc, bên nhận đặt cọc, người lao động, người sử dụng lao động, bên mua hoặc bên bán khi câu hỏi và tài liệu xác định rõ vai trò đó. Nếu chưa rõ, dùng thuật ngữ pháp lý trung tính và nêu điều kiện áp dụng thay vì đoán.\n\n"
            "Trước khi soạn, đối chiếu tiêu đề và điều kiện áp dụng của từng nguồn với đúng giai đoạn, thủ tục và tình huống trong câu hỏi. Nếu nguồn nói về một giai đoạn khác (ví dụ thay đổi quyết định sau này thay vì quyết định ban đầu), không dùng quy tắc đó làm câu trả lời chính. Chỉ nêu quy tắc gần kề nếu nói rõ giới hạn áp dụng.\n\n"
            "Giữ nguyên phạm vi của chủ thể, loại giao dịch, ngành nghề, tư cách pháp lý và điều kiện được nêu trong nguồn; không khái quát quy tắc giới hạn cho một nhóm thành quyền/nghĩa vụ chung. Khi điều khoản dẫn chiếu hoặc quy định mặc định cho trường hợp không có thỏa thuận, đọc đúng nội dung được cung cấp và không tự thêm điều kiện từ quy định khác. Gắn citation vào nguồn trực tiếp hỗ trợ nhận định đó.\n\n"
            "Với câu hỏi đơn giản về một quyền, nghĩa vụ hoặc kết quả pháp lý, ưu tiên điều khoản trực tiếp quy định sự kiện và kết quả đó. Trả lời bằng quy tắc trực tiếp trong một câu có citation; không thêm một câu kết luận 'do đó' chỉ để lặp lại cùng quy tắc. Chỉ áp dụng quy tắc cho tình huống người dùng khi nguồn nêu đủ điều kiện và dữ kiện họ đã cung cấp đáp ứng các điều kiện ấy.\n\n"
            "Với khoản tiền gồm nhiều cấu phần, phân biệt khoản hoàn gốc với phần phải trả thêm. Giữ đủ từng cấu phần và nêu đúng tổng số; không lược bỏ khoản tiền bổ sung rồi phủ nhận kết quả tương đương.\n\n"
            "Nếu người dùng chỉ hỏi một điều khoản, tóm tắt đúng phần liên quan trong 1–4 câu; không tạo các mục kết luận, thủ tục hay tài chính nếu không cần. Chỉ dùng tiêu đề khi câu hỏi có nhiều vấn đề cần phân tích. Nếu nguồn không trả lời phần được hỏi, nêu rõ giới hạn đó thay vì suy diễn.\n\n"
            "TÀI LIỆU ĐÃ TRUY XUẤT:\n"
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
        oversized_indices: list[int] = []
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
            if len(source_text) > _MAX_EXTRACTIVE_SOURCE_CHARS:
                oversized_indices.append(index)
                continue
            if len(claims) >= 6:
                continue
            claims.append(
                LegalAnswerClaim(
                    text=f"Theo {anchor}, văn bản quy định: {source_text}",
                    evidence_indices=[index],
                )
            )
        if not claims:
            if oversized_indices:
                references = " ".join(f"[{index}]" for index in oversized_indices[:8])
                return (
                    "Tôi tìm thấy tài liệu liên quan, nhưng phần trích xuất quá dài để tóm tắt "
                    "chính xác khi bộ tạo câu trả lời không khả dụng. Bạn có thể mở nguồn để xem "
                    f"nguyên văn: {references}"
                )
            return ""
        return LegalRouteAnswer(claims=claims).render(documents)


class StaticGenerationGateway:
    """Injectable generation double for graph and trajectory tests."""

    def __init__(self, answer_text: str | None = None) -> None:
        self.answer_text = answer_text
        self.web_text = "Theo nguồn web, nghĩa vụ cần được kiểm tra thêm [1]."
        self.calls: list[str] = []
        self.repair_queries: list[str] = []

    async def chitchat(self, query: str, history: list[dict[str, Any]]) -> str:
        self.calls.append("chitchat")
        return "Xin chào! Tôi có thể hỗ trợ tra cứu pháp luật Việt Nam."

    async def answer(self, task_type: str, query: str, documents: list[DocumentRecord], facts: dict[str, str]) -> str:
        self.calls.append(f"answer:{task_type}")
        if TaskType(task_type) == TaskType.CASE_ASSESSMENT:
            return EvidenceGenerationGateway._compose_assessment(query, facts, documents)
        if TaskType(task_type) == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return EvidenceGenerationGateway._compose_checklist(query, facts, documents)
        if self.answer_text is not None:
            return self.answer_text
        return EvidenceGenerationGateway._compose_legal_route_answer(documents)

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

    async def repair(
        self,
        answer: str,
        documents: list[DocumentRecord],
        task_type: str,
        *,
        query: str = "",
    ) -> str:
        self.calls.append("repair")
        self.repair_queries.append(query)
        return EvidenceGenerationGateway._compose_legal_route_answer(documents)
