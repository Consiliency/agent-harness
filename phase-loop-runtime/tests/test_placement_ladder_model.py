"""The placement ladder, tested from its table (agent-harness#896, amendment C7).

C7 of ``plans/detailed-remote-seat-placement-896-20261010.md`` specifies the walk as two
tables. This file keeps a LITERAL copy of them, so the product's ``LADDER_TABLE`` is never
its own oracle:

* the copy is compared with ``LADDER_TABLE`` and with the contract text;
* an interpreter of the copy (``_Model``) enumerates every event ordering the tables allow
  for one, two and three remote rungs and both values of the last rung, the waiting loop
  bounded by ``CAPACITY_ANSWERS_PER_RUNG``;
* for each ordering the fakes, the loopback endpoints and a fake clock are scripted so that
  exactly those events happen, the real ``place`` is driven, and what it did (outcome,
  trail, backend calls, lease journal) is compared with what the interpreter says;
* the properties the rulings require are asserted on every ordering, from the observed
  calls and the scripted truth, not from the interpreter's own bookkeeping.

The clock can pass the budget inside any call, a release and the local checks included.

**What is real.** Every ordering drives the real ``place``. For one and two rungs (9,356
orderings) everything under it is real too: the worker thread that bounds each backend
call, a loopback connection attempt to a socket that is open or closed, and the lease
journal on disk. Driven that way the 219,424 three-rung orderings take about eleven minutes
per Python version, so they run with three primitives in memory -- calls inline, the
connection attempt answered by the script, and a lease object with the journal's interface
passed through ``place``'s own ``open_lease`` parameter -- and every
``REAL_IO_STRIDE``-th of them runs with everything real as well. Nothing is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest

from phase_loop_runtime import placement_lease, sandbox_policy
from phase_loop_runtime import sandbox_placement as sp

# --------------------------------------------------------------------------------------
# The literal copy. Pasted from the plan; edited only by a change to the plan.
# --------------------------------------------------------------------------------------

C7_STATES = """\
| State | Event | Next | What it means |
|---|---|---|---|
| start | a local check fails: no backend is registered for the root's scheme or its plugin does not load, `available()` is false, `endpoint` raises, a required capability is not declared, the deadline exceeds the backend's maximum lifetime, a `leg` workload while the driver flag is false | left: **failed locally** | Nothing was sent |
| start | the local checks pass | connecting | |
| connecting | the driver's own resolution or connection fails | left: **unreachable** | Nothing was sent |
| connecting | connected, but the lease entry cannot be written | left: **failed locally** | Nothing was sent |
| connecting | budget spent | left: **out of time** | Nothing was sent. Running out of time is not evidence that the host is unreachable |
| connecting | connected, lease entry fsynced | admitting | The admission request is sent |
| admitting | admitted | committing | A slot is held on the far side |
| admitting | the backend raises the runtime's capacity code | waiting | **The capacity bar is set for the attempt.** The far end's answer means it holds nothing. |
| admitting | any other code except the time-out code | left: **refused** | The far end's own refusal means it holds nothing; the lease entry is cleared |
| admitting | no answer: the time-out code (`sandbox_placement_operation_timeout`), a lost answer, or any exception that is not a refusal | releasing | Something may be held |
| admitting | budget spent | releasing | The request is abandoned in flight; something may be held |
| waiting | back-off elapsed, while the wait is not spent | admitting | The admission request is sent again |
| waiting | wait spent (now, or already on an earlier rung, in which case at once), or budget spent | left: **capacity** | The lease entry is cleared |
| committing | committed, digest equal, required capabilities verified | sealing | |
| committing | the transfer fails or times out, a capability is not verified, or budget spent | releasing | |
| sealing | the caller's seal step returns the request (its guard passed) | **`execute` is called** | Final: the attempt is **placed** |
| sealing | the guard fails, or sealing raises | releasing | |
| sealing | budget spent before the seal step returns | releasing | `execute` is not called |
| releasing | the kill by lease id is acknowledged and `list_owned` shows nothing for it | left: **refused** | The lease entry is cleared |
| releasing | the kill or the confirmation times out or fails | left: **refused, unconfirmed** | `sandbox_placement_release_unconfirmed` is recorded; **the lease entry is kept for the reaper; the lease stays fenced** (C6) |
"""

C7_CODES = """\
| Class | Code in the trail |
|---|---|
| failed locally | `sandbox_placement_driver_unavailable` (flag off); `sandbox_placement_capability_unmet` (a required capability not declared); `sandbox_placement_backend_unregistered`, `sandbox_placement_plugin_unavailable` or `sandbox_placement_refused` for the other local checks, as the seam raises them today |
| unreachable | `sandbox_placement_unreachable` |
| out of time | `sandbox_placement_budget_spent` |
| capacity | `sandbox_placement_at_capacity` |
| refused | The code the backend raised, if it is one of the runtime's (`sandbox_placement_not_enrolled`, `sandbox_placement_identity_mismatch`, `sandbox_placement_workload_unsupported`) or one it registered; `sandbox_placement_code_invalid` if it is neither; `sandbox_placement_operation_timeout` for a time-out; `sandbox_placement_capability_unmet` for a capability not verified after `commit`; `sandbox_placement_ref_invalid` or `sandbox_placement_capability_undeclared` for a bad reference or claim from `commit`, as the seam raises them today; `sandbox_placement_refused` for a failed transfer or guard |
| refused, unconfirmed | The refusal's code, and `sandbox_placement_release_unconfirmed` beside it |
| cancelled | No code: whether a release was needed, and whether it was confirmed |
"""

C7_AFTER_LEFT = """\
| Condition | The walk |
|---|---|
| Another remote rung exists and the budget is not spent | Starts that rung |
| Otherwise, the last rung is `local` and the capacity bar is not set | Ends on **the launching host** |
| Otherwise, the last rung is `local` and the capacity bar is set | Ends **not run**, `sandbox_placement_capacity_exhausted` |
| Otherwise (the last rung is `none`) | Ends **not run**, with the code of the last rung left, or `sandbox_placement_required_unavailable` under the knob |
"""

#: The test's own names for the twenty rows above, in order. The state and the next state
#: of each come from the literal text, never from the product.
ROW_EVENTS = (
    "local_check_failed", "local_checks_passed",
    "connect_failed", "lease_unwritable", "budget_spent", "connected",
    "admitted", "at_capacity", "refused", "no_answer", "budget_spent",
    "backoff_elapsed", "wait_spent",
    "committed", "commit_failed",
    "sealed", "seal_failed", "budget_spent",
    "release_confirmed", "release_unconfirmed",
)
#: And for the four rows of the second table: (condition, what the walk does).
AFTER_LEFT_EVENTS = (
    ("another_rung", "start_next"),
    ("last_local_unbarred", "launching_host"),
    ("last_local_barred", "not_run_capacity_exhausted"),
    ("last_none", "not_run_last_code"),
)

#: The waiting loop is unbounded in the table; the enumeration bounds it here.
CAPACITY_ANSWERS_PER_RUNG = 2
#: Of the three-rung orderings, one in this many also runs on real threads, sockets and
#: lease files. One- and two-rung orderings all do.
REAL_IO_STRIDE = 16

CAPACITY = "sandbox_placement_at_capacity"
TIMEOUT = "sandbox_placement_operation_timeout"
REFUSED = "sandbox_placement_refused"
BUDGET = "sandbox_placement_budget_spent"
UNREACHABLE = "sandbox_placement_unreachable"
NOT_ENROLLED = "sandbox_placement_not_enrolled"
UNCONFIRMED = "sandbox_placement_release_unconfirmed"
EXHAUSTED = "sandbox_placement_capacity_exhausted"
DRIVER = "sandbox_placement_driver_unavailable"
WAITING_NOTICE = "seat_placement_waiting"
REQUIRED = frozenset({"inbound_closed", "one_shot_secret_channel", "private_ranges_unreachable"})
DIGEST = "d" * 64


def _cells(table: str) -> list[tuple[str, ...]]:
    rows = [line for line in table.splitlines() if line.startswith("|")]
    return [tuple(cell.strip() for cell in row.strip().strip("|").split("|")) for row in rows[2:]]


def _next_id(text: str) -> str:
    text = text.replace("*", "").replace("`", "").strip()
    if text.startswith("left:"):
        return "left:" + text[5:].strip().replace(", ", "_").replace(" ", "_")
    return "execute" if text == "execute is called" else text


STATE_ROWS = _cells(C7_STATES)
AFTER_ROWS = _cells(C7_AFTER_LEFT)
#: (state, event) -> next, read from the literal copy.
NEXT = {
    (row[0], event): _next_id(row[2]) for row, event in zip(STATE_ROWS, ROW_EVENTS)
}
STATES = ("start", "connecting", "admitting", "waiting", "committing", "sealing", "releasing")


def test_the_literal_copy_is_well_formed():
    assert len(STATE_ROWS) == len(ROW_EVENTS) == len(NEXT) == 20
    assert len(AFTER_ROWS) == len(AFTER_LEFT_EVENTS) == 4
    assert {state for state, _event in NEXT} == set(STATES)
    targets = set(NEXT.values())
    assert targets - set(STATES) == {
        "left:failed_locally", "left:unreachable", "left:out_of_time", "left:capacity",
        "left:refused", "left:refused_unconfirmed", "execute",
    }


def test_the_products_table_is_the_plans_table():
    """`LADDER_TABLE` equals the literal copy, row for row and cell for cell. Mutation: any
    change to a row of `LADDER_TABLE` (a next state, an event, a row removed)."""
    product = [(r.state, r.when, r.next, r.means) for r in sp.LADDER_TABLE.rung]
    literal = [(row[0], row[1], _next_id(row[2]), row[3]) for row in STATE_ROWS]
    # The finite implementation supplement extends only the gate workload wording.
    state, when, next_state, means = literal[0]
    literal[0] = (state, when.replace("a `leg` workload",
                                     "a `leg` or `implementation` workload"), next_state, means)
    assert product == literal
    assert tuple(r.event for r in sp.LADDER_TABLE.rung) == ROW_EVENTS
    after = [(r.condition, r.walk, r.when, r.then) for r in sp.LADDER_TABLE.after_left]
    assert after == [
        (condition, walk, row[0], row[1])
        for (condition, walk), row in zip(AFTER_LEFT_EVENTS, AFTER_ROWS)
    ]


def test_the_contract_carries_the_tables_verbatim():
    contract = Path(sp.__file__).parent / "advisor_board" / "CONTRACTS.md"
    lines = {line.strip() for line in contract.read_text(encoding="utf-8").splitlines()}
    for table in (C7_STATES, C7_CODES, C7_AFTER_LEFT):
        for line in table.splitlines():
            assert line.strip() in lines, line[:80]


# --------------------------------------------------------------------------------------
# The interpreter of the literal copy.
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One scripted event on the rung in hand.

    ``flag`` is how the test makes it happen: ``budget`` (the clock passes the budget inside
    the call), ``tie`` (the connection fails as the budget ends), ``cancel`` (the caller
    cancels inside the call), ``forced`` (no call: the state is entered with the budget or
    the wait already spent)."""

    state: str
    event: str
    flag: str = ""

    def __str__(self) -> str:
        return f"{self.state}:{self.event}" + (f"/{self.flag}" if self.flag else "")


