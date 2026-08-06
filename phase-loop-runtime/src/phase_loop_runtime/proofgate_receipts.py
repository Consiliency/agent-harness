"""proofgate_receipts.py — PROOFGATE receipts, receipt supervisor, and attestation services."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class BootstrapRecordError(ValueError):
    """Raised when a bootstrap record is reused or bound to a different server/PR."""


class AuthorizationOrderError(ValueError):
    """Raised when implementation authorization steps are executed out of order."""


class RunnerRouteError(ValueError):
    """Raised when a child process or stale writer attempts a runner route claim."""


class ProofgateReceiptError(ValueError):
    """Raised when receipt structure, chain, or attestation verification fails."""


class BootstrapRecordStore:
    """Store for single-use, server-bound bootstrap records."""

    def __init__(self) -> None:
        self._issued: dict[str, dict[str, Any]] = {}

    def issue_bootstrap_record(
        self,
        server_id: str,
        pr_number: int,
        head_sha: str,
        base_sha: str,
        token: str,
    ) -> dict[str, Any]:
        record = {
            "server_id": server_id,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "token": token,
            "used": False,
            "record_id": f"{server_id}-{pr_number}-{token}",
        }
        self._issued[record["record_id"]] = record
        return record

    def validate_bootstrap_record(
        self,
        record: dict[str, Any],
        expected_server_id: str,
        expected_pr_number: int,
    ) -> bool:
        if record.get("used"):
            raise BootstrapRecordError("single_use: bootstrap record already consumed")
        if record.get("server_id") != expected_server_id:
            raise BootstrapRecordError("server_bound: server_id mismatch")
        if record.get("pr_number") != expected_pr_number:
            raise BootstrapRecordError("server_bound: pr_number mismatch")
        record["used"] = True
        return True


def create_receipt(
    parent: dict[str, Any] | None = None,
    subject: str = "PROOFGATE-AC-1",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Constructs a unit-double proofgate receipt record dictionary."""
    seq = (parent["core"]["sequence"] + 1) if parent else 1
    prev_core_digest = parent["core_sha256"] if parent else None
    prev_append_sha256 = parent["append_sha256"] if parent else None
    prev_commit_oid = parent["commit_oid"] if parent else None

    core = {
        "schema": "proofgate_attested_core.v1",
        "sequence": seq,
        "repository": "Consiliency/agent-harness",
        "workflow_path": ".github/workflows/proofgate-receipt-attestation.yml",
        "environment": "proofgate-receipt-head-v1",
        "previous_core_digest": prev_core_digest,
        "expected_previous_external_head_oid": prev_commit_oid,
        "subject": subject,
        "payload": payload or {},
    }
    core_bytes = json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    core_sha256 = hashlib.sha256(core_bytes).hexdigest()
    seq_str = f"{seq:020d}"
    core_filename = f"cores/{seq_str}-{core_sha256}.json"

    bundle = {
        "signer": "github-actions[bot]",
        "signature": f"unit-double-bundle-{seq}-{core_sha256[:16]}",
        "evidence_kind": "unit_double",
        "decisive": False,
    }
    bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    bundle_filename = f"bundles/{seq_str}-{bundle_sha256}.json"

    append = {
        "schema": "proofgate_external_head_append.v1",
        "sequence": seq,
        "core_sha256": core_sha256,
        "bundle_sha256": bundle_sha256,
        "previous_append_sha256": prev_append_sha256,
        "expected_previous_external_head_oid": prev_commit_oid,
    }
    append_bytes = json.dumps(append, sort_keys=True, separators=(",", ":")).encode("utf-8")
    append_sha256 = hashlib.sha256(append_bytes).hexdigest()
    append_filename = f"appends/{seq_str}-{append_sha256}.json"

    commit_oid = parent["commit_oid"] if parent else "0" * 40

    change_kind_latest = "A" if seq == 1 else "M"
    change_tuples = [
        {"change_kind": "A", "path": core_filename},
        {"change_kind": "A", "path": bundle_filename},
        {"change_kind": "A", "path": append_filename},
        {"change_kind": change_kind_latest, "path": "latest.json"},
    ]

    return {
        "append": append,
        "append_filename": append_filename,
        "append_sha256": append_sha256,
        "bundle": bundle,
        "bundle_filename": bundle_filename,
        "bundle_sha256": bundle_sha256,
        "commit_oid": commit_oid,
        "core": core,
        "core_filename": core_filename,
        "core_sha256": core_sha256,
        "change_tuples": change_tuples,
        "evidence_kind": "unit_double",
        "decisive": False,
    }


