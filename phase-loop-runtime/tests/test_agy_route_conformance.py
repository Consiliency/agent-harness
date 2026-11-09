"""The strict hermetic agy route conformance suite (AGYROLL §3.4; RECBIND SL-2, amendments A1/A2).

It runs the PRODUCTION qualification driver -- ``agy_qualification.qualify_image`` -> worker
-> ``run_operation`` -> validator -- under the real bubblewrap owned profile and seal checks,
on a compiled stand-in image (``fixtures/agy_conformance/standin.c``). No provider is called,
no raw receipt is read, and the driver is never mocked: the only inputs this suite provides
are a stand-in executable, a synthetic login file in a private ``HOME``, and that store's
provenance entry for the stand-in's digest (the gate a provenance-verified image passes).

Each obligation in ``CONFORMANCE_OBLIGATIONS`` is one parametrized case of
``test_obligation``, so the JUnit report names every id exactly once:

- ``op_*``: the conforming stand-in passes ``completion``, ``cancel`` and ``owner-loss``;
- ``neg_*``: a provider-trippable violation does not pass, with its measured, pinned outcome;
- ``pos_*``: a provider that ignores cancel, or leaves an orphaned child, still passes,
  because the driver -- not the provider -- enforces cancellation and cleanup.

Strict mode (``AGY_CONFORMANCE_STRICT=1``, set by release CI): a missing prerequisite
(bubblewrap, user namespaces, a C compiler, the seat helpers, a machine id) is a FAILURE,
never a skip. Without it a local run skips with the reason. The flag is read once at import,
because the suite's autouse isolation removes every ``AGY_*`` name before each test.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from phase_loop_runtime import agy_provenance
from phase_loop_runtime import agy_qualification as q
from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import seat_resource_caps

#: The eight conformance obligations (AGYROLL §3.4, amendments A1 and A2). ``--release``
#: (``scripts/verify_qualified_agy_image.py``) requires each id passed exactly once.
CONFORMANCE_OBLIGATIONS = (
    "op_completion",
    "op_cancel",
    "op_owner_loss",
    "neg_no_terminal_event",
    "neg_unregistered_helper",
    "neg_tool_step",
    "pos_ignores_cancel",
    "pos_orphaned_child",
)

STRICT_ENV = "AGY_CONFORMANCE_STRICT"
STRICT = os.environ.get(STRICT_ENV) == "1"
# The REAL per-seat caps readiness (agent-harness#1895), captured at import: the suite's
# autouse fixture replaces it in this process, but the qualification worker is a separate
# process that launches its provider through the real capped boundary.
CAPS_READINESS = seat_resource_caps.readiness_code

REPO = Path(__file__).resolve().parents[2]
STANDIN_SOURCE = Path(__file__).resolve().parent / "fixtures" / "agy_conformance" / "standin.c"
BWRAP = "/usr/bin/bwrap"
SETPRIV = "/usr/bin/setpriv"
HELPER = "/usr/bin/sleep"  # the unregistered helper the stand-in's child execs

#: Stand-in modes (``-DAGY_STANDIN_MODE``), one image per control.
MODES = {
    "conforming": 0,
    "no_terminal_event": 1,
    "unregistered_helper": 2,
    "tool_step": 3,
    "ignores_cancel": 4,
    "orphaned_child": 5,
}

PASSED = {"status": "passed"}
#: Each obligation: the stand-in it runs, and the ``qualify_image`` outcome it must give.
#: The negative outcomes are the measured ones, pinned (A1, A2). Both stream-surface
#: negatives classify ``transient`` because the driver files any non-OK completion as a
#: provider transient (agent-harness#1935); this suite pins today's classification.
EXPECTED = {
    "op_completion": ("conforming", PASSED),
    "op_cancel": ("conforming", PASSED),
    "op_owner_loss": ("conforming", PASSED),
    "neg_no_terminal_event": ("no_terminal_event", {"status": "transient", "operation": "completion"}),
    "neg_unregistered_helper": ("unregistered_helper", {"status": "failed", "operation": "completion",
                                                        "reason": "operation_validation_failed"}),
    "neg_tool_step": ("tool_step", {"status": "transient", "operation": "completion"}),
    "pos_ignores_cancel": ("ignores_cancel", PASSED),
    "pos_orphaned_child": ("orphaned_child", PASSED),
}

TOKEN = ".gemini/antigravity-cli/antigravity-oauth-token"


# ------------------------------------------------------------------ prerequisites

def prerequisite_gap(*, bwrap: str = BWRAP, setpriv: str = SETPRIV, helper: str = HELPER,
                     which=shutil.which, run=subprocess.run, machine_id=q.read_machine_id,
                     caps_readiness=None) -> str | None:
    """The first missing prerequisite of a hermetic driver run, or ``None``."""
    if not sys.platform.startswith("linux"):
        return "the agy heartbeat route is Linux-only"
    for path, name in ((bwrap, "bubblewrap"), (setpriv, "setpriv"), (helper, "the helper executable")):
        if not os.access(path, os.X_OK):
            return f"{name} is missing ({path})"
    try:
        probe = run([bwrap, "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/", "--", "/bin/true"],
                    capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "user namespaces are unavailable (bubblewrap probe could not run)"
    if probe.returncode != 0:
        return "user namespaces are unavailable (bubblewrap probe failed)"
    if which("cc") is None:
        return "a C compiler (cc) is missing for the stand-in image"
    if machine_id() is None:
        return "/etc/machine-id is missing or malformed (the qualification store needs it)"
    code = (caps_readiness or CAPS_READINESS)()
    if code is not None:
        return f"per-seat resource caps are unavailable ({code}; docs/seat-resource-caps.md)"
    return None


def require_prerequisites(gap: str | None, *, strict: bool) -> None:
    """Under strict mode a gap FAILS; otherwise it skips with its reason."""
    if gap is None:
        return
    if strict:
        pytest.fail(f"agy conformance prerequisite missing under {STRICT_ENV}=1: {gap}", pytrace=False)
    pytest.skip(f"agy conformance prerequisite missing: {gap}")


# ------------------------------------------------------------------- the driver run

_BUILT: dict[str, Path] = {}
_RUNS: dict[str, dict] = {}


def _build(mode: str, directory: Path) -> Path:
    if mode not in _BUILT:
        out = directory / f"agy-{mode}"
        for flags in (["-static"], []):
            done = subprocess.run(["cc", "-O2", *flags, f"-DAGY_STANDIN_MODE={MODES[mode]}",
                                   "-o", str(out), str(STANDIN_SOURCE)], capture_output=True, timeout=120)
            if done.returncode == 0:
                break
        else:
            pytest.fail(f"the agy stand-in did not compile: {done.stderr.decode(errors='replace')[-400:]}")
        _BUILT[mode] = out
    return _BUILT[mode]


def _path_without_agy() -> list[str]:
    return [entry for entry in os.environ.get("PATH", os.defpath).split(os.pathsep)
            if entry and not os.path.exists(os.path.join(entry, "agy"))]


def _login(home: Path) -> None:
    """A synthetic login in agy's file shape; nothing reads it but the profile's symlink."""
    expiry = datetime.now(timezone.utc) + timedelta(hours=2)
    path = home / TOKEN
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"token": {"access_token": "synthetic-conformance", "token_type": "Bearer",
                                          "refresh_token": "synthetic-conformance",
                                          "expiry": expiry.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z"},
                                "auth_method": "consumer"}))
    path.chmod(0o600)


def _qualify(mode: str, base: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """One production ``qualify_image`` series of ``mode``'s stand-in; memoized per mode."""
    if mode in _RUNS:
        return _RUNS[mode]
    work = base / mode
    home = work / "home"
    home.mkdir(parents=True)
    _login(home)
    # The store defaults under $HOME; the inherited env of the qualification worker is the
    # test's own, so both the coordinator and the worker resolve this private store.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(REPO)  # the worker's board needs a canonical repository authority
    # As on a real first use, the image under qualification IS the `agy` on PATH. No host
    # agy may be reachable: the run must not depend on what this machine has installed.
    binary = _build(mode, base)
    bindir = work / "bin"
    bindir.mkdir()
    shutil.copyfile(binary, bindir / "agy")
    (bindir / "agy").chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bindir), *_path_without_agy()]))
    image = gh.VerifiedImage.from_bytes(binary.read_bytes())
    try:
        store = q.Store()
        store.create()
        host = agy_provenance.detect_platform()
        asset = agy_provenance.ReleaseAsset(
            "0.0.0-conformance", host.asset,
            f"https://github.com/google-antigravity/antigravity-cli/releases/download/0.0.0/{host.asset}",
            "0" * 64)
        store.put_provenance(agy_provenance.Provenance(image.sha256, host.name, asset), q.agy_profile_digest())
        help_bytes = q._run_help(image, q._panel()._broker_subscription_env())
        outcome = q.qualify_image(image, help_bytes, store=store)
        series, = (store.host_dir / "runs").iterdir()
    finally:
        image.close()
    receipts = {path.parent.name: json.loads(path.read_text()) for path in series.glob("*/qualification.json")}
    failures = {path.parent.name: json.loads(path.read_text()) for path in series.glob("*/failure.json")}
    _RUNS[mode] = {"outcome": outcome, "receipts": receipts, "failures": failures,
                   "diagnostics": _diagnostics(series)}
    return _RUNS[mode]


