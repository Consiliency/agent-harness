"""GROK SL-4: the jailed measurement (IF-0-GROK-4), with a recording runner.

Plan ``plans/phase-plan-v1-seats-GROK.md`` (SL-4.1); frozen contract
``plans/artifacts/grok-jail-tool-surface-contract-v1.md`` r7: §3 "Production writers",
§4.4 measurement mode, §4.5 M1-M5, §5.1 (the ``_require_qualified_jail`` clause, the launch
path and the measurement success predicate), §5.2-§5.4, §7.1, BA-1, BA-2 and BA-J7.

Nothing here runs grok, reads a real credential or makes a provider call. The flow cases
drive ``seat-window measure-tools`` through its installed parser with the seat composition,
the sink probe and the leg replaced by a recording runner that keeps the §4.5 order; the
eligibility records are fixture records. The leg cases run the real SL-3 leg, the real
spawn check and the real ``consume_admission`` around a ``/bin/sh`` stand-in.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from phase_loop_runtime import grok_jail_surface as gjs
from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import president_adapter as pa
from phase_loop_runtime import seat_egress_proxy, seat_jail, seat_window
from phase_loop_runtime import seat_profile_grok as grok

from test_grok_jail_surface import STAND_IN, _build, _credential, _open_gate, _Proc

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux seat jail")

GRANT = "grok-jail-fixture"
HOSTED = "https://github.com/example/agent-harness/actions/runs/1"
LAUNCH = "a" * 64
REFUSED = "grok_tool_surface_unverified"
INFERENCE_PATH = "/v1/chat/completions"
SRC = Path(gts.__file__).resolve().parent


def _staged_tools() -> list[str]:
    return sorted(pi._grok_allowed_tools(list(gjs.production_command())))


def _definitions(names, extra: str = "") -> bytes:
    return json.dumps([{"type": "function", "function": {
        "name": name, "description": "fixture tool " + extra, "parameters": {}}}
        for name in names]).encode()


def _event(decision: str, cause: str | None = None):
    cause = cause or ("allowed" if decision == "allow" else "rules")
    return SimpleNamespace(method="POST", host=gts.INFERENCE_HOST, path=INFERENCE_PATH,
                           decision=decision, cause=cause)


@dataclasses.dataclass
class Launch:
    """What the recording runner does for one launch (a rehearsal or a label)."""

    #: Where the launch refuses, in the §4.5 order; ``None`` spawns.
    refuse_at: str | None = None
    exit: int = 0
    text: str = "OK"
    artifact: bytes | None = None
    events: tuple = ()
    complete: bool = True
    launch_digest: str = LAUNCH
    leg_failure: str | None = None
    #: The leg's strict post-run admission lookup fails (the marker is not confirmed).
    strict_missing: bool = False


class Runner:
    """The recording runner: compose (M1), ``prepare_measurement`` (M1), ``probe_sink``
    (M2), the leg (M3) whose spawn check verifies (M4), then ``_require_qualified_jail``,
    the identity probe and the capped preflight, then the spawn hook (M5), then the spawn."""

    STEPS = ("compose", "prepare", "probe_sink", "leg", "verify", "qualified", "identity",
             "preflight", "hook", "spawn")

    def __init__(self, bench):
        self.bench = bench
        self.order: list[str] = []
        self.seat_keys: list[str] = []
        self.reads = 0
        self.plan: list[Launch] = []
        self.proxies: list = []

    def next(self) -> Launch:
        return self.plan.pop(0) if self.plan else Launch(
            artifact=_definitions(_staged_tools()), events=(_event("allow"),))

    @contextlib.contextmanager
    def compose(self, stage, label, *, budget):
        launch = self.next()
        self.current = launch
        self.order.append("compose")
        if launch.refuse_at == "compose":
            raise seat_jail.SeatSandboxRefused(seat_jail.refused("namespace"))
        proxy = SimpleNamespace(request_budget=budget, launch=launch, counted=0)
        self.proxies.append(proxy)
        jail = SimpleNamespace(provider_argv0="/seat/bin/grok",
                               review_dir=str(self.bench.root / "seat"),
                               env={"HTTPS_PROXY": "http://srt:" + "p" * 24 + "@127.0.0.1:1"})
        seat = SimpleNamespace(jail=jail, seat=SimpleNamespace(seat_dir=self.bench.root))
        yield gts._JailSeat(grok_seat=seat, proxy=proxy, holder=4242, seat_id=7,
                            leg_owns_teardown=True)

    def launch_digest(self, jail, command, *, arch=None, measurement=False):
        assert measurement is True
        return self.current.launch_digest

    def prepare(self, reservation, seat, *, proxy, holder, command, check_route=True):
        self.order.append("prepare")
        if self.current.refuse_at == "prepare":
            raise seat_jail.SeatSandboxRefused(REFUSED)
        assert proxy.request_budget == reservation.budget
        self.reservation = reservation
        return gjs.JailedMeasurementLaunch(
            reservation, (b"fixture-bearer-0123456789",), MappingProxyType({"sink": [1, 2]}),
            issuer=gjs._ISSUER)

    def probe_sink(self, holder, seat_id, sink, *, measurement):
        self.order.append("probe_sink")
        if self.current.refuse_at == "probe_sink":
            raise seat_jail.SeatSandboxRefused(REFUSED)
        return (1, 2)

    def leg(self, grok_seat, *, measurement, read_sink, failure_detail_sink, prompt, **kwargs):
        launch = self.current
        assert prompt == gts.MEASUREMENT_PROMPT
        from phase_loop_runtime import seat_resource_caps

        self.order.append("leg")
        self.seat_keys.append(seat_resource_caps.live_seat_key())
        for step in ("verify", "qualified", "identity", "preflight"):
            self.order.append(step)
            if launch.refuse_at == step:
                raise seat_jail.SeatSandboxRefused(REFUSED)
        self.order.append("hook")
        reservation = measurement.reservation
        os.close(os.open(Path(reservation.grant_dir) / gjs.admission_name(
            reservation.reservation_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        if launch.refuse_at == "spawn":
            raise OSError("the capped launch failed after its hook")
        self.order.append("spawn")
        proxy = self.proxies[-1]
        proxy.counted = sum(1 for event in launch.events if event.decision == "allow")
        if launch.strict_missing:  # the leg reads nothing and fails the launch
            failure_detail_sink.append(SimpleNamespace(template=REFUSED))
            return "DEGRADED", ""
        self.bench.sink_bytes = launch.artifact
        self.reads += 1
        read_sink("/fixture/sink")  # the leg reads once its marker is strictly present
        if launch.leg_failure is not None:
            failure_detail_sink.append(SimpleNamespace(template=launch.leg_failure))
            return "DEGRADED", ""
        status = "OK" if launch.exit == 0 else "DEGRADED"
        return status, launch.text

    def read_sink_in_h(self, holder, seat_id, sink):
        if self.bench.sink_bytes is None:
            raise gts.ArtifactRefused("artifact_missing")
        return self.bench.sink_bytes


class Bench:
    def __init__(self, root: Path, patch):
        self.root = root
        self.patch = patch
        patch.setenv("XDG_STATE_HOME", str(root / "state"))
        self.binary_path = STAND_IN
        self.digest = gjs.root_owned_digest(STAND_IN)
        table = dict(grok.JAIL_PROTECTION)
        table[self.digest] = table[grok.GROK_1_0_92_SHA256]
        patch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
        self.output = root / "state" / "out"
        self.runner = Runner(self)
        self.sink_bytes = None
        identity = (STAND_IN, self.digest, ())
        patch.setattr(gts, "_measure_binary", lambda binary, expected: identity
                      if expected == self.digest else (_ for _ in ()).throw(
                          gts.MeasurementRefused("binary_mismatch")))
        patch.setattr(pi, "_grok_probe_identity", lambda argv, env=None: identity)
        patch.setattr(pi, "_subscription_env", lambda base_env=None: {"PATH": "/usr/bin:/bin"})
        self.metadata_calls: list = []
        patch.setattr(gts, "_help_and_version", lambda binary, env: (
            self.metadata_calls.append(binary), (b"grok help\n", b"grok 1.0.92\n"))[1])
        self.credential_remaining = 7200
        patch.setattr(gts, "jail_credential_expiry",
                      lambda: int(time.time()) + self.credential_remaining)
        patch.setenv("GROK_SLOT_END_EPOCH", str(int(time.time()) + 600))
        patch.setattr(gts, "_prepare_route", lambda route: (None, None, None, None))
        patch.setattr(gjs, "resolve_subject",
                      lambda env=None: gjs.JailedSubject(STAND_IN, self.digest))
        patch.setattr(gts, "_jail_compose", self.runner.compose)
        patch.setattr(gjs, "launch_digest", self.runner.launch_digest)
        patch.setattr(gjs, "prepare_measurement", self.runner.prepare)
        patch.setattr(gjs, "probe_sink", self.runner.probe_sink)
        patch.setattr(gjs, "read_sink_in_h", self.runner.read_sink_in_h)
        patch.setattr(pi, "_exec_jailed_grok_leg", self.runner.leg)
        patch.setattr(seat_egress_proxy, "completion", lambda proxy: SimpleNamespace(
            complete=proxy.launch.complete, reason="complete" if proxy.launch.complete
            else "no_end_marker", requests=len(proxy.launch.events), counted=proxy.counted))
        patch.setattr(seat_egress_proxy, "proxy_stream", lambda proxy: SimpleNamespace(
            outside_events=tuple(proxy.launch.events)))
        patch.setattr(seat_egress_proxy, "completion_detail", lambda proxy: {})
        self.open_records()

    def open_records(self, *, skip=("record",)):
        """Eligibility conditions 3 and 4 as fixture records for :data:`LAUNCH`."""
        _open_gate(self.digest, LAUNCH, skip=skip)

    def cli(self, *argv, grant=GRANT, expected=None):
        parser = argparse.ArgumentParser()
        seat_window.register_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args([
            "seat-window", "measure-tools", "--vendor", "grok", "--grant", grant,
            "--binary", self.binary_path, "--expect-binary-sha256", expected or self.digest,
            "--output", str(self.output), *argv])
        return gts.measure_tools_cli(args)

    def new_grant(self, retries=2, planned="pilot,planted,confirm"):
        return self.cli("--new-grant", "--planned", planned, "--retries", str(retries),
                        "--hosted-check", HOSTED)

    def rehearse(self, launch: Launch | None = None):
        self.runner.plan.insert(0, launch or Launch(events=(_event("deny", "budget"),),
                                                    exit=1, text=""))
        return self.cli("--attended", "--rehearse", "--route", "staged")

    def launch(self, *plan: Launch, routes: int = 1):
        self.runner.plan.extend(plan)
        return self.cli("--attended", *(["--route", "staged"] * routes))

    def opened(self, retries=2):
        code, report = self.new_grant(retries)
        assert code == 0, report
        code, report = self.rehearse()
        assert code == 0 and report["result"] == "passed", report
        return report

    def status(self):
        code, report = self.cli("--status")
        assert code == 0, report
        return report

    def grant_dir(self) -> Path:
        return Path(pa.private_record_root()) / gts.GRANTS_DIRNAME / GRANT

    def admissions(self) -> list[str]:
        """The counted reservations' admission files (the rehearsal's is its own)."""
        rehearsals = {path.name.split(".")[0] for path in
                      (self.grant_dir() / "rehearsals").glob("*.json")}
        return sorted(path.name for path in self.grant_dir().glob("admission-*")
                      if path.name[len("admission-"):] not in rehearsals)

    def jail_record(self):
        return gjs.read_private(gjs.host_record_name(self.digest))


@pytest.fixture
def bench(tmp_path, monkeypatch):
    return Bench(tmp_path, monkeypatch)


def _measured(tools=None, extra=""):
    return Launch(artifact=_definitions(tools or _staged_tools(), extra),
                  events=(_event("allow"),))


# --- §5.2: jailed grants, eligibility and the context -------------------------------------


def test_a_jailed_grant_records_its_context_cap_and_labels(bench):
    code, report = bench.new_grant()
    assert code == 0, report
    grant = report["grant"]
    assert grant["context"] == gts.JAIL_CONTEXT and grant["planned"] == list(gts.JAIL_LABELS)
    assert grant["cap"] == gts.JAIL_GRANT_CAP == 5 and grant["retries"] == 2
    assert (bench.grant_dir() / "unspawned").is_dir()


@pytest.mark.parametrize("withheld", ["confirmation", "boundary", "protection"])
def test_new_grant_and_rehearse_refuse_unless_conditions_one_to_four_pass(
        tmp_path, monkeypatch, withheld):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state0"))
    bench = Bench(tmp_path, monkeypatch)
    if withheld == "protection":
        monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(
            {k: v for k, v in grok.JAIL_PROTECTION.items() if k != bench.digest}))
    else:
        gjs.write_private(gjs.confirmation_name(bench.digest) if withheld == "confirmation"
                          else gjs.boundary_name(LAUNCH), {"schema": "withdrawn"})
    code, report = bench.new_grant()
    assert (code, report["code"]) == (1, "jail_ineligible")
    # Open the grant while eligible, then withdraw the condition: the rehearsal refuses.
    if withheld == "protection":
        table = dict(grok.JAIL_PROTECTION)
        table[bench.digest] = table[grok.GROK_1_0_92_SHA256]
        monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
    bench.open_records()
    assert bench.new_grant()[0] == 0
    if withheld == "protection":
        monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(
            {k: v for k, v in grok.JAIL_PROTECTION.items() if k != bench.digest}))
    else:
        gjs.write_private(gjs.confirmation_name(bench.digest) if withheld == "confirmation"
                          else gjs.boundary_name(LAUNCH), {"schema": "withdrawn"})
    code, report = bench.rehearse()
    assert (code, report["code"]) == (1, "jail_ineligible")
    assert bench.runner.order == []


def test_a_jailed_grant_takes_at_most_two_retries(bench):
    code, report = bench.new_grant(retries=3)
    assert (code, report["code"]) == (1, "retries_invalid")


@pytest.mark.parametrize("argv", [("--route", "review"), ("--route", "sealed")])
def test_a_stage_of_another_context_refuses(bench, argv):
    """Every stage refuses a context other than its grant's (§5.2): a jailed grant measures
    only the jailed ``staged`` form."""
    bench.opened()
    code, report = bench.cli("--attended", *argv)
    assert (code, report["code"]) == (1, "context_mismatch")
    code, report = bench.cli("--require-measured", "review")
    assert (code, report["code"]) == (1, "context_mismatch")


def test_new_unjailed_grants_refuse_with_the_jailed_profile(bench):
    code, report = bench.new_grant(planned="review", retries=0)
    assert (code, report["code"]) == (1, "unjailed_grant_refused")
    assert not bench.grant_dir().exists()
    code, report = bench.new_grant(planned="pilot,review")
    assert (code, report["code"]) == (1, "planned_routes_invalid")


# --- §4.5 and BA-J7: the order, unspawned and the admission -------------------------------


def test_the_launch_runs_m1_to_m5_in_order_and_consumes_last(bench):
    bench.opened()
    bench.runner.order.clear()
    code, report = bench.launch(_measured())
    assert code == 0, report
    assert bench.runner.order == list(Runner.STEPS)
    reservation = report["routes"][0]["reservation"]
    assert bench.admissions() == [gjs.admission_name(reservation)]
    assert report["routes"][0]["label"] == "pilot"


@pytest.mark.parametrize("step", ["compose", "prepare", "probe_sink", "verify", "qualified",
                                  "identity", "preflight"])
def test_ba_j7_a_refusal_before_the_hook_settles_unspawned_with_no_charge(bench, step):
    """r7: a refused qualification check, identity probe, capped preflight or sink probe
    (or any earlier step) leaves no admission file, spawns nothing and settles the
    reservation ``unspawned`` with no charge; OWNER-DECISION r7-1's interim rule stops the
    procedure."""
    bench.opened()
    bench.runner.order.clear()
    code, report = bench.launch(Launch(refuse_at=step), _measured(), routes=2)
    assert code == 1
    first, second = report["routes"]
    assert first["status"] == "unspawned" and second["code"] == "not_attempted"
    assert "spawn" not in bench.runner.order and "hook" not in bench.runner.order
    assert bench.admissions() == []
    status = bench.status()
    assert status["charged"] == 0 and status["stopped"] is True
    assert status["unspawned"] == {first["reservation"]: gts._unspawned_code(first["code"])}
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "grant_stopped_unspawned")


def test_the_resume_policy_is_one_isolated_decision_point_that_refuses(bench, monkeypatch):
    """OWNER-DECISION r7-1 is not ruled: ``unspawned_resumes`` is the one place the ruling
    lands. Replaced (as the owner's answer would), the label resumes; as shipped it refuses."""
    bench.opened()
    bench.launch(Launch(refuse_at="probe_sink"))
    ledger = SimpleNamespace(unspawned={"x": "y"})
    assert gts.unspawned_resumes(ledger, "pilot") is False
    monkeypatch.setattr(gts, "unspawned_resumes", lambda ledger, label: True)
    code, report = bench.launch(_measured())
    assert code == 0 and report["routes"][0]["label"] == "pilot", report


def test_a_spawn_that_fails_after_the_hook_is_charged_in_full_and_unresolved(bench):
    bench.opened()
    code, report = bench.launch(Launch(refuse_at="spawn"))
    assert code == 1 and report["routes"][0]["status"] != "unspawned"
    assert len(bench.admissions()) == 1
    status = bench.status()
    assert status["charged"] == 1 and status["unresolved"] and status["stopped"]
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "reservation_unresolved")


