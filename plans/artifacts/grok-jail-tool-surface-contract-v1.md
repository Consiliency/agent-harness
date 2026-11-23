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
| Seat home | the per-launch fresh `seat-home`, with `.grok` the read-only staged directory of §2.3 and the masks of §2.4; at spawn the home's mount list is exactly §2.3's ordered list. |
| Environment | the profile's allow-listed environment plus `HTTPS_PROXY` and `SSL_CERT_FILE`; no `GROK_*` or `XAI_*` variable. |
| Managed config | the two `/etc/grok` paths absent on the host and in the jail view; `/etc/claude-code/managed-settings.json` absent from the jail view (TS contract erratum 1). |
| Fixed inputs | every path of E8-A's `SEAT_FIXED_INPUTS`, and every `DISCOVERY_PATHS` entry at `/seat/tree`, has the treatment §2.4's table gives it, checked on the actual mount view. |
| Egress | allow-list `grok-review`, its content digest; the jail's proxy-only namespace. |
| Tools | the receipt's admitted names are a subset of the `staged` form's `--tools` allow-list (`_grok_tools_admitted`); write and run tools are allowed only because §2.4 holds. |

### §2.2 Digests

- `jail_context_digest()`: sha256 of the canonical JSON (keys sorted, separators `,` and `:`,
  ASCII, no trailing newline) of `{schema: "grok_jail_context.v1", composition:
  "seat_jail.build_seat_jail+profile:grok", home: "/seat/home", seat_config: {path,
  sha256: SEAT_CONFIG_SHA256, projection: "ro-staged-dotdir"}, mounts: [the ordered list of
  §2.3], protection: {image_sha256, the §2.4 table}, environment:
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

### §2.3 Projections, the ordered mount list and the scan values (option A, r5)

The coordinator's ruling on Q-r4 adopts main's Gemini-style jail projection
(`seat_jail._gemini_binds`): a staged dot-directory bound read-only, writable children bound
over named entries, and the CA by read-only path bind. `build_seat_jail`, `_owner_argv` and
the SDK proof region `build_seat_jail` are not edited.

**The staged `.grok` directory.** Per launch, before `seat_uid.handoff`, the launch site (SL-3;
for the provider-free qualification, `seat_profile_grok.qualification_shape`, SL-2) writes
`<review_dir>/grok-config/`, the Grok counterpart of Gemini's `<review_dir>/gemini-config/`,
reached through the existing `OwnerPaths.provider_config` field (placeholder
`<provider-config>`):

| Entry | Type, mode | Content |
|---|---|---|
| `config.toml` | file, 0444 | E8-A's 424 bytes; sha256 `SEAT_CONFIG_SHA256` |
| `auth.json`, `agent_id` | files, 0444 | the access-only copy and the agent id (`seat_grok_credential`) |
| `logs/`, `sessions/` | empty dirs, 0555 | mount points for the writable entries |
| `.config-init.lock`, `managed_config.lock` | empty files, 0444 | mount points for the two lock files the client writes (erratum 8 r2 item 1d, launch 7) |

The directory itself is 0555 and holds nothing else. Mode 0444 and 0555 make it readable and
traversable by the dropped seat UID without Gemini's group handoff, which is Gemini-specific
in `seat_uid.handoff`; the review directory (0700, operator-owned) keeps it private on the
host. `seat_uid.py` is not edited (its bytes are a validator input). If the dropped UID cannot
read it (BA-J4), SL-2 STOPs.

**The mask sources.** `<review_dir>/grok-masks/` holds `empty` (zero bytes, 0444) and
`empty.d/` (empty, 0555). The profile derives its path from `paths.provider_config` (its
sibling), as `_gemini_writable_source` derives Gemini's writable sources from `paths.home`.

**The writable sources.** `<home>/.grok-rw/` inside seat-home, which `seat_uid.handoff`
already hands to the seat UID, holds `.config-init.lock` and `managed_config.lock` (empty
files). Seat-home is per launch and removed with the jailed seat.

**The ordered mount list.** After the builder's `--bind <tree> /seat/tree`, `--bind <home>
/seat/home` and `--bind <out> /seat/out`, the profile's `owner_binds(paths)` appends exactly,
in order:

1. `--ro-bind <provider-config> /seat/home/.grok` (the read-only dot-directory);
2. `--perms 1777 --tmpfs /seat/home/.grok/logs` and `--perms 1777 --tmpfs
   /seat/home/.grok/sessions` (during a measurement, the second is `--bind <home>/.grok-rw/sessions
   /seat/home/.grok/sessions`, §5.1);
3. `--bind <home>/.grok-rw/.config-init.lock /seat/home/.grok/.config-init.lock` and the same
   for `managed_config.lock`;
4. `--ro-bind <egress-ca> /seat/egress-ca.pem`;
5. the home masks of §2.4, in table order;
6. the tree masks of §2.4, in table order.

No other mount may have a normalised destination at, below or above (between the home or tree
bind and) any entry of this list, and none may follow it. Every destination is absolute,
`posixpath.normpath`-stable and has no symlink component.

**Integrity at spawn (§4.4 check 3).** The final check opens each staged file `O_NOFOLLOW` and
requires a regular file, mode 0444, operator-owned, with exactly the expected bytes: the
config's sha256 equal to `SEAT_CONFIG_SHA256`, the credential files equal to
`GrokSeatCredential.digest`, the CA equal to the CA digest of this launch's proxy. The staged
directory must hold exactly the table's entries.

**Difference from E8-A, recorded.** The unjailed seat (`panel_invoker.seat_profile`, grok
branch, with E8-A's `grok_tool_surface` check) projects the config as a sealed memfd with
`--perms 0444 --ro-bind-data`, checked by seals, size and `pread`. The jailed seat projects the
same bytes as a read-only file inside a read-only bind, checked by digest at each launch. Both
are immutable from inside: a read-only bind mount cannot be written (`EROFS`), and its mount
points cannot be renamed over or unlinked (`EBUSY`). The memfd path does not exist in the seat
jail because `build_seat_jail` passes only its own descriptors.

**Code ownership of the two config paths (no drift).**

| Path | Owner | Bytes from |
|---|---|---|
| unjailed `grok_seat_context.v1` | E8-A: `panel_invoker.seat_profile` (grok branch) and `grok_tool_surface`'s projection check | `grok_tool_surface.seat_config()` |
| jailed `grok_jail_context.v1` | GROK: `seat_grok_credential` (SL-1, staging), `seat_profile_grok` (SL-2, mounts), `grok_jail_surface` (SL-3, final check) | the same function once E8-A merges |

Until E8-A merges, SL-1 writes the bytes whose sha256 is the pinned input; SL-3 asserts
`seat_grok_credential`'s bytes equal `grok_tool_surface.seat_config()` and fails on any
difference, so the two paths cannot drift.

**Ephemeral paths.** `.grok/logs` (the client log carries the token's last 12 characters) and
`.grok/sessions` are tmpfs at use and vanish with the jail.

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
| provider stdout and stderr of a **failed** measurement (TS contract §5.9's private `provider.log`) | stricter than the TS contract: scanned before it is written; on a hit it is not written; otherwise kept private with the 7-day expiry |
| the definitions artifact and the sessions sink | scanned before retention or extraction; a hit is `artifact_refused` |
| `.grok/logs`, `.grok/sessions` (use) | tmpfs, never retained |

`artifact_refused` follows erratum 8 r3: no retention, extraction, reprocessing or publication;
the settled charge stands; `--require-measured` fails; the result and evidence readers accept
the status.

### §2.4 Fixed-input protection: why `staged` is eligible in the jail (option A, r5)

Erratum 8 r2 item 1d leaves `staged` ineligible because a writing tool can create a fixed input
during the launch. Under option A no tool can, because every fixed input is in one of three
places a seat process cannot write. Treatments come from E8-A's code (`SEAT_FIXED_INPUTS`,
`SEAT_FIXED_INPUT_EXCLUSIONS`, `MANAGED_CONFIG_PATHS`, `CHILD_ABSENT_POLICY_PATHS`) and main's
`DISCOVERY_PATHS`.

**The protection table** (`seat_profile_grok.JAIL_PROTECTION`, keyed by image sha256; the entry
for `add4d201…`, grok 1.0.92, landed by SL-2):

| Inputs | Treatment | Why mid-launch creation is impossible |
|---|---|---|
| `.grok/config.toml` | **projected**: staged file, bytes bound by `SEAT_CONFIG_SHA256` | inside the read-only bind of `.grok`: `EROFS` on write, `EBUSY` on rename over or unlink |
| `.grok/auth.json`, `.grok/agent_id` (exclusions) | **projected**: staged files, bytes checked against the staged copy's digest per launch | as above |
| `.grok/rules` (exclusion, prompt-only) | absent from the staged directory | inside the read-only `.grok`: cannot be created |
| every other `.grok/…` entry of `SEAT_FIXED_INPUTS`: `managed_config.toml`, `requirements.toml`, `managed_config_cache.json`, `managed_config.sig.json`, `managed_identity.sig.json`, `staged/managed_config_refresh.json`, `models_cache.json`, `experiments_state.json`, `campaigns_state.json`, `skills`, `agents`, `bundled/agents`, `bundled/skills`, `commands`, `plugins`, `installed-plugins`, `hooks`, `hooks-paths`, `disabled-hooks`, `workflows`, `lsp.json`, `sandbox.toml`, `trusted-plugins`, `trusted-hook-projects`, `trusted_folders.toml`, `mcp_preferences.json`, `mcp_credentials.json`, `settings.json` | **absent inside the read-only `.grok`** | `.grok` is a read-only bind, so nothing can be created in it; nested entries (`staged/…`, `bundled/…`) have absent parents that cannot be created either. `.grok` itself is a mount point and cannot be renamed away. The only writable places inside it are the `logs` and `sessions` tmpfs and the two lock-file binds, none of them a fixed input. |
| `/etc/grok/managed_config.toml`, `/etc/grok/requirements.toml`, `/etc/claude-code/managed-settings.json` | **absent outside writable mounts** | absent on the host (`/etc/grok`) and in the jail view (all three); `/` is `--remount-ro` |
| `.claude.json`, `.mcp.json` (home) | **masked file**: `--ro-bind <grok-masks>/empty <path>` | a read-only file mount point: not writable, not replaceable, not removable |
| `.claude`, `.cursor`, `.agents` (home) | **masked directory**: `--ro-bind <grok-masks>/empty.d <path>` | a read-only empty directory mount point: nothing can be created in or over it |
| `.config/grove` (home) | **masked directory** under a protected ancestor: `--perms 1777 --tmpfs /seat/home/.config`, then `--perms 0555 --dir /seat/home/.config/grove`, then `--ro-bind <grok-masks>/empty.d /seat/home/.config/grove` | `.config` is a mount point, so it cannot be renamed away to plant a new `grove`; `grove` is read-only |
| `.agents`, `.claude`, `.cursor`, `.grok` (tree, `DISCOVERY_PATHS`) | **masked directory** at `/seat/tree/<entry>` | read-only mount points over the per-launch copy; the hot-reloaded `<cwd>/.grok/` cannot gain an entry |
| `.mcp.json` (tree, `DISCOVERY_PATHS`) | **masked file** at `/seat/tree/.mcp.json` | as for the home file masks |

- **Mount points.** bwrap, running without DAC capability, cannot create a mount point in the
  seat's directories, so the launch site creates them first, as Gemini's staged directory
  carries its "three empty mount points": in seat-home before `seat_uid.handoff`, an empty file
  at `.claude.json` and `.mcp.json`, empty directories at `.claude`, `.cursor`, `.agents` and
  `.config`; in the per-launch tree copy, after its `staged_tree_sha256` check and before
  handoff, an empty entry of the table's type at each absent `DISCOVERY_PATHS` entry. An entry
  that exists in the stage keeps its type if it matches and is covered as it stands (its bytes
  stay in the authorised stage); a symlink, a symlinked component or a mismatched type refuses.
  The tree stubs are excluded, by name, from EC-GROK-1's "everything else unchanged"
  comparison.
- **Coverage.** No mask is mounted inside another: the table has no entry with an ancestor in
  the same table except `.config/grove`, whose ancestor is the tmpfs, not a mask. The ancestor
  rule holds: every protected path's ancestors below the home or tree bind are mount points
  (`.grok`, `.config`), and above `/seat/tree`, `/seat` and `/` are read-only.
- **Drift.** Once E8-A merges, SL-3 asserts that the table's inputs equal E8-A's
  `SEAT_FIXED_INPUTS` and `SEAT_FIXED_INPUT_EXCLUSIONS` and main's `DISCOVERY_PATHS` exactly,
  and fails on any difference. An image with no table entry has no eligible `staged`.
- **Client writes that fail.** Launch 7 also showed the client creating
  `installed-plugins/registry.lock` (inside a fixed input) and its docs and worktree database.
  Under option A those writes fail (`EROFS`). Whether the client tolerates that is what
  condition 3's confirmation observes. Adding a writable entry that is not a fixed input is a
  jail contract erratum before the grant; a fixed input is never made writable.
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
| 2 | the protection table is pinned for the image | `JAIL_PROTECTION[binary_sha256]` exists | SL-2's reviewed source |
| 3 | the option-A projection confirmation is recorded | a record `grok-jail-confirmation-<binary_sha256>.json`, schema `grok_jail_confirmation.v1`, under the private record root (TS contract §3.2 file checks), or the same object in the jailed catalog entry; fields: image sha256, `launch_digest` per architecture, `jail_context_digest`, the observed outcome (inference request reached; no `/v1/settings`, no `/v1/models`; staged files and masks unchanged), the owner's approval id and date | the owner's approval of the offline, credential-free, no-egress launch under the exact §2.3 projection; bound to the image, `launch_digest` and `jail_context_digest` |
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
- **Production writers (r7).** Each of the two jailed measurement outputs has one writer in
  production:
  - **The jailed host-local record** (`grok-jail-surface-<binary_sha256>.json`) is written by
    **SL-4**, in `grok_tool_surface.py`'s measurement region, through `measure-tools
    --aggregate` for a jailed grant only. It is written after the §5.4 agreement rule and
    publication gate pass, through `grok_jail_surface.write_private` and after
    `check_jail_surface`. No other code writes it.
  - **The jailed probe receipt** (`grok-jail-tools-<binary>-<argv>.json`) is written only by
    `grok_jail_surface.write_jail_receipt`. That function is called only from
    `panel_invoker._grok_jailed_probe` inside `probe_grok_tools`, which is SL-3's code and is
    already landed. In production it is reached through `phase-loop seat-window probe-tools
    --vendor grok` and through SL-4's `measure-tools --verify-probe final --grant <id>`, whose
    probe is that same probe (§7.1). It writes only while `staged_admission` holds, so the
    first jailed receipt on a host is written by the §7.1 grant-backed check, after
    `--aggregate`.

  SL-6 ships a record source (the catalog) and K-1's adapter reads `staged_admission`. Neither
  of them writes a receipt or a record. **Test (SL-4.1):** run through the installed entry
  point with a recording runner. Before `--aggregate`, `--verify-probe final` writes no jailed
  receipt. After it, the check writes exactly one, equal to `jail_receipt(...)` for the
  record, and the unjailed `tool_probe.v1` bytes are unchanged. A source scan finds no other
  caller of `write_jail_receipt`, and no writer of `grok_jail_surface.host_record_name(...)`
  (the jailed name) other than SL-4's `--aggregate`. The unjailed
  `grok_tool_surface.host_record_name` writers are a different name and are out of the scan.
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
| `seat-window probe-tools --vendor grok` | inspection. `seat_window.py` is unchanged; it calls `panel_invoker.probe_grok_tools`, which SL-3 extends. When `grok_jail_surface.resolve_subject()` resolves and `grok_jail_surface.staged_admission(binary_sha256)` holds for that subject (all five §2.4 conditions), the `staged` row resolves the jailed subject, reads and writes only the jailed receipt store and reports the jailed basis, and every other form reports refused. Otherwise the probe's result is identical to the unjailed probe's, and the TS contract suites stay unedited. SL-3's own tests show both branches, including each §2.4 condition removed alone giving the unjailed result. Its aggregate exit is unchanged and is not a gate. |
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
and verifies, without consuming it, the reservation's recorded admission against the actual
objects. The admission binds the grant id, the reservation id, the image sha256, the `staged`
argv digest and cwd, the staged `.grok` directory's device and inode, the sink's device and
inode, the holder's pid and network-namespace inode, the proxy socket and the stage budget.
Its two declared differences are verified on the actual objects: the sink is the fresh, empty
`<home>/.grok-rw/sessions` in this launch's seat-home, owned by the seat UID after handoff and
writable by it (proven before the leg by `grok_jail_surface.probe_sink`, §4.5 step M2), and
removed with seat-home in `finally` and by the existing cleanup of abandoned jailed seats; the
proxy is the reservation's budgeted proxy. The admission is **atomically consumed** later, by
the spawn hook of §4.5 step M5, by creating `admission-<reservation id>` with `O_CREAT|O_EXCL`
in the grant directory; it cannot be consumed twice. (r7: the r3 text consumed it here,
before `launch_provider`'s own qualification check and identity probe; see §4.5.)

The function issues a `JailLaunchContext` mark binding these objects; the spawn admits only
that mark for that exact argv and jail. Every failure is `grok_tool_surface_unverified`
before any process starts.

**Placement (r7).** "After every other jail probe (including the pre-Popen probe)" cannot
hold: the pre-Popen identity probe runs inside `launch_provider`, an SDK proof region. The
verifier runs immediately before `launch_provider`, as SL-3 built it; what must follow the
identity probe (consuming a measurement admission) is moved into `launch_provider`'s
`spawn_hook` (§4.5). "The jailed spawn" means a launch whose owner is a real `SeatJail`.

### §4.5 Measurement launch order (r7)

One counted or rehearsal launch of a jailed grant runs these steps in order. SL-4 owns every
step; the code it adds is named in §10.

- **M1. Prepare.** SL-4's stage (`grok_tool_surface.py`, measurement region) creates the
  reservation, starts its budgeted proxy and holder, and calls
  `panel_invoker._prepare_jailed_grok(..., measurement=True)` and then
  `grok_jail_surface.prepare_measurement`. The admission is recorded, not consumed (§5.1).
- **M2. Sink probe.** `grok_jail_surface.probe_sink(holder_pid, seat_id, sink)` runs this
  module's `sink-probe` verb in H as the dropped seat UID (`nsenter` into H, then
  `seat_jail.setpriv_drop(seat_id)`, then `seat_uid.trusted_module_argv`). As that UID it
  creates `.sink-probe-<16 random hex>` with `O_CREAT|O_EXCL|O_NOFOLLOW` and mode 0600,
  writes 32 random bytes, fsyncs, reopens it with `O_NOFOLLOW`, reads the bytes back and
  unlinks it. **Pass:** the helper exits 0 within 60 s; in H the sink is a directory owned by
  the seat UID, not a symlink, the bytes read equal the bytes written, and the sink is empty
  after the unlink; the parent then finds the sink's device and inode equal to the admission's
  `sink` binding and the directory empty. **Fail:** anything else, including a helper that
  cannot run, is `grok_tool_surface_unverified`. Nothing is spawned and the admission is not
  consumed. The probe runs in H and not in the jail. A second process in the launch's jail
  would mean spawning the single-use owner a second time. The identity probe runs in a probe
  jail of the same shape, not on this sink, and it is SDK proof code. The same credentials act
  on the same inode the jail binds, and check 2 (`launch_digest` with `measurement=True`,
  through `production_owner`'s exact `--bind <sink_source(home)> /seat/home/.grok/sessions`
  match) proves the bind is the one declared difference. Check 3 runs on the substituted
  owner and does not see the bind.
- **M3. Leg.** SL-4 calls `_exec_jailed_grok_leg(grok_seat, ..., measurement=<the
  JailedMeasurementLaunch>, read_sink=<SL-4's reader>)` (§5.1 "Launch path").
- **M4. Verify.** `_grok_jailed_spawn_check` runs §4.4 in measurement mode and issues the
  mark. Nothing is consumed.
- **M5. Spawn.** `_grok_jailed_spawn_check` returns a spawn hook in measurement mode, and
  `None` in board mode. It returns a hook only for a measurement that is a
  `JailedMeasurementLaunch` issued by `prepare_measurement` (`issuer is _ISSUER`). `_run_leg_with_liveness` passes it to `launch_provider` as
  `spawn_hook`. Inside `launch_provider` the order is: `_require_qualified_jail` (with the
  measurement clause of §5.1), the jailed identity probe, the capped launch's preflight, then
  the hook, then `Popen`. The hook is `grok_jail_surface.consume_admission`. It re-derives the
  binding from the actual objects, requires that the sink is still empty, and creates the
  admission file. It is the last step before `Popen`.

**The rule that makes the order safe.** The admission file is created only by the M5 hook, and
only after the qualification check and the identity probe have passed. When a step from M1
to M5 refuses before the hook returns, no admission file exists. The absence of that file
is positive proof that no provider process started for the reservation. SL-4 settles such a
reservation `unspawned` and charges no counted request (BA-1 still holds: the settlement
rests on positive proof). If the hook succeeded and the spawn then failed (`Popen` of the
capped helper, its attestation, or its gate), the admission is consumed and the reservation
has no settlement; §5.1 item 5 still applies to it and it is charged in full, although no
provider process ran. The same holds when `consume_admission` fails after its
`O_CREAT|O_EXCL` succeeded (a write or fsync error): the file exists, so the charge stands. How an
`unspawned` label resumes is **OWNER-DECISION r7-1** (§20). Until the owner rules, an
`unspawned` settlement stops the procedure, and nothing more is launched under the grant.

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
   - `.grok/sessions` is the reservation's sink, `<home>/.grok-rw/sessions`, a fresh empty
     directory in seat-home (handed to the seat UID by `seat_uid.handoff`, so the dropped UID
     can write it), bound at `.grok/sessions` instead of the tmpfs. The parent reads the
     artifact from it after the leg and removes it with seat-home;
   - the proxy is the reservation's budgeted proxy (`request_budget`), instead of the
     budgetless one;
4. records the admission of §4.4 (not yet consumed). Only the spawn hook of §4.5 step M5
   consumes it, at the real spawn; replaying it against another launch, proxy, sink or a
   second spawn refuses.
5. **Restart.** A reservation whose admission was consumed and that has no settlement is an
   unresolved settlement: charged in full (BA-1), never resumed and never reusable as a retry.
   A retry is a new reservation, refused while any reservation of the grant is live or
   unresolved. A reservation settled `unspawned` (§4.5) is neither live nor unresolved.

**Qualification of the measurement jail (r7).** `launch_provider` calls
`_require_qualified_jail`, which compares `actual_profile_digest(jail)` with the route key's
`profile_digest`. A measurement jail fails that comparison, because its owner carries the
sink bind. SL-4 adds one clause to `_require_qualified_jail`. The clause applies only when
`jail.leg == "grok"` and `_GROK_JAILED_LAUNCH` holds measurement mode for this exact jail
object (identity, not equality) and whose measurement is a `JailedMeasurementLaunch` issued by
`prepare_measurement` (`issuer is _ISSUER`). Under the clause, `_require_qualified_jail` first
rebinds `jail` to `dataclasses.replace(jail,
process_owner=grok_jail_surface.production_owner(jail, measurement=True))`, and both
`_require_canonical_jail` and the `qualification_key.profile_digest` comparison run on that
jail. A `JailRefused` from the substitution is `seat_sandbox_refused:identity`.
`_pass_refusal(key)` is unchanged. `production_owner` is SL-3's `_production_owner`, made
public. It is the
same single substitution `launch_digest` makes, and it refuses unless the owner differs from
production by exactly the one sink bind, at the tmpfs's position. The pass that is looked up
is the production key's, the pass item 1 already reads. For every other jail the function is
unchanged. `_require_qualified_jail` is listed in `SDK_PROOF_UNBOUND`, so this clause moves no
SDK proof binding. No second qualification key, qualification shape or `qualify` selector is
added (§20, r7 item 3).

**Launch path (r7).** The measurement launches through the SL-3 leg, `_exec_jailed_grok_leg`,
not through a second launch path. That leg holds the suffix scan, the refresh after-check and
the teardown order, and a second copy of them could drift. SL-4 adds two keyword parameters
to the leg:
- `measurement: JailedMeasurementLaunch | None = None`. When it is set, the leg sets
  `_GROK_JAILED_LAUNCH` to `(grok_seat, "measurement", measurement)` in place of
  `(…, "board", None)`. The leg refuses with `grok_tool_surface_unverified`, before any spawn,
  when `window_board` is not `None` (a measurement never runs in a row window) or when
  `read_sink` is `None`.
- `read_sink: Callable[[str], object] | None = None`. The leg calls it with the sink path after
  the process exits and after the after-check, inside the `try` and before the `finally`
  teardown removes seat-home. SL-4's reader scans for the leg's full secret set (the staged
  credential's scan values and the egress proxy credential) and their 12-character suffixes
  before it retains anything; a match retains nothing. Its result is kept only when the leg
  returns its success classification (no output secret match, no refresh finding, a process
  that exited); otherwise SL-4 discards it unretained.

In measurement mode, after the process exits, the leg requires that `admission-<reservation
id>` exists. If it does not, the leg treats the reservation as unresolved (charged in full),
stops the procedure, and retains nothing.

With `measurement=None`, the board path behaves exactly as SL-3 built it.
`_grok_jailed_measurement_admission`, which has no caller and whose mode the leg overrode
(SL-3 review N-3), is removed. The leg and its hunks are GROK's (§13). K-1 only delivers
`window_board`.

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
delegate, as a plan amendment under `claude-plan-phase` (not a lane, and not SL-7), after
erratum 8 merges: it adds erratum 9 to the TS contract and re-pins the TS contract in the
plan's frozen inputs and its manifest row. SL-3 and SL-4 are not dispatched until their base
contains erratum 9 and those matching pins, however many planning-only commits deliver them.

| TS contract section | Amendment |
|---|---|
| §3.1, §3.2, §3.3 | the jailed catalog, host-local names, receipt store and evidence (§3) |
| §4.1 | the record set follows the leg's context (§4.3) |
| §4.2 | `context` may be `grok_jail_context.v1`; the jailed admission rules of §4.2 |
| §4.3 | re-resolution with the jailed digests |
| §4.4 third row; erratum 8 r2 item 1d (`staged` ineligible) | jailed `staged` eligible under §2.4 only; unjailed `staged` stays ineligible |
| §5.1, §5.3, §5.4, §5.7, §5.8, §5.10 | §5 and §7.1 here |
| §10 BA-3 | BA-J1 here |
| erratum 8 r3 item 1b (delivery, normalisation and ancestor rules; the §4.4 "Home" rule as amended there) and item 1f's falsifiers | under `grok_jail_context.v1`, the staged read-only `.grok` directory, its writable entries, the CA bind and the masks of §2.3–§2.4, checked by §4.4 check 3; no memfd is used. Under `grok_seat_context.v1`, items 1b and 1f stand and E8-A's falsifiers stay unedited |

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
| Claude SDK proof inputs | `seat_route_contract.py` | none | `seat_profiles.py` | `claude_seat_transport.py` insertions; `_run_leg_with_liveness` | `_run_leg_with_liveness` (r7: the `spawn_hook` argument only, §4.5) | no | no |
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
- **SL-4's `panel_invoker.py` hunks (r7).** These are the leg's `measurement` and `read_sink`
  parameters, the removal of `_grok_jailed_measurement_admission`, the hook that
  `_grok_jailed_spawn_check` returns, the `_require_qualified_jail` measurement clause (§5.1),
  and the one `spawn_hook=` argument in `_run_leg_with_liveness`'s jailed branch. They are
  GROK hunks that follow SL-3's. `launch_provider`, `build_seat_jail`, `_JailedSeat`,
  `_require_jailed_seat_identity` and `claude_seat_transport.py` are not edited. The
  docstring of `launch_provider` says "only the grok rehearsal passes" a `spawn_hook`. That
  sentence is superseded by §4.5, and it stays unedited so that the `launch_provider` region
  does not move. The `SDK_PROOF_UNBOUND` comment on `_caps_spawn_hook` is superseded likewise
  and stays unedited. SL-4's PR refreshes the EC-CLAUDE-3 proof receipt for the
  `_run_leg_with_liveness` move, as SL-3 did.

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
| before the §7 grant ask | writers for the condition 3 confirmation and condition 4 boundary records, with provenance checks, named by erratum r8 (§14 item 4, agent-harness#2101) | coordinator's planning delegate |

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
  the real Grok jail can read the three staged files and the CA, cannot append, truncate,
  rename over, unlink or chmod any of them, cannot create any file in `.grok` outside the
  writable entries, cannot rename `.grok` or `.config` away, can write both tmpfs mounts and
  both lock files, cannot create inside a mask; a planted
  12-character suffix written to `.grok/logs` and the credential bytes are absent from
  seat-out, the review dir, the grant, the output directory, the record root and the evidence
  after teardown. SL-3 adds, through the real composed jail with a stand-in, for a short and a
  long credential shape: the suffix copied into stdout and returned text at use
  (`grok_seat_token_in_output`, nothing retained); into a failed measurement's stdout and
  stderr (no `provider.log` written); into the definitions artifact and the sessions sink
  (`artifact_refused`, `--require-measured` fails, the charge stands, both readers accept the
  record); and a crash after spawn (the review directory's staged `.grok` directory and the
  seat-home sink are gone after the existing cleanup of abandoned jailed seats, and no
  retained path holds the suffix).
- **BA-J5 (SL-3) — masks, through the real launcher.** In `live_jail` and as a hosted check,
  with the `planted` tree: every row of §2.4's table has its treatment on the actual mount
  view; creating `.grok/requirements.toml`, `.grok/managed_config.toml`,
  `.grok/staged/managed_config_refresh.json`, an MCP, skill, agent, hook or command source in
  the home, `.claude.json`, `.config/grove/x`, or a discovery path at `/seat/tree`, fails; renaming `.grok`, `.config` or
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
  **r7 additions (SL-4):** consider a refused `_require_qualified_jail`, a refused identity
  probe, a refused capped-launch preflight, and a failed `probe_sink` (a non-empty, swapped,
  symlinked, operator-owned or unwritable sink, or a helper that cannot run). After each one,
  no admission file exists, nothing is spawned and the reservation is settled `unspawned`
  with no charge. The admission file appears only when the hook runs, after the identity
  probe. A board launch passes no hook. A measurement jail whose owner differs from
  production by more than the sink bind refuses `seat_sandbox_refused:identity`. Mutations
  that the tests must kill: consuming in the verifier again, dropping the
  `_require_qualified_jail` clause's jail-identity condition, and `_run_leg_with_liveness` not
  passing the returned hook.

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
4. (r7, not ruled.) No lane yet writes the record for condition 3 (the confirmation) or for
   condition 4 (the boundary), and `--hosted-check` currently records only a string in the
   grant (SL-3 review §1). `--new-grant` needs conditions 1 to 4, so a writer and its
   provenance check must be named before the §7 grant is asked. This does not block SL-4's
   dispatch, because SL-4's tests write fixture records. Tracked in issue agent-harness#2101,
   dispositioned SCHEDULED under `docs/registers/deferred-findings.md`'s filing rule (a
   SCHEDULED issue stays open and takes no register row); a precondition of the §7 grant ask
   on the §11 critical path; owner: the coordinator's planning delegate, through erratum r8.
   The reviewer's direction for r8: SL-4 writes condition 4 through the existing
   `--hosted-check` flag (no new CLI flag, if r8 lands before SL-4.2 starts); condition 3
   needs its own owner-run, offline, no-egress procedure with the provenance checks of the
   SL-3 review §1.

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

## §18 Revision r5 (option A, 2026-11-22)

The coordinator ruled option A on Q-r4.

- **C1 closed.** §2.3: main's Gemini-style projection. The staged `<review_dir>/grok-config/`
  is bound read-only at `.grok` through `OwnerPaths.provider_config`; it holds E8-A's config
  bytes and the access-only credential. Writable entries (`logs`, `sessions` as tmpfs; two lock
  files from seat-home) are bound over named mount points, and the CA by read-only path bind.
  No `build_seat_jail`, `_owner_argv`, `seat_uid` or SDK-region edit. Readability by the dropped
  UID is by mode (0444, 0555), not Gemini's group handoff. The difference from E8-A's memfd
  projection and the code ownership of both config paths are recorded, with SL-3's
  byte-equality guard. The measurement sink is a seat-home directory the handoff already makes
  writable.
- **C3 closed.** §2.4's protection table classifies every `SEAT_FIXED_INPUTS` entry, both
  exclusions groups and every `DISCOVERY_PATHS` entry as projected, absent inside the
  read-only `.grok`, absent outside writable mounts, masked file or masked directory, with the
  reason creation is impossible; mount points are pre-created as Gemini's are; the ancestor
  rule and coverage are stated; SL-3 guards drift against E8-A.
- **C2** stays closed (§17).
- The r4 banners are removed; Q-r4 is answered.

## §19 Revision r6 (president ruling, 2026-11-22)

The presiding reviewer's ruling on the re-pin gate (agent-harness#2089) and on SL-3's flagged
items (agent-harness#2088) supplies this revision's text verbatim; no erratum 9 or TS contract
text changes, since erratum 9 takes §8 by reference.

- **Flagged item 1 (interpretation).** §8 gains a row: TS erratum 8 r3 item 1b's delivery,
  normalisation and ancestor rules, the §4.4 "Home" rule as 1b amends it, and item 1f's
  falsifiers govern `grok_seat_context.v1` only. Under `grok_jail_context.v1`, §2.3–§2.4 and
  §4.4 check 3 govern.
- **Flagged item 3 (erratum).** §4.3 row 3: `probe_grok_tools` stays SL-3's extension, but
  switches to the jailed basis only when `grok_jail_surface.staged_admission(...)` holds for the
  resolved subject; otherwise its result is identical to the unjailed probe's, so the TS contract
  suites stay unedited.

## §20 Revision r7 (SL-4 pre-dispatch erratum, 2026-11-22)

SL-4 is not dispatched until its base contains this revision and the matching pins. The
inputs are the SL-3 landing (agent-harness#2088) and its code review (items 4 and N-3). No TS
contract or erratum 9 text changes: erratum 9 takes this contract by reference. The roadmap
is unchanged.

1. **Production writers** → §3. SL-4's `--aggregate` writes the jailed host-local record.
   SL-3's `_grok_jailed_probe` writes the jailed receipt, reached through `seat-window
   probe-tools --vendor grok` and SL-4's `--verify-probe final`. SL-6 and K-1 add no writer.
2. **Admission order** → §4.4 and §4.5. The verifier no longer consumes the admission. The
   `spawn_hook` of `launch_provider` consumes it after `_require_qualified_jail` and the
   identity probe. A refusal before the hook leaves no admission file and settles
   `unspawned` with no charge.
3. **Qualification of the measurement jail** → §5.1 and §10. Option (b) is chosen: a
   sanctioned edit that adds `_run_leg_with_liveness` (the `spawn_hook` argument only) to
   SL-4's SDK proof inputs, plus a clause in `_require_qualified_jail` (listed in
   `SDK_PROOF_UNBOUND`, so it moves no SDK binding). The clause substitutes the declared sink
   difference back and checks the result against the **production** key's pass. Option (a)
   was not chosen. A second key would need either a second registered profile or a
   measurement variant in `qualification_shape`. Either moves the qualification validator
   digest a second time, which §10 allows SL-2 to do once, and it re-triggers Gemini window
   refreshes. It also needs a `qualify` selector (an SL-4 stop rule), and it changes §7's
   precondition, "qualification current for the production key".
4. **Sink probe** → §4.5 step M2: `grok_jail_surface.probe_sink`, owned by SL-4, with the pass
   and fail rules stated there. It runs as the seat UID in H on the inode the jail binds, and
   §4.5 says why it does not run inside the jail.
5. **Launch path** → §5.1 "Launch path". `_exec_jailed_grok_leg` gains the `measurement` and
   `read_sink` parameters, which are a GROK (SL-4) hunk and not a K-1 hunk. SL-4 gets no second
   launch path. `_grok_jailed_measurement_admission` is removed.

**OWNER-DECISION r7-1** (§4.5). Settling an `unspawned` reservation spends no request and
starts no process. How does that reservation's label resume under the grant's "at most 2
retries, transport failures only"?
- **(A)** The label reopens as a planned launch, and no retry is spent.
- **(A′)** (the reviewer's recommendation): the label reopens without spending a retry, at
  most once per label, and only when the refusal code is in a named transient class (for
  example a busy capped preflight or a sink-probe timeout). A deterministic refusal
  (qualification, identity probe, a swapped or owned sink, a launch digest that will recur),
  or a second `unspawned` on the same label, stops the grant as in (C).
- **(B)** It counts as one of the two retries. The reviewer notes that (B) contradicts the
  grant's own rule that retries are "transport failures only", since an `unspawned`
  reservation is not a transport failure.
- **(C)** The grant stops, and resuming needs a new grant.

The interim rule is to stop the procedure (§4.5). SL-4 implements that stop and the
`unspawned` settlement, and the owner's answer sets the resumption rule before the §7 grant
is asked. This does not block SL-4's dispatch.

**r7 review edits (independent review of agent-harness#2097, ACCEPT-WITH-EDITS).** E1 and E2
→ §5.1 (both checks of `_require_qualified_jail` run on the substituted jail; the clause and
the hook need a `prepare_measurement` issue); E3 → §5.1 "Launch path" and BA-J7 (the dropped
hook mutant and the post-spawn admission check); E4 → §4.5 M2 (check 2 proves the bind); E5
→ §4.5 (attestation and gate failures after the hook are charged); E6 and E7 → §5.1 (the
reader's result is kept only on success, and it scans the full secret set); E8 → §10 (stale
comment and the EC-CLAUDE-3 receipt refresh); E9 → §3 (the scan names the jailed record) and
the plan's SL-4 and SL-7 rows; E10 → §11 and §14 item 4 (agent-harness#2101). OWNER-DECISION
r7-1 gains option (A′); it stays the owner's decision.
