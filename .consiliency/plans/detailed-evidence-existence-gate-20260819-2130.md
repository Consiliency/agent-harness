# Detailed plan: make missing evidence fail loudly (agent-harness#607 + agent-harness#601)

**Revision 2.** Revision 1 was reviewed by a three-seat panel; codex and grok both returned
DISAGREE with overlapping blocking defects. Rev 1's own errors are recorded in
"What revision 1 got wrong" below, because two of them were instances of the very class this
plan exists to close.

## Task

Close one defect class with three observed instances: **the absence of evidence renders
identically to the presence of a positive result.** A check that never ran, a test that was
never collected, and a job that was skipped all read as "green".

- **agent-harness#607** — a newly added workflow never runs against already-open PRs, so the
  first change to violate a brand-new gate can merge with the gate having never executed.
- **agent-harness#601** — tests inert in a CI lane are indistinguishable from tests that pass.

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
before implementing): agent-harness#545 had **0 of 15** runs and merged 18 h after the gate
landed; **13 of 17** open PRs have never run the check (merge-simulated: 8 pass, 5 conflict,
**0 fail** — the hole is *latent, not realised*); Gate A junit diff gives **78**
skipped-here-live-there (73 legitimate / 5 unclassified / **0 confirmed accidental**), **41**
absent from collection with **no reason string**, **61** skipped in both lanes.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/evidence_gate.py` (create)

- `missing_or_unsuccessful(declared, observed, head_sha)` — add — pure. Returns each declared
  workflow whose run for **this `head_sha`** is absent, not `completed`, or whose
  `conclusion != "success"`. **Existence is necessary and not sufficient** — the rev-1 defect.
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
- Failure message names the remedy (empty commit / re-run on this head), following
  `suite gate`'s precedent of explaining why the red is correct.

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

### `.github/workflows/test.yml` (modify)

- Add an `inert-delta` step **at the offload aggregation seam**, consuming the already-paired
  `junit-offload/py310` and `junit-offload/gate-a`, with a hosted-path mirror — modify.
  Not attached to `suite gate` (no artifact download) and **not** in `gate_a_cleanroom.sh`.
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
