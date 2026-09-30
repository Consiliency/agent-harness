---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 3c61b270
related_issues: [agent-harness#896, agent-harness#1165, agent-harness#848, agent-harness#1147, agent-harness#1161, agent-harness#1132, agent-harness#1071, agent-harness#1166, agent-harness#1102]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_sandbox_placement.py tests/test_sandbox_egress.py tests/test_sandbox_policy.py tests/test_sandbox_retention.py tests/test_seat_host_uid_1098.py tests/test_review_monitor_policy.py tests/test_gemini_heartbeat_bootstrap.py tests/test_harden_evidence_producer.py tests/test_harden_evidence_verifier.py tests/test_review_stage_board_findings.py tests/test_sandbox_preamble.py tests/test_panel_invoker_timeout_argv.py tests/test_panel_tui_workspace_trust_223.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: vendor-neutral sandbox placement seam, receipt-bound evidence and local backend (agent-harness#896, plan 1a)

## Task

agent-harness#896: a configured sandbox root is resolved, and then the sandbox is staged and
run locally anyway. The fix is one vendor-neutral placement seam with several backends:
- **local:** today's behaviour;
- **self-hosted:** a remote host over authenticated HTTPS;
- **cloud:** first vendor planned in agent-harness#1165.

A second cloud vendor must need only an adapter.

**Bounded-plan split.** The board round asked for a full lifecycle contract, the revision queue
moved execution and the lease journal into plan 1, and the fail-closed and evidence fixes were
added. Together that is more than three distinct changes, so plan 1 is split:
- **Plan 1a**, this document, written in full:
  - the complete seam **contract**, including the execution and lease types;
  - receipt-bound placement evidence;
  - today's local path behind the seam, with no behaviour change;
  - an outcome-decided fail-closed knob.
- **Plan 1b**, listed under "Follow-on plans": the runtime driver for executing backends and the
  lease journal (heartbeat, fsynced journal, restart reaper).

The cloud path is plan 1a, then 1b, then agent-harness#1165 (4a, 4b). It no longer passes
through the self-hosted plan. Nothing here depends on the seat jail (agent-harness#1166). This
plan references agent-harness#896's acceptance items rather than restating them.

## Research summary

**The placement sequence in `panel_invoker._default_spawn`**, read at `input_base_commit`:
- scratch GC (PI:8436);
- `mkdtemp("pl-panel-").resolve()` (PI:8446). The `.resolve()` is the `provider_cwd_sha256`
  preimage (PI:4495);
- `select_sandbox_root` (PI:8484), whose result is recorded and never used;
- `ensure_staging_space` (PI:8500), then `stage_review_tree` (PI:8503);
- the staged path is tracked across the rename (PI:8508–8510), then `mark_as_sandbox`
  (PI:8516);
- `_revalidate_staged_tree` (PI:8527, implemented in `advisor_board/backing.py:1069`), then
  `revalidate_review_isolation_authorization` (PI:8537);
- the egress namespace (PI:8542–8568);
- `_record_sandbox_facts` (PI:8573–8588);
- the launch branches: brokered, claude TUI, and `_exec_leg` (PI:7633);
- the fail-closed `except` (PI:8850). It returns a bare `("DEGRADED", "", detail)` with no
  isolation evidence, unless a review monitor and broker exist;
- the `finally` (PI:8866–8879).

**What the board established by execution (hb1):**
- A staged leg that fails at egress leaves no placement facts in its result.
- A healthy legacy `host:path` selection returns `fell_back=False`.
- `scripts/verify_harden_evidence.py` `verify_broker` (around line 2334) has a closed key set.
  A valid fixture with `sandbox_root_applied` added is **rejected**, so today's `sandbox_*`
  keys and the verifier already disagree.

**Tests that pin the facts:**
- `tests/test_sandbox_egress.py`. It has direct `_record_sandbox_facts` calls, and a source-grep
  around lines 605–606.
- `tests/test_seat_host_uid_1098.py`, which also calls it directly.
- `tests/test_review_monitor_policy.py` and `tests/test_gemini_heartbeat_bootstrap.py`.

**Precedents in this repo:**
- Optional extras follow the `visual` extra in `phase-loop-runtime/pyproject.toml`, which is
  imported lazily.
- The detail vocabulary is closed at PI:2115–2131.

## Contract (normative for plans 1a, 1b, 3 and agent-harness#1165)

**Phases, in this order.** Every backend goes through them.

| Phase | Local | Non-local |
|---|---|---|
| `prepare` | Stage the tree locally. **Always.** | Stage the tree locally. Nothing leaves the host. |
| Runtime revalidation | Unchanged. Always against the local stage, so `_revalidate_staged_tree` works for every backend. | Same |
| `commit` | No-op | Transfer the **revalidated** local stage. The backend recomputes the digest, and a mismatch refuses. |
| `execute` → `wait` / `cancel` / `renew` | The runtime's own launch branches, unchanged | Backend-executed (plan 1b) |
| `release` | Remove the stage | Kill the sandbox and remove the stage |

This order means the code never leaves the operator's custody before revalidation.

**Receipts.**
- Backends return `BackendReceipt` values only.
- Only the runtime's own driver constructs `PlacementReceipt(attested_by="runtime")`, and only
  for a step the runtime itself performed and observed:
  - `prepared`: it staged;
  - `committed`: it sent snapshot bytes with digest D and got reference R;
  - `launched`: it called `execute(R)`, or spawned locally;
  - `completed`: it received the terminal result.
- Backend claims are wrapped as `attested_by="backend"`, and are never receipt-class on their
  own.
- Every receipt carries `sandbox_ref` and `snapshot_sha256`, and both are serialized.

**`sandbox_root_applied`.**
- **Local:** today's rule, written out: `backend.is_local and host is None and path == staged_at.parent`.
- **Non-local:** true iff all of these hold:
  - runtime-attested `committed` and `completed` receipts share one `sandbox_ref`;
  - both carry `snapshot_sha256 ==` the authorization's `staged_tree_sha256`;
  - the per-leg local provider-spawn count is 0;
  - any backend receipts agree with them.

  Backend receipts alone never make it true.

**`sandbox_staged_at`.**
- Local: the path, as today.
- Non-local: `<scheme>:<sandbox_ref>`. It never includes userinfo, query or a host credential.

**Capabilities.**
- `capabilities()` is what a backend *can* enforce. The vocabulary is closed:

  | Group | Capabilities |
  |---|---|
  | Network | `private_ranges_unreachable`, `public_egress`, `private_allowlist`, `inbound_closed` |
  | Confinement | `filesystem_confined`, `uid_isolated`, `bounding_set_empty`, `seccomp_filtered` |
  | Other | `resource_bounded`, `one_shot_secret_channel`, `operator_custody` |

- `PlacedSandbox.verified` maps each capability that was **verified for this placement** to its
  method, which is one of:
  - `runtime_end_to_end`: the runtime observed a destination-level result, never `connect()`
    success alone;
  - `backend_attested`.
- `verified` is always a subset of `capabilities()`.
- `LocalBackend.capabilities()` is the **empty set**. Local egress and uid facts stay in their
  existing fields, which are recorded by the code that enforces them.

**Declarations.** A backend's `declaration()` names:
- its `egress_residuals`, from a closed kind list (for example `resolver_allowed` or
  `udp_unfiltered_by_name`), each marked `closed_in_guest: bool`;
- its `guest_control_env`: the names of the control-plane variables it injects into the guest.
  Their values are redacted from evidence and logs;
- its `max_lifetime_s`, or `None`.

**Request.** `PlacementRequest` carries the leg, the round id, the repo, the snapshot digest,
`deadline_s` and `egress_needs`. `egress_needs` is derived from the global
`sandbox_policy.egress_allowlist()`, the only source today. It also carries
`one_shot_secret: bool`, the decided CD1 channel.

**Launch is final.** Once `execute` has been called, even if the call raised or its outcome is
unknown, the attempt is `launched`:
- it never falls back to local;
- a retry in the same round reuses the same backend or refuses.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (create)
- The types, the phase order and the `applied` rule — add — they encode the Contract section
  above:
  - `PlacementRequest`, `EgressNeeds`, `BackendReceipt`, `PlacementReceipt`, `Prepared`,
    `PlacedSandbox`, `Declaration`;
  - the closed `CAPABILITIES` and `VERIFICATION_METHODS`, and `PlacementUnavailable(code, reason)`.
- `PlacementBackend` (a `Protocol`: `name`, `is_local`, `capabilities`, `declaration`,
  `available`, `prepare`, `commit`, `release`) — add — the two-phase placement contract.
- `ExecutingBackend(PlacementBackend)` (`execute`, `wait`, `cancel`, `renew`, `list_owned`,
  `kill`), with `ExecSpec` and `ExecResult` — add — the execution types. Their driver is plan 1b.
- `register_backend`, `resolve_backend`, and entry-point discovery under
  `phase_loop_runtime.placement_backends` — add — optional extras register themselves, so core
  names no vendor. Registration **refuses** a non-local backend that does not implement
  `ExecutingBackend`, so a backend can never stage remotely while the provider starts locally.
- `LocalBackend` — add:
  - `prepare` runs today's `ensure_staging_space` → `stage_review_tree` → rename → `mark_as_sandbox`
    sequence, and **owns the partial state until it returns**. On any exception it removes
    whatever it created, the pre-rename path or the post-rename path, then re-raises.
  - `commit` is a no-op.
  - `release` calls `remove_review_stage`.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `SandboxLocation` / `parse_location` — modify:
  - add `scheme`: `local`, `hostpath`, or a URL scheme;
  - strip userinfo and the query string **at parse**, so a credential never reaches `repr`,
    `asdict` or evidence;
  - bare paths and drive letters parse as they do today.
- `select_sandbox_root` — modify — a scheme with no registered backend is never probed: no
  `ssh`, no DNS, no socket. It falls back to local, and the reason names the scheme. `hostpath`
  is unchanged; RD6 is ruled record-only.
- `remote_required()` — add — reads `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED`. It governs
  **board-seat** placement only (RD3 is ruled seats-only), and the documentation says so.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_default_spawn` — modify:
  - `resolve_backend`, then `backend.prepare`, replaces PI:8500–8516. Selection at PI:8484
    stays.
  - Both revalidations run next, unchanged, against the local stage; then `backend.commit`.
  - Egress, launch and `rmtree(base)` are unchanged, in the same order.
  - `prepared` and `placed` are initialised to `None` before the `try`, and the `finally`
    releases whichever exists.
- The fail-closed check — add — at the **launch boundary**, for every review-mode seat leg,
  whether or not a tree was authorized. It raises `sandbox_placement_required_unavailable`
  unless the placement came from a registered non-local backend matching the configured
  scheme. In 1a no such backend exists, so the knob always refuses:
  - with a reachable `hostpath`;
  - with an unset or local root;
  - on a route with no staged tree.
- The per-leg provider-spawn counter — add — a contextvar incremented at the provider spawn
  chokepoints: `run_provider` and its `Popen` sibling, next to PI:3495–3500. The identity probe
  is excluded. It is the "zero local spawns" observation.
- The fact recording — modify:
  - `_record_sandbox_facts` is called right after `prepare` and updated after `commit` and
    after launch.
  - The `except` at PI:8850 attaches `_sandbox_evidence()` to the `DEGRADED` result through the
    existing `attach_harden_isolation_evidence` / `_BrokeredSpawnResult(evidence=…)` path. A
    placement therefore always reaches the leg record, including when refusal comes after
    placement.
- `_record_sandbox_facts` — modify:
  - Every existing field stays.
  - Add `sandbox_placement_backend`, `sandbox_placement_receipts`, `sandbox_placement_verified`
    and `sandbox_local_provider_spawns`.
  - `applied` and `sandbox_staged_at` follow the Contract section.
  - The fallback reason stays in `sandbox_root_reason`. `sandbox_root_unapplied_reason` appears
    only when `applied` is false.
  - The reset-token discipline is unchanged.
- `_HARNESS_DETAIL_CODES` — modify — add exactly `"sandbox_placement_required_unavailable"`.

  **Frozen vocabulary, quoted from PI:2115–2123:** "`PanelLegResult.detail` is built ONLY from
  our own closed vocabulary … a HARNESS CODE — a fixed string this runtime itself emits
  (`_HARNESS_DETAIL_CODES`)". This adds one member by that mechanism, and no template or
  category.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)
- `verify_broker` closed key set — modify — accept every `sandbox_*` key the producer emits,
  existing and new. The current set already rejects them (hb1, measured).
- A placement check — add:
  - `sandbox_root_applied=true` must satisfy the Contract rule for the recorded backend;
  - every receipt's `snapshot_sha256` must equal the authorization's staged-tree digest. If
    the verifier's input does not already carry that digest, the producer adds it as
    `sandbox_snapshot_sha256`, taken from the authorization and never from a receipt;
  - backend-only receipts can never support `applied` for a non-local backend.

### `phase-loop-runtime/tests/test_sandbox_placement.py` (create)
- The falsifiers under "Verification".

### `phase-loop-runtime/tests/test_sandbox_egress.py`, `tests/test_seat_host_uid_1098.py`, `tests/test_harden_evidence_verifier.py` (modify)
- The direct `_record_sandbox_facts` calls and the source-grep — modify — to the new signature.
- A producer→verifier round trip on a real sandboxed record — add.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — the
  Contract section: phases, receipts, the `applied` rule, capabilities and declarations, and
  "launch is final".
- `docs/phase-loop/convergence-runtime.md` — modify — URL-scheme roots and their recorded
  fallback. `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED` covers board seats only, and in this release
  always refuses.
- `CHANGELOG.md` — modify — the seam, the evidence fields, the verifier key set and the knob.
  Note that the agy pin set drifts, so the next release cut requalifies agy.

## Dependencies & order
1. **agent-harness#1161.** It changes scratch allocation, the effective floor, pre-stage
   reclamation, retention marking, cleanup and child temp dirs. Whichever of #1161 and this plan
   lands second rebases, **re-captures the local-equivalence golden** on the merged base, and
   adds `tests/test_sandbox_staging_1147.py` to the gate. `LocalBackend.prepare` must preserve
   all of #1161's staging behaviour, not one site.
2. **agent-harness#1132, #1071 and #1166.** There is no functional dependency. They touch
   `_default_spawn` and `_record_sandbox_facts`, so the same rule applies: the second to land
   rebases and re-captures.
3. **Order within this plan:**
   1. Capture the equivalence golden **at `input_base_commit`** first, before any code moves.
   2. Write the tests. They fail on the missing symbols, and that is recorded as the RED receipt
      on the branch. They land together with the implementation.
   3. `sandbox_placement.py`.
   4. `sandbox_policy`.
   5. `_default_spawn` and the facts.
   6. The verifier.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_sandbox_placement.py tests/test_sandbox_egress.py tests/test_sandbox_policy.py \
  tests/test_sandbox_retention.py tests/test_seat_host_uid_1098.py \
  tests/test_review_monitor_policy.py tests/test_gemini_heartbeat_bootstrap.py \
  tests/test_harden_evidence_producer.py tests/test_harden_evidence_verifier.py \
  tests/test_review_stage_board_findings.py tests/test_sandbox_preamble.py \
  tests/test_panel_invoker_timeout_argv.py tests/test_panel_tui_workspace_trust_223.py
# after rebasing over agent-harness#1161, also: tests/test_sandbox_staging_1147.py
```

Falsifiers in `test_sandbox_placement.py`. Each is control-green, and red under its named
mutation.

**Local equivalence.** Record the full call sequence, including the entry and **exit** of
`isolated_network` and `remove_review_stage`, plus the provider argv and `provider_cwd_sha256`.
Compare it to the golden captured at `input_base_commit`. Mutations:
- `mark_as_sandbox` before the rename;
- `local_tree` returns the pre-rename path;
- `release` before the egress exit.

**Partial-failure ownership.** Inject a fault after `stage_review_tree`, after the rename, and
at `mark_as_sandbox`: no stage directory remains, and the exception propagates. Inject a
revalidation failure after `prepare`: the `finally` releases it. Mutation: remove `prepare`'s
rollback.

**Failure exits keep the evidence.** Inject an egress failure after a successful `prepare`. The
`DEGRADED` result carries the placement facts and a `prepared` receipt. Mutation: drop the
attach in the `except`.

**Unregistered schemes never probe.** With `https://example.invalid/x`, `e2b://t` or
`modal://t`, spies on `subprocess`, `socket.connect` and `socket.getaddrinfo` all record zero
calls. The leg runs local with a recorded fallback reason. Mutation: route unknown schemes to
`_probe_root`.

**Backend claims never apply.** A fake `ExecutingBackend` is registered, but the 1a driver never
calls `execute`, so no runtime `completed` receipt exists. It returns only backend receipts:
`applied=False`. Mutation: ignore `attested_by`.

**Registry.** Registering a non-local backend that is not an `ExecutingBackend` raises.
Mutation: accept it.

**Fail closed.** Each case below ends with detail `sandbox_placement_required_unavailable`, zero
`stage_review_tree` calls where staging had not yet occurred, and a spawn count of 0:
- a `hostpath` root whose probe **passes**;
- a `hostpath` root whose probe fails;
- an unset root, and a local root;
- an unregistered scheme;
- a route with no authorized tree.

Mutation: decide by `fell_back`.

**No credential leaks.** `https://u:t@h/p?k=v` appears as `https://h/p` in `repr`, `asdict`,
evidence, warnings and the leg log. Mutation: redact only in `__str__`.

**Vocabulary.** The code is a member of `_HARNESS_DETAIL_CODES` and passes
`_finalize_leg_detail` unchanged. Mutation: remove the member; the detail then becomes the
unknown-failure template.

**Verifier.** A real sandboxed brokered record passes. The same record with `applied=true` and
only backend receipts fails. Mutation: skip the placement check.

**Edge cases.**
- A drive-letter root is local.
- For the `hostpath` record, the existing fields are identical and only the new fields are added.
- With nothing configured, no probe runs.

Run the suite on a tree **left untouched** for its duration.

## Acceptance criteria
- [ ] With no root configured, the local-equivalence falsifier matches the
  `input_base_commit` golden: call sequence (including the egress exit), provider argv and
  `provider_cwd_sha256`. Every file in `automation.suite_command` passes.
- [ ] With the egress failure injected after `prepare`, the `DEGRADED` leg result carries
  `sandbox_placement_receipts` with a runtime-attested `prepared` receipt.
- [ ] A registered fake backend that returns only backend-attested receipts yields
  `sandbox_root_applied=False`. Removing the `attested_by` check turns
  `test_sandbox_placement.py::test_backend_claims_never_apply` red.
- [ ] With `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED=1`, each fail-closed case listed under
  Verification ends with detail `sandbox_placement_required_unavailable`, and the spawn-seam
  counter reads 0. That includes a reachable `hostpath`, an unset root, and a route with no
  tree.
- [ ] `verify_harden_evidence.py` accepts a real sandboxed brokered record produced by this
  runtime, and rejects the same record once `applied=true` rests only on backend receipts.

## Follow-on plans

### Plan 1b: execution driver and lease journal (next; the cloud path depends on it)

**Scope.** The runtime side of `ExecutingBackend`, for any non-local backend, and the lease
journal.

- **`sandbox_placement.py` or a new `placement_lease.py`:**
  - **Owner and journal.**
    - A per-user random owner id lives in the state directory.
    - The lease journal is under `$XDG_STATE_HOME/phase-loop/placement-leases/` (directory 0700,
      files 0600).
    - Each entry is written and fsynced, together with its directory, **before `commit`**.
      Backends must tag every remote sandbox with the owner id and lease id at create.
  - **Liveness** is an `flock` on each lease file, held by the owning process. It is never
    decided by pid or age.
  - **Heartbeat.** A thread renews through `backend.renew`, and never past the leg deadline.
    A leg whose deadline exceeds the backend's `max_lifetime_s` is refused before `commit`.
    That refusal is pre-launch, so it can fall back.
  - **Reaper.** It runs at runtime start, beside `_gc_stale_panel_scratch`, periodically, and
    from `phase-loop sandbox reap` in `cli.py`. It calls `list_owned(owner_id)` across every
    page and every state, paused included. It kills only sandboxes whose lease lock is free,
    then clears stale journal entries.
- **`panel_invoker.py`:**
  - The non-local execution branch: after `commit`, it runs `execute(ExecSpec)` with the CD1
    one-shot secret channel, then `wait` with the deadline.
  - `cancel` runs on cancellation, timeout or quiescence.
  - Output bytes are ingested under a size cap and a regular-bytes check, and the token scan
    runs before any leg record.
  - It produces runtime `launched` and `completed` receipts.
  - It enforces "launch is final".
  - It adds two fixed detail codes, `sandbox_placement_lost_after_launch` and
    `sandbox_placement_lease_expired`.

**Falsifiers (fake `ExecutingBackend`):**

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Execute path | `applied=true`, zero local spawns | — |
| Post-launch failure, including a lost acknowledgement | No local spawn, no fallback | Fall back on any exception |
| Owner SIGKILLed | The next start's reaper kills its sandbox | — |
| Another owner's sandbox, and a live same-owner lease held by a second process | Survives | Drop the owner filter; liveness by pid |
| Paused sandbox listed across pages | Reaped | Running-only listing; first page only |
| Renewal | Never exceeds the deadline | Fixed extension |
| Journal write | Happens before `commit` | Write after `commit` |

**Dependencies.**
- It needs plan 1a.
- It unblocks agent-harness#1165 (4a, then 4b) directly.

### Plan 2: egress allowlist from configuration
- **Scope.** The fleet-specific inference address in `sandbox_policy._INFERENCE_ALLOW` is
  replaced by `PHASE_LOOP_SANDBOX_EGRESS_ALLOW` (`host:port`, default empty). A static test
  keeps private or CGNAT host literals out of product code.
- **Ship it together with** the deployment's own configuration value, so no operator loses
  access in between.
- **Dependencies.** None.

### Plan 3: self-hosted remote over HTTPS (RD1–RD6 as ruled)
- **Scope.**
  - An `https://` `ExecutingBackend` and the agent: TLS with no insecure mode, and a 401 for an
    unauthenticated request.
  - Per-principal workspaces and subordinate uids.
  - cgroup bounds.
  - A server-side journal that mirrors 1b, and an attestation that gates the leg and is
    never receipt-class.
  - Retention, the floor and the cap.
  - The qualification command.
  - A falsifier for each consumer prerequisite on agent-harness#896.
- **Dependencies.**
  - It needs 1a and 1b.
  - The launch path for jailed seats waits on the seat jail.
  - Because of its size, it is expected to split again when written.
- **Note.** RD1 (a) per-user service and RD5 (a) project quotas need a one-time root setup
  on the host, which is a documented host prerequisite.

### Plans 4a and 4b: first cloud adapter (agent-harness#1165)
- **Dependencies.** 1a and 1b only.
- **Inherited from the hb1 board.** agent-harness#1165 carries these items; they are not
  restated in this plan:
  - sandbox creation always restricts public inbound traffic, with an unauthenticated-access
    falsifier;
  - the owner-filtered, paginated listing covers every state;
  - the leak falsifier includes another owner's sandbox, which must survive;
  - egress probes check the destination, not the connection;
  - IPv6 ranges are covered;
  - the guest loopback daemon cannot be driven by the seat's uid;
  - the vendor's opaque build identifier versus the "pinned by digest" requirement is
    surfaced as a decision there;
  - the revision-queue items F6 and F7 (the SDK's secure-access flag, and a debug mode that
    disables kill).

## Maintainer decisions

**Recorded on agent-harness#1162:**
- RD1–RD6 are accepted as recommended. RD3 is seats only.
- CD1 is the same one-shot channel as the local route.
- CD2 is all repositories.
- CD3 and CD4 are accepted as recommended.

**Open for plan 1a:** none.

## Execution Policy

- execute: effort=high, reason=behaviour-preserving refactor of the attested launch site, its
  evidence record and its verifier; falsifiers must prove byte-identical local placement
