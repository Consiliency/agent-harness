"""Lane L2b of the grok tool-surface plan: the measurement tool, ``seat-window measure-tools``
(plans/artifacts/grok-tool-surface-contract-v1.md section 5, and BA-1, BA-2 and the
measurement path of BA-3 in section 10).

No test contacts the vendor or runs a model. Most tests drive the real stage code over a
recording runner and a fake transport (:class:`Bench`): the stand-in grok binary is never
executed, ``_grok_review_egress`` yields a real :class:`SeatEgressProxy` whose observation the
scenario sets, and ``launch_owned`` is a recording child that writes the session artifact.
``seat_profile``, the measurement admission, the context checks, the ledger, the records and
the aggregation are the real code. Two tests run the real launch-owner composition, the real
proxy and the proxy-only namespace against a loopback fixture upstream (BA-3); they skip
where those prerequisites are absent, and ``PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1`` makes a
missing prerequisite fail.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import grok_tool_surface as gts
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import president_adapter as pa
from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_window

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "grok_1_0_89"
HELP = (FIXTURES / "help.out").read_text()
VERSION = (FIXTURES / "version.out").read_text()
SENTINEL = "SENTINEL-credential-7f3a9c41"
GRANT = "D4-grok-test"
HOSTED_RUN = "https://github.com/example/agent-harness/actions/runs/123456789"
PREFIX = ("nsenter", "-t", "4242", "--net", "--")
OTHER_HOLDER = ("nsenter", "-t", "4343", "--net", "--")
INFERENCE_PATH = "/v1/chat/completions"
ALLOWED = ("POST", gts.INFERENCE_HOST, INFERENCE_PATH, "allow")
#: What a budget-0 proxy makes of the model request: a refused allow-listed counted request.
BUDGET_DENIED = ("POST", gts.INFERENCE_HOST, INFERENCE_PATH, "deny", "budget")
#: The same request refused by the inner Host check, before the budget (fix round 2).
INNER_HOST_DENIED = ("POST", gts.INFERENCE_HOST, INFERENCE_PATH, "deny", "inner_host")
SETTINGS = ("GET", gts.INFERENCE_HOST, "/v1/settings", "deny")
UPDATER = ("CONNECT", "x.ai", None, "deny")
ARTIFACTS = ("CONNECT", "storage.googleapis.com", None, "deny")
SEAT = gts.MEASURED_ROUTES
REFUSED = "grok_tool_surface_unverified"
#: The two images of the tolerated map (errata 3 and 8), by binary sha256.
GROK_1_0_89 = "a3dface51d9bdc71fd121e0481dd02d9b46a721f7a6b892f756480e9666eba1f"
GROK_1_0_92 = "add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb"
#: The map as shipped, before any bench stands its stand-in binary for an image.
SHIPPED_TOLERATED = gts.TOLERATED_REFUSALS_BY_IMAGE
LEGACY_TOLERATED = SHIPPED_TOLERATED[GROK_1_0_89]
#: The real BA-3 binding check, before any bench models it.
REAL_BRIDGED_TO = gts.bridged_to


def _form(route):
    return pi.grok_runtime_forms()[route]


def _tools(route):
    """What an admitted surface of the form offers: exactly its allow-list."""
    return sorted(pi._grok_allowed_tools(_form(route)))


def _s2(names, extra=""):
    return json.dumps([{"type": "function", "function": {
        "name": name, "description": "fixture tool " + extra, "parameters": {}}}
        for name in names]).encode()


@dataclass
class Scenario:
    """What the fake transport and the recording child do for one launch."""

    requests: list = field(default_factory=lambda: [ALLOWED])
    artifact: object = "admitted"  # "admitted", None, bytes, "two", "symlink"
    exit: int = 0
    orderly: bool = True
    killed: bool = False
    proxy_returncode: int = 0
    truncated: bool = False
    hang: bool = False
    change_binary: bool = False
    egress_fails: bool = False
    block: str | None = None
    #: The egress hands back a live holder that does not bridge to its proxy (BA-3).
    crossed: bool = False
    #: The launch path refuses before it creates the process (the holder went away).
    refuse_in_launch_path: bool = False


class _Stdin:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, scenario):
        self.scenario = scenario
        self.returncode = None
        self.stdin = _Stdin()
        self.pid = 0

    def wait(self, timeout=None):
        if self.scenario.hang:
            raise subprocess.TimeoutExpired("grok", timeout)
        self.returncode = self.scenario.exit
        return self.returncode

    def poll(self):
        return self.returncode


class Bench:
    """A host for the measurement: a stand-in grok binary on the provider path (never
    executed), a private state home, an operator HOME holding a planted sentinel credential,
    a fake transport, a recording child, and a stand-in runner for ``--help`` and
    ``--version`` that answers with the real 1.0.89 outputs. The stand-in binary stands for
    the release image ``image`` in the tolerated map (:meth:`stand_for`)."""

    def __init__(self, root: Path, patch, *, real: bool = False, image: str | None = GROK_1_0_89):
        self.root = root
        self.patch = patch
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        self.binary = bin_dir / "grok"
        if not self.binary.exists():
            self.binary.write_bytes(b"\x7fELF grok 1.0.89 stand-in, never executed\n")
            self.binary.chmod(0o755)
        self.state = root / "state"
        patch.setenv("XDG_STATE_HOME", str(self.state))
        home = root / "home"
        if not home.exists():
            (home / ".grok").mkdir(parents=True)
            for name, body in ((".grok/auth.json", json.dumps({"key": SENTINEL})),
                               (".grok/agent_id", "agent-" + SENTINEL)):
                (home / name).write_text(body)
                (home / name).chmod(0o600)
        self.env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "LANG": "C.UTF-8"}
        self.output = self.state / "phase-loop" / "grok-surface" / GRANT
        ca = root / "egress-ca.crt"
        if not ca.exists():
            ca.write_text(ssl.DER_cert_to_PEM_cert(b"phase-loop measure CA " + os.urandom(8)))
        self.ca = ca
        self.ca_sha256 = sha256(ssl.PEM_cert_to_DER_cert(ca.read_text())).hexdigest()
        self.scenarios: dict[str, Scenario] = {}
        self.default = Scenario()
        #: What a rehearsal's child does (erratum 4): its model request is refused.
        self.rehearsal = Scenario(requests=[BUDGET_DENIED], artifact=None, exit=1)
        self.rehearsals: list = []
        self.current = self.default
        self.route = None
        self.launches: list = []
        self.proxies: list = []
        #: ``{"function": <one of the reservation steps>, "route": ..., "file": ...}``: block
        #: (for a SIGKILL from the test) just before that step runs for that route.
        self.block_at = None
        #: The holder each fake proxy's bridge serves; the fake ``bridged_to`` reads it.
        self.pairs: dict[int, tuple[str, ...]] = {}
        patch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
        patch.setattr(pi, "_subscription_env", lambda base_env=None: dict(self.env))
        patch.setattr(pi, "run_provider", self.run_provider)
        patch.setattr(gts, "isolation_check",
                      lambda **kwargs: {"passed": True, "code": "isolation_proven"})
        real_run = gts._run_reserved

        def run_reserved(stage, reservation, **kwargs):
            self.route = kwargs["route"]
            self.current = self.scenarios.get(self.route, self.default)
            return real_run(stage, reservation, **kwargs)
        patch.setattr(gts, "_run_reserved", run_reserved)
        real_rehearse = gts.rehearse

        def rehearse(stage, route):
            self.route, self.current = route, self.rehearsal
            return real_rehearse(stage, route)
        patch.setattr(gts, "rehearse", rehearse)
        def blocking(name, route_of):
            real_step = getattr(gts, name)

            def step(*args):
                block = self.block_at
                if block and block["function"] == name and route_of(*args) == block["route"]:
                    Path(block["file"]).write_text("ready")
                    time.sleep(3600)
                return real_step(*args)
            patch.setattr(gts, name, step)
        digests = {pi._grok_argv_digest(_form(route)): route for route in SEAT}
        blocking("_plan_reservation", lambda ledger, route, argv_digest, context: route)
        blocking("_record_attempt", lambda root, grant, reservation: reservation.route)
        blocking("_withdraw", lambda root, binary, argv_digest: digests.get(argv_digest))
        blocking("_write_reservation", lambda directory, grant, reservation: reservation.route)
        if not real:
            patch.setattr(gts, "bridged_to",
                          lambda prefix, proxy: self.pairs.get(id(proxy)) == tuple(prefix))
            patch.setattr(pi, "_grok_review_egress", self.egress)
            patch.setattr(pi, "launch_owned", self.launch_owned)
            patch.setattr(pi, "_terminate_process_group", lambda process, **kwargs: None)
            patch.setattr(pi, "_filtered_holder_namespace", lambda: 1)
            patch.setattr(seat_egress_proxy, "unavailable_reason", lambda: None)
            patch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)
        self.stand_for(image)

    @property
    def digest(self):
        return sha256(self.binary.read_bytes()).hexdigest()

    def stand_for(self, image: str | None):
        """The stand-in binary stands for the release image ``image`` (erratum 8): its own
        digest, which the grant pins, reads that image's entries of the tolerated map through
        the real lookup. ``None`` leaves it an image the map does not hold. Call it again
        after rewriting the binary."""
        self.image = image
        table = dict(SHIPPED_TOLERATED)
        if image is not None:
            table[self.digest] = SHIPPED_TOLERATED[image]
        self.patch.setattr(gts, "TOLERATED_REFUSALS_BY_IMAGE", table)

    # -- the stand-ins
    def run_provider(self, argv, **options):
        """Answers as grok 1.0.89 does, in text or, with ``text=False``, in bytes."""
        def answer(rc, out, err):
            if options.get("text") is False:
                return subprocess.CompletedProcess(argv, rc, out.encode(), err.encode())
            return subprocess.CompletedProcess(argv, rc, out, err)
        if argv[-1] == "--help":
            return answer(0, HELP, "")
        if argv[-1] == "--version":
            return answer(0, VERSION, "")
        return answer(2, "", "error: unexpected argument\n")

    def proxy_object(self, *, budget=1, **overrides):
        values = dict(socket="/fixture/proxy.sock",
                      proxy_url="http://srt:fixture-proxy-token@127.0.0.1:3128",
                      ca_cert=self.ca, ca_sha256=self.ca_sha256, inner_sni_check=True,
                      process=SimpleNamespace(poll=lambda: None),
                      allowlist_id=gts.EGRESS_ALLOWLIST_ID,
                      allowlist_digest=gts.egress_allowlist_digest(), request_budget=budget)
        values.update(overrides)
        return seat_egress_proxy.SeatEgressProxy(**values)

    @contextlib.contextmanager
    def egress(self, *, timeout_s, request_budget=None, named=()):
        scenario = self.current
        if scenario.egress_fails:
            raise sandbox_egress.EgressUnavailable("seat_filtered_egress_unavailable")
        proxy = self.proxy_object(budget=request_budget, named=tuple(named))
        self.proxies.append(proxy)
        self.pairs[id(proxy)] = PREFIX
        try:
            # A crossed pair: a live holder whose bridge serves another proxy.
            yield proxy, (OTHER_HOLDER if scenario.crossed else PREFIX)
        finally:
            with proxy._cond:
                proxy._eof = True
                proxy._exited = True
                proxy._killed = scenario.killed
                proxy._returncode = -9 if scenario.killed else scenario.proxy_returncode
                if scenario.truncated:
                    proxy._protocol_error = True
                if (scenario.orderly and not scenario.killed and not scenario.truncated
                        and proxy.request_budget is not None):
                    events = [item[1] for item in proxy._items if item[0] == "request"]
                    proxy._end = {"event": "end", "requests": len(events),
                                  "counted": sum(1 for event in events
                                                 if event.decision == "allow"
                                                 and event.method == "POST"),
                                  "budget": proxy.request_budget}

    def launch_owned(self, argv, *, role, profile, **kwargs):
        scenario = self.current
        proxy = self.proxies[-1]
        if scenario.refuse_in_launch_path:
            # A definite refusal inside the real launch path, before any process exists.
            raise sandbox_egress.EgressUnavailable("seat_filtered_egress_unavailable")
        # The real launch path calls this at the spawn itself, immediately before Popen.
        hook = kwargs.pop("spawn_hook", None)
        if hook is not None:
            hook()
        (self.rehearsals if proxy.request_budget == 0 else self.launches).append(SimpleNamespace(
            argv=list(argv), role=role, profile=profile, kwargs=kwargs, route=self.route, proxy=proxy,
            admission=gts.measurement_admission(), prefix=tuple(pi._EGRESS_LAUNCH_PREFIX.get()),
            record=self.host_record(), gate=self.gate(self.route), process=None))
        for method, host, path, decision, *cause in scenario.requests:
            # The budgeted proxy says which check decided; unless the scenario names it, an
            # allow is "allowed", a refused CONNECT "front" and any other refusal "rules".
            cause = cause[0] if cause else ("allowed" if decision == "allow" else
                                            "front" if method == "CONNECT" else "rules")
            proxy._items.append(("request", seat_egress_proxy.RequestEvent(
                method=method, host=host, path=path, decision=decision, cause=cause)))
        args = list(profile.mount_args)
        sessions = Path(next(args[index + 1] for index, word in enumerate(args)
                             if word == "--bind" and args[index + 2].endswith("/.grok/sessions")))
        artifact = scenario.artifact
        if artifact is not None:
            session = sessions / "-encoded-cwd" / "session-0001"
            session.mkdir(parents=True)
            target = session / "tool_definitions.json"
            if artifact == "admitted":
                target.write_bytes(_s2(_tools(self.route), extra=SENTINEL))
            elif artifact == "two":
                target.write_bytes(_s2(_tools(self.route)))
                other = sessions / "-encoded-cwd" / "session-0002"
                other.mkdir()
                (other / "tool_definitions.json").write_bytes(_s2(_tools(self.route)))
            elif artifact == "symlink":
                (session / "elsewhere.json").write_bytes(_s2(_tools(self.route)))
                target.symlink_to(session / "elsewhere.json")
            else:
                target.write_bytes(artifact)
        os.write(kwargs["stdout"], f"provider output {SENTINEL}\n".encode())
        if scenario.change_binary:
            self.binary.write_bytes(self.binary.read_bytes() + b"changed\n")
        if scenario.block:
            Path(scenario.block).write_text("ready")
            time.sleep(3600)
        process = FakeProcess(scenario)
        (self.rehearsals if proxy.request_budget == 0 else self.launches)[-1].process = process
        return process

    # -- inspection
    def host_record(self):
        path = pa.private_record_root() / gts.host_record_name(self.digest)
        return json.loads(path.read_text()) if path.exists() else None

    def gate(self, route):
        if route is None:
            return None
        return pi.grok_tool_gate(_form(route), self.env)

    def probe(self, route):
        command = _form(route)
        return pi.probe_grok_tools(command, allowed_tools=pi._grok_allowed_tools(command))

    def args(self, *argv, output=None, grant=GRANT, binary=None, expected=None):
        parser = argparse.ArgumentParser()
        seat_window.register_parser(parser.add_subparsers(dest="command"))
        return parser.parse_args([
            "seat-window", "measure-tools", "--vendor", "grok", "--grant", grant,
            "--binary", str(binary or self.binary),
            "--expect-binary-sha256", expected or self.digest,
            "--output", str(output or self.output), *argv])

    def cli(self, *argv, **kwargs):
        return gts.measure_tools_cli(self.args(*argv, **kwargs))

    def open_grant(self, planned="review,sealed,staged", retries=2, *, rehearse=True, **kwargs):
        code, report = self.cli("--new-grant", "--planned", planned, "--retries", str(retries),
                                "--hosted-check", HOSTED_RUN, **kwargs)
        assert code == 0, report
        if rehearse:  # erratum 4: no reservation without a passing rehearsal
            code, rehearsal = self.cli("--attended", "--rehearse", "--route",
                                       planned.split(",")[0], **kwargs)
            # The whole refusal, untruncated: on an incomplete observation it names what was
            # missing (CI fixes 2).
            assert code == 0 and rehearsal["result"] == "passed", json.dumps(
                rehearsal, sort_keys=True, default=str)
        return report

    def measure(self, *routes, **kwargs):
        argv = ["--attended"]
        for route in routes:
            argv += ["--route", route]
        return self.cli(*argv, **kwargs)

    def status(self, **kwargs):
        code, report = self.cli("--status", **kwargs)
        assert code == 0, report
        return report

    def grant_dir(self, grant=GRANT):
        return pa.private_record_root() / gts.GRANTS_DIRNAME / grant

    def results(self, output=None):
        folder = Path(output or self.output) / "results"
        return {path.name: json.loads(path.read_text()) for path in sorted(folder.glob("*.json"))}


@pytest.fixture
def bench(tmp_path, monkeypatch):
    return Bench(tmp_path, monkeypatch)


def _route_rows(report):
    return {row["route"]: row for row in report["routes"]}


# ===================================================================== the procedure

def test_the_owner_procedure_runs_end_to_end_offline(bench):
    """Contract §5.10 steps 2-8 on the fake transport: baseline, grant, pilot, gate on the
    pilot, the two other seat forms, aggregate and publish, the final probe, status."""
    code, report = bench.cli("--verify-probe", "initial")
    assert code == 0 and report["passed"], report
    assert all(row["basis"] == "none" and not row["passed"] for row in report["routes"])
    bench.open_grant()
    code, report = bench.measure("review")
    assert code == 0 and _route_rows(report)["review"]["status"] == "measured", report
    code, report = bench.cli("--require-measured", "review")
    assert code == 0 and report["status"] == "measured"
    code, report = bench.measure("sealed", "staged")
    assert code == 0 and [row["status"] for row in report["routes"]] == ["measured", "measured"]
    code, report = bench.cli("--aggregate")
    assert code == 0 and report["published"] == list(SEAT) and report["superseded"] == []
    code, report = bench.cli("--verify-probe", "final")
    assert code == 0 and report["passed"], report
    rows = {row["route"]: row for row in report["routes"]}
    assert all(rows[route]["basis"] == "frozen_measurement" and rows[route]["source"] == "host_local"
               for route in SEAT)
    assert not rows["execute"]["passed"] and not rows["workflow"]["passed"]
    status = bench.status()
    assert status["charged"] == 3 and status["launches"] == 3 and status["retries_used"] == 0
    assert [row["state"] for row in status["routes"]] == ["recorded"] * 3
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    assert evidence["schema"] == "grok_tool_surface_evidence.v1"
    assert evidence["grant"] == {"id": GRANT, "planned": 3, "retries": 2, "cap": 7, "charged": 3,
                                 "other_grants_for_binary": 0}
    assert evidence["account_scope"] == "unbound" and evidence["method"] == "session_artifact"
    assert evidence["egress"] == {"allowlist_id": "grok-review",
                                  "allowlist_sha256": gts.egress_allowlist_digest()}
    assert [route["status"] for route in evidence["routes"]] == ["measured"] * 3
    assert all(route["eligible"] and route["admitted"] for route in evidence["routes"])


def test_the_cli_is_wired_into_seat_window(bench, capsys):
    bench.open_grant()
    code = seat_window.cli_main(bench.args("--status"))
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["status"] == "ok" and report["grant"]["grant"] == GRANT


@pytest.mark.parametrize("argv", [(), ("--status", "--aggregate"),
                                  ("--status", "--route", "review"),
                                  ("--rehearse", "--status", "--route", "review")])
def test_exactly_one_stage_per_invocation(bench, argv):
    code, report = bench.cli(*argv)
    assert code == 2 and report["code"] == "one_stage_required"


def test_a_launch_stage_needs_attendance(bench):
    bench.open_grant()
    code, report = bench.cli("--route", "review")
    assert code == 1 and report["code"] == "attendance_required"
    assert bench.status()["launches"] == 0


# ============================================================ the launch (§5.1, §5.4)

def test_the_launch_argv_is_the_form_with_only_its_masked_slots_filled(bench):
    bench.open_grant()
    assert bench.measure(*SEAT)[0] == 0
    assert [launch.route for launch in bench.launches] == list(SEAT)
    for launch in bench.launches:
        form = _form(launch.route)
        assert launch.argv[0] == "/run/phase-loop-seat/provider"
        assert len(launch.argv) == len(form)
        assert pi._grok_argv_digest(launch.argv) == pi._grok_argv_digest(form)
        changed = {form[index - 1] for index in range(1, len(form)) if launch.argv[index] != form[index]}
        assert changed <= {"-p", "--cwd"}
        assert launch.role is pi.SeatLaunchRole.PROVIDER_REVIEW
        assert launch.prefix == PREFIX
        assert launch.admission.proxy is launch.proxy and launch.admission.egress_prefix == PREFIX
        assert launch.admission.argv_digest == pi._grok_argv_digest(form)
        if launch.route == "review":
            assert launch.argv[launch.argv.index("-p") + 1] == gts.MEASUREMENT_PROMPT
            assert launch.kwargs["stdin"] == subprocess.DEVNULL
        else:
            assert launch.kwargs["stdin"] == subprocess.PIPE
            assert launch.process.stdin.data == gts.MEASUREMENT_PROMPT.encode()
        cwd = launch.argv[launch.argv.index("--cwd") + 1]
        assert cwd == launch.kwargs["cwd"] and not os.path.exists(cwd)  # removed in finally
    assert all(launch.proxy.request_budget == 1 for launch in bench.launches)


def test_the_launch_composes_the_seat_profile_with_the_proxy_and_the_sessions_bind(bench):
    bench.open_grant(planned="review")
    assert bench.measure("review")[0] == 0
    (launch,) = bench.launches
    profile = launch.profile
    home = gts.PRIVATE_HOME
    args = list(profile.mount_args)
    assert args[:2] == ["--tmpfs", home]
    assert profile.env["HTTPS_PROXY"] == launch.proxy.proxy_url
    assert profile.env["SSL_CERT_FILE"] == home + "/.phase-loop-seat-egress-ca.pem"
    binds = [args[index + 1:index + 3] for index, word in enumerate(args) if word == "--bind"]
    assert len(binds) == 1 and binds[0][1] == home + "/.grok/sessions"
    assert not any(key.startswith(("GROK_", "XAI_")) for key in profile.env)
    assert profile.dependency is None


def test_the_measurement_admission_admits_only_its_own_launch(bench, tmp_path):
    form = gts.launch_argv(_form("review"), cwd=str(tmp_path))
    argv = [str(bench.binary), *form[1:]]
    proxy = bench.proxy_object()
    bench.pairs[id(proxy)] = PREFIX

    def admission(**overrides):
        values = dict(argv_digest=pi._grok_argv_digest(form), binary_sha256=bench.digest,
                      egress_prefix=PREFIX, proxy=proxy, issuer=gts._ISSUER)
        values.update(overrides)
        return gts.MeasurementAdmission(**values)

    @contextlib.contextmanager
    def egress(prefix):
        token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
        try:
            yield
        finally:
            pi._EGRESS_LAUNCH_PREFIX.reset(token)

    def admitted(held, prefix=PREFIX, command=argv):
        with gts._holding(held), egress(prefix):
            try:
                return pi.require_grok_admission(command, bench.env)
            except pi._seat_jail.SeatSandboxRefused as refusal:
                assert refusal.code == REFUSED
                return False

    # Without an admission the gate is today's: no receipt, no launch.
    with pytest.raises(pi._seat_jail.SeatSandboxRefused):
        pi.require_grok_admission(argv, bench.env)
    assert admitted(admission()) is True
    # The admission refuses without an egress prefix, and with any namespace not its proxy's.
    assert admitted(admission(), prefix=()) is False
    assert admitted(admission(), prefix=("nsenter", "-t", "999", "--net", "--")) is False
    # The measurement admission without its own proxy refuses (deferred from lane L2a).
    assert admitted(admission(proxy=bench.proxy_object(budget=None))) is False
    assert admitted(admission(proxy=None)) is False
    assert admitted(admission(proxy=bench.proxy_object(process=SimpleNamespace(poll=lambda: 0)))) is False
    assert admitted(admission(proxy=bench.proxy_object(allowlist_id="gemini"))) is False
    assert admitted(admission(proxy=bench.proxy_object(allowlist_digest="b" * 64))) is False
    assert admitted(admission(proxy=bench.proxy_object(budget=2))) is False
    # BA-3: a different live proxy with the same policy and budget, whose bridge serves
    # another holder, refuses; and so does a live holder whose bridge serves another proxy.
    other = bench.proxy_object()
    bench.pairs[id(other)] = OTHER_HOLDER
    assert admitted(admission(proxy=other)) is False
    assert admitted(admission(egress_prefix=OTHER_HOLDER), prefix=OTHER_HOLDER) is False
    assert admitted(admission(proxy=other, egress_prefix=OTHER_HOLDER), prefix=OTHER_HOLDER)
    # Its own argv form and binary only.
    assert admitted(admission(), command=[str(bench.binary), *_form("sealed")[1:]]) is False
    assert admitted(admission(binary_sha256="c" * 64)) is False
    with pytest.raises(TypeError):
        gts.MeasurementAdmission(argv_digest="a" * 64, binary_sha256=bench.digest,
                                 egress_prefix=PREFIX, proxy=proxy)
    # Admin commands stay outside the gate, held or not.
    with gts._holding(admission()):
        assert pi.require_grok_admission([str(bench.binary), "--help"], bench.env) is False


def test_without_a_measurement_admission_listing_receipts_keep_their_meaning(bench):
    command = _form("review")
    pi.record_tool_probe(command, {"tools": _tools("review"), "diagnostics": []},
                         allowed_tools=pi._grok_allowed_tools(command), version=VERSION)
    assert pi.require_grok_admission(command, bench.env) is True


def test_the_sessions_keyword_adds_one_bind_and_nothing_else(bench, tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir(mode=0o700)
    proxy = bench.proxy_object()

    def compose(**kwargs):
        with pi.seat_profile(harness="grok", executable=str(bench.binary), env=bench.env,
                             cwd=tmp_path, **kwargs) as (destination, profile):
            args = list(profile.mount_args)
            for index, word in enumerate(args[:-1]):
                if word in {"--file", "--ro-bind-data"}:
                    args[index + 1] = "<fd>"
            return destination, args, dict(profile.env), profile

    plain = compose()
    assert compose(grok_sessions=None)[1:3] == plain[1:3]
    with_sessions = compose(grok_sessions=str(sessions))
    args = with_sessions[1]
    start = args.index("--bind")
    assert args[start + 2] == gts.PRIVATE_HOME + "/.grok/sessions"
    assert os.path.realpath(args[start + 1]) == os.path.realpath(sessions)
    assert args[:start] + args[start + 3:] == plain[1] and with_sessions[2] == plain[2]
    assert "--bind" not in plain[1]
    with pytest.raises(ValueError):
        with pi.seat_profile(harness="codex", executable=str(bench.binary), env=bench.env,
                             cwd=tmp_path, grok_sessions=str(sessions)):
            pytest.fail("a non-grok profile took a sessions directory")
    # The home check takes the bind only for a measurement, and only that one.
    projected = compose(egress_proxy=proxy, grok_sessions=str(sessions))[3]
    gts._check_home(projected, str(sessions))
    with pytest.raises(gts._Refused):
        gts._check_home(projected)  # a launch relying on a record may not carry it
    with pytest.raises(gts._Refused):
        gts._check_home(projected, str(tmp_path))


def test_the_proxy_projection_constants_are_lane_l2as(bench):
    assert gts.PROXY_PROJECTED_PATHS == (pi._SEAT_EGRESS_CA_RELATIVE,)
    assert gts.PROXY_ENVIRONMENT == (seat_egress_proxy.SEAT_PROXY_ENV, seat_egress_proxy.SEAT_CA_ENV)
    assert gts.SESSIONS_RELATIVE == ".grok/sessions"


# ============================================================ each status (§5.5, §5.8)

def _managed_config_appears(bench, monkeypatch, tmp_path):
    managed = tmp_path / "etc-grok" / "managed_config.toml"
    monkeypatch.setattr(gts, "MANAGED_CONFIG_PATHS", (str(managed),))
    real = pi.seat_profile

    @contextlib.contextmanager
    def seat_profile(**kwargs):
        # It appears only for the measurement's own composition (budget 1), after the
        # rehearsal passed under the same context.
        proxy = kwargs.get("egress_proxy")
        if proxy is not None and proxy.request_budget == 1:
            managed.parent.mkdir(exist_ok=True)
            managed.write_text("")
        with real(**kwargs) as composed:
            yield composed
    monkeypatch.setattr(pi, "seat_profile", seat_profile)


STATUS_CASES = {
    "measured": Scenario(),
    "format_unrecognised": Scenario(artifact=b'{"functions": [{"name": "x"}]}'),
    "artifact_missing": Scenario(artifact=None),
    "artifact_ambiguous": Scenario(artifact="two"),
    "artifact_symlink": Scenario(artifact="symlink"),
    "launch_failed": Scenario(exit=1),
    "launch_timeout": Scenario(hang=True),
    "egress_refused": Scenario(requests=[ALLOWED, ("GET", gts.INFERENCE_HOST, "<other>", "deny")]),
    "bypass": Scenario(requests=[]),
    "tls_failure": Scenario(requests=[], exit=1, artifact=b"[]"),
    "egress_layer_failed": Scenario(egress_fails=True),
    "budget_exhausted": Scenario(requests=[ALLOWED, BUDGET_DENIED]),
    "identity_changed": Scenario(change_binary=True),
    "context_refused": Scenario(),
}
EXPECTED_STATUS = {
    "artifact_symlink": "artifact_ambiguous", "launch_timeout": "launch_failed",
    "bypass": "egress_refused", "tls_failure": "egress_refused",
    "egress_layer_failed": "egress_refused",
}


@pytest.mark.parametrize("case", list(STATUS_CASES))
def test_each_status_is_a_recorded_result(bench, monkeypatch, tmp_path, case):
    if case == "context_refused":
        _managed_config_appears(bench, monkeypatch, tmp_path)
    bench.open_grant(planned="review")
    original = bench.binary.read_bytes()
    bench.default = STATUS_CASES[case]
    code, report = bench.measure("review", expected=bench.digest)
    expected = EXPECTED_STATUS.get(case, case)
    row = _route_rows(report)["review"]
    # A recorded unsuccessful route is a result, not a script error (§5.10).
    assert code == 0 and row["reserved"] and row["status"] == expected, report
    (result,) = bench.results().values()
    assert result["status"] == expected
    assert sorted(result) == sorted(gts.RESULT_KEYS)
    if expected == "measured":
        assert result["tools"] == _tools("review") and result["shape"] == "S2" and result["admitted"]
    else:
        assert result["tools"] is None or expected == "format_unrecognised"
    if case == "context_refused":
        assert bench.launches == []  # refused after composition: nothing launched
    if case == "identity_changed":
        bench.binary.write_bytes(original)  # every later stage measures it again
    status = bench.status()
    assert _route_rows(status)["review"] == {"route": "review", "state": "recorded",
                                             "status": expected,
                                             "reservation": row["reservation"],
                                             "local_payload": "present"}


def test_a_tls_failure_or_a_bypass_leaves_no_qualifying_capture_even_on_exit_zero(bench):
    """§5.5: an unproxied attempt reaches nothing and may leave no observation at all;
    whatever is on disk, that is not ``measured``."""
    bench.open_grant(planned="review,sealed", retries=0)
    bench.scenarios["review"] = Scenario(requests=[], exit=0)
    bench.scenarios["sealed"] = Scenario(requests=[("POST", gts.INFERENCE_HOST, INFERENCE_PATH,
                                                    "deny")], exit=0)
    code, report = bench.measure("review", "sealed")
    assert code == 0
    assert [row["status"] for row in report["routes"]] == ["egress_refused", "egress_refused"]
    assert all(result["tools"] is None for result in bench.results().values())
    assert bench.cli("--aggregate")[1]["published"] == []
    assert bench.host_record() is None


# ============================================================ the grant ledger (§5.3)

@pytest.mark.parametrize("case,scenario,charge,settled", [
    ("abrupt_exit_valid_zero_event_stream", Scenario(requests=[], orderly=False, proxy_returncode=-9), 1, False),
    ("truncated_mid_record", Scenario(truncated=True), 1, False),
    ("shutdown_timeout_kill_path", Scenario(killed=True), 1, False),
    ("clean_exit_lost_marker", Scenario(orderly=False), 1, False),
    ("orderly_zero_events", Scenario(requests=[], artifact=None), 0, True),
    ("orderly_one_request", Scenario(), 1, True),
])
def test_ba1_only_a_completion_proof_settles_below_the_full_budget(bench, case, scenario, charge,
                                                                   settled):
    """BA-1 (lane L2b): settlement below the full budget requires a clean exit, the
    end-of-stream marker, a matching count and no protocol error; otherwise the reservation
    stays charged in full, permanently."""
    bench.open_grant(planned="review")
    bench.default = scenario
    code, report = bench.measure("review")
    assert code == 0
    rid = report["routes"][0]["reservation"]
    settlement = bench.grant_dir() / "settlements" / (rid + ".json")
    assert settlement.exists() is settled
    assert bench.status()["charged"] == charge
    # Permanently: a restart reads the same charge.
    assert bench.status(output=bench.root / "state" / "elsewhere")["charged"] == charge


def test_an_orderly_context_refusal_after_reservation_settles_to_zero(bench, monkeypatch, tmp_path):
    _managed_config_appears(bench, monkeypatch, tmp_path)
    bench.open_grant(planned="review")
    assert _route_rows(bench.measure("review")[1])["review"]["status"] == "context_refused"
    assert bench.status()["charged"] == 0


def test_a_fresh_output_directory_resets_nothing(bench):
    bench.open_grant(planned="review", retries=1)
    bench.default = Scenario(exit=1)
    assert bench.measure("review")[0] == 0
    elsewhere = bench.root / "state" / "fresh-output"
    status = bench.status(output=elsewhere)
    assert status["charged"] == 1 and status["launches"] == 1
    # The grant's committed record decides; this directory merely lacks its copy.
    assert _route_rows(status)["review"] == {
        "route": "review", "state": "recorded", "status": "launch_failed",
        "reservation": status["reservations"][0]["id"], "local_payload": "missing"}
    assert bench.measure("review", output=elsewhere)[0] == 0  # the one retry
    code, report = bench.measure("review", output=bench.root / "state" / "third-output")
    assert code == 1 and report["routes"][0] == {"route": "review", "reserved": False,
                                                 "code": "grant_retries_exhausted"}
    assert bench.status()["launches"] == 2


def test_the_retry_allowance_is_per_launch_of_an_already_launched_route(bench):
    bench.open_grant(planned="review,sealed,staged", retries=2)
    bench.default = Scenario(exit=1)
    for _ in range(3):
        assert bench.measure("review")[0] == 0
    code, report = bench.measure("review")
    assert code == 1 and report["routes"][0]["code"] == "grant_retries_exhausted"
    assert bench.measure("sealed", "staged")[0] == 0  # planned launches are not retries
    status = bench.status()
    assert status["launches"] == 5 and status["retries_used"] == 2 and status["charged"] == 5


def test_the_launch_that_would_pass_the_cap_of_seven_never_reserves(bench):
    bench.open_grant(planned="review,sealed,staged", retries=7)
    bench.default = Scenario(killed=True)  # every launch charged in full
    for route in ("review", "sealed", "staged", "review", "sealed", "staged", "review"):
        assert bench.measure(route)[0] == 0
    assert bench.status()["charged"] == 7
    code, report = bench.measure("sealed")
    assert code == 1 and report["routes"][0] == {"route": "sealed", "reserved": False,
                                                 "code": "grant_cap_reached"}
    assert bench.status()["launches"] == 7


def test_a_route_outside_the_plan_never_reserves(bench):
    bench.open_grant(planned="review")
    code, report = bench.measure("sealed")
    assert code == 1 and report["routes"][0]["code"] == "route_not_planned"


def test_a_mismatched_binary_or_host_refuses_against_grant_json(bench, monkeypatch):
    bench.open_grant(planned="review")
    old = bench.digest
    code, report = bench.measure("review", expected="d" * 64)
    assert code == 1 and report["code"] == "binary_mismatch"
    bench.binary.write_bytes(bench.binary.read_bytes() + b"another build\n")
    code, report = bench.measure("review", expected=old)
    assert code == 1 and report["code"] == "binary_mismatch"
    code, report = bench.measure("review")  # the new digest, as expected, is not the grant's
    assert code == 1 and report["code"] == "grant_mismatch"
    assert bench.cli("--verify-probe", "initial")[1]["code"] == "grant_mismatch"
    bench.binary.write_bytes(bench.binary.read_bytes()[:-len(b"another build\n")])
    assert bench.digest == old
    monkeypatch.setattr(seat_window, "_host_digest", lambda: "e" * 64)
    code, report = bench.measure("review", expected=bench.digest)
    assert code == 1 and report["code"] == "grant_mismatch"


def test_a_grant_is_created_once(bench):
    bench.open_grant()
    code, report = bench.cli("--new-grant", "--planned", "review", "--retries", "0",
                             "--hosted-check", HOSTED_RUN)
    assert code == 1 and report["code"] == "grant_exists"
    grant = json.loads((bench.grant_dir() / "grant.json").read_text())
    assert grant["planned"] == list(SEAT) and grant["retries"] == 2 and grant["cap"] == 7
    assert grant["budget"] == 1 and grant["binary_sha256"] == bench.digest
    assert grant["hosted_check"] == HOSTED_RUN  # erratum 4: GROK_HOSTED_CHECK_RUN


@pytest.mark.parametrize("planned,retries,code", [
    ("", 2, "planned_routes_invalid"), ("review,execute", 2, "planned_routes_invalid"),
    ("review,review", 2, "planned_routes_invalid"), ("review", -1, "retries_invalid"),
    ("review", 8, "retries_invalid"),
])
def test_a_grant_refuses_an_invalid_plan(bench, planned, retries, code):
    result, report = bench.cli("--new-grant", "--planned", planned, "--retries", str(retries),
                               "--hosted-check", HOSTED_RUN)
    assert result == 1 and report["code"] == code


@pytest.mark.parametrize("hosted", [None, "", "has space", "x" * 300])
def test_a_grant_needs_the_hosted_check_run(bench, hosted):
    argv = ["--new-grant", "--planned", "review", "--retries", "0"]
    if hosted is not None:
        argv += ["--hosted-check", hosted]
    code, report = bench.cli(*argv)
    assert code == 1 and report["code"] == "hosted_check_required"
    assert not bench.grant_dir().exists()


def test_every_stage_needs_a_valid_grant_id(bench):
    code, report = bench.cli("--status", grant="../escape")
    assert code == 1 and report["code"] == "grant_id_invalid"


# ------------------------------------------------- interruptions and concurrency (§5.3)

DRIVER = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import pytest
import test_grok_tool_surface_measure as t
bench = t.Bench(Path(sys.argv[2]), pytest.MonkeyPatch())
for route, values in json.loads(sys.argv[3]).items():
    if route == "__rehearsal__":
        bench.rehearsal = t.Scenario(**values)
    else:
        bench.scenarios[route] = t.Scenario(**values)
bench.block_at = json.loads(sys.argv[5]) or None
code, report = bench.cli(*json.loads(sys.argv[4]))
print(json.dumps({"code": code, "report": report}))
"""


