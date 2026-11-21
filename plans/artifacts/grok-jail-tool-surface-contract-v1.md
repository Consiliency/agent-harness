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
("the TS contract"; pinned at erratum 7 as the historical base, re-pinned by the planning
amendment of §8 when erratum 8 merges and erratum 9 is added); and, read for coordination only,
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
| Binary | the bytes bound at `/seat/bin/grok` are the resolved subject's, from a source that passes `seat_subject`'s root-owned pin walk (every component owned by root and not group- or other-writable), hashed at the spawn boundary (§4.4); their sha256 is the record's `binary_sha256`. |
| Argv | the `staged` form of `grok_runtime_forms()` for the production model and effort, with only argv0 and the `--cwd` value replaced (`--cwd /seat/tree`, prompt on stdin); `_grok_argv_digest(launch) == _grok_argv_digest(staged)`, and the launch's cwd is exactly `/seat/tree`. |
| Seat home | the per-launch fresh `seat-home`. At spawn its mount list is exactly the ordered list of §2.3. |
| Environment | the profile's allow-listed environment plus `HTTPS_PROXY` and `SSL_CERT_FILE`; no `GROK_*` or `XAI_*` variable. |
| Managed config | the two `/etc/grok` paths absent on the host and in the jail view; `/etc/claude-code/managed-settings.json` absent from the jail view (TS contract erratum 1). |
| Fixed inputs | every path of erratum 8's `SEAT_FIXED_INPUTS` (as of r3), and every project discovery path at `/seat/tree` and its visible ancestors, is immutable in the actual mount view (§2.4). |
| Egress | allow-list `grok-review`, its content digest; the jail's proxy-only namespace. |
| Tools | the receipt's admitted names are a subset of the `staged` form's `--tools` allow-list (`_grok_tools_admitted`); write and run tools are allowed only because §2.4 holds. |

### §2.2 Digests

- `jail_context_digest()`: sha256 of the canonical JSON (keys sorted, separators `,` and `:`,
  ASCII, no trailing newline) of `{schema: "grok_jail_context.v1", composition:
  "seat_jail.build_seat_jail+profile:grok", home: "/seat/home", seat_config: {path,
  sha256: SEAT_CONFIG_SHA256, projection: "ro-bind"}, mounts: [the ordered list of §2.3],
  protected_set: {image_sha256, home: [...], tree: [...]}, environment:
  {allowed, forbidden_prefixes}, managed_config, child_absent_policy, egress: {allowlist_id:
  "grok-review", content_digest}}`. It moves with any of those inputs.
