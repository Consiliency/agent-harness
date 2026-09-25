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
        "--bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--", "fixture", "arg",
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


def _fixture_repo(tmp_path):
    """A private one-commit repository for the board to digest and stage.

    The HARDEN review authority defaults to the CURRENT DIRECTORY -- the live checkout --
    independently of ``repo_dir``: the board digests its tracked files but stages a clone
    of HEAD, so another xdist worker rewriting a tracked file mid-test made them differ
    ("HARDEN review staged tree does not match authorization", agent-harness#987). Run
    the board with this repo as the cwd (``repo_dir`` alone does not move the authority;
    an explicit ``canonical_repo_authority`` also demands a pre-minted authorization)."""
    repo = tmp_path / "repo"
    panel.run_provider(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "README.md").write_text("synthetic review authority\n")
    panel.run_provider(["git", "-C", str(repo), "add", "README.md"], check=True, capture_output=True)
    panel.run_provider(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture"], check=True, capture_output=True)
    return repo


@pytest.fixture(autouse=True)
def _private_review_authority(tmp_path_factory, monkeypatch):
    """Every test here runs with a private one-commit repository as its cwd.

    The HARDEN review authority defaults to the cwd; left at the live checkout, a board
    run digests the checkout's tracked files but stages a clone of HEAD, so any other
    xdist worker (or an uncommitted edit) makes them differ -- "HARDEN review staged
    tree does not match authorization" (agent-harness#987). Tests that need a specific
    cwd chdir again; the last chdir wins."""
    monkeypatch.chdir(_fixture_repo(tmp_path_factory.mktemp("authority")))


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
 'pid':os.readlink('/proc/self/ns/pid')+' '+str(os.getpid()),
 'namespace':os.readlink('/proc/self/ns/pid'), 'fd_targets':fd_targets,
 'random_available':len(os.urandom(8))==8
}}))
if mode=='cancel':
    child=os.fork()
    if child==0:
        os.setsid()
        ready=Path({str(tmp_path / 'detached')!r})
        ready.with_suffix('.tmp').write_text(os.readlink('/proc/self/ns/pid')+' '+str(os.getpid()))
        os.replace(ready.with_suffix('.tmp'),ready)
        while True: time.sleep(.1)
    print('synthetic provider ready',file=sys.stderr,flush=True)
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
if mode in ('native-timeout','native-timeout-zero'):
    print('Error: timeout waiting for response PRIVATE_FIXTURE_SENTINEL',file=sys.stderr)
    raise SystemExit(0 if mode=='native-timeout-zero' else 1)
if mode=='malformed':
    print('{{PRIVATE_FIXTURE_SENTINEL',flush=True)
    raise SystemExit(0)
if mode=='quoted-timeout':
    print('{{'+'x'*220+' timeout waiting for response',flush=True)
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
if mode=='empty-timeout':
    print('Error: timeout waiting for response',file=sys.stderr)
emit('' if mode in ('empty','denied-empty','empty-timeout') else '<truncated 123 bytes>' if mode=='truncation' else 'No blocking findings.\\nAGREE',
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


def test_public_preflight_uses_the_supplied_subscription_environment(fixture_cli, monkeypatch):
    fixture_cli.module.require_capability(panel._broker_subscription_env())
    monkeypatch.setattr(panel, "default_matrix", lambda **kw: pytest.fail("availability preceded capability check"))
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization",
                        lambda *a, **kw: pytest.fail("authorization preceded actual-environment capability check"))
    result = panel.invoke_board(
        DEFAULT_BOARD, "input", monitoring_policy="heartbeat_only",
        base_env={"PATH": "/missing-gemini-image", "HOME": str(fixture_cli.home)},
    )
    assert len(result.legs) == 4
    assert all(leg.status == "UNAVAILABLE" and "gemini" in leg.detail for leg in result.legs)
    assert all(leg.review_monitoring["terminal_reason"] == "policy_refusal" for leg in result.legs)
    assert not fixture_cli.attempts.exists()


def test_supplied_capability_does_not_also_require_the_ambient_image(fixture_cli, monkeypatch, tmp_path):
    supplied = dict(os.environ)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    cancel = threading.Event()
    cancel.set()
    result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                base_env=supplied, cancel_event=cancel,
                                stream_dir=tmp_path / "records")
    assert result.legs[0].detail == "review_operation_cancelled"
    assert not fixture_cli.attempts.exists()


