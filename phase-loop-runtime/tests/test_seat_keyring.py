"""Seat-launch final-link ordering and native syscall filter contract."""

import ctypes
import errno
import json
import os
import platform
from pathlib import Path
import struct
import subprocess
import sys
import uuid

import pytest


try:
    import fcntl
except ImportError:
    fcntl = None

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat-owner contract")


def _evaluate(program, arch, number):
    instructions = list(struct.iter_unpack("<HBBI", program))
    index, accumulator = 0, 0
    while index < len(instructions):
        code, yes, no, value = instructions[index]
        if code == 0x20:
            accumulator = arch if value == 4 else number
        elif code == 0x15:
            index += yes if accumulator == value else no
        elif code == 0x45:
            index += yes if accumulator & value else no
        elif code == 0x06:
            return value
        else:
            raise AssertionError(f"unsupported instruction {code}")
        index += 1
    raise AssertionError("filter did not return")


@pytest.mark.parametrize("machine,arch,numbers", [
    ("x86_64", 0xC000003E, (250, 248, 249)),
    ("aarch64", 0xC00000B7, (219, 217, 218)),
])
def test_native_keyring_calls_return_eperm(machine, arch, numbers):
    from phase_loop_runtime.seat_seccomp import keyring_filter

    program = keyring_filter(machine)
    for number in numbers:
        assert _evaluate(program, arch, number) == 0x00050000 | errno.EPERM
    assert _evaluate(program, arch, 1) == 0x7FFF0000


@pytest.mark.parametrize("machine,arch", [("x86_64", 0xC000003E), ("aarch64", 0xC00000B7)])
def test_non_native_entry_is_refused(machine, arch):
    from phase_loop_runtime.seat_seccomp import keyring_filter

    for other in (0x40000003, 0xC000003E, 0xC00000B7):
        if other != arch:
            assert _evaluate(keyring_filter(machine), other, 1) == 0x80000000


def test_x32_entry_is_refused():
    from phase_loop_runtime.seat_seccomp import keyring_filter

    assert _evaluate(keyring_filter("x86_64"), 0xC000003E, 0x40000000 | 250) == 0x80000000


def test_filter_descriptor_is_sealed():
    from phase_loop_runtime.seat_seccomp import sealed_keyring_filter

    if not hasattr(os, "memfd_create"):
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks memfd support")
        pytest.skip("interpreter lacks memfd support")
    fd = sealed_keyring_filter()
    try:
        assert fcntl.fcntl(fd, 1034) & 15 == 15
        with pytest.raises(OSError):
            os.write(fd, b"changed")
    finally:
        os.close(fd)


def test_final_link_sets_and_verifies_no_new_privileges_before_filter(monkeypatch):
    from phase_loop_runtime import seat_keyring_exec as link

    calls = []

    class Libc:
        def prctl(self, operation, *args):
            calls.append(operation)
            return 1 if operation == 39 else 0

    monkeypatch.setattr(link, "_join_session", lambda libc, nr: calls.append("join"))
    monkeypatch.setattr(link, "_install_filter", lambda libc, nr, fd: calls.append("filter"))
    monkeypatch.setattr(link.os, "close", lambda fd: calls.append("close"))
    monkeypatch.setattr(link.os, "execv", lambda path, argv: calls.append("exec"))
    link.execute(Libc(), 250, 317, 10, ["/bin/true"])
    assert calls == ["join", 38, 39, "filter", "close", "exec"]


def test_final_link_does_not_exec_when_no_new_privileges_is_unverified(monkeypatch):
    from phase_loop_runtime import seat_keyring_exec as link

    class Libc:
        def prctl(self, operation, *args):
            return 0

    monkeypatch.setattr(link, "_join_session", lambda libc, nr: None)
    monkeypatch.setattr(link.os, "execv", lambda *args: pytest.fail("provider ran"))
    with pytest.raises(OSError):
        link.execute(Libc(), 250, 317, 10, ["/bin/true"])


@pytest.mark.skipif(sys.platform != "linux", reason="Linux seat-owner contract")
def test_unsealed_filter_refuses_before_provider_exec(tmp_path):
    from phase_loop_runtime import seat_keyring_exec as link

    if not hasattr(os, "memfd_create"):
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks memfd support")
        pytest.skip("interpreter lacks memfd support")
    fd = os.memfd_create("seat-filter-test", os.MFD_ALLOW_SEALING)
    try:
        os.write(fd, struct.pack("<HBBI", 6, 0, 0, 0x7FFF0000))
        marker = tmp_path / "ran"
        done = subprocess.run(
            [sys.executable, "-I", "-S", str(Path(link.__file__)), str(fd),
             "/bin/sh", "-c", f"touch {marker}"],
            pass_fds=(fd,), capture_output=True, text=True,
        )
        assert done.returncode == 127
        assert not marker.exists()
        assert "seat_keyring_unavailable" in done.stderr
    finally:
        os.close(fd)


