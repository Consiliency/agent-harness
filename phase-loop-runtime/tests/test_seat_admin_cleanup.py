"""Administrative launch cleanup includes descendants of its owned process."""

import os
from pathlib import Path
import subprocess
import time
import uuid

import pytest

from phase_loop_runtime import panel_invoker


def _matching_processes(marker):
    matched = set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            command = (process / 'cmdline').read_bytes()
            if marker.encode() in command:
                matched.add(int(process.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return matched


@pytest.mark.skipif(os.name != 'posix', reason='POSIX owned process cleanup')
def test_admin_timeout_cleans_up_a_detached_descendant(tmp_path):
    marker = 'seat-admin-' + uuid.uuid4().hex
    source = (
        'import subprocess,sys,time\n'
        'subprocess.Popen([sys.executable,"-I","-S","-c",'
        '"import time;time.sleep(60)",' + repr(marker) + '],start_new_session=True)\n'
        'print("child started",flush=True)\n'
        'time.sleep(60)\n'
    )
    before = _matching_processes(marker)
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        panel_invoker.run_provider(['/usr/bin/python3', '-I', '-S', '-c', source],
                                   cwd=tmp_path, capture_output=True, text=True, timeout=1)
    assert b'child started' in failure.value.output
    deadline = time.monotonic() + 5
    remaining = _matching_processes(marker) - before
    while remaining and time.monotonic() < deadline:
        time.sleep(.05)
        remaining = _matching_processes(marker) - before
    assert not remaining