def _driver(bench, argv, *, scenarios=None, block_at=None):
    return subprocess.Popen(
        [sys.executable, "-c", DRIVER, str(TESTS), str(bench.root), json.dumps(scenarios or {}),
         json.dumps(argv), json.dumps(block_at)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)


def _wait_for(path: Path, process, timeout_s=120.0):
    deadline = time.monotonic() + timeout_s
    while not path.exists():
        if process.poll() is not None:
            pytest.fail("the driver exited early: " + process.stderr.read().decode()[-2000:])
        if time.monotonic() > deadline:
            process.kill()
            pytest.fail("the driver never reached its blocking point")
        time.sleep(0.05)


def _kill(process):
    os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)


def test_a_kill_after_reservation_and_before_settlement_stays_charged(bench):
    bench.open_grant(planned="review", retries=1)
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--route", "review"],
                      scenarios={"review": {"block": str(ready)}})
    _wait_for(ready, process)
    _kill(process)
    status = bench.status()
    assert status["charged"] == 1 and status["launches"] == 1
    assert _route_rows(status)["review"]["state"] == "interrupted"
    assert not list((bench.grant_dir() / "settlements").iterdir())
    # A restart with a fresh output directory resets nothing: the one retry, then nothing.
    fresh = bench.root / "state" / "after-restart"
    assert bench.measure("review", output=fresh)[0] == 0
    code, report = bench.measure("review", output=fresh)
    assert code == 1 and report["routes"][0]["code"] == "grant_retries_exhausted"
    assert bench.status()["charged"] == 2


