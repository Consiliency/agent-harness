---
phase_loop_plan_version: 1
phase: GROK
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9d1d149a4709dbf7c67dbdbb957228ff8a06d36570e1f9cb77bcc039b96a7ac4
automation:
  suite_command: ["timeout", "600", "env", "PYTHONDONTWRITEBYTECODE=1", "PYTEST_ADDOPTS=", "uv", "run", "--project", "phase-loop-runtime", "--group", "test", "--python", "/usr/bin/python3", "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", "-q", "phase-loop-runtime/tests/test_grok_seat_vocabulary.py", "phase-loop-runtime/tests/test_grok_seat_credential.py", "phase-loop-runtime/tests/test_grok_seat_egress.py", "phase-loop-runtime/tests/test_grok_seat_profile.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_grok_jail_surface.py", "phase-loop-runtime/tests/test_grok_seat_jail.py", "phase-loop-runtime/tests/test_grok_jail_measure.py", "phase-loop-runtime/tests/test_grok_seat_provider_free.py", "phase-loop-runtime/tests/test_grok_jail_catalog.py", "phase-loop-runtime/tests/test_grok_seat_renewal.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# GROK: Grok Seat in the Jail

## Context

Roadmap Phase 7 (GROK) of `specs/phase-plans-seats-v1.md`, tracked by agent-harness#1820.
Exit criteria EC-GROK-1 to EC-GROK-5, cited by ID only. This is the 2026-11-21 amendment
(revision r2) of the plan landed by agent-harness#1857. It closes the currency check's A-1 to
A-9 under the coordinator's four rulings, the plan review's REQUIRED and SHOULD items,
erratum 8 (final at r3) with its four requirements on the jail contract, and the owner's
window-kit decisions (jail contract §15). The roadmap text is unchanged.

**Frozen inputs (pinned).**

- `plans/artifacts/grok-jail-tool-surface-contract-v1.md` at sha256
  `bc8e289c4d94799f6cd5f75de7d3dbd57a97b363d665a476787a41cad46c0ef9` ("the jail contract"). This plan cites its sections.
- `plans/artifacts/grok-tool-surface-contract-v1.md` at sha256
  `5b929cb588e4bb555ce8374311432376fe4c04e8a851fd511e6c44682736b27c` (the **effective
  input**: agent-harness#2033 through erratum 7, erratum 8 r3 as merged with E8-A
  agent-harness#2061, and erratum 9 added by the re-pin gate amendment; Execution Notes,
  "Re-pin gate"). The historical base through erratum 7 was
  `9c56fc68e164d9ae7abbeb4969ee860c6844355c3d80569e4bb4600a3e6355d4`.
- `plans/seats-jailcore-route-contract.md` at sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`: IF-0-JAILCORE-1 to
  IF-0-JAILCORE-3, including §1's vendor rule.
- IF-0-FIRSTSEAT-1 to IF-0-FIRSTSEAT-3, and the FIRSTSEAT Grok gate as agent-harness#2033
  left it (gates take a launch `context=`; receipts carry `list_tools` or
  `frozen_measurement`; the jailed spawn admits `list_tools` only).
- Gating, unmerged, named by role: the K-1 window kit with the owner's 2026-11-21
  decisions (jail contract header).

**Base.** `origin/main` with GROKROLL SL-0 (agent-harness#2050) merged. Registering a Grok
profile drops the `unconfined` exception (`seat_window.readiness_rows`); S-2 is closed in
source. No Grok profile, credential module or `grok_seat_*` code exists.

**Jailed projection (option A, r5).** The coordinator ruled option A on Q-r4: main's
Gemini-style jail projection (jail contract §2.3, §2.4). The jailed seat's config is a
read-only staged file, checked by digest at each launch; the unjailed seat keeps E8-A's sealed
memfd. The unjailed path is owned by E8-A (`panel_invoker.seat_profile`, `grok_tool_surface`);
the jailed path by GROK (`seat_grok_credential`, `seat_profile_grok`, `grok_jail_surface`).
Both take their bytes from `grok_tool_surface.seat_config()`, and SL-3 fails on any difference.
SL-1, SL-2 and SL-3 are dispatchable again.

**Execution gate.** JAILCORE and TEAMHOST code is on main (agent-harness#1890,
agent-harness#1904) and CODEX executed against the same gate (agent-harness#1916); the
coordinator treats it as met.

**Erratum 8 reconciled.** The jailed seat launches the `staged` form, which erratum 8 refuses
before spawn for frozen-basis use in the unjailed context. In `grok_jail_context.v1` it is
eligible only under the five conditions of jail contract §2.4 (every creatable policy and
discovery input immutable, `.grok` a mount, the confirmation recorded, the boundary check
passed, an admitted jailed record); otherwise jailed `staged` stays closed. Unjailed `staged`
stays ineligible. The jailed measurement measures `staged` only.

## Interface Freeze Gates

- [ ] IF-0-GROK-1 — Grok containment surface, provided by SL-0 (codes) and SL-1 (the rest).
  - **Codes.** Five `seat_jail.NOTICES` entries with what, why and fix, each classified in
    `OD10_CLASSES`, all terminal. No fix line names `XAI_API_KEY`, a key credential, or a
    sealed or inline route.

    | Code | Class | Fix line (gist) |
    |---|---|---|
    | `grok_seat_credential_missing` | ordinary | sign in with `grok login` (`--device-code` headless), re-run |
    | `grok_seat_credential_refused` | ordinary | sign in to the subscription account; seats use only that login |
    | `grok_seat_token_expired` | ordinary | the operator renews with `grok login`; a seat never renews (agent-harness#1289) |
    | `grok_seat_token_in_output` | security | sign out and in again; report privately |
    | `grok_seat_token_refreshed_in_jail` | security | report privately; re-run the containment probe |

  - **Credential** (`seat_grok_credential`, a new module):
    - `grok_seat_credential_present() -> bool`, reading no secret.
    - `stage_grok_seat_credential(config_dir, *, margin_s) -> GrokSeatCredential`: opens
      the operator's store `O_NOFOLLOW` under the operator's ownership (unsafe stores refuse
      `seat_profile_unavailable`) and writes, mode 0444, into the staged `<review_dir>/grok-config/`
      directory (jail contract §2.3): the access-only `auth.json`, `agent_id`, and the seat
      config whose sha256 is the pinned input
      `2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780`.
    - Refusals, `GrokCredentialRefused(code)`: `grok_seat_credential_missing`;
      `grok_seat_credential_refused` unless the store shows a positive subscription marker;
      `grok_seat_token_expired` unless the expiry parses and the remaining lifetime exceeds
      `margin_s` (the leg deadline plus 300 s).
    - `GrokSeatCredential(config_dir, scan_values, digest, expires_at)`: `scan_values` are taken from
      the exact projected copy, every secret value (at least 8 characters) and its last 12
      characters, in memory only. `grok_seat_credential_after(seat_home, delivered) -> str |
      None` returns `grok_seat_token_refreshed_in_jail` if a credential-shaped file appeared
      under the seat's `.grok`.
  - **Egress.** The profile adopts `grok-review` (jail contract §9); no allow-list file changes.

- [ ] IF-0-GROK-2 — The Grok `JailProfile`, provided by SL-2: `seat_profile_grok.register_grok()`,
  called from `seat_profiles.py`, also registers the provider executable and the admission
  gate, as `seat_profile_codex` does.

  | Field | Value |
  |---|---|
  | `leg`, `vendor` | `grok`, `grok` |
  | `argv` | main's `staged` form for the production model and effort; argv0 and `--cwd /seat/tree` replaced only |
  | `owner_binds` | exactly the ordered mount list of jail contract §2.3: the staged `.grok` directory read-only through `OwnerPaths.provider_config`; the `.grok/logs` and `.grok/sessions` tmpfs and the two lock-file binds from seat-home; the CA by read-only path bind; the home and tree masks of §2.4. No descriptor; no builder, `seat_uid` or SDK-region edit |
  | `env` | proxy variables and `SSL_CERT_FILE`; no `GROK_*`, `XAI_*` or key variable |
  | `home_dirs` | `(".grok",)` |
  | `projection` | `"none"` |
  | `new_session`, `token_fd` | `True`, `False` |
  | `credential` | `CredentialDelivery("home_file", "grok-credential-scope")` |
  | `credential_present`, `credential_missing_code` | `grok_seat_credential_present`, `grok_seat_credential_missing` |
  | `preconditions` | `(Precondition("tool_surface", …),)`: an unconditional `grok_tool_surface_unverified` while `grok_jail_surface` is absent; SL-3's module supplies the opening check (jail contract §4.1, §4.2) |
  | `config_surface` | `ConfigSurface(True, planted_paths)`, `planted_paths` = the per-image project discovery inventory (jail contract §2.4) |
  | `window` | `WindowRows` data, route `jailed`; plants `tree` = `/seat/tree`, `home` = `/seat/home`, `provider_config` = `/seat/home/.grok`; projections and masks are never plant targets |
  | `auth_probe`, `output_secret_code` | the Grok parent adapter on main; `grok_seat_token_in_output` |
  | `containment` | `ContainmentEvidence("grok-credential-scope", "grok-refresh-detection", "grok-unlisted-refusal", None)` |
  | `allowlist_id`, `notice_codes` | `"grok-review"`; the five codes and `grok_tool_surface_unverified` |

  SL-2 also lands `seat_profile_grok.JAIL_PROTECTION` (jail contract §2.4's table for the
  1.0.92 image, so SL-2 has a complete input), one Grok branch in
  `seat_jail_qualification.py` delegating to `seat_profile_grok.qualification_shape(seat_dir)`
  (which writes a fixture staged `.grok` directory, the mask sources and the mount points), and `phase-loop seat-sandbox
  qualify --leg grok`, whose receipt names the leg and its qualification key.

- [ ] IF-0-GROK-3 — Jailed launch site and gate, provided by SL-3: `grok_jail_surface`
  (`ENFORCEMENT`, `eligibility`, `precondition_code`, `jail_context_digest`,
  `verify_jail_launch_context` with its board and measurement modes, `JailLaunchContext`,
  `staged_admission`, `resolve_subject`, `prepare_measurement`, `JailedMeasurementLaunch`, the
  jailed record, receipt and evidence stores), the jailed Grok leg in `panel_invoker.py` with the
  spawn-boundary checks, the suffix scan before retention and the `window_board` hook calls
  (jail contract §2–§5.1).
- [ ] IF-0-GROK-4 — Jailed measurement, provided by SL-4: per-label jailed grants, the agreement
  rule, the publication gate on `jail_context_digest`, jailed publication and
  `--verify-probe final` in the jailed context (jail contract §5.2–§5.4, §7.1).

## Lane Index & Dependencies

SL-0 — VOCAB: Grok codes (roadmap lane B)
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: yes

SL-1 — CRED: credential staging and egress adoption (roadmap lane B)
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: yes

SL-2 — PROFILE: Grok profile registered with the gate closed (roadmap lane A)
  Depends on: SL-0, SL-1
  Blocks: SL-3, SL-5
  Parallel-safe: no

SL-3 — LAUNCH: jailed launch site, spawn-boundary identity and gate (roadmap lanes A and B)
  Depends on: SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — MEASURE: jailed measurement (roadmap lane B)
  Depends on: SL-3
  Blocks: SL-6
  Parallel-safe: no

SL-5 — CANDIDATE: provider-free qualification evidence (roadmap lane A)
  Depends on: SL-2
  Blocks: SL-7
  Parallel-safe: yes

SL-6 — SURFACE: granted measurement data (roadmap lane B)
  Depends on: SL-4
  Blocks: SL-7
  Parallel-safe: no

SL-8 — RENEW: per-vendor expiry, fallback only
  Depends on: (none)
  Blocks: SL-7
  Parallel-safe: yes

SL-7 — Documentation reducer (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5, SL-6, SL-8
  Blocks: (none)
  Parallel-safe: no

SL-8 is built and reviewed in parallel on the release base and rides Train A only if SL-2
misses the cut (jail contract §11); otherwise SL-7 records it closed.

## Lanes

Every lane: targeted test files, serial, `timeout 600`; no live provider call and no `grok`
execution; every new guard mutation-checked; `uvx ruff@0.15.5 check .` before committing;
CHANGELOG, readiness-doc and launch-inventory entries ride in the lane's PR as SL-7 tasks.
`live_jail` tests use stand-ins only.

### SL-0 — VOCAB: Grok codes (roadmap lane B)

- **Scope**: Add and classify the five IF-0-GROK-1 codes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_grok_seat_vocabulary.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`
- **Interfaces provided**: IF-0-GROK-1 (codes)
- **Interfaces consumed**: `NOTICES`, `OD10_CLASSES`, `mode_line_codes` (pre-existing)
- **Parallel-safe**: yes

Edit scope: Grok `NOTICES` entries and additive `OD10_CLASSES` entries only.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_vocabulary.py` | each code has non-empty what/why/fix and its class; no fix line matches `XAI_API_KEY`, "API key", "sealed" or "inline"; existing codes byte-identical. Falsifier: removing one classification fails it. | `V0` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_notices.py` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 files | `V0`, SDK binding tests unedited | `V0`, `VS` |

Stop: an SDK proof region (not the whole `seat_route_contract.py` file) moves.

### SL-1 — CRED: credential staging and egress adoption (roadmap lane B)

- **Scope**: Build `seat_grok_credential` with staged read-only directory delivery (mode 0444 files in the 0555 `<review_dir>/grok-config/`, jail contract §2.3), scan values and a positive subscription discriminator; prove the `grok-review` adoption offline.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_grok_credential.py`, `phase-loop-runtime/tests/test_grok_seat_credential.py`, `phase-loop-runtime/tests/test_grok_seat_egress.py`, `plans/evidence/seat-grok/containment.json`
- **Interfaces provided**: IF-0-GROK-1 (credential, egress)
- **Interfaces consumed**: IF-0-GROK-1 codes (SL-0); `_access_token_only`, `_seat_secret_values`, `contains_secret`, `allowlist_ref`, `start_proxy` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_credential.py`, `phase-loop-runtime/tests/test_grok_seat_egress.py` | (a) fixtures: subscription, API-key, ambiguous-marker, unparseable-expiry, expired, inside-margin, link, foreign-owner and oversize stores each give their code; nothing is written to disk. (b) the staged `grok-config/` directory is 0555 and its `auth.json`, `agent_id` and config files are 0444 regular files owned by the operator, with no other entries; the config digest equals the pin. (c) `scan_values` hold each secret value and its last 12 characters for a short and a long credential shape, and are not serialisable. (d) the after-check fires on a new credential-shaped file. (e) through the real `proxy.mjs`: an allowed inference request reaches a fixture upstream; unlisted, Gemini, Codex and unlisted-path requests and a direct connection are refused; allow-list digests equal their base values; nothing requires `allowlist_id == leg`. | `V1` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_grok_credential.py`, `plans/evidence/seat-grok/containment.json` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 files | all SL-1 tests | `V1`, `V9` |

`containment.json` holds ids and digests only (`grok-refresh-detection`,
`grok-unlisted-refusal`). Stop: a JAILCORE invariant refuses `allowlist_id="grok-review"`; an
allow-list digest moves; the subscription marker cannot be identified offline from the store
shape (the coordinator decides before SL-2).

### SL-2 — PROFILE: Grok profile registered with the gate closed (roadmap lane A)

- **Scope**: Register IF-0-GROK-2 so the installed runtime drops the `unconfined` exception while every Grok launch stops at L6 whatever receipts exist; add the provider-free Grok qualification entry.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profile_grok.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_grok_seat_profile.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`
- **Interfaces provided**: IF-0-GROK-2
- **Interfaces consumed**: IF-0-GROK-1 (SL-0, SL-1); `JailProfile`, `register`, `seat_route.resolve`, `build_seat_jail`, `register_provider_executable`, `seat_admission.register`, `readiness_rows`, `jail_profile_digest`, `grok_runtime_forms` (pre-existing)
- **Parallel-safe**: no

Edit scope: one import and call in `seat_profiles.py`; one delegating branch and a `--leg`
selector in `seat_jail_qualification.py`; the `seat-sandbox qualify` argument in `cli.py`.
`panel_invoker.py`, `seat_window.py`, `seat_subject.py`, `seat_uid.py` and `seat_jail.py`
unedited.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_profile.py` | (a) JAILCORE invariants; the no-branch scan. (b) BA-J6 through ordinary board routing with absent, unjailed-frozen, legacy and listing receipts. (c) L0 and L5 earlier refusals keep their codes. (d) readiness rows: `vendor:grok` `jailed`, no exception or expiry; `remote:grok` allow-list `grok-review`. (e) a fixture Gemini record observed before 2026-12-04 verifies at clocks before and after it under the snapshot rule. (f) the staged argv digest equals `staged`'s and the cwd is `/seat/tree`. (g) `live_jail` BA-J4 (SL-2 part) with a stand-in under the dropped UID through `build_seat_jail`. Mutation: replacing the fixed refusal with `grok_tool_gate` fails (b). | `V2`, `VL2` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_profile_grok.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py` | — | — |
| SL-2.3 | impl | SL-2.2 | `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py` | golden gains `grok` rows, others byte-identical; `qualify --leg grok` names `grok` and its key, the bare command still qualifies Claude; doctor agreement row `refuses` | `V2`, `V3q` |
| SL-2.4 | verify | SL-2.3 | SL-2 files | all SL-2 tests | `V2`, `V3q`, `VL2`, `V9`, `VS` |

Stop: the jailed argv digest differs from `staged`; the mounts cannot be expressed as
Grok-profile data, or the dropped UID cannot read or write them, without editing a shared
builder or `seat_uid`; a Gemini or Codex qualification shape changes.

### SL-3 — LAUNCH: jailed launch site, spawn-boundary identity and gate (roadmap lanes A and B)

- **Scope**: Build the jailed Grok leg and IF-0-GROK-3; open the gate only under the jail contract §2.4 eligibility conditions and a spawn-boundary mark.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/grok_jail_surface.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py`, `phase-loop-runtime/tests/test_grok_jail_surface.py`, `phase-loop-runtime/tests/test_grok_seat_jail.py`, `plans/evidence/seat-grok/write-confinement.json`
- **Interfaces provided**: IF-0-GROK-3
- **Interfaces consumed**: IF-0-GROK-1, IF-0-GROK-2; `build_seat_jail` (pre-existing), `start_proxy` (pre-existing), `stage_review_tree` (pre-existing), `_resolved_jail_subject` (pre-existing), `_WindowBoardLegRuntime` (pre-existing), `DISCOVERY_PATHS` (pre-existing), `SEAT_FIXED_INPUTS` (pre-existing once erratum 8's E8-A merges), `SEAT_CONFIG_SHA256` (pre-existing once E8-A merges)
- **Parallel-safe**: no

Edit scope: in `panel_invoker.py`, the new jailed Grok leg, its dispatch, the jailed branch of
the spawn check and the jailed measurement admission; in `claude_seat_transport.py`,
`SDK_PROOF_UNBOUND` insertions only. Starts only on a base holding the re-pin gate.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_grok_jail_surface.py`, `phase-loop-runtime/tests/test_grok_seat_jail.py` | Path-entered through `_seat_route_for_spawn` and the real leg: (a) argv `--cwd /seat/tree`, no host path (agent-harness#1460). (b) a copy differing from `staged_tree_sha256` refuses; `live_jail`: a stand-in's write lands only in the copy (agent-harness#1686). (c) BA-J2, BA-J3. (d) output carrying a delivered secret or its 12-character suffix gives `grok_seat_token_in_output` before retention; a new credential-shaped file gives the refresh code. (e) BA-J4 (SL-3 part), BA-J5. (f) `live_jail`: a jailed tool command reaches no unlisted, Gemini or Codex host. (g) BA-J1. (h) the hook calls run in Gemini's order. (i) each eligibility condition of jail contract §2.4, removed alone, keeps `staged` closed. (j) unjailed `context_digest()` unchanged, recorded before and after on the E8-A baseline; `jail_context_digest()` moves with each input. | `V3`, `VL`, `VJ` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/src/phase_loop_runtime/grok_jail_surface.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py` | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 files, `plans/evidence/seat-grok/write-confinement.json` | all SL-3 tests; unjailed suites unedited | `V3`, `VL`, `VJ`, `V9`, `VS`, `VU` |

Stop: an unjailed Grok test needs an edit; an SDK proof region other than
`_run_leg_with_liveness` moves; the masks or the `.grok` mount cannot be built without a
shared-builder edit; the masked-projection confirmation fails (the owner decides, jail
contract §2.4).

### SL-4 — MEASURE: jailed measurement (roadmap lane B)

- **Scope**: Implement IF-0-GROK-4 and the paste-safe jailed procedure.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/grok_tool_surface.py`, `phase-loop-runtime/tests/test_grok_jail_measure.py`, `docs/ops/grok-jail-measurement.md`
- **Interfaces provided**: IF-0-GROK-4
- **Interfaces consumed**: IF-0-GROK-3 (SL-3); the TS contract ledger, rehearsal and aggregation (pre-existing); erratum 8's per-image map, `artifact_refused` and publication gate (pre-existing once E8-B merges)
- **Parallel-safe**: no

Edit scope: `grok_tool_surface.py`'s measurement region only. No CLI flag; `seat_window.py`
is not edited.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | `phase-loop-runtime/tests/test_grok_jail_measure.py` | recording runner: BA-J7; `--new-grant` and `--rehearse` refuse unless eligibility conditions 1–4 pass; per-label reservations with interleaved transport failures, crash and restart, newest result per label, successful launches leaving both retries, a sixth counted request refused; context mismatch between grant and stage refuses; a new unjailed grant refuses once a profile is registered; agreement publishes or `surface_unstable`; `context_mismatch` when the runtime or `jail_context_digest` drifts after the last launch; a suffix in the definitions artifact gives `artifact_refused`; BA-1 and BA-2 for jailed grants; `--verify-probe final` passes only with jailed `staged` admitted and other forms refused; the procedure script runs end to end. | `V4` |
| SL-4.2 | impl | SL-4.1 | `phase-loop-runtime/src/phase_loop_runtime/grok_tool_surface.py`, `docs/ops/grok-jail-measurement.md` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 files | all SL-4 tests; TS contract suites unedited | `V4`, `VU`, `V9` |

Stop: the unjailed measurement's behaviour before registration, or a TS contract test, changes;
the procedure needs a new CLI flag.

### SL-5 — CANDIDATE: provider-free qualification evidence (roadmap lane A)

- **Scope**: After Train A is installed, record `seat-sandbox qualify --leg grok` on the designated seat host (EC-GROK-4 `candidate`).
- **Owned files**: `plans/evidence/seat-grok/provider-free.json`, `phase-loop-runtime/tests/test_grok_seat_provider_free.py`
- **Interfaces provided**: evidence id `grok-provider-free`
- **Interfaces consumed**: IF-0-GROK-2 (SL-2)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_provider_free.py` | the record is metadata only, names leg `grok`, its key and installed release; skips when absent (Gate A clean room) | `V7` |
| SL-5.2 | impl | SL-5.1 | `plans/evidence/seat-grok/provider-free.json` | — | — |
| SL-5.3 | verify | SL-5.2 | SL-5 files | — | `V7`, `VK` |

### SL-6 — SURFACE: granted measurement data (roadmap lane B)

- **Scope**: After the jail contract §7 grant, land the jailed aggregate, the catalog entry and EC-GROK-5's records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/data/grok_jail_tool_surfaces.json`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/tests/test_grok_jail_catalog.py`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/credential-scope.json`
- **Interfaces provided**: evidence id `grok-credential-scope`, the jailed surface
- **Interfaces consumed**: IF-0-GROK-4 (SL-4)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | — | `phase-loop-runtime/tests/test_grok_jail_catalog.py` | catalog parity per context; profile evidence ids resolve; no record carries a path, prompt, id or suffix | `V6` |
| SL-6.2 | impl | SL-6.1 | `phase-loop-runtime/src/phase_loop_runtime/data/grok_jail_tool_surfaces.json`, `phase-loop-runtime/pyproject.toml`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/credential-scope.json` | — | — |
| SL-6.3 | verify | SL-6.2 | SL-6 files | — | `V6`, `VK`, `V9` |

Stop: the aggregate is not `measured` and `admitted` for `staged`.

### SL-8 — RENEW: per-vendor expiry, fallback only

- **Scope**: Replace the shared expiry constant with a per-vendor map, renewing Grok's entry under a signed owner record, on a base without the Grok profile.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/tests/test_grok_seat_renewal.py`
- **Interfaces provided**: (none)
- **Interfaces consumed**: `readiness_rows` (pre-existing); the owner's renewal record
- **Parallel-safe**: yes

Edit scope: `readiness_rows`'s expiry literal and `renewal_record` only; K-1 also edits
`seat_window.py`, and the second lander rebases.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_renewal.py` | on a build without the Grok profile: Grok's expiry is the renewed one, Claude's and Codex's unchanged; the route admits Grok's exception only before it; `renewal_record` names the record; a fixture Gemini record verifies across 2026-12-04 under the snapshot rule | `V8` |
| SL-8.2 | impl | SL-8.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_window.py` | — | — |
| SL-8.3 | verify | SL-8.2 | SL-8 files | — | `V8`, `V9` |

### SL-7 — Documentation reducer (SL-docs)

- **Scope**: Single writer of shared docs, inventories and the manifest; its tasks ride in each producer's PR, then a final sweep.
- **Owned files**: `docs/review-seats-readiness.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-GROK-1, IF-0-GROK-2, IF-0-GROK-3, IF-0-GROK-4, `grok-provider-free`, `grok-credential-scope`
- **Parallel-safe**: no (terminal)

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | rescan, or record "manual catalog audit" |
| SL-docs.2 | docs | SL-docs.1 | per catalog | each PR: a CHANGELOG entry naming its pins and install; SL-2: the Grok readiness rows; SL-3: launch-inventory rows and the jailed probe paragraph; SL-4: the measurement row (`qualification`); after SL-6: the card's Grok entry |
| SL-docs.3 | docs | SL-docs.2 | `plans/phase-plan-v1-seats-GROK.md` | `### Post-execution amendments` only if a freeze proved wrong |
| SL-docs.4 | verify | SL-docs.3 | — | `V5`, the hosted docs-freshness audit, and the jail contract §7.3 row-window evidence present before closeout |

## Execution Notes

- **Rulings and review items.** Jail contract §15 maps A-1..A-9, the four rulings, the review's
  REQUIRED R1–R8 and SHOULDs, erratum 8's r2 and r3 inputs and the owner's window decisions.
- **Gate closed (ruling 2).** Jail contract §4.1 and §6: L6 refuses whatever receipts exist;
  earlier refusals keep their codes; what the matrix and other vendors' records see.
- **Owner grant (ruling 3).** Jail contract §7, with erratum 8's owner terms and briefing facts;
  asked after SL-0..SL-4 and erratum 8's lanes are installed as one release, BA-J1 has passed
  and the masked-projection confirmation is recorded.
- **Re-pin gate.** Writer: the coordinator's planning delegate, as a `claude-plan-phase`
  amendment (not a lane). After erratum 8 merges, the amendment adds erratum 9 (jail contract
  §8) to the TS contract and re-pins it here and in the manifest row; SL-3 and SL-4 are not
  dispatched until their base contains erratum 9 and those matching pins, however many
  planning-only commits deliver them. The roadmap moved on `main` after this base
  (OD-5, agent-harness#2052); `roadmap_sha256` is re-pinned against the merge base when this
  amendment lands. **Applied (2026-11-22):** erratum 8 merged (E8-A agent-harness#2061, E8-B
  agent-harness#2064); erratum 9 is in the TS contract and the frozen inputs and manifest row
  pin it; `roadmap_sha256` was checked against the landing base.
- **Installs and pins.** Jail contract §10: only SL-2 moves the qualification validator; Train
  A, the K-1 snapshot rule, Train B and the catalog install; none between Gemini's first-window
  launch and its export; a Gemini window is refreshed per installed digest it relies on.
- **Critical path and fallback.** Jail contract §11: SL-8 rides Train A in SL-2's place on a
  signed renewal; no second build.
- **Window (EC-GROK-4).** After SL-6 and K-1's Grok adapter (which implements jail contract
  §7.3): the owner's one-attempt grant for the Grok row window, LA-2, LA-3 and the records PR.
- **Coordination.** Erratum 8: SL-3 waits for E8-A, SL-4 for E8-B. K-1 (jail contract §13): GROK
  owns the hook calls in its leg; K-1 owns delivering the runtime and the adapter, which starts
  after SL-3 and SL-6, and only once K-1 has aligned the sections jail contract §13 lists.
- **Assumption A-1.** Another vendor's four-seat row window passes with Grok degraded at L6
  (jail contract §13); confirmation point: a K-1 provider-free end-to-end assertion before the
  first post-Train-A row-window grant. GROKROLL: no pin moves; later GROKROLL lanes re-take their base after a
  GROK lane lands.
- **Single writers.** `panel_invoker.py` (TEAMHOST, CODEX, PI, CLAUDENET, K-1, E8-A),
  `seat_profiles.py` and `seat_window.py` (K-1), `grok_tool_surface.py` (E8-A, E8-B), `cli.py`:
  the second lander rebases; each lane edits its own hunks only.
- **Roadmap.** No text change; lanes map onto roadmap lanes A and B as labelled.
- **Gate A clean room.** A test reading `plans/evidence/` skips when absent or is added to the
  sparse list.
- **Companions left untouched.** `tests/test_panel_invoker.py` (holds a live agy test; Grok
  cases live in `test_grok_seat_jail.py`), `tests/test_grok_tool_surface.py` (erratum 8's; run
  unedited in `VU`) and `uv.lock` (a package-data line does not change it). No release is
  dispatched by this phase.
- **OD-10.** Containment findings go to private state only.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see
  sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream
  dependency's merge>, it MUST stop and report rather than committing — the orchestrator will
  re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale
  worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Known destructive changes**: none. **SL-0 re-exports**: none.
- **Skill deviations.** Reconnaissance ran in-thread (lane limits forbid sub-agents);
  `TaskCreate` unavailable, so the lane DAG is the hand-off surface.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`, `docs/ops/grok-jail-measurement.md`
- evidence paths: `plans/evidence/seat-grok/containment.json`, `plans/evidence/seat-grok/write-confinement.json`, `plans/evidence/seat-grok/provider-free.json`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/credential-scope.json`, `plans/evidence/seat-qualification/`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-GROK-1 — proven by `V3` (a), (b), `VL`, `write-confinement.json`, and the row window's canary write (jail contract §7.3); falsified by a write outside the per-launch copy, a host path in the argv, or a missing or altered canary. Path-entered control: the write is issued inside the jail `build_seat_jail` builds for the real jailed Grok leg.
- [ ] EC-GROK-2 — proven by `V3` (c), (i), `V4`, the jailed aggregate in `tool-surface.json` (`measured`, `admitted`) on the granted image, and the row window's write and run tool steps with an uncancelled terminal turn; falsified by a spawn on a receipt offering a tool outside `--tools`, a non-jailed receipt admitted at the jailed spawn, `staged` opened with an eligibility condition missing, or a cancelled or tool-less turn. Path-entered control: receipts enter through the jailed receipt store and the spawn through `_run_leg_with_liveness`.
- [ ] EC-GROK-3 — proven by `V1` (e), `V3` (f), `VJ`; falsified by the `grok-review` proxy or a jailed tool command reaching an unlisted host or another vendor's listed host. Path-entered control: the real `proxy.mjs` and a command run inside the jail.
- [ ] EC-GROK-4 — proven by `VK` on the designated seat host (`provider-free.json`, row `candidate`), then by the row-window record under `plans/evidence/seat-qualification/` (`done-local`); falsified by a `done-local` Grok row with no window record on its current qualification key. Path-entered control: `seat-window verify` on the retained record.
- [ ] EC-GROK-5 — proven by `V1` (a)–(d), `V3` (d), `VL2`, and the ids in `containment.json` and `credential-scope.json`; falsified by a credential readable outside its declared delivery, an expiry with no typed code, an undetected refresh, or the token or its suffix in a retained path. Path-entered control: the store enters through `stage_grok_seat_credential` from a fixture operator home.

## Verification

`P` is `timeout 600 env PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= uv run --project phase-loop-runtime
--group test --python /usr/bin/python3 -m pytest -p no:cacheprovider -p no:xdist -q`, paths under
`phase-loop-runtime/tests/`, one run at a time after the headroom check. New files are absent
on this plan-only checkout, so these are pending selectors. `VL`, `VL2` and `VJ` are required
gates beside `suite_command`.

- `V0`: `P test_grok_seat_vocabulary.py test_seat_notices.py`
- `V1`: `P test_grok_seat_credential.py test_grok_seat_egress.py`
- `V2`: `P test_grok_seat_profile.py test_seat_profiles.py`, then `P test_seats_teamhost_doctor.py -k seats_teamhost_agreement`
- `V3q`: `P test_seat_jail_qualification_entry.py test_seat_qualification_host_context.py`
- `V3`: `P test_grok_jail_surface.py test_grok_seat_jail.py`
- `V4`: `P test_grok_jail_measure.py`
- `V5`: `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `V6`: `P test_grok_jail_catalog.py`
- `V7`: `P test_grok_seat_provider_free.py`
- `V8`: `P test_grok_seat_renewal.py`
- `V9`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py`
- `VS`: `P test_seats_claude_order.py test_gemini_seat_mode_pin.py`, unedited
- `VU`: `P test_grok_tool_surface.py test_grok_tool_surface_measure.py test_grok_board_leg_frozen_basis.py test_grok_measure_egress.py`, unedited
- `VL2`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_grok_seat_profile.py -k live_jail --junitxml=<private-receipt>`, stand-in only; a skip or zero collection fails
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_grok_seat_jail.py -k live_jail --junitxml=<private-receipt>`, stand-in only; a skip or zero collection fails
- `VJ`: `PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1 P test_grok_seat_jail.py -k jail_ns`, mandatory hosted check (BA-J1, BA-J5)
- `VK`: on the designated seat host's installed runtime: `timeout 300 phase-loop seat-sandbox qualify --leg grok`, `timeout 300 phase-loop seat-egress status`; after SL-6, `measure-tools --verify-probe final` (jail contract §7.1)
- Full suite: hosted CI and Gate A only.
