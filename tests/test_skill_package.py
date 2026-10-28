"""Integrity checks for the standalone legal source verifier skill."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from scripts.validate_skill_package import PACKAGE_DIR, create_package_zip, parse_frontmatter, validate_package


def test_skill_package_metadata_links_and_evaluation_cases_are_valid() -> None:
    assert validate_package(PACKAGE_DIR) == []


def test_frontmatter_requires_agent_skill_fields() -> None:
    parsed = parse_frontmatter("---\nname: example\ndescription: Verify official legal sources.\n---\n\nBody\n")

    assert parsed["name"] == "example"
    assert parsed["description"] == "Verify official legal sources."


def test_package_validator_rejects_name_mismatch_and_broken_links(tmp_path: Path) -> None:
    package = tmp_path / "vietnam-legal-source-verifier"
    shutil.copytree(PACKAGE_DIR, package)
    skill = package / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace(
            "name: vietnam-legal-source-verifier", "name: wrong-name", 1
        ).replace("references/official-sources.md", "references/missing.md", 1),
        encoding="utf-8",
    )

    errors = validate_package(package)

    assert any("name must match" in error for error in errors)
    assert any("Broken relative link" in error for error in errors)


def test_zip_contains_only_the_skill_package(tmp_path: Path) -> None:
    archive_path = tmp_path / "vietnam-legal-source-verifier.zip"

    assert create_package_zip(PACKAGE_DIR, archive_path) == []
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()

    assert names
    assert all(name.startswith("vietnam-legal-source-verifier/") for name in names)
    assert "vietnam-legal-source-verifier/SKILL.md" in names
    assert "vietnam-legal-source-verifier/tests/evaluation-cases.json" in names
    assert not any(name.startswith(("backend/", "data/", "src/")) for name in names)