def test_a_kill_between_the_two_routes_of_one_invocation(bench):
    bench.open_grant()
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--route", "sealed", "--route", "staged"],
                      block_at={"function": "_plan_reservation", "route": "staged",
                                "file": str(ready)})
    _wait_for(ready, process)
    _kill(process)
    status = bench.status()
    rows = _route_rows(status)
    assert rows["sealed"]["state"] == "recorded" and rows["sealed"]["status"] == "measured"
    assert rows["staged"]["state"] == "no_reservation"
    assert status["charged"] == 1 and status["launches"] == 1


def test_a_kill_during_the_second_route_leaves_it_charged_in_full(bench):
    bench.open_grant()
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--route", "sealed", "--route", "staged"],
                      scenarios={"staged": {"block": str(ready), "requests": []}})
    _wait_for(ready, process)
    _kill(process)
    rows = _route_rows(bench.status())
    assert rows["sealed"]["status"] == "measured" and rows["staged"]["state"] == "interrupted"
    status = bench.status()
    # sealed settled to 1; staged, with no observation at all, is charged its whole budget.
    assert status["charged"] == 2


def test_a_second_process_on_the_same_grant_refuses_at_once_whatever_its_output(bench):
    bench.open_grant()
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--route", "review"],
                      scenarios={"review": {"block": str(ready)}})
    try:
        _wait_for(ready, process)
        started = time.monotonic()
        code, report = bench.measure("sealed", output=bench.root / "state" / "other-output")
        assert code == 1 and report["code"] == "measurement_busy"
        assert time.monotonic() - started < 10
        code, report = bench.cli("--aggregate", output=bench.root / "state" / "third")
        assert code == 1 and report["code"] == "measurement_busy"
    finally:
        _kill(process)
    assert bench.status()["launches"] == 1  # the second never reserved


def test_the_publication_lock_is_shared_across_grants_and_directories(bench, monkeypatch):
    bench.open_grant(planned="review")
    monkeypatch.setattr(gts, "PUBLICATION_WAIT_S", 0.2)
    root = os.open(pa.private_record_root(), os.O_RDONLY | os.O_DIRECTORY)
    held = os.open(gts.publication_lock_name(bench.digest), os.O_RDWR | os.O_CREAT, 0o600,
                   dir_fd=root)
    import fcntl
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        code, report = bench.measure("review", output=bench.root / "state" / "elsewhere")
        assert code == 1 and report["routes"][0] == {"route": "review", "reserved": False,
                                                     "code": "publication_busy"}
    finally:
        os.close(held)
        os.close(root)
    assert bench.status()["launches"] == 0
    assert bench.measure("review")[0] == 0


def test_an_interruption_after_reservation_is_reported_apart_from_a_refusal(bench, monkeypatch):
    bench.open_grant(planned="review,sealed")
    monkeypatch.setattr(gts, "_write_result", lambda stage, result: (_ for _ in ()).throw(
        OSError("disk full")))
    code, report = bench.measure("review", "sealed")
    assert code == 1
    assert report["routes"][0]["reserved"] and report["routes"][0]["status"] == "interrupted"
    assert report["routes"][1] == {"route": "sealed", "reserved": False, "code": "not_attempted"}
    monkeypatch.undo()
    bench2 = Bench(bench.root, monkeypatch)
    status = bench2.status()
    rows = _route_rows(status)
    assert rows["review"]["state"] == "interrupted" and rows["sealed"]["state"] == "no_reservation"
    code, report = bench2.cli("--require-measured", "sealed")
    assert code == 1 and report["status"] == "no_reservation"
    code, report = bench2.cli("--require-measured", "review")
    assert code == 1 and report["status"] == "interrupted"


def test_require_measured_tells_no_reservation_from_not_measured(bench):
    bench.open_grant(planned="review,sealed")
    bench.default = Scenario(exit=1)
    bench.measure("review")
    code, report = bench.cli("--require-measured", "review")
    assert code == 1 and report["status"] == "not_measured" and report["result"] == "launch_failed"
    code, report = bench.cli("--require-measured", "sealed")
    assert code == 1 and report["status"] == "no_reservation" and report["result"] is None


# ================================================ records, withdrawal, latest (§5.7)

def test_result_records_are_immutable_and_name_their_grant_and_reservation(bench):
    bench.open_grant(planned="review")
    bench.measure("review")
    (name, result), = bench.results().items()
    rid = name[:-len(".json")]
    assert result["grant"] == GRANT and result["reservation"] == rid
    path = bench.output / "results" / name
    assert (path.stat().st_mode & 0o777) == 0o600
    results = os.open(bench.output / "results", os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            gts._write_new(results, name, {"rewritten": True})
    finally:
        os.close(results)
    assert json.loads(path.read_text()) == result


def test_the_latest_reservation_decides_a_route_within_a_grant(bench):
    bench.open_grant(planned="review", retries=1)
    bench.measure("review")
    bench.default = Scenario(exit=1)
    bench.measure("review")
    report = bench.cli("--aggregate")[1]
    assert report["published"] == []
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    assert [route["status"] for route in evidence["routes"]] == ["launch_failed"]
    assert bench.host_record() is None


def test_withdraw_before_launch_makes_a_prior_pass_unconsumable(bench):
    bench.open_grant(planned="review", retries=1)
    bench.measure("review")
    bench.cli("--aggregate")
    assert bench.probe("review")["passed"] and bench.gate("review")
    bench.measure("review")  # a retry: the record is withdrawn before its proxy starts
    retry = bench.launches[-1]
    assert retry.record is None and retry.gate is False
    register = json.loads((pa.private_record_root()
                           / gts.attempts_name(bench.digest)).read_text())
    entry = register["attempts"][pi._grok_argv_digest(_form("review"))]
    assert pi._grok_argv_digest(_form("review")) not in register["published"]
    latest = bench.status()["reservations"][-1]
    assert entry == {"route": "review", "grant": GRANT, "reservation": latest["id"],
                     "at": latest["at"]}


def test_ba2_an_older_grant_cannot_republish_a_route_a_newer_grant_withdrew(bench, monkeypatch):
    """BA-2: grant A measures and publishes R; grant B reserves R, which withdraws it, and
    fails; ``--aggregate`` for grant A leaves R out and reports it ``superseded``; the gate
    refuses a cached receipt for R."""
    out_a = bench.root / "state" / "out-a"
    out_b = bench.root / "state" / "out-b"
    bench.open_grant(planned="review,sealed", output=out_a, grant="grant-A")
    assert bench.measure("review", "sealed", output=out_a, grant="grant-A")[0] == 0
    assert bench.cli("--aggregate", output=out_a, grant="grant-A")[1]["published"] == ["review", "sealed"]
    assert bench.probe("review")["passed"] and bench.gate("review")  # the cached receipt
    bench.open_grant(planned="review", output=out_b, grant="grant-B")
    bench.default = Scenario(exit=1)
    assert _route_rows(bench.measure("review", output=out_b, grant="grant-B")[1])["review"][
        "status"] == "launch_failed"
    assert bench.gate("review") is False
    code, report = bench.cli("--aggregate", output=out_a, grant="grant-A")
    assert code == 0 and report["published"] == ["sealed"] and report["superseded"] == ["review"]
    evidence = json.loads((out_a / "tool-surface.json").read_text())
    assert {route["route"]: route["superseded"] for route in evidence["routes"]} == {
        "review": True, "sealed": False}
    assert evidence["grant"]["other_grants_for_binary"] == 1
    record = bench.host_record()
    assert [route["route"] for route in record["surface"]["routes"]] == ["sealed"]
    assert bench.probe("sealed")["passed"]
    assert bench.gate("review") is False and bench.gate("sealed") is True
    assert not bench.probe("review")["passed"]
    # Grant B's own aggregate publishes nothing for R and removes any record.
    assert bench.cli("--aggregate", output=out_b, grant="grant-B")[1]["published"] == []
    assert bench.host_record() is None


def test_ba2_a_catalog_route_keeps_its_precedence_whatever_the_register_says(bench, monkeypatch):
    out_a = bench.root / "state" / "out-a"
    bench.open_grant(planned="review", output=out_a, grant="grant-A")
    bench.measure("review", output=out_a, grant="grant-A")
    bench.cli("--aggregate", output=out_a, grant="grant-A")
    shipped = bench.host_record()["surface"]
    catalog = {"schema": gts.CATALOG_SCHEMA, "revoked": [], "surfaces": [shipped]}
    monkeypatch.setattr(gts, "_catalog_bytes", lambda: json.dumps(catalog).encode())
    bench.open_grant(planned="review", output=bench.root / "state" / "out-b", grant="grant-B")
    bench.default = Scenario(exit=1)
    bench.measure("review", output=bench.root / "state" / "out-b", grant="grant-B")
    assert bench.host_record() is None  # the host-local route was withdrawn
    receipt = bench.probe("review")
    assert receipt["passed"] and receipt["surface_source"] == "catalog"
    assert bench.gate("review") is True
    report = bench.cli("--aggregate", output=out_a, grant="grant-A")[1]
    assert report["superseded"] == ["review"] and bench.gate("review") is True


def test_a_missing_or_unreadable_register_publishes_nothing(bench):
    bench.open_grant(planned="review")
    bench.measure("review")
    register = pa.private_record_root() / gts.attempts_name(bench.digest)
    register.write_text("{not json")
    report = bench.cli("--aggregate")[1]
    assert report["published"] == [] and report["superseded"] == ["review"]
    register.unlink()
    assert bench.cli("--aggregate")[1]["published"] == []
    assert bench.host_record() is None


def test_aggregation_refuses_a_foreign_or_altered_result_and_removes_the_record(bench):
    bench.open_grant(planned="review,sealed")
    bench.measure("review", "sealed")
    assert bench.cli("--aggregate")[1]["published"] == ["review", "sealed"]
    name = sorted(bench.results())[0]
    path = bench.output / "results" / name
    altered = json.loads(path.read_text())
    altered["tools"] = ["read_file"]
    path.unlink()
    path.write_text(json.dumps(altered))
    path.chmod(0o600)
    code, report = bench.cli("--aggregate")
    assert code == 1 and report["code"] == "result_foreign"
    assert bench.host_record() is None


def test_aggregation_refuses_results_that_do_not_share_one_context(bench, monkeypatch):
    bench.open_grant(planned="review,sealed")
    bench.measure("review")
    # The code moved between the two launches: the results no longer share one runtime.
    monkeypatch.setattr(seat_window, "runtime_digest", lambda: "c" * 64)
    bench.measure("sealed")
    code, report = bench.cli("--aggregate")
    assert code == 1 and report["code"] == "context_mismatch"
    assert bench.host_record() is None


def test_a_launch_never_publishes(bench):
    bench.open_grant(planned="review")
    bench.measure("review")
    assert bench.host_record() is None
    assert not bench.probe("review")["passed"]


# ============================================== fix round 1: crash-consistent BA-2

def _published_by_a(bench):
    out_a = bench.root / "state" / "out-a"
    bench.open_grant(planned="review", output=out_a, grant="grant-A")
    assert bench.measure("review", output=out_a, grant="grant-A")[0] == 0
    assert bench.cli("--aggregate", output=out_a, grant="grant-A")[1]["published"] == ["review"]
    assert bench.probe("review")["passed"] and bench.gate("review")  # A's cached receipt
    bench.open_grant(planned="review", output=bench.root / "state" / "out-b", grant="grant-B")
    return out_a


@pytest.mark.parametrize("step,record_kept", [
    ("_withdraw", True),             # killed after the register, before the withdrawal
    ("_write_reservation", False),   # killed after the withdrawal, before the reservation
])
def test_ba2_a_kill_at_either_step_before_the_reservation_leaves_the_prior_pass_unconsumable(
        bench, step, record_kept):
    """Fix round 1, finding 1: each step is durable before the next, and the register is
    written first, so from the moment a newer attempt can exist A's pass stops admitting,
    whichever step a SIGKILL interrupts; A cannot republish it either."""
    out_a = _published_by_a(bench)
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--route", "review", "--output",
                              str(bench.root / "state" / "out-b"), "--grant", "grant-B"],
                      block_at={"function": step, "route": "review", "file": str(ready)})
    _wait_for(ready, process)
    _kill(process)
    record = bench.host_record()
    assert (record is not None and [r["route"] for r in record["surface"]["routes"]] == ["review"]) \
        is record_kept
    # Nothing was reserved, and the prior pass no longer admits.
    assert bench.status(grant="grant-B", output=bench.root / "state" / "out-b")["launches"] == 0
    assert bench.gate("review") is False and not bench.probe("review")["passed"]
    report = bench.cli("--aggregate", output=out_a, grant="grant-A")[1]
    assert report["published"] == [] and report["superseded"] == ["review"]
    assert bench.gate("review") is False


def test_a_host_local_route_admits_only_while_the_register_names_its_publication(bench):
    _published_by_a(bench)
    argv = pi._grok_argv_digest(_form("review"))
    path = pa.private_record_root() / gts.attempts_name(bench.digest)
    original = json.loads(path.read_text())

    def rewrite(change):
        document = json.loads(json.dumps(original))
        change(document)
        path.unlink()
        pa.write_private_record(path.name, document)
    for change in (lambda d: d["published"].pop(argv),
                   lambda d: d["published"][argv].update(surface_digest="0" * 64),
                   lambda d: d["attempts"][argv].update(reservation="0099-" + "f" * 16),
                   lambda d: d["attempts"][argv].update(grant="grant-C")):
        rewrite(change)
        assert gts.frozen_surface(bench.digest, argv) is None and bench.gate("review") is False
    path.unlink()
    assert gts.frozen_surface(bench.digest, argv) is None  # a missing register admits nothing
    path.write_text("{not json")
    path.chmod(0o600)
    assert gts.frozen_surface(bench.digest, argv) is None
    path.unlink()
    pa.write_private_record(path.name, original)
    assert gts.frozen_surface(bench.digest, argv) is not None and bench.gate("review")


# ============================================ fix round 1: holder-to-proxy (BA-3)

def test_ba3_a_holder_that_does_not_bridge_to_its_proxy_launches_nothing(bench):
    bench.open_grant(planned="review")
    bench.default = Scenario(crossed=True)
    code, report = bench.measure("review")
    assert code == 0 and report["routes"][0]["status"] == "context_refused"
    assert bench.launches == []


class _FakeBridge:
    """A real process registered as a holder's bridge, carrying the bridge's argv shape."""

    def __init__(self, holder: int, socket_path: str):
        self.process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)", "--net", "-t", str(holder),
             "socat", "TCP4-LISTEN:3128", f"UNIX-CONNECT:{socket_path}"])
        self.args, self.pid = self.process.args, self.process.pid

    def poll(self):
        return self.process.poll()


_LISTENER = ("import socket, sys, time\n"
             "s = socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen()\n"
             "print('ready', flush=True); time.sleep(120)\n")


