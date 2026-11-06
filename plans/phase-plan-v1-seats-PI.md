---
phase_loop_plan_version: 1
phase: PI
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9dc889c61a8d682dde30af65bf1597c1dca9a0df094fac747194d3629939b16e
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_pi_panel_leg.py", "phase-loop-runtime/tests/test_panel_invoker.py", "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py", "phase-loop-runtime/tests/test_panel_per_leg_model_66.py", "phase-loop-runtime/tests/test_pi_seat_profile.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_executable_dependency.py", "phase-loop-runtime/tests/test_pi_routed_identity.py", "phase-loop-runtime/tests/test_advisor_board_composition.py", "phase-loop-runtime/tests/test_governed_review.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# PI: Pi Review Seat

## Context

This plan covers roadmap Phase 8 (PI) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Acceptance is EC-PI-1 through EC-PI-5, cited by ID only.

**Frozen inputs.** PI consumes `plans/seats-jailcore-route-contract.md` at sha256
`235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`, including
IF-0-JAILCORE-1, IF-0-JAILCORE-2 and IF-0-JAILCORE-3. It also consumes
IF-0-TEAMHOST-1, IF-0-TEAMHOST-2 and IF-0-TEAMHOST-3; TEAMHOST must publish those exact IDs
before PI execution, and a different ID or meaning requires this plan to be amended. PI adds
exactly one `JailProfile` and exactly one allowlist. It changes no existing JAILCORE code,
descend set, resolver, proxy, qualification-key or route-policy behavior.

**Placement boundary.** The 2026-11-06 placement agreement is pinned to
Consiliency/agent-toolkit `docs/placement-consolidation.md` at external revision 9304a5b9.
agent-harness owns placement; agent-toolkit retains Pi agents,
toolsets, runner inputs, link and credential proxy. The projection keeps `landlock-exec` at
d945fdd0 and `pi-subagents` at `0.84.0`; the `ai` client remains
`OU=agent-toolkit`. Pi children remain one-shot, non-steerable and limited to 3600 seconds per
attempt. The separate Pi LANE-executor placement plan owns remote placement, admission, patch
return and retry. This phase is only the Pi REVIEW SEAT: it does not edit `launcher.py`, placement
profiles, `supervised_worker_cli`, runner images or remote-executor policy.

**Owner gate.** OD-5 must record the credential lane, one routed provider id, aggregator
disposition, spend cap for an API-billed lane, and board slot (explicit composition only). Lane C
measures the request set and credential scope under that record. The roadmap default is the current routed provider credential, no
aggregator, a spend cap and no plan/production slot. The agent-toolkit candidate is provider
`lithos`, model `deepseek-ai/DeepSeek-V4.1-Flash`, endpoint `api.lithosai.cloud`; it is evidence,
not a decision. Lane C stops before landing until OD-5 resolves every field. Lanes A and B may
land disabled.

## Interface Freeze Gates

- [ ] **IF-0-PI-1 (plan-internal) — one-shot leg and verdict.** One fresh process per attempt,
  no session resume or mid-run input, deadline at most 3600 seconds. The command shape, bound to
  the projected `pi` package version in the projection digest and proven against that binary, is
  `pi --provider P --model M --thinking E --mode json --print --no-session --no-approve
  --no-context-files --no-mcp --no-skills --no-prompt-templates --no-themes --no-extensions
  --extension TOOLSET --tools read,read_image,glob,grep,bash --`; prompt bytes arrive on stdin.
  `TOOLSET` is the projected, pinned agent-toolkit reviewer toolset, never ambient discovery.
  Success requires one terminal assistant `message_end`, a board-verdict payload, and
  `agent_settled.aborted == false`; malformed, missing, duplicate or post-terminal content is a
  typed leg failure. No retry resumes a process.
- [ ] **IF-0-PI-2 (plan-internal) — single profile.** One registry entry, key `pi`,
  `vendor="pi"` (the readiness-row id bound by IF-0-JAILCORE-1), `projection="required"`,
  `CredentialDelivery(channel="home_file",
  scope_evidence=<OD-5 receipt>)`, `allowlist_id="pi"`, closed `ConfigSurface`, full declared
  reviewer tools, and a terminal output-secret code. Its private home contains only the selected
  provider/model and scoped credential. Missing OD-5 evidence, projection, credential, allowlist or
  qualification resolves degraded through IF-0-JAILCORE-1; no exception or unconfined route is
  added. Under IF-0-JAILCORE-1's additive vendor rule it contributes
  `pi_seat_credential_missing` (ordinary), `pi_seat_od5_evidence_missing` (ordinary),
  `pi_seat_spend_cap_missing` (ordinary), and `pi_seat_secret_in_output` (security), with matching
  `seat_jail.NOTICES` and `OD10_CLASSES` entries, plus only Pi's `WindowRows` data. No existing
  code, class or window-kit function changes.
