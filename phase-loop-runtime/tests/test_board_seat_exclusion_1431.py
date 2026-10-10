"""A review-board seat is never dropped silently (agent-harness#1431, agent-harness#1420).

The fault: on a host whose agy build is outside the runtime's shipped set and has no local
qualification record for this runtime, the Gemini seat's probe raised
``AgyImageUnqualified``; the probe gate swallowed it into ``False``; composition dropped
Gemini and backfilled a second Grok seat without a word; and a president-requiring tier
then refused that lineup with a bare ``review_board_policy_mismatch``. Under ``--json`` the
refusal printed nothing on stdout, and the emit arm handed out a native-fill request for a
lineup the invoke arm was certain to refuse.

Pinned here, end to end:

* the probe gate keeps WHY it failed (the typed code of a refusal, never CLI output);
* composition returns every seat it left out: the seat, a typed reason, the fix and the
  backfilled seat that replaced it;
* the CLI names each excluded seat at composition, in text and in every JSON result, and a
  tier whose policy does not accept the composed lineup is refused AT COMPOSITION -- before
  a request is emitted, a fill is preflighted or anything is staged or launched;
* ``phase-loop doctor`` says whether the agy on PATH is admitted under this runtime, and
  tells "not shipped, never qualified here" from "qualified under another runtime".

The qualification gate itself is not touched: nothing here admits an image.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from importlib.resources import files
from pathlib import Path

import jsonschema
import pytest

from phase_loop_runtime import (
    agy_integrity,
    agy_provenance,
    agy_qualification,
    cli,
    doctor,
    executor_availability as ea,
    gemini_heartbeat,
    governed_review as gr,
    panel_invoker,
    sandbox_egress,
)
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board import composition
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.capability_registry import capability_registry
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult
from phase_loop_runtime.seat_jail import NOTICES

from test_train_review_packet import synthetic_train_packet  # noqa: E402, F401 - a fixture

try:
    from phase_loop_runtime import agy_diagnosis
except ImportError:  # a tree without the diagnosis: each test fails where it needs it
    agy_diagnosis = None

GEMINI_SEAT = "gemini:gemini-3.8-flash:medium:alternative-approach"
BACKFILL = "grok:grok-4.7:high:correctness"
RUN_FIX = "run `phase-loop agy-qualification run`"
PRESIDENT_TIERS = ("plan", "production_code")


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args="probe", returncode=returncode, stdout=stdout, stderr="")


@pytest.fixture(autouse=True)
def _fresh_auth_cache():
    ea.clear_auth_cache()
    yield
    ea.clear_auth_cache()


# =============================================================================================
# 1. The probe gate keeps the reason
# =============================================================================================

def test_a_typed_refusal_raised_by_a_probe_keeps_its_code():
    def runner(_probe):
        raise agy_integrity.AgyImageUnqualified("agy_image_unqualified")

    ok, refusal = ea._probes_verdict("gemini", ("agy --version", "agy --help"), runner)
    assert ok is False
    assert refusal == ea.ProbeRefusal("raised", "agy --version", code="agy_image_unqualified",
                                      exception="AgyImageUnqualified")
    # The boolean gate is unchanged: it still fails CLOSED.
    assert ea._probes_pass("gemini", ("agy --version",), runner) is False


def test_an_exception_message_that_is_not_a_code_is_never_carried():
    def runner(_probe):
        raise OSError("[Errno 2] No such file or directory: '/home/someone/.local/bin/agy'")

    _ok, refusal = ea._probes_verdict("gemini", ("agy --version",), runner)
    assert refusal == ea.ProbeRefusal("raised", "agy --version", exception="OSError")
    assert refusal.code is None


@pytest.mark.parametrize("executor, probes, runner, kind, probe, returncode", [
    ("grok", ("grok --version", "grok --help"),
     lambda probe: _completed(0 if probe.endswith("--version") else 3),
     "nonzero_exit", "grok --help", 3),
    ("codex", ("codex --version", "codex login status"),
     lambda probe: _completed(0, "Not authenticated"),
     "not_logged_in", "codex login status", None),
    ("claude", ("claude --version", "claude auth status"),
     lambda probe: _completed(0, '{"loggedIn": false}'),
     "not_logged_in", "claude auth status", None),
])
def test_a_failing_probe_is_named_with_how_it_failed(executor, probes, runner, kind, probe, returncode):
    assert ea._probes_verdict(executor, probes, runner) == (
        False, ea.ProbeRefusal(kind, probe, returncode=returncode))


def test_a_probe_that_times_out_is_named_as_timed_out():
    def runner(probe):
        raise subprocess.TimeoutExpired(cmd=probe, timeout=ea._PROBE_TIMEOUT_SECONDS)

    assert ea._probes_verdict("claude", ("claude --version",), runner) == (
        False, ea.ProbeRefusal("timed_out", "claude --version", exception="TimeoutExpired"))


def test_passing_probes_carry_no_refusal():
    probes = ("codex --version", "codex login status")
    assert ea._probes_verdict("codex", probes, lambda _p: _completed(0, "Logged in")) == (True, None)


def test_the_cached_gate_remembers_its_refusal_and_forgets_it_when_it_passes():
    probes = ("agy --version", "agy --help")

    def refuse(_probe):
        raise agy_integrity.AgyImageUnqualified("agy_image_unqualified")

    def must_not_run(_probe):
        raise AssertionError("auth_refusal_for must never run a probe")

    assert ea.auth_refusal_for("gemini", probes) is None  # never evaluated
    assert ea.auth_ok_for("gemini", probes, now=0.0, runner=refuse) is False
    assert ea.auth_refusal_for("gemini", probes).code == "agy_image_unqualified"
    # Inside the TTL the verdict AND its refusal are the cached ones; nothing re-runs.
    assert ea.auth_ok_for("gemini", probes, now=10.0, runner=must_not_run) is False
    assert ea.auth_refusal_for("gemini", probes).code == "agy_image_unqualified"
    # Another probe set for the same executor has its own verdict.
    assert ea.auth_refusal_for("gemini", ("agy --version",)) is None
    # After the TTL the gate passes: the old refusal must not outlive it.
    assert ea.auth_ok_for("gemini", probes, now=1000.0, runner=lambda _p: _completed(0)) is True
    assert ea.auth_refusal_for("gemini", probes) is None


# =============================================================================================
# 2. Composition returns what it left out
# =============================================================================================

def _compose(up, authed=None):
    kwargs = {"is_available": lambda vendor: vendor in up}
    if authed is not None:
        kwargs["auth_ok"] = lambda vendor: vendor in authed
    return composition.compose_review_board_report(**kwargs)


def test_a_vendor_whose_cli_is_absent_is_returned_as_an_excluded_seat():
    composed = _compose({"grok", "claude", "codex"})
    assert [seat.seat_key for seat in composed.board.seats][-1] == BACKFILL
    (excluded,) = composed.excluded
    assert excluded.vendor == "gemini"
    assert excluded.seat_key == GEMINI_SEAT
    assert excluded.code == composition.SEAT_CLI_NOT_ON_PATH
    assert "`agy`" in excluded.why and "`agy`" in excluded.fix
    assert excluded.replaced_by == BACKFILL
    assert excluded.as_json() == {
        "vendor": "gemini", "seat_key": GEMINI_SEAT, "code": composition.SEAT_CLI_NOT_ON_PATH,
        "why": excluded.why, "fix": excluded.fix, "replaced_by": BACKFILL,
    }
    rendered = excluded.render()
    for part in (GEMINI_SEAT, composition.SEAT_CLI_NOT_ON_PATH, excluded.fix, BACKFILL):
        assert part in rendered


def test_the_board_is_the_one_compose_review_board_returns():
    up = {"grok", "claude", "codex"}
    board = composition.compose_review_board(is_available=lambda vendor: vendor in up)
    assert board == _compose(up).board


def test_an_unauthenticated_vendor_under_an_injected_gate_is_excluded_generically():
    composed = _compose({"grok", "claude", "codex", "gemini"}, authed={"claude", "codex", "gemini"})
    (excluded,) = composed.excluded
    assert (excluded.vendor, excluded.code) == ("grok", composition.SEAT_UNAUTHENTICATED)
    assert excluded.seat_key == "grok:grok-4.7:high:adversarial"


def test_a_full_board_excludes_nothing():
    composed = _compose({"grok", "claude", "codex", "gemini"})
    assert composed.excluded == ()
    assert len({seat.harness for seat in composed.board.seats}) == 4


def test_each_excluded_vendor_is_paired_with_the_seat_that_replaced_it():
    composed = _compose({"claude", "codex"})
    backfilled = [seat.seat_key for seat in composed.board.seats[2:]]
    assert len(backfilled) == 2
    assert [(seat.vendor, seat.replaced_by) for seat in composed.excluded] == [
        ("grok", backfilled[0]), ("gemini", backfilled[1])]


def test_an_empty_board_still_names_every_vendor_it_could_not_seat():
    composed = _compose(set())
    assert composed.board.seats == ()
    assert [seat.vendor for seat in composed.excluded] == ["grok", "claude", "codex", "gemini"]
    assert {seat.replaced_by for seat in composed.excluded} == {None}


def test_exclusions_are_found_by_the_board_they_belong_to_and_by_no_other():
    composed = _compose({"grok", "claude", "codex"})
    assert composition.composition_exclusions(composed.board) == composed.excluded
    # An EQUAL board that is another object inherits nothing: not a fixture, not a copy.
    assert composition.composition_exclusions(dataclasses.replace(composed.board)) == ()
    assert composition.composition_exclusions(DEFAULT_BOARD) == ()
    # A later composition is the latest one; the earlier board's are no longer claimed.
    later = _compose({"grok", "claude", "codex", "gemini"})
    assert composition.composition_exclusions(later.board) == ()
    assert composition.composition_exclusions(composed.board) == ()


def _seed_default_gate(monkeypatch, runners):
    """Evaluate the REAL default gate for every board vendor with a canned probe runner.

    ``default_board_auth_ok`` reaches ``auth_ok_for`` through the capability registry's own
    closure and probe tuples; seeding its cache through that same function is what a real
    probe run leaves behind, without starting a vendor CLI."""
    passing = lambda _probe: _completed(0, 'logged in {"loggedIn": true}')  # noqa: E731
    for vendor in ("grok", "claude", "codex", "gemini"):
        probes = capability_registry()[vendor].auth_preflight_probes
        ea.auth_ok_for(vendor, probes, runner=runners.get(vendor, passing))


def _compose_through_the_default_gate():
    backing.prepare_review_composition_authorization()
    try:
        return composition.compose_review_board_report(
            is_available=lambda _vendor: True, auth_ok=composition.default_board_auth_ok)
    finally:
        backing.clear_review_composition_authorization()


def test_the_default_gate_reports_each_vendors_own_reason(monkeypatch, tmp_path):
    _isolate_agy(monkeypatch, tmp_path)

    def unqualified(_probe):
        raise agy_integrity.AgyImageUnqualified("agy_image_unqualified")

    def timed_out(probe):
        raise subprocess.TimeoutExpired(cmd=probe, timeout=1)

    _seed_default_gate(monkeypatch, {
        "gemini": unqualified,
        "codex": lambda probe: _completed(0, "Not authenticated"),
        "grok": lambda probe: _completed(0 if probe.endswith("--version") else 7),
        "claude": timed_out,
    })
    composed = _compose_through_the_default_gate()
    assert composed.board.seats == ()
    by_vendor = {seat.vendor: seat for seat in composed.excluded}
    assert by_vendor["gemini"].code == "agy_image_unqualified"
    assert by_vendor["gemini"].fix == RUN_FIX
    assert "not in this runtime's shipped set" in by_vendor["gemini"].why
    assert by_vendor["codex"].code == composition.SEAT_NOT_LOGGED_IN
    assert "codex login status" in by_vendor["codex"].why
    assert by_vendor["grok"].code == composition.SEAT_PROBE_FAILED
    assert "`grok --help`" in by_vendor["grok"].why and "(exit 7)" in by_vendor["grok"].why
    assert by_vendor["claude"].code == composition.SEAT_PROBE_TIMED_OUT
    assert "`claude --version`" in by_vendor["claude"].why


def test_a_typed_seat_refusal_keeps_its_code_and_the_notice_tables_own_text(monkeypatch):
    def refused(_probe):
        raise sandbox_egress.SeatIdentityUnverified("seat_profile_unavailable")

    _seed_default_gate(monkeypatch, {"codex": refused})
    composed = _compose_through_the_default_gate()
    (excluded,) = composed.excluded
    _what, why, fix = NOTICES["seat_profile_unavailable"]
    assert (excluded.vendor, excluded.code, excluded.why, excluded.fix) == (
        "codex", "seat_profile_unavailable", why, fix)


def test_a_raised_refusal_with_no_notice_names_its_exception_not_its_message(monkeypatch):
    def broke(_probe):
        raise RuntimeError("secret-looking detail /home/someone/.config")

    _seed_default_gate(monkeypatch, {"grok": broke})
    composed = _compose_through_the_default_gate()
    (excluded,) = composed.excluded
    assert excluded.code == composition.SEAT_PROBE_FAILED
    assert "RuntimeError" in excluded.why and "secret-looking" not in excluded.why


# =============================================================================================
# 3. The agy diagnosis: real images, a real store, the real admission gate
# =============================================================================================

MACHINE = "ab" * 16
OTHER_RUNTIME = {"version": "0.0.1", "route_core": {name: "0" * 64 for name in agy_qualification.ROUTE_CORE}}


def _fake_agy(directory: Path, body: str = "unshipped build") -> tuple[Path, str]:
    """An executable named ``agy`` that is not any shipped build. Returns (path, sha256)."""
    from hashlib import sha256

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "agy"
    data = f"#!/bin/sh\n# {body}\nexit 0\n".encode()
    path.write_bytes(data)
    path.chmod(0o755)
    return path, sha256(data).hexdigest()


def _isolate_agy(monkeypatch, tmp_path: Path) -> tuple[Path, str, "agy_qualification.Store"]:
    """A host with one unshipped agy first on PATH, an empty per-user store and no user
    board config. Every fact the diagnosis and the admission gate read is real."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    path, digest = _fake_agy(tmp_path / "bin")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("PATH", f"{path.parent}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setattr(agy_qualification, "read_machine_id", lambda path="/etc/machine-id": MACHINE)
    monkeypatch.setattr(panel_invoker, "_PROVIDER_SEARCH_PATH", os.environ["PATH"])
    monkeypatch.setattr(agy_integrity, "_PROVIDER_SEARCH_PATH", os.environ["PATH"])
    return path, digest, agy_qualification.Store()