def _listener(path: Path):
    process = subprocess.Popen([sys.executable, "-c", _LISTENER, str(path)],
                               stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "ready"
    return process


def test_bridged_to_binds_the_exact_live_holder_to_this_proxys_socket(bench, monkeypatch):
    """Offline, with real processes: the bridge registered for the holder must still run in
    the holder's network namespace and dial the socket this proxy's own process listens on."""
    import tempfile
    bridged_to = REAL_BRIDGED_TO
    sockets = Path(tempfile.mkdtemp(prefix="pl-bridge-"))  # short: an AF_UNIX path is bounded
    proxies, holders, bridges = [], [], []
    try:
        for name in ("a", "b"):
            listener = _listener(sockets / name)
            proxies.append(bench.proxy_object(socket=str(sockets / name), process=listener))
            holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            holders.append(holder)
            bridges.append(_FakeBridge(holder.pid, str(sockets / name)))
        registry = {str(holder.pid): bridge for holder, bridge in zip(holders, bridges)}
        monkeypatch.setattr(sandbox_egress, "_BRIDGES", registry)
        prefix_a, prefix_b = (("nsenter", "-t", str(h.pid), "--net", "--") for h in holders)
        assert bridged_to(prefix_a, proxies[0]) and bridged_to(prefix_b, proxies[1])
        # A different live proxy with the same policy and budget.
        assert not bridged_to(prefix_a, proxies[1])
        # A mismatched live holder.
        assert not bridged_to(prefix_b, proxies[0])
        # A holder with no bridge of ours, and a socket held by another process.
        assert not bridged_to(("nsenter", "-t", str(os.getpid()), "--net", "--"), proxies[0])
        stranger = bench.proxy_object(socket=str(sockets / "a"), process=proxies[1].process)
        assert not bridged_to(prefix_a, stranger)
        bridges[0].process.kill()
        bridges[0].process.wait()
        assert not bridged_to(prefix_a, proxies[0])  # the bridge died
    finally:
        for process in [*holders, *(b.process for b in bridges), *(p.process for p in proxies)]:
            process.kill()
            process.wait()
        shutil.rmtree(sockets, ignore_errors=True)


# ==================================== fix round 1: recoverable commits, one status

def test_a_reprocess_interrupted_before_its_commit_keeps_the_stop_and_retries_cleanly(
        bench, monkeypatch):
    """Fix round 1, finding 4: killed after the revised record's bytes are written and
    before they commit, the grant-wide stop holds, and the retry commits the same revision
    with no exclusive-file collision."""
    bench.open_grant(planned="review,sealed")
    observed = json.dumps({"declarations": [{"tool_name": n} for n in _tools("review")]}).encode()
    bench.default = Scenario(artifact=observed)
    rid = bench.measure("review")[1]["routes"][0]["reservation"]
    real_extract = gts.extract_tool_names
    monkeypatch.setattr(gts, "extract_tool_names", lambda raw: (
        "S4", sorted(item["tool_name"] for item in json.loads(raw)["declarations"]))
        if b"declarations" in raw else real_extract(raw))
    real_link = os.link

    def crash(*args, **kwargs):
        raise KeyboardInterrupt("killed before the commit")
    monkeypatch.setattr(os, "link", crash)
    with pytest.raises(KeyboardInterrupt):
        bench.cli("--reprocess", rid)
    monkeypatch.setattr(os, "link", real_link)
    status = bench.status()
    assert status["format_stop"] is True
    assert _route_rows(status)["review"]["status"] == "format_unrecognised"
    code, report = bench.measure("sealed")
    assert code == 1 and report["routes"][0]["code"] == "format_unrecognised_unresolved"
    # What a SIGKILL inside the commit leaves: the revision's temp file, never its name.
    stray = bench.grant_dir() / "results" / f".tmp-{rid}.1.json.0123456789abcdef"
    stray.write_bytes(b'{"partial":')
    stray.chmod(0o600)
    code, report = bench.cli("--reprocess", rid)
    assert code == 0 and report["result"] == "measured"
    committed = sorted(path.name for path in (bench.grant_dir() / "results").iterdir())
    assert committed == [rid + ".0.json", rid + ".1.json"]  # no temp left, no collision
    assert bench.status()["format_stop"] is False


def test_a_commit_interrupted_before_the_local_copy_is_recorded_and_recoverable(bench,
                                                                               monkeypatch):
    bench.open_grant(planned="review")
    real_commit = gts._commit_new
    calls = []

    def commit(directory, name, payload):
        calls.append(name)
        if len(calls) == 2:
            raise KeyboardInterrupt("killed between the grant's commit and the local copy")
        return real_commit(directory, name, payload)
    monkeypatch.setattr(gts, "_commit_new", commit)
    with pytest.raises(KeyboardInterrupt):
        bench.measure("review")
    monkeypatch.setattr(gts, "_commit_new", real_commit)
    rows = _route_rows(bench.status())
    assert rows["review"]["state"] == "recorded" and rows["review"]["status"] == "measured"
    assert rows["review"]["local_payload"] == "missing"
    assert bench.cli("--require-measured", "review")[0] == 0
    assert bench.cli("--aggregate")[1]["published"] == ["review"]
    assert _route_rows(bench.status())["review"]["local_payload"] == "present"


def test_one_authoritative_status_whatever_the_output_directory(bench):
    """Fix round 1, finding 5: a failed pilot reads as recorded and failed from any output
    directory, an interrupted attempt as interrupted, an unreserved route as no_reservation;
    the pilot gate exits non-zero for all three."""
    bench.open_grant(planned="review,sealed,staged")
    bench.default = Scenario(exit=1)
    bench.measure("review")
    fresh = bench.root / "state" / "elsewhere"
    status = bench.status(output=fresh)
    rows = _route_rows(status)
    assert rows["review"]["state"] == "recorded" and rows["review"]["status"] == "launch_failed"
    assert rows["review"]["local_payload"] == "missing"
    assert [item["status"] for item in status["reservations"]] == ["launch_failed"]
    assert rows["sealed"] == {"route": "sealed", "state": "no_reservation"}
    code, report = bench.cli("--require-measured", "review", output=fresh)
    assert (code, report["status"], report["result"]) == (1, "not_measured", "launch_failed")
    code, report = bench.cli("--require-measured", "sealed", output=fresh)
    assert (code, report["status"]) == (1, "no_reservation")
    copy = next((bench.output / "results").glob("*.json"))
    copy.write_text(copy.read_text().replace("launch_failed", "measured"))
    assert _route_rows(bench.status())["review"]["local_payload"] == "mismatch"


# ================================== fix round 1: final verification bound to the grant

def test_verify_probe_final_is_bound_to_this_grant(bench):
    out_a = bench.root / "state" / "out-a"
    bench.open_grant(planned="review", output=out_a, grant="grant-A")
    bench.measure("review", output=out_a, grant="grant-A")
    bench.cli("--aggregate", output=out_a, grant="grant-A")
    assert bench.cli("--verify-probe", "final", output=out_a, grant="grant-A")[0] == 0
    code, report = bench.cli("--verify-probe", "final", output=out_a, grant="grant-B")
    assert code == 1 and report["code"] == "grant_unavailable"
    bench.open_grant(planned="review", output=bench.root / "state" / "out-b", grant="grant-B")
    code, report = bench.cli("--verify-probe", "final", output=out_a, grant="grant-B")
    assert code == 1 and report["code"] == "aggregate_of_another_grant"
    # The initial stage still runs before any grant exists.
    assert bench.cli("--verify-probe", "initial", grant="grant-C")[1]["code"] == "probe_mismatch"


# ===================================================== format_unrecognised (§5.6)

def test_format_unrecognised_blocks_the_grant_until_reprocessed_with_no_second_charge(bench,
                                                                                    monkeypatch):
    bench.open_grant(planned="review,sealed", retries=1)
    observed = json.dumps({"declarations": [{"tool_name": name} for name in _tools("review")]})
    bench.default = Scenario(artifact=observed.encode())
    code, report = bench.measure("review")
    rid = report["routes"][0]["reservation"]
    assert code == 0 and report["routes"][0]["status"] == "format_unrecognised"
    (result,) = bench.results().values()
    assert result["structure"]["type"] == "object"
    assert result["structure"]["keys"][0][0] == "declarations"
    bench.default = Scenario()
    for argv in (("sealed",), ("review",)):
        code, report = bench.measure(*argv)
        assert code == 1 and report["routes"][0]["code"] == "format_unrecognised_unresolved"
    assert bench.status()["format_stop"] is True and bench.status()["launches"] == 1
    # The same extractor reprocesses to the same answer, charging nothing.
    assert bench.cli("--reprocess", rid)[1]["result"] == "format_unrecognised"
    # A narrow extractor for the observed shape, built offline, then reprocess.
    real = gts.extract_tool_names

    def extractor(raw):
        document = json.loads(raw)
        if isinstance(document, dict) and set(document) == {"declarations"}:
            return "S4", sorted(item["tool_name"] for item in document["declarations"])
        return real(raw)
    monkeypatch.setattr(gts, "extract_tool_names", extractor)
    code, report = bench.cli("--reprocess", rid)
    assert code == 0 and report["result"] == "measured"
    results = bench.results()
    assert sorted(results) == [rid + ".json", rid + ".r1.json", rid + ".r2.json"]
    assert results[rid + ".json"] == result  # the original stays as it was
    latest = results[rid + ".r2.json"]
    assert latest["reprocessed_from"] == rid and latest["revision"] == 2
    assert latest["tools"] == _tools("review") and latest["shape"] == "S4"
    status = bench.status()
    assert status["format_stop"] is False and status["charged"] == 1 and status["launches"] == 1
    assert bench.measure("sealed")[0] == 0
    report = bench.cli("--aggregate")[1]
    assert report["published"] == ["review", "sealed"]
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    assert [item["reprocessed"] for item in evidence["reservations"]] == [True, False]


def test_reprocess_needs_a_retained_capture(bench):
    bench.open_grant(planned="review")
    bench.default = Scenario(artifact=b'{"weird": true}')
    rid = bench.measure("review")[1]["routes"][0]["reservation"]
    assert bench.cli("--purge")[0] == 0
    code, report = bench.cli("--reprocess", rid)
    assert code == 1 and report["code"] == "capture_unavailable"
    code, report = bench.cli("--reprocess", "0099-0000000000000000")
    assert code == 1 and report["code"] == "reservation_unavailable"


@pytest.mark.parametrize("raw,shape,tools", [
    (b'[{"name": "grep"}, {"name": "list_dir"}, {"name": "grep"}]', "S1", ["grep", "list_dir"]),
    (_s2(["read_file", "grep"]), "S2", ["grep", "read_file"]),
    (b'{"tools": [{"name": "grep"}], "version": 3}', "S3", ["grep"]),
    (b'{"tools": ' + _s2(["grep"]) + b'}', "S3", ["grep"]),
    (b'[]', "empty", []),
    (b'{"tools": []}', "S3", []),
])
def test_the_extractor_reads_the_three_shapes(raw, shape, tools):
    assert gts.extract_tool_names(raw) == (shape, tools)


@pytest.mark.parametrize("raw", [
    b'[{"name": "grep"}, {"function": {"name": "list_dir"}}]',          # mixed
    b'[{"name": "grep", "function": {"name": "grep"}}]',               # two readings
    b'[{"description": "no name"}]',                                   # missing name
    b'[{"name": 3}]', b'{"functions": []}', b'"grep"', b'not json',
    b'[{"name": "grep"}, {"name": "grep"}, "x"]',
    b'[{"name": "../../etc/passwd"}]', b'[{"name": "' + b"a" * 97 + b'"}]',  # untrusted names
    b'[{"name": "grep", "name": "x"}]',                                # duplicate key
])
def test_the_extractor_never_guesses(raw):
    with pytest.raises(gts.FormatUnrecognised) as refusal:
        gts.extract_tool_names(raw)
    assert "grep" not in json.dumps(refusal.value.structure)  # no string values


def test_the_sanitized_structure_filters_key_names_and_drops_values():
    document = {"tools": [{"na me": "secret value", "ok_key": {"deep": {"deeper": 1}}}],
                **{f"k{index}": index for index in range(80)}}
    structure = gts.sanitized_structure(document)
    text = json.dumps(structure)
    assert "secret value" not in text and "na me" not in text
    keys = structure["keys"]
    assert len(keys) == 64 and keys[0][0] == "tools"
    item = keys[0][1]["items"][0]
    assert [pair[0] for pair in item["keys"]] == ["#5", "ok_key"]
    assert item["keys"][1][1] == {"type": "object", "size": 1}  # depth 3: no keys below
    gts._check_structure(structure)


# ========================================= redaction, the sentinel, retention (§5.9)

def _files(root: Path):
    return [path for path in root.rglob("*") if path.is_file()]


def test_the_planted_sentinel_reaches_no_record(bench):
    bench.open_grant()
    bench.measure(*SEAT)
    bench.cli("--aggregate")
    bench.probe("review")
    records = [*_files(bench.output / "results"), bench.output / "tool-surface.json",
               *_files(bench.grant_dir()), *_files(pa.private_record_root())]
    assert records
    for path in records:
        assert SENTINEL.encode() not in path.read_bytes(), path
    # The provider's output is secret-bearing: deleted at once on a measured route.
    assert not list((bench.output / "raw").rglob("provider.log"))


def test_records_hold_only_allow_listed_keys(bench):
    bench.open_grant(planned="review,sealed")
    bench.scenarios["sealed"] = Scenario(artifact=b'{"x": [1, {"y": "z"}]}')
    bench.measure("review", "sealed")
    for result in bench.results().values():
        gts.check_result_keys(result)
        assert set(result) == gts.RESULT_KEYS
        for value in json.dumps(result).split('"'):
            assert not value.startswith(("/home", str(bench.root))), value
    bench.cli("--aggregate")
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    gts.check_evidence_keys(evidence)
    assert str(bench.root) not in json.dumps(evidence)
    with pytest.raises(gts._Refused):
        gts.check_result_keys({**result, "stdout": "anything"})
    with pytest.raises(gts._Refused):
        gts.check_evidence_keys({**evidence, "prompt": gts.MEASUREMENT_PROMPT})


def test_retained_files_carry_operative_deadlines(bench):
    bench.open_grant(planned="review,sealed")
    bench.scenarios["sealed"] = Scenario(exit=1)
    report = bench.measure("review", "sealed")[1]
    review, sealed = (row["reservation"] for row in report["routes"])
    raw = bench.output / "raw"
    now = time.time()
    deadline = int((raw / review / "tool_definitions.json.expires_at").read_text())
    assert abs(deadline - (now + gts.RAW_RETENTION_S)) < 120
    assert not (raw / review / "provider.log").exists()  # measured: deleted at once
    log = raw / sealed / "provider.log"
    assert (log.stat().st_mode & 0o777) == 0o600
    assert abs(int((raw / sealed / "provider.log.expires_at").read_text())
               - (now + gts.LOG_RETENTION_S)) < 120
    out = os.open(bench.output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert gts.sweep_expired(out, now=now + gts.LOG_RETENTION_S + 1) == 1
        assert not log.exists() and (raw / review / "tool_definitions.json").exists()
        assert gts.sweep_expired(out, now=now + gts.RAW_RETENTION_S + 1) == 1
    finally:
        os.close(out)
    assert not list(raw.iterdir())


def test_every_stage_sweeps_expired_files_first_and_a_launch_refuses_if_it_cannot(bench):
    bench.open_grant(planned="review,sealed")
    bench.scenarios["review"] = Scenario(exit=1)
    rid = bench.measure("review")[1]["routes"][0]["reservation"]
    marker = bench.output / "raw" / rid / "provider.log.expires_at"
    marker.unlink()
    marker.write_text("0\n")
    marker.chmod(0o600)
    assert bench.status()["expired_removed"] == 1
    folder = bench.output / "raw" / "0099-0000000000000000"
    folder.mkdir(mode=0o700)
    (folder / "stray").write_text("x")
    folder.chmod(0o500)
    try:
        code, report = bench.measure("sealed")
        assert code == 1 and report["code"] == "expiry_sweep_failed"
        assert bench.status()["expired_removed"] is None and bench.status()["launches"] == 1
    finally:
        folder.chmod(0o700)


def test_purge_deletes_everything_retained_at_once(bench):
    bench.open_grant(planned="review,sealed")
    bench.scenarios["sealed"] = Scenario(exit=1)
    bench.measure("review", "sealed")
    code, report = bench.cli("--purge")
    assert code == 0 and report["removed"] == 2
    assert not list((bench.output / "raw").iterdir())
    assert bench.results() and (bench.grant_dir() / "grant.json").exists()


def test_purge_removes_a_killed_launchs_scratch_at_once_and_never_a_live_one(bench):
    """§5.9: a launch's scratch directory may hold its session transcript and prompt. While a
    real measurement process is inside its launch, ``--purge`` leaves that scratch alone and
    says so (``purge_incomplete``, exit 1). Once the process is killed before its own
    cleanup, an immediate ``--purge`` removes it, without waiting for the stale-scratch
    sweep."""
    bench.open_grant(planned="review", retries=1)
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--route", "review"],
                      scenarios={"review": {"block": str(ready)}})
    try:
        _wait_for(ready, process)
        (scratch,) = bench.output.glob("scratch-*")
        transcript = scratch / "sessions" / "transcript.jsonl"
        transcript.write_text("secret-bearing session transcript")
        code, report = bench.cli("--purge")
        assert code == 1 and report["status"] == "purge_incomplete", report
        assert report["scratch_active"] == [scratch.name] and report["scratch_unknown"] == []
        assert report["scratch_removed"] == 0 and transcript.exists()
    finally:
        _kill(process)
    code, report = bench.cli("--purge")
    assert code == 0 and report["status"] == "purged", report
    assert report["scratch_removed"] == 1 and report["scratch_active"] == []
    assert not scratch.exists() and not list(bench.output.glob("scratch-*"))


def test_purge_fails_closed_on_a_scratch_directory_it_cannot_judge(bench):
    """A scratch directory with no lock was not made by a launch of this tool, or lost its
    lock file: purge cannot tell whether it is in use, so it leaves it and fails closed."""
    bench.open_grant(planned="review")
    bench.status()
    unknown = bench.output / "scratch-unjudged"
    unknown.mkdir(mode=0o700)
    (unknown / "prompt.txt").write_text("secret-bearing prompt")
    code, report = bench.cli("--purge")
    assert code == 1 and report["status"] == "purge_incomplete", report
    assert report["scratch_unknown"] == ["scratch-unjudged"] and unknown.exists()


def test_without_posix_flags_or_locks_every_use_refuses(bench, monkeypatch):
    """CI fixes 2: ``panel_invoker`` imports this module on every platform, so it takes
    ``O_DIRECTORY`` and ``fcntl`` at use, not import. Where either is missing every use
    refuses: no directory opens without its no-follow flags, nothing proceeds unlocked, and
    ``--purge`` reports scratch it cannot lock as unjudged."""
    import builtins

    bench.open_grant(planned="review")
    bench.status()
    scratch, lock = gts._new_scratch(bench.output)
    os.close(lock)  # an abandoned launch: its lock released
    with monkeypatch.context() as patch:
        patch.delattr(os, "O_DIRECTORY")
        with pytest.raises(OSError):
            gts._dir_flags()
        with pytest.raises(gts.MeasurementRefused) as refused:
            gts._open_tree(bench.output, create=False)
        assert refused.value.code == "private_storage_unavailable"
    real_import = builtins.__import__

    def without_fcntl(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("blocked fcntl")
        return real_import(name, *args, **kwargs)
    output = os.open(bench.output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(builtins, "__import__", without_fcntl)
            with pytest.raises(OSError):
                gts._lock_now(output)
            with pytest.raises(gts.MeasurementRefused) as refused:
                with gts._flock(output, ".fixture-lock", busy="fixture_busy"):
                    pytest.fail("proceeded without its lock")
            assert refused.value.code == "private_storage_unavailable"
            result = gts.purge_scratch(output)
        assert result["scratch_unknown"] == [scratch.name] and result["scratch_removed"] == 0
        assert scratch.exists()
        assert gts.purge_scratch(output)["scratch_removed"] == 1 and not scratch.exists()
    finally:
        os.close(output)


@pytest.mark.parametrize("where,code", [("outside", "output_outside_private_state"),
                                        ("work_tree", "output_inside_work_tree")])
def test_the_output_must_be_private_state_outside_a_work_tree(bench, where, code):
    if where == "outside":
        output = bench.root / "elsewhere"
    else:
        (bench.state / "repo" / ".git").mkdir(parents=True)
        output = bench.state / "repo" / "out"
    result, report = bench.cli("--status", output=output)
    assert result == 1 and report["code"] == code


def test_the_scratch_directory_is_removed_and_a_stale_one_swept(bench):
    bench.open_grant(planned="review")
    bench.measure("review")
    assert not list(bench.output.glob("scratch-*"))
    stale = bench.output / "scratch-stale"
    (stale / "sessions" / "g" / "s").mkdir(parents=True)
    (stale / "sessions" / "g" / "s" / "transcript.jsonl").write_text("secret-bearing")
    old = time.time() - 2 * 3600 - gts.LAUNCH_TIMEOUT_S
    os.utime(stale, (old, old))
    bench.status()
    assert not stale.exists()


# ================================================================== verify-probe

def test_verify_probe_initial_needs_the_probe_binary_and_the_isolation_check(bench, monkeypatch):
    code, report = bench.cli("--verify-probe", "initial", expected="f" * 64)
    assert code == 1 and report["code"] == "binary_mismatch"
    monkeypatch.setattr(gts, "isolation_check",
                        lambda **kwargs: {"passed": False, "code": "isolation_unproven"})
    code, report = bench.cli("--verify-probe", "initial")
    assert code == 1 and report["code"] == "isolation_unproven"
    other = bench.root / "other-bin" / "grok"
    other.parent.mkdir()
    other.write_bytes(b"\x7fELF another grok, never executed\n")
    other.chmod(0o755)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(other.parent))
    code, report = bench.cli("--verify-probe", "initial")
    assert code == 1 and report["code"] == "probe_binary_mismatch"


def test_verify_probe_initial_fails_once_any_route_passes(bench):
    bench.open_grant(planned="review")
    bench.measure("review")
    bench.cli("--aggregate")
    code, report = bench.cli("--verify-probe", "initial")
    assert code == 1 and report["mismatches"] == ["review"]


def test_verify_probe_final_expects_a_measured_but_unadmitted_route_to_stay_refused(bench):
    bench.open_grant()
    bench.scenarios["sealed"] = Scenario(artifact=_s2(["run_terminal_cmd"]))
    bench.measure(*SEAT)
    report = bench.cli("--aggregate")[1]
    assert report["published"] == list(SEAT)
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    assert {route["route"]: route["admitted"] for route in evidence["routes"]} == {
        "review": True, "sealed": False, "staged": True}
    code, report = bench.cli("--verify-probe", "final")
    assert code == 0 and report["passed"], report
    rows = {row["route"]: row for row in report["routes"]}
    assert rows["sealed"]["passed"] is False and rows["review"]["passed"] is True


def test_verify_probe_final_fails_when_the_probe_disagrees_with_the_aggregate(bench):
    bench.open_grant(planned="review")
    bench.measure("review")
    bench.cli("--aggregate")
    (pa.private_record_root() / gts.host_record_name(bench.digest)).unlink()
    code, report = bench.cli("--verify-probe", "final")
    assert code == 1 and report["mismatches"] == ["review"]
    (bench.output / "tool-surface.json").unlink()
    code, report = bench.cli("--verify-probe", "final")
    assert code == 1 and report["code"] == "aggregate_unavailable"


# ====================================================== BA-3, the measurement path

from test_grok_measure_egress import (  # noqa: E402 - lane L2a's fixtures, reused as they are
    _host_reachable_listener, _layer_or_skip, _namespace_or_skip, fake_srt, real_proxy_upstream,
)

assert real_proxy_upstream and fake_srt  # fixtures, used by name below

_STAND_IN = r'''#!/usr/bin/python3 -I
import base64, json, os, socket, ssl, sys, urllib.parse
argv = sys.argv[1:]
if argv[-1:] == ["--help"]:
    sys.stdout.write(__HELP__)
    sys.exit(0)
if argv[-1:] == ["--version"]:
    sys.stdout.write(__VERSION__)
    sys.exit(0)
if "--prompt-file" in argv:
    sys.stdin.read()
proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
host, path = "cli-chat-proxy.grok.com", "/v1/chat/completions"
try:
    raw = socket.create_connection((proxy.hostname, proxy.port), 10)
    auth = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = raw.recv(4096)
        if not chunk:
            break
        head += chunk
    context = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: 2\r\n"
                    "Connection: close\r\n\r\n{}".encode())
        reply = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            reply += chunk
    proxied = reply.split(b"\r\n", 1)[0].decode("latin-1")
except OSError as exc:
    proxied = "error:" + type(exc).__name__
try:
    socket.create_connection(__DIRECT__, 3).close()
    direct = "connected"
except OSError:
    direct = "refused"
session = os.path.join(os.environ["HOME"], ".grok", "sessions", "-encoded-cwd", "session-0001")
os.makedirs(session)
with open(os.path.join(session, "tool_definitions.json"), "w") as handle:
    json.dump([{"type": "function", "function": {"name": name, "parameters": {}}}
               for name in __TOOLS__], handle)
print(proxied, direct)
sys.exit(0 if proxied.startswith("HTTP/1.1 200") and direct == "refused" else 3)
'''


REQUIRE_NS = "PHASE_LOOP_REQUIRE_GROK_EGRESS_NS"


def _require_bwrap():
    if shutil.which("bwrap", path="/usr/bin:/bin") is None:
        if os.environ.get(REQUIRE_NS) == "1":
            pytest.fail("bwrap is unavailable on a host that requires it")
        pytest.skip("bwrap is unavailable")


def _require_layer_or_skip():
    """Lane L2a's ``_layer_or_skip``, except that the hosted BA-3 job (``REQUIRE_NS=1``)
    fails on a missing prerequisite instead of skipping green (fix round 1, finding 3)."""
    if os.environ.get(REQUIRE_NS) == "1":
        reason = seat_egress_proxy.unavailable_reason()
        if reason is not None:
            pytest.fail(f"the seat egress layer is required here ({reason})")
        for name in ("socat", "openssl"):
            if shutil.which(name, path="/usr/bin:/bin") is None:
                pytest.fail(f"{name} is required here")
    _layer_or_skip()


@pytest.fixture
def required_upstream(request):
    """Lane L2a's ``real_proxy_upstream``, behind :func:`_require_layer_or_skip`."""
    _require_layer_or_skip()
    return request.getfixturevalue("real_proxy_upstream")


def test_ba3_the_measurement_launch_proves_isolation_in_its_own_child(required_upstream,
                                                                     tmp_path, monkeypatch):
    """BA-3, the measurement path: through the real launch-owner composition
    (``seat_profile`` plus ``launch_owned(PROVIDER_REVIEW)``), the real budgeted proxy and the
    ``grok-review`` proxy-only namespace, one and the same child completes a request through
    the proxy to the fixture upstream and fails a direct connection to a listener the host
    can reach at that moment. ``measured`` requires both (the stand-in exits non-zero if the
    direct connection succeeds)."""
    _namespace_or_skip()
    _require_bwrap()
    upstream = required_upstream
    listener = _host_reachable_listener()
    address, port = listener.getsockname()[:2]
    try:
        socket.create_connection((address, port), 3).close()
        listener.accept()[0].close()  # reachable from outside the namespace
        bench = Bench(tmp_path, monkeypatch, real=True)
        bench.binary.write_text(_STAND_IN.replace("__TOOLS__", repr(_tools("review")))
                                .replace("__DIRECT__", repr((address, port)))
                                .replace("__VERSION__", repr(VERSION))
                                .replace("__HELP__", repr(HELP)))
        bench.binary.chmod(0o700)
        bench.stand_for(GROK_1_0_89)
        bench.open_grant(planned="review")
        # The real rehearsal's marker was written by the hook inside the real launch_provider.
        names = sorted(p.name for p in (bench.grant_dir() / "rehearsals").iterdir())
        assert len(names) == 2 and names[0].endswith(".attempt.json"), names
        try:
            code, report = bench.measure("review")
        except pi._sandbox_egress.SeatIdentityUnverified as exc:
            if os.environ.get(REQUIRE_NS) == "1":
                raise
            pytest.skip(f"this host cannot own a seat ({exc})")
        listener.setblocking(False)
        with pytest.raises(BlockingIOError):
            listener.accept()  # nothing from the child reached it
    finally:
        listener.close()
    row = report["routes"][0]
    assert code == 0 and row["status"] == "measured", report
    assert [entry[1:3] for entry in upstream.requests] == [("POST", INFERENCE_PATH)]
    status = bench.status()
    assert status["charged"] == 1
    (result,) = bench.results().values()
    assert result["observation"] == {"complete": True, "reason": "complete", "requests": 1,
                                     "counted": 1, "denied": 0}


def test_ba3_the_on_host_isolation_self_check_runs_in_the_real_composition(tmp_path, monkeypatch):
    """BA-3 on the measuring host (``--verify-probe initial``): before any credential, one
    child of the real composition reaches this proxy (its canary is in this proxy's own
    stream) and nothing else; the budget is 0, so nothing is forwarded."""
    _require_layer_or_skip()
    _namespace_or_skip()
    _require_bwrap()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    result = gts.isolation_check(work_root=work)
    assert result == {"passed": True, "code": "isolation_proven"}
    assert not list(work.iterdir())


def test_the_isolation_self_check_fails_closed(tmp_path, monkeypatch):
    """A host where the check cannot run is not eligible: no non-loopback address, or a
    proxy with no proxy-only namespace to hold (the real launch owner refuses that), each
    fails it. Nothing here needs a namespace."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ca = tmp_path / "ca.crt"
    der = b"phase-loop isolation CA " + os.urandom(8)
    ca.write_text(ssl.DER_cert_to_PEM_cert(der))

    @contextlib.contextmanager
    def no_namespace(*, timeout_s, request_budget=None, named=()):
        yield seat_egress_proxy.SeatEgressProxy(
            socket="/fixture.sock", proxy_url="http://srt:token@127.0.0.1:3128", ca_cert=ca,
            ca_sha256=sha256(der).hexdigest(), inner_sni_check=True,
            process=SimpleNamespace(poll=lambda: None), allowlist_id="grok-review",
            allowlist_digest=gts.egress_allowlist_digest(), request_budget=request_budget), ()
    monkeypatch.setattr(pi, "_grok_review_egress", no_namespace)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    with monkeypatch.context() as patch:
        patch.setattr(sandbox_egress, "host_addresses", lambda: ("127.0.0.1", "::1"))
        assert gts.isolation_check(work_root=work) == {
            "passed": False, "code": "isolation_host_unaddressable"}
    if not any(":" not in value and not value.startswith("127.")
               for value in sandbox_egress.host_addresses()):
        pytest.skip("this host has no non-loopback IPv4 address")
    assert gts.isolation_check(work_root=work) == {"passed": False, "code": "isolation_unproven"}
    assert not list(work.iterdir())


def test_ba3_the_final_check_binds_the_exact_live_holder_to_this_proxy(tmp_path, monkeypatch):
    """BA-3 (fix round 1, finding 2) on the real proxy and namespace: two live holders, each
    bridged to its own live proxy of the same policy and budget. Each pair binds; neither
    crossed pair does, and a measurement handed a crossed pair launches nothing."""
    _require_layer_or_skip()
    _namespace_or_skip()
    _require_bwrap()
    with pi._grok_review_egress(timeout_s=300.0, request_budget=1) as (proxy_a, prefix_a), \
            pi._grok_review_egress(timeout_s=300.0, request_budget=1) as (proxy_b, prefix_b):
        assert proxy_a.socket != proxy_b.socket and prefix_a != prefix_b
        assert gts.bridged_to(prefix_a, proxy_a) and gts.bridged_to(prefix_b, proxy_b)
        assert not gts.bridged_to(prefix_a, proxy_b)  # another live proxy, same policy and budget
        assert not gts.bridged_to(prefix_b, proxy_a)  # a mismatched live holder
        bench = Bench(tmp_path, monkeypatch, real=True)
        bench.binary.write_text(_STAND_IN.replace("__TOOLS__", repr(_tools("review")))
                                .replace("__DIRECT__", repr(("127.0.0.1", 9)))
                                .replace("__VERSION__", repr(VERSION))
                                .replace("__HELP__", repr(HELP)))
        bench.binary.chmod(0o700)
        bench.stand_for(GROK_1_0_89)
        bench.open_grant(planned="review")  # its rehearsal runs on a real pair of its own

        @contextlib.contextmanager
        def crossed(*, timeout_s, request_budget=None, named=()):
            yield proxy_b, prefix_a
        monkeypatch.setattr(pi, "_grok_review_egress", crossed)
        code, report = bench.measure("review")
    assert code == 0 and report["routes"][0]["status"] == "context_refused"
    (result,) = bench.results().values()
    assert result["exit_code"] is None  # nothing was launched


WORKFLOW = TESTS.parents[1] / ".github" / "workflows" / "test.yml"


@pytest.mark.skipif(not WORKFLOW.is_file(), reason="the workflow is repository source")
def test_the_hosted_ba3_job_is_mandatory_and_cannot_skip_green():
    """Fix round 1, finding 3: a namespace-capable hosted job runs the BA-3 tests with
    PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1, refuses any skip in its junit, and the suite gate
    requires its success on every event."""
    import yaml

    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    job = jobs["grok-egress-ns"]
    assert "if" not in job and job["runs-on"] == "ubuntu-24.04"
    steps = {step.get("name"): step for step in job["steps"]}
    run = steps["BA-3 isolation and fixture-upstream round trip (no skip)"]
    assert run["env"] == {"PHASE_LOOP_REQUIRE_GROK_EGRESS_NS": "1"}
    for name in ("tests/test_grok_measure_egress.py", "tests/test_grok_tool_surface_measure.py",
                 "--junitxml", "none may"):
        assert name in run["run"], name
    install = steps["Install phase-loop-runtime and the seat egress layer"]["run"]
    assert "phase-loop seat-egress install" in install
    prerequisites = steps["Install review sandbox and seat egress prerequisites"]["run"]
    for name in ("bubblewrap", "uidmap", "socat", "ripgrep", "apparmor_restrict_unprivileged_userns",
                 "/etc/subuid"):
        assert name in prerequisites, name
    gate = jobs["gate"]
    assert "grok-egress-ns" in gate["needs"] and gate["if"] == "always()"
    required = next(step for step in gate["steps"]
                    if step.get("name") == "Require the grok egress namespace check")
    assert required["env"]["GROKNS"] == "${{ needs.grok-egress-ns.result }}"
    assert '"$GROKNS" != "success"' in required["run"]


# ======================================== erratum 3: tolerated startup refusals

def test_the_tolerated_refusals_of_1_0_89_are_the_closed_list_of_erratum_3():
    assert gts.tolerated_refusals(GROK_1_0_89) == (
        ("GET", "cli-chat-proxy.grok.com", "/v1/settings"),
        ("CONNECT", "x.ai", None),
        ("CONNECT", "storage.googleapis.com", None))
    # Not part of the context digest: it qualifies a measurement and constrains no launch.
    assert "tolerated" not in json.dumps(gts.context_document("a" * 64))


@pytest.mark.parametrize("requests", [
    [SETTINGS, ALLOWED], [ALLOWED, SETTINGS], [UPDATER, ALLOWED, ARTIFACTS],
    [SETTINGS, UPDATER, ARTIFACTS, ALLOWED, SETTINGS],
], ids=["before", "after", "both-sides", "all-three-and-a-repeat"])
def test_a_tolerated_refusal_before_or_after_the_counted_request_still_measures(bench, requests):
    bench.open_grant(planned="review")
    bench.default = Scenario(requests=requests)
    report = bench.measure("review")[1]
    assert report["routes"][0]["status"] == "measured", report
    (result,) = bench.results().values()
    expected = {}
    for method, host, path, _decision in requests:
        if (method, host, path) in LEGACY_TOLERATED:
            expected[(method, host, path)] = expected.get((method, host, path), 0) + 1
    assert {(item["method"], item["host"], item["path"]): item["count"]
            for item in result["tolerated_refusals"]} == expected
    assert result["observation"]["denied"] == sum(expected.values())
    bench.cli("--aggregate")
    evidence = json.loads((bench.output / "tool-surface.json").read_text())
    assert evidence["routes"][0]["tolerated_refusals"] == result["tolerated_refusals"]


@pytest.mark.parametrize("extra,status", [
    (("CONNECT", "<other>", None, "deny"), "egress_refused"),          # a sign-in host, or any other
    (("GET", gts.INFERENCE_HOST, "<other>", "deny"), "egress_refused"),  # another path
    (("POST", gts.INFERENCE_HOST, "<other>", "deny"), "egress_refused"),
    (("GET", gts.INFERENCE_HOST, "/v1/settings", "allow"), "egress_refused"),  # not a refusal
    (BUDGET_DENIED, "budget_exhausted"),                               # a second model call
], ids=["other-host", "other-path", "other-post", "allowed-settings", "second-post"])
def test_everything_else_still_disqualifies(bench, extra, status):
    bench.open_grant(planned="review")
    bench.default = Scenario(requests=[SETTINGS, ALLOWED, extra])
    assert bench.measure("review")[1]["routes"][0]["status"] == status


def test_a_tolerated_refusal_does_not_make_up_for_a_missing_counted_request(bench):
    bench.open_grant(planned="review")
    bench.default = Scenario(requests=[SETTINGS, UPDATER])
    assert bench.measure("review")[1]["routes"][0]["status"] == "egress_refused"


def test_the_proxy_names_exactly_the_tolerated_observations(fake_srt):
    """Erratum 3 at the proxy (offline, the real ``proxy.mjs`` over L2a's fake srt): an
    entry of ``named`` is observed verbatim, everything else keeps the closed vocabulary,
    and no decision changes."""
    fake = fake_srt()
    named = LEGACY_TOLERATED
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1,
                                       named=named) as proxy:
        verdicts = fake.decide([
            {"method": "GET", "url": f"https://{gts.INFERENCE_HOST}/v1/settings"},
            {"method": "GET", "url": f"https://{gts.INFERENCE_HOST}/v1/other"},
            {"method": "POST", "url": f"https://{gts.INFERENCE_HOST}{INFERENCE_PATH}"},
        ])
    assert verdicts == ["deny", "deny", "allow"]
    events = [(e.method, e.host, e.path, e.decision)
              for e in seat_egress_proxy.proxy_stream(proxy).outside_events]
    assert events == [SETTINGS, ("GET", gts.INFERENCE_HOST, "<other>", "deny"), ALLOWED]
    assert json.loads(fake.config_copy.read_text())["named"] == [list(e) for e in named]
    assert seat_egress_proxy.completion(proxy).complete


@pytest.mark.parametrize("named", [(("get", "x.ai", None),), (("CONNECT", "X.AI", None),),
                                   (("CONNECT", "x.ai", "no-slash"),), (("CONNECT", "x.ai"),)])
def test_a_malformed_named_observation_is_refused_before_anything_runs(named):
    with pytest.raises(ValueError):
        with seat_egress_proxy.start_proxy(allowlist_id="grok-review", named=named):
            pytest.fail("the proxy started")


def test_the_real_proxy_names_a_tolerated_connect_and_folds_a_sign_in_host(required_upstream):
    """On the real proxy: a refused ``CONNECT x.ai`` is named, a refused sign-in host stays
    ``<other>``, so it can never pass for a tolerated refusal."""
    from test_grok_measure_egress import _exchange, _http
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1,
                                       named=LEGACY_TOLERATED) as proxy:
        for host in ("x.ai", "auth.x.ai", "storage.googleapis.com"):
            status, _reply = _exchange(proxy, host, _http("GET", host, "/"))
            assert status.startswith(b"HTTP/1.1 403"), (host, status)
    events = [(e.method, e.host, e.path, e.decision)
              for e in seat_egress_proxy.proxy_stream(proxy).outside_events]
    assert events == [UPDATER, ("CONNECT", "<other>", None, "deny"), ARTIFACTS]


# ================================================= erratum 4: the binding rehearsal

def test_no_reservation_without_a_passing_rehearsal(bench, monkeypatch):
    bench.open_grant(planned="review", rehearse=False)
    code, report = bench.measure("review")
    assert code == 1 and report["routes"][0] == {"route": "review", "reserved": False,
                                                 "code": "rehearsal_required"}
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert code == 0 and report["result"] == "passed" and report["budget_denials"] == 1
    status = bench.status()
    assert status["charged"] == 0 and status["launches"] == 0  # it charges nothing
    # A rehearsal holds only for the context it ran under.
    monkeypatch.setattr(gts, "DISCOVERY_PATHS", (*gts.DISCOVERY_PATHS, ".vscode"))
    assert bench.measure("review")[1]["routes"][0]["code"] == "rehearsal_required"
    monkeypatch.undo()
    bench = Bench(bench.root, monkeypatch)
    assert bench.measure("review")[1]["routes"][0]["status"] == "measured"


@pytest.mark.parametrize("scenario,reason", [
    (Scenario(requests=[SETTINGS, UPDATER, BUDGET_DENIED, ARTIFACTS], artifact=None), "passed"),
    (Scenario(requests=[SETTINGS, ("CONNECT", "<other>", None, "deny"), BUDGET_DENIED],
              artifact=None), "unlisted_request"),
    (Scenario(requests=[SETTINGS], artifact=None), "no_model_request"),
    (Scenario(requests=[BUDGET_DENIED], artifact=None, killed=True), "observation_incomplete"),
    (Scenario(requests=[BUDGET_DENIED], artifact=None, orderly=False), "observation_incomplete"),
], ids=["tolerated", "unlisted", "no-model-request", "incomplete-killed", "incomplete-no-marker"])
def test_the_rehearsal_passes_only_when_every_observation_is_tolerated(bench, scenario, reason):
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = scenario
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert report["reason"] == reason and (code == 0) is (reason == "passed"), report
    (record,) = [json.loads(p.read_text())
                 for p in (bench.grant_dir() / "rehearsals").glob("????-????????????????.json")]
    gts.check_rehearsal_keys(record)
    assert record["status"] == ("passed" if reason == "passed" else "failed")
    # CI fixes 2: an incomplete observation says what was missing, in the record and the
    # refusal alike; every other rehearsal records none.
    assert report["observation"] == record["observation"]
    assert report["incomplete"] == record["incomplete"]
    if reason != "observation_incomplete":
        assert record["incomplete"] is None
    elif scenario.killed:
        assert record["incomplete"] == {
            "missing": "killed", "marker": False, "last_record": "request", "records": 1,
            "exit_status": -9, "killed": True, "stdout_eof": True, "exited": True,
            "protocol_error": False}
    else:
        assert record["incomplete"] == {
            "missing": "no_end_marker", "marker": False, "last_record": "request",
            "records": 1, "exit_status": 0, "killed": False, "stdout_eof": True,
            "exited": True, "protocol_error": False}
    assert bench.status()["charged"] == 0
    if reason != "passed":
        assert bench.measure("review")[1]["routes"][0]["code"] == "rehearsal_required"
    if reason in ("passed", "unlisted_request"):
        assert bench.rehearsals and bench.rehearsals[-1].proxy.request_budget == 0
        launch = bench.rehearsals[-1]
        assert pi._grok_argv_digest(launch.argv) == pi._grok_argv_digest(_form("review"))
        assert launch.admission.request_budget == 0


def test_only_an_incomplete_observation_records_what_was_missing(bench):
    """CI fixes 2: the ``incomplete`` block is closed, metadata only, and present exactly
    when the rehearsal's reason is ``observation_incomplete``."""
    assert gts._INCOMPLETE_KEYS == {"missing"} | seat_egress_proxy.COMPLETION_DETAIL_KEYS
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[BUDGET_DENIED], artifact=None, killed=True)
    bench.cli("--attended", "--rehearse", "--route", "review")
    (path,) = (bench.grant_dir() / "rehearsals").glob("????-????????????????.json")
    record = json.loads(path.read_text())
    gts.check_rehearsal_keys(record)
    for change in ({"incomplete": None},
                   {"incomplete": {**record["incomplete"], "stderr": "text"}},
                   {"incomplete": {**record["incomplete"], "missing": "not a reason"}},
                   {"incomplete": {**record["incomplete"], "last_record": "other"}},
                   {"incomplete": {**record["incomplete"], "killed": "yes"}},
                   {"incomplete": {**record["incomplete"], "exit_status": True}},
                   {"reason": "unlisted_request"}):
        with pytest.raises(gts._Refused):
            gts.check_rehearsal_keys({**record, **change})


@pytest.mark.parametrize("scenario,code", [
    (Scenario(requests=[BUDGET_DENIED], artifact=None, crossed=True), "context_refused"),
    (Scenario(requests=[BUDGET_DENIED], artifact=None, egress_fails=True), "egress_refused"),
], ids=["crossed-holder", "no-egress"])
def test_a_refusal_before_anything_launched_is_no_rehearsal(bench, scenario, code):
    """Nothing launched, so nothing is recorded, and the grant keeps its one rehearsal."""
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = scenario
    result, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (result, report["code"]) == (1, code)
    assert bench.rehearsals == [] and not list((bench.grant_dir() / "rehearsals").glob("????-????????????????.json"))
    bench.rehearsal = Scenario(requests=[BUDGET_DENIED], artifact=None)
    assert bench.cli("--attended", "--rehearse", "--route", "review")[1]["result"] == "passed"


def test_the_rehearsal_is_attended_and_names_one_route(bench):
    bench.open_grant(planned="review,sealed", rehearse=False)
    assert bench.cli("--rehearse", "--route", "review")[1]["code"] == "attendance_required"
    code, report = bench.cli("--attended", "--rehearse", "--route", "review", "--route", "sealed")
    assert code == 2 and report["code"] == "one_route_to_rehearse"
    code, report = bench.cli("--attended", "--rehearse", "--route", "staged")
    assert code == 1 and report["code"] == "route_not_planned"
    code, report = bench.cli("--attended", "--rehearse", "--route", "sealed")
    assert code == 1 and report["code"] == "route_not_pilot"  # the pilot's exact launch


# ============================================= erratum 3: output location, host class

def test_the_output_is_any_private_state_path_and_the_ledger_stays_in_the_record_root(bench):
    elsewhere = bench.state / "operator-chosen" / "grok-run"
    bench.open_grant(planned="review", output=elsewhere)
    bench.measure("review", output=elsewhere)
    code, report = bench.cli("--aggregate", "--host-class", "team", output=elsewhere)
    assert code == 0 and report["published"] == ["review"]
    evidence = json.loads((elsewhere / "tool-surface.json").read_text())
    assert evidence["host_class"] == "team"
    root = pa.private_record_root()
    assert root not in elsewhere.parents and (root / gts.GRANTS_DIRNAME / GRANT).is_dir()
    assert (root / gts.host_record_name(bench.digest)).is_file()


def test_one_rehearsal_per_grant(bench):
    bench.open_grant(planned="review")
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert code == 1 and report["code"] == "rehearsal_exists"
    assert len(list((bench.grant_dir() / "rehearsals").glob("????-????????????????.json"))) == 1


def test_one_failed_rehearsal_closes_the_grant_to_launches(bench):
    """A failed rehearsal stops the procedure: no second rehearsal, no pilot."""
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[("CONNECT", "<other>", None, "deny"), BUDGET_DENIED],
                               artifact=None)
    assert bench.cli("--attended", "--rehearse", "--route", "review")[0] == 1
    assert bench.cli("--attended", "--rehearse", "--route", "review")[1]["code"] == \
        "rehearsal_exists"
    assert bench.measure("review")[1]["routes"][0]["code"] == "rehearsal_required"


def test_require_rehearsed_gates_the_pilot(bench, monkeypatch):
    """Erratum 4, step 5: non-zero unless the grant holds a passing rehearsal of the route,
    for its binary and the context the code now enforces."""
    bench.open_grant(planned="review,sealed", rehearse=False)
    code, report = bench.cli("--require-rehearsed", "review")
    assert (code, report["status"]) == (1, "no_rehearsal")
    bench.cli("--attended", "--rehearse", "--route", "review")
    code, report = bench.cli("--require-rehearsed", "review")
    assert (code, report["status"], report["reason"]) == (0, "rehearsed", "passed")
    assert bench.cli("--require-rehearsed", "sealed")[0] == 1  # only the pilot is rehearsed
    status = bench.status()
    assert status["rehearsal"]["status"] == "passed" and status["launches"] == 0
    monkeypatch.setattr(gts, "DISCOVERY_PATHS", (*gts.DISCOVERY_PATHS, ".vscode"))
    code, report = bench.cli("--require-rehearsed", "review")
    assert (code, report["status"]) == (1, "not_rehearsed")


def test_require_rehearsed_fails_after_a_failed_rehearsal(bench):
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[SETTINGS], artifact=None)
    bench.cli("--attended", "--rehearse", "--route", "review")
    code, report = bench.cli("--require-rehearsed", "review")
    assert (code, report["status"], report["reason"]) == (1, "not_rehearsed", "no_model_request")


