"""
End-to-End Kaggle Automation Pipeline for Vietnamese Legal Indexing:
1. Compile & Unit Test Local Notebook (AST + Schema)
2. Push to Kaggle with GPU Accelerator (NvidiaTeslaT4)
3. Smart Queue & Execution Monitoring:
   - Max Queue Timeout (120s) to detect congested queues
   - Execution Tracking ONLY when status transitions to RUNNING
4. Auto-Download Artifact, Extract to qdrant_db/, and Verify Search
"""
import ast
import json
import shutil
import sys
import tarfile
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

KERNEL_SLUG = "taitran501/vnlegal-lal-qdrant-legal-indexer"
NB_PATH = PROJECT_ROOT / "kaggle_indexer" / "build_index_kaggle.ipynb"
OUTPUT_DIR = PROJECT_ROOT / "qdrant_db"
ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "kaggle_download"


def step_1_validate_notebook() -> bool:
    print("\n" + "="*60, flush=True)
    print("📋 STEP 1: Local AST Compilation & Unit Testing", flush=True)
    print("="*60, flush=True)
    
    if not NB_PATH.exists():
        print(f"❌ Error: {NB_PATH} does not exist.", flush=True)
        return False
        
    with open(NB_PATH, "r", encoding="utf-8") as f:
        nb = json.load(f)
        
    code_cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
    print(f"🔍 Validating {len(code_cells)} code cells...", flush=True)
    
    for idx, cell in enumerate(code_cells, 1):
        source = "".join(cell.get("source", []))
        clean_lines = [
            f"# {l}" if l.strip().startswith(("!", "%")) else l 
            for l in source.splitlines()
        ]
        clean_code = "\n".join(clean_lines)
        try:
            ast.parse(clean_code)
            print(f"   Cell {idx}: AST Syntax OK ✅", flush=True)
        except SyntaxError as e:
            print(f"   ❌ Syntax Error in Cell {idx}: {e}", flush=True)
            return False
            
    print("✅ All notebook cells passed local AST compilation.\n", flush=True)
    return True


def step_2_push_kernel(accelerator: str = "NvidiaTeslaT4") -> bool:
    print("="*60, flush=True)
    print(f"🚀 STEP 2: Pushing Kernel to Kaggle (Accelerator: {accelerator})", flush=True)
    print("="*60, flush=True)
    import kaggle
    kaggle.api.authenticate()
    
    folder = str(PROJECT_ROOT / "kaggle_indexer")
    print(f"Pushing folder: {folder} ...", flush=True)
    try:
        kaggle.api.kernels_push_cli(folder, timeout=None, acc=accelerator)
        print(f"✅ Successfully pushed to https://www.kaggle.com/code/{KERNEL_SLUG}\n", flush=True)
        return True
    except Exception as e:  # noqa: BLE001 - Kaggle SDK failures are reported and returned to the CLI caller
        print(f"❌ Push failed: {e}", flush=True)
        return False


def step_3_monitor_execution(max_queue_seconds: int = 120, poll_interval: int = 15) -> str:
    print("="*60, flush=True)
    print("⏳ STEP 3: Smart Queue & Execution Monitoring", flush=True)
    print("="*60, flush=True)
    import kaggle
    kaggle.api.authenticate()
    
    # Phase A: Queue Waiting
    print(f"📡 [Phase A] Waiting for GPU Worker Allocation (Max Queue Timeout: {max_queue_seconds}s)...", flush=True)
    queue_start = time.time()
    is_running = False
    
    while not is_running:
        try:
            status_obj = kaggle.api.kernels_status(KERNEL_SLUG)
            status = str(status_obj.status).upper()
        except Exception as e:  # noqa: BLE001 - transient Kaggle SDK failures are retried
            print(f"   [Notice] API check retry: {e}", flush=True)
            time.sleep(poll_interval)
            continue
            
        elapsed_q = int(time.time() - queue_start)
        
        if "RUNNING" in status:
            print(f"\n🎉 Node provisioned! Status is now ⚡ RUNNING (Waited in queue: {elapsed_q}s)\n", flush=True)
            is_running = True
            break
            
        if "COMPLETE" in status:
            print("\n🎉 Kernel is already COMPLETE!", flush=True)
            return "COMPLETE"
            
        if "ERROR" in status or "FAILED" in status:
            print(f"\n❌ Kernel failed before starting with status: {status}", flush=True)
            return "ERROR"
            
        if "CANCEL" in status:
            print("\n⚠️ Kernel was CANCELLED in queue.", flush=True)
            return "CANCELLED"
            
        print(f"   ⏳ Queue Elapsed: {elapsed_q:02d}s / {max_queue_seconds}s | Status: {status}", flush=True)
        
        if elapsed_q >= max_queue_seconds:
            print(f"\n⚠️ Queue timeout ({max_queue_seconds}s exceeded)! GPU pool is currently congested.", flush=True)
            print("   You can cancel the run on Kaggle Web or retry in Interactive Edit mode.", flush=True)
            return "QUEUE_TIMEOUT"
            
        time.sleep(poll_interval)
        
    # Phase B: Execution Monitoring (Active RUNNING state)
    print("🚀 [Phase B] Monitoring Live GPU Execution (CUDA Batch Encoding)...", flush=True)
    exec_start = time.time()
    
    while True:
        try:
            status_obj = kaggle.api.kernels_status(KERNEL_SLUG)
            status = str(status_obj.status).upper()
            failure_msg = getattr(status_obj, "failure_message", None)
        except Exception as e:  # noqa: BLE001 - transient Kaggle SDK failures are retried
            print(f"   [Notice] API check retry: {e}", flush=True)
            time.sleep(poll_interval)
            continue
            
        elapsed_exec = int(time.time() - exec_start)
        mins, secs = divmod(elapsed_exec, 60)
        
        print(f"   ⚡ Execution Time: {mins:02d}:{secs:02d} | Status: {status}", flush=True)
        
        if "COMPLETE" in status:
            print(f"\n🎉 Kernel execution COMPLETED successfully in {mins}m {secs}s!", flush=True)
            return "COMPLETE"
            
        if "ERROR" in status or "FAILED" in status:
            print(f"\n❌ Kernel execution FAILED after {mins}m {secs}s.", flush=True)
            if failure_msg:
                print(f"   Failure Detail: {failure_msg}", flush=True)
            return "ERROR"
            
        if "CANCEL" in status:
            print(f"\n⚠️ Kernel execution was CANCELLED after {mins}m {secs}s.", flush=True)
            return "CANCELLED"
            
        time.sleep(poll_interval)


