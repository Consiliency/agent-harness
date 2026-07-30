---
phase_loop_plan_version: 1
phase: FABPUB
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 7f2590bdebf5a892cf0987b67916d2c3b95970b547117b8cbf4adc7c7220838e
automation:
  suite_command:
    - env
    - PYTHONPATH=phase-loop-runtime/src
    - python3
    - -m
    - pytest
    - phase-loop-runtime/tests
    - -q
    - -k
    - fabpub_ or test_convergence_broker_admission or test_convergence_broker_verbs or test_convergence_broker_revocation_race or test_convergence_broker_credsep or test_convergence_live_enable or test_convergence_fencing or test_publishing or test_train_prebuilt or test_convergence_train_integration
---

# FABPUB: Shared Epoch Allocator — Publish Identity

## Context

FABPUB migrates the live `publish_committed_branch` path from caller-stamped `lease_epoch=1` to the broker's single per-repository monotonic allocator. The phase is an independent v10 root and produces `IF-0-FABPUB-1`; FABREADMIT and RESIDUAL remain downstream and must not execute beside this phase because they share publish-identity surfaces.

The roadmap fixes four boundaries. First, `LinearizableAdmissionStore.admit_next` allocates under the existing advisory lock and enforces both values supplied to `make_request(epoch, attempt_id)`. Second, completed-effect identity remains the roadmap-frozen, base-free `publish_committed_branch_idempotency_key(repo, branch, head_sha)`; the `base` question carried by `EC-RESIDUAL-1` is not reopened. Third, approval identity is derived from the transaction's resolved post-commit head and the merge base against its frozen full `base_tip_sha`, never from moving live `HEAD` or a raw base ref after preparation. Fourth, existing direct `BrokerService.execute(BrokerRequest(..., AdmissionRequest, ...))` callers remain a coherent finalized-admission compatibility path; only a publish request carrying the new epoch-free envelope invokes `admit_next`.

The live crash hole is also part of this phase. A normal `publish_from_worktree` call currently commits and then enters the broker, but a crash in that gap leaves a clean worktree; the next normal call exits at `nothing_staged` and never reaches `BrokerService.execute`. A checkpoint written only after commit leaves the same unrecoverable kill before that write. FABPUB therefore adds a versioned, metadata-only `PublishTransaction` under the coordinator-owned root and persists its `PREPARED` intent before `git commit`. The intent binds the canonical repo/worktree identity, branch and base name, frozen full `base_tip_sha`, normal/prebuilt mode, pre-commit parent SHA, staged tree SHA, ordered owned paths and staged-diff digest, deterministic commit-message digest and `FABPUB-Intent-ID` trailer, draft/body identity, and envelope authority pre-images/digest. Its deterministic transaction ID is stable before commit. After a normal commit, recovery accepts only a current `HEAD` commit whose full parent SHA, tree SHA, and trailer all match that intent; it can therefore rediscover the exact committed head after a kill before any post-commit checkpoint write, skip staging/commit, and reject descendants, rewritten heads, or caller mismatches. Prebuilt publication uses the same transaction shape with its already-committed full head/tree identity.

The allowed durable state progression is `PREPARED -> COMMITTED_HEAD_RESOLVED -> ADMISSION_DURABLE -> BROKER_INTENT_DURABLE -> ADAPTER_STARTED -> TERMINAL_SEALED`. Every local transition is serialized by the transaction lock and persisted by temp-file write, file fsync, atomic replace, and parent-directory fsync; Git ref update, the admission append, and broker evidence appends remain their authoritative atomic records. Recovery may advance a lagging transaction projection only after exact-identity reconciliation proves the corresponding Git commit, admission record, or broker evidence already exists. The adapter-start marker is durable before the adapter effect: a crash at the preserved broker-intent arm occurs before that marker and may retry, while an `ADAPTER_STARTED` record without terminal evidence is fail-closed as outcome-ambiguous and never re-invokes the adapter. `ABANDONED` and `CONFLICTED` are terminal non-authorizing tombstones. An active mismatch is never overwritten; cleanup can archive a terminal/tombstoned transaction and clear its active pointer only under the same lock and only after the tombstone is durable. A new different-head publish then creates a fresh fully validated intent. Exact terminal records remain replayable so a whole-path retry reaches broker terminal replay instead of `nothing_staged`.

Canonical runner state is `.phase-loop/`. Legacy `.codex/phase-loop/` compatibility files have no planning authority. The tracked roadmap bytes match the frontmatter digest.

