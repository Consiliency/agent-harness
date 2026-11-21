---
phase_loop_plan_version: 1
phase: GROK
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: b91c98ad7b9097ba411ca21f39cf390878dabac449e59d6fdfd1750915c16a09
automation:
  suite_command: ["timeout", "600", "env", "PYTHONDONTWRITEBYTECODE=1", "PYTEST_ADDOPTS=", "uv", "run", "--group", "test", "--python", "/usr/bin/python3", "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xdist", "-q", "phase-loop-runtime/tests/test_grok_seat_vocabulary.py", "phase-loop-runtime/tests/test_grok_seat_credential.py", "phase-loop-runtime/tests/test_grok_seat_egress.py", "phase-loop-runtime/tests/test_grok_seat_profile.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_grok_jail_surface.py", "phase-loop-runtime/tests/test_grok_seat_jail.py", "phase-loop-runtime/tests/test_grok_jail_measure.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# GROK: Grok Seat in the Jail

## Context

Roadmap Phase 7 (GROK) of `specs/phase-plans-seats-v1.md`, tracked by agent-harness#1820.
Exit criteria EC-GROK-1 to EC-GROK-5, cited by ID only. This is the 2026-11-21 amendment of
the plan landed by agent-harness#1857. It closes the currency check's A-1 to A-9 (mapped in
Execution Notes) under the coordinator's four rulings. The roadmap text is unchanged, so
`roadmap_sha256` is unchanged.

**Frozen inputs (pinned).**

- `plans/artifacts/grok-jail-tool-surface-contract-v1.md` at sha256
  `3286f58cb255383df902c89003048ce955da9ab267f4283a7e3bb0ac7d652316` ("the jail contract"):
  the jailed launch context, records, gate, measurement, closed-gate registration, owner
  grant, allow-list ruling, pins and critical path. This plan cites its sections.
- `plans/artifacts/grok-tool-surface-contract-v1.md` at sha256
  `9c56fc68e164d9ae7abbeb4969ee860c6844355c3d80569e4bb4600a3e6355d4` (agent-harness#2033,
  through erratum 7; "the TS contract"). The jail contract §8 lists every section it amends.
