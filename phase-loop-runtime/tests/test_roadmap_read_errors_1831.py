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


def test_git_index_corruption_and_non_utf8_tracked_filename_fail_typed_without_fd_leaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1. Valid registry + corrupt Git index: no /proc/self/fd or /dev/fd leak in CLI or ownership.
    repo_bad_idx = _init_repo(tmp_path / "bad-idx")
    v1 = repo_bad_idx / "specs" / "phase-plans-v1.md"
    v1.parent.mkdir(parents=True, exist_ok=True)
    v1.write_text("# R\n\n> **Status (2026-10-08): ACTIVE — test**\n\n## Phase A\n", encoding="utf-8")
    reg = repo_bad_idx / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    reg.write_text(
        '{"schema":"roadmap_status_manifest.v1","selected_roadmap":"specs/phase-plans-v1.md",'
        '"roadmaps":[{"path":"specs/phase-plans-v1.md","status":"active"}]}\n',
        encoding="utf-8",
    )
    (repo_bad_idx / ".git" / "index").write_bytes(b"NOT_A_VALID_GIT_INDEX")

    sentinel = Mock(side_effect=AssertionError("run_loop must not be reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    assert cli.main(["run", "--repo", str(repo_bad_idx)]) == 2
    err = capsys.readouterr().err
    assert "roadmap status refusal" in err
    assert "/proc/self/fd" not in err
    assert "/dev/fd" not in err
    assert str(repo_bad_idx) not in err
    assert "Git index" in err
    assert "Fix:" in err
    sentinel.assert_not_called()

    with pytest.raises(roadmap_ownership.RoadmapUnreadable) as own_exc:
        roadmap_ownership.resolve_roadmap(repo_bad_idx)
    assert "/proc/self/fd" not in str(own_exc.value)
    assert "/dev/fd" not in str(own_exc.value)
    assert str(repo_bad_idx) not in str(own_exc.value)

    # 2. Non-UTF-8 tracked roadmap filename: typed MalformedRegistryError (never raw UnicodeDecodeError).
    repo_bad_name = _init_repo(tmp_path / "bad-name")
    v2 = repo_bad_name / "specs" / "phase-plans-v1.md"
    v2.parent.mkdir(parents=True, exist_ok=True)
    v2.write_text("# R\n\n> **Status (2026-10-08): ACTIVE — test**\n\n## Phase A\n", encoding="utf-8")
    reg2 = repo_bad_name / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    reg2.write_text(
        '{"schema":"roadmap_status_manifest.v1","selected_roadmap":"specs/phase-plans-v1.md",'
        '"roadmaps":[{"path":"specs/phase-plans-v1.md","status":"active"}]}\n',
        encoding="utf-8",
    )
    bad_path = os.fsencode(repo_bad_name / "specs") + b"/phase-plans-v\xff.md"
    with open(bad_path, "wb") as fh:
        fh.write(b"# bad\n")
    subprocess.run(["git", "add", "-f", "--", bad_path], cwd=repo_bad_name, check=True, capture_output=True)

    assert cli.main(["run", "--repo", str(repo_bad_name)]) == 2
    err = capsys.readouterr().err
    assert "roadmap status refusal" in err
    assert "UTF-8" in err
    assert "Fix:" in err
    assert "Traceback" not in err


def test_registry_directory_and_deleted_target_name_path_and_fix(tmp_path: Path) -> None:
    # 1. Directory at specs/roadmap-status.json names the registry path and fix line.
    repo_dir = _init_repo(tmp_path / "reg-dir")
    (repo_dir / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL).mkdir(parents=True)
    with pytest.raises(roadmap_lint.MalformedRegistryError) as dir_exc:
        roadmap_lint.validate_roadmap_status_coherence(repo_dir, required=True)
    msg = str(dir_exc.value)
    assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in msg
    assert str(repo_dir) not in msg
    assert "Fix:" in msg

    # 2. Valid registry pointing to a deleted roadmap names the missing roadmap path and fix line.
    repo_del = _init_repo(tmp_path / "reg-del")
    reg = repo_del / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        '{"schema":"roadmap_status_manifest.v1","selected_roadmap":"specs/phase-plans-v1.md",'
        '"roadmaps":[{"path":"specs/phase-plans-v1.md","status":"active"}]}\n',
        encoding="utf-8",
    )
    with pytest.raises(roadmap_lint.MalformedRegistryError) as del_exc:
        roadmap_lint.validate_roadmap_status_coherence(repo_del, required=True)
    msg = str(del_exc.value)
    assert "specs/phase-plans-v1.md" in msg
    assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in msg
    assert str(repo_del) not in msg
    assert "Fix:" in msg

    # 3. Valid registry pointing to an unreadable roadmap file names that roadmap (not only the registry).
    if os.getuid() != 0:
        unreadable = repo_del / "specs" / "phase-plans-v1.md"
        unreadable.write_text("# R\n\n> **Status (2026-10-08): ACTIVE — test**\n", encoding="utf-8")
        unreadable.chmod(0o000)
        try:
            with pytest.raises(roadmap_lint.MalformedRegistryError) as perm_exc:
                roadmap_lint.validate_roadmap_status_coherence(repo_del, required=True)
            msg = str(perm_exc.value)
            assert "specs/phase-plans-v1.md" in msg
            assert roadmap_lint.ROADMAP_STATUS_REGISTRY_REL in msg
            assert str(repo_del) not in msg
            assert "Fix:" in msg
        finally:
            unreadable.chmod(0o644)


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses chmod 000 directory permissions")
def test_explicit_roadmap_under_unreadable_parent_raises_readable_file_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_repo(tmp_path)
    specs = repo / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    target = specs / "phase-plans-v1.md"
    target.write_text("# R\n\n> **Status (2026-10-08): ACTIVE — test**\n", encoding="utf-8")
    specs.chmod(0o000)
    try:
        with pytest.raises(roadmap_lint.MalformedBannerError) as exc:
            discovery.select_roadmap(repo, target)
        msg = str(exc.value)
        assert "specs/phase-plans-v1.md" in msg
        assert "cannot read" in msg
        assert "roadmap not found" not in msg
        assert str(repo) not in msg
        assert "Fix:" in msg

        sentinel = Mock(side_effect=AssertionError("run_loop must not be reached"))
        monkeypatch.setattr(cli, "run_loop", sentinel)
        assert cli.main(["run", "--repo", str(repo), "--roadmap", str(target)]) == 2
        err = capsys.readouterr().err
        assert "specs/phase-plans-v1.md" in err
        assert "cannot read" in err
        assert str(repo) not in err
        assert "Traceback" not in err
        sentinel.assert_not_called()
    finally:
        specs.chmod(0o755)


def test_symlinked_repo_and_cross_dir_validate_roadmap_preserve_repo_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_repo = _init_repo(tmp_path / "real")
    link_repo = tmp_path / "linked-repo"
    link_repo.symlink_to(real_repo, target_is_directory=True)

    # Missing relative and absolute roadmaps under symlinked repo preserve specs/phase-plans-v1.md.
    for explicit in ("specs/phase-plans-v1.md", str(link_repo / "specs" / "phase-plans-v1.md")):
        with pytest.raises(roadmap_lint.RoadmapNotFoundError) as exc:
            discovery.select_roadmap(link_repo, explicit)
        msg = str(exc.value)
        assert "specs/phase-plans-v1.md" in msg
        assert str(real_repo) not in msg
        assert str(link_repo) not in msg

    # validate-roadmap --repo <repo> --roadmap <path> called from another cwd preserves repo-relative path.
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    missing_abs = real_repo / "specs" / "phase-plans-v1.md"
    assert cli.main(["validate-roadmap", "--repo", str(link_repo), "--roadmap", str(missing_abs)]) == 2
    err = capsys.readouterr().err
    assert "specs/phase-plans-v1.md" in err
    assert str(real_repo) not in err
    assert str(link_repo) not in err
    assert "Fix:" in err

    # Path genuinely outside the repository still falls back to basename only.
    outside = tmp_path / "outside-roadmap.md"
    assert cli.main(["validate-roadmap", "--repo", str(link_repo), "--roadmap", str(outside)]) == 2
    err = capsys.readouterr().err
    assert outside.name in err
    assert str(tmp_path) not in err


def test_validate_roadmap_preserves_cwd_relative_paths_handles_symlink_loops_and_sanitizes_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    valid_roadmap = (
        "# Test Roadmap\n\n"
        "> **Status (2026-10-08): ACTIVE — created this date, nothing executed yet.**\n\n"
        "## Context\ncontext.\n\n"
        "## Phases\n\n"
        "### Phase 1 — Foundation (FOUND)\n"
        "**Objective**\nDo the thing.\n\n"
        "**Exit criteria**\n- [ ] it works\n\n"
        "**Scope notes**\nDecompose into 2 lanes.\n\n"
        "**Key files**\n- src/a.py\n\n"
        "**Depends on**\n- (none)\n\n"
        "**Produces**\n- IF-0-FOUND-1\n\n"
        "## Top Interface-Freeze Gates\n- IF-0-FOUND-1\n\n"
        "## Phase Dependency DAG\nFOUND\n\n"
        "## Execution Notes\nnotes.\n\n"
        "## Verification\nverify.\n"
    )
    checkout = _init_repo(tmp_path / "workspace")
    specs = checkout / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    roadmap_file = specs / "phase-plans-v1.md"
    roadmap_file.write_text(valid_roadmap, encoding="utf-8")
    reg = checkout / roadmap_lint.ROADMAP_STATUS_REGISTRY_REL
    reg.write_text(
        '{"schema":"roadmap_status_manifest.v1","selected_roadmap":"specs/phase-plans-v1.md",'
        '"roadmaps":[{"path":"specs/phase-plans-v1.md","status":"active"}]}\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-f", "specs/phase-plans-v1.md", roadmap_lint.ROADMAP_STATUS_REGISTRY_REL],
        cwd=checkout,
        check=True,
        capture_output=True,
    )

    # 1. From parent of checkout, cwd-relative paths with --repo still open the file (exit 0).
    monkeypatch.chdir(checkout.parent)
    rel_from_parent = f"{checkout.name}/specs/phase-plans-v1.md"
    assert cli.main(["validate-roadmap", "--repo", checkout.name, "--roadmap", rel_from_parent]) == 0
    _ = capfd.readouterr()
    assert cli.main(["validate-roadmap", "--repo", checkout.name, rel_from_parent]) == 0
    _ = capfd.readouterr()

    # From an unrelated cwd, repo-relative --roadmap still resolves against --repo.
    other_cwd = tmp_path / "unrelated"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    assert cli.main(["validate-roadmap", "--repo", str(checkout), "--roadmap", "specs/phase-plans-v1.md"]) == 0
    _ = capfd.readouterr()

    # 2. Self-referential symlink (both inside repo and outside git) returns exit 2 with Fix:, never RuntimeError.
    loop_in_repo = specs / "phase-plans-loop.md"
    loop_in_repo.symlink_to(loop_in_repo.name)
    assert roadmap_lint.main(["validate-roadmap", str(loop_in_repo)], repo=checkout) == 2
    err = capfd.readouterr().err
    assert "specs/phase-plans-loop.md" in err
    assert str(checkout) not in err
    assert "Fix:" in err

    outside_dir = tmp_path / "outside-git" / "specs"
    outside_dir.mkdir(parents=True)
    loop_outside = outside_dir / "loop.md"
    loop_outside.symlink_to(loop_outside.name)
    assert cli.main(["validate-roadmap", str(loop_outside)]) == 2
    err = capfd.readouterr().err
    assert "loop.md" in err
    assert str(tmp_path) not in err
    assert "Fix:" in err
    assert "Traceback" not in err

    # 3. Nonexistent --repo with valid absolute roadmap does not leak Git fatal stderr on fd 2;
    # outside-git coherence-skip note does not leak absolute host paths.
    nonexistent_repo = tmp_path / "does-not-exist-repo"
    assert cli.main(["validate-roadmap", "--repo", str(nonexistent_repo), "--roadmap", str(roadmap_file)]) == 0
    captured = capfd.readouterr()
    assert str(nonexistent_repo) not in captured.err
    assert "fatal:" not in captured.err

    loose_roadmap = outside_dir / "loose-valid.md"
    loose_roadmap.write_text(valid_roadmap, encoding="utf-8")
    assert cli.main(["validate-roadmap", str(loose_roadmap)]) == 0
    captured = capfd.readouterr()
    assert "not inside a git work tree" in captured.err
    assert "loose-valid.md" in captured.err
    assert str(tmp_path) not in captured.err
