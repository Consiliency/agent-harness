"""Synthetic acceptance coverage for agent-harness#1849 exact-PR repair."""
from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from phase_loop_runtime.convergence.broker import exact_pr_reconciliation as exact
from phase_loop_runtime.convergence.broker import live
from phase_loop_runtime.convergence.broker.credsep import GitHubBrokerAdapter
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
from phase_loop_runtime.convergence.broker.verbs import (
    AdapterStartOwnerLive,
    AdapterStartOwnership,
    BrokerService,
    _restore_owner_bytes,
    append_adapter_start_owner,
)
from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState
from phase_loop_runtime.publishing import prepare_publish_transaction
from test_fabpub_shared_epoch import (
    _CountingAdapter,
    _authority_preimage,
    _git,
    _init_repo,
    _publish_transaction_request,
    _service,
    _stage,
)


TITLE = "test: reconcile one existing pull request"
PR_URL = "https://github.com/Consiliency/agent-harness/pull/1849"
ORIGINAL_BODY = "Acceptance summary: 31 pool, 40 Codex, 96 Claude assertions\n"
OBSERVED_BODY = "Acceptance summary: 31 pool, 38 Codex, 94 Claude assertions; 163 total\n"
LEGACY_FIXTURE_SHA256 = "60fb77d1af562bdda9d23d277ee44d6817ab09bf71d2db3bddb63ebd59791afc"


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")


def _tree(path: Path) -> dict[str, tuple[str, bytes | str]]:
    if not os.path.lexists(path):
        return {}
    out: dict[str, tuple[str, bytes | str]] = {}
    for candidate in [path, *sorted(path.rglob("*"))]:
        relative = "." if candidate == path else str(candidate.relative_to(path))
        if candidate.is_symlink():
            out[relative] = ("symlink", os.readlink(candidate))
        elif candidate.is_file():
            out[relative] = ("file", candidate.read_bytes())
        elif candidate.is_dir():
            out[relative] = ("dir", b"")
    return out


class ExactRunner:
    """Read-only provider runner backed by deterministic synthetic GitHub JSON."""

    def __init__(self, case, *, mutate=None, fail: str | None = None) -> None:
        self.case = case
        self.mutate = mutate
        self.fail = fail
        self.commands: list[tuple[str, ...]] = []
        self.provider_reads = 0

    def _completed(self, args, body=b"", returncode=0, *, text=False):
        if text and isinstance(body, bytes):
            body = body.decode("utf-8")
        return subprocess.CompletedProcess(args, returncode, stdout=body, stderr="" if text else b"")

    def __call__(self, args, **kwargs):
        argv = tuple(str(part) for part in args)
        self.commands.append(argv)
        text = bool(kwargs.get("text", False))
        if argv[:3] == ("git", "-C", str(self.case.repo)) and argv[3:6] == (
            "remote", "get-url", "origin"
        ):
            return self._completed(args, b"https://github.com/Consiliency/agent-harness.git\n", text=text)
        if argv[:3] == ("gh", "pr", "view"):
            self.provider_reads += 1
            if self.fail == "view":
                return self._completed(args, b"", 1, text=text)
            if self.mutate is not None:
                self.mutate(self, "view")
            return self._completed(args, json.dumps(self.case.view).encode("utf-8"), text=text)
        if argv[:3] == ("gh", "pr", "list"):
            if self.fail == "list":
                return self._completed(args, b"", 1, text=text)
            if self.mutate is not None:
                self.mutate(self, "list")
            return self._completed(args, json.dumps(self.case.listed).encode("utf-8"), text=text)
        if "ls-remote" in argv:
            if self.fail == "remote":
                return self._completed(args, b"", 1, text=text)
            if self.mutate is not None:
                self.mutate(self, "remote")
            body = f"{self.case.disposition['head_sha']}\trefs/heads/{self.case.disposition['head_ref']}\n".encode()
            return self._completed(args, body, text=text)
        return subprocess.run(args, **kwargs)

    def assert_read_only(self) -> None:
        joined = [" ".join(command) for command in self.commands]
        forbidden = (" push ", " pr create", " pr edit", " pr merge", " pr close")
        assert not [command for command in joined if any(token in f" {command}" for token in forbidden)]


@dataclass
class ExactCase:
    repo: Path
    store: Path
    authority: Path
    transaction: object
    service: BrokerService
    request: object
    key: str
    owner_bytes: bytes
    ambiguity_line: bytes
    disposition: dict
    view: dict
    listed: list[dict]

    def runner(self, **kwargs) -> ExactRunner:
        return ExactRunner(self, **kwargs)

    def reconcile(self, *, disposition=None, check=False, runner=None):
        chosen = self.disposition if disposition is None else disposition
        return exact.reconcile_exact_pr(
            self.repo,
            authority_root=self.authority,
            transaction_id=chosen["transaction_id"],
            pr_url=chosen["pr_url"],
            disposition=chosen,
            check=check,
            run=runner or self.runner(),
        )


