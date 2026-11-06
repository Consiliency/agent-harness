"""EC-EXECFIND-2 jail falsifiers: per-host qualification of the seat jail (agent-harness#1132).

EC-EXECFIND-2 lets a seat go on the jailed route only after that jail's falsifiers pass
against the actual falsifier-run layout (agent-harness#1163/#1164). This module is that run:

- It starts a REAL falsifier run, using the EXECFIND staging, the dependency snapshot and
  the bounded bwrap node runner. Its node is a sentinel, which holds:
  - a sentinel process;
  - one listener each for TCP loopback, UDP loopback, a pathname Unix socket and an
    abstract Unix socket.
- The parent writes a nonce sentinel file in every directory of the run's protected set
  (the staged tree and the dependency root).
- CONCURRENTLY, it runs a deterministic probe program under a live seat jail, on the D8
  seat-uid chain and the production jail. The probe tries, through the literal host paths
  AND through anything it can resolve by device and inode, to:
  - create an entry in a protected directory;
  - change, replace or remove a sentinel;
  - signal the sentinel process;
  - connect to each listener.

  It also reports its own mounts and descriptors.
- Everything is judged parent-side:
  - no probe entry, and every sentinel intact;
  - no signal and no connection observed by the run;
  - every protected regular file has exactly one link;
  - no mount root and no write-capable, directory or O_PATH descriptor of the seat resolves
    to a protected object or an ancestor of one;
  - the falsifier run itself completed as `green_on_head`.
- On a pass, it records evidence and a pass record in THIS host's store, bound to the jail's
  profile digest, the host and the falsifier-run layout (maintainer decision: option A).

Nothing a seat produces is ever a falsifier outcome here: the probe is the adversary, and
the outcome is the parent's own observation.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, Mapping, Protocol, Sequence

from . import __version__, review_stage, sandbox_egress, seat_egress_proxy, seat_jail, seat_uid

SCHEMA = "seat_jail_execfind2_qualification.v1"
_SENTINEL_TEST = "tests/test_jail_sentinel.py"
_SENTINEL_NODE = f"{_SENTINEL_TEST}::test_hold"
_READY = ".sentinel-ready.json"
_EVENTS = ".sentinel-events"
_RELEASE = ".sentinel-release"

# The sentinel node. It runs INSIDE the falsifier run, and is the run's own process:
# - it binds one listener per socket family, and logs to the events file any accepted
#   connection, datagram or signal;
# - it reports its host-visible identity in the ready file;
# - it holds until the parent releases it.
_SENTINEL_SOURCE = r'''
import json, os, signal, socket, threading, time

def test_hold():
    events = open("/work/.sentinel-events", "a", buffering=1)
    def log(what):
        events.write(what + "\n")
    for sig in (signal.SIGUSR1, signal.SIGUSR2, signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda n, f: log(f"signal {n}"))
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM); tcp.bind(("127.0.0.1", 0)); tcp.listen(8)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); udp.bind(("127.0.0.1", 0))
    path = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); path.bind("/work/sentinel.sock"); path.listen(8)
    abstract_name = "\0pl-seat-jail-sentinel-" + os.environ.get("HOME", "x").replace("/", "-")
    abstract = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); abstract.bind(abstract_name); abstract.listen(8)
    def accept(sock, label):
        while True:
            try:
                conn, _ = sock.accept(); log(f"accepted {label}"); conn.close()
            except OSError:
                return
    def datagram():
        while True:
            try:
                udp.recvfrom(64); log("datagram udp")
            except OSError:
                return
    for sock, label in ((tcp, "tcp"), (path, "unix-path"), (abstract, "unix-abstract")):
        threading.Thread(target=accept, args=(sock, label), daemon=True).start()
    threading.Thread(target=datagram, daemon=True).start()
    with open("/work/.sentinel-ready.json.tmp", "w") as ready:
        json.dump({"tcp": tcp.getsockname()[1], "udp": udp.getsockname()[1],
                   "abstract": abstract_name[1:], "pid_in_run": os.getpid()}, ready)
    os.rename("/work/.sentinel-ready.json.tmp", "/work/.sentinel-ready.json")
    deadline = time.monotonic() + 600
    while not os.path.exists("/work/.sentinel-release") and time.monotonic() < deadline:
        time.sleep(0.1)
    assert os.path.exists("/work/.sentinel-release")
'''

# The adversary. It runs as the seat, inside the production jail.
_PROBE_SOURCE = r'''
import errno, json, os, signal, socket, stat, sys
cfg = json.loads(sys.argv[1])
nonce = cfg["nonce"]
protected = {(d, i) for d, i in cfg["protected_ids"]}
sentinel_ids = {(d, i) for d, i in cfg["sentinel_ids"]}
results = {"create": [], "sentinel": [], "signal": [], "connect": [], "resolved": [],
           "mounts": [], "fds": []}
def attempt(kind, target, fn):
    try:
        fn(); results[kind].append([target, "SUCCEEDED"])
    except OSError as exc:
        results[kind].append([target, errno.errorcode.get(exc.errno, str(exc.errno))])
def create_in(directory):
    fd = os.open(os.path.join(directory, "pl-probe-" + nonce), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    os.close(fd)
def tamper(path):
    with open(path, "ab") as handle:
        handle.write(b"probe")
for directory in cfg["protected_dirs"]:
    attempt("create", directory, lambda d=directory: create_in(d))
for path in cfg["sentinels"]:
    attempt("sentinel", path, lambda p=path: tamper(p))
    attempt("sentinel", path + ":rename", lambda p=path: os.rename(p, p + ".probe"))
    attempt("sentinel", path + ":unlink", lambda p=path: os.unlink(p))
# Anything the probe can resolve, by device and inode, not only the literal host paths.
for root, dirs, files in os.walk("/", followlinks=False):
    if root.startswith(("/proc", "/sys", "/dev")):
        dirs[:] = []
        continue
    try:
        st = os.lstat(root)
    except OSError:
        continue
    if (st.st_dev, st.st_ino) in protected:
        results["resolved"].append(root)
        attempt("create", root + ":resolved", lambda d=root: create_in(d))
    for name in files:
        path = os.path.join(root, name)
        try:
            fst = os.lstat(path)
        except OSError:
            continue
        if (fst.st_dev, fst.st_ino) in sentinel_ids:
            results["resolved"].append(path)
            attempt("sentinel", path + ":resolved", lambda p=path: tamper(p))
for sig in (0, signal.SIGUSR1, signal.SIGTERM):
    attempt("signal", f"{cfg['sentinel_pid']}:{int(sig)}", lambda s=sig: os.kill(cfg["sentinel_pid"], s))
def tcp():
    s = socket.create_connection(("127.0.0.1", cfg["tcp"]), timeout=2); s.close()
def udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b"probe", ("127.0.0.1", cfg["udp"])); s.close()
def unix(address):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(2); s.connect(address); s.close()
attempt("connect", "tcp", tcp)
attempt("connect", "udp", udp)
attempt("connect", "unix-path", lambda: unix(cfg["unix_path"]))
attempt("connect", "unix-abstract", lambda: unix("\0" + cfg["abstract"]))
for line in open("/proc/self/mountinfo"):
    point = line.split(" ")[4].encode().decode("unicode_escape")
    try:
        st = os.stat(point)
        results["mounts"].append([point, st.st_dev, st.st_ino])
    except OSError:
        pass
for name in os.listdir("/proc/self/fd"):
    try:
        st = os.fstat(int(name))
        flags = int(open(f"/proc/self/fdinfo/{name}").read().split("flags:")[1].split()[0], 8)
        results["fds"].append([int(name), st.st_dev, st.st_ino, flags])
    except (OSError, ValueError, IndexError):
        pass
print(json.dumps(results))
'''


class QualificationError(RuntimeError):
    pass


#: The qualification cannot start without `pytest` where the falsifier run reads dependencies
#: (agent-harness#1357). Compared by equality in `seat_jail_autoqualify.classify_failure`.
PYTEST_MISSING = "pytest is not installed where the jail's falsifier run reads dependencies"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=q@local", "-c", "user.name=q",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def _sentinel_repo(base: Path) -> Path:
    repo = base / "sentinel-repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "phase-loop-runtime" / "src").mkdir(parents=True)
    (repo / "phase-loop-runtime" / "tests").mkdir(parents=True)
    (repo / _SENTINEL_TEST).write_text(_SENTINEL_SOURCE, encoding="utf-8")
    (repo / "phase-loop-runtime" / "src" / ".keep").write_text("", encoding="utf-8")
    (repo / "phase-loop-runtime" / "tests" / ".keep").write_text("", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sentinel")
    return repo


def _directories(roots: list[Path]) -> list[Path]:
    found = []
    for root in roots:
        for directory, dirs, _files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(directory, d))]
            found.append(Path(directory))
    return found


def _identity(path: Path) -> tuple[int, int]:
    st = os.lstat(path)
    return st.st_dev, st.st_ino


def _ancestors(paths: list[Path]) -> set[tuple[int, int]]:
    ids = set()
    for path in paths:
        for parent in [path, *path.parents]:
            try:
                ids.add(_identity(parent))
            except OSError:
                pass
    return ids


def _find_host_pid(marker: str, deadline: float) -> int:
    while time.monotonic() < deadline:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                cmdline = Path(f"/proc/{name}/cmdline").read_bytes()
            except OSError:
                continue
            if marker.encode() in cmdline and b"-c" in cmdline:
                return int(name)
        time.sleep(0.1)
    raise QualificationError("sentinel process not found")


def qualify(leg: str = "claude", *, record: bool = True, provider: Path | None = None,
            _mutate_jail=None) -> dict[str, object]:
    """Run the EC-EXECFIND-2 jail falsifiers on this host. Returns the evidence; on a pass
    (and ``record``), writes the evidence and pass record to this host's store."""
    if leg not in seat_jail.JAILED_LEGS:
        raise QualificationError(f"no {leg} jail is shipped")
    if not seat_uid.seat_uid_available():
        raise QualificationError(seat_uid.PREREQUISITE)
    if not sandbox_egress.egress_isolation_available():
        raise QualificationError("egress isolation unavailable")
    try:
        pytest_present = review_stage.falsifier_distribution_available("pytest")
    except (OSError, subprocess.SubprocessError, ValueError):
        pytest_present = True   # cannot tell here; the run itself reports it
    if not pytest_present:
        raise QualificationError(PYTEST_MISSING)
    digest = seat_jail.jail_profile_digest(leg)
    layout = seat_jail.falsifier_layout_identity()
    host = seat_jail.host_identity()
    if host is None:
        raise QualificationError("no /etc/machine-id: this host has no identity to bind a pass to")
    nonce = secrets.token_hex(12)
    base = Path(tempfile.mkdtemp(prefix="pl-jail-qualify-"))
    evidence: dict[str, object] = {
        "schema": SCHEMA, "profile_digest": digest, "host_identity": host,
        "falsifier_layout": layout, "leg": leg,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    staged: Path | None = None
    run_thread: threading.Thread | None = None
    run_result: dict[str, object] = {}
    try:
        repo = _sentinel_repo(base)
        staged = review_stage.stage_review_tree(repo)
        with tempfile.TemporaryDirectory(prefix="pl-falsifier-deps-") as deps_name:
            deps = Path(deps_name)
            review_stage._snapshot_falsifier_dependencies(staged, deps)
            protected_roots = [staged, deps]
            # A parent-written nonce sentinel in every protected directory, recursively.
            sentinels = []
            for directory in _directories(protected_roots):
                sentinel = directory / f".pl-sentinel-{nonce}"
                sentinel.write_text(nonce, encoding="utf-8")
                sentinels.append(sentinel)
            before = {str(p): (p.read_bytes(), _identity(p)) for p in sentinels}
            review_stage._require_single_link_files((staged, deps))

            def _run() -> None:
                try:
                    run_result["value"] = review_stage._run_bounded_falsifier_node(
                        staged=staged, dependencies=deps, nodeid=_SENTINEL_NODE,
                        wall_clock_s=900.0, output_cap_bytes=1 << 20,
                    )
                except Exception as exc:  # recorded, judged below
                    run_result["error"] = f"{type(exc).__name__}: {exc}"

            run_thread = threading.Thread(target=_run, daemon=True)
            run_thread.start()
            deadline = time.monotonic() + 120
            while not (staged / _READY).exists():
                if time.monotonic() > deadline or not run_thread.is_alive():
                    raise QualificationError(f"sentinel never became ready: {run_result}")
                time.sleep(0.1)
            ready = json.loads((staged / _READY).read_text(encoding="utf-8"))
            sentinel_pid = _find_host_pid(_SENTINEL_NODE, time.monotonic() + 30)
            protected_dirs = _directories(protected_roots)
            protected_ids = {_identity(d) for d in protected_dirs}
            protected_file_ids = {_identity(p) for p in sentinels}
            config = {
                "nonce": nonce,
                "protected_dirs": [str(d) for d in protected_dirs],
                "protected_ids": sorted(protected_ids),
                "sentinels": [str(p) for p in sentinels],
                "sentinel_ids": sorted(protected_file_ids),
                "sentinel_pid": sentinel_pid,
                "tcp": ready["tcp"], "udp": ready["udp"], "abstract": ready["abstract"],
                "unix_path": str(staged / "sentinel.sock"),
            }
            probe = _run_probe_in_jail(leg, base, config, provider, _mutate_jail)
            evidence["probe"] = probe
            # Release the sentinel and collect the run's own outcome.
            (staged / _RELEASE).write_text("done", encoding="utf-8")
            run_thread.join(timeout=300)
            events = (staged / _EVENTS).read_text(encoding="utf-8") if (staged / _EVENTS).exists() else ""
            after = {}
            for path in sentinels:
                try:
                    after[str(path)] = (path.read_bytes(), _identity(path))
                except OSError:
                    after[str(path)] = None
            probe_entries = [str(p) for d in _directories(protected_roots)
                             for p in d.iterdir() if f"pl-probe-{nonce}" in p.name]
            try:
                review_stage._require_single_link_files((staged, deps))
                links_ok = True
            except ValueError:
                links_ok = False
            ancestors = _ancestors(protected_dirs)
            mount_hits = [m for m in probe.get("mounts", [])
                          if (m[1], m[2]) in protected_ids | protected_file_ids | ancestors]
            write_or_dir = os.O_WRONLY | os.O_RDWR | getattr(os, "O_PATH", 0) | getattr(os, "O_DIRECTORY", 0)
            fd_hits = [f for f in probe.get("fds", [])
                       if (f[1], f[2]) in protected_ids | protected_file_ids and f[3] & write_or_dir]
            outcome = None
            if "value" in run_result:
                returncode, _out, _err, failure, report = run_result["value"]
                from .falsifier import _outcome_from_report

                outcome = (f"error: {failure}" if failure
                           else _outcome_from_report(report, _SENTINEL_NODE, returncode))
            checks = {
                "no_probe_entry_in_protected_dirs": not probe_entries,
                "sentinels_intact": all(after[k] == v for k, v in before.items()),
                "no_signal_or_connection_observed_by_run": events.strip() == "",
                "protected_files_single_link": links_ok,
                "no_seat_mount_resolves_to_protected_object_or_ancestor": not mount_hits,
                "no_seat_descriptor_resolves_to_protected_object": not fd_hits,
                "probe_resolved_no_protected_path": not probe.get("resolved"),
                "falsifier_run_green_on_head": outcome == "green_on_head",
            }
            evidence.update({
                "checks": checks, "run_outcome": outcome, "run_events": events.splitlines()[:20],
                "probe_entries": probe_entries, "mount_hits": mount_hits, "fd_hits": fd_hits,
                "protected_dir_count": len(protected_dirs), "sentinel_count": len(sentinels),
                "result": "pass" if all(checks.values()) else "fail",
            })
    finally:
        if run_thread is not None and run_thread.is_alive() and staged is not None:
            try:
                (staged / _RELEASE).write_text("done", encoding="utf-8")
            except OSError:
                pass
            run_thread.join(timeout=60)
        if staged is not None:
            review_stage.remove_review_stage(staged)
        shutil.rmtree(base, ignore_errors=True)
    if record and evidence.get("result") == "pass":
        evidence["recorded_pass"] = str(_record_pass(evidence))
    return evidence


def _run_probe_in_jail(leg, base: Path, config: dict, provider: Path | None, mutate) -> dict:
    """The probe, as the seat, in the production jail on the D8 chain."""
    from . import panel_invoker as pi

    review = base / "seat" / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "README").write_text("probe seat tree\n", encoding="utf-8")
    seat_dir = base / "seat" / "dirs"
    seat_dir.mkdir(mode=0o700)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=900, required=True, seat_uid_map=True) as egress:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        holder = seat_uid.holder_pid_from_prefix(egress)
        jail = seat_jail.build_seat_jail(
            leg, seat_dir, provider or Path("/usr/bin/python3"), tree=tree,
            bundle_memfd=seat_jail.memfd_with("b", b"B"),
            instructions_memfd=seat_jail.memfd_with("i", b"I"),
            token_fd=seat_jail.token_pipe(b"QUALIFY-SENTINEL") if leg == "claude" else None,
            seat_ids=(n, n), **(_gemini_shape(seat_dir) if leg == "gemini" else {}))
        try:
            if mutate is not None:
                mutate(jail)
            else:
                # The probe runs in the canonical jail and nowhere else.
                pi._require_canonical_jail(jail)
            prefix = pi._compose_seat_jail_prefix(jail)
            done = subprocess.run(
                [*prefix, "/usr/bin/python3", "-I", "-c", _PROBE_SOURCE, json.dumps(config)],
                capture_output=True, text=True, timeout=600, pass_fds=jail.pass_fds,
                env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
        finally:
            seat_jail.close_jail_fds(jail)
            for parent in (review, seat_dir):
                seat_uid.teardown_in_h(holder, str(parent))
            pi._EGRESS_LAUNCH_PREFIX.reset(token)
    if done.returncode != 0:
        raise QualificationError(f"probe failed to run: {done.stderr[-400:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def _gemini_shape(seat_dir: Path) -> dict[str, object]:
    """The jailed Gemini seat's config, CA certificate and proxy URL (agent-harness#1170), in
    the production shape: the qualification judges the jail's boundaries, so the files only
    need to be where the seat's are. No credential and no CA key is involved."""
    from .panel_invoker import _write_gemini_config

    config = seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
    _write_gemini_config(config, b"")
    certificate = seat_dir / "egress-ca.pem"
    certificate.write_text("qualification placeholder certificate\n", encoding="ascii")
    certificate.chmod(0o444)
    return {"gemini_config": config, "egress_ca": certificate,
            "egress_proxy": "http://srt:qualification@127.0.0.1:3128"}


def _record_pass(evidence: dict[str, object]) -> Path:
    store = seat_jail.jail_pass_dir()
    for directory in (seat_jail.state_home(), seat_jail.state_home() / "phase-loop", store):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            # Never re-permission an existing directory of the operator's: the gate would
            # refuse a pass under a group/other-writable parent, so say how to fix it.
            if seat_jail.pass_store_dir_problem(directory) is not None:
                raise QualificationError(
                    f"{directory} must be a directory you own that is not other-writable, "
                    f"and not group-writable unless its group is your user-private group "
                    f"(e.g. chmod go-w {directory}); no pass recorded")
    digest = str(evidence["profile_digest"])
    raw = json.dumps(evidence, indent=2, sort_keys=True).encode("utf-8")
    evidence_name = f"{digest}.evidence.json"
    _write_private(store / evidence_name, raw)
    record = {"schema": seat_jail.PASS_RECORD_SCHEMA, "profile_digest": digest, "result": "pass",
              "host_identity": evidence["host_identity"],
              "falsifier_layout": evidence["falsifier_layout"],
              "evidence": evidence_name, "evidence_sha256": hashlib.sha256(raw).hexdigest()}
    path = store / f"{digest}.json"
    _write_private(path, json.dumps(record, indent=2, sort_keys=True).encode("utf-8"))
    return path


def _write_private(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)


# ======================================================================================
# FIRSTSEAT W1 containment supplier (IF-0-FIRSTSEAT-5).
#
# Frozen inputs: plans/seats-firstseat-containment-contract.md (cited as sections 1-16) and
# plans/artifacts/seats-firstseat-interfaces.md (cited as I-1 to I-15). Lane A owns I-1 to
# I-10, I-13 and the OwnerSummary type of I-14. Nothing here is a W1 result: every live
# measurement runs from lane E's `seat-window qualify` on an attended host.
# ======================================================================================

# --- I-9: the jailed step callable (type here, implementation in panel_invoker) --------


@dataclass(frozen=True, slots=True, kw_only=True)
class JailedStep:
    """One trusted step run in a launch's own jail. ``stdout`` stays in memory only."""

    exit_code: int | None
    timed_out: bool
    stdout: bytes = field(repr=False)


class JailedRun(Protocol):
    """Runs ``argv`` as the seat uid in the issuing launch's jail, namespace and proxy
    instance, with ``/seat/tree`` as its working directory and exactly ``env`` (plus the
    proxy variables when ``use_proxy``). ``stdout`` is capped at 65536 bytes."""

    def __call__(self, argv: Sequence[str], *, env: Mapping[str, str], use_proxy: bool,
                 timeout_s: float) -> JailedStep: ...


# --- I-7: the bracket (sections 9 and 11) ----------------------------------------------

BracketRowName = Literal["b_forbidden_hosts", "b_forbidden_paths", "b_tunnel_inner_host",
                         "b_tunnel_inner_sni_and_host", "b_tunnel_inner_sni_only",
                         "b_fail_closed_front", "b_direct_without_proxy", "f006_config_ancestor"]
BRACKET_ROW_NAMES: Final[tuple[str, ...]] = (
    "b_forbidden_hosts", "b_forbidden_paths", "b_tunnel_inner_host",
    "b_tunnel_inner_sni_and_host", "b_tunnel_inner_sni_only", "b_fail_closed_front",
    "b_direct_without_proxy", "f006_config_ancestor")

#: The refusal signatures each section 11 row may report, frozen per row (section 11: a
#: known client exit and that row's expected refusal signature). A step reports one of
#: these only on positive evidence that it ran and was refused; anything else is
#: ``unavailable``. A certificate failure is never a refusal.
#: - ``proxy_connect_refused``: the proxy answered the CONNECT with 403.
#: - ``request_filter_refused``: the proxy's request filter answered 403 inside the tunnel.
#: - ``handshake_refused``: the proxy ended the TLS handshake after accepting the CONNECT.
#: - ``no_upstream_bytes``: a completed attempt reported zero upstream bytes.
#: - ``resolve_refused`` / ``connect_refused``: the client's resolve or connect refusal exit.
#: - ``config_ancestor_read_only``: the config ancestor could not be renamed or written.
BRACKET_SIGNATURES: Final[Mapping[str, frozenset[str]]] = MappingProxyType({
    "b_forbidden_hosts": frozenset({"proxy_connect_refused"}),
    "b_forbidden_paths": frozenset({"proxy_connect_refused", "request_filter_refused"}),
    "b_tunnel_inner_host": frozenset({"proxy_connect_refused", "request_filter_refused",
                                      "handshake_refused"}),
    "b_tunnel_inner_sni_and_host": frozenset({"proxy_connect_refused", "request_filter_refused",
                                              "handshake_refused"}),
    "b_tunnel_inner_sni_only": frozenset({"proxy_connect_refused", "request_filter_refused",
                                          "handshake_refused"}),
    "b_fail_closed_front": frozenset({"no_upstream_bytes"}),
    "b_direct_without_proxy": frozenset({"resolve_refused", "connect_refused"}),
    "f006_config_ancestor": frozenset({"config_ancestor_read_only"}),
})
#: Section 9's token POST counts only when its client reported the proxy's CONNECT 403.
TOKEN_POST_STEP: Final = "token_post"
TOKEN_POST_SIGNATURE: Final = "proxy_connect_refused"

#: Section 11's client rules for every bracket step: no seat-writable configuration is read.
#: HOME, CURL_HOME and XDG_* name a path that cannot hold a file (under /dev/null), and a
#: curl step puts ``-q`` first on its argv.
BRACKET_EMPTY_HOME: Final = "/dev/null/phase-loop-bracket"
BRACKET_STEP_ENV: Final[Mapping[str, str]] = MappingProxyType({
    "PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": BRACKET_EMPTY_HOME,
    "CURL_HOME": BRACKET_EMPTY_HOME, "XDG_CONFIG_HOME": BRACKET_EMPTY_HOME,
    "XDG_DATA_HOME": BRACKET_EMPTY_HOME, "XDG_CACHE_HOME": BRACKET_EMPTY_HOME,
    "XDG_STATE_HOME": BRACKET_EMPTY_HOME, "XDG_RUNTIME_DIR": BRACKET_EMPTY_HOME,
    "SSL_CERT_FILE": seat_jail.SEAT_EGRESS_CA,
})


class BracketStep(Protocol):
    """One bracket step. It runs only through ``run`` (with :data:`BRACKET_STEP_ENV`) and
    returns a member of its row's :data:`BRACKET_SIGNATURES` set (for the token POST,
    :data:`TOKEN_POST_SIGNATURE`) on positive evidence of refusal, and ``None`` for any
    other result. It sends no request that matches section 9's token-endpoint table,
    except the token POST itself."""

    def __call__(self, run: JailedRun) -> str | None: ...


_CURL_WRITE_OUT: Final = "\nPHASE_LOOP_CURL %{http_code} %{http_connect}\n"
_PROXY_ERROR_HEADER: Final = b"x-proxy-error: blocked-by-sandbox-runtime"
_CURL_OK: Final = 0
_CURL_COULDNT_RESOLVE_HOST: Final = 6
_CURL_COULDNT_CONNECT: Final = 7
_CURL_SSL_CONNECT_ERROR: Final = 35
_CURL_RECV_ERROR: Final = 56


def _curl_step(run: JailedRun, url: str, *extra: str,
               use_proxy: bool = True) -> JailedStep:
    return run(
        ("/usr/bin/curl", "-q", "--silent", "--show-error", "--max-time", "15",
         "--output", "/dev/null", "--dump-header", "-", "--write-out",
         _CURL_WRITE_OUT, *extra, url),
        env=BRACKET_STEP_ENV,
        use_proxy=use_proxy,
        timeout_s=60.0,
    )


def _curl_refusal(done: JailedStep) -> str | None:
    if done.timed_out or done.exit_code is None:
        return None
    head, marker, raw_codes = done.stdout.rpartition(b"\nPHASE_LOOP_CURL ")
    codes = raw_codes.strip().split()
    if not marker or len(codes) != 2:
        return None
    http_code, connect_code = codes
    if done.exit_code == _CURL_RECV_ERROR and connect_code == b"403":
        return "proxy_connect_refused"
    if (done.exit_code == _CURL_OK and http_code == b"403" and connect_code == b"200"
            and _PROXY_ERROR_HEADER in head.lower()):
        return "request_filter_refused"
    if (done.exit_code == _CURL_SSL_CONNECT_ERROR
            and http_code == b"000" and connect_code == b"200"):
        return "handshake_refused"
    return None


def _token_post(run: JailedRun) -> str | None:
    refusal = _curl_refusal(_curl_step(
        run, "https://oauth2.googleapis.com/token", "--request", "POST"))
    return TOKEN_POST_SIGNATURE if refusal == TOKEN_POST_SIGNATURE else None


def _forbidden_hosts(run: JailedRun) -> str | None:
    targets = (
        "https://storage.googleapis.com/",
        "https://cloudresourcemanager.googleapis.com/",
        "https://compute.googleapis.com/",
        "https://iam.googleapis.com/",
    )
    refusals = tuple(_curl_refusal(_curl_step(run, target)) for target in targets)
    return ("proxy_connect_refused"
            if all(item == "proxy_connect_refused" for item in refusals) else None)


def _forbidden_paths(run: JailedRun) -> str | None:
    targets = (
        "https://www.googleapis.com/storage/v1/b",
        "https://www.googleapis.com/compute/v1/projects",
    )
    refusals = tuple(_curl_refusal(_curl_step(run, target)) for target in targets)
    if not all(item in BRACKET_SIGNATURES["b_forbidden_paths"] for item in refusals):
        return None
    return ("request_filter_refused" if "request_filter_refused" in refusals
            else "proxy_connect_refused")


def _tunnel_inner_host(run: JailedRun) -> str | None:
    return _curl_refusal(_curl_step(
        run,
        "https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
        "--request", "POST", "--header", "Host: storage.googleapis.com",
    ))


def _tunnel_inner_sni_and_host(run: JailedRun) -> str | None:
    return _curl_refusal(_curl_step(
        run,
        "https://storage.googleapis.com/v1internal:loadCodeAssist",
        "--request", "POST", "--connect-to",
        "storage.googleapis.com:443:daily-cloudcode-pa.googleapis.com:443",
    ))


def _tunnel_inner_sni_only(run: JailedRun) -> str | None:
    return _curl_refusal(_curl_step(
        run,
        "https://storage.googleapis.com/v1internal:loadCodeAssist",
        "--request", "POST", "--header", "Host: daily-cloudcode-pa.googleapis.com",
        "--connect-to", "storage.googleapis.com:443:daily-cloudcode-pa.googleapis.com:443",
    ))


_FAIL_CLOSED_FRONT = r'''
import base64, os, socket, urllib.parse

proxy = urllib.parse.urlsplit(os.environ.get("HTTPS_PROXY", ""))
if (proxy.scheme != "http" or proxy.hostname != "127.0.0.1" or proxy.port is None
        or proxy.username is None or proxy.password is None):
    raise SystemExit(2)
username = urllib.parse.unquote(proxy.username)
password = urllib.parse.unquote(proxy.password)
auth = base64.b64encode(f"{username}:{password}".encode()).decode()
allowed = b"daily-cloudcode-pa.googleapis.com"
sni = b"storage.googleapis.com"

def attempt(record_version):
    extension = (b"\x00\x00" + (len(sni) + 5).to_bytes(2, "big")
                 + (len(sni) + 3).to_bytes(2, "big") + b"\x00"
                 + len(sni).to_bytes(2, "big") + sni)
    body = (b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x00\x02\x13\x01"
            + b"\x01\x00" + len(extension).to_bytes(2, "big") + extension)
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    record = (b"\x16\x03" + bytes([record_version])
              + len(handshake).to_bytes(2, "big") + handshake)
    sock = socket.create_connection((proxy.hostname, proxy.port), 5)
    sock.settimeout(8)
    request = (b"CONNECT " + allowed + b":443 HTTP/1.1\r\nHost: " + allowed
               + b":443\r\nProxy-Authorization: Basic " + auth.encode() + b"\r\n\r\n")
    sock.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response and len(response) < 4096:
        chunk = sock.recv(4096 - len(response))
        if not chunk:
            break
        response += chunk
    if not (response.startswith(b"HTTP/1.1 200 ") or response.startswith(b"HTTP/1.0 200 ")):
        raise SystemExit(3)
    sock.sendall(record)
    try:
        reply = sock.recv(4096)
    except OSError:
        reply = b""
    finally:
        sock.close()
    return len(reply)

print("UPSTREAM_BYTES", attempt(4), attempt(3))
'''


def _fail_closed_front(run: JailedRun) -> str | None:
    done = run(
        ("/usr/bin/python3", "-I", "-c", _FAIL_CLOSED_FRONT),
        env=BRACKET_STEP_ENV,
        use_proxy=True,
        timeout_s=60.0,
    )
    if (not done.timed_out and done.exit_code == _CURL_OK
            and done.stdout.strip() == b"UPSTREAM_BYTES 0 0"):
        return "no_upstream_bytes"
    return None


def _direct_without_proxy(run: JailedRun) -> str | None:
    targets = (
        "https://1.1.1.1/",
        "https://daily-cloudcode-pa.googleapis.com/",
    )
    results = tuple(_curl_step(run, target, use_proxy=False) for target in targets)
    refusal_exits = {_CURL_COULDNT_RESOLVE_HOST, _CURL_COULDNT_CONNECT}
    if any(done.timed_out or done.exit_code not in refusal_exits for done in results):
        return None
    return ("resolve_refused"
            if any(done.exit_code == _CURL_COULDNT_RESOLVE_HOST for done in results)
            else "connect_refused")


_CONFIG_ANCESTOR_CHECK = (
    'C=/seat/home/.gemini; '
    'mv "$C" "$C.x" 2>/dev/null && echo RENAMED || echo rename-refused; '
    'mkdir "$C/antigravity-cli/evil" 2>/dev/null && echo MKDIR || echo mkdir-refused; '
    'echo x > "$C/antigravity-cli/antigravity-oauth-token" 2>/dev/null '
    '&& echo WROTE || echo write-refused; '
    'for d in bin cache log; do echo x > "$C/antigravity-cli/$d/probe" 2>/dev/null '
    '&& echo "writable:$d" || echo "ro:$d"; done'
)
_CONFIG_ANCESTOR_EXPECTED: Final = (
    b"rename-refused", b"mkdir-refused", b"write-refused",
    b"writable:bin", b"writable:cache", b"writable:log",
)


def _config_ancestor(run: JailedRun) -> str | None:
    done = run(
        ("/bin/sh", "-c", _CONFIG_ANCESTOR_CHECK),
        env=BRACKET_STEP_ENV,
        use_proxy=False,
        timeout_s=60.0,
    )
    if (not done.timed_out and done.exit_code == _CURL_OK
            and tuple(done.stdout.splitlines()) == _CONFIG_ANCESTOR_EXPECTED):
        return "config_ancestor_read_only"
    return None


#: The bracket's steps, in run order: section 9's token POST, then section 11's rows,
#: each ported from plans/evidence/seat-jail-1132/probe_p4_containment_egress.py (pinned
#: method input; that script is never executed).
BRACKET_STEPS: Final[Mapping[str, BracketStep]] = MappingProxyType({
    TOKEN_POST_STEP: _token_post,
    "b_forbidden_hosts": _forbidden_hosts,
    "b_forbidden_paths": _forbidden_paths,
    "b_tunnel_inner_host": _tunnel_inner_host,
    "b_tunnel_inner_sni_and_host": _tunnel_inner_sni_and_host,
    "b_tunnel_inner_sni_only": _tunnel_inner_sni_only,
    "b_fail_closed_front": _fail_closed_front,
    "b_direct_without_proxy": _direct_without_proxy,
    "f006_config_ancestor": _config_ancestor,
})


@dataclass(frozen=True, slots=True, kw_only=True)
class BracketRow:
    row: str
    outcome: Literal["refused", "unavailable"]
    signature: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class BracketResult:
    start: seat_egress_proxy.FenceResult
    end: seat_egress_proxy.FenceResult
    post_refused: bool
    rows: tuple[BracketRow, ...]


def _bracket_step(name: str, run: JailedRun) -> str | None:
    step = BRACKET_STEPS.get(name)
    if step is None:
        return None
    try:
        signature = step(run)
    except Exception:  # noqa: BLE001 - an unported or failed step is an unmade observation
        return None
    allowed = ({TOKEN_POST_SIGNATURE} if name == TOKEN_POST_STEP
               else BRACKET_SIGNATURES.get(name, frozenset()))
    return signature if isinstance(signature, str) and signature in allowed else None


def run_bracket(proxy: seat_egress_proxy.SeatEgressProxy, run: JailedRun) -> BracketResult:
    """The measured leg's control bracket (sections 9 and 11; I-7).

    D calls it on ``measured`` only, after the leg's acknowledged end fence, process-group
    absence, a ``True`` bridge wait and at least ``FENCE_QUIET_S`` since that fence's
    ``acked_ns``. It fences its own ``bracket`` window and runs :data:`BRACKET_STEPS`
    inside it: no step runs unless the start fence was acknowledged, so no probe request
    falls outside the bracket. A row that did not report one of its signatures is
    ``unavailable``."""
    unsent = seat_egress_proxy.FenceResult(fence_id="", acknowledged=False, acked_ns=None)
    start = seat_egress_proxy.fence(proxy, "start", "bracket")
    if not start.acknowledged:
        return BracketResult(start=start, end=unsent, post_refused=False, rows=tuple(
            BracketRow(row=name, outcome="unavailable", signature=None)
            for name in BRACKET_ROW_NAMES))
    post_refused = _bracket_step(TOKEN_POST_STEP, run) == TOKEN_POST_SIGNATURE
    rows = []
    for name in BRACKET_ROW_NAMES:
        signature = _bracket_step(name, run)
        rows.append(BracketRow(row=name, outcome="refused" if signature else "unavailable",
                               signature=signature))
    end = seat_egress_proxy.fence(proxy, "end", "bracket")
    return BracketResult(start=start, end=end, post_refused=post_refused, rows=tuple(rows))


_ARGV_ACTIONS = {
    (): "qualify",
    ("-h",): "help",
    ("--help",): "help",
    ("--version",): "version",
}


def qualification_provider_capable(argv: Sequence[str]) -> bool:
    """Only closed, effect-free informational commands run without a dependency lease."""
    return _ARGV_ACTIONS.get(tuple(argv)) not in {"help", "version"}


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phase-loop-seat-jail-qualification",
        add_help=False,
        allow_abbrev=False,
        description="Qualify and record the host's seat-jail profile.",
    )
    informational = parser.add_mutually_exclusive_group()
    informational.add_argument("-h", "--help", action="store_true", dest="show_help")
    informational.add_argument("--version", action="store_true", dest="show_version")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    normalized = tuple(sys.argv[1:] if argv is None else argv)
    action = _ARGV_ACTIONS.get(normalized)
    if action is None:
        parser.error("expected no arguments or exactly one of -h, --help, --version")
    if action == "help":
        parser.print_help()
        return 0
    if action == "version":
        print(f"{parser.prog} {__version__}")
        return 0
    evidence = qualify()
    summary = {k: evidence.get(k) for k in ("result", "profile_digest", "falsifier_layout",
                                            "checks", "run_outcome", "recorded_pass")}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if evidence.get("result") == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
