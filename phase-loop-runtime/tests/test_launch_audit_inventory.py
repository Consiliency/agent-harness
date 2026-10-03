"""The launch inventory is test-only and detects unmarked provider starts."""

import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from launch_audit_hook import provider_executable


def test_provider_detection_accepts_known_names_and_content_hashes(tmp_path):
    import hashlib

    alias = tmp_path / "alias"
    alias.write_bytes(b"synthetic-provider")
    alias.chmod(0o700)
    assert provider_executable("codex")
    assert provider_executable(str(alias), hashes={hashlib.sha256(alias.read_bytes()).hexdigest()})
    assert not provider_executable("/bin/true")


@pytest.mark.skipif(os.name != "posix", reason="POSIX launch inventory")
def test_test_only_hook_rejects_an_unmarked_provider_start(tmp_path):
    provider = tmp_path / "claude"
    provider.write_text("#!/bin/sh\nexit 0\n")
    provider.chmod(0o700)
    inventory = tmp_path / "audit.jsonl"
    code = '''
import subprocess,sys
from launch_audit_hook import install
install(sys.argv[1],fail=True)
try:
 subprocess.Popen([sys.argv[2]])
except RuntimeError:
 sys.exit(0)
sys.exit(1)
'''
    done = subprocess.run(
        [sys.executable, "-c", code, str(inventory), str(provider)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent)},
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    records = [json.loads(line) for line in inventory.read_text().splitlines()]
    assert any(row["provider"] and not row["owned"] for row in records)


@pytest.mark.parametrize('event', ['os.exec', 'os.posix_spawn', 'os.system'])
def test_audit_checks_each_provider_start_event(tmp_path, event):
    provider = tmp_path / 'claude'
    provider.write_text('#!/bin/sh\nexit 0\n')
    provider.chmod(0o700)
    inventory = tmp_path / 'audit.jsonl'
    code = '''
import sys,os
from launch_audit_hook import install
install(sys.argv[1],fail=True)
try:
 if sys.argv[3]=='os.system': sys.audit('os.system',sys.argv[2])
 else: sys.audit(sys.argv[3],sys.argv[2],[sys.argv[2]],dict(os.environ))
except RuntimeError:
 sys.exit(0)
sys.exit(1)
'''
    done = subprocess.run([sys.executable, '-c', code, str(inventory), str(provider), event],
                          env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)},
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    rows = [json.loads(line) for line in inventory.read_text().splitlines()]
    assert any(row['event'] == event and row['provider'] and not row['owned'] for row in rows)


@pytest.mark.parametrize('kind', ['direct', 'owned-bind', 'owned-data', 'version', 'fixture'])
def test_suite_guard_distinguishes_installed_inference_from_fixture_calls(tmp_path, kind):
    installed = tmp_path / 'installed-image'
    installed.write_bytes(b'synthetic installed image')
    fixture = tmp_path / 'fixture-image'
    fixture.write_bytes(b'synthetic test fixture')
    code = '''
import contextvars,hashlib,os,sys,types
from launch_audit_hook import install
module=types.ModuleType('phase_loop_runtime.panel_invoker')
module._OWNED_LAUNCH=contextvars.ContextVar('owned',default=True)
sys.modules[module.__name__]=module
install(sys.argv[1],native_inference_hashes={hashlib.sha256(open(sys.argv[2],'rb').read()).hexdigest()})
kind=sys.argv[4]
argv=[sys.argv[2],'--model','fixture']
if kind=='owned-bind': argv=['/bin/true','--ro-bind',sys.argv[2],'/provider','/provider','--model','fixture']
if kind=='owned-data':
 fd=os.open(sys.argv[2],os.O_RDONLY)
 argv=['/bin/true','--ro-bind-data',str(fd),'/provider','/provider','--model','fixture']
if kind=='version': argv=[sys.argv[2],'--version']
if kind=='fixture': argv=[sys.argv[3],'--model','fixture']
blocked=False
try: sys.audit('subprocess.Popen',argv[0],argv,None,None)
except RuntimeError as exc:
 assert 'installed provider' in str(exc)
 blocked=True
assert blocked == (kind in {'direct','owned-bind','owned-data'})
'''
    done = subprocess.run(
        [sys.executable, '-c', code, str(tmp_path / 'audit.jsonl'), str(installed), str(fixture), kind],
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).parent)},
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr


def test_suite_guard_supports_a_disabled_cache_provider(tmp_path):
    env = dict(os.environ)
    env.pop('PHASE_LOOP_LAUNCH_AUDIT_PATH', None)
    env['PYTHONPATH'] = os.pathsep.join(sys.path)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
         str(Path(__file__)) + '::test_provider_detection_accepts_known_names_and_content_hashes'],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout
