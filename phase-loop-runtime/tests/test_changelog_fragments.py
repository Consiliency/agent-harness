"""changelog.d/ fragments and their release-cut assembler (scripts/assemble_changelog.py)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"

# The assembler and the fragments are repository source, not wheel data, so Gate A's
# standalone tree cannot evaluate these.
pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file(), reason="repo-only changelog assembler absent from standalone-from-wheel layout"
)


def _module():
    spec = importlib.util.spec_from_file_location("assemble_changelog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Hand-written entry

- old

## [0.7.26] - 2026-10-09

### Previous
"""


def _repo(tmp_path: Path, fragments: dict[str, str], changelog: str = CHANGELOG) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    directory = tmp_path / "changelog.d"
    directory.mkdir()
    (directory / "README.md").write_text("# not a fragment\n", encoding="utf-8")
    for name, text in fragments.items():
        (directory / name).write_text(text, encoding="utf-8")
    return tmp_path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True, text=True, check=False,
    )


def test_release_cut_puts_fragments_then_hand_entries_under_the_version(tmp_path):
    root = _repo(tmp_path, {
        "20.fix.md": "### Fix twenty\n\n- b\n",
        "9.fix.md": "### Fix nine\n",
        "30.feature.md": "### Feature\n",
        "9.fix.2.md": "### Fix nine, second\n",
    })
    result = _run(root, "--version", "0.7.28", "--date", "2026-10-20")
    assert result.returncode == 0, result.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == """# Changelog

Intro.

## [Unreleased]

## [0.7.28] - 2026-10-20

### Feature

### Fix nine

### Fix nine, second

### Fix twenty

- b

### Hand-written entry

- old

## [0.7.26] - 2026-10-09

### Previous
"""
    assert sorted(p.name for p in (root / "changelog.d").iterdir()) == ["README.md"]


def test_without_version_folds_into_unreleased(tmp_path):
    root = _repo(tmp_path, {"5.ci.md": "### CI\n"})
    assert _run(root).returncode == 0
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]\n\n### CI\n\n### Hand-written entry\n" in text


def test_dry_run_changes_nothing(tmp_path):
    root = _repo(tmp_path, {"5.ci.md": "### CI\n"})
    result = _run(root, "--dry-run", "--version", "1.0.0", "--date", "2026-01-01")
    assert result.returncode == 0
    assert "## [1.0.0] - 2026-01-01\n\n### CI\n" in result.stdout
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG
    assert (root / "changelog.d" / "5.ci.md").is_file()


@pytest.mark.parametrize("name,text", [
    ("fix.md", "### x\n"),
    ("12.bugfix.md", "### x\n"),
    ("012.fix.md", "### x\n"),
    ("12.fix.txt", "### x\n"),
    ("12.fix.md", "no heading\n"),
    ("12.fix.md", "### x\n\n## [9.9.9]\n"),
])
def test_a_malformed_fragment_fails_and_changes_nothing(tmp_path, name, text):
    root = _repo(tmp_path, {name: text})
    for args in (("--check",), ("--version", "1.0.0")):
        result = _run(root, *args)
        assert result.returncode == 1, (args, result.stdout)
        assert name in result.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG
    assert (root / "changelog.d" / name).is_file()


def test_no_unreleased_heading_is_an_error(tmp_path):
    root = _repo(tmp_path, {"5.ci.md": "### CI\n"}, changelog="# Changelog\n")
    result = _run(root, "--version", "1.0.0")
    assert result.returncode == 1
    assert "[Unreleased]" in result.stderr
    assert (root / "changelog.d" / "5.ci.md").is_file()


def test_no_fragments_and_no_version_is_a_no_op():
    module = _module()
    assert module.assemble(CHANGELOG, [], None, "2026-01-01") == CHANGELOG


def test_committed_fragments_are_well_formed():
    # Runs on every pull request: a bad fragment name or heading fails here, not at the cut.
    result = _run(REPO_ROOT, "--check")
    assert result.returncode == 0, result.stderr
    assert "## [Unreleased]" in (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()


def test_the_docs_audit_accepts_exactly_the_assembled_names():
    # The audit's fragment glob and the assembler's name rule must agree on what is an entry.
    from phase_loop_runtime import docs_surfaces as ds

    module = _module()
    for name, is_entry in (("12.fix.md", True), ("12.fix.2.md", True), ("README.md", False)):
        assert ds._match(f"changelog.d/{name}", ds.CHANGELOG_FRAGMENT_GLOB) is is_entry, name
        assert (module._NAME.fullmatch(name) is not None) is is_entry, name
