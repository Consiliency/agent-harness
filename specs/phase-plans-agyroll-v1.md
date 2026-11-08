# Phase roadmap AGYROLL v1: agy admission without qualification lag

> # ADVISORY — not runner-selected (2026-11-08)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md`
> remains the sole active runner-selected roadmap. This status grants no live run,
> no `ai` access and no ruling authority; the owner rulings below are requests.

## Context

agy (google-antigravity/antigravity-cli) ships stable releases almost daily: 84 so far,
1.4.9 to 1.5.3 between 2026-10-28 and 2026-11-07. Admission still lags by weeks. The
shipped catalog holds only 1.3.5, and 18 stable releases are newer. Executor launches are
catalog-only, and the canary is hard-pinned to agy `1.1.13`. Review seats can self-qualify,
but only for the newest four releases, and the agent-harness#1420 upgrade drop recurred on
2026-11-04. This roadmap replaces the per-release hand step for good. It covers
agent-harness#1008 and the related issues agent-harness#1158, agent-harness#1407, agent-harness#1420 and agent-harness#1520.

What already exists, and why it does not cover the lag. The evidence for each point is in
the AGYROLL contract (External Inputs).

- **First-use self-qualification** (agent-harness#1076). `agy_qualification.ensure_admitted`
  checks provenance, measures help from a sealed memfd, runs three live operations and writes
  HMAC store entries. It runs only from the board preflight, through `requalify_once`. Spawn
  is lookup-only. Seats reach it through `agy_integrity.admit_for_seat`.
- **Executor and canary sit outside it.** `agy_integrity.check(path)` is called with no env
  from `trusted_command`, `admitted_command` and the canary, so they admit only
  `gemini_heartbeat.QUALIFIED_IMAGES`. The agent-harness#1333 plan scoped executors out ("not
  seats … keep release-only admission"), and the president's ruling on agent-harness#1350
  confirmed it. No threat was named. Separately, the canary's `probe_capability` requires
  `agy --version == "1.1.13"`.
- **The newest-four window is a download-cost bound, not a provenance control.** It comes
  from ruling D4 (`plans/detailed-agy-selfqual-1076-20260927.md`). A reverse lookup from
  image digest to release must download each archive. With daily releases, a host that has
  not upgraded agy within about four days can never re-qualify after its store entries drop.
- **Upgrade drop.** From ruling D2, the store key held `__version__` plus the route-core
  digests. IF-0-TEAMHOST-4 (agent-harness#1873, shipped in 0.7.29) re-keyed it on
  `agy_profile_digest` (maintainer Q8). What still drops is the release side: each record
  pins all 285 package sources (agent-harness#1032 ruling), and the catalog literal sits in a
  route-core file. Every harness release, and every member addition, therefore requalifies
  every member. agent-harness#1901 cut the catalog from 12 members to 1, and
  agent-harness#1923 is blocked on 11 drifted non-route-core files.
- **The fix was ruled but never built.**
  - The upstream watch (`agy_watch`) can qualify a release and open a PR, but "nothing in
    this repository installs the timer". It has never opened a PR.
  - Maintainer Q10 (signed records, automated promotion) and Q11 (a release cut re-runs only
    the newest member), both 2026-10-14, sit in agent-harness#1602 L6, which was never
    started.
  - The nightly upstream check was reduced to a warning in agent-harness#1333 PR1, so the lag never
    turned anything red.
- **Upstream publishes no signature and no attestation.** The attestations API returns 404,
  and the repository has no workflows. Provenance therefore rests on GitHub's per-asset
  digest, fetched over the pinned transport.

Thesis: admit an image by evidence, keyed on what the evidence actually depends on. That
evidence is genuine upstream bytes, a qualification under the route's contract identity
(QCI), and a named custody tier. A recurring, observable job keeps the shipped catalog
current within a red-on-breach lag bound.

## Architecture North Star

```
 GitHub release (tag, per-asset digest, attestation?) --pinned transport--> forward provenance
                                                             (any stable release; budget, not window)
                                                                            |
 seat QCI = agy_profile_digest + validator literal  <--- conformance suite (CI, hermetic)
                                                                            |
        custody:  shipped catalog (package data)  |  host_root (TEAMHOST)  |  host_user store
                         ^                                                  |
   ai: agy-qualification watch (timer) -- signed v2 record, one member/tick -+--> ready PR -> CI -> main
                                                                            |
        admit_for_seat        admit_for_executor          admit_for_canary
        (board preflight)     (runner-start preflight)    (capture-start preflight)
```

## Assumptions

1. agent-harness#1923 (v0.7.30, a hand bump to agy 1.5.3) lands, or is abandoned, before
   RECBIND's implementation starts. Under this roadmap it is the last hand-made bump. If
   RECBIND lands after the 0.7.31 cut, that cut still needs one hand run.
2. The v1 record of every member at RECBIND's base was produced by that base tree, so
   `source_sha256` equals the tree's sources. If this is false, migration needs one live
   run, and RECBIND routes a roadmap amendment.
3. The production qualification driver can run hermetically in CI against a scripted
   stand-in image under the bubblewrap and user-namespace setup that `publish-pypi.yml`
   already provisions. If this is false, RECBIND stops and amends.
4. `ai` stays the qualifying host (subscription, review-seat host), and the job runs there
   under an owner-approved identity (R9).

## External Inputs

| Input | Pin |
| --- | --- |
| AGYROLL contract | `plans/artifacts/agyroll-v1-contract.md`, sha256 `8640374dcf30beb8a7a544c867b25e242152cf1a37fe7debf82b69ef15f5ee72` |
| TEAMHOST contract §5 (agy key) and §7 (root updater) | `plans/seats-teamhost-contract.md`, sha256 `3ca3d3a57346acca8bf4e16e50304f00e3e2e19bc5bcd20b1831b4f837c3b1b1` |
| Upstream provenance surface | GitHub releases API for `google-antigravity/antigravity-cli`: per-asset `digest`; attestations endpoint (404 as of 2026-11-08) |

These are immutable planning inputs. A changed input needs a reviewed repin. No plan pins a
future implementation commit, commit count or landing topology.

## Owner Rulings Needed

- **R1.** The release gate binds records to the QCI plus the hermetic route conformance
  suite instead of all source pins. *Recommend:* yes.
  - **Rulings revisited:** the agent-harness#1032 maintainer ruling and its president line
    ("No publish path ships a tree whose full pin set differs…"), agent-harness#1119 "kept
    at full strength", and Q11.
  - **If no:** the job automates the per-cut live run (AGYROLL §6.4), and every PROVFWD and
    REQUAL route-core edit needs a job re-record. Amend.
- **R2.** The executor may admit a `host_user` locally qualified image after a provenance
  re-check. *Recommend:* yes.
  - **Ruling revisited:** the agent-harness#1333 scope, confirmed on agent-harness#1350.
  - **Why it is safe:** the evidence is the same as the catalog's, which is seat-route only.
    A same-euid writer already holds the user's privileges, and seats already accept that
    trust boundary.
- **R3.** The canary admits an image by `admit_for_canary` plus a complete capability
  matrix, replacing the `1.1.13` literal. *Recommend:* yes.
- **R4.** Drop `RECENCY_WINDOW` (D4) as an admission criterion and keep a download budget
  instead. *Recommend:* yes, with no freshness refusal.
- **R5.** Record attestation status now, and verify attestations only once upstream
  publishes them. *Recommend:* add the installer-manifest second channel for the job only,
  not for per-host first use.
- **R6.** The merge rule. Q10 asks for at least 2 distinct signers, which one host cannot
  meet. *Recommend:*
  - one host signature plus green CI (publisher digest, contract, conformance) auto-merges a
    new member whose QCI matches;
  - a QCI change also needs one owner approval.
- **R7.** Gemini login custody for the job on `ai`. Today only the owner renews it, and that
  rule is unwritten (agent-harness#1923, agent-harness#1924). *Recommend:* the job renews outside any
  seat through the existing wait-and-renew path. The refresh token never enters a seat
  (agent-harness#1222). On expiry the lag rule goes red.
- **R8.** Keep the newest 3 catalog members per route and prune older ones automatically.
  This replaces the Q5/Q11 member-requalification wording. *Recommend:* yes.
- **R9.** The job's GitHub identity on `ai`: a fine-grained token for this repository only,
  with contents and pull-requests write, while rulesets protect `main` and release branches
  (agent-harness#1138). *Recommend:* approve.

## External Readiness Gates

- **EXT-0730.** agent-harness#1923 has merged or been abandoned, and agent-harness#1924 is
  closed. This gates RECBIND implementation, not planning.
- **EXT-R.** Each phase starts implementation only after its listed rulings are recorded on
  agent-harness#1008. A ruling of "no" routes a roadmap amendment before that phase is
  planned.

## Non-Goals

- Executor-specific qualification operations.
- Platforms other than linux-x64 glibc.
- Fetching a catalog at runtime from outside the installed package.
- Seat-jail, egress or `SEALED_FALLBACK_CODES` changes.
- `cli_qualification` adapters for other harnesses (agent-harness#1333 PR3–PR7,
  agent-harness#1602 L1–L5).
- Any live run or `ai` access before ACTIVATE.

## Cross-Cutting Principles

- **Fail closed everywhere.** A missing or malformed catalog, an unknown attestation response,
  an unverifiable signature or an unreachable channel refuses typed (AGYROLL §8). A
  refusal is never silent and never reaches a sealed fallback.
- **Every admission names its evidence.** Each admission names its provenance, its QCI and
  its custody tier. No consumer trusts a tier the contract does not list for it.
- **Lookup-only at spawn.** Qualification runs only in preflights and in `agy-qualification
  run`/`watch`.
- **Measured, not literal.** No version literal gates admission. Versions appear only as
  untrusted hints and as reporting fields.
- **Shared-host test limits.** Use targeted pytest with `-n 0` (at most `-n 2`) under
  `timeout`. Full suites and live runs go to CI, Gate A or ACTIVATE.

## Top Interface-Freeze Gates

- IF-0-RECBIND-1 — Seat QCI with the validator literal, the package-data catalog
  `qualified_agy_catalog.v3`, record v2 and verifier modes `--contract`/`--release`
  (AGYROLL §2, §3).
- IF-0-PROVFWD-1 — `find_provenance(hint, budget)` forward resolution, the
  `budget_exhausted` reason, and the provenance entry's `attestation` and `second_channel`
  fields (AGYROLL §1).
- IF-0-REQUAL-1 — The `agy-qualification preflight` CLI, the runner and board preflight
  hooks, the `MODE_DEGRADED` refusal surface and the failed-entry classes (AGYROLL §5).
- IF-0-EXECADMIT-1 — `admit_for_executor` and `admit_for_canary` with custody tiers
  (AGYROLL §4).
- IF-0-ROLLJOB-1 — The watch tick contract, signed records, the lag rule and the merge rule
  (AGYROLL §6).

## Phases

### Phase 1 — Record binding and catalog decoupling (RECBIND)

**Objective**

Bind catalog evidence to the seat QCI instead of to file hashes, and move the catalog out of
the route core. After this phase, neither a harness release nor a member addition invalidates
existing records, so later phases land without hand live runs (goal d).

**Exit criteria**

- [ ] EC-RECBIND-1 — `gemini_heartbeat.QUALIFIED_IMAGES` is loaded from `phase_loop_runtime/data/agy_catalog.json` (AGYROLL §3.1); a missing or malformed file yields an empty catalog and the release fast path admits nothing.
- [ ] EC-RECBIND-2 — The seat QCI includes the validator literal (AGYROLL §2.1); a `__version__` bump or a catalog edit leaves it unchanged, and a validator mutant without a literal bump is red.
- [ ] EC-RECBIND-3 — Every member has a v2 record whose `qci` equals the tree's; `verify_qualified_agy_image.py --contract` fails naming the member when they differ.
- [ ] EC-RECBIND-4 — The route conformance suite (AGYROLL §3.4) passes on the production driver, and each negative-control mutant fails its operation.
- [ ] EC-RECBIND-5 — `publish-pypi.yml` gates on `--release`; a tree that differs from the records only outside the QCI passes with no live run, and a QCI change fails.
- [ ] EC-RECBIND-6 — v1 records convert without a live run (AGYROLL §3.5): the converter proves the base tree produced each record, and a test proves `agy_profile_digest()` and the validator sources are unchanged from base to head.

**Scope notes**

Decompose into 4 lanes plus docs:
- **Runtime:** QCI and the catalog loader.
- **Verifier:** record v2, the converter, the verifier, and the record and catalog writers in
  `agy_watch.py`.
- **Conformance suite:** tests and fixtures only.
- **Workflows.**

The lanes own disjoint files. Single-writer: `gemini_heartbeat.py` (runtime lane). Gated on
R1 and EXT-0730.

**Non-goals**

Provenance changes, the executor, the canary and the job.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json`
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py`
- `phase-loop-runtime/scripts/convert_agy_record_v2.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`
- `phase-loop-runtime/tests/test_agy_route_conformance.py`
- `.github/workflows/qualified-agy-image.yml`
- `.github/workflows/publish-pypi.yml`
- `plans/evidence/qualified-provider-images.json`

**Depends on**

- (none)

**Produces**

- IF-0-RECBIND-1 — Seat QCI, catalog v3, record v2 and verifier modes (AGYROLL §2, §3).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md` (qualified images), `docs/releases/outside-agent-release-handoff.md`;
evidence paths: `plans/evidence/agy-*-linux-x64-qualification.json`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 2 — Forward provenance for any stable release (PROVFWD)

**Objective**

Any stable upstream release can be admitted per host. Provenance is verified by its GitHub
asset digest, any attestation is recorded, and the recency window is replaced by a download
budget (goal a).

**Exit criteria**

- [ ] EC-PROVFWD-1 — A genuine image of any listed stable release gets a provenance entry, including a fixture release with 18 newer releases.
- [ ] EC-PROVFWD-2 — A tampered image costs at most `DOWNLOAD_BUDGET` archive fetches per call and refuses `unverified` with reason `budget_exhausted`; repeated calls progress monotonically through `member_cache`.
- [ ] EC-PROVFWD-3 — The hint only orders candidates: a wrong hint still admits the genuine image, and no hint admits a non-matching image.
- [ ] EC-PROVFWD-4 — Attestation status (`absent`/`present_unverified`) is recorded; a malformed attestation response refuses `unavailable`; the second channel follows R5.
- [ ] EC-PROVFWD-5 — The AGYROLL §1.1 transport, asset and member checks keep their existing tests green.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Resolver:** `agy_provenance.py`.
- **Attestation and second channel:** new `agy_attestation.py`.
- **Callers:** keep `stable_releases` and `release_by_tag` signature-compatible, and adapt
  the `--upstream-only` member fetch.

`agy_qualification.py` is not touched. REQUAL passes the hint. Gated on R4 and R5.

**Non-goals**

Admission tiers, the preflight, and signature verification before upstream publishes.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_attestation.py`
- `phase-loop-runtime/tests/test_agy_provenance_forward.py`

**Depends on**

- RECBIND

**Produces**

- IF-0-PROVFWD-1 — Forward resolver, budget reason and provenance fields (AGYROLL §1).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md` (self-qualification), `docs/ops/agy-upstream-watch.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_provenance_forward.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 3 — Per-instantiation preflight and recovery (REQUAL)

**Objective**

Qualification survives runtime upgrades while the QCI is unchanged. It re-qualifies
automatically at every instantiation point, and every refusal is visible (goal b).

**Exit criteria**

- [ ] EC-REQUAL-1 — `phase-loop agy-qualification preflight --route seat|executor|canary` admits or refuses typed, at most once per (store, route QCI, image).
- [ ] EC-REQUAL-2 — Runner start runs the preflight when a lane executor is `gemini`; a refusal stops the lane before launch, naming the code.
- [ ] EC-REQUAL-3 — A Gemini seat refused at preflight is reported `MODE_DEGRADED` with its code and fix line in the board report and president input, and is never absent or `unknown failure`.
- [ ] EC-REQUAL-4 — The local `qualified` key adopts `seat_qci()` (AGYROLL §2.1); a runtime upgrade with an unchanged QCI keeps local qualified entries, and a QCI change requalifies at the next preflight for any stable release.
- [ ] EC-REQUAL-5 — `repeated_transient` failed entries expire after 24 h; `violation` entries persist until cleared.
- [ ] EC-REQUAL-6 — A near-expiry login in `seat_profile` waits and renews instead of refusing, and the doctor's auth hint names the runtime token path.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Store and CLI:** the preflight CLI, the `seat_qci()` local key, the failed classes and the
  hint pass-through in `agy_qualification.py`.
- **Board, seat and doctor surfaces:** `panel_invoker.py` and `doctor.py`.
- **Runner hook:** `runner.py`.

The lanes own disjoint files.

**Non-goals**

Executor and canary admission tiers, which belong to EXECADMIT.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/doctor.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`

**Depends on**

- PROVFWD

**Produces**

- IF-0-REQUAL-1 — The preflight CLI and hooks, the refusal surface and the failed classes (AGYROLL §5).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_self_qualification.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 4 — Executor and canary admission (EXECADMIT)

**Objective**

The executor and the canary run a locally qualified current release under named custody
tiers, or a current catalog member (goal c, local path).

**Exit criteria**

- [ ] EC-EXECADMIT-1 — `trusted_command`, `admitted_command`, the `EXECUTOR_TRUSTED` role and the executor availability probes admit through `admit_for_executor`, using the launch env's PATH.
- [ ] EC-EXECADMIT-2 — With R2 approved, a `host_user` image that passes the provenance re-check is admitted; with R2 denied, only `shipped` and `host_root` images are admitted, and others refuse `agy_executor_image_unqualified`.
- [ ] EC-EXECADMIT-3 — The canary admits through `admit_for_canary` plus a complete capability matrix; no `"1.1.13"` literal gates production code.
- [ ] EC-EXECADMIT-4 — The executor and canary provenance re-check refuses an image whose upstream asset metadata no longer matches.
- [ ] EC-EXECADMIT-5 — Every refusal is a typed code from AGYROLL §8, and none reaches a sealed fallback.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Executor:** `agy_integrity.py` and the `launcher.py` call sites.
- **Owned and probe executor sites:** the `panel_invoker.py` `EXECUTOR_TRUSTED` sites and
  `executor_availability.py`.
- **Canary:** `agy_canary_evidence.py`.

Gated on R2 and R3.

**Non-goals**

Executor-specific operations and other harnesses.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/executor_availability.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_canary_evidence.py`
- `phase-loop-runtime/tests/test_agy_integrity_seat_admission.py`
- `phase-loop-runtime/tests/test_agy_canary_evidence.py`

**Depends on**

- REQUAL

**Produces**

- IF-0-EXECADMIT-1 — `admit_for_executor` and `admit_for_canary` with custody tiers (AGYROLL §4).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_integrity_seat_admission.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 5 — Rolling catalog job and lag rule (ROLLJOB)

**Objective**

A recurring, observable job on `ai` proposes each new upstream release as a signed catalog
member. A breach of the lag bound turns CI red (goals c and d).

**Exit criteria**

- [ ] EC-ROLLJOB-1 — A tick qualifies only the newest non-member release, retries the whole series up to `SERIES_RETRIES`, signs the record and opens a ready `agy-catalog-auto` PR; other members change only when their `qci` differs.
- [ ] EC-ROLLJOB-2 — `watch --install-units` and `--check` install and report the timer and the last tick's status line.
- [ ] EC-ROLLJOB-3 — Nightly `--upstream-only` fails under the AGYROLL §6.3 lag rule and only warns inside the bound.
- [ ] EC-ROLLJOB-4 — CI verifies each record signature against `plans/evidence/agy-allowed-signers` and the publisher digest; the workflow enforces the R6 merge rule.
- [ ] EC-ROLLJOB-5 — Catalog aging keeps `CATALOG_KEEP` members per route (R8).
- [ ] EC-ROLLJOB-6 — An expired login ends the tick with `gemini_login_expired` and opens no PR.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Job:** `agy_watch.py`.
- **CI:** the verifier's lag and signature checks, plus the workflows.
- **Units and install/check:** `docs/ops/agy-upstream-watch/**` and the `watch` CLI flags.

Gated on R6, R7, R8 and R9.

**Non-goals**

Runtime catalog fetch and other harnesses.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py`
- `.github/workflows/qualified-agy-image.yml`
- `docs/ops/agy-upstream-watch/agy-upstream-watch.service`
- `plans/evidence/agy-allowed-signers`
- `docs/ops/agy-upstream-watch.md`

**Depends on**

- RECBIND

**Produces**

- IF-0-ROLLJOB-1 — Tick contract, signed records, lag rule and merge rule (AGYROLL §6).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/ops/agy-upstream-watch.md`, `docs/releases/outside-agent-release-handoff.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_upstream_advisory.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 6 — Live activation on ai (ACTIVATE)

**Objective**

Install the job on `ai`. Then prove end to end that a new upstream release and a harness
release cut both pass with no hand step, and close agent-harness#1008.

**Exit criteria**

- [ ] EC-ACTIVATE-1 — `watch --check` on `ai` reports `installed`, recorded in `plans/evidence/agyroll-activate.json`.
- [ ] EC-ACTIVATE-2 — The newest stable upstream release at activation reaches `main` through an `agy-catalog-auto` PR with no hand step.
- [ ] EC-ACTIVATE-3 — The first harness release cut after RECBIND passes `--release` with no hand live run.
- [ ] EC-ACTIVATE-4 — An executor lane and a canary capture on `ai` admit a current release, neither 1.3.5 nor 1.1.13, through their preflights.
- [ ] EC-ACTIVATE-5 — agent-harness#1008 closes with that evidence linked, and `--source-only` and `agy_full_pin_scope.sh` are deleted.

**Scope notes**

Single lane: this is operational work on one host, with owner-approved `ai` access, plus a
deletion of the retired scripts. It produces runner-stamped operational evidence for
EC-ACTIVATE-1..4.

**Non-goals**

New code paths.

**Key files**

- `plans/evidence/agyroll-activate.json`
- `phase-loop-runtime/scripts/agy_full_pin_scope.sh`

**Depends on**

- EXECADMIT
- ROLLJOB

**Produces**

- (none)

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `roadmap_amendment`;
target surfaces: `specs/phase-plans-agyroll-v1.md`;
evidence paths: `plans/evidence/agyroll-activate.json`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

## Phase Dependency DAG

```
RECBIND ──┬──> PROVFWD ──> REQUAL ──> EXECADMIT ──┐
          │                                       ├──> ACTIVATE
          └──> ROLLJOB ───────────────────────────┘
```

- After RECBIND, ROLLJOB runs in parallel with PROVFWD → REQUAL → EXECADMIT.
- REQUAL follows PROVFWD because its local-key switch and automatic requalification need
  forward provenance (AGYROLL §2.1).
- Critical path: RECBIND → PROVFWD → REQUAL → EXECADMIT → ACTIVATE.

## Execution Notes

- **RECBIND is release-critical.** Land it before the 0.7.31 cut, so that 0.7.30
  (agent-harness#1923) is the last hand-made bump.
- **Planning commands:**
  - Plan any phase with `/claude-plan-phase specs/phase-plans-agyroll-v1.md <ALIAS> --output plans/phase-plan-v1-agyroll-<ALIAS>.md`.
  - PROVFWD and ROLLJOB can be planned now. ROLLJOB's implementation waits for R6–R9.
  - REQUAL and EXECADMIT follow; EXECADMIT waits for R2 and R3.
- **Before RECBIND lands:** PROVFWD and REQUAL edit route-core files. Until RECBIND lands,
  `--route-core` would demand a live re-record, so neither may land before it.
- **Single-writer files across phases:**
  - `agy_qualification.py`: RECBIND, then REQUAL.
  - `verify_qualified_agy_image.py`: RECBIND, then ROLLJOB.
  - `doctor.py`: REQUAL only.
  - `agy_watch.py`: RECBIND, then ROLLJOB. PROVFWD keeps `stable_releases`/`release_by_tag`
    signature-compatible, so it does not edit `agy_watch.py`.
  - `panel_invoker.py`: REQUAL, then EXECADMIT.

## Verification

```bash
cd phase-loop-runtime
timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider \
  tests/test_agy_route_conformance.py tests/test_agy_provenance_forward.py \
  tests/test_agy_self_qualification.py tests/test_agy_integrity_seat_admission.py \
  tests/test_agy_canary_evidence.py tests/test_verify_qualified_agy_route_core.py \
  tests/test_qualified_agy_image_set.py tests/test_agy_upstream_advisory.py
python scripts/verify_qualified_agy_image.py --contract
python scripts/verify_qualified_agy_image.py --release   # CI / Gate A only
```

Operational evidence comes from ACTIVATE, in `plans/evidence/agyroll-activate.json`, stamped
by the runner.
