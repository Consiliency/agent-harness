"""Tests for the prebuilt-node publish mode of the release-train coordinator.

A prebuilt node lands an already-committed, independently-verified branch
WITHOUT re-executing the node's phase (no executor dispatch): run_loop is not
called, owned_paths come from the committed diff vs base, and publish pushes the
existing branch + opens a draft PR without a new commit.  The publish mutation
is routed through the credential BROKER — a prebuilt node with a
broker-authoritative ``CoordinatorRuntime`` publishes via the broker; without a
broker_client the publish primitive fails closed (``broker_required``), never a
direct push.

Run with:
    cd phase-loop-runtime && \
        PYTHONPATH=src:tests python -m pytest tests/test_train_prebuilt.py -q

All git/gh/run_loop/publish boundaries are stubbed for the coordinator tests;
the preflight/owned-paths/fail-closed tests use real local git repos.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from phase_loop_runtime.train_ledger import read_ledger
from phase_loop_runtime.train_roadmap import parse_train_roadmap
from phase_loop_runtime.train_runner import (
    CoordinatorRuntime,
    _check_branch_ahead_of_base,
    _prebuilt_owned_paths,
    run_train,
)


# ---------------------------------------------------------------------------
# Fixtures

PREBUILT_1NODE_MD = """\
# Release Train: prebuilt-single

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)
**Mode:** prebuilt
"""

PREBUILT_3NODE_MD = """\
# Release Train: prebuilt-three

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)
**Mode:** prebuilt

### Node: repo-b / specs/plan-b.md

**Depends on:** repo-a / specs/plan-a.md
**Channel:** submodule path=vendor/repo-a
**Mode:** prebuilt

### Node: repo-c / specs/plan-c.md

**Depends on:** repo-b / specs/plan-b.md
**Channel:** submodule path=vendor/repo-b
**Mode:** prebuilt
"""


PREBUILT_ORDER_ONLY_MD = """\
# Release Train: prebuilt-order-only

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)
**Mode:** prebuilt

### Node: repo-b / specs/plan-b.md

