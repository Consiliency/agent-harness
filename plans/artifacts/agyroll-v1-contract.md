# AGYROLL v1 contract: admit agy by evidence, not by literal

This is a frozen planning input for `specs/phase-plans-agyroll-v1.md`. Phase plans cite it by
section, for example `AGYROLL §3.2`. Changing this file is a reviewed repin: amend the
roadmap's External Inputs row in the same PR.

Sections tagged `[R<n>]` implement the owner ruling of that number. The owner ruled all
nine on **2026-11-08**, accepting the plan-tier board's recommendations on
agent-harness#1927 as written. The decisions are in the roadmap ("Owner Rulings
(2026-11-08)") and are recorded on agent-harness#1008. The ruling conditions written into
those sections are binding: a lane that cannot meet a condition stops and routes an
amendment.

## 0. Vocabulary

- **Image.** The bytes of the `antigravity` member that `agy` resolves to on a host.
- **Consumer route.**
  - `seat`: the heartbeat, bounded and jailed review seats.
  - `executor`: `agy_integrity.trusted_command`/`admitted_command`, the `EXECUTOR_TRUSTED`
    role, the `executor_availability` probes and the convergence adapters.
  - `canary`: `agy_canary_evidence.probe_capability` and the capture launch.
- **QCI (qualification contract identity).** The digest that decides whether qualification
  evidence still applies. §2 defines it.
- **Custody tier.** Where an admission fact is recorded, and who can write it (§4).

## 1. Provenance: any stable release, found by forward lookup (goal a) [R4, R5]

**1.1 What stays.** Everything in `agy_provenance` stays except the recency window:
- the pinned transport: no proxy, no credentials, the compiled-in trust store, and redirects
  only to https hosts in `REDIRECT_HOSTS`;
- the exact name, URL and `sha256:` digest checks in `release_asset`;
- `read_member`'s rule of one regular `antigravity` member, with its caps and the
  archive-digest equality check;
- the codes `gemini_heartbeat_provenance_unavailable|unverified|platform_unsupported`, with
  their current meanings.

**1.2 Resolver.** `find_provenance` gains `hint: str | None = None` and
`budget: int = DOWNLOAD_BUDGET`, and loses `window`. `ProvenanceError` gains a `reason`
attribute, and its `str()` stays the code.

- **Hint source.** The hint is the first component of `os.path.realpath(subject_path)` that
  matches `^(\d+\.\d+\.\d+)(?:[-+].*)?$`. For example,
  `/opt/consiliency/operational-clis/agy/1.5.3-e363e1b1…/agy` gives `1.5.3`. If no component
  matches, there is no hint.
  - The hint is never obtained by executing the image, reading its bytes, or parsing
    `--version`.
  - It only orders candidates. Admission still requires a member-digest match.
- **Candidate order.** First the hint. Then every other stable release in the paginated
  listing (`per_page=100`, `MAX_LISTED = 300`), newest first.
- **Per-call budget.** A candidate whose asset digest has a `member_cache` entry costs no
  download. Each call fetches at most `budget` uncached archives, with `DOWNLOAD_BUDGET = 2`.
  Each fetch writes `member_cache` before the next candidate is tried, so repeated calls make
  steady progress.
- **Total bound.** Each (store, image) may fetch at most `TOTAL_DOWNLOAD_CAP = 12` uncached
  archives per rolling 24 h. The fetch times ride in the MAC-bound `transient` entry. That
  caps the worst case at 12 × `MAX_ARCHIVE_BYTES` (128 MB), about 1.5 GB per image per day,
  and `member_cache` is shared across images.
- **Retryable outcomes.** When the per-call budget runs out, the reason is `budget_exhausted`.
  When the total bound is reached, the reason is `download_cap_reached`. Both refuse with
  `unverified`.
  - Neither counts toward `MAX_TRANSIENT_ATTEMPTS`.
  - Neither consumes `requalify_once`'s once-per-(store, QCI, image) cap. Like `CANCELLED`
    today, the key is discarded so that the next preflight continues (§5).
- **Effect.** `RECENCY_WINDOW` is no longer an admission criterion. A tampered image costs at
  most `budget` downloads per attempt and `TOTAL_DOWNLOAD_CAP` per day.

**1.3 Attestation and second channel [R5].** As of 2026-11-08 upstream publishes no
signature, checksum file, Sigstore bundle or attestation. The attestations API returns 404
for the 1.3.5 and 1.5.3 linux-x64 digests, and the repository has no workflows.