def test_repo_dir_sets_the_review_authority_not_the_cwd(fixture_cli, tmp_path, monkeypatch):
    """agent-harness#1053 decision 2: ``repo_dir`` is the repository under review, so it is
    also the HARDEN review authority -- the tree that is fingerprinted and staged -- rather
    than whatever directory the process happens to run in. The cwd here is a different
    repository; both the authorization digest and the staged tree must come from repo_dir."""
    import phase_loop_runtime.advisor_board.backing as backing
    import phase_loop_runtime.review_stage as review_stage

    fixture_cli.mode.write_text("ok")
    reviewed = _fixture_repo(tmp_path / "reviewed")
    elsewhere = _fixture_repo(tmp_path / "elsewhere")
    monkeypatch.chdir(elsewhere)
    digested, staged = [], []
    real_digest, real_stage = backing._staged_tree_digest, review_stage.stage_review_tree

    def digest(authority):
        digested.append(Path(authority).resolve())
        return real_digest(authority)

    def stage(repo, parent=None):
        staged.append(Path(repo).resolve())
        return real_stage(repo, parent)

    monkeypatch.setattr(backing, "_staged_tree_digest", digest)
    monkeypatch.setattr(review_stage, "stage_review_tree", stage)
    result = panel.invoke_board(
        gemini_board(), "synthetic review input", monitoring_policy="heartbeat_only",
        stream_dir=tmp_path / "records", gateway_available=False, repo_dir=reviewed,
    )
    leg, = result.legs
    assert leg.status == "OK", (leg.status, leg.detail)
    assert digested == [reviewed.resolve()], digested
    assert staged == [reviewed.resolve()], staged


def test_a_non_git_repo_dir_keeps_the_cwd_authority(fixture_cli, tmp_path, monkeypatch):
    """The other half of agent-harness#1053 decision 2: a ``repo_dir`` that is not a git
    repository cannot be fingerprinted as one, so the historical cwd authority stands (and
    every later typed refusal is unchanged)."""
    import phase_loop_runtime.advisor_board.backing as backing

    fixture_cli.mode.write_text("ok")
    cwd_repo = _fixture_repo(tmp_path / "cwd")
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    monkeypatch.chdir(cwd_repo)
    digested = []
    real_digest = backing._staged_tree_digest
    monkeypatch.setattr(backing, "_staged_tree_digest",
                        lambda authority: digested.append(Path(authority).resolve()) or real_digest(authority))
    result = panel.invoke_board(
        gemini_board(), "synthetic review input", monitoring_policy="heartbeat_only",
        stream_dir=tmp_path / "records", gateway_available=False, repo_dir=plain,
    )
    leg, = result.legs
    assert leg.status == "OK", (leg.status, leg.detail)
    assert digested == [cwd_repo.resolve()], digested


def test_the_work_tree_probe_fails_closed_on_filesystem_errors(tmp_path, monkeypatch):
    """#1055 r2 (codex, claude): an EACCES/EIO on a ``.git`` lookup, or a symlink loop,
    means "maybe a repository" -- never "outside" (which would review the cwd instead)."""
    import errno

    plain = tmp_path / "plain"
    plain.mkdir()
    assert panel._outside_any_git_work_tree(plain) is True
    real_lstat = os.lstat

    def failing_lstat(path, *args, **kwargs):
        if Path(path).name == ".git":
            raise PermissionError(errno.EACCES, "injected", str(path))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", failing_lstat)
    assert panel._outside_any_git_work_tree(plain) is False
    monkeypatch.setattr(os, "lstat", real_lstat)
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    assert panel._outside_any_git_work_tree(loop) is False  # a symlink loop fails closed
    # #1055 r3 (codex): an I/O error while RESOLVING a symlink alias into a repository
    # must not leave the unresolved alias (whose ancestors miss the repo) -> "outside".
    repo = _fixture_repo(tmp_path / "aliased")
    (repo / "child").mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(repo / "child")
    assert panel._outside_any_git_work_tree(alias) is False

    def eio_on_alias(path, *args, **kwargs):
        if Path(path) == alias:
            raise OSError(errno.EIO, "injected", str(path))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", eio_on_alias)
    assert panel._outside_any_git_work_tree(alias) is False
    monkeypatch.setattr(os, "lstat", real_lstat)
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("loop")))
    assert panel._outside_any_git_work_tree(plain) is False


