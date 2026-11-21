"""Lane L2c of the grok tool-surface plan: the board review leg consumes the frozen basis
(plans/artifacts/grok-tool-surface-contract-v1.md section 4.6, and BA-3 in section 10).

A grok leg whose form rests on a frozen-basis receipt runs in the ``grok-review`` proxy-only
namespace its board leg holds, composed with that proxy's projection and checked in full after
composition (``verify_launch_context``), and its final admission in ``launch_owned`` is bound
to the exact namespace holder and proxy the leg owns, by the measurement's own check
(``grok_tool_surface.bridged_to``, lane L2b, whose tests cover the function itself). Nothing
falls back to a broader namespace. No test contacts the vendor or runs a model.

- The end-to-end tests enter through ``_exec_leg`` for the ``sealed``, ``staged`` and
  ``review`` forms (``staged`` refused before spawn, erratum 8 item 1d), under the egress the board leg's setup holds
  (``_grok_board_leg_egress``), over the real launch-owner composition (``seat_profile`` plus
  ``launch_owned(PROVIDER_REVIEW)``), the real ``grok-review`` proxy, the proxy-only namespace
  and a loopback fixture upstream (lane L2a's), with a stand-in ``grok`` executable. They skip
  where those prerequisites are absent; ``PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1`` makes a missing
  prerequisite fail.
- The board-site tests drive ``_default_spawn`` with stand-ins below the egress choice: which
  egress the leg holds, and that a listing receipt keeps today's egress byte for byte.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import president_adapter as pa
from phase_loop_runtime import review_stage, sandbox_egress, seat_egress_proxy
from phase_loop_runtime.advisor_board import backing

from test_grok_measure_egress import (  # noqa: E402 - lane L2a's fixtures, reused as they are
    _host_reachable_listener, _namespace_or_skip, real_proxy_upstream,
)
from test_grok_tool_surface import (  # noqa: E402 - lane L1's record helpers, reused as they are
    HELP, VERSION, _publish_host, _route, _runner, _surface,
)
from test_grok_tool_surface_measure import (  # noqa: E402 - lane L2b's hosted-job rule
    WORKFLOW, required_upstream,
)

# Fixtures, used by name below: L2b's ``required_upstream`` is L2a's ``real_proxy_upstream``
# behind a missing layer failing, not skipping, in the hosted BA-3 job.
assert real_proxy_upstream and required_upstream

REFUSED = "grok_tool_surface_unverified"
INFERENCE_HOST = "cli-chat-proxy.grok.com"
INFERENCE_PATH = "/v1/chat/completions"
#: Erratum 8, item 1d: the forms a frozen-basis receipt admits at use.
ELIGIBLE_FORMS = ("sealed", "review")
PROJECTED_FILES = {".grok/agent_id", ".grok/auth.json", ".phase-loop-seat-egress-ca.pem"}
#: The projection plus the seat config of the contract's erratum 8.
HOME_FILES = PROJECTED_FILES | {gts.SEAT_CONFIG_RELATIVE}
HOME_DIRECTORIES = {".grok", ".config", ".cache", ".local", ".local/share"}


def _require(condition: bool, what: str) -> None:
    if condition:
        return
    if os.environ.get("PHASE_LOOP_REQUIRE_GROK_EGRESS_NS") == "1":
        pytest.fail(f"{what} is unavailable on a host that requires it")
    pytest.skip(f"{what} is unavailable")


def _prerequisites() -> None:
    _namespace_or_skip()
    _require(shutil.which("bwrap", path="/usr/bin:/bin") is not None, "bwrap")
    _require(shutil.which("git") is not None, "git")


# ---------------------------------------------------------------------- the leg and its host

_STAND_IN = r'''#!/usr/bin/python3 -I
import base64, errno, hashlib, json, os, socket, ssl, sys, urllib.parse
argv = sys.argv[1:]
if argv[-1:] == ["--help"]:
    sys.stdout.buffer.write(__HELP__)
    sys.exit(0)
if argv[-1:] == ["--version"]:
    sys.stdout.buffer.write(__VERSION__)
    sys.exit(0)
if "--prompt-file" in argv:
    sys.stdin.read()
host, path = "cli-chat-proxy.grok.com", "/v1/chat/completions"
try:
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    raw = socket.create_connection((proxy.hostname, proxy.port), 10)
    auth = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = raw.recv(4096)
        if not chunk:
            break
        head += chunk
    context = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: 2\r\n"
                    "Connection: close\r\n\r\n{}".encode())
        reply = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            reply += chunk
    proxied = reply.split(b"\r\n", 1)[0].decode("latin-1")
except (OSError, KeyError, ValueError) as exc:
    proxied = "error:" + type(exc).__name__
try:
    socket.create_connection(__DIRECT__, 3).close()
    direct = "connected"
except OSError as exc:
    direct = "refused:" + type(exc).__name__
home = os.environ.get("HOME", "/nonexistent")
entries = []
for root, dirs, files in os.walk(home):
    entries += [["dir", os.path.relpath(os.path.join(root, name), home)] for name in dirs]
    entries += [["file", os.path.relpath(os.path.join(root, name), home)] for name in files]
grok = os.path.join(home, ".grok")
path = os.path.join(grok, "config.toml")


def digest(name):
    try:
        with open(name, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        return "error:" + type(exc).__name__


def attempt(change):
    try:
        change()
        return "succeeded"
    except OSError as exc:
        return errno.errorcode.get(exc.errno, str(exc.errno))


def rename_over():
    temporary = os.path.join(grok, ".stand-in.tmp")
    with open(temporary, "wb") as handle:
        handle.write(b"replacement")
    try:
        os.rename(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


config = digest(path)
# Erratum 8, item 1f: what the read-only mount refuses to its own process.
boundary = {
    "append": attempt(lambda: open(path, "ab").close()),
    "truncate": attempt(lambda: os.truncate(path, 0)),
    "rename_over": attempt(rename_over),
    "unlink": attempt(lambda: os.unlink(path)),
    "chmod": attempt(lambda: os.chmod(path, 0o666)),
}
config_after = digest(path)
# The ancestor case: rename .grok itself, plant a replacement and look the path up again.
moved = grok + "-moved"
parent = attempt(lambda: os.rename(grok, moved))
if parent == "succeeded":
    os.makedirs(grok, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"replacement")
replaced = digest(path)
moved_config = digest(os.path.join(moved, "config.toml")) if parent == "succeeded" else None
print(json.dumps({"proxied": proxied, "direct": direct, "home": sorted(entries),
                  "config": config, "boundary": boundary, "config_after": config_after,
                  "parent_rename": {"rename": parent, "path": replaced, "moved": moved_config},
                  "env": sorted(os.environ), "pid": os.getpid()}))
print("AGREE")
sys.exit(0 if proxied.startswith("HTTP/1.1 200") and direct.startswith("refused") else 3)
'''


class Board:
    """The host of one board leg: a ``grok`` on the provider search path, a private state
    home, and an operator HOME holding the two files a grok seat projects (fabricated)."""

    def __init__(self, root: Path, patch):
        self.root = root
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self.binary = bin_dir / "grok"
        self.binary.write_bytes(b"\x7fELF grok 1.0.89 stand-in, never executed\n")
        self.binary.chmod(0o755)
        patch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
        patch.setenv("XDG_STATE_HOME", str(root / "state"))
        home = root / "operator"
        (home / ".grok").mkdir(parents=True)
        for name, body in (
                (".grok/auth.json", json.dumps({"https://accounts.x.ai/sign-in": {
                    "key": "fabricated-grok-bearer-l2c"}})),
                (".grok/agent_id", "fabricated-agent-l2c")):
            (home / name).write_text(body)
            (home / name).chmod(0o600)
        # Any fallback to the ambient HOME reads the fabricated one, never the operator's;
        # the installed egress layer stays where it is (it lives under the data home).
        patch.setenv("XDG_DATA_HOME", str(seat_egress_proxy._data_home()))
        patch.setenv("HOME", str(home))
        self.env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "LANG": "C.UTF-8"}

    @property
    def digest(self) -> str:
        return sha256(self.binary.read_bytes()).hexdigest()

    def install(self, *, direct) -> None:
        """The stand-in that is launched; its digest is the one the record names."""
        self.binary.write_text(_STAND_IN.replace("__HELP__", repr(HELP))
                               .replace("__VERSION__", repr(VERSION))
                               .replace("__DIRECT__", repr(tuple(direct))))
        self.binary.chmod(0o700)

    def leg(self, form: str, *, tree_files=()) -> tuple[Path, Path]:
        """``(review_dir, out_dir)`` as ``_default_spawn`` stages them; ``staged`` holds a
        real staged tree (with ``tree_files`` committed in it)."""
        review_dir = self.root / f"{form}-review"
        out_dir = self.root / f"{form}-out"
        review_dir.mkdir()
        out_dir.mkdir()
        for name, body in (("review-bundle.md", "REVIEW BUNDLE\n"),
                           ("review-instructions.md", "Review it.\n")):
            (review_dir / name).write_text(body)
            (review_dir / name).chmod(0o400)
        if form == "staged":
            _stage_tree(self.root / f"{form}-repo", review_dir, tree_files)
        return review_dir, out_dir

    def publish(self, *commands) -> None:
        """A host-local record for this binary measured on each argv, and a passing
        frozen-basis receipt for each, as ``seat-window probe-tools`` writes them."""
        _publish_host(_surface(self.digest, [_route(f"route-{index}", command)
                                             for index, command in enumerate(commands)]))
        for command in commands:
            receipt = pi.probe_grok_tools(command, allowed_tools=pi._grok_allowed_tools(command),
                                          runner=_runner())
            assert receipt["passed"] and receipt["basis"] == "frozen_measurement", receipt

    def withdraw(self) -> None:
        (pa.private_record_root() / gts.host_record_name(self.digest)).unlink()


@pytest.fixture
def board(tmp_path, monkeypatch):
    return Board(tmp_path, monkeypatch)


def _stage_tree(repo: Path, review_dir: Path, tree_files) -> Path:
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "config", "user.email", "t@e.st"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)
    (repo / "stats.py").write_text("x = 1\n", encoding="utf-8")
    for name in tree_files:
        (repo / name).write_text("{}\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "-c", "commit.gpgsign=false", "commit", "-qm", "c"], check=True)
    staged = review_stage.stage_review_tree(repo, repo.parent / (repo.name + "-scratch"))
    tree = review_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME
    staged.rename(tree)
    return tree


def _effort_args():
    return pi.render_seat_invocation("grok", pi.DEFAULT_LEG_MODELS["grok"], "high").effort_args


def _leg_command(form: str, review_dir: Path, out_dir: Path) -> list[str]:
    """The argv ``_exec_leg`` launches for ``form``, from its own builders and defaults."""
    if form == "review":
        return pi._grok_review_form(model=None, review_dir=review_dir, prompt="",
                                    grok_effort_args=_effort_args())
    return pi._brokered_grok_command(model=None, out_dir=out_dir,
                                     grok_effort_args=_effort_args(),
                                     staged_tree=pi._sandbox_in(review_dir))


def _exec_leg(board: Board, form: str, review_dir: Path, out_dir: Path):
    """``_exec_leg`` as the board leg calls it: brokered for ``sealed`` and ``staged``."""
    brokered = {} if form == "review" else {
        "broker_prompt": "Review the staged bundle.", "broker_evidence": {}}
    return pi._exec_leg("grok", review_dir, out_dir, 300, "REVIEW BUNDLE", "review", None,
                        env=dict(board.env), deadline_s=300, **brokered)


@contextlib.contextmanager
def _board_leg_egress():
    """What the board leg's egress setup in ``_default_spawn`` holds for a frozen-basis grok
    leg: ``_grok_board_leg_egress`` and its prefix as the leg's launch prefix."""
    with pi._grok_board_leg_egress(timeout_s=600.0) as prefix:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
        try:
            proxy, held = pi._GROK_LEG_EGRESS.get()
            assert held == tuple(prefix)
            yield proxy, tuple(prefix)
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)