- **Attestation.** `attestation_status(asset, transport)` queries
  `/repos/google-antigravity/antigravity-cli/attestations/sha256:<digest>`.
  - It records `absent` on a 404 and `present_unverified` when an attestation exists.
  - It never makes an attestation an admission criterion.
  - A malformed response refuses with `unavailable`.
- **Second channel.** This cross-checks the digest against Google's installer manifest
  (SHA-512, unsigned). It runs **only in the catalog job** (§6), never in per-host first use.
  - A mismatch refuses with the new code `agy_provenance_second_channel_mismatch`.
  - An unreachable manifest refuses with `unavailable`.
- **Defaults and storage.** Until PROVFWD lands, both fields default to `not_checked`. The
  `provenance` store entry records `{release_version, asset_sha256, attestation,
  second_channel}`, and its MAC context does not change.

## 2. Qualification contract identity (goals b, d)

**2.1 Seat QCI.** The seat QCI builds on `agy_qualification.agy_profile_digest()` as frozen by
TEAMHOST §5 (`plans/seats-teamhost-contract.md`; maintainer Q8). That digest covers the
profile id, the owned-profile description and `OPERATIONS_CONTRACT`, and excludes
`__version__`, paths and file hashes.

```python
QUALIFICATION_VALIDATOR = "agy_validator_v1"
def seat_qci() -> str:
    if QUALIFICATION_VALIDATOR == "agy_validator_v1":
        return agy_profile_digest()            # identical at v1: no key change, no drop
    return sha256(canonical({"agy_profile_digest": agy_profile_digest(),
                             "validator": QUALIFICATION_VALIDATOR}))
```

- **Key stability.** At `agy_validator_v1`, `seat_qci()` equals `agy_profile_digest()`. So
  binding records to it in RECBIND, and keying local entries on it in REQUAL, changes no
  TEAMHOST §5 key value and drops no host entry. Only a later validator bump changes it.
- **When to bump the validator.** Bump it whenever what "passed" means changes. That covers
  the validator entry points (`validate_records`, `validate_directory`, `_classify_failure`)
  and everything they reach, **transitively**, including
  `panel_invoker.terminal_verdict` and the prompt and stream helpers it uses.
- **Semantic mutation guard (primary).** A fixed corpus of fixture series covers, per pass
  predicate, one passing case and one failing case for each way it can fail. The guard pins
  `{QUALIFICATION_VALIDATOR: sha256(verdict vector)}`. Any mutant that changes a verdict (for
  example, `terminal_verdict` accepting a non-terminal stream) turns the guard red unless the
  literal is bumped.
- **Source-hash table (supplement).** The guard also pins a hash table over the AST call-graph
  closure of the entry points within `phase_loop_runtime`, so an edit that keeps the verdicts
  still asks for a deliberate review.

**2.2 Executor QCI** equals the seat QCI. This gives the executor the same evidence the
catalog has: its records are seat-route only (`route: brokered_subscription_heartbeat_only`).

**2.3 Canary QCI** is `{capture_surface: _CAPABILITY_PROBE_SCHEMA, seat: <seat QCI>}`.

**2.4 Survival rule.** Evidence stays valid for route R while R's QCI is unchanged. A runtime
upgrade with the same QCI keeps both the local entries and the catalog records. A QCI change
invalidates them, and they requalify automatically: §5 handles hosts and §6 the catalog.

## 3. Records and catalog (goals c, d) [R1]

**3.1 Catalog leaves the route core.** `gemini_heartbeat.QUALIFIED_IMAGES` is loaded at
import from package data at `phase_loop_runtime/data/agy_catalog.json`, using the closed
schema `qualified_agy_catalog.v3`:

```json
{"schema": "qualified_agy_catalog.v3",
 "routes": {"linux-x64": [{"release_version": "<x.y.z>", "image_sha256": "<hex64>",
   "help_sha256": "<hex64>", "asset_sha256": "<hex64>", "qci": "<hex64>",
   "published_at": "<RFC 3339>", "pinned": false,
   "record": "agy-<x.y.z>-linux-x64-qualification.json"}]}}
```

- R3 is approved, so the canary does not depend on catalog-listed capability digests. The
  schema therefore has no `capture_surface_sha256` field.
- `pinned` is set only by a human PR. Aging never prunes a pinned member (§6.1, R8).
- **Runtime loader.** It is strict and makes no network calls. If the file is missing or
  malformed, the runtime sees an empty catalog, which is fail-closed: local qualification or
  a refusal.