- `launch_digest`: sha256 of the normalised actual owner argv and filter of a production
  jailed launch (§2.1), per architecture. Recorded in the measurement and compared at every
  spawn. It is the bridge the review asked for between the canonical policy and the composed
  launch: two launches with the same `jail_profile_digest` but a different mount policy or
  seat config differ here. **It is a shared digest** (r4): honest launches of the same image
  and policy on different hosts, with different credentials, CAs and per-launch objects, must
  produce the same value, because conditions 3 and 4 and the catalog compare it across hosts.
  - **Normalised to role placeholders:** every per-launch directory (tree copy, seat-home,
    seat-out, sink, and the config, credential and CA source operands, whatever projection
    is settled), every descriptor operand (`<bundle-fd>`, `<instructions-fd>`, `<token-fd>`,
    `<seccomp-fd>`, as `jail_profile_digest` already normalises them), and the proxy address
    and port operands (`<egress-proxy>`).
  - **Included:** the ordered mount policy, the environment names, the argv digest, and the
    pinned `SEAT_CONFIG_SHA256` (the seat config's bytes are policy, identical everywhere).
  - **Excluded:** the credential bytes, `agent_id` and the CA bytes. They are verified per
    launch against their own digests (§4.4 check 3), never in the shared digest.
- The record key stays `(binary_sha256, argv_digest)`; `context`, `jail_context_digest` and
  `launch_digest` are record fields checked at use.

### §2.3 Projections, the ordered mount list and the scan values

> **r4: the projection-directory design below is withdrawn** (coordinator ruling,
> 2026-11-21). Its replacement is open question Q-r4 (§17). The scan-value rules of this
> section stand.

**Delivery (no descriptor handoff).** `build_seat_jail` passes only its own descriptors, and
`owner_binds` emits arguments but owns none, so the jailed seat uses **path** binds and no new
descriptor. Per launch, the launch site (SL-3; for the provider-free qualification,
`seat_profile_grok.qualification_shape`, SL-2) creates a fresh **projection directory**:
operator-owned, mode 0700, outside seat-home, seat-out and the tree. It holds, each mode 0444
and written once with `O_CREAT|O_EXCL|O_NOFOLLOW`: `config.toml` (erratum 8's 424 bytes),
`auth.json` (the access-only copy), `agent_id`, `egress-ca.pem`, and `empty` (zero bytes); and
`empty.d/`, an empty directory, mode 0555. The profile's `owner_binds(paths)` binds them by
path through the `<grok-projection>` placeholder. Inside the jail a read-only bind mount point
cannot be written, replaced, renamed or unlinked (`EROFS`/`EBUSY`), and mode 0444 or 0555
makes it readable by the dropped seat UID without any ownership handoff. The directory is
removed in `finally`, and by the existing abandoned-scratch purge after a crash. The builder
and `seat_uid` are not edited. This differs from erratum 8's unjailed `--ro-bind-data` projection;
erratum 8's launch 7 observed the client tolerating a read-only mount point at the config path,
and condition 3's confirmation (§2.4) is taken under this exact path-bind projection. If the dropped UID cannot read a bound file or write a tmpfs
(BA-J4), SL-2 STOPs and the plan is amended before execution.

**Integrity at spawn.** The final check (§4.4) opens each projection file `O_NOFOLLOW`,
requires a regular file, mode 0444, owner the operator, size and sha256 equal to the expected
bytes, and the directory to be mode 0700, owned by the operator and to hold exactly those
entries. A same-UID writer can still change a file after the check; that is the TS contract's
D1 trust model (an operator-UID writer can forge a receipt too), stated here, not hidden.

**The ordered mount list (supersedes erratum 8 r2 item 1b's "nothing over `.grok/` but
`--dir`" for the jailed context only).** After the builder's `--bind <tree> /seat/tree`,
`--bind <home> /seat/home` and `--bind <out> /seat/out`, the profile appends exactly, in this
order:

1. `--perms 1777 --tmpfs /seat/home/.grok` and `--perms 1777 --tmpfs /seat/home/.config`;
2. `--ro-bind <grok-projection>/config.toml /seat/home/.grok/config.toml`, then `auth.json`
   and `agent_id` the same way, and `--ro-bind <grok-projection>/egress-ca.pem
   /seat/egress-ca.pem`;
3. the home masks of §2.4, in protected-set order;
4. `--perms 1777 --tmpfs /seat/home/.grok/logs` and `--perms 1777 --tmpfs
   /seat/home/.grok/sessions` (during a measurement, the sink bind of §5.1 in place of the
   second);
5. the tree masks of §2.4, in protected-set order.

No other mount may have a normalised destination equal to, below or above (between the home
or tree mount and) any protected path, projection or ephemeral mount, and none may follow
the list (no shadow mount). Every destination is absolute, `posixpath.normpath`-stable and
has no symlink component in the jail view.

**Ancestor rule, home and tree.** Every ancestor of a protected path, between it and the
`/seat/home` or `/seat/tree` bind, is itself a mount point (`.grok`, `.config`), so it
cannot be renamed away to plant a replacement (erratum 8 r3 item 1f). Above `/seat/tree`,
`/seat` and `/` are read-only (`--remount-ro /`), so a visible project ancestor cannot be
written or renamed.

**Ephemeral paths.** `.grok/logs` (the client log carries the token's last 12 characters) and
`.grok/sessions` vanish with the jail.

**Scan values and their handoff (erratum 8 r3 item 5).** `stage_grok_seat_credential` derives,
from the exact projected bytes (never a reread of the store), every secret value of
`_seat_secret_values` (at least 8 characters) and each value's last 12 characters, held only
in memory on `GrokSeatCredential.scan_values`. At use, the launch site passes them to the
output scan before the exec record, returned text or any log is retained. In a measurement,
SL-3's `prepare_measurement` returns a `JailedMeasurementLaunch` carrying them; SL-4's reader
receives that object, scans before it retains or extracts anything, and drops it once the
result record is written. Retained channels and their rule:

| Channel | Jailed rule |
|---|---|
| seat output, returned text, the exec record | scanned before retention; a hit is `grok_seat_token_in_output`, nothing retained |
| provider stdout and stderr of a **failed** measurement (TS contract §5.9's private `provider.log`, the r3 raw-failure exception) | stricter than the TS contract: scanned before it is written; on a hit it is not written; otherwise kept private with the 7-day expiry |
| the definitions artifact and the sessions sink | scanned before retention or extraction; a hit is `artifact_refused` |
| `.grok/logs`, `.grok/sessions` (use) | tmpfs, never retained |

`artifact_refused` follows erratum 8 r3: no retention, extraction, reprocessing or publication;
the settled charge stands; `--require-measured` fails; the result and evidence readers accept
the status.

### §2.4 Fixed-input masks: why `staged` is eligible in the jail

> **r4: the mask inventory and mechanism below are withdrawn** (coordinator ruling). The
> five-condition gate, its ordering and its evidence records stand; condition 2's protected
> set and the mask mechanism await Q-r4 (§17).

Erratum 8 r2 item 1d leaves `staged` ineligible because a tool can create a fixed input. In the
jail no tool can:

- **Masks.** A file entry is `--ro-bind <grok-projection>/empty <path>`; a directory entry is
  `--ro-bind <grok-projection>/empty.d <path>`. Nothing can be created inside, over or in
  place of a read-only mount point (erratum 8 r2 item 1b, observed for the config file).
- **Protected set: a complete input for SL-2.** `seat_profile_grok.PROTECTED_SETS` is a literal
  keyed by image sha256, landed by SL-2. For `add4d201…` (1.0.92) it is transcribed from the
  frozen text of erratum 8 r3 item 1c: `SEAT_FIXED_INPUTS` less `SEAT_FIXED_INPUT_EXCLUSIONS`
  (`auth.json` and `agent_id` are projections here; `.grok/rules` is prompt-only) for the home,
  and `grok_tool_surface.DISCOVERY_PATHS` (`.agents`, `.claude`, `.cursor`, `.grok`,
  `.mcp.json`) for the tree. Once E8-A merges, SL-3 asserts the home set equals E8-A's
  constants for that image; a mismatch STOPs SL-3. An image with no entry has no eligible
  `staged`.
- **Canonical coverage.** Each set is reduced before use: an entry with an ancestor in the same
  set is dropped as covered, so no mask is mounted inside another. A tree entry `.grok` covers
  a project `.grok/config.toml`. Home `.grok` is the writable tmpfs, not a mask, so home
  entries below it are masked one by one. The reduced list, not the raw one, is in the digest.
- **Tree mount points.** Before the jail is built, after the copy's `staged_tree_sha256`
  check, the launch site creates, in the per-launch copy, an empty file or directory of the
  entry's type at each absent tree entry, so the bind has a target. An entry that exists as a
  symlink, as a different type, or under a symlinked component refuses. An entry that exists
  is covered as it stands; its bytes stay in the authorised stage. These stubs are excluded,
  by name, from EC-GROK-1's "everything else unchanged" comparison.
- **Residuals, stated.** Discovery from directories nested below the cwd is not bound; the
  client watches `<cwd>/` and `<cwd>/.grok/` only [erratum 8, documented]. A run tool can start
  `/seat/bin/grok` again with other flags; that child is bounded by the same egress and
  account, and the snapshot says nothing about it (TS contract §4.4).

**The five eligibility conditions, each a checked gate.** `grok_jail_surface.eligibility(binary_sha256)`
returns the first failing condition or `None`. It is called before `--new-grant` and
`--rehearse` (conditions 1 to 4 must pass), and at L6 and at the final spawn of a board
launch (all five must pass). Any failure is `grok_tool_surface_unverified`.

| # | Condition | Evidence and check | Authority, binding |
|---|---|---|---|
| 1 | SL-3's enforcement is installed | `grok_jail_surface.ENFORCEMENT` is importable from the installed package and names the §2.3 list revision | the installed release |
| 2 | the protected set is pinned for the image | `PROTECTED_SETS[binary_sha256]` exists | SL-2's reviewed source |
| 3 | the masked-projection confirmation is recorded | a record `grok-jail-confirmation-<binary_sha256>.json`, schema `grok_jail_confirmation.v1`, under the private record root (TS contract §3.2 file checks), or the same object in the jailed catalog entry; fields: image sha256, `launch_digest` per architecture, `jail_context_digest`, the observed outcome (inference request reached; no `/v1/settings`, no `/v1/models`; masks and config unchanged), the owner's approval id and date | the owner's approval of the offline, credential-free, no-egress launch; bound to the image, `launch_digest` and `jail_context_digest` |
| 4 | the real-launcher boundary check passed | a record `grok-jail-boundary-<launch_digest>.json`, schema `grok_jail_boundary.v1`, or the same object in the catalog entry; fields: hosted run id, head, `launch_digest`, `jail_context_digest`, BA-J5 result `passed` with no skipped case | the hosted CI run, recorded with `--hosted-check`; bound to `launch_digest` and `jail_context_digest` |
| 5 | an admitted jailed record exists | §3 record for the image and `staged` argv digest, `measured`, `admitted`, its `jail_context_digest` and `launch_digest` equal the running values | §5 measurement, catalog or host-local |

**Carry-forward.** Conditions 3 and 4 bind `launch_digest` and `jail_context_digest`, not
`runtime_digest`. A release that changes neither (SL-6's catalog-only release, whose files are
outside the runtime hash and outside the jail argv) keeps them valid; SL-6 copies both objects
into the catalog entry. A release that changes either needs a new confirmation or boundary
run.

**If the confirmation fails.** SL-3 stops, and the owner chooses between (a) a roadmap
amendment admitting a non-mutating jailed form (`NON_MUTATING_TOOLS`), which gives up
EC-GROK-1's tool write, and (b) waiting for a later image or erratum.

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

- **Provisional, L6.** `grok_jail_surface.precondition_code()` passes only if
  `eligibility()` (§2.4) finds all five conditions, and on a jailed receipt that matches the
  record.
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
| `seat-window probe-tools --vendor grok` | inspection. `seat_window.py` is unchanged; it calls `panel_invoker.probe_grok_tools`, which SL-3 extends: when a Grok profile is registered and `grok_jail_surface` is installed, the `staged` row resolves the jailed subject through `grok_jail_surface.resolve_subject()`, reads and writes only the jailed receipt store and reports the jailed basis; every other form reports refused. Its aggregate exit is unchanged and is not a gate. |
| `measure-tools --verify-probe final --grant <id>` | the grant-backed check after `--aggregate` (§7.1) |
| the installed-catalog check | after SL-6 (§7.1) |
| every other row of the TS contract §4.4 table | unchanged |

### §4.4 One final verifier, two modes

`verify_jail_launch_context(jail, *, mode, proxy, holder, cwd, command)` runs inside the jailed
`_popen` branch of `_run_leg_with_liveness`, after every other jail probe (including the
pre-Popen probe) and immediately before `launch_provider`, against the objects about to be
spawned. `mode` is `board` or `measurement`.

**Common checks (both modes).**

1. **Binary.** The bound source is the actual executable `_resolved_jail_subject` returned,
   standalone subjects included. SL-3 checks its whole ownership chain itself: every path
   component, from `/` to the executable, is owned by root and not group- or other-writable,
   with `seat_subject`'s existing owned-directory check (the one its pin walk applies to
   `MANAGED_AUTHORITY_PIN`) applied to each component; resolving the subject alone does not
   discharge this. Its sha256, read now, equals the record's (board) or the grant's image
   (measurement). `_read_grok_receipt`'s host-path resolution is not used.
2. **Owner argv.** The actual argv's normalised `launch_digest` equals the expected production
   value; any dependency projection refuses.
3. **Projections and masks.** The mount policy as §2.3 and §2.4 settle it; no shadow mount; no
   symlink component. **Per-launch bytes (local, not in the shared digest):** the projected
   credential and `agent_id` equal `GrokSeatCredential.digest` of the exact staged copy; the
   projected CA equals the CA digest of the proxy this launch owns
   (`seat_egress_proxy`); the projected config equals `SEAT_CONFIG_SHA256`. A mismatch refuses.
4. **Cwd and argv.** cwd exactly `/seat/tree`; argv digest equals `staged`'s; production model
   and effort.
5. **Proxy and holder.** The proxy is this launch's and live, with the holder pid, network
   namespace and socket the egress prefix names (TS contract §4.6), its effective allow-list
   is `grok-review` with the expected content digest, and its budget is none (board), 0
   (rehearsal) or 1 (counted launch).

**Board mode** additionally requires all five eligibility conditions and a jailed receipt that
matches the record, re-resolved now (a withdrawn record, a replaced catalog route or a moved
digest refuses).

**Measurement mode** replaces the record with the reservation: it requires conditions 1 to 4,
and **atomically consumes** the reservation's admission by creating `admission-<reservation
id>` with `O_CREAT|O_EXCL` in the grant directory, immediately before spawn. The admission
binds the grant id, the reservation id, the image sha256, the `staged` argv digest and cwd,
the projection directory's device and inode, the sink's device and inode, the holder's pid
and network-namespace inode, the proxy socket and the stage budget. Its two declared
differences are verified on the actual objects: the sink is a fresh, empty, 0700 directory
under the private record root, writable by the dropped UID (proven by a probe write and read
in the jail before the provider starts), and removed in `finally` and by the abandoned-scratch
purge; the proxy is the reservation's budgeted proxy. The admission cannot be consumed twice.

The function issues a `JailLaunchContext` mark binding these objects; the spawn admits only
that mark for that exact argv and jail. Every failure is `grok_tool_surface_unverified`
before any process starts.

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
4. records the admission of §4.4 (not yet consumed). Only §4.4's measurement mode consumes it,
   at the real spawn; replaying it against another launch, proxy, sink or a second spawn
   refuses.
5. **Restart.** A reservation whose admission was consumed and that has no settlement is an
   unresolved settlement: charged in full (BA-1), never resumed and never reusable as a retry.
   A retry is a new reservation, refused while any reservation of the grant is live or
   unresolved.

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
  `measured` with identical `tools` and `definitions_sha256`, and the passed rehearsal and
  every label record the same normalised **production** `launch_digest`; otherwise nothing is
  published (`surface_unstable`).
- **Publication gate (erratum 8 r3 item 7).** `--aggregate` refuses with `context_mismatch`, and
  removes any jailed host-local record for the binary, unless every result and the passed
  rehearsal carry the running `runtime_digest` and the running `jail_context_digest`. A
  release installed between the last launch and the aggregate therefore publishes nothing.
- `admitted` is `_grok_tools_admitted(staged, tools)`; a measured, not admitted surface is
  evidence only.
- Redaction, retention, the purge and the publication lock: TS contract §5.7 and §5.9, with
  §2.3's stricter rule for a failed launch's stdout and stderr.

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
  `eligibility()` conditions 1 to 4 passing on the installed release (checked by
  `--new-grant` and `--rehearse`); `VL` and `VL2` passed on the seat host; where a Gemini
  window refresh is required, it is separately authorised and completed first, on the same
  installed release;
  the provider-free Grok qualification (`seat-sandbox qualify --leg grok`) current for the
  production key; erratum 8 item 4's staging check; a quiet slot, both shared-compute locks,
  the memory-PSI gate and `MemorySwapMax=0` scopes, as for D4.
- **Stops.** The rehearsal passes only on the expected observation; anything else stops before
  the pilot with no request spent. The runtime stop and publication gate of erratum 8 r3 item 7
  and §5.4 apply; a runtime drift during the grant stops it, and the Gemini refresh is
  repeated on the new release before any resumption.
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
  naming leg `grok` and its qualification key.
- **Grant-backed check**, after `--aggregate`: `measure-tools --verify-probe final --grant <id>`
  reads this host's grant and aggregate and passes only if the jailed `staged` row is
  `frozen_measurement`, admitted and sourced from the host-local jailed record, and every
  other form is refused.
- **Installed-catalog check**, after SL-6, with no grant: `phase-loop seat-window probe-tools
  --vendor grok` on a host with no jailed host-local record; the `staged` row must read
  `passed: true`, `basis: frozen_measurement`, `source: catalog`. Its exit status is not the
  gate; the row is.
- Both checks are exercised through the installed entry points (`phase-loop`), by SL-4 against a
  recording runner and by SL-6 against the shipped catalog.
- SL-4 ships the script as `docs/ops/grok-jail-measurement.md`.

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

- **Where the fixture is delivered.** K-1 keeps the board input unchanged, so the canary is not
  on the board. It is the Grok supplier's **measured** launch input:
  `seat_window_supply_grok.build_qualification_input(layout, base)` returns a fixture that
  stages a fresh random canary path, absent beforehand, and an instruction to create that file
  with given bytes using the write tool and then run one named shell command in the clone. Its
  digest is the record binding's `measured_input_sha256`.
- **Assertions, by the parent after the measured launch:** the canary exists only in the
  per-launch copy with exactly the requested bytes; the authorised stage's hash, every other
  tree path (stubs of §2.4 excluded by name) and a sibling seat's tree are unchanged; the
  stream facts show at least one write tool step and one run tool step, a terminal model turn
  and no cancellation (agent-harness#1091). The board leg proves the leg runs in the window
  composition.
- **Binding.** The record names the installed release, the image digest, the admitted `staged`
  argv digest, `jail_context_digest` and `measured_input_sha256`.
- **Fails.** A no-tool reply, a read-only run, a missing or altered canary, a canary outside
  the copy, or a cancelled turn each fail the relevant assertion. The surface prompt cannot
  supply this evidence.

## §8 Amendments to the TS contract (ruling 1)

Applied by one pointer erratum, **erratum 9**. **Writer:** the coordinator's planning
delegate, as a plan amendment under `claude-plan-phase` (not a lane, and not SL-7), in one
planning-only commit after erratum 8 merges: it adds erratum 9 to the TS contract and re-pins
the TS contract in the plan's frozen inputs and its manifest row. SL-3 and SL-4 are not
dispatched until that commit is on their base.

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
> eligible only while all five conditions of its §2.4 hold, each a checked gate: its
> enforcement installed, the protected set pinned for the image, the masked-projection
> confirmation and the real-launcher boundary check recorded for the image's launch digest,
> and an admitted jailed record; otherwise it stays closed. Everywhere else erratum 8's item
> 1d stands, including the unjailed frozen-basis `staged` refusal. It amends §3.1–§3.3, §4.1–§4.4, §5.1, §5.3, §5.4, §5.7, §5.8, §5.10 and §10
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
  TS contract with the §8 planning amendment's erratum 9. The second lander rebases.

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
| 2026-12-02 12:00 | Train A installed on every seat host, and the K-1 snapshot rule installed on every **verifying** host; coverage recorded per host: `seat-window matrix` shows Grok `jailed` with no exception (or the renewed expiry), and the installed verifier is the snapshot one | host owner |
| 2026-12-03 | only if Train A carried SL-2: `seat-sandbox qualify --leg grok` on the designated host (SL-5) | host owner |
| 2026-12-04 00:00 | expiry; the exception is absent or renewed on every installed host | — |

- **Fallback, without a second build.** SL-8 depends on nothing and rides Train A in SL-2's
  place. It replaces the shared expiry constant with a per-vendor map (Grok renewed to the
  signed date, no later than 2026-12-18; others unchanged) and fills `renewal_record`. If the
  owner declines the renewal and SL-2 misses the cut, Grok's exception expires; windows
  launched after the expiry then fail on the Grok snapshot until a recovery install lands.
- **Install miss.** If Train A or the snapshot verifier cannot be installed on a host by
  2026-12-03T12:00Z, no window launches or verifies on that host until it is. Existing records
  are protected by the snapshot rule only where that verifier is installed; a legacy W1
  record's expiry relief also needs K-1's journal and witness (K-1 contract, legacy-record
  rule). Other exceptions keep their original expiry.
- **Gemini on both sides of the boundary.** SL-2's and SL-8's tests verify a fixture Gemini
  record observed before 2026-12-04 at a clock before and after the boundary, under the
  snapshot rule, with Grok registered (SL-2) and renewed (SL-8).

## §12 Binding acceptance criteria of the lanes

- **BA-J1 (SL-3) — isolation in the real jailed child.** One child of the real Grok jail shows
  both an allowed request through the proxy to a fixture upstream and a refused direct
  connection to a host-reachable listener (first proven reachable). Mandatory hosted check
  under `PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1`; a missing prerequisite fails.
- **BA-J2 (SL-3) — spawn-boundary substitutions.** Each of these, applied after the gate and
  before spawn, refuses with nothing spawned: a provider source failing the root-owned pin
  walk, a binary whose digest differs, a changed or extra projection file, a dependency
  projection, a removed, retyped or shadowed mask, a symlinked destination, another proxy,
  holder or network namespace, a proxy with the wrong allow-list or budget, a withdrawn record,
  a different cwd, and each eligibility condition removed alone. The mark cannot be built
  outside `verify_jail_launch_context`.
- **BA-J2a (SL-3) — the shared digest is stable.** One positive comparison: a stand-in launch
  and a production-shaped fixture launch, with different credentials, `agent_id`, CA bytes,
  descriptor numbers, proxy ports and per-launch directories, produce the same
  `launch_digest`. A launch whose projected credential differs from its staged copy, or whose
  projected CA differs from its proxy's, refuses at check 3.
- **BA-J3 (SL-3) — receipts.** Unjailed frozen, legacy and listing receipts refuse at the jailed
  spawn; a jailed receipt refuses in `launch_owned`; a jailed probe does not overwrite an
  unjailed receipt.
- **BA-J4 (SL-2, extended by SL-3) — the dropped child.** A stand-in under the actual seat UID in
  the real Grok jail can read the three projections and the CA, cannot append, truncate,
  rename over, unlink or chmod any of them, cannot rename `.grok` (or `.config`) away, can
  write both tmpfs mounts and `.grok` itself, cannot create inside a mask; a planted
  12-character suffix written to `.grok/logs` and the credential bytes are absent from
  seat-out, the review dir, the grant, the output directory, the record root and the evidence
  after teardown. SL-3 adds, through the real composed jail with a stand-in, for a short and a
  long credential shape: the suffix copied into stdout and returned text at use
  (`grok_seat_token_in_output`, nothing retained); into a failed measurement's stdout and
  stderr (no `provider.log` written); into the definitions artifact and the sessions sink
  (`artifact_refused`, `--require-measured` fails, the charge stands, both readers accept the
  record); and a crash after spawn (the projection directory and the sink are gone after the
  abandoned-scratch purge, and no retained path holds the suffix).
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
- **BA-J7 (SL-3 verifier, SL-4 flow) — measurement admission.** With no receipt, a full
  rehearsal and first launch run through `prepare_measurement` and the measurement mode of
  §4.4; each of these refuses with nothing spawned: a swapped, non-empty, pre-existing or
  unwritable sink; a swapped proxy, holder or budget (0 for the rehearsal, 1 for a counted
  launch); a missing reservation; an admission consumed twice or replayed against another
  launch; a retry while a reservation is live or unresolved; and after a restart, reuse of a
  consumed, unsettled reservation. Publication refuses when the rehearsal and labels disagree
  on the production `launch_digest`.

## §13 Coordination

- **Erratum 8 (final at r3).** Consumed by reference (the projection, `SEAT_FIXED_INPUTS`,
  `NON_MUTATING_TOOLS`, per-image refusals). SL-1 pins the seat-config digest as an input; SL-3
  asserts it equals `grok_tool_surface.SEAT_CONFIG_SHA256`. SL-3 waits for E8-A and SL-4 for
  E8-B. Its item 9 defers to §7.
- **K-1.** One owner per piece. GROK SL-3's jailed leg takes `window_board:
  _WindowBoardLegRuntime | None` (pre-existing class) and calls `start`, `finish` and
  `finalize_proxy` in `_exec_jailed_gemini_leg`'s order. Delivering the runtime to the Grok
  leg (`_parent_infer` or `window_board_for`) is K-1's kit code. K-1's Grok adapter starts
  after GROK SL-3 and SL-6, implements §7.3, and registers Grok's `WindowVendorData`. **Gate:**
  before K-1's kit lane or Grok adapter lane starts, K-1 aligns these sections (requested text):
  - contract §5.4, Grok row: "grok — the jailed Grok leg calls `start`, `finish` and
    `finalize_proxy` itself (GROK SL-3); the kit delivers the runtime to it";
  - contract §5.2–§5.3: the board input stays unchanged; the Grok fixture is the supplier's
    `measured` input, bound by `measured_input_sha256` (§7.3 here);
  - contract §10.D and the amendment's SL-8 prerequisite: replace "a measured tool surface …
    so `probe-tools` passes on the designated host" with "`grok_jail_surface.staged_admission`
    true on the installed release (jail contract §2.4, all five conditions)"; the adapter
    starts after GROK SL-3 and SL-6;
  - the amendment's GROK coordination rows (hook in GROK SL-2 or the kit): replace by the
    split above; its two edits to the GROK plan are subsumed by this amendment.
- **Assumption A-1: a degraded Grok co-seat.** Until SL-6, Grok resolves degraded at L6 on
  every board. This plan assumes another vendor's four-seat row window can still pass with
  Grok present in the admitted composition and refused at L6, if the president completes
  (the composer requires the seat's availability and auth, and the reducer requires retained
  records and a completed president, not a model turn from each leg; inference from source).
  **Confirmation point:** a K-1 provider-free end-to-end assertion (full composition, Grok
  retained L6 refusal, the subject passes, valid president result and snapshot, only the
  subject's row changes), frozen in K-1 before the first post-Train-A row-window grant. If it
  fails, Grok admission (SL-6) is on every row window's path and the schedule is
  re-planned.
- **GROKROLL.** No GROKROLL pin moves. Its status query reads the unjailed catalog only;
  teaching it the jailed catalog is a GROKROLL follow-up.

## §14 Open questions

1. Assumption A-1 (§13) awaits its K-1 confirmation point.
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
- R5 → §2.3, BA-J4: memfd projections at 0444 and 1777 tmpfs, proven in the dropped child (memfds superseded in r3 by path binds, §16).
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

## §16 Revision r3 (2026-11-21)

Review `review-amendment-r2-sol.md` (CHANGES REQUIRED), required items only:

- C1 builder and SL-2 input → §2.3 (path binds from a per-launch 0700 projection directory, no
  descriptor handoff, no builder or `seat_uid` edit; the ordered mount list), §2.4 (SL-2 lands
  `PROTECTED_SETS` from erratum 8 r3's frozen text: a complete input; SL-3 asserts equality
  with E8-A). The validator/SDK pin table of §10 is unchanged.
- C2 final launcher → §4.4 (one verifier, board and measurement modes, common checks, atomic
  admission consumption at the real spawn, sink and proxy identity and budget, root-owned
  source immutability), §5.1 items 4–5 (restart), §5.4 (production `launch_digest` agreement),
  BA-J2, BA-J7.
- C3 masks and eligibility → §2.3 (ordered list superseding erratum 8's `.grok` rule for the
  jail, no shadow mount, ancestor and no-symlink rule for home and tree), §2.4 (canonical
  coverage, tree stubs, the five conditions as `eligibility()` with evidence formats,
  authority and binding; 1–4 before grant and rehearsal, all five at L6 and board spawn;
  carry-forward), §7 preconditions, erratum 9 text (§8).
- C4 suffix scan → §2.3 (handoff object, channel table, the failed-measurement stdout and
  stderr rule, `artifact_refused` semantics), BA-J4.
- C5 K-1 and CLI → §13 (gate with the exact K-1 sections), §7.3 (fixture as the `measured`
  input), §4.3 (probe seam in `probe_grok_tools`, no `seat_window.py` edit), §7.1 (grant-backed
  and installed-catalog checks), §8 (re-pin writer named).
- Dispositions: R2's operational correction → §11; erratum 8 r3 requirement 3 → §7.
- Degraded co-seat → assumption A-1 with a K-1 confirmation point (§13).

## §17 Revision r4 (convergence, 2026-11-21)

Review `review-amendment-r3.md` and the coordinator's ruling `DIAGNOSIS-r3.md`.

- **C2 closed.** §2.2: `launch_digest` is a shared digest, with role placeholders for
  per-launch directories, descriptors and proxy operands; it keeps the ordered policy and
  `SEAT_CONFIG_SHA256` and excludes credential, `agent_id` and CA bytes. §4.4 check 3 verifies
  those bytes per launch against their own digests; check 1 has SL-3 check the executable's
  whole ownership chain. BA-J2a gives the positive cross-fixture comparison and the
  projected-byte refusal.
- **Stale attribution struck.** Erratum 9 and the TS re-pin belong to the §8 planning
  amendment, not SL-7.
- **C1 and C3 stopped on one question (Q-r4).** The ruling adopts E8-A's sealed memfd
  `--ro-bind-data` config and `SEAT_FIXED_INPUTS` treatment by reference. Read against the
  code, neither main nor E8-A implements two things the jailed `staged` seat needs:
  1. **a descriptor handoff into the seat jail.** E8-A's memfd projection is in the unjailed
     `seat_profile` composition (`panel_invoker.py`); `seat_jail.build_seat_jail` passes only
     the bundle, instructions, token, dependency and seccomp descriptors, and `owner_binds`
     owns none. Main's implemented jailed-config projection is Gemini's: a staged host
     directory bound read-only over the config dotdir, writable children bound over named
     entries, and the CA by read-only path bind (`seat_jail._gemini_binds`);
  2. **protection of creatable inputs while a writing tool runs.** E8-A's treatment for every
     fixed input except the config is "absent from the seat's view at the final check", with
     `staged` never eligible because nothing then stops a tool creating one. Masks over the
     home's other inputs and over the writable tree's discovery paths exist in neither.

  **Q-r4.** Which mechanism does GROK adopt for the jailed `staged` seat?
  - **A (recommended):** main's jailed-config pattern for the config, credential and home
    inputs (a staged `.grok` directory bound read-only, holding E8-A's 424 bytes under
    `SEAT_CONFIG_SHA256` and the access-only copy; writable children bound over named entries,
    as Gemini's; the CA by read-only path bind), plus one new step for the tree: pre-created
    mount points in the per-launch copy with read-only empty binds over the discovery paths.
    No builder edit. The config is delivered as a read-only file, not a memfd.
  - **B:** E8-A's memfd literally: add a Grok descriptor to `build_seat_jail`'s `pass_fds` (a
    shared-builder edit that moves the SDK proof region `build_seat_jail` and needs the pin
    table amended), plus the same tree step.
  - **C:** E8-A's absence rule only: jailed `staged` stays closed; the jailed seat then admits
    only non-mutating forms, and EC-GROK-1's tool write needs a roadmap amendment.
  - **D:** pause GROK until E8-A and E8-B merge, then amend against merged code.
