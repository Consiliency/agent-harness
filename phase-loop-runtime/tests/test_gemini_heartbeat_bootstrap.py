"""Gemini bootstrap: public outcomes, immutable launch input and owned lifetime.

New module imports are intentionally inside test bodies/fixtures: the RED base
must collect every node. Synthetic CLIs use synthetic credentials and an explicit
test-only digest. No test invokes an installed model or reads an OAuth payload.
"""
from dataclasses import replace
from hashlib import sha256
import importlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD


def gemini_board():
    return replace(DEFAULT_BOARD, seats=tuple(
        seat for seat in DEFAULT_BOARD.seats if seat.harness == "gemini"
    ))


def test_logical_resolver_admits_gemini_without_probing(monkeypatch):
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("impure resolver"))
    policy = backing.resolve_review_monitoring_policy("heartbeat_only", gemini_board())
    assert policy.effective == "heartbeat_only"
    assert policy.model_deadline_s is None


def test_heartbeat_builder_uses_literal_zero_and_withholds_staged_tree(tmp_path):
    command = panel._brokered_gemini_command(
        model="gemini-3.8-flash-high", deadline_s=900,
        staged_tree=tmp_path, monitoring_policy="heartbeat_only",
    )
    assert command == [
        "agy", "--model", "gemini-3.8-flash-high", "--sandbox", "--mode", "plan",
        "--disable-slash-commands", "--input-format", "stream-json",
        "--output-format", "stream-json", "--print=", "--print-timeout", "0",
    ]


@pytest.mark.parametrize("deadline", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_bounded_builder_cannot_render_a_zero_or_nonfinite_sentinel(deadline):
    with pytest.raises(ValueError):
        panel._brokered_gemini_command(model="gemini-3.8-flash-high", deadline_s=deadline)


def test_no_profile_does_not_change_other_providers_owner_argv(tmp_path):
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "unchanged", 0, threading.Event())
    assert monitor.owned_command(("fixture", "arg")) == [
        "/usr/bin/bwrap", "--die-with-parent", "--unshare-pid",
        "--bind", "/", "/", "--dev", "/dev", "--", "fixture", "arg",
    ]


def _stream(protocol, final="No blocking findings.\nAGREE"):
    return [
        {"event": "result", "conversation_id": "fixture-session",
         "result": {"status": "SUCCESS", "response": response}}
        for response in (*protocol.acknowledgements, final)
    ]


@pytest.mark.parametrize("mutation,reason", [
    ("json", "malformed JSON"), ("event", "malformed stream event"),
    ("tool", "tool or subagent"), ("session", "conversation"),
    ("count", "incomplete ingestion"), ("ack", "chunk acknowledgement"),
    ("final", "terminal response"), ("truncation", "truncation"),
])
def test_stream_rejections_are_fixed_and_never_review_prose(mutation, reason):
    protocol = panel._broker_gemini_stream_protocol("synthetic input")
    rows = _stream(protocol)
    if mutation == "event": rows.insert(0, ["PRIVATE_FIXTURE_SENTINEL"])
    if mutation == "tool":
        rows.insert(0, {"event": "step_update", "step_update": {
            "step_type": "tool", "tool_info": "PRIVATE_FIXTURE_SENTINEL"}})
    if mutation == "session": rows[-1]["conversation_id"] = "another-session"
    if mutation == "count": rows.pop()
    if mutation == "ack": rows[0]["result"]["response"] = "PRIVATE_FIXTURE_SENTINEL"
    if mutation == "final": rows[-1]["result"]["status"] = "ERROR"
    if mutation == "truncation": rows[-1]["result"]["response"] = "<truncated 123 bytes>"
    raw = "\n".join(json.dumps(row) for row in rows)
    if mutation == "json": raw = '{"PRIVATE_FIXTURE_SENTINEL":'
    rc, body, detail, metadata = panel._broker_gemini_stream_result(raw, protocol)
    assert rc != 0 and body == ""
    assert reason in detail
    assert "PRIVATE_FIXTURE_SENTINEL" not in detail
    assert metadata["provider_stream_outcome"] != "accepted"


