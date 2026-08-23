"""FAB (Consiliency/agent-harness#191) activation milestone, piece 1 — wiring
the design §4.4 promotion-time re-assertion into the REAL merge path.
Deliberately UNMARKED (no ``dotfiles_integration``) so CI's
``-m "not dotfiles_integration"`` runs this module (the goal-id-inc2 lesson).

Piece 1 is *wiring only*: no producer (writes FAB provenance on a board pass)
and no consumer (delta-review shortcut) exist yet, so FAB provenance is
fabricated here via the same Lane A/D helpers the existing Lane D tests use
(``fab_provenance``/``fab_gate``), exactly as the plan instructs.

Coverage:
  N1. Byte-neutrality (``PHASE_LOOP_FAB`` unset/absent — the default):
      ``train_runner._default_train_review`` and
      ``runner.governed_premerge_for_run`` never call
      ``fab_canonical.equivalent()``. Stash-proof: this asserts the exact
      property that is unchanged from ``main`` for the non-FAB path.
  N2. Byte-neutrality at the P4 merge-loop threading layer: ``run_train``'s
      merge loop never passes a ``run_id`` kwarg to ``merge_pr_fn`` — a
      strict 4-arg stub (the SAME shape every pre-existing
      ``test_train_merge.py`` stub uses) would ``TypeError`` otherwise. True
      regardless of ``PHASE_LOOP_FAB``, because no producer populates
      ``completed_nodes[node_id]["fab_run_id"]`` yet (piece 2, out of scope).
  P1. Flag ON + ``run_id=None`` -> still inert: merge proceeds,
      ``fab_canonical.equivalent()`` never called.
  P2. Flag ON + ``run_id`` set + no provenance recorded for it (scoped-
      missing/unreadable — ``ProvenanceNotFound``) -> fail CLOSED: merge
      REFUSED (``RuntimeError``), ``gh pr merge`` never invoked. FIX
      (agent-harness#191 CR): a present ``run_id`` is itself the FAB-scope
      marker, so ``ProvenanceNotFound`` (missing, deleted, cleaned up, wrong
      workspace, or a failed write) must NOT be treated as "never scoped to
      FAB" — that was the fail-open this test now pins closed. Matches
      ``fab_gate.py``'s own fail-closed contract at ``fab_gate_validator``.
  P2b. Same scoped-present-run_id posture, but the provenance artifact
      exists and is UNREADABLE/corrupt (malformed JSON -> raises
      ``ProvenanceInvalid``, not ``ProvenanceNotFound``) -> also fails
      CLOSED (``RuntimeError``), never an unhandled exception and never a
      silent merge.
  P3. Flag ON + ``run_id`` set + provenance exists + live PR unchanged ->
      merge proceeds (``equivalent()`` is called and returns EQUIVALENT).
  P4. Flag ON + ``run_id`` set + provenance exists + live content DRIFTED
      after the board pass (a new commit landed on the reviewed branch, base
      unchanged) -> merge REFUSED (``RuntimeError``); ``gh pr merge`` is
      never invoked.
  P5. Fail-closed: flag ON + ``run_id`` set + provenance exists + the live
      head cannot be resolved -> REFUSED.
  P6. Flag OFF (even though a drifted, provenance-bearing ``run_id`` is
      supplied) -> still inert; the opt-in flag gates everything.
"""
from __future__ import annotations

import json
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from phase_loop_runtime import fab_canonical as fc
from phase_loop_runtime import fab_gate as fg
from phase_loop_runtime import fab_provenance as fp
from phase_loop_runtime import governed_premerge as gp
from phase_loop_runtime import runner as runner_mod
from phase_loop_runtime.panel_invoker import SeatOutcomeRecord
from phase_loop_runtime.train_runner import _default_train_review, _live_merge_pr, run_train

from test_train_merge import (
    TRAIN_2NODE_MD,
    _FakeCompletedProcess,
    _approval_review_fn,
    _gh_subcommand,
    _make_merge_pr_stub,
    _make_publish_stub,
    _merged_sha_json,
    _preflight_pass,
    _premerge_json,
    _pr_is_open_true,
    _reverify_pass,
    _setup_p3_done,
)
from phase_loop_runtime.train_roadmap import parse_train_roadmap

_GIT = shutil.which("git")
_REAL_SUBPROCESS_RUN = subprocess.run  # captured before any test patches it
REPO_SLUG = "github.com/testorg/testrepo"


