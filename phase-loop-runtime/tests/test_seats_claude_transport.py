"""SEATS CLAUDE, IF-0-CLAUDE-1: the jailed Claude seat's transport seam (EC-CLAUDE-1,
EC-CLAUDE-7).

* Resolution and refusal over every selector value; a refused value launches nothing.
* For every terminal code in ``CODES``, a control at the real ``_parent_infer`` jailed call
  site launches no other transport, the TUI included.
* The login proof (IF-0-CLAUDE-4) and the seat-mode republish run on every jailed
  transport, and ``claude_transport`` reaches ``broker_evidence``.
* Every ``CODES`` entry reaches the mode line with its OD-10 class; no fix line names a
  key-based credential; none is on the descend list.
* ``live_jail``: ``tui`` and every admitted transport module run at the real call site in
  a real jail, with a fake subject at ``/seat/bin/claude`` recording its argv, environment,
  descriptors and mounts. Stub transports are only failing controls: each widens one
  thing and must fail. With ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1`` a missing prerequisite
  fails instead of skipping.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

import pytest

from phase_loop_runtime import claude_seat_transport as ct
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_preflight as sp

PROVEN = sc.LoginProof(sc.SOURCE_LOGIN, "oauth_token", "none")
ACCESS = "fake-login-access-" + "t" * 24


# --------------------------------------------------------------------------------------
# Fake transport modules: admitted or not, registered under the package for one test.
# --------------------------------------------------------------------------------------

def _citation(section: str = "4a") -> ct.RecordCitation:
    return ct.RecordCitation(ct.DECISION_RECORD, section, "0" * 64, "agent-harness#1775")


def _install(monkeypatch, transport: str, *, admitted=True, activation=True, run=None,
             importable=True):
    name = ct._CANONICAL_TRANSPORT_MODULES[transport]
    qualified = f"phase_loop_runtime.{name}"
    if not importable:
        monkeypatch.delitem(sys.modules, qualified, raising=False)
        imported = ct.importlib.import_module

        def refuse(target, *args, **kwargs):
            if target == qualified:
                raise ImportError(target)
            return imported(target, *args, **kwargs)

        monkeypatch.setattr(ct.importlib, "import_module", refuse)
        return None
    module = types.ModuleType(qualified)
    module.__file__ = str(Path(ct.__file__))
    module.ADMITTED = admitted
    if activation:
        module.ACTIVATION = _citation("4a" if transport == "print" else "4b")
    module.calls = []

    def run_jailed(seat, **kwargs):
        module.calls.append(kwargs)
        return run(seat, **kwargs) if run is not None else ("OK", "a review\n\nAGREE")

    module.run_jailed = run_jailed
    literal_facts = ct._runtime_literal_facts

    def facts(module_name, names):
        if module_name != name:
            return literal_facts(module_name, names)
        values = {"ADMITTED": admitted}
        if activation:
            values["ACTIVATION"] = module.ACTIVATION
        return Path(module.__file__), {key: value for key, value in values.items() if key in names}

    monkeypatch.setattr(ct, "_runtime_literal_facts", facts)
    monkeypatch.setitem(sys.modules, qualified, module)
    return module


@pytest.fixture
def none_admitted(monkeypatch):
    _install(monkeypatch, "print", admitted=False)
    _install(monkeypatch, "sdk", admitted=False)


# --------------------------------------------------------------------------------------
# Resolution.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, admitted, expected", [
    (None, (), ("tui", None)),
    ("", (), ("tui", None)),
    ("   ", (), ("tui", None)),
    ("tui", (), ("tui", None)),
    (" TUI ", (), ("tui", None)),
    ("print", (), (None, ct.NOT_ADMITTED)),
    ("sdk", (), (None, ct.NOT_ADMITTED)),
    ("print", ("print",), ("print", None)),
    ("Print", ("print",), ("print", None)),
    ("sdk", ("print",), (None, ct.NOT_ADMITTED)),
    ("sdk", ("print", "sdk"), ("sdk", None)),
    ("bogus", ("print", "sdk"), (None, ct.ROUTE_INVALID)),
    ("tui,print", ("print",), (None, ct.ROUTE_INVALID)),
    ("bare", (), (None, ct.ROUTE_INVALID)),
])
def test_resolution_covers_every_selector_value(monkeypatch, raw, admitted, expected):
    for transport in ("print", "sdk"):
        _install(monkeypatch, transport, admitted=transport in admitted)
    env = {} if raw is None else {ct.ROUTE_ENV: raw}
    assert ct.resolve_jailed_claude_transport(env) == expected


@pytest.mark.parametrize("variant", ["not-admitted", "no-activation", "not-importable",
                                     "admitted-truthy", "run-not-callable"])
def test_a_module_short_of_the_three_exports_is_not_admitted(monkeypatch, variant):
    module = _install(monkeypatch, "print",
                      admitted=False if variant == "not-admitted" else
                      (1 if variant == "admitted-truthy" else True),
                      activation=variant != "no-activation",
                      importable=variant != "not-importable")
    if variant == "run-not-callable":
        module.run_jailed = "run"
    assert ct.transport_module("print") is None
    assert ct.resolve_jailed_claude_transport({ct.ROUTE_ENV: "print"}) == (None, ct.NOT_ADMITTED)


def test_tui_is_always_admitted_and_is_the_shipped_default():
    assert ct.is_admitted("tui")
    assert ct.JAILED_CLAUDE_DEFAULT in ct.TRANSPORTS
    record = (Path(__file__).resolve().parents[2] / ct.DECISION_RECORD).read_bytes()
    assert ct.default_rule_failures(ct.JAILED_CLAUDE_DEFAULT, ct.JAILED_DEFAULT_AUTHORITY,
                                    record, ()) == [] or ct.JAILED_CLAUDE_DEFAULT != "tui"


def test_no_transport_module_imports_the_agent_sdk_in_the_parent():
    code = textwrap.dedent("""
        import importlib, sys
        from phase_loop_runtime import claude_seat_transport as ct
        for name in ct._TRANSPORT_MODULES.values():
            try:
                importlib.import_module("phase_loop_runtime." + name)
            except ImportError:
                pass
        for transport in ("print", "sdk"):
            ct.transport_module(transport)
        import phase_loop_runtime.panel_invoker
        assert not any(m == "claude_agent_sdk" or m.startswith("claude_agent_sdk.")
                       for m in sys.modules), sorted(m for m in sys.modules if "claude_agent" in m)
    """)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]


# --------------------------------------------------------------------------------------
# The CODES table.
# --------------------------------------------------------------------------------------

_KEY_WORDING = re.compile(r"api[\s_-]*key|anthropic_api|x-api-key", re.IGNORECASE)


def test_the_codes_table_is_the_frozen_set_with_classes():
    assert set(ct.CODES) == {
        "claude_seat_token_in_output", "claude_seat_api_key_source", "claude_sdk_closure_refused",
        "claude_seat_login_unproven", "claude_seat_result_unproven", "claude_seat_stream_unsafe",
        "claude_sdk_dependency_unavailable"}
    security = {code for code, entry in ct.CODES.items() if entry[0] == ct.SECURITY}
    assert security == {"claude_seat_token_in_output", "claude_seat_api_key_source",
                        "claude_sdk_closure_refused"}
    assert all(entry[0] in ct.OD10_CLASSES for entry in ct.CODES.values())


@pytest.mark.parametrize("code", sorted(ct.CODES))
def test_no_code_descends_and_no_fix_line_names_a_key(code):
    klass, what, why, fix = ct.CODES[code]
    assert code not in seat_jail.SEALED_FALLBACK_CODES
    assert code not in seat_jail.JAIL_NOT_RUN_CODES
    assert not _KEY_WORDING.search(fix), fix
    assert what and why and fix
    assert code in pi._HARNESS_DETAIL_CODES
    if code in seat_jail.NOTICES:
        assert seat_jail.NOTICES[code] == (what, why, fix)


@pytest.mark.parametrize("code", sorted(ct.CODES))
def test_every_code_reaches_the_mode_line_with_its_class(code):
    assert code in ct.mode_line_codes()
    leg = pi.PanelLegResult(leg="claude", status="DEGRADED", text="", detail=code,
                            seat_key="claude:a")
    notices = [n for n in leg.seat_notices if n.code == code]
    assert len(notices) == 1
    klass, what, why, fix = ct.CODES[code]
    assert (notices[0].what, notices[0].why, notices[0].fix) == (f"{what} (OD-10 {klass})", why, fix)


# --------------------------------------------------------------------------------------
# The real spawn: a refused value launches nothing and republishes the seat's mode.
# --------------------------------------------------------------------------------------

@contextlib.contextmanager
def _published_modes(tmp_path):
    stream = tmp_path / "stream"
    sp.write_modes_record(stream, [sp.SeatMode("claude:a", "claude", sp.MODE_JAILED, None,
                                               "full tools inside its per-seat jail", "",
                                               sc.SOURCE_LOGIN, 0)])
    tokens = (pi._SEAT_MODES_STREAM.set(stream), pi._SEAT_SESSION_SEAT.set("claude:a"))
    try:
        yield stream
    finally:
        pi._SEAT_SESSION_SEAT.reset(tokens[1])
        pi._SEAT_MODES_STREAM.reset(tokens[0])


def _row(stream: Path) -> dict:
    return json.loads((stream / sp.MODES_FILE).read_text())["modes"][0]


@pytest.mark.parametrize("raw, code", [
    ("bogus", ct.ROUTE_INVALID), ("sdk", ct.NOT_ADMITTED), ("print", ct.NOT_ADMITTED),
])
def test_a_refused_selection_launches_nothing_at_the_real_spawn(
        monkeypatch, tmp_path, none_admitted, raw, code):
    from test_seat_login_wait_a3_1166 import _spawn

    monkeypatch.setenv(ct.ROUTE_ENV, raw)
    tui = []
    with _published_modes(tmp_path) as stream:
        spawned, calls = _spawn(monkeypatch, tmp_path, sc.LOGIN_READY,
                                jailed_leg=lambda seat, **k: tui.append(k) or ("OK", "x"))
    assert calls == {"prepare": 0, "launched": 0}
    assert tui == []
    assert tuple(spawned)[:2] == ("DEGRADED", "") and str(tuple(spawned)[2]) == code
    assert list((tmp_path / "staging").iterdir()) == []
    row = _row(stream)
    assert (row["mode"], row["code"]) == (sp.MODE_DEGRADED, code)
    assert row["fix"] == ct.REFUSAL_TEXT[code][2]


@pytest.mark.parametrize("outcome, code", [
    (sc.LOGIN_TIMEOUT, "claude_seat_login_token_expiring"),
    (sc.LOGIN_MISSING, "claude_seat_token_missing"),
])
def test_a_timed_out_login_wait_republishes_the_seat_mode(monkeypatch, tmp_path, outcome, code):
    """EC-CLAUDE-7, agent-harness#1255."""
    from test_seat_login_wait_a3_1166 import _spawn

    with _published_modes(tmp_path) as stream:
        spawned, calls = _spawn(monkeypatch, tmp_path, outcome)
    assert calls == {"prepare": 0, "launched": 0}
    row = _row(stream)
    _what, why, fix = seat_jail.NOTICES[code]
    assert (row["mode"], row["code"], row["why"], row["fix"]) == (sp.MODE_DEGRADED, code, why, fix)


