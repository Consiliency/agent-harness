"""Contract erratum 8 r3, item 5: the grok client's own log holds the token's last 12
characters, and a seat process can copy that text into a retained channel. These tests run a
stand-in grok through the real composed launches (measurement, rehearsal and board leg) and
plant a synthetic credential's suffix (or the whole value) where a child could put it:
stdout, stderr, a file in its working directory, the definitions artifact and a file under
``.grok/sessions``. No vendor CLI runs and no provider is called; the upstream is lane L2a's
fixture.

What each retained path may hold:

- ``provider.log`` (a failed measurement or rehearsal): the child's raw stdout and stderr,
  classified secret-bearing, private, 0600 and expiring (contract §5.9). A copy may land
  there and nowhere else.
- the definitions artifact: scanned for every registered value before it is retained or
  read, so a copy there is ``artifact_refused`` and nothing is kept.
- the board's returned text, private leg logs, outputs and ``leg_exec.v1`` record: the seat
  redactions, which include the suffix.
- the host-backed sessions scratch: removed by the launch's own cleanup, or by ``--purge``
  once abandoned.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import president_adapter as pa
from phase_loop_runtime import sandbox_egress

from test_grok_tool_surface_measure import (
    GROK_1_0_89, GROK_1_0_92, HELP, REQUIRE_NS, VERSION, Bench, _files, _namespace_or_skip,
    _require_bwrap, _route_rows, _tools,
)
from test_grok_tool_surface_measure import (  # the measurement's fixtures, used by name
    bench, real_proxy_upstream, required_upstream,
)

assert bench and real_proxy_upstream and required_upstream

#: The two credential shapes of item 5: a secret of 12 characters or fewer is its own
#: suffix; one well over 24 has a separate 12-character suffix.
SHORT_SECRET = "Wq5Ty8Lp3Zx"  # 11
LONG_SECRET = "fabricated-grok-bearer-e8b-redistribution-" + "Hn4Jd7Rc2Vb9"

_STAND_IN = r'''#!/usr/bin/python3 -I
import base64, json, os, socket, ssl, sys, urllib.parse
argv = sys.argv[1:]
if argv[-1:] == ["--help"]:
    sys.stdout.write(__HELP__)
    sys.exit(0)
if argv[-1:] == ["--version"]:
    sys.stdout.write(__VERSION__)
    sys.exit(0)
if "--prompt-file" in argv:
    sys.stdin.read()
home = os.environ["HOME"]
with open(os.path.join(home, ".grok", "auth.json")) as handle:
    node = json.load(handle)
while isinstance(node, dict):
    node = node["key"] if "key" in node else next(iter(node.values()))
planted = node if __VALUE__ == "full" else node[-12:]
copies = __COPIES__
# As grok 1.0.92 does: the token's last 12 characters, into its own log.
os.makedirs(os.path.join(home, ".grok", "logs"), exist_ok=True)
with open(os.path.join(home, ".grok", "logs", "unified.jsonl"), "a") as handle:
    for _ in range(5):
        handle.write(json.dumps({"event": "auth", "key_prefix": node[-12:]}) + "\n")
host = "cli-chat-proxy.grok.com"

def request(method, path):
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
        # A body only on a POST, as grok sends: a GET carries none. (A GET with a declared
        # body is teed by srt but reaches the filter bodyless, so the refusal cannot drain
        # it, and on Node 22 the cancelled in-flight branch ends the proxy.)
        body = "{}" if method == "POST" else ""
        framing = f"Content-Length: {len(body)}\r\n" if body else ""
        tls.sendall(f"{method} {path} HTTP/1.1\r\nHost: {host}\r\n{framing}"
                    f"Connection: close\r\n\r\n{body}".encode())
        reply = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            reply += chunk
    return reply.split(b"\r\n", 1)[0].decode("latin-1")

for method, path in __BEFORE__:
    try:
        request(method, path)
    except OSError:
        pass
try:
    proxied = request("POST", "/v1/chat/completions")
except OSError as exc:
    proxied = "error:" + type(exc).__name__
session = os.path.join(home, ".grok", "sessions", "-encoded-cwd", "session-0001")
os.makedirs(session)
tools = [{"type": "function", "function": {
    "name": name, "parameters": {},
    "description": ("echo " + planted) if "definitions" in copies else "fixture"}}
    for name in __TOOLS__]
with open(os.path.join(session, "tool_definitions.json"), "w") as handle:
    json.dump(tools, handle)
if "session_file" in copies:
    with open(os.path.join(session, "transcript.jsonl"), "w") as handle:
        handle.write(json.dumps({"tool_result": planted}) + "\n")
if "output" in copies:
    cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
    try:
        with open(os.path.join(cwd, "review-notes.md"), "w") as handle:
            handle.write("notes " + planted + "\n")
    except OSError as exc:
        print("output not written:", type(exc).__name__, file=sys.stderr)
print("provider says:", proxied)
if "stdout" in copies:
    print("the log said", planted)
if "stderr" in copies:
    print("stderr copy", planted, file=sys.stderr)
print("AGREE")
sys.exit(__EXIT__)
'''


def _stand_in(*, tools, copies, value="suffix", exit_code=0, before=()):
    return (_STAND_IN.replace("__HELP__", repr(HELP)).replace("__VERSION__", repr(VERSION))
            .replace("__TOOLS__", repr(tools)).replace("__EXIT__", str(exit_code))
            .replace("__VALUE__", repr(value)).replace("__COPIES__", repr(set(copies)))
            .replace("__BEFORE__", repr(list(before))))


def _plant(home: Path, secret: str) -> None:
    auth = home / ".grok" / "auth.json"
    auth.unlink()
    auth.write_text(json.dumps({"key": secret}))
    auth.chmod(0o600)


def _planted(secret: str, value: str) -> bytes:
    return (secret if value == "full" else secret[-12:]).encode()


def _carrying(needle: bytes, *roots: Path) -> list[Path]:
    return sorted(path for root in roots if root.exists() for path in _files(root)
                  if needle in path.read_bytes())


def _owned(call):
    try:
        return call()
    except sandbox_egress.SeatIdentityUnverified as exc:
        if os.environ.get(REQUIRE_NS) == "1":
            raise
        pytest.skip(f"this host cannot own a seat ({exc})")


def _real_bench(tmp_path, monkeypatch, *, secret, image=GROK_1_0_89, **stand_in):
    _namespace_or_skip()
    _require_bwrap()
    bench = Bench(tmp_path, monkeypatch, real=True)
    _plant(Path(bench.env["HOME"]), secret)
    bench.binary.write_text(_stand_in(tools=_tools("review"), **stand_in))
    bench.binary.chmod(0o700)
    bench.stand_for(image)
    return bench


def _assert_private_log(log: Path) -> None:
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert (log.parent / "provider.log.expires_at").is_file()


def _no_scratch_left(bench) -> None:
    assert not list(bench.output.glob("scratch-*"))
    assert not [p for p in bench.state.rglob("sessions") if p.is_dir()]
    assert not [p for p in bench.state.rglob("*") if p.name == "unified.jsonl"]


# ----------------------------------------------------------------------- the rehearsal

def test_a_failed_rehearsal_keeps_a_copied_suffix_in_its_provider_log_only(
        required_upstream, tmp_path, monkeypatch):
    """A rehearsal that fails (1.0.92 fetching its remote settings) keeps its provider log,
    which holds the child's copies on stdout and stderr: that private, expiring log is the
    only file that carries the suffix, and the sessions scratch with its copy is gone."""
    bench = _real_bench(tmp_path, monkeypatch, secret=LONG_SECRET, image=GROK_1_0_92,
                        exit_code=1, before=[("GET", "/v1/settings")],
                        copies={"stdout", "stderr", "session_file", "definitions"})
    bench.open_grant(planned="review", rehearse=False)
    code, report = _owned(lambda: bench.cli("--attended", "--rehearse", "--route", "review"))
    assert (code, report["reason"]) == (1, "unlisted_request"), report
    needle = _planted(LONG_SECRET, "suffix")
    assert needle.decode() not in json.dumps(report)
    (log,) = (bench.output / "raw").rglob("provider.log")
    assert _carrying(needle, bench.state) == [log]
    _assert_private_log(log)
    _no_scratch_left(bench)


# ---------------------------------------------------------------------- the measurement

@pytest.mark.parametrize("secret,value", [
    (SHORT_SECRET, "full"), (LONG_SECRET, "full"), (LONG_SECRET, "suffix")],
    ids=["short", "long-full", "long-suffix"])
def test_definitions_carrying_the_copy_are_refused_through_the_real_launch(
        required_upstream, tmp_path, monkeypatch, secret, value):
    """The child copies the planted value into its definitions artifact (and its stdout):
    ``artifact_refused``, with no raw copy and nothing extracted. The settled request stands;
    the route fails ``--require-measured``, is never reprocessed and never published. Only
    the failed launch's private provider log carries the value."""
    bench = _real_bench(tmp_path, monkeypatch, secret=secret, value=value,
                        copies={"definitions", "stdout"})
    bench.open_grant(planned="review")
    code, report = _owned(lambda: bench.measure("review"))
    assert code == 0 and report["routes"][0]["status"] == "artifact_refused", report
    assert not list((bench.output / "raw").rglob(gts.DEFINITIONS_NAME))
    (result,) = bench.results().values()
    assert result["definitions_sha256"] is None and result["tools"] is None
    assert bench.status()["charged"] == 1
    assert bench.cli("--require-measured", "review")[0] == 1
    assert bench.cli("--reprocess", result["reservation"])[0] == 1
    code, report = bench.cli("--aggregate")
    assert code == 0 and report["published"] == [] and bench.host_record() is None
    needle = _planted(secret, value)
    (log,) = (bench.output / "raw").rglob("provider.log")
    assert _carrying(needle, bench.state) == [log]
    _assert_private_log(log)
    _no_scratch_left(bench)