def _host():
    return agy_provenance.detect_platform()


def _asset(release: str) -> agy_provenance.ReleaseAsset:
    fields = {field.name for field in dataclasses.fields(agy_provenance.ReleaseAsset)}
    values = {"name": f"agy-{release}.tar.gz", "version": release, "digest": "d" * 64,
              "url": "https://example.invalid/asset", "size": 1}
    return agy_provenance.ReleaseAsset(**{key: value for key, value in values.items() if key in fields})


def _qualify(store, digest: str, runtime, release: str = "9.9.9") -> None:
    """What a successful first use leaves in the store for ``runtime``: the member cache
    (which image a release is) and the qualified entry. Written by the store itself."""
    host = _host()
    store.create()
    store.put_member(_asset(release), digest, host, runtime)
    store.put_qualified(digest, "e" * 64, host, runtime, release)


def _really_refused(path: Path) -> bool:
    """The REAL seat admission for this image, with this process's environment."""
    try:
        agy_integrity.admit_for_seat(str(path), dict(os.environ)).close()
    except agy_integrity.AgyImageUnqualified:
        return True
    return False


def test_an_unshipped_build_with_no_record_is_not_qualified(monkeypatch, tmp_path):
    path, _digest, _store = _isolate_agy(monkeypatch, tmp_path)
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.NOT_QUALIFIED
    assert not diagnosis.admitted
    assert diagnosis.fix == RUN_FIX
    assert "not in this runtime's shipped set" in diagnosis.detail
    assert "no local qualification record" in diagnosis.detail
    assert _really_refused(path), "the diagnosis says not admitted; the real gate must agree"


