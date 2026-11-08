# AGYROLL v1 contract: admit agy by evidence, not by literal

Frozen planning input for `specs/phase-plans-agyroll-v1.md`. Phase plans cite it by
section (`AGYROLL §3.2`). A change to this file is a reviewed repin: amend the roadmap's
External Inputs row in the same PR. Sections tagged `[R<n>]` depend on the owner ruling
of that number in the roadmap. Until R<n> is ruled, the lane ships only the part marked
"default".

## 0. Vocabulary

- **Image.** The bytes of the `antigravity` member that `agy` resolves to on a host.
- **Consumer route.** One of three kinds of agy launch:
  - `seat`: heartbeat, bounded and jailed review seats.
  - `executor`: `agy_integrity.trusted_command` and `admitted_command`, the
    `EXECUTOR_TRUSTED` role, `executor_availability` probes and the convergence adapters.
  - `canary`: `agy_canary_evidence.probe_capability` and the capture launch.
- **QCI (qualification contract identity).** The digest that decides whether
  qualification evidence still applies. It is defined per route in §2.
- **Custody tier.** Where an admission fact is recorded and who can write it (§4).

## 1. Provenance: any stable release, by forward lookup (goal a)

**1.1 What stays.** Everything in `agy_provenance` except the recency window:
- The pinned transport: no proxy, no credentials, the compiled-in trust store, and
  https-only redirects to `REDIRECT_HOSTS`.
- The exact asset name, URL and `sha256:` digest checks in `release_asset`.
- The rule in `read_member` that there is exactly one regular `antigravity` member, plus
  its caps and the archive-digest equality.
- The codes `gemini_heartbeat_provenance_unavailable|unverified|platform_unsupported` keep
  their meaning.

**1.2 Resolver.** `find_provenance` gains `hint: str | None = None` and
`budget: int = DOWNLOAD_BUDGET` and loses `window`. Its other parameters are unchanged.
- **Candidate order:**
  1. `hint`, an untrusted `MAJOR.MINOR.PATCH` taken from the resolved subject path. It only
     orders candidates.
  2. Every other stable release in the paginated listing (`per_page=100`,
     `MAX_LISTED = 300`), newest first.
- **Download budget.** A candidate whose asset digest already has a `member_cache` entry
  costs no download. At most `budget` uncached archives are fetched per call, with
  `DOWNLOAD_BUDGET = 2`.
- **Progress.** Each fetch writes `member_cache` before the next candidate is tried. Repeat
  calls therefore progress monotonically and cover the whole listing.
- **Budget exhausted.** If the budget runs out before a match, the call refuses
  `unverified`, and the store records the reason `budget_exhausted` in the transient entry
  without counting it as a failure.
- **Cost bound.** `RECENCY_WINDOW` is removed as an admission criterion: a tampered image
  now costs at most `budget` downloads per attempt. That is the bound D4 wanted.

**1.3 Second channel and attestation [R5].** As of 2026-11-08, upstream publishes no
signature, checksum file, Sigstore bundle or GitHub attestation: the attestations API
returns 404 for the 1.3.5 and 1.5.3 linux-x64 digests, and the upstream repository has no
workflows. Provenance therefore rests on GitHub's per-asset digest over the pinned transport.
- **Default.** `attestation_status(asset, transport)` queries
  `/repos/google-antigravity/antigravity-cli/attestations/sha256:<digest>` and records:
  - `absent` on 404;
  - `present_unverified` when one exists. This is a recorded fact, not an admission
    criterion, until R5 picks a verifier.
  - Any malformed response refuses `unavailable`.
- **Option (R5).** Cross-check the digest in Google's installer manifest (SHA-512, unsigned,
  served from infrastructure other than GitHub's).
  - A mismatch refuses with the new code `agy_provenance_second_channel_mismatch`.
  - An unreachable manifest refuses `unavailable`.
- **Stored fields.** The `provenance` store entry records `{release_version, asset_sha256,
  attestation, second_channel}`. Its MAC context is unchanged.

## 2. Qualification contract identity (goals b, d)

**2.1 Seat QCI.** This is `agy_qualification.agy_profile_digest()`, as frozen by TEAMHOST
§5 (`plans/seats-teamhost-contract.md`; maintainer Q8). It covers:
- the profile id;
- the owned-profile description;
- `OPERATIONS_CONTRACT`.

