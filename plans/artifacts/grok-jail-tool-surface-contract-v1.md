# grok jailed tool-surface contract v1 (frozen artifact)

Frozen input of `plans/phase-plan-v1-seats-GROK.md` (the 2026-11-21 amendment, revision r2).
It holds the detail the plan points at: the jailed launch context, the fixed-input masks that
make the `staged` form eligible in the jail, the records, the closed and opened gate, the
spawn-boundary identity, the measurement through the jail, the owner grant, the row-window
evidence the Grok adapter must produce, the allow-list ruling, the pins and installs, and the
critical path to 2026-12-04. No lane edits this file. A change is a plan amendment; a result
bound to an earlier digest of this file does not count. §15 lists what r2 changed.

Inputs. Their content digests are pinned once, in the plan's frozen inputs and its manifest
row, not repeated here: the roadmap `specs/phase-plans-seats-v1.md`;
`plans/seats-jailcore-route-contract.md`; `plans/artifacts/grok-tool-surface-contract-v1.md`
("the TS contract"; pinned at erratum 7 as the historical base, re-pinned by SL-7 when
erratum 8 merges and erratum 9 is added, §8); and, read for coordination only,
`plans/artifacts/grokroll-v1-contract.md`.

Gating inputs not merged yet, named by role, never by a future digest: **erratum 8, final at
revision r3** of the TS contract (the 424-byte seat `config.toml` projected immutably with
`--ro-bind-data` from a sealed memfd; `SEAT_FIXED_INPUTS` and `SEAT_FIXED_INPUT_EXCLUSIONS`;
`NON_MUTATING_TOOLS`; per-image tolerated refusals by cause and order; closed path
diagnostics; the suffix scan through `SeatProfile.scan_values`; the aggregate publication
gate; the four requirements its cross-contract note places on this contract, §15), as it
merges; the **K-1 window kit** with the owner's 2026-11-21 decisions (expiry judged on a
snapshot of the exceptions that applied to the record's own run; per-vendor window grants
bound to host, context, time window, packet and budget, one attempt by default; row windows
keep the full four-seat board).

## §1 Why the unjailed basis cannot serve the jail

- The TS contract's frozen basis is valid only in `grok_seat_context.v1`, whose composition is
  the launch-owner composition; its consumer audit lists the jailed route as ineligible (TS
  contract §4.4, third row). Main's jailed spawn admits a grok argv only on a `list_tools`
  receipt, and no grok build offers `--list-tools`.
- Erratum 8 (r2, kept at r3) makes `staged` ineligible at use in the unjailed context, refused
  before spawn for frozen-basis use: its write and run tools can create a fixed input (a
  policy layer such as `.grok/requirements.toml` or `.grok/managed_config.toml`, or an MCP,
  skill, agent, hook or command source) in the writable home or tree, and the client re-reads
  and hot-reloads those inputs, so the measured surface would not bind the launch. Erratum 8
  asks this contract to protect those inputs in the jail or keep jailed `staged` closed.
- The jailed seat exists to give grok a **writable** disposable clone (EC-GROK-1) and real
  tool turns (EC-GROK-2). It must launch `staged`. So the jail needs its own context, measured
  inside the jail, in which `staged` is eligible because every fixed input is immutable (§2.4).

## §2 The jailed launch context `grok_jail_context.v1`

A new context beside `grok_seat_context.v1`, never replacing it. `grok_seat_context.v1`, its
constants and `grok_tool_surface.context_digest()` are not edited by any GROK lane.

### §2.1 Conditions, each checked at the spawn boundary (§4.4)

| Condition | Rule |
|---|---|
| Composition | `seat_jail.build_seat_jail` under the registered Grok `JailProfile`, route `jailed`, the jail's proxy-only namespace, one `start_proxy(allowlist_id="grok-review")` owned by this launch. |
| Owner argv | the **actual** composed bwrap argv and seccomp filter, normalised by the profile's digest placeholders, hash to the record's `launch_digest` (§2.2). It is computed from the argv that is spawned, not from the registered profile. A dependency projection is refused: the Grok profile declares `projection="none"`. |
| Binary | the bytes bound at `/seat/bin/grok` come from a descriptor held from hashing to spawn (§4.4); their sha256 is the record's `binary_sha256`. |
| Argv | the `staged` form of `grok_runtime_forms()` for the production model and effort, with only argv0 and the `--cwd` value replaced (`--cwd /seat/tree`, prompt on stdin); `_grok_argv_digest(launch) == _grok_argv_digest(staged)`, and the launch's cwd is exactly `/seat/tree`. |
| Seat home | the per-launch fresh `seat-home`. At spawn it holds only the immutable projections of §2.3, the masks of §2.4 and the two tmpfs mounts of §2.3. |
| Environment | the profile's allow-listed environment plus `HTTPS_PROXY` and `SSL_CERT_FILE`; no `GROK_*` or `XAI_*` variable. |
| Managed config | the two `/etc/grok` paths absent on the host and in the jail view; `/etc/claude-code/managed-settings.json` absent from the jail view (TS contract erratum 1). |
| Fixed inputs | every path of erratum 8's `SEAT_FIXED_INPUTS` (as of r3), and every project discovery path at `/seat/tree` and its visible ancestors, is immutable in the actual mount view (§2.4). |
| Egress | allow-list `grok-review`, its content digest; the jail's proxy-only namespace. |
| Tools | the receipt's admitted names are a subset of the `staged` form's `--tools` allow-list (`_grok_tools_admitted`); write and run tools are allowed only because §2.4 holds. |

