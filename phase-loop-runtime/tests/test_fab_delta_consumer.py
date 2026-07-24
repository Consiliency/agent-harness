"""FAB (Consiliency/agent-harness#191) piece 3b-CONSUMER — the delta-round
capture/build round-trip through the LIVE merged gate. Deliberately UNMARKED so
CI runs it. Uses REAL git (base -> candidate_head -> delta_head) so every
live-git recompute in the gate (candidate.patch_digest, delta resulting_head_
digest, delta_changed_paths) resolves.

The load-bearing proof (team-lead's "real proof"): a delta round CAPTURED from a
real committed-range panel + BUILT off live git produces a `DeltaReviewRecord`
that, appended to the candidate artifact, PASSES `compose_gate_status` through the
merged gate — resolution_digest bound, per-round seats authenticated, epoch-set
complete. Anti-tautology: the delta seats come from the panel, the durable side
is the harness's own computation, and the gate re-derives everything.
"""
from __future__ import annotations

import unittest

from phase_loop_runtime import fab_delta as fd
from phase_loop_runtime import fab_gate as fg
from phase_loop_runtime import fab_producer as prod
from phase_loop_runtime import fab_provenance as fp
from phase_loop_runtime.governed_bundle import committed_range_diff
from phase_loop_runtime.governed_premerge import FAB_PROMOTION_ENV, fab_delta_shortcut_enabled
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

from test_fab_gate_d import GitRepoTestCase, _STRONG_MANIFEST, _durable_from_seat, _seat


class DeltaShortcutOptInTest(unittest.TestCase):
    """The delta-review shortcut is gated by a TRUSTED coordinator opt-in AND the
    master PHASE_LOOP_FAB flag — never engaged by PR-controlled input."""

    def test_requires_both_master_flag_and_coordinator_opt_in(self):
        on = {FAB_PROMOTION_ENV: "1"}
        off: dict = {}
        # Both on → engaged.
        self.assertTrue(fab_delta_shortcut_enabled(True, env=on))
        # Master flag off → never engaged, even with opt-in.
        self.assertFalse(fab_delta_shortcut_enabled(True, env=off))
        # Coordinator opt-in off → never engaged, even with the master flag.
        self.assertFalse(fab_delta_shortcut_enabled(False, env=on))
        self.assertFalse(fab_delta_shortcut_enabled(False, env=off))


def _delta_panel() -> PanelResult:
    """A real 2-leg delta-review panel result, both AGREE — the seats the consumer
    captures at invocation (never synthesized)."""
    return PanelResult(
        legs=(
            PanelLegResult(leg="codex", status="OK", text="Reviewed the delta.\n\nAGREE", seat_key="codex:d:high"),
            PanelLegResult(leg="gemini", status="OK", text="Reviewed the delta.\n\nAGREE", seat_key="gemini:d:high"),
        )
    )


