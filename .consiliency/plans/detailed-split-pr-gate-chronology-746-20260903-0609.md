# Detailed plan: split the per-PR gate — PRs never run the CONFORM chronology node; main + nightly always do; a red main files its own issue

Issue: Consiliency/agent-harness#746 (item 2 of the CI plan; item 1 = Consiliency/agent-harness#741, items 3/4 = Consiliency/agent-harness#747 / #748).

## Task

Make the per-PR `suite gate` hermetic-fast (target < 15 min wall clock) by moving the one
expensive proof — the CONFORM chronology node — out of ordinary pull-request runs entirely,
keeping it on every push to `main` and the nightly, and adding a red-on-main response so a
regression deferred to the landing push is filed, not just logged. Record gate minutes and
rerun count per merged PR so the split's effect is measured, not assumed.

## Research summary

Measured on the last green push to `main` (run 33709063249, junit `junit-offloaded`):
the offloaded job took 67 min; in each of the two lanes that run it, the node
`tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation`
took 50.1 min (py3.10) and 59.8 min (Gate A). Every other test summed to ~6 min per lane, and
no other node exceeds 1.2 min. So the "expensive proofs" are ONE node, and the split is one
selection change, not a tiering system.

After Consiliency/agent-harness#741, `ci/chronology-scope.sh` decides per run: `push` /
`schedule` / `workflow_dispatch` / unknown → retain (fail closed); `pull_request` → retain iff
the diff touches `phase-loop-runtime/*`, `ci/*`, or the two workflows. Because almost every PR
touches `phase-loop-runtime/*`, the three most recent PR runs (33699238334, 33694810927,
33693772385) all retained it: 67–72 min each. No deselected-node run has been measured yet;
`test.yml`'s "~8 min when deselected" is a projection.

Reusable machinery, all landed by Consiliency/agent-harness#741 and kept as-is:
- `ci/chronology-scope.sh --node` is the single spelling of the node id;
  `test_every_consumer_spells_the_same_node_id` pins every consumer to it.
- `phase-loop-runtime/scripts/chronology_witness.py --expect present|absent` proves the
  decision against the junit each lane produced (a deselect that matches nothing shows up).
- The `chronology-retention` guard job in `.github/workflows/test.yml` reads the workflow and
  the scope script as data and fails if `push`/`schedule`/`workflow_dispatch`/unknown events
  stop retaining the node, or if no matrix lane runs it. It does NOT constrain the
  `pull_request` branch — so this plan's change is inside its envelope by construction.
- The Dagger module (`ci/dagger/src/agent_harness_ci/main.py`) takes the scope decision as a
  `chronology` argument and needs no change.

## Changes

### `ci/chronology-scope.sh` (modify)
- header comment — modify — state the new property: PRs defer the node to the landing push and
  the nightly, except a PR that changes the gate's own plumbing; drop the paragraph that
  justifies the runtime-wide diff table.
