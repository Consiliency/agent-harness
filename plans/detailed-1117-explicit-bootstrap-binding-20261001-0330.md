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

### Panel repair amendment — Consiliency/agent-harness#1211

The owner requested a full manual panel with tools and authorized draft updates. Round one at the existing draft input produced Gemini AGREE and Claude/Astra/Sol PARTIALLY AGREE. Their actual fixture probes establish three blockers under the existing criteria: aliases double-acquire one lock, relative supplemental coverage changes with the barrier's working directory, and a bootstrap appearing after an absent initial read can produce an unbound receipt. Merge remains pending; no production authority or history attestation is authorized.

Before source repair, add regressions for absolute `..` aliases, relative and symlink refusal, activation from another working directory, and an initially absent bootstrap becoming ACTIVE. Require the authority-slot lock during traditional-only scans. Canonicalize explicit roots with the existing `_canonical_input_path` boundary, retaining their order; reject non-absolute recorded receipt roots before barrier admission. Hold the bootstrap authority-slot lock even when absent and revalidate both presence and binding before repository mutation. These changes preserve the existing vocabulary, signatures, receipt schema and sealed global inventory. Clarify canonical coverage and ordered retries in the contract document.

Generated repair evidence/read allowlist: `.phase-loop/runs/1117-panel-fix/**` and this task's manual reports, launch metadata and streams under `/home/viperjuice/workspace/reviews/agent-harness-1117-explicit-bootstrap-binding/manual-panel-round*/**`. This includes only task-generated evidence; credentials and operational authority payloads remain excluded. Re-run the dissenting seats against the actual repair delta, carrying only a usable AGREE verdict. The predeclared cap remains three rounds.

Round two completed at `4b74951f`: all three dissenting seats remain PARTIALLY AGREE. Original blockers are closed, but traditional barrier onboarding pre-acquires a different lock set from nested onboarding: the absent bootstrap guard is missing and declared aliases are not canonicalized. The resulting inter-process and self-deadlocks violate criteria 2/6. Historical absolute `..` receipt roots are locked canonically but scanned by their original spelling, allowing actual legacy evidence to be skipped after an intermediate directory disappears (criterion 5).

Add RED regressions for a traditional barrier's complete sorted initial lock set, a declared `..` root in the compatibility pointer format, and a genuine historical absolute `..` receipt with a removed intermediate directory and actual legacy evidence. Canonicalize declared roots and include the bootstrap slot in the barrier's initial lock union; rescan the same canonical receipt roots under those locks. Revalidate the barrier's initial bootstrap selection under its slot lock before nested onboarding, so a bootstrap appearing before acquisition cannot introduce a different lock set; exercise that boundary before namespace mutation. Preserve historical receipt bytes and all public contracts. Run the same focused module and required five-module suite, then review the actual delta with the three dissenting seats in round three.

Round three completed at `04d43fbb`: Sol AGREE; Astra and Claude PARTIALLY AGREE; Gemini's round-one AGREE is carried. Astra reproduced a remaining lock/coverage counterexample: a missing intermediate directory conceals a symlink at a historical alias's normalized root, and resolving it again after locking can select a different, unlocked target. Claude reproduced two lock regressions: retaining the initially absent bootstrap slot after barrier return deadlocks first bootstrap apply against train fencing; a traditional receipt's double-leading-slash root and a canonical onboarding root can name the same lock twice. These findings break criteria 2/5/6. Every reviewer finished before the combined implementation repair.

Add genuine RED regressions against unchanged `04d43fbb` for historical receipt retargeting with a separate writer, cross-process acquisition of the onboarding-only bootstrap slot after deferred and traditional barriers return, and a real traditional cutover with a double-leading-slash manifest root followed by a mixed migrated/fresh barrier. The bounded repair checks lexically normalized ancestors in `_canonical_input_path`, retains validated receipt roots from lock selection through pre-lease proof, and canonicalizes traditional lock identities without rewriting authenticated receipt or pointer bytes. Acquire the onboarding-only absent bootstrap slot on a separate stack in the same sorted loop and release it before barrier return or failure; existing receipts' required bootstrap seals remain retained. Preserve public signatures, wire bytes, operator completeness limits and the complete initial lock union. Run the complete module and required five-module suite under a fresh seal. The predeclared three-round cap remains in force; an additional review round requires an owner decision.

During this repair the owner merged Consiliency/agent-harness#1211 at `04d43fbb` (merge commit `2c0fe9def587d2943251b41dde4cce829efd8081`). Its main tree is identical to the reviewed head. Prepare these remaining fixes on successor branch `codex/1117-panel-lock-closeout` based on that merge commit. Preserve all completed review rounds and failed verification attempts. The first complete repair check exposed a fixture incompatibility: canonical lock identities now refuse the relative spelling used to construct a genuine historical receipt. Construct that historical receipt while holding its resolved physical root lock, preserving the relative wire claim and the existing refusal assertion. Publication of a new follow-up and extension of the exhausted review cap remain operator decisions; preparing code and evidence is authorized.

### Owner-authorized president and round-five repair

The owner explicitly authorized continuing beyond the original cap and delegated scope decisions to a separate president. Round four at `2991aae6` completed: Claude and Astra report PARTIALLY AGREE; their actual reports and the validated Opus scope ruling are retained in the allowlisted manual-panel-round4 directory. Astra's native turn completed but its collector exit status was lost during the server restart; no exit status is fabricated. Prior Sol/Gemini approvals do not constitute exact-head approvals.

The president closes the three round-three findings but requires one bounded round-five repair: traditional non-zero-source receipts must retain support for symlinked and relative recorded root spellings. Normalize their lock identities physically without applying the rejecting zero-source boundary. Keep canonical validation for zero-source base receipts, onboarding roots, and authority roots. Add a genuine traditional cutover through a symlinked ledger directory, verify admission and unchanged authenticated bytes, capture RED against unchanged `2991aae6`, and preserve the existing double-slash regression. Re-run the sealed module and required five-module suite, then obtain fresh exact-head verdicts from all four reviewers. No schema, signature, vocabulary, or wire migration is authorized.

The inherited barrier-retained-seal versus apply writer-then-seal lock-order class is explicitly deferred to Consiliency/agent-harness#1218. The apply/fencing no-deadlock invariant is not established. Declared-root locks for deferred repositories remain held until barrier lease release. This bounded repair must not claim that general invariant or expand to repair the inherited class. The plan/PR must link the follow-up and describe this limitation before merge; mandatory checks and exact-head CI remain required.

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
- Panel-fix RED: the new `explicit_root_alias`, `relative_supplemental_root`, `absent_bootstrap` and `traditional_scan_guards_bootstrap` regressions against the unchanged reviewed source. Run the complete bootstrap module and the same bounded subsystem suite after repair, with the isolated environment's `bin` directory first on `PATH` so fixture subprocesses use the matching phase-loop command.
- Round-two RED: `historical_dotdot`, `traditional_barrier_guards`, `traditional_barrier_declared_alias` and `barrier_bootstrap_appearance` regressions against unchanged `4b74951f` source; then repeat the complete module, dependency refresh, diff check and declared five-module suite under a fresh seal.
- Round-three RED: `historical_dotdot_symlink`, `traditional_barrier_guards`, `deferred_barrier_releases` and `double_slash` against unchanged `04d43fbb` source. Preserve separate completed attempts, then repeat the complete bootstrap module, frozen dependency refresh, diff check and required five-module suite.

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
