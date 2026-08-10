from __future__ import annotations

import pytest

from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.retrieval import StaticRetrievalGateway


@pytest.mark.asyncio
async def test_legal_gateway_has_no_faq_surface() -> None:
    gateway = StaticRetrievalGateway(
        legal_documents=[DocumentRecord(content="Điều 77", metadata={"Dieu": "Điều 77"}, document_id="77", source="legal")]
    )

    documents = await gateway.legal("Điều 77 quy định gì?")

    assert [document.document_id for document in documents] == ["77"]
    assert gateway.calls == [("legal", "Điều 77 quy định gì?")]
    assert not hasattr(gateway, "faq")
