# Making agent-run phases converge

A phase that never finishes looks, from the outside, exactly like a phase that is
progressing: pull requests keep landing, CI keeps running, the agent keeps reporting work.
This document describes that failure mode, the changes we made in response, and — carefully —
how much the evidence actually supports.

It is written for other repositories. Most of what follows costs nothing to adopt and needs
no particular infrastructure. The one part that needs a second machine is marked as such, and
it is the least important part.

**Read the evidence section before adopting anything on our say-so.** The mechanism described
here is, we believe, real and general. The measurements supporting it come from one repository
and do not isolate it from several competing explanations, and we say where.

## What the failure looks like

The diagnostic signature, in order of how early you can catch it:

1. **Plan amendments outnumber implementation.** The agent spends its pull requests
   correcting the plan rather than executing it.
2. **Re-pinning.** The plan contains exact identifiers — commit SHAs, blob hashes, commit
   counts, the shape of its own future history — and every landing invalidates some of them,
   forcing another amendment.
3. **Rework loops.** A correction invalidates an earlier correction. The agent is busy and
   the phase is not moving.
4. **Reviews that cannot fail.** Tests are frozen against the wrong anchor, or assert
   something true by construction. Green stops meaning anything.

Signature 1 is the one to instrument, because it is countable while the phase is still
running. See "An abort threshold" below.

## The leading failure mechanism we observed: plans that pin their own future

A plan that says "the implementation lands as exactly six commits, the fourth of which has
tree X, rebased onto Y" has written a prediction about work that has not happened yet. Git
does not produce identifiers you can predict: a rebase, a squash, or an unrelated commit
landing on the base branch changes them. The prediction fails; because the plan is the
ratified contract, the agent must amend the plan before proceeding; amending the plan changes
its digest, invalidating anything pinned to *it*; and around it goes.

That is the treadmill, and its important property is that it does not require anyone to behave
badly: the plan has made itself impossible to satisfy, and a diligent agent will keep trying
to satisfy it. We are not in a position to say what share of any given stall this accounts for
versus reviewer availability, feedback latency, or model behaviour — only that this mechanism
is real, self-sustaining, and cheap to remove.

**The rule: pin inputs, never your own outputs.** Pin the contract you consume, the schema
version, the upstream digest, the interface you must not break. Never pin the SHA, count, or
topology of work you have not yet done.

## What we actually measured, and what it does and does not show

Two phases in this repository, `Consiliency/agent-harness`:

| | CONFORM (before) | GOVLEAN (after) |
|---|---|---|
| Plan | **20,839 words, 55 pinned commit SHAs** | **2,173 words, 0** |
| Merged PRs | 48 | 5 |
| Implementation PRs | 5 | 1 |
| PRs modifying the plan | 14 | 3 (one of which *created* it) |
| Span | 2026-07-02 → 08-13, finished by hand | 2026-08-14 22:48Z → 08-15 16:26Z |

The plan-size and pin figures are the strongest evidence here, and they are directly
measured. The amendment ratio is suggestive: CONFORM amended its plan roughly thirteen times
against five implementation PRs; GOVLEAN amended once against one. **By rate, though, the
comparison cuts the other way** — GOVLEAN touched its plan in 3 of 6 PRs (50%) versus
CONFORM's 14 of 48 (29%). We report that because it partially undercuts our own claim.

**What this comparison does not control for.** Anyone treating "six weeks versus seventeen
hours" as a clean result should not:

- **The window was not exclusive.** During CONFORM's six weeks the repository merged **41
  pull requests belonging to other phases** (19 LEGIBLE, 15 FAB, 4 PROOFGATE, 3 REVIEWTRUTH).
  The six weeks were not six weeks of undivided attention.
- **The phases differ in size.** 48 PRs versus 5 is not a difference in style. If GOVLEAN was
  simply a smaller job, pinning cannot account for the gap.
- **Several treatments landed together.** GOVLEAN ran under a new plan *and* a pin ban *and*
  goal-ID references *and* tests-first *and* pre-registered metrics — and it *built* some of
  the enforcement described below. This is not a controlled comparison of one variable.
- **CI got much faster in between** (see the CI section: two lanes went from ~85 minutes to
  6–7). A slow feedback loop is itself a plausible contributor to a long phase.
- **Reviewer availability was a live problem.** A single required reviewer with no fallback
  stalled a phase for days during this period. That is not pinning, and we have not
  disentangled it.

The honest statement is: **pinning your own future history is a sufficient mechanism to make
a plan unsatisfiable, and we observed the predicted amendment behaviour. It is not
established as the sufficient explanation for this particular six-week stall.** We recommend
the changes below because the mechanism is sound and the cost is near zero, not because this
comparison proves them.

