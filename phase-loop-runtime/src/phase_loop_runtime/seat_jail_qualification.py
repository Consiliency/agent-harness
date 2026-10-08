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

import datetime
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import review_stage, sandbox_egress, seat_jail, seat_uid

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
    if leg != "claude":
        raise QualificationError("only the claude jail is shipped")
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
            token_fd=seat_jail.token_pipe(b"QUALIFY-SENTINEL"), seat_ids=(n, n))
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


def main(argv: list[str] | None = None) -> int:
    evidence = qualify()
    summary = {k: evidence.get(k) for k in ("result", "profile_digest", "falsifier_layout",
                                            "checks", "run_outcome", "recorded_pass")}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if evidence.get("result") == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
