---
phase_loop_plan_version: 1
phase: ROLLJOB
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: b18fcb7584e865adf99a69403e485449b04e4f43663d62556378043cb5d5e08a
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_catalog_policy.py tests/test_agy_watch_units.py tests/test_agy_watch_job.py tests/test_agy_promotion.py tests/test_agy_catalog_promote.py tests/test_agy_upstream_advisory.py tests/test_ci_agy_lag_issue.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_self_qualification.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# ROLLJOB: Rolling catalog job and lag rule

## Context

ROLLJOB turns the existing `agy_watch` into the job that keeps the shipped catalog current.
Each hourly tick qualifies the newest upstream release and submits a signed record. A
workflow on `main` verifies the record, authors the catalog pull request and arms its merge.
The nightly check reports catalog lag, and fails on it once ACTIVATE turns enforcement on.

**Frozen inputs.**
- AGYROLL §6 and §3.2 (`plans/artifacts/agyroll-v1-contract.md`): the job, promotion, aging,
  install, login and the lag rule.
- AGYFRESH §5, §5.1 and §1.2 (`plans/artifacts/agyfresh-contract.md`): R6′ under owner
  decision D8 = B, EC-ROLLJOB-4′, EC-ROLLJOB-7..9 and the streaming requirement.
- `plans/artifacts/agyroll-ROLLJOB-detail.md` (ROLLJOB-detail): symbols, per-file changes,
  test cases and the owner-action list. It is read-only during execution.
- `plans/artifacts/agyroll-ROLLJOB-amendment.md` (ROLLJOB-amendment): the R9′ text SL-5
  applies to both contracts and the roadmap.

Both contracts are pinned by sha256 in the roadmap's External Inputs.

**Revision 3 (2026-11-20).** The owner ruled that no new GitHub user account is created per
use case, which withdraws r2's fork design. r3 also applies the r2 re-review (R2a, R2b, R2c).

**Revision 4 (2026-11-20).** It applies the r3 re-review's five required items and the
coordinator's rulings. PROVFWD is frozen and unchanged.

**Revision 5 (2026-11-20).** The owner decided against any extra review requirement. The
CODEOWNERS enforcement of r4 is removed; everything else in r4 stands.

**Revision 6 (2026-11-20).** It applies the r5 re-review: the new check becomes required
only after it has run against a base that contains its verifier, and the amendment limits
the job signature and the diff-class restrictions to the promotion path.

**Revision 9 (2026-11-20), after PROVFWD.** PROVFWD merged as agent-harness#2039. This
revision carries the plan onto that `main`, regenerates the roadmap pin, re-checks what the
plan relies on from PROVFWD against the merged code (one wording change, in ROLLJOB-detail
§2.1), and names the qualification host by role. The design is unchanged.

**Revision 9.1 (2026-11-21).** Three clarifications from the r9 review, in ROLLJOB-detail
§2.1, §6.3 and §7: the phase may merge under the existing branch protection with the live
setup finishing afterwards; the runtime install is separate from preparing the job account;
and the login renewal's handling of admission failures is stated and tested.

**Job identity (R9′, proposed; the owner confirms it).** Two organization-owned GitHub Apps,
each installed on this repository only:
- the **INTAKE App** can write issues and nothing else. Its key is on the qualification host. The job uses it
  to submit the signed record as data. The job makes no git write.
- the **PROMOTION App** has contents and pull-requests write. Its key is a secret of an
  Actions environment limited to `main`. The trusted workflow uses a short-lived token from
  it to author the catalog pull request.

There is no fork, no `pull_request_target`, and no pull-request head written by untrusted
code. A compromised qualification host can write issues and can submit a signed record; that is what makes
AGYFRESH §5.1's statement about a compromised job identity hold.

