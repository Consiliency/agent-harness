# Proposal: narrow GOVLEAN's Key files (Consiliency/agent-harness#688)

**Status:** proposal for a maintainer / LEGIBLE decision. This document does not edit
`specs/phase-plans-v10.md`. Every number below was printed by the instrument named beside
it; none was estimated.

## The measurement

Window: the last 40 changes landed on `origin/main` at `ee3213ea`. Instrument:
`python -m phase_loop_runtime.roadmap_ownership --repo . --report 40 --base origin/main`,
with `--candidate-roadmap` for the projections (ah#688 adds that flag; it scores the SAME
40 commits and per-commit diffs against a hypothetical roadmap text).

| roadmap | flagged | GOVLEAN on | of which GOVLEAN's own commits | over-claim |
|---|---|---|---|---|
| live (history) | **37/40 (92%)** | 37 | 8 | 29 |
| v1 — src/ and tests/ made literal | 27/40 (68%) | 23 | 8 | 15 |
| v2 — v1 minus `plans/` minus `test_phase_loop_launcher.py` | 18/40 (45%) | 8 | 8 | 0 |
| v3 — v2 plus every file GOVLEAN's plan names (32) | 18/40 (45%) | 11 | 8 | **3** |
| v4 — v2 plus 18 plan-named files | 18/40 (45%) | 8 | 8 | 0 |
| v5 — v4 minus the `panel_invoker.py` dual-claim | 18/40 (45%) | 8 | 8 | 0 |
| v6 — v5 with `skills-src/` narrowed to the 12 skill directories GOVLEAN's plan names | 18/40 (45%) | 8 | 8 | 0 |
| v7 — v6 with those directories replaced by their 12 `SKILL.md` files plus the one plan-owned validator; every entry is a literal file | 18/40 (45%) | 8 | 8 | 0 |
| **v8 — v7 minus `test_console_scripts_are_declared.py` (a shared test GOVLEAN touched once)** | **18/40 (45%)** | **8** | **8** | **0** |
| floor — GOVLEAN claims nothing | 13/40 (32%) | — | — | — |

**"over-claim" means a GOVLEAN flag on a file GOVLEAN does not own by a named authority** —
not "a flag on a commit GOVLEAN did not land". An ownership check is SUPPOSED to flag a foreign
PR that edits your file; that is what a claim is for. The column is author attribution of the
flagged rows (the instrument prints per-phase counts, not this column), so it is reproduced
below at a second window to show it is not an artefact of the 40-commit cutoff:

| roadmap | window 60 flagged | GOVLEAN on | on GOVLEAN's own commits | on foreign commits — via which file, and GOVLEAN's authority for it |
|---|---|---|---|---|
| v4 | 24/60 (40%) | 12 | 8 | **4**: ah#643, ah#632, `4e45af61`, ah#545 — all via `panel_invoker.py`, the live roadmap's "(EC-GOVLEAN-5 bounded edits)" dual-claim; HARDEN owns the file and EC-GOVLEAN-5 is verified (phase `completed`), so the bounded edits are done |
| v5 | 24/60 (40%) | 10 | 8 | **2**: ah#643 via `test_govlean_panel_policy.py` AND via `skills-src/` — that PR edited the four `*-advisor-board` skills, which GOVLEAN's plan does not own; a directory token matches every descendant |
| **v6 = v7 = v8** | 24/60 (40%) | 10 | 8 | **2**: ah#643 via `test_govlean_panel_policy.py` (a board-defaults change updating the expectations of GOVLEAN's EC-GOVLEAN-5 proof test — GOVLEAN plan line 118); ah#545 via `agy_canary_evidence.py` (the commit that CREATED the file, before GOVLEAN's four subsequent landings on it — ah#670, ah#711, ah#725, ah#633; GOVLEAN's authority here is adoption by landed history under the live `src/phase_loop_runtime/` claim, NOT the plan's `Owned files`, which does not list this file) |