## Interface Freeze Gates

- [ ] IF-0-FABPUB-1 — `LinearizableAdmissionStore.admit_next(make_request, *, attempt_id, precondition) -> AdmissionRecord` holds `admissions.lock` while it checks `epoch_blocked`, policy, prior records, and the in-lock precondition. On an `attempt_id` hit it rebuilds with `make_request(prior.epoch, attempt_id)`, requires `rebuilt.lease_epoch == prior.epoch` and `rebuilt.attempt_id == attempt_id`, rejects any other authority-field mismatch, and returns the original record. On a miss it allocates `(max(record.epoch) if records else 0) + 1`, calls `make_request(epoch, attempt_id)`, requires `request.lease_epoch == epoch` and `request.attempt_id == attempt_id`, and appends plus fsyncs one record. `publish_from_worktree` creates a deterministic coordinator-owned `PublishTransaction` in `PREPARED` before a normal commit, binding immutable repo/branch/base-tip/parent/tree/owned-diff/commit-trailer/mode/presentation/authority identities. A restart resolves `COMMITTED_HEAD_RESOLVED` only when current `HEAD` has the intent's exact parent, tree, and `FABPUB-Intent-ID` trailer; it never re-commits that head and never uses a moving ref. `BrokerService.execute` preserves terminal evidence replay before authorization and has two explicit paths: a finalized `AdmissionRequest` retains legacy `admit()` semantics for all existing callers/fakes, while an epoch-free `PreAdmissionEnvelope` is legal only for `PUBLISH_COMMITTED_BRANCH`, derives `attempt_id = sha256("publish\\0" + repo + "\\0" + branch + "\\0" + transaction.committed_head_sha)`, derives approval `base_sha = merge-base(transaction.committed_head_sha, transaction.base_tip_sha)` from full frozen SHAs, rebuilds the lease/fence/idempotency fields at the allocated epoch, and passes only the finalized request to the adapter. The transaction reconciles and durably projects `ADMISSION_DURABLE`, `BROKER_INTENT_DURABLE`, `ADAPTER_STARTED`, and `TERMINAL_SEALED` from the authoritative admission/evidence records; only the pre-`ADAPTER_STARTED` broker-intent state may retry adapter execution. Active mismatch, stale/ref-moved state, or an abandoned/conflicted tombstone fails closed before admission, and cleanup cannot turn it into publish authority. Terminal replay retains the separate base-free `publish_committed_branch_idempotency_key(repo, branch, head_sha)`.

## Lane Index & Dependencies

SL-0 — Governed tests-only contract and chronology reducer
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Shared allocator and enforced equalities
  Depends on: SL-0
  Blocks: SL-2, SL-4
  Parallel-safe: no

SL-2 — Broker dual path and recoverable publish transaction
  Depends on: SL-0, SL-1
  Blocks: SL-3, SL-4
  Parallel-safe: no

SL-3 — Live train authority handoff and authentic resume
  Depends on: SL-0, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — Documentation, chronology, and whole-phase verification reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Governed tests-only contract and chronology reducer

