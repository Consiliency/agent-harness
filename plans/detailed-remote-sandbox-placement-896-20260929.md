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
| `prepare` | Runtime code: stage the tree locally | The **same runtime code**. Backends never implement `prepare`. |
| Runtime revalidation | Unchanged. Always against the local stage, so `_revalidate_staged_tree` works for every backend. | Same |
| `commit` | No-op | Transfer the **revalidated** local stage. The backend recomputes the digest, and a mismatch refuses. `commit` owns any partial remote state until it returns, and removes it on any exception. |
| `execute` → `wait` / `cancel` / `renew` | The runtime's own launch branches, unchanged | Backend-executed (plan 1b) |
| `release` | Remove the stage | Kill the sandbox and remove the stage |

The code never leaves the operator's custody before revalidation. This holds **by
construction**, because `prepare` is runtime code (`sandbox_placement.prepare_local_stage`,
today's `LocalBackend` sequence) run for every backend.

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
- `sandbox_ref` must match `[A-Za-z0-9._:-]{1,128}`. Any other value refuses the placement.
- **Digest source.** The runtime **computes** `prepared.snapshot_sha256` from the local stage
  with `review_tree_manifest_sha256`; it is never copied from the authorization. A refusal
  record carries the computed digest as it is. The check that a digest equals the
  authorization's `staged_tree_sha256` applies only to receipts cited in support of
  `applied=true`.

**`sandbox_root_applied`.**
- **Local:** today's rule, written out: `backend is the built-in LocalBackend and host is None
  and path == staged_at.parent`.
  - `is_local` is not an attribute a backend declares. The registry binds it to the built-in
    `LocalBackend`, and refuses a plugin that registers a built-in scheme (`local`,
    `hostpath`).
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
- Only the runtime writes `runtime_end_to_end`. An entry supplied by a backend is coerced to
  `backend_attested`.
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

**Execution gate: commit only what this build will execute.** A runtime may call a method of
a non-local backend (`available`, `commit`, `execute`) only if **that same build's** driver
will execute on it. One driver constant in `panel_invoker`, `_NONLOCAL_EXECUTION_DRIVER`, fixes
this:
- **In 1a it is `False`.** Every resolved non-local backend is refused with
  `PlacementUnavailable("sandbox_placement_driver_unavailable")` **before `prepare` and before
  any backend method**. No stage is built for it, and no snapshot byte leaves the host.
  - Knob off: a recorded local fallback, with `sandbox_root_fell_back=True` and a reason naming
    the scheme and the code.
  - Knob on: `sandbox_placement_required_unavailable`, with zero spawns.
- **1b sets it to `True`** in the same change that adds the execute branch.

Registration checks the protocol only; it does not make anything execute. The gate is what
keeps a conformant backend package, installed on a 1a-only runtime, from receiving the tree
while the leg runs locally. In 1a no transfer happens at all, because `commit` is reached only
for `LocalBackend`, where it is a no-op. From 1b on, `commit` is the only transfer.

**Exemption from the fail-closed knob is by execution, not by origin.** The knob exempts only
a leg the runtime ran through the backend's `execute` and completed. In 1a that is never true.
Once 1b lands it equals "placed remotely and executed there".

**Launch is final.** Once `execute` has been called, even if the call raised or its outcome is
unknown, the attempt is `launched`:
- it never falls back to local;
- a retry in the same round reuses the same backend or refuses.

**Execution types.** 1b owns the full field set. The minimum is:
- `ExecSpec`: argv, in-sandbox cwd, env (the declared set only), `one_shot_secret`
  (bytes or `None`), `deadline_s` and `output_cap_bytes`;
- `ExecResult`: `sandbox_ref`, exit status, stdout bytes, stderr bytes, and `truncated`.

**Plugin loading.**
- Entry points under `phase_loop_runtime.placement_backends` are loaded **only** when the
  configured root names a non-built-in scheme. A run with no root configured, or a local root,
  never imports a plugin.
- A plugin that fails to import or register becomes a pre-launch `PlacementUnavailable` for
  that scheme alone. It falls back or fails closed like any other refusal, and local legs are
  untouched.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (create)
- The types, the phase order and the `applied` rule — add — they encode the Contract section
  above:
  - `PlacementRequest`, `EgressNeeds`, `BackendReceipt`, `PlacementReceipt`, `Prepared`,
    `PlacedSandbox`, `Declaration`;
  - the closed `CAPABILITIES` and `VERIFICATION_METHODS`, and `PlacementUnavailable(code, reason)`.
- `PlacementBackend` (a `Protocol`: `name`, `capabilities`, `declaration`, `available`,
  `commit`, `release`) — add — the placement contract.
- `prepare_local_stage` — add — the runtime-owned `prepare`, run for every backend.
- `ExecutingBackend(PlacementBackend)` (`execute`, `wait`, `cancel`, `renew`, `list_owned`,
  `kill`), with `ExecSpec` and `ExecResult` — add — the execution types. Their driver is plan 1b.
- `register_backend`, `resolve_backend`, and entry-point discovery under
  `phase_loop_runtime.placement_backends` — add — optional extras register themselves, so core
  names no vendor. Plugins are loaded under the "Plugin loading" rule.
  - Registration refuses a non-local backend that does not implement `ExecutingBackend`, and
    refuses a plugin claiming a built-in scheme.
  - That is a protocol check only. The execution gate is what prevents a non-local stage
    from being followed by a local launch.
- `LocalBackend` — add:
  - `prepare_local_stage` runs today's `ensure_staging_space` → `stage_review_tree` → rename → `mark_as_sandbox`
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
- `remote_required()` — add — reads `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED`.
  - The values `1`, `true`, `yes` and `on` mean on, and unset, empty, `0`, `false`, `no` and
    `off` mean off, all case-insensitive. **Any other value means on**, with a warning: an
    unrecognised value fails closed.
  - It governs seat legs only, as defined under `panel_invoker.py`, because RD3 is ruled
    seats-only.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_default_spawn` — modify:
  - `resolve_backend`, then `prepare_local_stage`, replaces PI:8500–8516. Selection at
    PI:8484 stays.
  - The execution gate comes **first**, before `prepare_local_stage` and before any backend
    method, as the Contract section describes.
  - Under the knob, 1a also refuses **before `prepare`**. The outcome is already known there.
    The launch-boundary check below stays as a backstop.
  - Both revalidations run next, unchanged, against the local stage; then `backend.commit`.
  - Egress, launch and `rmtree(base)` are unchanged, in the same order.
  - `prepared` and `placed` are initialised to `None` before the `try`, and the `finally`
    releases whichever exists.
- The fail-closed check — add — as the backstop at the **launch boundary**, before egress
  acquisition so that an egress failure cannot pre-empt its code.
  - **Scope:** "seat legs", which means every review-mode leg `_default_spawn` launches for a
    board seat, whether or not a tree was authorized. The documentation uses the same
    definition.
  - **Rule:** raise `sandbox_placement_required_unavailable` unless the Contract's
    execution-based exemption holds. Where placement came from is never enough.
  - **In 1a** the knob always refuses **by construction**, even with a conformant non-local
    backend installed; this does not rest on none being bundled. So it refuses:
  - with a reachable `hostpath`;
  - with an unset or local root;
  - on a route with no staged tree.
- The per-leg provider-spawn counter — add:
  - a **mutable per-leg cell** (a small locked counter object), installed at leg start in a
    `ContextVar`;
  - copied contexts share the same object, and helper threads receive it explicitly;
  - it is incremented at the chokepoints `run_provider` and `launch_provider`, next to
    PI:3495–3500. Every launch branch, brokered legs included, reaches one of them, and the
    identity probe is excluded;
  - it is read when the record is **serialized**, so a `DEGRADED` record cannot report 0
    after a spawn.
- The fact recording — modify:
  - `_record_sandbox_facts` is called right after `prepare` and updated after `commit` and
    after launch.
  - The `except` at PI:8850 attaches `_sandbox_evidence()` to the `DEGRADED` result whenever
    facts exist, **whether or not a review monitor or broker exists**. It returns a result
    object that carries the evidence on every branch. The implementer first confirms that every
    caller of `_default_spawn` accepts `_BrokeredSpawnResult` on the non-monitor path; if one
    does not, the evidence goes through `attach_harden_isolation_evidence` on the object that
    caller builds. A placement therefore always reaches the leg record, including when refusal
    comes after placement.
- `_record_sandbox_facts` — modify:
  - Every existing field stays.
  - Add `sandbox_placement_backend`, `sandbox_placement_receipts`, `sandbox_placement_verified`
    and `sandbox_local_provider_spawns`.
  - `applied` and `sandbox_staged_at` follow the Contract section.
  - The fallback reason stays in `sandbox_root_reason`. `sandbox_root_unapplied_reason` appears
    only when `applied` is false.
  - **Reset on every exit.** From the first `set`, the reset token is registered in the leg's
    own outer `try`/`finally`, not on the egress `ExitStack`. Every exit therefore restores the
    pre-leg value.
- `_HARNESS_DETAIL_CODES` — modify — add exactly two fixed codes,
  `"sandbox_placement_required_unavailable"` and `"sandbox_placement_driver_unavailable"`.

  **Frozen vocabulary, quoted from PI:2115–2123:** "`PanelLegResult.detail` is built ONLY from
  our own closed vocabulary … a HARNESS CODE — a fixed string this runtime itself emits
  (`_HARNESS_DETAIL_CODES`)". This adds two members by that mechanism, and no template or
  category.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)
