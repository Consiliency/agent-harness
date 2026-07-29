# Disposition note — FAB ah#288 P1 (`agent-harness#368`): PARKED at round 11

*Status: PARKED, carve decision escalated to the maintainer. This is a RECORD, not a fold.*
*Branch `plan/288-shared-epoch-allocator` @ `f5d171a` is the last round-10-folded state of the plan.*
*Author: opus-4.8[1m], 2026-07-29. Companions: PR `agent-harness#368` body, memory `fab-288-epoch-domain-conflict.md`, three board transcripts (rounds 9/10/11).*

## Why this note exists

The eleven-round convergence attempt on P1 terminated on a **three-round chain in which each fix
created the next defect, all on ONE identity change** (binding `base` into the broker's durable
publish key). The chain is not distributed across three transcripts by accident — no single
transcript states all three facts, and a successor who re-carves P1 from scratch needs them in one
place or will walk straight back into the same wall. That is what this note preserves.

| round | event |
|---|---|
| 9  | codex overturns `D-B3` → fold `base` into the durable publish identity (**AC-17**) |
| 10 | AC-17's key change (3-arg → 4-arg) orphans persisted append-only records → **dual-read** (AC-19) |
| 11 | the dual-read **defeats AC-17** for the migrated (legacy-keyed) history |

The maintainer's ratified decision (`ah#363`, Option B) is unchanged and is NOT what stalled: ALL
admission kinds including publish draw from one shared per-repo monotonic epoch allocator, and
"publish byte-neutrality" stays retracted. What stalled is the *evidence-key migration* that
binding `base` into the durable identity forces on append-only persistent storage.

## The three facts a successor needs

### 1. The `D-B3` reversal — and why "no caller varies it" was the wrong scoping test

Through round 8 the plan carried `D-B3`: the publish durable key was a 3-arg
`sha256(repo, branch, head)` and did NOT include `base`, justified by "no current call site varies
`base` for a fixed `(repo, branch, head)`, so base cannot disambiguate two publishes." Round 9
(codex) overturned it: **absence of a base-varying caller today is not a security property.** A PR's
base is coordinator-supplied and GitHub allows post-creation base retargeting; the identity that a
durable, replayable record commits to must bind every field an adversary or a future caller can
vary, not merely the fields some present caller happens to vary. The scoping test "does any caller
vary it" answers a *reachability* question; the identity question is "could two materially different
publishes collide under this key" — and they can. AC-17 folded `base` in (4-arg key).

**This is the recurring MIRROR error** (see memory `fab-288-epoch-domain-conflict.md`): "no current
DATA/CALLER exercises it" ≡ "the guard is unreachable so it doesn't matter." It was wrong for the
epoch enumeration and it was wrong here one round later.

### 2. The orphan hazard the key change creates on append-only storage

