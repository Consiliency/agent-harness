# K-1 window-kit contract: one kit for every vendor's row window (r4)

This file is the frozen input of `plans/amendments/seats-FIRSTSEAT-K1-window-kit.md`, which
pins it by SHA-256. No lane edits it. A change is a plan amendment, and results bound to an
earlier digest do not count. It extends IF-0-FIRSTSEAT-2 (principle 5, EC-FIRSTSEAT-6).
`plans/seats-firstseat-containment-contract.md` and
`plans/artifacts/seats-firstseat-interfaces.md` stay byte-identical, and §5 lists the only
deltas this contract makes to their interfaces I-11, I-12 and I-15. r4 adds §15's acceptance
tests and gates to r3 and changes no design text above §15 except the §14 condition. It records
the owner's decisions of 2026-11-21 (§7 R6, §8, §9.3) and does not widen them.

Pinned inputs (content digests, not history). The roadmap is pinned by the plan's frontmatter
only.

| Input | sha256 |
|---|---|
| `plans/seats-firstseat-containment-contract.md` (Gemini's supplier contract) | `a57d46f722e22973f0522a8bc254856e6224d50b1b67893cab2b80522c4942a6` |
| `plans/artifacts/seats-firstseat-interfaces.md` | `b50a3a85e2f89d47b0d83f7a7cea117fc52ad04616e6616a7c4064816654ec79` |
| `plans/seats-jailcore-route-contract.md` | `235f1faded1d7f15d0ff69668b6a451cee7167e6438d258da57257faf7bdae81` |

Content inputs, which a lane's base tree must hold (§12):

- **The W1 grant:** `OWNER_W1_GRANT_SHA256`, `OWNER_W1_PACKET_SHA256`,
  `OWNER_W1_APPROVED_UNTIL`, `W1_COMPLETION_MARGIN_S`, `mint_w1_grant`, `owner_w1_grant` and
  `owner_w1_approved`, with the `w1-grant.jsonl` hash-chained journal and the
  `w1-attempt-<nonce>-<n>.json` witnesses.
- **The W1 read receipt:** its producer, and `_read_receipt_valid` bound to the containment
  stage.
- **The reducer:** it changes only the window vendor's row.
- **Gemini's co-seats:** `GEMINI_WINDOW_DATA.co_seats` names `claude`, `codex` and `grok`.

## 1. Ownership

| Part | Owner |
|---|---|
| The kit: `seat_window.py` (it holds the `seat-window` CLI; `cli.py` delegates), `seat_window_grants.py`, the `WindowVendorData` schema, `seat_window_supply.py`, the kit section of `panel_invoker.py` (§5), and the supplier adapters `seat_window_supply_<vendor>.py` | FIRSTSEAT, through this amendment's lanes |
| `WindowRows` (`JailProfile.window`) | JAILCORE (IF-0-JAILCORE-1), unchanged |
| A vendor's window rows, codes, allowlist, credential functions and receipts; its live window, records PR and readiness row | that vendor's phase |
| The Grok board-leg hook call, inside the Grok leg | GROK SL-3 (§5.4) |
| The Claude transport observer that the hook needs | open: question Q-C in the plan (§5.4) |
| The Pi revision of this contract (§10.E) | FIRSTSEAT |
| Gemini's qualification digests | FIRSTSEAT, then TEAMHOST (principle 4); K-1 moves none |

**Trust boundary.** The designated operator account and the parent process that writes the
private records are trusted. Every check below is independent of the seat uid. The checks
detect inconsistent retained sources, a replayed record and rollback of any one store. An
operator who forges or restores every trusted store is outside the guard, as for W1.

## 2. Windows and files

**Window ids and partitions.** `W1` is Gemini's first window. `row` is every later row
window, Gemini's included. The partition key is `(vendor, window)`.

**Private files.** Each file is 0600 in the operator's private record root, and each is
write-once unless the table says otherwise.

| File | Written | Content |
|---|---|---|
| `window-W1-<context>.json` | by W1, unchanged | the legacy W1 record |
| `window-row-<vendor>-<context>.json` | after reduction | the row record |
| `window-run-<vendor>-<context>.json` | before the first credentialed launch | the run binding (§6.1) |
| `window-exceptions-<vendor>-<context>.json` | with the run binding | the potential-route snapshot (§7 R6) |
| `window-ledger-<vendor>-<context>.jsonl` | append-only, one fsynced line per reservation | the dispatch ledger (§9.1) |
| `window-complete-<vendor>-<context>.json` | once, by the parent, after the board and reduction, or on abort | the completion receipt (§6.2) |
| `window-attempt-<vendor>-<nonce>-<n>.json` | at the claim | the attempt witness (§8) |
| `owner-summary-row-<vendor>-<context>.json` | after reduction | the owner summary |

W1 keeps its own names. The sources `leg-*.json`, `window-observation-*.json`,
`window-egress-*.json` and `window-read-*.json` keep theirs.

**Row record.** Schema `seat_window.v1`. It has the common fields, the vendor's two fields,
`run_binding_digest` and `completion_digest`. `rows` is `["vendor:<vendor>"]`, with one
observation. `qualification_keys` is §7 R8's key. `observed_at` equals the completion
receipt's `completed_at`.

**Exports.** W1 keeps the base export unchanged: `W1.json`, with rows from the matrix at
export time. A row window writes `plans/evidence/seat-qualification/<vendor>-row-<context>.json`,
which holds that vendor's contexts and row only.

## 3. IF-K1-1 `WindowVendorData`, version 2

The dataclass keeps its fields and adds the following:

- `supplier` (§4.2);
- `contract_sha256`: Gemini's containment contract for Gemini, this file for every other
  vendor;
- `windows`: Gemini `{"W1","row"}`, every other vendor `{"row"}`;
- `launch_kinds`, `credential_kinds`;
- `launch_cap`, equal to `len(credential_kinds) + 1`.

`register_window_data` refuses each of these:

- record-field names that lack the vendor's name, or that another vendor already uses;
- `co_seats` that are not the plan tier's required legs less this one;
- launch kinds outside I-11, or without `measured` and `expired_copy`;
- a `credential_kinds` entry outside `launch_kinds`;
- a wrong `launch_cap`;
- a supplier outside the table;
- a contract digest that is not a digest.

`board_fields` is `{"canonical": "canonical", "leg": "leg_observation"}` for every vendor.

## 4. IF-K1-2 Supplier protocol, table and discovery

**4.1 Names a supplier must provide:**

- `plant_layout`, `build_qualification_input`, `definition_probe`;
- `ContextBinding`, `ContainmentInputs`, `reduce_containment` (I-13's closed
  `ContainmentReduction`);
- `arm_watch`, `seed_runtime_plants`, `host_path_map(seat, *, credential)`;
- `launch_command(kind, *, qualification_input, model, plugin_paths)`;
- `credential_mode(kind)`, `copy_transform`;
- `stream_facts(raw_stdout)`, `terminal(observation)`;
- `scan_secrets(seat)`, `measure_credential_scope(seat)`, `refresh_detected(seat)`;
- `token_endpoint(event)`, `bracket_steps()`, `plugin_forms`.

A missing name gives `window_supplier_unavailable` before any claim. Gemini's supplier,
`seat_window_supply_gemini`, re-exports `seat_jail_qualification`'s names and calls the
existing Gemini argv and stream helpers. It edits neither module.

**4.2 The closed table.** `seat_window_supply.SUPPLIERS` maps each vendor to its module:

| Vendor | Module |
|---|---|
| `gemini` | `seat_window_supply_gemini` |
| `codex` | `seat_window_supply_codex` |
| `claude` | `seat_window_supply_claude` |
| `grok` | `seat_window_supply_grok` |

`load(vendor)` imports only a module in this table, by
`importlib.import_module("." + name, "phase_loop_runtime")`. It returns `None` when the module
is absent. Gemini's data stays registered in `seat_profiles.py`. Each other module registers
its own vendor's data on import. This is the only dynamic import, and it has one inventory
entry.

**4.3 Discovery.** The `--vendor` choices are the table's keys, so parsing imports nothing.
`qualify` loads the requested supplier. `verify`, `export` and `matrix` load every table
supplier that exists before they classify anything. A record whose vendor has no landed
supplier is unclassified: it is counted, it changes no row and it fails no partition.

## 5. IF-K1-3 Launch control, board and hooks (deltas to I-11, I-12 and I-15)

### 5.1 Control launches and the credential seam

`WindowLaunchSpec` gains `leg: str = "gemini"`. For a non-Gemini leg, `_open_window_launch`
calls that leg's prepare function with `credential_mode = supplier.credential_mode(kind)`:

- **`none`**: no credential is built or installed, and the read-only login checks still run.
  The proxy is `refuse_all=True`.
- **`live`**: production delivery.
- **`expired`**: the live copy passes through `supplier.copy_transform` before it is
  installed.

The prepare keyword defaults to `live`, so production callers are byte-identical. Control
launches run through `_WindowJailedRun` with `supplier.launch_command`. They never run through
a leg's board exec function: `_exec_jailed_codex_leg` keeps requiring a `CodexSeatCopy`. The
output secret scan uses `supplier.scan_secrets(seat)`, which returns the proxy credential
alone for `none`. The Gemini-only secret read in the control helper is reached only through
Gemini's supplier.

Each launch:

- runs exactly once, with no route retry, no soft-empty retry and no fallback rung;
- refuses a kind outside `launch_kinds` with `contract_bug`;
- reserves its ledger entry before spawning (§9.1).

For Gemini, every argv, protocol and bound digest is unchanged.

### 5.2 Board

`WindowBoardSpec` gains `leg: str = "gemini"`. The composition is the plan tier with its
required seats (§9.3), and the board input is unchanged. `window_board_launch` wraps the
president `invoke` callable it passes to `invoke_president`. Each call reserves one president
start for that rung (§9.1), and `invoke_president` itself is not edited.

### 5.3 `WindowBoardResult`

The result has these fields: `composition`, `board_outcome`, `window_leg`, `canonical`,
`staged_read`, `board_sha256`, `exec_record_sha256`, `tool_receipt_sha256`,
`delivered_turn_sha256`, `leg_exec_records`, `co_seats`, `leg_observation`,
`board_stage_sha256` and `source_attempt`. `canonical_gemini` and `gemini` are removed. Every
subject field comes from the `window_leg` leg alone. `source_attempt` is that leg's exec
record `attempt_id`.

### 5.4 The board-leg hook, in Gemini's order, inside each leg

`_WindowBoardLegRuntime` keeps `start`, `finish` and `finalize_proxy` and gains `leg`.
`_parent_infer` passes `window_board=` only to the leg whose name equals the runtime's `leg`.
Every leg calls the hook exactly where `_exec_jailed_gemini_leg` does:

- `start(...)`, with the exact argv being spawned, after the jail and proxy are ready and
  before the provider spawn;
- `finish(...)`, after quiescence. It closes the end fence, drains the watch and takes the
  delivered-copy and refresh reads while the seat and proxy are still usable. It runs on the
  normal path and on every refused or raised path, before the leg's own teardown.
- `finalize_proxy()`, after the proxy drains and before proxy close.

| Leg | Call site | Owner |
|---|---|---|
| gemini | `_exec_jailed_gemini_leg` | existing, unchanged |
| codex | `_exec_jailed_codex_leg`, a named part | K-1 SL-5 |
| grok | the jailed Grok leg | GROK SL-3. K-1 adds no Grok call site. A K-1 test (F17) fails if the Grok leg has anything other than exactly one hook call site. |
| claude | the jailed transport, which builds and tears down the command internally (`claude_seat_transport`, `claude_seat_print`, `claude_seat_sdk`) | **Interface gap, question Q-C.** It needs an observer passed into `launch_jailed`, with `spawning(argv)` and `before_teardown()` called on every path. No K-1 lane edits those files, so SL-7 waits on Q-C. |

### 5.5 Terminal classes

`supplier.terminal(observation)` returns one of the following: `completed`,
`refused_intended` (§10), `auth_refused`, `not_ready` (the CLI failed before it could attempt
its credential path), `stream_incomplete`, `jail_failure`, `proxy_failure`, `timeout` or
`other_failure`.

- The measured leg passes only on `completed`.
- The expired-copy leg passes only on `refused_intended`.
- Any other class makes the dependent fields `unavailable`.

### 5.6 I-15 order and the reference stage

The order is Gemini's, restricted to `launch_kinds`.

`build_qualification_input` fixes the reference stage manifest digest before any control
runs, and the run binding records it. Every control launch, the measured leg, the
expired-copy leg and the board stage the same qualification input. Each actual stage digest
goes into the ledger line for its launch. A launch whose stage digest differs from the
reference digest fails the context. The board's actual stage digest is `board_stage_sha256`.

## 6. Run binding and completion receipt

### 6.1 Run binding

The run binding is written once, after the claim and the composition and before the first
credentialed launch. It holds:

- `vendor`, `window`, `context_id`, `account_label`;
- `host_digest`, `host_class`, `operator_uid`;
- `grant_sha256` and the `attempt` (`nonce`, `number`, `claimed_at`, `context_id`);
- `started_at`, the latest permitted start (`deadline`), `runtime_digest` and
  `release_identity` (§8);
- `exceptions_sha256`, the `qualification_key` (R8, at launch), `board_input_sha256` and
  `reference_stage_sha256`.

### 6.2 Completion receipt

The trusted parent writes the completion receipt once, after the board and reduction. On an
abort, it writes the receipt with `status: "aborted"` and whatever counts were retained. It
holds:

- `run_binding_digest`, the exact `completed_at`, `board_input_sha256`, `board_stage_sha256`
  and `source_attempt`;
- the file digest of every retained source (`leg-<source_attempt>.json`, observation, egress,
  read, exceptions snapshot, ledger and owner summary);
- the per-item counts and the status.

### 6.3 When a row record verifies

All of these must hold:

1. **The grant.** The run binding's `grant_sha256` is an active or retired pin of this vendor
   and window (§8).
2. **The witness.** The witness file exists and matches the run binding on nonce, attempt,
   `claimed_at`, `context_id`, host and uid.
3. **The journal.** On the designated host, the grant journal holds that attempt with the
   same fields.
   - A journal that is readable but whose chain, count or entry disagrees is
     `window_journal_corrupt`.
   - A journal that cannot be read is `window_journal_unavailable`.
   - Both fail. Done-local verification runs only on the designated host (R8).
4. **The binding.** The record agrees with the run binding on vendor, window, context, account,
   host, `standard` class, uid, `runtime_digest` and key. The record's key also equals the key
   derived from the launch inputs in the leg's exec record.
5. **The snapshot.** The snapshot file hashes to `exceptions_sha256`.
6. **The completion receipt.** It hashes to `completion_digest`, names this run binding, and
   its `status` is `completed`. `observed_at == completed_at`.
7. **The deadline.** `claimed_at ≤ started_at ≤ deadline` and
   `completed_at ≤ started_at + 7320 s`.
8. **The sources.** Every source file's digest equals the receipt's.
   - `source_attempt` equals the exec record's `attempt_id` and the record's `source_attempt`.
   - The egress source names this context.
   - The read receipt's `tree_digest` equals `board_stage_sha256`, which equals
     `reference_stage_sha256` and the containment binding's stage.
   - `board_input_sha256` is the same in the run binding, the receipt, the egress source and
     the record.
9. **The counts.** The ledger's counts equal the receipt's and are within the grant's
   envelope.

Restamping `observed_at` inside the interval breaks check 6. Swapping in another
same-vendor source, attempt or count set breaks check 8 or check 9.

## 7. IF-K1-4 Verification and reduction

### Legacy W1 check

The legacy W1 check is exactly the base tree's `_valid_record` and `_reconcile_sources`,
with the same digest derivations. Only these three changes apply:

1. **R7 rows.** The record's `rows` and `row_observations` are compared with each other, not
   with today's candidates. Each must be unique and well formed, the two must agree, and they
   must include `vendor:gemini`. Only `vendor:gemini` is read.
2. **R6 legacy expiry.** See R6 below.
3. **Contract digest.** The contract digest comes from `data.contract_sha256`, which has the
   same value as before.

No other check is added to W1. There is no new projection, execfind or key check: the base
tree's W1 qualification gate stays where it was, at launch.

### Row records

- **R1 Vendor identity.** Exactly one vendor's field pair matches; two matches or none leave
  the record unclassified. The vendor must also agree with the exec source's `vendor`, the
  profile digest, the allowlist digest and the contract digest.
- **R2.** The window is in `data.windows`, and §6.3 holds.
- **R3 Partitions.** Records are grouped into `(vendor, window)` partitions. Each partition
  needs exactly one valid standard record.
  - Two valid records in one partition fail it with `window_duplicate_records`.
  - A read error fails only the partition its file name names: `window-W1-*` names
    `(gemini, W1)` and `window-row-<v>-*` names `(v, row)`. Any other read error is
    unclassified.
  - When both of Gemini's partitions pass, the later completion time sets the row (for W1,
    `observed_at`). On an exact tie, the `row` partition wins.
  - Team contexts are ignored.
