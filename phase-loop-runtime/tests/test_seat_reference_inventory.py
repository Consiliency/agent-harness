"""Classified launch references remain explicit across source changes."""

from pathlib import Path
import json
import os
import subprocess

import pytest


@pytest.mark.parametrize('source,primitive', [
    ('from subprocess import Popen as start\ndef f(runner=start): pass', 'subprocess.Popen'),
    ('import subprocess as child\ndef f(): return child.run(["git"])', 'subprocess.run'),
    ('import subprocess,functools\ndef f(): return functools.partial(subprocess.run)', 'subprocess.run'),
    ('import os\ndef f(): return os.posix_spawn', 'os.posix_spawn'),
    ('import ctypes\ndef f(): return ctypes.CDLL(None)', 'ctypes.CDLL'),
])
def test_reference_inventory_covers_aliases_defaults_and_partials(source, primitive):
    from launch_audit_hook import static_references

    references = static_references(source)
    assert references[('f', primitive)] >= 1


def test_runtime_launch_references_match_the_classified_inventory():
    from collections import Counter
    import json
    from launch_audit_hook import static_references
    from phase_loop_runtime import panel_invoker

    root = Path(panel_invoker.__file__).parent
    actual = Counter()
    for source in root.rglob('*.py'):
        module = source.relative_to(root).with_suffix('').as_posix()
        for (function, primitive), count in static_references(source.read_text()).items():
            actual[(module, function, primitive)] += count
    records = json.loads((Path(__file__).parent / 'data/seat_launch_references.json').read_text())
    expected = Counter()
    for row in records:
        assert row['role'] in {'owned', 'host-helper', 'operator-out-of-scope',
                               'qualification', 'supervisor', 'contained-falsifier',
                               'helper:keyring-exec', 'host-io', 'python-worker'}
        key = (row['module'], row['function'], row['primitive'])
        assert key not in expected
        expected[key] = row['count']
    assert actual == expected


def test_review_launch_stays_owned_at_each_site(tmp_path,monkeypatch,request):
    from phase_loop_runtime import panel_invoker as pi
    from launch_audit_hook import install

    provider=tmp_path/'codex'
    provider.write_text('#!/usr/bin/python3\nimport json,os\nprint(json.dumps({"namespace":os.stat("/proc/self/ns/pid").st_ino}))\n')
    provider.chmod(0o700)
    monkeypatch.setenv('SEAT_TEST_ADDED_SITE','1')
    close_audit = install(tmp_path/'audit.jsonl',fail=True)
    request.addfinalizer(close_audit)
    process=pi.launch_owned([str(provider)],role=pi.SeatLaunchRole.PROVIDER_ADMIN,
         profile=pi.SeatProfile(env={'PATH':'/usr/bin:/bin'},readonly_paths=(provider,)),
         cwd=tmp_path,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:out,err=process.communicate(timeout=15)
    finally:pi._terminate_process_group(process)
    assert process.returncode==0,err
    assert json.loads(out)['namespace']!=os.stat('/proc/self/ns/pid').st_ino
