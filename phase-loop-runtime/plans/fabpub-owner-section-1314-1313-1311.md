# FABPUB owner section: refusals leave no owner; liveness before ambiguity

Issues: agent-harness#1314, agent-harness#1313, agent-harness#1311 (follow-ups of
the board ruling on agent-harness#1298). One branch, done in that order, because
all three live in `BrokerService._owner_and_admission_under_one_lock` and
`BrokerService._block_unsealed_owner`
(`phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`).

## Context

`_fresh_publish` writes a durable `AdapterStartOwnership` and allocates an
admission inside ONE `admissions.lock` acquisition (ah#789). agent-harness#1298
moved the transaction-state precondition ahead of the owner write. Everything
`admit_next` refuses still runs AFTER the owner write, and a later attempt
promotes any unsealed owner without a known terminal to permanent
`outcome_ambiguous_blocked`, even when the owner's writer is still running.

## 1. agent-harness#1314: a refused section leaves the owner state it found

Refusals reachable in `LinearizableAdmissionStore.admit_next` (callable branch,
`lock_held=True`) after `append_adapter_start_owner` has returned:

- `self._authorize()`: `_require_generation` (lease nonce), `is_canonical_store_root`
  plus `authenticated_partition_floor`, and the `mkdir` (`OSError`);
- `_require_lock_held` (`RuntimeError`, unreachable here: the section holds the lock);
- the in-lock `_require_generation()` again;
- `epoch_blocked() or policy is None` → `PermissionError("broker admission denied")`;
- `_records()` → `AdmissionStoreIncompatible` / JSON errors (read once already at
  the top of the section under the same acquisition, so practically unreachable);
- the dedup loop: three `ValueError`s for a rebuilt request that differs, `policy(rebuilt)`,
  `precondition()` (the section passes `lambda: True`);
- `authenticated_partition_floor(self.root)` for the epoch floor;
- `make_request` errors and the `lease_epoch` / `attempt_id` `ValueError`s;
- `policy(request)` on the fresh request;
- the admission append itself (`OSError`).

**Choice: (b) restore, not (a) hoist.** `policy(request)` needs the allocated
epoch, which needs the high-water mark and the authenticated partition floor, so
hoisting means re-implementing `admit_next` in `verbs.py`; the copy would drift
from the store (and from test stores that wrap `admit_next`). Restoring under the
same acquisition keeps ah#789 intact: no writer of any version can observe the
owner between write and admission or between write and restore, because both
happen inside the one `admissions.lock` hold.

Mechanics, inside the section:

- Before the write, capture the raw bytes of `adapter-start-owner.json` (absent,
  or a sealed owner; an unsealed one already returned to the caller as foreign).
- Wrap everything after the owner write in `try/except Exception`. On a refusal,
  if the recorded owner is ours (same `owner_nonce`; never retire someone else's),
  restore the captured bytes atomically (or unlink when there were none, then
  fsync the directory) and re-raise the original exception unchanged.
- `PublishCrashInjected` is re-raised WITHOUT a restore: a simulated crash must
  not get a cleanup a real crash would not get.

Restoring the exact prior bytes (not sealing our owner) matters because rotation
reads the owner's `transaction_id` for the predecessor binding
(`live._rotation_owner_identity`); overwriting a predecessor's sealed owner with
an owner that never reached the provider would rebind it.

Out of scope (noted, not changed): failures after the section returns and before
the provider call (`record_intent`, checkpoint projection). Those leave an owner
plus an admission; with agent-harness#1313 the owner is no longer promoted while
its writer runs, and after the writer exits it is promoted exactly as today.

## 2. agent-harness#1313: liveness before promotion

`AdapterStartOwnership` has no pid or lease, and adding fields is ruled out:
older runtimes build it with `AdapterStartOwnership(**json)` and would crash on an
unknown key (the ah#789 mixed-version requirement).

**Choice: (i) an advisory `flock` held by the live writer, on the owner file's own
inode.** No new file and no schema change.

- Writer: inside the section, immediately after the owner write and still under
  `admissions.lock`, open `adapter-start-owner.json` (`O_RDWR|O_NOFOLLOW|O_CLOEXEC`)
  and take `LOCK_EX|LOCK_NB`. The descriptor is returned to `_fresh_publish`,
  which closes it in a `finally` around everything up to the terminal. It is
  also closed on the #1314 restore path. A refused acquisition means another
  holder of a just-written inode, which cannot happen under the lock; it refuses
  typed and retryable after restoring.
- Probe: `_block_unsealed_owner` already decides under `admissions.lock`. After it
  finds the owner unsealed and the evidence holds no known terminal, and BEFORE it
  appends `PROVIDER_CALL_IN_FLIGHT` / `OUTCOME_AMBIGUOUS_BLOCKED`, it opens the owner
  path afresh (`O_RDONLY|O_NOFOLLOW`) and tries `LOCK_SH|LOCK_NB`. Refused → the
  writer is alive: raise `AdapterStartOwnerLive` (a `PermissionError`, message says
  retry) and write nothing. Granted → release it immediately and promote as today.
  An owner already `OUTCOME_AMBIGUOUS_BLOCKED` returns true without probing.

Why the owner inode and not a dedicated lock file: the namespace tree is walked by
cutover and rotation inventories (`_tree_file_inventory`,
`_validate_historical_evidence_root` allowlists names), so a new file in the store
root is a cross-version compatibility surface. A lock on the existing file changes
no bytes. Writes are `os.replace`, so a seal makes a new inode, and our held
descriptor on the old inode is harmless. The probe and the seal both run under
`admissions.lock`, so a prober that reads "unsealed" sees the writer's inode.

Safety argument. The probe only ever chooses between "refuse retryable, write
nothing" and today's behaviour:
- False dead (a writer that holds no lock: an older runtime, a crash between the
  write and the lock, a filesystem without lock support) → today's promotion. No
  regression.
- False alive (a stale holder) → retryable refusal until the holder exits. That is
  an availability cost, never a second provider effect.
- Process death releases a `flock`, so a crashed writer reads dead. In-process
  "crashes" (`PublishCrashInjected`, an adapter exception, an ambiguous terminal)
  all unwind through the `finally`, so the existing crash and 1296 shapes are
  unchanged.
- In-process concurrency (two `BrokerService` instances in one process): `flock`
  belongs to the open file description, and the probe opens a new one, so a live
  writer on another thread reads alive. This is the property `_require_lock_held`
  already relies on.
- Cross-host: the store already depends on `flock` coherence for `admissions.lock`;
  the probe adds no new assumption. On Linux NFS `flock` is emulated with POSIX
  locks, which are per process, so an in-process probe there can read false dead
  (today's behaviour), and a crashed client's lock lasts until its lease expires
  (false alive, retryable).
- Mixed version: an older reader ignores the lock and promotes as today; an older
  writer never locks and is promoted as today.
- `fork()` without `exec` would inherit the descriptor; Python descriptors are
  non-inheritable across `exec` (PEP 446), and the adapter launches subprocesses.

## 3. Tests: `phase-loop-runtime/tests/test_fabpub_owner_section_1314_1313_1311.py`

Reuses the 789-compat `_routed` fixture where possible (`pytestmark` skip on
`fabpub_capability_active()` like the 1296 file).

- agent-harness#1311: wrap `service._validated_envelope`; on its second call (the
  in-section one) durably project the transaction to `ADMISSION_DURABLE`, then
  delegate. Assert a `PermissionError` naming the precondition, no owner on disk,
  admissions and evidence bytes unchanged, no provider call. Mutation: drop the
  `state != "COMMITTED_HEAD_RESOLVED"` refusal → the test fails.
- agent-harness#1314, parametrized over refusals after the owner write: policy
  denied on the fresh request, `epoch_blocked`, `_require_generation` failing, and
  a `make_request` `ValueError`. Each asserts the original exception, owner bytes
  identical to before (absent, or the prior sealed owner byte-for-byte), no
  admission, no evidence, and a later clean publish succeeds. Plus: a
  `PublishCrashInjected` from `admit_next` leaves the owner (no cleanup).
  Mutation: remove the restore → fails.
- agent-harness#1313: an unsealed owner whose inode is locked by a held descriptor
  → `AdapterStartOwnerLive`, no evidence appended, owner still unsealed; release the
  lock → the same call promotes to `outcome_ambiguous_blocked` as today. A writer
  thread parked mid-attempt (between section and provider) and a second service
  instance → refusal; after release the first attempt completes and seals. A
  subprocess that writes and locks an owner, then is killed → dead → promoted.
  Mutation: remove the probe → fails.

## 4. Docs and verification

- `docs/fabpub-pre-admission-ambiguity.md`: a short section on the section's
  restore-on-refusal and on the liveness probe and its refusal text.
- `CHANGELOG.md` entry.
- `tests/data/seat_launch_references.json`: update only the rows
  `tests/test_seat_reference_inventory.py` names for new host-I/O references.

From `phase-loop-runtime/`:

```
PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider \
  tests/test_fabpub_owner_section_1314_1313_1311.py \
  tests/test_fabpub_sealed_head_recovery_1296.py \
  tests/test_fabpub_*.py tests/test_convergence_broker_*.py \
  tests/test_seat_reference_inventory.py
```

Each new check is mutation-checked (removed temporarily, the targeted test must fail).