- `plans/seats-jailcore-route-contract.md` at sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`: IF-0-JAILCORE-1 to
  IF-0-JAILCORE-3. §1's vendor rule lets a vendor phase add one `JailProfile`, its own
  `<leg>_seat_*` codes with additive `OD10_CLASSES` entries and window rows as data.
- IF-0-FIRSTSEAT-1 to IF-0-FIRSTSEAT-3, and the FIRSTSEAT Grok gate **as agent-harness#2033
  left it**: `require_grok_admission`, `grok_tool_gate` and `probe_grok_tools` take a
  launch `context=`; receipts carry a basis (`list_tools` or `frozen_measurement`); the
  jailed spawn admits `list_tools` only (jail contract §1).
- Gating, unmerged, named by role (no digest): TS contract **erratum 8** as merged (seat
  `config.toml`, mounted immutably; per-image tolerated refusals; client log exclusion), and
  the **K-1** window kit (`plans/amendments/seats-FIRSTSEAT-K1-window-kit.md`).

**Base.** `origin/main` as the 2026-11-21 currency check read it. Registering a Grok profile drops the `unconfined`
exception (`seat_window.readiness_rows`) and stops L1's exception path; S-2 is closed in
source. No Grok code, profile, credential module or `grok_seat_*` code exists yet.

**Execution gate.** JAILCORE and TEAMHOST code is on main (agent-harness#1890,
agent-harness#1904) and CODEX executed against the same gate (agent-harness#1916); the
coordinator treats the gate as met.

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

  - **Credential and seat config** (`seat_grok_credential`, a new module, as Codex's):
    - `grok_seat_credential_present() -> bool`, reading no secret.
    - `stage_grok_seat_credential(dest, *, margin_s) -> GrokSeatCredential`: in a fresh 0700
      directory beside seat-home, writes 0400 the access-only `.grok/auth.json` (main's
      `_access_token_only` shape), `agent_id`, and `config.toml` with the erratum 8 seat
      config bytes, whose sha256 is the pinned input
      `2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780`. Opens the store
      `O_NOFOLLOW` under the operator's ownership; unsafe stores refuse
      `seat_profile_unavailable`. Raises `GrokCredentialRefused(code)` with
      `grok_seat_credential_missing`, `grok_seat_credential_refused` (no subscription
      login shape) or `grok_seat_token_expired` (remaining lifetime below `margin_s`).
    - `GrokSeatCredential(secrets, digest, expires_at)`; `grok_seat_credential_after(dest,
      delivered) -> str | None` returns `grok_seat_token_refreshed_in_jail` when delivered
      bytes changed or a credential-shaped file appeared under the seat's `.grok`.
    - `margin_s` is the leg deadline plus 300 s.
  - **Egress.** The profile adopts the existing `grok-review` allow-list (jail contract §9).
    No allow-list file is added or edited.

- [ ] IF-0-GROK-2 — The Grok `JailProfile`, provided by SL-2: `seat_profile_grok.register_grok()`,
  called from `seat_profiles.py`, also calls `seat_subject.register_provider_executable("grok",
  "grok")` and `seat_admission.register("grok", …)`, as `seat_profile_codex` does.

  | Field | Value |
  |---|---|
  | `leg`, `vendor` | `grok`, `grok` |
  | `argv` | main's `staged` form with `--cwd /seat/tree`, prompt on stdin; same `_grok_argv_digest` as `staged` (no new route form) |
  | `owner_binds` | read-only: the three staged files at `/seat/home/.grok/auth.json`, `agent_id`, `config.toml`; the egress CA at `/seat/egress-ca.pem`. Tmpfs: `/seat/home/.grok/logs`, `/seat/home/.grok/sessions` (jail contract §2.3) |
  | `env` | proxy variables and `SSL_CERT_FILE`; no `GROK_*`, `XAI_*` or key variable |
  | `home_dirs` | `(".grok",)` |
  | `digest_placeholders`, `mount_points` | `<grok-credential>`, `<egress-ca>`; the staged-file and tmpfs mount points |
  | `new_session`, `token_fd`, `projection` | `True`, `False`, `"optional"` |
  | `credential` | `CredentialDelivery("home_file", "grok-credential-scope")` |
  | `credential_present`, `credential_missing_code` | `grok_seat_credential_present`, `grok_seat_credential_missing` |
  | `preconditions` | `(Precondition("tool_surface", …),)`: main's `grok_tool_gate` on the `staged` form, yielding `grok_tool_surface_unverified`; SL-3 makes that gate accept only jailed-context frozen receipts once a profile is registered (jail contract §4.2) |
  | `config_surface` | `ConfigSurface(True, planted_paths)`, `planted_paths` = the pinned discovery set plus every project-config path the 1.0.92 bundled documentation names |
  | `window` | `WindowRows` data, route `jailed`; plants `tree` = `/seat/tree`, `home` = `/seat/home`, `provider_config` = `/seat/home/.grok`; credential binds are never plant targets |
  | `auth_probe` | the Grok parent adapter on main (IF-0-FIRSTSEAT-3) |
  | `output_secret_code` | `grok_seat_token_in_output` |
  | `containment` | `ContainmentEvidence("grok-credential-scope", "grok-refresh-detection", "grok-unlisted-refusal", None)` |
  | `allowlist_id`, `notice_codes` | `"grok-review"`; the five IF-0-GROK-1 codes and `grok_tool_surface_unverified` |

  It also adds one Grok branch to `seat_jail_qualification.py` that delegates to
  `seat_profile_grok.qualification_shape(seat_dir)` (CA and proxy placeholders, as Codex's).

- [ ] IF-0-GROK-3 — Jailed launch site and context, provided by SL-3: `grok_jail_surface`
  (`GROK_JAIL_CONTEXT`, `jail_context_digest()`, `verify_jail_launch_context`,
  `JailLaunchContext`, jailed record loaders), the context-aware `grok_tool_gate` and
  `probe_grok_tools`, the jailed Grok leg in `panel_invoker.py` and its jailed measurement
  entry (jail contract §2–§4, §5.1).
- [ ] IF-0-GROK-4 — Jailed measurement, provided by SL-4: `measure-tools --vendor grok` in
  the jailed context once a profile is registered, the three launches, the agreement rule and
  jailed publication (jail contract §5, §7.1).

## Lane Index & Dependencies

SL-0 — VOCAB: Grok codes (roadmap lane B)
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: yes

SL-1 — CRED: credential and seat-config staging, egress adoption (roadmap lane B)
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: yes

SL-2 — PROFILE: Grok profile registered with the gate closed (roadmap lane A)
  Depends on: SL-0, SL-1
  Blocks: SL-3, SL-5, SL-8
  Parallel-safe: no

SL-3 — LAUNCH: jailed launch site, jailed context and gate (roadmap lanes A and B)
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
  Depends on: SL-2
  Blocks: SL-7
  Parallel-safe: no

SL-7 — Documentation reducer (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5, SL-6, SL-8
  Blocks: (none)
  Parallel-safe: no

SL-8 runs only on the jail contract §11 trigger; otherwise SL-7 records it closed as not
needed.

## Lanes

Every lane: targeted test files, serial, `timeout 600`; no live provider call and no `grok`
execution; every new guard mutation-checked; `uvx ruff@0.15.5 check .` before committing;
CHANGELOG, readiness-doc and launch-inventory entries ride in the lane's PR as SL-7 tasks.

### SL-0 — VOCAB: Grok codes (roadmap lane B)

- **Scope**: Add and classify the five IF-0-GROK-1 codes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_grok_seat_vocabulary.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`
- **Interfaces provided**: IF-0-GROK-1 (codes)
- **Interfaces consumed**: `NOTICES`, `OD10_CLASSES`, `mode_line_codes` (pre-existing)
- **Parallel-safe**: yes

