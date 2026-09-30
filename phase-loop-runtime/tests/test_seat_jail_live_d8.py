"""Live D8 falsifiers (agent-harness#1132): J4, J6, J15, the hand-off and reap, on the real
seat-uid chain.

These run the PRODUCTION pieces end to end, with nothing faked:
- `sandbox_egress.isolated_network(seat_uid_map=True)`, whose holder is mapped by the real
  `newuidmap`/`newgidmap`;
- the `flock` seat-id lease;
- `seat_jail.build_seat_jail`;
- `panel_invoker._compose_seat_jail_prefix`, with the keyring shim, `nsenter`, the hand-off,
  bwrap and `setpriv`;
- `panel_invoker._require_jailed_seat_identity`.

They need the maintainer's host prerequisite. Without it they skip, and the skip reason
names that prerequisite.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import sandbox_egress, seat_jail, seat_uid

from ._seat_prereq import SEAT_UID_PREREQUISITE, seat_uid_ready

pytestmark = [
    pytest.mark.skipif(not seat_uid_ready(), reason=SEAT_UID_PREREQUISITE),
    pytest.mark.skipif(not sandbox_egress.egress_isolation_available(),
                       reason="needs unshare + slirp4netns + iptables"),
]


@contextlib.contextmanager
def live_seat(tmp_path: Path, name: str = "a", *, extra_owner: list[str] | None = None):
    """One jailed seat on the real D8 chain. Yields (jail, prefix, holder pid, dirs)."""
    base = Path(tempfile.mkdtemp(prefix=f"pl-live-{name}-", dir=tmp_path))
    review = base / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "src.py").write_text("value = 1\n")
    seat_dir = base / "seat"
    seat_dir.mkdir(mode=0o700)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=600, required=True, seat_uid_map=True) as egress:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        holder = seat_uid.holder_pid_from_prefix(egress)
        jail = seat_jail.build_seat_jail(
            "claude", seat_dir, Path("/usr/bin/true"), tree=tree,
            bundle_memfd=seat_jail.memfd_with("b", b"BUNDLE"),
            instructions_memfd=seat_jail.memfd_with("i", b"INSTRUCTIONS"),
            token_fd=seat_jail.token_pipe(b"SEAT-JAIL-SENTINEL-live"), seat_ids=(n, n))
        if extra_owner:
            owner = list(jail.process_owner)
            at = owner.index("--remount-ro")
            owner[at:at] = extra_owner
            object.__setattr__(jail, "process_owner", tuple(owner))
        try:
            yield jail, pi._compose_seat_jail_prefix(jail), holder, {
                "base": base, "review": review, "tree": tree, "seat": seat_dir, "n": n}
        finally:
            seat_jail.close_jail_fds(jail)
            for parent in (review, seat_dir):
                seat_uid.teardown_in_h(holder, str(parent))
            pi._EGRESS_LAUNCH_PREFIX.reset(token)


def _run(prefix, jail, script, *args, timeout=60):
    return subprocess.run([*prefix, "/bin/sh", "-c", script, "sh", *args], capture_output=True,
                          text=True, timeout=timeout, pass_fds=jail.pass_fds,
                          env=seat_uid._pythonpath_env())


# --------------------------------------------------------------------------------------
# J6 / J15: the seat is its subordinate uid, with nothing left.
# --------------------------------------------------------------------------------------

def test_j6_live_identity_probe_passes_through_the_production_prefix(tmp_path):
    with live_seat(tmp_path) as (jail, prefix, _holder, _dirs):
        pi._require_jailed_seat_identity(prefix, jail, jail.pass_fds)


def test_j6_live_setuid_and_uid_map_writes_fail(tmp_path):
    script = ('python3 -c "import os\ntry:\n os.setuid(0); print(\'SETUID-OK\')\nexcept OSError: print(\'setuid-refused\')"; '
              'echo "0 0 1" > /proc/self/uid_map 2>/dev/null && echo MAP-OK || echo map-refused')
    with live_seat(tmp_path) as (jail, prefix, _h, _d):
        done = _run(prefix, jail, script)
    assert "setuid-refused" in done.stdout and "map-refused" in done.stdout, done


def test_j6_live_mutation_skipping_the_bounding_drop_shows_capbnd(tmp_path):
    """Mutation: omit `--bounding-set=-all` -- the probe's CapBnd is no longer 0."""
    with live_seat(tmp_path) as (jail, prefix, _h, _d):
        mutated = list(prefix)
        mutated.remove("--bounding-set=-all")
        done = _run(mutated, jail, 'grep CapBnd /proc/self/status')
        with pytest.raises(seat_jail.SeatSandboxRefused):
            pi._require_jailed_seat_identity(mutated, jail, jail.pass_fds)
    assert "0000000000000000" not in done.stdout