It already excludes `__version__`, file paths and file hashes.

AGYROLL wraps it:

```python
seat_qci() = sha256(canonical({"agy_profile_digest": agy_profile_digest(),
                               "validator": QUALIFICATION_VALIDATOR}))
QUALIFICATION_VALIDATOR = "agy_validator_v1"
```

- **The validator literal.** It is bumped whenever `validate_records`, `validate_directory`,
  `_classify_failure` or a pass predicate changes what "passed" means. A mutation test pins
  the rule: a validator that admits a previously failing fixture series turns red unless the
  literal changes.
- **RECBIND** binds catalog records to `seat_qci()`. `agy_profile_digest()` keeps its value,
  so local store entries do not drop.
- **REQUAL** switches the local `qualified` key from `agy_profile_digest` to `seat_qci()`.
  This is a one-time requalify. It lands only after PROVFWD, so every host can requalify
  whatever release it runs. Landing it earlier would recreate agent-harness#1420 for hosts
  outside the old window.

**2.2 Executor QCI.** The executor QCI is the seat QCI. This gives evidence parity with the
shipped catalog, whose records are seat-route only (`route:
brokered_subscription_heartbeat_only`).

**2.3 Canary QCI.** `{capture_surface: _CAPABILITY_PROBE_SCHEMA, seat: <seat QCI>}`.

**2.4 Survival rule.** Evidence for an image is valid for route R while R's QCI is
unchanged:
- A runtime upgrade that leaves the QCI unchanged keeps both local entries and catalog
  records.
- A QCI change invalidates them, and they requalify automatically (§5 for hosts, §6 for
  the catalog).

## 3. Records and catalog (goals c, d)

**3.1 Catalog leaves the route core.** `gemini_heartbeat.QUALIFIED_IMAGES` is loaded at
import from the package-data file `phase_loop_runtime/data/agy_catalog.json`, schema
`qualified_agy_catalog.v3`:

```json
{"schema": "qualified_agy_catalog.v3",
 "routes": {"linux-x64": [{"release_version": "<x.y.z>", "image_sha256": "<hex64>",
   "help_sha256": "<hex64>", "asset_sha256": "<hex64>", "qci": "<hex64>",
   "record": "agy-<x.y.z>-linux-x64-qualification.json"}]}}
```

- **Loader.** Strict, closed schema, no network. A missing or malformed file gives an empty
  catalog, so every route falls back to local qualification or refuses (fail-closed).
- **Old paths.** `plans/evidence/qualified-provider-images.json` is retired (deleted). The
  package-data file is the only catalog. Records stay under `plans/evidence/`.
- **Effect.** Adding a member no longer edits a route-core file, so it no longer invalidates
  every other record (`agy_watch` step 4 today).

**3.2 Record v2.** The schema is `agy_redacted_qualification_summary.v2`. It keeps the v1
fields except `source_sha256`, and adds:
- `qci` (§2.1);
- `qualified_under`: the harness `__version__`, informational only;
- `upstream`: `{asset_sha256, release_url, attestation, second_channel}`;
- `signature`: optional. When present, it is an SSH signature (`ssh-keygen -Y sign`,
  namespace `agy-qualification`) over the canonical record minus `signature`, made by the
  qualifying host's key (maintainer Q10). ROLLJOB makes it required on any PR that adds or
  requalifies a record. Unsigned members are reported nightly until they age out (§6.1).
  No version is pinned.

**3.3 Verifier modes.** In `scripts/verify_qualified_agy_image.py`:

| Mode | Runs | Requires |
|---|---|---|
| `--contract` | every PR touching the route; nightly | Each catalog member has exactly one v2 record (unlisted records are ignored), each record's `qci` equals the tree's seat QCI, and signatures, where present, verify against `plans/evidence/agy-allowed-signers`. Failure prints `requalify: <members>`. |
| `--release` | `publish-pypi.yml`, before the build | `--contract`, plus the conformance suite (§3.4) on the same commit, plus every member's asset re-verified by tag. |
| `--upstream-only` | nightly | As today, plus the lag rule (§6.3). |

`--source-only`, `--route-core` and `agy_full_pin_scope.sh` retire when R1 rules as
recommended. If R1 keeps the full pin, they stay, and §6.4 applies.