def test_a_record_made_under_another_runtime_is_told_apart(monkeypatch, tmp_path):
    """agent-harness#1420 section 1: the host qualified this very build, under another
    runtime. The runtime upgrade left this runtime with no record."""
    path, digest, store = _isolate_agy(monkeypatch, tmp_path)
    _qualify(store, digest, OTHER_RUNTIME, release="1.3.2")
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.LOCAL_RECORD_OTHER_RUNTIME
    assert diagnosis.release == "1.3.2"
    assert diagnosis.fix == RUN_FIX
    assert "agy 1.3.2 under a different runtime" in diagnosis.detail
    assert "runtime upgrade" in diagnosis.detail
    assert _really_refused(path), "a record for another runtime admits nothing under this one"


def test_a_record_for_a_different_build_does_not_read_as_this_builds_record(monkeypatch, tmp_path):
    _path, _digest, store = _isolate_agy(monkeypatch, tmp_path)
    _qualify(store, "f" * 64, OTHER_RUNTIME, release="1.3.1")  # some other image
    assert agy_diagnosis.diagnose().status == agy_diagnosis.NOT_QUALIFIED


def test_another_builds_record_is_not_this_builds_even_when_this_build_is_a_known_release(
        monkeypatch, tmp_path):
    """The host resolved WHICH release this image is (the member cache) but qualified only a
    different release. That is "never qualified here", not "qualified under another runtime"."""
    _path, digest, store = _isolate_agy(monkeypatch, tmp_path)
    _qualify(store, "f" * 64, OTHER_RUNTIME, release="1.3.1")
    store.put_member(_asset("1.3.3"), digest, _host(), OTHER_RUNTIME)
    diagnosis = agy_diagnosis.diagnose()
    assert (diagnosis.status, diagnosis.release) == (agy_diagnosis.NOT_QUALIFIED, "1.3.3")


