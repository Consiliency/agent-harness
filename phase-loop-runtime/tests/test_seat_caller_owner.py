"""Production review callers run inside the unified owner."""

import json
import os
import sys
import threading
import socket
import uuid
from contextlib import ExitStack

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned review callers")


@pytest.mark.parametrize("heartbeat", [False, True])
def test_cli_review_caller_owns_the_process_and_view(tmp_path, heartbeat):
    canary = tmp_path / "host-input.txt"
    canary.write_text("host-only input")
    code = """
import ctypes,json,os,platform,sys
with open('/proc/self/status') as source:
 status=dict(line.split(':',1) for line in source if ':' in line)
libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
number={'x86_64':250,'aarch64':219}[platform.machine()]
value=libc.syscall(number,0,-3,0)
print(json.dumps({'namespace':os.stat('/proc/self/ns/pid').st_ino,
 'bounding':status['CapBnd'].strip(),'no_new_privs':status['NoNewPrivs'].strip(),
 'canary_visible':os.path.exists(sys.argv[1]),'ambient':os.getenv('SYNTHETIC_OPERATOR_VALUE'),
 'parent_proc_visible':os.path.exists('/proc/'+sys.argv[2]+'/status'),
 'root_readonly':any(line.split()[4]=='/' and 'ro' in line.split()[5].split(',')
                     for line in open('/proc/self/mountinfo')),
 'key_result':value,'key_errno':ctypes.get_errno()}))
"""
    monitor = panel_invoker._ReviewMonitor(tmp_path / "monitor.json", "caller-test", 0,
                                           threading.Event()) if heartbeat else None
    try:
        with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
            try:
                result = panel_invoker._run_leg_with_liveness(
                    ["/usr/bin/python3", "-I", "-S", "-c", code, str(canary), str(os.getpid())], cwd=tmp_path,
                    env={"PATH": "/usr/bin:/bin", "SYNTHETIC_OPERATOR_VALUE": "host-only-value"},
                    deadline_s=30, review_monitor=monitor,
                )
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    except sandbox_egress.EgressUnavailable:
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            raise
        pytest.skip("kernel seat-owner support unavailable")
    assert result.returncode == 0, result.stderr
    facts = json.loads(result.stdout)
    assert facts["namespace"] != os.stat("/proc/self/ns/pid").st_ino
    assert facts["bounding"] == "0000000000000000"
    assert facts["no_new_privs"] == "1"
    assert facts["canary_visible"] is False
    assert facts['parent_proc_visible'] is False
    assert facts['root_readonly'] is True
    assert facts["ambient"] is None
    assert facts["key_result"] == -1 and facts["key_errno"] == 1


@pytest.mark.parametrize('heartbeat', [False, True])
def test_review_caller_uses_the_holder_and_cannot_open_parent_listeners(tmp_path, heartbeat):
    with ExitStack() as stack:
        listeners = {}
        for family, address in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
            listener = stack.enter_context(socket.socket(family))
            if family == socket.AF_INET6:
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind((address, 0))
            listener.listen(32)
            listeners[family] = listener.getsockname()[1]
        abstract_names = ['\0seat-bus-' + uuid.uuid4().hex,
                          '\0/tmp/.X11-unix/seat-' + uuid.uuid4().hex]
        for name in abstract_names:
            listener = stack.enter_context(socket.socket(socket.AF_UNIX))
            listener.bind(name)
            listener.listen(8)
        # Positive controls establish that the fixtures actually listen on the host.
        for host, family in (('127.0.0.1', socket.AF_INET), ('::1', socket.AF_INET6)):
            with socket.create_connection((host, listeners[family]), timeout=1):
                pass
        for name in abstract_names:
            with socket.socket(socket.AF_UNIX) as client:
                client.connect(name)
        import ipaddress
        targets = [(host, listeners[socket.AF_INET if ipaddress.ip_address(host).version == 4
                                    else socket.AF_INET6])
                   for host in sandbox_egress.host_addresses()]
        assert any(host == '127.0.0.1' for host, _ in targets)
        source = '''
import json,os,socket,sys
targets=json.loads(sys.argv[1]);names=json.loads(sys.argv[2]);opened=[]
for host,port in targets:
 try:
  client=socket.create_connection((host,port),timeout=.3);client.close();opened.append('tcp')
 except OSError: pass
for name in names:
 with socket.socket(socket.AF_UNIX) as client:
  client.settimeout(.3)
  try: client.connect(name);opened.append('abstract')
  except OSError: pass
print(json.dumps({'opened':opened,'network':os.stat('/proc/self/ns/net').st_ino}))
'''
        monitor = panel_invoker._ReviewMonitor(tmp_path / 'monitor.json', 'network-control', 0,
                                               threading.Event()) if heartbeat else None
        with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
            try:
                holder_namespace = panel_invoker._filtered_holder_namespace()
                result = panel_invoker._run_leg_with_liveness(
                    ['/usr/bin/python3', '-I', '-S', '-c', source,
                     json.dumps(targets), json.dumps(abstract_names)],
                    cwd=tmp_path, env={'PATH': '/usr/bin:/bin'}, deadline_s=30,
                    review_monitor=monitor,
                )
            finally:
                panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        assert result.returncode == 0, result.stderr
        facts = json.loads(result.stdout)
        assert facts['opened'] == []
        assert facts['network'] == holder_namespace
        assert holder_namespace != os.stat('/proc/self/ns/net').st_ino


def test_review_repository_metadata_stays_readonly(tmp_path, owned_review_network):
    pi = panel_invoker
    stage=tmp_path/'context'; (stage/'.git').mkdir(parents=True)
    config=stage/'.git/config'; config.write_text('[core]\n')
    source='''import json,sys
opened=False
try:
 with open(sys.argv[1],'a') as stream:stream.write('changed');opened=True
except OSError:pass
print(json.dumps({'writable':opened}))
'''
    argv=['/usr/bin/python3','-I','-S','-c',source,str(config)]
    prefix = pi._EGRESS_LAUNCH_PREFIX.get()
    with ExitStack():
        token=pi._EGRESS_LAUNCH_PREFIX.set(prefix)
        try:
            with pi._seat_command_profile(argv,env={'PATH':'/usr/bin:/bin'},cwd=tmp_path,readonly_paths=(stage,)) as (command,profile):
                import subprocess
                process=pi.launch_owned(command,role=pi.SeatLaunchRole.PROVIDER_REVIEW,profile=profile,cwd=tmp_path,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
                try: out,err=process.communicate(timeout=15)
                finally: pi._terminate_process_group(process)
            assert process.returncode==0,err
            assert json.loads(out)=={'writable':False}
        finally: pi._EGRESS_LAUNCH_PREFIX.reset(token)
    assert config.read_text()=='[core]\n'
