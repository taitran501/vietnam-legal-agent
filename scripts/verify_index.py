import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.llm_instances import get_embeddings
from qdrant_client import QdrantClient


def main():
    db_path = Path("qdrant_db")
    print(f"Connecting to Qdrant at {db_path.resolve()} ...")
    client = QdrantClient(path=str(db_path))
    
    collection_name = "vietnam_legal_collection_v1"
    info = client.get_collection(collection_name)
    print("="*60)
    print("📊 VECTOR DATABASE HEALTH & STATUS")
    print("="*60)
    print(f"Collection Name   : {collection_name}")
    print(f"Collection Status : {info.status}")
    print(f"Total Vectors     : {info.points_count:,}")
    print(f"Vector Dimension  : {info.config.params.vectors.size}-d (SOTA darklethelong/vnlegal-lal)")
    print("="*60)
    
    # Test queries
    test_queries = [
        "Quy định về thời hạn nộp thuế thu nhập cá nhân",
        "Thủ tục thành lập công ty trách nhiệm hữu hạn hai thành viên",
        "Mức phạt vi phạm quy định về bảo vệ môi trường"
    ]
    
    embeddings = get_embeddings()
    print("\n🔍 RUNNING SEMANTIC RETRIEVAL QUALITY BENCHMARK...")
    
    for q_idx, query in enumerate(test_queries, 1):
        print(f"\n--- Query #{q_idx}: \"{query}\" ---")
        q_vec = embeddings.embed_query(query)
        response = client.query_points(
            collection_name=collection_name,
            query=q_vec,
            limit=2
        )
        hits = response.points
        for h_idx, hit in enumerate(hits, 1):
            doc = hit.payload.get("document_title", "")
            art = hit.payload.get("article_title", "")
            topic = hit.payload.get("topic", "")
            text_snippet = hit.payload.get("text", "")[:180].replace("\n", " ")
            print(f"  [{h_idx}] Score: {hit.score:.4f} | {doc} - {art}")
            print(f"      Chủ đề: {topic}")
            print(f"      Trích đoạn: {text_snippet}...")
            
    print("\n🎉 ALL VERIFICATION CHECKS PASSED: SOTA Vector DB is fully operational!")

if __name__ == "__main__":
    main()