@pytest.fixture
def fixture_cli(tmp_path, monkeypatch):
    gh = importlib.import_module("phase_loop_runtime.gemini_heartbeat")
    home = tmp_path / "synthetic-home"
    token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text("synthetic-token-only\n")
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    cli = cli_dir / "agy"
    attempts = tmp_path / "attempts"
    observation = tmp_path / "observation.json"
    mode_file = tmp_path / "mode"
    mode_file.write_text("ok")
    # Values are fixture-owned paths, never prompt or credential contents.
    cli.write_text("#!/usr/bin/python3\n" + f'''
import json,os,re,sys,time
from pathlib import Path
mode=Path({str(mode_file)!r}).read_text()
with Path({str(attempts)!r}).open('a') as f: f.write('attempt\\n')
home=Path.home()
config=home/'.gemini/antigravity-cli'
settings=config/'settings.json'
try:
    fd=os.open(settings,os.O_WRONLY)
    os.close(fd)
    settings_readonly=False
except OSError:
    settings_readonly=True
try: settings_value=json.loads(settings.read_text())
except (OSError,ValueError): settings_value=None
fd_targets=[]
for name in os.listdir('/proc/self/fd'):
    try: fd_targets.append(os.readlink('/proc/self/fd/'+name))
    except OSError: pass
Path({str(observation)!r}).write_text(json.dumps({{
 'argv':sys.argv, 'home':str(home), 'settings_readonly':settings_readonly,
 'settings':settings_value, 'mode':mode,
 'caps':next(x.split()[1] for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('CapBnd:')),
 'pid':int(Path('/proc/self/stat').read_text().split()[0]),
 'namespace':os.readlink('/proc/self/ns/pid'), 'fd_targets':fd_targets,
 'random_available':len(os.urandom(8))==8
}}))
if mode=='cancel':
    child=os.fork()
    if child==0:
        os.setsid()
        ready=Path({str(tmp_path / 'detached')!r})
        ready.with_suffix('.tmp').write_text(Path('/proc/self/stat').read_text().split()[0])
        os.replace(ready.with_suffix('.tmp'),ready)
        while True: time.sleep(.1)
    while True: time.sleep(.1)
if mode=='wait':
    while not Path({str(tmp_path / 'release')!r}).exists(): time.sleep(.01)
if mode=='refresh':
    credential=config/'antigravity-oauth-token'
    credential.write_text('synthetic-refreshed\\n')
    replacement=config/'replacement'
    replacement.write_text('synthetic-private-replacement\\n')
    os.replace(replacement,credential)
events=[json.loads(line) for line in sys.stdin]
def emit(response,status='SUCCESS',session='fixture-session'):
    print(json.dumps({{'event':'result','conversation_id':session,
      'result':{{'status':status,'response':response}}}}),flush=True)
if mode=='native':
    emit('PRIVATE_FIXTURE_SENTINEL')
    print('connection reset PRIVATE_FIXTURE_SENTINEL',file=sys.stderr)
    raise SystemExit(7)
if mode=='native-stdout':
    observed=json.loads(Path({str(observation)!r}).read_text())
    observed['native_failure_mode_entered']=True
    Path({str(observation)!r}).write_text(json.dumps(observed))
    print('connection reset PRIVATE_FIXTURE_SENTINEL')
    raise SystemExit(7)
if mode=='native-timeout':
    print('Error: timeout waiting for response PRIVATE_FIXTURE_SENTINEL',file=sys.stderr)
    raise SystemExit(1)
if mode=='malformed':
    print('{{PRIVATE_FIXTURE_SENTINEL',flush=True)
    raise SystemExit(0)
if mode=='event': print(json.dumps(['PRIVATE_FIXTURE_SENTINEL']))
for e in events[:-1]:
    match=re.search(r'^Reply with exactly: (.+)$',e['message']['content'],re.M)
    emit('wrong ack' if mode=='ack' else match.group(1))
if mode=='count': raise SystemExit(0)
if mode=='tool':
    print(json.dumps({{'event':'step_update','step_update':{{'step_type':'tool','tool_info':'PRIVATE_FIXTURE_SENTINEL'}}}}))
if mode=='denied-empty':
    print('auto-denied tool permission PRIVATE_FIXTURE_SENTINEL',file=sys.stderr)
emit('' if mode in ('empty','denied-empty') else '<truncated 123 bytes>' if mode=='truncation' else 'No blocking findings.\\nAGREE',
     status='ERROR' if mode=='final' else 'SUCCESS',
     session='another-session' if mode=='session' else 'fixture-session')
''')
    cli.chmod(0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(cli_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    monkeypatch.setattr(gh, "QUALIFIED_IMAGE_SHA256", sha256(cli.read_bytes()).hexdigest())
    return SimpleNamespace(module=gh, path=cli, attempts=attempts, observation=observation,
                           mode=mode_file, token=token, home=home)


@pytest.mark.parametrize("missing", ["image", "memfd", "pidfd", "pidfd_enosys"])
def test_missing_capability_refuses_whole_board_before_effects(fixture_cli, monkeypatch, missing, tmp_path, capsys):
    gh = fixture_cli.module
    if missing == "image": monkeypatch.setattr(gh, "QUALIFIED_IMAGE_SHA256", "0" * 64)
    if missing == "memfd": monkeypatch.delattr(gh.os, "memfd_create", raising=False)
    if missing == "pidfd": monkeypatch.delattr(gh.os, "pidfd_open", raising=False)
    if missing == "pidfd_enosys":
        import errno
        def unsupported(*args, **kwargs): raise OSError(errno.ENOSYS, "synthetic unsupported kernel")
        monkeypatch.setattr(gh.os, "pidfd_open", unsupported)
    monkeypatch.setattr(panel, "default_matrix", lambda **kw: pytest.fail("availability effect"))
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", lambda *a, **kw: pytest.fail("auth effect"))
    result = panel.invoke_board(DEFAULT_BOARD, "input", monitoring_policy="heartbeat_only")
    assert len(result.legs) == 4
    assert all(leg.status == "UNAVAILABLE" and "gemini" in leg.detail for leg in result.legs)
    assert all(leg.review_monitoring["terminal_reason"] == "policy_refusal" for leg in result.legs)
    assert not fixture_cli.attempts.exists()
    from phase_loop_runtime import cli
    from phase_loop_runtime.advisor_board import composition
    monkeypatch.setattr(composition, "compose_review_board", lambda: pytest.fail("CLI composition effect"))
    capsys.readouterr()
    rc = cli._advisor_board_command(args=SimpleNamespace(
        artifact=str(tmp_path / "must-not-read"), monitoring_policy="heartbeat_only", json=True,
    ))
    assert rc == 2
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "UNAVAILABLE"
    assert record["monitoring"]["terminal_reason"] == "policy_refusal"
    assert "gemini" in record["monitoring"]["diagnostic"]


@pytest.mark.parametrize("mode,status,detail", [
    ("ok", "OK", None), ("empty", "EMPTY", "without review text"),
    ("malformed", "ERROR", "malformed JSON"), ("ack", "ERROR", "acknowledgement"),
    ("tool", "ERROR", "tool or subagent"), ("native", "ERROR", "native exit"),
    ("native-stdout", "ERROR", "native exit"),
    ("native-timeout", "ERROR", "native timeout"),
    ("denied-empty", "ERROR", "tool permission"),
    ("event", "ERROR", "malformed stream event"),
    ("session", "ERROR", "conversation"), ("count", "ERROR", "incomplete ingestion"),
    ("final", "ERROR", "terminal response"), ("truncation", "ERROR", "truncation"),
])
def test_real_board_preserves_diagnostics_without_retries(fixture_cli, tmp_path, mode, status, detail):
    fixture_cli.mode.write_text(mode)
    result = panel.invoke_board(
        gemini_board(), "synthetic review input", monitoring_policy="heartbeat_only",
        stream_dir=tmp_path / "records", gateway_available=False,
    )
    leg, = result.legs
    assert leg.status == status, (leg.status, leg.detail)
    assert fixture_cli.attempts.read_text().splitlines() == ["attempt"]
    if detail is None:
        assert leg.detail is None and leg.text.endswith("AGREE")
    else:
        assert leg.text == "" and detail in leg.detail
        assert "PRIVATE_FIXTURE_SENTINEL" not in leg.detail
    evidence = leg.harden_isolation_evidence
    assert evidence["operation_deadline_s"] is None
    assert evidence["sandbox_network_filtered"] is True
    assert evidence["provider_agy_home_cleanup_verified"] is True
    assert evidence["provider_isolation_profile"] == "agy_memfd_home_deny_all_v1"
    assert set(("deny-all-actions", "no-add-dir", "no-dangerous-permissions")) <= set(evidence["provider_no_tool_controls"])
    assert evidence["provider_prompt_sha256"] == evidence["provider_input_sha256"]
    assert len(evidence["provider_transport_sha256"]) == 64
    assert all(evidence[key] for key in (
        "child_quiescent", "broker_thread_quiescent", "provider_adapter_quiescent",
        "cleanup_root_removed", "host_secret_probe_removed",
    ))
    observed = json.loads(fixture_cli.observation.read_text())
    assert observed["argv"][0] == "/dev/phase-loop-agy/agy"
    assert observed["argv"][observed["argv"].index("--print-timeout") + 1] == "0"
    assert "--add-dir" not in observed["argv"] and "plan" in observed["argv"]
    assert observed["home"] == "/dev/phase-loop-agy"
    assert observed["settings_readonly"] and observed["random_available"]
    assert observed["settings"]["permissions"]["deny"] == list(panel._BROKER_AGY_DENY_ACTIONS)
    assert int(observed["caps"], 16) == 0
    assert not any("memfd:" in target for target in observed["fd_targets"])
    assert not Path(observed["home"]).exists()
    assert fixture_cli.token.read_text() == "synthetic-token-only\n"
    verdicts = [json.loads(p.read_text()) for p in (tmp_path / "records").glob("*.verdict.json")]
    assert len(verdicts) == 1
    assert verdicts[0]["detail"] == leg.detail
    assert verdicts[0]["text"] == leg.text


def test_pre_cancelled_public_gemini_never_launches(fixture_cli, tmp_path):
    cancel = threading.Event()
    cancel.set()
    result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                cancel_event=cancel, stream_dir=tmp_path / "records")
    assert result.legs[0].status == "UNAVAILABLE"
    assert result.legs[0].detail == "review_operation_cancelled"
    assert not fixture_cli.attempts.exists()
    verdict, = [json.loads(p.read_text()) for p in (tmp_path / "records").glob("*.verdict.json")]
    assert verdict["status"] == "UNAVAILABLE" and verdict["text"] == ""
    assert verdict["detail"] == "review_operation_cancelled"


def test_real_broker_cancel_reclaims_private_profile_and_detached_child(fixture_cli, tmp_path):
    fixture_cli.mode.write_text("cancel")
    cancel = threading.Event()
    detached = tmp_path / "detached"
    control_errors = []
    def cancel_when_launched():
        try:
            until = time.monotonic() + 30  # synthetic admission only
            while not detached.exists():
                if time.monotonic() >= until: raise AssertionError("fixture did not launch")
                time.sleep(.02)
        except Exception as exc:
            control_errors.append(exc)
        finally:
            cancel.set()
    controller = threading.Thread(target=cancel_when_launched)
    controller.start()
    try:
        result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                    cancel_event=cancel, stream_dir=tmp_path / "records")
    finally:
        cancel.set()
        controller.join(35)
    assert not control_errors
    leg, = result.legs
    assert leg.status == "UNAVAILABLE" and leg.text == ""
    assert leg.detail == "review_operation_cancelled"
    assert leg.harden_isolation_evidence["provider_agy_home_cleanup_verified"]
    assert not Path(f"/proc/{int(detached.read_text())}").exists()
    assert fixture_cli.attempts.read_text().splitlines() == ["attempt"]
    verdict, = [json.loads(p.read_text()) for p in (tmp_path / "records").glob("*.verdict.json")]
    assert verdict["status"] == "UNAVAILABLE" and verdict["text"] == ""
    assert verdict["detail"] == "review_operation_cancelled"