- **Scope**: Land the complete FABPUB falsifier set and its executable Git-chronology reducer as one literal tests-and-verification-only change before the implementation branch base is created.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/fabpub_tdd_chronology.py`, `phase-loop-runtime/tests/test_fabpub_shared_epoch.py`, `phase-loop-runtime/tests/test_convergence_broker_admission.py`, `phase-loop-runtime/tests/test_convergence_broker_verbs.py`, `phase-loop-runtime/tests/test_convergence_broker_revocation_race.py`, `phase-loop-runtime/tests/test_convergence_broker_credsep.py`, `phase-loop-runtime/tests/test_convergence_live_enable.py`, `phase-loop-runtime/tests/test_convergence_fencing.py`, `phase-loop-runtime/tests/test_publishing.py`, `phase-loop-runtime/tests/test_train_prebuilt.py`, `phase-loop-runtime/tests/test_convergence_train_integration.py`
- **Interfaces provided**: `FABPUB immutable test digest`, `FABPUB stage selectors`, `fabpub_tdd_chronology executable`, `finalized-admission compatibility matrix`
- **Interfaces consumed**: `plan-frozen FABPUB contract` (pre-existing), `AdmissionRequest` (pre-existing), `BrokerRequest` (pre-existing), `LinearizableAdmissionStore` (pre-existing), `BrokerService` (pre-existing), `publish_from_worktree` (pre-existing), `_default_build_admission` (pre-existing)
- **Parallel-safe**: no; the exact test digest must clear the governed four-seat panel and land as one tests-only commit before any production writer starts.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `FABPUB-0-T1` | `test` | (none) | SL-0 owned set | all FABPUB falsifiers | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_"` is expected RED before implementation |
| `FABPUB-0-T2` | `test` | `FABPUB-0-T1` | the three compatibility suites | finalized `AdmissionRequest` controls | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests/test_convergence_broker_revocation_race.py phase-loop-runtime/tests/test_convergence_broker_credsep.py phase-loop-runtime/tests/test_convergence_live_enable.py -q` remains GREEN before implementation |
| `FABPUB-0-T3` | `impl` | `FABPUB-0-T1`, `FABPUB-0-T2` | SL-0 owned set only | none beyond SL-0 | Commit only tests and the verification-only `phase_loop_runtime.fabpub_tdd_chronology` module; no other `src/` or `CHANGELOG.md` path is legal |
| `FABPUB-0-T4` | `verify` | `FABPUB-0-T3` | Git topology | chronology reducer self-check | `env PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.fabpub_tdd_chronology --repo . --head HEAD --expect-tests-only-head` |

- **Tasks**:
  - test: Add independently runnable `test_fabpub_allocator_*`, `test_fabpub_broker_*`, `test_fabpub_intent_*`, `test_fabpub_checkpoint_*`, `test_fabpub_transaction_*`, `test_fabpub_train_handoff_*`, `test_fabpub_train_resume_*`, and `test_fabpub_changelog_*` cases. Delay imports/feature probes so missing new symbols fail the intended case instead of aborting collection, assert every mutation's live source anchor before applying it, retain GREEN reachability controls, and record each expected RED command/output digest.
  - test: Add normal and prebuilt whole-path crash tests that enter `run_train`/`publish_from_worktree`. The mandatory normal sequence durably creates `PREPARED`, lets the real `git commit` return success, kills at `after_git_commit_success_before_committed_checkpoint`, asserts the worktree is clean and only the pre-commit intent exists, and restarts. Recovery must match the commit's exact parent/tree/trailer, persist `COMMITTED_HEAD_RESOLVED`, skip staging and commit, and enter the real `BrokerService.execute`. Continue that sequence through the preserved `after_broker_intent_before_adapter_started` kill, then restart again: `admit_next` must dedup the one admission for the recovered head, the adapter must execute exactly once total, and broker plus transaction terminal evidence must seal. Keep separate `after_committed_checkpoint_before_broker_execute` and post-terminal replay arms. Add faithful-envelope, different-authority conflict, stale/rewritten/descendant head, different-head, abandoned cleanup, and prebuilt controls; a synthetic direct call to `BrokerService.execute` alone does not satisfy these tests.
  - test: Extend the three named compatibility files so finalized `AdmissionRequest` requests prove `.admit()` remains the selected path, revocation still serializes under the shared lock, `_AdmitAll`-style fakes remain valid, envelope publication selects `.admit_next()`, and no compatibility test silently switches paths.
  - test: Add the importable `phase_loop_runtime.fabpub_tdd_chronology` module entry point. In tests-only mode it treats `HEAD` as the candidate tests-only commit, resolves its first parent as the comparison base, requires the changed paths to be a non-empty subset of the exact SL-0 set, and rejects every production/doc path other than its own verification-only module. In final mode it resolves the already-landed tests-only commit and implementation base from runner-stamped SHA metadata, with fail-closed overrides from the named `FABPUB_TESTS_ONLY_COMMIT_SHA` and `FABPUB_IMPLEMENTATION_BASE_SHA` environment variables; it accepts no raw base ref on argv. It locates the first production-changing commit, proves the tests-only commit is already ancestral to the implementation base and that commit's first parent, proves the tests-only commit changed no non-SL-0 path, and compares every SL-0 blob from the tests-only commit to implementation `HEAD` byte-for-byte. It prints a deterministic JSON record with resolved SHAs, paths, and aggregate test-tree digest for runner evidence.
  - impl: Land only the tests/reducer after the exact digest is reviewed by Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5. The implementation branch must be based on this landed commit; later test edits are forbidden.
  - verify: `env PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.fabpub_tdd_chronology --repo . --head HEAD --expect-tests-only-head`

### SL-1 — Shared allocator and enforced equalities

- **Scope**: Add the one in-lock allocator and make its epoch, attempt, policy, revocation, precondition, dedup, and conflict guarantees fail closed.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py`
- **Interfaces provided**: `LinearizableAdmissionStore.admit_next`, `make_request(epoch, attempt_id) contract`, `attempt_id authority comparison`
- **Interfaces consumed**: `FABPUB immutable test digest`, `FABPUB stage selectors`, `AdmissionRequest` (pre-existing), `AdmissionRecord` (pre-existing), `BrokerAdmissionPolicy` (pre-existing)
- **Parallel-safe**: no; this is the sole allocator writer and its implementation base must already contain SL-0.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `FABPUB-1-T1` | `test` | (none) | `admission.py` behavior only | immutable SL-0 allocator selector | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_allocator"` is RED immediately before the edit |
| `FABPUB-1-T2` | `impl` | `FABPUB-1-T1` | `admission.py` | none | Implement `admit_next` without changing `admit` |
| `FABPUB-1-T3` | `verify` | `FABPUB-1-T2` | `admission.py` behavior only | immutable SL-0 allocator selector | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_allocator"` is GREEN |

