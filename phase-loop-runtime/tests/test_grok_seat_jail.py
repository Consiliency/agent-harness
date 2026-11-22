"""GROK SL-3: the jailed Grok leg, path-entered (SL-3.1 (a), (b), (d)-(h)).

Plan ``plans/phase-plan-v1-seats-GROK.md`` (SL-3, EC-GROK-1/2/3/5); frozen contract
``plans/artifacts/grok-jail-tool-surface-contract-v1.md`` §2.1, §2.3, §2.4, §4.4, §13 and
BA-J1, BA-J4 (SL-3 part), BA-J5.

Every launch here is a provider-free stand-in. The non-live cases enter through
``_seat_route_for_spawn``, ``_prepare_jailed_grok`` and ``_exec_jailed_grok_leg`` with only
the process start (``launch_provider``), the in-namespace helpers and the bridge proof
replaced; the spawn-boundary verifier runs for real. ``live_jail`` cases (``VL``) run a
Python stand-in as the dropped seat UID inside the jail ``_prepare_jailed_grok`` composes;
``jail_ns`` (``VJ``, BA-J1) adds the real ``grok-review`` proxy over a loopback fixture
upstream. No case runs grok, reads a real credential or dials an upstream.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from phase_loop_runtime import grok_jail_surface as gjs
from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_grok_credential as cred
from phase_loop_runtime import seat_jail, seat_profile_grok as grok

from test_grok_jail_surface import STAND_IN, _credential, _fabricated, _open_gate, _Proc
from test_grok_measure_egress import fake_srt, real_proxy_upstream  # the L2a harness

__all__ = ["fake_srt", "real_proxy_upstream"]  # fixtures, used by name below

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat jail")

REFUSED = "grok_tool_surface_unverified"
_REAL_RESOLVE = gjs.resolve_subject
REPO = Path(__file__).resolve().parents[2]


def _tree_manifest(tree: Path) -> str:
    fd = seat_jail.open_dir_nofollow(tree)
    try:
        return seat_jail.tree_manifest_sha256_at(fd)
    finally:
        os.close(fd)


def _stage(review: Path) -> str:
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True, mode=0o700)
    (tree / "README").write_text("the authorised stage\n", encoding="utf-8")
    (tree / "src").mkdir()
    (tree / "src" / "main.py").write_text("print('stage')\n", encoding="utf-8")
    return _tree_manifest(tree)


class _Board:
    """The window kit's leg runtime, recording its hook calls in one shared order."""

    def __init__(self, order: list):
        self.order, self.proxy, self.tool_steps = order, None, "unset"

    def start(self, seat, proxy, latch, command, prompt, authorization):
        self.order.append(("start", tuple(command)))
        return True

    def finish(self, seat, prefix, latch):
        self.order.append(("finish",))