def test_ba_j7_after_a_restart_a_consumed_unsettled_reservation_is_never_reused(bench):
    """A crash between the hook and the settlement: the reservation stays charged in full,
    is not resumed, and no retry is reserved while it is unresolved (§5.1 item 5)."""
    bench.opened()
    code, report = bench.launch(_measured())
    reservation = report["routes"][0]["reservation"]
    (bench.grant_dir() / "settlements" / f"{reservation}.json").unlink()
    status = bench.status()
    assert status["unresolved"] == [reservation] and status["charged"] == 1
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "reservation_unresolved")


def test_a_crash_between_reservation_and_settlement_stays_charged_after_restart(bench):
    bench.opened()

    def crash(*args, **kwargs):
        raise KeyboardInterrupt  # the stage dies after the reservation exists

    with bench.patch.context() as patch:
        patch.setattr(gts, "_jail_launch", crash)
        with pytest.raises(KeyboardInterrupt):
            bench.launch(_measured())
    status = bench.status()
    assert status["charged"] == 1 and len(status["unresolved"]) == 1
    assert bench.launch(_measured())[1]["routes"][0]["code"] == "reservation_unresolved"


# --- §5.2: per-label reservations ----------------------------------------------------------


def test_labels_run_in_order_and_a_measured_planned_launch_leaves_both_retries(bench):
    bench.opened()
    code, report = bench.launch(_measured(), _measured(), _measured(), routes=3)
    assert code == 0, report
    assert [row["label"] for row in report["routes"]] == list(gts.JAIL_LABELS)
    status = bench.status()
    assert status["retries_used"] == 0 and status["charged"] == 3
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "labels_measured")