## The changes, cheapest first

Items marked **(portable)** need nothing but a text editor and a CI job. Items marked
**(needs a plan runtime)** presuppose machinery this repository happens to have — a roadmap
with stable phase IDs, plan documents with frontmatter, and a dispatch step that has
somewhere to refuse. A portable analog is given for each.

### 1. Watch plan size (portable)

Our stalled plan was 20,839 words; its replacement was 2,173. We do not, however, enforce a
fixed number: this repository's own planning skill says *"Be as short as possible while citing
every load-bearing file:line. No fixed word cap."* Treat size as a signal to investigate, not
a limit to satisfy.

A cap applied naively pushes people to under-specify, which fails just as expensively. The
useful discipline is *where* the length lives: long frozen contracts belong in artifacts the
plan references; the execution plan itself stays short and points at them.

For a worked example of what a compliant plan contains at this length, see
`plans/phase-plan-v10-GOVLEAN.md` in this repository.

### 2. Ban future-history pins — carefully (portable)

Keep the rule; be careful with the lint. A naive "flag every 40-character hex string" will
fire on legitimate **input** pins. This repository pins
`contract_git_sha="b862f977897a7b87c4419680a3e83735d4ff07b0"` — the upstream contract commit
we consume — which the rule explicitly permits and a naive scan would reject. Do not tell
people to grep out the digests you also tell them to record.

| Allowed (inputs) | Forbidden (your own outputs) |
|---|---|
| Upstream contract/schema commit or digest | SHAs of commits this plan will produce |
| Dependency version or lockfile hash | Commit counts, "exactly N commits" |
| Interface/API you must not break | Tree or blob hashes of future landings |
| Digest of a *frozen* artifact already committed | Rebase/merge topology of your own branch |

A CI check that flags 40-hex literals **outside an allowlist of known input-pin fields** is
the portable version.

The same "be careful with the lint" problem shows up one level out, in the *documentation*
that records your pins. `phase_loop_runtime.entry_doc_check` is the worked implementation
here (`.github/workflows/entry-doc-check.yml`): it verifies entry-point docs against
properties that hold with no diff in sight. Two of its design constraints transfer
directly. First, a pin is checked for **staleness, not existence** — this repository's own
`v0.1.5` install pin rotted through six releases while remaining a perfectly resolvable
tag, so an existence rule passes the exact defect. Second, the false-positive classes are
load-bearing rather than optional: of the 32 path-like tokens in these entry docs, 17 are
deliberately not repository paths — home directories, issue citations, version
metavariables, install destinations — and a check without named classes for them is red on
day one and switched off by day two.

### 3. Reference goals by ID; never restate them (portable in principle, needs IDs in practice)

Give every exit criterion a stable identifier (`EC-<ALIAS>-<N>`). Plans reference the ID; they
do not paraphrase. A paraphrase drifts, and then two documents disagree about what "done"
means. If you have no roadmap format, a numbered list in one file that everything else cites
is enough — the property that matters is a single mutable definition with immutable names.

### 4. Refuse to run a plan written against different content (needs a plan runtime)

Record the digest of the roadmap in the plan's frontmatter and make dispatch **fail closed**
on a mismatch. In our runtime this was a small change; note that "small" is measured against
already having a dispatcher. Our plan validator is 1,222 lines — the cheap part is the check,
not the surrounding machinery.

**Portable analog:** a CI job on every pull request that recomputes the digest of the
spec/roadmap and fails when a plan file's recorded digest does not match. No dispatcher
required — the pull request is the gate.

### 5. Make ordering rules machine-readable, not prose (needs a plan runtime)

If phase B must not start until phase A completes, a sentence saying so enforces nothing.
We declare the hold on the later phase's section and fail its dispatch until the holder is
recorded complete.

The general lesson is broader: **if a rule matters, something must be able to refuse when it
is broken.** A rule that exists only in prose will be violated by an agent acting in good
faith.

**Portable analog:** a required CI check that reads the ordering declaration and fails the
pull request when it is violated.

### 6. Define the proof before declaring the behaviour done — and show it can fail (portable)

The durable rule is not "tests must land in an earlier commit." It is: **define the proof
before you declare the behaviour complete, and demonstrate that the proof detects a known
violation.** Tests and implementation may land atomically; a spike may legitimately precede
its test. What may not happen is accepting the work without falsification evidence.

Stated as a strict tests-first mandate this advice does real damage: it invites freezing a
guessed interface before discovery has happened, encourages tests coupled to implementation
details, and fits badly with exploratory work, incident response, migrations, and performance
tuning. Use the ordering where it helps and keep the falsification requirement everywhere.

