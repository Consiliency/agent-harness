# Phase roadmap AGYROLL v1: agy admission without qualification lag

> # ADVISORY — not runner-selected (2026-11-08)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md`
> remains the sole active runner-selected roadmap. This status grants no live run,
> no `ai` access. The owner rulings below were decided by the owner on 2026-11-08.

## Context

agy (google-antigravity/antigravity-cli) ships stable releases almost every day. There are 84
so far; 1.4.9 through 1.5.3 shipped between 2026-10-28 and 2026-11-07. Admission has lagged
by weeks:
- Until agent-harness#1923 bumped it by hand to 1.5.3, the shipped catalog held only 1.3.5.
- Executor launches admit only catalog members.
- The canary runs only a binary that reports itself as agy `1.1.13`.
- Review seats can self-qualify, but only the newest four releases.
- The agent-harness#1420 upgrade drop recurred on 2026-11-04.

This roadmap removes the per-release hand step for good. It covers agent-harness#1008 and the
related agent-harness#1158, agent-harness#1407, agent-harness#1420 and agent-harness#1520.
The evidence is in the AGYROLL contract (External Inputs).

What exists today, and why it leaves the lag in place:

- **First-use self-qualification** (agent-harness#1076). `agy_qualification.ensure_admitted`
  runs from the board preflight through `requalify_once`. Spawn is lookup-only. Seats reach
  it through `agy_integrity.admit_for_seat`.
- **Executor: catalog-only by a scope cut.** `trusted_command` and `admitted_command` call
  `agy_integrity.check(path)` with no env, so they admit only `QUALIFIED_IMAGES`.
  - The agent-harness#1333 plan scoped executors out ("not seats … keep release-only
    admission"), the president confirmed it on agent-harness#1350, and no threat was named.
  - `trusted_command` also execs the *path* after closing the verified memfd
    (`agy_integrity.py:112-122`, `launcher.py:2777`). That breaks the agent-harness#1076 I1
    invariant today.
- **Canary: weaker than the catalog, not catalog-only.** In production the canary never calls
  `check()`. It admits through `_trusted_agy_runtime`, which checks fixed paths and modes and
  records a digest that it compares to nothing. It also requires the self-reported
  `agy --version == "1.1.13"`, then execs the path.
- **The newest-four window caps download cost; it does not check provenance.** It comes from
  ruling D4 (`plans/detailed-agy-selfqual-1076-20260927.md`). With releases nearly daily, a
  host that falls about four releases behind can never requalify once its entries drop.
- **Release-side drop.** IF-0-TEAMHOST-4 (agent-harness#1873, in 0.7.29) moved the local key
  to `agy_profile_digest` (maintainer Q8). The release side still breaks, for two reasons:
  - Every record pins all ~288 package sources. That is the full pin, from the
    agent-harness#1032 ruling, enforced at release.
  - Every PR that touches the route core runs `--route-core`, from the agent-harness#1029
    ruling.

  The catalog literal itself sits in a route-core file. So every release and every member
  addition requalifies every member, and agent-harness#1901 cut the catalog from 12 members
  to 1.
- **The fix was ruled but never built.**
  - `agy_watch` exists, but nothing installs its timer, and it has never opened a PR.
  - Q10 (signed promotion) and Q11 (newest-only cut), both from 2026-10-14, sit unstarted in
    agent-harness#1602 L6.
  - The nightly upstream check only warns (agent-harness#1333 PR1).
- **Upstream signs nothing.** It publishes no signature and no attestation; the attestations
  API returns 404. Provenance rests on GitHub's per-asset digest, fetched over the pinned
  transport.

**AGYFRESH amendment (2026-11-20).** Only RECBIND was built. On 2026-11-11 the agy binary
passed the 250 MB member bound at 1.5.6 and the Gemini seat was lost: a subject that is not
admitted is simply excluded, with no floor. The amendment adds two phases. RESTORE replaces
the size literals with call-time bounds and a streaming reader. HOLD lets the seat run an
already-qualified image when the selected one cannot be used, so availability stops
depending on qualification speed. It also adds ROLLJOB clauses and amends R6 (R6′). Design:
the AGYFRESH contract (External Inputs).

Thesis: admit by evidence, keyed on what the evidence depends on. That means genuine upstream
bytes, a qualification under the route's contract identity (QCI), and a named custody tier.
An observable recurring job keeps the shipped catalog current, inside a lag bound that turns
red when breached.

## Architecture North Star

```
 GitHub release (tag, per-asset digest) --pinned transport--> forward provenance
                     (any stable release; per-call budget + daily total cap; path-derived hint)
                                                                   |
 seat QCI (= agy_profile_digest at agy_validator_v1) <--- strict conformance suite (CI)
                                                                   |
        custody:  shipped catalog (package data)   |   host_user store (euid boundary)
                         ^
   ai: watch (timer) -- signed v2 record, one member/tick --> intake issue -> `main` workflow verifies, authors the PR
                                                              -> job + owner signatures -> main
                                               (R6′, all catalog PRs: job + base provenance check)
                                                                   |
        admit_for_seat        admit_for_executor (memfd)    admit_for_canary (memfd)
        (board preflight)     (runner-start preflight)      (capture-start preflight)
```

## Assumptions

1. agent-harness#1923 (v0.7.30, the hand bump to agy 1.5.3) merged on 2026-11-08 (EXT-0730
   is met). If RECBIND lands before the 0.7.31 cut, 0.7.30 was the last hand-made bump.
2. Every member's v1 record has a record commit whose sources match its `source_sha256`
   exactly, and whose `agy_profile_digest()` and validator closure equal head's (AGYROLL
   §3.5). This is true for 1.5.3 (record commit `6ad154e48b`, per the RECBIND probe on
   2026-11-08). If it is false at execution time, RECBIND's stop task (SL-1.2) fires and the
   roadmap is amended. Nothing converts by assumption.
3. The production qualification driver can run hermetically under the bubblewrap and
   user-namespace setup that `publish-pypi.yml` already provisions. If not, RECBIND stops and
   is amended.
4. `ai` remains the qualifying host, and the job runs there only after R9's conditions hold.
5. The feasibility lane (2026-11-20) found that the jailed review route
   (refusing with `gemini_heartbeat_capability_unavailable`) and the
   release-authority check refuse a held image whose digest differs from the managed
   release's pinned executable. Managed-release subjects are therefore not covered by the
   harness-side hold (EC-HOLD-6, second branch), and the authority check is unchanged. The
   evidence is the probe test `phase-loop-runtime/tests/test_agy_hold_managed.py`, which
   ships with HOLD's core lane as a regression guard. On managed
   hosts, recovery happens at build time (EXT-DOT) and through the RESTORE restore runs.
   HOLD's core lane records how it handles the non-jailed heartbeat route.
   The jailed **standalone** route executes the provider by path, so a held admission could
   not run there either. History, first design: D12 first changed that route, for held
   admissions only, to execute the admitted sealed image, and left it to HOLD's jail
   feasibility lane to decide whether the one admitted mount form worked. Had it not, the
   route was to stay not covered while the owner chose between a new amendment and accepting
   the gap, with the rest of HOLD delivered either way. That lane reported STOP and the
   owner called for a new amendment. Current status:
   The first mount form (a sealed-memfd bind) failed its feasibility lane: neither
   bubblewrap nor the kernel binds a memfd. The route instead stages a private copy
   (AGYFRESH §2.11), subject to the second feasibility lane. Its guarantee rests on custody
   of that copy. A runtime check of the executing image is a backstop, and a wrong image
   that reached `exec` could act inside the jail before it is refused (AGYFRESH §2.11).
   The second feasibility lane reported GO with that runtime check observed, and the
   coordinator recorded the decision (`plans/evidence/agyfresh-jailbind-v2-feasibility.md`;
   AGYFRESH §2.11, "Outcome decided").

## External Inputs

| Input | Pin |
| --- | --- |
| AGYROLL contract | `plans/artifacts/agyroll-v1-contract.md`, sha256 `79a50a21c087cc3b7a1a176f66e2f7ae3cd944798cc4159472bca8d136122e56` (repinned by AGYFRESH: §1.2 archive bounds, §6.1 R6′, §6.2 tick frequency, §6.3 warning; repinned by PROVFWD: §1.2 candidate order and total bound; repinned for R9′) |
| AGYFRESH contract (RESTORE, HOLD, ROLLJOB additions, R6′) | `plans/artifacts/agyfresh-contract.md`, sha256 `0ff821471a7bbb2aa1bd6068c967fce6354c1343d381dfa159074bdffa717c62` (repinned for R9′) |
| TEAMHOST contract §5 (agy key, `requalify_once` call sites) | `plans/seats-teamhost-contract.md`, sha256 `91a7261323a12e2455ef8445b736a6a7749d06e162b4b34be85e525e046b1818`. **REQUAL amends §5.** The amendment adds the runner and canary preflight call sites, and names `seat_qci()` as the `qualified` key. Its value equals `agy_profile_digest()` at `agy_validator_v1`, so no entry drops, and §5 stays correct after a validator bump. The repin lands in REQUAL's docs lane. |
| Q10 and (G) promotion rules | `.consiliency/plans/detailed-lkg-cli-qualification-1602-20261014-0359.md` §(G) and the Q10 ruling |
| Upstream provenance surface | the GitHub releases API for `google-antigravity/antigravity-cli`: per-asset `digest`; the attestations endpoint returned 404 on 2026-11-08 |

These are immutable planning inputs, and a change needs a reviewed repin. No plan pins a
future implementation commit, a commit count or a landing topology.

## Owner Rulings (2026-11-08)

The owner ruled R1–R9 on 2026-11-08 and accepted the plan-tier board's recommendations from
its agent-harness#1927 comment as written. The rulings are recorded on agent-harness#1008.
Each condition below is binding on the phase that implements it. A lane that cannot meet a
condition stops and routes an amendment.

- **R1 — APPROVED with conditions.** A harness release ships without re-running agy live. It
  relies on records bound to the QCI, the strict conformance suite and the validator guard.
  - **Conditions:**
    - conformance cannot pass by skipping (AGYROLL §3.4; EC-RECBIND-5);
    - the semantic validator guard covers transitive predicates (§2.1; EC-RECBIND-2);
    - both removed gates are named here (§3.3).
  - **Superseded:**
    - the agent-harness#1032 maintainer ruling (the full pin);
    - its president line, "No publish path ships a tree whose full pin set differs…";
    - agent-harness#1119, "kept at full strength";
    - the **per-PR route-core gate** from agent-harness#1029 (2026-09-24,
      `qualified-agy-image.yml:48-53`);
    - Q11's cut re-run.
  - **Implemented by:** RECBIND.
