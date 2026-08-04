"""test_proofgate_receipts.py — PROOFGATE receipts and receipt chain tests."""

import copy
import concurrent.futures
import json
import subprocess
import threading
import pytest

from .proofgate_tdd_guard import ProofgateMissingCapabilityError, guard_proofgate_nodeid, run_proofgate_contract


def test_bootstrap_records_are_single_use_and_server_bound():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_bootstrap_records_are_single_use_and_server_bound"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "BootstrapRecordStore"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing BootstrapRecordStore capability")

        store = proofgate_receipts.BootstrapRecordStore()
        rec = store.issue_bootstrap_record(
            server_id="srv-prod-1",
            pr_number=130,
            head_sha="head123",
            base_sha="base456",
            token="tok-123",
        )
        assert store.validate_bootstrap_record(rec, expected_server_id="srv-prod-1", expected_pr_number=130)
        with pytest.raises(proofgate_receipts.BootstrapRecordError, match="single_use"):
            store.validate_bootstrap_record(rec, expected_server_id="srv-prod-1", expected_pr_number=130)
        rec2 = store.issue_bootstrap_record(
            server_id="srv-prod-1",
            pr_number=130,
            head_sha="head123",
            base_sha="base456",
            token="tok-456",
        )
        with pytest.raises(proofgate_receipts.BootstrapRecordError, match="server_bound"):
            store.validate_bootstrap_record(rec2, expected_server_id="srv-prod-2", expected_pr_number=130)

    run_proofgate_contract(nodeid, _contract)


