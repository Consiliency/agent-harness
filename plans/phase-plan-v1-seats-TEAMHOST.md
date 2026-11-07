---
phase_loop_plan_version: 1
phase: TEAMHOST
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9dc889c61a8d682dde30af65bf1597c1dca9a0df094fac747194d3629939b16e
automation:
  suite_command: ["timeout", "900", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--python", "3.14", "--python-preference", "only-system", "--locked", "python", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seats_teamhost_subject.py", "phase-loop-runtime/tests/test_seats_teamhost_accounts.py", "phase-loop-runtime/tests/test_seats_teamhost_gemini.py", "phase-loop-runtime/tests/test_seats_teamhost_integration.py", "phase-loop-runtime/tests/test_seats_teamhost_doctor.py", "phase-loop-runtime/tests/test_seats_teamhost_overlay.py", "phase-loop-runtime/tests/test_seats_teamhost_switchon.py", "phase-loop-runtime/tests/test_seat_jail_prerequisites_1357.py", "phase-loop-runtime/tests/test_agy_self_qualification.py", "phase-loop-runtime/tests/test_seat_host_uid_1098.py", "phase-loop-runtime/tests/test_sandbox_policy.py", "phase-loop-runtime/tests/test_agy_integrity_seat_admission.py", "phase-loop-runtime/tests/test_doctor_bom.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# TEAMHOST: Team Hosts and Gemini Follow-ups

## Context

This plan covers roadmap Phase 4 (TEAMHOST) of `specs/phase-plans-seats-v1.md`, pinned above
as amended on agent-harness#1852. Exit criteria are EC-TEAMHOST-1 to EC-TEAMHOST-7, cited by
ID only. The roadmap is advisory (OD-1) and the runner refuses it, so lanes land as governed
PRs under principle 2. The file name follows the manifest pattern of the sibling SEATS plans.
`PLAN_RE` rejects the `phase-plan-seats-v1-<ALIAS>` form, and the owner chose this form on
2026-11-06.

**Frozen artifact.** `plans/seats-teamhost-contract.md` is normative for every interface below
(§1–§8) at sha256 `1dd46b22829d67d8cd7a29c4e4326e7773645dc8863c7677367359424b2e3422`. This plan points at its sections and does not repeat
them. Its input pins include the JAILCORE route contract
(`235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`). TEAMHOST consumes it
only through IF-0-JAILCORE-1, IF-0-JAILCORE-2 and EC-JAILCORE-4.

**Base.** Current main plus the agent-harness#1852 roadmap bytes. FIRSTSEAT L1–L5 and the CLAUDE
code lanes have landed, and FIRSTSEAT lanes A, D and E are finishing. The construction sites
are:

- **Seat subject:** ambient resolution in `panel_invoker._seat_provider_source` and
  `seat_profile`, the import-time `_PROVIDER_SEARCH_PATH`, `_resolve_claude_executable`,
  `gemini_heartbeat.admit` and the keyring-helper bind.
- **Probes:** the probe path `auth_ok_for` → `_run_probe` → `_seat_probe_marker`.
- **Seat ids:** `seat_uid.seat_runtime_dir` and the range prerequisite.
- **Writers and scratch:** the native-fill writers, and scratch resolution in `sandbox_policy`.
- **Doctor:** its single `pytest` prerequisite row and `seat_jail_autoqualify.fix_for`.
- **agy qualification:** its key, which carries `__version__`.
- **Proxy front:** the parser and connection handler in `seat_egress/proxy.mjs`.
- **Gemini overlay:** `GEMINI_WRITABLE_DOTDIR_DIRS`.

Dependency projection admits one required session per process today. Board-wide projection
therefore comes from EC-JAILCORE-4 (gate G-A).

**Owned issues.** EC-TEAMHOST-1 owns agent-harness#1413. EC-TEAMHOST-2 owns
agent-harness#1108. EC-TEAMHOST-3 owns agent-harness#1357, agent-harness#1398 and
agent-harness#1399. EC-TEAMHOST-5 owns agent-harness#1479 and agent-harness#1520.
EC-TEAMHOST-6 owns agent-harness#1706. EC-TEAMHOST-7 owns agent-harness#1420. Each closes
when its EC holds. agent-harness#1602's lifecycle stays outside this roadmap (Non-Goals).

**Scope decisions.**
- Codex and Grok keep their named-exception routes (EC-JAILCORE-5) until CODEX and GROK
  register profiles. Those phases consume IF-0-TEAMHOST-1.
- TEAMHOST changes no Claude or Gemini profile digest except Gemini's item-6 overlay, which
  principle 4 lets it own.
- TEAMHOST adds no notice or route code (contract G1), runs no window and needs no owner
  decision.

## Interface Freeze Gates

All shapes, codes and rules are frozen now in the contract. Lanes implement against them
from day one.

- [ ] IF-0-TEAMHOST-1 — Seat subject (contract §1): `seat_subject.resolve_seat_subject`,
  `SeatSubject`, `open_managed_authority`, `deployment_kind`, `register_provider_executable`,
  `MANAGED_RELEASES_ROOT` and `MANAGED_AUTHORITY_PIN`. The resolution order is session lease →
  managed release → standalone. A managed release, or a failed guarded frontdoor, never falls
  back. Each downstream vendor phase specifies its leg's release declaration content (the
  runtime file list and its v2 pin entry, including `authority_sha256`, `authority_id` and
  `base_profile_sha256`) and adds one `register_provider_executable` call in
  its own module; it never edits `seat_subject.py`. Consiliency/dotfiles builds and ships the
  declaration under IF-XR-1.