def test_a_clean_measurement_with_copies_elsewhere_still_measures_and_keeps_none(
        required_upstream, tmp_path, monkeypatch):
    """The child copies the suffix to stdout, stderr and a sessions file but not into its
    definitions: ``measured``. The provider log is deleted on a measured route and the
    sessions scratch with it, so no file under the output root, the grant, the host-local
    record root or the evidence carries the suffix."""
    bench = _real_bench(tmp_path, monkeypatch, secret=LONG_SECRET,
                        copies={"stdout", "stderr", "session_file"})
    bench.open_grant(planned="review")
    code, report = _owned(lambda: bench.measure("review"))
    assert code == 0 and report["routes"][0]["status"] == "measured", report
    assert bench.cli("--aggregate")[1]["published"] == ["review"]
    needle = _planted(LONG_SECRET, "suffix")
    assert _carrying(needle, bench.state, pa.private_record_root()) == []
    assert not list((bench.output / "raw").rglob("provider.log"))
    _no_scratch_left(bench)


def test_an_abandoned_sessions_scratch_is_purged_with_its_copy(bench):
    """A launch killed before its own cleanup leaves its scratch, whose sessions tree may
    hold a copy: ``--purge`` removes it at once, since its lock is no longer held."""
    bench.open_grant(planned="review")
    scratch = bench.output / "scratch-abandoned"
    (scratch / "sessions" / "-encoded-cwd").mkdir(parents=True, mode=0o700)
    (scratch / gts.SCRATCH_LOCK).write_text("")
    (scratch / "sessions" / "-encoded-cwd" / "transcript.jsonl").write_text(
        LONG_SECRET[-12:])
    code, report = bench.cli("--purge")
    assert code == 0 and report["scratch_removed"] == 1, report
    assert not scratch.exists()
    assert _carrying(LONG_SECRET[-12:].encode(), bench.state) == []


