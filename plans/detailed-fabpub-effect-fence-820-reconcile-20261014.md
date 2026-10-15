---
phase_loop_plan_version: 1
automation:
  suite_command:
    - env
    - PHASE_LOOP_TDD_EXPECT_FABPUB=1
    - PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
    - python3
    - -m
    - pytest
    - -q
    - phase-loop-runtime/tests/test_publisher_effect_fence_820.py
    - phase-loop-runtime/tests/test_convergence_broker_credsep.py
    - phase-loop-runtime/tests/test_pr_readback_789.py
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a0_derivation_sites_match_the_plan_allow_list
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a17_flip_fences_pre_flip_lease_and_fresh_writers
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a26_concurrent_writer_lands_before_digest_or_is_fenced
    - phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py::test_partition_rotation_a17e_authorized_before_flip_is_refused_in_lock
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py::test_fabpub_shared_adapter_start_fence_blocks_competing_train_before_and_after_possible_provider_effect
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py::test_fabpub_legacy_writer_quiescence_blocks_armed_activation_and_fences_supported_restarts
    - phase-loop-runtime/tests/test_fabpub_shared_epoch.py::test_fabpub_post_activation_writer_generation_fence_blocks_direct_and_old_cli_restarts
    - --junitxml=.phase-loop/diagnostics/effect-fence-820-reland/junit.xml
---

# Detailed plan: re-land the agent-harness#820 synchronous publisher effect fence on current main

Status: planning artifact only. No source is changed by this plan. Amended per the
plan board's president ruling (remedy (c) of F015). Board evidence:
`/mnt/workspace/users/viperjuice/tmp/board-820-plan/` on dev0. Issue:
Consiliency/agent-harness#820 stays open after this lands.

## Task

Re-land the retained, never-pushed commit `71c4ba73`
(`codex/v10-publisher-effect-fence-820-20260912`) on current `origin/main`. Do not
treat its September evidence or approvals as valid for the new candidate. Leave the
recovery archive and both retained branches untouched.

The fence closes the check/use gap between writer-generation validation and the two
synchronous GitHub mutations (`git push`, `gh pr create`). It is a bounded partial
repair. It does not close agent-harness#820 (lease holder liveness), does not fix the
agent-harness#833 namespace-resolution bypass, and authorizes no lease cleanup,
rotation or publication recovery.

## Inputs (pinned)

- Retained fence commit: `71c4ba73c1df8315e6fbe0d6fbc76546ad300bea`. Its parent is
  `6e2b2a29`, an **unmerged, superseded** agent-harness#789 read-back retry. Main
  landed a different #789 repair (`fb7c6b82`, `cfe8999d`). Take the fence only.
- Retained design rationale and test requirements:
  `plans/detailed-publisher-effect-fence-820-20260911.md` at `71c4ba73`. That
  document stays authoritative for the fence's semantics, test obligations and
  documented limits. This plan records only what changes on re-landing.
- Investigation evidence: `claw:/mnt/workspace/archives/agent-harness-820-investigation-20260911-012457/`
  (read-only input; keep intact).

## Research summary

Main still lacks the fence. `credsep.py::_revalidate_generation_before_effect`
(main lines 208-229) validates and returns. `live.py::require_current_generation`
(main 799-820) releases the latch lock once `validate_lease` returns. `git push`
(around credsep 474) is checked but not held, and `gh pr create` (around 489) is
not checked at all. No later FABPUB work subsumes it. agent-harness#1593/#1577
added `_provider_entry_guard` (verbs.py around 1020), which sets `provider_entered`
before `adapter.execute` and calls the adapter outside `admissions.lock`, so holding
`writer-generation.lock` around each provider call adds no lock inversion.
agent-harness#1115, #807, #1213 and #1550-#1553 do not touch the latch, this helper
or the call sites.

`git merge-tree --merge-base=6e2b2a29 origin/main 71c4ba73` (cherry-pick
simulation) merges `credsep.py` and `live.py` cleanly into exactly the fence
change. Only `docs/fabpub-partition-rotation-runbook.md` and `plans/manifest.json`
conflict. All seven named frozen nodes still exist on main under the same names.
The A0 allow-list still pins derivation sites. The fence introduces none, since it
reuses `store_root` inside `require_current_generation`.