- **R2 — APPROVED with conditions.** Executor lanes may admit a `host_user` image that this
  account qualified itself, after the provenance re-check.
  - **Conditions:**
    - The executor execs the admitted memfd, never a path (§4; EC-EXECADMIT-1).
    - The forgery boundary is stated: any process running as that euid can forge a
      `host_user` entry. The re-check catches upstream withdrawal, not local forgery.
  - **Superseded:** the agent-harness#1333 executor scope cut, confirmed on
    agent-harness#1350.
  - **Implemented by:** EXECADMIT.
- **R3 — APPROVED with conditions.** The canary admits by `admit_for_canary` plus a complete
  capability matrix, which replaces the self-reported `1.1.13`. This strengthens admission.
  - **Conditions:** memfd exec, and the `stream-json` check is kept (EC-EXECADMIT-3).
  - **Implemented by:** EXECADMIT.
- **R4 — APPROVED with conditions.** Any genuine stable release is admissible, not only the
  newest four.
  - **Conditions:**
    - the retryable outcomes (`budget_exhausted`, `download_cap_reached`) never consume the
      preflight cap (EC-REQUAL-1);
    - a total download bound applies: 2 per call and 12 per (store, image) per 24 h
      (§1.2; EC-PROVFWD-2);
    - there is no freshness refusal.
  - **Superseded:** D4, the recency window.
  - **Implemented by:** PROVFWD and REQUAL.
- **R5 — APPROVED.** Attestations are recorded but not required. The installer-manifest
  cross-check runs only in the catalog job.
  - **Implemented by:** PROVFWD.
- **R6 — REJECTED as written; the board's alternative is adopted.** "One job signature plus
  green CI auto-merges" is rejected. Instead (§6.1; EC-ROLLJOB-4):
  - the signer list, verifier and merge rule are read from the base branch;
  - Q10's two distinct signers are the job key plus an **enrolled owner key**;
  - auto-merge applies only to data-only diffs, and only once `main` has a non-bypassable
    ruleset. Until then a maintainer merges after both signatures verify.

  Q10's draft promotion PR, signer quorum and publisher digest stand, and so does (G)'s base-branch rule. R6 **conditionally supersedes** Q10/(G)'s "a maintainer merges": once `main` has a non-bypassable ruleset, a data-only diff auto-merges. Every other diff, and every PR before that ruleset exists, is still merged by a maintainer.
  - **Amended 2026-11-20 (D8 = B), as R6′.** R6 stands except that no catalog PR needs an
    owner signature. The second Q10 signer is the base branch's hosted provenance check, which
    re-fetches the asset by tag and re-derives the member digest. Only a PR whose diff is only
    `data/agy_catalog.json` and `plans/evidence/agy-*-linux-x64-qualification.json`, and that
    adds or ages non-`pinned` members, auto-merges. A `pinned` change, any other path, and any
    change to the signer list, verifier or merge-rule workflow never auto-merges: a repository
    writer merges it under the `main` ruleset. The owner's words: "Whatever the solution is it
    should not involve me signing anything. It needs to be automated." The residual risk is
    stated in AGYFRESH §5.1 and AGYROLL §6.1.
  - **Scope of R6′ under R9′.** "Auto-merges" and "never auto-merges" describe what the
    promotion automation does: it arms a merge only for the diff class above, with a valid job
    signature. They are not a limit on repository writers, who keep GitHub's ordinary authority
    to merge, or to enable auto-merge on, any pull request that meets the `main` ruleset.
  - **Implemented by:** ROLLJOB.
