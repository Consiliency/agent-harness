"""agent-harness#789: an older runtime reading a newer broker store must REFUSE, not crash.

The incident opened with an installed runtime reading a store written by a newer one and
dying with `TypeError: AdmissionRecord.__init__() got an unexpected keyword argument
'binding'` — an optional field the old reader did not know. That happened BEFORE the
adapter was reached, and the run went on to leave a permanently blocked partition.

The ADMISSION store was hardened for it. Its sibling EVIDENCE store, whose replay was the
identical `Record(**raw)` construct, was not — so the same incident remained reachable one
module over, and would fire the moment anyone added an optional field to EvidenceRecord.
"""
from __future__ import annotations

import json

import pytest

from phase_loop_runtime.convergence.broker.evidence import (
    BrokerEvidenceStore,
    EvidenceStoreIncompatible,
)


def _store(tmp_path):
    store = BrokerEvidenceStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    return store


def _line(**overrides):
    record = {
        "idempotency_key": "key-1",
        "state": "effect_terminal_observed",
        "evidence_reference": "https://example.invalid/pr/1",
    }
    record.update(overrides)
    return json.dumps(record)


def _written_by_a_newer_runtime(tmp_path, field="future_diagnostic"):
    """A record carrying a field this runtime's EvidenceRecord does not declare."""
    store = _store(tmp_path)
    store.path.write_text(_line(**{field: "payload retained by a newer writer"}) + "\n")
    return store


def test_an_unknown_field_refuses_with_a_typed_error_not_a_TypeError(tmp_path):
    """The exact ah#789 shape, one module over."""
    store = _written_by_a_newer_runtime(tmp_path)
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert not isinstance(caught.value, TypeError)


def test_the_refusal_names_the_offending_key_and_the_reading_runtime(tmp_path):
    """What was missing in the incident was WHICH runtime was reading, and what it choked on.

    "the runtime crashed somewhere in the broker" is not actionable; naming the reader's
    own version and path, and the key it does not know, is.
    """
    import phase_loop_runtime

    store = _written_by_a_newer_runtime(tmp_path)
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    message = str(caught.value)
    assert "future_diagnostic" in message
    assert phase_loop_runtime.__version__ in message
    assert str(store.path) in message
    assert caught.value.unknown_keys == ("future_diagnostic",)
    assert caught.value.idempotency_key == "key-1"


def test_a_missing_required_field_is_also_a_typed_refusal(tmp_path):
    """Drift in the other direction — a newer reader against an older store."""
    store = _store(tmp_path)
    store.path.write_text(json.dumps({"state": "effect_terminal_observed"}) + "\n")
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert caught.value.missing_keys


def test_the_record_is_NOT_skipped_or_coerced(tmp_path):
    """Refusing beats fabricating a partial read of a SEALED evidence store.

    A tolerant reader that dropped the unreadable line would silently under-report the
    store — and `epoch_blocked` is computed from exactly these records, so a dropped
    `outcome_ambiguous_blocked` would un-block a partition that must stay blocked. That is
    strictly worse than refusing to read.
    """
    store = _store(tmp_path)
    store.path.write_text(
        _line(idempotency_key="readable-1")
        + "\n"
        + _line(idempotency_key="unreadable-2", state="outcome_ambiguous_blocked",
                future_diagnostic="x")
        + "\n"
    )
    with pytest.raises(EvidenceStoreIncompatible):
        store.replay()


def test_an_unknown_STATE_VALUE_is_also_a_typed_refusal(tmp_path):
    """Drift is not only new KEYS — a new state VALUE is at least as likely.

    The coercion `TerminalOutcomeState(raw["state"])` originally sat OUTSIDE the guard,
    so a newer writer adding a state this runtime does not know raised a bare ValueError
    and escaped the very protection written for forward compatibility.
    (ah#834 r1, fable N1.)
    """
    store = _store(tmp_path)
    store.path.write_text(_line(state="some_future_terminal_state") + "\n")
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert "some_future_terminal_state" in str(caught.value.__cause__)


def test_a_row_with_no_state_key_is_also_a_typed_refusal(tmp_path):
    """The third drift shape: an older writer that predates the field entirely."""
    store = _store(tmp_path)
    store.path.write_text('{"idempotency_key": "key-1"}\n')
    with pytest.raises(EvidenceStoreIncompatible):
        store.replay()