@pytest.fixture
def leg(tmp_path, monkeypatch):
    """A jailed Grok seat composed by ``_prepare_jailed_grok`` over a stand-in subject and a
    fixture credential, with its gate opened by fixture records."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    review = tmp_path / "review"
    staged = _stage(review)
    authorization = SimpleNamespace(staged_tree_sha256=staged, instructions_sha256=None)
    binary = gjs.root_owned_digest(STAND_IN)
    table = dict(grok.JAIL_PROTECTION)
    table[binary] = table[grok.GROK_1_0_92_SHA256]
    monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
    monkeypatch.setattr(gjs, "resolve_subject",
                        lambda env=None: gjs.JailedSubject(STAND_IN, binary))
    tokens: dict[str, str] = {}

    def stage(config, *, margin_s):
        assert margin_s >= 300.0
        credential, token = _credential(Path(config), tokens.get("next"))
        tokens["token"] = token
        return credential

    monkeypatch.setattr(cred, "stage_grok_seat_credential", stage)
    ca_source = tmp_path / "proxy-ca.pem"
    ca_source.write_bytes(b"fixture proxy certificate\n")
    proxy = SimpleNamespace(
        process=_Proc(), allowlist_id="grok-review",
        allowlist_digest=pi._seat_egress_proxy.allowlist_ref("grok-review").content_digest,
        request_budget=None, socket=str(tmp_path / "proxy.sock"), ca_cert=ca_source,
        ca_sha256=hashlib.sha256(ca_source.read_bytes()).hexdigest(),
        proxy_url="http://srt:" + "p" * 24 + "@127.0.0.1:3128")
    holder = os.getpid()
    prefix = ("/usr/bin/nsenter", "-t", str(holder), "-U")
    reset = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
    monkeypatch.setattr(gts, "bridged_to", lambda p, px: tuple(p) == prefix and px is proxy)
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda pid, path: [])
    after: list = [None]
    monkeypatch.setattr(gjs, "after_check_in_h", lambda pid, home: after[0])
    launches: list = []
    order: list = []
    output = {"stdout": "reviewed the change\nVERDICT: AGREE\n", "stderr": ""}

    def launch_provider(argv, *, process_owner=None, probe_owner=None, **kwargs):
        launches.append((list(argv), process_owner))
        order.append(("spawn",))
        script = ("cat >/dev/null; printf '%s' \"$OUT\"; printf '%s' \"$ERR\" >&2")
        return subprocess.Popen(
            ["/bin/sh", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "OUT": output["stdout"], "ERR": output["stderr"]})

    monkeypatch.setattr(pi, "launch_provider", launch_provider)
    real_cleanup = pi._cleanup_jailed_seat
    monkeypatch.setattr(pi, "_cleanup_jailed_seat",
                        lambda seat, **k: (order.append(("cleanup",)), real_cleanup(seat, **k))[1])

    def prepare(*, sha=staged, open_gate=True, token=None):
        tokens["next"] = token
        seat = pi._prepare_jailed_grok(
            review, tmp_path / "base" / "seat", SimpleNamespace(staged_tree_sha256=sha),
            7, holder, ("bundle", "instructions"), proxy, deadline_s=60)
        if open_gate:
            launch = gjs.launch_digest(seat.jail, gjs.production_command(seat.jail.provider_argv0))
            _open_gate(binary, launch)
        return seat

    (tmp_path / "base").mkdir()
    yield SimpleNamespace(prepare=prepare, launches=launches, output=output, after=after,
                          order=order, review=review, authorization=authorization,
                          proxy=proxy, binary=binary, tokens=tokens, tmp=tmp_path)
    pi._EGRESS_LAUNCH_PREFIX.reset(reset)


def _staged_left(leg) -> list[str]:
    seat_dir = leg.tmp / "base" / "seat"
    return [str(path) for directory in (seat_dir, seat_dir / pi._JAIL_PROBE_DIRNAME)
            for name in (grok.HOST_GROK_CONFIG_DIRNAME, grok.HOST_GROK_MASKS_DIRNAME)
            if (path := directory / name).exists()]


def _run(seat, **kwargs):
    sink: list = []
    evidence: dict = {}
    status, text = pi._exec_jailed_grok_leg(
        seat, deadline_s=60, model=gjs.PRODUCTION_MODEL, effort=gjs.PRODUCTION_EFFORT,
        prompt="review the change", broker_evidence=evidence, failure_detail_sink=sink,
        **kwargs)
    return status, text, [failure.template for failure in sink], evidence


# --- The route (§4.2): L6 decides through ordinary routing ----------------------------------


def _resolve(monkeypatch, env):
    from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_jail_autoqualify

    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    monkeypatch.setattr(cred, "grok_seat_credential_present", lambda: True)
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    monkeypatch.setattr(seat_jail_autoqualify, "ensure_qualified",
                        lambda leg, **k: SimpleNamespace(qualified=True, reason=None))
    pi._JAILCORE_ROUTE_CACHE.clear()
    try:
        route, _notices, refusal = pi._seat_route_for_spawn(
            "grok", SimpleNamespace(staged_tree_sha256="0" * 64, instructions_sha256=None),
            eligible=True, env=env)
    finally:
        pi._JAILCORE_ROUTE_CACHE.clear()
    if route is not None and getattr(route, "lease", None) is not None:
        pi._release_seat_route(route)
    return route.decision, refusal


def test_the_route_stays_closed_at_l6_without_the_records(leg, monkeypatch):
    decision, refusal = _resolve(monkeypatch, {"PATH": "/usr/bin:/bin"})
    assert refusal == REFUSED
    assert [(s.step, s.outcome, s.code) for s in decision.steps] == [("L6", "failed", REFUSED)]


def test_the_route_passes_l6_only_with_all_five_conditions(leg, monkeypatch):
    leg.prepare()  # writes the records for this composition's launch digest
    from phase_loop_runtime import panel_invoker

    monkeypatch.setattr(panel_invoker, "_resolved_jail_subject", lambda name, env: (
        SimpleNamespace(subject_path=Path(STAND_IN), source="standalone"), None))
    monkeypatch.setattr(gjs, "resolve_subject", _REAL_RESOLVE)
    from phase_loop_runtime import seat_route

    monkeypatch.setattr(seat_route, "_projection_for_launch", lambda profile, env: None)
    assert gjs.precondition_code() is None
    decision, _refusal = _resolve(monkeypatch, {"PATH": "/usr/bin:/bin"})
    assert all(step.step != "L6" for step in decision.steps), decision.steps


# --- (a) the argv, (b) the copy, (c) BA-J2/BA-J3 at the leg -------------------------------


def test_a_the_jailed_argv_is_the_staged_form_with_cwd_seat_tree_and_no_host_path(leg):
    seat = leg.prepare()
    status, text, failures, evidence = _run(seat)
    assert (status, failures) == ("OK", []), failures
    assert text.endswith("VERDICT: AGREE\n")
    (argv, owner), = leg.launches
    assert owner is seat.jail
    assert tuple(argv) == gjs.production_command("/seat/bin/grok")
    assert argv[argv.index("--cwd") + 1] == "/seat/tree"
    assert argv[argv.index("--prompt-file") + 1] == "/dev/stdin"
    assert not any(str(leg.tmp) in word for word in argv)  # agent-harness#1460
    assert pi._grok_argv_digest(argv) == gjs.staged_argv_digest()
    # The operator-owned staged directory and mask sources are gone with the seat.
    assert _staged_left(leg) == []


def test_b_a_copy_differing_from_the_staged_tree_digest_refuses_before_anything(leg):
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        leg.prepare(sha="0" * 64, open_gate=False)
    assert caught.value.code == seat_jail.refused("stage_changed")
    assert leg.launches == [] and not (leg.tmp / "base" / "seat").exists()


def test_b_a_copy_changed_after_its_check_refuses_at_the_spawn(leg):
    seat = leg.prepare()
    (Path(seat.jail.tree_dir) / ".mcp.json").unlink()  # a stub removed after the check
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        _run(seat)
    assert caught.value.code == REFUSED and leg.launches == []
    assert _staged_left(leg) == []  # torn down all the same


@pytest.mark.parametrize("withheld", ["receipt", "record", "boundary", "confirmation"])
def test_c_the_leg_refuses_at_its_spawn_without_the_jailed_basis(leg, withheld):
    """BA-J2 (each condition), BA-J3 (no jailed receipt): the verifier refuses in the jailed
    branch of the spawn check and nothing starts. An unjailed listing receipt is present."""
    seat = leg.prepare(open_gate=False)
    launch = gjs.launch_digest(seat.jail, gjs.production_command(seat.jail.provider_argv0))
    _open_gate(leg.binary, launch, skip=(withheld,))
    gjs.write_private("grok-probe-" + leg.binary + "-" + gjs.staged_argv_digest() + ".json",
                      {"schema": "tool_probe.v1", "basis": "list_tools", "passed": True})
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        _run(seat)  # the dispatch types it DEGRADED with this code
    assert caught.value.code == REFUSED and leg.launches == []


def test_c_a_grok_argv_in_a_seat_jail_outside_the_leg_refuses(leg):
    seat = leg.prepare()
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
            pi._run_leg_with_liveness(
                list(gjs.production_command(seat.jail.provider_argv0)), cwd="/seat/tree",
                env=dict(seat.jail.env), deadline_s=30, input_text="x",
                seat_jail=seat.jail, probe_jail=seat.seat.probe_jail)
        assert caught.value.code == REFUSED and leg.launches == []
    finally:
        pi._cleanup_jailed_seat(seat.seat)
        pi._remove_grok_staged(seat.seat.seat_dir)


def test_c_another_seats_mark_does_not_admit_this_jail(leg):
    first = leg.prepare()
    token = pi._GROK_JAILED_LAUNCH.set((first, "board", None))
    try:
        import dataclasses

        lookalike = dataclasses.replace(first.jail)  # equal fields, another jail object
        with pytest.raises(seat_jail.SeatSandboxRefused):
            pi._grok_jailed_spawn_check(
                list(gjs.production_command(first.jail.provider_argv0)), lookalike,
                "/seat/tree")
    finally:
        pi._GROK_JAILED_LAUNCH.reset(token)
        pi._cleanup_jailed_seat(first.seat)
        pi._remove_grok_staged(first.seat.seat_dir)


# --- (d) the suffix scan before retention, and the refresh after-check --------------------


@pytest.mark.parametrize("shape", ["short", "long"])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("what", ["token", "suffix"])
def test_d_a_delivered_secret_or_its_suffix_in_output_retains_nothing(leg, shape, stream,
                                                                      what):
    token = ("fx" + os.urandom(5).hex()) if shape == "short" else _fabricated() * 3
    seat = leg.prepare(token=token)
    leaked = token if what == "token" else token[-12:]
    leg.output[stream] = f"config carried {leaked} here\nVERDICT: AGREE\n"
    status, text, failures, evidence = _run(seat)
    assert (status, text, failures) == ("DEGRADED", "", ["grok_seat_token_in_output"])
    assert leaked not in json.dumps(evidence, default=str)


def test_d_the_proxy_credential_in_output_retains_nothing(leg):
    seat = leg.prepare()
    leg.output["stdout"] = "p" * 24 + "\nVERDICT: AGREE\n"
    assert _run(seat)[2] == ["grok_seat_token_in_output"]


def test_d_a_new_credential_shaped_file_gives_the_refresh_code(leg):
    seat = leg.prepare()
    leg.after[0] = "grok_seat_token_refreshed_in_jail"
    status, text, failures, _evidence = _run(seat)
    assert (status, text, failures) == ("DEGRADED", "", ["grok_seat_token_refreshed_in_jail"])


def test_d_an_absent_seat_home_is_a_finding(tmp_path):
    """Review N-2: the caller runs the after-check before cleanup, so a seat-home H cannot
    see is a finding, never a clean pass."""
    assert gjs._after_main(str(tmp_path / "missing")) == 3


def test_n1_a_config_drift_refuses_typed_before_the_credential_is_staged(leg, monkeypatch):
    """Review N-1 (SL-1 N1): an E8-A drift that makes `seat_config()` raise its `_Refused`
    is `seat_profile_unavailable` at the launch site, before any credential is staged."""
    staged = []
    monkeypatch.setattr(cred, "stage_grok_seat_credential",
                        lambda *a, **k: staged.append(a) or 1 / 0)

    def drifted():
        raise gts._Refused("record refused")
    monkeypatch.setattr(gts, "seat_config", drifted)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        leg.prepare(open_gate=False)
    assert caught.value.code == "seat_profile_unavailable"
    assert staged == [] and leg.launches == []
    assert not (leg.tmp / "base" / "seat").exists()


@pytest.mark.parametrize("exc, code", [
    (ValueError("drift"), "seat_profile_unavailable"),
    (OSError("disk"), "seat_profile_unavailable"),
    (RuntimeError("other"), "grok leg local failure")])
def test_n1_the_dispatch_types_an_untyped_preparation_failure(exc, code):
    """Review N-1: the Grok dispatch's typed fallback, like Gemini's."""
    assert pi._jailed_grok_failure(exc).template == code


def test_n1_the_dispatch_keeps_propagating_what_gemini_propagates():
    for kind in pi._JAILED_GEMINI_PROPAGATES:
        assert issubclass(kind, BaseException)
    source = Path(pi.__file__).read_text(encoding="utf-8")
    hunk = source[source.index('if leg == "grok" and jailed:'):
                  source.index('if leg == "gemini" and jailed:')]
    assert "except _JAILED_GEMINI_PROPAGATES:" in hunk
    assert hunk.index("except _JAILED_GEMINI_PROPAGATES:") < hunk.index("except Exception")
    assert "_jailed_grok_failure(exc)" in hunk


def test_d_the_in_h_after_check_reads_seat_home(tmp_path):
    home = tmp_path / "seat-home"
    (home / ".grok-rw" / "sessions").mkdir(parents=True)
    assert gjs._after_main(str(home)) == 0
    (home / ".grok-rw" / "sessions" / "auth.json").write_text("{}")
    assert gjs._after_main(str(home)) == 3
    unreadable = home / ".grok-rw" / "x"
    unreadable.mkdir()
    os.chmod(unreadable, 0)
    try:
        (home / ".grok-rw" / "sessions" / "auth.json").unlink()
        assert gjs._after_main(str(home)) == 3  # an entry it cannot inspect fails closed
    finally:
        os.chmod(unreadable, 0o700)


# --- (h) the window kit's hooks, in Gemini's order (§13) ------------------------------------


def test_h_the_hook_calls_run_in_geminis_order(leg):
    seat = leg.prepare()
    board = _Board(leg.order)
    status, _text, failures, _evidence = _run(
        seat, window_board=board, quiescence_latch=pi._ProviderQuiescenceLatch(),
        review_authorization=leg.authorization)
    assert (status, failures) == ("OK", [])
    command = gjs.production_command("/seat/bin/grok")
    assert leg.order == [("start", command), ("spawn",), ("finish",), ("cleanup",)]
    assert board.tool_steps is None


def test_h_a_refused_start_spawns_nothing_and_still_cleans_up(leg):
    seat = leg.prepare()
    board = _Board(leg.order)
    board.start = lambda *a: leg.order.append(("start",)) or False
    status, _text, failures, _evidence = _run(
        seat, window_board=board, quiescence_latch=pi._ProviderQuiescenceLatch(),
        review_authorization=leg.authorization)
    assert (status, failures) == ("DEGRADED", ["seat_sandbox_refused:watch_unavailable"])
    assert leg.order == [("start",), ("finish",), ("cleanup",)] and leg.launches == []


# --- live_jail (VL): the real composed jail, a stand-in as the dropped seat UID -----------

_LIVE_PROBE = r'''
import errno, hashlib, json, os, sys
config = json.loads(sys.argv[1])
out = {"uid": os.getuid(), "rows": {}, "denied": {}, "allowed": {}, "relook": {}}

def attempt(table, name, fn):
    try:
        fn()
        table[name] = "ok"
    except OSError as exc:
        table[name] = errno.errorcode.get(exc.errno, str(exc.errno))

def kind(path):
    if not os.path.lexists(path):
        return "absent"
    if os.path.islink(path):
        return "link"
    if os.path.isdir(path):
        return "dir:" + ",".join(sorted(os.listdir(path)))
    with open(path, "rb") as handle:
        return "file:" + hashlib.sha256(handle.read()).hexdigest()

for path in config["rows"]:
    out["rows"][path] = kind(path)
for path in config["create"]:
    def create(path=path):
        if path.endswith("/"):
            os.mkdir(path.rstrip("/"))
        else:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    attempt(out["denied"], "create:" + path, create)
for path in config["write"]:
    attempt(out["denied"], "write:" + path, lambda path=path: open(path, "ab").close())
for path in config["rename"]:
    attempt(out["denied"], "rename:" + path, lambda path=path: os.rename(path, path + "-moved"))
    out["relook"][path] = kind(path)
with open("/seat/tree/canary", "wb") as handle:
    handle.write(config["canary"].encode())
attempt(out["allowed"], "tree", lambda: open("/seat/tree/src/main.py", "ab").close())
with open("/seat/home/.grok/logs/client.log", "w") as handle:
    handle.write("token suffix " + config["suffix"] + "\n")
print(json.dumps(out))
'''


def _require_live():
    if os.environ.get("PHASE_LOOP_REQUIRE_LIVE_JAIL") != "1":
        pytest.skip("set PHASE_LOOP_REQUIRE_LIVE_JAIL=1 on a jail-capable host")
    from phase_loop_runtime import sandbox_egress, seat_uid

    missing = [reason for reason, ok in (
        (seat_uid.PREREQUISITE, seat_uid.seat_uid_available()),
        ("egress isolation unavailable", sandbox_egress.egress_isolation_available()),
        ("seat sandbox unavailable", seat_jail.seat_sandbox_capable() is None)) if not ok]
    if missing:
        pytest.fail("live jail unavailable: " + "; ".join(missing))


def _contains(root: Path, needles) -> list[str]:
    hits = []
    for directory, _dirs, files in os.walk(root):
        for name in files:
            try:
                data = (Path(directory) / name).read_bytes()
            except OSError:
                continue
            if any(needle in data for needle in needles):
                hits.append(str(Path(directory) / name))
    return hits


def _in_jail(seat, script: str, argument: dict, *, timeout: int = 120):
    pi._require_canonical_jail(seat.jail)
    prefix = pi._compose_seat_jail_prefix(seat.jail)
    return subprocess.run(
        [*prefix, "/usr/bin/python3", "-I", "-c", script, json.dumps(argument)],
        capture_output=True, text=True, timeout=timeout, pass_fds=seat.jail.pass_fds,
        env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)


def _live_seat(tmp_path, monkeypatch, *, proxy=None):
    """``_prepare_jailed_grok`` over the stand-in subject and a fixture credential, inside a
    real seat-uid namespace; yields ``(seat, n, holder, review, token)``."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(gjs, "resolve_subject", lambda env=None: gjs.JailedSubject(
        STAND_IN, gjs.root_owned_digest(STAND_IN)))
    token = _fabricated()
    monkeypatch.setattr(cred, "stage_grok_seat_credential",
                        lambda config, *, margin_s: _credential(Path(config), token)[0])
    review = tmp_path / "review"
    staged = _stage(review)
    if proxy is None:
        ca = tmp_path / "ca.pem"
        ca.write_bytes(b"stand-in certificate\n")
        proxy = SimpleNamespace(ca_cert=ca, proxy_url="http://srt:fixture@127.0.0.1:3128")
    return review, staged, token, proxy