- [ ] IF-0-TEAMHOST-2 — Operator state (contract §2): `seat_host_namespace.operator_private_dir`,
  `write_private_atomic`, `subordinate_ranges_disjoint`, `scratch_root_allowed`, plus the closed
  agent-harness#1108 disposition table.
- [ ] IF-0-TEAMHOST-3 — Seat admission and doctor JSON (contract §3–§4):
  `seat_admission.Verdict`, `Gate`, `register`, `verdict(execute=False)`, the closed
  `seat_jail_prerequisites[]` and `seat_cli_qualification[]` rows, `fix_sentence`, the
  LA-1 checklist item ids and the print-only `seat_host_admin` module. Vendor phases register
  gates from their own modules and never reopen `doctor.py`.
- [ ] IF-0-TEAMHOST-4 — agy admission key (contract §5): `agy_profile_digest`,
  `qualification_key`, `written_under`, `has_record`, `admission_verdict`/`AgyVerdict`,
  `requalify_once` (pre-composition only), and the last-known-good provider seam
  (`register_last_known_good`, `last_known_good`), which returns none until agent-harness#1602
  registers a provider. Also `gemini_heartbeat.admit(subject_path=)`.
- [ ] IF-0-TEAMHOST-5 — The agent-harness#1706 ledger and the single Gemini transition
  (contract §6).
- [ ] IF-0-VC-2 — Validate this plan's command argv with
  `phase_loop_runtime.verification_evidence.validate_verification_commands`. The new test
  files report `missing_path` at plan time; re-run after implementation. An unresolved
  executable, an import error, an empty selection or a timeout is not success.

## Cross-Repo Gates

- [ ] IF-XR-1 — Managed-release seat declarations (contract §7).
  - Each vendor phase specifies its leg's declaration content: the runtime file list and its
    v2 pin entry. SL-8's private Claude and Gemini declaration spec must emit
    `authority_sha256`, `authority_id` and `base_profile_sha256` for dotfiles to build.
  - The coordinator routes each specification to Consiliency/dotfiles.
  - Dotfiles builds and ships the per-leg `authority.json` and `declaration.json` in each
    managed release that serves seats.
  - The host administrator writes the root-owned pin (LA1-AUTHORITY-PIN).
  - Neither TEAMHOST nor a vendor phase lands a dotfiles change. From gate G-A on, until the
    declaration and the pin exist, a host's managed-release seats refuse `authority_missing`,
    and the doctor names the item.
  - LA-1 is not required to land code.

## Lane Index & Dependencies

SL-1 — A1: Seat subject and search-only probes
  Depends on: (none)
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-2 — B: Operator isolation
  Depends on: (none)
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-3 — D: Gemini follow-ups and agy key
  Depends on: (none)
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-4 — A2: Seat integration
  Depends on: SL-1, SL-2, SL-3
  Blocks: SL-5, SL-6
  Parallel-safe: no

