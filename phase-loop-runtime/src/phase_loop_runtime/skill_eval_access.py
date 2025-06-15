"""Host-side access observation; reads are evidence, never reader attribution."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import struct
import sys
import threading
from types import MappingProxyType


class AccessObserver:
    OPEN = 0x20
    ACCESS = 0x1
    INVALID = 0x2 | 0x4 | 0x8 | 0x400 | 0x800 | 0x2000 | 0x4000 | 0x8000

    def __init__(self, root: Path, paths: list[str]):
        if sys.platform != "linux":
            raise ValueError("inotify unsupported: Linux required")
        self.fd = -1
        self.events = {path: {"open": False, "access": False} for path in paths}
        self.errors: list[str] = []
        self._stop = threading.Event()
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        mapping = {}
        try:
            for path in paths:
                source = root / path
                if source.is_symlink() or not source.is_file() or source.stat().st_nlink != 1:
                    raise ValueError("observer requires private regular files")
                wd = libc.inotify_add_watch(self.fd, os.fsencode(source),
                                           self.OPEN | self.ACCESS | self.INVALID)
                if wd < 0 or wd in mapping:
                    raise OSError(ctypes.get_errno(), "inotify_add_watch")
                mapping[wd] = path
            self.watches = MappingProxyType(mapping)
        except BaseException:
            os.close(self.fd)
            self.fd = -1
            raise
        self._thread = threading.Thread(target=self._observe, daemon=True)

    def feed(self, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            if offset + 16 > len(data):
                self.errors.append("truncated_event")
                return
            wd, mask, cookie, length = struct.unpack_from("iIII", data, offset)
            offset += 16 + length
            if offset > len(data):
                self.errors.append("truncated_event")
                return
            if mask & self.INVALID or wd not in self.watches:
                self.errors.append("watch_invalid_or_overflow")
            if wd in self.watches:
                facts = self.events[self.watches[wd]]
                facts["open"] |= bool(mask & self.OPEN)
                facts["access"] |= bool(mask & self.ACCESS)

    def drain(self) -> None:
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno != errno.EAGAIN:
                    self.errors.append("observer_read_failed")
                return
            if not data:
                return
            self.feed(data)

    def _observe(self):
        while not self._stop.wait(.01):
            self.drain()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        self._thread.join()
        self.drain()
        os.close(self.fd)
        self.fd = -1

    def receipt(self):
        return {"events": self.events, "errors": sorted(set(self.errors))}