# --------------------------------------------------------------------------------------
# The real `_parent_infer` jailed call site: one transport, the proof first, no fall-through.
# --------------------------------------------------------------------------------------

def _run_call_site(monkeypatch, tmp_path, *, transport, tui=None, proof=None):
    """Drive `_default_spawn` to the real jailed call site. The prepared seat is a stand-in;
    the dispatch, the proof call and the outcome handling are the production code."""
    from test_seat_login_wait_a3_1166 import _spawn

    monkeypatch.setenv(ct.ROUTE_ENV, transport)
    seen = {"tui": [], "proof": 0, "cleanup": 0}

    def _tui(seat, **kwargs):
        seen["tui"].append(kwargs)
        return tui(seat, **kwargs) if tui is not None else ("OK", "a review\n\nAGREE")

    def _proof(seat, *a, **k):
        seen["proof"] += 1
        return proof(seat) if proof is not None else PROVEN

    monkeypatch.setattr(pi, "_cleanup_jailed_seat",
                        lambda seat, **k: seen.__setitem__("cleanup", seen["cleanup"] + 1))
    spawned, calls = _spawn(monkeypatch, tmp_path, sc.LOGIN_READY, jailed_leg=_tui,
                            login_proof=_proof)
    return spawned, calls, seen


def _detail(spawned) -> str:
    detail = tuple(spawned)[2] if len(tuple(spawned)) > 2 else ""
    return str(getattr(detail, "template", detail))


