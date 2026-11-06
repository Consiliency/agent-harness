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
        "claude_seat_token_in_output", "claude_seat_api_key_source",
        "claude_sdk_provenance_refused", "claude_sdk_worker_contract_violation",
        "claude_seat_login_unproven", "claude_seat_result_unproven", "claude_seat_stream_unsafe",
        "claude_sdk_dependency_unavailable", "claude_sdk_worker_unavailable"}
    security = {code for code, entry in ct.CODES.items() if entry[0] == ct.SECURITY}
    assert security == {"claude_seat_token_in_output", "claude_seat_api_key_source",
                        "claude_sdk_provenance_refused", "claude_sdk_worker_contract_violation"}
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


# --------------------------------------------------------------------------------------
# The W0 observation channel: what the bake-off kit reads of a native run.
# --------------------------------------------------------------------------------------

STAGED = "0123456789abcdef0123456789abcdef01234567"


def _observed_seat(tmp_path, commit=STAGED):
    stage = tmp_path / "stage"
    marker = stage / "reviewed-tree" / ".git" / "phase-loop-source-commit"
    marker.parent.mkdir(parents=True)
    marker.write_text(commit + "\n")
    jail = types.SimpleNamespace(profile_digest="d" * 64, dependency_projection_digest="",
                                 env={seat_jail.CLAUDE_TOKEN_FD_ENV: "3", "HOME": "/seat/home"})
    return types.SimpleNamespace(jail=jail, review_dir=stage, token=ACCESS.encode())


def _evidence_from_print(seat, **kwargs):
    kwargs["broker_evidence"].update({
        "claude_admission": {"outcome": "admitted", "code": "none"},
        "claude_api_key_source": "none", "claude_code_entrypoint": "unset",
        "sandbox_filesystem_confined": True, "claude_session_id_matches": True,
        "claude_result_count": 1, "provider_model": "claude-opus-5-5",
        "claude_item7_diagnostics": {"valid": True, "truncated": False, "model_status": "match",
                                     "tools": [{"path_sha256": "e" * 64, "read_completed": True,
                                                "name": "Read"}]},
        "provider_prompt_sha256": "f" * 64, "secret_text": ACCESS})
    return "OK", "the review " + ACCESS + "\n\nAGREE"


def test_a_w0_run_writes_one_closed_observation_per_launch(monkeypatch, tmp_path):
    _install(monkeypatch, "print", run=_evidence_from_print)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "observations.jsonl"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    monkeypatch.setenv(ct.W0_OBSERVATION_ENV, str(descriptor))
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: None)
    seat = _observed_seat(tmp_path)
    evidence: dict = {}
    try:
        assert ct.launch_jailed("print", seat, prove_login=lambda: PROVEN,
                                broker_evidence=evidence)[0] == "OK"
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, 1 << 20)
    finally:
        os.close(descriptor)
    assert ACCESS.encode() not in raw and b"review" not in raw
    assert path.stat().st_mode & 0o777 == 0o600
    (line,) = raw.splitlines()
    seen = json.loads(line)
    assert seen["schema"] == ct.W0_OBSERVATION_SCHEMA and seen["transport"] == "print"
    assert (seen["status"], seen["admission"], seen["code"]) == ("ok", "admitted", "none")
    assert seen["staged_source_commit"] == STAGED and seen["token_pipe"] is True
    assert seen["login_proof"] == [sc.SOURCE_LOGIN, "oauth_token", "none"]
    assert seen["jail_profile_digest"] == "d" * 64 and seen["read_path_sha256"] == ["e" * 64]
    assert "secret_text" not in seen and "provider_prompt_sha256" not in seen


def test_a_refused_w0_launch_is_observed_with_its_code(monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "observations.jsonl"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    monkeypatch.setenv(ct.W0_OBSERVATION_ENV, str(descriptor))
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: None)

    def refuse():
        raise ct.TransportRefused(sc.LOGIN_UNPROVEN)

    try:
        with pytest.raises(ct.TransportRefused):
            ct.launch_jailed("tui", _observed_seat(tmp_path, commit="HEAD"), prove_login=refuse,
                             broker_evidence={})
        os.lseek(descriptor, 0, os.SEEK_SET)
        seen = json.loads(os.read(descriptor, 1 << 20))
    finally:
        os.close(descriptor)
    assert (seen["status"], seen["code"], seen["admission"]) == ("refused", sc.LOGIN_UNPROVEN, None)
    assert seen["staged_source_commit"] is None  # no commit is claimed for an unreadable stage