- [ ] **IF-0-PI-3 (plan-internal) — route and identity.** The sole egress artifact is
  `phase_loop_runtime/seat_egress/pi-allowlist.json`, id `pi`, schema
  `phase_loop_seat_egress_allowlist.v1`, with only OD-5's measured provider requests and refusals.
  `PiRoutedIdentity(harness, requested_model, launch_provider, response_provider, response_model)`
  is accepted only when `harness == "pi"`, both provider fields equal the OD-5 provider and the
  response model is present. Vendor counting uses that provider, never the model string. The
  `JailProfile.vendor` remains `pi`; only board composition and independence use the routed
  provider from `PiRoutedIdentity`. Landing
  aliases use `(harness, model)` keys. Pi has no implicit plan/production alias; a same-routed-vendor
  author/reviewer pair is refused.

## Lane Index & Dependencies

SL-1 — Leg and verdict (lane A)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until enablement

SL-2 — Profile and projection (lane B)
  Depends on: (none)
  Blocks: SL-1 enablement, SL-4
  Parallel-safe: yes

SL-3 — Credential, egress and identity (lane C)
  Depends on: SL-2
  Blocks: SL-1 enablement, SL-4
  Parallel-safe: no

SL-4 — Evidence and documentation reducer (SL-docs)
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Leg and verdict (lane A)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py`, `phase-loop-runtime/tests/test_pi_panel_leg.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py`, `phase-loop-runtime/tests/test_panel_per_leg_model_66.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: IF-0-PI-1

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.1 | test | — | Path-enter the exact argv/stdin and JSONL parser. Prove one process, ≤3600-second deadline, no session/steering flags, exact toolset, bounded output, board-verdict validation, and typed failures for every malformed terminal sequence. Prove the registered backing is homebrew. An absent flag/event is a typed failure; SL-4 records the proven shape from this test. | `V1` |
| SL-1.2 | impl | SL-1.1 | Add the disabled Pi adapter and parser. It cannot be selected while any IF-0-PI-2/3 predicate is false. | `V1` |
| SL-1.3 | test | SL-3 | Prove the adapter remains unreachable for each missing profile, credential, scope receipt, spend-cap record, allowlist, qualification or attribution input; then prove the fully admitted path. | `V1` |
| SL-1.4 | impl | SL-1.3 | Flip Pi to homebrew and enable it through the leg selector only when IF-0-PI-2/3 hold and board config lists `pi`. Assert the default plan/production composition is unchanged. | `V1` |

### SL-2 — Profile and projection (lane B)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_pi_seat_profile.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_executable_dependency.py`
- **Interfaces provided**: IF-0-PI-2
- **Interfaces consumed**: IF-0-JAILCORE-1/2/3 (pre-existing), IF-0-TEAMHOST-1/2/3 (pre-existing at execution)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Assert registry count increases by exactly one and the only new key is `pi`. Exercise the real projection for the Pi runtime and explicit toolkit toolset. The closure excludes `landlock-exec` and `pi-subagents`; their d945fdd0 and 0.84.0 pins belong to the separate Pi LANE-executor plan. Plant project/user provider overrides, hooks, skills, MCP and extensions and prove none load. Assert the four exact codes/classes and Pi-only window data; mutation of any existing entry or window-kit function fails. | `V2` |
| SL-2.2 | impl | SL-2.1 | Register the IF-0-PI-2 profile and append only its four code/class entries and `WindowRows`. Its credential and absent allowlist fail closed until SL-3. | `V2` |
| SL-2.3 | verify | SL-2.2 | Prove profile digest stability, projection-digest binding, private per-account state, full declared tools, planted-config refusal and terminal planted-secret detection. | `V2`, `VL0` |

### SL-3 — Credential, egress and identity (lane C)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/pi_review_route.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-allowlist.json`, `phase-loop-runtime/tests/test_pi_routed_identity.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_governed_review.py`
- **Interfaces provided**: IF-0-PI-3
- **Interfaces consumed**: IF-0-PI-2, IF-0-JAILCORE-1/2/3 (pre-existing), OD-5 (pre-existing owner record)
  `advisor_board/schema.py`, `advisor_board/composition.py` and `governed_review.py` are also v11
  PANEL/ROUTE surfaces. This lane adds `PiRoutedIdentity` and edits only `schema.vendor_family`,
  `schema.vendor_of_harness`, `schema.vendor_of_model`, `composition.board_independence`,
  `governed_review.select_reviewer_pool` and `governed_review.author_vendor_for_model`; it rebases
  if second and never edits the same function concurrently.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | decision | SL-2, OD-5 record | Consume OD-5. Measure the provider request/refusal set and scope; create one `pi-allowlist.json`, never a second provider file. | receipt digest |
