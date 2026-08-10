"""
Comprehensive Performance Test - With Cache Clearing

This executable benchmark measures real workflow performance by:
1. Clearing all caches before each test
2. Testing 20+ diverse queries
3. Measuring EXACT time for each pipeline stage
4. Identifying actual bottlenecks (not assumptions)

Usage:
    python tests/eval/test_performance_deep.py
"""

# This standalone benchmark reports arbitrary service failures and writes one
# report after the async measurement loop has completed.
# ruff: noqa: BLE001, ASYNC230

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)



# ---------------------------------------------------------------------------
# Test Queries - Comprehensive Coverage
# ---------------------------------------------------------------------------

TEST_QUERIES = [
    # CHITCHAT (5 cases)
    {"id": "chat_01", "query": "Xin chào", "type": "chitchat"},
    {"id": "chat_02", "query": "Bạn là ai?", "type": "chitchat"},
    {"id": "chat_03", "query": "Cảm ơn bạn", "type": "chitchat"},
    {"id": "chat_04", "query": "Tạm biệt", "type": "chitchat"},
    {"id": "chat_05", "query": "Bạn có thể làm gì?", "type": "chitchat"},
    
    # Common legal questions (5 cases; FAQ is evaluation-only, never a route)
    {"id": "common_01", "query": "Các đối tượng nào phải thực hiện trách nhiệm tái chế?", "type": "legal_common"},
    {"id": "common_02", "query": "Bao bì thương phẩm là gì?", "type": "legal_common"},
    {"id": "common_03", "query": "Khi nào nhà sản xuất phải bắt đầu thực hiện trách nhiệm tái chế?", "type": "legal_common"},
    {"id": "common_04", "query": "Trường hợp nào không phải thực hiện trách nhiệm tái chế?", "type": "legal_common"},
    {"id": "common_05", "query": "Dầu nhớt có phải tái chế bắt buộc không?", "type": "legal_common"},
    
    # LEGAL - Explicit article numbers (5 cases)
    {"id": "legal_01", "query": "Điều 77 quy định gì?", "type": "legal_explicit"},
    {"id": "legal_02", "query": "Điều 80 nói về gì?", "type": "legal_explicit"},
    {"id": "legal_03", "query": "Điều 81 quy định gì?", "type": "legal_explicit"},
    {"id": "legal_04", "query": "Điều 78 có nội dung gì?", "type": "legal_explicit"},
    {"id": "legal_05", "query": "Điều 79 quy định những gì?", "type": "legal_explicit"},
    
    # LEGAL - Keyword-based (5 cases)
    {"id": "legal_kw_01", "query": "Điều kiện cơ sở tái chế", "type": "legal_keyword"},
    {"id": "legal_kw_02", "query": "Xử phạt vi phạm nghĩa vụ", "type": "legal_keyword"},
    {"id": "legal_kw_03", "query": "Đăng ký kế hoạch tái chế", "type": "legal_keyword"},
    {"id": "legal_kw_04", "query": "Tỷ lệ tái chế bao bì", "type": "legal_keyword"},
    {"id": "legal_kw_05", "query": "Hệ số đóng góp tài chính", "type": "legal_keyword"},
    
    # CACHE HITS - Same queries repeated (5 cases)
    {"id": "cache_01", "query": "Các đối tượng nào phải thực hiện trách nhiệm tái chế?", "type": "cache_hit"},
    {"id": "cache_02", "query": "Xin chào", "type": "cache_hit"},
    {"id": "cache_03", "query": "Điều 77 quy định gì?", "type": "cache_hit"},
    {"id": "cache_04", "query": "Bao bì thương phẩm là gì?", "type": "cache_hit"},
    {"id": "cache_05", "query": "Điều kiện cơ sở tái chế", "type": "cache_hit"},
]


async def clear_all_caches():
    """Clear only the legal-only answer cache for a clean benchmark run."""
    try:
        from backend.memory.session_store import get_redis
        r = await get_redis()
        exact_keys = await r.keys("legal:answer:v3:*")
        if exact_keys:
            await r.delete(*exact_keys)
    except Exception as e:
        print(f"Warning: Could not clear Redis cache: {e}")
    
    print("  ✅ Caches cleared")