@pytest.mark.parametrize("where", ["unset", "path", "pipe", "world-readable"])
def test_no_observation_is_written_without_the_parents_private_descriptor(
        monkeypatch, tmp_path, where):
    _install(monkeypatch, "print", run=_evidence_from_print)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: None)
    descriptors = ()
    output = tmp_path / "observation"
    if where == "path":
        monkeypatch.setenv(ct.W0_OBSERVATION_ENV, "observations.jsonl")
    elif where == "pipe":
        descriptors = os.pipe()
        monkeypatch.setenv(ct.W0_OBSERVATION_ENV, str(descriptors[1]))
    elif where == "world-readable":
        descriptor = os.open(output, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o644)
        os.fchmod(descriptor, 0o644)
        descriptors = (descriptor,)
        monkeypatch.setenv(ct.W0_OBSERVATION_ENV, str(descriptor))
    else:
        monkeypatch.delenv(ct.W0_OBSERVATION_ENV, raising=False)
    try:
        ct.launch_jailed("print", _observed_seat(tmp_path), prove_login=lambda: PROVEN,
                         broker_evidence={})
        if where == "world-readable":
            assert output.read_bytes() == b""
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def test_w0_parent_controls_are_not_inherited_by_a_provider_child(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def run_leg(command, **kwargs):
        captured["env"] = kwargs["env"]
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("review\nAGREE", encoding="utf-8")
        return pi._LegRun(0, "", "")

    review = tmp_path / "review"
    output = tmp_path / "output"
    review.mkdir()
    output.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin"),
        ct.W0_OBSERVATION_ENV: "9",
        ct.W0_LINEUP_ENV: '["codex:test:high:subscription"]',
    }
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run_leg)
    returncode, _review, _detail = pi._exec_leg(
        "codex", review, output, timeout_s=60, artifact="review", env=env)

    assert returncode == 0
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert ct.W0_OBSERVATION_ENV not in child_env
    assert ct.W0_LINEUP_ENV not in child_env


@pytest.mark.parametrize("marker", ["HEAD", "c" * 39, "../" + "c" * 40])
def test_a_staged_commit_marker_that_is_not_a_commit_is_not_observed(tmp_path, marker):
    assert ct._staged_source_commit(_observed_seat(tmp_path, commit=marker)) is None
    assert ct._staged_source_commit(types.SimpleNamespace(review_dir=None)) is None


def test_the_observation_reads_the_stage_tree_the_review_stage_writes():
    from phase_loop_runtime import review_stage

    assert ct._STAGE_TREE == review_stage.REVIEW_STAGE_TREE_DIRNAME


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


def _sdk_with_preflight(monkeypatch, preflight):
    module = _install(monkeypatch, "sdk")
    module.preflight = preflight
    return module


@pytest.mark.parametrize("code", ["claude_sdk_dependency_unavailable",
                                  "claude_sdk_provenance_refused",
                                  "claude_sdk_worker_unavailable"])
def test_the_sdk_worker_preflight_refuses_before_the_credential(monkeypatch, tmp_path, code):
    def preflight():
        raise ct.TransportRefused(code)

    _sdk_with_preflight(monkeypatch, preflight)
    read: list[object] = []
    monkeypatch.setattr(pi._seat_credentials, "resolve_claude_seat_credential",
                        lambda *a, **k: read.append(a) or (_ for _ in ()).throw(AssertionError))
    with pytest.raises(ct.TransportRefused) as caught:
        pi._prepare_jailed_claude(tmp_path, tmp_path / "seat", types.SimpleNamespace(), 1, 1,
                                  ("", ""), transport="sdk")
    assert caught.value.code == code
    assert read == [] and not (tmp_path / "seat").exists()


def test_the_sdk_preflight_runs_first_and_needs_no_dependency_session(monkeypatch, tmp_path):
    from phase_loop_runtime import executable_dependency_startup as eds

    events: list[str] = []
    _sdk_with_preflight(monkeypatch, lambda: events.append("preflight") or "the install")
    monkeypatch.setattr(eds, "current_dependency_for_provider", lambda provider: None)
    tree = tmp_path / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir()
    descriptor = seat_jail.open_dir_nofollow(tree)
    try:
        staged = seat_jail.tree_manifest_sha256_at(descriptor)
    finally:
        os.close(descriptor)

    class Reached(Exception):
        pass

    def credential(*_a, **_k):
        events.append("credential")
        raise Reached

    monkeypatch.setattr(pi._seat_credentials, "resolve_claude_seat_credential", credential)
    with pytest.raises(Reached):
        pi._prepare_jailed_claude(tmp_path, tmp_path / "seat",
                                  types.SimpleNamespace(staged_tree_sha256=staged), 1, 1, ("", ""),
                                  transport="sdk")
    assert events == ["preflight", "credential"]


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

    try:
        from ._seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready
    except ImportError:  # imported as a top-level module by a sibling test
        from _seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready

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


_STDIO = ("0", "1", "2")
#: bwrap binds the controlling terminal at /dev/console, so it belongs to the TUI's channel.
_TERMINAL_MOUNTS = frozenset({"/dev/console"})


def _past_stdio(record: dict) -> dict:
    return {fd: kind for fd, kind in (record.get("fds") or {}).items() if fd not in _STDIO}


def _stdio_channel(record: dict) -> str | None:
    """``terminal`` (all three on one pts) or ``pipe`` (three pipes); anything else is
    ``None``."""
    kinds = [(record.get("fds") or {}).get(fd) for fd in _STDIO]
    if all(isinstance(k, str) and k.startswith("/dev/pts/") for k in kinds) and len(set(kinds)) == 1:
        return "terminal"
    if kinds == ["pipe", "pipe", "pipe"]:
        return "pipe"
    return None


