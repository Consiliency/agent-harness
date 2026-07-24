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

from phase_loop_runtime import fab_delta as fd
from phase_loop_runtime import fab_gate as fg
from phase_loop_runtime import fab_producer as prod
from phase_loop_runtime import fab_provenance as fp
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

from test_fab_gate_d import GitRepoTestCase, _STRONG_MANIFEST, _durable_from_seat, _seat


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