@pytest.fixture
def stage_copy(tmp_path):
    return tmp_path


def test_live_jail_b_ba_j4_ba_j5_masks_write_confinement_and_retention(tmp_path, monkeypatch):
    """(b) EC-GROK-1, BA-J5 and BA-J4 (SL-3 part) in the jail the leg composes, as the
    actual seat UID: every §2.4 row has its treatment on the actual mount view; creating
    any fixed input or discovery path fails; renaming ``.grok``, ``.config`` or a tree
    mask's parent fails and the re-looked-up path still finds the mask; the copy is
    writable and the write lands only in it; the stage, a sibling tree and the staged
    ``.grok`` are unchanged; the planted suffix and the credential are retained nowhere."""
    _require_live()
    from phase_loop_runtime import sandbox_egress, seat_uid

    review, staged, token, proxy = _live_seat(tmp_path, monkeypatch)
    # The authorised stage the per-launch copy was made from (the leg stages a copy per
    # launch; this test's copy is `review/reviewed-tree`).
    source = tmp_path / "source"
    _stage(source)
    assert _tree_manifest(source / seat_jail.HOST_TREE_DIRNAME) == staged
    sibling = tmp_path / "sibling"
    _stage(sibling)
    sibling_digest = _tree_manifest(sibling / seat_jail.HOST_TREE_DIRNAME)
    base = tmp_path / "base"
    base.mkdir()
    canary = os.urandom(8).hex()
    home_absent = [f"/seat/home/.grok/{name}" for scope, name, treatment in
                   grok.JAIL_PROTECTION[grok.GROK_1_0_92_SHA256]
                   if treatment == grok.ABSENT_IN_READ_ONLY_DOTDIR
                   for name in [name.split("/", 1)[1]]]
    rows = [*home_absent, "/etc/grok/managed_config.toml", "/etc/grok/requirements.toml",
            "/etc/claude-code/managed-settings.json", "/seat/home/.grok/config.toml",
            *(f"/seat/home/{path}" for path, _t in grok.HOME_MASKS),
            *(f"/seat/tree/{path}" for path, _t in grok.TREE_MASKS)]
    create = ["/seat/home/.grok/requirements.toml", "/seat/home/.grok/managed_config.toml",
              "/seat/home/.grok/staged/", "/seat/home/.grok/skills/", "/seat/home/.grok/agents/",
              "/seat/home/.grok/hooks/", "/seat/home/.grok/commands/",
              "/seat/home/.grok/mcp_preferences.json", "/seat/home/.config/grove/x",
              "/seat/home/.claude/x", "/seat/tree/.grok/x", "/seat/tree/.claude/x",
              "/seat/tree/.agents/x", "/seat/tree/.cursor/x"]
    write = ["/seat/home/.claude.json", "/seat/home/.mcp.json", "/seat/tree/.mcp.json"]
    rename = ["/seat/home/.grok", "/seat/home/.config", "/seat/tree/.grok", "/seat/tree/.claude"]
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=300, required=True,
                                            seat_uid_map=True) as egress:
        reset = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        holder = seat_uid.holder_pid_from_prefix(egress)
        seat = pi._prepare_jailed_grok(
            review, base / "seat", SimpleNamespace(staged_tree_sha256=staged), n, holder,
            ("bundle", "instructions"), proxy, deadline_s=60)
        try:
            staged_before = {name: (Path(seat.jail.gemini_config_dir) / name).read_bytes()
                             for name in ("config.toml", "auth.json", "agent_id")}
            done = _in_jail(seat, _LIVE_PROBE, {"rows": rows, "create": create, "write": write,
                                                "rename": rename, "canary": canary,
                                                "suffix": token[-12:]})
            staged_after = {name: (Path(seat.jail.gemini_config_dir) / name).read_bytes()
                            for name in staged_before}
            copy_canary = seat_uid.read_in_h(holder, seat.jail.tree_dir, "canary", 64)
            refreshed = gjs.after_check_in_h(holder, str(seat.seat.seat_dir / "seat-home"))
        finally:
            pi._cleanup_jailed_seat(seat.seat)
            pi._remove_grok_staged(seat.seat.seat_dir)
            pi._EGRESS_LAUNCH_PREFIX.reset(reset)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["uid"] == n and n != 0
    empty_dir, empty_file = "dir:", "file:" + hashlib.sha256(b"").hexdigest()
    for path in home_absent + ["/etc/grok/managed_config.toml", "/etc/grok/requirements.toml",
                               "/etc/claude-code/managed-settings.json"]:
        assert result["rows"][path] == "absent", path
    assert result["rows"]["/seat/home/.grok/config.toml"] == "file:" + gts.SEAT_CONFIG_SHA256
    for scope_root, masks in (("/seat/home/", grok.HOME_MASKS), ("/seat/tree/", grok.TREE_MASKS)):
        for path, treatment in masks:
            expected = empty_dir if treatment == grok.MASKED_DIRECTORY else empty_file
            assert result["rows"][scope_root + path] == expected, path
    assert {name: code for name, code in result["denied"].items() if code == "ok"} == {}
    for path in rename:
        assert result["relook"][path].startswith("dir:"), path
    assert result["allowed"] == {"tree": "ok"}
    # EC-GROK-1: the write is in the per-launch copy only.
    assert refreshed is None
    assert staged_after == staged_before
    assert copy_canary == canary.encode()
    assert not (review / seat_jail.HOST_TREE_DIRNAME).exists()  # the copy went with the seat
    assert _tree_manifest(source / seat_jail.HOST_TREE_DIRNAME) == staged
    assert not (source / seat_jail.HOST_TREE_DIRNAME / "canary").exists()
    assert _tree_manifest(sibling / seat_jail.HOST_TREE_DIRNAME) == sibling_digest
    needles = (token[-12:].encode(), token.encode())
    assert _contains(tmp_path, needles) == []