Edit scope: Grok `NOTICES` entries and additive `OD10_CLASSES` entries only.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_vocabulary.py` | each code has non-empty what/why/fix and its class; no fix line matches `XAI_API_KEY`, "API key", "sealed" or "inline"; existing codes and classes byte-identical. Falsifier: removing one classification fails it. | `V0` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_notices.py` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 files | `V0`, the SDK binding tests unedited | `V0`, `VS` |

Stop: an SDK proof region (not the whole `seat_route_contract.py` file) moves.

### SL-1 — CRED: credential and seat-config staging, egress adoption (roadmap lane B)

- **Scope**: Build `seat_grok_credential`, prove the `grok-review` adoption offline, record offline containment evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_grok_credential.py`, `phase-loop-runtime/tests/test_grok_seat_credential.py`, `phase-loop-runtime/tests/test_grok_seat_egress.py`, `plans/evidence/seat-grok/containment.json`
- **Interfaces provided**: IF-0-GROK-1 (credential, seat config, egress)
- **Interfaces consumed**: IF-0-GROK-1 codes (SL-0); `_access_token_only`, `contains_secret`, `allowlist_ref`, `start_proxy` (pre-existing)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_credential.py`, `phase-loop-runtime/tests/test_grok_seat_egress.py` | (a) staged files carry no refresh or id keys, modes 0400/0700; a link, foreign owner or oversize store refuses `seat_profile_unavailable`; missing, non-subscription and inside-margin stores give their codes. (b) `config.toml` bytes hash to the pinned digest. (c) the after-check fires on a changed file and on a new credential-shaped file, `None` otherwise. (d) a proxy for `grok-review` refuses an unlisted host and hosts listed only for `gemini` or `codex`, through the real `proxy.mjs`; `grok-review`, `gemini` and `codex` digests equal their base values; nothing requires `allowlist_id == leg`. | `V1` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_grok_credential.py`, `plans/evidence/seat-grok/containment.json` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 files | all SL-1 tests | `V1`, `V9` |

`containment.json` holds ids and digests only: `grok-refresh-detection` and
`grok-unlisted-refusal` from these offline tests. Stop: a JAILCORE invariant refuses
`allowlist_id="grok-review"`; any allow-list digest moves.

### SL-2 — PROFILE: Grok profile registered with the gate closed (roadmap lane A)

- **Scope**: Register IF-0-GROK-2 with its window rows, subject, admission gate and qualification branch, so the installed runtime drops the `unconfined` exception while every launch stops at L6.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profile_grok.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py`, `phase-loop-runtime/tests/test_grok_seat_profile.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`
- **Interfaces provided**: IF-0-GROK-2
- **Interfaces consumed**: IF-0-GROK-1 (SL-0, SL-1); `JailProfile`, `register`, `seat_route.resolve`, `register_provider_executable`, `seat_admission.register`, `readiness_rows`, `jail_profile_digest`, `grok_runtime_forms`, `grok_tool_gate` (pre-existing)
- **Parallel-safe**: no

