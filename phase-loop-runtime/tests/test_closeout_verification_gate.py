import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.closeout import build_phase_loop_closeout, phase_loop_closeout_diagnostic
from phase_loop_runtime.verification_evidence import run_verification


class CloseoutVerificationGateTest(unittest.TestCase):
    def test_artifact_backed_pass_is_accepted_and_records_agent_report(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(repo, run_dir, [[sys.executable, "-c", "print('ok')"]], None, None, 5)

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["terminal_status"], "complete")
            self.assertEqual(closeout["verification"]["status"], "passed")
            self.assertEqual(closeout["verification"]["agent_reported_verification_status"], "passed")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "ok")

    def test_missing_artifact_blocks_passed_closeout_in_hard_mode(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_dir.mkdir(parents=True)

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["terminal_status"], "blocked")
            self.assertEqual(closeout["verification"]["status"], "blocked")
            self.assertEqual(closeout["blocker"]["blocker_class"], "verification_evidence_missing")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "malformed_artifact")

    def test_rg_passed_closeout_without_artifact_path_blocks_in_hard_mode(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)

            closeout = build_phase_loop_closeout(
                phase_alias="RG",
                plan_path=plan,
                terminal_summary={"terminal_status": "complete", "verification_status": "passed"},
                automation={"status": "complete", "verification_status": "passed", "human_required": False},
            )

            self.assertEqual(closeout["terminal_status"], "blocked")
            self.assertEqual(closeout["verification"]["status"], "blocked")
            self.assertEqual(closeout["blocker"]["blocker_class"], "verification_evidence_missing")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "missing_verification_artifact")

    def test_legacy_non_rg_passed_closeout_without_artifact_path_remains_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = repo / "plans/phase-plan-v1-LEGACY.md"
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("# LEGACY\n\n## Verification\n- `python3 -c \"print('ok')\"`\n", encoding="utf-8")

            closeout = build_phase_loop_closeout(
                phase_alias="LEGACY",
                plan_path=plan,
                terminal_summary={"terminal_status": "complete", "verification_status": "passed", "verification_evidence_opt_out": "no_executable_verification"},
                automation={"status": "complete", "verification_status": "passed", "human_required": False},
            )

            self.assertEqual(closeout["terminal_status"], "complete")
            self.assertEqual(closeout["verification"]["status"], "passed")
            self.assertEqual(closeout["verification"]["results"], [])

    def test_declared_rg_contract_requires_artifact_path_for_non_rg_phase(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = repo / "plans/phase-plan-v1-AUDIT.md"
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("**Interfaces provided**: IF-0-RG-1\n\n## Verification\n- `python3 -c \"print('ok')\"`\n", encoding="utf-8")

            closeout = build_phase_loop_closeout(
                phase_alias="AUDIT",
                plan_path=plan,
                terminal_summary={"terminal_status": "complete", "verification_status": "passed"},
                automation={"status": "complete", "verification_status": "passed", "human_required": False},
            )

            self.assertEqual(closeout["terminal_status"], "blocked")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "missing_verification_artifact")

    def test_warn_mode_records_warning_without_blocking_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_dir.mkdir(parents=True)

            with patch.dict(os.environ, {"PHASE_LOOP_VERIFY_ENFORCE": "warn"}):
                closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["terminal_status"], "complete")
            self.assertEqual(closeout["verification"]["status"], "passed")
            self.assertEqual(closeout["verification"]["results"][0]["enforcement"], "warn")
            self.assertIn("warning", closeout["verification"]["results"][0])

    def test_nonzero_artifact_blocks_passed_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(repo, run_dir, [[sys.executable, "-c", "raise SystemExit(7)"]], None, None, 5)

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "nonzero_exit")

    def test_malformed_artifact_blocks_passed_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_dir.mkdir(parents=True)
            (run_dir / "verification.json").write_text('{"schema_version": 1}', encoding="utf-8")
            (run_dir / "verification.log").write_text("log", encoding="utf-8")

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "malformed_artifact")

    def test_tampered_log_hash_blocks_passed_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(repo, run_dir, [[sys.executable, "-c", "print('ok')"]], None, None, 5)
            (run_dir / "verification.log").write_text("tampered", encoding="utf-8")

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")
            self.assertEqual(closeout["verification"]["results"][0]["code"], "log_sha256_mismatch")

    def test_closeout_diagnostic_with_secret_is_redacted_to_metadata_only(self):
        # agent-harness#243: a failing stage that dumps a secret-shaped value into
        # verification.log must NOT surface that secret through the persisted closeout record.
        # The diagnostic is redacted to metadata-only when it enters the record.
        import json as _json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo,
                run_dir,
                [[sys.executable, "-c",
                  "import sys; print(\"api_key='AKIAIOSFODNN7EXAMPLEKEY'\"); sys.exit(1)"]],
                None,
                None,
                5,
            )

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")  # nonzero still blocks
            result = closeout["verification"]["results"][0]
            self.assertEqual(result["code"], "nonzero_exit")
            diag = result["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertEqual(diag["diagnostic_status"], "redacted")
            self.assertNotIn("raw_tail", diag)
            # The secret must not appear anywhere in the serialized closeout record.
            self.assertNotIn("AKIAIOSFODNN7EXAMPLEKEY", _json.dumps(closeout))

    def test_closeout_diagnostic_with_double_quoted_secret_is_redacted_to_metadata_only(self):
        # agent-harness#243 CR (defect 1): a DOUBLE-quoted secret must be redacted too. The
        # pre-fix matcher ran against a json.dumps(...) blob, which backslash-escapes an
        # embedded double quote and broke the secret_like_value pattern (single-quoted secrets
        # were unaffected -- see test_closeout_diagnostic_with_secret_is_redacted_to_metadata_only
        # above -- which is why this case slipped through).
        import json as _json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo,
                run_dir,
                [[sys.executable, "-c",
                  'import sys; print("api_key=\\"AKIAIOSFODNN7EXAMPLEKEY\\""); sys.exit(1)']],
                None,
                None,
                5,
            )

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")  # nonzero still blocks
            result = closeout["verification"]["results"][0]
            self.assertEqual(result["code"], "nonzero_exit")
            diag = result["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertEqual(diag["diagnostic_status"], "redacted")
            self.assertNotIn("raw_tail", diag)
            # The secret must not appear anywhere in the serialized closeout record.
            self.assertNotIn("AKIAIOSFODNN7EXAMPLEKEY", _json.dumps(closeout))

    def test_closeout_diagnostic_with_split_argv_secret_is_redacted_to_metadata_only(self):
        # agent-harness#243 CR (round 2, cross-vendor, defect 3): a secret split across TWO
        # adjacent argv elements (a real subprocess invocation shape -- e.g. `tool --token
        # SECRET` -- rather than a single pre-joined string) must be caught end-to-end through
        # the closeout path, not just at the redaction-helper level. Before the fix, examining
        # each argv leaf in isolation never saw the "--token" flag and the secret value
        # contiguous, so `secret_like_value` never matched and the raw secret argv leaked
        # straight into the persisted closeout record.
        import json as _json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo,
                run_dir,
                [[sys.executable, "-c", "import sys; sys.exit(1)", "--token", "AKIAIOSFODNN7EXAMPLEKEY"]],
                None,
                None,
                5,
            )

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")  # nonzero still blocks
            result = closeout["verification"]["results"][0]
            self.assertEqual(result["code"], "nonzero_exit")
            diag = result["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertEqual(diag["diagnostic_status"], "redacted")
            self.assertNotIn("argv", diag)
            # The secret must not appear anywhere in the serialized closeout record.
            self.assertNotIn("AKIAIOSFODNN7EXAMPLEKEY", _json.dumps(closeout))

    def test_closeout_diagnostic_with_json_struct_secret_is_redacted_to_metadata_only(self):
        # agent-harness#243 CR round 4 (codex + Fable): a failing command that PRINTS ordinary
        # JSON credentials (e.g. ``print(json.dumps({"api_key": "SECRET"}))``) is captured
        # verbatim into raw_tail as literal JSON text. The closing quote on the JSON key sits
        # between the keyword and the ``:`` separator, breaking the keyword->separator->value
        # adjacency the matcher required -- so this JSON-formatted secret bypassed BOTH the
        # redaction path and the fatal metadata gate end-to-end through the real closeout path.
        import json as _json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo,
                run_dir,
                [[sys.executable, "-c",
                  "import json, sys; print(json.dumps({'api_key': 'AKIAIOSFODNN7EXAMPLEKEY'})); sys.exit(1)"]],
                None,
                None,
                5,
            )

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")  # nonzero still blocks
            result = closeout["verification"]["results"][0]
            self.assertEqual(result["code"], "nonzero_exit")
            diag = result["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertEqual(diag["diagnostic_status"], "redacted")
            self.assertNotIn("raw_tail", diag)
            # The secret must not appear anywhere in the serialized closeout record.
            self.assertNotIn("AKIAIOSFODNN7EXAMPLEKEY", _json.dumps(closeout))

    def test_closeout_diagnostic_with_nested_json_struct_secret_is_redacted_to_metadata_only(self):
        # agent-harness#243 CR round 4: the same JSON-struct blind spot, one level deeper --
        # a secret nested inside another JSON object, printed verbatim by a failing command.
        import json as _json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo,
                run_dir,
                [[sys.executable, "-c",
                  "import json, sys; print(json.dumps({'outer': {'token': 'AKIAIOSFODNN7EXAMPLEKEY'}})); sys.exit(1)"]],
                None,
                None,
                5,
            )

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")
            result = closeout["verification"]["results"][0]
            self.assertEqual(result["code"], "nonzero_exit")
            diag = result["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertNotIn("raw_tail", diag)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLEKEY", _json.dumps(closeout))

    def test_closeout_diagnostic_with_json_struct_password_is_redacted_to_metadata_only(self):
        # agent-harness#243 CR round 4: same JSON-struct blind spot with the "password" keyword.
        import json as _json

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo,
                run_dir,
                [[sys.executable, "-c",
                  "import json, sys; print(json.dumps({'password': 'AKIAIOSFODNN7EXAMPLEKEY'})); sys.exit(1)"]],
                None,
                None,
                5,
            )

            closeout = self._closeout(plan, run_dir)

            self.assertEqual(closeout["verification"]["status"], "blocked")
            result = closeout["verification"]["results"][0]
            self.assertEqual(result["code"], "nonzero_exit")
            diag = result["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertNotIn("raw_tail", diag)
            self.assertNotIn("AKIAIOSFODNN7EXAMPLEKEY", _json.dumps(closeout))

    def test_closeout_with_benign_prose_blocker_summary_is_not_malformed(self):
        # agent-harness#243 CR (cross-vendor codex, REGRESSION): the round that widened
        # secret_like_value's separator to accept bare whitespace made the FATAL
        # metadata_redaction_diagnostic gate (invoked here via phase_loop_closeout_diagnostic)
        # reject a legitimate human-authored blocker_summary that happens to contain a secret
        # keyword followed by whitespace and 12+ alnum chars -- e.g. "review the token
        # configuration" or "the password authentication documentation" -- turning an
        # ordinary blocked closeout into malformed_closeout and preventing
        # persistence/reconciliation. MUST FAIL at HEAD bec790f (diagnostic is non-None) and
        # pass once the separator is strict again.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(repo, run_dir, [[sys.executable, "-c", "print('ok')"]], None, None, 5)

            closeout = build_phase_loop_closeout(
                phase_alias="RG",
                plan_path=plan,
                terminal_summary={
                    "terminal_status": "blocked",
                    "verification_status": "passed",
                    "artifact_paths": {"root": str(run_dir)},
                },
                automation={
                    "status": "blocked",
                    "verification_status": "passed",
                    "human_required": True,
                    "blocker_class": "admin_approval",
                    "blocker_summary": (
                        "Next action: review the token configuration and the password "
                        "authentication documentation before re-running the suite; see the "
                        "secret management guide for the rotation policy."
                    ),
                },
            )

            self.assertEqual(closeout["terminal_status"], "human_required")
            self.assertIn("token configuration", closeout["blocker"]["blocker_summary"])
            diagnostic = phase_loop_closeout_diagnostic(closeout)
            self.assertIsNone(diagnostic, diagnostic)

    def test_closeout_force_all_redaction_suppresses_benign_tail(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            plan = self._plan(repo)
            run_dir = repo / ".phase-loop/runs/test-run"
            run_verification(
                repo, run_dir,
                [[sys.executable, "-c", "print('benign failing output'); raise SystemExit(1)"]],
                None, None, 5,
            )
            with patch.dict(os.environ, {"PHASE_LOOP_VERIFY_REDACT_DIAGNOSTICS": "all"}):
                closeout = self._closeout(plan, run_dir)
            diag = closeout["verification"]["results"][0]["diagnostics"][0]
            self.assertTrue(diag["redacted"])
            self.assertEqual(diag["redaction_reason"], "operator_forced")

    def test_proofgate_closeout_rejects_missing_or_invalid_attested_proof(self):
        from .proofgate_bootstrap_verifier import (
            ProofgateContractViolation,
            assert_closeout_attestation_contract,
            verify_external_observation,
        )
        from .proofgate_tdd_guard import (
            PROOFGATE_EXPECTED_CONFIG_V1,
            PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES,
            ProofgateMissingCapabilityError,
            ProofgateObservationRequest,
            RecordingObservationBoundary,
            assert_frozen_authority_contract,
            conforming_observation,
            guard_proofgate_nodeid,
            run_proofgate_contract,
        )
        nodeid = "phase-loop-runtime/tests/test_closeout_verification_gate.py::CloseoutVerificationGateTest::test_proofgate_closeout_rejects_missing_or_invalid_attested_proof"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            # Control A: the typed authority contracts are frozen and authority-free.
            assert_frozen_authority_contract()

            # Control B: the oracle is not vacuous — the test-owned reference verifier satisfies it.
            assert_closeout_attestation_contract(verify_external_observation, expected=PROOFGATE_EXPECTED_CONFIG_V1)

            # Control C: a marker-only closeout, whose verdict comes from caller-supplied
            # `evidence_kind=production_external_boundary` / `decisive=True` / status labels or
            # equivalent local receipt labels rather than from an external observation, must reject.
            def _marker_only_closeout(request, *, expected, boundary, markers=None):
                labels = markers or {
                    "evidence_kind": "production_external_boundary",
                    "decisive": True,
                    "status": "verified",
                }
                if (
                    labels.get("evidence_kind") == "production_external_boundary"
                    and labels.get("decisive") is True
                    and labels.get("status") == "verified"
                ):
                    return {
                        "status": "verified",
                        "decisive": True,
                        "evidence_kind": "production_external_boundary",
                        "observation_digest": "",
                    }
                return {"status": "blocked", "decisive": False}

            with self.assertRaises(ProofgateContractViolation):
                assert_closeout_attestation_contract(_marker_only_closeout, expected=PROOFGATE_EXPECTED_CONFIG_V1)

            from phase_loop_runtime import closeout
            from phase_loop_runtime.closeout import build_phase_loop_closeout

            if not hasattr(closeout, "verify_proofgate_closeout_attestation"):
                raise ProofgateMissingCapabilityError("verify_proofgate_closeout_attestation capability missing on closeout")

            # Production positive: the production closeout attestation verifier is handed only the
            # locator, the immutable expected configuration and a recording boundary.
            assert_closeout_attestation_contract(
                closeout.verify_proofgate_closeout_attestation,
                expected=PROOFGATE_EXPECTED_CONFIG_V1,
            )

            with tempfile.TemporaryDirectory() as td:
                repo = Path(td)
                plan = repo / "plans" / "phase-plan-v1-PROOFGATE.md"
                plan.parent.mkdir(parents=True, exist_ok=True)
                plan.write_text("# PROOFGATE\n\n## Verification\n- `python3 -c \"print('ok')\"`\n", encoding="utf-8")
                run_dir = repo / ".phase-loop" / "runs" / "test-run"
                # First create valid generic verification evidence so missing-artifact gate doesn't interfere
                run_verification(repo, run_dir, [[sys.executable, "-c", "print('ok')"]], None, None, 5)

                scenarios = [
                    ("missing", None),
                    ("stale", {"status": "stale"}),
                    ("wrong_candidate", {"status": "wrong_candidate"}),
                    ("wrong_external_head", {"status": "wrong_external_head"}),
                    ("invalid_grammar", {"status": "verified", "grammar_status": "valid"}),
                    ("mutation_block", {"status": "mutation_block"}),
                ]

                for scenario_name, proofgate_meta in scenarios:
                    if scenario_name == "invalid_grammar":
                        plan.write_text(PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES, encoding="utf-8")
                    else:
                        plan.write_text(
                            "# PROOFGATE\n\n## Verification\n- `python3 -c \"print('ok')\"`\n",
                            encoding="utf-8",
                        )
                    automation_payload = {
                        "status": "complete",
                        "verification_status": "passed",
                        "human_required": False,
                    }
                    if proofgate_meta is not None:
                        automation_payload["proofgate"] = proofgate_meta

                    closeout = build_phase_loop_closeout(
                        phase_alias="PROOFGATE",
                        plan_path=plan,
                        terminal_summary={
                            "terminal_status": "complete",
                            "verification_status": "passed",
                            "artifact_paths": {"root": str(run_dir)},
                        },
                        automation=automation_payload,
                    )
                    if not isinstance(closeout, dict) or closeout.get("terminal_status") != "blocked":
                        raise AssertionError(
                            f"PROOFGATE closeout missing proofgate attestation verification capability for scenario {scenario_name}"
                        )
                    self.assertEqual(closeout.get("terminal_status"), "blocked", f"Scenario {scenario_name} must block closeout")
                    self.assertEqual(closeout.get("blocker", {}).get("blocker_class"), "contract_bug")
                    self.assertFalse(closeout.get("blocker", {}).get("human_required", True))
                    if scenario_name == "invalid_grammar":
                        self.assertEqual(
                            closeout.get("blocker", {}).get("reason"),
                            "missing_path_entered_control",
                            "closeout must block on reparsing the invalid acceptance bytes",
                        )

                # Local JSON with internally consistent computed hashes and proofgate-app[bot] text MUST explicitly reject
                core_obj_loc = {
                    "schema": "proofgate_attested_core.v1",
                    "sequence": 1,
                    "repository": "Consiliency/agent-harness",
                    "workflow_path": ".github/workflows/proofgate-receipt-attestation.yml",
                    "environment": "proofgate-receipt-head-v1",
                }
                core_text_loc = json.dumps(core_obj_loc, sort_keys=True, separators=(",", ":"))
                core_dig_loc = hashlib.sha256(core_text_loc.encode("utf-8")).hexdigest()
                wf_file_loc = Path(__file__).resolve().parents[2] / ".github/workflows/proofgate-receipt-attestation.yml"
                wf_bytes_loc = wf_file_loc.read_bytes() if wf_file_loc.exists() else b"name: proofgate"
                wf_dig_loc = hashlib.sha1(b"blob " + str(len(wf_bytes_loc)).encode("utf-8") + b"\x00" + wf_bytes_loc).hexdigest()
                bundle_dig_loc = hashlib.sha256((core_dig_loc + wf_dig_loc).encode("utf-8")).hexdigest()
                head_oid_loc = hashlib.sha1(b"commit 0\x00").hexdigest()

                proof_file_loc = run_dir / "proofgate_attestation_proof.json"
                proof_file_loc.write_text(json.dumps({
                    "status": "verified",
                    "phase": "PROOFGATE",
                    "verification_status": "satisfied",
                    "repository_id": "1280382652",
                    "sequence": 1,
                    "external_head_oid": head_oid_loc,
                    "workflow_sha": wf_dig_loc,
                    "core_sha256": core_dig_loc,
                    "bundle_sha256": bundle_dig_loc,
                    "attestation_bundle": {
                        "status": "verified",
                        "signer": "proofgate-app[bot]",
                        "repository": "Consiliency/agent-harness",
                        "workflow_path": ".github/workflows/proofgate-receipt-attestation.yml",
                    },
                    "core_bytes": core_text_loc,
                }), encoding="utf-8")

                local_closeout = build_phase_loop_closeout(
                    phase_alias="PROOFGATE",
                    plan_path=plan,
                    terminal_summary={
                        "terminal_status": "complete",
                        "verification_status": "passed",
                        "artifact_paths": {"root": str(run_dir)},
                    },
                    automation={
                        "status": "complete",
                        "verification_status": "passed",
                        "human_required": False,
                        "proofgate": {"evidence_kind": "local_json", "decisive": False},
                    },
                )
                self.assertEqual(local_closeout.get("terminal_status"), "blocked", "Local JSON attestation proof must explicitly reject closeout")

                # Remove local json before the production positive
                if proof_file_loc.exists():
                    proof_file_loc.unlink()

                # Production positive: `complete` closeout is reachable only through the external
                # observation boundary. The caller supplies no receipt tree, no attestation mapping,
                # and no `evidence_kind`/`decisive`/status/hash/identity/receipt bytes — only the
                # locator, the immutable expected configuration and a recording boundary.
                exp = PROOFGATE_EXPECTED_CONFIG_V1
                head_oid_pos = hashlib.sha1(b"commit 1\x00").hexdigest()
                pos_request = ProofgateObservationRequest(
                    repository=exp.repository_name,
                    ref=exp.accepted_refs[0],
                    environment=exp.environment_name,
                    external_head_ref=exp.external_head_ref,
                    candidate_oid=head_oid_pos,
                    plan_path=str(plan),
                    sequence=1,
                )
                pos_boundary = RecordingObservationBoundary(
                    conforming_observation(
                        exp,
                        external_head_oid=head_oid_pos,
                        candidate_oid=head_oid_pos,
                        plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
                    )
                )

                pos_closeout = build_phase_loop_closeout(
                    phase_alias="PROOFGATE",
                    plan_path=plan,
                    terminal_summary={
                        "terminal_status": "complete",
                        "verification_status": "passed",
                        "artifact_paths": {"root": str(run_dir)},
                    },
                    automation={
                        "status": "complete",
                        "verification_status": "passed",
                        "human_required": False,
                    },
                    proofgate_request=pos_request,
                    proofgate_expected=exp,
                    proofgate_boundary=pos_boundary,
                )
                self.assertIsInstance(pos_closeout, dict, "closeout must return a dict for the valid scenario")
                self.assertEqual(
                    pos_boundary.calls, (pos_request,),
                    "Closeout must observe the external boundary exactly once with exactly the locator",
                )
                self.assertEqual(
                    pos_closeout.get("terminal_status"), "complete",
                    "Externally observed closeout scenario must return terminal_status='complete'",
                )

        run_proofgate_contract(nodeid, _contract)



    def _plan(self, repo: Path) -> Path:
        plan = repo / "plans/phase-plan-v1-RG.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# RG\n", encoding="utf-8")
        return plan

    def _closeout(self, plan: Path, run_dir: Path) -> dict:
        return build_phase_loop_closeout(
            phase_alias="RG",
            plan_path=plan,
            terminal_summary={
                "terminal_status": "complete",
                "verification_status": "passed",
                "artifact_paths": {"root": str(run_dir)},
            },
            automation={"status": "complete", "verification_status": "passed", "human_required": False},
        )


if __name__ == "__main__":
    unittest.main()
