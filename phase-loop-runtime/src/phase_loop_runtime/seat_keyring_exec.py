"""Join a fresh anonymous session keyring, then exec the rest of the argv (J3, D8).

The first element of a jailed seat's launch prefix. Possession of a key is independent of
uid, so a seat that merely changed uid would still possess the operator's session
keyring; joining a fresh anonymous one first leaves it none of the operator's keys. It
runs before the seccomp filter, which denies ``keyctl``.

Usage: ``python -m phase_loop_runtime.seat_keyring_exec -- <argv...>``. No keyutils
binary is needed: the call is made through ``syscall(2)``.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys

KEYCTL_JOIN_SESSION_KEYRING = 1
_KEYCTL_NR = {"x86_64": 250, "aarch64": 219}


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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
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