class DeltaConsumerRoundTripTest(GitRepoTestCase):
    def test_delta_capture_build_passes_the_live_gate(self):
        run_id = "fab-delta-roundtrip"
        # Manifest whose globs (auth/**, *secret*) do NOT match pkg/*.py, so the
        # disjoint delta stays a plain reviewed-clean round (no escalation).
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        base = self.commit("c0 base")
        self.push_main()

        # -- CANDIDATE round (epoch 1): a 1-commit-off-base reviewed head --------
        self.write("pkg/a.py", "reviewed candidate content\n")
        candidate_head = self.commit("c1 candidate patch")
        candidate = self.candidate(base, candidate_head)
        candidate_seats = (_seat("codex:c:high", epoch=1, finding_ids=()),)
        candidate_artifact = self.build_artifact(base_sha=base, candidate=candidate, seats=candidate_seats)
        c0 = candidate_artifact.chain_digest
        fp.write_provenance(self.repo, run_id, candidate_artifact)
        for s in candidate_seats:
            fg.append_seat_outcome(self.repo, run_id, _durable_from_seat(s))
        self.write_review_round(run_id, candidate_artifact)  # candidate round record e1 (resolution_digest=None)

        # -- DELTA round (epoch 2): a real committed-range review of the advance --
        self.write("pkg/c.py", "small disjoint delta content\n")
        delta_head = self.commit("c2 disjoint delta advance")
        diff = committed_range_diff(self.repo, candidate_head, delta_head)
        prod.capture_delta_review_at_invocation(self.repo, run_id, _delta_panel(), epoch=2, reviewed_diff_text=diff)
        delta_record = prod.build_and_finalize_delta_round(
            self.repo, run_id,
            epoch=2, base_sha=base, repo_slug=self.REPO_SLUG,
            parent_head_sha=candidate_head, parent_patch_digest=candidate.patch_digest, parent_chain_digest=c0,
            delta_head_sha=delta_head, findings=(), resolved_finding_ids=(),
            review_scope=fp.ReviewScope(mode=fp.REVIEW_SCOPE_DELTA_ONLY), reviewed_diff_text=diff,
        )
        self.assertEqual(delta_record.status, fp.DELTA_STATUS_REVIEWED_CLEAN)
        self.assertFalse(delta_record.escalation.required)

        # -- The extended artifact (candidate + delta) the merged gate reads ------
        extended = self.build_artifact(
            base_sha=base, candidate=candidate, seats=candidate_seats, delta_chain=(delta_record,)
        )
        fp.write_provenance(self.repo, run_id, extended)

        gate = fg.compose_gate_status(
            repo=self.repo, run_id=run_id, live_base_ref_name="main", live_head_sha=delta_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)
        self.assertEqual(gate.equivalence_verified.result, "EQUIVALENT")

    def test_recapture_truncation_lets_a_shorter_retry_pass(self):
        """Recapture-truncation (gate↔consumer epoch-set contract): a prior attempt
        finalized epochs {1,2,3}; a clean RETRY resolves in {1,2}. Without scoping,
        the stale finalized epoch-3 record makes the gate false-BLOCK on
        `{1,2} != {1,2,3}`; `scope_run_to_epochs({1,2})` removes the stale round →
        the retry PASSES."""
        run_id = "fab-delta-retry"
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        base = self.commit("c0 base")
        self.push_main()
        self.write("pkg/a.py", "candidate\n")
        candidate_head = self.commit("c1 candidate")
        candidate = self.candidate(base, candidate_head)
        candidate_seats = (_seat("codex:c:high", epoch=1, finding_ids=()),)
        candidate_artifact = self.build_artifact(base_sha=base, candidate=candidate, seats=candidate_seats)
        c0 = candidate_artifact.chain_digest
        fp.write_provenance(self.repo, run_id, candidate_artifact)
        for s in candidate_seats:
            fg.append_seat_outcome(self.repo, run_id, _durable_from_seat(s))
        self.write_review_round(run_id, candidate_artifact)

        # ATTEMPT 1 → epochs {1, 2, 3}.
        self.write("pkg/c.py", "delta 2\n")
        delta2_head = self.commit("c2 delta")
        diff2 = committed_range_diff(self.repo, candidate_head, delta2_head)
        prod.capture_delta_review_at_invocation(self.repo, run_id, _delta_panel(), epoch=2, reviewed_diff_text=diff2)
        d2 = prod.build_and_finalize_delta_round(
            self.repo, run_id, epoch=2, base_sha=base, repo_slug=self.REPO_SLUG,
            parent_head_sha=candidate_head, parent_patch_digest=candidate.patch_digest, parent_chain_digest=c0,
            delta_head_sha=delta2_head, findings=(), review_scope=fp.ReviewScope(mode=fp.REVIEW_SCOPE_DELTA_ONLY),
            reviewed_diff_text=diff2,
        )
        self.write("pkg/d.py", "delta 3\n")
        delta3_head = self.commit("c3 delta")
        diff3 = committed_range_diff(self.repo, delta2_head, delta3_head)
        prod.capture_delta_review_at_invocation(self.repo, run_id, _delta_panel(), epoch=3, reviewed_diff_text=diff3)
        prod.build_and_finalize_delta_round(
            self.repo, run_id, epoch=3, base_sha=base, repo_slug=self.REPO_SLUG,
            parent_head_sha=delta2_head, parent_patch_digest=d2.resulting_head_digest, parent_chain_digest=d2.chain_digest,
            delta_head_sha=delta3_head, findings=(), review_scope=fp.ReviewScope(mode=fp.REVIEW_SCOPE_DELTA_ONLY),
            reviewed_diff_text=diff3,
        )
        # RETRY resolves in {1,2}: the client chain is (d2,) only, but the run store
        # still holds the stale finalized epoch-3 record → false-BLOCK.
        retry_artifact = self.build_artifact(
            base_sha=base, candidate=candidate, seats=candidate_seats, delta_chain=(d2,)
        )
        fp.write_provenance(self.repo, run_id, retry_artifact)
        blocked = fg.compose_gate_status(
            repo=self.repo, run_id=run_id, live_base_ref_name="main", live_head_sha=delta2_head, origin="fetchsrc"
        )
        self.assertEqual(blocked.status, fp.GATE_STATUS_BLOCK)
        self.assertIn("durable FINALIZED epoch set", blocked.equivalence_verified.reason or "")

        # Scope the run to THIS attempt's chain → the stale epoch-3 record is gone.
        prod.scope_run_to_epochs(self.repo, run_id, (fg.FAB_CANDIDATE_EPOCH, 2))
        passed = fg.compose_gate_status(
            repo=self.repo, run_id=run_id, live_base_ref_name="main", live_head_sha=delta2_head, origin="fetchsrc"
        )
        self.assertEqual(passed.status, fp.GATE_STATUS_PASS, passed.equivalence_verified.reason)