class LocalBareRepositoryPublicationDouble:
    """Quarantined publication double for local bare repository unit tests."""

    def __init__(self, repo_path: Path, external_repo_path: Path | None, external_head_ref: str) -> None:
        self.repo_path = repo_path
        self.external_repo_path = external_repo_path
        self.external_head_ref = external_head_ref

    def publish_cas(self, expected_head_oid: str, candidate: dict[str, Any]) -> dict[str, Any]:
        if not self.external_repo_path:
            return {
                "schema": "proofgate_external_head_publication.v1",
                "outcome": "stale",
                "expected_head_oid": expected_head_oid,
                "observed_head_oid": None,
                "candidate_append_sha256": candidate["append_sha256"],
                "candidate_commit_oid": candidate.get("commit_oid", "0" * 40),
                "published_head_oid": None,
                "record": candidate,
            }

        curr_res = subprocess.run(
            ["git", "--git-dir", str(self.external_repo_path), "rev-parse", self.external_head_ref],
            capture_output=True,
            text=True,
            check=False,
        )
        current_external_head = curr_res.stdout.strip() if curr_res.returncode == 0 else None

        cand_oid = candidate.get("commit_oid", "0" * 40)
        obj_chk = subprocess.run(
            ["git", "cat-file", "-e", cand_oid],
            cwd=self.repo_path,
            capture_output=True,
            check=False,
        )
        if obj_chk.returncode != 0 or cand_oid == expected_head_oid:
            index_file = tempfile.mktemp(prefix="tmp_idx_")
            env = dict(os.environ)
            env["GIT_INDEX_FILE"] = index_file
            try:
                if expected_head_oid and expected_head_oid != "0" * 40:
                    subprocess.run(
                        ["git", "read-tree", expected_head_oid],
                        cwd=self.repo_path,
                        env=env,
                        check=True,
                        capture_output=True,
                    )

                for fname, val in [
                    (candidate["core_filename"], json.dumps(candidate["core"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
                    (candidate["bundle_filename"], json.dumps(candidate["bundle"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
                    (candidate["append_filename"], json.dumps(candidate["append"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
                    ("latest.json", json.dumps({"append_sha256": candidate["append_sha256"], "core_sha256": candidate["core_sha256"]}, sort_keys=True, separators=(",", ":")).encode("utf-8")),
                ]:
                    hash_res = subprocess.run(
                        ["git", "hash-object", "-w", "--stdin"],
                        cwd=self.repo_path,
                        input=val,
                        capture_output=True,
                        check=True,
                    )
                    blob_sha = hash_res.stdout.decode("utf-8").strip()
                    subprocess.run(
                        ["git", "update-index", "--add", "--cacheinfo", "100644", blob_sha, fname],
                        cwd=self.repo_path,
                        env=env,
                        check=True,
                        capture_output=True,
                    )

                tree_res = subprocess.run(
                    ["git", "write-tree"],
                    cwd=self.repo_path,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                tree_sha = tree_res.stdout.strip()

                parent_args = ["-p", expected_head_oid] if (expected_head_oid and expected_head_oid != "0" * 40) else []
                commit_res = subprocess.run(
                    ["git", "commit-tree", tree_sha, *parent_args, "-m", f"receipt append {candidate['append']['sequence']}"],
                    cwd=self.repo_path,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                cand_oid = commit_res.stdout.strip()
                candidate["commit_oid"] = cand_oid
            finally:
                if os.path.exists(index_file):
                    os.unlink(index_file)

        push_res = subprocess.run(
            ["git", "push", "-q", str(self.external_repo_path), f"{cand_oid}:{self.external_head_ref}"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

        curr_after = subprocess.run(
            ["git", "--git-dir", str(self.external_repo_path), "rev-parse", self.external_head_ref],
            capture_output=True,
            text=True,
            check=False,
        )
        observed_head = curr_after.stdout.strip() if curr_after.returncode == 0 else None

        if push_res.returncode == 0 and observed_head == cand_oid:
            for fname, val in [
                (candidate["core_filename"], json.dumps(candidate["core"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
                (candidate["bundle_filename"], json.dumps(candidate["bundle"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
                (candidate["append_filename"], json.dumps(candidate["append"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
                ("latest.json", json.dumps({"append_sha256": candidate["append_sha256"], "core_sha256": candidate["core_sha256"]}, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            ]:
                fpath = self.repo_path / fname
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_bytes(val)

            return {
                "schema": "proofgate_external_head_publication.v1",
                "outcome": "published",
                "expected_head_oid": expected_head_oid,
                "observed_head_oid": expected_head_oid,
                "candidate_append_sha256": candidate["append_sha256"],
                "candidate_commit_oid": cand_oid,
                "published_head_oid": cand_oid,
                "record": candidate,
            }
        else:
            return {
                "schema": "proofgate_external_head_publication.v1",
                "outcome": "stale",
                "expected_head_oid": expected_head_oid,
                "observed_head_oid": observed_head,
                "candidate_append_sha256": candidate["append_sha256"],
                "candidate_commit_oid": cand_oid,
                "published_head_oid": observed_head,
                "record": candidate,
            }


class ProofgateReceiptSupervisor:
    """Supervisor for receipt writing, external head synchronization, and CAS publication."""

    def __init__(
        self,
        repo_path: Path | str = ".",
        external_repo_path: Path | str | None = None,
        expected_workflow: str = ".github/workflows/proofgate-receipt-attestation.yml",
        expected_signer: str = "github-actions[bot]",
        expected_source_blob: str = "",
        expected_subject: str = "PROOFGATE-AC-1",
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.external_repo_path = Path(external_repo_path).resolve() if external_repo_path else None
        self.expected_workflow = expected_workflow
        self.expected_signer = expected_signer
        self.expected_source_blob = expected_source_blob
        self.expected_subject = expected_subject
        self.external_head_ref = "refs/heads/proofgate-receipt-head-v1"
        self._records: list[dict[str, Any]] = []

        is_git_repo = False
        if self.repo_path.exists():
            if (self.repo_path / ".git").exists():
                is_git_repo = True
            else:
                chk = subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=self.repo_path,
                    capture_output=True,
                    check=False,
                )
                if chk.returncode == 0:
                    is_git_repo = True

        if not is_git_repo:
            self.repo_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=self.repo_path, check=True)
            subprocess.run(["git", "config", "user.name", "proofgate-bot"], cwd=self.repo_path, check=True)
            subprocess.run(["git", "config", "user.email", "bot@example.com"], cwd=self.repo_path, check=True)

        if self.external_repo_path and not self.external_repo_path.exists():
            self.external_repo_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", "--bare"], cwd=self.external_repo_path, check=True)

        self._publication_double = LocalBareRepositoryPublicationDouble(
            self.repo_path, self.external_repo_path, self.external_head_ref
        )

    def _contained_path(self, rel_path: str | Path) -> Path:
        target = (self.repo_path / rel_path).resolve()
        base = self.repo_path.resolve()
        try:
            target.relative_to(base)
        except ValueError:
            raise ProofgateReceiptError(f"path traversal rejected: {rel_path}")
        return target

    def create_record(
        self,
        workflow: str,
        signer: str,
        source_blob: str,
        subject: str,
        timestamp: int,
    ) -> dict[str, Any]:
        return {
            "workflow": workflow,
            "signer": signer,
            "source_blob": source_blob,
            "subject": subject,
            "timestamp": timestamp,
        }

    def validate_record(self, record: dict[str, Any]) -> bool:
        if record.get("workflow") != self.expected_workflow:
            return False
        if record.get("signer") != self.expected_signer:
            return False
        if self.expected_source_blob and record.get("source_blob") != self.expected_source_blob:
            return False
        if self.expected_subject and record.get("subject") != self.expected_subject:
            return False
        if not record.get("timestamp") or record["timestamp"] <= 0:
            return False
        return True

    def append_receipt(self, subject: str = "PROOFGATE-AC-1", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        parent = self._records[-1] if self._records else None
        rec = create_receipt(parent=parent, subject=subject, payload=payload)

        expected_head = parent["commit_oid"] if parent else ""
        pub = self.publish_external_head_cas(expected_head_oid=expected_head, candidate=rec)
        if pub.get("outcome") == "published":
            rec = pub["record"]
            if not any(r.get("append_sha256") == rec.get("append_sha256") for r in self._records):
                self._records.append(rec)
        return rec

    def _sync_records_from_disk(self) -> list[dict[str, Any]]:
        appends_dir = self.repo_path / "appends"
        if not appends_dir.exists():
            return self._records

        append_files = sorted(appends_dir.glob("*.json"))
        records = []
        for app_file in append_files:
            try:
                append_data = json.loads(app_file.read_text(encoding="utf-8"))
                seq = append_data.get("sequence", 0)
                seq_str = f"{seq:020d}"

                core_files = list((self.repo_path / "cores").glob(f"{seq_str}-*.json"))
                bundle_files = list((self.repo_path / "bundles").glob(f"{seq_str}-*.json"))

                if not core_files or not bundle_files:
                    continue

                core_file = core_files[0]
                bundle_file = bundle_files[0]

                core_data = json.loads(core_file.read_text(encoding="utf-8"))
                bundle_data = json.loads(bundle_file.read_text(encoding="utf-8"))

                core_bytes = json.dumps(core_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                core_sha256 = hashlib.sha256(core_bytes).hexdigest()

                bundle_bytes = json.dumps(bundle_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()

                append_bytes = json.dumps(append_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                append_sha256 = hashlib.sha256(append_bytes).hexdigest()

                change_kind_latest = "A" if seq == 1 else "M"
                change_tuples = [
                    {"change_kind": "A", "path": core_file.relative_to(self.repo_path).as_posix()},
                    {"change_kind": "A", "path": bundle_file.relative_to(self.repo_path).as_posix()},
                    {"change_kind": "A", "path": app_file.relative_to(self.repo_path).as_posix()},
                    {"change_kind": change_kind_latest, "path": "latest.json"},
                ]

                rec = {
                    "append": append_data,
                    "append_filename": app_file.relative_to(self.repo_path).as_posix(),
                    "append_sha256": append_sha256,
                    "bundle": bundle_data,
                    "bundle_filename": bundle_file.relative_to(self.repo_path).as_posix(),
                    "bundle_sha256": bundle_sha256,
                    "commit_oid": "0" * 40,
                    "core": core_data,
                    "core_filename": core_file.relative_to(self.repo_path).as_posix(),
                    "core_sha256": core_sha256,
                    "change_tuples": change_tuples,
                    "evidence_kind": "unit_double",
                    "decisive": False,
                }
                records.append(rec)
            except Exception:
                pass

        if records:
            ext_head = None
            if self.external_repo_path:
                res = subprocess.run(
                    ["git", "--git-dir", str(self.external_repo_path), "rev-parse", self.external_head_ref],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0:
                    ext_head = res.stdout.strip()

            for i in range(len(records) - 1):
                parent_oid = records[i + 1]["append"].get("expected_previous_external_head_oid")
                if parent_oid:
                    records[i]["commit_oid"] = parent_oid

            if ext_head:
                records[-1]["commit_oid"] = ext_head

            for r_new in records:
                for r_old in self._records:
                    if r_old.get("append_sha256") == r_new.get("append_sha256") and r_old.get("commit_oid"):
                        r_new["commit_oid"] = r_old["commit_oid"]
            self._records = records
        return self._records

    def verify_chain(self) -> bool:
        latest_file = self.repo_path / "latest.json"
        if not latest_file.exists():
            return False
        try:
            latest_data = json.loads(latest_file.read_text(encoding="utf-8"))
        except Exception:
            return False

        records = self._sync_records_from_disk()
        if not records:
            return False
        if latest_data.get("append_sha256") != records[-1]["append_sha256"]:
            return False

        if self.external_repo_path:
            ext_res = subprocess.run(
                ["git", "--git-dir", str(self.external_repo_path), "rev-parse", self.external_head_ref],
                capture_output=True,
                text=True,
                check=False,
            )
            if ext_res.returncode != 0 or ext_res.stdout.strip() != records[-1]["commit_oid"]:
                return False

        return self.verify_records(records)

    def verify_records(
        self,
        records: list[dict[str, Any]],
        expected_length: int | None = None,
        expected_append_sha256: str | None = None,
    ) -> bool:
        if expected_length is not None and len(records) != expected_length:
            return False
        if expected_append_sha256 is not None and (not records or records[-1].get("append_sha256") != expected_append_sha256):
            return False

        for i, rec in enumerate(records):
            core = rec.get("core")
            if not isinstance(core, dict) or core.get("schema") != "proofgate_attested_core.v1":
                return False
            if "core_sha256" in core or rec.get("core_sha256") in core.values():
                return False

            core_bytes = json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if hashlib.sha256(core_bytes).hexdigest() != rec.get("core_sha256"):
                return False

            if not rec.get("core_filename", "").endswith(f"-{rec['core_sha256']}.json"):
                return False

            append = rec.get("append")
            if not isinstance(append, dict) or append.get("schema") != "proofgate_external_head_append.v1":
                return False
            if append.get("core_sha256") != rec.get("core_sha256"):
                return False
            if append.get("bundle_sha256") != rec.get("bundle_sha256"):
                return False

            if not rec.get("append_filename", "").endswith(f"-{rec['append_sha256']}.json"):
                return False

            if i == 0:
                if append.get("previous_append_sha256") is not None:
                    return False
            else:
                if append.get("previous_append_sha256") != records[i - 1]["append_sha256"]:
                    return False

        return True

    def reconstruct_verified_history(self) -> dict[str, Any]:
        return {
            "records": copy.deepcopy(self._records),
            "tip_append_sha256": self._records[-1]["append_sha256"] if self._records else None,
        }

    def verify_history_change_kinds(self, history: dict[str, Any]) -> bool:
        recs = history.get("records", [])
        if not recs:
            return False
        for i, r in enumerate(recs):
            tuples = r.get("change_tuples", [])
            if not tuples:
                return False
            expected_kind = "A" if i == 0 else "M"
            last_item = tuples[-1]
            if isinstance(last_item, dict):
                if last_item.get("change_kind") != expected_kind or last_item.get("path") != "latest.json":
                    return False
            elif isinstance(last_item, (tuple, list)):
                if last_item[0] != expected_kind or last_item[1] != "latest.json":
                    return False
        return True

    def publish_external_head_cas(self, expected_head_oid: str, candidate: dict[str, Any]) -> dict[str, Any]:
        return self._publication_double.publish_cas(expected_head_oid, candidate)

    def recover_interrupted_update(self, expected_parent: str, pending_record: dict[str, Any]) -> dict[str, Any]:
        """Refuses to import unverified caller-supplied pending records into authority."""
        if self.external_repo_path and self.external_repo_path.exists():
            res = subprocess.run(
                ["git", "--git-dir", str(self.external_repo_path), "rev-parse", self.external_head_ref],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip() == pending_record.get("commit_oid"):
                records = self._sync_records_from_disk()
                for r in records:
                    if r.get("append_sha256") == pending_record.get("append_sha256"):
                        return r

        for r in self._records:
            if r.get("append_sha256") == pending_record.get("append_sha256") and r.get("commit_oid") == pending_record.get("commit_oid"):
                return r

        raise ProofgateReceiptError("unverified_pending_record_recovery_refused: external tip mismatch")


class ImplementationAuthorizationSequence:
    """Validator for implementation authorization step ordering."""

    def __init__(self) -> None:
        self.steps: list[str] = []

    def record_step(self, step: str) -> None:
        self.steps.append(step)

    def verify_sequence(self) -> bool:
        expected = ["activation", "preflight", "panel", "red_order"]
        if self.steps != expected:
            raise AuthorizationOrderError("invalid authorization step order")
        return True


class RunnerRouteValidator:
    """Validator for runner routes and external head consistency."""

    def validate_route_claim(self, pid: int, is_child_process: bool) -> None:
        if is_child_process:
            raise RunnerRouteError("child_claim: child process cannot claim runner route")

    def validate_external_head(self, expected_head: str, current_head: str | None) -> None:
        if current_head is None:
            raise RunnerRouteError("missing_latest_external_head: external head missing")
        if expected_head != current_head:
            raise RunnerRouteError("stale_writer: external head mismatch")

    def validate_concurrent_push(self, expected_head: str, remote_head: str) -> None:
        if expected_head != remote_head:
            raise RunnerRouteError("stale_writer: concurrent push detected")


class ProofgateAttestationService:
    """Verifier for GitHub Actions attestations and external observation boundaries."""

    def verify_attestation(self, attestation_data: dict[str, Any]) -> dict[str, Any]:
        """Unit-double attestation verifier returning non-decisive proof."""
        if not attestation_data.get("github_hosted"):
            raise ValueError("github_hosted_required")

        subject = attestation_data.get("subject", "")
        if not subject or not subject.startswith("cores/") or not subject.endswith(".json"):
            raise ValueError("subject_mismatch")

        fname = subject.split("/")[-1]
        parts = fname.replace(".json", "").split("-")
        if len(parts) != 2 or len(parts[0]) != 20 or len(parts[1]) != 64:
            raise ValueError("subject_mismatch")

        subj_sha256 = parts[1]
        source_blob = attestation_data.get("source_blob_sha256", "")
        if source_blob and subj_sha256 != source_blob:
            raise ValueError("source_blob_mismatch")

        core_bytes = attestation_data.get("core_bytes")
        if core_bytes is not None:
            try:
                core_obj = json.loads(core_bytes.decode("utf-8") if isinstance(core_bytes, bytes) else core_bytes)
            except Exception as exc:
                raise ValueError("malformed_core_json") from exc

            if not isinstance(core_obj, dict):
                raise ValueError("malformed_core_json")
            if "core_sha256" in core_obj:
                raise ValueError("self_digest_forbidden: core contains core_sha256 key")
            for val in core_obj.values():
                if str(val) == subj_sha256:
                    raise ValueError("self_digest_forbidden: core value equals core_sha256")

        return {
            "status": "verified",
            "evidence_kind": "unit_double",
            "decisive": False,
            "subject": subject,
            "source_blob_sha256": source_blob,
        }

    def verify_external_attestation(
        self,
        locator: Any,
        *,
        expected: Any = None,
        boundary: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Validates production transparency claims and expected policy digests over external observation boundary."""
        if isinstance(locator, dict):
            return self.verify_attestation(locator)

        if boundary is None:
            return {
                "status": "blocked",
                "authorized": False,
                "decisive": False,
                "evidence_kind": "observation_unavailable",
                "locator": locator,
                "reason": "boundary_required",
            }

        try:
            obs = boundary.observe(locator)
        except Exception as exc:
            return {
                "status": "blocked",
                "authorized": False,
                "decisive": False,
                "evidence_kind": "observation_unavailable",
                "locator": locator,
                "reason": f"boundary_exception_{type(exc).__name__}",
            }

        if obs is None:
            return {
                "status": "blocked",
                "authorized": False,
                "decisive": False,
                "evidence_kind": "observation_unavailable",
                "locator": locator,
                "reason": "missing_observation",
            }

        def _get_val(key: str, default: Any = None) -> Any:
            if isinstance(obs, dict):
                return obs.get(key, default)
            return getattr(obs, key, default)

        # 1. Schema check
        schema = _get_val("schema")
        if schema != "proofgate_external_observation.v1":
            return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

        if expected is not None:
            # 2. Repository identity
            if _get_val("repository_id") != getattr(expected, "repository_id", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("repository_owner_id") != getattr(expected, "repository_owner_id", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("repository_name") != getattr(expected, "repository_name", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 3. Locator bindings
            req_repo = getattr(locator, "repository", None)
            if req_repo and req_repo not in (getattr(expected, "repository_name", None), getattr(expected, "repository_id", None)):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            req_ref = getattr(locator, "ref", None)
            if req_ref and req_ref not in getattr(expected, "accepted_refs", ()):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            req_env = getattr(locator, "environment", None)
            if req_env and req_env != getattr(expected, "environment_name", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            req_ext_ref = getattr(locator, "external_head_ref", None)
            if req_ext_ref and (req_ext_ref != getattr(expected, "external_head_ref", None) or _get_val("external_head_ref") != getattr(expected, "external_head_ref", None)):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 4. Dedicated App Installation
            if _get_val("app_installation_id") != getattr(expected, "dedicated_app_installation_id", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("app_integration_id") != getattr(expected, "dedicated_app_integration_id", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("app_repository_selection") != getattr(expected, "app_repository_selection", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if tuple(_get_val("app_permissions") or ()) != tuple(getattr(expected, "app_permissions", ())):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 5. Branch Ruleset
            if _get_val("ruleset_name") != getattr(expected, "ruleset_name", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if not set(getattr(expected, "ruleset_required_rule_types", ())).issubset(set(_get_val("ruleset_rule_types") or ())):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if getattr(expected, "external_head_ref", None) not in tuple(_get_val("ruleset_ref_includes") or ()):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if tuple(_get_val("ruleset_bypass_actors") or ()) != (("Integration", "always", getattr(expected, "dedicated_app_integration_id", None)),):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 6. Protected Environment
            if _get_val("environment_name") != getattr(expected, "environment_name", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("environment_can_admins_bypass") is not False:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("environment_prevent_self_review") is not True:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if tuple(_get_val("environment_required_reviewer_ids") or ()) != (getattr(expected, "required_reviewer_id", None),):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 7. Broker OIDC Claim Policy
            if _get_val("broker_deployment_id") != getattr(expected, "broker_deployment_id", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("broker_key_version") != getattr(expected, "broker_key_version", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("broker_claim_policy_digest") != getattr(expected, "broker_claim_policy_digest", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            claims = dict(_get_val("oidc_claims") or ())
            if claims.get("actor") != getattr(expected, "actor", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if claims.get("aud") != getattr(expected, "oidc_audience", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if claims.get("ref") not in getattr(expected, "accepted_refs", ()):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 8. Workflow Binding
            if _get_val("workflow_ref") != getattr(expected, "workflow_ref", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("workflow_path") != getattr(expected, "workflow_path", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("workflow_sha256") != getattr(expected, "workflow_sha256", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("runner_environment") != getattr(expected, "runner_environment", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("event_name") != getattr(expected, "event_name", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("actor") != getattr(expected, "actor", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("subject") != getattr(expected, "subject", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if str(_get_val("run_id")) != str(getattr(expected, "run_id", None)):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if str(_get_val("run_attempt")) != str(getattr(expected, "run_attempt", None)):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 9. External Head & Candidate
            ext_head_oid = _get_val("external_head_oid")
            if not ext_head_oid or ext_head_oid == "0" * 40:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            cand_oid = getattr(locator, "candidate_oid", None)
            if cand_oid and _get_val("candidate_oid") != cand_oid:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 10. Plan SHA
            plan_path = getattr(locator, "plan_path", None)
            if plan_path:
                pfile = Path(plan_path)
                if not pfile.is_file():
                    return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
                psha = hashlib.sha256(pfile.read_bytes()).hexdigest()
                if _get_val("plan_sha256") != psha:
                    return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 11. Receipt Digest Chain & Sequence
            seq = _get_val("sequence")
            core_sha = _get_val("core_sha256")
            bundle_sha = _get_val("bundle_sha256")
            append_sha = _get_val("append_sha256")
            if not isinstance(seq, int) or seq < 1:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if not core_sha or _get_val("subject") != f"cores/{seq:020d}-{core_sha}.json":
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if bundle_sha == core_sha or append_sha == bundle_sha:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            req_seq = getattr(locator, "sequence", None)
            if req_seq and seq != req_seq:
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 12. Panel Seats
            seats_raw = _get_val("panel_seat_verdicts") or ()
            panel_seats = tuple(sorted(seat for seat, verdict, _r in seats_raw))
            req_seats = tuple(sorted(getattr(expected, "required_panel_seats", ())))
            seat_runs = {run_id for _s, _v, run_id in seats_raw}
            if panel_seats != req_seats or not all(verdict == "AGREE" for _s, verdict, _r in seats_raw) or len(seat_runs) != len(req_seats):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

            # 13. RED Lifecycle
            if _get_val("red_lifecycle_nodeids") != getattr(expected, "expected_nodeid_count", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("red_lifecycle_passed") != getattr(expected, "forced_red_passed", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}
            if _get_val("red_lifecycle_failed") != getattr(expected, "forced_red_failed", None):
                return {"status": "blocked", "authorized": False, "decisive": False, "evidence_kind": "observation_mismatch", "locator": locator}

        obs_digest = ""
        if hasattr(obs, "__dataclass_fields__"):
            import dataclasses
            obs_digest = hashlib.sha256(json.dumps(dataclasses.asdict(obs), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        elif isinstance(obs, dict):
            obs_digest = hashlib.sha256(json.dumps(obs, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

        return {
            "status": "verified",
            "authorized": True,
            "decisive": True,
            "evidence_kind": "production_external_boundary",
            "blocker_class": None,
            "human_required": False,
            "failed_checks": [],
            "observation_digest": obs_digest,
            "locator": locator,
            "observation": obs,
        }
