---
phase_loop_plan_version: 1
phase: CLAUDE
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9dc889c61a8d682dde30af65bf1597c1dca9a0df094fac747194d3629939b16e
automation:
  suite_command: ["timeout", "1800", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--extra", "visual", "--extra", "claude-sdk", "--with", "pytest-xdist==3.8.0", "--python", "3.14", "--locked", "python", "-m", "pytest", "-n", "0", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seats_claude_login_proof.py", "phase-loop-runtime/tests/test_seats_claude_bakeoff.py", "phase-loop-runtime/tests/test_seats_claude_transport.py", "phase-loop-runtime/tests/test_seats_claude_order.py", "phase-loop-runtime/tests/test_seats_claude_records.py", "phase-loop-runtime/tests/test_seats_claude_print.py", "phase-loop-runtime/tests/test_seats_claude_print_observations.py", "phase-loop-runtime/tests/test_claude_transport_seam.py", "phase-loop-runtime/tests/test_panel_claude_print_route.py", "phase-loop-runtime/tests/test_seats_claude_sdk.py", "phase-loop-runtime/tests/test_seats_claude_sdk_adapter.py", "phase-loop-runtime/tests/test_seat_credentials.py", "phase-loop-runtime/tests/test_seat_login_wait_a3_1166.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_executable_dependency_startup.py"]
---

# CLAUDE: Claude Seat Transports and Bake-off

## Context

