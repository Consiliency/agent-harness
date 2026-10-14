# Detailed plan: seat CLIs keep the last good version and qualify new versions on arrival (agent-harness#1602)

## Task
agent-harness#1602, the 0.7.28 headline (maintainer decision 2026-10-14). Seat CLIs (agy, claude, codex, grok) update often, and today a seat launches whatever is on `PATH`. Under this change:

1. **Last good version keeps running.** Each host keeps a store of CLI versions and one active pointer per harness. Seats launch the active version, never `PATH`. A new version becomes active only after it qualifies. A failing new version leaves the seat on the last good one.
2. **Qualify on arrival.** A host-level watcher notices new versions, qualifies them in the background and moves the pointer. A board never qualifies a CLI.
3. **A failure is a bug report, not an outage.** A contract failure writes a secret-free diagnostic and can open an issue. Transient failures retry, with an expiry.
4. **Records survive runtime upgrades** (agent-harness#1420). The key binds what qualification depends on, not the runtime version.
5. **Feedback loop.** Signed, secret-free host records feed a reviewed, automated promotion PR. A release cut re-checks only the newest members.

**This amends `.consiliency/plans/detailed-cli-qualification-parity-20261008-0615.md`** (agent-harness#1333, "the 2026-10-08 plan").
- **Unchanged.** PR1 (agent-harness#1350) and PR2 (agent-harness#1360) have landed and are unchanged. The 2026-10-08 plan's sections (a)–(d) stay in force except where "Supersessions" below says otherwise. Its out-of-scope list stands: the sandbox and jail design, `SEALED_FALLBACK_CODES` (agent-harness#1288), the president ladder, and executor and non-brokered launches.
- **Also out of scope.** agent-harness#1420 section 2, the seat-profile credential refresh. If the watcher hits it, it counts as a transient under (C).
- **Replaced.** Its section (e), PR3–PR7, is replaced by the phasing below.

**Size.** Like the plan it amends, this is an umbrella over several PRs that share one contract. Each PR has its own acceptance criteria and falsifier.

## Supersessions of the 2026-10-08 plan
| 2026-10-08 text | Now | Authority |
|---|---|---|
| (a) Re-entrancy: first use runs in the board preflight and in `cli-qualification run` | First use runs **only** in the watcher (`watch` / `run`). The board preflight and spawn only look up. | Decision 2026-10-14, point 2. What a host with no good version does is Q7. |
| (a) `runtime_identity` = `__version__` + route-core digests | Key binds the qualification inputs (contract, adapter, launch shape). The runtime version becomes a readable, MAC-bound payload field. | Decision point 4, agent-harness#1420. How launch-builder edits are covered is Q8. |
| (a) Launch runs the verified bytes **of the `PATH` payload** | Launch runs the verified bytes **of the active store entry**. `PATH` is only where the watcher looks for new versions. | Decision point 1 |
| Q1: one release that only records (an absent key launches with class `none`), then enforcement | From L3 on, no qualified version means DEGRADED. The recording-only release and old PR7 fold into L3. | Decision 2026-10-14 ("no qualified version means DEGRADED, never counted"). Confirm as Q6. |
| Q4: manual submission | Automated, reviewed promotion PR | Decision point 5. Mechanism is Q10. |
| Q5: requalify every listed member at each cut | Re-check only the newest member per harness | Decision point 5. Older members are Q11. |
| (d) promotion needs a release-lane re-run record | Possibly replaced by agreement between independent signed hosts | Q10 |

Q2 (node is in the local key) and Q3 (strict: no publisher digest, no promotion) stay as ruled.

## Research summary
**How each CLI installs and updates on Linux.** Measured on one fleet host on 2026-10-14 by reading install trees, logs and binary strings. No CLI was executed.

| harness | what resolves on `PATH` | vendor-kept versions | self-update mechanism seen | candidate suppressors (from strings; semantics unverified) |
|---|---|---|---|---|
| agy | a single ELF file in a user-writable bin dir | none; the file is replaced in place | built in. The CLI log shows `auto_updater.go` "Spawned background update process" on interactive runs. Under seat launches, the binary's directory is not writable and it logs "skipping update". It checks at most every 15 min (`last_check.timestamp`). | `AGY_CLI_DISABLE_AUTO_UPDATE` |
| claude | npm global `@anthropic-ai/claude-code`; `bin/claude.exe` is a native ELF hardlinked from the `-linux-x64` optional dependency. The same host also has a stale native-installer `~/.local/share/claude/versions/<v>` dir. | native installer only | npm reinstall replaces it in place. The built-in updater is off in user settings here. | `DISABLE_AUTOUPDATER`; settings `autoUpdates` |
| codex | `~/.local/bin/codex` → `packages/standalone/current/bin/codex` (static musl ELF) | yes: `releases/<v>-<triple>/`, holding `bin/`, `codex-resources/` (bwrap, zsh) and `codex-path/` (rg). The `current` symlink moved on 2026-10-14 by itself. | built in (`auto-update-version`, `install.lock`) | config key `check_for_update_on_startup`; `CODEX_UPDATE_FROM_RELEASE` |
| grok | npm global `@xai-official/grok`; `bin/grok` → `grok-native` | yes: `$GROK_HOME/bin/grok-<v>` plus a `grok` symlink, written by `postinstall.js` from the brotli-compressed `@xai-official/grok-linux-x64` package | built in (`auto_update` setting strings) | `GROK_DISABLE_AUTOUPDATER`, `GROK_AUTO_UPDATE` |

Consequences for the design:
- **The store holds its own copy of the verified bytes, never a pointer into a vendor directory.** Vendor symlinks move without us, agy keeps no old versions, and npm replaces files in place.
- **Install method varies by host.** For example, claude can be installed with npm or with the native installer. So the watcher finds payloads through the existing per-adapter payload resolver of the 2026-10-08 plan, never through a vendor-path convention.
- **None of the four ships as a node script on this host.** The interpreter rule (Q2) still applies wherever an install does.
- **grok also has a publisher digest.** Its payload ships inside an npm platform package, whose `dist.integrity` is that digest. This bears on Q3 for grok, but no ruling changes. The adapter declares its provenance in L6.

**Seat binary resolution today.** There is no chokepoint: every site calls `shutil.which` against `PATH`.
- `_seat_provider_source` (`panel_invoker.py`, around l.4799) is used by codex, grok, non-jailed claude and non-heartbeat agy, through `_seat_command_profile`.
- `_resolve_claude_executable` (around l.11084) is used by the jailed claude path, which `--ro-bind`s the resolved path at `/seat/bin/claude`.
- `gemini_heartbeat.admit` (`gemini_heartbeat.py`, around l.181) is used by agy heartbeat, which binds a sealed memfd (`VerifiedImage`). This is the precedent to generalise.
- Not seat sites: `agy_integrity.trusted_command` and `agy_integrity.admitted_command` (executor), and `_recorded_provider_hashes` (allow-list only).
- Update suppression is set only in `seat_jail.seat_env` (`DISABLE_AUTOUPDATER=1`). `seat_profile`'s environment sets none.

**Contract on main.** `cli_qualification.py` is inert:
- `ADAPTERS = {}` (l.35) and `PENDING_ADAPTERS = {"claude","gemini"}` (l.38).
- `runtime_identity()` (l.232) puts `__version__` into every key.
- The `Store` (l.382) holds no live entries on any host, so re-keying it costs no migration.

**agy specifics.**
- `agy_qualification.ROUTE_CORE` is `gemini_heartbeat.py`, `agy_qualification.py` and `agy_provenance.py`. Its key also carries `__version__`, which is why every release drops local records (agent-harness#1420).
- `agy_provenance.fetch_member` downloads a release member against its publisher digest, in memory only.
- `agy_watch` (one tick, `gh pr create --draft`, idempotent against its own open PRs) is the pattern for automated PRs.
- `ci/main-red.sh` (one labelled issue, updated in place) is the pattern for issues.
- `credential_redaction.redact_text` is the redaction helper.

## Design

### (A) Store and active pointer: `cli_store.py` (new)
- **Location.** `$XDG_DATA_HOME/phase-loop/cli-store/hosts/<host-hash>/<harness>/`. User config `[qualification] store_dir` overrides it, and a repository config cannot. The host hash and the HMAC discipline are those of `cli_qualification.Store`: 0700 directories, `O_NOFOLLOW`, euid-owned, and a per-host HMAC over every metadata file.
- **Entry.** `entries/<payload_sha256>/` holds `payload` (binary) or `tree/` (closure), plus a MAC'd `entry.json`. That file is a closed schema with these fields:
  - `harness`, `platform`, `payload_kind`, `payload_sha256`
  - `version_label` (display only)
  - `captured_utc`
- **Capture.** The bytes are read once from the payload the resolver found, hashed while streaming, and written to a temporary sibling. They are then fsynced and re-hashed, the directory is renamed into place, and the entry is made read-only. An entry is immutable, and a digest mismatch is never repaired in place.
- **Pointers.**
  - `active.json` and `previous.json` are MAC'd and replaced only by atomic rename under the existing per-user, per-harness lock.
  - Only two events move `active`, and the old value goes to `previous`:
    - a `locally_qualified` pass recorded by the watcher;
    - a `release_qualified` admission.
  - `phase-loop cli-qualification activate --harness <h> --payload <sha>` is the operator rollback. It accepts only an entry that has a valid qualified record under the live key.
- **Retention.** Prune keeps `active`, `previous`, every entry leased by a live board (a shared `flock` on the entry, held from preflight to the board's last leg), and at most one pending candidate. It removes the rest.
- **Launch.** `open_verified(entry)` returns the verified bytes:
  - a binary as a sealed memfd (`VerifiedImage`);
  - a tree as a read-only snapshot in the seat stage, re-hashed after the copy.

  This keeps the 2026-10-08 guarantee. The only source changes from `PATH` to the store.

### (B) One chokepoint for seat launches
- **`seat_cli.resolve_for_seat(harness, *, pinned=None)`** (new) is the only function seat paths use to obtain a CLI.
  - For an adapted harness it returns the store entry: the `pinned` digest when the preflight pinned one, otherwise `active`.
  - For a pending harness it returns today's resolution unchanged.
- **Sites it replaces.** `_seat_provider_source`, `_resolve_claude_executable`, and (in L5) `gemini_heartbeat.admit`'s `PATH` lookup.
- **Jailed claude** launches the entry's verified bytes, bound the way the agy heartbeat binds its memfd.
- **Pinning.** The board preflight reads the pointer **once** per harness. It records `SeatMode.cli_payload_sha256` next to `cli_admission_class`, and takes the entry lease. Spawn launches that digest and never re-reads the pointer, so a pointer move during a board does not change what the board runs.
- **Update suppression.** Every seat launch environment carries the adapter's declared update suppressors. L3 records, per harness, a measurement showing that the suppressor works.
- **Narrow claim.** The store sits outside every vendor install path, and seats see only a memfd or a read-only bind. So a vendor updater, whether run by the user or triggered inside a seat, cannot change the bytes a seat launches. The claim does not go wider than that.

### (C) Re-keying (agent-harness#1420, agent-harness#1481, agent-harness#1527, agent-harness#1364)
- **`runtime_identity` becomes `qualification_inputs(adapter)`:** `{contract: sha256(cli_qualification.py), adapter: sha256(<adapter module>), launch: <launch-coverage digest, Q8>}`. `__version__` leaves the key.
- **`written_under`** (the runtime version) is a MAC-bound payload field of every `qualified` and `failed` entry. It is for reporting only and is never compared.
- **`Store.has_record(harness, payload_sha256, *, inputs)`** is a public read-only lookup. It makes no MAC claim and executes nothing. `doctor` and the watcher use it, and nothing reaches a private store attribute.
- **Transient rule** (agent-harness#1364, decided here):
  - The counter is keyed on the full key, help digest included.
  - It counts only transients within a 6 h window and resets on any pass.
  - Three in the window write the 24 h `failed_transient`.
  - `phase-loop cli-qualification clear` is the documented reset.

  Under LKG a transient only delays a candidate. It never degrades a running seat.
- **agy** adopts the same key and payload fields in L5, at the cut, because that is where its route core changes.

### (D) Watcher: `phase-loop cli-qualification watch` (one tick) and `run --harness <h>`
Per adapted harness, under its lock, one tick does these steps in order:

1. **Observe.** Resolve the payload with the adapter's resolver, against the `PATH` the watcher was given. User config `[qualification.<h>] source_path` overrides it. If the digest is not in the store, capture it as a candidate.
2. **Release fast path.** If the candidate is a shipped member, record `release_qualified` and move the pointer. No operations run, with one exception: interpreter-run payloads re-measure help under the local interpreter, per the 2026-10-08 Q2 application note.
3. **Qualify.** If the candidate has no record and no unexpired failure, run `ensure_admitted` with all operations against the store copy. The candidate token of the 2026-10-08 plan scopes these launches.
   - **Pass:** move the pointer.
   - **Contract failure:** write a failed record and a diagnostic, and go to (E). The pointer does not move.
   - **Identity or isolation failure:** sticky `failed`, with a local notice only. The pointer does not move.
   - **Transient:** record it and retry next tick, under (C)'s rule.
4. **Re-establish.** If `active` (then `previous`) has no record under the live key, because the inputs changed, requalify it first. Until that finishes, the harness has no qualified version, and (F) applies.
5. **Seed** (Q7). Only if the harness has no qualified entry at all.
6. **Prune**, then write `watch-state.json` with the time of the last tick and the outcome per harness.

**Running it.**
- A systemd user service does not inherit the login `PATH`. The unit template therefore sets `Environment=PATH=` to the operator's CLI install directories, as `agy-upstream-watch.service` already does. `doctor` flags a harness whose watcher has never observed a payload.
- `docs/ops/cli-qualification-watch/` ships a user systemd timer and service template, following `docs/ops/agy-upstream-watch/`: hourly, plus at boot, `Persistent=true`.
- Installing it is an operator or bootstrap step, not product code.
- `phase-loop doctor` reports the age of the last tick, and each harness that has no active entry or has a newer failed candidate.

**What it does not do.** The watcher never downloads except for Q7 seeding. It never edits vendor installs, and it never runs inside a board.

### (E) Failures: notice, diagnostic, issue
- **Notice.** A new additive notice code, `seat_cli_running_last_good`, informs; it never refuses. It means "a newer <harness> version failed qualification; seats run the last good one; see `cli-qualification status`". It gets what/why/fix text in `seat_jail.NOTICES` and an entry in `_HARNESS_DETAIL_CODES`, following the 2026-10-08 vocabulary rule. No existing code changes.
- **Diagnostic.** `cli_qualification_failure.v1` is a closed schema, `additionalProperties: false`, with these fields:
  - `harness`, `platform`, `version_label`, `payload_sha256`, `help_sha256`
  - `failed_op` (an op enum)
  - `reason` (an enum of contract reasons the adapter declares, such as a declared flag missing from the help surface, or an unparseable completion)
  - `missing_flags` (a subset of the adapter's declared flag list)
  - `agent_harness_version`, `utc`

  It has **no free text and no CLI output**. The writer validates its own output and refuses a record that fails.
- **Issue** (Q9).
  - Only contract-class failures are ever filed. Identity, isolation and transient failures are never filed anywhere automatically.
  - There is one issue per harness, updated in place (the `ci/main-red.sh` pattern), with label `cli-qualification-failure` and a `<!-- cli-qualification-failure:<harness> -->` marker.
  - Its body is rendered only from diagnostic records.
  - Filing uses `gh` and is skipped without error when `gh` is unavailable or unauthenticated.

### (F) Never toolless: outcomes
| situation | seat launches | class | after L7 counting |
|---|---|---|---|
| active has a valid record | active entry | `locally_qualified` / `release_qualified` | counts |
| newer candidate pending, transient or failed | active entry, plus `seat_cli_running_last_good` if failed | as above | counts |
| no qualified entry (fresh host, every version failed, or inputs changed and the requalification has not finished) | nothing: `MODE_DEGRADED` `seat_cli_unqualified` with a fix line naming `cli-qualification run` | — | not counted |
| store unsafe, platform unsupported, or an unrecognised wrapper | nothing: the existing `seat_cli_*` degraded codes | — | not counted |

- Every refusal is terminal `MODE_DEGRADED`. None falls to another rung or reaches `sealed`.
- The 2026-10-08 plan's gate placement carries over unchanged: before the `route is None` branch, and before `_seat_route_for_spawn`. So does the agent-harness#1244 PR-A1 join.

### (G) Feedback loop and lighter cut (L6; shape pending Q10 and Q11)
- **Signed export.** `cli-qualification export --sign` writes `cli_qualification_candidate.v1`. It extends PR2's closed schema with `qualification_inputs` and keeps `runtime_identity` readable. It carries a detached signature from a host key enrolled in a reviewed `allowed_signers` file in the repository.
- **Automated promotion PR.** A host with promotion enabled opens or updates one draft PR per `(harness, platform, payload, help)`, idempotent the way `agy_watch` is. It adds its signed record under `plans/evidence/cli-candidates/`.
- **CI on that PR** checks:
  - each signature against `allowed_signers`;
  - the schema;
  - the publisher digest (Q3, unchanged);
  - the quorum of distinct enrolled signers (Q10).

  When it passes, a step adds the member to catalog v2 on the same PR and marks it ready for review. A maintainer merges. A candidate's `ops` are still never read as evidence.
- **Catalog v2** keeps the 2026-10-08 shape: routes keyed by `(harness, platform)`, and the agy route byte-equivalent.
- **Lighter cut.** At a cut the release lane re-runs only the newest listed member per harness. Older members are handled per Q11. The release recipe, `verify_qualified_agy_image.py`'s publication member set, and the publication test move together in L6.

## Phasing
The old PRs map to the new ones as follows:
- old PR3 + PR4 → L3;
- old PR5 → L5;
- old PR6 → L6;
- old PR7 → L7.

L1, L2 and L4 are new. The 0.7.28 headline needs L1–L5.

**L1: re-key the contract (inert).** Files:
- `cli_qualification.py`: `qualification_inputs`, the `written_under` payload, `has_record`, and the transient rule;
- a new `tests/test_cli_qualification_rekey.py`;
- `advisor_board/CONTRACTS.md`, in the generic section.

Not agy route core.

Acceptance:
- [ ] A record written under one runtime version is found under a later one when the inputs are unchanged.
- [ ] A change to the adapter-module digest makes it absent.
- [ ] `has_record` executes nothing (a spy on subprocess records zero calls) and needs no help digest.
- [ ] Transients spread more than 6 h apart never reach `failed_transient`, and a pass resets the count.

Falsifier: putting `__version__` back in `qualification_inputs` reddens the first cell.

**L2: store plus chokepoint (behaviour-neutral for pending harnesses).** Files:
- a new `cli_store.py`;
- a new `seat_cli.py` (`resolve_for_seat`);
- `panel_invoker.py` (`_seat_provider_source` and `_resolve_claude_executable` delegate to it);
- `seat_preflight.SeatMode.cli_payload_sha256`;
- new tests `tests/test_cli_store.py` and `tests/test_seat_cli_chokepoint.py`.

Acceptance:
- [ ] Capture writes an immutable entry whose re-hash matches. A tampered `entry.json` or a tampered payload refuses `seat_cli_qualification_store_unsafe`.
- [ ] Moving a pointer is atomic. Prune never removes `active`, `previous` or a leased entry.
- [ ] An AST cell finds no `shutil.which` in any review-seat resolution path outside `seat_cli.py`. Executor and allow-list sites are excluded by name.
- [ ] With `ADAPTERS` empty, every existing seat-route test is unchanged and green.

Falsifier: re-adding `shutil.which` to `_resolve_claude_executable` reddens the AST cell.

**L3: codex, grok and claude adapters, the watcher, and seats launching active (enforcing, per Q6).** Files:
- `cli_qualification.py`: the three adapters, each declaring its update suppressors and flag list; claude leaves `PENDING_ADAPTERS`. The codex adapter measures whether a standalone install's payload is the binary alone or the release-directory tree (`codex-resources/`, `codex-path/`), and records the result in the PR body;
- `cli.py`: `run`, `watch`, `activate`;
- `panel_invoker.py`: the preflight pins and leases, and spawn launches the pinned entry;
- `doctor.py`;
- `docs/ops/cli-qualification-watch/` (new);
- a new `tests/test_cli_qualification_seat_route.py`.

Acceptance:
- [ ] **Failing upgrade.** With the store holding qualified version A and `PATH` changed to a version B that fails `completion`, a watch tick leaves `active` = A. The next seat launches A's digest with class `locally_qualified`, and the notice is `seat_cli_running_last_good`. No `MODE_DEGRADED`, no `MODE_SEALED`.
- [ ] **Passing upgrade.** With B passing, one tick moves `active` to B. The next board launches B. No board-path call to `ensure_admitted` is made (a spy counts zero in preflight and in spawn).
- [ ] **Self-update.** Replacing the `PATH` file after capture, or moving a vendor symlink, leaves the launched bytes equal to the pinned digest.
- [ ] **Mid-board move.** Moving `active` between preflight and the second leg's spawn leaves both legs on the preflight-pinned digest.
- [ ] **No qualified version.** An empty store gives a preflight `MODE_DEGRADED` `seat_cli_unqualified` and a spawn DEGRADED result, each with the fix line. The `PATH` binary is never launched.
- [ ] **Counting** (old PR7, folded in under Q6 option 1). `counts_toward_landing` reads `cli_admission_class` for every harness. A leg without `locally_qualified` or `release_qualified` cannot approve, its `DISAGREE` still blocks, and agy's counting cells are unchanged.
- [ ] **Carried from the 2026-10-08 plan's PR3 and PR4:** never sealed (including codex and grok route-None with the host sandbox unavailable); the candidate token crosses `invoke_panel`'s thread hop; one lookup per spawn; eligibility parity; no sealed extension; completeness with only `gemini` pending; the Omnigent guard; a jail pass plus a `failed` CLI is `MODE_DEGRADED`; a native claude fill is not CLI-gated.
- [ ] **Live.** One watch tick per harness on a Linux host. The PR body records each operation's result, wall time and inference cost, plus the suppressor measurement for each harness.

Falsifiers:
- Letting spawn re-read `active` reddens the mid-board cell.
- Moving the pointer on `failed` reddens the failing-upgrade cell.

**L4: failure diagnostics, the notice and issue filing.** Files:
- `cli_qualification.py` (the failure schema and writer);
- a new `cli_qualification_report.py` (the `gh` filer);
- `seat_jail.NOTICES` and `_HARNESS_DETAIL_CODES` (`seat_cli_running_last_good`);
- new tests.

Acceptance:
- [ ] The schema refuses free text, a path-shaped field, a host-shaped field or an extra field.
- [ ] An isolation-class or transient failure produces no `gh` invocation (spy).
- [ ] A repeat contract failure for the same harness edits the one open issue. It does not create a second.
- [ ] With filing not enabled, there is no `gh` call.

Falsifier: allowing `reason: "isolation"` through the filer reddens the spy cell.

**L5: agy onto the contract and the store (lands with the 0.7.28 cut).** This is old PR5, extended. Files:
- `agy_qualification.py`, which delegates its store, lock, classes, transient rule and key to `cli_qualification`. Its key drops `__version__`, its payload gains `written_under`, and it gains `has_record` (agent-harness#1481, agent-harness#1527).
- `gemini_heartbeat.admit`, which resolves through `seat_cli.resolve_for_seat`.
- `_preflight_gemini_heartbeat`, which becomes lookup-only, so first use moves to the watcher.
- `gemini` leaves `PENDING_ADAPTERS`.

The v1 migration rule is unchanged: entries are ignored and never translated, and the watcher re-establishes each host once. The route-core pins and the requalification forced by the edit are done in the same cut.

Acceptance:
- [ ] A host whose `PATH` agy fails qualification while the store holds an earlier qualified agy runs that earlier agy, with `seat_cli_running_last_good`. This is the live agy 1.3.4 shape, reproduced with fixture images.
  - On a host whose store is new and whose only local agy is the failing one, there is no last good version yet. Only Q7 option 1 restores that seat: a seeded shipped member. Under Q7 option 2 it stays DEGRADED until a passing agy arrives.
- [ ] `_preflight_gemini_heartbeat` never calls `ensure_admitted` (spy).
- [ ] After a simulated runtime upgrade with unchanged route core, the record is still found, and `doctor` names its `written_under`.
- [ ] All PR1 per-caller admission cells are unchanged and green. `--source-only` passes on the cut tree.

Falsifier: a v1-translating shim reddens the absent cell.

**L6: feedback loop (old PR6, reshaped by Q10 and Q11).** It covers (G):
- `cli-qualification export --sign`;
- the promotion workflow step;
- catalog v2;
- `scripts/verify_qualified_cli.py`;
- the publication member-set change.

It keeps old PR6's acceptance cells (a payload mismatch fails, `upstream_provenance=None` fails, the agy route verifies as before). It adds these:
- [ ] A record with a signature from an unenrolled key fails.
- [ ] Fewer than the quorum of distinct signers fails.
- [ ] Two records from one signer count once.

**L7: counting enforcement (old PR7).** Under Q6 option 1 it folds into L3 (the counting cell above) and is not a separate PR. Under option 2 it is old PR7 unchanged, in the release after L3.

## Changes
The PR sections above list the files. New entities:
- `cli_store.py`: `Entry`, `capture`, `open_verified`, `active`, `previous`, `activate`, `lease`, `prune`.
- `seat_cli.resolve_for_seat`.
- `cli_qualification`: `qualification_inputs`, `Store.has_record`, `FAILURE_SCHEMA`, `watch_tick`.
- `cli_qualification_report.file_or_update`.
- `SeatMode.cli_payload_sha256`.
- The code `seat_cli_running_last_good`.
- The CLI commands `phase-loop cli-qualification run|watch|activate|export --sign`.

**Vocabulary.** `_HARNESS_DETAIL_CODES` is a closed allowlist. This plan adds exactly one code, `seat_cli_running_last_good`, plus the six that the 2026-10-08 plan already added. No existing entry changes, and no existing test file is edited. New test files only, as in the 2026-10-08 plan, because `test_seat_notices.py` nodes are cited by mutation receipts.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` (modify):
  - L1: the generic section gets the re-key and the transient rule.
  - L2 and L3: the store, the pointer and the watcher.
  - L4: failure reporting.
  - L5: agy's first-use section gets the "board never qualifies" rule.
- `docs/ops/cli-qualification-watch.md` and its unit templates (add, L3): installing the watcher, `status`, `activate` rollback, `clear`, and disk use (about three payloads per harness).
- `docs/ops/agy-upstream-watch.md` (modify, L5): a pointer to the generic watcher. `agy_watch` stays until L6.
- `docs/ops/cli-qualification-promotion.md` (add, L6).
- `docs/releases/outside-agent-release-handoff.md` (modify, L6): re-check only the newest member.
- `CHANGELOG.md` (modify): one entry per PR.
- `.consiliency/plans/detailed-cli-qualification-parity-20261008-0615.md` (modify, this PR): an append-only revision-history line pointing here.

## Dependencies & order
- L1 must come before any adapter writes records, while the generic store is still empty.
- L1 → L2 → L3 → L4.
- L5 needs L1–L3 and a release cut.
- L6 needs L5 and the answers to Q10 and Q11.
- L7 folds into L3 under Q6 option 1. Under option 2 it follows the release that ships L3.
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

Live:
- **L3 and L5:** `phase-loop cli-qualification watch` once per harness on a Linux host, then `status` and `doctor`.
- **L3:** a forced failing candidate made from a fixture image, never by running an installed agy directly.
- **L4:** dry-run the filer against a scratch repository.

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
- **Q7. A host with no good version at all** (a fresh store, or the only local version fails). This decides whether the host behind agent-harness#1602, whose only agy is the failing 1.3.4, gets its Gemini seat back at the 0.7.28 cut.
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

## Revision history
- **r1** (2026-10-14): first draft, amending the 2026-10-08 plan's section (e).
