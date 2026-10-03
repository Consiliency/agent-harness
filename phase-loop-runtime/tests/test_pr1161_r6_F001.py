import pytest

import _scratch_audit_hook as hook
from phase_loop_runtime import sandbox_policy
from test_scratch_runtime_audit_1147 import runtime


@pytest.mark.parametrize("scenario", ["inherited", "empty", "pi"])
def test_runtime_completeness_requires_a_fresh_decision(runtime, monkeypatch, tmp_path, scenario):
    if scenario == "inherited":
        inherited = sandbox_policy.child_scratch_env({}, sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP)
        monkeypatch.setenv(hook.MARKER, inherited[hook.MARKER])
    elif scenario == "empty":
        monkeypatch.setenv(hook.MARKER, "")
    else:
        monkeypatch.delenv(hook.MARKER, raising=False)
        cli = tmp_path / "pi"
        cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        cli.chmod(0o755)
        runtime.CLAUDE = str(cli)
    hook.drain()
    runtime.partial_getattr()
    assert hook.drain(), f"undecided {scenario} launch escaped the completeness check"
