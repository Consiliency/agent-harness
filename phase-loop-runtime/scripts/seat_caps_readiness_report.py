"""Per-check readiness report for the per-seat resource caps (agent-harness#1993).

``readiness_code()`` runs five checks and folds every failure into the single code
``seat_resource_caps_unavailable``. This script reports each check separately, in the same
order, so a CI log shows which one failed and why. It changes nothing: it calls the
runtime's own functions and records what they return.

Report mode (default) always exits 0, even when a fact cannot be read; an unreadable fact
is recorded as an error. One JSON record per check, then a ``verdict`` record:

1. ``cgroup_v2``, 2. ``manager_controllers``, 3. ``systemd_run``, 4. ``runtime_bus``,
5. ``caps_record`` (the first half of check 5: which record applies, and whether it loads),
6. ``device_plan`` (the second half: where the automatic scratch paths land, and whether
   each resolves to a whole block device).

A record failure is reported as a record failure. The report never retries with the
packaged defaults and never substitutes a bound.

``--expect-device MAJ:MIN`` (assert mode) exits 1 unless readiness passes, both automatic
paths and the temporary directory are on MAJ:MIN, the child scratch is not the degraded
fallback, and the I/O device plan is exactly ``(MAJ:MIN,)``. The temporary directory
matters because a test session (the strict conformance suite) moves both automatic paths
below pytest's tmp_path, which is rooted there; ``tests/test_seat_caps_scratch_binding.py``
checks that binding from inside such a session.

``--summarize DIR`` prints a Markdown summary of the JSON Lines files in DIR.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "phase-loop-runtime/src/phase_loop_runtime"
CHECKS = ("cgroup_v2", "manager_controllers", "systemd_run", "runtime_bus", "caps_record",
          "device_plan")
_SYS_VENDOR = Path("/sys/class/dmi/id/sys_vendor")
_PROC_SELF_CGROUP = Path("/proc/self/cgroup")


def _runtime():
    if str(PACKAGE.parent) not in sys.path:
        sys.path.insert(0, str(PACKAGE.parent))
    from phase_loop_runtime import sandbox_policy, seat_resource_caps
    return seat_resource_caps, sandbox_policy


def _error(exc: BaseException) -> dict[str, Any]:
    cause = exc.__cause__
    out: dict[str, Any] = {"type": type(exc).__name__, "reason": str(exc)}
    if cause is not None:
        out["cause"] = {"type": type(cause).__name__, "reason": str(cause)}
    return out


def _fact(read: Callable[[], Any]) -> Any:
    """A fact, or a recorded error: an unreadable fact never stops the report."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - report mode records every failure
        return {"error": _error(exc)}


def _majmin(path: Path) -> str:
    info = os.stat(path)
    return f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="ascii", errors="replace").strip()


def _temp_root() -> str:
    """The temporary directory: pytest's tmp_path root, and so the suite's scratch root."""
    return tempfile.gettempdir()


def _in_user_manager() -> bool:
    """Whether this process runs below this user's systemd user manager (the in-unit
    baseline and provisioned reports), as opposed to the step's own shell (host context)."""
    marker = f"/user@{os.getuid()}.service/"
    return any(marker in line for line in _read_text(_PROC_SELF_CGROUP).splitlines())


def host_facts(label: str) -> dict[str, Any]:
    return {
        "check": "host",
        "label": label,
        "kernel": os.uname().release,
        "sys_vendor": _fact(lambda: _read_text(_SYS_VENDOR)),
        "cpu_count": os.cpu_count(),
        "uid": os.getuid(),
        "tempdir": _fact(_temp_root),
        "in_user_manager": _fact(_in_user_manager),
        "proc_self_cgroup": _fact(lambda: _read_text(_PROC_SELF_CGROUP)),
        "env": {name: os.environ.get(name, "unset") for name in (
            "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XDG_CACHE_HOME",
            "PHASE_LOOP_SANDBOX_STAGING_DIR", "HOME")},
    }


def _check_cgroup_v2(caps) -> tuple[bool, dict[str, Any]]:
    path = caps._CGROUP_ROOT / "cgroup.controllers"
    ok = path.is_file()
    return ok, {"path": str(path), "root_controllers": _fact(lambda: _read_text(path).split())}