- **Verifier.** It parses the same schema strictly and **fails** on a malformed or empty
  catalog (§3.3).
- `plans/evidence/qualified-provider-images.json` is deleted. Records stay under
  `plans/evidence/`.
- **Effect.** Adding a member no longer edits a route-core file.

**3.2 Record v2** (`agy_redacted_qualification_summary.v2`) keeps the v1 fields except
`source_sha256`, and adds:
- `qci`;
- `qualified_under` (`__version__`, informational);
- `upstream: {asset_sha256, release_url, attestation, second_channel}`;
- `signatures`, a list of SSH signatures (`ssh-keygen -Y sign`, namespace
  `agy-qualification`) over the canonical record minus `signatures`.

The list is empty in RECBIND. ROLLJOB requires it on promotion (§6.1). No version is pinned.

**3.3 Verifier modes** (`scripts/verify_qualified_agy_image.py`):

| Mode | Runs | Requires |
|---|---|---|
| `--contract` | **every** PR and push, with no path filter (the QCI reads `panel_invoker.py`), plus nightly | A strict catalog parse that rejects an empty catalog. Each member has exactly one v2 record; unlisted records are ignored. Each record's `qci` equals the tree's `seat_qci()`. Failure prints `requalify: <members>`. |
| `--release` | `publish-pypi.yml`, before the build | `--contract`. A **strict** conformance report (§3.4) from the same commit. Every member's asset re-verified by tag. |
| `--upstream-only` | nightly | As today, plus the lag rule (§6.3). |

**What R1 removes.** It removes the full pin, which is `--source-only`, `agy_full_pin_scope.sh`
and the `publish-pypi.yml` step from agent-harness#1032. It also removes the **per-PR
route-core gate** `--route-core` from the agent-harness#1029 ruling of 2026-09-24
(`qualified-agy-image.yml:48-53`). `--contract` and the conformance suite replace both.

R1 is approved (2026-11-08) on three conditions:
- conformance cannot pass by skipping (§3.4, strict mode);
- the semantic validator guard covers transitive predicates (§2.1);
- both removed gates are named in this section.

**3.4 Route conformance suite** (hermetic, no provider).
- **What it runs.** The production driver: `qualify_image` → worker → `run_operation` →
  validator, for `completion`, `cancel` and `owner-loss`.
- **Stand-in.** A stand-in executable emits the stream-json surface implied by the redacted
  record shape. The SL-2.1 probe used a static binary built from fixture source with one mode
  per control. Raw receipts are never used.
- **Amendment A1 (2026-11-08).** RECBIND's executor stopped at SL-2.1. It had run the real
  driver under the real bwrap profile, with compiled stand-ins and nothing mocked. Results:
  - the conforming stand-in passed all three operations, so the driver is hermetic;
  - "no terminal event" did not pass (the outcome was `transient` at `completion`);
  - a stand-in that handles SIGTERM, one that ignores SIGTERM/SIGINT/SIGHUP, and an orphaned
    `setsid` child that ignores SIGTERM all **passed**.

  They passed because the production driver, not the provider, enforces cancel and cleanup:
  - the broker returns `cancelled` itself;
  - it signals the process group with TERM then KILL, and kills pid 1;
  - `--die-with-parent` namespace teardown kills orphans.

  The coordinator ruled this a test-design correction consistent with R1's intent; the
  owner's R1–R9 rulings are unchanged. The controls are therefore split by who enforces the
  predicate.
- **Negative controls** (a provider *can* trip them; each must **not** pass):
  - `neg_no_terminal_event`: the stand-in never emits a terminal event. Measured outcome:
    `transient` at `completion`. The test pins that outcome.
  - `neg_no_progress_event` *(provisional)*: the stand-in answers without any progress event,
    so cancel never lands before the answer, and `cancel` must not pass.
  - `neg_unregistered_helper` *(provisional)*: the stand-in's child execs an executable
    outside the registered helper policy, and the helper check must reject it (expected
    `failed`).
- **Measuring the provisional controls.** The two provisional controls are measured in SL-2.1
  before they are frozen. Each runs 5 consecutive times and must give the same non-passing
  outcome every time; the test then pins that outcome. If either control passes or flaps, the
  stop rule applies: the lane stops and reports back for an amendment. It never weakens the
  control.