SL-5 — C: Doctor, admission agreement and checklist
  Depends on: SL-2, SL-3, SL-4
  Blocks: SL-6
  Parallel-safe: no

SL-6 — SL-docs: Documentation and spec reconciliation
  Depends on: SL-1, SL-2, SL-3, SL-4, SL-5, SL-7, SL-8
  Blocks: (none)
  Parallel-safe: no

SL-7 — D2: Gemini overlay (gate G-D)
  Depends on: SL-3
  Blocks: SL-6
  Parallel-safe: yes

SL-8 — A3: Managed-release switch-on (gate G-A)
  Depends on: SL-4, SL-5
  Blocks: SL-6
  Parallel-safe: no

## Lanes

### SL-1 — A1: Seat subject and search-only probes

- **Scope**: Implement IF-0-TEAMHOST-1 and the EC-TEAMHOST-1 search-only probe proof, without touching any launch site.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_subject.py`, `phase-loop-runtime/tests/test_seats_teamhost_subject.py`
- **Interfaces provided**: IF-0-TEAMHOST-1
- **Interfaces consumed**: `current_dependency_for_provider` (pre-existing), `panel_invoker._frontdoor_target` (pre-existing), `admit_executable_dependency` (pre-existing), IF-0-JAILCORE-1 (pre-existing roadmap contract)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_subject.py` | `seats_teamhost_subject` (see below) | `V-A` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_subject.py` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 files | all SL-1 tests | `V-A` |

**`seats_teamhost_subject` cases.**
- **Release fixtures.** These are built under a tmp root that is substituted for
  `MANAGED_RELEASES_ROOT` and the pin, with root ownership substituted the way
  `test_seat_frontdoor_1798.py` does it. Cases:
  - Order: a bound lease wins, then a frontdoor into a release gives `managed_release`, then
    a plain install gives `standalone`.
  - Pin and subject: a missing pin, a missing entry, a writable pin, a non-root ancestor, a
    digest mismatch and a self-hashed authority each refuse with their contract §1 code.
  - No fallback: a refused `managed_release` never yields `standalone`.
  - Selected subject only: no interpreter or launcher is admitted.
  - PATH: it is read at call time, so a changed `env["PATH"]` changes the result.
  - `deployment_kind`: each value comes from a path fixture, with no spawn (spy).
- **Search-only probe.** A 0o111 operator-owned ancestor above `TMPDIR` and the cwd. The real
  `auth_ok_for` reaches a stub CLI, which writes a marker file that proves it ran.
  - Mutant: an `O_RDONLY` ancestor walk in a test-local copy of the bind-source walk turns
    the case red.
  - Under euid 0 the case fails rather than skips.

### SL-2 — B: Operator isolation

- **Scope**: Implement IF-0-TEAMHOST-2 and EC-TEAMHOST-2 at the seat-uid, scratch and native-fill sites, and record the agent-harness#1108 dispositions.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_host_namespace.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/tests/test_seats_teamhost_accounts.py`, `phase-loop-runtime/tests/test_seat_host_uid_1098.py`, `phase-loop-runtime/tests/test_sandbox_policy.py`
- **Ownership note**: `seat_uid.py` is edited only in `seat_runtime_dir` and the L3 range conjunct (contract §8). `sandbox_policy.py` is edited only in `_child_tmp_dir` and `child_scratch_candidates`, `cli.py` only in `_advisor_board_command`'s native-fill writes, and `governed_review.py` only in `governed_board_gate`'s native-fill directory. `test_governed_review.py` stays untouched; SL-2's native-fill cases live in `test_seats_teamhost_accounts.py`.
- **Interfaces provided**: IF-0-TEAMHOST-2
- **Interfaces consumed**: `seat_uid.lease_seat_id` (pre-existing), `seat_uid.subordinate_range` (pre-existing), IF-0-JAILCORE-1 (pre-existing roadmap contract)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_accounts.py` | `seats_teamhost_accounts` (see below) | `V-B` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_host_namespace.py` | — | — |
| SL-2.3 | impl | SL-2.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py` | — | — |
| SL-2.4 | verify | SL-2.3 | SL-2 files | all SL-2 tests | `V-B` |

**`seats_teamhost_accounts` cases.**
- **Two concurrent identities.** Use distinct euids (substituted the way
  `test_seat_host_uid_1098.py` does it), distinct `HOME`, `XDG_*` and `TMPDIR`. Each runs the
  real seat-id lease, scratch resolution, native-fill writers and per-leg exec-record writer
  (IF-0-FIRSTSEAT-3) concurrently. Assert that no path, lock or descriptor is shared, and that
  neither identity can open the other's exec records or seat state.
- **Foreign state is refused.** A foreign-owned, group-writable or linked state directory, a
  pre-created fallback directory and a planted `native-fill` link each refuse with
  `seat_sandbox_refused:identity`.
- **Ranges.** An overlapping fixture `/etc/subuid` range gives
  `seat_sandbox_unavailable_seat_uid`.
- **Scratch.** A `TMPDIR` under `/dev` is skipped.
- **Mutants.** Dropping the owner check, or the disjointness conjunct, turns each case red.
- **Dispositions.** The table's eight rows are pinned by name.

### SL-3 — D: Gemini follow-ups and agy key

- **Scope**: Implement IF-0-TEAMHOST-4 for EC-TEAMHOST-7 and IF-0-TEAMHOST-5 for EC-TEAMHOST-6.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs`, `plans/evidence/seat-jail-1132/run_mutation_receipts_1170.py`, `plans/evidence/seat-jail-1132/mutation-receipts-1170.json`, `phase-loop-runtime/tests/test_seats_teamhost_gemini.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/test_agy_integrity_seat_admission.py`
- **Ownership note**: `proxy.mjs` is edited only in the ClientHello parser and the front connection handler. Contract §6 item 6 (the Gemini overlay) is lane SL-7.
- **Interfaces provided**: IF-0-TEAMHOST-4, IF-0-TEAMHOST-5
- **Interfaces consumed**: `agy_qualification.ensure_admitted` (pre-existing), `gemini_heartbeat.owned_profile` (pre-existing), `seat_egress_proxy.start_proxy` (pre-existing), IF-0-JAILCORE-1 (pre-existing roadmap contract), IF-0-JAILCORE-2 (pre-existing roadmap contract)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_gemini.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py` | `seats_teamhost_agy_key` and `seats_teamhost_1706` (see below) | `V-D` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py` | — | — |
| SL-3.3 | impl | SL-3.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_egress/proxy.mjs`, `plans/evidence/seat-jail-1132/run_mutation_receipts_1170.py`, `plans/evidence/seat-jail-1132/mutation-receipts-1170.json` | — | — |
| SL-3.4 | verify | SL-3.3 | SL-3 files | all SL-3 tests | `V-D` |

**`seats_teamhost_agy_key` cases.**
- These cases replace the version-in-key cells of `test_agy_self_qualification.py`; every
  other assertion stays.
- **Record survives:** a `__version__` bump plus a release-set edit keeps the record.
- **Record requalifies once:** an owned-profile or `OPERATIONS_CONTRACT` edit misses, and the
  pre-composition `requalify_once` then qualifies once through the existing login wait
  (stubbed renewal, no `agy models` call). A forced failure writes `failed`, and a second
  board does not retry within the window.
- **Nothing mid-run:** `ensure_admitted` is spied after composition is fixed, and in legs and
  the president, and records zero calls. A required session gives `dependency_route_unwired`.
- **Last known good:** a fixture provider is admitted with `source="lkg"`. The default is
  none.
- **Read-only checks:** `has_record` and `admission_verdict(execute=False)` spawn nothing.

**`seats_teamhost_1706` cases** are the contract §6 rows. Each has a neutralising mutant.

**Item 6** is lane SL-7 (gate G-D).

### SL-4 — A2: Seat integration

- **Scope**: The first of two serial TEAMHOST writers of `panel_invoker.py` (SL-4, then SL-8). It wires IF-0-TEAMHOST-1, -2 and -4 at the contract §8 call sites; the switch-on is SL-8.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_seats_teamhost_integration.py`
- **Ownership note**: `test_panel_invoker.py` stays untouched; JAILCORE SL-3 owns it, and TEAMHOST integration tests live in the new file.
- **Interfaces provided**: `integrated_seat_subject`, `board_preflight_requalify`
- **Interfaces consumed**: IF-0-TEAMHOST-1, IF-0-TEAMHOST-2, IF-0-TEAMHOST-4, IF-0-JAILCORE-1 (pre-existing roadmap contract)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_integration.py` | `seats_teamhost_integration` (see below) | `V-I` |
| SL-4.2 | impl | SL-4.1 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 files | all SL-4 tests | `V-I`, `V-R` |

**`seats_teamhost_integration` cases.** These enter `seat_profile`, `_prepare_jailed_gemini`,
`_prepare_jailed_claude` and `invoke_board` with stub providers.
- **Resolution and refusal.** Provider resolution goes through `resolve_seat_subject`. A
  refused managed release launches nothing. The keyring-helper bind passes the bind-source
  checks.
- **Native-fill writes** go through `write_private_atomic`.
- **Requalify once.** A board composing a jailed Gemini seat calls `requalify_once` before
  composition and never afterwards.
- **agy admission.** A Gemini subject from any source passes agy admission.

**Integration tasks.** SL-4.2 lands everything except the switch-on, which is lane SL-8.

### SL-5 — C: Doctor, admission agreement and checklist

- **Scope**: Implement IF-0-TEAMHOST-3 for EC-TEAMHOST-3, EC-TEAMHOST-4 and EC-TEAMHOST-5.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_admission.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_host_admin.py`, `phase-loop-runtime/src/phase_loop_runtime/doctor.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_prerequisites.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_autoqualify.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.golden.json`, `docs/team-host-admin.md`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`, `phase-loop-runtime/tests/test_seat_jail_prerequisites_1357.py`, `phase-loop-runtime/tests/test_doctor_bom.py`
- **Ownership note**: `seat_jail_autoqualify.py` is edited only in `fix_for`; `test_seat_jail_autoqualify.py` stays untouched (JAILCORE SL-3 owns it). `doctor.py` is edited only in its seat rows, coordinated with v11 GOVSETUP.
- **Interfaces provided**: IF-0-TEAMHOST-3
- **Interfaces consumed**: IF-0-TEAMHOST-1, IF-0-TEAMHOST-2, IF-0-TEAMHOST-4, `integrated_seat_subject`, `seat_jail.seat_sandbox_capable` (pre-existing), `seat_jail.pass_record_verdict` (pre-existing), `panel_invoker.require_grok_admission` (pre-existing), IF-0-JAILCORE-1 (pre-existing roadmap contract)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`, `phase-loop-runtime/tests/test_seat_jail_prerequisites_1357.py` | `seats_teamhost_doctor`, `seats_teamhost_agreement` and `seats_teamhost_checklist` (see below) | `V-C` |
| SL-5.2 | impl | SL-5.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_admission.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_prerequisites.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail_autoqualify.py`, `phase-loop-runtime/src/phase_loop_runtime/doctor.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.golden.json` | — | — |
| SL-5.3 | impl | SL-5.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_host_admin.py`, `docs/team-host-admin.md` | — | — |
| SL-5.4 | verify | SL-5.3 | SL-5 files | all SL-5 tests | `V-C` |

