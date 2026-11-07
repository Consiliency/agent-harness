---
phase_loop_plan_version: 1
phase: GROK
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 33f3f073db869be2349cce35a6f7bd86f1280b3f713c8c6f8a4dfa43d4aa8cbd
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_grok_seat_containment.py", "phase-loop-runtime/tests/test_seat_credentials.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_grok_seat_jail.py", "phase-loop-runtime/tests/test_grok_sandbox_seat_approval.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_jail_qualification_entry.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# GROK: Grok Seat in the Jail

## Context

This plan covers roadmap Phase 7 (GROK) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Its exit criteria are EC-GROK-1 to EC-GROK-5, cited by ID only. The roadmap
is registered non-active (OD-1), so lanes land as governed PRs under principle 2. JAILCORE's
plan and contract are on main (agent-harness#1852).

**Frozen inputs (pinned).**

- `plans/seats-jailcore-route-contract.md` at sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`. It defines
  IF-0-JAILCORE-1 (§1–§4), IF-0-JAILCORE-2 (§7) and IF-0-JAILCORE-3 (§5–§6). This plan cites
  sections and does not restate them. §1's vendor rule lets a vendor phase add one
  `JailProfile`, one allowlist, its own `<leg>_seat_*` codes (each with one additive
  `OD10_CLASSES` entry) and its window rows as data on the profile.
- IF-0-FIRSTSEAT-1 (the readiness row), IF-0-FIRSTSEAT-2 (the row-window kit) and
  IF-0-FIRSTSEAT-3 (the exec record and the Grok parent auth adapter).
- The Grok admission gate on main (FIRSTSEAT L4): `require_grok_admission`, `grok_tool_gate`,
  `probe_grok_tools`, `record_tool_probe`, `grok_runtime_forms`,
  `phase-loop seat-window probe-tools --vendor grok` and the code
  `grok_tool_surface_unverified`. A receipt binds the resolved binary digest and the argv
  digest, and every launch path fails closed. GROK consumes the gate unchanged.
- TEAMHOST publishes no interface (roadmap Phase 4, "Produces: (none)"). GROK consumes only
  its exits EC-TEAMHOST-1 and EC-TEAMHOST-2, and calls no TEAMHOST symbol.

**Base.** After JAILCORE, the core builders and `seat_route.resolve` contain no leg branch.
A Grok seat with a staged tree takes L1's named `unconfined` exception, which the matrix
says expires 2026-12-04 UTC. The brokered argv (`_grok_brokered_form`, `staged`) and the
access-only credential copy (`_SEAT_CREDENTIAL_SHAPE["grok"]`) live in `panel_invoker.py`.

**Execution gate.** Plan now. Execute after JAILCORE and TEAMHOST exit (roadmap DAG).

## Interface Freeze Gates

- [ ] IF-0-GROK-1 — Grok containment surface, provided by SL-1.
  - **Allowlist.** `seat_egress/grok-allowlist.json`, with schema
    `phase_loop_seat_egress_allowlist.v1`, `leg: "grok"` and id `grok`.
    - `allow` holds only requests in the set measured in SL-1.2.
    - `measured_and_refused` holds every other host observed there.
    - `measured` names the CLI version, the date and the method.
    - Every rule traces to a measured request.
    - It is consumed only through `allowlist_ref("grok")` and
      `start_proxy(allowlist_id="grok")` (contract §7).
  - **Credential** (`seat_credentials`):
    - `grok_seat_credential_present() -> bool`. True when the operator's Grok login store
      exists. It reads no secret.
    - `stage_grok_seat_credential(dest: Path, *, margin_s: float) -> GrokSeatCredential`.
      - Writes the access-only copy of the store, plus `agent_id`, as `0600` files in a fresh
        `0700` directory beside seat-home.
      - Opens the store with `O_NOFOLLOW` under the operator's ownership. An unsafe store
        refuses with `seat_profile_unavailable`, as main's brokered route does.
      - Raises `GrokCredentialRefused(code)` with `grok_seat_credential_missing`,
        `grok_seat_credential_refused` (not a subscription login, judged by the store marker
        SL-1.2 measures) or `grok_seat_token_expired` (remaining lifetime below `margin_s`).
    - `GrokSeatCredential(secrets: tuple[bytes, ...], digest: str, expires_at: datetime | None)`.
    - `grok_seat_credential_after(dest: Path, delivered: GrokSeatCredential) -> str | None`.
      Returns `grok_seat_token_refreshed_in_jail` if the delivered bytes changed or any
      credential-shaped file appeared under the seat's `.grok`. Otherwise `None`.
  - **Codes.** Each is a `seat_jail.NOTICES` entry with what, why and fix, classified in
    `OD10_CLASSES` (contract §1 vendor rule). All are terminal (contract §3 default rule). No fix line names
    `XAI_API_KEY`, a key-based credential, or a sealed or inline route.

    | Code | Class | Fix line (gist) |
    |---|---|---|
    | `grok_seat_credential_missing` | ordinary | sign in with `grok login` (`--device-code` on a headless host), then re-run |
    | `grok_seat_credential_refused` | ordinary | sign in with `grok login` to the subscription account; seats use only that login |
    | `grok_seat_token_expired` | ordinary | the operator renews the login with `grok login`; a seat never renews it (agent-harness#1289) |
    | `grok_seat_token_in_output` | security | sign out and in again with `grok logout` and `grok login`; report privately |
    | `grok_seat_token_refreshed_in_jail` | security | report privately; re-run the containment probe |

- [ ] IF-0-GROK-2 — The Grok `JailProfile`, provided by SL-2 and registered through
  `seat_profiles.register` (contract §1):

  | Field | Value |
  |---|---|
  | `leg`, `vendor` | `grok`, `grok`. This matches the unique `kind="vendor"` readiness row (contract §2). |
  | `argv` | Main's `staged` form, with `--cwd /seat/tree` and `--prompt-file /dev/stdin`, plus only the config-closing flags SL-2.1 measures. It keeps `--disable-web-search`, `--no-memory`, `--no-subagents`, the `--tools` allow-list, `--disallowed-tools` and the approving permission mode. If its `_grok_argv_digest` differs from `staged`, SL-2 adds `grok_runtime_forms()["jailed"]`. |
  | `owner_binds` | The staged credential files, read-only at `/seat/home/.grok/`. The egress CA, read-only at `/seat/egress-ca.pem`. |
  | `env` | The per-seat proxy variables and the CA-trust variable(s) the CLI honours (measured in SL-2.1). No provider key variable. |
  | `home_dirs` | `(".grok",)` |
  | `digest_placeholders`, `mount_points` | The credential directory as `<grok-credential>`; the CA as `<egress-ca>`; the two credential file mount points |
  | `new_session`, `token_fd` | `True`, `False` |
  | `projection` | `"optional"` |
  | `credential` | `CredentialDelivery("home_file", <scope evidence id>)` |
  | `credential_present`, `credential_missing_code` | `grok_seat_credential_present`, `grok_seat_credential_missing` |
  | `preconditions` | `(Precondition("tool_surface", …),)`. It runs main's `grok_tool_gate` on the jailed form against the resolved host binary, and yields `grok_tool_surface_unverified`. |
  | `recorded_stop`, `variant` | `None`, `None` |
  | `config_surface` | `ConfigSurface(True, planted_paths)`. `planted_paths` is every tree path the pinned CLI reads as project settings, hooks, MCP servers or provider overrides (measured in SL-2.1). |
  | `window` | `WindowRows` data, with field spellings as JAILCORE publishes them. Route literal `jailed`. Plant locations: `tree` is `/seat/tree`, backed by the per-launch copy; `home` is `/seat/home`, backed by seat-home; `provider_config` is `/seat/home/.grok`, backed by seat-home `.grok`. No separate `workdir` row, because the Grok working directory is the tree, and no two rows may share a host path. The read-only credential binds are never plant targets. Tree rows: `planted_paths`, each with its role and SL-2.1 evidence in the FIRSTSEAT containment contract §2 vocabulary. Record fields: the kit's vendor-neutral fields with `vendor="grok"`. |
  | `auth_probe` | The Grok parent adapter on main (IF-0-FIRSTSEAT-3), unchanged |
  | `output_secret_code` | `grok_seat_token_in_output` |
  | `containment` | `ContainmentEvidence(scope, refresh, unlisted, None)`, naming record ids in `plans/evidence/seat-grok/containment.json` |
  | `allowlist_id`, `notice_codes` | `"grok"`; the five IF-0-GROK-1 codes plus `grok_tool_surface_unverified` |

  The launch site has four invariants:
  - **Tree.** `/seat/tree` is a per-launch copy of the authorized stage. It is checked equal
    to `staged_tree_sha256` before launch (otherwise `seat_sandbox_refused:stage_changed`),
    passed as `build_seat_jail(tree=…)` and writable by the seat. It is removed when the leg
    ends. Neither the authorized stage nor another seat's tree is bound into a Grok jail.
  - **Gate.** Immediately before spawn, main's unchanged `require_grok_admission` checks the
    exact final provider argv and resolved host binary bound at `/seat/bin/grok`; neither may
    change afterward. A non-pass ends the leg with `grok_tool_surface_unverified` before any
    process starts.
  - **Output and refresh.** Seat output is scanned for every `GrokSeatCredential.secrets`
    value in each `contains_secret` encoding. A hit yields `grok_seat_token_in_output`. Then
    `grok_seat_credential_after` runs.
  - **Egress.** One `start_proxy(allowlist_id="grok")` per seat.

## Lane Index & Dependencies

SL-1 — Grok egress, credential and codes (roadmap lane B)
  Depends on: (none)
  Blocks: SL-2, SL-3
  Parallel-safe: yes

SL-2 — Grok profile, tree and launch (roadmap lane A)
  Depends on: SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation reducer (SL-docs)
  Depends on: SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Grok egress, credential and codes (roadmap lane B)

- **Scope**: Measure and add the Grok allowlist, stage and check the Grok credential, and add and classify the Grok codes (IF-0-GROK-1). The profile is not registered here.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_egress/grok-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_grok_seat_containment.py`, `phase-loop-runtime/tests/test_seat_credentials.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `plans/evidence/seat-grok/containment.json`
- **Interfaces provided**: IF-0-GROK-1
- **Interfaces consumed**: from IF-0-JAILCORE-1 and IF-0-JAILCORE-2: `allowlist_ref` (pre-existing), `start_proxy` (pre-existing), `OD10_CLASSES` (pre-existing), `mode_line_codes` (pre-existing). From main: `_access_token_only` (pre-existing), `contains_secret` (pre-existing)
- **Parallel-safe**: yes

Edit scope: in `seat_jail.py`, Grok `NOTICES` entries only. In `seat_route_contract.py`,
additive `OD10_CLASSES` entries for those codes only (contract §1 vendor rule).

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_containment.py` | (a) Allowlist schema, leg and id; `allowlist_ref("grok")` content digest and probe rows. (b) A proxy started for `grok` refuses an unlisted host and a host listed only in `gemini-allowlist.json`, path-entered through the real `proxy.mjs`. (c) The staged copy carries no refresh or id keys, has modes 0600 and 0700, and refuses a link, a foreign owner or an oversize store with `seat_profile_unavailable`. A missing store gives `grok_seat_credential_missing`; a non-subscription store, `grok_seat_credential_refused`; an expiry inside the margin, `grok_seat_token_expired`. (d) The after-check returns the refresh code for a changed delivered file and for a new credential-shaped file, and `None` for an untouched home. (e) Each new code has non-empty what/why/fix and its IF-0-GROK-1 class, and no fix line matches `XAI_API_KEY`, "API key", "sealed" or "inline". | `V1` |
| SL-1.2 | impl | SL-1.1 | `plans/evidence/seat-grok/containment.json` | — | — |
| SL-1.3 | impl | SL-1.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_egress/grok-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_jail.py` | — | — |
| SL-1.4 | verify | SL-1.3 | SL-1 files | all SL-1 tests | `V1`, `V4` |

**SL-1.2 measurement.** This runs on a developer host under the developer's own login
(principle 5; not a window). It uses the CLI version SL-2 pins, a fresh home holding only
the access-only copy, and the TLS-terminating proxy with every request logged. It records
four things:
- the request set;
- the store field that marks a subscription login;
- the credential's actual lifetime;
- its scope, meaning which provider endpoints accept the copy.

Raw logs stay private. `containment.json` holds record ids and digests only.

### SL-2 — Grok profile, tree and launch (roadmap lane A)

- **Scope**: Build the IF-0-GROK-2 profile, with its window rows, and the jailed launch site. Prove the tree, argv, gate, config and output behaviour, then register the profile and update the Grok doc row together when enabling the route.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `docs/review-seats-readiness.md`, `phase-loop-runtime/tests/test_grok_seat_jail.py`, `phase-loop-runtime/tests/test_grok_sandbox_seat_approval.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/evidence/seat-grok/write-confinement.json`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/provider-free.json`
- **Interfaces provided**: IF-0-GROK-2
- **Interfaces consumed**: IF-0-GROK-1 (SL-1). From IF-0-JAILCORE-1 to IF-0-JAILCORE-3: `JailProfile` (pre-existing), `register` (pre-existing), `seat_route.resolve` (pre-existing), `build_seat_jail` (pre-existing), `start_proxy` (pre-existing), `key_for_launch` (pre-existing). From FIRSTSEAT: `grok_tool_gate` (pre-existing), `grok_runtime_forms` (pre-existing), `probe_grok_tools` (pre-existing), `readiness_rows` (pre-existing)
- **Parallel-safe**: no

Edit scope: in `seat_profiles.py`, the Grok entry only, including its `window` data. In the
readiness doc, the Grok row only. In `panel_invoker.py`, the Grok leg and
`grok_runtime_forms`. `seat_window.py` is not edited; the kit reads the profile's `window`.
The three kit and notice test files change only in their Grok expectations.
`test_seats_teamhost_doctor.py` gains one additive agreement row (agent-harness#1882).

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_jail.py`, `plans/evidence/seat-grok/tool-surface.json` | Record the "SL-2.1 measurement", then write the "SL-2.1 cases". | `V2`, `VL` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | — | — |
| SL-2.3 | impl | SL-2.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `docs/review-seats-readiness.md`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py` | — | — |
| SL-2.4 | verify | SL-2.3 | SL-2 files, `plans/evidence/seat-grok/write-confinement.json`, `plans/evidence/seat-grok/provider-free.json` | all SL-2 tests | `V2`, `V3`, `V4`, `VL`, `VD`, `VK` |

**SL-2.1 measurement**, on the pinned CLI version:
- the project-config read set, and the flag or seat-home setting that keeps it from loading;
- the proxy and CA-trust variables the CLI honours;
- whether the bound binary runs without a projected closure;
- the tool-definition probe (`VK`) on the jailed form.

Publish tool-surface metadata only for a passing receipt. Any other result stays private
under FIRSTSEAT's gate rules.

**SL-2.1 cases.** Each case is path-entered through `_seat_route_for_spawn` and the real
Grok launch site, with recording runners unless marked `live_jail` (VL) or `live_provider`
(VD).

- (a) **Registration.** The JAILCORE invariants hold for the Grok profile. The vendor matches
  the readiness row. JAILCORE's no-branch scan still passes.
- (b) **Argv.** The provider argv has `--cwd /seat/tree` and no host path (agent-harness#1460).
  It keeps the retained flags. Its argv digest equals the probed runtime form's digest.
- (c) **Tree.** A copy that differs from `staged_tree_sha256` refuses before launch. In
  `live_jail`, a probe write lands in the copy only, and the authorized stage hash and a
  sibling seat's tree are unchanged (agent-harness#1686).
- (d) **Gate.** The outer argv starts at bwrap. The test asserts unchanged
  `require_grok_admission` receives that exact final provider argv and binary immediately
  before spawn, with no later mutation. Each of these ends with
  `grok_tool_surface_unverified` and spawns nothing:
  - no receipt;
  - a receipt for another binary digest;
  - a receipt for another argv digest;
  - a receipt whose offered tools include one outside `--tools`.

  A passing receipt spawns.
- (e) **Route.** With every step passing, the mode is `jailed`. Missing credential gives L5
  `grok_seat_credential_missing`. Missing receipt gives L6 `grok_tool_surface_unverified`. A
  missing allowlist file gives `seat_egress_allowlist_missing`. Once the profile is
  registered, no Grok seat reaches `MODE_UNCONFINED` (EC-JAILCORE-5).
- (f) **Output and refresh.** A planted delivered credential in each `contains_secret`
  encoding yields `grok_seat_token_in_output`, and the exec record omits the output. A
  mutated delivered file yields `grok_seat_token_refreshed_in_jail`.
- (g) **Config** (`live_jail`). Each `planted_paths` marker, staged through
  `stage_review_tree`, does not load.
- (h) **Egress** (`live_jail`). A tool command in the jail is refused for an unlisted host and
  for Gemini's listed host.
- (i) **Approval** (`live_provider`). A jailed turn that runs a compound shell command in the
  copy completes, and the turn is not cancelled (agent-harness#1091).
- (j) **Window.** The Grok `window` rows reach `seat_window`'s vendor gate and path rows with
  no kit-code edit. The kit's Grok row reads route `jailed` and allowlist `grok`, and the
  readiness doc's Grok row agrees. Gemini's kit records stay byte-identical.
- (k) **Agreement row** (SL-2.3). A Grok case with an unverified tool surface: the doctor
  `refuses` with `grok_tool_surface_unverified`, never `admits`.

**SL-2.3 enables the route.** It consumes IF-0-GROK-1 and runs only after `VK` passes on
the pinned version. It registers the profile with its `window` data, updates the Grok doc
row and records the launch-reference inventory decision.

### SL-3 — Documentation reducer (SL-docs)

- **Scope**: Single writer of shared docs and the plan manifest. Its tasks ride in each producer's landing PR, and a final sweep runs after SL-2.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-GROK-1 (SL-1), IF-0-GROK-2 (SL-2)
- **Parallel-safe**: no (terminal)

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan with `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`. If the helper is absent, record "manual catalog audit". |
| SL-docs.2 | docs | SL-docs.1 | per catalog | Each landing adds an `[Unreleased]` CHANGELOG entry. After SL-2, the card states that the Grok seat runs jailed with tools, provider-only egress and a staged access-only credential, and lists its codes and fix lines. |
| SL-docs.3 | docs | SL-docs.2 | `plans/phase-plan-v1-seats-GROK.md` | Append `### Post-execution amendments` only if a freeze proved wrong, by freeze ID and date. |
| SL-docs.4 | verify | SL-docs.3 | — | `V5` and the hosted docs-freshness audit. |

## Execution Notes

- **S-1 (resolved).** JAILCORE's merged vendor rule (contract §1) lets a vendor phase add its
  own `<leg>_seat_*` codes, each with one additive `OD10_CLASSES` entry, and its window rows
  as profile data. SL-1 and SL-2 use exactly that and nothing more.
- **S-2 (open; affects only the row window).** The kit's named exceptions are a code literal
  in `seat_window.readiness_rows()` that still lists Grok as `unconfined`. Registration ends
  the exception in effect, because L1 finds the profile (EC-JAILCORE-5). Under the data-only
  rule, though, no GROK lane may remove the literal, so the kit row would keep showing an
  exception that expires 2026-12-04. Proposed fix: omit `unconfined` only when a profile is registered, and `open egress` only
  when its profile has an allowlist. CODEX and CLAUDENET need those respective rules. Until S-2 is settled,
  SL-2.3 records the exception's end in the readiness doc only.
- **Other STOP conditions.** In each case, report the exact sentence. The row stays on its
  exception, and then OD-9 applies. Do not register the profile.
  - The pinned CLI cannot run through the TLS-terminating proxy (EC-JAILCORE-3).
  - No flag or seat-home setting keeps planted tree config from loading.
  - The store has no subscription marker, so `grok_seat_credential_refused` cannot be
    decided.
  - `VK` does not pass on the pinned version. The leg then stays degraded per
    EC-FIRSTSEAT-4, with results on its private route.
- **Expiry.** The Grok `unconfined` exception expires 2026-12-04 UTC. If SL-2.3 has not landed
  by then, Grok resolves degraded (EC-JAILCORE-5) unless an owner record in the matrix renews
  the exception.
- **Single writers.**
  - `panel_invoker.py` is also written by TEAMHOST lane A, CODEX, PI, CLAUDENET and v11
    PANELSPLIT. Whichever lands second rebases. If PANELSPLIT has moved the seat-launch
    code, SL-2 edits the successor module and records the move in its PR.
  - CODEX and PI also edit `seat_profiles.py` (profile and window data), `seat_jail.NOTICES`,
    `OD10_CLASSES` and the readiness doc, each for its own entries only. Whichever lands
    second rebases.
- **Row window (EC-GROK-4).** SL-2.4 records the provider-free team-host qualification, and
  the row reads `candidate`. The next row window (LA-2, LA-3) runs the IF-0-FIRSTSEAT-2 kit.
  Its reviewed PR edits only the Grok row and `plans/evidence/seat-qualification/`.
- **Known destructive changes**: none. **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none; no preamble lane is needed, because the two lanes own disjoint
  files.
- **Worktree naming**: allocated by the executor.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see
  sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream
  dependency's merge>, it MUST stop and report rather than committing — the orchestrator will
  re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale
  worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Shared-host limits.** Before each test command, check `uptime` and `/proc/pressure/io`.
  Run targeted files serially, with no `-n`, under `timeout 900`, using system python3.14.4
  for jail tests. The full suite runs only in hosted CI and Gate A.
- **Before marking a PR ready.**
  - Run `V4`.
  - Run a clean-room tree check from the installed wheel. Repo-only tests skip, and the
    allowlist JSON is declared as package data.
  - Union-resolve `CHANGELOG.md`, `plans/manifest.json` and the `tests/data` inventories.
  - Gate A follows current owner policy.
- **OD-10.** A containment or security finding is reported privately under the operator's
  private state. It never appears in a PR, commit, code comment or test name. Test names
  state required behaviour.
- **Skill deviations.** Reconnaissance ran in-thread. `advisor()` and `TaskCreate` were
  unavailable, so the lane DAG is the hand-off surface. One cross-vendor review round ran.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`
- evidence paths: `plans/evidence/seat-grok/write-confinement.json`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/provider-free.json`, `plans/evidence/seat-grok/containment.json`, `plans/evidence/seat-qualification/`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-GROK-1 — proven by `V2` cases (b), (c) and (e), and by `VL` case (c), with the result in `write-confinement.json`. Falsified by a `live_jail` probe write found outside the per-launch copy, or by a host path in the provider argv. Path-entered control: the write is issued by the real CLI's tool inside the jail built by `build_seat_jail`.
- [ ] EC-GROK-2 — proven by `V2` case (d), by `VK` on the pinned version (`tool-surface.json`) and by `VD` case (i). Falsified by a spawn under a receipt that offers a tool outside `--tools`, or by a cancelled jailed turn. Path-entered control: the receipt enters through `record_tool_probe` and the private record store.
- [ ] EC-GROK-3 — proven by `V1` (b) and `VL` (h). Falsified by the `grok` proxy or a jailed tool command reaching an unlisted host or Gemini's listed host. Path-entered control: requests go through the real `proxy.mjs` and the jailed tool command.
- [ ] EC-GROK-4 — proven by `VK` qualify on a team host (`provider-free.json`, row `candidate`), then by the row-window record under `plans/evidence/seat-qualification/` (row `done-local`). Falsified by a `done-local` Grok row with no window record on its current qualification key. Path-entered control: through `seat-window verify` on the retained record.
- [ ] EC-GROK-5 — proven by `V1` (c) and (d), `V2` (e) and (f), and the scope, refresh and lifetime ids in `containment.json`. Falsified by a credential readable outside its declared delivery, an expiry with no typed code, or a refresh that goes undetected. Path-entered control: the store enters through `stage_grok_seat_credential` from a fixture operator home.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, run with
system python3.14.4 and paths under `phase-loop-runtime/tests/`. The new test files are absent
on this plan-only checkout, so these are pending selectors, not receipts.

- `V1`: `P test_grok_seat_containment.py test_seat_credentials.py test_seat_route_contract.py test_seat_notices.py test_seat_jail.py`
- `V2`: `P test_grok_seat_jail.py test_grok_sandbox_seat_approval.py test_seat_profiles.py`, then `P test_seats_teamhost_doctor.py -k seats_teamhost_agreement`
- `V3`: `P test_panel_invoker.py -k grok test_seat_jail_qualification_entry.py test_seat_qualification_host_context.py`
- `V4`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py`
- `V5`: `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_grok_seat_jail.py -k live_jail --junitxml=<private-receipt>`. It runs provider-free on a host class with jail prerequisites; a skip or zero collection fails.
- `VD`: `PHASE_LOOP_GROK_LIVE=1 P test_grok_seat_jail.py -k live_provider`. It runs on a developer host under the developer's own login and is not a window.
- `VK`: `timeout 300 phase-loop seat-window probe-tools --vendor grok`, `timeout 300 phase-loop seat-sandbox qualify` and `timeout 300 phase-loop seat-egress status`.
- Full suite: hosted CI and Gate A only.