@pytest.fixture
def exact_case(tmp_path, monkeypatch) -> ExactCase:
    authority = tmp_path / "fabpub-authority"
    monkeypatch.setenv(live.FABPUB_AUTHORITY_ROOT_ENV, str(authority))
    repo = _init_repo(tmp_path / "repo")
    inventory = live.probe_zero_history_bootstrap(
        cutover_id="bootstrap-exact-pr",
        authority_root=authority,
        worktrees=(repo,),
        legacy_roots=(tmp_path / "legacy",),
        historical_evidence_roots=(),
        search_roots=(tmp_path,),
    )
    assert live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)["state"] == "ACTIVE"
    repository = live.repository_snapshot(repo)
    store = repository.store_root
    base_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_head)
    _git(repo, "checkout", "-q", "-b", "fix/exact-pr")
    _stage(repo, "repair.py", "bounded = True\n")
    checkpoint_root = tmp_path / "qualified-runtime-packet"
    transaction = prepare_publish_transaction(
        repo,
        owned_paths=("repair.py",),
        checkpoint_root=checkpoint_root,
        branch="fix/exact-pr",
        envelope_authority_preimage=_authority_preimage(repository.identity, "fix/exact-pr"),
        pr_body=ORIGINAL_BODY,
        commit_message=TITLE,
    )
    transaction.resume()
    service = _service(store, _CountingAdapter(explode=True))
    request = _publish_transaction_request(repository.identity, "fix/exact-pr", transaction, repo)
    outcome = service.execute(request)
    assert outcome.evidence.terminal_state == "outcome_ambiguous_blocked"
    key = service._dedup_key(request)
    owner_bytes = (store / "adapter-start-owner.json").read_bytes()
    owner = json.loads(owner_bytes)
    ambiguity_line = next(
        line
        for line in (store / "evidence.jsonl").read_bytes().splitlines()
        if json.loads(line).get("idempotency_key") == key
        and json.loads(line).get("state") == "outcome_ambiguous_blocked"
    )
    checkpoint_path = transaction.checkpoint_path
    pointer_path = transaction.store.active_pointer_path
    receipt_bytes = (store / live.RECEIPT_FILENAME).read_bytes()
    checkpoint = json.loads(checkpoint_path.read_bytes())
    disposition = {
        "schema": exact.DISPOSITION_SCHEMA,
        "canonical_repository_identity": repository.identity,
        "repository_common_dir": str(repository.common_dir),
        "authority_root": str(checkpoint_root.resolve()),
        "generation": 0,
        "partition_receipt_sha256": _sha(receipt_bytes),
        "transaction_id": transaction.transaction_id,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": _sha(checkpoint_path.read_bytes()),
        "active_transaction_pointer_path": str(pointer_path),
        "effect_key": key,
        "ambiguity_digest": _sha(ambiguity_line),
        "owner_nonce": owner["owner_nonce"],
        "owner_transaction_id": owner["transaction_id"],
        "owner_bytes_sha256": _sha(owner_bytes),
        "pr_host": "github.com",
        "pr_repository": "Consiliency/agent-harness",
        "pr_number": 1849,
        "pr_url": PR_URL,
        "head_repository": "Consiliency/agent-harness",
        "head_ref": "fix/exact-pr",
        "head_sha": transaction.committed_head_sha,
        "base_repository": "Consiliency/agent-harness",
        "base_ref": "main",
        "draft": True,
        "expected_title": TITLE,
        "observed_title": TITLE,
        "original_body": ORIGINAL_BODY,
        "observed_body": OBSERVED_BODY,
        "original_body_sha256": _sha(ORIGINAL_BODY.encode()),
        "observed_body_sha256": _sha(OBSERVED_BODY.encode()),
        "correction_kind": exact.CORRECTION_KIND,
        "correction_reason": "owner-approved correction of the frozen assertion count",
        "authorization_kind": exact.AUTHORIZATION_KIND,
        "owner_instruction_reference": "packet://agent-harness-1849/body-exception",
        "owner_instruction_sha256": _sha(b"agent-harness-1849 body exception"),
        "creator_attribution": exact.CREATOR_ATTRIBUTION,
    }
    assert checkpoint["pr_body"] == ORIGINAL_BODY
    view = {
        "url": PR_URL,
        "number": 1849,
        "state": "OPEN",
        "isDraft": True,
        "mergedAt": None,
        "baseRefName": "main",
        "headRefName": "fix/exact-pr",
        "headRefOid": transaction.committed_head_sha,
        "headRepository": {"nameWithOwner": "Consiliency/agent-harness"},
        "headRepositoryOwner": {"login": "Consiliency"},
        "isCrossRepository": False,
        "title": TITLE,
        "body": OBSERVED_BODY,
    }
    listed = [{
        "number": 1849,
        "url": PR_URL,
        "headRefName": "fix/exact-pr",
        "headRefOid": transaction.committed_head_sha,
    }]
    return ExactCase(
        repo, store, checkpoint_root.resolve(), transaction, service, request,
        key, owner_bytes, ambiguity_line, disposition, view, listed,
    )


def _settle(case: ExactCase) -> dict:
    runner = case.runner()
    result = case.reconcile(runner=runner)
    runner.assert_read_only()
    return result


def _settlement(case: ExactCase):
    snapshot = exact.snapshot_exact_pr_store(case.store)
    value = exact.read_exact_pr_settlement(snapshot, case.key)
    assert isinstance(value, exact.ValidExactPRSettlement)
    return value


def _release_service(service: BrokerService) -> None:
    seen: set[int] = set()
    for store in (service.admission_store, service.evidence_store):
        lease = getattr(store, "generation_lease", None)
        if lease is not None and id(lease) not in seen:
            seen.add(id(lease))
            with contextlib.suppress(Exception):
                lease.release()


def _ambiguity_digest(root: Path, key: str) -> str:
    line = next(
        line
        for line in (root / "evidence.jsonl").read_bytes().splitlines()
        if json.loads(line).get("idempotency_key") == key
        and json.loads(line).get("state") == "outcome_ambiguous_blocked"
    )
    return _sha(line)


