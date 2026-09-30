"""Autonomous Agent Trajectory Evaluation Harness.

Runs test cases from agent_manifest.py, evaluates step budget efficiency,
tool selection accuracy, termination safety, and groundedness metrics.

Usage:
    python tests/eval/agent_harness.py --suite all
    python tests/eval/agent_harness.py --suite single_hop
    python tests/eval/agent_harness.py --suite assessment
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

# Ensure repo root is on sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.eval.agent_manifest import AGENT_MANIFEST, AgentTestCase
from vietnam_legal_agent.agent.agent_loop import AgentRunConfig, VietnameseLegalAgentRunner
from vietnam_legal_agent.agent.runtime import AgentWorkflowRuntime, WorkflowDependencies
from vietnam_legal_agent.agent.tool_registry import ToolDependencies, set_tool_dependencies
from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.cache import CachedAnswer
from vietnam_legal_agent.tools.evidence import EvidenceEvaluator
from vietnam_legal_agent.tools.history import ContextSnapshot, HistoryGateway
from vietnam_legal_agent.tools.legal_readiness import SyntheticReadyLegalReadinessGate
from vietnam_legal_agent.tools.retrieval import StaticRetrievalGateway

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# MOCKS & DETERMINISTIC TEST STUBS
# ══════════════════════════════════════════════════════════════════════════════


class HarnessHistory(HistoryGateway):
    def __init__(self, active_case: dict[str, Any] | None = None) -> None:
        self.active_case = active_case

    async def initialize(self) -> None: pass
    async def load(self, user_id: str, conversation_id: str, max_messages: int = 6) -> ContextSnapshot:
        return ContextSnapshot(history=[], summary="", active_case=self.active_case)
    async def save_exchange(self, *args, **kwargs) -> int: return 1
    async def save_case(self, *args, **kwargs) -> dict: return {}
    async def clear_case(self, *args, **kwargs) -> None: pass
    async def record_run(self, *args, **kwargs) -> None: pass


class HarnessGeneration:
    async def chitchat(self, query: str, history: list) -> str:
        return "Xin chào! Tôi có thể giúp bạn tra cứu quy định pháp luật Việt Nam."

    async def answer(self, task_type: str, query: str, documents: list, facts: dict) -> str:
        return "Theo căn cứ pháp luật được tìm thấy [1], vấn đề này cần được đối chiếu với nội dung và thời điểm áp dụng của văn bản."

    async def web(self, query: str) -> tuple[str, list[DocumentRecord]]:
        return "Kết quả tìm kiếm web", []

    async def repair(self, answer: str, documents: list, task_type: str) -> str:
        return answer


class HarnessCache:
    def __init__(self, cached_hit: bool = False) -> None:
        self.cached_hit = cached_hit

    async def lookup(self, task_type, query: str, route: str = "legal_lookup"):
        if self.cached_hit:
            cached = CachedAnswer(
                answer="Căn cứ pháp luật được lưu trong câu trả lời trước [1].",
                evidence=[{"content": "Căn cứ pháp luật liên quan đến câu hỏi đã được lưu.", "document_id": "doc-1", "metadata": {"source": "Kho văn bản pháp luật Việt Nam"}}],
                citations=[{"index": 1, "document_id": "doc-1", "label": "Nguồn pháp luật"}],
                source="cache",
            )
            return cached, "cache-key"
        return None, "cache-key"

    async def store(self, *args, **kwargs): pass


def _build_mock_llm_for_case(case: AgentTestCase) -> Any:
    """Build a deterministic LLM response sequence tailored to the test case."""
    responses: list[AIMessage] = []

    if case.category == "single_hop":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "search_legal_provisions",
                    "args": {"query": case.query},
                    "id": "call_1",
                }],
            ),
            AIMessage(content="Căn cứ pháp luật liên quan đến câu hỏi của bạn được trích dẫn tại [1]."),
        ]
    elif case.category == "multi_hop":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": f"{case.query} căn cứ và thủ tục"}, "id": "call_2"}],
            ),
            AIMessage(content="Các căn cứ liên quan đã được đối chiếu tại nguồn pháp luật [1]."),
        ]
    elif case.category in {"assessment_complete", "assessment_exempt"}:
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(content="Từ thông tin bạn nêu, căn cứ pháp luật liên quan cần được xem xét như nguồn [1]."),
        ]
    elif case.category == "assessment_missing_facts":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "ask_user_for_clarification", "args": {"question": "Bạn có thể cho biết nội dung hợp đồng hoặc thỏa thuận liên quan không?"}, "id": "call_1"}],
            ),
        ]
    elif case.category == "checklist":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(
                content="Căn cứ pháp luật được tìm thấy giúp xác định hồ sơ và thủ tục phù hợp [1].",
            ),
        ]
    elif case.category == "fault_tolerance":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": "xử phạt FSF"}, "id": "call_1"}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": "Nghị định 45/2022 xử phạt môi trường"}, "id": "call_2"}],
            ),
            AIMessage(
                content="Nguồn pháp luật liên quan đến thủ tục khiếu nại được tìm thấy [1].",
            ),
        ]
    elif case.category == "budget_enforcement":
        # Returns continuous tool calls to trigger budget stop
        responses = [
            AIMessage(content="", tool_calls=[{"name": "search_legal_provisions", "args": {"query": f"Q_{i}"}, "id": f"c_{i}"}])
            for i in range(10)
        ]
    elif case.category == "cache_hit":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "lookup_answer_cache", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(
                content="Điều 25 Bộ luật Lao động quy định thời gian thử việc tối đa theo từng nhóm công việc [1].",
            ),
        ]
    elif case.category == "chitchat":
        responses = [AIMessage(content="Xin chào! Tôi có thể giúp gì cho bạn?")]
    elif case.category == "out_of_scope":
        responses = [AIMessage(content="Câu hỏi này nằm ngoài phạm vi trợ lý pháp luật.")]
    elif case.category == "layman_vague":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(content="Căn cứ pháp luật liên quan đến câu hỏi của bạn được trích dẫn tại [1]."),
        ]
    elif case.category == "layman_misconception":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(content="Căn cứ pháp luật liên quan đến tình huống của bạn được trích dẫn tại [1]."),
        ]
    elif case.category == "layman_workshop":
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": "search_legal_provisions", "args": {"query": case.query}, "id": "call_1"}],
            ),
            AIMessage(content="Căn cứ pháp luật liên quan đến tình huống bạn kể được trích dẫn tại [1]."),
        ]

    class ProgrammedLLM:
        def __init__(self, message_sequence: list[AIMessage]) -> None:
            self.seq = list(message_sequence)
            self.idx = 0

        async def ainvoke(self, messages: list) -> AIMessage:
            if self.idx < len(self.seq):
                msg = self.seq[self.idx]
                self.idx += 1
                return msg
            return AIMessage(content="Kết thúc phân tích.")

    return ProgrammedLLM(responses)


# ══════════════════════════════════════════════════════════════════════════════
# HARNESS RUNNER & METRICS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class CaseResult:
    case_id: str
    category: str
    passed: bool
    termination_reason: str
    steps_taken: int
    tools_called: list[str]
    latency_ms: float
    failure_reasons: list[str]


class AgentHarness:
    """Evaluation harness for running trajectory test suites."""

    async def run_case(self, case: AgentTestCase) -> CaseResult:
        sample_doc = DocumentRecord(
            content=f"Căn cứ pháp luật liên quan đến câu hỏi: {case.query}. Nội dung nguồn được lưu trong kho văn bản pháp luật Việt Nam để đối chiếu.",
            document_id="doc-1",
            score=0.95,
            source="legal",
            metadata={"source": "Kho văn bản pháp luật Việt Nam", "source_title": "Văn bản pháp luật Việt Nam"},
        )
        legal_docs = [] if case.mock_all_search_empty else [sample_doc]

        tool_deps = ToolDependencies(
            retrieval=StaticRetrievalGateway(legal_documents=legal_docs),
            evidence_evaluator=EvidenceEvaluator(min_docs=1, min_chars=10),
            generation=HarnessGeneration(),
            cache=HarnessCache(cached_hit=case.category == "cache_hit"),
            history=HarnessHistory(active_case=case.active_case),
        )
        set_tool_dependencies(tool_deps)

        workflow_deps = WorkflowDependencies(
            history=tool_deps.history,
            cache=tool_deps.cache,
            retrieval=tool_deps.retrieval,
            evidence=tool_deps.evidence_evaluator,
            generation=tool_deps.generation,
            planner=None,
            legal_readiness=SyntheticReadyLegalReadinessGate(),
        )

        mock_llm = _build_mock_llm_for_case(case)
        runner = VietnameseLegalAgentRunner(
            config=AgentRunConfig(max_steps=case.max_steps_allowed),
            llm=mock_llm,
        )
        runtime = AgentWorkflowRuntime(workflow_deps, runner=runner)

        started = time.perf_counter()
        events: list[dict[str, Any]] = []
        async for event in runtime.stream(query=case.query, user_id="eval_user", conversation_id="eval_conv"):
            events.append(event)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        # Parse results
        complete_event = next((e for e in reversed(events) if e.get("type") == "response_complete"), None)
        tools_called = [e.get("action") for e in events if e.get("type") == "workflow_step" and e.get("action")]

        actual_termination = complete_event.get("termination_reason", "unknown") if complete_event else "no_complete_event"
        actual_answer = complete_event.get("text", "") if complete_event else ""
        step_count = max(1, len([e for e in events if e.get("type") == "workflow_step"]))

        # Check assertion criteria
        failures: list[str] = []

        # 1. Termination Reason Check
        if actual_termination != case.expected_termination and not (
            case.expected_termination == "answer_complete" and actual_termination == "cache_hit"
        ):
            failures.append(f"Termination mismatch: expected '{case.expected_termination}', got '{actual_termination}'")

        # 2. Step Budget Efficiency Check
        if step_count > case.max_steps_allowed:
            failures.append(f"Step budget exceeded: took {step_count} steps (max {case.max_steps_allowed})")

        # 3. Expected Tools Called Check
        for tool in case.expected_tools:
            if tool not in tools_called:
                failures.append(f"Expected tool '{tool}' was not called (called: {tools_called})")

        # 4. Expected Substring in Answer Check
        for substr in case.expected_answer_contains:
            if substr.lower() not in actual_answer.lower():
                failures.append(f"Answer missing expected text: '{substr}'")

        passed = len(failures) == 0
        return CaseResult(
            case_id=case.id,
            category=case.category,
            passed=passed,
            termination_reason=actual_termination,
            steps_taken=step_count,
            tools_called=tools_called,
            latency_ms=latency_ms,
            failure_reasons=failures,
        )

    async def run_suite(self, suite_filter: str = "all") -> list[CaseResult]:
        cases = AGENT_MANIFEST
        if suite_filter != "all":
            cases = [c for c in AGENT_MANIFEST if c.category == suite_filter or suite_filter in c.id.lower()]

        print(f"\n🚀 Running Agent Trajectory Benchmark Suite: '{suite_filter}' ({len(cases)} test cases)\n" + "═" * 80)
        results: list[CaseResult] = []

        for case in cases:
            res = await self.run_case(case)
            results.append(res)
            status_icon = "✅ PASS" if res.passed else "❌ FAIL"
            tools_summary = ", ".join(res.tools_called) if res.tools_called else "(none)"
            print(f"[{status_icon}] {res.case_id:<8} ({res.category:<22}) | {res.steps_taken} steps | {res.latency_ms:>6.1f}ms | tools: {tools_summary}")
            if not res.passed:
                for f in res.failure_reasons:
                    print(f"       ↳ ⚠️ {f}")

        # Summary Report
        passed_count = sum(1 for r in results if r.passed)
        total_count = len(results)
        pass_rate = (passed_count / total_count * 100) if total_count else 0
        avg_steps = sum(r.steps_taken for r in results) / total_count if total_count else 0
        avg_latency = sum(r.latency_ms for r in results) / total_count if total_count else 0

        print("\n" + "═" * 80)
        print("📊 SUMMARY BENCHMARK REPORT:")
        print(f"   • Total Cases   : {total_count}")
        print(f"   • Passed        : {passed_count} ({pass_rate:.1f}%)")
        print(f"   • Failed        : {total_count - passed_count}")
        print(f"   • Avg Steps     : {avg_steps:.2f}")
        print(f"   • Avg Latency   : {avg_latency:.1f}ms")
        print("═" * 80 + "\n")

        return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agent Trajectory Benchmark Suite.")
    parser.add_argument("--suite", default="all", help="Test suite or category to run (default: all)")
    args = parser.parse_args()

    harness = AgentHarness()
    results = asyncio.run(harness.run_suite(args.suite))
    all_passed = all(r.passed for r in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
