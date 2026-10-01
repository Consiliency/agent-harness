"""Unified seat-launch namespace and allowlisted-view contract."""

from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat-owner contract")


def test_owner_has_all_namespaces_and_keeps_filtered_network():
    owner = panel_invoker._seat_owner((), filtered_network=True)
    for flag in ("--unshare-pid", "--unshare-ipc", "--unshare-uts",
                 "--unshare-cgroup-try", "--new-session", "--die-with-parent"):
        assert flag in owner
    assert "--unshare-net" not in owner
    assert "--seccomp" not in owner


def test_admin_owner_has_a_private_network():
    owner = panel_invoker._seat_owner((), filtered_network=False)
    assert "--unshare-net" in owner


def test_administrative_launch_keeps_its_private_network_with_outer_context(tmp_path):
    inherited = ('outer-operation-context',)
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(inherited)
    try:
        with panel_invoker.launch_owned(
            ['/usr/bin/python3', '-I', '-c', "import os; print(os.stat('/proc/self/ns/net').st_ino)"],
            role=panel_invoker.SeatLaunchRole.PROVIDER_ADMIN,
            profile=panel_invoker.SeatProfile(env={'PATH': '/usr/bin:/bin'}), cwd=tmp_path,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as proc:
            stdout, stderr = proc.communicate()
        assert proc.returncode == 0, stderr.decode()
        assert int(stdout) != os.stat('/proc/self/ns/net').st_ino
        assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == inherited
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)


def test_view_has_private_proc_and_no_host_directory_write_bind(tmp_path):
    view = panel_invoker._seat_filesystem_view(tmp_path)
    assert "--proc" in view and view[view.index("--proc") + 1] == "/proc"
    assert "--dev" in view and view[view.index("--dev") + 1] == "/dev"
    assert "--remount-ro" in view
    assert "--bind" not in view
    assert "--ro-bind" in view
    assert not any(str(Path.home()) == item for item in view)
    assert "/sys/fs/cgroup" not in view
    assert "/sys" not in view


def test_view_binds_only_individual_precreated_outputs(tmp_path):
    output = tmp_path / "answer.txt"
    output.write_text("")
    view = panel_invoker._seat_filesystem_view(tmp_path, outputs=(output,))
    writable = [view[index + 1:index + 3] for index, item in enumerate(view) if item == "--bind"]
    assert writable == [[str(output), str(output)]]


def test_view_refuses_a_linked_output(tmp_path):
    output = tmp_path / "answer.txt"
    output.symlink_to(tmp_path / "absent")
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        panel_invoker._seat_filesystem_view(tmp_path, outputs=(output,))


def test_view_refuses_a_directory_output(tmp_path):
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        panel_invoker._seat_filesystem_view(tmp_path, outputs=(tmp_path,))


def test_view_refuses_a_linked_input_source(tmp_path):
    source = tmp_path / "input"
    source.symlink_to(tmp_path)
    with pytest.raises(sandbox_egress.SeatIdentityUnverified):
        panel_invoker._seat_filesystem_view(tmp_path, readonly_paths=(source,))


def test_review_without_filtered_egress_refuses_even_when_optional(monkeypatch, tmp_path):
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
    monkeypatch.setattr(panel_invoker.subprocess, "Popen", lambda *a, **k: pytest.fail("provider ran"))
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(())
    try:
        with pytest.raises(sandbox_egress.EgressUnavailable):
            panel_invoker.launch_owned(
                ["/bin/true"], role="PROVIDER_REVIEW",
                profile=panel_invoker.SeatProfile(env={"PATH": "/usr/bin:/bin"}), cwd=tmp_path,
            )
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)


def test_real_admin_launch_carries_owner_and_final_link(tmp_path):
    if not hasattr(os, "memfd_create"):
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks memfd support")
        pytest.skip("interpreter lacks memfd support")
    probe = '''
import ctypes,json,os
libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
import platform
number={'x86_64':250,'aarch64':219}[platform.machine()]
value=libc.syscall(number,0,-3,0)
with open('/proc/self/status') as source:
 status=dict(line.split(':',1) for line in source if ':' in line)
print(json.dumps({'uid':os.getuid(),'pid_namespace':os.stat('/proc/self/ns/pid').st_ino,
                 'bounding':status['CapBnd'].strip(),'no_new_privs':status['NoNewPrivs'].strip(),
                 'keyctl_result':value,'keyctl_errno':ctypes.get_errno()}))
'''
    try:
        proc = panel_invoker.launch_owned(
            ["/usr/bin/python3", "-I", "-S", "-c", probe], role="PROVIDER_ADMIN",
            profile=panel_invoker.SeatProfile(env={"PATH": "/usr/bin:/bin"}), cwd=tmp_path,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate()
    except sandbox_egress.EgressUnavailable:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            raise
        pytest.skip("kernel seat-owner support unavailable")
    assert proc.returncode == 0, stderr.decode(errors="replace")
    facts = json.loads(stdout)
    assert facts["uid"] == os.getuid()
    assert facts["pid_namespace"] != os.stat("/proc/self/ns/pid").st_ino
    assert facts["bounding"] == "0000000000000000"
    assert facts["no_new_privs"] == "1"
    assert facts["keyctl_result"] == -1 and facts["keyctl_errno"] == 1


def test_provider_install_writes_stay_in_the_private_home(tmp_path):
    install = tmp_path / 'operator-bin'
    install.mkdir()
    provider = install / 'provider-entry'
    marker = install / '.new-image'
    source = '''#!/usr/bin/python3
import json,os,pathlib,sys
entry=pathlib.Path(sys.argv[0])
try:
 entry.write_text('replacement image')
 replaced=True
except OSError:
 replaced=False
private=pathlib.Path.home()/'.local/bin'
private.mkdir(parents=True,exist_ok=True)
(private/'agy').write_text('private image')
print(json.dumps({'entry_replaced':replaced,'private_install':(private/'agy').read_text(),
                 'operator_install_visible':pathlib.Path(sys.argv[1]).exists()}))
'''
    provider.write_text(source)
    provider.chmod(0o700)
    marker.write_text('operator install marker')
    try:
        with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
            try:
                result = panel_invoker._run_leg_with_liveness(
                    [str(provider), str(marker)], cwd=tmp_path,
                    env={'PATH': '/usr/bin:/bin'}, deadline_s=30,
                )
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    except sandbox_egress.EgressUnavailable:
        if os.environ.get('PHASE_LOOP_REQUIRE_SEAT_OWNER') == '1':
            raise
        pytest.skip('kernel seat-owner support unavailable')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        'entry_replaced': False, 'private_install': 'private image', 'operator_install_visible': False,
    }
    assert provider.read_text() == source
    assert marker.read_text() == 'operator install marker'
    assert set(install.iterdir()) == {provider, marker}


