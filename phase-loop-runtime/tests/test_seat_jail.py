"""Falsifiers for the per-seat jail (agent-harness#1132): J1-J3, J10, J14, D7, keyring.

Layer rule (plan "Tests and falsifiers"): each fixture isolates the layer it tests. The
live jail tests here run the PRODUCTION bwrap argv from `seat_jail.build_seat_jail` with
one test-only change -- an operator-uid user namespace (`--unshare-user`) in place of the
D8 seat-uid holder, which needs the maintainer's root prerequisite. That fixture disables
the uid layer on purpose, so the mount, environment, descriptor and seccomp layers are
each proven on their own. The uid layer (J15) is in `test_seat_sandbox_permissions.py`,
skip-guarded on the prerequisite.

The seccomp filter is proven two ways: an independent classic-BPF interpreter below runs
the exact production bytes against synthetic `seccomp_data` (filter-level proofs), and
the kernel loads the same bytes through `bwrap --seccomp` (live proofs).
"""

from __future__ import annotations

import base64
import binascii
import errno
import json
import os
import platform
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from phase_loop_runtime import review_stage, seat_jail, seat_keyring_exec

from ._seat_prereq import requires_userns

X86 = seat_jail.AUDIT_ARCH_X86_64
I386 = seat_jail.AUDIT_ARCH_I386
NR = {"unshare": 272, "clone": 56, "setns": 308, "clone3": 435, "keyctl": 250,
      "add_key": 248, "request_key": 249, "socket": 41, "socketpair": 53, "ioctl": 16,
      "read": 0, "getpid": 39}
ALLOW = 0x7FFF0000
EPERM = 0x00050000 | errno.EPERM
ENOSYS = 0x00050000 | errno.ENOSYS
KILL = 0x80000000


# --------------------------------------------------------------------------------------
# An independent classic-BPF interpreter (the verifier never derives from the builder).
# --------------------------------------------------------------------------------------

def run_bpf(program: bytes, *, nr: int, arch: int, args: tuple[int, ...] = ()) -> int:
    args = tuple(args) + (0,) * (6 - len(args))
    data = struct.pack("<iIQ6Q", nr, arch, 0, *args)
    insns = [struct.unpack("<HBBI", program[i:i + 8]) for i in range(0, len(program), 8)]
    acc = 0
    pc = 0
    while True:
        code, jt, jf, k = insns[pc]
        if code == 0x20:  # BPF_LD | BPF_W | BPF_ABS
            acc = struct.unpack_from("<I", data, k)[0]
            pc += 1
        elif code == 0x15:  # JEQ K
            pc += 1 + (jt if acc == k else jf)
        elif code == 0x35:  # JGE K
            pc += 1 + (jt if acc >= k else jf)
        elif code == 0x45:  # JSET K
            pc += 1 + (jt if acc & k else jf)
        elif code == 0x06:  # RET K
            return k
        else:  # pragma: no cover - an opcode the builder must never emit
            raise AssertionError(f"unexpected BPF opcode {code:#x}")


@pytest.fixture(scope="module")
def prog() -> bytes:
    return seat_jail.build_seccomp_filter("x86_64")


def test_j14_architecture_rule_kills_i386(prog):
    assert run_bpf(prog, nr=NR["getpid"], arch=I386) == KILL


def test_j14_every_x32_number_is_eperm_before_per_syscall_rules(prog):
    x32 = 0x40000000
    assert run_bpf(prog, nr=NR["unshare"] | x32, arch=X86, args=(0x10020000,)) == EPERM
    # The witness that the threshold fires first: native clone3 is ENOSYS, x32 clone3 EPERM.
    assert run_bpf(prog, nr=NR["clone3"] | x32, arch=X86) == EPERM
    assert run_bpf(prog, nr=NR["keyctl"] | x32, arch=X86, args=(11,)) == EPERM
    assert run_bpf(prog, nr=NR["setns"] | x32, arch=X86) == EPERM
    assert run_bpf(prog, nr=NR["getpid"] | x32, arch=X86) == EPERM


@pytest.mark.parametrize("call", ["unshare", "clone"])
@pytest.mark.parametrize("flags", [0x10000000, 0x00020000, 0x10020000, 0x10000011])
def test_j14_namespace_flags_are_eperm(prog, call, flags):
    assert run_bpf(prog, nr=NR[call], arch=X86, args=(flags,)) == EPERM


