# Detailed plan: split the per-PR gate — PRs never run the CONFORM chronology node; main + nightly always do; a red main files its own issue

Issue: Consiliency/agent-harness#746 (item 2 of the CI plan; item 1 = Consiliency/agent-harness#741, items 3/4 = Consiliency/agent-harness#747 / #748).
Revision: r2 (r1 reviewed by a 4-seat board; the DISAGREE findings are folded in below).

## Task

Make the per-PR `suite gate` hermetic-fast by moving the one expensive proof — the CONFORM
chronology node — out of ordinary pull-request runs entirely, keeping it on every push to
`main`, the nightly, and every default `workflow_dispatch`, and adding a red-on-main response so
a regression deferred to the landing push is filed (and the filing closed again on the next
green), not just logged. Record gate minutes and rerun count per merged PR so the split's
effect is measured, not assumed.

## Research summary

Measured on the last green push to `main` (run 33709063249, artifact `junit-offloaded`): the
offloaded job took 67 min; in each of the two lanes that run it, the node
`tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation`
took 50.1 min (py3.10) and 59.8 min (Gate A). Every other test summed to ~6 min per lane, and
no other node exceeds 1.2 min. So the "expensive proofs" are ONE node, and the split is one
selection change, not a tiering system.

After Consiliency/agent-harness#741, `ci/chronology-scope.sh` decides per run: `CHRONOLOGY_FORCE`
(the `workflow_dispatch` input `chronology`, default `true`) wins outright; then `push` /
`schedule` / `workflow_dispatch` / unknown → retain (fail closed); `pull_request` → retain iff
the diff touches `phase-loop-runtime/*`, `ci/*`, or the two workflows. Because almost every PR
touches `phase-loop-runtime/*`, the three most recent PR runs (33699238334, 33694810927,
33693772385) all retained it: 67–72 min each. No deselected-node run has been measured yet;
`test.yml`'s "~8 min when it is deselected" (offload job comment) is a projection.

Selection consumers OUTSIDE `ci/*` (they are the plumbing the new PR rule must keep on the full
gate): `phase-loop-runtime/scripts/chronology_witness.py` (proves the decision against each
lane's junit), `phase-loop-runtime/scripts/gate_a_cleanroom.sh` (Gate A's
`GATE_A_DESELECT_CHRONOLOGY` consumer + witness call) and `phase-loop-runtime/scripts/_gate_a_probe.py`
(its probe). `ci/offload-gate.sh` and `ci/dagger/**` are already under `ci/*`.

