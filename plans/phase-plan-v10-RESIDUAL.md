---
phase_loop_plan_version: 1
phase: RESIDUAL
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - env
    - PHASE_LOOP_TDD_EXPECT_RESIDUAL=1
    - PYTHONPATH=phase-loop-runtime/src
    - python3
    - -m
    - pytest
    - -q
    - phase-loop-runtime/tests
    - -m
    - not dotfiles_integration
    - -k
    - not residual_publish_identity_includes_base
---

# RESIDUAL: Broker, Train, and Channel Residuals

## Context

Canonical `.phase-loop/` state records RESIDUAL as `planned` after the
contract-bug reopen; legacy `.codex/phase-loop/` files are compatibility
artifacts only. The roadmap bytes match the frontmatter digest. Planning does
not prove the FABPUB dependency complete: execution must recheck the canonical
ledger and fail `upstream_phase_unmet` if that prerequisite is absent.

The immutable tests-only branch already carries the eight
`TestResidualInvariants` falsifiers. EC-RESIDUAL-1 is a roadmap-declared
deferred carry, not executable work: the parked agent-harness#368 four-argument
publish-key migration is excluded, durable base-free broker evidence is
preserved, and its activated falsifier remains an expected RED sentinel outside
the passing suite. The active implementation scope is EC-RESIDUAL-2 through
EC-RESIDUAL-7 plus the chronology proof required by EC-RESIDUAL-0.

The frozen tests record 45 F841 diagnostics across 31 files. That exact
execution-base inventory, rather than the historical “28 findings” label,
drives lane ownership and the per-finding triage reducer.

RESIDUAL's internal lanes are disjoint, but several owned paths overlap earlier
v10 phases. Before any writer dispatch, the coordinator must prove that active
SCHED, HARDEN, REVIEWTRUTH, and LEGLIFE exact-head work no longer owns the
selected paths. In particular, `panel_invoker.py` remains read-only until the
HARDEN completion review and agent-harness#733 disposition have landed on the
execution base. Any later upstream landing requires rebase, inventory
re-derivation, plan revalidation, and a fresh exact-head plan review.

## Interface Freeze Gates

- [ ] IF-0-RESIDUAL-1 — Train closure with publish identity held fixed.
  `publish_committed_branch_idempotency_key(repo, branch, head_sha)` and the
  base-free `EvidenceRecord` remain unchanged under the EC-RESIDUAL-1 deferred
  carry. On `pr_open` resume, an exception or unavailable live head produces one
  durable typed blocked result and never falls back to the ledger head or
  escapes `run_train`. A successful non-FAB `gh pr merge` with a null immediate
  merge OID enters the existing queue membership, bounded terminal poll,
  dequeue, and loud-unreconciled path before a terminal ledger result; enqueue
  omits `--delete-branch`.

- [ ] IF-0-RESIDUAL-2 — Hotfix and repair closure. Each scalar or list-item
  `verification_command` is shell-free argv; unquoted `;`, `&&`, `||`, `|`,
  `<`, `>`, and newline chaining are refused before execution or passing
  artifacts. A runner-owned atomic `repair_lineage.v1` lease under
  `.phase-loop/` binds repository, roadmap digest, phase, root work unit, owner
  process, and depth one. Live same-lineage repair/resume refuses recursion,
  stale lineage recovers, an interrupted no-diff repair preserves the
  byte-identical trusted terminal, and any child write invalidates that trust.

- [ ] IF-0-RESIDUAL-3 — Channel model provenance closure.
  `SessionRegistryRecord` carries normalized metadata-only actual model and
  binding state. `ChannelSidecarClient.preflight(expected_model=...)` refuses an
  absent actual model as `session_model_unbound` and a mismatch as
  `session_model_mismatch` before delivery. Launch metadata, event metadata,
  `WorkUnitMetric`, JSON/text status, aggregate metrics, and TUI handoff carry
  intended model, verified actual model when present, binding state, and caveat;
  an unbound intended model is never counted as verified in `by_model`.
  Command-adapter templates without `{model}` remain explicitly unbound.