def test_j14_setns_is_eperm_even_with_nstype_zero(prog):
    assert run_bpf(prog, nr=NR["setns"], arch=X86, args=(3, 0)) == EPERM


def test_j14_clone3_is_enosys(prog):
    assert run_bpf(prog, nr=NR["clone3"], arch=X86) == ENOSYS


@pytest.mark.parametrize("call", ["keyctl", "add_key", "request_key"])
def test_j14_key_syscalls_are_eperm(prog, call):
    assert run_bpf(prog, nr=NR[call], arch=X86) == EPERM


def test_j14_af_alg_sockets_only(prog):
    assert run_bpf(prog, nr=NR["socket"], arch=X86, args=(38, 5, 0)) == EPERM
    assert run_bpf(prog, nr=NR["socketpair"], arch=X86, args=(38, 5, 0)) == EPERM
    assert run_bpf(prog, nr=NR["socket"], arch=X86, args=(2, 1, 0)) == ALLOW
    assert run_bpf(prog, nr=NR["socket"], arch=X86, args=(1, 1, 0)) == ALLOW


@pytest.mark.parametrize("ioctl_req", [0x5412, 0x541C, 0x1_0000_5412, 0xFFFF_FFFF_0000_541C])
def test_j14_tiocsti_and_tioclinux_compare_the_low_half_only(prog, ioctl_req):
    assert run_bpf(prog, nr=NR["ioctl"], arch=X86, args=(0, ioctl_req)) == EPERM


def test_j14_allowed_controls(prog):
    assert run_bpf(prog, nr=NR["read"], arch=X86) == ALLOW
    # clone with thread flags (CLONE_VM|FS|FILES|SIGHAND|THREAD|SYSVSEM|SETTLS|...)
    assert run_bpf(prog, nr=NR["clone"], arch=X86, args=(0x003D0F00,)) == ALLOW
    assert run_bpf(prog, nr=NR["ioctl"], arch=X86, args=(0, 0x5401)) == ALLOW


def test_j14_aarch64_filter_is_built_for_its_own_arch():
    arm = seat_jail.build_seccomp_filter("aarch64")
    assert run_bpf(arm, nr=97, arch=seat_jail.AUDIT_ARCH_AARCH64, args=(0x10000000,)) == EPERM
    assert run_bpf(arm, nr=97, arch=X86) == KILL
    # No x32 rule on aarch64: a high number is simply not a denied syscall.
    assert run_bpf(arm, nr=0x40000000 | 172, arch=seat_jail.AUDIT_ARCH_AARCH64) == ALLOW


def test_j14_test_only_variant_has_its_own_digest():
    variant = seat_jail.build_seccomp_filter("x86_64", key_rules=False)
    assert seat_jail.filter_digest(variant) != seat_jail.production_filter_digest("x86_64")
    assert run_bpf(variant, nr=NR["keyctl"], arch=X86) == ALLOW


# --------------------------------------------------------------------------------------
# J14 live: the kernel loads the exact bytes.
# --------------------------------------------------------------------------------------

_LIVE_PROBE = r"""
import ctypes, errno, json, socket, subprocess, threading
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
def sc(nr, *a):
    r = libc.syscall(ctypes.c_long(nr), *[ctypes.c_long(x) for x in a])
    return errno.errorcode.get(ctypes.get_errno(), "0") if r < 0 else "ok"
out = {
  "unshare_user": sc(272, 0x10000000), "unshare_ns": sc(272, 0x00020000),
  "setns0": sc(308, -1, 0), "clone3": sc(435, 0, 0), "keyctl": sc(250, 0, 0),
  "add_key": sc(248, 0, 0, 0, 0, 0), "request_key": sc(249, 0, 0, 0, 0),
  "x32": sc(39 | 0x40000000),
  "tiocsti_hi": sc(16, 0, 0x100005412, 0), "tioclinux": sc(16, 0, 0x541C, 0),
}
try:
    socket.socket(38, socket.SOCK_SEQPACKET, 0); out["af_alg"] = "ok"
except OSError as e:
    out["af_alg"] = errno.errorcode[e.errno]
t = threading.Thread(target=lambda: None); t.start(); t.join(); out["thread"] = "ok"
out["subprocess"] = subprocess.run(["true"]).returncode
print(json.dumps(out))
"""


