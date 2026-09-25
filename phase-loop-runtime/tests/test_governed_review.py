"""model-routing-v1 P2 — governed planning gate (IF-0-P2-1)."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import execfind_content_tdd_adapter as execfind_tdd
import phase_loop_runtime.governed_review as governed_review
import phase_loop_runtime.panel_invoker as panel_invoker

from phase_loop_runtime.closeout_validators import CloseoutContext
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
from phase_loop_runtime.advisor_board.schema import Board
from phase_loop_runtime.governed_review import (
    author_vendor_for_executor,
    governed_planning_gate,
    resolve_run_mode,
    select_reviewer_pool,
)
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult
from test_execfind_falsifier import _advance_source_head, _falsifier_text, _source_repo


def _panel(*legs):
    return PanelResult(legs=tuple(legs))


def _execfind_gate(repo, head, *, diff=None):
    golden = json.loads((
        Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"
    ).read_text(encoding="utf-8"))
    entry = golden["attachment"]["falsifiers"][0]
    board = Board(name="execfind-test", purpose="code-review", seats=DEFAULT_SEATS[:3])
    panel = PanelResult((
        PanelLegResult("codex", "OK", "Reviewed.\nAGREE"),
        PanelLegResult("gemini", "OK", "Reviewed.\nAGREE"),
        PanelLegResult(
            "claude", "OK", _falsifier_text(entry, diff=diff),
            seat_key=golden["record"]["seat_key"],
        ),
    ))
    return governed_review.governed_board_gate(
        artifact="Review the exact committed head.",
        author_executor="train-coordinator", run_mode="governed", reviewed_sha=head,
        canonical_repo_authority=repo, compose=lambda: board,
        invoke=lambda _board, _artifact, **_kwargs: panel,
    )


def _count_gate(repo, head, counts):
    golden = json.loads((
        Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"
    ).read_text(encoding="utf-8"))
    seed = golden["attachment"]["falsifiers"][0]
    board = Board(name="execfind-count", purpose="code-review", seats=DEFAULT_SEATS)
    legs = []
    next_id = 1
    for seat, count in zip(board.seats, counts):
        blocks = []
        for _ in range(count):
            finding_id = f"F{next_id:03}"
            path = seed["new_test_path"].replace("F001", finding_id)
            diff = seed["diff"].replace("F001", finding_id)
            blocks.append(
                f"FINDING {finding_id}: BLOCKING — reproduction\n"
                f"```falsifier\nnodeid: {path}::test_trigger\n{diff}```\n"
            )
            next_id += 1
        text = "".join(blocks) + ("DISAGREE\n" if count else "AGREE\n")
        legs.append(PanelLegResult(
            seat.harness, "OK", text,
            seat_key=f"{seat.harness}:{seat.model}:{seat.effort}:{seat.lens}",
        ))
    panel = PanelResult(tuple(legs))
    return governed_review.governed_board_gate(
        artifact="Review the exact committed head.",
        author_executor="train-coordinator", run_mode="governed", reviewed_sha=head,
        canonical_repo_authority=repo, compose=lambda: board,
        invoke=lambda _board, _artifact, **_kwargs: panel,
    )


class RunModeTest(unittest.TestCase):
    def test_default_is_autonomous(self):
        self.assertEqual(resolve_run_mode({}), "autonomous")
        self.assertEqual(resolve_run_mode({"PHASE_LOOP_RUN_MODE": "governed"}), "governed")
        self.assertEqual(resolve_run_mode({"PHASE_LOOP_RUN_MODE": "nonsense"}), "autonomous")
        self.assertEqual(resolve_run_mode({}, explicit="governed"), "governed")

    def test_closeout_context_run_mode_defaults_autonomous(self):
        ctx = CloseoutContext(phase_alias="P", plan_path="p.md")
        self.assertEqual(ctx.run_mode, "autonomous")


class AutonomousShortCircuitTest(unittest.TestCase):
    def test_autonomous_makes_zero_panel_calls(self):
        invoke = Mock()  # if this is ever called, the guarantee is broken
        result = governed_planning_gate(
            artifact="ART", author_executor="claude", run_mode="autonomous", invoke=invoke,
        )
        invoke.assert_not_called()           # ZERO panel calls — stronger than "no human_required"
        self.assertFalse(result.ran)
        self.assertTrue(result.promoted)
        self.assertEqual(result.findings, ())


class GovernedGateTest(unittest.TestCase):
    def test_block_finding_holds_promotion(self):
        invoke = lambda art, pool, spawn=None: _panel(
            PanelLegResult(leg="codex", status="ok", text="DISAGREE — has a real bug"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
        )
        result = governed_planning_gate(
            artifact="ART", author_executor="claude", run_mode="governed",
            available_legs=("codex", "gemini"), invoke=invoke,
        )
        self.assertTrue(result.ran)
        self.assertFalse(result.promoted)     # an unresolved block holds promotion
        self.assertTrue(any(f.severity == "block" for f in result.findings))

    def test_no_block_promotes_with_nits_recorded(self):
        invoke = lambda art, pool, spawn=None: _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE, minor notes"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
        )
        result = governed_planning_gate(
            artifact="ART", author_executor="claude", run_mode="governed",
            available_legs=("codex", "gemini"), invoke=invoke,
        )
        self.assertTrue(result.promoted)
        self.assertTrue(result.findings)      # nits recorded (warn), non-gating
        self.assertTrue(all(f.severity == "warn" for f in result.findings))

    def test_repo_dir_is_forwarded_to_panel_invoker(self):
        captured = {}

        def invoke(artifact, pool, **kwargs):
            captured["artifact"] = artifact
            captured["pool"] = pool
            captured["kwargs"] = kwargs
            return _panel(PanelLegResult(leg="codex", status="ok", text="AGREE"))

        result = governed_planning_gate(
            artifact="ART",
            author_executor="claude",
            run_mode="governed",
            available_legs=("codex",),
            invoke=invoke,
            repo_dir="/tmp/repo-under-review",
        )

        self.assertTrue(result.promoted)
        self.assertEqual(captured["artifact"], "ART")
        self.assertEqual(captured["pool"], ("codex",))
        self.assertEqual(captured["kwargs"]["repo_dir"], "/tmp/repo-under-review")

    def test_deferred_claude_leg_is_a_warn_never_a_block(self):
        # #92 A6.4: a claude leg that returns ("UNAVAILABLE", "") records a
        # non-gating panel_leg_degraded WARN naming the claude leg, introduces NO
        # block, and the gate promotes on the two real legs' verdicts.
        invoke = lambda art, pool, spawn=None: _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
            PanelLegResult(leg="claude", status="UNAVAILABLE", text=""),
        )
        result = governed_planning_gate(
            artifact="ART", author_executor="pi", run_mode="governed",
            available_legs=("codex", "gemini", "claude"), invoke=invoke,
        )
        self.assertTrue(result.promoted)  # promotes on the two real AGREEs
        degraded = [f for f in result.findings if f.code == "panel_leg_degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertEqual(degraded[0].severity, "warn")
        self.assertIn("claude", degraded[0].reason)  # names the deferred leg
        self.assertFalse(any(f.severity == "block" for f in result.findings))

    def test_deferred_leg_does_not_mask_a_real_disagree(self):
        # The gate's promote/hold decision is driven only by the real legs: a
        # DISAGREE on codex still blocks even while the claude leg is deferred.
        invoke = lambda art, pool, spawn=None: _panel(
            PanelLegResult(leg="codex", status="ok", text="DISAGREE — real bug"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
            PanelLegResult(leg="claude", status="UNAVAILABLE", text=""),
        )
        result = governed_planning_gate(
            artifact="ART", author_executor="pi", run_mode="governed",
            available_legs=("codex", "gemini", "claude"), invoke=invoke,
        )
        self.assertFalse(result.promoted)
        self.assertTrue(any(f.severity == "block" for f in result.findings))

    def test_rejected_reason_as_text_would_block(self):
        # NEGATIVE GUARD (#92 A4): returning the deferred REASON as leg text (the
        # rejected design) yields a panel_nonconforming BLOCK — proving why the
        # implementation must return EMPTY text instead.
        invoke = lambda art, pool, spawn=None: _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
            PanelLegResult(
                leg="claude", status="UNAVAILABLE",
                text="claude leg not run by the runtime in this execution context",
            ),
        )
        result = governed_planning_gate(
            artifact="ART", author_executor="pi", run_mode="governed",
            available_legs=("codex", "gemini", "claude"), invoke=invoke,
        )
        self.assertFalse(result.promoted)  # reason-as-text over-blocks
        self.assertTrue(any(
            f.code == "panel_nonconforming" and f.severity == "block"
            for f in result.findings
        ))


class ReviewerPoolTest(unittest.TestCase):
    def test_pool_excludes_author_vendor(self):
        pool, reason = select_reviewer_pool("claude", ("codex", "gemini", "claude"))
        self.assertEqual(set(pool), {"codex", "gemini"})
        self.assertIsNone(reason)

    def test_author_vendor_only_degrades(self):
        pool, reason = select_reviewer_pool("claude", ("claude",))
        self.assertEqual(pool, ())
        self.assertEqual(reason, "author_vendor_only")

    def test_zero_authed_degrades(self):
        pool, reason = select_reviewer_pool("claude", ())
        self.assertEqual(reason, "no_reviewers")

    def test_author_vendor_mapping(self):
        self.assertEqual(author_vendor_for_executor("opencode"), "codex")
        self.assertEqual(author_vendor_for_executor("pi"), "pi")
        self.assertEqual(author_vendor_for_executor("claude"), "claude")

    def test_no_disjoint_reviewer_blocks_fail_closed(self):
        # FAIL-CLOSED (advisor-panel reconciliation): when the only authed leg is the
        # author's own vendor, governed mode HOLDS (non-human review_gate_block)
        # rather than advisory-passing a review that never happened. No self-review
        # is spawned, and the result is NOT a silent promote.
        invoke = Mock()
        result = governed_planning_gate(
            artifact="ART", author_executor="claude", run_mode="governed",
            available_legs=("claude",), invoke=invoke,  # only author vendor authed
        )
        invoke.assert_not_called()            # no self-review spawned
        self.assertTrue(result.ran)
        self.assertFalse(result.promoted)     # held, not advisory-passed
        self.assertFalse(result.degraded)
        self.assertEqual(result.reason, "author_vendor_only")
        self.assertTrue(any(f.severity == "block" for f in result.findings))


class VerdictClassifierTest(unittest.TestCase):
    # Advisor-panel reconciliation: a usable leg ENDS with a structured verdict;
    # `_leg_blocks` is a pure read of that terminal verdict (only a leading
    # DISAGREE blocks) — no substring/negation guessing.
    def test_approving_phrasings_do_not_block(self):
        from phase_loop_runtime.governed_review import _leg_blocks
        self.assertFalse(_leg_blocks("Some real concern.\nAGREE"))
        self.assertFalse(_leg_blocks("Minor nits only.\nPARTIALLY AGREE"))
        # last line not a verdict → non-conforming → not a block here (caught
        # upstream as `degraded`/unusable by _classify_leg).
        self.assertFalse(_leg_blocks("I cannot AGREE or DISAGREE without more context"))
        self.assertFalse(_leg_blocks("no blockers"))

    def test_real_block_verdicts_block(self):
        from phase_loop_runtime.governed_review import _leg_blocks
        self.assertTrue(_leg_blocks("The schema is unsafe.\nDISAGREE"))
        self.assertTrue(_leg_blocks("DISAGREE — the migration drops a column"))
        # A "BLOCK:" line that is NOT a terminal verdict is non-conforming, not a
        # block at this layer (fail-closed as unusable upstream, never a pass).
        self.assertFalse(_leg_blocks("BLOCK: the migration drops a column"))


class ExecfindFindingTests(unittest.TestCase):
    def test_falsifier_count_bound(self):
        def check():
            module = execfind_tdd.require_module("phase_loop_runtime.falsifier")
            result_type = execfind_tdd.require_attr(module, "FalsifierRunResult")
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            seen = []

            def run(*, falsifier, seat_key, authorization, repo, wall_clock_s,
                    output_cap_bytes):
                seen.append((seat_key, falsifier.finding_id, falsifier.expected_nodeid))
                digest = hashlib.sha256(falsifier.diff.encode("utf-8")).hexdigest()
                record = {
                    "schema": "finding_falsifier.v1",
                    "authorization_identity": "public_board_falsifier.v1",
                    "seat_key": seat_key,
                    "reviewed_sha": authorization.reviewed_sha,
                    "finding_id": falsifier.finding_id,
                    "nodeid": falsifier.expected_nodeid,
                    "outcome": "green_on_head",
                    "red_output_digest": None,
                    "diff_digest": digest,
                    "wall_clock_bound_s": float(wall_clock_s),
                    "output_cap_bytes": int(output_cap_bytes),
                }
                return result_type(
                    outcome="green_on_head", nodeid=falsifier.expected_nodeid,
                    red_output_digest=None, diff_digest=digest, junit_path=None,
                    detail=None, record=record,
                )

            with tempfile.TemporaryDirectory(prefix="execfind-count-") as root:
                repo, head = _source_repo(Path(root))
                with patch.object(module, "run_finding_falsifier", run), patch.object(
                    governed_review, "run_finding_falsifier", run, create=True,
                ):
                    for counts in ((5, 0, 0, 0), (4, 4, 4, 1)):
                        seen.clear()
                        gate = _count_gate(repo, head, counts)
                        self.assertTrue(gate.ran and not gate.promoted, gate)
                        self.assertEqual(seen, [], counts)
                    for counts in ((4, 0, 0, 0), (4, 4, 4, 0)):
                        seen.clear()
                        gate = _count_gate(repo, head, counts)
                        self.assertTrue(gate.ran, gate)
                        self.assertEqual(len(seen), sum(counts), counts)
                        self.assertEqual(
                            len({(seat, finding) for seat, finding, _node in seen}),
                            sum(counts), counts,
                        )

        execfind_tdd.run_execfind_contract("falsifier_count_bound", check)

    def test_red_receipt_requires_ruling(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            with tempfile.TemporaryDirectory(prefix="execfind-bound-") as root:
                repo, head = _source_repo(Path(root))
                gate = _execfind_gate(repo, head)
            self.assertFalse(gate.promoted)
            self.assertTrue(any(
                f.code == "finding_receipt" and f.severity == "block"
                and f.reviewed_sha == head
                and "observed_outcome=red_on_head" in f.reason
                and "record_digest=" in f.reason
                and "record_digest=unresolved" not in f.reason
                for f in gate.findings
            ), gate.findings)
            self.assertFalse(any(
                f.code in ("finding_bound", "finding_unbound") for f in gate.findings
            ), gate.findings)
            self.assertFalse(any(f.code == "panel_block" for f in gate.findings))

        execfind_tdd.run_execfind_contract("red_receipt_requires_ruling", check)

    def test_finding_reviewed_sha_mismatch(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            with tempfile.TemporaryDirectory(prefix="execfind-sha-drift-") as root:
                repo, reviewed_sha = _source_repo(Path(root))
                self.assertNotEqual(_advance_source_head(repo), reviewed_sha)
                gate = _execfind_gate(repo, reviewed_sha)
            self.assertTrue(gate.ran and not gate.promoted, gate)
            self.assertFalse(any(f.code == "finding_bound" for f in gate.findings), gate.findings)
            self.assertTrue(any(
                f.code == "finding_receipt" and f.severity == "block"
                and "record_digest=" in f.reason and "record_digest=unresolved" not in f.reason
                for f in gate.findings
            ), gate.findings)

        execfind_tdd.run_execfind_contract("finding_reviewed_sha_mismatch", check)

    def test_green_receipt_requires_ruling(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            with tempfile.TemporaryDirectory(prefix="execfind-unbound-") as root:
                repo, head = _source_repo(Path(root))
                diff = json.loads((
                    Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"
                ).read_text(encoding="utf-8"))["attachment"]["falsifiers"][0]["diff"]
                gate = _execfind_gate(repo, head, diff=diff.replace("assert False", "assert True"))
            self.assertFalse(gate.promoted)
            self.assertTrue(any(
                f.code == "finding_receipt" and f.severity == "block"
                and f.reviewed_sha == head
                and "observed_outcome=green_on_head" in f.reason
                and "record_digest=" in f.reason
                and "record_digest=unresolved" not in f.reason
                for f in gate.findings
            ), gate.findings)
            self.assertFalse(any(
                f.code in ("finding_bound", "finding_unbound") for f in gate.findings
            ), gate.findings)
            self.assertFalse(any(f.code == "panel_block" for f in gate.findings))

        execfind_tdd.run_execfind_contract("green_receipt_requires_ruling", check)

    def test_finding_prose(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            leg = PanelLegResult(
                "claude", "OK", "FINDING F001: BLOCKING — prose concern\nDISAGREE",
                seat_key="claude:claude-opus-5-5:max:correctness",
            )
            findings = governed_review._findings_from_panel(
                PanelResult((leg,)), reviewed_sha="1" * 40,
                falsifier_runs={}, falsifier_policy="optional",
            )
            self.assertTrue(any(
                f.code == "finding_prose" and f.severity == "warn"
                and f.body == leg.text and f.reviewed_sha == "1" * 40
                for f in findings
            ), findings)
            self.assertFalse(any(f.code == "panel_block" for f in findings), findings)

        execfind_tdd.run_execfind_contract("finding_prose", check)

    def test_degraded_leg_whole_code(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            leg = PanelLegResult("claude", "DEGRADED", "", detail="EgressUnavailable")
            findings = governed_review._findings_from_panel(
                PanelResult((leg,)), reviewed_sha="1" * 40,
                falsifier_runs={}, falsifier_policy="optional",
            )
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].code, "panel_leg_degraded")
            self.assertEqual(findings[0].severity, "warn")
            self.assertIn("EgressUnavailable", findings[0].reason)

        execfind_tdd.run_execfind_contract("degraded_leg_whole_code", check)

    def test_falsifier_policy_optional(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            leg = PanelLegResult(
                "claude", "OK", "FINDING F001: BLOCKING — prose concern\nDISAGREE",
                seat_key="claude:claude-opus-5-5:max:correctness",
            )
            findings = governed_review._findings_from_panel(
                PanelResult((leg,)), reviewed_sha="1" * 40,
                falsifier_runs={}, falsifier_policy="optional",
            )
            self.assertTrue(any(
                f.code == "finding_prose" and f.severity == "warn" for f in findings
            ), findings)
            self.assertFalse(any(f.severity == "block" for f in findings), findings)

        execfind_tdd.run_execfind_contract("falsifier_policy_optional", check)

    def test_falsifier_policy_required_refuses_prose(self):
        def check():
            execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            leg = PanelLegResult(
                "claude", "OK", "FINDING F001: BLOCKING — prose concern\nDISAGREE",
                seat_key="claude:claude-opus-5-5:max:correctness",
            )
            findings = governed_review._findings_from_panel(
                PanelResult((leg,)), reviewed_sha="1" * 40,
                falsifier_runs={}, falsifier_policy="required",
            )
            self.assertTrue(any(
                f.code == "finding_prose" and f.severity == "block" for f in findings
            ), findings)
            self.assertFalse(any(f.code == "finding_bound" for f in findings), findings)

        execfind_tdd.run_execfind_contract("falsifier_policy_required_refuses_prose", check)

    def test_finding_receipt(self):
        def check():
            golden = json.loads((
                Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"
            ).read_text())
            entry = golden["attachment"]["falsifiers"][0]
            source_record = golden["record"]
            falsifier = execfind_tdd.require_attr(panel_invoker, "FindingFalsifier")(**entry)
            attachment = execfind_tdd.require_attr(
                panel_invoker, "FindingFalsifierAttachment"
            )((falsifier,))
            leg = PanelLegResult(
                "claude", "OK", "FINDING F001: BLOCKING — repro\nDISAGREE",
                seat_key=source_record["seat_key"],
            )
            execfind_tdd.require_attr(panel_invoker, "attach_finding_falsifiers")(
                leg, attachment,
            )
            panel = PanelResult((leg,))
            result_type = execfind_tdd.require_attr(
                execfind_tdd.require_module("phase_loop_runtime.falsifier"),
                "FalsifierRunResult",
            )
            binding_type = execfind_tdd.require_attr(governed_review, "FalsifierRunBinding")
            reduce_findings = execfind_tdd.require_attr(
                governed_review, "_findings_from_panel"
            )
            key = (source_record["seat_key"], source_record["finding_id"])
            for outcome in ("apply_failed", "node_missing", "error"):
                record = {**source_record, "outcome": outcome, "red_output_digest": None}
                digest = hashlib.sha256(json.dumps(
                    record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                ).encode("utf-8")).hexdigest()
                result = result_type(
                    outcome=outcome, nodeid=record["nodeid"],
                    red_output_digest=None, diff_digest=record["diff_digest"],
                    junit_path=None, detail=None, record=record,
                )
                binding = binding_type(
                    seat_key=key[0], finding_id=key[1],
                    reviewed_sha=record["reviewed_sha"], result=result,
                    record_digest=digest,
                )
                findings = reduce_findings(
                    panel, reviewed_sha=record["reviewed_sha"],
                    falsifier_runs={key: binding},
                )
                self.assertTrue(any(
                    f.code == "finding_receipt" and f.severity == "block"
                    and f"observed_outcome={outcome}" in f.reason
                    and f"record_digest={digest}" in f.reason
                    and f.body == leg.text
                    for f in findings
                ), (outcome, findings))
                self.assertFalse(any(
                    f.code in ("finding_bound", "finding_unbound") for f in findings
                ), (outcome, findings))

        execfind_tdd.run_execfind_contract("finding_receipt", check)

    def test_finding_receipt_digest_unresolved(self):
        def check():
            golden = json.loads((
                Path(__file__).parent / "data/execfind_falsifier_attachment_v1.golden.json"
            ).read_text())
            entry = golden["attachment"]["falsifiers"][0]
            record = golden["record"]
            falsifier = execfind_tdd.require_attr(panel_invoker, "FindingFalsifier")(**entry)
            attachment = execfind_tdd.require_attr(
                panel_invoker, "FindingFalsifierAttachment"
            )((falsifier,))
            leg = PanelLegResult(
                "claude", "OK", "FINDING F001: BLOCKING — repro\nDISAGREE",
                seat_key=record["seat_key"],
            )
            execfind_tdd.require_attr(panel_invoker, "attach_finding_falsifiers")(
                leg, attachment,
            )
            panel = PanelResult((leg,))
            result_type = execfind_tdd.require_attr(
                execfind_tdd.require_module("phase_loop_runtime.falsifier"),
                "FalsifierRunResult",
            )
            binding_type = execfind_tdd.require_attr(
                governed_review, "FalsifierRunBinding"
            )
            reduce_findings = execfind_tdd.require_attr(
                governed_review, "_findings_from_panel"
            )
            key = (record["seat_key"], record["finding_id"])

            for outcome in ("red_on_head", "green_on_head"):
                expected = dict(record)
                expected["outcome"] = outcome
                if outcome == "green_on_head":
                    expected["red_output_digest"] = None

                def binding(changed_record=None, **overrides):
                    actual = dict(expected if changed_record is None else changed_record)
                    result = result_type(
                        outcome=overrides.pop("outcome", actual["outcome"]),
                        nodeid=overrides.pop("nodeid", actual["nodeid"]),
                        red_output_digest=overrides.pop(
                            "red_output_digest", actual["red_output_digest"]
                        ),
                        diff_digest=overrides.pop("diff_digest", actual["diff_digest"]),
                        junit_path=None, detail=None, record=actual,
                    )
                    digest = hashlib.sha256(json.dumps(
                        actual, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                    ).encode("utf-8")).hexdigest()
                    return binding_type(
                        seat_key=overrides.pop("seat_key", key[0]),
                        finding_id=overrides.pop("finding_id", key[1]),
                        reviewed_sha=overrides.pop("reviewed_sha", record["reviewed_sha"]),
                        result=result,
                        record_digest=overrides.pop("record_digest", digest),
                    )

                valid = reduce_findings(
                    panel, reviewed_sha=record["reviewed_sha"],
                    falsifier_runs={key: binding()},
                )
                self.assertTrue(any(
                    f.code == "finding_receipt" and f.severity == "block"
                    and f"observed_outcome={outcome}" in f.reason
                    and "record_digest=" in f.reason
                    and "record_digest=unresolved" not in f.reason
                    for f in valid
                ), valid)
                self.assertFalse(any(
                    f.code in ("finding_bound", "finding_unbound") for f in valid
                ), valid)
                wrong = [
                    {},
                    {(key[0], "F002"): binding()},
                    {key: binding(record_digest="0" * 64)},
                    {key: binding(reviewed_sha="2" * 40)},
                    {key: binding({**expected, "finding_id": "F002"})},
                    {key: binding({**expected, "seat_key": "other:seat"})},
                    {key: binding({**expected, "reviewed_sha": "2" * 40})},
                    {key: binding({**expected, "nodeid": "other.py::test_other"})},
                    {key: binding({**expected, "diff_digest": "0" * 64})},
                    {key: binding({**expected, "schema": "wrong.v1"})},
                    {key: binding({**expected, "authorization_identity": "wrong.v1"})},
                    {key: binding(outcome=(
                        "green_on_head" if outcome == "red_on_head" else "red_on_head"
                    ))},
                    {key: binding(nodeid="other.py::test_other")},
                    {key: binding(diff_digest="0" * 64)},
                    {key: binding(red_output_digest="0" * 64)},
                ]
                if outcome == "red_on_head":
                    wrong.append({key: binding({**expected, "red_output_digest": None})})
                else:
                    wrong.append({key: binding({**expected, "red_output_digest": "0" * 64})})
                for invalid in wrong:
                    with self.subTest(outcome=outcome, invalid=invalid):
                        findings = reduce_findings(
                            panel, reviewed_sha=record["reviewed_sha"],
                            falsifier_runs=invalid,
                        )
                        self.assertFalse(any(
                            f.code in ("finding_bound", "finding_unbound")
                            for f in findings
                        ), findings)
                        self.assertTrue(any(
                            f.code == "finding_receipt" and f.severity == "block"
                            and "record_digest=unresolved" in f.reason
                            for f in findings
                        ), findings)

        execfind_tdd.run_execfind_contract("finding_receipt_digest_unresolved", check)


if __name__ == "__main__":
    unittest.main()