The part usually skipped is the second half — verify each test *fails* when the behaviour it
guards is removed. A frozen test anchored to the wrong function passes forever and proves
nothing.

This is not theoretical. While building these primitives, the agent found one of its own
frozen mutation declarations anchored to a function that did not implement the behaviour
under test; the mutation survived, meaning that falsifier could never have failed. It was
caught because the process requires demonstrating the failure rather than asserting it.

### 7. Pre-register how you will judge the outcome (portable)

Before the run, record what success looks like: how many pull requests, how long, what
fraction may be support work. Then **do not change those numbers after seeing the result.**

Our first phase under the new rules beat its PR-count and wall-clock targets and *missed* its
support-share target — 80% against a 40% ceiling. The right response was to record the miss,
observe that the metric counts pull requests as equal units regardless of size, and defer any
refinement until a second phase had reported the same figures. Relaxing a target the moment it
stings destroys the only property that made measuring worthwhile.

### An abort threshold (portable)

Signature 1 is countable during the run. Pick a threshold in advance — for example, *three
plan-amendment PRs landing before any implementation PR* — and stop the phase for diagnosis
when it trips. Exclude the plan's own creation and any mandated tests-first landings, or the
tripwire fires on every compliant run.

### 8. Bound the review loop (portable)

A multi-seat review has its own flail mode, distinct from the plan's: every round re-reviews
everything, every finding becomes a fix, and each fix hands the next round something new to
find. One plan review here ran ten rounds because each fix introduced a fresh runtime number
for the next round to falsify; the reviewer had offered the exit at round five. Four rules,
fixed before round one, bound it:

1. **Delta review.** After a fix round, only the seats that dissented — `DISAGREE`,
   `PARTIALLY AGREE`, or any blocking finding — review again, and they review the delta since
   the round they dissented on; the round record names that delta's base and head. Seats that
   agreed are carried forward, marked as carried. A dissenting seat that errors, times out, or
   returns nothing is re-run, never carried: a carried verdict must be one somebody actually
   gave. Where a gate requires an exact-head unanimous board (this repository's runtime does,
   for the implementation board), that board runs once on the final head after the loop has
   converged; delta review governs the fix rounds that get it there.
2. **No cancel-on-first-blocker.** Let the round finish. A blocker at minute three says nothing
   about what the other seats would have found at minute twenty, and cancelling them means
   paying for the whole round again after the fix. Collect every seat's findings, then fix once.
3. **Findings cite the frozen goal.** A blocking finding names the `EC-<ALIAS>-<N>` (or the
   frozen artifact) it claims is violated. A finding that cannot point at a goal is a
   suggestion: it may be taken, but it cannot block, and it cannot become the round's new goal.
   This is the review-side half of rule 3 — it stops a review from restating the goals in its
   own words.
4. **A round cap that ends in descope, not in another round.** Write the cap into the pull
   request before round one (three is usual). When it trips, sort what remains: defects in how
   the change binds its inputs are fixed; findings that pin the change's own outputs are carried
   to a follow-up; and the class the loop kept re-litigating is descoped and recorded as an
   exception (below) rather than spent on a fourth round. When each round's fix adds a new
   falsifiable number, cut the number and keep the rule.

## Exceptions, and how to take one

Every rule above has legitimate exceptions, and a rule with no exception path gets violated
silently instead of deliberately. Make taking one cheap and visible: **name the rule, the
reason, and an owner, and record it where the work is reviewed.** A plan that must exceed a
sensible length, a pin that must be retained, a change that cannot practically be falsified
before it lands — all fine, once written down. What corrodes the practice is an unrecorded
exception, because the next reader cannot tell it from a mistake.

## If you want to reproduce these numbers, define them first

We found our own definitions slipperier than expected — the same two phases look different
depending on whether you count amendments as a ratio to implementation or as a rate per pull
request, and those two readings disagree about which phase did better. Before measuring
anything, write down:

- **Phase boundaries.** When does it start — plan authored, first commit, first merge? When
  does it end?
- **Implementation versus support.** Which categories count as which, and are they counted by
  pull request, by commit, or by diff size? (Counting pull requests treats a 1,500-line change
  and a two-line record as equal; ours did, and it distorted the result.)
- **What an amendment is.** Any edit to the plan? Only edits forced by a failed prediction?
  Does creating the plan count?
- **What time counts.** Wall clock includes nights, weekends, waiting on review, and work on
  other phases in the same window. Say which of those you are including.
- **Scope.** Some measure of size, so a fast phase is not confused with a small one.

