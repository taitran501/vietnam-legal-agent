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
from itertools import pairwise
from typing import Any, Protocol
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from vietnam_legal_agent.domain.models import DocumentRecord, TaskType

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


_NUMBERED_LEGAL_PARAGRAPH_RE = re.compile(r"(?m)^\s*\d{1,2}\.\s+")
_LEGAL_QUALIFIER_RE = re.compile(r"\b(?:trừ|ngoại trừ)\b", re.IGNORECASE)
_LEGAL_CROSS_REFERENCE_RE = re.compile(
    r"\bđiểm\s+([a-z])\s+khoản\s+(\d+)\b|\bkhoản\s+(\d+)\b",
    re.IGNORECASE,
)
_LEGAL_QUALIFIER_STOP_WORDS = {
    "các", "cho", "có", "của", "đến", "điểm", "điều", "được", "hoặc", "khoản",
    "không", "là", "một", "này", "nếu", "như", "phải", "quy", "trong", "trừ",
    "tại", "theo", "thì", "trường", "và", "vào", "về", "với",
}


def _legal_terms(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[\wÀ-ỹĐđ]+", value.casefold())
        if len(token) >= 2 and token not in _LEGAL_QUALIFIER_STOP_WORDS and not token.isdigit()
    ]


def _adjacent_legal_term_pairs(value: str) -> set[str]:
    terms = _legal_terms(value)
    return {f"{left} {right}" for left, right in pairwise(terms)}


def _answer_preserves_source_exceptions(answer: str, documents: list[DocumentRecord]) -> bool:
    """Reject a synthesis that states a qualified duty without its exception.

    Cross-referenced exceptions are resolved from the same retrieved document
    where possible, so a related option in another answer sentence does not
    accidentally qualify an unconditional duty.
    """

    answer_sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", answer or "")
        if sentence.strip()
    ]
    for document in documents:
        source = document.content or ""
        if source.lstrip().startswith("[") and "\n\n" in source:
            source = source.split("\n\n", 1)[1]
        paragraph_starts = list(_NUMBERED_LEGAL_PARAGRAPH_RE.finditer(source))
        paragraphs = (
            [
                source[start.end():paragraph_starts[index + 1].start() if index + 1 < len(paragraph_starts) else len(source)].strip()
                for index, start in enumerate(paragraph_starts)
            ]
            if paragraph_starts
            else [source.strip()]
        )
        for paragraph in paragraphs:
            qualifier = _LEGAL_QUALIFIER_RE.search(paragraph)
            if qualifier is None:
                continue
            duty_text = paragraph[:qualifier.start()]
            duty = re.search(
                r"\b(?:phải|có\s+nghĩa\s+vụ|có\s+trách\s+nhiệm)\b(.+)$",
                duty_text,
                re.IGNORECASE | re.DOTALL,
            )
            duty_terms = set(_legal_terms(duty.group(1) if duty else duty_text))
            if not duty_terms:
                continue

            qualifier_text = paragraph[qualifier.start():]
            reference = _LEGAL_CROSS_REFERENCE_RE.search(qualifier_text)
            exception_text = qualifier_text
            reference_label = ""
            if reference:
                if reference.group(1):
                    letter, paragraph_number = reference.group(1).casefold(), reference.group(2)
                    reference_label = f"điểm {letter} khoản {paragraph_number}"
                    point_re = re.compile(
                        rf"(?m)(?<!\w){re.escape(letter)}\)\s*(.+?)(?=\n\s*[a-z]\)\s|\n\s*\d{{1,2}}\.\s|\Z)",
                        re.IGNORECASE | re.DOTALL,
                    )
                    resolved = point_re.search(source)
                    if resolved:
                        exception_text = resolved.group(1)
                else:
                    reference_label = f"khoản {reference.group(3)}"

            exception_pairs = _adjacent_legal_term_pairs(exception_text)
            if reference and reference.group(1):
                resolved_terms = _legal_terms(exception_text)
                exception_pairs = {
                    f"{left} {right}"
                    for left, right in pairwise(resolved_terms[:6])
                }
            reference_casefold = reference_label.casefold()
            duty_sentences = [
                sentence
                for sentence in answer_sentences
                if len(duty_terms.intersection(_legal_terms(sentence))) >= min(2, len(duty_terms))
            ]
            for sentence in duty_sentences:
                sentence_folded = sentence.casefold()
                has_qualifier = bool(_LEGAL_QUALIFIER_RE.search(sentence))
                states_referenced_case = bool(reference_casefold and reference_casefold in sentence_folded)
                states_resolved_exception = any(pair in sentence_folded for pair in exception_pairs)
                if reference and not (states_referenced_case or states_resolved_exception):
                    return False
                if not reference and not has_qualifier:
                    return False

    return True


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
            return self._compose_assessment(query, facts, documents)
        if task == TaskType.BUILD_COMPLIANCE_CHECKLIST:
            return self._compose_checklist(query, facts, documents)

        # 1. Primary: Intelligent LLM Legal RAG Synthesis
        synthesized = await self._synthesize_legal_route_answer(query, documents)
        if synthesized:
            if _answer_preserves_source_exceptions(synthesized, documents):
                return synthesized
            logger.info("Legal synthesis omitted a source exception; using extractive answer")

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
            "Bạn là trợ lý tra cứu pháp luật Việt Nam. Trả lời trực tiếp đúng câu hỏi bằng tiếng Việt rõ ràng, ngắn gọn.\n\n"
            f"{source_scope_instruction}"
            "Chỉ dùng thông tin có trong tài liệu được cung cấp. Gắn chỉ số [n] vào từng nhận định pháp lý và chỉ trích dẫn tài liệu thực sự hỗ trợ nhận định đó. Giữ nguyên điều kiện, ngoại lệ, ngưỡng, thời điểm, đối tượng áp dụng và các lựa chọn thay thế nêu trong nguồn; không biến nghĩa vụ có điều kiện thành nghĩa vụ chung. Khi nguồn dẫn chiếu sang điểm hoặc khoản khác, hãy đọc phần được dẫn chiếu rồi nêu ngắn gọn ngoại lệ ngay trong cùng câu với nghĩa vụ. Nếu không thể xác định ngoại lệ, bỏ nhận định tuyệt đối đó hoặc nói rõ giới hạn. Không tự thêm thủ tục, cơ quan tiếp nhận, giấy tờ, phí, thời hạn, ngoại lệ hoặc hướng xử lý nếu tài liệu không nêu. Không suy đoán hiệu lực hiện hành hay sửa đổi về sau khi nguồn không xác nhận.\n\n"
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

    def __init__(self, answer_text: str | None = None) -> None:
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

    async def repair(self, answer: str, documents: list[DocumentRecord], task_type: str) -> str:
        self.calls.append("repair")
        return EvidenceGenerationGateway._compose_legal_route_answer(documents)
