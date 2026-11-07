"""Synthetic acceptance coverage for agent-harness#1849 exact-PR repair."""
from __future__ import annotations

import base64
import contextlib
import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime.convergence.broker import exact_pr_reconciliation as exact
from phase_loop_runtime.convergence.broker import live
from phase_loop_runtime.convergence.broker.credsep import GitHubBrokerAdapter
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
from phase_loop_runtime.convergence.broker.verbs import (
    AdapterStartOwnerLive,
    AdapterStartOwnership,
    BrokerService,
    append_adapter_start_owner,
    validate_adapter_start_owner,
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
LEGACY_0_7_27_RECORD_HASHES = {
    "convergence/__init__.py": "oZIwgejCpBIJJEram5_26CFxfTOM32sdgq8HcibwwGg",
    "convergence/contracts.py": "zbr6fs2h44URTw5Vewuuwz8OM-uyPWQMK0paaipSCQI",
    "convergence/provider_contracts.py": "I_R8HQtC_wb7AaD6Zl69krPnllhRJokRCfyARouN0cQ",
    "convergence/broker/__init__.py": "LzvG9224LYIaOliVydQLqZT6Hiq1Vf1gesQLUeIuzTI",
    "convergence/broker/admission.py": "u97xqH6kOlNxLCA_tTXxA8E39Avw0EaQp6Df5UEDkQ8",
    "convergence/broker/credsep.py": "".join(
        ("-HsTcz3iF1qWCbfY", "Evegw3ZCWC2LAGRH_ux8YmTjB1M")
    ),
    "convergence/broker/evidence.py": "wY6mS74VVU5-THr3vvh9k_304xYkdtsTAKj_mDCI4zU",
    "convergence/broker/live.py": "I4lj6CHu2A1iB9T_jK5EceaVltUKHG3eKghMbVbK7zA",
    "convergence/broker/verbs.py": "Qp4WWyWQ9t5LzHPL2VLRp6D5Ux005G8XXR06fgNHhCM",
}


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


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_AUDIT_HOOK_STATE = {"active": None}


def _audit_hook(roots):
    events = []
    resolved = [str(Path(root).resolve()) for root in roots]

    def under(path) -> bool:
        try:
            text = str(Path(os.fsdecode(path)).resolve())
        except Exception:
            return False
        return any(text == root or text.startswith(root + os.sep) for root in resolved)

    def hook(event, args):
        if event == "open":
            path, mode, flags = args
            writing = (
                isinstance(mode, str) and any(character in mode for character in "wax+")
            ) or (isinstance(flags, int) and flags & _WRITE_FLAGS)
            if writing and path is not None and not isinstance(path, int) and under(path):
                events.append((event, os.fsdecode(path), mode, flags))
        elif event in {
            "os.mkdir", "os.rename", "os.replace", "os.link", "os.symlink",
            "os.remove", "os.unlink", "os.rmdir", "os.truncate", "os.chmod", "os.utime",
        }:
            if args and not isinstance(args[0], int) and under(args[0]):
                events.append((event, os.fsdecode(args[0])))
    return events, hook


def _install_audit_hook_once():
    if getattr(sys, "_exact_pr_test_audit_hook", False):
        return

    def dispatch(event, args):
        active = _AUDIT_HOOK_STATE["active"]
        if active is not None:
            active(event, args)

    sys.addaudithook(dispatch)
    sys._exact_pr_test_audit_hook = True


@contextlib.contextmanager
def _assert_zero_writes(roots):
    _install_audit_hook_once()
    events, hook = _audit_hook(roots)
    _AUDIT_HOOK_STATE["active"] = hook
    try:
        yield
    finally:
        _AUDIT_HOOK_STATE["active"] = None
        assert events == []


def _zero_write_roots(case):
    return (
        case.store,
        case.authority,
        Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
    )


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
        if argv[:3] == ("git", "-C", str(self.case.repo)):
            tail = argv[3:]
            if tail == ("remote", "get-url", "origin"):
                return self._completed(
                    args,
                    b"https://github.com/Consiliency/agent-harness.git\n",
                    text=text,
                )
            if (
                tail[:2] == ("cat-file", "commit")
                or tail[:3] == ("log", "-1", "--format=%s")
                or tail[:4] == ("diff", "--name-only", "-z", "--no-renames")
            ):
                return subprocess.run(args, **kwargs)
            if tail[:1] == ("ls-remote",):
                if self.fail == "remote":
                    return self._completed(args, b"", 1, text=text)
                if self.mutate is not None:
                    self.mutate(self, "remote")
                body = (
                    f"{self.case.disposition['head_sha']}\t"
                    f"refs/heads/{self.case.disposition['head_ref']}\n"
                ).encode()
                return self._completed(args, body, text=text)
            raise AssertionError(f"unallowlisted git command: {argv!r}")
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
        raise AssertionError(f"unallowlisted provider runner command: {argv!r}")

    def assert_read_only(self) -> None:
        joined = [" ".join(command) for command in self.commands]
        forbidden = (" push ", " pr create", " pr edit", " pr merge", " pr close")
        assert not [command for command in joined if any(token in f" {command}" for token in forbidden)]

    def assert_allowlisted(self) -> None:
        for command in self.commands:
            if command[:3] == ("git", "-C", str(self.case.repo)):
                tail = command[3:]
                assert (
                    tail == ("remote", "get-url", "origin")
                    or tail[:2] == ("cat-file", "commit")
                    or tail[:3] == ("log", "-1", "--format=%s")
                    or tail[:4] == ("diff", "--name-only", "-z", "--no-renames")
                    or tail[:1] == ("ls-remote",)
                )
            else:
                assert command[:3] in (("gh", "pr", "view"), ("gh", "pr", "list"))


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
        chosen_runner = runner or self.runner()
        def invoke():
            return exact.reconcile_exact_pr(
                    self.repo,
                    authority_root=self.authority,
                    transaction_id=chosen["transaction_id"],
                    pr_url=chosen["pr_url"],
                    disposition=chosen,
                    check=check,
                    run=chosen_runner,
                )

        try:
            if check:
                with _assert_zero_writes(_zero_write_roots(self)):
                    return invoke()
            return invoke()
        finally:
            chosen_runner.assert_allowlisted()


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
    authority_preimage = _authority_preimage(repository.identity, "fix/exact-pr")
    transaction = prepare_publish_transaction(
        repo,
        owned_paths=("repair.py",),
        checkpoint_root=checkpoint_root,
        branch="fix/exact-pr",
        envelope_authority_preimage=authority_preimage,
        pr_body=ORIGINAL_BODY,
        commit_message=TITLE,
        node_id=authority_preimage["node_id"],
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


_CONCURRENT_RECONCILE_SCRIPT = r'''
import json
import subprocess
import sys
import time
from pathlib import Path

from phase_loop_runtime.convergence.broker import exact_pr_reconciliation as exact

repo = Path(sys.argv[1])
authority = Path(sys.argv[2])
transaction_id = sys.argv[3]
pr_url = sys.argv[4]
disposition = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
sync = Path(sys.argv[6])
tag = sys.argv[7]

class Runner:
    def __init__(self):
        self.provider_reads = 0

    @staticmethod
    def completed(args, body=b"", returncode=0, *, text=False):
        if text and isinstance(body, bytes):
            body = body.decode("utf-8")
        return subprocess.CompletedProcess(
            args, returncode, stdout=body, stderr="" if text else b""
        )

    def __call__(self, args, **kwargs):
        argv = tuple(str(part) for part in args)
        text = bool(kwargs.get("text", False))
        if argv[:3] == ("git", "-C", str(repo)):
            tail = argv[3:]
            if tail == ("remote", "get-url", "origin"):
                return self.completed(
                    args,
                    b"https://github.com/Consiliency/agent-harness.git\n",
                    text=text,
                )
            if (
                tail[:2] == ("cat-file", "commit")
                or tail[:3] == ("log", "-1", "--format=%s")
                or tail[:4] == ("diff", "--name-only", "-z", "--no-renames")
            ):
                return subprocess.run(args, **kwargs)
            if tail[:1] == ("ls-remote",):
                body = (
                    f"{disposition['head_sha']}\trefs/heads/{disposition['head_ref']}\n"
                ).encode()
                return self.completed(args, body, text=text)
            raise AssertionError(f"unallowlisted git command: {argv!r}")
        if argv[:3] == ("gh", "pr", "view"):
            self.provider_reads += 1
            if self.provider_reads == 1:
                (sync / f"witness-{tag}").write_text("ready\n", encoding="ascii")
                deadline = time.monotonic() + 10
                while not (sync / "release").exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("concurrency release was not observed")
                    time.sleep(0.01)
            body = json.dumps({
                "url": disposition["pr_url"],
                "number": disposition["pr_number"],
                "state": "OPEN",
                "isDraft": disposition["draft"],
                "mergedAt": None,
                "baseRefName": disposition["base_ref"],
                "headRefName": disposition["head_ref"],
                "headRefOid": disposition["head_sha"],
                "headRepository": {"nameWithOwner": disposition["head_repository"]},
                "headRepositoryOwner": {"login": disposition["head_repository"].split("/", 1)[0]},
                "isCrossRepository": False,
                "title": disposition["observed_title"],
                "body": disposition["observed_body"],
            }).encode()
            return self.completed(args, body, text=text)
        if argv[:3] == ("gh", "pr", "list"):
            body = json.dumps([{
                "number": disposition["pr_number"],
                "url": disposition["pr_url"],
                "headRefName": disposition["head_ref"],
                "headRefOid": disposition["head_sha"],
            }]).encode()
            return self.completed(args, body, text=text)
        raise AssertionError(f"unallowlisted provider runner command: {argv!r}")

runner = Runner()
(sync / f"started-{tag}").write_text("started\n", encoding="ascii")
try:
    result = exact.reconcile_exact_pr(
        repo,
        authority_root=authority,
        transaction_id=transaction_id,
        pr_url=pr_url,
        disposition=disposition,
        run=runner,
    )
    output = {
        "status": "ok",
        "settlement_digest": result["settlement_digest"],
        "path": "witness" if runner.provider_reads else "contended_wait",
    }
except Exception as error:
    output = {
        "status": "error",
        "error_type": type(error).__name__,
        "error": str(error),
        "path": "witness" if runner.provider_reads else "contended_wait",
    }
print(json.dumps(output, sort_keys=True))
'''


def _wait_for_path(path: Path, processes, *, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        failures = [process.returncode for process in processes if process.poll() is not None]
        if failures:
            raise AssertionError(f"reconciliation subprocess ended early: {failures}")
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _run_concurrent_reconciliation(
    case: ExactCase,
    root: Path,
    second_disposition: dict,
) -> tuple[dict, dict]:
    sync = root / "sync"
    sync.mkdir()
    dispositions = []
    for tag, payload in (("one", case.disposition), ("two", second_disposition)):
        path = root / f"{tag}.json"
        path.write_bytes(_canonical(payload) + b"\n")
        dispositions.append(path)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GH_TOKEN", "GITHUB_TOKEN"}
    }

    def start(tag, disposition_path):
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CONCURRENT_RECONCILE_SCRIPT,
                str(case.repo),
                str(case.authority),
                case.transaction.transaction_id,
                PR_URL,
                str(disposition_path),
                str(sync),
                tag,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )

    first = start("one", dispositions[0])
    _wait_for_path(sync / "witness-one", (first,))
    second = start("two", dispositions[1])
    _wait_for_path(sync / "started-two", (first, second))
    time.sleep(0.2)
    (sync / "release").write_text("release\n", encoding="ascii")
    completed = []
    try:
        for process in (first, second):
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            completed.append(json.loads(stdout.splitlines()[-1]))
    finally:
        for process in (first, second):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    return completed[0], completed[1]


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
    with _assert_zero_writes(_zero_write_roots(exact_case)):
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
    with _assert_zero_writes(_zero_write_roots(exact_case)):
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


def test_group_7_publish_resume_presents_settlement_without_writes(exact_case):
    from phase_loop_runtime import publishing

    _settle(exact_case)
    exact_case.service.adapter = _CountingAdapter(explode=True)
    roots = (
        exact_case.store,
        exact_case.authority,
        Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
    )
    before = tuple(_tree(root) for root in roots)
    authority = publishing.PublishAuthorityPreimages(
        exact_case.authority,
        exact_case.transaction.envelope_authority_preimage,
    )
    result = publishing.publish_from_worktree(
        exact_case.repo,
        exact_case.transaction.owned_paths,
        draft=exact_case.transaction.draft,
        pr_body=exact_case.transaction.pr_body,
        broker_client=exact_case.service,
        base=exact_case.transaction.base,
        publish_authority=authority,
        checkpoint_root=exact_case.authority,
    )
    assert "exact_pr_reconciliation" in result, result
    assert result["exact_pr_reconciliation"]["provider_call_made"] is False
    assert exact_case.service.adapter.calls == []
    assert tuple(_tree(root) for root in roots) == before


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
    runner = exact_case.runner()
    with _assert_zero_writes((tmp_path,)):
        with pytest.raises(exact.ExactPRReconciliationRefused):
            exact.reconcile_exact_pr(
                exact_case.repo,
                authority_root=missing,
                transaction_id=disposition["transaction_id"],
                pr_url=PR_URL,
                disposition=disposition,
                check=True,
                run=runner,
            )
    runner.assert_allowlisted()
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


def test_group_3_train_outer_resume_stays_ambiguous_without_reentry(
    exact_case, monkeypatch, tmp_path
):
    from phase_loop_runtime import publishing, train_runner
    from phase_loop_runtime.train_roadmap import parse_train_roadmap

    _settle(exact_case)
    assert (
        train_runner._sealed_publish_disposition(
            exact_case.repo, exact_case.transaction
        )
        == "ambiguous"
    )
    checkpoint = exact_case.transaction.checkpoint_path.read_bytes()
    pointer = exact_case.transaction.store.active_pointer_path.read_bytes()
    exact_case.service.adapter = _CountingAdapter(explode=True)
    monkeypatch.setattr(
        publishing,
        "inspect_publish_resume_candidate",
        lambda *_args, **_kwargs: SimpleNamespace(
            transaction=exact_case.transaction,
            state="TERMINAL_SEALED",
        ),
    )
    roadmap = parse_train_roadmap(
        """# Release Train: exact-pr

## Nodes

### Node: exact / specs/plan.md

**Depends on:** (none)
**Channel:** (none)
"""
    )
    unexpected = []

    def should_not_run(*_args, **_kwargs):
        unexpected.append(True)
        raise AssertionError("train continued past ambiguous sealed disposition")

    result = train_runner._run_train_unfenced(
        roadmap,
        tmp_path / "train.ledger.jsonl",
        resolve_workspace=lambda _node: exact_case.repo,
        coordinator_runtime=SimpleNamespace(train_id="exact-pr", broker_client=object()),
        _run_loop=should_not_run,
        _publish=should_not_run,
        _workspace_head_fn=lambda _workspace: "f" * 40,
        _publish_authority_fn=lambda *_args, **_kwargs: SimpleNamespace(
            checkpoint_root=exact_case.authority
        ),
    )
    assert result["status"] == "preflight_failed"
    assert "ambiguous terminal evidence" in result["errors"][0]
    assert unexpected == []
    assert exact_case.service.adapter.calls == []
    assert exact_case.transaction.checkpoint_path.read_bytes() == checkpoint
    assert exact_case.transaction.store.active_pointer_path.read_bytes() == pointer


def test_group_3_train_revocation_uses_effective_keys_but_replay_stays_exact(
    exact_case, monkeypatch
):
    from phase_loop_runtime import train_runner
    from phase_loop_runtime.train_review_packet import PacketError

    monkeypatch.setenv("PHASE_LOOP_FAB", "1")
    _settle(exact_case)
    record = SimpleNamespace(fab_run_id="run", node_id="exact")
    store = train_runner._train_revocation_store(exact_case.repo, record)
    assert store is not None
    exact_case.service.adapter = _CountingAdapter(explode=True)
    replayed = exact_case.service.execute(exact_case.request)
    assert replayed.reason == "exact_pr_reconciled"
    assert replayed.provider_call_made is False
    assert exact_case.service.adapter.calls == []

    _block_distinct(
        exact_case.service, "publish_committed_branch\0unsettled-train-key"
    )
    with pytest.raises(PacketError, match="readmission_revoked"):
        train_runner._train_revocation_store(exact_case.repo, record)


def test_group_3_rotation_ledger_keeps_settled_raw_ambiguity(exact_case):
    _settle(exact_case)
    ledger = live._read_predecessor_ledger(
        live._snapshot_predecessor(exact_case.store)
    )
    assert exact_case.key in ledger.blocked


def test_group_3_scope_correction_refuses_settled_predecessor_without_write(
    exact_case, monkeypatch
):
    from dataclasses import replace

    from phase_loop_runtime import publish_scope_correction as correction

    _settle(exact_case)
    exact_case.service.adapter = _CountingAdapter(explode=True)
    request = replace(
        exact_case.request,
        scope_correction_of=exact_case.transaction.transaction_id,
    )
    original = SimpleNamespace(
        transaction_id=exact_case.transaction.transaction_id,
        final_commit_object_sha256=exact_case.transaction.final_commit_object_sha256,
        owned_paths=exact_case.transaction.owned_paths,
        envelope_authority_preimage=exact_case.transaction.envelope_authority_preimage,
    )
    successor = SimpleNamespace(
        transaction_id="f" * 64,
        base=request.base,
        draft=request.draft,
        pr_body=request.pr_body,
        owned_paths=request.owned_paths,
        envelope_authority_preimage=original.envelope_authority_preimage,
    )
    monkeypatch.setattr(correction, "validate_source", lambda *_args: original)
    monkeypatch.setattr(
        exact_case.service,
        "_validated_envelope",
        lambda _request: (None, successor),
    )
    owner = (exact_case.store / "adapter-start-owner.json").read_bytes()
    admissions = (exact_case.store / "admissions.jsonl").read_bytes()
    with pytest.raises(
        correction.ScopeCorrectionPredecessorUnavailable,
        match="ownership-scope no-effect",
    ):
        correction.authorize(exact_case.service, request)
    assert not list(exact_case.store.glob("scope-correction-*.json"))
    assert (exact_case.store / "adapter-start-owner.json").read_bytes() == owner
    assert (exact_case.store / "admissions.jsonl").read_bytes() == admissions
    assert exact_case.service.adapter.calls == []


def test_group_3_scope_correction_reserves_once_when_only_settled_key_blocks(
    exact_case, monkeypatch
):
    from dataclasses import replace

    from phase_loop_runtime import publish_scope_correction as correction
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord

    _settle(exact_case)
    transaction_b, request_b = _new_transaction(exact_case, "scope-predecessor-b")
    key_b = exact_case.service._dedup_key(request_b)
    exact_case.service.evidence_store.record_intent(key_b)
    exact_case.service.evidence_store.record_terminal(
        EvidenceRecord(
            key_b,
            TerminalOutcomeState.NO_EFFECT_TERMINAL_PROVEN,
            "owned-scope-exceeded:outside.py",
        )
    )
    owner_b = AdapterStartOwnership(
        repository_identity=request_b.repo,
        idempotency_key=key_b,
        transaction_id=transaction_b.transaction_id,
        attempt_id="scope-predecessor-attempt",
        committed_head=request_b.head_sha,
        adapter_operation="publish_committed_branch",
        owner_nonce="scope-predecessor-owner",
        effect_key=key_b,
        sealed=True,
    )
    append_adapter_start_owner(exact_case.store, owner_b)
    request = replace(
        request_b,
        scope_correction_of=transaction_b.transaction_id,
    )
    original = SimpleNamespace(
        transaction_id=transaction_b.transaction_id,
        final_commit_object_sha256=transaction_b.final_commit_object_sha256,
        owned_paths=transaction_b.owned_paths,
        envelope_authority_preimage=transaction_b.envelope_authority_preimage,
    )
    successor = SimpleNamespace(
        transaction_id="e" * 64,
        base=request.base,
        draft=request.draft,
        pr_body=request.pr_body,
        owned_paths=request.owned_paths,
        envelope_authority_preimage=original.envelope_authority_preimage,
    )
    monkeypatch.setattr(correction, "validate_source", lambda *_args: original)
    monkeypatch.setattr(
        exact_case.service,
        "_validated_envelope",
        lambda _request: (None, successor),
    )
    exact_case.service.adapter = _CountingAdapter(explode=True)
    evidence_before_other = (exact_case.store / "evidence.jsonl").read_bytes()
    _block_distinct(
        exact_case.service, "publish_committed_branch\0unsettled-scope-key"
    )
    with pytest.raises(PermissionError, match="blocked partition"):
        correction.authorize(exact_case.service, request)
    assert not list(exact_case.store.glob("scope-correction-*.json"))

    (exact_case.store / "evidence.jsonl").write_bytes(evidence_before_other)
    first = correction.authorize(exact_case.service, request)
    second = correction.authorize(exact_case.service, request)
    assert first == second
    assert len(list(exact_case.store.glob("scope-correction-*.json"))) == 1
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
    if binding == "disposition":
        entry["observed_head"] = None
        entry["branch_absent"] = True
        entry.pop("settlement_digest")
    attestation = _rotation_attestation(
        exact_case, exact_case.store, 0, {exact_case.key: entry}
    )
    _release_service(exact_case.service)
    with pytest.raises(
        live.PartitionRotationRefused,
        match="must carry its exact observed head",
    ):
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


def test_group_1_admission_failure_restores_retired_owner_bytes(exact_case, monkeypatch):
    _settle(exact_case)
    path = exact_case.store / "adapter-start-owner.json"
    _transaction_b, request_b = _new_transaction(exact_case, "rollback-b")

    def refuse(*_args, **_kwargs):
        raise PermissionError("synthetic admission failure")

    monkeypatch.setattr(exact_case.service.admission_store, "admit_next", refuse)
    with pytest.raises(PermissionError, match="synthetic admission failure"):
        exact_case.service.execute(request_b)
    assert path.read_bytes() == exact_case.owner_bytes
    assert exact.current_owner_is_settlement_retired(
        exact_case.store, path.read_bytes(), exact_case.key
    ) is True
    assert isinstance(_settlement(exact_case), exact.ValidExactPRSettlement)


def test_group_1_admission_failure_does_not_overwrite_replacement_owner(
    exact_case, monkeypatch
):
    _settle(exact_case)
    path = exact_case.store / "adapter-start-owner.json"
    _transaction_b, request_b = _new_transaction(exact_case, "rollback-replaced-b")
    original = json.loads(exact_case.owner_bytes)
    owner_c = AdapterStartOwnership(
        repository_identity=original["repository_identity"],
        idempotency_key="publish_committed_branch\0C",
        transaction_id="transaction-C",
        attempt_id="attempt-C",
        committed_head="c" * 40,
        adapter_operation="publish_committed_branch",
        owner_nonce="nonce-C",
        effect_key="publish_committed_branch\0C",
        sealed=False,
    )
    owner_c_bytes = _canonical(owner_c.__dict__) + b"\n"

    def replace_then_refuse(*_args, **_kwargs):
        path.write_bytes(owner_c_bytes)
        raise PermissionError("synthetic replaced-owner admission failure")

    monkeypatch.setattr(
        exact_case.service.admission_store, "admit_next", replace_then_refuse
    )
    with pytest.raises(PermissionError, match="replaced-owner admission failure"):
        exact_case.service.execute(request_b)
    assert path.read_bytes() == owner_c_bytes


def test_group_1_retired_owner_guards_and_replay_precedence(
    exact_case, monkeypatch
):
    from phase_loop_runtime.convergence.broker.evidence import EvidenceRecord

    _settle(exact_case)
    owner = AdapterStartOwnership(**json.loads(exact_case.owner_bytes))
    row = exact_case.service.evidence_store.replay()[exact_case.key]
    in_flight = EvidenceRecord(
        exact_case.key, TerminalOutcomeState.PROVIDER_CALL_IN_FLIGHT
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            exact_case.service.evidence_store,
            "replay",
            lambda *_args, **_kwargs: {exact_case.key: in_flight},
        )
        assert (
            exact_case.service._provider_entry_guard(exact_case.key, owner)
            == in_flight
        )
    with pytest.raises(PermissionError, match="retired"):
        validate_adapter_start_owner(exact_case.store, owner)
    exact_case.service.adapter = _CountingAdapter(explode=True)
    replayed = exact_case.service._replay(
        exact_case.request, exact_case.key, row
    )
    assert replayed.reason == "exact_pr_reconciled"
    assert replayed.provider_call_made is False
    assert exact_case.service.adapter.calls == []


def test_group_1_malformed_or_absent_settlement_never_retires_owner(exact_case):
    _settle(exact_case)
    path = exact.settlement_path(exact_case.store, exact_case.key)
    path.write_bytes(b"{malformed")
    with pytest.raises(exact.ExactPRReconciliationRefused):
        exact.current_owner_is_settlement_retired(
            exact_case.store, exact_case.owner_bytes, exact_case.key
        )

    unknown_key = "publish_committed_branch\0unknown"
    assert exact.current_owner_is_settlement_retired(
        exact_case.store, exact_case.owner_bytes, unknown_key
    ) is False


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


def test_reader_requires_the_exact_durable_compatibility_observation(exact_case):
    _settle(exact_case)
    observation = exact_case.store / "post-ambiguity-observations.jsonl"
    observation.write_bytes(b"")
    value = exact.read_exact_pr_settlement(
        exact.snapshot_exact_pr_store(exact_case.store), exact_case.key
    )
    assert isinstance(value, exact.ExactPRTypedRefusal)
    assert "durable compatibility observation" in value.reason
    with pytest.raises(exact.ExactPRReconciliationRefused):
        _ = BrokerEvidenceStore(exact_case.store).epoch_blocked
    exact_case.service.adapter = _CountingAdapter(explode=True)
    with pytest.raises(PermissionError):
        exact_case.service.execute(exact_case.request)
    assert exact_case.service.adapter.calls == []


def test_direct_settlement_binds_its_generation_receipt_and_ambiguity(exact_case):
    _settle(exact_case)
    body = exact.settlement_path(exact_case.store, exact_case.key).read_bytes()
    successor = exact_case.store / live.GENERATIONS_DIR / "1"
    directory = successor / exact.SETTLEMENT_DIRECTORY
    directory.mkdir(parents=True)
    (directory / exact.settlement_filename(exact_case.key)).write_bytes(body)
    snapshot = exact.ExactPRStoreSnapshot(
        root=successor,
        receipt=None,
        receipt_bytes=b"different-generation-receipt",
        evidence_bytes=exact_case.ambiguity_line + b"\n",
        observation_bytes=(
            exact_case.store / "post-ambiguity-observations.jsonl"
        ).read_bytes(),
        settlement_files={exact.settlement_filename(exact_case.key): body},
        temporary_files=(),
        generation=1,
    )
    value = exact.read_exact_pr_settlement(snapshot, exact_case.key)
    assert isinstance(value, exact.ExactPRTypedRefusal)
    assert "does not bind this generation" in value.reason


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


def test_b4_two_identical_subprocess_callers_overlap_and_return_one_receipt(
    exact_case, tmp_path
):
    first, second = _run_concurrent_reconciliation(
        exact_case, tmp_path, exact_case.disposition
    )
    assert first["status"] == second["status"] == "ok"
    assert first["settlement_digest"] == second["settlement_digest"]
    assert {first["path"], second["path"]} == {"witness", "contended_wait"}
    assert len(list((exact_case.store / exact.SETTLEMENT_DIRECTORY).glob("*.json"))) == 1
    observations = [
        json.loads(line)
        for line in (
            exact_case.store / "post-ambiguity-observations.jsonl"
        ).read_text().splitlines()
    ]
    assert sum(row.get("idempotency_key") == exact_case.key for row in observations) == 1


def test_b4_competing_subprocess_dispositions_never_overwrite_winner(
    exact_case, tmp_path
):
    competing = copy.deepcopy(exact_case.disposition)
    competing["owner_instruction_reference"] += "-different"
    first, second = _run_concurrent_reconciliation(exact_case, tmp_path, competing)
    assert first["status"] == "ok"
    assert first["path"] == "witness"
    assert second["status"] == "error"
    assert second["path"] == "contended_wait"
    assert "conflicting" in second["error"]
    assert _settlement(exact_case).settlement_digest == first["settlement_digest"]
    assert len(list((exact_case.store / exact.SETTLEMENT_DIRECTORY).glob("*.json"))) == 1


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
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "legacy_0_7_27"
        / "phase_loop_runtime"
    )
    assert (fixture / "__init__.py").read_bytes() == b'__version__ = "0.7.27"\n'
    for relative, record_hash in LEGACY_0_7_27_RECORD_HASHES.items():
        digest = base64.urlsafe_b64encode(
            hashlib.sha256((fixture / relative).read_bytes()).digest()
        ).decode("ascii").rstrip("=")
        assert digest == record_hash

    script = r'''
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import phase_loop_runtime

convergence = types.ModuleType("phase_loop_runtime.convergence")
convergence.__path__ = [str(Path(sys.argv[1]) / "phase_loop_runtime" / "convergence")]
sys.modules["phase_loop_runtime.convergence"] = convergence
broker = types.ModuleType("phase_loop_runtime.convergence.broker")
broker.__path__ = [str(Path(convergence.__path__[0]) / "broker")]
sys.modules["phase_loop_runtime.convergence.broker"] = broker
from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    BrokerRequest,
    BrokerVerb,
)
from phase_loop_runtime.convergence.broker.admission import LinearizableAdmissionStore
from phase_loop_runtime.convergence.broker.evidence import BrokerEvidenceStore
from phase_loop_runtime.convergence.broker import live
from phase_loop_runtime.convergence.broker.verbs import (
    BrokerService,
    read_adapter_start_owner,
)

root = Path(sys.argv[2])
key = bytes.fromhex(sys.argv[3]).decode()
repository, branch, head = sys.argv[4:7]

class CountingAdapter:
    def __init__(self):
        self.calls = 0
    def execute(self, _request):
        self.calls += 1
        raise AssertionError("legacy replay entered the provider")

evidence = BrokerEvidenceStore(root)
admission = LinearizableAdmissionStore(root, epoch_blocked=lambda: evidence.epoch_blocked)
adapter = CountingAdapter()
service = BrokerService(admission, evidence, adapter)
owner = read_adapter_start_owner(root, repository_identity=repository)
before = (root / "evidence.jsonl").read_bytes()
owner_blocked = service._block_unsealed_owner(owner)
after = (root / "evidence.jsonl").read_bytes()

try:
    live._refuse_attested_not_landed_over_observations(
        root,
        {key: {"disposition": live.DISPOSITION_ATTESTED_NOT_LANDED}},
    )
    fence = False
except live.PartitionRotationRefused:
    fence = True

request = BrokerRequest(
    BrokerVerb.PUBLISH_COMMITTED_BRANCH,
    AdmissionRequest("attempt", 1, "fence", "approval", "version", "scope", key),
    repository,
    branch,
    head,
    ("repair.py",),
)
assert service._dedup_key(request) == key
result = service.execute(request)
print(json.dumps({
    "epoch_blocked": evidence.epoch_blocked,
    "owner_blocked": owner_blocked,
    "evidence_unchanged": before == after,
    "fence": fence,
    "provider_calls": adapter.calls,
    "reason": result.reason,
}))
'''
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PYTHON")
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            script,
            str(fixture.parent),
            str(exact_case.store),
            exact_case.key.encode().hex(),
            exact_case.disposition["canonical_repository_identity"],
            exact_case.disposition["head_ref"],
            exact_case.disposition["head_sha"],
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "epoch_blocked": True,
        "owner_blocked": True,
        "evidence_unchanged": True,
        "fence": True,
        "provider_calls": 0,
        "reason": "effect_observed_after_ambiguity",
    }