# --------------------------------------------------------------------------- #
# Git + FAB-provenance fixtures — mirrors test_fab_gate_d.py /
# test_fab_canonical_b.py's "two remotes" pattern (origin = github-shaped URL,
# identity-only; fetchsrc = a real local bare repo the live re-fetch actually
# reaches), duplicated here as plain functions (not a shared TestCase import)
# so pytest never double-collects an imported unittest.TestCase.
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = _REAL_SUBPROCESS_RUN(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result


def _rev_parse(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def _make_fab_repo(tmp_path: Path) -> Path:
    fetchsrc_dir = tmp_path / "fetchsrc.git"
    _REAL_SUBPROCESS_RUN(["git", "init", "-q", "--bare", str(fetchsrc_dir)], check=True)
    repo = tmp_path / "work"
    _REAL_SUBPROCESS_RUN(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "remote", "add", "origin", "git@github.com:testorg/testrepo.git")
    _git(repo, "remote", "add", "fetchsrc", str(fetchsrc_dir))
    return repo


def _write(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _rev_parse(repo)


def _push_main(repo: Path) -> None:
    _git(repo, "push", "-q", "-f", "fetchsrc", "HEAD:refs/heads/main")


def _finding(id_: str) -> fp.Finding:
    return fp.Finding(id=id_, severity="block", status="clean", path_scope=("a.py",), body_ref=f"sha256:{'0' * 64}")


def _seat(seat_key: str, *, finding_ids: tuple = ()) -> fp.ProvenanceSeat:
    return fp.ProvenanceSeat(
        seat_key=seat_key,
        vendor_leg="codex",
        required=True,
        status="OK",
        seat_instance_id=f"{seat_key}@1",
        epoch=1,
        artifact_digest="1" * 64,
        evidence_digest="2" * 64,
        verdict="AGREE",
        finding_ids=finding_ids,
    )


def _durable_from_seat(seat: fp.ProvenanceSeat) -> SeatOutcomeRecord:
    return SeatOutcomeRecord(
        seat_key=seat.seat_key,
        vendor_leg=seat.vendor_leg,
        required=seat.required,
        status=seat.status,
        attempt_id="a1",
        epoch=seat.epoch,
        artifact_digest=seat.artifact_digest,
        completed_at="2026-01-01T00:00:00Z",
        evidence_digest=seat.evidence_digest,
        reason=None,
        verdict=seat.verdict,
        finding_ids=seat.finding_ids,
        seat_instance_id=seat.seat_instance_id,
    )


def _persist_provenance(repo: Path, run_id: str, *, base_sha: str, head_sha: str) -> None:
    """Fabricate + persist a PASSING FAB provenance artifact reviewed at
    ``base_sha``..``head_sha`` (Lane A/D helpers only — no producer)."""
    pd = fc.patch_digest(repo, base_sha, head_sha, repo_slug=REPO_SLUG)
    scope = fp.ReviewScope(mode=fp.REVIEW_SCOPE_WHOLE_PATCH, covers_patch_digest=pd)
    candidate = fp.CandidateRecord(head_sha=head_sha, review_scope=scope, patch_digest=pd)
    seats = (_seat("codex:x:high", finding_ids=("f1",)),)
    findings = (_finding("f1"),)
    artifact = fp.ReviewProvenanceArtifact.build(
        repo=REPO_SLUG,
        base=fp.BaseBinding(ref_identity=f"{REPO_SLUG}#main", base_sha=base_sha),
        boundary_manifest=fp.BoundaryManifestRef(path=".advisor-board/boundaries.toml", source_rev=base_sha, digest="d" * 64),
        candidate=candidate,
        seats=seats,
        findings=findings,
    )
    fp.write_provenance(repo, run_id, artifact)
    for seat in seats:
        fg.append_seat_outcome(repo, run_id, _durable_from_seat(seat))
    # Piece 2: the harness-only durable round record the full merge-time re-gate
    # now requires (expected-seat manifest + round identity + canonical findings).
    fg.write_expected_seats(
        repo, run_id, epoch=1,
        expected_seats=tuple(
            fg.ExpectedSeat(seat_instance_id=s.seat_instance_id, seat_key=s.seat_key,
                            vendor_leg=s.vendor_leg, required=s.required)
            for s in seats
        ),
    )
    fg.finalize_review_round(
        repo, run_id, reviewed_head_sha=head_sha,
        reviewed_material_digest=artifact.candidate.review_scope.reviewed_material_digest,
        canonical_findings=tuple(
            fg.CanonicalFinding(finding_id=f.id, severity=f.severity, status=f.status, body_digest=f.body_ref)
            for f in findings
        ),
    )


def _reviewed_pr(repo: Path, run_id: str) -> tuple[str, str]:
    """Build a `main` (base) + `pr1` (head) history, persist FAB provenance
    reviewed at exactly this base/head, and leave `pr1` checked out."""
    _write(repo, "a.py", "hello\n")
    base = _commit(repo, "c0")
    _push_main(repo)
    _git(repo, "checkout", "-qb", "pr1")
    _write(repo, "a.py", "hello world\n")
    head = _commit(repo, "c1 on pr1")
    _persist_provenance(repo, run_id, base_sha=base, head_sha=head)
    return base, head


def _make_gh_fake(*, base_ref: str, head, merged_sha: str = "sha-realmerge", calls: Optional[list] = None):
    """Fake ``gh`` responses (real ``git`` calls pass through unmocked — the
    FAB equivalence recompute needs a REAL repo, per the Lane B/D test
    convention: 'no mocked git for the core equivalence recompute')."""
    state = {"merged": False}

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "git":
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)
        if calls is not None:
            calls.append(cmd)
        # FAB merge-queue prohibition (2d) probes branch rules via `gh api`;
        # default fixture: no merge queue (empty rules list) → merge proceeds.
        if cmd[:2] == ["gh", "api"]:
            return _FakeCompletedProcess(returncode=0, stdout="[]")
        label = _gh_subcommand(cmd)
        if label == "view-merged-sha":
            if not state["merged"]:
                return _FakeCompletedProcess(returncode=0, stdout=_merged_sha_json("OPEN", base_ref))
            return _FakeCompletedProcess(
                returncode=0, stdout=_merged_sha_json("MERGED", base_ref, sha=merged_sha, head=head)
            )
        if label == "view-premerge":
            if head is None:
                # Simulate an unresolvable live head: the combined pre-merge
                # `gh pr view` omits headRefOid entirely.
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"isDraft": False, "baseRefName": base_ref}))
            return _FakeCompletedProcess(returncode=0, stdout=_premerge_json(False, base_ref, head=head))
        if label == "merge":
            state["merged"] = True
            return _FakeCompletedProcess(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected gh call reached fake_run: {cmd!r}")

    return fake_run


def _clock_seq(values):
    """A `_clock` seam returning successive `values` (last repeats) — drives the
    merge-queue poll's deadline deterministically without real time."""
    box = {"i": 0}

    def _clock():
        i = box["i"]
        box["i"] = min(i + 1, len(values) - 1)
        return values[i]

    return _clock


def _make_queue_gh_fake(
    *, base_ref: str, head, merged_sha: str = "sha-queuemerge",
    merges_after: int = 1, closes: bool = False, kicked: bool = False,
    auto_merge: bool = False, dequeue_ok: bool = True, disable_auto_ok: bool = True,
    merge_during_dequeue: bool = False, membership_unreadable: bool = False,
    enqueue_after: int = 0, race_merge_at: int = 0, merged_head: Optional[str] = None,
    calls: Optional[list] = None,
):
    """Fake `gh` simulating a merge QUEUE with MEMBERSHIP (#265 CR round 1). Models the
    queue-entry (`isInMergeQueue`) + auto-merge dimensions SEPARATELY from PR `state`,
    which is what the round-1 blockers require:
      * default: enqueue → in-queue → after `merges_after` poll iterations, MERGED.
      * `closes` → CLOSED without merge.
      * `kicked` → OPEN, NO queue entry, NO auto-merge (merge-group check failed) →
        the poll must EARLY-BREAK, not hang.
      * `auto_merge` → a pending autoMergeRequest (in flight; re-queues).
      * `dequeue_ok` False / `merge_during_dequeue` → drive the timeout ladder.
      * `membership_unreadable` → `isInMergeQueue` null (caller stays conservative).
    The terminal binding is head/base IDENTITY (gh JSON only), so no git advance is
    needed. Real `git` still passes through for the PREVENTIVE pre-enqueue re-gate."""
    st = {"iter": 0, "state": "OPEN", "in_queue": True, "auto_merge": auto_merge,
          "merged": False, "dequeued": False}

    def fake(cmd, **kwargs):
        if cmd and cmd[0] == "git":
            return _REAL_SUBPROCESS_RUN(cmd, **kwargs)
        if calls is not None:
            calls.append(cmd)
        joined = " ".join(cmd)
        label = _gh_subcommand(cmd)
        if label == "view-premerge":
            return _FakeCompletedProcess(returncode=0, stdout=_premerge_json(False, base_ref, head=head))
        if "--disable-auto" in cmd:  # dequeue's auto-merge cancel
            if disable_auto_ok:
                st["auto_merge"] = False
            return _FakeCompletedProcess(returncode=0, stdout="", stderr="")
        if label == "merge":
            return _FakeCompletedProcess(returncode=0, stdout="", stderr="")  # ENQUEUE (not merged)
        if label == "view-merged-sha":
            if st["merged"]:
                return _FakeCompletedProcess(
                    returncode=0,
                    stdout=_merged_sha_json("MERGED", base_ref, sha=merged_sha, head=(merged_head or head)))
            return _FakeCompletedProcess(returncode=0, stdout=_merged_sha_json("OPEN", base_ref, head=head))
        # _live_pr_queue_status step 1: gh pr view --json number,state,autoMergeRequest
        if cmd[:3] == ["gh", "pr", "view"] and "autoMergeRequest" in joined:
            st["iter"] += 1  # each poll iteration advances the lifecycle
            if closes:
                st["state"] = "CLOSED"
            elif kicked:
                # Model the real TRANSITION: in the queue on poll 1 (so the poll latches
                # "seen live"), then KICKED (removed, no auto-merge) on poll 2+ — proving
                # the early-break fires on a True→False transition, not an instant-False
                # (which the seen-live latch would correctly ignore as not-yet-enqueued).
                st["state"], st["auto_merge"] = "OPEN", False
                st["in_queue"] = st["iter"] < 2
            elif race_merge_at and st["iter"] == race_merge_at:
                # NON-ATOMIC read race (Blocker 1): this poll's STATE read is stale-OPEN,
                # then the merge lands right after it — so the subsequent isInMergeQueue
                # + terminal reads observe MERGED / not-in-queue. Returns OPEN here; flips
                # merged AFTER, so `_live_pr_queue_status` sees {OPEN, in_queue False}.
                resp = _FakeCompletedProcess(returncode=0, stdout=json.dumps(
                    {"number": 123, "state": "OPEN", "autoMergeRequest": None}))
                st["merged"], st["state"], st["in_queue"] = True, "MERGED", False
                return resp
            elif st["iter"] > merges_after:
                st["merged"], st["state"] = True, "MERGED"
            else:
                # In-queue once past the enqueue-propagation window, UNLESS a dequeue
                # removed the entry (which must stick through the confirm).
                st["in_queue"] = (st["iter"] > enqueue_after) and not st["dequeued"]
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps(
                {"number": 123, "state": st["state"],
                 "autoMergeRequest": {"enabledAt": "t"} if st["auto_merge"] else None}))
        # _live_pr_queue_status step 2: GraphQL isInMergeQueue
        if cmd[:2] == ["gh", "api"] and "isInMergeQueue" in joined:
            val = None if membership_unreadable else st["in_queue"]
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps(
                {"data": {"repository": {"pullRequest": {"isInMergeQueue": val}}}}))
        if cmd[:3] == ["gh", "pr", "view"] and "id" in joined:  # _dequeue_pr: PR node id
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"id": "PR_node_1"}))
        if cmd[:2] == ["gh", "api"] and "dequeuePullRequest" in joined:  # dequeue mutation
            if merge_during_dequeue:  # the PR merges DURING the dequeue call → mutation fails
                st["merged"], st["state"] = True, "MERGED"
                return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"errors": [{"message": "not queued"}]}))
            if dequeue_ok:
                st["dequeued"] = True  # removed from queue (sticks through the confirm poll)
                return _FakeCompletedProcess(
                    returncode=0, stdout=json.dumps({"data": {"dequeuePullRequest": {"clientMutationId": None}}}))
            # zero exit but a GraphQL error → NOT confirmed (fail-open guard)
            return _FakeCompletedProcess(returncode=0, stdout=json.dumps({"errors": [{"message": "boom"}]}))
        raise AssertionError(f"unexpected gh call reached queue fake: {cmd!r}")

    return fake


