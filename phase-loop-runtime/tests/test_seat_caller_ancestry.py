"""Caller-driven namespace and process ancestry controls."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import pytest

from phase_loop_runtime import launcher, panel_invoker, sandbox_egress
from phase_loop_runtime.advisor_board.backing import start_context_carrying_thread


@pytest.mark.parametrize('route', ['admin', 'cli', 'tui', 'president', 'executor', 'supervised'])
def test_review_callers_have_bounded_ancestry_and_no_cgroup_mount(tmp_path, monkeypatch, route):
    nonce = uuid.uuid4().hex
    facts_path = panel_invoker._precreate_seat_output(tmp_path / 'facts.json')
    release = panel_invoker._precreate_seat_output(tmp_path / 'release')
    output = tmp_path / 'answer.txt'
    source = '''
import json,os,pathlib,sys,time
facts,release,output=map(pathlib.Path,sys.argv[1:4])
status=dict(line.split(':',1) for line in open('/proc/self/status') if ':' in line)
facts.write_text(json.dumps({'pid':os.getpid(),'ppid':os.getppid(),
 'cgroup_mount':any(line.split()[-3] in ('cgroup','cgroup2')
                    for line in open('/proc/self/mountinfo')),
 'bounding':status['CapBnd'].strip(),'no_new_privs':status['NoNewPrivs'].strip()}))
end=time.monotonic()+20
while not release.read_text():
 if time.monotonic()>end: raise RuntimeError('synthetic control was not released')
 time.sleep(.02)
text='The declared candidate has been inspected for this ownership control.\\n'
text+=('FORCING DECISION: continue' if sys.argv[4]=='president' else 'AGREE')+'\\n'
if sys.argv[4] in ('tui','president'): output.write_text(text)
else: print(text,flush=True)
'''
    command = ['/usr/bin/python3', '-I', '-S', '-c', source,
               str(facts_path), str(release), str(output), route, nonce]
    roots, results, errors = [], [], []
    original_launch = panel_invoker.launch_provider
    original_profile = panel_invoker._seat_command_profile

    def observe(command, **kwargs):
        process = original_launch(command, **kwargs)
        if nonce in command:
            roots.append(process.pid)
        return process

    @contextmanager
    def profile(command, **kwargs):
        kwargs['outputs'] = (*kwargs.get('outputs', ()), facts_path, release)
        with original_profile(command, **kwargs) as value:
            yield value

    monkeypatch.setattr(panel_invoker, 'launch_provider', observe)
    monkeypatch.setattr(panel_invoker, '_seat_command_profile', profile)

    def invoke():
        try:
            if route == 'admin':
                process = panel_invoker.launch_owned(
                    command, role='PROVIDER_ADMIN', cwd=tmp_path,
                    profile=panel_invoker.SeatProfile(env={'PATH': '/usr/bin:/bin'},
                                                     outputs=(facts_path, release)),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                results.append((process.communicate(timeout=25), process.returncode))
            elif route in ('executor', 'supervised'):
                descriptor = os.open(tmp_path / 'lease', os.O_RDWR | os.O_CREAT, 0o600)
                class Lease:
                    generation = 'ancestry-control'
                    def fileno(self):
                        return descriptor
                try:
                    results.append(launcher.launch(
                        command, action='review', cwd=tmp_path,
                        lease_authority=Lease() if route == 'supervised' else None,
                    ))
                finally:
                    os.close(descriptor)
            else:
                with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
                    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
                    try:
                        monitor = panel_invoker._ReviewMonitor(tmp_path / 'monitor.json',
                            'ancestry-control', 0, threading.Event())
                        if route == 'cli':
                            results.append(panel_invoker._run_leg_with_liveness(
                                command, cwd=tmp_path, env={'PATH': '/usr/bin:/bin'},
                                deadline_s=30, review_monitor=monitor,
                            ))
                        else:
                            results.append(panel_invoker._run_claude_tui_session(
                                command=command, cwd=tmp_path, env={'PATH': '/usr/bin:/bin'},
                                prompt='synthetic ownership control', output_file=output,
                                timeout_s=30, review_monitor=monitor,
                                mode='president' if route == 'president' else 'review',
                            ))
                    finally:
                        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
        except BaseException as exc:
            errors.append(exc)

    thread = start_context_carrying_thread(invoke, daemon=True)
    try:
        end = time.monotonic() + 20
        while not facts_path.read_text() and thread.is_alive() and time.monotonic() < end:
            time.sleep(.02)
        assert not errors, errors
        facts = json.loads(facts_path.read_text())
        assert facts == {'pid': 2, 'ppid': 1, 'cgroup_mount': False,
                         'bounding': '0000000000000000', 'no_new_privs': '1'}
        assert len(roots) == 1
        pending, providers = roots.copy(), []
        while pending:
            parent = pending.pop()
            for child in Path(f'/proc/{parent}/task/{parent}/children').read_text().split():
                pid = int(child)
                pending.append(pid)
                arguments = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                if arguments[1:5] == [arg.encode() for arg in command[1:5]]:
                    providers.append(pid)
        assert len(providers) == 1
        ancestry, parent = [], providers[0]
        while parent != roots[0]:
            ancestry.append(parent)
            status = Path(f'/proc/{parent}/status').read_text().splitlines()
            parent = int(next(line.split()[1] for line in status if line.startswith('PPid:')))
            assert parent > 1 and len(ancestry) <= 8
        assert len(ancestry) == (3 if route == 'supervised' else 2), (route, ancestry)
    finally:
        panel_invoker._write_seat_text(release, 'released')
        thread.join(timeout=30)
    assert not thread.is_alive() and not errors, errors
    result = results[0]
    if route == 'admin':
        assert result[1] == 0, result
    elif route in ('tui', 'president'):
        assert result[0] == 0, result
    else:
        assert result.returncode == 0, result
    if route == 'supervised':
        assert result.supervisor_receipt['process_tree_empty'] is True
