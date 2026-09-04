"""CI invariant suite for the cross-repo release-train coordinator.

These tests lock in the load-bearing safety properties of P1–P4.  Each test
targets one invariant explicitly; the assertion is structural (e.g. capturing
the actual ref value passed to ``set_upstream_ref``) rather than merely
checking that a function was called.

Run with:
    cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_train_invariants.py -q

All git/gh/run_loop/publish/panel boundaries are stubbed; no live network.

Invariants:
  INV-1. No node merges before train approval (partial-merge guard).
  INV-2. Downstream re-resolution to upstream MERGED SHA OCCURRED and was
         ordered BEFORE downstream re-verification — the false-green killer.
         The ref value passed to ``set_upstream_ref`` must equal the upstream
         MERGED SHA (not the draft SHA) and that call must appear in the call
         log BEFORE the downstream ``reverify`` call.
  INV-3. Preflight failure opens ZERO PRs.
  INV-4. Train state never written under any ``.phase-loop/`` path.
  INV-5. Autonomous mode adds no ``human_required``; a panel non-approval is a
         non-human terminal (``human_required=False`` in ``terminal_blocker``).
  INV-6. Live-default ``_live_reverify`` directly runs the downstream node's
         plan verification commands against the workspace.  A failing command
         (non-zero exit) returns False; a passing command returns True.
         Fail-closed: no plan → False; no awaiting phase → False; exception →
         False.  Tests call ``_live_reverify`` directly without stubbing
         ``_reverify_fn`` to guard the live-default path.  (After the
         false-green-killer fix: _live_reverify no longer delegates to
         run_loop, which was a no-op for awaiting_phase_closeout + manual.)
  INV-7. ``run_loop``'s failure contract: a genuine verification failure ALWAYS
         produces a StateSnapshot with at least one of the three failure signals
         set (``blocker_class`` non-None, ``human_required=True``, or
         ``closeout_terminal_status`` in the bad set).  Pinned via:
           (a) Pre-seeded repo + real ``status_snapshot()`` (the snapshot-
               construction code ``run_loop`` uses internally): a ``repeated_
               verification_failure`` LoopEvent in the event log causes
               ``status_snapshot()`` to return ``blocker_class`` non-None.
           (b) Structural: ``_pipeline_branch_blocker_from_error()`` always
               returns a non-None ``blocker_class`` in ``BLOCKER_CLASSES``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase_loop_runtime.governed_premerge import LoopResult
from phase_loop_runtime.models import StateSnapshot
from phase_loop_runtime.train_ledger import LedgerRecord, append_record, read_ledger
from phase_loop_runtime.train_roadmap import parse_train_roadmap
from phase_loop_runtime.train_runner import _live_reverify, run_train


# ---------------------------------------------------------------------------
# Shared fixtures

TRAIN_1NODE_MD = """\
# Release Train: invariant-test-1

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)
"""

TRAIN_2NODE_MD = """\
# Release Train: invariant-test

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)

### Node: repo-b / specs/plan-b.md

**Depends on:** repo-a / specs/plan-a.md
**Channel:** submodule path=vendor/repo-a
"""

TRAIN_3NODE_MD = """\
# Release Train: invariant-test-3

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)

### Node: repo-b / specs/plan-b.md

**Depends on:** repo-a / specs/plan-a.md
**Channel:** submodule path=vendor/repo-a

### Node: repo-c / specs/plan-c.md

**Depends on:** repo-b / specs/plan-b.md
**Channel:** submodule path=vendor/repo-b
"""

_DRAFT_SHA_A = "sha-DRAFT-repo-a"
_MERGED_SHA_A = "sha-MERGED-repo-a"

assert _DRAFT_SHA_A != _MERGED_SHA_A, "draft and merged SHAs must differ for tests to be meaningful"


def _preflight_pass(nodes, resolve_workspace):
    return []


def _preflight_fail(nodes, resolve_workspace):
    return ["preflight error: some check failed"]


def _pr_is_open_false(workspace: Path, branch: str) -> bool:
    return False


def _pr_is_open_true(workspace: Path, branch: str) -> bool:
    return True


def _live_head_for_p3_done(workspace: Path, branch: str) -> str:
    return _DRAFT_SHA_A if workspace.name == "repo-a" else "sha-DRAFT-repo-b"


def _approval_review_fn(artifact: str, run_mode: str) -> LoopResult:
    return LoopResult(mergeable=True, ran=True, rounds=1)


def _rejection_review_fn(artifact: str, run_mode: str) -> LoopResult:
    return LoopResult(
        mergeable=False,
        ran=True,
        rounds=1,
        terminal_blocker={
            "human_required": False,
            "blocker_class": "review_gate_block",
            "blocker_summary": "invariant test: panel rejected train",
        },
        reason="non_convergence",
    )


def _make_publish_stub(*, draft_sha_override: Optional[Dict[str, str]] = None):
    """Return a publish stub; allows per-repo draft-SHA override for contrast tests."""
    def _publish(workspace: Path, owned_paths, *, draft: bool, **kw):
        sha = (draft_sha_override or {}).get(workspace.name, f"sha-DRAFT-{workspace.name}")
        return {
            "status": "published",
            "branch": f"feat/train-{workspace.name}",
            "head_sha": sha,
            "pr_url": f"https://gh.com/{workspace.name}/pr/1",
        }
    return _publish


def _setup_p3_done(
    tmp_path: Path,
    roadmap,
    ws_map: Dict[str, Path],
    *,
    sha_a: str = _DRAFT_SHA_A,
    sha_b: str = "sha-DRAFT-repo-b",
):
    """Pre-populate the ledger with P3-done state (both nodes pr_open).

    Uses distinct explicit draft SHAs so tests can assert the merged SHA
    differs from the draft SHA.
    """
    ledger = tmp_path / "ledger" / "train.ledger.jsonl"
    append_record(ledger, LedgerRecord(
        node_id="repo-a/specs/plan-a.md",
        status="pr_open",
        branch="feat/train-repo-a",
        head_sha=sha_a,
        pr_url="https://gh.com/repo-a/pr/1",
        merge_order=0,
    ))
    append_record(ledger, LedgerRecord(
        node_id="repo-b/specs/plan-b.md",
        status="pr_open",
        branch="feat/train-repo-b",
        head_sha=sha_b,
        pr_url="https://gh.com/repo-b/pr/1",
        merge_order=1,
    ))
    return ledger


def _make_merge_pr_stub(merge_log: List[str], merged_sha_map: Optional[Dict[str, str]] = None):
    """Merge stub that records workspace names and returns deterministic merged SHAs."""
    def _merge_pr(workspace: Path, branch: str, base: str = "main", head_sha: Optional[str] = None) -> str:
        merge_log.append(workspace.name)
        if merged_sha_map and workspace.name in merged_sha_map:
            return merged_sha_map[workspace.name]
        return f"sha-MERGED-{workspace.name}"
    return _merge_pr


# ---------------------------------------------------------------------------
# INV-1: No node merges before train approval (partial-merge guard)

class TestInvariant1NoMergeBeforeApproval:
    """A rejected train review must result in ZERO merge_pr calls.

    The guard also holds when the review itself is never reached (P3 blocked)
    and in the edge case where the merge phase is not enabled at all.
    """

    def test_panel_rejection_zero_merges(self, tmp_path: Path):
        """Train review rejection → merge_pr never called."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map)
        merge_log: List[str] = []

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub(merge_log),
            _train_review_fn=_rejection_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert merge_log == [], (
            f"INV-1 VIOLATED: merge_pr called {merge_log!r} before train approval"
        )

    def test_merge_phase_disabled_zero_merges(self, tmp_path: Path):
        """Without _merge_phase_enabled, merge_pr must never be called."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        merge_log: List[str] = []

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=False,
            _merge_pr_fn=_make_merge_pr_stub(merge_log),
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert merge_log == [], (
            "INV-1 VIOLATED: merge_pr called when _merge_phase_enabled=False"
        )

    def test_review_approval_then_reverify_fail_halts_before_downstream(self, tmp_path: Path):
        """Upstream merged; downstream reverify fails → downstream NOT merged (forward-only)."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map)
        merge_log: List[str] = []

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub(merge_log),
            _reverify_fn=lambda ws, rp, rm: ws.name != "repo-b",
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        # repo-a merged (upstream, root — no dependency, no reverify needed before merge)
        assert "repo-a" in merge_log, "repo-a must be merged before downstream check"
        # repo-b NOT merged because reverify failed
        assert "repo-b" not in merge_log, (
            f"INV-1 VIOLATED: repo-b was merged even though reverify failed; "
            f"merge_log: {merge_log}"
        )


# ---------------------------------------------------------------------------
# INV-2: False-green killer — re-resolution to MERGED SHA ordered BEFORE reverify

class TestInvariant2FalseGreenKiller:
    """set_upstream_ref is called with the MERGED SHA and BEFORE reverify.

    This is the central safety invariant of P4: the downstream workspace is
    resolved to the upstream MERGED SHA (not the draft SHA used during P3)
    before the re-verify call.  A downstream that was green only against the
    draft ref would otherwise silently receive a false-green verdict.

    The draft SHA and merged SHA are deliberately distinct in all tests.
    """

    def test_set_upstream_ref_called_with_merged_sha_not_draft(self, tmp_path: Path):
        """The ref passed to set_upstream_ref for repo-b equals the MERGED SHA of repo-a."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        # seed with distinct draft SHAs so we can tell draft from merged
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map, sha_a=_DRAFT_SHA_A)

        set_ref_calls: List[Dict[str, Any]] = []

        def _set_upstream_ref_capture(workspace: Path, channel, ref: str):
            set_ref_calls.append({
                "workspace": workspace.name,
                "ref": ref,
            })

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=_set_upstream_ref_capture,
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([], merged_sha_map={"repo-a": _MERGED_SHA_A}),
            _reverify_fn=lambda ws, rp, rm: True,
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        # The P4 set_upstream_ref call for repo-b (the downstream) must carry
        # the MERGED SHA of repo-a, not the draft SHA.
        p4_calls = [c for c in set_ref_calls if c["workspace"] == "repo-b"]
        assert p4_calls, (
            "INV-2 VIOLATED: set_upstream_ref was never called for repo-b; "
            "P4 must re-inject the upstream merged SHA before re-verify"
        )
        last_call = p4_calls[-1]
        assert last_call["ref"] == _MERGED_SHA_A, (
            f"INV-2 VIOLATED: set_upstream_ref for repo-b received ref={last_call['ref']!r}; "
            f"expected the upstream MERGED SHA {_MERGED_SHA_A!r} (NOT the draft SHA {_DRAFT_SHA_A!r})"
        )

    def test_set_upstream_ref_ordered_before_reverify(self, tmp_path: Path):
        """set_upstream_ref(repo-b, MERGED_SHA) appears in the call log BEFORE reverify(repo-b)."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map, sha_a=_DRAFT_SHA_A)

        # Shared call log captures set_upstream_ref and reverify events in order.
        call_log: List[Dict[str, Any]] = []

        def _set_upstream_ref_logging(workspace: Path, channel, ref: str):
            call_log.append({
                "type": "set_upstream_ref",
                "workspace": workspace.name,
                "ref": ref,
            })

        def _reverify_logging(workspace: Path, roadmap_path: Path, run_mode: str) -> bool:
            call_log.append({
                "type": "reverify",
                "workspace": workspace.name,
            })
            return True

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=_set_upstream_ref_logging,
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([], merged_sha_map={"repo-a": _MERGED_SHA_A}),
            _reverify_fn=_reverify_logging,
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        # Locate the P4 set_upstream_ref call for repo-b (downstream re-injection).
        set_ref_idx: Optional[int] = None
        for i, entry in enumerate(call_log):
            if entry["type"] == "set_upstream_ref" and entry["workspace"] == "repo-b":
                # Verify it carries the MERGED SHA (belt-and-suspenders with INV-2a).
                assert entry["ref"] == _MERGED_SHA_A, (
                    f"INV-2 VIOLATED: set_upstream_ref for repo-b carries ref={entry['ref']!r}; "
                    f"expected {_MERGED_SHA_A!r}"
                )
                set_ref_idx = i
                break

        assert set_ref_idx is not None, (
            "INV-2 VIOLATED: set_upstream_ref not called for repo-b at all; "
            "P4 must re-inject before re-verify"
        )

        # Locate the reverify call for repo-b.
        reverify_idx: Optional[int] = None
        for i, entry in enumerate(call_log):
            if entry["type"] == "reverify" and entry["workspace"] == "repo-b":
                reverify_idx = i
                break

        assert reverify_idx is not None, (
            "INV-2 VIOLATED: reverify not called for repo-b"
        )

        # CRITICAL: set_upstream_ref MUST precede reverify in the call log.
        assert set_ref_idx < reverify_idx, (
            f"INV-2 VIOLATED: set_upstream_ref (index={set_ref_idx}) did not precede "
            f"reverify (index={reverify_idx}) for repo-b. "
            f"Call log: {call_log}"
        )

    def test_ref_value_is_distinct_from_draft_sha(self, tmp_path: Path):
        """Guard that the test itself is valid: draft and merged SHAs are distinct."""
        # This assertion guards INV-2a and INV-2b against a broken test that
        # uses the same value for both draft and merged SHA.
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map, sha_a=_DRAFT_SHA_A)
        captured_refs: List[str] = []

        def _set_upstream_ref_capture(workspace: Path, channel, ref: str):
            if workspace.name == "repo-b":
                captured_refs.append(ref)

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=_set_upstream_ref_capture,
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([], merged_sha_map={"repo-a": _MERGED_SHA_A}),
            _reverify_fn=lambda ws, rp, rm: True,
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert captured_refs, "set_upstream_ref must be called for repo-b"
        assert captured_refs[-1] != _DRAFT_SHA_A, (
            f"INV-2 VIOLATED: set_upstream_ref for repo-b received the DRAFT SHA "
            f"{_DRAFT_SHA_A!r} instead of the merged SHA — false-green guard bypassed"
        )


# ---------------------------------------------------------------------------
# INV-3: Preflight failure opens ZERO PRs

