# Skill-eval plan board review

Artifact: `plans/detailed-skill-eval-20261015-0614.md`
Branch: `plan/skill-eval-20261015`
Input base: `b9892d298aa23297e3f37eea5e2b4995c67ec60e`
Requested by the owner: “panel the plan”.

## Review contract, recorded before round one

Use the runtime-owned four-seat advisor board with the plan landing tier and its president. Review scientific validity, implementation feasibility, isolation and observation boundaries, deterministic verification, and fit to the plan's declared acceptance criteria. This review authorizes plan corrections only; implementation and live experiment trials remain outside the current task.

The review/fix loop has a maximum of **three rounds**. Collect all seats before changing the plan. A blocker must cite the plan's acceptance criteria, declared experiment/evidence contract, or an existing invariant. Suggestions do not silently expand scope. After corrections, rerun dissenting or unusable seats against the recorded delta; carry only usable AGREE verdicts. At the cap, remove separable blocking scope and leave it explicitly pending, or report a surviving blocker. Do not extend the cap or waive a blocker.

Round identities bind to SHA-256 hashes of the actual plan bytes; Git HEAD alone cannot identify this uncommitted plan. No future output commit, count, or topology is prescribed.

## Status

**Owner-authorized manual T3 plan review converged: all standing verdicts AGREE.** Final plan SHA-256: `dec674e831b818e91a0003ee52172228a341566c38bf2b497967f6027341f989`. No plan-review blockers remain. The runtime-board attempts remain recorded as failed; the owner explicitly authorized the alternate route. This is plan review, not a successful runtime-board invocation or merge permission. The plan remains uncommitted and implementation has not started.

## Round one

Plan SHA-256: `a05b0bb9cd74ee021876834c1adde4198c32402d6ddee6b5df2f438f18ad2b96`.
The installed `phase-loop` used an older site-packages runtime rather than this worktree's source. Requested models: Grok 4.7, Claude Opus 5.5, GPT-6 Astra, Gemini 3.8 Flash. No usable approval is carried from this round.

| Seat | Outcome | Limitation |
|---|---|---|
| Grok | ERROR | CLI exited without a review |
| Claude | DEGRADED | `claude_tui_missing_canonical_output` |
| Codex | PARTIALLY AGREE | Its source-reading commands failed with `bwrap: No permissions to create a new namespace`; isolation/observation feasibility remains unverified |
| Gemini | AGREE text, not source-grounded | Sealed route; pointer-brief material inaccessible; excluded from source-grounded floor |

The president held acceptance pending a working source-grounded review environment. Board command exited nonzero. The raw private evidence is under `/mnt/workspace/users/viperjuice/tmp/skill-eval-panel-20261015-p8ixj4mq/round-1-*`.

## Round two preparation

Keep the plan bytes unchanged and rerun through this worktree's `phase_loop_runtime` using the installed interpreter with an explicit source `PYTHONPATH`. Use the source runtime's recorded composition, not the old installed defaults; no verdict is carried. The canonical source's maintainer ruling in `plans/decision-claude-print-subscription-route-20261008.md` (agent-harness#1391) admits the subscription-proven print adapter and supersedes the installed skill's older TUI-only wording. Select that admitted route explicitly; no API/SDK/gateway fallback is allowed. Preserve unavailable or refused seats in the result.

## Round two result