def _check_manager_controllers(caps) -> tuple[bool, dict[str, Any]]:
    manager = caps._manager_cgroup()
    facts: dict[str, Any] = {"manager": str(manager),
                             "subtree_control": _fact(
                                 lambda: _read_text(manager / "cgroup.subtree_control").split())}
    controllers = set((manager / "cgroup.controllers").read_text(encoding="ascii").split())
    missing = sorted(caps.REQUIRED_CONTROLLERS - controllers)
    facts.update(controllers=sorted(controllers), missing=missing)
    return not missing, facts


def _check_systemd_run(caps) -> tuple[bool, dict[str, Any]]:
    path = caps._SYSTEMD_RUN

    def lstat_facts():
        info = os.lstat(path)
        return {"mode": oct(info.st_mode), "uid": info.st_uid, "realpath": os.path.realpath(path)}

    facts = {"path": str(path), "lstat": _fact(lstat_facts)}
    return bool(caps._systemd_run_ready()), facts


def _check_runtime_bus(caps) -> tuple[bool, dict[str, Any]]:
    runtime = caps._runtime_dir()
    bus = runtime / "bus"

    def bus_facts():
        import stat
        info = os.lstat(bus)
        return {"socket": stat.S_ISSOCK(info.st_mode), "uid": info.st_uid,
                "mode": oct(stat.S_IMODE(info.st_mode))}

    facts = {"XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", "unset"),
             "runtime_dir": str(runtime), "bus": str(bus), "exists": bus.exists(),
             "lstat": _fact(bus_facts)}
    return bool(facts["exists"]), facts


def _record_source(caps) -> tuple[str, str]:
    if os.path.lexists(caps.MANAGED_RECORD):
        return "managed", str(caps.MANAGED_RECORD)
    operator = caps._operator_record()
    if os.path.lexists(operator):
        return "operator", str(operator)
    return "defaults", ""


def _check_caps_record(caps) -> tuple[bool, dict[str, Any], Any]:
    facts: dict[str, Any] = {"cpu_count": os.cpu_count(), "mem_total": _fact(caps._mem_total)}
    source = _fact(lambda: _record_source(caps))
    if isinstance(source, tuple):
        facts.update(source=source[0], path=source[1], present=source[0] != "defaults")
    else:
        facts["source"] = source
    if facts.get("source") == "defaults":
        defaults = caps.DEFAULT_CAPS
        facts["default_bounds"] = {
            "cpu_max_percent": defaults.cpu_max_percent,
            "cpu_max_percent_limit": 100 * (os.cpu_count() or 1),
            "memory_max_bytes": defaults.memory_max_bytes,
        }
    try:
        loaded = caps.load_caps()
    except (caps.CapsUnavailable, OSError, ValueError) as exc:
        facts["failure"] = _error(exc)
        return False, facts, None
    facts.update(effective=asdict(loaded), caps_sha256=caps.caps_sha256(loaded))
    return True, facts, loaded


def _device_chain(caps, device: tuple[int, int]) -> dict[str, Any]:
    """The /sys/dev/block hops for one device, then the runtime's own whole-device answer."""
    hops: list[dict[str, Any]] = []
    current = device
    for _ in range(8):
        node = caps._SYS_DEV_BLOCK / f"{current[0]}:{current[1]}"
        try:
            resolved = node.resolve(strict=True)
        except OSError as exc:
            hops.append({"device": f"{current[0]}:{current[1]}", "error": _error(exc)})
            break
        hop: dict[str, Any] = {"device": f"{current[0]}:{current[1]}", "sysfs": str(resolved)}
        hops.append(hop)
        try:
            if (resolved / "partition").exists():
                hop["kind"] = "partition"
                current = caps._read_dev(resolved.parent / "dev")
                continue
            if (resolved / "dm").exists() or resolved.name.startswith("dm-"):
                hop["kind"] = "device-mapper"
                slaves = sorted((resolved / "slaves").iterdir())
                hop["slaves"] = [item.name for item in slaves]
                if len(slaves) != 1:
                    break
                current = caps._read_dev(slaves[0].resolve(strict=True) / "dev")
                continue
        except OSError as exc:
            hop["error"] = _error(exc)
            break
        hop["kind"] = "whole"
        break
    out: dict[str, Any] = {"hops": hops}
    try:
        whole = caps._whole_device(device)
        out["whole_device"] = f"{whole[0]}:{whole[1]}"
    except (caps.CapsUnavailable, OSError, ValueError) as exc:
        out["whole_device_error"] = _error(exc)
    return out


