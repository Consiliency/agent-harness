"""The seat egress layer's readiness covers the host tools the pinned srt needs
(agent-harness#1912).

srt refuses to start without ``bwrap``, ``socat`` and ``rg`` (it looks each one up with
``which`` on the proxy's own PATH). Readiness reports a host without one as unavailable,
with the typed ``seat_egress_not_installed`` code, before srt runs and before the host CA is
created. The last test runs srt's own dependency check where the pinned srt is installed and
proves it agrees with this one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import seat_egress_proxy

_REAL_TOOL_DIRS = "/usr/bin:/bin"


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _host_without(monkeypatch, tmp_path: Path, missing: str | None) -> Path:
    """A proxy PATH of a fake node directory plus one system directory holding every srt
    host tool except ``missing``. The operator's own PATH still has the real tools: the
    check must not consult it."""
    node_dir = tmp_path / "node" / "bin"
    system = tmp_path / "system-bin"
    node_dir.mkdir(parents=True)
    system.mkdir()
    node = _executable(node_dir / "node")
    for tool in seat_egress_proxy.SRT_HOST_TOOLS:
        if tool != missing:
            _executable(system / tool)
    monkeypatch.setattr(seat_egress_proxy, "_node", lambda: str(node))
    monkeypatch.setattr(seat_egress_proxy, "_PROXY_SYSTEM_PATH", str(system))
    monkeypatch.setenv("PATH", _REAL_TOOL_DIRS)
    return node


def _install_gates_must_not_run(monkeypatch) -> None:
    def reached(*_args):
        pytest.fail("the install and CA gates ran on a host missing an srt host tool")

    monkeypatch.setattr(seat_egress_proxy, "verify_install", reached)
    monkeypatch.setattr(seat_egress_proxy, "ensure_ca", reached)


def test_socat_absent_from_the_proxy_path_is_reported_unavailable(monkeypatch, tmp_path):
    _host_without(monkeypatch, tmp_path, "socat")
    _install_gates_must_not_run(monkeypatch)
    assert seat_egress_proxy.unavailable_reason() == (
        "socat is not installed (the pinned srt needs it)")
    assert seat_egress_proxy.unavailable_code() == seat_egress_proxy.NOT_INSTALLED_CODE


@pytest.mark.parametrize("tool", seat_egress_proxy.SRT_HOST_TOOLS)
def test_each_srt_host_tool_is_required(monkeypatch, tmp_path, tool):
    _host_without(monkeypatch, tmp_path, tool)
    _install_gates_must_not_run(monkeypatch)
    assert seat_egress_proxy.unavailable_reason() == (
        f"{tool} is not installed (the pinned srt needs it)")
    assert seat_egress_proxy.unavailable_code() == seat_egress_proxy.NOT_INSTALLED_CODE


def test_a_tool_in_nodes_own_directory_counts(monkeypatch, tmp_path):
    node = _host_without(monkeypatch, tmp_path, "socat")
    _executable(node.parent / "socat")
    monkeypatch.setattr(seat_egress_proxy, "verify_install", lambda: Path("/srt.js"))
    monkeypatch.setattr(seat_egress_proxy, "ensure_ca", lambda *_a: (Path("/c"), Path("/k")))
    assert seat_egress_proxy.unavailable_reason() is None
    assert seat_egress_proxy.unavailable_code() is None


def test_a_non_executable_tool_does_not_count(monkeypatch, tmp_path):
    _host_without(monkeypatch, tmp_path, "socat")
    (tmp_path / "system-bin" / "socat").write_text("not a program\n", encoding="utf-8")
    _install_gates_must_not_run(monkeypatch)
    assert seat_egress_proxy.unavailable_code() == seat_egress_proxy.NOT_INSTALLED_CODE


def test_start_proxy_refuses_before_spawn_without_socat(monkeypatch, tmp_path):
    _host_without(monkeypatch, tmp_path, "socat")
    _install_gates_must_not_run(monkeypatch)
    monkeypatch.setattr(
        seat_egress_proxy.subprocess, "Popen",
        lambda *_a, **_k: pytest.fail("the proxy started on a host without socat"))
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable) as refused:
        with seat_egress_proxy.start_proxy(allowlist_id="gemini"):
            pass
    assert refused.value.code == seat_egress_proxy.NOT_INSTALLED_CODE
    assert str(refused.value) == "socat is not installed (the pinned srt needs it)"


# srt's own check, imported from the installed pinned package. It prints only the
# dependency result: no proxy, no network, no CA.
_SRT_DEPENDENCY_PROBE = (
    "const { SandboxManager } = await import(process.argv[1]);"
    "process.stdout.write(JSON.stringify(SandboxManager.checkDependencies()));"
)


def _srt_dependency_errors(node: str, srt_index: Path, path: str, home: Path) -> list[str]:
    env = {"PATH": path, "LANG": "C.UTF-8", "HOME": str(home)}
    done = subprocess.run(
        [node, "--input-type=module", "-e", _SRT_DEPENDENCY_PROBE, str(srt_index)],
        env=env, cwd=home, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-400:]
    return list(json.loads(done.stdout)["errors"])


def test_the_pinned_srt_agrees_on_its_host_tools(monkeypatch, tmp_path):
    """Where the pinned srt is installed: with every tool present srt's own check reports no
    error, and with any one of them absent it reports one, exactly when readiness does."""
    try:
        node = seat_egress_proxy._node()
        srt_index = seat_egress_proxy.verify_install()
    except seat_egress_proxy.EgressLayerUnavailable as exc:
        pytest.skip(f"the pinned srt is not installed here ({exc})")
    real = {tool: shutil.which(tool, path=_REAL_TOOL_DIRS)
            for tool in seat_egress_proxy.SRT_HOST_TOOLS}
    absent = sorted(tool for tool, found in real.items() if found is None)
    if absent:
        pytest.skip(f"this host lacks {', '.join(absent)}, so the full set cannot be built")
    beside_node = sorted(tool for tool in real if (Path(node).parent / tool).exists())
    if beside_node:
        pytest.skip(f"node's own directory holds {', '.join(beside_node)}")
    home = tmp_path / "home"
    home.mkdir()
    observed = {}
    for missing in (None, *seat_egress_proxy.SRT_HOST_TOOLS):
        system = tmp_path / f"without-{missing or 'nothing'}"
        system.mkdir()
        for tool, found in real.items():
            if tool != missing:
                os.symlink(found, system / tool)
        errors = _srt_dependency_errors(node, srt_index, f"{Path(node).parent}:{system}", home)
        monkeypatch.setattr(seat_egress_proxy, "_PROXY_SYSTEM_PATH", str(system))
        try:
            seat_egress_proxy._require_srt_host_tools(node)
            refused = False
        except seat_egress_proxy.EgressLayerUnavailable as exc:
            refused = exc.code == seat_egress_proxy.NOT_INSTALLED_CODE
        observed[missing] = (bool(errors), refused, errors)
    assert {missing: row[:2] for missing, row in observed.items()} == {
        missing: (missing is not None,) * 2
        for missing in (None, *seat_egress_proxy.SRT_HOST_TOOLS)
    }, observed
