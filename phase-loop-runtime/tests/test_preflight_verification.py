import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.discovery import (
    resolve_suite_command,
    resolve_suite_command_doc,
    validate_plan_verification_commands_for_intake,
    verification_commands_from_plan,
)
from phase_loop_runtime.events import read_events
from phase_loop_runtime.launcher import LaunchResult
from phase_loop_runtime.runner import run_loop
from phase_loop_runtime.verification_evidence import (
    detect_changed_dependency_manifests,
    resolve_install_command,
    run_verification,
    validate_verification_artifact,
)
from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, make_repo, write_phase_plan

import pytest

# TESTDECOUPLE SL-1 (overlay-dependent): existing tests call run_loop which resolves dotfiles.
# Proofgate preflight test is standalone.


class PreflightVerificationTest(unittest.TestCase):
    @pytest.mark.dotfiles_integration
    def test_suite_command_prefers_plan_frontmatter_and_ignores_body_automation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "---\n"
                "automation:\n"
                f"  suite_command: [{sys.executable!r}, -c, 'print(\"roadmap\")']\n"
                "---\n"
                "# Roadmap\n\n"
                "### Phase 0 - Runner (RUNNER)\n",
                encoding="utf-8",
            )
            plan = write_phase_plan(
                repo,
                "RUNNER",
                roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Verification\n"
                    f"- `{sys.executable} -c \"print('verify')\"`\n\n"
                    "automation:\n"
                    "  suite_command: definitely ignored\n"
                ),
                extra_frontmatter={"automation": ""},
            )
            text = plan.read_text(encoding="utf-8")
            text = text.replace("automation: \n", f"automation:\n  suite_command: [{sys.executable!r}, -c, 'print(\"plan\")']\n")
            plan.write_text(text, encoding="utf-8")

            command = resolve_suite_command(repo, roadmap, plan)

            self.assertEqual(command, [sys.executable, "-c", 'print("plan")'])

    @pytest.mark.dotfiles_integration
    def test_malformed_suite_command_returns_structured_finding(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "---\n"
                "automation:\n"
                "  suite_command: [python, 7]\n"
                "---\n"
                "# Roadmap\n\n"
                "### Phase 0 - Runner (RUNNER)\n",
                encoding="utf-8",
            )
            plan = write_phase_plan(repo, "RUNNER", roadmap)

            command, findings = resolve_suite_command_doc(repo, roadmap, plan)

            self.assertIsNone(command)
            self.assertEqual(findings[0].code, "malformed_suite_command")

    @pytest.mark.dotfiles_integration
    def test_dependency_manifest_change_resolves_install_and_failure_blocks_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            commit_fixture_paths(repo, "add pyproject", repo / "pyproject.toml")
            (repo / "pyproject.toml").write_text("[project]\nname = 'changed'\n", encoding="utf-8")

            manifests = detect_changed_dependency_manifests(repo, "HEAD")
            command = resolve_install_command(repo, manifests)
            run_dir = repo / ".phase-loop/runs/preflight"
            run_verification(
                repo,
                run_dir,
                [],
                None,
                {"triggered": True, "manifests": manifests, "install_argv": command or [], "exit_code": 9},
                5,
            )
            validation = validate_verification_artifact(run_dir / "verification.json")

            self.assertEqual(manifests, ["pyproject.toml"])
            self.assertIsNotNone(command)
            self.assertFalse(validation.ok)
            self.assertEqual(validation.exit_summary["env_refresh"], 9)

    @pytest.mark.dotfiles_integration
    def test_operational_evidence_is_recorded_but_not_executed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            plan = write_phase_plan(
                repo,
                "RUNNER",
                roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Verification\n"
                    f"- `{sys.executable} -c \"print('machine')\"`\n"
                    "- `definitely-not-executed-operational-command` evidence: operational\n"
                ),
            )

            commands, operational = verification_commands_from_plan(plan)
            run_dir = repo / ".phase-loop/runs/operational"
            run_verification(repo, run_dir, commands, None, None, 5, operational_exemptions=operational)
            payload = json.loads((run_dir / "verification.json").read_text(encoding="utf-8"))

            self.assertEqual(len(payload["commands"]), 1)
            self.assertEqual(payload["commands"][0]["exit_code"], 0)
            self.assertEqual(payload["operational_exemptions"][0]["reason"], "evidence: operational")
            self.assertNotIn("definitely-not-executed", (run_dir / "verification.log").read_text(encoding="utf-8"))

    @pytest.mark.dotfiles_integration
    def test_reducer_note_bullets_are_not_verification_commands(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            plan = write_phase_plan(
                repo,
                "RUNNER",
                roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Verification\n\n"
                    "Reducer notes:\n\n"
                    "- `packages/pipeline-runtime/src/harness/claude-channel.mjs` now provides a helper.\n"
                    "- Channel preflight failure does not call print mode.\n\n"
                    "Lane-specific commands:\n\n"
                    f"- `{sys.executable} -c \"print('verify')\"`\n"
                    "- `definitely-not-executed-operational-command` evidence: operational\n"
                ),
            )

            commands, operational = verification_commands_from_plan(plan)

            self.assertEqual(commands, [[sys.executable, "-c", "print('verify')"]])
            self.assertEqual(len(operational), 1)
            self.assertEqual(operational[0]["command"], "definitely-not-executed-operational-command")

    @pytest.mark.dotfiles_integration
    def test_execute_launch_writes_runner_verification_metadata_before_reduction(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "---\n"
                "automation:\n"
                f"  suite_command: [{sys.executable!r}, -c, 'print(\"suite\")']\n"
                "---\n"
                "# Roadmap\n\n"
                "### Phase 0 - Runner (RUNNER)\n",
                encoding="utf-8",
            )
            plan = write_phase_plan(
                repo,
                "RUNNER",
                roadmap,
                body=(
                    "# RUNNER\n\n"
                    "## Lanes\n\n"
                    "### SL-0 - Runner\n"
                    "- **Owned files**: `README.md`\n\n"
                    "## Verification\n"
                    f"- `{sys.executable} -c \"print('verify')\"`\n"
                ),
            )
            commit_fixture_paths(repo, "add plan", roadmap, plan)

            output = build_fake_automation_output(status="complete", verification_status="passed")

            with patch.dict(os.environ, {"PHASE_LOOP_VERIFY_ENFORCE": "hard"}), patch(
                "phase_loop_runtime.runner.launch_with_spec",
                return_value=LaunchResult(command=["codex", "exec"], returncode=0, output=output, executor="codex"),
            ):
                snapshot, _results = run_loop(repo, roadmap, phase="RUNNER", executor="codex")

            self.assertEqual(snapshot.phases["RUNNER"], "complete")
            event = read_events(repo)[-1]
            verification = event["metadata"]["child_automation"]["runner_verification"]
            self.assertTrue(verification["ok"])
            self.assertTrue(Path(verification["verification_artifact_path"]).exists())
            self.assertTrue(Path(verification["verification_log_path"]).exists())
            self.assertEqual(verification["verification_exit_summary"]["commands"], [0])
            self.assertEqual(verification["verification_exit_summary"]["suite"], 0)

    @pytest.mark.dotfiles_integration
    def test_hard_mode_missing_suite_blocks_before_execute_launch(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            plan = write_phase_plan(
                repo,
                "RUNNER",
                roadmap,
                body="# RUNNER\n\n## Verification\n" f"- `{sys.executable} -c \"print('verify')\"`\n",
            )
            commit_fixture_paths(repo, "add plan", plan)

            with patch.dict(os.environ, {"PHASE_LOOP_VERIFY_ENFORCE": "hard"}), patch(
                "phase_loop_runtime.runner.launch_with_spec"
            ) as fake_launch:
                snapshot, results = run_loop(repo, roadmap, phase="RUNNER", executor="codex")

            fake_launch.assert_not_called()
            self.assertEqual(results, [])
            self.assertEqual(snapshot.phases["RUNNER"], "blocked")
            self.assertEqual(snapshot.blocker_class, "verification_evidence_missing")

    @pytest.mark.dotfiles_integration
    def test_bogus_verification_command_is_rejected_at_intake(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            plan = write_phase_plan(
                repo,
                "RUNNER",
                roadmap,
                body="# RUNNER\n\n## Verification\n- `definitely-not-a-real-verifier`\n",
            )

            findings = validate_plan_verification_commands_for_intake(repo, plan)

            self.assertEqual(findings[0].code, "unresolved_executable")

    def test_proofgate_preflight_requires_attested_authorization_and_exact_candidate(self):
        from .proofgate_bootstrap_verifier import (
            ProofgateContractViolation,
            assert_admin_preflight_authority_contract,
            assert_preflight_intake_contract,
            verify_external_observation,
        )
        from .proofgate_tdd_guard import (
            PROOFGATE_EXPECTED_CONFIG_V1,
            PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES,
            ProofgateMissingCapabilityError,
            assert_frozen_authority_contract,
            guard_proofgate_nodeid,
            run_proofgate_contract,
        )
        nodeid = "phase-loop-runtime/tests/test_preflight_verification.py::PreflightVerificationTest::test_proofgate_preflight_requires_attested_authorization_and_exact_candidate"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            # Control A: the typed authority contracts are frozen. The expected configuration cannot
            # be mutated in place, the locator carries no evidence/status/decisive/authority field,
            # the sealed observation carries no verdict of its own, and the boundary is read-only.
            assert_frozen_authority_contract()

            # Control B: the oracle is not vacuous — the test-owned reference verifier, whose whole
            # authority is the comparison of a sealed observation to the independently supplied
            # expected configuration, satisfies the frozen preflight-intake contract.
            assert_preflight_intake_contract(verify_external_observation, expected=PROOFGATE_EXPECTED_CONFIG_V1)

            # Control C: a shallow local-file preflight verifier, which trusts a caller-written
            # `proofgate_authorization.v1` file and never observes the external boundary, must reject.
            def _shallow_local_file_preflight(request, *, expected, boundary):
                auth_file = Path(request.plan_path).parent / "proofgate_authorization.json"
                if not auth_file.is_file():
                    return {"authorized": False, "decisive": False, "blocker_class": "contract_bug"}
                data = json.loads(auth_file.read_text(encoding="utf-8"))
                if data.get("schema") == "proofgate_authorization.v1":
                    return {
                        "status": "verified",
                        "authorized": True,
                        "decisive": True,
                        "evidence_kind": "production_external_boundary",
                        "observation_digest": data.get("observation_digest", ""),
                    }
                return {"authorized": False, "decisive": False, "blocker_class": "contract_bug"}

            with self.assertRaises(ProofgateContractViolation):
                assert_preflight_intake_contract(_shallow_local_file_preflight, expected=PROOFGATE_EXPECTED_CONFIG_V1)

            # Control D: the admin verifier receives the immutable expected configuration and the
            # observation boundary explicitly. A matching 42/42/43-plus-garbage observation and a
            # mutable expected-configuration substitute both reject, and the GitHub CLI adapter is
            # only constructed — it never executes a live observation in an ordinary run.
            with tempfile.TemporaryDirectory() as td_ap:
                run_dir = Path(td_ap) / "run_dir"
                run_dir.mkdir(parents=True)
                old_env = os.environ.get("PHASE_LOOP_RUN_DIR")
                try:
                    os.environ["PHASE_LOOP_RUN_DIR"] = str(run_dir)
                    assert_admin_preflight_authority_contract(PROOFGATE_EXPECTED_CONFIG_V1, run_dir)
                finally:
                    if old_env is not None:
                        os.environ["PHASE_LOOP_RUN_DIR"] = old_env
                    else:
                        os.environ.pop("PHASE_LOOP_RUN_DIR", None)

            try:
                from phase_loop_runtime import proofgate_receipts
            except ImportError as err:
                raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

            if not hasattr(proofgate_receipts, "verify_proofgate_preflight_intake"):
                raise ProofgateMissingCapabilityError("verify_proofgate_preflight_intake attribute missing on proofgate_receipts")

            # Production positive: the production preflight intake is handed only the locator, the
            # immutable expected configuration and a recording boundary. It must observe exactly once
            # with exactly that locator and derive its authority from the sealed observation alone.
            assert_preflight_intake_contract(
                proofgate_receipts.verify_proofgate_preflight_intake,
                expected=PROOFGATE_EXPECTED_CONFIG_V1,
            )

            # Scenario: caller-authored local authority must never authorize preflight.
            # The complete rich `proofgate_authorization.v1` tree — schema, satisfied status,
            # external head/candidate/plan digests, admin prerequisites, OIDC claims, panel
            # records, RED lifecycle and a decisive receipt — is written to disk exactly as an
            # attacker would, and the production intake must refuse to draw authority from it
            # through any call shape that supplies no external observation boundary.
            with tempfile.TemporaryDirectory() as td_local:
                r_local = make_repo(Path(td_local))
                rm_local = r_local / "specs" / "phase-plans-v1.md"
                pl_local = write_phase_plan(r_local, "PROOFGATE", rm_local)
                head_oid = hashlib.sha1(b"commit 1\x00").hexdigest()
                ext_head = r_local / ".git" / "refs" / "heads" / "proofgate-receipt-head-v1"
                ext_head.parent.mkdir(parents=True, exist_ok=True)
                ext_head.write_text(f"{head_oid}\n", encoding="utf-8")

                exp = PROOFGATE_EXPECTED_CONFIG_V1
                auth_file = r_local / ".phase-loop" / "proofgate_authorization.json"
                auth_file.parent.mkdir(parents=True, exist_ok=True)
                auth_file.write_text(json.dumps({
                    "schema": "proofgate_authorization.v1",
                    "authorized": True,
                    "status": "verified",
                    "decisive": True,
                    "evidence_kind": "production_external_boundary",
                    "stage": "SL0-T1",
                    "verification_status": "satisfied",
                    "external_head_ref": exp.external_head_ref,
                    "external_head_oid": head_oid,
                    "candidate_oid": head_oid,
                    "plan_sha256": hashlib.sha256(pl_local.read_bytes()).hexdigest(),
                    "admin_prerequisites": {
                        "status": "satisfied",
                        "dedicated_github_app_id": exp.dedicated_app_integration_id,
                        "installation_id": exp.dedicated_app_installation_id,
                        "required_reviewer_id": exp.required_reviewer_id,
                        "broker_deployment_id": exp.broker_deployment_id,
                        "broker_key_version": exp.broker_key_version,
                        "broker_claim_policy_digest": exp.broker_claim_policy_digest,
                    },
                    "oidc_claims": {
                        "aud": exp.oidc_audience,
                        "repository_id": exp.repository_id,
                        "repository_owner_id": exp.repository_owner_id,
                        "repository": exp.repository_name,
                        "ref": exp.accepted_refs[0],
                        "environment": exp.environment_name,
                        "event_name": exp.event_name,
                        "runner_environment": exp.runner_environment,
                        "workflow_ref": exp.workflow_ref,
                        "workflow_path": exp.workflow_path,
                        "workflow_sha": exp.workflow_sha256,
                        "actor": exp.actor,
                        "subject": exp.subject,
                        "run_id": exp.run_id,
                        "run_attempt": exp.run_attempt,
                    },
                    "panel_records": {
                        seat: {"verdict": "AGREE", "substantive": True, "run_identity": f"run-{seat}-1"}
                        for seat in exp.required_panel_seats
                    },
                    "red_lifecycle": {
                        "mode": "forced_red",
                        "expected_nodeids": exp.expected_nodeid_count,
                        "passed": exp.forced_red_passed,
                        "failed": exp.forced_red_failed,
                    },
                    "decisive_receipt": {"status": "verified", "sequence": 1, "external_head_oid": head_oid},
                }), encoding="utf-8")

                for call_shape, invoke in (
                    ("repo_roadmap_plan", lambda: proofgate_receipts.verify_proofgate_preflight_intake(
                        r_local, rm_local, pl_local)),
                    ("repo_only", lambda: proofgate_receipts.verify_proofgate_preflight_intake(r_local)),
                ):
                    try:
                        legacy_res = invoke()
                    except Exception:
                        continue
                    self.assertNotIsInstance(
                        legacy_res, bool,
                        f"Caller-local authorization must not authorize preflight via {call_shape}",
                    )
                    if isinstance(legacy_res, dict):
                        self.assertIsNot(
                            legacy_res.get("authorized"), True,
                            f"Caller-written local authorization tree authorized preflight via {call_shape}",
                        )
                        self.assertIsNot(
                            legacy_res.get("decisive"), True,
                            f"Caller-written local authorization tree was decisive via {call_shape}",
                        )

                pl_local.write_text(PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES, encoding="utf-8")
                for route in ("direct", "delegated", "lane"):
                    invalid_result = proofgate_receipts.verify_proofgate_preflight_intake(
                        r_local,
                        rm_local,
                        pl_local,
                        acceptance_route=route,
                    )
                    self.assertIsInstance(invalid_result, dict)
                    self.assertFalse(invalid_result.get("authorized", True), route)
                    self.assertFalse(invalid_result.get("decisive", True), route)
                    self.assertEqual(invalid_result.get("blocker_class"), "contract_bug", route)
                    self.assertEqual(invalid_result.get("reason"), "missing_path_entered_control", route)

        run_proofgate_contract(nodeid, _contract)



if __name__ == "__main__":
    unittest.main()
