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
        prod.capture_delta_review_at_invocation(self.repo, run_id, _delta_panel(), epoch=2)
        delta_record = prod.build_and_finalize_delta_round(
            self.repo, run_id,
            epoch=2, base_sha=base, repo_slug=self.REPO_SLUG,
            parent_head_sha=candidate_head, parent_patch_digest=candidate.patch_digest, parent_chain_digest=c0,
            delta_head_sha=delta_head, findings=(), resolved_finding_ids=(),
            review_scope=fp.ReviewScope(mode=fp.REVIEW_SCOPE_DELTA_ONLY),
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
        prod.capture_delta_review_at_invocation(self.repo, run_id, _delta_panel(), epoch=2)
        d2 = prod.build_and_finalize_delta_round(
            self.repo, run_id, epoch=2, base_sha=base, repo_slug=self.REPO_SLUG,
            parent_head_sha=candidate_head, parent_patch_digest=candidate.patch_digest, parent_chain_digest=c0,
            delta_head_sha=delta2_head, findings=(), review_scope=fp.ReviewScope(mode=fp.REVIEW_SCOPE_DELTA_ONLY),
        )
        self.write("pkg/d.py", "delta 3\n")
        delta3_head = self.commit("c3 delta")
        prod.capture_delta_review_at_invocation(self.repo, run_id, _delta_panel(), epoch=3)
        prod.build_and_finalize_delta_round(
            self.repo, run_id, epoch=3, base_sha=base, repo_slug=self.REPO_SLUG,
            parent_head_sha=delta2_head, parent_patch_digest=d2.resulting_head_digest, parent_chain_digest=d2.chain_digest,
            delta_head_sha=delta3_head, findings=(), review_scope=fp.ReviewScope(mode=fp.REVIEW_SCOPE_DELTA_ONLY),
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

    def _review_fn(self, ws, diff):
        from phase_loop_runtime.governed_premerge import LoopResult
        return LoopResult(mergeable=True, ran=True, rounds=1, panel=_delta_panel())

    def test_readmit_happy_path_extends_chain_and_commits_ledger(self):
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, delta_head = self._setup_candidate_and_advance()
        new_admitted = tr._fab_delta_readmit(
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
            delta_review_fn=self._review_fn, fab_fetch_origin="fetchsrc",
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
                    delta_review_fn=self._review_fn, fab_fetch_origin="fetchsrc",
                )
            # Fail-closed: the ledger still admits the OLD candidate head.
            self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

            # RESUME (attempt 2): the append succeeds → converges to the new head.
            state["crash"] = False
            new_admitted = tr._fab_delta_readmit(
                self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                delta_review_fn=self._review_fn, fab_fetch_origin="fetchsrc",
            )
            self.assertEqual(new_admitted, delta_head)
            self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, delta_head)
            gate = fg.compose_gate_status(
                repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=delta_head, origin="fetchsrc"
            )
            self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)
        finally:
            _trmod.append_record = real_append

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
            delta_review_fn=self._review_fn, fab_fetch_origin="fetchsrc",
        )
        self.assertIsNone(result)