- [ ] IF-0-RESIDUAL-4 — Chronology and F841 closure.
  `validate_chronology` derives test-before-implementation ancestry from Git
  commit identities and rejects caller-supplied truth. The governed-premerge
  early-block/structural-hold sequence resolves to `non_convergence`. All 45
  frozen F841 rows across 31 files receive a fixed or individually justified
  disposition; the resulting inventory is empty with no config, exclusion, or
  `noqa` concealment. Canonical validator source is edited once and both
  generated bundle layers are regenerated. `ruff.toml` and the existing pinned
  CI lint step enforce config-driven F841.

## Lane Index & Dependencies

SL-0 — Immutable tests-only boundary
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Train resume and non-FAB merge queue
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: yes

SL-2 — Hotfix and repair-lineage safety
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Channel provenance, chronology, and F841 retirement
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Documentation decision and evidence reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: SL-5
  Parallel-safe: no

SL-5 — Documentation and whole-phase verification
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: (none)
  Parallel-safe: no

The three writer lanes are disjoint. They may fan out only after the coordinator
machine-validates ownership and assigns isolated worktrees to the selected
single-vendor harness. Reducer and verifier nodes never join a writer wave.

## Lanes

### SL-0 — Immutable tests-only boundary

- **Scope**: Authenticate the already-landed RED boundary and make it read-only for implementation.
- **Owned files**: none
- **Interfaces provided**: `RESIDUAL_RED_SUITE`, tests-only chronology input, exact 45-row/31-file F841 inventory
- **Interfaces consumed**: `phase-loop-runtime/tests/test_train_invariants.py` (pre-existing), canonical Git history, roadmap EC-RESIDUAL-0 through EC-RESIDUAL-7
- **Parallel-safe**: no
- **Tasks**:
  - test: Confirm the test file is committed before any production change, was reviewed and observed default-GREEN/activated-RED, and remains absent from every implementation diff.
  - test: Treat `residual_publish_identity_includes_base` as the expected-RED deferred sentinel. Do not make it GREEN, include it in the active suite, or edit its production targets.
  - verify: Before writer dispatch, run the seven active node IDs individually against the pre-implementation base and retain raw/JUnit RED evidence with every named production seam entered.
  - verify: Fail closed if the test file is dirty, its frozen marker inventory drifted, or any production edit already precedes its authenticated landing.

### SL-1 — Train resume and non-FAB merge queue

- **Scope**: Close typed `pr_open` live-head failures and general null-OID queue reconciliation without changing broker publish identity.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/tests/test_convergence_broker_admission.py`, `phase-loop-runtime/tests/test_convergence_broker_verbs.py`, `phase-loop-runtime/tests/test_fab_activation_promotion.py`, `phase-loop-runtime/tests/test_fab_closeout_crash_safety.py`, `phase-loop-runtime/tests/test_fab_delta_consumer.py`, `phase-loop-runtime/tests/test_fab_flag_off_recovery_leak_299.py`, `phase-loop-runtime/tests/test_fabpub_shared_epoch.py`, `phase-loop-runtime/tests/test_fabreadmit_broker.py`, `phase-loop-runtime/tests/test_train_merge.py`, `phase-loop-runtime/tests/test_train_order_only_deps_47.py`, `phase-loop-runtime/tests/test_train_roadmap.py`, `phase-loop-runtime/tests/test_train_runner.py`
- **Interfaces provided**: `RESIDUAL_TRAIN_CLOSURE`, typed resume blocker, queue-bound terminal reconciliation
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, status-quo three-argument publish identity (pre-existing), existing queue membership/dequeue/re-gate primitives
- **Parallel-safe**: yes, only in its coordinator-assigned worktree beside SL-2 and SL-3
- **Tasks**:
  - test: Make only the EC-RESIDUAL-2 and EC-RESIDUAL-3 active falsifiers GREEN without editing SL-0.
  - impl: Catch live-head callback exceptions and unavailable results on `pr_open` resume, append one blocked ledger row with stable typed reason and node identity, and return the established blocked result before merge. Preserve successful resume and out-of-band-head detection.
  - impl: Generalize the existing queue-bound post-merge path to non-FAB nodes. Omit `--delete-branch` on enqueue; preserve terminal-first race handling, GraphQL membership, bounded polling, dequeue confirmation, and loud unreconciled halt. FAB provenance/re-gating remains additive only when a FAB run ID exists.
  - impl: Resolve this lane's frozen F841 rows individually without deleting load-bearing calls. Do not modify broker contracts, evidence schemas, admission, or publish-key code for EC-RESIDUAL-1.
  - verify: Run the two active lane node IDs, then the owned broker/train regression modules.

### SL-2 — Hotfix and repair-lineage safety

- **Scope**: Refuse shell control syntax and prevent recursive repair or interruption from degrading trusted closeout evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_hotfix_lane.py`, `phase-loop-runtime/tests/test_phase_loop_repair_precondition_planned_closeout.py`, `phase-loop-runtime/tests/test_phase_loop_runner.py`
- **Interfaces provided**: `RESIDUAL_HOTFIX_REPAIR_CLOSURE`, shell-operator refusal, `repair_lineage.v1`, trusted-terminal invalidation rule
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, canonical `.phase-loop/` paths (pre-existing), event and terminal-summary precedence
- **Parallel-safe**: yes, only in its coordinator-assigned worktree beside SL-1 and SL-3
- **Tasks**:
  - test: Make only the EC-RESIDUAL-4 and EC-RESIDUAL-6 active falsifiers GREEN without editing SL-0.
  - impl: Tokenize every hotfix scalar/list item with punctuation awareness and reject control operators/redirections before `run_verification`; never use `shell=True`, and preserve quoted literal tokens and separate safe list items.
  - impl: Acquire the atomic lineage lease before repair launch; refuse live same-scope repair or resume at depth one; carry lineage through launch metadata and prompt; retain stale evidence while recovering a dead owner.
  - impl: Preserve a previously authenticated `awaiting_phase_closeout`/`passed` terminal only for interrupted no-diff repair coordination. Invalidate it after any child write and for ordinary execute failure.
  - impl: Resolve this lane's frozen F841 rows individually while preserving dispatch behavior.
  - verify: Run the two active lane node IDs and the owned hotfix/runner regression modules.

