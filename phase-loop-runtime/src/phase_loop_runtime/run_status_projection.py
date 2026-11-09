"""Replay-only projection, liveness, bounded pages and reader views (IF-0-JOURNAL-1).

Everything here is derived from ``run_status`` reads, in admission-index order,
on every call. Nothing is cached, written, watched or listened for, and this
module performs no filesystem primitive of its own. A projection is replaceable;
the journal stays authoritative. Run status is never a work outcome.

Every produced projection, page and reader view passes the closed structural
checker and its semantic checker before it is returned.
"""
from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import re

import rfc8785

from . import run_status
from .run_status import AttemptIdentity, ChainHead, JournalRefused, Ref, ResultBinding, TerminalRefusal, Termination, Units

ProcessObserver = Callable[[int], tuple[bool, str | None]]
EvidenceResolver = Callable[[AttemptIdentity, Ref], str]

PROJECTION_SCHEMA = run_status.JOURNAL_FAMILY + "/projection"
PAGE_SIZE_MAX = 100
ATTEMPTS_PER_PAGE_MAX = 20
CURSOR_PREFIX = "rs1."
#: Section 9: the only ``display.runtime_state`` text.
RUNTIME_STATES = ("queued", "running", "cancelling", "finished (completed)", "finished (cancelled)",
                  "finished (timed_out)", "finished (failed_to_start)", "refused", "unknown", "stale_unknown")
EVIDENCE_RESULTS = ("present", "retention_dropped", "unknown")
#: Local codes added by this module; none appears in a public record.
LOCAL_CODES = frozenset({"page_size_invalid", "page_request_invalid", "page_invalid", "cursor_invalid",
                         "evidence_unknown", "reader_view_invalid", "runtime_state_invalid", "run_record_unknown"})
#: Line kinds a page may return as events; headers never are.
_EVENT_KINDS = frozenset({"event", "state", "terminal"})
_CURSOR_KEYS = frozenset({"assignment_digest", "index_seq", "seq", "index_prefix_sha256"})
_CURSOR_MAX = 512


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    projection: dict | None
    unknown_attempts: tuple[tuple[str, tuple[str, ...]], ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AttemptStatus:
    attempt_id: str
    state: str | None
    display: str
    termination: Termination | None
    refusal: TerminalRefusal | None
    result_binding: ResultBinding | None
    chain_head: ChainHead | None
    diagnostics: tuple[str, ...]
    #: Additive: the indexed identity and units that ``build_reader_view``
    #: needs for the public ``run_record``; None when the attempt is unknown.
    identity: AttemptIdentity | None = None
    units: Units | None = None


@dataclass(frozen=True, slots=True)
class PageResult:
    page: dict
    next_cursor: str | None
    diagnostics: tuple[str, ...]


def _strict(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def refuse(_):
        raise ValueError()

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=refuse, parse_constant=refuse)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        return None


def _plain(value):
    """A detached JSON-shaped copy of a caller mapping, or ValueError."""
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Mapping):
        if not all(type(key) is str for key in value):
            raise ValueError()
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    raise ValueError()


def _identity_json(identity: AttemptIdentity) -> dict:
    return {"assignment_digest": identity.assignment_digest, "envelope_digest": identity.envelope_digest,
            "run_id": identity.run_id, "attempt_id": identity.attempt_id}


def _units_json(units: Units) -> dict:
    return {"target_unit_ids": list(units.target_unit_ids),
            "readonly_neighbor_unit_ids": list(units.readonly_neighbor_unit_ids), "snapshot_ref": units.snapshot_ref}


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