def _git_available():
    if _GIT is None:  # pragma: no cover - CI always has git
        pytest.skip("git not available")


# --------------------------------------------------------------------------- #
# N1 — byte-neutrality: the default (flag-off) path never calls equivalent()
# --------------------------------------------------------------------------- #


class TestByteNeutralDefault:
    def test_default_train_review_never_calls_equivalent(self, monkeypatch):
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)

        def _boom(*a, **kw):
            raise AssertionError("fab_canonical.equivalent must NOT be called on the byte-neutral default path")

        with patch("phase_loop_runtime.fab_canonical.equivalent", side_effect=_boom):
            result = _default_train_review("irrelevant bundle text", "autonomous")

        assert result.mergeable is True
        assert result.ran is False
        assert result.reason == "autonomous"

    def test_governed_premerge_for_run_never_calls_equivalent(self, monkeypatch):
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)

        def _boom(*a, **kw):
            raise AssertionError("fab_canonical.equivalent must NOT be called on the byte-neutral default path")

        with patch("phase_loop_runtime.fab_canonical.equivalent", side_effect=_boom):
            result = runner_mod.governed_premerge_for_run(
                artifact="x", author_executor="codex", run_mode="autonomous"
            )

        assert result.mergeable is True
        assert result.ran is False

    def test_governed_premerge_for_run_default_fab_promotion_check_is_none(self):
        """The new kwarg's default is None — the exact byte-neutral sentinel
        `run_governed_premerge_loop` already branches on."""
        import inspect

        sig = inspect.signature(runner_mod.governed_premerge_for_run)
        assert sig.parameters["fab_promotion_check"].default is None


# --------------------------------------------------------------------------- #
# N2 — byte-neutrality at the P4 merge-loop threading layer
# --------------------------------------------------------------------------- #


class TestP4LoopThreadingNeutral:
    @pytest.mark.parametrize("fab_flag", [None, "1"])
    def test_no_run_id_kwarg_leaks_to_merge_pr_fn(self, tmp_path: Path, monkeypatch, fab_flag):
        """A strict 4-arg `_merge_pr_fn` stub (the shape every pre-existing
        test_train_merge.py stub already uses) must never see a `run_id`
        kwarg — true regardless of PHASE_LOOP_FAB, since no producer
        populates `completed_nodes[node_id]["fab_run_id"]` yet."""
        if fab_flag is None:
            monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)
        else:
            monkeypatch.setenv(gp.FAB_PROMOTION_ENV, fab_flag)

        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = _setup_p3_done(tmp_path, roadmap, ws_map)
        merge_order: List[str] = []

        result = run_train(
            roadmap,
            ledger,
            run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub({}),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true,
            _live_pr_head_sha_fn=lambda ws, br: None,
            _merge_phase_enabled=True,
            _merge_pr_fn=_make_merge_pr_stub(merge_order),  # strict 4-arg signature
            _reverify_fn=_reverify_pass,
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
        )

        assert result["status"] == "merged"
        assert merge_order == ["repo-a", "repo-b"]


# --------------------------------------------------------------------------- #
# P1-P6 — _live_merge_pr's design §4.4 promotion re-assertion
# --------------------------------------------------------------------------- #