@pytest.fixture
def owned_launches(monkeypatch):
    """Every owned seat launch that reaches the launch primitive (``launch_owned`` composes
    its command around the seat keyring helper); infrastructure launches are not counted."""
    seen: list[list[str]] = []
    real = pi.launch_provider

    def launch_provider(argv, **kwargs):
        if "/run/phase-loop-seat/keyring.py" in [str(word) for word in argv]:
            seen.append([str(word) for word in argv])
        return real(argv, **kwargs)
    monkeypatch.setattr(pi, "launch_provider", launch_provider)
    return seen


@contextlib.contextmanager
def _reachable_listener():
    """A host listener, first shown reachable from outside any namespace; on exit it is
    checked that nothing reached it since. In the hosted BA-3 job a host with no
    non-loopback IPv4 address fails here instead of skipping."""
    _require(any(":" not in value and not value.startswith("127.")
                 for value in sandbox_egress.host_addresses()), "a non-loopback IPv4 address")
    listener = _host_reachable_listener()
    try:
        address, port = listener.getsockname()[:2]
        socket.create_connection((address, port), 3).close()
        listener.accept()[0].close()  # reachable from outside the namespace
        yield address, port
        listener.setblocking(False)
        with pytest.raises(BlockingIOError):
            listener.accept()  # and nothing from inside reached it
    finally:
        listener.close()