def _replay(root, assignment_digest, supplied=None):
    """One replay: (index diagnostics, verified, unknown), in index order.

    Each verified attempt keeps only ``(index_seq, item, known)``. ``item`` is its
    head-derived projection row. ``known`` is the verdict for the supplied row's
    segment digest and state, compared inside the streaming pass, or None when
    none was supplied. Unknown attempts keep ``(index_seq, attempt_id, diagnostics)``. No
    window, segment list or journal line outlives its attempt. There is one index
    load and one window per attempt, and no earlier attempt is rescanned.
    """
    index = run_status.read_index(root, assignment_digest)
    if index.diagnostics:
        return index.diagnostics, [], []
    verified, unknown, earlier = [], [], set()
    for entry in index.entries:
        attempt_id = entry.identity.attempt_id
        row = (supplied or {}).get(attempt_id)
        prefix = None if row is None else (row["segment_index"], row["journal_seq"])
        window = run_status.read_attempt_window(root, index, entry, earlier_evidence=earlier, prefix_at=prefix)
        if window.evidence_digest is not None:
            earlier.add(window.evidence_digest)
        if window.diagnostics or window.state is None or window.chain_head is None:
            unknown.append((entry.index_seq, attempt_id, window.diagnostics))
            continue
        head = window.chain_head
        item = {"attempt": _identity_json(entry.identity), "state": window.state, "journal_seq": head.last_seq,
                "segment_index": head.segment_index, "segment_sha256": head.segment_sha256}
        verified.append((entry.index_seq, item, None if row is None else _digest_known(window, row)))
    return (), verified, unknown


def _digest_known(window, row) -> bool:
    """A behind row is derivable from the journal: its digest and its state both match.

    A row naming the segment's prefix digest at its ``journal_seq`` is historical,
    so its state must equal the replayed state at that seq. A row naming the
    segment's full current digest is anchored to the current segment, so its state
    must equal the current state (the pinned behind vector's shape). Anything else
    is not from the journal.
    """
    summary = window.segment
    if summary is None or summary[0] != row["segment_index"]:
        return False
    _, first, last, full = summary
    if not first <= row["journal_seq"] <= last:
        return False
    if row["segment_sha256"] == window.prefix_digest:
        return row["state"] == window.prefix_state
    if row["segment_sha256"] == full:
        return row["state"] == window.state
    return False


def _compare(value: dict, replayed) -> tuple[str, ...]:
    """Compare a structurally valid projection with one replay result."""
    index_diagnostics, verified, unknown = replayed
    if index_diagnostics:
        return ("projection_not_from_journal",)
    fresh = {item["attempt"]["attempt_id"]: (position, item, known)
             for position, (_, item, known) in enumerate(verified)}
    codes, positions = set(), []
    for supplied in value["attempts"]:
        attempt_id = supplied["attempt"]["attempt_id"]
        if attempt_id not in fresh or fresh[attempt_id][0] in positions:
            codes.add("projection_not_from_journal")
            continue
        position, current, known = fresh[attempt_id]
        positions.append(position)
        if supplied["attempt"] != current["attempt"]:
            codes.add("projection_not_from_journal")
            continue
        seq, tail = supplied["journal_seq"], current["journal_seq"]
        if seq > tail:
            codes.add("projection_not_from_journal")
        elif seq < tail:
            if not known:
                codes.add("projection_not_from_journal")
            else:
                codes.add("projection_behind_journal")
        elif any(supplied[key] != current[key] for key in ("state", "segment_index", "segment_sha256")):
            codes.add("projection_not_from_journal")
    if positions != sorted(positions):
        codes.add("projection_not_from_journal")
    if len(set(positions)) < len(verified):
        codes.add("projection_behind_journal")
    if unknown and (not verified or unknown[-1][0] > verified[-1][0]):
        codes.add("projection_behind_journal")
    return tuple(sorted(codes))