def _diagnostics(series: Path) -> dict:
    """What each operation's worker saw, for a failure message: the leg's terminal result and
    the tail of its log. Synthetic run only (stand-in image, synthetic login)."""
    found = {}
    for operation in sorted(path.name for path in series.iterdir() if path.is_dir()):
        root = series / operation
        terminal = json.loads((root / "terminal.json").read_text()) if (root / "terminal.json").is_file() else None
        log = (root / "worker.log").read_text(errors="replace") if (root / "worker.log").is_file() else ""
        found[operation] = {
            "result": terminal and terminal.get("result"),
            "terminal_reason": terminal and (terminal.get("monitoring") or {}).get("terminal_reason"),
            "worker_log_tail": log.splitlines()[-12:],
        }
    return found


@pytest.fixture(scope="session")
def conformance_base(tmp_path_factory):
    return tmp_path_factory.mktemp("agy-conformance")


@pytest.fixture
def driver(conformance_base, monkeypatch):
    require_prerequisites(prerequisite_gap(), strict=STRICT)
    return lambda mode: _qualify(mode, conformance_base, monkeypatch)


# --------------------------------------------------------------------- obligations

@pytest.mark.parametrize("obligation", CONFORMANCE_OBLIGATIONS)
def test_obligation(obligation, driver):
    mode, expected = EXPECTED[obligation]
    run = driver(mode)
    if run["outcome"] != expected:
        # A plain string, so CI shows the worker's refusal untruncated.
        pytest.fail(json.dumps({"obligation": obligation, "expected": expected, "outcome": run["outcome"],
                                "failures": {name: {key: failure.get(key) for key in ("stage", "reason")}
                                             for name, failure in run["failures"].items()},
                                "diagnostics": run["diagnostics"]}, sort_keys=True), pytrace=False)
    receipts, failures = run["receipts"], run["failures"]
    if obligation == "op_completion":
        record = receipts["completion"]
        assert record["result"]["status"] == "OK"
        assert q._panel().terminal_verdict(record["result"]["text"]) == "AGREE"
    elif obligation in ("op_cancel", "pos_ignores_cancel"):
        record = receipts["cancel"]
        assert record["monitoring"]["terminal_reason"] == "user_cancel"
        assert record["result"] == {"status": "UNAVAILABLE", "text": "", "detail": q.CANCELLED}
    elif obligation == "op_owner_loss":
        record = receipts["owner-loss"]
        assert record["observer"]["kill_event"]["signal"] == signal.SIGKILL
        assert record["observer"]["live_namespace_members"] == []
    elif obligation == "pos_orphaned_child":
        # The orphan really runs: the completion operation (3 s of provider life) observed two
        # distinct processes of the stand-in image. Owner-loss kills the owner as soon as the
        # provider is admitted, which can precede the fork, so its receipt is not used for
        # this. Every operation's teardown left nothing alive.
        agy = {(row["pid"], row["start"]) for row in receipts["completion"]["observer"]["helpers"] if row["is_agy"]}
        assert len(agy) >= 2
        for operation in ("completion", "cancel", "owner-loss"):
            observer = receipts[operation]["observer"]
            assert observer["live_namespace_members"] == [] and observer["init_exited"] is True
    elif obligation == "neg_unregistered_helper":
        # The helper policy rejected an executable; the internal stage is not pinned (A2).
        failure = failures["completion"]
        assert failure["rejected_image"]
        assert failure["reason"] == "qualification helper executable is outside the registered identity policy"
    elif obligation in ("neg_no_terminal_event", "neg_tool_step"):
        # Not vacuous: the provider ran and its record was built and REJECTED. A driver that
        # never observed the provider also ends `transient` at `completion`, so the pinned
        # outcome alone could pass without the control being exercised.
        failure = failures["completion"]
        assert (failure["stage"], failure["reason"]) == ("validation", "gemini qualification record rejected"), (
            failure.get("stage"), failure.get("reason"), run["diagnostics"])
    if obligation.startswith("neg_"):
        assert not receipts.get(expected["operation"]), "a negative control left a passing receipt"


