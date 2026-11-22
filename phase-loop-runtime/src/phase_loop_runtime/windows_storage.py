"""Protected NTFS handles; integration must not substitute ordinary path opens."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time
import uuid


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                ("inherit", wintypes.BOOL)]


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


def _apis():
    if os.name != "nt":
        raise OSError("Protected NTFS storage requires native Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    native = ctypes.WinDLL("ntdll", use_last_error=True)
    native.NtSetInformationFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    native.NtSetInformationFile.restype = ctypes.c_long
    native.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    native.RtlNtStatusToDosError.restype = wintypes.DWORD
    kernel.NtSetInformationFile = native.NtSetInformationFile
    kernel.RtlNtStatusToDosError = native.RtlNtStatusToDosError
    signatures = {
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "CreateDirectoryW": ([wintypes.LPCWSTR, ctypes.c_void_p], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "GetFileInformationByHandle": ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
        "GetVolumeInformationByHandleW": ([wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD], wintypes.BOOL),
        "GetDriveTypeW": ([wintypes.LPCWSTR], wintypes.UINT),
        "FlushFileBuffers": ([wintypes.HANDLE], wintypes.BOOL),
        "WriteFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "ReadFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "LocalFree": ([ctypes.c_void_p], ctypes.c_void_p),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    signatures = {
        "OpenProcessToken": ([wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "GetTokenInformation": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "ConvertSidToStringSidW": ([ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW": ([wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "ConvertSecurityDescriptorToStringSecurityDescriptorW": ([ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "GetSecurityInfo": ([wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], wintypes.DWORD),
    }
    for name, (args, result) in signatures.items():
        function = getattr(security, name)
        function.argtypes, function.restype = args, result
    return kernel, security


def _require(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


def _current_sid(kernel, security):
    token = wintypes.HANDLE()
    _require(security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        _require(security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        rendered = wintypes.LPWSTR()
        _require(security.ConvertSidToStringSidW(sid, ctypes.byref(rendered)))
        try:
            return rendered.value
        finally:
            kernel.LocalFree(rendered)
    finally:
        kernel.CloseHandle(token)


class PrivateSecurity:
    def __init__(self):
        self.kernel, self.security = _apis()
        sid = _current_sid(self.kernel, self.security)
        self.sid = sid
        self.sddl = f"D:P(A;;FA;;;SY)(A;;FA;;;{sid})"
        self.descriptor = ctypes.c_void_p()
        _require(self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(f"O:{sid}{self.sddl}", 1, ctypes.byref(self.descriptor), None))
        self.attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), self.descriptor, False)

    def verify(self, handle):
        descriptor = ctypes.c_void_p()
        owner = ctypes.c_void_p()
        result = self.security.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
        if result:
            raise ctypes.WinError(result)
        rendered = wintypes.LPWSTR()
        owner_sid = wintypes.LPWSTR()
        try:
            _require(self.security.ConvertSidToStringSidW(owner, ctypes.byref(owner_sid)))
            if owner_sid.value not in {self.sid, "S-1-5-18"}:
                raise PermissionError("Storage owner is not the current user or SYSTEM")
            _require(self.security.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(rendered), None))
            if rendered.value != self.sddl:
                raise PermissionError("Storage ACL is not protected current-user and SYSTEM only")
        finally:
            if rendered:
                self.kernel.LocalFree(rendered)
            if owner_sid:
                self.kernel.LocalFree(owner_sid)
            self.kernel.LocalFree(descriptor)

    def close(self):
        if self.descriptor:
            self.kernel.LocalFree(self.descriptor)
            self.descriptor = None


class BoundDirectory:
    """Hold all ancestors against rename, deletion and reparse modification."""

    def __init__(self, path: Path, *, create_private=False, deadline=None):
        self.deadline = deadline
        self.kernel, _ = _apis()
        self.path = Path(os.path.abspath(path))
        self.handles = []
        self.pin = None
        self.security = PrivateSecurity()
        created_indices = []
        try:
            if len(self.path.drive) != 2 or self.path.drive[1] != ":" or self.kernel.GetDriveTypeW(self.path.anchor) != 3:
                raise OSError("Storage requires a local fixed NTFS volume")
            current = Path(self.path.anchor)
            for index, component in enumerate(self.path.parts):
                self._check_deadline()
                if index:
                    current /= component
                if create_private and index == len(self.path.parts) - 1:
                    created = bool(self.kernel.CreateDirectoryW(str(current), ctypes.byref(self.security.attributes)))
                    if created:
                        created_indices.append(index)
                    if not created:
                        error = ctypes.get_last_error()
                        if error != 183:
                            raise ctypes.WinError(error)
                # FILE_LIST_DIRECTORY participates in sharing checks; a handle
                # requesting only attributes does not prevent directory rename.
                handle = self._open_directory(current, 0x00020081, 1)
                if handle == ctypes.c_void_p(-1).value and create_private and ctypes.get_last_error() in {2, 3}:
                    _require(self.kernel.CreateDirectoryW(str(current), ctypes.byref(self.security.attributes)))
                    created_indices.append(index)
                    handle = self._open_directory(current, 0x00020081, 1)
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.handles.append(handle)
                info = self.info(handle)
                if not info.attributes & 0x10 or info.attributes & 0x400:
                    raise OSError("Storage ancestors must be directories without reparse points")
                if index == 0:
                    filesystem = ctypes.create_unicode_buffer(32)
                    _require(self.kernel.GetVolumeInformationByHandleW(handle, None, 0, None, None, None, filesystem, len(filesystem)))
                    if filesystem.value != "NTFS":
                        raise OSError("Storage requires NTFS")
            if create_private:
                self.security.verify(self.handles[-1])
                pin = self.kernel.CreateFileW(str(self.path / ".directory-binding"), 0x80020080, 1,
                                              ctypes.byref(self.security.attributes), 4, 0x00200000, None)
                if pin == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.pin = pin
                info = self.info(pin)
                if info.attributes & (0x400 | 0x10) or info.links != 1:
                    raise OSError("Directory binding is not one regular private file")
                self.security.verify(pin)
                self._enable_directory_flush(-1, self.path)
                self.flush()
                for index in reversed(created_indices):
                    parent = Path(*self.path.parts[:index])
                    self._enable_directory_flush(index - 1, parent)
                    _require(self.kernel.FlushFileBuffers(self.handles[index - 1]))
        except BaseException:
            self.close()
            raise

    def info(self, handle):
        value = _FileInfo()
        _require(self.kernel.GetFileInformationByHandle(handle, ctypes.byref(value)))
        return value

    def _open_directory(self, path, access, sharing):
        deadline = min(time.monotonic() + 30, self.deadline if self.deadline is not None else float("inf"))
        while True:
            self._check_deadline()
            handle = self.kernel.CreateFileW(str(path), access, sharing, None, 3, 0x02200000, None)
            if handle != ctypes.c_void_p(-1).value or ctypes.get_last_error() != 32:
                return handle
            if time.monotonic() >= deadline:
                return handle
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))

    def _check_deadline(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("Protected storage admission deadline expired")

    def open_record(self, name, *, create):
        import msvcrt
        if not name or name in {".", ".."} or any(char in name for char in '/\\:\0') or name.endswith((".", " ")):
            raise ValueError("Record name must be one ordinary path component")
        access = 0xC0020080 if create else 0x80020080
        handle = self.kernel.CreateFileW(str(self.path / name), access, 3,
                                        ctypes.byref(self.security.attributes) if create else None,
                                        4 if create else 3, 0x80200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = self.info(handle)
            if info.attributes & (0x400 | 0x10) or info.links != 1:
                raise OSError("Record is not one regular private file")
            self.security.verify(handle)
            flags = os.O_BINARY | os.O_NOINHERIT | (os.O_RDWR | os.O_APPEND if create else os.O_RDONLY)
            return msvcrt.open_osfhandle(handle, flags)
        except BaseException:
            self.kernel.CloseHandle(handle)
            raise

    def _enable_directory_flush(self, index, path):
        # A pinned child prevents this directory from becoming empty or being
        # renamed while its read guard is replaced. NTFS refuses reparse points
        # on nonempty directories. Ancestors remain held throughout.
        previous = self.info(self.handles[index])
        self.kernel.CloseHandle(self.handles[index])
        self.handles[index] = None
        handle = self._open_directory(path, 0xC0020081, 3)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles[index] = handle
        current = self.info(handle)
        if (current.volume, current.index_high, current.index_low, current.attributes) != (previous.volume, previous.index_high, previous.index_low, previous.attributes):
            raise OSError("Directory identity changed before flush")

    def flush(self):
        self._check_deadline()
        _require(self.kernel.FlushFileBuffers(self.handles[-1]))
        self._check_deadline()

    def create_record(self, name: str, payload: bytes, *, replace=False):
        """Create once, with a private ACL, then flush before acknowledging.

        Replacement uses the open source handle and a bound destination directory.
        Failed flush or rename never acknowledges a committed replacement.
        """
        self._check_deadline()
        if not name or name in {".", ".."} or any(char in name for char in '/\\:\0') or name.endswith((".", " ")):
            raise ValueError("Record name must be one ordinary path component")
        path = self.path / name
        if replace:
            try:
                self.read_record(name, max_bytes=1048576)
            except FileNotFoundError:
                pass
        temporary = self.path / (".replace-" + uuid.uuid4().hex) if replace else path
        handle = self.kernel.CreateFileW(str(temporary), 0xC0030080, 1,
                                        ctypes.byref(self.security.attributes), 1,
                                        0x80200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = self.info(handle)
            if info.attributes & (0x400 | 0x10) or info.links != 1:
                raise OSError("Record is not one regular private file")
            self.security.verify(handle)
            offset = 0
            while offset < len(payload):
                chunk = payload[offset:offset + 65536]
                written = wintypes.DWORD()
                _require(self.kernel.WriteFile(handle, chunk, len(chunk), ctypes.byref(written), None))
                if not written.value:
                    raise OSError("Record write made no progress")
                offset += written.value
            _require(self.kernel.FlushFileBuffers(handle))
            if replace:
                target = name
                units = len(target.encode("utf-16le")) // 2
                class RenameInfo(ctypes.Structure):
                    _fields_ = [("replace", wintypes.BOOL), ("root", wintypes.HANDLE),
                                ("length", wintypes.DWORD), ("name", wintypes.WCHAR * (units + 1))]
                # Native same-directory rename uses the source's already-bound
                # parent. Win32 absolute rename reopens it for write and conflicts
                # with the ancestor guard's sharing restriction.
                rename = RenameInfo(True, None, len(target.encode("utf-16le")), target)
                class IOStatus(ctypes.Structure):
                    _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]
                io_status = IOStatus()
                status = self.kernel.NtSetInformationFile(handle, ctypes.byref(io_status), ctypes.byref(rename), ctypes.sizeof(rename), 10)
                if status < 0:
                    raise ctypes.WinError(self.kernel.RtlNtStatusToDosError(status))
                _require(self.kernel.FlushFileBuffers(handle))
                current = self.info(handle)
                if (current.volume, current.index_high, current.index_low) != (info.volume, info.index_high, info.index_low):
                    raise OSError("Record identity changed during replacement")
            self.flush()
            return info.volume, info.index_high, info.index_low
        finally:
            self.kernel.CloseHandle(handle)

    def read_record(self, name: str, *, max_bytes=4096):
        if not name or name in {".", ".."} or any(char in name for char in '/\\:\0') or name.endswith((".", " ")):
            raise ValueError("Record name must be one ordinary path component")
        handle = self.kernel.CreateFileW(str(self.path / name), 0x80020080, 1, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = self.info(handle)
            if info.attributes & (0x400 | 0x10) or info.links != 1:
                raise OSError("Record is not one regular private file")
            self.security.verify(handle)
            if (info.size_high << 32) + info.size_low > max_bytes:
                raise ValueError("Record exceeds metadata limit")
            buffer = ctypes.create_string_buffer(max_bytes + 1)
            count = wintypes.DWORD()
            _require(self.kernel.ReadFile(handle, buffer, max_bytes + 1, ctypes.byref(count), None))
            if count.value > max_bytes:
                raise ValueError("Record exceeds metadata limit")
            return buffer.raw[:count.value]
        finally:
            self.kernel.CloseHandle(handle)

    def close(self):
        for handle in reversed(self.handles):
            if handle:
                self.kernel.CloseHandle(handle)
        self.handles.clear()
        if self.pin:
            self.kernel.CloseHandle(self.pin)
            self.pin = None
        self.security.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
