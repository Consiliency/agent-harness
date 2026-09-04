---
phase_loop_plan_version: 1
phase: RELEASE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 9cef8186e5d3f6d141ccc170ad24147b611c38a0cddad907fa86a8bc4fea2be0
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      env PHASE_LOOP_TDD_EXPECT_RELEASE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
      python3 -m pytest -q phase-loop-runtime/tests/test_release_evidence.py
      phase-loop-runtime/tests/test_train_runner.py
      phase-loop-runtime/tests/test_outside_agent_release_surface.py;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests
      -m "not dotfiles_integration";
      ruff check phase-loop-runtime/src/phase_loop_runtime/
---

# RELEASE: Pilots and Governed Release

## Context

RELEASE preserves ratified v10 Phase 12 as one phase. Its lane DAG restores the load-bearing
`pilot evidence -> release candidate -> exact-main review -> dispatch -> publication evidence`
order without splitting or editing the roadmap. RELEASE starts only after INTEG and every
transitive predecessor are recorded `completed`; a pilot result is never publication or fleet
rollout evidence.

The planning input is current `phase-loop-runtime` 0.7.14, its signed GitHub Release, PyPI OIDC
workflow, `RELEASE_PIN`, and published handoff. That version is an input, not a prescribed future
output. The executor selects the next release version from the maintainer-approved release scope
and keeps all source identities equal without pinning future commits, counts, or topology.

Live follow-up state is explicit: agent-harness#454 is a fail-closed GitHub admin-identity gate;
agent-harness#353 covers killed-run worktree reaping; agent-harness#385 and agent-harness#387 cover
validator-visible pilot ordering; agent-harness#405 covers a separate reviewer live-probe pilot;
and agent-harness#623 covers stale-draft disposition. Only agent-harness#454 or an equivalent live
admin failure can block this phase; the others remain owned nonblocking tightening when attended
pilot evidence proves their safety concerns did not occur.

## Interface Freeze Gates

- [ ] IF-0-PILOT-1 — `PilotEvidenceBundle.v1` binds two overlapping-in-time, isolated pilot
  trains; canonical repository and train identities; exact input heads; broker admission and
  terminal evidence; draft PR identities; train-status equality; outside-agent admission verbs;
  ambiguity durations; no-reexecution proof; product/coordinator state separation; redacted auth
  posture; cleanup, rollback, and go/no-go receipts. Validation reads structured ledgers and live
  metadata, rejects prose-only claims, and cannot treat an ambiguous outcome as terminal success.
- [ ] IF-0-RELEASE-1 — `ReleaseEvidence.v1` binds IF-0-PILOT-1, candidate/merge/tag/package/fleet
  identities, exact-head CI and ratification, operator approval, retained workflow artifacts,
  clean-install CLI/dependency results, post-release convergence count, and exactly one honest
  status: `pilot-ready`, `deployed-not-baked`, or `production-ready`.
- [ ] TG-RELEASE-0 — production code cannot start until the complete RELEASE tests-only diff has
  landed, its default-GREEN and activated-RED evidence is content-bound, and its exact head has
  passed governed review.

## Lane Index & Dependencies

SL-0 — Immutable tests-only RELEASE contract
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no
SL-1 — Pilot and release evidence implementation
  Depends on: SL-0
  Blocks: SL-2, SL-3, SL-4, SL-5
  Parallel-safe: no
SL-2 — Operational and admin preflight
  Depends on: SL-1
  Blocks: SL-3, SL-4, SL-5
  Parallel-safe: no
SL-3 — SPECPKGMIN pilot
  Depends on: SL-1, SL-2
  Blocks: SL-5
  Parallel-safe: yes
SL-4 — Outside-agent pilot
  Depends on: SL-1, SL-2
  Blocks: SL-5
  Parallel-safe: yes
SL-5 — Pilot evidence and go/no-go reducer
  Depends on: SL-1, SL-2, SL-3, SL-4
  Blocks: SL-6
  Parallel-safe: no
SL-6 — Release candidate sources
  Depends on: SL-5
  Blocks: SL-7
  Parallel-safe: no
SL-7 — Exact-main clean-room and release authorization
  Depends on: SL-5, SL-6
  Blocks: SL-8
  Parallel-safe: no
SL-8 — Human-gated governed dispatch
  Depends on: SL-7
  Blocks: SL-9
  Parallel-safe: no
SL-9 — Post-dispatch documentation, fleet verification, and lifecycle closeout
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5, SL-6, SL-7, SL-8
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable tests-only RELEASE contract

