---
phase_loop_plan_version: 1
phase: WORKER
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5
automation:
  suite_command: ["timeout", "900", "python3", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "phase-loop-runtime/tests/test_convergence_adapters.py", "phase-loop-runtime/tests/test_supervised_worker.py", "phase-loop-runtime/tests/test_supervised_worker_cli.py", "phase-loop-runtime/tests/test_supervised_worker_receipt.py", "phase-loop-runtime/tests/test_output_retention.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_supervised_launch_receipt.py"]
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
  being written in parallel.
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
- JOURNAL's landed API reconciled with requirements J1–J6 in the frozen
  artifact. A mismatch requires a WORKER plan/artifact amendment before work,
  never an in-lane workaround.

Existing code inspected:

- `run_bounded` is the shared seam. It caps each pipe at 64 KiB, discards
  stderr, uses DEVNULL stdin, holds the unreaped leader and kills its own
  group. It returns only `ConvergenceResultEnvelope`.
- `prepare_launch`/`consume_admission` give a process-local single-use token
  over `LaunchInputs`, whose argv excludes instructions.
- `output_retention.mark/prune` supply the evidence-retention discipline.
- The seat reference and agent-CLI scratch inventories classify every new
  launch and I/O site.
- ENVELOPE's receipt hash-binds `docs/supervised-worker.md`.

## External Inputs

- Frozen contract: `plans/artifacts/v12-WORKER-contract.md`, sealed by this
  plan's manifest `frozen_inputs` digest. It holds every exact signature,
  ordering rule, proposal/audit/cancel rule, test obligation W1–W14, mutation
  list and JOURNAL requirement. Read it in full before any lane starts. This
  plan points at it and does not repeat it.
- Landed IF-0-ENVELOPE-1 symbols and IF-0-SCHEMA-1 receipt rows on main.
- IF-0-JOURNAL-1 as frozen by the roadmap.

No external commit, private schema or vector is consumed. The roadmap hash in
the frontmatter pins an input, never a future WORKER head.

## Interface Freeze Gates

- [ ] IF-0-WORKER-1 — The frozen artifact's §2–§6 surface, as follows.
  - `convergence/adapters/base.py` exports `CaptureRequest`, `StreamDigest`,
    `SpawnRefused`, `BoundedCapture`, `PROPOSAL_CAP_MAX`, `WORKER_ENV_DROP`,
    `WORKER_ENV_DROP_PREFIXES`, `worker_child_environment` and
    `run_bounded_capture`. `run_bounded` keeps its behavior.
  - `convergence/adapters/patch_return.py` exports `WorkerSettings`,
    `WorkerAttemptIdentity`, `BaselineIdentity`, `ProposalReturn`,
    `JournalAnchor`, `WorkerResult`, `CancelOutcome`,
    `PRODUCTION_LAUNCHER_COMMANDS`, `default_state_root`, `run_patch_return`
    and `cancel_attempt`.
  - `codex.py` adds `run_codex_patch_return`.
  - `supervised_worker_cli.py` exports `main`, `read_envelope_file`,
    `open_result_file` and `_production_codec` (None until CLOSEOUT).
  - Evidence: `plans/evidence/supervised-worker/WORKER.md`.

Frozen decisions the lanes must not reinterpret:

- **Proposal channel.** The proposal is the admitted chain's stdout. It is
  bounded by an operator-lowerable cap with a 64 MiB ceiling and digested in
  full; stderr is digested and never retained.
- **Order.** Admission is consumed, then a durable JOURNAL reservation, then
  audit and pre-spawn identity recheck, then `running` is journaled
  immediately before the spawn. Refusals happen only before start. Spawn
  failure is finished/`failed_to_start`.
- **Returned proposals.** Only completed, exit-0, in-cap, audit-clean,
  structurally valid proposals return. Every other case is a named
  withholding.
- **Cancel.** Cancel signals only a pidfd of a launcher verified by pid,
  start time, interpreter, cmdline, record lock and nonce/writer-instance
  match.
- **CLI launch.** It refuses `codec_unavailable` before any effect until
  CLOSEOUT wires the public codec.

