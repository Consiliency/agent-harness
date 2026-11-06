"""The test-only observation wrapper around the worker bootstrap's filter installer.

``python -I -S -B filter_observer.py <claude_sdk_bootstrap.py> <base64 program>`` loads
the unmodified bootstrap by path, installs the program exactly as the worker does, then
attempts each operation and prints ``{operation: "allowed" | "denied" | "error"}`` as JSON.
``denied`` means the kernel returned ``EPERM``; an operation the kernel itself refuses for
another reason reads ``error``. The production bootstrap has no such hook.
"""

import base64
import ctypes
import errno
import importlib.util
import json
import os
import socket
import sys
import threading


def attempt(action):
    try:
        action()
    except PermissionError:
        return "denied"
    except OSError as exc:
        return "denied" if exc.errno == errno.EPERM else "error"
    return "allowed"


def main(argv):
    spec = importlib.util.spec_from_file_location("observed_bootstrap", argv[1])
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    bootstrap.install_filter(base64.b64decode(argv[2]), os.uname().machine)
    libc = ctypes.CDLL(None, use_errno=True)

    def raw(number, *args):
        def call():
            if libc.syscall(number, *args) == -1:
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
        return call

    def thread():
        worker = threading.Thread(target=lambda: None)
        worker.start()
        worker.join()

    def event_loop():
        import asyncio

        asyncio.new_event_loop().close()

    def fork():
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        os.waitpid(pid, 0)

    observed = {
        "thread": attempt(thread),
        "socketpair_unix": attempt(lambda: [s.close() for s in socket.socketpair()]),
        "event_loop": attempt(event_loop),
        "execve": attempt(lambda: os.execv("/bin/true", ["true"])),
        "fork": attempt(fork),
        "socket_inet": attempt(lambda: socket.socket(socket.AF_INET).close()),
        "socket_unix": attempt(lambda: socket.socket(socket.AF_UNIX).close()),
        "socket_alg": attempt(lambda: socket.socket(38, socket.SOCK_SEQPACKET).close()),
        "socketpair_inet": attempt(raw(53, socket.AF_INET, socket.SOCK_STREAM, 0,
                                       ctypes.byref((ctypes.c_int * 2)()))),
        "unshare": attempt(lambda: os.unshare(os.CLONE_NEWUSER)),
        "setuid": attempt(lambda: os.setuid(os.getuid())),
        "keyctl": attempt(raw(250, 0, 0, 0, 0, 0)),
        "ptrace": attempt(raw(101, 0, 0, 0, 0)),
        "mount": attempt(raw(165, 0, 0, 0, 0, 0)),
    }
    sys.stdout.write(json.dumps(observed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