def test_a_record_under_this_runtime_is_reported_as_locally_qualified(monkeypatch, tmp_path):
    _path, digest, store = _isolate_agy(monkeypatch, tmp_path)
    _qualify(store, digest, agy_qualification.runtime_identity(), release="1.3.3")
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.LOCALLY_QUALIFIED
    assert diagnosis.admitted and diagnosis.fix is None and diagnosis.note is None
    # The record the diagnosis found is the one the store itself reads back under the live key.
    assert store.get_qualified(digest, "e" * 64, _host(), agy_qualification.runtime_identity())


def test_a_failed_qualification_is_reported_as_failed(monkeypatch, tmp_path):
    path, digest, store = _isolate_agy(monkeypatch, tmp_path)
    store.create()
    store.put_failed(digest, "e" * 64, _host(), agy_qualification.runtime_identity(),
                     "completion", "qualification_failed")
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.LOCAL_QUALIFICATION_FAILED
    assert "agy-qualification clear" in diagnosis.fix
    assert _really_refused(path)


def test_the_opt_out_is_reported_as_the_opt_out(monkeypatch, tmp_path):
    path, _digest, _store = _isolate_agy(monkeypatch, tmp_path)
    from phase_loop_runtime.advisor_board.schema import board_config_path

    config = board_config_path()
    assert tmp_path in config.parents
    config.parent.mkdir(parents=True)
    config.write_text("[agy]\nself_qualification = false\n", encoding="utf-8")
    assert agy_qualification.self_qualification_enabled() is False, "the fixture must reach the real config"
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.SELF_QUALIFICATION_DISABLED
    assert "[agy] self_qualification" in diagnosis.fix
    assert _really_refused(path)


def test_an_unsafe_store_is_reported_as_unsafe(monkeypatch, tmp_path):
    path, _digest, store = _isolate_agy(monkeypatch, tmp_path)
    store.create()
    store.root.chmod(0o755)
    try:
        assert agy_diagnosis.diagnose().status == agy_diagnosis.STORE_UNSAFE
        assert _really_refused(path)
    finally:
        store.root.chmod(0o700)


def test_a_shipped_build_is_release_qualified_and_needs_nothing(monkeypatch, tmp_path):
    path, digest, _store = _isolate_agy(monkeypatch, tmp_path)
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES, digest, "e" * 64)
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.RELEASE_QUALIFIED
    assert diagnosis.admitted and diagnosis.fix is None
    assert not _really_refused(path)


def test_no_agy_on_path_is_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    diagnosis = agy_diagnosis.diagnose()
    assert diagnosis.status == agy_diagnosis.ABSENT and not diagnosis.admitted


def test_a_shipped_build_later_on_path_is_named_without_a_path(monkeypatch, tmp_path):
    first, _digest, _store = _isolate_agy(monkeypatch, tmp_path)
    _second, shipped_digest = _fake_agy(tmp_path / "older", body="a shipped build")
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES, shipped_digest, "e" * 64)
    search = os.pathsep.join([str(first.parent), str(tmp_path / "older"), "/usr/bin"])
    diagnosis = agy_diagnosis.diagnose(search_path=search)
    assert diagnosis.status == agy_diagnosis.NOT_QUALIFIED
    assert diagnosis.shipped_build_later_on_path is True
    assert "also on PATH" in diagnosis.note and "first on PATH" in diagnosis.note
    assert str(tmp_path) not in json.dumps(diagnosis.as_json())
    # With no second build the note says how to check, and claims nothing.
    alone = agy_diagnosis.diagnose(search_path=str(first.parent))
    assert alone.shipped_build_later_on_path is False
    assert "re-running `phase-loop doctor`" in alone.note


def test_the_statuses_the_diagnosis_can_return_are_the_schemas(monkeypatch, tmp_path):
    schema = json.loads((files("phase_loop_runtime") / "schemas"
                         / "phase-loop-doctor.v1.schema.json").read_text())
    enum = schema["properties"]["seat_cli_qualification"]["items"]["properties"]["status"]["enum"]
    assert sorted(enum) == sorted(agy_diagnosis.STATUSES)


# --- the real gathering path: no stubbed fact between PATH and the excluded seat -------------

def test_the_real_probe_of_an_unshipped_agy_raises_the_typed_refusal(monkeypatch, tmp_path):
    """``executor_availability._run_probe`` itself, through the seat-launch owner, on a real
    file that is not a shipped build. Nothing is stubbed: this is the line where the reason
    used to be lost."""
    _isolate_agy(monkeypatch, tmp_path)
    with pytest.raises(agy_integrity.AgyImageUnqualified, match="agy_image_unqualified"):
        ea._run_probe("agy --version")