def _path_facts(caps, path: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"path": str(path)}
    try:
        info = os.stat(path)
    except OSError as exc:
        facts["error"] = _error(exc)
        return facts
    device = (os.major(info.st_dev), os.minor(info.st_dev))
    facts.update(st_dev=f"{device[0]}:{device[1]}", fstype=caps._mount_type(device))
    if device[0] == 0:
        facts["anonymous_filesystem"] = True
    else:
        facts.update(_device_chain(caps, device))
    return facts


def _staging_candidates(policy) -> dict[str, Any]:
    """Replays resolve_staging()'s order, stopping where it stops (so no extra directory
    is created), and records the first refusal of each refused candidate."""
    override = os.environ.get("PHASE_LOOP_SANDBOX_STAGING_DIR", "").strip()
    rows: list[dict[str, Any]] = []
    if override:
        rows.append({"path": override, "kind": "override", "result": "chosen_by_override"})
    else:
        accepted = False
        for candidate, base in policy._staging_candidates():
            row: dict[str, Any] = {"path": str(candidate), "base": str(base) if base else None}
            if accepted:
                row["result"] = "not_evaluated"
            elif policy.is_ram_backed(candidate):
                row["result"] = "refused"
                row["refusal"] = "is_ram_backed"
            elif not policy._staging_usable(candidate, base):
                row["result"] = "refused"
                row["refusal"] = "_private" if base is not None else "_staging_usable"
            else:
                row["result"] = "accepted"
                accepted = True
            rows.append(row)
    chosen = policy.resolve_staging()
    return {"candidates": rows, "chosen": {"path": str(chosen.path), "degraded": chosen.degraded,
                                           "reason": chosen.reason}}


def _child_candidates(policy) -> dict[str, Any]:
    """Replays _child_tmp_dir()'s order and records the first refusal of each candidate."""
    from phase_loop_runtime.seat_host_namespace import scratch_root_allowed
    cache = policy._user_cache_dir()
    shared = policy.legacy_staging_root()
    candidates = [(cache / "phase-loop" / "tmp", cache)] if cache is not None else []
    candidates.append((shared / f"phase-loop-{os.getuid()}" / "tmp", shared))
    rows: list[dict[str, Any]] = []
    accepted = False
    for candidate, base in candidates:
        row: dict[str, Any] = {"path": str(candidate), "base": str(base)}
        rows.append(row)
        if accepted:
            row["result"] = "not_evaluated"
            continue
        if not scratch_root_allowed(candidate):
            row.update(result="refused", refusal="scratch_root_allowed")
            continue
        if policy.is_ram_backed(candidate):
            row.update(result="refused", refusal="is_ram_backed")
            continue
        if not policy._private(candidate, base):
            row.update(result="refused", refusal="_private")
            continue
        try:
            free = policy._free_bytes(candidate)
            floor = policy.effective_floor_bytes(candidate)
        except OSError as exc:
            row.update(result="refused", refusal="free_space_unreadable", error=_error(exc))
            continue
        row.update(free_bytes=free, effective_floor_bytes=floor)
        if free < floor:
            row.update(result="refused", refusal="free < effective_floor_bytes")
            continue
        row["result"] = "accepted"
        accepted = True
    chosen = policy._child_tmp_dir()
    replay = next((row["path"] for row in rows if row["result"] == "accepted"), None)
    out = {"candidates": rows, "chosen": {"path": str(chosen.path), "degraded": chosen.degraded,
                                          "reason": chosen.reason}}
    if (replay is None) != chosen.degraded or (replay is not None and replay != str(chosen.path)):
        out["candidate_replay_mismatch"] = True
    return out