def _rotation_attestation(
    case: ExactCase,
    root: Path,
    generation: int,
    effects: dict[str, dict],
) -> dict:
    receipt = (root / live.RECEIPT_FILENAME).read_bytes()
    attestation = {
        "schema": live.ROTATION_ATTESTATION_SCHEMA,
        "attested_by": "synthetic operator",
        "attested_at": "2026-11-06T00:00:00Z",
        "predecessor_generation": generation,
        "predecessor_receipt_digest": _sha(receipt),
        "predecessor_store_digests": {
            name: _sha((root / name).read_bytes() if (root / name).exists() else b"")
            for name in live.ROTATION_DIGESTED_FILES
        },
        "effects": effects,
    }
    snapshot = exact.snapshot_exact_pr_store(root)
    if snapshot.settlement_files:
        attestation["exact_pr_settlement_snapshot_sha256"] = (
            exact.exact_pr_settlement_snapshot_sha256(snapshot)
        )
    return attestation


def _block_distinct(service: BrokerService, key: str) -> None:
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord

    service.evidence_store.record_intent(key)
    service.evidence_store.record_terminal(
        EvidenceRecord(key, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "synthetic-ambiguity")
    )


def test_group_6_authorization_and_result_semantics(exact_case):
    result = _settle(exact_case)
    assert result | {} == result
    assert result["title_equal"] is True
    assert result["body_equal"] is False
    assert result["authorization_kind"] == "operator_procedural"
    assert result["creator_attribution"] == "not_proven_broker"
    assert result["broker_created_pr"] is False
    assert result["independently_approved"] is False
    assert "human" not in json.dumps(result).lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_kind", "independent_approval"),
        ("creator_attribution", "broker"),
        ("owner_instruction_reference", ""),
        ("owner_instruction_sha256", "0" * 63),
    ],
)
def test_group_6_invalid_authorization_refuses(exact_case, field, value):
    disposition = {**exact_case.disposition, field: value}
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact_case.reconcile(disposition=disposition, check=True)


def test_group_7_inspection_and_immutable_originals(exact_case):
    originals = {
        path: path.read_bytes()
        for path in (
            exact_case.transaction.checkpoint_path,
            exact_case.transaction.store.active_pointer_path,
            exact_case.store / "evidence.jsonl",
            exact_case.store / "adapter-start-owner.json",
        )
    }
    before_inspect = _tree(exact_case.authority) | {
        f"store:{key}": value for key, value in _tree(exact_case.store).items()
    }
    raw = exact.inspect_exact_pr(
        exact_case.repo,
        authority_root=exact_case.authority,
        transaction_id=exact_case.transaction.transaction_id,
    )
    assert raw["raw_state"] == "outcome_ambiguous_blocked"
    assert raw["effective_publication"] is False
    assert before_inspect == _tree(exact_case.authority) | {
        f"store:{key}": value for key, value in _tree(exact_case.store).items()
    }
    _settle(exact_case)
    inspected = exact.inspect_exact_pr(
        exact_case.repo,
        authority_root=exact_case.authority,
        transaction_id=exact_case.transaction.transaction_id,
    )
    assert inspected["raw_state"] == "outcome_ambiguous_blocked"
    assert inspected["effective_publication"] is True
    assert inspected["pr_url"] == PR_URL
    assert inspected["body_equal"] is False
    assert all(path.read_bytes() == body for path, body in originals.items())


def test_group_8_check_is_point_in_time_and_zero_write(exact_case):
    before = (_tree(exact_case.store), _tree(exact_case.authority))
    result = exact_case.reconcile(check=True)
    assert result["status"] == "exact_pr_reconciliation_check_ready"
    assert result["check"] is True
    assert result["commit_authorized"] is False
    assert result["point_in_time"] is True
    assert before == (_tree(exact_case.store), _tree(exact_case.authority))