Both rows at window 60 are foreign edits to files GOVLEAN owns — one by its plan's `Owned
files` declaration (`test_govlean_panel_policy.py`, `plans/phase-plan-v10-GOVLEAN.md` line 70),
one by adoption (`agy_canary_evidence.py`: created by ah#545, then four GOVLEAN landings and no
other phase's since). They are correct flags, with two different authorities, both named.

And at window 150 (the round-5 CR asked for a third window):

| roadmap | window 150 flagged | GOVLEAN on | own | on foreign commits — via which file, and GOVLEAN's authority for it |
|---|---|---|---|---|
| v7 | 45/150 (30%) | 16 | 12 | **4**: the two above; ah#572 (PROOFGATE) via the four `*-plan-phase/SKILL.md` + `validate_plan_doc.py`; **ah#543 via `test_console_scripts_are_declared.py`** — the commit that CREATED that test for `phase-loop`/`codex-phase-loop` coverage; GOVLEAN added one case to it once (ah#725). Not plan-named, not GOVLEAN-created, shared by scope → **excluded in v8** |
| **v8** | 45/150 (30%) | 15 | 12 | **3**: ah#643 and ah#545 as above; ah#572 (PROOFGATE) editing the plan-phase skills that GOVLEAN's plan names in `Owned files` (line 70/86) — a foreign edit to GOVLEAN-owned files, i.e. a correct flag. `--preflight` reports no phase outside GOVLEAN for those five files; PROOFGATE's roadmap claims only the `skills_bundle/` copy of the validator |

Every foreign row that survives to v8 is a foreign edit to a file GOVLEAN owns by a NAMED
authority (plan `Owned files`, or creation-then-sole-stewardship). Every file dropped between v2
and v8 was one where the authority was the window itself, and each was exposed by widening the
window: `panel_invoker.py` (60), the `skills-src/` directory (60), single-skill directories (ah#340),
`test_console_scripts_are_declared.py` (150). v4's four
extra rows were not: they came through a file whose owner is HARDEN.

Sanity: a candidate identical to the live roadmap reproduces 37/40 exactly (and 53/60 at window
60), so within these windows the candidate path changes nothing but the text. The exact condition is
per commit: a candidate applies ONE map to every commit, a plain run reads each commit's own
roadmap, so the two agree exactly when no commit's flag OUTCOME differs between its own map and
the candidate map. "The map did not change" is sufficient but not necessary, and it is NOT what
held here: window 60 spans three roadmap blobs (39/4/17 commits), the SCHED claims on
`launcher.py`/`worker_pool.py` were added at `697dd899` (ah#616), and one earlier commit
(`d184ea63`, ah#706) touches both files — its outcome is unchanged because it has seven claimants
under either map. At window 150 the live text as a candidate flags 140/150 against 93/150
historically: 47 commits predate the phases the live map claims, so their outcomes differ. Do
not read a candidate number against a historical one without checking that condition.

Separately, the candidate
path changes nothing but the text.

**v8 is the proposal** (`plans/govlean-candidate.md` IS v8). The candidate is a verbatim copy of the live roadmap with ONLY GOVLEAN's
`**Key files**` block replaced; its prose — DAG notes, scope notes, the REVIEWTRUTH text that
names `panel_invoker.py` as a shared path — is the live roadmap's and is not part of the proposal. Under it every remaining GOVLEAN
flag sits on a commit GOVLEAN itself landed. The 13-point gap to the floor is not over-claim;
it is GOVLEAN owning its own work.

v2 was the first cut and it had a sampling defect the cross-vendor CR of agent-harness#732
caught: it was derived from a 40-commit *window*, so it silently dropped GOVLEAN's
deliverables from before the window. See "What a window-only narrowing would have dropped".
v3 is the naive repair — add everything GOVLEAN's plan names — and the instrument shows it
re-introduces three over-claims. v4 keeps the number and fixes the defect; v5 additionally
drops the one pre-existing dual-claim (`panel_invoker.py`) that a second window (60) showed to
be the source of every foreign flag beyond the first — the round-2 CR (codex) caught that
"zero" was window-bound. v6 applies the same lesson to the last directory token: `skills-src/`
matched the advisor-board skills ah#643 edited, which GOVLEAN's plan does not own (round 3).
v7 finishes the job: even a single-skill directory covers that skill's `scripts/` (19 such files
across the 12), which the plan does not name, so the entries are the 12 `SKILL.md` files plus
the one validator the plan does own (round 4, grok).

## Why v1 was not enough — attribution of its 15 over-claims

| GOVLEAN token still firing | over-claims | what those commits actually were |
|---|---|---|
| `plans/` | **12** | other phases' PRs appending lifecycle events to `plans/manifest.json` — 11 of the 40 commits write that file; GOVLEAN's own commits touched **zero** files under `plans/` |
| `phase-loop-runtime/tests/test_phase_loop_launcher.py` | 3 | SCHED test-contract PRs. In v1 only because ah#715 touched it incidentally; it is SCHED's |

Both are removed in v2. The `plans/` claim reads "closeout gate surface" in the roadmap; as a
directory claim it matches a file every phase must write, which is over-claim by construction.
If GOVLEAN later builds a closeout-gate artifact under `plans/`, claim that FILE.

## The proposed `**Key files**` block for GOVLEAN (paste-ready)

```
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/roadmap_ownership.py`
- `phase-loop-runtime/src/phase_loop_runtime/closeout_classifier.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_canary_evidence.py`
- `phase-loop-runtime/src/phase_loop_runtime/profiles.py`
- `phase-loop-runtime/src/phase_loop_runtime/prompts.py`
- `phase-loop-runtime/tests/test_roadmap_ownership.py`
- `phase-loop-runtime/tests/test_closeout_classifier.py`
- `phase-loop-runtime/tests/test_agy_canary_evidence.py`
- `phase-loop-runtime/tests/test_phase_loop_execution_policy.py`
- `phase-loop-runtime/tests/test_model_class_policy.py`
- `phase-loop-runtime/tests/test_model_tier_taxonomy.py`
- `phase-loop-runtime/src/phase_loop_runtime/declared_identity.py`
- `phase-loop-runtime/src/phase_loop_runtime/plan_pin_lint.py`
- `phase-loop-runtime/src/phase_loop_runtime/producer_manifest.py`
- `phase-loop-runtime/src/phase_loop_runtime/proof_stages.py`
- `phase-loop-runtime/src/phase_loop_runtime/roadmap_reseal.py`
- `phase-loop-runtime/src/phase_loop_runtime/tdd_receipts.py`
- `phase-loop-runtime/tests/govlean_freeze_receipt.py`
- `phase-loop-runtime/tests/test_govlean_declared_identity.py`
- `phase-loop-runtime/tests/test_govlean_panel_policy.py`
- `phase-loop-runtime/tests/test_govlean_plan_manifest_issue_dispositions.py`
- `phase-loop-runtime/tests/test_govlean_plan_pin_lint.py`
- `phase-loop-runtime/tests/test_govlean_producer_manifest.py`
- `phase-loop-runtime/tests/test_govlean_proof_stages.py`
- `phase-loop-runtime/tests/test_govlean_roadmap_reseal.py`
- `phase-loop-runtime/tests/test_govlean_skill_policy_parity.py`
- `phase-loop-runtime/tests/test_govlean_tdd_receipts.py`
- `phase-loop-runtime/tests/test_review_policy_govlean_repairs.py`
- `plans/phase-plan-v10-GOVLEAN.md`
- `skills-src/claude/claude-plan-phase/SKILL.md`
- `skills-src/claude/claude-phase-roadmap-builder/SKILL.md`
- `skills-src/claude/claude-execute-phase/SKILL.md`
- `skills-src/codex/codex-plan-phase/SKILL.md`
- `skills-src/codex/codex-phase-roadmap-builder/SKILL.md`
- `skills-src/codex/codex-execute-phase/SKILL.md`
- `skills-src/gemini/gemini-plan-phase/SKILL.md`
- `skills-src/gemini/gemini-phase-roadmap-builder/SKILL.md`
- `skills-src/gemini/gemini-execute-phase/SKILL.md`
- `skills-src/opencode/opencode-plan-phase/SKILL.md`
- `skills-src/opencode/opencode-phase-roadmap-builder/SKILL.md`
- `skills-src/opencode/opencode-execute-phase/SKILL.md`
- `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`

**Dispatch holds**
- PROOFGATE — plan dispatch for PROOFGATE fails closed until this phase (GOVLEAN) is
  recorded completed in the ledger; machine-parsed by the runner's dispatch-hold guard
  (new-phase-side declaration: the grammar forbids editing PROOFGATE or forward
  dependencies, so the hold is declared here and enforced in the runtime)
```

