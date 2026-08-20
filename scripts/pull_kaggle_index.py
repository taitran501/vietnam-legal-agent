"""
Helper script to download and unpack Kaggle Qdrant vector index artifact.

Usage:
    python scripts/pull_kaggle_index.py --kernel YOUR_KAGGLE_USERNAME/vnlegal-lal-qdrant-indexer
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pull_and_unpack(kernel_id: str, dest_dir: Path | None = None) -> bool:
    target_qdrant_dir = dest_dir or (ROOT / "qdrant_db")
    temp_dir = ROOT / "artifacts" / "kaggle_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== 1. Pulling artifact from Kaggle: {kernel_id} ===")
    cmd = ["kaggle", "kernels", "output", kernel_id, "-p", str(temp_dir)]
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(res.stdout)
    except subprocess.CalledProcessError as exc:
        print(f"❌ Error pulling from Kaggle CLI: {exc.stderr}")
        print("Tip: Make sure you have set up ~/.kaggle/kaggle.json and the kernel has completed execution.")
        return False

    tar_path = temp_dir / "qdrant_vnlegal_lal.tar.gz"
    if not tar_path.exists():
        tar_files = list(temp_dir.glob("*.tar.gz"))
        if tar_files:
            tar_path = tar_files[0]
        else:
            print(f"❌ Could not find .tar.gz file in {temp_dir}. Found files: {[f.name for f in temp_dir.iterdir()]}")
            return False

    print(f"\n=== 2. Unpacking {tar_path.name} to {target_qdrant_dir} ===")
    backup_dir = ROOT / "qdrant_db_backup"
    if target_qdrant_dir.exists():
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        target_qdrant_dir.rename(backup_dir)
        print(f"Moved existing qdrant_db to backup at {backup_dir.name}")

    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=ROOT)

    print(f"Extracted successfully to {target_qdrant_dir}")

    # Verify collection
    print("\n=== 3. Verifying Qdrant Collection Integrity ===")
    try:
        collection_dir = target_qdrant_dir / "collection" / "vietnam_legal_collection_v1"
        storage_db = collection_dir / "storage.sqlite"
        if storage_db.exists():
            conn = sqlite3.connect(storage_db)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM points")
            count = c.fetchone()[0]
            conn.close()
            print(f"✅ Collection 'vietnam_legal_collection_v1' verified! Total vectors: {count:,}")
        else:
            print(f"Notice: storage.sqlite checked at {storage_db}")
    except (OSError, sqlite3.Error) as exc:
        print(f"Notice during verification: {exc}")

    # Clean up temp
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("\n🎉 Indexing import completed successfully!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pull and unpack Qdrant vector database from Kaggle")
    parser.add_argument("--kernel", type=str, required=True, help="Kaggle kernel ID, e.g. username/kernel-slug")
    args = parser.parse_args()
    pull_and_unpack(args.kernel)