@pytest.mark.parametrize("transport", ["tui", "print"])
def test_the_proof_runs_once_before_the_selected_transport_and_its_evidence_is_kept(
        monkeypatch, tmp_path, transport):
    module = _install(monkeypatch, "print")
    order: list[str] = []
    module_run = module.run_jailed

    def run_print(seat, **kwargs):
        order.append("print")
        return module_run(seat, **kwargs)

    module.run_jailed = run_print
    spawned, calls, seen = _run_call_site(
        monkeypatch, tmp_path, transport=transport,
        tui=lambda seat, **k: (order.append("tui"), ("OK", "a review\n\nAGREE"))[1],
        proof=lambda seat: (order.append("proof"), PROVEN)[1])
    assert seen["proof"] == 1
    assert order == ["proof", transport]
    kwargs = (seen["tui"] or module.calls)[0]
    evidence = kwargs["broker_evidence"]
    assert evidence["claude_transport"] == transport
    assert evidence["claude_login_auth_method"] == "oauth_token"
    assert evidence["claude_login_api_key_source"] == "none"
    assert tuple(spawned)[0] == "OK"


@pytest.mark.parametrize("code", sorted(ct.CODES))
@pytest.mark.parametrize("selected", ["tui", "print"])
def test_a_terminal_code_of_the_selected_transport_launches_no_other(
        monkeypatch, tmp_path, code, selected):
    """No fall-through: whatever the selected transport ends in, nothing else launches."""
    def ending(seat, **kwargs):
        if code in seat_jail.NOTICES or code in ("claude_seat_result_unproven",):
            kwargs["failure_detail_sink"].append(pi._LegFailure(template=code))
            return "DEGRADED", ""
        raise ct.TransportRefused(code)

    module = _install(monkeypatch, "print", run=ending if selected == "print" else None)
    spawned, _calls, seen = _run_call_site(
        monkeypatch, tmp_path, transport=selected,
        tui=ending if selected == "tui" else None)
    assert (len(seen["tui"]), len(module.calls)) == ((1, 0) if selected == "tui" else (0, 1))
    assert tuple(spawned)[0] == "DEGRADED"
    assert _detail(spawned) == code
    assert code in spawned.seat_notices