def test_group_9_old_shape_rotation_refuses_only_the_settled_key(
    exact_case, monkeypatch
):
    _settle(exact_case)
    owner = json.loads(exact_case.owner_bytes)

    def old_side_files(root):
        observation = root / "post-ambiguity-observations.jsonl"
        return {}, observation.read_bytes() if observation.exists() else None

    effects_a = {
        exact_case.key: {
            "disposition": live.DISPOSITION_OBSERVED_LANDED,
            "observed_head": exact_case.disposition["head_sha"],
            "branch_absent": False,
            "evidence_url": PR_URL,
            "ambiguity_digest": _ambiguity_digest(exact_case.store, exact_case.key),
            "owner_nonce": owner["owner_nonce"],
            "transaction_id": owner["transaction_id"],
        }
    }
    attestation = _rotation_attestation(
        exact_case, exact_case.store, 0, effects_a
    )
    attestation.pop("exact_pr_settlement_snapshot_sha256", None)
    _release_service(exact_case.service)
    with monkeypatch.context() as patch:
        patch.setattr(live, "_snapshot_exact_pr_side_files", old_side_files)
        generation_one = live.rotate_blocked_partition(
            exact_case.repo,
            cutover_id="old-shape-one",
            attestation=attestation,
            authority_root=Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
        ).store_root

    assert live.load_partition_receipt(generation_one) is not None
    value = exact.effective_publication(
        exact.snapshot_exact_pr_store(generation_one), exact_case.key
    )
    assert isinstance(value, exact.ExactPRTypedRefusal)
    assert "omitted" in value.reason

    adapter_one = _CountingAdapter(explode=True)
    service_one = _service(generation_one, adapter_one)
    with pytest.raises(PermissionError, match="omitted"):
        service_one.execute(exact_case.request)
    assert adapter_one.calls == []

    _transaction_b, request_b = _new_transaction(exact_case, "old-shape-unrelated-b")
    publish_adapter_one = _CountingAdapter()
    service_one.adapter = publish_adapter_one
    published_b = service_one.execute(request_b)
    assert published_b.accepted is True
    assert len(publish_adapter_one.calls) == 1

    key_c = "publish_committed_branch\0old-shape-C"
    _block_distinct(service_one, key_c)
    effects_c = {
        key_c: {
            "disposition": live.DISPOSITION_ATTESTED_NOT_LANDED,
            "observed_head": None,
            "branch_absent": True,
            "evidence_url": "https://example.invalid/old-shape-C",
            "ambiguity_digest": _ambiguity_digest(generation_one, key_c),
        }
    }
    second_attestation = _rotation_attestation(
        exact_case, generation_one, 1, effects_c
    )
    _release_service(service_one)
    with monkeypatch.context() as patch:
        patch.setattr(live, "_snapshot_exact_pr_side_files", old_side_files)
        generation_two = live.rotate_blocked_partition(
            exact_case.repo,
            cutover_id="old-shape-two",
            attestation=second_attestation,
            authority_root=Path(os.environ[live.FABPUB_AUTHORITY_ROOT_ENV]),
        ).store_root

    assert live.load_partition_receipt(generation_two) is not None
    value = exact.effective_publication(
        exact.snapshot_exact_pr_store(generation_two), exact_case.key
    )
    assert isinstance(value, exact.ExactPRTypedRefusal)
    assert "omitted" in value.reason
    adapter_two = _CountingAdapter(explode=True)
    service_two = _service(generation_two, adapter_two)
    with pytest.raises(PermissionError, match="omitted"):
        service_two.execute(exact_case.request)
    assert adapter_two.calls == []

    _transaction_d, request_d = _new_transaction(exact_case, "old-shape-unrelated-d")
    publish_adapter_two = _CountingAdapter()
    service_two.adapter = publish_adapter_two
    published_d = service_two.execute(request_d)
    assert published_d.accepted is True
    assert len(publish_adapter_two.calls) == 1


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


