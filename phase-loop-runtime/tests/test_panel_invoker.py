"""model-routing-v1 P2 — panel-invoker (IF-0-P2-2). No live CLI calls."""
import unittest
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from president_fakes import deferring_president
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.panel_invoker import (
    LEG_STATUSES,
    PANEL_LEGS,
    PanelLegResult,
    PanelRequest,
    available_panel_legs,
    invoke_panel,
    invoke_panel_request,
    panel_leg_timeout_seconds,
)


def _install_firstseat_supplier_double(monkeypatch):
    """Install only lane A's frozen constructors and observation verbs."""
    from phase_loop_runtime import seat_jail_qualification as qualification

    @dataclass(frozen=True, slots=True, kw_only=True)
    class JailedStep:
        exit_code: int | None
        timed_out: bool
        stdout: bytes = field(repr=False)

    @dataclass(frozen=True, slots=True, kw_only=True)
    class DeliveredCopy:
        content: bytes = field(repr=False)
        sha256: str = field(repr=False)

    @dataclass(frozen=True, slots=True, kw_only=True)
    class TracedPath:
        location: str
        relpath: str = field(repr=False)

    @dataclass(frozen=True, slots=True, kw_only=True)
    class LaunchBinding:
        image_sha256: str
        admission_class: str
        stage_manifest_sha256: str
        argv_sha256: str
        input_sha256: str | None
        jail_profile_sha256: str
        allowlist_sha256: str

    @dataclass(frozen=True, slots=True, kw_only=True)
    class WindowLaunchResult:
        kind: str
        status: str
        timed_out: bool
        error: str | None
        quiescent: bool
        model_turn: bool | None
        tool_steps: int | None
        subagent_steps: int | None
        stream: object | None
        bridge_exited: bool | None
        lookups: tuple | None
        created: tuple | None
        lookup_complete: bool | None
        watch: object | None
        scan: object | None
        first_jailed_launch_ns: int | None
        bracket: object | None
        issuer: object | None
        delivered_copy_sha256: str | None = field(default=None, repr=False)
        help_sha256: str | None
        help_lists_plugin: bool | None
        plugin_validation: str | None
        binding: object | None

    @dataclass(frozen=True, slots=True, kw_only=True)
    class BoardLegObservation:
        watch: object | None
        stream: object | None
        input_sha256: str
        binding: object | None

    @dataclass(frozen=True, slots=True, kw_only=True)
    class HostPathMap:
        tree: Path = field(repr=False)
        seat_home: Path = field(repr=False)
        gemini_config: Path = field(repr=False)
        agy_rw: Path = field(repr=False)
        seat_out: Path = field(repr=False)
        delivered_credential: Path | None = field(default=None, repr=False)

    for name, value in {
        "JailedStep": JailedStep,
        "DeliveredCopy": DeliveredCopy,
        "WindowLaunchResult": WindowLaunchResult,
        "BoardLegObservation": BoardLegObservation,
        "LaunchBinding": LaunchBinding,
        "TracedPath": TracedPath,
        "HostPathMap": HostPathMap,
        "PlantLayoutRefused": type("PlantLayoutRefused", (ValueError,), {}),
        "WatchUnavailable": type("WatchUnavailable", (RuntimeError,), {}),
    }.items():
        monkeypatch.setattr(qualification, name, value, raising=False)
    return qualification


def _window_session(events, *, delivered=b'{"token":{"access_token":"fixture","expiry":"2099-01-01T00:00:00+00:00"}}'):
    class Session(SimpleNamespace):
        def cleanup(self):
            if not getattr(self, "cleaned", False):
                events.append("cleanup")
                self.cleaned = True

    jail = SimpleNamespace(
        env={"HOME": "/seat/home", "HTTPS_PROXY": "http://u:p@127.0.0.1:3128",
             "SSL_CERT_FILE": "/seat/ca.pem", "DBUS_SESSION_BUS_ADDRESS": "drop"},
        profile_digest="f" * 64,
    )
    seat = SimpleNamespace(
        jail=jail, probe_jail=jail, holder_pid=71, seat_dir=Path("/host/seat"),
        review_dir=Path("/host/review"), token=b"fixture", delivered_copy=delivered,
        image_sha256="a" * 64, admission_class="fixture",
        expires_at=None,
    )
    paths = SimpleNamespace(
        tree=Path("/host/review/reviewed-tree"), seat_home=Path("/host/seat/seat-home"),
        gemini_config=Path("/host/seat/gemini-config"),
        agy_rw=Path("/host/seat/seat-home/.agy-rw"), seat_out=Path("/host/seat/seat-out"),
        delivered_credential=Path("/host/seat/gemini-config/antigravity-cli/antigravity-oauth-token"),
    )
    return Session(
        seat=seat, proxy=SimpleNamespace(allowlist_sha256="b" * 64),
        prefix=("ns",), paths=paths,
        authorization=SimpleNamespace(staged_tree_sha256="c" * 64),
        quiescence_latch=SimpleNamespace(is_quiescent=lambda: True),
        trace_path=None, cleaned=False,
    )


