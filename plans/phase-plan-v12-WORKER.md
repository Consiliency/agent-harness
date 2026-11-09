---
phase_loop_plan_version: 1
phase: WORKER
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5
automation:
  suite_command: ["timeout", "900", "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "phase-loop-runtime/tests/test_convergence_adapters.py", "phase-loop-runtime/tests/test_supervised_worker.py", "phase-loop-runtime/tests/test_supervised_worker_cli.py", "phase-loop-runtime/tests/test_supervised_worker_receipt.py", "phase-loop-runtime/tests/test_output_retention.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_supervised_launch_receipt.py"]
---

# WORKER: Bounded patch-return worker

## Context

Phase 3 of the v12 roadmap for agent-harness#1818. The roadmap's EC-WORKER IDs
are the sole acceptance authority. WORKER composes ENVELOPE admission and
JOURNAL attempt history with the existing bounded adapter lifecycle. It is
authored against labelled synthetic fixtures. Its IF gate is a local seam
freeze, not public conformance. CLOSEOUT discharges the pinned-behavior parts
of each EC.

The roadmap stays advisory: it is encoded as superseded and v11 remains
selected, so autonomous selection needs a separate owner lifecycle decision.
This planning PR authorizes no implementation, provider run, delegation,
review dispatch, merge or live use.

**Upstream state (observed on main at planning time).**

- ENVELOPE is implemented on main: `supervised_launch.py`,
  `supervised_launch_binding.py`, `supervised_dependency.py`, five test files,
  `docs/supervised-worker.md` and `plans/evidence/supervised-worker/ENVELOPE.md`
  landed through agent-harness#1828. It is not closed:
  - its manifest entry has status `committed` and an empty lifecycle;
  - its receipt says `synthetic_fixture_only`, `final_tree_validated: false`
    and every EC-ENVELOPE `pending_hosted_ci`.
- JOURNAL is unimplemented: there is no `run_status*.py` on main. Its plan is
  agent-harness#1925.
- SCHEMA completed ahead of its DAG position under owner-authorized manual
  intake, which has four effects:
  1. The v1 bundle is available, but WORKER does not consume it at runtime.
     Lifecycle and termination names come from its run-status labels only as
     provisional fixture vocabulary.
  2. SCHEMA's receipt co-assigns WORKER 113 semantic and coverage rows, all
     `upstream_phase_unmet`. WORKER's receipt lists them as deferred to
     CLOSEOUT and resolves none.
  3. WORKER must leave SCHEMA's files untouched.
  4. CLOSEOUT's work-start gate now reduces to WORKER plus JOURNAL.

**Work-start gate.** All of the following, with
`blocker_class=upstream_phase_unmet` and `human_required=false` until then:

- IF-0-ENVELOPE-1 as landed on main (its acceptance stays a CLOSEOUT/hosted
  matter);
- IF-0-JOURNAL-1 implemented and landed;
- its landed names match artifact §8 (J1–J6, reconciled with JOURNAL's
  revised §10/§11 on agent-harness#1925). A rename needs a WORKER artifact
  amendment before work, never an in-lane workaround.

**Owner rulings in force (2026-11-08).** These are the board-recommended
answers on agent-harness#1926, accepted by the owner. The artifact applies them.

- OQ-1: the child gets the scrubbed launcher environment, narrowed by the
  digest-bound `worker_environment_allow`, which defaults to empty. Binding
  values to admission waits for CLOSEOUT v2.
- OQ-2: CLOSEOUT SL-1 raises ENVELOPE's 1 MiB executable cap, using a
  streaming hash and a configured ceiling, and still refuses symlinked
  executables.
- OQ-3: stdout carries the git-style unified-diff proposal.
- OQ-4: SL-2 makes the narrow ENVELOPE receipt binding amendment
  (agent-harness#1818 precedent).
- MM-2: WORKER's reservation is the only attempt reservation; LANEEXEC keeps
  only `exec_claimed`.
- MM-3: a cancelled or timed-out attempt never returns any part of a patch.
- MM-4: openshell patch return stays closed until a remote audit and evidence
  contract exists.
- Audit scope: the promise is "tree and refs", with the object-store
  disclosure.
- `-n`: dropped everywhere, in all four phases.
- State root: production selection of a non-default root is digest-bound
  operator configuration, designed in LANEEXEC.

Existing code inspected:

- `run_bounded` is the shared seam. It caps each pipe at 64 KiB, discards
  stderr, uses DEVNULL stdin, holds the unreaped leader and kills its own
  group. It returns only `ConvergenceResultEnvelope`.
- `prepare_launch`/`consume_admission` give a process-local single-use token
  over `LaunchInputs`, whose argv excludes instructions.
- `output_retention.mark/prune` supply the evidence-retention discipline;
  `prune` records nothing after retiring a run, hence WORKER's ledger.
- `rfc8785` is already a locked dependency.
- The seat reference and agent-CLI scratch inventories classify every new
  launch and I/O site.
- ENVELOPE's receipt hash-binds `docs/supervised-worker.md`.

## External Inputs

- Frozen contract: `plans/artifacts/v12-WORKER-contract.md`, sealed by this
  manifest amendment row `v12-WORKER-amend-withheld`'s `frozen_inputs`
  digest (sha256:
  `d767939b5309091b80fae559e9ed37c45daa52521526ebc41c54c1426125ca08`). It holds every exact signature,
  ordering rule, proposal/audit/cancel rule, test obligation W1–W15, mutation
  list and the JOURNAL names consumed. Read it in full before any lane starts.
  This plan points at it and does not repeat it.
- Landed IF-0-ENVELOPE-1 symbols and IF-0-SCHEMA-1 receipt rows on main.
- IF-0-JOURNAL-1 as frozen by the roadmap and named by agent-harness#1925 §10.

No external commit, private schema or vector is consumed. The roadmap hash in
the frontmatter pins an input, never a future WORKER head.

## Interface Freeze Gates

- [ ] IF-0-WORKER-1 — The frozen artifact's §2–§6 surface, as follows.
  - `convergence/adapters/base.py` exports `CaptureRequest`, `StreamDigest`,
    `SpawnRefused`, `BoundedCapture`, `PROPOSAL_CAP_MAX`, `WORKER_ENV_DROP`,
    `WORKER_ENV_DROP_PREFIXES`, `worker_child_environment` and
    `run_bounded_capture`. `run_bounded` keeps its behavior.
  - `convergence/adapters/patch_return.py` exports `CANCEL_WAIT_SECONDS`,
    `WorkerSettings`, `WorkerAttemptIdentity`, `BaselineIdentity`,
    `ProposalReturn`, `JournalAnchor`, `WorkerResult`, `CancelOutcome`,
    `PRODUCTION_LAUNCHER_COMMANDS`, `default_state_root`, `evidence_resolver`,
    `run_patch_return` and `cancel_attempt`.
  - `codex.py` adds `run_codex_patch_return`.
  - `supervised_worker_cli.py` exports `main` (keyword-only `state_root` test
    seam), `STATUS_PAGE_SIZE`, `read_envelope_file`, `open_result_file` and
    `_production_codec`.
    `_production_codec` returns None until CLOSEOUT SL-2 wires it.
  - Evidence: `plans/evidence/supervised-worker/WORKER.md`.

Behavior is frozen only by artifact §2–§7 and accepted only against
EC-WORKER-1 to EC-WORKER-4. This plan does not restate either. Exit codes,
lifecycle enums and record labels stay provisional until public
reconciliation.

## Lane Index & Dependencies

SL-0 — Shared bounded capture seam and regressions
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Patch-return adapter and attempt lifecycle
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Isolated CLI, documentation and evidence reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Shared bounded capture seam and regressions

- **Scope**: Add the artifact §2 capture seam beside `run_bounded`, outside `ConvergenceResultEnvelope`, without changing any existing convergence caller.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`
- **Interfaces provided**: `CaptureRequest`, `StreamDigest`, `SpawnRefused`, `BoundedCapture`, `PROPOSAL_CAP_MAX`, `WORKER_ENV_DROP`, `WORKER_ENV_DROP_PREFIXES`, `worker_child_environment`, `run_bounded_capture`
- **Interfaces consumed**: `run_bounded`, `AdapterExecutionRequest`, `_child_environment`, `panel_invoker.launch_owned` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add W1–W3 to `test_convergence_adapters.py` using real offline
    subprocess providers. Cover:
    - streams over and under the cap, binary stdout and a large stderr flood;
    - EPIPE on stdin, and instruction sentinels absent from argv;
    - deadline expiry, the cancel event, a failed exec, and a `before_spawn`
      refusal checked with a spawn spy;
    - descendant group reclaim, and an escaped descendant holding a pipe past
      the deadline (`streams_complete=False`);
    - planted credential variables, and the empty default allowlist.
    Add W2 parity: each existing `run_bounded` status, detail and bound,
    unchanged. Add the SL-0 source-copy mutants from artifact §7.
  - impl: Implement §2 on `launch_owned` with execute-mode timing. Keep the
    existing `RUNTIME-RED-ANCHOR` cases and module imports intact. Any shared
    helper must leave `run_bounded` observably identical.
  - verify: V0 and V0-reg. Every mutant must turn a previously passing
    path-entered assertion red. The new launch site is classified by SL-2 on
    the same phase branch (Execution Notes), so the inventory tests are not
    run here.

### SL-1 — Patch-return adapter and attempt lifecycle

- **Scope**: Compose admission, JOURNAL reservation, audit, capture, proposal decision, evidence, ledger, retention and native cancel per artifact §3–§5 and §8.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py`, `phase-loop-runtime/tests/test_supervised_worker.py`, `phase-loop-runtime/tests/fixtures/supervised_worker_local/**`
- **Interfaces provided**: `CANCEL_WAIT_SECONDS`, `WorkerSettings`, `WorkerAttemptIdentity`, `BaselineIdentity`, `ProposalReturn`, `JournalAnchor`, `WorkerResult`, `CancelOutcome`, `PRODUCTION_LAUNCHER_COMMANDS`, `default_state_root`, `evidence_resolver`, `run_patch_return`, `cancel_attempt`, `run_codex_patch_return`
- **Interfaces consumed**: `CaptureRequest`, `BoundedCapture`, `SpawnRefused`, `worker_child_environment`, `run_bounded_capture`, `PROPOSAL_CAP_MAX`; `prepare_launch`, `consume_admission`, `classify_workspace`, `LaunchInputs`, `LaunchConfig`, `PreparedLaunch`, `trusted_bytes` (pre-existing); IF-0-JOURNAL-1 (upstream; artifact §8 names); `output_retention.mark`, `output_retention.prune`, `rfc8785.dumps` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add W4–W12 and W15 to `test_supervised_worker.py` through
    `run_patch_return` and `cancel_attempt`. Use the real JOURNAL writer,
    with faults injected only by wrapping it. Inject the synthetic codec and
    validator in process, and use labelled fixture providers.
    - Replay one envelope sequentially and from 4 concurrent processes. Kill a
      launcher between reservation and spawn and rerun the envelope. Retry
      under the same run with a new attempt id.
    - Cover Rule W at each writer call through injected `os.write`/`os.fsync`
      failures in the real writer, including a `running` append that lands and
      then fails. Cover a dropped `event_cap_reached` event.
    - Exercise every §3.2 row, each §3.3 scope and every pre-spawn recheck.
    - For cancel, start a real fixture launcher (admitted only through the
      in-process `launcher_commands` parameter) and race it in queued,
      running and terminal states. Repeat the cancel. Forge a record naming an
      unrelated same-user process and assert zero signals. Cover a stale owner.
    - Run the setsid escape test, which reaps its own escapee.
    - Assert the evidence events, ledger and resolver. Expire evidence through
      WORKER's prune and its injected clock, and check JOURNAL's
      `retention_dropped` page. Assert that an unrecorded deletion reads
      `unknown`.
    - Cover JCS digests of `caller_context`.
    - Check that `run_codex_patch_return` refuses a non-codex basename.
    Add the SL-1 mutants from artifact §7.
  - impl: Implement §3–§5. Do not edit ENVELOPE, JOURNAL, SCHEMA or retention
    modules. A JOURNAL name that differs from §8 stops the lane as
    `upstream_phase_unmet` pending an artifact amendment.
  - verify: V1. Kill every listed mutant through a production path. Record
    per-node outcomes and proof cost. Any node over roughly five minutes is
    flagged.

### SL-2 — Isolated CLI, documentation and evidence reducer

- **Scope**: Ship the isolated module CLI, classify every new site, document the integrated seam and record the receipt.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`, `phase-loop-runtime/tests/test_supervised_worker_cli.py`, `phase-loop-runtime/tests/test_supervised_worker_receipt.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `docs/supervised-worker.md`, `CHANGELOG.md`, `plans/evidence/supervised-worker/WORKER.md`, `plans/evidence/supervised-worker/ENVELOPE.md`, `plans/manifest.json`
- **Ownership limits**:
  - The inventory files are owned only for rows classifying WORKER's new launch
    and I/O sites; their rules and role sets stay unchanged.
  - `ENVELOPE.md` is owned only for the OQ-4 binding amendment: recompute its
    `docs/supervised-worker.md` source-hash row and derived
    `source_tree_digest`, and add one dated paragraph. Producer rows,
    outcomes, `ec_status`, `final_tree_validated` and authority stay
    unchanged.
  - `plans/manifest.json` is owned only for the `v12-WORKER` entry's lifecycle
    metadata.
- **Interfaces provided**: `main`, `STATUS_PAGE_SIZE`, `read_envelope_file`, `open_result_file`, `_production_codec`; `plans/evidence/supervised-worker/WORKER.md` (runner-stamped per-node outcomes, deferred obligations and source bindings)
- **Interfaces consumed**: `run_patch_return`, `cancel_attempt`, `default_state_root`, `evidence_resolver`, `PRODUCTION_LAUNCHER_COMMANDS`, `CANCEL_WAIT_SECONDS`, `WorkerResult`, `CancelOutcome`, `run_bounded_capture`; `preflight_supervised_route`, `Refused` (pre-existing); IF-0-JOURNAL-1 (upstream; artifact §8 names)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add W13 to `test_supervised_worker_cli.py`.
    - Subprocess `python -I -m` children cover only paths that end before
      state-root resolution: required-session refusals, `codec_unavailable`
      with zero probes and effects, usage, and the shadowed stdlib and
      validator modules in the workspace cwd. They never touch the real root.
    - In-process tests call `main(..., state_root=tmp)`:
      - CLI cancel against a live fixture launcher returns `owner_unverified`,
        with zero `pidfd_send_signal` calls and the launcher still running;
      - `status` prints `attempt_status`, with liveness, and an optional page
        that follows `next_cursor`;
      - envelope-file and result-file checks.
    Add W14 to `test_supervised_worker_receipt.py`. It validates WORKER.md
    against observed producer results. It derives the deferred-obligation set
    from SCHEMA's receipt and requires equality. It falsifies stale bindings,
    missing results and false authority after entering production. Add the
    SL-2 mutants.
  - impl:
    - Implement artifact §6.
    - Classify every WORKER site in both inventories.
    - Document in `docs/supervised-worker.md`: the seam, order and Rule W, the
      proposal table, the audit scope and object-store disclosure, cancel
      identity and the nonce disclosure, the state layout and ledger, the
      setsid limit, same-login journal/credential limits, the empty
      environment default, the descriptor-exec residual window and codec
      gating.
    - Add an Unreleased `CHANGELOG.md` entry.
    - Apply the ENVELOPE binding amendment.
    - Write WORKER.md with `authority: synthetic_fixture_only`, the 113
      deferred rows and the J1–J6 reconciliation. List as pending: public
      reconciliation, installed-tool qualification, registry activation and
      CLOSEOUT codec wiring.
    - Record the `v12-WORKER` lifecycle.
  - verify: V2, then the effective suite. Finalize only runner-stamped,
    actually observed results.

## Execution Notes

All lanes are sequential with disjoint ownership, and land together on one
phase branch. SL-0 and SL-1 add launch and I/O sites that only SL-2
classifies, so the inventory tests are required at the phase head, not after
each lane. No lane merges to main alone. No subagent, scheduler fanout or
worktree creation is authorized. New modules are auto-discovered: no
`__init__.py`, `pyproject.toml`, `uv.lock`, `MANIFEST.in` or console-script
change.

**Unchanged regression inputs:**

- `output_retention.py` and its test;
- all ENVELOPE, SCHEMA and JOURNAL modules;
- `executable_dependency_startup.py`;
- `cli.py`;
- the regression tests in V0-reg.

**Serial edges with later phases:**

- CLOSEOUT SL-1 owns `supervised_launch*.py` next, including the OQ-2 cap.
- CLOSEOUT SL-2 owns `base.py`, `codex.py`, `patch_return.py`,
  `supervised_worker_cli.py` (codec wiring) and the worker tests next.
- CLOSEOUT SL-3 owns `docs/supervised-worker.md` and `CHANGELOG.md` next.
- PLACECLI SL-3 and LANEEXEC SL-5 own the inventories and `CHANGELOG.md`
  later. Each rebases onto WORKER's rows.

Validator check (N) warns only because SL-2 owns `CHANGELOG.md`, a packaging
heuristic. This phase dispatches no release or tag, so no post-dispatch reducer
applies. Readiness needs CLOSEOUT's live required checks, Gate A, independent
board and president. Proxy evidence needs a roadmap amendment.

**Downstream amendments (recorded here; those plans are not edited).**

- CLOSEOUT:
  - (a) echo cases enter through WORKER's `caller_context_sha256` site and are
    compared by exact bytes, with mutations of `__proto__` loss and a changed
    number before hashing;
  - (b) add `test_supervised_worker_cli.py`, `test_supervised_worker_receipt.py`
    and JOURNAL's `test_run_status_receipt.py` to the sealed V2 group;
  - (c) SL-1 owns the executable cap; SL-2 owns codec wiring and the first
    end-to-end launch→cancel test with `PRODUCTION_LAUNCHER_COMMANDS`;
  - (d) keep the `supervised_contracts` allowlist once JOURNAL's fix lands;
  - (e) drop `-n`.
  - The activation path also needs CLOSEOUT SL-0–SL-2, because `launch`
    refuses `codec_unavailable` until then.
- PLACECLI:
  - drop `-n 0`;
  - narrow `OpaqueId` to 128 characters where ids reach the journal;
  - state that its reservation journal is a separate store.
- LANEEXEC:
  - (a) `x-exec.one_exec` claims only `exec_claimed`; WORKER reserves once.
    Map `attempt_reserved` and define the crash states between the two
    claims;
  - (b) `status` maps `unknown`, `stale_unknown`, `refused` and the finished
    displays;
  - (c) `cancel` maps `owner_unverified` to `cancel_pending` and handles
    `owner_not_live`. It runs on the launching host with the launcher's
    interpreter and exactly `PRODUCTION_LAUNCHER_COMMANDS`;
  - (d) C8: a cancelled or timed-out patch return is null, with termination
    unchanged;
  - (e) reject ids over 128 characters before the claim;
  - (f) keep openshell patch return closed;
  - (g) activation depends on CLOSEOUT SL-0–SL-2;
  - (h) select per-client state and journal roots through digest-bound trusted
    configuration;
  - (i) drop `-n 0`.

## Verification

These commands are for future execution and are not run by this planning PR.

**Shared-host rule.** Run individual files serially under `timeout 900` with
`-p no:cacheprovider` and never `-n` (owner ruling). Check `uptime` and
`/proc/pressure/io` before each command and stop if degraded. Full suites,
Gate A and CI stay hosted.

**Environment.** Use the locked Python 3.12+ environment with absolute
source/test PYTHONPATH (CONTRIBUTING.md).

**Collection.** After implementation, every owned test file must contribute
nodes. Exit 5, zero collection or skipped-only runs fail. Record per-node
outcomes, not collection counts.

- V0: `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_convergence_adapters.py`
- V0-reg: `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_convergence_runtime_imports.py phase-loop-runtime/tests/test_seat_executor_review.py phase-loop-runtime/tests/test_pr1161_r2_F002.py phase-loop-runtime/tests/test_runtime_adapter_output_720.py phase-loop-runtime/tests/test_sandbox_staging_1147.py phase-loop-runtime/tests/test_subscription_scrub_xai_864.py`
- V1: `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_output_retention.py`
- V2: `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker_cli.py phase-loop-runtime/tests/test_supervised_worker_receipt.py phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_supervised_launch_receipt.py`
- Effective suite: the frontmatter `automation.suite_command`, the union of
  V0, V1 and V2. V0-reg is a separate required command.

**Command validation.** Validate every command and the suite through IF-0-VC-2
(`verification_evidence.validate_verification_commands`) at intake. Missing
future files are expected pre-implementation findings and must be zero before
execution verification. Restore production sources after every mutant.

## Acceptance Criteria

- [ ] EC-WORKER-1 — proven by `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_supervised_worker.py`; falsified by path-entered source-copy mutants removing the proposal cap, the drain deadline bound, a §3.2 withholding row, an audit scope or the `run_bounded` parity bound in `run_bounded_capture`/`run_patch_return`.
- [ ] EC-WORKER-2 — proven by `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_supervised_worker_cli.py`; falsified by mutants reordering reservation after spawn, skipping a pre-spawn identity recheck, continuing to journal after a writer failure, dropping an evidence binding field or bypassing the `codec_unavailable` gate, each entering `run_patch_return` or `main`.
- [ ] EC-WORKER-3 — proven by `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_supervised_worker_cli.py`; falsified by mutants removing each `cancel_attempt` identity check or the pidfd target, observed as a signal to a forged or fixture launcher, or by re-keying launcher records so a same-run retry is refused.
- [ ] EC-WORKER-4 — proven by `timeout 900 python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_supervised_worker_cli.py phase-loop-runtime/tests/test_supervised_worker_receipt.py` plus V0-reg; falsified by any surviving artifact §7 mutant in `run_bounded_capture`, `run_patch_return`, `cancel_attempt` or `main`, a skipped-only owned file, or a receipt claiming authority, qualification or resolution of a deferred SCHEMA row.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-worker.md`, `CHANGELOG.md`
- evidence paths: `plans/evidence/supervised-worker/WORKER.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing or malformed evidence routes to `contract_bug` with
`human_required=false`. Missing or renamed JOURNAL names route to
`upstream_phase_unmet`.
