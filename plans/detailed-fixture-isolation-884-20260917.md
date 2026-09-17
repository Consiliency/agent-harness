---
type: detailed
status: planned
implementation_started: false
plan_approval: false
automation:
  suite_command: "./phase-loop-runtime/.venv/bin/python -m pytest -q -rs --tb=short phase-loop-runtime/tests/test_common_directory_leases_807.py phase-loop-runtime/tests/test_convergence_fencing.py phase-loop-runtime/tests/test_fabpub_shared_epoch.py phase-loop-runtime/tests/test_train_prebuilt.py"
---

# Detailed plan: isolate agent-harness#883 Git fixtures for agent-harness#884 N3

## Task

Repair the confirmed agent-harness#884 N3 fixture-isolation defect inside the existing draft agent-harness#883. Make the smallest tests-only change: prevent repository-routing Git environment variables from redirecting fixture setup or child namespace resolution, while leaving agent-harness#884 open for its other residuals.

## Bound inputs and review truth

- Planning baseline: branch `codex/leases-807-integration-20260917`, HEAD `3d99a5a284add0fbe1ba66ad384165c48ef004fc`. The integrated production candidate remains `87d7c9e9c80438cfdde23bd2769065a7d8ba7118`.
- Current test input SHA-256 is `283dc82212a6c4d7e8002500170479d5e23fef8c61f9f0de8b55214b1344042a`; unchanged production `fencing.py` is `9af4f517b50b04bdc101df3320ddedced3782cfb2eb5f5a5449cfa7e6acdc5c3`.
- Frozen revision inputs `00` through `07` have SHA-256 values `283dc82212a6c4d7e8002500170479d5e23fef8c61f9f0de8b55214b1344042a`, `3e7f8422869aae49641c344a2ece95c947709113f3408ca8ebacd480343f3933`, `474cea8c83de139041a09c6e182b8e73454d699240825baaf2b7e6bb428665ce`, `507e29e2c30fbb62b547d150814b8f963d3a82ece81777a19b7c8b7c84b35695`, `409cff68755d258fab590cacea743cb321245a12d586d9e35a853019124ce8ea`, `14d245bfb053c4a3db957b97c5ffde67347246dabbda50863d8801df356e92b4`, `7f6355760d94eca5c40bc6bfe7dbd6ffee8a8e8be53b75448db1009bd674288c`, and `33c104f50be82a12be478d0bf3022f5aba7ec5312b6f1d9c1cd714d85fecca8c`, respectively. The source-review binding is `79c8f6e86a5381955b6fd5bf3b77aab6a2f0720583bbaba63b9695affffb18f7`; retained narrow/summary/affected records are `d12363d34713e546e5a6bfd5fdf5056b88c26c22f1695e33846a906c13526c79`, `fb3426c010d531055fca655f03e53e136f7e5efe5897c574d0cf252b94ba4468`, and `038ddcccb9192b01a735bb4b907818b85dee94bec33a20ed18a81c960ad6559c`.
- Historical evidence remains exactly: the original source repair retained RED at 3 failed / 4 passed; the final cross-process test was strengthened later; the prior candidate then passed 7 narrow and 64 affected cases. Do not recast the strengthened test as part of the original RED.
- The disposable reproduction `3e7f8422869aae49641c344a2ece95c947709113f3408ca8ebacd480343f3933` changed an external temporary repository HEAD and left the intended fixture without `.git`; no live workspace was supplied or changed.
- Preserve the terminal review at `2026-09-17T08:05:08Z` (`result_sha256=da6892181bd82c670e46b4749dd59b1889f072baed03335f2f3b81ee208fd6f6`): Sol/Codex `DISAGREE` with N3 blocking, Gemini and Grok `AGREE`, and Fable/Claude `DEGRADED` for provider output limit. It grants neither plan nor source approval.
- No panel round has been dispatched for this fixture plan. Its status is `planned`, `implementation_started=false`, and `plan_approval=false`; this correction authorizes no tests or implementation.

## Research summary