### SL-3 — Channel provenance, chronology, and F841 retirement

- **Scope**: Bind or caveat session models, implement Git-derived chronology, repair attribution, and retire all remaining F841 rows.
- **Owned files**: `phase-loop-runtime/scripts/_gate_a_probe.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/handoff.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/models.py`, `phase-loop-runtime/src/phase_loop_runtime/observability.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/render.py`, `phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/harness-capability-matrix.md`, `phase-loop-runtime/tests/proofgate_bootstrap_verifier.py`, `phase-loop-runtime/tests/test_injection_skill_failloud.py`, `phase-loop-runtime/tests/test_legible_evidence.py`, `phase-loop-runtime/tests/test_model_tier_taxonomy.py`, `phase-loop-runtime/tests/test_phase_loop_claude_channel_*.py`, `phase-loop-runtime/tests/test_phase_loop_claude_route_selection.py`, `phase-loop-runtime/tests/test_phase_loop_handoff.py`, `phase-loop-runtime/tests/test_phase_loop_launcher.py`, `phase-loop-runtime/tests/test_phase_loop_metrics.py`, `phase-loop-runtime/tests/test_phase_loop_models.py`, `phase-loop-runtime/tests/test_phase_loop_state.py`, `phase-loop-runtime/tests/test_phase_worktree_executor.py`, `phase-loop-runtime/tests/test_release_dispatch_operator_approval_145.py`, `phase-loop-runtime/tests/test_roadmap_ownership.py`, `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-skills/plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/claude-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/codex-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/gemini-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/opencode-plan-phase/scripts/validate_plan_doc.py`, `ruff.toml`, `.github/workflows/test.yml`
- **Interfaces provided**: `RESIDUAL_CHANNEL_CHRONOLOGY_F841_CLOSURE`, verified/unbound model provenance, Git-derived chronology, empty unsuppressed F841 inventory
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, current session registry/client and launch-metric-status flow, exact frozen F841 inventory
- **Parallel-safe**: yes, only in its coordinator-assigned worktree beside SL-1 and SL-2
- **Tasks**:
  - test: Make the EC-RESIDUAL-5 and chronology/attribution portions of EC-RESIDUAL-0 GREEN without editing SL-0.
  - impl: Add actual-model metadata and expected-model preflight to the sidecar. Refuse absent/mismatched sessions before `send_and_wait`; preserve matching delivery.
  - impl: Thread intended/actual/binding/caveat fields through launch, event, metric, aggregate, status, and handoff surfaces. Bound models count in `by_model`; unbound intended models do not. Keep command adapters without `{model}` explicitly unbound.
  - impl: Extend `validate_chronology` with Git-derived tests-landing and implementation-base identities, reject the legacy caller boolean, and fix `seen_block` attribution so an earlier substantive block survives a later structural hold as `non_convergence`.
  - impl: Fix or individually justify every remaining frozen F841 row. Edit `panel_invoker.py` only after the HARDEN/agent-harness#733 interlock above is satisfied. Edit the canonical validator source once, regenerate neutral and packaged copies, remove F841 suppression from `ruff.toml`, and update the existing pinned CI lint comment without adding a second job.
  - verify: Run the active channel and chronology node IDs, channel/metric/status regressions, canonical skill parity, documentation checks, and isolated no-suppression F841 inventory.

