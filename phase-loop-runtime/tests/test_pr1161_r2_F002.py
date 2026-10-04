import os

from phase_loop_runtime import sandbox_policy
from phase_loop_runtime.convergence.adapters import (
    AdapterExecutionRequest, run_claude_adapter,
)
from phase_loop_runtime.convergence.contracts import AdmissionRequest


def test_convergence_claude_child_receives_disk_scratch(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    for name in ("TMPDIR", "CLAUDE_CODE_TMPDIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        sandbox_policy, "_mount_fstype",
        lambda p: "tmpfs" if os.path.realpath(p) == "/tmp" else "ext4",
    )
    cli = tmp_path / "claude"
    cli.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$TMPDIR" "$CLAUDE_CODE_TMPDIR" > "$1"\n'
        'printf \'{"status":"completed"}\'\n'
    )
    cli.chmod(0o700)
    observed = tmp_path / "scratch.txt"
    admission = AdmissionRequest("a", 1, "f", "d", "head==abc", "repo", "key")
    request = AdapterExecutionRequest(
        "a", admission, (str(cli), str(observed)), tmp_path, 10, "execute",
    )
    assert run_claude_adapter(request).status.value == "completed"
    assert observed.read_text().splitlines() == [str(cache / "phase-loop/tmp")] * 2
