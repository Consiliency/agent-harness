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
| **v2 — v1 minus `plans/` minus `test_phase_loop_launcher.py`** | **18/40 (45%)** | **8** | **8** | **0** |
| floor — GOVLEAN claims nothing | 13/40 (32%) | — | — | — |

Sanity: a candidate identical to the live roadmap reproduces 37/40 exactly, so the candidate
path changes nothing but the text.

**v2 is the proposal.** Under it every remaining GOVLEAN flag sits on a commit GOVLEAN
itself landed. The 13-point gap to the floor is not over-claim; it is GOVLEAN owning its
own work.

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
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (EC-GOVLEAN-5 bounded edits)
- `phase-loop-runtime/tests/test_roadmap_ownership.py`
- `phase-loop-runtime/tests/test_closeout_classifier.py`
- `phase-loop-runtime/tests/test_agy_canary_evidence.py`
- `phase-loop-runtime/tests/test_console_scripts_are_declared.py`
- `phase-loop-runtime/tests/test_phase_loop_execution_policy.py`
- `phase-loop-runtime/tests/test_model_class_policy.py`
- `phase-loop-runtime/tests/test_model_tier_taxonomy.py`
- `phase-loop-runtime/tests/test_skill_liveness_contract.py`
- `skills-src/` planner and roadmap skills plus regeneration outputs

**Dispatch holds**
- PROOFGATE — plan dispatch for PROOFGATE fails closed until this phase (GOVLEAN) is
  recorded completed in the ledger; machine-parsed by the runner's dispatch-hold guard
  (new-phase-side declaration: the grammar forbids editing PROOFGATE or forward
  dependencies, so the hold is declared here and enforced in the runtime)
```

Derived from the files GOVLEAN's landed commits actually touched (ah#644 #672 #683 #725
#670/#693 #711/#712 #714/#715 #637), then filtered — see the next section. `skills-src/`
stays directory-wide: its qualification ("planner and roadmap skills plus regeneration
outputs") is accurate, and it fires only on skill edits.

## Measured is not authorized — the exclusion list

GOVLEAN's landed commits also touched these, and they are deliberately NOT claimed:

| path | why excluded | authority |
|---|---|---|
| `advisor_board/presets.py` | edited by ah#715 by mistake; caused HARDEN's SL-0 restart | HARDEN's roadmap Key files |
| `tests/test_advisor_board_presets.py` | same PR | HARDEN's frozen 26-path test inventory (`harden_tdd_guard.HARDEN_TEST_PATHS`) — **not** in HARDEN's roadmap Key files |
| `advisor_board/CONTRACTS.md` | same PR | **neither** — excluded on HARDEN's explicit freeze request only |
| `capability_registry.py` | same PR; HARDEN's production candidate edits it | **neither** — same |
| `tests/test_phase_loop_launcher.py` | ah#715 incidental | SCHED (3 of v1's over-claims) |

Deriving a claim from landed commits would have laundered ah#715's mistake into a standing
claim. The last two rows are themselves a `#688`-shaped gap: files HARDEN is actively editing
under a freeze appear in **no** Key files list, so nothing but the freeze request protects them.
Recorded here as input, not acted on.

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
  --repo . --report 40 --base origin/main --candidate-roadmap plans/govlean-candidate.md  # 18/40
```
The window moves as merges land; re-run before acting.
