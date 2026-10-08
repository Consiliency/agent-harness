# Detailed plan: per-host CLI qualification parity for every seat harness (r2)

## Task
Implement the three maintainer decisions of 2026-10-08:

1. **Parity.** Every harness that can fill a seat gets the same per-host CLI qualification model that only agy has today. That covers claude, codex, grok, gemini/agy and opencode, plus pi and cursor-agent once they can fill a seat. See (b) for which of them the local hook can reach.
2. **Relax agy.** A new upstream agy release becomes an advisory warning, not a blocker. First-use self-qualification on each host covers new versions. The full source pin of runtime files stays, and so does the release-time requalification of listed members.
3. **Feedback loop.** A version that a host qualifies for itself becomes a reviewable candidate. A maintainer can promote it into the shipped list, but only through a re-verifiable step. A record from another host is never trusted as-is.

Out of scope:
- **The seat sandbox/jail design itself.**
- **The existing sandbox refusals that choose `sealed` today** (`SEALED_FALLBACK_CODES`). Removing that path is agent-harness#1244 PR-A1's job (the resolver plus the argv-level sealed guard), and this plan does not redo it. This plan only guarantees that **its own** refusals never reach `sealed`, on every path; see (a), "Never toolless".
- **The president ladder.**
- **Executor (non-seat) launches.** `launcher.py`'s `trusted_command` (around l.2696) and the `EXECUTOR_TRUSTED` role (`admitted_command`, PI:4939) are not seats. They keep release-only admission and are not CLI-qualified.

**Size.** This plan exceeds the skill's bounded-plan threshold. It is one umbrella document with seven PRs, each with its own acceptance criteria and falsifier, because the PRs share one contract and one trust model.

## Research summary
**agy today.** A qualified agy image is identified by its binary sha256 plus the sha256 of its `--help` output. The version is a label only.
- `gemini_heartbeat.QUALIFIED_IMAGES` (`gemini_heartbeat.py:21`) must equal `plans/evidence/qualified-provider-images.json` (`verify_qualified_agy_image.py`, VS). `catalog_route()` (VS:57) requires the single route `gemini_heartbeat_linux_x64`.
- **First use** goes `agy_qualification.ensure_admitted` (AQ:1130) → `qualify_image` (AQ:1247) → `run_operation` (AQ:523), once for each of the three `OPERATIONS` (AQ:50).
  - `ensure_admitted` is called only by the whole-board preflight (`_preflight_gemini_heartbeat`, around PI:6240) and by `agy-qualification run`.
  - Legs re-admit by `lookup` (AQ:1094).
  - The qualification's own launches carry an explicit `qualification_candidate` Admission (`_run_help`, AQ:1052-1060).
- **Release fast path.** Release members are admitted offline by `gemini_heartbeat.admit()` (around GH:161), before any config, store or network access. `lookup` returns only `locally_qualified`, and only after checking the user opt-out first.
- **The memfd pattern.** The admitted bytes are carried as a sealed memfd (`VerifiedImage`). The path is never reopened.
- **Store and runtime identity.**
  - The store is `Store.host_dir` (AQ:791). Entries are HMAC'd over a context bound to image, platform, runtime, profile and help (AQ:958-984).
  - A v1 `qualified` entry stores only `operations` and `release_version`. Its runtime identity lives in the filename hash and the MAC, not in the payload.
  - Runtime identity is `__version__` plus the `ROUTE_CORE` digests (AQ:44, AQ:74-82).

**Claude.** The jail pass store `seat-jail-passes/<digest>.json` is keyed by the jail-profile digest (`seat_jail.py:1061-1079`), the host and the falsifier layout. It is not keyed by the CLI binary.

**Codex, grok and opencode** have the agent-harness#1282 owner and typed refusals only.

**The seat path** (read in this session):
- **Spawn-time route.** `_seat_route_for_spawn` (PI:11049) returns `(None, [], None)` both for `not eligible` and for `route is None`, before any hook (PI:11068-11075). `route is None` is the codex, grok and opencode case.
- **Preflight.** `_seat_launch_modes` handles native fill first (PI:1984), then non-brokered launches (`sealed`), then the `route is None` branch, which yields `unconfined` or **`sealed`** (PI:1995-2003). Only after that does it check `refusal` (PI:2004-2012). A refusal on a route-None leg therefore never reaches the degraded branch.
- **Callers of `_seat_route_for_spawn`.** The preflight (PI:1994), `_seat_jailed_at_launch` (PI:11104) and `_default_spawn` (PI:11281).
- **Omnigent seats.** `_route_omnigent_seat` (PI:12617) never visits `_seat_route_for_spawn`. Opencode has no homebrew seat launch builder. Governed review refuses gateway execution today.
- **`SeatMode.qualified_now`** (`seat_preflight.py`, around l.201) is a bool meaning "the jail qualified just before this board".

**Launcher identity.** `_seat_provider_source` (PI:4555) follows only `codex.js` to its native musl binary. Every other harness hashes the first resolved file. That file can be an npm node shim, a shell or pyenv wrapper, or a JS entry that spawns a native optional dependency.

