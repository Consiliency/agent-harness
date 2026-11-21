---
phase_loop_plan_version: 1
phase: PI
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 2f26635bfcb5119967735cf5d5966f1ce39695a8331d2543eb9e11c07d187018
automation:
  suite_command: ["timeout", "900", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--python", "3.14", "--python-preference", "only-system", "--locked", "python", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_pi_panel_leg.py", "phase-loop-runtime/tests/test_panel_invoker.py", "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py", "phase-loop-runtime/tests/test_panel_per_leg_model_66.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py", "phase-loop-runtime/tests/test_pi_seat_profile.py", "phase-loop-runtime/tests/test_seat_pi_qualification.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_executable_dependency.py", "phase-loop-runtime/tests/test_seat_pi_credential.py", "phase-loop-runtime/tests/test_pi_routed_identity.py", "phase-loop-runtime/tests/test_advisor_board_composition.py", "phase-loop-runtime/tests/test_governed_review.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
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
- `plans/artifacts/seats-pi-route-contract-v2.md`, sha256
  `9f096fefbf6a27d3cb28c4361e894bb13e21b3c4a1b6afda8709b4ccdcb6b2d0`, the "contract", cited by
  section.

The lanes of this plan land the subscription route only. That is one `JailProfile` (`pi`), one
allowlist, one window row and one alias key family. All of them are additions under
IF-0-JAILCORE-1. No JAILCORE code, descend set, resolver, proxy, qualification-key or
route-policy behavior changes. Resource caps come from `seat_profiles.register`.

**Placement boundary.** The placement agreement is pinned to Consiliency/agent-toolkit
`docs/placement-consolidation.md` at external revision 9304a5b9.

- agent-toolkit keeps the Pi agents, toolsets, runner inputs, link and credential proxy.
- The `landlock-exec` (d945fdd0) and `pi-subagents` (`0.84.0`) pins belong to the Pi
  LANE-executor plan, which also owns `launcher.py`.
- This phase edits no placement, `supervised_worker_cli`, runner image or remote-executor
  policy.

**OD-5 (owner, 2026-11-21).** The owner's answer, verbatim: "1. But pi should be able to use
subscription authed providers primarily". The roadmap default otherwise stands. The owner then
answered two follow-ups:

- **OQ-1: "OpenAI subscription".** The primary route is Pi's `openai-codex` sign-in, counted as
  codex. Its credential is the operator's existing Pi sign-in.
- **OQ-2: "Yes, DeepSeek with a cap".** The owner wants a paid DeepSeek route in v1.

The paid route is sequenced after this plan's lanes, as the deferred lane group SL-5 below. It
waits on:

- the owner's cap amount;
- the owner's cap period;
- the owner's key source (the executor's key or a seat-only key);
- a FIRSTSEAT readiness-identity amendment;
- its own plan review.

This is sequencing of the owner's decision, not a change to it. No subscription-route failure
ever selects the paid route.

## Interface Freeze Gates

- [ ] **IF-0-PI-1 (plan-internal) — one-shot leg, witness and verdict.**
  - The command, private directory, witness, cross-check, tools, terminal grammar and fixtures
    are as in contract §7.
  - The deadline is at most `panel_invoker._LEG_TIMEOUT_MAX_S`.
  - Typed ends follow contract §5, in its stated order.
  - Verdict eligibility follows contract §11.
  - No end leads the harness to retry, renew or switch route.
- [ ] **IF-0-PI-2 (plan-internal) — one profile.**
  - Registry key `pi`, defined in `seat_profile_pi.py` and registered by `register_pi()`. That
    function also registers the provider executable `pi` and a `seat_admission` gate.
  - The profile has `vendor="pi"`, `projection="required"`, `allowlist_id="pi"`, a closed
    `ConfigSurface`, the declared reviewer tools, and `variant` from contract §3.
  - Preconditions: the inherited `resource_caps` and `pi_containment` (contract §9).
  - `CredentialDelivery(channel="home_file", scope_evidence=<route record>)`.
  - `ContainmentEvidence` points at `plans/evidence/seats-pi/vl0/containment.json`.
  - `WindowVendorData` has `default=False`.
  - The 12 codes of contract §10 get `seat_jail.NOTICES` rows, a `seat_jail.PI_SEAT_CODES` set
    and `OD10_CLASSES` entries.
- [ ] **IF-0-PI-3 (plan-internal) — route, credential, egress, identity and policy.**
  - Route record, trust anchor (`pi_review_route.PI_ROUTE_SHA256`) and snapshot: contract §3.
  - Request set: contract §4.
  - Copy, claims, mount, ancestors and secrets: contract §8.
  - Egress: contract §6.
  - Attribution, the `PI_PROVIDER_VENDOR` map, `(harness, model)` alias keys, named consumers
    and author provenance: contract §11.