**Depends on:** repo-a / specs/plan-a.md
**Channel:** order-only
**Mode:** prebuilt
"""


def _preflight_pass(nodes, resolve_workspace):
    return []


def _pr_is_open_false(workspace: Path, branch: str) -> bool:
    return False


def _make_prebuilt_publish_stub(recorder: Optional[dict] = None):
    """Publish stub that records the prebuilt flag + owned_paths + broker kwargs."""
    def _publish(workspace: Path, owned_paths, *, draft: bool, prebuilt: bool = False, **kw):
        assert draft is True, "prebuilt publishes must still be draft"
        if recorder is not None:
            recorded = {
                "prebuilt": prebuilt,
                "owned_paths": list(owned_paths),
                "broker_client": kw.get("broker_client"),
                "publish_authority": kw.get("publish_authority"),
                "checkpoint_root": kw.get("checkpoint_root"),
            }
            if "admission" in kw:
                recorded["admission"] = kw["admission"]
            recorder[workspace.name] = recorded
        return {
            "status": "published",
            "branch": f"feat/train-{workspace.name}",
            "head_sha": f"sha-COMMITTED-{workspace.name}",
            "pr_url": f"https://gh.com/{workspace.name}/pr/1",
        }
    return _publish


def _make_runtime(broker_client: object) -> CoordinatorRuntime:
    return CoordinatorRuntime(
        train_id="train-prebuilt",
        coordinator_root=Path("/coord"),
        roadmap_path="train.md",
        roadmap_digest="deadbeef",
        workspace_id="ws-1",
        broker_client=broker_client,
    )


# ---------------------------------------------------------------------------
# 1. Prebuilt node skips run_loop and publishes with prebuilt=True


class TestPrebuiltSkipsRunLoop:
    def test_run_loop_not_called_publish_is_prebuilt(self, tmp_path: Path):
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        run_loop_calls: List[str] = []
        published: dict = {}

        def _run_loop_spy(*a, **kw):
            run_loop_calls.append("called")
            return (None, [])

        result = run_train(
            roadmap,
            ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=_run_loop_spy,
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/committed.py", "CHANGELOG.md"],
        )

        assert result["status"] == "completed"
        # ZERO executor dispatch — run_loop must never be called for prebuilt.
        assert run_loop_calls == [], (
            f"prebuilt node must NOT invoke run_loop; got {run_loop_calls}"
        )
        # Publish called with prebuilt=True and the committed-diff owned_paths.
        assert published["repo-a"]["prebuilt"] is True
        assert published["repo-a"]["owned_paths"] == ["src/committed.py", "CHANGELOG.md"]

    def test_ledger_records_committed_head(self, tmp_path: Path):
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        run_train(
            roadmap,
            ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub(),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"],
        )

        state = read_ledger(ledger)
        rec = state["repo-a/specs/plan-a.md"]
        assert rec.status == "pr_open"
        assert rec.branch == "feat/train-repo-a"
        assert rec.head_sha == "sha-COMMITTED-repo-a"  # the committed HEAD
        assert rec.upstream_merge_sha is None

    def test_explicit_owned_paths_override_diff(self, tmp_path: Path):
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        published: dict = {}

        # If an explicit resolver is supplied, the committed-diff seam is bypassed.
        def _diff_should_not_run(ws, base):
            raise AssertionError("prebuilt_owned_paths_fn must not run when resolver given")

        run_train(
            roadmap,
            ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            resolve_owned_paths=lambda n: ["explicit/only.py"],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _prebuilt_owned_paths_fn=_diff_should_not_run,
        )

        assert published["repo-a"]["owned_paths"] == ["explicit/only.py"]


# ---------------------------------------------------------------------------
# 2. Prebuilt publish routes through the broker (the adaptation vs the parked ref)


class TestPrebuiltBrokerRouting:
    def test_prebuilt_publish_passes_the_runtimes_broker_client(self, tmp_path: Path, request):
        """A broker-authoritative runtime → publish_fn receives broker_client+admission."""
        from _fabpub_tdd_guard import fabpub_migrated_activated

        _fabpub = fabpub_migrated_activated(
            request,
            symbol=("phase_loop_runtime.train_runner", "PublishAuthorityPreimages"),
            detail=(
                "the prebuilt route still hands publish a finalized admission built before "
                "the commit identity exists; FABPUB routes prebuilt publication through "
                "PublishAuthorityPreimages plus a train-local checkpoint_root, and freezes "
                "the supplied head as the exact expected/committed OID without rewriting it"
            ),
        )
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        published: dict = {}

        sentinel_broker = object()
        runtime = _make_runtime(sentinel_broker)

        common = dict(
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            coordinator_runtime=runtime,
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"],
        )

        if _fabpub:
            # FABPUB replacement handoff: the prebuilt route supplies PRE-commit
            # authority pre-images plus a train-local checkpoint_root, and NEVER a
            # broker-legal admission built before the commit identity exists.
            authority_sentinel = object()
            result = run_train(
                roadmap,
                ledger,
                _publish_authority_fn=lambda rt, node, ws, owned: authority_sentinel,
                **common,
            )
            assert result["status"] == "completed"
            rec = published["repo-a"]
            assert rec["prebuilt"] is True
            assert rec["broker_client"] is sentinel_broker
            assert rec["publish_authority"] is authority_sentinel
            assert "admission" not in rec, (
                "the retired finalized handoff must not survive into the prebuilt route"
            )
            assert "checkpoint_root" in rec, (
                "prebuilt publication needs its train-local transaction root"
            )
            # The superseded builder must be gone, so a conforming implementation
            # cannot satisfy this node by keeping the legacy seam alive.
            import phase_loop_runtime.train_runner as _tr

            assert not hasattr(_tr, "_default_build_admission")
            return

        admission_sentinel = object()
        result = run_train(
            roadmap,
            ledger,
            _admission_fn=lambda rt, node, ws, owned: admission_sentinel,
            **common,
        )

        assert result["status"] == "completed"
        rec = published["repo-a"]
        assert rec["prebuilt"] is True
        # The publish mutation is routed through the broker: exact runtime client.
        assert rec["broker_client"] is sentinel_broker
        assert rec["admission"] is admission_sentinel

    def test_prebuilt_without_broker_fails_closed_broker_required(self, tmp_path: Path):
        """No broker_client → the REAL publish primitive returns broker_required.

        Uses the live ``publish_from_worktree`` (no _publish stub) against a real
        prebuilt branch with NO coordinator_runtime, so publish gets no
        broker_client → publication_blocked/broker_required → node blocked.  A
        prebuilt node must NEVER fall back to a direct push.
        """
        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        (repo / "feature.py").write_text("# work\n")
        _git(repo, "add", "feature.py")
        _git(repo, "commit", "-q", "-m", "prebuilt work")

        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        with (
            patch("phase_loop_runtime.train_runner._check_gh_auth", return_value=None),
            patch("phase_loop_runtime.train_runner._check_remote_reachable", return_value=None),
        ):
            result = run_train(
                roadmap,
                ledger,
                run_mode="autonomous",
                resolve_workspace=lambda n: repo,
                _pr_is_open=_pr_is_open_false,
                _live_pr_head_sha_fn=lambda ws, br: None,
                # real _default_preflight (clean+ahead+base) + real publish_from_worktree
            )

        assert result["status"] == "blocked", result
        detail = result["detail"]
        assert detail.get("status") == "publication_blocked"
        assert detail.get("reason") == "broker_required"
        # Nothing was pushed/merged; ledger records the block, not a pr_open.
        state = read_ledger(ledger)
        assert state["repo-a/specs/plan-a.md"].status == "blocked"


# ---------------------------------------------------------------------------
# 3. Full 3-node prebuilt train reaches drafts_open with zero executor dispatch


class TestPrebuiltFullTrain:
    def test_three_node_prebuilt_reaches_drafts_open(self, tmp_path: Path):
        roadmap = parse_train_roadmap(PREBUILT_3NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        run_loop_calls: List[str] = []
        published: dict = {}

        result = run_train(
            roadmap,
            ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: run_loop_calls.append("called"),
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,  # P4 gate on; autonomous → drafts_open
            _prebuilt_owned_paths_fn=lambda ws, base: [f"src/{ws.name}.py"],
        )

        assert result["status"] == "drafts_open", result
        assert len(result["nodes"]) == 3
        assert run_loop_calls == [], "zero executor dispatch expected for prebuilt train"
        assert all(v["prebuilt"] for v in published.values())
        state = read_ledger(ledger)
        assert len([r for r in state.values() if r.status == "pr_open"]) == 3


# ---------------------------------------------------------------------------
# 4. Prebuilt + --governed is rejected up front (P4 out of scope) — INV-3 shape


class TestPrebuiltGovernedRejected:
    """agent-harness#906: the --governed refusal keys on the SAME predicate the P4 merge
    loop uses -- `edges_for_downstream(node)` non-empty -- because `reverify_fn` runs for
    every node inside `if _upstream_edges_m:`, order-only edges included. A prebuilt node
    with ANY upstream edge is refused at preflight with zero PRs; one with none lands."""

    def _governed_kwargs(self, ws_map, published, **extra):
        kw = dict(
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"],
        )
        kw.update(extra)
        return kw

    def test_governed_prebuilt_with_channel_upstream_refused_zero_prs(self, tmp_path: Path):
        roadmap = parse_train_roadmap(PREBUILT_3NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        published: dict = {}
        result = run_train(roadmap, ledger, **self._governed_kwargs(ws_map, published))
        assert result["status"] == "preflight_failed"
        assert any("upstream" in e and "repo-b/specs/plan-b.md" in e for e in result["errors"])
        assert "manually" not in " ".join(result["errors"]), (
            "the refusal must not instruct a manual merge the run-train skill forbids"
        )
        assert published == {}, "zero PRs must open when an upstream-bearing prebuilt is refused"

    def test_governed_prebuilt_with_order_only_upstream_refused_zero_prs(self, tmp_path: Path):
        """Order-only edges carry no channel but DO reach reverify_fn (board PR #907 r1)."""
        roadmap = parse_train_roadmap(PREBUILT_ORDER_ONLY_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        published: dict = {}
        result = run_train(roadmap, ledger, **self._governed_kwargs(ws_map, published))
        assert result["status"] == "preflight_failed", result
        assert any("repo-b/specs/plan-b.md" in e and "repo-a/specs/plan-a.md" in e for e in result["errors"])
        assert published == {}

    def test_governed_single_node_prebuilt_lands_pinned_to_admitted_head(self, tmp_path: Path):
        """A prebuilt node with NO upstream edge never reaches reverify_fn; it publishes,
        passes train review, and merges pinned (--match-head-commit) to its ADMITTED head."""
        from test_train_merge import _approval_review_fn

        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        published: dict = {}
        merge_heads: dict = {}

        def _merge_pr(workspace, branch, base="main", head_sha=None):
            merge_heads[workspace.name] = head_sha
            return f"sha-merged-{workspace.name}"

        def _reverify_must_not_run(*a, **kw):
            raise AssertionError("reverify_fn must never run for a zero-edge prebuilt node")

        result = run_train(
            roadmap, ledger,
            **self._governed_kwargs(
                ws_map, published,
                _merge_pr_fn=_merge_pr,
                _reverify_fn=_reverify_must_not_run,
                _train_review_fn=_approval_review_fn,
                _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            ),
        )
        assert result["status"] == "merged", result
        assert published["repo-a"]["prebuilt"] is True
        assert merge_heads == {"repo-a": "sha-COMMITTED-repo-a"}, (
            "the merge must be pinned to the broker-admitted head the publish returned"
        )


# ---------------------------------------------------------------------------
# 4b. agent-harness#906: refreshing an admitted prebuilt PR on local advance

from phase_loop_runtime.train_ledger import LedgerRecord, append_record  # noqa: E402


def _pr_is_open_true(workspace: Path, branch: str) -> bool:
    return True


ADMITTED = "sha-admitted-a"


class TestPrebuiltRefresh:
    """The Step 4 skip block reads the workspace HEAD for a prebuilt pr_open node. Only a
    fast-forward advance of the admitted head falls through into the prebuilt publish
    arm; remote drift and divergence are refused before any admission."""

    def _ledger_with_open_pr(self, tmp_path: Path) -> Path:
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open",
            branch="feat/train-repo-a", head_sha=ADMITTED,
            pr_url="https://gh.com/repo-a/pr/1", merge_order=0,
        ))
        return ledger

    def _run(self, tmp_path, ledger, published, *, head, ancestor=True, live=ADMITTED,
             live_fn=None, publish=None, head_fn=None):
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        return run_train(
            roadmap, ledger,
            run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=publish or _make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=live_fn or (lambda ws, br: live),
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"],
            _workspace_head_fn=head_fn or (lambda ws: head),
            _is_ancestor_fn=lambda ws, a, b: ancestor,
            _merge_phase_enabled=True,  # autonomous + merge phase => stops at drafts_open
        )

    def test_unchanged_resume_skips_without_publishing(self, tmp_path: Path):
        ledger = self._ledger_with_open_pr(tmp_path)
        before = ledger.read_bytes()
        published: dict = {}
        result = self._run(tmp_path, ledger, published, head=ADMITTED)
        assert result["status"] == "drafts_open"
        assert published == {}
        assert ledger.read_bytes() == before

    def test_fast_forward_advance_refreshes_through_the_prebuilt_arm(self, tmp_path: Path):
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        result = self._run(tmp_path, ledger, published, head="sha-new-a", ancestor=True)
        assert result["status"] == "drafts_open", result
        assert published["repo-a"]["prebuilt"] is True, "the refresh IS the prebuilt arm"
        assert published["repo-a"]["owned_paths"] == ["src/x.py"], "owned paths re-derived"
        lines = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
        pr_open_lines = [ln for ln in lines if '"pr_open"' in ln]
        assert len(pr_open_lines) == 2, "append-only: the prior pr_open line is preserved"
        assert ADMITTED in pr_open_lines[0]
        assert "sha-COMMITTED-repo-a" in pr_open_lines[1], "the NEW admitted head is last"
        assert read_ledger(ledger)["repo-a/specs/plan-a.md"].head_sha == "sha-COMMITTED-repo-a"
        assert result["nodes"]["repo-a/specs/plan-a.md"]["head_sha"] == "sha-COMMITTED-repo-a"

    def test_remote_drift_is_refused_before_any_admission(self, tmp_path: Path):
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        result = self._run(tmp_path, ledger, published, head="sha-new-a", live="sha-oob-a")
        assert result["status"] == "blocked"
        assert result["detail"]["reason"] == "remote_drift"
        assert published == {}, "no publish_fn call: refused before admission"
        assert read_ledger(ledger)["repo-a/specs/plan-a.md"].status == "blocked"

    def test_unobserved_live_head_is_refused_before_any_admission(self, tmp_path: Path):
        """A live read that returns nothing is not 'no drift' (PR #909 r1, claude)."""
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        result = self._run(tmp_path, ledger, published, head="sha-new-a", live=None)
        assert result["status"] == "blocked"
        assert result["detail"]["reason"] == "live_pr_head_unavailable"
        assert published == {}

    def test_refusal_is_durable_across_retries_until_the_pr_is_superseded(self, tmp_path: Path):
        """PR #909 r1, codex (blocking): after a remote_drift refusal the blocked row must not
        hide the prior admission -- a plain retry re-enters the decision and is refused
        again; only closing the PR (supersede) lets the node publish fresh as a NEW PR."""
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        first = self._run(tmp_path, ledger, published, head="sha-new-a", live="sha-oob-a")
        assert first["status"] == "blocked" and first["detail"]["reason"] == "remote_drift"
        second = self._run(tmp_path, ledger, published, head="sha-new-a", live="sha-oob-a")
        assert second["status"] == "blocked" and second["detail"]["reason"] == "remote_drift", (
            "a retry must NOT bypass the refusal by publishing fresh"
        )
        assert published == {}, "no publish across both refused runs"
        state = read_ledger(ledger)["repo-a/specs/plan-a.md"]
        assert state.status == "blocked" and state.head_sha == ADMITTED and state.pr_url
        # supersede: the operator closes the stale PR; resume drops the node and republishes
        # as a NEW PR (distinct URL), never a create against the closed one
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}

        def _publish_new_pr(workspace, owned_paths, **kw):
            out = _make_prebuilt_publish_stub(published)(workspace, owned_paths, **kw)
            out["pr_url"] = f"https://gh.com/{workspace.name}/pr/2"
            return out

        third = run_train(
            roadmap, ledger, run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_publish_new_pr,
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass, _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"],
            _merge_phase_enabled=True,
        )
        assert third["status"] == "drafts_open"
        assert published["repo-a"]["prebuilt"] is True
        latest = read_ledger(ledger)["repo-a/specs/plan-a.md"]
        assert latest.head_sha == "sha-COMMITTED-repo-a"
        assert latest.pr_url == "https://gh.com/repo-a/pr/2", "a distinct PR, the old URL kept in history"
        assert any("https://gh.com/repo-a/pr/1" in ln for ln in ledger.read_text().splitlines())

    def test_transient_live_read_failure_between_retries_keeps_the_refusal(self, tmp_path: Path):
        """PR #909 r2, codex: refusal -> read exception -> retry must still refuse."""
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        first = self._run(tmp_path, ledger, published, head="sha-new-a", live="sha-oob-a")
        assert first["detail"]["reason"] == "remote_drift"

        def _raises(ws, br):
            raise RuntimeError("gh transient")

        second = self._run(tmp_path, ledger, published, head="sha-new-a", live_fn=_raises)
        assert second["status"] == "blocked" and second["detail"]["reason"] == "live_pr_head_read_failed"
        third = self._run(tmp_path, ledger, published, head="sha-new-a", live="sha-oob-a")
        assert third["status"] == "blocked" and third["detail"]["reason"] == "remote_drift", (
            "the read-failure row must keep the admission so the retry re-enters the decision"
        )
        assert published == {}

    def test_drift_observed_at_resume_then_restored_is_still_refused(self, tmp_path: Path):
        """PR #909 r1, codex/grok: the Step 3 observation is remembered even when the
        decision's re-read flaps back to the admitted head."""
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        reads = iter(["sha-oob-a", ADMITTED, ADMITTED])

        def _flapping(ws, br):
            return next(reads)

        result = self._run(tmp_path, ledger, published, head="sha-new-a", live_fn=_flapping)
        assert result["status"] == "blocked" and result["detail"]["reason"] == "remote_drift"
        assert published == {}

    def test_diverged_candidate_is_refused_before_any_admission(self, tmp_path: Path):
        ledger = self._ledger_with_open_pr(tmp_path)
        published: dict = {}
        result = self._run(tmp_path, ledger, published, head="sha-rewritten-a", ancestor=False)
        assert result["status"] == "blocked"
        assert result["detail"]["reason"] == "candidate_diverged"
        assert published == {}

    def test_rejected_admission_leaves_the_old_admitted_head(self, tmp_path: Path):
        ledger = self._ledger_with_open_pr(tmp_path)

        def _publish_refused(workspace, owned_paths, **kw):
            return {"status": "blocked", "reason": "admission_rejected", "branch": "feat/train-repo-a"}

        result = self._run(tmp_path, ledger, {}, head="sha-new-a", publish=_publish_refused)
        assert result["status"] == "blocked"
        assert result["detail"]["reason"] == "admission_rejected"
        lines = ledger.read_text().splitlines()
        assert sum('"pr_open"' in ln for ln in lines) == 1, "no new pr_open was fabricated"
        assert any(ADMITTED in ln and '"pr_open"' in ln for ln in lines)

    def test_rejected_refresh_then_drift_is_still_refused_on_retry(self, tmp_path: Path):
        """A rejected refresh must not erase the admission either: a later retry that meets
        drift re-enters the decision and refuses (PR #909 r3 follow-through)."""
        ledger = self._ledger_with_open_pr(tmp_path)

        def _publish_refused(workspace, owned_paths, **kw):
            return {"status": "blocked", "reason": "admission_rejected", "branch": "feat/train-repo-a"}

        first = self._run(tmp_path, ledger, {}, head="sha-new-a", publish=_publish_refused)
        assert first["status"] == "blocked"
        published: dict = {}
        second = self._run(tmp_path, ledger, published, head="sha-new-a", live="sha-oob-a")
        assert second["status"] == "blocked" and second["detail"]["reason"] == "remote_drift"
        assert published == {}

    def test_stale_upstream_block_is_durable_until_the_pr_is_closed(self, tmp_path: Path):
        """PR #909 r4, codex: the stale-upstream block must not erase the downstream's
        admission either -- a re-run re-blocks; only closing the PR lets it republish."""
        from test_train_merge import TRAIN_2NODE_MD, _make_publish_stub, _setup_p3_done

        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map, sha_a="sha-admitted-a", sha_b="sha-admitted-b")
        run_loop_calls: list = []

        def _run(pr_open, live_a):
            def _run_loop(ws, *a, **kw):
                run_loop_calls.append(ws.name)
                return (None, [])
            return run_train(
                roadmap, ledger, run_mode="autonomous",
                resolve_workspace=lambda n: ws_map[n.node_id],
                _run_loop=_run_loop,
                _publish=_make_publish_stub({}),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=pr_open,
                _live_pr_head_sha_fn=lambda ws, br: live_a if br == "feat/train-a" else "sha-admitted-b",
                _merge_phase_enabled=True,
            )

        first = _run(_pr_is_open_true, "sha-oob-a")  # upstream repo-a advanced out of band
        assert first["status"] == "blocked" and first["detail"]["reason"] == "upstream_changed_downstream_pr_open"
        second = _run(_pr_is_open_true, "sha-oob-a")  # plain re-run, PR still open
        assert second["status"] == "blocked" and second["detail"]["reason"] == "upstream_changed_downstream_pr_open", (
            "a re-run must re-block, not republish the downstream fresh"
        )
        assert run_loop_calls == [], "no rebuild happened while the stale PR stayed open"
        state = read_ledger(ledger)["repo-b/specs/plan-b.md"]
        assert state.status == "blocked" and state.head_sha == "sha-admitted-b" and state.pr_url

    def test_live_head_read_failure_is_a_typed_block_not_an_escape(self, tmp_path: Path):
        """agent-harness#289, taken deliberately: the refresh's drift check reads the live
        head, so a failed read must be a blocked return with a ledger row."""
        ledger = self._ledger_with_open_pr(tmp_path)

        def _raises(ws, br):
            raise RuntimeError("gh unavailable")

        result = self._run(tmp_path, ledger, {}, head="sha-new-a", live_fn=_raises)
        assert result["status"] == "blocked"
        assert result["detail"]["reason"] == "live_pr_head_read_failed"
        assert read_ledger(ledger)["repo-a/specs/plan-a.md"].status == "blocked"

    def test_execute_nodes_are_never_refreshed(self, tmp_path: Path):
        roadmap = parse_train_roadmap(EXECUTE_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/train-repo-a",
            head_sha=ADMITTED, pr_url="https://gh.com/repo-a/pr/1", merge_order=0,
        ))

        def _head_must_not_be_read(ws):
            raise AssertionError("an execute node's workspace HEAD is coordinator-managed")

        result = run_train(
            roadmap, ledger, run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub({}),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass, _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=lambda ws, br: ADMITTED,
            _workspace_head_fn=_head_must_not_be_read,
            _merge_phase_enabled=True,
        )
        assert result["status"] == "drafts_open"

    def test_crash_after_running_append_resumes_to_one_publish(self, tmp_path: Path):
        """D4: a `running` record hides the prior pr_open in the last-wins fold, so the
        node republishes at HEAD through the ordinary arm -- exactly once -- and the prior
        pr_open line stays in the file."""
        ledger = self._ledger_with_open_pr(tmp_path)
        append_record(ledger, LedgerRecord(node_id="repo-a/specs/plan-a.md", status="running"))
        published: dict = {}
        calls = []

        def _publish(workspace, owned_paths, **kw):
            calls.append(kw.get("prebuilt"))
            return _make_prebuilt_publish_stub(published)(workspace, owned_paths, **kw)

        result = self._run(tmp_path, ledger, published, head="sha-new-a", publish=_publish)
        assert result["status"] == "drafts_open"
        assert calls == [True]
        lines = ledger.read_text().splitlines()
        assert any(ADMITTED in ln and '"pr_open"' in ln for ln in lines), "prior line preserved"


