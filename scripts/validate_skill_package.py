"""Validate and optionally zip the portable Agent Skills package."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "skills" / "vietnam-legal-source-verifier"
EXPECTED_NAME = "vietnam-legal-source-verifier"
REQUIRED_FILES = {
    "SKILL.md",
    "LICENSE",
    "references/official-sources.md",
    "references/citation-policy.md",
    "references/legal-limitations.md",
    "tests/evaluation-cases.json",
}
EXPECTED_CATEGORIES = {
    "clear_source_and_provision",
    "current_effect_and_amendment",
    "conflicting_sources",
    "missing_facts",
    "insufficient_sources_refusal",
    "citations_and_scope",
}
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def parse_frontmatter(markdown: str) -> dict[str, str]:
    """Parse the simple scalar fields required by this package's YAML header."""
    normalized = markdown.lstrip("\ufeff")
    if not normalized.startswith("---\n"):
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    closing = normalized.find("\n---\n", 4)
    if closing < 0:
        raise ValueError("YAML frontmatter has no closing delimiter")
    result: dict[str, str] = {}
    for line in normalized[4:closing].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in result:
            raise ValueError(f"Duplicate frontmatter key: {key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def _local_link_target(destination: str) -> str | None:
    destination = destination.strip()
    if destination.startswith("<") and destination.endswith(">"):
        destination = destination[1:-1]
    parsed = urlsplit(destination)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return unquote(parsed.path)


def validate_package(package_dir: Path = PACKAGE_DIR) -> list[str]:
    """Return validation errors for package metadata, references, and contents."""
    package_dir = package_dir.resolve()
    errors: list[str] = []
    if not package_dir.is_dir():
        return [f"Package directory does not exist: {package_dir}"]
    if package_dir.name != EXPECTED_NAME:
        errors.append(f"Package directory must be named {EXPECTED_NAME}")

    files = sorted(path for path in package_dir.rglob("*") if path.is_file())
    relative_files = {path.relative_to(package_dir).as_posix() for path in files}
    for required in sorted(REQUIRED_FILES - relative_files):
        errors.append(f"Missing required package file: {required}")

    for path in files:
        try:
            path.resolve().relative_to(package_dir)
        except ValueError:
            errors.append(f"Package file escapes package directory: {path.relative_to(package_dir)}")
        if path.suffix.lower() in {".py", ".parquet", ".sqlite", ".sqlite3", ".db", ".whl"}:
            errors.append(f"Application code, data, or dependency artifact is not allowed: {path.relative_to(package_dir)}")

    skill_path = package_dir / "SKILL.md"
    if skill_path.is_file():
        try:
            frontmatter = parse_frontmatter(skill_path.read_text(encoding="utf-8"))
            if not frontmatter.get("name"):
                errors.append("SKILL.md frontmatter requires a non-empty name")
            elif frontmatter["name"] != package_dir.name:
                errors.append("SKILL.md frontmatter name must match the package directory")
            if not frontmatter.get("description"):
                errors.append("SKILL.md frontmatter requires a non-empty description")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"Invalid SKILL.md frontmatter: {exc}")

    for markdown_path in (p for p in files if p.suffix.lower() == ".md"):
        try:
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"Cannot read {markdown_path.relative_to(package_dir)}: {exc}")
            continue
        for destination in LINK_PATTERN.findall(markdown):
            target = _local_link_target(destination)
            if target is None:
                continue
            resolved = (markdown_path.parent / target).resolve()
            try:
                resolved.relative_to(package_dir)
            except ValueError:
                errors.append(f"Relative link escapes package: {markdown_path.relative_to(package_dir)} -> {destination}")
                continue
            if not resolved.exists():
                errors.append(f"Broken relative link: {markdown_path.relative_to(package_dir)} -> {destination}")

    cases_path = package_dir / "tests" / "evaluation-cases.json"
    if cases_path.is_file():
        try:
            payload = json.loads(cases_path.read_text(encoding="utf-8"))
            cases = payload["cases"]
            categories = payload["categories"]
            if len(cases) != 24:
                errors.append(f"Expected exactly 24 evaluation cases, found {len(cases)}")
            counts = Counter(case["category"] for case in cases)
            if set(categories) != EXPECTED_CATEGORIES:
                errors.append("Evaluation cases must declare all six required categories")
            if set(counts) != EXPECTED_CATEGORIES or any(counts[category] != 4 for category in EXPECTED_CATEGORIES):
                errors.append("Evaluation cases must contain exactly four cases in each required category")
            ids = [case["id"] for case in cases]
            if len(ids) != len(set(ids)):
                errors.append("Evaluation case IDs must be unique")
            for index, case in enumerate(cases):
                if not case.get("prompt") or not case.get("expected_behaviors") or not case.get("critical_failures"):
                    errors.append(f"Evaluation case {index + 1} is missing prompt or rubric fields")
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"Invalid evaluation cases JSON: {exc}")

    if not (package_dir / "LICENSE").is_file():
        errors.append("Portable skill package requires its own LICENSE")
    return errors


def create_package_zip(package_dir: Path, output: Path) -> list[str]:
    """Create a ZIP containing only package files under their package directory."""
    package_dir = package_dir.resolve()
    output = output.resolve()
    try:
        output.relative_to(package_dir)
    except ValueError:
        pass
    else:
        return ["ZIP output must be outside the package directory"]

    errors = validate_package(package_dir)
    if errors:
        return errors
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in package_dir.rglob("*") if p.is_file()):
            archive.write(path, Path(package_dir.name) / path.relative_to(package_dir))

    expected = {
        (Path(package_dir.name) / path.relative_to(package_dir)).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        if names != expected:
            errors.append("ZIP contents do not exactly match files under the skill package directory")
        for name in names:
            candidate = Path(name)
            if candidate.is_absolute() or ".." in candidate.parts or not name.startswith(f"{package_dir.name}/"):
                errors.append(f"Unsafe or out-of-package ZIP path: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=PACKAGE_DIR)
    parser.add_argument("--output", type=Path, help="Optional ZIP output path, outside the package directory")
    args = parser.parse_args()
    errors = create_package_zip(args.package_dir, args.output) if args.output else validate_package(args.package_dir)
    if errors:
        print("Skill package validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if args.output:
        print(f"Validated skill package and wrote {args.output.resolve()}")
    else:
        print("Skill package is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
