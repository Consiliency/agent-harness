"""Isolated WORKER CLI fixture checks; no production state is accessed."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from phase_loop_runtime import seat_uid, supervised_worker_cli as cli
from phase_loop_runtime.supervised_launch import Refused


@pytest.mark.parametrize("argv,reason", [(["launch", "--envelope", "/absent", "--result", "/absent"],
                                        "envelope_file_unsafe"), (["unknown"], "invalid choice")])
def test_isolated_cli_before_root(tmp_path, argv, reason):
    root = Path(cli.__file__).parents[1]
    for name in ("json.py", "argparse.py", "validator.py"):
        (tmp_path / name).write_text('raise RuntimeError("shadow loaded")')
    precheck = subprocess.run([sys.executable, "-I", "-c",
        'import sys; from pathlib import Path; root=Path(sys.argv[1]); sys.path.insert(0,str(root)); '
        'import phase_loop_runtime; assert Path(phase_loop_runtime.__file__).resolve().is_relative_to(root.resolve())',
        str(root)], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert precheck.returncode == 0, precheck.stderr
    command = seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", *argv)
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
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
    "codec": ('if isinstance(passive, Refused):', 'if False:'),
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
            monkeypatch.setattr(module, "_production_codec", lambda **kwargs: effects.append("codec"))
        if control == "codec":
            from phase_loop_runtime import supervised_launch_binding as binding
            from phase_loop_runtime.supervised_launch import AttemptBinding
            monkeypatch.setattr(module, "read_envelope_file", lambda *args, **kwargs: (b"fixture", 0o600))
            monkeypatch.setattr(binding, "read_binding_locator", lambda path: SimpleNamespace(controller_root=tmp_path))
            snapshot = SimpleNamespace(exclusions=(tmp_path, tmp_path), document={}, attempt=AttemptBinding("a" * 64, "run", "attempt"))
            monkeypatch.setattr(module, "read_controller_snapshot", lambda *args, **kwargs: snapshot)
            monkeypatch.setattr(module, "_production_codec", lambda **kwargs: Refused("binding_invalid"))
            def agreement(*args, **kwargs):
                effects.append("agreement")
                return Refused("binding_invalid")
            monkeypatch.setattr(binding, "reconcile_v2_binding", agreement)
        assert module.main(argv, state_root=tmp_path) == 10
        expected = {"isolated": "isolation_required", "preflight": "fixture_required", "codec": "binding_invalid"}[control]
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


def test_status_follows_next_cursor(worker_case, monkeypatch, capsys):
    import json
    from test_supervised_worker import run
    fixture = worker_case
    assert run(fixture).state == "finished"
    monkeypatch.setattr(cli, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=1)))
    monkeypatch.setattr(cli, "STATUS_PAGE_SIZE", 1)
    argv = ["status", "--attempt", fixture.envelope["attempt_id"], "--page"]
    assert cli.main(argv, state_root=fixture.state) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["next_cursor"]
    assert cli.main(argv + ["--cursor", first["next_cursor"]], state_root=fixture.state) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["page"]["events"][0]["seq"] < second["page"]["events"][0]["seq"]


def test_production_launcher_matches_trusted_boot():
    from phase_loop_runtime.convergence.adapters.patch_return import PRODUCTION_LAUNCHER_COMMANDS
    command = seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", "launch")
    assert PRODUCTION_LAUNCHER_COMMANDS == (tuple(command[1:]),)
    assert command[1:3] == ["-I", "-c"]


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("verb", ["launch", "cancel"])
def test_required_session_child_refuses_before_effects(tmp_path, bound, verb):
    source = Path(cli.__file__).parents[1]
    tests = Path(__file__).parent
    code = '''import sys
from pathlib import Path
source, tests, verb, bound = sys.argv[1:]
sys.path[:0] = [source, tests]
import phase_loop_runtime
assert Path(phase_loop_runtime.__file__).resolve().is_relative_to(Path(source).resolve())
from test_executable_dependency_startup import FakeDependency, register_session
from phase_loop_runtime import supervised_worker_cli as cli
session = register_session(FakeDependency())
lease = session.acquire_task("synthetic-cli") if bound == "True" else None
calls = []
def unexpected(*args, **kwargs):
    calls.append(1)
    raise AssertionError("unexpected CLI effect")
cli._production_codec = unexpected
cli.read_envelope_file = unexpected
cli.open_result_file = unexpected
from phase_loop_runtime.convergence.adapters import patch_return as worker
worker.default_state_root = unexpected
worker.cancel_attempt = unexpected
args = (["launch", "--envelope", "/absent", "--result", "/absent"] if verb == "launch" else ["cancel", "--attempt", "fixture"])
try:
    if lease:
        with lease.bind_current():
            result = cli.main(args)
    else:
        result = cli.main(args)
    assert result == 10 and not calls
finally:
    if lease:
        lease.release()
    session.close()
'''
    result = subprocess.run([sys.executable, "-I", "-c", code, str(source), str(tests), verb, str(bound)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("dependency_route_unwired" if bound else "task_unbound")


from test_supervised_launch_binding import v2_operator


def _write_controller(operator, document=None, root=None):
    import json
    root = root or Path(operator.document["controller_root"])
    path = root / (operator.controller["h"] + ".json")
    path.write_text(json.dumps(operator.controller if document is None else document))
    path.chmod(0o600)
    return path


def test_controller_snapshot_is_held_across_path_changes(v2_operator):
    operator = v2_operator
    path = _write_controller(operator)
    snapshot = cli.read_controller_snapshot(path.parent, operator.controller["h"])
    assert isinstance(snapshot, cli.ControllerSnapshot)
    path.write_text('{"h":"changed"}')
    from phase_loop_runtime import supervised_launch_binding as binding
    locator = binding.read_binding_locator(operator.path)
    passive = binding.load_v2_binding(operator.path, **operator.roots)
    agreed = binding.reconcile_v2_binding(locator, passive, controller=snapshot.document, attempt=snapshot.attempt)
    assert isinstance(agreed, binding.V2Binding)
    assert agreed.context.expected_snapshot_ref == operator.context["expected_snapshot_ref"]
    assert agreed.context.expected_crosswalk_ref == operator.context["expected_crosswalk_ref"]
    assert not operator.marker.exists()


@pytest.mark.parametrize("change", ["h", "attempt", "context", "roots", "mode", "link"])
def test_controller_snapshot_checks_precede_activation(v2_operator, change):
    import copy
    operator = v2_operator
    document = copy.deepcopy(operator.controller)
    if change == "h": document["h"] = "e" * 64
    elif change == "attempt": document["attempt"]["assignment_digest"] = "e" * 64
    elif change == "context": document["context"].pop("expected_snapshot_ref")
    elif change == "roots": document["slots"].pop("reference_roots")
    path = _write_controller(operator, document)
    if change == "mode": path.chmod(0o644)
    elif change == "link":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    assert cli.read_controller_snapshot(path.parent, operator.controller["h"]) == Refused("binding_invalid")
    assert not operator.marker.exists()


@pytest.mark.parametrize("root_kind", ["workspace", "target", "reference"])
def test_controller_snapshot_excluded_location(v2_operator, root_kind):
    operator = v2_operator
    root = operator.roots["reference_roots"][0] if root_kind == "reference" else operator.roots[root_kind]
    path = _write_controller(operator, root=root)
    assert cli.read_controller_snapshot(path.parent, operator.controller["h"]) == Refused("binding_invalid")
    assert not operator.marker.exists()


@pytest.mark.parametrize("change", [None, "binding-replaced", "controller-missing", "controller-timeout", "policy-slot"])
def test_v2_cli_bootstrap_order_enters_real_worker(v2_operator, monkeypatch, change):
    import json
    from test_supervised_capture_v2 import build_v2_attempt
    from phase_loop_runtime import supervised_launch_binding as binding, supervised_launch as launch
    from phase_loop_runtime.convergence.adapters import patch_return
    fixture = build_v2_attempt(v2_operator)
    operator = fixture.operator
    launch.discard_admission(fixture.prepared)
    operator.marker.unlink()
    envelope = operator.path.parent / "public-envelope.json"
    envelope.write_bytes(fixture.raw)
    envelope.chmod(0o600)
    result = operator.path.parent / "result.json"
    state = operator.path.parent / "worker-state"
    if change == "controller-timeout": operator.controller["context"]["timeout_max_seconds"] = True
    if change == "policy-slot": operator.controller["slots"]["policy_epoch"] = "changed"
    controller_path = _write_controller(operator)
    if change == "controller-missing": controller_path.unlink()
    monkeypatch.setattr(binding, "MANAGED_BINDING", operator.path)
    monkeypatch.setattr(cli, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True)))
    events = []
    def wrap(owner, name, event):
        original = getattr(owner, name)
        def entered(*args, **kwargs):
            events.append(event)
            if event in {"envelope", "locator", "controller", "full", "agreement"}:
                assert not operator.marker.exists() and not result.exists() and not state.exists()
            value = original(*args, **kwargs)
            if event == "locator" and change == "binding-replaced":
                operator.path.write_bytes(operator.path.read_bytes() + b" ")
            if event == "activation" and isinstance(value, binding.V2Binding):
                from dataclasses import replace
                wrap(value.codec, "decode_v2", "decode")
                validator = value.validator
                def validate(*args, **kwargs):
                    events.append("validate")
                    return validator(*args, **kwargs)
                value = replace(value, validator=validate)
            return value
        monkeypatch.setattr(owner, name, entered)
    for owner, name, event in ((cli, "read_envelope_file", "envelope"), (binding, "read_binding_locator", "locator"),
            (cli, "read_controller_snapshot", "controller"), (binding, "load_v2_binding", "full"),
            (binding, "reconcile_v2_binding", "agreement"), (binding, "activate_v2_binding", "activation"),
            (cli, "prepare_launch_v2", "prepare"), (cli, "open_result_file", "result"),
            (patch_return, "run_patch_return", "journal-spawn")):
        wrap(owner, name, event)
    outcome = cli.main(["launch", "--envelope", str(envelope), "--result", str(result)], state_root=state)
    if change:
        assert outcome == 10 and not result.exists() and not state.exists()
        assert not operator.marker.exists()
        assert not {"activation", "decode", "validate", "prepare", "result", "journal-spawn"} & set(events)
    else:
        assert outcome == 0
        for before, after in zip(("envelope", "locator", "controller", "full", "agreement", "activation", "decode", "prepare", "validate", "result"),
                                 ("locator", "controller", "full", "agreement", "activation", "decode", "prepare", "validate", "result", "journal-spawn")):
            assert events.index(before) < events.index(after), events
        record = json.loads(result.read_bytes())
        assert record["runtime_state"] == "finished" and record["journal_acknowledged"]