def test_a_rehearsals_session_artifact_is_never_a_capture(bench):
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[SETTINGS, BUDGET_DENIED], artifact="admitted")
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert code == 0 and report["result"] == "passed"
    (record,) = [json.loads(p.read_text()) for p in (bench.grant_dir() / "rehearsals").glob("????-????????????????.json")]
    assert record["observed"] == [
        {"method": "GET", "host": gts.INFERENCE_HOST, "path": "/v1/settings", "decision": "deny"},
        {"method": "POST", "host": gts.INFERENCE_HOST, "path": INFERENCE_PATH, "decision": "deny"}]
    assert record["tolerated_refusals"] == [
        {"method": "GET", "host": gts.INFERENCE_HOST, "path": "/v1/settings", "count": 1}]
    assert not list(bench.output.rglob("tool_definitions.json"))  # nothing copied out
    assert not list(bench.output.glob("scratch-*"))  # removed with the scratch directory
    assert not bench.results() and not list((bench.grant_dir() / "results").iterdir())
    assert SENTINEL not in json.dumps(record)


# ================================================================== fix round 2

def test_a_rehearsal_killed_after_its_launch_is_spent_with_no_pass(bench):
    """Finding 1: the attempt marker is committed at the launch boundary, before the child
    can start; a SIGKILL after it and before the record leaves the grant's one rehearsal
    spent, with no passing outcome, whatever output directory asks next."""
    bench.open_grant(planned="review", rehearse=False)
    ready = bench.root / "ready"
    process = _driver(bench, ["--attended", "--rehearse", "--route", "review"],
                      scenarios={"__rehearsal__": {"requests": [list(BUDGET_DENIED)],
                                                   "artifact": None, "block": str(ready)}})
    _wait_for(ready, process)
    _kill(process)
    folder = bench.grant_dir() / "rehearsals"
    assert [p.name.endswith(".attempt.json") for p in folder.iterdir()] == [True]
    code, report = bench.cli("--attended", "--rehearse", "--route", "review",
                             output=bench.root / "state" / "another-output")
    assert (code, report["code"]) == (1, "rehearsal_exists")
    code, report = bench.cli("--require-rehearsed", "review")
    assert (code, report["status"]) == (1, "interrupted")
    assert bench.status()["rehearsal"]["status"] == "interrupted"
    assert bench.measure("review")[1]["routes"][0]["code"] == "rehearsal_required"