**SL-5.1 cases.**
- **`seats_teamhost_doctor`.**
  - **Rows.** Each row's predicate is injected missing, and the row names its checklist item.
  - **Off Linux.** With `sys.platform` set to `darwin` or `win32`, every row is
    `unknown`/`platform_unsupported` and spawns nothing (spy). No `/usr/bin/python3` is
    spawned.
  - **Fix text.** Each deployment yields exactly one sentence, and `managed` names
    LA1-RELEASE. The existing pins in `test_seat_jail_prerequisites_1357.py` move to the
    sentence form.
  - **Schema.** The golden file validates.
  - **`fix_for`.** A missing `pytest` on a host that is not ready returns only the pytest
    sentence. The host text appears once the operator has fixed pytest.
- **`seats_teamhost_agreement`.** A fixture table covers:
  - a release agy, a valid local record, a record whose MAC fails, a provenance-less record
    and no record;
  - a missing credential, an uninstalled egress layer and a failed guarded frontdoor;
  - each host-capability code;
  - stale and valid jail passes.
  
  For each state, the doctor verdict is compared with the real seat preparation's outcome
  (`integrated_seat_subject`), which must agree.
  - Mutant: a doctor that reports record existence, the agent-harness#1479 shape, turns the
    case red.
- **`seats_teamhost_checklist`.**
  - Every LA-1 item and doctor row maps to a checklist id.
  - An AST scan finds no exec import in `seat_host_admin`, and nothing imports it.
  - A run with spy executables on `PATH` records no call.