def _profile(fixture_cli):
    return fixture_cli.module.owned_profile(
        panel._broker_subscription_env(),
        settings_bytes=b'{"permissions":{"deny":["command(*)"]}}\n',
        credential_path=fixture_cli.token,
    )


def _run_profile(profile, tmp_path, cancel=None):
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "profile", 0,
                                   cancel if cancel is not None else threading.Event())
    return panel._run_leg_with_liveness(
        [profile.executable], cwd=tmp_path, env=profile.env,
        deadline_s=.01, stall_threshold_s=.01, review_monitor=monitor,
        gemini_profile=profile,
    )


@pytest.mark.parametrize("change", ["replace", "overwrite"])
def test_sealed_image_survives_source_replacement_and_inplace_change(fixture_cli, tmp_path, change):
    with _profile(fixture_cli) as profile:
        replacement = b"#!/bin/sh\necho 'WRONG IMAGE'\nexit 9\n"
        if change == "replace":
            swapped = fixture_cli.path.with_suffix(".new")
            swapped.write_bytes(replacement)
            swapped.chmod(0o700)
            os.replace(swapped, fixture_cli.path)
        else:
            fixture_cli.path.write_bytes(replacement)
        result = _run_profile(profile, tmp_path)
        assert result.returncode == 0 and "WRONG IMAGE" not in result.stdout
        assert fixture_cli.attempts.read_text().splitlines() == ["attempt"]


