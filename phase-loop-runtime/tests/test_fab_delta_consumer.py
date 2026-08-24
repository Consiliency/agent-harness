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
from pathlib import Path

from phase_loop_runtime import fab_delta as fd
from phase_loop_runtime import fab_gate as fg
from phase_loop_runtime import fab_producer as prod
from phase_loop_runtime import fab_provenance as fp
from phase_loop_runtime.governed_bundle import committed_range_diff
from phase_loop_runtime.governed_premerge import FAB_PROMOTION_ENV, fab_delta_shortcut_enabled
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult

from test_fab_gate_d import GitRepoTestCase, _STRONG_MANIFEST, _durable_from_seat, _seat
import pytest
from test_fab_activation_promotion import TRAIN_2NODE_MD, _make_publish_stub, _reverify_pass
from test_train_merge import _approval_review_fn



class DeltaShortcutOptInTest(unittest.TestCase):
    """The delta-review shortcut is gated by the #288 broker-readmit INTERLOCK AND a
    TRUSTED coordinator opt-in AND the master PHASE_LOOP_FAB flag — never engaged by
    PR-controlled input, and fenced OFF entirely until the deferred broker
    re-admission (Consiliency/agent-harness#288) lands."""

    def test_interlock_off_fences_engage_even_with_both_opt_ins(self):
        """CR round 5 (operator interlock): with the #288 interlock constant False —
        its shipped default — the shortcut NEVER engages, even with BOTH the master
        flag and the coordinator opt-in on. The broker gap is unreachable by
        construction, not by operator discipline."""
        import unittest.mock as _mock
        import phase_loop_runtime.governed_premerge as gpmod

        with _mock.patch.object(gpmod, "_FAB_DELTA_BROKER_READMIT_READY", False):
            on = {FAB_PROMOTION_ENV: "1"}
            self.assertFalse(fab_delta_shortcut_enabled(True, env=on))


    def test_requires_interlock_and_both_master_flag_and_coordinator_opt_in(self):
        """With the interlock FLIPPED ON (as #288 will), the gate reduces to the
        original master-flag AND coordinator-opt-in predicate — a clear switch + a
        proof the two trusted inputs are still both required."""
        import unittest.mock as _mock

        on = {FAB_PROMOTION_ENV: "1"}
        off: dict = {}
        with _mock.patch("phase_loop_runtime.governed_premerge._FAB_DELTA_BROKER_READMIT_READY", True):
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


def _fabreadmit_node_scoped_merge_stub(captured: dict, node_for_workspace: dict[Path, str]):
    """Capture each P4 merge under the roadmap node that owns its workspace."""
    def _merge_pr(workspace, branch, base="main", head_sha=None, run_id=None, fab_fetch_origin="origin"):
        node_id = node_for_workspace[Path(workspace)]
        captured.setdefault(node_id, []).append(
            {
                "branch": branch,
                "head_sha": head_sha,
                "run_id": run_id,
            }
        )
        return f"sha-merged-{Path(workspace).name}"
    return _merge_pr


def _seed_fabreadmit_two_node_resume(ledger_path: Path, candidate_head: str) -> None:
    """Make repo-b and the train approval durable before a repo-a-only replay."""
    from phase_loop_runtime.train_ledger import LedgerRecord, append_record
    from phase_loop_runtime.train_runner import _MIN_USABLE_REVIEWERS, _TRAIN_REVIEW_NODE_ID

    append_record(
        ledger_path,
        LedgerRecord(
            node_id="repo-b/specs/plan-b.md",
            status="pr_open",
            branch="feat/repo-b",
            head_sha=candidate_head,
            pr_url="u-repo-b",
            merge_order=1,
        ),
    )
    append_record(
        ledger_path,
        LedgerRecord(
            node_id=_TRAIN_REVIEW_NODE_ID,
            status="approved",
            usable_reviewers=_MIN_USABLE_REVIEWERS,
        ),
    )