def test_terminal_owner_sets_the_provider_foreground_group(tmp_path):
    import pty
    import select
    master, slave = pty.openpty()
    source = '''
import json,os
try:
 foreground=os.tcgetpgrp(0)==os.getpgrp()
except OSError:
 foreground=False
print(json.dumps({'foreground':foreground}),flush=True)
'''
    try:
        process = panel_invoker.launch_owned(
            ['/usr/bin/python3', '-I', '-S', '-c', source], role='PROVIDER_ADMIN',
            profile=panel_invoker.SeatProfile(env={'PATH': '/usr/bin:/bin'},
                                             pass_fds=(slave,), terminal_fd=slave),
            cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.close(slave)
        slave = None
        process.wait(timeout=10)
        assert process.returncode == 0
        assert select.select([master], [], [], 2)[0]
        assert json.loads(os.read(master, 8192)) == {'foreground': True}
    finally:
        if slave is not None:
            os.close(slave)
        os.close(master)


def test_owner_binds_the_single_broker_socket_and_hides_its_neighbors(tmp_path):
    import socket
    import threading
    import secrets

    parent = tmp_path / 'broker'
    parent.mkdir()
    endpoint = parent / 'endpoint.sock'
    neighbor = parent / 'operator-state'
    neighbor.write_text('undeclared input')
    nonce = secrets.token_hex(16).encode()
    source = '''
import json,pathlib,socket,sys
with socket.socket(socket.AF_UNIX) as client:
 client.connect(sys.argv[1]);nonce=client.recv(128).decode()
print(json.dumps({'nonce':nonce,'neighbor':pathlib.Path(sys.argv[2]).exists(),
 'socket_mounts':[line.split()[4] for line in open('/proc/self/mountinfo')
                  if line.split()[4].endswith('.sock')]}))
'''
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(endpoint))
        listener.listen(1)
        listener.settimeout(10)
        errors = []

        def serve():
            try:
                with listener.accept()[0] as client:
                    client.sendall(nonce)
            except OSError as exc:
                errors.append(type(exc).__name__)

        server = threading.Thread(target=serve)
        server.start()
        try:
            process = panel_invoker.launch_owned(
                ['/usr/bin/python3', '-I', '-S', '-c', source, str(endpoint), str(neighbor)],
                role='PROVIDER_ADMIN',
                profile=panel_invoker.SeatProfile(env={'PATH': '/usr/bin:/bin'},
                                                 broker_socket=endpoint),
                cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr.decode()
        finally:
            server.join(timeout=11)
        assert not server.is_alive() and not errors
    assert json.loads(stdout) == {
        'nonce': nonce.decode(), 'neighbor': False, 'socket_mounts': [str(endpoint)],
    }


def test_owner_provider_has_a_fixed_ancestry_and_no_cgroup_mount(tmp_path):
    import select
    import secrets

    marker = secrets.token_hex(16)
    source = '''
import json,os,sys
print(json.dumps({'pid':os.getpid(),'ppid':os.getppid(),
 'cgroup_mount':any(line.split()[-3] in ('cgroup','cgroup2')
                    for line in open('/proc/self/mountinfo'))}),flush=True)
sys.stdin.buffer.read(1)
'''
    process = panel_invoker.launch_owned(
        ['/usr/bin/python3', '-I', '-S', '-c', source, marker], role='PROVIDER_ADMIN',
        profile=panel_invoker.SeatProfile(env={'PATH': '/usr/bin:/bin'}), cwd=tmp_path,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        assert select.select([process.stdout], [], [], 10)[0]
        facts = json.loads(process.stdout.readline())
        assert facts == {'pid': 2, 'ppid': 1, 'cgroup_mount': False}
        pending, descendants = [process.pid], []
        while pending:
            parent = pending.pop()
            children = Path(f'/proc/{parent}/task/{parent}/children').read_text().split()
            for child in children:
                pending.append(int(child))
                descendants.append(int(child))
        providers = [pid for pid in descendants
                     if Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[0] == b'/usr/bin/python3'
                     and marker.encode() in Path(f'/proc/{pid}/cmdline').read_bytes()]
        assert len(providers) == 1
        chain, parent = [], providers[0]
        while parent != process.pid:
            chain.append(parent)
            status = Path(f'/proc/{parent}/status').read_text().splitlines()
            parent = int(next(line.split()[1] for line in status if line.startswith('PPid:')))
            assert parent > 1
        assert len(chain) == 2
        process.communicate(b'x', timeout=10)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
