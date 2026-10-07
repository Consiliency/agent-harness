"""The test-only launch audit lets ONLY the opt-in live jailed-seat test run the installed
CLI (agent-harness#1282).

The audit refuses a test that selects an installed provider for inference: a fixture CLI
must stand in. The one exception is a test marked ``host_seat_credentials``, which exists to
run the real Claude CLI inside the host's jail and already sees the host's own login and jail
state. The exemption is bound to that marker: an unmarked test cannot enable it."""

from __future__ import annotations

import hashlib
import subprocess

import pytest

import launch_audit_hook


def _installed(tmp_path):
    image = tmp_path / "installed-claude"
    image.write_bytes(b"#!/bin/sh\nexit 0\n")
    image.chmod(0o700)
    return image, {hashlib.sha256(image.read_bytes()).hexdigest()}


def test_the_audit_refuses_installed_inference_in_an_unmarked_test(request, tmp_path):
    assert request.node.get_closest_marker("host_seat_credentials") is None
    image, hashes = _installed(tmp_path)
    close = launch_audit_hook.install(tmp_path / "audit.jsonl", native_inference_hashes=hashes)
    try:
        with pytest.raises(RuntimeError, match="installed provider"):
            subprocess.run([str(image), "--model", "fixture"], check=False)
        with pytest.raises(RuntimeError, match="exemption refused"):
            launch_audit_hook.allow_installed_inference(request.node)
    finally:
        close()


@pytest.mark.host_seat_credentials
def test_a_marked_live_seat_test_may_run_the_installed_cli(request, tmp_path):
    image, hashes = _installed(tmp_path)
    close = launch_audit_hook.install(tmp_path / "audit.jsonl", native_inference_hashes=hashes)
    try:
        # The conftest holds the exemption for a marked test's whole duration.
        assert launch_audit_hook._INSTALLED_ALLOWED[0] == 1
        assert subprocess.run([str(image), "--model", "fixture"], check=False).returncode == 0
        with launch_audit_hook.allow_installed_inference(request.node):
            assert subprocess.run([str(image), "--model", "fixture"], check=False).returncode == 0
    finally:
        close()
