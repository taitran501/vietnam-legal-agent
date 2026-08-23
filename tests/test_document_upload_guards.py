from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from unittest.mock import patch

import pytest
from backend.api.routes.documents import router, upload_document
from backend.api.upload_validation import (
    MAX_DOCX_UNCOMPRESSED_BYTES,
    MAX_UPLOAD_BYTES,
    UPLOAD_CHUNK_BYTES,
    read_bounded_upload,
)
from fastapi import FastAPI, HTTPException, Request
from starlette.testclient import TestClient

from epr_agent.infra.admission import AdmissionLease, AdmissionUnavailable
from epr_agent.tools.document_parser import DocumentParseResult


class AllowingAdmissionController:
    async def acquire(self, scope: str, **_kwargs: object) -> AdmissionLease:
        return AdmissionLease(scope=scope, token="allowed", ttl_seconds=300)

    async def heartbeat(self, _lease: AdmissionLease, interval_seconds: float) -> None:
        await asyncio.sleep(interval_seconds)

    async def release(self, _lease: AdmissionLease) -> None:
        return None


class RejectingAdmissionController(AllowingAdmissionController):
    async def acquire(self, scope: str, **_kwargs: object) -> None:
        return None


class BrokenAdmissionController(AllowingAdmissionController):
    async def acquire(self, scope: str, **_kwargs: object) -> None:
        raise AdmissionUnavailable("redis down")


class BrokenHeartbeatController(AllowingAdmissionController):
    async def heartbeat(self, _lease: AdmissionLease, interval_seconds: float) -> None:
        raise AdmissionUnavailable("redis heartbeat down")


def _client(controller: object | None = None) -> TestClient:
    app = FastAPI()
    app.state.admission_controller = controller or AllowingAdmissionController()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _docx_bytes(
    *,
    extra_uncompressed_bytes: int = 0,
    extra_entries: int = 0,
    content_types_xml: str | None = None,
    document_xml: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            content_types_xml
            or (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
        )
        archive.writestr(
            "word/document.xml",
            document_xml
            or (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Hop dong hop le</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
        if extra_uncompressed_bytes:
            archive.writestr("word/media/bomb.bin", b"0" * extra_uncompressed_bytes)
        for index in range(extra_entries):
            archive.writestr(f"word/media/{index}.bin", b"x")
    return buffer.getvalue()


def test_exact_10_mib_payload_is_accepted_before_text_extraction_limit() -> None:
    parsed = DocumentParseResult(
        document_id="boundary",
        filename="boundary.txt",
        file_type="txt",
        total_chars=10,
        raw_text="valid text",
    )
    with patch("backend.api.routes.documents.parse_document_file", return_value=parsed):
        response = _client().post(
            "/api/v1/documents/upload",
            files={"file": ("boundary.txt", io.BytesIO(b"a" * MAX_UPLOAD_BYTES), "text/plain")},
            data={"analyze_redline": "false"},
        )
    assert response.status_code == 200


class RecordingUpload:
    def __init__(self) -> None:
        self.read_count = 0

    async def read(self, _size: int) -> bytes:
        self.read_count += 1
        return b"x" * UPLOAD_CHUNK_BYTES


@pytest.mark.asyncio
async def test_oversized_reader_stops_on_first_chunk_past_limit() -> None:
    upload = RecordingUpload()
    with pytest.raises(HTTPException) as exc_info:
        await read_bounded_upload(upload)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 413
    assert upload.read_count == MAX_UPLOAD_BYTES // UPLOAD_CHUNK_BYTES + 1


@pytest.mark.parametrize(
    ("filename", "mime_type", "content"),
    [
        ("spoof.pdf", "text/plain", b"%PDF-1.7"),
        ("spoof.txt", "text/plain", b"\xff\xfe"),
        ("malformed.pdf", "application/pdf", b"%PDF-not-a-document"),
        ("malformed.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04bad"),
        (
            "malformed-content-types.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx_bytes(content_types_xml="<Types>"),
        ),
        (
            "malformed-document.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx_bytes(document_xml="<w:document>"),
        ),
    ],
)
def test_mime_spoofing_and_malformed_documents_are_rejected(
    filename: str,
    mime_type: str,
    content: bytes,
) -> None:
    response = _client().post(
        "/api/v1/documents/upload",
        files={"file": (filename, io.BytesIO(content), mime_type)},
        data={"analyze_redline": "false"},
    )
    assert response.status_code == 415


def test_pdf_page_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePDF:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __len__(self) -> int:
            return 201

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda **_kwargs: FakePDF()))
    response = _client().post(
        "/api/v1/documents/upload",
        files={"file": ("long.pdf", io.BytesIO(b"%PDF-1.7 fake"), "application/pdf")},
        data={"analyze_redline": "false"},
    )
    assert response.status_code == 422
    assert "200-page" in response.json()["detail"]


def test_valid_docx_structure_is_accepted() -> None:
    response = _client().post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "contract.docx",
                io.BytesIO(_docx_bytes()),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"analyze_redline": "false"},
    )
    assert response.status_code == 200
    assert response.json()["document"]["file_type"] == "docx"