| SL-3.2 | test | SL-2; SL-3.1 for provider fixture | Path-enter launch config plus terminal provider response. Refuse mismatch, absent response provider/model, model-name vendor inference, `(model)`-only alias lookup, a Pi `gemini-*` alias fill, same-routed-vendor independence and every other-provider/unlisted endpoint. Mutation controls neutralise each check. | `V3` |
| SL-3.3 | impl | SL-3.2 | Add the private provider config, IF-0-PI-3 identity, tuple-key aliases, independence check and sole allowlist. Store no credential or response body in evidence. | `V3` |
| SL-3.4 | verify | SL-3.3 | Re-hash the allowlist into the qualification key; run the real proxy refusals and a redaction scan. | `V3`, `VL0` |

### SL-4 — Evidence and documentation reducer (SL-docs)

- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`, `plans/evidence/seats-pi/**`
- **Interfaces consumed**: IF-0-PI-1, IF-0-PI-2, IF-0-PI-3

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-4.1 | evidence | SL-1, SL-2, SL-3 | On a TEAMHOST-qualified host, attach provider-free `VL0` receipts and set only the Pi row to `candidate`. Attach the owner's `VL1` row-window record and set `done-local` only when it binds the current qualification key. If the owner records OD-9 for a named host-class falsifier, set `remote-pending` with its interim route. | `VL0`, `VL1` |
| SL-4.2 | docs | SL-4.1 | Apply `canonical_spec_update` to the three required spec surfaces, inventory and changelog. Rescan the docs catalog. Evidence is metadata-only. | `V4` |
| SL-4.3 | closeout | SL-4.2 | Emit `spec_delta_closeout.v1`; missing/malformed evidence uses `terminal_status=blocked`, `verification_status=blocked`, `blocker_class=contract_bug`. Otherwise record the supported terminal status with `verification_status=passed` and `blocker_class=none`. | `V4` |

## Execution Notes

- Lane A and lane B start without OD-5. Lane A lands its adapter disabled; SL-1.3 and SL-1.4
  resume only after lane C publishes IF-0-PI-3. Lane C's tests start after lane B; SL-3.1,
  SL-3.3 and SL-3.4 need OD-5, and nothing in lane C lands without it. SL-4 is terminal.
- `panel_invoker.py` is lane A's single-writer surface. `seat_profiles.py` is lane B's. The
  identity functions named in lane C are its narrow v11 PANEL/ROUTE sharing boundary; the
  second landing rebases. Lane B's only JAILCORE-file edits are the additive Pi entries frozen in
  IF-0-PI-2. No lane edits `seat_egress_proxy.py`, placement or executor modules.
- The exactly-one profile and exactly-one allowlist assertions are repository-wide count and
  path controls, not prescribed commit counts. The plan pins only upstream inputs.
- No release is dispatched, so no post-dispatch back-fill of a tag or workflow result applies.

## Verification

Run serially after the repository load/IO precheck:

```bash
V1="timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_pi_panel_leg.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py phase-loop-runtime/tests/test_panel_per_leg_model_66.py phase-loop-runtime/tests/test_seat_reference_inventory.py"
V2="timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_pi_seat_profile.py phase-loop-runtime/tests/test_seat_profiles.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_route_contract.py phase-loop-runtime/tests/test_seat_notices.py phase-loop-runtime/tests/test_executable_dependency.py"
V3="timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_pi_routed_identity.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_governed_review.py"
V4="timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_reference_inventory.py"
```

`VL0` is provider-free: real TEAMHOST projection/admission, closed-config and planted-secret
falsifiers, plus real-proxy refusal of an unlisted host and a second provider's listed host. `VL1`
is the governed row window: one real Pi review, launch/response attribution, verdict, exec record,
current qualification key and spend-cap evidence. Secret values and response bodies are not retained.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/advisor-board-capabilities-card.md`,
  `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`,
  `docs/review-seats-readiness.md`
- evidence paths: `plans/evidence/seats-pi/**`
- redaction posture: `metadata_only`
- downstream handling: none

## Acceptance Criteria

- [ ] EC-PI-1 — proven by `V1` and IF-0-PI-1. Falsified by any removed enablement predicate making the recording adapter reachable. Path-entered control: each mutation enters through the real panel-leg selector and spawn path.
- [ ] EC-PI-2 — proven by `V2`, IF-0-PI-2 and `VL0`. Falsified by any planted ambient surface loading or by removing a projection pin without changing the qualification key. Path-entered control: the real profile resolver, projection admission and jailed launch are used.
- [ ] EC-PI-3 — proven by `V3` plus OD-5, the sole allowlist digest, `VL0` and `VL1`. Falsified by the real proxy admitting an unlisted or second-provider request. Path-entered control: the jailed reviewer tool enters through its per-seat proxy.
- [ ] EC-PI-4 — proven by `plans/evidence/seats-pi/**` and `VL0`/`VL1`. Falsified by accepting a `done-local` row whose window record does not bind the current qualification key. Path-entered control: the readiness-row reducer reads the recorded window result.
- [ ] EC-PI-5 — proven by `V3`. Falsified by neutralising each attribution, tuple-alias or independence check while its mutation test still passes. Path-entered control: launch config and terminal provider response enter through the real composition and governed-review paths.