@pytest.mark.parametrize("code", [sc.LOGIN_UNPROVEN, sc.TOKEN_IN_OUTPUT])
@pytest.mark.parametrize("selected", ["tui", "print"])
def test_a_failed_proof_launches_no_transport_and_republishes(monkeypatch, tmp_path, code, selected):
    module = _install(monkeypatch, "print")

    def failing(seat):
        raise ct.TransportRefused(code)

    with _published_modes(tmp_path) as stream:
        spawned, _calls, seen = _run_call_site(monkeypatch, tmp_path, transport=selected,
                                               proof=failing)
    assert seen["tui"] == [] and module.calls == []
    assert seen["cleanup"] == 1
    assert _detail(spawned) == code and tuple(spawned)[0] == "DEGRADED"
    assert _row(stream)["code"] == code and _row(stream)["mode"] == sp.MODE_DEGRADED


def test_ec_claude_7_a_failing_probe_at_the_real_call_site_launches_nothing(
        monkeypatch, tmp_path):
    """The real proof (`_jailed_claude_login_proof` -> `seat_credentials.jailed_login_proof`)
    with only the single-use auth jail stubbed to fail: nothing launches."""
    config = tmp_path / "login" / ".claude"
    config.mkdir(parents=True)
    (config / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": ACCESS, "expiresAt": 4_102_444_800_000, "scopes": ["user:inference"],
        "subscriptionType": "max"}}))
    os.chmod(config / ".credentials.json", 0o600)
    for key in list(os.environ):
        if sc.caller_supplied_credential({key: ""}):
            monkeypatch.delenv(key)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    probes: list[bytes] = []

    def probe(seat, token, **_k):
        probes.append(token)
        return sc.AuthProbeResult(hashlib.sha256(token).hexdigest(), 1, b"")

    monkeypatch.setattr(pi, "_jailed_claude_auth_probe", probe)
    tui: list[object] = []
    import test_seat_login_wait_a3_1166 as a3

    def prepare(*_a, **_k):
        return types.SimpleNamespace(notices=[], token=ACCESS.encode(), source=sc.SOURCE_LOGIN,
                                     expires_at=None)

    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: None)
    spawned, calls = a3._spawn(monkeypatch, tmp_path, sc.LOGIN_READY,
                               jailed_leg=lambda seat, **k: tui.append(k) or ("OK", "x"),
                               login_proof="real", prepare=prepare)
    assert probes == [ACCESS.encode()]
    assert tui == []
    assert _detail(spawned) == sc.LOGIN_UNPROVEN and tuple(spawned)[0] == "DEGRADED"


@pytest.mark.parametrize("differs", ["profile_digest", "filter_digest",
                                     "dependency_projection_digest"])
def test_an_auth_jail_of_another_shape_is_a_failed_probe_and_launches_nothing(
        monkeypatch, tmp_path, differs):
    review = types.SimpleNamespace(profile_digest="a" * 64, filter_digest="b" * 64,
                                   dependency_projection_digest="", provider_path="/x",
                                   seat_ids=(1, 1), dependency=None)
    seat = types.SimpleNamespace(jail=review, seat_dir=tmp_path, holder_pid=1, notices=[])
    built: list[object] = []

    def build(_seat, directory, token):
        jail = types.SimpleNamespace(**{**vars(review), "provider_argv0": "/seat/bin/claude",
                                        "env": {}})
        if not built:
            setattr(jail, differs, "c" * 64)
        built.append(jail)
        return jail

    monkeypatch.setattr(pi, "_build_claude_auth_jail", build)
    monkeypatch.setattr(pi._seat_jail, "close_jail_fds", lambda _j: None)
    monkeypatch.setattr(pi, "_run_leg_with_liveness",
                        lambda *a, **k: pytest.fail("the probe launched"))
    result = pi._jailed_claude_auth_probe(seat, ACCESS.encode())
    assert len(built) == 2
    assert result.returncode != 0 and result.stdout == b""
    assert result.credential_sha256 == hashlib.sha256(ACCESS.encode()).hexdigest()


