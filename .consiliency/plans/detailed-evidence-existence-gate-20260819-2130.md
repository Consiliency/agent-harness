# Detailed plan: make missing evidence fail loudly (agent-harness#607 + agent-harness#601)

**Revision 5 — SCOPE CUT, corrected.** Rev 3 was re-reviewed: codex DISAGREE, grok DISAGREE,
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

### `.github/workflows/evidence-gate.yml` — completeness guard step (create, load-bearing)

- **Workflows-as-data guard** — add — parse `.github/workflows/*.yml` and fail when a workflow
  that triggers unconditionally on `pull_request` is **absent from the declared list**.
  Without it, workflow N+1 is invisible to the gate and **the agent-harness#607 class recurs
  one meta-level up, permanently** — a gate that only protects what someone remembered to
  declare. Precedent for reading workflow YAML as data already exists in this repo:
  `chronology-retention` (`test.yml:311-336`).
- The same guard enforces the invariant that declared workflows must be **unconditional** on
  `pull_request` — a path-filtered workflow legitimately does not run, and treating that as
  missing evidence is the false positive that would block every PR.

### `phase-loop-runtime/scripts/evidence_gate.py` (create)

> Placed in `scripts/`, **not** the published package. Repo precedent for CI-only helpers is
> `phase-loop-runtime/scripts/` (e.g. `check_model_id_sources.py`); putting it in
> `src/phase_loop_runtime/` would grow the published public surface for a CI-only concern.

- `missing_or_unsuccessful(declared, observed, head_sha)` — add — pure. Returns each declared
  workflow whose run for **this `head_sha`** is absent, not `completed`, or whose
  `conclusion != "success"`. **Existence is necessary and not sufficient** — the rev-1 defect.
  `cancelled` and `startup_failure` are runs that exist and produced **no evidence**; they
  must be red.
- `inert_delta(canonical_junit, lane_junit)` — add — returns three **separate identity sets**:
  `skipped_here_live_there`, `absent_from_collection`, `skipped_in_both`. Never summed, and
  **never reduced to cardinality** — sets, so an add/drop pair cannot cancel out.
- `classify_inert(entry, allowlist)` — add — `legitimate` / `unclassified` / `accidental`.
  **`unclassified` fails**, matching the acceptance rule; rev 1 failed only `accidental`
  while knowingly retaining 5 unclassified.

### `.github/workflows/evidence-gate.yml` (create)