class TestLiveMergePrFabPromotion:
    def test_flag_on_no_run_id_is_inert(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-p1")

        def _boom(*a, **kw):
            raise AssertionError("equivalent() must not be called when run_id is None")

        with patch("phase_loop_runtime.fab_canonical.equivalent", side_effect=_boom):
            fake = _make_gh_fake(base_ref="main", head=head)
            with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
                sha = _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id=None, fab_fetch_origin="fetchsrc"
                )
        assert sha == "sha-realmerge"

    def test_flag_on_run_id_scoped_missing_provenance_fails_closed(self, tmp_path: Path, monkeypatch):
        """FIX (agent-harness#191 CR, REAL fail-open): a trusted `run_id` is
        present (FAB-scoped) but no provenance was ever recorded for it —
        `fab_gate.read_provenance` raises `ProvenanceNotFound`. Pre-fix this
        was treated as inert ("never scoped to FAB") and the merge proceeded;
        that CONTRADICTS `fab_gate.py`'s own fail-closed contract
        (`fab_gate_validator` ~line 1014: run_id present + ProvenanceNotFound
        -> BLOCK). Post-fix this must REFUSE the merge, and `gh pr merge`
        must never be invoked."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _write(repo, "a.py", "hello\n")
        base = _commit(repo, "c0")
        _push_main(repo)
        _git(repo, "checkout", "-qb", "pr1")
        _write(repo, "a.py", "hello world\n")
        head = _commit(repo, "c1")
        # Deliberately never persist provenance for this run_id.

        calls: list = []
        fake = _make_gh_fake(base_ref="main", head=head, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="fab-promotion-reassertion-unresolvable"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head,
                    run_id="run-never-persisted", fab_fetch_origin="fetchsrc",
                )
        merge_calls = [c for c in calls if _gh_subcommand(c) == "merge"]
        assert merge_calls == [], (
            "gh pr merge must never be invoked when a trusted run_id's provenance is missing/unreadable"
        )

    def test_flag_on_run_id_unreadable_provenance_fails_closed(self, tmp_path: Path, monkeypatch):
        """P2b: the provenance artifact EXISTS on disk but is corrupt/
        unreadable (malformed JSON -> `fab_provenance.ProvenanceInvalid`, a
        DIFFERENT exception than `ProvenanceNotFound`). Pre-fix this
        exception was not caught at all by
        `_fab_promotion_gate_before_merge` (only `ProvenanceNotFound` was
        handled) and would propagate as an unhandled crash instead of a
        controlled fail-closed refusal. Post-fix this must also REFUSE the
        merge cleanly, and `gh pr merge` must never be invoked."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _write(repo, "a.py", "hello\n")
        base = _commit(repo, "c0")
        _push_main(repo)
        _git(repo, "checkout", "-qb", "pr1")
        _write(repo, "a.py", "hello world\n")
        head = _commit(repo, "c1")

        run_id = "run-corrupt-provenance"
        prov_path = fp.provenance_path_for_run(repo, run_id)
        prov_path.parent.mkdir(parents=True, exist_ok=True)
        prov_path.write_text("{not valid json!!", encoding="utf-8")

        calls: list = []
        fake = _make_gh_fake(base_ref="main", head=head, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="fab-promotion-reassertion-unresolvable"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head,
                    run_id=run_id, fab_fetch_origin="fetchsrc",
                )
        merge_calls = [c for c in calls if _gh_subcommand(c) == "merge"]
        assert merge_calls == [], (
            "gh pr merge must never be invoked when a trusted run_id's provenance is unreadable/corrupt"
        )

    def test_flag_on_provenance_exists_unchanged_merges(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-p3")

        fake = _make_gh_fake(base_ref="main", head=head)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id="run-p3", fab_fetch_origin="fetchsrc"
            )
        assert sha == "sha-realmerge"

    def test_flag_on_content_drift_refuses_merge(self, tmp_path: Path, monkeypatch):
        """design §4.4 residual closure (§4.2): the board reviewed `head`, but
        a LATER commit landed on the same branch post-review — the broker
        re-admitted it (so the EXISTING head-advance guard sees a consistent
        admitted/live head and does not itself catch this), yet the content
        no longer matches what FAB actually reviewed. Only the promotion
        re-assertion catches this."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, reviewed_head = _reviewed_pr(repo, "run-p4")
        _write(repo, "a.py", "hello world -- resolved differently, post-review\n")
        drifted_head = _commit(repo, "c2 not part of the reviewed head")

        calls: list = []
        fake = _make_gh_fake(base_ref="main", head=drifted_head, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            # Piece 2 (2c): the merge-time re-assertion now runs the FULL hard
            # gate; content drift surfaces as a review_gate_block with the
            # content_drift equivalence reason.
            with pytest.raises(RuntimeError, match=r"fab-promotion-reassertion-failed.*content_drift.*design §4\.4"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=drifted_head,
                    run_id="run-p4", fab_fetch_origin="fetchsrc",
                )
        merge_calls = [c for c in calls if _gh_subcommand(c) == "merge"]
        assert merge_calls == [], "gh pr merge must never be invoked when the FAB re-assertion refuses"

    def test_flag_on_unresolvable_live_head_fails_closed(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-p5")

        calls: list = []
        # head=None -> the combined pre-merge `gh pr view` response omits
        # headRefOid; head_sha is also omitted so the pre-existing
        # head-advance guard (`if head_sha and current_head ...`) does not
        # itself intercept this before the FAB check is reached.
        fake = _make_gh_fake(base_ref="main", head=None, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="fab-promotion-reassertion-unresolvable"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=None,
                    run_id="run-p5", fab_fetch_origin="fetchsrc",
                )
        merge_calls = [c for c in calls if _gh_subcommand(c) == "merge"]
        assert merge_calls == [], "gh pr merge must never be invoked when live identity is unresolvable"

    def test_flag_off_stays_inert_even_with_drifted_provenance(self, tmp_path: Path, monkeypatch):
        """The opt-in flag gates EVERYTHING: even a run_id whose provenance
        would fail the live re-check must not be looked at while
        PHASE_LOOP_FAB is off."""
        _git_available()
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)
        repo = _make_fab_repo(tmp_path)
        _base, reviewed_head = _reviewed_pr(repo, "run-p6")
        _write(repo, "a.py", "drift while the flag is off\n")
        drifted_head = _commit(repo, "c2 drift, flag off")

        def _boom(*a, **kw):
            raise AssertionError("equivalent() must not be called while PHASE_LOOP_FAB is off")

        with patch("phase_loop_runtime.fab_canonical.equivalent", side_effect=_boom):
            fake = _make_gh_fake(base_ref="main", head=drifted_head)
            with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
                sha = _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=drifted_head,
                    run_id="run-p6", fab_fetch_origin="fetchsrc",
                )
        assert sha == "sha-realmerge"

    def test_fab_queue_enqueue_polls_to_terminal_and_records(self, tmp_path: Path, monkeypatch):
        """#265 (replaces piece-2's prohibition): FAB on + a merge QUEUE — the PR is
        ENQUEUED (still OPEN), the queue-bound wait POLLS to the terminal MERGED
        commit, re-gates against it, and RETURNS that SHA (the caller records it).
        The prohibition is gone: `gh pr merge` IS now issued (no `fab-merge-queue-
        prohibited` refusal)."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq")

        calls: list = []
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=1, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq", fab_fetch_origin="fetchsrc",
                _clock=lambda: 0.0, _sleep=lambda _s: None,  # no real time; never hits the deadline
            )
        assert sha == "sha-queuemerge"
        assert [c for c in calls if _gh_subcommand(c) == "merge"], "the merge (enqueue) must be issued — prohibition removed"

    def test_fab_queue_rewritten_head_fails_closed(self, tmp_path: Path, monkeypatch):
        """#265 detective binding + known limitation: the terminal re-assertion is
        head/base IDENTITY (via `_live_pr_merged_sha`). A queue that REWRITES the head
        (e.g. a rebase-style merge queue) produces a `headRefOid` != the pinned
        admitted head → `pr-merged-wrong-head` fail-closed. Merge/squash queues (which
        preserve the head) are supported; a rebase queue fails closed (safe), not
        silently accepted."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-rebase")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merged_head="sha-rebased-by-queue")
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="pr-merged-wrong-head"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-rebase",
                    fab_fetch_origin="fetchsrc", _clock=lambda: 0.0, _sleep=lambda _s: None,
                )

    def test_fab_queue_closed_without_merge_blocks(self, tmp_path: Path, monkeypatch):
        """#265 fail-closed: an enqueued PR that goes CLOSED without merging (dequeued
        upstream) blocks — no merge recorded."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-closed")
        fake = _make_queue_gh_fake(base_ref="main", head=head, closes=True)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="merge-queue-dequeued"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-closed",
                    fab_fetch_origin="fetchsrc", _clock=lambda: 0.0, _sleep=lambda _s: None,
                )

    def test_fab_queue_kicked_open_early_blocks_no_hang(self, tmp_path: Path, monkeypatch):
        """#265 CR round 1 Blocker A-ii: a PR KICKED from the queue (merge-group check
        failed) stays state=OPEN with NO queue entry and NO auto-merge. The poll must
        read MEMBERSHIP and EARLY-BREAK (clean block) NOW — not hang for the full
        timeout. Uses a never-timeout clock (0.0) to prove the break is membership-
        driven, not the deadline."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-kick")
        fake = _make_queue_gh_fake(base_ref="main", head=head, kicked=True)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="merge-queue-removed"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-kick",
                    fab_fetch_origin="fetchsrc", _clock=lambda: 0.0, _sleep=lambda _s: None,
                )

    def test_fab_queue_merge_between_nonatomic_reads_is_recorded(self, tmp_path: Path, monkeypatch):
        """#265 CR round 2 Blocker 1: `_live_pr_queue_status` reads `state` and
        `isInMergeQueue` in TWO calls. If the merge lands BETWEEN them, the poll sees
        {state: OPEN (stale), in_queue: False} with seen_live latched — the naive
        early-break would false-`merge-queue-removed` a MERGED PR ('safe to retry').
        The reconcile terminal re-read must catch it and RECORD the SHA instead."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-race2")
        # iter 1 → in queue (seen_live); iter 2 → merge lands between the state and
        # membership reads (stale-OPEN + in_queue False).
        fake = _make_queue_gh_fake(base_ref="main", head=head, race_merge_at=2)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-race2",
                fab_fetch_origin="fetchsrc", _clock=lambda: 0.0, _sleep=lambda _s: None,
            )
        assert sha == "sha-queuemerge", "a merge racing the non-atomic reads must be RECORDED, not false-removed"

    def test_fab_queue_graphql_pinned_to_broker_host_not_ambient_gh_host(self, tmp_path: Path, monkeypatch):
        """#265 CR round 2 Blocker 2: `gh api graphql` takes no `--repo` and resolves
        its host from GH_HOST — so an ambient GH_HOST could redirect the membership
        read / dequeue mutation to a DIFFERENT host than the `gh pr view --repo
        github.com/...` REST calls. Both GraphQL calls MUST pin `--hostname` to the
        broker-validated host, regardless of a conflicting GH_HOST."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        monkeypatch.setenv("GH_HOST", "evil.example.com")  # conflicting ambient host
        repo = _make_fab_repo(tmp_path)  # origin → github.com/testorg/testrepo
        _base, head = _reviewed_pr(repo, "run-mq-host")
        calls: list = []
        # merges_after high + timeout → drives the dequeue graphql too; membership polls run.
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999, dequeue_ok=True, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError):  # times out → dequeue ladder; we assert the host binding
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-host",
                    fab_fetch_origin="fetchsrc", _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
                )
        graphql_calls = [c for c in calls if c[:2] == ["gh", "api"] and "graphql" in " ".join(c)]
        assert graphql_calls, "the queue path must issue GraphQL calls"
        for c in graphql_calls:
            assert "--hostname" in c and c[c.index("--hostname") + 1] == "github.com", (
                f"every GraphQL call must pin the broker host, not the ambient GH_HOST: {c!r}"
            )

    def test_fab_queue_not_yet_enqueued_window_does_not_false_block(self, tmp_path: Path, monkeypatch):
        """#265 CR round 1 (advisor): the enqueue-propagation window right after
        `gh pr merge` — OPEN, `isInMergeQueue` not visible yet, no auto-merge — must
        NOT trigger the `merge-queue-removed` early-break (that would false-block EVERY
        queue merge whose entry propagates slower than the first poll). The seen-live
        latch: never-seen-live → keep polling; the entry then appears → merges."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-window")
        # Poll 1: not yet in queue (window). Poll 2+: in queue. Merges after poll 2.
        fake = _make_queue_gh_fake(base_ref="main", head=head, enqueue_after=1, merges_after=2)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-window",
                fab_fetch_origin="fetchsrc", _clock=lambda: 0.0, _sleep=lambda _s: None,
            )
        assert sha == "sha-queuemerge", "the not-yet-enqueued window must NOT early-block; it merges once queued"

    def test_fab_queue_surviving_auto_merge_is_not_confirmed_dequeued(self, tmp_path: Path, monkeypatch):
        """#265 CR round 1 Blocker A-i: dequeue that removes the queue entry but leaves
        a surviving auto-merge request must NOT read as cancelled — a live merge intent
        remains. Confirmation requires BOTH no-entry AND no-auto-merge; a surviving
        auto-merge → the loud unreconciled halt, never a false timeout-dequeued."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-auto")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999,
                                   auto_merge=True, dequeue_ok=True, disable_auto_ok=False)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="merge-queue-unreconciled"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-auto",
                    fab_fetch_origin="fetchsrc", _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
                )

    def test_fab_queue_unreadable_membership_does_not_early_break(self, tmp_path: Path, monkeypatch):
        """#265 CR round 1: UNREADABLE membership (`isInMergeQueue` null) must NOT be
        read as 'not queued' — the poll keeps going (no false early-break) and, at the
        timeout, an unconfirmable dequeue → unreconciled (fail-closed on ambiguity)."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-unreadable")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999, membership_unreadable=True)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="merge-queue-unreconciled"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-unreadable",
                    fab_fetch_origin="fetchsrc", _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
                )

    def test_fab_queue_merge_during_dequeue_is_recorded_not_halted(self, tmp_path: Path, monkeypatch):
        """#265 CR round 1 Blocker B: if the PR MERGES during the (now-failing) dequeue
        call at the timeout boundary, the post-dequeue terminal re-read RECORDS it —
        a merged PR must never be LOST to a false unreconciled halt."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-race")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999, merge_during_dequeue=True)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-race",
                fab_fetch_origin="fetchsrc", _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
            )
        assert sha == "sha-queuemerge"

    def test_fab_queue_timeout_dequeue_confirmed_blocks(self, tmp_path: Path, monkeypatch):
        """#265 risk-1: the queue never terminalizes within the bound; on timeout the
        dequeue is CONFIRMED → a clean (retryable) block, not the loud halt."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-to")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999, dequeue_ok=True)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="merge-queue-timeout-dequeued"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-to",
                    fab_fetch_origin="fetchsrc", queue_poll_timeout_s=1800.0,
                    _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
                )

    def test_fab_queue_timeout_but_already_merged_records_not_blocks(self, tmp_path: Path, monkeypatch):
        """#265 risk-1 (do NOT block a merge that happened): the deadline passes, but
        the re-read-terminal-FIRST shows the queue already MERGED → return + record it,
        never a spurious block."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-race")
        # merges_after=1 → after the first state poll, the timeout re-read observes MERGED.
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=1)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-race",
                fab_fetch_origin="fetchsrc", _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
            )
        assert sha == "sha-queuemerge"

    def test_fab_queue_unreconcilable_halts_loud(self, tmp_path: Path, monkeypatch):
        """#265 risk-1 crux: the queue never terminalizes AND the dequeue cannot be
        confirmed → the loud `merge-queue-unreconciled` block (a scheduled mutation we
        can neither observe nor cancel — the train halts for operator reconciliation)."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-unrec")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999, dequeue_ok=False)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="merge-queue-unreconciled"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id="run-mq-unrec",
                    fab_fetch_origin="fetchsrc", _clock=_clock_seq([0.0, 10_000.0]), _sleep=lambda _s: None,
                )

    def test_flag_off_resume_with_stale_run_id_is_byte_neutral(self, tmp_path: Path, monkeypatch):
        """#265 CR round 3: a flag-OFF RESUME of a node whose ledger persisted a
        `fab_run_id` (from a prior flag-ON admission) must behave EXACTLY like a
        non-FAB node — `--delete-branch` KEPT, and the enqueue raises the byte-neutral
        'could not determine merge commit SHA' fail-closed. FAB stays DORMANT: no queue
        wait, no recorded queue SHA. Gating the FAB path on `run_id is None` (not the
        CURRENT flag) would half-activate FAB here (drop --delete-branch + track the
        queue while the re-gate is inert) — the byte-neutrality regression this closes."""
        _git_available()
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)  # flag OFF now
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-stale")  # provenance persisted, but flag is OFF
        calls: list = []
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999, calls=calls)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="could not determine merge commit SHA"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head,
                    run_id="run-stale",  # STALE persisted run_id restored on a flag-off resume
                    fab_fetch_origin="fetchsrc", _clock=lambda: 0.0, _sleep=lambda _s: None,
                )
        merge_calls = [c for c in calls if _gh_subcommand(c) == "merge"]
        assert merge_calls and "--delete-branch" in merge_calls[0], (
            "a flag-off resume with a stale run_id must KEEP --delete-branch (byte-neutral vs non-FAB main)"
        )
        assert not any("isInMergeQueue" in " ".join(c) for c in calls), (
            "the FAB queue wait must NOT run when the flag is off — FAB stays dormant"
        )

    def test_non_fab_queue_node_is_byte_neutral_fail_closed(self, tmp_path: Path, monkeypatch):
        """Byte-neutral: a NON-FAB node (`run_id=None`) whose merge ENQUEUES (never
        synchronously MERGED) hits main's UNCHANGED fail-closed raise — the queue-bound
        wait is a FAB-only capability (it needs the FAB re-gate), so off the FAB path
        nothing changes."""
        _git_available()
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-nonfab")
        fake = _make_queue_gh_fake(base_ref="main", head=head, merges_after=999)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            with pytest.raises(RuntimeError, match="could not determine merge commit SHA"):
                _live_merge_pr(
                    repo, "feat/pr1", base="main", head_sha=head, run_id=None, fab_fetch_origin="fetchsrc",
                )

    def test_repo_slug_owner_repo_extraction(self):
        from phase_loop_runtime import train_runner as tr

        assert tr._repo_slug_owner_repo(["--repo", "github.com/testorg/testrepo"]) == "testorg/testrepo"
        assert tr._repo_slug_owner_repo(["--repo", "testorg/testrepo"]) == "testorg/testrepo"
        assert tr._repo_slug_owner_repo([]) is None

    def test_flag_off_no_merge_queue_gh_api(self, tmp_path: Path, monkeypatch):
        """Byte-neutral: with the flag OFF, a synchronous merge issues NO `gh api`
        call at all (#265 removed piece-2's pre-merge rules probe; the FAB queue path
        + its dequeue GraphQL never run off the FAB path) and the merge proceeds."""
        _git_available()
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-off")

        base_fake = _make_gh_fake(base_ref="main", head=head)

        def fake(cmd, **kwargs):
            if cmd[:2] == ["gh", "api"]:
                raise AssertionError("no `gh api` call may run on the byte-neutral flag-off merge path")
            return base_fake(cmd, **kwargs)

        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            sha = _live_merge_pr(
                repo, "feat/pr1", base="main", head_sha=head, run_id=None, fab_fetch_origin="fetchsrc"
            )
        assert sha == "sha-realmerge"