Exit codes, lifecycle enums and record labels stay provisional until public
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
    subprocess providers. Cover streams over and under the cap, binary stdout,
    a large stderr flood, EPIPE on stdin and instruction sentinels absent from
    argv. Cover deadline expiry, the cancel event, a failed exec and a
    `before_spawn` refusal with a spawn spy. Cover descendant group reclaim and
    planted credential variables. Add W2 parity: each existing `run_bounded`
    status, detail and bound, unchanged. Add the SL-0 source-copy mutants from
    artifact §7.
  - impl: Implement §2 on `launch_owned` with execute-mode timing. Keep the
    existing `RUNTIME-RED-ANCHOR` cases and module imports intact. Any shared
    helper must leave `run_bounded` observably identical.
  - verify: V0 and V0-reg. Every mutant must turn a previously passing
    path-entered assertion red. Inventory tests are expected to stay red for
    the new site until SL-2 classifies it; they are not run here.

### SL-1 — Patch-return adapter and attempt lifecycle

- **Scope**: Compose admission, JOURNAL reservation, audit, capture, proposal decision, evidence, retention and native cancel per artifact §3–§5.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py`, `phase-loop-runtime/tests/test_supervised_worker.py`, `phase-loop-runtime/tests/fixtures/supervised_worker_local/**`
- **Interfaces provided**: `WorkerSettings`, `WorkerAttemptIdentity`, `BaselineIdentity`, `ProposalReturn`, `JournalAnchor`, `WorkerResult`, `CancelOutcome`, `PRODUCTION_LAUNCHER_COMMANDS`, `default_state_root`, `run_patch_return`, `cancel_attempt`, `run_codex_patch_return`
- **Interfaces consumed**: `CaptureRequest`, `BoundedCapture`, `SpawnRefused`, `worker_child_environment`, `run_bounded_capture`, `PROPOSAL_CAP_MAX`; `prepare_launch`, `consume_admission`, `classify_workspace`, `LaunchInputs`, `LaunchConfig`, `PreparedLaunch` (pre-existing); IF-0-JOURNAL-1 (upstream); `output_retention.mark`, `output_retention.prune` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add W4–W12 to `test_supervised_worker.py` through
    `run_patch_return` and `cancel_attempt`. Use real JOURNAL writers, the
    synthetic codec and validator injected in process, and labelled fixture
    providers.
    - Replay one envelope sequentially and from 4 concurrent processes. Kill a
      launcher between reservation and spawn and rerun the envelope. Assert at
      most one spawn in total.
    - Force reservation failure through filesystem state, not a mock.
    - Exercise every §3.2 row, each §3.3 scope and every pre-spawn recheck.
    - For cancel, start a real fixture launcher (admitted only through the
      in-process `launcher_commands` parameter) and race it in queued,
      running and terminal states. Repeat the cancel. Forge a record naming an
      unrelated same-user process and assert zero signals. Cover a stale owner.
    - Run the setsid escape test, which reaps its own escapee.
    - Expire evidence through prune's injected clock and check JOURNAL's
      `retention_dropped` page.
    - Check that `run_codex_patch_return` refuses a non-codex basename.
    Add the SL-1 mutants from artifact §7.
  - impl: Implement §3–§5. Do not edit ENVELOPE, JOURNAL, SCHEMA or retention
    modules. Missing JOURNAL capabilities J1–J6 stop the lane as
    `upstream_phase_unmet`.
  - verify: V1. Kill every listed mutant through a production path. Record
    per-node outcomes and proof cost. Any node over roughly five minutes is
    flagged.

### SL-2 — Isolated CLI, documentation and evidence reducer

- **Scope**: Ship the isolated module CLI, classify every new site, document the integrated seam and record the receipt.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`, `phase-loop-runtime/tests/test_supervised_worker_cli.py`, `phase-loop-runtime/tests/test_supervised_worker_receipt.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `docs/supervised-worker.md`, `CHANGELOG.md`, `plans/evidence/supervised-worker/WORKER.md`, `plans/evidence/supervised-worker/ENVELOPE.md`
- **Ownership limits**:
  - The inventory files are owned only for rows classifying WORKER's new launch
    and I/O sites; their rules and role sets stay unchanged.
  - `ENVELOPE.md` is owned only for a binding amendment: recompute its
    `docs/supervised-worker.md` source-hash row and derived
    `source_tree_digest`, and add one dated paragraph. Producer rows,
    outcomes, `ec_status`, `final_tree_validated` and authority stay
    unchanged. This follows the agent-harness#1818 binding-amendment
    precedent.
- **Interfaces provided**: `main`, `read_envelope_file`, `open_result_file`, `_production_codec`; `plans/evidence/supervised-worker/WORKER.md` (runner-stamped per-node outcomes, deferred obligations and source bindings)
- **Interfaces consumed**: `run_patch_return`, `cancel_attempt`, `default_state_root`, `PRODUCTION_LAUNCHER_COMMANDS`, `WorkerResult`, `CancelOutcome`, `run_bounded_capture`; `preflight_supervised_route`, `Refused` (pre-existing); IF-0-JOURNAL-1 (upstream)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add W13 to `test_supervised_worker_cli.py` with installed-style
    `python -I -m` children:
    - required-session launch and cancel refuse before reads;
    - `codec_unavailable` with spies on envelope, binding, journal, evidence
      and result effects, and zero probes and spawns;
    - status is provider-free;
    - shadowed stdlib and validator modules in the workspace cwd do not load;
    - envelope owner, mode, symlink, size and inline-instruction read-mode
      refusals;
    - result O_EXCL, 0600, no-follow and outside roots;
    - CLI cancel rejects a fixture launcher and returns `unknown_attempt`.
    Add W14 to `test_supervised_worker_receipt.py`. It validates WORKER.md
    against observed producer results. It derives the deferred-obligation set
    from SCHEMA's receipt and requires equality. It falsifies stale bindings,
    missing results and false authority after entering production. Add the
    SL-2 mutants.
  - impl:
    - Implement artifact §6.
    - Classify every WORKER site in both inventories.
    - Document in `docs/supervised-worker.md`: the seam, order, proposal
      table, audit scope and `.git/objects` exclusion, cancel identity,
      state layout, the setsid limit, same-login journal/credential limits,
      the descriptor-exec residual window and codec gating.
    - Add an Unreleased `CHANGELOG.md` entry.
    - Apply the ENVELOPE binding amendment.
    - Write WORKER.md with `authority: synthetic_fixture_only`, the 113
      deferred rows, J1–J6 reconciliation and the pending items: public
      reconciliation, installed-tool qualification, registry activation and
      CLOSEOUT codec wiring.
  - verify: V2, then the effective suite. Finalize only runner-stamped,
    actually observed results.

## Execution Notes

All lanes are sequential with disjoint ownership. No subagent, scheduler fanout
or worktree creation is authorized. New modules are auto-discovered: no
`__init__.py`, `pyproject.toml`, `uv.lock`, `MANIFEST.in` or console-script
change.

**Unchanged regression inputs:**

- `output_retention.py` and its test;
- all ENVELOPE, SCHEMA and JOURNAL modules;
- `executable_dependency_startup.py`;
- `cli.py`;
- the regression tests in V0-reg.

**Serial edges with later phases:**

- CLOSEOUT SL-1/SL-2 own `supervised_launch*.py`, `base.py`, `codex.py`,
  `patch_return.py`, `supervised_worker_cli.py`, the worker tests and
  `docs/supervised-worker.md` next.
- PLACECLI SL-3 and LANEEXEC SL-5 own the inventories and `CHANGELOG.md`
  later.
- Each starts only after WORKER lands and must rebase onto WORKER's rows.

Validator check (N) warns only because SL-2 owns `CHANGELOG.md`, a packaging
heuristic. This phase dispatches no release or tag, so no post-dispatch reducer
applies. Readiness
needs CLOSEOUT's live required checks, Gate A, independent board and
president. Proxy evidence needs a roadmap amendment.

**Open questions (recorded, not resolved here):**

- OQ-1: The cross-cutting rule "never ambient environment" conflicts with the
  WORKER note "use base scrubbers". The child environment here is the scrubbed
  launcher environment narrowed by the trusted `worker_environment_allow`.
  Admission binding of the environment arrives only with CLOSEOUT's v2
  classified environment.
- OQ-2: ENVELOPE's 1 MiB executable capture cap and its refusal of symlinked
  executables block typical installed provider binaries. WORKER must not edit
  `supervised_launch.py`, so the owner should assign this to CLOSEOUT SL-1,
  its next owner.
- OQ-3: The roadmap never names the proposal channel. Stdout was chosen
  because the roadmap motivates the transport by `run_bounded`'s output cap.
  A tree-diff proposal would be an amendment.
- OQ-4: Editing `docs/supervised-worker.md` forces the ENVELOPE receipt
  binding amendment. The owner may prefer a different route.

**Consumer mismatches (PLACECLI, LANEEXEC, CLOSEOUT):**

- MM-1: The launch path is WORKER, JOURNAL, PLACECLI, LANEEXEC, but it is
  insufficient. Under EC-WORKER-2 the production `launch` refuses
  `codec_unavailable` until CLOSEOUT wires the pinned codec. LANEEXEC's
  `x-envelope-construction` also builds v2 envelopes through `prepare_launch`,
  which needs CLOSEOUT SL-1's `prepare_launch_v2`. Real launches therefore
  also need CLOSEOUT SL-0–SL-2.
- MM-2: LANEEXEC `x-exec.one_exec` reserves the attempt through the v12
  journal at exec claim. WORKER then reserves again, as EC-WORKER-2 requires,
  and EC-JOURNAL-3 forbids that reuse, so every placed launch would refuse.
  LANEEXEC's artifact must drop its own reservation or delegate the claim to
  WORKER's.
- MM-3: LANEEXEC C8 expects a return on cancelled or timed-out attempts.
  WORKER withholds such patches as `withheld_incomplete`, so LANEEXEC's patch
  return must be null with the termination unchanged.
- MM-4: On LANEEXEC's openshell route the execution tree is remote, and
  WORKER's audit sees only the local workspace and target.
- MM-5: CLOSEOUT's sealed V2 group names `test_supervised_worker.py` but not
  `test_supervised_worker_cli.py` or `test_supervised_worker_receipt.py`.
  CLOSEOUT needs the input amendment its Execution Notes anticipate.
- MM-6 (compatible): LANEEXEC's 64 MiB patch cap equals
  `PROPOSAL_CAP_MAX`. pi-runner uses `result_kind none`, so on the toolkit
  path WORKER's role is launch, status, cancel, reservation, lifecycle and
  evidence. WORKER adds no CLI registry, so PLACECLI's packaging assumption
  holds.

## Verification

These commands are for future execution and are not run by this planning PR.

**Shared-host rule.** Run individual files serially under `timeout 900` with
`-n 0 -p no:cacheprovider`. Check `uptime` and `/proc/pressure/io` before each
command and stop if degraded. Full suites, Gate A and CI stay hosted.
`-n 0` needs pytest-xdist, which CI pins at 3.8.0 but the locked dev
environment lacks. Where it is absent, omit `-n 0`: pytest runs serially by
default.

**Environment.** Use the locked Python 3.12+ environment with absolute
source/test PYTHONPATH (CONTRIBUTING.md).

**Collection.** After implementation, every owned test file must contribute
nodes. Exit 5, zero collection or skipped-only runs fail. Record per-node
outcomes, not collection counts.

- V0: `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_convergence_adapters.py`
- V0-reg: `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_convergence_runtime_imports.py phase-loop-runtime/tests/test_seat_executor_review.py phase-loop-runtime/tests/test_pr1161_r2_F002.py phase-loop-runtime/tests/test_runtime_adapter_output_720.py phase-loop-runtime/tests/test_sandbox_staging_1147.py phase-loop-runtime/tests/test_subscription_scrub_xai_864.py`
- V1: `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_output_retention.py`
- V2: `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker_cli.py phase-loop-runtime/tests/test_supervised_worker_receipt.py phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_supervised_launch_receipt.py`
- Effective suite: the frontmatter `automation.suite_command`, the union of
  V0, V1 and V2. V0-reg is a separate required command.

**Command validation.** Validate every command and the suite through IF-0-VC-2
(`verification_evidence.validate_verification_commands`) at intake. Missing
future files are expected pre-implementation findings and must be zero before
execution verification. Restore production sources after every mutant.

## Acceptance Criteria

- [ ] EC-WORKER-1 — proven by `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_supervised_worker.py`; falsified by path-entered source-copy mutants removing the proposal cap, a §3.2 withholding row, an audit scope or the `run_bounded` parity bound in `run_bounded_capture`/`run_patch_return`.
- [ ] EC-WORKER-2 — proven by `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_supervised_worker_cli.py`; falsified by mutants reordering reservation after spawn, skipping a pre-spawn identity recheck, dropping an evidence binding field or bypassing the `codec_unavailable` gate, each entering `run_patch_return` or `main`.
- [ ] EC-WORKER-3 — proven by `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_worker.py`; falsified by mutants removing each `cancel_attempt` identity check or the pidfd target, observed as a signal to a forged unrelated process.
- [ ] EC-WORKER-4 — proven by `timeout 900 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_supervised_worker_cli.py phase-loop-runtime/tests/test_supervised_worker_receipt.py` plus V0-reg; falsified by any surviving artifact §7 mutant in `run_bounded_capture`, `run_patch_return`, `cancel_attempt` or `main`, a skipped-only owned file, or a receipt claiming authority, qualification or resolution of a deferred SCHEMA row.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-worker.md`, `CHANGELOG.md`
- evidence paths: `plans/evidence/supervised-worker/WORKER.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing or malformed evidence routes to `contract_bug` with
`human_required=false`. Missing JOURNAL capabilities route to
`upstream_phase_unmet`.
