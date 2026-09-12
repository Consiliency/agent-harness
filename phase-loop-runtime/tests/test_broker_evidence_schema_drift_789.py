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
