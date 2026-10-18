"""The execution driver for non-local placement: the rest of the contract (agent-harness#896).

`tests/test_placement_ladder_model.py` tests the walk from its table. This file holds the
cases the table does not enumerate: what a backend may raise and how it is recorded, the
driver's own reachability attempt, the bound on every blocking call, everything after
`execute` (`run_placed`), the runtime receipts, qualification, and the settings.

The backend is a conformant in-process fake with a small far side: what it holds is tagged
by owner and lease, a kill fences the lease, and every call is recorded in order. Its
endpoint is a real loopback socket, open or closed, so the driver's connection attempt is
real. `place` and `run_placed` are driven directly; the launch site is not involved.
"""

from __future__ import annotations

import contextvars
from dataclasses import replace
from hashlib import sha256
import json
import logging
from pathlib import Path
import subprocess
import threading
import time

import pytest

from phase_loop_runtime import panel_invoker, placement_lease, review_stage, sandbox_policy
from phase_loop_runtime import sandbox_placement as sp
from test_placement_ladder_model import (
    BUDGET, CAPACITY, DIGEST, DRIVER, EXHAUSTED, NOT_ENROLLED, REFUSED, REQUIRED, TIMEOUT,
    UNCONFIRMED, UNREACHABLE, Endpoints, exec_spec, prepared_stage, summary,
)

CODE_INVALID = "sandbox_placement_code_invalid"
UNMET = "sandbox_placement_capability_unmet"
LOST = "sandbox_placement_lost_after_launch"
END_REACHED = "sandbox_placement_end_reached"
OWN_CODE = "drv_quota_exceeded"
_DEFAULT = object()


class FarSide:
    """A conformant backend. `behave[method]` replaces a method's default behaviour."""

    def __init__(self, name: str, endpoint: tuple[str, int] | None) -> None:
        self.name = name
        self.endpoint_value = endpoint
        self.calls: list[str] = []
        self.seen: dict[str, list[tuple]] = {}
        self.behave: dict[str, object] = {}
        self.capability_set = REQUIRED
        self.verify = REQUIRED
        self.max_lifetime_s: float | None = None
        self.held: dict[str, dict[str, object]] = {}
        self.fenced: set[str] = set()
        self.waits: list[object] = []
        self.spec: sp.ExecSpec | None = None
        self.digest = DIGEST

    def _call(self, method: str, *args: object) -> object:
        self.calls.append(method)
        self.seen.setdefault(method, []).append(args)
        hook = self.behave.get(method)
        return hook(*args) if hook is not None else _DEFAULT

    def capabilities(self):
        out = self._call("capabilities")
        return frozenset(self.capability_set) if out is _DEFAULT else out

    def declaration(self):
        out = self._call("declaration")
        return sp.Declaration(max_lifetime_s=self.max_lifetime_s) if out is _DEFAULT else out

    def available(self, request):
        out = self._call("available", request)
        return True if out is _DEFAULT else out

    def endpoint(self, root):
        out = self._call("endpoint", root)
        return self.endpoint_value if out is _DEFAULT else out

    def admit(self, request, bound):
        if self._call("admit", request, bound) is not _DEFAULT:
            return
        assert request.lease_id not in self.fenced, "an admission for a fenced lease"
        self.held[request.lease_id] = {"owner": request.owner_id, "ref": None}

    def commit(self, prepared, request, bound=None):
        out = self._call("commit", prepared, request, bound)
        if out is not _DEFAULT:
            return out
        ref = f"sbx-{request.lease_id[:12]}"
        self.held[request.lease_id]["ref"] = ref
        self.digest = prepared.snapshot_sha256
        receipt = sp.PlacementReceipt.from_backend(
            sp.BackendReceipt("committed", ref, prepared.snapshot_sha256))
        return sp.PlacedSandbox(
            backend=self.name, sandbox_ref=ref, staged_at=f"{self.name}:{ref}",
            receipts=(receipt,), verified={name: "backend_attested" for name in self.verify},
        )

    def execute(self, sandbox_ref, spec, bound):
        self.spec = spec
        out = self._call("execute", sandbox_ref, spec, bound)
        return sp.BackendReceipt("launched", sandbox_ref, self.digest) if out is _DEFAULT else out

    def result(self, sandbox_ref: str, **extra: object) -> sp.ExecResult:
        body = {"request_sha256": sha256(self.spec.request).hexdigest(), "verdict": "AGREE", **extra}
        return sp.ExecResult(sandbox_ref, 0, json.dumps(body).encode(), False)

    def wait(self, sandbox_ref, wait_s):
        out = self._call("wait", sandbox_ref, wait_s)
        if out is not _DEFAULT:
            return out
        if self.waits:
            item = self.waits.pop(0)
            return item(sandbox_ref, wait_s) if callable(item) else item
        return self.result(sandbox_ref)

    def cancel(self, sandbox_ref, bound):
        self._call("cancel", sandbox_ref, bound)

    def renew(self, sandbox_ref, until_s, bound):
        self._call("renew", sandbox_ref, until_s, bound)

    def kill(self, lease_id, bound):
        if self._call("kill", lease_id, bound) is not _DEFAULT:
            return
        self.fenced.add(lease_id)
        self.held.pop(lease_id, None)

    def list_owned(self, owner_id, bound):
        out = self._call("list_owned", owner_id, bound)
        if out is not _DEFAULT:
            return out
        return [
            (entry["ref"] or f"reserved-{lease_id[:8]}", lease_id)
            for lease_id, entry in self.held.items() if entry["owner"] == owner_id
        ]

    def release(self, prepared, bound=None):
        self._call("release", prepared, bound)


@pytest.fixture(scope="module")
def endpoints():
    built = Endpoints()
    try:
        yield built
    finally:
        built.close()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # No root from the environment, and none from the user's own configuration.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for name in ("REMOTE_REQUIRED", "LAST_RUNG", "ADMIT_WAIT_S", "TRANSFER_ALLOWANCE_S",
                 "PROBE_TIMEOUT_S", "ROOT"):
        monkeypatch.delenv(f"PHASE_LOOP_SANDBOX_{name}", raising=False)


@pytest.fixture
def far(endpoints):
    """One registered backend whose endpoint is the open loopback socket."""
    backend = FarSide("drv", ("127.0.0.1", endpoints.open_port))
    sp.register_backend("drv", backend, {OWN_CODE: "raise the quota on the far side"})
    try:
        yield backend
    finally:
        sp._REGISTRY.pop("drv", None)
        sp._BACKEND_CODES.pop("drv", None)


@pytest.fixture
def second(endpoints):
    backend = FarSide("drw", ("127.0.0.1", endpoints.open_port))
    sp.register_backend("drw", backend)
    try:
        yield backend
    finally:
        sp._REGISTRY.pop("drw", None)
        sp._BACKEND_CODES.pop("drw", None)


def rungs(*schemes: str):
    return sandbox_policy.candidate_roots(
        [(f"r{i + 1}", f"{scheme}://rung-{i + 1}.invalid:7/stage") for i, scheme in enumerate(schemes)])