def test_a_bare_composition_on_a_host_with_an_unshipped_agy_explains_the_gemini_seat(
        monkeypatch, tmp_path):
    """The whole real path: PATH probe, capability registry, cached probe gate, the seat
    admission, the store and the diagnosis. Only the host is arranged (one unshipped agy on
    PATH, an empty store)."""
    _isolate_agy(monkeypatch, tmp_path)
    backing.prepare_review_composition_authorization()
    try:
        composed = composition.compose_review_board_report()
    finally:
        backing.clear_review_composition_authorization()
    seated = {seat.harness for seat in composed.board.seats}
    by_vendor = {seat.vendor: seat for seat in composed.excluded}
    assert "gemini" not in seated
    assert by_vendor["gemini"].seat_key == GEMINI_SEAT
    assert by_vendor["gemini"].code == "agy_image_unqualified"
    assert by_vendor["gemini"].fix == RUN_FIX
    assert "no local qualification record" in by_vendor["gemini"].why
    # Every board vendor is either seated or explained; none is simply missing.
    assert seated | set(by_vendor) == {"grok", "claude", "codex", "gemini"}
    assert not seated & set(by_vendor)


# =============================================================================================
# 4. The advisor-board CLI
# =============================================================================================

_REAL_COMPOSE = composition.compose_review_board


def _artifact(tmp_path: Path) -> Path:
    artifact = tmp_path / "bundle.md"
    artifact.write_text("# bundle\nreview me\n", encoding="utf-8")
    return artifact


def _cli(monkeypatch, tmp_path, up, argv, *, result=None, under_claude_code=False):
    """Run ``advisor-board`` with the REAL composer over an arranged availability, the real
    tier policy and the real policy check; only the mint and the seat launches are stubbed.
    Whether the driving session is Claude Code is set here, never inherited from the shell
    that runs the tests. Returns (rc, invoke calls, mint calls)."""
    invoked: list[dict] = []
    minted: list[object] = []
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(name, raising=False)
    if under_claude_code:
        monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(composition, "compose_review_board",
                        lambda: _REAL_COMPOSE(is_available=lambda vendor: vendor in up))
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization",
                        lambda *a, **k: minted.append(a) or None)

    def fake_invoke(board, artifact, **kwargs):
        invoked.append({"board": board, **kwargs})
        return result if result is not None else PanelResult(legs=tuple(
            PanelLegResult(leg=seat.harness, status="OK", text="fine\nAGREE", seat_key=seat.seat_key)
            for seat in board.seats))

    monkeypatch.setattr(panel_invoker, "invoke_board", fake_invoke)
    rc = cli.main(["advisor-board", str(_artifact(tmp_path)), *argv])
    return rc, invoked, minted


THREE = {"grok", "claude", "codex"}
FOUR = THREE | {"gemini"}


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_a_tier_that_needs_the_dropped_seat_is_refused_at_composition(monkeypatch, tmp_path, capsys, tier):
    rc, invoked, minted = _cli(monkeypatch, tmp_path, THREE, ["--landing-tier", tier])
    captured = capsys.readouterr()
    assert rc == 2
    assert invoked == [] and minted == [], "nothing may be staged, minted or launched"
    notice, refusal = [line for line in captured.err.splitlines() if line.startswith("advisor-board:")]
    assert notice.startswith(f"advisor-board: composition: {GEMINI_SEAT} excluded "
                             f"[{composition.SEAT_CLI_NOT_ON_PATH}]:")
    assert "fix: install the `agy` CLI on PATH" in notice and BACKFILL in notice
    assert refusal.startswith("advisor-board: refused at composition [review_board_policy_mismatch]: "
                              f"the {tier} landing tier does not accept this lineup")
    # The refusal that results from the drop names the seat, the typed reason and the fix.
    for part in (GEMINI_SEAT, composition.SEAT_CLI_NOT_ON_PATH, "fix: install the `agy` CLI on PATH"):
        assert part in refusal
    assert "president refused" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_the_refusal_is_also_the_json_result(monkeypatch, tmp_path, capsys, tier):
    rc, invoked, _minted = _cli(monkeypatch, tmp_path, THREE, ["--landing-tier", tier, "--json"])
    captured = capsys.readouterr()
    assert rc == 2 and invoked == []
    payload = json.loads(captured.out)
    assert payload["usable"] is False and payload["status"] == "UNAVAILABLE"
    assert payload["refusal"]["stage"] == "composition"
    assert payload["refusal"]["code"] == "review_board_policy_mismatch"
    assert payload["refusal"]["landing_tier"] == tier
    assert GEMINI_SEAT in payload["refusal"]["detail"]
    assert payload["composition"]["seats"][-1] == BACKFILL
    (excluded,) = payload["composition"]["excluded"]
    assert excluded == {"vendor": "gemini", "seat_key": GEMINI_SEAT,
                        "code": composition.SEAT_CLI_NOT_ON_PATH,
                        "why": "the `agy` CLI is not on PATH",
                        "fix": "install the `agy` CLI on PATH, then re-run",
                        "replaced_by": BACKFILL}


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_no_native_fill_request_is_emitted_for_a_lineup_the_tier_refuses(monkeypatch, tmp_path, capsys, tier):
    """The original agent-harness#1431 sequence: the emit arm ran first and handed out a
    request, and the board was refused only after the operator had filled the seat."""
    fill_dir = tmp_path / "fills"
    rc, invoked, _minted = _cli(
        monkeypatch, tmp_path, THREE,
        ["--emit-native-request", "--native-fill-dir", str(fill_dir), "--landing-tier", tier],
        under_claude_code=True)
    assert rc == 2 and invoked == []
    assert not fill_dir.exists(), "no request may be written for a lineup the tier refuses"
    assert "refused at composition [review_board_policy_mismatch]" in capsys.readouterr().err


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_the_default_composition_satisfies_each_president_tiers_own_policy(monkeypatch, tmp_path, capsys, tier):
    """With every vendor up, the composer's own lineup is the one the tier's policy asks
    for: the real composer, the real policy, the real check."""
    rc, invoked, _minted = _cli(monkeypatch, tmp_path, FOUR, ["--landing-tier", tier, "--json"])
    captured = capsys.readouterr()
    assert "refused at composition" not in captured.err
    assert len(invoked) == 1 and invoked[0]["landing_tier"] == tier
    board = invoked[0]["board"]
    panel_invoker._validate_review_board_policy(board, panel_invoker.review_policy_for_tier(tier), None)
    assert rc in (0, 1)


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
def test_a_full_board_still_gets_its_native_fill_request_under_a_tier(monkeypatch, tmp_path, capsys, tier):
    """The sequence the agent-harness#1431 reporter ran, on a host where every vendor is up:
    the tier check at composition lets the emit arm through."""
    fill_dir = tmp_path / "fills"
    rc, invoked, _minted = _cli(
        monkeypatch, tmp_path, FOUR,
        ["--emit-native-request", "--native-fill-dir", str(fill_dir), "--landing-tier", tier, "--json"],
        under_claude_code=True)
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert rc == 0 and invoked == [] and record["status"] == "native_fill_requested"
    assert record["composition_excluded"] == [] and Path(record["request_path"]).is_file()
    assert "refused at composition" not in captured.err


