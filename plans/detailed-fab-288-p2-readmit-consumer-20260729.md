# Detailed migration plan: FAB ah#288 — P2 of 2: readmit CONSUMER wiring + engage-flag flip

> **⚠️ PRECONDITION — P1 MUST BE MERGED TO `main` FIRST. Do not begin this plan until it is.**
> This is the second of a two-plan split (maintainer-ratified, `Consiliency/agent-harness#363`
> follow-up). **P1** — *"one shared monotonic epoch allocator across all admission kinds"*
> (`plans/detailed-fab-288-shared-epoch-allocator-20260728.md`, `Consiliency/agent-harness#368`)
> — re-lands the shared allocator (`admit_next`), the `readmit_advanced_head` /
> `readmit_attempt_id` / `ReadmitResult` primitive, and migrates the live #199 **publish** path
> onto the allocator. **This plan (P2) wires the readmit CONSUMER (`_fab_delta_readmit`) to that
> already-landed primitive and flips the engage flag.** It has ZERO value — and is actively
> unsafe — until P1 is on `main`: the flag flip requires publish to already be on the allocator
> (§Ordering, mode (b) — the mixed-allocation brick that killed #337 round 4), and P1 is what
> puts it there. The dependency is enforced by **git — a merge boundary** — not by an in-document
> ordering promise. This matters because this plan family has already demonstrated (P1 round 3)
> that a ratified decision can fail to reach the section an implementer follows; "P2 cannot start
> until P1 is on `main`" cannot fail that way.

---

## 0. Why this is a separate plan (the split, in one paragraph)

The original combined plan's §11 DAG placed the readmit-consumer wiring (step 4) and the
engage-flag flip (step 5) AFTER, and dependent on, the allocator + publish migration (steps
1–3). The density in that plan is concentrated — and entangled — in the publish half:
publish's IDENTITY under a commit that moves `HEAD` mid-operation (epoch late-binding, the
deterministic post-commit `attempt_id`, and commit-stable `approval_digest`). **The
readmit-consumer half does NOT share that entanglement.** `readmit_advanced_head` takes
`approval` as a **caller-supplied** parameter (`c1da62a` `verbs.py:87`) and keys on an
already-advanced, stable `new_head_sha`; it never re-derives `base_sha` from a drifting
`rev-parse HEAD`. So the consumer wiring is comparatively self-contained (one finding cluster:
the two commit points, plus the path-entered hardening). Splitting along the §11 merge boundary
lets the §5b identity sub-design (P1) get focused treatment without gating this simpler, ready
consumer work — and makes the mixed-allocation interlock **safer**, because publish is already
migrated on `main` before P2 begins.

---

## 1. The ratified decision (context — the full statement lives in P1 §1)

Ratified (maintainer, `ah#363`, Option B, 2026-07-28): ALL admission kinds — **including
publish** — draw from ONE shared, per-repo, monotonic epoch allocator (`admit_next`,
allocated in-lock). Publish stops stamping `lease_epoch=1`; its durable broker record shape
changes; **publish byte-neutrality is RETRACTED.** P1 realizes this for publish. What P2 adds:
the readmit **consumer** — today `_fab_delta_readmit` appends to the ledger DIRECTLY, bypassing
the broker entirely, so a revoked node can still delta-re-admit and merge. That bypass is the
seam #288 exists to fix, and it is what this plan closes.

---

## 2. Scope guard — the two-namespace distinction (READ BEFORE TOUCHING ANY `epoch`)

Exactly as in P1 §2 (restated so this plan reviews standalone): three unrelated things are
called `epoch` in this tree. This plan touches **only the first**:

- **Broker `AdmissionRecord.epoch`** — allocated by `admit_next`, sole consumer the fence at
  `admission.py:49`. The readmit consumer must route through it. **This is the one P2 changes.**
- **FAB review-round epoch** (`test_fab_*.py`, `SeatOutcomeRecord.epoch`, `panel_invoker.py:540`)
  — OUT of scope. A sweep that renumbers `epoch=1` in `tests/test_fab_*.py` is the WRONG sweep.
- **Runtime event-log epoch** (`event_log.py` `CoordinatorEvent.epoch`) — OUT of scope.