def walk(roots, *, last_rung="local", workload="leg", deadline_s=None, required=REQUIRED,
         preflight=lambda: None, seal=None, driver_enabled=True, cancelled=None, prepared=None,
         open_lease=placement_lease.open_lease):
    prepared = prepared if prepared is not None else prepared_stage(Path("/nonexistent/stage"))

    def request_for(root):
        return sp.PlacementRequest(
            leg="codex", round_id="codex:a", repo="/repo",
            snapshot_sha256=prepared.snapshot_sha256, deadline_s=deadline_s,
            # The launching host's own list: the walk must send it empty (C5).
            egress_needs=sp.EgressNeeds.from_policy(), workload=workload,
            required_capabilities=required,
        )

    return sp.place(
        roots, last_rung, prepared, request_for, open_lease, preflight=preflight,
        seal=seal if seal is not None else exec_spec, driver_enabled=driver_enabled,
        cancelled=cancelled if cancelled is not None else threading.Event(),
    )


def lease_files() -> list[Path]:
    directory = placement_lease._lease_dir()
    return sorted(directory.iterdir()) if directory.is_dir() else []


def entry_of(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def raises(code: str, reason: str = ""):
    def hook(*_args):
        raise sp.PlacementUnavailable(code, reason)
    return hook


# --------------------------------------------------------------------------------------
# What `admit` may raise, and how it is recorded.
# --------------------------------------------------------------------------------------

def test_the_runtimes_capacity_code_is_capacity(far, monkeypatch):
    """One capacity code, the runtime's. With the wait spent the rung is left "capacity"
    and the launching host is barred."""
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "0")
    far.behave["admit"] = raises(CAPACITY)
    decision = walk(rungs("drv"))
    assert (decision.outcome, decision.code) == ("not_run", EXHAUSTED)
    assert summary(decision.trail) == [("r1", "capacity", CAPACITY)]
    assert "kill" not in far.calls and lease_files() == []


def test_a_registered_code_is_a_refusal_and_never_capacity(far):
    """Mutation: treat a registered code as capacity."""
    far.behave["admit"] = raises(OWN_CODE)
    decision = walk(rungs("drv"))
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "refused", OWN_CODE)]
    assert far.calls.count("admit") == 1 and "kill" not in far.calls
    assert lease_files() == []


@pytest.mark.parametrize("code", sorted(sp._BACKEND_REFUSALS))
def test_the_runtimes_refusal_codes_pass_through(far, code):
    far.behave["admit"] = raises(code)
    assert summary(walk(rungs("drv")).trail) == [("r1", "refused", code)]


@pytest.mark.parametrize("raised", [
    "drv_never_registered",
    "the host said no: /srv/stage is full",
    "/home/someone/.ssh/id_ed25519",
    "x" * 200,
    UNREACHABLE,                 # the runtime's, but not a backend's to raise
    EXHAUSTED,
], ids=["unregistered", "prose", "path", "200-chars", "unreachable", "exhausted"])
def test_an_unregistered_code_is_recorded_as_invalid_and_its_text_is_dropped(
    far, caplog, raised,
):
    """Mutation: record `str(exc.reason)`, or the raised code itself."""
    reason = "a reason with /a/private/path in it"
    far.behave["admit"] = raises(raised, reason)
    with caplog.at_level(logging.DEBUG):
        decision = walk(rungs("drv"), last_rung="none")
    assert (decision.outcome, decision.code) == ("not_run", CODE_INVALID)
    assert summary(decision.trail) == [("r1", "refused", CODE_INVALID)]
    rendered = repr(decision) + caplog.text
    assert reason not in rendered and "/a/private/path" not in rendered
    if raised not in sp.PLACEMENT_CODES:
        assert raised not in rendered
    assert lease_files() == [] and "kill" not in far.calls


def test_any_other_exception_from_admit_is_no_answer_and_is_released(far):
    """A lost answer is not a refusal: something may be held, so the lease is fenced and
    killed."""
    def lost(request, bound):
        raise ConnectionResetError("the answer was lost")

    far.behave["admit"] = lost
    decision = walk(rungs("drv"))
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "refused", REFUSED)]
    assert far.calls[-3:] == ["admit", "kill", "list_owned"]
    assert lease_files() == []


def test_backend_codes_are_validated_at_registration():
    backend = FarSide("drx", None)
    for codes in (
        {"Has Space": "fix"}, {"ab": "fix"}, {CAPACITY: "fix"}, {"drx_code": ""},
        {"drx_code": "two\nlines"}, {"drx_code": "f" * 201}, {"/etc/passwd": "fix"},
    ):
        with pytest.raises(ValueError):
            sp.register_backend("drx", backend, codes)
    assert "drx" not in sp._REGISTRY


def test_existing_call_forms_still_work(tmp_path):
    """`commit` with two arguments, `release` with one, `register_backend` with two, and a
    request in today's form. Mutation: make a new parameter required."""
    request = sp.PlacementRequest(
        leg="codex", round_id="codex", repo="/repo", snapshot_sha256=DIGEST, deadline_s=600.0,
        egress_needs=sp.EgressNeeds(),
    )
    assert (request.workload, request.required_capabilities, request.root) == ("leg", frozenset(), None)
    assert (request.owner_id, request.lease_id) == ("", "")
    prepared = prepared_stage(tmp_path)
    assert sp.LOCAL_BACKEND.commit(prepared, request) is None
    sp.LOCAL_BACKEND.release(prepared)
    backend = FarSide("dry", None)
    sp.register_backend("dry", backend)
    try:
        assert sp.backend_for_scheme("dry") is backend
    finally:
        sp._REGISTRY.pop("dry", None)
        sp._BACKEND_CODES.pop("dry", None)
    with pytest.raises(ValueError):
        sp.PlacementRequest(
            leg="codex", round_id="codex", repo="/repo", snapshot_sha256=DIGEST,
            deadline_s=None, egress_needs=sp.EgressNeeds(), workload="argv",
        )


# --------------------------------------------------------------------------------------
# Reachability is the driver's.
# --------------------------------------------------------------------------------------

@pytest.fixture
def connections(monkeypatch):
    attempts: list[tuple[str, int]] = []
    real = sp._open_connection

    def spy(host, port, timeout_s):
        attempts.append((host, port))
        return real(host, port, timeout_s)

    monkeypatch.setattr(sp, "_open_connection", spy)
    return attempts


def test_a_backend_with_no_endpoint_is_never_unreachable(far, connections):
    """Mutation: treat a missing endpoint as unreachable."""
    far.endpoint_value = None
    decision = walk(rungs("drv"))
    assert decision.outcome == "placed" and connections == []
    assert far.calls.index("admit") > far.calls.index("endpoint")