def test_docx_decompression_bomb_is_rejected_before_extraction() -> None:
    content = _docx_bytes(extra_uncompressed_bytes=MAX_DOCX_UNCOMPRESSED_BYTES + 1)
    assert len(content) < MAX_UPLOAD_BYTES
    response = _client().post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "bomb.docx",
                io.BytesIO(content),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"analyze_redline": "false"},
    )
    assert response.status_code == 422
    assert "50 MiB" in response.json()["detail"]


def test_docx_entry_limit_is_enforced() -> None:
    response = _client().post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "many-entries.docx",
                io.BytesIO(_docx_bytes(extra_entries=999)),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"analyze_redline": "false"},
    )
    assert response.status_code == 422
    assert "1000-entry" in response.json()["detail"]


def test_extracted_text_limit_is_enforced() -> None:
    parsed = DocumentParseResult(
        document_id="large-text",
        filename="large.txt",
        file_type="txt",
        total_chars=2_000_001,
        raw_text="bounded double",
    )
    with patch("backend.api.routes.documents.parse_document_file", return_value=parsed):
        response = _client().post(
            "/api/v1/documents/upload",
            files={"file": ("large.txt", io.BytesIO(b"valid"), "text/plain")},
            data={"analyze_redline": "false"},
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("controller", "code"),
    [
        (RejectingAdmissionController(), "document_capacity_exceeded"),
        (BrokenAdmissionController(), "document_capacity_unavailable"),
        (BrokenHeartbeatController(), "document_capacity_unavailable"),
    ],
)
def test_upload_capacity_returns_retryable_503(controller: object, code: str) -> None:
    response = _client(controller).post(
        "/api/v1/documents/upload",
        files={"file": ("contract.txt", io.BytesIO(b"valid"), "text/plain")},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": code,
        "message": response.json()["detail"]["message"],
        "retryable": True,
        "retry_after_seconds": 5,
    }


class ConcurrentAdmissionController:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.active = 0
        self.maximum_seen = 0

    async def acquire(self, scope: str, **_kwargs: object) -> AdmissionLease | None:
        async with self.lock:
            if self.active >= 10:
                return None
            self.active += 1
            self.maximum_seen = max(self.maximum_seen, self.active)
            return AdmissionLease(scope=scope, token=str(self.active), ttl_seconds=300)

    async def heartbeat(self, _lease: AdmissionLease, interval_seconds: float) -> None:
        await asyncio.sleep(interval_seconds)

    async def release(self, _lease: AdmissionLease) -> None:
        async with self.lock:
            self.active -= 1


class BlockingUpload:
    filename = "contract.txt"
    content_type = "text/plain"

    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate
        self.sent = False

    async def read(self, _size: int) -> bytes:
        if self.sent:
            return b""
        self.sent = True
        await self.gate.wait()
        return b"valid contract text"

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ten_concurrent_uploads_are_admitted_and_eleventh_is_rejected() -> None:
    gate = asyncio.Event()
    controller = ConcurrentAdmissionController()
    app = FastAPI()
    app.state.admission_controller = controller
    request = Request({"type": "http", "app": app, "headers": []})
    tasks = [
        asyncio.create_task(
            upload_document(request, BlockingUpload(gate), analyze_redline=False)  # type: ignore[arg-type]
        )
        for _ in range(10)
    ]
    for _ in range(100):
        if controller.active == 10:
            break
        await asyncio.sleep(0.01)
    assert controller.active == 10

    with pytest.raises(HTTPException) as exc_info:
        await upload_document(request, BlockingUpload(gate), analyze_redline=False)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "document_capacity_exceeded"

    gate.set()
    results = await asyncio.gather(*tasks)
    assert len(results) == 10
    assert controller.maximum_seen == 10
    assert controller.active == 0


def test_nginx_allows_multipart_overhead_above_backend_payload_limit() -> None:
    nginx = Path("nginx.conf").read_text(encoding="utf-8")
    assert "client_max_body_size 11m;" in nginx