@pytest.mark.parametrize("vendor", ["claude", "gemini", "codex", "grok"])
def test_seats_firstseat_exec_record_prelaunch(tmp_path, monkeypatch, vendor):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (False, "unavailable"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    result = pi._exec_leg(vendor, tmp_path, tmp_path, artifact="planted auth text")
    assert result[0] != 0
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["vendor"] == vendor
    assert record["exit_code"] is None
    assert record["outcome"] != "leg_auth_signed_out"
    assert "planted" not in records[0].read_text()
    assert records[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("assurance", [None, (), (b"fixture-token-123456789",)])
def test_seats_firstseat_exec_record_closed_fields(tmp_path, assurance):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import seat_jail
    secret = b"fixture-token-123456789"
    for form in seat_jail.secret_encodings(secret):
        record = pi.leg_exec_record("grok", 1,
            ["grok", "-p", form.decode(), "--cwd", "/some/private/path"],
            auth_state="healthy", model_turn=False, verdict=False, scan_secrets=assurance)
        encoded = json.dumps(record).encode()
        assert not seat_jail.contains_secret(encoded, secret)
        assert len(encoded) <= 4096
        assert b"/some/private/path" not in encoded
        assert record["outcome"] == "leg_execution_failed"


@pytest.mark.parametrize("turn,verdict,state,expected", [
    (False, False, "signed_out", "leg_auth_signed_out"),
    (None, False, "signed_out", "leg_execution_failed"),
    (False, False, "unavailable", "leg_auth_unavailable"),
    (True, True, "unavailable", "leg_execution_failed"),
    (None, None, "healthy", "leg_execution_failed"),
    (False, False, "healthy", "leg_execution_failed"),
    (True, False, "signed_out", "leg_execution_failed"),
    (False, True, "signed_out", "leg_execution_failed"),
])
def test_seats_firstseat_exec_record_auth_observations(turn, verdict, state, expected):
    from phase_loop_runtime import panel_invoker as pi
    assert pi.leg_exec_record("grok", 1, [], auth_state=state,
        model_turn=turn, verdict=verdict)["outcome"] == expected


def test_seats_firstseat_exec_record_nested_launch(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    @pi._retained_leg_exec
    def inner(leg):
        observation = pi._EXEC_OBSERVATION.get()
        observation.update(argv=["fixture", "--model", "private-value"],
                           model_turn=True, verdict=True)
        return 0, "AGREE", ""
    @pi._retained_leg_exec
    def outer(leg):
        return inner(leg)
    assert outer("codex") == (0, "AGREE", "")
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["model_turn"] is True


@pytest.mark.parametrize("kind", ["wide", "symlink", "foreign", "checkout"])
def test_seats_firstseat_exec_record_storage(tmp_path, monkeypatch, kind):
    import os
    from phase_loop_runtime import president_adapter as pa
    root = tmp_path / "records"
    root.mkdir(mode=0o700)
    if kind == "wide":
        root.chmod(0o755)
    elif kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif kind == "foreign":
        real = os.fstat
        def fstat(fd):
            info = real(fd)
            return type("Info", (), {"st_uid": -1, "st_mode": info.st_mode})()
        monkeypatch.setattr(os, "fstat", fstat)
    else:
        (tmp_path / ".git").mkdir()
    with pytest.raises((ValueError, OSError)):
        pa.write_private_record("record.json", {"event": "start"}, root=root)


def test_seats_firstseat_exec_record_detector_error(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    from detect_secrets.core import scan
    monkeypatch.setattr(scan, "scan_line", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    assert pi._scan_exec_field(["--model"], ()) is None
    assert pi._scan_exec_field(["--model"], None) is None


def test_seats_firstseat_exec_record_exception_preserved(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    @pi._retained_leg_exec
    def transport(leg):
        raise RuntimeError("fixture")
    with pytest.raises(RuntimeError, match="fixture"):
        transport("grok")
    assert len(list((tmp_path / "state").rglob("leg-*.json"))) == 1


def test_seats_firstseat_exec_record_broker_context(tmp_path, monkeypatch):
    import threading
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    @pi._retained_leg_exec
    def transport(leg):
        def observe():
            pi._EXEC_OBSERVATION.get().update(argv=["fixture", "--model"], scan_secrets=())
            pi._note_exec_signals(model_turn=True, verdict=True)
        worker = threading.Thread(target=pi._exec_in_context(observe))
        worker.start()
        worker.join()
        return "OK", "AGREE"
    result = transport("gemini")
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["model_turn"] is True and record["verdict"] is True
    assert record["argv_flags"] == ["--model"]
    assert len(result.leg_exec_metadata["record_digest"]) == 64


def test_seats_firstseat_exec_record_scan_before_bound():
    from phase_loop_runtime import panel_invoker as pi, seat_jail
    secret = b"fixture-token-123456789"
    for form in seat_jail.secret_encodings(secret):
        value = "x" * 4090 + form.decode() + "x" * 8000
        assert pi._scan_exec_field(value, (secret,)) is None


def test_seats_firstseat_exec_record_typed_return(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    @pi._retained_leg_exec
    def transport(leg):
        pi._EXEC_OBSERVATION.get().update(auth_state="healthy", model_turn=False, verdict=False)
        return pi._BrokeredSpawnResult("DEGRADED", "", pi._LegFailure(template="auth_failure"))
    result = transport("grok")
    assert result[2] == "leg_execution_failed"
    assert "unknown failure" not in pi._finalize_leg_detail(result[2])


def test_seats_firstseat_exec_record_parent_probes(tmp_path, monkeypatch):
    import subprocess
    from phase_loop_runtime import panel_invoker as pi
    calls = []
    def runner(command, **kw):
        calls.append((command, kw))
        if command[0] == "claude":
            return subprocess.CompletedProcess(command, 1, '{"loggedIn":false}', "")
        return subprocess.CompletedProcess(command, 1, "", "Not logged in")
    monkeypatch.setattr(pi, "run_provider", runner)
    assert pi._parent_auth_state("claude") == "signed_out"
    assert pi._parent_auth_state("codex") == "signed_out"
    assert pi._parent_auth_state("gemini") == "unavailable"
    assert pi._parent_auth_state("grok") == "unavailable"
    assert all(Path(kw["cwd"]) != tmp_path and kw["stdin"] == subprocess.DEVNULL
               and kw["executor"] is True for _, kw in calls)


@pytest.mark.parametrize("route,exit_code", [("print", 41), ("tui", 42)])
def test_seats_firstseat_exec_record_claude_adapters(tmp_path, monkeypatch, route, exit_code):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", route)
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda **k: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda *a: (True, ""))
    monkeypatch.setattr(pi, "_run_claude_print_session", lambda *a, **k: (exit_code, "", "", ""))
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **k: (exit_code, "", "claude_tui_pty_eof_no_output", ""))
    review, out = tmp_path / "review", tmp_path / "out"
    review.mkdir()
    out.mkdir()
    (review / "review-bundle.md").write_text("fixture")
    (review / "review-instructions.md").write_text("fixture")
    @pi._retained_leg_exec
    def run(leg):
        return pi._exec_claude_tui_leg(review, out, 60, "fixture", env={})
    assert run("claude")[0] != "OK"
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["exit_code"] == exit_code
    assert record["auth_state"] == "unavailable"


@pytest.mark.parametrize("vendor,exit_code", [("gemini", 43), ("claude", 44)])
def test_seats_firstseat_exec_record_jailed_adapters(tmp_path, monkeypatch, vendor, exit_code):
    from types import SimpleNamespace
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda *a, **k: b"")
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    jail = SimpleNamespace(env={}, leg=vendor, provider_argv0="/seat/bin/" + vendor,
        profile_digest="d", profile_id="p", filter_digest="f",
        redacted_owner=lambda: [], pass_fds=())
    seat = pi._JailedSeat(jail=jail, probe_jail=jail, holder_pid=1, token=b"fixture-token",
        review_dir=tmp_path, seat_dir=tmp_path, expires_at=None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k:
        SimpleNamespace(returncode=exit_code, stdout="", stderr=""))
    monkeypatch.setattr(pi, "_run_claude_tui_session", lambda **k:
        (exit_code, "not logged in; please run claude login", "", ""))
    @pi._retained_leg_exec
    def run(leg):
        if leg == "gemini":
            return pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="fixture", broker_evidence=None)
        return pi._exec_jailed_claude_leg(seat, timeout_s=60, backstop_s=60,
            model=None, effort=None, prompt="fixture", broker_evidence=None, failure_detail_sink=[])
    assert run(vendor)[0] != "OK"
    assert not seat.notices
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["exit_code"] == exit_code
    assert record["outcome"] == "leg_execution_failed"


def test_seats_firstseat_exec_record_dependency_probe(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.executable_dependency_startup import ExecutableDependencyError
    def unavailable(*a, **kw):
        raise ExecutableDependencyError("dependency_route_unwired")
    monkeypatch.setattr(pi, "run_provider", unavailable)
    assert pi._parent_auth_state("claude") == "unavailable"
    assert pi._parent_auth_state("codex") == "unavailable"


@pytest.mark.parametrize("missing", [None, "claude", "gemini", "grok", "codex", "all"])
def test_seats_firstseat_exec_record_composed_board(tmp_path, missing):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.advisor_board.composition import compose_review_board_report
    composition = compose_review_board_report(is_available=lambda v: missing != "all" and v != missing,
                                               auth_ok=lambda v: True)
    outcome = composition.policy_outcome("plan")
    launched = []
    def spawn(leg, artifact, **kw):
        launched.append(leg)
        return "OK", "AGREE"
    if missing is not None:
        assert outcome.status == "policy_refused" and outcome.fix
        with pytest.raises(pi.PresidentPolicyError):
            invoke_sanctioned_review_transport(composition.board, "fixture", spawn=spawn,
                landing_tier="plan", president_invoke=deferring_president)
        assert not launched
    else:
        assert outcome.status == "admitted"
        result = invoke_sanctioned_review_transport(composition.board, "fixture", spawn=spawn,
            landing_tier="plan", president_invoke=deferring_president, max_concurrency=1)
        assert set(launched) == {"claude", "gemini", "codex", "grok"}
        assert result.legs


@pytest.mark.parametrize("failure", [False, True])
def test_seats_firstseat_exec_record_board_returns(tmp_path, monkeypatch, failure):
    from phase_loop_runtime.advisor_board import composition
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    composed = composition.compose_review_board_report(is_available=lambda v: True, auth_ok=lambda v: True)
    def spawn(leg, artifact, **kw):
        if failure:
            raise ValueError("fixture text omitted from records")
        return "OK", "AGREE"
    result = invoke_sanctioned_review_transport(composed.board, "fixture", spawn=spawn,
        landing_tier="plan", president_invoke=deferring_president, max_concurrency=1)
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == len(result.legs) == 4
    assert all(leg.status == ("DEGRADED" if failure else "OK") for leg in result.legs)
    for leg in result.legs:
        assert getattr(leg, "_leg_exec_metadata", {}).get("record_digest")
    assert all("fixture" not in path.read_text() for path in records)


def test_seats_firstseat_exec_record_provider_metadata(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    spawned = pi._BrokeredSpawnResult("OK", "AGREE")
    spawned.leg_exec_metadata = {"record_digest": "a" * 64, "outcome": "leg_execution_completed"}
    monkeypatch.setattr(pi, "_default_spawn", lambda *a, **kw: spawned)
    result = pi._default_spawn_via_provider("gemini", "fixture", repo_dir=tmp_path)
    assert result.leg_exec_metadata == spawned.leg_exec_metadata
    leg = pi.PanelLegResult("gemini", "OK", "AGREE")
    object.__setattr__(leg, "_leg_exec_metadata", result.leg_exec_metadata)
    assert pi._retain_panel_leg(leg) is leg


def test_seats_firstseat_exec_record_board_storage(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi, president_adapter as pa
    def fail(*args):
        raise OSError("fixture")
    monkeypatch.setattr(pa, "write_private_record", fail)
    result = pi._retain_panel_leg(pi.PanelLegResult("gemini", "OK", "AGREE"))
    assert result.status == "DEGRADED" and not result.text
    assert result.detail == "leg_exec_record_unavailable"


def test_seats_firstseat_exec_record_window_jailed_run_exact_env(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    qualification = _install_firstseat_supplier_double(monkeypatch)
    session = _window_session([])
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=7, stdout="x" * 70000, stderr="")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    done = pi._WindowJailedRun(session.seat, session.quiescence_latch)(
        ["/usr/bin/fixture", "arg"], env={"PATH": "/usr/bin", "MARK": "ok"},
        use_proxy=True, timeout_s=4.0,
    )
    assert isinstance(done, qualification.JailedStep)
    assert done.exit_code == 7 and not done.timed_out and len(done.stdout) == 65536
    assert seen["kwargs"]["cwd"] == pi._seat_jail.SEAT_TREE
    command = seen["command"]
    assert command[:4] == ["/usr/bin/python3", "-I", "-S", "-c"]
    rendered = "\n".join(command)
    assert "://" not in rendered and "u:p" not in rendered and "HTTPS_PROXY=" not in rendered
    payload = seen["kwargs"]["input_text"]
    got = {}
    for item in payload.encode("utf-8").split(b"\0"):
        if not item:
            continue
        key, value = item.split(b"=", 1)
        got[key.decode()] = value.decode()
    assert got == {
        "HTTPS_PROXY": "http://u:p@127.0.0.1:3128",
        "MARK": "ok",
        "PATH": "/usr/bin",
        "SSL_CERT_FILE": "/seat/ca.pem",
    }
    assert "HOME" not in got and "DBUS_SESSION_BUS_ADDRESS" not in got


@pytest.mark.parametrize("bad_env", [
    {"BAD\0NAME": "value"}, {"BAD=NAME": "value"}, {"NAME": "bad\0value"},
    {"NAME": "\ud800"},
])
def test_seats_firstseat_exec_record_window_jailed_run_bad_env_fails_closed(
    monkeypatch, bad_env,
):
    from phase_loop_runtime import panel_invoker as pi
    qualification = _install_firstseat_supplier_double(monkeypatch)
    session = _window_session([])
    monkeypatch.setattr(
        pi, "_run_leg_with_liveness", lambda *a, **k: pytest.fail("launched"),
    )
    done = pi._WindowJailedRun(session.seat, session.quiescence_latch)(
        ["/usr/bin/fixture"], env=bad_env, use_proxy=False, timeout_s=4.0,
    )
    assert done == qualification.JailedStep(exit_code=None, timed_out=False, stdout=b"")


def test_seats_firstseat_exec_record_window_expired_copy_changes_only_expiry():
    from phase_loop_runtime import panel_invoker as pi
    source = {
        "account": "fixture", "token": {
            "access_token": "not-a-live-token", "expiry": "2099-01-01T00:00:00+00:00",
            "scope": "fixture-scope",
        },
    }
    raw, expires_at = pi._window_expired_gemini_copy(json.dumps(source).encode())
    expired = json.loads(raw)
    assert expires_at < pi.time.time()
    assert expired["token"].pop("expiry") != source["token"]["expiry"]
    expected = json.loads(json.dumps(source))
    expected["token"].pop("expiry")
    assert expired == expected


@pytest.mark.parametrize("kind,tree", [
    ("tree_control", True),
    ("credentialed_tree_control", True),
    ("runtime_control", False),
    ("credentialed_runtime_control", False),
    ("measured", False),
    ("expired_copy", False),
])
def test_seats_firstseat_exec_record_window_control_argv(kind, tree):
    from phase_loop_runtime import panel_invoker as pi
    command = pi._window_control_command(kind, "fixture-model")
    production = pi._jailed_gemini_command("fixture-model")
    if tree:
        assert command[0] == "/usr/bin/env"
        assert f"--chdir={pi._seat_jail.SEAT_TREE}" in command
        assert command[-2:] == ["--add-dir", pi._seat_jail.SEAT_TREE]
        assert command != production
    else:
        assert command == production
        assert "--add-dir" not in command


def test_seats_firstseat_exec_record_window_stream_facts_fail_closed():
    from phase_loop_runtime import panel_invoker as pi
    assert pi._window_stream_facts("") == ("NONE", None, None, None)
    success = json.dumps({"event": "result", "result": {
        "status": "SUCCESS", "response": "READY"}})
    assert pi._window_stream_facts(success + "\nNOT JSON\n") == ("NONE", True, None, None)
    partial = json.dumps({
        "event": "step_update", "step_update": {"step_type": "agent_response"},
    })
    assert pi._window_stream_facts(partial) == ("NONE", True, None, None)
    failure = json.dumps({"event": "result", "result": {"status": "FAILURE"}})
    assert pi._window_stream_facts(failure) == ("FAILURE", False, 0, 0)


def test_seats_firstseat_exec_record_window_tracer_is_path_only(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    qualification = _install_firstseat_supplier_double(monkeypatch)
    seat = tmp_path / "seat"
    seat.mkdir()
    parent = tmp_path / "window-trace"
    parent.write_bytes(b"")
    parent.chmod(0o600)
    traced = pi._window_trace_argv(
        str(parent), ("ns",), ["/seat/bin/gemini", "--model", "fixture"],
    )
    syscall_filter = traced[traced.index("-e") + 1]
    assert traced[0] == "/usr/bin/strace" and "-DDD" in traced
    assert "execve" not in syscall_filter
    for banned in ("mount", "quotactl", "pivot_root", "chroot", "umount2"):
        assert banned not in syscall_filter.split("trace=")[-1].split(",")
    assert f"{pi._seat_jail.SEAT_OUT}/window-trace" not in traced
    raw = "\n".join((
        'openat(AT_FDCWD</seat/tree>, ".gemini/settings.json", O_RDONLY) = 3',
        'mkdirat(AT_FDCWD</seat/home>, "created", 0700) = 0',
        'statx(AT_FDCWD</outside>, "/outside/ignored", 0, 0, {}) = 0',
    )).encode()
    parent.write_bytes(raw)
    session = _window_session([])
    session.trace_path = parent
    session.seat.seat_dir = seat
    looked, created, complete = pi._read_window_trace(session, qualification)
    assert complete
    assert {(item.location, item.relpath) for item in looked} == {
        ("tree", ".gemini/settings.json"), ("home", "created"),
    }
    assert {(item.location, item.relpath) for item in created} == {("home", "created")}
    forged = seat / "seat-out"
    forged.mkdir()
    (forged / "window-trace").write_text(
        'openat(AT_FDCWD</seat/tree>, "forged", O_RDONLY) = 3\n')
    session.trace_path = forged / "window-trace"
    assert pi._read_window_trace(session, qualification) == ((), (), False)
    parent.write_bytes(raw + b"\nopenat(AT_FDCWD</seat/tree>, <unfinished ...>\n")
    session.trace_path = parent
    assert pi._read_window_trace(session, qualification)[2] is False


def test_seats_firstseat_exec_record_window_launch_uses_fresh_seat_directory(
    tmp_path, monkeypatch,
):
    from phase_loop_runtime import panel_invoker as pi

    _install_firstseat_supplier_double(monkeypatch)
    commit = "d" * 40
    bases = iter((tmp_path / "launch-1", tmp_path / "launch-2"))
    prepared = []

    @dataclass(frozen=True, slots=True)
    class Completed:
        stdout: str

    @dataclass(frozen=True, slots=True)
    class Authorization:
        staged_tree_sha256: str

    @dataclass(frozen=True, slots=True)
    class Proxy:
        socket: str
        allowlist_sha256: str

    @dataclass(frozen=True, slots=True)
    class Seat:
        review_dir: Path
        seat_dir: Path
        notices: tuple = ()

    def mkdtemp(*, prefix, dir):
        assert prefix == "pl-window-launch-"
        assert Path(dir) == tmp_path
        base = next(bases)
        base.mkdir()
        return str(base)

    def host_git(source, *args, **kwargs):
        assert Path(source) == tmp_path
        return Completed(stdout=commit + "\n")

    def prepare_authorization(
        board, artifact, *, mode, canonical_repo_authority, stage_review_tree,
    ):
        return Authorization(staged_tree_sha256="c" * 64)

    def activate_authorization(
        authorization, board, artifact, *, mode, canonical_repo_authority,
    ):
        return None

    def close_authorization(authorization):
        return None

    def stage_review_tree(source, *, parent):
        staged = Path(parent) / "staged"
        staged.mkdir()
        return staged

    def staged_source_commit(tree):
        return commit

    @contextmanager
    def lease_seat_id(count):
        yield 2

    @contextmanager
    def start_proxy(*, refuse_all=False):
        yield Proxy(socket="proxy.sock", allowlist_sha256="b" * 64)

    @contextmanager
    def isolated_network(
        *, timeout_s, required, seat_uid_map, proxy_socket, proxy_port,
    ):
        yield ("namespace",)

    def prepare_gemini(
        review_dir, seat_dir, authorization, seat_id, holder_pid, prompt_parts, egress,
        *, env=None, review_monitor=None, quiescence_latch=None, credential="live",
    ):
        prepared.append(Path(seat_dir))
        return Seat(review_dir=Path(review_dir), seat_dir=Path(seat_dir))

    monkeypatch.setattr(pi.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(pi._review_stage, "host_git", host_git)
    monkeypatch.setattr(pi, "prepare_review_isolation_authorization", prepare_authorization)
    monkeypatch.setattr(pi, "activate_review_isolation_authorization", activate_authorization)
    monkeypatch.setattr(pi, "close_review_isolation_authorization", close_authorization)
    monkeypatch.setattr(pi._review_stage, "stage_review_tree", stage_review_tree)
    monkeypatch.setattr(pi._review_stage, "staged_source_commit", staged_source_commit)
    monkeypatch.setattr(pi._review_stage, "remove_review_stage", lambda path: None)
    monkeypatch.setattr(pi._seat_uid, "subordinate_range", lambda path: (1, 2))
    monkeypatch.setattr(pi._seat_uid, "seat_id_count", lambda uids, gids: 1)
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id", lease_seat_id)
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda prefix: 71)
    monkeypatch.setattr(pi._seat_egress_proxy, "start_proxy", start_proxy)
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", isolated_network)
    monkeypatch.setattr(pi, "_prepare_jailed_gemini", prepare_gemini)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat: None)

    spec = pi.WindowLaunchSpec(
        kind="runtime_control",
        qualification_input=SimpleNamespace(
            repo=tmp_path, commit=commit, layout=SimpleNamespace(rows=()),
        ),
        model="fixture",
        timeout_s=2.0,
    )
    with pi._open_window_launch(spec):
        pass
    with pi._open_window_launch(spec):
        pass
    assert prepared == [tmp_path / "launch-1" / "seat", tmp_path / "launch-2" / "seat"]
    assert prepared[0].parent != prepared[1].parent


def test_seats_firstseat_exec_record_window_board_uses_fresh_gemini_seat(
    tmp_path, monkeypatch,
):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_policy
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    _install_firstseat_supplier_double(monkeypatch)
    board_bases = iter((tmp_path / "board-1", tmp_path / "board-2"))
    panel_bases = iter((tmp_path / "panel-1", tmp_path / "panel-2"))
    board_allocations = []
    panel_allocations = []
    prepared_seats = []
    invocation_errors = []

    @dataclass(frozen=True, slots=True)
    class Authorization:
        staged_tree_sha256: str

    @dataclass(frozen=True, slots=True)
    class Route:
        jailed: bool

    @dataclass(frozen=True, slots=True)
    class Proxy:
        socket: str
        allowlist_sha256: str

    @dataclass(frozen=True, slots=True)
    class Prepared:
        review_dir: Path
        local_tree: Path
        snapshot_sha256: str
        sandbox_ref: str

    @dataclass(frozen=True, slots=True)
    class Backend:
        name: str = "local"

        def commit(self, prepared, request):
            return None

        def release(self, prepared):
            return None

    @dataclass(frozen=True, slots=True)
    class Placement:
        backend: object
        prepared: object
        authorization_sha256: str

        def record_backend_receipt(self, receipt):
            return None

    @dataclass(frozen=True, slots=True)
    class Seat:
        review_dir: Path
        seat_dir: Path
        notices: tuple = ()

    class Broker:
        def __init__(self, *args, **kwargs):
            self.evidence = {}

        def run_credentialless_client(self, adapter, *, deadline_s, cancel_event=None):
            status, text = adapter.invoke()
            return {
                "schema": "parent_unix_broker_v1", "status": status, "text": text,
            }, {"fake": True}

        def close(self):
            return None

    authorization = Authorization(staged_tree_sha256="c" * 64)
    backend = Backend()

    def mkdtemp(*, prefix, dir):
        assert Path(dir) == tmp_path
        if prefix == "pl-window-board-":
            path = next(board_bases)
            board_allocations.append(path)
        elif prefix == "pl-panel-":
            path = next(panel_bases)
            panel_allocations.append(path)
        else:
            raise AssertionError(prefix)
        path.mkdir()
        return str(path)

    def prepare_local_stage(repo, review_dir, *, floor_bytes, mark):
        tree = Path(review_dir) / pi._review_stage.REVIEW_STAGE_TREE_DIRNAME
        git = tree / ".git"
        git.mkdir(parents=True)
        (git / "phase-loop-source-commit").write_text("d" * 40, encoding="utf-8")
        return Prepared(
            review_dir=Path(review_dir), local_tree=tree,
            snapshot_sha256="c" * 64, sandbox_ref="local:fixture",
        )

    @contextmanager
    def lease_seat_id(count):
        yield 2

    @contextmanager
    def start_proxy(*, refuse_all=False):
        yield Proxy(socket="proxy.sock", allowlist_sha256="b" * 64)

    @contextmanager
    def isolated_network(
        *, timeout_s, seat_uid_map=False, required=False,
        proxy_socket=None, proxy_port=None,
    ):
        yield ("namespace",)

    def prepare_gemini(
        review_dir, seat_dir, review_authorization, seat_id, holder_pid,
        prompt_parts, egress, *, env=None, review_monitor=None,
        quiescence_latch=None, credential="live",
    ):
        prepared_seats.append(Path(seat_dir))
        return Seat(review_dir=Path(review_dir), seat_dir=Path(seat_dir))

    def exec_gemini(
        seat, *, deadline_s, model, prompt, broker_evidence,
        egress_evidence=None, failure_detail_sink=None, quiescence_latch=None,
        review_monitor=None, window_board=None, review_authorization=None,
    ):
        return "OK", "review\nAGREE"

    report = SimpleNamespace(
        board=DEFAULT_BOARD,
        policy_outcome=lambda tier: SimpleNamespace(status="admitted"),
    )
    monkeypatch.setattr(
        "phase_loop_runtime.advisor_board.composition.compose_review_board_report",
        lambda: report,
    )
    monkeypatch.setattr(pi.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(pi, "prepare_review_isolation_authorization", lambda *a, **k: authorization)
    monkeypatch.setattr(pi, "close_review_isolation_authorization", lambda value: None)
    monkeypatch.setattr(pi, "set_review_instruction_digest", lambda value: object())
    monkeypatch.setattr(pi, "reset_review_instruction_digest", lambda token: None)
    monkeypatch.setattr(
        "phase_loop_runtime.president_adapter.build_president_invoke", lambda *a, **k: object(),
    )
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda: None)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda path: tmp_path)
    monkeypatch.setattr(pi, "_has_injected_review_execution_seam", lambda *, leg=None: False)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (Route(True), [], None))
    monkeypatch.setattr(pi._sandbox_policy, "effective_floor_bytes", lambda path: 1)
    monkeypatch.setattr(pi._sandbox_retention, "reap_until_free", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_refuse_unless_executed_remotely", lambda *a, **k: None)
    monkeypatch.setattr(
        pi._sandbox_policy, "select_sandbox_root",
        lambda **kwargs: sandbox_policy.SandboxRootChoice(None, tmp_path, False),
    )
    monkeypatch.setattr(pi._sandbox_placement, "resolve_backend", lambda choice: backend)
    monkeypatch.setattr(pi, "_placement_gate", lambda value: None)
    monkeypatch.setattr(pi._sandbox_placement, "prepare_local_stage", prepare_local_stage)
    monkeypatch.setattr(
        pi._sandbox_placement, "LegPlacement",
        lambda value, prepared, *, scheme, authorization_sha256: Placement(
            value, prepared, authorization_sha256,
        ),
    )
    monkeypatch.setattr(pi, "_record_sandbox_facts", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._seat_uid, "subordinate_range", lambda path: (1, 2))
    monkeypatch.setattr(pi._seat_uid, "seat_id_count", lambda uids, gids: 1)
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id", lease_seat_id)
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda prefix: 71)
    monkeypatch.setattr(pi._seat_egress_proxy, "start_proxy", start_proxy)
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda proxy: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", isolated_network)
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda *, applied: {})
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(
        pi, "derive_review_leg_authorization",
        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=10**30),
    )
    monkeypatch.setattr(pi, "ParentUnixBroker", Broker)
    monkeypatch.setattr(pi, "_render_broker_pointer_prompt", lambda *a, **k: "frame")
    monkeypatch.setattr(pi, "_prepare_jailed_gemini", prepare_gemini)
    monkeypatch.setattr(pi, "_exec_jailed_gemini_leg", exec_gemini)
    monkeypatch.setattr(pi._review_stage, "remove_review_stage", lambda path: None)
    classify_exception = pi._exception_failure

    def capture_exception(exc):
        invocation_errors.append(repr(exc))
        return classify_exception(exc)

    monkeypatch.setattr(pi, "_exception_failure", capture_exception)

    receipt = "e" * 64

    def invoke(board, artifact, **kwargs):
        try:
            spawned = pi._default_spawn(
                "gemini", artifact, repo_dir=tmp_path, mode="review", model="fixture",
                review_authorization=kwargs["review_authorization"],
                canonical_repo_authority=tmp_path,
            )
            assert spawned[:2] == ("OK", "review\nAGREE"), tuple(spawned)
        except BaseException as exc:
            invocation_errors.append(repr(exc))
            raise
        run = pi._registered_window_board(kwargs["review_authorization"])
        run.watch = SimpleNamespace(read_marker_opened=True)
        run.stream = SimpleNamespace(final=True)
        run.binding = SimpleNamespace(image_sha256="a" * 64)
        run.tool_steps = 1
        legs = []
        for seat in board.seats:
            leg = pi.PanelLegResult(
                seat.harness, "OK", "review\nAGREE", seat_key=seat.seat_key,
            )
            object.__setattr__(leg, "_leg_exec_metadata", {"record_digest": receipt})
            legs.append(leg)
        return pi.PanelResult(tuple(legs), president=SimpleNamespace())

    monkeypatch.setattr(pi, "invoke_board", invoke)
    spec = pi.WindowBoardSpec(
        qualification_input=SimpleNamespace(repo=tmp_path, layout=SimpleNamespace()),
        monitoring_policy="bounded",
    )
    first = pi.window_board_launch(spec)
    second = pi.window_board_launch(spec)
    assert not invocation_errors
    assert first.canonical_gemini and second.canonical_gemini
    assert board_allocations == [tmp_path / "board-1", tmp_path / "board-2"]
    assert panel_allocations == [tmp_path / "panel-1", tmp_path / "panel-2"]
    assert prepared_seats == [
        tmp_path / "panel-1" / "seat", tmp_path / "panel-2" / "seat",
    ]
    assert prepared_seats[0].parent != prepared_seats[1].parent


@pytest.mark.parametrize(
    "kind,seeded,credential,bracketed",
    [
        ("tree_control", False, False, False),
        ("credentialed_tree_control", False, True, False),
        ("runtime_control", True, False, False),
        ("credentialed_runtime_control", True, True, False),
        ("measured", False, True, True),
        ("expired_copy", False, True, False),
    ],
)
def test_seats_firstseat_exec_record_window_launch_order(
    tmp_path, monkeypatch, kind, seeded, credential, bracketed,
):
    from phase_loop_runtime import panel_invoker as pi
    qualification = _install_firstseat_supplier_double(monkeypatch)
    events = []
    session = _window_session(events)

    @contextmanager
    def opened(spec):
        events.append("open")
        try:
            yield session
        finally:
            events.append("proxy_exit")

    class Watch:
        def prove_sentinel(self, run):
            events.append("sentinel")
            return True
        def drain_and_close(self, *, quiescent):
            events.append("watch_close")
            return SimpleNamespace(read_marker_opened=kind == "measured")

    def fence(proxy, marker, window):
        events.append(f"fence:{marker}:{window}")
        return SimpleNamespace(acknowledged=True, acked_ns=1, fence_id=marker)

    def process(*args, **kwargs):
        events.append("provider")
        raw = "\n".join((
            json.dumps({"event": "init", "conversation_id": "c"}),
            json.dumps({"event": "result", "conversation_id": "c", "result": {
                "conversation_id": "c", "status": "SUCCESS", "response": "READY"}}),
        ))
        return pi._WindowProcess(0, False, raw)

    monkeypatch.setattr(pi, "_open_window_launch", opened)
    monkeypatch.setattr(pi, "_run_window_process", process)
    monkeypatch.setattr(pi, "_read_window_trace", lambda *a: ((), (), True))
    monkeypatch.setattr(pi, "_hold_window_fence_gap", lambda ns: events.append("quiet"))
    monkeypatch.setattr(pi._seat_egress_proxy, "fence", fence, raising=False)
    monkeypatch.setattr(pi._seat_egress_proxy, "proxy_stream",
        lambda proxy: events.append("stream") or SimpleNamespace(final=True), raising=False)
    monkeypatch.setattr(pi._sandbox_egress, "wait_bridge_exit",
        lambda prefix: events.append("bridge") or True, raising=False)
    def seed_runtime_plants(layout, paths):
        events.append("seed")

    def arm_watch(layout, paths, *, kind):
        events.append("arm")
        return Watch()

    monkeypatch.setattr(
        qualification, "seed_runtime_plants", seed_runtime_plants, raising=False,
    )
    monkeypatch.setattr(qualification, "arm_watch", arm_watch, raising=False)
    monkeypatch.setattr(qualification, "measure_issuer",
        lambda delivered: events.append("issuer") or SimpleNamespace(outcome="pass"), raising=False)
    def scan(holder_pid, seat_root, layout, paths, *, delivered):
        events.append("scan:credential" if delivered is not None else "scan:none")
        return SimpleNamespace(scan_complete=True)
    monkeypatch.setattr(qualification, "scan_seat", scan, raising=False)
    monkeypatch.setattr(qualification, "run_bracket",
        lambda proxy, run: events.append("bracket") or SimpleNamespace(), raising=False)
    monkeypatch.setattr(pi, "_broker_gemini_stream_protocol",
        lambda *a, **k: SimpleNamespace(transport="input"))
    monkeypatch.setattr(pi, "_render_broker_pointer_prompt", lambda *a, **k: "frame")

    spec = pi.WindowLaunchSpec(
        kind=kind, qualification_input=SimpleNamespace(
            layout=SimpleNamespace(rows=()), commit="d" * 40, repo=tmp_path,
        ), model="fixture", timeout_s=12.0,
    )
    result = pi.window_control_launch(spec)
    assert result.status == "SUCCESS" and result.error is None
    assert ("seed" in events) is seeded
    assert ("scan:credential" in events) is credential
    assert ("bracket" in events) is bracketed
    assert events.index("arm") < events.index("sentinel") < events.index("fence:start:leg")
    if kind == "measured":
        assert events.index("issuer") < events.index("provider")
    assert events.index("provider") < events.index("bridge") < events.index("fence:end:leg")
    assert events.index("fence:end:leg") < events.index("watch_close")
    scans = [i for i, item in enumerate(events) if item.startswith("scan:")]
    assert bool(scans) is credential
    if credential:
        assert events.index("watch_close") < min(scans)
    if bracketed:
        assert events.index("scan:credential") < events.index("bracket") < events.index("cleanup")
    assert events.index("cleanup") < events.index("proxy_exit") < events.index("stream")


@pytest.mark.parametrize("failed,expected", [("bridge", "bridge_wait_timeout"), ("end", "fence_unacknowledged")])
def test_seats_firstseat_exec_record_window_failed_end_still_reads(
    tmp_path, monkeypatch, failed, expected,
):
    from phase_loop_runtime import panel_invoker as pi
    qualification = _install_firstseat_supplier_double(monkeypatch)
    events = []
    session = _window_session(events)

    @contextmanager
    def opened(spec):
        yield session

    class Watch:
        def prove_sentinel(self, run): return True
        def drain_and_close(self, *, quiescent):
            events.append("watch_close")
            return SimpleNamespace(read_marker_opened=True)

    def fence(proxy, marker, window):
        events.append(marker)
        return SimpleNamespace(acknowledged=not (failed == "end" and marker == "end"),
                               acked_ns=1, fence_id=marker)

    monkeypatch.setattr(pi, "_open_window_launch", opened)
    monkeypatch.setattr(pi, "_run_window_process", lambda *a, **k: pi._WindowProcess(
        0, False, json.dumps({"event": "result", "result": {
            "status": "SUCCESS", "response": "marker"}})))
    monkeypatch.setattr(pi._seat_egress_proxy, "fence", fence, raising=False)
    monkeypatch.setattr(pi._seat_egress_proxy, "proxy_stream",
        lambda p: SimpleNamespace(final=True), raising=False)
    monkeypatch.setattr(pi._sandbox_egress, "wait_bridge_exit",
        lambda p: events.append("bridge") or failed != "bridge", raising=False)
    def arm_watch(layout, paths, *, kind):
        return Watch()

    def scan_seat(holder_pid, seat_root, layout, paths, *, delivered):
        events.append("scan")
        return SimpleNamespace()

    def measure_issuer(delivered):
        return SimpleNamespace()

    def run_bracket(proxy, run):
        events.append("bracket")
        return SimpleNamespace()

    monkeypatch.setattr(qualification, "arm_watch", arm_watch, raising=False)
    monkeypatch.setattr(qualification, "scan_seat", scan_seat, raising=False)
    monkeypatch.setattr(qualification, "measure_issuer", measure_issuer, raising=False)
    monkeypatch.setattr(qualification, "run_bracket", run_bracket, raising=False)
    monkeypatch.setattr(pi, "_broker_gemini_stream_protocol",
        lambda *a, **k: SimpleNamespace(transport="input"))
    monkeypatch.setattr(pi, "_render_broker_pointer_prompt", lambda *a, **k: "frame")
    result = pi.window_control_launch(pi.WindowLaunchSpec(
        kind="measured", qualification_input=SimpleNamespace(
            layout=SimpleNamespace(rows=()), commit="d" * 40, repo=tmp_path),
        model="fixture", timeout_s=2,
    ))
    assert result.error == expected
    assert "watch_close" in events and "scan" in events and "bracket" not in events
    assert ("end" in events) is (failed == "end")


def test_seats_firstseat_exec_record_window_help_and_plugin(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    qualification = _install_firstseat_supplier_double(monkeypatch)
    outputs = ["usage: gemini plugin\n", json.dumps({
        "findings": [], "counts": {"hooks": 1, "mcpServers": 1, "rules": 1, "skills": 1},
    })]
    monkeypatch.setattr(pi, "_window_plugin_copies", lambda *a: ("/seat/out/p",))
    monkeypatch.setattr(pi, "_run_window_process",
        lambda *a, **k: pi._WindowProcess(0, False, outputs.pop(0)))
    monkeypatch.setattr(pi._sandbox_egress, "wait_bridge_exit", lambda p: True, raising=False)

    def fence(proxy, marker, window):
        return SimpleNamespace(acknowledged=True, acked_ns=1, fence_id="f")

    class Watch:
        def prove_sentinel(self, run):
            return True

        def drain_and_close(self, *, quiescent):
            return SimpleNamespace(read_marker_opened=False)

    def arm_watch(layout, paths, *, kind):
        return Watch()

    def scan_seat(holder_pid, seat_root, layout, paths, *, delivered):
        return SimpleNamespace()

    monkeypatch.setattr(pi._seat_egress_proxy, "fence", fence, raising=False)
    monkeypatch.setattr(pi._seat_egress_proxy, "proxy_stream", lambda p: SimpleNamespace(final=True), raising=False)
    monkeypatch.setattr(qualification, "arm_watch", arm_watch, raising=False)
    monkeypatch.setattr(qualification, "scan_seat", scan_seat, raising=False)
    for kind in ("help", "plugin_validation"):
        session = _window_session([])
        @contextmanager
        def opened(spec, session=session):
            yield session
        monkeypatch.setattr(pi, "_open_window_launch", opened)
        result = pi.window_control_launch(pi.WindowLaunchSpec(
            kind=kind, qualification_input=SimpleNamespace(
                layout=SimpleNamespace(rows=()), commit="d" * 40, repo=tmp_path),
            model="fixture", timeout_s=2,
        ))
        assert result.status == "SUCCESS"
        if kind == "help":
            assert result.help_lists_plugin is True
            assert result.help_sha256 == hashlib.sha256(b"usage: gemini plugin\n").hexdigest()
        else:
            assert result.plugin_validation == "valid"


def test_seats_firstseat_exec_record_window_board_frame_is_opt_in():
    from phase_loop_runtime import panel_invoker as pi
    jail = pi._seat_jail
    normal = pi._broker_review_jail_preamble(model_only_network=True)
    assert normal == pi._broker_review_jail_preamble(
        model_only_network=True, qualification_board=False)
    assert normal.startswith(
        "You are a reviewer with a private sandbox. Produce exactly one report.\n")
    assert f"DISPOSABLE CLONE at {jail.SEAT_TREE}" in normal
    assert f"read-only file {jail.SEAT_BUNDLE}" in normal
    assert "window-read.txt" not in normal
    plain = pi._broker_review_jail_preamble(model_only_network=False)
    assert "There is no network beyond your own model" not in plain
    assert "You MAY run commands and read and write files inside that clone" in plain
    qualified = pi._broker_review_jail_preamble(
        model_only_network=True, qualification_board=True)
    assert qualified != normal
    assert f"{jail.SEAT_TREE}/window-read.txt" in qualified
    assert "DISPOSABLE CLONE" not in qualified
    assert "review-bundle.md" not in qualified
    tooled = json.loads(pi._broker_gemini_stream_protocol(
        "frame", tooled=True, qualification_board=False).transport)
    tooled_body = tooled["message"]["content"]
    assert (
        f"Review with your tools: read {jail.SEAT_BUNDLE} in full and the code at "
        f"{jail.SEAT_TREE}, and run commands there to check claims."
    ) in tooled_body
    assert "window-read.txt" not in tooled_body
    board = json.loads(pi._broker_gemini_stream_protocol(
        "frame", tooled=True, qualification_board=True).transport)
    board_body = board["message"]["content"]
    assert f"{jail.SEAT_TREE}/window-read.txt" in board_body
    assert f"read {jail.SEAT_BUNDLE} in full" not in board_body
    untouched = json.loads(pi._broker_gemini_stream_protocol(
        "frame", tooled=False).transport)
    untouched_body = untouched["message"]["content"]
    assert "Do not use or request tools, commands, files, network, browser, MCP" in untouched_body
    assert "window-read.txt" not in untouched_body


def test_seats_firstseat_exec_record_window_board_hooks_real_gemini_leg(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    events = []
    session = _window_session(events)
    observer = SimpleNamespace(proxy=object(), tool_steps=None)
    observer.start = lambda *a: events.append("watch_start") or True
    observer.finish = lambda *a: events.append("watch_finish")
    monkeypatch.setattr(pi, "_record_broker_provider_evidence", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_record_executable_dependency_evidence", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: events.append("cleanup"))
    monkeypatch.setattr(pi, "_note_exec_result", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_broker_gemini_stream_protocol",
        lambda *a, **k: events.append(f"qualify:{k.get('qualification_board')}")
        or SimpleNamespace(transport="input", protocol="fixture", chunk_sha256=(),
                           chunk_bytes=(), final_event_sha256="f" * 64))
    monkeypatch.setattr(pi, "_run_leg_with_liveness",
        lambda *a, **k: events.append("provider")
        or SimpleNamespace(returncode=0, stdout="stream", stderr=""))
    monkeypatch.setattr(pi, "_broker_gemini_stream_result",
        lambda *a, **k: (0, "review\nAGREE", "", {"provider_stream_tool_steps": 1}))
    monkeypatch.setattr(pi, "_classify_leg", lambda *a: "OK")
    result = pi._exec_jailed_gemini_leg(
        session.seat, deadline_s=3, model="fixture", prompt="frame",
        broker_evidence=None, quiescence_latch=session.quiescence_latch,
        window_board=observer,
        review_authorization=SimpleNamespace(staged_tree_sha256="c" * 64),
    )
    assert result == ("OK", "review\nAGREE") and observer.tool_steps == 1
    assert events == [
        "qualify:True", "watch_start", "provider", "watch_finish", "cleanup",
    ]


def test_seats_firstseat_exec_record_window_board_launch(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    qualification = _install_firstseat_supplier_double(monkeypatch)
    report = SimpleNamespace(
        board=DEFAULT_BOARD,
        policy_outcome=lambda tier: SimpleNamespace(status="admitted"),
    )
    monkeypatch.setattr(
        "phase_loop_runtime.advisor_board.composition.compose_review_board_report",
        lambda: report,
    )
    authorization = SimpleNamespace(staged_tree_sha256="c" * 64)
    monkeypatch.setattr(pi, "prepare_review_isolation_authorization", lambda *a, **k: authorization)
    monkeypatch.setattr(pi, "set_review_instruction_digest", lambda value: object())
    monkeypatch.setattr(pi, "reset_review_instruction_digest", lambda token: None)
    monkeypatch.setattr(
        "phase_loop_runtime.president_adapter.build_president_invoke", lambda *a, **k: object())
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: tmp_path)
    receipt = "e" * 64

    def invoke(board, artifact, **kwargs):
        run = pi._registered_window_board(kwargs["review_authorization"])
        run.watch = SimpleNamespace(read_marker_opened=True)
        run.stream = SimpleNamespace(final=True)
        run.binding = SimpleNamespace(image_sha256="a" * 64)
        run.tool_steps = 1
        legs = []
        for seat in board.seats:
            leg = pi.PanelLegResult(seat.harness, "OK", "review\nAGREE", seat_key=seat.seat_key)
            object.__setattr__(leg, "_leg_exec_metadata", {"record_digest": receipt})
            legs.append(leg)
        return pi.PanelResult(tuple(legs), president=SimpleNamespace())

    monkeypatch.setattr(pi, "invoke_board", invoke)
    result = pi.window_board_launch(pi.WindowBoardSpec(
        qualification_input=SimpleNamespace(repo=tmp_path, layout=SimpleNamespace()),
        monitoring_policy="bounded",
    ))
    assert isinstance(result, pi.WindowBoardResult)
    assert result.composition == "admitted" and result.board_outcome == "terminated"
    assert result.canonical_gemini and result.staged_read
    assert result.exec_record_sha256 == receipt
    with pytest.raises(TypeError):
        result.leg_exec_records["gemini"] = None
    assert result.gemini.watch.read_marker_opened and result.gemini.stream.final
    assert result.gemini.input_sha256 == hashlib.sha256(pi._WINDOW_BOARD_INPUT.encode()).hexdigest()


def test_seats_firstseat_exec_record_window_board_refusal(tmp_path, monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    _install_firstseat_supplier_double(monkeypatch)
    report = SimpleNamespace(
        board=None,
        policy_outcome=lambda tier: SimpleNamespace(status="policy_refused"),
    )
    monkeypatch.setattr(
        "phase_loop_runtime.advisor_board.composition.compose_review_board_report",
        lambda: report,
    )
    monkeypatch.setattr(pi, "invoke_board", lambda *a, **k: pytest.fail("launched"))
    result = pi.window_board_launch(pi.WindowBoardSpec(
        qualification_input=SimpleNamespace(repo=tmp_path, layout=SimpleNamespace()),
        monitoring_policy="bounded",
    ))
    assert result.composition == "refused" and result.board_outcome == "not_terminated"
    assert result.gemini.watch is None and result.gemini.stream is None




class PanelInvokerTest(unittest.TestCase):
    def test_available_legs_uses_injected_probe(self):
        # only codex + claude "installed"
        present = {"codex", "claude"}
        legs = available_panel_legs(probe=lambda cli: cli in present)
        self.assertEqual(set(legs), {"codex", "claude"})

    def test_available_panel_legs_includes_grok_when_present(self):
        # ah#171: grok is exposed (ordered last) when its CLI is installed, so a caller
        # whose gemini/agy leg is down reaches a 4th independent vendor without a
        # hand-rolled grok CLI.
        legs = available_panel_legs(probe=lambda cli: True)
        self.assertEqual(legs, ("codex", "gemini", "claude", "grok"))

    def test_available_panel_legs_grok_is_availability_aware(self):
        # grok absent -> not returned (a host without the grok CLI still gets the frozen
        # 3-tuple), and the byte-frozen PANEL_LEGS keystone is never mutated.
        legs = available_panel_legs(probe=lambda cli: cli != "grok")
        self.assertNotIn("grok", legs)
        self.assertEqual(legs, ("codex", "gemini", "claude"))
        self.assertEqual(PANEL_LEGS, ("codex", "gemini", "claude"))

    def test_invoke_flags_per_leg_status(self):
        def spawn(leg, artifact):
            if leg == "codex":
                return ("ok", "AGREE. looks fine")
            if leg == "gemini":
                return ("timeout", "")
            raise RuntimeError("claude leg crashed")

        result = invoke_panel("ARTIFACT", ["codex", "gemini", "claude"], spawn=spawn)
        by_leg = {leg.leg: leg for leg in result.legs}
        self.assertEqual(by_leg["codex"].status, "OK")
        self.assertTrue(by_leg["codex"].usable)
        self.assertEqual(by_leg["gemini"].status, "TIMEOUT")
        self.assertFalse(by_leg["gemini"].usable)
        # a crashing leg is fail-closed to degraded, never raised
        self.assertEqual(by_leg["claude"].status, "DEGRADED")
        # agent-harness#1102 r7: an exception's own text is not our vocabulary; the leg's
        # detail names an unknown failure (its message goes only to the private log).
        self.assertTrue((by_leg["claude"].detail or "").startswith("unknown failure"))
        self.assertEqual(result.usable_legs, (by_leg["codex"],))

    def test_ok_with_empty_text_becomes_empty(self):
        result = invoke_panel("A", ["codex"], spawn=lambda leg, art: ("ok", "   "))
        self.assertEqual(result.legs[0].status, "EMPTY")
        self.assertFalse(result.legs[0].usable)

    def test_unknown_status_degrades(self):
        result = invoke_panel("A", ["codex"], spawn=lambda leg, art: ("weird", "x"))
        self.assertEqual(result.legs[0].status, "DEGRADED")

    def test_leg_status_validation(self):
        with self.assertRaises(ValueError):
            PanelLegResult(leg="codex", status="not_a_status")

    def test_leg_statuses_are_canonical_uppercase(self):
        self.assertEqual(LEG_STATUSES, ("OK", "EMPTY", "TIMEOUT", "ERROR", "DEGRADED", "UNAVAILABLE"))
        self.assertEqual(PanelLegResult(leg="codex", status="ok", text="AGREE").status, "OK")
        self.assertEqual(PanelLegResult(leg="codex", status="Ok", text="AGREE").status, "OK")

    def test_panel_request_uses_metadata_only_redaction_and_scaled_timeouts(self):
        request = PanelRequest(artifact="x" * 400_000)
        self.assertEqual(request.redaction_posture, "metadata_only")
        self.assertGreater(request.timeout_seconds_for_leg("codex"), panel_leg_timeout_seconds("codex", "small"))
        self.assertLessEqual(request.timeout_seconds_for_leg("codex"), 1800)
        with self.assertRaises(ValueError):
            PanelRequest(artifact="bundle", redaction_posture="raw_payload")

    def test_panel_legs_are_three_vendors(self):
        self.assertEqual(PANEL_LEGS, ("codex", "gemini", "claude"))

    def test_artifact_ref_wins_over_inline_artifact_for_panel(self):
        seen = {}

        def spawn(leg, artifact):
            seen[leg] = artifact
            return ("ok", "AGREE")

        with TemporaryDirectory() as td:
            p = Path(td) / "bundle.md"
            p.write_text("FROM_ARTIFACT_REF", encoding="utf-8")
            invoke_panel("INLINE_SHOULD_NOT_APPEAR", ["codex"], artifact_ref=str(p), spawn=spawn)
        self.assertEqual(seen["codex"], "FROM_ARTIFACT_REF")

    def test_board_threads_artifact_ref_and_context_refs(self):
        seen = {}

        def spawn(leg, artifact):
            seen[leg] = artifact
            return ("ok", "AGREE")

        with TemporaryDirectory() as td:
            bundle = Path(td) / "bundle.md"
            bundle.write_text("FROM_BOARD_REF", encoding="utf-8")
            ref = Path(td) / "private.txt"
            ref.write_text("PRIVATE_BODY_ABSENT", encoding="utf-8")
            invoke_sanctioned_review_transport(
                DEFAULT_BOARD,
                "INLINE",
                artifact_ref=str(bundle),
                context_refs=[str(ref)],
                spawn=spawn,
                landing_tier="production_code",
                president_invoke=deferring_president,
            )
        self.assertIn("FROM_BOARD_REF", seen["codex"])
        self.assertNotIn("PRIVATE_BODY_ABSENT", seen["codex"])
        self.assertIn(str(ref.resolve()), seen["codex"])

    def test_board_threads_timeout_overrides_to_real_spawn_boundary(self):
        seen_timeouts = {}

        def spawn(leg, artifact, **kwargs):
            seen_timeouts[leg] = kwargs.get("timeout_s")
            return ("OK", "AGREE")

        with patch("phase_loop_runtime.panel_invoker._default_spawn_via_provider", side_effect=spawn):
            invoke_sanctioned_review_transport(
                DEFAULT_BOARD,
                "ARTIFACT",
                timeouts_by_leg={"gemini": 137},
                max_concurrency=1,
                landing_tier="production_code",
                president_invoke=deferring_president,
            )

        self.assertEqual(seen_timeouts["gemini"], 137)
        self.assertIsNone(seen_timeouts["codex"])
        self.assertIsNone(seen_timeouts["claude"])

    def test_panel_request_threads_artifact_ref_and_timeout_field_names(self):
        seen = {}

        def spawn(leg, artifact):
            seen[leg] = artifact
            return ("ok", "AGREE")

        with TemporaryDirectory() as td:
            p = Path(td) / "bundle.md"
            p.write_text("FROM_REQUEST_REF", encoding="utf-8")
            req = PanelRequest(
                artifact="INLINE",
                artifact_ref=str(p),
                legs=("codex",),
                timeout_seconds_by_leg={"codex": 123},
            )
            invoke_panel_request(req, spawn=spawn)
        self.assertEqual(seen["codex"], "FROM_REQUEST_REF")
        self.assertIn("timeout_seconds_by_leg", {field.name for field in fields(PanelRequest)})
        self.assertNotIn("timeouts_by_leg", {field.name for field in fields(PanelRequest)})

    def test_panel_request_deliberately_excludes_brief_ref(self):
        request_fields = {field.name for field in fields(PanelRequest)}
        self.assertNotIn("brief_ref", request_fields)


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize("failure", ["refused", "missing", "launch"])
def test_seats_firstseat_exec_record_tui_prelaunch(tmp_path, monkeypatch, failure):
    from phase_loop_runtime import panel_invoker as pi
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", "tui")
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda **k: (True, "supported"))
    monkeypatch.setattr(pi, "_claude_subscription_auth_ok", lambda *a: (True, ""))
    errors = {"refused": pi._seat_jail.SeatSandboxRefused("grok_tool_surface_unverified"),
              "missing": FileNotFoundError("claude"), "launch": OSError("fixture")}
    def refuse(*a, **k):
        raise errors[failure]
    monkeypatch.setattr(pi, "_seat_command_profile", refuse)
    review, out = tmp_path / "review", tmp_path / "out"
    review.mkdir()
    out.mkdir()
    (review / "review-bundle.md").write_text("fixture")
    (review / "review-instructions.md").write_text("fixture")
    @pi._retained_leg_exec
    def run(leg):
        return pi._exec_claude_tui_leg(review, out, 60, "fixture", env={})
    assert run("claude")[0] != "OK"
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    assert record["exit_code"] is None
