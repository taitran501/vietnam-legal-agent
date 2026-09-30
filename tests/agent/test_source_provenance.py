from __future__ import annotations

from types import SimpleNamespace

from vietnam_legal_agent.agent.runtime import _documents_for_api, _source_snapshots
from vietnam_legal_agent.tools.retrieval import _to_record
from vietnam_legal_agent.tools.source_provenance import (
    canonical_source_snapshots,
    normalize_source,
    normalized_document_metadata,
)


def test_normalize_source_uses_parent_document_and_keeps_chunk_excerpt() -> None:
    item = {
        "document_id": "chunk-318-1",
        "content": "[CHỦ ĐỀ]: Văn bản mới | [CĂN CỨ VĂN BẢN]: Nghị định số 318/2026/NĐ-CP\n\nĐiều 1 quy định phạm vi áp dụng.",
        "source": "legal",
        "metadata": {
            "chunk_id": "chunk-318-1",
            "parent_id": "nd-318-2026",
            "law_ref": "(Điều 1 Nghị định số 318/2026/NĐ-CP ngày 12/08/2026)",
            "Dieu": "Điều 1",
            "source_uri": "https://vanban.chinhphu.vn/?docid=318",
        },
    }

    snapshot = normalize_source(item, citation_index=1, corpus_as_of_date="2026-08-23")

    assert snapshot["source_id"] == "nd-318-2026"
    assert snapshot["chunk_id"] == "chunk-318-1"
    assert snapshot["instrument_number"] == "318/2026/NĐ-CP"
    assert snapshot["title"] == "Điều 1 Nghị định số 318/2026/NĐ-CP ngày 12/08/2026"
    assert snapshot["anchor"] == "Điều 1"
    assert snapshot["official_url"] == "https://vanban.chinhphu.vn/?docid=318"
    assert "[CHỦ ĐỀ]" not in snapshot["excerpt"]
    assert snapshot["excerpt"].startswith("Điều 1 quy định")


def test_normalized_document_metadata_preserves_legacy_fields_without_raw_chunk_headers() -> None:
    item = {
        "document_id": "chunk-1",
        "page_content": "[CHỦ ĐỀ]: X\n\nNội dung Điều 25",
        "metadata": {
            "parent_id": "labor-code-2019",
            "source": "Bộ luật Lao động 2019",
            "topic": "Lao động",
            "Document_Number": "45/2019/QH14",
            "official_url": "https://vanban.chinhphu.vn/?docid=205092",
            "Dieu": "Điều 25",
            "Pages": "12",
            "Source_Start": 100,
            "Source_End": 140,
        },
    }
    snapshot = normalize_source(item, citation_index=2)
    metadata = normalized_document_metadata(snapshot, original=item)

    assert metadata["source_id"] == "labor-code-2019"
    assert metadata["source_title"] == "Bộ luật Lao động 2019"
    assert metadata["Document_Number"] == "45/2019/QH14"
    assert metadata["legal_anchor"] == "Điều 25"
    assert metadata["Pages"] == "12"
    assert metadata["Source_Start"] == 100
    assert metadata["Source_End"] == 140
    assert metadata["topic"] == "Lao động"
    assert metadata["excerpt"] == "Nội dung Điều 25"
    assert "page_content" not in metadata


def test_generic_catalogue_url_and_source_label_are_not_presented_as_canonical_source() -> None:
    snapshot = normalize_source(
        {
            "document_id": "chunk-1",
            "content": "Nội dung chưa có metadata.",
            "source": "Hệ thống văn bản",
            "metadata": {"source_title": "Hệ thống văn bản", "official_url": "https://vbpl.vn"},
        },
        citation_index=1,
    )

    assert snapshot["title"] == ""
    assert snapshot["official_url"] == ""


def test_clean_excerpt_separates_legacy_double_pipe_fields() -> None:
    snapshot = normalize_source(
        {
            "document_id": "chunk-1",
            "content": "Tài liệu đính kèm || 318/2026/NĐ-CP || Quy định chi tiết một số điều.",
            "metadata": {"source": "Hệ thống văn bản"},
        },
        citation_index=1,
    )

    assert "||" not in snapshot["excerpt"]
    assert "318/2026/NĐ-CP" in snapshot["excerpt"]