- `verify_broker` closed key set — modify — **enumerate** the keys; never accept by prefix. The
  current set already rejects them (hb1, measured).
  - Existing: `sandbox_root_host`, `sandbox_root_path`, `sandbox_root_fell_back`,
    `sandbox_root_reason`, `sandbox_staged_at`, `sandbox_root_applied`,
    `sandbox_network_filtered`, `sandbox_network_mechanism`,
    `sandbox_network_unfiltered_reason`, `sandbox_seat_identity`,
    `sandbox_root_unapplied_reason`.
  - New: `sandbox_placement_backend`, `sandbox_placement_receipts`,
    `sandbox_placement_verified`, `sandbox_local_provider_spawns`, `sandbox_snapshot_sha256`.
- A placement check — add:
  - `sandbox_root_applied=true` must satisfy the Contract rule for the recorded backend;
  - every receipt cited in support of `applied=true` must carry a `snapshot_sha256` equal to the
    authorization's staged-tree digest. If
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
  fallback. `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED` covers seat legs only (the same definition as the
  code), reads an unrecognised value as on, and in this release always refuses. A configured
  *local* path root stays record-only (`applied=false`). Local staging location is set by
  agent-harness#1161's staging-directory setting, not by this root.
- `CHANGELOG.md` — modify — the seam, the evidence fields, the verifier key set and the knob.
  Note that the agy pin set drifts, so the next release cut requalifies agy.

