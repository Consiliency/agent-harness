# K-1 window-kit contract: one kit for every vendor's row window

This file is the frozen input of `plans/amendments/seats-FIRSTSEAT-K1-window-kit.md`, which
pins it by SHA-256. No lane edits it. A change is a plan amendment, and results bound to an
earlier digest do not count. It extends IF-0-FIRSTSEAT-2 so that one kit serves every
vendor's row window (principle 5, EC-FIRSTSEAT-6). It does not change Gemini's frozen
detail: `plans/seats-firstseat-containment-contract.md` and
`plans/artifacts/seats-firstseat-interfaces.md` stay byte-identical, and §5 below lists the
only deltas this contract makes to their interfaces I-11, I-12 and I-15.

Pinned inputs (content digests, not history):

| Input | sha256 |
|---|---|
| `specs/phase-plans-seats-v1.md` | `b91c98ad7b9097ba411ca21f39cf390878dabac449e59d6fdfd1750915c16a09` |
| `plans/seats-firstseat-containment-contract.md` (Gemini's supplier contract) | `a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6` |
| `plans/artifacts/seats-firstseat-interfaces.md` | `b50a3a85e2f89d47b0d83f7a7cea117fc52ad04616e6616a7c4064816654ec79` |
| `plans/seats-jailcore-route-contract.md` | `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81` |

## 1. Ownership

| Part | Owner | Notes |
|---|---|---|
| The kit: `seat_window.py`, the `seat-window` CLI, the `WindowVendorData` schema, the supplier protocol and registry (`seat_window_supply.py`), the window section of `panel_invoker.py` (`WindowLaunchSpec`, `WindowBoardSpec`, `WindowBoardResult`, `window_control_launch`, `window_board_launch`, `window_board_for`, `_open_window_launch`, `_WindowBoardLegRuntime` and the `_window_*` helpers), and the per-vendor supplier adapters `seat_window_supply_<vendor>.py` | FIRSTSEAT, through this amendment's lanes | IF-0-FIRSTSEAT-2 and EC-FIRSTSEAT-6 are FIRSTSEAT's. JAILCORE SL-3.5 supplied only the profile-sourced rows. |
| `WindowRows` (the `JailProfile.window` field shape) | JAILCORE (IF-0-JAILCORE-1) | Unchanged. |
| A vendor's `<VENDOR>_WINDOW_ROWS` on its profile, its notice codes, allowlist and containment receipts | that vendor's phase (CODEX, CLAUDENET, GROK, PI) | Data only, as contract §1 of the JAILCORE route contract allows. |
| A vendor's live row window, its reviewed records PR and its readiness row | that vendor's phase | EC-CODEX-4, EC-CLAUDENET-4, EC-GROK-4, EC-PI-4. |
| Gemini's qualification digests | FIRSTSEAT, then TEAMHOST (principle 4) | K-1 moves none (§11). |

An adapter is kit code. It consumes the vendor phase's landed interfaces read-only and never
edits a vendor-owned file, except for the one board-leg hook call of §5.4, which is a named
part.

## 2. Windows, files and record shape

- **Window ids.** `W1` is Gemini's first window and is valid only for a record whose window
  data is Gemini's. `row` is every later row window, for every vendor, Gemini included. The
  CLI's `--window` accepts `W1` and `row`.
- **Files.** A W1 record keeps its name, `window-W1-<context>.json`, and its owner summary
  `owner-summary-W1-<context>.json`. A row-window record is `window-row-<vendor>-<context>.json`
  with `owner-summary-row-<vendor>-<context>.json`. The sources (`leg-*.json`,
  `window-observation-*.json`, `window-egress-*.json`, `window-read-*.json`) keep their names;
  they are content-addressed.
- **Record shape.** Schema `seat_window.v1` and the common field set are unchanged. The vendor
  fields stay the two named by `WindowVendorData.record_fields` (`canonical_<vendor>`,
  `<vendor>_route`). A Gemini record built by the pre-K-1 producer is a valid K-1 record,
  field for field. No `vendor` field is added; the vendor is derived (§6, R1).
- **Public exports.** W1: `plans/evidence/seat-qualification/W1.json`, unchanged shape.
  A row window: `plans/evidence/seat-qualification/<vendor>-row-<context>.json`, which holds
  that vendor's contexts and that vendor's `vendor:<vendor>` row only.

## 3. IF-K1-1 `WindowVendorData`, version 2

The dataclass in `seat_profiles.py` keeps every existing field and gains these, each
required at registration:

| Field | Type | Meaning |
|---|---|---|
| `supplier` | `str` | The adapter module's name inside the package, from the closed table of §4.2. |
| `contract_sha256` | `str` | The digest of this vendor's frozen containment-supplier contract. Gemini: the containment contract digest above. Codex: this file's digest (§10.B). |
| `windows` | `frozenset[str]` | Window ids this vendor's records may carry. Gemini: `{"W1", "row"}`. Others: `{"row"}`. |
| `launch_kinds` | `tuple[str, ...]` | The I-15 launch kinds the adapter runs, in order, a subset of I-11's kinds. |
| `launch_cap` | `int` | The most credential-carrying launches the kit itself may start in one context, the board leg included (§9.1). |
| `credential_kinds` | `frozenset[str]` | The launch kinds that carry a credential. |

`register_window_data` additionally refuses, with `ValueError`:

- a `record_fields` value that does not contain the vendor's name, or that another registered
  vendor already uses;
- `co_seats` that contains the vendor itself, or that is not the plan-tier board's required
  legs less this leg (I-12's co-seats: every other leg on the board);
- a `launch_kinds` entry outside I-11's kinds, `measured` or `expired_copy` missing, a
  `credential_kinds` entry outside `launch_kinds`, or a `launch_cap` other than the number of
  `credential_kinds` entries plus one for the board leg;
- a `supplier` outside §4.2's table, or a `contract_sha256` that is not a digest.

`board_fields` stays, and every vendor maps it to the generic result fields of §5.3:
`{"canonical": "canonical", "leg": "leg_observation"}`. Gemini's value changes to that
mapping; nothing digest-bound reads it.

## 4. IF-K1-2 The supplier protocol

### 4.1 Required names

A supplier module provides these names, with I-4 to I-14's shapes where a name already
exists there. Gemini's supplier, `seat_window_supply_gemini`, re-exports
`seat_jail_qualification`'s existing names and wraps the existing Gemini argv and stream
helpers of `window_control_launch` by calling them; it edits neither module's Gemini
behaviour, and `seat_jail_qualification.py` is not edited:

`plant_layout(*, plugin_form, window)`, `build_qualification_input(layout, base)`,
`definition_probe(layout, controls)`, `ContextBinding`, `ContainmentInputs`,
`reduce_containment(inputs)` (returning I-13's closed `ContainmentReduction` shape, whatever
the vendor), `arm_watch(layout, paths, *, kind)`,
`seed_runtime_plants(layout, paths)`, `host_path_map(seat, *, credential)`,
`launch_command(kind, *, qualification_input, model, plugin_paths)`,
`stream_facts(raw_stdout)`, `scan_secrets(seat)`, `measure_credential_scope(delivered)`,
`expired_copy(delivered)`, `token_endpoint(event)`, `bracket_steps()`,
`plugin_forms` (a tuple; `("nested",)` for a vendor with no plugin form).

`seat_window._required_interfaces` checks the supplier for all of them; a missing name is
`window_supplier_unavailable` before any launch. `stream_facts` returns the closed facts
I-11 already names (`model_turn`, `tool_steps`, `subagent_steps`, unknown-event flag) and
nothing else; no output text leaves it.

### 4.2 The closed supplier table

`seat_window_supply.SUPPLIERS` is a literal mapping, fixed by this contract:

| Vendor | Module |
|---|---|
| `gemini` | `seat_window_supply_gemini` |
| `codex` | `seat_window_supply_codex` |
| `claude` | `seat_window_supply_claude` |
| `grok` | `seat_window_supply_grok` |

`seat_window_supply.load(vendor)` imports only a module named in this table, through
`importlib.import_module("." + name, "phase_loop_runtime")`. A module that does not exist yet
yields `None`, and the vendor's window returns `window_supplier_unavailable`. Gemini's
`WindowVendorData` stays registered in `seat_profiles.py`, as today. Every other adapter
module registers its own vendor's `WindowVendorData` on import, and `seat_window` calls
`seat_window_supply.load(vendor)` before it reads a vendor's window data. The table is the only dynamic import
and takes one entry in `tests/test_agent_cli_scratch_inventory_1147.py`'s inventory. Pi gets
a row by a later revision of this contract (§10.E).

## 5. IF-K1-3 Launch control and board (deltas to I-11, I-12 and I-15)

### 5.1 `WindowLaunchSpec` (I-11)

Gains `leg: str = "gemini"`. `window_control_launch(spec)`:

- opens the jail for `profile_for(spec.leg)` through that leg's existing prepare function
  and starts one proxy per launch with `start_proxy(allowlist_id=profile.allowlist_id)`, or
  `refuse_all=True` for credential-free kinds;
- takes its argv from `supplier.launch_command(...)` and its stream facts from
  `supplier.stream_facts`;
- runs each launch **exactly once**: no route retry, no soft-empty retry and no fallback
  rung inside a window launch;
- refuses a kind not in the vendor's `launch_kinds` with `contract_bug`, launching nothing.

For `spec.leg == "gemini"` the argv, the stream protocol, the help and plugin-validation
commands and every bound digest are those of the base tree, byte for byte.

### 5.2 `WindowBoardSpec` (I-12)

Gains `leg: str = "gemini"`, the window leg. The board composition and board input are
unchanged.

### 5.3 `WindowBoardResult` (I-12)

The fields are `composition`, `board_outcome`, `window_leg`, `canonical`, `staged_read`,
`board_sha256`, `exec_record_sha256`, `tool_receipt_sha256`, `delivered_turn_sha256`,
`leg_exec_records`, `co_seats` and `leg_observation`. `canonical_gemini` and `gemini` are
removed. `window_leg` equals `spec.leg`. `canonical`, `exec_record_sha256`,
`delivered_turn_sha256`, the staged-read receipt and `leg_observation` come from the board leg
whose name equals `window_leg`, and from no other leg. `co_seats` is every other leg on the
board, as today.

### 5.4 The board-leg hook

`_WindowBoardLegRuntime` keeps its `start`, `finish` and `finalize_proxy` methods and gains
a `leg` attribute set at registration from `WindowBoardSpec.leg`. The hook is called exactly
as `_exec_jailed_gemini_leg` calls it: `start` after the jail and proxy are ready and before
the provider process starts, `finish` after quiescence, `finalize_proxy` after the proxy
drains. A leg reaches the runtime in one of two ways, and only for its own leg:

- an explicit `window_board=` argument, which `_parent_infer` passes only to the leg whose
  name equals the registered runtime's `leg` (`None` to every other leg); or
- `panel_invoker.window_board_for(leg, authorization)`, which returns the registered runtime
  when its `leg` equals `leg`, and `None` otherwise. It is for launch code that
  `_parent_infer` does not call with keyword arguments of its own.

Call sites:

| Leg | Where | Lane |
|---|---|---|
| gemini | `_exec_jailed_gemini_leg`, `window_board=` | existing; behaviour unchanged |
| codex | `_exec_jailed_codex_leg`, `window_board=` | K-1 kit lane |
| claude | the jailed transport launch, `window_board_for("claude", ...)` | K-1 Claude lane (§10.C) |
| grok | the jailed Grok leg, `window_board_for("grok", ...)` | GROK, in its own launch site (§10.D) |

### 5.5 I-15 call order

Unchanged for Gemini. For another vendor it is the same order restricted to
`launch_kinds`: help; plugin validation only if the vendor has a plugin form and help lists
it; tree and runtime controls; the credentialed controls only when `definition_probe` says
so; measured; expired copy; then the board with `WindowBoardSpec(leg=...)`.

## 6. IF-K1-4 Reducer and verifier: one vendor's record qualifies one vendor's row

These rules make it impossible for one vendor's passing window to change another vendor's
row. Each is a separate falsifier (§13).

- **R1 Vendor identity.** A record's vendor is the unique registered `WindowVendorData`
  whose `record_fields` are all present in it. Registration keeps those names disjoint
  (§3), so at most one matches. The record must also agree with that vendor in four
  independent places: its retained `leg-*.json` source names that vendor; its binding's
  `jail_profile_sha256` equals `jail_profile_digest(data.leg, arch)` for `x86_64` or
  `aarch64` on the verifying runtime; its `allowlist_digest` equals the content digest of
  that vendor's allowlist; and its binding's `contract_sha256` equals `data.contract_sha256`.
  The single module constant `CONTAINMENT_CONTRACT_SHA256` is replaced by the per-vendor
  value; Gemini's value is unchanged.
- **R2 Window id.** `record["window"]` is in `data.windows`.
- **R3 Partition.** Verification and reduction first partition standard records by vendor.
  Each partition is verified alone: exactly one valid standard record for that vendor and
  window. A partition that fails leaves only its own row `candidate`, and never fails or
  satisfies another partition. Team contexts are ignored as today.
- **R4 Write set.** A passing partition for vendor V writes exactly row `vendor:V`: status
  `done-local`, `qualification_record`, `live_evidence_digest`, `profile_digest` and
  `allowlist_digest`, each taken from V's record alone. The reducer asserts that every row it
  changed has id `vendor:V`; any other changed row is an error that discards the reduction.
  President and remote rows never change here.
- **R5 Own observation.** `live_evidence_digest` is computed from V's record's own
  `vendor:V` observation, which must be `observed` with an `exec_record_digest` equal to the
  record's `exec_record_digest`. Every other observation in the record is read for shape
  only and ignored.
- **R6 Expiry.** A record is invalid if V's own row has an exception expired at `now`, or if
  any row's exception had expired at the record's `observed_at` (a co-seat ran on an expired
  exception). An exception that expires after `observed_at` on another vendor's row does
  not invalidate V's record. (This narrows the base tree's rule, which refuses every record
  once any row has expired; open question O-1 in the plan.)
- **R7 Export.** `export --vendor V` writes V's contexts and V's row only; W1's export keeps
  its shape, and its other rows are unchanged from `readiness_rows()`.
- **R8 Key currency.** R1's profile and allowlist checks run against the verifying
  runtime, so a record whose key no longer matches leaves its row `candidate`
  (EC-CODEX-4's, EC-GROK-4's and EC-CLAUDENET-4's "current qualification key").
  `runtime_digest` is recorded, not compared with the current runtime.

`verify_records(records, *, vendor="gemini", window="W1")` keeps its return shape. For a
record set holding only Gemini records it returns exactly what the base tree returns.

## 7. IF-K1-5 CLI

- `--vendor` defaults to none. Its choices are the registered window vendors plus `grok`.
- `probe-tools` and `measure-tools` behave as today; with no `--vendor` they use `grok`.
- `qualify --window W1` with no `--vendor` is Gemini (the base tree's command line).
  `qualify --window row --vendor V` runs V's window. `qualify --window row` with no
  `--vendor` runs every registered window vendor whose row is `candidate` and whose grant is
  open (§8), one after another, each producing its own record: one failing vendor does not
  stop the next (principle 5, EC-FIRSTSEAT-6's one command).
- `verify`, `export` and `matrix` take `--vendor` and `--window`. With no `--record`, they
  select that vendor's own files (§2).

## 8. IF-K1-6 Live grants, closed per vendor

`seat_window.WINDOW_GRANTS` is a literal mapping from `(vendor, window)` to an exclusive
UTC cutoff or `None`. Every entry is `None` except the one the W1-opening change set for
`("gemini", "W1")`. `qualify` returns `window_owner_approval_required` before preflight,
authentication, storage or any launch unless the requested vendor's own entry is open.
Opening one vendor's entry is a reviewed source change that names that vendor and the
owner's approval and edits that entry alone. No entry opens another, and the `row` window
of Gemini is a separate entry from `W1`.

## 9. Launch caps

### 9.1 The rule

Each context keeps a launch ledger of the kit's own credential-carrying launches: the
`credential_kinds` launches and the board leg. Before each, the kit checks that the ledger
plus this launch stays within `launch_cap`; otherwise it stops the context with
`window_launch_cap_reached` and launches nothing more. Credential-free launches are not on
the ledger but run once each (§5.1). Co-seat and president starts belong to the board and
are bounded by its composition, not by this ledger; §9.2 lists them as the envelope.

### 9.2 Per-vendor counts

Counts are provider process starts that can carry a model request. Credential-free help,
plugin validation and the two refuse-all controls are process starts with no credential;
they are listed apart. Renewal and auth-status probes are not launches. One plan-tier board
seat per vendor (the board's required seats: one each for Claude, Codex, Gemini and Grok).

| Window | Window vendor: ledger cap, and envelope | Credential-free starts | Co-seats on the board |
|---|---|---|---|
| Gemini W1 or row | cap 5: up to 2 credentialed controls, measured, expired copy, board leg; plus one issuer POST (Gemini contract §11) | help, plugin validation once per planted plugin, 2 controls | Claude 1 seat and up to 2 president starts; Codex 1; Grok up to 2 (soft-empty retry); agy first-use up to 3 |
| Codex row | cap 5: up to 2 credentialed controls, measured, expired copy, board leg; no issuer call (§10.B) | help, 2 controls | Claude 1 + up to 2 president; Gemini 1 + agy first-use up to 3; Grok up to 2 |
| Claude row | cap 5: up to 2 credentialed controls, measured, expired copy, board seat; envelope 7 on the Claude account with up to 2 president starts on the fable rung | help, 2 controls | Codex 1; Gemini 1 + agy first-use up to 3; Grok up to 2 |
| Grok row | cap 5: up to 2 credentialed controls, measured, expired copy, board leg (no retry inside a window launch, §5.1; the board leg is jailed once GROK registers) | help, 2 controls | Claude 1 + up to 2 president; Codex 1; Gemini 1 + agy first-use up to 3 |
| Pi row | not yet defined (§10.E) | — | — |

Sources: Gemini contract §15 for the launch list and its order; §5.1 here for one start per
launch; the plan-tier policy's required seats; the president ladder, whose fable rung can
start a second fresh transport invocation after a malformed ruling; and
`board_preflight_requalify`, which can start the three agy qualification operations once per
board process. Claude's envelope counts the president because those starts land on the
Claude account the window qualifies.

## 10. Per-vendor appendices

### 10.A Gemini

Gemini's supplier contract is the FIRSTSEAT containment contract, unchanged. Its
`WindowVendorData` gains `supplier="seat_window_supply_gemini"`, the contract digest above,
`windows={"W1","row"}`, `launch_kinds` equal to §15's eight kinds, `credential_kinds` equal
to the two credentialed controls, measured and expired copy, and `launch_cap=5`.

### 10.B Codex (frozen here)

Inputs, all pre-existing: `CODEX_PROFILE` and `CODEX_WINDOW_ROWS` (IF-0-CODEX-1),
`seat_codex_credential` (IF-0-CODEX-2), `seat_egress/codex-allowlist.json` (IF-0-CODEX-3),
`seat_codex_evidence` (IF-0-CODEX-4), the `codex_seat_*` codes (IF-0-CODEX-5) and the
recorded receipts `codex-credential-scope`, `codex-refresh-detection` and
`codex-unlisted-endpoint`.

- **Plant locations and tree rows**: `CODEX_WINDOW_ROWS`, unchanged.
- **Runtime rows**: every tree row whose path starts with `.codex/`, re-rooted at
  `provider_config`, plus `provider_config:AGENTS.md`. `home:.codex/config.toml` is the home
  row the definition probe baselines (Gemini contract §7's rule, applied to this row).
- **Plugin forms**: `("nested",)`. No plugin-validation launch.
- **Launch kinds**: `help`, `tree_control`, `runtime_control`, `credentialed_tree_control`,
  `credentialed_runtime_control`, `measured`, `expired_copy`.
- **Help**: `<runtime>/bin/codex exec --help`, jailed, credential-free, on a refuse-all proxy.
  It yields the help digest.
- **Controls and measured**: `jailed_codex_command` with the control or measured input; the
  measured leg carries the delivered copy that `seat_codex_credential.build_seat_copy` makes
  and the production `codex` allowlist.
- **Stream facts**: from `seat_codex_evidence.read_tool_record` over the leg's stdout; a tool
  record that `tools_ran_code` refuses is `tool_steps = 0`.
- **Credential scope**: measured offline on the delivered copy:
  `seat_codex_credential.scope_problem(copy)` is `None` → `pass`;
  `codex_seat_token_scope_excess` → that code; anything else → `unavailable`. There is no
  issuer call and no bracket token POST.
- **Expired copy**: the delivered copy with the access token's expiry claim moved into the
  past. The copy rules already empty the refresh token. It passes under Gemini contract §10's
  four conditions.
- **Refresh detection**: a credential event is a `seat_codex_credential.tokens_changed`
  result on the seat-home auth file after the leg, or an allowed request to a Codex
  token endpoint (the allowlist's auth host, path `/oauth/token`). Detected →
  `codex_seat_token_refreshed_in_jail`.
- **Bracket rows**: forbidden hosts, forbidden paths, the three inner-tunnel rows, fail-closed
  front and direct-without-proxy, ported with the `codex-unlisted-endpoint` receipt's
  targets. No row requests a token endpoint.
- **Containment outcomes**: `credential_scope` ∈ {`pass`, `codex_seat_token_scope_excess`,
  `unavailable`}; `refresh_detection` ∈ {`pass`, `codex_seat_token_refreshed_in_jail`,
  `unavailable`}; the four config fields as Gemini's.
- **Binding**: `BINDING_FIELDS` unchanged. `image_sha256` is the projected Codex runtime's
  subject digest and `admission_class` its `seat_admission` class.

### 10.C Claude (inputs named; values come from CLAUDENET)

The Claude adapter starts only when its base holds IF-0-CLAUDENET-1 (the profile with
`window=CLAUDE_WINDOW_ROWS` and `allowlist_id="claude"`), IF-0-CLAUDENET-2 (the allowlist)
and IF-0-CLAUDENET-3 (refresh detection and its code), and CLAUDENET SL-3's
`claude-credential-scope` receipt. It qualifies the OD-3b default transport only; the
transport is a key part (EC-JAILCORE-4). Its stream facts and help come from the selected
transport's existing launch path. Credential scope and refresh detection call CLAUDENET's
published measurement and detection functions; this contract adds no Claude rule of its
own. The board-leg hook (§5.4) sits at the jailed transport launch; if placing it needs an
edit inside `claude_seat_transport.py` or `claude_seat_sdk.py`, the lane stops (plan
stop rule) because those files belong to CLAUDE and carry the SDK worker's proof inputs.

### 10.D Grok (inputs named; values come from GROK)

The Grok adapter starts only when its base holds IF-0-GROK-1 and IF-0-GROK-2 (profile
registered with its window rows and its jailed launch site, including the §5.4 hook call)
and a measured tool surface for the installed binary, so `probe-tools` passes on the
designated host. Its help, controls and stream facts come from the jailed Grok launch site.
Credential scope and refresh detection call GROK's IF-0-GROK-1 functions.

### 10.E Pi

Not covered. The PI phase plans no window-kit change, but a Pi seat qualifies on a board
that composes it explicitly (OD-5 default), not on the plan-tier board. A Pi row window
therefore needs a board-composition field in `WindowVendorData`, which is a revision of this
contract and a kit lane, before PI can run its row window.

## 11. Pins and requalification

| Pin | Moves under K-1 | Requalification |
|---|---|---|
| `seat_window.runtime_digest()` | Yes, with every code lane | None. Recorded per record and not compared (R8). A vendor's first row window captures its installed release's value. |
| `jail_profile_digest(leg)` for every leg | No. Window data, adapters and hooks are not part of the owner argv or filter | None. `tests/data/seat_profile_digests_jailcore.json` is unchanged and is the falsifier. |
| Allowlist content digests | No | None. |
| Gemini containment contract digest | No | None. |
| Gemini window binding fields and digests (help, argv, inputs, plant layout, watch, proxy, validator) | No. The Gemini golden is byte-identical | None. |
| `GEMINI_WINDOW_DATA` | Gains §3's fields and the generic `board_fields`; `co_seats` as the W1-1 fix set it | None; not a key part. |
| agy QCI (`seat_qci`, `agy_profile_digest`, `QUALIFICATION_VALIDATOR`) | No, provided no lane edits `agy_qualification.py`, `gemini_heartbeat.py`, `panel_invoker.terminal_verdict` or the prompt and stream helpers it reaches (stop rule) | None. `tests/test_agy_qci.py` decides. The raw agy series' source inventory of changed `.py` files moves, as for any code change; it is not an admission-store key. |
| EC-EXECFIND-2 passes (profile digest, host, falsifier layout) | No | None. |
| Claude SDK proof inputs (the SDK worker contract, `claude_seat_sdk.py`, W0's `request_set`) | No; read only | None. |
| A completed W1's records | No | None: they verify under K-1, which the Gemini golden proves. |
| Codex evidence receipts and its provider-free qualification | No | None. |

## 12. Sequencing with W1 and the work in flight

- The kit lanes start only on a base where the W1 fixes have landed: `GEMINI_WINDOW_DATA`
  names `claude`, `codex` and `grok` as co-seats; `reduce_readiness` changes only
  `vendor:gemini` from a Gemini record; the board writes the `window-read-<digest>.json`
  receipt the verifier reads. They also need the W1-opening change on that base, because it
  edits the same grant function that §8 replaces, and the W0 two-session change merged or
  confirmed not to touch these files.
- W1 runs from an installed release, not from `main`. The kit's code lanes should merge
  after that release is cut, so the release under the owner's W1 approval is the one that
  was reviewed. If one merges earlier, the Gemini golden must pass on it and the release
  owner decides whether the W1 release includes it.
- W1 evidence is never thrown away: §11 holds for W1, R6 can only widen the time a W1
  record stays verifiable, and the golden includes a W1 record set made by the pre-K-1
  producer.

## 13. Falsifiers

Each is a test the plan names; each enters through a production path.

- F1 A passing Gemini W1 set with exec records for every co-seat: only `vendor:gemini`
  changes.
- F2 A Codex record with Gemini's record-field names (or a Gemini record with Codex's) is
  refused by R1's leg-source, profile or contract checks.
- F3 A Codex record whose binding carries Gemini's profile digest, allowlist digest or
  contract digest is refused.
- F4 A set with a passing Codex record and a failing Gemini record: Codex reads
  `done-local`, Gemini stays `candidate`; and the reverse.
- F5 Registering window data whose record fields overlap another vendor's, or whose
  `co_seats` names itself, raises.
- F6 A Codex record that marks `vendor:gemini` observed with a digest leaves the Gemini row
  unchanged.
- F7 Mutation: removing the partition or the R4 assertion makes F1, F4 or F6 fail.
- F8 A grant opened for one vendor does not open `qualify` for another, nor Gemini `row` from
  Gemini `W1`.
- F9 The ledger stops a context at `launch_cap`, and a window launch never retries.
- F10 The Gemini golden: the base tree's records, matrix rows, export bytes, argv and binding
  digests for a fixture W1 set are equal under K-1.
- F11 A record whose profile or allowlist key is no longer current leaves its row
  `candidate`.
- F12 An expired exception on another vendor's row after `observed_at` does not invalidate a
  record; one expired before `observed_at` does; the record's own expired row does.