**`agy_integrity.check` has five callers:**
- credential refresh (PI:4679);
- the owned non-heartbeat seat (PI:4774);
- `admitted_command` (PI:4939, executor);
- `trusted_command` (`launcher.py:2696`, executor);
- `agy_canary_evidence.py:924`.

It admits only `QUALIFIED_IMAGES` members.

**The upstream job.** The newest-upstream check is `require(len(latest) == 1, …)` (VS:165). It runs only in `qualified-agy-image.yml`'s `upstream` job (l.74-85, schedule or dispatch). After it, the step checks that one member's vendor asset digest, URL prefix and archive (VS:166-180). `publish-pypi.yml:51-57` runs only `--source-only`, and no test pins the `upstream` job.

**The agent-harness#1244 join.** agent-harness#1244's plan (merged as agent-harness#1245; `plans/detailed-1244-seat-route-resolver-20261004.md`) makes `resolve_seat_route` a pure resolver. It also rebuilds `_seat_route_for_spawn` and `_publish_seat_modes` from that resolver. Its implementing PR, PR-A1, is not open, and `resolve_seat_route` does not exist on main.
- Its split matches this plan's re-entrancy rule: the **walk** may run first use, and **derive** is read-only.
- Qualification outcomes enter it as resolver **inputs** gathered before the call (`jail_qualification`).
- It does not replace `_seat_provider_source`.

agent-harness#1308 (merged) is why the full source pin stays.

## Design

### (a) The harness-agnostic qualification contract
A **qualified CLI version** is a key that passed every operation that applies, on this host, under this runtime, through the seat's production launch path.

**The key is `(harness, platform, payload_identity, interpreter_identity?, help_digest, runtime_identity)`.**

- **`payload_identity` is what actually executes, never a shim.** Each adapter declares a payload resolver. It follows the launcher to the executed artifact:
  - **A native single binary** (agy, claude native install, codex's musl binary, opencode's platform-package binary, grok-native): the sha256 of that file.
  - **A script package** (npm `cli.js`-style): a tree digest over the adapter-declared **closure**. That closure is the package root plus each named platform-dependency root it spawns, such as a sibling `node_modules/@scope/<pkg>-<platform>`. The digest is the sorted list of (closure-relative path, mode, file sha256).
  - **Anything the resolver does not recognise** (a shell or pyenv wrapper, or an unknown shim) is refused with `seat_cli_qualification_unavailable` (degraded). A wrapper is never hashed in place of its payload.
- **The launch runs the verified bytes.** The admitted bytes are what runs, as agy does today:
  - A single binary runs from a sealed memfd (`VerifiedImage`), bound with `--ro-bind-data` or executed from the fd.
  - A script package runs from a private, read-only snapshot of the verified tree in the seat's stage. The snapshot is re-hashed after the copy, together with the verified interpreter image.
  - A self-update between admission and launch therefore cannot substitute bytes. A mismatch refuses with `seat_cli_unqualified`.
- **`interpreter_identity`** (Q2) is the sha256 of the interpreter that the **launch** uses. That is the one resolved inside the owner's launch environment, which is not necessarily the qualifying shell's `PATH`. It is part of the **local** key only (see the r2 application note under the rulings).
- **`help_digest`** is the sha256 of the adapter's option-surface probe. The probe's argv(s) cover every flag the seat's launch builder uses. Stdout and stderr are captured together.
  - It runs from the verified bytes, inside the owned profile, in a **pinned environment**: `LC_ALL=C.UTF-8`, `COLUMNS=200`, `TERM=dumb`, `NO_COLOR=1`, a private `HOME`, a fixed `PATH`, and each adapter's declared update/banner suppressors.
  - The user's environment never reaches it.
- **`runtime_identity`** is `__version__` plus the digests of `cli_qualification.py` and the adapter's own module. agy's `ROUTE_CORE` tuple is unchanged.
  - Launch-builder changes in `panel_invoker.py` are covered by `__version__` on released installs, following the agy precedent.
  - The accepted gap: a dev install with an unchanged `__version__` does not requalify on a builder edit.

**Operations.** Each operation runs through the seat's production launch path:

| op | meaning | applies to |
|---|---|---|
| `identity` | resolve the payload, hash it, and measure the help digest in the pinned environment | every adapter |
| `completion` | one short prompt; a parseable answer within the deadline | every adapter |
| `cancel` | SIGTERM after progress is observed; a clean terminal state and no surviving process | every adapter |
| `owner_loss` | SIGKILL the owner; the provider tree is gone and no terminal record exists | every adapter. Every adapted route is an owned review-seat launch: the agy broker, the claude jail, and the agent-harness#1282 owner for codex and grok. |

**Platform scope.** The observers use `/proc` and `nsenter`, and owned launches already refuse on non-Linux with `seat_owner_unavailable` (around PI:325).

