"""
End-to-End Test for the Complete Legal RAG Pipeline (Retrieval -> Evidence Evaluation -> Answer Generation).
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from backend.core.retrieval import retrieve_legal_async

from epr_agent.api.routes import stream_chat_events


async def test_rag_flow():
    print("="*70)
    print("⚖️ TESTING END-TO-END VIETNAMESE LEGAL RAG PIPELINE")
    print("="*70)
    
    test_queries = [
        "Thủ tục thành lập doanh nghiệp tư nhân cần những giấy tờ gì?",
        "Thời hạn nộp hồ sơ quyết toán thuế thu nhập cá nhân là khi nào?",
        "Người lao động đơn phương chấm dứt hợp đồng lao động không xác định thời hạn phải báo trước bao nhiêu ngày?"
    ]
    
    # 1. Test Direct Legal Retrieval
    print("\n🔍 --- PHASE 1: DIRECT HYBRID RETRIEVAL (ENSEMBLE / QDRANT) ---")
    for idx, query in enumerate(test_queries, 1):
        print(f"\n[Query #{idx}]: \"{query}\"")
        t0 = time.time()
        docs = await retrieve_legal_async(query, top_k=3)
        elapsed = (time.time() - t0) * 1000
        print(f"⚡ Retrieved {len(docs)} documents in {elapsed:.1f}ms")
        for d_idx, doc in enumerate(docs, 1):
            title = doc.metadata.get("article_title") or doc.metadata.get("Dieu") or "N/A"
            source = doc.metadata.get("document_title") or doc.metadata.get("source") or "N/A"
            content_preview = doc.page_content[:150].replace("\n", " ")
            print(f"   ({d_idx}) Source: {source[:60]}... | {title}")
            print(f"       Preview: {content_preview}...")
            
    # 2. Test Agentic Stream Chat Workflow
    print("\n🤖 --- PHASE 2: AGENTIC GRAPH & RAG GENERATION (STREAM_CHAT) ---")
    query = test_queries[0]
    print(f"\n[Running Agent Chat Turn for]: \"{query}\"\n")
    
    t_start = time.time()
    events_received = []
    full_response = []
    
    async for event in stream_chat_events(
        query=query,
        user_id="test-user-001",
        conversation_id="test-conv-001",
        mode="auto"
    ):
        events_received.append(event)
        event_type = event.get("type")
        
        if event_type == "status":
            step = event.get("step") or event.get("label") or ""
            print(f"   [Agent Step]: ⚡ {step}")
        elif event_type == "response_chunk" or event_type == "token":
            chunk = event.get("delta") or event.get("content") or event.get("chunk") or ""
            full_response.append(chunk)
        elif event_type == "response_complete" or event_type == "complete":
            print("   [Agent Complete]: Received final answer metadata.")
            citations = event.get("citations", [])
            if citations:
                print(f"   [Citations]: {len(citations)} legal references cited.")
                
    elapsed_total = time.time() - t_start
    final_text = "".join(full_response).strip()
    
    print("\n" + "="*70)
    print("📝 GENERATED FINAL ANSWER:")
    print("="*70)
    print(final_text if final_text else "[Response streamed through events or direct payload]")
    print(f"\n⏱️ Total Turnaround Time: {elapsed_total:.2f}s")
    print(f"📦 Total Stream Events: {len(events_received)}")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(test_rag_flow())
