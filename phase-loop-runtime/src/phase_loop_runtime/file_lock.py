"""Exclusive record locks and distinct generation-lease ownership."""
from __future__ import annotations

import errno
import os
import time
from pathlib import Path


def _descriptor(handle) -> int:
    return handle if isinstance(handle, int) else handle.fileno()


def _windows_lock(fd: int, *, release: bool = False) -> None:
    import ctypes
    import msvcrt

    crt = ctypes.CDLL("ucrtbase", use_errno=True)
    crt._set_doserrno.argtypes = [ctypes.c_ulong]
    crt._get_doserrno.argtypes = [ctypes.POINTER(ctypes.c_ulong)]
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        crt._set_doserrno(0)
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
        except OSError as error:
            native = ctypes.c_ulong()
            crt._get_doserrno(ctypes.byref(native))
            # EACCES alone is ambiguous. Retry only ERROR_LOCK_VIOLATION;
            # access-denied, bad descriptors and I/O failures remain errors.
            if not release and (getattr(error, "winerror", None) or native.value) == 33:
                raise BlockingIOError(errno.EWOULDBLOCK, "Exclusive lock is held") from error
            raise
    finally:
        os.lseek(fd, position, os.SEEK_SET)


def acquire_exclusive(handle, *, blocking: bool = True) -> None:
    fd = _descriptor(handle)
    if os.name != "nt":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    while True:
        try:
            _windows_lock(fd)
            return
        except BlockingIOError:
            if not blocking:
                raise
            time.sleep(0.05)


def release_exclusive(handle) -> None:
    fd = _descriptor(handle)
    if os.name == "nt":
        _windows_lock(fd, release=True)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def open_generation_lease(path: Path) -> int:
    """Return a non-inheritable descriptor whose last owner holds the lease.

    Windows sharing exclusion follows duplicate file handles, unlike byte-range
    lock ownership. A supervisor must explicitly retain a duplicate until its
    entire executor job is quiescent; ordinary lock inheritance is insufficient.
    """
    if os.name != "nt":
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            acquire_exclusive(fd, blocking=False)
            return fd
        except BaseException:
            os.close(fd)
            raise
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000 | 0x40000000, 0, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 32:  # ERROR_SHARING_VIOLATION, not ERROR_ACCESS_DENIED.
            raise BlockingIOError(errno.EWOULDBLOCK, "Generation lease is held")
        raise ctypes.WinError(error)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY | os.O_NOINHERIT)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