# =========================================================================== #
# PIECE 3a — the durable admission bridge (Consiliency/agent-harness#191).
#
# Piece 3a binds the trusted `fab_run_id` at ADMISSION time (the same append
# that records the admitted head) into the durable train ledger, which ACTIVATES
# piece 1's previously-inert merge-time re-gate. Coverage:
#   A1-A5  `_resolve_admission_fab_run_id` fail-closed matrix (unit).
#   A6     fresh admission binds fab_run_id in the ledger AND threads it to the
#          merge fn (the re-gate now runs for FAB-admitted nodes).
#   A7     BYTE-NEUTRAL off: flag off ⇒ no fab_run_id bound even if a snapshot
#          leaks one; the ledger record is unchanged and no run_id threads.
#   A8     RESUME: the fab_run_id bound at first admission is recovered from the
#          durable ledger (the only source on resume) and threaded to the merge.
#   A9     admission head-mismatch ⇒ node BLOCKS (fail-closed), no merge.
#   A10/11 end-to-end through run_train with the REAL `_live_merge_pr`: the
#          re-gate fires for an admitted node — passes a legit gated head,
#          fail-closes on tampered provenance.
# =========================================================================== #

from types import SimpleNamespace  # noqa: E402

from phase_loop_runtime.train_ledger import LedgerRecord, append_record, read_ledger  # noqa: E402
from phase_loop_runtime.train_runner import _resolve_admission_fab_run_id  # noqa: E402