def _skip_unless_owned(exc: BaseException) -> None:
    if os.environ.get("PHASE_LOOP_REQUIRE_GROK_EGRESS_NS") == "1":
        raise exc
    pytest.skip(f"this host cannot own a seat ({exc})")


# ------------------------------------------------- end to end through _exec_leg (contract §4.6)

@pytest.mark.parametrize("form", ELIGIBLE_FORMS)
def test_each_form_completes_through_exec_leg_under_the_grok_review_egress(
        board, required_upstream, owned_launches, live_seat_attempt, form):
    """The ``sealed`` brokered leg and the unbrokered ``review`` leg each complete through
    ``_exec_leg`` on a frozen-basis receipt (``staged`` is refused before spawn: erratum 8,
    item 1d). BA-3: one and the same unjailed child of the real launch-owner composition
    completes a request through the leg's own ``grok-review`` proxy to the fixture upstream
    and fails a direct connection to a host listener first shown reachable from outside the
    namespace; its home holds only the projection and the seat config, which the real
    launcher mounts read-only (erratum 8, item 1f)."""
    _prerequisites()
    upstream = required_upstream
    with _reachable_listener() as direct:
        board.install(direct=direct)
        review_dir, out_dir = board.leg(form)
        board.publish(_leg_command(form, review_dir, out_dir))
        try:
            with _board_leg_egress() as (proxy, prefix):
                assert gts.bridged_to(prefix, proxy)
                rc, text, log = _exec_leg(board, form, review_dir, out_dir)
        except sandbox_egress.SeatIdentityUnverified as exc:
            _skip_unless_owned(exc)
    assert rc == 0, log[-800:]
    result = json.loads(text.strip().splitlines()[0])
    assert text.strip().splitlines()[-1] == "AGREE"
    assert result["proxied"].startswith("HTTP/1.1 200"), result
    assert result["direct"].startswith("refused:"), result
    assert len(owned_launches) == 1  # one child, which did both
    assert [entry[1:3] for entry in upstream.requests] == [("POST", INFERENCE_PATH)]
    events = seat_egress_proxy.proxy_stream(proxy).outside_events
    assert [(event.method, event.host, event.path, event.decision) for event in events] == [
        ("POST", INFERENCE_HOST, INFERENCE_PATH, "allow")]
    assert {path for kind, path in result["home"] if kind == "file"} == HOME_FILES
    # The child reads the pinned bytes at the config's path, through the real launcher, and
    # cannot change them: the mount refuses every write, replacement and removal.
    assert result["config"] == result["config_after"] == gts.SEAT_CONFIG_SHA256
    boundary = result["boundary"]
    # A write by path meets the 0444 mode first (EACCES) or the read-only mount (EROFS).
    assert {boundary["append"], boundary["truncate"]} <= {"EACCES", "EROFS"}, boundary
    assert boundary["chmod"] == "EROFS", boundary
    assert (boundary["rename_over"], boundary["unlink"]) == ("EBUSY", "EBUSY"), boundary
    # The ancestor case is recorded, not relied on: when the parent can be renamed, the
    # mount moves with it, and the path claim holds only for forms with no writing tool.
    parent = result["parent_rename"]
    print("grok seat config, parent rename:", json.dumps(parent))
    if parent["rename"] == "succeeded":
        assert parent["moved"] == gts.SEAT_CONFIG_SHA256, parent
    else:
        assert parent["path"] == gts.SEAT_CONFIG_SHA256, parent
    assert {path for kind, path in result["home"] if kind == "dir"} <= HOME_DIRECTORIES
    assert {"HTTPS_PROXY", "SSL_CERT_FILE"} <= set(result["env"])
    assert not [key for key in result["env"] if key.startswith(("GROK_", "XAI_"))]


