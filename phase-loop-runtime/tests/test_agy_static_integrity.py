"""Non-heartbeat image admission uses the static qualified release set."""

import hashlib
import os
import sys

import pytest

from phase_loop_runtime import gemini_heartbeat


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux image-admission contract")


def test_unlisted_image_is_refused_without_running_it(tmp_path):
    from phase_loop_runtime import agy_integrity

    image = tmp_path / "agy"
    image.write_bytes(b"synthetic-image")
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        agy_integrity.check(image)


def test_qualified_image_carries_the_same_checked_bytes(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity

    if not hasattr(os, "memfd_create"):
        if os.environ.get("PHASE_LOOP_REQUIRE_SEAT_OWNER") == "1":
            pytest.fail("required seat-owner lane lacks memfd support")
        pytest.skip("interpreter lacks memfd support")
    data = b"synthetic-qualified-image"
    image = tmp_path / "agy"
    image.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES, digest, "synthetic-help-digest")
    checked = agy_integrity.check(image)
    try:
        image.write_bytes(b"changed-on-disk")
        assert checked.sha256 == digest
        assert os.pread(checked.fd, len(data), 0) == data
    finally:
        checked.close()


@pytest.mark.parametrize("supervised", [False, True])
def test_trusted_executor_refuses_an_unlisted_image_before_launch(tmp_path, supervised):
    from phase_loop_runtime import agy_integrity, launcher

    image = tmp_path / "agy"
    marker = tmp_path / "ran"
    image.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\n")
    image.chmod(0o700)
    descriptor = os.open(tmp_path / "lease", os.O_CREAT | os.O_RDWR, 0o600)

    class Lease:
        generation = "static-image-test"

        def fileno(self):
            return descriptor

    try:
        with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
            launcher.launch([str(image)], cwd=tmp_path,
                            lease_authority=Lease() if supervised else None)
        assert not marker.exists()
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("supervised", [False, True])
def test_trusted_executor_runs_the_release_qualified_absolute_image(tmp_path, monkeypatch, supervised):
    from phase_loop_runtime import launcher

    image = tmp_path / "agy"
    data = b"#!/bin/sh\nprintf 'qualified image completed\\n'\n"
    image.write_bytes(data)
    image.chmod(0o700)
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES, hashlib.sha256(data).hexdigest(), "synthetic-help")
    descriptor = os.open(tmp_path / "lease", os.O_CREAT | os.O_RDWR, 0o600)

    class Lease:
        generation = "qualified-image-test"

        def fileno(self):
            return descriptor

    try:
        result = launcher.launch([str(image)], cwd=tmp_path,
                                 lease_authority=Lease() if supervised else None)
    finally:
        os.close(descriptor)
    assert result.returncode == 0
    assert result.output.strip() == "qualified image completed"


def test_canary_runtime_refuses_an_unlisted_entry_image(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_canary_evidence, agy_integrity
    image = tmp_path / '.local/bin/agy'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'#!/bin/sh\nexit 0\n')
    image.chmod(0o700)
    monkeypatch.setattr(agy_canary_evidence, '_account_home', lambda: tmp_path)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match='agy_image_unqualified'):
        agy_canary_evidence._trusted_provider_runtime('gemini')


def test_canary_runtime_keeps_the_qualified_entry_digest(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_canary_evidence
    image = tmp_path / '.local/bin/agy'
    image.parent.mkdir(parents=True)
    data = b'#!/bin/sh\nexit 0\n'
    image.write_bytes(data)
    image.chmod(0o700)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES, digest, 'synthetic-help')
    monkeypatch.setattr(agy_canary_evidence, '_account_home', lambda: tmp_path)
    runtime = agy_canary_evidence._trusted_provider_runtime('gemini')
    assert runtime.source == image and runtime.sha256 == digest


def test_trusted_image_resolution_uses_the_frozen_search(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity
    from types import SimpleNamespace

    seen = []
    monkeypatch.setattr(agy_integrity.shutil, 'which',
                        lambda name, path: seen.append(path) or '/usr/bin/agy')
    monkeypatch.setattr(agy_integrity, 'check',
                        lambda path: SimpleNamespace(path=path, close=lambda: None))
    agy_integrity.trusted_command(['agy', 'models'], {'PATH': str(tmp_path)})
    assert seen == [agy_integrity._PROVIDER_SEARCH_PATH]


def test_trusted_image_execution_keeps_admitted_bytes(tmp_path, monkeypatch):
    from phase_loop_runtime import agy_integrity
    import subprocess

    image = tmp_path / 'agy'
    original = b'#!/bin/sh\nprintf admitted\n'
    image.write_bytes(original)
    image.chmod(0o700)
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES,
                        hashlib.sha256(original).hexdigest(), 'synthetic-help')
    with agy_integrity.admitted_command([str(image)]) as (command, descriptors):
        image.write_bytes(b'#!/bin/sh\nprintf replaced\n')
        result = subprocess.run(command, pass_fds=descriptors, capture_output=True, check=True)
        assert result.stdout == b'admitted'
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
