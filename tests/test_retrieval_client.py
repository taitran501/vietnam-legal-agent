from __future__ import annotations

from types import SimpleNamespace

import backend.config
import backend.core.retrieval
import pytest

from epr_agent.domain.models import DocumentRecord
from epr_agent.retrieval import universal_retriever as universal_module
from epr_agent.tools.retrieval import QdrantLegalRetrievalGateway, StaticRetrievalGateway


@pytest.mark.asyncio
async def test_legal_gateway_has_no_faq_surface() -> None:
    gateway = StaticRetrievalGateway(
        legal_documents=[DocumentRecord(content="Điều 77", metadata={"Dieu": "Điều 77"}, document_id="77", source="legal")]
    )

    documents = await gateway.legal("Điều 77 quy định gì?")

    assert [document.document_id for document in documents] == ["77"]
    assert gateway.calls == [("legal", "Điều 77 quy định gì?")]
    assert not hasattr(gateway, "faq")


@pytest.mark.asyncio
async def test_universal_retrieval_is_not_an_implicit_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backend.config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_universal_retrieval=False,
            law_citation_label="Vietnamese legal corpus",
            corpus_version="test-corpus",
        ),
    )

    async def _empty_retrieval(*_args, **_kwargs):
        return []

    monkeypatch.setattr(backend.core.retrieval, "retrieve_legal_async", _empty_retrieval)

    class _UniversalPreview:
        is_available = True

        def search(self, *_args, **_kwargs):
            return [{"page_content": "unapproved preview source", "document_id": "univ-1", "metadata": {}}]

    monkeypatch.setattr(universal_module, "universal_retriever", _UniversalPreview())

    documents = await QdrantLegalRetrievalGateway().legal("Luật đất đai quy định gì?")

    assert documents == []