- **Scope**: Freeze every code-backed RELEASE falsifier and content receipt before production.
- **Owned files**: `phase-loop-runtime/tests/release_content_tdd_adapter.py`, `phase-loop-runtime/tests/_release_tdd_guard.py`, `phase-loop-runtime/tests/test_release_evidence.py`, `phase-loop-runtime/tests/test_train_runner.py`, `phase-loop-runtime/tests/test_outside_agent_release_surface.py`
- **Interfaces provided**: `immutable RELEASE tests`
- **Interfaces consumed**: none
- **Parallel-safe**: no
- **Tasks**:
  - test: Add default-inert guards whose activated cases name exact production symbol/path and
    unique RED anchor for structured pilot evidence, parallel isolation, status plurality,
    publication identity, subscription-only review auth, cleanup, and direct-credential rejection.
  - test: Run the exact node inventory against the implementation-free base: default GREEN and
    activated nonzero only at the expected anchors. Record raw/JUnit digests with unchanged
    `ContentTddReceipt`, then land a tests-only commit declaring
    `Phase-Loop-Identity: release-tests-freeze-v1`.
  - impl: Change tests/support only. The governed review binds the exact tests-only head; no
    production path may change before that review and landing.
  - verify: `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m release_content_tdd_adapter verify --repo . --identity release-tests-freeze-v1 --head HEAD`.

### SL-1 — Pilot and release evidence implementation

- **Scope**: Implement the structured evidence builder/validator and only the train hooks it needs.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/release_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- **Interfaces provided**: `release evidence validator`
- **Interfaces consumed**: `immutable RELEASE tests`
- **Parallel-safe**: no
- **Tasks**:
  - test: Consume SL-0 unchanged and require all activated anchors to fail before implementation.
  - impl: Add `PilotEvidenceBundle`, `ReleaseEvidence`, strict serializers, validation, and module
    commands `verify-pilots`, `verify-status`, and `verify-publication`. Extend train events only to
    expose existing broker/status/ambiguity facts; never copy credentials or provider payloads.
  - impl: Derive success from broker/ledger/live metadata, overlap from timestamps, ambiguity time
    from durable transitions, and status from counted post-release trains. Reject narrated evidence,
    direct provider/API-key routes, auto-failover from ambiguity, and locally rebuilt artifact hashes.
  - verify: Run SL-0 activated tests, then the focused release, train, broker, outside-agent,
    ratification, operator-approval, and release-pin suites without editing SL-0.

### SL-2 — Operational and admin preflight

- **Scope**: Produce one redacted go/no-go input before either outward pilot starts.
- **Owned files**: none
- **Interfaces provided**: `operational preflight receipt`
- **Interfaces consumed**: `release evidence validator`
- **Parallel-safe**: no
- **Tasks**:
  - test: Prove exact `origin/main`, completed predecessors, clean pilot inputs, disjoint canonical
    repository/train/evidence roots, broker-only mutation, available disk/inodes, and rollback scope.
  - impl: Probe `gh`, GitHub App/protection/environment relations, PyPI `pypi` environment/workflow,
    1Password item/field presence, and board CLI auth/capability as metadata only. Model seats use
    subscription auth through supported CLIs; scrub and reject provider API keys or direct routes.
  - impl: Fail closed with `human_required=true` and an exact trigger: agent-harness#454 requires
    the maintainer to provision/approve and ratify the live assigned App/install/reviewer binding;
    missing PyPI setup requires the maintainer to configure the trusted publisher for
    `ViperJuice/agent-harness`, `publish-pypi.yml`, environment `pypi`. Never substitute IDs, mint a
    token, read a secret value, or use a long-lived PyPI/GitHub token.
  - verify: Write `.phase-loop/evidence/RELEASE/preflight.json` with typed access attempts,
    observable pilot success/failure, created-resource allowlists, rollback owner, and NO-GO reasons.

### SL-3 — SPECPKGMIN pilot

- **Scope**: Publish the preserved three-repo SPECPKGMIN slice to coordinated draft PRs only.
- **Owned files**: none
- **Interfaces provided**: `SPECPKGMIN pilot evidence`
- **Interfaces consumed**: `release evidence validator`, `operational preflight receipt`
- **Parallel-safe**: yes; only with SL-4 after the preflight proves disjoint canonical repositories,
  state roots, owned paths, and evidence authority.
