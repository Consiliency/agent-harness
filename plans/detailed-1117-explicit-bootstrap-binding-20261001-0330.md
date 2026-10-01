---
automation:
  suite_command: "UV_PROJECT_ENVIRONMENT=/home/viperjuice/workspace/tmp/agent-harness-1117-binding/venv uv run --frozen --group test --project phase-loop-runtime python -m pytest -q phase-loop-runtime/tests/test_fabpub_zero_history_bootstrap.py phase-loop-runtime/tests/test_fabpub_shared_epoch.py phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py phase-loop-runtime/tests/test_fabpub_recovery_controls_789.py phase-loop-runtime/tests/test_fabpub_admission_compat_789.py"
---

# Detailed plan: bind explicit-root onboarding to authenticated bootstrap authority

## Task

Repair Consiliency/agent-harness#1117: onboarding with explicitly declared legacy roots must preserve its authenticated persistent bootstrap identity, scan and lock those roots, and retain the resulting binding through receipt validation and activation. Prepare a local change and genuine isolated tests. Do not onboard a production repository, alter production authority/routing/admissions, attest complete history, invoke providers, publish, or merge.

## Research summary

Input is freshly fetched `origin/main` at `2ece0c3cb9077c0a8460680e865b54c025e93f47`; the isolated branch is `codex/1117-explicit-bootstrap-binding`. Initial `git status --short --untracked-files=all` is empty. No suitable existing Consiliency/agent-harness#1117 worktree exists; the app artifact tool is unavailable.

`onboard_zero_legacy_repository` currently looks up the bootstrap only inside `if roots is None` (`live.py:3877–3891`). Explicit roots therefore omit the existing bootstrap fields from the sealed onboarding inventory, while later receipt authentication requires those fields (`live.py:5187–5236`). Receipt seal locks also currently cover only the bootstrap inventory, omitting supplemental receipt roots (`live.py:5251–5262`). `_hold_all` takes paths in supplied order (`live.py:1892–1896`); all combined lock sets must be deduplicated and sorted before acquisition.

