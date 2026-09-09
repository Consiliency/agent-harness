# Decision note — interim ratification of president-gated landing tiers

**Date:** 2026-09-04
**Anchor:** `origin/main` @ `c567c01c`
**Decided by:** the maintainer (operator ruling, relayed by the operator's claude session)
**Decision:** **Until a HARDEN-authorized president execution operation exists
(Consiliency/agent-harness#752), the `plan` and `production_code` landing tiers land on
four-seat cross-vendor convergence with no president ruling.** This is an explicit, dated,
expiring exception recorded here — not a change to the runtime default and not a silent
bypass.

## Why an exception is needed

`review_policy_for_tier` (`phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`)
answers the `plan` and `production_code` tiers with `requires_president=True`, as
EC-GOVLEAN-5 mandates ("full board plus president for production-code and plan landings").
Since Consiliency/agent-harness#750 (ah#736) a president-requiring policy also requires a
president seam, and the only adapter (`president_adapter.build_president_invoke`) answers
every seated rung with `president_execution_route_unavailable` — by design, because
post-HARDEN (EC-HARDEN-5) the only production execution operation is the governed review
and a president ruling's terminal grammar (`FORCING DECISION:`) is not that operation's
grammar. The adapter's docstring names the replacement: a HARDEN-authorized president
operation with its own mode, brief, completion grammar, and authorization identity. That
operation does not exist yet.

The consequence, measured on 2026-09-04: every plan- and production-code-tier landing fails
closed by construction. Four converged PRs (Consiliency/agent-harness#765, #768, #769,
#771) sat parked with 4/4 AGREE recorded and no path to `main`. The maintainer's ruling:
"What about the failure to merge any work" → interim ratification.

## What the exception is

- **Scope.** Landings whose review tier is `plan` or `production_code` under the GOVLEAN
  authority switch (in force for agent-harness).
- **Bar.** The full four-vendor board (`fable`, `sol`, `gemini`, `grok`) must converge
  4/4 AGREE on the landing head under the advisor-board skill's review-round rules (which
  seats re-review after a delta, the round cap, and what "exact head" means are defined
  there, not here). Nothing below the full board is admitted; the exception removes only
  the president ruling, not any seat.
- **Mechanism.** The landing caller passes an explicit
  `ReviewLandingPolicy(required_seats=("fable", "sol", "gemini", "grok"),
  requires_president=False)` to `invoke_board`. `review_policy_for_tier` is NOT changed:
  the tier default and the `landing_tier=` path still require a president and still fail
  closed. The exception is reachable only by constructing that policy by hand, and the
  runtime does not know this note exists: nothing binds the override to a citation or a
  ledger row. Citing this note and appending the ledger row are recording obligations on
  the operator performing the landing, enforced by review of that landing's PR body, not
  by code. Stated plainly: for every landing in the ledger below, EC-GOVLEAN-5's "full
  board plus president" mandate is not met; the runtime's frozen controls stay green
  because the runtime is unchanged, not because the mandate is satisfied. This note is a
  procedural exception — a documented, dated bypass of the president ruling with the
  maintainer's authority behind it — until the roadmap carrier lands.
- **Record.** Every landing performed under this exception cites this note in its PR
  body and appends itself to the ledger below (append-only; do not rewrite earlier rows).
- **Expiry.** The exception ends the moment the president operation from
  Consiliency/agent-harness#752 lands on `main`. Because the default was never changed,
  nothing in the runtime needs reverting — but nothing in the runtime stops a caller from
  continuing to hand-construct `requires_president=False` either. So expiry is a closing
  action, not a passive event: the PR that lands ah#752 MUST, in the same PR, append a
  final `EXPIRED by Consiliency/agent-harness#<that PR's number>` row to the ledger below
  and mark this note closed (the PR number is known before merge; the merge commit is
  not, so the row is keyed on the PR, not the commit). Expiry takes effect when that PR
  merges to `main` — not when the row is written, and not later. ah#752's issue body
  carries that obligation. From that merge on, any `plan`/`production_code` landing that
  passes `requires_president=False` is a governance violation to be raised on the landing
  PR, and any launcher script that still hard-codes the override (the operator's
  standalone `invoke_board` launchers) is to be deleted or switched to `landing_tier=`.
  This note stays as history.

## What this does NOT change

- The roadmap `specs/phase-plans-v10.md` is LEGIBLE-owned and is not edited here. The
  roadmap-text carrier for this exception is Consiliency/agent-harness#688 (roadmap edit
  proposal); this note is the operator record until that lands.
- The president availability ladder, ruling grammar, and typed-refusal behaviour
  (`president_ruling_missing`, `president_execution_route_unavailable`) are unchanged.
- `tests_only` / `docs_only` tiers (single grounded reviewer) are unchanged.
- EC-HARDEN-5: no execution route is added for president rulings; nothing routes around
  `harden_advisory_execution_refused`.

## Ledger of landings under this exception

| PR | Tier | Landing head | Board record |
|---|---|---|---|
| Consiliency/agent-harness#765 | plan | `08acf487` | r1 grok/gemini AGREE, codex/claude DISAGREE (2 findings); delta r2 codex/claude AGREE → 4/4 |
| Consiliency/agent-harness#768 | production_code | `5277cd6f` | r1 3 AGREE + fable PARTIALLY AGREE (2 findings addressed); exact-head delta 4/4 AGREE (recorded in PR body) |
| Consiliency/agent-harness#769 | plan | `e205cfa7` | exact-head plan board 4/4 AGREE (recorded in PR body) |
| Consiliency/agent-harness#771 | tests_only (not under this exception; listed because it is the stack leaf) | `b50f0b99` | fresh four-vendor 4/4 AGREE (recorded in PR body), exceeding the tier's single-grounded-reviewer bar |
| Consiliency/agent-harness#777 | production_code | exact head recorded in the PR body | four-vendor board, `requires_president=False` (record in PR body) |
| Consiliency/agent-harness#786 | production_code | exact head recorded in the PR body | four-vendor board, `requires_president=False`; landing conditional on 4/4 exact-head AGREE and required CI (record in PR body) |
| Consiliency/agent-harness#788 | production_code | exact head recorded in the PR body | four-vendor board, `requires_president=False`; landing conditional on 4/4 exact-head AGREE and required CI (record in PR body) |
| Consiliency/agent-harness#787 | production_code | `0d4ce954` (merged `00df53e0`) | **recorded post-merge, gap acknowledged**: exact-head rounds ran on `ddbe6b58` (r2: 2 AGREE, codex DISAGREE ×3, fable n/a) and `8c5e4440` (r2: codex/gemini/grok AGREE, fable PARTIALLY AGREE, 1 blocking); the two commits after `8c5e4440` had no exact-head board; merged on maintainer instruction without a 4/4 record; the blocking finding is carried to Consiliency/agent-harness#794 (next row). Records: PR comments on ah#787 |
| Consiliency/agent-harness#794 | production_code | exact head recorded in the PR body | four-vendor board, `requires_president=False`; landing conditional on 4/4 exact-head AGREE and required CI (record in PR body); carries ah#787's open blocking finding |
| Consiliency/agent-harness#798 | plan | `3edae821` | ah#789 detailed plan; r1-r3 not converged, r4 3/4 (codex DISAGREE, records on the PR); r5 grok/gemini/fable AGREE + codex PARTIALLY AGREE with no finding → same-head codex delta with the cited source inlined → 4/4 AGREE (recorded in the PR body); this row is a recording-only commit on the board head |
| Consiliency/agent-harness#803 | production_code | `f48d6b87` | ah#789 Workstream A; r1 grok/gemini/fable AGREE + codex DISAGREE (blocking: admission record turning incompatible between `probe_readable` and `_block_unsealed_owner`); r2 on `f48d6b87` 4/4 AGREE (in-lock `_records()` re-validation + loud `lock_held` guard; four fable residuals carried in the PR body); records: PR comments on ah#803; this row is a recording-only commit on the board head |
| Consiliency/agent-harness#804 | production_code | `7bbf7c92` | ah#789 Workstream B; r1 on `678f9ad9` fable DISAGREE (F1–F3) + codex/gemini/grok AGREE; r2 on `bb7fdc85` fable/gemini/grok AGREE + codex coverage nit; r3 on `adaf6c30` codex DISAGREE (blocking: `<repo>/.git/objects` rows refused as pruned) + 3 AGREE; r4 on `7bbf7c92` 4/4 AGREE (discovery-based recorded-path health check; fallback candidate keeps strict own-common-dir equality; foreign-discovery shape and cutover-side coverage carried to Workstream D); rebased onto `004c033a` (ah#803) with an all-`=` range-diff before this row; records: PR comments on ah#804; this row is a recording-only commit on the rebased board head |
| Consiliency/agent-harness#810 | plan | `91af9542` | ah#789 Workstream D detailed plan (FABPUB partition rotation, `plans/detailed-789d-fabpub-partition-rotation-20260908.md`); r1–r13 spliced text not converged, r14 (`80569e60`) clean rewrite from the settled generational-stores contract: gemini/grok AGREE, codex DISAGREE ×3, fable PARTIALLY AGREE; r15 (`d6273ad3`) gemini/grok AGREE, codex DISAGREE + fable PARTIALLY AGREE on the same inventory-walk fact (`live.py:2220`); r16 on `91af9542` 4/4 AGREE (narrowing taken over widening; in-lock predicate siting; fable F1 + two gemini nits carried to the lanes in the r16 record); records: PR comments on ah#810; this row is a recording-only commit on the board head |
| Consiliency/agent-harness#816 | production_code | `da2e9a6e` | ah#789 Workstream D Lane D2 (`rotate_blocked_partition` production + D1 descope absorption); r1 (`c8294fb2`) → r2 (`31cf3ed7`: gemini/grok AGREE, codex 2×P1, fable P1) → r3 (`30e2b827`: gemini AGREE + nit, grok AGREE, codex DISAGREE P1 = two post-flip completion paths, fable PARTIALLY AGREE) → r4 (`e0203d74`: gemini/grok AGREE, codex DISAGREE P1 = predecessor ledger never un-settles a key, fable PARTIALLY AGREE F1/F2) → r5 (`218e8daf`: gemini/grok AGREE, codex DISAGREE P1 = resume skips the partition-map digest, fable PARTIALLY AGREE F1 = latest-row fix reached only `dangling`) → r6 (`77ed9d33`: gemini/grok AGREE, codex DISAGREE P1 = resume binds the sealed digests but not the partition's identity/container/predecessor content, fable PARTIALLY AGREE F1 = same class × 4 fields) → r7 (`5d12b8c3`: gemini/grok AGREE, codex DISAGREE P1 = resume binds only the loader-visible fields, the inventory's authority-bearing fields are taken on trust, fable PARTIALLY AGREE F1 = same class / F2 bare `LegacyCutoverConflict` on a foreign successor receipt) → r8 (`7f65d58d`: gemini/grok/fable AGREE, codex DISAGREE P1 = the post-flip completion arm never adjudicates the attestation nor derives — residue of the r7 class, confirmed by probe) → r9 (`43391a25`: gemini/grok AGREE, codex DISAGREE P1 = TOCTOU between the pre-flip backstop under the predecessor lock and the finish under the successor lock — confirmed by probe, fable PARTIALLY AGREE F1 = generation ≥ 2 post-flip arm unwitnessed) → r10 (`5de39a46`: gemini/grok/fable AGREE, codex DISAGREE P1 = the adjudication hashed the predecessor then parsed it by separate reads — confirmed by probe, judged a NEW class, maintainer authorized a structural round) → r11 (`f843615b`: grok/gemini AGREE, codex DISAGREE P1 = `legacy_root_inventory` inherited from the separately-loaded container receipt, fable DISAGREE P1 = `sealed_partition_effects` re-read the predecessor's sealed inventory unbound to `inventory_sha256` — RUN probe sealed forged provenance into gen 2; both classified residue of the r10/r11 snapshot class) → r12 on `da2e9a6e` 4/4 AGREE (`sealed_partition_effects` digest-bound to the receipt it serves — closes the publish-path TOCTOU too; `_derive_rotation_inventory` inherits from the snapshot-bound predecessor receipt; A11v swap-probe + control, A11w container-forge, A11t widened to the whole fixture root over gen 0→1 / 1→2; three mutation witnesses RUN on a scratch tree); fable r3 O2 filed as Consiliency/agent-harness#817, D9-C container-lock remedy + fable r1 F3/F4 + r2 O1 + r5 O3 + r6 O4 + r8 O3 + r9 O3 + r10 O2/O3 + r11 O5 + r12 O1/O2 carried to Lane D4/D5; records: PR comments on ah#816; this row is a recording-only commit on the board head |
| Consiliency/agent-harness#818 | production_code | `dd7812df` | ah#789 Workstream D Lane D4 (`fabpub-rotate-partition` operator surface: CLI verb, docs, CHANGELOG, 19 CLI tests); production unchanged since `3434f67d` (r2) — r1 (`568c6831`) and r2 (`3434f67d`) 2/4, r3 (`03286f37`) 3/4, r4 (`12245c46`) 2/4 (codex DISAGREE F1 = missing latch after the `ACTIVE` row is refused, never recreated; fable DISAGREE F1 = a fifth chain link and the un-nameable drifted side, F2 = same as codex) — all docs-binding, remedied on `3b4d7d35`/`dd7812df` by stating the recovery rule once ("a re-run never repairs its inputs") pinned by `predecessor_drift` and `missing_latch_after_the_active_row`; r5 on `dd7812df` 4/4 AGREE (fable O1/O2/O8–O11 carried on ah#789); records: PR comments on ah#818 (r5 = 5607618847); this row is a recording-only commit on the board head |