def test_the_clean_staged_leg_is_refused_before_spawn(board, required_upstream, owned_launches,
                                                     live_seat_attempt):
    """Contract §4.6 as erratum 8 amends it: the clean ``staged`` leg on a frozen-basis
    receipt, under the same egress, is an explicit refusal with no launch and no request."""
    _prerequisites()
    upstream = required_upstream
    with _reachable_listener() as direct:
        board.install(direct=direct)
        review_dir, out_dir = board.leg("staged")
        board.publish(_leg_command("staged", review_dir, out_dir))
        try:
            with _board_leg_egress() as (proxy, prefix):
                assert gts.bridged_to(prefix, proxy)
                outcome = _refusal(lambda: _exec_leg(board, "staged", review_dir, out_dir))
                assert seat_egress_proxy.proxy_stream(proxy).outside_events == ()
        except sandbox_egress.SeatIdentityUnverified as exc:
            _skip_unless_owned(exc)
    assert outcome == REFUSED
    assert owned_launches == []
    assert upstream.requests == []


def test_a_listing_receipt_keeps_its_launch_out_of_the_grok_review_egress(board, owned_launches,
                                                                         monkeypatch):
    """A leg on a listing receipt holds no grok-review egress and composes exactly as before:
    no proxy projection is asked for (its egress is today's, byte for byte)."""
    review_dir, out_dir = board.leg("sealed")
    command = _leg_command("sealed", review_dir, out_dir)
    pi.record_tool_probe(command, {"tools": [], "diagnostics": []},
                         allowed_tools=pi._grok_allowed_tools(command), version=VERSION.decode())
    composed = []
    real = pi._seat_command_profile

    def seat_command_profile(cmd, **kwargs):
        composed.append(sorted(kwargs))
        return real(cmd, **kwargs)
    monkeypatch.setattr(pi, "_seat_command_profile", seat_command_profile)

    class Stop(Exception):
        pass

    def isolated_network(**kwargs):
        raise Stop(kwargs)  # today's own fallback namespace: reached, as before
    monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
    with pytest.raises(Stop) as stopped:
        _exec_leg(board, "sealed", review_dir, out_dir)
    assert stopped.value.args[0] == {"timeout_s": None, "required": True}
    assert composed == [["cwd", "env", "gemini_profile"]]
    assert owned_launches == []


