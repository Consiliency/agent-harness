"""Cross-repo release-train coordinator (P3).

Serial draft-PR execution: topo-sort the train, preflight ALL repos, then per
node (in topo order): inject upstream draft ref via set_upstream_ref → invoke
the unchanged per-repo run_loop → publish a draft PR → append to ledger.

Safety invariants (enforced structurally, asserted in tests):
  1. **Zero-PRs-on-preflight-failure**: preflight runs on ALL repos before the
     per-node loop is entered.  If any check fails, ``run_train`` returns
     immediately with ``status="preflight_failed"`` and zero publish calls.
     Train-schema validation (T-A/B/C/D via ``validate_train_loud``) runs as
     part of this gate — a malformed train (e.g. a ``none``-channel dependency
     edge) opens zero PRs.
  2. **Draft-only**: every ``publish_from_worktree`` call uses ``draft=True``.
     P3 never merges.  The merge seam (P4) is absent here.
  3. **Train state off .phase-loop/**: ledger_path is caller-supplied and must
     pass ``_assert_not_phase_loop``; the coordinator never touches any repo's
     ``.phase-loop/`` directory.
  4. **Resumable with upstream-change detection**: a partial run leaves prior
     nodes' draft PRs open and the failed node ``blocked`` in the ledger.
     Re-running re-reads both the ledger and live PR state; confirmed-open
     nodes are skipped unless an upstream changed (rebuilt this run, or its live
     head SHA diverged from the ledger — out-of-band push).  When an upstream
     changed and the downstream's PR is already open, the downstream is
     **blocked with a clear reason** (``upstream_changed_downstream_pr_open``)
     so the user can close the stale PR and re-run.
     NOTE: automatic downstream rebuild when an upstream changes requires an
     update-existing-PR primitive and is deferred to a future release.
  5. **Exception safety**: if inject or run_loop raises, the node is marked
     ``blocked`` in the ledger (never left stuck at ``running``).

All git/gh/run_loop/publish boundaries are injectable seams so the module is
fully testable without live network access.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set

from .cross_repo_channel import ChannelDescriptor, set_upstream_ref
from .train_ledger import LedgerRecord, append_record, read_ledger
from .train_roadmap import TrainEdge, TrainNode, TrainRoadmap

# ---------------------------------------------------------------------------
# Types

ResolveWorkspace = Callable[[TrainNode], Path]
ResolveOwnedPaths = Callable[[TrainNode], Sequence[str]]

# ---------------------------------------------------------------------------
# Preflight check functions
# Each is a module-level function so tests can patch it individually.


def _check_gh_auth() -> Optional[str]:
    """Return an error string if gh auth is not valid, else None.

    Stubbable seam: ``patch("phase_loop_runtime.train_runner._check_gh_auth")``.
    """
    completed = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        return f"gh auth status failed: {completed.stderr.strip() or 'not authenticated'}"
    return None


def _check_repo_clean(workspace: Path, node_id: str) -> Optional[str]:
    """Return an error string if the workspace has uncommitted changes, else None."""
    completed = subprocess.run(
        ["git", "-C", str(workspace), "status", "--short"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        return (
            f"[{node_id}] git status failed "
            f"(workspace may not be a git repo): {completed.stderr.strip()}"
        )
    if completed.stdout.strip():
        return f"[{node_id}] workspace '{workspace}' has uncommitted changes — preflight failed"
    return None


def _check_remote_reachable(workspace: Path, node_id: str, remote: str = "origin") -> Optional[str]:
    """Return an error string if the remote is not reachable, else None."""
    completed = subprocess.run(
        ["git", "-C", str(workspace), "ls-remote", "--exit-code", remote, "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return (
            f"[{node_id}] remote '{remote}' is not reachable: "
            f"{completed.stderr.strip() or 'ls-remote failed'}"
        )
    return None


def _check_base_branch_exists(
    workspace: Path, node_id: str, base: str = "main"
) -> Optional[str]:
    """Return an error string if origin/<base> does not exist, else None."""
    completed = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--verify", f"origin/{base}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return f"[{node_id}] base branch 'origin/{base}' does not exist"
    return None


def _default_preflight(
    nodes: List[TrainNode],
    resolve_workspace: ResolveWorkspace,
) -> List[str]:
    """Run all preflight checks across all nodes; return list of errors (empty = pass).

    Checks (in order):
    1. ``gh auth status`` — once, globally.
    2. Per-repo: workspace clean (no uncommitted changes).
    3. Per-repo: remote ``origin`` is reachable.
    4. Per-repo: base branch ``origin/main`` exists.

    A non-empty return means the entry gate is closed; zero PRs must be opened.
    """
    errors: List[str] = []

    # gh auth — once globally, before touching any repo
    auth_err = _check_gh_auth()
    if auth_err:
        errors.append(auth_err)

    for node in nodes:
        workspace = resolve_workspace(node)
        for check_fn in (
            _check_repo_clean,
            _check_remote_reachable,
            _check_base_branch_exists,
        ):
            err = check_fn(workspace, node.node_id)
            if err:
                errors.append(err)

    return errors


# ---------------------------------------------------------------------------
# Live PR state seams


def _live_pr_is_open(workspace: Path, branch: str) -> bool:
    """Return True if ``branch`` has an open PR on the remote.

    Stubbable seam for tests.  Uses ``_gh_pr_metadata`` from ``git_topology``
    (already reused by the P1 publish primitive for the same reason).
    """
    from .git_topology import _gh_pr_metadata

    meta = _gh_pr_metadata(workspace, branch)
    return bool(meta.get("pr_url"))


def _live_pr_head_sha(workspace: Path, branch: str) -> Optional[str]:
    """Return the live PR head commit SHA for ``branch``, or None if unavailable.

    Queries ``gh pr list`` (the same endpoint as ``_gh_pr_metadata``, which uses
    the proven ``--head <branch>`` flag) and extracts ``headRefOid`` — the commit
    SHA at the PR's head, which may differ from the ledger-recorded value if the
    branch was force-pushed since the last run.

    Uses ``gh pr list --head <branch>`` (not ``gh pr view``, which takes a PR
    number, not a branch ref).

    Stubbable seam: inject ``_live_pr_head_sha_fn`` into :func:`run_train`.
    """
    try:
        completed = subprocess.run(
            [
                "gh", "pr", "list",
                "--head", branch,
                "--state", "open",
                "--limit", "1",
                "--json", "headRefOid",
                "--jq", ".[0].headRefOid",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(workspace),
        )
        sha = completed.stdout.strip() if completed.returncode == 0 else ""
        return sha or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# PR body builder


def _build_pr_body(
    node: TrainNode,
    topo_order: List[TrainNode],
    upstream_results: Dict[str, Dict],
    upstream_edges: List[TrainEdge],
) -> str:
    """Build the PR body with cross-repo dependency links and merge order.

    At creation time, upstream PRs are already open (topo order guarantees
    it).  Downstream PRs are not yet open, so only backward-links are included.
    """
    lines: List[str] = [
        f"## Cross-repo release train\n\n",
        f"**Node:** `{node.node_id}`\n\n",
    ]

    if upstream_edges:
        lines.append("### Upstream dependencies (must merge first)\n\n")
        for edge in upstream_edges:
            result = upstream_results.get(edge.upstream.node_id, {})
            pr_url = result.get("pr_url", "(not yet open)")
            lines.append(f"- [{edge.upstream.node_id}]({pr_url})\n")
        lines.append("\n")

    lines.append("### Train merge order\n\n")
    for i, n in enumerate(topo_order, 1):
        marker = " **(this PR)**" if n.node_id == node.node_id else ""
        lines.append(f"{i}. `{n.node_id}`{marker}\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Main coordinator


def run_train(
    roadmap: TrainRoadmap,
    ledger_path: Path,
    *,
    run_mode: str = "autonomous",
    resolve_workspace: ResolveWorkspace,
    resolve_owned_paths: Optional[ResolveOwnedPaths] = None,
    # Injectable seams — default to the live implementations; tests override.
    _run_loop: Optional[Callable] = None,
    _publish: Optional[Callable] = None,
    _set_upstream_ref_fn: Optional[Callable] = None,
    _pr_is_open: Optional[Callable] = None,
    _live_pr_head_sha_fn: Optional[Callable] = None,
    _preflight_fn: Optional[Callable] = None,
) -> Dict:
    """Coordinate a cross-repo release train: preflight, topo-sort, draft-PR open.

    Parameters
    ----------
    roadmap:
        Parsed ``TrainRoadmap`` (P2 schema).
    ledger_path:
        Path to the coordinator-side ledger file.  Must not be inside any
        repo's ``.phase-loop/`` (enforced by ``append_record``).
    run_mode:
        ``"autonomous"`` or ``"governed"``.  Passed unchanged to each
        per-repo ``run_loop`` call.
    resolve_workspace:
        Maps a ``TrainNode`` to its workspace ``Path`` on disk.
    resolve_owned_paths:
        Maps a ``TrainNode`` to the list of paths the publish primitive
        should stage.  When ``None`` (the default for real end-to-end runs),
        the coordinator uses the paths produced by ``run_loop`` itself:
        ``StateSnapshot.phase_owned_dirty_paths`` (or ``dirty_paths`` as
        fallback).  Callers may pass an explicit resolver to override this
        (e.g. tests, or callers that know the paths ahead of time).
    _run_loop, _publish, _set_upstream_ref_fn, _pr_is_open,
    _live_pr_head_sha_fn, _preflight_fn:
        Injectable seams for testing.  Each defaults to the corresponding
        live implementation.

    Returns
    -------
    dict
        ``{"status": "completed", "nodes": {node_id: {branch, head_sha, pr_url}}}``
        on success;
        ``{"status": "blocked", "node_id": ..., "detail": ...}`` if a node
        fails (prior nodes' draft PRs remain open; train is resumable);
        ``{"status": "preflight_failed", "errors": [...]}`` if any preflight
        check or train-validation fails (zero PRs opened).
    """
    # Resolve seams
    from .publishing import publish_from_worktree as _default_publish
    from .runner import run_loop as _default_run_loop

    run_loop_fn = _run_loop if _run_loop is not None else _default_run_loop
    publish_fn = _publish if _publish is not None else _default_publish
    set_upstream_ref_fn = (
        _set_upstream_ref_fn if _set_upstream_ref_fn is not None else set_upstream_ref
    )
    pr_is_open_fn = _pr_is_open if _pr_is_open is not None else _live_pr_is_open
    live_pr_head_sha_fn = (
        _live_pr_head_sha_fn if _live_pr_head_sha_fn is not None else _live_pr_head_sha
    )
    preflight_fn = _preflight_fn if _preflight_fn is not None else _default_preflight

    # Track whether caller supplied an explicit owned-paths resolver so we know
    # whether to fall back to the run_loop-produced snapshot paths (Finding #1).
    _explicit_owned_paths = resolve_owned_paths is not None

    # --- Step 0: Train-schema validation (T-A/B/C/D) — BEFORE any PR ------
    # A malformed train (e.g. a none-channel dependency edge) must open ZERO
    # PRs.  validate_train_loud raises ValueError on any violation.
    from .train_roadmap import validate_train_loud

    try:
        validate_train_loud(roadmap)
    except ValueError as exc:
        return {
            "status": "preflight_failed",
            "errors": [f"train validation failed: {exc}"],
        }

    # --- Step 1: Topo-sort (raises ValueError on cycle) --------------------
    topo_order = roadmap.topo_order()

    # --- Step 2: Train-level preflight — ALL repos, BEFORE any PR ----------
    # This is the structural guarantee that preflight failure → zero PRs:
    # we return immediately here, before the per-node loop is entered.
    preflight_errors = preflight_fn(topo_order, resolve_workspace)
    if preflight_errors:
        return {
            "status": "preflight_failed",
            "errors": preflight_errors,
        }

    # --- Step 3: Re-read ledger + live PR state (resume support) -----------
    ledger_state = read_ledger(ledger_path)
    # completed_nodes: node_id → {branch, head_sha, pr_url}
    # These are the upstream refs the coordinator can inject into downstream
    # nodes via set_upstream_ref (IF-0-P2-2).
    completed_nodes: Dict[str, Dict] = {}
    # out_of_band_upstreams: nodes whose live PR head SHA differs from the
    # ledger-recorded head_sha — an out-of-band push since the last run.
    out_of_band_upstreams: Set[str] = set()

    for node in topo_order:
        nid = node.node_id
        rec = ledger_state.get(nid)
        if rec and rec.status == "pr_open" and rec.branch and rec.pr_url:
            workspace = resolve_workspace(node)
            if pr_is_open_fn(workspace, rec.branch):
                # Prefer the live PR head SHA (the branch may have been updated
                # since the last run); fall back to the ledger-recorded head_sha.
                live_sha = live_pr_head_sha_fn(workspace, rec.branch)
                head_sha = live_sha or rec.head_sha
                # Detect out-of-band push: live SHA exists and differs from ledger.
                if live_sha and rec.head_sha and live_sha != rec.head_sha:
                    out_of_band_upstreams.add(nid)
                completed_nodes[nid] = {
                    "branch": rec.branch,
                    "head_sha": head_sha,
                    "pr_url": rec.pr_url,
                }

    # --- Step 4: Execute in topo order ------------------------------------
    # rebuilt_this_run tracks nodes where run_loop was actually invoked during
    # this execution.  Used to detect when a downstream's confirmed-open PR
    # is stale because its upstream was rebuilt (Finding #4).
    rebuilt_this_run: Set[str] = set()

    for i, node in enumerate(topo_order):
        nid = node.node_id

        # Resume: skip nodes already confirmed pr_open (live PR check passed).
        # BUT: if an upstream changed — either rebuilt this run OR an out-of-band
        # push advanced its SHA since the last run — and this node's PR is open,
        # we cannot silently skip (stale) or re-publish (no update-existing-PR
        # primitive exists).  Block with a clear reason so the user can close the
        # stale downstream PR and re-run.
        #
        # NOTE: automatic downstream rebuild when an upstream changes requires an
        # update-existing-PR primitive and is deferred to a future release.
        if nid in completed_nodes:
            upstream_edges = roadmap.edges_for_downstream(node)
            changed_upstreams = [
                edge for edge in upstream_edges
                if edge.upstream.node_id in rebuilt_this_run
                or edge.upstream.node_id in out_of_band_upstreams
            ]
            if not changed_upstreams:
                continue
            # An upstream changed and this node's draft PR is still open.
            # Block so the user can close the stale PR and re-run.
            change_reasons: List[str] = []
            for edge in changed_upstreams:
                uid = edge.upstream.node_id
                if uid in rebuilt_this_run:
                    change_reasons.append(f"upstream {uid!r} was rebuilt this run")
                else:
                    new_sha = completed_nodes.get(uid, {}).get("head_sha", "<unknown>")
                    change_reasons.append(
                        f"upstream {uid!r} advanced to {new_sha!r} (out-of-band push)"
                    )
            detail_msg = (
                "; ".join(change_reasons)
                + f"; close/supersede the stale downstream PR and re-run"
            )
            append_record(
                ledger_path,
                LedgerRecord(
                    node_id=nid,
                    status="blocked",
                    branch=completed_nodes[nid].get("branch"),
                ),
            )
            return {
                "status": "blocked",
                "node_id": nid,
                "detail": {
                    "reason": "upstream_changed_downstream_pr_open",
                    "message": detail_msg,
                },
            }

        workspace = resolve_workspace(node)
        upstream_edges = roadmap.edges_for_downstream(node)

        # Mark as running (durable breadcrumb for diagnostics)
        append_record(ledger_path, LedgerRecord(node_id=nid, status="running"))

        try:
            # (i) Inject upstream draft refs (IF-0-P2-2) BEFORE run_loop.
            #     Collect injected paths to union into owned_paths after run_loop.
            #
            # The guard below is a defensive invariant.  It should be unreachable
            # in a well-formed train: validate_train_loud (T-B) ensures every
            # upstream is a declared node, and topo-sort guarantees we processed
            # it before this node.  If the upstream failed/was blocked, run_train
            # returns immediately and never reaches this downstream.  Kept here to
            # make the "no silent skip" contract explicit and catch future refactors.
            injected_channel_paths: List[str] = []
            for edge in upstream_edges:
                upstream_result = completed_nodes.get(edge.upstream.node_id)
                if upstream_result is None:
                    # Defensive: topo-order + T-B validation make this
                    # unreachable; kept as an explicit fail-loud guard.
                    raise RuntimeError(
                        f"upstream ref for '{edge.upstream.node_id}' is not resolved "
                        f"(not in completed_nodes) — cannot inject into "
                        f"'{nid}'; the upstream must be built and published first"
                    )
                ref = upstream_result.get("head_sha")
                if not ref:
                    # Block: do NOT fall back to injecting a moving branch name.
                    # A missing SHA means neither the live query nor the ledger
                    # have a pinnable ref — injecting a branch name would build
                    # the downstream against a moving target.
                    raise RuntimeError(
                        f"no resolvable SHA for upstream '{edge.upstream.node_id}' "
                        f"(live head SHA query returned None and ledger head_sha is "
                        f"None); cannot inject a moving branch name for channel "
                        f"{edge.channel.kind!r} — resolve the upstream SHA and re-run"
                    )
                injected = set_upstream_ref_fn(workspace, edge.channel, ref)
                if injected:
                    injected_channel_paths.extend(injected)

            # (ii) Invoke the unchanged per-repo run_loop.
            #      The real run_loop returns (StateSnapshot, list[LaunchResult]).
            result_tuple = run_loop_fn(
                workspace, workspace / node.roadmap, run_mode=run_mode
            )

            # (iii) Determine owned paths (Finding #1).
            #       If the caller supplied an explicit resolver, honour it.
            #       Otherwise use the snapshot's produced/owned paths so the
            #       published PR contains the actual implementation, not just
            #       the roadmap file.
            if _explicit_owned_paths:
                owned_paths = list(resolve_owned_paths(node))  # type: ignore[arg-type]
            else:
                snapshot = result_tuple[0] if isinstance(result_tuple, tuple) else None
                if snapshot is not None:
                    produced = (
                        getattr(snapshot, "phase_owned_dirty_paths", None)
                        or getattr(snapshot, "dirty_paths", None)
                        or ()
                    )
                    owned_paths = list(produced)
                else:
                    owned_paths = []

            # Union the coordinator-injected channel paths into owned_paths so
            # the pin/submodule change always ships in the PR even if run_loop's
            # snapshot doesn't include the injected file (Finding #6 / union fix).
            # de-duplicate while preserving order (snapshot paths first).
            if injected_channel_paths:
                seen = set(owned_paths)
                for p in injected_channel_paths:
                    if p not in seen:
                        owned_paths.append(p)
                        seen.add(p)

            # (iv) Publish as draft PR via the P1 runtime primitive.
            #      draft=True is structural — P3 never merges.
            pr_body = _build_pr_body(node, topo_order, completed_nodes, upstream_edges)
            publish_result = publish_fn(
                workspace,
                owned_paths,
                draft=True,  # P3 invariant: draft-only, never merge
                pr_body=pr_body,
            )

        except Exception as exc:
            # Inject or run_loop or publish raised — mark blocked so the node
            # is never left stuck at "running" (Finding #3 / exception safety).
            append_record(
                ledger_path,
                LedgerRecord(
                    node_id=nid,
                    status="blocked",
                    branch=None,
                ),
            )
            return {
                "status": "blocked",
                "node_id": nid,
                "detail": {"reason": str(exc)},
            }

        if publish_result.get("status") != "published":
            # Node blocked by the publish primitive (e.g. push rejected, dirty
            # worktree, publication_blocked).  Record in ledger and halt.
            # Prior nodes' draft PRs remain open; the train is resumable.
            append_record(
                ledger_path,
                LedgerRecord(
                    node_id=nid,
                    status="blocked",
                    branch=publish_result.get("branch"),
                ),
            )
            return {
                "status": "blocked",
                "node_id": nid,
                "detail": publish_result,
            }

        # Record success — store draft head in ``head_sha``; leave
        # ``upstream_merge_sha`` for P4's merged-SHA (Finding #5).
        branch = publish_result["branch"]
        head_sha = publish_result["head_sha"]
        pr_url = publish_result["pr_url"]

        completed_nodes[nid] = {
            "branch": branch,
            "head_sha": head_sha,
            "pr_url": pr_url,
        }
        rebuilt_this_run.add(nid)

        append_record(
            ledger_path,
            LedgerRecord(
                node_id=nid,
                status="pr_open",
                branch=branch,
                pr_url=pr_url,
                head_sha=head_sha,       # draft branch HEAD SHA
                upstream_merge_sha=None,  # reserved for P4 (merge SHA only)
                merge_order=i,
            ),
        )

    return {"status": "completed", "nodes": completed_nodes}