In-flight work on dev0:
- agent-harness#1626 (draft, branch `claude/fabpub-typed-handoffs`) edits live.py
  (new `RoutingClientGenerationRetired`, `_RepositoryRoutingBrokerService` raise),
  verbs.py refusal sites, publishing.py and the runbook. It does not touch the fence's
  functions. It owns the refusal-to-next-step table, but it types **only pre-entry**
  refusals. It does not route a post-entry `WriterGenerationBlocked`.
- `claude/fabpub-recovery-record-compat-1576` (uncommitted) edits a different live.py
  function and a runbook paragraph.
- `claude/fabpub-observed-after-ambiguity-1591` (uncommitted) changes tests only.

Known residual, which predates this plan: after `provider_entered`, a fence refusal
reaches the `_fresh_publish` except-handler. Its `record_terminal` append is itself
generation-fenced, so under DRAINING or a revoked shared lease it re-raises
`WriterGenerationBlocked` (a `PermissionError`). `publishing.py` maps that to
`repair_fabpub_authority`. Main already does this for the pre-push check. The fence
adds a second post-entry site (before PR create) without changing the routing. The fix
is tracked in agent-harness#1628, sequenced after agent-harness#1626, and is out of
scope here.

Claw holds an idle clean worktree of the same branch (last touched 2026-09-13). No
claw session uses it.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py` (modify)
- `require_current_generation` — modify — take the `71c4ba73` hunk unchanged: an
  optional keyword-only `effect`. When set, validation plus exactly one `effect()`
  run inside `latch.exclusive()`. Validation-only calls keep their current return
  value and lock duration.

### `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py` (modify)
- `GitHubBrokerAdapter._revalidate_generation_before_effect` — modify — take the
  `71c4ba73` hunk: an optional `effect`, returned through `require_current_generation`.
  The capability-off and undeclared-resolution branches invoke the effect once.
- `GitHubBrokerAdapter.execute` push and PR-create call sites — modify — each
  wrapped separately as `effect=lambda: self.run(...)`, with argv, env and read-back
  unchanged. Take no other hunk from `6e2b2a29`.

### `phase-loop-runtime/tests/test_publisher_effect_fence_820.py` (create)
- Take the file from `71c4ba73`. Then confirm its fixture imports still resolve on
  the new base: `test_convergence_broker_credsep` (`_BRANCH`, `_FakeRun`,
  `_base_responses`, `_request`, `_same_repo_pr`), `test_fabpub_recovery_controls_789`
  (`_two_partitions`) and `test_fabpub_shared_epoch` (`_authorized_publish_fixture`,
  `_git`, `_publish_transaction_request`, `_service`). Adapt only fixture-call drift,
  never assertions.
- Keep the retained post-entry refusal tests for both sites (before the push, and
  between push and create). Each must show that no further provider effect occurs
  (create count 0 after a drain between push and create), that the
  `provider_call_in_flight` row and the unsealed owner are retained, and that
  `WriterGenerationBlocked` propagates out of `BrokerService.execute`. Add a
  revoked-shared-lease variant next to the existing DRAINING variant. Do not assert
  the human-publication next step; agent-harness#1628 owns it.
  - For the revoked-lease variant, give the evidence store the adapter's own lease,
    as production does. With the existing `_service` helper the append succeeds and
    nothing propagates.
  - The retained module drives only the push-to-create site through `BrokerService`.
    The before-push site needs a new test in this module.

### `plans/manifest.json` (modify)
- Append a manifest entry for this plan. Do not carry over `71c4ba73`'s manifest
  delta; it recorded the September run.

## Documentation impact
- `docs/fabpub-partition-rotation-runbook.md` — modify — port the `71c4ba73`
  section by hand, after typed-handoffs' §6/provider-entry hunks and #1576's
  recovery-paragraph hunk are in. It covers the bounded synchronous guarantee, store
  fencing versus provider-effect fencing, and the documented limits (a hung push or
  create holds the namespace latch; a drain between the two calls can leave a pushed
  branch without a PR; parent death proves neither cancellation nor release).
- The runbook text also states that the agent-harness#833 undeclared-resolution
  bypass now covers PR create as well as push, and that a post-entry refusal's
  publication handoff is currently `repair_fabpub_authority` (agent-harness#1628).
- `docs/fabpub-pre-admission-ambiguity.md` — no change. Post-entry routing belongs
  to agent-harness#1628.
- `CHANGELOG.md` — modify — one Unreleased entry naming agent-harness#820 as
  partially addressed, not fixed.

## Dependencies & order

1. **Wait for agent-harness#1626 to land.** This is an ordering dependency only: it
   edits the same live.py region and runbook sections. It does not provide
   post-entry routing; agent-harness#1628 does that afterwards. The other two
   in-flight branches have no dependency. Do not edit any of their worktrees. If
   agent-harness#1626 stalls, the re-land may go first and leave the runbook port
   for its author to rebase over.
2. Create a fresh branch/worktree from the then-current `origin/main` and run
   `git cherry-pick 71c4ba73`. Resolve the runbook by porting the text, and resolve
   the manifest by dropping the old delta.
3. **RED on the new base:** with only the new test file applied (source edits
   reverted), the exclusion and second-effect witnesses fail on behavior, not on a
   `TypeError` for the new keyword. Keep the RED JUnit file under its own label.
4. GREEN: apply the two source hunks and run the suite command. Then run the two
   mutation controls on temporary copies. Removing the held section, and separately
   removing only the PR-create guard, must each fail the intended test.
5. Run a fresh four-seat board plus president on the exact candidate. The September
   four-vendor approval bound different bytes on a different base and does not
   carry over.
6. Publish via the normal owner gates. On agent-harness#820, comment with the PR and
   state that the issue remains open. Do not delete the retained branch, the claw
   worktree or the archive until the PR merges; ask the owner before deleting them
   then.

## Verification

```bash
# in the implementation worktree, repo root
git cherry-pick 71c4ba73          # expect conflicts only in the runbook and plans/manifest.json
git diff origin/main --stat -- phase-loop-runtime/src   # exactly live.py and credsep.py
env PHASE_LOOP_TDD_EXPECT_FABPUB=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests \
  python3 -m pytest -q phase-loop-runtime/tests/test_publisher_effect_fence_820.py   # plus the frontmatter nodes
