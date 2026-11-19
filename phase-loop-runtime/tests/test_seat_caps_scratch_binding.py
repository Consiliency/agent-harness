"""The CI scratch device binding, checked from inside a test session (agent-harness#1993).

The strict conformance suite runs under this directory's conftest, whose host isolation
(``_isolate_host_state``) replaces ``PHASE_LOOP_SANDBOX_STAGING_DIR`` and redirects the
per-user cache dir below pytest's ``tmp_path``. A readiness check made by a plain process
therefore says nothing about the paths the suite itself resolves: those follow pytest's
temporary root, ``tempfile.gettempdir()``. On a runner whose ``/tmp`` cannot carry
``io.max``, the suite fails with ``seat_resource_caps_unavailable`` although a plain
readiness report passes.

``publish-pypi.yml`` and ``seat-caps-gate.yml`` run this module inside the user manager,
with the gate's own scratch environment, and set ``CI_SCRATCH_DEVICE`` to the provisioned
device's MAJ:MIN. The test then requires readiness and both automatic paths, as this
session resolves them, to be on that device. Without the variable it skips.

``CI_SCRATCH_STUB_ROOT`` is for ``tests/test_seat_caps_host_script.py`` only: it stands in
for the device (paths below the root are the device, anything else is a block device
that cannot carry ``io.max``), so the binding can be exercised without a loop device.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pytest

from phase_loop_runtime import sandbox_policy
from phase_loop_runtime import seat_resource_caps as caps


# Read at import, before any fixture changes the environment.
EXPECTED = os.environ.get("CI_SCRATCH_DEVICE", "")
STUB_ROOT = os.environ.get("CI_SCRATCH_STUB_ROOT", "")

pytestmark = [
    pytest.mark.real_seat_caps,
    pytest.mark.skipif(not EXPECTED, reason="runs only in the CI gate, which sets CI_SCRATCH_DEVICE"),
]


def _install_stub(monkeypatch) -> None:
    root = os.path.realpath(STUB_ROOT)
    device = tuple(int(part) for part in EXPECTED.split(":"))
    other = (252, 0)

    def dev_number(path):
        real = os.path.realpath(path)
        return device if real == root or real.startswith(root + os.sep) else other

    def whole_device(found, seen=frozenset()):
        if found == other:
            caps._refuse("device-mapper node does not have one slave")
        return found

    monkeypatch.setattr(caps, "_dev_number", dev_number)
    monkeypatch.setattr(caps, "_whole_device", whole_device)
    monkeypatch.setattr(caps, "load_caps", lambda: caps.DEFAULT_CAPS)


def _majmin(path: Path) -> str:
    if STUB_ROOT:
        return "%d:%d" % caps._dev_number(path)
    info = os.stat(path)
    return f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"


def test_the_test_session_scratch_is_on_the_provisioned_device(monkeypatch, tmp_path):
    if STUB_ROOT:
        _install_stub(monkeypatch)
    staging = Path(sandbox_policy.staging_root())
    child = sandbox_policy._child_tmp_dir()
    observed = {
        "tempdir": (tempfile.gettempdir(), _majmin(Path(tempfile.gettempdir()))),
        "tmp_path": (str(tmp_path), _majmin(tmp_path)),
        "staging_root": (str(staging), _majmin(staging)),
        "child_scratch": (str(child.path), _majmin(child.path)),
    }
    off_device = {name: value for name, value in observed.items() if value[1] != EXPECTED}
    assert not off_device, f"not on the provisioned device {EXPECTED}: {off_device}"
    assert not child.degraded, f"child scratch is the degraded fallback: {child.reason}"
    assert caps.io_devices(caps.load_caps()) == (EXPECTED,)
    if not STUB_ROOT:
        assert caps.readiness_code() is None