def test_the_attempt_marker_comes_after_every_pre_launch_refusal(bench):
    """A refusal positively before the launch boundary writes no marker, so it may be
    retried; once the boundary is crossed the marker exists even if the launch fails."""
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[BUDGET_DENIED], artifact=None, crossed=True)
    assert bench.cli("--attended", "--rehearse", "--route", "review")[1]["code"] == \
        "context_refused"
    assert not list((bench.grant_dir() / "rehearsals").iterdir())
    bench.rehearsal = Scenario(requests=[BUDGET_DENIED], artifact=None, hang=True)
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (code, report["reason"]) == (1, "launch_failed")
    names = sorted(p.name for p in (bench.grant_dir() / "rehearsals").iterdir())
    assert len(names) == 2 and names[0].endswith(".attempt.json")


def test_only_the_budgets_own_refusal_passes_a_rehearsal(bench):
    """Finding 2: an inference-shaped POST refused by the inner Host check -- which runs
    before the budget -- is not the budget's refusal and fails the rehearsal."""
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[SETTINGS, INNER_HOST_DENIED], artifact=None)
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (code, report["reason"], report["budget_denials"]) == (1, "unlisted_request", 0)


def test_an_inner_host_refusal_is_not_budget_exhausted(bench):
    bench.open_grant(planned="review")
    bench.default = Scenario(requests=[ALLOWED, INNER_HOST_DENIED])
    assert bench.measure("review")[1]["routes"][0]["status"] == "egress_refused"


def test_the_stream_carries_a_cause_only_from_a_budgeted_proxy():
    item = {"event": "request", "method": "POST", "host": gts.INFERENCE_HOST,
            "path": INFERENCE_PATH, "decision": "deny"}
    rules = seat_egress_proxy.allowlist_ref("grok-review").request_set
    assert seat_egress_proxy._valid_request_event(item, rules)
    for cause in sorted(seat_egress_proxy.EVENT_CAUSES):
        assert seat_egress_proxy._valid_request_event({**item, "cause": cause}, rules, budgeted=True)
        assert not seat_egress_proxy._valid_request_event({**item, "cause": cause}, rules)
    assert not seat_egress_proxy._valid_request_event({**item, "cause": "because"}, rules,
                                                      budgeted=True)


def test_the_real_proxy_reports_which_check_refused_an_inference_post(required_upstream):
    """On the real proxy: the inner Host check and the budget each name themselves."""
    from test_grok_measure_egress import _exchange, _http
    post = _http("POST", gts.INFERENCE_HOST, INFERENCE_PATH)
    foreign = post.replace(f"Host: {gts.INFERENCE_HOST}".encode(), b"Host: elsewhere.example")
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1,
                                       named=LEGACY_TOLERATED) as proxy:
        for request in (foreign, post, post):
            _exchange(proxy, gts.INFERENCE_HOST, request)
    events = [(e.method, e.host, e.path, e.decision, e.cause)
              for e in seat_egress_proxy.proxy_stream(proxy).outside_events]
    assert events == [INNER_HOST_DENIED, (*ALLOWED, "allowed"), BUDGET_DENIED]
    assert [gts._budget_denial(e) for e in seat_egress_proxy.proxy_stream(proxy).outside_events] \
        == [False, False, True]


def _raw_connect(proxy, authority: str) -> bytes:
    """A CONNECT to ``authority`` exactly as written, through the proxy's socket."""
    from test_grok_measure_egress import _authorization, _read_head
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(20)
    sock.connect(proxy.socket)
    try:
        sock.sendall(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n".encode()
                     + b"Proxy-Authorization: Basic " + _authorization(proxy) + b"\r\n\r\n")
        return _read_head(sock).split(b"\r\n", 1)[0]
    finally:
        sock.close()


def test_a_tolerated_connect_is_the_exact_authority_port_443_included(required_upstream):
    """Finding 3, on the real proxy: CONNECTs to x.ai and storage.googleapis.com on any
    port but 443 are neither named nor tolerated; on 443 they are."""
    authorities = ("x.ai:8443", "storage.googleapis.com:80", "x.ai:0443",
                   "storage.googleapis.com:0443", "x.ai:443", "storage.googleapis.com:443")
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1,
                                       named=LEGACY_TOLERATED) as proxy:
        for authority in authorities:
            assert _raw_connect(proxy, authority).startswith(b"HTTP/1.1 403"), authority
    events = seat_egress_proxy.proxy_stream(proxy).outside_events
    # Zero-padded 443 (fix round 3) is not the authority either: neither named nor tolerated.
    assert [(e.method, e.host, e.path, e.decision) for e in events] == [
        ("CONNECT", "<other>", None, "deny")] * 4 + [UPDATER, ARTIFACTS]
    assert gts.tolerated_summary(events, GROK_1_0_89) == [
        {"method": "CONNECT", "host": "x.ai", "path": None, "count": 1},
        {"method": "CONNECT", "host": "storage.googleapis.com", "path": None, "count": 1}]


def test_a_local_copy_io_error_after_the_grant_commit_is_a_recorded_result(bench, monkeypatch):
    """Finding 4: a regular I/O error writing the local copy, after the grant has the
    record, is reported apart; the route is recorded and the stage exits 0."""
    bench.open_grant(planned="review,sealed")
    real_commit = gts._commit_new

    local = str((bench.output / "results").resolve())

    def commit(directory, name, payload):
        if os.path.realpath(f"/proc/self/fd/{directory}") == local:  # the local copy only
            raise OSError(28, "No space left on device")
        return real_commit(directory, name, payload)
    monkeypatch.setattr(gts, "_commit_new", commit)
    code, report = bench.measure("review", "sealed")
    assert code == 0, report
    assert [(row["status"], row["local_copy"]) for row in report["routes"]] == [
        ("measured", "failed"), ("measured", "failed")]
    monkeypatch.setattr(gts, "_commit_new", real_commit)
    rows = _route_rows(bench.status())
    assert rows["review"]["local_payload"] == "missing"
    assert bench.cli("--require-measured", "review")[0] == 0
    assert bench.cli("--aggregate")[1]["published"] == ["review", "sealed"]


def test_an_error_after_the_grant_commit_reconciles_against_the_grant(bench, monkeypatch):
    bench.open_grant(planned="review,sealed")
    real_write = gts._write_result

    def write(stage, result):
        real_write(stage, result)
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(gts, "_write_result", write)
    code, report = bench.measure("review", "sealed")
    assert code == 1  # sealed never reserved
    assert report["routes"][0] == {"route": "review", "reserved": True,
                                   "reservation": report["routes"][0]["reservation"],
                                   "status": "measured", "local_copy": "present",
                                   "error": "after_commit"}
    assert report["routes"][1] == {"route": "sealed", "reserved": False, "code": "not_attempted"}
    assert _route_rows(bench.status())["review"]["state"] == "recorded"
    code, report = bench.measure("sealed")
    assert code == 0 and report["routes"][0]["status"] == "measured"  # alone: exit 0


# ================================================================== fix round 3

REAL_LAUNCH_OWNED = pi.launch_owned


def test_a_refusal_inside_the_real_launch_path_leaves_the_rehearsal_retryable(bench, monkeypatch):
    """Finding 1, through the real ``launch_owned``: the live holder disappears after the
    measurement's own checks and before the launch path's final holder check, which
    refuses before any process exists. No marker is written, nothing is recorded, and the
    grant keeps its one rehearsal."""
    bench.open_grant(planned="review", rehearse=False)
    monkeypatch.setattr(pi, "launch_owned", REAL_LAUNCH_OWNED)
    spawned = []
    monkeypatch.setattr(pi, "launch_provider", lambda *a, **k: spawned.append(a) or pytest.fail(
        "a process was created"))
    checks = []

    def holder():
        checks.append(True)
        # The admission and the final context check see it; the launch path does not.
        if len(checks) > 2:
            raise sandbox_egress.EgressUnavailable("seat_filtered_egress_unavailable")
        return 1
    monkeypatch.setattr(pi, "_filtered_holder_namespace", holder)
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (code, report["code"]) == (1, "launch_refused")
    assert len(checks) == 3 and spawned == []
    assert not list((bench.grant_dir() / "rehearsals").iterdir())
    monkeypatch.undo()
    bench = Bench(bench.root, monkeypatch)
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert code == 0 and report["result"] == "passed"


def test_a_refusal_raised_by_the_launch_path_writes_no_marker(bench):
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=[BUDGET_DENIED], artifact=None, refuse_in_launch_path=True)
    assert bench.cli("--attended", "--rehearse", "--route", "review")[1]["code"] == "launch_refused"
    assert not list((bench.grant_dir() / "rehearsals").iterdir())


def test_the_spawn_hook_runs_after_the_launch_paths_checks_and_before_the_process(tmp_path,
                                                                                monkeypatch):
    """Offline, through the real ``launch_provider``: the hook runs once, immediately before
    the process is created (the child sees the file the hook wrote); a hook that raises
    creates no process."""
    marker = tmp_path / "marked"
    calls = []

    def hook():
        calls.append(True)
        marker.write_text("marked")
    process = pi.launch_provider(["/bin/sh", "-c", f"test -e {marker}"], cwd=str(tmp_path),
                                 spawn_hook=hook)
    assert process.wait(timeout=30) == 0 and calls == [True]
    counted = []
    monkeypatch.setattr(pi, "_count_provider_spawn", lambda: counted.append(True))

    def refuse():
        raise OSError("the marker could not be committed")
    with pytest.raises(OSError):
        pi.launch_provider(["/bin/sh", "-c", "exit 0"], cwd=str(tmp_path), spawn_hook=refuse)
    assert counted == []


_BWRAP_OWNER = ["/usr/bin/bwrap", "--unshare-pid", "--ro-bind", "/", "/", "--"]


def _refuse_witness_args(monkeypatch):
    """A refusal in building the bwrap witness's arguments: after the seat-identity probe,
    which round 3's hook preceded, and before Popen."""
    monkeypatch.setattr(pi, "_require_seat_identity", lambda *a, **k: None)
    abandoned = []
    real = pi._tree_proof.BwrapLaunch

    class Witness(real):
        def abandon(self):
            abandoned.append(True)
            return super().abandon()
    monkeypatch.setattr(pi._tree_proof, "BwrapLaunch", Witness)

    def refuse(*args):
        raise pi._sandbox_egress.SeatIdentityUnverified("seat_owner_unavailable")
    monkeypatch.setattr(pi, "_with_bwrap_lifecycle_fds", refuse)
    return abandoned


def test_a_refusal_building_the_witness_arguments_never_reaches_the_hook(tmp_path, monkeypatch):
    """Fix round 4, the ordinary owned branch: the bwrap witness's arguments are built
    before the hook, so their refusal creates no process and calls no hook."""
    abandoned = _refuse_witness_args(monkeypatch)
    calls, spawned = [], []
    monkeypatch.setattr(pi, "_count_provider_spawn", lambda: spawned.append(True))
    token = pi._OWNED_LAUNCH.set(True)
    try:
        with pytest.raises(pi._sandbox_egress.SeatIdentityUnverified):
            pi.launch_provider(["/bin/true"], process_owner=_BWRAP_OWNER, cwd=str(tmp_path),
                               spawn_hook=lambda: calls.append(True))
    finally:
        pi._OWNED_LAUNCH.reset(token)
    assert calls == [] and spawned == [] and abandoned == [True]


@pytest.mark.real_seat_caps  # the production capped_popen, not conftest's stand-in
def test_a_capped_preflight_refusal_never_reaches_the_hook(tmp_path, monkeypatch):
    """Fix round 4, the capped path: ``capped_popen``'s preflight refuses (here, no caps
    record) before its spawn boundary, so the hook -- the rehearsal's marker -- never runs."""
    from phase_loop_runtime import seat_resource_caps
    marker = tmp_path / "marker"

    def no_caps():
        raise seat_resource_caps.CapsUnavailable("no caps record")
    monkeypatch.setattr(seat_resource_caps, "load_caps", no_caps)
    with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
        pi.launch_provider(["/bin/true"], seat_caps="seat-test", cwd=str(tmp_path),
                           spawn_hook=lambda: marker.write_text("spent"))
    assert refusal.value.code == seat_resource_caps.CODE
    assert not marker.exists()
    # Retryable: the same hook still runs on a launch that reaches the spawn boundary.
    assert pi.launch_provider(["/bin/true"], cwd=str(tmp_path),
                              spawn_hook=lambda: marker.write_text("spent")).wait(30) == 0
    assert marker.read_text() == "spent"


@pytest.mark.real_seat_caps  # the production capped_popen, not conftest's stand-in
def test_the_capped_spawn_boundary_is_after_every_preflight_check():
    """Structural: inside ``capped_popen`` the hook is the statement right before its one
    ``subprocess.Popen``, after the seat key, scope, caps, controller and environment
    checks; and a raising hook surfaces as the OSError it releases its parent on."""
    import ast
    import inspect
    from phase_loop_runtime import seat_resource_caps
    source = inspect.getsource(seat_resource_caps.capped_popen)
    assert source.index("readiness_code()") < source.index("before_spawn()") \
        < source.index("subprocess.Popen(argv")
    body = [node for node in ast.walk(ast.parse(source.lstrip()))
            if isinstance(node, ast.Try) and any(
                isinstance(item, ast.Assign) and "Popen" in ast.unparse(item) for item in node.body)]
    (spawn,) = body
    assert ast.unparse(spawn.body[0]).startswith("if before_spawn is not None:")
    wrapped = pi._caps_spawn_hook(lambda: (_ for _ in ()).throw(
        gts.MeasurementRefused("private_storage_unavailable")))
    with pytest.raises(OSError):
        wrapped()


def test_a_witness_argument_refusal_leaves_the_rehearsal_retryable(bench, monkeypatch):
    """The same refusal through a real rehearsal: the real ``launch_owned`` and the real
    ``launch_provider`` refuse while building the witness's arguments; no marker is
    written and the retry passes."""
    bench.open_grant(planned="review", rehearse=False)
    monkeypatch.setattr(pi, "launch_owned", REAL_LAUNCH_OWNED)
    from phase_loop_runtime import seat_seccomp
    monkeypatch.setattr(seat_seccomp, "sealed_keyring_filter",
                        lambda: os.open(os.devnull, os.O_RDONLY))
    monkeypatch.setattr(pi, "_seat_owner", lambda view, **kwargs: list(_BWRAP_OWNER))
    abandoned = _refuse_witness_args(monkeypatch)
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (code, report["code"]) == (1, "launch_refused")
    assert abandoned == [True]
    assert not list((bench.grant_dir() / "rehearsals").iterdir())
    monkeypatch.undo()
    bench = Bench(bench.root, monkeypatch)
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert code == 0 and report["result"] == "passed"