def _check_device_plan(caps, policy, loaded) -> tuple[bool | None, dict[str, Any]]:
    facts: dict[str, Any] = {
        "staging": _fact(lambda: _staging_candidates(policy)),
        "child_scratch": _fact(lambda: _child_candidates(policy)),
    }
    for key in ("staging", "child_scratch"):
        chosen = facts[key].get("chosen") if isinstance(facts[key], dict) else None
        if chosen:
            chosen["facts"] = _fact(lambda path=chosen["path"]: _path_facts(caps, Path(path)))
    if loaded is None:
        facts["informational"] = True
        return None, facts
    try:
        facts["io_devices"] = list(caps.io_devices(loaded))
    except (caps.CapsUnavailable, OSError, ValueError) as exc:
        facts["failure"] = _error(exc)
        return False, facts
    return True, facts


def report(label: str) -> list[dict[str, Any]]:
    caps, policy = _runtime()
    records: list[dict[str, Any]] = [host_facts(label)]
    first_failing: str | None = None
    loaded = None
    simple = {
        "cgroup_v2": _check_cgroup_v2,
        "manager_controllers": _check_manager_controllers,
        "systemd_run": _check_systemd_run,
        "runtime_bus": _check_runtime_bus,
    }
    for name in CHECKS:
        record: dict[str, Any] = {"check": name}
        try:
            if name in simple:
                ok, facts = simple[name](caps)
            elif name == "caps_record":
                ok, facts, loaded = _check_caps_record(caps)
            else:
                ok, facts = _check_device_plan(caps, policy, loaded)
        except Exception as exc:  # noqa: BLE001 - an unreadable fact is a failed check
            ok, facts = False, {"failure": _error(exc)}
        record.update(facts)
        if first_failing is not None:
            record["status"] = "not_reached"
            record["informational"] = True
        elif ok is None:
            record["status"] = "not_reached"
        else:
            record["status"] = "pass" if ok else "fail"
            if not ok:
                first_failing = name
        records.append(record)
    verdict: dict[str, Any] = {"check": "verdict"}
    try:
        code = caps.readiness_code()
        verdict["verdict"] = code
        verdict["first_failing"] = first_failing
        verdict["attribution"] = ("consistent" if (code is None) == (first_failing is None)
                                  else "attribution_mismatch")
    except Exception as exc:  # noqa: BLE001
        verdict["verdict_error"] = _error(exc)
        verdict["first_failing"] = first_failing
    records.append(verdict)
    return records


def assert_device(label: str, expected: str) -> tuple[bool, list[dict[str, Any]]]:
    caps, policy = _runtime()
    results: list[dict[str, Any]] = [host_facts(label)]

    def check(name: str, probe: Callable[[], tuple[bool, Any]]) -> None:
        try:
            ok, observed = probe()
        except Exception as exc:  # noqa: BLE001 - any failure to observe fails the assertion
            ok, observed = False, {"error": _error(exc)}
        results.append({"check": "assert", "name": name, "ok": bool(ok), "observed": observed})

    check("readiness_code is None", lambda: (lambda code: (code is None, code))(caps.readiness_code()))
    check("staging_root on device",
          lambda: (lambda dev: (dev == expected, dev))(_majmin(policy.staging_root())))
    check("temporary directory on device",
          lambda: (lambda dev: (dev == expected, dev))(_majmin(Path(_temp_root()))))
    child = None

    def child_location():
        nonlocal child
        child = policy._child_tmp_dir()
        return child

    check("child scratch on device",
          lambda: (lambda dev: (dev == expected, dev))(_majmin(child_location().path)))
    check("child scratch not degraded",
          lambda: (child is not None and not child.degraded,
                   None if child is None else {"path": str(child.path), "reason": child.reason}))
    check("io_devices is exactly the device",
          lambda: (lambda devs: (devs == (expected,), list(devs)))(caps.io_devices(caps.load_caps())))
    passed = all(row["ok"] for row in results if row.get("check") == "assert")
    results.append({"check": "assert_verdict", "expected_device": expected, "passed": passed})
    return passed, results