from test_train_merge import _pr_is_open_true as _p3a_pr_open  # noqa: E402


def _make_fab_repo_at(path: Path, tmp_path: Path) -> Path:
    """A real git repo (with the origin=github-shaped / fetchsrc=real-bare two
    remotes) at an EXPLICIT path, so a train node's workspace is a genuine FAB
    repo (`_make_fab_repo` hardcodes `tmp_path/'work'`)."""
    fetchsrc = tmp_path / f"{path.name}-fetchsrc.git"
    _REAL_SUBPROCESS_RUN(["git", "init", "-q", "--bare", str(fetchsrc)], check=True)
    path.mkdir(parents=True, exist_ok=True)
    _REAL_SUBPROCESS_RUN(["git", "init", "-q", str(path)], check=True)
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "remote", "add", "origin", "git@github.com:testorg/testrepo.git")
    _git(path, "remote", "add", "fetchsrc", str(fetchsrc))
    return path


def _capturing_merge_stub(captured: dict):
    """A merge fn that ACCEPTS the FAB `run_id` kwarg (unlike the strict 4-arg
    `_make_merge_pr_stub`) and records it per workspace, so a test can assert
    exactly which run_id the admission bridge threaded to the merge."""
    def _merge_pr(workspace, branch, base="main", head_sha=None, run_id=None, fab_fetch_origin="origin"):
        captured[Path(workspace).name] = run_id
        return f"sha-merged-{Path(workspace).name}"
    return _merge_pr


def _plumbing_snapshot(fab_run_id):
    """A minimal run_loop snapshot carrying the producer's plumbed fab_run_id in
    its closeout summary (no `phases` ⇒ the green-state guard is skipped)."""
    return SimpleNamespace(
        closeout_summary={"fab_run_id": fab_run_id},
        phase_owned_dirty_paths=(),
        dirty_paths=(),
    )