- **Driver-enforcement controls** (positive; each must **pass**). These prove the driver
  enforces cancel and cleanup without trusting the provider:
  - `pos_ignores_cancel`: the stand-in ignores SIGTERM/SIGINT/SIGHUP. `cancel` passes because
    the broker reports `cancelled` and kills the process group with TERM then KILL.
  - `pos_orphaned_child`: the stand-in leaves a `setsid` child that ignores SIGTERM.
    `owner-loss` passes because namespace teardown with `--die-with-parent` kills it.
- **Obligations.** `CONFORMANCE_OBLIGATIONS` declares **eight** ids:
  - `op_completion`, `op_cancel` and `op_owner_loss`, run with the conforming stand-in;
  - the three negative controls above;
  - the two driver-enforcement controls above.

  In the JUnit sense, an obligation "passes" when its test confirms the expected outcome.
- **Strict mode** (`AGY_CONFORMANCE_STRICT=1`, which release CI sets):
  - A missing bwrap or user namespaces is a failure, not a skip.
  - `--release` reads the suite's JUnit report and requires every obligation id to be present
    and passed, exactly once, with zero skipped, xfailed or errored cases.
  - A missing report, a partial report or an uncollected obligation fails `--release`.
  - Release CI writes the report into a private run directory (`$RUNNER_TEMP`, or a
    `mktemp -d` directory locally), never to a fixed `/tmp` path.
- **Outside release CI.** Local and ordinary runs may skip, with a reason.
- **Never mocked.** If the production driver cannot run hermetically, the lane stops and
  routes a roadmap amendment. It never mocks the driver.

**3.5 Migrating v1 records.** `scripts/convert_agy_record_v2.py` handles each member:
1. It finds the **record commit**. That is the newest commit in
   `git log -- plans/evidence/<record>` whose tree's package sources match the record's
   `source_sha256` exactly.
2. It requires two things:
   - `agy_profile_digest(record commit) == agy_profile_digest(head)`. A v1 record commit has
     no `seat_qci()`, and the two digests are equal at `agy_validator_v1`;
   - an equal source-hash closure table for the validator (§2.1) at both commits.
3. It writes the v2 record with no signatures.

**Stop task.** If no record commit exists, or the QCI or the validator closure differs, the
lane stops and reports. That member needs one owner-approved live requalification, and the
roadmap is amended. Nothing converts by assumption.

## 4. Custody tiers and per-route admission (goal c) [R2, R3]

| Tier | Written by | Writable by | Accepted for |
|---|---|---|---|
| `shipped` | merged PR → package data (§3.1) | repo maintainers, under §6.1's merge rule | seat, executor, canary |
| `host_user` | `agy_qualification.Store` (HMAC, 0700/0600, euid) | **any process running as that euid** | seat (today); executor [R2]; canary [R3] |

- **No root tier.** There is no root-owned qualification tier. TEAMHOST §7's root-written
  pins are seat *authority* pins, not agy qualification, and a root tier is a non-goal.
- **Forgery boundary [R2].** The store's HMAC key sits in the same euid's store, so any
  same-euid process can forge a `host_user` entry. Accepting `host_user` for the executor
  accepts the euid as the trust boundary. Seats already accept it, and such a process can
  already replace the user's tools.
- **Provenance re-check.** A non-`shipped` admission also requires a `provenance` entry. The
  executor and canary re-run `release_by_tag` and `release_asset` once per process per image.
  That is metadata only. It catches upstream withdrawal or re-digesting (refusing
  `unverified`), **not** local forgery.
- **New functions** in `agy_integrity`:
  - `admit_for_executor(path, env, *, evidence=None) -> VerifiedImage`
  - `admit_for_canary(path, env, *, evidence=None) -> VerifiedImage`

  Both are lookup-only, with `admit_for_seat`'s typed pass-through.
- **Executor execs the admitted memfd.** Today `trusted_command` returns a path and closes
  the memfd (`agy_integrity.py:112-122`), and `launcher.launch` later execs that path
  (`launcher.py:2777`). That breaks the agent-harness#1076 I1 invariant even before R2.
  - `trusted_command` becomes a context manager on the `admitted_command` pattern: it yields
    `["/proc/self/fd/N", *argv[1:]]` plus `pass_fds`, held open across the spawn.
  - Both take the launch env's PATH, replacing the import-time `_PROVIDER_SEARCH_PATH`.
  - A path-replacement test swaps the file between admission and exec. The admitted bytes
    must run.
- **R2 approved (2026-11-08)** on two conditions: the memfd exec above, and the forgery
  boundary stated above. `admit_for_executor` admits `shipped` and `host_user` images that
  pass the provenance re-check. It refuses others with `agy_executor_image_unqualified`.