def test_the_refusal_matches_the_admission_stores_fail_closed_base_class(tmp_path):
    """`AdmissionStoreIncompatible` is a PermissionError "so every fail-closed path stays
    closed". Its twin must be too, or a handler written to that convention misses this one.
    (ah#834 r1, fable N2.)
    """
    from phase_loop_runtime.convergence.broker.admission import AdmissionStoreIncompatible

    assert issubclass(EvidenceStoreIncompatible, PermissionError)
    assert issubclass(AdmissionStoreIncompatible, PermissionError)


def test_a_store_this_runtime_CAN_read_is_unaffected(tmp_path):
    """The guard must not refuse anything it understands."""
    store = _store(tmp_path)
    store.path.write_text(_line() + "\n" + _line(idempotency_key="key-2") + "\n")
    replayed = store.replay()
    assert set(replayed) == {"key-1", "key-2"}
    assert replayed["key-1"].evidence_reference == "https://example.invalid/pr/1"


# ---------------------------------------------------------------------------
# ah#834 r6 (fable): the refusal's `line` was never asserted, so two mutants
# survived — `enumerate(..., start=1)` -> `start=0` and the `line=index` that
# carries it. The offending row is deliberately NOT the first one: a store whose
# only row is the bad one cannot tell a correct line number from a constant.


def test_the_refusal_NAMES_THE_LINE_of_the_offending_row(tmp_path):
    """The line number is the actionable half of a multi-row store's refusal.

    `evidence.jsonl` is append-only and grows for the life of a partition, so "this
    store is unreadable" without a row is a haystack. Two readable rows precede the
    drifted one here, which is what makes the assertion able to fail: it pins the
    1-based index of the row that actually broke, not merely that some number was
    reported.
    """
    # THE SHAPE A REAL STORE HAS, not the shape that is easy to write.
    #
    # The first version put the drifted row LAST and gave every row a distinct key. Under
    # those two coincidences the true index equals both the row count and the
    # records-read count, so `line=len(result) + 1` and `line=len(lines)` both SURVIVED —
    # invisibly, because they were not in the matrix and left the collected count at 111.
    #
    # `len(result) + 1` is the plausible refactor ("count what you have read") and it is
    # wrong on the production shape: `record_intent` appends PROVIDER_CALL_IN_FLIGHT and
    # `record_terminal` appends the terminal for the SAME key, and `replay()` collapses
    # them last-row-wins — so on a live store `len(result)` is strictly smaller than the
    # row index. Rows 1-2 below are that duplicate, and the drifted row is row 3 of 4.
    #
    # One fixture kills all four at once: `start=0` reports 2, a constant reports 1, the
    # total row count reports 4, and records-read+1 reports 2 (only `key-1` is in
    # `result` when row 3 fails). (ah#834 r7, fable.)
    store = _store(tmp_path)
    store.path.write_text(
        _line(idempotency_key="key-1", state="provider_call_in_flight") + "\n"
        + _line(idempotency_key="key-1") + "\n"
        + _line(idempotency_key="key-2", future_diagnostic="from a newer writer") + "\n"
        + _line(idempotency_key="key-3") + "\n"
    )
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert caught.value.line == 3, caught.value.line
    assert caught.value.idempotency_key == "key-2"
    # ...and the operator reads the message, not the attribute.
    assert "at line 3" in str(caught.value)


def test_the_line_is_ONE_BASED_so_it_matches_what_a_reader_counts(tmp_path):
    """A first-row failure must report 1, not 0.

    This is the half `start=1` owns: with the bad row first, an off-by-one is the only
    thing that can move this number, and `sed -n 1p` on the store must land on the row
    the refusal names.
    """
    store = _written_by_a_newer_runtime(tmp_path)
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert caught.value.line == 1, caught.value.line


def test_constructor_key_mismatch_returns_EMPTY_for_a_non_dataclass():
    """The documented unconditional-call contract, which no test reached.

    The docstring promises `((), ())` for a non-dataclass "so a caller may use it
    unconditionally" — and the refusal path depends on that: it calls the helper before
    it knows anything about the constructor, and falls back to naming the cause when both
    tuples are empty. Delete the guard and that call raises inside the except block,
    replacing a typed refusal with a TypeError from the error handler itself — the exact
    ah#789 failure shape, relocated. Unpinned, the guard was free to vanish.
    """
    from phase_loop_runtime.convergence.broker.admission import constructor_key_mismatch

    class NotADataclass:
        def __init__(self, **kwargs):
            raise AssertionError("must not be constructed")

    assert constructor_key_mismatch(NotADataclass, {"anything": 1}) == ((), ())
    assert constructor_key_mismatch(dict, {"anything": 1}) == ((), ())