def test_j6_live_mutation_skipping_setpriv_leaves_h_root_with_three_caps(tmp_path):
    with live_seat(tmp_path) as (jail, prefix, _h, _d):
        drop = prefix.index("/usr/bin/setpriv")
        mutated = prefix[:drop] + prefix[prefix.index("/usr/bin/env", drop):]
        done = _run(mutated, jail, 'id -u; grep CapEff /proc/self/status')
    lines = done.stdout.split()
    assert lines[0] == "0" and "00000000000001c0" in done.stdout


def test_j15_dac_is_a_second_layer_under_the_mounts(tmp_path):
    """A test-only READ-WRITE bind of operator-owned objects: DAC alone refuses the seat."""
    canary_dir = tmp_path / "operator-dir"
    canary_dir.mkdir(mode=0o755)
    canary = canary_dir / "file"
    canary.write_text("operator\n")
    canary.chmod(0o644)
    extra = ["--bind", str(canary_dir), "/seat/operator"]
    with live_seat(tmp_path, extra_owner=extra) as (jail, prefix, _h, _d):
        done = _run(prefix, jail, 'echo x >> /seat/operator/file 2>/dev/null && echo WROTE-FILE; '
                                  'touch /seat/operator/new 2>/dev/null && echo WROTE-DIR; cat /seat/operator/file')
    assert "WROTE" not in done.stdout and "operator" in done.stdout
    assert canary.read_text() == "operator\n" and not (canary_dir / "new").exists()


def test_j15_nothing_operator_owned_is_writable_in_the_host_backed_mounts(tmp_path):
    with live_seat(tmp_path) as (jail, prefix, holder, dirs):
        _run(prefix, jail, "touch /seat/tree/new /seat/home/new /seat/out/new")
        found = subprocess.run(
            ["/usr/bin/nsenter", "-t", str(holder), "-U", "-m", "--preserve-credentials",
             "/usr/bin/find", str(dirs["tree"]), str(dirs["seat"] / "seat-home"),
               str(dirs["seat"] / "seat-out"), "!", "-uid", str(dirs["n"]), "-print"],
            capture_output=True, text=True)
    assert found.returncode == 0 and found.stdout.strip() == "", found


# --------------------------------------------------------------------------------------
# The hand-off (private inodes) on the real chain.
# --------------------------------------------------------------------------------------

def test_handoff_live_refuses_a_hard_link_and_leaves_the_outside_file_alone(tmp_path):
    outside = tmp_path / "operator-secret"
    outside.write_text("secret")
    outside.chmod(0o600)
    with live_seat(tmp_path) as (jail, prefix, _h, dirs):
        os.link(outside, dirs["tree"] / "planted")
        done = _run(prefix, jail, "echo RAN")
    assert "RAN" not in done.stdout
    assert "seat_sandbox_refused:stage_not_private" in done.stderr
    info = outside.stat()
    assert info.st_uid == os.getuid() and info.st_mode & 0o777 == 0o600


# --------------------------------------------------------------------------------------
# J4: concurrent seats cannot reach each other.
# --------------------------------------------------------------------------------------