Publish the definitions with the numbers. Ours are stated above; they are not the only
defensible choices.

## Making CI cheap enough to iterate against

Slow feedback compounds everything above: a 90-minute cycle means a wrong guess costs half a
morning, and agents batch speculative changes to amortize the wait.

### Split the expensive proof out of redundant lanes (portable principle; example is stack-specific)

Our heaviest test — a boundary walk taking roughly 40 minutes — ran in all three Python matrix
lanes. It only needs to run where its result is meaningful. Excluding it from the other lanes
took **those lanes from ~85 minutes to 6–7**, with no loss of coverage: the node still runs in
one matrix lane and in the clean-room gate.

The example below uses pytest's `--deselect`; the principle — *run an expensive proof in the
minimum set of environments where its result differs* — applies to any test runner. Two
cautions, both learned the hard way:

- **Guard the exclusion.** If the test is renamed, an exclusion that no longer matches
  silently becomes a no-op and the expensive test quietly returns to every lane. Assert the
  test is still collectable in the lanes that exclude it.
- **Guard against removal.** Add a separate job asserting at least one lane still retains the
  test — in its own job, not inside the matrix, since an in-matrix guard disappears with the
  lane it protects.

### Scope the expensive proof to the changes that can move it (portable principle)

Splitting lanes bounds how many *times* the proof runs per change; it does not bound the
change's wall clock, which is still the proof itself. Once we measured it, that one node was
~50 minutes of a ~65-minute run — 88 % — and every pull request paid it, including the ones
that touched only prose, a workflow, or a module the proof never reads.

The proof's process reads far more than the modules it mutates — the test runner collects
the whole test tree, the test bootstrap loads runtime plugins, sibling tests read repository
docs — so no enumeration of "the inputs" is small, and the second step does **not** claim
that a change outside some list cannot change the verdict. It claims something narrower that
holds by construction: the proof runs *unconditionally* on every merge to the default branch
and on a nightly schedule, and on a pull request whenever the diff touches the runtime
package or the CI plumbing; for any other pull request the proof is deferred to the landing
merge, so a regression surfaces on the default branch at the latest, never silently. Three
properties make this safe, and each needs a guard of its own:

- **The retained set is checked against the proof's own definition**, not maintained by
  hand: a test enumerates every path the proof's frozen definitions reference and asserts the
  scope rule classifies each one as retained. A new input that the rule would let a pull
  request skip fails that test.
- **The decision fails closed.** Any event the rule cannot classify, any pull request it
  cannot diff, and any lane the decision fails to reach all retain the proof. The retention
  guard from the previous section additionally asserts the rule answers "retain" for the
  default branch and the schedule.
- **The evidence witnesses the decision.** The lane that ran writes a junit report either
  way, and the run asserts the node's name is present in it when retained and absent when
  deselected — so a deselect that silently matched nothing, or a retain that silently did not
  run, is a red job rather than a green one.

The nightly run is the backstop: it bounds how long a regression in an untouched input can
stay invisible, independent of merge traffic. On our numbers the quick path takes a
prose-only pull request from ~65 minutes to under 10.

### Use one aggregate required check (GitHub-specific detail; general principle)

On GitHub, **a skipped job satisfies a required status check**, so a pipeline with two
alternative paths where one always skips can go green having run nothing. Require a single
aggregate job that inspects the others and fails when neither ran. Also exclude path-filtered
workflows from required checks: a check that never reports on a pull request blocks it
forever. Other CI systems differ in detail; the principle is that *the required check must be
one that cannot pass without work having happened*.

### Offloading to another machine (needs a second machine — optional)

We moved heavy CI to a spare machine over a private network using a container pipeline.
Measured: the clean-room gate went from **86:36 to 51:18**, the heavy matrix lane from
**65:59 to 41:55**, total wall clock from about **87 minutes to 51**, with hosted-runner
minutes for that work dropping to zero.

This is the least important item here. The plan discipline is what we believe made the phase
converge; the offload made iterating cheaper. **If you have one machine, skip this section and
lose nothing structural.**

If you do adopt it, three findings that will otherwise cost a day each:

- **Run stages concurrently and aggregate verdicts.** Sequential composition stops at the
  first failure, so each run surfaces exactly one defect — ours cost roughly 45 minutes per
  defect discovered until the stages ran in parallel.
- **Do not let evidence export re-run the work.** If exporting test reports re-invokes the
  stages, a warm cache hides it and a cold cache doubles wall clock. Make the report a
  byproduct of the run that gated.