def test_retrieval_adapter_does_not_use_source_label_as_document_id() -> None:
    record = _to_record(
        SimpleNamespace(
            page_content="Nội dung",
            metadata={"source": "Hệ thống văn bản", "_id": "chunk-qdrant-1"},
        ),
        source="legal",
        index=0,
    )

    assert record.document_id == "chunk-qdrant-1"


def test_runtime_api_documents_expose_canonical_parent_and_clean_excerpt() -> None:
    state = {
        "answer": "Theo Điều 25 [1].",
        "evidence": [
            {
                "document_id": "chunk-25",
                "content": "[CHỦ ĐỀ]: Lao động | [CĂN CỨ VĂN BẢN]: Bộ luật Lao động 2019\n\nĐiều 25 quy định thời gian thử việc.",
                "metadata": {
                    "chunk_id": "chunk-77",
                    "parent_id": "labor-code-2019",
                    "source": "Bộ luật Lao động 2019",
                    "Document_Number": "45/2019/QH14",
                    "Dieu": "Điều 25",
                    "source_uri": "https://vanban.chinhphu.vn/?docid=205092",
                },
            }
        ],
    }

    documents = _documents_for_api(state)
    snapshots = _source_snapshots(state)

    assert documents[0]["document_id"] == "chunk-77"
    assert documents[0]["metadata"]["source_id"] == "labor-code-2019"
    assert documents[0]["metadata"]["Source_Title"] == "Bộ luật Lao động 2019"
    assert documents[0]["metadata"]["Document_Number"] == "45/2019/QH14"
    assert documents[0]["page_content"].startswith("Điều 25")
    assert snapshots[0]["source_id"] == "labor-code-2019"
    assert snapshots[0]["chunk_id"] == "chunk-77"


def test_canonical_source_snapshots_group_chunks_and_keep_all_citation_indices() -> None:
    items = [
        {
            "document_id": "chunk-25-a",
            "content": "Đoạn đầu Điều 25.",
            "score": 0.62,
            "metadata": {
                "parent_id": "labor-code-2019",
                "Document_Number": "45/2019/QH14",
                "legal_anchor": "Điều 25",
                "source_title": "Bộ luật Lao động 2019",
            },
        },
        {
            "document_id": "chunk-25-b",
            "content": "Đoạn chính Điều 25 || trường dữ liệu cũ.",
            "score": 0.91,
            "metadata": {
                "parent_id": "labor-code-2019",
                "instrument_number": "45/2019/QH14",
                "legal_anchor": "Điều 25",
                "source_title": "Bộ luật Lao động 2019",
            },
        },
    ]

    snapshots = canonical_source_snapshots(items, citation_indices=[1, 2])

    assert len(snapshots) == 1
    assert snapshots[0]["source_id"] == "labor-code-2019"
    assert snapshots[0]["citation_index"] == 1
    assert snapshots[0]["citation_indices"] == [1, 2]
    assert snapshots[0]["chunk_id"] == "chunk-25-b"
    assert snapshots[0]["excerpt"] == "Đoạn chính Điều 25\n\ntrường dữ liệu cũ."


def test_runtime_source_snapshots_use_canonical_grouping_for_duplicate_chunks() -> None:
    state = {
        "answer": "Theo Điều 25 [1] và [2].",
        "evidence": [
            {
                "document_id": "chunk-a",
                "content": "Điều 25 đoạn một.",
                "score": 0.4,
                "metadata": {
                    "parent_id": "labor-code-2019",
                    "Document_Number": "45/2019/QH14",
                    "legal_anchor": "Điều 25",
                    "source_title": "Bộ luật Lao động 2019",
                },
            },
            {
                "document_id": "chunk-b",
                "content": "Điều 25 đoạn hai.",
                "score": 0.8,
                "metadata": {
                    "parent_id": "labor-code-2019",
                    "Document_Number": "45/2019/QH14",
                    "legal_anchor": "Điều 25",
                    "source_title": "Bộ luật Lao động 2019",
                },
            },
        ],
    }

    snapshots = _source_snapshots(state)

    assert len(snapshots) == 1
    assert snapshots[0]["citation_indices"] == [1, 2]
    assert snapshots[0]["chunk_id"] == "chunk-b"
