"""Verdict logic of the CI I/O enforcement validation (agent-harness#1993).

Pure functions only: the real direct-I/O run happens on hosted runners, inside the user
manager, on the provisioned loop device. Nothing here performs I/O against a device.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from phase_loop_runtime.seat_resource_caps import DEFAULT_CAPS


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seat_caps_loop_validation.py"
MIB = 1024 * 1024


def _load():
    spec = importlib.util.spec_from_file_location("seat_caps_loop_validation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v = _load()
WBPS = DEFAULT_CAPS.io_max.wbps
RBPS = DEFAULT_CAPS.io_max.rbps


def test_dd_statistics_parse_every_transfer_in_order():
    stderr = (
        "64+0 records in\n64+0 records out\n"
        "67108864 bytes (67 MB, 64 MiB) copied, 1.2799 s, 52.4 MB/s\n"
        "512+0 records in\n512+0 records out\n"
        "536870912 bytes (537 MB, 512 MiB) copied, 10.24 s, 52.4 MB/s\n"
    )
    assert v.parse_dd(stderr) == [(67108864, 1.2799), (536870912, 10.24)]
    assert v.parse_dd("dd: error writing: No space left on device\n") == []


def test_exact_byte_counts_are_required():
    stderr = "1048576 bytes (1.0 MB, 1.0 MiB) copied, 0.5 s, 2 MB/s\n"
    assert v._exact(stderr, [1048576], "x") == 0.5
    with pytest.raises(v.ValidationError):
        v._exact(stderr, [2 * 1048576], "x")
    with pytest.raises(v.ValidationError):
        v._exact(stderr, [1048576, 1048576], "x")


def test_throughput_refuses_a_non_positive_interval():
    with pytest.raises(v.ValidationError):
        v.throughput(1, 0.0)


@pytest.mark.parametrize("ratio, bound", [(1.0, True), (1.25, True), (1.2501, False), (3.0, False)])
def test_capped_bound_tolerance(ratio, bound):
    size = 512 * MIB
    seconds = size / (WBPS * ratio)
    verdict = v.capped_verdict(label="write", measured_bytes=size, seconds=seconds, cap_bps=WBPS,
                               accounted_delta=size)
    assert verdict["bound"] is bound and verdict["pass"] is bound


@pytest.mark.parametrize("fraction, accounted", [(1.0, True), (0.9, True), (0.89, False), (0.0, False)])
def test_capped_accounting_delta_floor(fraction, accounted):
    size = 512 * MIB
    verdict = v.capped_verdict(label="read", measured_bytes=size, seconds=size / RBPS, cap_bps=RBPS,
                               accounted_delta=math.ceil(size * fraction))
    assert verdict["accounted"] is accounted and verdict["pass"] is accounted


@pytest.mark.parametrize("write, read, conclusive", [
    (2 * WBPS, 2 * RBPS, True),
    (2 * WBPS - 1, 10 * RBPS, False),
    (10 * WBPS, 2 * RBPS - 1, False),
])
def test_control_must_be_twice_the_cap(write, read, conclusive):
    assert v.control_verdict(write, read, wbps=WBPS, rbps=RBPS)["conclusive"] is conclusive


def _capped(passing=True):
    return {"pass": passing}


def test_overall_verdict():
    good = v.control_verdict(10 * WBPS, 10 * RBPS, wbps=WBPS, rbps=RBPS)
    slow = v.control_verdict(WBPS, RBPS, wbps=WBPS, rbps=RBPS)
    assert v.overall(good, [_capped(), _capped()], True) == "pass"
    assert v.overall(slow, [_capped(), _capped()], True) == "inconclusive"
    assert v.overall(None, [], None) == "inconclusive"
    assert v.overall(good, [_capped(), _capped(False)], True) == "fail"
    assert v.overall(good, [_capped(), _capped()], False) == "fail"
    assert v.overall(good, [_capped()], True) == "fail"
    assert v.overall(good, [_capped(), _capped()], None) == "fail"


def test_io_stat_and_io_max_rows():
    stat = "7:3 rbytes=100 wbytes=200 rios=1 wios=2 dbytes=0 dios=0\n8:0 rbytes=5 wbytes=6\n"
    assert v.parse_io_stat(stat, "7:3")["wbytes"] == 200
    assert v.parse_io_stat(stat, "7:9") == {}
    io_max = "7:3 rbps=104857600 wbps=52428800 riops=2000 wiops=1000\n"
    assert v.parse_io_max(io_max, "7:3") == v.expected_io_max(DEFAULT_CAPS.io_max)
    assert v.parse_io_max(io_max, "8:0") is None


def test_deadline_bounds_every_child(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(v.time, "monotonic", lambda: clock["now"])
    deadline = v.Deadline(30, 120)
    assert deadline.child() == 30
    clock["now"] = 129.5
    with pytest.raises(v.ValidationError):
        deadline.child()


def test_a_timed_out_child_is_terminated_and_reaped():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               start_new_session=True)
    with pytest.raises(v.ValidationError, match="exceeded"):
        v._finish(process, 0.2, "sleeper")
    assert process.returncode is not None


def test_a_failed_child_is_not_evidence():
    process = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               start_new_session=True)
    with pytest.raises(v.ValidationError, match="exited 3"):
        v._finish(process, 30, "failing child")


def test_evidence_is_written_on_failure(monkeypatch, tmp_path):
    def broken(_args, result):
        result["kernel"] = "test"
        raise v.ValidationError("no device")

    monkeypatch.setattr(v, "validate", broken)
    assert v.main(["--majmin", "7:3", "--out", str(tmp_path)]) == 1
    written = json.loads((tmp_path / "enforcement.json").read_text())
    assert written["verdict"] == "fail" and written["error"]["reason"] == "no device"
    assert written["kernel"] == "test"
    assert written["protocol"]["tolerance"] == 1.25
    assert (tmp_path / "enforcement.json").stat().st_mode & 0o777 == 0o600