def test_the_diagnosis_explains_the_agy_the_probe_resolved(monkeypatch, tmp_path):
    """The refused probe found agy on the seat owner's search path, fixed when the runtime
    was imported. The reason given is about THAT binary even if this process's PATH has
    since changed to one with no agy at all."""
    _isolate_agy(monkeypatch, tmp_path)

    def unqualified(_probe):
        raise agy_integrity.AgyImageUnqualified("agy_image_unqualified")

    _seed_default_gate(monkeypatch, {"gemini": unqualified})
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no agy here; the owner's path still has it
    (excluded,) = _compose_through_the_default_gate().excluded
    assert excluded.code == "agy_image_unqualified" and excluded.fix == RUN_FIX
    assert "not in this runtime's shipped set" in excluded.why


def test_a_tierless_board_proceeds_and_says_which_seat_it_left_out(monkeypatch, tmp_path, capsys):
    rc, invoked, _minted = _cli(monkeypatch, tmp_path, THREE, [])
    captured = capsys.readouterr()
    assert rc == 0 and len(invoked) == 1
    assert f"advisor-board: composition: {GEMINI_SEAT} excluded [{composition.SEAT_CLI_NOT_ON_PATH}]" in captured.err
    # And again with the result, on stdout, where the verdicts are read.
    assert f"  [EXCLUDED] {GEMINI_SEAT} excluded [{composition.SEAT_CLI_NOT_ON_PATH}]" in captured.out