## Lane Index & Dependencies

SL-1 — Leg, witness, verdict and fixtures (lane A)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until SL-1.3

SL-2 — Profile, projection and Pi containment supplier (lane B)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until SL-2.3

SL-3 — Route, credential, identity and policy (lane C)
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes until SL-3.5

SL-4 — Qualification evidence and documentation (SL-docs)
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Leg, witness, verdict and fixtures (lane A)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py`, `phase-loop-runtime/src/phase_loop_runtime/data/pi_seat/witness.mjs`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/tests/data/seats_pi/**`, `phase-loop-runtime/tests/test_pi_panel_leg.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py`, `phase-loop-runtime/tests/test_panel_per_leg_model_66.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: IF-0-PI-1
- **Fixtures.** SL-1.0 freezes `tests/data/seats_pi/`: event streams, witness records,
  synthetic route records and synthetic stores. SL-2 and SL-3 read it and never write it.
- **`pyproject.toml`.** The edit is one package-data line for `data/pi_seat/*`. `phase-loop-runtime/uv.lock` stays untouched: there is no dependency change, and it is a Claude SDK proof input.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.0 | test | — | Record the contract §7 fixtures from the projected binary through the test-only loopback seam, including 401, 403 and 429 with identical bodies and a tool-originated POST. | `V1` |
| SL-1.1 | test | SL-1.0 | Path-enter the argv, stdin, settings and parser. Prove: the terminal grammar; per-event tool names; the witness and proxy count cross-check; the §5 end precedence; distinct ends for identical bodies; effective retries; `--offline`; no `--api-key`; one process; the deadline. | `V1` |
| SL-1.2 | impl | SL-1.1 | Add the disabled adapter and `witness.mjs`. Add the per-launch namespace, proxy and `bridged_to` binding; the selected model in the route environment; the pre-spawn snapshot, allowlist and witness checks; the mount, anchor and secret-registration hooks. Add a disabled seam that calls the `pi_review_route` alias interface, and inventory entries. Edit no `SDK_PROOF_REGIONS` function. | `V1` |
| SL-1.3 | test | SL-1.2, SL-3.4 | Path-enter `_validate_review_board_policy` with the real `pi_review_route`. Refuse a `(model)`-only alias, a Pi `gemini-*` fill and a same-vendor pair. This is the final alias proof before enablement. | `V1` |
| SL-1.4 | test | SL-1.3, SL-2.4, SL-3.6 | Prove the adapter is unreachable for each missing input: profile, record digest, snapshot equality, credential, login record, allowlist, qualification, `pi_containment` record, bridge, witness and stream completion. Then prove the admitted path. Prove that a planted paid route file or cap record changes nothing. | `V1` |
| SL-1.5 | impl | SL-1.4 | Flip `pi` to homebrew with the subscription lane only. Enable it through the leg selector when IF-0-PI-2/3 hold and board config lists `pi`. The default composition is unchanged. | `V1` |

### SL-2 — Profile, projection and Pi containment supplier (lane B)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profile_pi.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_pi_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_pi_seat_profile.py`, `phase-loop-runtime/tests/test_seat_pi_qualification.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_executable_dependency.py`
- **Interfaces provided**: IF-0-PI-2
- **Interfaces consumed**: IF-0-JAILCORE-1/2/3 (pre-existing), IF-0-TEAMHOST-1/2/3 (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | SL-1.0 | Assert the registry grows by exactly `pi` and readiness gains no row beyond Pi's. Assert the real projection: node, the Pi package, the toolset and the witness; `landlock-exec` and `pi-subagents` are excluded. Plant configuration and prove none loads. Assert the 12 codes and classes, `resource_caps`, and the `pi_containment` negative control. | `V2` |
| SL-2.2 | impl | SL-2.1 | Add `seat_profile_pi.py` and `register_pi()`, with the executable, the admission gate, the codes and the window rows. It fails closed until SL-3's record and module exist. | `V2` |
| SL-2.3 | impl | SL-2.2, SL-1.2, SL-3.4 | Add `seat_pi_qualification.py`, the contract §9 supplier. It writes the key-bound pass record from the real projected Pi, mount, proxy and witness against the loopback fixture. | `V2` |
| SL-2.4 | verify | SL-2.3 | Prove each of: digest stability; snapshot-in-variant; projection binding; private per-account state; CA; cleanup; planted-secret detection; that the supplier's record is required. | `V2`, `VL0` |

### SL-3 — Route, credential, identity and policy (lane C)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_pi_credential.py`, `phase-loop-runtime/src/phase_loop_runtime/pi_review_route.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-allowlist.json`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-route.json`, `plans/evidence/seats-pi/route/**`, `phase-loop-runtime/tests/test_seat_pi_credential.py`, `phase-loop-runtime/tests/test_pi_routed_identity.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_governed_review.py`
- **Interfaces provided**: IF-0-PI-3
- **Interfaces consumed**: IF-0-JAILCORE-1/2/3 (pre-existing), OD-5/OQ-1/OQ-2 (pre-existing owner record)
- **Policy ownership.** SL-3 is the single policy and alias owner. It edits only these
  functions:
  - `schema.vendor_family` and `schema.vendor_of_harness`;
  - `composition.board_independence`;
  - `governed_review.select_reviewer_pool`, `governed_planning_gate`, `governed_board_gate`,
    `author_vendor_for_executor` and `author_vendor_for_model`;
  - `president_adapter.seat_for_rung`;
  - the `cli.py` `seat-sandbox pi-login-record` subcommand.

  `runner._phase_author_vendors` is not edited. It keeps every non-empty author, and SL-3.3
  path-enters it.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | evidence | — | Credential-free route work now: source-derived candidate rows, synthetic records and loopback-fixture request paths. No token and no live call. | receipt digest |
| SL-3.2 | test | SL-1.0 | Path-enter the credential module against synthetic stores. Cover: malformed and duplicate entries; the wrong provider or type; the margin at −1 ms, 0 and +1 ms; requested-minimum validity; missing, future or implausible `iat`/`exp`; every claim rule (`iss`, `aud`, `client_id`, scopes, account against the login record); a store at the wrong path; planted ambient credentials. Mutation controls neutralise each check. | `V3` |
| SL-3.3 | test | SL-1.0 | Path-enter the snapshot, the provider map, verdict eligibility over witness fixtures, `board_independence`, `seat_for_rung`, and `runner._phase_author_vendors` into both governed gates. A mixed Claude and unknown-Pi author holds. A known Pi author (synthetic record) reviewed by native codex is refused. | `V3` |
| SL-3.4 | impl | SL-3.2, SL-3.3 | Add `seat_pi_credential.py`, `pi_review_route.py` (with `load_route()` and `PI_ROUTE_SHA256`), the named policy edits and `pi-login-record`. Store no credential or response body. | `V3` |
| SL-3.5 | verify | SL-3.4, SL-1.2, SL-2.4 | Fixture-only VL0: contract §6 probes from real tool descendants, §8 mount and ancestor checks, the redaction scan, installed-package tamper and missing-record tests, and the falsifiers below. | `V3`, `VL0` |
| SL-3.6 | evidence | SL-3.5 | Authenticated, non-billable measurement on the designated seat host. The owner authorizes it after LA-2 and `pi-login-record`. It runs through the production-shaped jailed launch under a private observation allowlist. Record the contract §2 to-measure facts and write `pi-route.json`, `pi-allowlist.json` and `PI_ROUTE_SHA256`. The row window (`VL1`) is the first governed confirmation. A short lifetime, a needed writable copy, an untrusted witness or an inadequate `named`/budget interface is a STOP. | receipt digest |

| Claim | Falsifier (any one fails the claim) |
|---|---|
| Subscription only | Any paid profile, allowlist, window, alias or harness is reachable in production, or a `pi` outcome selects a paid route. |
| Access-only, read-only | The copy carries a non-empty `refresh`, an unlisted field or a second entry; the file is writable; read-back accepts other bytes or a moved ancestor. |
| No in-jail refresh | A token-host request is allowed, or a refresh signal is not reported. |
| Expiry typed | A copy below the margin at spawn launches, or identical bodies on 401 and 429 give the same end. |
| Egress per launch | Any contract §6 probe from a tool descendant succeeds, or a leg uses another leg's namespace. |
| Attribution | A verdict counts without a 2xx, complete, digest-matched witness record and equal proxy counts. |
| Authorship | Unknown Pi authorship is lost in aggregation, or a same-vendor review counts as independent. |
| No secret leak | A planted sentinel reaches any published artifact on any path. |

### SL-4 — Qualification evidence and documentation (SL-docs)

- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`, `plans/evidence/seats-pi/vl0/**`, `plans/evidence/seats-pi/vl1/**`
- **Interfaces consumed**: IF-0-PI-1, IF-0-PI-2, IF-0-PI-3
- **Cross-lane qualification owner.** SL-4 runs `VL0` and `VL1` on the designated seat host.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-4.1 | evidence | SL-1, SL-2, SL-3 | Run the SL-2.3 supplier for the current key and attach `vl0/containment.json`. Set the Pi row to route `jailed`, status `candidate`. Attach the owner's `VL1` record and set `done-local` only when it binds the current qualification key. OD-9 gives `remote-pending`. | `VL0`, `VL1` |
| SL-4.2 | docs | SL-4.1 | Apply `canonical_spec_update` to the three spec surfaces. Record the subscription route, and record that the paid route is wanted in v1 and sequenced as SL-5, with its owner inputs listed. Update the inventory, changelog and catalog. Evidence is metadata-only. | `V4` |
| SL-4.3 | closeout | SL-4.2 | Emit `spec_delta_closeout.v1`. Missing or malformed evidence: `terminal_status=blocked`, `verification_status=blocked`, `blocker_class=contract_bug`. Otherwise `verification_status=passed` and `blocker_class=none`. | `V4` |

## Deferred: SL-5 paid route

SL-5 is not part of this plan's lanes, and nothing in SL-1 to SL-4 registers it. Its design is
contract §13. It gets its own plan amendment and plan review only after all three of these hold:

1. the owner's cap amount and currency, cap period and key source, recorded privately;
2. a FIRSTSEAT amendment to IF-0-FIRSTSEAT-1 giving it its own readiness identity;
3. a verified provider-side enforcement binding.

No billable measurement is authorized before then. When SL-5 exists, its typed refusal is
`pi_seat_spend_cap_missing`.

## Execution Notes

- **Buildable now.** SL-1.0 to SL-1.2, SL-2.1 and SL-2.2, and SL-3.1 to SL-3.4.
- **Then.**
  - SL-2.3 and SL-2.4, then SL-3.5.
  - SL-3.6 once the owner authorizes it.
  - SL-1.3 to SL-1.5, with activation last.
  - SL-4.
- **Single writers.**
  - `panel_invoker.py`: SL-1.
  - `seat_profile_pi.py`, the `register_pi()` call in `seat_profiles.py`, and the additive
    JAILCORE-file entries: SL-2.
  - The named policy functions: SL-3.
- **Stops (contract §12).**
  - S2: recheck at the SL-2 PR base and head; run `claude-sdk-audit` and `audit-order`.
  - S7: the coordinator rules on the Pi-author hold.
  - S1, S3, S4, S5 and S6 are STOPs if reached.
- **Pins.** Count assertions are repository-wide controls, not commit counts. No release is
  dispatched.

## Verification

Run serially after the load/IO precheck.

```bash
U="timeout 900 uv run --quiet --project phase-loop-runtime --group test --python 3.14 --python-preference only-system --locked python -m pytest -p no:cacheprovider -q"
V1="$U phase-loop-runtime/tests/test_pi_panel_leg.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py phase-loop-runtime/tests/test_panel_per_leg_model_66.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py phase-loop-runtime/tests/test_seat_reference_inventory.py"
V2="$U phase-loop-runtime/tests/test_pi_seat_profile.py phase-loop-runtime/tests/test_seat_pi_qualification.py phase-loop-runtime/tests/test_seat_profiles.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_route_contract.py phase-loop-runtime/tests/test_seat_notices.py phase-loop-runtime/tests/test_executable_dependency.py"
V3="$U phase-loop-runtime/tests/test_seat_pi_credential.py phase-loop-runtime/tests/test_pi_routed_identity.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_governed_review.py"
V4="$U phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_legible_roadmap_contract.py"
```

- **`VL0`** is the contract §9 supplier pass plus SL-3.5's fixture-only falsifiers. The generic
  first-use jail pass is not `VL0`.
- **`VL1`** is the governed row window on `pi`. It records the witness-eligible verdict, the
  exec record, the qualification key and usage.
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

- [ ] EC-PI-1 — Proven by `V1` and IF-0-PI-1. Falsified by any enablement predicate whose removal makes the adapter reachable, or by a non-clean final stop accepted as a verdict. Path-entered control: the real panel-leg selector and spawn path.
- [ ] EC-PI-2 — Proven by `V2`, IF-0-PI-2 and `VL0`. Falsified by a planted ambient surface loading, or by a snapshot or projection change that leaves the qualification key unchanged. Path-entered control: the real profile resolver, projection admission, supplier and jailed launch.
- [ ] EC-PI-3 — Proven by `V3`, the route record and its trust anchor, the allowlist digest, SL-3's falsifier table, `VL0` and `VL1`. The paid lane is not registered, and its cap is SL-5's. Falsified by any row of that table. Path-entered control: tool descendants enter through the per-launch proxy, and the credential through the real copy and mount.
- [ ] EC-PI-4 — Proven by `plans/evidence/seats-pi/**` and `VL0`/`VL1`. Falsified by an accepted `done-local` row whose window record does not bind the current qualification key. Path-entered control: the readiness-row reducer reads the recorded window result.
- [ ] EC-PI-5 — Proven by `V1` (SL-1.3) and `V3`. Falsified by neutralising any witness-eligibility, provider-map, alias-key, independence or author-provenance check while its mutation test still passes. Path-entered control: the witness, the proxy stream and the author record enter through the real composition, governed gates, runner aggregation, landing policy and president paths.