def test_real_final_link_joins_before_deny_and_completes_probe():
    from phase_loop_runtime import seat_keyring_exec as link
    from phase_loop_runtime.seat_seccomp import sealed_keyring_filter

    if not hasattr(os, "memfd_create"):
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks memfd support")
        pytest.skip("interpreter lacks memfd support")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    keyctl, add_key, request_key = {"x86_64": (250, 248, 249), "aarch64": (219, 217, 218)}[platform.machine()]
    name = ("seat-test-" + uuid.uuid4().hex).encode()
    serial = libc.syscall(add_key, ctypes.c_char_p(b"user"), ctypes.c_char_p(name),
                          ctypes.c_char_p(b"synthetic"), 9, -3)
    if serial < 0:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks keyring support")
        pytest.skip("kernel keyrings unavailable in this test environment")
    try:
        assert libc.syscall(keyctl, 5, serial, 0x3F000000) == 0
        fd = sealed_keyring_filter()
        try:
            probe = f'''
import ctypes,json,os
libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
with open('/proc/keys') as source:
    serials={{int(line.split()[0],16) for line in source if line.split()}}
result={{'proc_keys_read':True,'sentinel_present':{serial} in serials}}
for label,number,args in (
    ('read',{keyctl},(11,{serial},ctypes.c_void_p(),0)),
    ('add',{add_key},(ctypes.c_char_p(b'user'),ctypes.c_char_p(b'seat-child'),ctypes.c_char_p(b'synthetic'),9,-3)),
    ('request',{request_key},(ctypes.c_char_p(b'user'),ctypes.c_char_p(b'seat-child'),ctypes.c_void_p(),-3)),
):
    value=libc.syscall(number,*args)
    result[label]={{'result':value,'errno':ctypes.get_errno()}}
result['completed']=True
print(json.dumps(result))
'''
            done = subprocess.run(
                [sys.executable, "-I", "-S", str(Path(link.__file__)), str(fd),
                 sys.executable, "-I", "-S", "-c", probe],
                pass_fds=(fd,), capture_output=True, text=True,
            )
            assert done.returncode == 0, done.stderr
            result = json.loads(done.stdout)
            assert result["completed"] and result["proc_keys_read"]
            assert not result["sentinel_present"]
            for label in ("read", "add", "request"):
                assert result[label] == {"result": -1, "errno": errno.EPERM}
        finally:
            os.close(fd)
    finally:
        assert libc.syscall(keyctl, 9, serial, -3) == 0


@pytest.mark.parametrize('join,deny', [(True, True), (False, True), (True, False)])
def test_final_link_layers_have_independent_controls(tmp_path, join, deny):
    from phase_loop_runtime import seat_keyring_exec as link
    from phase_loop_runtime.seat_seccomp import sealed_keyring_filter

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    keyctl, add_key = {'x86_64': (250, 248), 'aarch64': (219, 217)}[platform.machine()]
    prefix = 'seat-control-' + uuid.uuid4().hex
    keys = []
    descriptor = None
    try:
        for label, ring, permissions in (('possession', -3, 0x3F000000),
                                         ('metadata', -3, 0x3F010000),
                                         ('user', -4, 0x3F010000),
                                         ('user-session', -5, 0x3F010000)):
            serial = libc.syscall(add_key, ctypes.c_char_p(b'user'),
                                  ctypes.c_char_p((prefix + '-' + label).encode()),
                                  ctypes.c_char_p(b'synthetic'), 9, ring)
            if serial < 0:
                if os.environ.get('PHASE_LOOP_REQUIRE_SEAT_OWNER') == '1':
                    pytest.fail('required seat-owner lane lacks keyring support')
                pytest.skip('kernel keyrings unavailable in this test environment')
            keys.append((label, serial, ring))
            if ring == -3:
                assert libc.syscall(keyctl, 5, serial, permissions) == 0
        parent_ring = libc.syscall(keyctl, 0, -3, 1)
        assert parent_ring > 0
        source = Path(link.__file__).read_text()
        if not join:
            old = '    _join_session(libc, keyctl_number)'
            assert source.count(old) == 1
            source = source.replace(old, '    pass', 1)
        if not deny:
            old = '    _install_filter(libc, seccomp_number, descriptor)'
            assert source.count(old) == 1
            source = source.replace(old, '    pass', 1)
        control = tmp_path / 'final-link.py'
        control.write_text(source)
        probe = '''
import ctypes,json
libc=ctypes.CDLL(None,use_errno=True);libc.syscall.restype=ctypes.c_long
with open('/proc/keys') as stream:
 serials={int(line.split()[0],16) for line in stream if line.split()}
reads={}
for label,serial,ring in KEYS:
 ctypes.set_errno(0)
 value=libc.syscall(KEYCTL,11,serial,ctypes.c_void_p(),0)
 reads[label]={'value':value,'errno':ctypes.get_errno()}
own=libc.syscall(KEYCTL,0,-3,0)
own_size=libc.syscall(KEYCTL,11,own,ctypes.c_void_p(),0) if own>0 else -1
parent_read=libc.syscall(KEYCTL,11,PARENT,ctypes.c_void_p(),0)
print(json.dumps({'proc_keys_read':True,'completed':True,'serials':sorted(serials),
 'reads':reads,'own':own,'own_size':own_size,'parent_read':parent_read}))
'''.replace('KEYS', repr(keys)).replace('KEYCTL', str(keyctl)).replace('PARENT', str(parent_ring))
        descriptor = sealed_keyring_filter()
        done = subprocess.run(
            [sys.executable, '-I', '-S', str(control), str(descriptor),
             sys.executable, '-I', '-S', '-c', probe],
            pass_fds=(descriptor,), capture_output=True, text=True, timeout=10,
        )
        assert done.returncode == 0, done.stderr
        facts = json.loads(done.stdout)
        assert facts['proc_keys_read'] and facts['completed']
        by_name = {label: serial for label, serial, _ in keys}
        assert (by_name['possession'] in facts['serials']) is (not join)
        assert all(by_name[label] in facts['serials'] for label in ('metadata', 'user', 'user-session'))
        if deny:
            assert all(value == {'value': -1, 'errno': errno.EPERM} for value in facts['reads'].values())
        else:
            assert facts['own'] != parent_ring and facts['own_size'] == 0
            assert facts['parent_read'] < 0
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for _, serial, ring in reversed(keys):
            assert libc.syscall(keyctl, 9, serial, ring) == 0