### SL-4 — Documentation decision and evidence reducer

- **Scope**: Reduce every producer result into exact-head metadata-only triage and closeout evidence.
- **Owned files**: `plans/evidence/v10-RESIDUAL-f841-triage.md`, `plans/evidence/v10-RESIDUAL-closeout.json`
- **Interfaces provided**: `RESIDUAL_CLOSEOUT_EVIDENCE`
- **Interfaces consumed**: `RESIDUAL_RED_SUITE`, `RESIDUAL_TRAIN_CLOSURE`, `RESIDUAL_HOTFIX_REPAIR_CLOSURE`, `RESIDUAL_CHANNEL_CHRONOLOGY_F841_CLOSURE`, exact staged diff and verification outputs
- **Parallel-safe**: no
- **Tasks**:
  - test: Consume the frozen reducer assertions; never edit SL-0.
  - impl: Record all 45 frozen F841 rows with path/symbol/baseline location and an individual fixed/justified disposition, plus proof that the final inventory is empty and unsuppressed.
  - impl: Write closeout evidence with roadmap/plan digests, derived test/implementation chronology, raw/JUnit command references and hashes, issue-qualified dispositions, produced gates, and the explicit EC-RESIDUAL-1 deferred-carry result. Never claim agent-harness#368 closed.
  - impl: Record `no_doc_delta`: the phase changes internal runtime behavior and evidence only, so README, CHANGELOG, and release notes remain unchanged.
  - verify: Validate reducer schemas and digests against the exact staged tree. Any reducer edit invalidates prior final verification.

### SL-5 — Documentation and whole-phase verification

- **Scope**: Verify the no-doc-delta decision and exact reduced candidate without writing repository files.
- **Owned files**: none
- **Interfaces provided**: `RESIDUAL_VERIFIED_CANDIDATE`
- **Interfaces consumed**: `RESIDUAL_CLOSEOUT_EVIDENCE`, all four IF-0-RESIDUAL gates, exact staged tree
- **Parallel-safe**: no
- **Tasks**:
  - test: Run the resolved frontmatter suite and every Verification command.
  - impl: none; report drift or failures to the owning lane.
  - verify: Require passing active falsifiers, the expected-RED EC-RESIDUAL-1 sentinel, full regressions, empty unsuppressed F841, canonical bundle parity, docs freshness, plan/roadmap validation, and `git diff --check`.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`max`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`roadmap`
- SL-4: work-unit=`phase_reducer`, effort=`max`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`phase-plan`
- SL-5: work-unit=`phase_verify`, effort=`max`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`phase-plan`

Policy precedence is CLI/operator override, this phase plan, roadmap policy,
`Dispatch Hints`, then registry defaults. The coordinator retains one explicit
whole-phase author vendor; silent downgrade is forbidden.

## Execution Notes

Execution waits for canonical FABPUB completion and for the cross-phase
single-writer interlock in Context to pass. SL-0 authenticates the already
landed tests-only boundary and grants no write ownership. SL-1 through SL-3 may
then run as a machine-validated same-vendor writer wave in assigned worktrees;
SL-4 reduces only after all producers and SL-5 verifies only after the reducer.
The phase-owned set is the union of writable lanes, not `.phase-loop/` runtime
artifacts. Release, publication, merge, issue mutation, and the
agent-harness#368 publish-identity design remain outside this plan.