- **Expect the isolated environment to expose real bugs.** A hosted runner silently supplies
  things your code depends on. Moving execution somewhere that does not pretend to be one
  found two genuine defects in shipped code within two runs: an unguarded external-binary call
  leaking an untyped exception where a typed error was promised, and a guard whose path
  assumption made it unable to fail. Both would have hit any user in a clean-room install.

## Governance that does not become the work

Reviews are where a stalled phase burns the most time, because a review that cannot conclude
blocks everything behind it.

- **Give the deciding seat a fallback chain.** A single required reviewer is a single point of
  failure; ours stalled a phase for days. Define an ordered list of substitutes, descend it on
  typed failures only, and record which seat actually ruled.
- **Let the deciding seat verify.** A reviewer that can only read must take claims on faith.
- **Separate "is this finding real" from "does it block."** Conflating them turns every
  observation into an argument.
- **File deferrals as issues before dispatching the decision.** A deferred finding with no
  ticket is a finding that was dropped.

## Bot writes to governed branches

If an automated assistant can push to your branches, decide deliberately whether it should.
Over 36 hours ours pushed unaudited commits to five governed branches, including a rewrite of
the module then under review and an edit that would have made a test unable to fail its own
named property. Its diagnoses were frequently correct — the channel was the problem, not the
analysis.

1. **Scope it to propose-only** if that setting exists. Note such settings are sometimes
   per-user and organization-wide rather than per-repository — check the scope before assuming
   a repository is unaffected.
2. **Pin the head when merging**, so a merge fails loudly if anything landed since review.
3. **Check author *and* committer.** A bot commit is often authored as you and committed as
   the bot; looking only at the author shows nothing unusual.

## The one-machine, no-runtime version

If you have no phase runtime, no CI matrix, and one machine, the whole of this document
reduces to a short recipe that needs only a text editor, a repository, and a single CI job (or
a git hook, or a command someone runs before opening a pull request):

1. **One file lists the goals**, each with a stable ID that never gets renumbered. Plans and
   pull requests cite IDs; they never restate the goal.
2. **Plans are short and reference frozen artifacts** rather than restating them, and contain
   no identifier for work that has not happened.
3. **One local command** (`make check`, a script, whatever fits) that: recomputes the digest
   of the goals file and compares it to the digest each plan records; scans plans for 40-hex
   literals outside your allowlist of input-pin fields; and fails on either. That single
   command is the portable substitute for a dispatch guard — the pull request becomes the gate.
4. **Acceptance requires falsification evidence**: for each goal, a proof, plus a
   demonstration that the proof fails when the behaviour is removed.
5. **Write down your targets and an abort threshold before starting**, and record the outcome
   against them honestly — including misses.
6. **Bound every review before it starts**: a round cap written into the pull request, delta
   re-review by dissenting reviewers only, findings that cite a goal ID, and descope — not a
   further round — when the cap trips.

Nothing in that list requires containers, a second machine, a matrix, or a custom runner.
Everything else in this document is an optimisation on top of it.

## Adoption order

1. Watch plan size; move long contracts into referenced artifacts. *(portable)*
2. Ban future-history pins, with an allowlist for input pins. *(portable)*
3. Reference goals by stable ID instead of restating them. *(portable)*
4. Define the proof before declaring a behaviour done, and demonstrate it failing. *(portable)*
5. Pre-register convergence targets; set an abort threshold; refuse to move either mid-run.
   *(portable)*
6. Bound the review loop: delta review by dissenting seats only, no cancel-on-first-blocker,
   findings cite goal IDs, a pre-written round cap that ends in descope. *(portable)*
7. Split expensive proofs out of redundant lanes, with both guards; then scope them to the
   changes that can move them, with a default-branch + nightly backstop and an evidence
   witness. *(portable, needs a CI matrix)*
8. Make one aggregate check required; never require a job that can skip. *(portable, CI-system
   specific)*
9. Fail closed on a stale plan digest — as a CI check if you have no dispatcher. *(portable as
   a check; cheap only if you already have a runtime)*
10. Make ordering rules machine-enforced rather than prose. *(same)*
11. Offload heavy CI to a second machine. *(optional; needs hardware)*

## Honest limits

One phase converged under these rules and a second was in progress when this was written.
That is a small sample from a single repository; the phases were not equal in size; several
changes landed together; and the earlier phase shared its window with 41 pull requests from
other phases. The plan-size and pin counts are directly measured. The causal claim is an
inference from a mechanism we can describe precisely and an amendment pattern we can only
partly evidence — and one of our own measurements (plan-touch *rate*) points the other way.

The support-share target was missed by the completed phase and we have deliberately not
adjusted it. Treat every number here as a starting point to calibrate against your own
baseline, not as a validated threshold.