def test_planted_and_confirm_wait_for_a_measured_pilot(bench):
    bench.opened()
    code, report = bench.launch(Launch(exit=2, events=(_event("allow"),)))
    assert report["routes"][0]["label"] == "pilot" and report["routes"][0]["status"] != "measured"
    code, report = bench.launch(_measured())
    assert report["routes"][0]["label"] == "pilot"  # a retry of the pilot, not planted
    assert bench.status()["retries_used"] == 1


def test_interleaved_transport_failures_use_retries_and_the_newest_result_decides(bench):
    bench.opened()
    failure = Launch(exit=1, events=(_event("allow"),))
    code, report = bench.launch(failure)
    assert report["routes"][0]["status"] == "launch_failed"
    code, report = bench.launch(_measured(), failure, routes=2)
    assert [row["label"] for row in report["routes"]] == ["pilot", "planted"]
    assert [row["status"] for row in report["routes"]] == ["measured", "launch_failed"]
    code, report = bench.launch(_measured(), _measured(), routes=2)
    assert [row["label"] for row in report["routes"]] == ["planted", "confirm"]
    status = bench.status()
    assert status["retries_used"] == 2 and status["charged"] == 5
    states = {row["route"]: row["status"] for row in status["routes"]}
    assert states == dict.fromkeys(gts.JAIL_LABELS, "measured")


def test_a_sixth_counted_request_is_refused(bench):
    bench.opened()
    failure = Launch(exit=1, events=(_event("allow"),))
    bench.launch(failure)
    bench.launch(failure)
    bench.launch(_measured(), _measured(), routes=2)
    assert bench.status()["charged"] == 4
    code, report = bench.launch(failure)
    assert report["routes"][0]["status"] == "launch_failed"
    assert bench.status()["charged"] == 5
    calls = len(bench.metadata_calls)
    code, report = bench.launch(_measured())
    assert code == 1 and report["routes"][0]["code"] in ("grant_retries_exhausted",
                                                         "grant_cap_reached")
    assert len(bench.metadata_calls) == calls  # refused before any grok subprocess


def test_ba1_an_incomplete_observation_settles_nothing_and_charges_in_full(bench):
    bench.opened()
    code, report = bench.launch(Launch(complete=False, artifact=_definitions(_staged_tools()),
                                       events=(_event("allow"),)))
    assert report["routes"][0]["status"] == "egress_refused"
    status = bench.status()
    assert status["charged"] == 1 and status["reservations"][0]["settled"] is None


def test_no_reservation_without_the_grants_passing_rehearsal(bench):
    assert bench.new_grant()[0] == 0
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "rehearsal_required")
    assert bench.metadata_calls == []  # refused before any grok subprocess
    code, report = bench.rehearse(Launch(events=(_event("allow"),)))  # forwarded: fails
    assert (code, report["result"], report["reason"]) == (1, "failed", "unlisted_request")
    assert bench.launch(_measured())[1]["routes"][0]["code"] == "rehearsal_required"


def test_a_rehearsal_refused_before_its_hook_is_no_rehearsal(bench):
    assert bench.new_grant()[0] == 0
    code, report = bench.rehearse(Launch(refuse_at="identity"))
    assert (code, report["code"]) == (1, REFUSED)  # the typed code survives the boundary
    assert bench.admissions() == []
    code, report = bench.rehearse()
    assert code == 0 and report["result"] == "passed", report
    assert bench.rehearse()[1]["code"] == "rehearsal_exists"


# --- §5.1: the measurement success predicate, at the stage --------------------------------


def test_a_leg_secret_or_refresh_finding_is_not_measured_and_reads_nothing(bench):
    bench.opened()
    code, report = bench.launch(Launch(leg_failure="grok_seat_token_in_output",
                                       artifact=_definitions(_staged_tools()),
                                       events=(_event("allow"),)))
    assert report["routes"][0]["status"] == "launch_failed"
    assert not list((bench.output / "raw").rglob(gts.DEFINITIONS_NAME))


def test_a_second_inference_post_is_ok_at_the_leg_and_not_measured(bench):
    bench.opened()
    code, report = bench.launch(Launch(artifact=_definitions(_staged_tools()),
                                       events=(_event("allow"), _event("deny", "budget"))))
    assert report["routes"][0]["status"] == "budget_exhausted"


def test_a_suffix_in_the_definitions_artifact_gives_artifact_refused(bench):
    bench.opened()
    code, report = bench.launch(Launch(
        artifact=_definitions(_staged_tools(), extra="fixture-bearer-0123456789"[-12:]),
        events=(_event("allow"),)))
    assert report["routes"][0]["status"] == "artifact_refused"
    assert not list((bench.output / "raw").rglob(gts.DEFINITIONS_NAME))
    code, report = bench.cli("--require-measured", "staged")
    assert code == 1 and report["status"] == "not_measured"


# --- §5.4: agreement, the publication gate, and the sole writer (§3) ----------------------


def _three(bench, *plans):
    bench.opened()
    code, report = bench.launch(*(plans or (_measured(), _measured(), _measured())), routes=3)
    return code, report


def test_agreement_publishes_the_jailed_record_through_the_sole_writer(bench):
    code, _report = _three(bench)
    assert code == 0
    assert bench.jail_record() is None
    code, report = bench.cli("--aggregate")
    assert code == 0 and report["published"] == ["staged"], report
    record = bench.jail_record()
    gjs.check_jail_surface(record["surface"])
    surface = record["surface"]
    assert surface["routes"][0]["tools"] == _staged_tools()
    assert surface["launch_digest"] == {seat_jail.host_arch(): LAUNCH}
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    assert evidence["schema"] == gts.JAIL_EVIDENCE_SCHEMA and evidence["context"] == gts.JAIL_CONTEXT
    assert evidence["launch_digest"] == LAUNCH
    assert [route["route"] for route in evidence["routes"]] == list(gts.JAIL_LABELS)
    assert gjs.eligibility(bench.digest) is None  # condition 5 now holds