def _mounts(record: dict) -> list:
    return [m for m in record.get("mounts") or () if m not in _TERMINAL_MOUNTS]


#: Each transport's stdio channel at the CLI boundary.
STDIO_CHANNEL = {"tui": "terminal", "print": "pipe", "sdk": "pipe"}


def boundary_violations(baseline: dict, other: dict, *, cli_delta: tuple[str, ...] = ()) -> list[str]:
    """What ``other`` (one transport's record at /seat/bin/claude) widens against the TUI
    ``baseline``: an environment variable, a descriptor, a mount, a tool or permission
    flag, or an argv token outside the transport's declared CLI delta."""
    problems = []
    if other.get("launch", {}).get("pass_fd_kinds") != baseline.get("launch", {}).get("pass_fd_kinds"):
        problems.append("pass_fds")
    if other.get("env") != baseline.get("env"):
        problems.append("environment")
    # Stdio is each transport's declared channel (the TUI's terminal, print's pipes, see
    # `_stdio_channel`); every descriptor past it must be the same, i.e. the token pipe.
    if _past_stdio(other) != _past_stdio(baseline):
        problems.append("descriptors")
    if _stdio_channel(other) is None:
        problems.append("stdio")
    if _mounts(other) != _mounts(baseline):
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
        assert _stdio_channel(leg) == STDIO_CHANNEL[transport]
        assert list(_past_stdio(leg).values()) == ["pipe"]  # the token pipe, nothing else
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


# --------------------------------------------------------------------------------------
# IF-0-CLAUDE-3: the `sdk` host worker's launcher and duplex leg (SL-1). The worker and the
# bridge are SL-3's; these controls enter through the parent's own launch and I/O helpers.
# --------------------------------------------------------------------------------------

import test_seats_claude_sdk as sdk_tests  # noqa: E402

#: The sealed test install: SL-3's session fixture, bound here under this module's name.
sealed_install = sdk_tests.test_install

from phase_loop_runtime import claude_seat_sdk as sdk  # noqa: E402

#: The fake CLI's one result (tests/data/seats_claude_sdk/fake_cli.py).
_FAKE_RESULT = "VERDICT: approve\nNo blocking findings."
_ENTER_H = ["/usr/bin/nsenter", "--net", "--mount", "-t", "4242", "-U", "--preserve-credentials"]


def _prepared(sealed, payload=None):
    """The launch a preflight would prepare for the sealed test install."""
    payload = payload or {name: sdk.read_packaged(f"worker/{name}") for name in sdk.WORKER_PAYLOAD}
    return sdk.PreparedSdkLaunch(
        install=sealed.install, payload_bytes=dict(payload),
        bindings={f"payload:{name}": hashlib.sha256(data).hexdigest()
                  for name, data in payload.items()},
        directory=sealed.state, manifest_raw=sealed.manifest_raw)


def _worker_argv(sealed_install, *, worker_id=7):
    spec = sdk.worker_launch_spec(sealed_install.install)
    fds = {name: 20 + index for index, name in enumerate(sdk.WORKER_PAYLOAD)}
    return spec, pi._claude_sdk_worker_argv(spec, worker_id=worker_id, in_fd=11, out_fd=12,
                                            enter_h=_ENTER_H, payload_fds=fds)