# ---------------------------------------------------------------------------
# ah#834 r7 (codex, BLOCKING): the decode and the shape check sat OUTSIDE the
# guard, so three more shapes crashed untyped — losing the runtime, path and line
# diagnostics the refusal exists to carry, in the store whose replay decides
# `epoch_blocked`. A multi-row store, per the seat, so the line number is proven
# too.


@pytest.mark.parametrize(
    "label,row",
    [
        ("json null", "null"),
        ("json list", "[]"),
        ("json string", '"not an object"'),
        ("json number", "5"),
        ("truncated append", '{"idempotency_key": "k2", '),
        ("blank line", ""),
        ("whitespace only", "   "),
    ],
)
def test_a_row_that_is_not_a_usable_OBJECT_is_a_typed_refusal_naming_its_line(
    tmp_path, label, row
):
    """Every one of these bypassed `EvidenceStoreIncompatible` before r7.

    `json.loads(line)` and `raw.get(...)` both ran above the try, so a non-object row
    raised `AttributeError: 'NoneType' object has no attribute 'get'` and an undecodable
    one raised `JSONDecodeError` — the ah#789 failure mode exactly, an untyped crash on a
    sealed store read, with no diagnostics.

    The truncated-append case is the one most likely in production: the store is
    append-only, so a crash mid-append leaves precisely that. Refusing it is correct —
    fabricating a partial read of a sealed evidence store is the documented worse option.
    """
    store = _store(tmp_path)
    store.path.write_text(
        _line(idempotency_key="key-1") + "\n" + row + "\n"
    )
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert caught.value.line == 2, (label, caught.value.line)
    assert "at line 2" in str(caught.value)
    # No keys can be named for a row that is not a mapping — and the mismatch helper must
    # never have been handed one, or the error handler itself would have crashed.
    assert caught.value.unknown_keys == ()
    assert caught.value.missing_keys == ()
    # The refusal still names the reading runtime, which is the actionable fact in ah#789.
    import phase_loop_runtime
    assert phase_loop_runtime.__version__ in str(caught.value)


def test_a_readable_store_is_still_read_after_the_shape_check(tmp_path):
    """The guard must not have narrowed the success path.

    Two valid rows, both returned, keyed by idempotency key. A shape check that rejected
    a legitimate record would fail-close a partition that should be readable, which is a
    worse outcome than the crash it replaced.
    """
    store = _store(tmp_path)
    store.path.write_text(
        _line(idempotency_key="key-1") + "\n" + _line(idempotency_key="key-2") + "\n"
    )
    replayed = store.replay()
    assert sorted(replayed) == ["key-1", "key-2"]


@pytest.mark.parametrize(
    "label,key",
    [("a list", ["a"]), ("a dict", {"a": 1}), ("a number", 7), ("null", None)],
)
def test_a_NON_STRING_idempotency_key_is_a_typed_refusal(tmp_path, label, key):
    """`result[raw["idempotency_key"]]` ran below the guard.

    An unhashable key raised a bare `TypeError: unhashable type: 'list'` out of
    `replay()` — the ah#789 signature, after the record had constructed fine. A
    hashable non-string key was worse than a crash: it read SILENTLY and keyed a record
    nothing will ever look up, while `epoch_blocked` is computed over exactly this
    mapping. (ah#834 r7, fable.)
    """
    import json

    store = _store(tmp_path)
    store.path.write_text(
        _line(idempotency_key="key-1") + "\n"
        + json.dumps({"idempotency_key": key, "state": "effect_terminal_observed",
                      "evidence_reference": "https://example.invalid/pr/2"}) + "\n"
    )
    with pytest.raises(EvidenceStoreIncompatible) as caught:
        store.replay()
    assert caught.value.line == 2, (label, caught.value.line)


def test_an_EMPTY_STRING_key_still_reads(tmp_path):
    """The control on the shape check: it must not fail-close a store that reads today.

    An empty key is hashable and readable. Rejecting it would fail-close a partition for
    a vocabulary complaint, which this round's own control calls worse than the crash it
    replaced.
    """
    store = _store(tmp_path)
    store.path.write_text(_line(idempotency_key="") + "\n")
    assert list(store.replay()) == [""]