@pytest.mark.parametrize("kind", ["unresolvable-name", "closed-port"])
def test_unreachable_is_decided_by_the_drivers_own_attempt(far, endpoints, connections, monkeypatch, kind):
    """A name that does not resolve, and a name that resolves to a closed port. The backend
    only named the endpoint: it made no further call. Mutation: let the backend resolve."""
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_PROBE_TIMEOUT_S", "3")
    far.endpoint_value = (
        ("no-such-host.invalid", 9) if kind == "unresolvable-name"
        else ("localhost", endpoints.closed_port)
    )
    decision = walk(rungs("drv"))
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "unreachable", UNREACHABLE)]
    assert connections == [far.endpoint_value]
    assert far.calls == ["available", "endpoint", "capabilities", "declaration"]
    assert lease_files() == []


def test_the_endpoint_is_asked_without_network_and_recorded_beside_the_root(far, connections):
    decision = walk(rungs("drv"))
    assert decision.outcome == "placed"
    (root,), = far.seen["endpoint"]
    assert (root.name, root.scheme, root.host) == ("r1", "drv", "rung-1.invalid:7")
    assert connections == [far.endpoint_value]


# --------------------------------------------------------------------------------------
# The local checks of a rung.
# --------------------------------------------------------------------------------------

def test_a_required_capability_that_is_not_declared_fails_the_rung_locally(far):
    far.capability_set = REQUIRED - {"inbound_closed"}
    decision = walk(rungs("drv"))
    assert summary(decision.trail) == [("r1", "failed_locally", UNMET)]
    assert "admit" not in far.calls and lease_files() == []


def test_a_capability_not_verified_after_commit_is_released(far):
    far.verify = REQUIRED - {"private_ranges_unreachable"}
    decision = walk(rungs("drv"))
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "refused", UNMET)]
    assert far.calls[-3:] == ["commit", "kill", "list_owned"] and "execute" not in far.calls


def test_a_bare_receipt_from_commit_verifies_nothing(far):
    """`commit` may return its receipt alone. A leg's required capabilities are then not
    verified; a request that requires none is placed."""
    far.behave["commit"] = lambda prepared, request, bound: sp.BackendReceipt(
        "committed", "sbx-bare", prepared.snapshot_sha256)
    assert summary(walk(rungs("drv")).trail) == [("r1", "refused", UNMET)]
    far.capability_set = frozenset()
    decision = walk(rungs("drv"), required=frozenset())
    assert decision.outcome == "placed" and decision.placement.sandbox_ref == "sbx-bare"


@pytest.mark.parametrize("fault,code", [
    ("none", REFUSED), ("digest", REFUSED), ("bad-ref", "sandbox_placement_ref_invalid"),
    ("undeclared-claim", "sandbox_placement_capability_undeclared"), ("raises", REFUSED),
    ("own-code", OWN_CODE), ("unregistered", CODE_INVALID),
])
def test_a_commit_that_fails_is_released_with_its_code(far, fault, code):
    def commit(prepared, request, bound):
        if fault == "none":
            return None
        if fault == "digest":
            return sp.BackendReceipt("committed", "sbx-1", "0" * 64)
        if fault == "bad-ref":
            return sp.BackendReceipt("committed", "not a reference", prepared.snapshot_sha256)
        if fault == "undeclared-claim":
            receipt = sp.PlacementReceipt.from_backend(
                sp.BackendReceipt("committed", "sbx-1", prepared.snapshot_sha256))
            return sp.PlacedSandbox("drv", "sbx-1", "drv:sbx-1", (receipt,),
                                    {**{c: "backend_attested" for c in REQUIRED},
                                     "uid_isolated": "backend_attested"})
        if fault == "raises":
            raise OSError("the transfer broke")
        raise sp.PlacementUnavailable(OWN_CODE if fault == "own-code" else "drv_made_up")

    far.behave["commit"] = commit
    decision = walk(rungs("drv"))
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "refused", code)]
    assert far.calls[-3:] == ["commit", "kill", "list_owned"] and lease_files() == []


def test_a_deadline_beyond_the_backends_maximum_lifetime_fails_locally(far):
    far.max_lifetime_s = 600.0
    decision = walk(rungs("drv"), deadline_s=601.0)
    assert summary(decision.trail) == [("r1", "failed_locally", REFUSED)]
    assert "admit" not in far.calls
    assert walk(rungs("drv"), deadline_s=600.0).outcome == "placed"


@pytest.mark.parametrize("fault,code", [
    ("unregistered", "sandbox_placement_backend_unregistered"),
    ("plugin", "sandbox_placement_plugin_unavailable"),
    ("unavailable", REFUSED), ("endpoint-raises", REFUSED), ("endpoint-malformed", REFUSED),
    ("lease", REFUSED),
])
def test_the_other_local_checks(far, monkeypatch, fault, code):
    roots, options = rungs("drv"), {}
    if fault == "unregistered":
        roots = rungs("nobackend")
    elif fault == "plugin":
        roots = rungs("brokenplugin")
        monkeypatch.setattr(sp, "_load_plugins", raises("sandbox_placement_plugin_unavailable"))
    elif fault == "unavailable":
        far.behave["available"] = lambda request: False
    elif fault == "endpoint-raises":
        far.behave["endpoint"] = lambda root: 1 / 0
    elif fault == "endpoint-malformed":
        far.behave["endpoint"] = lambda root: ("host with space", 22)
    else:
        def unwritable(name, root):
            raise PermissionError("the lease directory is not writable")
        options["open_lease"] = unwritable
    decision = walk(roots, **options)
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "failed_locally", code)]
    assert not {"admit", "commit", "execute", "kill"} & set(far.calls)
    assert lease_files() == []


def test_the_seal_step_must_return_this_requests_spec_with_a_fixed_end(far):
    """A spec for another workload, or a deadline with no end, is a failed seal: released,
    never executed."""
    def other_workload(request):
        return sp.ExecSpec("qualification", b"x", None, None, 1024)

    def no_end(request):
        return sp.ExecSpec("leg", b"x", 600.0, None, 1024)

    def raising(request):
        raise RuntimeError("the credential could not be read")

    for seal in (other_workload, no_end, raising, lambda request: None):
        far.calls.clear()
        decision = walk(rungs("drv"), seal=seal, deadline_s=600.0 if seal is no_end else None)
        assert summary(decision.trail) == [("r1", "refused", REFUSED)]
        assert "execute" not in far.calls and far.calls[-2:] == ["kill", "list_owned"]


def test_execute_is_never_sent_for_a_fenced_lease(far):
    """The one sender of `execute` refuses a fenced lease. Mutation: remove the guard."""
    lease = placement_lease.open_lease("r1", rungs("drv")[0])
    placement = sp.LegPlacement(far, prepared_stage(Path("/x")), scheme="drv", authorization_sha256=None)
    spec = sp.ExecSpec("leg", b"sealed", None, None, 1024)
    lease.fence()
    with pytest.raises(RuntimeError):
        sp._send_execute(sp._Calls(), placement, spec, lease)
    assert far.calls == [] and placement._launched_at is None
    lease.clear()


# --------------------------------------------------------------------------------------
# What travels with the request.
# --------------------------------------------------------------------------------------