def test_the_worker_launch_is_the_declared_sandbox(sealed_install):
    spec, argv = _worker_argv(sealed_install)
    worker = dict(sdk.sdk_cli_delta()["worker"])
    limits = worker["limits"]
    assert argv[:7] == [
        "/usr/bin/prlimit", f"--as={limits['memory_bytes']}", f"--nofile={limits['descriptors']}",
        f"--cpu={limits['cpu_seconds']}", f"--fsize={limits['file_bytes']}",
        f"--core={limits['core_bytes']}", "--"]
    keyring = pi._seat_uid.trusted_module_argv("phase_loop_runtime.seat_keyring_exec", "--")
    assert argv[7:7 + len(keyring)] == keyring
    at = 7 + len(keyring)
    assert argv[at:at + len(_ENTER_H)] == _ENTER_H
    bwrap = at + len(_ENTER_H)
    assert argv[bwrap] == seat_jail.BWRAP
    namespaces = list(worker["namespaces"])
    assert argv[bwrap + 1:bwrap + 1 + len(namespaces)] == namespaces
    assert "--unshare-net" in namespaces and "--die-with-parent" in namespaces
    end = argv.index("--", bwrap)
    sandbox = argv[bwrap:end]
    adds = [sandbox[i + 1] for i, item in enumerate(sandbox) if item == "--cap-add"]
    assert adds == list(seat_jail.JAIL_CAP_ADD)
    snapshot = str(sealed_install.install.snapshot)
    drop_tools = set(pi._claude_sdk_drop_tool_files(sealed_install.install.runtime_root).values())
    sources = [sandbox[i + 1] for i, item in enumerate(sandbox) if item == "--ro-bind"]
    assert sources and all(s.startswith(snapshot + "/") or s in drop_tools for s in sources)
    assert sandbox.count("--ro-bind-data") == len(sdk.WORKER_PAYLOAD)
    for i, item in enumerate(sandbox):
        if item == "--ro-bind-data":
            assert sandbox[i - 2:i] == ["--perms", "0444"]
    for path, size in worker["tmpfs"].items():
        assert ["--perms", "1777", "--size", str(size), "--tmpfs", path] == \
            sandbox[sandbox.index(path) - 5:sandbox.index(path) + 1]
    assert ["--remount-ro", "/"] == sandbox[sandbox.index("--remount-ro"):sandbox.index("--remount-ro") + 2]
    env = {sandbox[i + 1]: sandbox[i + 2] for i, item in enumerate(sandbox) if item == "--setenv"}
    assert env == worker["env"] and "--clearenv" in sandbox
    assert not any(re.search(r"TOKEN|KEY|SECRET|ANTHROPIC|PASSWORD", key) for key in env)
    inner = argv[end + 1:]
    drop = seat_jail.setpriv_drop(7)
    assert inner[:len(drop)] == drop
    rest = inner[len(drop):]
    assert rest[:7] == [spec.argv[0], "-I", "-S", "-B", "-c", pi._CLAUDE_SDK_WORKER_SETTLE, "7"]
    assert rest[7:9] == [str(limits["processes"]), "11,12"]
    assert rest[9:] == [*spec.argv, "11", "12"]


def test_a_worker_needs_the_seat_uid_holder(sealed_install, monkeypatch):
    spec = sdk.worker_launch_spec(sealed_install.install)
    for prefix in ((), ("/usr/bin/nsenter", "-t", "1", "-U"), ("/usr/bin/env",)):
        token = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
        try:
            with pytest.raises(ct.TransportRefused) as caught:
                pi._launch_claude_sdk_worker(spec, worker_id=3, prepared=_prepared(sealed_install))
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)
        assert caught.value.code == "claude_sdk_worker_unavailable"


def test_an_untrusted_drop_tool_refuses(sealed_install, monkeypatch, tmp_path):
    planted = tmp_path / "setpriv"
    planted.write_bytes((Path("/usr/bin/setpriv")).read_bytes()
                        if Path("/usr/bin/setpriv").exists() else b"\x7fELF")
    monkeypatch.setattr(pi, "_CLAUDE_SDK_WORKER_DROP_TOOL", str(planted))
    with pytest.raises(ct.TransportRefused) as caught:
        pi._claude_sdk_drop_tool_files(sealed_install.install.runtime_root)
    assert caught.value.code == "claude_sdk_worker_unavailable"


def test_the_settle_step_refuses_a_worker_that_kept_its_identity(tmp_path):
    marker = tmp_path / "ran"
    done = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", pi._CLAUDE_SDK_WORKER_SETTLE,
         str(os.getuid() + 1), "8", "", sys.executable, "-c", f"open({str(marker)!r}, 'w')"],
        capture_output=True, timeout=60)
    assert done.returncode == 96 and not marker.exists()


# -- the duplex leg at the real call site, with an unsandboxed worker ----------------------

def _unsandboxed_worker(tmp_path: Path) -> "pi._ClaudeSdkWorker":
    home, scratch = tmp_path / "worker-home", tmp_path / "worker-tmp"
    home.mkdir(exist_ok=True)
    scratch.mkdir(exist_ok=True)
    env = {**sdk.sdk_cli_delta()["worker"]["env"], "HOME": str(home), "TMPDIR": str(scratch)}
    parent_to_worker, worker_to_parent = os.pipe(), os.pipe()
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", str(sdk_tests.PAYLOAD / "claude_sdk_bootstrap.py"),
         str(parent_to_worker[0]), str(worker_to_parent[1])],
        pass_fds=(parent_to_worker[0], worker_to_parent[1]), env=env, cwd=scratch,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True)
    os.close(parent_to_worker[0])
    os.close(worker_to_parent[1])
    pi._anchor_process_group(process)
    pi._drain_bounded(process.stderr)
    return pi._ClaudeSdkWorker(process=process, read_fd=worker_to_parent[0],
                               feeder=pi._PipeFeeder(pi._fd_writer(parent_to_worker[1])),
                               worker_id=2)