@dataclass(frozen=True)
class _Model:
    n: int
    last_rung: str
    i: int = 0
    state: str = "start"
    budget: bool = False
    wait: bool = False
    bar: bool = False
    capacity_answers: int = 0
    cancel: bool = False
    reason: str | None = None
    trail: tuple = ()
    calls: tuple = ()
    leases: tuple = ()          # per rung: None | "held" | "abandoned"
    held: tuple = ()            # per rung: may something exist on the far side?
    capacity_truth: bool = False
    waited: bool = False
    outcome: str | None = None
    code: str | None = None
    script: tuple = ()

    @classmethod
    def initial(cls, n: int, last_rung: str) -> "_Model":
        return cls(n=n, last_rung=last_rung, leases=(None,) * n, held=(False,) * n)

    # -- what can happen next -----------------------------------------------------------
    def options(self) -> list[Step]:
        if self.outcome is not None:
            return []
        s, spent = self.state, self.budget
        if s == "start":
            return [Step(s, event, flag) for event in ("local_checks_passed", "local_check_failed")
                    for flag in ("", "budget")] + [Step(s, "cancel")]
        if s == "connecting":
            if spent:
                return [Step(s, "budget_spent", "forced")]
            return [Step(s, "connect_failed"), Step(s, "lease_unwritable"), Step(s, "connected"),
                    Step(s, "budget_spent", "budget"), Step(s, "budget_spent", "tie"),
                    Step(s, "cancel")]
        if s == "admitting":
            answers = ["admitted", "refused"]
            if self.capacity_answers < CAPACITY_ANSWERS_PER_RUNG:
                answers.append("at_capacity")
            return ([Step(s, event, flag) for event in answers for flag in ("", "budget")]
                    + [Step(s, "no_answer"), Step(s, "budget_spent", "budget"), Step(s, "cancel")])
        if s == "waiting":
            if spent or self.wait:
                return [Step(s, "wait_spent", "forced")]
            return [Step(s, "backoff_elapsed"), Step(s, "wait_spent"),
                    Step(s, "wait_spent", "budget"), Step(s, "cancel")]
        if s == "committing":
            if spent:
                return [Step(s, "commit_failed", "forced")]
            return [Step(s, event, flag) for event in ("committed", "commit_failed")
                    for flag in ("", "budget")] + [Step(s, "cancel")]
        if s == "sealing":
            if spent:
                return [Step(s, "budget_spent", "forced")]
            return [Step(s, "sealed"), Step(s, "seal_failed"), Step(s, "budget_spent", "budget"),
                    Step(s, "cancel")]
        assert s == "releasing"
        flags = [""] + ([] if spent else ["budget"]) + ([] if self.cancel else ["cancel"])
        return [Step(s, event, flag) for event in ("release_confirmed", "release_unconfirmed")
                for flag in flags]

    # -- what it does -------------------------------------------------------------------
    def _call(self, *ops: str) -> "_Model":
        return replace(self, calls=self.calls + tuple((self.i, op) for op in ops))

    def _set(self, name: str, value: object) -> "_Model":
        values = list(getattr(self, name))
        values[self.i] = value
        return replace(self, **{name: tuple(values)})

    def _record(self, klass: str, code: str | None, **extra: object) -> "_Model":
        record = {"rung": f"r{self.i + 1}", "class": klass, "code": code, **extra}
        return replace(self, trail=self.trail + (record,))

    def _cancelled(self, *, release: bool | None) -> "_Model":
        extra = {"release_needed": release is not None, "release_confirmed": release}
        return replace(self._record("cancelled", None, **extra), outcome="cancelled")

    def _left(self, klass: str, code: str | None, **extra: object) -> "_Model":
        """The second table, in its own order."""
        m = self._record(klass, code, **extra)
        for (condition, walk) in AFTER_LEFT_EVENTS:
            if condition == "another_rung" and not (m.i + 1 < m.n and not m.budget):
                continue
            if condition == "last_local_unbarred" and not (m.last_rung == "local" and not m.bar):
                continue
            if condition == "last_local_barred" and not (m.last_rung == "local" and m.bar):
                continue
            break
        if walk == "start_next":
            return replace(m, i=m.i + 1, state="start", capacity_answers=0, reason=None)
        if walk == "launching_host":
            return replace(m, outcome="launching_host")
        if walk == "not_run_capacity_exhausted":
            return replace(m, outcome="not_run", code=EXHAUSTED)
        return replace(m, outcome="not_run", code=code)

    def advance(self, step: Step) -> "_Model":
        assert step.state == self.state, (step, self.state)
        m = replace(self, script=self.script + (step,))
        s, event, flag = step.state, step.event, step.flag
        # The calls the driver makes in this state, whatever comes of them.
        if flag != "forced":
            if s == "start":
                m = m._call("available") if event != "local_checks_passed" else m._call(
                    "available", "endpoint", "capabilities", "declaration")
            elif s == "connecting":
                m = m._call("connect")
            elif s == "admitting":
                m = m._call("admit")._set("held", True)
            elif s == "waiting":
                m = m._call("pause")
            elif s == "committing":
                m = m._call("commit")
            elif s == "sealing":
                m = m._call("seal")
            else:
                m = m._call("kill")
        if flag in ("budget", "tie"):
            m = replace(m, budget=True)
        if flag == "cancel" or event == "cancel":
            m = replace(m, cancel=True)
        if event == "cancel":
            # Accepted in every state; it never moves the walk on.
            if s in ("start", "connecting"):
                return m._cancelled(release=None)
            if s == "waiting":
                return m._set("leases", None)._cancelled(release=None)
            return replace(m, state="releasing")
        target = NEXT[(s, event)]
        if s == "connecting" and event == "lease_unwritable":
            m = m._call("lease_open_failed")
        if s == "connecting" and event == "connected":
            m = m._call("lease_open")._set("leases", "held")
        if s == "admitting":
            if event == "at_capacity":
                m = replace(m._set("held", False), bar=True, capacity_truth=True,
                            capacity_answers=m.capacity_answers + 1, waited=True)
            elif event == "refused":
                m = m._set("held", False)._set("leases", None)
            elif event == "no_answer":
                m = replace(m, reason=TIMEOUT)
            elif event == "budget_spent":
                m = replace(m, reason=BUDGET)
        if s == "waiting" and event == "wait_spent":
            m = replace(m._set("leases", None), wait=m.wait or flag != "forced" or not m.budget)
        if s == "committing" and event == "commit_failed":
            m = replace(m, reason=BUDGET if flag in ("budget", "forced") else REFUSED)
        if s == "sealing" and event != "sealed":
            m = replace(m, reason=BUDGET if event == "budget_spent" else REFUSED)
        if s == "releasing":
            confirmed = event == "release_confirmed"
            m = m._call("list_owned") if confirmed else m
            m = m._set("leases", None)._set("held", False) if confirmed else m._set(
                "leases", "abandoned")
            if m.cancel:
                return m._cancelled(release=confirmed)
            if confirmed:
                return m._left("refused", m.reason)
            return m._left("refused_unconfirmed", m.reason, release=UNCONFIRMED)
        if target == "execute":
            m = m._call("execute")._record("placed", None)
            return replace(m, outcome="placed")
        if target.startswith("left:"):
            klass = target[5:]
            code = {
                "failed_locally": REFUSED, "unreachable": UNREACHABLE, "out_of_time": BUDGET,
                "capacity": CAPACITY, "refused": NOT_ENROLLED,
            }[klass]
            return m._left(klass, code)
        return replace(m, state=target)