def test_owner_lease_and_root_travel_and_a_placed_seat_has_no_private_endpoint(far):
    decision = walk(rungs("drv"))
    (request, bound), = far.seen["admit"]
    assert request.owner_id == placement_lease.owner_id() and len(request.lease_id) == 32
    assert request.root is rungs("drv")[0] or request.root == rungs("drv")[0]
    assert request.egress_needs == sp.EgressNeeds() and request.egress_needs.allow == ()
    assert request.required_capabilities == REQUIRED and request.workload == "leg"
    assert isinstance(bound, sp.OperationBound) and 0 < bound.timeout_s <= sp.ANSWER_BOUND_S
    (available_request,), = far.seen["available"]
    assert available_request.egress_needs.allow == () and available_request.lease_id == ""
    assert far.seen["commit"][0][1] == request
    assert decision.placement._lease.lease_id == request.lease_id


def test_a_root_written_with_userinfo_and_a_query_carries_neither(far):
    """Mutation: pass the configured text."""
    roots = sandbox_policy.candidate_roots(
        [("r1", "drv://operator:s3cret@host.invalid:7/stage?token=qvalue#fragpart")])
    decision = walk(roots)
    assert decision.outcome == "placed"
    request = far.seen["admit"][0][0]
    rendered = repr(request) + repr(decision) + "".join(
        path.read_text(encoding="utf-8") for path in lease_files())
    for leak in ("s3cret", "operator", "token", "qvalue", "fragpart"):
        assert leak not in rendered
    assert (request.root.host, str(request.root.path)) == ("host.invalid:7", "/stage")
    assert entry_of(lease_files()[0])["root"] == "drv://host.invalid:7/stage"


def test_each_rung_that_is_asked_gets_its_own_lease(far, second):
    far.behave["admit"] = raises(NOT_ENROLLED)
    decision = walk(rungs("drv", "drw"))
    assert decision.outcome == "placed"
    first, last = far.seen["admit"][0][0], second.seen["admit"][0][0]
    assert first.lease_id != last.lease_id and first.owner_id == last.owner_id
    assert [path.name for path in lease_files()] == [f"{last.lease_id}.json"]


# --------------------------------------------------------------------------------------
# Every blocking call is bounded and interruptible (C4).
# --------------------------------------------------------------------------------------

def _never(release: threading.Event):
    def hook(*_args):
        release.wait(30)
        raise AssertionError("a call that never returns was waited for")
    return hook


@pytest.fixture
def hang():
    release = threading.Event()
    try:
        yield _never(release)
    finally:
        release.set()


@pytest.mark.parametrize("method,klass,code", [
    ("admit", "refused", TIMEOUT), ("commit", "refused", BUDGET),
    ("kill", "refused_unconfirmed", NOT_ENROLLED), ("list_owned", "refused_unconfirmed", NOT_ENROLLED),
])
def test_a_backend_call_that_never_returns_ends_within_its_bound(far, hang, monkeypatch, method, klass, code):
    """Mutation: wait without a timeout. A host that accepts a connection and then stops
    answering costs the answer bound, not the budget."""
    monkeypatch.setattr(sp, "ANSWER_BOUND_S", 0.3)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "1")
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", "1")
    far.behave[method] = hang
    if method in ("kill", "list_owned"):
        far.behave["commit"] = raises(NOT_ENROLLED)
    started = time.monotonic()
    decision = walk(rungs("drv"))
    assert time.monotonic() - started < 6.0
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", klass, code)]
    if klass == "refused_unconfirmed":
        (path,) = lease_files()
        assert entry_of(path)["abandoned"] is True


@pytest.mark.parametrize("method", ["admit", "commit", "kill", "list_owned"])
def test_a_cancel_during_a_hung_call_returns_within_the_bound(far, hang, monkeypatch, method):
    monkeypatch.setattr(sp, "ANSWER_BOUND_S", 0.5)
    far.behave[method] = hang
    if method in ("kill", "list_owned"):
        far.behave["commit"] = raises(NOT_ENROLLED)
    cancelled = threading.Event()
    timer = threading.Timer(0.2, cancelled.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(sp.PlacementCancelled) as caught:
            walk(rungs("drv"), cancelled=cancelled)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5.0
    record = dict(caught.value.trail[-1])
    assert record["class"] == "cancelled" and record["release_needed"] is True
    assert record["release_confirmed"] is (method in ("admit", "commit"))
    assert "execute" not in far.calls


def test_the_answer_bound_is_a_constant_far_below_the_budget():
    budget = sandbox_policy.admit_wait_s() + sandbox_policy.transfer_allowance_s()
    assert 0 < sp.ANSWER_BOUND_S <= sandbox_policy.transfer_allowance_s() / 2 < budget


# --------------------------------------------------------------------------------------
# The settings and the lifetime arithmetic.
# --------------------------------------------------------------------------------------

def test_lifetime_arithmetic(monkeypatch):
    """Mutation: omit the wait, or the allowance, from the sum."""
    floor = 1800.0
    assert (sandbox_policy.admit_wait_s(), sandbox_policy.transfer_allowance_s()) == (600, 300)
    assert sp.lifetime_sufficient(2700.0, floor) is True
    assert sp.lifetime_sufficient(2699.0, floor) is False
    assert sp.lifetime_at_floor(1800.0, floor) is True
    assert sp.lifetime_at_floor(1799.0, floor) is False
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "100")
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", "20")
    assert sp.lifetime_sufficient(1920.0, floor) and not sp.lifetime_sufficient(1919.0, floor)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", "0")
    assert sp.lifetime_sufficient(1900.0, floor) and not sp.lifetime_sufficient(1899.0, floor)
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "not a number")
    assert sandbox_policy.admit_wait_s() == 600
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "-5")
    assert sandbox_policy.admit_wait_s() == 0


def test_the_last_rung_setting(monkeypatch):
    assert sandbox_policy.last_rung() == "local"
    for value, want in (("local", "local"), ("none", "none"), (" NONE ", "none"), ("", "local")):
        monkeypatch.setenv("PHASE_LOOP_SANDBOX_LAST_RUNG", value)
        assert sandbox_policy.last_rung() == want
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_LAST_RUNG", "cloud")
    with pytest.raises(sandbox_policy.SandboxConfigError) as caught:
        sandbox_policy.last_rung()
    assert str(caught.value) == "sandbox_config_invalid"
    # The fail-closed knob forces `none`, whatever the setting says.
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", "1")
    assert sandbox_policy.last_rung() == "none"
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_LAST_RUNG", "local")
    assert sandbox_policy.last_rung() == "none"
    with pytest.raises(ValueError):
        walk((), last_rung="cloud")


