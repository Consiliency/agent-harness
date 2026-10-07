"""The final-link ordering control is isolated in a child process."""

import ctypes, ctypes.util, errno, os, platform, sys
import pytest


NR_KEYCTL = {"x86_64": 250, "aarch64": 219, "armv7l": 311, "ppc64le": 271,
             "s390x": 349}.get(platform.machine())
PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000
KEYCTL_JOIN_SESSION_KEYRING = 1


class SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
                ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16),
                ("filter", ctypes.POINTER(SockFilter))]


def _child():
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6",
                       use_errno=True)
    libc.prctl.restype = ctypes.c_int
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.syscall.restype = ctypes.c_long
    libc.syscall.argtypes = [ctypes.c_long] * 6
    prog = (SockFilter * 4)(
        SockFilter(0x20, 0, 0, 0),
        SockFilter(0x15, 0, 1, NR_KEYCTL),
        SockFilter(0x06, 0, 0, SECCOMP_RET_ERRNO | errno.EPERM),
        SockFilter(0x06, 0, 0, SECCOMP_RET_ALLOW),
    )
    fprog = SockFprog(4, prog)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        os._exit(10)
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER,
                  ctypes.cast(ctypes.byref(fprog), ctypes.c_void_p),
                  0, 0) != 0:
        os._exit(11)
    ctypes.set_errno(0)
    rc = libc.syscall(NR_KEYCTL, KEYCTL_JOIN_SESSION_KEYRING, 0, 0, 0, 0)
    eno = ctypes.get_errno()
    os._exit(42 if (rc == -1 and eno == errno.EPERM) else 43)


@pytest.mark.skipif(sys.platform != "linux" or NR_KEYCTL is None,
                    reason="Linux keyctl syscall number required")
def test_keyring_deny_seccomp_blocks_join_before_exec():
    pid = os.fork()
    if pid == 0:
        try:
            _child()
        except BaseException:
            os._exit(99)
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status), "child did not exit normally"
    code = os.WEXITSTATUS(status)
    assert code == 42, f"child exit {code}: join not EPERM-blocked as modeled"
