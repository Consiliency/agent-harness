---
phase_loop_plan_version: 1
phase: CLAUDE
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 82efbc23a19b62044e2e8252d90a0124a1c0b5d2cc6ae2180259f63dd2941ca3
automation:
  suite_command: ["timeout", "1800", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--extra", "visual", "--with", "pytest-xdist==3.8.0", "--python", "3.14", "--locked", "python", "-m", "pytest", "-n", "0", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seats_claude_login_proof.py", "phase-loop-runtime/tests/test_seats_claude_bakeoff.py", "phase-loop-runtime/tests/test_seats_claude_transport.py", "phase-loop-runtime/tests/test_seats_claude_records.py", "phase-loop-runtime/tests/test_seats_claude_print.py", "phase-loop-runtime/tests/test_seats_claude_print_observations.py", "phase-loop-runtime/tests/test_seats_claude_sdk.py", "phase-loop-runtime/tests/test_seats_claude_sdk_adapter.py", "phase-loop-runtime/tests/test_claude_transport_seam.py", "phase-loop-runtime/tests/test_panel_claude_print_route.py", "phase-loop-runtime/tests/test_seat_credentials.py", "phase-loop-runtime/tests/test_seat_login_wait_a3_1166.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_executable_dependency_startup.py"]
---

# CLAUDE: Claude Seat Transports and Bake-off

## Context

This plan covers roadmap Phase 1 (CLAUDE) of `specs/phase-plans-seats-v1.md`, a root phase
with no phase dependencies. Exit criteria are EC-CLAUDE-1 to EC-CLAUDE-8. This plan cites
them by ID and never restates them. The roadmap is advisory (OD-1). The runner refuses it,
so each lane lands as one or more governed PRs under roadmap principle 2. The plan file
name departs from the roadmap's `phase-plan-seats-v1-<ALIAS>.md`, because the manifest's
canonical pattern requires `phase-plan-v…`. That was the root maintainer's decision.