def _write(records: list[dict[str, Any]], out: Path | None) -> None:
    lines = [json.dumps(record, sort_keys=True, default=str) for record in records]
    for line in lines:
        print(line)
    if out is None:
        return
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def _outcome(records: list[dict[str, Any]]) -> tuple[str, str]:
    """(first failing check, outcome) for one report file.

    ``ready`` and ``assert passed`` are claimed only from a complete, successful report:
    an explicit ``verdict: null`` with consistent attribution and all six checks passed,
    or an assert verdict with ``passed: true``. Anything missing or failed says so.
    """
    by_check: dict[str, dict[str, Any]] = {}
    for record in records:
        by_check.setdefault(str(record.get("check")), record)
    if "report_error" in by_check:
        error = by_check["report_error"].get("error") or {}
        return "", f"report error ({error.get('type', 'unknown')})"
    if "assert_verdict" in by_check:
        verdict = by_check["assert_verdict"]
        if verdict.get("passed") is True and "error" not in verdict:
            return "", "assert passed"
        failed = [row.get("name", "") for row in records
                  if row.get("check") == "assert" and row.get("ok") is not True]
        return ", ".join(failed), "assert FAILED"
    verdict = by_check.get("verdict")
    if verdict is None:
        return "", "incomplete (no verdict)"
    failing = str(verdict.get("first_failing") or "")
    if "verdict_error" in verdict:
        error = verdict["verdict_error"] or {}
        return failing, f"verdict error ({error.get('type', 'unknown')})"
    if "verdict" not in verdict:
        return failing, "incomplete (no verdict)"
    if verdict["verdict"] is not None:
        return failing, str(verdict["verdict"])
    statuses = [by_check.get(name, {}).get("status") for name in CHECKS]
    if verdict.get("attribution") == "consistent" and statuses == ["pass"] * len(CHECKS):
        return "", "ready"
    return failing, "incomplete (checks did not all pass)"


def summarize(directory: Path) -> str:
    rows = ["| report | context | sys_vendor | kernel | first failing check | verdict |",
            "|---|---|---|---|---|---|"]
    for path in sorted(directory.glob("*.jsonl")):
        try:
            records = [json.loads(line) for line in
                       path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not all(isinstance(record, dict) for record in records):
                raise ValueError("not a JSON object per line")
        except (OSError, ValueError):
            rows.append(f"| {path.stem} | unreadable | | | | unreadable |")
            continue
        host = next((record for record in records if record.get("check") == "host"), {})
        context = {True: "user manager", False: "host"}.get(host.get("in_user_manager"), "unknown")
        vendor = host.get("sys_vendor")
        failing, outcome = _outcome(records)
        rows.append(f"| {path.stem} | {context} | {vendor if isinstance(vendor, str) else 'unknown'}"
                    f" | {host.get('kernel', '')} | {failing} | {outcome} |")
    enforcement = directory / "enforcement.json"
    if enforcement.is_file():
        try:
            verdict_text = json.loads(enforcement.read_text(encoding="utf-8")).get("verdict")
        except (OSError, ValueError):
            verdict_text = "unreadable"
        rows.append("")
        rows.append(f"Enforcement validation: **{verdict_text}**")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="report")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--expect-device", metavar="MAJ:MIN")
    parser.add_argument("--summarize", type=Path, metavar="DIR")
    args = parser.parse_args(argv)
    if args.summarize is not None:
        sys.stdout.write(summarize(args.summarize))
        return 0
    if args.expect_device is not None:
        try:
            passed, records = assert_device(args.label, args.expect_device)
        except Exception as exc:  # noqa: BLE001 - assert mode fails closed
            passed, records = False, [{"check": "assert_verdict", "passed": False,
                                       "error": _error(exc)}]
        _write(records, args.out)
        return 0 if passed else 1
    try:
        records = report(args.label)
    except Exception as exc:  # noqa: BLE001 - report mode never fails the caller
        records = [{"check": "report_error", "label": args.label, "error": _error(exc)}]
    try:
        _write(records, args.out)
    except OSError as exc:
        print(json.dumps({"check": "report_error", "error": _error(exc)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