class TestPiece3aResolveAdmissionFabRunId:
    """A1-A5 — the admission resolver's fail-closed matrix (unit)."""

    def test_binds_on_head_match(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-a1")
        assert _resolve_admission_fab_run_id(repo, head, "run-a1") == ("run-a1", None)

    def test_head_mismatch_fails_closed(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, _head = _reviewed_pr(repo, "run-a2")
        bound, reason = _resolve_admission_fab_run_id(repo, "sha-not-the-reviewed-head", "run-a2")
        assert bound is None
        assert reason is not None and "fab-admission-head-mismatch" in reason

    def test_missing_provenance_fails_closed(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        bound, reason = _resolve_admission_fab_run_id(repo, "sha-whatever", "run-absent")
        assert bound is None
        assert reason is not None and "fab-admission-provenance-missing" in reason

    def test_unreadable_provenance_fails_closed(self, tmp_path: Path, monkeypatch):
        """grok 3a follow-up: a plumbed run_id whose provenance is PRESENT but
        UNREADABLE/tampered (not merely absent) must fail CLOSED — a broken
        FAB-scoped artifact is never treated as 'non-FAB'."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        # A provenance file EXISTS at the run-store path but is corrupt JSON.
        path = fp.provenance_path_for_run(repo, "run-corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not valid provenance json", encoding="utf-8")
        bound, reason = _resolve_admission_fab_run_id(repo, "sha-whatever", "run-corrupt")
        assert bound is None
        assert reason is not None and "fab-admission-provenance-unreadable" in reason

    def test_flag_off_is_inert(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-a4")
        # A valid, matching run_id — but the flag is OFF, so nothing is bound.
        assert _resolve_admission_fab_run_id(repo, head, "run-a4") == (None, None)

    def test_no_plumbed_id_is_inert(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        assert _resolve_admission_fab_run_id(repo, "sha-x", None) == (None, None)


def _p3a_two_fab_nodes(tmp_path: Path):
    """Set up repo-a + repo-b as real FAB workspaces, each with a reviewed PR +
    persisted provenance. Returns (roadmap, ws_map, run_ids, heads)."""
    roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
    ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
    run_ids: dict = {}
    heads: dict = {}
    for node in roadmap.nodes:
        ws = ws_map[node.node_id]
        _make_fab_repo_at(ws, tmp_path)
        rid = f"run-{ws.name}"
        _base, head = _reviewed_pr(ws, rid)
        run_ids[str(ws)] = rid
        heads[str(ws)] = head
    return roadmap, ws_map, run_ids, heads


def _p3a_run_train(roadmap, ledger, ws_map, *, run_loop, publish, merge_fn):
    return run_train(
        roadmap,
        ledger,
        run_mode="governed",
        resolve_workspace=lambda n: ws_map[n.node_id],
        _run_loop=run_loop,
        _publish=publish,
        _set_upstream_ref_fn=lambda *a, **kw: [],
        _preflight_fn=_preflight_pass,
        _pr_is_open=_p3a_pr_open,
        _live_pr_head_sha_fn=lambda ws, br: None,
        _merge_phase_enabled=True,
        _merge_pr_fn=merge_fn,
        _reverify_fn=_reverify_pass,
        _train_review_fn=_approval_review_fn,
        _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
    )


class TestPiece3aAdmissionBridgeIntegration:
    def test_fresh_admission_binds_and_threads_run_id(self, tmp_path: Path, monkeypatch):
        """A6: a fresh FAB build binds the plumbed fab_run_id in the pr_open
        ledger record AND threads it to the merge fn — the re-gate now runs for
        FAB-admitted nodes."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        roadmap, ws_map, run_ids, heads = _p3a_two_fab_nodes(tmp_path)
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        publish = _make_publish_stub({
            str(ws): {"status": "published", "branch": f"feat/{ws.name}",
                      "head_sha": heads[str(ws)], "pr_url": f"https://gh/{ws.name}/1"}
            for ws in ws_map.values()
        })
        captured: dict = {}
        result = _p3a_run_train(
            roadmap, ledger, ws_map,
            run_loop=lambda ws, rm, **kw: (_plumbing_snapshot(run_ids[str(ws)]), []),
            publish=publish,
            merge_fn=_capturing_merge_stub(captured),
        )

        assert result["status"] == "merged", result
        # Threaded to the merge fn for BOTH admitted nodes.
        assert captured == {"repo-a": "run-repo-a", "repo-b": "run-repo-b"}
        # Durably bound in the pr_open ADMISSION records (the later `merged`
        # record legitimately drops it — the merge already ran; a resume would
        # skip a merged node, so the binding is only load-bearing on pr_open).
        pr_open = {
            (r["node_id"], r["fab_run_id"])
            for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()
            for r in [json.loads(line)] if r["status"] == "pr_open"
        }
        assert ("repo-a/specs/plan-a.md", "run-repo-a") in pr_open
        assert ("repo-b/specs/plan-b.md", "run-repo-b") in pr_open

    def test_flag_off_admission_is_byte_neutral(self, tmp_path: Path, monkeypatch):
        """A7: flag OFF ⇒ even a snapshot that leaks a fab_run_id binds NOTHING;
        the ledger record carries no fab_run_id key and no run_id threads."""
        _git_available()
        monkeypatch.delenv(gp.FAB_PROMOTION_ENV, raising=False)
        roadmap, ws_map, run_ids, heads = _p3a_two_fab_nodes(tmp_path)
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        publish = _make_publish_stub({
            str(ws): {"status": "published", "branch": f"feat/{ws.name}",
                      "head_sha": heads[str(ws)], "pr_url": f"https://gh/{ws.name}/1"}
            for ws in ws_map.values()
        })
        captured: dict = {}
        result = _p3a_run_train(
            roadmap, ledger, ws_map,
            run_loop=lambda ws, rm, **kw: (_plumbing_snapshot(run_ids[str(ws)]), []),
            publish=publish,
            merge_fn=_capturing_merge_stub(captured),
        )
        assert result["status"] == "merged", result
        assert captured == {"repo-a": None, "repo-b": None}
        state = read_ledger(ledger)
        # The optional field is absent → byte-identical to a pre-piece-3 record.
        assert state["repo-a/specs/plan-a.md"].fab_run_id is None
        raw = ledger.read_text(encoding="utf-8")
        assert "fab_run_id" not in raw

    def test_resume_recovers_fab_run_id_from_ledger(self, tmp_path: Path, monkeypatch):
        """A8: on RESUME there is no fresh snapshot — the fab_run_id bound at
        first admission is recovered from the durable ledger and threaded to the
        merge-time re-gate."""
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/repo-a",
            head_sha="sha-a", pr_url="https://gh/a/1", merge_order=0, fab_run_id="run-repo-a"))
        append_record(ledger, LedgerRecord(
            node_id="repo-b/specs/plan-b.md", status="pr_open", branch="feat/repo-b",
            head_sha="sha-b", pr_url="https://gh/b/1", merge_order=1, fab_run_id="run-repo-b"))

        captured: dict = {}
        result = _p3a_run_train(
            roadmap, ledger, ws_map,
            run_loop=lambda *a, **kw: (None, []),  # resume: run_loop is not invoked
            publish=_make_publish_stub({}),
            merge_fn=_capturing_merge_stub(captured),
        )
        assert result["status"] == "merged", result
        assert captured == {"repo-a": "run-repo-a", "repo-b": "run-repo-b"}

    def test_admission_head_mismatch_blocks_node(self, tmp_path: Path, monkeypatch):
        """A9: a plumbed run_id whose provenance candidate head != the admitted
        head is a torn/ambiguous admission → the node BLOCKS, no merge runs."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        roadmap, ws_map, run_ids, heads = _p3a_two_fab_nodes(tmp_path)
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"

        # repo-a publishes a head that does NOT match its provenance candidate.
        publish = _make_publish_stub({
            str(ws): {"status": "published", "branch": f"feat/{ws.name}",
                      "head_sha": ("sha-wrong-head" if ws.name == "repo-a" else heads[str(ws)]),
                      "pr_url": f"https://gh/{ws.name}/1"}
            for ws in ws_map.values()
        })
        captured: dict = {}
        result = _p3a_run_train(
            roadmap, ledger, ws_map,
            run_loop=lambda ws, rm, **kw: (_plumbing_snapshot(run_ids[str(ws)]), []),
            publish=publish,
            merge_fn=_capturing_merge_stub(captured),
        )
        assert result["status"] != "merged"
        assert "fab-admission-head-mismatch" in json.dumps(result, default=str)
        assert captured == {}, "no node may merge once admission fails closed"


class TestPiece3bRecoveryWiring:
    """Round 4 1a/1b — the FAB torn-state recovery / re-admission wiring in the P4
    merge loop."""

    def _resume_ledger(self, tmp_path):
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/repo-a",
            head_sha="sha-a", pr_url="https://gh/a/1", merge_order=0, fab_run_id="run-repo-a"))
        append_record(ledger, LedgerRecord(
            node_id="repo-b/specs/plan-b.md", status="pr_open", branch="feat/repo-b",
            head_sha="sha-b", pr_url="https://gh/b/1", merge_order=1, fab_run_id="run-repo-b"))
        return roadmap, ws_map, ledger

    def test_recovery_runs_for_fab_nodes_even_with_shortcut_disabled(self, tmp_path: Path, monkeypatch):
        """1b: the torn-state recovery runs before the merge re-gate for EVERY FAB
        node, INDEPENDENT of the delta-shortcut opt-in (OFF here) — otherwise a torn
        seat ledger from a crashed prior attempt would brick the STRICT merge re-gate
        forever even with the shortcut disabled. The re-gate runs regardless of
        opt-in, so recovery must too."""
        from phase_loop_runtime import train_runner as tr

        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        roadmap, ws_map, ledger = self._resume_ledger(tmp_path)

        recovered: list = []
        monkeypatch.setattr(
            tr, "_fab_recover_torn_to_admitted",
            lambda ws, run_id, *, admitted_head_sha: recovered.append(run_id),
        )
        captured: dict = {}
        result = _p3a_run_train(
            roadmap, ledger, ws_map,
            run_loop=lambda *a, **kw: (None, []),  # resume: run_loop not invoked
            publish=_make_publish_stub({}),
            merge_fn=_capturing_merge_stub(captured),
        )
        assert result["status"] == "merged", result
        assert set(recovered) == {"run-repo-a", "run-repo-b"}, recovered
        assert captured == {"repo-a": "run-repo-a", "repo-b": "run-repo-b"}

    def test_raise_in_fab_recovery_is_caught_as_merge_halted(self, tmp_path: Path, monkeypatch):
        """1a: a raise anywhere in the FAB recovery/re-admission is caught and
        ledgered as blocked / merge_halted — NEVER an uncaught traceback that aborts
        run_train (the shortcut sites live outside the merge-call try/except, so
        without this an exception here would violate run_train's no-uncaught-escape
        contract)."""
        from phase_loop_runtime import train_runner as tr

        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        roadmap, ws_map, ledger = self._resume_ledger(tmp_path)

        def boom(ws, run_id, *, admitted_head_sha):
            raise OSError("simulated FAB recovery failure")

        monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", boom)
        captured: dict = {}
        result = _p3a_run_train(
            roadmap, ledger, ws_map,
            run_loop=lambda *a, **kw: (None, []),
            publish=_make_publish_stub({}),
            merge_fn=_capturing_merge_stub(captured),
        )
        assert result["status"] == "merge_halted", result
        assert result["reason"] == "fab_readmit_failed", result
        assert captured == {}, "no node merges once FAB recovery fails closed"
        assert read_ledger(ledger)["repo-a/specs/plan-a.md"].status == "blocked"

    _SOLO_MD = (
        "# Release Train: solo\n\n## Nodes\n\n"
        "### Node: repo-a / specs/plan-a.md\n\n**Depends on:** (none)\n**Channel:** (none)\n"
    )

    def _run_with_advanced_head(self, tmp_path, monkeypatch, engaged):
        """Drive the merge loop for a SINGLE admitted FAB node whose live PR head has
        ADVANCED (live != admitted), with the coordinator opt-in ON, spying on
        `_fab_delta_readmit` so the ENGAGE decision is observable without running the
        real re-admission. A single node avoids the unrelated downstream
        upstream-changed guard a 2-node train would trip on an advanced upstream."""
        from phase_loop_runtime.train_runner import run_train
        from phase_loop_runtime import train_runner as tr

        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        roadmap = parse_train_roadmap(self._SOLO_MD)
        ws_map = {n.node_id: tmp_path / n.repo for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/repo-a",
            head_sha="sha-a", pr_url="https://gh/a/1", merge_order=0, fab_run_id="run-repo-a"))

        monkeypatch.setattr(tr, "_fab_recover_torn_to_admitted", lambda *a, **k: None)  # no-op safety net
        monkeypatch.setattr(
            tr, "_fab_delta_readmit",
            lambda *a, **k: (engaged.append(k.get("live_head_sha")), None)[1],
        )
        return run_train(
            roadmap, ledger, run_mode="governed",
            resolve_workspace=lambda n: ws_map[n.node_id],
            _run_loop=lambda *a, **kw: (None, []),
            _publish=_make_publish_stub({}),
            _set_upstream_ref_fn=lambda *a, **kw: [],
            _preflight_fn=_preflight_pass,
            _pr_is_open=_p3a_pr_open,
            _live_pr_head_sha_fn=lambda ws, br: f"advanced-{br}",  # live != admitted
            _merge_phase_enabled=True,
            _merge_pr_fn=_capturing_merge_stub({}),
            _reverify_fn=_reverify_pass,
            _train_review_fn=_approval_review_fn,
            _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            fab_delta_shortcut=True,  # coordinator opt-in ON
        )

    def test_interlock_off_fences_engage_in_the_merge_loop(self, tmp_path: Path, monkeypatch):
        """CR round 5 (operator interlock): with the #288 constant at its shipped
        default (False), an ADVANCED head + BOTH opt-ins on does NOT engage the
        shortcut — `_fab_delta_readmit` is never called; the advance is handled by the
        normal (unchanged) `pr-head-advanced` path. The broker gap is unreachable by
        construction."""
        monkeypatch.setattr("phase_loop_runtime.governed_premerge._FAB_DELTA_BROKER_READMIT_READY", False)
        engaged: list = []
        result = self._run_with_advanced_head(tmp_path, monkeypatch, engaged)
        assert engaged == [], "the ENGAGE path must be fenced off while _FAB_DELTA_BROKER_READMIT_READY is False"
        assert result["status"] == "merged", result


    def test_interlock_on_re_enables_engage(self, tmp_path: Path, monkeypatch):
        """Flipping the interlock True (as #288 will) re-enables ENGAGE — the clear
        switch + proof: `_fab_delta_readmit` IS invoked for the advanced head."""
        monkeypatch.setattr("phase_loop_runtime.governed_premerge._FAB_DELTA_BROKER_READMIT_READY", True)
        engaged: list = []
        self._run_with_advanced_head(tmp_path, monkeypatch, engaged)
        assert engaged and all(str(h).startswith("advanced-") for h in engaged), engaged


class TestPiece3aRegateEndToEnd:
    """A10/11 — the REAL `_live_merge_pr` re-gate fires for an admitted node."""

    def _one_node_resume(self, tmp_path: Path, repo: Path, head: str, run_id: str):
        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        # Only repo-a participates; make repo-b a merged no-op so the merge loop
        # reaches repo-a's REAL _live_merge_pr with the ledger-bound run_id.
        ws_map = {n.node_id: (repo if n.repo == "repo-a" else tmp_path / n.repo) for n in roadmap.nodes}
        ledger = tmp_path / "ledger" / "train.ledger.jsonl"
        append_record(ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/pr1",
            head_sha=head, pr_url="https://gh/a/1", merge_order=0, fab_run_id=run_id))
        append_record(ledger, LedgerRecord(
            node_id="repo-b/specs/plan-b.md", status="merged", branch="feat/repo-b",
            head_sha="sha-b", pr_url="https://gh/b/1", upstream_merge_sha="sha-b-merged", merge_order=1))
        return roadmap, ws_map, ledger

    def test_regate_passes_legit_admitted_head(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-e2e")
        roadmap, ws_map, ledger = self._one_node_resume(tmp_path, repo, head, "run-e2e")

        fake = _make_gh_fake(base_ref="main", head=head)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            result = run_train(
                roadmap, ledger, run_mode="governed",
                resolve_workspace=lambda n: ws_map[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub({}),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_p3a_pr_open,
                _live_pr_head_sha_fn=lambda ws, br: None,
                _merge_phase_enabled=True,
                # REAL _live_merge_pr (default merge fn) — the re-gate runs here.
                _reverify_fn=_reverify_pass,
                _train_review_fn=_approval_review_fn,
                fab_fetch_origin="fetchsrc",
            )
        assert result["status"] == "merged", result

    def test_fab_queue_terminal_sha_recorded_in_ledger_through_run_train(self, tmp_path: Path, monkeypatch):
        """#265 CR round 1 test-gap: the terminal→ledger integration. THROUGH run_train
        (real `_live_merge_pr`, queue path), the queue-produced terminal SHA is written
        into the node's durable `merged` ledger record — not just returned. `time.sleep`
        is a no-op so the poll spins to the terminal without real time."""
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        monkeypatch.setattr("phase_loop_runtime.train_runner.time.sleep", lambda _s: None)
        repo = _make_fab_repo(tmp_path)
        _base, head = _reviewed_pr(repo, "run-mq-e2e")
        roadmap, ws_map, ledger = self._one_node_resume(tmp_path, repo, head, "run-mq-e2e")

        fake = _make_queue_gh_fake(base_ref="main", head=head, merged_sha="sha-queue-terminal", merges_after=1)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            result = run_train(
                roadmap, ledger, run_mode="governed",
                resolve_workspace=lambda n: ws_map[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub({}),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_p3a_pr_open,
                _live_pr_head_sha_fn=lambda ws, br: None,
                _merge_phase_enabled=True,  # REAL _live_merge_pr → the queue wait runs here
                _reverify_fn=_reverify_pass,
                _train_review_fn=_approval_review_fn,
                fab_fetch_origin="fetchsrc",
            )
        assert result["status"] == "merged", result
        rec = read_ledger(ledger)["repo-a/specs/plan-a.md"]
        assert rec.status == "merged"
        assert rec.upstream_merge_sha == "sha-queue-terminal", (
            "the QUEUE-produced terminal SHA must be recorded in the durable ledger, not lost"
        )

    def test_regate_fail_closes_on_tampered_provenance(self, tmp_path: Path, monkeypatch):
        _git_available()
        monkeypatch.setenv(gp.FAB_PROMOTION_ENV, "1")
        repo = _make_fab_repo(tmp_path)
        _base, reviewed_head = _reviewed_pr(repo, "run-e2e-drift")
        # A later commit lands on the reviewed branch: the live head no longer
        # matches what FAB reviewed. The admitted head in the ledger is the
        # DRIFTED head (broker re-admitted it); only the re-gate catches it.
        _write(repo, "a.py", "post-review drift\n")
        drifted = _commit(repo, "c2 drift")
        roadmap, ws_map, ledger = self._one_node_resume(tmp_path, repo, drifted, "run-e2e-drift")

        fake = _make_gh_fake(base_ref="main", head=drifted)
        with patch("phase_loop_runtime.train_runner.subprocess.run", side_effect=fake):
            result = run_train(
                roadmap, ledger, run_mode="governed",
                resolve_workspace=lambda n: ws_map[n.node_id],
                _run_loop=lambda *a, **kw: (None, []),
                _publish=_make_publish_stub({}),
                _set_upstream_ref_fn=lambda *a, **kw: [],
                _preflight_fn=_preflight_pass,
                _pr_is_open=_p3a_pr_open,
                _live_pr_head_sha_fn=lambda ws, br: None,
                _merge_phase_enabled=True,
                _reverify_fn=_reverify_pass,
                _train_review_fn=_approval_review_fn,
                fab_fetch_origin="fetchsrc",
            )
        assert result["status"] != "merged", result
        assert "fab-promotion-reassertion" in json.dumps(result, default=str)


def test_fabreadmit_hardcoded_epoch_publisher_interlock(request, tmp_path):
    """Interlock arm: any supported publisher stamping hardcoded epoch blocks readiness."""
    import ast
    from pathlib import Path
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

    src_dir = Path(__file__).resolve().parent.parent / "src" / "phase_loop_runtime"
    hardcoded_sites = []

    for p in src_dir.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "epoch" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                        hardcoded_sites.append(f"{p.name}:{node.lineno}")

    synthetic_file = tmp_path / "hardcoded_publisher.py"
    synthetic_file.write_text("def publish(): return do_publish(epoch=1)\n", encoding="utf-8")
    syn_tree = ast.parse(synthetic_file.read_text(encoding="utf-8"))
    syn_hardcoded = False
    for node in ast.walk(syn_tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "epoch" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                    syn_hardcoded = True

    check_fn = fabreadmit_symbol("phase_loop_runtime.governed_premerge", "_has_no_hardcoded_epoch_publishers")
    no_hardcoded_prod = check_fn() if callable(check_fn) else False

    valid_interlock = (len(hardcoded_sites) == 0 and syn_hardcoded and no_hardcoded_prod)

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        valid_interlock,
        f"Hardcoded epoch publishers present or interlock unvalidated: {hardcoded_sites}",
    )


def test_fabreadmit_flag_reversal_kills_shortcut(request, tmp_path):
    """Reverting readiness interlock kills real-git shortcut."""
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

    readiness = fabreadmit_symbol("phase_loop_runtime.governed_premerge", "_FAB_DELTA_BROKER_READMIT_READY")

    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        readiness is True,
        "_FAB_DELTA_BROKER_READMIT_READY is False in governed_premerge",
    )
