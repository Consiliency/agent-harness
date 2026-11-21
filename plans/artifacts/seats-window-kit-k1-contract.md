# K-1 window-kit contract: one kit for every vendor's row window (r2)

This file is the frozen input of `plans/amendments/seats-FIRSTSEAT-K1-window-kit.md`, which
pins it by SHA-256. No lane edits it. A change is a plan amendment, and results bound to an
earlier digest do not count. It extends IF-0-FIRSTSEAT-2 (principle 5, EC-FIRSTSEAT-6).
`plans/seats-firstseat-containment-contract.md` and
`plans/artifacts/seats-firstseat-interfaces.md` stay byte-identical; §5 lists the only deltas
this contract makes to their interfaces I-11, I-12 and I-15. r2 replaces r1 and records
the owner's decisions of 2026-11-21 (§7 R6, §8, §9.3).

Pinned inputs (content digests, not history). The roadmap is pinned by the plan's
frontmatter only, so a roadmap re-stamp never changes this file.

| Input | sha256 |
|---|---|
| `plans/seats-firstseat-containment-contract.md` (Gemini's supplier contract) | `a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6` |
| `plans/artifacts/seats-firstseat-interfaces.md` | `b50a3a85e2f89d47b0d83f7a7cea117fc52ad04616e6616a7c4064816654ec79` |
| `plans/seats-jailcore-route-contract.md` | `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81` |

Content inputs, which a lane's base tree must hold (checked by content, §12):

- the W1 grant: `OWNER_W1_GRANT_SHA256`, `OWNER_W1_PACKET_SHA256`,
  `OWNER_W1_APPROVED_UNTIL`, `mint_w1_grant`, `owner_w1_grant` and `owner_w1_approved`, with
  the `w1-grant.jsonl` hash-chained journal and the `w1-attempt-<nonce>-<n>.json` witnesses;
- the W1 read-receipt producer, with `_read_receipt_valid` bound to the containment stage;
- the reducer that changes only the window vendor's row;
- `GEMINI_WINDOW_DATA.co_seats` naming `claude`, `codex` and `grok`.

## 1. Ownership

| Part | Owner | Notes |
|---|---|---|
| The kit: `seat_window.py` (which holds the `seat-window` CLI; `cli.py` only delegates to `seat_window.register_parser` and `cli_main`), the `WindowVendorData` schema, `seat_window_supply.py`, the window section of `panel_invoker.py` (§5), and the supplier adapters `seat_window_supply_<vendor>.py` | FIRSTSEAT, through this amendment's lanes | JAILCORE SL-3.5 supplied only the profile-sourced rows. |
| `WindowRows` (the `JailProfile.window` field) | JAILCORE (IF-0-JAILCORE-1) | Unchanged. |
| A vendor's `<VENDOR>_WINDOW_ROWS`, codes, allowlist, credential functions and containment receipts | that vendor's phase | Consumed read-only. |
| A vendor's live row window, its records PR and its readiness row | that vendor's phase | EC-CODEX-4, EC-CLAUDENET-4, EC-GROK-4, EC-PI-4. |
| The Pi revision of this contract (§10.E) | FIRSTSEAT, the kit owner | Starts when IF-0-PI-2 and IF-0-PI-3 are on its base. |
| Gemini's qualification digests | FIRSTSEAT, then TEAMHOST (principle 4) | K-1 moves none (§11). |

No K-1 lane edits a source file owned by CLAUDE, CLAUDENET, CODEX or GROK. Every hook sits in
the kit's own section of `panel_invoker.py` (§5.4).

## 2. Windows, files and record shapes

- **Window ids.** `W1` is Gemini's first window. `row` is every later row window, for every
  vendor, Gemini included. The partition key everywhere is `(vendor, window)`.
- **Private files.** Each is 0600 in the operator's private record root unless stated.

  | File | Written | Content |
  |---|---|---|
  | `window-W1-<context>.json` | by W1, unchanged | the legacy W1 record |
  | `window-row-<vendor>-<context>.json` | by row windows | the row record |
  | `window-run-<vendor>-<context>.json` | once, before the first credentialed launch | the run binding (§6) |
  | `window-exceptions-<vendor>-<context>.json` | once, with the run binding | the exception snapshot (§7 R6) |
  | `window-count-<vendor>-<context>.json` | once, after the board | the launch counts (§9) |
  | `window-attempt-<vendor>-<nonce>-<n>.json` | at each claim | the attempt witness (§8) |
  | `owner-summary-row-<vendor>-<context>.json` (W1 keeps `owner-summary-W1-<context>.json`) | after reduction | the owner summary |

  The sources `leg-*.json`, `window-observation-*.json`, `window-egress-*.json` and
  `window-read-*.json` keep their names.
- **Legacy W1 record.** Exactly the shape the base tree's W1 producer writes. It is never
  rewritten, and it keeps verifying under §7's legacy rules.
- **Row record.** Schema `seat_window.v1`. It holds the common fields, the vendor's two
  fields (`canonical_<vendor>`, `<vendor>_route`), `run_binding_digest` and
  `count_digest`. Its `rows` is exactly `["vendor:<vendor>"]`, and `row_observations` holds
  that one row. `qualification_keys` is the full key of §7 R8.
- **Public exports.** W1 keeps `plans/evidence/seat-qualification/W1.json` in its current
  shape. A row window exports `plans/evidence/seat-qualification/<vendor>-row-<context>.json`,
  which holds that vendor's contexts and its `vendor:<vendor>` row only.

## 3. IF-K1-1 `WindowVendorData`, version 2

The dataclass in `seat_profiles.py` keeps every existing field and gains these, each required:

| Field | Type | Meaning |
|---|---|---|
| `supplier` | `str` | Its module, from §4.2's table. |
| `contract_sha256` | `str` | This vendor's frozen supplier contract. Gemini: the containment contract. Every other vendor: this file. |
| `windows` | `frozenset[str]` | Gemini `{"W1","row"}`; others `{"row"}`. |
| `launch_kinds` | `tuple[str, ...]` | The I-15 kinds the adapter runs, in order. |
| `credential_kinds` | `frozenset[str]` | The kinds that carry a credential. |
| `launch_cap` | `int` | The kit's subject ledger, `len(credential_kinds) + 1` (the board leg). |

`register_window_data` raises `ValueError` for:

- record-field names that lack the vendor's name, or that another vendor already uses;
- `co_seats` other than the plan-tier board's required legs less this leg;
- launch kinds outside I-11, or `measured` or `expired_copy` missing;
- a `credential_kinds` entry outside `launch_kinds`;
- a `launch_cap` other than the rule above;
- a supplier outside §4.2, or a contract digest that is not a digest.

`board_fields` maps every vendor to `{"canonical": "canonical", "leg": "leg_observation"}`.

## 4. IF-K1-2 Supplier protocol, table and discovery

### 4.1 Required names

A supplier module provides all of these:

- `plant_layout`, `build_qualification_input` and `definition_probe`;
- `ContextBinding`, `ContainmentInputs` and `reduce_containment`, which returns I-13's
  closed `ContainmentReduction` for every vendor;
- `arm_watch`, `seed_runtime_plants` and `host_path_map(seat, *, credential)`;
- `launch_command(kind, *, qualification_input, model, plugin_paths)`;
- `credential_mode(kind)` and `copy_transform` (§5.1);
- `stream_facts(raw_stdout)` and `terminal(observation)` (§5.5);
- `scan_secrets(seat)`, `measure_credential_scope(seat)` and `refresh_detected(seat)`;
- `token_endpoint(event)`, `bracket_steps()` and `plugin_forms`.

A missing name gives `window_supplier_unavailable` before any claim or launch.

Gemini's supplier is `seat_window_supply_gemini`. It re-exports `seat_jail_qualification`'s
names and calls the existing Gemini argv and stream helpers, and it edits neither module.

### 4.2 The closed table

`seat_window_supply.SUPPLIERS` is a literal mapping:

| Vendor | Module |
|---|---|
| `gemini` | `seat_window_supply_gemini` |
| `codex` | `seat_window_supply_codex` |
| `claude` | `seat_window_supply_claude` |
| `grok` | `seat_window_supply_grok` |

`load(vendor)` imports only a module named in this table, by
`importlib.import_module("." + name, "phase_loop_runtime")`, and returns `None` when the
module is absent. Gemini's `WindowVendorData` stays registered in `seat_profiles.py`. Every
other module registers its own vendor's data on import. The table is the only dynamic import,
and it has one entry in `tests/test_agent_cli_scratch_inventory_1147.py`.

### 4.3 Discovery

- The CLI's `--vendor` choices are the table's keys, fixed when the parser is built. Parsing
  imports nothing.
- After parsing, `qualify` loads the requested vendor's supplier. `verify`, `export` and
  `matrix` load every table supplier that exists before classifying any record, so R1 sees
  every landed vendor in a fresh process.
- A record whose vendor's supplier has not landed is **unclassified**. It is reported as a
  count, changes no row and fails no partition.

## 5. IF-K1-3 Launch control and board (deltas to I-11, I-12 and I-15)

### 5.1 `WindowLaunchSpec` (I-11) and the credential seam

`WindowLaunchSpec` gains `leg: str = "gemini"`. `window_control_launch` then does this:

- **Jail.** It opens the jail for `profile_for(spec.leg)` through that leg's prepare
  function, with `credential_mode = supplier.credential_mode(spec.kind)`:
  - `none`: no credential is built or delivered. The leg's read-only login checks still run.
  - `live`: today's production delivery.
  - `expired`: the live copy goes through `supplier.copy_transform` before delivery (§10).
- **Proxy.** It starts one proxy per launch, with the vendor's allowlist, or with
  `refuse_all=True` for `none` kinds.
- **Command.** It takes argv from `supplier.launch_command` and stream facts from
  `supplier.stream_facts`.
- **Once.** It runs each launch exactly once: no route retry, no soft-empty retry and no
  fallback rung.
- **Unknown kind.** A kind outside the vendor's `launch_kinds` is refused with `contract_bug`,
  and nothing launches.

For Gemini, the argv, the stream protocol, the help and plugin-validation commands and every
bound digest are unchanged. A prepare function takes the mode as a keyword whose default is
`live`, so every production caller stays byte-identical.

### 5.2 `WindowBoardSpec` (I-12)

It gains `leg: str = "gemini"`. The composition stays the plan tier with its required seats
(§9.3), and the board input is unchanged.

### 5.3 `WindowBoardResult` (I-12)

The fields are `composition`, `board_outcome`, `window_leg`, `canonical`, `staged_read`,
`board_sha256`, `exec_record_sha256`, `tool_receipt_sha256`, `delivered_turn_sha256`,
`leg_exec_records`, `co_seats` and `leg_observation`. `canonical_gemini` and `gemini` are
removed. Every subject field comes from the leg named by `window_leg` alone.

### 5.4 The board-leg bracket

`_WindowBoardLegRuntime` keeps `start`, `finish` and `finalize_proxy`, and gains `leg`, set at
registration. Every call site is in `panel_invoker.py`, in the kit's section:

| Leg | Where | Lane |
|---|---|---|
| gemini | inside `_exec_jailed_gemini_leg` (`window_board=`) | existing, unchanged |
| codex, claude | `_window_bracket(leg, seat, proxy, latch, argv, authorization)`, a context manager in `_parent_infer` around that branch's exec call (`_exec_jailed_codex_leg`, `claude_seat_transport.launch_jailed`) | SL-5 |
| grok | the same helper, around the jailed Grok branch | SL-5 when that branch is on SL-5's base; otherwise GROK SL-2 uses the helper |

`_window_bracket` does nothing unless the registered runtime's `leg` equals `leg`. Inside a
window it calls `start` before the exec call, then `finish` and `finalize_proxy` after it.
The argv it binds is `profile.argv(ArgvInputs(...))` for the inputs that call uses. A seat
with no per-seat proxy (Claude before CLAUDENET SL-2) gives `proxy_unavailable`, and that
window cannot qualify. The Claude bracket wraps the whole `launch_jailed` call, login proof
included, so no Claude file is edited.

### 5.5 Terminal observation

`supplier.terminal(observation)` gives each launch one closed class:

- `completed`;
- `refused_intended`, the vendor's intended expired-credential signature (§10);
- `auth_refused`, a typed auth refusal other than the intended one;
- `stream_incomplete`, `jail_failure`, `proxy_failure`, `timeout` or `other_failure`.

The measured leg passes only on `completed`, and the expired-copy leg only on
`refused_intended`. Any other class makes the fields that need that leg `unavailable`.

### 5.6 I-15 call order

Gemini's order is unchanged. Every other vendor runs the same order, restricted to its
`launch_kinds`. Before each credential-carrying launch, and again before the board, the kit
checks the exception snapshot (§7 R6). If any entry has expired by then, it refuses with
`window_exception_expired` and launches nothing.

## 6. Run binding: what ties a row record to its own run

`window-run-<vendor>-<context>.json` (schema `seat_window_run.v1`) is written once, after the
attempt claim and the composition and before the first credentialed launch, and never
rewritten. It holds:

- `vendor`, `window`, `context_id` and `account_label`;
- `host_digest` (from `_host_digest()`) and `host_class` (from the grant);
- `grant_sha256` and the `attempt` (`nonce`, `number`, `claimed_at`);
- `started_at` and `runtime_digest`;
- `exceptions_sha256` and the `qualification_key` taken at launch (§7 R8);
- `board_input_sha256` and `stage_manifest_sha256`.

The row record's `run_binding_digest` is that file's digest. A row record verifies only if
every one of these holds:

- the run binding names the same vendor, window, context, account and host as the record;
- its host class is `standard`, and its host digest is the grant's host;
- the attempt's witness exists, and wherever the grant journal is readable it holds that
  attempt with the same `claimed_at`;
- `claimed_at ≤ started_at ≤ observed_at ≤ started_at + 7320 s` (the run's outer bound plus
  the kill grace);
- the egress source names the same context;
- the read receipt's `tree_digest` equals the run binding's `stage_manifest_sha256`, and the
  containment binding's;
- the record's key equals the run binding's.

Two records naming one context, or two standard row records for one attempt, fail that
partition. A W1 record relabelled `row` has no row run binding, so it fails. A team context
has no grant claim, so it cannot become standard.

**Provenance.** Every one of these files is operator-writable. The checks defend against the
seat uid, accidental reuse, relabelling and replay of retained files. They do not defend
against an operator who forges the whole set: an owner-writable file with correct hashes is
not proof of origin.

## 7. IF-K1-4 Verification and reduction

- **R1 Vendor identity.** The record is that vendor's when its record fields are all present
  for exactly one registered vendor (two matches or none: unclassified). The record must also
  agree with that vendor in four places:
  - the `leg-*.json` source's `vendor`;
  - the profile digest;
  - the allowlist digest;
  - `contract_sha256 == data.contract_sha256`.

  The module constant `CONTAINMENT_CONTRACT_SHA256` becomes this per-vendor value. Gemini's
  value is unchanged.
- **R2 Window.** `record["window"]` is in `data.windows`, and a row record also passes §6.
- **R3 Partition.** Standard records are partitioned by `(vendor, window)`. Each partition
  needs exactly one valid record, and a failing partition fails only itself. A read error on
  a file whose name names a vendor fails that vendor's row partition. Any other read error is
  unclassified. When both of a vendor's partitions (`W1` and `row`) pass, the later
  `observed_at` sets the row. Team contexts are ignored, as on the base.
- **R4 Write set.** A passing partition for V writes only row `vendor:V`: status, record
  digest, live-evidence digest, profile digest and allowlist digest, all from V's own record.
  The reducer asserts that nothing else changed.
- **R5 Own observation.** `live_evidence_digest` comes from V's `vendor:V` observation, which
  must be `observed` with the record's `exec_record_digest`.
- **R6 Expiry** (owner decision O-1, below). A row record fails if any of these holds:
  - V's own current row has an exception expired at `now`;
  - an entry of its exception snapshot had expired by the end of its run (`observed_at`);
  - a leg or president rung that actually ran (per the exec records and the president
    ledger) is missing from the snapshot.

  The snapshot covers the subject, each composed co-seat and each president rung the ladder
  can reach. For each it records the route (from `seat_route.resolve`) and the exception,
  expiry and renewal record, all from the packaged matrix of the recorded runtime. Each entry
  is judged against the snapshot, so a co-seat whose exception later leaves the matrix keeps
  its recorded expiry. The record still fails if the current matrix shows the same exception
  literal with an expiry earlier than the snapshot's and no renewal record.

  **Legacy W1.** The relaxed rule applies to a W1 record only when all of these hold:
  - the verifying host can read the W1 grant journal and its witnesses, pinned by the
    runtime's `OWNER_W1_GRANT_SHA256`;
  - the journal holds an attempt with `claimed_at ≤ observed_at ≤ claimed_at + 7320 s`;
  - that attempt's `claimed_at` is before `OWNER_W1_APPROVED_UNTIL`.

  The frozen premise is that in the W1 runtime every named exception expires at `_EXPIRES`,
  which equals `OWNER_W1_APPROVED_UNTIL`, so no exception can have expired during a W1 run.
  A test asserts this premise on the W1 base literals. When any condition fails, the base
  tree's conservative rule applies: any currently expired row fails the record.
- **R7 Rows.** A row record's `rows` is `["vendor:V"]`. A legacy W1 record's `rows` and
  `row_observations` must agree with each other, contain `vendor:gemini` and have
  well-formed ids. They are not compared with today's candidate rows, so a later matrix
  change cannot reject W1. Only `vendor:gemini` is read.
- **R8 Full key currency** (EC-JAILCORE-4). A row record's `qualification_keys` holds
  `runtime_digest`, `profile_digest`, `allowlist_digest`, `falsifier_layout`,
  `projection_digest`, `variant` (the Claude transport), `host_identity` and `arch`.
  Verification on the designated host requires every one of these:
  - `profile_digest == jail_profile_digest(leg, arch)`, with `arch == host_arch()`;
  - the allowlist digest equal to `allowlist_ref`'s content digest;
  - `falsifier_layout == falsifier_layout_identity()`, and `execfind_pass_recorded`;
  - `projection_digest` equal to the dependency projection currently admitted for the leg
    (both `None` when none is projected);
  - `variant` equal to the currently resolved variant (Claude:
    `resolve_jailed_claude_transport()`);
  - `host_identity == seat_jail.host_identity()`.

  A mismatch, or verification on another host, gives `window_key_stale`, and the row stays
  `candidate`. A legacy W1 record checks its profile, its allowlist, the binding's projection
  digest and `execfind_pass_recorded`. `runtime_digest` is provenance only.
- **R9 Freshness.** The 30-day age limit and every other base check stay as they are.
- **R10 Export.** `export --vendor V --window row` writes V's contexts and V's row only. W1's
  export keeps its shape.

`verify_records(records, *, vendor="gemini", window="W1")` returns the base shape for a
Gemini W1 set, plus an `unclassified` count.

**Owner decision O-1 (2026-11-21), in the owner's wording:** "Approve, with launch snapshot
(Recommended)". A record fails only on its own vendor's expired exception, or on a co-seat's
exception that had already expired when it ran, recorded at launch and checked against the
run time; Gemini's first window keeps verifying after 12-04; other freshness and key checks
unchanged.

## 8. IF-K1-6 Grants and CLI

**Owner decision O-2 (2026-11-21), in the owner's wording:** "Same binding, 1 attempt
(Recommended)". Each vendor window gets its own grant, bound to host, context, time window,
packet and launch budget. It allows ONE attempt by default, and a second needs the owner's
explicit OK. A wrong host, replayed or corrupted state, or a duplicate run is refused before
any login is used.

**W1 is kept exactly.** Its constants, file, schemas, completion margin, claim order and
refusals are the base tree's. `WINDOW_GRANTS[("gemini","W1")]` names them and changes
nothing.

**Row grants:**

- **The pin.** `WINDOW_GRANTS[(vendor,"row")]` is a reviewed literal,
  `GrantPin(grant_sha256, packet_sha256, approved_until)`. It is `None` (closed) for every
  vendor until a reviewed change citing the owner's approval of that vendor's packet sets it.
  `approved_until` is its own literal, never derived from an exception.
- **The file.** `row-grant-<vendor>.jsonl`, 0600, in the 0700 directory
  `<passwd home>/.local/state/agent-harness/window-admission/`. Its first line has schema
  `seat_window_row_grant.v1` and the fields `host_digest`, `host_class` (`standard`),
  `vendor`, `window` (`row`), `not_before`, `not_after`, `max_attempts`, `packet_sha256`,
  `release_runtime_digest`, `launch_envelope` (§9) and `nonce`.
- **Minting.** `mint_window_grant(vendor, ...)` writes the file on the designated host and
  never overwrites one.
- **Attempts.** `max_attempts` is 1. A value of 2 is valid only when the reviewed change
  states the owner's explicit OK for a second attempt.
- **Journal.** The journal, witnesses, lock and completion margin follow W1's design. The
  witnesses are named `window-attempt-<vendor>-<nonce>-<n>.json`.

**Eligibility is separate from the claim:**

- `window_grant(vendor, window)` only reads. It answers whether the grant can admit an
  attempt now, on this host.
- `claim_window_attempt(vendor, window)` is the atomic claim. Under an exclusive,
  non-blocking lock it re-checks the grant, appends a hash-chained attempt line, fsyncs it and
  writes the witness.
- The claim runs immediately before that vendor's preflight, and so before any login, auth
  probe or launch. Batch selection calls only `window_grant`.

**Refused before any login:**

- a pin that is missing or unset;
- a grant file that is missing, unsafe or corrupt;
- a broken journal chain, or a witness count that disagrees with the journal (replay or
  rollback);
- the wrong host or host class;
- a packet mismatch, or a `release_runtime_digest` other than `runtime_digest()`;
- exhausted attempts, or a claim outside the grant's time window;
- a concurrent duplicate (the lock is held).

Every claim counts, including one later refused by composition or interrupted, and none is
ever released. As with W1, an operator who controls and restores every trusted local store is
outside this guard; the runbook's ledger and the owner's quiet slot cover that case.

**CLI (IF-K1-5):**

- **`qualify`.**
  - `--window` keeps its `W1` default and accepts `W1` and `row`. A bare `qualify` runs
    Gemini `W1`.
  - `qualify --window row --vendor V` runs V's row window.
  - `qualify --window row` with no `--vendor` checks `window_grant` for each table vendor
    whose supplier has landed and whose row is `candidate`. It then claims and runs those
    vendors one after another and returns one result per vendor; one vendor's failure does not
    stop the next.
  - When no vendor is eligible it returns
    `{"status": "candidate", "code": "window_no_eligible_vendor", "vendors": []}` and exits 1.
  - An invalid pair (`W1` with any vendor but Gemini, or a vendor whose supplier has not
    landed) gives `window_vendor_unavailable` before any claim or preflight.
- **Grok actions.** `probe-tools`, `measure-tools` and `status` keep their Grok behaviour.
  With no `--vendor` they use `grok`.
- **`ready --vendor V --window W`** only reads. It reports grant eligibility, each board
  vendor's availability and whether its login file is present, without touching the network or
  using a credential.
- **Reading actions.** `verify`, `export` and `matrix` take `--vendor` and `--window`. With no
  `--record`, they select that partition's own files.

## 9. Launch envelope

### 9.1 Enforcement

- **Subject ledger, enforced.** The kit refuses with `window_launch_cap_reached` any
  credential-carrying subject launch beyond `launch_cap` (5). The board leg counts.
  Credential-free subject starts run once each.
- **Board starts** are bounded by the code that makes them, not by new policy:
  - the plan-tier composition: one seat per vendor;
  - the unjailed soft-empty retry: at most one;
  - the president format re-ask: at most one per rung;
  - agy first-use: at most three operations per board process.
- **Every line item is counted and capped by the grant.**
  - After the board, the kit counts each line item below from its ledger, the exec records,
    the president ledger and the agy receipts.
  - It writes those counts to `window-count-<vendor>-<context>.json`. The record's
    `count_digest` is that file's digest.
  - The verifier refuses a record whose count exceeds the grant's `launch_envelope` for any
    item.
  - The kit refuses at composition when the composed board or the president ladder differs
    from the envelope's assumptions (first rung Fable, one seat per vendor).

The per-context 5 is the kit's subject count. It is not the board's budget, and it is not a
budget for repeated invocations.

### 9.2 Per-context envelope (current routes and ladder)

Model-capable starts:

| Window | Subject | Claude co-seat (seat + Fable president) | Codex | Gemini (seat + agy first-use) | Grok | Total |
|---|---|---|---|---|---|---|
| Gemini | 5 | 1 + 2 | 1 | 0 + 3 | 2 | 14 |
| Codex | 5 | 1 + 2 | 0 | 1 + 3 | 2 | 14 |
| Claude | 5, plus 2 Fable president starts on the same account | — | 1 | 1 + 3 | 2 | 14 |
| Grok | 5 | 1 + 2 | 1 | 1 + 3 | 0 | 13 |

Ancillary line items, capped per context. These are credential-bearing or host-run, but not
model-capable:

| Item | Gemini | Codex | Claude | Grok | Source |
|---|---|---|---|---|---|
| A1 composition auth probes (preflight and board, four vendors each) | 8 | 8 | 8 | 8 | `preflight`, `window_board_launch` |
| A2 jailed Claude login proof (`claude auth status`) | 1 | 1 | 5 | 1 | `_jailed_claude_login_proof`, once per jailed Claude launch |
| A3 agy cold help measurement | 1 | 1 | 1 | 1 | `agy_qualification`, once per board process |
| A4 agy host credential renewal | 5 | 1 | 1 | 1 | before each credentialed Gemini launch |
| A5 Gemini issuer token-info request | 1 | 0 | 0 | 0 | Gemini contract §11 |
| A6 Codex host admission-gate processes (credential-free) | 2 | 16 | 2 | 2 | `codex_admission_gate`, two per Codex prepare |
| A7 credential-free subject starts (help and two refuse-all controls; for Gemini, plugin validation once per planted plugin) | 3 + plugins | 3 | 3 | 3 | §5.6 |

These envelopes assume the current ladder and routes. First-use work can be shared across
contexts. A changed ladder, route or composition voids the envelope: the grant refuses
(§9.1), and a new packet and grant are needed.

### 9.3 Login precondition (owner decision, 2026-11-21)

**The owner's wording:** "Keep the full board (Recommended)". Each vendor window runs the real
four-seat board. The owner keeps all four logins current on the designated host, and windows
are batched per session.

- The composition stays the plan tier with its required seats. Nothing is removed from
  production plan policy (EC-FIRSTSEAT-1).
- The operator runs `ready` before claiming.
- A composition refusal after the claim spends that attempt, with no model starts. A further
  attempt needs the owner's explicit OK (§8).
- A Pi row window needs its own composition, which the Pi revision supplies (§10.E).

## 10. Per-vendor appendices

**The expired-copy rule, for every vendor.**

- The fixture is the live copy with only its unsigned freshness metadata aged. A signed token
  is never edited.
- Where a credential has no such metadata, the secret is replaced by a well-formed value the
  issuer will refuse.
- Each vendor's intended signature (`refused_intended`) is named below. It must be observed
  before any model turn, inside a complete fenced stream, with no allowed token-endpoint
  request and no credential event.

### 10.A Gemini

The supplier contract is the FIRSTSEAT containment contract, unchanged. The window data gains
these fields and nothing else:

- `supplier="seat_window_supply_gemini"`;
- the containment contract's digest;
- `windows={"W1","row"}`;
- `launch_kinds` equal to §15's eight kinds;
- `credential_kinds` equal to the two credentialed controls, measured and expired copy;
- `launch_cap=5`.

### 10.B Codex

**Inputs**, all pre-existing:

- `CODEX_PROFILE` and `CODEX_WINDOW_ROWS` (IF-0-CODEX-1);
- `seat_codex_credential` (IF-0-CODEX-2);
- the `codex` allowlist (IF-0-CODEX-3), whose `measured_and_refused` holds `auth.openai.com`;
- `seat_codex_evidence` (IF-0-CODEX-4) and the `codex_seat_*` codes (IF-0-CODEX-5);
- the receipts `codex-credential-scope`, `codex-refresh-detection` and
  `codex-unlisted-endpoint`.

**Rows.** `CODEX_WINDOW_ROWS`. The runtime rows are the tree rows under `.codex/`, re-rooted
at `provider_config`, plus `provider_config:AGENTS.md`. The definition probe's home row is
`home:.codex/config.toml`.

**Kinds.** `help`, `tree_control`, `runtime_control`, `credentialed_tree_control`,
`credentialed_runtime_control`, `measured` and `expired_copy`. Plugin forms: `("nested",)`.

**Credential seam.** `_prepare_jailed_codex` gains `credential_mode` (default `live`) and
`copy_transform`, as an SL-5 named part of `panel_invoker.py`:

- `none`: the admission gate and the login checks run, but no copy is built or installed, and
  `codex_copy` is `None`.
- `expired`: after the gates, `copy = copy_transform(copy)`, then the copy is installed. The
  margin re-check still reads the live login.

**Expired fixture.** `seat_window_supply_codex.aged_copy` moves `last_refresh` 60 days into
the past and leaves `tokens` unchanged, so `tokens_sha256` is unchanged.

- **Assumption A-C1.** The pinned CLI attempts a refresh before its first model request when
  `last_refresh` is that old.
- SL-6 proves A-C1 provider-free: the real pinned binary runs in the jail under the existing
  provider-free loopback harness. If it does not hold, SL-6 stops.

**`refused_intended`** requires all of these:

- at least one request to `auth.openai.com` denied in the leg window;
- no allowed token-endpoint event;
- no `turn.started`;
- a non-zero exit before the timeout;
- complete fences.

**Facts and outcomes:**

- Stream facts come from `read_tool_record`.
- Credential scope: `scope_problem` on the delivered copy gives `pass`,
  `codex_seat_token_scope_excess` or `unavailable`. There is no issuer call.
- Refresh detection: `tokens_changed` on the seat-home auth file, or an allowed
  token-endpoint request, gives `codex_seat_token_refreshed_in_jail`.
- Bracket rows are ported with the `codex-unlisted-endpoint` targets.
- The outcome vocabularies are the Codex codes plus `pass` and `unavailable`.
- `image_sha256` is the projected runtime's subject digest, and `admission_class` is its
  `seat_admission` class.

### 10.C Claude

**Gate.** IF-0-CLAUDENET-1 to IF-0-CLAUDENET-3 and SL-1's `claude-credential-scope` receipt
are on the base, and OD-3b's default is recorded.

- **Transport.** Only the resolved default transport is qualified. The transport is the key's
  `variant`.
- **Bracket.** As in §5.4, around `launch_jailed`.
  - With the transport's process spawn stubbed at its boundary, SL-7 proves the order: bracket
    start, first provider spawn, quiescence, bracket finish, proxy drain.
  - If that order cannot be shown for the default transport, SL-7 stops.
  - It never edits `claude_seat_transport.py`, `claude_seat_sdk.py`, the SDK worker contract or
    its receipt verifier.
- **Refresh detection.** `seat_claude_containment.refreshed_in_jail(seat_home_fd)`
  (IF-0-CLAUDENET-3, CLAUDENET SL-2.4) gives `claude_seat_token_refreshed_in_jail`.
- **Credential scope.** `pass` when the `claude-credential-scope` receipt exists for the
  installed CLI version and the delivered credential is the token-fd subscription login it
  measured; otherwise `unavailable`. CLAUDENET needs no new interface.
- **Expired fixture.** The token-fd value is replaced by a well-formed refused value.
  `refused_intended` is the login proof's typed refusal before the transport starts.

### 10.D Grok

**Gate.** IF-0-GROK-1 and IF-0-GROK-2 are on the base, the jailed Grok branch is bracketed
(§5.4), and a measured tool surface exists.

- **Delivery.** `stage_grok_seat_credential`; the `none` mode skips it.
- **Refresh detection.** `grok_seat_credential_after` gives
  `grok_seat_token_refreshed_in_jail`.
- **Credential scope.** `pass` when staging succeeded with the subscription marker;
  `grok_seat_credential_refused` otherwise.
- **Expired fixture.** By the expired-copy rule, using the metadata GROK SL-1.2 measures.
  `refused_intended` is the CLI's typed auth refusal before a model turn. If GROK's
  measurement shows no such signature, SL-8 stops.
- **Retries.** A window launch never uses the route's retry.

### 10.E Pi

The Pi revision of this contract adds Pi's supplier and a qualification composition for a board
that composes Pi explicitly (OD-5), with its envelope. FIRSTSEAT owns it. Until it lands, Pi
registers no `WindowVendorData`, as the PI plan already says.

## 11. Pins and requalification

| Pin | Moves | Requalification |
|---|---|---|
| `runtime_digest()` | Yes, with every code lane | None. It is provenance only (R8); a row grant binds the release it names. |
| `jail_profile_digest` (every leg) | No. Window data, seams with `live` defaults and brackets lie outside the owner argv and filter | None. An unchanged `tests/data/seat_profile_digests_jailcore.json` is the falsifier. |
| Allowlist digests, the Gemini containment contract, the FIRSTSEAT interfaces artifact | No | None. |
| Gemini window binding (help, argv, inputs, plant layout, watch, proxy, validator) | No | None. Producer bytes match the golden at a fixed clock. |
| `GEMINI_WINDOW_DATA` | Gains §3's fields and the generic `board_fields` | None; it is not a key part. |
| agy QCI (`seat_qci`, `agy_profile_digest`, validator) | No, provided no lane edits `agy_qualification.py`, `gemini_heartbeat.py`, `seat_jail_qualification.py`, or `terminal_verdict` and its helpers | None. `tests/test_agy_qci.py` decides. |
| EC-EXECFIND-2 passes | No | None. |
| Claude SDK proof inputs | No; nothing in them is edited | None. |
| The W1 grant and admission behaviour | No | None. |
| W1 record verification | Yes: R6's legacy rule, R7's historical rows and the per-vendor contract digest | None. A W1 record that verifies on the base still verifies, subject to R9's age limit and the legacy-rule conditions. |

## 12. Sequencing

- SL-5's base must hold the content inputs listed at the top of this file and main's Grok
  `status` action.
- W1 runs from its installed release. K-1's code lanes should merge after that release is cut.
  A later K-1 release leaves W1 production and admission unchanged, and changes W1 record
  verification only as §11's last row states.
- A roadmap re-stamp (W0's, for example) changes only the plan's frontmatter pin. Whichever
  lands second re-stamps the amendment's frontmatter. `CHANGELOG.md` and
  `seat_launch_references.json` are union-resolved.

## 13. Falsifiers

Each runs through a production path.

- **F1.** A passing Gemini W1 set that has exec records for every co-seat changes only
  `vendor:gemini`.
- **F2.** A record carrying both vendors' field pairs is unclassified. A Codex record with
  Gemini's field names, or the reverse, fails R1.
- **F3.** A Codex record carrying Gemini's profile, allowlist or contract digest fails.
- **F4.** Beside a failing Gemini record, a passing Codex record makes Codex `done-local` and
  leaves Gemini `candidate`; the reverse also holds.
- **F5.** Registration refuses overlapping fields, a self co-seat and a wrong `launch_cap`.
- **F6.** A Codex record that marks `vendor:gemini` observed leaves Gemini unchanged.
- **F7.** Mutation: removing the partition or R4's assertion makes F1, F4 or F6 fail.
- **F8.** Grants:
  - a grant opens only its own `(vendor, window)`;
  - a wrong host, a corrupted journal, a deleted witness, a restored old file, an exhausted
    attempt, a packet or release mismatch, and a concurrent duplicate are each refused before
    `preflight` is called, and the test asserts that no auth function ran;
  - a composition refusal spends the attempt;
  - batch selection claims nothing;
  - W1's base behaviour is unchanged, and a separate Gemini `row` grant behaves the same way.
- **F9.** The subject ledger stops at 5, and no window launch retries. Line-item counts over
  the grant's envelope fail the record. The counters are tested with an unready co-seat,
  Grok's retry, a president format re-ask, and a missing or cold agy receipt.
- **F10.** Golden: at a fixed clock and registry, the W1 producer's records, matrix and export
  bytes, argv and binding digests are equal under K-1.
- **F11.** Each key part going stale fails the record: profile, allowlist, falsifier layout,
  projection, Claude transport (a `print` record with `sdk` now selected), host and arch.
- **F12.** Expiry:
  - an unrelated row that expires after `observed_at` still passes;
  - a co-seat expiry before `observed_at` fails;
  - the subject's own expired row fails;
  - a co-seat whose exception later leaves the matrix keeps its snapshot verdict;
  - a snapshot showing a later expiry than the authority fails;
  - a credentialed launch after a snapshot expiry is refused;
  - legacy W1 passes on both sides of the 2026-12-04 cutoff with its journal, and falls back
    to the base rule without it.
- **F13.** Integrity: each of these fails:
  - a W1 record relabelled `row`;
  - a refreshed `observed_at`;
  - a team record edited to standard;
  - duplicate records for one context;
  - a read receipt from another stage;
  - a run binding for another vendor or host.
- **F14.** W1 survives registry change: a pre-K-1 W1 record and its sources still verify after
  a candidate row is added and after a Grok profile registers.
- **F15.** Fresh-process CLI:
  - `--vendor codex` parses and loads its supplier with no fixture registration;
  - a bare `qualify` runs Gemini W1;
  - invalid pairs are refused before preflight;
  - a mixed `--record` set classifies every landed vendor;
  - an empty batch returns its code;
  - `status --vendor grok` is unchanged.
- **F16.** The Codex seam and terminal classes run through the real `_prepare_jailed_codex`,
  with the provider process stubbed at its spawn boundary:
  - `none` delivers no credential, and `expired` delivers the aged copy;
  - `refused_intended` is told apart from `stream_incomplete`, `jail_failure`,
    `proxy_failure`, `auth_refused` and `timeout`;
  - the production default path is byte-identical.