Edit scope: one import and call in `seat_profiles.py`; one delegating branch in
`seat_jail_qualification.py`; `panel_invoker.py`, `seat_window.py`, `seat_subject.py` and
`seat_jail.py` unedited.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_profile.py` | (a) JAILCORE invariants hold; vendor matches the unique row; the no-branch scan passes. (b) BA-J6: registered with no receipt, the route stops at L6 `grok_tool_surface_unverified` (L5 code without a credential), starts no proxy, never reaches L8, spawns nothing; a planted unjailed frozen receipt spawns nothing; no Grok route reaches `MODE_UNCONFINED`. (c) the readiness row reads `jailed`, no exception, no expiry, `grok-review`, `candidate`. (d) `register_window_data` is not called for Grok (K-1's adapter owns it). (e) the staged argv digest equals `staged`'s. Falsifier: deleting the precondition makes (b) fail. | `V2` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_profile_grok.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py` | — | — |
| SL-2.3 | impl | SL-2.2 | `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py` | golden gains `grok` rows, other rows byte-identical; doctor agreement row `refuses` with `grok_tool_surface_unverified`; Grok qualification shape | `V2`, `V3q` |
| SL-2.4 | verify | SL-2.3 | SL-2 files | all SL-2 tests | `V2`, `V3q`, `V9`, `VS` |

Stop: the jailed argv digest differs from `staged`; a shared builder edit would move another
leg's `jail_profile_digest`; the profile cannot express the tmpfs mounts as its own owner
arguments; a Gemini or Codex qualification shape changes.

### SL-3 — LAUNCH: jailed launch site, jailed context and gate (roadmap lanes A and B)

- **Scope**: Build the jailed Grok leg and IF-0-GROK-3; open the jailed spawn only on a jailed-context record plus a matching mark.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/grok_jail_surface.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py`, `phase-loop-runtime/tests/test_grok_jail_surface.py`, `phase-loop-runtime/tests/test_grok_seat_jail.py`, `plans/evidence/seat-grok/write-confinement.json`
- **Interfaces provided**: IF-0-GROK-3
- **Interfaces consumed**: IF-0-GROK-1, IF-0-GROK-2; `build_seat_jail` (pre-existing), `start_proxy` (pre-existing), `stage_review_tree` (pre-existing), `_grok_gate_with_basis` (pre-existing), `DISCOVERY_PATHS` (pre-existing), `SEAT_CONFIG_SHA256` (pre-existing once erratum 8's E8-A merges), `window_board_for` (pre-existing once the K-1 kit lane merges; used only if on the base)
- **Parallel-safe**: no

Edit scope: in `panel_invoker.py`, the new jailed Grok leg, its dispatch, the jailed branch of
the spawn check, the context rule in `grok_tool_gate` and `probe_grok_tools`, and the jailed
measurement admission in `require_grok_admission`; in `claude_seat_transport.py`, `SDK_PROOF_UNBOUND` insertions only.
The unjailed board leg and `grok_seat_context.v1` stay byte-identical.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_grok_jail_surface.py`, `phase-loop-runtime/tests/test_grok_seat_jail.py` | Path-entered through `_seat_route_for_spawn` and the real leg, recording runners unless `live_jail`: (a) argv has `--cwd /seat/tree`, no host path (agent-harness#1460). (b) a tree copy differing from `staged_tree_sha256` refuses before launch; `live_jail`: a stand-in's write lands only in the copy, stage and sibling trees unchanged (agent-harness#1686). (c) spawn refuses with no receipt, another binary or argv digest, an out-of-list tool, a seat-context receipt, a jailed record without a mark, and a mark for another jail, proxy, argv or cwd (BA-J2, BA-J3); a valid jailed record plus mark spawns the stand-in. (d) output carrying a delivered secret in each `contains_secret` encoding gives `grok_seat_token_in_output` and the exec record omits it; a mutated delivered file gives the refresh code. (e) BA-J4 and BA-J5. (f) `live_jail` (h): a jailed tool command reaches neither an unlisted host nor Gemini's or Codex's listed host. (g) BA-J1. (h) `context_digest()` unchanged; `jail_context_digest()` moves with each of its inputs. | `V3`, `VL` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/src/phase_loop_runtime/grok_jail_surface.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py` | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 files, `plans/evidence/seat-grok/write-confinement.json` | all SL-3 tests; unjailed suites unedited | `V3`, `VL`, `V9`, `VS`, `VU` |

The K-1 hook: if the K-1 kit lane is on SL-3's base, the leg calls `window_board_for("grok",
…)` in `_exec_jailed_gemini_leg`'s order with a test; otherwise K-1's Grok adapter lane adds
that call as its named part. Stop: an unjailed Grok test needs an edit; an SDK proof region
other than `_run_leg_with_liveness` moves; erratum 8's immutable projection is unavailable.

### SL-4 — MEASURE: jailed measurement (roadmap lane B)

- **Scope**: Implement IF-0-GROK-4 and the paste-safe jailed procedure.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/grok_tool_surface.py`, `phase-loop-runtime/tests/test_grok_jail_measure.py`, `docs/ops/grok-jail-measurement.md`
- **Interfaces provided**: IF-0-GROK-4
- **Interfaces consumed**: IF-0-GROK-3 (SL-3); the TS contract ledger, rehearsal and aggregation (pre-existing); erratum 8's per-image map (pre-existing once E8-B merges)
- **Parallel-safe**: no

