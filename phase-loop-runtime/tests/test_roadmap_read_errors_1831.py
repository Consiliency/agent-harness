"""Regression tests for typed errors, repo-relative paths, and fix lines in roadmap read paths (agent-harness#1831)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from phase_loop_runtime import cli, discovery, roadmap_lint, roadmap_ownership


@pytest.fixture(autouse=True)
def _isolate_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Phase Loop Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Phase Loop Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def _init_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "init", "-q"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def test_required_registry_absent_uses_repo_relative_path_and_fix_line(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    marker = repo / "plans" / "phase-plan-v10-LEGIBLE.md"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("# LEGIBLE\n", encoding="utf-8")

    with pytest.raises(roadmap_lint.MalformedRegistryError) as exc:
        roadmap_lint.validate_roadmap_status_coherence(repo, required=True)
    msg = str(exc.value)
    assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in msg
    assert "/proc/self/fd" not in msg
    assert "/dev/fd" not in msg
    assert str(repo) not in msg
    assert "Fix:" in msg


def test_empty_or_non_utf8_registry_and_escape_raise_typed_errors_without_abs_paths(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    registry = repo / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    registry.parent.mkdir(parents=True, exist_ok=True)

    # Empty registry
    registry.write_text("   \n", encoding="utf-8")
    with pytest.raises(roadmap_lint.MalformedRegistryError) as empty_exc:
        roadmap_lint.read_roadmap_status(repo, registry)
    assert str(repo) not in str(empty_exc.value)
    assert "/proc/self/fd" not in str(empty_exc.value)
    assert "/dev/fd" not in str(empty_exc.value)
    assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in str(empty_exc.value)
    assert "Fix:" in str(empty_exc.value)

    # Non-UTF-8 registry
    registry.write_bytes(b"\xff\xfe\x00invalid")
    with pytest.raises(roadmap_lint.MalformedRegistryError) as utf8_exc:
        roadmap_lint.read_roadmap_status(repo, registry)
    assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in str(utf8_exc.value)
    assert str(repo) not in str(utf8_exc.value)
    assert "Fix:" in str(utf8_exc.value)

    # Escaping registry path
    outside = tmp_path / "outside-status.json"
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(roadmap_lint.MalformedRegistryError) as escape_exc:
        roadmap_lint.read_roadmap_status(repo, outside)
    assert outside.name in str(escape_exc.value)
    assert str(tmp_path) not in str(escape_exc.value)
    assert "Fix:" in str(escape_exc.value)

    # Nonexistent repository root raises typed MalformedRegistryError (not raw FileNotFoundError)
    missing_repo = tmp_path / "does-not-exist"
    with pytest.raises(roadmap_lint.MalformedRegistryError) as missing_exc:
        roadmap_lint.read_roadmap_status(missing_repo, missing_repo / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL)
    assert str(tmp_path) not in str(missing_exc.value)
    assert "Fix:" in str(missing_exc.value)


def test_roadmap_lint_main_handles_missing_unreadable_and_non_utf8_files_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)

    # Missing file (passed as absolute path inside repo -> printed repo-relative)
    missing = repo / "specs" / "phase-plans-v99.md"
    assert roadmap_lint.main(["validate_roadmap", str(missing)]) == 2
    err = capsys.readouterr().err
    assert "specs/phase-plans-v99.md" in err
    assert str(repo) not in err
    assert "Fix:" in err

    # Non-UTF-8 file (caught cleanly, never raw UnicodeDecodeError)
    bad_utf8 = repo / "specs" / "phase-plans-v98.md"
    bad_utf8.parent.mkdir(parents=True, exist_ok=True)
    bad_utf8.write_bytes(b"\xff\xfe\x00")
    assert roadmap_lint.main(["validate_roadmap", str(bad_utf8)]) == 2
    err = capsys.readouterr().err
    assert "specs/phase-plans-v98.md" in err
    assert str(repo) not in err
    assert "Fix:" in err

    # Directory passed as roadmap file (caught cleanly, no raw OSError abs path)
    as_dir = repo / "specs" / "phase-plans-v97.md"
    as_dir.mkdir()
    assert roadmap_lint.main(["validate_roadmap", str(as_dir)]) == 2
    err = capsys.readouterr().err
    assert "specs/phase-plans-v97.md" in err
    assert str(repo) not in err
    assert "Fix:" in err


def test_discovery_missing_explicit_and_default_roadmaps_are_typed_and_repo_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)

    # Missing explicit roadmap inside repo: typed RoadmapStatusError + FileNotFoundError, repo-relative + fix line
    missing = repo / "specs" / "phase-plans-v99.md"
    with pytest.raises(roadmap_lint.RoadmapNotFoundError) as exc:
        discovery.select_roadmap(repo, missing)
    assert isinstance(exc.value, roadmap_lint.RoadmapStatusError)
    assert isinstance(exc.value, FileNotFoundError)
    assert "specs/phase-plans-v99.md" in str(exc.value)
    assert str(repo) not in str(exc.value)
    assert "Fix:" in str(exc.value)

    # CLI catches it cleanly as a roadmap status refusal (exit 2, no traceback)
    sentinel = Mock(side_effect=AssertionError("run_loop must not be reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    assert cli.main(["run", "--repo", str(repo), "--roadmap", str(missing)]) == 2
    err = capsys.readouterr().err
    assert "roadmap status refusal" in err
    assert "specs/phase-plans-v99.md" in err
    assert str(repo) not in err
    assert "Fix:" in err
    sentinel.assert_not_called()

    # No roadmap in specs/ at all
    with pytest.raises(roadmap_lint.RoadmapNotFoundError) as empty_exc:
        discovery.select_roadmap(repo)
    assert isinstance(empty_exc.value, roadmap_lint.RoadmapStatusError)
    assert isinstance(empty_exc.value, FileNotFoundError)
    assert "no specs/phase-plans-v*.md roadmap found" in str(empty_exc.value)
    assert "Fix:" in str(empty_exc.value)


def test_roadmap_ownership_resolve_roadmap_omits_absolute_repo_path_and_includes_fix_line(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    with pytest.raises(roadmap_ownership.RoadmapUnreadable) as exc:
        roadmap_ownership.resolve_roadmap(repo)
    msg = str(exc.value)
    assert str(repo) not in msg
    assert str(tmp_path) not in msg
    assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in msg
    assert "Fix:" in msg
