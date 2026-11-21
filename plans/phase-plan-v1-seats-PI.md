---
phase_loop_plan_version: 1
phase: PI
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: b91c98ad7b9097ba411ca21f39cf390878dabac449e59d6fdfd1750915c16a09
automation:
  suite_command: ["timeout", "900", "uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--python", "3.14", "--python-preference", "only-system", "--locked", "python", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_pi_panel_leg.py", "phase-loop-runtime/tests/test_panel_invoker.py", "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py", "phase-loop-runtime/tests/test_panel_per_leg_model_66.py", "phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py", "phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py", "phase-loop-runtime/tests/test_pi_seat_profile.py", "phase-loop-runtime/tests/test_seat_profiles.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_route_contract.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_executable_dependency.py", "phase-loop-runtime/tests/test_seat_pi_credential.py", "phase-loop-runtime/tests/test_pi_routed_identity.py", "phase-loop-runtime/tests/test_advisor_board_composition.py", "phase-loop-runtime/tests/test_governed_review.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# PI: Pi Review Seat

## Context

This plan covers roadmap Phase 8 (PI) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Acceptance is EC-PI-1 through EC-PI-5, cited by ID only.

**Frozen inputs.** PI consumes `plans/seats-jailcore-route-contract.md` at sha256
`235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81`, including
IF-0-JAILCORE-1, IF-0-JAILCORE-2 and IF-0-JAILCORE-3, and IF-0-TEAMHOST-1, IF-0-TEAMHOST-2
and IF-0-TEAMHOST-3. PI adds exactly one `JailProfile` and exactly one allowlist. It changes
no existing JAILCORE code, descend set, resolver, proxy, qualification-key or route-policy
behavior. Per-seat resource caps come from `seat_profiles.register`'s `resource_caps`
precondition, unchanged.

**Pi runtime input.** The projected Pi package (`@earendil-works/pi-coding-agent` with
`@earendil-works/pi-ai`, 1.6.0 in the current managed release) is the input the credential and
egress work measures. Its store is `auth.json` in the agent directory (`PI_CODING_AGENT_DIR`,
else `~/.pi/agent`). It holds one entry per provider id: `{type: "oauth", access, refresh,
expires, ...provider fields}` or `{type: "api_key", key, env}`. Its OAuth resolver refreshes a
token whose remaining lifetime is under 300 seconds. A version change is a new input and
re-runs SL-3.1.

**Placement boundary.** The 2026-11-06 placement agreement is pinned to
Consiliency/agent-toolkit `docs/placement-consolidation.md` at external revision 9304a5b9.
agent-harness owns placement. agent-toolkit retains the Pi agents, toolsets, runner inputs,
link and credential proxy. The `landlock-exec` (d945fdd0) and `pi-subagents` (`0.84.0`) pins
belong to the separate Pi LANE-executor plan. This phase is only the Pi REVIEW SEAT. It does not
edit `launcher.py`, placement profiles, `supervised_worker_cli`, runner images or
remote-executor policy, and it does not change which credential the Pi executor uses.

**OD-5 (owner, decided 2026-11-21).** The owner accepted the roadmap default and added,
verbatim: "pi should be able to use subscription authed providers primarily". The seat
therefore:

- uses a subscription sign-in, delivered access-only, as its primary lane;
- uses an API-billed key on the routed provider only as a secondary lane, behind the board's
  API-key opt-in and a spend cap;
- uses no aggregator, and changes no plan or production board slot in v1;
- counts as its routed vendor.

The owner has not yet named the provider. OQ-1 and OQ-2 below hold only the provider-bound
evidence, SL-3.1.

**Owner questions (open).**

- **OQ-1.** Which subscription provider is Pi's primary route? The candidates are the projected
  package's own subscription sign-ins: `anthropic`, `openai-codex`, `xai`, `kimi-coding` and
  `meta`. `github-copilot`, `openrouter` and `radius` are aggregators and are excluded. Under
  EC-PI-5, Pi on `anthropic`, `openai-codex` or `xai` counts as claude, codex or grok
  respectively.
- **OQ-2.** Is the API-billed secondary lane wanted in v1? If it is, the owner names its
  provider, whether the key is the executor's existing provider-scoped key or one issued for the
  seat, and the spend-cap amount and period. Until the owner answers, the secondary lane is built
  and tested but stays unbound.

## Interface Freeze Gates

- [ ] **IF-0-PI-1 (plan-internal) — one-shot leg and verdict.**
  - One fresh process per attempt, with no session resume and no mid-run input.
  - The deadline is at most `panel_invoker._LEG_TIMEOUT_MAX_S`, the panel leg cap, and never
    above Pi's 3600-second attempt limit.
  - The command shape is `pi --offline --provider P --model M --thinking E --mode json --print
    --no-session --no-approve --no-context-files --no-mcp --no-skills --no-prompt-templates
    --no-themes --no-extensions --extension TOOLSET --tools TOOLS --`. Prompt bytes arrive on
    stdin. It is bound to the projected `pi` version in the projection digest and proven against
    that binary.
  - `P` and `M` come from the bound route (IF-0-PI-3).
  - `TOOLS` are the reviewer tool names that the projected binary and the pinned agent-toolkit
    `TOOLSET` declare (the 1.6.0 built-ins are `read`, `grep`, `find`, `ls` and `bash`). Any other
    name is admitted only when `TOOLSET` declares it. No ambient discovery.
  - `--api-key` never appears in the argv.
  - Success requires one terminal assistant `message_end`, a board-verdict payload and
    `agent_settled.aborted == false`.
  - A provider authentication rejection is `pi_seat_credential_expired`. Malformed, missing,
    duplicate or post-terminal content is a typed leg failure.
  - No retry resumes a process or renews a credential.
- [ ] **IF-0-PI-2 (plan-internal) — single profile.**
  - One registry entry, key `pi`. It is defined in `seat_profile_pi.py` and registered by
    `register_pi()` from `seat_profiles.py`, following the `seat_profile_codex.py` precedent.
  - `vendor="pi"`, `projection="required"`, `allowlist_id="pi"`, a closed `ConfigSurface`, the
    full declared reviewer tools, and `variant` = the bound route's `provider/auth_type`.
  - `CredentialDelivery(channel="home_file", scope_evidence="plans/evidence/seats-pi/od5-route.json")`.
  - `ContainmentEvidence(credential_scope="plans/evidence/seats-pi/od5-route.json",
    refresh_detection="plans/evidence/seats-pi/vl0/containment.json",
    unlisted_endpoint_refused="plans/evidence/seats-pi/vl0/containment.json", deferred_to=None)`.
  - The private home holds only `.pi/agent/auth.json`, the access-only copy from IF-0-PI-3, and
    `PI_CODING_AGENT_DIR` names that directory.
  - Pi's `WindowVendorData` has `default=False`.
  - Codes, added under IF-0-JAILCORE-1's additive vendor rule as `seat_jail.NOTICES` rows, a
    `seat_jail.PI_SEAT_CODES` set and `OD10_CLASSES` entries:
    - ordinary: `pi_seat_credential_missing`, `pi_seat_od5_evidence_missing`,
      `pi_seat_spend_cap_missing`, `pi_seat_credential_route_mismatch`,
      `pi_seat_token_expiring` and `pi_seat_credential_expired`;
    - security: `pi_seat_secret_in_output`, `pi_seat_token_refreshed_in_jail` and
      `pi_seat_token_scope_excess`.
  - Fix lines recommend a subscription sign-in or an owner record, never an API-key lane.
  - Any missing input resolves degraded through IF-0-JAILCORE-1. No existing code, class or
    window-kit function changes.
- [ ] **IF-0-PI-3 (plan-internal) — route, credential, egress and identity.**
  - **Route.** `PiSeatRoute(provider, auth_type, model)` is bound by
    `plans/evidence/seats-pi/od5-route.json`, schema `pi_seat_route.v1`. The receipt records:
    - provider, `auth_type` (`oauth` or `api_key`) and model;
    - the Pi version and the allowlist content digest;
    - the kept credential field names;
    - the refresh window, the admission margin and the scope ceiling;
    - `spend_cap_required`.
  - **Admitted routes.** `oauth` routes use OQ-1's provider. `api_key` routes are admitted only
    after OQ-2, with `Board.allow_api_key_fallback` set and a spend-cap record present. Any
    aggregator provider id is refused.
  - **Credential copy.** It contains one entry, the bound provider's.
    - `oauth` keeps `type`, `access`, `expires` and the receipt's named non-secret provider
      fields, with `refresh` set to `""`.
    - `api_key` keeps `type` and a literal `key`, and drops `env`. A key starting with `!` or
      containing `$` is refused.
  - **Egress.** `phase_loop_runtime/seat_egress/pi-allowlist.json` (id `pi`, schema
    `phase_loop_seat_egress_allowlist.v1`) holds only the bound route's measured inference rows.
    Its `measured_and_refused` lists that provider's sign-in and token hosts. One route is bound
    at a time: rebinding changes the variant and the allowlist digest, so the qualification key
    changes.
  - **Identity.** `PiRoutedIdentity(harness, requested_model, launch_provider,
    response_provider, response_model)` is accepted only when `harness == "pi"`, both provider
    fields equal the bound provider, and the response model is present.
  - **Vendor counting.** Counting uses the closed `PI_PROVIDER_VENDOR` map: `anthropic`→claude,
    `openai-codex` and `openai`→codex, `xai`→grok, and each other admitted provider to the family
    named in the receipt. An unmapped provider is refused, and the model string is never used.
    `JailProfile.vendor` stays `pi`. Landing aliases use `(harness, model)` keys. A
    same-routed-vendor author/reviewer pair is refused.

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
  Depends on: (none)
  Blocks: SL-1 enablement, SL-4
  Parallel-safe: yes until SL-3.5

SL-4 — Evidence and documentation reducer (SL-docs)
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Leg and verdict (lane A)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py`, `phase-loop-runtime/tests/test_pi_panel_leg.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py`, `phase-loop-runtime/tests/test_panel_per_leg_model_66.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: IF-0-PI-1

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.1 | test | — | Path-enter the exact argv/stdin and JSONL parser against the projected binary. Prove each of: one process; the leg-cap deadline; `--offline`; no session or steering flags; no `--api-key`; the declared tool names; bounded output; board-verdict validation; `pi_seat_credential_expired` for a provider authentication rejection; a typed failure for every malformed terminal sequence. Prove the registered backing is homebrew. An absent flag or event is a typed failure. | `V1` |
| SL-1.2 | impl | SL-1.1 | Add the disabled Pi adapter and parser, plus the inventory entries for its launch site. It cannot be selected while any IF-0-PI-2/3 predicate is false. The leg never injects a key through the board's environment re-injection. | `V1` |
| SL-1.3 | test | SL-3 | Prove the adapter is unreachable when any one of these inputs is missing: profile, credential, route receipt, spend-cap record (`api_key` route only), allowlist, qualification or attribution. Then prove the fully admitted path. | `V1` |
| SL-1.4 | impl | SL-1.3 | Flip Pi to homebrew with lanes `(subscription, api_key)`, subscription first, and api_key only behind `allow_api_key_fallback`. Enable it through the leg selector only when IF-0-PI-2/3 hold and board config lists `pi`. Assert the default plan/production composition is unchanged. | `V1` |

### SL-2 — Profile and projection (lane B)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_profile_pi.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_route_contract.py`, `phase-loop-runtime/tests/test_pi_seat_profile.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_seat_route_contract.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/test_executable_dependency.py`
- **Interfaces provided**: IF-0-PI-2
- **Interfaces consumed**: IF-0-JAILCORE-1/2/3 (pre-existing), IF-0-TEAMHOST-1/2/3 (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Assert that the registry count increases by exactly one and that the only new key is `pi`. Exercise the real projection for the Pi runtime and the explicit toolkit toolset; the closure excludes `landlock-exec` and `pi-subagents`. Plant project and user provider overrides, `models.json`, hooks, skills, MCP and extensions, and prove that none of them load. Assert the nine exact codes and classes, the `resource_caps` precondition and Pi-only window data. Mutating any existing entry or window-kit function fails. | `V2` |
| SL-2.2 | impl | SL-2.1 | Add `seat_profile_pi.py` and its `register_pi()` call. Append only Pi's code and class entries and its `WindowRows`. The profile fails closed until SL-3's route receipt, credential and allowlist exist. | `V2` |
| SL-2.3 | verify | SL-2.2 | Prove each of: profile digest stability; projection-digest binding; private per-account state; the full declared tools; planted-config refusal; terminal planted-secret detection. | `V2`, `VL0` |

### SL-3 — Credential, egress and identity (lane C)

- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_pi_credential.py`, `phase-loop-runtime/src/phase_loop_runtime/pi_review_route.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_egress/pi-allowlist.json`, `plans/evidence/seats-pi/od5-route.json`, `phase-loop-runtime/tests/test_seat_pi_credential.py`, `phase-loop-runtime/tests/test_pi_routed_identity.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_governed_review.py`
- **Interfaces provided**: IF-0-PI-3
- **Interfaces consumed**: IF-0-PI-2, IF-0-JAILCORE-1/2/3 (pre-existing), OD-5 (decided), OQ-1/OQ-2 (SL-3.1 only)
- **Shared surfaces.** `advisor_board/schema.py`, `advisor_board/composition.py` and
  `governed_review.py` are also v11 PANEL/ROUTE surfaces. This lane adds `PiRoutedIdentity` and
  `PI_PROVIDER_VENDOR` and edits only the following functions:
  - `schema.vendor_family`, `schema.vendor_of_harness` and `schema.vendor_of_model`;
  - `composition.board_independence`;
  - `governed_review.select_reviewer_pool` and `governed_review.author_vendor_for_model`.

  If it lands second, it rebases. It never edits the same function concurrently with another
  lane.
- **Credential module.** `seat_pi_credential.py` mirrors `seat_codex_credential.py`.
  - It reads the operator store on the host, owner-only and size-capped.
  - It runs no Pi process and calls no token endpoint.
  - Four ordered checks each return one code or `None`:
    - route match: `pi_seat_credential_route_mismatch`;
    - margin: `pi_seat_token_expiring`;
    - scope ceiling: `pi_seat_token_scope_excess`;
    - spend-cap record, for `api_key` only: `pi_seat_spend_cap_missing`.
  - **Margin.** Admission needs `expires − now ≥ deadline + 300 s (Pi's refresh window) + 300
    s`. A shorter token is never renewed here. The seat waits, reading the store read-only, for
    the owner to renew it, as `seat_credentials.await_login_margin` does, and otherwise
    degrades.
  - **Install.** The copy is installed in a writable private agent directory, because Pi's store
    takes a lock directory beside the file. It is installed mode 0400 if SL-3.1 shows Pi
    completes a turn with it read-only, else 0600. At teardown the copy is read back and must
    match the installed digest.
  - **Spend cap.** The spend-cap record is operator-private, schema `pi_seat_spend_cap.v1`, with
    provider, cap, period, `enforced_by="provider"` and `recorded_at`. The leg records the
    record's digest and Pi's reported usage.

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | evidence | OQ-1 (OQ-2 for an `api_key` route) | For the bound route, derive the request set from the projected package source. Name every request path through a loopback fixture under the TLS-terminating proxy. Measure the token lifetime, the kept fields and whether a read-only copy completes a turn. Write `od5-route.json` and the one `pi-allowlist.json`; the row window is the first live confirmation and fails closed. | receipt digest |
| SL-3.2 | test | — | Path-enter the credential module against fixture stores for every candidate provider: both entry types, other-provider entries, aggregator ids, command/template keys, short and long expiry, extra fields, a changed read-back, a missing spend-cap record, and planted pi-ai provider key/token env names. Mutation controls neutralise each check. | `V3` |
| SL-3.3 | test | — | Path-enter launch config plus terminal provider response. Refuse each of: provider mismatch; an absent response provider or model; model-name vendor inference; an unmapped provider; `(model)`-only alias lookup; a Pi `gemini-*` alias fill; same-routed-vendor independence. | `V3` |
| SL-3.4 | impl | SL-3.2, SL-3.3 | Add `seat_pi_credential.py`, `pi_review_route.py`, the IF-0-PI-3 identity, `PI_PROVIDER_VENDOR`, tuple-key aliases and the independence check. Store no credential or response body in evidence. | `V3` |
| SL-3.5 | verify | SL-2, SL-3.1, SL-3.4 | Re-hash the allowlist and variant into the qualification key. Run the real proxy refusals, the falsifiers below and a redaction scan. | `V3`, `VL0` |

| Claim | Falsifier (any one fails the claim) |
|---|---|
| Subscription first | An `api_key` route resolves without `allow_api_key_fallback`, OQ-2 or a spend-cap record; or the api_key lane is chosen while the subscription lane is admitted. |
| Access-only copy | The seat copy carries a non-empty `refresh`, a second provider entry, an unlisted field, `env`, or a command/template key. |
| No in-jail refresh | A request to a listed token host is admitted. A changed read-back or a refused token-host request is not reported as `pi_seat_token_refreshed_in_jail`. |
| Expiry is typed | A token under the margin launches; a mid-run authentication rejection ends other than `pi_seat_credential_expired`; a retry renews. |
| Egress per route | The real proxy admits an unlisted host, another candidate provider's inference or token host, or a DNS lookup from a tool command. |
| No env or argv secret | Any pi-ai provider key/token env name reaches the seat, or `--api-key` appears in argv. |
| Spend cap | An `api_key` leg runs without a current record for its provider, or its record digest is absent from the leg record. |

### SL-4 — Evidence and documentation reducer (SL-docs)

- **Owned files**: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/review-seats-readiness.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`, `plans/evidence/seats-pi/vl0/**`, `plans/evidence/seats-pi/vl1/**`
- **Interfaces consumed**: IF-0-PI-1, IF-0-PI-2, IF-0-PI-3

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-4.1 | evidence | SL-1, SL-2, SL-3 | On the designated seat host, attach provider-free `VL0` receipts, including `vl0/containment.json`. Set the Pi row's route to `jailed` and its status to `candidate`. Attach the owner's `VL1` row-window record and set `done-local` only when it binds the current qualification key. If the owner records OD-9 for a named host-class falsifier, set `remote-pending` with its interim route. | `VL0`, `VL1` |
| SL-4.2 | docs | SL-4.1 | Apply `canonical_spec_update` to the three required spec surfaces, recording the subscription-first lane in the capabilities card. Update the inventory and changelog, and rescan the docs catalog. Evidence is metadata-only. | `V4` |
| SL-4.3 | closeout | SL-4.2 | Emit `spec_delta_closeout.v1`. Missing or malformed evidence uses `terminal_status=blocked`, `verification_status=blocked` and `blocker_class=contract_bug`. Otherwise record the supported terminal status with `verification_status=passed` and `blocker_class=none`. | `V4` |

## Execution Notes

- **Ordering.**
  - SL-1, SL-2 and SL-3 start in parallel now, because SL-3.2 to SL-3.4 are provider-generic over
    the candidate set.
  - SL-3.1 waits only on OQ-1, and SL-3.5 waits on SL-2 and SL-3.1.
  - SL-1 lands its adapter disabled. SL-1.3 and SL-1.4 resume once SL-3 publishes IF-0-PI-3.
  - SL-4 is terminal.
- **Write ownership.**
  - `panel_invoker.py` is SL-1's single-writer surface, and `seat_profile_pi.py` is SL-2's.
  - The `seat_profiles.py` edit is the `register_pi()` call only.
  - SL-2's only JAILCORE-file edits are the additive Pi entries frozen in IF-0-PI-2.
  - No lane edits `seat_egress_proxy.py`, `seat_credentials.py`, `seat_codex_credential.py`,
    placement or executor modules.
- **Inventory tests.** Lanes that add a launch site or dynamic import run the scratch-inventory
  and trusted-helper tests. SL-3 adds no launch site.
- **Pins.** The exactly-one profile and exactly-one allowlist assertions are repository-wide
  count and path controls, not prescribed commit counts. The plan pins only upstream inputs.
- **Releases.** No release is dispatched, so no post-dispatch back-fill of a tag or workflow
  result applies.

## Verification

Run serially after the repository load/IO precheck. `U` is `timeout 900 uv run --quiet --project phase-loop-runtime --group test --python 3.14 --python-preference only-system --locked python -m pytest -p no:cacheprovider -q`.

```bash
U="timeout 900 uv run --quiet --project phase-loop-runtime --group test --python 3.14 --python-preference only-system --locked python -m pytest -p no:cacheprovider -q"
V1="$U phase-loop-runtime/tests/test_pi_panel_leg.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py phase-loop-runtime/tests/test_panel_per_leg_model_66.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py phase-loop-runtime/tests/test_seat_reference_inventory.py"
V2="$U phase-loop-runtime/tests/test_pi_seat_profile.py phase-loop-runtime/tests/test_seat_profiles.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_route_contract.py phase-loop-runtime/tests/test_seat_notices.py phase-loop-runtime/tests/test_executable_dependency.py"
V3="$U phase-loop-runtime/tests/test_seat_pi_credential.py phase-loop-runtime/tests/test_pi_routed_identity.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_governed_review.py"
V4="$U phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_legible_roadmap_contract.py"
```

- **`VL0`** is provider-free and covers:
  - real TEAMHOST projection and admission;
  - the closed-config and planted-secret falsifiers;
  - SL-3's falsifier table against the real proxy and jail.
- **`VL1`** is the governed row window and records:
  - one real Pi review on the bound subscription route;
  - launch and response attribution, the verdict and the exec record;
  - the current qualification key;
  - usage, plus spend-cap evidence for an `api_key` route.
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

- [ ] EC-PI-1 — Proven by `V1` and IF-0-PI-1. Falsified by any enablement predicate whose removal makes the recording adapter reachable. Path-entered control: each mutation enters through the real panel-leg selector and spawn path.
- [ ] EC-PI-2 — Proven by `V2`, IF-0-PI-2 and `VL0`. Falsified by any planted ambient surface loading, or by a projection pin removed without changing the qualification key. Path-entered control: the real profile resolver, projection admission and jailed launch are used.
- [ ] EC-PI-3 — Proven by `V3` plus OD-5, the route receipt, the sole allowlist digest, SL-3's falsifier table, `VL0` and `VL1`. Falsified by any row of that table, or by the real proxy admitting an unlisted or other-provider request. Path-entered control: the jailed reviewer tool enters through its per-seat proxy, and the credential enters through the real host-side copy.
- [ ] EC-PI-4 — Proven by `plans/evidence/seats-pi/**` and `VL0`/`VL1`. Falsified by an accepted `done-local` row whose window record does not bind the current qualification key. Path-entered control: the readiness-row reducer reads the recorded window result.
- [ ] EC-PI-5 — Proven by `V3`. Falsified by neutralising any attribution, provider-map, tuple-alias or independence check while its mutation test still passes. Path-entered control: launch config and terminal provider response enter through the real composition and governed-review paths.