## Dependencies & order
1. **agent-harness#1161.** It changes scratch allocation, the effective floor, pre-stage
   reclamation, retention marking, cleanup and child temp dirs. Whichever of #1161 and this plan
   lands second rebases, **re-captures the local-equivalence golden** on the merged base, and
   adds `tests/test_sandbox_staging_1147.py` to the gate. `prepare_local_stage` must preserve
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
revalidation failure after `prepare`: the `finally` releases it. Mutation: remove
`prepare_local_stage`'s rollback.

**Failure exits keep the evidence.** Inject an egress failure after a successful `prepare`, on
**each** launch branch (brokered, claude TUI, `_exec_leg`) and with and without a review
monitor. The `DEGRADED` result carries the placement facts and a `prepared` receipt.
Mutation: attach only when a broker exists.

**No stale facts.** Run two legs on one thread. The first fails at revalidation and the second
inside `prepare`. The second must carry no sandbox facts. Mutation: reset only through the
egress stack.

**Spawn counter.** A spawn made from a helper thread, and one made from a copied context, both
count. A `DEGRADED` record serialized after a spawn reports it. Mutation: an integer
`ContextVar`.

**Unregistered schemes never probe.** With `https://example.invalid/x`, `e2b://t` or
`modal://t`, spies on `subprocess`, `socket.connect` and `socket.getaddrinfo` record zero calls
**during selection**, which is where the spies are scoped. No plugin is imported unless the
scheme is configured. The leg runs local with a recorded fallback reason. Mutation: route unknown schemes to
`_probe_root`.

**The execution gate.** A conformant fake `ExecutingBackend` is registered for the configured
scheme, and it counts every method call. Run it with the knob **off** and **on**:
- **Both runs:** zero calls to `available`, `commit` and `execute`, and zero
  `prepare_local_stage` calls for it.
- **Knob off:** a local run, with `sandbox_root_fell_back=True` and a reason naming the scheme and
  `sandbox_placement_driver_unavailable`.
- **Knob on:** detail `sandbox_placement_required_unavailable`, with a spawn count of 0.

Mutations:
- exempt by where placement came from;
- set `_NONLOCAL_EXECUTION_DRIVER = True` without an execute branch.

**Plugin failure.**
- A broken entry point is never imported while no root is configured.
- Once its scheme is configured, it becomes a pre-launch fallback, or a refusal under the knob.
- A local leg in the same process is unaffected.

Mutation: load all entry points at import.

**Backend claims never apply.** This is a derivation-level unit test of the `applied` rule on
synthesized non-local placement state, because 1a cannot reach it end to end.
- Backend-attested `committed` and `completed` receipts with a matching `sandbox_ref` and the
  authorization digest, and a spawn count of 0, give `applied=False`. In that setup
  `attested_by` is the only guard. Mutation: ignore `attested_by`.