def test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill(tmp_path):
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "ProofgateReceiptSupervisor"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ProofgateReceiptSupervisor capability")

        git_repo = tmp_path / "receipts_repo"
        external_repo = tmp_path / "external_receipt_head.git"
        supervisor = proofgate_receipts.ProofgateReceiptSupervisor(
            repo_path=git_repo,
            external_repo_path=external_repo,
        )

        required_methods = (
            "append_receipt",
            "verify_chain",
            "verify_records",
            "publish_external_head_cas",
            "reconstruct_verified_history",
            "verify_history_change_kinds",
            "recover_interrupted_update",
        )
        missing_methods = [name for name in required_methods if not callable(getattr(supervisor, name, None))]
        if missing_methods:
            raise ProofgateMissingCapabilityError(
                f"proofgate_receipts missing receipt-history capability: {', '.join(missing_methods)}"
            )

        def _record(record: dict) -> None:
            assert isinstance(record, dict)
            required = {
                "append",
                "append_filename",
                "append_sha256",
                "bundle",
                "bundle_filename",
                "bundle_sha256",
                "commit_oid",
                "core",
                "core_filename",
                "core_sha256",
            }
            assert required.issubset(record), f"receipt record lacks canonical fields: {required - set(record)}"
            assert record["core"]["schema"] == "proofgate_attested_core.v1"
            assert record["append"]["schema"] == "proofgate_external_head_append.v1"
            assert record["append"]["core_sha256"] == record["core_sha256"]
            assert record["append"]["bundle_sha256"] == record["bundle_sha256"]
            assert record["core_filename"].endswith(f"-{record['core_sha256']}.json")
            assert record["append_filename"].endswith(f"-{record['append_sha256']}.json")
            assert record["core_sha256"] not in record["core"].values()
            assert "core_sha256" not in record["core"]
            assert record["bundle"].get("signer") == "github-actions[bot]"
            assert isinstance(record["bundle"].get("signature"), str) and record["bundle"]["signature"]

        def _changes(commit_oid: str, *, root: bool) -> list[tuple[str, str]]:
            command = ["git", "diff-tree", "--no-commit-id", "--name-status", "-r"]
            if root:
                command.append("--root")
            command.append(commit_oid)
            raw = subprocess.run(command, cwd=git_repo, capture_output=True, text=True, check=True).stdout
            return [tuple(line.split("\t", 1)) for line in raw.splitlines() if line]

        # Zero-parent genesis commit
        r1 = supervisor.append_receipt(subject="PROOFGATE-AC-1", payload={"step": 1})
        assert supervisor.verify_chain()
        _record(r1)

        # Independently observe raw disk and real commit tuples rather than trusting a boolean.
        assert (git_repo / ".git").is_dir(), "Receipt repository must be initialized git repo"
        assert external_repo != git_repo
        assert subprocess.run(
            ["git", "--git-dir", str(external_repo), "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == "true"
        latest_file = git_repo / "latest.json"
        assert latest_file.exists(), "latest.json must exist on disk after genesis commit"
        latest_data = json.loads(latest_file.read_text(encoding="utf-8"))
        assert latest_data["append_sha256"] == r1["append_sha256"]
        assert latest_data["core_sha256"] == r1["core_sha256"]
        assert set(_changes(r1["commit_oid"], root=True)) == {
            ("A", r1["core_filename"]),
            ("A", r1["bundle_filename"]),
            ("A", r1["append_filename"]),
            ("A", "latest.json"),
        }

        # One-parent appends
        r2 = supervisor.append_receipt(subject="PROOFGATE-AC-1", payload={"step": 2})
        r3 = supervisor.append_receipt(subject="PROOFGATE-AC-1", payload={"step": 3})
        assert supervisor.verify_chain()
        _record(r2)
        _record(r3)
        assert r2["append"]["previous_append_sha256"] == r1["append_sha256"]
        assert r3["append"]["previous_append_sha256"] == r2["append_sha256"]
        assert supervisor.verify_records([r1, r2, r3]), "the rollback prefix must itself remain a valid signed history"
        assert set(_changes(r2["commit_oid"], root=False)) == {
            ("A", r2["core_filename"]),
            ("A", r2["bundle_filename"]),
            ("A", r2["append_filename"]),
            ("M", "latest.json"),
        }

        # A core self-digest is a cycle, not an external binding, and must be refused.
        self_referential = copy.deepcopy(r1)
        self_referential["core"]["core_sha256"] = r1["core_sha256"]
        assert not supervisor.verify_records([self_referential, r2, r3])

        # Tamper the actual canonical structures and bindings returned by the receipt writer.
        tampered_core = copy.deepcopy(r1)
        tampered_core["core"]["payload"] = {"step": 999}
        assert not supervisor.verify_records([tampered_core, r2, r3])

        tampered_filename = copy.deepcopy(r1)
        tampered_filename["core_filename"] = tampered_filename["core_filename"].replace(".json", "-tampered.json")
        assert not supervisor.verify_records([tampered_filename, r2, r3])
        tampered_append = copy.deepcopy(r2)
        tampered_append["append"]["core_sha256"] = r1["core_sha256"]
        assert not supervisor.verify_records([r1, tampered_append, r3])

        # Truncation check
        assert not supervisor.verify_records([r1], expected_length=3)

        # Fork / backfill / rewrite check over real Git object/ref history
        forked = [copy.deepcopy(r1), copy.deepcopy(r2), proofgate_receipts.create_receipt(parent=r1, subject="PROOFGATE-AC-1", payload={"step": 3})]
        assert not supervisor.verify_records(forked)

        backfilled = [copy.deepcopy(r2), copy.deepcopy(r1), copy.deepcopy(r3)]
        assert not supervisor.verify_records(backfilled)

        # The exact observed change kinds are structural evidence; adding/replacing them in
        # the wrong generation must fail even when all digest fields are otherwise unchanged.
        history = supervisor.reconstruct_verified_history()
        assert history["records"] == [r1, r2, r3]
        assert history["tip_append_sha256"] == r3["append_sha256"]
        assert supervisor.verify_history_change_kinds(history)
        swapped_kinds = copy.deepcopy(history)
        swapped_kinds["records"][0]["change_tuples"][-1]["change_kind"] = "M"
        swapped_kinds["records"][1]["change_tuples"][-1]["change_kind"] = "A"
        assert not supervisor.verify_history_change_kinds(swapped_kinds)

        # Two distinct one-parent children of the same exact external head must race through
        # the publication CAS.  Choosing one from a Python list is not publication evidence.
        candidate_a = proofgate_receipts.create_receipt(parent=r3, subject="PROOFGATE-AC-1", payload={"step": "4a"})
        candidate_b = proofgate_receipts.create_receipt(parent=r3, subject="PROOFGATE-AC-1", payload={"step": "4b"})
        assert candidate_a["append_sha256"] != candidate_b["append_sha256"]
        assert getattr(supervisor, "external_head_ref", None) == "refs/heads/proofgate-receipt-head-v1"
        start = threading.Barrier(2)

        def _publish(candidate):
            lane = proofgate_receipts.ProofgateReceiptSupervisor(
                repo_path=git_repo,
                external_repo_path=external_repo,
            )
            start.wait(timeout=10)
            return lane.publish_external_head_cas(
                expected_head_oid=r3["commit_oid"], candidate=candidate
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            publications = tuple(executor.map(_publish, (candidate_a, candidate_b)))
        required_publication_fields = {
            "schema",
            "outcome",
            "expected_head_oid",
            "observed_head_oid",
            "candidate_append_sha256",
            "candidate_commit_oid",
            "published_head_oid",
            "record",
        }
        assert all(isinstance(publication, dict) and set(publication) == required_publication_fields for publication in publications)
        assert all(publication["schema"] == "proofgate_external_head_publication.v1" for publication in publications)
        assert all(publication["expected_head_oid"] == r3["commit_oid"] for publication in publications)
        assert {publication["outcome"] for publication in publications} == {"published", "stale"}
        external_head = subprocess.run(
            ["git", "--git-dir", str(external_repo), "rev-parse", supervisor.external_head_ref],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for publication in publications:
            parents = subprocess.run(
                ["git", "show", "-s", "--format=%P", publication["candidate_commit_oid"]],
                cwd=git_repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip().split()
            assert parents == [r3["commit_oid"]]

        winner = next(publication for publication in publications if publication["outcome"] == "published")
        loser = next(publication for publication in publications if publication["outcome"] == "stale")
        assert external_head == winner["published_head_oid"]
        assert winner["published_head_oid"] == winner["candidate_commit_oid"]
        assert winner["observed_head_oid"] == r3["commit_oid"]
        assert loser["observed_head_oid"] == winner["published_head_oid"]
        assert loser["published_head_oid"] == winner["published_head_oid"]
        replay = supervisor.publish_external_head_cas(
            expected_head_oid=r3["commit_oid"],
            candidate=candidate_a if loser["candidate_append_sha256"] == candidate_a["append_sha256"] else candidate_b,
        )
        assert replay["outcome"] == "stale"
        assert replay["candidate_commit_oid"] == loser["candidate_commit_oid"]
        assert replay["published_head_oid"] == winner["published_head_oid"]

        missing_pointer = copy.deepcopy(r2)
        del missing_pointer["append"]["previous_append_sha256"]
        assert not supervisor.verify_records([r1, missing_pointer, r3])
        assert not supervisor.verify_records([r1, r2], expected_append_sha256=r3["append_sha256"])

        latest_bytes = latest_file.read_bytes()
        latest_file.unlink()
        assert not supervisor.verify_chain()
        latest_file.write_bytes(latest_bytes)
        assert supervisor.verify_chain()

        recovered_once = supervisor.recover_interrupted_update(expected_parent=r3["commit_oid"], pending_record=winner["record"])
        recovered_twice = supervisor.recover_interrupted_update(expected_parent=r3["commit_oid"], pending_record=winner["record"])
        assert recovered_once == recovered_twice
        reconstructed = supervisor.reconstruct_verified_history()
        assert reconstructed["records"][-1] == recovered_once
        assert supervisor.verify_chain()

        # Replacing both pointers with an older, otherwise-valid signed prefix is a rollback,
        # not recovery.  The fixed external head and latest.json must refuse it together.
        winner_head = winner["published_head_oid"]
        latest_after_winner = latest_file.read_bytes()
        older_latest = subprocess.run(
            ["git", "--git-dir", str(external_repo), "show", f"{r3['commit_oid']}:latest.json"],
            capture_output=True,
            check=True,
        ).stdout
        subprocess.run(
            [
                "git",
                "--git-dir",
                str(external_repo),
                "update-ref",
                supervisor.external_head_ref,
                r3["commit_oid"],
                winner_head,
            ],
            capture_output=True,
            check=True,
        )
        latest_file.write_bytes(older_latest)
        assert subprocess.run(
            ["git", "--git-dir", str(external_repo), "rev-parse", supervisor.external_head_ref],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == r3["commit_oid"]
        assert not supervisor.verify_chain(), "older signed prefix replaced fixed head/latest.json without refusal"
        subprocess.run(
            [
                "git",
                "--git-dir",
                str(external_repo),
                "update-ref",
                supervisor.external_head_ref,
                winner_head,
                r3["commit_oid"],
            ],
            capture_output=True,
            check=True,
        )
        latest_file.write_bytes(latest_after_winner)
        assert subprocess.run(
            ["git", "--git-dir", str(external_repo), "rev-parse", supervisor.external_head_ref],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip() == winner_head
        assert supervisor.verify_chain()

    run_proofgate_contract(nodeid, _contract)


def test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "ProofgateReceiptSupervisor"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ProofgateReceiptSupervisor capability")

        supervisor = proofgate_receipts.ProofgateReceiptSupervisor(
            expected_workflow=".github/workflows/proofgate-receipt-attestation.yml",
            expected_signer="github-actions[bot]",
            expected_source_blob="sha256:abc123def456",
            expected_subject="PROOFGATE-AC-1",
        )
        valid_rec = supervisor.create_record(
            workflow=".github/workflows/proofgate-receipt-attestation.yml",
            signer="github-actions[bot]",
            source_blob="sha256:abc123def456",
            subject="PROOFGATE-AC-1",
            timestamp=1700000000,
        )
        assert supervisor.validate_record(valid_rec)

        bad_wf = valid_rec.copy()
        bad_wf["workflow"] = ".github/workflows/other.yml"
        assert not supervisor.validate_record(bad_wf)

        bad_signer = valid_rec.copy()
        bad_signer["signer"] = "unauthorized-user"
        assert not supervisor.validate_record(bad_signer)

        bad_blob = valid_rec.copy()
        bad_blob["source_blob"] = "sha256:badblob"
        assert not supervisor.validate_record(bad_blob)

        bad_subj = valid_rec.copy()
        bad_subj["subject"] = "OTHER-AC"
        assert not supervisor.validate_record(bad_subj)

        bad_ts = valid_rec.copy()
        bad_ts["timestamp"] = 0
        assert not supervisor.validate_record(bad_ts)

    run_proofgate_contract(nodeid, _contract)


def test_implementation_authorization_requires_activation_preflight_panel_and_red_order():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_implementation_authorization_requires_activation_preflight_panel_and_red_order"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "ImplementationAuthorizationSequence"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing ImplementationAuthorizationSequence capability")

        auth = proofgate_receipts.ImplementationAuthorizationSequence()
        auth.record_step("activation")
        auth.record_step("preflight")
        auth.record_step("panel")
        auth.record_step("red_order")
        assert auth.verify_sequence()

        bad_auth = proofgate_receipts.ImplementationAuthorizationSequence()
        bad_auth.record_step("panel")
        bad_auth.record_step("activation")
        with pytest.raises(proofgate_receipts.AuthorizationOrderError):
            bad_auth.verify_sequence()

    run_proofgate_contract(nodeid, _contract)


def test_runner_routes_reject_child_claims_and_missing_latest_external_head():
    nodeid = "phase-loop-runtime/tests/test_proofgate_receipts.py::test_runner_routes_reject_child_claims_and_missing_latest_external_head"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import proofgate_receipts
        except ImportError as err:
            raise ProofgateMissingCapabilityError("proofgate_receipts module missing") from err

        if not hasattr(proofgate_receipts, "RunnerRouteValidator"):
            raise ProofgateMissingCapabilityError("proofgate_receipts missing RunnerRouteValidator capability")

        router = proofgate_receipts.RunnerRouteValidator()
        with pytest.raises(proofgate_receipts.RunnerRouteError, match="child_claim"):
            router.validate_route_claim(pid=9999, is_child_process=True)

        with pytest.raises(proofgate_receipts.RunnerRouteError, match="missing_latest_external_head"):
            router.validate_external_head(expected_head="sha:head-1", current_head=None)

        # Stale writer / concurrent non-force winner check
        with pytest.raises(proofgate_receipts.RunnerRouteError, match="stale_writer"):
            router.validate_concurrent_push(expected_head="sha:head-1", remote_head="sha:head-2_winner")

    run_proofgate_contract(nodeid, _contract)