The plan bytes were unchanged. The source runtime requested Grok 4.7, Claude Opus 5.5, GPT-6 Astra and Gemini 4 Argon. **All four were DEGRADED; zero usable reviews.** Grok produced introductory text without a completed verdict; Claude reported `claude_tui_missing_canonical_output`; Codex was refused as `seat_tool_sandbox_unavailable` (known nested-namespace limitation, agent-harness#1335); Gemini was refused as `gemini_seat_egress_unconfined` before invocation. No substitution or native fill was made.

The president ruled **HALT — do not advance the phase**. This remains an open landing-review blocker. No review-policy or host-isolation exception has been made. The command exited nonzero. Round-one/two streamed leg files share the CLI's default stream directory, so only each round's separate final JSON and bound input are authoritative for its seat results; a stray earlier streamed verdict is not carried.

## Corrections before round three

These are source-confirmed corrections by the driving agent, not attributed to unavailable reviewers:

1. `build_codex_command(read_only=True)` emits a staging placeholder, while direct `launch` does not resolve it. Materialize through the existing resolver before profile construction and watch the resolved copy's actual inodes. Add controls proving the source copy is unobserved.
2. Require guide access in every case, pin the executable used, and keep actual Codex tool qualification separate from Python-process observer controls. Host namespace failures cannot be bypassed or counted as successful qualification.
3. Lock the experiment to prevent concurrent runners exceeding the trial schedule.
4. Distinguish gold score/reducer tests from semantic validation of human rubrics. Require a separate blinded gold calibration receipt before a promising result.

## Round three contract

Attempt the current runtime's documented `--advisory` document-review mode with the full revised plan and exact relevant source excerpts inline. This is a different, explicitly **non-gating** evidence class: no source-pointer claim, no president/landing-tier request, no merge approval, and no cancellation of the round-two HALT. The private scratch authority contains no project tree. The intended packet gives every seat the same self-contained bundle and prior failures/corrections. This is the final round within the recorded cap. Report its actual requested/delivered seats and findings even if it remains unusable; do not retry into a fourth round.

## Round three result

Revised plan SHA-256: `cf560b27618be6debcc72e336a5816d1d639d2aa960c6b83689bf09a63605118`.
Delta base: `a05b0bb9cd74ee021876834c1adde4198c32402d6ddee6b5df2f438f18ad2b96`.
The exact revised plan, delta, source excerpts and binding are preserved in the private evidence directory as `round-3-*`.

The invocation exited 2 with `president refused [review_landing_tier_required]: post-switch board invocation requires an explicit landing tier or policy`. No reviewer launched and no advisory review was delivered. The CLI's documented `--advisory` mode forbids `--landing-tier`; the lower runtime nevertheless demands one on this path. This is a separate invocation-contract failure, not a plan verdict. Do not supply an incompatible landing tier, inject test seams, waive the president's HALT, or represent advisory evidence as landing approval.

## Remaining work

Restore a functioning review environment/entrypoint, then review the revised plan with a newly agreed review budget. The known Codex namespace prerequisite and Gemini containment prerequisite remain unresolved; Claude's canonical-output failure and Grok's incomplete review also remain. The advisory admission mismatch needs its own bounded investigation. No host, runtime, auth, or review policy was changed here. Implementation, live experiment qualification, skill adoption and archival are still pending.

The cap follows the advisor-board skill's “Round cap → descope” rule: a blocker that survives the cap and cannot be removed with its scope halts for the operator. The three-round number was selected for this task before round one; it is not a universal skill requirement. The missing review cannot be removed while still claiming the owner-requested panel succeeded, so this result remains blocked.

No tests or live skill-eval trials ran. Review attempts used subscription CLI adapters through the runtime. No Git commit, push, PR or merge occurred.

## Owner-authorized T3 delegation route

After the blocked result the owner instructed: “hand launch whatever agents via T3 Code delegation to get past the block and continue”. This explicitly authorizes an alternate manual review route and reopens the review task. The original runtime-board HALT and failed attempts remain historical evidence; T3 review results must not be mislabeled as a successful runtime-board invocation or merge authorization.

Before launching: select three independent read-only reviewers from the live T3 catalog — Claude Opus 5.5 (implementation correctness), GPT-6 Astra (adversarial evidence validity), and Gemini 4 Argon High (experiment design/alternative approach). They all review plan SHA-256 `cf560b27618be6debcc72e336a5816d1d639d2aa960c6b83689bf09a63605118` and the actual referenced source in the existing owned worktree. No skill edits, tests, archival, implementation, commits or publishing are delegated.

This owner-authorized route gets a fresh cap of three review/fix rounds. Collect all reviewers before changing the plan. Blockers must name an acceptance criterion, declared contract or existing invariant and a concrete failure scenario. Reconcile once, then delta-review dissenting or unusable seats with new T3 tasks, original briefs, findings, responses and unresolved objections. Carry only usable AGREE verdicts and bind all standing verdicts to the reviewed plan/delta hashes. Do not count startup/tool failures as approval. At the cap, descope separable blockers or record a surviving blocker; no silent cap extension.

T3 round one is in progress. Claude's default and Frontier provider instances both failed before review with a rate-limit error; neither supplies findings or a vote. Grok 4.7 now owns that implementation lens under the owner's explicit “whatever agents” instruction. Astra and Gemini remain the other independent reviewers. These startup substitutions are recorded, not silent reviewer approvals.

## T3 round one result and reconciliation

All three active reviewers completed source-grounded reviews of plan `cf560b27618be6debcc72e336a5816d1d639d2aa960c6b83689bf09a63605118` and returned **PARTIALLY AGREE**. None reported outstanding source-access failure. No AGREE verdict is carried.

| Reviewer | Provider / model | Task client request ID | Blocking findings |
|---|---|---|---|
| Evidence validity | codex / gpt-6-astra | `skill-eval-20261015-t3-astra-r1` | EVID-001 |
| Implementation | grok / grok-4.7 | `skill-eval-20261015-t3-grok-r1` | SE-OBS-1, SE-WEB-1, SE-SCORE-1, SE-PKG-1 |
| Experiment design | antigravity / gemini-4-argon-high | `skill-eval-20261015-t3-gemini-r1` | B1, B2, B3, B4 |

Full responses are preserved privately in `/mnt/workspace/users/viperjuice/tmp/skill-eval-panel-20261015-p8ixj4mq/t3/{astra,grok,gemini}-r1.md`. Their task IDs are the corresponding T3 delegated nodes under this parent thread; the stable client request IDs identify each task without treating child threads as future-round targets.

All blocking findings were accepted and reconciled in one plan revision:

* **EVID-001 / B1 / SE-SCORE-1:** Resolve the contradiction conservatively: guide access is required exposure; an unexposed trial invalidates the comparison and cannot manufacture a treatment win. Missing case-fixture access after exposure is still a behavioral failure. Specify PASS/FAIL pair mapping and require all negative-control baseline trials to pass before comparison sensitivity is established. This chooses the alternate correction Astra offered and follows Gemini's causal distinction; it does not silently weaken acceptance criterion 4.
* **SE-OBS-1 / B3:** Put preimage and resolved stage below the existing staging root, outside experiment/log placement and every Git worktree. Use `log_path=None` for stage resolution; reject Git discovery failures or enclosing repositories before observation. Existing launcher snapshots therefore cannot hash watched untracked fixtures. Require an in-Git refusal control and source-copy non-observation.
* **SE-WEB-1 / B4:** Freeze explicit ephemeral/execpolicy/feature/web controls, preserving shell/code-mode tools. Distinguish private-network filtering from web disablement. Before the watch, require a positive no-inference Codex inner-sandbox probe through the same owned executable/profile/cwd/network context. Unknown/failed probes refuse rather than spend subject calls or bypass isolation.
* **B2 / EVID-S02:** Define experiment-local, one-shot calibration state/receipt under the experiment lock, exact scorer/experiment/packet/rubric/gold-pack binding, no annotation release, and no second attempt or foreign receipt. Prior-disclosed examples are practice only under an explicit procedural human trust declaration.
* **SE-PKG-1:** Add the exact console target to the release allowlist, specify a zero-required-argument callable, list existing packaging tests and update the README's console-script inventory.
* **EVID-S01 and other clarifications:** Explicit receipt joins and swap/missing-receipt falsifiers; exact scoreable-ID handling without invented scores for invalid/no-output trials; legal ModelSelection profile; terminal JSON event/merged-diagnostic rules; common no-Git/final-message envelope; precise skill anchors; and identity scans that do not reject ordinary case vocabulary.

No implementation or tests were performed. The declared first increment still owns eight source/config/test/fixture files plus its docs and changelog; it introduces no new provider framework, shared protocol vocabulary or skill edit.

## T3 round two

Delta base: `cf560b27618be6debcc72e336a5816d1d639d2aa960c6b83689bf09a63605118`.
Revised plan: `13128613722fe500e1781d7eb15a6b928f2b3f28049273a3d69089e7adf08f48`.
Exact snapshots, diff and binding are private `t3/round-1-plan.md`, `t3/round-2-plan.md`, `t3/round-2-delta.diff`, and `t3/round-2-binding.json`.

Rerun all three dissenting reviewers as new T3 delegated tasks with original briefs, their findings, this reconciliation and the delta. No prior runtime or T3 review is carried as AGREE. This is round two of the owner-authorized three-round cap; review outcome pending.

## T3 round two result

Astra and Gemini returned **AGREE**, confirming their original blockers and relevant cross-review changes resolved at plan hash `13128613722fe500e1781d7eb15a6b928f2b3f28049273a3d69089e7adf08f48`. Grok returned **PARTIALLY AGREE**: SE-WEB-1, SE-SCORE-1 and SE-PKG-1 resolved; SE-OBS-1 remained ambiguous because an expected non-repository Git result is itself nonzero.

Grok's final correction is accepted: freeze C-locale diagnostics; distinguish repository present (return 0, refuse), confirmed absence (return 128 plus the exact non-repository fatal prefix, allow), and discovery unavailable (all other errors/codes/diagnostics, refuse). Tests must cover all three outcomes, not merely classify every nonzero result as absence or failure.

Also adopt Grok's nonblocking clarifications for a finite no-inference probe through the existing owned launcher (without putting a deadline on subject review), and for packet creation versus calibration attempt/receipt creation. Keep the existing REQUIRED_SCRIPTS expansion suggestion outside this plan: the planned new entrypoint smoke already executes the actual no-argument console target; release-map equality and existing packaging tests are required. No blocker is waived by that test-location choice.

Full responses are preserved privately as `t3/{astra,grok,gemini}-r2.md` in the evidence directory. The two AGREE verdicts are carried only across this narrow operational delta; the dissenting implementation lens is rerun. No approval of pilot efficacy, runtime-board operation or merge follows.

## T3 round three

Final permitted owner-authorized round: new Grok delta task, original brief and both prior reviews, all responses and remaining SE-OBS-1 objection supplied. Delta base is `13128613722fe500e1781d7eb15a6b928f2b3f28049273a3d69089e7adf08f48`. Final snapshot/diff/binding are preserved as `t3/round-3-*`. Astra and Gemini are AGREE (carried from round two). Grok result pending; do not extend into round four.

## Final T3 result — 2026-10-15T07:35:04Z

Grok returned **AGREE** on final hash `dec674e831b818e91a0003ee52172228a341566c38bf2b497967f6027341f989`, confirming SE-OBS-1 resolved and no blocking regression from the probe-bound/calibration clarifications. Its response is preserved privately as `t3/grok-r3.md` and in this parent thread's T3 delegated task result.

| Reviewer | Standing verdict | Binding / provenance |
|---|---|---|
| Astra, evidence validity | AGREE (carried) | Round two, hash `13128613722fe500e1781d7eb15a6b928f2b3f28049273a3d69089e7adf08f48`; task `skill-eval-20261015-t3-astra-r2` |
| Gemini, experiment design | AGREE (carried) | Round two, same hash; task `skill-eval-20261015-t3-gemini-r2` |
| Grok, implementation | AGREE (fresh) | Round three, final hash `dec674e831b818e91a0003ee52172228a341566c38bf2b497967f6027341f989`; task `skill-eval-20261015-t3-grok-r3` |

The carried verdicts follow the predeclared delta-review contract: only the dissenting implementation lens reran on the narrow final Git-classification, probe-bound and calibration-command changes. There is no claim that all three freshly reviewed identical final bytes. Both earlier Claude startup attempts remain rate-limit failures with no vote.

The owner-authorized plan-review task is complete within its fresh three-round cap. No blocker was waived, no further round was started, and no runtime/host/auth/review policy was modified. Runtime-board repair remains separate work; it is not an unperformed dependency silently represented as complete.

Review evidence consists of source inspection and declared test/qualification obligations. No pytest/build, seat-owner/inotify validation, real Codex eval trial or skill application ran. Grok also inspected Git discovery behavior under C locale using temporary staging-directory metadata probes; that is not proof of the future observer or pilot. Implementation, its required checks, live operational qualification, and any later merge authorization remain pending.
