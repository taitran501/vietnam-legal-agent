"""
EPR Chatbot Evaluation Runner

Dimensions evaluated per test case:
  1. Routing accuracy   — expected_route vs actual route inferred from pipeline stages
  2. Keyword presence   — fast check, no LLM cost
  3. Faithfulness 0–5   — LLM-as-judge: answer grounded in retrieved docs (faq/legal only)
  4. Relevance   0–5    — LLM-as-judge: answer addresses the question
  5. Completeness 0–5   — LLM-as-judge: answer covers key aspects
  6. Stage latencies    — ms per pipeline stage, total wall time

Usage:
    cd epr_chatbot
    python -m tests.eval.run_eval
    python -m tests.eval.run_eval --no-llm-eval
    # LLM-as-judge (faithfulness needs retrieved docs — bypass cache):
    python -m tests.eval.run_eval --no-cache --output tests/eval/results_with_llm_judge.json
    python -m tests.eval.run_eval --category faq --verbose
    python -m tests.eval.run_eval --cases 10 --output results.json

To shrink committed JSON snapshots (drops final_text, empty judge reasons):
    python -m tests.eval.compact_stored_results
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Suppress noisy LangChain/OpenAI compatibility warnings
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_openai")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain")
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"Pydantic serializer warnings:.*",
)

# ── Bootstrap ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.core import pipeline as pipeline_module

optimized_chatbot_pipeline = pipeline_module.optimized_chatbot_pipeline

CASES_FILE = Path(__file__).parent / "test_cases.json"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    query: str
    stages_hit: list[str] = field(default_factory=list)
    inferred_route: str = ""          # "chitchat" | "vectorstore_faq"
    source: str = ""                  # cache / faq / legal / chitchat
    final_text: str = ""
    documents: list[dict] = field(default_factory=list)
    total_ms: float = 0.0
    stage_ms: dict[str, float] = field(default_factory=dict)
    error: str | None = None


@dataclass
class CaseScore:
    case_id: str
    query: str
    category: str
    notes: str
    # Routing
    expected_route: str
    actual_route: str
    route_correct: bool
    # Source
    source: str
    # Keywords
    expected_keywords: list[str]
    found_keywords: list[str]
    missing_keywords: list[str]
    keyword_hit_rate: float
    # LLM scores (None if --no-llm-eval or chitchat/edge)
    faithfulness: int | None = None
    faithfulness_reason: str = ""
    relevance: int | None = None
    relevance_reason: str = ""
    completeness: int | None = None
    completeness_reason: str = ""
    # Answer text (for debugging keyword misses)
    final_text: str = ""
    # Timing
    total_ms: float = 0.0
    error: str | None = None


# ── Pipeline runner ───────────────────────────────────────────────────────────

async def _run_pipeline(query: str, *, skip_cache: bool = False) -> PipelineResult:
    """Run the chatbot pipeline and collect all events + timing."""
    session_id = f"eval_{uuid.uuid4().hex[:8]}"
    result = PipelineResult(query=query)

    wall_start = time.perf_counter()
    last_event_time = wall_start
    last_stage = ""

    try:
        async for event in optimized_chatbot_pipeline(
            query=query,
            session_id=session_id,
            skip_cache=skip_cache,
        ):
            now = time.perf_counter()
            etype = event.get("type")
            stage = event.get("stage", "")

            if etype == "status":
                # Record elapsed time for the previous stage
                if last_stage:
                    result.stage_ms[last_stage] = (now - last_event_time) * 1000
                result.stages_hit.append(stage)
                last_stage = stage
                last_event_time = now

            elif etype == "response_complete":
                result.final_text = event.get("text", "")
                result.documents = event.get("documents", [])
                result.source = event.get("source", "")

    except Exception as exc:  # noqa: BLE001 - each case records failures instead of aborting the run
        result.error = str(exc)

    result.total_ms = (time.perf_counter() - wall_start) * 1000

    # Infer route from pipeline stages hit
    if "chitchat" in result.stages_hit:
        result.inferred_route = "chitchat"
    elif any(s in result.stages_hit for s in ("faq_retrieval", "generation", "legal_retrieval", "web_search")):
        result.inferred_route = "vectorstore_faq"
    elif result.source == "cache":
        # Cache hit bypasses routing entirely — mark as unknown so we skip route accuracy check
        result.inferred_route = "cache_hit"
    elif result.source == "web_search":
        result.inferred_route = "vectorstore_faq"
    else:
        result.inferred_route = "chitchat"  # fallback

    return result


# ── Scoring ───────────────────────────────────────────────────────────────────

def _check_keywords(answer: str, keywords: list[str]):
    answer_lower = answer.lower()
    found = [kw for kw in keywords if kw.lower() in answer_lower]
    missing = [kw for kw in keywords if kw.lower() not in answer_lower]
    return found, missing


def score_case(
    case: dict[str, Any],
    result: PipelineResult,
    *,
    llm_eval: bool = True,
) -> CaseScore:
    expected_route = case.get("expected_route", "")
    expected_keywords = case.get("expected_keywords", [])

    found_kws, missing_kws = _check_keywords(result.final_text, expected_keywords)
    hit_rate = len(found_kws) / len(expected_keywords) if expected_keywords else 1.0

    # Cache hits bypass routing — do not penalise, route was already correct when cached
    is_cache_hit = result.inferred_route == "cache_hit"
    route_correct = is_cache_hit or (result.inferred_route == expected_route)

    cs = CaseScore(
        case_id=case["id"],
        query=case["query"],
        category=case.get("category", ""),
        notes=case.get("notes", ""),
        expected_route=expected_route,
        actual_route=result.inferred_route if not is_cache_hit else f"cache_hit({expected_route})",
        route_correct=route_correct,
        source=result.source,
        expected_keywords=expected_keywords,
        found_keywords=found_kws,
        missing_keywords=missing_kws,
        keyword_hit_rate=hit_rate,
        final_text=result.final_text,
        total_ms=result.total_ms,
        error=result.error,
    )

    # Only run LLM judge on substantive faq/legal/web_search answers
    should_llm_eval = (
        llm_eval
        and case.get("category") in ("faq", "legal", "edge", "web_search")
        and result.final_text
        and result.source not in ("chitchat",)
        and not result.error
    )

    if should_llm_eval:
        from tests.eval.evaluators import eval_completeness, eval_faithfulness, eval_relevance

        f = eval_faithfulness(case["query"], result.final_text, result.documents)
        cs.faithfulness = f.score
        cs.faithfulness_reason = f.reasoning

        r = eval_relevance(case["query"], result.final_text)
        cs.relevance = r.score
        cs.relevance_reason = r.reasoning

        c = eval_completeness(case["query"], result.final_text)
        cs.completeness = c.score
        cs.completeness_reason = c.reasoning

    return cs


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_all_cases(
    cases: list[dict],
    *,
    llm_eval: bool,
    verbose: bool,
    skip_cache: bool = False,
) -> list[CaseScore]:
    scores: list[CaseScore] = []

    for i, case in enumerate(cases, 1):
        cid = case["id"]
        cat = case.get("category", "")
        sep = f"[{i:02d}/{len(cases)}]"

        print(f"{sep} {cid} ({cat}) — {case['query'][:60]}")

        result = await _run_pipeline(case["query"], skip_cache=skip_cache)

        if result.error:
            print(f"       ❌ ERROR: {result.error}")

        cs = score_case(case, result, llm_eval=llm_eval)
        scores.append(cs)

        route_icon = "✅" if cs.route_correct else "❌"
        cache_tag = " [CACHE]" if cs.source == "cache" else ""
        kw_icon = "✅" if cs.keyword_hit_rate >= 1.0 else ("⚠️" if cs.keyword_hit_rate >= 0.5 else "❌")
        llm_str = ""
        if cs.faithfulness is not None:
            llm_str = f"  F={cs.faithfulness}/5 R={cs.relevance}/5 C={cs.completeness}/5"

        print(
            f"       {route_icon} route={cs.actual_route!r}{cache_tag}  "
            f"{kw_icon} kw={cs.keyword_hit_rate:.0%}  "
            f"⏱ {cs.total_ms:.0f}ms  source={cs.source!r}"
            f"{llm_str}"
        )

        if verbose and cs.missing_keywords:
            print(f"       missing keywords: {cs.missing_keywords}")
        if verbose and cs.final_text and cs.missing_keywords:
            print(f"       answer[:200]: {cs.final_text[:200]!r}")
        if verbose and cs.faithfulness_reason:
            print(f"       faithfulness: {cs.faithfulness_reason}")

    return scores


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(scores: list[CaseScore], *, llm_eval: bool) -> None:
    cats = {}
    for cs in scores:
        cats.setdefault(cs.category, []).append(cs)

    total = len(scores)
    route_correct = sum(1 for s in scores if s.route_correct)
    errors = [s for s in scores if s.error]

    print()
    print("=" * 60)
    print("  EPR CHATBOT EVALUATION REPORT")
    print("=" * 60)

    print()
    print("ROUTING ACCURACY")
    print("-" * 40)
    for cat, cat_scores in sorted(cats.items()):
        correct = sum(1 for s in cat_scores if s.route_correct)
        pct = correct / len(cat_scores) * 100
        icon = "✅" if pct == 100 else ("⚠️" if pct >= 70 else "❌")
        print(f"  {icon} {cat:12s}  {correct}/{len(cat_scores)}  ({pct:.0f}%)")
    total_pct = route_correct / total * 100 if total else 0.0
    icon = "✅" if total_pct >= 90 else ("⚠️" if total_pct >= 70 else "❌")
    print(f"  {icon} {'TOTAL':12s}  {route_correct}/{total}  ({total_pct:.0f}%)")

    kw_cases = [s for s in scores if s.expected_keywords]
    if kw_cases:
        print()
        print("KEYWORD PRESENCE")
        print("-" * 40)
        avg_hit = sum(s.keyword_hit_rate for s in kw_cases) / len(kw_cases)
        full_hit = sum(1 for s in kw_cases if s.keyword_hit_rate >= 1.0)
        print(f"  Average hit rate : {avg_hit:.1%}")
        print(f"  Full match (100%): {full_hit}/{len(kw_cases)}")

    llm_scored = [s for s in scores if s.faithfulness is not None and s.faithfulness >= 0]
    if llm_scored:
        print()
        print("LLM-AS-JUDGE (scale 0–5)")
        print("-" * 40)
        avg_f = sum(float(s.faithfulness) for s in llm_scored) / len(llm_scored)
        avg_r = sum(float(s.relevance) for s in llm_scored) / len(llm_scored)
        avg_c = sum(float(s.completeness) for s in llm_scored) / len(llm_scored)
        print(f"  Faithfulness  : {avg_f:.2f} / 5.0  (n={len(llm_scored)})")
        print(f"  Relevance     : {avg_r:.2f} / 5.0")
        print(f"  Completeness  : {avg_c:.2f} / 5.0")
    elif llm_eval:
        print()
        print("LLM-AS-JUDGE : no scored cases (all chitchat or errors)")

    ok_scores = [s for s in scores if not s.error]
    if ok_scores:
        latencies = sorted(s.total_ms for s in ok_scores)
        p50 = latencies[int(len(latencies) * 0.50)]
        p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
        avg = sum(latencies) / len(latencies)
        print()
        print("LATENCY")
        print("-" * 40)
        print(f"  Average : {avg:.0f} ms")
        print(f"  p50     : {p50:.0f} ms")
        print(f"  p95     : {p95:.0f} ms")
        print(f"  Min     : {latencies[0]:.0f} ms")
        print(f"  Max     : {latencies[-1]:.0f} ms")

        source_counts: dict[str, int] = {}
        for score in ok_scores:
            source = score.source or "unknown"
            source_counts[source] = source_counts.get(source, 0) + 1
        print()
        print("SOURCE DISTRIBUTION")
        print("-" * 40)
        for source, count in sorted(source_counts.items(), key=lambda item: -item[1]):
            print(f"  {source:12s} : {count} ({count/len(ok_scores):.0%})")

    failures = [s for s in scores if not s.route_correct or s.keyword_hit_rate < 0.5]
    if failures:
        print()
        print("CASES NEEDING ATTENTION")
        print("-" * 40)
        for score in failures:
            route_issue = (
                ""
                if score.route_correct
                else f"route: expected {score.expected_route!r} got {score.actual_route!r}"
            )
            keyword_issue = (
                ""
                if score.keyword_hit_rate >= 0.5
                else f"missing keywords: {score.missing_keywords}"
            )
            issues = " | ".join(issue for issue in (route_issue, keyword_issue) if issue)
            print(f"  [{score.case_id}] {score.query[:55]}")
            print(f"    → {issues}")

    if errors:
        print()
        print("ERRORS")
        print("-" * 40)
        for score in errors:
            print(f"  [{score.case_id}] {score.error}")

    print()
    print("=" * 60)


def _compute_summary_metrics(scores: list[CaseScore]) -> dict[str, float]:
    """Compute aggregate metrics used by the quality gate."""
    total = len(scores) or 1
    route_accuracy = sum(1 for s in scores if s.route_correct) / total

    kw_cases = [s for s in scores if s.expected_keywords]
    keyword_hit_rate = (
        sum(s.keyword_hit_rate for s in kw_cases) / len(kw_cases)
        if kw_cases
        else 1.0
    )

    llm_scored = [s for s in scores if s.faithfulness is not None and s.faithfulness >= 0]
    faithfulness = (
        sum(float(s.faithfulness) for s in llm_scored) / len(llm_scored)
        if llm_scored
        else -1.0
    )

    ok_scores = [s for s in scores if not s.error]
    latencies = sorted(s.total_ms for s in ok_scores)
    if latencies:
        p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
    else:
        p95 = float("inf")

    return {
        "route_accuracy": route_accuracy,
        "keyword_hit_rate": keyword_hit_rate,
        "faithfulness": faithfulness,
        "p95_latency_ms": p95,
    }


def _run_quality_gate(scores: list[CaseScore], args) -> bool:
    """Return True if all configured quality gates pass."""
    summary = _compute_summary_metrics(scores)
    failures: list[str] = []

    if summary["route_accuracy"] < args.min_routing_accuracy:
        failures.append(
            f"route_accuracy {summary['route_accuracy']:.2%} < {args.min_routing_accuracy:.2%}"
        )

    if summary["keyword_hit_rate"] < args.min_keyword_hit_rate:
        failures.append(
            f"keyword_hit_rate {summary['keyword_hit_rate']:.2%} < {args.min_keyword_hit_rate:.2%}"
        )

    if summary["faithfulness"] >= 0 and summary["faithfulness"] < args.min_faithfulness:
        failures.append(
            f"faithfulness {summary['faithfulness']:.2f} < {args.min_faithfulness:.2f}"
        )

    if summary["p95_latency_ms"] > args.max_p95_latency_ms:
        failures.append(
            f"p95_latency_ms {summary['p95_latency_ms']:.0f} > {args.max_p95_latency_ms:.0f}"
        )

    print()
    print("QUALITY GATE")
    print("-" * 40)
    print(f"  route_accuracy   : {summary['route_accuracy']:.2%}")
    print(f"  keyword_hit_rate : {summary['keyword_hit_rate']:.2%}")
    if summary["faithfulness"] >= 0:
        print(f"  faithfulness     : {summary['faithfulness']:.2f}")
    else:
        print("  faithfulness     : n/a (LLM judge disabled or no scored cases)")
    print(f"  p95_latency_ms   : {summary['p95_latency_ms']:.0f}")

    if failures:
        print("  status           : FAIL")
        for f in failures:
            print(f"  - {f}")
        return False

    print("  status           : PASS")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="EPR Chatbot Evaluation Runner")
    p.add_argument("--cases", type=int, default=None, help="Max number of cases to run (default: all)")
    p.add_argument("--category", type=str, default=None, help="Filter by category: chitchat|faq|legal|edge")
    p.add_argument("--no-llm-eval", action="store_true", help="Skip LLM-as-judge scoring (faster, no API cost)")
    p.add_argument("--output", type=str, default=None, help="Save JSON results to this file")
    p.add_argument("--verbose", action="store_true", help="Print extra detail per case")
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip semantic cache lookup so retrieval runs every time (needed for faithfulness LLM judge)",
    )
    p.add_argument(
        "--isolated-state",
        action="store_true",
        help=(
            "Disable history and cache writes for a reproducible golden run while "
            "keeping live routing, retrieval, and generation enabled"
        ),
    )
    p.add_argument(
        "--quality-gate",
        action="store_true",
        help="Fail with non-zero exit code if quality thresholds are not met",
    )
    p.add_argument("--min-routing-accuracy", type=float, default=0.90)
    p.add_argument("--min-keyword-hit-rate", type=float, default=0.80)
    p.add_argument("--min-faithfulness", type=float, default=3.0)
    p.add_argument("--max-p95-latency-ms", type=float, default=5000.0)
    return p.parse_args()


def _enable_isolated_state() -> None:
    """Remove persistence/cache side effects from a live retrieval evaluation."""

    async def _ensure_conversation(_user_id: str, conversation_id: str, **_kwargs) -> str:
        return conversation_id

    async def _empty_history(**_kwargs) -> list[dict]:
        return []

    async def _ignore_exchange(*_args, **_kwargs) -> None:
        return None

    async def _ignore_cache_store(*_args, **_kwargs) -> None:
        return None

    pipeline_module.ensure_conversation = _ensure_conversation
    pipeline_module.get_recent_history = _empty_history
    pipeline_module._persist_exchange = _ignore_exchange
    pipeline_module.semantic_cache.store = _ignore_cache_store


def main():
    args = _parse_args()

    if args.isolated_state:
        _enable_isolated_state()

    # Load test cases
    with open(CASES_FILE, encoding="utf-8") as f:
        dataset = json.load(f)
    cases = dataset["cases"]

    # Apply filters
    if args.category:
        cases = [c for c in cases if c.get("category") == args.category]
    if args.cases:
        cases = cases[: args.cases]

    if not cases:
        print("No cases matched the specified filters.")
        sys.exit(1)

    llm_eval = not args.no_llm_eval
    print(f"\nRunning {len(cases)} case(s)   LLM eval: {'yes' if llm_eval else 'no (--no-llm-eval)'}\n")
    if llm_eval and not args.no_cache:
        print(
            "⚠️  Hint: for Faithfulness scores, use --no-cache so answers are not served from cache "
            "(cache responses have no `documents` for the judge).\n"
        )

    try:
        scores = asyncio.run(
            run_all_cases(
                cases,
                llm_eval=llm_eval,
                verbose=args.verbose,
                skip_cache=args.no_cache,
            )
        )
    finally:
        pipeline_module.retrieval.close_qdrant_client()

    print_report(scores, llm_eval=llm_eval)

    if args.quality_gate:
        passed = _run_quality_gate(scores, args)
        if not passed:
            sys.exit(2)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(
            json.dumps([asdict(s) for s in scores], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