The first 11 entries are the files GOVLEAN's landed commits in the window actually touched
(ah#644 #672 #683 #725 #670/#693 #711/#712 #714/#715 #637), then filtered — see the exclusion
list. The next 18 are GOVLEAN's deliverables from before the window: named by
`plans/phase-plan-v10-GOVLEAN.md`, untouched by any commit in the window, and with a
first-parent history consisting only of GOVLEAN branches — with one disclosed exception:
`test_govlean_panel_policy.py` has one touch from `fleet-board-defaults` (ah#643). It stays,
on authority rather than history: it is in GOVLEAN's plan `Owned files` (line 70) and is the
test that PROVES EC-GOVLEAN-5 (line 118); ah#643 changed board defaults and updated that test's
expectations, which is a foreign edit to a GOVLEAN-owned file — exactly what a claim should
flag. `panel_invoker.py` is NOT listed although the live roadmap claims it for GOVLEAN: the
"(EC-GOVLEAN-5 bounded edits)" are landed and verified, HARDEN owns the file under a freeze,
and at window 60 that single bullet produced every foreign GOVLEAN flag (table above). `skills-src/` is NOT kept as a
directory claim: its qualification ("planner and roadmap skills") is prose the matcher never
reads — the token matches every skill, and at window 60 it flagged ah#643's edits to the four
`*-advisor-board` skills. The 12 `SKILL.md` files are exactly the planner, roadmap-builder, and
execute-phase skills GOVLEAN's plan names, one per harness, plus `claude-plan-phase/scripts/
validate_plan_doc.py` which the plan's `Owned files` names; the other 18 files under those skill
directories (execute-phase `scripts/`, roadmap-builder `scripts/`, `assets/`) are NOT claimed —
the plan does not name them. Regeneration outputs under `phase-loop-skills/` and the packaged
`skills_bundle/` are NOT claimed either (other phases regenerate them too). `test_skill_liveness_contract.py` (agent-harness#731) is NOT
listed: it is not on `main` yet, and an entry that never appears in a diff is unmeasured.
Add it when #731 lands.

## What a window-only narrowing would have dropped

Replacing three directory-wide claims with literal files un-claims **1116** tracked files on
`main` (1064 become unclaimed by every phase; 52 stay claimed by another phase). That is the
point of the narrowing, not a side effect — but 32 of those 1116 are files
`plans/phase-plan-v10-GOVLEAN.md` itself names. Splitting the 32 by evidence:

| group | count | disposition |
|---|---|---|
| GOVLEAN-only first-parent history, untouched in the window | 18 | **claimed in v4** |
| touched in the window by another phase's commit | 5 | excluded — see the exclusion list; each one re-flags a foreign commit |
| shared history across phases, untouched in the window | 9 | excluded — `test_phase_loop_plan_manifest.py`, `test_phase_loop_planner_validation.py`, `test_phase_loop_roadmap_validate.py`, `test_roadmap_authority.py`, `test_skill_plan_manifest_write.py`, `test_skills_bundle_drift.py` (PROOFGATE ×2), `test_skills_canon_parity.py` (9 commits, ≥3 phases), `tests/data/launchspec_golden/launchspec_golden.json` (9 commits, 6 phases), `plans/phase-plan-v10-PROOFGATE.md` (PROOFGATE's own plan) |

The 9 shared files are the ones a LEGIBLE editor might reasonably decide differently. They
are named by GOVLEAN's plan as *inputs* it reads or extends, and other phases edit them; a
GOVLEAN claim on any of them would fire on those phases' merges.

## Measured is not authorized — the exclusion list

GOVLEAN's landed commits also touched these, and they are deliberately NOT claimed:

| path | why excluded | authority |
|---|---|---|
| `advisor_board/presets.py` | edited by ah#715 by mistake; caused HARDEN's SL-0 restart | HARDEN's roadmap Key files |
| `tests/test_advisor_board_presets.py` | same PR | HARDEN's frozen 26-path test inventory (`harden_tdd_guard.HARDEN_TEST_PATHS`) — **not** in HARDEN's roadmap Key files |
| `advisor_board/CONTRACTS.md` | same PR | **neither** — excluded on HARDEN's explicit freeze request only |
| `capability_registry.py` | same PR; HARDEN's production candidate edits it | **neither** — same |
| `tests/test_phase_loop_launcher.py` | ah#715 incidental | SCHED (3 of v1's over-claims) |
| `tests/test_panel_invoker.py` | named by GOVLEAN's plan; touched by ah#723 (HARDEN SL-0 restart r3) in the window | HARDEN's frozen test inventory (`harden_tdd_guard.HARDEN_TEST_PATHS`) |
| `roadmap_assumptions.py` + `tests/fixtures/roadmap-assumption-probes-v10.json` | named by GOVLEAN's plan; touched by ah#649 (RELEASE) and ah#616 (SCHED) | neither — shared by measurement |
| `plan_manifest.py` | named by GOVLEAN's plan; touched by ah#647 (LEGIBLE) | LEGIBLE's roadmap Key files |
| `tests/test_legible_review_repairs.py` | named by GOVLEAN's plan; 17 LEGIBLE PRs in its history | LEGIBLE by history |
| `tests/test_console_scripts_are_declared.py` | touched by ah#725 (one added case); created by ah#543 for shared console-script coverage; not plan-named | shared by scope and creation — window over-claim at 150 |

Deriving a claim from landed commits would have laundered ah#715's mistake into a standing
claim; deriving one from the plan's file list would have laundered five files other phases
own (v3's three extra flags are exactly ah#723, ah#649, ah#647).

The last two rows are themselves a `#688`-shaped gap: files HARDEN is actively editing
under a freeze appear in **no** Key files list, so nothing but the freeze request protects them.
Recorded here as input, not acted on.

### Verification of the authority column

`--preflight` reports ROADMAP claims. HARDEN's frozen test inventory is a different authority
(`harden_tdd_guard.HARDEN_TEST_PATHS`) that `--preflight` cannot see — the plan's acceptance
criterion 4 was amended to name both. Produced by the script below on `origin/main` `ee3213ea`:

| excluded path | `--preflight` claimants | in `HARDEN_TEST_PATHS` |
|---|---|---|
| `advisor_board/presets.py` | HARDEN | — |
| `tests/test_console_scripts_are_declared.py` | none outside GOVLEAN | — (shared by creation ah#543 and scope) |
| `tests/test_advisor_board_presets.py` | none outside GOVLEAN | **yes** |
| `advisor_board/CONTRACTS.md` | none outside GOVLEAN | — (neither: freeze request only) |
| `capability_registry.py` | none outside GOVLEAN | — (neither: freeze request only) |
| `tests/test_phase_loop_launcher.py` | none outside GOVLEAN | — (SCHED by measurement: 3 SCHED PRs) |
| `tests/test_panel_invoker.py` | none outside GOVLEAN | **yes** |
| `roadmap_assumptions.py` + probes fixture | none outside GOVLEAN | — (RELEASE ah#649 + SCHED ah#616 by measurement) |
| `plan_manifest.py` | LEGIBLE | — |
| `tests/test_legible_review_repairs.py` | none outside GOVLEAN | — (LEGIBLE by history: 17 PRs) |

```bash
cd phase-loop-runtime && PYTHONPATH=src:tests python3 - <<'VERIFY'
import subprocess, sys
from harden_tdd_guard import HARDEN_TEST_PATHS
for p in ["phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py",
          "phase-loop-runtime/tests/test_advisor_board_presets.py",
          "phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md",
          "phase-loop-runtime/src/phase_loop_runtime/capability_registry.py",
          "phase-loop-runtime/tests/test_phase_loop_launcher.py",
          "phase-loop-runtime/tests/test_panel_invoker.py",
          "phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py",
          "phase-loop-runtime/tests/fixtures/roadmap-assumption-probes-v10.json",
          "phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py",
          "phase-loop-runtime/tests/test_legible_review_repairs.py",
          "phase-loop-runtime/tests/test_console_scripts_are_declared.py"]:
    out = subprocess.run([sys.executable, "-m", "phase_loop_runtime.roadmap_ownership", "--repo", "..",
                          "--preflight", p, "--current-phase", "GOVLEAN"], capture_output=True, text=True).stdout
    claimants = sorted({l.split("claimed by:")[1].split("—")[0].strip() for l in out.splitlines() if "claimed by:" in l})
    print(f"{p:<75} {claimants or 'none outside GOVLEAN'}  frozen={p in set(HARDEN_TEST_PATHS)}")
VERIFY
```

## Part 2 — the residual 13, for a cross-phase decision (not acted on)

With GOVLEAN claiming nothing, 13/40 still flag. Claimant sets on those 13:

| claimants | count | note |
|---|---|---|
| REVIEWTRUTH alone | 5 | 13 specific claims; genuinely broad footprint |
| RELEASE alone | 2 | `CHANGELOG.md` / `pyproject.toml` — the near-universal claims the audit renderer already demotes to `Expected`; `--preflight` has no such demotion (known, ah#725) |
| HARDEN alone | 1 | |
| FABPUB + RESIDUAL | 1 | |
| LEGIBLE + REVIEWTRUTH | 1 | |
| LEGIBLE + RELEASE + REVIEWTRUTH | 1 | |
| HARDEN + LEGIBLE + RESIDUAL + REVIEWTRUTH + RUNTIME + SCHED | 1 | six claimants on one change |
| FABPUB + FABREADMIT + INTEG + RELEASE + RESIDUAL + RUNTIME | 1 | six claimants |

These are other phases' specific claims overlapping on specific files. Whether each overlap is
legitimate is that phase's call. The two six-claimant rows are the ones worth a look first.

## Reproduce

```bash
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --report 40 --base origin/main                                            # 37/40
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --report 40 --base origin/main --candidate-roadmap plans/govlean-candidate.md  # 18/40, GOVLEAN 8
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --report 60 --base origin/main --candidate-roadmap plans/govlean-candidate.md  # 24/60, GOVLEAN 10
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --report 150 --base origin/main --candidate-roadmap plans/govlean-candidate.md  # 45/150, GOVLEAN 15
```
Verbatim output of the candidate commands at `origin/main` `ee3213ea` (the lines acceptance
criterion 2 compares byte-for-byte):

```
roadmap-ownership --report (CANDIDATE roadmap, not history): 40 landed change(s) replayed (40 scored, 0 unscorable)

  would have flagged (CANDIDATE PROJECTION): 18/40 (45%)
```
```
roadmap-ownership --report (CANDIDATE roadmap, not history): 60 landed change(s) replayed (60 scored, 0 unscorable)

  would have flagged (CANDIDATE PROJECTION): 24/60 (40%)
```

The window moves as merges land; re-run before acting. The candidate must also lint:
`python3 -m phase_loop_runtime.roadmap_lint plans/govlean-candidate.md` (14 phases, OK).