@pytest.mark.parametrize("relative", [".grok/logs", ".grok", ""],
                         ids=["logs", "ancestor-grok", "ancestor-home"])
def test_a_host_bind_at_or_above_the_client_log_refuses_before_any_launch(
        bench, monkeypatch, tmp_path, relative):
    """``.grok/logs`` is never host-backed: a bind at it, or at any ancestor up to the home
    itself, refuses a rehearsal and a measurement at the context check."""
    source = tmp_path / "host-bind"
    source.mkdir(mode=0o700)
    destination = gts.PRIVATE_HOME + ("/" + relative if relative else "")
    real = pi.seat_profile
    binding = {"on": False}

    @contextlib.contextmanager
    def seat_profile(**kwargs):
        with real(**kwargs) as (seat, profile):
            if binding["on"]:
                profile = replace(profile, mount_args=(
                    *profile.mount_args, "--bind", str(source), destination))
            yield seat, profile
    monkeypatch.setattr(pi, "seat_profile", seat_profile)
    bench.open_grant(planned="review", rehearse=False)
    binding["on"] = True
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (code, report["status"], report["code"]) == (1, "refused", "context_refused"), report
    assert bench.rehearsals == []
    binding["on"] = False
    assert bench.cli("--attended", "--rehearse", "--route", "review")[0] == 0
    binding["on"] = True
    code, report = bench.measure("review")
    assert _route_rows(report)["review"]["status"] == "context_refused"
    assert bench.launches == []