- `evidence-gate` job — add — required aggregate, `if: always()`, `permissions: actions: read`
  (sufficient; **admin scope is not required** — this was the panel's answer to "is it even
  buildable", and the answer is yes, but not as rev 1 specified it).
- Keyed on `head_sha`. Polls `queued`/`in_progress` to a bounded deadline rather than reading
  "not finished yet" as missing.
- **Excludes path-filtered workflows** from the declared set — they legitimately do not run,
  and treating that as missing evidence is the false-positive that would block every PR.
- Failure message names the remedy: **an empty commit**. "Re-run the workflow" is impossible
  when no run exists, and `entry-doc-check.yml` has no `workflow_dispatch` trigger
  (`:19-22`) — so the obvious remedy text would be advice that cannot be followed.
- **Bounded retry for the first-push race.** Workflows for one `pull_request` event are
  created near-simultaneously but **not transactionally**, so an immediate read can see a
  genuinely-coming run as missing and false-red a fresh push.

### `.github/workflows/evidence-reconcile.yml` (create)

- Scheduled + `workflow_dispatch` reconciler — add — **closes rev-1 defect 2.** Enumerates
  open PRs and re-evaluates each head against the current declared set, so landing a new
  requirement reaches PRs that will never emit a `pull_request` event. Without this the gate
  has the hole it exists to detect.

### `.github/required-workflows.json` (create)

- Declared required set — add — checked in, so the gate's correctness is reviewable in a
  diff rather than depending on a branch-protection setting no reviewer sees.

### `.github/inert-tests-baseline.json` (create)

- Two identity-keyed sets — add — allowed skips (seeded from the 73, each with a reason) and
  the **expected-collection baseline** for `absent_from_collection`. Identity-keyed, not
  counts, per rev-1 defect 4.
- **Pruning rule** — add — an allowlist entry matching **no collected test** is itself a
  finding. Without it the allowlist rots into a rubber stamp: entries accumulate, nothing ever
  removes them, and a stale entry silently excuses a test that no longer exists. Seeding 73
  wholesale is a rubber stamp at birth; the fresh-measurement requirement plus pruning is what
  keeps it honest.

### `.github/workflows/test.yml` (modify)

- Add an `inert-delta` step **at the offload aggregation seam**, consuming the already-paired
  `junit-offload/py310` and `junit-offload/gate-a` — modify. Not attached to `suite gate` (no
  artifact download) and **not** in `gate_a_cleanroom.sh`.
- **Dual-path, fail-closed on exactly one evidence set.** The hosted jobs (`pytest`,
  `cleanroom`) are **skipped on the offload path** (`test.yml:191-192`, `:345-346`), which is
  the *common* path, and the two paths produce different artifact layouts
  (`junit-offloaded` vs `chronology-junit-*`). Wiring only the hosted layout makes the
  inertness detector **itself inert on the majority path** — this plan's own class, third
  occurrence. Assert **exactly one** evidence set is present and fail closed otherwise,
  mirroring `suite gate`'s exactly-one-verdict contract.
- Note: the canonical junit currently excludes the two LEGIBLE files, which run in a separate
  invocation emitting no junit (`test.yml:253`, `ci/dagger/src/agent_harness_ci/main.py:168`).
  Inertness there is invisible; either emit junit for them or record them as a declared blind
  spot. **Do not leave it undocumented** — an unrecorded blind spot is this plan's own class.

### `CHANGELOG.md` (modify)

- Add — a new required check is a public surface; the docs-audit gate blocks a public-surface
  change without a committed CHANGELOG entry.

## Dependencies & order

1. Pure functions in `evidence_gate.py` first — the only part testable without CI round-trips.
2. Reseed **all** measured inputs; the numbers above expire on any merge.
3. `evidence-gate.yml` lands and runs **advisory** before becoming required. A gate made
   required before it is proven converts a false positive into a repo-wide outage.
4. `evidence-reconcile.yml` must land **with or before** the gate becomes required, or the
   gate cannot reach the 13 PRs that motivated it.
5. **Blocking external dependency:** `ci/` and `test.yml` are offload/Dagger territory
   (agent-harness#534/#543). Ratify this design before editing them.

## Verification

```sh
PYTHONPATH=src:tests python3 -m pytest tests/test_evidence_gate.py -q

# agent-harness#607, keyed on head_sha (NOT branch)
gh api "repos/Consiliency/agent-harness/actions/runs?head_sha=<sha>" \
  --jq '.workflow_runs[] | "\(.name) \(.status) \(.conclusion)"'

# agent-harness#601, at the seam where both files already exist
python3 -m phase_loop_runtime.evidence_gate \
  --canonical junit-offload/py310/junit-py310.xml \
  --lane junit-offload/gate-a/junit-gate-a.xml
# expect three separate identity sets, never summed, never cardinality-reduced

# FALSIFIERS — required, and each must be RUN, not reasoned about
# 1. A declared workflow whose run FAILED  -> gate red (rev 1 would have gone green)
# 2. A declared workflow with no run       -> gate red
# 3. Inert test absent from the baseline   -> red;  present with a reason -> green
# 4. Add one uncollected test AND restore another -> identity sets differ -> red
#    (a cardinality gate is green here; this is the rev-1 defect)
```

## Acceptance criteria

- [ ] A declared workflow whose run **exists but did not succeed** makes `evidence-gate`
      **red**. Proven by running it, not by inspection — this is rev 1's primary defect.
- [ ] A PR head with **no run** for a declared workflow makes the gate red, with the remedy
      named.
- [ ] The reconciler makes a **stale open PR** (last push predating the requirement) report,
      demonstrated on a real branch. Without this the gate has agent-harness#607's own defect.
- [ ] `inert_delta` returns three **identity sets**; an add/drop pair that preserves counts
      still fails. No code path sums or counts them.
- [ ] A non-allowlisted inert test fails, **including `unclassified`**.
- [ ] Path-filtered workflows do **not** trip the gate.
- [ ] Each half mutation-verified against **its own** fixture, asserted through the
      **entry point** (workflow verdict / CLI exit), not only the pure function.
- [ ] `suite gate` behaviour unchanged.

## Execution Policy

- execute: effort=high, reason=CI gate correctness; a false positive blocks every PR, and the
  failure being fixed is silent.

## Out of scope

- Branch-protection settings — an operator action; the gate proves itself first.
- The 5 conflicted PRs from the sweep — unmergeable today; their resolution produces an
  unchecked tree, tracked separately.
- agent-harness#600 — unrelated surface.

## Manifest note

`plans/manifest.json` **deliberately not appended**: agent-harness#606, agent-harness#546 and
agent-harness#383 all modify it concurrently. Append when they settle.