Frozen contract: the public signature `onboard_zero_legacy_repository(worktree, *, cutover_id=ZERO_SOURCE_ONBOARDING_CUTOVER_ID, roots=None, authority_root=None, recorded_worktree=None)` is unchanged (`live.py:3858–3865`). The existing sealed fields `bootstrap_inventory_sha256`, `bootstrap_authority_root` and `legacy_root_inventory` remain the binding (`live.py:4035–4050`). No schema, receipt vocabulary, bootstrap inventory, generation state, provider pair, or admission shape is added or weakened. Traditional-only authority remains supported; an ACTIVE persistent bootstrap selects its existing identity even when roots are explicit.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py` (modify)

- `onboard_zero_legacy_repository` — move authenticated bootstrap lookup outside the implicit-roots branch. Preserve supplied roots; inherit bootstrap roots only when omitted. Reuse its real cutover ID/digest/root; reject a conflicting requested cutover before canonical mutation. Deduplicate and sort the union of bootstrap seal locks and explicit-root authority locks. Revalidate the bootstrap binding while holding that union before draining/writing.
- `_onboard_zero_legacy_repository_under_seal` — preserve immutable receipt/inventory history coverage on retry: refuse changed root inventory or bootstrap binding rather than silently returning a receipt for different inputs. Retain actual repeated zero-source scans and existing activation ordering.
- `_receipt_seal_lock_paths` — include receipt legacy-root locks together with persistent bootstrap locks, in stable sorted order, so subsequent activation retains the same coverage.
- `fabpub_activation_barrier` — before granting a generation lease, rerun the actual zero-source scan across the base zero-source receipt's recorded roots under the held locks. New evidence in a supplemental root must block and unwind leases. Rotated receipts use their existing authenticated base receipt.

### `phase-loop-runtime/tests/test_fabpub_zero_history_bootstrap.py` (modify)

- Add regressions using genuine temporary Git repositories and test-only bootstrap authority under pytest `tmp_path`: explicit roots retain authenticated bootstrap binding and an unchanged sealed bootstrap; default cutover ID resolves to that bootstrap; exact supplied coverage appears in the receipt; successful retry is idempotent; changed coverage/binding or conflicting ID refuses.
- Exercise real cross-process lock contention during source scans and later barrier admission for both persistent-bootstrap and supplemental-root locks; verify a deduplicated stable acquisition order.
- Inject an authority change between the initial read and lock acquisition and require refusal before canonical namespace mutation.
- Add real supplemental-root legacy evidence before onboarding and after successful onboarding; both must refuse without a barrier lease.
- Preserve existing missing-ACTIVE, traditional-only, downgrade refusal, post-write failure, and recovery tests.

### `docs/phase-loop/convergence-contracts.md` (modify)

- Document the supported explicit-root bootstrap binding, immutable retry coverage, held lock union, and actual zero-source checks. Clarify that choosing history roots remains an operator completeness assertion, and this repair does not attest the consumer's history or authorize production onboarding.

### Control artifacts (create/update)

- This detailed plan and resolver-owned planning/execution handoffs/reflections.
- `plans/manifest.json`: append the typed detailed entry and lifecycle through installed public helpers; preserve all existing entries and order.
- Runner verification artifacts under `.phase-loop/runs/1117-explicit-bootstrap-binding/**`, including actual command logs/seals. Read permission is limited to these generated artifacts and this run's resolved handoffs/reflections. No ignored credential, receipt, ledger or production authority payload is allowlisted.

## Documentation impact

Update the existing convergence contract document. No public API/schema change or generated skill changes are required. Full source ownership is the three source/test/doc paths above; dependency manifests, locks, package version, other test modules and shared installed environments are read-only.

## Dependencies & order

1. Write this plan, planning handoff/reflection and typed manifest registration serially. Planning ends without running tests.
2. Execute the explicitly requested bounded implementation under `codex-execute-detailed`; mark executing with the helper. Create an isolated environment from the repository's frozen dependency manifest, leaving shared tooling unchanged.
3. Add meaningful regressions first and run only the new regressions against unchanged source to capture the actual failure.
4. Apply the bounded broker/doc changes; run the complete bootstrap module, then the declared FABPUB subsystem suite and diff check through runner-owned verification.
5. Resolve any concrete failures within owned scope. Preserve the candidate and actual evidence locally, report acceptance/limits and write execution handoff/reflection. No commit, push, PR, production bootstrap/onboarding or global migration is authorized in this task.

## Verification

All commands run from this isolated worktree with `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests` and `PYTHONDONTWRITEBYTECODE=1`; pytest's existing autouse host-state isolation remains enabled. Only temporary fixture receipts/authority are created. Scratch environment: `/home/viperjuice/workspace/tmp/agent-harness-1117-binding/venv`.

- Environment refresh: `UV_PROJECT_ENVIRONMENT=/home/viperjuice/workspace/tmp/agent-harness-1117-binding/venv uv sync --python /opt/consiliency/tooling/current/python/bin/python --frozen --group test --project phase-loop-runtime`. The runner also detects `ci/dagger`'s Python 3.14 floor; use the genuine installed 3.14 interpreter for this isolated environment rather than uv's default 3.13. Actual interpreter-preflight refusals are retained as failed artifacts; they are not RED product regressions.
- RED regression evidence: the suite wrapper `uv run --frozen --group test --project phase-loop-runtime python -m pytest -q phase-loop-runtime/tests/test_fabpub_zero_history_bootstrap.py -k explicit_roots` with the scratch environment above.
- Bootstrap module: the same wrapper with `python -m pytest -q phase-loop-runtime/tests/test_fabpub_zero_history_bootstrap.py`.
- Required complete bounded subsystem suite: the exact `automation.suite_command` above (bootstrap, shared epoch, partition rotation, recovery controls and admission compatibility). No full repository suite or live-provider qualification is claimed.
- `git diff --check`.

Use installed `phase_loop_runtime.verification_evidence.run_verification` to execute/record the environment refresh, bootstrap module, diff check and required suite; cite its actual sealed `verification.json` and log. No hand-authored success evidence. The task authorizes focused validation; full repository/provider-dependent gates are outside this local repair closeout.

## Acceptance criteria

- [ ] Explicit-root onboarding authenticates and retains the real persistent bootstrap claim and cutover ID, without modifying its sealed inventory; receipt ACTIVE validation and activation barrier succeed — bootstrap module.
- [ ] Both bootstrap locks and supplemental-root locks are held during real source checks and subsequent lease admission; acquisition is deduplicated and sorted — cross-process contention regressions in bootstrap module.
- [ ] Conflicting cutover identity and changed authority before the seal refuse before canonical namespace mutation — bootstrap module.
- [ ] Retry returns the same receipt for unchanged binding/coverage and refuses altered immutable history coverage or binding — bootstrap module.
- [ ] Actual legacy evidence in supplemental roots, before onboarding or after receipt creation, blocks without a granted/stranded barrier lease — bootstrap module.
- [ ] Missing ACTIVE, traditional-only onboarding, bootstrap downgrade refusal, post-write failure and existing recovery behavior retain their fail-closed results — required bounded subsystem suite.
- [ ] Documentation describes behavior and operator completeness limits, with no new vocabulary or production authority assertion — source/doc review and `git diff --check`.
- [ ] All declared checks have actual runner logs/sealed evidence, and final dirty paths are owned by this plan — runner verification plus final status comparison.