### SL-6 — SL-docs: Documentation and spec reconciliation

- **Scope**: Refresh the docs catalog, update cross-cutting documentation touched or invalidated by this phase's impl lanes, and append any post-execution amendments to phase specs whose interface freezes turned out wrong.
- **Owned files**: `CHANGELOG.md`, `docs/TEAM-ONBOARDING.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `.claude/docs-catalog.json`, `.doc-decisions.json`, `plans/manifest.json`, `plans/seats-teamhost-contract.md`, `plans/evidence/seat-teamhost/doctor-receipts.json`
- **Ownership note**: Every file here is JAILCORE SL-4's in that phase. TEAMHOST edits only its own entries and sections, union-resolved. `docs/review-seats-readiness.md` is edited only in the Gemini row. Each lane's PR adds its own `CHANGELOG.md` and inventory entries under this lane's ownership, entry by entry.
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-TEAMHOST-1, IF-0-TEAMHOST-2, IF-0-TEAMHOST-3, IF-0-TEAMHOST-4, IF-0-TEAMHOST-5, `integrated_seat_subject`, `board_preflight_requalify`
- **Parallel-safe**: no (terminal)

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan the catalog; add `docs/team-host-admin.md`. |
| SL-docs.2 | docs | SL-docs.1 | per catalog | TEAM-ONBOARDING links the checklist and the doctor rows. The card gets the doctor vocabulary and the managed-release subject. CONTRACTS gets the item-3(c) and item-4 wording. The matrix's Gemini row returns to `candidate`, naming the first row window after TEAMHOST exits. |
| SL-docs.3 | docs | SL-docs.2 | `plans/evidence/seat-teamhost/doctor-receipts.json` | A provider-free `phase-loop doctor --json` from the first released runtime that carries this phase, on one team host and one standard host, recorded metadata-only (host classes, never host names). It is supporting evidence; V-C is the proof. |
| SL-docs.4 | docs | SL-docs.3 | `specs/phase-plans-seats-v1.md`, prior plans | Append `### Post-execution amendments` where a freeze proved wrong. |
| SL-docs.5 | verify | SL-docs.4 | — | `V-R`, `V-S`. |