# ----------------------------------------------- each listed refusal launches nothing (§4.6)

def test_no_egress_layer_refuses_the_leg_before_anything_launches(board, monkeypatch,
                                                                  owned_launches):
    """The egress layer unavailable, or the allow-list missing: the board leg's egress
    setup refuses with the one public code and nothing launches; there is no fallback."""
    review_dir, out_dir = board.leg("sealed")
    board.publish(_leg_command("sealed", review_dir, out_dir))
    proxy = SimpleNamespace(socket="/run/fixture/proxy.sock")
    for layer, namespace in (
            (seat_egress_proxy.EgressLayerUnavailable("seat_egress_unavailable", "no srt here"),
             None),
            (seat_egress_proxy.EgressLayerUnavailable("seat_egress_unavailable",
                                                      "allowlist grok-review missing"), None),
            (None, sandbox_egress.EgressUnavailable("egress isolation unavailable"))):
        @contextlib.contextmanager
        def start_proxy(**kwargs):
            if layer is not None:
                raise layer
            yield proxy

        @contextlib.contextmanager
        def isolated_network(**kwargs):
            raise namespace
            yield  # pragma: no cover
        monkeypatch.setattr(seat_egress_proxy, "start_proxy", start_proxy)
        monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
        with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
            with _board_leg_egress():
                pytest.fail("the leg ran without its egress")
        assert refusal.value.code == REFUSED
    assert pi._GROK_LEG_EGRESS.get() is None and pi._EGRESS_LAUNCH_PREFIX.get() == ()
    assert owned_launches == []


@pytest.mark.parametrize("case", ["mcp_json_in_tree", "managed_config", "withdrawn_record",
                                  "fallback_namespace", "slirp_namespace"])
def test_each_listed_refusal_launches_nothing(board, required_upstream, owned_launches,
                                              monkeypatch, tmp_path, case):
    """Contract §4.6: a staged tree containing ``.mcp.json``, a managed-config file, a
    withdrawn record, and the same leg forced onto the fallback namespace (no proxy-only
    prefix: ``_run_leg_with_liveness``'s own; or a slirp one held in its place) each refuse
    with ``grok_tool_surface_unverified`` and launch nothing."""
    _prerequisites()
    upstream = required_upstream
    form = "staged" if case == "mcp_json_in_tree" else "sealed"
    managed = tmp_path / "etc-grok" / "managed_config.toml"
    if case == "managed_config":
        # The record and receipt are measured under the same (patched) context; the file
        # then appears on the host before the leg runs.
        monkeypatch.setattr(gts, "MANAGED_CONFIG_PATHS", (str(managed),))
    with _reachable_listener() as direct:
        board.install(direct=direct)
        review_dir, out_dir = board.leg(form, tree_files=(".mcp.json",) if form == "staged"
                                        else ())
        board.publish(_leg_command(form, review_dir, out_dir))
        if case == "managed_config":
            managed.parent.mkdir()
            managed.write_text("")
        if case == "withdrawn_record":
            board.withdraw()
        fallback = []
        real_isolated = sandbox_egress.isolated_network

        def isolated_network(*args, **kwargs):
            if kwargs.get("proxy_socket") is None:
                fallback.append(kwargs)
            return real_isolated(*args, **kwargs)
        monkeypatch.setattr(sandbox_egress, "isolated_network", isolated_network)
        try:
            if case == "fallback_namespace":
                outcome = _refusal(lambda: _exec_leg(board, form, review_dir, out_dir))
                assert fallback == []  # refused before its own namespace was taken
            elif case == "slirp_namespace":
                with sandbox_egress.isolated_network(timeout_s=300.0, required=True) as slirp:
                    token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(slirp))
                    try:
                        outcome = _refusal(lambda: _exec_leg(board, form, review_dir, out_dir))
                    finally:
                        pi._EGRESS_LAUNCH_PREFIX.reset(token)
            else:
                with _board_leg_egress() as (proxy, _prefix):
                    outcome = _refusal(lambda: _exec_leg(board, form, review_dir, out_dir))
                assert seat_egress_proxy.proxy_stream(proxy).outside_events == ()
        except sandbox_egress.EgressUnavailable as exc:
            _require(False, f"the namespace ({exc})")
    assert outcome == REFUSED
    assert owned_launches == []
    assert upstream.requests == []