class DeltaReadmitTransactionTest(GitRepoTestCase):
    """The atomic re-admission (`_fab_delta_readmit`) — the CR crux: ordering,
    crash-between fail-closed, and resume convergence."""

    RUN = "fab-readmit"

    def _setup_candidate_and_advance(self):
        """Real git base→candidate_head→delta_head; a candidate run store admitted at
        candidate_head; returns (ledger_path, base, candidate_head, delta_head)."""
        from phase_loop_runtime.train_ledger import LedgerRecord, append_record

        # Exclude the run store from git (as the real runtime does via
        # .git/info/exclude) so the test's `git add -A` never tracks `.phase-loop/`
        # and a `git reset --hard` cannot delete the durable run store.
        (self.repo / ".git" / "info" / "exclude").write_text(".phase-loop/\n", encoding="utf-8")
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        base = self.commit("c0 base")
        self.push_main()
        self.write("pkg/a.py", "candidate\n")
        candidate_head = self.commit("c1 candidate")
        candidate = self.candidate(base, candidate_head)
        candidate_seats = (_seat("codex:c:high", epoch=1, finding_ids=()),)
        candidate_artifact = self.build_artifact(base_sha=base, candidate=candidate, seats=candidate_seats)
        fp.write_provenance(self.repo, self.RUN, candidate_artifact)
        for s in candidate_seats:
            fg.append_seat_outcome(self.repo, self.RUN, _durable_from_seat(s))
        self.write_review_round(self.RUN, candidate_artifact)
        # The advance: a single commit past the admitted candidate head.
        self.write("pkg/c.py", "disjoint delta advance\n")
        delta_head = self.commit("c2 advance")
        ledger_path = self.repo.parent / "train.ledger.jsonl"
        append_record(ledger_path, LedgerRecord(
            node_id="n1", status="pr_open", branch="feat/pr1", head_sha=candidate_head,
            fab_run_id=self.RUN, merge_order=0))
        return ledger_path, base, candidate_head, delta_head

    # All delta advances in these fixtures touch `pkg/...`; the node's owned scope
    # is `pkg` so the CR-B4 broker owned-scope re-check passes for the intended
    # cases and can be narrowed to prove an out-of-scope escape fails closed.
    OWNED = ["pkg"]

    def _review_fn(self, ws, diff, author_vendors=frozenset()):
        from phase_loop_runtime.governed_premerge import LoopResult
        return LoopResult(mergeable=True, ran=True, rounds=1, panel=_delta_panel())

    def test_readmit_happy_path_extends_chain_and_commits_ledger(self):
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, delta_head = self._setup_candidate_and_advance()
        new_admitted = tr._fab_delta_readmit(
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
            delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
        )
        self.assertEqual(new_admitted, delta_head)
        # COMMIT POINT: the ledger now admits the new head with the same fab_run_id.
        rec = read_ledger(ledger_path)["n1"]
        self.assertEqual(rec.head_sha, delta_head)
        self.assertEqual(rec.fab_run_id, self.RUN)
        # The extended chain (candidate + delta) passes the merged gate at the new head.
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=delta_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)

    def test_crash_between_fails_closed_then_resume_converges(self):
        """A crash BETWEEN the provenance overwrite and the ledger append: the
        ledger still admits the OLD head (fail-closed — the merge guard would fire),
        yet the durable provenance was extended. Resume re-runs the branch and
        converges (recapture → scope → rebuild → re-admit), NOT bricked."""
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, delta_head = self._setup_candidate_and_advance()

        # ATTEMPT 1 crashes at the commit point: append_record raises after the
        # provenance overwrite + fsync + gate-verify.
        import phase_loop_runtime.train_runner as _trmod
        real_append = _trmod.append_record
        state = {"crash": True}

        def crashing_append(path, record):
            if state["crash"] and record.status == "pr_open" and record.head_sha == delta_head:
                raise OSError("simulated crash at the ledger commit point")
            return real_append(path, record)

        _trmod.append_record = crashing_append
        try:
            with self.assertRaises(OSError):
                tr._fab_delta_readmit(
                    self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                    merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                    delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
                )
            # Fail-closed: the ledger still admits the OLD candidate head.
            self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

            # RESUME (attempt 2): the append succeeds → converges to the new head.
            state["crash"] = False
            new_admitted = tr._fab_delta_readmit(
                self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
            )
            self.assertEqual(new_admitted, delta_head)
            self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, delta_head)
            gate = fg.compose_gate_status(
                repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=delta_head, origin="fetchsrc"
            )
            self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)
        finally:
            _trmod.append_record = real_append

    def test_review_reject_is_not_re_admitted(self):
        """The whole point of reviewing: a delta review that does NOT pass (panel
        non-mergeable) → _fab_delta_readmit returns None, appends NO ledger record,
        and the admitted head stays the OLD candidate head (→ pr-head-advanced
        guard fires at merge)."""
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.governed_premerge import LoopResult
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, delta_head = self._setup_candidate_and_advance()

        def reject_fn(ws, diff, author_vendors=frozenset()):
            return LoopResult(mergeable=False, ran=True, rounds=1, panel=_delta_panel())

        result = tr._fab_delta_readmit(
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
            delta_review_fn=reject_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
        )
        self.assertIsNone(result)
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

    def test_torn_provenance_from_crash_recovers_on_next_attempt(self):
        """CR B2 — the crux the happy/final-append tests masked. Attempt 1 CRASHES
        AFTER the provenance is overwritten with the extended chain (before the
        gate-verify/recovery could run) → a torn durable state (ledger admits C1,
        provenance resolves to C2, and the durable epoch-2 record would even fail
        the candidate-only epoch-set-completeness → the node was bricked: couldn't
        merge, revert, or accept a fix). The author then replaces the advance with
        a new single commit C2'; attempt 2 must CONVERGE — the unconditional
        scope-back-to-admitted-prefix at the START of the attempt recovers the
        torn state, then rebuilds for C2' and re-admits."""
        import subprocess

        from phase_loop_runtime import fab_provenance as fpmod
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, c2_head = self._setup_candidate_and_advance()

        # ATTEMPT 1: crash on the fsync of the EXTENDED provenance (the one whose
        # chain is nonempty) → torn state left, no recovery.
        real_fsync = fpmod.fsync_run_store_durable
        crashed = {"done": False}

        def crashing_fsync(repo, run_id):
            art = fg.read_provenance(repo, run_id)
            if art.delta_chain and not crashed["done"]:
                crashed["done"] = True
                raise OSError("simulated crash after the extended-provenance overwrite")
            return real_fsync(repo, run_id)

        fpmod.fsync_run_store_durable = crashing_fsync
        try:
            with self.assertRaises(OSError):
                tr._fab_delta_readmit(
                    self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                    merge_order=0, admitted_head_sha=candidate_head, live_head_sha=c2_head,
                    delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
                )
        finally:
            fpmod.fsync_run_store_durable = real_fsync
        # Torn: the provenance resolves to C2 but the ledger still admits C1.
        self.assertEqual(fg.read_provenance(self.repo, self.RUN).delta_chain[-1].delta_head_sha, c2_head)
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

        # The author force-resets the branch to the admitted head and pushes a NEW
        # single-commit replacement advance C2'.
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)
        self.write("pkg/fix.py", "fixed single-commit advance\n")
        c2b_head = self.commit("c2' replacement advance")

        # ATTEMPT 2 must CONVERGE (scope-back-at-start recovers the torn state).
        new_admitted = tr._fab_delta_readmit(
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=c2b_head,
            delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
        )
        self.assertEqual(new_admitted, c2b_head, "attempt 2 must converge, not brick on the torn state")
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, c2b_head)
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=c2b_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)

    def test_multi_commit_advance_is_not_handled(self):
        """A MULTI-commit advance is out of scope → _fab_delta_readmit returns None
        (the caller falls through to the unchanged pr-head-advanced guard)."""
        from phase_loop_runtime import train_runner as tr

        ledger_path, base, candidate_head, delta_head = self._setup_candidate_and_advance()
        self.write("pkg/e.py", "second advance commit\n")
        delta_head_2 = self.commit("c3 second advance")  # now 2 commits past candidate
        result = tr._fab_delta_readmit(
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head_2,
            delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
        )
        self.assertIsNone(result)

    def test_delta_touching_out_of_scope_path_is_not_re_admitted(self):
        """CR B4 — broker owned-scope re-check (ah#202/#251). The advance touches
        `pkg/c.py`; when the node's owned scope does NOT cover it, the re-admission
        fails closed (→ the pr-head-advanced guard), never broker-admitting an
        advance that escapes the node's owned scope. An UNPROVABLE scope
        (`owned_paths=None`) is treated the same way — the fence is never applied on
        a scope we cannot establish."""
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, delta_head = self._setup_candidate_and_advance()
        for scope in (["docs"], None):  # out-of-scope, then unprovable
            result = tr._fab_delta_readmit(
                self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                delta_review_fn=self._review_fn, owned_paths=scope, fab_fetch_origin="fetchsrc",
            )
            self.assertIsNone(result, f"owned_paths={scope!r} must fail closed")
            self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

    def test_delta_commit_author_vendor_is_excluded_from_the_delta_review(self):
        """CR B5 — reviewer≠author for the DELTA. The advance is authored OUT-OF-BAND
        by a vendor (gemini) with NO local dispatch event; `_fab_delta_readmit` must
        extract that vendor from the ACTUAL delta commit range and pass it to the
        review as an excluded author — so the vendor can never sit on its own
        delta's board (the historical dispatch-event union would MISS it)."""
        import os
        import subprocess

        from phase_loop_runtime import train_runner as tr

        ledger_path, base, candidate_head, _delta_head = self._setup_candidate_and_advance()
        # Replace the advance with one AUTHORED by a gemini agent (author +
        # committer + Co-authored-by all carry the vendor marker), no dispatch event.
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)
        self.write("pkg/c.py", "gemini out-of-band advance\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, capture_output=True)
        env = {**os.environ,
               "GIT_AUTHOR_NAME": "Gemini Agent", "GIT_AUTHOR_EMAIL": "g@example.com",
               "GIT_COMMITTER_NAME": "Gemini Agent", "GIT_COMMITTER_EMAIL": "g@example.com"}
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "delta by gemini\n\nCo-authored-by: Gemini <g@example.com>"],
            check=True, capture_output=True, env=env,
        )
        gem_head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()

        # The extractor binds the vendor to the actual delta commits.
        self.assertIn("gemini", tr._delta_commit_author_vendors(self.repo, candidate_head, gem_head))

        seen: dict = {}

        def capturing_review(ws, diff, author_vendors=frozenset()):
            from phase_loop_runtime.governed_premerge import LoopResult
            seen["authors"] = frozenset(author_vendors)
            return LoopResult(mergeable=True, ran=True, rounds=1, panel=_delta_panel())

        new_admitted = tr._fab_delta_readmit(
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=gem_head,
            delta_review_fn=capturing_review, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
        )
        self.assertEqual(new_admitted, gem_head)
        self.assertIn(
            "gemini", seen["authors"],
            "the delta's OWN author vendor must be passed to the review as an excluded author",
        )


