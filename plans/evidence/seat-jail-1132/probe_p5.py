#!/usr/bin/env python3
"""Live probe P5 (agent-harness#1132, maintainer decision D8): the seat-uid launch chain.

It builds its own throwaway D8 chain from literal argv and does NOT use `seat_jail.py`'s
jail builder or `panel_invoker`'s composition, so the probe is independent of the code it
checks. The J14 filter bytes are the one exception: they are taken from the production
builder, because P5 must run the CLIs under the EXACT production filter, and the digest of
those bytes is recorded.

The chain:
- an unmapped holder, mapped by `newuidmap`/`newgidmap` so that 0 is the operator and
  1..N is the subordinate range;
- `nsenter` into it as H-root;
- bwrap, as H-root and without `--unshare-user`, building the J1 mount set with the filter;
- `setpriv`, dropping to seat uid n.

Recorded in the evidence:
- whether bwrap builds the jail as H-root;
- the capability set before the drop, with and without `--cap-drop ALL`;
- the seat's view after the drop;
- whether the CLIs run as the seat uid;
- whether the in-H reader can read a 0600 file the seat created.

P5's stop rules are applied, and a stop is recorded as a stop.

Usage (from the repo root): python3 plans/evidence/seat-jail-1132/probe_p5.py
Writes plans/evidence/seat-jail-1132/p5-seat-uid.json.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "phase-loop-runtime" / "src"))
from phase_loop_runtime import seat_jail  # noqa: E402  (filter bytes only)

OUT = Path(__file__).resolve().parent / "p5-seat-uid.json"
SEAT = 7
ETC = ("ssl", "resolv.conf", "hosts", "nsswitch.conf", "passwd", "group", "localtime",
       "ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives")
CAPS = {6: "CAP_SETGID", 7: "CAP_SETUID", 8: "CAP_SETPCAP"}


def sub_range(path: str) -> tuple[int, int]:
    import pwd

    name = pwd.getpwuid(os.getuid()).pw_name
    for line in Path(path).read_text().splitlines():
        owner, start, count = line.split(":")
        if owner in (name, str(os.getuid())):
            return int(start), int(count)
    raise SystemExit(f"no range in {path}")


def holder() -> tuple[subprocess.Popen, list[str]]:
    r, w = os.pipe()
    proc = subprocess.Popen(["/usr/bin/unshare", "--user", "--net", "--mount", "/bin/sh", "-c",
                             f"read g <&{r}; exec sleep 600"], pass_fds=(r,))
    os.close(r)
    own = os.readlink("/proc/self/ns/user")
    deadline = time.monotonic() + 10
    while os.readlink(f"/proc/{proc.pid}/ns/user") == own:
        if time.monotonic() > deadline:
            raise SystemExit("holder never entered its namespace")
        time.sleep(0.01)
    us, uc = sub_range("/etc/subuid")
    gs, gc = sub_range("/etc/subgid")
    count = min(uc, gc, 256)
    for tool, start in (("/usr/bin/newuidmap", us), ("/usr/bin/newgidmap", gs)):
        base = os.getuid() if "uid" in tool else os.getgid()
        subprocess.run([tool, str(proc.pid), "0", str(base), "1", "1", str(start), str(count)],
                       check=True)
    os.write(w, b"go\n")
    os.close(w)
    return proc, ["/usr/bin/nsenter", "-t", str(proc.pid), "-U", "-m", "-n",
                  "--preserve-credentials"]


def mounts(work: Path, provider_binds: list[tuple[str, str]], fds: dict[str, int]) -> list[str]:
    args: list[str] = []
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32"):
        if os.path.islink(path):
            args += ["--symlink", os.readlink(path), path]
        elif os.path.isdir(path):
            args += ["--ro-bind", path, path]
    args += ["--perms", "0755", "--dir", "/etc"]
    for name in ETC:
        host = f"/etc/{name}"
        if os.path.lexists(host):
            args += ["--ro-bind", host, host]
    args += ["--proc", "/proc", "--dev", "/dev", "--perms", "1777", "--tmpfs", "/tmp",
             "--perms", "1777", "--tmpfs", "/dev/shm"]
    # The seat directories are created explicitly world-searchable: bwrap creates the
    # parent of a FILE bind 0700 and owned by H-root, which the seat uid cannot traverse.
    for directory in ("/seat", "/seat/bin", "/seat/review"):
        args += ["--perms", "0755", "--dir", directory]
    for host, jail in provider_binds:
        args += ["--ro-bind", host, jail]
    args += ["--perms", "0444", "--ro-bind-data", str(fds["bundle"]), "/seat/review/review-bundle.md",
             "--bind", str(work / "tree"), "/seat/tree", "--bind", str(work / "home"), "/seat/home",
             "--bind", str(work / "out"), "/seat/out", "--remount-ro", "/",
             "--clearenv", "--setenv", "HOME", "/seat/home",
             "--setenv", "PATH", "/seat/bin:/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8"]
    return args


def memfd(data: bytes) -> int:
    fd = os.memfd_create("p5", 0)
    os.write(fd, data)
    os.lseek(fd, 0, 0)
    return fd


def caps_of(text: str) -> dict[str, str]:
    return {line.split(":")[0]: line.split(":")[1].strip() for line in text.splitlines()
            if line.startswith(("Cap", "NoNewPrivs", "Seccomp"))}


def names(mask_hex: str) -> list[str]:
    mask = int(mask_hex, 16)
    return [CAPS.get(bit, f"cap{bit}") for bit in range(64) if mask >> bit & 1]


def run_chain(enter, bwrap_args, tail, fds, *, drop=True, filter_fd=None, cap_drop_all=True):
    bw = ["/usr/bin/bwrap", "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
          "--unshare-cgroup-try", *(["--cap-drop", "ALL"] if cap_drop_all else []),
          "--cap-add", "CAP_SETUID", "--cap-add", "CAP_SETGID", "--cap-add", "CAP_SETPCAP",
          *bwrap_args, *(["--seccomp", str(filter_fd)] if filter_fd is not None else [])]
    setpriv = ["/usr/bin/setpriv", "--reuid", str(SEAT), "--regid", str(SEAT), "--clear-groups",
               "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all", "--no-new-privs", "--"]
    # The cwd is entered AFTER the drop, as the seat: with `--cap-drop ALL`, bwrap's own
    # `--chdir` runs as a capability-less H-root and cannot enter the seat's 0700 tree.
    chdir = ["/usr/bin/env", "--chdir=/seat/tree", "--"]
    argv = [*enter, *bw, *((*setpriv, *chdir) if drop else ()), *tail]
    keep = tuple(fd for fd in (*fds.values(), filter_fd) if fd is not None)
    done = subprocess.run(argv, capture_output=True, text=True, timeout=120, pass_fds=keep,
                          env={"PATH": "/usr/bin:/bin"})
    return done, argv


def main() -> int:
    record: dict[str, object] = {
        "schema": "seat_jail_probe_p5.v1", "issue": "agent-harness#1132", "decision": "D8",
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "host": {"kernel": os.uname().release,
                 "bwrap": subprocess.run(["/usr/bin/bwrap", "--version"], capture_output=True,
                                         text=True).stdout.strip(),
                 "operator_uid": os.getuid(), "subuid": sub_range("/etc/subuid"),
                 "subgid": sub_range("/etc/subgid"),
                 "legacy_tiocsti": Path("/proc/sys/dev/tty/legacy_tiocsti").read_text().strip()},
        "seat_id": SEAT,
        # Measured on this host; each changes the plan's literal argv (plan "Seat uid",
        # step 4) and is reported to the maintainer. None is a P5 stop: each restores a
        # property the plan requires.
        "plan_deviations": [
            "bwrap run as H-root keeps EVERY capability (see pre_drop_without_cap_drop_all); "
            "the plan's premise that bwrap leaves none by default holds only when bwrap is "
            "not real root. Production adds `--cap-drop ALL` before the three `--cap-add`s, so "
            "the pre-drop effective set is exactly CAP_SETUID, CAP_SETGID, CAP_SETPCAP.",
            "With `--cap-drop ALL`, bwrap's `--chdir /seat/tree` fails (a capability-less H-root "
            "cannot enter the seat's 0700 tree). The cwd is entered after the drop, as the seat, "
            "with `/usr/bin/env --chdir=/seat/tree`.",
            "bwrap creates the parent of a FILE bind 0700 and owned by H-root, so the seat could "
            "not traverse /seat, /seat/bin, /seat/review or /etc (node: OpenSSL config EACCES; git: "
            "/etc/gitconfig EACCES). Production creates those four directories with `--perms 0755 --dir`.",
        ],
    }
    program = seat_jail.build_seccomp_filter()
    record["filter_sha256"] = hashlib.sha256(program).hexdigest()
    record["filter_is_production"] = record["filter_sha256"] == seat_jail.production_filter_digest()
    work = Path(tempfile.mkdtemp(prefix="pl-p5-"))
    proc = None
    stops: list[str] = []
    try:
        for name in ("tree", "home", "out"):
            (work / name).mkdir(mode=0o700)
        claude = os.path.realpath(shutil.which("claude", path="/home/%s/.npm-global/bin:%s" % (
            os.environ.get("USER", ""), os.environ.get("PATH", ""))) or "")
        agy = os.path.realpath(shutil.which("agy") or "")
        binds = [(claude, "/seat/bin/claude"), (agy, "/seat/bin/agy")]
        record["providers"] = {"claude": claude, "agy": agy}
        proc, enter = holder()
        record["holder_uid_map"] = Path(f"/proc/{proc.pid}/uid_map").read_text().split("\n")[:2]
        # Hand-off (step 3), run as H-root inside H.
        chown = subprocess.run([*enter, "/bin/chown", "-R", f"{SEAT}:{SEAT}", str(work / "tree"),
                                str(work / "home"), str(work / "out")], capture_output=True, text=True)
        record["handoff_chown_rc"] = chown.returncode

        def fds() -> dict[str, int]:
            return {"bundle": memfd(b"P5 BUNDLE\n")}

        status = '/bin/sh -c "id -u; id -g; id -G; grep -E \'^(Cap|NoNewPrivs|Seccomp)\' /proc/self/status"'
        # Pre-drop set, as production composes it (--cap-drop ALL) and as the plan first
        # assumed (no --cap-drop).
        for label, cap_drop_all in (("with_cap_drop_all", True), ("without_cap_drop_all", False)):
            f = fds()
            done, _ = run_chain(enter, mounts(work, binds, f), ["/bin/sh", "-c", status.split('"')[1]],
                                f, drop=False, cap_drop_all=cap_drop_all)
            lines = done.stdout.splitlines()
            view = caps_of(done.stdout)
            record[f"pre_drop_{label}"] = {
                "rc": done.returncode, "ids": lines[:3], "status": view,
                "effective_caps": names(view.get("CapEff", "0")),
                "bounding_caps_count": len(names(view.get("CapBnd", "0"))),
                "stderr": done.stderr[-400:],
            }
        record["bwrap_builds_j1_as_h_root"] = record["pre_drop_with_cap_drop_all"]["rc"] == 0
        pre = record["pre_drop_with_cap_drop_all"]["effective_caps"]
        record["pre_drop_is_exactly_three"] = sorted(pre) == sorted(CAPS.values())

        # Post-drop view under the exact filter, and the mount points.
        f = fds()
        filter_fd = memfd(program)
        done, argv = run_chain(enter, mounts(work, binds, f), [
            "/bin/sh", "-c",
            'id -u; id -g; id -G; grep -E "^(Cap|NoNewPrivs|Seccomp)" /proc/self/status; '
            'awk "{print \\$5}" /proc/self/mountinfo | sort | tr "\\n" " "'], f, filter_fd=filter_fd)
        os.close(filter_fd)
        lines = done.stdout.splitlines()
        view = caps_of(done.stdout)
        record["post_drop"] = {"rc": done.returncode, "ids": lines[:3], "status": view,
                               "mount_points": lines[-1].split() if lines else [],
                               "stderr": done.stderr[-400:]}
        caps_zero = all(view.get(k) == "0000000000000000"
                        for k in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
        record["post_drop_ok"] = (done.returncode == 0 and lines[:3] == [str(SEAT)] * 3 and caps_zero
                                  and view.get("NoNewPrivs") == "1" and view.get("Seccomp") == "2")
        record["argv_shape"] = [a if not a.isdigit() else "<n>" for a in argv[:8]] + ["..."]

        # CLIs as the seat uid, under the exact filter.
        tools = {
            "claude --version": ["/seat/bin/claude", "--version"],
            "agy --version": ["/seat/bin/agy", "--version"],
            "node": ["/usr/bin/node", "-e", "require('child_process').execSync('true');console.log(process.version)"],
            "python3 threads+subprocess": ["/usr/bin/python3", "-c",
                                           "import threading,subprocess;t=threading.Thread(target=print);t.start();t.join();print(subprocess.run(['true']).returncode)"],
            "git": ["/usr/bin/git", "-C", "/seat/tree", "init", "-q", "probe-repo"],
            "pip": ["/usr/bin/python3", "-m", "pip", "--version"],
        }
        results = {}
        for label, cmd in tools.items():
            f = fds()
            filter_fd = memfd(program)
            done, _ = run_chain(enter, mounts(work, binds, f), cmd, f, filter_fd=filter_fd)
            os.close(filter_fd)
            results[label] = {"rc": done.returncode, "stdout": done.stdout.strip()[-200:],
                              "stderr": done.stderr.strip()[-300:]}
        results["uv"] = {"rc": None, "note": "uv is installed outside /usr on this host "
                         f"({os.path.realpath(shutil.which('uv') or '') or 'absent'}); toolchains "
                         "outside /usr are a plan non-goal"}
        record["clis"] = results
        cli_ok = all(v["rc"] == 0 for k, v in results.items() if k != "uv")

        # The seat creates a 0600 file; the in-H reader (H-root) reads it; the operator cannot.
        f = fds()
        done, _ = run_chain(enter, mounts(work, binds, f), [
            "/bin/sh", "-c", "umask 077; echo seat-secret > /seat/out/private.txt; ls -ln /seat/out"], f)
        operator_read = True
        try:
            (work / "out" / "private.txt").read_text()
        except PermissionError:
            operator_read = False
        reader = subprocess.run([*enter, "/bin/cat", str(work / "out" / "private.txt")],
                                capture_output=True, text=True)
        record["in_h_reader"] = {"seat_write_rc": done.returncode, "listing": done.stdout.strip(),
                                 "operator_can_read_from_host": operator_read,
                                 "in_h_reader_rc": reader.returncode,
                                 "in_h_reader_read": reader.stdout.strip() == "seat-secret"}

        if not record["bwrap_builds_j1_as_h_root"]:
            stops.append("bwrap cannot build the jail as H-root")
        if not record["post_drop_ok"]:
            stops.append("a capability survives the drop, or the seat view is wrong")
        if not cli_ok:
            stops.append("a CLI does not run as the seat uid under the filter")
        record["stops"] = stops
        record["result"] = "stop" if stops else "pass"
    finally:
        if proc is not None:
            subprocess.run([*enter, "/bin/rm", "-rf", str(work)], capture_output=True)
            proc.kill()
            proc.wait()
        shutil.rmtree(work, ignore_errors=True)
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": record["result"], "stops": stops,
                      "pre_drop_is_exactly_three": record["pre_drop_is_exactly_three"],
                      "post_drop_ok": record["post_drop_ok"]}))
    return 0 if not stops else 3


if __name__ == "__main__":
    raise SystemExit(main())