**3.4 Route conformance suite.** The suite is hermetic and needs no provider.
- **What it drives.** The production driver path: `qualify_image` → worker →
  `run_operation` → validator, for `completion`, `cancel` and `owner-loss`.
- **Stand-in image.** A scripted executable that emits the stream-json surface implied by
  the redacted record shape. It never uses a raw receipt.
- **What it proves.** Harness-side drift still meets every pass predicate. That is what the
  full source pin stood in for: agent-harness#1029 says "modules they import can change its
  behaviour".
- **Negative controls.** There is one scripted mutant per predicate: no terminal event, an
  ignored cancel, an orphaned child. Each must fail its operation.
- **Prerequisites.** The suite runs where `publish-pypi.yml` already installs bubblewrap and
  enables user namespaces. If the production driver cannot run hermetically, the lane stops
  and routes a roadmap amendment. It never substitutes a mock of the driver.

**3.5 Migrating v1 records.** `scripts/convert_agy_record_v2.py` runs on the base tree.
- It requires that the v1 `source_sha256` equals that tree's sources exactly. This proves the
  record was produced there.
- It computes the seat QCI and writes the v2 record without a signature.
- A test asserts QCI(base) == QCI(head) for that PR, so no live run is needed.

## 4. Custody tiers and per-route admission (goal c)

| Tier | Written by | Writable by | Accepted for |
|---|---|---|---|
| `shipped` | merged PR → package data (§3.1) | repo maintainers | seat, executor, canary |
| `host_root` | TEAMHOST root release updater (`plans/seats-teamhost-contract.md` §7), only for a managed release it built and admitted | root | seat, executor, canary |
| `host_user` | `agy_qualification.Store` (HMAC, 0700/0600, euid) | that euid | seat (today); executor [R2]; canary [R3] |

**Admission rules.**
- **Provenance re-check.** A non-`shipped` admission always also requires a `provenance`
  entry. The executor and canary re-run `release_by_tag` and `release_asset` on it once per
  process per image. That is metadata only, with no download, and an asset that is withdrawn
  or re-digested upstream refuses `unverified`.
- **New functions in `agy_integrity`:**
  - `admit_for_executor(path, env, *, evidence=None) -> VerifiedImage`
  - `admit_for_canary(path, env, *, evidence=None) -> VerifiedImage`

  Both are lookup-only at spawn, with `admit_for_seat`'s typed pass-through.
- **Executor call sites.** `trusted_command` and `admitted_command` take the launch env and
  call `admit_for_executor`. The import-time `_PROVIDER_SEARCH_PATH` is replaced by the
  launch env's PATH. Under R2-denied, `admit_for_executor` admits `shipped` and `host_root`
  only, refusing `agy_executor_image_unqualified`.
- **Canary.**
  - The `"1.1.13"` literals in `_sealed_agy_runtime`, `probe_capability` and
    `_require_complete_capability_probe` become: admitted by `admit_for_canary`, plus a
    complete capability matrix recorded under the canary QCI.
  - `_trusted_agy_runtime` keeps its path and mode checks, and the canary executes the
    admitted memfd.
  - The production-unreachable branch `_trusted_provider_runtime("gemini")` is deleted.
  - Under R3-denied, the canary admits an image only when its `capture_surface` matrix
    digest is listed in the shipped catalog. The job (§6) proposes these.

## 5. Per-instantiation preflight and recovery (goal b)

**Command.**

```
phase-loop agy-qualification preflight [--route seat|executor|canary] [--json]
```

It runs `ensure_admitted` for agy on the launch env's PATH, plus the route's extra probe.

**When it runs automatically.**
- At board pre-composition (already, through `requalify_once`).
- At runner start, when any lane's executor is `gemini` (`runner.py`).
- At canary capture start.

**Cost.** At most once per (store, route QCI, image). Spawn stays lookup-only.

**Visibility.** A preflight refusal is shown, never swallowed:
- The board reports the Gemini seat as `MODE_DEGRADED` (Q6), with its code and a fix line.
  This fixes the agent-harness#1420 recurrence, which surfaced as "unknown failure" and
  `review_board_policy_mismatch`.