def _bwrap_filtered(argv: list[str], program: bytes | None) -> subprocess.CompletedProcess:
    base = ["/usr/bin/bwrap", "--unshare-user", "--dev-bind", "/", "/"]
    if program is None:
        return subprocess.run([*base, *argv], capture_output=True, text=True, timeout=60)
    fd = seat_jail.memfd_with("t-filter", program)
    try:
        return subprocess.run([*base, "--seccomp", str(fd), *argv], capture_output=True,
                              text=True, timeout=60, pass_fds=(fd,))
    finally:
        os.close(fd)


x86_only = pytest.mark.skipif(platform.machine() != "x86_64", reason="x86_64 syscall numbers")


@requires_userns
@x86_only
def test_j14_live_filter_denies_in_the_kernel():
    done = _bwrap_filtered([sys.executable, "-c", _LIVE_PROBE], seat_jail.build_seccomp_filter())
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout)
    assert seen == {
        "unshare_user": "EPERM", "unshare_ns": "EPERM", "setns0": "EPERM", "clone3": "ENOSYS",
        "keyctl": "EPERM", "add_key": "EPERM", "request_key": "EPERM", "x32": "EPERM",
        "tiocsti_hi": "EPERM", "tioclinux": "EPERM", "af_alg": "EPERM",
        "thread": "ok", "subprocess": 0,
    }


@requires_userns
@x86_only
def test_j14_live_end_to_end_mutation_omit_seccomp():
    """The one live mutation sound on this host: no `--seccomp` at all, and the nested
    user namespace and AF_ALG socket succeed."""
    done = _bwrap_filtered([sys.executable, "-c", _LIVE_PROBE], None)
    seen = json.loads(done.stdout)
    assert seen["unshare_user"] == "ok" and seen["clone3"] != "ENOSYS"


@requires_userns
@x86_only
def test_j14_live_i386_int80_is_killed(tmp_path):
    source = tmp_path / "i386.c"
    source.write_text('int main(void){long r;__asm__ volatile("int $0x80":"=a"(r):"a"(20));return 0;}\n')
    binary = tmp_path / "i386"
    if subprocess.run(["cc", "-O0", "-o", str(binary), str(source)], capture_output=True).returncode:
        pytest.skip("no C compiler for the int 0x80 probe")
    assert _bwrap_filtered([str(binary)], None).returncode == 0
    killed = _bwrap_filtered([str(binary)], seat_jail.build_seccomp_filter())
    assert killed.returncode == 128 + 31, killed  # SIGSYS: SECCOMP_RET_KILL_PROCESS


@requires_userns
@pytest.mark.parametrize("argv", [
    ["git", "--version"], ["node", "-e", "require('child_process').execSync('true')"],
    [sys.executable, "-c", "import threading;t=threading.Thread(target=print);t.start();t.join()"],
])
def test_j14_probe_coverage_real_tools_run_under_the_filter(argv):
    if subprocess.run(["which", argv[0]], capture_output=True).returncode:
        pytest.skip(f"{argv[0]} not installed")
    done = _bwrap_filtered(argv, seat_jail.build_seccomp_filter())
    assert done.returncode == 0, done.stderr


# --------------------------------------------------------------------------------------
# J1-J3 live: the production jail argv, with an operator-uid user namespace.
# --------------------------------------------------------------------------------------

SENTINEL_TOKEN = b"SEAT-JAIL-SENTINEL-1132-" + b"x" * 24


def _review_dir(tmp_path: Path) -> Path:
    review = tmp_path / "review"
    (review / seat_jail.HOST_TREE_DIRNAME).mkdir(parents=True)
    (review / seat_jail.HOST_TREE_DIRNAME / "src.py").write_text("x = 1\n")
    return review


def _test_owner(jail: seat_jail.SeatJail) -> list[str]:
    """The production owner, with an operator-uid user namespace in place of D8's H."""
    owner = list(jail.process_owner)
    owner[1:1] = ["--unshare-user", "--uid", str(os.getuid()), "--gid", str(os.getgid())]
    return owner


def _jail(tmp_path: Path, *, token: bytes | None = SENTINEL_TOKEN, **kw) -> seat_jail.SeatJail:
    review = _review_dir(tmp_path)
    bundle = seat_jail.memfd_with("b", b"THE BUNDLE")
    brief = seat_jail.memfd_with("i", b"THE INSTRUCTIONS")
    token_fd = seat_jail.token_pipe(token) if token is not None else None
    return seat_jail.build_seat_jail("claude", review, Path("/usr/bin/true"),
                                     bundle_memfd=bundle, instructions_memfd=brief,
                                     token_fd=token_fd, seat_ids=(1, 1), **kw)