Junit evidence layout (inputs, pinned by #741): eligible runs upload `junit-offloaded` =
`junit-offload/py310/junit-py310.xml` + `junit-offload/gate-a/junit-gate-a.xml`; the hosted
fallback uploads `chronology-junit-py310` and `chronology-junit-gate-a`.

Reusable machinery, all landed by Consiliency/agent-harness#741 and kept as-is:
- `ci/chronology-scope.sh --node` is the single spelling of the node id;
  `test_every_consumer_spells_the_same_node_id` pins every consumer to it.
- The `chronology-retention` guard job reads the workflow and the scope script as data and
  fails if `push`/`schedule`/`workflow_dispatch`/unknown events stop retaining the node, or if
  no matrix lane runs it. It does NOT constrain the `pull_request` branch — this plan's change
  is inside its envelope by construction.
- The Dagger module (`ci/dagger/src/agent_harness_ci/main.py`) takes the scope decision as a
  `chronology` argument and needs no change.

Repository inputs this plan pins (checked 2026-09-03): PRs land with merge commits
(`gh pr merge --merge`), so `git log --merges` over a `main` range enumerates landed PRs;
`default_workflow_permissions` is `read`, which a job-level `permissions:` block may raise for
non-fork events (the reporter never runs on `pull_request`); no `ci-main-red` label exists yet.

## Exception record (rule relaxed by this plan)

Per `docs/agent-phase-convergence.md` → "Exceptions, and how to take one": a relaxed gate is
recorded with the rule, the reason, and an owner.
- **Rule relaxed:** a pull request no longer executes the CONFORM chronology node unless its
  diff touches the gate's own selection plumbing (table below).
- **Reason:** the node is ~88% of per-PR wall clock (measured above) and proves a property of
  frozen history, not of the diff under review; the landing push to `main` executes it on the
  exact merged tree, the nightly bounds how long a regression can stay invisible.
- **Owner:** the operator (repository owner), via Consiliency/agent-harness#746.
- **Accepted limitation (recorded, not fixed):** a change that hollows the proof's oracle —
  e.g. a `conftest.py`/fixture change that makes the node pass vacuously — is green on the PR
  (node not run) and green on `main` (hollow node passes). This class is not new: the same
  change executed on the PR today would also pass. The node's own vacuity guards
  (`--collect-only` pin, junit witness) are unchanged. A merge commit whose message carries
  `[skip ci]` would also bypass the landing proof; the nightly is the bound in both cases.

## Changes

### `ci/chronology-scope.sh` (modify)
- header comment — modify — state the new property: PRs defer the node to the landing push and
  the nightly, except a PR that changes the gate's own selection plumbing; drop the paragraph
  that justifies the runtime-wide diff table.
- `chronology_input_path` — modify + rename to `gate_plumbing_path` — the table becomes exactly:
  `ci/*`, `.github/workflows/test.yml`, `.github/workflows/publish-pypi.yml`,
  `phase-loop-runtime/scripts/chronology_witness.py`,
  `phase-loop-runtime/scripts/gate_a_cleanroom.sh`,
  `phase-loop-runtime/scripts/_gate_a_probe.py`. The `phase-loop-runtime/*` arm is removed.
  Per-file, not `phase-loop-runtime/scripts/*`: the other scripts there
  (`regenerate_skills_bundle.py`, `sync_skills_bundle.py`, `check_model_id_sources.py`,
  `sweep_fleet_worktrees.sh`) are not selection plumbing.
- `decide` reasons in the PR branch — modify — "PR touches gate plumbing: <path>" /
  "PR defers the chronology node to the landing push (<count> paths changed)".
- Unchanged: `--node`, `--match`, the `CHRONOLOGY_FORCE` override (so a `workflow_dispatch`
  with `chronology=false` still deselects — that is the measurement lever), the fail-closed
  arms (no base, unknown event, diff failure), NUL-terminated `--no-renames` listing.

### `ci/main-red.sh` (create)
- the reporter body, out of YAML so it is testable with a stub `gh` — add — reads env
  `GATE_RESULT` (`failure`|`success`), `GITHUB_RUN_ID`, `GITHUB_SERVER_URL`, `GITHUB_REPOSITORY`,
  `GH_TOKEN`; `set -euo pipefail`.
  - Both branches first: `gh label create ci-main-red --force --color B60205
    --description "suite gate is red on main"` (idempotent; `--force` updates instead of
    failing when the label exists).
  - `GATE_RESULT=failure`: `green="$(gh run list --workflow test.yml --branch main --event push
    --status success --limit 1 --json headSha --jq '.[0].headSha')"`; range text =
    `git log --merges --oneline "$green..HEAD"` when `green` is non-empty and resolvable, else
    `git log --oneline -20` (no green run, or a squash-landed range with no merge commits →
    the plain log, labelled as such); failing jobs =
    `gh run view "$GITHUB_RUN_ID" --json jobs --jq '[.jobs[] | select(.conclusion=="failure")
    | .name] | join(", ")'`; `open="$(gh issue list --state open --label ci-main-red --limit 1
    --json number --jq '.[0].number')"`; if `open` is non-empty → `gh issue comment "$open"
    --body-file <tmp>`, else `gh issue create --label ci-main-red --title "suite gate red on
    main: run $GITHUB_RUN_ID" --body-file <tmp>`. The body carries the run URL
    (`$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID`), the failing job
    names, and the range text.
  - `GATE_RESULT=success`: for every open `ci-main-red` issue, `gh issue close <n> --comment
    "suite gate green again on main: run <url>"`; no-op when none is open.
  - Any other `GATE_RESULT` → exit 2 with a message (never a silent no-op).
  Deliberately NOT in scope: auto-bisect (the node is ~55 min, the merge range since the last
  green push is typically 1–3 PRs, and the issue lists them) and auto-revert (the node is
  contention-fragile on `ai`; a false red must not revert good work). Both are cut, not
  deferred — if the measurement below shows the range is routinely > 3 PRs, that is a new plan.

### `.github/workflows/test.yml` (modify)
- top-of-file comment on the `schedule` trigger — modify — say PRs never run the node unless
  they touch gate plumbing; push-to-main is the landing proof, nightly the backstop.
- `main-red` job — add — `needs: gate`; `if: always() && github.event_name != 'pull_request'
  && github.ref == 'refs/heads/main' && (needs.gate.result == 'failure' || needs.gate.result
  == 'success')` (cancelled/skipped gates report nothing; a dispatch on a non-default ref
  reports nothing); job-level `permissions: { contents: read, actions: read, issues: write }`
  (`actions: read` is what `gh run list`/`gh run view` need — a job-level block REPLACES the
  defaults, it does not extend them; the workflow's top-level stays `contents: read`);
  job-level `concurrency: { group: main-red, cancel-in-progress: false }` so two reds landing
  close together serialize and the second one sees the first one's issue; steps: checkout
  (`fetch-depth: 0`), then `run: bash ci/main-red.sh` with `env: { GATE_RESULT:
  ${{ needs.gate.result }}, GH_TOKEN: ${{ github.token }} }`. Not in `gate`'s `needs`, so a
  reporter failure never masks or unmasks the gate result.
- the `suite (offloaded to ai)` job comment "~8 min when it is deselected" — modify — replace
  with the measured value from Verification step 1.

### `.github/workflows/publish-pypi.yml` (modify)
- comment at ~line 96–97 ("test.yml already runs it wherever ci/chronology-scope.sh retains
  it") — modify — wording only, to match the new PR rule; no behaviour change (it already
  deselects on `pull_request`).

### `ci/gate_metrics.py` (create; underscore — it is imported by its test)
- `rows(prs, runs_for, plumbing_for)` — add — pure: for each PR dict
  (`number,headRefName,headRefOid,mergedAt`) take the runs whose `headSha == headRefOid`
  (a `pull_request` run's `headSha` is the PR branch tip, never the merge commit, so
  `mergeCommit` is NOT a join key); `executions = sum(run["attempt"])` (a `gh run rerun` is a
  new attempt of the same run record, not a new record); `reruns = executions - 1`;
  `minutes = (updatedAt - startedAt)` of the newest run on that head (`run_started_at` resets
  per attempt, so this is the last attempt's wall clock); `plumbing = yes|no` from
  `plumbing_for(number)`. A PR with no run on its final head prints `minutes=-` and is excluded
  from the median.
- `main()` — add — stdlib + `gh`: `--last N` (default 10) → `gh pr list --state merged
  --base main --limit N --json number,headRefName,headRefOid,mergedAt`; or `--pr N [N ...]`
  → `gh pr view N --json ...` each. Per PR: `gh run list --workflow test.yml --event
  pull_request --branch <headRefName> --limit 50 --json
  databaseId,headSha,attempt,status,conclusion,startedAt,updatedAt`; plumbing =
  any path from `gh pr diff N --name-only` for which `bash ci/chronology-scope.sh --match
  <path>` prints `match`. Prints one row per PR (`number minutes executions reruns plumbing`)
  and a final line: median minutes over `plumbing=no` rows, share of PRs with `reruns == 0`.
  If `gh` is not on `PATH` or `gh auth status` fails: exit 2 with a message, never an empty
  table. Read-only; no persistence.

### `phase-loop-runtime/tests/test_ci_chronology_scope.py` (modify)
- `_chronology_inputs`, `test_every_chronology_input_is_classified_as_an_input`,
  `test_every_conftest_bootstrapped_plugin_is_a_chronology_input` — delete — they pinned the
  runtime-wide diff table this plan removes (the `--match` assertions inside the first one,
  currently the block asserting `phase-loop-runtime/src/.../panel_invoker.py` … `protocol.md`
  all `match`, go with it).
- `test_gate_plumbing_table_is_exactly_the_selection_consumers` — add — every path the
  workflow's scope/witness/Gate A steps reference (`ci/chronology-scope.sh`, `ci/offload-gate.sh`,
  `ci/main-red.sh`, `scripts/chronology_witness.py`, `scripts/gate_a_cleanroom.sh`,
  `scripts/_gate_a_probe.py`, both workflow files) is `match`; and the negative controls
  `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`,
  `phase-loop-runtime/tests/test_unrelated.py`, `phase-loop-runtime/tests/conftest.py`,
  `phase-loop-runtime/scripts/regenerate_skills_bundle.py`, `README.md` are `no-match`.
- `test_pull_request_touching_an_input_retains_the_node`,
  `test_pull_request_renaming_an_input_out_of_the_table_retains_the_node`,
  `test_pull_request_touching_a_fixture_vector_retains_the_node`,
  `test_pull_request_touching_a_quoted_pathname_retains_the_node` — modify — retarget the
  positive cases at gate-plumbing paths (`ci/x.sh`, `.github/workflows/test.yml`,
  `phase-loop-runtime/scripts/chronology_witness.py`) and add
  `test_pull_request_touching_only_the_runtime_defers_the_node`: a PR touching
  `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` and
  `phase-loop-runtime/tests/test_x.py` yields `chronology=false`. The quoted-pathname case
  keeps exercising the NUL listing with a gate-plumbing path.
- `test_workflows_retain_the_node_on_main_nightly_and_release` — modify — additionally assert
  the `main-red` job exists; its `if:` contains the literal predicates
  `github.event_name != 'pull_request'`, `github.ref == 'refs/heads/main'`,
  `needs.gate.result == 'failure'` and `needs.gate.result == 'success'`; its `permissions`
  equals `{contents: read, actions: read, issues: write}`; its `concurrency.group == "main-red"`
  with `cancel-in-progress: false`; the top-level `permissions` is still `{contents: read}`;
  and `gate.needs` does not contain `main-red`.
- Unchanged: witness tests, `test_non_pull_request_events_always_retain_the_node`,
  `test_pull_request_without_a_base_fails_closed`, `test_force_overrides_every_scope`,
  `test_pull_request_touching_only_prose_deselects_the_node`,
  `test_pull_request_with_an_unresolvable_base_fails_closed`,
  `test_every_consumer_spells_the_same_node_id`.

### `phase-loop-runtime/tests/test_ci_main_red.py` (create)
- `_stub_gh(tmp_path, *, open_issue)` — add — writes an executable `gh` into a temp `bin/` that
  appends its argv to a log file and answers `run list` (a fixed sha), `run view` (one failed
  job), `issue list` (empty, or one number), and exits 0 for `label create`, `issue create`,
  `issue comment`, `issue close`; the test runs `ci/main-red.sh` with `PATH=<bin>:/usr/bin:/bin`
  inside a throwaway git repo with two merge commits past the "green" sha.
- `test_red_with_no_open_issue_creates_one` — add — the log contains exactly one
  `issue create --label ci-main-red --title ... --body-file ...` and no `issue comment`; the
  body file names the run URL, the failing job, and both merge subjects.
- `test_red_with_an_open_issue_comments_instead` — add — exactly one `issue comment <n>`,
  zero `issue create`.
- `test_green_closes_the_open_issue_and_is_a_noop_otherwise` — add — with an open issue: one
  `issue close <n> --comment ...`; without: no `issue` call at all.
- `test_label_is_ensured_idempotently_before_use` — add — `label create ci-main-red --force`
  precedes the first `issue` call in both branches.
- `test_unknown_gate_result_exits_2` — add.

### `phase-loop-runtime/tests/test_ci_gate_metrics.py` (create)
- `test_rows_joins_runs_on_head_ref_oid_not_merge_commit` — add — one PR
  (`headRefOid=aaa`) with runs `[headSha=aaa attempt=1 success, headSha=aaa attempt=2 success,
  headSha=bbb attempt=1 failure]`: executions=2, reruns=1, minutes from the newest `aaa` run
  only, and a second PR whose only run is on a superseded head prints `minutes=-`.
- `test_cli_refuses_when_gh_is_absent` — add — run `[sys.executable, "ci/gate_metrics.py",
  "--last", "1"]` with `PATH` set to an empty temp dir: exit 2, message on stderr, nothing on
  stdout.

### `CHANGELOG.md` (modify)
- `[Unreleased]` — add — entry "CI: pull requests no longer run the CONFORM chronology node
  (Consiliency/agent-harness#746)": the measured split (one node = 50–60 min of a 67-min run),
  the new PR rule and the gate-plumbing table, the exception record (rule/reason/owner/
  limitation), the `main-red` job (files on red, closes on green, serialized), the cut
  decisions (no bisect, no revert) and `ci/gate_metrics.py`. Update the existing
  `ci/chronology-scope.sh` and `tests/test_ci_chronology_scope.py` bullets under the #741 entry
  so they do not describe the removed runtime-wide table as current.

## Documentation impact
- `CHANGELOG.md` — modify — as above (docs-audit CHANGELOG gate requires it).
- `docs/agent-phase-convergence.md` — modify — under "Exceptions, and how to take one", add one
  bullet pointing at this plan's exception record as the worked example of a recorded gate
  relaxation (rule / reason / owner / accepted limitation), so the next reader can tell it from
  a mistake. No other change.
- No `ci/README`: the header comments of `ci/chronology-scope.sh`, `ci/main-red.sh` and
  `test.yml` are the operator-facing documentation for the gate and are updated in place.

## Dependencies & order
1. Consiliency/agent-harness#741 must be on `main` (it owns the scope script, witness, and
   retention guard this plan edits). Branch from `main` after it lands.
2. Verification step 1 (the measured deselected-node run) comes BEFORE editing `test.yml`'s
   duration comment — the number goes in from the measurement, never from the projection.
3. Scope script + `test_ci_chronology_scope.py` change together (the test pins the table).
4. `ci/main-red.sh` + the `main-red` job + `test_ci_main_red.py` + the workflow static test
   change together.
5. `ci/gate_metrics.py` + its test land in THIS PR (acceptance criterion 1 reads its output).
6. The whole PR touches `ci/*` and `test.yml`, so its own run RETAINS the node — the deferral
   is first observed on the next runtime-only PR after merge (acceptance criterion 1).

Does not touch `phase-loop-runtime/src/**` (GOVLEAN non-goal: no client-facing primitive is
coupled to fleet CI). Does not touch `specs/phase-plans-v10.md` (LEGIBLE-owned).

## Execution Policy
- execute: effort=medium, reason=bash/YAML plumbing with static-contract tests; the subtle
  parts (reporter permissions, dedupe, serialization, the run→PR join) are each pinned by a
  hermetic test.

## Verification
All commands run from the repository root; `cd` only inside subshells.
```bash
# 1. Measure the deselected-node run BEFORE editing (fills the duration comment).
gh workflow run test.yml --ref main -f chronology=false
run_id="$(gh run list --workflow test.yml --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run_id" --exit-status
gh run view "$run_id" --json jobs --jq '.jobs[] | select(.name|test("offloaded")) | "\(.startedAt) \(.completedAt)"'
gh run download "$run_id" -n junit-offloaded -D /tmp/m1
python3 phase-loop-runtime/scripts/chronology_witness.py --junit /tmp/m1/py310/junit-py310.xml \
  --node "$(bash ci/chronology-scope.sh --node)" --expect absent

# 2. Hermetic contracts, CI-style (bare PATH: no agent CLIs, no real gh), bytecode-clean.
( cd phase-loop-runtime && env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT PATH=/usr/bin:/bin \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3 -m pytest -q -p no:cacheprovider \
  --no-header -o addopts="" tests/test_ci_chronology_scope.py tests/test_ci_main_red.py \
  tests/test_ci_gate_metrics.py )
ruff --version   # 0.15.5 in CI
ruff check ci/gate_metrics.py phase-loop-runtime/tests/test_ci_main_red.py \
  phase-loop-runtime/tests/test_ci_gate_metrics.py phase-loop-runtime/tests/test_ci_chronology_scope.py
bash -n ci/main-red.sh ci/chronology-scope.sh

# 3. The rule, by hand, on the PR classes.
GITHUB_EVENT_NAME=pull_request CHRONOLOGY_BASE_SHA="$(git merge-base origin/main HEAD)" bash ci/chronology-scope.sh  # this PR: chronology=true (touches ci/*)
bash ci/chronology-scope.sh --match phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py     # no-match
bash ci/chronology-scope.sh --match phase-loop-runtime/scripts/chronology_witness.py               # match
bash ci/chronology-scope.sh --match ci/main-red.sh                                                 # match
GITHUB_EVENT_NAME=push bash ci/chronology-scope.sh                                                 # chronology=true
GITHUB_EVENT_NAME=workflow_dispatch bash ci/chronology-scope.sh                                    # chronology=true
GITHUB_EVENT_NAME=workflow_dispatch CHRONOLOGY_FORCE=false bash ci/chronology-scope.sh             # chronology=false

# 4. Workflow shape (the same predicates the static test pins, asserted literally).
python3 - <<'PY'
import yaml
wf = yaml.safe_load(open(".github/workflows/test.yml"))
j = wf["jobs"]["main-red"]
for lit in ("github.event_name != 'pull_request'", "github.ref == 'refs/heads/main'",
            "needs.gate.result == 'failure'", "needs.gate.result == 'success'"):
    assert lit in j["if"], lit
assert j["permissions"] == {"contents": "read", "actions": "read", "issues": "write"}
assert j["concurrency"] == {"group": "main-red", "cancel-in-progress": False}
assert wf["permissions"] == {"contents": "read"}
assert "main-red" not in wf["jobs"]["gate"]["needs"]
print("main-red shape ok")
PY
# and the retention guard's own script on the edited workflow: run the `chronology-retention`
# job's python block verbatim (copy from test.yml) — it must still print "chronology node retained".

# 5. Junit witness on this PR's own run (it RETAINS: it touches ci/*).
pr_run="$(gh run list --workflow test.yml --event pull_request --branch "$(git branch --show-current)" --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run download "$pr_run" -n junit-offloaded -D /tmp/m5 \
  || gh run download "$pr_run" -n chronology-junit-py310 -D /tmp/m5   # hosted-fallback path
python3 phase-loop-runtime/scripts/chronology_witness.py \
  --junit "$(find /tmp/m5 -name 'junit-py310.xml' | head -n 1)" \
  --node "$(bash ci/chronology-scope.sh --node)" --expect present

# 6. Reporter: the hermetic stub-gh tests in step 2 are the proof of create/comment/close;
#    live smoke = after merge, wait for the first red push to main (or the nightly) and confirm
#    exactly one open ci-main-red issue; the concurrency group is a static pin (step 4), not
#    reproduced live.

# 7. Metrics.
python3 ci/gate_metrics.py --last 10
```
Edge cases: PR with an empty diff (count=0 → `false`); PR that renames `ci/x.sh` to
`tools/x.sh` (rename reports both endpoints → `true`); `main-red` when no green run exists
(plain `-20` log, still files); squash-landed range with no merge commits (plain log,
labelled); `gh` rate limit inside `main-red` (step fails loudly; the gate result is unaffected
because `main-red` is not in `gate`'s `needs`); a `workflow_dispatch` on a non-`main` ref (gate
runs, reporter skipped); `gate_metrics` PR with no run on its final head (`minutes=-`, excluded
from the median).

## Acceptance criteria
- [ ] The first pull request merged after this lands whose `ci/gate_metrics.py --pr <N>` row
      shows `plumbing=no` has `chronology=false` in its scope step log and its `junit-py310.xml`
      passes `chronology_witness.py --expect absent`; its `minutes` value is recorded in the PR
      closeout next to the Verification-step-1 measurement (the number is measured there, not
      pinned here).
- [ ] Every `push` to `main`, `schedule`, and `workflow_dispatch` run retains the node unless
      the dispatch passes `chronology=false` (`chronology-retention` job green; junit witness
      `--expect present` on `junit-py310.xml` of the first push-to-main run after merge).
- [ ] With the stub `gh`, a red gate with no open `ci-main-red` issue creates exactly one, a red
      with an open issue comments exactly once, and a green closes it; the live `main-red` job
      is serialized (`concurrency.group == main-red`) and never runs on `pull_request`, a
      non-`main` ref, or a cancelled/skipped gate.
- [ ] `( cd phase-loop-runtime && PATH=/usr/bin:/bin PYTHONPATH=src:tests python3 -m pytest -q
      tests/test_ci_chronology_scope.py tests/test_ci_main_red.py tests/test_ci_gate_metrics.py )`
      passes, and `ruff check` (0.15.5) is clean on the new/changed Python files.
- [ ] `CHANGELOG.md` `[Unreleased]` carries the entry, the #741 bullets no longer describe the
      runtime-wide diff table as current, and `docs/agent-phase-convergence.md` names this
      plan's exception record.