def test_obligations_are_exactly_the_parametrized_cases():
    assert len(CONFORMANCE_OBLIGATIONS) == len(set(CONFORMANCE_OBLIGATIONS)) == 8
    assert set(EXPECTED) == set(CONFORMANCE_OBLIGATIONS)
    marks = {mark.name: mark for mark in test_obligation.pytestmark}
    assert tuple(marks["parametrize"].args[1]) == CONFORMANCE_OBLIGATIONS
    assert {mode for mode, _ in EXPECTED.values()} == set(MODES)
    assert all(outcome != PASSED for name, (_, outcome) in EXPECTED.items() if name.startswith("neg_"))
    assert all(outcome == PASSED for name, (_, outcome) in EXPECTED.items() if not name.startswith("neg_"))


# ------------------------------------------------------------------- strict mode

def test_strict_mode_fails_on_missing_bubblewrap(tmp_path):
    gap = _host_without(bwrap=str(tmp_path / "no-bwrap"))
    assert gap is not None and "bubblewrap" in gap
    with pytest.raises(pytest.fail.Exception, match=STRICT_ENV):
        require_prerequisites(gap, strict=True)
    with pytest.raises(pytest.skip.Exception):
        require_prerequisites(gap, strict=False)


def test_strict_mode_fails_on_missing_user_namespaces(tmp_path):
    fake = tmp_path / "bwrap"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    gap = _host_without(bwrap=str(fake),
                        run=lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"setting up uid map"))
    assert gap == "user namespaces are unavailable (bubblewrap probe failed)"
    with pytest.raises(pytest.fail.Exception, match=STRICT_ENV):
        require_prerequisites(gap, strict=True)