### §2.2 Digests

- `jail_context_digest()`: sha256 of the canonical JSON (keys sorted, separators `,` and `:`,
  ASCII, no trailing newline) of `{schema: "grok_jail_context.v1", composition:
  "seat_jail.build_seat_jail+profile:grok", home: "/seat/home", seat_config: {path,
  sha256: SEAT_CONFIG_SHA256, projection: "ro-bind-data"}, immutable_projections: [sorted
  paths], ephemeral: [".grok/logs", ".grok/sessions"], fixed_inputs: [SEAT_FIXED_INPUTS],
  discovery: {policy: "masked", paths: [the per-image discovery inventory]}, environment:
  {allowed, forbidden_prefixes}, managed_config, child_absent_policy, egress: {allowlist_id:
  "grok-review", content_digest}}`. It moves with any of those inputs.
- `launch_digest`: sha256 of the normalised actual owner argv and filter of a production
  jailed launch (§2.1), per architecture. Recorded in the measurement and compared at every
  spawn. It is the bridge the review asked for between the canonical policy and the composed
  launch: two launches with the same `jail_profile_digest` but a different projection, mask
  or config descriptor differ here.
- The record key stays `(binary_sha256, argv_digest)`; `context`, `jail_context_digest` and
  `launch_digest` are record fields checked at use.

### §2.3 Projections and ephemeral paths (readable by the dropped seat UID)

