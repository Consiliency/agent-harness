"""ci/offload-gate.sh holds a host-side lock for the whole `dagger call`.

Two offloaded suites sharing one Dagger engine kill each other (the engine's
session-end prune removes the rootfs of the sibling's running containers --
Consiliency/agent-harness#746 diagnosis). The script takes a `flock` ON THE
ENGINE HOST, over the same ssh route the engine uses, and holds it until the
`dagger call` returns. These tests drive the script with a stub `ssh` that runs
the remote command locally and a stub `dagger` that records when it ran.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ci" / "offload-gate.sh"

assert shutil.which("flock"), "flock (util-linux) is required for these tests"

_SSH_STUB = """#!/usr/bin/env bash
# ssh [-p PORT] <host> <command...>: run the remote command locally, record the target.
set -euo pipefail
if [ "$1" = "-p" ]; then echo "port=$2" >>"$STUB_LOG.ssh"; shift 2; fi
echo "$1" >>"$STUB_LOG.ssh"
shift
exec bash -c "$*"
"""

_DAGGER_STUB = """#!/usr/bin/env bash
# dagger -m <mod> call all ... export --path=<dir>: record an interval, produce evidence.
set -euo pipefail
start=$(date +%s.%N)
sleep "${DAGGER_STUB_SECONDS:-1.5}"
for a in "$@"; do case "$a" in --path=*) mkdir -p "${a#--path=}"; echo "stub verdicts" >"${a#--path=}/verdicts.txt";; esac; done
echo "$start $(date +%s.%N)" >>"$STUB_LOG.dagger"
exit "${DAGGER_STUB_EXIT:-0}"
"""


@pytest.fixture()
def harness(tmp_path: Path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("ssh", _SSH_STUB), ("dagger", _DAGGER_STUB)):
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    lock = tmp_path / "engine.lock"

    def run(label: str, *, wait: int = 30, docker_host: str | None = None, extra: dict[str, str] | None = None):
        workdir = tmp_path / label
        workdir.mkdir()
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "AGENT_DAGGER": "1",
            "AGENT_REMOTE_HOST": "engine-host",
            "OFFLOAD_LOCK": str(lock),
            "OFFLOAD_LOCK_WAIT_SECONDS": str(wait),
            "STUB_LOG": str(tmp_path / f"{label}.log"),
            "CHRONOLOGY": "false",
        }
        if docker_host is not None:
            env["DOCKER_HOST"] = docker_host
        env.update(extra or {})
        # A script that never releases (or never returns) must fail the test, not hang it.
        return subprocess.run(["bash", str(SCRIPT)], cwd=workdir, env=env, capture_output=True, text=True, timeout=60)

    def intervals(label: str) -> list[tuple[float, float]]:
        f = tmp_path / f"{label}.log.dagger"
        if not f.exists():
            return []
        return [tuple(float(x) for x in line.split()) for line in f.read_text().splitlines()]

    def ssh_hosts(label: str) -> list[str]:
        f = tmp_path / f"{label}.log.ssh"
        return f.read_text().split() if f.exists() else []

    return run, intervals, ssh_hosts, lock


def test_two_concurrent_offloads_never_overlap_the_dagger_call(harness) -> None:
    run, intervals, ssh_hosts, _ = harness
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run, "a")
        b = pool.submit(run, "b")
        ra, rb = a.result(), b.result()
    assert ra.returncode == 0, ra.stdout + ra.stderr
    assert rb.returncode == 0, rb.stdout + rb.stderr
    (sa, ea), (sb, eb) = intervals("a")[0], intervals("b")[0]
    assert ea <= sb or eb <= sa, f"dagger calls overlapped: a=({sa},{ea}) b=({sb},{eb})"
    assert ssh_hosts("a") == ["engine-host"] and ssh_hosts("b") == ["engine-host"]
    for r in (ra, rb):
        assert "offload lock: held" in r.stdout and "offload lock: released" in r.stdout


def test_lock_wait_exhausted_fails_closed_without_calling_dagger(harness) -> None:
    run, intervals, _, lock = harness
    holder = subprocess.Popen(["flock", str(lock), "-c", "sleep 8"])
    try:
        time.sleep(0.5)  # let the holder take the lock
        r = run("late", wait=1)
    finally:
        holder.kill()
        holder.wait()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "refusing to run unlocked" in r.stderr
    assert intervals("late") == [], "dagger must not run without the lock"


def test_lock_is_released_when_dagger_fails(harness) -> None:
    run, intervals, _, lock = harness
    r = run("bad", extra={"DAGGER_STUB_EXIT": "3"})
    assert r.returncode == 3, r.stdout + r.stderr
    assert intervals("bad"), "dagger ran under the lock"
    probe = subprocess.run(["flock", "-n", str(lock), "-c", "true"])
    assert probe.returncode == 0, "lock still held after the script exited"


def test_non_ssh_engine_skips_the_lock(harness) -> None:
    run, intervals, ssh_hosts, _ = harness
    r = run("local", docker_host="unix:///var/run/docker.sock")
    assert r.returncode == 0, r.stdout + r.stderr
    assert intervals("local") and ssh_hosts("local") == []
    assert "nothing to serialise against" in r.stderr


def test_engine_port_is_passed_to_ssh_as_a_flag(harness) -> None:
    run, intervals, ssh_hosts, _ = harness
    r = run("port", docker_host="ssh://ci@engine-host:2222")
    assert r.returncode == 0, r.stdout + r.stderr
    assert intervals("port")
    assert ssh_hosts("port") == ["port=2222", "ci@engine-host"]


def test_script_is_executable_and_parses() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
