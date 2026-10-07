"""Sealed native-architecture syscall filter for seat-launch final links."""

import errno
import fcntl
import os
import platform
import struct


_ABI = {
    "x86_64": (0xC000003E, 250, 248, 249),
    "aarch64": (0xC00000B7, 219, 217, 218),
}


def keyring_filter(machine=None):
    machine = platform.machine() if machine is None else machine
    arch, keyctl, add_key, request_key = _ABI[machine]
    instructions = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, arch),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
    ]
    if machine == "x86_64":
        instructions.extend([(0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)])
    for number in (keyctl, add_key, request_key):
        instructions.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x00050000 | errno.EPERM)])
    instructions.append((0x06, 0, 0, 0x7FFF0000))
    return b"".join(struct.pack("<HBBI", *instruction) for instruction in instructions)


def sealed_keyring_filter():
    if not hasattr(os, "memfd_create"):
        raise OSError(errno.ENOSYS, "seat_filter_unavailable")
    program = keyring_filter()
    descriptor = os.memfd_create("seat-launch-filter", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(descriptor, program)
        # Linux UAPI values also support interpreters which omit these constants.
        fcntl.fcntl(descriptor, getattr(fcntl, "F_ADD_SEALS", 1033), 15)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