class TestInvariant3PreflightZeroPRs:
    """A preflight failure must prevent ANY draft PR from being opened."""

    def test_preflight_failure_zero_publish_calls(self, tmp_path: Path):
        """_preflight_fn returns errors → _publish never called."""
        roadmap = parse_train_roadmap(TRAIN_3NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        publish_log: List[str] = []

        def _publish_spy(workspace: Path, owned_paths, *, draft: bool, **kw):
            publish_log.append(workspace.name)
            return {"status": "published", "branch": f"feat/train-{workspace.name}",
                    "head_sha": f"sha-{workspace.name}", "pr_url": "https://gh.com/1"}

        result = run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_publish_spy,
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_fail,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([]),
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert result["status"] == "preflight_failed", (
            f"Expected status='preflight_failed', got {result['status']!r}"
        )
        assert publish_log == [], (
            f"INV-3 VIOLATED: publish called {publish_log!r} after preflight failure; "
            "zero PRs must be opened when preflight fails"
        )

    def test_preflight_failure_empty_ledger(self, tmp_path: Path):
        """After preflight failure, ledger remains empty (no records written)."""
        roadmap = parse_train_roadmap(TRAIN_3NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_fail,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([]),
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        # Ledger may not exist at all, or may be empty.
        if ledger.exists():
            state = read_ledger(ledger)
            assert state == {}, (
                f"INV-3 VIOLATED: ledger contains records after preflight failure: {state}"
            )


# ---------------------------------------------------------------------------
# INV-4: Train state never written under any .phase-loop/ path

class TestInvariant4NoPhaseLoopState:
    """The train ledger must never be located inside a .phase-loop/ directory."""

    def test_ledger_outside_phase_loop_is_accepted(self, tmp_path: Path):
        """A ledger path outside .phase-loop/ works normally."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        # Any non-.phase-loop path must be accepted.
        ledger = tmp_path / "train-ledger" / "train.ledger.jsonl"

        result = run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([]),
            _reverify_fn=lambda ws, rp, rm: True,
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert result["status"] == "merged"

    def test_ledger_inside_phase_loop_raises(self, tmp_path: Path):
        """A ledger path under .phase-loop/ must raise ValueError immediately."""
        import pytest

        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        # Any path through .phase-loop/ must be rejected.
        bad_ledger = tmp_path / "repo-a" / ".phase-loop" / "train.ledger.jsonl"

        with pytest.raises(ValueError, match=r"\.phase-loop"):
            run_train(
                roadmap,
                bad_ledger,
                run_mode="governed",
                resolve_workspace=lambda n: ws_map[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub(),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_false,
                _live_pr_head_sha_fn=lambda ws, br: None,
                _merge_phase_enabled=True,
                _merge_pr_fn=_make_merge_pr_stub([]),
                _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            )


# ---------------------------------------------------------------------------
# INV-5: Autonomy boundary — no human_required; non-approval is non-human terminal

class TestInvariant5AutonomyBoundary:
    """Coordinator autonomy-first invariants.

    - Autonomous mode with _merge_phase_enabled=True stops at drafts_open (no merge).
    - Panel rejection terminal carries human_required=False.
    - The coordinator NEVER injects human_required into the train state.
    """

    def test_autonomous_stops_at_drafts_open(self, tmp_path: Path):
        """Autonomous mode + _merge_phase_enabled=True → status='drafts_open', zero merges."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        merge_log: List[str] = []

        result = run_train(
            roadmap,
            ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub(merge_log),
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert result["status"] == "drafts_open", (
            f"INV-5 VIOLATED: autonomous mode must stop at 'drafts_open'; "
            f"got {result['status']!r}"
        )
        assert merge_log == [], (
            f"INV-5 VIOLATED: merge_pr called in autonomous mode: {merge_log}"
        )

    def test_non_approval_terminal_is_non_human(self, tmp_path: Path):
        """Panel rejection must carry human_required=False in terminal_blocker."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map)

        result = run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=_live_head_for_p3_done,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([]),
            _train_review_fn=_rejection_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        blocker = result.get("terminal_blocker") or {}
        assert blocker.get("human_required") is False, (
            f"INV-5 VIOLATED: terminal_blocker must have human_required=False on "
            f"panel rejection; got {blocker!r}"
        )

    def test_autonomous_result_has_no_human_required_key(self, tmp_path: Path):
        """Autonomous stops at drafts_open; result must not carry human_required=True."""
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        result = run_train(
            roadmap,
            ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub([]),
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        # The result must NOT have human_required=True anywhere.
        assert result.get("human_required") is not True, (
            f"INV-5 VIOLATED: autonomous result must not carry human_required=True; "
            f"got {result!r}"
        )
        blocker = result.get("terminal_blocker") or {}
        assert blocker.get("human_required") is not True, (
            f"INV-5 VIOLATED: terminal_blocker must not carry human_required=True in "
            f"autonomous mode; got {blocker!r}"
        )


# ---------------------------------------------------------------------------
# INV-6: Live-default _live_reverify directly runs verification commands

class TestInvariant6LiveReverifyRunsVerification:
    """_live_reverify directly executes the downstream node's plan verification
    commands against the workspace and returns False when any command fails.

    This test calls _live_reverify DIRECTLY (not through run_train) without
    stubbing _reverify_fn.  It guards the live-default path used in production
    runs.

    After the false-green-killer fix: _live_reverify no longer delegates to
    run_loop (which was a no-op for awaiting_phase_closeout + manual closeout).
    It directly calls verification_commands_from_plan + run_verification against
    the workspace that has the merged pin injected.  The merged-pin file written
    by set_upstream_ref is read by whatever commands the plan declares.

    Fail-closed contract:
      a. Failing verification command → False
      b. No plan file → False (can't verify)
      c. No awaiting phase found → False (no actionable phase)
      d. Any exception → False (fail-safe)
      e. Plan with no verification commands → True (plan author's choice)
      f. Passing verification commands → True
    """

    def test_proofgate_train_reverify_requires_exact_attested_proof(self):
        from .proofgate_tdd_guard import ProofgateMissingCapabilityError, guard_proofgate_nodeid, proofgate_invalid_acceptance_route_cases, run_proofgate_contract
        nodeid = "phase-loop-runtime/tests/test_train_invariants.py::TestInvariant6LiveReverifyRunsVerification::test_proofgate_train_reverify_requires_exact_attested_proof"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            import tempfile
            from unittest.mock import patch
            from phase_loop_runtime import goal_coverage
            from phase_loop_runtime import train_runner

            if not hasattr(train_runner, "reverify_proofgate_train_scenarios"):
                raise ProofgateMissingCapabilityError("train_runner missing reverify_proofgate_train_scenarios capability")

            with tempfile.TemporaryDirectory() as td:
                ws, roadmap = self._make_reverify_repo(Path(td))
                reverify_fn = getattr(train_runner, "_live_reverify", getattr(train_runner, "reverify_proofgate_train_scenarios", None))
                for mode in ("PROOFGATE", "PROOFGATE_ATTENDED"):
                    # 1. Uncorrupted / missing proof scenario must fail
                    res1 = reverify_fn(ws, roadmap_path=roadmap, run_mode=mode)
                    self.assertFalse(res1, f"Live reverify in mode {mode} with missing proof must return False")

                    # 2. Corrupted plan files (all authoritative invalid acceptance bytes)
                    plan_file = ws / "plans" / "P1.md"
                    if plan_file.exists():
                        if not hasattr(goal_coverage, "extract_acceptance_contracts"):
                            raise ProofgateMissingCapabilityError("goal_coverage.extract_acceptance_contracts missing")
                        parser = goal_coverage.extract_acceptance_contracts
                        for expected_reason, invalid_bytes in proofgate_invalid_acceptance_route_cases():
                            plan_file.write_text(invalid_bytes, encoding="utf-8")
                            with patch.object(
                                goal_coverage,
                                "extract_acceptance_contracts",
                                wraps=parser,
                            ) as parser_spy:
                                res2 = reverify_fn(ws, roadmap_path=roadmap, run_mode=mode)
                            self.assertFalse(
                                res2,
                                f"Live reverify in mode {mode} with {expected_reason} plan must return False",
                            )
                            self.assertTrue(
                                any(
                                    call.args and call.args[0] == invalid_bytes
                                    for call in parser_spy.call_args_list
                                ),
                                f"Live reverify in mode {mode} must parse {expected_reason} bytes",
                            )

                    # 3. Positive scenario control: valid verification must return True
                    ws_pos, roadmap_pos = self._make_reverify_repo(
                        Path(td) / f"pos_{mode}",
                        verify_lines='- `python3 -c "import sys; sys.exit(0)"`\n',
                    )
                    res_pos = reverify_fn(ws_pos, roadmap_path=roadmap_pos, run_mode=mode)
                    self.assertIsNotNone(res_pos, f"Live reverify in mode {mode} must not return None")
                    self.assertTrue(res_pos, f"Live reverify in mode {mode} with valid proof must return True")

        run_proofgate_contract(nodeid, _contract)



    def _make_reverify_repo(self, tmp_path: Path, verify_lines: str = "") -> tuple[Path, Path]:
        """Create a minimal workspace at awaiting_phase_closeout.

        Sets up a git repo with a single-phase roadmap, a plan file whose
        ## Verification section contains ``verify_lines``, and a persisted
        state file that puts phase P1 at awaiting_phase_closeout so that
        ``reconcile()`` returns ``current_phase="P1"``.
        """
        import subprocess
        from phase_loop_test_utils import make_repo, write_phase_plan
        from phase_loop_runtime.models import utc_now
        from phase_loop_runtime.provenance import snapshot_provenance
        from phase_loop_runtime.state import write_state

        repo = make_repo(tmp_path)
        # Replace the default multi-phase roadmap with a single test phase.
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text("# Roadmap\n\n### Phase 0 — P1 (P1)\n\n")
        subprocess.run(["git", "add", "specs/phase-plans-v1.md"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "single-phase roadmap"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )

        # Write a plan with the given verification body.
        body = (
            "# P1\n\n"
            "## Lanes\n\n"
            "### SL-0 - P1\n"
            "- **Owned files**: `work.md`\n\n"
            f"## Verification\n\n{verify_lines}\n"
        )
        plan = write_phase_plan(repo, "P1", roadmap, body=body)
        subprocess.run(
            ["git", "add", str(plan.relative_to(repo))],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "add plan with verification"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )

        # Write state that puts P1 at awaiting_phase_closeout with correct
        # provenance so reconcile() restores the status from the state file.
        state = StateSnapshot(
            timestamp=utc_now(),
            repo=str(repo),
            roadmap=str(roadmap),
            phases={"P1": "awaiting_phase_closeout"},
            current_phase="P1",
            **snapshot_provenance(roadmap),
        )
        write_state(repo, state)
        return repo, roadmap

    def test_passing_verification_returns_true(self, tmp_path: Path):
        """Verification command exits 0 → _live_reverify returns True."""
        repo, roadmap = self._make_reverify_repo(
            tmp_path,
            verify_lines='- `python3 -c "import sys; sys.exit(0)"`\n',
        )
        result = _live_reverify(repo, roadmap, "governed")
        assert result is True, (
            "INV-6 VIOLATED: _live_reverify returned False when all verification "
            "commands exited 0 (expected True — all commands passed)"
        )

    def test_failing_verification_returns_false(self, tmp_path: Path):
        """Verification command exits 1 → _live_reverify returns False.

        This is the canonical false-green regression guard: a downstream whose
        verification FAILS against the merged pin must cause _live_reverify to
        return False so the merge is halted.
        """
        repo, roadmap = self._make_reverify_repo(
            tmp_path,
            verify_lines='- `python3 -c "import sys; sys.exit(1)"`\n',
        )
        result = _live_reverify(repo, roadmap, "governed")
        assert result is False, (
            "INV-6 VIOLATED: _live_reverify returned True even though a "
            "verification command exited non-zero — downstream would be "
            "merged without valid verification against the merged pin"
        )

    def test_no_plan_returns_false(self, tmp_path: Path):
        """No plan file for the current phase → False (fail-closed)."""
        import subprocess
        from phase_loop_test_utils import make_repo
        from phase_loop_runtime.models import utc_now
        from phase_loop_runtime.provenance import snapshot_provenance
        from phase_loop_runtime.state import write_state

        repo = make_repo(tmp_path)
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text("# Roadmap\n\n### Phase 0 — P1 (P1)\n\n")
        subprocess.run(["git", "add", "specs/phase-plans-v1.md"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "roadmap no plan"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )
        # Write state but NO plan file — find_plan_artifact returns None.
        state = StateSnapshot(
            timestamp=utc_now(),
            repo=str(repo),
            roadmap=str(roadmap),
            phases={"P1": "awaiting_phase_closeout"},
            current_phase="P1",
            **snapshot_provenance(roadmap),
        )
        write_state(repo, state)
        result = _live_reverify(repo, roadmap, "governed")
        assert result is False, (
            "INV-6 VIOLATED: _live_reverify returned True when no plan file exists "
            "(fail-closed: cannot verify without a plan)"
        )

    def test_no_awaiting_phase_returns_false(self, tmp_path: Path):
        """All phases at 'planned' (nothing awaiting closeout) → False (fail-closed)."""
        from phase_loop_test_utils import make_repo
        repo = make_repo(tmp_path)
        roadmap = repo / "specs" / "phase-plans-v1.md"
        # No state written → reconcile returns all phases as 'planned';
        # _current_phase returns the first planned phase, not awaiting_phase_closeout.
        # _live_reverify finds no phase at awaiting_phase_closeout → fail closed.
        result = _live_reverify(repo, roadmap, "governed")
        assert result is False, (
            "INV-6 VIOLATED: _live_reverify returned True when no phase is at "
            "awaiting_phase_closeout — fail-closed contract violated"
        )

    def test_no_verification_commands_returns_true_by_default(self, tmp_path: Path, monkeypatch):
        """Plan with no verification commands → True when hard enforcement is off."""
        monkeypatch.delenv("PHASE_LOOP_VERIFY_ENFORCE", raising=False)
        repo, roadmap = self._make_reverify_repo(
            tmp_path,
            verify_lines="",  # empty → verification_commands_from_plan returns []
        )
        result = _live_reverify(repo, roadmap, "governed")
        assert result is True, (
            "INV-6 VIOLATED: _live_reverify returned False when the plan declares "
            "no verification commands — empty is not a failure (warn default)"
        )

    def test_no_verification_hard_enforce_returns_false(self, tmp_path: Path, monkeypatch):
        """[#39] No ## Verification under PHASE_LOOP_VERIFY_ENFORCE=hard → False (fail-closed).

        A downstream that declares no verification cannot be proven to survive the
        upstream MERGED-pin contract, so under hard enforce the re-verify gate must
        NOT trivial-pass it — it returns False, halting the train at merge_halted (a
        non-human terminal; no human_required added, preserving autonomy-first).
        Mirrors the single-repo execute preflight under hard enforce.
        """
        monkeypatch.setenv("PHASE_LOOP_VERIFY_ENFORCE", "hard")
        repo, roadmap = self._make_reverify_repo(tmp_path, verify_lines="")
        result = _live_reverify(repo, roadmap, "governed")
        assert result is False, (
            "#39 VIOLATED: _live_reverify must fail-closed (False) for a no-verification "
            "node under PHASE_LOOP_VERIFY_ENFORCE=hard — else a no-verification downstream "
            "merges unverified against the merged pin"
        )

    def test_no_verification_warn_explicit_returns_true(self, tmp_path: Path, monkeypatch):
        """[#39] The same node under an explicit warn → True (unchanged trivial pass)."""
        monkeypatch.setenv("PHASE_LOOP_VERIFY_ENFORCE", "warn")
        repo, roadmap = self._make_reverify_repo(tmp_path, verify_lines="")
        assert _live_reverify(repo, roadmap, "governed") is True

    def test_exception_returns_false(self, tmp_path: Path):
        """Non-existent workspace → exception → False (fail-safe)."""
        result = _live_reverify(
            tmp_path / "nonexistent-repo",
            tmp_path / "nonexistent-repo" / "specs" / "plan.md",
            "governed",
        )
        assert result is False, (
            "INV-6 VIOLATED: _live_reverify must return False (fail-safe) "
            "when an exception is raised (e.g. workspace does not exist)"
        )


# ---------------------------------------------------------------------------
# agent-harness#236: phase alias threaded into the train re-verify
# run_verification call

class TestTrainReverifyPhaseAlias236:
    """_live_reverify must thread its resolved ``phase`` into run_verification's
    ``phase_alias`` parameter, so verification.json records the actual phase
    that was verified instead of falling back to 'unknown'.

    Follow-up from agent-harness#85(b) (agent-harness#235), which threaded the
    live run alias on the execute path (runner.py). agent-harness#236 is the
    same fix on the train re-verify path: ``_live_reverify`` resolves
    ``phase = snapshot.current_phase`` and uses it for ``find_plan_artifact`` --
    but pre-fix, that resolved phase was never passed on to
    ``run_verification``, so verification.json's ``_phase_alias()`` fell back
    to its LAST-RESORT re-read of ``state.json``'s persisted ``current_phase``.

    This test persists state.json with ``current_phase=None`` (while ``P1`` is
    at ``awaiting_phase_closeout``) so that last-resort fallback would read
    'unknown' if the fix under test were absent. reconcile() -- called fresh
    inside ``_live_reverify`` -- recomputes ``current_phase="P1"`` from the
    persisted ``phases`` dict regardless of the stale persisted
    ``current_phase`` (verified directly: reconcile() on this fixture returns
    ``current_phase="P1"``), so the two diverge and the discrimination is
    genuine: pre-fix 'unknown', post-fix 'P1'.
    """

    def test_reverify_records_resolved_phase_not_unknown(self, tmp_path: Path):
        import json
        import subprocess

        from phase_loop_test_utils import make_repo, write_phase_plan
        from phase_loop_runtime import train_runner
        from phase_loop_runtime.models import utc_now
        from phase_loop_runtime.provenance import snapshot_provenance
        from phase_loop_runtime.state import write_state

        repo = make_repo(tmp_path)
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text("# Roadmap\n\n### Phase 0 — P1 (P1)\n\n")
        subprocess.run(["git", "add", "specs/phase-plans-v1.md"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "single-phase roadmap"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )

        body = (
            "# P1\n\n"
            "## Lanes\n\n"
            "### SL-0 - P1\n"
            "- **Owned files**: `work.md`\n\n"
            "## Verification\n\n"
            '- `python3 -c "import sys; sys.exit(0)"`\n'
        )
        plan = write_phase_plan(repo, "P1", roadmap, body=body)
        subprocess.run(
            ["git", "add", str(plan.relative_to(repo))],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "add plan"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )

        # Persist state with current_phase=None (but P1 at awaiting_phase_closeout)
        # so verification_evidence._phase_alias's LAST-RESORT state.json read
        # would produce 'unknown' if phase_alias were not threaded -- while
        # reconcile() itself recomputes current_phase="P1" from the persisted
        # phases dict (see class docstring), so _live_reverify's own
        # ``phase = snapshot.current_phase`` resolves "P1" correctly and the
        # only question is whether that resolved value reaches verification.json.
        state = StateSnapshot(
            timestamp=utc_now(),
            repo=str(repo),
            roadmap=str(roadmap),
            phases={"P1": "awaiting_phase_closeout"},
            current_phase=None,
            **snapshot_provenance(roadmap),
        )
        write_state(repo, state)

        result = train_runner._live_reverify(repo, roadmap, "governed")
        assert result is True, "setup regression: verification command should have passed"

        reverify_dirs = sorted((repo / ".phase-loop" / "runs").glob("*-reverify"))
        assert reverify_dirs, "expected _live_reverify to write a run directory"
        artifact = json.loads((reverify_dirs[-1] / "verification.json").read_text())
        assert artifact["phase_alias"] == "P1", (
            "agent-harness#236 VIOLATED: verification.json recorded "
            f"{artifact['phase_alias']!r} instead of 'P1' -- the phase resolved "
            "by _live_reverify (snapshot.current_phase) was not threaded into "
            "the run_verification call as phase_alias"
        )


# ---------------------------------------------------------------------------
# BLOCK 2: End-to-end reverify — real post-P3 workspace, real verification

class TestBlock2ReverifyEndToEnd:
    """End-to-end regression guard for the false-green killer (BLOCK 2).

    The post-P3 workspace state (awaiting_phase_closeout) is reproduced via
    write_state with correct provenance — the smallest faithful reproduction
    that exercises the actual _live_reverify→verification path without stubbing
    _reverify_fn.  Injecting via a real run_loop call would require skill-bundle
    infrastructure (PHASE_LOOP_RUNNER_REPO_ROOT / dotfiles tree) that is absent
    in standalone CI; the write_state approach produces identical reconcile()
    output since reconcile() reads the persisted state file directly.

    PRE-FIX BEHAVIOR CONFIRMED (before the false-green-killer fix):
      _live_reverify called run_loop(workspace, roadmap_path, run_mode=run_mode).
      run_loop found the node at awaiting_phase_closeout with closeout_mode=
      "manual" (default), dispatched into the bare `break` at runner.py:1897 —
      no executor, no verification — and returned the cached P3 snapshot with
      closeout_terminal_status=None, human_required=False, blocker_class=None.
      _live_reverify mapped that to True (the false green).  Confirmed by
      running the test against the pre-fix code: it failed with
      "AssertionError: BLOCK 2 REGRESSION: _live_reverify returned True ...".

    POST-FIX BEHAVIOR: _live_reverify runs the plan's verification commands
    directly.  A command that reads the pin file and exits 1 when it contains
    'BREAKING' causes _live_reverify to return False → merge is halted.
    """

    def _make_post_p3_workspace(self, tmp_path: Path) -> tuple[Path, Path]:
        """Set up the smallest faithful post-P3 workspace.

        Creates a git repo with a single-phase roadmap and a plan whose
        ## Verification section contains a command that reads
        ``upstream-version.txt`` and exits 1 if it contains ``BREAKING``.

        The workspace state is set to awaiting_phase_closeout via write_state
        (with correct provenance) so that reconcile() returns current_phase=P1
        at awaiting_phase_closeout — the same state a real run_loop call leaves.
        """
        import subprocess
        from phase_loop_test_utils import make_repo, write_phase_plan
        from phase_loop_runtime.models import utc_now
        from phase_loop_runtime.provenance import snapshot_provenance
        from phase_loop_runtime.state import write_state

        repo = make_repo(tmp_path)
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text("# Roadmap\n\n### Phase 0 — P1 (P1)\n\n")
        subprocess.run(["git", "add", "specs/phase-plans-v1.md"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "p3 roadmap"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )

        # Plan whose verification reads the pin file and fails on BREAKING.
        verify_cmd = (
            "python3 -c \""
            "import sys, pathlib; "
            "v = pathlib.Path('upstream-version.txt').read_text().strip(); "
            "sys.exit(1 if 'BREAKING' in v else 0)"
            "\""
        )
        body = (
            "# P1\n\n"
            "## Lanes\n\n"
            "### SL-0 - P1\n"
            "- **Owned files**: `work.md`\n\n"
            "## Verification\n\n"
            f"- `{verify_cmd}`\n"
        )
        plan = write_phase_plan(repo, "P1", roadmap, body=body)
        subprocess.run(
            ["git", "add", str(plan.relative_to(repo))],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "p3 plan"],
            cwd=repo, check=True, stdout=subprocess.DEVNULL,
        )

        # Persist awaiting_phase_closeout state (matching provenance).
        # reconcile() reads load_state(repo) first and restores this status,
        # identical to what a real run_loop call would leave on disk.
        state = StateSnapshot(
            timestamp=utc_now(),
            repo=str(repo),
            roadmap=str(roadmap),
            phases={"P1": "awaiting_phase_closeout"},
            current_phase="P1",
            **snapshot_provenance(roadmap),
        )
        write_state(repo, state)

        # Initial upstream-version.txt (non-breaking) before P4 re-injection.
        (repo / "upstream-version.txt").write_text("sha-DRAFT-abc123\n")
        return repo, roadmap

    def test_breaking_merged_pin_makes_reverify_return_false(self, tmp_path: Path):
        """CONTRACT-BREAKING merged pin → _live_reverify returns False → merge halted.

        set_upstream_ref writes 'BREAKING-SHA-INCOMPATIBLE' into
        upstream-version.txt.  The plan's verification command reads that file
        and exits 1.  _live_reverify must return False.

        Against the PRE-FIX code: _live_reverify returned True (false green —
        run_loop hit the awaiting_phase_closeout + manual no-op bare break).
        Against the POST-FIX code: _live_reverify returns False (verified here).
        """
        from phase_loop_runtime.cross_repo_channel import ChannelDescriptor, set_upstream_ref

        repo, roadmap = self._make_post_p3_workspace(tmp_path)

        # Inject a CONTRACT-BREAKING merged SHA (the P4 set_upstream_ref call).
        channel = ChannelDescriptor(kind="pin", params={"file": "upstream-version.txt"})
        set_upstream_ref(repo, channel, "BREAKING-SHA-INCOMPATIBLE")

        # The verification command reads upstream-version.txt → 'BREAKING' → exits 1.
        result = _live_reverify(repo, roadmap, "governed")
        assert result is False, (
            "BLOCK 2 REGRESSION: _live_reverify returned True with a CONTRACT-BREAKING "
            "merged pin.\nupstream-version.txt now contains 'BREAKING-SHA-INCOMPATIBLE'; "
            "the plan's verification command should have exited 1.\n"
            "Pre-fix: this returned True (run_loop no-op); post-fix: must be False."
        )

    def test_compatible_merged_pin_makes_reverify_return_true(self, tmp_path: Path):
        """Compatible merged pin → _live_reverify returns True → merge proceeds."""
        from phase_loop_runtime.cross_repo_channel import ChannelDescriptor, set_upstream_ref

        repo, roadmap = self._make_post_p3_workspace(tmp_path)

        # Inject a compatible merged SHA (no 'BREAKING').
        channel = ChannelDescriptor(kind="pin", params={"file": "upstream-version.txt"})
        set_upstream_ref(repo, channel, "sha-MERGED-COMPATIBLE-abc123")

        # The verification command reads upstream-version.txt → no BREAKING → exits 0.
        result = _live_reverify(repo, roadmap, "governed")
        assert result is True, (
            "BLOCK 2 REGRESSION: _live_reverify returned False with a compatible "
            "merged pin — verification falsely rejected.\n"
            "upstream-version.txt contains 'sha-MERGED-COMPATIBLE-abc123'; "
            "the plan's verification command should have exited 0."
        )


# ---------------------------------------------------------------------------
# INV-7: run_loop failure contract — a genuine failure ALWAYS emits a signal

class TestInvariant7RunLoopFailureContract:
    """Pin that run_loop ALWAYS emits at least one failure signal on a genuine
    verification failure.

    Two complementary pins:
      (a) Real snapshot-construction path (status_snapshot on a pre-seeded repo).
      (b) Structural: the helper functions that COERCE all failure paths to
          non-None signals are themselves verified to produce non-None values.

    NOTE: After the false-green-killer fix, _live_reverify no longer reads
    run_loop's snapshot signals — it directly runs verification commands.
    This invariant now guards run_loop's standalone failure contract rather
    than the _live_reverify mechanism.  It remains important for callers that
    DO consume run_loop's snapshot signals (e.g. the standalone CLI, INV-5
    autonomy boundary checks).
    """

    # -----------------------------------------------------------------------
    # Part (a): real snapshot-construction path — pre-seeded repo

    def test_pre_seeded_verification_failure_snapshot_carries_signal(
        self, tmp_path: Path
    ):
        """status_snapshot() on a repo with a repeated_verification_failure
        LoopEvent returns a snapshot with blocker_class non-None.

        This exercises runner.reconcile() / status_snapshot() — the same
        code path run_loop uses to build its return value after a verification
        failure.  Changing run_loop's failure output so that reconcile() no
        longer sees the signal would make this test red.
        """

        from phase_loop_runtime.events import append_event
        from phase_loop_runtime.models import LoopEvent, utc_now
        from phase_loop_runtime.provenance import event_provenance
        from phase_loop_runtime.runner import status_snapshot

        repo = tmp_path / "repo-v"
        repo.mkdir()
        # Minimal git repo (status_snapshot calls snapshot_provenance which
        # only needs the roadmap file; no git commands needed).
        roadmap = repo / "specs" / "phase-plans.md"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text(
            "# Roadmap\n\n### Phase 1 - Verify (VERIFY)\n"
        )

        # Append the exact LoopEvent that run_loop writes after a
        # repeated_verification_failure (runner.py lines 2457-2467 pattern).
        append_event(
            repo,
            LoopEvent(
                timestamp=utc_now(),
                repo=str(repo),
                roadmap=str(roadmap),
                phase="VERIFY",
                action="execute",
                status="blocked",
                model="gpt-5.6-terra",
                reasoning_effort="medium",
                source="invariant-test-fixture",
                blocker={
                    "human_required": False,
                    "blocker_class": "repeated_verification_failure",
                    "blocker_summary": (
                        "INV-7 fixture: synthetic repeated_verification_failure "
                        "mirroring runner.py lines 2458-2466."
                    ),
                    "required_human_inputs": (),
                    "access_attempts": (),
                },
                **event_provenance(roadmap, "VERIFY"),
            ),
        )

        # Call the REAL status_snapshot() — same code path run_loop uses
        # internally to construct its return StateSnapshot.
        snapshot = status_snapshot(repo, roadmap)

        assert snapshot.blocker_class is not None, (
            "INV-7 VIOLATED: status_snapshot() returned a snapshot with "
            "blocker_class=None after a repeated_verification_failure LoopEvent "
            "was appended.  run_loop's snapshot-construction code (reconcile) "
            "is not propagating the blocker signal — _live_reverify would "
            "silently false-green a downstream merge."
        )
        assert snapshot.blocker_class == "repeated_verification_failure", (
            f"INV-7: unexpected blocker_class={snapshot.blocker_class!r}; "
            "expected 'repeated_verification_failure'"
        )

    def test_pre_seeded_verification_failure_causes_reverify_false(
        self, tmp_path: Path
    ):
        """_live_reverify returns False when run_loop returns the snapshot that
        status_snapshot() produces from a pre-seeded verification failure.

        This bridges INV-7a (snapshot carries signal) with the reader (INV-6):
        the ACTUAL snapshot produced by run_loop's internal code path causes
        _live_reverify to return False.
        """
        from unittest.mock import patch

        from phase_loop_runtime.events import append_event
        from phase_loop_runtime.models import LoopEvent, utc_now
        from phase_loop_runtime.provenance import event_provenance
        from phase_loop_runtime.runner import status_snapshot

        repo = tmp_path / "repo-v2"
        repo.mkdir()
        roadmap = repo / "specs" / "phase-plans.md"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text(
            "# Roadmap\n\n### Phase 1 - Verify (VERIFY)\n"
        )
        append_event(
            repo,
            LoopEvent(
                timestamp=utc_now(),
                repo=str(repo),
                roadmap=str(roadmap),
                phase="VERIFY",
                action="execute",
                status="blocked",
                model="gpt-5.6-terra",
                reasoning_effort="medium",
                source="invariant-test-fixture",
                blocker={
                    "human_required": False,
                    "blocker_class": "repeated_verification_failure",
                    "blocker_summary": "INV-7 fixture: synthetic failure.",
                    "required_human_inputs": (),
                    "access_attempts": (),
                },
                **event_provenance(roadmap, "VERIFY"),
            ),
        )

        # Capture the REAL snapshot from status_snapshot() — what run_loop
        # would actually return for this blocked repo state.
        real_snapshot = status_snapshot(repo, roadmap)

        # Now feed that real snapshot through _live_reverify (patching run_loop
        # to return the snapshot we just obtained from real code).
        with patch(
            "phase_loop_runtime.runner.run_loop",
            return_value=(real_snapshot, []),
        ):
            result = _live_reverify(
                repo,
                roadmap,
                "governed",
            )

        assert result is False, (
            "INV-7 VIOLATED: _live_reverify returned True on the snapshot that "
            "status_snapshot() (run_loop's internal snapshot-construction code) "
            "produced for a pre-seeded repeated_verification_failure state.  "
            "The false-green killer does NOT catch the signal that run_loop "
            "actually emits on a verification failure."
        )

    # -----------------------------------------------------------------------
    # Part (b): structural — helper functions that coerce exception paths

    def test_pipeline_branch_blocker_from_error_always_sets_signal(self):
        """_pipeline_branch_blocker_from_error always returns a dict with
        non-None blocker_class in BLOCKER_CLASSES.

        This is the coercing helper for ALL exception paths in run_loop
        (runner.py lines 378-387, 418, 605).  If it could return None, any
        exception during pipeline-branch setup would silently false-green.
        """
        from phase_loop_runtime.models import BLOCKER_CLASSES
        from phase_loop_runtime.runner import _pipeline_branch_blocker_from_error

        class _BareException(Exception):
            pass

        class _TaggedException(Exception):
            blocker_class = "missing_secret"
            blocker_summary = "tagged exc summary"

        class _EmptyBlocker(Exception):
            blocker_class = None  # malformed; the helper must still coerce

        test_cases = [
            _BareException("bare exception — no blocker_class attribute"),
            _TaggedException("tagged — has valid blocker_class"),
            _EmptyBlocker("None blocker_class — coerce to contract_bug"),
            RuntimeError("generic runtime error"),
            ValueError("value error with no blocker_class"),
        ]

        for exc in test_cases:
            result = _pipeline_branch_blocker_from_error(exc)
            bc = result.get("blocker_class")
            assert bc is not None, (
                f"INV-7 VIOLATED: _pipeline_branch_blocker_from_error({exc!r}) "
                "returned blocker_class=None; all exception paths must produce "
                "a non-None blocker_class so _live_reverify can detect failure."
            )
            assert bc in BLOCKER_CLASSES, (
                f"INV-7 VIOLATED: _pipeline_branch_blocker_from_error({exc!r}) "
                f"returned blocker_class={bc!r} which is not in BLOCKER_CLASSES."
            )

    def test_blocker_site_count_in_runner_is_non_empty(self):
        """runner.py contains a non-trivial number of repeated_verification_failure
        sites — asserts the structural coverage is not vacuous.

        A future refactor that removes all signal-setting sites without updating
        this test would make it red (count drops to zero).
        """
        import inspect
        import re

        import phase_loop_runtime.runner as runner_mod

        source = inspect.getsource(runner_mod)

        # Count explicit repeated_verification_failure assignments in runner.py.
        rvf_sites = len(re.findall(r'"repeated_verification_failure"', source))
        assert rvf_sites >= 10, (
            f"INV-7 VIOLATED: only {rvf_sites} 'repeated_verification_failure' "
            "sites found in runner.py (expected ≥10).  The structural guarantee "
            "that run_loop always sets a failure signal may have eroded — verify "
            "that all verification-failure code paths still emit a blocker."
        )

        # Count non-None blocker_class defaults in coercing helpers.
        coerce_sites = len(re.findall(
            r'or "repeated_verification_failure"|or "contract_bug"',
            source,
        ))
        assert coerce_sites >= 2, (
            f"INV-7 VIOLATED: only {coerce_sites} coercing-default sites found "
            "in runner.py (expected ≥2 — the closeout reader and "
            "_pipeline_branch_blocker_from_error each contribute one).  "
            "A removed default would let a failure path silently emit None."
        )


# ---------------------------------------------------------------------------
# agent-harness#60 (roadmap-format-handling half): a format defect that survives
# parse (a duplicated node block) must be caught by run_train's Step-0 schema
# gate as preflight_failed with ZERO publish calls and an actionable, node-named
# diagnostic — binding the format fix to INV-3's zero-PR contract.

TRAIN_DUP_NODE_MD = TRAIN_2NODE_MD + (
    "\n### Node: repo-a / specs/plan-a.md\n\n"
    "**Depends on:** (none)\n**Channel:** (none)\n"
)


class TestIssue60FormatDefectZeroPRs:
    def test_duplicate_node_train_preflight_failed_zero_publish(self, tmp_path: Path):
        roadmap = parse_train_roadmap(TRAIN_DUP_NODE_MD)  # parse tolerates dup
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        publish_log: List[str] = []

        def _publish_spy(workspace: Path, owned_paths, *, draft: bool, **kw):
            publish_log.append(workspace.name)
            return {"status": "published", "branch": "b", "head_sha": "s", "pr_url": "u"}

        result = run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_publish_spy,
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,  # repo-preflight would pass; schema gate must fire first
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
        )

        assert result["status"] == "preflight_failed", result
        assert publish_log == [], f"format defect must open zero PRs; got {publish_log!r}"
        joined = " ".join(result["errors"])
        assert "(T-F)" in joined and "repo-a/specs/plan-a.md" in joined, (
            f"diagnostic must be coded and name the duplicated node; got: {result['errors']}"
        )
        assert not ledger.exists() or read_ledger(ledger) == {}, "no ledger records on schema failure"


# ---------------------------------------------------------------------------
# RESIDUAL (v10) TDD falsifiers — SL-0 immutable tests-only RED boundary

class TestResidualInvariants:
    """Guarded TDD falsifiers for RESIDUAL: Broker, Train, and Channel Residuals.

    When PHASE_LOOP_TDD_EXPECT_RESIDUAL is NOT set (or != "1"), these tests
    pass cleanly (default-GREEN). When PHASE_LOOP_TDD_EXPECT_RESIDUAL=1, these
    tests activate and fail (RED) against pre-implementation production code at
    their named guarantees.
    """

    def _is_activated(self) -> bool:
        return os.environ.get("PHASE_LOOP_TDD_EXPECT_RESIDUAL") == "1"

    def test_residual_tdd_chronology(self, tmp_path: Path):
        """EC-RESIDUAL-0: residual_tdd_chronology TDD falsifier.

        Guards production-facing commit-identity chronology API, git graph ancestry derivation, premerge attribution, and F841 triage state.
        """
        if not self._is_activated():
            return

        import inspect
        import subprocess
        from phase_loop_test_utils import make_repo
        from phase_loop_runtime.legible_evidence import LegibleChronologyError, validate_chronology

        repo_root = Path(__file__).resolve().parents[2]
        test_file = Path("phase-loop-runtime/tests/test_train_invariants.py")
        src_dir = repo_root / "phase-loop-runtime" / "src" / "phase_loop_runtime"
        assert (repo_root / test_file).exists(), "test_train_invariants.py missing from git inventory"
        assert src_dir.exists(), "phase_loop_runtime source tree missing from git inventory"

        def _commit(repo: Path, message: str, timestamp: str) -> None:
            environment = {
                **os.environ,
                "GIT_AUTHOR_DATE": timestamp,
                "GIT_COMMITTER_DATE": timestamp,
            }
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo,
                check=True,
                capture_output=True,
                env=environment,
            )

        # 1. Build a real temporary git repository with valid commit graph ancestry
        chron_repo = make_repo(tmp_path / "chronology_graph_valid")
        (chron_repo / "README.md").write_text("initial", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=chron_repo, check=True, capture_output=True)
        _commit(chron_repo, "C0: initial", "2029-01-01T00:00:00+0000")

        (chron_repo / "test_file.py").write_text("# test", encoding="utf-8")
        subprocess.run(["git", "add", "test_file.py"], cwd=chron_repo, check=True, capture_output=True)
        _commit(chron_repo, "C_test: tests landing", "2030-01-01T00:00:00+0000")
        c_test = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=chron_repo, check=True, capture_output=True, text=True
        ).stdout.strip()

        (chron_repo / "src_file.py").write_text("# impl", encoding="utf-8")
        subprocess.run(["git", "add", "src_file.py"], cwd=chron_repo, check=True, capture_output=True)
        _commit(chron_repo, "C_impl: implementation", "2020-01-01T00:00:00+0000")
        c_impl = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=chron_repo, check=True, capture_output=True, text=True
        ).stdout.strip()

        # 2. Build inverted commit graph topology
        chron_repo_inv = make_repo(tmp_path / "chronology_graph_inverted")
        (chron_repo_inv / "README.md").write_text("initial", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=chron_repo_inv, check=True, capture_output=True)
        _commit(chron_repo_inv, "C0: initial", "2029-01-01T00:00:00+0000")
        (chron_repo_inv / "src_file.py").write_text("# impl early", encoding="utf-8")
        subprocess.run(["git", "add", "src_file.py"], cwd=chron_repo_inv, check=True, capture_output=True)
        _commit(chron_repo_inv, "C_impl_inv", "2030-01-01T00:00:00+0000")
        c_impl_inv = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=chron_repo_inv, check=True, capture_output=True, text=True
        ).stdout.strip()

        # Keep the inverted history linear: implementation is the direct
        # ancestor of the later tests landing.
        (chron_repo_inv / "test_file.py").write_text("# test late", encoding="utf-8")
        subprocess.run(["git", "add", "test_file.py"], cwd=chron_repo_inv, check=True, capture_output=True)
        _commit(chron_repo_inv, "C_test_inv", "2020-01-01T00:00:00+0000")
        c_test_inv = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=chron_repo_inv, check=True, capture_output=True, text=True
        ).stdout.strip()

        # 3. Freeze production-facing API: validate_chronology must receive commit identities and own the check
        chron_params = inspect.signature(validate_chronology).parameters
        has_commit_ancestry_api = {
            "tests_landing_commit",
            "implementation_base_commit",
        }.issubset(chron_params)

        valid_graph_accepted = False
        inverted_graph_rejected = False
        if has_commit_ancestry_api:
            try:
                validate_chronology(
                    chron_repo,
                    tests_landing_commit=c_test,
                    implementation_base_commit=c_impl,
                )
            except LegibleChronologyError:
                pass
            else:
                valid_graph_accepted = True
            try:
                validate_chronology(
                    chron_repo_inv,
                    tests_landing_commit=c_test_inv,
                    implementation_base_commit=c_impl_inv,
                )
            except LegibleChronologyError:
                inverted_graph_rejected = True

        # Negative control / mutation check: calling validate_chronology with tests_landing_ancestor_of_base=True on inverted graph accepts invalid topology
        rejected_caller_bool = False
        try:
            validate_chronology(chron_repo_inv, tests_landing_ancestor_of_base=True)
        except (LegibleChronologyError, TypeError):
            rejected_caller_bool = True

        caller_boolean_trusted = not rejected_caller_bool

        # 4. Separately retain governed_premerge content-block then structural-hold non_convergence regression
        from phase_loop_runtime.governed_premerge import GateResult, ReviewFinding, run_governed_premerge_loop

        findings_round1 = [
            ReviewFinding(
                code="review_block",
                reason="content block",
                severity="block",
                blocker_class="review_gate_block",
            )
        ]
        gate1 = GateResult(ran=True, promoted=False, findings=tuple(findings_round1), reason="content_rejected")
        gate2 = GateResult(ran=True, promoted=False, degraded=False, findings=(), reason="content_rejected")

        invokes = [gate1, gate2]

        def mock_invoke(**kwargs):
            return invokes.pop(0) if invokes else gate2

        def mock_apply_fix(round_num, artifact, findings):
            return artifact

        res_loop = run_governed_premerge_loop(
            artifact="test_artifact",
            author_executor="gemini",
            author_vendors=("google",),
            run_mode="governed",
            max_rounds=2,
            invoke=mock_invoke,
            apply_fix=mock_apply_fix,
        )

        premerge_reason_ok = (res_loop.reason == "non_convergence")

        # 5. Check production triage evidence file
        triage_file = repo_root / "plans" / "evidence" / "v10-RESIDUAL-f841-triage.md"
        triage_file_exists = triage_file.exists()

        if (
            not has_commit_ancestry_api
            or not valid_graph_accepted
            or not inverted_graph_rejected
            or caller_boolean_trusted
            or not premerge_reason_ok
            or not triage_file_exists
        ):
            defect_details = []
            if not has_commit_ancestry_api:
                defect_details.append("validate_chronology lacks production commit-identity ancestry parameters")
            elif not valid_graph_accepted:
                defect_details.append("validate_chronology rejected a real valid tests-before-implementation graph")
            elif not inverted_graph_rejected:
                defect_details.append("validate_chronology accepted a real inverted tests/implementation graph")
            if caller_boolean_trusted:
                defect_details.append("validate_chronology trusts caller boolean (accepts True on inverted Git graph)")
            if not premerge_reason_ok:
                defect_details.append(f"governed_premerge non_convergence returned {res_loop.reason!r}")
            if not triage_file_exists:
                defect_details.append("plans/evidence/v10-RESIDUAL-f841-triage.md missing")

            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_tdd_chronology — "
                f"chronology contract defects present: {'; '.join(defect_details)}"
            )

    def test_residual_publish_identity_includes_base(self, tmp_path: Path):
        """EC-RESIDUAL-1: residual_publish_identity_includes_base TDD falsifier.

        Guards four-argument publish identity: (repo, branch, base, head_sha) and AST value-flow binding.
        """
        if not self._is_activated():
            return

        import ast
        import inspect
        from dataclasses import fields, replace
        from unittest.mock import patch

        from test_convergence_live_enable import _activated_publish_fixture
        from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
        from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
        from phase_loop_runtime.convergence import contracts
        from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
        from phase_loop_runtime.convergence.broker.verbs import BrokerService
        from phase_loop_runtime.convergence.contracts import (
            BrokerTerminalEvidence,
            PublishCommittedBranchResult,
        )
        from phase_loop_runtime.convergence.provider_contracts import (
            PROVIDER_COMPLETION_CLASSIFICATIONS,
            TerminalOutcomeState,
        )

        defect_details = []

        # 0. Prove 3-argument call raises TypeError
        try:
            contracts.publish_committed_branch_idempotency_key("repo-a", "feat/x", "main")
        except TypeError:
            pass
        else:
            defect_details.append("3-argument call to publish_committed_branch_idempotency_key did not raise TypeError")

        try:
            main_key = contracts.publish_committed_branch_idempotency_key("repo-a", "feat/x", "main", "sha-head")
            release_key = contracts.publish_committed_branch_idempotency_key("repo-a", "feat/x", "release", "sha-head")
        except TypeError as exc:
            defect_details.append(f"4-argument publish identity call failed: {exc}")
        else:
            if main_key == release_key:
                defect_details.append("publish identity does not separate otherwise-identical requests by base")

        # Exercise the real producer, admission, evidence, and replay decisions.
        # The provider adapter is the only fake boundary: same-base retry must
        # replay without a second effect, while a different base must be admitted
        # as a distinct effect. A dead compliant helper call followed by a
        # base-blind decision cannot satisfy these observations.
        try:
            repo, evidence_root, publish_request = _activated_publish_fixture(
                tmp_path, label="residual-base", branch="feat/base"
            )
            envelope_main = replace(publish_request.admission, base="main")
            envelope_release = replace(publish_request.admission, base="release")
            if envelope_main.idempotency_key == envelope_release.idempotency_key:
                defect_details.append("PreAdmissionEnvelope.idempotency_key aliases different bases")

            request_main = replace(publish_request, admission=envelope_main, base="main")
            request_release = replace(publish_request, admission=envelope_release, base="release")

            provider_requests = []

            class _CountingSuccessAdapter:
                def execute(self, request):
                    provider_requests.append(request)
                    return (
                        PublishCommittedBranchResult(
                            request.branch,
                            request.head_sha,
                            f"https://example.invalid/{request.base}",
                        ),
                        BrokerTerminalEvidence(
                            "provider-boundary",
                            TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED.value,
                            f"https://example.invalid/{request.base}",
                        ),
                    )

            service = BrokerService(
                LinearizableAdmissionStore(evidence_root, lambda _request: True),
                BrokerEvidenceStore(evidence_root),
                _CountingSuccessAdapter(),
                contracts=PROVIDER_COMPLETION_CLASSIFICATIONS,
            )
            main_result = service.execute(request_main)
            main_retry = service.execute(request_main)
            release_result = service.execute(request_release)
            if not main_result.accepted or not main_retry.accepted or not release_result.accepted:
                defect_details.append("real broker decision did not accept main, its retry, and distinct release base")
            if main_result.evidence.idempotency_key == release_result.evidence.idempotency_key:
                defect_details.append("real broker decision aliased main and release evidence keys")
            if [getattr(request, "base", None) for request in provider_requests] != ["main", "release"]:
                defect_details.append(
                    "real broker admission/replay decision did not deduplicate only the same-base retry"
                )

            captured_legacy_calls = []

            class _LegacyProbeStore:
                @staticmethod
                def authenticated_legacy_records():
                    return {"never-match": {"serialized_repository": publish_request.repo}}

            def _capture_legacy_key(*args, **kwargs):
                captured_legacy_calls.append((args, kwargs))
                return "captured-key"

            legacy_service = BrokerService(None, _LegacyProbeStore(), None)
            with patch(
                "phase_loop_runtime.convergence.broker.verbs.publish_committed_branch_idempotency_key",
                side_effect=_capture_legacy_key,
            ):
                legacy_service._legacy_terminal_replay(request_release, "new-key")
            captured_legacy_binding = None
            if len(captured_legacy_calls) == 1:
                try:
                    captured_legacy_binding = inspect.signature(
                        contracts.publish_committed_branch_idempotency_key
                    ).bind(*captured_legacy_calls[0][0], **captured_legacy_calls[0][1]).arguments
                except TypeError:
                    pass
            if captured_legacy_binding != {
                "repo": publish_request.repo,
                "branch": publish_request.branch,
                "base": "release",
                "head_sha": publish_request.head_sha,
            }:
                defect_details.append(
                    f"BrokerService._legacy_terminal_replay passed wrong key preimage {captured_legacy_calls!r}"
                )
        except Exception as exc:
            defect_details.append(f"runtime publish base value-flow control failed: {exc}")

        # 1. EvidenceRecord dataclass, serialization, and real BrokerEvidenceStore lifecycle checks
        ev_fields = {f.name for f in fields(EvidenceRecord)}
        if "base" not in ev_fields:
            defect_details.append("EvidenceRecord dataclass missing 'base' field")
        else:
            try:
                rec = EvidenceRecord(
                    idempotency_key="k",
                    state=TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                    evidence_reference="ref",
                    base="main",
                )
                rec_dict = rec.to_json() if hasattr(rec, "to_json") else getattr(rec, "__dict__", {})
                if not isinstance(rec_dict, dict) or rec_dict.get("base") != "main":
                    defect_details.append("EvidenceRecord.to_json() failed to serialize exact 'base' value")

                from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
                ev_store = BrokerEvidenceStore(tmp_path / "evidence")
                try:
                    ev_store.record_intent("k", base="main")
                except TypeError:
                    defect_details.append("BrokerEvidenceStore.record_intent lacks future 'base' parameter")
                else:
                    intent_replay = ev_store.replay()
                    if getattr(intent_replay.get("k"), "base", None) != "main":
                        defect_details.append("BrokerEvidenceStore.record_intent discarded exact 'base' value")
                    ev_store.record_terminal(rec)
                    reloaded_dict = ev_store.replay()
                    if not isinstance(reloaded_dict, dict) or "k" not in reloaded_dict:
                        defect_details.append("BrokerEvidenceStore.replay() did not return dict containing key 'k'")
                    elif getattr(reloaded_dict["k"], "base", None) != "main":
                        defect_details.append("BrokerEvidenceStore.replay()['k'] failed to preserve exact 'base' attribute")
            except TypeError as exc:
                defect_details.append(f"EvidenceRecord construction failed with base argument: {exc}")
            except Exception as exc:
                defect_details.append(f"BrokerEvidenceStore lifecycle control raised exception: {exc}")

        # 2. AST Value-Flow & Definition Verifier helper over contracts.py, verbs.py, admission.py, and evidence.py
        def verify_publish_identity_value_flow(contracts_src: str, verbs_src: str, admission_src: str, evidence_src: str) -> list[str]:
            errors = []

            # Check definition in contracts.py
            contracts_ast = ast.parse(contracts_src)
            def_node = next(
                (n for n in ast.walk(contracts_ast) if isinstance(n, ast.FunctionDef) and n.name == "publish_committed_branch_idempotency_key"),
                None
            )
            if def_node is None:
                errors.append("def publish_committed_branch_idempotency_key missing in contracts.py")
            else:
                arg_names = [arg.arg for arg in def_node.args.args]
                if arg_names != ["repo", "branch", "base", "head_sha"]:
                    errors.append(f"signature mismatch: expected ['repo', 'branch', 'base', 'head_sha'], got {arg_names}")
                base_used = any(isinstance(n, ast.Name) and n.id == "base" for n in ast.walk(def_node))
                if not base_used:
                    errors.append("function body does not consume 'base' parameter")

            # Helper to check the single required identity-producing call in each target method.
            def check_call_site(tree: ast.AST, class_name: str, method_name: str, expected_base_expr: str):
                class_node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name), None)
                if class_node is None:
                    return f"class {class_name} missing"
                method_node = next((n for n in ast.walk(class_node) if isinstance(n, ast.FunctionDef) and n.name == method_name), None)
                if method_node is None:
                    return f"method {class_name}.{method_name} missing"

                calls = [n for n in ast.walk(method_node) if isinstance(n, ast.Call) and (
                    (isinstance(n.func, ast.Name) and n.func.id == "publish_committed_branch_idempotency_key") or
                    (isinstance(n.func, ast.Attribute) and n.func.attr == "publish_committed_branch_idempotency_key")
                )]
                if len(calls) != 1:
                    return f"method {class_name}.{method_name} has {len(calls)} calls to publish_committed_branch_idempotency_key (expected exactly 1)"

                call = calls[0]
                total_args = len(call.args) + len(call.keywords)
                if total_args < 4:
                    return f"call in {class_name}.{method_name} has fewer than 4 arguments ({total_args})"

                base_val = None
                if len(call.args) >= 3:
                    base_val = call.args[2]
                else:
                    kw = next((k for k in call.keywords if k.arg == "base"), None)
                    if kw:
                        base_val = kw.value

                if base_val is None:
                    return f"call in {class_name}.{method_name} missing base argument"

                actual_expr = ast.unparse(base_val).strip()
                if actual_expr != expected_base_expr:
                    return f"call in {class_name}.{method_name} base expression is {actual_expr!r}, expected {expected_base_expr!r}"
                return None

            err_producer = check_call_site(contracts_ast, "PreAdmissionEnvelope", "idempotency_key", "self.base")
            if err_producer:
                errors.append(err_producer)

            verbs_ast = ast.parse(verbs_src)
            err_dedup = check_call_site(verbs_ast, "BrokerService", "_dedup_key", "request.base")
            if err_dedup:
                errors.append(err_dedup)

            err_replay = check_call_site(verbs_ast, "BrokerService", "_legacy_terminal_replay", "request.base")
            if err_replay:
                errors.append(err_replay)

            admission_ast = ast.parse(admission_src)
            err_admission = check_call_site(admission_ast, "LinearizableAdmissionStore", "admit_next", "auth.base")
            if err_admission:
                errors.append(err_admission)

            # Check admission.py branch_head helper returns 4-tuple with normalized base attribute in both branches
            store_class = next((n for n in ast.walk(admission_ast) if isinstance(n, ast.ClassDef) and n.name == "LinearizableAdmissionStore"), None)
            if store_class:
                admit_method = next((n for n in ast.walk(store_class) if isinstance(n, ast.FunctionDef) and n.name == "admit_next"), None)
                if admit_method:
                    bh_func = next((n for n in ast.walk(admit_method) if isinstance(n, ast.FunctionDef) and n.name == "branch_head"), None)
                    if bh_func:
                        ret_tuples = [n.value for n in ast.walk(bh_func) if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)]
                        if not ret_tuples:
                            errors.append("admission.py branch_head has no return tuple statements")
                        for t in ret_tuples:
                            if len(t.elts) != 4:
                                errors.append(f"admission.py branch_head returns tuple with {len(t.elts)} elements (expected exactly 4)")
                            else:
                                el = t.elts[2]
                                is_base_attr = isinstance(el, ast.Attribute) and el.attr == "base"
                                if not is_base_attr:
                                    errors.append(f"admission.py branch_head tuple element 3 is {ast.unparse(el)!r}, expected normalized base attribute (.base)")

            # Check BrokerService._replay in verbs.py contains ast.Compare between current.base and request.base
            bs_class = next((n for n in ast.walk(verbs_ast) if isinstance(n, ast.ClassDef) and n.name == "BrokerService"), None)
            if bs_class:
                replay_method = next((n for n in ast.walk(bs_class) if isinstance(n, ast.FunctionDef) and n.name == "_replay"), None)
                if replay_method:
                    has_base_cmp = False
                    for node in ast.walk(replay_method):
                        if isinstance(node, ast.Compare):
                            left_str = ast.unparse(node.left).strip()
                            comp_strs = [ast.unparse(c).strip() for c in node.comparators]
                            operands = [left_str] + comp_strs
                            if "current.base" in operands and "request.base" in operands:
                                has_base_cmp = True
                                break
                    if not has_base_cmp:
                        errors.append("BrokerService._replay method AST missing exact ast.Compare between current.base and request.base")

            # Check EvidenceRecord class in evidence.py
            evidence_ast = ast.parse(evidence_src)
            ev_class = next((n for n in ast.walk(evidence_ast) if isinstance(n, ast.ClassDef) and n.name == "EvidenceRecord"), None)
            if ev_class is None:
                errors.append("class EvidenceRecord missing in evidence.py")
            else:
                has_base_field = any(isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "base" for stmt in ev_class.body)
                if not has_base_field:
                    errors.append("EvidenceRecord class missing 'base' field annotation")

            # Check all production EvidenceRecord(...) calls bind base
            for fpath, tree in (("verbs.py", verbs_ast), ("evidence.py", evidence_ast)):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
                        if func_name == "EvidenceRecord":
                            kw_names = {k.arg for k in node.keywords}
                            if "base" not in kw_names and len(node.args) < 4:
                                errors.append(f"EvidenceRecord(...) call in {fpath} missing base parameter")

            return errors

        # 3. Read production source files and verify AST value flow
        repo_root = Path(__file__).resolve().parents[2]
        contracts_path = repo_root / "phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py"
        verbs_path = repo_root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py"
        admission_path = repo_root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py"
        evidence_path = repo_root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/evidence.py"

        contracts_text = contracts_path.read_text(encoding="utf-8")
        verbs_text = verbs_path.read_text(encoding="utf-8")
        admission_text = admission_path.read_text(encoding="utf-8")
        evidence_text = evidence_path.read_text(encoding="utf-8")

        prod_errors = verify_publish_identity_value_flow(contracts_text, verbs_text, admission_text, evidence_text)
        if prod_errors:
            defect_details.extend(prod_errors)

        # 4. Mandatory class/method-bounded source mutants for all four publish identity sites & _replay
        def _mutate_method(src: str, class_name: str, method_name: str, target: str, replacement: str) -> tuple[str, Optional[str]]:
            try:
                tree = ast.parse(src)
            except Exception as exc:
                return src, f"ast.parse failed: {exc}"
            class_node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name), None)
            if not class_node:
                return src, f"class {class_name} missing"
            method_node = next((n for n in ast.walk(class_node) if isinstance(n, ast.FunctionDef) and n.name == method_name), None)
            if not method_node:
                return src, f"method {class_name}.{method_name} missing"
            target_node = ast.parse(target, mode="eval").body
            replacement_node = ast.parse(replacement, mode="eval").body
            target_shape = ast.dump(target_node, include_attributes=False)
            selected = None
            if method_name == "_replay":
                for comparison in (
                    node for node in ast.walk(method_node) if isinstance(node, ast.Compare)
                ):
                    operands = [comparison.left, *comparison.comparators]
                    operand_shapes = {
                        ast.dump(node, include_attributes=False) for node in operands
                    }
                    if {
                        ast.dump(ast.parse("current.base", mode="eval").body, include_attributes=False),
                        ast.dump(ast.parse("request.base", mode="eval").body, include_attributes=False),
                    }.issubset(operand_shapes):
                        selected = next(
                            (
                                node
                                for node in operands
                                if ast.dump(node, include_attributes=False) == target_shape
                            ),
                            None,
                        )
                        break
            else:
                identity_calls = [
                    node
                    for node in ast.walk(method_node)
                    if isinstance(node, ast.Call)
                    and (
                        isinstance(node.func, ast.Name)
                        and node.func.id == "publish_committed_branch_idempotency_key"
                        or isinstance(node.func, ast.Attribute)
                        and node.func.attr == "publish_committed_branch_idempotency_key"
                    )
                ]
                if len(identity_calls) == 1:
                    call = identity_calls[0]
                    selected = (
                        call.args[2]
                        if len(call.args) >= 3
                        else next(
                            (keyword.value for keyword in call.keywords if keyword.arg == "base"),
                            None,
                        )
                    )
                    if selected is not None and ast.dump(selected, include_attributes=False) != target_shape:
                        selected = None
            if selected is None:
                return src, f"exact target {target!r} missing from {class_name}.{method_name} identity decision"

            class _ExactNodeMutator(ast.NodeTransformer):
                def visit(self, node):
                    if node is selected:
                        return ast.copy_location(replacement_node, node)
                    return super().visit(node)

            _ExactNodeMutator().visit(method_node)
            ast.fix_missing_locations(tree)
            mutated_src = ast.unparse(tree) + "\n"
            if ast.dump(ast.parse(mutated_src)) == ast.dump(ast.parse(src)):
                return src, f"mutation of {target!r} in {class_name}.{method_name} resulted in no-op"
            return mutated_src, None

        # Site 1: PreAdmissionEnvelope.idempotency_key in contracts.py
        mut1_contracts, err1_mut = _mutate_method(contracts_text, "PreAdmissionEnvelope", "idempotency_key", "self.base", '"main"')
        if err1_mut:
            defect_details.append(f"Site 1 mutant error: {err1_mut}")
        else:
            errs1 = verify_publish_identity_value_flow(mut1_contracts, verbs_text, admission_text, evidence_text)
            if not errs1:
                defect_details.append("AST verifier failed to reject Site 1 wrong-base mutant in PreAdmissionEnvelope.idempotency_key")

        # Site 2: BrokerService._dedup_key in verbs.py
        mut2_verbs, err2_mut = _mutate_method(verbs_text, "BrokerService", "_dedup_key", "request.base", "request.branch")
        if err2_mut:
            defect_details.append(f"Site 2 mutant error: {err2_mut}")
        else:
            errs2 = verify_publish_identity_value_flow(contracts_text, mut2_verbs, admission_text, evidence_text)
            if not errs2:
                defect_details.append("AST verifier failed to reject Site 2 wrong-base mutant in BrokerService._dedup_key")

        # Site 3: BrokerService._legacy_terminal_replay in verbs.py
        mut3_verbs, err3_mut = _mutate_method(verbs_text, "BrokerService", "_legacy_terminal_replay", "request.base", "request.branch")
        if err3_mut:
            defect_details.append(f"Site 3 mutant error: {err3_mut}")
        else:
            errs3 = verify_publish_identity_value_flow(contracts_text, mut3_verbs, admission_text, evidence_text)
            if not errs3:
                defect_details.append("AST verifier failed to reject Site 3 wrong-base mutant in BrokerService._legacy_terminal_replay")

        # Site 4: LinearizableAdmissionStore.admit_next in admission.py
        mut4_admission, err4_mut = _mutate_method(admission_text, "LinearizableAdmissionStore", "admit_next", "auth.base", "auth.branch")
        if err4_mut:
            defect_details.append(f"Site 4 mutant error: {err4_mut}")
        else:
            errs4 = verify_publish_identity_value_flow(contracts_text, verbs_text, mut4_admission, evidence_text)
            if not errs4:
                defect_details.append("AST verifier failed to reject Site 4 wrong-base mutant in LinearizableAdmissionStore.admit_next")

        # Site 5: BrokerService._replay in verbs.py (target current.base)
        mut5_replay, err5_mut = _mutate_method(verbs_text, "BrokerService", "_replay", "current.base", "current.branch")
        if err5_mut:
            defect_details.append(f"Site 5 mutant error: {err5_mut}")
        else:
            errs5 = verify_publish_identity_value_flow(contracts_text, mut5_replay, admission_text, evidence_text)
            if not errs5:
                defect_details.append("AST verifier failed to reject wrong-base mutant in BrokerService._replay")

        if defect_details:
            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_publish_identity_includes_base — "
                f"publish identity base binding defects present: {'; '.join(defect_details)}"
            )

    def test_residual_pr_open_resume_live_head_failure(self, tmp_path: Path):
        """EC-RESIDUAL-2: residual_pr_open_resume_live_head_failure TDD falsifier.

        Guards pr_open resume live-head read failure handling (typed blocked return & ledger row).
        """
        if not self._is_activated():
            return

        # Execute fresh raises/unavailable/success scenarios through run_train;
        # the unavailable case itself rejects restoration of ledger-head fallback.
        sc1_dir = tmp_path / "sc1"
        sc1_dir.mkdir()
        roadmap1 = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map1 = {n.node_id: sc1_dir / n.repo for n in roadmap1.nodes}
        ledger1 = _setup_p3_done(sc1_dir, roadmap1, ws_map1)
        merge_log1: List[str] = []

        def _head_raises(ws, br):
            raise RuntimeError("head unavailable")

        res1 = None
        exc1 = None
        try:
            res1 = run_train(
                roadmap1,
                ledger1,
                run_mode="governed",
                resolve_workspace=lambda n: ws_map1[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub(),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_true,
                _live_pr_head_sha_fn=_head_raises,
                _merge_phase_enabled=True,
                _merge_pr_fn=_make_merge_pr_stub(merge_log1),
                _reverify_fn=lambda ws, rp, rm: True,
                _train_review_fn=_approval_review_fn,
                _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            )
        except Exception as e:
            exc1 = e

        rec1 = read_ledger(ledger1)
        blocked_records1 = [r for r in rec1.values() if isinstance(r, LedgerRecord) and getattr(r, "status", None) == "blocked"]

        # Scenario 2: live-head callback returns unavailable (None)
        sc2_dir = tmp_path / "sc2"
        sc2_dir.mkdir()
        roadmap2 = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map2 = {n.node_id: sc2_dir / n.repo for n in roadmap2.nodes}
        ledger2 = _setup_p3_done(sc2_dir, roadmap2, ws_map2)
        merge_log2: List[str] = []

        res2 = None
        exc2 = None
        try:
            res2 = run_train(
                roadmap2,
                ledger2,
                run_mode="governed",
                resolve_workspace=lambda n: ws_map2[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub(),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_true,
                _live_pr_head_sha_fn=lambda ws, br: None,
                _merge_phase_enabled=True,
                _merge_pr_fn=_make_merge_pr_stub(merge_log2),
                _reverify_fn=lambda ws, rp, rm: True,
                _train_review_fn=_approval_review_fn,
                _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            )
        except Exception as e:
            exc2 = e

        rec2 = read_ledger(ledger2)
        blocked_records2 = [r for r in rec2.values() if isinstance(r, LedgerRecord) and getattr(r, "status", None) == "blocked"]

        # Scenario 3: live-head callback succeeds
        sc3_dir = tmp_path / "sc3"
        sc3_dir.mkdir()
        roadmap3 = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map3 = {n.node_id: sc3_dir / n.repo for n in roadmap3.nodes}
        ledger3 = _setup_p3_done(sc3_dir, roadmap3, ws_map3)
        merge_log3: List[str] = []

        res3 = None
        exc3 = None
        try:
            res3 = run_train(
                roadmap3,
                ledger3,
                run_mode="governed",
                resolve_workspace=lambda n: ws_map3[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub(),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_true,
                _live_pr_head_sha_fn=_live_head_for_p3_done,
                _merge_phase_enabled=True,
                _merge_pr_fn=_make_merge_pr_stub(merge_log3),
                _reverify_fn=lambda ws, rp, rm: True,
                _train_review_fn=_approval_review_fn,
                _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            )
        except Exception as e:
            exc3 = e

        rec3 = read_ledger(ledger3)
        assert isinstance(rec3, dict), "read_ledger must return a dict"

        expected_node = "repo-a/specs/plan-a.md"

        def _typed_failure_ok(result, records, reason):
            detail = result.get("detail") if isinstance(result, dict) else None
            return (
                result is not None
                and result.get("status") == "blocked"
                and result.get("node_id") == expected_node
                and isinstance(detail, dict)
                and detail.get("reason") == reason
                and detail.get("blocker_class") == "live_head_unavailable"
                and len(records) == 1
                and records[0].node_id == expected_node
                and records[0].branch == "feat/train-repo-a"
            )

        failure1_ok = _typed_failure_ok(res1, blocked_records1, "pr_open_live_head_read_failed")
        failure2_ok = _typed_failure_ok(res2, blocked_records2, "pr_open_live_head_unavailable")
        success_ok = (
            exc3 is None
            and res3 is not None
            and res3.get("status") == "merged"
            and merge_log3 == ["repo-a", "repo-b"]
        )

        # Evaluate scenarios against named RED anchor
        if exc1 is not None or exc2 is not None or not failure1_ok or not failure2_ok or merge_log1 or merge_log2 or not success_ok:
            defect_details = []
            if exc1 is not None:
                defect_details.append(f"live head callback exception raised unhandled {exc1}")
            if not failure1_ok:
                defect_details.append("live head exception lacked exact typed blocker, node identity, or durable blocked row")
            if merge_log1:
                defect_details.append(f"live head exception reached merge for {merge_log1!r}")
            if exc2 is not None:
                defect_details.append(f"unavailable live head raised unhandled {exc2}")
            if not failure2_ok:
                defect_details.append("unavailable live head lacked exact typed blocker, node identity, or durable blocked row")
            if merge_log2:
                defect_details.append(f"unavailable live head reached merge for {merge_log2!r}")
            if not success_ok:
                defect_details.append(
                    f"successful live heads returned {res3!r} with merge log {merge_log3!r} and exception {exc3!r}"
                )

            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_pr_open_resume_live_head_failure — "
                f"pr_open resume live head read failure defects present: {'; '.join(defect_details)}"
            )

    def test_residual_non_fab_merge_queue_null_oid(self, tmp_path: Path):
        """EC-RESIDUAL-3: residual_non_fab_merge_queue_null_oid TDD falsifier.

        Guards integrated run_train enqueue and reconcile path, requiring gh pr merge argv to exist and omit --delete-branch.
        """
        if not self._is_activated():
            return

        import json
        import time
        from unittest.mock import patch
        from phase_loop_runtime.train_runner import _fab_queue_bound_merge_wait, _live_merge_pr

        # 1. Direct _fab_queue_bound_merge_wait unit controls
        with patch("phase_loop_runtime.train_runner._live_pr_merged_sha", return_value="sha-MERGED-123"):
            res_merged = _fab_queue_bound_merge_wait(
                tmp_path, "feat/x", base="main", head_sha="sha123",
                poll_interval_s=0.01, poll_timeout_s=0.05,
                clock=time.time, sleep=lambda s: None,
                dequeue_fn=lambda ws, br: True,
            )
            assert res_merged == "sha-MERGED-123", "terminal success outcome mismatch"

        # 2. Integrated run_train execution
        roadmap = parse_train_roadmap(TRAIN_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md",
            status="pr_open",
            branch="feat/train-repo-a",
            head_sha="sha-DRAFT-repo-a",
            pr_url="https://gh.com/repo-a/pr/1",
            merge_order=0,
        ))

        captured_merge_argvs: list[list[str]] = []
        captured_graphql: list[str] = []
        queue_status_reads = [0]

        def fake_subproc_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and cmd[:4] == ["git", "-C", str(tmp_path / "repo-a"), "remote"]:
                return type("CompletedProcess", (), {"returncode": 0, "stdout": "https://github.com/owner/repo-a.git\n", "stderr": ""})()
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "gh" and cmd[1] == "pr" and cmd[2] == "merge":
                captured_merge_argvs.append(list(cmd))
                return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "gh" and cmd[1] == "pr" and cmd[2] == "view":
                requested = next((value for index, value in enumerate(cmd) if index and cmd[index - 1] == "--json"), "")
                if requested == "state,mergeCommit,baseRefName,headRefOid":
                    res_data = json.dumps({
                        "state": "OPEN",
                        "mergeCommit": None,
                        "baseRefName": "main",
                        "headRefOid": "sha-DRAFT-repo-a",
                    })
                elif requested == "number,state,autoMergeRequest":
                    queue_status_reads[0] += 1
                    res_data = json.dumps({"number": 1, "state": "OPEN", "autoMergeRequest": None})
                elif requested == "id":
                    res_data = json.dumps({"id": "PR_node_id"})
                else:
                    res_data = json.dumps({
                        "isDraft": False,
                        "baseRefName": "main",
                        "headRefOid": None,
                    })
                return type("CompletedProcess", (), {"returncode": 0, "stdout": res_data, "stderr": ""})()
            if isinstance(cmd, list) and cmd[:3] == ["gh", "api", "graphql"]:
                query = next((value for value in cmd if isinstance(value, str) and value.startswith("query=")), "")
                captured_graphql.append(query)
                if "dequeuePullRequest" in query:
                    res_data = json.dumps({"data": {"dequeuePullRequest": {"clientMutationId": None}}})
                else:
                    res_data = json.dumps({
                        "data": {"repository": {"pullRequest": {"isInMergeQueue": False}}}
                    })
                return type("CompletedProcess", (), {"returncode": 0, "stdout": res_data, "stderr": ""})()
            return type("CompletedProcess", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        clock_values = iter((0.0, 1.0))

        def _bounded_real_merge(workspace, branch, base="main", head_sha=None, run_id=None):
            return _live_merge_pr(
                workspace,
                branch,
                base=base,
                head_sha=head_sha,
                run_id=run_id,
                queue_poll_interval_s=0.0,
                queue_poll_timeout_s=0.5,
                _clock=lambda: next(clock_values, 1.0),
                _sleep=lambda _seconds: None,
            )

        with patch("subprocess.run", side_effect=fake_subproc_run):
            result = run_train(
                roadmap,
                ledger,
                run_mode="governed",
                resolve_workspace=lambda n: ws_map[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub(),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_true,
                _live_pr_head_sha_fn=lambda ws, br: "sha-DRAFT-repo-a",
                _merge_phase_enabled=True,
                _merge_pr_fn=_bounded_real_merge,
                _reverify_fn=lambda ws, rp, rm: True,
                _train_review_fn=_approval_review_fn,
                _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            )

        enqueue_argvs = [cmd for cmd in captured_merge_argvs if "--disable-auto" not in cmd]
        delete_branch_present = any("--delete-branch" in cmd for cmd in enqueue_argvs)
        dequeue_attempted = (
            any("dequeuePullRequest" in query for query in captured_graphql)
            and sum("isInMergeQueue" in query for query in captured_graphql) >= 2
            and any("--disable-auto" in cmd for cmd in captured_merge_argvs)
            and queue_status_reads[0] >= 2
        )
        final_record = read_ledger(ledger).get("repo-a/specs/plan-a.md")
        queue_failure_preserved = (
            result.get("status") == "merge_halted"
            and result.get("reason") == "merge_failed"
            and "merge-queue-timeout-dequeued" in result.get("detail", "")
            and final_record is not None
            and final_record.status == "blocked"
        )

        if not enqueue_argvs or delete_branch_present or not dequeue_attempted or not queue_failure_preserved:
            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_non_fab_merge_queue_null_oid — "
                "non-FAB merge with null OID did not enter queue reconciliation, preserve its typed failure, or omitted --delete-branch"
            )

    def test_residual_hotfix_shell_operator(self, tmp_path: Path):
        """EC-RESIDUAL-4: residual_hotfix_shell_operator TDD falsifier.

        Guards public hotfix execution path refusal of shell control operators (; && || | < > \n) before verification launch.
        """
        if not self._is_activated():
            return

        import argparse
        from unittest.mock import patch
        from phase_loop_test_utils import make_repo
        from phase_loop_runtime.cli import _hotfix_command, _hotfix_verification_commands

        # 1. Benign safe positive control driven through public _hotfix_command CLI path with valid repo/roadmap/plan preconditions
        repo_dir = make_repo(tmp_path / "hotfix_repo")
        specs_dir = repo_dir / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        roadmap_file = specs_dir / "phase-plans-v1.md"
        roadmap_file.write_text(
            "# Roadmap\n\n### Phase 0 - Contract (CONTRACT)\n",
            encoding="utf-8",
        )

        plans_dir = repo_dir / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        safe_plan = plans_dir / "CONTRACT.md"
        safe_plan.write_text(
            'verification_command: python -c "print(\'; literal\')"\n'
            "verification_commands:\n"
            '  - python -c "print(\'&& literal\')"\n'
            '  - python -c "print(\'|| literal\')"\n'
            '  - python -c "print(\'| literal\')"\n'
            '  - python -c "print(\'< literal\')"\n'
            '  - python -c "print(\'> literal\')"\n'
            '  - python -c "print(\'\\\\n literal\')"\n',
            encoding="utf-8",
        )
        expected_safe_commands = [
            ["python", "-c", "print('; literal')"],
            ["python", "-c", "print('&& literal')"],
            ["python", "-c", "print('|| literal')"],
            ["python", "-c", "print('| literal')"],
            ["python", "-c", "print('< literal')"],
            ["python", "-c", "print('> literal')"],
            ["python", "-c", "print('\\n literal')"],
        ]
        safe_parser_commands = _hotfix_verification_commands(safe_plan)

        run_verification_calls: list[list[list[str]]] = []

        def spy_run_verification(repo, run_dir, commands, suite_command, *args, **kwargs):
            run_verification_calls.append(commands)

        class _PassingValidation:
            ok = True
            code = "ok"

            @staticmethod
            def to_json():
                return {"ok": True, "code": "ok", "exit_summary": {}}

        args_safe = argparse.Namespace(
            plan=str(safe_plan.relative_to(repo_dir)),
            reason="safe hotfix test",
            init_stub=None,
            roadmap=None,
        )

        with patch("phase_loop_runtime.cli.run_verification", side_effect=spy_run_verification), \
             patch("phase_loop_runtime.cli.validate_verification_artifact", return_value=_PassingValidation()):
            exit_code_safe = _hotfix_command(repo=repo_dir, args=args_safe, as_json=True)

        safe_reached_verification = (
            safe_parser_commands == expected_safe_commands
            and run_verification_calls == [expected_safe_commands]
            and exit_code_safe == 0
        )

        # 2. Refuse every operator in both scalar and list-item inputs. The DSL is
        # line-oriented, so newline chaining is represented by the literal `\n`
        # escape an external plan author would put in a scalar value.
        forbidden_operators = [
            ("semicolon", ";"),
            ("and", "&&"),
            ("or", "||"),
            ("pipe", "|"),
            ("redirect-in", "<"),
            ("redirect-out", ">"),
            ("newline", "\\n"),
        ]
        unsafe_failures: list[str] = []

        for operator_name, operator in forbidden_operators:
            for shape in ("scalar", "list"):
                unsafe_plan = plans_dir / f"CONTRACT_unsafe_{operator_name}_{shape}.md"
                unsafe_line = f"pytest {operator} echo sentinel_reached"
                unsafe_plan.write_text(
                    f"verification_command: {unsafe_line}\n"
                    if shape == "scalar"
                    else f"verification_commands:\n  - {unsafe_line}\n",
                    encoding="utf-8",
                )

                parser_rejected = False
                try:
                    _hotfix_verification_commands(unsafe_plan)
                except ValueError as exc:
                    parser_rejected = "control operator" in str(exc).lower()

                args_unsafe = argparse.Namespace(
                    plan=str(unsafe_plan.relative_to(repo_dir)),
                    reason=f"unsafe hotfix test {operator_name} {shape}",
                    init_stub=None,
                    roadmap=None,
                )

                calls_unsafe: list[list[list[str]]] = []

                def spy_run_verification_unsafe(repo, run_dir, commands, suite_command, *args, **kwargs):
                    calls_unsafe.append(commands)

                artifacts_before = set(
                    (repo_dir / ".phase-loop" / "runs").glob("*/verification.json")
                )
                leaked_exception = False
                try:
                    with patch("phase_loop_runtime.cli.run_verification", side_effect=spy_run_verification_unsafe), \
                         patch("phase_loop_runtime.cli.validate_verification_artifact", return_value=_PassingValidation()):
                        exit_code = _hotfix_command(repo=repo_dir, args=args_unsafe, as_json=True)
                except ValueError:
                    leaked_exception = True
                    exit_code = 1

                verification_artifacts = set(
                    (repo_dir / ".phase-loop" / "runs").glob("*/verification.json")
                ) - artifacts_before
                if (
                    not parser_rejected
                    or leaked_exception
                    or calls_unsafe
                    or exit_code == 0
                    or verification_artifacts
                ):
                    unsafe_failures.append(f"{operator_name}/{shape}")

        if not safe_reached_verification or unsafe_failures:
            defect_details = []
            if not safe_reached_verification:
                defect_details.append("safe positive control failed to reach run_verification")
            if unsafe_failures:
                defect_details.append(
                    "_hotfix_command failed exact parser/public-path refusal for " + ", ".join(unsafe_failures)
                )

            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_hotfix_shell_operator — "
                f"hotfix execution path defects present: {'; '.join(defect_details)}"
            )

    def test_residual_channel_session_model(self, tmp_path: Path, monkeypatch):
        """EC-RESIDUAL-5: residual_channel_session_model TDD falsifier.

        Guards launcher-to-sidecar explicit intended model provenance and preflight session model validation.
        """
        if not self._is_activated():
            return

        monkeypatch.setenv("PHASE_LOOP_RUNNER_REPO_ROOT", str(Path(__file__).resolve().parents[2]))

        import inspect
        import json
        from dataclasses import fields
        from io import BytesIO
        from urllib import response

        from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan
        from phase_loop_runtime.claude_channel_sidecar import (
            ChannelSidecarClient,
            ChannelSidecarClientError,
            SessionRegistryRecord,
        )
        from phase_loop_runtime.events import read_events
        from phase_loop_runtime.launcher import (
            ModelSelection,
            _render_command_template,
            build_launch_request,
            build_launch_spec,
        )
        from phase_loop_runtime.models import CommandAdapterConfig
        from phase_loop_runtime.observability import read_work_unit_metrics
        from phase_loop_runtime.prompts import build_prompt
        from phase_loop_runtime.render import render_status
        from phase_loop_runtime.runner import run_loop, status_snapshot

        defects: list[str] = []
        model = "claude-3-5-sonnet"

        def validate_surface(name, value, actual, state, caveat):
            if value is None:
                return [f"{name} missing"]
            if isinstance(value, str):
                lowered = value.lower()
                errors = []
                for label in ("intended", "binding"):
                    if label not in lowered:
                        errors.append(f"{name} text lacks {label} model provenance")
                if model not in value:
                    errors.append(f"{name} text lacks intended model")
                if actual is not None and "actual" not in lowered:
                    errors.append(f"{name} text lacks actual model provenance")
                if state not in lowered:
                    errors.append(f"{name} text lacks {state} binding state")
                if caveat and caveat not in value:
                    errors.append(f"{name} text lacks caveat {caveat!r}")
                return errors

            def pick(*names):
                for field_name in names:
                    if isinstance(value, dict) and field_name in value:
                        return value[field_name]
                    if hasattr(value, field_name):
                        return getattr(value, field_name)
                return None

            errors = []
            if pick("intended_model", "expected_model", "selected_model") != model:
                errors.append(f"{name} missing exact intended model")
            if actual is not None and pick("actual_model", "verified_model") != actual:
                errors.append(f"{name} missing distinct exact actual model")
            if pick("binding_state", "model_binding_state") != state:
                errors.append(f"{name} missing {state!r} binding state")
            observed_caveat = pick("caveat", "model_caveat", "caveats")
            if caveat and observed_caveat != caveat:
                errors.append(f"{name} missing caveat {caveat!r}")
            if not caveat and observed_caveat not in (None, "", [], ()):
                errors.append(f"{name} has unexpected bound caveat")
            return errors

        repo_dir = make_repo(tmp_path / "channel_repo")
        roadmap_file = repo_dir / "specs" / "phase-plans-v1.md"
        roadmap_file.parent.mkdir(parents=True, exist_ok=True)
        roadmap_file.write_text(
            "---\ntitle: Channel Test Roadmap\nphases:\n  - id: CONTRACT\n    name: Contract\n---\n",
            encoding="utf-8",
        )
        plan_file = repo_dir / "plans" / "CONTRACT.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("verification_command: pytest\n", encoding="utf-8")
        prompt_bundle = build_prompt("execute", roadmap_file, phase="CONTRACT")
        model_sel = ModelSelection(profile="execute", model=model, effort="high")

        def launch_request(template: str, name: str):
            return build_launch_request(
                executor="command",
                action="execute",
                repo=repo_dir,
                roadmap=roadmap_file,
                phase="CONTRACT",
                plan=plan_file,
                model_selection=model_sel,
                prompt_bundle=prompt_bundle,
                json_output=True,
                bypass_approvals=False,
                command_adapter=CommandAdapterConfig(name=name, template=template),
            )

        bound_template = "python3 -c \"print('ok')\" --model {model} --context-file {context_file}"
        bound_spec = build_launch_spec(launch_request(bound_template, "bound"))
        defects.extend(validate_surface("launch_spec_bound", bound_spec, model, "bound", None))

        unbound_template = "python3 -c \"print('ok')\" --context-file {context_file}"
        unbound_request = launch_request(unbound_template, "unbound")
        rendered_unbound = _render_command_template(unbound_template, unbound_request)
        if model in rendered_unbound:
            defects.append("command adapter without {model} injected the intended model")
        unbound_spec = build_launch_spec(unbound_request)
        defects.extend(validate_surface("launch_spec_unbound", unbound_spec, None, "unbound", "session_model_unbound"))

        record_fields = {field.name for field in fields(SessionRegistryRecord)}
        if not {"actual_model", "binding_state"}.issubset(record_fields):
            defects.append("SessionRegistryRecord lacks actual_model/binding_state")

        responses = {
            "match": {"session_id": "sess-1", "state": "ready", "channel_health": "ready", "actual_model": model},
            "mismatch": {"session_id": "sess-1", "state": "ready", "channel_health": "ready", "actual_model": "claude-3-5-haiku"},
            "absent": {"session_id": "sess-1", "state": "ready", "channel_health": "ready"},
        }

        def opener_for(scenario, request_log):
            def opener(req, timeout=None):
                method = req.get_method()
                url = req.full_url
                request_log.append((method, url))
                if "/message" in url:
                    body = {"event_id": "evt-123"}
                elif "/events" in url:
                    body = {"events": [{"event_id": "evt-123", "acknowledged": True, "replies": [{"status": "done", "final": True, "text": "OK"}]}]}
                else:
                    body = responses[scenario]
                return response.addinfourl(BytesIO(json.dumps(body).encode()), headers={}, url=url, code=200)
            return opener

        preflight_has_model = "expected_model" in inspect.signature(ChannelSidecarClient.preflight).parameters
        send_has_model = "expected_model" in inspect.signature(ChannelSidecarClient.send_and_wait).parameters
        if not preflight_has_model:
            defects.append("ChannelSidecarClient.preflight lacks expected_model")
        if not send_has_model:
            defects.append("ChannelSidecarClient.send_and_wait lacks expected_model")

        for scenario, reason in (("mismatch", "session_model_mismatch"), ("absent", "session_model_unbound")):
            request_log = []
            client = ChannelSidecarClient(
                base_url="http://127.0.0.1:8080",
                session_id="sess-1",
                sender="test",
                opener=opener_for(scenario, request_log),
            )
            if preflight_has_model:
                try:
                    client.preflight(expected_model=model)
                except ChannelSidecarClientError as exc:
                    if getattr(exc, "reason", None) != reason:
                        defects.append(f"{scenario} preflight returned wrong reason")
                else:
                    defects.append(f"{scenario} preflight admitted invalid model")
            if send_has_model:
                try:
                    client.send_and_wait("test", expected_model=model)
                except ChannelSidecarClientError as exc:
                    if getattr(exc, "reason", None) != reason:
                        defects.append(f"{scenario} send returned wrong reason")
                else:
                    defects.append(f"{scenario} send admitted invalid model")
            if any(method == "POST" and "/message" in url for method, url in request_log):
                defects.append(f"{scenario} session posted a message")

        match_log = []
        match_client = ChannelSidecarClient(
            base_url="http://127.0.0.1:8080",
            session_id="sess-1",
            sender="test",
            opener=opener_for("match", match_log),
        )
        if preflight_has_model:
            try:
                match_record = match_client.preflight(expected_model=model)
                defects.extend(validate_surface("session_preflight_bound", match_record, model, "bound", None))
            except ChannelSidecarClientError as exc:
                defects.append(f"matching preflight failed: {exc}")
        if send_has_model:
            try:
                reply = match_client.send_and_wait("test", expected_model=model)
                if not reply or not any(method == "POST" and "/message" in url for method, url in match_log):
                    defects.append("matching session did not deliver")
            except (ChannelSidecarClientError, TypeError) as exc:
                defects.append(f"matching send failed: {exc}")

        # Drive each route through the real runner and command-adapter launcher.
        # The resulting launch event is the sole provenance source consumed by
        # the persisted metric, status snapshot, aggregate, and TUI handoff.
        for state, actual, caveat, template in (
            ("bound", model, None, bound_template),
            ("unbound", None, "session_model_unbound", unbound_template),
        ):
            try:
                runner_repo = make_repo(tmp_path / f"runner-{state}")
                runner_roadmap = runner_repo / "specs" / "phase-plans-v1.md"
                runner_plan = write_phase_plan(runner_repo, "CONTRACT", runner_roadmap)
                commit_fixture_paths(runner_repo, f"add {state} plan", runner_plan)
                runner_snapshot, runner_results = run_loop(
                    runner_repo,
                    runner_roadmap,
                    phase="CONTRACT",
                    executor="command",
                    command_adapter_name=state,
                    command_template=template,
                    model=model,
                    effort="high",
                    closeout_mode="manual",
                )
                if len(runner_results) != 1 or runner_results[0].returncode != 0:
                    defects.append(f"real runner command-adapter {state} launch failed")
                    continue
                rendered_command = runner_results[0].command
                if any("{model}" in argument for argument in rendered_command):
                    defects.append(f"real runner {state} command left the model placeholder unresolved")
                if state == "bound" and model not in rendered_command:
                    defects.append("real runner bound command omitted the selected model argv")
                if state == "unbound" and model in rendered_command:
                    defects.append("real runner unbound command injected the selected model argv")

                launch_result_event = runner_results[0].event_metadata()
                defects.extend(validate_surface(f"launch_result_{state}", launch_result_event, actual, state, caveat))
                events = read_events(runner_repo)
                launch_event = (events[-1].get("metadata") or {}).get("launch") if events else None
                defects.extend(validate_surface(f"runner_event_{state}", launch_event, actual, state, caveat))

                metrics = read_work_unit_metrics(runner_repo)
                metric = metrics[-1] if metrics else None
                defects.extend(validate_surface(f"metric_{state}", metric, actual, state, caveat))

                persisted_snapshot = status_snapshot(runner_repo, runner_roadmap)
                status_payload = json.loads(render_status(persisted_snapshot, as_json=True))
                defects.extend(validate_surface(
                    f"status_metric_{state}", status_payload.get("latest_metric"), actual, state, caveat
                ))
                summary = status_payload.get("metrics_summary") or {}
                if state == "bound" and summary.get("by_model", {}).get(model) != 1:
                    defects.append("aggregate did not count the verified bound model")
                if state == "unbound":
                    if summary.get("by_model", {}).get(model):
                        defects.append("aggregate counted an unbound intended model as verified")
                    if caveat not in json.dumps(summary, sort_keys=True):
                        defects.append("aggregate dropped the unbound-model caveat")

                handoff_text = (runner_repo / ".phase-loop" / "tui-handoff.md").read_text(encoding="utf-8")
                defects.extend(validate_surface(f"handoff_{state}", handoff_text, actual, state, caveat))
                if runner_snapshot.repo != str(runner_repo):
                    defects.append(f"real runner {state} snapshot belongs to wrong repository")
            except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
                defects.append(f"real runner {state} provenance flow failed: {exc}")

        if defects:
            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_channel_session_model — "
                f"channel session model validation defects present: {'; '.join(defects)}"
            )

    def test_residual_repair_recursion_or_interrupt(self, tmp_path: Path, monkeypatch):
        """EC-RESIDUAL-6: residual_repair_recursion_or_interrupt TDD falsifier.

        Guards top-level action selection and interruption-only terminal preservation.
        """
        if not self._is_activated():
            return

        monkeypatch.setenv("PHASE_LOOP_RUNNER_REPO_ROOT", str(Path(__file__).resolve().parents[2]))

        import json
        import os
        import subprocess
        from unittest.mock import patch

        from phase_loop_test_utils import make_repo, write_phase_plan
        from phase_loop_runtime.events import append_event, read_events
        from phase_loop_runtime.launcher import LaunchResult
        from phase_loop_runtime.models import LoopEvent, utc_now
        from phase_loop_runtime.provenance import event_provenance, snapshot_provenance
        from phase_loop_runtime.runner import run_loop

        def _field(record, name):
            if isinstance(record, dict):
                return record.get(name)
            return getattr(record, name, None)

        def _lineage_refusal(repo: Path, expected_action: str) -> bool:
            events = read_events(repo)
            if not events:
                return False
            event = events[-1]
            blocker = _field(event, "blocker") or {}
            searchable = json.dumps(blocker, sort_keys=True).lower()
            return (
                _field(event, "action") == expected_action
                and _field(event, "status") == "blocked"
                and ("lineage" in searchable or "nested" in searchable)
            )

        def _setup_repair_repo(repo_dir: Path, pid: int, *, phase_status: str = "blocked"):
            repo = make_repo(repo_dir)
            roadmap = repo / "specs" / "phase-plans-v1.md"
            plan = write_phase_plan(repo, "CONTRACT", roadmap, owned_files=("README.md",))
            subprocess.run(["git", "add", str(plan.relative_to(repo))], cwd=repo, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "commit", "-m", "add repair plan"], cwd=repo, check=True, stdout=subprocess.DEVNULL)

            prov = snapshot_provenance(roadmap)
            roadmap_digest = prov.get("roadmap_sha256") or prov.get("roadmap_digest")

            term_file = repo / ".phase-loop" / "runs" / "x" / "terminal-summary.json"
            term_file.parent.mkdir(parents=True, exist_ok=True)
            term_content = {
                "terminal_status": "awaiting_phase_closeout",
                "verification_status": "passed",
                "dirty_paths": [],
                "produced_if_gates": [],
            }
            term_file.write_text(json.dumps(term_content), encoding="utf-8")

            append_event(
                repo,
                LoopEvent(
                    timestamp=utc_now(),
                    repo=str(repo),
                    roadmap=str(roadmap),
                    phase="CONTRACT",
                    action="plan" if phase_status == "blocked" else "execute",
                    status=phase_status,
                    model="gpt-5.6-terra",
                    reasoning_effort="medium",
                    source="fixture",
                    blocker={
                        "human_required": False,
                        "blocker_summary": "Repair needed.",
                    } if phase_status == "blocked" else None,
                    metadata={
                        "artifacts": {
                            "log": str(repo / ".phase-loop" / "runs" / "x" / "output.log"),
                            "terminal": str(term_file),
                            "metadata": str(repo / ".phase-loop" / "runs" / "x" / "launch.json"),
                        },
                        "terminal_summary": term_content,
                    },
                    **event_provenance(roadmap, "CONTRACT"),
                ),
            )

            dot_phase = repo / ".phase-loop"
            dot_phase.mkdir(exist_ok=True)
            lineage_file = dot_phase / "repair_lineage.json"
            lease_data = {
                "contract": "repair_lineage.v1",
                "repo": str(repo),
                "roadmap_digest": roadmap_digest,
                "phase": "CONTRACT",
                "root_work_unit_id": "wu-root-123",
                "pid": pid,
                "depth": 1,
            }
            lineage_file.write_text(json.dumps(lease_data), encoding="utf-8")
            return repo, roadmap, term_file, lineage_file

        dead_owner = subprocess.Popen(["true"])
        dead_owner.wait(timeout=5)
        stale_pid = dead_owner.pid

        # 1. Live repair lease: run_loop must select "repair" and not launch recursively
        repo_repair, roadmap_repair, _, _ = _setup_repair_repo(tmp_path / "repo-repair-live", os.getpid(), phase_status="blocked")
        repair_launch_called = [False]

        def fake_launch_repair(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
            repair_launch_called[0] = True
            return LaunchResult(command=spec.command, returncode=0)

        with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch_repair):
            run_loop(repo_repair, roadmap_repair, max_phases=1)
        repair_refused_for_lineage = _lineage_refusal(repo_repair, "repair")

        # 2. Live resume lease: run_loop must select "resume" and not launch recursively
        repo_resume, roadmap_resume, _, _ = _setup_repair_repo(tmp_path / "repo-resume-live", os.getpid(), phase_status="executing")
        resume_launch_called = [False]

        def fake_launch_resume(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
            resume_launch_called[0] = True
            return LaunchResult(command=spec.command, returncode=0)

        with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch_resume):
            run_loop(repo_resume, roadmap_resume, max_phases=1)
        resume_refused_for_lineage = _lineage_refusal(repo_resume, "resume")

        # 3. A reaped process is a guaranteed stale owner: run_loop must repair.
        repo_stale, roadmap_stale, _, _ = _setup_repair_repo(tmp_path / "repo-repair-stale", stale_pid, phase_status="blocked")
        stale_launch_called = [False]

        def fake_launch_stale(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
            stale_launch_called[0] = True
            return LaunchResult(command=spec.command, returncode=0)

        with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch_stale):
            run_loop(repo_stale, roadmap_stale, max_phases=1)

        stale_events = read_events(repo_stale)
        stale_event_last = stale_events[-1] if stale_events else None
        stale_action_selected = (
            stale_event_last.get("action")
            if isinstance(stale_event_last, dict)
            else getattr(stale_event_last, "action", None)
        )

        # 4. Child-write negative control: child writes to README.md and fails
        repo_child, roadmap_child, term_file_child, _ = _setup_repair_repo(tmp_path / "repo-child-writes", stale_pid, phase_status="blocked")
        term_bytes_child_before = term_file_child.read_bytes()

        def fake_launch_child(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
            (repo_child / "README.md").write_text("child modified content", encoding="utf-8")
            return LaunchResult(command=spec.command, returncode=1, interrupted=True)

        with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch_child):
            run_loop(repo_child, roadmap_child, max_phases=1)

        term_bytes_child_after = term_file_child.read_bytes() if term_file_child.exists() else None
        child_preserved_trusted_terminal = (term_bytes_child_before == term_bytes_child_after)

        # 5. No-diff interrupted repair must preserve the trusted terminal bytes.
        repo_no_diff, roadmap_no_diff, term_file_no_diff, _ = _setup_repair_repo(
            tmp_path / "repo-child-no-diff", stale_pid, phase_status="blocked"
        )
        term_bytes_no_diff_before = term_file_no_diff.read_bytes()

        def fake_launch_no_diff(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
            return LaunchResult(command=spec.command, returncode=1, interrupted=True)

        with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch_no_diff):
            run_loop(repo_no_diff, roadmap_no_diff, max_phases=1)

        term_bytes_no_diff_after = term_file_no_diff.read_bytes() if term_file_no_diff.exists() else None
        no_diff_preserved_trusted_terminal = term_bytes_no_diff_before == term_bytes_no_diff_after

        if (
            repair_launch_called[0]
            or resume_launch_called[0]
            or not repair_refused_for_lineage
            or not resume_refused_for_lineage
            or child_preserved_trusted_terminal
            or not no_diff_preserved_trusted_terminal
            or not stale_launch_called[0]
            or stale_action_selected != "repair"
        ):
            defect_details = []
            if repair_launch_called[0]:
                defect_details.append("live repair lease launched nested repair")
            if resume_launch_called[0]:
                defect_details.append("live resume lease launched nested resume")
            if not repair_refused_for_lineage:
                defect_details.append("live repair lease did not terminalize with a lineage-specific blocker")
            if not resume_refused_for_lineage:
                defect_details.append("live resume lease did not terminalize with a lineage-specific blocker")
            if child_preserved_trusted_terminal:
                defect_details.append("old trusted terminal preserved when child wrote to repo")
            if not no_diff_preserved_trusted_terminal:
                defect_details.append("trusted terminal changed after an interrupted no-diff repair")
            if not stale_launch_called[0]:
                defect_details.append("stale lease failed to launch")
            if stale_action_selected != "repair":
                defect_details.append(f"stale lease selected action {stale_action_selected!r} instead of 'repair'")

            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_repair_recursion_or_interrupt — "
                f"repair recursion and lineage safety defects present: {'; '.join(defect_details)}"
            )

    def test_residual_f841_triage(self, tmp_path: Path):
        """EC-RESIDUAL-7: residual_f841_triage TDD falsifier.

        Guards exact config-driven CI-equivalent ruff check . and F841 triage state.
        """
        if not self._is_activated():
            return

        import json
        import shutil
        import subprocess

        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        repo_root = Path(__file__).resolve().parents[2]

        # 1. Verify every config suppression form structurally; comments mentioning
        # F841 must not be mistaken for a live ignore entry.
        ruff_toml_text = (repo_root / "ruff.toml").read_text(encoding="utf-8")
        lint_config = tomllib.loads(ruff_toml_text).get("lint", {})

        def _covers_f841(selector) -> bool:
            normalized = str(selector).strip().upper()
            return normalized == "ALL" or bool(normalized) and "F841".startswith(normalized)

        ignore_values = [
            *lint_config.get("ignore", []),
            *lint_config.get("extend-ignore", []),
        ]
        per_file_values = [
            selector
            for key in ("per-file-ignores", "extend-per-file-ignores")
            for selectors in lint_config.get(key, {}).values()
            for selector in ([selectors] if isinstance(selectors, str) else selectors)
        ]
        f841_suppressed_in_config = any(
            _covers_f841(selector) for selector in [*ignore_values, *per_file_values]
        )

        # 2. Config-driven CI check: the current baseline returns no F841 because
        # ruff.toml suppresses it; GREEN requires that suppression to be removed.
        res_config = subprocess.run(
            ["ruff", "check", ".", "--output-format", "json", "--no-cache"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        config_json_valid = True
        try:
            config_diags = json.loads(res_config.stdout or "[]")
        except json.JSONDecodeError:
            config_diags = []
            config_json_valid = False

        config_f841_count = sum(1 for d in config_diags if d.get("code") == "F841")

        # 3. Exact frozen 45/31 execution-base inventory when --select F841 is explicitly passed
        FROZEN_F841_TUPLES = [
            ("phase-loop-runtime/scripts/_gate_a_probe.py", 107, 13),
            ("phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py", 495, 9),
            ("phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py", 836, 5),
            ("phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py", 6080, 5),
            ("phase-loop-runtime/src/phase_loop_runtime/runner.py", 2588, 17),
            ("phase-loop-runtime/src/phase_loop_runtime/runner.py", 5626, 13),
            ("phase-loop-runtime/src/phase_loop_runtime/skills_bundle/claude-plan-phase/scripts/validate_plan_doc.py", 1004, 5),
            ("phase-loop-runtime/src/phase_loop_runtime/skills_bundle/codex-plan-phase/scripts/validate_plan_doc.py", 1004, 5),
            ("phase-loop-runtime/src/phase_loop_runtime/skills_bundle/gemini-plan-phase/scripts/validate_plan_doc.py", 1004, 5),
            ("phase-loop-runtime/src/phase_loop_runtime/skills_bundle/opencode-plan-phase/scripts/validate_plan_doc.py", 1004, 5),
            ("phase-loop-runtime/src/phase_loop_runtime/train_runner.py", 593, 9),
            ("phase-loop-runtime/tests/proofgate_bootstrap_verifier.py", 2393, 9),
            ("phase-loop-runtime/tests/test_convergence_broker_admission.py", 196, 5),
            ("phase-loop-runtime/tests/test_convergence_broker_verbs.py", 189, 5),
            ("phase-loop-runtime/tests/test_fab_activation_promotion.py", 498, 9),
            ("phase-loop-runtime/tests/test_fab_activation_promotion.py", 531, 9),
            ("phase-loop-runtime/tests/test_fab_activation_promotion.py", 1618, 9),
            ("phase-loop-runtime/tests/test_fab_closeout_crash_safety.py", 490, 5),
            ("phase-loop-runtime/tests/test_fab_delta_consumer.py", 2099, 9),
            ("phase-loop-runtime/tests/test_fabpub_shared_epoch.py", 1970, 9),
            ("phase-loop-runtime/tests/test_fabpub_shared_epoch.py", 2173, 9),
            ("phase-loop-runtime/tests/test_fabpub_shared_epoch.py", 2372, 5),
            ("phase-loop-runtime/tests/test_fabpub_shared_epoch.py", 2545, 5),
            ("phase-loop-runtime/tests/test_fabpub_shared_epoch.py", 4295, 5),
            ("phase-loop-runtime/tests/test_fabreadmit_broker.py", 140, 5),
            ("phase-loop-runtime/tests/test_injection_skill_failloud.py", 135, 13),
            ("phase-loop-runtime/tests/test_legible_evidence.py", 1448, 20),
            ("phase-loop-runtime/tests/test_phase_loop_launcher.py", 218, 13),
            ("phase-loop-runtime/tests/test_phase_loop_runner.py", 879, 13),
            ("phase-loop-runtime/tests/test_phase_loop_runner.py", 2911, 13),
            ("phase-loop-runtime/tests/test_phase_worktree_executor.py", 344, 5),
            ("phase-loop-runtime/tests/test_release_dispatch_operator_approval_145.py", 204, 9),
            ("phase-loop-runtime/tests/test_roadmap_ownership.py", 1878, 13),
            ("phase-loop-runtime/tests/test_roadmap_ownership.py", 2034, 13),
            ("phase-loop-runtime/tests/test_roadmap_ownership.py", 2057, 60),
            ("phase-loop-runtime/tests/test_roadmap_ownership.py", 2192, 13),
            ("phase-loop-runtime/tests/test_train_merge.py", 1506, 9),
            ("phase-loop-runtime/tests/test_train_order_only_deps_47.py", 94, 5),
            ("phase-loop-runtime/tests/test_train_roadmap.py", 706, 9),
            ("phase-loop-runtime/tests/test_train_runner.py", 830, 9),
            ("phase-loop-runtime/tests/test_train_runner.py", 2954, 5),
            ("phase-loop-runtime/tests/test_train_runner.py", 2955, 5),
            ("phase-loop-runtime/tests/test_train_runner.py", 2956, 5),
            ("phase-loop-skills/plan-phase/scripts/validate_plan_doc.py", 1004, 5),
            ("skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py", 1004, 5),
        ]

        res_explicit = subprocess.run(
            ["ruff", "check", ".", "--select", "F841", "--output-format", "json", "--no-cache"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        explicit_json_valid = True
        try:
            explicit_diags = json.loads(res_explicit.stdout or "[]")
        except json.JSONDecodeError:
            explicit_diags = []
            explicit_json_valid = False
        observed_f841_tuples = [
            (
                Path(diag["filename"]).resolve().relative_to(repo_root.resolve()).as_posix(),
                diag["location"]["row"],
                diag["location"]["column"],
            )
            for diag in explicit_diags
            if diag.get("code") == "F841"
        ]
        inventory_matches_baseline_or_closed = observed_f841_tuples in (FROZEN_F841_TUPLES, [])
        frozen_files = sorted({path for path, _, _ in FROZEN_F841_TUPLES})

        # An empty inventory is valid only when every formerly affected file is
        # still in the configured lint scope and an isolated, ignore-free run also
        # sees no F841. This rejects exclusions, per-file suppression, and noqa-based
        # cleanup that would otherwise masquerade as triage.
        res_show_files = subprocess.run(
            ["ruff", "check", ".", "--show-files", "--no-cache"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        linted_files = {
            Path(line).resolve().relative_to(repo_root.resolve()).as_posix()
            for line in res_show_files.stdout.splitlines()
            if line.strip() and Path(line).resolve().is_relative_to(repo_root.resolve())
        }
        frozen_files_in_scope = set(frozen_files) <= linted_files

        res_unsuppressed = subprocess.run(
            [
                "ruff",
                "check",
                *frozen_files,
                "--isolated",
                "--select",
                "F841",
                "--ignore-noqa",
                "--output-format",
                "json",
                "--no-cache",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        unsuppressed_json_valid = True
        try:
            unsuppressed_diags = json.loads(res_unsuppressed.stdout or "[]")
        except json.JSONDecodeError:
            unsuppressed_diags = []
            unsuppressed_json_valid = False
        unsuppressed_f841_tuples = [
            (
                Path(diag["filename"]).resolve().relative_to(repo_root.resolve()).as_posix(),
                diag["location"]["row"],
                diag["location"]["column"],
            )
            for diag in unsuppressed_diags
            if diag.get("code") == "F841"
        ]
        no_hidden_f841 = unsuppressed_f841_tuples == observed_f841_tuples

        # 4. Config-driven mutation proof: a standalone local binding avoids
        # attributing an existing source diagnostic to the injected mutation.
        repo_copy = tmp_path / "repo_copy"
        repo_copy.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_root / "ruff.toml", repo_copy / "ruff.toml")

        mutated_src = repo_copy / "mutation_probe.py"
        mutated_src.write_text(
            "def mutation_probe():\n"
            "    unused_local_mutation = 42\n"
            "    return None\n",
            encoding="utf-8",
        )

        res_config_mut = subprocess.run(
            ["ruff", "check", ".", "--output-format", "json", "--no-cache"],
            cwd=str(repo_copy),
            capture_output=True,
            text=True,
        )
        mutation_json_valid = True
        try:
            config_mut_diags = json.loads(res_config_mut.stdout or "[]")
        except json.JSONDecodeError:
            config_mut_diags = []
            mutation_json_valid = False
        mutation_f841 = [
            diag
            for diag in config_mut_diags
            if diag.get("code") == "F841"
            and Path(diag["filename"]).resolve() == mutated_src.resolve()
            and diag.get("location") == {"row": 2, "column": 5}
        ]
        config_driven_mutation_detected = len(mutation_f841) == 1

        # 5. The initial frozen inventory and the fully closed empty inventory
        # are valid states. Any partial/drifted inventory remains a hard failure.
        if (
            f841_suppressed_in_config
            or not config_json_valid
            or res_config.returncode not in (0, 1)
            or not explicit_json_valid
            or res_explicit.returncode not in (0, 1)
            or not mutation_json_valid
            or res_config_mut.returncode != 1
            or config_f841_count != len(observed_f841_tuples)
            or observed_f841_tuples
            or not config_driven_mutation_detected
            or not inventory_matches_baseline_or_closed
            or res_show_files.returncode != 0
            or not frozen_files_in_scope
            or not unsuppressed_json_valid
            or res_unsuppressed.returncode not in (0, 1)
            or not no_hidden_f841
        ):
            defect_details = []
            if f841_suppressed_in_config:
                defect_details.append("F841 is suppressed by ruff.toml")
            if not config_json_valid or res_config.returncode not in (0, 1):
                defect_details.append(f"config-driven Ruff run was invalid (exit {res_config.returncode})")
            if not explicit_json_valid or res_explicit.returncode not in (0, 1):
                defect_details.append(f"explicit F841 Ruff run was invalid (exit {res_explicit.returncode})")
            if not mutation_json_valid or res_config_mut.returncode != 1:
                defect_details.append(f"mutation Ruff run did not fail diagnostically (exit {res_config_mut.returncode})")
            if config_f841_count != len(observed_f841_tuples):
                defect_details.append(
                    "config-driven and explicit F841 inventories disagree"
                )
            if observed_f841_tuples:
                defect_details.append(f"{len(observed_f841_tuples)} F841 diagnostics remain")
            if not config_driven_mutation_detected:
                defect_details.append("config-driven ruff check . missed the exact unused-local mutation")
            if not inventory_matches_baseline_or_closed:
                defect_details.append(
                    f"execution-base F841 inventory is neither the frozen {len(FROZEN_F841_TUPLES)} rows nor empty: "
                    f"observed {len(observed_f841_tuples)} rows"
                )
            if res_show_files.returncode != 0 or not frozen_files_in_scope:
                missing_files = sorted(set(frozen_files) - linted_files)
                defect_details.append(
                    f"formerly affected files are outside configured Ruff scope: {missing_files!r}"
                )
            if not unsuppressed_json_valid or res_unsuppressed.returncode not in (0, 1):
                defect_details.append(
                    f"isolated unsuppressed Ruff run was invalid (exit {res_unsuppressed.returncode})"
                )
            elif not no_hidden_f841:
                defect_details.append(
                    "configured Ruff inventory hides F841 findings visible with exclusions and noqa disabled"
                )

            raise AssertionError(
                "RESIDUAL-RED-ANCHOR::residual_f841_triage — "
                f"F841 diagnostics remain unresolved or suppressed ({len(FROZEN_F841_TUPLES)}-diagnostic baseline across 31 files): {'; '.join(defect_details)}"
            )