def _run_in(jail: seat_jail.SeatJail, script: str, *args: str,
            owner: list[str] | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([*(owner or _test_owner(jail)), "/bin/sh", "-c", script, "sh", *args],
                              capture_output=True, text=True, timeout=60,
                              pass_fds=jail.pass_fds, env={"PATH": "/usr/bin:/bin"})
    finally:
        seat_jail.close_jail_fds(jail)


@requires_userns
def test_j1_mountinfo_equals_the_declared_set(tmp_path):
    jail = _jail(tmp_path)
    done = _run_in(jail, 'awk "{print \\$5}" /proc/self/mountinfo | sort')
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == seat_jail.expected_mount_points(jail)


@requires_userns
def test_j1_host_canaries_are_unreachable(tmp_path):
    canaries = []
    home_canary = Path.home() / f".pl-seat-canary-{os.getpid()}"
    home_canary.write_text("HOME-CANARY")
    home_canary.chmod(0o644)
    canaries.append(home_canary)
    workspace = Path("/mnt/workspace")
    try:
        jail = _jail(tmp_path)
        script = "; ".join(f'cat "{c}" 2>/dev/null && echo LEAK' for c in canaries) + \
            '; cat /run/user/*/bus 2>/dev/null && echo LEAK; ls "$HOME" 2>/dev/null; true'
        if workspace.is_dir():
            script += f'; ls "{workspace}" 2>/dev/null && echo LEAK'
        done = _run_in(jail, script)
        assert "LEAK" not in done.stdout and "HOME-CANARY" not in done.stdout
    finally:
        home_canary.unlink()


@requires_userns
def test_j1_mutation_binding_home_exposes_the_canary(tmp_path):
    """Mutation: `--ro-bind $HOME $HOME` -- the canary becomes readable."""
    canary = Path.home() / f".pl-seat-canary-m-{os.getpid()}"
    canary.write_text("HOME-CANARY")
    canary.chmod(0o644)
    try:
        jail = _jail(tmp_path)
        owner = _test_owner(jail)
        at = owner.index("--remount-ro")
        owner[at:at] = ["--ro-bind", str(Path.home()), str(Path.home())]
        done = _run_in(jail, f'cat "{canary}"', owner=owner)
        assert "HOME-CANARY" in done.stdout
    finally:
        canary.unlink()


@requires_userns
def test_j2_writes_are_confined(tmp_path):
    jail = _jail(tmp_path)
    done = _run_in(jail, 'for p in /x /etc/x /usr/x /seat/review/x /seat/bin/x; do '
                         'touch "$p" 2>/dev/null && echo "WROTE $p"; done; '
                         'touch /seat/tree/ok /seat/home/ok /seat/out/ok /tmp/ok && echo writable')
    assert "WROTE" not in done.stdout
    assert "writable" in done.stdout
    review = tmp_path / "review"
    assert (review / seat_jail.HOST_TREE_DIRNAME / "ok").exists()
    assert (review / seat_jail.HOST_HOME_DIRNAME / "ok").exists()


@requires_userns
def test_j2_mutation_dropping_remount_ro_lets_root_writes_land(tmp_path):
    jail = _jail(tmp_path)
    owner = _test_owner(jail)
    at = owner.index("--remount-ro")
    del owner[at:at + 2]
    done = _run_in(jail, 'touch /x && echo WROTE', owner=owner)
    assert "WROTE" in done.stdout


@requires_userns
def test_j3_environment_is_exactly_the_declared_set(tmp_path):
    jail = _jail(tmp_path)
    # The parent carries a variable the jail must NOT inherit, so dropping `--clearenv`
    # is observable (a parent env of only PATH would be masked by the jail's own PATH).
    try:
        done = subprocess.run([*_test_owner(jail), "/usr/bin/env", "-0"], capture_output=True,
                              text=True, timeout=60, pass_fds=jail.pass_fds,
                              env={"PATH": "/usr/bin:/bin", "PL_PARENT_ONLY": "1",
                                   "CLAUDE_CODE_OAUTH_TOKEN": SENTINEL_TOKEN.decode()})
    finally:
        seat_jail.close_jail_fds(jail)
    seen = dict(item.split("=", 1) for item in done.stdout.split("\0") if item)
    seen.pop("PWD", None)  # set by the shell, not the jail
    assert seen == dict(jail.env)
    assert not any(SENTINEL_TOKEN.decode() in value for value in seen.values())


@requires_userns
def test_j3_mutation_dropping_clearenv_leaks_the_parent_environment(tmp_path):
    jail = _jail(tmp_path)
    owner = _test_owner(jail)
    owner.remove("--clearenv")
    done = subprocess.run([*owner, "/usr/bin/env"], capture_output=True, text=True,
                          pass_fds=jail.pass_fds, env={"PATH": "/usr/bin:/bin",
                                                       "PL_PARENT_ONLY": "1"})
    seat_jail.close_jail_fds(jail)
    assert "PL_PARENT_ONLY=1" in done.stdout


@requires_userns
def test_j3_descriptors_are_exactly_the_declared_set(tmp_path):
    """Through the production closer: whatever this bwrap leaves open, the seat holds only
    0-2 and the token fd (a hosted CI bwrap left its data/seccomp descriptors open)."""
    jail = _jail(tmp_path)
    owner = [*_test_owner(jail), *seat_jail.seat_fd_closer(str(jail.token_fd))]
    # No pipeline: a shell holds its pipe ends while `ls` reads the shell's fd table, which
    # races (CI saw a pipe end as fd 4). A lone command leaves the shell's table as inherited.
    done = _run_in(jail, 'ls /proc/$$/fd', owner=owner)
    assert sorted(done.stdout.split(), key=int) == [str(fd) for fd in sorted({0, 1, 2, jail.token_fd})]


@requires_userns
def test_j3_the_closer_closes_a_leaked_descriptor(tmp_path):
    jail = _jail(tmp_path)
    leak_r, leak_w = os.pipe()
    try:
        owner = [*_test_owner(jail), *seat_jail.seat_fd_closer(str(jail.token_fd))]
        done = subprocess.run([*owner, "/bin/sh", "-c", "ls /proc/$$/fd"], capture_output=True,
                              text=True, pass_fds=(*jail.pass_fds, leak_r))
    finally:
        os.close(leak_r)
        os.close(leak_w)
        seat_jail.close_jail_fds(jail)
    assert str(leak_r) not in done.stdout.split()
    assert sorted(done.stdout.split(), key=int) == [str(fd) for fd in sorted({0, 1, 2, jail.token_fd})]


@requires_userns
def test_j3_mutation_leaking_an_extra_fd_is_visible(tmp_path):
    jail = _jail(tmp_path)
    leak_r, leak_w = os.pipe()
    try:
        done = subprocess.run([*_test_owner(jail), "/bin/sh", "-c", 'ls /proc/$$/fd'],
                              capture_output=True, text=True,
                              pass_fds=(*jail.pass_fds, leak_r))
    finally:
        os.close(leak_r)
        os.close(leak_w)
        seat_jail.close_jail_fds(jail)
    assert str(leak_r) in done.stdout.split()


@requires_userns
def test_j3_token_pipe_is_drained_once_and_bundle_is_a_sealed_memfd(tmp_path):
    jail = _jail(tmp_path)
    fd = jail.token_fd
    # `/dev/fd/N`, not `<&N`: dash redirects single-digit descriptors only.
    done = _run_in(jail, f'cat /dev/fd/{fd}; echo "|"; cat /dev/fd/{fd}; echo "|"; '
                         'cat /seat/review/review-bundle.md; '
                         'echo x >> /seat/review/review-bundle.md 2>/dev/null && echo MUTATED')
    first, second, rest = done.stdout.split("|", 2)
    assert first.strip() == SENTINEL_TOKEN.decode()
    assert second.strip() == ""
    assert "THE BUNDLE" in rest and "MUTATED" not in rest


def test_j3_harness_surfaces_never_carry_the_token(tmp_path):
    jail = _jail(tmp_path)
    try:
        rendered = json.dumps({"argv": list(jail.process_owner), "env": dict(jail.env),
                               "redacted": jail.redacted_owner()})
    finally:
        seat_jail.close_jail_fds(jail)
    for form in seat_jail.secret_encodings(SENTINEL_TOKEN):
        assert form.decode("ascii", "replace") not in rendered


# --------------------------------------------------------------------------------------
# J10: hardened reads and walks.
# --------------------------------------------------------------------------------------

def _dirfd(path: Path) -> int:
    return seat_jail.open_dir_nofollow(path)


def test_j10_reads_a_regular_file(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "out.txt").write_bytes(b"review")
    fd = _dirfd(tmp_path)
    try:
        assert seat_jail.read_regular_file_at(fd, "a/out.txt", 100) == b"review"
    finally:
        os.close(fd)


@pytest.mark.parametrize("shape", ["symlink", "fifo", "oversize", "directory", "link-dir"])
def test_j10_refuses_every_unsafe_shape_without_blocking(tmp_path, shape):
    canary = tmp_path / "canary"
    canary.write_bytes(b"HOST-CANARY")
    seat = tmp_path / "seat"
    seat.mkdir()
    target = seat / "out.txt"
    if shape == "symlink":
        target.symlink_to(canary)
    elif shape == "fifo":
        os.mkfifo(target)
    elif shape == "oversize":
        target.write_bytes(b"x" * 2048)
    elif shape == "directory":
        target.mkdir()
    else:
        (seat / "d").symlink_to(tmp_path)
        target = seat / "d" / "canary"
    fd = _dirfd(seat)
    started = time.monotonic()
    try:
        with pytest.raises(seat_jail.UnsafeSeatObject):
            seat_jail.read_regular_file_at(fd, str(target.relative_to(seat)), 1024)
    finally:
        os.close(fd)
    assert time.monotonic() - started < 5


def _stage_like(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "a.py").write_text("a\n")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "b.sh").write_text("#!/bin/sh\n")
    (repo / "pkg" / "b.sh").chmod(0o755)
    (repo / "link").symlink_to("a.py")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
                   check=True)
    return review_stage.stage_review_tree(repo, tmp_path)


