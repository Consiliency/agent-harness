# Detailed plan: make missing evidence fail loudly (agent-harness#607 + agent-harness#601)

**Revision 7 — the retro window, and a guard that can actually be falsified.** Rev 3 was re-reviewed: codex DISAGREE, grok DISAGREE,
fable PARTIALLY AGREE. All three said the `evidence-gate` aggregate must go. Rev 4 cut it; rev 5
adds the decisive reason (which I did not have), un-cuts one piece rev 4 removed by mistake, and
records two defects that would otherwise have been rebuilt.

## Why the aggregate is cut — the decisive reason

**It converts a live gate into a snapshot.** `evidence-gate` samples sibling runs at time T and
concludes; nothing re-triggers it. `entry-doc-check` is time-dependent *by design* — a tag push
makes a previously-fresh pin stale. If it is re-run on the same head and **fails**, the
aggregate stays green and the merge proceeds, because under this design the individual
workflows are deliberately **not** required. Native required contexts flip that context red and
block.

So the aggregate is not merely redundant with the platform — it is **strictly weaker on a live
axis**, and it reports a stale absence-of-failure as present success. That is the plan's own
class, and it is architectural: no amount of polling discipline fixes it.

The supporting defects (any one sufficient):

1. **Self-dependency deadlock.** The completeness guard demands every unconditional
   `pull_request` workflow be declared; `evidence-gate.yml` is one. Declaring it makes the gate
   wait on its own `in_progress` run to the deadline, then fail. Omitting it fails the guard.
2. **It does not close the defect it names.** GitHub treats a conditionally skipped **job** as
   success for required-check purposes, so workflow-level `conclusion == success` passes while
   the intended evidence job never ran. `head_sha` alone also accepts a `push`/`dispatch` run in
   place of the missing `pull_request` run.
3. **The reconciler cannot make a stale PR report** — scheduled runs use the default-branch
   head; a required context must report on the PR head. It also specced only `actions: read`,
   while reporting needs `checks:`/`statuses: write`. It falls with the aggregate: native
   contexts reach event-less PRs for free, blocking as "Expected", with the same empty-commit
   remedy.
4. **Poll budget vs wall clock.** The declared set must include `test`, whose offload job allows
   **120 minutes** — a poller with a normal budget false-reds every PR during a busy window, on
   a *required* check, i.e. repo-wide.

## What rev 4 got wrong: the completeness guard survives

Rev 4 withdrew the completeness guard along with the aggregate. That was an over-cut. It is the
**one piece that closes the meta-hole** (workflow N+1 lands undeclared and is invisible), and no
branch-protection setting covers it. Keep it — but **host it in an already-required job**
(e.g. `lint (pyflakes)`: required, unconditional, already has a checkout) rather than in a new
workflow. Data-only: no polling, no API, no race, no self-dependency.

Honesty note to carry: without admin API the guard can only assert membership in the checked-in
declared list. **Declared-list == branch-protection remains a human mirror step.**

## Two defects that would otherwise have been rebuilt

- **The PyYAML `on:` footgun — vacuity inside the guard itself.** YAML 1.1 parses the bare key
  `on` as boolean `True`, so `wf.get("on")` is `None` for every workflow. A naive guard sees
  **zero** `pull_request` workflows, computes an empty unconditional set, and **passes
  vacuously** — absence-as-success, hiding in the very mechanism meant to detect it. Read
  `wf.get(True) or wf.get("on")`, or use a YAML 1.2 loader.
- **The completeness guard had no falsifier.** It was labelled load-bearing while nothing
  exercised it — the exact shape rev 1 shipped twice. **Required:** a fixture workflow
  unconditional on `pull_request` and absent from the declared list → guard **red**; the same
  fixture path-filtered → **green**.

## The agent-harness#601 half: placement was contradictory, and a red that blocks nothing is the class again

Rev 3 specified the inert-delta step "at the offload aggregation seam". Those paths exist only
in the offload job's workspace, so the step **never runs on the hosted/fork path** — the
detector silently does not exist for fork PRs, and an exactly-one-evidence-set assert cannot
rescue a step that never executes.