def test_snapshot_rechecks_bytes_after_successful_capability_check(fixture_cli):
    gh = fixture_cli.module
    gh.require_capability(panel._broker_subscription_env())
    fixture_cli.path.write_text("#!/bin/sh\nexit 0\n")
    with pytest.raises(ValueError, match="gemini"):
        with _profile(fixture_cli):
            pytest.fail("changed image reached an owned profile")
    assert not fixture_cli.attempts.exists()


def test_capability_checks_leave_other_policy_routes_unaffected(fixture_cli, monkeypatch):
    monkeypatch.setattr(fixture_cli.module, "require_capability",
                        lambda *a, **kw: pytest.fail("unrelated capability probe"))
    panel._preflight_gemini_heartbeat(gemini_board(), "bounded")
    others = replace(DEFAULT_BOARD, seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness != "gemini"))
    panel._preflight_gemini_heartbeat(others, "heartbeat_only")


@pytest.mark.parametrize("route", ["bounded_gemini", "heartbeat_codex"])
@pytest.mark.parametrize("missing", ["image", "memfd", "pidfd"])
def test_public_other_routes_complete_without_gemini_capability(fixture_cli, tmp_path, monkeypatch, route, missing):
    gh = fixture_cli.module
    if missing == "image": monkeypatch.setattr(gh, "QUALIFIED_IMAGE_SHA256", "0" * 64)
    if missing == "memfd": monkeypatch.delattr(gh.os, "memfd_create", raising=False)
    if missing == "pidfd": monkeypatch.delattr(gh.os, "pidfd_open", raising=False)
    board, policy = gemini_board(), "bounded"
    if route == "heartbeat_codex":
        cli = fixture_cli.path.with_name("codex")
        cli.write_text(
            "#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n"
            "if 'exec' not in sys.argv: raise SystemExit(0)\n"
            "sys.stdin.read()\n"
            "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('No blocking findings.\\nAGREE')\n"
        )
        cli.chmod(0o700)
        board = replace(DEFAULT_BOARD, seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness == "codex"))
        policy = "heartbeat_only"
    result = panel.invoke_board(board, "synthetic other-route control", monitoring_policy=policy,
                                stream_dir=tmp_path / "records", gateway_available=False)
    leg, = result.legs
    assert leg.status == "OK" and leg.text.endswith("AGREE"), (leg.status, leg.detail)
    if route == "bounded_gemini":
        observed = json.loads(fixture_cli.observation.read_text())
        assert observed["settings"] and observed["mode"] == "ok"


def test_bounded_retry_classifies_raw_stdout_before_discarding_prose(fixture_cli, tmp_path):
    fixture_cli.mode.write_text("native-stdout")
    result = panel.invoke_board(gemini_board(), "synthetic bounded retry", monitoring_policy="bounded",
                                stream_dir=tmp_path / "records", gateway_available=False)
    leg, = result.legs
    assert fixture_cli.attempts.read_text().splitlines() == ["attempt", "attempt"]
    observed = json.loads(fixture_cli.observation.read_text())
    assert observed["settings"] and observed["native_failure_mode_entered"] is True
    assert leg.status == "ERROR" and leg.text == ""
    assert "native exit" in leg.detail and "PRIVATE_FIXTURE_SENTINEL" not in leg.detail


def test_cli_preserves_requested_membership_and_policy_after_capability_admission(fixture_cli, tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli
    from phase_loop_runtime.advisor_board import composition
    artifact = tmp_path / "input.md"
    artifact.write_text("synthetic CLI wiring control")
    monkeypatch.setattr(composition, "compose_review_board", lambda: pytest.fail("availability backfill"))
    observed = []
    def capture(board, text, **kwargs):
        observed.append(board)
        assert board.seats == DEFAULT_BOARD.seats
        assert kwargs["monitoring_policy"] == "heartbeat_only"
        assert kwargs["review_authorization"].monitoring_policy == "heartbeat_only"
        return panel.PanelResult(tuple(panel.PanelLegResult(
            leg=s.harness, seat_key=s.seat_key, status="OK", text="AGREE",
        ) for s in board.seats))
    monkeypatch.setattr(panel, "invoke_board", capture)
    rc = cli._advisor_board_command(args=SimpleNamespace(
        artifact=str(artifact), monitoring_policy="heartbeat_only", json=True,
    ))
    assert rc == 0 and len(observed) == 1
    assert json.loads(capsys.readouterr().out)["requested_seats"] == 4
    assert not fixture_cli.attempts.exists()


def test_default_spawn_rechecks_capability_before_scratch_effects(fixture_cli, tmp_path, monkeypatch):
    authorization = backing.prepare_review_isolation_authorization(
        gemini_board(), "input", mode="review", monitoring_policy="heartbeat_only",
        canonical_repo_authority=Path(__file__).resolve().parents[2],
    )
    monkeypatch.setattr(fixture_cli.module, "QUALIFIED_IMAGE_SHA256", "0" * 64)
    monkeypatch.setattr(panel, "_gc_stale_panel_scratch", lambda: pytest.fail("scratch effect"))
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "direct", 0, threading.Event())
    result = panel._default_spawn("gemini", "input", review_monitor=monitor,
                                  review_authorization=authorization)
    assert result[0] == "UNAVAILABLE" and result[1] == ""
    assert "gemini" in result[2] and "capability" in result[2]