def orderings(n: int, last_rung: str):
    """Every ordering the tables allow, depth first. Nothing within the bound is skipped."""
    stack = [_Model.initial(n, last_rung)]
    while stack:
        model = stack.pop()
        if model.outcome is not None:
            yield model
            continue
        stack.extend(model.advance(step) for step in model.options())


# --------------------------------------------------------------------------------------
# The world the real `place` is driven in: scripted fakes, loopback endpoints, a fake clock.
# --------------------------------------------------------------------------------------

SCHEMES = ("fakea", "fakeb", "fakec")
FAR = 1.0e9          # a clock step that passes any budget
NEVER = 10**7        # a setting no ordering reaches


# The far side of the open endpoint: a child process that accepts every connection, waits
# for the driver to close its end, then resets its own. Neither side is left in TIME_WAIT,
# so the enumeration's many connections never run out of ports, and the reset cannot race
# the driver's `connect`. A process, not a thread: it must not share the interpreter lock
# with the walk it serves. It exits when its standard input closes, so it cannot outlive
# the test process.
_ACCEPTOR = r"""
import select, socket, struct, sys
listener = socket.socket(fileno=int(sys.argv[1]))
reset = struct.pack("ii", 1, 0)
while True:
    ready, _, _ = select.select([listener, sys.stdin], [], [])
    if sys.stdin in ready:
        break
    peer, _address = listener.accept()
    try:
        peer.settimeout(5.0)
        peer.recv(1)
        peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, reset)
    except OSError:
        pass
    peer.close()
"""