class SeatLedgerAtomicRewriteTest(GitRepoTestCase):
    """CR B1 — the durable seat ledger is rewritten ATOMICALLY (temp → fsync →
    `os.replace`), never unlink-then-append. A crash DURING the rewrite must leave
    the ORIGINAL ledger fully intact — losing the candidate seats would brick the
    node (the gate could no longer authenticate them)."""

    def test_crash_during_rewrite_leaves_original_ledger_intact(self):
        from phase_loop_runtime import fab_gate as fgmod
        from phase_loop_runtime import fab_provenance as fpmod

        run_id = "fab-seat-atomic"
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        self.commit("c0 base")
        self.push_main()

        s1 = _durable_from_seat(_seat("codex:c:high", epoch=1, finding_ids=()))
        s2 = _durable_from_seat(_seat("gemini:d:high", epoch=2, finding_ids=()))
        fgmod.append_seat_outcome(self.repo, run_id, s1)
        fgmod.append_seat_outcome(self.repo, run_id, s2)
        self.assertEqual(len(fgmod.read_seat_outcomes(self.repo, run_id)), 2)

        # Crash at the atomic replace while rewriting to DROP epoch 2: the rewrite
        # must raise and leave the on-disk ledger UNCHANGED (both records present).
        real_replace = fpmod.os.replace

        def boom(src, dst):
            raise OSError("simulated crash before the atomic replace")

        fpmod.os.replace = boom
        try:
            with self.assertRaises(OSError):
                fgmod.rewrite_seat_ledger(self.repo, run_id, [s1])
        finally:
            fpmod.os.replace = real_replace

        after = fgmod.read_seat_outcomes(self.repo, run_id)
        self.assertEqual(
            len(after), 2,
            "a crash mid-rewrite must never truncate/lose the durable seat ledger (never unlink-then-append)",
        )