# --- (f) live_jail and (g) BA-J1 jail_ns: egress from inside the real jail ----------------

_EGRESS_PROBE = r'''
import base64, json, os, socket, ssl, sys, urllib.parse
config = json.loads(sys.argv[1])
url = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
auth = base64.b64encode(f"{url.username}:{url.password}".encode()).decode()
out = {"connect": {}, "direct": None, "allowed": None}

def tunnel(host):
    raw = socket.create_connection((url.hostname, url.port), timeout=20)
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = raw.recv(4096)
        if not chunk:
            break
        head += chunk
    return raw, head.split(b"\r\n", 1)[0].decode(errors="replace")

for host in config["refused"]:
    raw, status = tunnel(host)
    raw.close()
    out["connect"][host] = status
if config.get("inference"):
    raw, status = tunnel(config["inference"])
    if status.startswith("HTTP/1.1 200"):
        context = ssl.create_default_context(cafile="/seat/egress-ca.pem")
        context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        with context.wrap_socket(raw, server_hostname=config["inference"]) as tls:
            tls.sendall((f"POST {config['path']} HTTP/1.1\r\nHost: {config['inference']}\r\n"
                         "Content-Length: 0\r\nConnection: close\r\n\r\n").encode())
            out["allowed"] = tls.recv(64).split(b"\r\n", 1)[0].decode(errors="replace")
    else:
        out["allowed"] = status
try:
    socket.create_connection((config["direct_host"], config["direct_port"]), timeout=5).close()
    out["direct"] = "connected"
except OSError as exc:
    out["direct"] = type(exc).__name__
print(json.dumps(out))
'''


