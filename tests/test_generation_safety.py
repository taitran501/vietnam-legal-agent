from backend.core import generation
from langchain_core.documents import Document


def test_relevance_gate_fails_closed_when_provider_errors(monkeypatch):
    """A relevance-provider outage must not authorize legal generation."""

    def raise_provider_error():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(generation, "get_llm_router", raise_provider_error)

    assert generation.is_retrieval_relevant(
        "Điều 77 quy định gì?",
        [Document(page_content="Trách nhiệm tái chế", metadata={"Dieu": "Điều 77"})],
    ) is False


def test_relevance_gate_missing_verdict_fails_closed(monkeypatch):
    """A malformed structured verdict must not default to relevant."""

    class Chain:
        def invoke(self, _payload):
            return object()

    class Router:
        def with_structured_output(self, _schema):
            return Chain()

    monkeypatch.setattr(generation, "get_llm_router", lambda: Router())

    assert generation.is_retrieval_relevant(
        "Điều 77 quy định gì?",
        [Document(page_content="Trách nhiệm tái chế", metadata={"Dieu": "Điều 77"})],
    ) is False
