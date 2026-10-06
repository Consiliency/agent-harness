# ruff: noqa: F401, F811
# agent-harness#1147 round 7: the HMAC stamp this body forges was removed for an
# identity-bound decision, so `sandbox_policy._stamp_mac` no longer exists. The shim below
# (test-only, outside the verbatim body) restores a forger: any value works, because a
# forged label cannot make a hand-built env the object a decision returned.
from phase_loop_runtime import sandbox_policy as _policy_for_shim  # noqa: E402

if not hasattr(_policy_for_shim, "_stamp_mac"):
    _policy_for_shim._stamp_mac = lambda decision, nonce, env: "forged"

import os
import subprocess
import sys
from pathlib import Path

import pytest

import _scratch_audit_hook as hook
from phase_loop_runtime import panel_invoker, sandbox_policy
from test_scratch_runtime_audit_1147 import runtime


@pytest.mark.parametrize("scenario", [
    "whole_env_replay", "different_route_exception", "forged_exception", "registration_veto",
])
def test_a_launch_cannot_reuse_or_mint_a_decision_without_taking_it(runtime, monkeypatch, scenario):
    if scenario == "registration_veto":
        code = """
import sys
import _scratch_audit_hook as hook
vetoed = False
def veto(event, args):
    global vetoed
    if event == "sys.addaudithook" and not vetoed:
        vetoed = True
        raise RuntimeError("veto the scratch hook only")
sys.addaudithook(veto)
try:
    hook.install()
except RuntimeError:
    sys.exit(0)
hook.enabled = True
hook.RUNTIME_ROOTS.append("<review>")
exec(compile("import subprocess; subprocess.run([sys.argv[1]], env={})",
             "<review>bad.py", "exec"))
assert hook.drain(), "installation succeeded without the actual scratch hook"
"""
        child_env = dict(os.environ, PYTHONPATH=os.pathsep.join([
            str(Path(hook.__file__).parent), str(Path(sandbox_policy.__file__).parents[1]),
        ]))
        result = subprocess.run([sys.executable, "-c", code, runtime.CLAUDE],
                                env=child_env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return
    env = {"PATH": os.environ["PATH"]}
    if scenario == "whole_env_replay":
        env = sandbox_policy.child_scratch_env(env, sandbox_policy.CHILD_SCRATCH_RELOCATE)
        hook.drain()
        runtime.with_env(dict(env))
    else:
        if scenario == "different_route_exception":
            env = sandbox_policy.child_scratch_env(env, sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP)

        def skip_decision(kwargs, decision):
            if scenario == "forged_exception":
                target = kwargs["env"]
                kind = sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP
                nonce = "0" * 16
                mac = sandbox_policy._stamp_mac(kind, nonce, target)
                target[hook.MARKER] = f"{kind}:{nonce}:{mac}"

        monkeypatch.setattr(panel_invoker, "_child_scratch_kwargs", skip_decision)
        hook.drain()
        result = panel_invoker.run_provider([runtime.CLAUDE], env=dict(env))
        assert result.returncode == 0
    found = hook.drain()
    assert found, f"undecided {scenario} launch escaped the completeness check"