Respecify as an **`if: always()` job** with `needs: [offload, pytest, cleanroom]`, downloading
both artifact families (`junit-offload/{py310,gate-a}` from offload; `chronology-junit-py310` /
`chronology-junit-gate-a` from hosted), asserting **exactly one family present**, then running
`inert_delta`. **Wire it into `suite gate`'s `needs` and verdict** so its red actually blocks —
a detector whose red blocks nothing is the class again — while leaving the required-context set
unchanged.

## What remains

- **agent-harness#607 — operator action only.** Add the per-workflow required contexts. No code.
- **The completeness guard**, hosted in an already-required job, with the falsifier above.
- **agent-harness#601 inert-delta**, as respecified.

**Withdrawn:** `evidence-gate.yml`, `evidence-reconcile.yml`, `required-workflows.json`, and the
polling/aggregate design in every section below. Sections are retained for the surviving halves.

## Task

Close one defect class with three observed instances: **the absence of evidence renders
identically to the presence of a positive result.** A check that never ran, a test that was
never collected, and a job that was skipped all read as "green".

- **agent-harness#607** — a newly added workflow never runs against already-open PRs, so the
  first change to violate a brand-new gate can merge with the gate having never executed.
- **agent-harness#601** — tests inert in a CI lane are indistinguishable from tests that pass.

## Do this first — it is one operator action and it closes the observed instance

**Recommended before any of the work below.** `entry-point docs verification` is **not in the
required contexts** (verified live: `["suite gate","lint (pyflakes)","chronology retention
guard","docs-freshness audit","gitleaks","check"]`). That — not the absence of a gate — is why
agent-harness#545 merged ungated.

A required check that has **never reported** blocks merge as *"Expected — waiting for status
to be reported."* So had `entry-point docs verification` been required, GitHub's own mechanism
would have blocked agent-harness#545, and all 13 ungated PRs would be blocked today. **The
native platform already implements "no run ≠ pass."**

This is an operator action on branch protection, not a code change, and it is deliberately
**not** something this plan performs.

### So why build anything?

Stated because revision 2 omitted it and it is the load-bearing design decision:

| | native required-context | checked-in aggregate |
|---|---|---|
| closes the observed instance | **yes, immediately** | yes, after build + reconciler |
| covers agent-harness#601 (inert tests) | **no** | yes |
| required-context set | grows per workflow | stays minimal |
| `skipped satisfies required` pitfall | **still present** | avoided by demanding SUCCESS |
| reviewable in a diff | no — a setting no reviewer sees | yes |
| new failure modes | none | polling, congestion false-reds |

**Recommendation: take the operator action now, and scope the build to what it cannot do** —
the agent-harness#601 half, the `skipped satisfies required` pitfall, and diff-reviewable
declaration. Do not justify the gate by the instance the setting already fixes.

### Resolving a contradiction in revision 2

Rev 2 listed branch-protection changes as out of scope while proposing a gate with **zero
enforcement power until that same operator action makes it required**. Both halves cannot be
true. Resolved: the operator action is **in scope as a prerequisite and a recommendation**;
this plan simply does not perform it.

## What revision 1 got wrong

Recorded rather than silently corrected, because the errors are the plan's own subject matter.

1. **It gated on existence, not success — reproducing the class it closes.** Rev 1 failed only
   when a workflow had *no run*. A **failed, cancelled, or skipped** run *exists*, so the
   aggregate would have gone green over it. `suite gate` never had this defect: it requires
   `successes -ne 1` to fail (`.github/workflows/test.yml:138-152`), i.e. an actual SUCCESS.
   Rev 1 copied that job's **name and shape but not its contract.**
2. **The new gate would itself never run on already-open PRs.** Landing
   `evidence-gate.yml` does not trigger `pull_request` for PRs whose last push predates it —
   which is *precisely* agent-harness#607. Rev 1 proposed a gate with the defect it was built
   to detect, and its verification step only *observed* the hole rather than closing it.
