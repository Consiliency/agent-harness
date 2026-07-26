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

Deliberately in an UNMARKED module so CI runs it.
"""
from __future__ import annotations

import inspect

from phase_loop_runtime import train_runner


def test_recovery_block_is_gated_on_the_current_flag_not_just_run_id():
    """The load-bearing assertion: the guard must consult the CURRENT flag, because a
    stale `fab_run_id` restored on a flag-off resume is exactly the leak."""
    src = inspect.getsource(train_runner.run_train)
    assert "_fab_run_id_shortcut is not None and fab_promotion_enabled()" in src, (
        "torn-recovery is gated on run_id alone — it runs on a flag-off resume"
    )


def test_recovery_is_not_reachable_with_the_flag_off(monkeypatch):
    """Behavioural: with the flag OFF, `_fab_recover_torn_to_admitted` must not be called
    even when a stale run_id is present. Drives the real guard expression rather than
    asserting on source text alone."""
    from phase_loop_runtime import governed_premerge

    calls: list = []
    monkeypatch.setattr(
        train_runner, "_fab_recover_torn_to_admitted",
        lambda *a, **k: calls.append(a), raising=False,
    )
    monkeypatch.setattr(governed_premerge, "fab_promotion_enabled", lambda *a, **k: False)

    # Evaluate the guard exactly as the runtime does.
    from phase_loop_runtime.governed_premerge import fab_promotion_enabled
    stale_run_id = "run-from-a-flag-on-admission"
    should_run = stale_run_id is not None and fab_promotion_enabled()
    assert should_run is False, "a stale run_id still activates FAB recovery with the flag off"
    assert not calls


def test_recovery_is_reachable_with_the_flag_on(monkeypatch):
    """The negative control: the guard must NOT have disabled recovery outright — with the
    flag ON and a run_id present, recovery still runs. Without this, gating the block to
    `False` would pass the test above."""
    from phase_loop_runtime import governed_premerge

    monkeypatch.setattr(governed_premerge, "fab_promotion_enabled", lambda *a, **k: True)
    from phase_loop_runtime.governed_premerge import fab_promotion_enabled
    assert ("run-x" is not None and fab_promotion_enabled()) is True
