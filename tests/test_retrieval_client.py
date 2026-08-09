from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from backend.core import retrieval


def test_qdrant_client_is_initialized_once_across_threads(monkeypatch):
    created: list[object] = []

    def fake_client(**_kwargs):
        time.sleep(0.01)
        client = object()
        created.append(client)
        return client

    settings = SimpleNamespace(
        use_qdrant_cloud=False,
        qdrant_cloud_url=None,
        qdrant_api_key=None,
        qdrant_url=None,
        qdrant_local_path="./qdrant_db",
    )
    monkeypatch.setattr(retrieval, "get_settings", lambda: settings)
    monkeypatch.setattr(retrieval, "QdrantClient", fake_client)
    monkeypatch.setattr(retrieval, "_qdrant_client", None)

    with ThreadPoolExecutor(max_workers=8) as executor:
        clients = list(executor.map(lambda _index: retrieval._get_qdrant_client(), range(16)))

    assert len(created) == 1
    assert all(client is created[0] for client in clients)


def test_close_qdrant_client_releases_shared_instance(monkeypatch):
    class FakeClient:
        closed = False

        def close(self):
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(retrieval, "_qdrant_client", client)

    retrieval.close_qdrant_client()

    assert client.closed is True
    assert retrieval._qdrant_client is None


def test_general_faq_wording_can_use_high_confidence_faq_cache() -> None:
    assert not retrieval._looks_like_legal_query(
        "Trường hợp nào không phải thực hiện trách nhiệm tái chế?"
    )


def test_explicit_legal_reference_bypasses_faq_cache() -> None:
    assert retrieval._looks_like_legal_query("Điều 77 Nghị định 08/2022 quy định gì?")