- **Tasks**:
  - test: Run only `fabpub_allocator` cases before and after the edit; later broker, train, and CHANGELOG tests are deliberately not selected in this lane.
  - impl: Implement `admit_next(make_request, *, attempt_id, precondition)` under the existing flock; preserve fail-closed `policy is None`, policy denial, and `epoch_blocked` checks on fresh and dedup paths; rebuild and compare a dedup hit; allocate only after the in-lock precondition; enforce both equalities; retain append-only fsync persistence and the legacy `admit()` surface.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_allocator"`

### SL-2 — Broker dual path and recoverable publish transaction

- **Scope**: Freeze the finalized/envelope dual path, allocate only envelope publishes, and close the commit/checkpoint crash hole with a coordinator-owned transaction whose durable intent precedes commit.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`, `phase-loop-runtime/src/phase_loop_runtime/publishing.py`
- **Interfaces provided**: `PreAdmissionEnvelope`, `PublishIntent`, `PublishCheckpoint`, `PublishTransactionState`, `PublishTransactionStore`, `publish_attempt_id(repo, branch, head_sha)`, `finalized AdmissionRequest compatibility path`, `publish_from_worktree transaction recovery route`, `base-free publish_committed_branch_idempotency_key(repo, branch, head_sha)`
- **Interfaces consumed**: `FABPUB immutable test digest`, `FABPUB stage selectors`, `LinearizableAdmissionStore.admit_next`, `make_request(epoch, attempt_id) contract`, `FencedAdmissionFactory` (pre-existing), `BrokerEvidenceStore` (pre-existing), `BrokerProviderAdapter` (pre-existing)
- **Parallel-safe**: no; the request union, service dispatch, transaction validation, and publish resume route move together after SL-1.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `FABPUB-2-T1` | `test` | (none) | SL-2 behavior only | immutable broker/intent/checkpoint/transaction/dual-path selectors | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_broker or fabpub_intent or fabpub_checkpoint or fabpub_transaction or fabpub_dual_path"` is RED immediately before the edit |
| `FABPUB-2-T2` | `impl` | `FABPUB-2-T1` | SL-2 owned production files | none | Implement the request union, service branch, and recoverable transaction state machine |
| `FABPUB-2-T3` | `verify` | `FABPUB-2-T2` | SL-2 plus finalized compatibility callers | immutable SL-0 files only | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "(fabpub_ or test_convergence_broker_verbs or test_convergence_broker_revocation_race or test_convergence_broker_credsep or test_convergence_live_enable or test_publishing) and not fabpub_train_handoff and not fabpub_train_resume and not fabpub_changelog"` is GREEN |

- **Tasks**:
  - test: Run the SL-2 RED selector first, then the GREEN command that includes all direct `BrokerService.execute` callers/fakes in `test_convergence_broker_revocation_race.py`, `test_convergence_broker_credsep.py`, and `test_convergence_live_enable.py`. Do not run the SL-3 authentic train-resume or SL-4 CHANGELOG selectors here.
  - impl: Add an epoch-free `PreAdmissionEnvelope` carrying train/node/action identity, roadmap/effective-code/dependency/verification pre-images, expected-version predicate, authority scope, and deterministic operation identity, but no epoch, attempt ID, fence token, approval digest, or fencing idempotency key. Permit it only on `PUBLISH_COMMITTED_BRANCH`.
  - impl: In `BrokerService.execute`, compute terminal publish replay from the base-free completed-effect key before either admission path. A finalized `AdmissionRequest` continues through `admit()` byte-for-byte in behavior. An envelope publish consumes only `COMMITTED_HEAD_RESOLVED` transaction identity, resolves approval from `merge-base(committed_head_sha, base_tip_sha)`, builds commit-stable approval, calls `admit_next`, replaces the envelope with the stored finalized request, and only then records broker intent/calls the adapter. Every non-publish envelope fails before admission. An unresolved full SHA or identity mismatch blocks; current `HEAD` and moving `origin/<base>` are never substitutes after `PREPARED`.
  - impl: Keep `publish_committed_branch_idempotency_key(repo, branch, head_sha)` byte-for-byte base-free and epoch-free as required by `EC-FABPUB-4`; do not fold `base`, `attempt_id`, `lease_epoch`, or randomness into the completed-effect key.
  - impl: Add versioned metadata-only `PublishIntent`/`PublishCheckpoint` payloads and a `PublishTransactionStore` under an explicit coordinator-owned `checkpoint_root`, never under the published repo. For normal mode, stage and audit first; resolve full `parent_head_sha` and `base_tip_sha`; compute `staged_tree_sha`, staged-diff digest, deterministic commit bytes containing one `FABPUB-Intent-ID` trailer, presentation digests, and the envelope authority digest; derive the transaction ID from those immutable fields; and persist `PREPARED` before invoking `git commit`. Prebuilt mode persists an equivalent intent with its full committed head/tree before broker entry. Serialization, lock ownership, compare-and-transition, temp write, file fsync, atomic replace, and parent fsync are part of the frozen contract.
  - impl: Resolve `PREPARED` before any new staging. A normal intent becomes `COMMITTED_HEAD_RESOLVED` only when current branch `HEAD` is the unique commit with exactly the recorded parent SHA, tree SHA, and transaction trailer; store that full head and derive `attempt_id` from it. If `HEAD == parent_head_sha` and the audited staged tree still matches, a pre-commit crash may continue the one commit; if the matching commit already exists, never commit again. A descendant, rewrite, missing/multiple marker, repo/branch/base-tip/mode/path/digest/authority mismatch, or clean `HEAD == parent_head_sha` is a typed conflict/stale intent before admission and cannot fall through to `nothing_staged` or start a new transaction.
  - impl: Enforce only `PREPARED -> COMMITTED_HEAD_RESOLVED -> ADMISSION_DURABLE -> BROKER_INTENT_DURABLE -> ADAPTER_STARTED -> TERMINAL_SEALED`, plus terminal `ABANDONED`/`CONFLICTED`. After each authoritative Git/admission/evidence fsync, atomically project the matching transaction state and identity digest. Recovery of a projection lag replays the authoritative stores and advances only on exact matches. Persist `ADAPTER_STARTED` immediately before the adapter call; `BROKER_INTENT_DURABLE` without that marker may resume, while `ADAPTER_STARTED` without terminal evidence records/refuses as outcome-ambiguous and never invokes the adapter again. Seal terminal broker state/evidence reference into `TERMINAL_SEALED` only after broker terminal evidence is durable.
  - impl: Preserve the existing finalized-admission API for non-train callers. An envelope requires `checkpoint_root`; absence fails closed. Exact active input resumes; active mismatches never overwrite the record. Cleanup first writes and fsyncs an `ABANDONED` or `CONFLICTED` tombstone, then archives/clears the active pointer under the same lock; those states never authorize admission or effect. Only a terminal/tombstoned prior transaction may be superseded by a freshly validated different-head intent. Retain sealed transaction/evidence identity for exact terminal replay.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "(fabpub_ or test_convergence_broker_verbs or test_convergence_broker_revocation_race or test_convergence_broker_credsep or test_convergence_live_enable or test_publishing) and not fabpub_train_handoff and not fabpub_train_resume and not fabpub_changelog"`