EXECUTE_1NODE_MD = """\
# Release Train: execute-single

## Nodes

### Node: repo-a / specs/plan-a.md

**Depends on:** (none)
**Channel:** (none)
"""


class TestRefreshGitHelpers:
    """The default seams behind `_prebuilt_refresh_decision`, against REAL git (board PR
    #909 r1, gemini: every refresh test injects them, so an argument-order mutant in
    `_is_ancestor` would have survived)."""

    def test_workspace_head_and_is_ancestor_against_real_git(self, tmp_path: Path):
        from phase_loop_runtime.train_runner import _is_ancestor, _workspace_head

        repo = _make_repo_with_origin(tmp_path)
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "a.txt").write_text("a\n"); _git(repo, "add", "a.txt"); _git(repo, "commit", "-q", "-m", "a")
        child = _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert _workspace_head(repo) == child
        assert _is_ancestor(repo, base, child) is True
        assert _is_ancestor(repo, child, base) is False, "argument order: (ancestor, descendant)"
        assert _is_ancestor(repo, "0" * 40, child) is None, "unknown object: undecidable, not False"
        assert _workspace_head(tmp_path / "not-a-repo") is None

    def test_undecidable_ancestry_is_refused_before_admission(self, tmp_path: Path):
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/train-repo-a",
            head_sha=ADMITTED, pr_url="https://gh.com/repo-a/pr/1", merge_order=0,
        ))
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        published: dict = {}
        result = run_train(
            roadmap, ledger, run_mode="autonomous",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass, _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=lambda ws, br: ADMITTED,
            _workspace_head_fn=lambda ws: "sha-new-a",
            _is_ancestor_fn=lambda ws, a, b: None,
            _merge_phase_enabled=True,
        )
        assert result["status"] == "blocked"
        assert result["detail"]["reason"] == "ancestry_unreadable"
        assert published == {}