- **Tasks**:
  - test: Require the authoritative three committed heads and interchange receipts; no rebuilding or
    fresh re-execution may stand in for the preserved slice.
  - impl: Start on the shared barrier with SL-4, use broker `publish_committed_branch`, open exactly
    three coordinated draft PRs, stop at `drafts_open`, and never merge.
  - verify: Persist ledger, broker admission/terminal records, draft PR metadata, exact heads,
    `train-status` equality, and no-reexecution evidence under the SPECPKGMIN-only root.

### SL-4 — Outside-agent pilot

- **Scope**: Run the isolated admin/outside-agent capability-admission pilot without product leakage.
- **Owned files**: none
- **Interfaces provided**: `outside-agent pilot evidence`
- **Interfaces consumed**: `release evidence validator`, `operational preflight receipt`
- **Parallel-safe**: yes; the same preflight must prove no shared repository, path, data, or evidence
  writer with SL-3.
- **Tasks**:
  - test: Freeze a bounded submission/target allowlist and terminal/no-effect expectations.
  - impl: Start on the shared barrier, fire `needs_clarification`, `review_candidate`, and `reject`
    through capability admission, and retain broker evidence plus time in ambiguous block. Never run
    agent-harness#405's arbitrary reviewer live-probe path or unconfined Grok.
  - verify: Prove product work remained in its owning repository, train state remained with the
    coordinator, no direct mutation credential reached the worker, and no ambiguous result advanced.

### SL-5 — Pilot evidence and go/no-go reducer

- **Scope**: Validate IF-0-PILOT-1 and issue the sole release-candidate go/no-go decision.
- **Owned files**: none
- **Interfaces provided**: `IF-0-PILOT-1`
- **Interfaces consumed**: `release evidence validator`, `operational preflight receipt`, `SPECPKGMIN pilot evidence`, `outside-agent pilot evidence`
- **Parallel-safe**: no
- **Tasks**:
  - test: Reject missing/nonoverlapping runs, shared authority, prose claims, incomplete broker rows,
    non-draft/missing PRs, absent verbs/metrics, state leakage, or cleanup uncertainty.
  - impl: Record GO only when all positive arms pass; otherwise record NO-GO without publication.
    A successful pilot authorizes at most `pilot-ready`.
  - impl: Run attended cleanup: reap clean ephemeral worktrees/data scopes, preserve and report dirty
    or unmerged work, keep ambiguous evidence permanent, and give every draft PR an owner/disposition.
    Rollback may close only created drafts and delete only proven-safe pilot branches after approval;
    it never deletes ledgers or rewrites provider outcomes. Carry agent-harness#353,
    agent-harness#385, agent-harness#387, agent-harness#405, and agent-harness#623 with owners when
    their tightening remains nonblocking.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-pilots --repo . --evidence-root .phase-loop/evidence/RELEASE`.

### SL-6 — Release candidate sources

- **Scope**: Prepare the reviewed release candidate after IF-0-PILOT-1, distinct from dispatch.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/src/phase_loop_runtime/__init__.py`, `phase-loop-runtime/uv.lock`, `RELEASE_PIN`, `phase-loop-runtime/README.md`, `CHANGELOG.md`
- **Interfaces provided**: `release candidate sources`
- **Interfaces consumed**: `IF-0-PILOT-1`
- **Parallel-safe**: no
- **Tasks**:
  - test: Record the accepted non-code exception; existing/new release checks remain frozen.
  - impl: Select the maintainer-approved SemVer, update package/runtime/lock/pin/README/CHANGELOG in
    lockstep, and label readiness honestly. Do not edit publish workflows, tag, publish, update fleet,
    or overwrite the last published handoff.
  - verify: Run release consistency, locked build, exact wheel/sdist Gate A, focused tests, full CI
    profile, package inventory, `uv lock --check --project phase-loop-runtime`, and docs audit from a
    temp output directory.

### SL-7 — Exact-main clean-room and release authorization

