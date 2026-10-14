# Detailed plan: seat CLIs keep the last good version and qualify new versions on arrival (agent-harness#1602)

## Task
agent-harness#1602, the 0.7.28 headline (maintainer decision 2026-10-14). Seat CLIs (agy, claude, codex, grok) update often, and today a seat launches whatever is on `PATH`. Under this change:

1. **Last good version keeps running.** Each host keeps a store of CLI versions and one active pointer per harness. Seats launch the active version, never `PATH`; a new version becomes active only after it qualifies.
2. **Qualify on arrival.** A host-level watcher notices new versions, qualifies them in the background and moves the pointer. A board never qualifies a CLI.
3. **A failure is a bug report, not an outage.** A contract failure writes a secret-free diagnostic and can open an issue. Transient failures retry, with an expiry.
4. **Records survive runtime upgrades** (agent-harness#1420). The key binds what qualification depends on, not the runtime version.
5. **Feedback loop.** Signed, secret-free host records feed a reviewed, automated promotion PR. A release cut re-checks only the newest members.

**This amends `.consiliency/plans/detailed-cli-qualification-parity-20261008-0615.md`** (agent-harness#1333, "the 2026-10-08 plan").
- **Unchanged.** PR1 (agent-harness#1350) and PR2 (agent-harness#1360) landed. Sections (a)–(d) stand except as "Supersessions" says. Its out-of-scope list stands: the sandbox and jail design, `SEALED_FALLBACK_CODES` (agent-harness#1288), the president ladder, and executor and non-brokered launches.
- **Also out of scope:** agent-harness#1420 §2 (seat-profile credential refresh); the watcher counts it as a transient.
- **Replaced:** section (e), PR3–PR7, by the phasing below.

## Supersessions of the 2026-10-08 plan
| 2026-10-08 text | Now | Authority |
|---|---|---|
| (a) Re-entrancy: first use runs in the board preflight and in `cli-qualification run` | First use runs **only** in the watcher (`watch` / `run`). The board preflight and spawn only look up. | Decision point 2; Q7 (ruled). |
| (a) `runtime_identity` = `__version__` + route-core digests | Key binds the qualification inputs (contract, adapter, launch shape). The runtime version becomes a readable, MAC-bound payload field. | Decision point 4; Q8 (ruled). |
| (a) Launch runs the verified bytes **of the `PATH` payload** | Launch runs the verified bytes **of the active store entry**. `PATH` is only where the watcher looks for new versions. | Decision point 1 |
| Q1: one release that only records (an absent key launches with class `none`), then enforcement | From L3 on, no qualified version means DEGRADED. The recording-only release and old PR7 fold into L3. | Decision 2026-10-14; Q6 (ruled). |
| Q4: manual submission | Automated, reviewed promotion PR | Decision point 5; Q10 (ruled). |
| Q5: requalify every listed member at each cut | Re-check only the newest member per harness | Decision point 5; Q11 (ruled). |
| (d) promotion needs a release-lane re-run record | Replaced by a quorum of independent signed hosts | Q10 (ruled) |

Q2 (node is in the local key) and Q3 (strict: no publisher digest, no promotion) stay as ruled.

## Research summary
**How each CLI installs and updates on Linux** (one host, 2026-10-14; install trees, logs and binary strings only, no CLI executed):

| harness | what resolves on `PATH` | vendor-kept versions | self-update | suppressor strings (unverified) |
|---|---|---|---|---|
| agy | a single ELF file in a user-writable bin dir | none; the file is replaced in place | built in (`auto_updater.go`); replaces the file on interactive runs, skips when its directory is not writable (seat launches) | `AGY_CLI_DISABLE_AUTO_UPDATE` |
| claude | npm global `@anthropic-ai/claude-code`; `bin/claude.exe` is a native ELF (a native-installer `versions/<v>` dir may also exist) | native installer only | npm replaces in place; built-in updater (off here) | `DISABLE_AUTOUPDATER`; settings `autoUpdates` |
| codex | `~/.local/bin/codex` → `packages/standalone/current/bin/codex` (static musl ELF) | `releases/<v>-<triple>/` (`bin/`, `codex-resources/`, `codex-path/`); `current` moved by itself on 2026-10-14 | built in | config key `check_for_update_on_startup`; `CODEX_UPDATE_FROM_RELEASE` |
| grok | npm global `@xai-official/grok`; `bin/grok` → `grok-native` | `$GROK_HOME/bin/grok-<v>` plus a symlink, from the `@xai-official/grok-linux-x64` package | built in | `GROK_DISABLE_AUTOUPDATER`, `GROK_AUTO_UPDATE` |

Consequences:
- **The store keeps its own copy of the verified bytes**, never a pointer into a vendor directory: vendor symlinks move, agy keeps no old versions, npm replaces in place.
- **Install method varies by host**, so the watcher uses the 2026-10-08 per-adapter payload resolver, never a vendor-path convention.
- None of the four runs as a node script here; Q2 still applies wherever one does.
- grok's payload ships in an npm platform package whose `dist.integrity` is a publisher digest (Q3 unchanged; declared in L6).

**Board-time uses of a provider binary today** (no chokepoint; each executes or recognises what `PATH` resolves; `panel_invoker.py` unless noted):
- seat resolution: `_seat_provider_source` (around l.4799, import-time `PATH`); `_resolve_claude_executable` (around l.11084, `/usr/local/bin:/usr/bin:/bin` first; jailed claude `--ro-bind`s its result); `gemini_heartbeat.admit` (around l.181, a sealed memfd `VerifiedImage`, the precedent to generalise);
- the claude version gate `_claude_code_support_status` (l.7474); the auth probes `claude auth status` and codex `login status` (`_LEG_AUTH_PROBE`, l.7352); codex's command-sandbox probe `_codex_sandbox_probe_command` (l.11508); leg availability `available_panel_legs` (l.2565); the launch-owner guard `_provider_entry` / `_recorded_provider_hashes` (around l.5649).

Executor sites (`agy_integrity.trusted_command`, `admitted_command`) are not seat sites.
- Update suppression is set only in `seat_jail.seat_env` (`DISABLE_AUTOUPDATER=1`). `seat_profile`'s environment sets none.

**Contract on main.** `cli_qualification.py` is inert (`ADAPTERS = {}`); `runtime_identity()` (l.232) keys on `__version__`; its store is empty, so re-keying costs no migration.

**agy and patterns.** `agy_qualification.ROUTE_CORE` (`gemini_heartbeat.py`, `agy_qualification.py`, `agy_provenance.py`) plus `__version__` keys agy records, so every release drops them (agent-harness#1420). `agy_provenance.fetch_member` fetches a member against its publisher digest, in memory. Patterns: `agy_watch` for automated draft PRs, `ci/main-red.sh` for one issue updated in place, `credential_redaction.redact_text` for redaction.

## Design

### (A) Store and active pointer: `cli_store.py` (new)
- **Location.** `$XDG_DATA_HOME/phase-loop/cli-store/hosts/<host-hash>/<harness>/`; user config `[qualification] store_dir` overrides it, a repository config cannot. Host hash and HMAC discipline as `cli_qualification.Store` (0700, `O_NOFOLLOW`, euid-owned, per-host HMAC over every metadata file).
- **Entry.** `entries/<payload_sha256>/` holds `payload` (binary) or `tree/` (closure) and a MAC'd, closed-schema `entry.json`: `harness`, `platform`, `payload_kind`, `payload_sha256`, `version_label` (display only), `captured_utc`.
- **Capture.** Read once from the resolved payload, hashed while streaming, written to a temporary sibling, fsynced, re-hashed, renamed into place and made read-only. Entries are immutable; a mismatch is never repaired in place.
- **Pointers.** `active.json` and `previous.json` are MAC'd and replaced only by atomic rename under the per-user, per-harness lock. `active` moves (old value to `previous`) only on the watcher's local pass, the watcher's release admission or Q7 seed, or the `activate` rollback; the L5 board-path admission moves nothing. `phase-loop cli-qualification activate --harness <h> --payload <sha>` accepts only an entry with a valid qualified record under the live key.
- **Retention.** Prune keeps `active`, `previous`, every entry leased by a live board (a shared `flock` held from preflight to the board's last leg) and at most one pending candidate.
- **Launch.** `open_verified(entry)` returns a binary as a sealed memfd (`VerifiedImage`), or a tree as a read-only snapshot in the seat stage, re-hashed after the copy. This keeps the 2026-10-08 guarantee; only the source changes from `PATH` to the store.

### (B) One chokepoint for seat launches
- **`seat_cli.resolve_for_seat(harness, *, pinned=None)`** (new) is the only way seat paths obtain a CLI: for an adapted harness the store entry (`pinned` if the preflight pinned one, else `active`); for a pending harness today's resolution, unchanged.
- **Every board-time use.** For an adapted harness, every board-time launch, probe or gate that executes or recognises a provider binary uses the preflight-pinned entry: seat resolution (`_seat_provider_source`, `_resolve_claude_executable`; `gemini_heartbeat.admit` from L5), the claude version gate, the auth probes (`claude auth status`, codex `login status`), codex's command-sandbox probe, leg availability (`available_panel_legs`: an adapted harness is available when its CLI is on `PATH` or the store holds an entry for it; qualification stays the preflight's decision, so Q6's DEGRADED-with-fix-line stays visible), and the launch-owner guard (which recognises store entries as provider launches).
- **Jailed claude** launches the entry's verified bytes, bound the way the agy heartbeat binds its memfd.
- **Pinning.** The preflight reads the pointer **once** per harness, records `SeatMode.cli_payload_sha256` beside `cli_admission_class` and takes the lease. Spawn launches that digest and never re-reads the pointer.
- **Update suppression.** Every seat environment carries the adapter's declared suppressors; L3 measures each.
- **Narrow claim.** The store is outside every vendor install path and seats see only a memfd or read-only bind, so a vendor updater (user-run or in-seat) cannot change the bytes a seat launches. The claim goes no wider.

### (C) Re-keying (agent-harness#1420, agent-harness#1481, agent-harness#1527, agent-harness#1364)
- **`runtime_identity` becomes `qualification_inputs(adapter)`.** `__version__` leaves the key, which has three parts:
  - `contract`: the sha256 of the contract-core file `cli_qualification.py`. That file holds only the key, the classes, the store, `lookup` and the operation contract.
  - `adapter`: the sha256 of that harness's own adapter module, `cli_adapters/<harness>.py`. There is one module per harness.
  - `launch`: the Q8 digest of the argv and environment-name set that the production builder renders for a fixed fixture, plus the sha256 of the seat-owner module `seat_launch.py`. That module holds only the seat launch owner and the builders.

  The watcher (`cli_watch.watch_tick`), the failure schema and writer, the filer and the export live in modules outside the key.
- **`written_under`** (runtime version) is a MAC-bound payload field of every `qualified` and `failed` entry, for reporting only.
- **`Store.has_record(harness, payload_sha256, *, inputs)`**: public, read-only, no MAC claim, executes nothing; `doctor` and the watcher use it instead of private store attributes.
- **Transient rule** (agent-harness#1364): keyed on the full key (help included); counts transients within 6 h, resets on a pass; three write the 24 h `failed_transient`; `clear` is the reset. Under LKG a transient only delays a candidate.
- **agy** adopts the same key and fields in L5, at the cut.

### (D) Watcher: `phase-loop cli-qualification watch` (one tick) and `run --harness <h>`
Per adapted harness, one tick takes the per-harness lock once and does these steps in order:

1. **Observe.** Resolve the payload with the adapter's resolver against the watcher's `PATH` (user config `[qualification.<h>] source_path` overrides). A new digest is captured as a candidate.
2. **Release fast path.** A shipped-member candidate is recorded `release_qualified` and the pointer moves, with no operations (interpreter-run payloads re-measure help locally, per the Q2 application note).
3. **Qualify.** If the candidate has no record and no unexpired failure, run all operations against the store copy. The tick calls the qualification body for a lock it already holds: the same re-lookup, then the operations, then the record. It never goes through `ensure_admitted`'s own lock acquisition. The candidate token of the 2026-10-08 plan scopes these launches.
   Pass moves the pointer. Otherwise the pointer stays: a contract failure writes a failed record and a diagnostic (E); an identity or isolation failure is sticky `failed` with a local notice only; a transient retries next tick under (C).
4. **Re-establish.** If `active` (then `previous`) has no record under the live key because the inputs changed, requalify it first; until then (F) applies.
5. **Seed** (Q7). Only if the harness has no qualified entry at all.
6. **Prune**, then write `watch-state.json` (last tick, outcome per harness).

**Running it.** `docs/ops/cli-qualification-watch/` ships a user systemd timer and service (hourly, at boot, `Persistent=true`), following `agy-upstream-watch`, including its `Environment=PATH=` of the operator's CLI install directories, since a user service does not inherit the login `PATH`. Installing it is an operator or bootstrap step. `doctor` reports the last tick's age, a harness never observed, and a harness with no active entry or a newer failed candidate.

The watcher downloads only for Q7 seeding, never edits vendor installs and never runs inside a board.

### (E) Failures: notice, diagnostic, issue
- **Notice.** New additive code `seat_cli_running_last_good` informs, never refuses: "a newer <harness> version failed qualification; seats run the last good one; see `cli-qualification status`". What/why/fix text in `seat_jail.NOTICES`, an entry in `_HARNESS_DETAIL_CODES`; no existing code changes.
- **Diagnostic.** `cli_qualification_failure.v1`, closed (`additionalProperties: false`): `harness`, `platform`, `version_label`, `payload_sha256`, `help_sha256`, `failed_op` (enum), `reason` (an adapter-declared contract-reason enum, e.g. a declared flag missing from help, an unparseable completion), `missing_flags` (subset of the declared flag list), `agent_harness_version`, `utc`.

  It has **no free text and no CLI output**: `version_label` matches `^[0-9]+(\.[0-9]+){1,3}([-+][0-9A-Za-z.]{1,32})?$` or is omitted. The writer validates its own output and refuses a record that fails.
- **Issue** (Q9). Only contract-class failures are filed; identity, isolation and transient failures never are. One issue per harness, updated in place (`ci/main-red.sh` pattern), label `cli-qualification-failure`, marker `<!-- cli-qualification-failure:<harness> -->`, body rendered only from diagnostic records. Filing uses `gh` and is skipped without error when `gh` is unavailable.

### (F) Never toolless: outcomes
| situation | seat launches | class | after L7 counting |
|---|---|---|---|
| active has a valid record | active entry | `locally_qualified` / `release_qualified` | counts |
| newer candidate pending, transient or failed | active entry, plus `seat_cli_running_last_good` if failed | as above | counts |
| no qualified entry (fresh host, all versions failed, or inputs changed and not yet requalified) | nothing: `MODE_DEGRADED` `seat_cli_unqualified` with a fix line naming `cli-qualification run` | — | not counted |
| store unsafe, platform unsupported, or an unrecognised wrapper | nothing: the existing `seat_cli_*` degraded codes | — | not counted |

- Every refusal is terminal `MODE_DEGRADED`. None falls to another rung or reaches `sealed`.
- The 2026-10-08 gate placement (before the `route is None` branch and `_seat_route_for_spawn`) and the agent-harness#1244 PR-A1 join carry over unchanged.

### (G) Feedback loop and lighter cut (L6)
- **Signed export.** `cli-qualification export --sign` writes `cli_qualification_candidate.v1` (PR2's closed schema plus `qualification_inputs`, `runtime_identity` readable), with a detached signature from a host key enrolled in a reviewed `allowed_signers` file.
- **Automated promotion PR.** An enabled host opens or updates one draft PR per `(harness, platform, payload, help)`, idempotent like `agy_watch`, adding its signed record under `plans/evidence/cli-candidates/`.
- **CI on that PR** checks each signature against `allowed_signers`, the schema, the publisher digest (Q3), and the quorum of distinct enrolled signers (Q10). It counts only records whose `qualification_inputs` are identical to each other and to the base tree's.

  CI reads the signer list, the verifier and the quorum rule from the base branch, never from the PR head. A promotion PR that changes any of them fails the promotion check. On a pass, a step adds the member to catalog v2 on the PR and marks it ready; a maintainer merges. A candidate's `ops` are never evidence.
- **Catalog v2** keeps the 2026-10-08 shape: routes keyed by `(harness, platform)`, and the agy route byte-equivalent.
- **Lighter cut.** A cut re-runs only the newest member per harness; older members per Q11. The release recipe, the verifier's publication member set and the publication test move together in L6.

## Phasing
Old PR3+PR4 → L3, PR5 → L5, PR6 → L6, PR7 → L3 (Q6); L1, L2 and L4 are new. The 0.7.28 headline needs L1–L5.

**L1: re-key the contract (inert; not agy route core).** Files: `cli_qualification.py` (`qualification_inputs`, `written_under`, `has_record`, transient rule); new `tests/test_cli_qualification_rekey.py`; `advisor_board/CONTRACTS.md`.

Acceptance:
- [ ] A record written under one runtime version is found under a later one when the inputs are unchanged.
- [ ] A change to the adapter-module digest makes it absent.
- [ ] **Key breadth** (fixture adapter; L3 re-runs these with the real adapters):
  - an edit to `panel_invoker.py` outside the rendered launch leaves `has_record` true;
  - an edit to watcher, report or export code leaves records valid;
  - an edit to one adapter module leaves the other harnesses' records valid.
- [ ] `has_record` executes nothing (a spy on subprocess records zero calls) and needs no help digest.
- [ ] Transients spread more than 6 h apart never reach `failed_transient`, and a pass resets the count.

Falsifier: putting `__version__` back in `qualification_inputs` reddens the first cell.

**L2: store plus chokepoint (behaviour-neutral for pending harnesses).** Files: new `cli_store.py` and `seat_cli.py`;
- `panel_invoker.py`:
  - `_seat_provider_source` and `_resolve_claude_executable` delegate to `resolve_for_seat`;
  - the seat launch owner and builders move unchanged to a new `seat_launch.py` (the seat-owner module of (C)).
- `seat_preflight.SeatMode.cli_payload_sha256`; new `tests/test_cli_store.py`, `tests/test_seat_cli_chokepoint.py`.

Acceptance:
- [ ] Capture writes an immutable entry whose re-hash matches; a tampered `entry.json` or payload refuses `seat_cli_qualification_store_unsafe`. Pointer moves are atomic; prune never removes `active`, `previous` or a leased entry.
- [ ] **Behavioural resolution cell.** For each harness adapted at this PR (a fixture adapter at L2), with the `PATH` binary's digest differing from the store's `active` entry, the preflight-pinned and launched digest equals `active`. Pending harnesses (agy until L5) keep today's resolution, including `_resolve_claude_executable`'s `/usr/local/bin:/usr/bin:/bin`-first order and `_seat_provider_source`'s import-time `PATH`.
- [ ] A spawn of a store entry outside the launch owner is refused.
- [ ] With `ADAPTERS` empty, every existing seat-route test is unchanged and green.

Falsifier: making `resolve_for_seat` return the `PATH` resolution for an adapted harness reddens the behavioural cell.

**L3: codex, grok and claude adapters, the watcher, and seats launching active (enforcing, per Q6).** Files:
- `cli_adapters/{codex,grok,claude}.py`, one module per harness, each declaring its update suppressors and flag list. claude leaves `cli_qualification.PENDING_ADAPTERS`. The codex adapter measures (PR body) whether a standalone payload is the binary or the release-directory tree;
- a new `cli_watch.py`, and `cli.py`: `run`, `watch`, `activate`;
- `seat_jail.NOTICES` and `_HARNESS_DETAIL_CODES` (`seat_cli_running_last_good`);
- `seat_preflight.py` and `governed_review.py`. The generic counting rule lives in `seat_preflight`, beside `counts_as_grounded_vote`. `governed_review` calls it, and it delegates agy legs to `agy_qualification.counts_toward_landing` unchanged. `agy_qualification.py` is not edited before L5.
- `panel_invoker.py` (preflight pins and leases; spawn launches the pinned entry); `doctor.py`; new `docs/ops/cli-qualification-watch/` and `tests/test_cli_qualification_seat_route.py`.

Acceptance:
- [ ] **Failing upgrade.** With the store holding qualified version A and `PATH` changed to a version B that fails `completion`, a watch tick leaves `active` = A. The next seat launches A's digest with class `locally_qualified`, and the notice is `seat_cli_running_last_good`. No `MODE_DEGRADED`, no `MODE_SEALED`.
  - The same holds when B fails `--version`, and separately when B is absent from `PATH`: the seat still launches A, and the leg is available.
  - codex's sandbox probe runs on A's bytes, and it is not skipped for a store launch.
- [ ] **Single run.** A tick with a passing candidate runs each operation exactly once and moves `active`.
- [ ] **Passing upgrade.** With B passing, one tick moves `active` to B. The next board launches B. No board-path call to `ensure_admitted` is made (a spy counts zero in preflight and in spawn).
- [ ] **Self-update.** Replacing the `PATH` file after capture, or moving a vendor symlink, leaves the launched bytes equal to the pinned digest.
- [ ] **Mid-board move.** Moving `active` between preflight and the second leg's spawn leaves both legs on the preflight-pinned digest.
- [ ] **No qualified version.** An empty store gives a preflight `MODE_DEGRADED` `seat_cli_unqualified` and a spawn DEGRADED result, each with the fix line. The `PATH` binary is never launched.
- [ ] **Counting** (old PR7, Q6). The `seat_preflight` rule reads `cli_admission_class` for every harness. A leg without `locally_qualified` or `release_qualified` cannot approve, its `DISAGREE` still blocks, and agy's counting cells are unchanged.
- [ ] `verify_qualified_agy_image.py --route-core` passes on L3's tree with no new agy record.
- [ ] **Carried from the 2026-10-08 plan's PR3 and PR4:** never sealed (including codex and grok route-None with the host sandbox unavailable); the candidate token crosses `invoke_panel`'s thread hop; one lookup per spawn; eligibility parity; no sealed extension; completeness with only `gemini` pending; the Omnigent guard; a jail pass plus a `failed` CLI is `MODE_DEGRADED`; a native claude fill is not CLI-gated.
- [ ] **Live.** One watch tick per harness on a Linux host; the PR body records each operation's result, wall time, inference cost and suppressor measurement.

Falsifiers:
- Letting spawn re-read `active` reddens the mid-board cell.
- Moving the pointer on `failed` reddens the failing-upgrade cell.

**L4: failure diagnostics and issue filing.** Files: new `cli_qualification_report.py` (failure schema, writer, `gh` filer) and tests.

Acceptance:
- [ ] The schema refuses free text, a path-shaped field, a host-shaped field or an extra field.
- [ ] An isolation-class or transient failure produces no `gh` invocation (spy).
- [ ] A repeat contract failure edits the harness's one open issue, never a second; with filing not enabled there is no `gh` call.

Falsifier: allowing `reason: "isolation"` through the filer reddens the spy cell.

**L5: agy onto the contract and the store (old PR5, with the 0.7.28 cut).** Files:
- `agy_qualification.py` delegates store, lock, classes, transient rule and key to `cli_qualification`: no `__version__`, plus `written_under` and `has_record` (agent-harness#1481, agent-harness#1527).
- `gemini_heartbeat.admit`, which resolves through `seat_cli.resolve_for_seat`.
- `_preflight_gemini_heartbeat`, which becomes lookup-only, so first use moves to the watcher.
  - **Shipped-member admission.** When no agy entry has a valid record under the live key and the `PATH` payload is a shipped member, the preflight admits it `release_qualified` with zero operations, exactly as `gemini_heartbeat.admit` does today (one read, digest checked against the shipped set, launch of that sealed memfd). It writes no store entry and moves no pointer, so it never waits on the per-harness lock; the next tick captures it (step 2). Decision point 1 keeps unqualified new versions from ever launching; a shipped member is release-qualified, and its sealed, verified bytes are not "whatever is on `PATH`".
- Q7 seeding for agy (watcher step 5), through `agy_provenance.fetch_member` against the publisher digest, re-hashed on capture. codex, grok and claude seed once catalog v2 (L6) lists members for them, and L6 adds the same three cells for one of them.
- `gemini` leaves `PENDING_ADAPTERS`.

The v1 migration rule is unchanged: entries are ignored and never translated, and the watcher re-establishes each host once.

**The 0.7.28 cut applies Q11.**
- It requalifies the newest agy release on the cut tree, determined at cut time.
- L5 changes the route core, so every older member's record was taken under different inputs. The cut PR therefore removes those members from the catalog and from `QUALIFIED_IMAGES` together.
- The existing `verify_qualified_agy_image.py` (`--source-only`) then passes unchanged. L6 generalises the member-set filter.

Acceptance:
- [ ] A host whose `PATH` agy fails qualification while the store holds an earlier qualified agy runs that earlier agy, with `seat_cli_running_last_good`. Reproduced with fixture images.
- [ ] Empty store, and the `PATH` agy is a shipped member: the preflight class is `release_qualified`, with zero watcher ticks, zero `ensure_admitted` calls and zero operations. The seat launches that digest.
- [ ] **Seeding** (Q7):
  - fresh store and a failing `PATH` agy: the watcher seeds the newest shipped member, `active` becomes it, and its class is `release_qualified`;
  - a fetched payload whose digest differs from the publisher digest writes no entry, and the harness stays DEGRADED;
  - seeding never runs while any entry has a valid record.
- [ ] `_preflight_gemini_heartbeat` never calls `ensure_admitted` (spy).
- [ ] After a simulated runtime upgrade with unchanged route core, the record is still found, and `doctor` names its `written_under`.
- [ ] All PR1 per-caller admission cells are unchanged and green. `--source-only` passes on the cut tree.

Falsifier: a v1-translating shim reddens the absent cell.

**L6: feedback loop (old PR6).** (G): `export --sign`, the promotion workflow step, catalog v2, `scripts/verify_qualified_cli.py`, and the publication member-set change.

Old PR6's cells stay (payload mismatch fails, `upstream_provenance=None` fails, agy route verifies as before), plus:
- [ ] A record with a signature from an unenrolled key fails.
- [ ] Fewer than the quorum of distinct signers fails.
- [ ] Two records from one signer count once.
- [ ] Two valid signatures over stale inputs fail.
- [ ] A candidate PR that also edits `allowed_signers` or the verifier fails.

**L7:** Folded into L3 (Q6).

## Changes
The PR sections list the files. New entities: `cli_store` (`Entry`, `capture`, `open_verified`, `active`, `previous`, `activate`, `lease`, `prune`); `seat_cli.resolve_for_seat`; `cli_qualification.qualification_inputs` and `Store.has_record`; `cli_adapters/<harness>.py`; `seat_launch.py`; `cli_watch.watch_tick`; `cli_qualification_report` (`FAILURE_SCHEMA`, `file_or_update`); `SeatMode.cli_payload_sha256`; the code `seat_cli_running_last_good`; `phase-loop cli-qualification run|watch|activate|export --sign`.

**Vocabulary.** `_HARNESS_DETAIL_CODES` is a closed allowlist; this plan adds exactly `seat_cli_running_last_good` (plus the 2026-10-08 six) and changes no entry.

Existing test files cited by mutation receipts (`test_seat_notices.py`) are never edited. `test_cli_qualification_contract.py`, which no receipt cites, may have its inert-contract node (`test_no_adapter_exists_and_the_contract_is_inert`) updated by the PR that adds the first adapter. Its docstring already anticipates this.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` (modify): re-key and transient rule (L1); store, pointer and watcher (L2, L3); failure reporting (L4); agy's "board never qualifies" rule (L5).
- `docs/ops/cli-qualification-watch.md` and unit templates (add, L3): install, `status`, `activate` rollback, `clear`, disk use (about three payloads per harness).
- `docs/ops/agy-upstream-watch.md` (modify, L5): pointer to the generic watcher; `agy_watch` stays until L6.
- `docs/ops/cli-qualification-promotion.md` (add, L6); `docs/releases/outside-agent-release-handoff.md` (modify, L6): newest member only.
- `CHANGELOG.md`: one entry per PR. The 2026-10-08 plan (this PR): append-only pointer lines.

## Dependencies & order
- L1 → L2 → L3 → L4; L1 lands while the generic store is still empty. L5 needs L1–L3 and a release cut; L6 needs L5.
- **agent-harness#1244 PR-A1:** the 2026-10-08 join rule is unchanged. `resolve_for_seat` and the pinned digest are resolver inputs gathered before the call.
- **agent-harness#1288:** an open dependency, not a prerequisite, as before.

## Execution Policy
- execute: effort=high, reason=verified-bytes launch from a new store, pointer/lease concurrency with live boards, and an outward-facing issue filer. L1: effort=medium.

## Verification
From `phase-loop-runtime/`:

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_cli_qualification_contract.py tests/test_agy_self_qualification.py tests/test_seat_notices.py tests/test_agy_integrity_seat_admission.py
PYTHONPATH=src python3 -m pytest -q tests/test_cli_qualification_rekey.py tests/test_cli_store.py tests/test_seat_cli_chokepoint.py tests/test_cli_qualification_seat_route.py   # new, per PR
python3 scripts/verify_qualified_agy_image.py --route-core
python3 scripts/verify_qualified_agy_image.py --source-only   # L5 (cut) only
```

Live: L3 and L5 run `cli-qualification watch` once per harness on a Linux host, then `status` and `doctor`; L3 forces a failing candidate from a fixture image, never by running an installed agy; L4 dry-runs the filer against a scratch repository.

automation.suite_command: `cd phase-loop-runtime && PYTHONPATH=src python3 -m pytest -q tests/test_cli_qualification_contract.py tests/test_agy_self_qualification.py tests/test_seat_notices.py`

## Acceptance criteria
- [ ] An upgrade to a version that fails qualification leaves the seat on the last good version with `seat_cli_running_last_good`, and it is neither DEGRADED nor sealed. Proven by L3's failing-upgrade cell (codex, grok, claude) and L5's agy cell.
- [ ] A passing new version becomes active through a watch tick, with zero `ensure_admitted` calls on any board path. Proven by L3's passing-upgrade cell.
- [ ] A vendor self-update or a `PATH` change after capture never changes the bytes a seat launches. Proven by L3's self-update and mid-board cells.
- [ ] A runtime upgrade that leaves the qualification inputs unchanged keeps local records valid. Proven by L1's first cell and L5's upgrade cell.
- [ ] No harness without a qualified version launches a sealed or toolless seat. Proven by the never-sealed cells carried into L3.

## Questions for the maintainer
- **Q6. Q1's recording-only release, superseded by "no qualified version means DEGRADED, never counted".**
  1. *(Recommended)* Enforce from L3. No qualified version is DEGRADED, and counting requires a qualified class, so old PR7 folds into L3.
     - Cost: after upgrading, each host must run one `cli-qualification watch` before its next board. Until it does, its codex, grok and claude seats are DEGRADED with a fix line. The release notes and `doctor` say so.
  2. Keep Q1. In L3's release, a host with no qualified version launches today's `PATH` binary with class `none`: tooled, never sealed, and still counted. Enforcement and counting land one release later.
- **Q7. A host with no good version at all** (a fresh store, or the only local version fails). This decides whether such a host has any seat for that harness before a passing version arrives locally.
  1. *(Recommended)* The watcher seeds from the newest shipped member when the adapter can fetch it against a publisher digest (agy today, others once promoted). Otherwise DEGRADED until a local version qualifies.
  2. Observe only: never download. DEGRADED until a version on `PATH` qualifies.
  3. Option 1, and the watcher also captures older versions that a vendor still keeps on disk (codex, grok and claude version directories) as candidates.
- **Q8. Covering launch-builder edits once `__version__` leaves the key** (the 2026-10-08 plan relied on it).
  1. *(Recommended)* The key includes a digest of the argv and environment-name set that the production seat builder renders for a fixed fixture, plus the seat-owner module digest. A builder edit that changes the launch triggers requalification; an unrelated release does not.
  2. Move each harness's seat argv builder into its adapter module, and hash that module.
  3. Key on the contract and adapter modules only, and accept that builder edits do not requalify.
- **Q9. Opening issues for contract failures.**
  1. *(Recommended)* Opt-in per host, through user config `[qualification] report_issues_to = "<owner>/<repo>"`. Contract failures only, one issue per harness updated in place.
  2. On by default, filing to agent-harness.
  3. Never file. Local diagnostic and `status` only.
- **Q10. Promotion (supersedes Q4; Q3 stays).**
  1. *(Recommended)* Hosts sign records with SSH keys enrolled in a reviewed `allowed_signers` file. An enabled host opens or updates a draft promotion PR. CI requires the publisher digest plus at least 2 distinct enrolled signers on an identical `(harness, platform, payload, help)`. The release-lane re-run record is dropped, and a maintainer review merges.
  2. As option 1, but also keep the release-lane re-run record.
  3. Keep Q4: manual submission, no automation.
- **Q11. Older listed members at a cut (supersedes Q5).**
  1. *(Recommended)* Re-run only the newest member per harness. An older member stays listed while its record's `qualification_inputs` match the cut tree. Otherwise the cut PR removes it.
  2. Re-run only the newest member, and keep older members listed regardless.
  3. Keep Q5: re-run every listed member.

## Maintainer rulings (2026-10-14)
These rulings are append-only. All six follow the recommendation (option 1).
- **Q6: enforce from L3.** No qualified version means DEGRADED, and such a leg is never counted. Old PR7 folds into L3. This **supersedes 2026-10-08 Q1**, the recording-only release.
- **Q7: seed.** The watcher seeds from the newest shipped member, fetched against a publisher digest. Otherwise the harness is DEGRADED.
- **Q8: launch coverage.** The key includes the digest of the argv and environment-name set rendered for a fixed fixture, plus the seat-owner module digest.
- **Q9: opt-in filing.** Issue filing is opt-in per host through `[qualification] report_issues_to`, and covers contract failures only.
- **Q10: signed promotion.** The rules are:
  - records are SSH-signed against an enrolled `allowed_signers` file;
  - promotion goes through a draft promotion PR;
  - CI requires the publisher digest plus at least 2 distinct signers;
  - there is no release-lane re-run;
  - a maintainer merges.

  This **supersedes 2026-10-08 Q4**, manual submission. Q3 (strict) stands.
- **Q11: newest member only.** A cut re-runs only the newest member per harness. Older members stay while their `qualification_inputs` match, and otherwise the cut PR removes them. This **supersedes 2026-10-08 Q5**, which requalified every member.

2026-10-08 Q2 and Q3 are unchanged.

**Confirmed (2026-10-14).** The maintainer confirmed that Q11 at the 0.7.28 cut is meant to shrink the agy catalog to its single newest member.

## Revision history
- **r1** (2026-10-14): first draft, amending the 2026-10-08 plan's section (e).
- **r2** (2026-10-14): the maintainer's rulings on Q6–Q11 are recorded, and the Q7 motivation is reworded generically, with no claim about a specific agy version.
- **r3** (2026-10-14): applies the president's hb1 ruling D1–D14 (REVISE AND RECHECK) and records the maintainer's confirmation of Q11 at 0.7.28.
