"""Static checks for intended deterministic workflow triggers and ignore rules."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TRIGGERS = """on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
"""


def test_ci_and_promptfoo_run_for_pr_main_push_and_manual_dispatch() -> None:
    for filename in ("ci.yml", "promptfoo-eval.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        assert EXPECTED_TRIGGERS in text


def test_new_source_and_skill_paths_are_not_ignored() -> None:
    paths = (
        "src/vietnam_legal_agent/agent/new_agent_module.py",
        "src/vietnam_legal_agent/tools/new_tool.py",
        ".agents/skills/legal-evidence-engineering/SKILL.md",
        "skills/vietnam-legal-source-verifier/SKILL.md",
    )
    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 1, f"Git unexpectedly ignores {path}"


def test_root_local_scratch_remains_ignored() -> None:
    paths = ("agent/local-only.txt", "tools/local-only.exe", ".agents/teamwork/private-note.md")
    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, f"Expected local scratch to remain ignored: {path}"