def _host_address() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # no packet is sent: routing only
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _egress_case(tmp_path, monkeypatch, upstream):
    """One child of the real Grok jail, behind the real ``grok-review`` proxy (port-443
    dials go to the loopback fixture upstream), with a host-reachable listener."""
    from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_uid

    from test_grok_measure_egress import INFERENCE_HOST, INFERENCE_PATH
    from test_grok_seat_egress import _hosts

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", 0))
    listener.listen(4)
    address, port = _host_address(), listener.getsockname()[1]
    socket.create_connection((address, port), timeout=5).close()  # proven reachable first
    refused = ["seat-egress-unlisted.invalid", *_hosts("gemini")[:2], *_hosts("codex")[:2]]
    try:
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review") as proxy:
            review, staged, _token, proxy = _live_seat(tmp_path, monkeypatch, proxy=proxy)
            (tmp_path / "base").mkdir()
            uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
            gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
            with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
                    sandbox_egress.isolated_network(
                        timeout_s=300, required=True, seat_uid_map=True,
                        proxy_socket=proxy.socket,
                        proxy_port=seat_egress_proxy.SEAT_PROXY_PORT) as egress:
                reset = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
                holder = seat_uid.holder_pid_from_prefix(egress)
                seat = pi._prepare_jailed_grok(
                    review, tmp_path / "base" / "seat",
                    SimpleNamespace(staged_tree_sha256=staged), n, holder,
                    ("bundle", "instructions"), proxy, deadline_s=60)
                try:
                    assert gts.bridged_to(egress, proxy)
                    done = _in_jail(seat, _EGRESS_PROBE, {
                        "refused": refused, "inference": INFERENCE_HOST, "path": INFERENCE_PATH,
                        "direct_host": address, "direct_port": port})
                finally:
                    pi._cleanup_jailed_seat(seat.seat)
                    pi._remove_grok_staged(seat.seat.seat_dir)
                    pi._EGRESS_LAUNCH_PREFIX.reset(reset)
    finally:
        listener.close()
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    return result, refused, upstream


