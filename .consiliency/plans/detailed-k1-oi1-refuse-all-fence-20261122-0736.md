---
automation:
  suite_command: "cd phase-loop-runtime && timeout 900 env PYTEST_ADDOPTS= uv run --frozen --group test python -m pytest -p no:cacheprovider -n 0 -q tests/test_seat_window_codex_oi1_fence.py tests/test_seat_window_supply_codex.py tests/test_seat_window_vendor_neutral.py tests/test_seat_window_grants.py tests/test_seat_qualification_host_context.py tests/test_seat_jail_qualification_entry.py tests/test_seat_jail.py tests/test_seat_profile_codex.py tests/test_seat_profiles.py tests/test_seat_reference_inventory.py tests/test_seat_launch_helpers_trusted.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_agy_qci.py"
---

# Detailed plan: K-1 OI-1 refuse-all fence for the Codex expired leg

## Task

Implement contract §10.B "The production expired leg's fence (OI-1, decided)": owner decision
2026-11-22, "Block all its traffic (Recommended)". The governing text is
`plans/artifacts/seats-window-kit-k1-contract.md` r5.2 (sha256
`aa30ce0a2f947fd004476ac62f1c964c57a1e6554cc273e16366c92a2088e967`, agent-harness#2076). The
president's rulings `president-k1-r5-1.md` (B1, B2, §3) and `president-k1-sl6-rulings.md`
(successor-edit bounds) and D1 (`d1-codex-refresh-diagnosis.md`) also apply. This plan
restates none of them. It is a separate kit lane outside the K-1 amendment's lane set, and
its landing lifts SL-6's `codex_expired_leg_unfenced` hold.

Revision r2 applies the president's ruling on agent-harness#2080 of 2026-11-22
(`president-oi1-plan-2080.md`, P1 to P4).

**Erratum (P3).** Contract r5.2 §10.B's reducer bullet, and ruling B2(ii), name
`seat_jail_qualification.reduce_containment`. By the president's ruling of 2026-11-22, that
bullet is corrected by erratum to the Codex row's own reducer,
`seat_window_supply_codex.reduce_containment`, which ruling 6 created. This is a safe
narrowing:
- the owner-approved behaviour is unchanged;
- the frozen file stays unedited.

agent-harness#2076 is not reopened, and the contract pin does not move. SL-9 records the
erratum.

## Research summary

- **Proxy.** `seat_egress_proxy.start_proxy(refuse_all=True)` writes `rules = []`, so
  `allowlist_sha256 = _digest([])`, and every CONNECT is refused before any dial. `named`
  only labels events. `_window_named_refusals` (SL-6) derives the named set from the
  allowlist's probe rows, not from `rules`, so the `("CONNECT","auth.openai.com",None)` denial
  is still reported under refuse-all. Non-named hosts fold to `<other>` (A-C1 run 3).
- **Launch.** In `panel_invoker._open_window_launch`, the non-Gemini branch passes
  `refuse_all=credential_mode == "none"`. `expired` therefore runs the full production rule
  set today (B1's hazard).
- **Reducer.**
  - `seat_window.run_native_window` calls `jailq.reduce_containment(inputs)`, where `jailq` is
    `seat_window_supply.available(vendor)`, the vendor's supplier module. A Codex row
    therefore runs `seat_window_supply_codex.reduce_containment`, which is ruling 6's own
    reducer and is built in SL-6.5.
  - `seat_jail_qualification.reduce_containment` is Gemini-shaped: `_layout_complete` and the
    home row are Gemini's. It is never edited (ruling 6).
- **Digests.** `_VALIDATOR_IMPLEMENTATION_SHA256` and `_WATCH_IMPLEMENTATION_SHA256` hash the
  whole bytes of `seat_jail_qualification.py`, so they stay unmoved because the file is
  unedited.
- **F10.** The Gemini golden uses a stubbed reducer. The `test_seat_jail.py` reducer tests and
  mutants prove the Gemini reducer.
- **Terminal.** SL-6's `terminal` at its pre-r5 head checks `timeout` first and needs
  `FAILURE`. r5.2 replaces that rule for Codex `expired_copy` (P2, and see SL-6 in Dependencies
  & order).

## Step 0: check the reducer (blocking)

At SL-6's landed head, confirm that `seat_window_supply_codex.reduce_containment` is
self-contained. If it calls `seat_jail_qualification.reduce_containment` or any of its binding
helpers, that breaks ruling 6: **stop**.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_codex.py` (modify; successor edit to SL-6's landed file)

- `EXPIRED_LEG_PROXY = "refuse_all"` (add): the single fence declaration in Codex's window
  data, which both the proxy start and the reducer read. It is an optional supplier attribute
  with a default of `None`. The president accepted this reading in the ruling 3(b) precedent.
  `WindowVendorData` is not edited, because `seat_profiles.py` is an `SDK_PROOF_FILES` input.
- SL-6's `codex_expired_leg_unfenced` hold predicate (modify): it fires only while
  `EXPIRED_LEG_PROXY != "refuse_all"`. It is not deleted, so dropping the declaration
  re-arms it.
- `reduce_containment` (modify; SL-6.5's reducer).
  - **With the declaration:**
    - `expired_copy`'s `allowlist_sha256` must equal the single refuse-all value, which is
      `_digest([])`, the value of the `none` kinds, and must differ from the production value;
    - `expired_copy` is left out of the production-allowlist set and out of the bound
      `production_allowlist_sha256`.
  - **Without it:** the production digest is required, as today.
  - **Either way:** refuse-all on `measured` or a credentialed control is `binding_mismatch`.
  - No new vocabulary: no `UnavailableReason`, kind or field.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify; `_open_window_launch` only)

- The non-Gemini `start_proxy(...)` call (modify): `refuse_all = credential_mode == "none"
  or (spec.kind == "expired_copy" and credential_mode == "expired" and
  getattr(supplier, "EXPIRED_LEG_PROXY", None) == "refuse_all")`. A declaration value other
  than `None` or `"refuse_all"` raises `contract_bug`. `allowlist_id` and `named` are
  unchanged. The Gemini branch stays byte-identical.

### `phase-loop-runtime/tests/test_seat_window_codex_oi1_fence.py` (create)

Tests T1 to T4 below.

### `phase-loop-runtime/tests/test_seat_window_supply_codex.py` (modify)

- SL-6's hold test (modify): it asserts the hold with the declaration removed under
  `monkeypatch`, and its absence with the declaration present. No assertion is weakened.

### `CHANGELOG.md` (modify)

An `[Unreleased]` Fixed or Security line. Its Pins line names the moved pins without values.

## Documentation impact

- `CHANGELOG.md`: add the entry above.
- Everything else: none. SL-9 owns the K-1 reconciliation text and records the landing. The
  contract is not edited.

## Pin movement

| Pin | Moves | Why |
|---|---|---|
| `_VALIDATOR_IMPLEMENTATION_SHA256` | no | Its closure is the whole bytes of `seat_jail_qualification.py` (verified), and that file is unedited |
| `_WATCH_IMPLEMENTATION_SHA256` (`watch_sha256`) | no | Same file bytes |
| `proxy_sha256` | no | No proxy file is edited. agent-harness#2077 moves it |
| `runtime_digest()`, `release_identity()` | yes | Any package `.py` edit moves them |
| SDK proof bindings (108) | no | `_open_window_launch` is not in `SDK_PROOF_REGIONS`, and no `SDK_PROOF_FILES` file is edited. Recompute them; any movement is a stop |
| Launch inventory (`seat_launch_references.json`) | no | No new I/O or subprocess primitive |
| `CONTAINMENT_CONTRACT_SHA256` | no | Gemini's contract file is not edited |
| K-1 contract pin (amendment, manifest, `K1_CONTRACT_SHA256`) | no | The contract is not edited |
| Jail-profile digests, allowlist digests, agy QCI | no | Proven by T4 |

**Stale records.** None. No digest that existing Gemini W1 or row records bind moves.
`ROW_GRANTS` is empty, and A-C1 evidence binds r5.2, which does not move.

## Dependencies & order

1. agent-harness#2076 merges. This plan's base merges its head, and the base is recorded in
   the PR.
2. K-1 SL-6 lands (today a local branch, `t3/k1-sl6-codex`, with no PR). It brings:
   - the hold;
   - `_window_named_refusals`;
   - SL-6.5's Codex reducer;
   - (P4) `terminal` on r5.2's Codex `expired_copy` rule, which is stream-defined and holds
     whatever the CLI's exit;
   - `K1_CONTRACT_SHA256` re-pinned to `aa30ce0a…e967`.
3. Step 0.
4. This lane is one PR. T1 to T3 are committed red first, then the implementation.
5. agent-harness#2077 touches disjoint files, and it lands before any live Codex row
   requalification. Whichever lands later rebases, recomputes
   `runtime_digest` and `release_identity` (and `proxy_sha256` for agent-harness#2077), and
   restates them in its PR body.
6. Live requalification of the Codex row, a release and a grant are owner-gated and not
   scheduled here.

## Verification

All checks are provider-free. On a shared host, check headroom first, then run serially with
`-n 0` under `timeout`. Never run a full suite.

- **T1 (red first, then green).**
  - (a) A Codex row `qualify` with launches stubbed returns `codex_expired_leg_unfenced`
    today. With the declaration it passes the hold, and it launches only stubs.
  - (b) Use a recording `start_proxy` stub through `_open_window_launch`, with jail and
    stage stubbed:
    - `expired_copy`: `refuse_all=True`, the production `allowlist_id`, and
      `named == _window_named_refusals(...)`;
    - `measured` and the credentialed controls: `refuse_all=False`;
    - the `none` kinds: `True`.
  - (c) Start the real proxy with `refuse_all=True` and the production named set, using
    `test_seat_egress_allowlist_codex.py`'s fixture:
    - CONNECT `auth.openai.com` gives the named deny;
    - CONNECT `chatgpt.com` gives an `<other>` deny;
    - there are zero allowed events and zero upstream dials;
    - the stream is complete.
  - (d) `seat_window_supply_codex.reduce_containment` with the declaration accepts an
    `expired_copy` binding of `_digest([])` and rejects the production digest.
- **T2 (negatives).**
  - In the Codex reducer, without the declaration (`monkeypatch`), a refuse-all
    `expired_copy` gives `binding_mismatch`, and the production digest is required.
  - With the declaration, refuse-all on `measured` or a credentialed control is still a
    mismatch.
  - A fixture vendor without the declaration keeps production rules for its expired leg, and
    its refuse-all expired binding is rejected.
  - An unknown declaration value gives `contract_bug`.
- **T3 (terminal, r5.2 §10.B).** Feed a fenced Codex `expired_copy` stream to the landed
  `terminal`. The stream has the named `auth.openai.com` deny, `<other>` denies and no allowed
  request, and `tokens_changed` is false.
  - It gives `refused_intended` when the CLI exits `FAILURE`.
  - It gives `refused_intended` when the launch's own deadline stops it with a complete stream.
  - It is not `refused_intended` for:
    - an incomplete stream;
    - an outer `timeout 900` or an external kill;
    - any allowed event;
    - a jail or proxy failure.
  - The lane does not edit `terminal`. A failure here is SL-6's defect and a stop.
- **T4 (Gemini unchanged).**
  - `test_seat_window_gemini_golden_is_byte_identical`.
  - `git diff --exit-code <base> --` on these files: the golden JSON,
    `seat_profile_digests_jailcore.json`, the allowlist files, `test_seat_jail.py`,
    `test_seat_window_vendor_neutral.py` and `test_seat_window_grants.py`.
  - `test_seat_jail.py -k firstseat_teamhost_containment` (W1 reduction and mutants), with
    no assertion edits.
  - `test_agy_qci.py` green with no literal bumped.
  - `git diff --exit-code <base> --
    phase-loop-runtime/src/phase_loop_runtime/seat_jail_qualification.py` is empty.
- **Mutations** (hand-applied, receipts in the PR):
  - M1: drop the `expired_copy` selection, and T1(b) goes red;
  - M2: the Codex reducer accepts refuse-all for any kind, and T2 goes red;
  - M3: the Codex reducer accepts both digests for a fenced leg, and T1(d) goes red;
  - M4: remove the declaration, and T1(a) goes red;
  - M5: let the declaration enable refuse-all for a fixture vendor, and T2 goes red.
- **Gates.**
  - The frontmatter `suite_command`.
  - From the repository root: `PYTHONPATH=phase-loop-runtime/src python3 -m
    phase_loop_runtime.claude_seat_transport audit-order --repo . --base origin/main`.
  - The SDK-binding recompute.
  - A Gate A-shaped wheel tree in CI.

## Scope boundaries and stop rules

The lane changes only the mode selection and the reducer's acceptance of one binding. Stop
and escalate, with no workaround, if any of these would be needed:
- an allowlist, named-set, proxy-rule, `proxy.mjs` or jail-profile change;
- a `seat_profiles.py`, `WindowVendorData` or SDK-region edit;
- a new launch kind, `UnavailableReason` or terminal class;
- a contract edit;
- a Gemini output difference in T4;
- an agy QCI movement;
- an inventory movement;
- any edit to `seat_jail_qualification.py`, or SL-6.5's reducer delegating to it;
- SL-6's landed `terminal` not meeting r5.2's stream-defined rule (T3).

## Resolved escalations

- **E1:** resolved by the president's ruling of 2026-11-22. A Codex row's reducer is the
  Codex one. The erratum is above.
- **E2:** resolved by the same ruling. Under r5.2, a fenced expired leg that ends `FAILURE`,
  or that is stopped at its own deadline with a complete stream, passes on its stream
  conditions. This needs no owner question.

## Execution Policy

- execute: effort=high, reason=containment-sensitive selection and reducer rule; Codex-only files, Gemini untouched

## Acceptance criteria

- [ ] T1(a)–(d) are red at the base and green after, in `tests/test_seat_window_codex_oi1_fence.py`, and T3 passes against SL-6's landed `terminal`.
- [ ] T2 and M1–M5 behave as stated, with the receipts in the PR.
- [ ] The T4 commands pass, and the diff of `seat_jail_qualification.py` is empty.
- [ ] `audit-order` passes, the 108 SDK bindings and `seat_launch_references.json` are unchanged, and `git diff` shows no allowlist, profile or contract change.
- [ ] A Codex row `qualify` no longer returns `codex_expired_leg_unfenced`, and its expired leg's launch binding carries `_digest([])`.