@dataclass
class StageTiming:
    name: str
    duration_ms: float
    start_offset_ms: float


@dataclass
class QueryResult:
    query_id: str
    query: str
    query_type: str
    ttft_ms: float  # Time to first token
    total_ms: float  # Total time
    token_count: int
    token_rate: float  # tokens/sec during streaming
    source: str
    stages: list[StageTiming] = field(default_factory=list)
    error: str = ""


async def run_single_query(test_case: dict, clear_cache_before: bool = True) -> QueryResult:
    """Test a single query with full timing breakdown."""
    query = test_case["query"]
    query_id = test_case["id"]
    query_type = test_case["type"]
    
    # Clear caches if requested
    if clear_cache_before:
        await clear_all_caches()
    
    result = QueryResult(
        query_id=query_id,
        query=query[:80],
        query_type=query_type,
        ttft_ms=0,
        total_ms=0,
        token_count=0,
        token_rate=0,
        source="",
    )
    
    session_id = f"perf_{query_id}_{int(time.time())}"
    stage_start = time.perf_counter()
    global_start = stage_start
    first_token_time = None
    full_text = ""
    stage_events = []
    
    try:
        from epr_agent.agent.runtime import stream_chat
        async for event in stream_chat(
            query=query,
            user_id="performance-local",
            conversation_id=session_id,
        ):
            now = time.perf_counter()
            elapsed_ms = (now - global_start) * 1000
            event_type = event.get("type", "")
            
            if event_type == "status":
                stage_name = event.get("stage", "unknown")
                stage_duration = (now - stage_start) * 1000
                result.stages.append(StageTiming(
                    name=stage_name,
                    duration_ms=stage_duration,
                    start_offset_ms=elapsed_ms - stage_duration,
                ))
                stage_start = now
                stage_events.append(f"{elapsed_ms:.0f}ms: {event.get('message', '')}")
            
            elif event_type == "response_chunk":
                chunk = event.get("chunk", "")
                full_text += chunk
                result.token_count += len(chunk.split())  # Approximate word count
                
                if first_token_time is None:
                    first_token_time = now
                    result.ttft_ms = (now - global_start) * 1000
            
            elif event_type == "response_complete":
                result.source = event.get("source", "")
                result.total_ms = (now - global_start) * 1000
                
                # Record final stage
                stage_duration = (now - stage_start) * 1000
                result.stages.append(StageTiming(
                    name="complete",
                    duration_ms=stage_duration,
                    start_offset_ms=elapsed_ms - stage_duration,
                ))
                
                # Calculate streaming token rate
                streaming_time = result.total_ms - result.ttft_ms
                if streaming_time > 0 and result.token_count > 0:
                    result.token_rate = result.token_count / (streaming_time / 1000)
                
                break
    
    except Exception as e:
        result.error = str(e)
        result.total_ms = (time.perf_counter() - global_start) * 1000
    
    return result