def test_live_jail_f_a_jailed_tool_command_reaches_no_unlisted_or_other_vendor_host(
        tmp_path, monkeypatch, real_proxy_upstream):
    """(f) EC-GROK-3: a command run inside the real jail reaches neither an unlisted host
    nor a Gemini or Codex listed host through the jail's only uplink, and cannot dial out
    directly."""
    _require_live()
    result, refused, upstream = _egress_case(tmp_path, monkeypatch, real_proxy_upstream)
    for host in refused:
        assert result["connect"][host].startswith("HTTP/1.1 403"), (host, result)
    assert result["direct"] != "connected"
    assert all(request[0] not in refused for request in upstream.requests)


def test_jail_ns_ba_j1_one_child_allowed_through_the_proxy_and_refused_direct(
        tmp_path, monkeypatch, real_proxy_upstream):
    """BA-J1 (VJ): one child of the real Grok jail shows an allowed request through the
    proxy reaching the fixture upstream and a refused direct connection to a listener the
    host reaches. Mandatory hosted check: a missing prerequisite fails."""
    if os.environ.get("PHASE_LOOP_REQUIRE_GROK_JAIL_NS") != "1":
        pytest.skip("set PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1 (hosted BA-J1)")
    os.environ.setdefault("PHASE_LOOP_REQUIRE_LIVE_JAIL", "1")
    _require_live()
    from test_grok_measure_egress import INFERENCE_HOST, INFERENCE_PATH

    result, _refused, upstream = _egress_case(tmp_path, monkeypatch, real_proxy_upstream)
    assert result["allowed"].startswith("HTTP/1.1 200"), result
    assert (INFERENCE_HOST, "POST", INFERENCE_PATH, INFERENCE_HOST) in upstream.requests
    assert result["direct"] != "connected"


