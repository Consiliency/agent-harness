# grok jailed tool-surface contract v1 (frozen artifact)

Frozen input of `plans/phase-plan-v1-seats-GROK.md` (the 2026-11-21 amendment). It holds the
detail the plan points at: the jailed launch context, its records and gate rules, the
measurement through the jail, the closed-gate registration, the owner grant, the allow-list
ruling, the pin table and the critical path to 2026-12-04. No lane edits this file. A change
is a plan amendment; a result bound to an earlier digest of this file does not count.

Inputs. Their content digests are pinned once, in the plan's frozen inputs and its manifest
row, not repeated here: the roadmap `specs/phase-plans-seats-v1.md`;
`plans/seats-jailcore-route-contract.md`; `plans/artifacts/grok-tool-surface-contract-v1.md`
(the agent-harness#2033 contract, through erratum 7; called "the TS contract" below); and,
read for coordination only, `plans/artifacts/grokroll-v1-contract.md`.

Gating inputs that are not merged yet, named by role, never by a future digest: **erratum 8**
of the TS contract (the pinned seat `config.toml`, mounted immutably; the per-image
tolerated-refusal map; the client log kept out of retained paths) as it merges after its
review; the **K-1 window kit** (`plans/amendments/seats-FIRSTSEAT-K1-window-kit.md` and its
contract) as it merges.

## §1 Why the unjailed basis cannot serve the jail

- The TS contract's frozen basis is valid only in `grok_seat_context.v1`, whose composition
  condition is the launch-owner composition (`seat_profile` plus
  `launch_owned(PROVIDER_REVIEW)`, TS contract §4.4). Its consumer audit lists the jailed
  route as **ineligible** (TS contract §4.4, third row).
- Main enforces that: the jailed spawn in `_run_leg_with_liveness` admits a grok argv only on
  a `list_tools` receipt (`panel_invoker.py`, the `seat_jail is not None` branch). No grok
  build offers `--list-tools` (TS contract §1).
- So a registered Grok `JailProfile` without this contract refuses every launch with
  `grok_tool_surface_unverified`. Reusing the unjailed record would contradict the
  composition condition and still move `context_digest` (rejected, coordinator ruling 1).

The jailed seat therefore gets its own basis, measured inside the jail.

## §2 The jailed launch context `grok_jail_context.v1`

A new context, beside `grok_seat_context.v1`, never replacing it. `grok_seat_context.v1`,
its constants and `grok_tool_surface.context_digest()` stay byte-identical (GROKROLL holds
that digest; GROKROLL contract §8).

### §2.1 Conditions, each checked by code at the final check (§4.2)

| Condition | Rule |
|---|---|
| Composition | `seat_jail.build_seat_jail` under the registered Grok `JailProfile`, route `jailed`, with the proxy-only namespace of that jail and one `start_proxy(allowlist_id="grok-review")` owned by this launch. Identifier `seat_jail.build_seat_jail+profile:grok`. |
| Jail profile | `seat_jail.jail_profile_digest("grok")` for the running architecture equals the value in the record. Any change to the Grok profile's owner binds, env, home dirs or mounts voids the record. |
| Binary | `/seat/bin/grok` is the resolved host binary whose sha256 the record names (the existing `_grok_probe_identity` re-check after launch stays). |
| Argv | the launch argv is the `staged` form of `grok_runtime_forms()` with only digest-masked slots filled (`--cwd /seat/tree`, the prompt on stdin); `_grok_argv_digest(launch) == _grok_argv_digest(staged)`. No new route form (§10). |
| Seat home | `/seat/home` is the per-launch `seat-home` that `build_seat_jail` creates fresh (0700). At spawn it holds only: the staged access-only `.grok/auth.json` and `.grok/agent_id` as read-only binds; the erratum 8 seat `config.toml` bytes (`SEAT_CONFIG_SHA256`), staged 0400 beside the credential and bound read-only (immutable, as erratum 8's revision requires); the egress CA as a read-only bind. `.grok/logs` and `.grok/sessions` are never host paths that outlive the launch (§2.3). |
| Environment | the profile's allow-listed environment plus `HTTPS_PROXY` and `SSL_CERT_FILE` (the names the TS contract's erratum 3 recorded); no `GROK_*` or `XAI_*` variable. |
| Managed config | the TS contract's two `/etc/grok` paths are absent from the jail's view and from the host; `/etc/claude-code/managed-settings.json` is absent from the jail's view (TS contract erratum 1). `$HOME/.grok/managed_config.toml` and `requirements.toml` are absent (erratum 8 item 4). |
| Discovery | **masked, not refused.** Every path of the pinned discovery set (`grok_tool_surface.DISCOVERY_PATHS`) and every `ConfigSurface.planted_paths` entry, at `/seat/tree` and at each ancestor visible in the jail, resolves to a read-only empty mask (an empty directory for a directory entry, an empty file for a file entry). The per-launch tree copy keeps every other byte. This closes TS contract follow-up F12 for the jailed route only. |
| Egress | allow-list `grok-review`, its content digest; the jail's existing proxy-only namespace (the Gemini and Codex pattern). |

### §2.2 Digest

`jail_context_digest()` is the sha256 of the canonical JSON (keys sorted, separators `,` and
`:`, ASCII, no trailing newline) of:

```json
{
  "schema": "grok_jail_context.v1",
  "composition": "seat_jail.build_seat_jail+profile:grok",
  "jail_profile": {"x86_64": "<jail_profile_digest(grok, x86_64)>",
                   "aarch64": "<jail_profile_digest(grok, aarch64)>"},
  "home": "/seat/home",
  "projected_paths": ["<sorted: .grok/agent_id, .grok/auth.json, .grok/config.toml, the CA path>"],
  "seat_config": {"path": ".grok/config.toml", "sha256": "<SEAT_CONFIG_SHA256 of erratum 8>"},
  "ephemeral_paths": [".grok/logs", ".grok/sessions"],
  "environment": {"allowed": ["<sorted>"], "forbidden_prefixes": ["GROK_", "XAI_"]},
  "managed_config": ["/etc/grok/managed_config.toml", "/etc/grok/requirements.toml"],
  "child_absent_policy": ["/etc/claude-code/managed-settings.json"],
  "home_absent": [".grok/managed_config.toml", ".grok/requirements.toml"],
  "discovery": {"policy": "masked", "paths": ["<pinned discovery set>"],
                "planted_paths": ["<profile planted_paths>"]},
  "egress": {"allowlist_id": "grok-review", "content_digest": "<grok-review content digest>"}
}
```

It moves whenever the Grok jail profile, the seat config, the discovery set, the planted
paths or the `grok-review` bytes move. No record exists under any value yet.

### §2.3 Ephemeral paths (A-5)

- `.grok/logs` (the client log carries the token's last 12 characters, erratum 8 item 5) and
  `.grok/sessions` (transcripts) are each a tmpfs inside the jail, emitted by the Grok
  profile's own owner arguments. If the profile cannot express a tmpfs without editing the
  shared `_owner_argv` builder, the lane STOPs and reports; it does not edit the shared
  builder (that would move every leg's `jail_profile_digest`).
- During a measurement only, `.grok/sessions` is instead a per-launch 0700 scratch directory
  bound in, read by §5.5 and removed in `finally` (TS contract §5.9 rules).
- No output, exec record, evidence or retained log may carry the suffix. The secret scanner
  does not catch a suffix; the guarantee is by exclusion and is tested with a planted
  suffix (§12, BA-J4).

## §3 Records

- **Shipped catalog** `phase_loop_runtime/data/grok_jail_tool_surfaces.json`, schema
  `grok_jail_tool_surface_catalog.v1`: the TS contract §3.1 shape and loader rules, with
  `context` fixed to `grok_jail_context.v1` and each surface adding `jail_profile_sha256`.
  A missing file is an empty catalog. The TS contract's `grok_tool_surfaces.json` and its
  loader are not edited.
- **Host-local record** `grok-jail-surface-<binary_sha256>.json` under
  `president_adapter.private_record_root()`, schema `grok_jail_tool_surface_measurement.v1`,
  read with the TS contract §3.2 checks and precedence (revoked, then catalog, then
  host-local). Its lock and latest-attempt register are
  `grok-jail-surface-<binary_sha256>.lock` and `.attempts.json`. The unjailed names and
  `attempts_name` (consumed by GROKROLL) are unchanged.
- **Repo evidence** `plans/evidence/seat-grok/tool-surface.json` keeps schema
  `grok_tool_surface_evidence_set.v1`; a jailed aggregate carries `"context":
  "grok_jail_context.v1"`, `jail_profile_sha256`, `"egress": {"allowlist_id": "grok-review",
  …}` and the three launches of §5.4. Catalog parity (TS contract §3.3) is asserted per
  context.

## §4 Probe, receipt and gate

### §4.1 Probe

`probe_grok_tools` keeps the TS contract §4.1 basis selection. The record set §3.2
precedence reads is the context the leg would launch in: `grok_jail_context.v1` when a Grok
profile is registered, `grok_seat_context.v1` otherwise (today's behaviour, byte-identical).
`seat-window probe-tools` rows keep their shape; `seat_window.py` is not edited.

### §4.2 Receipt and the two-step check

- `tool_probe.v1` is unchanged in shape. A jailed frozen receipt carries `basis:
  "frozen_measurement"`, `context: "grok_jail_context.v1"` and the jailed `context_digest`.
- **Provisional** (the profile's `Precondition("tool_surface")`, route L6, which calls
  main's `grok_tool_gate` on the `staged` form, and the leg's early gate): once a Grok
  profile is registered, a frozen receipt passes only if its context is
  `grok_jail_context.v1`, and then only TS contract §4.2 and §4.3, re-resolving the jailed
  record and comparing `jail_context_digest()`. It admits composition, never a launch.
- **Final**, inside the Grok jailed launch site after `build_seat_jail` and the proxy are
  ready and before spawn: `verify_jail_launch_context(jail, *, proxy, cwd, command, env)`
  checks every §2.1 condition against the composed jail argv and the proxy this launch
  owns (holder pid and socket, as TS contract §4.6 binds them) and issues a
  `JailLaunchContext` mark, constructible only by that function.
- **Spawn** (`_run_leg_with_liveness`, jailed branch): a grok argv launches only if
  `basis == "list_tools"`, or `basis == "frozen_measurement"` with `context ==
  "grok_jail_context.v1"` **and** the jail carries a `JailLaunchContext` mark that matches
  the exact final argv, cwd, jail fingerprint and proxy. Everything else refuses
  `grok_tool_surface_unverified` before any process starts.
- **Cross-context refusals.** `launch_owned` refuses a jailed-context receipt; the jailed
  spawn refuses a `grok_seat_context.v1` receipt. Each is a falsifier.
- **Invalidation** is the TS contract §4.3 rule with the jailed record set and digest.

### §4.3 Consumer audit (replaces the TS contract §4.4 third row)

| Consumer | Basis |
|---|---|
| a leg on the jailed route (`seat_jail is not None`), Grok profile registered | eligible under `grok_jail_context.v1` only, through §4.2's final check |
| every other row of the TS contract §4.4 table | unchanged |

## §5 Measurement through the jail

### §5.1 Launch path

`seat-window measure-tools --vendor grok`, unchanged on the command line: once a Grok
profile is registered the measurement context is `grok_jail_context.v1`, and the unjailed
measurement refuses before any reservation (coordinator ruling 3). It launches
through the real Grok jailed launch site with `build_seat_jail` under the registered
profile. `require_grok_admission` admits a receipt-less grok argv only while a jailed
**measurement admission** is held: a context variable set by the measurement stage alone,
tied to the one budgeted proxy that launch owns, honoured only for a jailed spawn whose
proxy is that proxy. Without it the gate is exactly §4.2. The launch is classified
`qualification` in `tests/data/seat_launch_references.json`.

### §5.2 Egress and budget

The jail's proxy-only namespace with `start_proxy(allowlist_id="grok-review",
request_budget=…)`. The TS contract §5.3 counted-request rule, per-launch budget 1, the
grant ledger, reservation before enabling, settlement on positive proof only (BA-1) and the
cap of 7 apply unchanged. `grant.json` gains `context`; a grant without it is
`grok_seat_context.v1`. Every stage refuses a context other than its grant's.

### §5.3 Fixture trees

Two fixed trees, staged through `stage_review_tree` into the per-launch copy:
- `clean`: one source file and a rules file (`AGENTS.md`), no discovery path;
- `planted`: `clean` plus a marker at every discovery path and every `planted_paths` entry
  (a `.mcp.json` naming a stdio server, a `.grok/config.toml` naming another model, a
  skill, a hook, an agent). The masks of §2.1 must hide each.

### §5.4 Launches

The jailed route launches one form, `staged`. The grant's three planned launches are three
reservations of route `staged` in context `grok_jail_context.v1`, named in `--planned` and
taken in order by successive `--route staged` stages (the tree follows the label):

| Launch | Tree | Purpose |
|---|---|---|
| `jailed-pilot` | `clean` | the measurement |
| `jailed-planted` | `planted` | the surface is unchanged when every discovery marker is present and masked |
| `jailed-confirm` | `clean` | the surface is stable across sessions |

Prompt, timeout and argv rules: TS contract §5.4. The rehearsal is of `jailed-pilot`, under
a budget-0 proxy, binding (TS contract erratum 4); its expected observation is the
per-image table of erratum 8 for the granted image.

### §5.5 Reading the artifact, aggregation, retention

- The artifact is read from the per-launch sessions scratch (§2.3) with the TS contract §5.5
  and §5.6 rules.
- **Agreement rule (new).** The jailed `staged` route is published only if all three
  launches are `measured` with identical `tools` and `definitions_sha256`. Any difference,
  or a missing launch, publishes nothing and is recorded `surface_unstable`. The TS
  contract's "latest reservation decides" holds within that rule.
- `admitted` is `_grok_tools_admitted(staged, tools)`; a measured but not admitted surface
  is published as evidence and never makes a receipt pass (TS contract §3.1).
- Redaction, retention, `--purge` and the publication lock: TS contract §5.7 and §5.9, with
  the §3 names.

## §6 Registered with the gate closed (coordinator ruling 2)

Lanes SL-0 to SL-2 register the Grok profile with no jailed record able to exist yet. Then,
on the installed runtime:

- **Route.** L1 finds the profile, so the `unconfined` exception is never consulted
  (`seat_route.py`, L1). A missing credential stops at L5 `grok_seat_credential_missing`;
  otherwise L6's `tool_surface` precondition (main's `grok_tool_gate` on the `staged` form)
  returns `grok_tool_surface_unverified`, because no receipt can pass: the shipped catalog
  is empty and no owner grant is spent on the unjailed context. The leg resolves degraded.
  No proxy starts, no auto-qualification runs (L8 is not reached), no process spawns. Even a
  planted unjailed frozen receipt would only reach the jailed spawn check, which stays
  `list_tools`-only until SL-3 and spawns nothing.
- **What Grok loses.** Nothing usable: today every Grok board leg is already degraded (empty
  catalog, no frozen record) and the exception would expire on 2026-12-04 anyway.
- **Readiness matrix.** The `vendor:grok` row reads `route: jailed`, `exception: null`,
  `expiry: null`, `allowlist_id: grok-review`, `status: candidate`, `interim_route:
  degraded` (`seat_window.readiness_rows`, which drops `unconfined` once a profile is
  registered). `remote:grok` is unchanged. A president row derived from Grok, if any,
  inherits the same fields.
- **Other vendors' window records.** `seat_window._valid_record` refuses every record once
  any row carries an expired exception. With Grok registered and installed, the Grok row
  carries no expiry, so it stops being a cause of that refusal. **It is not sufficient:**
  the Claude row's `open egress` exception shares the same expiry constant and still
  invalidates every record from 2026-12-04T00:00Z, Gemini's included, unless CLAUDENET
  gives Claude an allow-list, K-1's rule R6 (expiry judged at `observed_at` for other rows)
  lands, or the owner renews Claude's exception. That decision is outside GROK.
- **Digests.** `runtime_digest()` moves (recorded per record; K-1 R8 compares it with
  nothing). Gemini's, Codex's and Claude's `jail_profile_digest` rows are unchanged; the
  profile-digest golden gains `grok` rows on both architectures. Allow-list digests do not
  move (§9). The jail-qualification validator and watch digests move once (§10).
- **Provider-free qualification** (`seat-sandbox qualify`, EC-GROK-4's `candidate`) can run on
  the seat host after install; it needs no tool surface.

## §7 The next owner grant: jailed composition (coordinator ruling 3)

No owner-granted request is spent on `grok_seat_context.v1`. The TS contract erratum 8
item 9 grant is superseded by this one.

**Grant text (to put to the owner).**

- **Image.** One grok release image by sha256, at the TEAMHOST release path the grant
  names, which must be (a) the image installed as `grok` on the seat host, so
  `--verify-probe initial` resolves it, (b) listed in GROKROLL's release catalog once that
  has landed, and (c) a key of erratum 8's per-image tolerated-refusal map. Expected:
  grok 1.0.92, `add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb`.
- **Context.** `grok_jail_context.v1` on the designated seat host, under the installed
  release that contains lanes SL-0 to SL-3 and erratum 8's lanes.
- **One rehearsal** of `jailed-pilot`, budget 0, binding; nothing forwarded.
- **3 planned launches**: `jailed-pilot`, then `jailed-planted` and `jailed-confirm` after
  the pilot is `measured`.
- **At most 2 retries**, transport failures only, each run manually with the coordinator's
  agreement. A credential or egress failure is never retried.
- **Budget 1 per launch, so at most 5 counted requests.** The ledger's cap of 7 stays the
  ceiling and is not granted.
- **A fresh grok sign-in by the owner on the seat host**, immediately before the slot. The
  token must stay valid until the slot's hard end plus 5 minutes, re-read before the first
  counted launch. The sign-in also yields EC-GROK-5's lifetime and subscription-marker
  records (§7.2) at zero calls.
- **Preconditions:** this contract and the plan accepted by review; SL-0 to SL-3 and
  erratum 8's lanes merged, released and installed on the seat host; hosted BA-J1 (§12)
  executed with no skips on that merged head and recorded through `--hosted-check`;
  `VL` passed on the seat host; erratum 8's authorized offline, no-egress confirmation that
  the granted image runs with its seat config mounted read-only (otherwise the rehearsal
  would fail and spend the grant's one rehearsal); erratum 8 item 4's managed-policy staging
  check; a quiet
  slot agreed with the host's coordinators, both shared-compute locks, the memory-PSI gate
  and `MemorySwapMax=0` scopes, as for D4.
- **What stops it.** The rehearsal passes only on the granted image's expected observation;
  anything else stops before the pilot with no request spent. `jailed-planted` and
  `jailed-confirm` run only after `--require-measured` passes for the pilot.

### §7.1 Procedure

TS contract §5.10's script, with `--planned jailed-pilot,jailed-planted,jailed-confirm`,
`--route staged` for each launch (the pilot first), steps 4 to 8 naming those launches, and
step 0
(new, 0 calls) checking that `phase-loop seat-window matrix` on the installed runtime shows
the Grok row `route: jailed`. The lane that implements §5 ships the script as
`docs/ops/grok-jail-measurement.md` and a test that runs it against a recording runner.

### §7.2 EC-GROK-5 records from the same slot (0 extra calls)

- **Lifetime and subscription marker**: after the fresh sign-in, a metadata-only reader
  records the store's key names (never values), the presence of the subscription marker and
  `expires_at` minus the sign-in time.
- **Scope**: the pilot's settled observation (the copy accepted at the inference row) plus
  the allow-list's refusal of every other endpoint is the measured scope.
- Both land as ids in `plans/evidence/seat-grok/credential-scope.json`.

## §8 Amendments to the TS contract (coordinator ruling 1)

Applied by one pointer erratum added to `plans/artifacts/grok-tool-surface-contract-v1.md`
**after erratum 8 merges**, in a planning-only commit (text below). Each item points here.

| TS contract section | Amendment |
|---|---|
| §3.1 catalog | a second catalog file for `grok_jail_tool_surfaces.json` (§3); the first file's loader and its `context` rule unchanged |
| §3.2 host-local record | jailed names (§3); precedence unchanged |
| §3.3 evidence | the evidence set accepts jailed aggregates; parity per context |
| §4.1 basis selection | `context_name` selects the record set (§4.1) |
| §4.2 receipt | `context` may be `grok_jail_context.v1`; the gate table row for `frozen_measurement` validates against the receipt's own context |
| §4.3 invalidation | re-resolution compares the receipt context's digest |
| §4.4 consumer audit, third row ("a leg on the jailed route … ineligible (SEATS GROK SL-2)") | replaced by §4.3 here |
| §5.1 launch path | a jailed measurement path (§5.1), selected by registration, no new flag; `seat_jail.py` and `seat_profiles.py` stay unedited by the measurement code |
| §5.3 ledger | `grant.json` binds `context` |
| §5.4 launch rules | the jailed cwd is the per-launch fixture tree copy, not an empty scratch directory |
| §5.7 aggregation | the agreement rule (§5.5) for the jailed route |
| §5.8 evidence | `context`, `jail_profile_sha256`, launch labels |
| §5.10 procedure | §7.1 here for jailed grants |
| §10 BA-3 | BA-J1 here for the jailed child |
| erratum 8 item 9 | superseded by §7 here |

Pointer erratum text:

> **Erratum 9 (jailed context).** A second launch context, `grok_jail_context.v1`, is defined
> by `plans/artifacts/grok-jail-tool-surface-contract-v1.md`, which amends §3.1, §3.2,
> §3.3, §4.1–§4.4, §5.1, §5.3, §5.4, §5.7, §5.8, §5.10 and §10 as its §8 lists, and
> supersedes erratum 8 item 9. `grok_seat_context.v1`, its constants and `context_digest()`
> are unchanged.

## §9 Allow-list: adopt `grok-review` (coordinator ruling 4)

The Grok profile sets `allowlist_id="grok-review"`; no `grok-allowlist.json` is added.

- **Same client, same requests.** The jailed and unjailed seats run the same binary with the
  same seat config against the same vendor endpoints. One measured request set belongs in
  one file; two files would need two measurements and could drift.
- **Pins hold.** No `seat_egress/*` file changes, so no allow-list digest moves, GROKROLL's
  must-not-move allow-list digests and `context_digest()` hold, and no window binding's
  `production_allowlist_sha256` changes for another vendor.
- **No code assumes `allowlist_id == leg`.** The loader checks the file's `leg` against the
  id (`seat_egress_proxy`), not against the profile's leg. SL-1 proves that by test; if a
  JAILCORE invariant refuses it, SL-1 STOPs.
- **Retiring `grok-review` later** (renaming to `grok`) moves both contexts' digests and voids
  every record, so it is not done. The TS contract's reservation of the id `grok` lapses.
- **Cost accepted.** A future row the jail needs and the unjailed path does not would widen
  both. Once a Grok profile is registered the unjailed context is unreachable for board legs
  (inference: a registered profile never resolves `MODE_UNCONFINED`, EC-JAILCORE-5), so that
  widening has no live consumer.

## §10 Pins, lane by lane

"Moves" means the lane changes the value; values are lane outputs recorded in each lane's
report, never targets here.

| Pin | SL-0 | SL-1 | SL-2 | SL-3 | SL-4 | SL-6 | SL-8 |
|---|---|---|---|---|---|---|---|
| `seat_window.runtime_digest()` | moves | moves | moves | moves | moves | no (data and evidence are outside the hash) | moves |
| jail-qualification validator and watch digests (`seat_jail_qualification.py` bytes) | no | no | **moves, once** | no | no | no | no |
| `_PROXY_IMPLEMENTATION_SHA256` | no | no | no | no | no | no | no |
| Claude SDK proof files | `seat_route_contract.py` | none expected | `seat_profiles.py` (one import line); `claude_seat_transport.py` if `SDK_PROOF_UNBOUND` needs an insertion | `claude_seat_transport.py` (insertions) | none expected | no | no |
| Claude SDK proof regions (`panel_invoker.py`) | no | no | none; `_run_leg_with_liveness` is not edited | `_run_leg_with_liveness` (the spawn check) | no | no | no |
| `grok_tool_surface.context_digest()` | no | no | no | **no** (a new `jail_context_digest()`) | no | no | no |
| `jail_context_digest()` | — | — | — | new | no | no | no |
| route forms and argv digests | no | no | no | no | no | no | no |
| allow-list content digests | no | no (guard test) | no | no | no | no | no |
| `jail_profile_digest` | no | no | new `grok` rows; others unchanged | no | no | no | no |
| `tool_probe.v1` shape | no | no | no | no (new context value) | no | no | no |
| `tests/data/seat_launch_references.json` | no | rows if a detected call site | rows for the launch site | the measurement launch (`qualification`) | no | no | no |

Erratum 8's lanes move `context_digest()` (E8-A) and `_PROXY_IMPLEMENTATION_SHA256` (E8-C);
those are erratum 8's to record.

### §10.1 Batching so other vendors requalify as rarely as possible

- **Only SL-2 edits `seat_jail_qualification.py`**, and it adds a branch that delegates to
  `seat_profile_grok.qualification_shape(...)`. Later Grok changes edit that module, not the
  validator, so the validator moves once for Grok.
- **Release trains, not merges, decide requalification**: a window runs from an installed
  release. Two trains:
  - **Train A** (by 2026-12-02): SL-0, SL-1, SL-2, and erratum 8's E8-A/E8-B/E8-C if merged by
    then. One validator move, one proxy move, one runtime-digest move for Gemini and Codex.
  - **Train B** (after 2026-12-04): SL-3 and SL-4. Moves runtime digest and SDK inputs only;
    no validator, proxy or allow-list move, so no jailed-seat binding of another vendor
    changes.
  - SL-5 and SL-6 are evidence and data only. SL-6's catalog entry rides the next routine
    release; it is outside `runtime_digest()`.
- **Gemini's first window.** A train is never installed on the seat host between Gemini W1's
  first launch and its export. If W1 is open on 2026-12-02, the coordinator chooses: install
  Train A after the export if the export finishes before 2026-12-03T12:00Z, or before W1's
  first launch otherwise (W1 then binds Train A's digests). Merges to `main` are unaffected.
- **Codex** has no row-window record yet (inference from the base), so Train A costs Codex
  nothing beyond its next provider-free qualification.

## §11 Critical path to 2026-12-04T00:00Z

| By (UTC) | What | Who |
|---|---|---|
| 2026-11-23 12:00 | this amendment accepted (one review round plus the final check) | coordinator |
| 2026-11-24 | SL-0 merged | lane |
| 2026-11-26 | SL-1 merged | lane |
| 2026-11-27 | GROKROLL SL-0 (agent-harness#2050) merged, or the coordinator records the base GROKROLL's remaining lanes re-take after SL-2 | coordinator |
| 2026-11-30 12:00 | SL-2 merged (profile registered, gate closed) | lane |
| 2026-12-01 | Train A release cut (SL-0..SL-2; erratum 8 lanes if merged) | release owner |
| 2026-12-02 12:00 | Train A installed on every seat host; on each, `seat-window matrix` shows the Grok row `jailed` with no exception, and grok resolves L6 `grok_tool_surface_unverified` | coordinator / host owner |
| 2026-12-03 | buffer; provider-free qualification on the designated host (`candidate`) | host owner |
| 2026-12-04 00:00 | the exception's expiry; it is already absent | — |

**Fallback (an owner renewal record).** Trigger: SL-2 not merged by 2026-12-01T00:00Z, or Train
A not installed on every seat host by 2026-12-03T12:00Z.

1. The owner signs a renewal record (private state, mode 0600): the vendor `grok`, the new
   expiry (no later than 2026-12-18T00:00Z), the reason and the date.
2. SL-8, pre-staged and reviewed by 2026-12-01, replaces the shared expiry constant with a
   per-vendor map in `seat_window.readiness_rows` (Grok's entry renewed, every other entry
   unchanged) and fills `renewal_record` with the record's id. The route reads the same rows,
   so one edit covers both.
3. SL-8 merges, is released and installed by 2026-12-03T18:00Z.
4. If even SL-8 cannot be installed in time, Grok degrades at expiry
   (`seat_route_exception_expired`), as it would have anyway; the record-invalidation
   consequence of §6 then applies on that host until a release lands.

SL-8 renews Grok only. Renewing Claude's `open egress` is a one-value change in the same
map but needs its own owner decision.

## §12 Binding acceptance criteria of the lanes

A lane is not done, and the §7 grant is not asked, until each is met by a test.

- **BA-J1 (SL-3) — isolation in the real jailed child.** One child of the real
  `build_seat_jail` composition under the Grok profile shows both: a request through the
  proxy to a fixture upstream succeeds, and a direct connection to a host-reachable fixture
  listener fails (the listener first proven reachable from outside). Runs as a mandatory
  hosted check with `PHASE_LOOP_REQUIRE_GROK_JAIL_NS=1`, where a missing prerequisite fails.
- **BA-J2 (SL-3) — the mark binds the launch.** A `JailLaunchContext` for one jail, proxy,
  argv or cwd refuses at the spawn check for any other; the mark cannot be constructed
  outside `verify_jail_launch_context`.
- **BA-J3 (SL-3) — cross-context refusal.** A `grok_seat_context.v1` receipt refuses at the
  jailed spawn; a `grok_jail_context.v1` receipt refuses in `launch_owned`.
- **BA-J4 (SL-2, extended by SL-3) — the suffix never leaves.** A stand-in grok writes a
  planted credential's 12-character suffix to `$HOME/.grok/logs/unified.jsonl` in the jail;
  after a launch, a measurement and a rehearsal, no file under seat-out, the review dir,
  the grant, the output directory, the record root or the evidence contains it, and a
  variant binding `.grok/logs` from the host refuses.
- **BA-J5 (SL-3) — masks hold.** In `live_jail`, with the `planted` tree, every discovery and
  planted path resolves to an empty read-only mask inside the jail, and the rest of the tree
  is byte-identical to the stage.
- **BA-J6 (SL-2) — gate closed.** With the profile registered and no receipt: the route
  stops at L6 with `grok_tool_surface_unverified`, starts no proxy, does not reach L8 and
  spawns nothing. With a planted unjailed frozen receipt, nothing spawns either (the jailed
  spawn check refuses).

## §13 Coordination with work in flight

- **Erratum 8.** The jailed home uses erratum 8's seat config and immutability rule and its
  per-image map, by reference. SL-3 starts only after E8-A and E8-B merge (shared
  `grok_tool_surface.py` regions). SL-0 to SL-2 do not touch erratum 8's files and may land
  in either order. Erratum 8's revision should drop or mark superseded its item 9 grant.
- **K-1.** Confirmed: the Grok leg calls `window_board_for("grok", ...)` (K-1 contract §5.4)
  from the jailed Grok launch site, and K-1's Grok adapter registers Grok's
  `WindowVendorData`. One adjustment: the hook call is GROK SL-4, which waits for K-1's kit
  lane, so the closed-gate profile (SL-2) does not wait on K-1. K-1's two edits to the GROK
  plan are subsumed by this amendment.
- **GROKROLL.** GROK lanes edit no GROKROLL-owned file except SL-6's one `pyproject.toml`
  package-data line and the fallback SL-8's `seat_window.py` expiry literal; they move none
  of GROKROLL's must-not-move pins (§10). A GROK lane landing while a GROKROLL lane
  is in flight forces that lane to re-take its phase base for EC-GROKROLL-8's diff check.
  GROKROLL's status query reads only the unjailed catalog; teaching it the jailed catalog is
  a GROKROLL follow-up, not a GROK lane.

## §14 Open questions

1. Whether Train A may be installed while Gemini W1 is open (§10.1) depends on W1's schedule,
   which this contract does not know.
2. Claude's `open egress` expiry (§6) still invalidates every window record from 2026-12-04
   unless CLAUDENET, K-1 R6 or an owner renewal intervenes.
3. If erratum 8's revision finds that grok 1.0.92 does not accept a read-only seat config,
   SL-3 STOPs: the jailed context cannot bind a config the client rewrites, and SL-2's
   read-only bind then needs an amendment (nothing launches before SL-3, so nothing is
   exposed meanwhile).
4. If the jailed `staged` argv cannot equal main's `staged` digest, SL-2 STOPs: a new route
   form moves a GROKROLL pin and needs its own measurement.
