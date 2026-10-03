"""Provider entry points require the owned launch path."""

import hashlib
import subprocess

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress


def test_helper_interface_refuses_provider_name_without_launching(monkeypatch):
    monkeypatch.setattr(panel_invoker.subprocess, "Popen", lambda *a, **k: pytest.fail("provider launched"))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_launch_owner_required"):
        panel_invoker.launch_provider(["codex", "--version"])


def test_helper_interface_refuses_a_recorded_provider_image_alias(tmp_path, monkeypatch):
    alias = tmp_path / "renamed-entry"
    alias.write_bytes(b"synthetic-provider-image")
    alias.chmod(0o700)
    digest = hashlib.sha256(alias.read_bytes()).hexdigest()
    monkeypatch.setattr(panel_invoker, "_recorded_provider_hashes", lambda: frozenset({digest}))
    monkeypatch.setattr(panel_invoker.subprocess, "Popen", lambda *a, **k: pytest.fail("provider launched"))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_launch_owner_required"):
        panel_invoker.launch_provider([str(alias)])


def test_helper_interface_still_runs_a_host_helper():
    with panel_invoker.launch_provider(["/bin/echo", "helper"], stdout=subprocess.PIPE) as proc:
        assert proc.communicate()[0] == b"helper\n"
        assert proc.returncode == 0