def test_candidate_roots_are_the_url_roots_in_the_configured_order(monkeypatch):
    """A `host:path` root is never a rung: that form stays record-only. Nothing is looked
    up, called or probed."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("candidate_roots must not look a backend up or probe")

    monkeypatch.setattr(sp, "backend_for_scheme", forbidden)
    monkeypatch.setattr(sandbox_policy, "_probe_with_deadline", forbidden)
    configured = [
        ("first", "nobackend://one.invalid/stage"), ("legacy", "build-host:/srv/stage"),
        ("path", "/var/tmp/stage"), ("builtin", "local://x/y"), ("bad", "user:pw@host:/p"),
        ("second", "DRV://two.invalid:2222/stage"),
    ]
    found = sandbox_policy.candidate_roots(configured)
    assert [(root.name, root.scheme, root.host) for root in found] == [
        ("first", "nobackend", "one.invalid"), ("second", "drv", "two.invalid:2222")]
    assert all(root.fell_back is False for root in found)
    assert sandbox_policy.candidate_roots([(None, "build-host:/srv/stage")]) == ()
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", "drv://only.invalid/stage")
    assert [root.host for root in sandbox_policy.candidate_roots()] == ["only.invalid"]
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ROOT", "build-host:/srv/stage")
    assert sandbox_policy.candidate_roots() == ()


def test_with_no_rung_at_all_the_last_rung_is_resolved():
    assert walk(()).outcome == "launching_host"
    decision = walk((), last_rung="none")
    assert (decision.outcome, decision.code, decision.trail) == (
        "not_run", "sandbox_placement_required_unavailable", ())


def test_a_cancel_before_the_walk_records_the_rung_in_hand(far):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(sp.PlacementCancelled) as caught:
        walk(rungs("drv"), cancelled=cancelled)
    assert [dict(record) for record in caught.value.trail] == [{
        "rung": "r1", "class": "cancelled", "code": None,
        "release_needed": False, "release_confirmed": None,
    }]
    assert far.calls == []


# --------------------------------------------------------------------------------------
# The vocabulary.
# --------------------------------------------------------------------------------------

PLAN_CODES = (
    "sandbox_placement_required_unavailable", "sandbox_placement_driver_unavailable",
    "sandbox_placement_ref_invalid", "sandbox_placement_capability_undeclared",
    "sandbox_placement_plugin_unavailable", "sandbox_placement_backend_unregistered",
    "sandbox_placement_lost_after_launch", "sandbox_placement_end_reached",
    "sandbox_placement_capability_unmet", "sandbox_placement_capacity_exhausted",
    "sandbox_placement_unreachable", "sandbox_placement_not_enrolled",
    "sandbox_placement_identity_mismatch", "sandbox_placement_refused",
    "sandbox_placement_workload_unsupported", "sandbox_placement_operation_timeout",
    "sandbox_placement_code_invalid", "sandbox_placement_release_unconfirmed",
    "sandbox_placement_at_capacity", "sandbox_placement_budget_spent",
    "seat_placement_waiting",
)


def test_the_runtimes_code_list_is_the_plans():
    assert sp.PLACEMENT_CODES == frozenset(PLAN_CODES) and len(PLAN_CODES) == 21


def test_the_flag_is_still_off_and_the_launch_site_does_not_call_the_driver():
    """Acceptance 5. Nothing a user runs today reaches `place` or `run_placed`."""
    assert panel_invoker._NONLOCAL_EXECUTION_DRIVER is False
    source = Path(panel_invoker.__file__).read_text(encoding="utf-8")
    for name in ("placement_lease", ".place(", "run_placed", "candidate_roots", "last_rung("):
        assert name not in source, name


# --------------------------------------------------------------------------------------
# After `execute`: run_placed, the receipts, the release.
# --------------------------------------------------------------------------------------

def _placed(far, **options):
    decision = walk(rungs("drv"), **options)
    assert decision.outcome == "placed"
    return decision.placement


def _steps(placement, attested_by="runtime"):
    return [r.step for r in placement.receipts if r.attested_by == attested_by]


def _applied(placement):
    return sp.applied_rule(
        backend=placement.backend, host="rung-1.invalid:7", path=Path("/stage"),
        staged_at=placement.staged_at(), receipts=placement.receipts_for(0),
        authorization_sha256=placement.prepared.snapshot_sha256, local_spawns=0,
    )


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    run = lambda *argv: subprocess.run(["git", "-C", str(repo), *argv], check=True)  # noqa: E731
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    run("config", "user.email", "t@e.st")
    run("config", "user.name", "t")
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    run("add", "-A")
    run("-c", "commit.gpgsign=false", "commit", "-qm", "c")
    return repo


def test_place_then_run_placed_attests_one_sandbox_for_the_computed_digest(
    far, tmp_path, monkeypatch,
):
    """Acceptance 4, from the real gathering path: the stage is built by the runtime's own
    `prepare_local_stage` from a real repository, the journal's real `fsync` is ordered
    against `admit`, and the result is the fake's echo of the request the runtime sealed."""
    repo = _git_repo(tmp_path)
    review_dir = tmp_path / "scratch" / "review"
    review_dir.mkdir(parents=True)
    prepared = sp.prepare_local_stage(repo, review_dir, floor_bytes=0, mark=review_dir.parent)
    assert prepared.snapshot_sha256 == review_stage.review_tree_manifest_sha256(prepared.local_tree)

    order: list[str] = []
    real_fsync = placement_lease._fsync
    monkeypatch.setattr(placement_lease, "_fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    far.behave["admit"] = lambda request, bound: order.append("admit") or _DEFAULT
    progress: list[int] = []
    far.waits = [lambda ref, wait_s: sp.ExecProgress(ref, 1), lambda ref, wait_s: sp.ExecProgress(ref, 2)]

    decision = walk(rungs("drv"), prepared=prepared)
    placement = decision.placement
    # The entry and its directory were synced before the first call with a remote effect.
    assert order.index("admit") >= 3 and order[:order.index("admit")].count("fsync") >= 2
    assert _steps(placement) == ["prepared", "committed", "launched"]
    assert _applied(placement) == (False, "no runtime-attested commit and completion for this placement")

    result = sp.run_placed(placement, on_progress=lambda p: progress.append(p.seq),
                           cancelled=threading.Event())
    assert json.loads(result.result)["verdict"] == "AGREE" and progress == [1, 2]
    assert _steps(placement) == ["prepared", "committed", "launched", "completed"]
    runtime = {r.step: r for r in placement.receipts if r.attested_by == "runtime"}
    ref = far.seen["execute"][0][0]
    assert runtime["committed"].sandbox_ref == runtime["completed"].sandbox_ref == ref
    assert runtime["committed"].snapshot_sha256 == runtime["completed"].snapshot_sha256 == prepared.snapshot_sha256
    assert placement.staged_at() == f"drv:{ref}"
    assert _applied(placement) == (True, None)
    assert placement.verified == {name: "backend_attested" for name in REQUIRED}
    # Released with confirmation: killed by lease id, absent from the listing, entry cleared.
    assert far.calls[-2:] == ["kill", "list_owned"] and far.held == {}
    assert lease_files() == [] and placement.notices == []
    assert far.spec.request == b"sealed request" and far.spec.workload == "leg"
    sp.LOCAL_BACKEND.release(prepared)


def test_only_the_driver_attests_and_only_what_it_observed(far):
    placement = _placed(far)
    with pytest.raises(ValueError):
        placement.record_runtime("completed")       # not observed yet
    with pytest.raises(ValueError):
        placement.record_runtime("prepared")
    local = sp.LegPlacement(sp.LOCAL_BACKEND, placement.prepared, scheme="local", authorization_sha256=None)
    with pytest.raises(ValueError):
        local.record_runtime("committed")
    assert placement.record_runtime("launched") is placement.record_runtime("launched")
    assert _steps(placement).count("launched") == 1
    sp.run_placed(placement, on_progress=None, cancelled=threading.Event())


@pytest.mark.parametrize("fault", ["no-echo", "other-sandbox", "wait-raises", "connection-lost", "junk"])
def test_a_leg_lost_after_launch_is_never_tried_anywhere_else(far, second, fault):
    """No `completed` receipt, `sandbox_placement_lost_after_launch`, and no call on any
    other rung. Mutation: try the next rung after a post-launch failure."""
    placement = walk(rungs("drv", "drw")).placement

    def wait(ref, wait_s):
        if fault == "no-echo":
            return sp.ExecResult(ref, 0, json.dumps({"request_sha256": "0" * 64}).encode(), False)
        if fault == "other-sandbox":
            return far.result("sbx-someone-else")
        if fault == "wait-raises":
            raise RuntimeError("the worker crashed")
        if fault == "connection-lost":
            raise ConnectionResetError("connection lost")
        return "neither a result nor progress"

    far.waits = [wait]
    with pytest.raises(sp.PlacementUnavailable) as caught:
        sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert caught.value.code == LOST
    assert "completed" not in _steps(placement) and _applied(placement)[0] is False
    assert second.calls == []
    assert far.calls[-3:] == ["cancel", "kill", "list_owned"] and lease_files() == []


def test_an_execute_that_raised_is_still_a_launch(far, second):
    far.behave["execute"] = raises(TIMEOUT)
    decision = walk(rungs("drv", "drw"))
    assert decision.outcome == "placed" and second.calls == []
    assert _steps(decision.placement) == ["prepared", "committed", "launched"]
    with pytest.raises(sp.PlacementUnavailable) as caught:
        sp.run_placed(decision.placement, on_progress=None, cancelled=threading.Event())
    assert caught.value.code == LOST and "wait" not in far.calls and second.calls == []


class _Clock:
    def __init__(self, monkeypatch) -> None:
        self.now = 5000.0
        monkeypatch.setattr(sp, "_monotonic", lambda: self.now)


def test_the_fixed_end_is_enforced_whatever_progress_and_renewals_arrive(far, monkeypatch):
    """`must_end_within_s` is reached while the fake keeps reporting progress, and renewals
    keep arriving: the driver cancels, the leg ends `sandbox_placement_end_reached`, and
    no renewal moved the end. Mutation: extend on renewal."""
    clock = _Clock(monkeypatch)
    far.max_lifetime_s = 0.03          # a renewal every hundredth of a second, in real time
    asked: list[float] = []

    def seal(request):
        return sp.ExecSpec("leg", b"sealed", None, 100.0, 1024)

    def wait(ref, wait_s):
        asked.append(wait_s)
        assert clock.now < 6000.0, "the end moved"
        if len(asked) == 3:
            time.sleep(0.15)           # let renewals arrive just before the end
        clock.now += wait_s
        return sp.ExecProgress(ref, len(asked))

    far.behave["wait"] = wait
    placement = _placed(far, seal=seal)
    with pytest.raises(sp.PlacementUnavailable) as caught:
        sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert caught.value.code == END_REACHED
    assert sum(asked) == 100.0 and asked[-1] == 10.0
    assert far.calls.count("renew") >= 1
    assert far.calls.index("renew") < far.calls.index("cancel")
    assert [call for call in far.calls if call != "renew"][-3:] == ["cancel", "kill", "list_owned"]
    assert all(args[1] == 0.03 for args in far.seen["renew"])
    assert "completed" not in _steps(placement) and lease_files() == []


def test_a_no_deadline_leg_is_admitted_and_renewed_while_the_lock_is_held(far):
    """A backend's maximum lifetime is a liveness bound for a leg with no deadline, not a
    refusal. Mutation: refuse when `deadline_s is None`. The renewals stop with the leg."""
    far.max_lifetime_s = 0.06
    placement = _placed(far, deadline_s=None)
    assert placement._lease.held

    def slow(ref, wait_s):
        time.sleep(0.2)
        return sp.ExecProgress(ref, 1)

    far.waits = [slow]
    sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    renewals = far.calls.count("renew")
    assert renewals >= 2 and not placement._lease.held
    time.sleep(0.15)
    assert far.calls.count("renew") == renewals


def test_a_leg_with_a_deadline_is_not_renewed(far):
    """With a deadline the backend keeps the sandbox for the deadline; nothing is renewed.
    The leg outlasts a renewal interval (a third of the maximum lifetime) and finishes
    before its end."""
    far.max_lifetime_s = 0.6
    placement = _placed(far, deadline_s=0.6)

    def slow(ref, wait_s):
        time.sleep(0.3)
        return far.result(ref)

    far.waits = [slow]
    sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert "renew" not in far.calls


def test_a_renewal_that_never_returns_does_not_block_the_leg(far, hang, monkeypatch):
    """The heartbeat gives up within its bound. Mutation: call `renew` without a bound."""
    monkeypatch.setattr(sp, "ANSWER_BOUND_S", 0.2)
    far.max_lifetime_s = 0.03
    far.behave["renew"] = hang

    def slow(ref, wait_s):
        time.sleep(0.1)
        return far.result(ref)

    far.waits = [slow]
    placement = _placed(far)
    started = time.monotonic()
    result = sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert time.monotonic() - started < 3.0 and result.exit_status == 0
    assert far.calls.count("renew") == 1
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and any(
        thread.name == "placement-renew" and thread.is_alive() for thread in threading.enumerate()
    ):
        time.sleep(0.02)
    assert not [t for t in threading.enumerate() if t.name == "placement-renew" and t.is_alive()]


@pytest.mark.parametrize("with_result", [True, False])
def test_an_unconfirmed_release_after_launch_keeps_a_finished_review(far, with_result):
    """Result received, then the kill is not confirmed: the result is KEPT, the placement
    carries the notice and the lease entry stays for the reaper. Without a result the leg
    is lost. Mutation: discard the result."""
    placement = _placed(far)
    far.behave["kill"] = raises(TIMEOUT)
    if not with_result:
        far.waits = [lambda ref, wait_s: 1 / 0]
    if with_result:
        result = sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
        assert json.loads(result.result)["verdict"] == "AGREE"
        assert "completed" in _steps(placement) and _applied(placement) == (True, None)
    else:
        with pytest.raises(sp.PlacementUnavailable) as caught:
            sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
        assert caught.value.code == LOST
    assert placement.notices == [UNCONFIRMED]
    (path,) = lease_files()
    entry = entry_of(path)
    assert entry["abandoned"] is True and entry["sandbox_ref"] == placement.sandbox_ref
    assert not placement._lease.held and placement._lease.fenced
    assert "execute" not in far.calls[far.calls.index("execute") + 1:]


def test_a_kill_that_is_acknowledged_but_still_listed_is_not_a_release(far):
    placement = _placed(far)
    far.behave["kill"] = lambda lease_id, bound: None       # acknowledged, removes nothing
    sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert placement.notices == [UNCONFIRMED]
    entry = entry_of(lease_files()[0])
    assert entry["abandoned"] is True and entry["confirmed_killed_at"] is not None


def test_a_cancel_after_launch_cancels_releases_and_raises_with_the_trail(far):
    placement = _placed(far)
    cancelled = threading.Event()

    def wait(ref, wait_s):
        cancelled.set()
        return sp.ExecProgress(ref, 1)

    far.waits = [wait]
    with pytest.raises(sp.PlacementCancelled) as caught:
        sp.run_placed(placement, on_progress=None, cancelled=cancelled)
    assert str(caught.value) == "review_operation_cancelled"
    assert summary(caught.value.trail) == [("r1", "placed", None)]
    assert far.calls[-3:] == ["cancel", "kill", "list_owned"] and lease_files() == []
    assert panel_invoker._exception_failure(caught.value) == "review_operation_cancelled"


def test_a_wait_that_never_returns_is_a_lost_leg_within_its_bound(far, hang, monkeypatch):
    monkeypatch.setattr(sp, "ANSWER_BOUND_S", 0.2)
    monkeypatch.setattr(sp, "_WAIT_SLICE_S", 0.2)
    placement = _placed(far)
    far.behave["wait"] = hang
    started = time.monotonic()
    with pytest.raises(sp.PlacementUnavailable) as caught:
        sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert caught.value.code == LOST and time.monotonic() - started < 5.0


def test_run_placed_takes_only_a_launched_placement(far):
    never = sp.LegPlacement(far, prepared_stage(Path("/x")), scheme="drv", authorization_sha256=None)
    with pytest.raises(ValueError):
        sp.run_placed(never, on_progress=None, cancelled=threading.Event())


# --------------------------------------------------------------------------------------
# Qualification is exempt from the gate, and never counts as applied (C10).
# --------------------------------------------------------------------------------------

def test_a_qualification_request_is_driven_while_the_flag_is_false(far):
    """Its receipts are marked and `applied_rule` is false for them. Mutation: count them
    as applied. A `leg` on the same rung, same flag, is refused before the backend is
    touched."""
    placement = _placed(far, workload="qualification", driver_enabled=False)
    result = sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert result.exit_status == 0 and far.spec.workload == "qualification"
    assert far.seen["admit"][0][0].workload == "qualification"
    runtime = [r for r in placement.receipts if r.attested_by == "runtime" and r.step != "prepared"]
    assert [r.step for r in runtime] == ["committed", "launched", "completed"]
    assert all(r.workload == "qualification" and r.to_dict()["workload"] == "qualification"
               for r in runtime)
    assert _applied(placement) == (False, "a qualification workload is never an applied placement")

    far.calls.clear()
    decision = walk(rungs("drv"), workload="leg", driver_enabled=False)
    assert summary(decision.trail) == [("r1", "failed_locally", DRIVER)] and far.calls == []


def test_a_leg_receipt_keeps_todays_record_shape():
    receipt = sp._runtime_receipt("committed", "sbx-1", DIGEST)
    assert receipt.to_dict() == {
        "step": "committed", "sandbox_ref": "sbx-1", "snapshot_sha256": DIGEST,
        "attested_by": "runtime",
    }


# --------------------------------------------------------------------------------------
# agent-harness#1492 board round 1: the president's findings, as named tests.
# --------------------------------------------------------------------------------------

def test_a_capacity_answer_from_commit_never_sends_the_seat_to_the_launching_host(far):
    """codex F006. A capacity code raised by `commit` sets the capacity bar (C7: the first
    capacity answer on any rung), so the seat is not run rather than run on this machine;
    the slot is released as a failed transfer. Mutation: the bar is not set on a
    commit-time capacity code."""
    far.behave["commit"] = raises(CAPACITY)
    decision = walk(rungs("drv"), last_rung="local")
    assert (decision.outcome, decision.code) == ("not_run", EXHAUSTED)
    assert summary(decision.trail) == [("r1", "refused", CAPACITY)]
    assert far.calls[-3:] == ["commit", "kill", "list_owned"] and "execute" not in far.calls
    assert decision.notices == () and lease_files() == []


def test_the_fixed_end_interrupts_a_wait_in_flight(far):
    """codex F007. The call in flight is bounded by the time left to the end, so a `wait`
    that blocks past it is cancelled at the end and the leg ends
    `sandbox_placement_end_reached`, not lost. Mutation: bound the call by the wait slice
    plus the answer bound."""
    release_wait, wait_entered, cancel_seen = threading.Event(), threading.Event(), threading.Event()
    failures: list[str] = []

    def wait(ref, wait_s):
        wait_entered.set()
        release_wait.wait(5)
        return sp.ExecProgress(ref, 1)

    def seal(request):
        return sp.ExecSpec("leg", b"sealed", None, 0.1, 1024)

    placement = walk(rungs("drv"), seal=seal).placement

    def run():
        try:
            sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
        except sp.PlacementUnavailable as exc:
            failures.append(exc.code)

    far.behave["wait"] = wait
    far.behave["cancel"] = lambda *args: cancel_seen.set()
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert wait_entered.wait(1)
        ended_in_time = cancel_seen.wait(0.5)
    finally:
        release_wait.set()
        worker.join(2)
    assert ended_in_time, "the fixed end passed while the driver stayed inside wait"
    assert failures == [END_REACHED]


def test_execute_receives_the_callers_cancel_in_its_bound(far):
    """codex F009 (C4). The backend's bound carries the walk's cancel; the driver still
    waits for the answer, so the attempt is placed and launch stays final. Mutation: pass
    `execute` a fresh event."""
    cancelled = threading.Event()
    observed: list[bool] = []

    def execute(ref, spec, bound):
        cancelled.set()
        observed.append(bound.cancelled.is_set())
        return sp.BackendReceipt("launched", ref, far.digest)

    far.behave["execute"] = execute
    decision = walk(rungs("drv"), cancelled=cancelled)
    assert decision.outcome == "placed" and observed == [True]
    with pytest.raises(sp.PlacementCancelled):
        sp.run_placed(decision.placement, on_progress=None, cancelled=cancelled)


@pytest.mark.parametrize("returned", ["private-digest", "other-sandbox", "other-digest", "other-step"])
def test_an_execute_receipt_that_is_not_this_sandboxes_is_dropped(far, returned):
    """codex F008 and claude N2. `execute`'s receipt is recorded only when it says
    `launched` for this sandbox and the runtime's digest; anything else is dropped without
    failing the launch, so no backend text reaches a receipt and `applied_rule` is not
    poisoned. Mutation: record the receipt unchecked."""
    private_text = "/home/operator/.credentials?token=synthetic-secret"

    def execute(ref, spec, bound):
        if returned == "private-digest":
            return sp.BackendReceipt("launched", ref, private_text)
        if returned == "other-sandbox":
            return sp.BackendReceipt("launched", "sbx-someone-else", far.digest)
        if returned == "other-digest":
            return sp.BackendReceipt("launched", ref, "e" * 64)
        return sp.BackendReceipt("completed", ref, far.digest)

    far.behave["execute"] = execute
    placement = _placed(far)
    exported = json.dumps([receipt.to_dict() for receipt in placement.receipts])
    assert private_text not in exported and "sbx-someone-else" not in exported
    assert _steps(placement, "backend") == ["committed"]
    sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert _applied(placement) == (True, None)


def test_a_matching_execute_receipt_is_recorded(far):
    placement = _placed(far)
    assert _steps(placement, "backend") == ["committed", "launched"]
    sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
    assert _applied(placement) == (True, None)


def test_a_backend_time_out_before_the_fixed_end_is_a_lost_leg(monkeypatch):
    """codex F001 (board round 2). Whether the end was reached is read from the clock when
    the time-out is handled, not from the planned bound: a backend that raises the time-out
    code at once, with ten seconds left, has lost the leg; it has not reached the end.
    Mutation: decide from the planned call bound."""
    from types import SimpleNamespace

    monkeypatch.setattr(sp, "_monotonic", lambda: 0.0)
    calls = []

    def wait(sandbox_ref, wait_s):
        assert wait_s == 10.0
        raise sp.PlacementUnavailable("sandbox_placement_operation_timeout")

    backend = SimpleNamespace(
        wait=wait,
        cancel=lambda *args: calls.append("cancel"),
        kill=lambda *args: calls.append("kill"),
        list_owned=lambda *args: (),
    )
    lease = SimpleNamespace(
        lease_id="a" * 32, owner_id="b" * 32,
        fence=lambda: calls.append("fence"),
        note_killed=lambda: None,
        clear=lambda: calls.append("clear"),
        abandon=lambda: calls.append("abandon"),
    )
    placement = SimpleNamespace(
        backend=backend, sandbox_ref="sbx-early-timeout",
        _spec=sp.ExecSpec("leg", b"sealed", 10.0, 10.0, 1024),
        _lease=lease, _launched_at=0.0, _launch_failed=False,
        _trail=(), notices=[],
    )

    with pytest.raises(sp.PlacementUnavailable) as caught:
        sp.run_placed(placement, on_progress=None, cancelled=threading.Event())

    assert calls == ["cancel", "fence", "kill", "clear"]
    assert caught.value.code == "sandbox_placement_lost_after_launch"


@pytest.mark.parametrize("cancel", [False, True])
def test_seal_is_bounded_and_late_spec_is_discarded(far, monkeypatch, cancel):
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "0")
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", "1")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    cancelled = threading.Event()
    outcomes = []

    def seal(request):
        entered.set()
        release.wait(5)
        return exec_spec(request)

    def run():
        try:
            outcomes.append(walk(rungs("drv"), seal=seal, cancelled=cancelled))
        except sp.PlacementCancelled as exc:
            outcomes.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(2)
        if cancel:
            cancelled.set()
        assert finished.wait(2)
        assert "execute" not in far.calls
        assert "kill" in far.calls and lease_files() == []
        if cancel:
            assert isinstance(outcomes[0], sp.PlacementCancelled)
        else:
            assert summary(outcomes[0].trail) == [("r1", "refused", BUDGET)]
    finally:
        release.set()
        thread.join(3)
    assert "execute" not in far.calls


