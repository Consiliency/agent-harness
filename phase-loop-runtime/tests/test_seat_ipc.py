"""Owned review callers have an independent IPC namespace."""

import ctypes
import json
import os
import secrets
import sys
import threading

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress


pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux IPC namespace contract')


@pytest.mark.parametrize('heartbeat', [False, True])
def test_review_caller_cannot_open_parent_ipc_objects(tmp_path, heartbeat):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.shmat.restype = ctypes.c_void_p
    libc.mq_open.restype = ctypes.c_int
    key = secrets.randbelow(0x3fffffff) + 1
    flags = 0o600 | 0o1000 | 0o2000
    shm = libc.shmget(key, 4096, flags)
    semaphore = libc.semget(key, 1, flags)
    queue = libc.msgget(key, flags)
    name = ('/seat-' + secrets.token_hex(16)).encode()
    mq = libc.mq_open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600, None)
    address = None
    try:
        assert min(shm, semaphore, queue, mq) >= 0, 'required IPC fixture support unavailable'
        address = libc.shmat(shm, None, 0)
        assert address != ctypes.c_void_p(-1).value
        nonce = secrets.token_bytes(16)
        ctypes.memmove(address, nonce, len(nonce))
        assert ctypes.string_at(address, len(nonce)) == nonce
        assert libc.semctl(semaphore, 0, 16, 7) == 0
        assert libc.semctl(semaphore, 0, 12) == 7
        payload = ctypes.create_string_buffer(ctypes.sizeof(ctypes.c_long) + len(nonce))
        ctypes.c_long.from_buffer(payload).value = 1
        ctypes.memmove(ctypes.addressof(payload) + ctypes.sizeof(ctypes.c_long), nonce, len(nonce))
        assert libc.msgsnd(queue, payload, len(nonce), 0) == 0
        assert libc.mq_send(mq, nonce, len(nonce), 0) == 0
        source = '''
import ctypes,json,os,sys
libc=ctypes.CDLL(None,use_errno=True)
libc.shmat.restype=ctypes.c_void_p
key,shm,semaphore,queue=map(int,sys.argv[1:5])
message=ctypes.create_string_buffer(128)
result={
 'shared_by_key':libc.shmget(key,4096,0),
 'shared_by_id':libc.shmat(shm,None,0)==ctypes.c_void_p(-1).value,
 'semaphore_by_key':libc.semget(key,1,0),
 'semaphore_by_id':libc.semctl(semaphore,0,12),
 'queue_by_key':libc.msgget(key,0),
 'queue_by_id':libc.msgrcv(queue,message,64,0,0o4000),
 'posix_queue':libc.mq_open(sys.argv[5].encode(),os.O_RDONLY|os.O_NONBLOCK),
 'ipc_namespace':os.stat('/proc/self/ns/ipc').st_ino,
 'ipc_tables_empty':all(len(open('/proc/sysvipc/'+name).read().splitlines())==1
                        for name in ('shm','sem','msg')),
}
print(json.dumps(result))
'''
        monitor = panel_invoker._ReviewMonitor(tmp_path / 'monitor.json', 'ipc-control', 0,
                                               threading.Event()) if heartbeat else None
        with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
            try:
                result = panel_invoker._run_leg_with_liveness(
                    ['/usr/bin/python3', '-I', '-S', '-c', source,
                     str(key), str(shm), str(semaphore), str(queue), name.decode()],
                    cwd=tmp_path, env={'PATH': '/usr/bin:/bin'}, deadline_s=30,
                    review_monitor=monitor,
                )
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        assert result.returncode == 0, result.stderr
        facts = json.loads(result.stdout)
        assert facts.pop('ipc_namespace') != os.stat('/proc/self/ns/ipc').st_ino
        assert facts.pop('ipc_tables_empty') is True
        assert facts.pop('shared_by_id') is True
        assert all(value == -1 for value in facts.values()), facts
    finally:
        if address not in (None, ctypes.c_void_p(-1).value):
            libc.shmdt(ctypes.c_void_p(address))
        if shm >= 0:
            libc.shmctl(shm, 0, None)
        if semaphore >= 0:
            libc.semctl(semaphore, 0, 0)
        if queue >= 0:
            libc.msgctl(queue, 0, None)
        if mq >= 0:
            libc.mq_close(mq)
            libc.mq_unlink(name)