@pytest.mark.parametrize("planted", [True, False])
def test_an_auth_probe_past_its_cap_is_still_scanned(monkeypatch, tmp_path, planted):
    """A probe that writes past the cap is stopped, and what it wrote is still scanned for
    the proof's security refusal."""
    review = types.SimpleNamespace(profile_digest="a" * 64, filter_digest="b" * 64,
                                   dependency_projection_digest="", provider_path="/x",
                                   seat_ids=(1, 1), dependency=None)
    seat = types.SimpleNamespace(jail=review, seat_dir=tmp_path, holder_pid=1, notices=[])
    monkeypatch.setattr(pi, "_build_claude_auth_jail", lambda _s, _d, _t: types.SimpleNamespace(
        **{**vars(review), "provider_argv0": "/seat/bin/claude", "env": {}}))
    monkeypatch.setattr(pi._seat_jail, "close_jail_fds", lambda _j: None)
    token = ACCESS.encode()

    def run(_cmd, *, stdout_guard, **_k):
        head = b"x" * (sc.PROBE_OUTPUT_CAP_BYTES - 8)
        assert stdout_guard(head) is False
        assert stdout_guard(b"y" * 4 + (token if planted else b"z" * len(token))) is True
        return pi._LegRun(1, "", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    result = pi._jailed_claude_auth_probe(seat, token)
    assert result.returncode != 0
    assert seat_jail.contains_secret(result.stdout, token) is planted
    if not planted:
        assert result.stdout == b""


def test_the_leg_runner_stops_the_group_when_the_stderr_guard_says_so(tmp_path):
    seen: list[bytes] = []

    def guard(chunk: bytes) -> bool:
        seen.append(chunk)
        return True

    started = time.monotonic()
    run = pi._run_leg_with_liveness(
        [sys.executable, "-c", "import sys, time; sys.stderr.write('e' * 64); sys.stderr.flush();"
                               " time.sleep(60)"],
        cwd=str(tmp_path), env=dict(os.environ), deadline_s=90.0, stall_threshold_s=90.0,
        stderr_guard=guard)
    assert time.monotonic() - started < 30
    assert seen and run.returncode != 0


def test_the_jailed_prepare_refuses_a_refused_selection_before_creating_anything(
        monkeypatch, tmp_path, none_admitted):
    seat_dir = tmp_path / "seat"
    for value, code in (("bogus", ct.ROUTE_INVALID), ("sdk", ct.NOT_ADMITTED)):
        monkeypatch.setenv(ct.ROUTE_ENV, value)
        with pytest.raises(ct.TransportRefused) as caught:
            pi._prepare_jailed_claude(tmp_path, seat_dir, types.SimpleNamespace(), 1, 1, ("", ""))
        assert caught.value.code == code
        assert not seat_dir.exists()


def test_sdk_without_a_dependency_session_refuses_before_the_credential(monkeypatch, tmp_path):
    _install(monkeypatch, "sdk")
    read: list[object] = []
    monkeypatch.setattr(pi._seat_credentials, "resolve_claude_seat_credential",
                        lambda *a, **k: read.append(a) or (_ for _ in ()).throw(AssertionError))
    with pytest.raises(ct.TransportRefused) as caught:
        pi._prepare_jailed_claude(tmp_path, tmp_path / "seat", types.SimpleNamespace(), 1, 1,
                                  ("", ""), transport="sdk")
    assert caught.value.code == "claude_sdk_dependency_unavailable"
    assert read == [] and not (tmp_path / "seat").exists()


# --------------------------------------------------------------------------------------
# live_jail: the real call site, a real jail, a fake subject at /seat/bin/claude.
# --------------------------------------------------------------------------------------

REQUIRE_LIVE = os.environ.get("PHASE_LOOP_REQUIRE_LIVE_JAIL") == "1"


def _host_state_home() -> Path:
    import pwd

    configured = os.environ.get("XDG_STATE_HOME")
    if configured and os.path.isabs(configured):
        return Path(configured)
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "state"


#: Captured at import, before any fixture isolates the state home: the host's recorded
#: EC-EXECFIND-2 passes, read only and copied into each live test's private state home.
HOST_PASS_DIR = _host_state_home() / "phase-loop" / "seat-jail-passes"


def _seed_host_passes(state: Path) -> None:
    import shutil

    target = state / "phase-loop" / "seat-jail-passes"
    for directory in (state, state / "phase-loop", target):
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
    for record in HOST_PASS_DIR.glob("*.json"):
        shutil.copyfile(record, target / record.name)
        os.chmod(target / record.name, 0o600)


def require_live_jail() -> None:
    """Skip only when PHASE_LOOP_REQUIRE_LIVE_JAIL is unset; with it set, a missing
    prerequisite fails the test."""
    from phase_loop_runtime import sandbox_egress

    from ._seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready

    missing = []
    if not hasattr(os, "memfd_create"):
        missing.append("this interpreter has no os.memfd_create")
    if not seat_uid_ready():
        missing.append(SEAT_UID_PREREQUISITE)
    if not sandbox_egress.egress_isolation_available():
        missing.append("needs unshare + slirp4netns + iptables")
    else:
        try:
            passed, _reason = seat_jail.pass_record_verdict(
                seat_jail.jail_profile_digest("claude"), root=HOST_PASS_DIR)
        except Exception:
            passed = False
        if not passed:
            missing.append("no recorded EC-EXECFIND-2 pass for the claude jail on this host")
    if missing:
        message = "live jail unavailable: " + "; ".join(missing)
        if REQUIRE_LIVE:
            pytest.fail(message)
        pytest.skip(message)


FAKE_SUBJECT = r'''#!/usr/bin/python3 -I
"""A fake `claude` at /seat/bin/claude: records what it was handed, answers minimally."""
import hashlib, json, os, sys

argv = sys.argv[1:]
fds = {}
for name in sorted(os.listdir("/proc/self/fd"), key=int):
    try:
        target = os.readlink(f"/proc/self/fd/{name}")
    except OSError:
        continue
    if target.startswith("/proc/"):
        continue
    kind = target.split(":", 1)[0] if target.split(":", 1)[0] in (
        "pipe", "socket", "anon_inode") else target
    fds[name] = kind
token_sha256 = None
fd = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "")
if fd.isdigit():
    try:
        token_sha256 = hashlib.sha256(os.read(int(fd), 8192)).hexdigest()
    except OSError:
        token_sha256 = "unreadable"
mounts = sorted({line.split()[4] for line in open("/proc/self/mountinfo")})
role = "auth" if argv[:2] == ["auth", "status"] else "leg"
record = {"argv": argv, "env": dict(os.environ), "fds": fds, "mounts": mounts,
          "token_sha256": token_sha256, "cwd": os.getcwd()}
try:
    with open(f"/seat/out/observed-{role}.json", "x") as handle:
        json.dump(record, handle)
except OSError:
    pass
if role == "auth":
    print(json.dumps({"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}))
    sys.exit(0)
session = argv[argv.index("--session-id") + 1] if "--session-id" in argv else ""
model = argv[argv.index("--model") + 1] if "--model" in argv else ""
if "-p" in argv:
    sys.stdin.read()
    print(json.dumps({"type": "system", "subtype": "init", "apiKeySource": "none",
                      "session_id": session, "model": model, "tools": ["Read"]}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": "observed\n\nAGREE", "session_id": session}), flush=True)
    sys.exit(0)
with open("/seat/out/panel-claude.txt", "w") as handle:
    handle.write("observed\n\nAGREE\n")
sys.exit(0)
'''


def _fake_subject(tmp_path: Path) -> Path:
    path = tmp_path / "fake-bin" / "claude"
    path.parent.mkdir(mode=0o755)
    path.write_text(FAKE_SUBJECT)
    path.chmod(0o755)
    os.chmod(tmp_path, 0o755)
    return path


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@e.st"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm",
                    "seed"], check=True)
    return repo