Edit scope: `grok_tool_surface.py`'s measurement region only (grant `context`, jailed
stages, agreement rule, jailed publication names). No CLI flag is added, so `seat_window.py`
is not edited.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | `phase-loop-runtime/tests/test_grok_jail_measure.py` | recording runner: a jailed grant refuses a seat-context stage and vice versa; the unjailed measurement refuses once a profile is registered; a passing jailed rehearsal; the pilot refused without it; three agreeing launches publish to the jailed record; a disagreeing or missing launch publishes nothing (`surface_unstable`); BA-1 and BA-2 hold for jailed grants; the procedure script runs end to end against the recording runner. | `V4` |
| SL-4.2 | impl | SL-4.1 | `phase-loop-runtime/src/phase_loop_runtime/grok_tool_surface.py`, `docs/ops/grok-jail-measurement.md` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 files | all SL-4 tests; TS contract measurement suites unedited | `V4`, `VU`, `V9` |

Stop: the unjailed measurement's behaviour before registration, or a TS contract test,
changes; the procedure needs a new CLI flag (that is a `seat_window.py` edit and an
amendment).

### SL-5 — CANDIDATE: provider-free qualification evidence (roadmap lane A)

- **Scope**: After Train A is installed (jail contract §10.1), record the provider-free Grok qualification on the designated seat host (EC-GROK-4 `candidate`).
- **Owned files**: `plans/evidence/seat-grok/provider-free.json`, `phase-loop-runtime/tests/test_grok_seat_provider_free.py`
- **Interfaces provided**: evidence id `grok-provider-free`
- **Interfaces consumed**: IF-0-GROK-2 (SL-2)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_provider_free.py` | the record is metadata only and its profile digest equals `jail_profile_digest("grok")`; skips when the file is absent (Gate A clean room) | `V7` |
| SL-5.2 | impl | SL-5.1 | `plans/evidence/seat-grok/provider-free.json` | — | — |
| SL-5.3 | verify | SL-5.2 | SL-5 files | — | `V7`, `VK` |

### SL-6 — SURFACE: granted measurement data (roadmap lane B)

- **Scope**: After the jail contract §7 grant runs, land the jailed aggregate, the catalog entry and EC-GROK-5's records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/data/grok_jail_tool_surfaces.json`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/tests/test_grok_jail_catalog.py`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/credential-scope.json`
- **Interfaces provided**: evidence ids `grok-credential-scope`, the jailed surface
- **Interfaces consumed**: IF-0-GROK-4 (SL-4)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | — | `phase-loop-runtime/tests/test_grok_jail_catalog.py` | catalog parity per context; every profile evidence id resolves; no record carries a path, prompt, id or suffix | `V6` |
| SL-6.2 | impl | SL-6.1 | `phase-loop-runtime/src/phase_loop_runtime/data/grok_jail_tool_surfaces.json`, `phase-loop-runtime/pyproject.toml`, `plans/evidence/seat-grok/tool-surface.json`, `plans/evidence/seat-grok/credential-scope.json` | — | — |
| SL-6.3 | verify | SL-6.2 | SL-6 files | — | `V6`, `VK`, `V9` |