`phase-loop-runtime/tests/test_common_directory_leases_807.py` has two environment-inheriting boundaries: `git()` invokes Git without `env`, and `environment()` copies all of `os.environ` into children. `phase-loop-runtime/src/phase_loop_runtime/cli.py:3513-3525` already defines the exact repository-location vocabulary; duplicate that tuple test-locally without changing runtime code. The append-only agent-harness#883 ledger is in `plans/decision-interim-president-ratification-20260904.md`; after new candidate evidence exists, add a corrective row without changing any previous row bytes.

## Frozen scope

- Modify only the test module during code repair. `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py` and every existing test body, decorator, parameter, and assertion remain byte-for-byte unchanged.
- The exact scrub set is `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_NAMESPACE`, `GIT_CEILING_DIRECTORIES`, `GIT_DISCOVERY_ACROSS_FILESYSTEM`, `GIT_GRAFT_FILE`, and `GIT_SHALLOW_FILE`.
- Those names cover repository/worktree/common-directory routing, index routing, object storage/alternates, ref namespaces, discovery boundaries/cross-filesystem discovery, and graft/shallow ancestry metadata. Introduce no new vocabulary and do not blanket-remove harmless variables such as `GIT_PAGER`.
- This is test infrastructure only: no production-code, API/schema, release, HARDEN/RUNTIME, V10, or downstream acceptance claim.

## Changes

### `phase-loop-runtime/tests/test_common_directory_leases_807.py` (modify)

- `_GIT_LOCATION_ENV` — add — copy the exact frozen 11-name tuple above for both helper boundaries.
- `test_fixture_helpers_scrub_repository_routing_git_environment` — add — create only under `tmp_path` an external Git repository with a committed tracked baseline and populated index; record its HEAD and exact index bytes using an explicitly scrubbed control environment.
- The same regression — add — create a separate intended fixture, then use `monkeypatch` to set at least `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, and `GIT_INDEX_FILE` to paths inside that disposable external repository. Call the real `git()` helper for intended `init` and commit, and launch a Python child with `environment()` to print `repository_namespace_root(intended)`.
- The same regression — add — assert the external HEAD and index bytes are unchanged, the intended directory owns `.git` and its commit, and the child resolves the intended namespace. Before the helper repair, the focused node must fail because commit and/or namespace resolution is redirected to the disposable external repository.
- `git()` and `environment()` — modify only after RED review/freeze — filter `os.environ` by exact membership in `_GIT_LOCATION_ENV`; `environment()` then overlays only its existing `PYTHONPATH`. Preserve all other variables, including `GIT_PAGER`.

### `plans/decision-interim-president-ratification-20260904.md` (append after GREEN)

- Corrective/additional `Consiliency/agent-harness#883` row — append — retain every byte of all previous ledger rows and add the N3 regression, observed RED, helper-only repair, exact verification/review evidence, and then-current candidate identity. Explicitly qualify prior isolation wording as **provider-isolation**, not Git fixture or repository-environment isolation. Preserve the older 3-failed/4-passed chronology, the later cross-process strengthening, the original Sol dissent, and the fact that agent-harness#884 stays open for N1/N2/N4/N5 residuals.

### `plans/manifest.json` (modify metadata only)

- `fixture-isolation-884-20260917` — modify — bind this correction's exact plan digest in the existing row, then append truthful executor/review lifecycle events during execution. Never claim implementation, approval, verification, publication, merge, or CI before its corresponding evidence exists.

## Documentation impact

No product documentation or API/schema change. Only an append-only corrective governance ledger row and this plan's lifecycle need truthful evidence updates because the repair is tests-only.

## Dependencies and order

1. Obtain the required exact-digest plan review before any test or implementation work; no fixture-plan panel round has yet been dispatched.
2. Add only `_GIT_LOCATION_ENV` and the disposable regression; do not alter `git()` or `environment()` yet.
3. Before any baseline run, independently review and freeze the additive regression against input `283dc82212a6c4d7e8002500170479d5e23fef8c61f9f0de8b55214b1344042a`; bind its exact bytes and record an explicit verdict that all original test bodies, decorators, parameters, and assertions are unchanged.
4. Run that exact reviewed and frozen focused node against the pre-helper-repair baseline. Retain real RED from disposable external commit and/or namespace redirection; a collection error, missing fixture, or synthetic assertion is not acceptable RED.
5. Bind the RED artifact and disposable-path proof to the already-reviewed test bytes, then apply the helper-only repair to `git()` and `environment()` using the frozen tuple without editing the reviewed regression.
6. Rerun the same frozen node, the original seven cases, then the existing 64 affected cases. Do not run a local full suite for this bounded repair.
7. Produce native verification and source-identity records, append the corrective ledger row and lifecycle evidence truthfully, perform a scoped staged audit, and request a fresh exact-head review that carries the original dissent rather than overwriting it.
8. The coordinator alone owns commit/publication. Required CI runs through normal publication; no merge or acceptance claim is permitted before fresh review convergence and green required CI.