def test_each_call_captures_its_own_context():
    value = contextvars.ContextVar("submission", default="missing")
    calls = sp._Calls()
    threads = []
    try:
        for expected in ("first", "second"):
            token = value.set(expected)
            try:
                def job():
                    threads.append(threading.get_ident())
                    got = value.get()
                    value.set("worker mutation")
                    return got
                assert calls.run(job, 1) == expected
                assert value.get() == expected
            finally:
                value.reset(token)
        assert threads[0] == threads[1]
    finally:
        calls.close()


@pytest.mark.parametrize("remaining", [0, 0.25, 40])
def test_seal_uses_whole_budget_and_execute_only_the_remainder(far, monkeypatch, remaining):
    clock = [0.0]
    monkeypatch.setattr(sp, "_monotonic", lambda: clock[0])
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", "60")
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", "60")
    bounds = []
    run = sp._Calls.run

    def record(self, call, timeout_s, cancelled=None):
        bounds.append(timeout_s)
        return run(self, call, timeout_s, cancelled)

    monkeypatch.setattr(sp._Calls, "run", record)

    def seal(request):
        assert bounds[-1] == 120
        clock[0] = 120 - remaining
        return exec_spec(request)

    decision = walk(rungs("drv"), seal=seal)
    if remaining == 0:
        assert decision.outcome == "launching_host" and "execute" not in far.calls
    else:
        assert decision.outcome == "placed"
        assert far.seen["execute"][0][2].timeout_s == min(sp.ANSWER_BOUND_S, remaining)
        sp.run_placed(decision.placement, on_progress=None, cancelled=threading.Event())