def _duplex_leg(monkeypatch, tmp_path, sealed_install, *, mode="ok", cli=None, deadline_s=120.0,
                worker=None):
    """``_run_claude_sdk_leg`` with the fake CLI behind ``launch_provider``, the worker run
    unsandboxed (its own closure root seen at its real path), and the real bridge."""
    launched: list[list[str]] = []
    workers: list[object] = []

    def fake_launch(argv, *, process_owner, probe_owner, env, stdin, stdout, stderr,
                    start_new_session):
        launched.append(list(argv))
        script = cli if cli is not None else str(sdk_tests.FAKE_CLI)
        return subprocess.Popen([sys.executable, "-I", script, *argv[1:]],
                                env={**env, "FAKE_CLI_MODE": mode}, stdin=stdin, stdout=stdout,
                                stderr=stderr, start_new_session=start_new_session, cwd=tmp_path)

    def launch_worker(spec, *, worker_id, prepared):
        made = worker(tmp_path) if worker is not None else _unsandboxed_worker(tmp_path)
        workers.append(made)
        return made

    @contextlib.contextmanager
    def lease(count):
        yield 2

    monkeypatch.setattr(pi, "launch_provider", fake_launch)
    monkeypatch.setattr(pi, "_launch_claude_sdk_worker", launch_worker)
    monkeypatch.setattr(pi, "_claude_sdk_worker_count", lambda: 4)
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id", lease)
    install = sealed_install.install
    spec = sdk.worker_launch_spec(install)
    import dataclasses

    spec = dataclasses.replace(spec, read_only={str(install.closure_root): str(install.closure_root)})
    bridge = sdk.SDKBridge(token=sdk_tests.SEAT_TOKEN, session_id=sdk_tests.SESSION_ID,
                           prompt=pi._BROKER_CLAUDE_DIRECT_REQUEST + sdk_tests.PROMPT)
    seat = types.SimpleNamespace(jail=types.SimpleNamespace(seat_ids=(5, 5)), probe_jail=None)
    run = pi._run_claude_sdk_leg(
        sdk_tests.owned_argv(sdk.sdk_cli_delta()), spec=spec, bridge=bridge,
        prepared=_prepared(sealed_install), options=sdk_tests.leg_options(sdk.sdk_cli_delta()),
        cwd=tmp_path, env=sdk.cli_env(sdk_tests.fake_jail()), deadline_s=deadline_s, seat=seat)
    return run, bridge, launched, workers


def test_the_duplex_leg_admits_one_result_through_the_liveness_loop(monkeypatch, tmp_path,
                                                                     sealed_install):
    run, bridge, launched, workers = _duplex_leg(monkeypatch, tmp_path, sealed_install)
    assert bridge.outcome(run.returncode) == ("admitted", _FAKE_RESULT)
    assert bridge.worker_outcome == "result" and bridge.state == "ended"
    assert len(launched) == 1 and workers[0].process.poll() is not None


def test_a_bridge_stop_ends_the_duplex_leg(monkeypatch, tmp_path, sealed_install):
    run, bridge, _launched, workers = _duplex_leg(monkeypatch, tmp_path, sealed_install,
                                                  mode="inbound_control_request")
    assert bridge.outcome(run.returncode) == ("refused", sdk.CONTRACT_VIOLATION)
    assert run.returncode != 0 and workers[0].process.poll() is not None


def test_a_worker_that_never_readies_refuses_before_the_cli(monkeypatch, tmp_path, sealed_install):
    def silent(path):
        parent_to_worker, worker_to_parent = os.pipe(), os.pipe()
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        os.close(parent_to_worker[0])
        os.close(worker_to_parent[1])
        return pi._ClaudeSdkWorker(process=process, read_fd=worker_to_parent[0],
                                   feeder=pi._PipeFeeder(pi._fd_writer(parent_to_worker[1])),
                                   worker_id=2)

    launched: list = []
    monkeypatch.setattr(pi, "launch_provider", lambda *a, **k: launched.append(a))
    with pytest.raises(ct.TransportRefused) as caught:
        _duplex_leg(monkeypatch, tmp_path, sealed_install, worker=silent)
    assert caught.value.code == "claude_sdk_worker_unavailable"


def test_a_cli_that_never_answers_hits_the_deadline_and_both_trees_end(monkeypatch, tmp_path,
                                                                        sealed_install):
    silent = tmp_path / "silent_cli.py"
    silent.write_text("import sys, time\nfor _line in sys.stdin:\n    time.sleep(0)\n"
                      "time.sleep(600)\n")
    with pytest.raises(subprocess.TimeoutExpired):
        _duplex_leg(monkeypatch, tmp_path, sealed_install, cli=str(silent), deadline_s=5.0)


# -- live: the sandboxed worker in a seat-uid holder ---------------------------------------

def require_live_worker() -> None:
    """Skip only when PHASE_LOOP_REQUIRE_LIVE_JAIL is unset; with it set, a missing
    prerequisite fails the test."""
    from phase_loop_runtime import sandbox_egress

    try:
        from ._seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready
    except ImportError:
        from _seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready
    missing = []
    if not hasattr(os, "memfd_create"):
        missing.append("this interpreter has no os.memfd_create")
    if not seat_uid_ready():
        missing.append(SEAT_UID_PREREQUISITE)
    if not sandbox_egress.egress_isolation_available():
        missing.append("needs unshare + slirp4netns + iptables")
    for tool in (pi._PRLIMIT, seat_jail.BWRAP, pi._CLAUDE_SDK_WORKER_DROP_TOOL):
        if not os.access(tool, os.X_OK):
            missing.append(f"needs {tool}")
    if missing:
        message = "live worker unavailable: " + "; ".join(missing)
        if REQUIRE_LIVE:
            pytest.fail(message)
        pytest.skip(message)