# ================== erratum 8: per-image tolerated refusals, the rehearsal, the client log

ARCHIVE = ("GET", gts.INFERENCE_HOST, "/v1/bundle/archive", "deny")
ROOT = ("GET", gts.INFERENCE_HOST, "/", "deny")
SUBAGENTS = ("GET", gts.INFERENCE_HOST, "/v1/subagents/bundle", "deny")
FEEDBACK = ("GET", gts.INFERENCE_HOST, "/v1/feedback/config", "deny")
#: One of the two pre-turn calls on another model (grok 1.0.92).
RESPONSES = ("POST", gts.INFERENCE_HOST, "/v1/responses", "deny")


@pytest.fixture
def bench92(tmp_path, monkeypatch):
    """A bench whose stand-in binary stands for grok 1.0.92."""
    return Bench(tmp_path, monkeypatch, image=GROK_1_0_92)


def _rehearse(bench, requests):
    """One rehearsal of the pilot observing ``requests``: ``(exit code, report)``."""
    bench.open_grant(planned="review", rehearse=False)
    bench.rehearsal = Scenario(requests=list(requests), artifact=None, exit=1)
    return bench.cli("--attended", "--rehearse", "--route", "review")


def _pilot(bench, requests):
    """One measurement of the pilot observing ``requests``: ``(status, result record)``."""
    bench.open_grant(planned="review")
    bench.default = Scenario(requests=list(requests))
    report = bench.measure("review")[1]
    (result,) = bench.results().values()
    assert result["status"] == report["routes"][0]["status"]
    return result["status"], result


def test_each_tolerated_entry_names_the_check_that_refuses_it():
    """The two updater CONNECTs of 1.0.89 are refused by the front; every other entry is a
    request the rules refuse inside a tunnel to the inference host."""
    by_check = {}
    for entries in SHIPPED_TOLERATED.values():
        for entry in entries:
            by_check.setdefault(gts._refusing_check(entry), []).append(entry)
    assert by_check["front"] == [("CONNECT", "x.ai", None),
                                 ("CONNECT", "storage.googleapis.com", None)]
    assert len(by_check["rules"]) == 6 and set(by_check) == {"front", "rules"}
    assert all(host == gts.INFERENCE_HOST and path is not None
               for _method, host, path in by_check["rules"])


@pytest.mark.parametrize("image,entry,cause", [
    (GROK_1_0_89, SETTINGS, "inner_host"), (GROK_1_0_89, UPDATER, "rules"),
    (GROK_1_0_89, ARTIFACTS, "inner_host"), (GROK_1_0_92, ARCHIVE, "inner_host"),
    (GROK_1_0_92, ROOT, "shutdown"), (GROK_1_0_92, FEEDBACK, "front"),
    (GROK_1_0_92, RESPONSES, "inner_host"), (GROK_1_0_92, RESPONSES, "budget"),
], ids=["settings-inner-host", "updater-rules", "artifacts-inner-host", "archive-inner-host",
        "root-shutdown", "feedback-front", "responses-inner-host", "responses-budget"])
@pytest.mark.parametrize("stage", ["rehearsal", "measurement"])
def test_an_entry_is_tolerated_only_as_the_allow_lists_own_refusal(tmp_path, monkeypatch, image,
                                                                   entry, cause, stage):
    """A listed observation refused by any check but its own -- the inner Host check, the
    budget, the shutdown -- is not a tolerated refusal, in a rehearsal or a measurement."""
    bench = Bench(tmp_path, monkeypatch, image=image)
    if stage == "rehearsal":
        code, report = _rehearse(bench, [(*entry, cause), BUDGET_DENIED])
        assert (code, report["reason"]) == (1, "unlisted_request"), report
        assert report["tolerated_refusals"] == []
    else:
        status, result = _pilot(bench, [(*entry, cause), ALLOWED])
        assert status == "egress_refused" and result["tolerated_refusals"] == []


def test_the_ordering_rule_a_tolerated_post_counts_only_before_the_inference_request(
        tmp_path, monkeypatch):
    """THE ORDERING RULE (erratum 8, item 2), as the erratum states it. ``POST /v1/responses``
    is tolerated only before the inference request: the counted request of a measurement,
    the first budget denial of a rehearsal. One after it disqualifies the launch, while a
    tolerated GET may come before or after. Relaxing the rule is one line in
    ``grok_tool_surface._only_before_inference``; this test then fails at its ``late`` cases
    and is the place to record the new decision."""
    only_before = [entry for entries in SHIPPED_TOLERATED.values() for entry in entries
                   if gts._only_before_inference(entry)]
    assert only_before == [RESPONSES[:3]]

    def bench(name):
        root = tmp_path / name
        root.mkdir()
        return Bench(root, monkeypatch, image=GROK_1_0_92)

    # Before the inference request: tolerated, any number of times.
    code, report = _rehearse(bench("early-rehearsal"), [RESPONSES, RESPONSES, BUDGET_DENIED])
    assert (code, report["reason"]) == (0, "passed"), report
    assert report["tolerated_refusals"] == [
        {"method": "POST", "host": gts.INFERENCE_HOST, "path": "/v1/responses", "count": 2}]
    status, result = _pilot(bench("early-pilot"), [RESPONSES, RESPONSES, ALLOWED])
    assert status == "measured" and result["tolerated_refusals"][0]["count"] == 2
    # After it: the launch is disqualified, and the record does not call the late one
    # tolerated. A tolerated GET after the inference request still is.
    code, report = _rehearse(bench("late-rehearsal"),
                             [RESPONSES, BUDGET_DENIED, RESPONSES, FEEDBACK])
    assert (code, report["reason"]) == (1, "unlisted_request"), report
    assert report["tolerated_refusals"] == [
        {"method": "GET", "host": gts.INFERENCE_HOST, "path": "/v1/feedback/config", "count": 1},
        {"method": "POST", "host": gts.INFERENCE_HOST, "path": "/v1/responses", "count": 1}]
    status, result = _pilot(bench("late-pilot"), [RESPONSES, ALLOWED, RESPONSES])
    assert status == "egress_refused"
    assert [item["count"] for item in result["tolerated_refusals"]] == [1]
    assert _pilot(bench("late-get"), [ALLOWED, FEEDBACK])[0] == "measured"
    # With no inference request at all the POSTs are all "before" it, and the launch fails
    # on the missing request, never on their order.
    assert _rehearse(bench("no-inference"), [RESPONSES])[1]["reason"] == "no_model_request"


def _on_the_allow_list(method, host, path):
    rules = seat_egress_proxy.allowlist_ref(gts.EGRESS_ALLOWLIST_ID).request_set
    if path is None:  # a CONNECT: is a tunnel to this host admitted at all?
        return any(rule["host"] == host for rule in rules)
    return any(rule["host"] == host and rule["method"] == method
               and (path == rule["path"] if "path" in rule else path.startswith(rule["path_prefix"]))
               for rule in rules)


def test_the_tolerated_map_is_the_closed_map_of_erratum_8():
    """Erratum 8, item 2: the map, exactly. An entry or an image needs an erratum."""
    host = "cli-chat-proxy.grok.com"
    assert dict(SHIPPED_TOLERATED) == {
        GROK_1_0_89: (("GET", host, "/v1/settings"), ("CONNECT", "x.ai", None),
                      ("CONNECT", "storage.googleapis.com", None)),
        GROK_1_0_92: (("GET", host, "/v1/bundle/archive"), ("GET", host, "/"),
                      ("GET", host, "/v1/subagents/bundle"), ("GET", host, "/v1/feedback/config"),
                      ("POST", host, "/v1/responses"))}
    assert host == gts.INFERENCE_HOST and not hasattr(gts, "TOLERATED_REFUSALS")
    with pytest.raises(TypeError):
        SHIPPED_TOLERATED["f" * 64] = ()  # closed: not a table a caller can extend
    for image, entries in SHIPPED_TOLERATED.items():
        assert gts.tolerated_refusals(image) == entries
        assert len(entries) <= 16  # the proxy's named channel
        # Refused only: nothing tolerated is on the allow-list, so nothing is ever forwarded
        # or counted, and adding an entry adds nothing to the allow-list.
        assert not any(_on_the_allow_list(*entry) for entry in entries), image
    # What stays untolerated for 1.0.92: the settings and model-list fetches (the pinned seat
    # config was not honoured if either appears) and the 1.0.89 updater's CONNECTs.
    for never in (("GET", host, "/v1/settings"), ("GET", host, "/v1/models"),
                  ("CONNECT", "x.ai", None), ("CONNECT", "storage.googleapis.com", None),
                  ("GET", host, "<other>"), ("POST", host, "<other>"), ("GET", "<other>", "<other>")):
        assert never not in gts.tolerated_refusals(GROK_1_0_92), never
    # Not part of the context digest: it qualifies a measurement and constrains no launch.
    assert "tolerated" not in json.dumps(gts.context_document("a" * 64))


@pytest.mark.parametrize("image", ["f" * 64, GROK_1_0_92.upper(), GROK_1_0_92[:-1], "", None, 7,
                                   (GROK_1_0_92,)])
def test_an_image_the_map_does_not_hold_has_no_entries(image):
    assert gts.tolerated_refusals(image) == ()
    event = seat_egress_proxy.RequestEvent(method="GET", host=gts.INFERENCE_HOST,
                                           path="/v1/bundle/archive", decision="deny", cause="rules")
    assert gts._tolerated([event], image) == [None] and gts.tolerated_summary([event], image) == []
    assert gts._tolerated([event], GROK_1_0_92) == [ARCHIVE[:3]]


@pytest.mark.parametrize("image", [GROK_1_0_89, GROK_1_0_92, None], ids=["1.0.89", "1.0.92", "absent"])
def test_each_launch_names_exactly_its_images_entries_to_the_proxy(tmp_path, monkeypatch, image):
    """The rehearsal's proxy and the measurement's are both started with the entries of the
    image the grant pins, and with nothing for an image the map does not hold."""
    bench = Bench(tmp_path, monkeypatch, image=image)
    bench.open_grant(planned="review")
    assert bench.status()["grant"]["binary_sha256"] == bench.digest  # the key: the grant's pin
    assert bench.measure("review")[1]["routes"][0]["status"] == "measured"
    expected = () if image is None else SHIPPED_TOLERATED[image]
    assert [(proxy.request_budget, proxy.named) for proxy in bench.proxies] == [
        (0, expected), (1, expected)]


def test_the_proxy_names_the_entries_of_1_0_92_and_nothing_else(fake_srt):
    """Erratum 8 at the proxy (offline, the real ``proxy.mjs`` over lane L2a's fake srt): the
    five entries are observed verbatim, each refused by the rules; the settings and
    model-list fetches stay ``<other>``; no decision changes, and nothing but the inference
    request is allowed."""
    fake = fake_srt()
    named = SHIPPED_TOLERATED[GROK_1_0_92]
    paths = ["/v1/bundle/archive", "/", "/v1/subagents/bundle", "/v1/feedback/config",
             "/v1/settings", "/v1/models"]
    with seat_egress_proxy.start_proxy(allowlist_id="grok-review", request_budget=1,
                                       named=named) as proxy:
        verdicts = fake.decide(
            [{"method": "GET", "url": f"https://{gts.INFERENCE_HOST}{path}"} for path in paths]
            + [{"method": "POST", "url": f"https://{gts.INFERENCE_HOST}/v1/responses"}] * 2
            + [{"method": "POST", "url": f"https://{gts.INFERENCE_HOST}{INFERENCE_PATH}"},
               {"method": "POST", "url": f"https://{gts.INFERENCE_HOST}/v1/responses"}])
    assert verdicts == ["deny"] * 8 + ["allow", "deny"]
    stream = seat_egress_proxy.proxy_stream(proxy).outside_events
    other = ("GET", gts.INFERENCE_HOST, "<other>", "deny")
    assert [(e.method, e.host, e.path, e.decision) for e in stream] == [
        ARCHIVE, ROOT, SUBAGENTS, FEEDBACK, other, other, RESPONSES, RESPONSES, ALLOWED, RESPONSES]
    assert [e.cause for e in stream] == ["rules"] * 8 + ["allowed", "rules"]
    assert json.loads(fake.config_copy.read_text())["named"] == [list(e) for e in named]
    assert seat_egress_proxy.completion(proxy).complete
    # The same predicate reads the real stream: the two fetches and the late POST are not
    # tolerated, and the counts say so.
    assert gts._tolerated(stream, GROK_1_0_92) == [
        ARCHIVE[:3], ROOT[:3], SUBAGENTS[:3], FEEDBACK[:3], None, None, RESPONSES[:3],
        RESPONSES[:3], None, None]
    assert [item["count"] for item in gts.tolerated_summary(stream, GROK_1_0_92)] == [1, 1, 1, 1, 2]


#: Erratum 8, item 7: what a rehearsal of grok 1.0.92 (``add4d201...``) with the pinned seat
#: config is expected to observe under a budget-0 proxy -- four GETs once each, the two
#: pre-turn POSTs, then the inference request refused by the budget -- in the order of the
#: offline launch. ``(method, host, path, decision, cause)``.
EXPECTED_REHEARSAL_1_0_92 = (
    (*ARCHIVE, "rules"), (*ROOT, "rules"), (*SUBAGENTS, "rules"), (*FEEDBACK, "rules"),
    (*RESPONSES, "rules"), (*RESPONSES, "rules"), BUDGET_DENIED)


def _tolerated_counts(report):
    return {(item["method"], item["path"]): item["count"] for item in report["tolerated_refusals"]}


def test_the_rehearsal_of_1_0_92_passes_on_the_tabled_observation(bench92):
    """Erratum 8, item 7, the table as a fixture: nothing allowed, only tolerated refusals,
    and the budget's own denial of the inference request. The client's exit status (1) does
    not matter; a passing rehearsal lets the pilot reserve."""
    assert [row[:3] for row in EXPECTED_REHEARSAL_1_0_92[:-1]] == [
        *SHIPPED_TOLERATED[GROK_1_0_92], RESPONSES[:3]]
    code, report = _rehearse(bench92, EXPECTED_REHEARSAL_1_0_92)
    assert (code, report["result"], report["reason"]) == (0, "passed", "passed"), report
    assert report["budget_denials"] == 1
    assert report["observation"] == {"complete": True, "reason": "complete", "requests": 7,
                                     "counted": 0, "denied": 7}
    assert _tolerated_counts(report) == {
        ("GET", "/v1/bundle/archive"): 1, ("GET", "/"): 1, ("GET", "/v1/subagents/bundle"): 1,
        ("GET", "/v1/feedback/config"): 1, ("POST", "/v1/responses"): 2}
    (record,) = [json.loads(p.read_text()) for p in
                 (bench92.grant_dir() / "rehearsals").glob("????-????????????????.json")]
    gts.check_rehearsal_keys(record)
    assert record["binary_sha256"] == bench92.digest and record["exit_code"] == 1
    assert [(item["method"], item["host"], item["path"], item["decision"])
            for item in record["observed"]] == [row[:4] for row in EXPECTED_REHEARSAL_1_0_92]
    assert bench92.cli("--require-rehearsed", "review")[0] == 0
    assert bench92.rehearsals[-1].proxy.request_budget == 0 and bench92.status()["charged"] == 0
    bench92.default = Scenario(requests=[*EXPECTED_REHEARSAL_1_0_92[:-1], ALLOWED])
    assert bench92.measure("review")[1]["routes"][0]["status"] == "measured"


_TABLE = list(EXPECTED_REHEARSAL_1_0_92)
_OTHER_GET = ("GET", gts.INFERENCE_HOST, "<other>", "deny")
#: What must fail a launch of grok 1.0.92 although the rest of the table is there. A request
#: the proxy is not told to name arrives folded (``<other>``); the verbatim spelling is here
#: too, so naming one later could not make it tolerated.
NEVER_TOLERATED_1_0_92 = {
    "settings": ("GET", gts.INFERENCE_HOST, "/v1/settings", "deny"),
    "models": ("GET", gts.INFERENCE_HOST, "/v1/models", "deny"),
    "other-path": _OTHER_GET,
    "other-post": ("POST", gts.INFERENCE_HOST, "<other>", "deny"),
    "updater-connect": UPDATER,
    "artifact-connect": ARTIFACTS,
    "other-host": ("CONNECT", "<other>", None, "deny"),
    "sign-in-host": ("CONNECT", "accounts.x.ai", None, "deny"),
    "other-host-and-path": ("GET", "<other>", "<other>", "deny"),
}


@pytest.mark.parametrize("name", list(NEVER_TOLERATED_1_0_92))
@pytest.mark.parametrize("where", ["before", "after"])
def test_a_rehearsal_of_1_0_92_fails_on_anything_outside_its_entries(bench92, name, where):
    """Erratum 8, items 2 and 7: with the rest of the table present, one request outside the
    image's entries fails the rehearsal, before or after the inference request. For the
    settings and model-list fetches that means the pinned seat config was not honoured."""
    extra = NEVER_TOLERATED_1_0_92[name]
    requests = [extra, *_TABLE] if where == "before" else [*_TABLE, extra]
    code, report = _rehearse(bench92, requests)
    assert (code, report["reason"]) == (1, "unlisted_request"), report
    assert report["budget_denials"] == 1 and sum(_tolerated_counts(report).values()) == 6
    assert bench92.measure("review")[1]["routes"][0]["code"] == "rehearsal_required"


@pytest.mark.parametrize("requests,reason", [
    (_TABLE[:-1], "no_model_request"),                      # the budget's own denial is required
    ([*_TABLE[:-1], INNER_HOST_DENIED], "unlisted_request"),  # refused, but not by the budget
    # Nothing may be allowed: a budget-0 proxy that counted one fails its own proof first.
    ([*_TABLE[:-1], ALLOWED], "observation_incomplete"),
    ([*_TABLE, RESPONSES], "unlisted_request"),              # a late POST: the ordering rule
    ([BUDGET_DENIED], "passed"),                             # a tolerated row may occur 0 times
    ([*_TABLE, BUDGET_DENIED, FEEDBACK], "passed"),          # client retries; a late GET
    ([ARCHIVE] * 3 + _TABLE, "passed"),                      # any number of a tolerated row
], ids=["no-budget-denial", "inner-host-denial", "an-allowed-request", "late-responses",
        "only-the-budget-denial", "retries-and-a-late-get", "repeats"])
def test_the_rehearsal_of_1_0_92_still_requires_the_budgets_own_denial(bench92, requests, reason):
    code, report = _rehearse(bench92, requests)
    assert report["reason"] == reason and (code == 0) is (reason == "passed"), report


@pytest.mark.parametrize("name", list(NEVER_TOLERATED_1_0_92))
@pytest.mark.parametrize("where", ["before", "after"])
def test_a_measurement_of_1_0_92_is_refused_on_anything_outside_its_entries(bench92, name, where):
    extra = NEVER_TOLERATED_1_0_92[name]
    pilot = [*_TABLE[:-1], ALLOWED]
    status, result = _pilot(bench92, [extra, *pilot] if where == "before" else [*pilot, extra])
    assert status == "egress_refused"
    assert result["tools"] is None and result["definitions_sha256"] is None  # never read
    assert sum(item["count"] for item in result["tolerated_refusals"]) == 6


def test_a_pilot_of_1_0_92_with_the_five_entries_before_its_counted_request_is_measured(bench92):
    status, result = _pilot(bench92, [*_TABLE[:-1], ALLOWED, FEEDBACK])
    assert status == "measured" and result["admitted"] is True
    assert result["observation"] == {"complete": True, "reason": "complete", "requests": 8,
                                     "counted": 1, "denied": 7}
    assert _tolerated_counts(result) == {
        ("GET", "/v1/bundle/archive"): 1, ("GET", "/"): 1, ("GET", "/v1/subagents/bundle"): 1,
        ("GET", "/v1/feedback/config"): 2, ("POST", "/v1/responses"): 2}
    assert bench92.status()["charged"] == 1  # the tolerated POSTs are never counted
    bench92.cli("--aggregate")
    evidence = json.loads((bench92.output / "tool-surface.json").read_text())
    gts.check_evidence_keys(evidence)
    assert evidence["routes"][0]["tolerated_refusals"] == result["tolerated_refusals"]
    # A second model call still disqualifies, tolerated entries or not.
    assert gts._classify(early=None, exit_code=0, identity_ok=True, binary_sha256=GROK_1_0_92,
                         proof=SimpleNamespace(complete=True, counted=1), events=[
        seat_egress_proxy.RequestEvent(method=m, host=h, path=p, decision=d, cause=c)
        for m, h, p, d, c in [(*RESPONSES, "rules"), (*ALLOWED, "allowed"), BUDGET_DENIED]
    ]) == "budget_exhausted"


