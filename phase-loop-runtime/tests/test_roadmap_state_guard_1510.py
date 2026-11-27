"""Regression tests for the roadmap state guard, precedence, and registry source matrix (agent-harness#1510)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from phase_loop_runtime import cli, discovery, roadmap_lint
from phase_loop_runtime.events import event_path
from phase_loop_runtime.plan_manifest import DotfilesPlanEntry, DotfilesPlanRef, append_entry
from phase_loop_runtime.state import write_state
from phase_loop_runtime.state_ops import archive_root

from phase_loop_test_utils import provenanced_state


ACTIVE_BANNER = "> **Status (2026-10-08): ACTIVE — created this date, nothing executed yet.**"
SUPERSEDED_V10_BANNER = "> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v11.md` (2026-10-08)"
DELIVERED_BANNER = "> # DELIVERED — CLOSED (assessed 2026-07-29)"
ADVISORY_BANNER = "> # ADVISORY — not runner-selected (2026-11-04)"

V10_REL = "specs/phase-plans-v10.md"
V11_REL = "specs/phase-plans-v11.md"


@pytest.fixture(autouse=True)
def _isolate_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test (fixture setup and runtime CLI/discovery git calls) from
    inherited GIT_* variables and host global/system git configuration."""
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Phase Loop Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Phase Loop Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_AUTHOR_NAME"] = "Phase Loop Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Phase Loop Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        env=_git_env(),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    return repo


def _write_roadmap(repo: Path, rel: str, banner: str) -> Path:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Roadmap {Path(rel).stem}", ""]
    if banner:
        lines.append(banner)
        lines.append("")
    lines.extend(["## Phase ALPHA", "", "- [ ] Step 1", ""])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _write_registry(repo: Path, selected: str, statuses: dict[str, str]) -> Path:
    path = repo / "specs" / "roadmap-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "roadmap_status_manifest.v1",
        "selected_roadmap": selected,
        "roadmaps": [
            {"path": rel, "status": status}
            for rel, status in sorted(statuses.items())
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _commit_all(repo: Path, message: str = "init") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _build_v10_v11_repo(base: Path) -> tuple[Path, Path, Path]:
    repo = _init_repo(base)
    v10 = _write_roadmap(repo, V10_REL, SUPERSEDED_V10_BANNER)
    v11 = _write_roadmap(repo, V11_REL, ACTIVE_BANNER)
    _write_registry(repo, V11_REL, {V10_REL: "superseded", V11_REL: "active"})
    _commit_all(repo)
    return repo, v10, v11


def _add_manifest_entry(repo: Path, *, phase: str, status: str, roadmap_rel: str) -> None:
    version = Path(roadmap_rel).stem.removeprefix("phase-plans-")
    plan_rel = f"plans/phase-plan-{version}-{phase}.md"
    plan_path = repo / plan_rel
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        f"---\nphase: {phase}\nroadmap: {roadmap_rel}\n---\n# Plan {phase}\n",
        encoding="utf-8",
    )
    append_entry(
        repo,
        DotfilesPlanEntry(
            slug=f"{version}-{phase}",
            file=plan_rel,
            type="phase",
            status=status,
            created_at="2026-10-11T00:00:00Z",
            updated_at="2026-10-11T00:00:00Z",
            owner_skill="codex-plan-phase",
            roadmap_ref=DotfilesPlanRef(
                slug=f"phase-plans-{version}",
                file=roadmap_rel,
                type="phase",
                status=status,
            ),
            phase_alias=phase,
        ),
    )


def _assert_state_remedy_in_message(message: str, repo: Path | None = None) -> None:
    assert "phase-loop archive-state" in message
    assert ".phase-loop__state.json" in message
    assert ".phase-loop__events.jsonl" in message
    assert ".phase-loop/" in message
    assert ".codex__phase-loop__" in message
    assert "ls -a" in message
    if repo is not None:
        assert str(repo) not in message