- **R7 — APPROVED with conditions.** The `ai` job renews its own Gemini login, outside any
  seat.
  - **Conditions:**
    - renewal goes only through `_await_gemini_login` → `_refresh_gemini_credential`
      (§5, §6.2);
    - the refresh token stays out of seats (agent-harness#1222);
    - **expiry turns red directly**: the tick exits non-zero with `gemini_login_expired`, its systemd unit enters `failed`, and `watch --check` reports it at once. CI fails through the lag rule once the newest release passes `LAG_BOUND` (EC-ROLLJOB-6).
  - **Superseded:** the unwritten owner-only renewal rule on `ai` (agent-harness#1923,
    agent-harness#1924).
  - **Implemented by:** REQUAL (path) and ROLLJOB (job).
- **R8 — APPROVED with conditions.** The shipped catalog keeps only recent members.
  - **Conditions:**
    - keep a member while it is among the newest 3 *or* younger than 14 days;
    - never prune a `pinned` member;
    - **Q11 is superseded for the agy route only** (§6.1; EC-ROLLJOB-5). Q11 had itself already superseded the 2026-10-08 Q5, and other harnesses keep Q11.
  - **Implemented by:** ROLLJOB.
- **R9 — APPROVED with conditions.** The `ai` job gets a repository-only GitHub identity.
  - **Conditions, all in place before ACTIVATE (EC-ACTIVATE-1):**
    - a non-admin GitHub App or machine user;
    - no `workflows` permission;
    - a non-bypassable `main` ruleset.
  - **Amended 2026-11-20, as R9′.** No GitHub user account is created. The job on the
    qualification host holds an issues-only GitHub App and submits its signed record as data.
    A workflow on `main` verifies it and authors the catalog pull request with a second App
    whose key exists only in GitHub Actions (AGYROLL §6.1, §6.2). The non-bypassable `main`
    ruleset condition stands, and now also requires strict status checks. No review rule is
    added and CODEOWNERS is unchanged: the files this mechanism trusts change through
    ordinary pull requests by repository writers, who are trusted for them as for any code. A
    required check re-derives upstream provenance for every catalog change, whoever wrote it.
    The existing automation account's access is unchanged. Reason: with write access on the
    qualification host, R6′'s statement about a compromised job identity would hold for the
    promotion path only. Confirmed by the owner: 2026-11-20T17:39:31Z, in answer to a direct
    question: "Confirm as described (Recommended)".
  - **Implemented by:** ACTIVATE (with agent-harness#1138).

## Owner Decisions (2026-11-20, AGYFRESH)

The owner decided these for the AGYFRESH amendment. Values live in the cited sections.

- **D1** — cut a release now (RESTORE operational step).
- **D2** — one live self-qualification per host after that release installs, then the
  automatic first-use run, on all machines including `ai` (RESTORE; EC-RESTORE-1).
- **D3a** — the hold is on by default (`[agy] hold`, AGYFRESH §2.7).
- **D3b** — managed hosts are included if the feasibility lane passes (§2.9; EC-HOLD-6). It
  failed, so they are not covered (Assumption 5).
- **D3c** — held images are shipped catalog members and images this account qualified (§2.3).
- **D4** — no age limit on a held image; a per-host deny list (`[agy] hold_deny`, §2.7).
- **D5** — keep the last two admitted images on disk (§2.8; EC-HOLD-10).
- **D6** — minimal dotfiles change: a refused agy no longer fails the tooling build (§2.10;
  EC-HOLD-11).
- **D7** — start R9's prerequisites now: the two GitHub Apps (R9′), non-bypassable `main`
  ruleset, and the job's signing key. The owner creates and enrols no key (R6′). Setup only; ACTIVATE still
  needs EXECADMIT and ROLLJOB.
- **D8** — B: amend R6 (R6′ above).
- **D9** — hourly watch tick (AGYROLL §6.2).
- **D10** — 512 MB member, 256 MB archive, 1 GB expanded, one in-memory image copy (§1).
- **D11** — amend this roadmap rather than open a separate one.
- **D12** — on the jailed standalone route a **held** admission runs from a private per-launch
  copy of the admitted image, held under a checked name (AGYFRESH §2.11; EC-HOLD-13, EC-HOLD-14). Ordinary launches keep the
  existing path bind. The managed projection and its digest gate are unchanged. The bind
  must leave every canonical jail digest and qualification key as it is; a form that
  changes one is not admitted by this amendment. The jail integration lane merges only on
  the release owner's clearance (G-REL).

## External Readiness Gates

- **EXT-0730.** agent-harness#1923 is merged or abandoned. It merged on 2026-11-08, so the
  gate is met.
- **EXT-1916.** agent-harness#1916 shares `panel_invoker.py`. REQUAL and EXECADMIT implement
  after it merges or closes, and rebase onto it.
- **EXT-R.** Every owner ruling is recorded on agent-harness#1008 (decided 2026-11-08), so the
  gate is met. Each phase implements its rulings' conditions as listed in Owner Rulings.
- **EXT-DOT.** EC-HOLD-11 lands in Consiliency/dotfiles under that repository's rules. It is
  independent of every agent-harness lane and reads `admission_verdict(execute=False)`,
  which HOLD leaves unchanged (EC-HOLD-5).

## Non-Goals

- Executor-specific qualification operations.
- Platforms other than linux-x64 glibc.
- Fetching a catalog at runtime.
- A root-owned qualification tier. TEAMHOST §7 pins are seat authority, not qualification.
- Egress or `SEALED_FALLBACK_CODES` changes.
- Seat-jail changes, **except** what AGYFRESH §2.11 defines for a held admission on the
  standalone Gemini route: a private staged copy bound by the existing path bind and gated
  at each start as §2.11 states. No jail property changes: no mount, capability, filter,
  uid, environment or egress property of any jail, and no jail of another leg.
- `cli_qualification` adapters for other harnesses (agent-harness#1333 PR3–PR7,
  agent-harness#1602 L1–L5).
- Any live run or `ai` access before ACTIVATE, except RESTORE's restore runs under D2.
- A held image that meets no existing qualification predicate, or any weakening of the
  managed-release authority check to admit one (AGYFRESH §2.3, §2.9).

## Cross-Cutting Principles

- **Fail closed.** A missing or malformed catalog, an empty catalog in CI, an unknown
  attestation response, an unverifiable signature, a skipped conformance obligation or an
  unreachable channel all refuse with a typed code (AGYROLL §8). A refusal is never silent
  and never sealed.
- **Every admission names its evidence:** provenance, QCI and custody tier. Executed bytes
  are always the admitted memfd, never a path.
- **Lookup-only at spawn.** Qualification runs only in preflights and in
  `agy-qualification run`/`watch`.
- **Measured, not literal.** No version literal gates admission. Versions appear only as
  untrusted, path-derived hints and as reporting fields.
- **Shared-host test limits.** Targeted pytest runs serially under `timeout`. Full suites and
  live runs go to CI, Gate A, ACTIVATE or RESTORE's D2 restore runs.
- **Availability floor.** A subject-side refusal falls back to an already-qualified image
  (HOLD); with no candidate, the original refusal is raised unchanged.

## Top Interface-Freeze Gates

- IF-0-RECBIND-1 — `seat_qci()` and `QUALIFICATION_VALIDATOR`, the package-data catalog `qualified_agy_catalog.v3`, record v2, and the verifier modes `--contract`/`--release` (AGYROLL §2, §3).
- IF-0-RECBIND-2 — The strict conformance suite's entry point, its `CONFORMANCE_OBLIGATIONS` and its JUnit report, which `--release` consumes (AGYROLL §3.4).
- IF-0-PROVFWD-1 — `find_provenance(hint, budget)`, the `ProvenanceError.reason` values `budget_exhausted`/`download_cap_reached`, the path-derived hint, and the provenance fields `attestation`/`second_channel` (AGYROLL §1).
- IF-0-REQUAL-1 — The `agy-qualification preflight` CLI and hooks, retryable-outcome handling, the `MODE_DEGRADED` surface, failed classes and the TEAMHOST §5 repin (AGYROLL §5).
- IF-0-EXECADMIT-1 — `admit_for_executor`/`admit_for_canary`, memfd exec and the custody tiers (AGYROLL §4).
- IF-0-ROLLJOB-1 — The tick contract, signed records, the base-branch promotion policy, the lag rule and aging (AGYROLL §6).
- IF-0-RESTORE-1 — The size constants, call-time reads, `VerifiedImage.from_fd`, the expanded-bytes rule and the memory rule (AGYFRESH §1, §6.1).
- IF-0-HOLD-1 — `admit_seat`, hold-eligible and never-eligible conditions, qualification predicates, discovery order and budgets, filesystem handling, evidence and config (AGYFRESH §2.1–§2.7, §6.2–§6.3).
- IF-0-HOLD-2 — The harness-owned cache of admitted images (AGYFRESH §2.8).
- IF-0-HOLD-3 — Consiliency/dotfiles `stage_agy` falling back to a retained image (AGYFRESH §2.10).
- IF-0-HOLD-4 — The managed-release authority outcome from the feasibility lane (AGYFRESH §2.9).
- IF-0-HOLD-5 — The standalone Gemini jail's staged private copy for a held admission, its checked name, its start gate, and its evidence (AGYFRESH §2.11).

## Phases

### Phase 1 — Record binding and catalog decoupling (RECBIND)

**Objective**

Bind catalog evidence to `seat_qci()` instead of file hashes, and move the catalog out of the
route core. After this phase, neither a release nor a member addition invalidates existing
records, so later phases land without hand live runs (goal d).

**Exit criteria**

- [ ] EC-RECBIND-1 — `gemini_heartbeat.QUALIFIED_IMAGES` loads from `phase_loop_runtime/data/agy_catalog.json` (AGYROLL §3.1); a missing or malformed file gives an empty runtime catalog, and the release fast path admits nothing; the verifier fails on a malformed or empty catalog.
- [ ] EC-RECBIND-2 — `seat_qci()` equals `agy_profile_digest()` at `agy_validator_v1`; a `__version__` bump or a catalog edit leaves it unchanged; the semantic validator guard (AGYROLL §2.1, transitive) turns red on a verdict-changing mutant without a literal bump.
- [ ] EC-RECBIND-3 — Every member has one v2 record whose `qci` equals the tree's; `--contract` runs on every PR and fails naming the member when they differ.
- [ ] EC-RECBIND-4 — The conformance suite passes on the production driver: each provider-trippable negative control (no terminal event, unregistered helper, tool step) does not pass with its pinned outcome, and each driver-enforcement control (ignores cancel, orphaned child) passes (AGYROLL §3.4, amendments A1 and A2).
- [ ] EC-RECBIND-5 — `publish-pypi.yml` gates on a strict conformance run plus `--release`; a tree differing only outside the QCI passes with no live run; a QCI change fails; a skipped, xfailed or partial conformance run fails `--release`.
- [ ] EC-RECBIND-6 — v1 records convert without a live run through their record commit (AGYROLL §3.5), or the stop task fires.

**Scope notes**

Decompose into 2 lanes plus docs:
- **Catalog, QCI and records:** one sequential lane covering the runtime catalog loader,
  `seat_qci`, the validator guard, record v2, the converter stop gate, the verifier,
  `agy_watch`'s writers, both workflows, and the watch tests and inventory.
- **Conformance suite:** tests and fixtures only.

The runtime and records work cannot split. The watch and verifier tests and the exact
inventory couple them, and the lane-IR overlap check refuses shared owned files. The lanes
own disjoint files. This phase implements R1 (approved) and its three conditions.

**Non-goals**

Provenance, the executor, the canary and the job.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json`
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py`
- `phase-loop-runtime/scripts/convert_agy_record_v2.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`
- `phase-loop-runtime/tests/test_agy_route_conformance.py`
- `phase-loop-runtime/tests/test_agy_self_qualification.py`
- `phase-loop-runtime/tests/data/seat_launch_references.json`
- `.github/workflows/qualified-agy-image.yml`
- `.github/workflows/publish-pypi.yml`
- `plans/evidence/qualified-provider-images.json`

**Depends on**

- (none)

**Produces**

- IF-0-RECBIND-1 — `seat_qci`, catalog v3, record v2 and the verifier modes (AGYROLL §2, §3).
- IF-0-RECBIND-2 — The strict conformance entry point, its obligations and its report (AGYROLL §3.4).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md` (qualified images), `docs/releases/outside-agent-release-handoff.md`, `docs/advisor-board-capabilities-card.md`;
evidence paths: `plans/evidence/agy-*-linux-x64-qualification.json`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 2 — Forward provenance for any stable release (PROVFWD)

**Objective**

Any stable upstream release can be admitted per host, verified by its GitHub asset digest,
with any attestation recorded. Bounded downloads replace the recency window (goal a).

**Exit criteria**

- [ ] EC-PROVFWD-1 — A genuine image of any listed stable release gets a provenance entry, including a fixture with 18 newer releases.
- [ ] EC-PROVFWD-2 — A tampered image costs at most `DOWNLOAD_BUDGET` fetches per call and `TOTAL_DOWNLOAD_CAP` per (store, image) per 24 h; it refuses `unverified` with reason `budget_exhausted` or `download_cap_reached`; repeated calls progress through `member_cache`.
- [ ] EC-PROVFWD-3 — The hint comes only from a `realpath` component and never from executing or reading the image; a wrong hint still admits the genuine image, and no hint admits a non-matching one.
- [ ] EC-PROVFWD-4 — Attestation status (`absent`/`present_unverified`) is recorded; a malformed response refuses `unavailable`; `second_channel` defaults to `not_checked` outside the job.
- [ ] EC-PROVFWD-5 — The AGYROLL §1.1 checks keep their existing tests green.
- [ ] EC-PROVFWD-6 — `agy_watch`'s `RECENCY_WINDOW` caller uses the new listing with no window, and its tests stay green.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Resolver:** `agy_provenance.py`.
- **Attestation and second channel:** a new `agy_attestation.py`.
- **Callers:** the `agy_watch.py` listing caller and the verifier's `--upstream-only` fetch.

PROVFWD also owns one serialized edit to `agy_qualification.py`, after HOLD's core lane: the
store's fetch ledger, the hint and ledger at the first-use call site, and release of the
once-per-key entry on the two retryable reasons. R4's total bound is a condition of removing
the window, so the resolver does not ship without it (coordinator ruling, 2026-11-20).
Implements R4 and R5 (approved).

**Non-goals**

Admission tiers, the preflight, and attestation verification before upstream publishes any.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_attestation.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/tests/test_agy_provenance_forward.py`
- `phase-loop-runtime/tests/test_agy_provenance_wiring.py`

**Depends on**

- RECBIND

**Produces**

- IF-0-PROVFWD-1 — The forward resolver, the reasons, the hint and the provenance fields (AGYROLL §1).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md` (self-qualification), `docs/ops/agy-upstream-watch.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_provenance_forward.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 3 — Size bounds and seat restore (RESTORE)

**Objective**

Return the Gemini seat on hosts whose agy outgrew the size bounds, and make the next growth a
constant change: three ceilings defined once and read at call time, and a streaming reader
that holds one image copy (AGYFRESH §1).

**Exit criteria**

- [ ] EC-RESTORE-1 — A released `phase-loop-runtime` contains the 512 MB member bound, and `phase-loop agy-qualification status` on each host named in the O2 grant reports `verdict.status == "admits"` for the staged seat subject; operational evidence in `plans/evidence/agyfresh-restore.json`, stamped by the runner.
- [ ] EC-RESTORE-2 — AGYFRESH §1: at a patched bound N, an image of N−1 and of exactly N bytes is accepted and N+1 refused by `read_member`, `gh.admit`, `agy_integrity.check` and the verifier; an archive whose declared member sizes exceed `MAX_EXPANDED_BYTES` is refused; the seat reader's peak traced allocation stays under 4 MiB for any image size.

**Scope notes**

Decompose into 2 lanes:
- **Caps** (code): `agy_provenance.py`, `agy_integrity.py`, `gemini_heartbeat.py`, the
  verifier and a new size-bounds test. Carries the binding archive-expansion requirement
  (AGYFRESH §6.1).
- **Restore** (operational, O1 then O2): cut the release under D1; on each granted host run
  `status`, one live `run`, and `status` again under D2, recording the runner-stamped
  evidence for EC-RESTORE-1.

No requalification intended (AGYFRESH §3). Implements D1, D2 and D10.

**Non-goals**

The hold, the watch's member streaming (EC-ROLLJOB-9), and showing that a host can afford the
ceilings.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py`
- `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py`
- `phase-loop-runtime/tests/test_agy_size_bounds.py`
- `plans/evidence/agyfresh-restore.json`

**Depends on**

- RECBIND

**Produces**

- IF-0-RESTORE-1 — The size constants, call-time reads, `VerifiedImage.from_fd`, the expanded-bytes rule and the memory rule (AGYFRESH §1, §6.1).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md` (qualified images);
evidence paths: `phase-loop-runtime/tests/test_agy_size_bounds.py`, `plans/evidence/agyfresh-restore.json`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 4 — Availability floor (HOLD)

**Objective**

When the seat's selected agy cannot be used for a subject-side reason, the seat runs an
already-qualified image found by a bounded search of the host. Every executed image still
meets an existing qualification predicate; what changes is selection (AGYFRESH §2.1). The
promise is bounded best effort (§2.4).

**Exit criteria**

- [ ] EC-HOLD-1 — For each hold-eligible reason in AGYFRESH §2.2, at preflight and at spawn, a held release member is admitted with source `lkg` and the reason in evidence; with no candidate the original refusal is raised unchanged.
- [ ] EC-HOLD-2 — Each never-eligible condition in §2.2 propagates unchanged with a candidate present, including no provider installed.
- [ ] EC-HOLD-3 — A held non-member needs a MAC-valid `provenance` and `qualified` entry and no `failed` entry, and is never executed before the provenance check; `hold_deny` excludes it.
- [ ] EC-HOLD-4 — First use runs for the subject before any hold; a passing subject is returned.
- [ ] EC-HOLD-5 — `admission_verdict(execute=False)` never reports `admits` for a non-member because of a held image; `[agy] hold = false` restores today's refusals.
- [ ] EC-HOLD-6 — Managed release: with a fallback image whose digest differs from the pinned subject, the real projection and jail admission pass (lane F0); otherwise managed hosts are recorded as not covered and the authority check is unchanged.
- [ ] EC-HOLD-7 — Order and budgets (§2.4): a newer vendor member beats an older cache member whatever their mtimes; 64 forged hints cannot prevent admission of an authenticated candidate; result is identical under shuffled directory order.
- [ ] EC-HOLD-8 — Resource rule (§1.2, §2.2): at most one sealed image is open at any point of a hold; every rejected, cancelled or failing candidate is closed.
- [ ] EC-HOLD-9 — Filesystem rule (§2.5): a symlinked candidate, a directory swapped for a symlink between listing and open, and a file whose replacement is observed during the read (AGYFRESH §2.5) are all rejected.
- [ ] EC-HOLD-10 — Cache (§2.8): retain, prune, corrupt-file removal and `clear --all` are correct under concurrent retain and clear.
- [ ] EC-HOLD-11 — (Consiliency/dotfiles) a selected agy the release runtime refuses no longer fails the release build when a retained image verifies.
- [ ] EC-HOLD-12 — `agy-qualification status` reports the hold state (§2.6).
- [ ] EC-HOLD-13 — Jailed standalone route (AGYFRESH §2.11): for a held admission the production and the probe jail bind one private per-launch copy of the admitted image at `/seat/bin/gemini`, by one checked name that no other uid can redirect; a staged copy that fails verification or the name rules is refused; every held start is gated as AGYFRESH §2.11 states, by the custody proofs and by the runtime check where §2.11 provides one, and a refused start's stream, files and success evidence are not used and its jail tree is torn down; what runs is unchanged after the candidate's source file is renamed, unlinked or rewritten; the evidence carries source `lkg`; a failed build, a refused check, a cancellation and a completion leave no staged file or descriptor; an ordinary launch keeps the existing path bind, and its launch and evidence behaviour apart from the one additive `provider_admission_source` key.
- [ ] EC-HOLD-14 — Jail qualification (AGYFRESH §2.11, §3): the canonical digest of every registered leg and every qualification key are the same before and after the jail integration lane; a staged-image jail, the managed-dependency jail and every jail the qualifier builds each pass the unstubbed canonical comparison against their own leg's canonical digest.
- [ ] EC-HOLD-15 — Status (AGYFRESH §2.6): `hold` reports the subject class, coverage per route, and a candidate with its state; it never reports a candidate as in use.

**Scope notes**

Decompose into these lanes:
- **F0 feasibility** (managed authority): done; it failed (Assumption 5).
- **Amend** (docs): this amendment.
- **Jail feasibility** (scratch test, no production change): decides whether the mount form
  of AGYFRESH §2.11 works. If it does not, the jail integration lane is not run and the
  other lanes complete without it. A second feasibility lane decides whether the
  staged-copy design works.
- **Core**: `agy_hold.py`, `admit_seat` in `agy_qualification.py`, config, status.
- **Jail integration**: `agy_hold_stage.py` and `panel_invoker._prepare_jailed_gemini`
  for a held admission on the standalone Gemini jail; evidence. After core and a passing
  jail feasibility lane; merged only under G-REL.
- **Cache**: retain, prune and `clear --all`.
- **Dotfiles** (Consiliency/dotfiles, EXT-DOT): independent.

Core and cache carry the binding ordering and replacement-detection requirements (AGYFRESH
§6.2, §6.3). Implements D3a–c, D4, D5 and D6.

Stop rule: if the managed projection, its digest gate, the authority path, or any jail
property would have to change for a test to pass, the lane stops.

**Non-goals**

New refusal codes (AGYFRESH §4), store-key, catalog or record changes, executor and canary
admission, any change to the authority path, and any change to a jail property. The staged
source and the start gate that AGYFRESH §2.11 defines for a held admission are in scope;
they change no jail property.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_hold.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_hold_stage.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`
- `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/tests/test_agy_hold.py`
- `phase-loop-runtime/tests/test_agy_hold_managed.py`
- `phase-loop-runtime/tests/test_agy_hold_cache.py`
- `phase-loop-runtime/tests/test_agy_hold_jail.py`
- `docs/advisor-board-capabilities-card.md`

**Depends on**

- RESTORE

**Produces**

- IF-0-HOLD-1 — `admit_seat`, hold-eligible and never-eligible conditions, qualification predicates, discovery order and budgets, filesystem handling, evidence and config (AGYFRESH §2.1–§2.7, §6.2–§6.3).
- IF-0-HOLD-2 — The harness-owned cache of admitted images (AGYFRESH §2.8).
- IF-0-HOLD-3 — Consiliency/dotfiles `stage_agy` falling back to a retained image (AGYFRESH §2.10).
- IF-0-HOLD-4 — The managed-release authority outcome from the feasibility lane (AGYFRESH §2.9).
- IF-0-HOLD-5 — The standalone Gemini jail's staged private copy for a held admission, its checked name, its start gate, and its evidence (AGYFRESH §2.11).

**Release hold G-REL (execution gate; release owner: the Agent-Harness Exec).** The control
is the merge, and the release owner is the only merge actor for the jail integration lane.
Its PR does not merge to `main` until the release owner has recorded an affirmative
clearance that names the cleared head SHA. The clearance names three records: the second
feasibility lane's report on `main`, with its digest comparison; that head's hosted CI run
with both hosted groups executed and zero skips, namely the EC-HOLD-14 cases and the
EC-HOLD-13 cases that need no jail, and the cases that need a real jail as well where that
report showed the runner can launch one; and the jail lane's recorded dev0 run of the
cases that need a real jail. The merge is head-conditioned on the cleared SHA
(`gh pr merge --match-head-commit <cleared-sha>`, or the train runner's equivalent), after
every required check has passed on that same head; the lane is excluded from auto-merge
and from any queued or deferred merge. A different PR head at merge time invalidates the
clearance, and the head condition enforces that. Because the lane is never on `main` without the clearance, `main` stays
releasable at every tag, every PyPI publication and every dotfiles nightly consumer is
covered, and a deployment that consumes `main` directly is covered by the same gate; no
pre-tag check is needed. The clearance is recorded in the engagement plan and ledger and
linked from the PR.

If a canonical key would change, the lane stops (it is outside this amendment). Should a
later amendment admit such a change, it would also need:

- **O4 — jail requalification (owner-gated)** covering every affected host, including the
  dotfiles nightly consumers, before the change merges. The harness requalifies a jail by
  itself at first use (`seat_jail_autoqualify`), so installation is the trigger; the owner
  is asked first. A rollback that changes a canonical key again is under the same rule. No
  code lane runs it.

**If the jail feasibility lane fails (historical STOP contingency).** This paragraph was
written for the first design. Its terms were: once the coordinator has recorded the failed
probe and the owner has accepted the gap, the cache lane and the REQUAL early slice follow
the core lane, `routes.jailed` stays `"not_covered"`, and the phase closes on the delivered
scope with EC-HOLD-13 and EC-HOLD-14 recorded as **unmet** and G-REL not applicable; if the
owner instead calls for a new amendment, those lanes still proceed and the phase stays
open for the jailed route. What happened: the first feasibility lane reported STOP, the
owner called for a new amendment, and the second feasibility lane reported GO, observed
(Assumption 5). The gap-accepted closeout therefore does not apply to this phase as
amended.

**Not part of this phase.** Ordinary jailed launches stay outside HOLD and keep the
existing path bind. Any design that gives them an admitted-image guarantee is separate
work, with its own feasibility evidence.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md` (self-qualification, hold), `docs/advisor-board-capabilities-card.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_hold.py`, `phase-loop-runtime/tests/test_agy_hold_cache.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 5 — Per-instantiation preflight and recovery (REQUAL)

**Objective**

Qualification survives runtime upgrades while the QCI is unchanged, requalifies
automatically at every instantiation point, and every refusal is visible (goal b).

**Exit criteria**

- [ ] EC-REQUAL-1 — `phase-loop agy-qualification preflight --route seat|executor|canary` admits or refuses with a typed code, at most once per (store, route QCI, image); `budget_exhausted` and `download_cap_reached` do not consume that cap.
- [ ] EC-REQUAL-2 — Runner start runs the preflight when a lane executor is `gemini`, and a refusal stops the lane before launch, naming the code.
- [ ] EC-REQUAL-3 — A Gemini seat refused at preflight is `MODE_DEGRADED` with its code and fix line in the board report and president input, and is never absent or reported as an `unknown failure`.
- [ ] EC-REQUAL-4 — The local `qualified` key is `seat_qci()`, unchanged at `agy_validator_v1`; an upgrade with an unchanged QCI keeps entries, and a QCI change requalifies at the next preflight for any stable release.
- [ ] EC-REQUAL-5 — `repeated_transient` failed entries expire after 24 h, and `violation` entries persist until cleared.
- [ ] EC-REQUAL-6 — A near-expiry login in `seat_profile` waits and renews through `_await_gemini_login` → `_refresh_gemini_credential`, and the doctor's auth hint names the runtime token path.
- [ ] EC-REQUAL-7 — TEAMHOST §5 is repinned to list the runner and canary preflight call sites and to name `seat_qci()` as the `qualified` key, equal to `agy_profile_digest()` at `agy_validator_v1`; falsified by a §5 that still names `agy_profile_digest` as the key, or by a validator bump that leaves §5's key description wrong.
- [ ] EC-REQUAL-8 — The doctor's Gemini row names a hold candidate, its state and the route coverage (AGYFRESH §2.6, early slice), and never reports it as in use.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Store and CLI** (`agy_qualification.py`): the preflight CLI, retryable handling, the
  key, failed classes and the hint.
- **Board, seat and doctor surfaces:** `panel_invoker.py` and `doctor.py`.
- **Runner hook:** `runner.py`.

The docs lane owns the TEAMHOST §5 repin. EC-REQUAL-3/5/6 do not need PROVFWD, so they may
be planned and landed as an early first slice if the owner wants the fastest route to the
per-instantiation preflight. Gated on EXT-1916.

AGYFRESH: the early slice now carries EC-REQUAL-5 and EC-REQUAL-8 and lands after HOLD, as
the next writer of `agy_qualification.py`; it needs HOLD but not PROVFWD. The rest of REQUAL
needs both.

The hint, the fetch ledger and the retryable release landed with PROVFWD; REQUAL's preflight
inherits them.

**Non-goals**

Executor and canary admission tiers (EXECADMIT).

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/doctor.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- `plans/seats-teamhost-contract.md`

**Depends on**

- PROVFWD
- HOLD

**Produces**

- IF-0-REQUAL-1 — The preflight CLI and hooks, retryable handling, the refusal surface, failed classes and the §5 repin (AGYROLL §5).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `plans/seats-teamhost-contract.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_self_qualification.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 6 — Executor and canary admission (EXECADMIT)

**Objective**

The executor and the canary execute the admitted memfd of a current release, admitted under
named custody tiers (goal c, local path).

**Exit criteria**

- [ ] EC-EXECADMIT-1 — `trusted_command`, `admitted_command`, the `EXECUTOR_TRUSTED` role and the executor availability probes admit through `admit_for_executor` using the launch env's PATH, and exec `/proc/self/fd/N` held across the spawn; a path-replacement test shows the admitted bytes run.
- [ ] EC-EXECADMIT-2 — Under R2 (approved), a `shipped` image or a `host_user` image that passes the provenance re-check is admitted, and any other image refuses `agy_executor_image_unqualified`; the forgery boundary is stated in the admission's evidence and docs.
- [ ] EC-EXECADMIT-3 — The canary admits through `admit_for_canary` plus a complete capability matrix that keeps the `stream-json` check, and execs the memfd; no `"1.1.13"` literal gates production code.
- [ ] EC-EXECADMIT-4 — The provenance re-check refuses an image whose upstream asset metadata no longer matches.
- [ ] EC-EXECADMIT-5 — Every refusal is a typed AGYROLL §8 code, and none is sealed.
- [ ] EC-EXECADMIT-6 — Canary capture start runs the canary-route preflight (AGYROLL §5).

**Scope notes**

Decompose into 3 lanes plus docs:
- **Executor:** `agy_integrity.py` and the `launcher.py` call sites.
- **Owned executor sites:** the `panel_invoker.py` `EXECUTOR_TRUSTED` sites and
  `executor_availability.py`.
- **Canary:** `agy_canary_evidence.py`.

The memfd exec fix in EC-EXECADMIT-1 is independent of R2, so it may land first as a
standalone fix. Implements R2 and R3 (approved). Gated on EXT-1916.

**Non-goals**

Executor-specific operations, and other harnesses.

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

- IF-0-EXECADMIT-1 — `admit_for_executor`/`admit_for_canary`, memfd exec and the custody tiers (AGYROLL §4).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_integrity_seat_admission.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 7 — Rolling catalog job and lag rule (ROLLJOB)

**Objective**

A recurring, observable job on `ai` proposes each new upstream release as a signed catalog
member, through Q10/(G) promotion. A breach of the lag bound turns CI red (goals c, d).

**Exit criteria**

- [ ] EC-ROLLJOB-1 — A tick qualifies only the newest non-member release, retries the whole series up to `SERIES_RETRIES`, signs the record and opens a draft `agy-catalog-auto` PR; other members change only when their `qci` differs. Under R9′, 'opens a draft `agy-catalog-auto` PR' reads 'submits the signed record through the INTAKE App; the trusted workflow opens the `agy-catalog-auto` PR'.
- [ ] EC-ROLLJOB-2 — `watch --install-units` and `--check` install and report the timer and the last tick's status line.
- [ ] EC-ROLLJOB-3 — Nightly `--upstream-only` fails under the AGYROLL §6.3 lag rule, and warns inside the bound or while a PR awaits approval. Under R9′ the rule is report-only until ACTIVATE sets `AGY_LAG_ENFORCE`; before that a failing status is recorded and warned, and the run's exit is unaffected by lag.
- [ ] EC-ROLLJOB-4 — Promotion CI runs the base branch's verifier, signer list and merge rule, and reads only the catalog and agy records from the PR head; a PR touching any other path or the policy fails and never auto-merges; under R6 (rejected as written, alternative adopted), a PR merges only with valid job and enrolled-owner signatures, and auto-merges only for a data-only diff once `main` has a non-bypassable ruleset. Under R6′ (D8 = B), for every promotion by the automation, "valid job and enrolled-owner signatures" is replaced by "a valid job signature and a passing base-branch provenance check that re-fetches the asset by tag and re-derives the member digest"; auto-merge stays limited to the diff class in R6′, and any other diff never auto-merges and a repository writer merges it under the `main` ruleset. Under R9′, 'reads only the catalog and agy records from the PR head' reads 'reads only the submitted record, as data', and 'a PR touching any other path or the policy fails' is enforced, for promotion by the automation, by the trusted workflow writing exactly those two paths. The job signature and the diff-class limits bind that path only. Separately, the required check `agy catalog provenance` reports on every pull request to `main`, passes at once when the catalog is untouched, and otherwise re-derives each added or changed member from upstream. 'Never auto-merges' limits this automation; repository writers keep GitHub's ordinary merge and auto-merge authority.
- [ ] EC-ROLLJOB-5 — Aging keeps the newest `CATALOG_KEEP` members or those younger than `CATALOG_MIN_AGE`, and never prunes a `pinned` member (R8).
- [ ] EC-ROLLJOB-6 — An expired login ends the tick with `gemini_login_expired` and a non-zero exit, opens no PR, and makes `watch --check` report `failed: gemini_login_expired`; falsified by an expired-login tick that exits 0, opens a PR, or leaves `--check` reporting `installed`, or by nightly `--upstream-only` passing once the newest release exceeds `LAG_BOUND` while the login stays expired. The final clause, about nightly `--upstream-only` passing, applies once the lag rule is enforced.
- [ ] EC-ROLLJOB-7 — When the lag rule fails, the nightly workflow creates or updates exactly one open issue labelled `agy-lag`, and closes it on the next pass. This applies once the lag rule is enforced; in report-only mode the workflow creates, updates and closes no issue.
- [ ] EC-ROLLJOB-8 — Nightly `--upstream-only` measures the newest upstream archive and member and warns at 80%, fails at 90%, of `MAX_ARCHIVE_BYTES` or `MAX_MEMBER_BYTES`.
- [ ] EC-ROLLJOB-9 — The watch streams each member to a sealed descriptor and holds one member image at a time.

**Scope notes**

Decompose into 3 lanes plus docs:
- **Job:** `agy_watch.py`.
- **Promotion CI:** the verifier's signature, lag and base-policy checks, plus the workflows.
- **Units and install/check:** `docs/ops/agy-upstream-watch/**` and the `watch` flags.

Implements R6 as amended by R6′, R7 and R8, plus D9's hourly tick (AGYROLL §6.2).
EC-ROLLJOB-7..9 come from AGYFRESH §5; EC-ROLLJOB-9 retires the `fetch_member(keep_bytes=True)`
join (AGYFRESH §1.2). Auto-merge stays disabled until a `main` ruleset exists.

Under R9′ the job submits through the INTAKE App and makes no git write; the `main`
workflow builds the catalog change, aging included, and opens the pull request with the
PROMOTION App. The lag rule is report-only until ACTIVATE.

**Non-goals**

A runtime catalog fetch, other harnesses, and enabling auto-merge before a `main` ruleset
exists.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py`
- `.github/workflows/qualified-agy-image.yml`
- `docs/ops/agy-upstream-watch/agy-upstream-watch.service`
- `plans/evidence/agy-allowed-signers`
- `docs/ops/agy-upstream-watch.md`
- `.github/workflows/agy-catalog-intake.yml`
- `.github/workflows/agy-catalog-provenance.yml`
- `ci/agy_catalog_promote.py`
- `config/agy-rollout-attestation.json`
- `phase-loop-runtime/src/phase_loop_runtime/agy_intake.py`

**Depends on**

- RECBIND
- PROVFWD

**Produces**

- IF-0-ROLLJOB-1 — The tick contract, signed records, base-branch promotion, the lag rule and aging (AGYROLL §6).

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/ops/agy-upstream-watch.md`, `docs/releases/outside-agent-release-handoff.md`;
evidence paths: `phase-loop-runtime/tests/test_agy_upstream_advisory.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 8 — Live activation on ai (ACTIVATE)

**Objective**

Once R9's conditions hold, install the job on `ai` and prove end to end that a new upstream
release and a release cut both pass with no hand step. Then close agent-harness#1008.

**Exit criteria**

- [ ] EC-ACTIVATE-1 — Before install, the R9 identity (non-admin, no `workflows` permission) and a non-bypassable `main` ruleset exist; then `watch --check` on `ai` reports `installed`; both are recorded in `plans/evidence/agyroll-activate.json`. Under R9′, 'the R9 identity (non-admin, no `workflows` permission)' reads 'the two R9′ Apps with their stated permissions, each installed on this repository only', and both rulesets are recorded in the attested `config/agy-rollout-attestation.json`.
- [ ] EC-ACTIVATE-2 — The newest stable upstream release at activation reaches `main` through an `agy-catalog-auto` PR with no hand step. This is proven only by a pull request opened after auto-merge was enabled and merged by the PROMOTION App, with no review and no human merge or branch update. A pull request created while auto-merge was off is superseded by a fresh verified one; a hand merge never counts.
- [ ] EC-ACTIVATE-3 — The first release cut after RECBIND passes strict conformance and `--release` with no hand live run.
- [ ] EC-ACTIVATE-4 — An executor lane and a canary capture on `ai` admit a current release, neither 1.3.5 nor 1.1.13, through their preflights, and exec the memfd.
- [ ] EC-ACTIVATE-5 — agent-harness#1008 closes with that evidence linked.

**Scope notes**

Single lane: this is operational work on one host, with owner-approved `ai` access. It
produces runner-stamped operational evidence for EC-ACTIVATE-1..4. RECBIND already deleted
the retired scripts, so nothing is deleted here.

**Non-goals**

New code paths.

**Key files**

- `plans/evidence/agyroll-activate.json`

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
RECBIND ─┬─> RESTORE ──> HOLD ──> REQUAL(early slice) ──────────────────────────────────────┐
         │               │                                                                  │
         │               └─(core lane)──┐                                                   │
         └─> PROVFWD lanes ─────────────┴─> PROVFWD merge ─┬─> REQUAL(rest) ──> EXECADMIT ──┼──> ACTIVATE
                                                           └─> ROLLJOB ─────────────────────┘
```

- AGYFRESH: PROVFWD's resolver and attestation lanes run beside RESTORE and HOLD; its wiring
  lane and its merge follow HOLD's core lane. REQUAL's early slice follows HOLD; the rest of
  REQUAL follows PROVFWD and, as the next writer of `agy_qualification.py`, HOLD.

- ROLLJOB follows PROVFWD for two reasons:
  - it consumes the `attestation`/`second_channel` fields;
  - it is the next writer of `agy_watch.py`.

  After PROVFWD, ROLLJOB runs in parallel with REQUAL → EXECADMIT.
- REQUAL follows PROVFWD for two reasons:
  - its automatic requalification and retryable handling consume IF-0-PROVFWD-1;
  - hosts that are far behind need forward provenance to recover.
- Critical path: RECBIND → PROVFWD → REQUAL → EXECADMIT → ACTIVATE, with HOLD also ahead of
  REQUAL.

## Execution Notes

- **RECBIND is release-critical.** Land it before the 0.7.31 cut.
- **Planning.** Run `/claude-plan-phase specs/phase-plans-agyroll-v1.md <ALIAS> --output plans/phase-plan-v1-agyroll-<ALIAS>.md`.
  - PROVFWD can be planned now.
  - ROLLJOB and REQUAL can be planned after PROVFWD.
  - All rulings are decided (EXT-R met); each phase implements its conditions.
- **Before RECBIND lands**, PROVFWD and REQUAL must not land: `--route-core` would demand a
  live re-record.
- **AGYFRESH planning.** Plan RESTORE and HOLD with the same command. HOLD's F0 lane and
  RESTORE's caps lane can start at once; PROVFWD and ROLLJOB are planned on this amended
  roadmap. Operational steps need their grants: O1 release (D1), O2 restore (D2, after O1),
  O3 R9 prerequisites (D7, setup only).
- **Single-writer files across phases:**
  - `agy_qualification.py`: RECBIND → HOLD → PROVFWD (ledger and call site) → REQUAL.
  - `verify_qualified_agy_image.py`: RECBIND → RESTORE → PROVFWD (`--upstream-only` fetch) → ROLLJOB.
  - `agy_provenance.py`: RECBIND → RESTORE → PROVFWD → ROLLJOB. PROVFWD's first lane lands
    after RESTORE's caps lane merges; it does not wait for EC-RESTORE-1.
  - `agy_watch.py`: RECBIND → PROVFWD → ROLLJOB.
  - `panel_invoker.py`: agent-harness#1916 → HOLD (jail integration) → REQUAL → EXECADMIT.
  - `doctor.py`: REQUAL only (early slice first).
  - `gemini_heartbeat.py`, `agy_integrity.py`: RECBIND → RESTORE → HOLD → EXECADMIT.
  - `plans/seats-teamhost-contract.md`: REQUAL only.
- **In-flight PRs.** agent-harness#1925 and agent-harness#1926 conflict with this roadmap only
  at the `plans/manifest.json` tail; rebase and re-append.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_route_conformance.py tests/test_agy_provenance_forward.py \
  tests/test_agy_self_qualification.py tests/test_agy_integrity_seat_admission.py \
  tests/test_agy_canary_evidence.py tests/test_verify_qualified_agy_route_core.py \
  tests/test_qualified_agy_image_set.py tests/test_agy_upstream_advisory.py \
  tests/test_seat_reference_inventory.py
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider -n 0 \
  tests/test_agy_size_bounds.py tests/test_agy_hold.py tests/test_agy_hold_cache.py \
  tests/test_seats_teamhost_gemini.py tests/test_agy_catalog_data.py tests/test_agy_qci.py
timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract
phase-loop agy-qualification status   # read-only; after HOLD, reports a "hold" object
# CI / Gate A only: strict conformance into a private run directory, then the release gate
RUN_DIR="${RUNNER_TEMP:-$(mktemp -d)}/agy-conformance" && mkdir -p -m 0700 "$RUN_DIR"
AGY_CONFORMANCE_STRICT=1 PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q \
  -p no:cacheprovider tests/test_agy_route_conformance.py --junitxml="$RUN_DIR/conformance.xml"
timeout 600 uv run --locked python scripts/verify_qualified_agy_image.py --release \
  --conformance-report "$RUN_DIR/conformance.xml"
```

Operational evidence comes from ACTIVATE, in `plans/evidence/agyroll-activate.json`, and from
RESTORE, in `plans/evidence/agyfresh-restore.json`, both stamped by the runner.