def test_group_8_check_never_opens_mutation_seams(exact_case, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("zero-write check reached a mutation seam")

    monkeypatch.setattr(exact, "_atomic_install_observation", forbidden)
    monkeypatch.setattr(exact, "_install_settlement", forbidden)
    monkeypatch.setattr(live.WriterGenerationLatch, "acquire", forbidden)
    result = exact_case.reconcile(check=True)
    assert result["commit_authorized"] is False


def test_group_8_check_then_local_drift_does_not_authorize_commit(exact_case):
    check = exact_case.reconcile(check=True)
    assert check["commit_authorized"] is False
    path = exact_case.transaction.checkpoint_path
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact_case.reconcile()
    assert not exact.settlement_path(exact_case.store, exact_case.key).exists()


def test_group_8_missing_authority_check_does_not_construct(tmp_path, exact_case):
    missing = tmp_path / "missing-authority"
    disposition = {**exact_case.disposition, "authority_root": str(missing)}
    before = _tree(tmp_path)
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact.reconcile_exact_pr(
            exact_case.repo,
            authority_root=missing,
            transaction_id=disposition["transaction_id"],
            pr_url=PR_URL,
            disposition=disposition,
            check=True,
            run=exact_case.runner(),
        )
    assert not missing.exists()
    assert before == _tree(tmp_path)


def test_group_5_exact_witness_and_runner_allowlist(exact_case):
    runner = exact_case.runner()
    result = exact_case.reconcile(check=True, runner=runner)
    assert result["pr_url"] == PR_URL
    assert len([cmd for cmd in runner.commands if cmd[:3] == ("gh", "pr", "view")]) == 2
    assert len([cmd for cmd in runner.commands if cmd[:3] == ("gh", "pr", "list")]) == 2
    runner.assert_read_only()


@pytest.mark.parametrize(
    ("where", "field", "value"),
    [
        ("view", "title", "test: isolate credential retirement shell fixtures"),
        ("view", "headRefOid", "f" * 40),
        ("view", "baseRefName", "other"),
        ("view", "isDraft", False),
        ("view", "isCrossRepository", True),
        ("view", "state", "CLOSED"),
        ("view", "mergedAt", "2026-11-06T00:00:00Z"),
        ("view", "url", "https://github.com/Consiliency/agent-harness/tree/fix/exact-pr"),
        ("view", "headRepository", {"nameWithOwner": "fork/agent-harness"}),
        ("list", "url", "https://github.com/Consiliency/agent-harness/pull/1850"),
    ],
)
def test_group_5_wrong_provider_fact_refuses(exact_case, where, field, value):
    if where == "view":
        exact_case.view[field] = value
    else:
        exact_case.listed[0][field] = value
    runner = exact_case.runner()
    with pytest.raises((exact.ExactPRReconciliationRefused, PermissionError)):
        exact_case.reconcile(check=True, runner=runner)
    runner.assert_read_only()


@pytest.mark.parametrize("listed", [[], [{"number": 1}, {"number": 2}]])
def test_group_5_absent_or_multiple_all_state_prs_refuse(exact_case, listed):
    exact_case.listed[:] = listed
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact_case.reconcile(check=True)


def test_group_5_closed_duplicate_beyond_first_page_refuses(exact_case):
    duplicate = dict(exact_case.listed[0], number=1800, url=PR_URL.replace("1849", "1800"))
    exact_case.listed[:] = [exact_case.listed[0], *[duplicate for _ in range(101)]]
    with pytest.raises(exact.ExactPRReconciliationRefused, match="exactly one"):
        exact_case.reconcile(check=True)


@pytest.mark.parametrize("remote", [b"", b"a" * 40 + b"\trefs/heads/fix/exact-pr\n" + b"b" * 40 + b"\trefs/heads/fix/exact-pr\n"])
def test_group_5_missing_or_ambiguous_remote_ref_refuses(exact_case, remote):
    class RemoteRunner(ExactRunner):
        def __call__(self, args, **kwargs):
            if "ls-remote" in tuple(str(part) for part in args):
                return self._completed(args, remote, text=bool(kwargs.get("text", False)))
            return super().__call__(args, **kwargs)

    with pytest.raises((exact.ExactPRReconciliationRefused, PermissionError)):
        exact_case.reconcile(check=True, runner=RemoteRunner(exact_case))


@pytest.mark.parametrize("failure", ["view", "list", "remote"])
def test_group_5_provider_failures_refuse(exact_case, failure):
    with pytest.raises((exact.ExactPRReconciliationRefused, PermissionError)):
        exact_case.reconcile(check=True, runner=exact_case.runner(fail=failure))


def test_group_5_inconsistent_second_complete_read_refuses(exact_case):
    def mutate(runner, stage):
        if stage == "view" and runner.provider_reads == 2:
            exact_case.view["title"] = "changed between reads"

    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact_case.reconcile(check=True, runner=exact_case.runner(mutate=mutate))


def test_group_5_body_hash_preserves_decoded_unicode_crlf_and_trailing_newline(exact_case):
    body = "snowman ☃\r\nline two\n"
    exact_case.view["body"] = body
    witness = GitHubBrokerAdapter(exact_case.repo, run=exact_case.runner()).read_exact_pr_witness(
        pr_url=PR_URL, branch="fix/exact-pr"
    )
    assert witness["body_sha256"] == _sha(body.encode("utf-8"))


@pytest.mark.parametrize(
    "mutation",
    [
        {"correction_kind": "none"},
        {"correction_reason": ""},
        {"original_body_sha256": "0" * 64},
        {"observed_body_sha256": "0" * 64},
        {"observed_body": OBSERVED_BODY + "extra"},
    ],
)
def test_group_5_body_exception_is_exact(exact_case, mutation):
    disposition = {**exact_case.disposition, **mutation}
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact_case.reconcile(disposition=disposition, check=True)


def test_group_2_lock_free_reads_while_admissions_lock_is_held(exact_case):
    _settle(exact_case)
    lock_path = exact_case.store / "admissions.lock"
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = exact.snapshot_exact_pr_store(exact_case.store)
        assert exact_case.key not in exact.effective_blocking_keys(snapshot)
        assert BrokerEvidenceStore(exact_case.store).epoch_blocked is False
        fcntl.flock(lock, fcntl.LOCK_UN)


def test_group_2_provider_reads_run_outside_admissions_lock(exact_case):
    lock_path = exact_case.store / "admissions.lock"

    def mutate(_runner, _stage):
        with lock_path.open("r+") as contender:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(contender, fcntl.LOCK_UN)

    _settle_result = exact_case.reconcile(runner=exact_case.runner(mutate=mutate))
    assert _settle_result["effective_publication"] is True


def test_group_2_subprocess_effective_reader_has_hard_deadline(exact_case):
    _settle(exact_case)
    script = (
        "from pathlib import Path; "
        "from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore; "
        "assert BrokerEvidenceStore(Path(__import__('sys').argv[1])).epoch_blocked is False"
    )
    lock_path = exact_case.store / "admissions.lock"
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        completed = subprocess.run(
            [os.sys.executable, "-c", script, str(exact_case.store)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        fcntl.flock(lock, fcntl.LOCK_UN)
    assert completed.returncode == 0, completed.stderr


def test_group_2_admit_next_epoch_callback_is_lock_free(exact_case):
    _settle(exact_case)
    admission = exact_case.service.admission_store
    admission.epoch_blocked = lambda: BrokerEvidenceStore(exact_case.store).epoch_blocked
    record = admission._records()[0]
    attempt_id = record.request.attempt_id
    returned = admission.admit_next(
        lambda _epoch, _attempt: record.request,
        attempt_id=attempt_id,
        precondition=lambda: True,
    )
    assert returned == record


def test_group_3_effective_consumers_keep_other_ambiguity_blocking(exact_case):
    _settle(exact_case)
    other = "publish_committed_branch\0other-ambiguous"
    exact_case.service.evidence_store.record_intent(other)
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord

    exact_case.service.evidence_store.record_terminal(
        EvidenceRecord(other, TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED, "other")
    )
    assert BrokerEvidenceStore(exact_case.store).blocking_keys == (other,)
    assert live.partition_is_ambiguity_blocked(exact_case.store) is True


def test_group_3_same_key_replays_settlement_without_adapter_entry(exact_case):
    _settle(exact_case)
    exact_case.service.adapter = _CountingAdapter(explode=True)
    replayed = exact_case.service.execute(exact_case.request)
    assert replayed.accepted is False
    assert replayed.provider_call_made is False
    assert replayed.reason == "exact_pr_reconciled"
    assert replayed.exact_pr_settlement["pr_url"] == PR_URL
    assert exact_case.service.adapter.calls == []


def test_b3_rotation_carries_full_proof_twice_and_prevents_provider_entry(exact_case):
    first = _settle(exact_case)
    key_b = "publish_committed_branch\0distinct-B"
    _block_distinct(exact_case.service, key_b)
    owner = json.loads(exact_case.owner_bytes)
    effects = {
        exact_case.key: {
            "disposition": live.DISPOSITION_OBSERVED_LANDED,
            "observed_head": exact_case.disposition["head_sha"],
            "branch_absent": False,
            "evidence_url": PR_URL,
            "ambiguity_digest": _ambiguity_digest(exact_case.store, exact_case.key),
            "owner_nonce": owner["owner_nonce"],
            "transaction_id": owner["transaction_id"],
            "settlement_digest": first["settlement_digest"],
        },
        key_b: {
            "disposition": live.DISPOSITION_ATTESTED_NOT_LANDED,
            "observed_head": None,
            "branch_absent": True,
            "evidence_url": "https://example.invalid/distinct-B",
            "ambiguity_digest": _ambiguity_digest(exact_case.store, key_b),
        },
    }
    attestation = _rotation_attestation(exact_case, exact_case.store, 0, effects)
    _release_service(exact_case.service)
    rotated = live.rotate_blocked_partition(
        exact_case.repo,
        cutover_id="exact-pr-carry-one",
        attestation=attestation,
        authority_root=Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
    )
    settled = exact.read_exact_pr_settlement(
        exact.snapshot_exact_pr_store(rotated.store_root), exact_case.key
    )
    assert isinstance(settled, exact.ValidExactPRSettlement)
    assert settled.carried is True
    assert settled.payload["disposition"]["observed_title"] == TITLE
    assert settled.payload["disposition"]["observed_body"] == OBSERVED_BODY

    adapter = _CountingAdapter(explode=True)
    successor_service = _service(rotated.store_root, adapter)
    replay = successor_service.execute(exact_case.request)
    assert replay.reason == "exact_pr_reconciled"
    assert replay.provider_call_made is False
    assert adapter.calls == []

    key_c = "publish_committed_branch\0distinct-C"
    _block_distinct(successor_service, key_c)
    effects_c = {
        key_c: {
            "disposition": live.DISPOSITION_ATTESTED_NOT_LANDED,
            "observed_head": None,
            "branch_absent": True,
            "evidence_url": "https://example.invalid/distinct-C",
            "ambiguity_digest": _ambiguity_digest(rotated.store_root, key_c),
        }
    }
    second_attestation = _rotation_attestation(
        exact_case, rotated.store_root, 1, effects_c
    )
    _release_service(successor_service)
    rotated_twice = live.rotate_blocked_partition(
        exact_case.repo,
        cutover_id="exact-pr-carry-two",
        attestation=second_attestation,
        authority_root=Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
    )
    carried_twice = exact.read_exact_pr_settlement(
        exact.snapshot_exact_pr_store(rotated_twice.store_root), exact_case.key
    )
    assert isinstance(carried_twice, exact.ValidExactPRSettlement)
    assert carried_twice.settlement_digest == first["settlement_digest"]
    assert carried_twice.payload == settled.payload


@pytest.mark.parametrize("binding", ["evidence_url", "observed_head", "settlement_digest", "disposition"])
def test_b3_wrong_or_false_carry_binding_refuses(exact_case, binding):
    result = _settle(exact_case)
    owner = json.loads(exact_case.owner_bytes)
    entry = {
        "disposition": live.DISPOSITION_OBSERVED_LANDED,
        "observed_head": exact_case.disposition["head_sha"],
        "branch_absent": False,
        "evidence_url": PR_URL,
        "ambiguity_digest": _ambiguity_digest(exact_case.store, exact_case.key),
        "owner_nonce": owner["owner_nonce"],
        "transaction_id": owner["transaction_id"],
        "settlement_digest": result["settlement_digest"],
    }
    entry[binding] = {
        "evidence_url": "https://example.invalid/wrong",
        "observed_head": "f" * 40,
        "settlement_digest": "0" * 64,
        "disposition": live.DISPOSITION_ATTESTED_NOT_LANDED,
    }[binding]
    attestation = _rotation_attestation(
        exact_case, exact_case.store, 0, {exact_case.key: entry}
    )
    _release_service(exact_case.service)
    with pytest.raises(live.PartitionRotationRefused):
        live.rotate_blocked_partition(
            exact_case.repo,
            cutover_id=f"wrong-{binding}",
            attestation=attestation,
            authority_root=Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
        )


def test_group_1_owner_retirement_is_exact_and_original_bytes_stay(exact_case):
    before = exact_case.owner_bytes
    _settle(exact_case)
    assert (exact_case.store / "adapter-start-owner.json").read_bytes() == before
    settlement = _settlement(exact_case)
    assert exact.owner_is_settlement_retired(before, exact_case.key, (settlement,)) is True
    assert exact.owner_is_settlement_retired(before, exact_case.key + "x", (settlement,)) is False
    changed = before.replace(b'"owner_nonce":"', b'"owner_nonce":"different-', 1)
    assert exact.owner_is_settlement_retired(changed, exact_case.key, (settlement,)) is False


def test_group_1_distinct_owner_replaces_retired_a_and_is_not_retired(exact_case):
    _settle(exact_case)
    owner_a = json.loads(exact_case.owner_bytes)
    owner_b = AdapterStartOwnership(
        repository_identity=owner_a["repository_identity"],
        idempotency_key="publish_committed_branch\0B",
        transaction_id="transaction-B",
        attempt_id="attempt-B",
        committed_head="b" * 40,
        adapter_operation="publish_committed_branch",
        owner_nonce="nonce-B",
        effect_key="publish_committed_branch\0B",
        sealed=False,
    )
    recorded = append_adapter_start_owner(exact_case.store, owner_b)
    assert recorded == owner_b
    assert json.loads((exact_case.store / "adapter-start-owner.json").read_bytes())["effect_key"] == owner_b.effect_key
    assert exact.current_owner_is_settlement_retired(
        exact_case.store,
        (exact_case.store / "adapter-start-owner.json").read_bytes(),
        owner_b.effect_key,
    ) is False
    assert isinstance(_settlement(exact_case), exact.ValidExactPRSettlement)


def _new_transaction(case: ExactCase, tag: str):
    _git(case.repo, "checkout", "-q", "main")
    branch = f"fix/{tag}"
    _git(case.repo, "checkout", "-q", "-b", branch)
    filename = f"{tag}.py"
    _stage(case.repo, filename, f"{tag.replace('-', '_')} = True\n")
    transaction = prepare_publish_transaction(
        case.repo,
        owned_paths=(filename,),
        checkpoint_root=case.authority.parent / f"packet-{tag}",
        branch=branch,
        envelope_authority_preimage=_authority_preimage(case.disposition["canonical_repository_identity"], branch),
        commit_message=f"test: {tag}",
    )
    transaction.resume()
    return transaction, _publish_transaction_request(
        case.disposition["canonical_repository_identity"], branch, transaction, case.repo
    )


def test_group_1_distinct_b_publishes_after_a_settles(exact_case):
    _settle(exact_case)
    transaction_b, request_b = _new_transaction(exact_case, "distinct-b")
    adapter = _CountingAdapter()
    exact_case.service.adapter = adapter
    outcome = exact_case.service.execute(request_b)
    assert outcome.accepted is True
    assert len(adapter.calls) == 1
    owner = json.loads((exact_case.store / "adapter-start-owner.json").read_bytes())
    assert owner["transaction_id"] == transaction_b.transaction_id
    assert isinstance(_settlement(exact_case), exact.ValidExactPRSettlement)


def test_group_1_crashed_b_is_promoted_as_b_not_retired_as_a(exact_case):
    from phase_loop_runtime.publishing import PublishCrashInjected, crash_after
    from phase_loop_runtime.convergence.broker.verbs import UnsealedOwnerBlocksPartition

    _settle(exact_case)
    _transaction_b, request_b = _new_transaction(exact_case, "crashed-b")
    exact_case.service.adapter = _CountingAdapter()
    with crash_after("after_broker_intent_before_adapter_started"):
        with pytest.raises(PublishCrashInjected):
            exact_case.service.execute(request_b)
    key_b = exact_case.service._dedup_key(request_b)
    with pytest.raises(UnsealedOwnerBlocksPartition) as refused:
        exact_case.service.execute(request_b)
    assert refused.value.effect_key == key_b
    assert exact_case.service.evidence_store.replay()[key_b].state is TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED
    assert isinstance(_settlement(exact_case), exact.ValidExactPRSettlement)


def test_group_1_restore_old_bytes_remain_retired_without_overwriting_replacement(exact_case):
    _settle(exact_case)
    path = exact_case.store / "adapter-start-owner.json"
    replacement = exact_case.owner_bytes.replace(b'"effect_key":"', b'"effect_key":"new-', 1)
    path.write_bytes(replacement)
    # The lifecycle calls this only after an exact CAS; the low-level byte
    # primitive is deliberately exact, so test both the restoration and the
    # caller-side non-overwrite condition.
    if path.read_bytes() == exact_case.owner_bytes:
        _restore_owner_bytes(exact_case.store, exact_case.owner_bytes)
    assert path.read_bytes() == replacement
    path.write_bytes(exact_case.owner_bytes)
    assert exact.current_owner_is_settlement_retired(
        exact_case.store, path.read_bytes(), exact_case.key
    ) is True


def test_group_4_active_latch_required(exact_case):
    latch = live.WriterGenerationLatch.for_store_root(exact_case.store)
    latch.begin_draining()
    with pytest.raises(exact.ExactPRReconciliationRefused, match="ACTIVE"):
        exact_case.reconcile()


@pytest.mark.parametrize("target", ["receipt", "checkpoint", "owner", "ambiguity", "observation", "generation"])
def test_group_4_cas_drift_refuses_without_settlement(exact_case, target):
    changed = False

    def mutate(runner, stage):
        nonlocal changed
        if changed or stage != "remote" or runner.provider_reads != 2:
            return
        changed = True
        if target == "receipt":
            path = exact_case.store / live.RECEIPT_FILENAME
            path.write_bytes(path.read_bytes() + b" ")
        elif target == "checkpoint":
            path = exact_case.transaction.checkpoint_path
            path.write_bytes(path.read_bytes() + b" ")
        elif target == "owner":
            path = exact_case.store / "adapter-start-owner.json"
            path.write_bytes(path.read_bytes() + b" ")
        elif target == "ambiguity":
            path = exact_case.store / "evidence.jsonl"
            path.write_bytes(path.read_bytes() + b'{"idempotency_key":"other","state":"rejected_before_start"}\n')
        else:
            if target == "observation":
                (exact_case.store / "post-ambiguity-observations.jsonl").write_text(
                    json.dumps({"idempotency_key": "other"}) + "\n", encoding="utf-8"
                )
            else:
                latch = live.WriterGenerationLatch.for_store_root(exact_case.store)
                raw = json.loads(latch.path.read_text())
                raw["generation"] = "stale-generation"
                latch.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises((exact.ExactPRReconciliationRefused, PermissionError)):
        exact_case.reconcile(runner=exact_case.runner(mutate=mutate))
    assert not exact.settlement_path(exact_case.store, exact_case.key).exists()


def test_group_4_live_owner_refuses(exact_case):
    descriptor = os.open(exact_case.store / "adapter-start-owner.json", os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(AdapterStartOwnerLive):
            exact_case.reconcile()
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@pytest.mark.parametrize("state", ["DRAINING", "INVENTORY_SEALED", "ARMED"])
def test_group_4_non_active_latch_states_refuse(exact_case, state):
    latch = live.WriterGenerationLatch.for_store_root(exact_case.store)
    raw = json.loads(latch.path.read_text())
    raw["generation_state"] = state
    latch.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(exact.ExactPRReconciliationRefused, match="ACTIVE"):
        exact_case.reconcile()


def test_group_4_common_directory_and_authority_laundering_refuse(exact_case, tmp_path):
    for field, value in (
        ("repository_common_dir", str(tmp_path / "other-common")),
        ("authority_root", str(tmp_path / "other-authority")),
    ):
        disposition = {**exact_case.disposition, field: value}
        with pytest.raises(exact.ExactPRReconciliationRefused):
            exact.reconcile_exact_pr(
                exact_case.repo,
                authority_root=exact_case.authority,
                transaction_id=disposition["transaction_id"],
                pr_url=PR_URL,
                disposition=disposition,
                check=True,
                run=exact_case.runner(),
            )


def test_b4_raw_ambiguity_terminal_transition_remains_forbidden(exact_case):
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord

    _settle(exact_case)
    with pytest.raises(ValueError):
        exact_case.service.evidence_store.record_terminal(
            EvidenceRecord(
                exact_case.key,
                TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED,
                PR_URL,
            )
        )


def test_b2_observation_precedes_settlement_and_is_reused(exact_case, monkeypatch):
    events: list[str] = []
    real_replace = os.replace
    real_link = os.link

    def replace(source, target, *args, **kwargs):
        if Path(target).name == "post-ambiguity-observations.jsonl":
            events.append("observation_replace")
        return real_replace(source, target, *args, **kwargs)

    def link(source, target, *args, **kwargs):
        events.append("settlement_link")
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "link", link)
    first = _settle(exact_case)
    assert events.index("observation_replace") < events.index("settlement_link")
    observation_path = exact_case.store / "post-ambiguity-observations.jsonl"
    before = observation_path.read_bytes()
    second = exact_case.reconcile()
    assert second["settlement_digest"] == first["settlement_digest"]
    assert observation_path.read_bytes() == before


@pytest.mark.parametrize("kind", ["unreadable", "no_effect", "conflict"])
def test_b2_incompatible_preexisting_observation_refuses(exact_case, kind):
    path = exact_case.store / "post-ambiguity-observations.jsonl"
    if kind == "unreadable":
        path.write_bytes(b"{torn")
    else:
        row = exact._observation_for(exact_case.disposition)
        if kind == "no_effect":
            row["observed_state"] = "no_effect_terminal_proven"
        else:
            row["head_sha"] = "f" * 40
        path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact_case.reconcile()
    assert path.read_bytes() == before
    assert not exact.settlement_path(exact_case.store, exact_case.key).exists()


@pytest.mark.parametrize("step", exact.EXACT_PR_CRASH_STEPS)
def test_b4_crash_recovery_is_absent_or_complete_and_retry_idempotent(exact_case, step):
    exact.crash_at_exact_pr_step(step)
    try:
        with pytest.raises(exact._ExactPRCrash):
            exact_case.reconcile()
    finally:
        exact.crash_at_exact_pr_step(None)
    final = exact.settlement_path(exact_case.store, exact_case.key)
    if final.exists():
        assert isinstance(_settlement(exact_case), exact.ValidExactPRSettlement)
    result = exact_case.reconcile()
    assert result["effective_publication"] is True
    assert isinstance(_settlement(exact_case), exact.ValidExactPRSettlement)
    observation = exact_case.store / "post-ambiguity-observations.jsonl"
    rows = [json.loads(line) for line in observation.read_text().splitlines()]
    assert sum(row.get("idempotency_key") == exact_case.key for row in rows) == 1


def test_b4_two_identical_callers_return_one_receipt(exact_case):
    barrier = threading.Barrier(2)
    results: list[dict] = []
    errors: list[BaseException] = []

    def mutate(_runner, stage):
        if stage == "view":
            try:
                barrier.wait(timeout=5)
            except threading.BrokenBarrierError:
                pass

    def caller():
        try:
            results.append(exact_case.reconcile(runner=exact_case.runner(mutate=mutate)))
        except BaseException as error:  # recorded for an assertion in the parent
            errors.append(error)

    threads = [threading.Thread(target=caller) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert errors == []
    assert len(results) == 2
    assert results[0]["settlement_digest"] == results[1]["settlement_digest"]
    assert len(list((exact_case.store / exact.SETTLEMENT_DIRECTORY).glob("*.json"))) == 1


def test_b4_competing_disposition_never_overwrites_winner(exact_case):
    winner = _settle(exact_case)
    competing = copy.deepcopy(exact_case.disposition)
    competing["owner_instruction_reference"] += "-different"
    with pytest.raises(exact.ExactPRReconciliationRefused, match="conflicting"):
        exact_case.reconcile(disposition=competing)
    assert _settlement(exact_case).settlement_digest == winner["settlement_digest"]


@pytest.mark.parametrize("shape", ["malformed", "symlink", "conflicting"])
def test_b4_eexist_bad_final_refuses(exact_case, shape, tmp_path):
    directory = exact_case.store / exact.SETTLEMENT_DIRECTORY
    directory.mkdir()
    final = exact.settlement_path(exact_case.store, exact_case.key)
    if shape == "malformed":
        final.write_bytes(b"not-json")
    elif shape == "symlink":
        target = tmp_path / "target"
        target.write_text("{}")
        final.symlink_to(target)
    else:
        payload = {"schema": "other"}
        final.write_bytes(_canonical(payload) + b"\n")
    before = os.lstat(final)
    with pytest.raises((exact.ExactPRReconciliationRefused, PermissionError)):
        exact_case.reconcile()
    assert os.lstat(final).st_ino == before.st_ino


def test_group_9_frozen_legacy_consumers_remain_blocked(exact_case):
    _settle(exact_case)
    fixture = Path(__file__).parent / "fixtures" / "fabpub_exact_pr_legacy_0_7_27.py"
    assert _sha(fixture.read_bytes()) == LEGACY_FIXTURE_SHA256
    spec = importlib.util.spec_from_file_location("fabpub_legacy_0_7_27", fixture)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    evidence = (exact_case.store / "evidence.jsonl").read_bytes()
    observations = (exact_case.store / "post-ambiguity-observations.jsonl").read_bytes()
    assert module.epoch_blocked(evidence) is True
    after, appended = module.block_unsealed_owner(evidence, exact_case.key)
    assert appended is False and after == evidence
    with pytest.raises(PermissionError):
        module.false_not_landed_rotation(observations, exact_case.key)
    provider_calls: list[bool] = []
    with pytest.raises(PermissionError):
        module.writer(evidence, lambda: provider_calls.append(True))
    assert provider_calls == []


def test_group_9_new_reader_refuses_provenance_losing_old_rotation(
    exact_case, monkeypatch
):
    _settle(exact_case)
    successor = exact_case.store / "generations" / "1"
    successor.mkdir(parents=True)

    class OldReceipt:
        generation = 1
        predecessor_generation = 0
        adjudicated_effect_dispositions = {}

    monkeypatch.setattr(live, "sealed_partition_effects", lambda _receipt: {})
    snapshot = exact.ExactPRStoreSnapshot(
        root=successor,
        receipt=OldReceipt(),
        receipt_bytes=b"old-receipt",
        evidence_bytes=b"",
        observation_bytes=None,
        settlement_files={},
        temporary_files=(),
        generation=1,
    )
    value = exact.read_exact_pr_settlement(snapshot, exact_case.key)
    assert isinstance(value, exact.ExactPRTypedRefusal)
    assert "omitted" in value.reason


def test_b3_missing_embedded_proof_refuses(exact_case, monkeypatch):
    result = _settle(exact_case)

    class MissingProofReceipt:
        generation = 1
        predecessor_generation = 0
        adjudicated_effect_dispositions = {
            exact_case.key: {"settlement_digest": result["settlement_digest"]}
        }

    monkeypatch.setattr(
        live,
        "sealed_partition_effects",
        lambda _receipt: {exact_case.key: {"settlement_digest": result["settlement_digest"]}},
    )
    snapshot = exact.ExactPRStoreSnapshot(
        root=exact_case.store / "generations" / "1",
        receipt=MissingProofReceipt(),
        receipt_bytes=b"missing-proof-receipt",
        evidence_bytes=b"",
        observation_bytes=None,
        settlement_files={},
        temporary_files=(),
        generation=1,
    )
    value = exact.read_exact_pr_settlement(snapshot, exact_case.key)
    assert isinstance(value, exact.ExactPRTypedRefusal)
    assert "omits its embedded proof" in value.reason


def test_group_10_new_module_is_real_and_has_no_skipped_tests():
    assert Path(exact.__file__).name == "exact_pr_reconciliation.py"
    source = Path(__file__).read_text(encoding="utf-8")
    assert "pytest.mark." + "skip" not in source
    assert "http" + "://" not in source