- **Scope**: Merge the candidate, re-anchor on exact main, and authorize only that release identity.
- **Owned files**: none
- **Interfaces provided**: `exact-main release authorization`
- **Interfaces consumed**: `IF-0-PILOT-1`, `release candidate sources`
- **Parallel-safe**: no
- **Tasks**:
  - test: Require terminal exact-head PR CI, offloaded suite and aggregate gate, candidate merge
    ancestry/tree equality, a clean synced fresh worktree, retained workflow artifacts, and repeat
    clean-room package verification. Cancelled, skipped, pending, stale-head, or locally rebuilt
    evidence is not green.
  - impl: Run the release-dispatch review in prover-first order against the exact merged bundle.
    Resolve the parameterized policy from exact-main repository config; require its vendor/lens/
    consensus facts and usable Fable binding prover. No shortfall may promote under `escalate`.
  - impl: The four reviewing seats remain topology/policy-derived. This run alone uses Grok 4.6 as
    the separate president through a recorded per-run model override; do not edit model registries,
    board defaults, `DEFAULT_RATIFICATION_POLICIES`, or shipped configuration. A typed failure blocks.
  - verify: Only after review and CI pass, accept a fresh secret-free operator approval scoped to
    RELEASE and the exact tag, PyPI package, GitHub Release, and fleet targets.

### SL-8 — Human-gated governed dispatch

- **Scope**: Cut the exact approved tag, let trusted publishing run, and create the GitHub Release.
- **Owned files**: none
- **Interfaces provided**: `publication result`
- **Interfaces consumed**: `exact-main release authorization`
- **Parallel-safe**: no
- **Tasks**:
  - test: Recompute exact main/version/tag/approval/review/CI bindings immediately before mutation.
  - impl: The maintainer creates and pushes the signed annotated tag. That literal tag push triggers
    `.github/workflows/publish-pypi.yml`; its publish job uses GitHub OIDC/PyPI trusted publishing,
    retained build artifacts, and no API token. After success, create the matching GitHub Release
    with repository-scoped authenticated `gh`; never dispatch an alternate token-bearing route.
  - impl: Missing account, trusted publisher, environment, signing, or admin authority records the
    exact `missing_secret`, `account_or_billing_setup`, or `admin_approval` maintainer trigger and
    stops. Before tag push rollback is no mutation; after a pushed/published tag, never delete,
    retag, yank, or overwrite automatically—preserve evidence and require an approved fix-forward.
  - verify: Watch the exact tag workflow to terminal success and query tag, release, workflow jobs,
    retained `SHA256SUMS`, and PyPI files by the same version.

### SL-9 — Post-dispatch documentation, fleet verification, and lifecycle closeout

- **Scope**: Back-fill durable release evidence and close lifecycle only from observed publication.
- **Owned files**: `docs/releases/outside-agent-release-handoff.md`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-RELEASE-1`
- **Interfaces consumed**: `release evidence validator`, `operational preflight receipt`, `SPECPKGMIN pilot evidence`, `outside-agent pilot evidence`, `IF-0-PILOT-1`, `release candidate sources`, `exact-main release authorization`, `publication result`
- **Parallel-safe**: no
- **Tasks**:
  - test: Verify public PyPI and GitHub Release identity, retained official hashes, non-yanked files,
    fresh no-cache install, `pip check`, declared dependency bounds, site-packages import, both console
    scripts, `phase-loop --version`, fleet pin equality, and removal of HEAD-install workarounds.
  - impl: Refresh the published handoff with observed merge/tag/workflow/package/install/fleet facts
    only. Record `production-ready` only after at least two distinct post-release trains converge;
    otherwise use `deployed-not-baked`. Pilot evidence alone never changes publication/rollout status.
  - impl: Append runner-controlled `executing` then `completed` manifest lifecycle evidence only
    after spec closeout, issue dispositions, verification, cleanup, and exact plan/roadmap hashes pass.
    The docs-only back-fill receives its governed tier review before landing.
  - verify: `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-publication --repo . --evidence-root .phase-loop/evidence/RELEASE` and rerun the complete suite.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`, reason=`coordinator supplies one subscription-auth author executor for code lanes`
- SL-5: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-7: effort=`high`, work-unit=`phase_verify`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-8: effort=`high`, work-unit=`phase_verify`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-9: effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

SL-3 and SL-4 are the only concurrent lanes. They start from one barrier and count as parallel only
when their execution intervals overlap and `evaluate_resource_isolation` proves disjoint canonical
repositories, paths, data, and evidence roots; otherwise RELEASE is NO-GO, not silently serialized.
All other lanes are ordered exactly by the DAG. Code lanes use one selected subscription-auth vendor;
review legs are independent and use supported subscription CLIs only. Release/admin documents and
credentialed external dispatch never share a code implementation lane.

This combined plan intentionally omits `phase_loop_mutation: release_dispatch`: that runner mode
requires a clean synced dispatch-only plan, while RELEASE must first implement, pilot, and merge.
SL-8 recreates the same guard at the sole external mutation boundary after SL-7 proves clean exact
main and injects the fresh operator approval. No earlier lane can tag, publish, create a release, or
roll out the fleet.