### SL-7 — D2: Gemini overlay (gate G-D)

- **Scope**: Contract §6 item 6, on a base that holds the IF-0-JAILCORE-1 registration of the Gemini profile.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/tests/data/seat_profile_digests_jailcore.json`, `plans/evidence/seat-teamhost/gemini-config-writes.json`, `phase-loop-runtime/tests/test_seats_teamhost_overlay.py`
- **Ownership note**: Edited only at the contract §8 names. `test_seat_jail.py` and `test_seat_profiles.py` stay untouched (JAILCORE SL-3 owns them).
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-TEAMHOST-5, IF-0-JAILCORE-1 (pre-existing roadmap contract)
- **Parallel-safe**: yes

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-7.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_overlay.py` | `seats_teamhost_overlay`: each recorded write is admitted and a write outside the narrowed overlay is refused, through the real Gemini bind builder; mutant: restore the whole-directory overlay | `V-O` |
| SL-7.2 | impl | SL-7.1 | the SL-7 source and data files | — | — |
| SL-7.3 | verify | SL-7.2 | SL-7 files | all SL-7 tests | `V-O`, `V-D` |

Without a recorded measurement, item 6 is deferred with the contract's reason, and SL-7 changes only the evidence record.

### SL-8 — A3: Managed-release switch-on (gate G-A)