class TestSealedPriorTransaction:
    """agent-harness#906 Step 2: a TERMINAL_SEALED prior transaction is never a resume
    candidate; the evidence store decides whether the attempt is over."""

    def test_disposition_maps_evidence_by_the_brokers_own_key(self, tmp_path: Path, monkeypatch):
        """The evidence read is keyed exactly as the broker files it
        (`<verb>\\0sha256(repo\\0branch\\0head)`) at the repository's broker namespace, and
        the three terminal classes map to complete / ambiguous / no. Writing to a REAL
        store needs FABPUB bootstrap receipts, so the store is faked at the seam the helper
        imports; the store's own suite covers its reads."""
        from types import SimpleNamespace
        from phase_loop_runtime.convergence.broker import evidence as evidence_mod
        from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
        from phase_loop_runtime.convergence.broker.live import repository_broker_namespace
        from phase_loop_runtime.convergence.contracts import publish_committed_branch_idempotency_key
        from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
        from phase_loop_runtime.train_runner import _sealed_publish_disposition

        repo = _make_repo_with_origin(tmp_path)
        expected_root = repository_broker_namespace(repo)
        records: dict = {}
        seen_roots: list = []

        class _FakeStore:
            def __init__(self, root, **kw):
                seen_roots.append(Path(root))
            def replay(self):
                return dict(records)

        monkeypatch.setattr(evidence_mod, "BrokerEvidenceStore", _FakeStore)
        from phase_loop_runtime.convergence.contracts import BrokerVerb
        tx = SimpleNamespace(canonical_repository_identity="ident", branch="feat/x", committed_head_sha="abc")
        # the broker's own dedup shape: `<verb>\0<base>` (see BrokerService._dedup_key)
        key = f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0" + publish_committed_branch_idempotency_key("ident", "feat/x", "abc")

        assert _sealed_publish_disposition(repo, tx) == "no"
        assert seen_roots == [expected_root], "the read must target the repository's broker namespace"
        records[key] = EvidenceRecord(key, TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, "pr")
        assert _sealed_publish_disposition(repo, tx) == "complete"
        records[key] = EvidenceRecord(key, TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN, "none")
        assert _sealed_publish_disposition(repo, tx) == "complete"
        records[key] = EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "?")
        assert _sealed_publish_disposition(repo, tx) == "ambiguous"
        # a record filed under a DIFFERENT head is not this transaction's evidence
        records.clear()
        records[f"{BrokerVerb.PUBLISH_COMMITTED_BRANCH.value}\0" + publish_committed_branch_idempotency_key("ident", "feat/x", "zzz")] = (
            EvidenceRecord("other", TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED, "pr")
        )
        assert _sealed_publish_disposition(repo, tx) == "no"

    def test_disposition_is_unreadable_when_the_store_cannot_be_opened(self, tmp_path: Path, monkeypatch):
        from types import SimpleNamespace
        from phase_loop_runtime.convergence.broker import evidence as evidence_mod
        from phase_loop_runtime.train_runner import _sealed_publish_disposition

        def _boom(root, **kw):
            raise PermissionError("no receipt")

        monkeypatch.setattr(evidence_mod, "BrokerEvidenceStore", _boom)
        tx = SimpleNamespace(canonical_repository_identity="i", branch="b", committed_head_sha="h")
        assert _sealed_publish_disposition(_make_repo_with_origin(tmp_path), tx) == "unreadable"

    def _run_step2(self, tmp_path, monkeypatch, disposition):
        """Drive the REAL Step 2 (default preflight, FABPUB active) with the inspector
        returning a sealed prior; the disposition seam stands in for the evidence read."""
        from phase_loop_runtime import publishing
        from phase_loop_runtime.convergence.broker import live

        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/train-repo")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "x.py").write_text("x = 1\n")
        _git(repo, "add", "src/x.py"); _git(repo, "commit", "-q", "-m", "work")
        from types import SimpleNamespace
        # a sealed transaction for an OLD head: the workspace HEAD (real git) differs
        sealed = publishing.PublishResumeCandidate(
            "TERMINAL_SEALED", SimpleNamespace(committed_head_sha="sha-old-admitted")
        )
        monkeypatch.setattr(live, "fabpub_capability_active", lambda: True)
        monkeypatch.setattr(publishing, "inspect_publish_resume_candidate", lambda *a, **k: sealed)

        class _Auth:
            checkpoint_root = tmp_path / "checkpoints"
            envelope_authority_preimage = {"node_id": "repo-a/specs/plan-a.md"}

        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        published: dict = {}
        broker = type("B", (), {"requires_gh_auth_preflight": False})()
        result = run_train(
            roadmap, tmp_path / "ledger" / "train.ledger.jsonl",
            run_mode="autonomous",
            resolve_workspace=lambda n: repo,
            coordinator_runtime=_make_runtime(broker),
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_prebuilt_publish_stub(published),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _pr_is_open=_pr_is_open_false,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _publish_authority_fn=lambda *a, **k: _Auth(),
            _sealed_disposition_fn=lambda ws, tx: disposition,
            _merge_phase_enabled=True,
        )
        return result, published

    def test_sealed_prior_with_observed_effect_does_not_block_preflight(self, tmp_path, monkeypatch):
        result, published = self._run_step2(tmp_path, monkeypatch, "complete")
        assert result["status"] == "drafts_open", result
        assert published["repo"]["prebuilt"] is True, "a FRESH prebuilt publish ran, not a replay"

    def test_sealed_prior_with_ambiguous_evidence_fails_preflight_zero_prs(self, tmp_path, monkeypatch):
        result, published = self._run_step2(tmp_path, monkeypatch, "ambiguous")
        assert result["status"] == "preflight_failed", result
        assert any("sealed publish transaction has ambiguous" in e for e in result["errors"])
        assert published == {}

    @pytest.mark.parametrize("disposition", ["no", "unreadable"])
    def test_sealed_prior_without_usable_evidence_fails_preflight_zero_prs(self, tmp_path, monkeypatch, disposition):
        """PR #909 r1, grok's seventh mutant: only 'complete' may proceed."""
        result, published = self._run_step2(tmp_path, monkeypatch, disposition)
        assert result["status"] == "preflight_failed", result
        assert any(f"sealed publish transaction has {disposition}" in e for e in result["errors"])
        assert published == {}