def test_an_unreadable_repo_dir_is_maybe_a_repository(tmp_path):
    """Implementation-agnostic (a real EACCES, nothing mocked; #1055 president)."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    locked = tmp_path / "locked"
    (locked / "inner").mkdir(parents=True)
    locked.chmod(0o000)
    try:
        assert panel._outside_any_git_work_tree(locked / "inner") is False
        assert panel._outside_any_git_work_tree("bad\0path") is False  # NUL byte fails closed
    finally:
        locked.chmod(0o700)


def test_review_authority_resolution_rule(tmp_path):
    """agent-harness#1053 decision 2, every branch of the one rule (#1055 r1): explicit
    authority wins; else repo_dir; a GOVERNED request ignores repo_dir; a repo_dir outside
    any work tree falls back to the cwd; a real repository whose resolution fails does NOT
    fall back (it reaches the typed refusal). Exactly one resolution per call."""
    repo = _fixture_repo(tmp_path / "r")
    plain = tmp_path / "plain"
    plain.mkdir()
    worktree_file = tmp_path / "wt"
    worktree_file.mkdir()
    (worktree_file / ".git").write_text("gitdir: /nonexistent\n")
    seen = []

    def resolve(value):
        seen.append(value)
        if value == worktree_file:
            raise ValueError("HARDEN review has no canonical repository authority")
        return Path(value or "/cwd")

    def rule(explicit, repo_dir, governed=False):
        seen.clear()
        result = panel._resolve_review_authority(explicit, repo_dir, governed=governed, resolve=resolve)
        assert len(seen) == 1, seen
        return result, seen[0]

    assert rule(tmp_path / "explicit", repo)[1] == tmp_path / "explicit"
    assert rule(None, repo)[1] == repo
    assert rule(None, repo, governed=True)[1] is None
    assert rule(None, plain)[1] is None
    assert rule(None, None)[1] is None
    with pytest.raises(ValueError, match="no canonical repository authority"):
        panel._resolve_review_authority(None, worktree_file, governed=False, resolve=resolve)


@pytest.mark.parametrize("mode,status,detail", [
    ("ok", "OK", None), ("empty", "EMPTY", "without review text"),
    ("malformed", "ERROR", "malformed JSON"), ("ack", "ERROR", "acknowledgement"),
    ("tool", "ERROR", "tool or subagent"), ("native", "ERROR", "native exit"),
    ("native-stdout", "ERROR", "native exit"),
    ("native-timeout", "ERROR", "native timeout"),
    ("native-timeout-zero", "ERROR", "native timeout"),
    ("empty-timeout", "ERROR", "native timeout"),
    ("quoted-timeout", "ERROR", "malformed JSON"),
    ("denied-empty", "ERROR", "tool permission"),
    ("event", "ERROR", "malformed stream event"),
    ("session", "ERROR", "conversation"),
    ("count", "ERROR", "incomplete ingestion"),
    ("final", "ERROR", "terminal response"), ("truncation", "ERROR", "truncation"),
])
def test_real_board_preserves_diagnostics_without_retries(fixture_cli, tmp_path, monkeypatch, mode, status, detail):
    fixture_cli.mode.write_text(mode)
    repo = _fixture_repo(tmp_path)
    monkeypatch.chdir(repo)  # the HARDEN review authority defaults to the cwd
    result = panel.invoke_board(
        gemini_board(), "synthetic review input", monitoring_policy="heartbeat_only",
        stream_dir=tmp_path / "records", gateway_available=False,
        repo_dir=repo,
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


def test_profile_does_not_relabel_a_body_failure_as_a_capability_failure(fixture_cli):
    with pytest.raises(OSError, match="synthetic body failure"):
        with _profile(fixture_cli):
            raise OSError("synthetic body failure")


def test_monitor_write_failure_stays_distinct_from_capability(fixture_cli, tmp_path, monkeypatch):
    fixture_cli.mode.write_text("wait")
    original = panel._ReviewMonitor.observe
    def fail_after_admission(self, age=None, terminal=None):
        if fixture_cli.attempts.exists() and terminal is None:
            self.write_failed = True
            raise OSError("PRIVATE_FIXTURE_SENTINEL")
        return original(self, age, terminal)
    monkeypatch.setattr(panel._ReviewMonitor, "observe", fail_after_admission)
    result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                stream_dir=tmp_path / "records")
    leg, = result.legs
    assert leg.status != "OK" and leg.text == ""
    assert leg.detail == "review_monitoring_write_failed"
    assert leg.harden_isolation_evidence["provider_agy_home_cleanup_verified"]


def test_heartbeat_credential_reference_uses_supplied_home(fixture_cli, tmp_path):
    configured_home = tmp_path / "configured-home"
    configured_token = configured_home / ".gemini/antigravity-cli/antigravity-oauth-token"
    configured_token.parent.mkdir(parents=True)
    configured_token.write_text("synthetic-configured-token\n")
    fixture_cli.mode.write_text("refresh")
    result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                base_env={**os.environ, "HOME": str(configured_home)},
                                stream_dir=tmp_path / "records")
    leg, = result.legs
    assert leg.status == "OK", leg.detail
    assert configured_token.read_text() == "synthetic-refreshed\n"
    assert fixture_cli.token.read_text() == "synthetic-token-only\n"
    assert leg.harden_isolation_evidence["provider_credential_home_source"] == "scrubbed_subscription_home"


def test_heartbeat_credential_home_fallback_is_recorded_truthfully(fixture_cli, tmp_path):
    env = {key: value for key, value in os.environ.items() if key != "HOME"}
    result = panel.invoke_board(gemini_board(), "input", monitoring_policy="heartbeat_only",
                                base_env=env, stream_dir=tmp_path / "records")
    leg, = result.legs
    assert leg.status == "OK", leg.detail
    assert leg.harden_isolation_evidence["provider_credential_home_source"] == "process_home_fallback"


def test_explicit_empty_home_is_not_reported_as_process_home_fallback(fixture_cli, tmp_path, monkeypatch):
    repo = _fixture_repo(tmp_path)
    relative_home = repo / "relative-home"
    token = relative_home / ".gemini/antigravity-cli/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text("synthetic-relative-token\n")
    fixture_cli.mode.write_text("refresh")
    monkeypatch.chdir(relative_home)
    result = panel.invoke_board(gemini_board(), "input", repo_dir=repo,
                                base_env={**os.environ, "HOME": ""}, monitoring_policy="heartbeat_only",
                                stream_dir=tmp_path / "records", review_policy=panel.ReviewLandingPolicy(("gemini",), False))
    leg, = result.legs
    assert leg.status == "OK", leg.detail
    assert token.read_text() == "synthetic-refreshed\n"
    assert fixture_cli.token.read_text() == "synthetic-token-only\n"
    assert leg.harden_isolation_evidence["provider_credential_home_source"] == "scrubbed_subscription_home"


def test_real_broker_cancel_reclaims_private_profile_and_detached_child(fixture_cli, tmp_path):
    fixture_cli.mode.write_text("cancel")
    cancel = threading.Event()
    detached = tmp_path / "detached"
    control_errors = []
    detached_pidfd = []
    def cancel_when_launched():
        try:
            until = time.monotonic() + 30  # synthetic admission only
            while not detached.exists():
                if time.monotonic() >= until: raise AssertionError("fixture did not launch")
                time.sleep(.02)
            # Pin the detached child while it is ALIVE: after cancellation a (namespace
            # inode, local PID) pair can be reused by another test's process.
            detached_pidfd.append(os.pidfd_open(_host_pid(detached.read_text())))
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
    # the pinned detached child is gone (its pidfd is readable once it has exited)
    import select
    assert detached_pidfd, "the detached child was never pinned"
    try:
        until = time.monotonic() + 5
        while not select.select([detached_pidfd[0]], [], [], 0)[0]:
            assert time.monotonic() < until, "detached child survived cancellation"
            time.sleep(.02)
    finally:
        os.close(detached_pidfd[0])
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
        # A private repository, never the live checkout (agent-harness#1053).
        canonical_repo_authority=_fixture_repo(tmp_path / "authority"),
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
panel.invoke_board(board,'synthetic owner-loss fixture',monitoring_policy='heartbeat_only',stream_dir=Path({str(tmp_path / 'records')!r}),review_policy=panel.ReviewLandingPolicy(('gemini',),False))
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
        provider_pid = _host_pid(info["pid"])
        for pid in (provider_pid, _host_pid(detached.read_text())):
            pidfds.append(os.pidfd_open(pid))
        namespace = os.stat(f"/proc/{provider_pid}/ns/pid")
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
               "terminal_reason": "completed", "admission_expires_monotonic_ns": 10000000100}
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
        "provider_namespace_identity": {"init_pid": 100002, "init_start": "2",
                                        "pid_namespace_device": 4, "pid_namespace_inode": 12345},
        "provider_namespace_quiescence": {"init_exited": True, "live_members": [], "unreadable_entries": 0},
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
        "credential_home_source": "scrubbed_subscription_home",
        "credential_target_regular_before": True, "credential_target_regular_after": True,
        "live_namespace_members": [], "owned_fds_closed": True,
        "sandbox_network_filtered": True, "network_rules_verified": True,
        "network_rule_checks": 3,
        "init_pid": 100002, "init_start": "2", "pid_namespace_device": 4, "pid_namespace_inode": 12345,
        "provider_pid": 100003, "provider_start": "3",
        "mount_namespace_device": 4, "mount_namespace_inode": 12346,
        "mount_namespace_users_after": [], "mount_scan_unreadable_entries": 0,
        "fd_cleanup_observations": [{"pid": 100002, "start": "2", "state": "absent", "fd_count": 0},
                                    {"pid": 100003, "start": "3", "state": "absent", "fd_count": 0}],
        "helpers": [{"pid": 100003, "start": "3", "executable_sha256": "c" * 64, "is_agy": True}],
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


def test_completion_record_needs_a_terminal_review_even_with_coherent_hashes():
    record = _qualification_record("completion")
    _validate_record(record)
    record["result"]["text"] = "A nonterminal partial response"
    record["broker"]["provider_response_sha256"] = sha256(record["result"]["text"].encode()).hexdigest()
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


@pytest.mark.parametrize("field", ["init_pid", "init_start", "pid_namespace_device", "pid_namespace_inode", "expiry", "quiescence"])
def test_qualification_cross_checks_namespace_and_admission_identity(field):
    record = _qualification_record("completion")
    _validate_record(record)
    if field == "expiry": record["monitoring"]["admission_expires_monotonic_ns"] += 1
    elif field == "quiescence": record["broker"]["provider_namespace_quiescence"]["init_exited"] = False
    else: record["broker"]["provider_namespace_identity"][field] = "other" if field == "init_start" else 99999
    _rebind_record(record)
    with pytest.raises(ValueError): _validate_record(record)


@pytest.mark.parametrize("field", ["provider_start", "unknown_helper", "not_agy", "fd_open", "mount_user", "credential_missing", "no_rules"])
def test_qualification_requires_measured_entry_and_cleanup_facts(field):
    record = _qualification_record("completion")
    _validate_record(record)
    if field == "provider_start": record["observer"]["provider_start"] = "999"
    if field == "unknown_helper": record["observer"]["helpers"][0]["executable_sha256"] = "4" * 64
    if field == "not_agy": record["observer"]["helpers"][0]["is_agy"] = False
    if field == "fd_open": record["observer"]["fd_cleanup_observations"][0].update(state="open", fd_count=1)
    if field == "mount_user": record["observer"]["mount_namespace_users_after"] = [{"pid": 100003, "start": "3"}]
    if field == "credential_missing": record["observer"]["credential_target_regular_after"] = False
    if field == "no_rules": record["observer"]["network_rule_checks"] = 0
    _rebind_record(record)
    with pytest.raises(ValueError): _validate_record(record)


def test_helper_observer_rejects_same_pid_exec_even_into_an_allowed_helper(tmp_path):
    observer_type = _qualification_validator().__globals__["HelperObserver"]
    shell_hash = sha256(Path("/usr/bin/dash").read_bytes()).hexdigest()
    sleep_hash = sha256(Path("/usr/bin/sleep").read_bytes()).hexdigest()
    proc = panel.launch_provider(["/usr/bin/dash", "-c", "read trigger; exec /usr/bin/sleep 30"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        start = Path(f"/proc/{proc.pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
        observer = observer_type(shell_hash, {"sleep": sleep_hash}, (proc.pid, start))
        observer.observe(proc.pid, start)
        proc.stdin.write(b"go\n")
        proc.stdin.flush()
        until = time.monotonic() + 2  # synthetic exec admission only
        while sha256(Path(f"/proc/{proc.pid}/exe").read_bytes()).hexdigest() != sleep_hash:
            assert time.monotonic() < until
            time.sleep(.01)
        assert Path(f"/proc/{proc.pid}/stat").read_text().rsplit(") ", 1)[1].split()[19] == start
        with pytest.raises(ValueError, match="identity policy"):
            observer.observe(proc.pid, start)
    finally:
        proc.kill()
        proc.wait(5)
        proc.stdin.close()


def _qualification_directory(root):
    artifact, brief, help_text = "synthetic artifact", "synthetic instructions", "synthetic help"
    prompt = panel._render_broker_inline_prompt(artifact, brief, "review")
    request = {"artifact_sha256": sha256(artifact.encode()).hexdigest(),
               "instructions_sha256": sha256(brief.encode()).hexdigest(),
               "provider_input_sha256": sha256(prompt.encode()).hexdigest(),
               "provider_transport_sha256": sha256(panel._broker_gemini_stream_protocol(prompt).transport.encode()).hexdigest()}
    for operation in ("completion", "cancel", "owner-loss"):
        folder = root / operation
        folder.mkdir()
        record = _qualification_record(operation)
        record["request"] = request
        record["help_sha256"] = sha256(help_text.encode()).hexdigest()
        if record["broker"] is not None:
            record["broker"].update(stage_bundle_sha256=request["artifact_sha256"], stage_instructions_sha256=request["instructions_sha256"],
                                    provider_input_sha256=request["provider_input_sha256"], provider_prompt_sha256=request["provider_input_sha256"],
                                    provider_transport_sha256=request["provider_transport_sha256"])
        _rebind_record(record)
        (folder / "artifact.md").write_text(artifact)
        (folder / "brief.md").write_text(brief)
        (folder / "agy-help.txt").write_text(help_text)
        admission = {**record["observer"], "monitoring": {**record["monitoring"], "terminal_reason": None}, "kill_event": None}
        (folder / "admission-observation.json").write_text(json.dumps(admission))
        prereg = {k: record[k] for k in ("operation", "source_sha256", "image_sha256", "help_sha256", "profile", "profile_sha256", "request")}
        prereg["attempt_limit"] = 1
        (folder / "preregistration.json").write_text(json.dumps(prereg))
        (folder / "qualification.json").write_text(json.dumps(record))
        if operation != "owner-loss":
            (folder / "terminal.json").write_text(json.dumps({key: record[key] for key in ("monitoring", "broker", "result")}))
    return {"expected_source_sha256": {"panel_invoker.py": "a" * 64}, "expected_image_sha256": "c" * 64,
            "expected_help_sha256": sha256(help_text.encode()).hexdigest(), "expected_profile_sha256": _digest_record(_qualification_profile())}


@pytest.mark.parametrize("mutation", ["failed_attempt", "pending_attempt", "unregistered_receipt", "prereg_mismatch", "input_change", "admission_change", "duplicate_operation", "terminal_change", "owner_terminal", "admission_expiry", "admission_policy"])
def test_directory_validator_cannot_select_success_from_an_incomplete_attempt_set(tmp_path, mutation):
    validate = _qualification_validator().__globals__["validate_directory"]
    expected = _qualification_directory(tmp_path)
    assert validate(tmp_path, **expected)["route_qualified"] is True
    if mutation in ("failed_attempt", "pending_attempt", "duplicate_operation"):
        import shutil
        extra = tmp_path / "extra"
        shutil.copytree(tmp_path / "completion", extra)
        if mutation != "duplicate_operation": (extra / "qualification.json").unlink()
        if mutation == "failed_attempt": (extra / "failure.json").write_text('{"qualification_passed":false}')
    if mutation == "unregistered_receipt": (tmp_path / "completion/preregistration.json").unlink()
    if mutation == "prereg_mismatch":
        p = tmp_path / "completion/preregistration.json"
        value = json.loads(p.read_text()); value["attempt_limit"] = 2; p.write_text(json.dumps(value))
    if mutation == "input_change": (tmp_path / "owner-loss/artifact.md").write_text("different input")
    if mutation == "admission_change":
        p = tmp_path / "owner-loss/admission-observation.json"
        value = json.loads(p.read_text()); value["provider_start"] = "999"; p.write_text(json.dumps(value))
    if mutation == "terminal_change":
        p = tmp_path / "completion/terminal.json"
        value = json.loads(p.read_text()); value["result"]["text"] = "Different. DISAGREE"; p.write_text(json.dumps(value))
    if mutation == "owner_terminal": (tmp_path / "owner-loss/terminal.json").write_text("{}")
    if mutation in ("admission_expiry", "admission_policy"):
        p = tmp_path / "owner-loss/admission-observation.json"
        value = json.loads(p.read_text())
        if mutation == "admission_expiry": value["monitoring"]["admission_expires_monotonic_ns"] += 1
        else: value["monitoring"]["effective_policy"] = "bounded"
        p.write_text(json.dumps(value))
    with pytest.raises(ValueError): validate(tmp_path, **expected)


def test_helper_observer_includes_nested_pid_namespaces(tmp_path):
    driver = _qualification_validator().__globals__
    command = ["bwrap", "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/",
               "--proc", "/proc", "--dev", "/dev", "--", "/usr/bin/unshare",
               "--user", "--map-root-user", "--pid", "--fork", "--kill-child", "/usr/bin/sleep", "30"]
    proc = panel.launch_provider(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 5  # synthetic process startup only
        while True:
            table = driver["process_table"]()
            children = driver["descendants"](table, proc.pid)
            sleeping = []
            for pid in children:
                try:
                    if Path(f"/proc/{pid}/exe").resolve() == Path("/usr/bin/sleep"):
                        sleeping.append(pid)
                except (FileNotFoundError, ProcessLookupError):
                    pass
            if sleeping:
                break
            assert proc.poll() is None, proc.stderr.read().decode()
            assert time.monotonic() < deadline, "nested synthetic helper did not start"
            time.sleep(.02)
        def namespace_pids(pid):
            return next(line for line in Path(f"/proc/{pid}/status").read_text().splitlines()
                        if line.startswith("NSpid:")).split()[1:]
        outer_depth = len(namespace_pids("self")) + 1
        init = next(pid for pid in children if len(namespace_pids(pid)) == outer_depth and namespace_pids(pid)[-1] == "1")
        assert os.stat(f"/proc/{sleeping[0]}/ns/pid").st_ino != os.stat(f"/proc/{init}/ns/pid").st_ino
        observer = driver["HelperObserver"](sha256(Path("/usr/bin/bwrap").read_bytes()).hexdigest(),
                                             {"unshare": sha256(Path("/usr/bin/unshare").read_bytes()).hexdigest()})
        with pytest.raises(ValueError, match="outside the registered identity policy") as caught:
            driver["observe_owned_helpers"](table, init, observer)
        driver["write_failure"](tmp_path, caught.value, "helper_observation", observer, {})
        failure = json.loads((tmp_path / "failure.json").read_text())
        assert failure["rejected_image"]["executable_sha256"] == sha256(Path("/usr/bin/sleep").read_bytes()).hexdigest()
        assert failure["rejected_image"]["pid"] == sleeping[0]
        assert "outside the registered identity policy" in failure["reason"]
        driver["write_failure"](tmp_path, OSError("PRIVATE_FIXTURE_SENTINEL"), "observer_cleanup", observer, {})
        updated = json.loads((tmp_path / "failure.json").read_text())
        assert updated["reason"] == failure["reason"]
        assert "PRIVATE_FIXTURE_SENTINEL" not in json.dumps(updated)
    finally:
        panel._terminate_process_group(proc)
        proc.stderr.close()


def test_qualification_refuses_an_empty_network_rule_set(monkeypatch):
    from phase_loop_runtime import sandbox_egress
    monkeypatch.setattr(sandbox_egress, "egress_rules", lambda: [])
    with pytest.raises(ValueError, match="rule set is empty"):
        _qualification_validator().__globals__["inspect_network"](os.getpid())


def _host_pid(record: str, timeout_s: float = 5.0) -> int:
    """Host PID for a ``"<pid-namespace link> <namespace-local pid>"`` record.

    Inside the owner wrapper /proc is the namespace's OWN procfs (agent-harness#1003), so a
    process can only report its namespace-local PID; the host PID is resolved from outside
    through the host /proc (the process whose pid namespace matches and whose innermost
    ``NSpid`` is that PID).
    """
    link, local = record.split()
    deadline = time.monotonic() + timeout_s
    while True:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.readlink(f"/proc/{entry}/ns/pid") != link:
                    continue
                nspid = next(line for line in Path(f"/proc/{entry}/status").read_text().splitlines()
                             if line.startswith("NSpid:"))
            except (OSError, StopIteration):
                continue
            if nspid.split()[-1] == local:
                return int(entry)
        if time.monotonic() >= deadline:
            raise AssertionError(f"no host process for {record!r}")
        time.sleep(.02)