- **Scope**: The contract §1 switch-on and the §3 authority gate, on a base that holds EC-JAILCORE-4's per-profile projection, plus the Claude and Gemini declaration specifications that contract §7 routes to Consiliency/dotfiles.
- **Owned files**: `phase-loop-runtime/tests/test_seats_teamhost_switchon.py`
- **Ownership note**: Serial after SL-4; edited only at the contract §8 names. SL-8 also edits `panel_invoker.py`, but only after SL-4 has merged and only at those names. The file is listed under SL-4 alone because `validate_plan_doc` check (D) has no form for serial ownership (coordinator decision, 2026-11-06).
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-TEAMHOST-1, IF-0-TEAMHOST-3, `integrated_seat_subject`, IF-0-JAILCORE-1 (pre-existing roadmap contract)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | — | `phase-loop-runtime/tests/test_seats_teamhost_switchon.py` | `seats_teamhost_switchon`: a registered profile with projection `optional` launches the managed-release subject at its declared destination with its profile digest unchanged; a missing pin, a missing entry or a digest mismatch refuses its §1 code, launches nothing and never falls back; the doctor and the seat agree on each state | `V-G` |
| SL-8.2 | impl | SL-8.1 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | — | — |
| SL-8.3 | verify | SL-8.2 | SL-8 files | all SL-8 tests | `V-G`, `V-I`, `V-C` |

## Execution Notes

- **Parallelism.**
  - SL-1, SL-2 and SL-3 are roots. SL-4 integrates them, and SL-5 compares the doctor with the
    integrated launch path.
  - Every lane executes after FIRSTSEAT exits (gate G-F) and in parallel with JAILCORE.
- **Cross-phase gates.** Contract §8's G-A holds lane SL-8 and G-D holds lane SL-7. Only those
  two lanes, and SL-6 after them, wait for JAILCORE.
- **Single-writer files.**
  - `panel_invoker.py` → SL-4, then SL-8. `seat_uid.py`, `cli.py` and `governed_review.py` → SL-2.
    `seat_jail_autoqualify.py` → SL-5. `proxy.mjs` → SL-3. `seat_jail.py` and `seat_profiles.py` → SL-7.
  - Each is also written by another phase, only at the functions contract §8 names; the
    second lander rebases.
  - v11 shares three modules: PANELSPLIT `panel_invoker.py`, GOVSETUP `doctor.py`, and
    RESIDUAL the sidecar and broker files, which TEAMHOST does not edit.
- **Known destructive changes**: none. Every lane is purely additive at file level. The agy
  key replaces its version part, so old records are ignored, never deleted (contract §5).
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none; no preamble lane.
- **Worktree naming**: claude-execute-phase allocates unique worktree names via
  `scripts/allocate_worktree_name.sh`. Plan doc does not need to spell out lane worktree paths.
- **Stale-base guidance**: Lane teammates working in isolated worktrees do not see sibling-lane
  merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's
  merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or
  rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces
  commits that destroy peer-lane work on `--no-ff` merge.
- **Gemini transition.** All Gemini key changes name the first row window after TEAMHOST
  exits (principle 4). SL-8 changes Claude's qualification key through its projection
  digest, but not its profile digest. Claude stays `candidate` until CLAUDENET.
- **agent-harness#1602.** Its pinned plan keys on module digests, and only its watcher
  qualifies. IF-0-TEAMHOST-4 keys on a declared digest and lets the pre-composition preflight
  requalify once (EC-TEAMHOST-7). SL-docs records this divergence as a comment on
  agent-harness#1602, so its L5 adopts or amends IF-0-TEAMHOST-4 before re-keying agy.
  TEAMHOST does not edit that plan.
- **Shared-host limits.** Check `uptime` and IO pressure first. Run targeted files serially
  under `timeout 900`, with `-p no:cacheprovider` and without `-n`. Never use
  `local_check.py --full`. Jail-touching cases need system Python 3.14.4, hence
  `--python-preference only-system`.
