"""Bounded I/O-bandwidth enforcement check on the CI scratch device (agent-harness#1993).

Readback proves that io.max is written; it does not prove that the kernel throttles I/O
on the device. This script runs real direct I/O through the production capped launch path
(``_seat_scope`` and ``capped_popen``, called, not changed) on the provisioned loop device
and checks that the parent's I/O bandwidth caps bind there. It runs only in the
``seat-caps-gate`` probe workflow, inside the user manager, with the scratch paths on the
device.

Protocol (predeclared; thresholds are never relaxed and failed checks are never retried):

1. Realize the parent: inside one ``_seat_scope``, launch and await a no-I/O child, so the
   scope's retained parent slice exists. All snapshots and property reads happen while
   that scope is alive.
2. Uncapped control, outside the caps: a direct-I/O write, then read, of ``--size-mib``.
   If either is slower than twice its cap, the device is too slow to show the cap and the
   result is ``inconclusive``, which fails.
3. Capped write, then capped read, each in one capped child: a short warm-up transfer
   (consuming any burst allowance the kernel grants a fresh throttle window) followed by
   the measured transfer of ``--size-mib``. Elapsed time is dd's own figure for the
   measured transfer alone, so systemd startup and cap attestation are excluded. Each
   child must exit 0 and dd must report exactly the requested byte counts.
4. The measured throughput must be at most ``TOLERANCE`` times the cap. The parent's
   ``io.stat`` row for the device must grow by at least ``ACCOUNTED`` of the measured
   bytes across each child, and its ``io.max`` row must equal the record's four values.

Every child and the whole validation are bounded; a timed-out child is terminated and
reaped. ``enforcement.json`` is written on every outcome.

Scope of the claim: on the observed runner, the I/O bandwidth caps bind and are accounted
at the provisioned loop device for the capped launch path. Direct I/O bypasses the mounted
filesystem's page cache; the loop backing file may still be cached by the host, so this
says nothing about the backing layer. Memory, CPU and pids rest on the child's readback
attestation and the conformance obligations, as before.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "phase-loop-runtime/src/phase_loop_runtime"
MIB = 1024 * 1024
TOLERANCE = 1.25
CONTROL_FACTOR = 2.0
ACCOUNTED = 0.9
WARMUP_MIB = 64
SEAT_KEY = "ci:seat-caps-validation"
_DD_LINE = re.compile(r"^(\d+) bytes\b.*\bcopied, ([0-9.]+(?:e[-+]?\d+)?) s\b", re.MULTILINE)


class ValidationError(RuntimeError):
    """A step of the protocol could not produce evidence."""


# --- pure verdict logic (unit tested) -------------------------------------------------

def parse_dd(stderr: str) -> list[tuple[int, float]]:
    """Every (bytes, seconds) pair dd printed, in order (LC_ALL=C output)."""
    return [(int(match.group(1)), float(match.group(2))) for match in _DD_LINE.finditer(stderr)]


def throughput(nbytes: int, seconds: float) -> float:
    if seconds <= 0:
        raise ValidationError("dd reported a non-positive elapsed time")
    return nbytes / seconds


def parse_io_stat(text: str, device: str) -> dict[str, int]:
    """The ``io.stat`` counters for ``device``; zero counters when the row is absent."""
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == device:
            counters = {}
            for field in fields[1:]:
                key, _, value = field.partition("=")
                if value.isdigit():
                    counters[key] = int(value)
            return counters
    return {}


def parse_io_max(text: str, device: str) -> dict[str, str] | None:
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == device:
            return dict(field.partition("=")[::2] for field in fields[1:])
    return None


def control_verdict(write_bps: float, read_bps: float, *, wbps: int, rbps: int) -> dict[str, Any]:
    """The uncapped control must be fast enough to make the cap observable."""
    write_ok = write_bps >= CONTROL_FACTOR * wbps
    read_ok = read_bps >= CONTROL_FACTOR * rbps
    return {"write_bps": write_bps, "read_bps": read_bps,
            "write_floor_bps": CONTROL_FACTOR * wbps, "read_floor_bps": CONTROL_FACTOR * rbps,
            "conclusive": write_ok and read_ok}


def capped_verdict(*, label: str, measured_bytes: int, seconds: float, cap_bps: int,
                   accounted_delta: int) -> dict[str, Any]:
    """One capped transfer: bound by the cap within TOLERANCE, and accounted at the parent."""
    observed = throughput(measured_bytes, seconds)
    bound_ok = observed <= TOLERANCE * cap_bps
    accounted_ok = accounted_delta >= ACCOUNTED * measured_bytes
    return {"label": label, "measured_bytes": measured_bytes, "seconds": seconds,
            "observed_bps": observed, "cap_bps": cap_bps, "limit_bps": TOLERANCE * cap_bps,
            "bound": bound_ok, "accounted_delta": accounted_delta,
            "accounted_floor": ACCOUNTED * measured_bytes, "accounted": accounted_ok,
            "pass": bound_ok and accounted_ok}


def expected_io_max(io_max) -> dict[str, str]:
    return {"rbps": str(io_max.rbps), "wbps": str(io_max.wbps),
            "riops": str(io_max.riops), "wiops": str(io_max.wiops)}


def overall(control: dict[str, Any] | None, capped: list[dict[str, Any]],
            io_max_ok: bool | None) -> str:
    """``pass`` only when the control is conclusive and every check holds."""
    if control is None or not control.get("conclusive"):
        return "inconclusive"
    if io_max_ok is True and len(capped) == 2 and all(item["pass"] for item in capped):
        return "pass"
    return "fail"


# --- execution --------------------------------------------------------------------------

def _runtime():
    if str(PACKAGE.parent) not in sys.path:
        sys.path.insert(0, str(PACKAGE.parent))
    from phase_loop_runtime import sandbox_policy, seat_resource_caps
    return seat_resource_caps, sandbox_policy


class Deadline:
    def __init__(self, seconds: float, child_cap: float):
        self.end = time.monotonic() + seconds
        self.child_cap = child_cap

    def child(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 1:
            raise ValidationError("the validation deadline was reached")
        return min(self.child_cap, remaining)


def _stop(process: subprocess.Popen) -> None:
    """Terminate and reap a timed-out child and its process group."""
    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def _finish(process: subprocess.Popen, timeout: float, what: str) -> str:
    try:
        _out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _stop(process)
        raise ValidationError(f"{what} exceeded its {timeout:.0f} s bound") from exc
    text = err.decode("utf-8", "replace") if isinstance(err, bytes) else (err or "")
    if process.returncode != 0:
        raise ValidationError(f"{what} exited {process.returncode}: {text.strip()[-400:]}")
    return text


def _dd_env() -> dict[str, str]:
    return {**os.environ, "LC_ALL": "C"}


def _dd_write(path: Path, mib: int) -> list[str]:
    return ["dd", "if=/dev/zero", f"of={path}", "bs=1M", f"count={mib}", "oflag=direct",
            "conv=fsync"]


def _dd_read(path: Path, mib: int) -> list[str]:
    return ["dd", f"if={path}", "of=/dev/null", "bs=1M", f"count={mib}", "iflag=direct"]


def _exact(stderr: str, wanted: list[int], what: str) -> float:
    """Require dd's exact byte counts; return the last (measured) transfer's seconds."""
    pairs = parse_dd(stderr)
    if [nbytes for nbytes, _ in pairs] != wanted:
        raise ValidationError(f"{what}: dd reported {[n for n, _ in pairs]} bytes, wanted {wanted}")
    return pairs[-1][1]


def _uncapped(argv: list[str], deadline: Deadline, what: str) -> str:
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, env=_dd_env(), start_new_session=True)
    return _finish(process, deadline.child(), what)


def _capped(caps, script: str, deadline: Deadline, what: str) -> str:
    process = caps.capped_popen(["/bin/sh", "-c", script], seat_key=SEAT_KEY,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, env=_dd_env(), start_new_session=True)
    return _finish(process, deadline.child(), what)


def _shell(argv: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(item) for item in argv)


def _systemctl_show(unit: str) -> dict[str, str]:
    runtime = f"/run/user/{os.getuid()}"
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", runtime)}
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus")
    done = subprocess.run(
        ["systemctl", "--user", "show", unit, "-p", "IOReadBandwidthMax", "-p",
         "IOWriteBandwidthMax", "-p", "IOReadIOPSMax", "-p", "IOWriteIOPSMax", "-p", "MemoryMax",
         "-p", "MemorySwapMax", "-p", "CPUQuotaPerSecUSec", "-p", "TasksMax"],
        capture_output=True, text=True, timeout=15, check=False, env=env)
    out: dict[str, str] = {"returncode": str(done.returncode)}
    for line in done.stdout.splitlines():
        key, _, value = line.partition("=")
        # A property with one row per device repeats its key; keep every row.
        out[key] = f"{out[key]}; {value}" if key in out else value
    return out


def validate(args, result: dict[str, Any]) -> None:
    caps, policy = _runtime()
    deadline = Deadline(args.deadline, args.child_timeout)
    result["kernel"] = os.uname().release
    loaded = caps.load_caps()
    result["caps_sha256"] = caps.caps_sha256(loaded)
    result["io_max_record"] = asdict(loaded.io_max)
    devices = caps.io_devices(loaded)
    result["io_devices"] = list(devices)
    if devices != (args.majmin,):
        raise ValidationError(f"the automatic paths resolve to {list(devices)}, not {args.majmin}")
    work = Path(policy.staging_root()) / f"ci-seat-caps-validation-{os.getpid()}"
    work.mkdir(mode=0o700)
    result["work_dir"] = str(work)
    info = os.stat(work)
    observed_dev = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    if observed_dev != args.majmin:
        raise ValidationError(f"{work} is on {observed_dev}, not {args.majmin}")
    size = args.size_mib
    size_bytes = size * MIB
    warm_bytes = WARMUP_MIB * MIB
    try:
        control_file = work / "control.bin"
        write_err = _uncapped(_dd_write(control_file, size), deadline, "control write")
        read_err = _uncapped(_dd_read(control_file, size), deadline, "control read")
        control_file.unlink()
        control = control_verdict(
            throughput(size_bytes, _exact(write_err, [size_bytes], "control write")),
            throughput(size_bytes, _exact(read_err, [size_bytes], "control read")),
            wbps=loaded.io_max.wbps, rbps=loaded.io_max.rbps)
        result["control"] = control
        if not control["conclusive"]:
            return
        with caps._seat_scope(SEAT_KEY, caps._LaunchClass.TEST):
            # Realize and retain the parent before the first snapshot.
            _finish(caps.capped_popen(["/bin/true"], seat_key=SEAT_KEY, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      start_new_session=True),
                    deadline.child(), "parent realization child")
            scope = caps._CURRENT_SEAT_SCOPE.get()
            if scope is None or scope.parent is None:
                raise ValidationError("the seat scope did not retain a parent")
            unit = scope.parent.unit
            parent = caps._seat_slice_chain(unit)[-1]
            result["parent_unit"] = unit
            result["parent_cgroup"] = str(parent)
            io_max_text = (parent / "io.max").read_text(encoding="ascii")
            row = parse_io_max(io_max_text, args.majmin)
            result["io_max"] = row
            result["io_max_ok"] = row == expected_io_max(loaded.io_max)
            result["properties"] = _systemctl_show(unit)

            def stat() -> dict[str, int]:
                return parse_io_stat((parent / "io.stat").read_text(encoding="ascii"), args.majmin)

            capped: list[dict[str, Any]] = []
            warm_file, cap_file = work / "warm.bin", work / "cap.bin"
            before = stat()
            write_script = f"{_shell(_dd_write(warm_file, WARMUP_MIB))} && {_shell(_dd_write(cap_file, size))}"
            err = _capped(caps, write_script, deadline, "capped write")
            after = stat()
            seconds = _exact(err, [warm_bytes, size_bytes], "capped write")
            capped.append(capped_verdict(
                label="write", measured_bytes=size_bytes, seconds=seconds,
                cap_bps=loaded.io_max.wbps,
                accounted_delta=after.get("wbytes", 0) - before.get("wbytes", 0)))
            result["io_stat_write"] = {"before": before, "after": after}
            before = stat()
            read_script = f"{_shell(_dd_read(warm_file, WARMUP_MIB))} && {_shell(_dd_read(cap_file, size))}"
            err = _capped(caps, read_script, deadline, "capped read")
            after = stat()
            seconds = _exact(err, [warm_bytes, size_bytes], "capped read")
            capped.append(capped_verdict(
                label="read", measured_bytes=size_bytes, seconds=seconds,
                cap_bps=loaded.io_max.rbps,
                accounted_delta=after.get("rbytes", 0) - before.get("rbytes", 0)))
            result["io_stat_read"] = {"before": before, "after": after}
            result["capped"] = capped
    finally:
        for name in ("control.bin", "warm.bin", "cap.bin"):
            try:
                (work / name).unlink()
            except FileNotFoundError:
                pass
        try:
            work.rmdir()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--majmin", required=True, help="the provisioned device's MAJ:MIN")
    parser.add_argument("--out", type=Path, required=True, help="evidence directory")
    parser.add_argument("--size-mib", type=int, default=512)
    parser.add_argument("--child-timeout", type=float, default=120.0)
    parser.add_argument("--deadline", type=float, default=480.0)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d+:\d+", args.majmin) or args.size_mib < 128:
        parser.error("--majmin must be MAJ:MIN and --size-mib at least 128")
    result: dict[str, Any] = {
        "schema": "ci_seat_caps_enforcement.v1", "device": args.majmin,
        "protocol": {"size_mib": args.size_mib, "warmup_mib": WARMUP_MIB,
                     "tolerance": TOLERANCE, "control_factor": CONTROL_FACTOR,
                     "accounted": ACCOUNTED, "child_timeout_s": args.child_timeout,
                     "deadline_s": args.deadline, "timing": "dd's own elapsed time for the measured transfer"},
    }
    try:
        validate(args, result)
        result["verdict"] = overall(result.get("control"), result.get("capped", []),
                                    result.get("io_max_ok"))
    except Exception as exc:  # noqa: BLE001 - every failure is recorded as evidence
        result["verdict"] = "fail"
        result["error"] = {"type": type(exc).__name__, "reason": str(exc)}
    finally:
        args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(args.out / "enforcement.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, default=str)
            stream.write("\n")
    print(json.dumps({"verdict": result["verdict"], "error": result.get("error")}, sort_keys=True))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