def _run_fabreadmit_two_node_resume(runner, fixture, seeded: dict, *, live_head_sha: str, captured: dict):
    """Drive the governed caller with a coherent repo-a admission and inert repo-b."""
    from phase_loop_runtime.convergence.broker.live import build_routing_broker_client
    from phase_loop_runtime.train_roadmap import parse_train_roadmap
    from phase_loop_runtime.train_runner import CoordinatorRuntime

    node_id = seeded["node_id"]
    repo_b = fixture.tmp_path / "repo-b"
    repo_b.mkdir(parents=True, exist_ok=True)
    ws_map = {
        node_id: fixture.repo,
        "repo-b/specs/plan-b.md": repo_b,
    }
    coordinator_runtime = CoordinatorRuntime(
        train_id="train1",
        coordinator_root=seeded["coordinator_root"],
        roadmap_path="train.md",
        roadmap_digest="d" * 64,
        workspace_id=str(fixture.repo),
        broker_client=build_routing_broker_client(),
    )
    return runner.run_train(
        # Keep the existing two-node topology, but make its dependency order-only:
        # repo-b has no upstream-content comparison that can pre-empt repo-a P4.
        parse_train_roadmap(TRAIN_2NODE_MD.replace(
            "**Channel:** submodule path=vendor/repo-a", "**Channel:** order-only"
        )),
        seeded["ledger_path"],
        run_mode="governed",
        resolve_workspace=lambda node: ws_map[node.node_id],
        coordinator_runtime=coordinator_runtime,
        resolve_owned_paths=None,
        _run_loop=lambda *args, **kwargs: (None, []),
        _publish=_make_publish_stub({}),
        _set_upstream_ref_fn=lambda *args, **kwargs: [],
        _preflight_fn=lambda *args, **kwargs: None,
        _pr_is_open=lambda *args, **kwargs: True,
        _live_pr_head_sha_fn=lambda workspace, branch: (
            live_head_sha if Path(workspace) == fixture.repo else None
        ),
        _merge_phase_enabled=True,
        _reverify_fn=_reverify_pass,
        _train_review_fn=_approval_review_fn,
        _pr_merged_sha_fn=lambda *args, **kwargs: None,
        _delta_review_fn=fixture._review_fn,
        _merge_pr_fn=_fabreadmit_node_scoped_merge_stub(captured, {
            fixture.repo: node_id,
            repo_b: "repo-b/specs/plan-b.md",
        }),
        fab_fetch_origin="fetchsrc",
        fab_delta_shortcut=True,
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
        # The advance: a single vendor-authored commit past the admitted candidate
        # head (attributable so the readmit boundary's reviewer≠author check passes).
        self.write("pkg/c.py", "disjoint delta advance\n")
        delta_head = self._vendor_commit("c2 advance", vendor="Codex")
        ledger_path = self.repo.parent / "train.ledger.jsonl"
        append_record(ledger_path, LedgerRecord(
            node_id="n1", status="pr_open", branch="feat/pr1", head_sha=candidate_head,
            fab_run_id=self.RUN, merge_order=0))
        return ledger_path, base, candidate_head, delta_head

    # All delta advances in these fixtures touch `pkg/...`; the node's owned scope
    # is `pkg` so the CR-B4 broker owned-scope re-check passes for the intended
    # cases and can be narrowed to prove an out-of-scope escape fails closed.
    OWNED = ["pkg"]

    def _vendor_commit(self, message: str, *, vendor: str = "Codex") -> str:
        """Commit the currently-written files AUTHORED by a vendor agent, so the
        delta commit range is positively attributable (CR round 2 B5: an
        unattributed delta author fails closed at the readmit boundary). Returns the
        new HEAD sha."""
        import os
        import subprocess

        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, capture_output=True)
        env = {**os.environ,
               "GIT_AUTHOR_NAME": f"{vendor} Agent", "GIT_AUTHOR_EMAIL": f"agent@{vendor.lower()}.example",
               "GIT_COMMITTER_NAME": f"{vendor} Agent", "GIT_COMMITTER_EMAIL": f"agent@{vendor.lower()}.example"}
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", message], check=True, capture_output=True, env=env)
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()

    def _review_fn(self, ws, diff, author_vendors=frozenset()):
        from phase_loop_runtime.governed_premerge import LoopResult
        return LoopResult(mergeable=True, ran=True, rounds=1, panel=_delta_panel())

    def _setup_broker_readmit_candidate(
        self,
        *,
        node_id: str = "n1",
        branch: str = "feat/pr1",
    ) -> dict:
        """Seed one coherent FABPUB-admitted candidate and a real delta advance.

        The normal publish transaction constructs the candidate commit from the
        staged tree.  Preparing it after a direct commit constructs a child and
        makes the broker/readmission fixture self-contradictory, so this helper
        intentionally stages first, prepares, then resumes the transaction.
        """
        import subprocess

        from phase_loop_runtime.convergence.broker import live
        from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
        from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
        from phase_loop_runtime.convergence.contracts import BrokerRequest, BrokerVerb
        from phase_loop_runtime.publishing import _envelope_from_transaction, prepare_publish_transaction
        from phase_loop_runtime.train_ledger import LedgerRecord, append_record
        from test_fabpub_shared_epoch import _CountingAdapter, _authority_preimage, _service as _pub_service

        # Match the runtime's durable-artifact posture: FAB provenance is local
        # state, never an input to the candidate or delta Git commits.
        (self.repo / ".git" / "info" / "exclude").write_text(
            ".phase-loop/\n", encoding="utf-8"
        )
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        base = self.commit("c0 base")
        self.push_main()

        live.onboard_zero_legacy_repository(self.repo)
        live.fabpub_activation_barrier([self.repo])
        store_root = live.repository_broker_namespace(self.repo)
        identity = live.canonical_repository_identity(self.repo)

        subprocess.run(
            ["git", "-C", str(self.repo), "checkout", "-q", "-b", branch], check=True
        )
        self.write("pkg/a.py", "candidate content\n")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "--", "pkg/a.py"], check=True
        )

        fixture_root = self.repo.parent
        coordinator_root = fixture_root / "coord"
        authority = _authority_preimage(identity, branch)
        authority["train_id"] = "train1"
        authority["node_id"] = node_id
        transaction = prepare_publish_transaction(
            self.repo,
            owned_paths=self.OWNED,
            checkpoint_root=coordinator_root,
            branch=branch,
            envelope_authority_preimage=authority,
        )
        transaction.resume()
        candidate_head = transaction.committed_head_sha
        assert candidate_head == subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True
        ).strip()

        candidate = self.candidate(base, candidate_head)
        candidate_seats = (_seat("codex:c:high", epoch=1, finding_ids=()),)
        candidate_artifact = self.build_artifact(
            base_sha=base, candidate=candidate, seats=candidate_seats
        )
        fp.write_provenance(self.repo, self.RUN, candidate_artifact)
        for seat in candidate_seats:
            fg.append_seat_outcome(self.repo, self.RUN, _durable_from_seat(seat))
        self.write_review_round(self.RUN, candidate_artifact)

        store = LinearizableAdmissionStore(store_root, lambda _: True)
        evidence = BrokerEvidenceStore(store_root)
        publish_adapter = _CountingAdapter()
        publish_service = _pub_service(store_root, publish_adapter, store=store)
        publish_request = BrokerRequest(
            BrokerVerb.PUBLISH_COMMITTED_BRANCH,
            _envelope_from_transaction(transaction, authority, self.repo),
            identity,
            branch,
            candidate_head,
            tuple(transaction.owned_paths),
            adapter_worktree=str(self.repo),
        )
        publish_result = publish_service.execute(publish_request)
        assert publish_result.accepted
        assert len(store.replay()) == 1

        # GitRepoTestCase owns the local fetchsrc bare remote; reuse it rather
        # than registering a second remote with the same routing name.
        fetch_remote = subprocess.check_output(
            ["git", "-C", str(self.repo), "remote", "get-url", "fetchsrc"], text=True
        ).strip()
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "-f", "fetchsrc", f"{base}:refs/heads/main"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "-f", "fetchsrc", f"HEAD:refs/heads/{branch}"],
            check=True,
        )

        ledger_path = fixture_root / "train.ledger.jsonl"
        append_record(
            ledger_path,
            LedgerRecord(
                node_id=node_id,
                status="pr_open",
                branch=branch,
                head_sha=candidate_head,
                pr_url="u",
                merge_order=0,
                fab_run_id=self.RUN,
            ),
        )

        self.write("pkg/c.py", "disjoint delta advance\n")
        delta_head = self._vendor_commit("c2 advance", vendor="Codex")
        subprocess.run(
            ["git", "-C", str(self.repo), "push", "-q", "-f", "fetchsrc", f"HEAD:refs/heads/{branch}"],
            check=True,
        )

        return {
            "base": base,
            "candidate_head": candidate_head,
            "delta_head": delta_head,
            "transaction": transaction,
            "store": store,
            "evidence": evidence,
            "ledger_path": ledger_path,
            "identity": identity,
            "store_root": store_root,
            "coordinator_root": coordinator_root,
            "fetch_remote": fetch_remote,
            "authority": authority,
            "node_id": node_id,
            "branch": branch,
            "candidate_artifact": candidate_artifact,
        }

    def _readmit_with_broker(self, runner, *args, broker_store, evidence_store, **kwargs):
        """Pass the real broker/evidence pair once the SL-0 callable exposes it.

        The frozen default suite intentionally exercises the pre-capability
        callable, whose signature has no broker parameters.  This bridge keeps
        that compatibility check stable while ensuring every migrated positive
        supplies concrete broker/evidence artifacts as soon as the capability is
        present.
        """
        import inspect

        assert broker_store is not None
        assert evidence_store is not None
        parameters = inspect.signature(runner._fab_delta_readmit).parameters
        if {"broker_store", "evidence_store"} <= set(parameters):
            return runner._fab_delta_readmit(
                *args,
                broker_store=broker_store,
                evidence_store=evidence_store,
                **kwargs,
            )
        return runner._fab_delta_readmit(*args, **kwargs)

    def test_readmit_happy_path_extends_chain_and_commits_ledger(self):
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        seeded = self._setup_broker_readmit_candidate()
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        delta_head = seeded["delta_head"]
        new_admitted = self._readmit_with_broker(
            tr,
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
            delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
            broker_store=seeded["store"], evidence_store=seeded["evidence"],
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

        seeded = self._setup_broker_readmit_candidate()
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        delta_head = seeded["delta_head"]

        # ATTEMPT 1 crashes at the commit point: append_record raises after the
        # provenance overwrite + fsync + gate-verify.
        import phase_loop_runtime.train_runner as _trmod
        real_append = _trmod.append_record
        state = {"crash": True}

        def crashing_append(path, record, **kwargs):
            if state["crash"] and record.status == "pr_open" and record.head_sha == delta_head:
                raise OSError("simulated crash at the ledger commit point")
            return real_append(path, record, **kwargs)

        _trmod.append_record = crashing_append
        try:
            with self.assertRaises(OSError):
                self._readmit_with_broker(
                    tr,
                    self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                    merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                    delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
                    broker_store=seeded["store"], evidence_store=seeded["evidence"],
                )
            # Fail-closed: the ledger still admits the OLD candidate head.
            self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

            # RESUME (attempt 2): the append succeeds → converges to the new head.
            state["crash"] = False
            new_admitted = self._readmit_with_broker(
                tr,
                self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
                broker_store=seeded["store"], evidence_store=seeded["evidence"],
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

        seeded = self._setup_broker_readmit_candidate()
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        c2_head = seeded["delta_head"]

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
                self._readmit_with_broker(
                    tr,
                    self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                    merge_order=0, admitted_head_sha=candidate_head, live_head_sha=c2_head,
                    delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
                    broker_store=seeded["store"], evidence_store=seeded["evidence"],
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
        c2b_head = self._vendor_commit("c2' replacement advance", vendor="Codex")

        # ATTEMPT 2 must CONVERGE (scope-back-at-start recovers the torn state).
        new_admitted = self._readmit_with_broker(
            tr,
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=c2b_head,
            delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
            broker_store=seeded["store"], evidence_store=seeded["evidence"],
        )
        self.assertEqual(new_admitted, c2b_head, "attempt 2 must converge, not brick on the torn state")
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, c2b_head)
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=c2b_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)

    def test_shortcut_engages_for_a_remote_only_advance_via_fetch(self):
        """CR round 5 #2 — the load-bearing REAL use case: the live head comes from
        GitHub's API (a push to the PR from ANOTHER host), so the delta commit is NOT
        in the reviewed workspace. The shortcut must FETCH it before the local
        eligibility rev-list, or it never engages for a remote advance. Here the
        delta commit exists ONLY on the remote (a second clone created + pushed it;
        the reviewed workspace never had it) — the re-admission must still converge,
        proving the fetch, not a locally-created commit (which masked this)."""
        import os
        import subprocess

        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        seeded = self._setup_broker_readmit_candidate()
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        # Drop the LOCAL advance the fixture made — we want a REMOTE-only one.
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)
        # Publish the admitted candidate to the remote (a side ref, leaving
        # fetchsrc/main = base so the gate's base-currency check is unaffected).
        subprocess.run(["git", "-C", str(self.repo), "push", "-q", "-f", "fetchsrc",
                        f"{candidate_head}:refs/heads/cand"], check=True, capture_output=True)

        # A SEPARATE clone creates the delta commit and pushes it ONLY to the remote.
        remote_work = self.repo.parent / "remote_work"
        subprocess.run(["git", "clone", "-q", str(self.origin_dir), str(remote_work)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(remote_work), "checkout", "-q", candidate_head], check=True, capture_output=True)
        (remote_work / "pkg").mkdir(parents=True, exist_ok=True)
        (remote_work / "pkg" / "remote.py").write_text("remote-only advance\n", encoding="utf-8")
        env = {**os.environ,
               "GIT_AUTHOR_NAME": "Codex Agent", "GIT_AUTHOR_EMAIL": "agent@codex.example",
               "GIT_COMMITTER_NAME": "Codex Agent", "GIT_COMMITTER_EMAIL": "agent@codex.example"}
        subprocess.run(["git", "-C", str(remote_work), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(remote_work), "commit", "-m", "remote delta advance"],
                       check=True, capture_output=True, env=env)
        remote_head = subprocess.run(["git", "-C", str(remote_work), "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(remote_work), "push", "-q", "origin", f"{remote_head}:refs/heads/pr"],
                       check=True, capture_output=True)

        # The reviewed workspace does NOT have the remote delta commit locally.
        self.assertNotEqual(
            0,
            subprocess.run(["git", "-C", str(self.repo), "cat-file", "-e", f"{remote_head}^{{commit}}"],
                           capture_output=True).returncode,
            "precondition: the remote-only delta commit must be absent from the reviewed workspace",
        )

        # The re-admission fetches it and converges to the remote head.
        new_admitted = self._readmit_with_broker(
            tr,
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=remote_head,
            delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
            broker_store=seeded["store"], evidence_store=seeded["evidence"],
        )
        self.assertEqual(new_admitted, remote_head, "the shortcut must ENGAGE for a remote-only advance (via fetch)")
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, remote_head)
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=remote_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)

    def test_non_oid_live_head_is_rejected_before_fetch(self):
        """CR round 5 (grok) — `live_head_sha` is validated as a resolved hex OID
        BEFORE `git fetch` shells out, so a flag-leading / ref value can never be
        smuggled to git as an argument (parity with `committed_range_diff`). A
        non-OID value fails closed (→ guard, returns None), never reaching git; the
        admitted head is unchanged."""
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, _advance = self._setup_candidate_and_advance()
        for bad in ("--upload-pack=evil", "refs/heads/main", "HEAD", "", "zzzz"):
            self.assertIsNone(
                tr._fab_delta_readmit(
                    self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                    merge_order=0, admitted_head_sha=candidate_head, live_head_sha=bad,
                    delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
                ),
                f"non-OID live_head_sha {bad!r} must fail closed before any git op",
            )
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

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

        seeded = self._setup_broker_readmit_candidate()
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
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

        new_admitted = self._readmit_with_broker(
            tr,
            self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
            merge_order=0, admitted_head_sha=candidate_head, live_head_sha=gem_head,
            delta_review_fn=capturing_review, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
            broker_store=seeded["store"], evidence_store=seeded["evidence"],
        )
        self.assertEqual(new_admitted, gem_head)
        self.assertIn(
            "gemini", seen["authors"],
            "the delta's OWN author vendor must be passed to the review as an excluded author",
        )

    def test_delta_author_identified_by_email_only(self):
        """CR round 2 B5 — the delta-author extraction reads author/committer EMAIL,
        not just name. A commit whose NAME carries no vendor marker but whose EMAIL
        does (e.g. `codex@openai.com`) is still positively attributed."""
        import os
        import subprocess

        from phase_loop_runtime import train_runner as tr

        _ledger, base, candidate_head, _delta = self._setup_candidate_and_advance()
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)
        self.write("pkg/c.py", "advance attributable by email only\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, capture_output=True)
        env = {**os.environ,
               "GIT_AUTHOR_NAME": "Automation Bot", "GIT_AUTHOR_EMAIL": "codex@openai.com",
               "GIT_COMMITTER_NAME": "Automation Bot", "GIT_COMMITTER_EMAIL": "codex@openai.com"}
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "email-only advance"],
                       check=True, capture_output=True, env=env)
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        self.assertIn("codex", tr._delta_commit_author_vendors(self.repo, candidate_head, head))

    def test_unattributed_delta_author_fails_closed_regardless_of_dispatch(self):
        """CR round 2 B5 — an UNIDENTIFIED delta author fails closed AT the readmit
        boundary, and the historical dispatch set never masks it. A human/non-vendor
        advance (no vendor marker in name/email/trailers) → the boundary returns
        None BEFORE the dispatch union is even consulted, so a nonempty dispatch
        history cannot rescue it into a review that would seat the real (unknown)
        author."""
        import os
        import subprocess

        import phase_loop_runtime.events as _events
        from phase_loop_runtime import train_runner as tr
        from phase_loop_runtime.train_ledger import read_ledger

        ledger_path, base, candidate_head, _delta = self._setup_candidate_and_advance()
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)
        self.write("pkg/c.py", "human out-of-band advance\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, capture_output=True)
        env = {**os.environ,
               "GIT_AUTHOR_NAME": "Jane Human", "GIT_AUTHOR_EMAIL": "jane@example.com",
               "GIT_COMMITTER_NAME": "Jane Human", "GIT_COMMITTER_EMAIL": "jane@example.com"}
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "human advance"],
                       check=True, capture_output=True, env=env)
        human_head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()
        self.assertEqual(frozenset(), tr._delta_commit_author_vendors(self.repo, candidate_head, human_head))

        # Even with a nonempty dispatch history, the unattributed delta fails closed.
        orig = _events.read_events
        _events.read_events = lambda ws: [{"selected_executor": "codex"}]
        try:
            result = tr._fab_delta_readmit(
                self.repo, ledger_path, node_id="n1", run_id=self.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head, live_head_sha=human_head,
                delta_review_fn=self._review_fn, owned_paths=self.OWNED, fab_fetch_origin="fetchsrc",
            )
        finally:
            _events.read_events = orig
        self.assertIsNone(result)
        self.assertEqual(read_ledger(ledger_path)["n1"].head_sha, candidate_head)

    def test_reset_to_admitted_recovers_torn_extended_provenance(self):
        """CR round 2 B1 — reset-to-admitted recovery. A crashed prior attempt left a
        torn EXTENDED provenance (resolves past the admitted head) while the ledger
        still admits the candidate head. The PR is then RESET back to the admitted
        head (live == admitted), so the handled branch is skipped. Without recovery
        the merge re-gate would reject forever; `_fab_recover_torn_to_admitted`
        scopes the durable run store back to the admitted-chain prefix so the node
        converges at the admitted head."""
        import subprocess

        from phase_loop_runtime import fab_provenance as fpmod
        from phase_loop_runtime import train_runner as tr

        ledger_path, base, candidate_head, c2_head = self._setup_candidate_and_advance()

        # ATTEMPT 1 crashes at the fsync of the EXTENDED provenance → torn state.
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
        # Torn: provenance resolves to C2 but the ledger still admits the candidate.
        self.assertEqual(fg.read_provenance(self.repo, self.RUN).delta_chain[-1].delta_head_sha, c2_head)

        # The branch is RESET back to the admitted head (live == admitted).
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)

        # Recovery scopes the torn extended chain back to the admitted prefix.
        tr._fab_recover_torn_to_admitted(self.repo, self.RUN, admitted_head_sha=candidate_head)
        recovered = fg.read_provenance(self.repo, self.RUN)
        self.assertEqual(recovered.delta_chain, (), "torn extended chain must be scoped back to the candidate")
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=candidate_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)

    def test_crash_torn_seat_ledger_tail_is_repaired_by_recovery(self):
        """CR round 3 B1 — a SIGKILL mid seat-append leaves a PARTIAL (newline-less)
        trailing seat record; the STRICT `read_seat_outcomes` then rejects the WHOLE
        ledger, so WITHOUT repair every recovery path bricks (the old `except:
        return` swallowed it). Recovery must repair the torn tail (truncate the
        un-terminated bytes) then scope+converge — the gate PASSES at the admitted
        head and the committed candidate seats survive."""
        import subprocess

        from phase_loop_runtime import fab_gate as fgmod
        from phase_loop_runtime import train_runner as tr

        ledger_path, base, candidate_head, _delta = self._setup_candidate_and_advance()
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)

        seat_path = fgmod.seat_outcomes_path_for_run(self.repo, self.RUN)
        with open(seat_path, "ab") as fh:  # crash mid-append: partial line, no newline
            fh.write(b'{"seat_key": "codex:d:high", "vendor_le')
        # Brick precondition: the strict gate reader rejects the WHOLE ledger.
        with self.assertRaises(fp.ProvenanceInvalid):
            fgmod.read_seat_outcomes(self.repo, self.RUN)

        # Recovery repairs the torn tail and converges (not a brick).
        tr._fab_recover_torn_to_admitted(self.repo, self.RUN, admitted_head_sha=candidate_head)
        seats = fgmod.read_seat_outcomes(self.repo, self.RUN)  # readable again
        self.assertTrue(any(s.epoch == 1 for s in seats), "committed candidate seats must survive the repair")
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=candidate_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)

    def test_crash_mid_recovery_reruns_cleanly(self):
        """CR round 3 B2 — a crash DURING recovery (after stale epochs are scoped,
        before the provenance overwrite lands) must re-run cleanly. Because recovery
        removes stale epochs BEFORE rewriting provenance, the provenance still
        resolves PAST the admitted head, so the next attempt re-detects the torn
        state and converges — never an admitted-looking provenance + stale finalized
        rounds that an early-return would skip forever (false-blocking the gate on
        epoch-set equality)."""
        import subprocess

        from phase_loop_runtime import fab_provenance as fpmod
        from phase_loop_runtime import train_runner as tr

        ledger_path, base, candidate_head, c2_head = self._setup_candidate_and_advance()

        # Build a torn EXTENDED provenance (crash after the extend overwrite).
        real_fsync = fpmod.fsync_run_store_durable
        crashed = {"done": False}

        def crashing_fsync(repo, run_id):
            art = fg.read_provenance(repo, run_id)
            if art.delta_chain and not crashed["done"]:
                crashed["done"] = True
                raise OSError("crash after the extended-provenance overwrite")
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
        subprocess.run(["git", "-C", str(self.repo), "reset", "--hard", candidate_head], check=True, capture_output=True)

        # RECOVERY attempt 1 crashes right after the scope, before the recovered
        # (candidate-only) provenance write lands.
        real_wp = fpmod.write_provenance

        def crashing_wp(repo, run_id, artifact):
            if not artifact.delta_chain:  # the recovered candidate-only write
                raise OSError("crash mid-recovery: after scope, before provenance write")
            return real_wp(repo, run_id, artifact)

        fpmod.write_provenance = crashing_wp
        try:
            with self.assertRaises(OSError):
                tr._fab_recover_torn_to_admitted(self.repo, self.RUN, admitted_head_sha=candidate_head)
        finally:
            fpmod.write_provenance = real_wp
        # Still torn: provenance resolves to C2 (the write didn't land), even though
        # the stale epoch was already scoped.
        self.assertEqual(fg.read_provenance(self.repo, self.RUN).delta_chain[-1].delta_head_sha, c2_head)

        # RECOVERY attempt 2 re-detects the torn state and converges.
        tr._fab_recover_torn_to_admitted(self.repo, self.RUN, admitted_head_sha=candidate_head)
        self.assertEqual(fg.read_provenance(self.repo, self.RUN).delta_chain, ())
        gate = fg.compose_gate_status(
            repo=self.repo, run_id=self.RUN, live_base_ref_name="main", live_head_sha=candidate_head, origin="fetchsrc"
        )
        self.assertEqual(gate.status, fp.GATE_STATUS_PASS, gate.equivalence_verified.reason)