def test_j4_live_concurrent_seats_are_isolated(tmp_path):
    with live_seat(tmp_path, "a") as (jail_a, prefix_a, holder_a, dirs_a), \
            live_seat(tmp_path, "b") as (jail_b, prefix_b, _hb, dirs_b):
        assert dirs_a["n"] != dirs_b["n"], "concurrent seats must lease distinct uids"
        sleeper = subprocess.Popen(
            [*prefix_a, "/bin/sh", "-c", "echo A-SECRET > /seat/out/sentinel; exec sleep 61.4321"],
            pass_fds=jail_a.pass_fds, env=seat_uid._pythonpath_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = 50
            a_pids = []
            while deadline and not a_pids:
                a_pids = [p for p in os.listdir("/proc") if p.isdigit()
                          and _cmdline(p) == "sleep\x0061.4321\x00"]
                deadline -= 1
                subprocess.run(["sleep", "0.1"])
            assert a_pids, ("seat A's sleeper was not found on the host",
                            sleeper.poll(), sleeper.stderr.read() if sleeper.poll() is not None else "")
            pid = a_pids[0]
            out_a = dirs_a["seat"] / "seat-out"
            done = _run(prefix_b, jail_b, (
                f'cat "{out_a}/sentinel" 2>/dev/null && echo READ-HOST-PATH; '
                f'ls /proc/{pid} >/dev/null 2>&1 && echo SAW-PID; '
                f'cat /proc/{pid}/environ 2>/dev/null && echo READ-ENVIRON; '
                f'kill -0 {pid} 2>/dev/null && echo SIGNALLED; '
                'cat /seat/out/sentinel 2>/dev/null && echo READ-OWN-ALIAS; echo done'))
        finally:
            sleeper.kill()
            sleeper.wait()
    assert done.stdout.strip().endswith("done"), done
    for leak in ("READ-HOST-PATH", "SAW-PID", "READ-ENVIRON", "SIGNALLED", "READ-OWN-ALIAS", "A-SECRET"):
        assert leak not in done.stdout, done.stdout


def _cmdline(pid: str) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_text()
    except OSError:
        return ""


# --------------------------------------------------------------------------------------
# Retention and reap (F022) on a real seat-owned directory.
# --------------------------------------------------------------------------------------

def test_live_reap_removes_a_recorded_seat_owned_directory(tmp_path, monkeypatch):
    records = tmp_path / "records"
    monkeypatch.setattr(seat_uid, "retention_dir", lambda: records)
    monkeypatch.setattr(seat_uid, "stage_root", lambda: tmp_path.resolve())
    with live_seat(tmp_path) as (jail, prefix, holder, dirs):
        _run(prefix, jail, "mkdir -p /seat/home/deep && umask 077 && echo x > /seat/home/deep/f")
        target = dirs["seat"] / "seat-home"
        assert os.stat(target).st_uid == seat_uid.subordinate_host_uid(dirs["n"])
        seat_uid.record_retention(target, directory=records)
        seat_uid.reap(str(target))
        assert not target.exists()


# --------------------------------------------------------------------------------------
# P5/P1 findings folded into the production jail, each proven on the live chain.
# --------------------------------------------------------------------------------------

def test_live_seat_can_use_tmp_etc_and_its_tree(tmp_path):
    """The seat uid can write its sticky tmpfs, traverse /etc and /seat, and starts in its
    tree. Each broke on the plan's literal argv (P5 and P1)."""
    script = ('pwd; touch /tmp/t /dev/shm/t && echo tmp-ok; cat /etc/ssl/openssl.cnf >/dev/null && '
              'echo etc-ok; test -x /seat/bin/claude && echo seat-ok')
    with live_seat(tmp_path) as (jail, prefix, _h, _d):
        done = _run(prefix, jail, script)
    assert done.stdout.split() == ["/seat/tree", "tmp-ok", "etc-ok", "seat-ok"], done


def test_live_pre_drop_set_is_exactly_the_three_capabilities(tmp_path):
    """P5: bwrap as H-root keeps every capability unless `--cap-drop ALL` comes first."""
    with live_seat(tmp_path) as (jail, prefix, _h, _d):
        drop = prefix.index("/usr/bin/setpriv")
        done = subprocess.run([*prefix[:drop], "/bin/sh", "-c", "grep CapEff /proc/self/status"],
                              capture_output=True, text=True, pass_fds=jail.pass_fds,
                              env=seat_uid._pythonpath_env(), timeout=60)
    assert done.stdout.split() == ["CapEff:", "00000000000001c0"], done


# --------------------------------------------------------------------------------------
# Tool use (plan "Tests": a jailed Claude seat runs a command and quotes its output).
# Runs for real once the maintainer's seat token is in place (P2); the EC-EXECFIND-2 gate
# sits above `_prepare_jailed_claude`, so this drives the jailed leg directly.
# --------------------------------------------------------------------------------------

def test_live_jailed_claude_runs_a_tool_and_quotes_it(tmp_path):
    import hashlib
    import types

    from phase_loop_runtime import review_stage

    from ._seat_prereq import require_seat_token

    require_seat_token()
    subject = "seat-jail-tool-use-" + hashlib.sha256(os.urandom(8)).hexdigest()[:12]
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@e.st"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", subject],
                   check=True)
    base = Path(tempfile.mkdtemp(prefix="pl-live-tool-", dir=tmp_path))
    review = base / "review"
    review.mkdir()
    staged = review_stage.stage_review_tree(repo, review)
    staged.rename(review / seat_jail.HOST_TREE_DIRNAME)
    auth = types.SimpleNamespace(staged_tree_sha256=review_stage.review_tree_manifest_sha256(
        review / seat_jail.HOST_TREE_DIRNAME))
    instructions = ("Run `git log -1 --format=%s` in /seat/tree and reply with its exact output "
                    "on one line, then the verdict AGREE.")
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
            sandbox_egress.isolated_network(timeout_s=1200, required=True, seat_uid_map=True) as egress:
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
        try:
            seat = pi._prepare_jailed_claude(review, base / "seat", auth, n,
                                             seat_uid.holder_pid_from_prefix(egress),
                                             ("BUNDLE: see the tree.", instructions))
            prompt = pi._render_broker_pointer_prompt(
                "BUNDLE: see the tree.", instructions,
                source_commit=(review / seat_jail.HOST_TREE_DIRNAME / ".git"
                               / "phase-loop-source-commit").read_text().strip(),
                staged_tree_sha256=auth.staged_tree_sha256)
            status, text = pi._exec_jailed_claude_leg(
                seat, timeout_s=600, backstop_s=900, model=None, effort="low", prompt=prompt,
                broker_evidence={})
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)
    assert status == "OK", (status, text)
    assert subject in text