class Endpoints:
    """Two real loopback sockets: one that accepts connections and one that is closed."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(128)
        self.open_port = self._listener.getsockname()[1]
        # Bound and never listening: a connection to it is refused.
        self._closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._closed.bind(("127.0.0.1", 0))
        self.closed_port = self._closed.getsockname()[1]
        self._acceptor = subprocess.Popen(
            [sys.executable, "-c", _ACCEPTOR, str(self._listener.fileno())],
            stdin=subprocess.PIPE, pass_fds=[self._listener.fileno()],
        )

    def close(self) -> None:
        self._acceptor.stdin.close()
        self._acceptor.wait(timeout=10)
        self._listener.close()
        self._closed.close()


class MemoryLease:
    """A lease with the journal's interface and no file: what `place` is given for the
    three-rung orderings that do not touch the disk."""

    owner_id = "0" * 32

    def __init__(self, number: int) -> None:
        self.lease_id = f"{number:032x}"
        self.fenced = False
        self.state: str | None = "held"
        self.sandbox_ref: str | None = None

    def fence(self) -> None:
        self.fenced = True

    def record_sandbox_ref(self, sandbox_ref: str) -> None:
        self.sandbox_ref = sandbox_ref

    def note_killed(self) -> None:
        pass

    def abandon(self) -> None:
        self.fenced = True
        self.state = "abandoned"

    def clear(self) -> None:
        self.state = None


class InlineCalls:
    """`_Calls` without its worker thread: the scripted backends always return at once."""

    def ready(self) -> None:
        pass

    def run(self, call, timeout_s, cancelled=None):
        return call()

    def close(self) -> None:
        pass


class World:
    """One ordering: its script, its clock, and everything `place` did in it."""

    def __init__(self, endpoints: Endpoints, script: tuple = (), real: bool = True) -> None:
        self.endpoints = endpoints
        self.script = script
        #: Real threads, sockets and lease files under `place`, or the in-memory three.
        self.real = real
        self.cursor = 0
        self.rung = 0
        self.now = 1000.0
        self.started = self.now
        self.log: list[tuple[int, str]] = []
        self.clock: list[float] = []         # the clock at each log entry
        self.lease_of: list[str] = []        # the lease a log entry was made for, or ""
        self.cancelled = threading.Event()
        self.cancel_at: int | None = None
        self.leases: dict[int, placement_lease.Lease] = {}
        self.fail_lease = False
        self.unexpected: list[str] = []
        self.requests: list[sp.PlacementRequest] = []
        self.connect_errors: list[str] = []
        self.fenced_at_kill: list[bool] = []

    def note(self, op: str, lease: str = "") -> None:
        self.log.append((self.rung, op))
        self.clock.append(self.now)
        self.lease_of.append(lease)

    def take(self, state: str) -> Step:
        """The scripted step this call realizes. Steps no call makes are skipped."""
        while self.cursor < len(self.script) and self.script[self.cursor].flag == "forced":
            self.cursor += 1
        if self.cursor >= len(self.script) or self.script[self.cursor].state != state:
            self.unexpected.append(f"{state} at {self.cursor}")
            return Step(state, "unexpected")
        step = self.script[self.cursor]
        self.cursor += 1
        if step.flag in ("budget", "tie"):
            self.now += FAR
        if step.flag == "cancel" or step.event == "cancel":
            self.cancel_at = len(self.log)
            self.cancelled.set()
        return step

    def consumed(self) -> bool:
        rest = self.script[self.cursor:]
        return not self.unexpected and all(step.flag == "forced" for step in rest)


class ScriptedBackend:
    """A conformant in-process backend that does what the script says and records every
    call made to it, in order."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.name = SCHEMES[index]
        self.world: World | None = None
        self.refs: dict[str, str] = {}

    def capabilities(self):
        self.world.note("capabilities")
        return REQUIRED

    def declaration(self):
        self.world.note("declaration")
        return sp.Declaration()

    def available(self, request):
        step = self.world.take("start")
        self.world.note("available")
        return step.event != "local_check_failed"

    def endpoint(self, root):
        self.world.note("endpoint")
        return ("127.0.0.1", self.world.endpoints.open_port)

    def admit(self, request, bound):
        world = self.world
        step = world.take("admitting")
        world.requests.append(request)
        world.note("admit", request.lease_id)
        if step.event == "at_capacity":
            raise sp.PlacementUnavailable(CAPACITY)
        if step.event == "refused":
            raise sp.PlacementUnavailable(NOT_ENROLLED)
        if step.event in ("no_answer", "budget_spent"):
            raise sp.PlacementUnavailable(TIMEOUT)

    def commit(self, prepared, request, bound=None):
        world = self.world
        step = world.take("committing")
        world.note("commit", request.lease_id)
        if step.event == "commit_failed":
            if step.flag == "budget":
                raise sp.PlacementUnavailable(TIMEOUT)
            raise RuntimeError("the transfer failed")
        ref = f"sbx-{self.index}-{request.lease_id[:8]}"
        self.refs[ref] = request.lease_id
        receipt = sp.PlacementReceipt.from_backend(
            sp.BackendReceipt("committed", ref, prepared.snapshot_sha256))
        return sp.PlacedSandbox(
            backend=self.name, sandbox_ref=ref, staged_at=f"{self.name}:{ref}",
            receipts=(receipt,), verified={name: "backend_attested" for name in REQUIRED},
        )

    def execute(self, sandbox_ref, spec, bound):
        self.world.note("execute", self.refs.get(sandbox_ref, "?"))
        return sp.BackendReceipt("launched", sandbox_ref, DIGEST)

    def kill(self, lease_id, bound):
        world = self.world
        step = world.take("releasing")
        # Entering "releasing" fences first: the driver's own mark is set before the kill.
        world.fenced_at_kill.append(world.leases[world.rung].fenced)
        world.note("kill", lease_id)
        if step.event != "release_confirmed":
            raise sp.PlacementUnavailable(TIMEOUT)

    def list_owned(self, owner_id, bound):
        self.world.note("list_owned")
        return []

    def release(self, prepared, bound=None):
        self.world.note("release")

    def wait(self, sandbox_ref, wait_s):
        self.world.note("wait")

    def cancel(self, sandbox_ref, bound):
        self.world.note("cancel")

    def renew(self, sandbox_ref, until_s, bound):
        self.world.note("renew")