def test_bwrap_gate_eof_really_releases_a_synthetic_command(tmp_path):
    marker = tmp_path / "executed"
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    proc = panel.launch_provider([
        "/usr/bin/bwrap", "--die-with-parent", "--unshare-pid", "--bind", "/", "/",
        "--dev", "/dev", "--block-fd", str(read_fd), "--", "/usr/bin/python3", "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).touch()", str(marker),
    ], pass_fds=(read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    os.close(read_fd)
    try:
        time.sleep(.05)
        assert not marker.exists()
        os.close(write_fd)
        write_fd = -1
        _, error = proc.communicate(timeout=5)
        assert proc.returncode == 0, error
        assert marker.exists(), "EOF is a release, so abort must reap before closing the gate"
    finally:
        if proc.poll() is None: proc.kill()
        proc.wait(5)
        if write_fd >= 0: os.close(write_fd)


def test_profile_refresh_preserves_target_and_discards_private_replacement(fixture_cli, tmp_path):
    fixture_cli.mode.write_text("refresh")
    with _profile(fixture_cli) as profile:
        assert _run_profile(profile, tmp_path).returncode == 0
    assert fixture_cli.token.read_text() == "synthetic-refreshed\n"
    assert not Path("/dev/phase-loop-agy").exists()


def test_gemini_exec_wait_crosses_old_clocks_with_its_monitor(fixture_cli, tmp_path, monkeypatch):
    fixture_cli.mode.write_text("wait")
    elapsed = 0
    clock = SimpleNamespace(monotonic=lambda: time.monotonic() + elapsed,
                            monotonic_ns=lambda: time.monotonic_ns() + int(elapsed * 1_000_000_000),
                            time=time.time, sleep=time.sleep)
    monkeypatch.setattr(panel, "time", clock)
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .02)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "clock", 0, threading.Event())
    observe = monitor.observe
    advanced_observations = []
    def release_after_admission(*args, **kwargs):
        nonlocal elapsed
        if fixture_cli.observation.exists():
            if not elapsed:
                elapsed = 4 * 1800
            advanced_observations.append(elapsed)
            if len(advanced_observations) <= 2:
                assert not (tmp_path / "release").exists()
            elif len(advanced_observations) == 3:
                (tmp_path / "release").touch()
        observe(*args, **kwargs)
    monkeypatch.setattr(monitor, "observe", release_after_admission)
    output = tmp_path / "output"
    output.mkdir()
    watchdog_fired = threading.Event()
    def stop_broken_fixture():
        watchdog_fired.set()
        (tmp_path / "release").touch()
        monitor.cancel.set()
    watchdog = threading.Timer(30, stop_broken_fixture)  # synthetic CLI only, never a model
    watchdog.start()
    try:
        rc, body, detail = panel._exec_leg(
            "gemini", tmp_path, output, timeout_s=1, deadline_s=1,
            model=backing.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["gemini"],
            broker_prompt="synthetic clock review", broker_evidence={}, review_monitor=monitor,
        )
    finally:
        watchdog.cancel()
        watchdog.join()
    assert not watchdog_fired.is_set(), "synthetic fixture never observed/released"
    assert rc == 0 and body.endswith("AGREE"), detail
    assert elapsed == 7200, "Gemini did not propagate the operation monitor"
    assert len(advanced_observations) >= 3, "fixture never remained blocked across advanced-clock polls"
    assert fixture_cli.attempts.read_text().splitlines() == ["attempt"]


def test_profile_fds_are_sealed_closed_and_not_inherited_by_provider(fixture_cli, tmp_path, monkeypatch):
    import fcntl
    identities = {}
    with _profile(fixture_cli) as profile:
        passed = tuple(profile.pass_fds)
        assert len(passed) == 4  # image, settings, info write, gate read
        for fd in profile.owned_fds:
            st = os.fstat(fd)
            identities[fd] = (st.st_dev, st.st_ino)
        original_pin = profile.pin_identity
        def retain_admitted_fds(*args, **kwargs):
            value = original_pin(*args, **kwargs)
            for fd in profile.owned_fds:
                st = os.fstat(fd)
                identities[fd] = (st.st_dev, st.st_ino)
            return value
        monkeypatch.setattr(profile, "pin_identity", retain_admitted_fds)
        sealed = [fd for fd in passed if "memfd:" in os.readlink(f"/proc/self/fd/{fd}")]
        assert len(sealed) == 2
        for fd in sealed:
            with pytest.raises(OSError): os.write(fd, b"change")
            assert fcntl.fcntl(fd, fcntl.F_GET_SEALS) & fcntl.F_SEAL_WRITE
        result = _run_profile(profile, tmp_path)
        assert result.returncode == 0
        observed = json.loads(fixture_cli.observation.read_text())
        for _, inode in identities.values():
            assert f"pipe:[{inode}]" not in observed["fd_targets"]
        assert not any("memfd:" in value for value in observed["fd_targets"])
    for fd, identity in identities.items():
        try: st = os.fstat(fd)
        except OSError: continue
        assert (st.st_dev, st.st_ino) != identity, "profile leaked an owned fd"


@pytest.mark.parametrize("during_pin", ["failure", "cancel"])
def test_admission_abort_kills_before_closing_gate_and_never_executes(
    fixture_cli, tmp_path, monkeypatch, during_pin,
):
    cancel = threading.Event()
    original_launch = panel.launch_provider
    original_close = os.close
    launched = []
    gate_closes = []
    gate_violations = []
    def retain_launch(*args, **kwargs):
        proc = original_launch(*args, **kwargs)
        launched.append(proc)
        return proc
    monkeypatch.setattr(panel, "launch_provider", retain_launch)
    with _profile(fixture_cli) as profile:
        gate_fd = profile.gate_write_fd
        def check_gate_close(fd):
            if fd == gate_fd:
                gate_closes.append(fd)
                if not launched or not all(proc.poll() is not None and not panel._process_group_exists(proc.pid)
                                           for proc in launched):
                    gate_violations.append("gate EOF preceded abort/reap")
            return original_close(fd)
        monkeypatch.setattr(fixture_cli.module.os, "close", check_gate_close)
        original_pin = profile.pin_identity
        def abort_pin(*args, **kwargs):
            if during_pin == "failure": raise ValueError("synthetic identity failure")
            value = original_pin(*args, **kwargs)
            cancel.set()
            return value
        monkeypatch.setattr(profile, "pin_identity", abort_pin)
        with pytest.raises((ValueError, panel._ReviewOperationCancelled)):
            _run_profile(profile, tmp_path, cancel)
    assert gate_closes == [gate_fd], "gate close was not observed exactly once"
    assert not gate_violations, gate_violations
    assert not fixture_cli.attempts.exists(), "provider exec preceded successful admission"


