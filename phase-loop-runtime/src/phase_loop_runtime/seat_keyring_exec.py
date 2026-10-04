"""Standalone stdlib final link for an owned seat launch."""

import ctypes
import errno
import fcntl
import os
import platform
import sys


class _Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]


class _Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(_Filter))]


def _checked(value):
    if value < 0:
        raise OSError(ctypes.get_errno(), "seat_keyring_unavailable")
    return value


def _join_session(libc, number):
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
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


if __name__ == "__main__":
    raise SystemExit(main())