Every acceptance command emits or validates `verification_evidence.v3` with its command argv,
environment refresh, suite result, exact input artifact digests, and final-log seal; path-entered
controls bind negative cases to the named production function before their unique assertion.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/release_evidence.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/tests/release_content_tdd_adapter.py`, `phase-loop-runtime/tests/_release_tdd_guard.py`, `phase-loop-runtime/tests/test_release_evidence.py`, `phase-loop-runtime/tests/test_train_runner.py`, `phase-loop-runtime/tests/test_outside_agent_release_surface.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/src/phase_loop_runtime/__init__.py`, `phase-loop-runtime/uv.lock`, `RELEASE_PIN`, `phase-loop-runtime/README.md`, `CHANGELOG.md`, `docs/releases/outside-agent-release-handoff.md`, `plans/manifest.json`
- evidence paths: `.phase-loop/evidence/RELEASE/spec-delta-closeout.json`, `.phase-loop/evidence/RELEASE/issue-dispositions.json`, `.phase-loop/evidence/RELEASE/release-evidence.json`
- redaction posture: `metadata_only`
- downstream handling: `none`; repository-qualified tightening issues retain explicit owners

## Verification

```bash
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m release_content_tdd_adapter verify --repo . --identity release-tests-freeze-v1 --head HEAD
env PHASE_LOOP_TDD_EXPECT_RELEASE=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_release_evidence.py phase-loop-runtime/tests/test_train_runner.py phase-loop-runtime/tests/test_outside_agent_release_surface.py
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-pilots --repo . --evidence-root .phase-loop/evidence/RELEASE
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-status --repo . --evidence-root .phase-loop/evidence/RELEASE
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-publication --repo . --evidence-root .phase-loop/evidence/RELEASE
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests -m "not dotfiles_integration"
ruff check phase-loop-runtime/src/phase_loop_runtime/
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md --check-assumptions
PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-RELEASE.md
PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.planner_validation import validate_plan_dispatch_hints; assert not validate_plan_dispatch_hints(Path("plans/phase-plan-v10-RELEASE.md").read_text())'
PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; r=validate_manifest(Path("plans/manifest.json")); assert r.valid, r.errors'
python3 -c 'from pathlib import Path; n=len(Path("plans/phase-plan-v10-RELEASE.md").read_text().split()); print(n); assert n <= 3000'
git diff --check
```

## Acceptance Criteria

- [ ] EC-RELEASE-0 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m release_content_tdd_adapter verify --repo . --identity release-tests-freeze-v1 --head HEAD`; falsified by a changed frozen test, missing RED anchor, or production predecessor producing a green receipt; path-entered control binds each anchor to its exact production symbol.
- [ ] EC-RELEASE-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-pilots --repo . --evidence-root .phase-loop/evidence/RELEASE`; falsified by fewer than two overlapping broker-mediated terminal pilots or any direct-credential side effect; path-entered control reaches the pilot validator before mutation.
- [ ] EC-RELEASE-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-pilots --repo . --evidence-root .phase-loop/evidence/RELEASE`; falsified by substituting prose for a required ledger or live metadata record; path-entered control reaches structured record decoding before rejection.
- [ ] EC-RELEASE-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-status --repo . --evidence-root .phase-loop/evidence/RELEASE`; falsified by `production-ready` with zero or one post-release converged train; path-entered control reaches the counted-status branch and exactly two is the positive boundary.
- [ ] EC-RELEASE-4 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_release_pin_autotrack.py phase-loop-runtime/tests/test_outside_agent_release_surface.py`; falsified by changing one version source or authorizing tag push before approval; path-entered control reaches both the equality and operator-gate checks.
- [ ] EC-RELEASE-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-publication --repo . --evidence-root .phase-loop/evidence/RELEASE`; falsified by a missing trusted-publish result, retained HEAD workaround, or package/command/fleet identity mismatch; path-entered control reaches registry, install, and fleet probes before comparison.
- [ ] EC-RELEASE-6 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.release_evidence verify-pilots --repo . --evidence-root .phase-loop/evidence/RELEASE`; falsified by absent SPECPKGMIN three-draft evidence, missing outside-agent verb, missing ambiguity time, transcript dependence, or state-boundary leakage; path-entered control reaches each named pilot discriminator.