def test_quiescence_failure_cannot_become_wire_ok_or_a_vote(fixture_cli, tmp_path, monkeypatch):
    gh = fixture_cli.module
    def unverified(*args, **kwargs):
        raise gh.GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified")
    monkeypatch.setattr(gh.GeminiHeartbeatProfile, "verify_quiescence", unverified)
    published = []
    try:
        result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                    stream_dir=tmp_path / "records", on_leg_complete=published.append)
    except panel.ProviderProcessGroupQuiescenceError:
        pass
    else:
        assert all(not leg.usable and not leg.text for leg in result.legs)
    assert all(not leg.usable and leg.status != "OK" for leg in published)
    for path in (tmp_path / "records").glob("*.verdict.json"):
        record = json.loads(path.read_text())
        assert record["status"] != "OK" and not record["usable"] and not record["text"]
    assert fixture_cli.attempts.read_text().splitlines() == ["attempt"]


@pytest.mark.parametrize("observation", ["init_alive", "member_alive"])
def test_leader_exit_alone_is_not_a_quiescence_proof(fixture_cli, tmp_path, monkeypatch, observation):
    gh = fixture_cli.module
    with _profile(fixture_cli) as profile:
        monkeypatch.setattr(profile, "observe_quiescence", lambda: {
            "init_exited": observation != "init_alive",
            "live_members": [123456789] if observation == "member_alive" else [],
            "unreadable_entries": 0,
        })
        verify = profile.verify_quiescence
        monkeypatch.setattr(profile, "verify_quiescence", lambda: verify(grace_s=.01))
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError, match="quiescence_unverified"):
            _run_profile(profile, tmp_path)


def test_identity_pin_precedes_gate_release_and_stdin(fixture_cli, tmp_path, monkeypatch):
    with _profile(fixture_cli) as profile:
        original_pin = profile.pin_identity
        original_write = os.write
        original_close = os.close
        gate_fd = profile.gate_write_fd
        pinned = []
        def check_release(fd, data):
            if fd == gate_fd:
                assert pinned == [True], "gate release preceded identity pin"
            return original_write(fd, data)
        def check_close(fd):
            if fd == gate_fd:
                assert pinned == [True], "gate EOF preceded identity pin"
            return original_close(fd)
        def check_gate(*args, **kwargs):
            time.sleep(.05)
            assert not fixture_cli.attempts.exists(), "gate opened before identity pin"
            value = original_pin(*args, **kwargs)
            pinned.append(True)
            return value
        monkeypatch.setattr(profile, "pin_identity", check_gate)
        monkeypatch.setattr(fixture_cli.module.os, "write", check_release)
        monkeypatch.setattr(fixture_cli.module.os, "close", check_close)
        assert _run_profile(profile, tmp_path).returncode == 0
        assert pinned == [True]


@pytest.mark.parametrize("bad_pid", ["self", "missing"])
def test_identity_pin_rejects_host_namespace_or_missing_process(fixture_cli, bad_pid):
    with _profile(fixture_cli) as profile:
        pid = os.getpid() if bad_pid == "self" else 2 ** 30
        with pytest.raises(ValueError, match="admission_handshake_failed"):
            profile.pin_identity({"child-pid": pid}, SimpleNamespace(pid=os.getpid()))
    assert not fixture_cli.attempts.exists()


@pytest.mark.parametrize("info", [b'', b'{"child-pid":'])
def test_partial_admission_info_cannot_block_past_local_admission_bound(fixture_cli, info):
    with _profile(fixture_cli) as profile:
        # This helper never invokes a model. It holds the info pipe open while
        # the parent must enforce the finite pre-execution admission window.
        proc = panel.launch_provider([
            "/usr/bin/python3", "-c",
            "import os,sys,time; os.write(int(sys.argv[1]),bytes.fromhex(sys.argv[2])); time.sleep(30)",
            str(profile.info_write_fd), info.hex(),
        ], pass_fds=(profile.info_write_fd,), start_new_session=True)
        try:
            start = time.monotonic()
            with pytest.raises(ValueError, match="admission_handshake_failed"):
                profile.admit(proc, threading.Event(), admission_s=.05)
            assert time.monotonic() - start < 2
            assert not fixture_cli.attempts.exists()
        finally:
            proc.kill()
            proc.wait(5)