- The runner refuses the lane before launch, naming the code.
- The doctor shows a row with the code and the next command.

**Failed-entry classes.**
- A `failed` entry gains `class: violation|repeated_transient`.
- `repeated_transient` expires after 24 h or on any key change, as in
  `cli_qualification.TRANSIENT_FAILURE_EXPIRY_S`. `violation` stays permanent until
  `agy-qualification clear`.
- This retires the agent-harness#1158 trap, where three transients outside a git directory
  became a permanent failure.

**Credential and docs fixes.**
- When the login is near expiry, `_refresh_gemini_credential` in `seat_profile` waits
  through the existing `_await_gemini_login` path (agent-harness#1407).
- The doctor's `_AUTH_HINTS` adds `~/.gemini/antigravity-cli/antigravity-oauth-token`.
- `advisor_board/CONTRACTS.md` "Runtime identity (D2)" is rewritten to TEAMHOST §5.

## 6. Rolling catalog and the recurring job (goals c, d)

**6.1 Job.** `phase-loop agy-qualification watch` (`agy_watch`) changes as follows:
- **Scope of a tick.** A tick qualifies only the newest stable upstream release that is not
  a member. It requalifies an existing member only when that member's record `qci` differs
  from `main`'s.
- **Records.** It signs each record (§3.2) with the job's SSH key.
- **PRs.** It opens a ready, not draft, PR labelled `agy-catalog-auto`.
- **Retries.** A series is retried whole, up to `SERIES_RETRIES = 3` per tick, because
  Gemini non-conformance is intermittent (agent-harness#1008: about 3 in 4 per operation).
  An observed `violation` stops the tick and files nothing (Q9 opt-in filing stays off).
- **Aging [R8].** The tick keeps the newest `CATALOG_KEEP = 3` members per route and prunes
  older ones in the same PR.
- **Merge [R6].** Either automatic on green CI under the signer quorum, or one owner
  approval.
- **Unchanged.** Idempotence, oid agreement, push-destination checks and create-only writes
  (`docs/ops/agy-upstream-watch.md`).

**6.2 Install and observe.** `phase-loop agy-qualification watch --install-units` writes the
existing `.service`/`.timer` (four ticks a day) into the user systemd directory and enables
them. `--check` reports `installed|stale|absent` and the last tick's status line. A doctor
row for the watch is out of scope; the lag rule (§6.3) is the red signal.
- **Login.** The job's Gemini login is renewed on the custody terms of ruling R7.
- **Expired login.** If the login has expired, the tick reports `gemini_login_expired` and
  stops, and the lag rule turns it red. It is never silent.

**6.3 Lag rule (bounded and red).** Let `L` be the newest stable upstream release on the
route. Nightly `--upstream-only` fails when all three hold:
- `L` was published more than `LAG_BOUND = 48 h` ago;
- `L` is not a member;
- no open `agy-catalog-auto` PR for `L` exists.

Inside the bound it only warns, as today.

Expected lag by path:
- **To `main`:** at most one tick (6 h), plus the series, plus CI, plus the merge rule.
- **To catalog-only consumers:** the next harness release.
- **To hosts that qualify locally:** zero.

**6.4 Release cut.**
- **R1 as recommended.** No live run. `--release` (§3.3) gates.
- **R1 keeps the full pin.** The job also watches open PRs that change `RELEASE_PIN`. For
  each, it requalifies the newest member (Q11) on the PR head and pushes the refreshed record
  as a new create-only branch with a PR into the release PR's branch. The run is automated,
  not removed.

## 7. Non-goals

- Executor-specific qualification operations.
- Platforms other than linux-x64 glibc.
- Fetching a catalog at runtime from outside the installed package.
- Seat-jail, egress or `SEALED_FALLBACK_CODES` changes.
- `cli_qualification` adapters for other harnesses (agent-harness#1333 PR3–PR7,
  agent-harness#1602 L1–L5).

## 8. Codes

- **New codes:** `agy_provenance_second_channel_mismatch`, `agy_executor_image_unqualified`,
  `agy_canary_image_unqualified`.
- **New store reason:** `budget_exhausted`.
- **New failed classes:** `violation`, `repeated_transient`.
- **Unchanged:** every existing code keeps its meaning.
- **Sealed fallback:** no new code may reach a sealed fallback.
