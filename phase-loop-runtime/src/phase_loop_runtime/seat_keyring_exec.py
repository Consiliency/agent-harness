"""Join a fresh anonymous session keyring, then exec the rest of the argv (J3, D8).

Possession of a key is independent of uid, so a seat that merely changed uid would still
possess the operator's session keyring; joining a fresh anonymous one first leaves it none
of the operator's keys. It runs before the seccomp filter, which denies ``keyctl``.

Two call shapes, one module. It stays standalone stdlib (no package imports), because the
owned route runs it as a bound file under ``python3 -I -S``:

* the jailed seat (agent-harness#1132): ``python -m phase_loop_runtime.seat_keyring_exec
  -- <argv...>``, the first element of the jail's launch prefix;
* the owned seat launch: ``python3 -I -S <this file> <seccomp-fd> <argv...>``, the final
  link inside the owner: it joins the keyring, sets no-new-privs, installs the sealed
  filter read from ``<seccomp-fd>`` and execs the argv.

No keyutils binary is needed: the calls are made through ``syscall(2)``.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import platform
import sys

KEYCTL_JOIN_SESSION_KEYRING = 1
_KEYCTL_NR = {"x86_64": 250, "aarch64": 219}


class _Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]


class _Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(_Filter))]


def join_fresh_session_keyring() -> int:
    """Join a new anonymous session keyring and return its serial (> 0)."""
    number = _KEYCTL_NR.get(platform.machine().lower())
    if number is None:
        raise OSError("seat_keyring_exec: unsupported architecture")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    serial = libc.syscall(ctypes.c_long(number), ctypes.c_long(KEYCTL_JOIN_SESSION_KEYRING),
                          ctypes.c_void_p(None))
    if serial < 0:
        code = ctypes.get_errno()
        raise OSError(code, f"keyctl(JOIN_SESSION_KEYRING) failed: {os.strerror(code)}")
    return int(serial)


def _checked(value):
    if value < 0:
        raise OSError(ctypes.get_errno(), "seat_keyring_unavailable")
    return value


def _join_session(libc, number):
    # A long-lived process can hold a revoked or expired session keyring (pam_keyinit
    # revokes it at logout): that is "no prior keyring", and the join below still works.
    try:
        before = _checked(libc.syscall(number, 0, -3, 1))
    except OSError as exc:
        if exc.errno not in {errno.EKEYREVOKED, errno.EKEYEXPIRED, errno.ENOKEY}:
            raise
        before = None
    _checked(libc.syscall(number, 1, ctypes.c_void_p()))
    after = _checked(libc.syscall(number, 0, -3, 0))
    if before == after:
        raise OSError(errno.EPERM, "seat_keyring_unavailable")


def _install_filter(libc, number, descriptor):
    if fcntl.fcntl(descriptor, getattr(fcntl, "F_GET_SEALS", 1034)) & 15 != 15:
        raise OSError(errno.EPERM, "seat_keyring_unavailable")
    size = os.fstat(descriptor).st_size
    if not 8 <= size <= 4096 * 8 or size % 8:
        raise OSError(errno.EINVAL, "seat_keyring_unavailable")
    data = os.pread(descriptor, size, 0)
    if len(data) != size:
        raise OSError(errno.EIO, "seat_keyring_unavailable")
    filters = (_Filter * (size // 8)).from_buffer_copy(data)
    program = _Program(len(filters), filters)
    _checked(libc.syscall(number, 1, 0, ctypes.byref(program)))


def execute(libc, keyctl_number, seccomp_number, descriptor, command):
    _join_session(libc, keyctl_number)
    _checked(libc.prctl(38, 1, 0, 0, 0))
    if libc.prctl(39, 0, 0, 0, 0) != 1:
        raise OSError(errno.EPERM, "seat_keyring_unavailable")
    _install_filter(libc, seccomp_number, descriptor)
    os.close(descriptor)
    os.execv(command[0], command)


def _owned_main(argv):
    try:
        descriptor = int(argv[0])
        command = argv[1:]
        if not command:
            raise ValueError("missing seat command")
        keyctl_number, seccomp_number = {
            "x86_64": (250, 317), "aarch64": (219, 277),
        }[platform.machine()]
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        execute(libc, keyctl_number, seccomp_number, descriptor, command)
    except (IndexError, KeyError, OSError, ValueError):
        print("seat_keyring_unavailable", file=sys.stderr)
        return 127
    return 127


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["--"]:
        return _owned_main(args)
    args = args[1:]
    if not args:
        print("usage: python -m phase_loop_runtime.seat_keyring_exec -- <argv...>", file=sys.stderr)
        return 2
    try:
        join_fresh_session_keyring()
    except OSError as exc:
        print(f"seat_keyring_exec: {exc}", file=sys.stderr)
        return 126
    os.execvp(args[0], args)
    return 127  # pragma: no cover - execvp does not return


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