- Runtime receipts are present, but a backend receipt names a different `sandbox_ref` or
  digest: `applied=False`, with a distinct unapplied reason. Mutation: ignore backend
  receipts.

**Registry and self-declared honesty inputs.**
- Registering a non-local backend that is not an `ExecutingBackend` raises.
- A plugin registering `local` or `hostpath` raises.
- A backend-supplied `runtime_end_to_end` entry is recorded as `backend_attested`.
- A `sandbox_ref` outside the allowed characters refuses the placement.

Mutations:
- accept the non-executing backend;
- accept the built-in scheme;
- keep the backend's method label.

**Fail closed.** Each case below ends with detail `sandbox_placement_required_unavailable`, **zero
`stage_review_tree` calls** (1a refuses before `prepare`) and a spawn count of 0. Each case runs
on every launch branch (brokered, claude TUI, `_exec_leg`), and again with sandboxing disabled:
- a `hostpath` root whose probe **passes**;
- a `hostpath` root whose probe fails;
- an unset root, and a local root;
- an unregistered scheme;
- a route with no authorized tree;
- the knob set to an unrecognised value such as `enable`.

Mutations:
- decide by `fell_back`;
- read an unrecognised value as off;
- drop the pre-`prepare` refusal. The launch-boundary backstop still refuses, but staging is
  then observed.

**No credential leaks.** `https://u:t@h/p?k=v` appears as `https://h/p` in `repr`, `asdict`,
evidence, warnings and the leg log. Mutation: redact only in `__str__`.

**Vocabulary.** Both codes are members of `_HARNESS_DETAIL_CODES` and pass
`_finalize_leg_detail` unchanged. Mutation: remove either member; the detail then becomes the
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
- [ ] With an egress failure injected after `prepare`, on each of the brokered, claude TUI and
  `_exec_leg` branches, the `DEGRADED` leg result carries `sandbox_placement_receipts` with a
  runtime-attested `prepared` receipt.
- [ ] Register a conformant fake `ExecutingBackend` for the configured scheme. With the knob off
  **and** on, it records zero calls to `available`, `commit` and `execute`.
  - Knob off: `sandbox_root_fell_back=True`, with a reason naming the scheme and
    `sandbox_placement_driver_unavailable`.
  - Knob on: `sandbox_placement_required_unavailable`, with a spawn count of 0.
- [ ] With `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED=1`, each fail-closed case listed under
  Verification ends with detail `sandbox_placement_required_unavailable`, and the spawn-seam
  counter reads 0. That includes a reachable `hostpath`, an unset root, and a route with no
  tree.
- [ ] `verify_harden_evidence.py` accepts a real sandboxed brokered record produced by this
  runtime, and rejects the same record once `applied=true` rests only on backend receipts.
  `test_sandbox_placement.py::test_backend_claims_never_apply` passes at derivation level:
  backend-attested `committed` and `completed` receipts with a matching ref and digest, and 0
  spawns, give `applied=False`.

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
  - It sets `_NONLOCAL_EXECUTION_DRIVER = True` **in the same change** as the execute branch,
    and its falsifier replaces 1a's gate test: a registered fake backend is committed and then
    executed, with zero local spawns.
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
  - The RD6 (a) typed notice for a legacy `host:path` root.
- **Dependencies.**
  - It needs 1a and 1b.
  - The launch path for jailed seats waits on the seat jail.
  - Because of its size, it is expected to split again when written.
- **Note.** RD1 (a) per-user service and RD5 (a) project quotas need a one-time root setup
  on the host, which is a documented host prerequisite.

### Plans 4a and 4b: first cloud adapter (agent-harness#1165)
- **Dependencies.** 1a and 1b only.
- **Inherited from the hb1 and hb2 boards.** agent-harness#1165 carries these items; they are
  not restated in this plan:
  - a scan for the API key in the **local** provider environment, because fallback legs
    inherit the runtime's environment;
  - per-principal isolation under a single project key. Owner metadata is cooperative, not a
    security boundary;
  - CD2's per-repository opt-out;
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
- CD2 is all repositories, with a per-repository opt-out. agent-harness#1165 implements the
  opt-out.
- RD6 (a) is record-only for `host:path`. Plan 3 owns its typed notice. Until then, 1a keeps
  today's record, adds the new fields, and makes the knob refuse.
- No plan in this lineage makes a configured *local* path root `applied`. It stays honest
  record-only. Local staging location belongs to agent-harness#1161's setting.
- CD3 and CD4 are accepted as recommended.

**Open for plan 1a:** none.

## Execution Policy

- execute: effort=high, reason=behaviour-preserving refactor of the attested launch site, its
  evidence record and its verifier; falsifiers must prove byte-identical local placement