def test_j10_rehash_equals_the_existing_revalidation(tmp_path):
    stage = _stage_like(tmp_path)
    fd = _dirfd(stage)
    try:
        assert seat_jail.tree_manifest_sha256_at(fd) == review_stage.review_tree_manifest_sha256(stage)
    finally:
        os.close(fd)


def test_j10_rehash_moves_on_a_flipped_byte(tmp_path):
    stage = _stage_like(tmp_path)
    before = review_stage.review_tree_manifest_sha256(stage)
    (stage / "a.py").write_text("b\n")
    fd = _dirfd(stage)
    try:
        assert seat_jail.tree_manifest_sha256_at(fd) != before
    finally:
        os.close(fd)


def test_j10_tree_walk_never_follows_a_link_or_opens_a_fifo(tmp_path):
    stage = _stage_like(tmp_path)
    fifo = tmp_path / "outside-fifo"
    os.mkfifo(fifo)
    (stage / "to-fifo").symlink_to(fifo)
    os.mkfifo(stage / "planted-fifo")
    fd = _dirfd(stage)
    started = time.monotonic()
    try:
        seat_jail.tree_manifest_sha256_at(fd)
    finally:
        os.close(fd)
    assert time.monotonic() - started < 5


def test_hard_link_handoff_precondition_detects_a_shared_inode(tmp_path):
    stage = tmp_path / "tree"
    stage.mkdir()
    outside = tmp_path / "operator-secret"
    outside.write_text("secret")
    outside.chmod(0o600)
    (stage / "sub").mkdir()
    os.link(outside, stage / "sub" / "linked")
    fd = _dirfd(stage)
    try:
        assert seat_jail.tree_is_private(fd) is False
    finally:
        os.close(fd)
    (stage / "sub" / "linked").unlink()
    (stage / "sub" / "own").write_text("mine")
    fd = _dirfd(stage)
    try:
        assert seat_jail.tree_is_private(fd) is True
    finally:
        os.close(fd)


