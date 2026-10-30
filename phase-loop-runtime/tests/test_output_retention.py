"""Output lifecycle controls use small synthetic run directories only."""
import json
import os
from pathlib import Path
import shutil
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
    assert not path.exists()
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


@pytest.mark.parametrize("args,code", [(["--collect-only", "-q"], 0), (["-k", "test_bad_policy_refused", "-q"], 0), (["-k", "("], 4)])
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
def test_fork_exit_preserves_parent_audit_log(request):
    conftest = request.config.pluginmanager.get_plugin(str(Path(__file__).with_name("conftest.py")))
    assert conftest is not None

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


@pytest.mark.parametrize("ram_backed", [False, True])
def test_operator_producer_uses_owned_launch_and_scratch_policy(root, tmp_path, monkeypatch, ram_backed):
    from phase_loop_runtime import sandbox_policy

    # Control filesystem observations, not the launch/decision seam. The policy
    # intentionally leaves TMPDIR unset when the system default is disk-backed.
    scratch = tmp_path / "child-scratch"
    scratch.mkdir(mode=0o700)
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_TMPDIR", raising=False)
    monkeypatch.setattr(sandbox_policy, "is_ram_backed", lambda path: ram_backed)
    monkeypatch.setattr(sandbox_policy, "_child_tmp_dir", lambda: sandbox_policy.ScratchLocation(scratch, False))
    # A local stub, never a provider/auth/network trial. The suite audit hook
    # recognizes this executable name and checks the actual launch environment.
    stub = tmp_path / "codex"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib\n"
        "out = pathlib.Path(os.environ['PHASE_LOOP_OUTPUT_DIR'])\n"
        "(out / 'env.json').write_text(json.dumps({k: os.environ.get(k) "
        "for k in ('TMPDIR', 'PHASE_LOOP_SCRATCH_DECIDED')}))\n"
    )
    stub.chmod(0o700)
    assert r.run_managed(root, "owned", [str(stub)], finish_state="sealed") == 0
    observed = json.loads((root / "owned" / "env.json").read_text())
    assert observed["PHASE_LOOP_SCRATCH_DECIDED"] == "relocate"
    assert observed["TMPDIR"] == (str(scratch) if ram_backed else None)


def test_retirement_preserves_replacement_during_acquisition(root, monkeypatch, capsys):
    path, record = completed(root)
    rename = os.rename
    def replace_at_acquisition(src, dst, **kwargs):
        if src == "done" and dst == "output":
            path.rename(root / "original")
            path.mkdir()
            (path / "bystander").write_text("keep replacement")
        return rename(src, dst, **kwargs)
    monkeypatch.setattr(os, "rename", replace_at_acquisition)
    assert r.prune(root, now=record["completed_at"] + 40 * 86400, apply=True) == []
    recovery, = (root / r.REGISTRY).glob(".retiring-*")
    assert (recovery / "output" / "bystander").read_text() == "keep replacement"
    assert (root / "original" / "evidence.txt").read_text() == "retained bytes"
    assert json.loads((recovery / "recovery.json").read_text())["run"] == "done"
    assert "preserved" in capsys.readouterr().err
    assert r.prune(root, now=record["completed_at"] + 50 * 86400, apply=True) == []


def test_generation_token_preserves_reused_identity(root):
    path, record = completed(root)
    shutil.rmtree(path)
    path.mkdir()
    (path / "replacement").write_text("keep")
    # Model inode reuse deterministically; the old token is still required.
    record.update(device=path.stat().st_dev, inode=path.stat().st_ino)
    (root / r.REGISTRY / "done.json").write_text(json.dumps(record))
    assert r.prune(root, now=record["completed_at"] + 40 * 86400, apply=True) == []
    assert (path / "replacement").read_text() == "keep"


def test_missing_run_retires_record_on_apply_only(root):
    path, _ = completed(root)
    shutil.rmtree(path)
    record = root / r.REGISTRY / "done.json"
    assert r.prune(root) == []
    assert record.exists()
    assert r.prune(root, apply=True) == []
    assert not record.exists()
    assert len(list((root / r.REGISTRY).glob(".missing-*"))) == 1