def prepared_stage(tmp: Path) -> sp.Prepared:
    return sp.Prepared(
        review_dir=tmp, local_tree=tmp / "reviewed-tree", snapshot_sha256=DIGEST,
        sandbox_ref="local:stage",
        receipt=sp._runtime_receipt("prepared", "local:stage", DIGEST),
    )


def exec_spec(request: sp.PlacementRequest, body: bytes = b"sealed request") -> sp.ExecSpec:
    return sp.ExecSpec(
        workload=request.workload, request=body, deadline_s=request.deadline_s,
        must_end_within_s=request.deadline_s, output_cap_bytes=1 << 20,
    )


class Harness:
    """The fakes, registered once, and the seams of the driver pointed at one `World`."""

    def __init__(self, tmp: Path, patch: pytest.MonkeyPatch) -> None:
        self.endpoints = Endpoints()
        self.backends = [ScriptedBackend(i) for i in range(len(SCHEMES))]
        for backend in self.backends:
            sp.register_backend(backend.name, backend)
        self.rungs = sandbox_policy.candidate_roots(
            [(f"r{i + 1}", f"{scheme}://rung-{i + 1}.invalid/stage")
             for i, scheme in enumerate(SCHEMES)])
        self.prepared = prepared_stage(tmp)
        self.patch = patch
        self.world = World(self.endpoints)
        self.backoff = sp._ADMIT_BACKOFF_S
        # The suite's own fixtures remove XDG_* names before every test, so the state dir is
        # pinned again at every drive and every lease is checked to be under it.
        self.state = tmp / "state"
        patch.setenv("XDG_STATE_HOME", str(self.state))
        patch.delenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", raising=False)
        patch.setattr(sp, "_monotonic", lambda: self.world.now)
        patch.setattr(sp, "_pause", self._pause)
        self._open_connection = sp._open_connection
        patch.setattr(sp, "_open_connection", self._connect)
        bounded = sp._Calls
        patch.setattr(sp, "_Calls", lambda **kwargs: bounded(**kwargs) if self.world.real else InlineCalls())
        self._settings: dict[str, str | None] = {}
        self._leases = 0

    def close(self) -> None:
        self.endpoints.close()
        for scheme in SCHEMES:
            sp._REGISTRY.pop(scheme, None)
            sp._BACKEND_CODES.pop(scheme, None)

    # -- the driver's seams ---------------------------------------------------------------
    def _pause(self, cancelled, seconds):
        world = self.world
        step = world.take("waiting")
        world.note("pause")
        if step.event != "cancel" and step.flag != "budget":
            world.now += seconds

    def _connect(self, host, port, timeout_s):
        world = self.world
        step = world.take("connecting")
        world.note("connect")
        if step.event == "lease_unwritable":
            world.fail_lease = True
        refused = step.event == "connect_failed" or step.flag == "tie"
        try:
            if not world.real:
                if refused:
                    raise ConnectionRefusedError("scripted: the port is closed")
                return None
            port = self.endpoints.closed_port if refused else port
            return self._open_connection(host, port, timeout_s)
        except Exception as exc:
            world.connect_errors.append(f"{type(exc).__name__}: {exc}")
            raise

    def _request_for(self, root):
        world = self.world
        world.rung = int(root.name[1:]) - 1
        return sp.PlacementRequest(
            leg="codex", round_id="codex:a", repo="/repo", snapshot_sha256=DIGEST,
            deadline_s=None, egress_needs=sp.EgressNeeds(), workload=world.workload,
            required_capabilities=REQUIRED,
        )

    def _open_lease(self, name, root):
        world = self.world
        if world.fail_lease:
            world.fail_lease = False
            world.note("lease_open_failed")
            raise OSError("the lease entry cannot be written")
        if world.real:
            lease = placement_lease.open_lease(name, root)
            assert lease.path.is_relative_to(self.state), lease.path
        else:
            self._leases += 1
            lease = MemoryLease(self._leases)
        world.leases[world.rung] = lease
        world.note("lease_open", lease.lease_id)
        return lease

    def _seal(self, request):
        world = self.world
        step = world.take("sealing")
        world.note("seal", request.lease_id)
        if step.event == "seal_failed" or not world.guard():
            return None
        return exec_spec(request)

    # -- one ordering ---------------------------------------------------------------------
    def _setting(self, name: str, value: str | None) -> None:
        if self._settings.get(name, "") != value:
            self._settings[name] = value
            if value is None:
                self.patch.delenv(name, raising=False)
            else:
                self.patch.setenv(name, value)

    def drive(self, n: int, last_rung: str, script: tuple, *, workload: str = "leg",
              driver_enabled: bool = True, preflight=None, guard=None, defaults: bool = False,
              real: bool = True):
        """Drive the real `place` through `script`. `preflight` and `guard` are given the
        world, so they can read its clock. With `defaults` the walk runs on the settings'
        default values instead of ones chosen to make the script happen. `real` is whether
        the calls, the connection attempt and the lease journal under `place` are real."""
        world = self.world = World(self.endpoints, script, real)
        self.patch.setenv("XDG_STATE_HOME", str(self.state))
        world.workload = workload
        world.guard = (lambda: guard(world)) if guard is not None else (lambda: True)
        for backend in self.backends:
            backend.world = world
            backend.refs.clear()
        if defaults:
            self._setting("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", None)
            self._setting("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", None)
            world.budget = 600 + 300
        else:
            wait_s = self._wait_setting(script)
            self._setting("PHASE_LOOP_SANDBOX_ADMIT_WAIT_S", str(wait_s))
            self._setting("PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S", str(NEVER))
            world.budget = wait_s + NEVER
        preflight = (lambda: None) if preflight is None else (lambda p=preflight: p(world))
        try:
            decision = sp.place(
                self.rungs[:n], last_rung, self.prepared, self._request_for, self._open_lease,
                preflight=preflight, seal=self._seal, driver_enabled=driver_enabled,
                cancelled=world.cancelled,
            )
        except sp.PlacementCancelled as exc:
            return world, None, exc
        return world, decision, None

    def _wait_setting(self, script: tuple) -> int:
        """The admission wait that makes the scripted `wait_spent` happen where it is
        scripted: it is reached by exactly that many back-offs, summed over all rungs."""
        pauses = 0
        for step in script:
            if step.state != "waiting" or step.flag in ("forced", "budget") or step.event == "cancel":
                continue
            pauses += 1
            if step.event == "wait_spent":
                return int(pauses * self.backoff)
        return NEVER

    def lease_state(self, world: World, rung: int) -> str | None:
        """What the journal holds for a rung's lease: nothing, a held entry, or an entry
        kept with a free lock and marked abandoned."""
        lease = world.leases.get(rung)
        if lease is None:
            return None
        if isinstance(lease, MemoryLease):
            return lease.state
        try:
            fd = os.open(lease.path, os.O_RDWR)
        except FileNotFoundError:
            return None
        try:
            entry = json.loads(os.read(fd, 4096).split(b"\n", 1)[0])
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            free = True
        except OSError:
            free = False
        finally:
            os.close(fd)
        if free:
            return "abandoned" if entry["abandoned"] else "free-unmarked"
        return "held" if not entry["abandoned"] else "held-marked"

    def forget(self, world: World) -> None:
        """Drop what an ordering left in the journal, so the next one starts clean."""
        for lease in world.leases.values():
            lease.clear()


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    built = Harness(tmp_path_factory.mktemp("ladder"), patch)
    # The journal's syncs are ordered against `admit` by the lease tests; here they would
    # only make the enumeration slow.
    patch.setattr(placement_lease, "_fsync", lambda fd: None)
    import logging

    logger = logging.getLogger(sp.__name__)
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield built
    finally:
        logger.setLevel(level)
        built.close()
        patch.undo()