def test_j2_teardown_never_follows_a_planted_link(tmp_path):
    canary_dir = tmp_path / "outside"
    canary_dir.mkdir()
    (canary_dir / "keep").write_text("keep")
    seat = tmp_path / "seat-home"
    (seat / "deep").mkdir(parents=True)
    (seat / "deep" / "link").symlink_to(canary_dir)
    (seat / "deep" / "file").write_text("x")
    (seat / "deep").chmod(0o500)
    parent = _dirfd(tmp_path)
    try:
        seat_jail.remove_tree_at(parent, "seat-home")
    finally:
        os.close(parent)
    assert not seat.exists()
    assert (canary_dir / "keep").read_text() == "keep"


# --------------------------------------------------------------------------------------
# The Claude seat token (D2) and the output scan.
# --------------------------------------------------------------------------------------

def _token_file(tmp_path: Path, *, dir_mode=0o700, file_mode=0o600, data=SENTINEL_TOKEN + b"\n"):
    directory = tmp_path / "seat-credentials"
    directory.mkdir(mode=0o700)
    path = directory / "claude"
    path.write_bytes(data)
    path.chmod(file_mode)
    directory.chmod(dir_mode)
    return path


def test_token_file_owner_only_is_read(tmp_path):
    assert seat_jail.read_claude_seat_token(_token_file(tmp_path)) == SENTINEL_TOKEN