def _staged_digest(repo: Path, tmp_path: Path) -> str:
    from phase_loop_runtime import review_stage

    probe = tmp_path / "digest-probe"
    probe.mkdir()
    staged = review_stage.stage_review_tree(repo, probe)
    try:
        return review_stage.review_tree_manifest_sha256(staged)
    finally:
        review_stage.remove_review_stage(staged)


def _live_login(monkeypatch, tmp_path: Path) -> bytes:
    config = tmp_path / "login" / ".claude"
    config.mkdir(parents=True)
    (config / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": ACCESS, "expiresAt": 4_102_444_800_000, "scopes": ["user:inference"],
        "subscriptionType": "max"}}))
    os.chmod(config / ".credentials.json", 0o600)
    for key in list(os.environ):
        if sc.caller_supplied_credential({key: ""}):
            monkeypatch.delenv(key)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _seed_host_passes(tmp_path / "state")
    return ACCESS.encode()


def live_call_site(monkeypatch, tmp_path: Path, transport: str, *, widen=None):
    """`_default_spawn` -> `_parent_infer` -> `launch_jailed` -> the transport, in a real
    jail on the real seat-uid chain and egress namespace, with the login proof's real auth
    jail. Only the HARDEN broker's process boundary and its authorization bookkeeping are
    stand-ins (the broker runs the same `_parent_infer` in-process). ``widen(jail)`` is a
    failing control applied to the review jail just before the transport launches."""
    from test_seat_notices import _FakeBroker

    subject = _fake_subject(tmp_path)
    token = _live_login(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    digest = _staged_digest(repo, tmp_path)
    observed: dict[str, dict] = {}
    real_teardown = pi._seat_uid.teardown_in_h
    real_read = pi._seat_uid.read_in_h

    def teardown(holder, parent):
        out = os.path.join(parent, seat_jail.HOST_OUT_DIRNAME)
        for role in ("auth", "leg"):
            key = f"{Path(parent).name}:{role}"
            try:
                observed[key] = json.loads(real_read(holder, out, f"observed-{role}.json", 1 << 20))
            except Exception:
                pass
        return real_teardown(holder, parent)

    evidence_seen: list[dict] = []
    real_launch = ct.launch_jailed
    real_provider = pi.launch_provider

    def provider(argv, *, process_owner=(), **kwargs):
        if isinstance(process_owner, seat_jail.SeatJail):
            kinds = []
            for fd in process_owner.pass_fds:
                try:
                    target = os.readlink(f"/proc/self/fd/{fd}")
                except OSError:
                    target = "closed"
                kinds.append(target.split(":", 1)[0] if ":" in target else "file")
            launches.append({"argv0": list(argv)[:1], "pass_fd_kinds": sorted(kinds),
                             "auth": list(argv)[1:3] == ["auth", "status"]})
        return real_provider(argv, process_owner=process_owner, **kwargs)

    launches: list[dict] = []
    monkeypatch.setattr(pi, "launch_provider", provider)

    def launch(transport_name, seat, **kwargs):
        evidence_seen.append(kwargs["broker_evidence"])
        if widen is not None:
            widen(seat.jail)
        return real_launch(transport_name, seat, **kwargs)

    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", teardown)
    monkeypatch.setattr(pi._claude_seat_transport, "launch_jailed", launch)
    monkeypatch.setattr(pi, "_resolve_claude_executable", lambda: subject)
    monkeypatch.setattr(pi._seat_jail, "decide_seat_route", lambda leg, **k: seat_jail.SeatRoute(True))
    monkeypatch.setattr(pi._seat_jail_autoqualify, "ensure_qualified",
                        lambda leg: pi._seat_jail_autoqualify.Outcome("qualified"))
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12))
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: repo)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setenv(ct.ROUTE_ENV, transport)
    spawned = pi._default_spawn(
        "claude", "ARTIFACT", repo_dir=repo, mode="review", model="claude-opus-5-5",
        timeout_s=240, review_authorization=types.SimpleNamespace(staged_tree_sha256=digest),
        canonical_repo_authority=repo,
    )
    leg_launches = [launch for launch in launches if not launch["auth"]]
    observed["launch"] = leg_launches[-1] if leg_launches else {}
    return spawned, observed, (evidence_seen[0] if evidence_seen else {}), token