def test_owner_loss_through_real_broker_reclaims_namespace(fixture_cli, tmp_path):
    fixture_cli.mode.write_text("cancel")
    detached = tmp_path / "detached"
    worker_code = f'''
from dataclasses import replace
from pathlib import Path
from phase_loop_runtime import panel_invoker as panel, gemini_heartbeat as gh
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
gh.QUALIFIED_IMAGE_SHA256={fixture_cli.module.QUALIFIED_IMAGE_SHA256!r}
board=replace(DEFAULT_BOARD,seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness=='gemini'))
panel.invoke_board(board,'synthetic owner-loss fixture',monitoring_policy='heartbeat_only',stream_dir=Path({str(tmp_path / 'records')!r}))
'''
    worker = panel.launch_provider([sys.executable, "-c", worker_code],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
    pidfds = []
    try:
        until = time.monotonic() + 30
        while not detached.exists():
            assert worker.poll() is None, f"fixture worker exited {worker.returncode}"
            assert time.monotonic() < until, "synthetic provider never admitted"
            time.sleep(.02)
        info = json.loads(fixture_cli.observation.read_text())
        for pid in (info["pid"], int(detached.read_text())):
            pidfds.append(os.pidfd_open(pid))
        namespace = os.stat(f"/proc/{info['pid']}/ns/pid")
        assert namespace.st_ino != os.stat("/proc/self/ns/pid").st_ino
        worker.kill()
        worker.wait(10)
        until = time.monotonic() + 5
        import select
        while any(not select.select([fd], [], [], 0)[0] for fd in pidfds):
            assert time.monotonic() < until, "fixture survived abrupt owner loss"
            time.sleep(.02)
        assert not Path(info["home"]).exists()
        assert fixture_cli.token.read_text() == "synthetic-token-only\n"
        assert fixture_cli.attempts.read_text().splitlines() == ["attempt"]
    finally:
        if worker.poll() is None: worker.kill()
        worker.wait(10)
        for fd in pidfds:
            try: signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError: pass
            os.close(fd)


def _qualification_validator():
    path = Path(__file__).resolve().parents[1] / "scripts/qualify_gemini_heartbeat.py"
    spec = importlib.util.spec_from_file_location("gemini_qualification_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_records


def _digest_record(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _qualification_profile():
    return {"id": "agy_memfd_home_deny_all_v1", "image_sha256": "c" * 64,
            "settings_sha256": "3" * 64, "home": "/dev/phase-loop-agy"}


def _qualification_record(operation):
    """Synthetic format/integrity fixture; never proof of a real qualification."""
    argv = ["/dev/phase-loop-agy/agy", "--model", "gemini-3.8-flash-high",
            "--sandbox", "--mode", "plan", "--disable-slash-commands",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--print=", "--print-timeout", "0"]
    result = {"status": "OK", "text": "No blocking findings.\nAGREE", "detail": None}
    monitor = {"schema": "review_monitoring.v1", "invocation": "fixture-operation",
               "requested_policy": "heartbeat_only", "effective_policy": "heartbeat_only",
               "model_deadline_s": None, "silence_deadline_s": None,
               "terminal_reason": "completed"}
    broker = {
        "schema": "parent_unix_broker_v1", "operation_deadline_s": None,
        "stage_bundle_sha256": "e" * 64, "stage_instructions_sha256": "f" * 64,
        "leg_authorization_issued_monotonic_ns": 100,
        "leg_authorization_expires_monotonic_ns": 10000000100,
        "monitoring": {"schema": "review_monitoring.v1", "requested_policy": "heartbeat_only",
                       "effective_policy": "heartbeat_only", "operation_deadline_s": None,
                       "authorization_expiry_scope": "admission_only",
                       "admission_expires_monotonic_ns": 10000000100},
        "provider_argv_shape": argv + ["<STDIN_SEALED_INLINE_PROMPT>"],
        "provider_argv_sha256": sha256("\0".join(argv + ["<STDIN_SEALED_INLINE_PROMPT>"]).encode()).hexdigest(),
        "provider_isolation_profile": "agy_memfd_home_deny_all_v1",
        "provider_profile_sha256": _digest_record(_qualification_profile()),
        "provider_agy_settings_sha256": "3" * 64,
        "provider_input_sha256": "1" * 64, "provider_prompt_sha256": "1" * 64,
        "provider_transport_sha256": "2" * 64,
        "provider_response_status": "OK",
        "provider_response_sha256": sha256(result["text"].encode()).hexdigest(),
        "provider_stream_outcome": "accepted", "provider_stream_acknowledgements_verified": True,
        "provider_stream_final_no_truncation": True, "provider_agy_home_cleanup_verified": True,
        "sandbox_network_filtered": True, "child_quiescent": True,
        "broker_thread_quiescent": True, "provider_adapter_quiescent": True,
        "cleanup_root_removed": True, "host_secret_probe_removed": True,
    }
    observer = {
        "invocation": "fixture-operation", "argv": argv, "image_sha256": "c" * 64,
        "profile_sha256": _digest_record(_qualification_profile()),
        "settings_sha256": "3" * 64,
        "image_readonly": True, "home_removed": True, "init_exited": True,
        "live_namespace_members": [], "owned_fds_closed": True,
        "sandbox_network_filtered": True, "network_rules_verified": True,
        "init_pid": 100002, "init_start": "2", "pid_namespace_inode": 12345,
        "helpers": [{"pid": 100003, "start": "3", "executable_sha256": "c" * 64}],
        "kill_event": None,
    }
    if operation == "cancel":
        result = {"status": "UNAVAILABLE", "text": "", "detail": "review_operation_cancelled"}
        monitor["terminal_reason"] = "user_cancel"
        broker["provider_cancel_requested"] = True
        # Cancellation retains evidence but raises before a wire response returns.
        for key in ("provider_response_status", "provider_response_sha256",
                    "provider_stream_outcome", "provider_stream_acknowledgements_verified",
                    "provider_stream_final_no_truncation"):
            broker.pop(key)
    if operation == "owner-loss":
        broker = None
        result = None
        monitor["terminal_reason"] = None
        observer["kill_event"] = {"target": "invoker", "pid": 100001, "start": "1", "signal": 9}
    record = {
        "schema": "gemini_heartbeat_qualification.v1", "operation": operation,
        "invocation": "fixture-operation", "source_sha256": {"panel_invoker.py": "a" * 64},
        "image_sha256": "c" * 64, "help_sha256": "d" * 64,
        "profile": _qualification_profile(), "profile_sha256": _digest_record(_qualification_profile()),
        "request": {"artifact_sha256": "e" * 64, "instructions_sha256": "f" * 64,
                    "provider_input_sha256": "1" * 64, "provider_transport_sha256": "2" * 64},
        "monitoring": monitor, "broker": broker, "observer": observer, "result": result,
    }
    _rebind_record(record)
    return record


def _rebind_record(record):
    record["record_sha256"] = {name: _digest_record(record[name])
                               for name in ("monitoring", "broker", "observer", "result")}


def _validate_record(record):
    return _qualification_validator()(
        record, expected_source_sha256={"panel_invoker.py": "a" * 64},
        expected_image_sha256="c" * 64, expected_help_sha256="d" * 64,
        expected_profile_sha256=_digest_record(_qualification_profile()),
    )


@pytest.mark.parametrize("operation", ["completion", "cancel", "owner-loss"])
def test_qualification_validator_accepts_the_distinct_record_sets(operation):
    _validate_record(_qualification_record(operation))


@pytest.mark.parametrize("mutation", [
    "changed_image", "changed_source", "swapped_monitor",
    "finite_deadline", "finite_model_deadline", "finite_silence_deadline",
    "bounded_zero", "missing_expiry", "session_mismatch",
    "failed_cleanup", "finite_argv", "missing_filter", "response_mismatch",
    "wrong_input", "unreadable_helper", "missing_profile", "unknown_profile",
    "changed_profile", "missing_transport", "changed_transport", "changed_prompt",
    "changed_settings", "json_argv_digest", "consistent_finite_argv",
])
def test_qualification_validator_rejects_cross_record_and_policy_mutants(mutation):
    record = _qualification_record("completion")
    if mutation == "changed_image": record["observer"]["image_sha256"] = "0" * 64
    if mutation == "changed_source": record["source_sha256"]["panel_invoker.py"] = "0" * 64
    if mutation == "swapped_monitor": record["monitoring"]["invocation"] = "another-operation"
    if mutation == "finite_deadline": record["broker"]["operation_deadline_s"] = 900
    if mutation == "finite_model_deadline": record["monitoring"]["model_deadline_s"] = 900
    if mutation == "finite_silence_deadline": record["monitoring"]["silence_deadline_s"] = 900
    if mutation == "bounded_zero": record["monitoring"]["effective_policy"] = "bounded"
    if mutation == "missing_expiry": record["broker"]["leg_authorization_expires_monotonic_ns"] = None
    if mutation == "session_mismatch": record["broker"]["provider_stream_acknowledgements_verified"] = False
    if mutation == "failed_cleanup": record["observer"]["live_namespace_members"] = [100003]
    if mutation == "finite_argv": record["observer"]["argv"][-1] = "900s"
    if mutation == "missing_filter": record["observer"]["network_rules_verified"] = False
    if mutation == "response_mismatch": record["broker"]["provider_response_sha256"] = "0" * 64
    if mutation == "wrong_input": record["broker"]["stage_bundle_sha256"] = "0" * 64
    if mutation == "unreadable_helper": record["observer"]["helpers"][0]["executable_sha256"] = None
    if mutation == "missing_profile": record.pop("profile_sha256")
    if mutation == "unknown_profile": record["broker"]["provider_isolation_profile"] = None
    if mutation == "changed_profile": record["observer"]["profile_sha256"] = "0" * 64
    if mutation == "missing_transport": record["broker"].pop("provider_transport_sha256")
    if mutation == "changed_transport": record["broker"]["provider_transport_sha256"] = "0" * 64
    if mutation == "changed_prompt": record["broker"]["provider_prompt_sha256"] = "0" * 64
    if mutation == "changed_settings": record["observer"]["settings_sha256"] = "0" * 64
    if mutation == "json_argv_digest": record["broker"]["provider_argv_sha256"] = _digest_record(record["broker"]["provider_argv_shape"])
    if mutation == "consistent_finite_argv":
        record["observer"]["argv"][-1] = "900s"
        record["broker"]["provider_argv_shape"][-2] = "900s"
        record["broker"]["provider_argv_sha256"] = sha256("\0".join(record["broker"]["provider_argv_shape"]).encode()).hexdigest()
    _rebind_record(record)
    with pytest.raises(ValueError): _validate_record(record)


def test_monitor_record_digest_is_independent_of_terminal_semantics():
    record = _qualification_record("completion")
    record["monitoring"]["last_genuine_progress_age_s"] = 1.0
    record["monitoring"]["observation_state"] = "progress_unobserved"
    _rebind_record(record)
    _validate_record(record)
    # Both observations are valid completed snapshots. Only the stale digest
    # must distinguish this rejection from the rebound acceptance below.
    record["monitoring"]["last_genuine_progress_age_s"] = 2.0
    with pytest.raises(ValueError): _validate_record(record)
    _rebind_record(record)
    _validate_record(record)


def test_cancel_record_cannot_report_an_ok_review():
    record = _qualification_record("cancel")
    _validate_record(record)
    record["result"] = {"status": "OK", "text": "AGREE", "detail": None}
    _rebind_record(record)
    with pytest.raises(ValueError): _validate_record(record)


@pytest.mark.parametrize("operation", ["completion", "cancel", "owner-loss"])
@pytest.mark.parametrize("bad_fact", ["live_namespace_members", "init_exited", "home_removed", "owned_fds_closed"])
def test_every_operation_requires_verified_cleanup(operation, bad_fact):
    record = _qualification_record(operation)
    _validate_record(record)
    record["observer"][bad_fact] = [100003] if bad_fact == "live_namespace_members" else False
    _rebind_record(record)
    with pytest.raises(ValueError): _validate_record(record)


@pytest.mark.parametrize("fabrication", ["broker", "terminal_monitor", "result"])
def test_owner_loss_never_accepts_a_fabricated_terminal_record(fabrication):
    record = _qualification_record("owner-loss")
    if fabrication == "broker": record["broker"] = _qualification_record("completion")["broker"]
    if fabrication == "terminal_monitor": record["monitoring"]["terminal_reason"] = "completed"
    if fabrication == "result": record["result"] = {"status": "OK", "text": "AGREE", "detail": None}
    _rebind_record(record)
    with pytest.raises(ValueError): _validate_record(record)