# --- Evidence: plans/evidence/seat-grok/write-confinement.json ------------------------------

EVIDENCE = REPO / "plans" / "evidence" / "seat-grok" / "write-confinement.json"


def test_the_write_confinement_record_holds_ids_and_current_digests():
    if not EVIDENCE.exists():
        pytest.skip("plans/evidence is outside this checkout (Gate A clean room)")
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert record["schema"] == "phase_loop_seat_grok_write_confinement.v1"
    assert record["redaction"] == "metadata_only" and record["provider_turns"] == 0
    assert record["context"] == gjs.JAIL_CONTEXT
    assert record["jail_context_digest"] == {
        grok.GROK_1_0_92_SHA256: gjs.jail_context_digest(grok.GROK_1_0_92_SHA256)}
    assert record["jail_profile_digest"] == {
        arch: seat_jail.jail_profile_digest("grok", arch) for arch in ("x86_64", "aarch64")}
    ids = [item["evidence_id"] for item in record["evidence"]]
    assert ids == ["grok-write-confinement", "grok-mask-protection", "grok-jailed-egress"]
    for item in record["evidence"]:
        for selector in item["proven_by"]:
            path, _sep, name = selector.partition("::")
            assert (REPO / path).exists(), selector
            source = (REPO / path).read_text(encoding="utf-8")
            assert f"def {name}(" in source, selector