@pytest.mark.parametrize("disagree", ["tools", "definitions", "launch", "rehearsal_launch"])
def test_disagreement_publishes_nothing_surface_unstable(bench, disagree):
    plans = [_measured(), _measured(), _measured()]
    if disagree == "tools":
        plans[2] = _measured(tools=_staged_tools()[:-1])
    elif disagree == "definitions":
        plans[1] = _measured(extra="other")
    elif disagree == "launch":
        plans[2] = dataclasses.replace(_measured(), launch_digest="b" * 64)
    if disagree == "rehearsal_launch":
        assert bench.new_grant()[0] == 0
        assert bench.rehearse(Launch(events=(_event("deny", "budget"),), exit=1,
                                     launch_digest="c" * 64))[0] == 0
        assert bench.launch(*plans, routes=3)[0] == 0
    else:
        _three(bench, *plans)
    code, report = bench.cli("--aggregate")
    assert (code, report["code"]) == (1, "surface_unstable")
    assert bench.jail_record() is None


def test_a_label_not_measured_publishes_nothing(bench):
    bench.opened()
    bench.launch(_measured(), _measured(), routes=2)
    code, report = bench.cli("--aggregate")
    assert (code, report["code"]) == (1, "surface_unstable")


@pytest.mark.parametrize("drift", ["runtime", "jail_context"])
def test_context_mismatch_when_the_runtime_or_jail_context_drifts_after_the_last_launch(
        bench, monkeypatch, drift):
    _three(bench)
    assert bench.cli("--aggregate")[0] == 0 and bench.jail_record() is not None
    if drift == "runtime":
        monkeypatch.setattr(seat_window, "runtime_digest", lambda: "f" * 64)
    else:
        monkeypatch.setattr(gjs, "jail_context_digest", lambda image: "e" * 64)
    code, report = bench.cli("--aggregate")
    assert (code, report["code"]) == (1, "context_mismatch")
    assert bench.jail_record() is None  # removed, and nothing published


def test_ba2_a_new_reservation_withdraws_the_jailed_publication(bench):
    _three(bench)
    assert bench.cli("--aggregate")[0] == 0
    assert gjs.resolve_record(bench.digest, gjs.staged_argv_digest()) is not None
    # A second grant for the same image: its reservation withdraws before it exists.
    bench2 = bench
    code, report = bench2.cli("--new-grant", "--planned", "pilot,planted,confirm",
                              "--retries", "0", "--hosted-check", HOSTED, grant="second")
    assert code == 0, report
    bench2.runner.plan.insert(0, Launch(events=(_event("deny", "budget"),), exit=1))
    assert bench2.cli("--attended", "--rehearse", "--route", "staged", grant="second")[0] == 0
    bench2.runner.plan.append(Launch(refuse_at="compose"))
    bench2.cli("--attended", "--route", "staged", grant="second")
    assert bench.jail_record() is None
    assert gjs.resolve_record(bench.digest, gjs.staged_argv_digest()) is None
    # The first grant's aggregate no longer publishes: its attempt is not the latest.
    code, report = bench.cli("--aggregate")
    assert code == 0 and report["published"] == [] and report["superseded"]


# --- §7.1 and §3: --verify-probe final and the production writers ------------------------


def test_verify_probe_final_passes_only_on_the_jailed_staged_row(bench):
    plain = "grok-probe-" + bench.digest + "-" + gjs.staged_argv_digest() + ".json"
    gjs.write_private(plain, {"schema": "tool_probe.v1", "basis": "list_tools", "passed": True})
    before = (Path(pa.private_record_root()) / plain).read_bytes()
    receipt = Path(pa.private_record_root()) / gjs.receipt_name(bench.digest,
                                                                gjs.staged_argv_digest())
    _three(bench)
    code, report = bench.cli("--verify-probe", "final")
    assert (code, report["code"]) == (1, "aggregate_unavailable") and not receipt.exists()
    assert bench.cli("--aggregate")[0] == 0
    code, report = bench.cli("--verify-probe", "final")
    assert code == 0 and report["passed"], report
    rows = {row["route"]: row for row in report["routes"]}
    assert rows["staged"] == {"route": "staged", "passed": True, "basis": "frozen_measurement",
                              "source": "host_local"}
    assert all(not row["passed"] for name, row in rows.items() if name != "staged")
    record = gjs.resolve_record(bench.digest, gjs.staged_argv_digest())
    assert json.loads(receipt.read_text()) == gjs.jail_receipt(record, bench.digest, LAUNCH)
    assert (Path(pa.private_record_root()) / plain).read_bytes() == before


def _calls(tree, predicate):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and predicate(inner):
                    found.append(node.name)
    return found


def _jail_alias_names(tree) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in (None, ""):
            for alias in node.names:
                if alias.name == "grok_jail_surface":
                    names.add(alias.asname or alias.name)
    return names


def test_the_production_writers_are_the_named_ones_only():
    """§3 r7: no caller of ``write_jail_receipt`` but ``panel_invoker._grok_jailed_probe``;
    no writer of the jailed ``host_record_name`` but this lane's ``jail_aggregate``. The
    unjailed ``grok_tool_surface.host_record_name`` is a different name and out of scope."""
    receipt_callers, record_writers = [], []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _jail_alias_names(tree)
        local = path.name == "grok_jail_surface.py"

        def jailed_name(node) -> bool:
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "host_record_name":
                return isinstance(func.value, ast.Name) and func.value.id in aliases
            return local and isinstance(func, ast.Name) and func.id == "host_record_name"

        def writes_record(node) -> bool:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            return (name in ("write_private", "write_private_record") and node.args
                    and isinstance(node.args[0], ast.Call) and jailed_name(node.args[0]))

        def calls_receipt(node) -> bool:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            return name == "write_jail_receipt"

        receipt_callers += [(path.name, name) for name in _calls(tree, calls_receipt)]
        record_writers += [(path.name, name) for name in _calls(tree, writes_record)]
    assert sorted(set(receipt_callers)) == [("panel_invoker.py", "_grok_jailed_probe")]
    assert sorted(set(record_writers)) == [("grok_tool_surface.py", "jail_aggregate")]


# --- §5.1 r7: the leg's measurement mode, through the real SL-3 leg ----------------------