def check(harness: Harness, model: _Model, real: bool = True) -> list[str]:
    """Drive the real `place` through one ordering and compare. Returns what differs."""
    world, decision, cancel = harness.drive(model.n, model.last_rung, model.script, real=real)
    try:
        return _compare(harness, model, world, decision, cancel)
    finally:
        harness.forget(world)


def _compare(harness, model, world, decision, cancel) -> list[str]:
    wrong: list[str] = []

    def expect(what: str, got: object, want: object) -> None:
        if got != want:
            wrong.append(f"{what}: got {got!r}, the table gives {want!r}")

    # -- 3. what `place` did against what the table says --------------------------------
    if cancel is not None:
        outcome, code, trail = "cancelled", None, cancel.trail
        expect("what a cancel raises", str(cancel), "review_operation_cancelled")
    else:
        outcome, code, trail = decision.outcome, decision.code, decision.trail
        expect("the never-sealed mark", decision.tooled_route_required, outcome == "launching_host")
        expect("a placement", decision.placement is not None, outcome == "placed")
        expect("the waiting notice", WAITING_NOTICE in decision.notices, model.waited)
    expect("outcome", outcome, model.outcome)
    expect("code", code, model.code)
    expect("trail", [dict(record) for record in trail], list(model.trail))
    expect("calls", world.log, list(model.calls))
    refused = sum(step.event == "connect_failed" or step.flag == "tie" for step in model.script)
    expect("connection failures", len(world.connect_errors), refused)
    if len(world.connect_errors) != refused:
        wrong.append(repr(world.connect_errors))
    expect("the script was followed", world.consumed(), True)
    states = tuple(harness.lease_state(world, rung) for rung in range(model.n))
    expect("lease journal", states, model.leases)

    # -- the properties, from what was observed and the scripted truth -------------------
    log = world.log
    executes = [k for k, (_rung, op) in enumerate(log) if op == "execute"]
    if len(executes) > 1 or (outcome == "placed") != (len(executes) == 1):
        wrong.append("P1: execute is called at most once, exactly once when placed")
    if executes and executes[0] != len(log) - 1:
        wrong.append("P2: a call follows execute")
    answered_capacity = any(step.event == "at_capacity" for step in model.script)
    if outcome == "launching_host" and answered_capacity:
        wrong.append("P3: the launching host after a capacity answer")
    if outcome == "not_run" and not (answered_capacity or model.last_rung == "none"):
        wrong.append("P4: not run without the capacity bar or a last rung of none")
    if world.cancel_at is not None:
        after = log[world.cancel_at + 1:]
        rung_in_hand = log[world.cancel_at][0]
        if outcome != "cancelled" or any(
            rung != rung_in_hand or op not in ("kill", "list_owned") for rung, op in after
        ):
            wrong.append("P5: after a cancel something happened that is not a release")
    killed = {lease for lease, (_rung, op) in zip(world.lease_of, log) if op == "kill"}
    placed_on = log[executes[0]][0] if executes else None
    for rung, may_hold in enumerate(model.held):
        lease = world.leases.get(rung)
        if rung == placed_on:
            continue
        if may_hold and not (states[rung] == "abandoned" and lease.lease_id in killed):
            wrong.append(f"P6: rung {rung + 1} may hold something without a fenced, kept lease")
    if not all(world.fenced_at_kill):
        wrong.append("P6: a kill was sent for a lease the driver had not fenced")
    for k in executes:
        if world.lease_of[k] in {
            lease for lease, (_r, op) in zip(world.lease_of[:k], log[:k]) if op == "kill"
        } or world.leases[log[k][0]].fenced:
            wrong.append("P6: execute was sent for a fenced lease")
    touched = list(dict.fromkeys(rung for rung, _op in log))
    if [record["rung"] for record in trail] != [f"r{rung + 1}" for rung in touched]:
        wrong.append("P7: the trail does not name every rung touched, once, in order")
    for k in range(1, len(log)):
        # A rung's first call: was the budget already spent when the rung before was left?
        if log[k][0] != log[k - 1][0] and world.clock[k - 1] - world.started >= world.budget:
            wrong.append("P8: a rung was started after the budget was spent")
    for rung, lease in world.leases.items():
        first_admit = next(
            (k for k, entry in enumerate(log) if entry == (rung, "admit")), None)
        if first_admit is not None and (rung, "lease_open") not in log[:first_admit]:
            wrong.append("the lease entry was not written before admit")
    return wrong


