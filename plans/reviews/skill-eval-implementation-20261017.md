# Skill-eval implementation review and acceptance record

Scope: reviewed evaluator fixes and the narrow
[CI-evidence amendment](../amendments/skill-eval-ci-evidence-20261017.md) for
[DRAFT agent-harness#1733](https://github.com/Consiliency/agent-harness/pull/1733).
The [original detailed plan](../detailed-skill-eval-20261015-0614.md), SHA-256
`dec674e831b818e91a0003ee52172228a341566c38bf2b497967f6027341f989`, and
[plan-review history](skill-eval-20261015.md) remain unchanged. Plan review is
distinct from the implementation reviews below.

## Authority and review route

The owner authorized Sol implementation, the narrow CI-evidence amendment,
independent manual Opus/Gemini review through T3 Code, and readiness reassessment.
The owner subsequently switched Claude from Frontier to Regenesis after quota
exhaustion. Frontier performed no review. These are manual T3 reviews, not a
successful runtime advisor-board invocation. Publication is authorized; merging
and readiness promotion are not authorized at this stage.

Both candidates use local HEAD `8aecf2fdb7bb2468e4cfcb650585fae1ade4dda2`
and comparison main `a776e681b24f2f019c9908f91a0e97caf99ab5d6`, with
different frozen working overlays. HEAD alone does not identify reviewed bytes.

| Reviewer / account / model | Review base and verdict | Carry limits |
| --- | --- | --- |
| Opus / `t3-claude-regenesis` / `claude-opus-5-5` | Full prior repair-candidate review: **PARTIALLY AGREE**, conditional support for the narrow CI method, blocker B1 | Full review was not final implementation approval. |
| Opus / `t3-claude-regenesis` / `claude-opus-5-5` | B1 delta review: **AGREE**; identity and packet checks passed before and after review; B1 resolved, no surviving blocker | Covers B1 runner repair and associated tests/docs. Optional extra test assertions were nonblocking and were not added after approval. |
| Gemini / `antigravity` / `gemini-4-argon-high` | Rounds 1–3 ended with **AGREE** on the prior repair candidate; identity checks passed before and after final review | Prior-base verdict only. Returned citations named nonexistent `parse_events`, `valid_access` and `main`, misstated the feature tuple, and confused reproduction/broad counts. Those claims are not adopted. No fourth round or B1-delta Gemini approval is claimed. |

## Frozen identities

All values below are SHA-256 of recorded bytes, not fabricated commit identities.

| Binding | Prior repair candidate (Gemini final / Opus full) | B1 candidate (Opus delta) |
| --- | --- | --- |
| Identity | `41ba42ee17ce21c00aa8b5fd71dc2cb3e1eecdac7c023a12ffbfa294e551f28d` | `9b4c4c3734d9c8528e8244ff0287f826c3f913e2bf865e18885c096e0c187b7f` |
| Packet manifest | `622d1d425614fd9a17d7cbb71e20d8e74658863c2f63ced7aa9e06f655164e8d` | `060986c85c391ba72978b3ac40fb768d1824ec25c28934ea21e7e7667a7b2273` |
| Complete public diff | `0069ff4e7b7ac12ec7cb07420fd27005e570f55fc3a8627409bdc51612f40317` | `4ee9f78804aae677da86fb83069d415b1e661c663d2068aa58a4cbaccf1ca07c` |

The B1 snapshot delta is
`fe55bd11fcbec3e4137294b87b26d71aea50be0f898a3c98207d5997ed9c06c2`.
The reviewed amendment bytes were
`3528b9f482ac044e99e0689a1f23f701c1394cdbef884c7a75135510ba317a4d`;
its later method-status/route correction and this record are procedural publication
documentation, not additional reviewed runtime changes. The publication candidate
must be bound separately by its actual Git head and fresh CI evidence.

## Findings, repairs and deferrals

The prior repair enforces single-turn event ordering, refuses identity-bearing
packet inputs, and handles malformed scores while retaining failed one-shot
calibration evidence. B1 identified that the launcher can return cancellation
rather than raise it. `skill_eval_runner.run_trial` now retains the interruption
flag and actual cleanup evidence, classifies the trial invalid before stream
parsing, persists bound receipts, then propagates interruption. Cleanup absence
remains null and reported cleanup failure remains failure. Shared launcher
semantics and the experiment's `run()` loop are unchanged.

Observed B1 reproduction: five failed, nine passed; the batch made 48 calls
instead of one. After repair, all 14 selected controls passed. Actual
`LaunchResult` fakes cover interrupted nonzero/zero exits and empty/partial/full
responses, cleanup present/absent/failed, and raised interruption/SystemExit.
The batch test makes one call, leaves all 47 later trials unclaimed, retains the
first receipts, and permits only untouched work on a later explicit run.

Nonblocking suggestions remain deferred: packet/calibration workflow ordering,
moving context cleanup after receipt persistence, broader identity-marker
coverage, and ordinary invalid-trial cost policy. Existing calibration claim
ordering and executable preflight remain under the original contract. These
limits were retained without broadening B1 or filing new issues.

## Evidence, integration and acceptance

The B1 sealed bounded artifact records locked Python 3.12.14 dependency refresh
and 14 successful commands: 161 focused tests, 74 required Linux controls with
**zero skips**, 46 packaging, seven inventory, 89 integration tests, fresh
installed-wheel entrypoint/import validation, entry docs, lint and whitespace.
Docs freshness explicitly reported **skipped**. These offline checks used fake
subjects and real owned process controls; no model pilot or human calibration ran.

Publication reconciles one additional main snapshot,
`3c001bf1d55654aa48709ebcbd0b5d9832234181` (agent-harness#1747), changing
only the static-import test module and upstream manifest metadata. Reviewed
evaluator source/tests/guide/changelog bytes are preserved; no launcher, stage,
ownership or calibration interface changes. The original plan and evaluator's
failed manifest row are preserved. Focused integration checks and the procedural
documentation checks supply bounded post-review evidence, not new vendor review
or full-suite coverage.

**Evidence method accepted; candidate verification pending.** AC1–4 and AC6 retain
their satisfied offline verdicts. **AC5 remains UNMET.** Historical local
`make check`/`make check-full` failures and the failed lifecycle remain unchanged.
Historical successful dispatch 39004507757 covers only `2dc68fc`, not this
candidate. Actual successful full Python 3.12 source/copy legs, lint, installed
Gate A and all six required PR checks must cover the published candidate before
acceptance reduction/readiness reassessment. Dispatch acceptance is not PASS.
No exact-head unanimous board, Frontier approval, live qualification, automatic
skill adoption, or merge approval is claimed.