class DeltaMaterialBindingTest(GitRepoTestCase):
    """CR B3 — the delta review binds the REVIEWED bytes, and an incomplete render
    is never laundered into provenance for bytes the seats never saw."""

    def test_sentinel_reviewed_diff_is_rejected_no_delta_round(self):
        run_id = "fab-delta-sentinel"
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        self.commit("c0 base")
        self.push_main()
        # `committed_range_diff`'s fail-closed sentinel (nonzero git rc / empty
        # range) must be REJECTED at capture — no seats/round for unseen bytes.
        for sentinel in ("(committed range diff unavailable)", "(empty committed range diff)"):
            with self.assertRaises(prod.ProvenanceInvalid):
                prod.capture_delta_review_at_invocation(
                    self.repo, run_id, _delta_panel(), epoch=2, reviewed_diff_text=sentinel
                )


class DeltaReviewEmptyAuthorFailsClosedTest(unittest.TestCase):
    """CR B5 load-bearing assumption — the REAL delta review (`_default_delta_
    review`, not the injected seam) FAILS CLOSED when the author-vendor set is empty
    (unknown author). This is what makes 'union the delta authors with the dispatch
    authors, empty ⇒ block' conservative rather than a silent self-review: an
    out-of-band vendor commit with no marker and no dispatch event yields an empty
    set → NOT mergeable, never the full panel including the author's own vendor.
    The block fires BEFORE any panel/leg discovery, so no CLI is spawned."""

    def test_empty_author_vendors_is_not_mergeable(self):
        import tempfile
        from pathlib import Path

        from phase_loop_runtime import train_runner as tr

        with tempfile.TemporaryDirectory() as d:
            result = tr._default_delta_review(
                Path(d), "diff --git a/x b/x\n@@\n+y\n", author_vendors=frozenset()
            )
        self.assertFalse(
            getattr(result, "mergeable", True),
            "an unknown (empty) delta author must fail closed, never run a self-review panel",
        )