class LedgerTornTailRepairTest(unittest.TestCase):
    """CR round 3 B3 — a crash-torn (newline-less) trailing train-ledger record must
    be REPAIRED before the next append, so a new record never fuses onto the partial
    one into a permanently-unreadable mid-file line (which would also hide the
    re-admission)."""

    def test_torn_trailing_line_is_repaired_before_append(self):
        import tempfile
        from pathlib import Path

        import phase_loop_runtime.train_ledger as tl

        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "train.ledger.jsonl"
            tl.append_record(ledger, tl.LedgerRecord(node_id="n", status="pr_open", head_sha="a" * 40))
            # Crash-torn partial append: a fragment with NO trailing newline.
            with open(ledger, "ab") as fh:
                fh.write(b'{"node_id": "n", "status": "pr_o')
            # The next append must REPAIR the torn tail, not fuse onto it — otherwise
            # the merged record is lost / the ledger becomes permanently unreadable.
            tl.append_record(ledger, tl.LedgerRecord(node_id="n", status="merged", head_sha="b" * 40))
            state = tl.read_ledger(ledger)  # must not raise
            self.assertEqual(state["n"].status, "merged")
            self.assertEqual(state["n"].head_sha, "b" * 40)


class LedgerDurabilityScopingTest(unittest.TestCase):
    """CR round 2 B6 — the train ledger append fsyncs ONLY at the FAB re-admission
    commit point (`durable=True`), never on ordinary appends, so a non-FAB train run
    is behaviour-identical to merged main (which had no fsync). A byte-comparison
    test cannot see this — fsync changes no bytes — so this asserts on the fsync
    CALL count directly."""

    def test_default_append_does_not_fsync_but_durable_does(self):
        import tempfile
        from pathlib import Path

        import phase_loop_runtime.train_ledger as tl

        calls: list = []
        real_fsync = tl.os.fsync
        tl.os.fsync = lambda fd: calls.append(fd)
        try:
            with tempfile.TemporaryDirectory() as d:
                ledger = Path(d) / "train.ledger.jsonl"
                tl.append_record(ledger, tl.LedgerRecord(node_id="n", status="pr_open"))
                self.assertEqual(calls, [], "a default (non-FAB) train append must NOT fsync (byte/behaviour-neutral)")
                tl.append_record(ledger, tl.LedgerRecord(node_id="n", status="merged"), durable=True)
                self.assertEqual(len(calls), 1, "the FAB re-admission commit point (durable=True) must fsync")
        finally:
            tl.os.fsync = real_fsync


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

    def test_torn_material_snapshot_is_repaired_not_trusted(self):
        """CR round 2 B2 — a material snapshot copied non-atomically and never
        repaired bricks recovery: a crash-torn snapshot at the digest-named path
        would make every retry's §6.4 re-verify fail permanently. `snapshot_material`
        must RE-COPY (repair) a destination whose bytes don't match its digest, not
        trust it because the name exists."""
        run_id = "fab-delta-torn-material"
        self.write(fd.BOUNDARY_MANIFEST_PATH, _STRONG_MANIFEST)
        self.commit("c0 base")
        self.push_main()
        bundle = self.repo / "bundle.md"
        bundle.write_text("the reviewed bytes\n", encoding="utf-8")

        digests = fp.snapshot_material(self.repo, run_id, [str(bundle)])
        snap = fp.provenance_dir_for_run(self.repo, run_id) / fp.MATERIAL_SNAPSHOT_DIRNAME / f"{digests[0].sha256}.md"
        self.assertTrue(snap.is_file())

        # Simulate a crash-torn snapshot: the digest-named file exists but its bytes
        # are truncated/garbage. A bare `if not dest.exists()` would trust it.
        snap.write_text("TORN", encoding="utf-8")
        again = fp.snapshot_material(self.repo, run_id, [str(bundle)])
        self.assertEqual(again[0].sha256, digests[0].sha256)
        self.assertEqual(snap.read_text(encoding="utf-8"), "the reviewed bytes\n",
                         "a torn snapshot must be REPAIRED (re-copied), never trusted by name alone")


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


