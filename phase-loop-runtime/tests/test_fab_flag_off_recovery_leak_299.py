"""ah#299: FAB torn-recovery ran on a FLAG-OFF resume, leaking byte-neutrality.

The recovery block in `run_train` was gated on `fab_run_id is not None` alone, with a
comment claiming that made it byte-neutral when the master flag is off ("no provenance ⇒
no run_id ⇒ block skipped"). That premise is FALSE on the resume path: a flag-ON admission
persists `fab_run_id` to the ledger and a later flag-OFF resume restores it
unconditionally. So with the flag off the block still ran — mutating the run store via
torn-recovery and, on exception, halting with `fab_readmit_failed` instead of taking the
ordinary non-FAB merge path.

Same false premise the #265 CR disproved for `_live_merge_pr`, which is why that site
keys on `fab_active`.

WHY THIS FILE EXISTS SEPARATELY FROM THE #265 COVERAGE
`test_flag_off_resume_with_stale_run_id_is_byte_neutral` already covers a flag-off resume
with a stale run_id — but it drives `_live_merge_pr`, the #265 SITE. The #299 leak is a
DIFFERENT call site: the torn-recovery block inside `run_train`. That is precisely why the
existing test did not catch this, and why the regression below must drive `run_train`.

CR HISTORY (this file's first version was TAUTOLOGICAL — recorded so it is not repeated)
The original tests asserted on values reconstructed inside the test body: one grepped
`inspect.getsource` for a substring, and two recomputed `run_id is not None and
fab_promotion_enabled()` locally without ever calling `run_train`, so the monkeypatched
recovery spy was never reachable and `assert not calls` was vacuously true. The codex CR
leg supplied the killing mutation:

    if _fab_run_id_shortcut is not None and fab_promotion_enabled() or _fab_run_id_shortcut is not None:

which restores the bug in full while every one of those tests still passed. The tests
below drive the real `run_train` guard, so that mutation fails them.

Deliberately in an UNMARKED module so CI runs it.
"""
from __future__ import annotations

from pathlib import Path

from phase_loop_runtime import governed_premerge as gp
from phase_loop_runtime import train_runner
from phase_loop_runtime.train_ledger import LedgerRecord, append_record
from phase_loop_runtime.train_roadmap import parse_train_roadmap

# Reuse the piece-3a integration harness rather than rebuilding a train fixture; the repo
# already imports across test modules this way (see test_fab_activation_promotion's own
# `from test_train_merge import _pr_is_open_true`).
from test_fab_activation_promotion import (  # noqa: E402
    TRAIN_2NODE_MD,
    _capturing_merge_stub,
    _make_publish_stub,
    _p3a_run_train,
)


def _resumable_ledger(tmp_path: Path) -> Path:
    """A ledger in the exact state the leak needs: both nodes already admitted (`pr_open`)
    with a `fab_run_id` durably bound by a PRIOR FLAG-ON admission. On resume `run_train`
    restores that run_id unconditionally — the stale-provenance precondition."""
    ledger = tmp_path / "ledger" / "train.ledger.jsonl"
    append_record(ledger, LedgerRecord(
        node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/repo-a",
        head_sha="sha-a", pr_url="https://gh/a/1", merge_order=0, fab_run_id="run-repo-a"))
    append_record(ledger, LedgerRecord(
        node_id="repo-b/specs/plan-b.md", status="pr_open", branch="feat/repo-b",
        head_sha="sha-b", pr_url="https://gh/b/1", merge_order=1, fab_run_id="run-repo-b"))
    return ledger


def _resume_train(tmp_path: Path, monkeypatch, *, recovery_calls: list):
    """Drive the REAL `run_train` resume path with a spy on torn-recovery.

    `run_loop` is never invoked on resume (no fresh snapshot), so the only source of
    `fab_run_id` is the ledger — exactly the production shape of the leak.
    """
    roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
    ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
    monkeypatch.setattr(
        train_runner, "_fab_recover_torn_to_admitted",
        lambda *a, **k: recovery_calls.append(a), raising=False,
    )
    return _p3a_run_train(
        roadmap, _resumable_ledger(tmp_path), ws_map,
        run_loop=lambda *a, **kw: (None, []),
        publish=_make_publish_stub({}),
        merge_fn=_capturing_merge_stub({}),
    )


def test_flag_off_resume_does_not_run_torn_recovery(tmp_path: Path, monkeypatch):
    """THE ah#299 REGRESSION. Flag OFF + a stale ledger-persisted `fab_run_id` must NOT
    reach torn-recovery, and the train must still complete by the ordinary merge path.

    Mutation that kills this: gate the block on `_fab_run_id_shortcut is not None` alone
    (the pre-fix state), or codex's `... and fab_promotion_enabled() or
    _fab_run_id_shortcut is not None` — either lets recovery run and populates `calls`.
    """
    monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)  # flag OFF on this resume
    calls: list = []

    result = _resume_train(tmp_path, monkeypatch, recovery_calls=calls)

    assert calls == [], (
        "FAB torn-recovery ran on a FLAG-OFF resume from a stale ledger fab_run_id — "
        "byte-neutrality leak (ah#299)"
    )
    assert result["status"] == "merged", (
        f"the ordinary non-FAB merge path must still complete with the flag off: {result}"
    )


def test_flag_on_resume_still_runs_torn_recovery(tmp_path: Path, monkeypatch):
    """NEGATIVE CONTROL. Without this, gating the block to a constant `False` — or
    deleting it outright — would satisfy the test above while silently disabling FAB
    recovery for real flag-ON runs."""
    monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
    calls: list = []

    result = _resume_train(tmp_path, monkeypatch, recovery_calls=calls)

    assert calls, "flag ON + a bound fab_run_id must still reach torn-recovery"
    assert result["status"] == "merged", result


def test_fabreadmit_flag_off_recovery_leak_guard(request):
    """Flag-off recovery leak guard for broker readmission."""
    from pytest import skip

    from _fabreadmit_tdd_guard import (
        FABREADMIT_SKIP_REASON,
        fabreadmit_capability_active,
        fabreadmit_require,
        fabreadmit_symbol,
        fabreadmit_this_nodeid,
    )

    if not fabreadmit_capability_active():
        skip(FABREADMIT_SKIP_REASON)

    recovery_fn = fabreadmit_symbol("phase_loop_runtime.train_runner", "_commit_broker_readmitted_head")
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        recovery_fn is not None,
        "_commit_broker_readmitted_head missing in train_runner for flag-off recovery leak guard",
    )