@pytest.mark.parametrize("image,foreign", [
    (GROK_1_0_92, SETTINGS), (GROK_1_0_92, UPDATER), (GROK_1_0_92, ARTIFACTS),
    (GROK_1_0_89, ARCHIVE), (GROK_1_0_89, ROOT), (GROK_1_0_89, SUBAGENTS),
    (GROK_1_0_89, FEEDBACK), (GROK_1_0_89, RESPONSES),
    *[(None, entry) for entry in (SETTINGS, UPDATER, ARTIFACTS, ARCHIVE, ROOT, SUBAGENTS, FEEDBACK,
                                  RESPONSES)],
])
@pytest.mark.parametrize("stage", ["rehearsal", "measurement"])
def test_an_image_tolerates_only_its_own_entries(tmp_path, monkeypatch, image, foreign, stage):
    """A 1.0.92 grant does not tolerate erratum 3's three, a 1.0.89 grant does not tolerate
    erratum 8's five, and an image the map does not hold tolerates none of the eight."""
    bench = Bench(tmp_path, monkeypatch, image=image)
    if stage == "rehearsal":
        code, report = _rehearse(bench, [foreign, BUDGET_DENIED])
        assert (code, report["reason"], report["tolerated_refusals"]) == (1, "unlisted_request", [])
    else:
        status, result = _pilot(bench, [foreign, ALLOWED])
        assert status == "egress_refused" and result["tolerated_refusals"] == []


def test_a_record_holds_only_its_own_images_tolerated_entries(bench92):
    """The validators of the result, the aggregate and the rehearsal read the record's own
    image: an entry of another image's list, or any entry under an image the map does not
    hold, refuses the record."""
    foreign = {"method": "GET", "host": gts.INFERENCE_HOST, "path": "/v1/settings", "count": 1}
    status, result = _pilot(bench92, [ARCHIVE, RESPONSES, ALLOWED])
    assert status == "measured" and len(result["tolerated_refusals"]) == 2
    gts.check_result_keys(result)
    for change in ({"tolerated_refusals": [foreign]}, {"binary_sha256": "f" * 64},
                   {"binary_sha256": GROK_1_0_89}):
        with pytest.raises(gts._Refused):
            gts.check_result_keys({**result, **change})
    bench92.cli("--aggregate")
    evidence = json.loads((bench92.output / "tool-surface.json").read_text())
    gts.check_evidence_keys(evidence)
    for change in ({"routes": [{**evidence["routes"][0], "tolerated_refusals": [foreign]}]},
                   {"binary_sha256": "f" * 64}):
        with pytest.raises(gts._Refused):
            gts.check_evidence_keys({**evidence, **change})
    (record,) = [json.loads(p.read_text()) for p in
                 (bench92.grant_dir() / "rehearsals").glob("????-????????????????.json")]
    gts.check_rehearsal_keys(record)
    for change in ({"tolerated_refusals": [foreign]},
                   {"tolerated_refusals": result["tolerated_refusals"], "binary_sha256": "f" * 64}):
        with pytest.raises(gts._Refused):
            gts.check_rehearsal_keys({**record, **change})


def test_a_stored_record_with_another_images_entry_is_not_read_back(bench92):
    """On reload: a stored rehearsal that calls another image's entry tolerated is no
    rehearsal, so the pilot is refused; a stored result that does is unreadable, so nothing
    aggregates and the host-local record goes."""
    foreign = {"method": "GET", "host": gts.INFERENCE_HOST, "path": "/v1/settings", "count": 1}

    def rewrite(path, change):
        document = {**json.loads(path.read_text()), **change}
        path.unlink()
        path.write_text(json.dumps(document))
        path.chmod(0o600)

    status, _result = _pilot(bench92, [ARCHIVE, ALLOWED])
    assert status == "measured" and bench92.cli("--aggregate")[1]["published"] == ["review"]
    assert bench92.host_record() is not None
    (committed,) = (bench92.grant_dir() / "results").glob("*.json")
    rewrite(committed, {"tolerated_refusals": [foreign]})
    assert bench92.status()["unreadable_results"] == 1
    code, report = bench92.cli("--aggregate")
    assert (code, report["code"]) == (1, "ledger_unreadable") and bench92.host_record() is None
    (rehearsal,) = (bench92.grant_dir() / "rehearsals").glob("????-????????????????.json")
    assert bench92.cli("--require-rehearsed", "review")[0] == 0
    rewrite(rehearsal, {"tolerated_refusals": [foreign]})
    code, report = bench92.cli("--require-rehearsed", "review")
    assert (code, report["status"]) == (1, "interrupted")


# ------------------------------- erratum 8, review finding 3: no client path text retained

#: An all-letter word a client could put in a path segment: a slug, a customer name, a
#: prompt word. A templating proxy (lane E8-C) keeps such a segment verbatim in its event.
PLANTED_WORD = "zqxvplantedslugword"
PLANTED = [
    ("GET", gts.INFERENCE_HOST, f"/v1/{PLANTED_WORD}", "deny"),
    ("GET", gts.INFERENCE_HOST, f"/v1/users/<seg>/{PLANTED_WORD}", "deny"),
    ("POST", gts.INFERENCE_HOST, f"/{PLANTED_WORD}", "deny"),
    ("GET", f"{PLANTED_WORD}.example", "/", "deny"),
]


def test_the_diagnostic_paths_are_pinned_and_apart_from_the_tolerated_map():
    assert gts.DIAGNOSTIC_PATHS == ("/v1/settings", "/v1/models")
    for path in gts.DIAGNOSTIC_PATHS:  # named in a record, never tolerated for 1.0.92
        assert ("GET", gts.INFERENCE_HOST, path) not in gts.tolerated_refusals(GROK_1_0_92)
    _methods, hosts, paths = gts._retained_vocabulary()
    assert "/v1/models" in paths and "/v1/chat/completions" in paths and "<other>" in paths
    assert gts.INFERENCE_HOST in hosts and "x.ai" in hosts
    assert gts.retained_observation("GET", gts.INFERENCE_HOST, "/v1/models", "deny") == {
        "method": "GET", "host": gts.INFERENCE_HOST, "path": "/v1/models", "decision": "deny"}


@pytest.mark.parametrize("planted", PLANTED, ids=["segment", "templated", "post", "host"])
def test_a_client_chosen_path_word_reaches_no_rehearsal_record_or_output(bench92, planted):
    """A path or host spelling outside the closed vocabulary is retained as ``<other>``: the
    grant's rehearsal record, every file under the output, grant and host-record roots, and
    the CLI's report carry no trace of it. The launch still fails, as any unlisted request."""
    code, report = _rehearse(bench92, [*_TABLE[:-1], planted, BUDGET_DENIED])
    assert (code, report["reason"]) == (1, "unlisted_request"), report
    assert PLANTED_WORD not in json.dumps(report)
    (record,) = [json.loads(p.read_text()) for p in
                 (bench92.grant_dir() / "rehearsals").glob("????-????????????????.json")]
    retained = record["observed"][6]
    assert retained["method"] == planted[0] and "<other>" in (retained["host"], retained["path"])
    for root in (bench92.output, bench92.grant_dir(), pa.private_record_root()):
        for path in _files(root):
            assert PLANTED_WORD.encode() not in path.read_bytes(), path
    # The tabled rows are kept, verbatim.
    assert [tuple(item.values()) for item in record["observed"][:6]] == [
        ARCHIVE, ROOT, SUBAGENTS, FEEDBACK, RESPONSES, RESPONSES]


def test_a_measurement_retains_totals_and_tolerated_tuples_only(bench92):
    """The pilot writer keeps no path of its own: a planted word in a refused request
    reaches neither the result, the aggregate, the host record nor the report."""
    status, result = _pilot(bench92, [*_TABLE[:-1], PLANTED[0], ALLOWED])
    assert status == "egress_refused"
    bench92.cli("--aggregate")
    for root in (bench92.output, bench92.grant_dir(), pa.private_record_root()):
        for path in _files(root):
            assert PLANTED_WORD.encode() not in path.read_bytes(), path
    assert PLANTED_WORD not in json.dumps(bench92.status())


@pytest.mark.parametrize("field,value", [
    ("path", f"/v1/{PLANTED_WORD}"), ("host", f"{PLANTED_WORD}.example"),
    ("method", PLANTED_WORD.upper()), ("decision", "forwarded")])
def test_a_rehearsal_record_naming_text_outside_the_vocabulary_is_refused(bench92, field, value):
    """The reader holds the producer's bound: a stored rehearsal whose observation names a
    value outside the vocabulary is no rehearsal, so the pilot cannot reserve on it."""
    code, _report = _rehearse(bench92, _TABLE)
    assert code == 0
    (path,) = (bench92.grant_dir() / "rehearsals").glob("????-????????????????.json")
    record = json.loads(path.read_text())
    gts.check_rehearsal_keys(record)
    record["observed"][0][field] = value
    with pytest.raises(gts._Refused):
        gts.check_rehearsal_keys(record)
    path.unlink()
    path.write_text(json.dumps(record))
    path.chmod(0o600)
    code, report = bench92.cli("--require-rehearsed", "review")
    assert (code, report["status"]) == (1, "interrupted")


# ------------------------------------ erratum 8, item 5 (review finding 4): the client log

#: The collector guarantee this falsifier tests: no collector of the harness opens the
#: client's own log, ``~/.grok/logs/unified.jsonl``, which records the token's last 12
#: characters (``key_prefix``). It lives in the seat's tmpfs home. The retained paths that
#: do carry child-derived text are the provider log a failed measurement or rehearsal keeps,
#: the definitions artifact a measurement copies out of the host-backed sessions bind, and a
#: board leg's private log; each is exercised below through the real launcher. A seat process
#: that copied the suffix into its own output would put it there: that is redistribution
#: inside the seat, which no collector can tell apart and this test does not claim.
PLANTED_TOKEN = "fabricated-grok-bearer-e8b-" + "Qm7Rt2Vx9KpL"
TOKEN_SUFFIX = PLANTED_TOKEN[-12:]
assert TOKEN_SUFFIX == "Qm7Rt2Vx9KpL"

_LOGGING_STAND_IN = r'''#!/usr/bin/python3 -I
import base64, json, os, socket, ssl, sys, urllib.parse
argv = sys.argv[1:]
if argv[-1:] == ["--help"]:
    sys.stdout.write(__HELP__)
    sys.exit(0)
if argv[-1:] == ["--version"]:
    sys.stdout.write(__VERSION__)
    sys.exit(0)
if "--prompt-file" in argv:
    sys.stdin.read()
home = os.environ["HOME"]
# As grok 1.0.92 does: the projected token's last 12 characters, into its own log only.
with open(os.path.join(home, ".grok", "auth.json")) as handle:
    node = json.load(handle)
while isinstance(node, dict):
    node = node["key"] if "key" in node else next(iter(node.values()))
os.makedirs(os.path.join(home, ".grok", "logs"), exist_ok=True)
with open(os.path.join(home, ".grok", "logs", "unified.jsonl"), "a") as handle:
    for _ in range(5):
        handle.write(json.dumps({"event": "auth", "key_prefix": node[-12:]}) + "\n")
host = "cli-chat-proxy.grok.com"

def request(method, path):
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    raw = socket.create_connection((proxy.hostname, proxy.port), 10)
    auth = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
    raw.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = raw.recv(4096)
        if not chunk:
            break
        head += chunk
    context = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with context.wrap_socket(raw, server_hostname=host) as tls:
        tls.sendall(f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: 2\r\n"
                    "Connection: close\r\n\r\n{}".encode())
        reply = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            reply += chunk
    return reply.split(b"\r\n", 1)[0].decode("latin-1")

for method, path in __BEFORE__:
    try:
        request(method, path)
    except OSError:
        pass
try:
    proxied = request("POST", "/v1/chat/completions")
except OSError as exc:
    proxied = "error:" + type(exc).__name__
session = os.path.join(home, ".grok", "sessions", "-encoded-cwd", "session-0001")
os.makedirs(session)
with open(os.path.join(session, "tool_definitions.json"), "w") as handle:
    json.dump([{"type": "function", "function": {"name": name, "parameters": {}}}
               for name in __TOOLS__], handle)
# Child-derived text in the retained output, and a marker that the client log was written.
print("provider says:", proxied, "client log lines:", 5)
print("REVIEW TEXT FROM THE CHILD", file=sys.stderr)
sys.exit(__EXIT__)
'''


def _logging_stand_in(*, tools, exit_code=0, before=()):
    return (_LOGGING_STAND_IN.replace("__HELP__", repr(HELP)).replace("__VERSION__", repr(VERSION))
            .replace("__TOOLS__", repr(tools)).replace("__EXIT__", str(exit_code))
            .replace("__BEFORE__", repr(list(before))))


def _plant_token(home: Path) -> None:
    auth = home / ".grok" / "auth.json"
    auth.unlink()
    auth.write_text(json.dumps({"key": PLANTED_TOKEN}))
    auth.chmod(0o600)


def _carrying_the_suffix(*roots: Path) -> list[Path]:
    return [path for root in roots if root.exists() for path in _files(root)
            if TOKEN_SUFFIX.encode() in path.read_bytes()]


def _logging_bench(tmp_path, monkeypatch, *, image=GROK_1_0_89, **stand_in):
    _namespace_or_skip()
    _require_bwrap()
    bench = Bench(tmp_path, monkeypatch, real=True)
    _plant_token(Path(bench.env["HOME"]))
    bench.binary.write_text(_logging_stand_in(tools=_tools("review"), **stand_in))
    bench.binary.chmod(0o700)
    bench.stand_for(image)
    return bench


@pytest.mark.parametrize("case", ["measured", "launch_failed"])
def test_the_client_logs_token_suffix_reaches_no_retained_measurement_path(
        required_upstream, tmp_path, monkeypatch, case):
    """Erratum 8, item 5: a stand-in grok writes the planted token's 12-character suffix into
    ``$HOME/.grok/logs/unified.jsonl`` and nowhere else. Through the real launcher, a passing
    rehearsal, then a measurement that copies its definitions artifact out (``measured``) or
    one whose provider log is retained (``launch_failed``): no file under the state home --
    the output, raw and result copies, the aggregate evidence, the grant, the host-local
    record -- holds the suffix, and the sessions directory is gone."""
    bench = _logging_bench(tmp_path, monkeypatch, exit_code=0 if case == "measured" else 3)
    bench.open_grant(planned="review")
    try:
        code, report = bench.measure("review")
    except pi._sandbox_egress.SeatIdentityUnverified as exc:
        if os.environ.get(REQUIRE_NS) == "1":
            raise
        pytest.skip(f"this host cannot own a seat ({exc})")
    assert code == 0 and report["routes"][0]["status"] == case, report
    logs = list((bench.output / "raw").rglob("provider.log"))
    if case == "measured":
        assert bench.cli("--aggregate")[1]["published"] == ["review"]
        assert (bench.output / "tool-surface.json").is_file()
        copied = [p for p in _files(bench.output / "raw") if p.name.endswith(".json")]
        assert copied, "the definitions artifact was copied out"
        assert logs == []
    else:
        (log,) = logs  # retained on failure, with the child's own text in it
        text = log.read_text()
        assert "REVIEW TEXT FROM THE CHILD" in text and "client log lines: 5" in text
    assert _carrying_the_suffix(bench.state) == []
    assert not [p for p in bench.state.rglob("sessions") if p.is_dir()]
    assert not [p for p in bench.state.rglob("*") if p.name == "unified.jsonl"]


def test_the_client_logs_token_suffix_reaches_no_retained_rehearsal_path(
        required_upstream, tmp_path, monkeypatch):
    """The same for a failed rehearsal, whose provider log is retained: grok 1.0.92 fetching
    its remote settings disqualifies it (the pinned seat config was not honoured)."""
    bench = _logging_bench(tmp_path, monkeypatch, image=GROK_1_0_92, exit_code=1,
                           before=[("GET", "/v1/settings")])
    bench.open_grant(planned="review", rehearse=False)
    try:
        code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    except pi._sandbox_egress.SeatIdentityUnverified as exc:
        if os.environ.get(REQUIRE_NS) == "1":
            raise
        pytest.skip(f"this host cannot own a seat ({exc})")
    assert (code, report["reason"], report["budget_denials"]) == (1, "unlisted_request", 1), report
    (log,) = (bench.output / "raw").rglob("provider.log")
    assert "REVIEW TEXT FROM THE CHILD" in log.read_text()
    assert TOKEN_SUFFIX not in json.dumps(report)
    assert _carrying_the_suffix(bench.state) == []
    assert not [p for p in bench.state.rglob("sessions") if p.is_dir()]


@pytest.mark.parametrize("exit_code", [0, 3], ids=["completed", "failed"])
def test_the_client_logs_token_suffix_reaches_no_board_leg_output_or_private_log(
        required_upstream, live_seat_attempt, tmp_path, monkeypatch, exit_code):
    """A frozen-basis board leg through the real ``_exec_leg`` composition: its returned text,
    its output and review directories, and -- for a failed leg -- the private leg log the
    board writes from its raw output (``_leg_failure_detail``, ``_resolve_leg_detail``)."""
    from test_grok_board_leg_frozen_basis import (
        Board, _board_leg_egress, _exec_leg, _leg_command, _prerequisites, _skip_unless_owned,
    )
    _prerequisites()
    board = Board(tmp_path, monkeypatch)
    _plant_token(Path(board.env["HOME"]))
    board.binary.write_text(_logging_stand_in(tools=_tools("review"), exit_code=exit_code))
    board.binary.chmod(0o700)
    review_dir, out_dir = board.leg("review")
    board.publish(_leg_command("review", review_dir, out_dir))
    try:
        with _board_leg_egress():
            rc, text, log = _exec_leg(board, "review", review_dir, out_dir)
    except sandbox_egress.SeatIdentityUnverified as exc:
        _skip_unless_owned(exc)
    assert rc == exit_code and "client log lines: 5" in text + log, (rc, log[-800:])
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    detail = pi._resolve_leg_detail(
        pi._leg_failure_detail("OK" if rc == 0 else "FAILED", rc, text, log), run_dir, "grok")
    leg_logs = list((run_dir / pi._LEG_LOG_DIRNAME).glob("*.log"))
    assert bool(leg_logs) is (rc != 0), detail
    assert TOKEN_SUFFIX not in text + log + str(detail)
    assert _carrying_the_suffix(run_dir, review_dir, out_dir, tmp_path / "state") == []


def test_a_host_bind_at_the_client_log_refuses_at_the_context_check(bench, monkeypatch, tmp_path):
    """The home check takes no host path in the home but the measurement's sessions bind:
    ``.grok/logs`` bound from the host refuses a rehearsal and a measurement before any
    launch."""
    host_logs = tmp_path / "host-logs"
    host_logs.mkdir(mode=0o700)
    real = pi.seat_profile
    binding = {"on": False}

    @contextlib.contextmanager
    def seat_profile(**kwargs):
        with real(**kwargs) as (destination, profile):
            if binding["on"]:
                profile = replace(profile, mount_args=(
                    *profile.mount_args, "--bind", str(host_logs),
                    gts.PRIVATE_HOME + "/.grok/logs"))
            yield destination, profile
    monkeypatch.setattr(pi, "seat_profile", seat_profile)
    bench.open_grant(planned="review", rehearse=False)
    binding["on"] = True
    code, report = bench.cli("--attended", "--rehearse", "--route", "review")
    assert (code, report["status"], report["code"]) == (1, "refused", "context_refused"), report
    assert bench.rehearsals == []
    binding["on"] = False
    assert bench.cli("--attended", "--rehearse", "--route", "review")[0] == 0
    binding["on"] = True
    code, report = bench.measure("review")
    assert report["routes"][0]["status"] == "context_refused" and bench.launches == []
