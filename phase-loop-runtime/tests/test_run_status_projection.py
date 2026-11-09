"""JOURNAL SL-1: replay projection, liveness, bounded pages and reader views.

Vectors enter production entries only (artifact section 12). Journals are
written through SL-0 or materialized by the test-only harness. Each mutation
control replaces one asserted-present fragment of ``run_status_projection``;
its witness passes on production and fails on the mutant.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import ModuleType

import pytest
import rfc8785

import _run_status_vectors as vectors
from phase_loop_runtime import run_status as rs
from phase_loop_runtime import run_status_projection as production

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the journal writer is Linux-only")

A = sha256(b"assignment-a").hexdigest()
B = sha256(b"assignment-b").hexdigest()
ENVELOPE = sha256(b"envelope").hexdigest()
SNAPSHOT = sha256(b"snapshot").hexdigest()
DIGEST = sha256(b"digest").hexdigest()
SRC = str(Path(rs.__file__).resolve().parents[1])


@pytest.fixture(autouse=True)
def umask077():
    previous = os.umask(0o077)
    yield
    os.umask(previous)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def make_root(tmp_path, name="journal"):
    root = rs.open_journal_root(tmp_path / name, create=True)
    assert isinstance(root, rs.JournalRoot), root
    return root


def vector_root(tmp_path, journal, name="vector"):
    root = rs.open_journal_root(vectors.materialize(journal, tmp_path / name), create=False)
    assert isinstance(root, rs.JournalRoot), root
    return root


def open_attempt(root, attempt, run="run-1", assignment=A, limits=None):
    reservation = rs.reserve_attempt(root, rs.AttemptIdentity(assignment, ENVELOPE, run, attempt),
                                     units=rs.Units(("unit:target",), ("unit:neighbor",), SNAPSHOT),
                                     launch_digest=DIGEST, caller_context_sha256=DIGEST)
    assert isinstance(reservation, rs.Reservation), reservation
    writer = rs.open_writer(root, reservation) if limits is None else rs.open_writer(root, reservation, limits=limits)
    assert isinstance(writer, rs.AttemptWriter), writer
    return reservation, writer


def bind(reservation):
    identity = reservation.identity
    return rs.ResultBinding(identity.envelope_digest, identity.run_id, identity.attempt_id, DIGEST,
                            sha256(b"evidence:" + identity.attempt_id.encode()).hexdigest())


def finish(writer, reservation, *, events=1, reason="completed"):
    assert isinstance(writer.state("queued", worker_invocations=0), rs.ChainHead)
    assert isinstance(writer.state("running", worker_invocations=1), rs.ChainHead)
    for _ in range(events):
        assert isinstance(writer.event("output streams digested", refs=(rs.make_ref("stdout", b"o", None),
                                                                        rs.make_ref("stderr", b"e", None))),
                          rs.ChainHead)
    head = writer.terminal("finished", worker_invocations=1, termination=rs.Termination(reason, None, "worker"),
                           refusal=None, result_binding=bind(reservation))
    assert isinstance(head, rs.ChainHead), head
    writer.close()
    return head


def refuse(writer):
    writer.state("queued", worker_invocations=0)
    head = writer.terminal("refused", worker_invocations=0, termination=None,
                           refusal=rs.TerminalRefusal("constraint_unsupported", "network_denial", None),
                           result_binding=None)
    assert isinstance(head, rs.ChainHead), head
    writer.close()


def tear(root, attempt):
    with open(sorted((root.path / "attempts" / attempt).glob("*.jsonl"))[-1], "ab") as handle:
        handle.write(b'{"torn":')


def request(digest=A, size=2, cursor=None):
    return rfc8785.dumps({"assignment_digest": digest, "page_size": size, "cursor": cursor})


def present(identity, ref):
    return "present"


def page(m, root, digest=A, size=2, cursor=None, evidence=present):
    result = m.read_page(root, request(digest, size, cursor), evidence=evidence)
    assert isinstance(result, m.PageResult), result
    return result


def display_of(codes):
    if not codes:
        return "current"
    return "stale" if codes == ("projection_behind_journal",) else "refused"


# --------------------------------------------------------------------------
# Pinned vectors through production entries
# --------------------------------------------------------------------------

def projection_witness(m, tmp_path, case_id):
    item, value = vectors.case(case_id), vectors.expand(case_id)
    root = vector_root(tmp_path, value["journal"])
    codes = m.check_projection(value["projection"], root)
    assert codes == tuple(sorted(item["expected"])), (case_id, codes)
    if item.get("expected_effect"):
        assert display_of(codes) == item["expected_effect"]["display"]
    if item["role"] == "control":
        result = m.project_assignment(root, value["projection"]["assignment_digest"])
        assert result.projection == value["projection"]
        assert result.unknown_attempts == () and result.diagnostics == ()


@pytest.mark.parametrize("case_id", vectors.ids("projection"))
def test_projection_vector(tmp_path, case_id):
    projection_witness(production, tmp_path, case_id)


def liveness_witness(m, tmp_path, case_id):
    item, value = vectors.case(case_id), vectors.expand(case_id)
    root = vector_root(tmp_path, value["journal"])
    calls = []

    def observer(pid):
        calls.append(pid)
        return value["liveness"]["observed_live"], value["liveness"]["observed_start_time"]

    status = m.attempt_status(root, "attempt-1", observer=observer)
    assert status.diagnostics == tuple(item["expected"]), (case_id, status)
    assert [status.display] == item["expected_effect"]["display"]
    assert calls == [4242] and status.state == "running"


@pytest.mark.parametrize("case_id", vectors.ids("liveness"))
def test_liveness_vector(tmp_path, case_id):
    liveness_witness(production, tmp_path, case_id)


def reader_view_witness(m, tmp_path, case_id):
    item, view = vectors.case(case_id), vectors.expand(case_id)
    assert m.check_reader_view(view) == tuple(sorted(item["expected"]))
    root = vector_root(tmp_path, vectors.expand("V-two-attempts")["journal"])
    status = m.attempt_status(root, view["run_record"]["attempt"]["attempt_id"])
    built = m.build_reader_view(view["row"], status, work_outcome=view["display"]["work_outcome"],
                                evidence=view["display"]["evidence"])
    if item["expected"]:
        assert built == rs.JournalRefused(item["expected"][0])
    else:
        assert built == view


@pytest.mark.parametrize("case_id", vectors.ids("reader_view"))
def test_reader_view_vector(tmp_path, case_id):
    reader_view_witness(production, tmp_path, case_id)


def page_vector_witness(m, case_id):
    item, value = vectors.case(case_id), vectors.expand(case_id)
    assert m.check_page(value["request"], value["page"]) == tuple(item["expected"])


@pytest.mark.parametrize("case_id", vectors.ids("page"))
def test_page_vector(tmp_path, case_id):
    page_vector_witness(production, case_id)
    value = vectors.expand(case_id)
    if case_id in ("RC25-no-page-size", "RC25-over-bound"):
        root = vector_root(tmp_path, vectors.expand("V-two-attempts")["journal"])
        assert production.read_page(root, rfc8785.dumps(value["request"]), evidence=present) == rs.JournalRefused(
            "read_unbounded")


def page_rederive_witness(m, tmp_path):
    value = vectors.expand("V-page")
    root = vector_root(tmp_path, {"attempts": vectors.expand("V-two-attempts")["journal"]["attempts"][:1]})
    first = m.read_page(root, rfc8785.dumps(value["request"]), evidence=present)
    assert isinstance(first, m.PageResult)
    assert first.page == value["page"] and first.diagnostics == () and first.next_cursor is not None
    calls = []
    second = m.read_page(root, rfc8785.dumps(dict(value["request"], cursor=first.next_cursor)),
                         evidence=lambda identity, ref: calls.append((identity, ref)) or "present")
    assert [event["seq"] for event in second.page["events"]] == [4, 5]
    assert second.page["has_more"] is False and second.next_cursor is None
    assert second.page["omitted"] == {"before": 4, "after": 0, "retention_dropped": 0}
    assert [ref.kind for _, ref in calls] == ["proposal_bytes", "stdout"]
    assert all(isinstance(identity, rs.AttemptIdentity) and isinstance(ref, rs.Ref) for identity, ref in calls)


def test_page_vector_rederived_through_read_page(tmp_path):
    page_rederive_witness(production, tmp_path)


def test_bounds_match_pinned_schema():
    bounds = vectors.schema()["x-journal-rules"]["bounds"]
    assert bounds["page_size_max"] == production.PAGE_SIZE_MAX
    assert bounds["attempts_per_page_max"] == production.ATTEMPTS_PER_PAGE_MAX
    assert production.RUNTIME_STATES == (
        "queued", "running", "cancelling", "finished (completed)", "finished (cancelled)", "finished (timed_out)",
        "finished (failed_to_start)", "refused", "unknown", "stale_unknown")
    assert production.LOCAL_CODES.isdisjoint(rs.PUBLIC_CODES)


def test_module_has_no_filesystem_primitive():
    from launch_audit_hook import static_references
    source = Path(production.__file__).read_text()
    assert dict(static_references(source)) == {}
    assert "supervised_contracts" not in source


# --------------------------------------------------------------------------
# Ordering and latest attempt
# --------------------------------------------------------------------------

def order_witness(m, tmp_path):
    journal = vectors.expand("V-two-attempts")["journal"]
    early, late = journal["attempts"]
    for line in late["segments"][0]["lines"]:
        line["observed_at"] = "2026-12-31T00:00:00Z"
    journal["attempts"] = [late, early]
    root = vector_root(tmp_path, journal)
    for path in (root.path / "attempts/attempt-2").iterdir():
        os.utime(path, (2_000_000_000, 2_000_000_000))
    for path in (root.path / "attempts/attempt-1").iterdir():
        os.utime(path, (1_000_000_000, 1_000_000_000))
    digest = journal["attempts"][0]["segments"][0]["lines"][0]["attempt"]["assignment_digest"]
    result = m.project_assignment(root, digest)
    assert [item["attempt"]["attempt_id"] for item in result.projection["attempts"]] == ["attempt-2", "attempt-1"]
    assert m.check_projection(result.projection, root) == ()
    events = page(m, root, digest, size=100).page["events"]
    assert [event["attempt"]["attempt_id"] for event in events][:4] == ["attempt-2"] * 4


def test_admission_order_defeats_lexical_mtime_and_observed_at(tmp_path):
    order_witness(production, tmp_path)


def latest_witness(m, tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1")
    finish(writer, reservation)
    cached = m.project_assignment(root, A).projection
    assert [item["attempt"]["attempt_id"] for item in cached["attempts"]] == ["attempt-1"]
    _, writer = open_attempt(root, "attempt-2")
    writer.state("queued", worker_invocations=0)
    writer.close()
    tear(root, "attempt-2")
    result = m.project_assignment(root, A)
    assert result.projection is None
    assert result.unknown_attempts == (("attempt-2", ("journal_torn_line",)),)
    assert result.diagnostics == ("journal_torn_line",)
    assert m.check_projection(cached, root) == ("projection_behind_journal",)
    assert m.attempt_status(root, "attempt-2").display == "unknown"


def test_unknown_latest_attempt_never_falls_back(tmp_path):
    latest_witness(production, tmp_path)


def test_unknown_earlier_attempt_is_listed_separately(tmp_path):
    root = make_root(tmp_path)
    for attempt in ("attempt-1", "attempt-2"):
        reservation, writer = open_attempt(root, attempt)
        finish(writer, reservation)
    tear(root, "attempt-1")
    result = production.project_assignment(root, A)
    assert [item["attempt"]["attempt_id"] for item in result.projection["attempts"]] == ["attempt-2"]
    assert result.unknown_attempts == (("attempt-1", ("journal_torn_line",)),)
    assert production.check_projection(result.projection, root) == ()
    reserved = rs.reserve_attempt(root, rs.AttemptIdentity(A, ENVELOPE, "run-1", "attempt-3"),
                                  units=rs.Units(("unit:target",), (), SNAPSHOT), launch_digest=DIGEST,
                                  caller_context_sha256=DIGEST)
    assert isinstance(reserved, rs.Reservation)
    pending = production.project_assignment(root, A)
    assert pending.projection is None and pending.unknown_attempts[-1] == ("attempt-3", ("journal_missing",))


def test_index_defect_has_no_projection(tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1")
    finish(writer, reservation)
    cached = production.project_assignment(root, A).projection
    with open(root.path / "assignments" / A / "index.jsonl", "ab") as handle:
        handle.write(b"{")
    result = production.project_assignment(root, A)
    assert result == production.ProjectionResult(None, (), ("index_unverifiable",))
    assert production.check_projection(cached, root) == ("projection_not_from_journal",)


# --------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------

def test_cached_projection_is_stale_or_refused_never_current(tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1", limits=rs.JournalLimits(segment_max_lines=3))
    writer.state("queued", worker_invocations=0)
    writer.state("running", worker_invocations=1)
    writer.event("worker process started")
    early = production.project_assignment(root, A).projection
    assert production.check_projection(early, root) == ()
    writer.event("output streams digested")
    middle = production.project_assignment(root, A).projection
    writer.terminal("finished", worker_invocations=1, termination=rs.Termination("timed_out", "SIGKILL", "harness"),
                    refusal=None, result_binding=bind(reservation))
    writer.close()
    for cached in (early, middle):
        assert production.check_projection(cached, root) == ("projection_behind_journal",)
    current = production.project_assignment(root, A).projection
    assert production.check_projection(current, root) == ()
    item = current["attempts"][0]

    def variant(**changes):
        return dict(current, attempts=[dict(item, **changes)])

    refusals = [variant(journal_seq=item["journal_seq"] + 1), variant(segment_sha256="0" * 64),
                variant(state="running"), variant(segment_index=item["segment_index"] + 1),
                variant(attempt=dict(item["attempt"], run_id="run-9")),
                dict(early, attempts=[dict(early["attempts"][0], segment_sha256="1" * 64)]),
                dict(current, assignment_digest=B, attempts=[dict(item, attempt=dict(item["attempt"], assignment_digest=B))]),
                dict(current, attempts=[item, item]), dict(current, schema="other"), {"attempts": []}, "text"]
    for supplied in refusals:
        assert production.check_projection(supplied, root) == ("projection_not_from_journal",), supplied
    assert production.check_projection(dict(current, attempts=[]), root) == ("projection_behind_journal",)


def test_behind_row_state_is_checked_against_the_replay(tmp_path):
    """Review case: a queued capture, a later running append, and an edited cached state."""
    root = make_root(tmp_path)
    _, writer = open_attempt(root, "attempt-1")
    writer.state("queued", worker_invocations=0)
    cached = production.project_assignment(root, A).projection
    assert cached["attempts"][0]["state"] == "queued"
    writer.state("running", worker_invocations=1)
    assert production.check_projection(cached, root) == ("projection_behind_journal",)
    for state in ("refused", "running", "finished", "cancelling"):
        forged = json.loads(json.dumps(cached))
        forged["attempts"][0]["state"] = state
        assert production.check_projection(forged, root) == ("projection_not_from_journal",), state
    # A behind row anchored to the full current segment digest carries the current state.
    current = production.project_assignment(root, A).projection
    anchored = json.loads(json.dumps(current))
    anchored["attempts"][0]["journal_seq"] -= 1
    assert production.check_projection(anchored, root) == ("projection_behind_journal",)
    anchored["attempts"][0]["state"] = "queued"
    assert production.check_projection(anchored, root) == ("projection_not_from_journal",)
    writer.close()


def test_projection_attempt_order_must_follow_index(tmp_path):
    root = make_root(tmp_path)
    for attempt in ("attempt-1", "attempt-2"):
        reservation, writer = open_attempt(root, attempt)
        finish(writer, reservation)
    current = production.project_assignment(root, A).projection
    swapped = dict(current, attempts=list(reversed(current["attempts"])))
    assert production.check_projection(swapped, root) == ("projection_not_from_journal",)


# --------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------

LIVE = (
    "import sys; sys.path.insert(0, sys.argv[1])\nfrom pathlib import Path\n"
    "from phase_loop_runtime import run_status as rs\n"
    "root = rs.open_journal_root(Path(sys.argv[2]), create=False)\n"
    "r = rs.reserve_attempt(root, rs.AttemptIdentity(sys.argv[3], sys.argv[4], 'run-1', 'attempt-1'),"
    " units=rs.Units(('unit:target',), (), sys.argv[4]), launch_digest=sys.argv[4], caller_context_sha256=sys.argv[4])\n"
    "w = rs.open_writer(root, r); w.state('queued', worker_invocations=0); w.state('running', worker_invocations=1)\n"
    "print('running', flush=True)\nsys.stdin.read()\n")


def test_killed_subprocess_writer_reads_stale_unknown(tmp_path):
    root = make_root(tmp_path)
    process = subprocess.Popen([sys.executable, "-I", "-c", LIVE, SRC, root.path, A, ENVELOPE], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "running"
        live = production.attempt_status(root, "attempt-1")
        assert (live.display, live.diagnostics, live.state) == ("running", (), "running")
        assert rs.read_attempt(root, "attempt-1").writer.owner_pid == process.pid
        os.kill(process.pid, signal.SIGKILL)
    finally:
        process.wait(timeout=60)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
    assert process.returncode == -signal.SIGKILL
    status = production.attempt_status(root, "attempt-1")
    assert (status.display, status.diagnostics, status.state) == ("stale_unknown", ("owner_not_live",), "running")
    assert production.proc_observer(process.pid) == (False, None)


def test_pid_reuse_and_observer_failures_are_stale(tmp_path):
    root = make_root(tmp_path)
    _, writer = open_attempt(root, "attempt-1")
    writer.state("queued", worker_invocations=0)
    assert production.attempt_status(root, "attempt-1").display == "queued"
    writer.state("running", worker_invocations=1)
    writer.state("cancelling", worker_invocations=1)
    assert production.attempt_status(root, "attempt-1").display == "cancelling"
    me = rs.process_start_identity(os.getpid())
    assert production.proc_observer(os.getpid()) == (True, me)
    # A reused pid has a later start tick; another live process may share ours.
    prefix, ticks = me.rsplit(":", 1)
    other = f"{prefix}:{int(ticks) + 1}"

    def boom(pid):
        raise RuntimeError("observer failure")

    for observer in (lambda pid: (True, other), lambda pid: (True, "linux-proc:x:1"), lambda pid: (True, None),
                     lambda pid: (False, me), boom, lambda pid: "yes", lambda pid: (1, me)):
        status = production.attempt_status(root, "attempt-1", observer=observer)
        assert (status.display, status.diagnostics) == ("stale_unknown", ("owner_not_live",))
    writer.close()


def test_terminal_attempts_never_consult_the_observer(tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1")
    finish(writer, reservation, reason="cancelled")
    calls = []
    status = production.attempt_status(root, "attempt-1", observer=lambda pid: calls.append(pid) or (False, None))
    assert calls == [] and status.display == "finished (cancelled)"


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def running_attempt(root, attempt="attempt-1", events=3, run="run-1"):
    reservation, writer = open_attempt(root, attempt, run=run)
    writer.state("queued", worker_invocations=0)
    writer.state("running", worker_invocations=1)
    for _ in range(events):
        writer.event("output streams digested", refs=(rs.make_ref("stdout", b"o", None),))
    return reservation, writer


@pytest.mark.parametrize("size,expected", [(0, "page_size_invalid"), (1, 1), (100, 5), (101, "read_unbounded"),
                                           (None, "read_unbounded")])
def test_page_size_bounds(tmp_path, size, expected):
    root = make_root(tmp_path)
    _, writer = running_attempt(root)
    result = production.read_page(root, request(size=size), evidence=present)
    writer.close()
    if isinstance(expected, str):
        assert result == rs.JournalRefused(expected)
        return
    assert len(result.page["events"]) == expected
    assert result.page["has_more"] is (expected < 5) and (result.next_cursor is not None) is (expected < 5)
    assert all(event["line_kind"] != "header" for event in result.page["events"])
    assert result.page["omitted"]["before"] == 1


def attempt_bound_witness(m, tmp_path):
    root = make_root(tmp_path)
    for number in range(25):
        _, writer = open_attempt(root, f"attempt-{number:02d}", run=f"run-{number:02d}")
        refuse(writer)
    first = page(m, root, size=100)
    attempts = [event["attempt"]["attempt_id"] for event in first.page["events"]]
    assert len(first.page["events"]) == 40 and len(set(attempts)) == 20 and attempts[-1] == "attempt-19"
    assert first.page["has_more"] is True and first.next_cursor is not None
    assert first.page["omitted"] == {"before": 1, "after": 15, "retention_dropped": 0}
    second = page(m, root, size=100, cursor=first.next_cursor)
    assert len(second.page["events"]) == 10 and second.page["has_more"] is False and second.next_cursor is None
    assert second.page["omitted"] == {"before": 61, "after": 0, "retention_dropped": 0}


def test_page_spans_at_most_twenty_attempts(tmp_path):
    attempt_bound_witness(production, tmp_path)


def continuation_witness(m, tmp_path):
    root = make_root(tmp_path)
    _, writer = running_attempt(root, events=1)
    first = page(m, root, size=2)
    assert [event["seq"] for event in first.page["events"]] == [1, 2] and first.page["has_more"] is True
    assert first.next_cursor is not None
    writer.event("worker process started")
    writer.close()
    _, other = open_attempt(root, "attempt-2")
    refuse(other)
    second = page(m, root, size=2, cursor=first.next_cursor)
    assert [event["seq"] for event in second.page["events"]] == [3, 4]
    assert second.page["has_more"] is True and second.next_cursor is not None
    third = page(m, root, size=2, cursor=second.next_cursor)
    assert [(e["attempt"]["attempt_id"], e["seq"]) for e in third.page["events"]] == [("attempt-2", 1), ("attempt-2", 2)]
    assert third.page["has_more"] is False and third.next_cursor is None
    assert third.page["omitted"] == {"before": 6, "after": 0, "retention_dropped": 0}


def test_cursor_continues_after_further_appends(tmp_path):
    continuation_witness(production, tmp_path)


def retention_witness(m, tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1")
    finish(writer, reservation, events=3)
    seen = []

    def resolver(identity, ref):
        seen.append((identity, ref))
        return "retention_dropped" if ref.kind == "stdout" else "present"

    result = page(m, root, size=100, evidence=resolver)
    assert result.page["omitted"]["retention_dropped"] == 3 and result.diagnostics == ()
    assert len(seen) == 6 and all(identity == reservation.identity for identity, _ in seen)
    unknown = page(m, root, size=100, evidence=lambda identity, ref: "unknown" if ref.kind == "stderr" else "present")
    assert unknown.diagnostics == ("evidence_unknown",) and unknown.page["omitted"]["retention_dropped"] == 0


def test_retention_dropped_counts_go_through_the_resolver(tmp_path):
    retention_witness(production, tmp_path)


def test_resolver_failures_are_unknown(tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1")
    finish(writer, reservation)

    def boom(identity, ref):
        raise RuntimeError("resolver failure")

    for resolver in (boom, lambda identity, ref: "gone", lambda identity, ref: None):
        assert page(production, root, size=100, evidence=resolver).diagnostics == ("evidence_unknown",)
    assert production.read_page(root, request(size=100), evidence=None) == rs.JournalRefused("evidence_unknown")


def recode(cursor, **changes):
    body = cursor[4:]
    value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    value.update(changes)
    return "rs1." + base64.urlsafe_b64encode(rfc8785.dumps(value)).decode().rstrip("=")


def cursor_binding_witness(m, tmp_path):
    root = make_root(tmp_path)
    _, writer = running_attempt(root)
    cursor = page(m, root, size=1).next_cursor
    writer.close()
    assert isinstance(m.read_page(root, request(cursor=cursor), evidence=present), m.PageResult)
    tampered = recode(cursor, index_prefix_sha256="0" * 64)
    assert m.read_page(root, request(cursor=tampered), evidence=present) == rs.JournalRefused("cursor_invalid")


def test_cursor_tamper_foreign_and_range_refused(tmp_path):
    cursor_binding_witness(production, tmp_path)
    root = rs.open_journal_root(tmp_path / "journal", create=False)
    cursor = page(production, root, size=1).next_cursor
    _, other = open_attempt(root, "attempt-b", "run-b", B)
    refuse(other)
    foreign = page(production, root, B, size=1).next_cursor
    body = cursor[4:]
    flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
    bad = ["rs2." + body, "rs1." + body + "==", "rs1." + flipped, "rs1.!", "rs1." + "A" * 600, foreign,
           recode(cursor, index_seq=1), recode(cursor, seq=999), recode(cursor, seq=-1),
           recode(cursor, assignment_digest=B), recode(cursor, extra=1)]
    for value in bad:
        assert production.read_page(root, request(cursor=value), evidence=present) == rs.JournalRefused(
            "cursor_invalid"), value


@pytest.mark.parametrize("raw", [b"{", b"[]", rfc8785.dumps({"assignment_digest": A, "page_size": 2}),
                                 rfc8785.dumps({"assignment_digest": A, "page_size": "2", "cursor": None}),
                                 rfc8785.dumps({"assignment_digest": A, "page_size": 2.5, "cursor": None}),
                                 b'{"assignment_digest":"' + A.encode() + b'","page_size":2,"page_size":3,"cursor":null}',
                                 "text"])
def test_malformed_page_request_refused(tmp_path, raw):
    root = make_root(tmp_path)
    assert production.read_page(root, raw, evidence=present) == rs.JournalRefused("page_request_invalid")


def test_unknown_attempts_contribute_no_lines(tmp_path):
    root = make_root(tmp_path)
    for attempt in ("attempt-1", "attempt-2", "attempt-3"):
        reservation, writer = open_attempt(root, attempt)
        finish(writer, reservation)
    tear(root, "attempt-2")
    result = page(production, root, size=100)
    assert {event["attempt"]["attempt_id"] for event in result.page["events"]} == {"attempt-1", "attempt-3"}
    assert result.diagnostics == ("journal_torn_line",)
    with open(root.path / "assignments" / A / "index.jsonl", "ab") as handle:
        handle.write(b"{")
    assert production.read_page(root, request(size=100), evidence=present) == rs.JournalRefused("index_unverifiable")


def test_check_page_structure():
    assert production.check_page({"page_size": 1}, {}) == ("page_request_invalid",)
    good = vectors.expand("V-page")
    assert production.check_page(good["request"], {"events": []}) == ("page_invalid",)
    assert production.check_page(dict(good["request"], page_size=1), good["page"]) == ("read_unbounded",)
    assert production.check_page(dict(good["request"], page_size=0), good["page"]) == (
        "page_size_invalid", "read_unbounded")
    assert production.check_page(good["request"], dict(good["page"], has_more=None)) == ("read_unbounded",)


def synthetic_history(tmp_path, attempts, lines):
    """A large, valid single-segment history written straight to disk (no writer fsyncs)."""
    writer = {"harness_id": "example-harness", "harness_version": "1", "writer_instance_id": "w",
              "owner_pid": 4242, "process_start_time": "t"}
    journal = {"attempts": []}
    for number in range(attempts):
        identity = {"assignment_digest": A, "envelope_digest": ENVELOPE, "run_id": f"run-{number}",
                    "attempt_id": f"attempt-{number:03d}"}
        base = {"schema": "supervised_run_status.v1", "version": "1", "attempt": identity,
                "units": {"target_unit_ids": ["unit:target"], "readonly_neighbor_unit_ids": [], "snapshot_ref": SNAPSHOT},
                "writer": writer, "observed_at": "2026-11-09T00:00:00Z",
                "redaction_posture": "digests_and_repo_relative_locators_only"}
        bodies = [{"body_kind": "header", "segment_index": 0, "previous_segment_sha256": None, "previous_last_seq": None},
                  {"body_kind": "state", "state": "queued", "worker_invocations": 0},
                  {"body_kind": "state", "state": "running", "worker_invocations": 1}]
        bodies += [{"body_kind": "event", "message": {"label": "untrusted_display_text", "text": "output streams digested"},
                    "refs": [{"kind": "stdout", "sha256": sha256(f"{number}:{n}".encode()).hexdigest(), "locator": None}]}
                   for n in range(lines - 4)]
        bodies.append({"body_kind": "terminal", "state": "finished", "worker_invocations": 1,
                       "termination": {"reason": "completed", "signal": None, "by": "worker"}, "refusal": None,
                       "result_binding": {"envelope_digest": ENVELOPE, "run_id": f"run-{number}",
                                          "attempt_id": identity["attempt_id"], "proposal_bytes_digest": None,
                                          "evidence_envelope_digest": sha256(f"evidence:{number}".encode()).hexdigest()}})
        journal["attempts"].append({"segments": [{"lines": [dict(base, line_kind=body["body_kind"], seq=seq, body=body)
                                                            for seq, body in enumerate(bodies)]}]})
    root = vector_root(tmp_path, journal, "history")
    size = sum(path.stat().st_size for path in (root.path / "attempts").rglob("*.jsonl"))
    return root, size


def test_read_page_memory_is_bounded_on_a_large_history(tmp_path):
    import gc
    import tracemalloc
    root, size = synthetic_history(tmp_path, 30, 300)
    assert size > 5_000_000
    gc.collect()
    tracemalloc.start()
    try:
        first = page(production, root, size=10)
        middle = page(production, root, size=10, cursor=recode(first.next_cursor, index_seq=15, seq=150,
                                                               index_prefix_sha256=rs.read_index(root, A).entries[15].entry_sha256))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [event["seq"] for event in first.page["events"]] == list(range(1, 11))
    assert first.page["omitted"] == {"before": 1, "after": 30 * 300 - 11, "retention_dropped": 0}
    assert [event["seq"] for event in middle.page["events"]] == list(range(151, 161))
    assert middle.page["omitted"] == {"before": 15 * 300 + 151, "after": 30 * 300 - (15 * 300 + 161),
                                      "retention_dropped": 0}
    # Retaining the decoded history would cost several times its on-disk size.
    assert peak < 3 * 1024 * 1024 and peak < size // 2, (peak, size)


def test_streaming_reads_load_the_index_once_and_never_rescan(tmp_path, monkeypatch):
    root, _ = synthetic_history(tmp_path, 12, 12)
    counts = {"index": 0, "rescan": 0, "windows": []}
    load, rescan, window = rs._load_index, rs._terminal_evidence, rs.read_attempt_window

    def counted_load(*args):
        counts["index"] += 1
        return load(*args)

    def counted_rescan(*args):
        counts["rescan"] += 1
        return rescan(*args)

    def counted_window(root, index, entry, **kwargs):
        counts["windows"].append(entry.identity.attempt_id)
        return window(root, index, entry, **kwargs)

    monkeypatch.setattr(rs, "_load_index", counted_load)
    monkeypatch.setattr(rs, "_terminal_evidence", counted_rescan)
    monkeypatch.setattr(rs, "read_attempt_window", counted_window)
    every = [f"attempt-{number:03d}" for number in range(12)]

    def observed():
        seen = dict(counts, windows=list(counts["windows"]))
        counts.update(index=0, rescan=0, windows=[])
        return seen

    result = page(production, root, size=100)
    assert len(result.page["events"]) == 100 and result.page["has_more"] is True
    assert observed() == {"index": 1, "rescan": 0, "windows": every}
    projection = production.project_assignment(root, A)
    assert len(projection.projection["attempts"]) == 12
    assert observed() == {"index": 1, "rescan": 0, "windows": every}
    assert production.check_projection(projection.projection, root) == ()
    assert observed() == {"index": 1, "rescan": 0, "windows": every}


def rotated_history(tmp_path, attempts, events, per_segment=4):
    """A valid multi-segment history (rotation every ``per_segment`` lines), written straight to disk."""
    writer = {"harness_id": "example-harness", "harness_version": "1", "writer_instance_id": "w",
              "owner_pid": 4242, "process_start_time": "t"}
    journal = {"attempts": []}
    for number in range(attempts):
        identity = {"assignment_digest": A, "envelope_digest": ENVELOPE, "run_id": f"run-{number}",
                    "attempt_id": f"attempt-{number:03d}"}
        base = {"schema": "supervised_run_status.v1", "version": "1", "attempt": identity,
                "units": {"target_unit_ids": ["unit:target"], "readonly_neighbor_unit_ids": [], "snapshot_ref": SNAPSHOT},
                "writer": writer, "observed_at": "2026-11-09T00:00:00Z",
                "redaction_posture": "digests_and_repo_relative_locators_only"}
        bodies = [{"body_kind": "state", "state": "queued", "worker_invocations": 0},
                  {"body_kind": "state", "state": "running", "worker_invocations": 1}]
        bodies += [{"body_kind": "event", "message": {"label": "untrusted_display_text", "text": "output streams digested"},
                    "refs": [{"kind": "stdout", "sha256": sha256(f"{number}:{n}".encode()).hexdigest(), "locator": None}]}
                   for n in range(events)]
        bodies.append({"body_kind": "terminal", "state": "finished", "worker_invocations": 1,
                       "termination": {"reason": "completed", "signal": None, "by": "worker"}, "refusal": None,
                       "result_binding": {"envelope_digest": ENVELOPE, "run_id": f"run-{number}",
                                          "attempt_id": identity["attempt_id"], "proposal_bytes_digest": None,
                                          "evidence_envelope_digest": sha256(f"evidence:{number}".encode()).hexdigest()}})
        segments, seq, previous, last = [], 0, None, None
        for start in range(0, len(bodies), per_segment - 1):
            header = {"body_kind": "header", "segment_index": len(segments), "previous_segment_sha256": previous,
                      "previous_last_seq": last}
            lines = []
            for body in [header, *bodies[start:start + per_segment - 1]]:
                lines.append(dict(base, line_kind=body["body_kind"], seq=seq, body=body))
                seq += 1
            segment = {"lines": lines}
            segments.append(segment)
            previous, last = sha256(vectors.segment_bytes(segment)).hexdigest(), seq - 1
        journal["attempts"].append({"segments": segments})
    root = vector_root(tmp_path, journal, "history")
    files = list((root.path / "attempts").rglob("*.jsonl"))
    return root, sum(path.stat().st_size for path in files), len(files)


def measured(call):
    import gc
    import tracemalloc
    gc.collect()
    tracemalloc.start()
    try:
        result = call()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, peak


def test_projection_and_page_memory_do_not_grow_with_segment_count(tmp_path):
    peaks = {}
    for name, events in (("small", 30), ("large", 330)):
        (tmp_path / name).mkdir(mode=0o700)
        root, size, segments = rotated_history(tmp_path / name, 8, events)
        result, project_peak = measured(lambda: production.project_assignment(root, A))
        assert result.diagnostics == () and len(result.projection["attempts"]) == 8
        # A behind row naming its tail segment's digest exercises the digest comparison.
        cached = json.loads(json.dumps(result.projection))
        cached["attempts"][0]["journal_seq"] -= 1
        codes, check_peak = measured(lambda: production.check_projection(cached, root))
        assert codes == ("projection_behind_journal",)
        current, current_peak = measured(lambda: production.check_projection(result.projection, root))
        assert current == ()
        listing, page_peak = measured(lambda: page(production, root, size=10))
        assert len(listing.page["events"]) == 10
        peaks[name] = {"segments": segments, "size": size,
                       "peaks": (project_peak, check_peak, current_peak, page_peak)}
    small, large = peaks["small"], peaks["large"]
    assert large["segments"] >= 8 * small["segments"] and large["size"] > 2_000_000
    for before, after in zip(small["peaks"], large["peaks"]):
        # Retaining per-segment metadata or lines would grow with the segment count.
        assert after < before + 64 * 1024 and after < 1024 * 1024, peaks


# --------------------------------------------------------------------------
# Reader views
# --------------------------------------------------------------------------

def statuses(tmp_path):
    root = make_root(tmp_path)
    out = {}
    for reason in ("completed", "cancelled", "timed_out", "failed_to_start"):
        reservation, writer = open_attempt(root, f"finished-{reason}", run=f"run-{reason}")
        finish(writer, reservation, reason=reason)
        out[reason] = production.attempt_status(root, f"finished-{reason}")
    _, writer = open_attempt(root, "refused-1", run="run-refused")
    refuse(writer)
    out["refused"] = production.attempt_status(root, "refused-1")
    _, writer = running_attempt(root, "running-1", run="run-running")
    out["running"] = production.attempt_status(root, "running-1")
    out["stale"] = production.attempt_status(root, "running-1", observer=lambda pid: (False, None))
    writer.close()
    _, writer = open_attempt(root, "queued-1", run="run-queued")
    writer.state("queued", worker_invocations=0)
    out["queued"] = production.attempt_status(root, "queued-1")
    writer.close()
    out["unknown"] = production.attempt_status(root, "absent-1")
    return root, out


ROW = {"assignment_digest": A, "snapshot_ref": SNAPSHOT}


def test_runtime_state_comes_from_the_closed_phrase_set(tmp_path):
    _, found = statuses(tmp_path)
    assert {key: status.display for key, status in found.items()} == {
        "completed": "finished (completed)", "cancelled": "finished (cancelled)",
        "timed_out": "finished (timed_out)", "failed_to_start": "finished (failed_to_start)", "refused": "refused",
        "running": "running", "stale": "stale_unknown", "queued": "queued", "unknown": "unknown"}
    for key, status in found.items():
        view = production.build_reader_view(ROW, status)
        if key == "unknown":
            assert view == rs.JournalRefused("run_record_unknown")
            continue
        assert production.check_reader_view(view) == () and view["display"]["runtime_state"] == status.display
        assert view["run_record"]["state"] == status.state
    stale = production.build_reader_view(ROW, found["stale"])
    assert stale["run_record"]["state"] == "running" and stale["run_record"]["termination_reason"] is None
    completed = production.build_reader_view(ROW, found["completed"])
    assert completed["run_record"]["termination_reason"] == "completed" and completed["display"]["work_outcome"] is None


def phrase_witness(m, tmp_path):
    view = vectors.expand("V-reader-view")
    view["display"]["runtime_state"] = "running (healthy)"
    assert m.check_reader_view(view) == ("runtime_state_invalid",)
    root = vector_root(tmp_path, vectors.expand("V-two-attempts")["journal"])
    status = m.attempt_status(root, "attempt-2")
    forged = m.AttemptStatus(status.attempt_id, status.state, "done", status.termination, status.refusal,
                             status.result_binding, status.chain_head, (), status.identity, status.units)
    assert m.build_reader_view(view["row"], forged) == rs.JournalRefused("runtime_state_invalid")


def test_non_phrase_runtime_state_refused(tmp_path):
    phrase_witness(production, tmp_path)


def test_reader_view_input_shapes(tmp_path):
    root = vector_root(tmp_path, vectors.expand("V-two-attempts")["journal"])
    status = production.attempt_status(root, "attempt-2")
    view = vectors.expand("V-reader-view")
    assert production.build_reader_view({"assignment_digest": "x"}, status) == rs.JournalRefused("reader_view_invalid")
    assert production.build_reader_view(view["row"], status, work_outcome={"value": object()}) == rs.JournalRefused(
        "reader_view_invalid")
    assert production.build_reader_view(view["row"], "status") == rs.JournalRefused("run_record_unknown")
    assert production.check_reader_view({"row": {}}) == ("reader_view_invalid",)
    built = production.build_reader_view(view["row"], status)
    built["row"]["assignment_digest"] = B
    assert production.build_reader_view(view["row"], status)["row"] == view["row"]


# --------------------------------------------------------------------------
# Secrecy and pass-through
# --------------------------------------------------------------------------

SENTINELS = (b"PROMPT-SENTINEL-7f3a", b"SOURCE-SENTINEL-91bc", b"SECRET-SENTINEL-c0de", b"ARGV-SENTINEL-5e11")


def test_sentinels_never_reach_projections_statuses_pages_or_views(tmp_path):
    root = make_root(tmp_path)
    reservation, writer = open_attempt(root, "attempt-1")
    writer.state("queued", worker_invocations=0)
    writer.state("running", worker_invocations=1)
    for kind, data in zip(("stdout", "stderr", "proposal_bytes", "evidence_envelope"), SENTINELS):
        writer.event("output streams digested", refs=(rs.make_ref(kind, data + b" payload", None),))
    termination = rs.Termination("completed", None, "worker")
    binding = bind(reservation)
    writer.terminal("finished", worker_invocations=1, termination=termination, refusal=None, result_binding=binding)
    writer.close()
    status = production.attempt_status(root, "attempt-1")
    read = rs.read_attempt(root, "attempt-1")
    assert (status.termination, status.refusal, status.result_binding) == (termination, None, binding)
    assert (read.terminal.termination, read.terminal.refusal, read.terminal.result_binding) == (termination, None, binding)
    outputs = [production.project_assignment(root, A).projection, page(production, root, size=100).page,
               production.build_reader_view(ROW, status), repr(status)]
    blob = json.dumps(outputs, default=str).encode()
    for sentinel in SENTINELS:
        assert sentinel not in blob
    for data in SENTINELS:
        assert sha256(data + b" payload").hexdigest().encode() in blob


def test_refusal_passes_through_unchanged(tmp_path):
    root = make_root(tmp_path)
    _, writer = open_attempt(root, "attempt-1")
    refuse(writer)
    status = production.attempt_status(root, "attempt-1")
    assert status.refusal == rs.TerminalRefusal("constraint_unsupported", "network_denial", None)
    assert status.refusal == rs.read_attempt(root, "attempt-1").terminal.refusal and status.result_binding is None


# --------------------------------------------------------------------------
# Named mutation controls (artifact section 13, SL-1)
# --------------------------------------------------------------------------

CONTROLS = {
    "index_order": ("    for entry in index.entries:\n",
                    "    for entry in sorted(index.entries, key=lambda item: item.identity.attempt_id):\n"),
    "latest_fallback": ("if latest_unknown:", "if False:"),
    "projection_behind": ("elif seq < tail:", "elif False:"),
    "projection_ahead": ("if seq > tail:", "if False:"),
    "owner_live": ("stale = not live", "stale = False"),
    "pid_reuse": ("if start != read.writer.process_start_time:", "if False:"),
    "page_bound": ("if size is None or size > PAGE_SIZE_MAX:", "if size is None:"),
    "page_attempt_bound": ("if not prior and not closed and used == ATTEMPTS_PER_PAGE_MAX:", "if False:"),
    "header_not_event": ('_EVENT_KINDS = frozenset({"event", "state", "terminal"})',
                         '_EVENT_KINDS = frozenset({"header", "event", "state", "terminal"})'),
    "omitted_counts": ('"omitted": {"before": before, "after": pending,', '"omitted": {"before": 0, "after": 0,'),
    "retention_count": ("dropped += 1", "pass"),
    "next_cursor": ("    if has_more:\n", "    if False:\n"),
    "cursor_binding": ('if entries[index_seq].entry_sha256 != value["index_prefix_sha256"]:', "if False:"),
    "outcome_source": ('if outcome is not None and outcome["source"] != "work_result_reducer":', "if False:"),
    "row_join": ('if (row["assignment_digest"], row["snapshot_ref"]) != (',
                 'if False and (row["assignment_digest"], row["snapshot_ref"]) != ('),
    "runtime_phrase_set": ('if display["runtime_state"] not in RUNTIME_STATES:', "if False:"),
}


def mutant(monkeypatch, control):
    source = Path(production.__file__).read_text()
    fragment, replacement = CONTROLS[control]
    assert source.count(fragment) == 1, control
    name = "phase_loop_runtime._mutation_run_status_projection_" + control
    module = ModuleType(name)
    module.__file__ = production.__file__
    module.__package__ = "phase_loop_runtime"
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source.replace(fragment, replacement), production.__file__, "exec"), module.__dict__)
    return module


def page_bound_witness(m, tmp_path):
    page_vector_witness(m, "RC25-over-bound")
    root = vector_root(tmp_path, vectors.expand("V-two-attempts")["journal"])
    assert m.read_page(root, request(digest=vectors.expand("V-page")["request"]["assignment_digest"], size=101),
                       evidence=present) == rs.JournalRefused("read_unbounded")


def witness(m, control, tmp_path):
    if control == "index_order":
        order_witness(m, tmp_path)
    elif control == "latest_fallback":
        latest_witness(m, tmp_path)
    elif control in ("projection_behind", "projection_ahead"):
        projection_witness(m, tmp_path, "N16-projection-behind" if control == "projection_behind"
                           else "S-projection-ahead")
    elif control in ("owner_live", "pid_reuse"):
        liveness_witness(m, tmp_path, "N17-owner-not-live" if control == "owner_live" else "N17-pid-reused")
    elif control == "page_bound":
        page_bound_witness(m, tmp_path)
    elif control == "page_attempt_bound":
        attempt_bound_witness(m, tmp_path)
    elif control in ("header_not_event", "omitted_counts"):
        page_rederive_witness(m, tmp_path)
    elif control == "retention_count":
        retention_witness(m, tmp_path)
    elif control == "next_cursor":
        continuation_witness(m, tmp_path)
    elif control == "cursor_binding":
        cursor_binding_witness(m, tmp_path)
    elif control in ("outcome_source", "row_join"):
        reader_view_witness(m, tmp_path, "N18-completed-as-outcome" if control == "outcome_source"
                            else "RC24-foreign-assignment")
    elif control == "runtime_phrase_set":
        phrase_witness(m, tmp_path)
    else:  # pragma: no cover - every named control has a witness
        raise AssertionError(control)


def test_control_inventory_matches_artifact():
    assert list(CONTROLS) == [
        "index_order", "latest_fallback", "projection_behind", "projection_ahead", "owner_live", "pid_reuse",
        "page_bound", "page_attempt_bound", "header_not_event", "omitted_counts", "retention_count", "next_cursor",
        "cursor_binding", "outcome_source", "row_join", "runtime_phrase_set"]


@pytest.mark.parametrize("control", list(CONTROLS))
def test_production_control_witness(tmp_path, control):
    witness(production, control, tmp_path)


@pytest.mark.parametrize("control", list(CONTROLS))
def test_run_status_projection_mutation_killed(tmp_path, monkeypatch, control):
    module = mutant(monkeypatch, control)
    with pytest.raises(AssertionError):
        witness(module, control, tmp_path)