- `chronology_input_path` — modify — remove the `phase-loop-runtime/*` arm; keep `ci/*`,
  `.github/workflows/test.yml`, `.github/workflows/publish-pypi.yml` (a PR that edits the
  selection machinery runs the full gate; that is the only PR class that can silently break the
  node's selection before main sees it). Rename to `gate_plumbing_path` so the name says what
  the table now is.
- `--match` mode, `decide` reasons — modify — reason strings become "PR touches gate plumbing:
  <path>" / "PR defers the chronology node to the landing push (<count> paths changed)".
- Unchanged: `--node`, `CHRONOLOGY_FORCE`, the fail-closed arms (no base, unknown event, diff
  failure), NUL-terminated `--no-renames` listing.

### `.github/workflows/test.yml` (modify)
- top-of-file comment on the `schedule` trigger — modify — say PRs never run the node unless
  they touch gate plumbing; push-to-main is the landing proof, nightly the backstop.
- `main-red` job — add — `needs: gate`, `if: always() && github.event_name != 'pull_request'
  && needs.gate.result != 'success'`, job-level `permissions: { contents: read, issues: write }`
  (the workflow's top-level stays `contents: read`). Steps: checkout (`fetch-depth: 0`); find the
  last green `main` head via `gh run list --workflow test.yml --branch main --event push
  --status success --limit 1 --json headSha`; list `git log --merges --oneline
  <green>..HEAD` (fallback: `git log --oneline -20` when no green run exists); if an OPEN issue
  labelled `ci-main-red` exists, comment on it, else `gh issue create --label ci-main-red`
  with the run URL, the failing job names from `gh run view --json jobs`, and the merge range.
  Uses `GH_TOKEN: ${{ github.token }}`.
  Deliberately NOT in scope: auto-bisect (the node is ~55 min, the merge range since the last
  green push is typically 1–3 PRs, and the issue lists them) and auto-revert (the node is
  contention-fragile on `ai`; a false red must not revert good work). Both are cut, not
  deferred — if the measurement below shows the range is routinely > 3 PRs, that is a new plan.
- the `suite (offloaded to ai)` step comment "~8 min when it is deselected" — modify — replace
  with the measured value from Verification step 1.

### `.github/workflows/publish-pypi.yml` (modify)
- comment at ~line 97 that references "wherever ci/chronology-scope.sh retains it" — modify —
  wording only, to match the new PR rule; no behaviour change (it already deselects).

### `ci/gate-metrics.py` (create)
- `main()` — add — stdlib + `gh`: for the last N merged PRs (`gh pr list --state merged
  --limit N --json number,headRefName,mergedAt,mergeCommit`), list that PR's `test.yml` runs
  (`gh run list --workflow test.yml --event pull_request --branch <head> --json
  databaseId,status,conclusion,createdAt,updatedAt,headSha`) and print one row per PR: number,
  wall minutes of the run on the merged head, total run count (success + failure + cancelled),
  reruns = count − 1. Prints a final line with the median minutes and the share of PRs with
  reruns ≤ 1. Read-only; no persistence — the numbers are re-derived from GitHub on demand, so
  there is nothing to keep in sync.

### `phase-loop-runtime/tests/test_ci_chronology_scope.py` (modify)
- `_chronology_inputs`, `test_every_chronology_input_is_classified_as_an_input`,
  `test_every_conftest_bootstrapped_plugin_is_a_chronology_input` — delete — they pinned the
  runtime-wide diff table this plan removes.
- `test_pull_request_touching_an_input_retains_the_node`,
  `test_pull_request_renaming_an_input_out_of_the_table_retains_the_node`,
  `test_pull_request_touching_a_fixture_vector_retains_the_node`,
  `test_pull_request_touching_a_quoted_pathname_retains_the_node` — modify — retarget the
  positive cases at gate-plumbing paths (`ci/x.sh`, `.github/workflows/test.yml`) and add the
  inverse: a PR touching `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` and
  `phase-loop-runtime/tests/test_x.py` yields `chronology=false`. The quoted-pathname case
  keeps exercising the NUL listing with a gate-plumbing path.
- `--match` assertions at :98–108 — modify — runtime paths become `no-match`; the four plumbing
  paths `match`.
- `test_workflows_retain_the_node_on_main_nightly_and_release` — modify — additionally assert
  the `main-red` job exists, its `if:` excludes `pull_request`, and it declares `issues: write`
  at job level while the top-level `permissions` stays `contents: read`.
- Unchanged: witness tests, `test_non_pull_request_events_always_retain_the_node`,
  `test_pull_request_without_a_base_fails_closed`, `test_force_overrides_every_scope`,
  `test_pull_request_with_an_unresolvable_base_fails_closed`, `test_every_consumer_spells_the_same_node_id`.

### `phase-loop-runtime/tests/test_ci_gate_metrics.py` (create)
- `test_rows_from_fixture_runs` — add — feed `gate-metrics.py`'s row builder canned `gh` JSON
  (one PR with success+cancelled+success runs) and assert minutes, count=3, reruns=2, and that
  a run on a non-merged head is excluded from the minutes column.
- `test_cli_refuses_when_gh_is_absent` — add — with `PATH=/usr/bin:/bin` the script exits 2
  with a message, never prints an empty table as if it were data.

### `CHANGELOG.md` (modify)
- `[Unreleased]` — add — entry "CI: pull requests no longer run the CONFORM chronology node
  (Consiliency/agent-harness#746)": the measured split (one node = 50–60 min of a 67-min run),
  the new PR rule, the gate-plumbing exception, the `main-red` issue job, the cut decisions
  (no bisect, no revert) and `ci/gate-metrics.py`. Update the existing `ci/chronology-scope.sh`
  and `tests/test_ci_chronology_scope.py` bullets under the #741 entry so they do not describe
  the removed table as current.

## Documentation impact
- `CHANGELOG.md` — modify — as above (docs-audit CHANGELOG gate requires it).
- `docs/agent-phase-convergence.md` — no change — it discusses plan discipline, not gate
  selection; verified by grep for "chronology" before closing.
- No `ci/README`: the header comments of `ci/chronology-scope.sh` and `test.yml` are the
  operator-facing documentation for the gate and are updated in place.

## Dependencies & order
1. Consiliency/agent-harness#741 must be on `main` (it owns the scope script, witness, and
   retention guard this plan edits). Branch from `main` after it lands.
2. Verification step 1 (the measured deselected-node run) comes BEFORE editing `test.yml`'s
   duration comment — the number goes in from the measurement, never from the projection.
3. Scope script + its tests change together (the test pins the script's `--match` table).
4. `main-red` job + workflow static test change together.
5. `gate-metrics.py` + its test are independent of 3–4 and can land in the same PR or a
   follow-up if the PR grows past review comfort.

Does not touch `phase-loop-runtime/src/**` (GOVLEAN non-goal: no client-facing primitive is
coupled to fleet CI). Does not touch `specs/phase-plans-v10.md` (LEGIBLE-owned).

## Execution Policy
- execute: effort=medium, reason=bash/YAML plumbing with one static-contract test file; the
  only subtle part is the `main-red` job's permissions and dedupe, which the static test pins.

## Verification
```bash
# 1. Measure the deselected-node run BEFORE editing (fills the duration comment).
gh workflow run test.yml --ref main -f chronology=false
# then: gh run list --workflow test.yml --event workflow_dispatch --limit 1 --json databaseId
# gh run view <id> --json jobs --jq '.jobs[] | select(.name|test("offloaded")) | "\(.startedAt) \(.completedAt)"'

# 2. Scope script contract (fast, hermetic).
cd phase-loop-runtime && PYTHONPATH=src:tests python3 -m pytest -q tests/test_ci_chronology_scope.py tests/test_ci_gate_metrics.py

# 3. The rule, by hand, on the three PR classes.
GITHUB_EVENT_NAME=pull_request CHRONOLOGY_BASE_SHA=$(git merge-base origin/main HEAD) bash ci/chronology-scope.sh   # runtime-only diff → chronology=false
bash ci/chronology-scope.sh --match phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py  # no-match
bash ci/chronology-scope.sh --match ci/chronology-scope.sh                                       # match
GITHUB_EVENT_NAME=push bash ci/chronology-scope.sh                                                # chronology=true

# 4. Retention guard still passes on the edited workflow (same script the CI job runs).
python3 - <<'PY'
import yaml; wf=yaml.safe_load(open(".github/workflows/test.yml")); j=wf["jobs"]["main-red"]
assert "pull_request" in j["if"] and j["permissions"]["issues"]=="write" and wf["permissions"]=={"contents":"read"}
PY

# 5. Junit witness on the plan PR's own run: the PR touches ci/* so it RETAINS; a sibling
#    runtime-only PR opened after merge must show `--expect absent` in its uploaded junit.
python3 phase-loop-runtime/scripts/chronology_witness.py --junit junit-offload/py310/junit-py310.xml \
  --node "$(bash ci/chronology-scope.sh --node)" --expect present

# 6. main-red job: exercise on a throwaway branch by dispatching with a deliberately failing
#    step (edit in a fork or a `wip/` branch, never main), confirm an issue labelled
#    ci-main-red is created once and a second red comments instead of duplicating.

# 7. Metrics.
python3 ci/gate-metrics.py --last 10
```
Edge cases: PR with an empty diff (count=0 → false); PR that renames `ci/x.sh` to `tools/x.sh`
(rename reports both endpoints → true); `main-red` when no green run exists (falls back to
`-20` log, still files); `gh` rate limit inside `main-red` (step fails loudly; the gate result
is unaffected because `main-red` is not in `gate`'s `needs`).

## Acceptance criteria
- [ ] A pull request whose diff is confined to `phase-loop-runtime/**` completes `suite gate`
      in < 15 min wall clock on three consecutive PRs after merge, as printed by
      `python3 ci/gate-metrics.py --last 3`.
- [ ] Every `push` to `main`, `schedule`, and `workflow_dispatch` run retains the node
      (`chronology-retention` job green; junit witness `--expect present` on the py3.10 lane
      of the first push-to-main run after merge).
- [ ] A red `suite gate` on a non-PR event produces exactly one open `ci-main-red` issue naming
      the run and the merge range; a second red comments on it rather than opening another.
- [ ] `PYTHONPATH=src:tests python3 -m pytest -q tests/test_ci_chronology_scope.py
      tests/test_ci_gate_metrics.py` passes with `PATH=/usr/bin:/bin` (no agent CLIs).
- [ ] `CHANGELOG.md` `[Unreleased]` carries the entry and the #741 bullets no longer describe
      the runtime-wide diff table as current.