def step_4_download_and_verify() -> bool:
    print("\n" + "="*60, flush=True)
    print("📦 STEP 4: Downloading Artifact & Integrating into Local Qdrant DB", flush=True)
    print("="*60, flush=True)
    import kaggle
    kaggle.api.authenticate()
    
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading output from {KERNEL_SLUG} to {ARTIFACT_DIR} ...", flush=True)
    try:
        kaggle.api.kernels_output_cli(KERNEL_SLUG, path=str(ARTIFACT_DIR))
    except Exception as e:  # noqa: BLE001 - Kaggle SDK failures are reported and returned to the CLI caller
        print(f"❌ Download error: {e}", flush=True)
        return False
        
    tar_path = ARTIFACT_DIR / "qdrant_vnlegal_lal.tar.gz"
    if not tar_path.exists():
        for f in ARTIFACT_DIR.rglob("*.tar.gz"):
            tar_path = f
            break
            
    if not tar_path.exists():
        print(f"❌ Error: Archive {tar_path} not found in output!", flush=True)
        return False
        
    size_mb = tar_path.stat().st_size / (1024 * 1024)
    print(f"✅ Found artifact: {tar_path.name} ({size_mb:.2f} MB)", flush=True)
    
    # Backup existing qdrant_db
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        backup_dir = PROJECT_ROOT / f"qdrant_db_backup_{int(time.time())}"
        print(f"Creating backup of current qdrant_db to {backup_dir} ...", flush=True)
        shutil.copytree(OUTPUT_DIR, backup_dir)
        shutil.rmtree(OUTPUT_DIR)
        
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Extracting {tar_path.name} into {OUTPUT_DIR} ...", flush=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=PROJECT_ROOT)
        
    # Verify with Qdrant Client
    print("\n🔍 Verifying Vector Collection in Local Qdrant...", flush=True)
    from qdrant_client import QdrantClient
    client = QdrantClient(path=str(OUTPUT_DIR))
    collections = client.get_collections().collections
    print(f"   Available Collections: {[c.name for c in collections]}", flush=True)
    
    collection_name = "vietnam_legal_collection_v1"
    info = client.get_collection(collection_name)
    print(f"   Vector Dimension: {info.config.params.vectors.size}", flush=True)
    print(f"   Total Indexed Points: {info.points_count:,}", flush=True)
    print(f"   Collection Status: {info.status}", flush=True)
    
    if info.points_count > 0:
        print(f"\n🎉 SUCCESS: {info.points_count:,} legal articles indexed & ready in local Qdrant DB!", flush=True)
        return True
    else:
        print("❌ Warning: Collection is empty.", flush=True)
        return False


def main():
    acc = sys.argv[1] if len(sys.argv) > 1 else "NvidiaTeslaT4"
    queue_timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    
    print("🚀 Starting Automated Kaggle Pipeline for VNLegal-LAL Indexer...", flush=True)
    
    # 1. Local Validate
    if not step_1_validate_notebook():
        sys.exit(1)
        
    # 2. Push to Kaggle
    if not step_2_push_kernel(accelerator=acc):
        sys.exit(1)
        
    # 3. Smart Monitor (Queue timeout + Execution tracking)
    result = step_3_monitor_execution(max_queue_seconds=queue_timeout, poll_interval=15)
    
    if result == "QUEUE_TIMEOUT":
        print("\n💡 Gợi ý: Bạn có thể mở notebook trên Kaggle Web bấm Edit để chạy ngay tức thì (không qua hàng đợi).", flush=True)
        sys.exit(2)
        
    if result != "COMPLETE":
        # Fetch log if error
        try:
            import kaggle
            kaggle.api.kernels_output_cli(KERNEL_SLUG, path=str(ARTIFACT_DIR))
            for f in ARTIFACT_DIR.rglob("*.log"):
                print(f"\n📋 FAILURE LOG TAIL:\n{f.read_text(encoding='utf-8', errors='ignore')[-3000:]}", flush=True)
        except Exception as exc:  # noqa: BLE001 - failure-log collection must not hide the original run failure
            print(f"Notice: unable to collect Kaggle failure logs: {exc}", flush=True)
        sys.exit(1)
        
    # 4. Download & Verify
    if not step_4_download_and_verify():
        sys.exit(1)
        
    print("\n✨ All steps finished successfully!", flush=True)


if __name__ == "__main__":
    main()
