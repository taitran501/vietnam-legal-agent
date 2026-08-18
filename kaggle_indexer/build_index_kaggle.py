"""
Kaggle GPU Indexer for Vietnamese Legal Corpus using SOTA darklethelong/vnlegal-lal
Indexes 318 National Codes & Laws + 67,000+ Codified Legal Articles (Pháp điển)
Outputs: Compressed Qdrant Vector Database (1024 dimensions)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.request

# Ensure unbuffered real-time stdout for Kaggle logging
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Ensure required libraries are present in Kaggle environment
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "sentence-transformers", "qdrant-client", "pyarrow", "tqdm"],
    check=False,
)

import pyarrow.parquet as pq
import torch
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Device detection: Try CUDA first
DEVICE = "cpu"
if torch.cuda.is_available():
    try:
        cap = torch.cuda.get_device_capability()
        gpu_name = torch.cuda.get_device_name(0)
        print(f"Detected GPU: {gpu_name} (Capability: {cap[0]}.{cap[1]})", flush=True)
        if cap[0] >= 7:
            DEVICE = "cuda"
            print("Using GPU CUDA acceleration.", flush=True)
        else:
            print(f"GPU {gpu_name} has capability {cap[0]}.{cap[1]} (< 7.0). Downgrading torch for P100 support...", flush=True)
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-q", "torch==2.4.1", "--index-url", "https://download.pytorch.org/whl/cu121"],
                    check=False,
                )
                import importlib
                importlib.reload(torch)
                DEVICE = "cuda"
                print("Successfully configured CUDA for P100.", flush=True)
            except Exception as e:
                print(f"Torch reload notice: {e}. Running multi-threaded CPU.", flush=True)
                DEVICE = "cpu"
                torch.set_num_threads(8)
    except Exception as exc:
        print(f"GPU check notice: {exc}. Using CPU.", flush=True)
        DEVICE = "cpu"
        torch.set_num_threads(8)
else:
    DEVICE = "cpu"
    torch.set_num_threads(8)

print(f"=== Active compute device: {DEVICE} ===", flush=True)



# ---------------------------------------------------------------------------
# 1. TẢI VÀ CHUẨN BỊ DATASET (UTS_VLC + PHAPDIEN)
# ---------------------------------------------------------------------------
print("\n=== 1. DOWNLOADING & PARSING LEGAL DATASETS ===")

CORPUS_DIR = "data_corpus"
os.makedirs(CORPUS_DIR, exist_ok=True)

articles: list[dict[str, str]] = []

# 1.1 Tải và nạp UTS_VLC (318 Bộ luật & Luật Quốc gia)
local_uts_candidates = [
    "uts_vlc_2026_01.parquet",
    os.path.join(os.path.dirname(__file__), "uts_vlc_2026_01.parquet"),
    os.path.join("/kaggle/src", "uts_vlc_2026_01.parquet"),
    os.path.join("/kaggle/working", "uts_vlc_2026_01.parquet"),
    os.path.join(CORPUS_DIR, "uts_vlc_2026_01.parquet"),
]

# Deep scan if not in direct paths
uts_path = None
for cand in local_uts_candidates:
    if os.path.exists(cand):
        uts_path = cand
        break

if not uts_path:
    for root_search in [".", "/kaggle"]:
        if os.path.exists(root_search):
            for r, _, fnames in os.walk(root_search):
                for fn in fnames:
                    if "uts_vlc" in fn and fn.endswith(".parquet"):
                        uts_path = os.path.join(r, fn)
                        break
                if uts_path:
                    break


if uts_path and os.path.exists(uts_path):
    print(f"Loading local UTS_VLC from {uts_path}...")
    table = pq.read_table(uts_path).to_pydict()
    num_laws = len(table.get("id", []))
    for i in range(num_laws):
        law_id = str(table["id"][i])
        law_title = str(table.get("title", [""])[i] or "")
        content = str(table.get("content", [""])[i] or "")
        domain = str(table.get("domain", ["Luật Quốc gia"])[i] or "Luật Quốc gia")
        status = str(table.get("status", ["Còn hiệu lực"])[i] or "Còn hiệu lực")
        code = str(table.get("code", [""])[i] or "")

        split_articles = art_split_pattern.split(content)
        for idx, art in enumerate(split_articles[1:], 1):
            art_clean = art.strip()
            if not art_clean:
                continue
            first_line = art_clean.splitlines()[0]
            articles.append({
                "record_id": f"{law_id}-art-{idx}",
                "topic": "Luật Quốc gia",
                "subject": domain,
                "document_title": law_title,
                "document_code": code,
                "article_title": first_line[:140],
                "effective_status": status,
                "content_text": art_clean,
            })
    print(f"Indexed {len(articles):,} articles from 318 National Laws.")


# 1.2 Tải Bộ Pháp điển (67.000+ điều khoản chi tiết)
print("Downloading Phapdien parquet shards...")
HF_PHAPDIEN_BASE = "https://huggingface.co/datasets/tmquan/phapdien-moj-gov-vn/resolve/main"
for i in range(7):
    fname = f"articles-{i:05d}-of-00007.parquet"
    local_path = os.path.join(CORPUS_DIR, fname)
    if not os.path.exists(local_path):
        urllib.request.urlretrieve(f"{HF_PHAPDIEN_BASE}/{fname}", local_path)
    
    table = pq.read_table(local_path).to_pydict()
    for j in range(len(table["record_id"])):
        articles.append({
            "record_id": str(table["record_id"][j]),
            "topic": str(table["topic_title_vi"][j] or "Pháp điển"),
            "subject": str(table["subject_title_vi"][j] or ""),
            "document_title": str(table["source_note_text"][j] or "Bộ Pháp điển Việt Nam"),
            "document_code": "",
            "article_title": str(table["article_title"][j] or ""),
            "effective_status": "Còn hiệu lực",
            "content_text": str(table["content_text"][j] or ""),
        })

print(f"✅ Total Legal Articles to Index: {len(articles):,}")

# ---------------------------------------------------------------------------
# 2. LOAD MODEL SOTA: darklethelong/vnlegal-lal
# ---------------------------------------------------------------------------
MODEL_NAME = "darklethelong/vnlegal-lal"
print(f"\n=== 2. LOADING MODEL: {MODEL_NAME} ===")

model = SentenceTransformer(MODEL_NAME, device=DEVICE)
if DEVICE == "cuda":
    try:
        model.half()
        print("Using FP16 precision on GPU.")
    except Exception as exc:
        print(f"FP16 half() notice: {exc}. Running in default precision.")


VECTOR_DIM = 1024

# ---------------------------------------------------------------------------
# 3. KHỞI TẠO LOCAL QDRANT DATABASE
# ---------------------------------------------------------------------------
print("\n=== 3. INITIALIZING QDRANT DATABASE ===")
OUTPUT_DIR = "qdrant_db"
os.makedirs(OUTPUT_DIR, exist_ok=True)

client = QdrantClient(path=OUTPUT_DIR)
COLLECTION_NAME = "vietnam_legal_collection_v1"

client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    hnsw_config=HnswConfigDiff(m=16, ef_construct=128, full_scan_threshold=10000),
)

# Tạo payload index để tìm kiếm và lọc metadata siêu tốc
for field in ["topic", "subject", "effective_status", "document_title"]:
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
    except Exception as exc:
        print(f"Payload index creation note: {exc}")

# ---------------------------------------------------------------------------
# 4. CHUNKING THEO CẤU TRÚC VÀ BATCH GPU EMBEDDING
# ---------------------------------------------------------------------------
print("\n=== 4. BATCH ENCODING & UPSERTING ===")

BATCH_SIZE = 64  # Optimal for Kaggle T4 GPU 16GB

# Chuẩn bị văn bản định dạng phân cấp chuẩn legal_structure_v2
texts_to_embed = []
for a in articles:
    text_repr = (
        f"Văn bản: {a['document_title']}\n"
        f"Chủ đề: {a['topic']} - {a['subject']}\n"
        f"Điều: {a['article_title']}\n"
        f"Nội dung: {a['content_text'][:3500]}"
    )
    texts_to_embed.append(text_repr)

total_records = len(articles)
started_at = time.time()

for batch_num, idx in enumerate(range(0, total_records, BATCH_SIZE), 1):
    batch_texts = texts_to_embed[idx : idx + BATCH_SIZE]
    batch_articles = articles[idx : idx + BATCH_SIZE]
    
    with torch.no_grad():
        embeddings = model.encode(
            batch_texts,
            batch_size=BATCH_SIZE,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
    
    points = []
    for i, item in enumerate(batch_articles):
        points.append(
            PointStruct(
                id=idx + i + 1,
                vector=embeddings[i].tolist(),
                payload={
                    "record_id": item["record_id"],
                    "topic": item["topic"],
                    "subject": item["subject"],
                    "document_title": item["document_title"],
                    "document_code": item["document_code"],
                    "article_title": item["article_title"],
                    "effective_status": item["effective_status"],
                    "source": item["document_title"],
                    "text": item["content_text"][:2000],
                },
            )
        )
    
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    if batch_num % 10 == 0 or idx + BATCH_SIZE >= total_records:
        current_count = min(idx + len(batch_articles), total_records)
        elapsed = time.time() - started_at
        speed = current_count / max(elapsed, 0.1)
        remaining = (total_records - current_count) / max(speed, 0.1)
        pct = (current_count / total_records) * 100
        print(f"⚡ [{current_count:,}/{total_records:,}] ({pct:.1f}%) | Speed: {speed:.1f} vec/s | Elapsed: {elapsed:.0f}s | ETA: {remaining:.0f}s", flush=True)

duration = time.time() - started_at
speed = total_records / max(duration, 0.1)
print(f"\nIndexed {total_records:,} vectors in {duration:.1f}s ({speed:.1f} vectors/sec)", flush=True)


# ---------------------------------------------------------------------------
# 5. ĐÓNG GÓI THÀNH ARTIFACT (.TAR.GZ)
# ---------------------------------------------------------------------------
print("\n=== 5. COMPRESSING QDRANT ARTIFACT ===")
artifact_name = "qdrant_vnlegal_lal.tar.gz"
with tarfile.open(artifact_name, "w:gz") as tar:
    tar.add(OUTPUT_DIR, arcname="qdrant_db")

artifact_size_mb = os.path.getsize(artifact_name) / (1024 * 1024)
print(f"🎉 SUCCESS! Output file: {artifact_name} ({artifact_size_mb:.1f} MB)")