Stop: the aggregate is not `measured` and `admitted` for `staged` (EC-GROK-2 then stays open,
the leg degraded); the store has no subscription marker.

### SL-8 — RENEW: per-vendor expiry, fallback only

- **Scope**: On the jail contract §11 trigger, replace the shared expiry constant with a per-vendor map, renewing Grok's entry under the owner's record.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/tests/test_grok_seat_renewal.py`
- **Interfaces provided**: (none)
- **Interfaces consumed**: `readiness_rows` (pre-existing); the owner's renewal record
- **Parallel-safe**: no

Edit scope: `readiness_rows`'s exception expiry literal and `renewal_record` only.
`seat_window.py` is also GROKROLL SL-0's (agent-harness#2050) and K-1's; the second lander
rebases.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | — | `phase-loop-runtime/tests/test_grok_seat_renewal.py` | Grok's expiry is the renewed one, Claude's and Codex's unchanged; the route admits Grok's exception only before it; `renewal_record` names the record | `V8` |
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
| SL-docs.2 | docs | SL-docs.1 | per catalog | each PR: a CHANGELOG entry naming the pins it moves; SL-2: the Grok readiness row (`jailed`, no exception); SL-3: launch-inventory rows and the jailed probe paragraph; SL-4: the measurement row (`qualification`); after SL-6: the card's Grok entry and codes |
| SL-docs.3 | docs | SL-docs.2 | `plans/phase-plan-v1-seats-GROK.md` | `### Post-execution amendments` only if a freeze proved wrong |
| SL-docs.4 | verify | SL-docs.3 | — | `V5` and the hosted docs-freshness audit |

## Execution Notes

- **A-1 to A-9.** A-1: jail contract §2–§5 (ruling 1), lanes SL-3, SL-4, SL-6. A-2: §9,
  adopt `grok-review` (ruling 4), SL-1. A-3: subject, admission, qualification branch in
  SL-2; `WindowVendorData` by K-1's Grok adapter. A-4: S-2 closed in source; no doc-only
  fallback. A-5: IF-0-GROK-2 `owner_binds`, jail contract §2.3, BA-J4. A-6: codes in SL-0.
  A-7: Frozen inputs above. A-8: below. A-9: jail contract §7 (the image rule).
- **Gate closed (ruling 2).** Jail contract §6 states what registration does to the route,
  the matrix and other vendors' records; it is necessary but not sufficient to protect
  Gemini's records after 2026-12-04 (Claude's exception).
- **Owner grant (ruling 3).** Jail contract §7; asked only after SL-0 to SL-4 and erratum 8's
  lanes are merged, released and installed, and BA-J1 passed.
- **Pins and batching.** Jail contract §10: only SL-2 moves the qualification validator;
  Train A (SL-0..SL-2) and Train B (SL-3, SL-4); never installed between Gemini W1's first
  launch and its export.
- **Critical path and fallback.** Jail contract §11. SL-2 merges by 2026-11-30 12:00Z; Train
  A installed on every seat host by 2026-12-02 12:00Z; SL-8 pre-staged by 2026-12-01.