### SL-3 — Live train authority handoff and authentic resume

- **Scope**: Make normal and prebuilt train publication supply epoch-free authority and the transaction root, then prove the live route recovers an exact commit from pre-commit intent and resumes through the idempotent broker path.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- **Interfaces provided**: `_default_build_admission -> PreAdmissionEnvelope`, `CoordinatorRuntime.coordinator_root -> publish transaction root`, `commit-stable approval pre-images`, `authentic normal/prebuilt crash resume`
- **Interfaces consumed**: `FABPUB immutable test digest`, `FABPUB stage selectors`, `PreAdmissionEnvelope`, `PublishIntent`, `PublishCheckpoint`, `PublishTransactionState`, `publish_from_worktree transaction recovery route`, `publish_attempt_id(repo, branch, head_sha)`, `FencedAdmissionFactory` (pre-existing), `ApprovalBinding` (pre-existing)
- **Parallel-safe**: no; `train_runner.py` is phase-single-writer and this lane consumes the complete SL-2 transaction contract.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `FABPUB-3-T1` | `test` | (none) | live normal/prebuilt train routes | immutable train handoff/resume selectors | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_train_handoff or fabpub_train_resume"` is RED immediately before the edit |
| `FABPUB-3-T2` | `impl` | `FABPUB-3-T1` | SL-3 owned production files | none | Return the envelope and pass the coordinator-owned transaction root on both routes |
| `FABPUB-3-T3` | `verify` | `FABPUB-3-T2` | live normal/prebuilt train routes | immutable SL-0 files only | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "(fabpub_ or test_convergence_fencing or test_train_prebuilt or test_convergence_train_integration) and not fabpub_changelog"` is GREEN |

- **Tasks**:
  - test: Run the authentic selectors that start above `BrokerService`. In `fabpub_train_resume_post_commit_pre_checkpoint`, normal work must persist `PREPARED`, commit successfully, and die at the faithful `after_git_commit_success_before_committed_checkpoint` injection; assert the retry begins from a clean worktree with the committed `HEAD` and no post-commit checkpoint. Restart must recover that exact commit from parent/tree/trailer identity without staging or committing, persist `COMMITTED_HEAD_RESOLVED`, and reach the real `BrokerService.execute`. Preserve independent `after_committed_checkpoint_before_broker_execute` coverage. In the compound arm, kill again at `after_broker_intent_before_adapter_started`; the final restart must reconcile/dedup one admission, execute the adapter exactly once total, write terminal broker evidence, seal `TERMINAL_SEALED`, and reach `pr_open`. Repeat the applicable sequence for a prebuilt head, then exercise faithful retry, mismatched authority, stale/rewritten/descendant intent, safe abandonment/cleanup, different-head allocation, `ADAPTER_STARTED` ambiguity refusal, and replay after terminal evidence. Assert every crash anchor, transition, clean-worktree condition, broker entry, admission/effect count, and evidence record.
  - impl: Refactor `_default_build_admission` to return `PreAdmissionEnvelope`; preserve surrogate-escaped owned-path digest behavior and all roadmap/dependency/verification/authority inputs, but remove the literal epoch-1 lease and every pre-commit `HEAD`, attempt, fence, approval, or fencing-key binding.
  - impl: Pass a deterministic node-scoped transaction root beneath `CoordinatorRuntime.coordinator_root` to `publish_from_worktree` for both normal and prebuilt routes. Capture the immutable envelope and presentation pre-images before `PREPARED`; resume-time authority comes from the exact transaction, not a fresh clean-worktree diff. Do not create a second train-ledger status or treat a blocked ledger append as transaction state. The durable pre-commit intent plus exact Git reconciliation is the only route that repairs the commit-to-checkpoint gap.
  - impl: Keep the fencing digest formulas unchanged: when SL-2's `make_request` invokes the factory, pass its deterministic `attempt_id` to `lease`, its allocated epoch as `lease_epoch`, and its post-commit approval binding to `create`. Do not change the FAB review-round `epoch` namespace.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "(fabpub_ or test_convergence_fencing or test_train_prebuilt or test_convergence_train_integration) and not fabpub_changelog"`

