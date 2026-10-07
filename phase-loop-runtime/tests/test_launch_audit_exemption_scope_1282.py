"""agent-harness#1282 final check, codex F001 falsifier (verbatim): an unmarked test cannot
enable the installed-inference exemption."""

import hashlib
import subprocess

import pytest

import launch_audit_hook


def test_unmarked_test_cannot_exempt_installed_inference(request, tmp_path):
    assert request.node.get_closest_marker("host_seat_credentials") is None
    assert launch_audit_hook._INSTALLED_ALLOWED[0] == 0
    image = tmp_path / "installed-image"
    image.write_bytes(b"#!/bin/sh\nexit 0\n")
    image.chmod(0o700)
    close = launch_audit_hook.install(
        tmp_path / "audit.jsonl",
        native_inference_hashes={hashlib.sha256(image.read_bytes()).hexdigest()},
    )
    try:
        with pytest.raises(RuntimeError):
            with launch_audit_hook.allow_installed_inference():
                subprocess.run([str(image), "--model", "fixture"], check=True)
    finally:
        close()
