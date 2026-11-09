"""Isolated WORKER CLI fixture checks; no production state is accessed."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from phase_loop_runtime import supervised_worker_cli as cli
from phase_loop_runtime.supervised_launch import Refused


@pytest.mark.parametrize("argv,reason", [(["launch", "--envelope", "/absent", "--result", "/absent"],
                                        "codec_unavailable"), (["unknown"], "invalid choice")])
def test_isolated_cli_before_root(tmp_path, argv, reason):
    root = Path(cli.__file__).parents[1]
    for name in ("json.py", "argparse.py", "validator.py"):
        (tmp_path / name).write_text('raise RuntimeError("shadow loaded")')
    result = subprocess.run([sys.executable, "-I", "-c",
        'import sys; sys.path.insert(0,sys.argv.pop(1)); '
        'from phase_loop_runtime.supervised_worker_cli import main; raise SystemExit(main())',
        str(root), *argv], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode in (2, 10)
    assert reason in result.stdout + result.stderr
    assert "shadow loaded" not in result.stderr


def test_cli_preflight_before_codec_and_reads(monkeypatch, capsys):
    monkeypatch.setattr(cli, "preflight_supervised_route", lambda _: Refused("fixture_required"))
    def unexpected():
        raise AssertionError("codec reached")
    monkeypatch.setattr(cli, "_production_codec", unexpected)
    assert cli.main(["launch", "--envelope", "/absent", "--result", "/absent"]) == 10
    assert capsys.readouterr().out.strip() == "fixture_required"


def test_envelope_file_and_result_modes(tmp_path):
    tmp_path.chmod(0o700)
    source = tmp_path / "envelope"
    source.write_bytes(b"fixture")
    source.chmod(0o600)
    result = cli.read_envelope_file(source, cap=10)
    assert result[0] == b"fixture"
    assert isinstance(cli.read_envelope_file(source, cap=2), Refused)
    source.chmod(0o622)
    assert isinstance(cli.read_envelope_file(source, cap=10), Refused)
    link = tmp_path / "link"
    link.symlink_to(source)
    assert isinstance(cli.read_envelope_file(link, cap=10), Refused)
    result_path = tmp_path / "result"
    fd = cli.open_result_file(result_path, excluded=())
    assert isinstance(fd, int)
    assert os.fstat(fd).st_mode & 0o777 == 0o600
    os.close(fd)
    assert isinstance(cli.open_result_file(result_path, excluded=()), Refused)
    assert isinstance(cli.open_result_file(tmp_path / "other", excluded=(tmp_path,)), Refused)


def test_status_missing_root_in_process(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1)))
    assert cli.main(["status", "--attempt", "fixture"], state_root=tmp_path / "absent") == 10
    assert "journal_missing" in capsys.readouterr().out


from test_supervised_worker import case as _case, worker_case as _worker_case
case = _case
worker_case = _worker_case


def test_cli_cancel_retains_production_commands(worker_case, monkeypatch, capsys):
    from test_supervised_worker import _start_launcher, _finish_launcher, _await_state
    from phase_loop_runtime.convergence.adapters import patch_return as worker
    fixture = worker_case
    fixture.config.template_path.write_text('["{executable}", "wait"]')
    process, _ = _start_launcher(fixture)
    try:
        _await_state(fixture, "running")
        sent = []
        monkeypatch.setattr(cli, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1)))
        monkeypatch.setattr(worker.signal, "pidfd_send_signal", lambda *args: sent.append(args))
        assert cli.main(["cancel", "--attempt", fixture.envelope["attempt_id"]], state_root=fixture.state) == 0
        assert capsys.readouterr().out.strip() == "owner_unverified"
        assert sent == [] and process.poll() is None
    finally:
        process.terminate()
        _finish_launcher(process)


def test_status_liveness_and_page(worker_case, monkeypatch, capsys):
    import json
    from test_supervised_worker import run
    fixture = worker_case
    result = run(fixture)
    assert result.state == "finished"
    monkeypatch.setattr(cli, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1)))
    assert cli.main(["status", "--run", fixture.envelope["run_id"], "--page"], state_root=fixture.state) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["attempt"]["state"] == "finished" and record["page"] is not None
    assert record["page_diagnostics"] == []


CLI_CONTROLS = {
    "isolated": ('if not sys.flags.isolated:', 'if False:'),
    "preflight": ('if isinstance(preflight, Refused):', 'if False:'),
    "codec": ('if _production_codec() is None:', 'if False:'),
    "envelope-owner": ('or info.st_uid != os.geteuid()', ''),
    "envelope-regular": ('not stat.S_ISREG(info.st_mode) or ', ''),
    "envelope-mode": ('or info.st_mode & 0o022', ''),
    "envelope-size": ('or info.st_size > cap', ''),
    "envelope-stream-cap": ('if len(data) > cap:', 'if False:'),
    "envelope-nofollow": ('fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)', 'fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK, dir_fd=parent)'),
    "result-absolute": ('if not path.is_absolute() or ".." in path.parts:', 'if False:'),
    "result-excluded": ('if any(resolved == root.resolve() or root.resolve() in resolved.parents for root in excluded):', 'if False:'),
    "result-mode": ('or stat.S_IMODE(info.st_mode) != 0o700', ''),
    "result-owner": ('info.st_uid != os.geteuid() or ', ''),
    "result-create": ('os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW', 'os.O_WRONLY | os.O_EXCL | os.O_NOFOLLOW'),
    "result-exclusive": ('os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW', 'os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW'),
    "result-nofollow": ('os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW', 'os.O_WRONLY | os.O_CREAT | os.O_EXCL'),
    "status-liveness": ('status = projection.attempt_status(root, attempt)', 'status = projection.attempt_status(root, attempt, observer=lambda _pid: (False, None))'),
}


def _cli_source_copy(monkeypatch, control):
    import types
    source = Path(cli.__file__).read_text()
    old, new = CLI_CONTROLS[control]
    assert old in source
    module = types.ModuleType("phase_loop_runtime._cli_copy")
    module.__file__, module.__package__ = cli.__file__, cli.__package__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source.replace(old, new, 1), module.__file__, "exec"), module.__dict__)
    return module


def _cli_control_witness(module, control, tmp_path, monkeypatch, capsys, fixture):
    import json
    import stat
    from phase_loop_runtime.convergence.adapters import patch_return as worker
    argv = ["launch", "--envelope", "/absent", "--result", "/absent"]
    monkeypatch.setattr(module, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=control != "isolated")))
    if control in ("isolated", "preflight", "codec"):
        effects = []
        if control == "preflight":
            monkeypatch.setattr(module, "preflight_supervised_route", lambda _: Refused("fixture_required"))
            monkeypatch.setattr(module, "_production_codec", lambda: effects.append("codec"))
        assert module.main(argv, state_root=tmp_path) == 10
        expected = {"isolated": "isolation_required", "preflight": "fixture_required", "codec": "codec_unavailable"}[control]
        assert capsys.readouterr().out.strip() == expected and not effects
        return
    if control == "status-liveness":
        from test_supervised_worker import _start_launcher, _await_state, _finish_launcher
        fixture.config.template_path.write_text('["{executable}", "wait"]')
        process, _ = _start_launcher(fixture)
        try:
            _await_state(fixture, "running")
            assert module.main(["status", "--attempt", fixture.envelope["attempt_id"]], state_root=fixture.state) == 0
            assert json.loads(capsys.readouterr().out)["attempt"]["display"] == "running"
        finally:
            process.terminate()
            _finish_launcher(process)
        return
    tmp_path.chmod(0o700)
    path = tmp_path / "file"
    if control.startswith("envelope-"):
        path.write_bytes(b"fixture-envelope")
        path.chmod(0o600)
        if control == "envelope-mode":
            path.chmod(0o622)
        if control == "envelope-nofollow":
            link = tmp_path / "link"
            link.symlink_to(path)
            path = link
        original_stat, original_read = os.fstat, os.read
        reads = []
        def fstat(fd):
            info = original_stat(fd)
            if os.readlink(f"/proc/self/fd/{fd}") == str(path):
                return SimpleNamespace(st_uid=-1 if control == "envelope-owner" else info.st_uid,
                    st_mode=stat.S_IFIFO | 0o600 if control == "envelope-regular" else info.st_mode,
                    st_size=0 if control == "envelope-stream-cap" else info.st_size)
            return info
        def read(fd, size):
            reads.append(size)
            return original_read(fd, size)
        monkeypatch.setattr(os, "fstat", fstat)
        monkeypatch.setattr(os, "read", read)
        result = module.read_envelope_file(path, cap=2 if "cap" in control or control == "envelope-size" else 100)
        assert isinstance(result, Refused)
        if control == "envelope-size":
            assert not reads
        return
    if control == "result-mode":
        tmp_path.chmod(0o755)
    if control == "result-exclusive":
        path.write_bytes(b"existing-result")
    if control == "result-owner":
        original = os.fstat
        def fstat(fd):
            info = original(fd)
            if os.readlink(f"/proc/self/fd/{fd}") == str(tmp_path):
                return SimpleNamespace(st_uid=-1, st_mode=info.st_mode)
            return info
        monkeypatch.setattr(os, "fstat", fstat)
    directories, flags = [], []
    original_dir, original_open = worker._directory_fd, os.open
    def directory(path):
        directories.append(path)
        return original_dir(path)
    def opened(path, value, *args, **kwargs):
        if path == "file":
            flags.append(value)
        return original_open(path, value, *args, **kwargs)
    monkeypatch.setattr(worker, "_directory_fd", directory)
    monkeypatch.setattr(os, "open", opened)
    result = module.open_result_file(Path("relative") if control == "result-absolute" else path,
                                   excluded=(tmp_path,) if control == "result-excluded" else ())
    try:
        if control in ("result-create", "result-nofollow"):
            assert isinstance(result, int)
            assert flags and flags[-1] & (os.O_CREAT if control == "result-create" else os.O_NOFOLLOW)
        else:
            assert isinstance(result, Refused)
            if control == "result-absolute":
                assert not directories
    finally:
        if isinstance(result, int):
            os.close(result)


@pytest.mark.parametrize("control", sorted(CLI_CONTROLS))
@pytest.mark.parametrize("mutated", [False, True], ids=["intact", "killed"])
def test_cli_source_controls(worker_case, tmp_path, monkeypatch, capsys, control, mutated):
    module = _cli_source_copy(monkeypatch, control) if mutated else cli
    if mutated:
        with pytest.raises(AssertionError):
            _cli_control_witness(module, control, tmp_path, monkeypatch, capsys, worker_case)
    else:
        _cli_control_witness(module, control, tmp_path, monkeypatch, capsys, worker_case)