# ------------------------------------------------------------------------ the board leg

@pytest.mark.parametrize("form", ["review", "sealed"])
@pytest.mark.parametrize("exit_code", [0, 3], ids=["completed", "failed"])
def test_a_board_leg_redacts_every_copy_of_the_suffix(
        required_upstream, live_seat_attempt, tmp_path, monkeypatch, form, exit_code):
    """A frozen-basis board leg through the real ``_exec_leg`` composition, whose child
    copies the suffix to stdout, stderr and a file in its working directory: the suffix is
    absent from the returned text, the private leg log (``_leg_failure_detail``,
    ``_resolve_leg_detail``), the leg's review and output directories, the board's records
    (``leg_exec.v1`` among them, under the private record root) and the run directory."""
    from test_grok_board_leg_frozen_basis import (
        Board, _board_leg_egress, _exec_leg, _leg_command, _prerequisites, _skip_unless_owned,
    )
    _prerequisites()
    board = Board(tmp_path, monkeypatch)
    _plant(Path(board.env["HOME"]), LONG_SECRET)
    board.binary.write_text(_stand_in(tools=_tools(form), exit_code=exit_code,
                                      copies={"stdout", "stderr", "output", "session_file"}))
    board.binary.chmod(0o700)
    review_dir, out_dir = board.leg(form)
    board.publish(_leg_command(form, review_dir, out_dir))
    try:
        with _board_leg_egress():
            rc, text, log = _exec_leg(board, form, review_dir, out_dir)
    except sandbox_egress.SeatIdentityUnverified as exc:
        _skip_unless_owned(exc)
    needle = LONG_SECRET[-12:]
    assert "the log said" in text + log, (rc, log[-800:])  # the copies were made
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    status = "OK" if rc == 0 else "FAILED"
    detail = pi._resolve_leg_detail(pi._leg_failure_detail(status, rc, text, log), run_dir,
                                    "grok")
    assert needle not in text + log + str(detail)
    records = sorted(pa.private_record_root().glob("leg-*.json"))
    assert records and all(json.loads(p.read_text())["schema"] == "leg_exec.v1"
                           for p in records)
    assert _carrying(needle.encode(), run_dir, review_dir, out_dir, tmp_path / "state",
                     pa.private_record_root()) == []
    # The leg's output file is the redacted review text, not the child's raw stdout.
    (output,) = _files(out_dir)
    assert "[credential redacted]" in output.read_text()