_PER_RUN_FLAGS = ("--session-id", "--name")


def _argv_shape(argv: list[str]) -> list[str]:
    out, skip = [], False
    for item in argv:
        if skip:
            out.append("<per-run>")
            skip = False
            continue
        out.append(item)
        skip = item in _PER_RUN_FLAGS
    return out


def boundary_violations(baseline: dict, other: dict, *, cli_delta: tuple[str, ...] = ()) -> list[str]:
    """What ``other`` (one transport's record at /seat/bin/claude) widens against the TUI
    ``baseline``: an environment variable, a descriptor, a mount, a tool or permission
    flag, or an argv token outside the transport's declared CLI delta."""
    problems = []
    if other.get("launch", {}).get("pass_fd_kinds") != baseline.get("launch", {}).get("pass_fd_kinds"):
        problems.append("pass_fds")
    if other.get("env") != baseline.get("env"):
        problems.append("environment")
    if other.get("fds") != baseline.get("fds"):
        problems.append("descriptors")
    if other.get("mounts") != baseline.get("mounts"):
        problems.append("mounts")
    if other.get("cwd") != baseline.get("cwd"):
        problems.append("cwd")
    for flag in ("--tools", "--permission-mode", "--setting-sources", "--settings",
                 "--mcp-config", "--agents", "--allowedTools", "--disallowedTools",
                 "--add-dir", "--model", "--effort"):
        def values(argv):
            return [argv[i + 1] for i, item in enumerate(argv[:-1]) if item == flag]
        if values(other.get("argv", [])) != values(baseline.get("argv", [])):
            problems.append(f"argv {flag}")
    base_shape = _argv_shape(baseline.get("argv", []))
    extra = [item for item in _argv_shape(other.get("argv", [])) if item not in base_shape]
    missing = [item for item in base_shape if item not in _argv_shape(other.get("argv", []))]
    if [item for item in extra if item not in cli_delta] or missing:
        problems.append("argv tokens")
    return problems


def _cli_delta(transport: str) -> tuple[str, ...]:
    if transport == "tui":
        return ()
    module = ct.transport_module(transport)
    return tuple(getattr(module, "CLI_DELTA", ()))


def _admitted_transports() -> list[str]:
    return ["tui", *(t for t in ("print", "sdk") if ct.transport_module(t) is not None)]