def project_assignment(root, assignment_digest: str) -> ProjectionResult:
    """Replay the assignment once from its index and journals; nothing is cached."""
    replayed = _replay(root, assignment_digest)
    index_diagnostics, verified, unknown = replayed
    if index_diagnostics:
        return ProjectionResult(None, (), tuple(index_diagnostics))
    listed = tuple((attempt_id, codes) for _, attempt_id, codes in unknown)
    diagnostics = tuple(sorted({code for _, codes in listed for code in codes}))
    latest_unknown = bool(unknown) and (not verified or unknown[-1][0] > verified[-1][0])
    if latest_unknown:
        # The latest attempt is the last index entry; when it is unknown the
        # latest is unknown, and no earlier attempt stands in for it.
        return ProjectionResult(None, listed, diagnostics)
    projection = {"schema": PROJECTION_SCHEMA, "assignment_digest": assignment_digest,
                  "attempts": [item for _, item, _ in verified]}
    # The semantic check runs against the same replay, so the result is
    # validated without a second index load or a second read of any attempt.
    # The latest-unknown case is refused above; this guards derivability.
    if (not run_status.check_structure("projection", projection)
            or "projection_not_from_journal" in _compare(projection, replayed)):
        return ProjectionResult(None, listed, tuple(sorted({*diagnostics, "projection_not_from_journal"})))
    return ProjectionResult(projection, listed, diagnostics)


def check_projection(projection: Mapping, root) -> tuple[str, ...]:
    """Compare a supplied (possibly cached) projection with one fresh replay.

    ``()`` means current; ``projection_behind_journal`` is shown stale;
    ``projection_not_from_journal`` is refused.
    """
    try:
        value = _plain(projection)
    except (ValueError, RecursionError):
        return ("projection_not_from_journal",)
    if not run_status.check_structure("projection", value):
        return ("projection_not_from_journal",)
    supplied = {}
    for row in value["attempts"]:
        supplied.setdefault(row["attempt"]["attempt_id"], row)
    return _compare(value, _replay(root, value["assignment_digest"], supplied))


# --------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------

def proc_observer(pid: int) -> tuple[bool, str | None]:
    identity = run_status.process_start_identity(pid)
    return identity is not None, identity


def _observe(observer, pid) -> tuple[bool, str | None]:
    try:
        result = observer(pid)
    except Exception:
        return False, None
    if (not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not bool
            or not (result[1] is None or type(result[1]) is str)):
        return False, None
    return result


def attempt_status(root, attempt_id: str, *, observer: ProcessObserver = proc_observer) -> AttemptStatus:
    """The only per-attempt display surface; a non-terminal owner must be live."""
    read = run_status.read_attempt(root, attempt_id)
    if read.diagnostics or read.state is None or read.writer is None:
        return AttemptStatus(read.attempt_id, None, "unknown", None, None, None, None, read.diagnostics,
                             read.identity, read.units)
    terminal = read.terminal
    if terminal is not None:
        display = "refused" if terminal.state == "refused" else f"finished ({terminal.termination.reason})"
        return AttemptStatus(read.attempt_id, read.state, display, terminal.termination, terminal.refusal,
                             terminal.result_binding, read.chain_head, (), read.identity, read.units)
    live, start = _observe(observer, read.writer.owner_pid)
    stale = not live
    if start != read.writer.process_start_time:
        stale = True
    if stale:
        return AttemptStatus(read.attempt_id, read.state, "stale_unknown", None, None, None, read.chain_head,
                             ("owner_not_live",), read.identity, read.units)
    return AttemptStatus(read.attempt_id, read.state, read.state, None, None, None, read.chain_head, (),
                         read.identity, read.units)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def _request_codes(request: dict) -> tuple[str, ...]:
    size = request["page_size"]
    if size is None or size > PAGE_SIZE_MAX:
        return ("read_unbounded",)
    if size < 1:
        return ("page_size_invalid",)
    return ()