@pytest.mark.parametrize("case", ["loose-file", "loose-dir", "symlink", "empty", "missing"])
def test_token_file_hygiene_refuses(tmp_path, case):
    if case == "loose-file":
        path = _token_file(tmp_path, file_mode=0o644)
    elif case == "loose-dir":
        path = _token_file(tmp_path, dir_mode=0o755)
    elif case == "empty":
        path = _token_file(tmp_path, data=b"  \n")
    elif case == "missing":
        path = tmp_path / "nowhere" / "claude"
    else:
        real = _token_file(tmp_path)
        (tmp_path / "seat-credentials").chmod(0o700)
        path = real.parent / "alias"
        path.symlink_to(real)
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        seat_jail.read_claude_seat_token(path)
    assert refused.value.code == "seat_sandbox_refused:token_file_unsafe"


def test_token_pipe_is_one_drained_channel():
    fd = seat_jail.token_pipe(SENTINEL_TOKEN)
    try:
        assert os.read(fd, 4096) == SENTINEL_TOKEN
        assert os.read(fd, 4096) == b""
    finally:
        os.close(fd)


@pytest.mark.parametrize("prefix", [b"", b"a", b"ab", b"abc"])
def test_output_scan_finds_the_token_and_its_encodings_at_every_alignment(prefix):
    for encoded in (SENTINEL_TOKEN,
                    base64.b64encode(prefix + SENTINEL_TOKEN + b"tail"),
                    base64.urlsafe_b64encode(prefix + SENTINEL_TOKEN + b"t"),
                    binascii.hexlify(SENTINEL_TOKEN), binascii.hexlify(SENTINEL_TOKEN).upper()):
        assert seat_jail.contains_secret(b"output: " + encoded + b" end", SENTINEL_TOKEN)


def test_output_scan_does_not_fire_on_clean_output_and_misses_split_forms():
    assert not seat_jail.contains_secret(b"a clean review. AGREE", SENTINEL_TOKEN)
    half = len(SENTINEL_TOKEN) // 2
    split = SENTINEL_TOKEN[:half] + b" " + SENTINEL_TOKEN[half:]
    # D3 residual, recorded rather than hidden: a split form passes the scan.
    assert not seat_jail.contains_secret(split, SENTINEL_TOKEN)


# --------------------------------------------------------------------------------------
# D7: the Gemini seat credential copy (builder only; the tooled Gemini route is gated on
# P4 then P3 and stays sealed).
# --------------------------------------------------------------------------------------

def _agy_file(tmp_path: Path, document: object, mode: int = 0o600) -> Path:
    path = tmp_path / "antigravity-oauth-token"
    path.write_text(json.dumps(document) if not isinstance(document, str) else document)
    path.chmod(mode)
    return path


def test_d7_copy_strips_the_refresh_and_id_tokens(tmp_path):
    path = _agy_file(tmp_path, {"token": {"access_token": "AT", "refresh_token": "RT",
                                          "expiry": "2026-09-29T00:00:00Z"},
                                "id_token": "IDT", "auth_method": "oauth"})
    copy = json.loads(seat_jail.build_gemini_seat_copy(path))
    assert copy["token"] == {"access_token": "AT", "expiry": "2026-09-29T00:00:00Z"}
    assert "id_token" not in copy and "RT" not in json.dumps(copy)