# --- Verifier placement (president ruling on agent-harness#2088): nothing between the mark
# --- and the spawn alters the argv or the jail -----------------------------------------------


def test_the_spawn_gets_exactly_the_argv_and_jail_the_verifier_marked(leg, monkeypatch):
    """The verifier runs immediately before `launch_provider`; the SDK-region identity probe
    inside it can only add refusals. This pins that the object spawned is the object marked:
    the same jail (identity, owner argv, descriptors, env), the same argv, and the mark still
    admits them at the spawn."""
    seat = leg.prepare()
    marked = []
    real_verify = gjs.verify_jail_launch_context

    def verify(jail, **kwargs):
        context = real_verify(jail, **kwargs)
        marked.append((context, jail, tuple(kwargs["command"]), kwargs["cwd"],
                       tuple(jail.process_owner), tuple(jail.pass_fds), dict(jail.env)))
        return context

    monkeypatch.setattr(gjs, "verify_jail_launch_context", verify)
    status, _text, failures, _evidence = _run(seat)
    assert (status, failures) == ("OK", [])
    (context, jail, command, cwd, owner, fds, env), = marked
    (argv, spawned_owner), = leg.launches
    assert spawned_owner is jail is seat.jail
    assert tuple(argv) == command == context.command
    assert (tuple(spawned_owner.process_owner), tuple(spawned_owner.pass_fds),
            dict(spawned_owner.env)) == (owner, fds, env)
    assert gjs.admits(context, spawned_owner, argv, cwd)


def test_live_jail_d_the_after_check_through_the_real_nsenter_path(tmp_path, monkeypatch):
    """Review N-2, positive case: a credential-shaped file the stand-in writes as the seat
    UID gives `grok_seat_token_refreshed_in_jail` through the real in-H after-check; a
    clean home passes and a home H cannot see is a finding."""
    _require_live()
    from phase_loop_runtime import sandbox_egress, seat_uid

    review, staged, _token, proxy = _live_seat(tmp_path, monkeypatch)
    base = tmp_path / "base"
    base.mkdir()
    write = ("import os\n"
             "open('/seat/home/.grok-rw/auth.json', 'w').write("
             "'{\"https://accounts.x.ai/sign-in\": {\"key\": \"' + 'k' * 24 + '\"}}')\n"
             "print('written')\n")
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=300, required=True,
                                            seat_uid_map=True) as egress:
        reset = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        holder = seat_uid.holder_pid_from_prefix(egress)
        seat = pi._prepare_jailed_grok(
            review, base / "seat", SimpleNamespace(staged_tree_sha256=staged), n, holder,
            ("bundle", "instructions"), proxy, deadline_s=60)
        home = str(seat.seat.seat_dir / seat_jail.HOST_HOME_DIRNAME)
        try:
            before = gjs.after_check_in_h(holder, home)  # the composed, unlaunched home
            pi._require_canonical_jail(seat.jail)
            done = subprocess.run([*pi._compose_seat_jail_prefix(seat.jail), "/usr/bin/python3",
                                   "-I", "-c", write], capture_output=True, text=True,
                                  timeout=120, pass_fds=seat.jail.pass_fds,
                                  env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
            after = gjs.after_check_in_h(holder, home)
            missing = gjs.after_check_in_h(holder, home + "-not-there")
        finally:
            pi._cleanup_jailed_seat(seat.seat)
            pi._remove_grok_staged(seat.seat.seat_dir)
            pi._EGRESS_LAUNCH_PREFIX.reset(reset)
    assert done.returncode == 0 and "written" in done.stdout, done.stderr[-2000:]
    assert before is None
    assert after == "grok_seat_token_refreshed_in_jail"
    assert missing == "grok_seat_token_refreshed_in_jail"


def test_the_seat_and_probe_directories_are_private_under_a_permissive_umask(leg):
    """Hosted runners use umask 022: every directory the launch site creates for the stager
    (the seat directory and the probe jail's) is 0700 whatever the umask, so the stager's
    privacy check passes without being relaxed."""
    previous = os.umask(0o022)
    try:
        seat = leg.prepare()
    finally:
        os.umask(previous)
    try:
        for directory in (seat.seat.seat_dir, seat.seat.seat_dir / pi._JAIL_PROBE_DIRNAME):
            assert os.stat(directory).st_mode & 0o777 == 0o700, directory
    finally:
        pi._cleanup_jailed_seat(seat.seat)
        pi._remove_grok_staged(seat.seat.seat_dir)