@contextlib.contextmanager
def _seat_uid_holder():
    from phase_loop_runtime import sandbox_egress

    with sandbox_egress.isolated_network(timeout_s=None, required=True, seat_uid_map=True) as prefix:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
        try:
            yield prefix
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)


def _tree(pid: int) -> list[int]:
    found, pending = [], [pid]
    while pending:
        current = pending.pop()
        found.append(current)
        try:
            pending += [int(c) for c in Path(f"/proc/{current}/task/{current}/children")
                        .read_text().split()]
        except OSError:
            pass
    return found


def _status(pid: int) -> dict[str, str]:
    fields = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        key, _sep, value = line.partition(":")
        fields[key] = value.strip()
    return fields


def test_live_worker_runs_as_its_own_identity_and_is_reaped(sealed_install, monkeypatch):
    require_live_worker()
    install = sealed_install.install
    spec = sdk.worker_launch_spec(install)
    prepared = _prepared(sealed_install)
    # The packaged payload changes after the preflight: the worker still runs the verified
    # bytes, because the launcher never reopens the package.
    real_read = sdk.read_packaged
    monkeypatch.setattr(sdk, "read_packaged", lambda name, **k: (
        b"raise SystemExit(99)\n" if name.startswith("worker/") else real_read(name, **k)))
    with _seat_uid_holder():
        bridge = sdk.SDKBridge(token=sdk_tests.SEAT_TOKEN, session_id=sdk_tests.SESSION_ID,
                               prompt="the sealed prompt")
        with pi._seat_uid.lease_seat_id(pi._claude_sdk_worker_count()) as worker_id:
            worker = pi._launch_claude_sdk_worker(spec, worker_id=worker_id, prepared=prepared)
            try:
                closure = next(d for d, s in spec.read_only.items()
                               if Path(s) == install.closure_root)
                worker.send(bridge.hello(filter_program=spec.filter_program, roots=[closure],
                                         inventory=install.inventory,
                                         excluded=list(install.excluded),
                                         options=sdk_tests.leg_options(sdk.sdk_cli_delta())))
                assert pi._await_claude_sdk_ready(worker, bridge, 120.0), bridge.worker_failure
                tree = _tree(worker.process.pid)
                pythons = [p for p in tree if Path(f"/proc/{p}/comm").read_text().startswith("python")]
                assert len(pythons) == 1
                status = _status(pythons[0])
                host_uid = pi._seat_uid.subordinate_host_uid(worker_id)
                assert status["Uid"].split() == [str(host_uid)] * 4 != [str(os.getuid())] * 4
                assert all(int(status[k], 16) == 0
                           for k in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
                assert status["Seccomp"] == "2" and status["NoNewPrivs"] == "1"
                assert status["Groups"] == ""
                assert len(status["NSpid"].split()) >= 2  # its own PID namespace
                assert _status(worker.process.pid)["Uid"].split()[0] == str(os.getuid())
            finally:
                worker.terminate()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and any(Path(f"/proc/{p}").exists() for p in tree):
                time.sleep(0.1)
            assert not any(Path(f"/proc/{p}").exists() for p in tree)


def test_live_sdk_leg_admits_through_the_sandboxed_worker(monkeypatch, tmp_path, sealed_install):
    require_live_worker()

    real_launch = pi.launch_provider

    def fake_launch(argv, **kwargs):
        if "process_owner" not in kwargs:  # the holder's own infrastructure launches
            return real_launch(argv, **kwargs)
        return subprocess.Popen([sys.executable, "-I", str(sdk_tests.FAKE_CLI), *argv[1:]],
                                env=dict(kwargs["env"]), stdin=kwargs["stdin"],
                                stdout=kwargs["stdout"], stderr=kwargs["stderr"],
                                start_new_session=kwargs["start_new_session"], cwd=tmp_path)

    monkeypatch.setattr(pi, "launch_provider", fake_launch)
    install = sealed_install.install
    with _seat_uid_holder():
        bridge = sdk.SDKBridge(token=sdk_tests.SEAT_TOKEN, session_id=sdk_tests.SESSION_ID,
                               prompt=pi._BROKER_CLAUDE_DIRECT_REQUEST + sdk_tests.PROMPT)
        seat = types.SimpleNamespace(jail=types.SimpleNamespace(seat_ids=None), probe_jail=None)
        run = pi._run_claude_sdk_leg(
            sdk_tests.owned_argv(sdk.sdk_cli_delta()), spec=sdk.worker_launch_spec(install),
            bridge=bridge, prepared=_prepared(sealed_install),
            options=sdk_tests.leg_options(sdk.sdk_cli_delta()),
            cwd=tmp_path, env=sdk.cli_env(sdk_tests.fake_jail()), deadline_s=120.0, seat=seat)
    assert bridge.outcome(run.returncode) == ("admitted", _FAKE_RESULT)


def test_live_parent_death_reaps_the_worker(tmp_path, sealed_install):
    require_live_worker()
    state = sealed_install.state
    child = tmp_path / "board.py"
    child.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
        import test_seats_claude_sdk as T
        from phase_loop_runtime import claude_seat_sdk as sdk, panel_invoker as pi
        from phase_loop_runtime import sandbox_egress, seat_uid
        install = sdk.verify_install(__import__("pathlib").Path({str(state)!r}),
                                     manifest_raw=open({str(tmp_path / "manifest.json")!r}, "rb").read())
        spec = sdk.worker_launch_spec(install)
        with sandbox_egress.isolated_network(timeout_s=None, required=True, seat_uid_map=True) as prefix:
            pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
            bridge = sdk.SDKBridge(token=T.SEAT_TOKEN, session_id=T.SESSION_ID, prompt="p")
            with seat_uid.lease_seat_id(pi._claude_sdk_worker_count()) as worker_id:
                payload = {{n: sdk.read_packaged(f"worker/{{n}}") for n in sdk.WORKER_PAYLOAD}}
                prepared = sdk.PreparedSdkLaunch(install=install, payload_bytes=payload, bindings={{}})
                worker = pi._launch_claude_sdk_worker(spec, worker_id=worker_id, prepared=prepared)
                closure = next(d for d, s in spec.read_only.items() if s == str(install.closure_root))
                worker.send(bridge.hello(filter_program=spec.filter_program, roots=[closure],
                                         inventory=install.inventory, excluded=list(install.excluded),
                                         options=T.leg_options(sdk.sdk_cli_delta())))
                assert pi._await_claude_sdk_ready(worker, bridge, 120.0)
                print(worker.process.pid, flush=True)
                import time
                time.sleep(600)
    """))
    (tmp_path / "manifest.json").write_bytes(sealed_install.manifest_raw)
    board = subprocess.Popen([sys.executable, str(child)], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    try:
        line = board.stdout.readline()
        assert line.strip(), board.stderr.read()[-2000:]
        tree = _tree(int(line))
        assert any(Path(f"/proc/{p}/comm").read_text().startswith("python") for p in tree)
        os.killpg(board.pid, 9)
        board.wait(timeout=30)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and any(Path(f"/proc/{p}").exists() for p in tree):
            time.sleep(0.1)
        assert not any(Path(f"/proc/{p}").exists() for p in tree)
    finally:
        if board.poll() is None:
            os.killpg(board.pid, 9)
            board.wait()


# -- the review's repair round: prepared bytes, currency and ordering -----------------------

def test_the_launcher_seals_only_the_prepared_bytes(sealed_install, monkeypatch):
    """The packaged payload changes after the preflight: the memfds hold the verified bytes
    and the launcher never reopens the package."""
    spec = sdk.worker_launch_spec(sealed_install.install)
    prepared = _prepared(sealed_install)
    reopened, sealed = [], {}
    monkeypatch.setattr(sdk, "read_packaged", lambda name, **k: reopened.append(name) or b"x")
    real_memfd = seat_jail.memfd_with

    def memfd(name, data):
        sealed[name] = bytes(data)
        return real_memfd(name, data)

    monkeypatch.setattr(pi._seat_jail, "memfd_with", memfd)

    class Started:
        pid = os.getpid()
        stderr = None

    monkeypatch.setattr(pi.subprocess, "Popen", lambda *a, **k: Started())
    monkeypatch.setattr(pi, "_anchor_process_group", lambda process: None)
    monkeypatch.setattr(pi, "_drain_bounded", lambda pipe: None)
    monkeypatch.setattr(pi, "_claude_sdk_drop_tool_files", lambda root: {})
    token = pi._EGRESS_LAUNCH_PREFIX.set((*_ENTER_H, "/usr/bin/setpriv", "--"))
    try:
        worker = pi._launch_claude_sdk_worker(spec, worker_id=3, prepared=prepared)
    finally:
        pi._EGRESS_LAUNCH_PREFIX.reset(token)
    worker.feeder.close()
    os.close(worker.read_fd)
    assert reopened == []
    assert {name.removeprefix("claude-sdk-"): data for name, data in sealed.items()} == dict(
        prepared.payload_bytes)


def test_run_jailed_needs_the_seats_prepared_launch_and_never_rereads_it(sealed_install,
                                                                         monkeypatch):
    torn: list = []
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: torn.append(seat))
    prepared = _prepared(sealed_install)
    tampered = dataclasses_replace(prepared, payload_bytes={
        **prepared.payload_bytes, "claude_sdk_worker.py": b"# changed\n"})
    for value, code in ((None, sdk.WORKER_UNAVAILABLE), ("not-a-launch", sdk.WORKER_UNAVAILABLE),
                        (tampered, sdk.PROVENANCE_REFUSED)):
        sink: list = []
        seat = types.SimpleNamespace(jail=sdk_tests.fake_jail(), token=sdk_tests.SEAT_TOKEN,
                                     sdk_prepared=value)
        assert sdk.run_jailed(seat, timeout_s=1, backstop_s=1, model=None, effort=None,
                              prompt="p", broker_evidence={}, failure_detail_sink=sink) == (
            "DEGRADED", "")
        assert sink[0].template == code
    assert sdk.still_current(prepared) is prepared


def dataclasses_replace(value, **changes):
    import dataclasses

    return dataclasses.replace(value, **changes)


def test_the_real_spawn_runs_the_sdk_preflight_before_any_credential_read(monkeypatch, tmp_path):
    """Transport resolution, then the worker preflight, then the login-store read, then the
    credential (``_prepare_jailed_claude``), then the login proof and the launch."""
    from test_seat_login_wait_a3_1166 import _spawn

    events: list[str] = []
    prepared = object()
    module = _install(monkeypatch, "sdk", run=lambda seat, **k: events.append("launch") or (
        "OK", "a review\n\nAGREE"))
    module.preflight = lambda: events.append("preflight") or prepared
    real_wait = sc.LoginWait
    monkeypatch.setattr(sc, "LoginWait", lambda *a, **k: events.append("login-store") or real_wait(*a, **k))
    monkeypatch.setenv(ct.ROUTE_ENV, "sdk")

    def prepare(*_a, **kwargs):
        events.append("credential")
        assert kwargs["sdk_prepared"] is prepared
        return types.SimpleNamespace(notices=[])

    _spawned, calls = _spawn(
        monkeypatch, tmp_path, sc.LOGIN_READY, jailed_leg=lambda seat, **k: ("OK", "x"),
        prepare=prepare, login_proof=lambda seat, *a, **k: events.append("login-proof") or sc.LoginProof(
            sc.SOURCE_LOGIN, "oauth_token", "none"))
    assert events == ["preflight", "login-store", "credential", "login-proof", "launch"]


@pytest.mark.parametrize("code", ["claude_sdk_worker_unavailable", "claude_sdk_provenance_refused"])
def test_a_refused_sdk_preflight_at_the_spawn_reads_no_credential(monkeypatch, tmp_path, code):
    from test_seat_login_wait_a3_1166 import _spawn

    module = _install(monkeypatch, "sdk")

    def preflight():
        raise ct.TransportRefused(code)

    module.preflight = preflight
    monkeypatch.setattr(sc, "LoginWait", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setenv(ct.ROUTE_ENV, "sdk")
    spawned, calls = _spawn(monkeypatch, tmp_path, sc.LOGIN_READY,
                            jailed_leg=lambda seat, **k: ("OK", "x"))
    assert calls == {"prepare": 0, "launched": 0}
    assert tuple(spawned)[:2] == ("DEGRADED", "") and str(tuple(spawned)[2]) == code


def _modes_board():
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
    from phase_loop_runtime.advisor_board.schema import Board

    claude = next(seat for seat in DEFAULT_SEATS if seat.harness == "claude")
    return Board(name="claude-only", purpose="premerge-review", seats=(claude,))


def _modes(monkeypatch, events):
    from phase_loop_runtime import seat_jail_autoqualify as aq

    monkeypatch.setattr(aq, "ensure_qualified", lambda *a: aq.Outcome(aq.QUALIFIED))
    monkeypatch.setattr(aq, "recent_outcome", lambda digest: None)
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    monkeypatch.setattr(seat_jail, "decide_seat_route", lambda *a, **k: seat_jail.SeatRoute(True))
    monkeypatch.setattr(sc, "override_decision",
                        lambda *a, **k: events.append("credential") or types.SimpleNamespace(
                            applies=False, refusal=None, notice=None))
    monkeypatch.setattr(sc, "login_seconds_left", lambda margin: None)
    return pi._seat_launch_modes(_modes_board(), mode="review",
                                 review_authorization=types.SimpleNamespace(
                                     staged_tree_sha256="a" * 64),
                                 base_env={}, timeouts_by_leg={"claude": 300})


def test_seat_modes_refuse_an_unadmitted_sdk_before_any_credential(monkeypatch, none_admitted):
    events: list[str] = []
    monkeypatch.setenv(ct.ROUTE_ENV, "sdk")
    modes = _modes(monkeypatch, events)
    assert (modes[0].mode, modes[0].code) == ("degraded", ct.NOT_ADMITTED)
    assert events == []


def test_seat_modes_run_the_sdk_preflight_before_any_credential(monkeypatch):
    events: list[str] = []
    module = _install(monkeypatch, "sdk")
    module.preflight = lambda: events.append("preflight") or object()
    monkeypatch.setenv(ct.ROUTE_ENV, "sdk")
    modes = _modes(monkeypatch, events)
    assert modes[0].mode == "jailed"
    assert events[0] == "preflight" and set(events[1:]) == {"credential"}
    events.clear()

    def refused():
        events.append("preflight")
        raise ct.TransportRefused("claude_sdk_worker_unavailable")

    module.preflight = refused
    modes = _modes(monkeypatch, events)
    assert (modes[0].mode, modes[0].code) == ("degraded", "claude_sdk_worker_unavailable")
    assert events == ["preflight"]