CONFIGURATIONS = [(n, last) for n in (1, 2, 3) for last in ("local", "none")]


@pytest.mark.parametrize("n,last_rung", CONFIGURATIONS)
def test_the_real_walk_does_what_the_table_says_on_every_ordering(harness, n, last_rung):
    """Acceptance 1. Every ordering the literal tables allow for this many rungs and this
    last rung, none skipped within `CAPACITY_ANSWERS_PER_RUNG`: the real `place` produces
    the outcome, trail, backend calls and lease entries the table gives, and the eight
    properties hold."""
    count = real_io = 0
    failures: list[str] = []
    seen_rows: set[tuple[str, str]] = set()
    for model in orderings(n, last_rung):
        real = n < 3 or count % REAL_IO_STRIDE == 0
        count += 1
        real_io += real
        seen_rows.update((step.state, step.event) for step in model.script)
        wrong = check(harness, model, real)
        if wrong:
            failures.append(" > ".join(map(str, model.script)) + "\n    " + "\n    ".join(wrong))
            if len(failures) >= 5:
                break
    assert not failures, f"{len(failures)} orderings differ, the first:\n" + "\n".join(failures)
    # Every row of the first table was exercised, and nothing was enumerated twice.
    assert seen_rows >= set(NEXT)
    assert count == EXPECTED_ORDERINGS[n]
    assert real_io == (count if n < 3 else -(-count // REAL_IO_STRIDE))


#: The size of the enumeration, so that a change which silently skips orderings is seen.
EXPECTED_ORDERINGS = {1: 176, 2: 4502, 3: 109712}


# --------------------------------------------------------------------------------------
# Named orderings. Each is one ordering of the enumeration, kept as a test of its own so
# that a failure reads as the finding it answers. Their expectations are written out here,
# not taken from the interpreter.
# --------------------------------------------------------------------------------------

REACHED = ("start:local_checks_passed", "connecting:connected")
ADMITTED = (*REACHED, "admitting:admitted")
PLACED = (*ADMITTED, "committing:committed", "sealing:sealed")


def script(*specs: str) -> tuple[Step, ...]:
    return tuple(Step(*spec.split(":")) for spec in specs)


@pytest.fixture
def drive(harness):
    worlds: list[World] = []

    def run(n: int, last_rung: str, *specs: str, **options):
        world, decision, cancel = harness.drive(n, last_rung, script(*specs), **options)
        worlds.append(world)
        assert world.consumed(), (world.unexpected, world.cursor, world.log)
        return world, decision, cancel

    run.lease_state = harness.lease_state
    try:
        yield run
    finally:
        for world in worlds:
            harness.forget(world)


def summary(trail) -> list[tuple]:
    return [(record["rung"], record["class"], record["code"]) for record in trail]


def ops(world: World, rung: int | None = None) -> list[str]:
    return [op for index, op in world.log if rung is None or index == rung]


def test_two_refusals_end_on_the_launching_host_with_both_rungs_in_the_trail(drive):
    """Mutation: a non-capacity refusal ends the attempt instead of leaving the rung."""
    world, decision, _ = drive(
        2, "local", *REACHED, "admitting:refused", *REACHED, "admitting:refused")
    assert decision.outcome == "launching_host" and decision.code is None
    assert decision.tooled_route_required is True
    assert summary(decision.trail) == [
        ("r1", "refused", NOT_ENROLLED), ("r2", "refused", NOT_ENROLLED)]
    assert "commit" not in ops(world) and "execute" not in ops(world)
    assert [drive.lease_state(world, rung) for rung in (0, 1)] == [None, None]


def test_the_lifetime_boundary_with_the_default_settings(drive):
    """With the defaults a credential with exactly the floor plus the whole budget left is
    placed on rung two after rung one used up the wait; one second less and nothing is
    sent. Mutations: the preflight's sum is evaluated again before a later rung; the wait
    or the allowance is left out of the sum."""
    floor, seen = 1800.0, []

    def remaining(world, total):
        return total - (world.now - world.started)

    def guard(world):
        seen.append(remaining(world, 2700.0))
        return sp.lifetime_at_floor(seen[-1], floor)

    def preflight(total):
        return lambda world: (
            None if sp.lifetime_sufficient(remaining(world, total), floor) else "below_floor")

    full_host = (*REACHED, *("admitting:at_capacity", "waiting:backoff_elapsed") * 39,
                 "admitting:at_capacity", "waiting:wait_spent")
    world, decision, _ = drive(
        2, "local", *full_host, *PLACED, defaults=True, preflight=preflight(2700.0), guard=guard)
    assert world.now - world.started == 600.0 and seen == [2100.0]
    assert decision.outcome == "placed"
    assert summary(decision.trail) == [("r1", "capacity", CAPACITY), ("r2", "placed", None)]
    assert decision.notices == (WAITING_NOTICE,)

    world, decision, _ = drive(2, "local", defaults=True, preflight=preflight(2699.0), guard=guard)
    assert decision.outcome == "launching_host" and decision.code == "below_floor"
    assert decision.tooled_route_required is True and decision.trail == ()
    assert world.log == []


@pytest.mark.parametrize("rungs,outcome", [(1, "launching_host"), (2, "placed")])
def test_a_host_that_stops_answering_is_left_fenced_and_the_walk_goes_on(drive, rungs, outcome):
    """Connected; `admit` times out; the kill by lease id times out too. Mutations: an
    unconfirmed release clears the lease entry, or does not fence; an unconfirmed release
    before `execute` ends the attempt; the release is never attempted."""
    world, decision, _ = drive(
        rungs, "local", *REACHED, "admitting:no_answer", "releasing:release_unconfirmed",
        *(PLACED if rungs == 2 else ()))
    assert decision.outcome == outcome
    assert dict(decision.trail[0]) == {
        "rung": "r1", "class": "refused_unconfirmed", "code": TIMEOUT, "release": UNCONFIRMED}
    assert ops(world, 0)[-2:] == ["admit", "kill"]
    lease = world.leases[0]
    assert drive.lease_state(world, 0) == "abandoned" and lease.fenced
    assert (0, "execute") not in world.log


@pytest.mark.parametrize("rungs,outcome,code", [(1, "not_run", EXHAUSTED), (2, "placed", None)])
def test_a_full_rung_that_then_fails_never_sends_the_seat_to_the_launching_host(
    drive, rungs, outcome, code,
):
    """At capacity, then admitted on the same rung, then the seal step's guard fails: the
    capacity bar is set, so the next remote rung or "not run". Mutation: the capacity bar
    is cleared by a later admission, or not set at all."""
    world, decision, _ = drive(
        rungs, "local", *REACHED, "admitting:at_capacity", "waiting:backoff_elapsed",
        "admitting:admitted", "committing:committed", "sealing:seal_failed",
        "releasing:release_confirmed", *(PLACED if rungs == 2 else ()))
    assert (decision.outcome, decision.code) == (outcome, code)
    assert summary(decision.trail)[0] == ("r1", "refused", REFUSED)
    assert ops(world, 0)[-3:] == ["seal", "kill", "list_owned"]
    assert drive.lease_state(world, 0) is None


def test_the_budget_spent_while_committing_releases_and_starts_no_other_rung(drive):
    world, decision, _ = drive(
        2, "local", *ADMITTED, "committing:commit_failed:budget", "releasing:release_confirmed")
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "refused", BUDGET)]
    assert ops(world, 0)[-3:] == ["commit", "kill", "list_owned"] and ops(world, 1) == []


