from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm


# ===========================
# Dependency auto-installation
# ===========================
REQUIRED_PACKAGES = [
    "qdrant-client>=1.10.0",
    "sentence-transformers>=3.0.0",
    "tqdm>=4.66.0",
]


def ensure_dependencies() -> None:
    missing = []
    checks = {
        "qdrant_client": "qdrant-client>=1.10.0",
        "sentence_transformers": "sentence-transformers>=3.0.0",
        "tqdm": "tqdm>=4.66.0",
    }
    for module_name, package_name in checks.items():
        try:
            __import__(module_name)
        except Exception:
            missing.append(package_name)

    if missing:
        print(f"[deps] Missing packages detected: {missing}")
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-q",
                "--progress-bar",
                "off",
                *REQUIRED_PACKAGES,
            ]
        )
        print("[deps] Installation complete.")


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _as_int(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class RuntimeConfig:
    law_json_path: Path
    qdrant_collection: str
    qdrant_cloud_url: str
    qdrant_api_key: str
    use_qdrant_cloud: bool
    qdrant_local_path: Path
    reset_collection: bool
    embed_model: str
    embed_device: str
    embed_batch_size: int
    upsert_batch_size: int
    chunk_size_chars: int
    chunk_overlap_chars: int
    min_chunk_chars: int
    artifacts_path: Path
    hnsw_m: int
    hnsw_ef_construct: int


def discover_law_json_path() -> Path:
    """
    Resolve law.json path with priority:
    1) LAW_JSON_PATH env
    2) Kaggle dataset path provided by user
    3) local repo fallback: ./data/law.json
    """
    env_path = os.getenv("LAW_JSON_PATH", "").strip()
    if env_path:
        p = Path(env_path).resolve()
        if p.exists():
            return p

    candidates = [
        Path("/kaggle/input/datasets/taitran501/law-dataset/law.json"),
        Path(__file__).resolve().parent / "data" / "law.json",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()

    # Keep deterministic default even if not found, so later error message is clear.
    return candidates[0].resolve()


def build_runtime_config() -> RuntimeConfig:
    project_root = Path(__file__).resolve().parent
    default_law_json = discover_law_json_path()

    cfg = RuntimeConfig(
        law_json_path=Path(os.getenv("LAW_JSON_PATH", str(default_law_json))).resolve(),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "law_collection_bge").strip(),
        qdrant_cloud_url=os.getenv("QDRANT_CLOUD_URL", "").strip(),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip(),
        use_qdrant_cloud=_as_bool(os.getenv("USE_QDRANT_CLOUD"), True),
        qdrant_local_path=Path(os.getenv("QDRANT_LOCAL_PATH", "./qdrant_db")).resolve(),
        reset_collection=_as_bool(os.getenv("RESET_COLLECTION_ON_BUILD"), True),
        embed_model=os.getenv("EMBED_MODEL", "BAAI/bge-m3").strip(),
        embed_device=os.getenv("EMBED_DEVICE", "cuda").strip(),
        embed_batch_size=_as_int(os.getenv("EMBED_BATCH_SIZE"), 32),
        upsert_batch_size=_as_int(os.getenv("UPSERT_BATCH_SIZE"), 128),
        chunk_size_chars=_as_int(os.getenv("CHUNK_SIZE_CHARS"), 1600),
        chunk_overlap_chars=_as_int(os.getenv("CHUNK_OVERLAP_CHARS"), 220),
        min_chunk_chars=_as_int(os.getenv("MIN_CHUNK_CHARS"), 180),
        artifacts_path=Path(os.getenv("ARTIFACTS_PATH", "./artifacts/index_build_stats.json")).resolve(),
        hnsw_m=_as_int(os.getenv("HNSW_M"), 64),
        hnsw_ef_construct=_as_int(os.getenv("HNSW_EF_CONSTRUCT"), 256),
    )
    return cfg


ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\uFEFF]")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTIBLANK_RE = re.compile(r"\n{3,}")
PUNCT_NO_SPACE_RE = re.compile(r"([,;:])(?=\S)")
ENUM_NO_SPACE_RE = re.compile(r"(?<=\d)\.(?=[A-Za-zÀ-ỹà-ỹ])")
EXTRACT_DIEU_NUMBER_RE = re.compile(r"\bĐiều\s+(\d+)\b", flags=re.IGNORECASE)


