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
import dataclasses
import errno
import hashlib
import json
import os
import platform
import shutil
import stat
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


def test_memfd_with_seals_on_an_interpreter_whose_fcntl_lacks_the_seal_constants(monkeypatch):
    """CPython exports F_ADD_SEALS and F_SEAL_* only from 3.14; the package supports older
    interpreters, so the kernel ABI values are the fallback (agent-harness#1276)."""
    import errno
    import fcntl

    for constant in ("F_ADD_SEALS", "F_SEAL_SEAL", "F_SEAL_SHRINK", "F_SEAL_GROW", "F_SEAL_WRITE"):
        monkeypatch.delattr(fcntl, constant, raising=False)
    fd = seat_jail.memfd_with("t-seal", b"PAYLOAD")
    try:
        assert fcntl.fcntl(fd, 1034) == 0xF   # F_GET_SEALS: seal, shrink, grow and write
        assert os.pread(fd, 7, 0) == b"PAYLOAD"
        with pytest.raises(OSError) as raised:
            os.write(fd, b"x")
        assert raised.value.errno == errno.EPERM
    finally:
        os.close(fd)


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


def test_seats_firstseat_teamhost_promisor_stage(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (repo / "code.py").write_text("value = 1\n")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    for version in (2, 3):
        (repo / "code.py").write_text(f"value = {version}\n")
        git("add", ".")
        git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    git("config", "uploadpack.allowFilter", "true")
    origin = repo
    repo = tmp_path / "partial"
    subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout",
                    origin.as_uri(), str(repo)], check=True, capture_output=True)
    git("checkout", "-q", "HEAD")
    head = git("rev-parse", "HEAD")
    assert "?" in git("rev-list", "--objects", "--all", "--missing=print")
    assert review_stage.host_git(repo, "show", "HEAD~1:code.py", capture_output=True,
                                 text=True, check=True).stdout == "value = 2\n"
    assert "?" in git("rev-list", "--objects", "--all", "--missing=print")
    git("config", "remote.origin.url", "https://fixture.invalid/repo")
    git("config", "remote.origin.promisor", "true")
    git("config", "extensions.partialClone", "origin")
    calls = []
    original = review_stage.host_git
    def observed(root, *args, **kw):
        calls.append((args, review_stage.host_git_env(offline=kw.get("offline", False))))
        return original(root, *args, **kw)
    monkeypatch.setattr(review_stage, "host_git", observed)
    previous = os.umask(0o077)
    try:
        staged = review_stage.stage_review_tree(repo, tmp_path / "stages")
    finally:
        os.umask(previous)
    try:
        assert review_stage.staged_source_commit(staged) == head
        config = (staged / ".git/config").read_text()
        assert "remote " not in config and "promisor" not in config and "partialclone" not in config.lower()
        assert all(env["GIT_NO_LAZY_FETCH"] == "1" for args, env in calls if args[0] == "clone")
        assert (staged / "code.py").read_text() == "value = 3\n"
        assert not (staged / ".git/logs").exists()
        assert not any(str(repo).encode() in p.read_bytes()
                       for p in (staged / ".git").rglob("*") if p.is_file())
    finally:
        review_stage.remove_review_stage(staged)