def print_detailed_result(result: QueryResult):
    """Print detailed breakdown for a single query."""
    print(f"\n{'='*90}")
    print(f"📝 QUERY: {result.query}")
    print(f"🏷️  TYPE: {result.query_type}")
    print(f"🆔 ID: {result.query_id}")
    print(f"{'='*90}")
    
    if result.error:
        print(f"❌ ERROR: {result.error}")
        return
    
    # Timing summary
    print("\n⏱️  TIMING BREAKDOWN:")
    print(f"  Time to First Token:  {result.ttft_ms:>8.0f}ms ({result.ttft_ms/1000:.2f}s)")
    print(f"  Total Time:           {result.total_ms:>8.0f}ms ({result.total_ms/1000:.2f}s)")
    print(f"  Streaming Time:       {(result.total_ms - result.ttft_ms):>8.0f}ms")
    print(f"  Token Rate:           {result.token_rate:>8.1f} words/sec")
    print(f"  Source:               {result.source}")
    
    # Stage-by-stage breakdown
    if result.stages:
        print("\n📊 STAGE-BY-STAGE BREAKDOWN:")
        print(f"  {'Stage':<25} {'Start':>8} {'Duration':>10} {'% of Total':>12}")
        print(f"  {'-'*58}")
        
        # Filter out the misleading 'complete' stage from percentage calculation
        # The 'complete' stage in the test includes streaming time, which is wrong
        # We'll show actual streaming vs post-processing breakdown
        streaming_start = None
        streaming_end = None
        
        for i, stage in enumerate(result.stages):
            if stage.name in ['chitchat', 'generation', 'web_search']:
                # These are streaming stages
                if streaming_start is None:
                    streaming_start = stage.start_offset_ms
                streaming_end = stage.start_offset_ms + stage.duration_ms
            
            if stage.name not in ['complete', 'cache']:
                stage.start_offset_ms + stage.duration_ms
        
        # Calculate actual metrics
        (streaming_end - streaming_start) if (streaming_start is not None and streaming_end is not None) else 0
        actual_post_processing = result.total_ms - (streaming_end if streaming_end else result.total_ms)
        
        # For cache hits with no streaming, user-perceived time is the total time
        user_perceived_time = streaming_end if streaming_end else result.total_ms
        
        for stage in result.stages:
            # For the 'complete' stage, show the actual post-processing time, not the misleading duration
            if stage.name == 'complete':
                display_duration = actual_post_processing
            else:
                display_duration = stage.duration_ms
            
            pct = (display_duration / result.total_ms * 100) if result.total_ms > 0 else 0
            print(f"  {stage.name:<25} {stage.start_offset_ms:>6.0f}ms {display_duration:>8.0f}ms {pct:>10.1f}%")
        
        # Add summary line
        print(f"\n  {'💡 User-Perceived Time:':<25} {user_perceived_time:>6.0f}ms (response fully received)")
        print(f"  {'🔄 Background Tasks:':<25} {actual_post_processing:>6.0f}ms (user doesn't wait)")
    
    # Verdict
    print(f"\n{'='*90}")
    if result.ttft_ms < 2000:
        verdict = "✅ EXCELLENT (<2s)"
    elif result.ttft_ms < 4000:
        verdict = "⚠️ ACCEPTABLE (2-4s)"
    else:
        verdict = "❌ SLOW (>4s)"
    print(f"VERDICT: {verdict}")
    print(f"{'='*90}")