def test_cli_reconcile_check_json_and_refusal_exit_codes(
    exact_case, monkeypatch, tmp_path, capsys
):
    from phase_loop_runtime import cli
    from phase_loop_runtime.convergence.broker import credsep

    disposition = tmp_path / "disposition.json"
    disposition.write_bytes(_canonical(exact_case.disposition) + b"\n")
    runner = exact_case.runner()
    adapter_class = credsep.GitHubBrokerAdapter
    monkeypatch.setattr(
        credsep,
        "GitHubBrokerAdapter",
        lambda worktree: adapter_class(Path(worktree), run=runner),
    )
    with _assert_zero_writes(_zero_write_roots(exact_case)):
        code = cli.main(
            [
                "fabpub-reconcile-exact-pr",
                "--worktree", str(exact_case.repo),
                "--authority-root", str(exact_case.authority),
                "--transaction-id", exact_case.transaction.transaction_id,
                "--pr-url", PR_URL,
                "--disposition", str(disposition),
                "--check",
                "--json",
            ]
        )
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["commit_authorized"] is False
    assert captured.err == ""
    runner.assert_allowlisted()

    disposition.write_text('{"schema":"ExactPRReconciliationDisposition.v1"}\n')
    code = cli.main(
        [
            "fabpub-reconcile-exact-pr",
            "--worktree", str(exact_case.repo),
            "--authority-root", str(exact_case.authority),
            "--transaction-id", exact_case.transaction.transaction_id,
            "--pr-url", PR_URL,
            "--disposition", str(disposition),
            "--check",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "fabpub-reconcile-exact-pr" in captured.err


def test_cli_inspect_missing_authority_refuses_without_creation(
    exact_case, tmp_path, capsys
):
    from phase_loop_runtime import cli

    missing = tmp_path / "missing-inspect-authority"
    code = cli.main(
        [
            "fabpub-inspect-exact-pr",
            "--worktree", str(exact_case.repo),
            "--authority-root", str(missing),
            "--transaction-id", exact_case.transaction.transaction_id,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "fabpub-inspect-exact-pr" in captured.err
    assert not missing.exists()