- **Canary (corrected).** The production canary never calls `check()`. It admits through
  `_trusted_agy_runtime`, which applies fixed paths and mode checks and records a digest, plus
  the **self-reported** `agy --version == "1.1.13"`. Its digest is checked against nothing,
  and it executes the path. R3 therefore **strengthens** admission:
  - the `"1.1.13"` literals in `_sealed_agy_runtime`, `probe_capability` and
    `_require_complete_capability_probe` become `admit_for_canary`, plus a complete
    capability matrix under the canary QCI;
  - the `stream-json` check in that matrix stays;
  - `_trusted_agy_runtime` keeps its path and mode checks;
  - the canary executes the admitted memfd;
  - the production-unreachable branch `_trusted_provider_runtime("gemini")` is deleted.
- **R3 approved (2026-11-08)** on two conditions: memfd exec, and the kept `stream-json`
  check.

## 5. Per-instantiation preflight and recovery (goal b)

The command is:

```
phase-loop agy-qualification preflight [--route seat|executor|canary] [--json]
```

It runs `ensure_admitted` for the agy on the launch env's PATH, plus the route's extra probe.

**When it runs automatically:**
- at board pre-composition, through the existing `requalify_once`;
- at runner start, when any lane's executor is `gemini` (`runner.py`, REQUAL);
- at canary capture start (`agy_canary_evidence.py`, EXECADMIT).

The last two are new call sites. TEAMHOST §5 freezes `requalify_once` to two call sites, so
**REQUAL repins TEAMHOST §5.** The repin lists both new call sites and names `seat_qci()`
as the `qualified` key, instead of `agy_profile_digest`. Its value is unchanged at
`agy_validator_v1` (§2.1), so no entry drops, and §5 stays correct after the first validator
bump.

**Cost.** It runs at most once per (store, route QCI, image). The retryable provenance
outcomes from §1.2 do not count toward that limit. Spawn stays lookup-only.