## Verification

Run from the repository root, in this order during implementation:

```sh
./phase-loop-runtime/.venv/bin/python -m pytest -q -rs --tb=short phase-loop-runtime/tests/test_common_directory_leases_807.py::test_fixture_helpers_scrub_repository_routing_git_environment
./phase-loop-runtime/.venv/bin/python -m pytest -q -rs --tb=short phase-loop-runtime/tests/test_common_directory_leases_807.py::test_each_worktree_keeps_its_lease_without_locking_one_namespace_twice phase-loop-runtime/tests/test_common_directory_leases_807.py::test_other_process_cannot_enter_a_linked_worktree_while_primary_holds_lock phase-loop-runtime/tests/test_common_directory_leases_807.py::test_rejected_second_generation_releases_earlier_lease_and_shared_lock
./phase-loop-runtime/.venv/bin/python -m pytest -q -rs --tb=short phase-loop-runtime/tests/test_convergence_fencing.py phase-loop-runtime/tests/test_fabpub_shared_epoch.py phase-loop-runtime/tests/test_train_prebuilt.py
sha256sum phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py
git diff --cached --name-only
git diff --cached -- phase-loop-runtime/tests/test_common_directory_leases_807.py plans/decision-interim-president-ratification-20260904.md plans/manifest.json
```

Only after independent review freezes the additive test does the first command run once against the pre-helper-repair baseline for RED; its artifact must bind that RED to the reviewed test bytes. The same frozen command runs again after helper repair for GREEN. Native artifacts must bind each command, exit status, candidate head, interpreter, changed test SHA-256, and unchanged `fencing.py` SHA-256. This new fixture-isolation RED is additional evidence: it neither replaces nor retroactively strengthens the historical actual 3-failed/4-passed RED, whose final cross-process test was strengthened later. If normal publication produces an installed runtime, also bind its resolved `fencing.py` identity to source; do not fabricate an installed identity for the non-installed test module.

## Acceptance criteria

- [ ] Before its baseline run, an independent frozen-test review binds the additive regression's exact bytes and confirms every original test body/decorator/parameter/assertion is unchanged.
- [ ] That exact already-reviewed focused node has retained pre-helper-repair RED from actual disposable commit/namespace redirection, proven by the first pytest command and a native RED artifact bound to the reviewed test bytes; this evidence remains distinct from the historical actual 3-failed/4-passed RED and later strengthening.
- [ ] Both helpers remove exactly the 11 frozen routing names while preserving `GIT_PAGER` and other harmless environment, proven by the staged test-file diff.
- [ ] The focused node passes after repair and proves exact external HEAD/index preservation plus an owned intended `.git`, commit, and namespace, proven by the first pytest command's GREEN artifact.
- [ ] All original seven cases pass unchanged, proven by the second pytest command and frozen-test review.
- [ ] All existing 64 affected cases pass, proven by the third pytest command.
- [ ] `fencing.py` remains SHA-256 `9af4f517b50b04bdc101df3320ddedced3782cfb2eb5f5a5449cfa7e6acdc5c3`, and the scoped staged audit contains only the test file plus truthful ledger/lifecycle recording; native source/installed identities are bound where applicable.
- [ ] The exact-head review artifact preserves the original `2026-09-17T08:05:08Z` dissent, agent-harness#884 remains open, the append-only corrective ledger row retains every previous row byte and qualifies prior isolation wording as provider-isolation, lifecycle/ledger claims match evidence, and required published-candidate CI is green before the coordinator lands agent-harness#883.