---

## 3. The seam this plan fixes — S8, the readmit CONSUMER

**S8 — `train_runner.py:892`, `_fab_delta_readmit` (THE readmit CONSUMER — the seam #288
exists to fix; "guard correct, never wired" applied to the readmit half).**
Today (verified on `main` @ `b581fcd`): `_fab_delta_readmit` takes `ledger_path`, **NOT a
`broker_client`**, and the call site (`train_runner.py:3084`) passes no broker. So the
delta re-admit **bypasses broker lease/epoch/revocation entirely** — a node whose lease
was revoked mid-run can still delta-re-admit and merge.

**⚠️ There are TWO re-admission COMMIT POINTs in this one function, not one** (P1 round-1 CR,
codex — verified):
- **`train_runner.py:1016`** — the idempotent CRASH-RESUME early append (comment: "a prior
  attempt already extended the chain to the live head AND it passes the gate — only the
  ledger append was pending"). Fires when `resolved_final == live_head_sha and _gate_passes()`.
- **`train_runner.py:1139`** — the NORMAL path append ("7. COMMIT POINT"), after
  capture+build+re-gate.

Both build the **identical** `LedgerRecord(status="pr_open", head_sha=live_head_sha,
fab_run_id=run_id, …)` and both `append_record(..., durable=True)` directly. A rewrite
that only touches `:1139` (the seam a reader lands on) leaves `:1016` as a live bypass: a
crash that leaves gate-passing extended provenance lets a **revoked resume take the early
`:1016` append and merge with no broker admission** — the exact #288 defect, on the path
nobody reads. This is the dominant failure class in this line of work (guard added at one
seam; a second seam completes the same operation unguarded).

**Change — ONE shared broker-gated commit path covering BOTH appends:** introduce a single
inner `_commit_readmission(*, broker_client, ledger_path, node_id, branch, pr_url,
merge_order, run_id, new_head_sha) -> str | None` that (a) fails CLOSED and returns `None`
when `broker_client is None` (NO direct-append fallback — caller falls through to the
unchanged `pr-head-advanced` guard); (b) otherwise calls `broker_client.readmit_advanced_head(...)`,
which allocates via `admit_next` and fail-closes on `epoch_blocked`; (c) `append_record(...,
durable=True)` the ledger record ONLY on an accepted `ReadmitResult`, then returns
`new_head_sha`. **BOTH `:1016` and `:1139` call this one function instead of their inline
`append_record`.** Two call sites converging on one admission-gated function — not two
parallel rewrites that can drift. **Normative: any future site that advances the admitted head
MUST route through `_commit_readmission`; a new direct `append_record` of an advanced head is a
defect.**

- **Commit-ordering / crash-consistency (state it so the shifted COMMIT POINT is not misread
  as a regression):** the broker admission becomes the authority; the ledger append is
  downstream of an accepted `ReadmitResult`. A crash BETWEEN the broker admit and the ledger
  append still fails CLOSED — the ledger stays at the OLD admitted head, so `_live_merge_pr`
  pins `--match-head-commit` to it and the guard fires; on resume the `:1016` branch re-enters
  `_commit_readmission`, and `admit_next` **dedups on the deterministic
  `readmit_attempt_id(node_id, new_head_sha)`** → same epoch if not revoked (idempotent, ledger
  append completes), refused if revoked (P1 §6 two-layer / AC-6b).
- **Threading (the load-bearing plumbing #288's body calls "multi-day protocol integration"):**
  `broker_client` must reach `_fab_delta_readmit` through the PRODUCTION path
  `run_train → merge loop (`:3084`) → _fab_delta_readmit → _commit_readmission`. The
  `CoordinatorRuntime` already carries `broker_client` (`train_runner.py:100`); it must be added
  to the `:3084` call and to `_fab_delta_readmit`'s signature. **P1 re-landing the
  `readmit_advanced_head` primitive makes it EXIST; it does NOT make S8 CALL it — the test that
  proves the wiring is a seam-level test (AC-8a/8b, §5), NOT a direct helper call.**

**Enumeration method (so a reviewer can check COMPLETENESS, not just the result) — repo-wide,
re-checkable:**
1. `grep -rn "append_record(" phase-loop-runtime/src/` → **21 call sites in 3 files**
   (`train_ledger.py`, `train_runner.py`, `advisor_board/observability.py`). The durable ledger
   `append_record` is the SOLE commit surface that admits/advances a node's admitted head — the
   merge pins `--match-head-commit` to the ledger's admitted head, so a head-advancing
   re-admission MUST write a ledger record carrying the new head.
2. Discriminant for a HEAD-ADVANCING re-admission commit: the appended `LedgerRecord` sets
   `head_sha=live_head_sha` (the advanced head). `grep -rn "head_sha=live_head_sha"
   phase-loop-runtime/src/` — then EXCLUDE the read-side `final_pr_head_sha=live_head_sha` /
   `live_head_sha=` params in `fab_gate.py` and `fab_canonical.py` (gate-compose inputs, not
   ledger writes). **Result: exactly `train_runner.py:1020` and `:1143` — i.e. the `:1016` and
   `:1139` appends, both inside `_fab_delta_readmit`.** The `observability.py` and
   `train_ledger.py` appends are non-head-advancing (metrics / the `append_record` def).
3. Completeness is re-checkable by re-running both greps: any NEW head-advancing append surfaces
   as a third `head_sha=<advanced head>` hit and MUST route through `_commit_readmission`.

**RE-VERIFY these anchors against P1-merged `main` before implementing.** P1 migrates publish
and re-lands the primitive; line numbers in `train_runner.py` (`:892`, `:1016`, `:1139`,
`:3084`, `:100`) may shift. Re-run the two greps above on P1-merged `main` and rebind by the
`head_sha=<advanced head>` discriminant, not by literal line number.

---

## 4. Reader-audit note (carried from P1 §7)

P2 does not add a new `AdmissionRecord.epoch` reader — the fence at `admission.py:49` remains
the sole consumer. P1's RA-1 (verify a publish `lease_epoch` does not flow into a
`CoordinatorEvent(epoch=…)` monotonic check) is a PUBLISH-path audit owned by P1; readmit's
`readmit_advanced_head` allocates the same broker epoch and rides the same fence, and does not
emit a publish event. No new reader audit is required here.

---

## 5. Acceptance criteria — AC-8a / AC-8b (each names its FALSIFIER, injection anchor, positive control)

> A criterion that cannot fire is the defect class this repo keeps shipping. Both ACs below name
> the exact mutation that breaks them AND assert a positive control so they are not vacuously
> green — and (P1 round-4 grok B1) each asserts its PATH WAS ENTERED, not merely that the bad
> outcome is absent.

> **AC-8 is split into AC-8a (normal path) and AC-8b (crash-resume path) — the two S8 commit
> points. BOTH bind to the PRODUCTION SEAM, not to a direct helper call.** Driving
> `_fab_delta_readmit(broker_client=<fake>, …)` directly would test the helper in isolation and
> CANNOT catch the actual #288 defect — `broker_client` never threaded through the `:3084`
> production path (the "guard correct, never wired, suite green" class). It also breaks the §6
> contract: a test naming the new `broker_client` param dies on `main` with a `TypeError`
> (rule-2 wrong-reason red) and must be edited by the impl PR (rule-5 violation). So each test
> sets up a revoked per-repo broker store and drives the merge-loop seam (`run_train` / the
> `:3084` caller — at minimum `_live_merge_pr`); it NEVER hands `broker_client` to the helper.
> The wiring supplies it, so an unwired path stays red.

- **AC-8a — the NORMAL-path delta re-admit is subject to revocation.** Drive the merge-loop
  seam with a valid single-commit PASS delta (so `:1139` is the append reached) against a
  revoked per-repo broker store (`evidence_store.epoch_blocked = True`): the node does NOT
  re-admit — no new admitted head, no `:1139` ledger append, the merge falls through to the
  `pr-head-advanced` guard (no merge). **Falsifier:** restore the direct `append_record` at
  `train_runner.py:1139` (the current bypass) → the seam re-admits and the advanced head merges
  despite revocation. **Injection anchor:** the `:1139` append rewrite + `broker_client`
  threading at the `:3084` call. **Wave-0 red on P1-merged `main` — get the POLARITY right
  (P1 round-4 grok B1 + self-review).** The PRIMARY assertion is the DESIRED behavior under
  revocation: `assert result["status"] != "merged"` (and NO `:1139` ledger record for the
  advanced head). RED on P1-merged `main` — P1 does NOT touch the consumer, so the bypass still
  appends at `:1139` ignoring the revoked store, so `main` merges and this assertion FAILS — and
  GREEN after the P2 fix. **Do NOT assert `status == "merged"`: that is GREEN on `main` (the bug
  merges) and RED after the fix — the INVERSE of red-first, and it leaves no passing regression
  guard (§6 rule-5). Asserting a POSITIVE observable (grok B1) does NOT mean asserting the bug
  outcome.** Grok's non-vacuity is satisfied by a companion **reachability control that runs AT
  WAVE-0** (not POST-IMPL): the SAME delta against a NON-revoked store (`epoch_blocked = False`)
  asserts the merge/append DOES happen — `status == "merged"`, the `:1139` record written. That
  control is GREEN on P1-merged `main` (the bypass merges regardless of revocation) AND GREEN
  post-fix (re-admits at an allocated epoch), so it proves the seam is REACHED in both worlds;
  if it ever fails, the delta never reached `:1139` and the revoked assertion's greenness is
  suspect — the exact vacuity grok named. The pair — red-first "not merged under revocation" +
  wave-0 "merged when NOT revoked" — is the "pair a negative with a positive control" rule,
  non-vacuous by construction. **Green-time (POST-IMPL):** the non-revoked control keeps passing
  (re-admits at an allocated epoch), now proving the fix PRESERVED reachability rather than
  killing the path.

- **AC-8b — the CRASH-RESUME delta re-admit is subject to revocation (the second bypass codex
  found).** Pre-extend the durable provenance to the live head so it passes the gate
  (`resolved_final == live_head_sha and _gate_passes()` → the `:1016` crash-resume branch
  fires), then drive the SAME merge-loop seam against a revoked store: the node does NOT re-admit
  — no `:1016` ledger append, falls through to the guard. **Falsifier:** restore the direct
  `append_record` at `train_runner.py:1016` (the crash-resume bypass) → a revoked resume takes
  the early append and merges. **Injection anchor:** the `:1016` append specifically (assert
  `head_sha=live_head_sha` at that append in `src` before mutating, so the mutation cannot be a
  silent no-op against a moved anchor). **Wave-0 red on P1-merged `main` — POLARITY (P1 round-4
  grok B1 + self-review).** PRIMARY assertion = desired behavior: `assert result["status"] !=
  "merged"` and NO `:1016` ledger record. RED on P1-merged `main` (P1 leaves the consumer
  untouched, so the crash-resume bypass still appends at `:1016` ignoring revocation → `main`
  merges → fails), GREEN after the P2 fix. **Do NOT assert `status == "merged"` (green-on-main,
  red-after-fix — inverted, no regression guard).** **Reachability control AT WAVE-0:** the SAME
  pre-extended-provenance scenario against a NON-revoked store must route to `:1016` and
  merge/advance (`status == "merged"`, the `:1016` record written) — GREEN on `main` and
  post-fix. This is what proves the `:1016` crash-resume BRANCH was actually entered (the gate
  `resolved_final == live_head_sha and _gate_passes()` satisfied); if it fails, the provenance
  never routed to `:1016` and the revoked assertion is vacuous — the seed-precondition
  discipline of P1's AC-12 applied to a code branch. **Green-time (POST-IMPL):** with
  `epoch_blocked = False` the crash-resume DEDUPS to the SAME `granted_epoch` (idempotent resume,
  per P1 §6/AC-6b) and the head advances — proving the fix refuses only under revocation, not
  that the crash-resume path is dead.

### Falsifier re-audit — does each mutation actually reach an assertion, and via WHAT observable?

| AC | Falsifier observable | Fires? | Note |
|----|----------------------|--------|------|
| AC-8a / AC-8b | primary: `status != "merged"` under a revoked store (RED on P1-merged `main`, which merges via the persistent bypass); paired with a wave-0 non-revoked control asserting `status == "merged"` | ✅ (wave-0 red) | production-seam bound; polarity is red-first (P1 round-4 — NOT `status=="merged"`, which is green-on-main); the non-revoked control proves the seam was reached (grok B1 non-vacuity) |

### Path-entered re-audit — if the scenario silently never reaches the seam, does the assertion still pass? (P1 round-4, per grok B1 "sweep ALL")

| AC | Assertion polarity | Path-entered control |
|----|--------------------|----------------------|
| AC-8a | negative (not merged under revocation) | positive control: SAME delta, NON-revoked store → `status == "merged"` + `:1139` record written (proves the `:1139` append path was reached in both worlds) |
| AC-8b | negative (not merged under revocation) | positive control: SAME pre-extended provenance, NON-revoked store → routes to `:1016`, `status == "merged"` + `:1016` record (proves the crash-resume BRANCH was entered) |

---

## 6. Test-first execution contract — NORMATIVE, not advisory (per-plan waves)

Identical contract to P1 §10 (reproduced so P2 reviews standalone), applied to P2's own waves.
Its acceptance criteria (§5) LAND AS FAILING TESTS BEFORE any production change here.

**No harness gate enforces this.** The falsifier-gate that would (`Consiliency/agent-harness#362`)
is not built. This is a PLAN-LEVEL commitment enforced by the reviewer.

**The contract (each rule is a review gate):**
1. **Tests land FIRST, in their own PR**, before any production change — test files plus minimal
   import scaffolding only.
2. **Every test FAILS when it lands, for its named reason** (the asserted behavior is wrong, NOT
   an import error / typo / missing fixture). A test that passes on arrival proves nothing.
3. **Each falsifier from §5 is RUN, with its injection anchor asserted** — the mutation is applied,
   `assert <anchor> in <source>` confirms the anchor matched, the test dies, source restored.
4. **The test PR is REVIEWED BY THE PANEL BEFORE implementation begins** ("are these the right
   tests," decided while argument is cheap).
5. **The implementation PR MUST NOT modify the landed tests** — any such diff is a BLOCKING review
   item.
6. **`pytest -k <new tests>` goes red→green across exactly TWO commits** (test commit red, impl
   commit green).
7. **A REGRESSION GUARD (green-on-arrival, proving EXISTING behavior stays fixed) is rule-2 exempt
   BY LABEL, never by silence.** (Not used by P2's ACs — both AC-8a/8b are genuinely red-first.)

**Applied to P2's waves — CRITICAL: the baseline is P1-merged `main`, NOT today's `main`.**

- **AC-8a + AC-8b are P2's WAVE-0, red against P1-MERGED `main`.** This is the load-bearing
  refinement of the split (team-lead directive): P1 migrates publish and re-lands the
  `readmit_advanced_head` primitive, but **P1 does NOT touch the readmit CONSUMER** —
  `_fab_delta_readmit` still appends directly at `:1016` and `:1139` on P1-merged `main`. So the
  #288 bypass these tests target **still exists at the moment P2's wave-0 lands**, and both tests
  are RED on P1-merged `main` for their named reason (the direct append merges despite revocation).
  The falsifier IS the status quo on P1-merged `main` — zero P2 behavior scaffolding required. The
  green transition is P2's own consumer-wiring commit. The positive/reachability controls
  (non-revoked advances; 8b dedups to the same epoch) are POST-IMPL green-time, not wave-0 red.
  **Do NOT write these tests against today's `main`:** the primitive they interact with post-fix
  (`readmit_advanced_head`) does not exist until P1 lands, and the merge-loop seam fixtures must
  match P1-migrated `train_runner.py`. Author them on a branch cut from P1-merged `main`.
- **Step-5 (flag flip) carries no new red-first AC** — it is a one-line gated flip whose safety is
  the §7 interlock (both predecessors satisfied by merge boundaries). Its "test" is that AC-8a/8b
  (consumer wired) AND P1's AC-1 (publish migrated) are green on `main` before the flip lands.

---

## 7. Ordering and the merge-boundary interlock

P2 owns steps (4) and (5) of the original combined §11 DAG. Steps (1)(2)(3) — the allocator, the
publish migration, the docs retraction — are P1 and are on `main` before P2 begins.

4. **Wire the readmit CONSUMER (S8)** — replace BOTH direct `append_record` sites (`:1016`
   crash-resume + `:1139` normal) with the single `_commit_readmission → readmit_advanced_head`
   path, and thread `broker_client` through `run_train → merge loop (`:3084`) → _fab_delta_readmit`.
   Depends on P1 (the primitive) being on `main`. This is the "multi-day protocol integration" of
   #288 and the actual gap the flag guards. **AC-8a AND AC-8b gate it** (one per commit point).
5. **Flip `_FAB_DELTA_BROKER_READMIT_READY = True`** in `governed_premerge.py:76` — LAST, as its
   own gated step per the #288 landing-checklist interlock. **Depends on BOTH (4) consumer wiring
   AND P1's publish migration.** Two failure modes it must not activate:
   - **(a)** flipping while `_fab_delta_readmit` still appends directly ACTIVATES the exact bypass
     #288 exists to fix → needs (4), IN THIS PLAN.
   - **(b)** flipping while publish is still on `admit(lease_epoch=1)` creates MIXED ALLOCATION —
     the first delta readmit allocates epoch 2 into the shared per-repo store via `admit_next`,
     then the next live #199 publish still presents epoch 1 and the fence at `admission.py:49`
     raises `PermissionError("stale epoch")` (`1 < 2`), BRICKING every multi-node train after the
     first readmit → needs P1's publish migration. **This is the identical mixed-allocation hazard
     that killed #337 round 4.**

**The interlock is now enforced by GIT, not by an in-document promise (the strongest argument for
the split).** Mode (b)'s predecessor — publish migrated — is satisfied because **P1 is merged to
`main` before P2 starts**; the `(5)→(publish-migration)` edge is a MERGE BOUNDARY, not an
in-plan ordering note that a reader could miss. Mode (a)'s predecessor — consumer wired — is
step (4) IN THIS PLAN, sequenced before the flip. An earlier combined-plan draft over-corrected
"the flag must not depend only on the primitive" into "depends on (4) NOT (2)," which was exactly
bug (b); the split removes that footgun by construction, because publish is provably on `main`.
Until this flip, the delta-shortcut ENGAGE path is fenced OFF and the gap is unreachable.

---

## 8. Scope statement + what is explicitly NOT in scope

**In scope:** the readmit CONSUMER wiring (step 4, S8/AC-8a/AC-8b — BOTH commit points
`:1016`+`:1139` via one gated `_commit_readmission` path) and the gated flag flip (step 5). This
is the seam #288 exists to fix and the "multi-day protocol integration" its body describes —
specified here at the seam/falsifier level, implemented by the execution PR.

**Explicitly NOT in scope (owned by P1, must be on `main` first):**
- The shared allocator (`admit_next`), the `readmit_advanced_head` primitive, publish migration,
  §5b commit-stable approval identity, the CHANGELOG retraction — all P1.
- **No data migration** (maintainer confirmed no durable broker state exists — `ah#363`).
- **No new allocator or fence changes** — P2 consumes the P1 allocator unchanged.
- **No touching the FAB review-round epoch or the event-log epoch** (§2).

---

## Governed close-out

- **Plan path:** written to `plans/` (matches this repo's manifest entries and the runtime
  `MANIFEST_PATH`).
- **Acceptance criteria count:** 2 (AC-8a, AC-8b).
- **Manifest registration:** registered on this branch via `phase_loop_runtime.plan_manifest.append_entry`
  (typed `DotfilesPlanEntry`, slug `fab-288-p2-readmit-consumer`) — **re-run against P1-merged
  `main` before this PR merges** (P2 cannot merge until P1 is on `main`; re-run reconciles the
  manifest with P1's own entry and any other intervening plans; do not hand-edit).
- **Precondition:** P1 (`agent-harness#368`) MERGED. Enforced as a merge boundary, stated in the
  first paragraph.