def print_comprehensive_summary(results: list[QueryResult]):
    """Print comprehensive summary across all queries."""
    print(f"\n\n{'='*90}")
    print("📊 COMPREHENSIVE PERFORMANCE SUMMARY")
    print(f"{'='*90}")
    
    # Group by type
    by_type = {}
    for r in results:
        by_type.setdefault(r.query_type, []).append(r)
    
    # Summary table
    print(f"\n{'Type':<20} {'Queries':>8} {'Avg TTFT':>12} {'Avg Total':>12} {'Min TTFT':>10} {'Max TTFT':>10} {'Status':<15}")
    print(f"{'-'*90}")
    
    all_ttft = []
    for query_type, type_results in sorted(by_type.items()):
        ttfts = [r.ttft_ms for r in type_results]
        totals = [r.total_ms for r in type_results]
        all_ttft.extend(ttfts)
        
        avg_ttft = sum(ttfts) / len(ttfts)
        avg_total = sum(totals) / len(totals)
        min_ttft = min(ttfts)
        max_ttft = max(ttfts)
        
        if avg_ttft < 2000:
            status = "✅ EXCELLENT"
        elif avg_ttft < 4000:
            status = "⚠️ ACCEPTABLE"
        else:
            status = "❌ SLOW"
        
        print(f"{query_type:<20} {len(type_results):>8} {avg_ttft:>8.0f}ms {avg_total:>8.0f}ms {min_ttft:>8.0f}ms {max_ttft:>8.0f}ms   {status}")
    
    # Overall statistics
    print(f"\n{'='*90}")
    print("🎯 OVERALL STATISTICS:")
    print(f"{'='*90}")
    
    if all_ttft:
        all_totals = [r.total_ms for r in results]
        
        print("\n📈 TTFT (Time to First Token):")
        print(f"  Average: {sum(all_ttft)/len(all_ttft):.0f}ms ({sum(all_ttft)/len(all_ttft)/1000:.2f}s)")
        sorted_ttft = sorted(all_ttft)
        print(f"  Median:  {sorted_ttft[len(sorted_ttft)//2]:.0f}ms")
        print(f"  Min:     {min(all_ttft):.0f}ms")
        print(f"  Max:     {max(all_ttft):.0f}ms ({max(all_ttft)/1000:.2f}s)")
        print(f"  P50:     {sorted_ttft[int(len(sorted_ttft)*0.5)]:.0f}ms")
        print(f"  P90:     {sorted_ttft[int(len(sorted_ttft)*0.9)]:.0f}ms")
        
        print("\n⏱️  Total Response Time:")
        print(f"  Average: {sum(all_totals)/len(all_totals):.0f}ms ({sum(all_totals)/len(all_totals)/1000:.2f}s)")
        print(f"  Median:  {sorted(all_totals)[len(all_totals)//2]:.0f}ms")
        print(f"  Min:     {min(all_totals):.0f}ms")
        print(f"  Max:     {max(all_totals):.0f}ms ({max(all_totals)/1000:.2f}s)")
    
    # Stage aggregation - Find the REAL bottleneck
    print("\n🔍 BOTTLENECK ANALYSIS (Average time per stage across all queries):")
    print(f"{'='*90}")
    
    stage_totals = {}
    stage_counts = {}
    for r in results:
        for stage in r.stages:
            if stage.name not in stage_totals:
                stage_totals[stage.name] = 0
                stage_counts[stage.name] = 0
            stage_totals[stage.name] += stage.duration_ms
            stage_counts[stage.name] += 1
    
    if stage_totals:
        print(f"\n  {'Stage':<30} {'Avg Time':>12} {'Count':>8} {'% of Total':>12}")
        print(f"  {'-'*65}")
        
        total_all = sum(stage_totals.values())
        for stage_name in sorted(stage_totals.keys(), key=lambda x: stage_totals[x], reverse=True):
            avg = stage_totals[stage_name] / stage_counts[stage_name]
            count = stage_counts[stage_name]
            pct = (stage_totals[stage_name] / total_all * 100) if total_all > 0 else 0
            print(f"  {stage_name:<30} {avg:>8.0f}ms {count:>8} {pct:>10.1f}%")
    
    # Success/failure counts
    passed = sum(1 for r in results if r.ttft_ms < 4000)
    failed = len(results) - passed
    
    print(f"\n{'='*90}")
    print(f"📋 TEST RESULTS: {passed}/{len(results)} queries with TTFT < 4s")
    if failed > 0:
        print("\n❌ FAILED QUERIES (TTFT >= 4s):")
        for r in results:
            if r.ttft_ms >= 4000:
                print(f"  - {r.query_id} ({r.query_type}): {r.ttft_ms:.0f}ms - {r.query[:60]}")
    print(f"{'='*90}")


async def main():
    print("="*90)
    print("🚀 COMPREHENSIVE PERFORMANCE TEST - WITH CACHE CLEARING")
    print(f"Testing {len(TEST_QUERIES)} queries across {len({q['type'] for q in TEST_QUERIES})} categories")
    print("="*90)
    
    results = []
    
    for i, test_case in enumerate(TEST_QUERIES, 1):
        print(f"\n\n[{i}/{len(TEST_QUERIES)}] Testing: {test_case['query'][:70]}")
        print(f"Type: {test_case['type']}")
        
        # Clear cache for every query to get true cold-start performance
        result = await run_single_query(test_case, clear_cache_before=True)
        results.append(result)
        
        # Print detailed result
        print_detailed_result(result)
        
        # Brief pause between tests
        await asyncio.sleep(0.5)
    
    # Print comprehensive summary
    print_comprehensive_summary(results)
    
    # Save results
    output_file = ROOT / "tests" / "eval" / "performance_deep_results.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "test_timestamp": time.time(),
            "total_queries": len(results),
            "results": [asdict(r) for r in results],
            "summary": {
                "avg_ttft_ms": sum(r.ttft_ms for r in results) / len(results),
                "avg_total_ms": sum(r.total_ms for r in results) / len(results),
                "passed_under_4s": sum(1 for r in results if r.ttft_ms < 4000),
                "failed_over_4s": sum(1 for r in results if r.ttft_ms >= 4000),
            }
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Detailed results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