git diff --check
git diff origin/main --name-only   # scope audit: the 2 sources, 1 new test, runbook, CHANGELOG, plan/manifest, plus plans/detailed-publisher-effect-fence-820-20260911.md added by the cherry-pick
```

Also run the full FABPUB module set (`phase-loop-runtime/tests/test_fabpub_*.py`)
once on the GREEN candidate. Existing nodes must pass with their test files
byte-identical to main (`git diff origin/main -- phase-loop-runtime/tests ':!*effect_fence_820*'` is empty).

## Acceptance criteria
- [ ] The source diff against the base is exactly the `71c4ba73` hunks in `live.py` and `credsep.py`, and no `6e2b2a29` read-back hunk is present (`git diff origin/main -- '*credsep.py'` contains no `time.sleep` retry loop).
- [ ] RED on the new base fails `test_publisher_effect_fence_820.py`'s exclusion and push-then-drain witnesses on behavior. GREEN passes the full suite command with no skips in the new module.
- [ ] Each of the two mutation controls fails its intended test node.
- [ ] A fence refusal after `provider_entered`, before the push or between push and create, causes no further provider effect (create count 0), keeps the `provider_call_in_flight` row and the unsealed owner, and propagates `WriterGenerationBlocked` out of `BrokerService.execute`. This holds under both DRAINING and a revoked shared lease, each proven by a named test in the new module. The human-publication next step is out of scope (agent-harness#1628).
- [ ] The candidate's board and president verdicts bind the final head. agent-harness#820, agent-harness#833 and agent-harness#1628 remain open, and #820 has a comment linking the PR.

## Execution Policy
- execute: effort=high, reason=lock-ordering and partial-effect semantics in publication; small diff but concurrency-sensitive