### SL-4 — Documentation, chronology, and whole-phase verification reducer

- **Scope**: Retract publish byte-neutrality, prove the tests-only ancestry/immutability record, and reduce all producer evidence without widening into FABREADMIT or RESIDUAL. Post-dispatch applicability is none: FABPUB cuts no tag and runs no external release workflow, so there is no commit/workflow back-fill.
- **Owned files**: `CHANGELOG.md`
- **Interfaces provided**: `IF-0-FABPUB-1`, `FABPUB verification evidence`, `publish byte-neutrality retraction`
- **Interfaces consumed**: `FABPUB immutable test digest`, `fabpub_tdd_chronology executable`, `LinearizableAdmissionStore.admit_next`, `PreAdmissionEnvelope`, `PublishIntent`, `PublishCheckpoint`, `PublishTransactionState`, `publish_from_worktree transaction recovery route`, `_default_build_admission -> PreAdmissionEnvelope`
- **Parallel-safe**: no; this terminal documentation/verification reducer runs after every producer and is excluded from writer waves.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `FABPUB-4-T1` | `test` | (none) | `CHANGELOG.md` observable | immutable CHANGELOG selector | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_changelog"` is RED before the doc edit |
| `FABPUB-4-T2` | `impl` | `FABPUB-4-T1` | `CHANGELOG.md` | none | Add the explicit byte-neutrality retraction |
| `FABPUB-4-T3` | `verify` | `FABPUB-4-T2` | complete FABPUB focused surface | immutable SL-0 suite | Run the frontmatter `automation.suite_command`; this is the first whole-phase focused suite and must be GREEN |
| `FABPUB-4-T4` | `verify` | `FABPUB-4-T3` | Git topology and SL-0 blobs | executable chronology evidence | `env PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.fabpub_tdd_chronology --repo . --head HEAD` |
| `FABPUB-4-T5` | `verify` | `FABPUB-4-T4` | whole phase | final regression evidence | Run every command under `## Verification` and emit `IF-0-FABPUB-1` only when all pass |