- **Window (EC-GROK-4).** After SL-6 and K-1's Grok adapter: the owner's grant for the Grok
  row window, the release, LA-2, LA-3 and the records PR. The window's measured launch and
  board leg also prove EC-GROK-1's real-CLI write and EC-GROK-2's uncancelled tool turn
  (agent-harness#1091); no separate live test runs.
- **Coordination.** Erratum 8: SL-3 waits for E8-A, SL-4 for E8-B; SL-0..SL-2 touch none of
  its files. K-1: confirmed (jail contract §13); K-1's SL-8 gate should read IF-0-GROK-1 to
  IF-0-GROK-3 plus a measured jailed surface, and K-1's two edits to this plan are subsumed.
  GROKROLL: no GROK lane moves a GROKROLL pin; only SL-6 (`pyproject.toml`) and SL-8
  (`seat_window.py`) touch GROKROLL SL-0's files (agent-harness#2050), each rebasing after it;
  a GROK lane landing during a GROKROLL lane forces that lane to re-take its phase base.
- **Single writers.** `panel_invoker.py` (TEAMHOST, CODEX, PI, CLAUDENET, erratum 8 E8-A):
  second lander rebases. `seat_profiles.py`, `NOTICES`, `OD10_CLASSES`: own entries only.
  `grok_tool_surface.py`: E8-A and E8-B own other regions.
- **Roadmap.** No text change; lanes map onto roadmap lanes A and B as labelled, and lane B's
  probe work (SL-3, SL-4) opens the route only after lane A registers it.
- **Gate A clean room.** A new test reading `plans/evidence/` skips when absent or is added
  to the sparse list.
- **OD-10.** Containment findings go to private state, never to a PR, commit, comment or test
  name.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see
  sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream
  dependency's merge>, it MUST stop and report rather than committing — the orchestrator will
  re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale
  worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Known destructive changes**: none. **SL-0 re-exports**: none.
- **Companions left untouched.** `tests/test_panel_invoker.py` (Grok cases live in `test_grok_seat_jail.py`; the file also holds a live agy test), `tests/test_grok_tool_surface.py` (erratum 8's; run unedited in `VU`) and `uv.lock` (a package-data line does not change the lock). No release is dispatched by this phase, so no release evidence reducer is needed.
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

- [ ] EC-GROK-1 — proven by `V3` (a), (b) and `VL` (b), recorded in `write-confinement.json`, then by the row window's measured launch; falsified by a write found outside the per-launch copy or a host path in the provider argv. Path-entered control: the write is issued inside the jail `build_seat_jail` builds for the real jailed Grok leg.
- [ ] EC-GROK-2 — proven by `V3` (c), `V4`, the jailed aggregate in `tool-surface.json` (`measured`, `admitted`) on the granted image, and the window board leg's uncancelled tool turn; falsified by a spawn on a receipt offering a tool outside `--tools`, a cross-context receipt admitted, or a cancelled jailed turn. Path-entered control: receipts enter through `record_tool_probe` and the private record store, and the spawn through `_run_leg_with_liveness`.
- [ ] EC-GROK-3 — proven by `V1` (d), `V3` (f) and (g); falsified by the `grok-review` proxy or a jailed tool command reaching an unlisted host or another vendor's listed host. Path-entered control: the real `proxy.mjs` and a command run inside the jail.
- [ ] EC-GROK-4 — proven by `VK` on the designated seat host (`provider-free.json`, row `candidate`), then by the row-window record under `plans/evidence/seat-qualification/` (`done-local`); falsified by a `done-local` Grok row with no window record on its current qualification key. Path-entered control: `seat-window verify` on the retained record.
- [ ] EC-GROK-5 — proven by `V1` (a), (c), `V3` (d), (e) and the ids in `containment.json` and `credential-scope.json`; falsified by a credential readable outside its declared delivery, an expiry with no typed code, an undetected refresh, or the token suffix in a retained path. Path-entered control: the store enters through `stage_grok_seat_credential` from a fixture operator home.

## Verification

`P` is `timeout 600 env PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS= uv run --group test
--python /usr/bin/python3 -m pytest -p no:cacheprovider -p no:xdist -q`, paths under
`phase-loop-runtime/tests/`, one run at a time after the headroom check. New files are absent
on this plan-only checkout, so these are pending selectors.

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
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_grok_seat_jail.py -k live_jail --junitxml=<private-receipt>`, provider-free; a skip or zero collection fails
- `VK`: on the designated seat host's installed runtime: `timeout 300 phase-loop seat-sandbox qualify`, `timeout 300 phase-loop seat-egress status`, `timeout 300 phase-loop seat-window probe-tools --vendor grok`
- Full suite: hosted CI and Gate A only.