def test_live_jail_every_admitted_transport_holds_the_jail_boundary(monkeypatch, tmp_path):
    require_live_jail()
    records: dict[str, dict] = {}
    for transport in _admitted_transports():
        with monkeypatch.context() as m:
            base = tmp_path / transport
            base.mkdir()
            _spawned, observed, evidence, token = live_call_site(m, base, transport)
        leg = observed.get("seat:leg")
        auth = observed.get("seat-auth:auth")
        assert leg is not None, (transport, sorted(observed))
        assert auth is not None, (transport, sorted(observed))
        # The token pipe delivered exactly the login token, to the proof and to the launch.
        assert leg["token_sha256"] == auth["token_sha256"] == hashlib.sha256(token).hexdigest()
        assert leg["env"].get(seat_jail.CLAUDE_TOKEN_FD_ENV, "").isdigit()
        assert not any(token.decode() in value for value in leg["env"].values())
        assert not any(token.decode() in item for item in leg["argv"])
        assert "--bare" not in leg["argv"]
        assert evidence["claude_transport"] == transport
        records[transport] = {"leg": {**leg, "launch": observed["launch"]},
                              "digest": evidence.get("seat_jail_profile_digest")}
    baseline = records["tui"]
    for transport, record in records.items():
        assert record["digest"] == baseline["digest"] == seat_jail.jail_profile_digest("claude")
        assert boundary_violations(baseline["leg"], record["leg"],
                                   cli_delta=_cli_delta(transport)) == [], transport


def _add_env(jail):
    owner = list(jail.process_owner)
    at = owner.index("--clearenv") + 1
    owner[at:at] = ["--setenv", "SEAT_STUB_EXTRA", "1"]
    object.__setattr__(jail, "process_owner", tuple(owner))


def _add_pass_fd(jail):
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    os.set_inheritable(read_fd, True)
    object.__setattr__(jail, "pass_fds", (*jail.pass_fds, read_fd))


def _add_mount(jail):
    owner = list(jail.process_owner)
    at = owner.index("--remount-ro") if "--remount-ro" in owner else len(owner) - 1
    owner[at:at] = ["--ro-bind", "/etc/passwd", "/seat/stub-extra"]
    object.__setattr__(jail, "process_owner", tuple(owner))


def _change_digest(jail):
    object.__setattr__(jail, "profile_digest", "f" * 64)


WIDENINGS = {"environment": _add_env, "pass-fd": _add_pass_fd, "mount": _add_mount,
             "digest": _change_digest}


@pytest.mark.parametrize("widening", [*WIDENINGS, "tool", "descriptor"])
def test_live_jail_a_widening_stub_transport_fails(monkeypatch, tmp_path, widening):
    """Stub transports are failing controls only: each widens one thing at the real call
    site in a real jail, and the boundary must not hold for it (refused at launch, or its
    record differs from the TUI baseline)."""
    require_live_jail()
    with monkeypatch.context() as m:
        base = tmp_path / "baseline"
        base.mkdir()
        _s, observed, evidence, _t = live_call_site(m, base, "tui")
    baseline = {**observed["seat:leg"], "launch": observed["launch"]}

    def tool_stub(seat, **kwargs):
        real = pi._broker_claude_tui_command

        def widened(**kw):
            command = real(**kw)
            command[command.index("--tools") + 1] = "default,StubExtraTool"
            return command

        with pytest.MonkeyPatch.context() as inner:
            inner.setattr(pi, "_broker_claude_tui_command", widened)
            return pi._exec_jailed_claude_leg(seat, **kwargs)

    def descriptor_stub(seat, **kwargs):
        """A provider-visible descriptor: the transport's own argv opens one for the CLI."""
        real = pi._broker_claude_tui_command

        def wrapped(**kw):
            command = real(**kw)
            return ["/bin/sh", "-c", 'exec 7</etc/passwd; exec "$0" "$@"', *command]

        with pytest.MonkeyPatch.context() as inner:
            inner.setattr(pi, "_broker_claude_tui_command", wrapped)
            return pi._exec_jailed_claude_leg(seat, **kwargs)

    stubs = {"tool": tool_stub, "descriptor": descriptor_stub}
    with monkeypatch.context() as m:
        _install(m, "print", run=stubs.get(widening) or
                 (lambda seat, **kwargs: pi._exec_jailed_claude_leg(seat, **kwargs)))
        base = tmp_path / "stub"
        base.mkdir()
        spawned, observed, stub_evidence, _t = live_call_site(
            m, base, "print", widen=WIDENINGS.get(widening))
    record = observed.get("seat:leg")
    refused_at_launch = record is None
    if record is not None:
        record = {**record, "launch": observed["launch"]}
    widened = (refused_at_launch
               or boundary_violations(baseline, record) != []
               or stub_evidence.get("seat_jail_profile_digest") != evidence.get("seat_jail_profile_digest"))
    assert widened, (widening, tuple(spawned)[:3])
