"""test_acceptance_falsifier_contract.py — Acceptance falsifier contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .proofgate_content_tdd_adapter import (
    ProofgateMissingCapabilityError,
    PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES,
    emit_mutation_observable,
    guard_proofgate_nodeid,
    run_proofgate_contract,
)


def _validator_script_path() -> Path:
    script = Path.cwd() / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    if not script.exists():
        script = Path(__file__).resolve().parents[2] / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    return script


def test_missing_falsifier_is_invalid(record_property):
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage

        if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers attribute missing on goal_coverage")

        plan_content_missing = (
            "# Phase Plan — Test\n\n"
            "## Acceptance Criteria\n"
            "- [ ] EC-FEATURE-1 — proven by `pytest phase-loop-runtime/tests/test_foo.py`\n"
        )
        plan_content_valid = (
            "# Phase Plan — Test\n\n"
            "## Acceptance Criteria\n"
            "- [ ] EC-FEATURE-1 — proven by `pytest phase-loop-runtime/tests/test_foo.py`, "
            "falsified by `python3 -c \"assert False\"`\n"
        )

        # 1. Python-level contract check and mutation observable emission first
        contracts_missing = goal_coverage.extract_acceptance_contracts(plan_content_missing)
        check_missing = goal_coverage.check_acceptance_falsifiers(contracts_missing)
        cond1 = isinstance(check_missing, dict) and not check_missing.get("valid", True) and check_missing.get("reason") == "missing_falsifier"
        if not cond1:
            emit_mutation_observable("ec-proofgate-1.missing-falsifier", record_property)

        contracts_valid = goal_coverage.extract_acceptance_contracts(plan_content_valid)
        check_valid = goal_coverage.check_acceptance_falsifiers(contracts_valid)
        cond2 = isinstance(check_valid, dict) and check_valid.get("valid", False) is True

        assert cond1, f"check_missing must return valid=False with reason missing_falsifier, got {check_missing}"
        assert cond2, f"check_valid must return valid=True, got {check_valid}"

        # 2. CLI process validation
        validator_script = _validator_script_path()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
            tf.write(plan_content_missing)
            tf_path = tf.name

        proc = subprocess.run([sys.executable, str(validator_script), tf_path], capture_output=True, text=True)
        assert proc.returncode != 0, "validate_plan_doc.py CLI must exit non-zero when falsifier is missing"
        combined_output = proc.stdout + proc.stderr
        assert "EC-FEATURE-1" in combined_output
        assert "missing_falsifier" in combined_output
        assert "WARN" not in combined_output

    run_proofgate_contract(nodeid, _contract)


def test_negative_assertion_requires_path_entered_control(record_property):
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage

        if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

        validator_script = _validator_script_path()

        # Arm 1: Absence claim without path-entered control
        plan_no_control = PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
            tf.write(plan_no_control)
            tf_path = tf.name

        contracts_no_control = goal_coverage.extract_acceptance_contracts(plan_no_control)
        check_no_control = goal_coverage.check_acceptance_falsifiers(contracts_no_control)
        cond1 = isinstance(check_no_control, dict) and not check_no_control.get("valid", True) and check_no_control.get("reason") == "missing_path_entered_control"
        if not cond1:
            emit_mutation_observable("ec-proofgate-6.missing-path-entered", record_property)

        # Arm 2: Absence claim with path-entered control
        plan_with_control = (
            "# Phase Plan — Test\n\n"
            "## Acceptance Criteria\n"
            "- [ ] EC-FEAT-2 — proven by `pytest tests/test_foo.py`, "
            "falsified by `fails if invalid key is accepted when path-entered control reaches branch B`\n"
        )
        contracts_with_control = goal_coverage.extract_acceptance_contracts(plan_with_control)
        check_with_control = goal_coverage.check_acceptance_falsifiers(contracts_with_control)
        cond2 = isinstance(check_with_control, dict) and check_with_control.get("valid", False) is True

        proc = subprocess.run([sys.executable, str(validator_script), tf_path], capture_output=True, text=True)
        assert proc.returncode != 0, "validate_plan_doc.py CLI must exit non-zero when path-entered control is missing"

        assert cond1
        assert cond2

    run_proofgate_contract(nodeid, _contract)


def test_runner_preflight_gates_enforce_acceptance_falsifiers_on_all_routes(record_property):
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_preflight_gates_enforce_acceptance_falsifiers_on_all_routes"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        import unittest.mock
        from phase_loop_runtime import goal_coverage, runner
        from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan

        if not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("check_acceptance_falsifiers attribute missing on goal_coverage")
        if not hasattr(runner, "_execute_dispatch_preflight_gates"):
            raise ProofgateMissingCapabilityError("_execute_dispatch_preflight_gates attribute missing on runner")

        def _make_fresh_repo(parent_dir: Path, name: str) -> tuple[Path, Path, Path]:
            repo = make_repo(parent_dir / name)
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text("# Roadmap\n\n### Phase 0 - Runner (RUNNER)\n\n**Exit criteria**\n- [ ] EC-RUNNER-1 — Do the thing.\n", encoding="utf-8")
            plan = write_phase_plan(
                repo, "RUNNER", roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Acceptance Criteria\n"
                    "- [ ] EC-RUNNER-1 — proven by `python3 -c \"print('ok')\"`\n\n"
                    "## Verification\n- `python3 -c \"print('verify')\"`\n"
                ),
            )
            commit_fixture_paths(repo, "add plan", roadmap, plan)
            return repo, roadmap, plan

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            # 1. Behavioral test: Prove the real helper returns typed blocker on malformed acceptance
            repo_beh, roadmap_beh, plan_beh = _make_fresh_repo(base, "beh")
            preflight_res = runner._execute_dispatch_preflight_gates(repo_beh, roadmap_beh, plan_beh)
            if preflight_res is None or preflight_res[1] != "goal_coverage_preflight":
                raise ProofgateMissingCapabilityError(
                    f"runner._execute_dispatch_preflight_gates did not block on missing acceptance falsifier: got {preflight_res}"
                )
            assert preflight_res[0].get("blocker_class") == "contract_bug"

            # 2. Route isolation tests: Give direct, lane, and work-unit separate fresh repos
            routes = [
                ("direct", lambda r, rm: runner.run_loop(r, rm, phase="RUNNER", executor="codex")),
                ("lane", lambda r, rm: runner.run_loop(r, rm, phase="RUNNER", lane_scheduler_mode="serialized")),
                ("work_unit", lambda r, rm: runner.run_loop(r, rm, phase="RUNNER", work_unit_mode=True)),
            ]

            for route_name, run_fn in routes:
                r_repo, r_roadmap, _ = _make_fresh_repo(base, f"repo_{route_name}")
                with unittest.mock.patch("phase_loop_runtime.runner.launch_with_spec") as fake_launch, \
                     unittest.mock.patch("phase_loop_runtime.runner._execute_dispatch_preflight_gates", wraps=runner._execute_dispatch_preflight_gates) as spy_preflight:
                    snap, _ = run_fn(r_repo, r_roadmap)
                    assert spy_preflight.call_count == 1, f"Route {route_name} did not call _execute_dispatch_preflight_gates exactly once (called {spy_preflight.call_count} times)"
                    assert snap.phases["RUNNER"] == "blocked", f"Route {route_name} did not transition to blocked status"
                    assert not fake_launch.called, f"Route {route_name} launched execution despite preflight blocker"

            # 3. Unrelated Check P advisory control
            repo_adv, roadmap_adv, _ = _make_fresh_repo(base, "adv")
            plan_valid_falsifier_unref = write_phase_plan(
                repo_adv, "RUNNER", roadmap_adv,
                body=(
                    "# RUNNER\n\n"
                    "## Acceptance Criteria\n"
                    "- [ ] EC-OTHER-1 — proven by `python3 -c \"print('ok')\"`, falsified by `python3 -c \"assert False\"`\n\n"
                    "## Verification\n- `python3 -c \"print('verify')\"`\n"
                ),
            )
            commit_fixture_paths(repo_adv, "update plan", plan_valid_falsifier_unref)
            res_advisory = runner._execute_dispatch_preflight_gates(repo_adv, roadmap_adv, plan_valid_falsifier_unref)
            assert res_advisory is None, "unrelated Check P warning must remain advisory"

    run_proofgate_contract(nodeid, _contract)


def test_runner_closeout_recheck_blocks_invalid_falsifiers_on_delegated_reduction():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_closeout_recheck_blocks_invalid_falsifiers_on_delegated_reduction"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage, runner
        from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan

        if not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("check_acceptance_falsifiers attribute missing on goal_coverage")
        if not hasattr(runner, "_closeout_gate_recheck"):
            raise ProofgateMissingCapabilityError("_closeout_gate_recheck attribute missing on runner")

        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text("# Roadmap\n\n### Phase 0 - Runner (RUNNER)\n\n**Exit criteria**\n- [ ] EC-RUNNER-1 — Do the thing.\n", encoding="utf-8")
            plan = write_phase_plan(
                repo, "RUNNER", roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Acceptance Criteria\n"
                    "- [ ] EC-RUNNER-1 — proven by `python3 -c \"print('ok')\"`\n\n"
                    "## Verification\n- `python3 -c \"print('verify')\"`\n"
                ),
            )
            commit_fixture_paths(repo, "add plan", roadmap, plan)

            child_automation = {"automation_status": "complete", "delegation_request": {"request_id": "req-1"}}
            outcome = runner._closeout_gate_recheck(
                repo=repo,
                roadmap=roadmap,
                plan=plan,
                child_automation=child_automation,
                automation_status="complete",
                event_blocker=None,
            )

            if outcome.automation_status != "blocked":
                raise ProofgateMissingCapabilityError(
                    f"runner._closeout_gate_recheck did not block invalid acceptance falsifier on delegated reduction: status={outcome.automation_status}"
                )

            assert outcome.event_blocker is not None
            assert outcome.event_blocker.get("blocker_class") == "contract_bug"

    run_proofgate_contract(nodeid, _contract)


def test_runner_final_closeout_boundary_enforces_path_entered_and_advisory_check_p():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_final_closeout_boundary_enforces_path_entered_and_advisory_check_p"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage, runner
        from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan
        from .proofgate_content_tdd_adapter import PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES

        if not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("check_acceptance_falsifiers attribute missing on goal_coverage")

        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text("# Roadmap\n\n### Phase 0 - Runner (RUNNER)\n\n**Exit criteria**\n- [ ] EC-PROOFGATE-ROUTE-1 — Do the thing.\n", encoding="utf-8")
            plan = write_phase_plan(
                repo, "RUNNER", roadmap,
                body=PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES,
            )
            commit_fixture_paths(repo, "add plan", roadmap, plan)

            closeout_fn = getattr(runner, "_goal_coverage_closeout_outcome", None)
            if not closeout_fn:
                raise ProofgateMissingCapabilityError("runner._goal_coverage_closeout_outcome function missing")

            evidence, blocker = closeout_fn(repo, roadmap, plan, is_complete=True)
            if blocker is None:
                raise ProofgateMissingCapabilityError(
                    "runner final closeout boundary did not block missing_path_entered_control"
                )

            assert blocker.get("blocker_class") == "contract_bug"

            plan_unref = write_phase_plan(
                repo, "RUNNER", roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Acceptance Criteria\n"
                    "- [ ] EC-OTHER-1 — proven by `python3 -c \"print('ok')\"`, falsified by `fails if unref when path-entered control reaches branch B`\n\n"
                    "## Verification\n- `python3 -c \"print('verify')\"`\n"
                ),
            )
            commit_fixture_paths(repo, "update plan", plan_unref)
            _ev_adv, blocker_adv = closeout_fn(repo, roadmap, plan_unref, is_complete=True)
            assert blocker_adv is None, "unrelated Check P warning must remain advisory at closeout"

    run_proofgate_contract(nodeid, _contract)


def test_ec4_helper_only_mutation_cannot_be_credited_as_kill():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_ec4_helper_only_mutation_cannot_be_credited_as_kill"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import verification_evidence

        if not hasattr(verification_evidence, "execute_proofgate_mutation_manifest"):
            raise ProofgateMissingCapabilityError("execute_proofgate_mutation_manifest attribute missing on verification_evidence")

        manifest_path = Path(__file__).parent / "fixtures" / "proofgate" / "v10-proofgate-mutations.json"
        fn = verification_evidence.execute_proofgate_mutation_manifest
        res = fn(
            manifest_path=manifest_path,
            candidate_oid="0000000000000000000000000000000000000000",
            parameter_id="ec-proofgate-4.github-builder-epoch-blocked",
            target_path="phase-loop-runtime/tests/proofgate_tdd_guard.py",
        )
        assert isinstance(res, dict)
        assert res.get("status") != "killed", "helper-only mutation cannot be credited as killed"
        assert res.get("reason") == "vacuous_falsifier", f"expected reason vacuous_falsifier, got {res.get('reason')}"

    run_proofgate_contract(nodeid, _contract)


def test_guard_requires_production_construction_site():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage

        if not hasattr(goal_coverage, "is_production_construction_site"):
            raise ProofgateMissingCapabilityError("is_production_construction_site attribute missing on goal_coverage")

        checker = goal_coverage.is_production_construction_site
        site_helper = "phase-loop-runtime/tests/proofgate_tdd_guard.py"
        assert not checker(site_helper), "Helper-only declaration must be classified as invalid construction site"

        site_prod = "phase-loop-runtime/src/phase_loop_runtime/runner.py"
        assert checker(site_prod), "Real production path must be classified as valid construction site"

    run_proofgate_contract(nodeid, _contract)


def test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import verification_evidence

        if not hasattr(verification_evidence, "execute_proofgate_mutation_manifest"):
            raise ProofgateMissingCapabilityError("execute_proofgate_mutation_manifest attribute missing on verification_evidence")

        from .proofgate_content_tdd_adapter import validate_mutation_manifest_structure

        manifest_path = Path(__file__).parent / "fixtures" / "proofgate" / "v10-proofgate-mutations.json"
        res_struct = validate_mutation_manifest_structure(manifest_path)
        assert res_struct is not None, "validate_mutation_manifest_structure must not return None"
        assert res_struct.get("is_valid") is True or res_struct.get("status") == "valid"
        assert res_struct["criteria_count"] == 8
        assert res_struct["parameters_count"] == 9

        # Negative manifest structure validation tests
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

        def _assert_invalid(mutator, msg_substring):
            import copy
            bad_data = copy.deepcopy(manifest_data)
            mutator(bad_data)
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
                tf.write(json.dumps(bad_data))
                tf_path = Path(tf.name)
            res = validate_mutation_manifest_structure(tf_path)
            assert res.get("is_valid") is False, f"Expected invalid manifest for {msg_substring}, got valid"

        # 1. Bogus criterion ID
        def _mut_bogus_crit(d):
            d["declarations"][0]["criterion_id"] = "EC-PROOFGATE-99"
        _assert_invalid(_mut_bogus_crit, "bogus criterion ID")

        # 2. Duplicate criterion
        def _mut_dup_crit(d):
            d["declarations"][1]["criterion_id"] = "EC-PROOFGATE-0"
        _assert_invalid(_mut_dup_crit, "duplicate criterion")

        # 3. Duplicate parameter
        def _mut_dup_param(d):
            d["declarations"][1]["parameters"][0]["parameter_id"] = "ec-proofgate-0.chronology-guard"
        _assert_invalid(_mut_dup_param, "duplicate parameter")

        # 4. Substituted proof command
        def _mut_sub_cmd(d):
            d["declarations"][0]["parameters"][0]["proof_command"] = ["python3", "-m", "pytest", "wrong_nodeid"]
        _assert_invalid(_mut_sub_cmd, "substituted proof command")

        # 5. Substituted nodeid
        def _mut_sub_node(d):
            d["declarations"][0]["parameters"][0]["target_nodeid"] = "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline"
        _assert_invalid(_mut_sub_node, "substituted target_nodeid")

        # 6. Altered observable
        def _mut_alt_obs(d):
            d["declarations"][0]["parameters"][0]["expected_observable"]["result_code"] = "wrong_code"
        _assert_invalid(_mut_alt_obs, "altered observable")

        # 7. Altered failure class
        def _mut_alt_fail(d):
            d["declarations"][0]["parameters"][0]["expected_failure_class"] = "wrong_class"
        _assert_invalid(_mut_alt_fail, "altered failure class")

        # 8. Same replacement bytes as anchor
        def _mut_same_repl(d):
            anchor = d["declarations"][0]["parameters"][0]["injection_anchor"]
            d["declarations"][0]["parameters"][0]["replacement_bytes"] = anchor
        _assert_invalid(_mut_same_repl, "same replacement bytes")

        # 9. Out-of-scope target
        def _mut_out_scope(d):
            d["declarations"][0]["parameters"][0]["target_nodeid"] = "phase-loop-runtime/tests/test_unknown.py::test_foo"
        _assert_invalid(_mut_out_scope, "out-of-scope target")

        # 10. Nonunique or missing anchor
        def _mut_missing_anchor(d):
            d["declarations"][0]["parameters"][0]["injection_anchor"] = "NONEXISTENT_ANCHOR_12345"
        _assert_invalid(_mut_missing_anchor, "missing anchor")

        # 11. Incomplete / missing parameter
        def _mut_missing_param(d):
            d["declarations"][0]["parameters"] = []
        _assert_invalid(_mut_missing_param, "missing parameter")

        # 12. Extra parameter
        def _mut_extra_param(d):
            import copy
            extra = copy.deepcopy(d["declarations"][0]["parameters"][0])
            extra["parameter_id"] = "ec-proofgate-extra"
            d["declarations"][0]["parameters"].append(extra)
        _assert_invalid(_mut_extra_param, "extra parameter")

        try:
            cand_oid = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            cand_oid = "0000000000000000000000000000000000000000"

        exec_fn = verification_evidence.execute_proofgate_mutation_manifest
        exec_res = exec_fn(manifest_path=manifest_path, candidate_oid=cand_oid)
        assert isinstance(exec_res, dict)
        assert exec_res.get("parameters_count") == 9
        assert exec_res.get("killed_count") == 9
        assert exec_res.get("survived_count") == 0
        assert exec_res.get("block_count") == 0
        assert exec_res.get("status") == "killed"
        assert len(exec_res.get("classifications", {})) == 9
        assert all(v == "killed" for v in exec_res["classifications"].values())
        bindings = exec_res.get("bindings", {})
        assert len(bindings) == 9
        for b in bindings.values():
            assert "candidate" in b
            assert "tree" in b
            assert "path" in b
            assert "blob" in b
            assert "argv" in b
            assert "command" in b
            assert "environment" in b
            assert "testcase" in b
            assert "assertion" in b

    run_proofgate_contract(nodeid, _contract)