def _refusal(run) -> str:
    """The leg's refusal code: a typed refusal raised through ``_exec_leg`` (which the board
    leg reports as ``DEGRADED``), or the early gate's own detail."""
    try:
        rc, _text, log = run()
    except pi._seat_jail.SeatSandboxRefused as exc:
        return exc.code
    assert rc != 0
    return str(log)


# --------------------------------------- BA-3: the final admission is bound to holder and proxy

def test_ba3_the_final_admission_is_bound_to_the_exact_holder_and_proxy(
        board, required_upstream, owned_launches, monkeypatch):
    """Two live ``grok-review`` egresses, A and B, of the same policy. A composed profile is
    admitted only with the pair the leg owns: a mark for holder A with proxy B, or holder B
    with proxy A, is refused by ``launch_owned`` on the binding itself, and so is A's own mark
    launched under B's prefix; the leg's final step refuses either pairing before it marks
    anything. The control: A's mark under A launches, and that one child reaches the fixture
    upstream through proxy A only and fails a direct connection."""
    _prerequisites()
    upstream = required_upstream
    judged: list[bool] = []
    real_bound = gts.bridged_to

    def bound(prefix, proxy):
        judged.append(real_bound(prefix, proxy))
        return judged[-1]
    monkeypatch.setattr(gts, "bridged_to", bound)
    with _reachable_listener() as direct:
        board.install(direct=direct)
        review_dir, out_dir = board.leg("sealed")
        command = _leg_command("sealed", review_dir, out_dir)
        board.publish(command)
        role = pi.SeatLaunchRole.PROVIDER_REVIEW
        try:
            with _board_leg_egress() as (proxy_a, prefix_a), \
                    pi._grok_review_egress(timeout_s=600.0) as (proxy_b, prefix_b):
                prefix_b = tuple(prefix_b)
                assert prefix_a != prefix_b and proxy_a.socket != proxy_b.socket
                assert gts.bridged_to(prefix_a, proxy_a)
                assert gts.bridged_to(prefix_b, proxy_b)
                assert not gts.bridged_to(prefix_a, proxy_b)
                assert not gts.bridged_to(prefix_b, proxy_a)

                def launch(profile, prefix):
                    token = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
                    judged.clear()
                    try:
                        with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
                            pi.launch_owned(owned, role=role, profile=profile, cwd=str(out_dir),
                                            env=dict(board.env), stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, start_new_session=True)
                        assert refusal.value.code == REFUSED
                    finally:
                        pi._EGRESS_LAUNCH_PREFIX.reset(token)
                    return judged

                for prefix, proxy in ((prefix_a, proxy_b), (prefix_b, proxy_a)):
                    token = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
                    try:
                        with pi._seat_command_profile(command, env=dict(board.env), cwd=out_dir,
                                                      grok_egress_proxy=proxy) as (owned, profile):
                            # The leg's own final step refuses the pairing outright.
                            with pytest.raises(pi._seat_jail.SeatSandboxRefused):
                                pi._grok_leg_final_check(profile, (proxy, prefix),
                                                         env=dict(board.env), cwd=out_dir)
                            # A mark issued for it anyway is refused at the final admission.
                            marked = gts.verify_launch_context(profile, env=dict(board.env),
                                                               cwd=out_dir, role=role, proxy=proxy)
                            assert gts.is_issued(marked.grok_launch_context)
                            # Every other condition held: the binding alone refused it.
                            assert launch(marked, prefix) == [False]
                    finally:
                        pi._EGRESS_LAUNCH_PREFIX.reset(token)
                with pi._seat_command_profile(command, env=dict(board.env), cwd=out_dir,
                                              grok_egress_proxy=proxy_a) as (owned, profile):
                    marked = pi._grok_leg_final_check(profile, (proxy_a, prefix_a),
                                                      env=dict(board.env), cwd=out_dir)
                    launch(marked, prefix_b)  # A's own mark, under another live holder
                    assert owned_launches == [] and upstream.requests == []
                    # The control: the pair the leg owns launches.
                    process = pi.launch_owned(owned, role=role, profile=marked, cwd=str(out_dir),
                                              env=dict(board.env), stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              start_new_session=True)
                    try:
                        out, err = process.communicate(input=b"Review it.", timeout=120)
                    finally:
                        pi._terminate_process_group(process)
        except sandbox_egress.SeatIdentityUnverified as exc:
            _skip_unless_owned(exc)
    assert process.returncode == 0, err[-800:]
    result = json.loads(out.decode().strip().splitlines()[0])
    assert result["proxied"].startswith("HTTP/1.1 200") and result["direct"].startswith("refused:")
    assert len(owned_launches) == 1
    assert [entry[1:3] for entry in upstream.requests] == [("POST", INFERENCE_PATH)]
    assert [(event.method, event.path, event.decision)
            for event in seat_egress_proxy.proxy_stream(proxy_a).outside_events] == [
        ("POST", INFERENCE_PATH, "allow")]
    assert seat_egress_proxy.proxy_stream(proxy_b).outside_events == ()


