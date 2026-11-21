---
phase_loop_plan_version: 1
phase: PI
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 1f2c4970163d1930bc398fd5abc3a2869c3a0bf32ba3805d483ef987dd1017e6
automation:
  suite_command: ["timeout", "900", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--python", "3.14", "--python-preference", "only-system", "--locked", "python", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_pi_panel_leg.py", "phase-loop-runtime/tests/test_panel_invoker.py", "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py", "phase-loop-runtime/tests/test_panel_per_leg_model_66.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py", "phase-loop-runtime/tests/test_pi_seat_profile.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_executable_dependency.py", "phase-loop-runtime/tests/test_seat_pi_credential.py", "phase-loop-runtime/tests/test_pi_routed_identity.py", "phase-loop-runtime/tests/test_advisor_board_composition.py", "phase-loop-runtime/tests/test_governed_review.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# PI: Pi Review Seat

## Context

This plan covers roadmap Phase 8 (PI) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Acceptance is EC-PI-1 through EC-PI-5, cited by ID only.

**Frozen inputs.**

- `plans/seats-jailcore-route-contract.md`, sha256
  `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`: IF-0-JAILCORE-1,
  IF-0-JAILCORE-2 and IF-0-JAILCORE-3.
- IF-0-TEAMHOST-1, IF-0-TEAMHOST-2 and IF-0-TEAMHOST-3.
- `plans/artifacts/seats-pi-route-contract-v1.md`, sha256
  `e7bc180ce8a2a0536d594584817a81b5364c1a74ff133681c96d9baf79314437` (the "contract" below).
  It carries the Pi source facts, routes, credential, egress, attribution, spend-cap, code and
  shared-surface detail, and this plan cites it by section.

PI adds exactly two `JailProfile`s (`pi` and `pi-deepseek`) and exactly two allowlists, one per
leg, as additions under IF-0-JAILCORE-1 (contract §4). It changes no JAILCORE code, descend
set, resolver, proxy, qualification-key or route-policy behavior. Resource caps come from
`seat_profiles.register`'s precondition.

**Placement boundary.** The 2026-11-06 placement agreement is pinned to
Consiliency/agent-toolkit `docs/placement-consolidation.md` at external revision 9304a5b9.

- agent-toolkit retains the Pi agents, toolsets, runner inputs, link and credential proxy.
- The `landlock-exec` (d945fdd0) and `pi-subagents` (`0.84.0`) pins belong to the Pi
  LANE-executor plan.
- This phase is the review seat only. It does not edit `launcher.py`, placement profiles,
  `supervised_worker_cli`, runner images or remote-executor policy.

**OD-5 (owner, 2026-11-21).** The owner's answer, verbatim: "1. But pi should be able to use
subscription authed providers primarily". The roadmap default otherwise stands. Then the owner
answered two follow-ups:

- **OQ-1: "OpenAI subscription".** The primary route is Pi's `openai-codex` subscription
  sign-in, counted as codex. Its credential is the operator's existing Pi `openai-codex`
  sign-in, so the executor-credential default holds.
- **OQ-2: "Yes, DeepSeek with a cap".** A DeepSeek API-key route is wanted in v1.

The DeepSeek route stays inert, with the typed `pi_seat_spend_cap_missing`, until the owner
supplies the remaining inputs: the cap amount, the cap period, and the key source (the executor's
key or a seat-only key). Contract §1 and §9 hold the detail.

## Interface Freeze Gates

- [ ] **IF-0-PI-1 (plan-internal) — one-shot leg and verdict.** The command, private
  directory, tools, terminal grammar and fixtures are as in contract §7.
  - There is no trailing `--`, and the command is proven against the projected binary.
  - One fresh process per attempt. The deadline is at most `panel_invoker._LEG_TIMEOUT_MAX_S`.
  - Success needs the full terminal grammar and a clean final `stop`. Tool names are checked
    across the whole stream.
  - The typed ends are as in contract §5. No retry resumes a process, renews a credential or
    switches route.
- [ ] **IF-0-PI-2 (plan-internal) — two profiles.**
  - Two registry entries, `pi` and `pi-deepseek`, defined in `seat_profile_pi.py` and
    registered by `register_pi()`. That function also registers the provider executable `pi`
    and a `seat_admission` gate, as `seat_profile_codex.py` does.
  - Each profile has `vendor="pi"`, `projection="required"`, its own `allowlist_id`, a closed
    `ConfigSurface`, the declared reviewer tools, and `variant` = the `PiRouteSnapshot` digest
    (contract §3).
  - `CredentialDelivery(channel="home_file", scope_evidence=<route record>)`.
  - `ContainmentEvidence` points at `plans/evidence/seats-pi/vl0/containment.json`, or its
    `paid/` equivalent for `pi-deepseek`.
  - Each private home holds the credential copy, `settings.json` and the CA, as in contract §7
    and §8.
  - Both legs' `WindowVendorData` have `default=False`.
  - The 13 codes of contract §10 get `seat_jail.NOTICES` rows, a `seat_jail.PI_SEAT_CODES` set
    and `OD10_CLASSES` entries.
  - Any missing input resolves degraded through IF-0-JAILCORE-1.
- [ ] **IF-0-PI-3 (plan-internal) — route, credential, egress and identity.**
  - Route records and the immutable `PiRouteSnapshot`: contract §3 and §4.
  - The credential copy, immutable mount, identity-checked read-back and parent-side secret
    registration: contract §8.
  - Margin and expiry: contract §5.
  - Per-launch namespace, proxy, budget and named observations: contract §6.
  - The spend cap: contract §9.
  - Provider attestation from the complete proxy stream. `PiRoutedIdentity(harness,
    requested_model, launch_provider, response_provider, response_model)` takes its
    `response_provider` from that stream, never from Pi's JSONL (contract §11).
  - `PI_PROVIDER_VENDOR`, `(harness, model)` alias keys, author provenance, and the named policy
    consumers: contract §11.
  - No `pi` outcome selects `pi-deepseek`.

## Lane Index & Dependencies

SL-1 — Leg, verdict and fixtures (lane A)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until SL-1.3

SL-2 — Profiles and projection (lane B)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until SL-2.3

SL-3 — Route, credential, egress, identity and policy (lane C)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until SL-3.5

SL-4 — Evidence, qualification and documentation (SL-docs)
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Leg, verdict and fixtures (lane A)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py`, `phase-loop-runtime/tests/data/seats_pi/**`, `phase-loop-runtime/tests/test_pi_panel_leg.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py`, `phase-loop-runtime/tests/test_panel_per_leg_model_66.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: IF-0-PI-1
- **Fixtures.** SL-1.0 freezes `tests/data/seats_pi/` (event streams, synthetic route records, synthetic stores). SL-2 and SL-3 read it and never write it.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.0 | test | — | Freeze the fixture interface. Record contract §7 streams from the projected binary against a loopback provider fixture behind a test-only seam: tooled success, assistant error, malformed, duplicate and post-terminal streams, a 401, a 429, a transport reset, and a response model that differs from the request. | `V1` |
| SL-1.1 | test | SL-1.0 | Path-enter the argv, stdin and parser. Prove: no bare `--`; `--offline`; no `--api-key`; one process; the leg-cap deadline; the terminal grammar; per-event tool names; bounded output; the §5 typed ends. Homebrew backing is a test-only seam here. | `V1` |
| SL-1.2 | impl | SL-1.1 | Add the disabled Pi adapter, the per-launch namespace and proxy binding (contract §6), the credential mount and secret-registration hooks (contract §8), and inventory entries. Edit no function in `SDK_PROOF_REGIONS`. | `V1` |
| SL-1.3 | test | SL-2.3, SL-3.5 | Prove the adapter is unreachable for each missing input: profile, snapshot, credential, spend cap (`pi-deepseek`), allowlist, qualification, bridge proof or stream completion. Prove both admitted paths, and that no `pi` outcome selects `pi-deepseek`. | `V1` |
| SL-1.4 | impl | SL-1.3 | Register harness `pi-deepseek`. Flip both legs to homebrew: `pi` with the subscription lane, `pi-deepseek` with the api_key lane behind `allow_api_key_fallback`. Wire `pi_review_route` alias keys into `_validate_review_board_policy`. The default composition is unchanged. | `V1` |

### SL-2 — Profiles and projection (lane B)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profile_pi.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_pi_seat_profile.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_executable_dependency.py`
- **Interfaces provided**: IF-0-PI-2
- **Interfaces consumed**: IF-0-JAILCORE-1/2/3 (pre-existing), IF-0-TEAMHOST-1/2/3 (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Assert the registry grows by exactly `pi` and `pi-deepseek`. Exercise the real Pi projection: node, the Pi package and the explicit toolset; `landlock-exec` and `pi-subagents` are excluded. Plant provider overrides, `models.json`, hooks, skills, MCP and extensions, and prove none load. Assert the 13 codes and classes, `resource_caps` and Pi-only window data. | `V2` |
| SL-2.2 | impl | SL-2.1 | Add `seat_profile_pi.py` and its `register_pi()` call, including the provider executable and admission gate. Append only the Pi codes, classes and `WindowRows`. The profiles fail closed until SL-3's records and credential module exist. | `V2` |
| SL-2.3 | verify | SL-2.2, SL-3.4, SL-1.2 | Prove profile digest stability, snapshot-in-variant, projection binding, private per-account state with CA and cleanup, planted-config refusal and terminal planted-secret detection. | `V2`, `VL0` |

### SL-3 — Route, credential, egress, identity and policy (lane C)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_pi_credential.py`, `phase-loop-runtime/src/phase_loop_runtime/pi_review_route.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-route.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-deepseek-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-deepseek-route.json`, `plans/evidence/seats-pi/route/**`, `phase-loop-runtime/tests/test_seat_pi_credential.py`, `phase-loop-runtime/tests/test_pi_routed_identity.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_governed_review.py`
- **Interfaces provided**: IF-0-PI-3
- **Interfaces consumed**: IF-0-JAILCORE-1/2/3 (pre-existing), OD-5/OQ-1/OQ-2 (pre-existing owner record)
- **Policy ownership.** SL-3 is the single owner of policy and alias semantics. It edits only
  these functions:
  - `schema.vendor_family` and `schema.vendor_of_harness`;
  - `composition.board_independence`;
  - `governed_review.select_reviewer_pool`, `author_vendor_for_executor` and
    `author_vendor_for_model`;
  - `president_adapter.seat_for_rung`.

  It provides the alias-key function that SL-1.4 wires in. If it lands second, it rebases.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | evidence | — | On the designated seat host, for `pi` (`openai-codex`): measure the request set, the startup hosts under `--offline`, the WebSocket behaviour with forced SSE, the token lifetime (`exp − iat`, no value kept), the kept fields, the read-only turn and the POST budget. Write `pi-route.json` and `pi-allowlist.json`, contract §4. Measure the `pi-deepseek` rows and write its records with `spend_cap_required`. The row window is the first live confirmation and fails closed. Report a lifetime below the margin, or a needed writable copy, as a STOP. | receipt digest |
| SL-3.2 | test | SL-1.0 | Path-enter the credential module against synthetic stores: both entry types, malformed or duplicate entries, other providers, `!`, `$` and `${}` keys, exact margin boundaries under a clock fixture (−1 ms, 0, +1 ms), non-credible expiry, claims outside the ceiling, every spend-cap mismatch (provider, account, key binding, validity, non-positive, missing field), and planted ambient credentials. Mutation controls neutralise each check. | `V3` |
| SL-3.3 | test | SL-1.0 | Path-enter the snapshot, `PI_PROVIDER_VENDOR`, alias keys and author provenance through the real `board_independence`, `select_reviewer_pool`, `_validate_review_board_policy` and `seat_for_rung`. Refuse a provider mismatch, an incomplete stream, the fixture's differing response model as evidence, model-name inference (including `gemini-*`), a `(model)`-only alias, a same-vendor pair and unknown provenance. | `V3` |
| SL-3.4 | impl | SL-3.2, SL-3.3 | Add `seat_pi_credential.py` and `pi_review_route.py`, and make the named policy edits. Store no credential or response body in evidence. | `V3` |
| SL-3.5 | verify | SL-3.1, SL-3.4, SL-2.3 | Re-hash the snapshot into the qualification key. Run contract §6 probes from real tool descendants, the redaction scan, and the falsifiers below. | `V3`, `VL0` |

| Claim | Falsifier (any one fails the claim) |
|---|---|
| Subscription first | A `pi` outcome (an expiring token, an expiry, a refusal or unavailability) selects `pi-deepseek`; or `pi-deepseek` runs without `allow_api_key_fallback` and a valid §9 record. |
| Access-only, immutable | The copy carries a non-empty `refresh`, a second entry, an unlisted field, `env` or a non-literal key; the in-seat file can be replaced; or read-back accepts a substituted object. |
| No in-jail refresh | A token-host request is allowed, or credential-file activity is not reported as `pi_seat_token_refreshed_in_jail`. |
| Expiry typed | A copy below the margin at spawn launches; an upstream 401 ends other than `pi_seat_credential_expired`; a 429, transport failure or proxy refusal is misclassified; a retry renews. |
| Egress per launch | An unlisted host, a same-host path or method, a non-443 authority, direct-IP or DNS from a tool descendant succeeds; or a leg runs in another leg's namespace. |
| Attribution | A leg counts without a complete stream showing its inference row, or Pi's JSONL decides the provider. |
| No secret leak | A planted sentinel reaches any published artifact on a success or failure path. |
| Spend cap | `pi-deepseek` admits with a missing, stale, other-account or other-key record. |

### SL-4 — Evidence, qualification and documentation (SL-docs)

- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`, `plans/evidence/seats-pi/vl0/**`, `plans/evidence/seats-pi/vl1/**`, `plans/evidence/seats-pi/paid/**`
- **Interfaces consumed**: IF-0-PI-1, IF-0-PI-2, IF-0-PI-3
- **Cross-lane qualification owner.** SL-4 runs `VL0`/`VL1`.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-4.1 | evidence | SL-1, SL-2, SL-3 | On the designated seat host, attach `VL0` (`vl0/containment.json`) and set the Pi row to route `jailed`, status `candidate`. Attach the owner's `VL1` record and set `done-local` only when it binds the current qualification key. If the owner records OD-9, set `remote-pending`. | `VL0`, `VL1` |
| SL-4.2 | evidence | SL-4.1 | Keep `pi-deepseek`'s admission and window evidence separate, under `paid/`. It reads `pi_seat_spend_cap_missing` until the owner's §9 record exists. It never gates EC-PI-4's Pi row. | `VL0` |
| SL-4.3 | docs | SL-4.1 | Apply `canonical_spec_update` to the three spec surfaces, recording the subscription-first route and the inert paid leg. Update the inventory, changelog and docs catalog. Evidence is metadata-only. | `V4` |
| SL-4.4 | closeout | SL-4.3 | Emit `spec_delta_closeout.v1`. Missing or malformed evidence: `terminal_status=blocked`, `verification_status=blocked`, `blocker_class=contract_bug`. Otherwise `verification_status=passed` and `blocker_class=none`. | `V4` |

## Execution Notes

- **Immediate starts.** SL-1.0–1.2, SL-2.1–2.2, SL-3.1 (route work) and SL-3.2–3.4 start now.
  Activation (SL-1.3–1.4) follows SL-2.3 and SL-3.5. SL-4 is terminal.
- **Single writers.**
  - `panel_invoker.py`: SL-1.
  - `seat_profile_pi.py`, `seat_profiles.py` (the `register_pi()` call only) and the additive
    JAILCORE-file entries: SL-2.
  - The named policy functions: SL-3.
- **No lane edits** `seat_egress_proxy.py`, `seat_egress/proxy.mjs`, `grok_tool_surface.py`,
  `seat_credentials.py`, `seat_codex_credential.py`, window-kit functions, placement or
  executor modules (contract §12).
- **Owner stops (contract §12).**
  - S2: SL-2's edits to `seat_profiles.py` and `seat_route_contract.py` stale the Claude SDK
    proof receipt. The coordinator assigns the EC-CLAUDE-3 re-proof to the CLAUDE owner before
    SL-2 lands.
  - S1, S3, S4 and S5 are STOPs if reached.
- **Pins.** The count assertions are repository-wide controls, not commit counts. The plan pins
  only upstream inputs. No release is dispatched.

## Verification

Run serially after the load/IO precheck.

```bash
U="timeout 900 uv run --quiet --project phase-loop-runtime --group test --python 3.14 --python-preference only-system --locked python -m pytest -p no:cacheprovider -q"
V1="$U phase-loop-runtime/tests/test_pi_panel_leg.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py phase-loop-runtime/tests/test_panel_per_leg_model_66.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py phase-loop-runtime/tests/test_seat_reference_inventory.py"
V2="$U phase-loop-runtime/tests/test_pi_seat_profile.py phase-loop-runtime/tests/test_seat_profiles.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_route_contract.py phase-loop-runtime/tests/test_seat_notices.py phase-loop-runtime/tests/test_executable_dependency.py"
V3="$U phase-loop-runtime/tests/test_seat_pi_credential.py phase-loop-runtime/tests/test_pi_routed_identity.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_governed_review.py"
V4="$U phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_legible_roadmap_contract.py"
```

- **`VL0`** is provider-free: real TEAMHOST projection and admission, contract §6 probes, §8
  containment, and SL-3's falsifier table.
- **`VL1`** is the governed row window on the `pi` route. It records attribution from the proxy
  stream, the verdict, the exec record, the qualification key and usage.
- Secret values and response bodies are not retained.

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

- [ ] EC-PI-1 — Proven by `V1` and IF-0-PI-1. Falsified by any enablement predicate whose removal makes the recording adapter reachable, or by a fixture stream with a non-clean final stop accepted as a verdict. Path-entered control: the real panel-leg selector and spawn path.
- [ ] EC-PI-2 — Proven by `V2`, IF-0-PI-2 and `VL0`. Falsified by any planted ambient surface loading, or by a snapshot or projection change that leaves the qualification key unchanged. Path-entered control: the real profile resolver, projection admission and jailed launch.
- [ ] EC-PI-3 — Proven by `V3`, the route records, the allowlist digests, SL-3's falsifier table, `VL0` and `VL1`. Falsified by any row of that table. Path-entered control: tool descendants enter through the per-launch proxy, and the credential through the real host-side copy and mount.
- [ ] EC-PI-4 — Proven by `plans/evidence/seats-pi/**` and `VL0`/`VL1`. Falsified by an accepted `done-local` row whose window record does not bind the current qualification key. Path-entered control: the readiness-row reducer reads the recorded window result.
- [ ] EC-PI-5 — Proven by `V3`. Falsified by neutralising any attribution, provider-map, alias-key, independence or author-provenance check while its mutation test still passes. Path-entered control: launch config, the proxy stream and the author record enter through the real composition, governed-review, landing-policy and president paths.