@pytest.mark.parametrize("case", ["loose", "symlink", "unparseable", "no-access-token", "oversize"])
def test_d7_operator_file_hygiene_refuses(tmp_path, case):
    good = {"token": {"access_token": "AT", "refresh_token": "RT"}}
    if case == "loose":
        path = _agy_file(tmp_path, good, 0o644)
    elif case == "symlink":
        real = _agy_file(tmp_path, good)
        path = tmp_path / "alias"
        path.symlink_to(real)
    elif case == "unparseable":
        path = _agy_file(tmp_path, "{not json")
    elif case == "no-access-token":
        path = _agy_file(tmp_path, {"token": {"refresh_token": "RT"}})
    else:
        path = _agy_file(tmp_path, {"token": {"access_token": "A" * 70000}})
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        seat_jail.build_gemini_seat_copy(path)
    assert refused.value.code == "seat_sandbox_refused:gemini_credential_unsafe"


# --------------------------------------------------------------------------------------
# Session keyring (J3): the shim leaves the seat none of the operator's session keys.
# --------------------------------------------------------------------------------------

_SESSION_SERIAL = (
    "import ctypes;l=ctypes.CDLL(None);l.syscall.restype=ctypes.c_long;"
    "print(l.syscall(ctypes.c_long({nr}),ctypes.c_long(0),ctypes.c_long(-3),ctypes.c_long(0)))"
)


@pytest.mark.skipif(platform.machine() not in ("x86_64", "aarch64"), reason="keyctl numbers")
def test_keyring_shim_joins_a_fresh_session_keyring():
    nr = seat_keyring_exec._KEYCTL_NR[platform.machine()]
    code = _SESSION_SERIAL.format(nr=nr)
    env = {**os.environ, "PYTHONPATH": str(Path(seat_jail.__file__).resolve().parent.parent)}
    parent = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env).stdout.strip()
    shimmed = subprocess.run(
        [sys.executable, "-m", "phase_loop_runtime.seat_keyring_exec", "--",
         sys.executable, "-c", code], capture_output=True, text=True, env=env,
    ).stdout.strip()
    assert int(parent) > 0 and int(shimmed) > 0
    assert shimmed != parent
    # Mutation (skip the shim): the child shares the parent's session keyring.
    unshimmed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=env).stdout.strip()
    assert unshimmed == parent


# --------------------------------------------------------------------------------------
# Seat-token rotation: the token is per-launch input, never part of the jail's identity.
# --------------------------------------------------------------------------------------

def test_a_replaced_seat_token_changes_no_jail_digest(tmp_path):
    """The qualification gate's input at launch is the built jail's actual digest, so a token
    swapped between two launches must leave it, and the canonical digest, unchanged."""
    digests = []
    for name, token in (("one", b"SEAT-TOKEN-SUBSCRIPTION-A"), ("two", b"SEAT-TOKEN-B-" * 7)):
        (tmp_path / name).mkdir()
        jail = _jail(tmp_path / name, token=token)
        try:
            digests.append((jail.profile_digest, seat_jail.actual_profile_digest(jail)))
        finally:
            seat_jail.close_jail_fds(jail)
    canonical = seat_jail.jail_profile_digest("claude")
    assert digests == [(canonical, canonical), (canonical, canonical)]


# --------------------------------------------------------------------------------------
# The identity probe's descriptor line is listed by a child the shell forks with no pipe
# open (agent-harness#1132 round 9: `ls /proc/$$/fd | ...` raced the shell's own pipe
# descriptors under load and refused a correctly confined seat).
# --------------------------------------------------------------------------------------

def _fd_segment() -> str:
    probe = seat_jail.JAIL_PROBE
    start = probe.index("/usr/bin/python3 -I -S -c 'import os")
    return probe[start:probe.index("'; ", start) + 3]


def test_the_probe_lists_descriptors_without_a_pipeline():
    segment = _fd_segment()
    assert "/proc/$$/fd" not in seat_jail.JAIL_PROBE
    # Outside the Python source (single-quoted), the command has no pipe or substitution.
    shell = segment[:segment.index("'")] + segment[segment.rindex("'"):]
    assert not set("|`$(") & set(shell)


def test_the_probe_descriptor_line_is_exactly_the_inherited_set():
    read, write = os.pipe()
    os.set_inheritable(read, True)
    try:
        for _ in range(20):
            done = subprocess.run(["/bin/sh", "-c", _fd_segment()], pass_fds=(read,),
                                  capture_output=True, text=True, timeout=30)
            assert done.stdout == f"0 1 2 {read} \n", done
    finally:
        os.close(read)
        os.close(write)
