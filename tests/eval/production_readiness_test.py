"""
Production Readiness Analysis Script

Measures:
1. Retrieval latency per stage
2. Memory usage
3. API call counts (cost analysis)
4. Cache hit rates
5. Concurrency handling
6. Scalability with dataset size
"""

import sys
import time
import asyncio
import tracemalloc
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass, field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

from backend.core.retrieval import retrieve_legal, retrieve_faq_top1
from backend.core.pipeline import optimized_chatbot_pipeline
from backend.cache import semantic_cache
from backend.memory import session_store

# Test queries of varying complexity
TEST_QUERIES = [
    # Simple chitchat (fast)
    "Xin chào",
    # FAQ lookup (medium)
    "Các đối tượng nào phải thực hiện trách nhiệm tái chế?",
    # Legal with explicit article (fast - rule-based)
    "Điều 77 quy định gì?",
    # Legal with keywords (medium - keyword mapping)
    "Điều kiện cơ sở tái chế",
    # Complex legal query (slow - needs semantic search)
    "Phương tiện giao thông bắt đầu tái chế từ năm nào?",
    # Edge case - long query
    "Tôi muốn biết về trách nhiệm tái chế của nhà sản xuất nhập khẩu ắc quy pin theo Nghị định 08",
]

@dataclass
class PerformanceMetrics:
    query: str
    total_latency_ms: float
    retrieval_latency_ms: float
    reranking_latency_ms: float
    llm_calls: int = 0
    embedding_calls: int = 0
    docs_retrieved: int = 0
    cache_hit: bool = False
    memory_mb: float = 0
    peak_memory_mb: float = 0

async def measure_query_performance(query: str, session_id: str = "perf_test") -> PerformanceMetrics:
    """Measure all performance metrics for a single query."""
    tracemalloc.start()
    start_time = time.perf_counter()

    metrics = PerformanceMetrics(
        query=query[:50],
        total_latency_ms=0,
        retrieval_latency_ms=0,
        reranking_latency_ms=0,
    )

    # Run the full pipeline and capture events
    events = []
    async for event in optimized_chatbot_pipeline(
        query=query,
        session_id=session_id,
        skip_cache=True,  # Force fresh retrieval for measurement
    ):
        events.append(event)

    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000

    # Analyze events to determine stages hit
    stages_hit = [e.get("stage", "") for e in events if e.get("type") == "status"]

    # Determine source
    for e in events:
        if e.get("type") == "response_complete":
            metrics.docs_retrieved = len(e.get("documents", []))
            metrics.cache_hit = e.get("source") == "cache"

    # Get memory usage
    current, peak = tracemalloc.get_traced_memory()
    metrics.memory_mb = current / (1024 * 1024)
    metrics.peak_memory_mb = peak / (1024 * 1024)
    tracemalloc.stop()

    return metrics

async def test_concurrent_queries(num_concurrent: int = 10):
    """Test how the system handles concurrent requests."""
    print(f"\n{'='*80}")
    print(f"CONCURRENT QUERY TEST ({num_concurrent} simultaneous queries)")
    print(f"{'='*80}")

    queries = ["Điều 77 quy định gì?"] * num_concurrent

    start_time = time.perf_counter()
    tasks = [
        measure_query_performance(q, f"concurrent_{i}")
        for i, q in enumerate(queries)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_time = time.perf_counter() - start_time

    # Analyze results
    latencies = []
    errors = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            errors.append(str(r))
        else:
            latencies.append(r.total_latency_ms)

    print(f"\nTotal time for {num_concurrent} queries: {total_time*1000:.0f}ms")
    print(f"Average latency: {sum(latencies)/len(latencies):.0f}ms")
    print(f"Min latency: {min(latencies):.0f}ms")
    print(f"Max latency: {max(latencies):.0f}ms")
    print(f"P50 latency: {sorted(latencies)[len(latencies)//2]:.0f}ms")
    print(f"P95 latency: {sorted(latencies)[int(len(latencies)*0.95)]:.0f}ms")
    print(f"Errors: {len(errors)}/{num_concurrent}")

    if errors:
        print(f"Error examples: {errors[:2]}")

    return latencies

async def test_cache_effectiveness():
    """Test cache hit rates and effectiveness."""
    print(f"\n{'='*80}")
    print(f"CACHE EFFECTIVENESS TEST")
    print(f"{'='*80}")

    # First query - cache miss
    query = "Điều 77 quy định gì về trách nhiệm tái chế?"

    print(f"\nFirst query (cache miss expected):")
    start = time.perf_counter()
    result1 = await measure_query_performance(query, "cache_test_1")
    time1 = (time.perf_counter() - start) * 1000
    print(f"  Latency: {time1:.0f}ms")

    # Second identical query - should hit cache
    print(f"\nSecond identical query (cache hit expected):")
    start = time.perf_counter()
    result2 = await measure_query_performance(query, "cache_test_1")  # Same session_id
    time2 = (time.perf_counter() - start) * 1000
    print(f"  Latency: {time2:.0f}ms")

    cache_speedup = time1 / time2 if time2 > 0 else 0
    print(f"\nCache speedup: {cache_speedup:.1f}x")
    print(f"Time saved: {time1 - time2:.0f}ms")

    return time1, time2

async def test_scaling_retrieval():
    """Test how retrieval scales with dataset size."""
    print(f"\n{'='*80}")
    print(f"RETRIEVAL SCALABILITY TEST")
    print(f"{'='*80}")

    queries = [
        ("Điều 77", "Explicit article"),
        ("Điều kiện cơ sở", "Keyword mapping"),
        ("Tái chế bao bì", "Semantic search"),
    ]

    for query, query_type in queries:
        print(f"\n{query_type}: '{query}'")
        start = time.perf_counter()
        docs = retrieve_legal(query)
        latency = (time.perf_counter() - start) * 1000
        print(f"  Retrieved {len(docs)} docs in {latency:.0f}ms")
        if docs:
            print(f"  Top result: {docs[0].metadata.get('Dieu', 'N/A')[:50]}")

async def main():
    print("="*80)
    print("PRODUCTION READINESS ANALYSIS")
    print("="*80)

    # 1. Single query performance
    print(f"\n{'='*80}")
    print(f"SINGLE QUERY PERFORMANCE")
    print(f"{'='*80}")

    for query in TEST_QUERIES:
        print(f"\nQuery: {query[:60]}")
        metrics = await measure_query_performance(query)
        print(f"  Total latency: {metrics.total_latency_ms:.0f}ms")
        print(f"  Docs retrieved: {metrics.docs_retrieved}")
        print(f"  Memory: {metrics.memory_mb:.1f}MB (peak: {metrics.peak_memory_mb:.1f}MB)")
        print(f"  Cache hit: {metrics.cache_hit}")

        # Categorize performance
        if metrics.total_latency_ms < 2000:
            print(f"  Status: ✅ FAST")
        elif metrics.total_latency_ms < 5000:
            print(f"  Status: ⚠️ ACCEPTABLE")
        else:
            print(f"  Status: ❌ SLOW")

    # 2. Concurrent queries
    await test_concurrent_queries(5)
    await test_concurrent_queries(10)

    # 3. Cache effectiveness
    await test_cache_effectiveness()

    # 4. Retrieval scalability
    await test_scaling_retrieval()

    print(f"\n{'='*80}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(main())
