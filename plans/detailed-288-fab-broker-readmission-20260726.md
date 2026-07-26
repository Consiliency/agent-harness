# Detailed plan: FAB 3b broker re-admission of a delta-approved head (ah#288)

## Task
FAB piece 3b-consumer (Consiliency/agent-harness#191, PR #287) re-admits a delta-approved advanced PR head
by writing the new admitted head **directly to the coordinator ledger** (`_fab_delta_readmit` →
`append_record`, after an owned-scope `_covered_by_owned` re-check). That direct append **bypasses the
broker's lease / epoch / revocation authority**: a node whose broker lease was revoked mid-run could still
delta-re-admit + merge. The ratified design (`plans/design-fab-integration-milestone.md:75`, item 3.2)
requires a successful delta review to trigger a **new broker admission**.

Implement broker re-admission of a delta-approved head — a **decoupled admit** (admit an already-pushed
advanced head WITHOUT re-publishing), a **lease-epoch bump** on re-admission, and **revocation /
linearizability gating** — so the delta re-admit is subject to the same broker authority as the original
admission. Then, as a **separate gated step**, flip `_FAB_DELTA_BROKER_READMIT_READY = True` to activate the
delta-review ENGAGE path.

FAB design principle throughout: **trust ONLY harness-written durable records; verify client-supplied
artifacts field-by-field; fail closed on absence / mismatch / vacuity.** For a trust-root activation gate,
**failing OPEN on missing evidence is the worst possible outcome** — the plan makes that structurally
impossible.

## Research summary (source-verified on `feat/fab-265-merge-queue-bound` @ `9540f91`)

### The interlock and what it gates
- `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py:74` — `_FAB_DELTA_BROKER_READMIT_READY = False`.
- `governed_premerge.py:77-93` — `fab_delta_shortcut_enabled(coordinator_opt_in, env)` returns
  `_FAB_DELTA_BROKER_READMIT_READY and fab_promotion_enabled(env) and bool(coordinator_opt_in)`. The
  interlock is one of **three ANDed trusted gates**; the flip touches ONLY this predicate. Because the
  master flag `fab_promotion_enabled(env)` is already ANDed here, **flipping the interlock keeps the ENGAGE
  path byte-neutral when `PHASE_LOOP_FAB` is off** (verified: flag-off ⇒ predicate False regardless of the
  interlock).
- The predicate gates ONLY the ENGAGE (delta review + re-admit) at `train_runner.py:3058`. The torn-state
  recovery net (`_fab_recover_torn_to_admitted`, `train_runner.py:3054-3055`) is gated separately on
  `fab_run_id is not None` and is unaffected by the flip — that is the seam #299 addresses (below).

### The current direct-append re-admission (what must go through the broker)
- `train_runner.py:890-1145` — `_fab_delta_readmit(...)`. On a single-commit advance of an admitted FAB node
  with the trusted opt-in: fetch the live head (`:953`), single-commit check (`:965-970`), **broker
  owned-scope re-check** via `_paths_covered_by_owned` (`:983`, reusing `GitHubBrokerAdapter._covered_by_owned`,
  `train_runner.py:736-752`), review the committed delta, build+finalize the delta round, overwrite
  provenance, verify the merged gate PASSes (`:1117`), then the **COMMIT POINT** at `:1137-1144`: a **direct**
  `append_record` of the new `LedgerRecord` (new `head_sha`, same `fab_run_id`), `durable=True`.
- `train_runner.py:1125-1136` — the KNOWN-LIMITATION comment documenting the deferred broker gap (must be
  removed by change (4), issue Scope).
- The delta round's epoch is already computed deterministically from the **durable provenance chain**:
  `next_epoch = max([FAB_CANDIDATE_EPOCH, *(d.epoch for d in artifact.delta_chain)]) + 1`
  (`train_runner.py:1035` / `:1039`). `FAB_CANDIDATE_EPOCH = 1` (`fab_gate.py:505`), so the first delta round
  is epoch **2**, strictly greater than the original publish's `lease_epoch=1` — this is the natural,
  deterministic, monotonic **lease-epoch bump** the re-admission needs, sourced from a harness-written
  durable record (not a parallel epoch invented at attempt time).

### The engage/consume site (where the broker authority must be threaded)
- `train_runner.py:3025-3091` — the P4 merge-loop shortcut block. Gated on `_fab_run_id_shortcut is not None`
  (`:3044`), it runs the unconditional torn-recovery (`:3054-3055`) then, ONLY under
  `fab_delta_shortcut_enabled(fab_delta_shortcut)` (`:3058`), calls `_fab_delta_readmit(...)` (`:3068-3075`).
  This block is **inline inside `run_train`**, so `run_train`'s params — `coordinator_runtime`
  (`train_runner.py:2127`), `resolve_owned_paths` (`:2126`), `admission_fn` (`:2244`) — are in lexical scope
  here (confirmed: `coordinator_runtime` is a `run_train` param, referenced at `:2222/:2550/:2691`). No
  cross-function plumbing is required to reach the broker at the call site.
- `train_runner.py:2222` — `run_train` already asserts: `coordinator_runtime is not None ⟹ train_id set AND
  broker_client is not None`. So a broker-authoritative runtime always carries a live `broker_client`.
- `CoordinatorRuntime` (`train_runner.py:~88-98`) carries `train_id`, `roadmap_digest`, `workspace_id`,
  `broker_client`.

### The broker admission stack (the primitive to extend)
- `convergence/contracts.py:18-33` — `AdmissionRequest(attempt_id, lease_epoch, fence_token, approval_digest,
  expected_version_predicate, authority_domain_scope, idempotency_key)`; `__post_init__` rejects any empty
  fencing field.
- `convergence/fencing.py:53-68` — `FencedAdmissionFactory`: `.lease(train_id, node_id, action, lease_epoch,
  attempt_id=None)` (**accepts a caller-supplied `attempt_id`** — load-bearing for determinism; default is
  `uuid4().hex`), `.approval(...)`, `.create(lease, approval, expected_version_predicate,
  authority_domain_scope, latest_epoch=None)`. `create()`'s `idempotency_key = _digest((attempt_id,
  lease_epoch, fence_token, approval_digest, expected_version_predicate, authority_domain_scope))` — so a
  byte-identical request across resume attempts yields a byte-identical key.
- `convergence/broker/admission.py:23-56` — `LinearizableAdmissionStore.admit(request)` under an `fcntl`
  exclusive lock: (1) `if self.epoch_blocked() or policy is None or not policy(request): raise
  PermissionError("broker admission denied")`; (2) idempotency dedup — same key + identical request → return
  the existing `AdmissionRecord`; same key + **different** request → `raise ValueError("conflicting
  idempotency key")`; (3) `if records and request.lease_epoch < max(r.epoch for r in records): raise
  PermissionError("stale epoch")`; (4) append `AdmissionRecord(sequence=len(records)+1, epoch=lease_epoch,
  request)`, fsync. `.replay()` returns the durable tuple of records.
  - **Fail-open trap (advisor):** on an **empty** log, `epoch_blocked()` is the dormant injected callable
    (`lambda: False` — `_service_for` builds the store WITHOUT the callable), the dedup loop is skipped, and
    `if records and ...` short-circuits → the request is **appended at the bumped epoch and returned
    accepted** with NO verified prior admission. Re-admitting against an empty/misconfigured/wrong-`broker_root`
    store is exactly "activation failing OPEN on missing evidence." The contract MUST reject a readmit whose
    admission is the FIRST record in the store (no publish preceded it).
- `convergence/broker/evidence.py:28-30` — `BrokerEvidenceStore.epoch_blocked` is `any(state is
  OUTCOME_AMBIGUOUS_BLOCKED)` over the durable evidence log; an ambiguous terminal is **permanent**
  (`evidence.py:43-50`). This is the **revocation** signal.
- `convergence/broker/verbs.py:55-76` — `BrokerService.execute` checks `if self.evidence_store.epoch_blocked:
  raise PermissionError("epoch permanently blocked")` at `:64` **before** `admission_store.admit`. The
  admission store's OWN `epoch_blocked` is dormant in `_service_for` (built without the callable,
  `live.py:138-143`), so **revocation lives in the evidence store** and the decoupled-admit method MUST check
  it explicitly — the admission store alone will not enforce it.
- `convergence/broker/verbs.py:15-16` — `BrokerClient` is a structural `Protocol` (`def execute(...)`).
  Concrete impls: `BrokerService` (`verbs.py:28`) and `_RoutingBrokerService` (`live.py:96`,
  `_service_for(repo)` → per-repo `BrokerService`, `live.py:134-145`). Adding a decoupled-admit method
  requires adding it to the Protocol + both impls. Test fakes that never reach the readmit path are
  structurally unaffected (Protocol = structural typing); the readmit path itself is driven by a **callable
  seam** (below), so readmit tests inject a callable, not a full `BrokerClient`.
- `publishing.py:194-199` — the existing publish path: `broker_client.execute(BrokerRequest(
  PUBLISH_COMMITTED_BRANCH, admission, repo, branch, head_sha, owned_paths, base=..., draft=..., pr_body=...))`;
  `broker_client is None or admission is None ⇒ _blocked("broker_required")`. This is the model to mirror,
  minus the GitHub push (the advance is already pushed).

### #299 interaction (Consiliency/agent-harness#299 — flag-off byte-neutrality of the recovery block)
- #299 is a **pre-existing** flag-off leak in the recovery block (`_fab_recover_torn_to_admitted`, gated on
  `fab_run_id is not None`, NOT the flag). It is **orthogonal to the interlock flip** (the flip only touches
  the ENGAGE predicate, which already ANDs `fab_promotion_enabled`). BUT once the milestone is activated, the
  recovery-block leak ships **active**. So **#299's flag-gating is a gating predecessor of the flip**, not
  merely "related." Correct sequence: **broker mechanism (dormant) → #299 → interlock flip.** #299 is a
  separate, smaller issue and is NOT implemented by this plan; this plan only records the ordering
  dependency.

## The re-admission contract (what the broker must re-admit + verify)

A delta re-admission is admitted **iff** all hold; otherwise it FAILS CLOSED (`_fab_delta_readmit` returns
`None` → the caller falls through to the UNCHANGED, fail-closed `pr-head-advanced` guard in `_live_merge_pr`):

1. **Live broker authority present.** The shortcut is enabled AND a live `broker_client` (via a
   broker-authoritative `coordinator_runtime`) is available. Absent ⇒ fail closed. (No silent direct-append
   fallback — the direct append is REPLACED by the brokered admit, not kept as a fallback.)
2. **A verified prior admission baseline exists** for this node/repo in the durable admission log (a real
   publish preceded this readmit). Enforced by requiring the granted `AdmissionRecord.sequence ≥ 2` — the
   readmit is never the FIRST record in the store. (Single-node-per-repo store: `sequence≥2` ⇒ the publish
   admission preceded it. Multi-node-per-repo store: `sequence≥2` proves *some* prior admission; the
   implementer MAY additionally scan `store.replay()` for a record whose `authority_domain_scope` +
   `approval_digest` match this node's original publish admission — decide explicitly at build time and
   document it. The empty-log fail-open MUST be closed either way.)
3. **Deterministic, resume-idempotent request.** The `AdmissionRequest` is **byte-identical across resume
   attempts** so `admit()`'s dedup returns the existing record instead of conflicting or bumping the epoch
   unboundedly. This requires (HARD CONTRACT, not an implementation detail):
   - `attempt_id` **deterministic** — e.g. `sha256(node_id, new_head_sha, next_epoch, "fab-readmit")`; never
     the factory's `uuid4` default.
   - approval evidence sourced from **durable provenance** — `artifact.base.base_sha`, the owned-scope digest
     over `owned_paths` (same `os.fsencode` construction as `_default_build_admission`,
     `train_runner.py:127`), `roadmap_digest` from the runtime — never a live `git rev-parse HEAD`.
   - `lease_epoch = next_epoch` (the delta round epoch, ≥2, from the durable provenance chain) — the genuine,
     deterministic, monotonic bump strictly above the publish epoch 1.
   - `action = "readmit"` (a distinct verb-action string; keeps readmit leases namespaced from publish leases).
4. **Linearizable, not stale.** `admission_store.admit` (under its lock) rejects `lease_epoch < max(existing
   epoch)`. Epoch **ordering** is delegated to `admit()`'s locked stale-check — the plan does NOT add a
   strict-greater check outside the lock (that would break resume idempotency, since a resumed identical
   request must dedup, not re-compare).
5. **Not revoked.** `evidence_store.epoch_blocked` is False (no permanent `OUTCOME_AMBIGUOUS_BLOCKED`
   terminal for this node/repo). Checked **explicitly** in the decoupled-admit method (the admission store's
   own `epoch_blocked` is dormant).
6. **Durable-record verification (anti-vacuity).** After `admit`, the method re-reads the durable admission
   log and confirms a record whose `request.idempotency_key` == the readmit request's key AND whose `epoch`
   == `next_epoch` is present. A broker that returns `accepted=True` without a durable record (a stub / no-op
   / partial write) is treated as vacuous ⇒ fail closed. (Trust the harness-written durable record, not the
   returned boolean.)

Only when 1-6 hold does `_fab_delta_readmit` proceed to its existing COMMIT POINT (the ledger append). The
ledger append stays the crash-consistency commit point; the brokered admit is inserted **before** it (a crash
between admit and ledger-append fails closed exactly as today — the ledger still points at the old head, the
guard fires, resume re-runs and the deterministic admit dedups).

## Fail-closed matrix (each branch drives the production path; each has a biting mutation)

| # | Condition | Detection (production path) | Result | Biting mutation (test proves it) |
|---|-----------|-----------------------------|--------|-----------------------------------|
| M1 | **Missing broker authority** — shortcut enabled but `broker_admit_fn`/`broker_client` is `None` | `_fab_delta_readmit` guard before the commit point | return `None` | Remove the None-guard → readmit proceeds to a direct append with no broker |
| M2 | **Missing baseline** — empty admission log (readmit would be the first record) | granted `AdmissionRecord.sequence == 1` → reject | return `None` | Delete the `sequence ≥ 2` check → an empty-store readmit is accepted (the fail-OPEN the advisor flagged) |
| M3 | **Stale epoch** — `lease_epoch` not strictly above the durable max | `LinearizableAdmissionStore.admit` raises `PermissionError("stale epoch")` → caught | return `None` | Seed the admission log with a higher-epoch record; unmutated code must reject |
| M4 | **Revoked** — `evidence_store.epoch_blocked` True (permanent ambiguous terminal) | explicit `epoch_blocked` check in the decoupled-admit method → deny | return `None` | Delete the explicit `epoch_blocked` check → a seeded `OUTCOME_AMBIGUOUS_BLOCKED` record no longer denies |
| M5 | **Mismatched admission** — same idempotency key, different request (forged/altered readmit colliding with a durable record) | `admit` raises `ValueError("conflicting idempotency key")` → caught | return `None` | Seed a conflicting durable record under the same key; unmutated code must reject |
| M6 | **Vacuous admit** — broker returns `accepted=True` with NO durable record | post-admit durable re-read finds no matching `idempotency_key`+`epoch` | return `None` | Inject a stub `broker_admit_fn` returning `accepted=True` without writing; the durable-record verify must reject |

All six return `None`, never a weakening of the guard. M1/M2/M6 are the fail-OPEN-critical branches (missing /
vacuous evidence) — the ones that would activate an unverified re-admission if wrong.

## Split into bounded changes (this issue is larger than one bounded change)

Recommend **three** bounded changes; the interlock flip MUST be its own step:

- **Change A — decoupled-admit broker primitive** (self-contained in `convergence/broker/`).
  Add a `readmit_advanced_head(...) -> ReadmitResult` method to the `BrokerClient` Protocol, `BrokerService`,
  and `_RoutingBrokerService`, plus a `ReadmitResult` dataclass. Unit-testable in isolation against a
  file-backed `LinearizableAdmissionStore` + `BrokerEvidenceStore`. Encapsulates the epoch-bump binding,
  explicit `evidence_store.epoch_blocked` revocation check, the `sequence ≥ 2` baseline gate, and the
  post-admit durable-record verification.
- **Change B — thread the primitive into `_fab_delta_readmit` + the fail-closed matrix.**
  Add a `broker_admit_fn` **callable seam** parameter to `_fab_delta_readmit` (mirroring `delta_review_fn`);
  the production default binds it to `coordinator_runtime.broker_client.readmit_advanced_head`. Insert the
  brokered admit (contract items 1-6) immediately before the existing COMMIT POINT; remove the
  KNOWN-LIMITATION comment (`train_runner.py:1125-1136`). Thread `broker_admit_fn` from the merge-loop call
  site (`:3068`) using the in-scope `coordinator_runtime`. Add the M1-M6 regression tests.
  - A and B MAY be combined into one PR if kept tight, but the fail-closed matrix (B) is the load-bearing
    review surface and benefits from landing with the primitive it exercises.
- **Change C — the activation flip** (tiny, auditable, separate PR, AFTER #299).
  Flip `_FAB_DELTA_BROKER_READMIT_READY = True`; update the fence tests
  (`DeltaShortcutOptInTest.test_interlock_off_fences_engage_*`, `TestPiece3bRecoveryWiring.test_interlock_*`)
  to assert the ON behavior; delete the interlock comment block (`governed_premerge.py:64-73`).

**Interlock-flip safety call:** the flip belongs in a **SEPARATE, gated step (Change C), NOT the same change
as the mechanism.** Rationale:
- A trust-root activation that fails OPEN on missing/vacuous evidence is the worst outcome; keeping the flip a
  standalone diff lets a reviewer audit "is the gate actually closed on EVERY branch" cheaply, without that
  audit being buried under hundreds of lines of new protocol.
- It matches the milestone's established DORMANT-then-activate discipline (3b-consumer landed DORMANT in
  `ecd1258`; the producer/consumer were fenced until their gates were CR'd).
- With the interlock OFF, the Change-B fail-closed matrix is still fully provable — the tests call
  `_fab_delta_readmit` **directly** (as `DeltaReadmitTransactionTest` already does), so the mechanism is
  verified before activation. Change C then only removes the fence.
- **Hard predecessor:** Change C must land **after #299** (the recovery-block flag-gating), because
  activation ships the #299 leak active otherwise. Sequence: **A → B → #299 → C.**

## Changes (file · entity · action · reason)

### Change A — `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py` (modify)
- **Add** frozen dataclass `ReadmitResult(accepted: bool, granted_epoch: int, idempotency_key: str, reason:
  str = "")`. Reason: a typed, minimal result the readmit seam can verify field-by-field (never a bare bool).
- **Add** method `BrokerClient.readmit_advanced_head(self, *, repo, node_id, train_id, new_head_sha,
  next_epoch, approval, expected_version_predicate, authority_domain_scope) -> ReadmitResult` to the Protocol
  (search for `class BrokerClient`). Reason: the decoupled admit verb the issue requires (admit without
  publish).
- **Add** the concrete `BrokerService.readmit_advanced_head` (search for `class BrokerService`). Body:
  (1) `if self.evidence_store.epoch_blocked: return ReadmitResult(False, next_epoch, "", "revoked")` —
  explicit revocation gate (M4); (2) build a deterministic lease via a `FencedAdmissionFactory` with
  `action="readmit"`, `lease_epoch=next_epoch`, `attempt_id=sha256(node_id, new_head_sha, next_epoch,
  "fab-readmit")`, and the caller-supplied `approval`; `factory.create(...)` → `AdmissionRequest`;
  (3) `record = self.admission_store.admit(request)` — catches nothing; `PermissionError`/`ValueError`
  propagate to the seam caller which maps them to `None` (M3/M5); (4) **baseline + anti-vacuity re-read**:
  `records = self.admission_store.replay()`; require a record with `request.idempotency_key ==
  record.request.idempotency_key AND record.epoch == next_epoch AND record.sequence >= 2`; absent ⇒
  `ReadmitResult(False, ...)` (M2 + M6); present ⇒ `ReadmitResult(True, next_epoch, key)`. Reason: implements
  contract items 3-6 against harness-written durable records; the explicit `epoch_blocked` check is required
  because the admission store's own `epoch_blocked` is dormant.
- Note: `readmit_advanced_head` deliberately does NOT touch the provider adapter (no GitHub push) — the
  advance is already pushed; this is the "decouple admit from publish" the issue calls for.

### Change A — `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py` (modify)
- **Add** `_RoutingBrokerService.readmit_advanced_head(self, *, repo, **kw)` delegating to
  `self._service_for(repo).readmit_advanced_head(repo=repo, **kw)` (search for `class _RoutingBrokerService`
  / `def execute`). Reason: multi-repo routing must reach the per-repo admission+evidence store (the same
  per-repo blast-radius property the routing service already guarantees for `execute`).

### Change B — `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- **Add** a module-level default seam `_default_broker_readmit(coordinator_runtime, *, node, workspace,
  owned_paths, run_id, artifact, new_head_sha, next_epoch) -> Optional[str]` (place near
  `_default_build_admission`, `train_runner.py:101`). It builds the approval binding from **durable
  provenance** (`artifact.base.base_sha`, owned-scope digest over `owned_paths` via `os.fsencode`,
  `roadmap_digest` from the runtime — mirror `_default_build_admission:127-135`), calls
  `coordinator_runtime.broker_client.readmit_advanced_head(repo=str(workspace), node_id=node.node_id,
  train_id=coordinator_runtime.train_id, new_head_sha=new_head_sha, next_epoch=next_epoch, approval=...,
  expected_version_predicate="head == committed", authority_domain_scope=coordinator_runtime.workspace_id or
  coordinator_runtime.train_id)`, and returns `new_head_sha` iff `result.accepted and result.granted_epoch ==
  next_epoch`, else `None`. Reason: the production binding of the seam; keeps the epoch/approval evidence
  sourced from durable records, not live git.
- **Modify** `_fab_delta_readmit` signature (`train_runner.py:890-904`): add `broker_admit_fn:
  Optional[Callable] = None`. Reason: injectable seam so the fail-closed matrix tests drive the production
  branch without a live broker (mirrors `delta_review_fn`).
- **Modify** `_fab_delta_readmit` body immediately BEFORE the COMMIT POINT `append_record`
  (`train_runner.py:1137`), and before the idempotent-success-resume append (`:1013-1022`): insert the
  brokered admit. Compute `next_epoch` (already computed as the delta round epoch at `:1035`/`:1039` — reuse
  it; for the idempotent-success-resume branch derive it from the resolved chain). Then:
  `_admitted_via_broker = broker_admit_fn(...)` — **M1**: if `broker_admit_fn is None` ⇒ `return None`
  (fail closed, no direct-append fallback); if it returns `None` (M2-M6 surfaced by the primitive / caught
  `PermissionError`/`ValueError`) ⇒ recover to the admitted prefix (`_scope_run_to_admitted_prefix`, as the
  gate-fail path at `:1118` does) and `return None`. Only on a truthy broker admit does control reach the
  existing `append_record` COMMIT POINT. Reason: the ledger append (crash-consistency commit point) now runs
  ONLY after a linearized, revocation-checked, non-vacuous broker admission; the direct append is gated, not
  removed — preserving the crash-consistency ordering the 3b-consumer CR established.
- **Remove** the KNOWN-LIMITATION comment block (`train_runner.py:1125-1136`). Reason: issue Scope — "Remove
  the interim-limitation note from the 3b-consumer path when done."
- **Modify** the merge-loop call site (`train_runner.py:3068-3075`): pass
  `broker_admit_fn=(functools.partial(_default_broker_readmit, coordinator_runtime, node=_node_m) if
  coordinator_runtime is not None else None)` (or an equivalent closure capturing the in-scope
  `coordinator_runtime`). Reason: thread the live broker authority to the readmit; `coordinator_runtime` is
  already in lexical scope here (verified) — no signature plumbing through `run_train` is needed.

### Change C — `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py` (modify — SEPARATE PR, after #299)
- **Modify** `_FAB_DELTA_BROKER_READMIT_READY = False` → `True` (`governed_premerge.py:74`); delete the
  interlock comment block (`:64-73`). Reason: activate the ENGAGE path once the brokered mechanism (A+B) has
  cross-vendor CR and #299 has landed.

## Regression tests (MANDATORY — one per fail-closed branch; each drives the PRODUCTION path and FAILS before the fix)

Anti-tautology discipline (a recent PR here was blocked for asserting on values built in the test body): every
test invokes the real production function (`BrokerService.readmit_advanced_head` for A; `_fab_delta_readmit`
for B) and asserts on the durable artifacts it produces / the value it returns — never on a value the test
computed. Follow `DeltaReadmitTransactionTest`'s fixture (`tests/test_fab_delta_consumer.py:185-267`): real
git base→candidate→delta, a candidate run store, a real file-backed ledger.

### `phase-loop-runtime/tests/test_convergence_broker_readmit.py` (create — UNMARKED module) — Change A
Drive `BrokerService.readmit_advanced_head` against a real file-backed `LinearizableAdmissionStore` +
`BrokerEvidenceStore`.
- `test_readmit_bumps_epoch_above_publish_and_is_durable`: seed the store with a publish admission at epoch 1;
  readmit at `next_epoch=2` → `accepted`, `granted_epoch==2`, and `store.replay()` shows a durable epoch-2
  record with `sequence==2`. Proves the bump is real + durable.
- `test_readmit_is_idempotent_across_resume` (determinism): call readmit twice with identical inputs → the
  SAME `AdmissionRecord` (same `idempotency_key`, no second append, epoch not re-bumped). **Bite:** make
  `attempt_id` non-deterministic (uuid4) → the second call conflicts / double-appends. Proves contract item 3.
- `test_empty_store_readmit_fails_closed` (**M2 — fail-OPEN critical**): readmit against an EMPTY store →
  `not accepted`. **Bite:** delete the `sequence ≥ 2` gate → the empty-store readmit is accepted (the exact
  fail-open the advisor flagged).
- `test_revoked_epoch_denies_readmit` (**M4**): append an `OUTCOME_AMBIGUOUS_BLOCKED` evidence record →
  readmit `not accepted`. **Bite:** delete the explicit `evidence_store.epoch_blocked` check → the readmit is
  accepted despite revocation.
- `test_stale_epoch_is_rejected` (**M3**): seed a durable record at epoch 5; readmit at `next_epoch=2` →
  `admit` raises `PermissionError("stale epoch")` (assert the raise / mapped denial).
- `test_vacuous_admit_without_durable_record_fails_closed` (**M6**): inject an admission store whose `admit`
  returns a record but writes nothing durable (or whose `replay()` omits it) → readmit `not accepted`.
  **Bite:** delete the post-admit durable re-read → the vacuous admit is accepted.

### `phase-loop-runtime/tests/test_fab_delta_consumer.py` (extend `DeltaReadmitTransactionTest`) — Change B
Each calls the real `tr._fab_delta_readmit(...)` with a `broker_admit_fn` seam and the existing real fixture.
- `test_readmit_goes_through_broker_before_ledger_commit`: a spying `broker_admit_fn` that records its call
  and returns the new head → the ledger COMMIT POINT is reached AND the spy was called with `next_epoch==2`,
  `new_head_sha==delta_head`, BEFORE the ledger record was written. Proves the admit precedes the commit
  point. **Bite:** move the append before the admit → ordering assertion fails.
- `test_missing_broker_admit_fn_fails_closed` (**M1**): `broker_admit_fn=None` (shortcut path with no live
  broker) → returns `None`, NO ledger record appended, admitted head unchanged. **Bite:** remove the
  None-guard → a direct append lands with no broker.
- `test_broker_denied_readmit_recovers_and_fails_closed` (**M2-M6 at the readmit boundary**): a
  `broker_admit_fn` returning `None` (broker denied) → `_fab_delta_readmit` returns `None`, the run store is
  recovered to the admitted prefix (assert the durable chain resolves to `candidate_head`, gate still passes
  at the admitted head), NO ledger record for the new head. **Bite:** on a broker denial, skip the recover +
  return path → a torn extended provenance / spurious append survives.

(M3/M5 are covered end-to-end via the Change-A tests; at the B layer they surface through the `None`-return
path, which `test_broker_denied_readmit_recovers_and_fails_closed` exercises generically.)

### `phase-loop-runtime/tests/test_fab_delta_consumer.py` (fence tests) — Change C
- Update `DeltaShortcutOptInTest.test_interlock_off_fences_engage_even_with_both_opt_ins` (`:35`) and
  `test_requires_interlock_and_both_master_flag_and_coordinator_opt_in` (`:46`), plus
  `TestPiece3bRecoveryWiring.test_interlock_{off,on}_*` (in `tests/test_fab_activation_promotion.py`), to
  assert the ON behavior. These move WITH the flip (Change C), not before.

## Dependencies / order
1. **Change A** — broker primitive + `ReadmitResult` + Change-A tests. Self-contained; verify in isolation.
2. **Change B** — thread `broker_admit_fn` into `_fab_delta_readmit` + call site; remove KNOWN-LIMITATION
   comment; M1-M6 readmit tests. Depends on A.
3. **#299** — recovery-block flag-gating (separate issue; gating predecessor of the flip).
4. **Change C** — flip `_FAB_DELTA_BROKER_READMIT_READY` + fence-test updates. Depends on A, B, #299.

To prove each regression bites: run the new tests on the pre-change tree (Change A tests fail — no
`readmit_advanced_head`; the six-branch tests each fail under their stated mutation) and pass after.

## Verification (from `phase-loop-runtime/`)
- Prove the Change-A bite: `PYTHONPATH=src:tests python3 -m pytest -q tests/test_convergence_broker_readmit.py`
  (fails before A, passes after).
- Prove the Change-B bites: `PYTHONPATH=src:tests python3 -m pytest -q tests/test_fab_delta_consumer.py`
  (new M1/M2 tests fail before B, pass after; fence tests still assert OFF until Change C).
- Full default lane: `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"`.
  Known pre-existing unrelated failure: `test_task_message_resolver::test_control_socket_...` reproduces on
  clean main — not caused by this change.
- Model-id guard (unchanged surface; run for hygiene): `python3 phase-loop-runtime/scripts/check_model_id_sources.py`.
- Change C only: after the flip, `PYTHONPATH=src:tests python3 -m pytest -q tests/test_fab_delta_consumer.py
  tests/test_fab_activation_promotion.py` (fence tests now assert ON) plus the full default lane.

## Acceptance criteria
- [ ] `_fab_delta_readmit`'s ledger COMMIT POINT is reached ONLY after a brokered admit that is
      epoch-bumped (`lease_epoch = next_epoch ≥ 2`), revocation-checked (`evidence_store.epoch_blocked`), and
      verified against a durable `AdmissionRecord` (`sequence ≥ 2`, matching `idempotency_key` + epoch); the
      direct-append-without-broker path is gone and the KNOWN-LIMITATION comment is removed.
- [ ] All six fail-closed branches (M1 missing-authority, M2 missing-baseline/empty-store, M3 stale, M4
      revoked, M5 mismatched, M6 vacuous) each have a regression test that invokes the production function,
      FAILS under its stated mutation, and PASSES with the fix — no test asserts on a value built in its own
      body.
- [ ] The empty-admission-log fail-OPEN is structurally closed (M2 test): a readmit that would be the FIRST
      record in the store is rejected.
- [ ] With the interlock OFF (Changes A+B), the mechanism is fully test-verified and the ENGAGE fences still
      assert OFF; the flip is a separate diff (Change C) landing only after #299.
- [ ] `PYTHONPATH=src:tests python3 -m pytest -q -m "not dotfiles_integration"` shows no new failures beyond
      the known pre-existing `test_task_message_resolver::test_control_socket_...`.