# ---------------------------------------------------------------------------
# 5. Prebuilt preflight + owned-paths detection against REAL git repos


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _make_repo_with_origin(tmp_path: Path) -> Path:
    """Clone-shaped repo: a bare 'origin' with a main branch, checked out locally."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin")
    return repo


class TestPrebuiltPreflightRealGit:
    def test_clean_and_ahead_passes(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        (repo / "feature.py").write_text("# work\n")
        _git(repo, "add", "feature.py")
        _git(repo, "commit", "-q", "-m", "prebuilt work")

        assert _check_branch_ahead_of_base(repo, "repo/plan", "main") is None

    def test_clean_but_not_ahead_errors(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        # Fresh branch AT origin/main — clean but not ahead → nothing to publish.
        _git(repo, "checkout", "-q", "-b", "feat/empty")

        err = _check_branch_ahead_of_base(repo, "repo/plan", "main")
        assert err is not None
        assert "not" in err and "ahead" in err

    def test_owned_paths_from_committed_diff(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        (repo / "a.py").write_text("a\n")
        (repo / "b.py").write_text("b\n")
        _git(repo, "add", "a.py", "b.py")
        _git(repo, "commit", "-q", "-m", "two files")

        paths = _prebuilt_owned_paths(repo, "main")
        assert sorted(paths) == ["a.py", "b.py"]

    # --- agent-harness#250 (N1/N4): `-z --no-renames` against a REAL git repo, proving
    # the rename source is surfaced (not hidden behind the destination) and a legit
    # within-scope rename still lists both endpoints identically to the broker's own
    # `_branch_diff_paths` re-derivation (the two MUST agree byte-for-byte).
    def test_rename_of_a_file_surfaces_both_source_and_destination(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        (repo / "unowned").mkdir()
        (repo / "unowned" / "x.py").write_text("x\n")
        _git(repo, "add", "unowned/x.py")
        _git(repo, "commit", "-q", "-m", "add unowned file")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")

        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        (repo / "owned").mkdir()
        _git(repo, "mv", "unowned/x.py", "owned/x.py")
        _git(repo, "commit", "-q", "-m", "move unowned file into owned/")

        paths = _prebuilt_owned_paths(repo, "main")
        # Both the destination AND the source must be present — a plain `--name-only`
        # (rename-detecting) diff would report ONLY "owned/x.py", hiding the unowned
        # source from any downstream coverage check.
        assert sorted(paths) == ["owned/x.py", "unowned/x.py"]

    def test_rename_within_the_same_owned_directory_lists_both_endpoints(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        (repo / "owned").mkdir()
        (repo / "owned" / "old.py").write_text("x\n")
        _git(repo, "add", "owned/old.py")
        _git(repo, "commit", "-q", "-m", "add owned file")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")

        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        _git(repo, "mv", "owned/old.py", "owned/new.py")
        _git(repo, "commit", "-q", "-m", "rename within owned/")

        paths = _prebuilt_owned_paths(repo, "main")
        # A within-scope rename lists BOTH endpoints (delete + add), not just the dest —
        # matching the broker side so a directory-owned entry covers both and the
        # coordinator never derives a scope the broker would then false-reject.
        assert sorted(paths) == ["owned/new.py", "owned/old.py"]

    # --- agent-harness#250 (IF-0-BRK-1 sharpening): "identical parsing" is not a strong
    # enough freeze if both sides identically .strip() a path — that still approves the
    # WRONG path when the real filename and an owned entry differ only by
    # whitespace/newlines. Prove against a REAL git repo that a leading/trailing-
    # whitespace filename and a filename with an embedded newline survive the `-z`
    # NUL-split byte-for-byte (no trimming), which is what the coverage check needs to
    # never collapse two distinct filenames into one.
    def test_owned_paths_preserve_whitespace_and_embedded_newline_filenames_verbatim(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        padded = "  padded.py  "
        newline_name = "has\nnewline.py"
        (repo / padded).write_text("x\n")
        (repo / newline_name).write_text("y\n")
        _git(repo, "add", "--", padded, newline_name)
        _git(repo, "commit", "-q", "-m", "weird filenames")

        paths = _prebuilt_owned_paths(repo, "main")
        assert set(paths) == {padded, newline_name}
        # A stripped/trimmed variant must be ABSENT — proving neither side trims.
        assert "padded.py" not in paths
        assert "has" not in paths and "newline.py" not in paths

    # --- agent-harness#250 (IF-0-BRK-1 byte-identity hole, cross-vendor CR): the previous
    # `text=True` capture applied universal-newline decoding, which translates the raw
    # bytes `\r` AND `\r\n` into `\n` at decode time — AFTER which the NUL-split can no
    # longer tell `a\r.py`, `a\r\n.py`, and `a\n.py` apart, so three DISTINCT valid git
    # paths collapsed onto the SAME Python string. Prove against a REAL git repo that all
    # three survive as distinct entries with the bytes-capture + os.fsdecode fix.
    def test_owned_paths_distinguish_cr_crlf_and_lf_filenames(self, tmp_path: Path):
        import os as _os

        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        cr_name = _os.fsdecode(b"a\rcr.py")
        crlf_name = _os.fsdecode(b"a\r\ncrlf.py")
        lf_name = "a\nlf.py"
        for name in (cr_name, crlf_name, lf_name):
            (repo / name).write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "cr/crlf/lf filenames")

        paths = _prebuilt_owned_paths(repo, "main")
        # All three must be present AND distinct — a universal-newline collapse would
        # merge two or more of these onto the same string.
        assert set(paths) == {cr_name, crlf_name, lf_name}
        assert len(paths) == 3

    # --- agent-harness#250: a git path is bytes, not guaranteed UTF-8. `text=True` would
    # raise UnicodeDecodeError on a non-UTF-8 filename byte; the fix (bytes-capture +
    # os.fsdecode with surrogateescape) must not crash and must round-trip losslessly.
    def test_owned_paths_do_not_raise_on_invalid_utf8_filename(self, tmp_path: Path):
        import os as _os

        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        invalid_bytes = b"invalid-\xffbyte.py"
        name = _os.fsdecode(invalid_bytes)
        (repo / name).write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "invalid utf-8 filename")

        paths = _prebuilt_owned_paths(repo, "main")  # must not raise
        assert len(paths) == 1
        assert _os.fsencode(paths[0]) == invalid_bytes

    # --- agent-harness#250 (cross-vendor CR, codex): a DOWNSTREAM consumer of the
    # surrogate-escaped `_prebuilt_owned_paths` output re-encoded it with a strict
    # (default utf-8) str.encode() when building the owned-path digest in
    # `_default_build_admission`, raising UnicodeEncodeError on the very surrogates
    # os.fsdecode produces for an invalid-UTF-8 filename byte -- so the LIVE publish
    # path still crashed on an owned path git itself accepted. The fix swaps that
    # encode() for os.fsencode (same surrogateescape policy as os.fsdecode), so it
    # must not raise here and must produce a deterministic digest. ---
    def test_default_build_admission_does_not_raise_on_invalid_utf8_owned_path(
        self, tmp_path: Path, request
    ):
        import os as _os
        from types import SimpleNamespace

        from _fabpub_tdd_guard import fabpub_migrated_activated, fabpub_symbol

        invalid_bytes = b"invalid-\xffbyte.py"
        owned_paths = [_os.fsdecode(invalid_bytes)]
        runtime = _make_runtime(broker_client=None)
        node = SimpleNamespace(node_id="repo-a")

        if fabpub_migrated_activated(
            request,
            symbol=("phase_loop_runtime.train_runner", "_default_build_publish_authority"),
            detail=(
                "this node still imports and calls _default_build_admission, which the FABPUB "
                "handoff freeze requires to be ABSENT; the surrogate-escape owned-path digest "
                "property moves to _default_build_publish_authority"
            ),
        ):
            # plan:297 — the replacement builder preserves the surrogate-escaped
            # owned-path digest behaviour, so the same property is asserted there.
            build_authority = fabpub_symbol(
                "phase_loop_runtime.train_runner", "_default_build_publish_authority"
            )
            authority = build_authority(runtime, node, tmp_path, owned_paths)
            assert authority is not None
            assert authority.owned_paths_digest
            again = build_authority(runtime, node, tmp_path, owned_paths)
            assert authority.owned_paths_digest == again.owned_paths_digest
            # The superseded builder must be gone, so this node and the handoff
            # falsifier can both be green in ONE process.
            import phase_loop_runtime.train_runner as _tr

            assert not hasattr(_tr, "_default_build_admission")
            return

        from phase_loop_runtime.train_runner import _default_build_admission

        # Must NOT raise UnicodeEncodeError.
        admission = _default_build_admission(runtime, node, tmp_path, owned_paths)
        assert admission is not None
        assert admission.approval_digest

        # The digest must be deterministic for the same owned_paths (not a random
        # per-call artifact of the surrogate handling).
        admission2 = _default_build_admission(runtime, node, tmp_path, owned_paths)
        assert admission.approval_digest == admission2.approval_digest

    def test_default_build_admission_digest_unchanged_for_ascii_owned_paths(
        self, tmp_path: Path, request
    ):
        """os.fsencode(s) == s.encode('utf-8') for ordinary ASCII/UTF-8 paths, so this
        fix must not change the digest (and therefore the approval) for the normal case."""
        import hashlib
        import os as _os
        from types import SimpleNamespace

        from _fabpub_tdd_guard import fabpub_migrated_activated, fabpub_symbol

        owned_paths = ["a.py", "src/pkg/mod.py"]
        runtime = _make_runtime(broker_client=None)
        node = SimpleNamespace(node_id="repo-a")
        expected_owned_digest = hashlib.sha256(_os.fsencode("\0".join(owned_paths))).hexdigest()
        assert expected_owned_digest == hashlib.sha256("\0".join(owned_paths).encode()).hexdigest()

        if fabpub_migrated_activated(
            request,
            symbol=("phase_loop_runtime.train_runner", "_default_build_publish_authority"),
            detail=(
                "this node still imports and calls _default_build_admission, which the FABPUB "
                "handoff freeze requires to be ABSENT; the ASCII owned-path digest property "
                "moves to _default_build_publish_authority"
            ),
        ):
            build_authority = fabpub_symbol(
                "phase_loop_runtime.train_runner", "_default_build_publish_authority"
            )
            authority = build_authority(runtime, node, tmp_path, owned_paths)
            # The ASCII digest is byte-identical across the handoff migration.
            assert authority.owned_paths_digest == expected_owned_digest
            import phase_loop_runtime.train_runner as _tr

            assert not hasattr(_tr, "_default_build_admission")
            return

        from phase_loop_runtime.train_runner import _default_build_admission

        admission = _default_build_admission(runtime, node, tmp_path, owned_paths)
        assert admission.approval_digest


# ---------------------------------------------------------------------------
# 6. Dirty prebuilt workspace fails preflight (via the default preflight path)


class TestPrebuiltDirtyPreflight:
    def test_dirty_prebuilt_workspace_fails(self, tmp_path: Path):
        repo = _make_repo_with_origin(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feat/prebuilt")
        (repo / "committed.py").write_text("x\n")
        _git(repo, "add", "committed.py")
        _git(repo, "commit", "-q", "-m", "committed")
        # Now dirty the tree (uncommitted change).
        (repo / "uncommitted.py").write_text("dirty\n")

        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        publish_calls: List[str] = []

        with (
            patch("phase_loop_runtime.train_runner._check_gh_auth", return_value=None),
            patch("phase_loop_runtime.train_runner._check_remote_reachable", return_value=None),
        ):
            result = run_train(
                roadmap,
                ledger,
                run_mode="autonomous",
                resolve_workspace=lambda n: repo,
                _run_loop=lambda *a, **kw: (None, []),
                _publish=lambda *a, **kw: publish_calls.append("x"),
                # real _default_preflight (clean + ahead checks run against repo)
            )

        assert result["status"] == "preflight_failed"
        assert any("uncommitted" in e.lower() for e in result["errors"])
        assert publish_calls == []


def test_prebuilt_owned_paths_fails_closed_on_diff_error(tmp_path):
    """CR fix: a git-diff error must RAISE (fail-closed), not return [] — an empty
    owned-paths scope would let the broker admission approve nothing while the push
    publishes the real branch (approved-nothing / published-something mismatch)."""
    import subprocess as sp
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    sp.run(["git", "init", "-q", str(tmp_path)], check=True)
    sp.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "x"], check=True, env=env)
    # No 'origin/main' ref → `git diff origin/main...HEAD` fails → must raise, never [].
    with pytest.raises(RuntimeError):
        _prebuilt_owned_paths(tmp_path)