3. **The agent-harness#601 half was wired to a seam that cannot supply its inputs.** Rev 1
   changed `gate_a_cleanroom.sh` to emit the canonical-lane junit. Gate A cannot: the
   canonical junit comes from a different stage. **The pairing already exists** —
   `ci/offload-gate.sh:49-51` exports `./junit-offload` from one DAG node, containing
   `py310/junit-py310.xml` and `gate-a/junit-gate-a.xml`. On the eligible path
   `pytest`/`cleanroom` are skipped, so offload *is* the suite of record. Rev 1 also attached
   the consumer to `suite gate`, which downloads no artifacts.
4. **`absent_from_collection` gated on *growth*** — the identical cardinality hole the plan
   explicitly rejects for skip counts. One test goes inert while another becomes live, the
   count is flat, the gate is green.
5. **Branch-keyed observation.** Rev 1's verification used `headBranch`; the correct key is
   **`head_sha`**, which is stable under force-push.

## Research summary

`suite gate` (`.github/workflows/test.yml:125-153`) is the correct precedent and this plan
still anchors on it — but on its **contract**, not its shape: `if: always()`,
`needs: [offload, hosted]`, and a demand for **exactly one SUCCESS**, failing with "Both
skipped means NO suite ran: that is a red, not a green." Its mechanism is an *intra-workflow*
`needs:` roll-up, which structurally cannot express "a different workflow produced no run".

The repo already has the right pattern for the cross-workflow case:
`agy_canary_evidence.py:7314-7337` requires `head_sha` + `completed` + `conclusion == success`.
agent-harness#607's half should be modeled on **that**, not on `suite gate`.