def test_seats_firstseat_teamhost_missing_blob(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    (repo / "code.py").write_text("materialize before staging\n")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    identity = git("rev-parse", "HEAD:code.py")
    git("config", "remote.origin.url", "https://fixture.invalid/repo")
    git("config", "remote.origin.promisor", "true")
    (repo / ".git/objects" / identity[:2] / identity[2:]).unlink()
    with pytest.raises(RuntimeError, match="^sandbox_source_partial_clone$") as refusal:
        review_stage.stage_review_tree(repo, tmp_path / "stages")
    assert refusal.value.__suppress_context__ and str(repo) not in str(refusal.value)
    assert not list((tmp_path / "stages").iterdir())


def _firstseat_paths(tmp_path):
    from phase_loop_runtime import seat_jail_qualification as q

    tree = tmp_path / "tree"
    seat_home = tmp_path / "seat-home"
    gemini_config = tmp_path / "gemini-config"
    agy_rw = seat_home / ".agy-rw"
    seat_out = tmp_path / "seat-out"
    for path in (tree, seat_home / "workspace", gemini_config / "antigravity-cli",
                 agy_rw / "config", seat_out):
        path.mkdir(parents=True, exist_ok=True)
    return q.HostPathMap(tree=tree, seat_home=seat_home, gemini_config=gemini_config,
                         agy_rw=agy_rw, seat_out=seat_out, delivered_credential=None)


def test_seats_firstseat_teamhost_containment_layout_and_input(tmp_path):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="nested")
    expected = {f"{location}:{row}" for location in q._LOCATIONS for row in q.TREE_ROWS}
    expected.update(f"{location}:{row}" for location, row in q.RUNTIME_ROWS)
    assert {row.row_id for row in layout.rows} == expected
    assert len({row.nonce for row in layout.rows}) == len(layout.rows)
    assert all(len(value) == 40 and value.endswith(".invalid")
               for values in layout.canary_hosts.values() for value in values)
    qualification = q.build_qualification_input(layout, tmp_path / "inputs")
    assert qualification.commit == subprocess.run(
        ["git", "-C", str(qualification.repo), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True).stdout.strip()
    assert (qualification.repo / q.WINDOW_READ_PATH).is_file()
    assert (qualification.repo / q.WATCH_EXEC_SENTINEL).stat().st_mode & 0o111
    assert not (qualification.repo / ".git/config").read_text().count("remote ")
    for plugin in (".agent/plugins/p", ".agents/plugins/p"):
        root = qualification.repo / plugin
        manifest = json.loads((root / "plugin.json").read_text())
        assert manifest["skills"] == ["./skills/s"]
        assert json.loads((root / "hooks.json").read_text())
        assert json.loads((root / "mcp_config.json").read_text())["mcpServers"]
        assert "trigger: always_on" in (root / "rules/r.md").read_text()


def test_seats_firstseat_teamhost_containment_runtime_paths(tmp_path):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    paths = _firstseat_paths(tmp_path)
    q.seed_runtime_plants(layout, paths)
    assert (paths.seat_home / "workspace" / "AGENTS.md").is_file()
    assert (paths.gemini_config / "antigravity-cli" / "settings.json").is_file()
    assert (paths.agy_rw / "config" / "mcp_config.json").is_file()
    assert not (paths.seat_home / ".gemini").exists()
    for row in layout.rows:
        if row.location == "tree":
            continue
        relative = row.row_id.partition(":")[2]
        target = q._host_path(paths, row.location, relative)
        assert stat.S_IMODE(target.stat().st_mode) == (
            0o700 if relative.endswith("/") else 0o600)
    for row in layout.rows:
        if (row.location == "tree"
                or row.row_id.partition(":")[2] != ".gemini/settings.json"):
            continue
        target = q._host_path(paths, row.location, ".gemini/settings.json")
        settings = json.loads(target.read_text())
        assert settings["mcpServers"][row.nonce]["url"] == f"https://{row.nonce}.invalid/"
    duplicate = dataclasses.replace(layout, rows=(*layout.rows, layout.rows[-1]))
    with pytest.raises(q.PlantLayoutRefused):
        q.seed_runtime_plants(duplicate, _firstseat_paths(tmp_path / "duplicate"))


def test_seats_firstseat_teamhost_containment_watch(tmp_path):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    source = q.build_qualification_input(layout, tmp_path / "input")
    paths = _firstseat_paths(tmp_path / "seat")
    shutil.copytree(source.repo, paths.tree, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git"))
    q.seed_runtime_plants(layout, paths)
    watch = q.arm_watch(layout, paths, kind="measured")

    class Run:
        def __call__(self, argv, *, env, use_proxy, timeout_s):
            assert not use_proxy and env["LC_ALL"] == "C" and timeout_s == 30.0
            target = paths.tree / Path(argv[-1]).name
            if argv[0] == "/bin/cat":
                target.read_bytes()
            else:
                subprocess.run([str(target)], check=True)
            return q.JailedStep(exit_code=0, timed_out=False, stdout=b"")

    assert watch.prove_sentinel(Run())
    selected = next(row for row in layout.rows if row.location == "tree")
    (paths.tree / selected.row_id.partition(":")[2].rstrip("/")).read_bytes()
    (paths.tree / q.WINDOW_READ_PATH).read_bytes()
    runtime = next(row for row in layout.rows if row.location == "workdir"
                   and not row.row_id.endswith("/"))
    runtime_path = q._host_path(paths, runtime.location, runtime.row_id.partition(":")[2])
    runtime_path.write_bytes(runtime_path.read_bytes() + b"change")
    attribute_only = next(row for row in layout.rows if row.location == "provider_config")
    attribute_path = q._host_path(
        paths, attribute_only.location, attribute_only.row_id.partition(":")[2])
    attribute_path.chmod(0o640)
    observation = watch.drain_and_close(quiescent=True)
    assert observation.sentinel_observed and observation.read_marker_opened
    assert selected.row_id in observation.opened_rows
    assert runtime.row_id in observation.changed_rows
    assert attribute_only.row_id not in observation.changed_rows
    assert observation.drained_after_quiescence and not observation.overflow


def test_seats_firstseat_teamhost_containment_watch_arms_before_runtime_seed_and_ignores_stat(
        tmp_path):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    source = q.build_qualification_input(layout, tmp_path / "input")
    paths = _firstseat_paths(tmp_path / "seat")
    shutil.copytree(source.repo, paths.tree, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git"))
    watch = q.arm_watch(layout, paths, kind="tree_control")
    selected = next(row for row in layout.rows
                    if row.location == "tree" and not row.row_id.endswith("/"))
    target = paths.tree / selected.row_id.partition(":")[2]
    target.stat()
    assert os.access(target, os.R_OK)
    observation = watch.drain_and_close(quiescent=True)
    assert selected.row_id not in observation.opened_rows
    assert not observation.row_ancestor_created


def test_seats_firstseat_teamhost_containment_watch_reports_ancestor_and_credential_rename(
        tmp_path):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    source = q.build_qualification_input(layout, tmp_path / "input")
    paths = _firstseat_paths(tmp_path / "seat")
    shutil.copytree(source.repo, paths.tree, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git"))
    credential = paths.seat_out / "delivered.json"
    credential.write_text("old\n")
    paths = dataclasses.replace(paths, delivered_credential=credential)
    watch = q.arm_watch(layout, paths, kind="credentialed_tree_control")
    (paths.seat_home / "workspace" / ".agent").mkdir()
    replacement = paths.seat_out / "replacement.json"
    replacement.write_text("new\n")
    replacement.replace(credential)
    observation = watch.drain_and_close(quiescent=True)
    assert observation.row_ancestor_created
    assert any(row.startswith("workdir:.agent/") for row in observation.changed_rows)
    assert observation.credential_path_events > 0


def test_seats_firstseat_teamhost_containment_scan_wrapper(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    paths = _firstseat_paths(tmp_path)
    q.seed_runtime_plants(layout, paths)
    token = b'{"token":{"access_token":"fixture-access"}}'
    delivered = q.DeliveredCopy(content=token, sha256=hashlib.sha256(token).hexdigest())

    def scan_in_h(holder, seat_root, tree, rows, *, token, **_kw):
        assert holder == 17 and seat_root == str(paths.seat_home.parent)
        assert token == b"fixture-access"
        return {"schema": "seat_scan.v1", "scan_complete": True, "entries": 1,
                "tree_manifest": "a" * 64,
                "counts": {"field_names": 0, "delivered_token": 0},
                "rows": {row_id: {"kind": "dir" if row_id.endswith("/") else "file",
                                  "digest": "b" * 64, "mode": 0o700 if row_id.endswith("/") else 0o600}
                         for row_id in rows}}

    monkeypatch.setattr(q.seat_uid, "scan_in_h", scan_in_h)
    result = q.scan_seat(17, str(paths.seat_home.parent), layout, paths, delivered=delivered)
    assert result.scan_complete and result.tree_manifest_sha256 == "a" * 64
    assert result.credential_counts == q.CredentialCounts(field_names=0, token=0)
    assert set(result.rows) == {row.row_id for row in layout.rows if row.location != "tree"}
    assert any(state.state == "directory" for state in result.rows.values())


def test_seats_firstseat_teamhost_containment_scan_incomplete_rows_stay_unread(
        tmp_path, monkeypatch):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    paths = _firstseat_paths(tmp_path)

    def scan_in_h(_holder, _seat_root, _tree, rows, *, token, **_kw):
        assert token is None
        payload = {}
        for row_id in rows:
            if row_id.endswith("/"):
                payload[row_id] = {"kind": "dir", "digest": None, "mode": 0o700}
            else:
                payload[row_id] = {"kind": "other", "digest": None, "mode": None}
        return {"schema": "seat_scan.v1", "scan_complete": False, "entries": 0,
                "tree_manifest": None, "counts": {"field_names": 0, "delivered_token": 0},
                "rows": payload}

    monkeypatch.setattr(q.seat_uid, "scan_in_h", scan_in_h)
    result = q.scan_seat(17, str(paths.seat_home.parent), layout, paths, delivered=None)
    assert result.scan_complete is False
    helper_ids = {row.row_id for row in layout.rows
                  if row.location in ("workdir", "home")
                  and not (row.location == "home" and row.row_id.split(":", 1)[1].startswith(".gemini/")
                           and not row.row_id.split(":", 1)[1].startswith(".gemini/config/"))}
    assert helper_ids
    assert all(result.rows[row_id].state == "unread" for row_id in helper_ids)


def test_seats_firstseat_teamhost_containment_scan_walker_is_bounded_and_counts_names(
        tmp_path, monkeypatch):
    from phase_loop_runtime import seat_uid

    tree = tmp_path / "tree"
    seat = tmp_path / "seat"
    home = seat / seat_jail.HOST_HOME_DIRNAME
    out = seat / seat_jail.HOST_OUT_DIRNAME
    for path in (tree, home / "workspace" / "plant", out):
        path.mkdir(parents=True)
    token = b"fixture-access"
    (tree / "row.txt").write_text("row\n")
    (home / "workspace" / "plant" / token.decode()).write_text("x")
    (out / "access_token").write_text("x")
    rows = {
        "workdir:plant/": ("seat", f"{seat_jail.HOST_HOME_DIRNAME}/workspace/plant"),
        "workdir:missing": ("seat", f"{seat_jail.HOST_HOME_DIRNAME}/workspace/missing"),
    }
    result = seat_uid.scan(str(seat), str(tree), rows, token=token)
    assert result["scan_complete"] is True
    assert result["rows"]["workdir:plant/"]["kind"] == "dir"
    assert result["rows"]["workdir:missing"]["kind"] == "missing"
    assert result["counts"]["delivered_token"] >= 1
    assert result["counts"]["field_names"] >= 1
    over_cap = seat_uid.scan(str(seat), str(tree), rows, token=token, cap_bytes=0)
    assert over_cap["scan_complete"] is False and over_cap["tree_manifest"] is None
    monkeypatch.setattr(seat_uid, "_SCAN_FLAGS_AVAILABLE", False)
    unavailable = seat_uid.scan(str(seat), str(tree), rows, token=token)
    assert unavailable["scan_complete"] is False and unavailable["tree_manifest"] is None
    assert all(row["kind"] == "other" for row in unavailable["rows"].values())


def test_seats_firstseat_teamhost_containment_scan_wrapper_fails_closed(
        tmp_path, monkeypatch):
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    paths = _firstseat_paths(tmp_path)
    q.seed_runtime_plants(layout, paths)
    monkeypatch.setattr(q.seat_uid, "scan_in_h", lambda *_a, **_kw: (_ for _ in ()).throw(
        OSError("unavailable")))
    result = q.scan_seat(17, str(paths.seat_home.parent), layout, paths, delivered=None)
    assert result.scan_complete is False
    assert result.tree_manifest_sha256 is None and result.credential_counts is None
    assert result.rows and all(row.state == "unread" for row in result.rows.values())


@pytest.mark.parametrize("change, outcome", [
    (None, "pass"), ("empty", "unavailable"), ("aud", "unavailable"),
    ("azp", "unavailable"), ("expiry", "unavailable"),
    ("excess", "gemini_seat_token_scope_excess"),
])
def test_seats_firstseat_teamhost_containment_issuer(monkeypatch, change, outcome):
    from phase_loop_runtime import seat_jail_qualification as q

    token = b'{"token":{"access_token":"fixture-access"}}'
    delivered = q.DeliveredCopy(content=token, sha256=hashlib.sha256(token).hexdigest())
    response = {"scope": next(iter(q._ISSUER_SCOPE_CEILING)), "aud": q._ISSUER_AUD,
                "azp": q._ISSUER_AZP, "expires_in": 60}
    if change == "empty": response["scope"] = ""
    if change in ("aud", "azp"): response[change] = "other"
    if change == "expiry": response["expires_in"] = "60"
    if change == "excess": response["scope"] += " extra"
    monkeypatch.setattr(q, "_issuer_response", lambda access: response)
    measured = q.measure_issuer(delivered)
    assert measured.outcome == outcome
    assert measured.measured_sha256 == delivered.sha256


def _firstseat_stream(*, bracket=False, outside=(), protocol_error=False):
    from phase_loop_runtime import seat_egress_proxy as proxy

    inference = proxy.RequestEvent(method="POST", host="daily-cloudcode-pa.googleapis.com",
                                   path="/v1internal:*", decision="allow")
    windows = [proxy.ProxyWindow(label="leg", start_acked=True, end_acked=True,
                                 events=(inference,))]
    if bracket:
        token = proxy.RequestEvent(method="POST", host="oauth2.googleapis.com",
                                   path="<other>", decision="deny")
        windows.append(proxy.ProxyWindow(label="bracket", start_acked=True, end_acked=True,
                                         events=(token,)))
    return proxy.ProxyStream(final=True, protocol_error=protocol_error, windows=tuple(windows),
                             outside_events=tuple(outside), allowlist_sha256="d" * 64)


def _firstseat_reducer_input():
    from phase_loop_runtime import seat_egress_proxy as proxy
    from phase_loop_runtime import seat_jail_qualification as q

    layout = q.plant_layout(plugin_form="plugin_json")
    selected = tuple(next(row for row in layout.rows
                          if row.location == "tree" and row.role == surface)
                     for surface in q._SURFACES)
    tree_manifest = "e" * 64
    row_states = {}
    for row in layout.rows:
        if row.location == "tree":
            continue
        relative = row.row_id.partition(":")[2]
        directory = relative.endswith("/")
        readonly = (row.location == "provider_config"
                    or row.location == "home" and relative.startswith(".gemini/")
                    and not relative.startswith(".gemini/config/"))
        row_states[row.row_id] = q.RowState(
            state="directory" if directory else "regular",
            sha256=hashlib.sha256(row.nonce.encode()).hexdigest(),
            mode=(0o550 if directory else 0o440) if readonly
            else (0o700 if directory else 0o600))
    scan = q.ScanResult(rows=row_states, tree_manifest_sha256=tree_manifest,
                        credential_counts=q.CredentialCounts(field_names=0, token=0),
                        scan_complete=True)
    pre = {row_id: state.sha256 for row_id, state in row_states.items()}
    control_watch = q.WatchObservation(
        armed_ns=1, closed_ns=3, sentinel_observed=True, overflow=False,
        read_marker_opened=False, drained_after_quiescence=True,
        opened_rows=tuple(row.row_id for row in selected), changed_rows=(),
        row_ancestor_created=False, credential_path_events=0,
        pre_row_sha256=pre, pre_tree_manifest_sha256=tree_manifest)
    measured_watch = dataclasses.replace(control_watch, read_marker_opened=True,
                                         opened_rows=())
    refuse_binding = q.LaunchBinding(
        image_sha256="1" * 64, admission_class="release_qualified",
        stage_manifest_sha256="2" * 64, argv_sha256="3" * 64,
        input_sha256=hashlib.sha256(q.CONTROL_INPUT.encode()).hexdigest(),
        jail_profile_sha256="4" * 64, allowlist_sha256="5" * 64)
    production_binding = dataclasses.replace(
        refuse_binding, argv_sha256="6" * 64,
        input_sha256=hashlib.sha256(q.MEASURED_INPUT.encode()).hexdigest(),
        allowlist_sha256="7" * 64)

    def launch(kind, *, watch=control_watch, stream=None, binding=refuse_binding,
               status="SUCCESS", model_turn=False, issuer=None, bracket=None,
               delivered=None, created=()):
        return q.WindowLaunchResult(
            kind=kind, status=status, timed_out=False, error=None, quiescent=True,
            model_turn=model_turn, tool_steps=0, subagent_steps=0,
            stream=stream or _firstseat_stream(), bridge_exited=True,
            lookups=(), created=created, lookup_complete=True, watch=watch, scan=scan,
            first_jailed_launch_ns=2, bracket=bracket, issuer=issuer,
            delivered_copy_sha256=delivered, help_sha256=None, help_lists_plugin=None,
            plugin_validation=None, binding=binding)

    controls = (launch("tree_control"),
                launch("runtime_control", binding=dataclasses.replace(
                    refuse_binding, argv_sha256="6" * 64)),
                launch("credentialed_tree_control", binding=dataclasses.replace(
                    refuse_binding, allowlist_sha256="7" * 64), created=(
                    q.TracedPath(location="home", relpath=".gemini/config/mcp_config.json"),)),
                launch("credentialed_runtime_control", binding=dataclasses.replace(
                    refuse_binding, argv_sha256="6" * 64, allowlist_sha256="7" * 64)))
    delivered = "8" * 64
    fence = proxy.FenceResult(fence_id="9" * 32, acknowledged=True, acked_ns=10)
    bracket = q.BracketResult(start=fence, end=fence, post_refused=True,
                              rows=tuple(q.BracketRow(row=name, outcome="refused",
                                  signature=next(iter(q.BRACKET_SIGNATURES[name])))
                                  for name in q.BRACKET_ROW_NAMES))
    measured = launch("measured", watch=measured_watch, stream=_firstseat_stream(bracket=True),
                      binding=production_binding, issuer=q.IssuerMeasurement(
                          outcome="pass", measured_sha256=delivered), bracket=bracket,
                      delivered=delivered, model_turn=True)
    expired = launch("expired_copy", watch=measured_watch,
                     binding=production_binding, status="FAILURE", model_turn=False)
    help_result = dataclasses.replace(
        launch("help", watch=None, stream=None, binding=dataclasses.replace(
            refuse_binding, input_sha256=None)),
        help_sha256="a" * 64, help_lists_plugin=False, scan=None,
        first_jailed_launch_ns=None, lookup_complete=None, lookups=None, created=None)
    return q.ContainmentInputs(
        context=q.ContextBinding(context_id="fixture-context", account_label="fixture-account",
                                 dependency_subject_sha256=None,
                                 dependency_projection_sha256=None),
        layout=layout, help=help_result, plugin_validation=None, controls=controls,
        measured=measured, expired_copy=expired, board=None)


def test_seats_firstseat_teamhost_containment_reducer_control():
    from phase_loop_runtime import seat_jail_qualification as q

    result = q.reduce_containment(_firstseat_reducer_input())
    assert result.admitted
    assert result.containment == {
        "credential_scope": "pass", "refresh_detection": "pass",
        "project_settings": "not_loaded", "hooks": "not_loaded",
        "mcp_servers": "not_loaded", "provider_overrides": "not_loaded",
    }
    assert all(result.checks.values())
    assert result.owner_summary.schema == "seat_window_owner_summary.v1"
    assert set(result.binding) == set(q._BINDING_KEYS)
    assert result.owner_summary.private_route is False


def test_seats_firstseat_teamhost_containment_admission_routes_positive_observations():
    from phase_loop_runtime import seat_jail_qualification as q

    inputs = _firstseat_reducer_input()
    measured = inputs.measured
    assert measured is not None and measured.watch is not None
    row = next(row for row in inputs.layout.rows if row.role == "project_settings")
    measured = dataclasses.replace(
        measured, watch=dataclasses.replace(measured.watch, opened_rows=(row.row_id,)))

    def admission(item, value):
        if item is None or item.binding is None:
            return item
        return dataclasses.replace(
            item, binding=dataclasses.replace(item.binding, admission_class=value))

    controls = tuple(admission(item, "candidate") for item in inputs.controls)
    not_admitted = dataclasses.replace(
        inputs, help=admission(inputs.help, "candidate"), controls=controls,
        measured=admission(measured, "candidate"),
        expired_copy=admission(inputs.expired_copy, "candidate"))
    result = q.reduce_containment(not_admitted)
    assert not result.admitted and set(result.containment.values()) == {"unavailable"}
    assert result.owner_summary.outcomes["project_settings"] == "loaded"
    assert result.owner_summary.private_route

    dependency = dataclasses.replace(
        inputs.context, dependency_subject_sha256=measured.binding.image_sha256)
    controls = tuple(admission(item, "executable_dependency") for item in inputs.controls)
    executable = dataclasses.replace(
        inputs, context=dependency, help=admission(inputs.help, "executable_dependency"),
        controls=controls, measured=admission(inputs.measured, "executable_dependency"),
        expired_copy=admission(inputs.expired_copy, "executable_dependency"))
    assert q.reduce_containment(executable).admitted


_FIRSTSEAT_MUTANTS = (
    "01_constant_definition", "02_control_argv_equals_production",
    "03_row_dropped_per_surface", "04_watch_armed_after_launch",
    "05_scope_derived_in_jail", "06_stat_or_access_counted_as_open",
    "07_tool_or_subagent_control", "08_missing_sentinel_or_staged_read",
    "09_missing_or_unended_stream", "10_canary_ignored", "11_empty_issuer_scope",
    "12_wrong_issuer_audience", "13_token_endpoint_ignored", "14_credential_write_ignored",
    "15_runtime_change_ignored", "16_unknown_lookup_ignored",
    "17_expired_copy_error_passes", "18_early_fence_ack", "19_outside_event_attributed",
    "20_board_or_outside_positive_ignored", "21_board_not_loaded_or_wrong_measured_input",
    "22_shadowed_plant_counted", "23_late_watch_or_attribute_event",
    "24_positive_lost_on_incomplete_channel", "25_failed_bracket_row_passes",
    "26_incomplete_scan_or_token_ignored", "27_tree_manifest_change_ignored",
    "28_home_change_or_lookup_ignored", "29_missing_credential_scan_passes",
    "30_wrong_board_input",
)


def _firstseat_map_controls(inputs, mutate):
    return dataclasses.replace(inputs, controls=tuple(mutate(item) for item in inputs.controls))


def _firstseat_leg_event(result, event):
    stream = result.stream
    assert stream is not None
    windows = tuple(dataclasses.replace(window, events=(*window.events, event))
                    if window.label == "leg" else window for window in stream.windows)
    return dataclasses.replace(result, stream=dataclasses.replace(stream, windows=windows))


@pytest.mark.parametrize("mutant", _FIRSTSEAT_MUTANTS)
def test_seats_firstseat_teamhost_containment_mutants(mutant, tmp_path):
    """Each section 13 mutation loses assurance or preserves its positive observation."""
    from phase_loop_runtime import seat_egress_proxy as proxy
    from phase_loop_runtime import seat_jail_qualification as q

    inputs = _firstseat_reducer_input()
    measured = inputs.measured
    expired = inputs.expired_copy
    assert measured is not None and measured.watch is not None and measured.scan is not None
    assert measured.binding is not None and expired is not None

    if mutant == "01_constant_definition":
        inputs = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, watch=dataclasses.replace(item.watch, opened_rows=()) if item.watch else None))
        assert q.reduce_containment(inputs).containment["project_settings"] == "unavailable"
    elif mutant == "02_control_argv_equals_production":
        inputs = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, binding=dataclasses.replace(item.binding, argv_sha256="6" * 64)))
        assert not any(q.reduce_containment(inputs).checks.values())
    elif mutant == "03_row_dropped_per_surface":
        for surface in q._SURFACES:
            dropped = next(row for row in inputs.layout.rows if row.role == surface)
            layout = dataclasses.replace(
                inputs.layout, rows=tuple(row for row in inputs.layout.rows if row != dropped))
            assert q.reduce_containment(dataclasses.replace(inputs, layout=layout)).containment[
                surface] == "unavailable"
    elif mutant == "04_watch_armed_after_launch":
        late_controls = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, watch=dataclasses.replace(item.watch, armed_ns=3) if item.watch else None))
        assert q.reduce_containment(late_controls).containment["hooks"] == "unavailable"
        late_measured = dataclasses.replace(
            inputs, measured=dataclasses.replace(
                measured, watch=dataclasses.replace(measured.watch, armed_ns=3)))
        assert q.reduce_containment(late_measured).containment["hooks"] == "unavailable"
    elif mutant == "05_scope_derived_in_jail":
        result = q.reduce_containment(
            dataclasses.replace(inputs, measured=dataclasses.replace(measured, issuer=None)))
        assert result.containment["credential_scope"] == "unavailable"
    elif mutant == "06_stat_or_access_counted_as_open":
        known = q.TracedPath(location="tree", relpath="AGENTS.md")
        inputs = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, watch=dataclasses.replace(item.watch, opened_rows=()) if item.watch else None,
            lookups=(known,)))
        assert q.reduce_containment(inputs).containment["provider_overrides"] == "unavailable"
    elif mutant == "07_tool_or_subagent_control":
        for field in ("tool_steps", "subagent_steps"):
            changed = _firstseat_map_controls(
                inputs, lambda item, field=field: dataclasses.replace(item, **{field: 1}))
            assert q.reduce_containment(changed).containment["mcp_servers"] == "unavailable"
    elif mutant == "08_missing_sentinel_or_staged_read":
        controls = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, watch=dataclasses.replace(item.watch, sentinel_observed=False)
            if item.watch else None))
        assert q.reduce_containment(controls).containment["hooks"] == "unavailable"
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(
            measured, watch=dataclasses.replace(measured.watch, read_marker_opened=False)))
        assert q.reduce_containment(changed).containment["hooks"] == "unavailable"
    elif mutant == "09_missing_or_unended_stream":
        for stream in (None, dataclasses.replace(measured.stream, final=False)):
            changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, stream=stream))
            assert q.reduce_containment(changed).containment["hooks"] == "unavailable"
    elif mutant == "10_canary_ignored":
        event = proxy.RequestEvent(method="GET", host=inputs.layout.canary_hosts["mcp_servers"][0],
                                   path="<other>", decision="deny")
        stream = dataclasses.replace(measured.stream, outside_events=(event,), protocol_error=True)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, stream=stream))
        assert q.reduce_containment(changed).containment["mcp_servers"] == "loaded"
    elif mutant in ("11_empty_issuer_scope", "12_wrong_issuer_audience"):
        issuer = q.IssuerMeasurement(outcome="unavailable",
                                     measured_sha256=measured.delivered_copy_sha256)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, issuer=issuer))
        assert q.reduce_containment(changed).containment["credential_scope"] == "unavailable"
    elif mutant == "13_token_endpoint_ignored":
        event = proxy.RequestEvent(method="POST", host="oauth2.googleapis.com",
                                   path="<other>", decision="deny")
        changed = dataclasses.replace(inputs, measured=_firstseat_leg_event(measured, event))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
        userinfo = proxy.RequestEvent(method="POST", host="www.googleapis.com",
                                      path="/oauth2/v2/userinfo", decision="deny")
        changed = dataclasses.replace(inputs, measured=_firstseat_leg_event(measured, userinfo))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
        get_userinfo = dataclasses.replace(userinfo, method="GET")
        changed = dataclasses.replace(inputs, measured=_firstseat_leg_event(
            measured, get_userinfo))
        assert q.reduce_containment(changed).containment["refresh_detection"] == "pass"
        outside = dataclasses.replace(measured.stream, outside_events=(event,))
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(
            measured, stream=outside))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
        allowed = dataclasses.replace(event, decision="allow")
        stream = dataclasses.replace(expired.stream, outside_events=(allowed,))
        changed = dataclasses.replace(inputs, expired_copy=dataclasses.replace(
            expired, stream=stream))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
    elif mutant == "14_credential_write_ignored":
        watch = dataclasses.replace(measured.watch, credential_path_events=1)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, watch=watch))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
        counts = q.CredentialCounts(field_names=1, token=0)
        scan = dataclasses.replace(measured.scan, credential_counts=counts)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(
            measured, scan=scan))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
    elif mutant == "15_runtime_change_ignored":
        row = next(row for row in inputs.layout.rows if row.location == "workdir")
        watch = dataclasses.replace(measured.watch, changed_rows=(row.row_id,))
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, watch=watch))
        assert q.reduce_containment(changed).containment[row.role] == "loaded"
        defined = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, watch=dataclasses.replace(
                item.watch, opened_rows=(*item.watch.opened_rows, row.row_id))
            if item.watch is not None else None))
        defined = dataclasses.replace(
            defined, measured=dataclasses.replace(measured, watch=watch))
        result = q.reduce_containment(defined)
        assert row.row_id in q.definition_probe(defined.layout, defined.controls).defined_rows
        assert result.containment[row.role] == "loaded"
        assert all(result.containment[surface] != "not_loaded" for surface in q._SURFACES)
        home = "home:.gemini/config/mcp_config.json"
        rows = dict(measured.scan.rows)
        rows[home] = dataclasses.replace(rows[home], mode=0o644)
        mode_measured = dataclasses.replace(
            measured, scan=dataclasses.replace(measured.scan, rows=rows))
        mode_result = q.reduce_containment(dataclasses.replace(inputs, measured=mode_measured))
        assert mode_result.containment["mcp_servers"] != "not_loaded"
        assert home in mode_result.private["rows"]["measured_changed"]
    elif mutant == "16_unknown_lookup_ignored":
        lookup = q.TracedPath(location="tree", relpath=".agents/unknown-loader.json")
        changed = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, lookups=(lookup,)))
        result = q.reduce_containment(changed)
        assert result.containment["project_settings"] == "unavailable"
        assert all(value == 1 for value in result.owner_summary.counted_lookups.values())
        nested = q.TracedPath(location="tree", relpath=".agent/plugins/p/nested/AGENTS.md")
        nested_inputs = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, lookups=(nested,)))
        nested_result = q.reduce_containment(nested_inputs)
        assert nested_result.containment["project_settings"] == "unavailable"
        assert all(value == 1 for value in nested_result.owner_summary.counted_lookups.values())
    elif mutant == "17_expired_copy_error_passes":
        changed = dataclasses.replace(inputs, expired_copy=dataclasses.replace(
            expired, error="jail_unavailable"))
        assert q.reduce_containment(changed).containment["refresh_detection"] == "unavailable"
    elif mutant == "18_early_fence_ack":
        stream = dataclasses.replace(measured.stream, protocol_error=True)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, stream=stream))
        assert q.reduce_containment(changed).containment["hooks"] == "unavailable"
    elif mutant == "19_outside_event_attributed":
        event = proxy.RequestEvent(method="POST", host="daily-cloudcode-pa.googleapis.com",
                                   path="/v1internal:*", decision="allow")
        stream = dataclasses.replace(measured.stream, outside_events=(event,))
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, stream=stream))
        assert q.reduce_containment(changed).containment["hooks"] == "unavailable"
    elif mutant == "20_board_or_outside_positive_ignored":
        canary = proxy.RequestEvent(method="GET",
            host=inputs.layout.canary_hosts["mcp_servers"][0], path="<other>", decision="deny")
        outside = dataclasses.replace(measured.stream, outside_events=(canary,))
        assert q.reduce_containment(dataclasses.replace(
            inputs, measured=dataclasses.replace(measured, stream=outside))).containment[
                "mcp_servers"] == "loaded"
        row = next(row for row in inputs.layout.rows if row.role == "project_settings")
        board_watch = dataclasses.replace(measured.watch, opened_rows=(row.row_id,))
        board = q.BoardLegObservation(
            watch=board_watch, stream=None, input_sha256=hashlib.sha256(
                q.BOARD_INPUT.encode()).hexdigest(), binding=measured.binding)
        assert q.reduce_containment(dataclasses.replace(inputs, board=board)).containment[
            "project_settings"] == "loaded"
    elif mutant == "21_board_not_loaded_or_wrong_measured_input":
        assert "containment" not in {item.name for item in dataclasses.fields(q.BoardLegObservation)}
        binding = dataclasses.replace(measured.binding, input_sha256="0" * 64)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, binding=binding))
        assert not any(q.reduce_containment(changed).checks.values())
    elif mutant == "22_shadowed_plant_counted":
        base = tmp_path / "shadow"
        seat_home, agy_rw, real_config = base / "seat", base / "agy", base / "real-config"
        for path in (seat_home / "workspace", agy_rw / "config", real_config, base / "out",
                     base / "tree"):
            path.mkdir(parents=True, exist_ok=True)
        shadow = base / "gemini-config"
        shadow.symlink_to(real_config, target_is_directory=True)
        paths = q.HostPathMap(tree=base / "tree", seat_home=seat_home,
                              gemini_config=shadow, agy_rw=agy_rw, seat_out=base / "out",
                              delivered_credential=None)
        with pytest.raises(q.PlantLayoutRefused):
            q.seed_runtime_plants(q.plant_layout(plugin_form="plugin_json"), paths)
    elif mutant == "23_late_watch_or_attribute_event":
        watch = dataclasses.replace(measured.watch, armed_ns=3)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, watch=watch))
        assert q.reduce_containment(changed).containment["hooks"] == "unavailable"
    elif mutant == "24_positive_lost_on_incomplete_channel":
        row = next(row for row in inputs.layout.rows if row.role == "project_settings")
        incomplete = dataclasses.replace(measured.watch, opened_rows=(row.row_id,),
                                         sentinel_observed=False, overflow=True)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(
            measured, watch=incomplete, stream=None, scan=None))
        assert q.reduce_containment(changed).containment["project_settings"] == "loaded"
        credential = dataclasses.replace(incomplete, credential_path_events=1)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(
            measured, watch=credential, stream=None, scan=None))
        assert q.reduce_containment(changed).containment[
            "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
        issuer = q.IssuerMeasurement(outcome="gemini_seat_token_scope_excess",
                                     measured_sha256=measured.delivered_copy_sha256)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(
            measured, issuer=issuer, stream=None, scan=None))
        assert q.reduce_containment(changed).containment[
            "credential_scope"] == "gemini_seat_token_scope_excess"
    elif mutant == "25_failed_bracket_row_passes":
        rows = list(measured.bracket.rows)
        rows[0] = dataclasses.replace(rows[0], outcome="unavailable", signature=None)
        bracket = dataclasses.replace(measured.bracket, rows=tuple(rows))
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, bracket=bracket))
        assert q.reduce_containment(changed).containment["credential_scope"] == "unavailable"
    elif mutant == "26_incomplete_scan_or_token_ignored":
        incomplete = dataclasses.replace(measured.scan, scan_complete=False)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, scan=incomplete))
        assert q.reduce_containment(changed).containment["hooks"] == "unavailable"
        row = next(row for row in inputs.layout.rows if row.location == "workdir")
        rows = dict(measured.scan.rows)
        rows[row.row_id] = dataclasses.replace(rows[row.row_id], state="non_regular", sha256=None)
        nonregular = dataclasses.replace(measured.scan, rows=rows)
        assert q.reduce_containment(dataclasses.replace(
            inputs, measured=dataclasses.replace(measured, scan=nonregular))).containment[
                row.role] == "loaded"
        rows[row.row_id] = dataclasses.replace(rows[row.row_id], state="unread")
        unread = dataclasses.replace(measured.scan, rows=rows, scan_complete=True)
        assert q.reduce_containment(dataclasses.replace(
            inputs, measured=dataclasses.replace(measured, scan=unread))).containment[
                row.role] == "unavailable"
        counts = q.CredentialCounts(field_names=0, token=1)
        token_scan = dataclasses.replace(incomplete, credential_counts=counts)
        assert q.reduce_containment(dataclasses.replace(
            inputs, measured=dataclasses.replace(measured, scan=token_scan))).containment[
                "refresh_detection"] == "gemini_seat_token_refreshed_in_jail"
    elif mutant == "27_tree_manifest_change_ignored":
        scan = dataclasses.replace(measured.scan, tree_manifest_sha256="f" * 64)
        changed = dataclasses.replace(inputs, measured=dataclasses.replace(measured, scan=scan))
        result = q.reduce_containment(changed)
        assert result.containment["hooks"] == "unavailable"
        assert result.private["manifest_differences"] is True
    elif mutant == "28_home_change_or_lookup_ignored":
        home = "home:.gemini/config/mcp_config.json"
        controls = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(item, created=()))
        watch = dataclasses.replace(measured.watch, changed_rows=(home,))
        changed = dataclasses.replace(controls, measured=dataclasses.replace(measured, watch=watch))
        result = q.reduce_containment(changed)
        assert result.containment["mcp_servers"] == "loaded"
        assert all(result.containment[surface] != "not_loaded" for surface in q._SURFACES)
        lookup = q.TracedPath(location="home", relpath="private/mcp_config.json")
        changed = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, lookups=(lookup,)))
        assert q.reduce_containment(changed).containment["mcp_servers"] == "unavailable"
    elif mutant == "29_missing_credential_scan_passes":
        changed = dataclasses.replace(inputs, expired_copy=dataclasses.replace(expired, scan=None))
        assert q.reduce_containment(changed).containment["refresh_detection"] == "unavailable"
        no_counts = dataclasses.replace(expired.scan, credential_counts=None)
        changed = dataclasses.replace(inputs, expired_copy=dataclasses.replace(
            expired, scan=no_counts))
        assert q.reduce_containment(changed).containment["refresh_detection"] == "unavailable"
        controls = _firstseat_map_controls(inputs, lambda item: dataclasses.replace(
            item, scan=dataclasses.replace(item.scan, credential_counts=None))
            if item.kind.startswith("credentialed_") else item)
        definition = q.definition_probe(controls.layout, controls.controls)
        assert any(item.reason == "incomplete_watch" for item in definition.voided)
        assert definition.home_row_baseline == "absent"
    elif mutant == "30_wrong_board_input":
        row = next(row for row in inputs.layout.rows if row.role == "project_settings")
        board = q.BoardLegObservation(
            watch=dataclasses.replace(measured.watch, opened_rows=(row.row_id,)), stream=None,
            input_sha256="0" * 64, binding=measured.binding)
        measured_incomplete = dataclasses.replace(measured, stream=None)
        result = q.reduce_containment(dataclasses.replace(
            inputs, measured=measured_incomplete, board=board))
        assert result.containment["project_settings"] == "unavailable"
        assert "binding_mismatch" in result.owner_summary.unavailable_reasons["project_settings"]
        assert result.owner_summary.outcomes["project_settings"] == "loaded"
        assert result.owner_summary.private_route
        assert row.row_id in result.private["rows"]["board_opened"]
    else:  # pragma: no cover - the closed parameter table is exhaustive
        raise AssertionError(mutant)