**Prerequisite, met.** PROVFWD is merged (agent-harness#2039): it is the previous writer of `agy_watch.py`,
`agy_provenance.py` and the verifier, and it provides `stable_releases(limit=)`,
`newest_stable` and the recorded `attestation` and `second_channel` statuses.

**Merge rule in force (R6′).** No catalog pull request needs an owner signature, and no owner
key exists. The signer list holds the job key only. The second Q10 signer is the hosted
provenance check, run by the workflow on `main`. Only the diff class in R6′ is promoted, and
the workflow enforces it by writing exactly those paths itself. Every other change is merged
by a repository writer under the `main` ruleset.

**Every catalog change is checked, whoever wrote it.** The organization's default permission
is write, so the App path alone does not bound what reaches the catalog. A required check,
`agy catalog provenance`, runs on every pull request to `main`: it passes at once if the
catalog is untouched, and otherwise re-derives upstream provenance for each added or changed
member, whoever wrote the pull request (ROLLJOB-detail §4.4). A change that is upstream's
passes. The job signature is required only for automatic promotion. It never blocks a pull request that leaves the catalog alone.

**Trust-root files and the residual risk.** The workflows, the signer list, the policy and
verifier code and the attestation file change through ordinary pull requests by repository
writers, like any other code. No review rule is added and CODEOWNERS is not edited (owner
decision, 2026-11-20). The automated path never changes them, because it writes only the
catalog and one record. So a rogue or compromised **writer** can change these files, as with
any code; the required check's own workflow file is editable by a pull request, and writers
keep GitHub's ordinary merge and auto-merge authority. A compromised qualification host or job identity still cannot promote bytes that are not
upstream's: it holds only the issues App and the job key, and both the workflow and the
required check re-derive every member from the fixed upstream.

**What tokens cannot read is attested.** `config/agy-rollout-attestation.json`
records the ruleset ids, targets, exact bypass lists and identities. Auto-merge is armed
only when it is attested and the live rule reads agree (ROLLJOB-detail §4.5).

**Lag alarm mode.** The lag rule is report-only until ACTIVATE: it records its status but
does not fail the run or touch the `agy-lag` issue until
`AGY_LAG_ENFORCE` is `true` in a `main`-only Actions environment (ROLLJOB-detail §5).

**Not in any lane.** Creating and installing the two Apps, placing their keys, both rulesets,
both Actions environments and their variables, labels and settings, filling the attestation
file, signer enrolment, installing the `agy-watch` extra on the qualification host, the owner's confirmation of
R9′, and everything else on the qualification host are owner actions (ROLLJOB-detail §7). Lanes use fixture
keys, fake runners and a fake API. Auto-merge and lag enforcement ship switched off, and the
attestation file ships unattested.

**Stop rules.**
- A lane that needs to edit `agy_qualification.py`, `gemini_heartbeat.py` or
  `panel_invoker.py` stops and reports. The login path and `_classify_failure` are called,
  never changed.
- If `tests/test_agy_qci.py`'s verdict-vector pin changes, the lane stops and reports
  (AGYFRESH §3).
- SL-3 and SL-6 check the current GitHub documentation before writing a workflow, for the
  behaviours ROLLJOB-detail §8 lists as unverified. If one is contradicted, the lane stops and
  reports. If one cannot be confirmed from documentation, the workflow still ships with
  auto-merge off and the item goes to ACTIVATE's confirmations.
- No lane gives the promoter ruleset or administration access, infers an empty bypass list
  from an omitted field, or uses "update branch" on a promotion pull request.
- SL-5 does not start until the owner's confirmation of R9′ has been supplied.
- No lane gives the job on the qualification host any credential other than the INTAKE App's, and no lane
  moves the PROMOTION key out of the `main`-only environment to make a test pass.

## Interface Freeze Gates

- [ ] IF-0-ROLLJOB-1 — AGYROLL §6, with the symbols frozen in ROLLJOB-detail:
  - §1: `agy_catalog_policy` constants, `canonical_record`, `sign_record`,
    `verified_signers`, `aging`, `catalog_change`, `build_catalog`, `render_intake`,
    `parse_intake`, `parse_catalog`, `candidate_member`, `load_attestation`,
    `authentic_author`, `headroom` and the tick-status file;
  - §2: the tick order, the work set, `read_member(…, sink=)` and `fetch_member(…, sink=)`
    with `keep_bytes` removed, `agy_intake.installation_token`, `submit` and `pending`, and
    the statuses `gemini_login_expired`, `series_violation`, `series_unavailable`,
    `agy_watch_signing_unavailable`, `agy_intake_unavailable`,
    `agy_intake_dependency_missing`, `agy_intake_submit_failed` and `intake_stalled`; the
    `agy-watch` extra and the `intake_receipt.v1` store context;
  - §3: `watch --install-units`, `watch --check` and its four states, and the unit lines;
  - §4: `--intake … --out` and its classes `ignored`, `refused`, `manual`, `auto`;
    `--catalog-pr` and the check name `agy catalog provenance`; the intake workflow's jobs
    and `ci/agy_catalog_promote.py promote|reconcile`; the
    `agy_rollout_attestation.v1` file and the four-part merge gate; the environments
    `agy-promotion` (`AGY_CATALOG_AUTOMERGE`) and `agy-activation` (`AGY_LAG_ENFORCE`);
  - §5: `--upstream-only --report`, the report-only and enforced modes under
    `AGY_LAG_ENFORCE`, the four lag statuses, headroom, and the `agy-lag` issue contract.

## Lane Index & Dependencies

SL-0 — Catalog policy primitives
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-6
  Parallel-safe: yes

SL-1 — Units, install and check
  Depends on: SL-0
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-2 — Job
  Depends on: SL-0, SL-1, SL-5
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Verifier modes, catalog check, attestation, lag and headroom
  Depends on: SL-0, SL-5
  Blocks: SL-4, SL-6
  Parallel-safe: yes

SL-4 — Documentation & spec reconciliation
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-5, SL-6
  Blocks: (none)
  Parallel-safe: no

SL-5 — Contract and roadmap amendment (R9′)
  Depends on: (none)
  Blocks: SL-2, SL-3, SL-4
  Parallel-safe: yes

SL-6 — Intake and promotion workflow, promote and reconcile
  Depends on: SL-0, SL-3
  Blocks: SL-4
  Parallel-safe: yes

SL-0 is a preamble: it holds the rules the job and the verifier must agree on, so neither
copies the other. After it, SL-1 and SL-3 run in parallel; SL-2 follows SL-1 because it
reduces the launch-reference inventory for SL-0's and SL-1's new modules. SL-5 is docs only
and starts at once; it starts once the owner has confirmed R9′, and can be split out and merged ahead of the
code so that the owner actions follow R9′ from the start.

## Lanes

### SL-0 — Catalog policy primitives
- **Scope**: One standard-library module for signing, aging, building the catalog change, the intake body format, the strict catalog parser, the attestation reader, author authentication, the auto-merge diff class, headroom and the tick status.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_catalog_policy.py`, `phase-loop-runtime/tests/test_agy_catalog_policy.py`, `phase-loop-runtime/tests/fixtures/agy_catalog_policy/**`
- **Interfaces provided**: `canonical_record`, `sign_record`, `verified_signers`, `aging`, `catalog_change`, `build_catalog`, `candidate_member`, `render_intake`, `parse_intake`, `parse_catalog`, `load_attestation`, `authentic_author`, `headroom`, `read_tick_status`, `write_tick_status`, `SIGNING_KEY_ENV`, and the constants of ROLLJOB-detail §1
- **Interfaces consumed**: the standard library and `ssh-keygen` (pre-existing)
- **Parallel-safe**: yes
- test: ROLLJOB-detail §6.1, written first and failing.
- impl: ROLLJOB-detail §1.
- verify: the lane's test file. The inventory test is run by SL-2.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | (none) | `phase-loop-runtime/tests/test_agy_catalog_policy.py`, `phase-loop-runtime/tests/fixtures/agy_catalog_policy/**` | ROLLJOB-detail §6.1 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_catalog_policy.py` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_catalog_policy.py` | (none) | same |
| SL-0.3 | verify | SL-0.2 | `phase-loop-runtime/tests/test_agy_catalog_policy.py` | ROLLJOB-detail §6.1 | same |

### SL-1 — Units, install and check
- **Scope**: Set the hourly timer, and add `watch --install-units` and `watch --check`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_watch_units.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `docs/ops/agy-upstream-watch/agy-upstream-watch.service`, `docs/ops/agy-upstream-watch/agy-upstream-watch.timer`, `phase-loop-runtime/tests/test_agy_watch_units.py`
- **Interfaces provided**: ROLLJOB-detail §3
- **Interfaces consumed**: `read_tick_status` (SL-0); `SIGNING_KEY_ENV` (SL-0)
- **Parallel-safe**: yes
- test: ROLLJOB-detail §6.2, written first and failing.
- impl: ROLLJOB-detail §3. No test runs a real `systemctl`.
- verify: the lane's test file plus the existing top-level `--dry-run` watch test.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | (none) | `phase-loop-runtime/tests/test_agy_watch_units.py` | ROLLJOB-detail §6.2 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_watch_units.py` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_watch_units.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, the two unit files | (none) | same |
| SL-1.3 | verify | SL-1.2 | `phase-loop-runtime/tests/test_agy_watch_units.py` | ROLLJOB-detail §6.2 | same, plus `tests/test_agy_self_qualification.py -k dry_run` |

### SL-2 — Job
- **Scope**: Make one tick qualify only what needs it, one image at a time, with retries, login renewal, signing and a recorded status, and submit the record through the INTAKE App with no git write.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_intake.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/tests/test_agy_watch_job.py`, `phase-loop-runtime/tests/fixtures/agy_intake/**`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/test_publishing.py`, `phase-loop-runtime/tests/test_agy_size_bounds.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`
- **Interfaces provided**: ROLLJOB-detail §2
- **Interfaces consumed**: `sign_record` (SL-0); `render_intake` (SL-0); `write_tick_status` (SL-0); R9′ (SL-5); `stable_releases(limit=)`, `attestation_status`, `second_channel_status` (pre-existing, PROVFWD); `VerifiedImage.from_fd` (pre-existing, IF-0-RESTORE-1); `panel_invoker._gemini_login_left_s`, `_await_gemini_login`, `_refresh_gemini_credential` (pre-existing)
- **Parallel-safe**: yes
- test: ROLLJOB-detail §6.3, written first and failing.
- impl: ROLLJOB-detail §2, including the `agy-watch` extra in `pyproject.toml` and the regenerated `uv.lock`. Add inventory rows for SL-0's, SL-1's and this lane's new sites.
- verify: the lane's test files, `tests/test_agy_qci.py` and both inventory tests.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | (none) | `phase-loop-runtime/tests/test_agy_watch_job.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/test_agy_size_bounds.py` | ROLLJOB-detail §6.3 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_watch_job.py tests/test_agy_self_qualification.py tests/test_agy_size_bounds.py` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py` | (none) | same |
| SL-2.3 | impl | SL-2.2 | `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`, the two inventory files | (none) | same |
| SL-2.4 | verify | SL-2.3 | the lane's test files | ROLLJOB-detail §6.3 | same, plus `tests/test_agy_qci.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py` |

### SL-3 — Verifier modes, catalog check, attestation, lag and headroom
- **Scope**: Add the `--intake` and `--catalog-pr` verifier modes, the required catalog provenance check, the attestation file, the lag rule with its report-only mode and issue, and the headroom alarm.
- **Owned files**: `phase-loop-runtime/scripts/verify_qualified_agy_image.py`, `.github/workflows/qualified-agy-image.yml`, `.github/workflows/agy-catalog-provenance.yml`, `config/agy-rollout-attestation.json`, `ci/agy-lag-issue.sh`, `plans/evidence/agy-allowed-signers`, `phase-loop-runtime/tests/test_agy_promotion.py`, `phase-loop-runtime/tests/test_agy_upstream_advisory.py`, `phase-loop-runtime/tests/test_ci_agy_lag_issue.py`, `phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py`
- **Interfaces provided**: `--intake`, `--catalog-pr`, `agy catalog provenance`, the decision file, `--upstream-only --report`
- **Interfaces consumed**: `verified_signers` (SL-0); `catalog_change` (SL-0); `build_catalog` (SL-0); `candidate_member` (SL-0); `parse_intake` (SL-0); `parse_catalog` (SL-0); `load_attestation` (SL-0); `authentic_author` (SL-0); `headroom` (SL-0); R9′ (SL-5); `newest_stable`, `contract`, `verify_asset`, `download_asset`, `verify_archive` (pre-existing)
- **Parallel-safe**: yes
- test: ROLLJOB-detail §6.4 (`--intake`, `--catalog-pr`, provenance workflow shape) and §6.5, written first and failing.
- impl: ROLLJOB-detail §4.2, §4.4, §4.5 (the file), §4.6 and §5.
- verify: the lane's test files and `--contract`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | (none) | the lane's four test files | ROLLJOB-detail §6.4, §6.5 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_promotion.py tests/test_agy_upstream_advisory.py tests/test_ci_agy_lag_issue.py tests/test_verify_qualified_agy_route_core.py` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/scripts/verify_qualified_agy_image.py`, `plans/evidence/agy-allowed-signers`, `config/agy-rollout-attestation.json` | (none) | same |
| SL-3.3 | impl | SL-3.2 | `.github/workflows/qualified-agy-image.yml`, `.github/workflows/agy-catalog-provenance.yml`, `ci/agy-lag-issue.sh` | (none) | same |
| SL-3.4 | verify | SL-3.3 | the lane's four test files | ROLLJOB-detail §6.4, §6.5 | same, then `timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract` |

### SL-6 — Intake and promotion workflow, promote and reconcile
- **Scope**: Add the workflow on `main` that authenticates an intake issue, verifies it, authors the catalog pull request with the PROMOTION App, arms the merge behind the gate, and reconciles stale or stranded work.
- **Owned files**: `.github/workflows/agy-catalog-intake.yml`, `ci/agy_catalog_promote.py`, `phase-loop-runtime/tests/test_agy_catalog_promote.py`, `phase-loop-runtime/tests/fixtures/agy_catalog_promote/**`
- **Interfaces provided**: `ci/agy_catalog_promote.py promote`, `ci/agy_catalog_promote.py reconcile`, the supersede rule
- **Interfaces consumed**: `--intake` (SL-3); the decision file (SL-3); `load_attestation` (SL-0); `authentic_author` (SL-0); `catalog_change` (SL-0); `parse_catalog` (SL-0)
- **Parallel-safe**: yes
- test: ROLLJOB-detail §6.4 (promote, reconcile, intake workflow shape), written first and failing.
- impl: ROLLJOB-detail §4.3 and §4.5 (the gate).
- verify: the lane's test file.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | (none) | `phase-loop-runtime/tests/test_agy_catalog_promote.py`, `phase-loop-runtime/tests/fixtures/agy_catalog_promote/**` | ROLLJOB-detail §6.4 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_catalog_promote.py` |
| SL-6.2 | impl | SL-6.1 | `ci/agy_catalog_promote.py`, `.github/workflows/agy-catalog-intake.yml` | (none) | same |
| SL-6.3 | verify | SL-6.2 | `phase-loop-runtime/tests/test_agy_catalog_promote.py` | ROLLJOB-detail §6.4 | same |

### SL-4 — Documentation & spec reconciliation
- **Scope**: Rewrite the watch runbook and update the docs this phase invalidates, after every code lane.
- **Owned files**: `docs/ops/agy-upstream-watch.md`, `docs/releases/outside-agent-release-handoff.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-4.1 | docs | — | `.claude/docs-catalog.json` | Rescan with the scaffold helper when present; otherwise record "manual catalog audit". |
| SL-4.2 | docs | SL-4.1 | the four docs | **Watch runbook:** the tick order, work set, retries, signing, aging, login expiry, `--install-units`, `--check`, submission through the INTAKE App, the intake classes and their reasons, how a writer takes a `manual` record into an ordinary pull request, the catalog provenance check, the attestation file, the residual risk for writers, reconcile and supersede, the two Apps and what each key can do, the lag rule's report-only and enforced modes, the issue and headroom; the owner actions of ROLLJOB-detail §7 as prerequisites **of live operation, not of this phase's merge**, marked as not performed by this phase. **Release handoff:** catalog members arrive by the job. **CONTRACTS** (qualified images): R6′, R9′, the signer list, the residual risk from AGYFRESH §5.1 as amended. **CHANGELOG:** one entry. |
| SL-4.3 | verify | SL-4.2 | — | `grep -n "owner key\|enrolled-owner\|01,07,13,19" docs/ops/agy-upstream-watch.md` returns nothing. |

### SL-5 — Contract and roadmap amendment (R9′)
- **Scope**: Apply the frozen R9′ text to both contracts and the roadmap, and repin the roadmap's External Inputs.
- **Owned files**: `plans/artifacts/agyroll-v1-contract.md`, `plans/artifacts/agyfresh-contract.md`, `specs/phase-plans-agyroll-v1.md`
- **Interfaces provided**: R9′
- **Interfaces consumed**: ROLLJOB-amendment (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-5.1 | docs | — | the two contracts | Requires the owner's confirmation of R9′ (ROLLJOB-amendment §0); without it, stop. Apply ROLLJOB-amendment §1 and §2 verbatim. |
| SL-5.2 | docs | SL-5.1 | `specs/phase-plans-agyroll-v1.md` | Apply ROLLJOB-amendment §3, filling its one placeholder with the supplied confirmation; recompute both External Inputs digests from the committed contract files. |
| SL-5.3 | verify | SL-5.2 | — | `sha256sum` of each contract equals its External Inputs row; `timeout 120 uv run --locked python -m phase_loop_runtime.roadmap_lint specs/phase-plans-agyroll-v1.md`; `grep -n "owner confirmation:" specs/phase-plans-agyroll-v1.md` returns nothing (the placeholder was filled). |

## Execution Notes

- **One PR, or two.** The phase lands as one pull request; lanes are its internal ownership
  units. SL-5 may instead land first as its own docs pull request. Either way it waits for
  the owner's confirmation of R9′ and records it.
- **Pins after SL-5.** SL-5 changes the roadmap and both contracts, so this plan's
  `roadmap_sha256` and any other plan's are regenerated after it merges. That is an input
  repin, not an amendment of this plan's content.
- **Workflow files.** The pull request adds and edits workflows, so a repository writer
  authors and merges it. Neither App has the `workflows` permission.
- **Shared files across phases.** `cli.py` is also edited by REQUAL (the `preflight` action),
  and `CONTRACTS.md`, `CHANGELOG.md`, `tests/test_agy_self_qualification.py` and the
  inventory by REQUAL and EXECADMIT. Each phase adds its own lines; the PR that merges second
  rebases and reconciles, never rewriting the other's text.
- **What merging this phase turns on.** Two things act from merge. The
  `agy catalog provenance` workflow runs on every pull request. It is not required yet:
  this pull request's own run has no verifier in its base. The owner makes it required
  only after a successful run on a later pull request (ROLLJOB-detail §7, steps 16 to 19). The headroom alarm can fail a
  nightly run at 90 percent of a size bound. Everything else is inert: no enrolled key, an
  unattested file, and both switches unset.
- **Churn on a busy `main`.** Strict up-to-date checks mean a pending promotion goes stale
  whenever `main` moves, and is rebuilt. `MAX_PROMOTION_ATTEMPTS` bounds that; if `main`
  moves faster than the required checks finish, promotions stall and the lag rule says so.
  ACTIVATE measures it.
- **Shared host.** Targeted pytest only, serial (no `-n`), under `timeout`. No full suite, no
  `-n auto`, no live provider call, no real `systemctl`, no call to the GitHub API, no push, and no App is created.
- **Requalification.** None intended (AGYFRESH §3).
- **Rollback.** Revert. The timer on the qualification host, if installed, is disabled with
  `systemctl --user disable --now agy-upstream-watch.timer`; no store migration.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- SL-0: effort=high, reason=signature and merge-class rules are security-relevant
- SL-1: effort=medium, reason=bounded CLI and unit change
- SL-2: effort=high, reason=live-job control flow, login renewal and streaming
- SL-3: effort=high, reason=verifier modes and a required check that every pull request runs
- SL-6: effort=high, reason=privileged workflow, merge gate and recovery
- SL-4: effort=low, reason=docs sweep only
- SL-5: effort=low, reason=frozen text applied verbatim

## Acceptance Criteria

Test files are under `phase-loop-runtime/`.

- [ ] EC-ROLLJOB-1 — proven by `tests/test_agy_watch_job.py` (work set, retries, signing, submission); falsified by a tick that runs a member whose `qci` matches, that submits an unsigned record, or that runs `git push` or opens a pull request.
- [ ] EC-ROLLJOB-2 — proven by `tests/test_agy_watch_units.py`; falsified by a `--check` that reports `installed` with a unit file missing, or by a timer line other than `OnCalendar=hourly`.
- [ ] EC-ROLLJOB-3 — proven by `tests/test_agy_upstream_advisory.py` (lag statuses in both modes); falsified by exit 0, with enforcement on, for a non-member newest release older than `LAG_BOUND_S` with nothing in flight; and falsified by a lag status changing the exit with enforcement off.
- [ ] EC-ROLLJOB-4 — proven by `tests/test_agy_promotion.py`; falsified by class `auto` for a record that lacks a job signature verified against `main`'s signer list, whose archive re-derives a different member digest, or that came from an issue created by anyone other than the INTAKE App; and falsified by a promoted commit that changes any path other than the catalog and one new record, or by auto-merge armed for a commit other than the one the workflow created; and falsified by `agy catalog provenance` passing a writer's catalog change whose archive re-derives a different member digest, or failing a pull request that leaves the catalog untouched, or one whose added member is upstream's but unsigned.
- [ ] EC-ROLLJOB-5 — proven by `tests/test_agy_catalog_policy.py` (aging, `build_catalog`) and `tests/test_agy_promotion.py`; falsified by a pruned `pinned` member, or a pruned member among the newest three.
- [ ] EC-ROLLJOB-6 — proven by `tests/test_agy_watch_job.py` (login), `tests/test_agy_watch_units.py` (`failed: gemini_login_expired`) and `tests/test_agy_upstream_advisory.py` (enforced lag `fail` with nothing in flight); falsified by an expired-login tick that exits 0, submits a record, or leaves `--check` reporting `installed`.
- [ ] EC-ROLLJOB-7 — proven by `tests/test_ci_agy_lag_issue.py`; falsified by two open `agy-lag` issues after two failing runs, or an open issue after a passing run, with enforcement on; and falsified by any issue created, commented on or closed with enforcement off.
- [ ] EC-ROLLJOB-8 — proven by `tests/test_agy_upstream_advisory.py` (headroom); falsified by exit 0 at 90 percent of either bound, or no warning at 80 percent.
- [ ] EC-ROLLJOB-9 — proven by `tests/test_agy_watch_job.py` (streaming); falsified by two images open at once, or by `keep_bytes` remaining in `agy_provenance.py`.
- [ ] Plan-internal (R9′) — proven by SL-5.3's digest and lint commands and by `tests/test_agy_watch_job.py` (submission); falsified by a token request that names a permission other than `issues`, by the key or token appearing in any output, or by a tick that proceeds to a live operation with the `agy-watch` extra absent.
- [ ] Plan-internal (workflow trust) — proven by `tests/test_agy_promotion.py` and `tests/test_agy_catalog_promote.py` (workflow shape); falsified by a `pull_request_target` trigger, an issue field interpolated into a `run:`, a secret reachable from the `intake` job, a job that runs on a ref other than `refs/heads/main`, or any mutation on an issue that failed author authentication.
- [ ] Plan-internal (merge gate) — proven by `tests/test_agy_catalog_promote.py` (gate, races, policy change); falsified by auto-merge armed with an unattested file, an absent bypass list, a rule from an unexpected ruleset id or a stale base, or by an "update branch" call; and falsified by a concurrency group on any job other than `promote` and `reconcile`.
- [ ] Plan-internal (recovery) — proven by `tests/test_agy_catalog_promote.py` (reconcile) and `tests/test_agy_watch_job.py` (recovery); falsified by an authenticated issue that is left unprocessed after its event run was lost, by a duplicate issue after a lost POST response, by an intake issue counted as in flight by the lag rule, or by a pull request matched to its issue through a label, title or body.
- [ ] Plan-internal (check closure) — proven by `tests/test_agy_promotion.py` (import closure); falsified by `--catalog-pr` importing a module other than `agy_catalog_policy` and the standard library.
- [ ] Plan-internal (inventory) — proven by `tests/test_seat_reference_inventory.py` and `tests/test_agent_cli_scratch_inventory_1147.py`; falsified by a new subprocess site in `agy_watch_units.py` with no row.
- [ ] Plan-internal (QCI) — proven by `tests/test_agy_qci.py`; falsified by a changed verdict-vector pin in this phase's diff.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_catalog_policy.py tests/test_agy_watch_units.py tests/test_agy_watch_job.py \
  tests/test_agy_promotion.py tests/test_agy_catalog_promote.py \
  tests/test_agy_upstream_advisory.py tests/test_ci_agy_lag_issue.py \
  tests/test_verify_qualified_agy_route_core.py tests/test_agy_self_qualification.py \
  tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py \
  tests/test_agent_cli_scratch_inventory_1147.py
timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract
```

Hosted CI on the PR: the seven required checks, the `agy catalog contract` job, and the
strict conformance run with `--release`. The phase touches workflows and `docs/`, so dispatch
Gate A as `CONTRIBUTING.md` describes. The promotion workflow's live behaviour is proven at
ACTIVATE (EC-ACTIVATE-2), not here.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyroll-v1-contract.md`, `plans/artifacts/agyfresh-contract.md`, `docs/ops/agy-upstream-watch.md`, `docs/releases/outside-agent-release-handoff.md`
- evidence paths: `phase-loop-runtime/tests/test_agy_upstream_advisory.py`
- redaction posture: `metadata_only`
- downstream handling: roadmap amendment (R9′, SL-5); plans that pin the roadmap digest regenerate it after SL-5 merges