Inputs (pinned in the roadmap's External Inputs, not here):
- the print-route decision record, whose §4a is the agent-harness#1775 record;
- the Stage 3 SDK record;
- the dependency projection contract;
- the dated Claude billing statement.

The billing statement is Help Center article 15036540, read 2026-11-04: under a subscription
login, the Agent SDK and `claude -p` draw on subscription limits. That has held since the
2026-06-15 pause and was reaffirmed on 2026-10-07. The bake-off (W0) is the empirical check.

Today's tree, checked during planning:
- The non-jailed seam (`_resolve_claude_transport`, `PHASE_LOOP_PANEL_CLAUDE_ROUTE`) already
  names `sdk` and refuses it.
- The jailed seat (`_prepare_jailed_claude`, `_exec_jailed_claude_leg`) ignores the selector
  and runs only the TUI.
- The jail profile digest covers the owner argv and the filter, with dependency mounts
  stripped. The provider argv does not affect it.
- Drafts agent-harness#1740 and agent-harness#1744 conflict with main. They are mined, never
  rebased.

Owner decisions this phase obeys:
- **OD-3a.** The decision-record amendment lands in its own reviewed PR before any default
  change, `sdk` activation or W0 `sdk` run.
- **OD-3b.** The owner picks the default from W0 evidence.
- **TUI last.** The TUI is the last fallback.
- **Open egress.** Claude's open egress is a named exception that expires when CLAUDENET
  exits.

This phase changes no jail profile digest and edits neither `seat_jail.py` nor any profile
builder.

## Interface Freeze Gates

- [ ] IF-0-CLAUDE-1 — The roadmap gate, frozen here as concrete symbols in the new
  `phase_loop_runtime/claude_seat_transport.py`:
  - `ClaudeTransport = Literal["tui", "print", "sdk"]`.
  - `JAILED_CLAUDE_DEFAULT`: the one declared setting, initially `"tui"` (§4a item 2). Its
    companion `JAILED_DEFAULT_AUTHORITY: RecordCitation | None` is `None` while the value is
    `"tui"`.
  - `RecordCitation(record, section, section_sha256, pr)`.
  - `resolve_jailed_claude_transport(env) -> tuple[ClaudeTransport | None, str | None]` reads
    the existing `PHASE_LOOP_PANEL_CLAUDE_ROUTE`. Unset or blank resolves to the default; an
    unknown value refuses `panel_claude_route_invalid`; a known value that is not admitted
    refuses `panel_claude_transport_not_admitted`. A refusal never falls back.
  - `tui` is always admitted. `print` and `sdk` are admitted only when their module
    (`claude_seat_print`, `claude_seat_sdk`) imports and exports `ADMITTED = True`, an
    `ACTIVATION: RecordCitation`, and `run_jailed(seat, **kwargs) -> tuple[str, str]`.
    `run_jailed` takes the keywords of today's `_exec_jailed_claude_leg`.
  - Invariants across transports:
    - the same `_JailedSeat` (jail, probe jail, staged clone);
    - the same teardown (`_cleanup_jailed_seat`);
    - the same tool posture (`--tools default`, `bypassPermissions`, closed settings, MCP and
      agents);
    - the credential only through the existing token pipe (`CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`);
    - no new environment variable and no new `pass_fds`.
  - Equality is checked on the profile-digest view: owner argv without dependency mounts.
    `sdk` may differ only by its declared closure, which is recorded by
    `dependency_projection_digest`.
  - Transport modules late-bind `panel_invoker` helpers at call time, through the facade
    (PANELSPLIT-compatible), and change none of them.
- [ ] IF-0-CLAUDE-2 — The roadmap's record fields, implemented in the new
  `phase_loop_runtime/claude_bakeoff.py`:
  - `BakeoffRecord`, serialized as canonical JSON `claude-bakeoff-record.v1`, one file per
    run at `plans/evidence/seat-qualification/claude-w0/<run_id>.json`;
  - `validate_record(obj) -> tuple[str, ...]`;
  - `evidence_digest(directory) -> str`, the sha256 over sorted record bytes. OD-3b cites
    it.
  - Transport values are `print`, `sdk` and `t3-sdk-control`.
  - Transports write these `broker_evidence` keys, which the recorder reads:
    `claude_transport`, `claude_code_entrypoint`, `claude_api_key_source`,
    `claude_admission` (predicate → bool) and the §4a item 7 diagnostics.
    `claude_code_entrypoint` is observed at the CLI process boundary, never inferred from
    the transport name.
  - Records are metadata only: no transcript, review text, token, account identifier or
    private host.
  - For `t3-sdk-control`, jail-only predicates record `not_applicable`. The entrypoint,
    the meter reference and the canonical-output outcome stay required.
- [ ] IF-0-CLAUDE-3 — A plan-local gate: the `sdk` in-jail closure.
  - The subject stays the system `claude` at the canonical `/seat/bin/claude` slot, which is
    the SDK `cli_path`.
  - Declared files: a pinned CPython with a zipped stdlib, the `claude-sdk` extra's packages
    zipped for zipimport, and the in-jail entry. This keeps the closure within the
    projection ceilings (1,024 entries).
  - Launch argv: `<projected python> -I <entry>`. The entry sets its import path from the
    declared destinations.
  - SDK options:
    - `setting_sources=[]`;
    - `strict_mcp_config=True`;
    - tools and permission mode equal to the jailed TUI's;
    - no token in options, argv, environment or seat home.
  - The CLI child inherits the token-pipe descriptor.
  - Stage 3 record §3 conditions 1, 4 and 5 apply inside the jail.
  - If the jail cannot run a declared non-subject interpreter without changing the base
    profile digest or the projection contract, SL-3 stops. It reports roadmap Assumption 2
    as false, which requires a roadmap amendment, not a plan workaround.
- [ ] IF-0-CLAUDE-4 — A plan-local gate: the jailed login proof.
  - `seat_credentials.jailed_login_proof(credential, auth_probe) -> LoginProof` applies to
    the selected credential the same proof the print and TUI routes hold
    (agent-harness#1532): the subscription check on the same login context, plus a
    single-use auth-status probe on that exact credential. `auth_probe` is the caller's
    jailed probe.
  - `seat_preflight.republish_seat_mode(stream_dir, mode) -> Path` replaces one seat's row
    in `seat-modes.json` (agent-harness#1255).

## Lane Index & Dependencies

SL-0 — Lane D core: login proof, bake-off recorder and W0 kit
  Depends on: (none)
  Blocks: SL-1, SL-4
  Parallel-safe: yes

SL-1 — Lane A: jailed seam, decision records and default
  Depends on: SL-0
  Blocks: SL-2, SL-3, SL-4
  Parallel-safe: no

SL-2 — Lane B: jailed print transport
  Depends on: SL-1
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Lane C: jailed sdk transport and claude-sdk extra
  Depends on: SL-1
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Docs and shared inventory reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Lane D core: login proof, bake-off recorder and W0 kit

- **Scope**: Deliver EC-CLAUDE-7's helpers, IF-0-CLAUDE-2's recorder and validator, and the W0 kit (`python -m phase_loop_runtime.claude_bakeoff`), without touching `panel_invoker.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_bakeoff.py`, `phase-loop-runtime/tests/test_seats_claude_login_proof.py`, `phase-loop-runtime/tests/test_seats_claude_bakeoff.py`, `phase-loop-runtime/tests/test_seat_credentials.py`, `phase-loop-runtime/tests/test_claude_seat_subscription_proof_1444.py`, `phase-loop-runtime/tests/test_seat_credential_refresh.py`
- **Interfaces provided**: `IF-0-CLAUDE-2`, `IF-0-CLAUDE-4`
- **Interfaces consumed**: none
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_login_proof.py`:
    - A credential that passes the store check but fails the auth probe is refused typed.
    - A probe run on a different credential than the selected one is refused.
    - A timed-out wait yields a republished `degraded` row whose code and fix line match the
      existing `claude_seat_login_token_expiring` and `claude_seat_token_missing` text.
  - test: `test_seats_claude_bakeoff.py`:
    - The validator rejects a record missing its entrypoint, meter reference, item 7
      outcome or billing value.
    - It rejects a record that carries a planted token in any `contains_secret` encoding.
    - The evidence digest is order-independent.
    - The kit refuses to start without a run plan matching Execution Notes.
  - impl: Mine agent-harness#1740's `seat_credentials.py` login-context change into
    `jailed_login_proof`. Add `republish_seat_mode`.
  - impl: Write `claude_bakeoff.py`. It covers the record, the validator, the digest, the
    arm runner (the native board seat path through `phase-loop advisor-board` with the
    selector set per arm), the control-arm recorder from owner inputs, and a composition
    preflight that stops before any run whose board would refuse composition.
  - impl: Measure the request set without changing the jail profile digest, seat
    environment or credential channel. Record each host plus whatever method and path are
    observable. EC-CLAUDE-1's test guards this.
  - impl: Give SL-4 this lane's inventory rows (`static_references` output) for its landing
    PR.
  - verify: `V1`.

### SL-1 — Lane A: jailed seam, decision records and default

- **Scope**: Make the jailed seat read IF-0-CLAUDE-1. Wire IF-0-CLAUDE-4 into the jailed launch. Own the decision record, the v11 amendment, the W0 records, the OD-3b record and the default switch.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `plans/decision-claude-print-subscription-route-20261008.md`, `specs/phase-plans-v11.md`, `plans/phase-plan-v11-*.md`, `plans/evidence/seat-qualification/claude-w0/**`, `phase-loop-runtime/tests/test_seats_claude_transport.py`, `phase-loop-runtime/tests/test_seats_claude_records.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_claude_transport_seam.py`, `phase-loop-runtime/tests/test_panel_claude_print_route.py`, `phase-loop-runtime/tests/test_seat_login_wait_a3_1166.py`, `phase-loop-runtime/tests/test_seat_login_wait_board_context_r12.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_session_label.py`, `phase-loop-runtime/tests/test_seat_sandbox_permissions.py`
- **Interfaces provided**: `IF-0-CLAUDE-1`
- **Interfaces consumed**: `IF-0-CLAUDE-4`, `IF-0-CLAUDE-2`
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_seats_claude_transport.py`:
    - Resolution and refusal cover every value; a refused value launches nothing and has
      no fallback.
    - The invariant test asserts IF-0-CLAUDE-1 equality across `tui`, a stub `print` and a
      stub `sdk` module. Path-entered controls are stub transports that each add one
      environment variable, one pass fd or one tool, or that change the profile digest;
      each must fail.
    - The login proof and republish are wired on every jailed transport.
    - The transport is written to `broker_evidence` as `claude_transport`.
  - test: `test_seats_claude_records.py`:
    - Each admitted module's and the default's `RecordCitation` matches the
      sha256 of its cited section in the tree. With `SEATS_CLAUDE_BASE_REF` set to the
      landing's base, the test reads the record from that ref. A section that arrives in
      the same PR then fails.
    - The amendment's responsibility table names exactly one owner per responsibility
      (EC-CLAUDE-8), and `specs/phase-plans-v11.md` carries the consumption note.
    - `JAILED_CLAUDE_DEFAULT` equals the recorded OD-3b value, or `tui` while OD-3b is
      unrecorded, and the card's default statement names the same value.
  - impl: Seam PR. Add `claude_seat_transport.py`. At the jailed Claude call site in
    `_parent_infer`, `_prepare_jailed_claude` and the login-wait branch, resolve the
    transport before preparing the jail, dispatch through it and wire IF-0-CLAUDE-4.
    `print` and `sdk` stay refused until their modules land. The PR carries the existing
    tests' expectation updates for the jailed seat reading the selector (§4a item 3) and
    never weakens an assertion.
  - impl: Amendment PR. Records only, in its own reviewed PR. It adds a new section to the
    print-route record covering:
    - everything OD-3a lists;
    - the EC-CLAUDE-8 responsibility table, with PANELSPLIT's mechanical extraction staying
      in v11;
    - the token pipe for `sdk`;
    - TUI last;
    - the open-egress disclosure until CLAUDENET exits.

    The maintainer's merge ratifies it (gate G1).
  - impl: v11 PR, after G1. A records-only amendment to `specs/phase-plans-v11.md`. It
    marks the affected EC-PANEL-6 items as consumed by the EC IDs in the amendment, notes
    the departure from EC-REVIEWTRUTH-15, and tells PANELSPLIT's module map that the
    jailed transport seam has no PANEL owner. The same PR re-pins `roadmap_sha256` (that
    frontmatter line only) in every `plans/phase-plan-v11-*.md` whose pin matched the
    previous bytes. It lands only while no v11 plan is executing.
  - impl: After G2 (Execution Notes), land the W0 records PR, metadata only and validated
    by `V7`.
  - impl: After G3, land the OD-3b record PR. It adds a section citing W0's evidence digest
    and the chosen transport or "none admitted". Then land the switch PR, which edits only
    `JAILED_CLAUDE_DEFAULT` and `JAILED_DEFAULT_AUTHORITY` and carries SL-4's card
    statement. With "none admitted", there is no switch. `tui` stays the default, the row
    stays typed-degraded for the jailed seat, and SL-4 records that on the card.
  - verify: `V2`, `V7`, `V8`.

### SL-2 — Lane B: jailed print transport

- **Scope**: Mine agent-harness#1740's jailed `print` diff onto current main as `claude_seat_print`, then close agent-harness#1740 citing the landing PR.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_seat_print.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_print_observations.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/tests/test_seats_claude_print.py`, `phase-loop-runtime/tests/test_seats_claude_print_observations.py`, `phase-loop-runtime/tests/test_launcher_liveness.py`
- **Interfaces provided**: `claude_seat_print.run_jailed`
- **Interfaces consumed**: `IF-0-CLAUDE-1`
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_print.py` covers §4a items 4 and 5 as amended:
    - the argv is the jailed TUI command's with `-p`, stream-json, prompt on stdin and
      `--no-session-persistence`, and never `--bare`;
    - `apiKeySource` other than `"none"` refuses typed;
    - only one successful conforming `result` event admits a review;
    - no transcript, output file or assistant-turn salvage;
    - the token is scanned in everything the parent keeps.

    Path-entered controls inject a second result, a non-`none` key source or a salvaged
    turn, and each must not admit.
  - test: `test_seats_claude_print_observations.py`: observations are bounded and
    metadata-only, and never change admission.
  - impl: Mine the jailed `print` diff from agent-harness#1740's head. Do not start from
    its branch. Take `claude_print_observations.py` and the native-image resolver
    (agent-harness#1641's part) in `launcher.py`. Write the IF-0-CLAUDE-2 evidence keys. A
    needed `panel_invoker.py` change goes to SL-1 in this lane's landing PR; anything wider
    stops the lane.
  - impl: Give SL-4 this lane's inventory rows and docs text. Close agent-harness#1740
    after landing.
  - verify: `V3`.

### SL-3 — Lane C: jailed sdk transport and claude-sdk extra

- **Scope**: Salvage agent-harness#1744's adapter as the seat-neutral `claude_sdk_adapter`, plus its `claude-sdk` extra pin and Gate A clean-room install fix. Add `claude_seat_sdk` under IF-0-CLAUDE-3, then close agent-harness#1744.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_sdk_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_seat_sdk.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/local_check.py`, `.github/workflows/test.yml`, `ci/dagger/src/agent_harness_ci/main.py`, `phase-loop-runtime/tests/test_seats_claude_sdk.py`, `phase-loop-runtime/tests/test_seats_claude_sdk_adapter.py`, `phase-loop-runtime/tests/test_local_check.py`, `phase-loop-runtime/tests/test_ci_xdist_adoption.py`
- **Interfaces provided**: `claude_seat_sdk.run_jailed`, `IF-0-CLAUDE-3`
- **Interfaces consumed**: `IF-0-CLAUDE-1`
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_sdk.py`. The first test is the IF-0-CLAUDE-3 fail-loud probe:
    - a declared non-subject interpreter runs in a fixture jail with the base profile
      digest unchanged;
    - the closure stays within the ceilings;
    - an import outside the declared closure fails;
    - a token planted in options, argv, environment or seat home is refused;
    - missing init `apiKeySource == "none"` refuses;
    - the admission rules equal print's.

    Path-entered control: an ambient-host import path must make the test fail.
  - test: `test_seats_claude_sdk_adapter.py`: the salvaged adapter's credential-free tests,
    minus the solo-runner route, which re-files on agent-harness#1391.
  - impl: Salvage the adapter, the `claude-sdk` extra pin (`claude-agent-sdk`,
    `markdown-it-py`), the test-group and CI install lines, the Gate A fix and
    `uv lock`. A version change from the salvaged pins needs its own review.
  - impl: `claude_seat_sdk` builds the declared closure and runs the in-jail entry. It sets
    `ADMITTED = True` and `ACTIVATION` only in a landing whose base tree holds the G1
    section (EC-CLAUDE-4). Before G1 the module lands with `ADMITTED = False`.
  - impl: Give SL-4 this lane's inventory rows and docs text. Close agent-harness#1744
    after landing. Dispatch Gate A on the branch, since packaging and workflows change.
  - verify: `V4`.

### SL-4 — Docs and shared inventory reducer

- **Scope**: Single writer of every shared surface. Its tasks ride in each producer's landing PR, and a final sweep runs after the switch PR or the "none admitted" record.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `CHANGELOG.md`, `.doc-decisions.json`, `phase-loop-runtime/README.md`, `docs/TEAM-ONBOARDING.md`, `docs/executable-dependency-projection.md`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-skills/advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/**`, `phase-loop-runtime/tests/data/launchspec_golden/**`, `plans/manifest.json`
- **Interfaces provided**: none
- **Interfaces consumed**: `IF-0-CLAUDE-1`, `IF-0-CLAUDE-2`, `IF-0-CLAUDE-3`, `IF-0-CLAUDE-4`, `claude_seat_print.run_jailed`, `claude_seat_sdk.run_jailed`
- **Parallel-safe**: no
- **Tasks**:
  - test: Each landing PR passes `test_seat_reference_inventory.py` with only its own rows
    added, and passes the docs-freshness audit.
  - impl: Per landing:
    - add the inventory rows;
    - add a `[Unreleased]` CHANGELOG entry;
    - update the capabilities card and CONTRACTS.md. The selection stays experimental and
      unqualified until its row window (§4a item 6). `sdk` requires the extra and a
      dependency authority declaring IF-0-CLAUDE-3.
    - update the projection doc's supported routes for `sdk`.

    Change skill text only if a skill names jailed-seat routing. If one does, regenerate
    with `regenerate_skills_bundle.py` and the launchspec golden in the same PR.
  - impl: Switch PR: the EC-CLAUDE-6 card statement. With "none admitted", the card shows
    `tui` as the default and the jailed seat as typed-degraded. Manifest lifecycle
    transitions go through the manifest API.
  - verify: `V5`, `V6`.

## Execution Notes

**Gates and landing order.** The lane DAG orders development. Landings and three owner
gates order the rest.
1. SL-0, then SL-1's seam PR.
2. SL-1's amendment PR. The maintainer's merge is **G1** (OD-3a ratified). No W0 `sdk`
   run, `sdk` activation or default change comes before G1.
3. SL-1's v11 PR.
4. SL-2. Its landing activates jailed `print`, and EC-CLAUDE-4 does not cover it. It
   follows §4a item 9 of the record as it stands, an input rather than a future pin. Its
   landing message cites, by full SHA, the existing commit that landed §4a
   (agent-harness#1775), read with `git log` at landing time, and it lands non-fast-forward
   as item 9 requires.
5. SL-3, whose activating landing waits for G1 in its base.
6. **G2**: the owner runs W0 (LA-3). Its records land via SL-1.
7. **G3**: the owner answers OD-3b.
8. SL-1's OD-3b record PR.
9. SL-1's switch PR, carrying SL-4's card statement.

G2 and G3 are named live/owner gates. Nothing in this plan proxies them. W0 may share an
owner session with W1, and neither waits for the other.

**W0 run plan (EC-CLAUDE-5's count, fixed before the window).**
- Arms and count: three arms (`print`, `sdk`, `t3-sdk-control`), five runs each, 15
  records.
- Setting: one host and one operator account, the same review bundle, model and effort,
  and the W0 head recorded.
- Order: arms run in blocks (print, sdk, control).
- Meter readings: the owner reads the account usage meter before the first block and after
  each block, covering subscription usage and extra-usage/API spend. Each record cites its
  block's readings by reference. Billing landing is therefore resolved per block; an
  ambiguous block records `unknown`.
- Default ranking: a block that moved extra usage or API spend ranks its arm behind one
  that landed on subscription limits (roadmap scope note). OD-3b still decides.
- TUI: `tui` is not a W0 arm. It stays the last fallback, and its repair is CLAUDETUI's.

**Single writers.**
- SL-1 owns `panel_invoker.py` and both records.
- SL-4 owns the inventory and docs.
- Producer lanes hand their changes to these owners inside their own landing PRs.
- No lane edits `seat_jail.py` or a profile builder. New typed codes join the panel's
  existing typed-code lists, with fix lines.

**PANELSPLIT and v11.**
- The PANELSPLIT rule is the roadmap's: v11 PANELSPLIT may split `panel_invoker.py` at any
  time. CLAUDE rebases onto the split rather than block it. SL-1's ownership moves to the
  seat-launch module the PANELSPLIT module map names, and SL-4 regenerates the inventory
  rows under the new module paths.
- Between concurrent seat phases (FIRSTSEAT lane D also writes `panel_invoker.py`),
  whichever lands second rebases.
- EC-CLAUDE-8 is the only ownership transfer out of v11.

**Registration and re-pins.**
- The interim `superseded` registration is a known workaround until agent-harness#1824.
- Switching to `advisory` changes the roadmap's bytes, so re-pin this plan's
  `roadmap_sha256` in that commit.
- SL-1's v11 PR re-pins live v11 plans, as its task states.

**Load limits (owner instruction).** Every test command runs serially (`-n 0`, with
`pytest-xdist` added only so `-n` parses) under `timeout`. The full suite runs only in
hosted CI and Gate A, never locally on a shared host. Live W0 runs are owner actions.

**Issues.** SL-4's final sweep comments each issue the roadmap lists as absorbed with its
landing PR. Closure follows the INVENTORY issue index.

**Review.** Every PR goes through principle 2: the six required checks, dispatched Gate A
where packaging, workflows or tested docs change, and a cross-vendor board on the exact
head.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `plans/decision-claude-print-subscription-route-20261008.md`, `specs/phase-plans-v11.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/seat-qualification/claude-w0/`
- redaction posture: `metadata_only`
- downstream handling: `roadmap amendment` (the v11 EC-PANEL-6 consumption note, landed by SL-1); meter readings are owner-observed and cited by reference only

## Verification

`P` abbreviates the serial pytest prefix: `timeout 900 uv run --quiet --project
phase-loop-runtime --group test --extra visual --with pytest-xdist==3.8.0 --python 3.14
--locked python -m pytest -n 0 -p no:cacheprovider -q`. Every file below is prefixed by
`phase-loop-runtime/tests/`.

Zero-collection rule (agent-harness#1825): each new selector collected zero tests on the
planning tree, and each must collect more than zero after its lane lands.

- `V1`: `P test_seats_claude_login_proof.py test_seats_claude_bakeoff.py test_seat_credentials.py test_claude_seat_subscription_proof_1444.py test_seat_credential_refresh.py`
- `V2`: `P test_seats_claude_transport.py test_seats_claude_records.py test_claude_transport_seam.py test_panel_claude_print_route.py test_seat_login_wait_a3_1166.py test_seat_login_wait_board_context_r12.py test_seat_notices.py test_seat_session_label.py test_seat_sandbox_permissions.py`
- `V3`: `P test_seats_claude_print.py test_seats_claude_print_observations.py test_launcher_liveness.py test_seats_claude_transport.py`
- `V4`: `P test_seats_claude_sdk.py test_seats_claude_sdk_adapter.py test_local_check.py test_ci_xdist_adoption.py test_executable_dependency_startup.py test_seats_claude_transport.py`
- `V5`: `P test_seat_reference_inventory.py`, plus the docs-freshness audit in hosted CI
- `V6`: `automation.suite_command`; the full suite runs in hosted CI and dispatched Gate A
  only
- `V7`: `timeout 300 uv run --quiet --project phase-loop-runtime --python 3.14 --locked python -m phase_loop_runtime.claude_bakeoff validate plans/evidence/seat-qualification/claude-w0`
- `V8`: `phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-v11.md` and `phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`

## Acceptance Criteria

- [ ] EC-CLAUDE-1 — proven by `V2` (`test_seats_claude_transport.py`), falsified by a transport that changes the profile digest, environment, descriptors, tools or credential channel, or that falls back, passing the invariant test; path-entered control: stub transports that each add one environment variable, pass fd or tool must fail at the real `_parent_infer` jailed call site.
- [ ] EC-CLAUDE-2 — proven by `V3` (`test_seats_claude_print.py`) and agent-harness#1740 closed citing the landing PR, falsified by an admitted result that breaks an item 4 or item 5 rule; path-entered control: an injected second result, non-`none` key source or salvaged turn, entered through `claude_seat_print.run_jailed`, must not admit.
- [ ] EC-CLAUDE-3 — proven by `V4` (`test_seats_claude_sdk.py`) and agent-harness#1744 closed, falsified by an ambient-host dependency, an unprojected import or a token in the environment, SDK options or seat home passing; path-entered control: an ambient import path entered through `claude_seat_sdk.run_jailed` must fail.
- [ ] EC-CLAUDE-4 — proven by `V2` (`test_seats_claude_records.py`) on each activating and switch landing's base tree, falsified by a citation whose section digest is absent from the base tree passing, or by a landing that edits the record and the setting together; path-entered control: a disposable tree with the cited section removed must fail the same test.
- [ ] EC-CLAUDE-5 — proven by `V7` over the W0 records (G2), falsified by a record without its entrypoint, meter reference or item 7 outcome validating; path-entered control: a disposable copy of one record with `claude_code_entrypoint` deleted must fail `V7`.
- [ ] EC-CLAUDE-6 — proven by `V2` (`test_seats_claude_records.py`) after G3, falsified by `JAILED_CLAUDE_DEFAULT` disagreeing with the OD-3b record or the card statement; path-entered control: a disposable record naming another transport must fail the same test.
- [ ] EC-CLAUDE-7 — proven by `V1` and `V2` (`test_seats_claude_login_proof.py`, `test_seats_claude_transport.py`), falsified by a jailed transport launching without the login proof, or a timed-out wait leaving the awaiting row; path-entered control: an auth probe stub that fails must stop the launch at the real call site.
- [ ] EC-CLAUDE-8 — proven by `V2` (`test_seats_claude_records.py`) and `V8`, falsified by a responsibility with two owners or none passing; path-entered control: a disposable amendment copy listing one responsibility under two owners must fail.

The phase exits only with all eight referenced criteria, after G2 and G3. Planning
produces no implemented IF gate.