def test_interrupted_retirement_leaves_no_live_permission(root, monkeypatch):
    path, record = completed(root)
    rename = os.rename
    def interrupted(src, dst, **kwargs):
        if dst == "output":
            raise KeyboardInterrupt
        return rename(src, dst, **kwargs)
    monkeypatch.setattr(os, "rename", interrupted)
    with pytest.raises(KeyboardInterrupt):
        r.prune(root, now=record["completed_at"] + 40 * 86400, apply=True)
    assert path.exists()
    assert not (root / r.REGISTRY / "done.json").exists()
    assert r.prune(root, now=record["completed_at"] + 50 * 86400, apply=True) == []


@pytest.mark.parametrize("bad", ["integer", "nested"])
def test_invalid_record_does_not_abort_configured_sweep(root, monkeypatch, bad):
    path, record = completed(root)
    if bad == "integer":
        record["completed_at"] = 10 ** 400
        contents = json.dumps(record)
    else:
        contents = "[" * 1500 + "]" * 1500
    (root / r.REGISTRY / "done.json").write_text(contents)
    monkeypatch.setenv("PHASE_LOOP_OUTPUT_ROOTS", str(root))
    r.configured_sweep()
    assert path.exists()


def test_one_retirement_failure_does_not_starve_siblings(root, monkeypatch, capsys):
    first, record = completed(root, "a")
    second, _ = completed(root, "b")
    remove = shutil.rmtree
    def fail_first(path, *, dir_fd=None, **kwargs):
        # The first run is now under its private recovery directory.
        receipt = json.loads(Path(f"/proc/self/fd/{dir_fd}/recovery.json").read_text())
        if receipt["run"] == "a":
            raise PermissionError("synthetic read-only output")
        return remove(path, dir_fd=dir_fd, **kwargs)
    fail_first.avoids_symlink_attacks = True
    monkeypatch.setattr(shutil, "rmtree", fail_first)
    assert r.prune(root, now=record["completed_at"] + 40 * 86400, apply=True) == ["b"]
    recovery, = (root / r.REGISTRY).glob(".retiring-*")
    assert (recovery / "output" / "evidence.txt").read_text() == "retained bytes"
    assert not first.exists() and not second.exists()
    assert "synthetic read-only output" in capsys.readouterr().err


@pytest.mark.parametrize("code", [0, 3])
def test_sweep_failure_preserves_producer_exit(root, monkeypatch, code, capsys):
    def fail(*args, **kwargs):
        raise OSError("sweep unavailable")
    monkeypatch.setattr(r, "prune", fail)
    assert r.run_managed(root, "new", [sys.executable, "-c", f"raise SystemExit({code})"], finish_state="sealed") == code
    assert "sweep unavailable" in capsys.readouterr().err


def test_shared_policy_preserves_longer_retention(root, monkeypatch):
    path, record = completed(root)
    monkeypatch.setenv("PHASE_LOOP_OUTPUT_RETENTION_DAYS", "90")
    monkeypatch.setattr(r.time, "time", lambda: record["completed_at"] + 40 * 86400)
    assert r.prune(root, apply=True) == []
    assert r.run_managed(root, "new", [sys.executable, "-c", "pass"], finish_state="published") == 0
    assert path.exists()
    assert r.prune(root, days=30) == ["done"]


def test_handled_interrupt_leaves_held(root, monkeypatch):
    from phase_loop_runtime import panel_invoker
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(panel_invoker, "run_provider", interrupted)
    with pytest.raises(KeyboardInterrupt):
        r.run_managed(root, "interrupted", ["unused"], finish_state="sealed")
    assert json.loads((root / r.REGISTRY / "interrupted.json").read_text())["state"] == "held"
    assert r.prune(root, now=10**11, apply=True) == []


def test_releasing_hold_keeps_first_time(root):
    _, record = completed(root)
    r.mark(root, "done", "held")
    assert r.mark(root, "done", "sealed")["completed_at"] == record["completed_at"]


def test_missing_root_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        r.prune(tmp_path / "absent")