def check_page(request: Mapping, page: Mapping) -> tuple[str, ...]:
    """The public page rules for a supplied request and page."""
    try:
        request, page = _plain(request), _plain(page)
    except (ValueError, RecursionError):
        return ("page_invalid",)
    if not run_status.check_structure("page_request", request):
        return ("page_request_invalid",)
    if not run_status.check_structure("page", page):
        return ("page_invalid",)
    codes = set(_request_codes(request))
    size = request["page_size"]
    if size is not None and len(page["events"]) > size:
        codes.add("read_unbounded")
    if page["has_more"] is None or page["omitted"] is None:
        codes.add("read_unbounded")
    return tuple(sorted(codes))


def _encode_cursor(assignment_digest: str, index_seq: int, seq: int, prefix: str) -> str:
    payload = {"assignment_digest": assignment_digest, "index_seq": index_seq, "seq": seq,
               "index_prefix_sha256": prefix}
    return CURSOR_PREFIX + base64.urlsafe_b64encode(rfc8785.dumps(payload)).decode("ascii").rstrip("=")


def _decode_cursor(text, assignment_digest: str, entries) -> tuple[int, int] | None:
    if type(text) is not str or len(text) > _CURSOR_MAX or not text.startswith(CURSOR_PREFIX):
        return None
    body = text[len(CURSOR_PREFIX):]
    if re.fullmatch(r"[A-Za-z0-9_-]+", body) is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError:
        return None
    value = _strict(raw)
    if type(value) is not dict or set(value) != _CURSOR_KEYS:
        return None
    index_seq, seq = value["index_seq"], value["seq"]
    if type(index_seq) is not int or type(seq) is not int or index_seq < 0 or seq < 0:
        return None
    if type(value["assignment_digest"]) is not str or type(value["index_prefix_sha256"]) is not str:
        return None
    if _encode_cursor(value["assignment_digest"], index_seq, seq, value["index_prefix_sha256"]) != text:
        return None
    if value["assignment_digest"] != assignment_digest or index_seq >= len(entries):
        return None
    if entries[index_seq].entry_sha256 != value["index_prefix_sha256"]:
        return None
    return index_seq, seq


def _resolve(evidence, identity, ref) -> str:
    try:
        result = evidence(identity, ref)
    except Exception:
        return "unknown"
    return result if type(result) is str and result in EVIDENCE_RESULTS else "unknown"


def read_page(root, request: bytes, *, evidence: EvidenceResolver) -> PageResult | JournalRefused:
    """One bounded page of verified lines, in index order and then seq order."""
    if not callable(evidence):
        return JournalRefused("evidence_unknown")
    value = _strict(request) if type(request) is bytes else None
    if not run_status.check_structure("page_request", value):
        return JournalRefused("page_request_invalid")
    codes = _request_codes(value)
    if codes:
        return JournalRefused(codes[0])
    digest, size = value["assignment_digest"], value["page_size"]
    index = run_status.read_index(root, digest)
    if index.diagnostics:
        return JournalRefused(index.diagnostics[0])
    entries = index.entries
    start = (-1, -1)
    if value["cursor"] is not None:
        start = _decode_cursor(value["cursor"], digest, entries)
        if start is None:
            return JournalRefused("cursor_invalid")
    # Stream the attempts once, in index order. Only the selected events (at
    # most ``size``) are retained; every other verified line is only counted.
    events, owners, diagnostics, earlier = [], [], set(), set()
    before = pending = used = 0
    closed = has_more = False
    last = None
    for entry in entries:
        prior = entry.index_seq < start[0]
        after_seq = start[1] if entry.index_seq == start[0] else -1
        if not prior and not closed and used == ATTEMPTS_PER_PAGE_MAX:
            closed = True
        capacity = 0 if prior or closed else size - len(events)
        window = run_status.read_attempt_window(root, index, entry, after_seq=after_seq, max_events=capacity,
                                                earlier_evidence=earlier, event_kinds=_EVENT_KINDS)
        if window.evidence_digest is not None:
            earlier.add(window.evidence_digest)
        if window.diagnostics:
            diagnostics.update(window.diagnostics)
            continue
        if entry.index_seq == start[0] and not window.found_after_seq:
            return JournalRefused("cursor_invalid")
        if prior or not events:
            before += window.skipped + window.lead
        elif not window.events:
            pending += window.skipped + window.lead
            has_more = has_more or window.more_events
        if window.events:
            selected = [json.loads(raw) for raw in window.events]
            events.extend(selected)
            owners.extend([entry.identity] * len(selected))
            used += 1
            pending = window.tail
            last = (entry.index_seq, selected[-1]["seq"])
            if window.more_events or len(events) == size:
                closed = True
                has_more = has_more or window.more_events
    dropped = 0
    for line, identity in zip(events, owners):
        if line["line_kind"] != "event":
            continue
        for ref in line["body"]["refs"]:
            result = _resolve(evidence, identity, Ref(ref["kind"], ref["sha256"], ref["locator"]))
            if result == "retention_dropped":
                dropped += 1
            elif result != "present":
                diagnostics.add("evidence_unknown")
    page = {"events": events, "has_more": has_more,
            "omitted": {"before": before, "after": pending, "retention_dropped": dropped}}
    codes = check_page(value, page)
    if codes:
        return JournalRefused(codes[0])
    next_cursor = None
    if has_more:
        next_cursor = _encode_cursor(digest, last[0], last[1], entries[last[0]].entry_sha256)
    return PageResult(page, next_cursor, tuple(sorted(diagnostics)))