# ------------------------------------------ the board leg's egress setup (``_default_spawn``)

FAKE_PREFIX = ("/usr/bin/nsenter", "--net", "--mount", "-t", "4242", "-U", "--")
SLIRP_PREFIX = ("/usr/bin/nsenter", "--net", "--mount", "-t", "4343", "-U", "--")


class Site:
    """Stand-ins below the board leg's egress choice: the grok-review egress yields a fake
    proxy and prefix bound to each other, the slirp namespace a fake prefix, and the leg
    records what it was launched under. ``_exec_leg`` replaced is the injected seam, so
    ``_default_spawn`` runs the leg unbrokered: the ``review`` form."""

    def __init__(self, board: Board, patch):
        self.board = board
        self.proxy = SimpleNamespace(socket="/run/fixture/proxy.sock",
                                     process=SimpleNamespace(poll=lambda: None))
        self.calls: list[tuple] = []
        self.legs: list[dict] = []
        self.egress_failure: BaseException | None = None
        self.bound = True
        site = self

        @contextlib.contextmanager
        def grok_review_egress(*, timeout_s, request_budget=None):
            site.calls.append(("grok-review", timeout_s, request_budget))
            if site.egress_failure is not None:
                raise site.egress_failure
            yield site.proxy, FAKE_PREFIX

        @contextlib.contextmanager
        def isolated_network(*args, **kwargs):
            site.calls.append(("isolated_network", kwargs))
            yield list(SLIRP_PREFIX)

        def exec_leg(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
            site.legs.append({"prefix": tuple(pi._EGRESS_LAUNCH_PREFIX.get()),
                              "held": pi._GROK_LEG_EGRESS.get(),
                              "evidence": json.dumps(pi._sandbox_evidence(), default=str)})
            return 0, "AGREE", "log"

        patch.setattr(pi, "_grok_review_egress", grok_review_egress)
        patch.setattr(sandbox_egress, "isolated_network", isolated_network)
        patch.setattr(gts, "bridged_to",
                      lambda prefix, proxy: site.bound and proxy is site.proxy
                      and tuple(prefix) == FAKE_PREFIX)
        patch.setattr(pi, "_exec_leg", exec_leg)

    def receipt(self, kind: str) -> None:
        command = pi.grok_runtime_forms()["review"]
        if kind == "frozen_measurement":
            self.board.publish(command)
        else:
            receipt = pi.record_tool_probe(
                command, {"tools": sorted(pi._grok_allowed_tools(command)), "diagnostics": []},
                allowed_tools=pi._grok_allowed_tools(command), version=VERSION.decode())
            assert receipt["basis"] == "list_tools"

    def spawn(self, *, staged: bool):
        repo = self.board.root / "reviewed-repo"
        if not repo.exists():
            _stage_source(repo)
        options = {}
        if staged:
            options = {"review_authorization": _authorization(repo),
                       "canonical_repo_authority": repo}
        return pi._default_spawn("grok", "REVIEW BUNDLE BODY", repo_dir=repo, **options)


def _stage_source(repo: Path) -> None:
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "config", "user.email", "t@e.st"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "-c", "commit.gpgsign=false", "commit", "-qm", "c"], check=True)


def _authorization(repo: Path):
    return backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=review_stage.review_tree_manifest_sha256(repo),
    )


@pytest.fixture
def site(board, monkeypatch):
    _require(shutil.which("git") is not None, "git")
    return Site(board, monkeypatch)


@pytest.mark.parametrize("staged", [False, True], ids=["no_tree", "staged_tree"])
def test_the_board_leg_holds_the_grok_review_egress_for_a_frozen_basis(site, staged):
    """A frozen-basis grok leg holds the grok-review egress (no request budget) for the whole
    leg, in place of the slirp namespace a staged tree would take, and its leg is launched
    under that prefix with the pair held; the record names the proxy-only mechanism."""
    site.receipt("frozen_measurement")
    result = site.spawn(staged=staged)
    assert result[:2] == ("OK", "AGREE"), result
    timeout = float(pi._LEG_TIMEOUT_MAX_S) + 300.0
    assert site.calls == [("grok-review", timeout, None)]
    (leg,) = site.legs
    assert leg["prefix"] == FAKE_PREFIX and leg["held"] == (site.proxy, FAKE_PREFIX)
    if staged:
        assert "user-namespace+allowlisting-proxy" in leg["evidence"]
    assert pi._GROK_LEG_EGRESS.get() is None and pi._EGRESS_LAUNCH_PREFIX.get() == ()