def _clean_heading(text: str | None) -> str:
    if not text:
        return ""
    t = ZERO_WIDTH_RE.sub("", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = " ".join(part.strip() for part in t.split("\n") if part.strip())
    t = MULTISPACE_RE.sub(" ", t)
    return t.strip()


def _normalize_paragraph(raw: str) -> str:
    s = raw.strip()
    s = MULTISPACE_RE.sub(" ", s)
    s = PUNCT_NO_SPACE_RE.sub(r"\1 ", s)
    s = ENUM_NO_SPACE_RE.sub(". ", s)
    return s.strip()


def clean_legal_text(text: str | None) -> str:
    if not text:
        return ""
    t = ZERO_WIDTH_RE.sub("", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\t", " ")

    # Fix OCR/export line-wrap artifacts inside a paragraph:
    # non-empty lines separated by '\n' should usually be joined by space.
    lines = [ln.strip() for ln in t.split("\n")]
    paragraphs: list[str] = []
    cur: list[str] = []
    for ln in lines:
        if not ln:
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
            continue
        cur.append(ln)
    if cur:
        paragraphs.append(" ".join(cur))

    cleaned_paragraphs = [_normalize_paragraph(p) for p in paragraphs if p.strip()]
    t = "\n\n".join(cleaned_paragraphs)
    t = MULTIBLANK_RE.sub("\n\n", t)
    return t.strip()


def chunk_text(
    text: str,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    min_chunk_chars: int,
) -> list[str]:
    if len(text) <= chunk_size_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + chunk_size_chars, n)
        if end < n:
            soft_cut = text.rfind("\n\n", start + max(200, min_chunk_chars), end)
            if soft_cut != -1:
                end = soft_cut

        chunk = text[start:end].strip()
        if chunk:
            if len(chunk) >= min_chunk_chars or not chunks:
                chunks.append(chunk)

        if end >= n:
            break
        next_start = max(0, end - chunk_overlap_chars)
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks if chunks else [text]


def _extract_dieu_number(dieu_heading: str) -> int | None:
    m = EXTRACT_DIEU_NUMBER_RE.search(dieu_heading)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _stable_id(*parts: str) -> str:
    blob = "|".join(parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def load_law_records(law_json_path: Path) -> list[dict[str, Any]]:
    if not law_json_path.exists():
        raise FileNotFoundError(f"law.json not found: {law_json_path}")

    with law_json_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and "meta" in raw and isinstance(raw["meta"], list):
        records = raw["meta"]
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("Unsupported law.json format. Expect list or {'meta': [...]} ")

    return [r for r in records if isinstance(r, dict)]


def build_documents(cfg: RuntimeConfig, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    skipped_no_text = 0
    total_chunks = 0
    appendix_docs = 0
    unique_base_ids: set[str] = set()

    for record in records:
        dieu = _clean_heading(record.get("Điều") or record.get("Dieu") or "")
        chuong = _clean_heading(record.get("Chương") or record.get("Chuong") or "")
        muc = _clean_heading(record.get("Mục") or record.get("Muc") or "")
        pages = _clean_heading(record.get("Pages") or "")
        raw_text = record.get("Text") or record.get("text") or ""
        text = clean_legal_text(raw_text)

        if not text:
            skipped_no_text += 1
            continue

        is_appendix = "phụ lục" in dieu.lower() or "phu luc" in dieu.lower()
        if is_appendix:
            appendix_docs += 1

        dieu_number = _extract_dieu_number(dieu)

        base_id = _stable_id(dieu, chuong, muc, text[:8000])
        if base_id in unique_base_ids:
            # same normalized content
            continue
        unique_base_ids.add(base_id)

        chunks = chunk_text(
            text=text,
            chunk_size_chars=cfg.chunk_size_chars,
            chunk_overlap_chars=cfg.chunk_overlap_chars,
            min_chunk_chars=cfg.min_chunk_chars,
        )
        total_chunks += len(chunks)

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{base_id}:{idx:03d}"
            payload = {
                "Dieu": dieu,
                "Chuong": chuong,
                "Muc": muc,
                "Pages": pages,
                "Text": chunk,
                "source_file": str(cfg.law_json_path),
                "record_id": base_id,
                "chunk_id": chunk_id,
                "chunk_index": idx,
                "chunk_total": len(chunks),
                "is_appendix": is_appendix,
                "dieu_number": dieu_number,
            }

            embed_text_parts = []
            if dieu:
                embed_text_parts.append(f"Điều: {dieu}")
            if chuong:
                embed_text_parts.append(f"Chương: {chuong}")
            if muc:
                embed_text_parts.append(f"Mục: {muc}")
            embed_text_parts.append(chunk)
            embed_text = "\n".join(embed_text_parts)

            docs.append(
                {
                    "id": chunk_id,
                    "embed_text": embed_text,
                    "payload": payload,
                }
            )

    stats = {
        "records_input": len(records),
        "records_unique": len(unique_base_ids),
        "docs_output": len(docs),
        "chunks_total": total_chunks,
        "appendix_records": appendix_docs,
        "skipped_no_text": skipped_no_text,
    }
    return docs, stats


def _iter_batches(items: list[dict[str, Any]], batch_size: int):
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def build_index(cfg: RuntimeConfig) -> None:
    ensure_dependencies()

    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, HnswConfigDiff, PointStruct, VectorParams
    from sentence_transformers import SentenceTransformer

    print("======== KAGGLE LAW INDEX BUILD ========")
    print(f"LAW_JSON_PATH={cfg.law_json_path}")
    print(f"USE_QDRANT_CLOUD={cfg.use_qdrant_cloud}")
    print(f"QDRANT_COLLECTION={cfg.qdrant_collection}")
    print(f"EMBED_MODEL={cfg.embed_model}")
    print(f"EMBED_DEVICE={cfg.embed_device}")
    print(f"EMBED_BATCH_SIZE={cfg.embed_batch_size}")
    print(f"UPSERT_BATCH_SIZE={cfg.upsert_batch_size}")
    print(f"CHUNK_SIZE_CHARS={cfg.chunk_size_chars}")
    print(f"CHUNK_OVERLAP_CHARS={cfg.chunk_overlap_chars}")
    print(f"MIN_CHUNK_CHARS={cfg.min_chunk_chars}")
    print("========================================")

    t0 = time.perf_counter()

    records = load_law_records(cfg.law_json_path)
    docs, data_stats = build_documents(cfg, records)
    print(f"[data] {data_stats}")

    model = SentenceTransformer(cfg.embed_model, device=cfg.embed_device)
    probe = model.encode(["dimension probe"], normalize_embeddings=True)
    vector_dim = int(probe.shape[1])

    if cfg.use_qdrant_cloud:
        if not cfg.qdrant_cloud_url or not cfg.qdrant_api_key:
            raise ValueError("USE_QDRANT_CLOUD=true requires QDRANT_CLOUD_URL and QDRANT_API_KEY")
        client = QdrantClient(url=cfg.qdrant_cloud_url, api_key=cfg.qdrant_api_key, timeout=60)
    else:
        cfg.qdrant_local_path.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(cfg.qdrant_local_path), timeout=60)

    existing = {c.name for c in client.get_collections().collections}
    if cfg.reset_collection and cfg.qdrant_collection in existing:
        print(f"[qdrant] deleting existing collection: {cfg.qdrant_collection}")
        client.delete_collection(cfg.qdrant_collection)
        existing.remove(cfg.qdrant_collection)

    if cfg.qdrant_collection not in existing:
        print(f"[qdrant] creating collection: {cfg.qdrant_collection} (dim={vector_dim})")
        client.create_collection(
            collection_name=cfg.qdrant_collection,
            vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(
                m=cfg.hnsw_m,
                ef_construct=cfg.hnsw_ef_construct,
            ),
        )

    upserted = 0
    for batch in tqdm(list(_iter_batches(docs, cfg.upsert_batch_size)), desc="upsert_batches"):
        texts = [x["embed_text"] for x in batch]
        vectors = model.encode(
            texts,
            batch_size=cfg.embed_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        points = [
            PointStruct(
                id=item["id"],
                vector=vectors[i].tolist(),
                payload=item["payload"],
            )
            for i, item in enumerate(batch)
        ]
        client.upsert(collection_name=cfg.qdrant_collection, points=points)
        upserted += len(points)

    elapsed = time.perf_counter() - t0
    stats_payload = {
        "law_json_path": str(cfg.law_json_path),
        "collection": cfg.qdrant_collection,
        "use_qdrant_cloud": cfg.use_qdrant_cloud,
        "embed_model": cfg.embed_model,
        "embed_device": cfg.embed_device,
        "embed_batch_size": cfg.embed_batch_size,
        "upsert_batch_size": cfg.upsert_batch_size,
        "chunk_size_chars": cfg.chunk_size_chars,
        "chunk_overlap_chars": cfg.chunk_overlap_chars,
        "min_chunk_chars": cfg.min_chunk_chars,
        "vector_dim": vector_dim,
        "upserted_points": upserted,
        "data_stats": data_stats,
        "elapsed_seconds": round(elapsed, 2),
    }

    cfg.artifacts_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.artifacts_path.write_text(
        json.dumps(stats_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[done] upserted_points={upserted}, elapsed={elapsed:.2f}s")
    print(f"[done] stats saved to {cfg.artifacts_path}")


if __name__ == "__main__":
    config = build_runtime_config()
    build_index(config)