def _host_without(**missing):
    present = sys.executable  # an executable that exists everywhere this suite runs
    facts = {"bwrap": present, "setpriv": present, "helper": present, "which": lambda name: present,
             "run": lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""), "machine_id": lambda: "0" * 32,
             "caps_readiness": lambda: None}
    return prerequisite_gap(**{**facts, **missing})


def test_a_complete_host_has_no_gap():
    assert _host_without() is None


@pytest.mark.parametrize(("missing", "named"), [
    ({"which": lambda name: None}, "C compiler"),
    ({"machine_id": lambda: None}, "machine-id"),
    ({"setpriv": "/nonexistent/setpriv"}, "setpriv"),
    ({"helper": "/nonexistent/sleep"}, "helper executable"),
    ({"caps_readiness": lambda: "seat_resource_caps_unavailable"}, "per-seat resource caps"),
])
def test_strict_mode_fails_on_every_other_gap(missing, named):
    gap = _host_without(**missing)
    assert gap is not None and named in gap
    with pytest.raises(pytest.fail.Exception, match=STRICT_ENV):
        require_prerequisites(gap, strict=True)


def test_strict_flag_is_read_at_import_not_per_test():
    # The suite's autouse isolation deletes AGY_* names before each test, so a per-test read
    # would always see strict mode off and let a skip pass a release gate.
    assert STRICT_ENV not in os.environ
    assert isinstance(STRICT, bool)


# ------------------------------------------------- the controls are not vacuous

def test_ignores_cancel_stand_in_really_ignores_sigterm(tmp_path):
    require_prerequisites(prerequisite_gap(), strict=STRICT)
    binary = _build("ignores_cancel", tmp_path)
    proc = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        proc.stdin.write(b'{"event":"user","message":{"content":"x"}}\n')
        proc.stdin.flush()
        assert b'"init"' in proc.stdout.readline() and b'"step_update"' in proc.stdout.readline()
        proc.send_signal(signal.SIGTERM)
        time.sleep(0.5)
        assert proc.poll() is None, "the ignores-cancel stand-in exited on SIGTERM"
    finally:
        proc.kill()
        proc.wait(timeout=10)
