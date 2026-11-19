"""The per-check readiness report and its assert mode (agent-harness#1993).

The report must attribute a failure to the one check that failed, in readiness_code()'s
order, agree with readiness_code() itself, and never turn a caps-record failure into a
defaults retry. Assert mode must fail on a device mismatch and on a degraded child scratch.
Facts are faked through the same module seams the caps tests use.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from phase_loop_runtime import sandbox_policy, seat_jail
from phase_loop_runtime import seat_resource_caps as caps


pytestmark = pytest.mark.real_seat_caps
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seat_caps_readiness_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("seat_caps_readiness_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_mod = _load()


@pytest.fixture
def host(monkeypatch, tmp_path):
    """A fully ready fake host; each test breaks exactly one fact."""
    state = tmp_path / "state"
    (state / "phase-loop").mkdir(parents=True, mode=0o700)
    state.chmod(0o700)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       33554432 kB\n")
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu io memory pids")
    manager = root / "user.slice" / f"user-{os.getuid()}.slice" / f"user@{os.getuid()}.service"
    manager.mkdir(parents=True)
    (manager / "cgroup.controllers").write_text("cpu io memory pids")
    (manager / "cgroup.subtree_control").write_text("cpu io memory pids")
    runtime = tmp_path / "run"
    runtime.mkdir()
    (runtime / "bus").touch()
    cache = tmp_path / "cache"
    staging = tmp_path / "staging"
    scratch = tmp_path / "scratch"
    staging.mkdir()
    scratch.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_STAGING_DIR", raising=False)
    monkeypatch.setattr(seat_jail, "state_home", lambda: state)
    monkeypatch.setattr(caps, "MANAGED_RECORD", tmp_path / "managed-missing.json")
    monkeypatch.setattr(caps, "_PROC_MEMINFO", meminfo)
    monkeypatch.setattr(caps, "_CGROUP_ROOT", root)
    monkeypatch.setattr(caps, "_systemd_run_ready", lambda: True)
    monkeypatch.setattr(caps, "_automatic_paths", lambda: (staging, scratch))
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (8, 0))
    monkeypatch.setattr(caps, "_whole_device", lambda device, seen=frozenset(): device)
    return {"root": root, "manager": manager, "runtime": runtime, "state": state,
            "tmp": tmp_path}


def _by_check(records):
    return {record["check"]: record for record in records}


def _statuses(records):
    return [_by_check(records)[name]["status"] for name in report_mod.CHECKS]


def test_ready_host_passes_every_check_and_agrees_with_readiness_code(host):
    records = report_mod.report("t")
    assert _statuses(records) == ["pass"] * 6
    verdict = _by_check(records)["verdict"]
    assert verdict == {"check": "verdict", "verdict": None, "first_failing": None,
                       "attribution": "consistent"}
    assert _by_check(records)["device_plan"]["io_devices"] == ["8:0"]


def _break_cgroup_v2(monkeypatch, host):
    (host["root"] / "cgroup.controllers").unlink()


def _break_manager(monkeypatch, host):
    (host["manager"] / "cgroup.controllers").write_text("cpu memory pids")


def _break_systemd_run(monkeypatch, host):
    monkeypatch.setattr(caps, "_systemd_run_ready", lambda: False)


def _break_bus(monkeypatch, host):
    (host["runtime"] / "bus").unlink()


def _break_record(monkeypatch, host):
    record = host["state"] / "phase-loop" / "seat-resource-caps.json"
    record.write_text("{not json")
    record.chmod(0o600)


def _break_device(monkeypatch, host):
    monkeypatch.setattr(caps, "_dev_number", lambda _path: (0, 52))
    monkeypatch.setattr(caps, "_tmpfs_carveout", lambda *_: False)


@pytest.mark.parametrize("breaker, failing", [
    (_break_cgroup_v2, "cgroup_v2"),
    (_break_manager, "manager_controllers"),
    (_break_systemd_run, "systemd_run"),
    (_break_bus, "runtime_bus"),
    (_break_record, "caps_record"),
    (_break_device, "device_plan"),
])
def test_one_injected_failure_is_attributed_to_its_own_check(monkeypatch, host, breaker, failing):
    breaker(monkeypatch, host)
    records = report_mod.report("t")
    index = report_mod.CHECKS.index(failing)
    statuses = _statuses(records)
    assert statuses[:index] == ["pass"] * index
    assert statuses[index] == "fail"
    assert all(status == "not_reached" for status in statuses[index + 1:])
    verdict = _by_check(records)["verdict"]
    assert verdict["verdict"] == caps.readiness_code() == caps.CODE
    assert verdict["first_failing"] == failing
    assert verdict["attribution"] == "consistent"


def test_missing_controllers_are_named(host):
    (host["manager"] / "cgroup.controllers").write_text("cpu memory")
    record = _by_check(report_mod.report("t"))["manager_controllers"]
    assert record["missing"] == ["io", "pids"]


@pytest.mark.parametrize("content, mode, reason", [
    ("{not json", 0o600, "caps record is malformed"),
    (json.dumps({"schema": caps.SCHEMA, "surprise": 1}), 0o600, "caps record shape is invalid"),
    (json.dumps({"pids_max": 512}), 0o622, "caps record is unsafe"),
])
def test_record_failure_is_reported_as_such_without_a_defaults_retry(monkeypatch, host, content,
                                                                     mode, reason):
    record = host["state"] / "phase-loop" / "seat-resource-caps.json"
    record.write_text(content)
    record.chmod(mode)
    calls = []
    real_decode = caps._decode_record

    def decode(raw):
        calls.append(raw)
        return real_decode(raw)

    monkeypatch.setattr(caps, "_decode_record", decode)
    records = _by_check(report_mod.report("t"))
    caps_record = records["caps_record"]
    assert caps_record["status"] == "fail"
    assert caps_record["source"] == "operator" and caps_record["present"] is True
    assert caps_record["failure"]["reason"] == reason
    assert "effective" not in caps_record and "default_bounds" not in caps_record
    # The record's bytes are the only thing ever decoded: no defaults document follows.
    assert all(raw == content.encode() for raw in calls)
    device_plan = records["device_plan"]
    assert device_plan["status"] == "not_reached" and device_plan["informational"] is True
    assert "io_devices" not in device_plan


def test_a_default_host_bound_failure_shows_the_bounds(monkeypatch, host):
    monkeypatch.setattr(report_mod.os, "cpu_count", lambda: 1)
    monkeypatch.setattr(caps.os, "cpu_count", lambda: 1)
    record = _by_check(report_mod.report("t"))["caps_record"]
    assert record["status"] == "fail" and record["source"] == "defaults"
    assert record["default_bounds"] == {"cpu_max_percent": 200, "cpu_max_percent_limit": 100,
                                        "memory_max_bytes": caps.DEFAULT_CAPS.memory_max_bytes}
    assert record["failure"]["reason"] == "caps record value is outside its bound"


def test_child_scratch_candidate_refusals_are_recorded(monkeypatch, host):
    monkeypatch.setattr(sandbox_policy, "is_ram_backed",
                        lambda path: str(path).startswith(str(host["tmp"] / "cache")))
    monkeypatch.setattr(sandbox_policy, "legacy_staging_root", lambda: host["tmp"] / "shared")
    (host["tmp"] / "shared").mkdir(mode=0o700)
    monkeypatch.setattr(sandbox_policy, "_free_bytes", lambda _p: 10)
    monkeypatch.setattr(sandbox_policy, "effective_floor_bytes", lambda _p: 100)
    record = _by_check(report_mod.report("t"))["device_plan"]
    rows = record["child_scratch"]["candidates"]
    assert [row["refusal"] for row in rows] == ["is_ram_backed", "free < effective_floor_bytes"]
    assert rows[1]["free_bytes"] == 10 and rows[1]["effective_floor_bytes"] == 100
    assert record["child_scratch"]["chosen"]["degraded"] is True
    assert "candidate_replay_mismatch" not in record["child_scratch"]
    staging = record["staging"]["candidates"]
    assert staging[0]["refusal"] == "is_ram_backed"


def test_report_mode_exits_zero_even_when_everything_fails(monkeypatch, host, tmp_path):
    def boom(*_args, **_kwargs):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(caps, "_manager_cgroup", boom)
    monkeypatch.setattr(caps, "readiness_code", boom)
    out = tmp_path / "evidence" / "r.jsonl"
    assert report_mod.main(["--label", "x", "--out", str(out)]) == 0
    records = [json.loads(line) for line in out.read_text().splitlines()]
    by = _by_check(records)
    assert by["manager_controllers"]["status"] == "fail"
    assert by["manager_controllers"]["failure"]["type"] == "RuntimeError"
    assert by["verdict"]["verdict_error"]["reason"] == "unreadable"
    assert out.stat().st_mode & 0o777 == 0o600


def test_report_mode_survives_a_crash_of_the_report_itself(monkeypatch, capsys):
    monkeypatch.setattr(report_mod, "report", lambda _label: 1 / 0)
    assert report_mod.main(["--label", "x"]) == 0
    assert "ZeroDivisionError" in capsys.readouterr().out


@pytest.fixture
def device_host(monkeypatch, host, tmp_path):
    staging = tmp_path / "dev-staging"
    child = tmp_path / "dev-child"
    staging.mkdir()
    child.mkdir()
    devices = {str(staging): (7, 3), str(child): (7, 3)}
    monkeypatch.setattr(sandbox_policy, "staging_root", lambda: staging)
    location = {"value": sandbox_policy.ScratchLocation(child, False)}
    monkeypatch.setattr(sandbox_policy, "_child_tmp_dir", lambda: location["value"])
    monkeypatch.setattr(caps, "_dev_number", lambda path: devices[str(path)])
    monkeypatch.setattr(caps, "_automatic_paths", lambda: (staging, child))
    temp_root = tmp_path / "dev-tmp"
    temp_root.mkdir()
    devices[str(temp_root)] = (7, 3)
    monkeypatch.setattr(report_mod, "_temp_root", lambda: str(temp_root))
    monkeypatch.setattr(report_mod, "_majmin", lambda path: "%d:%d" % devices[str(path)])
    return devices, staging, child, location


def test_assert_mode_passes_on_the_expected_device(device_host, tmp_path):
    out = tmp_path / "a.jsonl"
    assert report_mod.main(["--expect-device", "7:3", "--out", str(out)]) == 0
    verdict = [json.loads(line) for line in out.read_text().splitlines()][-1]
    assert verdict == {"check": "assert_verdict", "expected_device": "7:3", "passed": True}


def test_assert_mode_fails_on_a_device_mismatch(device_host):
    devices, staging, _child, _location = device_host
    devices[str(staging)] = (8, 1)
    assert report_mod.main(["--expect-device", "7:3"]) == 1


def test_assert_mode_fails_on_a_degraded_child_scratch(device_host, capsys):
    _devices, _staging, child, location = device_host
    location["value"] = sandbox_policy.ScratchLocation(child, True, "no private disk-backed dir")
    assert report_mod.main(["--expect-device", "7:3"]) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    failed = [row["name"] for row in rows if row.get("check") == "assert" and not row["ok"]]
    assert failed == ["child scratch not degraded"]


def test_assert_mode_fails_when_readiness_fails(device_host, host):
    (host["runtime"] / "bus").unlink()
    assert report_mod.main(["--expect-device", "7:3"]) == 1


def test_summary_names_the_first_failing_check(tmp_path, capsys):
    (tmp_path / "baseline.jsonl").write_text("\n".join(json.dumps(r) for r in (
        {"check": "host", "sys_vendor": "Vendor", "kernel": "6.8", "in_user_manager": True},
        {"check": "verdict", "verdict": caps.CODE, "first_failing": "device_plan"},
    )) + "\n")
    (tmp_path / "enforcement.json").write_text(json.dumps({"verdict": "pass"}))
    assert report_mod.main(["--summarize", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "| baseline | user manager | Vendor | 6.8 | device_plan | seat_resource_caps_unavailable |" in out
    assert "Enforcement validation: **pass**" in out


def test_the_context_is_read_from_the_cgroup_not_the_environment(monkeypatch, tmp_path):
    cgroup = tmp_path / "cgroup"
    monkeypatch.setattr(report_mod, "_PROC_SELF_CGROUP", cgroup)
    monkeypatch.setenv("INVOCATION_ID", "set-by-any-service")
    cgroup.write_text("0::/system.slice/runner.service\n")
    assert report_mod.host_facts("h")["in_user_manager"] is False
    cgroup.write_text(f"0::/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/"
                      "app.slice/ci-seat-caps-run-1-2.service\n")
    assert report_mod.host_facts("b")["in_user_manager"] is True


def _summary_row(tmp_path, capsys, name, records, raw=None):
    directory = tmp_path / name
    directory.mkdir()
    text = raw if raw is not None else "".join(json.dumps(r) + "\n" for r in records)
    (directory / "baseline.jsonl").write_text(text)
    assert report_mod.main(["--summarize", str(directory)]) == 0
    (row,) = [line for line in capsys.readouterr().out.splitlines() if line.startswith("| baseline")]
    return row


_HOST = {"check": "host", "sys_vendor": "Vendor", "kernel": "6.8", "in_user_manager": True}
_ALL_PASS = [{"check": name, "status": "pass"} for name in report_mod.CHECKS]
_READY = {"check": "verdict", "verdict": None, "first_failing": None, "attribution": "consistent"}


@pytest.mark.parametrize("name, records, raw, expected", [
    ("report-error", [{"check": "report_error", "label": "baseline",
                       "error": {"type": "ZeroDivisionError", "reason": "x"}}], None,
     "report error (ZeroDivisionError)"),
    ("verdict-error", [_HOST, *_ALL_PASS, {"check": "verdict", "first_failing": None,
                                           "verdict_error": {"type": "OSError"}}], None,
     "verdict error (OSError)"),
    ("empty", [], "", "incomplete (no verdict)"),
    ("host-only", [_HOST], None, "incomplete (no verdict)"),
    ("verdict-key-missing", [_HOST, *_ALL_PASS, {"check": "verdict", "first_failing": None}], None,
     "incomplete (no verdict)"),
    ("null-but-a-check-failed", [_HOST, *_ALL_PASS[:5], {"check": "device_plan", "status": "fail"},
                                 {**_READY, "attribution": "attribution_mismatch"}], None,
     "incomplete (checks did not all pass)"),
    ("null-but-checks-missing", [_HOST, _ALL_PASS[0], _READY], None,
     "incomplete (checks did not all pass)"),
    ("assert-error", [{"check": "assert_verdict", "passed": False, "error": {"type": "OSError"}}],
     None, "assert FAILED"),
    ("not-json", [], "{oops\n", "unreadable"),
])
def test_summary_never_says_ready_for_a_missing_or_failed_report(tmp_path, capsys, name, records,
                                                                 raw, expected):
    row = _summary_row(tmp_path, capsys, name, records, raw)
    assert row.rstrip().endswith(f"| {expected} |"), row
    assert "| ready |" not in row and "assert passed" not in row


def test_summary_says_ready_only_for_a_complete_passing_report(tmp_path, capsys):
    row = _summary_row(tmp_path, capsys, "ready", [_HOST, *_ALL_PASS, _READY])
    assert row == "| baseline | user manager | Vendor | 6.8 |  | ready |"


def test_summary_of_a_real_failed_report_is_not_ready(monkeypatch, tmp_path, capsys):
    """End to end: the report's own crash record must not summarize as ready."""
    monkeypatch.setattr(report_mod, "report", lambda _label: 1 / 0)
    directory = tmp_path / "ev"
    assert report_mod.main(["--label", "baseline", "--out", str(directory / "baseline.jsonl")]) == 0
    capsys.readouterr()
    assert report_mod.main(["--summarize", str(directory)]) == 0
    out = capsys.readouterr().out
    assert "report error (ZeroDivisionError)" in out and "| ready |" not in out


def test_assert_mode_fails_when_the_temporary_directory_is_off_the_device(device_host, tmp_path,
                                                                         capsys):
    """agent-harness#1993: the test session's scratch follows the temporary directory."""
    devices, _staging, _child, _location = device_host
    devices[str(tmp_path / "dev-tmp")] = (252, 0)
    assert report_mod.main(["--expect-device", "7:3"]) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    failed = [row["name"] for row in rows if row.get("check") == "assert" and not row["ok"]]
    assert failed == ["temporary directory on device"]


def test_host_facts_never_dump_the_api_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_fake-token-value")
    facts = report_mod.host_facts("h")
    assert "ghs_fake-token-value" not in json.dumps(facts, default=str)
    assert set(facts["env"]) == {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XDG_CACHE_HOME",
                                 "PHASE_LOOP_SANDBOX_STAGING_DIR", "HOME"}