def _scan_append_sites_in_source(source_text: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Inventory every append and classify the durable head-carrying subset."""
    import ast
    tree = ast.parse(source_text)
    all_sites: list[tuple[str, str, str]] = []
    head_sites: list[tuple[str, str, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.fn_stack = []
            # Module bindings are needed for status constants; function bindings
            # shadow them for separately constructed records.
            self.assignments: list[dict[str, ast.expr]] = [{}]
            self.train_ledger_modules: list[set[str]] = [set()]

        def visit_FunctionDef(self, node):
            self.fn_stack.append(node.name)
            self.assignments.append({})
            self.train_ledger_modules.append(set())
            self.generic_visit(node)
            self.train_ledger_modules.pop()
            self.assignments.pop()
            self.fn_stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self.fn_stack.append(node.name)
            self.assignments.append({})
            self.train_ledger_modules.append(set())
            self.generic_visit(node)
            self.train_ledger_modules.pop()
            self.assignments.pop()
            self.fn_stack.pop()

        def visit_ImportFrom(self, node):
            if (node.module or "").endswith("train_ledger"):
                for alias in node.names:
                    if alias.name == "append_record":
                        self.assignments[-1][alias.asname or alias.name] = ast.Name(id="append_record")
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                if alias.name.endswith(".train_ledger") and alias.asname:
                    self.train_ledger_modules[-1].add(alias.asname)
            self.generic_visit(node)

        def visit_Assign(self, node):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.assignments[-1][target.id] = node.value
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            if isinstance(node.target, ast.Name) and node.value is not None:
                self.assignments[-1][node.target.id] = node.value
            self.generic_visit(node)

        def _resolve(self, node, seen=frozenset()):
            if isinstance(node, ast.Name):
                if node.id in seen:
                    return node
                for scope in reversed(self.assignments):
                    value = scope.get(node.id)
                    if value is not None:
                        return self._resolve(value, seen | {node.id})
            return node

        def _literal(self, node) -> str:
            node = self._resolve(node)
            return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ast.unparse(node)

        def _record_shape(self, record_arg) -> tuple[str, str, bool]:
            supplied_as_name = isinstance(record_arg, ast.Name)
            record = self._resolve(record_arg)
            if not (
                isinstance(record, ast.Call)
                and ((isinstance(record.func, ast.Name) and record.func.id == "LedgerRecord")
                     or (isinstance(record.func, ast.Attribute) and record.func.attr == "LedgerRecord"))
            ):
                return ("other", "unknown", False)
            values = {keyword.arg: keyword.value for keyword in record.keywords if keyword.arg}
            for keyword in record.keywords:
                if keyword.arg is None and isinstance(keyword.value, ast.Dict):
                    for key, value in zip(keyword.value.keys, keyword.value.values):
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            values.setdefault(key.value, value)
            status = self._literal(values["status"]) if "status" in values else "missing"
            return ("assigned" if supplied_as_name else "inline", status, "head_sha" in values)

        def _is_append_record_target(self, node) -> bool:
            target = self._resolve(node)
            if isinstance(target, ast.Name):
                return target.id == "append_record"
            if isinstance(target, ast.Attribute) and target.attr == "append_record":
                value = self._resolve(target.value)
                return isinstance(value, ast.Name) and any(
                    value.id in modules for modules in reversed(self.train_ledger_modules)
                )
            return False

        def visit_Call(self, node):
            if self._is_append_record_target(node.func):
                enclosing_fn = self.fn_stack[-1] if self.fn_stack else "global"
                record_arg = None
                if len(node.args) >= 2:
                    record_arg = node.args[1]
                for kw in node.keywords:
                    if kw.arg == "record":
                        record_arg = kw.value
                shape, status, has_head = self._record_shape(record_arg)
                site = (enclosing_fn, shape, status)
                all_sites.append(site)
                if has_head:
                    head_sites.append(site)
            self.generic_visit(node)

    Visitor().visit(tree)
    return all_sites, head_sites


def _assert_head_append_inventory(source_text: str):
    """FR-R8-09: exact head-append shapes, including assigned records/constants."""
    all_sites, head_sites = _scan_append_sites_in_source(source_text)
    from collections import Counter

    expected_head_sites = Counter((
        ("_commit_broker_readmitted_head", "inline", "pr_open"),
        ("_run_train_unfenced", "inline", "pr_open"),
        ("_run_train_unfenced", "assigned", "merged"),
        ("_run_train_unfenced", "inline", "merged"),
    ))
    assert all_sites, "append_record inventory unexpectedly found no append sites"
    assert Counter(head_sites) == expected_head_sites, (
        "unauthorized or malformed head-carrying append sites detected: "
        f"expected={expected_head_sites}, observed={head_sites}"
    )


def test_fabreadmit_commit_points_reach_commit_broker_readmitted_head(request, tmp_path):
    """Commit points reach _commit_broker_readmitted_head during readmission execution."""
    from dataclasses import replace
    import subprocess
    import unittest.mock as _mock
    import pytest
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

    commit_helper = fabreadmit_symbol(
        "phase_loop_runtime.train_runner", "_commit_broker_readmitted_head"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        commit_helper is not None,
        "_commit_broker_readmitted_head missing in phase_loop_runtime.train_runner",
    )

    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.contracts import DeltaReadmitReceipt
    from phase_loop_runtime.train_ledger import read_ledger

    def _receipt_from_call(call):
        args, kwargs = call
        receipts = [
            value
            for value in (*args, *kwargs.values())
            if isinstance(value, DeltaReadmitReceipt)
        ]
        assert len(receipts) == 1, (
            "each durable ledger commit must receive exactly one DeltaReadmitReceipt; "
            f"got {receipts!r}"
        )
        return receipts[0]

    def _assert_receipt_binds_durable_append(call, *, seeded, prior_head, proposed_head, store):
        receipt = _receipt_from_call(call)
        assert receipt.repository == seeded["identity"]
        assert receipt.branch == seeded["branch"]
        assert receipt.prior_head_sha == prior_head
        assert receipt.proposed_head_sha == proposed_head
        durable_record = store.replay()[-1]
        assert durable_record.request.repository == receipt.repository
        assert durable_record.request.branch == receipt.branch
        assert receipt.allocated_epoch == durable_record.epoch
        assert durable_record.binding.prior_head_sha == receipt.prior_head_sha
        assert durable_record.binding.proposed_head_sha == receipt.proposed_head_sha
        assert durable_record.binding.authority_digest == receipt.authority_digest

    # Arm 1: Fresh advance readmission path (FR-R4-04, FR-R5-01, FR-R7-03)
    fixture = DeltaReadmitTransactionTest()
    fixture.tmp_path = tmp_path / "fresh"
    fixture.setUp()
    try:
        seeded = fixture._setup_broker_readmit_candidate()
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        delta_head = seeded["delta_head"]
        store = seeded["store"]
        evidence = seeded["evidence"]
        assert candidate_head == subprocess.check_output(
            ["git", "-C", str(fixture.repo), "rev-parse", "HEAD^"], text=True
        ).strip()

        spy_calls = []
        real_commit = tr._commit_broker_readmitted_head

        def _spy_commit(*args, **kwargs):
            spy_calls.append((args, kwargs))
            return real_commit(*args, **kwargs)

        with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_spy_commit):
            res_fresh = tr._fab_delta_readmit(
                fixture.repo, ledger_path, node_id="n1", run_id=fixture.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head, live_head_sha=delta_head,
                delta_review_fn=fixture._review_fn, owned_paths=fixture.OWNED, fab_fetch_origin="fetchsrc",
                broker_store=store, evidence_store=evidence,
            )

        assert res_fresh == delta_head
        assert len(spy_calls) == 1, "exactly one helper entry in fresh advance arm"
        _assert_receipt_binds_durable_append(
            spy_calls[0],
            seeded=seeded,
            prior_head=candidate_head,
            proposed_head=delta_head,
            store=store,
        )
        assert read_ledger(ledger_path)["n1"].head_sha == delta_head
        assert len(store.replay()) == 2

        # Missing or altered receipts may not authorize a durable ledger append.
        for invalid_name, alter_receipt in (
            ("missing", lambda _receipt: None),
            ("mismatched", lambda receipt: replace(
                receipt, proposed_head_sha=receipt.prior_head_sha
            )),
        ):
            fixture_bad = DeltaReadmitTransactionTest()
            fixture_bad.tmp_path = tmp_path / f"{invalid_name}_receipt"
            fixture_bad.setUp()
            try:
                seeded_bad = fixture_bad._setup_broker_readmit_candidate()
                real_commit_bad = tr._commit_broker_readmitted_head
                append_calls = []

                def _invalid_receipt_commit(*args, **kwargs):
                    changed = False
                    altered_args = []
                    for value in args:
                        if isinstance(value, DeltaReadmitReceipt):
                            altered_args.append(alter_receipt(value))
                            changed = True
                        else:
                            altered_args.append(value)
                    altered_kwargs = {}
                    for key, value in kwargs.items():
                        if isinstance(value, DeltaReadmitReceipt):
                            altered_kwargs[key] = alter_receipt(value)
                            changed = True
                        else:
                            altered_kwargs[key] = value
                    assert changed, "the commit point must receive a DeltaReadmitReceipt"
                    return real_commit_bad(*altered_args, **altered_kwargs)

                real_append_bad = tr.append_record

                def _observe_append(*args, **kwargs):
                    append_calls.append((args, kwargs))
                    return real_append_bad(*args, **kwargs)

                with _mock.patch.object(
                    tr, "_commit_broker_readmitted_head", side_effect=_invalid_receipt_commit
                ), _mock.patch.object(tr, "append_record", side_effect=_observe_append):
                    rejected = tr._fab_delta_readmit(
                        fixture_bad.repo,
                        seeded_bad["ledger_path"],
                        node_id="n1",
                        run_id=fixture_bad.RUN,
                        branch=seeded_bad["branch"],
                        pr_url="u",
                        merge_order=0,
                        admitted_head_sha=seeded_bad["candidate_head"],
                        live_head_sha=seeded_bad["delta_head"],
                        delta_review_fn=fixture_bad._review_fn,
                        owned_paths=fixture_bad.OWNED,
                        fab_fetch_origin="fetchsrc",
                        broker_store=seeded_bad["store"],
                        evidence_store=seeded_bad["evidence"],
                    )

                assert rejected is None
                assert append_calls == [], f"a {invalid_name} receipt must cause zero ledger appends"
                assert (
                    read_ledger(seeded_bad["ledger_path"])["n1"].head_sha
                    == seeded_bad["candidate_head"]
                )
            finally:
                fixture_bad.tearDown()
    finally:
        fixture.tearDown()

    # Arm 2: Crash-resume readmission path (FR-R4-04, FR-R5-01, FR-R7-03)
    fixture2 = DeltaReadmitTransactionTest()
    fixture2.tmp_path = tmp_path / "crash_resume"
    fixture2.setUp()
    try:
        seeded2 = fixture2._setup_broker_readmit_candidate()
        ledger_path2 = seeded2["ledger_path"]
        candidate_head2 = seeded2["candidate_head"]
        delta_head2 = seeded2["delta_head"]
        store2 = seeded2["store"]
        evidence2 = seeded2["evidence"]

        import phase_loop_runtime.train_runner as _trmod
        real_append = _trmod.append_record
        state = {"crash": True}

        def crashing_append(path, record, **kwargs):
            if state["crash"] and record.status == "pr_open" and record.head_sha == delta_head2:
                raise OSError("crash after broker grant before ledger append")
            return real_append(path, record, **kwargs)

        _trmod.append_record = crashing_append
        try:
            with pytest.raises(OSError):
                tr._fab_delta_readmit(
                    fixture2.repo, ledger_path2, node_id="n1", run_id=fixture2.RUN, branch="feat/pr1", pr_url="u",
                    merge_order=0, admitted_head_sha=candidate_head2, live_head_sha=delta_head2,
                    delta_review_fn=fixture2._review_fn, owned_paths=fixture2.OWNED, fab_fetch_origin="fetchsrc",
                    broker_store=store2, evidence_store=evidence2,
                )
        finally:
            _trmod.append_record = real_append

        state["crash"] = False
        spy_calls2 = []
        real_commit2 = tr._commit_broker_readmitted_head

        def _spy_commit2(*args, **kwargs):
            spy_calls2.append((args, kwargs))
            return real_commit2(*args, **kwargs)

        with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_spy_commit2):
            res_resume = tr._fab_delta_readmit(
                fixture2.repo, ledger_path2, node_id="n1", run_id=fixture2.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=candidate_head2, live_head_sha=delta_head2,
                delta_review_fn=fixture2._review_fn, owned_paths=fixture2.OWNED, fab_fetch_origin="fetchsrc",
                broker_store=store2, evidence_store=evidence2,
            )

        assert res_resume == delta_head2
        assert len(spy_calls2) == 1, "exactly one helper entry in crash-resume arm"
        _assert_receipt_binds_durable_append(
            spy_calls2[0],
            seeded=seeded2,
            prior_head=candidate_head2,
            proposed_head=delta_head2,
            store=store2,
        )
        assert read_ledger(ledger_path2)["n1"].head_sha == delta_head2
    finally:
        fixture2.tearDown()


def test_fabreadmit_append_site_inventory(request):
    """AST inventory of head-advancing ledger append sites."""
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

    commit_helper = fabreadmit_symbol(
        "phase_loop_runtime.train_runner", "_commit_broker_readmitted_head"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        commit_helper is not None,
        "_commit_broker_readmitted_head missing in phase_loop_runtime.train_runner",
    )

    train_runner_file = Path(__file__).resolve().parent.parent / "src" / "phase_loop_runtime" / "train_runner.py"
    source = train_runner_file.read_text(encoding="utf-8")
    _assert_head_append_inventory(source)


def test_fabreadmit_append_site_inventory_detects_third_site(request, tmp_path):
    """AST inventory detects third head-advancing append site."""
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

    commit_helper = fabreadmit_symbol(
        "phase_loop_runtime.train_runner", "_commit_broker_readmitted_head"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        commit_helper is not None,
        "_commit_broker_readmitted_head missing in phase_loop_runtime.train_runner",
    )

    train_runner_file = Path(__file__).resolve().parent.parent / "src" / "phase_loop_runtime" / "train_runner.py"
    source = train_runner_file.read_text(encoding="utf-8")

    mutations = (
        # A direct readmission append inside the former catch-all exemption.
        source + "\ndef _run_train_unfenced(ledger_path):\n    append_record(ledger_path, LedgerRecord(node_id='mutated', status='pr_open', head_sha='sha3'))\n",
        # A separately constructed record must not escape the inventory.
        source + "\ndef _extra_unauthorized_append_site(path, nid):\n    record = LedgerRecord(node_id=nid, status='pr_open', head_sha='sha3')\n    append_record(path, record)\n",
        # Nor may a status constant evade the pr_open classification.
        source + "\nOPEN_STATUS = 'pr_open'\ndef _extra_constant_status_append(path, nid):\n    append_record(path, LedgerRecord(node_id=nid, status=OPEN_STATUS, head_sha='sha3'))\n",
        # Nor may a dictionary expansion hide a head-carrying ledger record.
        source + "\ndef _extra_kwargs_head_append(path, nid):\n    append_record(path, LedgerRecord(**{'node_id': nid, 'status': 'pr_open', 'head_sha': 'sha3'}))\n",
        # Nor may direct call-target and import aliases hide a third head append.
        source + (
            "\nfrom phase_loop_runtime.train_ledger import append_record as persisted_append\n"
            "def _extra_aliased_head_append(path, nid):\n"
            "    append_alias = persisted_append\n"
            "    append_alias(path, LedgerRecord(node_id=nid, status='pr_open', head_sha='sha3'))\n"
        ),
    )

    for synthetic_source in mutations:
        with pytest.raises(AssertionError, match=r"unauthorized or malformed"):
            _assert_head_append_inventory(synthetic_source)


def test_fabreadmit_fresh_revocation_blocks_delta_merge(request, tmp_path):
    """Fresh readmission path revocation check blocks delta merge."""
    import os
    import unittest.mock as _mock
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

    chk_symbol = fabreadmit_symbol(
        "phase_loop_runtime.train_runner", "_check_readmission_revocation"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        chk_symbol is not None,
        "_check_readmission_revocation missing in phase_loop_runtime.train_runner",
    )

    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
    from phase_loop_runtime.train_ledger import read_ledger

    fixture = DeltaReadmitTransactionTest()
    fixture.tmp_path = tmp_path / "fresh_positive"
    fixture.setUp()
    try:
        seeded = fixture._setup_broker_readmit_candidate(
            node_id="repo-a/specs/plan-a.md", branch="feat/repo-a"
        )
        ledger_path = seeded["ledger_path"]
        delta_head = seeded["delta_head"]
        store = seeded["store"]
        _seed_fabreadmit_two_node_resume(ledger_path, seeded["candidate_head"])
        captured = {}
        commit_calls = []
        real_commit = tr._commit_broker_readmitted_head

        def _observe_commit(*args, **kwargs):
            commit_calls.append((args, kwargs))
            return real_commit(*args, **kwargs)

        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_observe_commit):
                result = _run_fabreadmit_two_node_resume(
                    tr, fixture, seeded, live_head_sha=delta_head, captured=captured
                )

        assert result["status"] == "merged"
        assert len(commit_calls) == 1, "unrevoked readmission must enter the broker helper once"
        assert captured[seeded["node_id"]] == [{
            "branch": seeded["branch"],
            "head_sha": delta_head,
            "run_id": fixture.RUN,
        }]
        assert read_ledger(ledger_path)[seeded["node_id"]].head_sha == delta_head
        assert len(store.replay()) == 2
    finally:
        fixture.tearDown()

    fixture_revoked = DeltaReadmitTransactionTest()
    fixture_revoked.tmp_path = tmp_path / "fresh_revoked"
    fixture_revoked.setUp()
    try:
        seeded = fixture_revoked._setup_broker_readmit_candidate(
            node_id="repo-a/specs/plan-a.md", branch="feat/repo-a"
        )
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        delta_head = seeded["delta_head"]
        store = seeded["store"]
        evidence = seeded["evidence"]

        evidence.record_intent("rev-key-fresh")
        evidence.record_terminal(EvidenceRecord("rev-key-fresh", TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "revocation"))
        _seed_fabreadmit_two_node_resume(ledger_path, candidate_head)
        ledger_before = ledger_path.read_text(encoding="utf-8")
        admission_before = tuple(store.replay())
        captured = {}
        provider_effects = []
        commit_calls = []
        real_commit = tr._commit_broker_readmitted_head
        revocation_checks = []
        real_revocation_check = tr._check_readmission_revocation

        def _unexpected_provider_effect(*args, **kwargs):
            provider_effects.append((args, kwargs))
            raise AssertionError("revoked readmission must not reach a provider adapter")

        def _observe_commit(*args, **kwargs):
            commit_calls.append((args, kwargs))
            return real_commit(*args, **kwargs)

        def _observe_revocation_check(*args, **kwargs):
            revocation_checks.append((args, kwargs))
            return real_revocation_check(*args, **kwargs)

        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "_check_readmission_revocation", side_effect=_observe_revocation_check):
                with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_observe_commit):
                    with _mock.patch(
                        "phase_loop_runtime.convergence.broker.live.GitHubBrokerAdapter.execute",
                        side_effect=_unexpected_provider_effect,
                    ):
                        result = _run_fabreadmit_two_node_resume(
                            tr, fixture_revoked, seeded, live_head_sha=delta_head, captured=captured
                        )

        assert result["status"] != "merged", "revoked fresh readmission must block the caller merge"
        assert revocation_checks, "revoked fresh readmission must enter the revocation boundary"
        assert commit_calls == [], "revoked fresh readmission must not enter the broker helper"
        assert captured == {}, "revoked fresh readmission must execute zero merges"
        assert provider_effects == [], "revoked fresh readmission must have zero provider-adapter effect"
        assert ledger_path.read_text(encoding="utf-8") == ledger_before, "revocation must append no ledger record"
        assert read_ledger(ledger_path)[seeded["node_id"]].head_sha == candidate_head, "ledger head must remain at candidate_head"
        assert tuple(store.replay()) == admission_before, "admission store must remain unchanged after revocation"
    finally:
        fixture_revoked.tearDown()


def test_fabreadmit_crash_resume_revocation_rechecked_blocks(request, tmp_path):
    """Crash-resume path rechecks revocation and blocks on terminal revocation."""
    import os
    import pytest
    import unittest.mock as _mock
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

    chk_symbol = fabreadmit_symbol(
        "phase_loop_runtime.train_runner", "_check_readmission_revocation"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        chk_symbol is not None,
        "_check_readmission_revocation missing in phase_loop_runtime.train_runner",
    )

    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord
    from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
    from phase_loop_runtime.train_ledger import read_ledger

    fixture = DeltaReadmitTransactionTest()
    fixture.tmp_path = tmp_path
    fixture.setUp()
    try:
        seeded = fixture._setup_broker_readmit_candidate(
            node_id="repo-a/specs/plan-a.md", branch="feat/repo-a"
        )
        ledger_path = seeded["ledger_path"]
        delta_head = seeded["delta_head"]
        store = seeded["store"]
        _seed_fabreadmit_two_node_resume(ledger_path, seeded["candidate_head"])
        real_append = tr.append_record

        def _crash_after_broker_grant(path, record, **kwargs):
            if record.status == "pr_open" and record.node_id == seeded["node_id"] and record.head_sha == delta_head:
                raise SystemExit("simulated crash after broker grant before ledger append")
            return real_append(path, record, **kwargs)

        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "append_record", side_effect=_crash_after_broker_grant):
                with pytest.raises(SystemExit, match="simulated crash"):
                    _run_fabreadmit_two_node_resume(
                        tr, fixture, seeded, live_head_sha=delta_head, captured={}
                    )

        grant_count_before = len(store.replay())
        captured = {}
        commit_calls = []
        real_commit = tr._commit_broker_readmitted_head

        def _observe_commit(*args, **kwargs):
            commit_calls.append((args, kwargs))
            return real_commit(*args, **kwargs)

        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_observe_commit):
                result = _run_fabreadmit_two_node_resume(
                    tr, fixture, seeded, live_head_sha=delta_head, captured=captured
                )
        assert result["status"] == "merged"
        assert len(commit_calls) == 1, "resume must re-enter the broker helper once"
        assert captured[seeded["node_id"]] == [{
            "branch": seeded["branch"],
            "head_sha": delta_head,
            "run_id": fixture.RUN,
        }]
        assert read_ledger(ledger_path)[seeded["node_id"]].head_sha == delta_head
        assert len(store.replay()) == grant_count_before, "resume must deduplicate the prior grant"
    finally:
        fixture.tearDown()

    fixture_revoked = DeltaReadmitTransactionTest()
    fixture_revoked.tmp_path = tmp_path / "revoked_resume"
    fixture_revoked.setUp()
    try:
        seeded = fixture_revoked._setup_broker_readmit_candidate(
            node_id="repo-a/specs/plan-a.md", branch="feat/repo-a"
        )
        ledger_path = seeded["ledger_path"]
        delta_head = seeded["delta_head"]
        store = seeded["store"]
        evidence = seeded["evidence"]
        _seed_fabreadmit_two_node_resume(ledger_path, seeded["candidate_head"])
        real_append = tr.append_record

        def _crash_after_broker_grant(path, record, **kwargs):
            if record.status == "pr_open" and record.node_id == seeded["node_id"] and record.head_sha == delta_head:
                raise SystemExit("simulated crash after broker grant before ledger append")
            return real_append(path, record, **kwargs)

        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "append_record", side_effect=_crash_after_broker_grant):
                with pytest.raises(SystemExit, match="simulated crash"):
                    _run_fabreadmit_two_node_resume(
                        tr, fixture_revoked, seeded, live_head_sha=delta_head, captured={}
                    )

        evidence.record_intent("rev-key-resume")
        evidence.record_terminal(EvidenceRecord(
            "rev-key-resume", TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "revocation"
        ))
        ledger_before = ledger_path.read_text(encoding="utf-8")
        admission_before = tuple(store.replay())
        captured = {}
        provider_effects = []
        commit_calls = []
        real_commit = tr._commit_broker_readmitted_head
        revocation_checks = []
        real_revocation_check = tr._check_readmission_revocation

        def _unexpected_provider_effect(*args, **kwargs):
            provider_effects.append((args, kwargs))
            raise AssertionError("revoked resume must not reach a provider adapter")

        def _observe_commit(*args, **kwargs):
            commit_calls.append((args, kwargs))
            return real_commit(*args, **kwargs)

        def _observe_revocation_check(*args, **kwargs):
            revocation_checks.append((args, kwargs))
            return real_revocation_check(*args, **kwargs)

        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "_check_readmission_revocation", side_effect=_observe_revocation_check):
                with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_observe_commit):
                    with _mock.patch(
                        "phase_loop_runtime.convergence.broker.live.GitHubBrokerAdapter.execute",
                        side_effect=_unexpected_provider_effect,
                    ):
                        result = _run_fabreadmit_two_node_resume(
                            tr, fixture_revoked, seeded, live_head_sha=delta_head, captured=captured
                        )

        assert result["status"] != "merged", "revoked crash-resume must block the caller merge"
        assert revocation_checks, "revoked crash-resume must enter the revocation boundary"
        assert commit_calls == [], "revoked crash-resume must not enter the broker helper"
        assert captured == {}, "revoked crash-resume must execute zero merges"
        assert provider_effects == [], "revoked crash-resume must have zero provider-adapter effect"
        assert ledger_path.read_text(encoding="utf-8") == ledger_before, "revocation must append no ledger record"
        assert tuple(store.replay()) == admission_before, "admission store must remain unchanged after revocation"
    finally:
        fixture_revoked.tearDown()


def test_fabreadmit_real_git_shortcut_end_to_end(request, tmp_path):
    """Real-Git end-to-end delta shortcut with broker readmission."""
    import os
    import unittest.mock as _mock
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

    commit_helper = fabreadmit_symbol(
        "phase_loop_runtime.train_runner", "_commit_broker_readmitted_head"
    )
    fabreadmit_require(
        fabreadmit_this_nodeid(request),
        commit_helper is not None,
        "_commit_broker_readmitted_head missing in phase_loop_runtime.train_runner",
    )

    from phase_loop_runtime import train_runner as tr
    from phase_loop_runtime.train_ledger import read_ledger
    from phase_loop_runtime.train_runner import CoordinatorRuntime
    from phase_loop_runtime.convergence.broker.live import _RepositoryRoutingBrokerService, build_routing_broker_client
    from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
    from phase_loop_runtime.governed_premerge import FAB_PROMOTION_ENV
    from phase_loop_runtime.train_roadmap import parse_train_roadmap

    def _capturing_head_merge_stub(cap: dict, node_for_workspace: dict[Path, str] | None = None):
        def _merge_pr(workspace, branch, base="main", head_sha=None, run_id=None, fab_fetch_origin="origin"):
            node_id = node_for_workspace[Path(workspace)] if node_for_workspace else str(workspace)
            cap.setdefault(node_id, []).append({
                "branch": branch,
                "head_sha": head_sha,
                "run_id": run_id,
            })
            return f"sha-merged-{Path(workspace).name}"
        return _merge_pr

    fixture = DeltaReadmitTransactionTest()
    fixture.tmp_path = tmp_path / "pos"
    fixture.setUp()
    try:
        node_id = "repo-a/specs/plan-a.md"
        seeded = fixture._setup_broker_readmit_candidate(node_id=node_id)
        ledger_path = seeded["ledger_path"]
        candidate_head = seeded["candidate_head"]
        delta_head = seeded["delta_head"]

        routing_client = build_routing_broker_client()
        assert isinstance(routing_client, _RepositoryRoutingBrokerService)

        coord_runtime = CoordinatorRuntime(
            train_id="train1",
            coordinator_root=seeded["coordinator_root"],
            roadmap_path="train.md",
            roadmap_digest="d" * 64,
            workspace_id=str(fixture.repo),
            broker_client=routing_client,
        )

        roadmap = parse_train_roadmap(TRAIN_2NODE_MD)
        repo_b = tmp_path / "pos-repo-b"
        repo_b.mkdir()
        ws_map = {
            "repo-a/specs/plan-a.md": fixture.repo,
            "repo-b/specs/plan-b.md": repo_b,
        }

        captured = {}
        commit_calls = []
        real_commit = tr._commit_broker_readmitted_head

        def _spy_commit(*args, **kwargs):
            commit_calls.append((args, kwargs))
            return real_commit(*args, **kwargs)

        # 1. Positive E2E Arm: production readiness is unpatched; only the master
        # flag enables the otherwise-valid, durable authority path.
        with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
            with _mock.patch.object(tr, "_commit_broker_readmitted_head", side_effect=_spy_commit):
                result = tr.run_train(
                    roadmap,
                    ledger_path,
                    run_mode="governed",
                    resolve_workspace=lambda n: ws_map[n.node_id],
                    coordinator_runtime=coord_runtime,
                    resolve_owned_paths=None,
                    _run_loop=lambda *a, **kw: (None, []),
                    _publish=_make_publish_stub({}),
                    _set_upstream_ref_fn=lambda *a, **kw: [],
                    _preflight_fn=lambda *a, **kw: None,
                    _pr_is_open=lambda ws, br: True,
                    _live_pr_head_sha_fn=lambda ws, br: delta_head,
                    _merge_phase_enabled=True,
                    _reverify_fn=_reverify_pass,
                    _train_review_fn=_approval_review_fn,
                    _pr_merged_sha_fn=lambda *a, **kw: None,
                    _delta_review_fn=fixture._review_fn,
                    _merge_pr_fn=_capturing_head_merge_stub(captured, {
                        fixture.repo: "repo-a/specs/plan-a.md",
                        repo_b: "repo-b/specs/plan-b.md",
                    }),
                    fab_fetch_origin="fetchsrc",
                    fab_delta_shortcut=True,
                )

        assert result["status"] == "merged"
        assert len(commit_calls) == 1, "shortcut helper entry must occur exactly once"
        rec = read_ledger(ledger_path)["repo-a/specs/plan-a.md"]
        assert rec.head_sha == delta_head, "ledger must advance to exact admitted delta head"
        assert captured["repo-a/specs/plan-a.md"] == [{
            "branch": seeded["branch"],
            "head_sha": delta_head,
            "run_id": fixture.RUN,
        }], "repo-a merge must receive exact delta_head without a later-node overwrite"

        gate_res = fg.compose_gate_status(
            repo=fixture.repo, run_id=fixture.RUN, live_base_ref_name="main", live_head_sha=delta_head, origin="fetchsrc"
        )
        assert gate_res.status == fp.GATE_STATUS_PASS
        admission_store = LinearizableAdmissionStore(seeded["store_root"], lambda _: True)
        replayed = admission_store.replay()
        assert len(replayed) == 2, "admission store must hold publish + readmission records"
        assert replayed[-1].epoch == 2

        # 2. Readiness kill: this is otherwise the same valid fixture and call
        # shape as the positive arm; only the readiness conjunct is false.
        fix_a = DeltaReadmitTransactionTest()
        fix_a.tmp_path = tmp_path / "arm_a"
        fix_a.setUp()
        try:
            seeded_a = fix_a._setup_broker_readmit_candidate(node_id=node_id)
            ledger_a = seeded_a["ledger_path"]
            cand_a = seeded_a["candidate_head"]
            delta_a = seeded_a["delta_head"]
            runtime_a = CoordinatorRuntime(
                train_id="train1", coordinator_root=seeded_a["coordinator_root"],
                roadmap_path="train.md", roadmap_digest="d" * 64,
                workspace_id=str(fix_a.repo), broker_client=build_routing_broker_client(),
            )
            captured_a = {}
            commit_calls_a = []

            def _observe_readiness_kill_commit(*args, **kwargs):
                commit_calls_a.append((args, kwargs))
                return real_commit(*args, **kwargs)

            with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
                with _mock.patch("phase_loop_runtime.governed_premerge._FAB_DELTA_BROKER_READMIT_READY", False):
                    with _mock.patch.object(
                        tr, "_commit_broker_readmitted_head", side_effect=_observe_readiness_kill_commit
                    ):
                        result_a = tr.run_train(
                            roadmap, ledger_a, run_mode="governed",
                            resolve_workspace=lambda n: fix_a.repo,
                            coordinator_runtime=runtime_a,
                            resolve_owned_paths=None,
                            _run_loop=lambda *a, **kw: (None, []),
                            _publish=_make_publish_stub({}),
                            _set_upstream_ref_fn=lambda *a, **kw: [],
                            _preflight_fn=lambda *a, **kw: None,
                            _pr_is_open=lambda ws, br: True,
                            _live_pr_head_sha_fn=lambda ws, br: delta_a,
                            _merge_phase_enabled=True,
                            _reverify_fn=_reverify_pass,
                            _train_review_fn=_approval_review_fn,
                            _pr_merged_sha_fn=lambda *a, **kw: None,
                            _delta_review_fn=fix_a._review_fn,
                            _merge_pr_fn=_capturing_head_merge_stub(captured_a),
                            fab_fetch_origin="fetchsrc",
                            fab_delta_shortcut=True,
                        )
            assert result_a["status"] == "merged"
            assert commit_calls_a == [], "readiness kill must not enter the broker helper"
            assert read_ledger(ledger_a)[node_id].head_sha == delta_a
            assert len(LinearizableAdmissionStore(seeded_a["store_root"], lambda _: True).replay()) == 1, (
                "readiness kill must retain only the candidate admission"
            )
            assert captured_a[str(fix_a.repo)][0]["head_sha"] == cand_a
        finally:
            fix_a.tearDown()

        # 3. Resolver kill: only injected resolver authority differs.  Its
        # covering superset includes both the candidate and actual delta paths.
        fix_b = DeltaReadmitTransactionTest()
        fix_b.tmp_path = tmp_path / "arm_b"
        fix_b.setUp()
        try:
            seeded_b = fix_b._setup_broker_readmit_candidate(node_id=node_id)
            ledger_b = seeded_b["ledger_path"]
            cand_b = seeded_b["candidate_head"]
            delta_b = seeded_b["delta_head"]
            runtime_b = CoordinatorRuntime(
                train_id="train1", coordinator_root=seeded_b["coordinator_root"],
                roadmap_path="train.md", roadmap_digest="d" * 64,
                workspace_id=str(fix_b.repo), broker_client=build_routing_broker_client(),
            )
            captured_b = {}
            commit_calls_b = []

            def _observe_resolver_kill_commit(*args, **kwargs):
                commit_calls_b.append((args, kwargs))
                return real_commit(*args, **kwargs)

            with _mock.patch.dict(os.environ, {FAB_PROMOTION_ENV: "1"}):
                with _mock.patch.object(
                    tr, "_commit_broker_readmitted_head", side_effect=_observe_resolver_kill_commit
                ):
                    result_b = tr.run_train(
                        roadmap, ledger_b, run_mode="governed",
                        resolve_workspace=lambda n: fix_b.repo,
                        coordinator_runtime=runtime_b,
                        resolve_owned_paths=lambda _n: ("pkg/a.py", "pkg/c.py"),
                        _run_loop=lambda *a, **kw: (None, []),
                        _publish=_make_publish_stub({}),
                        _set_upstream_ref_fn=lambda *a, **kw: [],
                        _preflight_fn=lambda *a, **kw: None,
                        _pr_is_open=lambda ws, br: True,
                        _live_pr_head_sha_fn=lambda ws, br: delta_b,
                        _merge_phase_enabled=True,
                        _reverify_fn=_reverify_pass,
                        _train_review_fn=_approval_review_fn,
                        _pr_merged_sha_fn=lambda *a, **kw: None,
                        _delta_review_fn=fix_b._review_fn,
                        _merge_pr_fn=_capturing_head_merge_stub(captured_b),
                        fab_fetch_origin="fetchsrc",
                        fab_delta_shortcut=True,
                    )
            assert result_b["status"] == "merged"
            assert commit_calls_b == [], "resolver kill must not enter the broker helper"
            assert read_ledger(ledger_b)[node_id].head_sha == delta_b
            assert len(LinearizableAdmissionStore(seeded_b["store_root"], lambda _: True).replay()) == 1, (
                "resolver kill must retain only the candidate admission"
            )
            assert captured_b[str(fix_b.repo)][0]["head_sha"] == cand_b
        finally:
            fix_b.tearDown()

        # 4. FR-R3-04 & FR-R3-06 Kill arm (c): Broker bypass -> direct readmit without broker fails closed
        fix_c = DeltaReadmitTransactionTest()
        fix_c.tmp_path = tmp_path / "arm_c"
        fix_c.setUp()
        try:
            seeded_c = fix_c._setup_broker_readmit_candidate()
            ledger_c = seeded_c["ledger_path"]
            cand_c = seeded_c["candidate_head"]
            delta_c = seeded_c["delta_head"]

            res_c = tr._fab_delta_readmit(
                fix_c.repo, ledger_c, node_id="n1", run_id=fix_c.RUN, branch="feat/pr1", pr_url="u",
                merge_order=0, admitted_head_sha=cand_c, live_head_sha=delta_c,
                delta_review_fn=fix_c._review_fn, owned_paths=fix_c.OWNED, fab_fetch_origin="fetchsrc",
                broker_store=None,
            )
            assert res_c is None
            assert read_ledger(ledger_c)["n1"].head_sha == cand_c
        finally:
            fix_c.tearDown()
    finally:
        fixture.tearDown()