def test_a_tierless_json_result_carries_the_composition(monkeypatch, tmp_path, capsys):
    rc, _invoked, _minted = _cli(monkeypatch, tmp_path, THREE, ["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["usable"] is True
    assert payload["composition"]["seats"] == [leg["seat_key"] for leg in payload["legs"]]
    assert [seat["seat_key"] for seat in payload["composition"]["excluded"]] == [GEMINI_SEAT]
    assert payload["independence"]["level"] == "degraded"


def test_a_full_board_reports_an_empty_exclusion_list(monkeypatch, tmp_path, capsys):
    rc, _invoked, _minted = _cli(monkeypatch, tmp_path, FOUR, ["--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0 and payload["composition"]["excluded"] == []
    assert "composition:" not in captured.err


def test_a_tierless_native_fill_request_names_the_excluded_seat(monkeypatch, tmp_path, capsys):
    fill_dir = tmp_path / "fills"
    rc, _invoked, _minted = _cli(
        monkeypatch, tmp_path, THREE,
        ["--emit-native-request", "--native-fill-dir", str(fill_dir), "--json"],
        under_claude_code=True)
    record = json.loads(capsys.readouterr().out)
    assert rc == 0 and record["status"] == "native_fill_requested"
    assert [seat["seat_key"] for seat in record["composition_excluded"]] == [GEMINI_SEAT]
    request = json.loads(Path(record["request_path"]).read_text())
    assert request["composition_excluded"] == record["composition_excluded"]
    assert BACKFILL in request["composition"]
    # The request still loads as a fill request.
    review = Path(record["request_path"]).parent / "review.md"
    review.write_text("Reviewed.\nAGREE\n", encoding="utf-8")
    fill = panel_invoker.load_native_leg_fill(Path(record["request_path"]), review)
    assert fill.seat_key == record["seat_key"] and fill.request_id == record["request_id"]


def test_an_empty_board_is_refused_with_every_vendors_reason(monkeypatch, tmp_path, capsys):
    rc, invoked, _minted = _cli(monkeypatch, tmp_path, set(), ["--json"])
    captured = capsys.readouterr()
    assert rc == 2 and invoked == []
    payload = json.loads(captured.out)
    assert payload["refusal"]["code"] == "review_board_no_seats"
    assert [seat["vendor"] for seat in payload["composition"]["excluded"]] == [
        "grok", "claude", "codex", "gemini"]
    assert captured.err.count("advisor-board: composition:") == 4
    assert "nothing to compose" in captured.err


# --- the policy refusal, for a caller that is not the CLI ------------------------------------

def test_the_policy_refusal_names_the_excluded_seat_for_any_caller():
    composed = _compose(THREE)
    policy = panel_invoker.review_policy_for_tier("production_code")
    with pytest.raises(panel_invoker.PresidentPolicyError) as refused:
        panel_invoker._validate_review_board_policy(composed.board, policy, None)
    assert refused.value.code == "review_board_policy_mismatch"
    message = str(refused.value)
    assert message.startswith(
        "review board seats {'grok': 2, 'fable': 1, 'sol': 1} do not match policy "
        "{'fable': 1, 'sol': 1, 'gemini': 1, 'grok': 1}; ")
    assert (f"{GEMINI_SEAT} was excluded at composition [{composition.SEAT_CLI_NOT_ON_PATH}] "
            "-- fix: install the `agy` CLI on PATH, then re-run") in message


def test_a_mismatch_that_composition_did_not_cause_keeps_the_plain_message():
    # The same seats, but not the board a composition returned.
    board = dataclasses.replace(
        composition.compose_review_board(is_available=lambda vendor: vendor in THREE))
    policy = panel_invoker.review_policy_for_tier("plan")
    with pytest.raises(panel_invoker.PresidentPolicyError) as refused:
        panel_invoker._validate_review_board_policy(board, policy, None)
    assert str(refused.value) == (
        "review board seats {'grok': 2, 'fable': 1, 'sol': 1} do not match policy "
        "{'fable': 1, 'sol': 1, 'gemini': 1, 'grok': 1}")


_VENDORS = ("grok", "claude", "codex", "gemini")
_PARTIAL_AVAILABILITY = [
    frozenset(vendor for bit, vendor in enumerate(_VENDORS) if mask >> bit & 1)
    for mask in range(1, 2 ** len(_VENDORS) - 1)
]


@pytest.mark.parametrize("tier", PRESIDENT_TIERS)
@pytest.mark.parametrize("up", _PARTIAL_AVAILABILITY, ids=lambda up: "+".join(sorted(up)))
def test_no_backfilled_board_reaches_a_president(tier, up):
    """Every composition that left a seat out is refused by each president-requiring tier's
    policy, so a president is never asked to rule on a backfilled board. (If a policy ever
    accepts one, the president's request must name the excluded seats too.)"""
    composed = _compose(up)
    assert composed.excluded and len(composed.board.seats) == 4
    with pytest.raises(panel_invoker.PresidentPolicyError) as refused:
        panel_invoker._validate_review_board_policy(
            composed.board, panel_invoker.review_policy_for_tier(tier), None)
    assert refused.value.code == "review_board_policy_mismatch"
    for excluded in composed.excluded:
        assert f"{excluded.seat_key} was excluded at composition [{excluded.code}]" in str(refused.value)


def test_the_policy_itself_is_unchanged():
    for tier in PRESIDENT_TIERS:
        policy = panel_invoker.review_policy_for_tier(tier)
        assert policy.required_seats == ("fable", "sol", "gemini", "grok")
        assert policy.requires_president is True


# =============================================================================================
# 5. The governed gate
# =============================================================================================

def _canonical_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "canonical"
    repo.mkdir()
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t.com"),
                 ("config", "user.name", "T"), ("config", "commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    return repo.resolve()


def test_a_governed_hold_below_the_floor_names_the_seats_composition_left_out(tmp_path, monkeypatch, capsys):
    repo = _canonical_repo(tmp_path)
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not mint")))
    gate = gr.governed_board_gate(
        artifact="bundle", author_executor="claude", run_mode="governed",
        canonical_repo_authority=repo,
        compose=lambda: _REAL_COMPOSE(is_available=lambda vendor: vendor == "claude"),
        invoke=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not invoke")),
    )
    assert not gate.promoted and gate.reason == "no_disjoint_reviewer"
    hold = gate.findings[0].reason
    for vendor_cli in ("`grok`", "`codex`", "`agy`"):
        assert vendor_cli in hold
    assert composition.SEAT_CLI_NOT_ON_PATH in hold and GEMINI_SEAT in hold
    warned = [finding for finding in gate.findings if finding.severity == "warn"]
    assert [finding.code for finding in warned] == [composition.SEAT_CLI_NOT_ON_PATH] * 3
    assert capsys.readouterr().err.count("governed board: composition:") == 3


def test_a_governed_review_on_a_backfilled_board_carries_the_exclusion(tmp_path, monkeypatch, capsys):
    repo = _canonical_repo(tmp_path)
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", lambda *a, **k: object())

    def invoke(board, _artifact_text, **_kwargs):
        return PanelResult(legs=[
            PanelLegResult(leg=seat.harness, status="OK", text="Reviewed.\nAGREE") for seat in board.seats])

    gate = gr.governed_board_gate(
        artifact="bundle", author_executor="train-coordinator", run_mode="governed",
        canonical_repo_authority=repo,
        compose=lambda: _REAL_COMPOSE(is_available=lambda vendor: vendor in THREE),
        invoke=invoke,
    )
    assert gate.ran and gate.promoted, "a non-gating notice must not hold the gate"
    (warned,) = [finding for finding in gate.findings if finding.code == composition.SEAT_CLI_NOT_ON_PATH]
    assert warned.severity == "warn" and GEMINI_SEAT in warned.reason
    assert f"governed board: composition: {GEMINI_SEAT} excluded" in capsys.readouterr().err


@pytest.mark.usefixtures("synthetic_train_packet")
def test_a_train_fill_refused_below_the_floor_names_the_seats_composition_left_out(tmp_path, monkeypatch):
    """The train's cache-reuse path composes only to validate a native fill; when that
    board is below the floor, the refusal says which seats were left out and why."""
    from phase_loop_runtime.train_roadmap import parse_train_roadmap
    from phase_loop_runtime.train_runner import run_train
    from test_train_prebuilt import PREBUILT_1NODE_MD
    from test_train_review_authorization import ADMITTED, _ledger, _pr_is_open_true, _preflight_pass

    def never(*_a, **_k):
        raise AssertionError("the refused run must not publish, merge or review")

    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(composition, "compose_review_board",
                        lambda *a, **k: _REAL_COMPOSE(is_available=lambda vendor: vendor in FOUR))
    roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
    workspaces = {node.node_id: tmp_path / node.repo for node in roadmap.nodes}

    def train(ledger, **extra):
        return run_train(
            roadmap, ledger, run_mode="governed",
            resolve_workspace=lambda node: workspaces[node.node_id],
            _run_loop=lambda *a, **kw: (None, []), _publish=never,
            _set_upstream_ref_fn=lambda *a, **kw: [], _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true, _live_pr_head_sha_fn=lambda ws, br: ADMITTED,
            _workspace_head_fn=lambda ws: ADMITTED, _is_ancestor_fn=lambda ws, a, b: True,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"], _merge_phase_enabled=True,
            review_only=True, _merge_pr_fn=never,
            _reverify_fn=lambda *a, **k: True,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            **extra,
        )

    ledger = _ledger(tmp_path)
    emitted = train(ledger, emit_native_request=True)
    assert emitted["status"] == "native_fill_requested", emitted
    request_path = Path(emitted["request_path"])
    (request_path.parent / "claude.md").write_text("Reviewed the train.\nAGREE\n")
    fill = panel_invoker.load_native_leg_fill(request_path, request_path.parent / "claude.md")
    board = _REAL_COMPOSE(is_available=lambda vendor: vendor in FOUR)
    approved = PanelResult(legs=tuple(
        PanelLegResult(leg=seat.harness, status="OK", text="Reviewed.\nAGREE", seat_key=seat.seat_key)
        for seat in board.seats))
    monkeypatch.setattr(gr, "governed_board_gate",
                        lambda **kw: gr.GateResult(ran=True, promoted=True, panel=approved))
    assert train(ledger, native_leg_fills=[fill])["status"] == "review_approved"

    # The approval is cached. Now no vendor is available when the fill is re-validated.
    monkeypatch.setattr(composition, "compose_review_board",
                        lambda *a, **k: _REAL_COMPOSE(is_available=lambda _vendor: False))
    halted = train(ledger, native_leg_fills=[fill], _train_review_fn=never)
    assert (halted["status"], halted["reason"]) == ("review_halted", "native_fill_refused")
    assert "composed board below floor" in halted["detail"]
    for vendor_seat in ("grok:grok-4.7:high:adversarial", GEMINI_SEAT):
        assert f"{vendor_seat} excluded [{composition.SEAT_CLI_NOT_ON_PATH}]" in halted["detail"]


# =============================================================================================
# 6. phase-loop doctor
# =============================================================================================

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _doctor_schema() -> dict:
    return json.loads((files("phase_loop_runtime") / "schemas" / "phase-loop-doctor.v1.schema.json").read_text())


def _doctor_report(monkeypatch) -> dict:
    """The real report; only the worktree scan (minutes on a host with hundreds of
    worktrees, and nothing to do with this section) is replaced by its documented empty form."""
    monkeypatch.setattr(doctor, "build_worktree_divergence", lambda _repo: {
        "base_ref": "origin/main", "worktree_count": 0, "max_commits_ahead": 0,
        "threshold": 20, "verdict": "ok"})
    return doctor.build_doctor_report(PACKAGE_ROOT, fetch=lambda url: None)


def test_doctor_says_agy_is_present_but_not_qualified_for_this_runtime(monkeypatch, tmp_path, capsys):
    _path, digest, store = _isolate_agy(monkeypatch, tmp_path)
    _qualify(store, digest, OTHER_RUNTIME, release="1.3.2")
    report = _doctor_report(monkeypatch)
    jsonschema.validate(report, _doctor_schema())
    (row,) = report["seat_cli_qualification"]
    assert (row["harness"], row["cli"], row["status"]) == ("gemini", "agy", "local_record_other_runtime")
    assert row["fix"] == RUN_FIX and row["release"] == "1.3.2"
    assert str(tmp_path) not in json.dumps(report)
    doctor._print_doctor(report)
    printed = capsys.readouterr().out
    assert "agy present but not qualified for this runtime" in printed
    assert f"fix: {RUN_FIX}" in printed
    assert "agy 1.3.2 under a different runtime" in printed


def test_doctor_tells_never_qualified_from_qualified_under_another_runtime(monkeypatch, tmp_path):
    _path, digest, store = _isolate_agy(monkeypatch, tmp_path)
    (never,) = _doctor_report(monkeypatch)["seat_cli_qualification"]
    _qualify(store, digest, OTHER_RUNTIME)
    (other,) = _doctor_report(monkeypatch)["seat_cli_qualification"]
    assert (never["status"], other["status"]) == ("not_qualified", "local_record_other_runtime")
    assert never["fix"] == other["fix"] == RUN_FIX
    assert never["detail"] != other["detail"]


def test_doctor_reports_an_admitted_agy_without_a_fix(monkeypatch, tmp_path, capsys):
    _path, digest, _store = _isolate_agy(monkeypatch, tmp_path)
    monkeypatch.setitem(gemini_heartbeat.QUALIFIED_IMAGES, digest, "e" * 64)
    report = _doctor_report(monkeypatch)
    jsonschema.validate(report, _doctor_schema())
    (row,) = report["seat_cli_qualification"]
    assert row["status"] == "release_qualified" and "fix" not in row and "note" not in row
    doctor._print_doctor(report)
    assert "agy present and admitted for this runtime" in capsys.readouterr().out


def test_a_doctor_payload_without_the_new_section_still_validates():
    golden = json.loads((files("phase_loop_runtime") / "schemas" / "phase-loop-doctor.v1.golden.json").read_text())
    jsonschema.validate(golden, _doctor_schema())
    assert golden.pop("seat_cli_qualification")
    jsonschema.validate(golden, _doctor_schema())