- **Before Gate A.** Run V-R. The new modules launch nothing; any launch-site change gets an
  inventory decision. Run a clean-room wheel check: repo-only reads skip when files are
  absent, and `docs/team-host-admin.md` is not package data. Then dispatch
  `gh workflow run test.yml --repo Consiliency/agent-harness --ref <branch> -f chronology=false`.
- **OD-10.** Public text states requirements (contract G3).

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/TEAM-ONBOARDING.md`, `docs/advisor-board-capabilities-card.md`, `docs/team-host-admin.md`
- evidence paths: `plans/evidence/seat-teamhost/`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment` (record gates G-A and G-D, which hold lanes SL-8 and SL-7, beside TEAMHOST's dependency line; accepted by the coordinator on 2026-11-06)

## Acceptance Criteria

- [ ] EC-TEAMHOST-1 — proven by `V-A`, `V-I` and `V-G` (`seats_teamhost_subject`, `seats_teamhost_integration`), falsified by a stub CLI that never runs below the 0o111 ancestor, a refused managed release that launches a standalone or ambient subject, or a self-hashed authority admitted, each path-entered through the real `auth_ok_for` / `resolve_seat_subject` / `seat_profile` path.
- [ ] EC-TEAMHOST-2 — proven by `V-B` (`seats_teamhost_accounts`), falsified by a shared path, lock or descriptor between the two identities, one identity opening the other's exec records or seat state, or a foreign-owned state directory or overlapping range accepted by the real lease, scratch or native-fill code.
- [ ] EC-TEAMHOST-3 — proven by `V-C` (`seats_teamhost_doctor`), with `plans/evidence/seat-teamhost/doctor-receipts.json` as supporting team-host evidence, falsified by a spawn off Linux, a row whose status disagrees with its route predicate, or a multi-sentence or managed-branch-less fix from the real `doctor.run_doctor`.
- [ ] EC-TEAMHOST-4 — proven by `V-C` (`seats_teamhost_checklist`), falsified by an LA-1 root action missing from `docs/team-host-admin.md` or any exec reached from `seat_host_admin`.
- [ ] EC-TEAMHOST-5 — proven by `V-C` (`seats_teamhost_agreement`), falsified by a doctor `admits` for a fixture state the real seat preparation refuses.
- [ ] EC-TEAMHOST-6 — proven by `V-D` and `V-O` (`seats_teamhost_1706`), falsified by a neutralised check that stays green, or an agent-harness#1706 item with no closure or recorded deferral.
- [ ] EC-TEAMHOST-7 — proven by `V-D` (`seats_teamhost_agy_key`), falsified by a lost record after a version bump or release-set edit, or an `ensure_admitted` call after composition, through the real `lookup` and `invoke_board` preflight.

## Verification

`P` = `timeout 900 uv run --quiet --project phase-loop-runtime --group test --python 3.14
--python-preference only-system --locked python -m pytest -p no:cacheprovider -q`.

```bash
# V-A
P phase-loop-runtime/tests/test_seats_teamhost_subject.py
# V-B
P phase-loop-runtime/tests/test_seats_teamhost_accounts.py phase-loop-runtime/tests/test_seat_host_uid_1098.py phase-loop-runtime/tests/test_sandbox_policy.py
# V-D
P phase-loop-runtime/tests/test_seats_teamhost_gemini.py phase-loop-runtime/tests/test_agy_self_qualification.py phase-loop-runtime/tests/test_agy_integrity_seat_admission.py
# V-I
P phase-loop-runtime/tests/test_seats_teamhost_integration.py
# V-O
P phase-loop-runtime/tests/test_seats_teamhost_overlay.py phase-loop-runtime/tests/test_seat_profiles.py
# V-G
P phase-loop-runtime/tests/test_seats_teamhost_switchon.py
# V-C
P phase-loop-runtime/tests/test_seats_teamhost_doctor.py phase-loop-runtime/tests/test_seat_jail_prerequisites_1357.py phase-loop-runtime/tests/test_doctor_bom.py
# V-R
P phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py phase-loop-runtime/tests/test_seat_reference_inventory.py
# V-S
uv run --quiet --project phase-loop-runtime python phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-seats-TEAMHOST.md
timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md
uv run --quiet --project phase-loop-runtime python -m phase_loop_runtime.plan_manifest check --repo .
```