- **Immutable projections.** `.grok/config.toml` (erratum 8's 424 bytes),
  `.grok/auth.json` (the access-only copy) and `.grok/agent_id` are each a sealed memfd
  (write, grow, shrink and seal sealed; offset 0 at handoff) projected with
  `--perms 0444 --ro-bind-data <fd> <path>`, held by the launch's exit stack, in `pass_fds`,
  closed after exit. No credential byte is written to disk. The egress CA is projected the
  same way. Mode 0444 makes them readable by the dropped seat UID without a chown; the jail
  holds only the seat. The descriptor checks of erratum 8 r2 item 1b (seals, size, `pread`
  digest without consuming, offset, `pass_fds`, lifetime, normalised destination, nothing
  mounted at or below it, nothing over `.grok/` but `--dir`) apply to all four.
- **`.grok` itself is a mount.** `.grok` is a `--perms 1777 --tmpfs` mount (the mode the builder
  already uses for `/tmp`), so the client can write its locks, docs and worktree database, and
  the directory cannot be renamed away (`EBUSY`) to plant a replacement `.grok/config.toml`
  (erratum 8 r3 item 1f's ancestor-rename case). The projections, masks and ephemeral mounts
  sit inside it. **Ancestor rule:** no projection or mask has an ancestor below the home mount
  that is not itself a mount point (so `.config` is a tmpfs mount for `.config/grove/`).
- **Ephemeral paths.** `.grok/logs` (the client log carries the token's last 12 characters) and
  `.grok/sessions` are each `--perms 1777 --tmpfs`, so the dropped UID can write them; both
  vanish with the jail. During a measurement only, `.grok/sessions` is the reservation's
  private sink (§5.2).
- **Suffix scan (erratum 8 r3 item 5).** The launch registers, from the exact projected
  credential copy (after shaping, never a reread of the store), every secret value of
  `_seat_secret_values` (at least 8 characters) and each value's last 12 characters as scan
  values, held in memory only (the jail profile's equivalent of `SeatProfile.scan_values`,
  never serialised). Seat output, the exec record, retained logs and, in a measurement, the
  definitions artifact are scanned for them **before** any retention or extraction. A hit is
  `grok_seat_token_in_output` at use and `artifact_refused` in a measurement (no retention, no
  extraction, no reprocessing or publication; the charge stands). The tmpfs log is the
  stricter sink as well, not a substitute.
- If the profile cannot express these as its own owner arguments without editing the shared
  `_owner_argv` builder or `seat_uid`, SL-2 STOPs (an edit there moves every leg's digests).

### §2.4 Fixed-input masks: why `staged` is eligible in the jail

Erratum 8 r2 item 1d leaves `staged` ineligible because a tool can create a fixed input. In the
jail no tool can:

- **Home.** Every `SEAT_FIXED_INPUTS` path under the seat home other than the four
  projections is an **immutable mask**: an empty sealed memfd with `--perms 0444
  --ro-bind-data` for a file entry, an empty read-only directory (`--perms 0555 --dir` then
  `--remount-ro`, or a read-only bind of an empty private directory) for a directory entry.
  A mount point cannot be created over, renamed over or unlinked (`EBUSY`), and nothing can
  be created inside a read-only directory (`EROFS`), whatever the parent's mode (erratum 8 r2
  item 1b, observed).
- **Tree.** Every path of the per-image discovery inventory at `/seat/tree` and at each
  ancestor visible in the jail is masked the same way, over the per-launch copy. The rest of
  the copy stays writable; that is EC-GROK-1's clone.
- **Inventory.** The protected set for the granted image is erratum 8 r3's `SEAT_FIXED_INPUTS`
  (policy layers including `.grok/requirements.toml` and `.grok/managed_config.toml`, the
  managed-sync state and caches, and the home discovery sources including `bundled/agents`,
  `bundled/skills` and `commands`) less `SEAT_FIXED_INPUT_EXCLUSIONS` (`auth.json` and
  `agent_id`, which are projections here; `.grok/rules`, prompt-only), plus the project
  discovery inventory: `grok_tool_surface.DISCOVERY_PATHS` and every project-config path the
  image's bundled documentation names (a project `.grok/config.toml` contributes
  `[mcp_servers]`, `[plugins]`, `[env]` and `[permission]`). SL-3 pins it per image, with the
  derivation in its test.
- **Refused construction.** Overlapping mask paths, a mask path that already exists in the
  stage as a symlink or a non-matching type, and any mask whose normalised destination
  differs from the inventory entry refuse `grok_tool_surface_unverified` before launch. A
  stage that already holds a discovery path is masked, not rewritten; its bytes stay in the
  authorised stage.
- **Residuals, stated.** Discovery from directories nested below the cwd is not bound; the
  client watches `<cwd>/` and `<cwd>/.grok/` only [erratum 8 r2, documented]. A run tool can
  start `/seat/bin/grok` again with other flags; that child's requests are bounded by the same
  egress policy and account, and the snapshot says nothing about it (TS contract §4.4, "what
  the snapshot is evidence of").
- **Exactly when jailed `staged` is eligible.** At a spawn only if all hold; otherwise jailed
  `staged` stays closed (L6 refuses, and the spawn boundary refuses):
  1. the installed release carries SL-3, whose final check enforces §2.3 and §2.4 on the actual
     mount list (ancestor rule included);
  2. the protected set is pinned for the resolved image;
  3. the masked-projection confirmation below is recorded for that image;
  4. the hosted real-launcher boundary check (BA-J5, with the ancestor-rename attempt) passed on
     the installed release's head;
  5. a jailed record exists for the image and `staged` argv digest, `measured` and `admitted`,
     whose `jail_context_digest` equals the running one.
- **Confirmation before any credentialed launch.** Whether grok 1.0.92 tolerates read-only
  masks at paths it unlinks at start (the managed-sync files) is untested (erratum 8 r2 item
  1d). An approved, credential-free, no-egress offline launch of the granted image under the
  exact jailed projection (immutable config, masks, tmpfs, CA) must reach the inference
  request with no `/v1/settings` or `/v1/models` and record the masks unchanged. It is a
  precondition of the §7 grant. If the client fails, SL-3 STOPs and the owner chooses
  between (a) a roadmap amendment admitting a non-mutating jailed form
  (`NON_MUTATING_TOOLS`), which gives up EC-GROK-1's tool write, and (b) waiting for a
  later image or erratum.

## §3 Records

- **Shipped catalog** `phase_loop_runtime/data/grok_jail_tool_surfaces.json`, schema
  `grok_jail_tool_surface_catalog.v1`: the TS contract §3.1 shape and loader rules, `context`
  fixed to `grok_jail_context.v1`, each surface adding `jail_context_digest`, `launch_digest`
  (per architecture) and `image_sha256` of the discovery inventory. A missing file is an empty
  catalog. The TS contract's catalog and loader are not edited.
- **Host-local record** `grok-jail-surface-<binary_sha256>.json`, schema
  `grok_jail_tool_surface_measurement.v1`, with TS contract §3.2 checks and precedence; lock
  and latest-attempt register `grok-jail-surface-<binary_sha256>.lock` and `.attempts.json`.
- **Receipts.** A jailed probe receipt is stored as `grok-jail-tools-<binary>-<argv>.json`,
  apart from the unjailed `tool_probe.v1` file keyed by binary and argv, so inspecting one
  context never overwrites the other. Same schema; `context` names the jailed context.
- **Repo evidence** `plans/evidence/seat-grok/tool-surface.json`
  (`grok_tool_surface_evidence_set.v1`); a jailed aggregate carries the context, both
  digests, the per-label launches (§5.3) and the release it was captured on. Catalog parity
  is per context.

## §4 Gate

### §4.1 Closed (Train A, SL-2)

- The profile's `Precondition("tool_surface")` returns `grok_tool_surface_unverified`
  **unconditionally** while `grok_jail_surface` is absent from the installed package. It reads
  no receipt, so absent, unjailed-frozen, legacy and listing receipts all stop at L6. SL-2
  implements it as a Grok-local function that imports the opening check from
  `grok_jail_surface` and returns the fixed refusal on `ImportError`; the module is created
  by SL-3 only. No other route step changes.
- Earlier refusals keep their codes: L0 `seat_sandbox_not_staged` without a staged tree, the
  L3/L4 host and subject refusals, L5 `grok_seat_credential_missing`. No proxy starts, L7 and
  L8 are not reached, nothing spawns.

### §4.2 Opened (SL-3)

- **Provisional, L6.** `grok_jail_surface.precondition_code()` passes only on a jailed record
  (catalog or host-local) for the resolved binary and the `staged` argv digest whose
  `jail_context_digest` equals the running code's, and on a jailed receipt that matches it.
  A `list_tools` receipt does **not** pass: a listing cannot bind the fixed inputs; a future
  listing build needs its own jailed erratum.
- **Final, at the spawn boundary**: §4.4.
- **Cross-context.** `launch_owned` refuses a jailed receipt; the jailed spawn refuses any
  unjailed, legacy or listing receipt.
- **Invalidation.** TS contract §4.3 with the jailed record set, digests and receipt store.

### §4.3 Consumer audit (replaces the TS contract §4.4 third row)

| Consumer | Basis |
|---|---|
| the jailed Grok leg, profile registered | eligible under `grok_jail_context.v1` only, through §4.2 and §4.4 |
| the window kit's Grok adapter | reads admission through `grok_jail_surface.staged_admission(binary_sha256)` |
| `seat-window probe-tools --vendor grok` | inspection only: its rows use the context the leg would launch in (jailed once registered); its aggregate exit is unchanged and is not a gate |
| `measure-tools --verify-probe final` | the installed admission check (§7.1) |
| every other row of the TS contract §4.4 table | unchanged |

### §4.4 Spawn-boundary identity

Checked inside the jailed `_popen` branch of `_run_leg_with_liveness`, after every other jail
probe (including the pre-Popen probe) and immediately before `launch_provider`, against the
exact objects about to be spawned:

1. **Binary.** The provider bound into the jail comes from the held seat subject
   (`_resolved_jail_subject`), opened once; its bytes are hashed through that descriptor and
   bound from it (`/proc/self/fd/N`, or the subject's own held-authority mechanism). A
   release replacement of the host path after the gate cannot change what is bound. The
   receipt is looked up by that digest; `_read_grok_receipt`'s host-path resolution is not
   used for the jailed leg.
2. **Owner argv.** The actual argv's `launch_digest` equals the record's; any dependency
   projection refuses.
3. **Projections and masks.** Each descriptor of §2.3 and §2.4 passes the erratum 8 r2 item
   1b checks; every mask destination, type, read-only status and the inventory coverage
   match the actual mount list.
4. **Cwd and argv.** cwd exactly `/seat/tree`; argv digest equals `staged`'s; model and
   effort are the production values.
5. **Proxy and holder.** The proxy is this launch's, live, with the holder pid and socket the
   egress prefix names (TS contract §4.6 binding).
6. **Receipt and record.** Re-resolved now; a withdrawn record, a replaced catalog route or a
   moved digest refuses.

`verify_jail_launch_context` issues a `JailLaunchContext` mark binding (1)–(6); the spawn
admits only that mark for that exact argv and jail. Every failure is
`grok_tool_surface_unverified`, before any process starts.

## §5 Measurement through the jail

### §5.1 No route bypass

The measurement does not enter `seat_route.resolve`'s L6 and gains no general bypass.
`grok_jail_surface.prepare_measurement(reservation)`:

1. evaluates every route step except L6 for the Grok leg: L0–L5 and L7 must pass, and the
   provider-free jail qualification for the **production** qualification key must be current
   (L8's verdict, read, not run);
2. composes the jail through the same builder path as a production jailed launch;
3. verifies the composition equals the production composition except for exactly two
   declared differences, and computes `launch_digest` with both substituted back:
   - `.grok/sessions` is the reservation's private sink, a fresh 0700 directory under the
     private record root (never a discovery path), instead of the tmpfs;
   - the proxy is the reservation's budgeted proxy (`request_budget`), instead of the
     budgetless one;
4. issues a single-use measurement admission bound to (reservation id, jail fingerprint,
   proxy, holder). `require_grok_admission` honours it for that spawn only; replaying it
   against another launch, another proxy or a second spawn refuses.

### §5.2 Egress, budget and ledger

- The TS contract §5.3 counted-request rule, per-launch budget 1, reservation before
  enabling, settlement on positive proof only (BA-1) and withdrawal across grants (BA-2)
  apply.
- `grant.json` gains `context` (absent means `grok_seat_context.v1`). Every stage refuses a
  context other than its grant's. Once a Grok profile is registered, a new
  `grok_seat_context.v1` grant refuses (coordinator ruling 3).
- **Per-label reservations (jailed grants).** The grant's `planned` list is the three labels
  of §5.3. Each reservation is immutable and names its label. A reservation for a label with
  no earlier reservation is a planned launch; one for a label that has one is a retry and
  needs a retry allowance. A planned launch never consumes a retry. Each `--route staged`
  stage takes the first label, in order, whose latest result is not `measured`; `planted`
  and `confirm` are refused until `pilot` is `measured`. The newest result per label
  decides. The jailed grant's cap is **5** counted requests (3 planned plus 2 retries), hard;
  the global ceiling of 7 is unchanged. No `seat_window.py` flag is added.
- Tests: interleaved transport failures, a crash and restart between reservation and
  settlement, the newest result per label, a successful planned launch leaving both retries,
  a sixth counted request refused.

### §5.3 Launches and fixture trees

| Label | Tree | Purpose |
|---|---|---|
| `pilot` | `clean`: one source file and `AGENTS.md`, no discovery path | the measurement |
| `planted` | `clean` plus a marker at every discovery-inventory path | surface unchanged with every marker masked |
| `confirm` | `clean` | surface stable across sessions |

Prompt, timeout and argv rules: TS contract §5.4. One binding rehearsal of `pilot` under a
budget-0 proxy (TS contract erratum 4), whose expected observation is erratum 8's
per-image table for the granted image, by cause and order. The rehearsal also proves the
1.0.92 request path through the jailed proxy: every refused request is observed and only the
budget denies the inference POST.

### §5.4 Reading, agreement, retention

- The artifact is read from the reservation's sink with TS contract §5.5–§5.6 rules; the sink
  is removed in `finally`.
- **Agreement.** `staged` is published only if `pilot`, `planted` and `confirm` are each
  `measured` with identical `tools` and `definitions_sha256`; otherwise nothing is published
  (`surface_unstable`).
- **Publication gate (erratum 8 r3 item 7).** `--aggregate` refuses with `context_mismatch`, and
  removes any jailed host-local record for the binary, unless every result and the passed
  rehearsal carry the running `runtime_digest` and the running `jail_context_digest`. A
  release installed between the last launch and the aggregate therefore publishes nothing.
- `admitted` is `_grok_tools_admitted(staged, tools)`; a measured, not admitted surface is
  evidence only.
- Redaction, retention, the purge and the publication lock: TS contract §5.7 and §5.9.

## §6 What Train A does

- **Route.** §4.1. Grok resolves degraded with a typed code; it was degraded already (no
  record, empty catalog).
- **Readiness matrix.** `vendor:grok`: `route: jailed`, `exception: null`, `expiry: null`,
  `allowlist_id: grok-review`, `status: candidate`, `interim_route: degraded`.
  `remote:grok`: its `allowlist_id` becomes `grok-review` (inherited from the profile by
  `readiness_rows`); its route and status are unchanged.
- **Other vendors' window records.** Under the owner's snapshot rule (K-1, once installed on
  the verifying host) a record fails only on exceptions that applied to its own run. Records
  observed before 2026-12-04 (Gemini's first window) keep verifying whatever happens to
  Grok. What Train A protects is every window **launched** at or after 2026-12-04: row
  windows keep the full four-seat board, so Grok's row is in every such run's snapshot, and
  an expired Grok exception there fails that record. Until the snapshot rule is installed,
  main's verifier fails every record while any row carries an expired exception, Claude's
  `open egress` included; that is resolved by the snapshot rule, not by GROK.
- **Digests.** `runtime_digest()` moves; Gemini's, Codex's and Claude's `jail_profile_digest`
  rows are unchanged; the golden gains `grok` rows. The qualification validator and watch
  digests move once (§10).

## §7 The next owner grant: jailed composition (ruling 3)

No owner-granted request is spent on `grok_seat_context.v1`; erratum 8's item 9 already
defers to this section.

- **Image.** One grok release image by sha256, installed as `grok` on the seat host, in
  GROKROLL's release catalog, and keyed in erratum 8's per-image map. Expected 1.0.92,
  `add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb`.
- **Context and release baseline.** `grok_jail_context.v1`, on the designated seat host, under
  one installed release carrying erratum 8's lanes and SL-0 to SL-4 (erratum 8 r3 item 8). The
  rehearsal, every launch and the aggregate run on that release; a different install stops
  the procedure (publication gate, §5.4).
- **One rehearsal** of `pilot`, budget 0, binding.
- **3 planned launches**, labels `pilot`, then `planted` and `confirm` after the pilot is
  `measured`.
- **At most 2 retries**, transport failures only, each manual with the coordinator's
  agreement; never for a credential or egress failure.
- **At most 5 counted requests**, budget 1 per launch, hard cap 5 for this grant.
- **A fresh grok sign-in** by the owner on the seat host immediately before the slot. Before
  the grant is reserved, a metadata-only reader checks the store: a positive subscription
  marker, a parseable expiry, and remaining lifetime above the slot's hard end plus 5 minutes.
  An absent or ambiguous marker, an unparseable expiry or too short a lifetime stops the
  procedure before any reservation.
- **Preconditions:** this contract and the plan accepted; SL-0 to SL-4 and erratum 8's lanes
  merged, released and installed on the seat host; hosted BA-J1 executed with no skips on
  that merged head (`PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1`), recorded through `--hosted-check`;
  the §2.4 masked-projection confirmation recorded; `VL` and `VL2` passed on the seat host;
  the provider-free Grok qualification (`seat-sandbox qualify --leg grok`) current for the
  production key; erratum 8 item 4's staging check; a quiet slot, both shared-compute locks,
  the memory-PSI gate and `MemorySwapMax=0` scopes, as for D4.
- **Stops.** The rehearsal passes only on the expected observation; anything else stops before
  the pilot with no request spent. The runtime stop and publication gate of erratum 8 r3 item 7
  and §5.4 apply.
- **Briefing facts the owner authorises against (erratum 8 r3 item 9).**
  - Two outcomes can leave the board gate closed after requests are spent: a pilot that is
    `measured` with `admitted: false`, and measured results that disagree (`surface_unstable`).
    The measured-and-admitted gate stays either way.
  - The offline `review` artifact offered `use_tool`, so an unjailed `review` measurement could
    come out measured but not admitted. It does not predict the jailed `staged` pilot. Only
    `staged` carries the explicit `use_tool` disallowance; `sealed` runs in plan mode with an
    empty `--tools`. This grant measures jailed `staged` only: no unjailed, `review` or
    `sealed` measurement.
  - The grant inherits erratum 8's runtime stop and publication gate and the `staged`
    prerequisite of §2.4 (the masked-projection confirmation).

### §7.1 Procedure and installed checks

- TS contract §5.10's script with `--planned pilot,planted,confirm` and `--route staged` per
  launch. Step 0 (0 calls): `phase-loop seat-window matrix` on the installed runtime shows the
  Grok row `jailed`, and `phase-loop seat-sandbox qualify --leg grok` reports a current pass
  naming leg `grok` and its qualification key. The final step is
  `measure-tools --verify-probe final`, which passes only if, in the jailed context, `staged`
  is `frozen_measurement` and admitted and every other form is refused.
- SL-4 ships the script as `docs/ops/grok-jail-measurement.md` with a test that runs it against
  a recording runner.

### §7.2 EC-GROK-5 records (0 extra calls)

- Lifetime and subscription marker: the pre-grant reader's metadata (key names, marker presence,
  expiry minus sign-in time). Never values.
- **Effective egress scope**, not bearer rights: the pilot's settled observation (the copy was
  accepted at the one allowed inference row) plus the allow-list's refusal of every other
  endpoint. It shows what the seat can reach; it does not show what the bearer could do
  elsewhere.
- Both land as ids in `plans/evidence/seat-grok/credential-scope.json`.

### §7.3 Row-window evidence the Grok adapter must produce (EC-GROK-1, EC-GROK-2)

The Grok row window is separately granted by the owner (one attempt by default), outside the
five-request surface grant. K-1's Grok adapter implements this fixture; GROK's closeout
requires its evidence.

- **Fixture.** The adapter stages a tree with a fresh random canary path that does not exist,
  and a prompt that asks the CLI to create that file with given content using its write tool
  and then run one named shell command in the clone.
- **Assertions, by the parent after the leg:** the canary exists only in the per-launch copy
  with exactly the requested bytes; the authorised stage's hash, every other tree path and a
  sibling seat's tree are unchanged; the stream facts show at least one write tool step and
  one run tool step, a terminal model turn and no cancellation (agent-harness#1091).
- **Binding.** The record names the installed release, the image digest and the admitted
  `staged` argv digest and `jail_context_digest`.
- **Fails.** A no-tool reply, a read-only run, a missing or altered canary, a canary outside
  the copy, or a cancelled turn each fail the relevant assertion. The surface prompt ("Do not
  call any tool") cannot supply this evidence.

## §8 Amendments to the TS contract (ruling 1)

Applied by one pointer erratum, **erratum 9**, added to the TS contract by SL-7 in a
planning-only commit after erratum 8 merges; the same commit re-pins the TS contract in the
plan's frozen inputs and its manifest row. SL-3 and SL-4 start only on a base holding that
re-pin.

| TS contract section | Amendment |
|---|---|
| §3.1, §3.2, §3.3 | the jailed catalog, host-local names, receipt store and evidence (§3) |
| §4.1 | the record set follows the leg's context (§4.3) |
| §4.2 | `context` may be `grok_jail_context.v1`; the jailed admission rules of §4.2 |
| §4.3 | re-resolution with the jailed digests |
| §4.4 third row; erratum 8 r2 item 1d (`staged` ineligible) | jailed `staged` eligible under §2.4 only; unjailed `staged` stays ineligible |
| §5.1, §5.3, §5.4, §5.7, §5.8, §5.10 | §5 and §7.1 here |
| §10 BA-3 | BA-J1 here |

Erratum 9 text:

> **Erratum 9 (jailed context).** A second launch context, `grok_jail_context.v1`, is defined
> by `plans/artifacts/grok-jail-tool-surface-contract-v1.md`. In it the `staged` form is
> eligible because every fixed input is immutable (its §2.4); everywhere else erratum 8's
> item 1d stands. It amends §3.1–§3.3, §4.1–§4.4, §5.1, §5.3, §5.4, §5.7, §5.8, §5.10 and §10
> as its §8 lists. `grok_seat_context.v1` and `context_digest()` are unchanged.

## §9 Allow-list: adopt `grok-review` (ruling 4)

The profile sets `allowlist_id="grok-review"`; no allow-list file is added or edited. Same
client, same seat config, same endpoints, so one measured request set; no allow-list digest
moves; the loader checks the file's `leg` against the id and the route passes the profile's id
(`seat_egress_proxy`, `seat_route`), so nothing needs `allowlist_id == leg`. SL-1 runs the
positive control (an allowed inference request through the real `proxy.mjs` to a fixture
upstream) and the refusals (an unlisted host, Gemini's and Codex's hosts, a listed host on an
unlisted path, a direct connection). The jailed rehearsal and pilot prove the real 1.0.92 path.
Retiring the id would move both contexts' digests; it is not done.

## §10 Pins, installs and shared edits

"Moves" means the lane changes the value; values are lane outputs, recorded in lane reports.

| Pin | SL-0 | SL-1 | SL-2 | SL-3 | SL-4 | SL-6 | SL-8 |
|---|---|---|---|---|---|---|---|
| `runtime_digest()` | moves | moves | moves | moves | moves | no | moves |
| qualification validator and watch digests | no | no | **once** | no | no | no | no |
| `_PROXY_IMPLEMENTATION_SHA256` | no | no | no | no | no | no | no |
| Claude SDK proof inputs | `seat_route_contract.py` | none | `seat_profiles.py` | `claude_seat_transport.py` insertions; `_run_leg_with_liveness` | none | no | no |
| unjailed `context_digest()` | no | no | no | no | no | no | no |
| `jail_context_digest()`, `launch_digest` | — | — | — | new | — | — | — |
| route forms and argv digests; allow-list digests | no | no | no | no | no | no | no |
| `jail_profile_digest` | no | no | new `grok` rows | no | no | no | no |

- **Unjailed baseline.** Erratum 8's E8-A moves `context_digest()`. SL-3 and SL-4 record its
  value before and after their change on the E8-A baseline, and run the unjailed
  compatibility suites (legacy, `review`, `sealed`, and `staged` measurement) unedited.
- **What requalifies, as an operational evidence policy.** On main the route key omits watch
  and validator digests, and the window verifier checks those binding digests for shape only.
  This plan therefore states the policy: after an install that moves the validator, watch or
  proxy digest, a jailed seat's next provider-free qualification and its next window bind the
  new values; existing records are not invalidated by code. K-1's R1 and R8 compare profile
  and allow-list digests and record `runtime_digest`.
- **Installs.**

  | Install | Contents | Moves for other vendors |
  |---|---|---|
  | Train A (cut 2026-12-01) | SL-0, SL-1, and SL-2 if merged, else SL-8; E8-A, E8-B, E8-C if merged by the cut | validator and watch (SL-2), proxy (E8-C if in A), runtime |
  | K-1 snapshot expiry rule | FIRSTSEAT K-1; its own install, before 2026-12-04 on every verifying host | per K-1 |
  | Train B | SL-3, SL-4; E8-C if it missed A (then B moves the proxy pin) | runtime, and proxy if E8-C rides B |
  | Catalog | SL-6 data and its `pyproject.toml` line | none (outside the runtime hash) |
  | Recovery | only if SL-8 rode A and SL-2 follows | validator and watch |

  No install lands on the seat host between Gemini's first-window launch and its export. Each
  evidence capture records its installed release, and each verification records the installed
  verifier that judged expiry.
- **Same release baseline (erratum 8 r3 item 8).** The baseline is the installed integrated
  release, not a merge. The §7 grant and any Gemini first-window refresh run on the installed
  release carrying erratum 8 and the jail lanes they rely on. A Gemini window is refreshed per
  installed digest it relies on; with two trains there is no single-refresh promise: Train A
  and Train B can each require one.
- **Shared edits, one writer per hunk.** GROKROLL: SL-6's package-data line, SL-8's expiry
  literal (GROKROLL SL-0, agent-harness#2050, is merged; later GROKROLL lanes re-take their
  base after a GROK lane lands), and the CHANGELOG and launch inventory (SL-7). K-1:
  `seat_profiles.py` (window data), `panel_invoker.py` (the window section vs. SL-3's leg),
  `seat_window.py` (kit vs. SL-8), this plan and the manifest. Erratum 8: E8-A shares
  `panel_invoker.py` with SL-3, E8-B shares `grok_tool_surface.py` with SL-4, and both share the
  TS contract with SL-7's erratum 9. The second lander rebases.

## §11 Critical path to 2026-12-04T00:00Z

| By (UTC) | What | Who |
|---|---|---|
| 2026-11-23 12:00 | r2 accepted | coordinator |
| 2026-11-24 | SL-0 merged | lane |
| 2026-11-25 | SL-8 reviewed on the release base, proven on a build without the Grok profile; release slot for Train A reserved | lane, release owner |
| 2026-11-26 | SL-1 merged | lane |
| 2026-11-28 | owner decides the Grok renewal record (signed, or declined); K-1 snapshot expiry rule merged | owner, FIRSTSEAT |
| 2026-11-30 12:00 | SL-2 merged, with its dropped-UID check (`VL2`) passed on a jail-capable host | lane |
| 2026-12-01 | Train A cut: SL-2 if merged, else SL-8 under the signed record | release owner |
| 2026-12-02 12:00 | Train A and the K-1 snapshot rule installed on every seat host; coverage recorded per host: `seat-window matrix` shows Grok `jailed` with no exception (or the renewed expiry) | host owner |
| 2026-12-03 | `seat-sandbox qualify --leg grok` on the designated host (SL-5) | host owner |
| 2026-12-04 00:00 | expiry; the exception is absent or renewed on every installed host | — |

- **Fallback, without a second build.** SL-8 depends on nothing and rides Train A in SL-2's
  place. It replaces the shared expiry constant with a per-vendor map (Grok renewed to the
  signed date, no later than 2026-12-18; others unchanged) and fills `renewal_record`. If the
  owner declines the renewal and SL-2 misses the cut, Grok's exception expires; windows
  launched after the expiry then fail on the Grok snapshot until a recovery install lands.
- **Install miss.** If Train A cannot be installed on a host by 2026-12-03T12:00Z, no window
  launches on that host until it is; existing records are protected by the snapshot rule.
- **Gemini on both sides of the boundary.** SL-2's and SL-8's tests verify a fixture Gemini
  record observed before 2026-12-04 at a clock before and after the boundary, under the
  snapshot rule, with Grok registered (SL-2) and renewed (SL-8).

## §12 Binding acceptance criteria of the lanes

- **BA-J1 (SL-3) — isolation in the real jailed child.** One child of the real Grok jail shows
  both an allowed request through the proxy to a fixture upstream and a refused direct
  connection to a host-reachable listener (first proven reachable). Mandatory hosted check
  under `PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1`; a missing prerequisite fails.
- **BA-J2 (SL-3) — spawn-boundary substitutions.** Each of these, applied after the gate and
  before spawn, refuses with nothing spawned: a different binary at the host path, a swapped
  config descriptor, a dependency projection, a removed or retyped mask, another proxy or
  holder, a withdrawn record, a different cwd. The mark cannot be built outside
  `verify_jail_launch_context`.
- **BA-J3 (SL-3) — receipts.** Unjailed frozen, legacy and listing receipts refuse at the jailed
  spawn; a jailed receipt refuses in `launch_owned`; a jailed probe does not overwrite an
  unjailed receipt.
- **BA-J4 (SL-2, extended by SL-3) — the dropped child.** A stand-in under the actual seat UID in
  the real Grok jail can read the three projections and the CA, cannot append, truncate,
  rename over, unlink or chmod any of them, cannot rename `.grok` (or `.config`) away, can
  write both tmpfs mounts and `.grok` itself, cannot create inside a mask; a planted
  12-character suffix written to `.grok/logs` and the credential bytes are absent from
  seat-out, the review dir, the grant, the output directory, the record root and the evidence
  after teardown. SL-3 adds: a stand-in that copies the suffix into its stdout and into the
  definitions artifact is caught by the scan before retention, for a short and a long
  credential shape (`grok_seat_token_in_output`, `artifact_refused`).
- **BA-J5 (SL-3) — masks, through the real launcher.** In `live_jail` and as a hosted check,
  with the `planted` tree: every protected path is an immutable mask; creating
  `.grok/requirements.toml`, `.grok/managed_config.toml`, an MCP, skill, agent, hook or command
  source in the home, or a discovery path at `/seat/tree`, fails; renaming `.grok`, `.config` or
  a tree mask's parent and re-looking-up the path still finds the mask; the rest of the copy is
  writable and byte-identical to the stage; an overlapping or symlinked mask path refuses.
- **BA-J6 (SL-2) — gate closed.** Through ordinary board routing with an absent, a valid
  unjailed frozen, a legacy and a listing receipt: the same L6 refusal, zero proxies, zero
  qualification runs, zero provider spawns. Mutation: replacing the fixed refusal with
  `grok_tool_gate` fails this test.
- **BA-J7 (SL-4) — measurement flow.** With no receipt, a full rehearsal and first launch run
  through `prepare_measurement`; a swapped sink, a swapped proxy, a missing reservation and a
  replayed admission each refuse.

## §13 Coordination

- **Erratum 8 (final at r3).** Consumed by reference (the projection, `SEAT_FIXED_INPUTS`,
  `NON_MUTATING_TOOLS`, per-image refusals). SL-1 pins the seat-config digest as an input; SL-3
  asserts it equals `grok_tool_surface.SEAT_CONFIG_SHA256`. SL-3 waits for E8-A and SL-4 for
  E8-B. Its item 9 defers to §7.
- **K-1.** One owner per piece. GROK SL-3's jailed leg takes `window_board:
  _WindowBoardLegRuntime | None` (pre-existing class) and calls `start`, `finish` and
  `finalize_proxy` in `_exec_jailed_gemini_leg`'s order. Delivering the runtime to the Grok
  leg (`_parent_infer` or `window_board_for`) is K-1's kit code. K-1's Grok adapter starts
  after GROK SL-3 and SL-6, implements §7.3, and registers Grok's `WindowVendorData`. K-1's
  §5.4 table and §10.D need that wording; its two edits to this plan are subsumed.
- **GROKROLL.** No GROKROLL pin moves. Its status query reads the unjailed catalog only;
  teaching it the jailed catalog is a GROKROLL follow-up.

## §14 Open questions

1. Whether a degraded Grok co-seat lets another vendor's four-seat row window pass before SL-6
   admits Grok. If it does not, Grok admission is on every row window's path.
2. The masked-projection confirmation (§2.4) is the largest technical risk to the grant; it
   should be requested as soon as SL-3's projection is reviewable.
3. One attempt per row window by default: the Grok adapter's fixture should be dry-run with a
   stand-in through the real adapter before the owner grants the window.

## §15 Revision r2 (2026-11-21)

Review `review-amendment-sol.md` (ACCEPT-WITH-CHANGES) and new inputs:

- R1 → §4.1, BA-J6: unconditional L6 refusal in Train A, independent of receipts.
- R2 → §11: SL-8 depends on nothing and rides Train A in SL-2's place; owner decision by
  11-28; Gemini protection by the owner's snapshot rule; tests on both sides of the boundary.
- R3 → §2.1, §2.2, §4.4, BA-J2: actual-launch identity at the spawn boundary.
- R4 → §5.1, §5.2, BA-J7: reservation-scoped flow, two declared differences, per-label
  ledger, hard cap 5; one hosted flag name.
- R5 → §2.3, BA-J4: memfd projections at 0444 and 1777 tmpfs, proven in the dropped child.
- R6 → §7.3: the adapter's canary write and tool-turn evidence.
- R7 → §8, §13: one hook owner per piece; TS contract re-pin at erratum 9.
- R8 → §4.3, §7.1: `seat-sandbox qualify --leg grok`; `--verify-probe final`; separate receipt
  store.
- SHOULDs → §2.4 (inventory, masks, listing removed), §6 (`remote:grok`), §7 (discriminator,
  effective scope), §9 (positive control), §10 (baseline, evidence policy, installs, shared
  hunks).
- Erratum 8 r2 → §1, §2.4: `staged` is eligible only in the jail, behind fixed-input masks,
  after the masked-projection confirmation.
- Owner window decisions → §6, §7.3, §11.
- Erratum 8 r3's four requirements on this contract: (1) home inputs protected and the exact
  eligibility conditions → §2.3 (`.grok` as a mount, ancestor rule), §2.4, BA-J5; (2) suffix
  scan carried, plus the tmpfs sink → §2.3, BA-J4; (3) one installed release baseline, W1
  refreshed per installed digest → §7, §10; (4) owner terms and briefing facts → §7. The
  aggregate's `context_mismatch` gate binds `jail_context_digest()` → §5.4.