@pytest.fixture
def mleg(tmp_path, monkeypatch):
    """A jailed measurement seat composed by the real ``_prepare_jailed_grok(...,
    measurement=True)`` over the stand-in subject, a budget-1 proxy object and fixture
    eligibility records; ``launch_provider`` is a recorder that runs the spawn hook it is
    passed, then a ``/bin/sh`` stand-in."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    review = tmp_path / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True, mode=0o700)
    (tree / "main.py").write_text("print('fixture')\n", encoding="utf-8")
    fd = seat_jail.open_dir_nofollow(tree)
    try:
        staged = seat_jail.tree_manifest_sha256_at(fd)
    finally:
        os.close(fd)
    binary = gjs.root_owned_digest(STAND_IN)
    table = dict(grok.JAIL_PROTECTION)
    table[binary] = table[grok.GROK_1_0_92_SHA256]
    monkeypatch.setattr(grok, "JAIL_PROTECTION", MappingProxyType(table))
    monkeypatch.setattr(gjs, "resolve_subject",
                        lambda env=None: gjs.JailedSubject(STAND_IN, binary))
    from phase_loop_runtime import seat_grok_credential as cred

    monkeypatch.setattr(cred, "stage_grok_seat_credential",
                        lambda config, *, margin_s: _credential(Path(config))[0])
    import hashlib

    ca = tmp_path / "proxy-ca.pem"
    ca.write_bytes(b"fixture proxy certificate\n")
    proxy = SimpleNamespace(
        process=_Proc(), allowlist_id="grok-review",
        allowlist_digest=pi._seat_egress_proxy.allowlist_ref("grok-review").content_digest,
        request_budget=1, socket=str(tmp_path / "proxy.sock"), ca_cert=ca,
        ca_sha256=hashlib.sha256(ca.read_bytes()).hexdigest(),
        proxy_url="http://srt:" + "p" * 24 + "@127.0.0.1:3128")
    holder = os.getpid()
    prefix = ("/usr/bin/nsenter", "-t", str(holder), "-U")
    reset = pi._EGRESS_LAUNCH_PREFIX.set(prefix)
    monkeypatch.setattr(gts, "bridged_to", lambda p, px: tuple(p) == prefix and px is proxy)
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda pid, path: [])
    after: list = [None]
    monkeypatch.setattr(gjs, "after_check_in_h", lambda pid, home: after[0])
    state = SimpleNamespace(order=[], hooks=[], output={"stdout": "OK\n", "stderr": "", "rc": 0},
                            reads=[], after=after, proxy=proxy, binary=binary, tmp=tmp_path)

    def launch_provider(argv, *, process_owner=None, probe_owner=None, spawn_hook=None, **kw):
        state.hooks.append(spawn_hook)
        if spawn_hook is not None:
            spawn_hook()
            state.order.append("hook")
        state.order.append("spawn")
        script = ("cat >/dev/null; printf '%s' \"$OUT\"; printf '%s' \"$ERR\" >&2; exit $RC")
        return subprocess.Popen(
            ["/bin/sh", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "OUT": state.output["stdout"],
                 "ERR": state.output["stderr"], "RC": str(state.output["rc"])})

    monkeypatch.setattr(pi, "launch_provider", launch_provider)
    (tmp_path / "base").mkdir()
    grant_dir = tmp_path / "grant"
    grant_dir.mkdir(mode=0o700)

    def prepare(*, budget=1):
        proxy.request_budget = budget
        seat = pi._prepare_jailed_grok(
            review, tmp_path / "base" / "seat", SimpleNamespace(staged_tree_sha256=staged),
            7, holder, ("", ""), proxy, deadline_s=60, measurement=True)
        command = list(gjs.production_command(seat.jail.provider_argv0))
        launch = gjs.launch_digest(seat.jail, command, measurement=True)
        _open_gate(binary, launch, skip=("record",))
        reservation = gjs.MeasurementReservation("g1", "0001-00000000000000aa", "pilot",
                                                 binary, budget, str(grant_dir))
        measurement = gjs.prepare_measurement(reservation, seat, proxy=proxy, holder=holder,
                                              command=command, check_route=False)
        return seat, measurement

    state.prepare = prepare
    state.grant_dir = grant_dir
    yield state
    pi._EGRESS_LAUNCH_PREFIX.reset(reset)


def _mrun(state, seat, prepared, **kwargs):
    sink: list = []

    def reader(path):
        state.reads.append(path)
        return "read"

    arguments = dict(measurement=prepared, read_sink=reader)
    arguments.update(kwargs)
    status, text = pi._exec_jailed_grok_leg(
        seat, deadline_s=60, model=gjs.PRODUCTION_MODEL, effort=gjs.PRODUCTION_EFFORT,
        prompt=gts.MEASUREMENT_PROMPT, broker_evidence=None, failure_detail_sink=sink,
        **arguments)
    return status, text, [failure.template for failure in sink]


@pytest.mark.parametrize("reply", ["OK\n", "reviewed\nVERDICT: AGREE\n", "anything at all\n"])
def test_a_measurement_that_exits_zero_is_ok_whatever_it_replies(mleg, reply):
    seat, measurement = mleg.prepare()
    mleg.output["stdout"] = reply
    status, text, failures = _mrun(mleg, seat, measurement)
    assert (status, failures) == ("OK", []), failures
    assert text == reply and len(mleg.reads) == 1
    assert mleg.reads[0].endswith("/.grok-rw/sessions")
    assert gjs.admission_consumed(measurement.reservation)
    assert mleg.order == ["hook", "spawn"] and callable(mleg.hooks[0])


def test_the_board_predicate_would_fail_the_ok_measurement():
    """The falsifier mutant (§5.1 r7): the board predicate on the fixed measurement reply."""
    assert pi._classify_leg(0, "OK\n", "", "review") != "OK"


@pytest.mark.parametrize("case", ["nonzero", "secret", "refresh"])
def test_a_measurement_that_fails_is_not_ok(mleg, case):
    seat, measurement = mleg.prepare()
    if case == "nonzero":
        mleg.output["rc"] = 3
    elif case == "secret":
        token = list(measurement.scan_values)[0].decode()
        mleg.output["stdout"] = "leak " + token + "\n"
    else:
        mleg.after[0] = "grok_seat_token_refreshed_in_jail"
    status, _text, _failures = _mrun(mleg, seat, measurement)
    assert status != "OK"


def test_a_measurement_without_its_admission_after_exit_is_unresolved(mleg, monkeypatch):
    seat, measurement = mleg.prepare()
    monkeypatch.setattr(gjs, "admission_present", lambda reservation: False)
    status, _text, failures = _mrun(mleg, seat, measurement)
    assert status != "OK" and failures == [REFUSED] and mleg.reads == []


@pytest.mark.parametrize("bad", ["window_board", "no_reader", "unprepared"])
def test_the_leg_refuses_a_measurement_in_a_window_or_without_a_reader(mleg, bad):
    seat, measurement = mleg.prepare()
    kwargs = {"window_board": object()} if bad == "window_board" else (
        {"read_sink": None} if bad == "no_reader" else {"measurement": object()})
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        _mrun(mleg, seat, measurement, **kwargs)
    assert caught.value.code == REFUSED
    assert mleg.order == [] and not gjs.admission_consumed(measurement.reservation)


def test_a_board_launch_passes_no_hook(mleg):
    """``_grok_jailed_spawn_check`` returns ``None`` in board mode, and the board path still
    reaches ``launch_provider`` with ``spawn_hook=None``."""
    seat, measurement = mleg.prepare()
    token = pi._GROK_JAILED_LAUNCH.set((seat, "board", None))
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused):  # no jailed receipt: board refuses
            pi._grok_jailed_spawn_check(list(gjs.production_command(seat.jail.provider_argv0)),
                                        seat.jail, "/seat/tree")
    finally:
        pi._GROK_JAILED_LAUNCH.reset(token)
    pi._cleanup_jailed_seat(seat.seat)
    pi._remove_grok_staged(seat.seat.seat_dir)
    import inspect

    source = inspect.getsource(pi._grok_jailed_spawn_check)
    assert 'if mode != "measurement":\n        return None' in source


def test_run_leg_with_liveness_passes_the_returned_hook(mleg):
    """The dropped-hook mutant (BA-J7 r7): the jailed branch hands ``launch_provider``
    exactly the hook the spawn check returned, and the admission appears only then."""
    seat, measurement = mleg.prepare()
    status, _text, _failures = _mrun(mleg, seat, measurement)
    assert status == "OK" and mleg.hooks and mleg.hooks[0] is not None
    assert mleg.order.index("hook") < mleg.order.index("spawn")


def test_the_verifier_does_not_consume_again(mleg):
    """The consuming-verifier mutant: after the spawn check the admission does not exist;
    only the hook creates it."""
    seat, measurement = mleg.prepare()
    token = pi._GROK_JAILED_LAUNCH.set((seat, "measurement", measurement))
    try:
        hook = pi._grok_jailed_spawn_check(
            list(gjs.production_command(seat.jail.provider_argv0)), seat.jail, "/seat/tree")
        assert not gjs.admission_consumed(measurement.reservation)
        hook()
        assert gjs.admission_consumed(measurement.reservation)
        with pytest.raises(gjs.JailRefused):
            hook()
    finally:
        pi._GROK_JAILED_LAUNCH.reset(token)
        pi._cleanup_jailed_seat(seat.seat)
        pi._remove_grok_staged(seat.seat.seat_dir)


# --- §5.1 r7: the _require_qualified_jail measurement clause ------------------------------


@pytest.fixture
def qualified(tmp_path, monkeypatch):
    built = _build(tmp_path / "q")
    measured = dataclasses.replace(built.jail, process_owner=gjs.measurement_owner(built.jail))
    seen: list = []
    monkeypatch.setattr(pi, "_require_canonical_jail", lambda jail: seen.append(jail))
    monkeypatch.setattr(pi, "_pass_refusal", lambda key, recorded=None: None)
    reservation = gjs.MeasurementReservation("g", "0001-00000000000000aa", "pilot", "0" * 64,
                                             1, str(tmp_path))
    launch = gjs.JailedMeasurementLaunch(reservation, (), MappingProxyType({}),
                                         issuer=gjs._ISSUER)
    yield SimpleNamespace(built=built, measured=measured, seen=seen, launch=launch)
    seat_jail.close_jail_fds(built.jail)


def _with_launch(jail, mode, measurement):
    seat = SimpleNamespace(jail=jail)
    return pi._GROK_JAILED_LAUNCH.set((seat, mode, measurement))


def test_the_clause_substitutes_the_sink_bind_back_for_this_jail_only(qualified):
    q = qualified
    token = _with_launch(q.measured, "measurement", q.launch)
    try:
        pi._require_qualified_jail(q.measured)
    finally:
        pi._GROK_JAILED_LAUNCH.reset(token)
    assert q.seen[-1].process_owner == q.built.jail.process_owner


@pytest.mark.parametrize("held", ["lookalike", "board", "unprepared", "none"])
def test_the_clause_needs_this_exact_jail_and_a_prepared_measurement(qualified, held):
    """The identity-condition mutant: an equal-valued copy, a board launch, a measurement
    not issued by ``prepare_measurement`` or nothing held leaves the jail as it is."""
    q = qualified
    jail = q.measured
    holder = {"lookalike": (dataclasses.replace(q.measured), "measurement", q.launch),
              "board": (q.measured, "board", None),
              "unprepared": (q.measured, "measurement", object()),
              "none": None}[held]
    token = (pi._GROK_JAILED_LAUNCH.set((SimpleNamespace(jail=holder[0]), *holder[1:]))
             if holder is not None else pi._GROK_JAILED_LAUNCH.set(None))
    try:
        pi._require_qualified_jail(jail)
    finally:
        pi._GROK_JAILED_LAUNCH.reset(token)
    assert q.seen[-1] is jail


def test_a_measurement_owner_differing_by_more_than_the_sink_refuses_identity(qualified):
    q = qualified
    extra = dataclasses.replace(q.measured, process_owner=(*q.measured.process_owner[:1],
                                                           "--unshare-uts",
                                                           *q.measured.process_owner[1:]))
    production = dataclasses.replace(q.built.jail)  # no sink bind at all
    for jail in (production,):
        token = _with_launch(jail, "measurement", q.launch)
        try:
            with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
                pi._require_qualified_jail(jail)
            assert caught.value.code == seat_jail.refused("identity")
        finally:
            pi._GROK_JAILED_LAUNCH.reset(token)
    token = _with_launch(extra, "measurement", q.launch)
    try:
        pi._require_qualified_jail(extra)
    finally:
        pi._GROK_JAILED_LAUNCH.reset(token)
    assert q.seen[-1].process_owner != q.built.jail.process_owner  # the extra flag remains


def test_launch_provider_runs_the_hook_after_qualification_identity_and_preflight(
        qualified, monkeypatch):
    """§4.5 M5 in ``launch_provider`` (unedited): each earlier refusal calls no hook."""
    order: list = []
    jail = qualified.built.jail
    monkeypatch.setattr(pi, "_require_qualified_jail",
                        lambda owner: order.append("qualified"))
    monkeypatch.setattr(pi, "_require_jailed_seat_identity",
                        lambda *a, **k: order.append("identity"))
    monkeypatch.setattr(pi, "_compose_launch_prefix", lambda cwd, owner, caps: ["/bin/true"])
    monkeypatch.setattr(pi, "_compose_seat_jail_prefix", lambda owner, caps=(): ["/bin/true"])
    from phase_loop_runtime import seat_resource_caps

    def capped(command, *, seat_key, before_spawn=None, **kwargs):
        order.append("preflight")
        before_spawn()
        order.append("spawn")
        raise OSError("stop before a real process")

    monkeypatch.setattr(seat_resource_caps, "capped_popen", capped)
    with pytest.raises(OSError):
        pi.launch_provider(["/seat/bin/grok"], process_owner=jail, probe_owner=jail,
                           spawn_hook=lambda: order.append("hook"))
    assert order == ["qualified", "identity", "preflight", "hook", "spawn"]
    for step in ("qualified", "identity"):
        order.clear()
        target = "_require_qualified_jail" if step == "qualified" else "_require_jailed_seat_identity"

        def refuse(*a, **k):
            raise seat_jail.SeatSandboxRefused(seat_jail.refused("identity"))

        monkeypatch.setattr(pi, target, refuse)
        with pytest.raises(seat_jail.SeatSandboxRefused):
            pi.launch_provider(["/seat/bin/grok"], process_owner=jail, probe_owner=jail,
                               spawn_hook=lambda: order.append("hook"))
        assert "hook" not in order


# --- §4.5 M2: probe_sink, bound to the admitted inode -------------------------------------


class _Done:
    def __init__(self, rc, out=b""):
        self.returncode, self.stdout, self.stderr = rc, out, b""


def _sink_measurement(sink: Path, *, admitted=None):
    descriptor = gjs.open_dir_chain(str(sink))
    info = os.fstat(descriptor)
    reservation = gjs.MeasurementReservation("g", "0001-00000000000000aa", "pilot", "0" * 64,
                                             1, str(sink.parent))
    return gjs.JailedMeasurementLaunch(
        reservation, (), MappingProxyType({"sink": list(admitted or (info.st_dev, info.st_ino))}),
        issuer=gjs._ISSUER, sink_fd=descriptor)


def test_probe_sink_runs_the_verbs_in_h_bound_to_the_admitted_inode(tmp_path, monkeypatch):
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    measurement = _sink_measurement(sink)
    info = sink.stat()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return _Done(0, json.dumps({"device": info.st_dev, "inode": info.st_ino}).encode())

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(os, "getuid", lambda: info.st_uid + 1)  # the sink is the seat's
    try:
        assert gjs.probe_sink(4242, 7, str(sink), measurement=measurement) == (
            info.st_dev, info.st_ino)
    finally:
        gjs.close_measurement(measurement)
    argv = calls[0]
    assert argv[:4] == ["/usr/bin/nsenter", "-t", "4242", "-U"]
    assert argv[-5:] == ["sink-handoff", str(sink), "7", str(info.st_dev), str(info.st_ino)]
    assert "phase_loop_runtime.grok_jail_surface" in argv


@pytest.mark.parametrize("fail", ["exit", "swapped", "non_empty", "garbled", "helper",
                                  "operator_owned", "group_mode", "path_swapped", "no_fd"])
def test_probe_sink_fails_closed(tmp_path, monkeypatch, fail):
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    measurement = _sink_measurement(sink)
    info = sink.stat()
    report = {"device": info.st_dev, "inode": info.st_ino}
    rc = 0
    if fail == "exit":
        rc = 3
    elif fail == "swapped":
        report["inode"] += 1
    elif fail == "non_empty":
        (sink / "x").write_bytes(b"")
    elif fail == "group_mode":
        sink.chmod(0o770)
    elif fail == "path_swapped":  # the name now holds another empty directory
        sink.rename(tmp_path / "moved")
        sink.mkdir(mode=0o700)
    elif fail == "no_fd":
        gjs.close_measurement(measurement)
    payload = b"{" if fail == "garbled" else json.dumps(report).encode()

    def run(argv, **kwargs):
        if fail == "helper":
            raise OSError("nsenter missing")
        return _Done(rc, payload)

    monkeypatch.setattr(subprocess, "run", run)
    if fail != "operator_owned":
        monkeypatch.setattr(os, "getuid", lambda: info.st_uid + 1)
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
            gjs.probe_sink(4242, 7, str(sink), measurement=measurement)
    finally:
        gjs.close_measurement(measurement)
    assert caught.value.code == REFUSED


def test_the_handoff_refuses_a_substituted_sink_before_changing_anything(tmp_path):
    """The pre-handoff substitution: another empty directory renamed into the sink slot
    after M1. The H helper compares the admitted inode first and changes nothing."""
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    admitted = sink.stat()
    sink.rename(tmp_path / "admitted")
    other = tmp_path / "sibling"
    other.mkdir(mode=0o750)
    other.rename(sink)
    before = sink.stat()
    assert gjs._sink_handoff_main(str(sink), str(os.getuid()), str(admitted.st_dev),
                                  str(admitted.st_ino)) == 3
    after = sink.stat()
    assert (after.st_mode, after.st_uid, after.st_gid) == (
        before.st_mode, before.st_uid, before.st_gid)


@pytest.mark.parametrize("bad", ["mode", "non_empty", "symlink"])
def test_the_handoff_refuses_a_sink_that_is_not_an_empty_private_directory(tmp_path, bad):
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    info = sink.stat()
    if bad == "mode":
        sink.chmod(0o750)
    elif bad == "non_empty":
        (sink / "old").write_bytes(b"")
    else:
        sink.rename(tmp_path / "target")
        sink.symlink_to(tmp_path / "target")
    assert gjs._sink_handoff_main(str(sink), str(os.getuid()), str(info.st_dev),
                                  str(info.st_ino)) == 3


def test_the_handoff_keeps_0700_and_passes_its_descriptor_to_the_dropped_probe(
        tmp_path, monkeypatch):
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    info = sink.stat()
    seen = []

    class Exec(Exception):
        pass

    def execv(path, argv):
        seen.append(argv)
        raise Exec

    monkeypatch.setattr(os, "execv", execv)
    with pytest.raises(Exec):
        gjs._sink_handoff_main(str(sink), str(os.getuid()), str(info.st_dev), str(info.st_ino))
    after = sink.stat()
    assert after.st_mode & 0o777 == 0o700
    assert (after.st_uid, after.st_gid) == (os.getuid(), os.getuid())
    argv = seen[0]
    assert argv[0] == "/usr/bin/setpriv" and argv[-2] == "sink-probe"
    assert os.fstat(int(argv[-1])).st_ino == info.st_ino


def test_the_sink_probe_verb_writes_reads_back_and_unlinks(tmp_path, capsys):
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    os.chown(sink, os.getuid(), os.getgid())
    descriptor = os.open(sink, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert gjs._sink_probe_main(str(descriptor)) == 0
    finally:
        os.close(descriptor)
    reported = json.loads(capsys.readouterr().out)
    assert (reported["device"], reported["inode"]) == (sink.stat().st_dev, sink.stat().st_ino)
    assert list(sink.iterdir()) == []


@pytest.mark.parametrize("bad", ["non_empty", "symlink_entry", "group_mode"])
def test_the_sink_probe_verb_refuses_a_non_private_or_non_empty_sink(tmp_path, bad):
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    if bad == "non_empty":
        (sink / "old").write_bytes(b"")
    elif bad == "symlink_entry":
        (sink / "link").symlink_to("/etc/passwd")
    else:
        sink.chmod(0o770)
    descriptor = os.open(sink, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert gjs._sink_probe_main(str(descriptor)) == 3
    finally:
        os.close(descriptor)


def test_the_spawn_hook_reads_the_sink_through_the_m1_descriptor(tmp_path, monkeypatch):
    """After M2 the sink is the seat's; M5 checks emptiness through the operator's M1
    descriptor and refuses when the path names another inode."""
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    measurement = _sink_measurement(sink)
    try:
        sink.rename(tmp_path / "moved")
        sink.mkdir(mode=0o700)
        with pytest.raises(gjs.JailRefused):
            gjs._sink_view(measurement.sink_fd, [sink.stat().st_dev, sink.stat().st_ino])
    finally:
        gjs.close_measurement(measurement)


def test_the_admission_presence_check_is_strict(tmp_path):
    reservation = gjs.MeasurementReservation("g", "0001-00000000000000aa", "pilot", "0" * 64,
                                             1, str(tmp_path))
    assert gjs.admission_state(reservation) == "absent"
    (tmp_path / gjs.admission_name(reservation.reservation_id)).mkdir()  # not the file
    assert gjs.admission_consumed(reservation) is True  # the charge stays
    assert gjs.admission_present(reservation) is False  # and nothing succeeds


def test_the_sink_handoff_verb_refuses_a_symlinked_sink(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    link = tmp_path / "sink"
    link.symlink_to(target)
    info = target.stat()
    assert gjs._sink_handoff_main(str(link), "7", str(info.st_dev), str(info.st_ino)) == 3


def test_the_sink_reader_reads_one_seat_owned_artifact(tmp_path, capsys):
    session = tmp_path / "sink" / "group" / "session"
    session.mkdir(parents=True)
    (session / gts.DEFINITIONS_NAME).write_bytes(_definitions(_staged_tools()))
    assert gjs._sink_read_main(str(tmp_path / "sink"), str(os.getuid())) == 0
    assert capsys.readouterr().out.encode() == _definitions(_staged_tools())
    assert gjs._sink_read_main(str(tmp_path / "sink"), str(os.getuid() + 1)) == gjs._SINK_AMBIGUOUS
    assert gjs._sink_read_main(str(tmp_path / "none"), str(os.getuid())) == gjs._SINK_AMBIGUOUS


# --- Review round 1: ordering, ownership and the credential slot ------------------------


def test_a_stopped_grant_starts_no_grok_subprocess(bench):
    """A launch stage of a stopped grant refuses before the definition-only --help and
    --version calls, and before anything is composed."""
    bench.opened()
    bench.launch(Launch(refuse_at="probe_sink"))
    calls, order = len(bench.metadata_calls), len(bench.runner.order)
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "grant_stopped_unspawned")
    assert len(bench.metadata_calls) == calls and len(bench.runner.order) == order


def test_an_identity_refused_grant_starts_no_grok_subprocess(bench, monkeypatch):
    bench.opened()
    bench.runner.order.clear()
    monkeypatch.setattr(gjs, "resolve_subject",
                        lambda env=None: gjs.JailedSubject(STAND_IN, "0" * 64))
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "binary_mismatch")
    assert bench.metadata_calls == [] and "compose" not in bench.runner.order


def test_an_m2_refusal_keeps_its_typed_code(bench):
    bench.opened()
    code, report = bench.launch(Launch(refuse_at="probe_sink"))
    assert report["routes"][0]["code"] == REFUSED
    assert list(bench.status()["unspawned"].values()) == [REFUSED]


def test_a_short_credential_lifetime_refuses_before_opening_or_reserving(bench):
    bench.credential_remaining = int(gts.JAIL_CREDENTIAL_MARGIN_S)
    code, report = bench.new_grant()
    assert (code, report["code"]) == (1, "grok_seat_token_expired")
    assert not bench.grant_dir().exists()
    bench.credential_remaining = 7200
    code, report = bench.new_grant()
    assert code == 0 and "credential_remaining_s" not in report  # no post-commit reread
    assert bench.rehearse()[0] == 0
    bench.credential_remaining = 60
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "grok_seat_token_expired")
    assert bench.status()["reservations"] == [] and bench.metadata_calls == []


@pytest.mark.parametrize("slot", ["short", "missing", "malformed"])
def test_the_slot_cutoff_is_enforced_before_the_grant_exists(bench, monkeypatch, slot):
    """§7: the expiry must exceed the slot end plus five minutes, checked before
    ``grant.json`` is written; a missing or malformed slot end refuses too."""
    if slot == "short":  # expiry 7200 s away; the slot ends 7000 s away: < slot end + 300
        monkeypatch.setenv("GROK_SLOT_END_EPOCH", str(int(time.time()) + 7000))
        expected = "grok_seat_token_expired"
    elif slot == "missing":
        monkeypatch.delenv("GROK_SLOT_END_EPOCH")
        expected = "slot_end_required"
    else:
        monkeypatch.setenv("GROK_SLOT_END_EPOCH", "soon")
        expected = "slot_end_required"
    code, report = bench.new_grant()
    assert (code, report["code"]) == (1, expected)
    assert not bench.grant_dir().exists()


def _metadata_store(tmp_path, monkeypatch, *, expires_at=None):
    home = tmp_path / "home"
    store = home / ".grok"
    store.mkdir(parents=True, mode=0o700)
    auth = store / "auth.json"
    auth.write_bytes(b"not read by the metadata reader")
    auth.chmod(0o600)
    info = auth.stat()
    expires_at = expires_at or int(time.time()) + 7200
    meta = store / gts.CREDENTIAL_METADATA_NAME
    meta.write_text(json.dumps({"subscription": True, "expires_at": expires_at, "auth_state": {
        "device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
        "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}}))
    meta.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    from phase_loop_runtime import seat_grok_credential as cred

    def forbidden(*args, **kwargs):
        raise AssertionError("the metadata reader touched the secret store")

    monkeypatch.setattr(cred, "_read_store", forbidden)
    monkeypatch.setattr(cred, "_sign_in_entry", forbidden)
    real_open = os.open

    def guarded_open(path, *args, **kwargs):
        if os.fspath(path).endswith(("auth.json", "agent_id")):
            raise AssertionError("the metadata reader opened a secret file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    return SimpleNamespace(store=store, auth=auth, meta=meta, expires_at=expires_at)


def test_the_metadata_reader_reads_only_the_credential_free_record(tmp_path, monkeypatch):
    fixture = _metadata_store(tmp_path, monkeypatch)
    assert gts.jail_credential_expiry() == fixture.expires_at


@pytest.mark.parametrize("bad", ["stale", "absent", "mode", "keys", "subscription",
                                 "symlinked_auth"])
def test_absent_malformed_or_stale_metadata_refuses(tmp_path, monkeypatch, bad):
    fixture = _metadata_store(tmp_path, monkeypatch)
    if bad == "stale":
        with open(fixture.auth, "ab") as handle:  # signed in again after the record
            handle.write(b" refreshed")
    elif bad == "absent":
        fixture.meta.unlink()
    elif bad == "mode":
        fixture.meta.chmod(0o640)
    elif bad in ("keys", "subscription"):
        document = json.loads(fixture.meta.read_text())
        if bad == "keys":
            document["token"] = "never"
        else:
            document["subscription"] = "yes"
        fixture.meta.write_text(json.dumps(document))
    else:
        fixture.auth.rename(fixture.store / "real.json")
        fixture.auth.symlink_to(fixture.store / "real.json")
    with pytest.raises(gts.MeasurementRefused) as caught:
        gts.jail_credential_expiry()
    assert caught.value.code == "credential_metadata_unavailable"


def _second_grant(bench, name="second"):
    code, report = bench.cli("--new-grant", "--planned", "pilot,planted,confirm",
                             "--retries", "0", "--hosted-check", HOSTED, grant=name)
    assert code == 0, report
    bench.runner.plan.insert(0, Launch(events=(_event("deny", "budget"),), exit=1))
    assert bench.cli("--attended", "--rehearse", "--route", "staged", grant=name)[0] == 0
    bench.runner.plan.extend([_measured(), _measured(), _measured()])
    out = bench.output
    bench.output = out.parent / ("out-" + name)
    try:
        assert bench.cli("--attended", *(["--route", "staged"] * 3), grant=name)[0] == 0
        code, report = bench.cli("--aggregate", grant=name)
        assert code == 0 and report["published"] == ["staged"], report
    finally:
        bench.output = out


def test_a_stale_aggregate_leaves_the_other_grants_publication(bench):
    _three(bench)
    assert bench.cli("--aggregate")[0] == 0
    _second_grant(bench)
    published = bench.jail_record()
    code, report = bench.cli("--aggregate")
    assert code == 0 and report["published"] == [] and report["superseded"]
    assert bench.jail_record() == published
    assert gjs.resolve_record(bench.digest, gjs.staged_argv_digest()) is not None


def test_a_refused_stale_aggregate_leaves_the_other_grants_publication(bench, monkeypatch):
    _three(bench)
    _second_grant(bench)
    published = bench.jail_record()
    monkeypatch.setattr(seat_window, "runtime_digest", lambda: "f" * 64)
    code, report = bench.cli("--aggregate")
    assert (code, report["code"]) == (1, "context_mismatch")
    assert bench.jail_record() == published


def test_the_final_check_refuses_another_grants_publication_and_writes_no_receipt(bench):
    receipt = Path(pa.private_record_root()) / gjs.receipt_name(bench.digest,
                                                                gjs.staged_argv_digest())
    _three(bench)
    assert bench.cli("--aggregate")[0] == 0
    _second_grant(bench)
    code, report = bench.cli("--verify-probe", "final")
    assert (code, report["code"]) == (1, "publication_of_another_grant")
    assert not receipt.exists()


def test_the_final_check_needs_exactly_one_staged_row(bench, monkeypatch):
    _three(bench)
    assert bench.cli("--aggregate")[0] == 0
    real = gts._probe_rows
    monkeypatch.setattr(gts, "_probe_rows",
                        lambda *a, **k: [row for row in real(*a, **k) if row["route"] != "staged"])
    code, report = bench.cli("--verify-probe", "final")
    assert (code, report["code"]) == (1, "probe_mismatch")


def test_the_procedure_code_block_is_valid_bash():
    doc = Path(__file__).resolve().parents[2] / "docs" / "ops" / "grok-jail-measurement.md"
    if not doc.exists():
        pytest.skip("repo-only: the clean-room wheel tree has no docs/")
    text = doc.read_text(encoding="utf-8")
    block = text.split("```bash\n", 1)[1].split("```", 1)[0]
    done = subprocess.run(["bash", "-n"], input=block.encode(), capture_output=True,
                          timeout=30)
    assert done.returncode == 0, done.stderr.decode()
    for needed in ("GROK_SLOT_END_EPOCH", "credential-metadata.json", "VL2",
                   "erratum 8", "MemorySwapMax=0", "Gemini"):
        assert needed in text, needed


def test_an_unverified_post_run_admission_stays_unresolved(bench):
    """E1: the leg returns after its strict marker lookup fails, while the conservative
    charge check sees the marker and the proxy shows a complete zero-count proof. The
    reservation is never settled: charged in full, unresolved, nothing read, grant stopped."""
    bench.opened()
    reads = bench.runner.reads
    code, report = bench.launch(Launch(strict_missing=True, events=(), complete=True))
    assert code == 1 and report["routes"][0]["status"] != "unspawned"
    reservation = report["routes"][0]["reservation"]
    assert not (bench.grant_dir() / "settlements" / f"{reservation}.json").exists()
    status = bench.status()
    assert status["charged"] == 1 and status["unresolved"] == [reservation]
    assert bench.runner.reads == reads and status["stopped"] is True
    code, report = bench.launch(_measured())
    assert (code, report["routes"][0]["code"]) == (1, "reservation_unresolved")


def test_an_unverified_post_run_admission_fails_the_rehearsal(bench):
    assert bench.new_grant()[0] == 0
    code, report = bench.rehearse(Launch(strict_missing=True, exit=1, text="",
                                         events=(_event("deny", "budget"),)))
    assert (code, report["result"], report["reason"]) == (1, "failed", "launch_failed")


def test_the_measurement_leg_runs_inside_a_live_seat_scope(bench):
    """The jailed branch's capped launch needs a live seat key; the measurement holds the
    per-seat resource scope around its whole launch, and the leg reaches the hook in it."""
    from phase_loop_runtime import seat_resource_caps

    bench.opened()
    code, _report = bench.launch(_measured())
    assert code == 0 and bench.runner.seat_keys and all(bench.runner.seat_keys)
    assert all(key.startswith("measure:grok:") for key in bench.runner.seat_keys)
    assert "hook" in bench.runner.order and seat_resource_caps.live_seat_key() == ""


# --- The procedure script ------------------------------------------------------------------


def test_the_procedure_script_runs_end_to_end(bench):
    """``docs/ops/grok-jail-measurement.md``'s stages, in order, on the recording runner:
    grant, rehearsal, its gate, the pilot and its gate, planted and confirm, aggregate,
    the grant-backed final check, status."""
    doc = Path(__file__).resolve().parents[2] / "docs" / "ops" / "grok-jail-measurement.md"
    if doc.exists():  # repo-only: the clean-room wheel tree has no docs/
        text = doc.read_text(encoding="utf-8")
        for stage in ("--new-grant", "--rehearse", "--require-rehearsed staged",
                      "--route staged", "--require-measured staged", "--aggregate",
                      "--verify-probe final", "--status"):
            assert stage in text, stage
    assert bench.new_grant()[0] == 0
    assert bench.rehearse()[0] == 0
    assert bench.cli("--require-rehearsed", "staged")[0] == 0
    assert bench.launch(_measured())[0] == 0
    code, report = bench.cli("--require-measured", "staged")
    assert code == 0 and report["label"] == "pilot"
    assert bench.launch(_measured(), _measured(), routes=2)[0] == 0
    assert bench.cli("--require-measured", "staged")[1]["label"] == "confirm"
    assert bench.cli("--aggregate")[0] == 0
    code, report = bench.cli("--verify-probe", "final")
    assert code == 0 and report["passed"], report
    status = bench.status()
    assert status["charged"] == 3 and status["stopped"] is False


# --- The no-hook call shape of _run_leg_with_liveness is unchanged ------------------------


def test_a_launch_without_a_hook_keeps_its_old_call_shape(tmp_path, monkeypatch):
    """Only a prepared Grok measurement passes ``spawn_hook``; every other jailed launch
    reaches ``launch_provider`` with exactly the keywords it had before SL-4, so a launch
    callable that does not accept ``spawn_hook`` still works."""
    built = _build(tmp_path / "shape")
    seen: list = []

    def launch_provider(argv, *, process_owner, probe_owner, env, stdin, stdout, stderr,
                        start_new_session, trace_output, seat_caps):
        seen.append(sorted(locals()))
        return subprocess.Popen(["/bin/echo", "shape"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)

    monkeypatch.setattr(pi, "launch_provider", launch_provider)
    try:
        proc = pi._run_leg_with_liveness(["/bin/echo", "shape"], cwd="/seat/tree", env={},
                                         deadline_s=30, seat_jail=built.jail,
                                         probe_jail=built.jail)
    finally:
        seat_jail.close_jail_fds(built.jail)
    assert proc.returncode == 0 and len(seen) == 1
    assert "spawn_hook" not in seen[0]