**Visibility.**
- **Board.** A Gemini seat that is refused shows as `MODE_DEGRADED` (Q6), with its code and a
  fix line. It is never absent and never reported as "unknown failure" (agent-harness#1420).
- **Runner.** It refuses the lane before launch.
- **Doctor.** It shows a row with the code and the next command.

**Failed entries.** A `failed` entry gains `class: violation|repeated_transient`.
- `repeated_transient` expires after 24 h or on any key change, which retires the
  agent-harness#1158 trap.
- `violation` lasts until `agy-qualification clear`.

**Login renewal.** One renewal path serves both seats and the job (R7):
`panel_invoker._await_gemini_login` followed by `_refresh_gemini_credential(home, image)`.
- That is the unjailed, non-seat `models` run with `HOME` set to the owner home and
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/dev/null`. It writes
  `~/.gemini/antigravity-cli/antigravity-oauth-token` in the owner home.
- Seat copies stay access-only (agent-harness#1222).
- In `seat_profile`, a login near expiry now waits on that path instead of refusing
  (agent-harness#1407, EC-REQUAL-6).
- The doctor's `_AUTH_HINTS` adds the token path.
- `advisor_board/CONTRACTS.md` "Runtime identity (D2)" is rewritten to TEAMHOST §5.

## 6. Rolling catalog and the recurring job (goals c, d) [R6–R9]

### 6.1 The job

`phase-loop agy-qualification watch` (`agy_watch`) changes in these ways:

- **Scope.** One tick qualifies only the newest stable non-member release. It requalifies an
  existing member only when that member's `qci` differs from `main`'s.
- **Retries.** It retries the whole series up to `SERIES_RETRIES = 3` per tick, because
  Gemini non-conformance is intermittent (agent-harness#1008). An observed `violation` stops
  the tick.
- **Promotion path.** This keeps Q10's draft promotion PR, its signer quorum and its
  publisher digest, and (G)'s base-branch rule
  (`.consiliency/plans/detailed-lkg-cli-qualification-1602-20261014-0359.md`). The only
  thing R6 replaces is Q10/(G)'s "a maintainer merges", and only conditionally (see Merge
  below):
  1. The job signs the record with its enrolled key and opens a **draft** PR labelled
     `agy-catalog-auto`.
  2. CI checks out the **base** branch and runs the base's verifier, `agy-allowed-signers`
     and merge rule. It reads only `data/agy_catalog.json` and
     `plans/evidence/agy-*-linux-x64-qualification.json` from the PR head, as data.
  3. A catalog PR that changes the signer list, the verifier, the merge-rule workflow or any
     path outside those two fails the promotion check, and never auto-merges.
  4. On a pass, CI marks the PR ready.
- **Merge [R6].** The owner **rejected** "one job signature plus green CI auto-merges" as
  written (2026-11-08) and adopted the board's alternative:
  - **Base-branch policy.** The signer list, verifier and merge rule come from the base
    branch (steps 2 and 3).
  - **Two distinct signers (Q10).** The job's key and an **enrolled owner key**, both listed
    in the base branch's `agy-allowed-signers`. A PR without both valid signatures never
    merges.
  - **Auto-merge (conditional supersession of Q10/(G)'s "a maintainer merges").** Once
    `main` has a non-bypassable ruleset, a data-only diff (`data/agy_catalog.json` plus agy
    records) auto-merges after both signatures verify. Every other diff, and every PR opened
    before that ruleset exists, is still merged by a maintainer.
  - **Today `main` has none.** The only ruleset covers `conform-evidence/*` tags. Classic
    protection requires status checks but no review, `enforce_admins` is false, and the
    `gate` check is self-certifiable (`.github/CODEOWNERS:5-9`).
- **Aging [R8].** Approved 2026-11-08. A member is kept while it is among the newest
  `CATALOG_KEEP = 3` or was published less than `CATALOG_MIN_AGE = 14 d` ago. A `pinned`
  member is never pruned, and pruning happens in the same PR. **Q11 is superseded for the agy
  route only.** Q11 had already superseded the 2026-10-08 Q5. Under R1 the cut re-runs
  nothing, so aging bounds the agy catalog instead of requalification. Other harnesses keep
  Q11.
- **Unchanged.** Idempotence, oid agreement, push-destination checks and create-only writes
  stay as in `docs/ops/agy-upstream-watch.md`.

### 6.2 Install and observe

- **Units.** `watch --install-units` writes and enables the existing `.service`/`.timer` (four
  ticks a day).
- **Status.** `--check` reports `installed`, `stale` or `absent`, plus the last tick's status
  line.
- **Login [R7].** Approved 2026-11-08 on three conditions:
  - The job renews only through the named path `_await_gemini_login` →
    `_refresh_gemini_credential` (§5), outside any seat.
  - The refresh token stays in the owner home and never enters a seat (agent-harness#1222).
  - **Expiry turns red directly.** On expiry the tick prints `gemini_login_expired` and
    exits non-zero, so the systemd unit enters `failed`. `watch --check` then reports
    `failed: gemini_login_expired` at once. No PR is opened. CI turns red through the lag
    rule (§6.3) once `L` passes `LAG_BOUND` with the login still expired.
- **Identity [R9].** Approved 2026-11-08 on three conditions, all in place before ACTIVATE:
  - The job uses a non-admin GitHub App or machine user. It is scoped to this repository
    only, has contents and pull-requests write, and has no `workflows` permission.
  - `main` has a non-bypassable ruleset.
  - agent-harness#1138 is closed by that setup.

### 6.3 Lag rule (bounded, and red)

Let `L` be the newest stable upstream release.

- **Fail.** Nightly `--upstream-only` fails when `L` is more than `LAG_BOUND = 48 h` old,
  `L` is not a member, and no open `agy-catalog-auto` PR for `L` exists.
- **Warn.** It warns when such a PR has been open longer than `LAG_BOUND`, naming the awaited
  owner signature or merge. It also warns inside the bound.

Expected lag by consumer:
- to `main`: one tick, plus the series, plus CI, plus the merge rule;
- to catalog-only consumers: the next release;
- to hosts that qualify locally: none.

### 6.4 Release cut

R1 is approved, so a cut needs no live run. Strict conformance plus `--release` (§3.3) gate
the cut, and the job does not watch release PRs.

## 7. Non-goals

- executor-specific operations;
- non-linux-x64-glibc platforms;
- a runtime catalog fetch;
- a root-owned qualification tier;
- seat-jail, egress or `SEALED_FALLBACK_CODES` changes;
- `cli_qualification` adapters for other harnesses (agent-harness#1333 PR3–PR7,
  agent-harness#1602 L1–L5).

## 8. Codes

- **New codes:** `agy_provenance_second_channel_mismatch`, `agy_executor_image_unqualified`,
  `agy_canary_image_unqualified`.
- **New reasons:** `budget_exhausted` and `download_cap_reached`.
- **New failed classes:** `violation` and `repeated_transient`.
- All other codes keep their meaning, and none may reach a sealed fallback.