def test_permissions_and_git_outputs_refused(root):
    path = root / "new"
    path.mkdir(mode=0o777)
    path.chmod(0o777)
    with pytest.raises(ValueError, match="writable"):
        r.mark(root, "new", "active")
    path.chmod(0o700)
    (path / ".git").write_text("gitdir: elsewhere")
    with pytest.raises(ValueError, match="Git checkouts"):
        r.mark(root, "new", "sealed")


def test_nested_git_directory_preserved(root):
    path, record = completed(root)
    (path / "nested" / ".git").mkdir(parents=True)
    assert r.prune(root, now=record["completed_at"] + 40 * 86400, apply=True) == []
    assert (path / "evidence.txt").read_text() == "retained bytes"


def test_cli_run_and_apply_share_environment_policy(root, monkeypatch):
    _, record = completed(root)
    record["completed_at"] -= 40 * 86400
    (root / r.REGISTRY / "done.json").write_text(json.dumps(record))
    monkeypatch.setenv("PHASE_LOOP_OUTPUT_RETENTION_DAYS", "90")
    command = [sys.executable, "-m", "phase_loop_runtime.cli", "output-retention"]
    result = subprocess.run([*command, "run", "--root", str(root), "--run", "cli", "--finish-state", "sealed",
                             "--exec", sys.executable, "-c", "pass"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (root / "done").exists()
    result = subprocess.run([*command, "prune", "--root", str(root), "--apply"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"removed": []}
    result = subprocess.run([*command, "prune", "--root", str(root), "--apply", "--days", "30"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"removed": ["done"]}


def test_lifecycle_update_waits_for_sweep_lock(root):
    completed(root)
    script = """
import sys
from pathlib import Path
from phase_loop_runtime import output_retention as r
print('ready', flush=True)
r.mark(Path(sys.argv[1]), 'done', 'active')
"""
    with r._locked(root, create=False):
        child = subprocess.Popen([sys.executable, '-c', script, str(root)], stdout=subprocess.PIPE, text=True)
        try:
            import selectors
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), 'lifecycle child did not start'
            assert child.stdout.readline().strip() == 'ready'
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=0.2)
        except BaseException:
            child.kill()
            child.wait(timeout=5)
            raise
    try:
        assert child.wait(timeout=10) == 0
        assert json.loads((root / r.REGISTRY / 'done.json').read_text())['state'] == 'active'
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()


@pytest.mark.parametrize('command', ['run', 'execute', 'advisor-board'])
@pytest.mark.parametrize('dry_run', [True, False])
def test_cli_startup_sweep_selection(monkeypatch, command, dry_run):
    from phase_loop_runtime import cli

    class StopAfterDispatch(Exception):
        pass

    class Arguments:
        def __getattr__(self, key):
            raise StopAfterDispatch(key)

    args = Arguments()
    args.command = command
    args.dry_run = dry_run
    calls = []
    monkeypatch.setattr(cli, 'build_parser', lambda: type('Parser', (), {'parse_args': lambda self, argv: args})())
    monkeypatch.setattr(r, 'configured_sweep', lambda: calls.append('sweep'))
    with pytest.raises(StopAfterDispatch):
        cli.main([])
    assert calls == ([] if dry_run else ['sweep'])


def test_abrupt_wrapper_exit_preserves_active_output(root):
    script = """
import signal, sys
from pathlib import Path
from phase_loop_runtime import output_retention as r, panel_invoker

def producer(*args, **kwargs):
    print('ready', flush=True)
    signal.pause()
panel_invoker.run_provider = producer
r.run_managed(Path(sys.argv[1]), 'unfinished', ['synthetic'], finish_state='sealed')
"""
    child = subprocess.Popen([sys.executable, '-c', script, str(root)], stdout=subprocess.PIPE, text=True)
    try:
        import selectors
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=10), 'synthetic wrapper did not start'
        assert child.stdout.readline().strip() == 'ready'
        child.kill()
        child.wait(timeout=5)
        record = json.loads((root / r.REGISTRY / 'unfinished.json').read_text())
        assert record['state'] == 'active'
        assert r.prune(root, apply=True, now=10**11) == []
        assert (root / 'unfinished').is_dir()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