@pytest.mark.parametrize("staged", [False, True], ids=["no_tree", "staged_tree"])
@pytest.mark.parametrize("kind", ["legacy_or_listing", "no_receipt"])
def test_a_grok_leg_without_a_frozen_basis_keeps_todays_egress(site, staged, kind):
    """Byte for byte: a staged tree takes today's slirp namespace with today's arguments, an
    unstaged leg holds none (its launch takes its own), and no grok-review egress is held."""
    if kind == "legacy_or_listing":
        site.receipt("list_tools")
    result = site.spawn(staged=staged)
    assert result[:2] == ("OK", "AGREE"), result
    timeout = float(pi._LEG_TIMEOUT_MAX_S) + 300.0
    assert site.calls == ([("isolated_network", {"timeout_s": timeout})] if staged else [])
    (leg,) = site.legs
    assert leg["held"] is None
    assert leg["prefix"] == (SLIRP_PREFIX if staged else ())


@pytest.mark.parametrize("staged", [False, True], ids=["no_tree", "staged_tree"])
@pytest.mark.parametrize("failure", ["layer_unavailable", "namespace_unavailable", "unbound"])
def test_a_board_leg_whose_grok_review_egress_fails_is_refused_with_no_fallback(site, staged,
                                                                                failure):
    """Any failure to hold the grok-review egress is ``grok_tool_surface_unverified``: the leg
    is DEGRADED, it never runs, and no slirp namespace is taken in its place."""
    site.receipt("frozen_measurement")
    if failure == "layer_unavailable":
        site.egress_failure = seat_egress_proxy.EgressLayerUnavailable(
            "seat_egress_unavailable", "fixture: no egress layer")
    elif failure == "namespace_unavailable":
        site.egress_failure = sandbox_egress.EgressUnavailable("fixture: no namespace")
    else:
        site.bound = False
    result = site.spawn(staged=staged)
    assert result[0] == "DEGRADED" and result[-1] == REFUSED, result
    assert site.legs == []
    assert [call[0] for call in site.calls] == ["grok-review"]


def test_the_board_decision_builds_the_form_the_leg_launches(board, monkeypatch):
    """The provisional step at the board site judges the argv ``_exec_leg`` will launch: for a
    brokered leg the ``sealed`` or ``staged`` form on the brokered model, for an unbrokered one
    the ``review`` form. Proved by recording only the argv ``_exec_leg`` actually built."""
    for brokered, form in ((True, "sealed"), (True, "staged"), (False, "review")):
        review_dir, out_dir = board.leg(form)
        model = (pi.harden_subscription_model("grok", pi.DEFAULT_LEG_MODELS["grok"], None)
                 if brokered else None)
        built = []
        with monkeypatch.context() as patch:
            def gate(command, env=None):
                built.append(list(command))
                return False
            patch.setattr(pi, "grok_tool_gate", gate)
            pi._exec_leg("grok", review_dir, out_dir, 300, "REVIEW BUNDLE", "review", model,
                         env=dict(board.env), deadline_s=300,
                         **({"broker_prompt": "P", "broker_evidence": {}} if brokered else {}))
        (command,) = built
        decide = dict(brokered=brokered, model=None, effort=None, env=dict(board.env),
                      review_dir=review_dir, out_dir=out_dir)
        assert pi._grok_leg_on_frozen_basis(**decide) is False  # no receipt yet
        board.publish(command)
        assert pi._grok_leg_on_frozen_basis(**decide) is True, form
        board.withdraw()
        assert pi._grok_leg_on_frozen_basis(**decide) is False  # a withdrawn record


# The workflow is repository source, not wheel or package data, so Gate A's copied
# standalone tree cannot evaluate this, as for the repository's CI-workflow tests. The
# hosted grok-egress-ns job runs this file in the full checkout, where it is present, and
# its junit check fails on any skip.
@pytest.mark.skipif(not WORKFLOW.is_file(),
                    reason="repo-only test workflow absent from standalone-from-wheel layout")
def test_the_hosted_ba3_job_runs_this_file_and_cannot_skip_green():
    """BA-3 binds lane L2c too: the hosted ``grok-egress-ns`` job (lane L2b), which sets
    PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1 and refuses any skip in its junit, runs this file."""
    import yaml

    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["grok-egress-ns"]
    steps = {step.get("name"): step for step in job["steps"]}
    run = steps["BA-3 isolation and fixture-upstream round trip (no skip)"]
    assert run["env"] == {"PHASE_LOOP_REQUIRE_GROK_EGRESS_NS": "1"}
    assert "tests/test_grok_board_leg_frozen_basis.py" in run["run"] and "none may" in run["run"]