Evidence is stored append-only. `BrokerEvidenceStore` (`convergence/broker/evidence.py`) appends
JSON lines to `evidence.jsonl` under persistent `.train-ledger` storage; `replay()` rebuilds a dict
keyed by the record's stored `idempotency_key`, and `_append` only ever adds. There is no rewrite
path and — per the maintainer — no backfill tooling. So the moment AC-17 changes the key an existing
publish is recorded under from 3-arg to 4-arg, **every record written before the upgrade becomes
invisible to lookup.** A terminal or in-flight same-`(repo,branch,head)` publish that already
completed is no longer found; execution re-enters the mutation adapter, which pushes and
unconditionally attempts `gh pr create` (`credsep.py:281`), and a failed duplicate attempt becomes
permanent ambiguous evidence. A key change on append-only persistent storage **is a migration** —
round 10 treated it as an identity fix, which is the error the lead owned ("I treated it as an
identity fix"). AC-19's dual-read was the attempted remedy.

### 3. Why the dual-read CANNOT close it — there is no discriminator in the legacy records

AC-19 proposed a **dual-READ**: compute both the new 4-arg key and the legacy 3-arg key, look up
new-then-legacy, rewrite nothing (honoring "no backfill"). Round 11 (codex + grok, independently)
showed this **undoes AC-17 for exactly the records it is meant to rescue.** Two grounded facts:

- **`EvidenceRecord` carries no `base`.** Its fields are exactly `idempotency_key`, `state`,
  `evidence_reference` (`evidence.py`, verified). The whole identity is the opaque key string. A
  legacy record's key is the 3-arg digest, which has **no base component**, and the record has no
  `base` field to re-check. So a legacy terminal record created for base `main` is
  **indistinguishable** from one created for `release/2.0`.
- **The legacy-key fallback replays BEFORE the adapter's base verification.** Every base check
  (`_base_invalid`, the `origin/{base}...{head_sha}` diff) lives INSIDE `execute()`
  (`credsep.py:209+`, guards at ~:246/:248). The dedup/replay short-circuit decides whether
  `execute` runs at all — a replay "MAKES NO ADAPTER CALL AT ALL" (the code's own comment,
  `credsep.py:213-218`). A base-blind legacy match therefore short-circuits `execute` entirely and
  **replays a record whose base was never verified against the current request** — recreating the
  exact wrong-base publish replay AC-17 exists to forbid.

grok framed it structurally as a **fourth foreclosure surface**: a migration dual-read on a
*coarser* (base-free) key sitting in front of the *finer* (base-bound) AC-17 identity — the same
family as "evidence dedup in front of `admit_next`," one layer up.

**The reason no twelfth fold was attempted:** the next fix would have to discriminate legacy records
that carry no discriminator. That is not a plan-text problem. It is a statement that **the migration
cannot be made safe by reading alone** — closing it needs either a record REWRITE (a real backfill,
which the maintainer excluded) or a decision to accept a bounded re-drive window / fail-closed on
base-ambiguous legacy matches. That is a design decision above this plan, which is why it went to the
maintainer rather than into a round-12 fold.

## What a successor picking up P1 must decide FIRST

**The open question (this part is verified):** binding `base` into the durable, replayable publish
key forces a migration on append-only storage that **cannot be made safe by reading alone** (fact 3).
So P1 cannot proceed until the migration is resolved at the DESIGN level, above plan text.

**Starting points, NOT vetted paths.** The board never analyzed these; they are unexamined options,
recorded here only so a successor does not start from zero. Each carries an unresolved objection —
do not treat any as a solution:

1. **Backfill** — a one-time rewrite of `evidence.jsonl` to the 4-arg key. Reverses the maintainer's
   "no backfill"; needs re-ratification. *Open:* whether a rewrite of persistent terminal evidence is
   acceptable at all.
2. **Fail-closed on ambiguity** — on a legacy-key match whose base cannot be confirmed, do NOT
   replay; treat as `outcome_ambiguous_blocked` (or force a fresh base-verified `execute`). *Open:*
   converts every pre-upgrade in-flight publish into a manual-unblock event; blast radius unquantified.
3. **Relocate the base-binding** — bind base into the upstream APPROVAL DIGEST (the "stronger,
   separate step" credsep.py:226-228 names) rather than the replay key. *Open — and likely does NOT
   work as stated:* if the durable/dedup key stays 3-arg, two different-base publishes for the same
   `(repo,branch,head)` still collide and the second REPLAYS the first with no base check — the exact
   round-9 defect AC-17 was created to fix. Approval-digest binding defends against a coordinator
   *gaming* the base; it does not by itself make the replay key base-safe. Do not record this as
   "migration moot" — it is not.

**Where the eleven rounds still stand.** The shared-allocator and #199 publish-path core (the
`admit_next` allocator, the re-landed `readmit_advanced_head` primitive, the live publish draws) are
**largely** independent of this identity/migration knot and hold as-folded at `f5d171a`. But
"independent" is NOT clean: anything threading the 4-arg key moves with the identity decision —
**AC-12's seed** (retrofitted in round 10 to seed against the 4-arg key) and **AC-18**, at minimum.
Treat the AC-17/18/19 cluster PLUS AC-12's seed rule as the coupled set; re-audit §5e's propagation
rows against whatever identity decision lands before assuming any other AC is untouched.

## Anchors (verified 2026-07-29 on this branch)

- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/evidence.py` — `EvidenceRecord`
  (3 fields, no base); `replay()` keyed by stored `idempotency_key`; append-only `_append`.
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py:209-307` — base checks
  inside `execute()`; unconditional `gh pr create` at :281; replay-makes-no-adapter-call at :213-218;
  base-retarget guard at :300-307.
- Plan (last folded): `plans/detailed-fab-288-shared-epoch-allocator-20260728.md` @ `f5d171a`
  (AC-17/18/19 in §5, §12 scope block, §8a round-10 addendum).
- Cross-refs: P2 = `agent-harness#373` (parked with P1); `#376` AC-4 stays gated on P1; `#376` core
  is independent and moving on its own branch (`plan/376-post-commit-resume-seam`).