def test_stale_v10_state_refused_before_v11_registry_with_remedy_and_archive_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, v10, v11 = _build_v10_v11_repo(tmp_path)
    write_state(repo, provenanced_state(repo, v10, {"ALPHA": "executing"}))
    ev = event_path(repo)
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps({"action": "plan", "roadmap": str(v10)}) + "\n", encoding="utf-8")

    # State precedes registry: stale state pointing at superseded v10 is refused
    # rather than silently jumping to v11 via the registry.
    with pytest.raises(roadmap_lint.NonActiveSelectionError) as exc:
        discovery.select_roadmap(repo)
    _assert_state_remedy_in_message(str(exc.value), repo=repo)
    assert V10_REL in str(exc.value)

    # CLI surfaces the same clean refusal without dispatching run_loop.
    sentinel = Mock(side_effect=AssertionError("run_loop must not be reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    assert cli.main(["run", "--repo", str(repo)]) == 2
    err = capsys.readouterr().err
    assert "roadmap status refusal" in err
    assert "Traceback" not in err
    _assert_state_remedy_in_message(err, repo=repo)
    sentinel.assert_not_called()

    # Running the named remedy archives dot-prefixed files and unblocks v11 via registry.
    assert cli.main(["archive-state", "--repo", str(repo)]) == 0
    _ = capsys.readouterr()
    archive_dirs = [p for p in archive_root(repo).iterdir() if p.is_dir()]
    assert len(archive_dirs) == 1
    archived_names = {p.name for p in archive_dirs[0].iterdir()}
    assert ".phase-loop__state.json" in archived_names
    assert ".phase-loop__events.jsonl" in archived_names

    calls: list[tuple[Path, Path, str]] = []
    real_gate = discovery._return_selectable_roadmap

    def _spy(spy_repo: Path, spy_candidate: Path, spy_source: str) -> Path:
        calls.append((Path(spy_repo), Path(spy_candidate), spy_source))
        return real_gate(spy_repo, spy_candidate, spy_source)

    monkeypatch.setattr(discovery, "_return_selectable_roadmap", _spy)
    assert discovery.select_roadmap(repo) == v11.resolve()
    assert calls[-1][2] == "registry"
    assert calls[-1][1].resolve() == v11.resolve()


def test_stale_legacy_codex_state_refused_and_archived_with_legacy_dotfiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, v10, v11 = _build_v10_v11_repo(tmp_path)
    write_state(repo, provenanced_state(repo, v10, {"ALPHA": "executing"}))
    canonical_state = repo / ".phase-loop" / "state.json"
    legacy_dir = repo / ".codex" / "phase-loop"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_state = legacy_dir / "state.json"
    canonical_state.replace(legacy_state)
    canonical_state.parent.rmdir()
    legacy_events = legacy_dir / "events.jsonl"
    legacy_events.write_text(
        json.dumps({"action": "plan", "roadmap": str(v10)}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(roadmap_lint.NonActiveSelectionError) as exc:
        discovery.select_roadmap(repo)
    _assert_state_remedy_in_message(str(exc.value), repo=repo)
    assert V10_REL in str(exc.value)

    sentinel = Mock(side_effect=AssertionError("run_loop must not be reached"))
    monkeypatch.setattr(cli, "run_loop", sentinel)
    assert cli.main(["run", "--repo", str(repo)]) == 2
    err = capsys.readouterr().err
    assert "roadmap status refusal" in err
    assert "Traceback" not in err
    _assert_state_remedy_in_message(err, repo=repo)
    sentinel.assert_not_called()

    assert cli.main(["archive-state", "--repo", str(repo)]) == 0
    _ = capsys.readouterr()
    archive_dirs = [p for p in archive_root(repo).iterdir() if p.is_dir()]
    assert len(archive_dirs) == 1
    archived_names = {p.name for p in archive_dirs[0].iterdir()}
    assert ".codex__phase-loop__state.json" in archived_names
    assert ".codex__phase-loop__events.jsonl" in archived_names
    assert not legacy_state.exists()

    calls: list[str] = []
    real_gate = discovery._return_selectable_roadmap

    def _spy(spy_repo: Path, spy_candidate: Path, spy_source: str) -> Path:
        calls.append(spy_source)
        return real_gate(spy_repo, spy_candidate, spy_source)

    monkeypatch.setattr(discovery, "_return_selectable_roadmap", _spy)
    assert discovery.select_roadmap(repo) == v11.resolve()
    assert calls == ["registry"]


def test_superseded_state_error_also_names_archive_state_and_dotfiles(tmp_path: Path) -> None:
    repo, v10, _v11 = _build_v10_v11_repo(tmp_path)
    _add_manifest_entry(repo, phase="ALPHA", status="completed", roadmap_rel=V10_REL)
    write_state(repo, provenanced_state(repo, v10, {"ALPHA": "planned"}))

    with pytest.raises(discovery.SupersededRoadmapStateError) as exc:
        discovery.select_roadmap(repo)
    message = str(exc.value)
    _assert_state_remedy_in_message(message)
    assert "rm .phase-loop/state.json" in message


def test_state_precedes_registry_and_registry_precedes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _v10, v11 = _build_v10_v11_repo(tmp_path)
    _add_manifest_entry(repo, phase="ALPHA", status="executing", roadmap_rel=V11_REL)
    write_state(repo, provenanced_state(repo, v11, {"ALPHA": "executing"}))

    calls: list[str] = []
    real_gate = discovery._return_selectable_roadmap

    def _spy(spy_repo: Path, spy_candidate: Path, spy_source: str) -> Path:
        calls.append(spy_source)
        return real_gate(spy_repo, spy_candidate, spy_source)

    monkeypatch.setattr(discovery, "_return_selectable_roadmap", _spy)

    # Active state + registry + manifest -> state wins over registry.
    assert discovery.select_roadmap(repo) == v11.resolve()
    assert calls == ["state"]

    # Archive state -> registry wins over manifest.
    calls.clear()
    assert cli.main(["archive-state", "--repo", str(repo)]) == 0
    assert discovery.select_roadmap(repo) == v11.resolve()
    assert calls == ["registry"]


def test_registry_mismatch_branch_names_remedy_only_for_state_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, v10, _v11 = _build_v10_v11_repo(tmp_path)
    # Give v10 an active banner locally while stubbing coherence to still select v11,
    # directly exercising the `rel != status["selected_roadmap"]` guard branch.
    _write_roadmap(repo, V10_REL, ACTIVE_BANNER)
    monkeypatch.setattr(
        roadmap_lint,
        "validate_roadmap_status_coherence",
        lambda _repo, required=True: {
            "schema": "roadmap_status_manifest.v1",
            "selected_roadmap": V11_REL,
            "roadmaps": [
                {"path": V10_REL, "status": "superseded"},
                {"path": V11_REL, "status": "active"},
            ],
        },
    )

    with pytest.raises(roadmap_lint.NonActiveSelectionError) as state_exc:
        discovery._return_selectable_roadmap(repo, v10, "state")
    _assert_state_remedy_in_message(str(state_exc.value), repo=repo)
    assert V11_REL in str(state_exc.value)

    for non_state_source in ("explicit", "registry", "manifest", "handoff", "singleton-glob"):
        with pytest.raises(roadmap_lint.NonActiveSelectionError) as other_exc:
            discovery._return_selectable_roadmap(repo, v10, non_state_source)
        assert "phase-loop archive-state" not in str(other_exc.value)
        assert str(repo) not in str(other_exc.value)


@pytest.mark.parametrize(
    ("status_name", "banner"),
    [
        ("superseded", SUPERSEDED_V10_BANNER),
        ("delivered", DELIVERED_BANNER),
        ("advisory", ADVISORY_BANNER),
    ],
)
def test_registry_source_fails_closed_in_source_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_name: str,
    banner: str,
) -> None:
    """`registry` joins the fail-closed selector source matrix alongside the frozen
    LEGIBLE 8-source contract (which keeps its exact 84-nodeid inventory)."""
    # 1. Direct common-gate fail-closed check for source="registry" without state remedy.
    repo_gate = _init_repo(tmp_path / f"gate-{status_name}")
    non_active = _write_roadmap(repo_gate, V10_REL, banner)
    _commit_all(repo_gate)
    with pytest.raises(roadmap_lint.NonActiveSelectionError) as gate_exc:
        discovery._return_selectable_roadmap(repo_gate, non_active, "registry")
    assert "phase-loop archive-state" not in str(gate_exc.value)
    assert str(repo_gate) not in str(gate_exc.value)

    # 2. Live registry pointing selected_roadmap at a non-active roadmap fails closed.
    repo_bad_reg = _init_repo(tmp_path / f"bad-reg-{status_name}")
    _write_roadmap(repo_bad_reg, V10_REL, banner)
    _write_registry(repo_bad_reg, V10_REL, {V10_REL: status_name})
    _commit_all(repo_bad_reg)
    with pytest.raises(roadmap_lint.RoadmapStatusError):
        discovery.select_roadmap(repo_bad_reg)

    # 3. Even if coherence lookup returns a non-active selected_roadmap, select_roadmap's
    # registry branch still routes through _return_selectable_roadmap(..., "registry") and
    # fails closed with NonActiveSelectionError.
    calls: list[tuple[Path, str]] = []
    real_gate = discovery._return_selectable_roadmap

    def _spy(spy_repo: Path, spy_candidate: Path, spy_source: str) -> Path:
        calls.append((Path(spy_candidate), spy_source))
        return real_gate(spy_repo, spy_candidate, spy_source)

    monkeypatch.setattr(discovery, "_return_selectable_roadmap", _spy)
    monkeypatch.setattr(
        roadmap_lint,
        "validate_roadmap_status_coherence",
        lambda _repo, required=False: (
            {
                "schema": "roadmap_status_manifest.v1",
                "selected_roadmap": V10_REL,
                "roadmaps": [{"path": V10_REL, "status": status_name}],
            }
            if not required
            else None
        ),
    )
    with pytest.raises(roadmap_lint.NonActiveSelectionError) as select_exc:
        discovery.select_roadmap(repo_gate)
    assert calls == [(non_active.resolve(), "registry")]
    assert "phase-loop archive-state" not in str(select_exc.value)


def test_registry_source_positive_control_and_explicit_non_active_omits_state_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, v10, v11 = _build_v10_v11_repo(tmp_path)

    # Positive control: coherent registry selects active v11 through source="registry".
    calls: list[str] = []
    real_gate = discovery._return_selectable_roadmap

    def _spy(spy_repo: Path, spy_candidate: Path, spy_source: str) -> Path:
        calls.append(spy_source)
        return real_gate(spy_repo, spy_candidate, spy_source)

    monkeypatch.setattr(discovery, "_return_selectable_roadmap", _spy)
    assert discovery.select_roadmap(repo) == v11.resolve()
    assert calls == ["registry"]

    # Explicit selection of superseded v10 refuses without the state-only archive-state remedy.
    with pytest.raises(roadmap_lint.NonActiveSelectionError) as explicit_exc:
        discovery.select_roadmap(repo, V10_REL)
    assert "phase-loop archive-state" not in str(explicit_exc.value)
    assert str(repo) not in str(explicit_exc.value)