- **R4 Write set.** A partition writes only its own `vendor:V` row, and the reducer asserts
  that nothing else changed.
- **R5.** `live_evidence_digest` comes from the `vendor:V` observation, which carries the
  record's exec digest.
- **R6 Expiry** (owner decision O-1, unchanged). This rule needs two pieces of evidence from
  the run:
  - **The potential-route snapshot.** The trusted launcher writes it after composition, from
    the exact release's packaged matrix and from `seat_route.resolve` output for the subject,
    each composed co-seat and each reachable president rung. Each entry carries the route,
    exception, exclusive expiry and renewal record.
  - **The used entries.** Every credential-bearing dispatch reserves through the ledger
    (§9.1). Before spawn it checks its route and exception against the snapshot and checks
    that `launch_time < expiry`; otherwise it refuses with `window_exception_expired` and does
    not spawn. The ledger line keeps the route and the exact launch time. This covers queued
    legs, Grok's retry and every president rung.

  **Verification.** A row record fails if either of these holds:
  - V's current row has an exception expired at `now` (the base subject rule, kept);
  - a used entry's exception had expired at that entry's `launch_time`.

  Unused rungs and potential-only entries are ignored. A used entry absent from the snapshot
  fails the record. A later change to the matrix does not matter, because the authority is
  the snapshot, bound by `exceptions_sha256` and the run binding's `release_identity`. The
  verifier also recomputes the snapshot from that release's packaged matrix literal when the
  verifying runtime's `release_identity` equals it; otherwise it relies on the binding.
  Renewal records come only from that packaged matrix, never from the snapshot alone.

  **Legacy W1 exception.** The relaxed W1 rule applies only when every one of these holds:
  - the record's host digest and the `standard` class equal the W1 grant's;
  - `OWNER_W1_GRANT_SHA256` equals the journal's first line;
  - exactly one journal attempt and its witness lie within `[claimed_at, claimed_at + 7320 s]`
    of the record's `observed_at`;
  - that attempt's witness names the same nonce;
  - that attempt's `claimed_at ≤ min(grant not_after, OWNER_W1_APPROVED_UNTIL) −
    W1_COMPLETION_MARGIN_S`.

  The base claim gate enforces that last margin, and W1's margin of 10800 s exceeds its outer
  bound of 7320 s. Together with the record's `observed_at < OWNER_W1_APPROVED_UNTIL`, this
  proves the run completed before the cutoff. Every W1-era exception expires at `_EXPIRES`,
  which equals `OWNER_W1_APPROVED_UNTIL`, and a test asserts that equality on the W1 base
  literals. Otherwise, including when the journal is unavailable or two attempts match, the
  base conservative rule applies.
- **R7 Rows.** A row record's rows are `["vendor:V"]`.
- **R8 Key.** At launch the key is `seat_qualification_key.key_for_launch(profile,
  variant=..., allowlist_digest=..., projection=...)` for the actual launch inputs, plus
  `arch = host_arch()` and `runtime_digest`. At verification on the designated host, the same
  function over the current resolved inputs must equal the recorded key, `arch` must equal
  `host_arch()` and `execfind_pass_recorded` must hold. Otherwise the result is
  `window_key_stale`. `runtime_digest` is provenance only.
- **R9.** The 30-day age limit and every other base check are kept.
- **R10 Export.** A row export holds V's contexts and V's row only.

`verify_records` keeps the base shape for a Gemini W1 set and adds an `unclassified` count.

**Owner decision O-1 (2026-11-21), in the owner's wording:** "Approve, with launch snapshot
(Recommended)". A record fails only on its own vendor's expired exception, or on a co-seat's
exception that had already expired when it ran. That exception is recorded at launch and
checked against the run time. Gemini's first window keeps verifying after 12-04, and the
other freshness and key checks are unchanged.

## 8. IF-K1-6 Grants and CLI

**Owner decision O-2 (2026-11-21), in the owner's wording:** "Same binding, 1 attempt
(Recommended)". Each vendor window gets its own grant, bound to host, context, time window,
packet and launch budget. It allows ONE attempt by default, and a second needs the owner's
explicit OK. A wrong host, replayed or corrupted state, or a duplicate run is refused before
any login is used.

**W1 is kept exactly.** Its constants, its file and the base behavior are unchanged. The ledger
of §9 is inactive for W1.

### Release identity, without a circular pin

`release_identity()` is the sha256 of the same files `runtime_digest()` hashes, with one file
excluded: `seat_window_grants.py`. `runtime_digest()` keeps covering every file, for
provenance.

`seat_window_grants.py` holds only literals: `ROW_GRANTS` (the active pin for each vendor)
and `RETIRED_ROW_GRANTS` (every past pin, kept for verification). Each pin is
`(grant_sha256, packet_sha256, approved_until)`. The kit parses the module's AST before it
imports it and refuses anything other than literal assignments.

The order:

1. The packet names `release_identity` R of the candidate release.
2. The operator mints the grant on the designated host. The grant names R, giving digest G.
3. A reviewed change sets `ROW_GRANTS[vendor] = (G, ...)`. That change touches only
   `seat_window_grants.py`, so R does not move.
4. The release is cut and installed.
5. The claim checks `release_identity() == R`.

F8 tests these steps in order.

### The grant file

The file is `row-grant-<vendor>-<nonce>.jsonl`, in
`<passwd home>/.local/state/agent-harness/window-admission/` (directory 0700, file 0600). It
is never overwritten. A later window gets a new file and a new pin; the old pin moves to
`RETIRED_ROW_GRANTS`, and its file, journal and witnesses are never deleted.

Its first line has schema `seat_window_row_grant.v1` and these fields: `host_digest`,
`host_class` (`standard`), `operator_uid`, `vendor`, `window`, `not_before`, `not_after`,
`max_attempts` (1; 2 only when the reviewed pin change states the owner's explicit OK),
`packet_sha256`, `release_identity`, `launch_envelope` (§9.2) and `nonce`.

**Context.** The context a grant binds is OD-12's designated standard context: this host
digest, the `standard` class and this operator uid. The run's `context_id` is generated before
the claim and written into the journal line and the witness.

### Eligibility and claim

- **`window_grant(vendor, window)`** only reads, with no lock and no side effects. It never
  calls preflight, an auth function or a provider.
- **`claim_window_attempt(vendor, window, context_id)`** takes an exclusive non-blocking lock,
  re-reads and revalidates, and refuses corrupt or partial journal state. It then appends the
  hash-chained line, fsyncs and writes the witness. All of this happens before preflight and
  so before any login.

These are refused before any login:

- a missing pin, file or safe directory;
- a corrupt or partial journal;
- a broken chain, or a witness that disagrees with the journal;
- the wrong host, class or uid;
- a packet or release-identity mismatch;
- exhausted attempts;
- a claim outside the time window or past the deadline (`not_after`, minus the completion
  margin);
- a concurrent claim, because the lock is held.

Every claim counts and none is released.

### CLI (IF-K1-5)

- `--window` defaults to `W1`. A bare `qualify` is Gemini W1.
- `qualify --window row --vendor V` runs one vendor.
- `qualify --window row` with no vendor runs a batch.
  - Candidates are the landed-supplier vendors whose row is not `done-local` under a verified
    reduction of this host's retained records, and whose `window_grant` is true.
  - Selection claims nothing. Each vendor is claimed just before its own preflight.
  - The output lists one code per vendor. The exit is 0 only when every attempted vendor wrote
    a record (`window_review_required`). It is 1 otherwise, including the empty case
    `window_no_eligible_vendor`.
- `W1` with any vendor other than Gemini, or a vendor without a landed supplier, gives
  `window_vendor_unavailable` before any claim.
- `probe-tools`, `measure-tools` and `status` keep their Grok behavior, with `grok` as the
  default vendor.
- `ready --vendor V --window W` only reads: grant eligibility, availability and login-file
  presence.
- `verify` and `export` with no `--vendor` act on Gemini W1, as on the base.
- `matrix` with no `--record` is the base unscoped matrix. `matrix --record …` reduces every
  partition, and `--vendor` and `--window` narrow it.

## 9. Launch envelope, enforced before dispatch

### 9.1 The dispatch ledger

Inside a row window, a context variable holds the ledger, and every start reserves before it
happens. Reservations are atomic across threads, because board legs run concurrently. Each
reservation is appended and fsynced to `window-ledger-<vendor>-<context>.jsonl` before the
start, so a partial run keeps its counts. A start that ends without an exec result still
counts.

There are two enforcement points, both in kit-owned code:

- **The provider boundary.** `panel_invoker.launch_provider` and `run_provider` reserve one
  unit of the current scoped item, which the kit sets around the call it makes. A start
  inside a window with no scoped item is refused (`window_unbudgeted_start`).
- **Kit call sites**, for starts that bypass that boundary. Each reserves at the call site:

  | Start | Where it reserves |
  |---|---|
  | the Claude seat | at the jailed Claude dispatch in `_parent_infer` |
  | the Claude login proof | at the jailed Claude dispatch in `_parent_infer` |
  | each president rung call, the format re-ask included | the `invoke` wrapper (§5.2) |
  | each subject launch | the control launcher |
  | agy first-use | 3 reserved before `board_preflight_requalify` |
  | the cold agy help measurement | 1 reserved before `board_preflight_requalify` |

A refused reservation spawns nothing and raises a typed refusal, and the leg or rung ends
typed. **President fallback is refused:** the envelope budgets only Fable, so a descent to any
other rung inside a window fails its reservation. The president then fails typed, the board
does not terminate, and the row stays `candidate`. Before any work, the kit checks the
composed board and ladder against the envelope's assumptions (one seat per vendor, first rung
Fable). W1 authorization stays separate and unchanged.

### 9.2 The per-context envelope

The grant's `launch_envelope` holds the per-item caps below. They imply 14 model-capable starts
for a Gemini, Codex or Claude context, and 13 for a Grok context.

**Model-capable starts:**

| Item | Gemini | Codex | Claude | Grok |
|---|---|---|---|---|
| Subject (credentialed controls up to 2, measured, expired copy, board leg) | 5 | 5 | 5 | 5 |
| Claude seat | 1 | 1 | — | 1 |
| Fable president (one call plus one format re-ask) | 2 | 2 | 2 | 2 |
| Codex seat | 1 | — | 1 | 1 |
| Gemini seat | — | 1 | 1 | 1 |
| Grok seat (two starts with the soft-empty retry) | 2 | 2 | 2 | — |
| agy first-use operations | 3 | 3 | 3 | 3 |
| **Total** | **14** | **14** | **14** | **13** |

Gemini's subject count includes its board leg, so it has no separate Gemini seat.

**Ancillary items.** The unit is one actual subprocess or one request.

| Item | Gemini | Codex | Claude | Grok |
|---|---|---|---|---|
| A1 auth probe subprocesses (cached gate results reserve nothing) | ≤8 | ≤8 | ≤8 | ≤8 |
| A2 Claude login proofs | 1 | 1 | 5 | 1 |
| A3 cold agy help | 1 | 1 | 1 | 1 |
| A4 agy renewal attempts (each started renewal, successful or not) | 5 | 1 | 1 | 1 |
| A5 Gemini issuer request | 1 | 0 | 0 | 0 |
| A6 Codex admission-gate processes (both `exec --help` and `features list` count) | 2 | 16 | 2 | 2 |
| A7 credential-free subject starts | 3 + plugins | 3 | 3 | 3 |

A grant whose envelope is smaller than a context needs is refused at the first reservation
that would exceed it. A changed ladder, route or composition fails the pre-work check.

### 9.3 Logins (owner decision, 2026-11-21)

**The owner's wording:** "Keep the full board (Recommended)". Each vendor window runs the real
four-seat board. The owner keeps all four logins current on the designated host, and windows
are batched per session.

The board still requires all four logins, as approved. The operator runs `ready` before
claiming. A composition refusal after the claim spends the attempt. Pi's composition belongs
to the Pi revision (§10.E).

## 10. Per-vendor appendices

**The expired-copy rule.** Only unsigned freshness metadata is aged, and a signed token is
never edited. A credential without such metadata gets a well-formed refused value instead.
`refused_intended` is that vendor's signature below, observed before any model request, in a
complete fenced stream, with no allowed token-endpoint request and no credential event.

**10.A Gemini.** Its contract is the FIRSTSEAT containment contract, unchanged. Its window
data:

- `seat_window_supply_gemini`;
- its contract digest;
- `{"W1","row"}`;
- §15's eight kinds;
- the four credential kinds;
- `launch_cap` 5.

**10.B Codex.**

- **Inputs:** IF-0-CODEX-1 to IF-0-CODEX-5, and the `codex-credential-scope`,
  `codex-refresh-detection` and `codex-unlisted-endpoint` receipts.
- **Rows:**
  - `CODEX_WINDOW_ROWS`;
  - runtime rows, the `.codex/` tree rows re-rooted at `provider_config`, plus
    `provider_config:AGENTS.md`;
  - home row `home:.codex/config.toml`.
- **Kinds:** `help`, the two controls, the two credentialed controls, `measured` and
  `expired_copy`. Plugin forms: `("nested",)`.
- **The seam:** `_prepare_jailed_codex(credential_mode, copy_transform)`, an SL-5 named
  part.
  - `none` builds and installs no copy.
  - `expired` applies `aged_copy` to the production copy, then installs it. The margin
    re-check reads the live login.
- **The fixture:** `aged_copy` changes only `last_refresh`, to 60 days in the past. The
  production copy shape is unchanged: the JWT is intact and `refresh_token` stays `""`.
- **A-C1, an offline acceptance gate** (SL-6.2). It must pass before SL-6's implementation
  task.
  - **Setup:**
    - Assert the pinned Codex image digest, which the `seat_codex_runtime` pin names.
    - Run the real `_prepare_jailed_codex` and the production auth path, with copies built
      by `build_seat_copy` from one fixture login.
    - The fresh and aged copies differ only in `last_refresh`.
    - Use the production `codex` allowlist and no CLI provider or config override.
    - The TLS-terminating proxy runs deny-by-default and never dials an upstream, in the
      way `tests/test_seat_egress_allowlist_codex.py`'s proxy fixture observes denials.
    - A model request is observed as an allowed-rule match. If the proxy has a test
      responder it answers locally; otherwise the request is refused after it is recorded.
    - Event order comes from the proxy stream, not from `turn.started`.
  - **Pass condition:**
    - **Aged copy:** a fenced POST to `auth.openai.com` `/oauth/token` is denied, no model
      request comes before or after it, and the CLI ends with a typed refusal. This is
      `refused_intended`.
    - **Fresh copy:** the first request is the model request, and there is no OAuth POST.
    - **Not-ready variant:** the CLI fails before its credential path and is classified
      `not_ready`, never `refused_intended`.
  - **Hard failures:**
    - the jail opt-in (`PHASE_LOOP_REQUIRE_LIVE_JAIL=1`) missing;
    - a skip;
    - a wrong image digest;
    - missing fixture proof.
  - **If A-C1 fails, SL-6 stops.** That covers no POST, and a model request before or after
    the denial. Changing the copy shape to make it pass is not allowed. A further contract
    revision would be the fourth amendment, so the stall rule applies (principle 6).
  - **Known risk.** CODEX SL-1.5 measured no renewal by CLI 0.167.0 while its access token
    was valid, at any `last_refresh` age up to 29 days (the comment on
    `seat_codex_credential.CODEX_LOGIN_MIN_S`). Sixty days lies outside that measurement, so
    A-C1 is genuinely open. What replaces the Codex expired-copy control if A-C1 fails is the
    plan's question Q-D; it is not decided here.
- **Outcomes:**
  - scope via `scope_problem`, with no issuer call;
  - refresh via `tokens_changed` or an allowed token-endpoint request, giving
    `codex_seat_token_refreshed_in_jail`;
  - bracket rows ported from `codex-unlisted-endpoint`;
  - `image_sha256` is the projected subject digest, and `admission_class` the
    `seat_admission` class.

**10.C Claude.**

- **Gate:**
  - IF-0-CLAUDENET-1 to IF-0-CLAUDENET-3;
  - SL-1's `claude-credential-scope` receipt;
  - an OD-3b default recorded;
  - question Q-C resolved, with the observer interface landed by its owner.
- **Transport:** only the default transport is qualified; it is the key's `variant`.
- **Hook:** through the Q-C observer. `start` takes the argv from `spawning(argv)`, and
  `finish` runs in `before_teardown()` on every path.
- **Refresh:** `seat_claude_containment.refreshed_in_jail`.
- **Scope:** `pass` when the receipt covers the installed CLI version and the token-fd
  subscription login; otherwise `unavailable`.
- **Expired fixture:** a well-formed refused token-fd value. `refused_intended` is the login
  proof's typed refusal before the transport starts.

**10.D Grok.**

- **Gate:**
  - IF-0-GROK-1 to IF-0-GROK-3 on the base;
  - GROK SL-3 (the jailed leg with its hook call) and SL-6 (the measured jailed surface)
    landed.
- **Delivery:** `stage_grok_seat_credential`, which is skipped for `none`.
- **Refresh:** `grok_seat_credential_after`.
- **Scope:** the staging result.
- **Expired fixture:** per the rule above, on GROK's measured metadata. `refused_intended`
  is the CLI's typed auth refusal before a model turn. SL-8 stops if there is no such
  signature.
- **Retries:** a window launch never retries. Grok's `WindowVendorData` is registered by this
  adapter.

**10.E Pi.** The Pi revision adds Pi's supplier and a qualification composition for a board
that composes Pi explicitly (OD-5), with its envelope. FIRSTSEAT owns it. Until it lands, Pi
registers no window data.

## 11. Pins

These claims hold only while §5.1's `live` default, §5.4's call sites, §7's legacy check and the
stop rules hold.

| Pin | Moves | Requalification |
|---|---|---|
| `runtime_digest()` | yes, with every code lane | none; provenance |
| `release_identity()` | yes, with code; not with a grant pin | none; a grant binds it |
| `jail_profile_digest` (every leg) | no | none; `seat_profile_digests_jailcore.json` unchanged |
| Allowlists, the Gemini containment contract, the FIRSTSEAT interfaces | no | none |
| Gemini window binding | no | none; the fixed-clock, fixed-registry golden |
| agy QCI | no, provided no lane edits `agy_qualification.py`, `gemini_heartbeat.py`, `seat_jail_qualification.py`, or `terminal_verdict` and its helpers | none; `test_agy_qci.py` |
| EC-EXECFIND-2 passes, Claude SDK proof inputs | no | none |
| The W1 grant and admission | no | none |
| W1 record verification | only R7's own-rows comparison, R6's legacy exception and the per-vendor digest field | none |

## 12. Sequencing

SL-5's base holds the content inputs at the top of this file and main's Grok `status` action.
K-1's code lanes merge after the W1 release is cut. A roadmap re-stamp changes only the plan's
frontmatter. `CHANGELOG.md` and `seat_launch_references.json` are union-resolved.

## 13. Falsifiers (each through a production path)

- **F1–F7.** Isolation, unchanged from r2:
  - only `vendor:V` changes;
  - mismatched field names fail;
  - a borrowed digest fails;
  - a failing partition fails only itself;
  - registration refuses bad data;
  - a foreign observation is ignored;
  - the partition and R4 assertion are mutation-checked.
- **F8.** Grants:
  - mint, pin publication, install and claim, in order, with `release_identity` unchanged by
    the pin;
  - a non-literal grants module is refused;
  - each refusal of §8 happens before any auth call, with a spy on every auth and preflight
    function;
  - two concurrent claims leave one winner;
  - batch enumeration makes no preflight call and claims nothing;
  - grant rollover keeps retired-pin records verifying;
  - W1 is unchanged.
- **F9.** Envelope:
  - each excess is refused before spawn or request: a cold agy start, Grok's retry beyond 2, a
    Fable re-ask beyond 2, a fallback rung, a grant envelope too small, and an unscoped
    start;
  - concurrent legs reserve atomically;
  - a partial run keeps its counts;
  - the subject ledger stops at 5.
- **F10.** Golden, at a fixed clock and registry, unchanged from r2.
- **F11.** Each key part going stale (profile, allowlist, layout, projection, transport,
  host, arch) fails, and a key that differs from the exec record's launch inputs fails.
- **F12.** Expiry:
  - a used entry expired at its launch fails;
  - one valid at launch but expired by completion passes;
  - an expired unused rung passes;
  - a delayed used leg is refused at dispatch;
  - removing the entry from the matrix later does not change the verdict;
  - a missing used entry fails;
  - the subject's current expiry fails;
  - legacy W1 at the cutoff boundary: a claim just inside the margin passes, and one outside
    the margin falls back to the base rule;
  - a mismatched legacy witness, two candidate attempts and an unavailable journal each fall
    back to the base rule.
- **F13.** Integrity, through the production reader:
  - a restamp inside the interval fails;
  - a swapped same-vendor source, attempt or count set fails;
  - a missing or mismatched completion receipt, snapshot or witness fails;
  - a corrupt journal versus an unavailable journal gives distinct codes;
  - relabel, team-to-standard, duplicates and a foreign stage each fail.
- **F14.** W1 survives a registry change both with and without the W1 journal. Without it,
  the base expiry rule applies.
- **F15.** CLI, in a fresh process:
  - parsing;
  - bare `qualify`;
  - an invalid pair;
  - a mixed `--record` set with W1 and row read errors;
  - a duplicate and a tie in one partition;
  - the unscoped matrix;
  - batch exit codes for mixed results;
  - Grok's actions.
- **F16.** Codex, through `window_control_launch` with a stub at process spawn:
  - `none` (no copy, refusal without a copy);
  - `live` measured;
  - `expired` (the intended refusal);
  - every terminal class, `not_ready` included;
  - the production default byte-identical.
- **F17.** Hook ownership:
  - each leg has exactly one hook call site;
  - the hook finishes before teardown on normal, refused and raised paths;
  - the argv bound is the argv spawned.

## 14. Degraded Grok co-seat (answer for the GROK amendment)

**Yes, on condition of gate K1-G3 (§15).** A non-Grok row window can pass with a degraded Grok
co-seat, under these conditions:

- **Composition.** Grok is available and signed in, so the four-seat plan-tier composition is
  admitted (§9.3).
- **Termination.**
  - The Grok leg resolves degraded at its route and writes its exec record, as
    EC-FIRSTSEAT-3 requires for degraded legs.
  - The president completes, so the board terminates.
  - `co_seats` lists Grok as for any co-seat.
- **Expiry.**
  - A degraded leg makes no credential-bearing dispatch, so it is not a used entry under R6.
  - An expired Grok exception therefore does not fail the record.
  - An exception that has expired resolves degraded and cannot launch (principle 3).
- **Envelope.** Grok's reserved starts may stay unused.

If Grok is unavailable or signed out, composition refuses before launch. Grok's admission (GROK
SL-6) is therefore not on other vendors' paths, but a current Grok login is.

## 15. Acceptance tests and start gates (r4, convergence)

Each r3 finding is a named test, owned by one lane. The test is written red before the lane's
implementation and turns green only through the production path. Code review of that lane
checks it. Where a statement below is more specific than the prose above, it governs the
lane's code. Paths are under `phase-loop-runtime/tests/`.

### 15.1 Acceptance tests

**K1-T1: grant-module grammar.** Lane SL-5, test file `test_seat_window_grants.py`.
- *Given* `seat_window_grants.py` is anything other than exactly one assignment to each of
  the plain names `ROW_GRANTS` and `RETIRED_ROW_GRANTS`, with no other statement or target,
  *then* `window_grant`, `claim_window_attempt` and verification refuse it. This includes a
  literal-only file outside the grammar.
- *Given* a table key that is not a table vendor, or a duplicate key, *then* they refuse.
- *Given* a pin that is not a `(64-hex, 64-hex, timezone-aware ISO time)` tuple, *then* they
  refuse.
- The values used are the ones parsed from the checked bytes; the module is never imported
  separately.
- A retired entry admits nothing. It serves verification only.

**K1-T2: legacy W1 attempt linkage.** Lane SL-5, test file `test_seat_window_vendor_neutral.py`.
- *Given* a legacy W1 record whose context ID is not linked to the matching journal attempt
  by contemporaneous private evidence, *then* the relaxed R6 rule does not apply and the
  conservative rule does. That evidence is a private record written by the W1 run that names
  both the context ID and the attempt.
- This includes a second record with a different context inside the same unique interval.
- The journal's first line is compared by `sha256(first line + "\n") ==
  OWNER_W1_GRANT_SHA256`, as on the base tree, never by literal equality.

**K1-T3: ledger propagation into board workers.** Lane SL-5, test file
`test_seat_window_vendor_neutral.py`.
- *Given* a row window whose envelope allows exactly one Grok start, run through the real
  board fan-out (the board pool and the broker copy), *then* the second Grok start is
  refused before spawn.
- *Given* a board worker inside a window with no ledger in its context, *then* it is refused
  as `window_unbudgeted_start`. It is never treated as a non-window call.
- The attempt's single shared ledger is passed explicitly into each worker.

**K1-T4: the issuer request.** Lane SL-5, test file `test_seat_window_vendor_neutral.py`.
- *Given* an A5 allowance of 0, *then* the Gemini issuer token-info POST is not sent.
- *Given* an allowance of 1, *then* the request is reserved in the kit-owned caller
  immediately before it is made, and debited once.

**K1-T5: reservations versus dispatches.** Lane SL-5, test file
`test_seat_window_vendor_neutral.py`.
- A bulk reservation, such as the agy first-use reservation before preflight, debits the
  budget but is never recorded as a dispatch.
- Only an actual start records a route and a launch time for R6.
- An uncertain start still debits.
- Each counted operation is debited exactly once across the wrapper and the provider
  boundary.
- *Given* an unused reservation of an expired route, *then* the record still verifies.

**K1-T6: the A-C1 image pin.** Lane SL-6. This is a start gate for SL-6.3.
- `test_seat_window_codex_provider_free.py` carries a reviewed literal: the expected native
  Codex image digest and its source, which is the release image of the pinned CLI version,
  named by version and sha256.
- *Given* any launched image whose actual digest differs, *then* the test fails hard.
- The SL-6 implementation task does not start until this literal has been reviewed and the
  test is red for the right reason.

**K1-T7: A-C1 fixture isolation.** Lane SL-6, test file `test_seat_window_codex_provider_free.py`.
- The real prepare path runs with an isolated fixture `HOME` and `CODEX_HOME` and a synthetic
  login only, the margin re-check included.
- *Given* any credential or config lookup outside the fixture, *then* the test fails closed.
- The proxy denies by default and has no upstream.
- *Given* the fresh control, *then* it completes its local model request.
- *Given* the aged copy, *then* it ends `refused_intended`.
- *Given* the not-ready variant, *then* it ends `not_ready`.
- Every gate and command runs the test with `PHASE_LOOP_REQUIRE_LIVE_JAIL=1`. A skip fails.
- If A-C1 fails, SL-6 stops (Q-D, below).

**K1-T8: hook ownership, in three parts.**
- **SL-5:** dispatch routing (`window_board=` reaches only the window leg) and the order
  assertions for the existing Gemini and Codex legs.
- **SL-8, a start gate:** exactly one production Grok call site. It runs when GROK SL-3 is on
  the base, at SL-8 entry or on whichever of GROK SL-3 and K-1 SL-5 lands second.
- **SL-7, a start gate:** the Claude order assertion, through the print-path observer.

SL-5 does not require Grok or Claude call sites to land.

**K1-T9: mixed-validity duplicates.** Lane SL-5, test file `test_seat_window_vendor_neutral.py`.
- *Given* one valid standard record and one classified but invalid standard record in the
  same partition, *then* that partition fails with `window_duplicate_records`.
- The cardinality of standard records is counted before validity, as on the base W1 tree.
- A healthy different partition still reduces in the same run.

### 15.2 Start gates (not tests in this plan; each is checked on the gated lane's base)

**K1-G1: Grok's measured-input binding.** This gates SL-8.
- The Grok supplier's measured fixture and its `measured_input_sha256` binding, as the GROK
  contract (`grok-jail-tool-surface-contract-v1.md`) defines them, are on the base.
- SL-8 binds them. It does not substitute its own input.

**K1-G2: Grok's installed admission.** This gates the first Grok row grant.
- `staged_admission()` holds on the installed release with all five conditions of the GROK
  contract.
- This is live readiness on the designated host, kept separate from SL-8 consuming the code
  interfaces.

**K1-G3: provider-free confirmation of §14.** This gates the first post-Train-A row grant for
any vendor. It runs as SL-5's provider-free board test, `test_seat_window_vendor_neutral.py
-k degraded_grok`. The confirmation is a full four-seat board with:
- an authenticated Grok co-seat that returns its L6 refusal without a credentialed start;
- its exec evidence retained;
- a verified snapshot;
- the president completing;
- only the subject row changing.

If K1-G3 fails, §14's answer is withdrawn, and no non-Grok row grant is issued until GROK SL-6
admits Grok.

**K1-G4: F17 sequencing.** As in K1-T8.

**K1-G5: the A-C1 pin.** As in K1-T6.

### 15.3 Recorded rulings

**Q-C(b) (coordinator ruling, 2026-11-21).**
- `print` is the recorded default.
- The Claude observer lands on the print path, owned by CLAUDE.
- SL-7 qualifies `print` only. SDK is not qualified by this amendment.
- If OD-3b's record ever names a default other than `print`, SL-7 stops.

**Q-D: a contingency stop.** If K1-T7's aged case fails, SL-6 stops. No replacement control is
authorized.