The activated suite excludes only
`residual_publish_identity_includes_base`. That test must stay default-GREEN and
activated-RED with its exact named marker, proving the deferred obligation is
retained while the executable criteria can pass.

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-RESIDUAL.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k "not residual_publish_identity_includes_base"`
- `PYTHONPATH=phase-loop-runtime/src python3 -c "import os,subprocess; env={**os.environ,'PHASE_LOOP_TDD_EXPECT_RESIDUAL':'1'}; p=subprocess.run(['python3','-m','pytest','-q','phase-loop-runtime/tests/test_train_invariants.py::TestResidualInvariants::test_residual_publish_identity_includes_base'],env=env,capture_output=True,text=True); assert p.returncode != 0 and 'RESIDUAL-RED-ANCHOR::residual_publish_identity_includes_base' in p.stdout+p.stderr"`
- `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests -m "not dotfiles_integration" -k "not residual_publish_identity_includes_base"`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests -m "not dotfiles_integration"`
- `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_phase_loop_docs.py`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.docs_freshness check-catalog --repo .`
- `ruff check . --no-cache`
- `ruff check . --isolated --select F841 --ignore-noqa --no-cache`
- `git diff --check`

IF-0-VC-2 passes only when the plan validator resolves the pinned roadmap,
extracts every command above as shell-free argv, and resolves the exact
frontmatter suite into verification evidence. Collection-only output, skipped
active falsifiers, an unexpectedly GREEN deferred sentinel, stale-head output,
or a prose-only triage table is not passing evidence.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `none`
- evidence paths: `.phase-loop/evidence/RESIDUAL/spec-delta-closeout.json`, `plans/evidence/v10-RESIDUAL-f841-triage.md`, `plans/evidence/v10-RESIDUAL-closeout.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

The runner records the deferred EC-RESIDUAL-1 obligation and agent-harness#368
reference as metadata; it does not amend the roadmap, broker identity, or
evidence schema.

## Acceptance Criteria

- [ ] EC-RESIDUAL-0 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_tdd_chronology` plus the digest-bound chronology in `plans/evidence/v10-RESIDUAL-closeout.json`; falsified by a `verification_evidence.v3` path-entered ancestry inversion or implementation diff touching the frozen test file before the restored control passes.
- [ ] EC-RESIDUAL-1 — deferred-carry disposition proven by `PYTHONPATH=phase-loop-runtime/src python3 -c "import os,subprocess; env={**os.environ,'PHASE_LOOP_TDD_EXPECT_RESIDUAL':'1'}; p=subprocess.run(['python3','-m','pytest','-q','phase-loop-runtime/tests/test_train_invariants.py::TestResidualInvariants::test_residual_publish_identity_includes_base'],env=env,capture_output=True,text=True); assert p.returncode != 0 and 'RESIDUAL-RED-ANCHOR::residual_publish_identity_includes_base' in p.stdout+p.stderr"`; falsified by the path-entered deferred sentinel turning GREEN, losing its named marker, or executable lanes modifying the base-free identity before the restored control passes.
- [ ] EC-RESIDUAL-2 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_pr_open_resume_live_head_failure`; falsified by a `verification_evidence.v3` path-entered mutation that restores exception escape or ledger-head fallback before the restored control passes.
- [ ] EC-RESIDUAL-3 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_non_fab_merge_queue_null_oid`; falsified by a `verification_evidence.v3` path-entered mutation that bypasses queue membership or restores `--delete-branch` before the restored control passes.
- [ ] EC-RESIDUAL-4 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_hotfix_shell_operator`; falsified by a `verification_evidence.v3` path-entered operator mutation that reaches the execution sentinel before restored refusal passes.
- [ ] EC-RESIDUAL-5 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_channel_session_model`; falsified by a `verification_evidence.v3` path-entered mismatch/unbound mutation that reaches message delivery or uncaveated reporting before the restored control passes.
- [ ] EC-RESIDUAL-6 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_repair_recursion_or_interrupt`; falsified by a `verification_evidence.v3` path-entered lineage or child-write mutation that launches nested repair or preserves invalid trust before the restored control passes.
- [ ] EC-RESIDUAL-7 — proven by `env PHASE_LOOP_TDD_EXPECT_RESIDUAL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_train_invariants.py -k residual_f841_triage` and `ruff check . --isolated --select F841 --ignore-noqa --no-cache`; falsified by a path-entered unused-local mutation, hidden formerly affected file, suppression, or missing per-row disposition before the restored control passes.