# --------------------------------------------------------------------------
# Reader view
# --------------------------------------------------------------------------

def _view_codes(view) -> tuple[str, ...]:
    if not run_status.check_structure("reader_view", view):
        return ("reader_view_invalid",)
    codes = set()
    row, record, display = view["row"], view["run_record"], view["display"]
    if (row["assignment_digest"], row["snapshot_ref"]) != (record["attempt"]["assignment_digest"],
                                                           record["units"]["snapshot_ref"]):
        codes.add("run_record_foreign")
    outcome, evidence = display["work_outcome"], display["evidence"]
    if outcome is not None and outcome["source"] != "work_result_reducer":
        codes.add("runtime_not_work_outcome")
    if evidence is not None and evidence["source"] != "requirement_admission":
        codes.add("runtime_not_work_outcome")
    if display["runtime_state"] not in RUNTIME_STATES:
        codes.add("runtime_state_invalid")
    return tuple(sorted(codes))


def check_reader_view(view: Mapping) -> tuple[str, ...]:
    try:
        return _view_codes(_plain(view))
    except (ValueError, RecursionError):
        return ("reader_view_invalid",)


def build_reader_view(row: Mapping, status: AttemptStatus, *, work_outcome=None,
                      evidence=None) -> Mapping | JournalRefused:
    """Compose the public reader view from three producers kept separate."""
    if (not isinstance(status, AttemptStatus) or status.state is None or status.identity is None
            or status.units is None):
        return JournalRefused("run_record_unknown")
    try:
        view = {"row": _plain(row),
                "run_record": {"attempt": _identity_json(status.identity), "units": _units_json(status.units),
                               "state": status.state,
                               "termination_reason": None if status.termination is None else status.termination.reason},
                "display": {"runtime_state": status.display, "work_outcome": _plain(work_outcome),
                            "evidence": _plain(evidence)}}
    except (ValueError, RecursionError, AttributeError):
        return JournalRefused("reader_view_invalid")
    codes = _view_codes(view)
    if codes:
        return JournalRefused(codes[0])
    return view


__all__ = [
    "ProcessObserver", "EvidenceResolver", "ProjectionResult", "AttemptStatus", "PageResult", "RUNTIME_STATES",
    "PAGE_SIZE_MAX", "ATTEMPTS_PER_PAGE_MAX", "LOCAL_CODES", "project_assignment", "check_projection",
    "attempt_status", "read_page", "check_page", "build_reader_view", "check_reader_view", "proc_observer",
]