This plan covers roadmap Phase 1 (CLAUDE) of `specs/phase-plans-seats-v1.md`, a root phase.
Exit criteria are EC-CLAUDE-1 to EC-CLAUDE-8, cited by ID only. The roadmap is advisory
(OD-1) and the runner refuses it, so lanes land as governed PRs under principle 2. The file
name follows the manifest pattern (root maintainer's decision).

Inputs are the roadmap's External Inputs, plus one pin from the print-route record: §4a, merged by agent-harness#1775, has section sha256
`7af0fb700ef10d444a904b01169c8b08aa056ba25ca496c7adcca7c646852cdb`. A section's bytes run
from its `## ` heading line to the line before the next `## ` heading.

Worker contract: `plans/seats-claude-sdk-worker-contract.md`, sha256
`204d4ab83c7c1b9c0328a99e6934ee121d6e8269307d4547c1f6d5949481599d` (EC-CLAUDE-3).

Amendment 2026-11-05: owner option A selects EC-CLAUDE-3. SL-3 remains pending.
The regression command targets the implementation checkout, not this plan-only tree.
This amendment authorizes planning only.

Amendment 2026-11-06 (SL-3 landing): `suite_command` regains both SDK operands and
`--extra claude-sdk`. `sdk` stays unadmitted; GL-2 still needs every gate below.

Owner decisions obeyed: the print-vs-SDK bake-off with T3 Code's SDK route as the control;
OD-3a in its own reviewed PR before any `sdk` activation, W0 `sdk` run or default change;
the owner picks the default (OD-3b); TUI last; open egress as a named exception until
CLAUDENET exits. No jail profile digest changes, and no lane edits `seat_jail.py`, a profile
builder or an egress allowlist.

## Interface Freeze Gates

- [ ] IF-0-CLAUDE-1 — The roadmap gate, frozen in the new `phase_loop_runtime/claude_seat_transport.py`.
  - **Selector types.** `ClaudeTransport = Literal["tui", "print", "sdk"]`.
    `RecordCitation(record, section, section_sha256, pr)`.
  - **Section per purpose.** `SECTION_FOR` maps `print` to §4a, `sdk` to the OD-3a amendment
    (heading `## 4b. OD-3a`), and `default` to an OD-3b section (initially `## 4c. OD-3b`;
    use the next free letter if occupied, and every OD-3b heading carries `OD-3b`).
    A superseding OD-3a section becomes `SECTION_FOR["sdk"]`; superseded citations refuse.
    Sections are append-only.
  - **Default.** `JAILED_CLAUDE_DEFAULT = "tui"` (§4a item 2), with
    `JAILED_DEFAULT_AUTHORITY: RecordCitation | None`. The default is `tui` (which may cite an
    OD-3b section), or the latest OD-3b value with an authority citing it. A recorded but
    unshipped OD-3b value is legal.
  - **Resolution.** `resolve_jailed_claude_transport(env) -> tuple[ClaudeTransport | None, str | None]`
    reads `PHASE_LOOP_PANEL_CLAUDE_ROUTE`: unset or blank gives the default, an unknown value
    refuses `panel_claude_route_invalid`, and a known but unadmitted value refuses
    `panel_claude_transport_not_admitted`.
  - **Admission.** `tui` is always admitted. `print` or `sdk` is admitted only when its module
    (`claude_seat_print`, `claude_seat_sdk`) imports and exports `ADMITTED = True`,
    `ACTIVATION: RecordCitation` and `run_jailed(seat, **kwargs) -> tuple[str, str]`.
    `run_jailed` takes the keywords of `_exec_jailed_claude_leg`. SDK imports occur only
    in the verified host worker under IF-0-CLAUDE-3; the board parent never imports it.
  - **Jail/CLI boundary.** EC-CLAUDE-1 and EC-CLAUDE-3 govern the owned launch.
    `SDK_CLI_DELTA` is the complete versioned fixture at
    `phase-loop-runtime/tests/data/seats_claude_sdk/launch-v1.json`, with its sha256
    recorded in the proof receipt; runtime uses its identical packaged copy. No SDK projection or stock spawn.
  - **`CODES`.** The typed codes these transports add, each with an OD-10 class and a fix
    line. Security: `claude_seat_token_in_output`, `claude_seat_api_key_source`,
    `claude_sdk_provenance_refused`, `claude_sdk_worker_contract_violation`. Ordinary: `claude_seat_login_unproven`,
    `claude_seat_result_unproven`, `claude_seat_stream_unsafe`,
    `claude_sdk_dependency_unavailable`, `claude_sdk_worker_unavailable`. None descends, and no fix line names an API key.
    Classes and fix lines follow EC-CLAUDE-3's contract.
    The mode line accepts `seat_jail.NOTICE_CODES | CODES`; the table is JAILCORE's input
    for EC-JAILCORE-2's falsifier.
  - **No fall-through.** A refusal or post-launch terminal code launches no other transport.
    "TUI last" is operator selection only.
  - **Order audit.** `audit_order(base, head, pr) -> tuple[str, ...]` and its CLI
    (`python -m phase_loop_runtime.claude_seat_transport audit-order`) check every admission
    citation and the default. They fail when:
    - the base is missing or isn't the event's base;
    - the cited section is absent from the base tree, differs in digest, or isn't the
      purpose's own (`SECTION_FOR`);
    - a landing that changes an admission or the default also edits the decision record;
    - the cited PR is unmerged, or is the PR under check (read-only GitHub API);
    - the default breaks the rule above.
    Enforce EC-CLAUDE-3 receipt/fact rules continuously using the base-tree auditor.
  - **Late binding.** Modules use the `panel_invoker` facade. SL-1 alone may extend its
    owned I/O helper for duplex SDK traffic, preserving launch, liveness and teardown;
    EC-CLAUDE-5 names the capture exception. SL-3 supplies worker requirements to SL-1.
- [ ] IF-0-CLAUDE-2 — The roadmap's record, as a closed schema in the new `phase_loop_runtime/claude_bakeoff.py`.
  - **Record and digest.** `BakeoffRecord`, canonical JSON `claude-bakeoff-record.v1`, one
    file per run at `plans/evidence/seat-qualification/claude-w0/<run_id>.json`;
    `validate_record(obj)`; `evidence_digest(directory)`, the sha256 over sorted record
    bytes, which OD-3b cites.
  - **Required fields, no others:** `run_id` (generated, `w0-b<block>-r<n>`), `arm`
    (`print | sdk | t3-sdk-control`), `block`, `w0_head` (40-hex), `cli_version`,
    `canonical_output` (`admitted | absent | refused | timed_out`), `code` (typed or
    `none`), `admission` and `item7` (predicate → `pass | fail | not_applicable |
    self_reported`), `billing` (`subscription | extra_usage | api | unknown`), `meter_ref`
    (`w0-block-<n>`), `meter_digest` (salted sha256 of the private readings),
    `claude_code_entrypoint` and `claude_api_key_source` (short slugs), `request_set`
    (`completeness: complete | partial`, `capture_digest`, entries of `method`, `host`,
    `path_template`), `jail_profile_digest`, `dependency_projection_digest`
    (`not_applicable` without a subject projection, otherwise its actual digest),
    `sdk_location` (`host_worker | t3_control | not_applicable`), `sdk_version` (semantic version or
    `not_applicable | self_reported`), `sdk_package_digest`, `sdk_delta_digest`, `sdk_boundary_proof_digest` (sha256 or
    `not_applicable`; control may use `self_reported`), `activation_section_sha256`, `co_seats_unconfined` (vendor
    slugs) and `security_outcome` (`none | withheld_private`).
  - **Closed schema.** An unknown field refuses; every string is a vocabulary value or
    matches a strict pattern; diagnostics never pass through. Before writing, the kit runs
    `contains_secret` with the live credential and writes nothing on a hit.
  - **`validate`** refuses:
    - credential shapes, UUIDs, emails, home paths, IP literals and private-namespace host
      names (single-label, `.local`, `.internal`, `.lan`, `.ts.net`);
    - a path segment that carries an identifier without templating (`{id}`);
    - a block that mixes arms, or a `meter_ref` shared across blocks;
    - a native record whose `jail_profile_digest` isn't the TUI's at its `w0_head`;
    - an `sdk` record whose `w0_head` record lacks the current OD-3a section named by
      `activation_section_sha256`, or missing host SDK provenance/proof/delta metadata;
    - once an OD-3b section exists, one that doesn't cite this directory's
      `evidence_digest`.
  - **Control arm.** `t3-sdk-control` may mark `not_applicable` only the jail, staged-clone,
    token-pipe and seat-diagnostics predicates. The kit parses its entrypoint, key source,
    model, canonical output and verdict from the child's output file, marked
    `self_reported` where it can't observe them.
  - **Private data.** Raw captures and meter readings live only in per-operator private
    storage (mode 0600); raw captures are deleted after templating.
- [ ] IF-0-CLAUDE-3 — EC-CLAUDE-3 governs the dedicated host worker, install/provenance,
  parent IPC gates, launcher, fixture and receipt verifier; EC-CLAUDE-5 governs its twin.
  - **Preflight.** `claude_seat_sdk.preflight()` verifies worker readiness and provenance
    before the leg's credential resolver. Require subject sessions only where applicable.
  - **Interfaces.** `claude_sdk_adapter` runs only in the worker; `claude_seat_sdk.run_jailed`
    owns parent admission. SL-1 owns worker launch and jailed duplex I/O in the leg context.
    `build_sdk_cli_argv` supplies actual CLI flags; SDK `cli_path` is inert here.
  - **Freeze/proof.** SL-3 captures `SDK_CLI_DELTA` before G1 and owns
    `plans/evidence/seat-qualification/claude-sdk-boundary/receipt-v1.json`.
    VB/VL and the base-tree verifier implement EC-CLAUDE-3. Failed proof or unresolved
    memory control stops GL-2. The twin is the sole CLI launch exception, admission-checked
    under EC-CLAUDE-5; pre-activation exercise uses only offline synthetic fixtures.
- [ ] IF-0-CLAUDE-4 — A plan-local gate: the jailed login proof.
  - **Proof.** `seat_credentials.jailed_login_proof(credential, auth_probe, caller_env) -> LoginProof`
    applies the three checks the print and TUI routes hold (agent-harness#1532):
    caller-credential rejection (`_claude_caller_supplied_credential`, any `ANTHROPIC_*`
    included), the subscription check on the same login context, and a single-use
    auth-status probe on that exact credential.
  - **Closed type.** `LoginProof` has no identity field; probe output is reduced to
    `authMethod` and `apiKeySource` before anything is kept.
  - **Republish.** `seat_preflight.republish_seat_mode(stream_dir, mode) -> Path` replaces one
    seat's row in `seat-modes.json` (agent-harness#1255).

## Lane Index & Dependencies

SL-0 — Login proof (lane D, part 1)
  Depends on: (none)
  Blocks: SL-1, SL-6
  Parallel-safe: yes

SL-1 — Jailed seam, resolver and order audit (lane A, code)
  Depends on: SL-0
  Blocks: SL-2, SL-3, SL-4, SL-6
  Parallel-safe: no

SL-2 — Jailed print transport (lane B)
  Depends on: SL-1
  Blocks: SL-3, SL-6
  Parallel-safe: yes

SL-3 — Host SDK, owned jailed transport and extra (lane C)
  Depends on: SL-1, SL-2
  Blocks: SL-4, SL-6
  Parallel-safe: yes

SL-4 — Bake-off recorder and W0 kit (lane D, part 2)
  Depends on: SL-1, SL-3
  Blocks: SL-6
  Parallel-safe: yes

SL-5 — Decision records and v11 note (lane A, records)
  Depends on: (none)
  Blocks: SL-6
  Parallel-safe: yes

SL-6 — Docs and shared inventory reducer
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Login proof (lane D, part 1)

- **Scope**: Deliver IF-0-CLAUDE-4 and EC-CLAUDE-7's helpers without touching `panel_invoker.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `phase-loop-runtime/tests/test_seats_claude_login_proof.py`, `phase-loop-runtime/tests/test_seat_credentials.py`, `phase-loop-runtime/tests/test_claude_seat_subscription_proof_1444.py`, `phase-loop-runtime/tests/test_seat_credential_refresh.py`
- **Interfaces provided**: `IF-0-CLAUDE-4`
- **Interfaces consumed**: none
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_login_proof.py`:
    - Refused typed: a store pass with a failed probe; a probe on another credential; any
      `ANTHROPIC_*` variable in the caller's environment; probe output whose `authMethod`
      isn't `oauth_token` or that carries any `apiKeySource`.
    - A token or email in probe output never reaches `LoginProof` or evidence, and the
      override credential keeps its account binding.
    - A timed-out wait republishes a `degraded` row whose code and fix line match the
      existing `claude_seat_login_token_expiring` and `claude_seat_token_missing` text.
  - impl: Write `jailed_login_proof` against main, reading agent-harness#1740's
    login-context change only as a reference. Add `republish_seat_mode`.
  - impl: Give SL-6 this lane's inventory rows for its landing PR.
  - verify: `V1`.

### SL-1 — Jailed seam, resolver and order audit (lane A, code)

- **Scope**: Make the jailed seat read IF-0-CLAUDE-1 with `print` and `sdk` refused, wire IF-0-CLAUDE-4 into the jailed launch, land agent-harness#1641's resolver fix, and run the order audit in CI.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `.github/workflows/test.yml`, `.github/workflows/claude-sdk-audit.yml`, `phase-loop-runtime/tests/test_seats_claude_transport.py`, `phase-loop-runtime/tests/test_seats_claude_order.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_claude_transport_seam.py`, `phase-loop-runtime/tests/test_panel_claude_print_route.py`, `phase-loop-runtime/tests/test_seat_login_wait_a3_1166.py`, `phase-loop-runtime/tests/test_seat_login_wait_board_context_r12.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_seat_session_label.py`, `phase-loop-runtime/tests/test_seat_sandbox_permissions.py`
- **Interfaces provided**: `IF-0-CLAUDE-1`
- **Interfaces consumed**: `IF-0-CLAUDE-4`
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_seats_claude_transport.py`:
    - Resolution and refusal cover every value; a refused value launches nothing. For each
      terminal code in `CODES`, a control at the real `_parent_infer` jailed call site
      launches no other transport, the TUI included.
    - The invariant test runs `tui`, and every module that exports `ADMITTED`, at the real
      call site in a real jail, with a fake subject at `/seat/bin/claude` recording argv,
      environment and descriptors. Stubs are only failing controls: each adds one
      environment variable, pass fd, tool, undeclared mount or provider-visible descriptor,
      or changes the digest, and must fail.
    - Live-jail tests skip only when `PHASE_LOOP_REQUIRE_LIVE_JAIL=1` is unset; with it set, a
      skip fails.
    - The login proof and republish run on every jailed transport, and `claude_transport`
      reaches `broker_evidence`. Every `CODES` entry reaches the mode line with its OD-10
      class, and no fix line names an API key.
  - test: `test_seats_claude_order.py`. Controls entered through `audit-order` on disposable
    trees, each of which must fail: an unset or untrusted base; a cited section only on the
    head; a real section of another purpose; an unmerged cited PR; one PR carrying record and
    switch; a landing that edits the record; a default that breaks the rule; a card whose
    default statement omits the default, open egress or the row window. A recorded but
    unshipped OD-3b value must pass. SDK activation with a missing, failed or stale `VB`
    receipt must fail; the positive control binds current inputs. Cover EC-CLAUDE-3
    post-activation drift, base-auditor and declarative-facts controls.
  - impl: Resolver PR, first and on its own: agent-harness#1641's
    `_resolve_claude_executable` change rebased onto main, so the TUI and `print` both jail
    the native image. Its inventory row goes to SL-6.
  - impl: Seam PR. Add `claude_seat_transport.py`. At the jailed call site in `_parent_infer`,
    in `_prepare_jailed_claude` and in the login-wait branch, resolve the transport before
    preparing the jail, dispatch through it and wire IF-0-CLAUDE-4. `print` and `sdk` stay
    refused until their modules land. The PR carries the existing tests' expectation updates
    for the jailed seat reading the selector (§4a item 3) and never weakens an assertion.
  - impl: Deliver EC-CLAUDE-3's base-defined required audit workflow, proof checker and
    declarative-fact enforcement before GL-2. Head trees are data; missing base/evidence
    fails. Owner-enforced workflow policy is a GL-2 prerequisite.
  - impl: Implement the sandboxed worker launcher through existing `seat_uid`/seat-owner
    primitives; test isolation, parent death and cleanup under EC-CLAUDE-3.
  - impl: Extend the owned I/O helper for IF-0-CLAUDE-3; test duplex exchange and
    cancellation at the real call site in `test_seats_claude_transport.py`. Keep launch
    ownership and print/TUI behavior. Replace `_prepare_jailed_claude`'s unconditional SDK
    session refusal with worker preflight before credential resolution; retain genuine
    subject-session enforcement. Spy-test resolver ordering and integrate SL-3 metadata.
  - verify: `V2`.

### SL-2 — Jailed print transport (lane B)

- **Scope**: Write `claude_seat_print` against current main from §4a items 4 and 5, then close agent-harness#1740 citing the landing PR. This landing makes `PHASE_LOOP_PANEL_CLAUDE_ROUTE=print` usable at once.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_seat_print.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_print_observations.py`, `phase-loop-runtime/tests/test_seats_claude_print.py`, `phase-loop-runtime/tests/test_seats_claude_print_observations.py`
- **Interfaces provided**: `claude_seat_print.run_jailed`, parsed `StreamAdmission`
- **Interfaces consumed**: `IF-0-CLAUDE-1`
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_print.py` covers §4a items 4 and 5:
    - The argv is the jailed TUI command's plus `-p`, stream-json, the prompt on stdin and
      `--no-session-persistence`, never `--bare`.
    - An `apiKeySource` other than `"none"` refuses `claude_seat_api_key_source`. Only one
      successful conforming `result` admits; nothing is salvaged. The token is scanned in
      everything the parent keeps.
    - A stream past the byte cap, invalid UTF-8, a duplicate key or nesting past a bound in
      any `system` or `result` frame, or a `RecursionError`, refuses
      `claude_seat_stream_unsafe`.

    Path-entered controls through `claude_seat_print.run_jailed`, none of which may admit: a
    second result, a key source other than `none`, a salvaged turn and each hardening case.
  - test: `test_seats_claude_print_observations.py`: observations are bounded and
    metadata-only, and never change admission.
  - impl: Write `claude_seat_print.py` from §4a. Read agent-harness#1740 for reference only
    and apply none of its `panel_invoker.py` hunks; copy `claude_print_observations.py` only
    where it still fits main. Write the IF-0-CLAUDE-2 evidence keys (`claude_transport`,
    `claude_code_entrypoint` observed at the CLI process boundary, `claude_api_key_source`,
    `claude_admission`, the item 7 diagnostics, `jail_profile_digest`). Export
    `ADMITTED = True` with `ACTIVATION` citing §4a (the Context pin and agent-harness#1775).
    A needed `panel_invoker.py` change goes to SL-1 in this landing PR, limited to the seam
    call site; anything wider stops the lane.
  - impl: Refactor parsed `StreamAdmission` for SL-3 with route-specific policy; retain
    print semantics/authority and verify V3. This is not print re-activation.
  - impl: Give SL-6 the inventory rows and docs text. Close agent-harness#1740 after landing.
  - verify: `V3`, `VL`.

### SL-3 — Host SDK, owned jailed transport and extra (lane C)

- **Scope**: Write the seat-neutral `claude_sdk_adapter`, the `claude-sdk` extra and the Gate A clean-room fix, and `claude_seat_sdk` under IF-0-CLAUDE-3, which lands with `ADMITTED = False`. Then close agent-harness#1744.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_seat_sdk.py`, `phase-loop-runtime/src/phase_loop_runtime/data/claude_sdk/**`, `plans/evidence/seat-qualification/claude-sdk-boundary/**`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/local_check.py`, `ci/dagger/src/agent_harness_ci/main.py`, `phase-loop-runtime/tests/test_seats_claude_sdk.py`, `phase-loop-runtime/tests/test_seats_claude_sdk_adapter.py`, `phase-loop-runtime/tests/test_local_check.py`, `phase-loop-runtime/tests/test_ci_xdist_adoption.py`, `phase-loop-runtime/tests/data/seats_claude_sdk/**`, `plans/phase-plan-v1-seats-CLAUDE.md`, `plans/seats-claude-sdk-worker-contract.md`
- **Interfaces provided**: `claude_seat_sdk.run_jailed`, `IF-0-CLAUDE-3`
- **Interfaces consumed**: `IF-0-CLAUDE-1`, parsed `StreamAdmission`
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_sdk.py` implements EC-CLAUDE-3's generic falsifiers and
    EC-CLAUDE-5's twin controls through `_parent_infer`; private suites are separately bound.
    Disposable guard mutations must fail their controls.
  - test: `test_seats_claude_sdk_adapter.py` covers the contract's transport, lifecycle,
    configuration and forbidden-call controls, including no solo route or stock transport.
  - impl: Salvage agent-harness#1744's adapter, pins and Gate A fix. Supply the contract's
    packaged worker payload, install resources and proof producer. V4/VB/VL use the
    documented worker install. No `launcher.py` change; SL-1 owns launch/audit wiring.
  - impl: Land with `ADMITTED = False`; capture the fixture before G1. Coordinate SL-4's
    twin and produce VB/VL receipt metadata with private junit. Restore both SDK test
    operands and `--extra claude-sdk` to `suite_command` before GL-2; require nonzero
    collection per SDK file, without skips. The implemented-lanes command stays unchanged
    until the extra and tests land.
  - impl: Give SL-6 inventory/install docs; close agent-harness#1744 after disposition.
    Dispatch Gate A for packaging/workflow changes.
  - verify: `V4`, `VB`, `VL`. Activation is only GL-2.

### SL-4 — Bake-off recorder and W0 kit (lane D, part 2)

- **Scope**: Deliver IF-0-CLAUDE-2's recorder and validator and the W0 kit (`python -m phase_loop_runtime.claude_bakeoff`), without touching `panel_invoker.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_bakeoff.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_bakeoff_recorder.mjs`, `phase-loop-runtime/tests/test_seats_claude_bakeoff.py`, `plans/evidence/seat-qualification/claude-w0/**`
- **Interfaces provided**: `IF-0-CLAUDE-2`
- **Interfaces consumed**: `IF-0-CLAUDE-1`, `IF-0-CLAUDE-3`
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_bakeoff.py`, entered through `validate` or the kit. Each must
    fail:
    - a missing field, an unknown field or an out-of-vocabulary value;
    - a disposable record with a planted credential shape, UUID, email, home path, IP
      literal, private host or untemplated identifier path;
    - a `contains_secret` hit on the test credential, which blocks the write;
    - recorder output holding a planted header or body token or an untemplated path; a twin
      environment beyond the declared delta or a bundle head off `main`; a `complete` set
      with an unparsed connection; an SDK twin using print, missing control traffic or
      mismatching the SDK fixture; incorrect SDK provenance or invented projection digest;
    - a block mixing arms, shared meter refs, an `sdk` record whose head lacks the current OD-3a section, or a
      control record marking a non-permitted check `not_applicable`.

    Exercise EC-CLAUDE-5 preflight before meters/credentials/twins and repeat it at twin
    entry; unadmitted or stale SDK inputs launch nothing.
    The kit stops an arm on a security-class code and writes only `withheld_private`. Before
    any run, it refuses a run plan that differs from Execution Notes, or a board whose
    president or co-seat uses the W0 Claude account. A run past its timeout records
    `timed_out`. The evidence digest is order-independent.
  - impl: Write `claude_bakeoff.py`: record, validator and digest; the arm runner (the native
    board seat path through `phase-loop advisor-board`, selector set per arm); per-block
    meter prompts with private storage; the control-block brief and ingest; the composition
    preflight.
  - impl: Capture twin, principle 5's developer-host measurement. Once per native block,
    inside its meter bracket, the kit runs that block's transport outside the seat with its
    jailed argv, environment and token pipe, on a disposable copy of the W0 bundle, whose
    head must be on `main`. The only delta is path remaps, a fresh empty home (no host
    settings, hooks, MCP servers or plugins load), a proxy variable and a CA variable. The
    recorder (`claude_bakeoff_recorder.mjs`) runs on the verified srt install, with
    `seat_egress_proxy` unedited and a per-window private CA trusted only through that
    variable. It keeps method, host and templated path, never headers or bodies. The twin's
    output is discarded, never a record; SDK output first passes EC-CLAUDE-5 admission.
    `complete` means every connection the recorder saw was terminated and parsed; CLAUDENET consumes only complete sets.
  - impl: Add the SDK-specific capture twin and EC-CLAUDE-5 metadata, coordinated with
    SL-3 before GL-2 using synthetic fixtures only. Record actual entrypoint (`unset` allowed),
    SDK location/version and measured differences from T3; never assert parity by label. Give SL-6 inventory rows.
  - verify: `V5`.

### SL-5 — Decision records and v11 note (lane A, records)

- **Scope**: Draft and land the OD-3a amendment (G1), then the v11 consumption note. Records only.
- **Owned files**: `plans/decision-claude-print-subscription-route-20261008.md`, `specs/phase-plans-v11.md`, `plans/phase-plan-v11-*.md`, `phase-loop-runtime/tests/test_seats_claude_records.py`
- **Interfaces provided**: none
- **Interfaces consumed**: none
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_seats_claude_records.py`: the current OD-3a section gives each EC-CLAUDE-8 responsibility exactly
    one owner, and each Stage 3 §3 condition one row (applies, replaced by a named jail
    control, or waived with a reason). Earlier sections are never edited. Once the v11 note
    has landed, `specs/phase-plans-v11.md` carries it. Path-entered controls through the records test's parser on disposable copies, each of
    which must fail: a responsibility under two owners, a missing condition row, an edited
    earlier section.
  - impl: Amendment PR (`## 4b. OD-3a …`), records only, in its own reviewed PR, drafted on
    day one. It covers:
    - everything OD-3a lists, and the EC-CLAUDE-8 table (PANELSPLIT's mechanical extraction
      stays in v11);
    - EC-REVIEWTRUTH-18 amended for the jailed seat's `sdk` route, lifting Stage 3 §4's
      review exclusion for that route only;
    - EC-CLAUDE-3's dedicated host-worker refinement and contract digest, fixture sha256, memory-control
      disposition and proof gate; revise an unratified draft or append a superseding
      section and update `SECTION_FOR`. G1 follows fixture capture;
    - EC-CLAUDE-4's content order in place of §4a item 9 for every jailed-transport landing;
    - TUI last as operator selection only;
    - the open-egress exception, for the jailed Claude seat only, until CLAUDENET exits, with
      its expiry date set at GL-6 (OQ-8); the worker remains networkless;
    - the condition table. Proposed rows: 1, 4 and 7 apply. 2 applies through IF-0-CLAUDE-4,
      with personal Pro/Max scoping for `sdk` put to the owner. 3 is replaced by the jail's
      cleared environment and actual empty-settings/strict-empty-MCP argv flags, plus the
      EC-CLAUDE-3 memory-control disposition. 5 is replaced by parity with the jailed TUI command, importing
      neither the runner-CLI oracle nor the `allowed_tools` rule. 6 is replaced by the
      jailed seat's own lease, teardown and stall detection.

    The maintainer's merge ratifies it (G1).
  - impl: v11 note, after G1, records only. It marks the affected EC-PANEL-6 items as
    consumed by the amendment's EC IDs, notes the departure from EC-REVIEWTRUTH-15, and tells
    PANELSPLIT's module map that the jailed transport seam has no PANEL owner. It rides the
    next v11-owned roadmap amendment if v11's owner takes it; otherwise it is its own PR,
    merged when a fresh status check shows no executing v11 phase. That PR re-pins
    `roadmap_sha256` (that line only) in every v11 plan whose pin matched the previous
    bytes, and an executing v11 lane rebases before its next plan-file commit. No CLAUDE
    landing waits on the note; only EC-CLAUDE-8 does.
  - verify: `V6`, `V10`.

### SL-6 — Docs and shared inventory reducer

- **Scope**: Single writer of every shared surface. Its tasks ride in each producer's landing PR, and a final sweep runs after GL-6 or the "none admitted" record.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `CHANGELOG.md`, `.doc-decisions.json`, `phase-loop-runtime/README.md`, `docs/TEAM-ONBOARDING.md`, `docs/executable-dependency-projection.md`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-skills/advisor-board/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/**`, `phase-loop-runtime/tests/data/launchspec_golden/**`, `plans/manifest.json`
- **Interfaces provided**: none
- **Interfaces consumed**: `IF-0-CLAUDE-1`, `IF-0-CLAUDE-2`, `IF-0-CLAUDE-3`, `IF-0-CLAUDE-4`, `claude_seat_print.run_jailed`, `claude_seat_sdk.run_jailed`
- **Parallel-safe**: no
- **Tasks**:
  - test: Each landing PR passes `test_seat_reference_inventory.py` with only its own rows
    added, and passes the docs-freshness audit.
  - impl: Per landing: the inventory rows and an `[Unreleased]` CHANGELOG entry; the card and
    CONTRACTS.md, which from the first `print` landing call the selection experimental,
    unqualified until its row window (§4a item 6) and on open egress; for `sdk`, the extra
    and documented hashed worker install (IF-0-CLAUDE-3), plus genuine Claude-subject
    dependency requirements in the projection doc. Skill text changes only if a skill names jailed-seat routing, regenerated with
    `regenerate_skills_bundle.py` and the launchspec golden in the same PR.
  - impl: GL-6: the EC-CLAUDE-6 card statement, and the exception's expiry handed to
    FIRSTSEAT's matrix. With "none admitted", the card shows `tui` as the default and the row
    as typed-degraded, as OQ-7 settles. Manifest lifecycle transitions go through the
    manifest API.
  - verify: `V8`, `V9`.

## Execution Notes

**Shortest path to `print`.** SL-0, SL-1's resolver PR, SL-1's seam PR, then SL-2. Merging
SL-2 makes `PHASE_LOOP_PANEL_CLAUDE_ROUTE=print` usable on the jailed seat at once
(experimental, unqualified, open egress); the default stays `tui`. The `print` landing is
ordered by content: `audit-order` finds §4a's digest on the base tree and
agent-harness#1775 merged. It needs no merge mode, landing-time lookup or SHA in its
message (OQ-6). SL-3 and SL-5 develop alongside; SL-4 follows SL-3. None blocks print.

**Gated landings.** Each is made by its single writer. G1 follows SL-3 fixture capture;
activation and live SDK twins wait for GL-2.
- **GL-1 (G1).** The maintainer merges SL-5's amendment PR: OD-3a ratified.
- **GL-2.** SL-3 sets `ADMITTED = True`, citing the current OD-3a section, in a record-free
  PR. EC-CLAUDE-3's base workflow policy and proof/fact enforcement must already hold. VB/VL run on
  the final executable tree including activation, then commit receipt/package metadata. Require
  the SDK-inclusive suite and SL-4 twin proof. Missing/stale proof keeps SDK refused.
- **GL-3 (G2).** The owner runs W0 (LA-3). SL-4's owner lands the records in a reviewed PR,
  validated by `V7`.
- **GL-4 (G3).** The owner answers OD-3b.
- **GL-5.** SL-5's owner lands the OD-3b section, records only, citing W0's evidence digest
  and the chosen transport or "none admitted".
- **GL-6.** After GL-5 merges, SL-1's owner lands the switch PR. It edits only
  `JAILED_CLAUDE_DEFAULT` and `JAILED_DEFAULT_AUTHORITY` and carries SL-6's card statement.
  With "none admitted" there is no switch.

Before asking for any gated merge, the landing agent re-runs `audit-order` against `main`'s
tip, because `base.sha` can lag it.

**W0 run plan.** EC-CLAUDE-5's count, fixed before the window. The defaults stand unless the
owner answers OQ-1 to OQ-5 otherwise before this plan merges.
- **Setting.** One host and one operator account; the same review bundle, model and effort;
  the W0 head recorded.
- **Blocks.** Six single-arm blocks: print, control, sdk, sdk, control, print. The second
  half reverses the first. Three runs per block, 18 records (OQ-1). The first print and
  control blocks may run once SL-2 lands; sdk blocks need GL-2.
- **Meter.** The kit prompts the owner to read the account usage meter before the first
  block and after each block, after a settle interval: seven readings (OQ-2). Each covers
  subscription usage and extra-usage spend, plus API spend if the account has an API
  organization. Records cite their block's `meter_ref`. A block that moves extra usage or
  API spend sets `billing` for all its records; an ambiguous block records `unknown`.
- **Isolation.** Inside a block, no other Claude work runs on the W0 account: no W1 Claude
  seat, no other session, and no Claude president or co-seat on a W0 board. W0 may share
  an owner session with W1 outside the blocks.
- **Timeout.** 30 minutes per run (OQ-3); `timed_out` counts as no canonical output.
- **Request sets.** One capture twin per native block (OQ-5), inside its bracket.
- **Control.** Three T3 Code SDK-route runs per control block. The kit prints one brief;
  the owner pastes it into a T3 Code thread whose own model isn't on the W0 account, which
  delegates each run to a W0-account Claude child at the run's model and effort. Each child writes a
  structured output file that the kit ingests.
- **Security outcome.** It stops the arm; its records carry `withheld_private`, and the
  owner gets the detail privately (OD-10).
- **Ranking.** A transport whose blocks land on extra usage or API billing ranks behind one
  on subscription limits; OD-3b still decides. `tui` is not an arm (CLAUDETUI).

**W0 owner actions.**
1. Answer OQ-1 to OQ-5, or accept the defaults. Pick the W0 host and account, with LA-1 and
   LA-2 done there.
2. Pause all other Claude use on that account for each block, then run
   `python -m phase_loop_runtime.claude_bakeoff run` on the W0 head.
3. Read the usage meter at each of the seven prompts.
4. At each of the two control blocks, paste the kit's brief into a T3 Code thread.
5. Review the kit's redacted records, and approve the records PR (G2).
6. Answer OD-3b (G3), together with OQ-7 and OQ-8.

**Owner questions.** Each lists the recommended default first.
- **OQ-1, runs per block.** Three, for 18 records. The alternative is five per arm in a
  single pass, with no control for order.
- **OQ-2, meter cadence.** Per block: seven readings, each after a 5-minute settle. Reading
  per run would take 19 readings.
- **OQ-3, per-run timeout.** 30 minutes.
- **OQ-4, sessions.** One session after GL-2. The alternative is an early session for the
  first print and control blocks, which costs one extra reading.
- **OQ-5, capture twins.** One per native block, run unjailed with tools under the owner's
  login (principle 5). One per run doubles native runs for the same set.
- **OQ-6, the `print` landing, before SL-2 merges.** Accept the content check in place of
  §4a item 9's merge form. If declined, the merging maintainer uses item 9's form; this plan
  doesn't change.
- **OQ-7, "none admitted", needed at G3.** "Typed-degraded" is a matrix and card status, and
  the TUI keeps launching as §4a's default until CLAUDETUI's OD-6. The alternative is a
  typed refusal, which would be a default change under EC-CLAUDE-4.
- **OQ-8, open-egress expiry, needed at GL-6.** The switch date plus 90 days, renewable by an
  owner record in the matrix.

**Single writers.** SL-1: `panel_invoker.py`, `claude_seat_transport.py`, `test.yml`, `claude-sdk-audit.yml`. SL-5:
the decision record and the v11 files. SL-6: the inventory and docs. Producer lanes hand
changes to these owners inside their own landing PRs.

**PANELSPLIT and v11.** v11 PANELSPLIT may split `panel_invoker.py` at any time; CLAUDE
rebases onto the split rather than block it. SL-1's ownership then moves to the seat-launch
module PANELSPLIT's map names, and SL-6 regenerates the inventory rows. FIRSTSEAT lane D also
writes `panel_invoker.py`; whichever lands second rebases. EC-CLAUDE-8 is the only ownership
transfer out of v11.

**Registration.** The interim `superseded` registration is a workaround until
agent-harness#1824. Switching to `advisory` changes the roadmap's bytes, so that commit
re-pins this plan's `roadmap_sha256`.

**Load limits (owner instruction).** Every test command runs serially (`-n 0`; `pytest-xdist`
is added only so `-n` parses) under `timeout`. The full suite runs only in hosted CI and
Gate A, never locally on a shared host. `VL` runs targeted on a host class with the jail
prerequisites. Live W0 runs are owner actions.

**Issues and review.** SL-6's final sweep comments each issue the roadmap lists as absorbed,
citing its landing PR; closure follows the INVENTORY issue index. Every PR goes through
principle 2: the six required checks, a dispatched Gate A where packaging, workflows or
tested docs change, and a cross-vendor board on the exact head.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `plans/decision-claude-print-subscription-route-20261008.md`, `specs/phase-plans-v11.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/seat-qualification/claude-w0/`
- redaction posture: `metadata_only`; meter readings and raw captures stay private, and records carry references and digests.
- downstream handling: `roadmap amendment` (the v11 EC-PANEL-6 consumption note, SL-5, non-blocking).

## Verification

`P` abbreviates the serial pytest prefix: `timeout 900 uv run --quiet --project
phase-loop-runtime --group test --extra visual --with pytest-xdist==3.8.0 --python 3.14
--locked python -m pytest -n 0 -p no:cacheprovider -q`. Each file below lives under
`phase-loop-runtime/tests/`. `PS` is `P` with `--extra claude-sdk` added before
`--with` (V4, VB and VL). VB/VL also require the contract's documented worker install,
private-suite operands and session-bound JUnit; CI and board run its proof checker.

Collection rule (agent-harness#1825): absent SDK files are pending, not passing coverage;
every implemented selector must collect tests. `suite_command` is the implemented-lanes
regression suite: only the two absent SDK operands were removed. SDK refusal coverage
stays. Green automation cannot satisfy EC-CLAUDE-3 or close the phase. SL-3 restores both
files with `--extra claude-sdk`; no placeholders, filtering or skip-to-success wrappers. On this plan-only
checkout, all nine new test files are absent: serial collect-only returned exit 4 for each,
including `-k boundary_proof`. These are pending selectors, not passing test receipts.

- `V1`: `P test_seats_claude_login_proof.py test_seat_credentials.py test_claude_seat_subscription_proof_1444.py test_seat_credential_refresh.py`
- `V2`: `P test_seats_claude_transport.py test_seats_claude_order.py test_claude_transport_seam.py test_panel_claude_print_route.py test_seat_login_wait_a3_1166.py test_seat_login_wait_board_context_r12.py test_seat_notices.py test_seat_session_label.py test_seat_sandbox_permissions.py`
- `V3`: `P test_seats_claude_print.py test_seats_claude_print_observations.py test_seats_claude_transport.py`
- `V4`: `PS test_seats_claude_sdk.py test_seats_claude_sdk_adapter.py test_local_check.py test_ci_xdist_adoption.py test_executable_dependency_startup.py test_seats_claude_transport.py`
- `VB`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 PS test_seats_claude_sdk.py -k boundary_proof --junitxml=<private-receipt>`; provider-free, real SDK/jail, synthetic credentials. A skip or zero collection fails. Record interpreter, host class and EC-CLAUDE-3 input digests; retain evidence privately.
- `V5`: `P test_seats_claude_bakeoff.py`
- `V6`: `P test_seats_claude_records.py`
- `V7`: `timeout 300 uv run --quiet --project phase-loop-runtime --python 3.14 --locked python -m phase_loop_runtime.claude_bakeoff validate plans/evidence/seat-qualification/claude-w0`.
- `V8`: `P test_seat_reference_inventory.py`, plus the docs-freshness audit in hosted CI
- `V9`: `automation.suite_command`. The full suite runs in hosted CI and dispatched Gate A only.
- `V10`: `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-v11.md` and `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 PS test_seats_claude_transport.py test_seats_claude_print.py test_seats_claude_sdk.py -k live_jail --junitxml=<private-receipt>`, run on a named host class with jail prerequisites. Require nonzero collection per file; any skip fails. The activating PR cites the `--junitxml` receipt's digest and host class; the file stays private.

## Acceptance Criteria

- [ ] EC-CLAUDE-1 — proven by `VL` (`test_seats_claude_transport.py`, real modules in a live jail) and by `V7` over W0's native records, falsified by any stub control in that file passing; path-entered control: each stub enters through the real `_parent_infer` jailed call site.
- [ ] EC-CLAUDE-2 — proven by `V3` and `VL` (`test_seats_claude_print.py`) and by agent-harness#1740 closed citing the landing PR, falsified by any injection or hardening control in that file admitting; path-entered control: each enters through `claude_seat_print.run_jailed`.
- [ ] EC-CLAUDE-3 — proven by `V4`, `VB`, `VL` at GL-2, W0 provenance records and agent-harness#1744 disposition. Falsified by any SL-3 mutation control passing; path-entered control: `_parent_infer` dispatch to `claude_seat_sdk.run_jailed` with the real SDK. Fixture-only tests cannot replace `VB`.
- [ ] EC-CLAUDE-4 — proven by `V2` (`test_seats_claude_order.py`) and by the required `audit-order` step on each gated landing, falsified by any `audit_order` control passing; path-entered control: each enters through the `audit-order` CLI on a disposable tree.
- [ ] EC-CLAUDE-5 — proven by G2's reviewed records PR, with `V7` as its shape check, falsified by any validator control in `test_seats_claude_bakeoff.py` passing; path-entered control: each disposable record enters through `claude_bakeoff validate`.
- [ ] EC-CLAUDE-6 — proven by `V2` (`test_seats_claude_order.py`) after GL-5 and GL-6, falsified by its default-rule or card-statement control passing; path-entered control: a disposable OD-3b section naming another transport enters through `audit-order`.
- [ ] EC-CLAUDE-7 — proven by `V1` and `V2` (`test_seats_claude_login_proof.py`, `test_seats_claude_transport.py`), falsified by a failing-probe control that still launches; path-entered control: the stub probe enters at the real `_parent_infer` call site.
- [ ] EC-CLAUDE-8 — proven by `V6` (`test_seats_claude_records.py`) and `V10` after the v11 note lands, falsified by the two-owner amendment control passing; path-entered control: the disposable amendment copy enters through the records test's parser.

The phase exits only when all eight criteria hold, after G2, G3 and the v11 note. Planning
implements no IF gate.