@pytest.mark.parametrize("rungs", [1, 2])
def test_the_clock_can_pass_the_budget_during_a_release(drive, rungs):
    """The release has its own bound outside the budget, so it finishes; the budget is read
    when the rung is left and no further rung is started."""
    world, decision, _ = drive(
        rungs, "local", *REACHED, "admitting:no_answer", "releasing:release_confirmed:budget")
    assert decision.outcome == "launching_host"
    assert summary(decision.trail) == [("r1", "refused", TIMEOUT)]
    assert ops(world, 0)[-2:] == ["kill", "list_owned"] and ops(world, 1) == []


def test_the_clock_can_pass_the_budget_before_the_local_checks_finish(drive):
    world, decision, _ = drive(
        2, "none", "start:local_checks_passed:budget", "connecting:budget_spent:forced")
    assert (decision.outcome, decision.code) == ("not_run", BUDGET)
    assert summary(decision.trail) == [("r1", "out_of_time", BUDGET)]
    assert "connect" not in ops(world) and ops(world, 1) == []


def test_the_budget_wins_a_tie_with_the_connection_attempt(drive):
    """The connection attempt fails as the budget ends: "out of time", not "unreachable"."""
    world, decision, _ = drive(1, "local", "start:local_checks_passed", "connecting:budget_spent:tie")
    assert len(world.connect_errors) == 1
    assert summary(decision.trail) == [("r1", "out_of_time", BUDGET)]


@pytest.mark.parametrize("state,specs,release", [
    ("admitting", (*REACHED, "admitting:cancel", "releasing:release_confirmed"), True),
    ("committing", (*ADMITTED, "committing:cancel", "releasing:release_unconfirmed"), False),
    ("sealing", (*ADMITTED, "committing:committed", "sealing:cancel",
                 "releasing:release_confirmed"), True),
    ("waiting", (*REACHED, "admitting:at_capacity", "waiting:cancel"), None),
    ("connecting", ("start:local_checks_passed", "connecting:cancel"), None),
    ("start", ("start:cancel",), None),
    ("releasing", (*REACHED, "admitting:no_answer", "releasing:release_confirmed:cancel"), True),
], ids=["admitting", "committing", "sealing", "waiting", "connecting", "start", "releasing"])
def test_a_cancel_ends_the_attempt_and_never_moves_the_walk_on(drive, state, specs, release):
    """Mutations: a cancel moves on to the next rung; the cancelled rung is left out of the
    trail; a cancel while something may be held skips the release."""
    world, decision, cancel = drive(2, "local", *specs)
    assert decision is None and str(cancel) == "review_operation_cancelled"
    assert dict(cancel.trail[-1]) == {
        "rung": "r1", "class": "cancelled", "code": None,
        "release_needed": release is not None, "release_confirmed": release,
    }
    after = world.log[world.cancel_at + 1:]
    assert all(rung == 0 and op in ("kill", "list_owned") for rung, op in after), after
    assert ("kill" in ops(world)) is (release is not None)
    assert not {"execute"} & set(ops(world)) and ops(world, 1) == []
    want = {True: None, False: "abandoned", None: None}[release]
    assert drive.lease_state(world, 0) == want


def test_an_unreachable_first_rung_is_in_the_trail_of_a_seat_placed_on_the_second(drive):
    """Mutation: a rung is left without a trail record."""
    world, decision, _ = drive(
        2, "local", "start:local_checks_passed", "connecting:connect_failed", *PLACED)
    assert decision.outcome == "placed" and decision.placement is not None
    assert summary(decision.trail) == [("r1", "unreachable", UNREACHABLE), ("r2", "placed", None)]
    assert ops(world, 0) == ["available", "endpoint", "capabilities", "declaration", "connect"]
    assert world.log[-1] == (1, "execute")
    assert drive.lease_state(world, 1) == "held"


@pytest.mark.parametrize("last_rung,outcome,code", [
    ("local", "launching_host", None), ("none", "not_run", DRIVER)])
def test_a_leg_with_the_driver_flag_false_touches_no_backend(drive, last_rung, outcome, code):
    """Every remote rung is left "failed locally" before its backend is looked up or
    called, and no connection is attempted. Mutation: drive a `leg` while the flag is false."""
    world, decision, _ = drive(2, last_rung, driver_enabled=False)
    assert (decision.outcome, decision.code) == (outcome, code)
    assert summary(decision.trail) == [
        ("r1", "failed_locally", DRIVER), ("r2", "failed_locally", DRIVER)]
    assert world.log == [] and world.leases == {}


@pytest.mark.parametrize("last_rung,outcome", [("local", "launching_host"), ("none", "not_run")])
def test_a_failed_preflight_resolves_the_last_rung_at_once(drive, last_rung, outcome):
    world, decision, _ = drive(2, last_rung, preflight=lambda world: "seat_credential_below_floor")
    assert (decision.outcome, decision.code) == (outcome, "seat_credential_below_floor")
    assert decision.tooled_route_required is (outcome == "launching_host")
    assert decision.trail == () and world.log == []


def test_a_last_rung_of_none_under_the_knob_carries_the_knobs_code(drive, monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_REMOTE_REQUIRED", "1")
    assert sandbox_policy.last_rung() == "none"
    world, decision, _ = drive(1, "none", *REACHED, "admitting:refused")
    assert (decision.outcome, decision.code) == (
        "not_run", "sandbox_placement_required_unavailable")
    assert summary(decision.trail) == [("r1", "refused", NOT_ENROLLED)]
