"""Durable, metadata-only broker admission ordering."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from phase_loop_runtime.convergence.contracts import (
    AdmissionRequest,
    DeltaReadmitAuthority,
    DeltaReadmitReceipt,
    PreAdmissionEnvelope,
    ReadmitAdmissionBinding,
    publish_committed_branch_idempotency_key,
)


@dataclass(frozen=True)
class AdmissionRecord:
    sequence: int
    epoch: int
    request: AdmissionRequest | DeltaReadmitAuthority | PreAdmissionEnvelope
    binding: ReadmitAdmissionBinding | None = None


BrokerAdmissionPolicy = Callable[[Any], bool]


def validate_checkpoint_root(
    checkpoint_root: str,
    repository: str,
    train_id: str,
    node_id: str,
) -> bool:
    ckpt_path = Path(checkpoint_root)
    if not ckpt_path.is_absolute():
        raise ValueError(f"relative checkpoint_root path: {checkpoint_root}")
    if not ckpt_path.is_dir():
        raise ValueError(f"missing checkpoint_root directory: {checkpoint_root}")

    train_file = ckpt_path / "train.json"
    if train_file.exists():
        try:
            train_data = json.loads(train_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"invalid train.json in checkpoint_root: {e}") from e
        if train_data.get("train_id") and train_data.get("train_id") != train_id:
            raise ValueError(f"train_id mismatch: expected {train_id}, got {train_data.get('train_id')}")
        if train_data.get("repository") and train_data.get("repository") != repository:
            raise ValueError(f"repository mismatch: expected {repository}, got {train_data.get('repository')}")

    node_file = ckpt_path / f"{node_id}.json"
    if node_file.exists():
        try:
            node_data = json.loads(node_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"invalid {node_id}.json in checkpoint_root: {e}") from e
        if node_data.get("node_id") and node_data.get("node_id") != node_id:
            raise ValueError(f"node_id mismatch: expected {node_id}, got {node_data.get('node_id')}")
    else:
        other_node_files = [f for f in ckpt_path.glob("*.json") if f.name != "train.json"]
        if other_node_files:
            raise ValueError(f"node_id mismatch: checkpoint_root carries node files {other_node_files!r} but not expected {node_id}.json")

    return True




def get_canonical_repository_store(
    repo_dir: Path | str,
    checkpoint_root: Path | str | None = None,
) -> LinearizableAdmissionStore:
    from .live import canonical_repository_identity, repository_broker_namespace

    repo_path = Path(repo_dir)
    canonical_repo = canonical_repository_identity(repo_path)
    store_dir = repository_broker_namespace(repo_path)
    store = LinearizableAdmissionStore(store_dir)
    object.__setattr__(store, "canonical_repository", canonical_repo)
    return store


def _fabpub_active() -> bool:
    """Activation probe that never downgrades on a configuration failure."""
    from .live import fabpub_capability_active

    return fabpub_capability_active()


#: "The caller declared no lease at all", distinct from an explicit
#: ``generation_lease=None``.  A DECLARED absence is denied under an ACTIVE
#: generation; an undeclared one is validated against latch state only, because
#: the frozen compatibility helpers construct stores without the argument.
_UNDECLARED = object()


class LinearizableAdmissionStore:
    """Append-only admission log guarded by an OS advisory lock."""
    def __init__(
        self,
        root: Path,
        policy: BrokerAdmissionPolicy | None = None,
        epoch_blocked: Callable[[], bool] | None = None,
        generation_lease=_UNDECLARED,
    ) -> None:
        self.root = root
        self.policy = policy if policy is not None else (lambda _: True)
        self.epoch_blocked = epoch_blocked or (lambda: False)
        # The FABPUB WriterGenerationLease.v1 this store writes under.  It is
        # revalidated by exact nonce inside the store lock before every append.
        self.generation_lease = generation_lease
        if not _fabpub_active():
            self.root.mkdir(parents=True, exist_ok=True)
        self.path, self.lock_path = root / "admissions.jsonl", root / "admissions.lock"


    @property
    def store_dir(self) -> Path:
        return self.root

    def _authorize(self) -> None:
        """Authenticate BEFORE any directory creation, then create the tree."""
        from .live import REPOSITORY_NAMESPACE_DIR, authenticated_partition_floor

        self._require_generation()
        canonical_store = (
            self.root.parent.name == "repositories"
            and self.root.parent.parent.name == REPOSITORY_NAMESPACE_DIR
        )
        if _fabpub_active() and (
            self.generation_lease is not _UNDECLARED or canonical_store
        ):
            authenticated_partition_floor(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _require_generation(self) -> None:
        """In-lock generation revalidation; closes the check/use race."""
        from .live import require_current_generation

        lease = self.generation_lease
        if lease is _UNDECLARED:
            require_current_generation(self.root, None, strict=False)
        else:
            require_current_generation(self.root, lease, strict=True)

    def _records(self) -> list[AdmissionRecord]:
        if not self.path.exists(): return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            raw = json.loads(line)
            if "binding" in raw and raw["binding"] is not None:
                b = raw["binding"]
                if isinstance(b.get("owned_scope"), list):
                    b["owned_scope"] = tuple(b["owned_scope"])
                raw["binding"] = ReadmitAdmissionBinding(**b)
            if "request" in raw and isinstance(raw["request"], dict):
                req_dict = raw["request"]
                if "proposed_head_sha" in req_dict:
                    if isinstance(req_dict.get("owned_scope"), list):
                        req_dict["owned_scope"] = tuple(req_dict["owned_scope"])
                    raw["request"] = DeltaReadmitAuthority(**req_dict)
                elif "idempotency_key" in req_dict:
                    raw["request"] = AdmissionRequest(**req_dict)
                elif "canonical_repository_identity" in req_dict:
                    raw["request"] = PreAdmissionEnvelope(**req_dict)
            records.append(AdmissionRecord(**raw))
        return records

    def _canonical_high_water(self, records: list[AdmissionRecord]) -> int:
        """The canonical floor: ``max(record.epoch)``, or 0 when none exists."""
        return max((record.epoch for record in records), default=0)

    def admit_next(
        self,
        make_request_or_auth: Callable[[int, str], AdmissionRequest] | DeltaReadmitAuthority,
        *,
        attempt_id: str | None = None,
        precondition: Callable[[], bool] | None = None,
    ) -> AdmissionRecord | DeltaReadmitReceipt:
        import fcntl
        from .live import authenticated_partition_floor

        is_delta_auth = hasattr(make_request_or_auth, "proposed_head_sha") and hasattr(make_request_or_auth, "prior_head_sha")
        if is_delta_auth:
            auth = make_request_or_auth
            self._authorize()
            with self.lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    self._require_generation()
                    if self.epoch_blocked() or self.policy is None:
                        raise PermissionError("broker admission denied: epoch blocked")
                    if not self.policy(auth):
                        raise PermissionError("broker admission denied by policy")


                    try:
                        validate_checkpoint_root(
                            checkpoint_root=auth.checkpoint_root,
                            repository=auth.repository,
                            train_id=auth.train_id,
                            node_id=auth.node_id,
                        )
                    except ValueError as ve:
                        raise PermissionError(f"checkpoint root validation failed: {ve}") from ve

                    records = self._records()

                    def branch_head(
                        record: AdmissionRecord,
                    ) -> tuple[str, str, str] | None:
                        if record.binding is not None:
                            return (
                                getattr(record.request, "repository", ""),
                                getattr(record.request, "branch", ""),
                                record.binding.proposed_head_sha,
                            )
                        if isinstance(record.request, PreAdmissionEnvelope):
                            prefix = "publish:"
                            if not record.request.operation_identity.startswith(prefix):
                                return None
                            return (
                                record.request.canonical_repository_identity,
                                record.request.operation_identity[len(prefix):],
                                record.request.committed_head_sha,
                            )
                        if isinstance(record.request, AdmissionRequest):
                            expected = publish_committed_branch_idempotency_key(
                                auth.repository,
                                auth.branch,
                                auth.prior_head_sha,
                            )
                            if record.request.idempotency_key == (
                                f"publish_committed_branch\0{expected}"
                            ):
                                return (
                                    auth.repository,
                                    auth.branch,
                                    auth.prior_head_sha,
                                )
                        return None

                    # Deduplication check
                    for record in records:
                        if record.binding is not None and record.binding.authority_digest == auth.authority_digest:
                            latest_for_branch = None
                            for r in records:
                                decoded = branch_head(r)
                                if decoded is None:
                                    continue
                                rec_repo, rec_branch, head_sha = decoded
                                if (
                                    rec_repo == auth.repository
                                    and rec_branch == auth.branch
                                ):
                                    latest_for_branch = head_sha
                            if latest_for_branch and latest_for_branch != auth.prior_head_sha and latest_for_branch != auth.proposed_head_sha:
                                raise PermissionError(f"stale prior head on deduplication: {auth.prior_head_sha} is not latest {latest_for_branch}")
                            return record

                    # Prior record predicate check
                    matching_history = [
                        (decoded[2], record)
                        for record in records
                        if (decoded := branch_head(record)) is not None
                        and decoded[0] == auth.repository
                        and decoded[1] == auth.branch
                    ]

                    if not matching_history:
                        raise PermissionError(f"unadmitted or empty store: prior head {auth.prior_head_sha} has no prior admission on branch {auth.branch}")

                    if not any(h == auth.prior_head_sha for h, _ in matching_history):
                        raise PermissionError(f"unadmitted or forged prior head: {auth.prior_head_sha}")

                    latest_head_sha, latest_record = matching_history[-1]
                    if auth.prior_head_sha != latest_head_sha:
                        raise PermissionError(f"stale prior head: {auth.prior_head_sha} is not latest {latest_head_sha}")

                    if latest_record is not None:
                        prior_node = latest_record.binding.node_id if latest_record.binding is not None else (
                            getattr(latest_record.request, "node_id", None)
                            or (latest_record.request.envelope_authority_preimage.get("node_id") if isinstance(latest_record.request, PreAdmissionEnvelope) and hasattr(latest_record.request, "envelope_authority_preimage") else None)
                        )
                        if prior_node and prior_node != auth.node_id:
                            raise PermissionError(f"node_id mismatch: expected {prior_node}, got {auth.node_id}")

                    if latest_record is not None and latest_record.binding is not None:
                        if latest_record.binding.owned_scope != auth.owned_scope:
                            raise PermissionError(f"scope mismatch: expected {latest_record.binding.owned_scope}, got {auth.owned_scope}")

                    # Cross-check and prove pre-existing first-hop publish transaction at checkpoint_root
                    from phase_loop_runtime.publishing import PublishTransactionStore
                    store_pub = PublishTransactionStore(Path(auth.checkpoint_root), auth.node_id)
                    active_ptr = store_pub.load_active()
                    if not active_ptr or not active_ptr.get("transaction_id"):
                        store_pub = PublishTransactionStore(Path(auth.checkpoint_root), "node")
                        active_ptr = store_pub.load_active()
                    if not active_ptr or not active_ptr.get("transaction_id"):
                        raise PermissionError(f"publish transaction absent or missing at checkpoint_root: {auth.checkpoint_root}")

                    ckpt_file = store_pub.checkpoint_path(active_ptr["transaction_id"])
                    if not ckpt_file.exists():
                        raise PermissionError(f"publish transaction checkpoint missing: {ckpt_file}")

                    active_pub = json.loads(ckpt_file.read_text(encoding="utf-8"))
                    if active_pub.get("state") in ("ABANDONED", "CONFLICTED"):
                        raise PermissionError(f"publish transaction state invalid: {active_pub.get('state')}")

                    pub_committed_head = active_pub.get("committed_head_sha") or active_pub.get("expected_commit_oid") or active_pub.get("parent_head_sha")
                    if latest_record.binding is None and pub_committed_head and pub_committed_head != auth.prior_head_sha:
                        raise PermissionError(f"node_id mismatch: transaction committed head {pub_committed_head} != prior_head_sha {auth.prior_head_sha}")

                    pub_branch = active_pub.get("branch")
                    if pub_branch and pub_branch != auth.branch:
                        raise PermissionError(f"idempotency key mismatch: branch mismatch {pub_branch} != {auth.branch}")

                    envelope_preimage = active_pub.get("envelope_authority_preimage") or {}
                    pub_node = active_pub.get("node_id") or envelope_preimage.get("node_id")
                    if pub_node and pub_node != auth.node_id:
                        raise PermissionError(f"node_id mismatch: expected {pub_node}, got {auth.node_id}")


                    pub_scope = tuple(active_pub.get("owned_paths", ()))
                    if pub_scope and pub_scope != auth.owned_scope:
                        raise PermissionError(f"scope mismatch: expected {pub_scope}, got {auth.owned_scope}")

                    if auth.adapter_worktree:
                        import subprocess
                        try:
                            diff_out = subprocess.check_output(
                                ["git", "-C", auth.adapter_worktree, "diff", "--name-only", f"{auth.prior_head_sha}..{auth.proposed_head_sha}"],
                                text=True,
                                stderr=subprocess.PIPE,
                            )
                        except subprocess.CalledProcessError as e:
                            raise PermissionError(f"git diff failed for proposed head range: {e.stderr or e}") from e

                        changed_paths = [p.strip() for p in diff_out.splitlines() if p.strip()]
                        for path in changed_paths:
                            if not any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in auth.owned_scope):
                                raise PermissionError(f"unowned path in diff: {path} outside scope {auth.owned_scope}")

                    epoch = max(self._canonical_high_water(records), 0) + 1

                    binding = ReadmitAdmissionBinding(
                        prior_head_sha=auth.prior_head_sha,
                        proposed_head_sha=auth.proposed_head_sha,
                        node_id=auth.node_id,
                        owned_scope=auth.owned_scope,
                        authority_digest=auth.authority_digest,
                        attempt_identity=auth.attempt_identity,
                    )
                    record = AdmissionRecord(len(records) + 1, epoch, auth, binding=binding)
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    return record



                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

        # Standard callable branch for make_request
        make_request = make_request_or_auth
        assert attempt_id is not None
        assert precondition is not None

        self._authorize()
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self._require_generation()
                if self.epoch_blocked() or self.policy is None:
                    raise PermissionError("broker admission denied")
                records = self._records()

                for record in records:
                    if not isinstance(record.request, AdmissionRequest) and not isinstance(record.request, PreAdmissionEnvelope):
                        continue
                    if getattr(record.request, "attempt_id", None) != attempt_id:
                        continue
                    rebuilt = make_request(record.epoch, attempt_id)
                    if rebuilt.lease_epoch != record.epoch:
                        raise ValueError(
                            "admit_next dedup must rebuild at the prior epoch "
                            f"{record.epoch}, got {rebuilt.lease_epoch}"
                        )
                    if rebuilt.attempt_id != attempt_id:
                        raise ValueError("admit_next dedup rebuilt a different attempt_id")
                    if rebuilt != record.request:
                        raise ValueError("conflicting authority for an existing attempt_id")
                    if not self.policy(rebuilt):
                        raise PermissionError("broker admission denied")
                    if not precondition():
                        raise PermissionError("broker admission precondition denied")
                    return record

                if not precondition():
                    raise PermissionError("broker admission precondition denied")

                epoch = max(
                    self._canonical_high_water(records),
                    authenticated_partition_floor(self.root),
                ) + 1

                request = make_request(epoch, attempt_id)
                if request.lease_epoch != epoch:
                    raise ValueError(
                        f"admit_next requires lease_epoch == allocated epoch {epoch}, "
                        f"got {request.lease_epoch}"
                    )
                if request.attempt_id != attempt_id:
                    raise ValueError("admit_next requires the supplied attempt_id")
                if not self.policy(request):
                    raise PermissionError("broker admission denied")

                record = AdmissionRecord(len(records) + 1, epoch, request)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(record), sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                return record
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def admit(self, request: AdmissionRequest) -> AdmissionRecord:
        import fcntl
        self._authorize()
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self._require_generation()
                if self.epoch_blocked() or self.policy is None or not self.policy(request):
                    raise PermissionError("broker admission denied")
                records = self._records()
                for record in records:
                    if hasattr(record.request, "idempotency_key") and record.request.idempotency_key == request.idempotency_key:
                        if record.request != request: raise ValueError("conflicting idempotency key")
                        return record
                if records and request.lease_epoch < max(r.epoch for r in records): raise PermissionError("stale epoch")
                record = AdmissionRecord(len(records) + 1, request.lease_epoch, request)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(asdict(record), sort_keys=True) + "\n"); stream.flush(); os.fsync(stream.fileno())
                return record
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    def replay(self) -> tuple[AdmissionRecord, ...]: return tuple(self._records())
