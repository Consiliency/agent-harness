"""Output lifecycle controls use small synthetic run directories only."""
import json
import os
import subprocess
import sys

import pytest

from phase_loop_runtime import output_retention as r


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "outputs"
    path.mkdir(mode=0o700)
    return path


def completed(root, name="done", state="sealed"):
    path = root / name
    path.mkdir()
    (path / "evidence.txt").write_text("retained bytes")
    record = r.mark(root, name, state)
    return path, record


def test_expiry_uses_completion_time_and_preview(root):
    path, record = completed(root)
    os.utime(path, (1, 1))
    assert r.prune(root, now=record["completed_at"] + 29 * 86400) == []
    now = record["completed_at"] + 30 * 86400
    assert r.prune(root, now=now) == ["done"]
    assert path.exists()
    assert r.prune(root, now=now, apply=True) == ["done"]
    assert not path.exists()
    assert r.prune(root, now=now, apply=True) == []


@pytest.mark.parametrize("state", ["active", "held"])
def test_active_and_held_never_expire(root, state):
    path, record = completed(root)
    r.mark(root, "done", state)
    assert r.prune(root, now=record["completed_at"] + 400 * 86400, apply=True) == []
    assert path.exists()


def test_repeat_publication_preserves_first_time_and_resume_resets_it(root, monkeypatch):
    _, first = completed(root)
    monkeypatch.setattr(r.time, "time", lambda: first["completed_at"] + 100)
    assert r.mark(root, "done", "published")["completed_at"] == first["completed_at"]
    r.mark(root, "done", "active")
    assert r.mark(root, "done", "sealed")["completed_at"] == first["completed_at"] + 100


def test_unmarked_and_malformed_preserved(root):
    path, record = completed(root)
    unknown = root / "old-review"
    unknown.mkdir()
    (root / r.REGISTRY / "done.json").write_text("broken")
    assert r.prune(root, now=record["completed_at"] + 400 * 86400, apply=True) == []
    assert path.exists() and unknown.exists()


def test_directory_replacement_and_links_preserved(root, tmp_path):
    path, record = completed(root)
    moved = root / "original"
    path.rename(moved)
    path.mkdir()
    assert r.prune(root, now=record["completed_at"] + 400 * 86400, apply=True) == []
    with pytest.raises(ValueError, match="identity changed"):
        r.mark(root, "done", "sealed")
    path.rmdir()
    path.symlink_to(moved, target_is_directory=True)
    assert r.prune(root, now=record["completed_at"] + 400 * 86400, apply=True) == []
    assert (moved / "evidence.txt").read_text() == "retained bytes"


def test_nested_link_does_not_remove_target(root, tmp_path):
    path, record = completed(root)
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (path / "link").symlink_to(outside, target_is_directory=True)
    r.prune(root, now=record["completed_at"] + 400 * 86400, apply=True)
    assert (outside / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("days", [0, -1, True, 1.5])
def test_bad_policy_refused(root, days):
    with pytest.raises(ValueError):
        r.prune(root, days=days, apply=True)


@pytest.mark.parametrize("name", ["..", "../elsewhere", ".", "a/b", ""])
def test_invalid_run_name(root, name):
    with pytest.raises(ValueError):
        r.mark(root, name, "sealed")


@pytest.mark.parametrize("exit_code,state", [(0, "sealed"), (3, "held")])
def test_managed_producer_lifecycle(root, exit_code, state):
    script = "import os,pathlib,sys; p=pathlib.Path(os.environ['PHASE_LOOP_OUTPUT_DIR']); (p/'result').write_text('ok'); sys.exit(%d)" % exit_code
    assert r.run_managed(root, "new", [sys.executable, "-c", script], finish_state="sealed") == exit_code
    record = json.loads((root / r.REGISTRY / "new.json").read_text())
    assert record["state"] == state
    assert (root / "new" / "result").read_text() == "ok"
    with pytest.raises(FileExistsError):
        r.run_managed(root, "new", [sys.executable, "-c", ""], finish_state="sealed")


def test_managed_spawn_failure_held(root):
    with pytest.raises(FileNotFoundError):
        r.run_managed(root, "failed", ["/nonexistent/producer"], finish_state="sealed")
    assert json.loads((root / r.REGISTRY / "failed.json").read_text())["state"] == "held"


def test_configured_sweep_only_registered_roots(root, monkeypatch):
    path, record = completed(root)
    monkeypatch.setattr(r.time, "time", lambda: record["completed_at"] + 31 * 86400)
    monkeypatch.delenv("PHASE_LOOP_OUTPUT_ROOTS", raising=False)
    r.configured_sweep()
    assert path.exists()
    monkeypatch.setenv("PHASE_LOOP_OUTPUT_ROOTS", str(root))
    r.configured_sweep()
    assert not path.exists()


def test_cli_preview_and_mark(root):
    path, _ = completed(root)
    result = subprocess.run([sys.executable, "-m", "phase_loop_runtime.cli", "output-retention", "prune", "--root", str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"eligible": []}
    assert path.exists()


@pytest.mark.parametrize("args,code", [(["--collect-only", "-q"], 0), (["-k", "("], 4)])
def test_pytest_process_removes_audit_scratch(tmp_path, args, code):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = dict(os.environ, TMPDIR=str(scratch))
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, *args],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == code, result.stdout + result.stderr
    assert list(scratch.glob("pl-scratch-audit-*")) == []


def test_live_producer_cannot_be_marked_complete_by_another_process(root):
    path, _ = completed(root)
    r.mark(root, "done", "active", owner_pid=os.getpid())
    result = subprocess.run(
        [sys.executable, "-m", "phase_loop_runtime.cli", "output-retention", "mark",
         "--root", str(root), "--run", "done", "--state", "sealed"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "still active" in result.stderr
    assert path.exists()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_fork_exit_preserves_parent_audit_log():
    import conftest

    path = conftest._scratch_audit_dir
    pid = os.fork()
    if pid == 0:
        conftest._cleanup_scratch_audit()
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    assert status == 0
    assert os.path.isdir(path)


def test_xdist_workers_remove_owned_audit_scratch(tmp_path):
    pytest.importorskip("xdist")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = dict(os.environ, TMPDIR=str(scratch))
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__ + "::test_bad_policy_refused", "-n", "2", "-q"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(scratch.glob("pl-scratch-audit-*")) == []