@pytest.mark.parametrize("cap", [True, False, -1, 1.5, "1024", None])
def test_invalid_output_cap_refuses_before_dispatch(far, cap):
    decision = walk(rungs("drv"), seal=lambda request: replace(exec_spec(request), output_cap_bytes=cap))
    assert decision.outcome == "launching_host"
    assert "execute" not in far.calls and lease_files() == []


@pytest.mark.parametrize("kind", ["exact", "over", "text", "bytearray", "zero"])
def test_result_cap_precedes_digest_parsing(far, monkeypatch, kind):
    body = json.dumps({"request_sha256": sha256(b"sealed request").hexdigest()}).encode()
    cap = len(body) if kind == "exact" else len(body) - 1
    if kind == "zero":
        cap = 0
    payload = body.decode() if kind == "text" else bytearray(body) if kind == "bytearray" else body
    placement = _placed(far, seal=lambda request: replace(exec_spec(request), output_cap_bytes=cap))
    far.behave["wait"] = lambda ref, wait: sp.ExecResult(ref, 0, payload, False)
    parsed = []
    echoes = sp._echoes
    monkeypatch.setattr(sp, "_echoes", lambda *args: parsed.append(args) or echoes(*args))
    if kind == "exact":
        assert sp.run_placed(placement, on_progress=None, cancelled=threading.Event()).result == body
        assert len(parsed) == 1
    else:
        with pytest.raises(sp.PlacementUnavailable, match=LOST):
            sp.run_placed(placement, on_progress=None, cancelled=threading.Event())
        assert parsed == []
        assert "completed" not in placement._observed
    assert lease_files() == []