| platform | scope |
|---|---|
| linux-x64, linux-arm64 (glibc) | every adapter |
| linux musl | per adapter, as declared |
| macOS, Windows, WSL | out of scope until a seat can fill there. The outcome is `seat_cli_platform_unsupported` (degraded). An adapter's platform set must grow before any seat fills on a new platform; the completeness test enforces it. |

**Classes.**
- `release_qualified`, `locally_qualified` and `qualification_candidate` keep their agy meaning.
- `none` marks a launch made without a class during the recording-only release (see "Refuse versus record").

**Re-entrancy (agy's split).**
- **First use** (`cli_qualification.ensure_admitted`) runs only in two places:
  - the board preflight, which is `_seat_launch_modes` and, after agent-harness#1244, the resolver **walk**;
  - `phase-loop cli-qualification run`.
- **Spawn** (`_default_spawn`), `_seat_jailed_at_launch` and the agent-harness#1244 **derive** call `cli_qualification.lookup` only. Lookup is read-only and never executes operations.
- **Qualification's own launches** carry a typed `qualification_candidate` token, bound to the key being qualified. The token lives in a context variable set only by the operations runner. Lookup returns it without consulting the store, and a nested `ensure_admitted` under the token raises.
- **Seat deadlines.** First use happens in the preflight, before any seat deadline starts, so it never counts against the triggering board's seat deadlines. Different harnesses' first uses may run concurrently. Their locks are independent.

**Refuse versus record.** In the recording-only release (Q1), only these outcomes **refuse**:
- `failed` (an identity or isolation violation);
- `store_unsafe`;
- verified-bytes mismatch at launch;
- `seat_cli_qualification_unavailable` (an unrecognised wrapper: there is no payload to vouch for);
- `seat_cli_platform_unsupported`.

Everything else launches and records its class:
- `locally_qualified` / `release_qualified`;
- `none`, for opt-out, a first use that ended transient, or an absent key on a path with no preflight.

PR7 changes **counting** only. It never adds refusals.

**Failures.**
- **Identity or isolation `failed`** is sticky until `phase-loop cli-qualification clear --harness <h>`.
- **A transient-derived `failed`** (the third consecutive transient) expires after 24 h or on any key change. When PR5 moves agy onto the contract, agy adopts the same rule.
- **Cancellation** writes nothing.

**Lock and store.**
- There is one `flock` per user, host and harness, under the user's own `$XDG_STATE_HOME`. Users never contend on a shared lock.
- The store is `$XDG_STATE_HOME/phase-loop/cli-qualification/hosts/<machine>/<harness>/`. It has agy's discipline: 0700/0600, euid-owned, `O_NOFOLLOW`, with a per-host HMAC over the type, euid, machine-id and live key.
- It is **new** and orthogonal to `seat-jail-passes/`. A jailed claude seat needs both a jail pass and a CLI qualification.

**Opt-out.** User config only: `[qualification.<harness>] self_qualification = false`. `[agy] self_qualification` keeps working, and a repository config cannot opt out. An opted-out harness launches with class `none`, so after PR7 its legs do not count.

**Notices.** The new codes are additive. Each has what/why/fix text in `seat_jail.NOTICES`, and the fix lines name `phase-loop cli-qualification status|run|clear --harness <h>`:
- `seat_cli_unqualified`
- `seat_cli_qualification_failed`
- `seat_cli_qualification_unavailable`
- `seat_cli_qualification_store_unsafe`
- `seat_cli_adapter_missing`
- `seat_cli_platform_unsupported`

No existing code is renamed.

**Never toolless.** Every `seat_cli_*` refusal is a terminal `MODE_DEGRADED` (not run) with its typed fix line. It never falls to another rung, and it never reaches `sealed`.
- **Today's code.** The CLI gate runs in `_seat_launch_modes` **before** the `route is None` and non-jailed branches, and in `_default_spawn` **before** `_seat_route_for_spawn`. So the codex, grok and opencode route-None paths cannot turn a CLI refusal into `sealed`.
- **After agent-harness#1244 PR-A1.** CLI admission becomes a **step-1 input**, gathered before the call like `jail_qualification`.
  - The agent-harness#1244 plan excludes a claude seat under Claude Code from step 1 (its l.149), so PR4's native-fill cell holds in both shapes.
  - Once step 1 is attempted, a `seat_cli_*` refusal is terminal and resolves to step 4 (`degraded`). It deliberately does **not** descend to step 2 (remote) or step 3 (host-native). That is a narrowing of agent-harness#1244's chain for this refusal class: the local CLI failed its own identity check, and a stand-in would hide that from the operator.
  - Today steps 2 and 3 do not exist for codex, grok or gemini, so behaviour is the same in both shapes.

Whichever PR lands second adapts to the other, and the acceptance cells below drive both shapes.

### (b) Per-harness adapters and their reach
There is one `ADAPTERS` table. Each adapter declares:
- the payload resolver;
- the interpreter rule;
- the help-probe argv(s) and suppressor env;
- the completion request, built by the seat's own launch builder;
- progress observation, for `cancel`;
- its platform set;
- `upstream_provenance`, or `None`;
- `fetch_member(version)`, for the release lane.

The adapters hold no fleet paths or markers.

**Reach.** The hook covers every harness with a **local owned seat launch builder**: claude, codex, grok and gemini/agy.
- **opencode, pi and cursor-agent** fill seats only through Omnigent (`_route_omnigent_seat`, PI:12617). Omnigent is a gateway whose CLI is not launched by this runtime, and a local pass must not stand in for it.
  - They get adapters in the PR that gives them a local owned launch builder.
  - **Guard test.** `_route_omnigent_seat` stays unreachable from governed review, so the PR that enables that path must add qualification at its execution boundary.
- **Completeness test.** `ADAPTERS ∪ PENDING_ADAPTERS` equals the set of harnesses with a local owned launch builder.
  - `PENDING_ADAPTERS` names claude (until PR4) and gemini (until PR5). It is empty after PR5.
  - A harness in neither set refuses with `seat_cli_adapter_missing`.
  - A pending harness keeps its existing admission (the claude jail, `agy_qualification`) until its PR lands.

**Preflight output.** The preflight records the class in a **new** `SeatMode.cli_admission_class` field, an additive change to `seat_modes.v1`. Board evidence records it per leg. `qualified_now` keeps its jail meaning.

### (c) agy relaxation (decision 2)
**What changes:**
- **`verify_qualified_agy_image.py --upstream-only`.**
  - A newest upstream release that is not a member prints `::warning::newest upstream agy <v> is not a shipped member; hosts self-qualify it on first use` and records `latest_is_member: false` in the JSON.
  - It then fetches the **newest shipped member** by tag (`/releases/tags/<v>`) and runs the existing vendor asset digest, URL prefix and archive checks against it.
  - Those checks stay `require`s. The workflow step stays without `continue-on-error`, so the job reds on any member-integrity failure and never on membership.
- **The release recipe** stops listing "`--upstream-only` passes" as a cut criterion: `docs/releases/outside-agent-release-handoff.md` (around l.66) and the caveats.
- **A new seat-only entry, `agy_integrity.admit_for_seat(path, env)`,** used only at PI:4679 (the `gemini_profile is None` branch) and PI:4774. It works in this order:
  1. Release members are admitted offline, as now, before any config or store access.
  2. Otherwise it calls `agy_qualification.lookup(env, data, path)`. On `gh.AdmissionMiss` it closes the carried image and raises `AgyImageUnqualified`, so no memfd leaks and no exception is swallowed.
  3. **Why it does not recurse.** `lookup`'s help measurement (`_run_help`, AQ:1052-1060) launches with its own `qualification_candidate` Admission and a profile. Its launch therefore takes the profile branch at PI:4669-4675 and never reaches PI:4679's `gemini_profile is None` branch or PI:4774. A PR1 cell pins this.
- **`check(path)` is unchanged** for the executor and canary callers (PI:4939, `launcher.py:2696`, `agy_canary_evidence.py:924`), which stay release-only.
- **Evidence.** A `locally_qualified` record admits the owned non-heartbeat route because shipped members already do. Shipped members are qualified on the same `gemini_heartbeat_linux_x64` route and admitted on the owned route by identity. Local admission uses the same identity binding (image and help) with the same operations.

**What stays, unchanged:**
- `publish-pypi.yml` `--source-only` (blocking).
- `--route-core` on every PR.
- `agy_full_pin_scope.sh`.
- Live requalification of listed members at the cut.
- `QUALIFIED_IMAGES` == catalog.
- `agy_watch` draft PRs.

### (d) Feedback and promotion, with its trust model
**Export.** `phase-loop cli-qualification export --harness <h>` writes `cli_qualification_candidate.v1`. It is a closed JSON Schema with `additionalProperties: false` at every level:

```
harness: enum(ADAPTERS)          platform: enum(linux-x64, linux-arm64, linux-x64-musl, linux-arm64-musl)
version_label: ^[A-Za-z0-9 ._()+-]{1,64}$
payload_sha256, help_sha256: ^[0-9a-f]{64}$     payload_kind: enum(binary, tree)
runtime_identity: {version: PEP 440 string, route_core: {<enum of route-core file names>: ^[0-9a-f]{64}$}}
agent_harness_version: PEP 440 string            ops: {<enum op>: const "passed"}
utc: RFC 3339 UTC timestamp
```

- The export never includes the interpreter hash, an HMAC, a machine-id, a hostname, a path, a username, environment, credentials or receipts.
- The exporter validates its own output and refuses to write a failing record.

**Submission (Q4).** Submission is manual: the operator attaches the record to a promotion PR or an issue.

**Promotion is the only way the shipped list grows (Q3).**
1. **Upstream check.** The adapter's `upstream_provenance` fetches the artifact from a **publisher-published digest**, and CI matches `payload_sha256` against it.
   - agy uses `agy_provenance`.
   - npm-shipped CLIs use the registry `dist.integrity` of the package whose tarball holds the payload. For codex that is `@openai/codex-linux-<arch>`, not `@openai/codex`.
   - The adapter declares claude's source in PR6.
   - An adapter with `upstream_provenance = None` (grok and opencode today) cannot be promoted. That rule is enforced by the verifier, not by convention.
2. **Release-lane record.** The maintainer, as release lane, runs `phase-loop cli-qualification release-record --harness <h> --version <v>` on a release-lane host.
   - It downloads the artifact with `fetch_member`, re-runs every operation, and writes a redacted record that the verifier checks against the payload hash.
   - It is committed as a separate commit on the promotion PR. Until that commit exists, the promotion PR is red by design, and the runbook says so.
3. **The candidate's `ops` are never read.** The candidate is a lead, never evidence.

**Shipped npm members (Q2 application).** A shipped member binds `(harness, platform, payload, help)`, without the interpreter. On a consuming host, `release_qualified` still measures `help_digest` locally in the pinned environment under the launch interpreter. A broken interpreter fails or changes the help digest, and the member then decays to first use.

This is deliberately different from agy's release fast path, which admits offline without executing anything. A shipped npm member's admission executes the help probe, because its interpreter is not part of the shipped identity. A shipped native-binary member admits offline, as agy does.

**Consumption.** Other hosts skip the live operations only for **shipped** members, never for peer candidates.

**Pruning.** A member is removed by a maintainer PR. The verifier allows removal and requires nothing for it. Under Q5 every listed member is requalified at each cut, which keeps lists short. The runbook notes that promoting fast-moving CLIs, such as claude, buys little.

### (e) Phasing: seven PRs
Each PR is small and lands in order. "Tests-first" means the corpus skips contracts that are not implemented yet in ordinary runs, rather than failing. Each PR body records measured wall time and inference cost per harness for any live run.

**PR1: agy relaxation.** Files:
- `phase-loop-runtime/scripts/verify_qualified_agy_image.py` (membership advisory; member integrity by tag)
- `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py` (`admit_for_seat`)
- `panel_invoker.py` (PI:4679 and PI:4774 call `admit_for_seat`)
- tests: a new `tests/test_agy_upstream_advisory.py` and a new `tests/test_agy_integrity_seat_admission.py`. No existing test file is edited.
- `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`, `CHANGELOG.md`

Acceptance:
- [ ] With a fixture where the latest upstream is not a member, `--upstream-only` exits 0 with the warning.
- [ ] With a fixture where the newest shipped member has a mismatched asset digest, a mismatched URL or a mismatched archive, it exits non-zero.
- [ ] The `upstream` workflow step has no `continue-on-error`, and `test_publication_is_gated_on_the_full_pin_set` is unchanged and green.
- [ ] `admit_for_seat` admits release members with self-qualification disabled.
- [ ] `admit_for_seat` admits a `locally_qualified` image, and refuses an absent, failed or tampered store.
- [ ] On `AdmissionMiss`, the image fd is closed.
- [ ] Under `lookup`'s help measurement, `admit_for_seat` is not re-entered (a spy on it records zero calls).
- [ ] `check` still refuses a `locally_qualified` image, with one cell per executor/canary caller.

Falsifiers:
- Wrapping the step in `continue-on-error` reddens the workflow cell.
- Dropping the member-digest `require` reddens the mismatch cell.
- Routing `check` through `lookup` reddens the executor cell.

**PR2: the contract module and the status/clear CLI, inert.** Files:
- a new `cli_qualification.py`: key, payload and tree digest, pinned probe environment, classes, operations runner with the candidate token, `lookup`, `ensure_admitted`, store, per-user lock, transient expiry, and candidate schema plus validator
- `phase-loop cli-qualification status|clear`
- `seat_jail.NOTICES` and `_HARNESS_DETAIL_CODES` (PI:2824), for the six codes
- `seat_preflight.SeatMode.cli_admission_class`
- a new `tests/test_cli_qualification_contract.py`
- the new "CLI qualification (all harnesses)" section of `advisor_board/CONTRACTS.md`

Acceptance:
- [ ] **Store safety:** wrong permissions, a symlink, or a foreign euid each make the store refuse.
- [ ] **HMAC:** a tampered entry refuses.
- [ ] **Failure rules:** a transient-derived `failed` expires after 24 h or on a key change, while an identity `failed` stays sticky.
- [ ] **Tree digest:** a byte-identical shim over a changed payload changes the key, and a changed imported module in a tree changes the key (codex F007's case).
- [ ] **Pinned probe:** the same binary under two different user environments gives the same `help_sha256`.
- [ ] **Re-entrancy:** a nested `ensure_admitted` under the candidate token raises.
- [ ] **Export schema:** the schema refuses a path-shaped, host-shaped or extra field.
- [ ] **Sealed set:** no new code is in `SEALED_FALLBACK_CODES`.

Falsifiers:
- Hashing the entry file instead of the tree reddens the payload-change cell.
- Removing the HMAC check reddens the tamper cell.

**PR3: codex and grok adapters, wired (recording only).** Files:
- `cli_qualification.py` (the codex and grok adapters, `PENDING_ADAPTERS`, `run`)
- `panel_invoker._seat_launch_modes` (first use before the route-None and non-jailed branches)
- `_default_spawn` (lookup before `_seat_route_for_spawn`, and launching the verified bytes)
- `_seat_jailed_at_launch` (lookup only)
- `seat_preflight.py`
- tests: a new `tests/test_cli_qualification_seat_route.py`, and an Omnigent guard cell

Acceptance:
- [ ] **First use and launch:** on a fresh store, preflight first use runs, and the seat launches with `cli_admission_class=locally_qualified`.
- [ ] **No first use at spawn:** a spawn with no preflight record performs **no** operation and launches with class `none`.
- [ ] **Never sealed:** for codex and grok, a seeded `failed`, `store_unsafe`, wrapper-unavailable or platform-unsupported outcome gives a preflight `MODE_DEGRADED` and a spawn DEGRADED result with a fix line. This holds with the host sandbox available and also when it is unavailable, so the existing sandbox refusal is in play. The result is never `MODE_SEALED`.
- [ ] **Re-entrancy:** a qualification operation's launch never calls `ensure_admitted`.
- [ ] **Self-update:** swapping the binary after admission refuses `seat_cli_unqualified` at launch.
- [ ] **Completeness:** the completeness test passes with claude and gemini pending.
- [ ] **Omnigent guard:** `_route_omnigent_seat` stays unreachable from governed review.

Falsifiers:
- Moving the gate after the `route is None` branch reddens the sealed cell.
- Calling `ensure_admitted` from `_default_spawn` reddens the no-first-use cell.

**PR4: claude adapter.** Files:
- `cli_qualification.py` (the claude adapter for the native binary and the npm tree; removed from pending)
- the same `panel_invoker` gate sites
- tests

The jail pass store is untouched.

Acceptance:
- [ ] A jail pass plus a `failed` CLI record gives `MODE_DEGRADED` `seat_cli_qualification_failed`.
- [ ] A CLI pass with no jail pass keeps today's `seat_jail_qualification_failed` or `jail_unqualified` notice.
- [ ] A jail-pass digest file planted under the CLI store is absent to `lookup`, and a CLI entry planted under `seat-jail-passes/` is absent to `pass_record_verdict`.
- [ ] A claude seat filled natively under Claude Code (PI:1984) is not CLI-gated, because no CLI is launched.

Falsifier: delete the CLI gate for claude, and the first cell reddens.

**PR5: agy onto the contract (lands with a release cut).**
- **Code.** `agy_qualification.py` delegates its store, lock, classes, transient rule and expiry to `cli_qualification`. It keeps its broker operations and provenance. `gemini` is removed from pending.
- **CLI.** `phase-loop agy-qualification run|status|clear|watch` stays as an alias of `phase-loop cli-qualification … --harness gemini`; `watch` remains agy-only. Docs and fix lines keep working.
- **Why the cut.** It touches `ROUTE_CORE`, so it lands with a release cut, where full requalification already happens.
- **Migration.** A route-core edit plus a release changes `runtime_identity`, so no v1 entry can match the live key. That is already true at every release today. Therefore:
  - v1 entries are **ignored**, never translated;
  - each host re-runs agy first use once, exactly as after any release;
  - the v1 directory is left in place, and `phase-loop cli-qualification clear --harness gemini --legacy` removes it.

Acceptance:
- [ ] A host holding only v1 entries looks up as absent and preflight first use runs. No v1 entry is ever read as a pass.
- [ ] All PR1 per-caller admission cells stay green.
- [ ] `verify_qualified_agy_image.py --source-only` passes on the cut tree with a fresh record.
- [ ] The completeness test passes with `PENDING_ADAPTERS` empty.

Falsifier: a shim that translates v1 entries reddens the absent cell.

**PR6: export, catalog v2, promotion and the generic verifier.** Files:
- `cli_qualification.py` (`export`, `release-record`, `fetch_member`, `upstream_provenance`)
- `plans/evidence/qualified-provider-images.json` → v2, with routes keyed by `(harness, platform)` and the agy route carried byte-equivalently
- `verify_qualified_agy_image.py` (reads v2; existing flags unchanged), with a new `scripts/verify_qualified_cli.py` for the other routes
- a new workflow step that re-verifies promotion PRs
- `docs/ops/cli-qualification-promotion.md` (new)

PR6 greps for every reader of the catalog and updates them in the same PR.

Acceptance:
- [ ] A promotion whose `payload_sha256` does not match the upstream artifact fails.
- [ ] A promotion without a release-lane record fails.
- [ ] A promotion for an adapter with `upstream_provenance = None` fails.
- [ ] An exported record validates and contains no interpreter hash.
- [ ] A shipped npm member admits as `release_qualified` on a host with a different node, once the local help digest matches.
- [ ] The agy route verifies exactly as before.

Falsifier: point a candidate at a different upstream asset, and the CI step reds.

**PR7: counting enforcement for non-agy legs (Q1; the release after PR3 and PR4 ship).** Files:
- `agy_qualification.counts_toward_landing` / `president_input_items` (AQ:1290-1330), generalized to read `cli_admission_class` for every harness
- tests

Acceptance:
- [ ] A non-agy leg with class `none`, `qualification_candidate` or no class cannot approve and contributes a `not counted` president item, and its `DISAGREE` still blocks.
- [ ] `locally_qualified` and `release_qualified` count.
- [ ] agy's counting cells are byte-unchanged.
- [ ] No outcome in the "refuse versus record" set changes.

Falsifier: drop the class check, and the `none`-cannot-approve cell reddens.

**Rollout summary:**
- First use is on by default per harness, with a user-config opt-out.
- The claude jail store is unchanged.
- agy re-runs first use once per host at the PR5 cut, the same cost as any release.
- Shipped non-agy lists start empty.
- Executor launches are unchanged.

### (f) Questions put to the maintainer
All five are ruled; see "Maintainer rulings" below. The question text is kept as history.
- **Q1. Counting.** Should a non-agy leg without a `release_qualified` or `locally_qualified` class stop counting toward landing, as agy's does? *Recommend:* yes, as PR7, after PR3 and PR4 have been live for one release.
- **Q2. Script launchers.** Does the interpreter (node) identity enter the key for npm-shipped CLIs? *Recommend:* yes. A node upgrade then triggers one cheap re-run per host.
- **Q3. Promotion without verifiable upstream provenance.** For harnesses such as grok or opencode with no published integrity digest, choose between two options:
  - *Recommended:* refuse promotion; those harnesses stay first-use only.
  - Accept a release-lane-built record keyed by a hash the release lane downloads itself. This is weaker, because there is no publisher attestation.
- **Q4. Submission channel.** Should export stay manual (attach to a PR or issue), or should a watcher in the style of `agy_watch` open draft promotion PRs from a subscribed host? *Recommend:* manual in v1.
- **Q5. Requalifying non-agy members at release.** Decision 2 keeps full requalification for agy members. Choose between two options:
  - *Recommended:* re-run every listed member of every harness at each cut. This costs about 1 min of inference per member and pushes towards a short list.
  - Re-run only the newest member per harness, and age out older ones.

### Maintainer rulings (2026-10-08)
These rulings are append-only. All five follow the recommendation, and no maintainer decision is left open.
- **Q1: yes.** A non-agy leg without a `release_qualified` or `locally_qualified` class stops counting toward landing. The first release that ships PR3 and PR4 only records the class. PR7 enforces it in the next release.
- **Q2: yes.** For npm-shipped CLIs, the node interpreter's real-path sha256 is part of the qualification key.
- **Q3: strict.** A harness with no verifiable upstream digest (today grok and opencode) is never promoted. It stays first-use only, and its shipped list stays empty.
- **Q4: manual submission in v1.** The operator attaches the exported record to a PR or an issue. There is no watcher-driven promotion PR.
- **Q5: requalify every listed member of every harness at each release cut.**

**r2 application note (2026-10-08, team-lead direction after board round 1; the rulings above are unchanged).**
- **Q2 applies to the local key.** The interpreter hash is in every host's local key. Shipped npm members do not bind it, because no publisher digest exists for a host's node build. On a consuming host the local pinned help probe, run under the launch interpreter, guards it.
- **Q3 leaves npm members promotable.** It counts npm `dist.integrity` of the payload-bearing package as a verifiable upstream digest.

## Changes
The PR sections in (e) list every file. The new entities are:
- `cli_qualification.py`: `QualificationKey`, `Adapter`, `ADAPTERS`, `PENDING_ADAPTERS`, `lookup`, `ensure_admitted`, `Store`, `export`, `release_record`
- `agy_integrity.admit_for_seat`
- the six `seat_cli_*` codes
- `SeatMode.cli_admission_class`
- `phase-loop cli-qualification status|clear|run|export|release-record`
- catalog v2

**Vocabulary.** `_HARNESS_DETAIL_CODES` (`panel_invoker.py:2824`) is a closed allowlist. Its agy block (around l.2858-2866) reads `"agy_image_unqualified", … "gemini_heartbeat_self_qualification_failed", … "gemini_heartbeat_platform_unsupported"`. This plan deliberately **adds** the six `seat_cli_*` codes, which are pinned by `tests/test_cli_qualification_contract.py`. No existing entry changes.

**Frozen status (checked).**
- I grepped `plans/`, `specs/` and `plans/manifest.json` for `_HARNESS_DETAIL_CODES`, `NOTICES` and every test file this plan names. None is on a frozen-path list or has an `sl0_repairs` entry.
- `_HARNESS_DETAIL_CODES` appears only in the agent-harness#1244 and agent-harness#896 plans.
- `test_seat_notices.py` nodes are cited by `plans/evidence/seat-jail-1132/mutation-receipts.json`, so this plan edits **no** existing test file and adds new files only.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`:
  - the generic section (PR2);
  - the promotion trust model (PR6);
  - in PR5, an **amendment** to agy's "First-use self-qualification (agent-harness#1076)" section. Its "`failed` … until `agy-qualification clear`" rule becomes "identity/isolation `failed` until clear; a transient-derived `failed` expires after 24 h or on a key change", and the section points to the generic contract.
- `docs/releases/outside-agent-release-handoff.md`: drop the upstream-pass criterion (PR1).
- `docs/ops/agy-upstream-watch.md`: upstream membership is advisory (PR1).
- `docs/ops/cli-qualification-promotion.md`: new runbook, covering release-record, pruning and which CLIs are worth promoting (PR6).
- `CHANGELOG.md`: one entry per PR.

## Dependencies & order
- PR1 is independent.
- PR2 → PR3 → PR4.
- PR5 needs PR2 and a release cut.
- PR6 needs PR5.
- PR7 needs PR3 and PR4 to have shipped in one release that only records the class (ruled, Q1).
- **No PR enables a refusal before its prerequisites exist.** The CLI with status and clear lands in PR2, before any notice names it. `run` lands with the first adapters in PR3. Pending harnesses keep their existing admission until their own PR.
- **agent-harness#1244 PR-A1.** If PR-A1 lands first, PR3 wires CLI admission as a resolver input. If PR3 lands first, PR-A1 must carry the gate into `resolve_seat_route`. In both cases PR3's never-sealed cells are the shared acceptance.

## Execution Policy
- execute: effort=high, reason=process ownership, verified-bytes launch, store integrity and a promotion trust boundary. PR1 alone: effort=medium.

## Verification
Run from `phase-loop-runtime/`:

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_verify_qualified_agy_route_core.py tests/test_qualified_agy_image_set.py  # 37 passed on origin/main 0840936d
PYTHONPATH=src python3 -m pytest -q tests/test_agy_self_qualification.py tests/test_seat_notices.py tests/test_agy_static_integrity.py
PYTHONPATH=src python3 -m pytest -q tests/test_agy_upstream_advisory.py tests/test_agy_integrity_seat_admission.py tests/test_cli_qualification_contract.py tests/test_cli_qualification_seat_route.py  # new per PR
python3 scripts/verify_qualified_agy_image.py --route-core
python3 scripts/verify_qualified_agy_image.py --source-only   # PR5 (release cut) only
```

Live checks:
- **PR3, PR4 and PR5** each need one real first-use run per harness on a Linux host: `phase-loop cli-qualification run --harness <h>`, then `status`. The PR body records each operation's actual result, wall time and inference cost.
- **PR6:** run `export`, then validate the record against the schema.

automation.suite_command: `cd phase-loop-runtime && PYTHONPATH=src python3 -m pytest -q tests/test_verify_qualified_agy_route_core.py tests/test_qualified_agy_image_set.py tests/test_agy_self_qualification.py tests/test_seat_notices.py`

## Acceptance criteria
- [ ] A newer upstream agy only warns. A shipped member's asset digest, URL or archive mismatch still reds the `upstream` job. `publish-pypi.yml` is unchanged. (PR1)
- [ ] A `seat_cli_*` refusal is `MODE_DEGRADED` with a fix line on every path, including codex and grok route-None with the host sandbox unavailable, and is never `sealed`. (PR3, PR4)
- [ ] A changed payload, a byte-identical shim over a changed payload, or a self-update after admission never runs under a qualified class. (PR2, PR3)
- [ ] A catalog member is added only when CI re-verifies its payload hash against a publisher digest and finds a committed release-lane record. Exported records contain only schema fields. (PR6)
- [ ] After PR7, non-agy legs whose class is not `release_qualified` or `locally_qualified` cannot approve, and agy's counting is unchanged. (PR7)

## Revision history
- **r1** (`1276140b`): board hb1. gemini AGREE; codex, claude and grok DISAGREE.
- **r2.** Every convergent blocker is fixed:
  1. **Never sealed:** a terminal degraded result, the gate placed before the route-None branch, and cells covering the exact paths. See (a) "Never toolless" and the PR3 cells.
  2. **Stale pass:** a payload resolver and tree digest, launching the verified bytes, and the pinned probe environment. See (a).
  3. **Re-entrancy:** the walk/preflight versus lookup split, and the candidate token. See (a).
  4. **PR1:** a seat-only `admit_for_seat` with all five callers named. See (c).
  5. **Advisory scope:** only membership becomes advisory; member integrity stays blocking. See (c).
  6. **PR5 migration:** v1 entries are ignored and one re-run happens at the cut. See PR5.
  7. **Sequencing:** pending adapters, the CLI in PR2, and the refuse-versus-record list.
  8. **Q2:** the r2 application note.
  9. **PR7:** acceptance criteria and a falsifier.
  10. **Omnigent reach:** coverage now matches the hook, plus a guard test. See (b).

  Non-blockers folded in: the platform table, first use outside seat deadlines, transient expiry, the per-user lock, `fetch_member` and pruning, the release-lane owner, `cli_admission_class`, the closed schema, PR4's cells, executor launches out of scope, and the agent-harness#1244 join.