- **Tasks**:
  - test: Run only `fabpub_changelog` before the edit and retain its expected RED evidence; do not run the knowingly incomplete whole-phase suite before `CHANGELOG.md` is repaired.
  - impl: Add one explicit CHANGELOG entry retracting publish byte-neutrality because publish admission epochs and derived fence records are intentionally renumbered. Do not claim FABREADMIT, its dormant flag flip, or RESIDUAL's unresolved `base` identity carry as delivered.
  - verify: `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_ or test_convergence_broker_admission or test_convergence_broker_verbs or test_convergence_broker_revocation_race or test_convergence_broker_credsep or test_convergence_live_enable or test_convergence_fencing or test_publishing or test_train_prebuilt or test_convergence_train_integration"`

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- SL-4: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, reason=`cross-lane documentation chronology and acceptance synthesis`

## Execution Notes

- Before SL-0, review the exact plan digest with the roadmap-required Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5 board. Fable and Sol are mandatory reviewing seats; any unavailable, errored, empty, capped, refused, or timed-out mandatory leg blocks dispatch. Resolve material findings and re-panel every changed digest.
- The coordinator selects one implementation author vendor for the whole phase and records the explicit executor/model/effort. Do not combine cross-vendor work-unit rotation with lane scheduling.
- SL-0 is a hard Git boundary. Its commit is literally tests-and-verification-only: every changed path is in SL-0's owned set, the sole `src/` path is the non-production chronology entry point, the new falsifiers were observed RED against the pre-implementation base, and the implementation branch first parent already contains that commit before any production `src/` change. SL-1 through SL-4 may execute but never edit an SL-0 path. A needed test repair returns to SL-0, re-panels/re-runs RED, and establishes a new tests-only boundary before implementation resumes.
- `phase_loop_runtime.fabpub_tdd_chronology` is the executable acceptance reducer, not prose evidence. Its final JSON and exit status bind runner-stamped or named-environment SHA metadata, prove the tests-only commit precedes the first production commit on the implementation first-parent base, and prove that every SL-0 blob remains byte-identical at implementation head. Runner timestamps, commit-message claims, a plain `git log` listing, and a moving raw ref are not substitutes.
- The three previously omitted suites are phase-owned by SL-0 and frozen after their tests-only commit. The compatibility contract they enforce is intentional: finalized `AdmissionRequest` requests continue to call `admit()`; only live envelope publishes call `admit_next()`. This keeps revocation-race locking, credential-separation service fakes, live builders, routing clients, non-publish refusal, and terminal replay covered without converting them to unowned failures.
- The transaction state machine has one authority per boundary: the transaction file for prepared input/projection, the Git commit object and branch ref for committed-head resolution, `admissions.jsonl` for allocation/dedup, and broker `evidence.jsonl` for effect intent/terminal outcome. A projection lag is recoverable; an identity disagreement is not. No state transition may infer success from chronology prose, train-ledger status, a clean worktree, a moving ref, or the transaction projection alone.
- `after_git_commit_success_before_committed_checkpoint`, `after_committed_checkpoint_before_broker_execute`, and `after_broker_intent_before_adapter_started` are distinct faithful injection anchors. SL-0 freezes all three before production changes. The first is blocking acceptance coverage for the exact panel dissent; the latter two preserve the already-approved crash surfaces.
- The roadmap asks publish-path and approval work to partition `train_runner.py` by function, but executor ownership is file-granular. SL-3 alone owns `train_runner.py`; SL-2 owns the envelope/checkpoint/broker contract, and SL-3 consumes it serially. No path or glob overlaps.
- The phase-owned write set is exactly the union of SL-0 through SL-4. There are no dependency, lockfile, migration, generated package artifact, snapshot, environment-example, package-export, external-dispatch, or plan-manifest deltas. Any other dirty path is `phase_owned_dirty` and blocks closeout.
- `refresh_downstream_after_merge` is not a live FABPUB S1/S3/S3b seam and remains outside this phase. FABREADMIT owns the readmit consumer and `_FAB_DELTA_BROKER_READMIT_READY` flip. RESIDUAL owns any later `base` change to completed-effect publish identity. Neither may be smuggled into this implementation.
- Documentation impact is limited to the required CHANGELOG retraction. README, release notes, fleet pins, and external repository docs have no FABPUB delta.
- Policy precedence is CLI/operator override, this phase plan, roadmap policy, `Dispatch Hints`, then registry defaults. Silent model, effort, executor, or capability downgrade is forbidden unless an explicit fallback is selected or `inherit_default` applies.
- FABPUB is not a visible avatar, browser, or media-render deliverable. Closeout records `visual_render_declared=false` and a typed non-render opt-out.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py`, `phase-loop-runtime/src/phase_loop_runtime/publishing.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/fabpub_tdd_chronology.py`, `phase-loop-runtime/tests/test_fabpub_shared_epoch.py`, `phase-loop-runtime/tests/test_convergence_broker_admission.py`, `phase-loop-runtime/tests/test_convergence_broker_verbs.py`, `phase-loop-runtime/tests/test_convergence_broker_revocation_race.py`, `phase-loop-runtime/tests/test_convergence_broker_credsep.py`, `phase-loop-runtime/tests/test_convergence_live_enable.py`, `phase-loop-runtime/tests/test_convergence_fencing.py`, `phase-loop-runtime/tests/test_publishing.py`, `phase-loop-runtime/tests/test_train_prebuilt.py`, `phase-loop-runtime/tests/test_convergence_train_integration.py`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-FABPUB.md`, `phase-loop-runtime/src/phase_loop_runtime/fabpub_tdd_chronology.py`, `phase-loop-runtime/tests/test_fabpub_shared_epoch.py`, `.phase-loop/runs/*/verification.json`, `.phase-loop/runs/*/verification.log`, `.phase-loop/events.jsonl`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-FABPUB.md`
- `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_ or test_convergence_broker_admission or test_convergence_broker_verbs or test_convergence_broker_revocation_race or test_convergence_broker_credsep or test_convergence_live_enable or test_convergence_fencing or test_publishing or test_train_prebuilt or test_convergence_train_integration"`
- `env PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.fabpub_tdd_chronology --repo . --head HEAD`
- `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "broker or admission or convergence or fab"`
- `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-FABPUB-0 — proven by `env PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.fabpub_tdd_chronology --repo . --head HEAD`, the retained independent RED outputs/injection anchors, and the exact plan/test panel digests. The reducer must report a tests-only commit already ancestral to the first production commit's first parent and zero changed SL-0 blobs through implementation head.
- [ ] EC-FABPUB-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_allocator_stale_epoch"`.
- [ ] EC-FABPUB-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_allocator_epoch_equality"`.
- [ ] EC-FABPUB-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_allocator_attempt_equality"`.
- [ ] EC-FABPUB-4 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_train_resume_post_commit_pre_checkpoint or fabpub_train_resume_normal or fabpub_train_resume_prebuilt or fabpub_terminal_replay or fabpub_different_head"`; the blocking normal arm must kill immediately after real commit success and before `COMMITTED_HEAD_RESOLVED`, restart clean from `PREPARED`, resolve the exact parent/tree/trailer-bound head without re-commit, enter the real broker, dedup to one admission across the preserved broker-intent crash, execute the adapter exactly once, and seal terminal evidence.
- [ ] EC-FABPUB-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_faithful_retry or fabpub_checkpoint_conflict or fabpub_intent_conflict or fabpub_intent_cleanup"`.
- [ ] EC-FABPUB-6 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_conflicting_resume or fabpub_genuine_resume"`.
- [ ] EC-FABPUB-7 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "fabpub_changelog"`.