Measured inputs (all against `main` at `2344d030`; **they expire on any merge** — reseed
before implementing). **They have already expired twice while this plan was under review:**
`main` moved `2344d030` → `650c35ca` (agent-harness#603) → `ad48930e` (agent-harness#606).
The 13-ungated figure in particular is a property of a moment, not of the repo. Treat every
number below as an illustration of shape and re-measure before seeding anything: agent-harness#545 had **0 of 15** runs and merged 18 h after the gate
landed; **13 of 17** open PRs have never run the check (merge-simulated: 8 pass, 5 conflict,
**0 fail** — the hole is *latent, not realised*); Gate A junit diff gives **78**
skipped-here-live-there (73 legitimate / 5 unclassified / **0 confirmed accidental**), **41**
absent from collection with **no reason string**, **61** skipped in both lanes.

## Changes

> **Scope note.** Revision 5 withdrew `evidence-gate.yml`, `evidence-reconcile.yml`, and
> `required-workflows.json`, but left this section still creating them — so an implementer
> following the acceptance contract would have rebuilt the defect class the revision cut.
> Revision 6 rewrites the section to match. Nothing below creates a polling aggregate.

### Operator action — no code (closes the observed agent-harness#607 instance)

- Add the **per-workflow required contexts** to `main`'s branch protection. A required
  context that has never reported blocks merge as *"Expected — waiting for status to be
  reported"*, at **job identity**, with no polling and no new failure modes. This is an
  operator action; the plan does not perform it.

### `.github/workflows/test.yml` — completeness guard, hosted in an already-required job

- Add a **workflows-as-data** step to `lint (pyflakes)` (required, unconditional, already has
  a checkout) — modify. It fails when a workflow that triggers unconditionally on
  `pull_request` is absent from a checked-in declared list. Data-only: no polling, no API, no
  self-dependency, no race.
- **Scan `*.yml` AND `*.yaml`.** GitHub accepts both; scanning one extension is a direct
  false green in the guard itself.
- **PyYAML footgun.** YAML 1.1 parses the bare key `on` as boolean `True`, so a lookup of the
  string `"on"` returns `None` for every workflow: the guard then sees zero `pull_request`
  workflows and **passes vacuously**. Read `wf.get(True) or wf.get("on")`, or use a 1.2 loader.
- **Honest scope, recorded rather than implied:** branch protection requires **job/check
  contexts**, while this guard declares **workflow files**. A new gating *job* added inside an
  already-declared workflow stays invisible to it, and a conditional required job can still
  skip and satisfy protection. The guard closes the *new-workflow* meta-hole only. It does not
  close the skipped-job hole, and nothing in this plan does — that remains open and is not
  claimed as covered.

### `phase-loop-runtime/scripts/check_declared_pr_workflows.py` (create)

- The guard as a **standalone script** (`check_model_id_sources.py` precedent), taking
  `--workflows-dir` and `--declared` so it can be pointed at a **fixture directory**. The
  in-file precedent (`chronology-retention`, `test.yml:311-336`) is an inline heredoc, which
  **cannot be falsified** — falsifiers 1–4 require the guard be RUN, and an inline step gives
  them no executable path. Without this, acceptance criteria 1–2 are unmeetable as written.
  Invoke it from the `lint (pyflakes)` step.
- **Handle `on`-value polymorphism.** Every workflow here uses the mapping form today, but
  `on: [push, pull_request]` and `on: pull_request` are legal. A dict-assuming guard either
  **crashes in a required job — a repo-wide false red** — or silently misses the workflow.
- **Define "unconditional":** `paths:` / `types:` make a workflow conditional; `branches:`
  alone does not. Today's unconditional set is `docs-audit`, `entry-doc-check`,
  `release-consistency`, `scrub`, `test`; `skills-parity` and `publish-consiliency-harness` are
  path-filtered and stay out.

### `.github/declared-pr-workflows.json` (create)

- The checked-in declared list the guard reads. Named here because the guard needs one and the
  previously specified `required-workflows.json` was withdrawn with the aggregate.
- Without admin API this asserts membership in a checked-in list only; **declared-list ==
  branch-protection stays a human mirror step.**

### `.github/workflows/test.yml` — agent-harness#601 inert-delta

- New **`if: always()`** job with `needs: [offload, pytest, cleanroom]` — add. Downloads both
  artifact families (`junit-offload/{py310,gate-a}` from offload; `chronology-junit-py310` /
  `chronology-junit-gate-a` from hosted), asserts **exactly one family present**, then runs
  the inert-delta reduction.
- **Wired into `suite gate`'s `needs` and verdict**, so its red actually blocks. A detector
  whose red blocks nothing is this plan's own class.
- Placement matters: the offload seam alone never runs on the hosted/fork path, so a
  seam-local step would silently not exist there.
- **Download by ARTIFACT NAME.** The offload artifact is `junit-offloaded` (`test.yml:90`);
  `junit-offload/{py310,gate-a}` is the path family *inside* it. Hosted names are
  `chronology-junit-py310` (`:283`) and `chronology-junit-gate-a` (`:387`).
- **Family completeness, not presence:** a *partial* hosted family (py310 present, gate-a
  absent) must be **red**.
- **Known baseline entry — do not prune as stale:** the canonical py310 junit does not cover
  the second LEGIBLE pytest invocation (`test.yml:271-274`, no `--junitxml`), so LEGIBLE tests
  legitimately read as absent-from-collection versus Gate A.
- **Verify artifact download under `permissions: contents: read`** (`test.yml:8-9`) at
  implementation time. The withdrawn reconciler died partly on a permissions mis-spec.

### `phase-loop-runtime/scripts/inert_delta.py` (create)

- `inert_delta(canonical_junit, lane_junit)` — returns three **identity sets**:
  `skipped_here_live_there`, `absent_from_collection`, `skipped_in_both`. Never summed, never
  reduced to cardinality — an add/drop pair that preserves counts must still fail.
- `classify_inert(entry, allowlist)` — `legitimate` / `unclassified` / `accidental`.
  **`unclassified` fails.**
- In `scripts/`, **not** the published package, per the repo's CI-only-helper precedent
  (`check_model_id_sources.py`). **Invoke it as `python3 scripts/inert_delta.py`** — the
  earlier `python3 -m phase_loop_runtime.evidence_gate` form was impossible against this
  placement.

### `.github/inert-tests-baseline.json` (create)

- Identity-keyed allowed-skip set (seeded from a **fresh** measurement) and the
  expected-collection baseline. **Pruning rule:** an entry matching no collected test is
  itself a finding, or the allowlist rots into a rubber stamp. **Apply the same rule
  symmetrically to `.github/declared-pr-workflows.json`** — a deleted workflow otherwise leaves
  a stale declared entry forever and the human-mirror step drifts silently.

### `CHANGELOG.md` (modify)

- A new required check is a public surface; the docs-audit gate blocks a public-surface change
  without a committed entry.

## Dependencies & order

1. Pure functions in `scripts/inert_delta.py` first — the only part testable without CI.
2. Reseed every measured input; the numbers in this plan expired twice during review.
3. The completeness guard and the inert-delta job land **advisory** before anything gates on
   them.
4. **Blocking external dependency:** `ci/` and `test.yml` are offload/Dagger territory
   (agent-harness#534/#543). Ratify before editing.

## Verification

```sh
PYTHONPATH=src:tests python3 -m pytest tests/test_inert_delta.py -q

python3 scripts/inert_delta.py \
  --canonical junit-offload/py310/junit-py310.xml \
  --lane junit-offload/gate-a/junit-gate-a.xml
# expect three separate identity sets, never summed

# FALSIFIERS — each must be RUN, not reasoned about
# 1. fixture workflow, unconditional on pull_request, absent from the declared list -> guard RED
# 2. same fixture, path-filtered                                                    -> guard GREEN
# 3. a .yaml (not .yml) unconditional workflow absent from the list                 -> guard RED
# 4. guard reading the string key "on" instead of boolean True                      -> must FAIL
#    (verified live: ALL 9 workflows in this repo parse `on` as boolean True)
# 4b. undeclared workflow using the LIST form `on: [push, pull_request]`             -> guard RED
#     (a dict-assuming guard CRASHES here: repo-wide false red in a required job)
#    (proves the vacuity footgun is closed, not merely noted)
# 5. inert test absent from the baseline -> RED; present with a reason -> GREEN
# 6. add one uncollected test AND restore another (counts unchanged)   -> RED
```

## Acceptance criteria

- [ ] The completeness guard fails on an undeclared unconditional `pull_request` workflow, and
      passes on a path-filtered one. Proven by running falsifiers 1–2.
- [ ] The guard detects a `.yaml` workflow (falsifier 3) and cannot pass vacuously under the
      PyYAML `on` footgun (falsifier 4).
- [ ] `inert_delta` returns three **identity sets**; a count-preserving add/drop still fails.
- [ ] A non-allowlisted inert test fails the build, **including `unclassified`**.
- [ ] The inert-delta job runs on **both** the offload and hosted paths, asserts exactly one
      evidence family, and its red **blocks** via `suite gate`.
- [ ] Each half mutation-verified against **its own** fixture, asserted through the **entry
      point** (workflow verdict), not only the pure function.
- [ ] `suite gate` behaviour is otherwise unchanged; the required-context set is unchanged.

## Out of scope

- Branch-protection settings — an operator action.
- **The already-open-PR retro window.** `strict` (require branches up to date) is **false** on
  `main` — verified live. A PR whose head already carries green `lint (pyflakes)` and `suite
  gate` from runs predating this change therefore **merges with the guard and the inert-delta
  never having executed on it**. Sharpest bite: a PR opened *before* the guard lands, which
  itself adds an undeclared unconditional workflow, merges ungated — the exact
  agent-harness#607 shape this plan exists to close.

  Stated precisely rather than overclaimed: **not** a permanent false green. `test.yml` also
  triggers on `push: branches: [main]`, and both surviving pieces run unconditionally there, so
  the merge reds on `main` post-hoc and a landed undeclared workflow reds every subsequent PR's
  lint. **The window converts prevention into post-hoc alarm.**

  This is rev 1's defect 2, recorded above for the *withdrawn* aggregate and never carried to
  the survivors. **Ordered remedy, not a note:** after the guard lands, sweep the open-PR queue
  with an empty commit or re-trigger, so every open head has executed both pieces before it can
  merge.

- **The skipped-job hole.** A conditionally skipped required job satisfies branch protection;
  nothing here closes it. Stated as open rather than implied covered.
- The 5 conflicted PRs from the agent-harness#607 sweep.
- agent-harness#600 — unrelated surface.

## Manifest note

`plans/manifest.json` deliberately not appended: agent-harness#606, agent-harness#546 and
agent-harness#383 all modify it concurrently.
