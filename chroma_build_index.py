from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict

from tqdm import tqdm


# ===========================
# 1. Dependency auto-installation
# ===========================
REQUIRED_PACKAGES = [
    "chromadb>=0.5.0",
    "llama-index-core>=0.12.0",
    "llama-index-embeddings-huggingface>=0.4.0",
    "tqdm>=4.66.0",
]


def ensure_dependencies() -> None:
    print("[deps] Checking/Installing dependencies...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "--progress-bar", "off", *REQUIRED_PACKAGES]
    )
    print("[deps] Installation done.")


# ===========================
# 2. Advanced Legal Cleaning
# ===========================
def clean_legal_text(text: str | None) -> str:
    """
    Clean Vietnamese legal text by fixing broken newlines and normalizing whitespace.
    """
    if not text:
        return ""
    
    # 1. Fix broken newlines: join lines that don't start with a clause number (1., 2.) 
    # or a bullet point (-), but preserve newlines before clauses.
    # Logic: If a newline is NOT followed by a digit and a dot (e.g., "1."), join it.
    text = re.sub(r'(?<![.\d])\n(?![1-9]\.|\d+\)|-)', ' ', text)
    
    # 2. Normalize whitespace (remove tabs, double spaces)
    text = re.sub(r'[ \t]+', ' ', text)
    
    # 3. Remove excessive blank lines
    text = re.sub(r'\n\s*\n', '\n', text)
    
    return text.strip()


# ===========================
# 3. Legal Data Loading & Chunking
# ===========================
def load_legal_nodes(json_path: Path) -> List[Dict[str, Any]]:
    """
    Load law.json and split articles into clauses (Khoản) for better retrieval.
    Injects the article title into each clause for context preservation.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"Legal data not found at {json_path}")

    print(f"Loading legal data from {json_path}...")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    
    # Handle different JSON structures
    articles = data.get("meta", []) if isinstance(data, dict) else data
    nodes = []
    
    for art in articles:
        dieu_title = art.get("Điều") or art.get("Dieu") or "Không xác định"
        chuong = art.get("Chương") or art.get("Chuong") or ""
        muc = art.get("Mục") or art.get("Muc") or ""
        raw_text = art.get("Text") or art.get("text") or ""
        
        if not raw_text:
            continue

        # Preliminary cleaning
        cleaned_content = clean_legal_text(raw_text)
        
        # Split into clauses (Khoản) using regex for numbers at start of lines (e.g., "1.", "2.")
        # We use a lookahead to keep the clause number in the split result
        clauses = re.split(r'\n(?=\d+\.)', cleaned_content)
        
        for i, clause in enumerate(clauses):
            clause_text = clause.strip()
            if not clause_text:
                continue
            
            # CONTEXT INJECTION: Prepend Article title to each clause
            # This ensures the embedding captures the relationship to the law article
            final_text = f"{dieu_title}\n{clause_text}"
            
            # Generate a stable ID
            node_id = f"{dieu_title}_clause_{i+1}".replace(" ", "_")
            
            metadata = {
                "Dieu": dieu_title,
                "Chuong": chuong,
                "Muc": muc,
                "clause_index": i + 1,
                "node_type": "legal_clause",
                "source": "law_json"
            }
            
            nodes.append({
                "id": node_id,
                "text": final_text,
                "metadata": metadata
            })
            
    return nodes


# ===========================
# 4. Main Build Runner
# ===========================
def run_build():
    ensure_dependencies()
    import chromadb
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    # Config (Kaggle-friendly paths)
    # Check if we are on Kaggle or Local
    is_kaggle = os.path.exists("/kaggle/working")
    
    # Determine Data Path
    # Default to current project structure if local, otherwise Kaggle input
    local_data = Path("data/law.json")
    kaggle_data = Path("/kaggle/input/epr-law-dataset/law.json") # Adjust as needed
    DATA_PATH = kaggle_data if is_kaggle else local_data
    
    # Output Paths
    WORKING_DIR = Path("/kaggle/working") if is_kaggle else Path(".")
    STORAGE_PATH = WORKING_DIR / "storage" / "chroma"
    COLLECTION_NAME = "epr_legal_clauses"
    
    EMBED_MODEL = "BAAI/bge-m3" # Multi-lingual powerhouse for Vietnamese
    BATCH_SIZE = 16 if is_kaggle else 4 # Higher batch size for Kaggle GPUs

    STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("======== LEGAL RAG BUILD (CHROMA) ========")
    print(f"Data Source: {DATA_PATH}")
    print(f"Embed Model: {EMBED_MODEL}")
    print(f"Storage: {STORAGE_PATH}")
    print("==========================================")

    # 1. Load & Chunk
    if not DATA_PATH.exists():
        print(f"ERROR: law.json not found at {DATA_PATH}")
        print("Please check your DATA_PATH configuration.")
        return

    nodes = load_legal_nodes(DATA_PATH)
    print(f"Total nodes (Clauses) generated: {len(nodes)}")

    # 2. Init Embed Model
    print(f"Loading {EMBED_MODEL} on {'GPU' if is_kaggle else 'CPU'}...")
    embed_model = HuggingFaceEmbedding(
        model_name=EMBED_MODEL,
        device="cuda" if is_kaggle else "cpu", 
        embed_batch_size=BATCH_SIZE
    )

    # 3. Setup Chroma
    chroma_client = chromadb.PersistentClient(path=str(STORAGE_PATH))
    
    # Use Cosine Similarity (recommended for BGE-M3)
    # We delete existing collection if reset_collection is true
    if os.getenv("RESET_COLLECTION", "true").lower() == "true":
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            print(f"Deleted existing collection: {COLLECTION_NAME}")
        except:
            pass

    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"} 
    )

    # 4. Build Index
    print(f"Building embeddings and inserting into Chroma in batches of {BATCH_SIZE}...")
    for i in tqdm(range(0, len(nodes), BATCH_SIZE)):
        batch = nodes[i : i + BATCH_SIZE]
        ids = [n["id"] for n in batch]
        texts = [n["text"] for n in batch]
        metadatas = [n["metadata"] for n in batch]
        
        # Convert to embeddings
        embeddings = embed_model.get_text_embedding_batch(texts)
        
        # Insert into Chroma
        collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings
        )

    print(f"✅ Build complete. Collection size: {collection.count()}")
    print(f"Index artifacts saved in: {STORAGE_PATH}")


if __name__ == "__main__":
    run_build()
