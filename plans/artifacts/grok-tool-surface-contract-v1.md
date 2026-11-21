# grok tool-surface contract v1 (frozen artifact)

Frozen input for `.consiliency/plans/detailed-grok-tool-surface-frozen-basis-20261120-1545.md`.
It holds the detail the plan points at: what was measured offline on grok 1.0.89, the record
schemas, the probe, gate and measurement rules, and the owner-gated procedure.

Revision r4 (2026-11-20) adds the r3 review's three implementation proofs as binding
acceptance criteria on their lanes (§10), with the matching rules in place. Revision r3
adopted the three REQUIRED changes of the r2 re-review: a durable
grant ledger (§5.3), a consumable basis wired into the board review leg (§4.4, §4.6), and a
paste-safe owner procedure (§5.10). r2 adopted the first review and the rulings on D1–D6
(§9). No lane has landed, so each revision replaces the last in place. Once a lane lands, amend by adding an errata section; never rewrite a
rule a landed lane implements.

Pinned inputs (all observed on `origin/main` @ `5c0f4a399385992f5430936d2e03f48964866868`):

| Input | Value |
|---|---|
| grok binary | `/opt/consiliency/tooling/releases/sync-e4f69bb057172a53-08478e82cbc8/native/grok` |
| binary sha256 | `a3dface51d9bdc71fd121e0481dd02d9b46a721f7a6b892f756480e9666eba1f` |
| `version.out` | `grok 1.0.89 (28be5bb1bf65)` + newline, 27 bytes, sha256 `1e1b53a8ed47243cf0f71d5199d626d7c5a1a83c666b2c9d95cbb08c8deeb059` |
| `help.out` | 5187 bytes, sha256 `67572647636f496ccfdd1899390efb1dc14bc7de8a4e77c109ef22787fb80c16` |
| `listtools.err` | 192 bytes, rc 2, sha256 `4f7e3e9993486c3ca348e6fded76e9000b34fc9d7cffde78f249e1833f990dad` |
| `forms.json` | sha256 `17e63cbb744e5645554f4a17f4ce933131f02f88375e8411a0f6c068d68c9081` |
| `summary.json` (fixture name `argv-parse-summary.json`) | sha256 `382a8d0690d07237d990774973b0ac236b4542d22e9499ab50e14b21f3f9df6b` |
| Fixture source | the engagement's review records: `grok-1089-introspection/` (`help.out`, `version.out`, `listtools.err`) and `grok-1089-argv-parse/` (`forms.json`, `summary.json`); their location is in the plan handoff. Verify each file against the digests above before committing it as a fixture |

## §1 What 1.0.89 offers, and what it does not

- No `--list-tools`, no help line `Print tool definitions without running a model`, and no
  other offline listing of the built-in tool surface (triage: `grok-1089-triage.md`
  in the engagement's review records). The same holds for 0.1.220, 1.0.13, 1.0.77 and 1.0.88.
- A session writes its tool definitions to disk. The storage-layout text bundled in the
  1.0.89 binary reads:

  ```text
  ~/.grok/sessions/<encoded-cwd>/<session-id>/
    tool_definitions.json   # function tools sent on the latest model call (no MCP server__tool entries)
  ```

  The artifact exists only after a model request, and it is overwritten by each later one.
- The JSON shape of `tool_definitions.json` is **not known**; observing it takes a live call.
- Static strings in the binary, read offline, not behaviour: the default inference base is
  `https://cli-chat-proxy.grok.com/v1`; `GROK_CLI_CHAT_PROXY_BASE_URL` overrides it;
  `HTTPS_PROXY` is referenced; no CA-trust variable name was found. Whether the client
  honours a proxy and an added CA is unconfirmed (§5.2).

## §2 Offline argv parsing of the five route forms on 1.0.89

Method: `env -i` with an empty scratch HOME, `PATH=/usr/bin:/bin`, `cwd` in that HOME, stdin
closed, `timeout 20 unshare -rn <grok> <form argv[1:]> --help`. clap parses arguments left to
right and prints help when it reaches `--help`, so every flag and value before it is parsed
and nothing runs. No network, no credentials, no session. Raw outputs:
`grok-1089-argv-parse/` in the engagement's review records.

Forms come from `panel_invoker.grok_runtime_forms()` at the pinned commit (default model
`grok-4.7`, effort `high`).

| Case | rc | Result |
|---|---|---|
| `execute` (argv digest `b4d769acb44e…`) | 0 | parses |
| `workflow` (`6bf5f222ba78…`) | 0 | parses |
| `review` (`c8267fd3dde1…`) | 0 | parses |
| `sealed` (`b7178b763fe9…`), carries hidden `--no-memory`, `--tools ""` | 0 | parses |
| `staged` (`9a3fed1c1475…`), carries hidden `--no-memory` | 0 | parses |
| `--no-memory`, `--no-subagents`, `--disable-web-search`, each alone | 0 | accepted |
| control: `--no-such-flag` | 2 | `unexpected argument` — unknown flags are refused before `--help` |
| control: `--permission-mode bogus` | 2 | `invalid value` — enumerated values are checked before `--help` |
| control: `--output-format bogus` | 2 | `invalid value` |
| control: `--list-tools` | 2 | `unexpected argument` |
| `--tools no_such_tool`, `--disallowed-tools no_such_tool` | 0 | tool names are **not** validated at parse time |
| `--reasoning-effort bogus` | 0 | effort values are **not** validated at parse time |

This establishes parsing only. Not checkable offline:

1. whether each tool id in `--tools` / `--disallowed-tools` still names a real built-in;
2. what `--tools ""` means at run time (empty surface, or "no restriction");
3. whether `--no-memory`, `--no-subagents` and `--disallowed-tools` take effect. Parse
   success is not evidence: an older build spawned a subagent despite `--no-subagents`
   (`launcher.py`, the comment in `build_grok_command`);
4. whether `grok-4.7` and effort `high` are accepted by the provider;
5. cross-argument conflicts, which clap checks only after `--help` would have exited;
6. whether `bypassPermissions` still auto-approves in a headless run.

The remaining SL-2.1 cases and the other EC-GROK-2 proofs stay open.

## §3 Frozen surface records

### §3.1 Shipped catalog — `phase_loop_runtime/data/grok_tool_surfaces.json`

Read only through `importlib.resources`. Lands **empty** in lane L1.

```json
{
  "schema": "grok_tool_surface_catalog.v1",
  "revoked": ["<binary sha256>"],
  "surfaces": [
    {
      "binary_sha256": "<64 hex>",
      "version": "<exact --version stdout, trailing newline stripped>",
      "version_sha256": "<sha256 of the exact --version stdout bytes>",
      "help_sha256": "<sha256 of the exact --help stdout bytes>",
      "model": "grok-4.7", "effort": "high",
      "context": "grok_seat_context.v1", "context_digest": "<64 hex>",
      "measured_at": "<UTC, RFC 3339>",
      "routes": [
        {"route": "review", "argv_digest": "<64 hex>", "tools": ["grep", "list_dir"],
         "definitions_sha256": "<64 hex>"}
      ]
    }
  ]
}
```

The lookup key is `(binary_sha256, argv_digest)`. `route` is a label. `tools` is the sorted,
de-duplicated list of offered function-tool names, each matching `[A-Za-z0-9_.-]{1,96}`.
Only routes with status `measured` **and** eligible under §4.4 may appear.

**Empty lists.** An observed empty `tools` list is valid evidence. It does not change
`record_tool_probe`'s existing rule `bool(offered) or not allowed_tools`: an empty surface
passes only for a form whose allow-list is itself empty (`sealed`, `--tools ""`). For a form
with a non-empty allow-list, or for the workflow form (`_grok_tools_admitted` requires a
non-empty offering there), an empty surface is recorded and the receipt fails. Neither rule
is edited.

**`revoked`** withdraws a binary digest. A revoked digest has no usable record from any
source, host-local included (§3.2).

Loader rules, all fail-closed (the loader returns "no record"):

- file over 256 KiB, not valid JSON, wrong `schema`, or any unknown key at any level;
- any digest that is not 64 lowercase hex; any `tools` entry outside the pattern, unsorted or
  duplicated; a `context` other than `grok_seat_context.v1`;
- two entries with the same `binary_sha256`, two routes of one entry with the same
  `argv_digest`, or a digest both in `surfaces` and in `revoked`.

One bad entry voids the whole file.

### §3.2 Host-local measurement record (ruling D1)

Name `grok-surface-<binary_sha256>.json` under `president_adapter.private_record_root()`.
Body: `{"schema": "grok_tool_surface_measurement.v1", "host_digest": "<64 hex>",
"surface": <one §3.1 surfaces element>}`. Read with the directory and file checks
`grok_tool_gate` applies to receipts (owner uid, directory 0700, file 0600, regular file,
`O_NOFOLLOW`, bounded read), and refused when `host_digest` is not this host's
`seat_window._host_digest()`.

Trust model, stated so nobody reads more into it: the record is as trustworthy as the
operator UID. A same-UID writer can forge it, exactly as it can forge today's passing
receipt. It adds no trust beyond the operator-written receipt; the shipped catalog is the
only reviewed source.

Precedence:

1. a digest in the catalog's `revoked` list has no record;
2. a catalog route wins;
3. the host-local route is used only when the catalog has no route for the key.

When a host-local route exists and differs from the catalog's, the catalog still wins and
the `probe-tools` row carries `"shadowed": "host_local"`. When the host-local route is the
one used, the row carries `"source": "host_local"`; a catalog route gives
`"source": "catalog"`. There is no override flag.

### §3.3 Repo evidence — `plans/evidence/seat-grok/tool-surface.json`

The path SEATS GROK SL-2.1 names. Append-only set:

```json
{"schema": "grok_tool_surface_evidence_set.v1", "measurements": [ <§5.8 aggregate> ]}
```

Catalog parity, asserted by a test: every catalog surface equals one evidence aggregate on
the **full context** — `binary_sha256`, `version_sha256`, `help_sha256`, `model`, `effort`,
`context`, `context_digest` — and each catalog route equals an aggregate route with
`status: "measured"`, `eligible: true` and the same `argv_digest`, `tools` and
`definitions_sha256`. A catalog entry with no such evidence fails the test.

## §4 Probe and gate rules

### §4.1 Basis selection (`probe_grok_tools`)

1. Measure the binary with `_grok_probe_identity` and run `--help`, as today.
2. **Basis selection is by the help gate alone.** If `--help` exits 0 with empty stderr and
   contains both `--list-tools` and `Print tool definitions without running a model`, use the
   existing `--list-tools --output-format json` path, unchanged. A build that advertises the
   flag never falls back to a frozen record.
3. Otherwise, if `--help` exited 0 with empty stderr: run `--version` (rc 0, empty stderr,
   non-empty stdout). Resolve `(probed digest, _grok_argv_digest(command))` by §3.2
   precedence. Accept the record only if its `version_sha256` and `help_sha256` equal the
   digests of the two outputs just read. Then pass
   `{"tools": <record tools>, "diagnostics": []}` to `record_tool_probe`.
4. No record, a mismatch, a loader refusal or any error: `definitions = None`, which is
   today's `passed: false` / `grok_tool_surface_unverified`.
5. The identity re-check after the runs stays.

Admission is still computed by `_grok_tools_admitted` from the form's own argv. A frozen
record states what was offered; it never states "passed".

### §4.2 Receipt (ruling D3)

`tool_probe.v1` gains additive fields, written only on a passing receipt:

- `basis`: `"list_tools"` or `"frozen_measurement"`;
- frozen basis only: `surface_digest` (sha256 of the canonical JSON of the record route
  used), `surface_source` (`"catalog"` or `"host_local"`), `context` and `context_digest`
  (copied from the record).

`grok_tool_gate` validates the combination at consumption:

| Receipt | Gate requires |
|---|---|
| no `basis` (written before this change) | today's checks only; none of the frozen fields may be present |
| `basis: "list_tools"` | today's checks; none of the frozen fields may be present |
| `basis: "frozen_measurement"` | today's checks, all four frozen fields well-formed, **and** §4.3, **and** §4.4 |
| any other `basis` | refuse |

Genuine legacy listing receipts stay valid. The file name, the digest bindings, the `tools`
admission check and the `version_digest` check do not change.

### §4.3 Invalidation: replacement, withdrawal, drift

A `frozen_measurement` receipt is a cache of a record, so the gate re-resolves the record on
every consumption (two bounded file reads) and refuses unless:

- §3.2 precedence still yields a record for `(binary_sha256, argv_digest)`;
- that record's `surface_digest` equals the receipt's, and its source equals
  `surface_source`;
- the record's `context_digest` equals the receipt's and equals the context digest the
  running code computes (§4.4).

So a revoked digest, a withdrawn or replaced host-local record, a catalog route that now
shadows the host-local one, an edited allow-list or discovery set, and a changed egress
policy each invalidate the cached receipt with no operator action. Re-running
`probe-tools` rewrites it (the existing unlink-then-write in `record_tool_probe`).

### §4.4 Scope of the basis at use

The digests identify a client and an argv form. They do not bind the home, the environment,
managed configuration, project discovery, the account, or server-side rollout. The basis is
therefore valid only inside one launch context, enforced at **measurement and at every
launch that relies on it**.

`grok_seat_context.v1`, each condition checked by code at the launch site:

| Condition | Rule |
|---|---|
| Home | a fresh private seat home built by `panel_invoker.seat_profile` (the `harness == "grok"` branch): nothing but the projected `.grok/auth.json` and `.grok/agent_id`, plus the egress proxy projection of §5.2; `HOME` and the three `XDG_*` values point into it |
| Environment | the child environment is the profile's allow-listed one plus the proxy variables of §5.2; no variable named `GROK_*` or `XAI_*` |
| Managed config | `/etc/grok/requirements.toml` and `/etc/grok/managed_config.toml` do not exist on the host at launch and are not visible to the child. `/etc/claude-code/managed-settings.json` (Claude Code managed settings, which grok also reads) is absent from the seat's effective view; its existence on the host alone does not refuse (erratum 1) |
| Project discovery | the launch cwd, each `--add-dir`, and each of their ancestors visible to the child contains none of the pinned discovery paths (below). The digest masks `--cwd` and `--add-dir`, so a real staged tree can differ from the empty measurement directory; this guard is what closes that |
| Egress | the launch runs in the proxy-only namespace under the `grok-review` allow-list (§5.2), the same policy the measurement ran under; its content digest is part of the context |
| Composition | the launch is the launch-owner composition: `seat_profile` plus `launch_owned` with role `PROVIDER_REVIEW`. The measurement uses the same one (§5.1) |

The **pinned discovery set** is a frozen tuple in `grok_tool_surface.py`: the project paths
that can add or reconfigure tools — plugins, skills, agents, hooks, MCP servers and
settings. Lane L1 derives it offline from the documentation bundled in the 1.0.89 binary,
starts from at least `.grok/`, `.mcp.json`, `.claude/` and `.cursor/`, and records the
derivation in the test that pins it. Rules files (`AGENTS.md`, `CLAUDE.md`) are **not** in
the set: they change the prompt, not the offered tools, and nearly every reviewed repository
has one, so including them would make the staged form unusable. That exclusion holds only
if the pinned build treats them as prompt text. Lane L1 checks it offline: from the
documentation bundled in the binary, and, where the offline fixture upstream of §5.2 allows,
by comparing the tool definitions of the first request with and without each file present.
If either file can load configuration or register a tool, it goes back into the set. The
guard always evaluates the actual staged paths and visible ancestors at launch. A launch whose cwd holds a
discovery path is ineligible for the frozen basis; the tree is not rewritten. Consequence:
the `staged` form is refused for a reviewed repository that carries such a directory, until
follow-up F12 masks those paths in the disposable clone. Discovery from directories nested
below the cwd is not bound; it is contained by the egress policy and the composition.

`context_digest` is the sha256 of the canonical JSON of: the schema name, the projected
paths, the environment rule, the two `/etc/grok` managed-config paths, the child-absent policy
paths (field `child_absent_policy`, erratum 2), the discovery set, the `grok-review`
allow-list content digest and the composition identifier.

**What the snapshot is evidence of.** Only the local function definitions sent on the
observed request. It does not prove later requests see the same surface, and it says nothing
about memory, subagents, plugins, MCP tools (omitted from the artifact by design),
server-side tools, or actions outside the tool channel. Those are limited by independent
enforcement, not by the snapshot: vendor-only egress (network), the fresh home (no memory
store, no plugin or MCP configuration), the discovery guard, and whatever filesystem
confinement the launch-owner composition gives. This plan claims no more filesystem
confinement than that composition has today; write confinement is EC-GROK-1's. The receipt
binds to the enforcement through `context_digest`. Account and server-side rollout are not
bound; that residual limit is accepted for the first slice and recorded in the evidence
(`account_scope: "unbound"`).

**Two-step check.** The enforced profile is not known when `_seat_command_profile` runs its
early gate, so the frozen check is split:

1. *Provisional*, at the early gates (`_seat_command_profile`, the `_exec_leg` leg loop): a
   frozen-basis receipt passes only §4.2 and §4.3. This admits composition, never a launch.
2. *Final*, after composition, where the profile, the cwd and the egress owner are known:
   `verify_launch_context(...)` checks all six conditions against the actual composed
   profile and the actual proxy owned by this launch, and marks the profile. `launch_owned`
   refuses a grok argv on a frozen-basis receipt unless the profile carries that mark. A
   digest or a non-empty egress prefix alone never satisfies it.

Listing receipts are unaffected by either step.

**Consumer audit.** Default for every consumer is **ineligible**; one test row per consumer:

| Consumer (search for the symbol) | Launch shape | Frozen basis |
|---|---|---|
| board review leg: the per-leg egress setup in `panel_invoker.py` (search `gemini_egress`), then `_exec_leg` → `_run_leg_with_liveness` → `launch_owned(PROVIDER_REVIEW)` | launch-owner composition | **eligible, wired by lane L2c (§4.6)** |
| `_run_leg_with_liveness` reached with no proxy-only prefix (its own fallback `isolated_network`) | slirp uplink, broader than the policy | **ineligible** |
| a leg on the jailed route (`seat_jail is not None`) | `build_seat_jail`; not the measured composition | **ineligible** (SEATS GROK SL-2) |
| `run_provider` → `launch_owned(PROVIDER_ADMIN)` | no proxy-only prefix | **ineligible** |
| `launch_owned`, `EXECUTOR_TRUSTED`; `launcher.py` supervisor launch | the operator's own home and repository | **ineligible** |
| `seat_admission` doctor verdict | admission check with a fixed argv | provisional step only; unchanged behaviour |

The executor forms `execute` and `workflow` cannot use the frozen basis in this plan.

### §4.5 Vocabulary

No public code is added. `panel_invoker.py` `_HARNESS_DETAIL_CODES` (around line 3112) reads:

```python
_HARNESS_DETAIL_CODES: frozenset[str] = frozenset({
    "sandbox_source_partial_clone",
    "grok_tool_surface_unverified", "leg_exec_record_unavailable",
```

Every refusal keeps `grok_tool_surface_unverified`. `seat-window probe-tools` rows gain
`"basis"` (`"list_tools"`, `"frozen_measurement"` or `"none"`), and for the frozen basis
`"source"` and, when it applies, `"shadowed"`; all additive to `{"route", "passed"}`.

### §4.6 Consumption wiring: the board review leg (lane L2c)

The goal is a usable grok seat on the review board (a downstream board run uses
`grok:grok-4.7:high:adversarial`). Which argv form that leg launches is decided in
`panel_invoker.py`, not by the caller:

- `brokered_route = mode == "review" and review_authorization is not None` (around line
  2086). A governed review is therefore **brokered**, and `_exec_leg` replaces the `review`
  form with `_brokered_grok_command`: the `sealed` form when no tree is staged, the `staged`
  form when one is;
- the `review` form (`_grok_review_form`) is launched only for a review leg that is not
  brokered.

All three go through one launch site, so that site is what L2c wires, and all three forms
become eligible there. Wiring only the `review` form would leave the governed board refused.

Wiring, in the board leg's egress setup and `_run_leg_with_liveness`:

1. For a grok leg whose provisional check passed on a frozen-basis receipt, start
   `start_proxy(allowlist_id="grok-review")` (no request budget) and hold the proxy-only
   namespace of §5.2 as the leg's egress prefix, in place of the slirp namespace. A leg on a
   listing receipt keeps today's egress, byte for byte.
2. Compose the profile with the proxy projection, then run the final check of §4.4 against
   that profile and that proxy.
3. Any failure — egress layer unavailable, allow-list missing, a discovery path in the cwd,
   managed config present — is `grok_tool_surface_unverified`. There is no fallback to the
   broader namespace.

End-to-end test with a stand-in, no vendor contact (`tests/test_grok_board_leg_frozen_basis.py`):
a stand-in `grok` executable that answers `--help` and `--version` with the 1.0.89 fixtures
and, when launched, makes one request through its environment's proxy to a loopback fixture
upstream behind the real `proxy.mjs`; a fixture frozen record for its digest. Enter through
`_exec_leg` for a brokered leg without a tree (`sealed`), a brokered leg with a staged tree
(`staged`) and an unbrokered leg (`review`). Assert: the leg completes; the request was
observed by the `grok-review` proxy; the child's home held only the projection; and each of
these refuses with no launch: no egress layer, a staged tree containing `.mcp.json`, a
managed-config file, a withdrawn record, and the same leg forced onto the fallback namespace.

That is not yet proof that the accepted child has no second path. BA-3 (§10) requires the
dual proof from one child of the real launch-owner composition, and binds the final check to
the exact namespace holder and proxy the launch owns: the holder pid behind the leg's egress
prefix and the proxy socket that holder bridges to, not any non-empty prefix.
The test uses the namespace and bwrap prerequisites the existing seat-launch tests use and
skips where they are absent; hosted CI is where it must run.

## §5 Measurement (`seat-window measure-tools`)

### §5.1 Launch path

Every existing grok launch calls `grok_tool_gate` first, and no receipt can exist before the
first measurement. The measurement still goes through the seat's own composition, so that it
is the context of §4.4 and not an imitation of it:

- the profile is built by `seat_profile(harness="grok", …)`: the same credential projection
  (`credential(".grok/auth.json", shape=…)` and the `agent_id` data file). The login store is
  never copied;
- the launch goes through `launch_owned` with role `PROVIDER_REVIEW`, the role the board leg
  uses. `PROVIDER_ADMIN` cannot be used: `launch_owned` clears the egress prefix for it, so
  the child would not run in the proxy-only namespace. `require_grok_admission`
  admits a receipt-less grok argv only while a **measurement admission** is held: a
  context variable set by `measure_route` alone, never from argv or environment, and tied to
  the one budgeted proxy that launch owns (§5.3): it is honoured only for a launch whose
  egress prefix is that proxy's namespace. Without it the gate behaves exactly as today;
- the private home stays a tmpfs. The only host-backed path in it is the scratch sessions
  directory bound at `.grok/sessions`. If `seat_profile` cannot express that today, add one
  keyword for it and prove ordinary launches compose byte-identically;
- `seat_jail.py` and `seat_profiles.py` are not edited.

The measurement launch is classified `qualification` in
`tests/data/seat_launch_references.json`.

### §5.2 Egress (ruling D2: host networking declined)

No credentialed launch without isolated, fail-closed, vendor-only egress.

- **Pattern.** The proxy-only namespace the jailed Gemini seat uses:
  `seat_egress_proxy.start_proxy(allowlist_id=…)`, then
  `sandbox_egress.isolated_network(required=True, seat_uid_map=True,
  proxy_socket=proxy.socket, proxy_port=SEAT_PROXY_PORT)`. No slirp uplink. A client that
  ignores the proxy reaches nothing. The ordinary broker/slirp path is not used.
- **Policy.** The pinned tree ships `codex` and `gemini` allow-lists only; neither can carry
  grok inference. Lane L2a adds `seat_egress/grok-review-allowlist.json`
  (`phase_loop_seat_egress_allowlist.v1`, `leg` and id `grok-review`): exact method and path
  rows on `cli-chat-proxy.grok.com:443`, plus whatever the offline derivation shows a
  review turn needs, each as an exact row. Sign-in and token-refresh hosts go in
  `measured_and_refused`; an expired credential fails closed.
- **One policy, two users.** The measurement and the board review leg (§4.6) run under this
  same file; its content digest is in `context_digest`, so they cannot drift apart. It is
  named for what it governs, the launch-owner review launch. The id `grok` stays reserved
  for SEATS GROK SL-1: that plan binds `allowlist_ref("grok")` to the jailed seat profile,
  its own measurement and its own digest tests, and taking the id here would pre-empt that
  contract. When SL-1 lands it may adopt these rows and retire `grok-review`.
- **Proxy projection.** The composed profile carries the proxy address and the seat egress
  CA certificate (a read-only data file in the private home) through the variables the
  offline confirmation identifies. The same projection is used at measurement and at use.
- **Namespace for a launch-owner leg.** `isolated_network(proxy_socket=…)` is used today
  only with `seat_uid_map=True`, for the jailed Gemini seat. L2a confirms it serves the
  launch-owner composition, or extends it, with existing callers byte-identical. It is not
  worked around with the slirp namespace.
- **Offline derivation and confirmation**, no credential and no vendor contact, as the codex
  allow-list was derived: run 1.0.89 against a loopback fixture upstream through the real
  `proxy.mjs`, with a fabricated credential, to name every request path of one headless turn
  and to confirm the client honours the proxy and trusts the seat egress CA. Record which
  variables carry the proxy and the CA.
- **If that cannot be confirmed offline**, the allow-list lands with the statically known
  inference row only, the measurement stays blocked from catalog use, and the pilot is the
  first confirmation. It fails closed: a denied or unproxied request yields a non-zero exit,
  status `egress_refused`, and the proxy's metadata-only observation of the refused request.
- **Evidence** records the egress policy actually applied: allow-list id and content digest,
  and the per-request observation counts.
- **Refusal tests** (offline, with the fixture upstream): the egress layer unavailable
  refuses before any launch; a missing allow-list refuses; a request to an unlisted host, to
  a host listed only for `gemini` or `codex`, to a listed host on an unlisted path, and a
  direct connection that bypasses the proxy are each refused; a client that does not trust
  the CA completes no request; the measurement admission without its own proxy refuses.

Broader networking stays unfinished.

### §5.3 The request budget and the grant ledger

A launch count does not bound model calls: the client can retry, take tool turns, title the
session or spawn subagents, and each later request overwrites the artifact.

- **Counted request**: any request the proxy allows whose method is `POST` and whose host is
  the inference host, on any path. This over-counts on purpose; it can never under-count.
- **Stop mechanism**: `start_proxy` gains `request_budget=N`, passed through the proxy's
  configuration file like `refuse_all`, and able only to narrow. `proxy.mjs` decrements the
  budget **before** forwarding, atomically across concurrent requests, and denies every
  request once it is spent, observing the denial. One proxy per launch, owned by that
  launch; the measurement admission (§5.1) is tied to that exact proxy.
- **Per-launch budget**: 1, a constant in this plan. There is no flag for it. A larger
  per-launch budget needs a revised grant and an erratum here, because with two requests the
  artifact could reflect the later one.

**Grant ledger.** The cap must survive a kill, a timeout and a fresh output directory.

- A grant is a directory `grok-measure-grants/<grant id>/` under
  `president_adapter.private_record_root()`. `--grant <id>` is required on every
  `measure-tools` stage. `grant.json` is created once (`O_CREAT|O_EXCL`, fsynced) and binds
  the grant id, `host_digest`, the pinned binary sha256, the planned routes, the retry
  allowance and the cap. Every later stage and retry must match it or refuses. The output
  directory holds no accounting, so a new one resets nothing. Creating a grant needs
  `--new-grant`; the evidence lists every grant that exists for the same host and binary.
- **Reserve before enabling.** Under an exclusive, non-blocking `flock` on the grant's lock
  file, and before the launch's proxy is started, the tool writes an immutable reservation
  `reservations/<n>-<random>.json` (`O_EXCL`, file and directory fsynced) for that launch's
  **whole** budget. It refuses unless `charged + budget <= cap` and the launch is within
  `planned routes + retry allowance`. A second process on the same grant refuses at once
  (`measurement_busy`), whatever its output directory.
- **Reconcile after shutdown, on positive proof only.** End-of-stream after the proxy exits
  is not proof: a crash can drop buffered output at a record boundary and leave a stream
  that parses. A settlement **below the full budget** is written only when all three hold:
  the proxy shut down cleanly on request (exit status 0, not signalled); it wrote an explicit
  end-of-stream marker as its last record, carrying its own count of observed requests, and
  that count equals the records read; and no record failed to parse. `proxy.mjs` gains that
  marker in lane L2a, written and flushed only on the orderly shutdown path. Anything else
  — a kill, a timeout, `start_proxy`'s own shutdown-timeout kill path, a missing or
  mismatched marker, a truncated record — is an incomplete observation: the reservation
  stays charged in full, permanently (BA-1, §10).
- **Charged** is the sum over reservations of the settled count, or the full budget where no
  settlement exists. The cap is **7**, a constant.
- **Routes are reserved one at a time**, each immediately before its own launch. An
  interruption between two routes of one invocation leaves the first settled and the second
  unreserved; an interruption during the second leaves it charged in full.

Tests (recording runner, no vendor contact): a kill after reservation and before settlement;
a kill between the two routes of one invocation; a restart with a fresh output directory; a
truncated observation stream; a mismatched binary or host against `grant.json`; two
concurrent processes; the launch beyond the retry allowance; the launch that would pass 7.

### §5.4 Launch rules

For each selected route, exactly one launch, never retried by the tool:

1. `form = grok_runtime_forms(model, effort)[route]`, first run `grok-4.7` / `high` only
   (ruling D6). Measure the binary with `_grok_probe_identity` (or `--binary PATH`).
2. Verify every `grok_seat_context.v1` condition (§4.4). The cwd is an empty scratch
   directory, so the discovery guard holds trivially; it is still evaluated.
3. Launch argv is the form with only its digest-masked slots filled: the `-p` value becomes
   the fixed prompt, and `--prompt-file /dev/stdin` forms get it on stdin. Refuse before
   launching unless `_grok_argv_digest(launch_argv) == _grok_argv_digest(form)`. No flag is
   added: `--max-turns` or `--session-id` would change the digest.
4. Prompt, fixed: `Reply with the single word OK. Do not call any tool.` It reduces the
   chance of a second request; it is not the control. §5.3 is.
5. `timeout` 180 s per launch.

### §5.5 Reading the artifact

A route is `measured` only if **all** hold:

- the launch exited 0, the binary identity is unchanged after it, and the settled
  observation shows exactly one allowed counted request and no denial other than the
  tolerated refusals of erratum 3. A TLS
  failure, a refused request, or an attempt to bypass the proxy leaves **no qualifying
  capture, even when the client exits 0**: an unproxied attempt reaches nothing and may
  leave no observation at all, which is "zero allowed counted requests" and so not
  `measured`, whatever is on disk;
- under the scratch sessions directory, opened as a directory descriptor, exactly one
  `<group>/<session>/tool_definitions.json` exists. Each path component is opened relative
  to its parent with `O_NOFOLLOW`; the file is a regular file owned by the launch's mapped
  uid, at most 4 MiB, read through that descriptor with a bounded read. Zero or several
  candidates, a symlink, or any other file type refuse (`artifact_missing`,
  `artifact_ambiguous`);
- names extract under §5.6.

### §5.6 Extracting names; an unrecognised shape

The extractor accepts only:

- **S1** a JSON array of objects, each with a string `name`;
- **S2** a JSON array of objects, each with `function.name` a string;
- **S3** a JSON object whose `tools` value is S1 or S2.

Mixed arrays, a missing name, a shape matching more than one reading, or anything else give
`format_unrecognised`. Ambiguous shapes stay refused; the extractor never guesses.

On `format_unrecognised` at the pilot:

1. stop. The tool refuses every further reservation on the **grant**, retries included,
   while an unresolved `format_unrecognised` result is the latest for any of its routes;
2. the private raw bytes are retained (§5.9); the result record carries only the sanitized
   structure: JSON types and key names to depth 3, no string values, key names filtered as
   §5.9 states;
3. a narrow extractor for the observed shape is built and tested **offline** from that
   structure, as a normal reviewed change;
4. `measure-tools --reprocess <reservation id>` re-reads the retained capture with the new
   extractor and writes a further result record for the same reservation, with
   `reprocessed_from` and the extractor revision. It reserves nothing and charges nothing;
   the reservation's original charge stands;
5. only if the capture is unusable is a revised grant sought. No call is spent to rediscover
   a shape already captured.

### §5.7 Result records, aggregation, retry, concurrency

- **Immutable result records.** One per launch, written right after its settlement to
  `<output>/results/<reservation id>.json` with `O_CREAT|O_EXCL`, 0600, never rewritten. It
  names its grant and reservation and holds the full context, the route, its status and
  result. The pilot is one such record and stays. A reservation with no result record is a
  failed attempt of its route, status `interrupted`.
- **Retry.** A retry is a new reservation for the same route, inside the grant's retry
  allowance and the cap (§5.3). The `format_unrecognised` stop of §5.6 applies to the whole
  grant, retries included.
- **Withdraw before launching.** Under the per-binary publication lock (below), and before
  the proxy for route R is started, the tool removes route R from the host-local record
  (§3.2), or removes the record when R was its last route. So from the moment a newer
  attempt can exist until the next successful aggregation, a prior pass for R is not
  consumable; cached receipts for it stop admitting (§4.3).
- **Aggregation.** `measure-tools --aggregate --grant <id>` (no launch) reads the grant's
  reservations and settlements and the result records, and refuses unless every result
  matches a reservation of this grant and all share `binary_sha256`, `version_sha256`,
  `help_sha256`, `model`, `effort`, `context_digest`, `host_digest` and the allow-list
  digest. Per route the **latest reservation** decides: a later failed or interrupted attempt
  supersedes an earlier `measured`. It writes `<output>/tool-surface.json` (§5.8) by temp
  file and rename. Call accounting comes from the ledger, per reservation; a reprocessed
  result (§5.6) replaces the outcome of its reservation and is never charged again.
- **Publication.** The host-local record is written only by `--aggregate`, by
  unlink-then-write (`write_private_record` creates exclusively), and contains only routes
  that are `measured` and `eligible`. If aggregation fails or leaves no such route, any
  record for that binary is removed. A launch never publishes.
- **Cross-directory coordination.** Writers of one binary's host-local record — withdrawal,
  publication, removal — take an exclusive `flock` on
  `grok-surface-<binary_sha256>.lock` in the private record root, whichever grant or output
  directory they run from.
- **Latest attempt across grants.** Aggregation reads one grant, so the lock alone would let
  an older grant republish a route a newer grant withdrew. Under that same lock the tool
  keeps `grok-surface-<binary_sha256>.attempts.json` in the private record root: per route,
  the grant id, reservation id and reservation time of the **latest attempt by any grant**.
  It is updated in the withdraw-before-launch step, before the proxy starts. `--aggregate`
  publishes route R only if the register names this grant's own latest reservation for R;
  otherwise R is left out of the record and reported as `superseded`. A missing or
  unreadable register publishes nothing. This invariant covers host-local publication
  only: a shipped catalog route keeps its D1 precedence (§3.2) whatever the register says
  (BA-2, §10).

### §5.8 Aggregate evidence

```json
{
  "schema": "grok_tool_surface_evidence.v1",
  "binary_sha256": "…", "version": "…", "version_sha256": "…", "help_sha256": "…",
  "host_class": "team", "host_digest": "…", "runtime_digest": "…",
  "context": "grok_seat_context.v1", "context_digest": "…", "account_scope": "unbound",
  "method": "session_artifact", "model": "grok-4.7", "effort": "high",
  "egress": {"allowlist_id": "grok-review", "allowlist_sha256": "…"},
  "prompt_sha256": "…",
  "grant": {"id": "…", "planned": 3, "retries": 2, "cap": 7, "charged": 3,
            "other_grants_for_binary": 0},
  "reservations": [
    {"id": "…", "at": "…", "route": "review", "budget": 1, "settled": 1,
     "reprocessed": false}
  ],
  "routes": [
    {"route": "review", "argv_digest": "…", "status": "measured", "eligible": true,
     "shape": "S2", "tools": ["…"], "definitions_sha256": "…", "definitions_bytes": 0,
     "reservation": "…", "exit_code": 0, "admitted": true}
  ]
}
```

`status` is one of `measured`, `format_unrecognised`, `artifact_missing`,
`artifact_ambiguous`, `launch_failed`, `egress_refused`, `budget_exhausted`,
`identity_changed`, `context_refused`, `interrupted`. `eligible` follows §4.4: `true` for the
three seat forms once lane L2c has landed. `admitted` is `_grok_tools_admitted(form, tools)` with the nonempty rule of §3.1.

### §5.9 Redaction and retention

- **Evidence and result records** hold names, digests, counts and statuses only. Never:
  prompt text, stdout or stderr, session ids, account or agent ids, any path under a home,
  tool descriptions or parameter schemas, or credential bytes. An allow-list of keys is
  enforced by the writer and by a test.
- **Untrusted strings.** JSON key names and purported tool names from the artifact are
  provider-controlled. A tool name is exported only if it matches the §3.1 pattern;
  anything else makes the route `format_unrecognised`. The sanitized structure of §5.6
  exports a key name only if it matches `[A-Za-z0-9_]{1,64}`, and otherwise a placeholder
  with the key's length; at most 64 keys per object.
- **Raw `tool_definitions.json`**: copied 0600 to `<output>/raw/<reservation id>/`, kept on
  the host only, for §5.6 reprocessing.
- **Provider stdout and stderr** are treated as secret-bearing: no claim is made that they
  contain no secret. They go to a 0600 file beside the raw artifact through a descriptor
  opened `O_CREAT|O_EXCL|O_NOFOLLOW`, are never parsed into any record, and are deleted at
  once on a `measured` route.
- **Operative deadlines.** Each retained file gets a sibling `expires_at` written with it:
  7 days for logs, 30 days for raw artifacts. Every `measure-tools` stage first deletes what
  has expired under its output directory and reports the count, and refuses to launch if
  that deletion fails. `measure-tools --purge` deletes everything retained at once; the
  procedure's last step runs it after lane L3 merges. An expired raw artifact cannot be
  reprocessed.
- **The scratch sessions directory** is removed in `finally` after the artifact is copied.
  Nothing else of the session (transcript, prompts, system prompt) is copied out.
- `--output` must be under the operator's private state home (erratum 3) and is refused inside a git work
  tree. Only `tool-surface.json` ever leaves the host.
- The planted-sentinel test covers the credential projection reaching no record. It does not
  prove provider logs are clean, which is why those are retained as secrets.

### §5.10 Owner-gated procedure on the measurement host (decision D4)

Preconditions: lanes L1, L2a, L2b and L2c are merged; the plan re-review has accepted; the
owner has granted the run **for one named grok release image**; a scratch worktree of merged
`main` on the measurement host with the tree's locked uv environment; the operator account is signed in to
grok; the seat egress layer is installed; `/proc/pressure/memory` and `free -h` show headroom;
the hosted egress check of BA-3 has run without skips on the merged head (erratum 4).

**The grant.**

- One **rehearsal** of the `review` pilot before it (erratum 4): a credentialed launch under
  a budget-0 proxy. Every request is refused and observed, nothing is forwarded, no model
  call is made. It counts against no request budget and is not a planned launch.
- Planned launches: **3** — the `review` pilot, then `sealed` and `staged` after inspection.
- Retry allowance: **2** launches in total, for any route, for a transport failure.
- Per-launch budget: **1** counted request, fixed.
- So at most **5** counted requests can be spent under this grant. The hard cap of **7**
  stays as the ceiling the ledger enforces; the two beyond 5 are not granted.
- The executor forms `execute` and `workflow` are not measured (ruling C1).

The script is safe to paste into `bash` as a whole. It stops at the first unexpected result.
`probe-tools` exits 1 whenever any route is not passing, which is the expected state both
before the measurement and after it (the executor forms stay refused), so the script never
calls it bare: `--verify-probe` runs the same probe, compares each route with what is
expected, and exits 0 only on a match.

```bash
set -euo pipefail

# The approved image. Replace both values only if the owner's grant names another release.
GROK_BIN=/opt/consiliency/tooling/releases/sync-e4f69bb057172a53-08478e82cbc8/native/grok
GROK_SHA=a3dface51d9bdc71fd121e0481dd02d9b46a721f7a6b892f756480e9666eba1f
GRANT=D4-grok-1.0.89
OUT="$HOME/.local/state/phase-loop/grok-surface/$GRANT"
MT=(uv run --frozen phase-loop seat-window measure-tools --vendor grok --host-class team
    --grant "$GRANT"
    --binary "$GROK_BIN" --expect-binary-sha256 "$GROK_SHA" --output "$OUT")

# The scratch worktree of merged main. Export it before pasting; the script stops if unset.
: "${GROK_MEASURE_WORKTREE:?export GROK_MEASURE_WORKTREE=/path/to/scratch/worktree first}"
# The hosted CI run of the egress check on the merged head (BA-3). Recorded in the grant.
: "${GROK_HOSTED_CHECK_RUN:?export GROK_HOSTED_CHECK_RUN=<hosted run id or URL> first}"
cd "$GROK_MEASURE_WORKTREE/phase-loop-runtime"

# 1. Verify the image before anything credentialed. 0 calls.
echo "$GROK_SHA  $GROK_BIN" | sha256sum --check --strict
timeout 120 uv run --frozen phase-loop seat-egress status

# 2. Baseline. 0 calls. Passes only if every route is refused with basis "none", and the
#    on-host isolation check passes (the child reaches only its proxy).
timeout 300 "${MT[@]}" --verify-probe initial

# 3. Open the grant: 3 planned launches, 2 retries, cap 7. 0 calls.
timeout 60 "${MT[@]}" --new-grant --planned review,sealed,staged --retries 2 \
  --hosted-check "$GROK_HOSTED_CHECK_RUN"

# 4. Rehearsal of the pilot under a budget-0 proxy. 0 calls: nothing is forwarded.
timeout 300 "${MT[@]}" --attended --rehearse --route review

# 5. Gate on THIS grant's rehearsal record. Exits non-zero unless it shows only tolerated
#    refusals and the budget's own refusal of the inference request.
timeout 60 "${MT[@]}" --require-rehearsed review

# 6. Pilot. At most 1 counted request.
timeout 300 "${MT[@]}" --attended --route review

# 7. Gate on THIS grant's pilot record. Exits non-zero unless review is "measured".
timeout 60 "${MT[@]}" --require-measured review

# 8. The two remaining seat forms. At most 1 counted request each.
timeout 600 "${MT[@]}" --attended --route sealed --route staged

# 9. Aggregate and publish the host-local record. 0 calls.
timeout 300 "${MT[@]}" --aggregate

# 10. Final check. 0 calls. Passes only if each seat route's result equals the aggregate
#     (frozen_measurement where measured and admitted) and both executor routes are refused.
timeout 300 "${MT[@]}" --verify-probe final

timeout 60 "${MT[@]}" --status
```

Notes on the script:

- `--verify-probe initial` also fails unless the binary the probe itself resolves for
  `grok` has the approved digest. If it does not, stop: the seat would launch a different
  binary than the one measured.
- Every `measure-tools` stage re-measures `--binary` against `--expect-binary-sha256` and
  against `grant.json` before it projects a credential, and refuses on a mismatch.
- Steps 6 and 8 exit 0 when every named route got a reservation and a result record,
  whatever its status: an unsuccessful route is a recorded result, not a script error. They
  exit non-zero, stopping the script, when a named route **never reserved** (a refusal
  before the ledger: image mismatch, context, egress layer, grant limits, a busy grant) or
  reserved but left no result record (`interrupted`). `--status` lists the two cases
  separately, and `--require-measured` reports "no reservation" apart from "not measured".
  Steps 7, 9 and 10 are what decide the outcome. If step 7 stops the script, read
  `"${MT[@]}" --status` and §5.6 (`format_unrecognised`) or §5.2 (`egress_refused`). The
  fix is offline; nothing further is launched.
- A transport retry is step 6 or step 8 run again for the failed route alone. The ledger
  refuses the third retry.
- Step 4 reserves nothing and is charged nothing. If step 5 stops the script, the pilot has
  not run and no request was spent: the rehearsal record names the unexpected request, and
  the fix is an erratum to the tolerated list or to the allow-list, made offline.
- After step 10, copy `$OUT/tool-surface.json` only off the host for lane L3. After L3
  merges, run `"${MT[@]}" --purge`.

Outcomes that are **not** failures of this plan:

- a route is `measured` but `admitted: false` (for example `sealed` offering built-ins despite
  `--tools ""`). It stays refused, correctly, and step 8 expects exactly that;
- the pilot reports `format_unrecognised`, `egress_refused` or `budget_exhausted`. At most one
  request was spent.

## §6 New grok builds

A new binary digest has no record, so the probe fails closed for it. What limits the wait:

1. the seat host follows TEAMHOST tooling releases under `/opt/consiliency/tooling/releases/`,
   not upstream's daily cadence;
2. records accumulate per digest, so a host held on, or rolled back to, a measured digest
   keeps working;
3. `measure-tools --binary <release path>` measures a synced release before it is `current`;
4. the host-local record unblocks the measuring host with no package release.

Each new digest still needs an owner grant. A standing grant is deferred (ruling D5) and is a
follow-up with this scoping: approved release artifacts only, one eligible host and account,
the default form set, a persistent deduplicated ledger, an expiry, aggregate caps across
releases and invocations, and a stop on policy or artifact drift. A watch job and the
TEAMHOST release-updater hook (agent-harness#1820) are follow-ups too.

## §7 Alternatives evaluated

| Alternative | Verdict |
|---|---|
| Derive the surface from argv (`--tools` minus `--disallowed-tools`) | Rejected as a basis. 1.0.52 offered built-ins `--tools` did not list (`panel_invoker.py` near line 6570). |
| Pin a grok version | Not a basis: no installed build has `--list-tools`. Used as §6 rule 1. |
| Ask xAI for a definitions-only flag | Right long-term fix (follow-up). The `--list-tools` path stays so such a build needs no code change. |
| `grok inspect --json` | Reports discovered configuration, takes no tool controls. Useful later as a discovery check, not as a surface. |
| `grok agent stdio` | Needs a running authenticated agent and an unmeasured protocol. |
| A separate bwrap jail with host networking (r1) | Declined (ruling D2): it exposes host loopback, LAN and arbitrary destinations, and imitates the seat context instead of using it. |

## §8 Integrity

`seat_window.runtime_digest()` hashes every runtime `*.py`, `advisor_board/*.py` and
`seat_egress/*`.

| Pin | L1 | L2a | L2b | L2c | L3 |
|---|---|---|---|---|---|
| `runtime_digest()` and with it window `qualification_keys` | moves | moves (`proxy.mjs`, `seat_egress_proxy.py`, the new allow-list file, `sandbox_egress.py` if extended) | moves | moves (`panel_invoker.py`) | does not move (`data/*.json` and `plans/evidence/` are outside the hash) |
| `tests/data/seat_launch_references.json` | new `host-io` rows: the loaders, and the record reads added to `grok_tool_gate` | rows only if a call site is added | the measurement launch wrapper under `qualification`; the ledger's `host-io` rows | rows only if the leg's proxy start adds a detected call site | — |
| `tool_probe.v1` receipt | additive fields | — | — | — | — |
| Egress allow-list content digests | — | new `grok-review` digest; `codex` and `gemini` digests must not move | — | — | — |
| `pyproject.toml` package data | one entry | one entry if the allow-list needs listing | — | — | — |
| Claude SDK proof region `_run_leg_with_liveness` (`panel_invoker.py`, one of the `SDK_PROOF_REGIONS`) | its proof binding moves | — | — | its proof binding moves | — |
| Claude SDK proof region `launch_provider` (`panel_invoker.py`) (erratum 6) | — | — | moves | unchanged from L2b | — |
| Claude SDK proof file `claude_seat_transport.py`, whole file (erratum 6) | moves | — | moves | moves | — |
| Claude SDK proof file `seat_resource_caps.py`, whole file (erratum 6) | — | — | moves | unchanged from L2b | — |
| `runtime_digest()` values at each accepted lane head | erratum 6 | erratum 6 | erratum 6 | erratum 6 | — |

Transition, named for rollout: after each of L1, L2a, L2b and L2c lands, window records on
the previous `runtime_digest` key no longer match, existing W1 records included. Requalify
affected windows before relying on them. Landing the four close together, then requalifying
once, is the cheap order. L3 needs no requalification.

The inventory counts what its scanner detects per call site, not runtime invocations: a
second `runner(...)` call inside `probe_grok_tools` changes that row's count only if the
scanner sees a new `run_provider` reference. Run the inventory test and record what it reports.

`context_digest` (§4.4) is a pin of its own: it covers the managed-config paths and the
child-absent policy paths, so errata 1 and 2 change its value. Lane L2b filling the proxy
projection constants changes it once more (erratum 3, lane note). No record carried the earlier value.

Must not move, each with a named guard:

- the agy seat QCI, `QUALIFICATION_VALIDATOR`, the shipped agy catalog and its records
  (`tests/test_agy_qci.py`);
- the grok and gemini seat profiles and jail profile digests (`seat_profiles.py`,
  `seat_jail.py` not edited), `CONTAINMENT_CONTRACT_SHA256`, `SRT_TREE_SHA256`;
- existing proxy behaviour with no `request_budget`, and the egress of every non-grok leg and
  of a grok leg on a listing receipt (the existing gemini and codex egress tests, unedited);
- the five route forms and their argv digests (fixture guard against `forms.json`);
- the public detail-code vocabulary.

After the egress choice, lane L2a must prove the table by test, not by reading: the two
existing allow-list digests equal their pinned values, and a proxy started without a budget
makes the same decisions as before.

Receipt consumers to exercise: a legacy receipt, a `list_tools` receipt and a
`frozen_measurement` receipt through each consumer in §4.4, with the refusal cases of §4.2
and §4.3.

## §9 Rulings recorded

| Decision | Ruling | Where |
|---|---|---|
| D1 | Host-local evidence only within the operator-UID trust model; the shipped catalog wins on conflict; the source is visible in diagnostics | §3.2 |
| D2 | Host networking declined; vendor-only egress | §5.2 |
| D3 | Additive `tool_probe.v1` fields; combination validated at consumption; invalidation on replacement or withdrawal | §4.2, §4.3 |
| D4 | Owner-gated, for one named release image: 3 planned launches (the `review` pilot, then `sealed` and `staged`), a retry allowance of 2, budget 1 per launch, so at most 5 counted requests; the hard cap of 7 stays as the ledger's ceiling | §5.3, §5.10 |
| r2 re-review 1 | A durable grant ledger: reserve before enabling the proxy, reconcile after shutdown, orphans stay charged, bound to grant, host and binary | §5.3 |
| r2 re-review 2 | The basis must be consumable: the board review leg is wired end to end under the measured policy and composition, with the frozen check after composition | §4.4, §4.6 |
| r2 re-review 3 | A paste-safe procedure with explicit probe handling | §5.10 |
| r3 review 1–3 | Implementation proofs, binding on their lanes: completion proof before a reduced charge; withdrawal across grants; isolation in the real child | §10 |
| C2 | Resolved by the coordinator's repository check; the runtime discovery guard stays | §4.4 |
| C1 | The executor forms `execute` and `workflow` are dropped from the measurement; a follow-up | §5.10 |
| D5 | Deferred; a follow-up with the review's scoping | §6 |
| D6 | `grok-4.7` and `high` only for the first run | §5.4 |

## §10 Binding acceptance criteria (r4)

These are acceptance criteria of the named lanes, in addition to the plan's. A lane is not
done, and D4 is not asked, until each is met by a test that runs in hosted CI; BA-3 also
runs on the measuring host.

- **BA-1 (lanes L2a and L2b) — completion proof before a reduced charge.** Per §5.3. L2a:
  `proxy.mjs` writes the end-of-stream marker only on orderly shutdown. L2b: settlement
  below the full budget requires clean exit, the marker, a matching count and no protocol
  error. Tests: an abrupt proxy exit that leaves a syntactically valid stream with zero
  events is charged in full; a stream truncated mid-record is charged in full; a shutdown
  that takes `start_proxy`'s timeout kill path is charged in full; an orderly shutdown with
  zero events settles to zero.
- **BA-2 (lane L2b) — withdrawal holds across grants.** Per §5.7. Test: grant A measures and
  publishes route R; grant B reserves R, which withdraws it, then fails or is interrupted;
  `--aggregate` for grant A does not republish R and reports it `superseded`; the gate
  refuses a cached receipt for R. A second test shows a catalog route for the same key
  still wins, unaffected by the register.
- **BA-3 (lane L2c; measurement path in L2b) — isolation proven in the real child.** Using
  the real launch-owner composition (`seat_profile` plus `launch_owned(PROVIDER_REVIEW)`),
  not a stand-in for it, **one and the same unjailed child process** must show both: a
  request through the proxy to the fixture upstream succeeds, and a direct connection from
  that child to a fixture listener that is reachable from the host at that moment fails.
  The test first shows the listener is reachable from outside the namespace, so a failure
  inside is the namespace's doing. The final context check is bound to the exact owned
  holder and proxy (§4.6), with a test that a different live holder or proxy is refused. The
  measurement launch uses `PROVIDER_REVIEW` and passes the same check. Where each half is
  proven (erratum 4):
  - **Hosted CI, both halves.** The dual proof above, with a fixture upstream, runs as a
    mandatory hosted check with `PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1`. With that variable
    set a missing namespace prerequisite is a failure, never a skip. The allowed-request
    round trip to an upstream is proven **only** here. The check must have executed, with
    no skipped case, on the merged head before D4 is asked.
  - **On the measurement host, isolation only.** `measure-tools --verify-probe initial` proves, before any
    credential is projected, that the real child reaches only this launch's proxy and that
    its direct connection to a host-reachable listener is refused. It makes no claim about
    an allowed request reaching an upstream; on the measurement host the first such request is the pilot's.
  A host where the isolation check cannot run is not eligible to measure or to consume the
  basis.

## Errata

### Erratum 1 (2026-11-20) — Claude Code managed settings in the launch context

Source: the lane L1 code review and the coordinator's ruling.

`/etc/claude-code/managed-settings.json` is Claude Code's managed-settings file, and grok
reads it too. It joins the managed-config condition of `grok_seat_context.v1` (§4.4) beside
the two `/etc/grok` paths, with a different rule:

- it must be **absent from the seat's effective view**, in the measurement and at every
  launch that relies on the frozen basis. The final context check (§4.4, step 2) verifies
  that against the composed profile: the path does not resolve inside the child's view;
- the launch is **not** refused merely because the file exists on the host. A host that has
  it stays eligible as long as the composition hides it from the seat;
- the path is one of the managed-config paths in `context_digest`, so the digest value
  changes with this erratum (§8). No frozen record, receipt or catalog entry existed under
  the earlier value, so nothing needs re-measuring.

The rule for the two `/etc/grok` paths is unchanged. Nothing else in the contract changes.

### Erratum 2 (2026-11-20) — `child_absent_policy` in the context digest's canonical inputs

Source: the lane L1 re-review (last paragraph) and the coordinator's ruling.

Erratum 1 said the Claude Code managed-settings path is "one of the managed-config paths in
`context_digest`". The L1 implementation keeps it in a field of its own, because its rule
differs (absent from the seat's view; the host may hold it). The contract follows the
implementation, so the measurement and every verification derive the same digest. This
erratum supersedes that one sentence of erratum 1; the absence rule of erratum 1 and of the
§4.4 table stands.

`context_digest` is the sha256 of the canonical JSON of this document — keys sorted,
separators `,` and `:`, ASCII only, no trailing newline:

```json
{
  "schema": "grok_seat_context.v1",
  "home": "<the private seat home path>",
  "projected_paths": ["<sorted: the credential and proxy projection paths>"],
  "environment": {"allowed": ["<sorted variable names>"],
                  "forbidden_prefixes": ["GROK_", "XAI_"]},
  "managed_config": ["/etc/grok/managed_config.toml", "/etc/grok/requirements.toml"],
  "child_absent_policy": ["/etc/claude-code/managed-settings.json"],
  "discovery": ["<the pinned discovery set>"],
  "egress": {"allowlist_id": "grok-review", "content_digest": "<allow-list content digest>"},
  "composition": "<the launch-owner composition identifier>"
}
```

- `managed_config`: paths that must not exist on the host at launch and must not be visible
  to the child.
- `child_absent_policy`: paths that must be absent from the seat's effective view, in the
  measurement and at every launch; existence on the host alone does not refuse. It is a
  list, in the order the code pins, and today holds the one path above.

Adding the field changes the digest for any fixed allow-list digest. No frozen record,
receipt or catalog entry existed under an earlier value. Nothing else in the contract changes.

### Erratum 3 (2026-11-20) — tolerated startup refusals, output location, host class, a lane note

Source: lane L2b's findings ("Needs your decision"), lane L2a's offline client observations,
and an offline read of the 1.0.89 binary's strings and bundled documentation. No live call.

**1. Tolerated refusals (amends §5.5).** §5.5 required "no denial of any kind". Applied
literally, the pilot would be `egress_refused` and its one request wasted, because 1.0.89
makes requests of its own that `grok-review` refuses. A denial no longer disqualifies a
launch when the proxy's observation of it matches one entry of this closed list exactly:

| Observation at the proxy | What it is | Evidence |
|---|---|---|
| `GET` `cli-chat-proxy.grok.com:443` `/v1/settings`, denied | the startup fetch of remote settings | bundled documentation: grok reads its servers' settings at startup, with a bounded wait; L2a's fixture test refuses this row |
| `CONNECT` `x.ai:443`, denied | the updater's release check (`GET /cli/stable` inside the tunnel) | observed offline by L2a through the fixture proxy |
| `CONNECT` `storage.googleapis.com:443`, denied | the updater's artifact host | observed offline by L2a |

Rules:

- The list is closed and lives beside the discovery set in `grok_tool_surface.py`, pinned by
  a test. Adding an entry needs an erratum here. It is not part of `context_digest`: it
  qualifies a measurement and constrains no launch.
- A tolerated refusal may come before or after the counted request. Each is recorded in the
  result and the aggregate as `tolerated_refusals` (the entry and a count), metadata only.
- Everything else still disqualifies, in particular: a second `POST` to the inference host,
  whether denied by the allow-list or by the spent budget (`budget_exhausted`; a later model
  call may rewrite the artifact even when refused); any request to `accounts.x.ai` or
  `auth.x.ai` (the credential is expired); any other method, path or host; a TLS failure; an
  incomplete observation. The positive requirements of §5.5 are unchanged: exit 0, exactly
  one allowed counted request, the completion proof of BA-1.
- The same refusals happen at every board launch, since it runs under the same allow-list.
  Nothing is added to the allow-list.

Why this option, of the three considered:

- **(b) tolerated refusals — adopted.** Nothing new leaves the host, so the network scope
  is exactly what it was. It also keeps two server-controlled inputs out of the seat that
  the digests cannot bind: remote settings, which the documentation says can switch features
  on or off, and the updater, which could replace the measured binary. Refusing both makes
  the measured surface depend on less, at measurement and at use alike.
- **(a) a switch — not adopted.** The documentation lists `--no-auto-update`,
  `GROK_DISABLE_AUTOUPDATER=1`, `[cli] auto_update = false`, and automatic suppression when
  stderr is not a terminal, which is the seat's case already. The flag would change every
  form's argv digest. The variable needs an exception to the §4.4 rule that no `GROK_*`
  variable is set, and a new context digest. The config key needs a `config.toml` in the
  private home. None of them covers the settings fetch, for which no switch was found. So a
  switch would add an input to the context and still leave (b) necessary.
- **(c) allow rows — rejected.** It widens egress, and for these two endpoints it would
  admit exactly the unbound inputs named above.

Limit, stated plainly: the list comes from offline observation of the sign-in and updater
clients and from documentation. The inference client could not be exercised offline, so a
startup or shutdown request not listed here (telemetry is the likely one) would still make
the pilot `egress_refused`. That outcome stays fail-closed and costs one request.

*Proposed, not adopted by this erratum:* a rehearsal before the pilot would remove that
risk — the pilot's exact launch under a proxy with `request_budget=0`, so every request is
refused and observed, nothing is forwarded and no model call is made. It would need a
`--rehearse` stage in `measure-tools` and one more credentialed launch in the owner's grant.

**2. Output location (amends §5.9, reconciles it with §5.10).** `--output` may be any path
under the operator's private state home, outside a git work tree. The §5.10 path
`$HOME/.local/state/phase-loop/grok-surface/$GRANT` is such a path. The grant ledger and the
host-local record stay under `president_adapter.private_record_root()`, as §5.3 and §3.2 say.

**3. Host class (amends §5.10).** The measurement-host run passes `--host-class team`; the script's `MT`
array now carries it. The tool's default is `standard`, and the §5.8 aggregate records
whichever was passed.

**4. Lane note.** Lane L1 left the proxy-projection constants of the launch context empty
for L2a to fill, and L2a was built independently. Lane L2b fills them —
`PROXY_PROJECTED_PATHS` (the egress CA file in the private home) and `PROXY_ENVIRONMENT`
(`HTTPS_PROXY`, `SSL_CERT_FILE`) — with a test holding them equal to L2a's names. Both L2b
and L2c need them: without them no measurement or board launch passes the final context
check. They are inputs of `context_digest` (`projected_paths`, `environment.allowed`), so
its value changes when L2b lands (§8).

### Erratum 4 (2026-11-20) — a binding rehearsal before the pilot; where BA-3's two halves are proven

Source: the coordinator's ruling on erratum 3's proposal, and lane L2b review finding 3.

**1. The rehearsal is binding (amends §5.10; supersedes the "proposed, not adopted"
paragraph of erratum 3).**

- **What it is.** `measure-tools --rehearse --route review`: the pilot's exact launch — same
  form, same argv-digest check, same context check, same credential projection, same
  composition and namespace — under a proxy started with `request_budget=0`. With a zero
  budget the proxy refuses every request, counted or not, and observes each. Nothing is
  forwarded, so nothing reaches the vendor and no model call is made.
- **What it must show.** The proxy's observation, with BA-1's completion proof, contains
  only: denials matching the erratum 3 tolerated list, and the budget's own denial of a
  `POST` to the inference host on the allow-listed path (any number of client retries of
  it). No allowed request. The client's exit status does not matter; it is expected to fail.
- **What stops the procedure.** Any other observed request, an incomplete observation, or
  no observation of the inference request at all (the client never got as far as the
  pilot would). `--require-rehearsed review` then exits non-zero and the pilot is never
  launched, so its request is not spent. The observation is recorded, metadata only
  (method, host, templated path, decision), for an erratum.
- **Accounting.** It reserves nothing, settles nothing and is charged nothing; it is not one
  of the planned launches and uses no retry. It is recorded immutably in the grant as a
  rehearsal. The pilot's reservation is refused unless the grant holds a passing rehearsal
  of the same route, binary and context digest. One rehearsal per grant; a second, after an
  erratum, is a new grant.
- **Artifacts.** A session artifact a rehearsal leaves is never a capture: it is removed
  with the scratch directory and nothing is copied out. Its log is retained as §5.9 states.
- **In the grant.** It is one credentialed launch on the measurement host inside the owner's D4 grant, in
  addition to the three planned launches and two retries. The D4 ask must name it.
- Lane L2b implements `--rehearse` and `--require-rehearsed`, with tests on a recording
  runner: a passing rehearsal; an untolerated request; a missing inference request; an
  incomplete observation; the pilot refused without a passing rehearsal.

**2. BA-3 is split by where it can be proven (amends §10 BA-3 and §5.10).** As rewritten in
§10: the hosted check with `PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1` proves both halves and is
the only proof of the allowed-request round trip; `--verify-probe initial` on the measurement host proves
isolation only. The hosted check must have executed without skips on the merged head before
D4. §5.10 now lists that as a precondition, and the script requires
`GROK_HOSTED_CHECK_RUN` and records it in `grant.json` through `--hosted-check`.

Nothing else in the contract changes.

### Erratum 5 (2026-11-20) — the Claude SDK proof region `_run_leg_with_liveness`

Source: the coordinator's ruling.

`_run_leg_with_liveness` in `panel_invoker.py` is one of the Claude SDK proof regions
(`claude_seat_transport.SDK_PROOF_REGIONS`, which lists 56 regions of `panel_invoker.py` at the
pinned commit). Lane L1
changes it and lane L2c changes it again (§4.6), so that region's proof binding moves in
both lanes. The other 55 `panel_invoker.py` regions are unchanged. §8's table now has that row.

- **No SDK receipt is required now.** `claude_seat_sdk.ADMITTED` is `False` on `main`, so the
  transport gate refuses `sdk` and requires no receipt for a moved region, as with
  Consiliency/agent-harness#2019.
- **A future admission must bind the then-current region.** When the SDK transport is
  admitted, its proof must be taken over `_run_leg_with_liveness` as it then stands, with
  the L1 and L2c changes in it; a binding to an earlier version of the region is not valid.

Nothing else in the contract changes.

### Erratum 6 (2026-11-20) — the full Claude SDK proof movement, and `runtime_digest()` per lane

Source: the final pin accounting of the accepted lanes (lane L2c's report, last section),
the lane L2b reviewer's required row, and the coordinator's ruling.

These are values the lanes already produced and their reviews accepted, recorded here after
the fact. They are lane outputs, not targets: nothing below pins a future commit, and a
later merge or rebase that changes them needs no amendment to this contract.

**Corrects erratum 5.** Erratum 5 named one moving SDK proof input, the region
`panel_invoker.py::_run_leg_with_liveness`, and said the other 55 `panel_invoker.py` regions
are unchanged. That understates the movement. Four SDK proof inputs move: two regions and
two whole files. Of the 56 `panel_invoker.py` regions, 54 are unchanged, not 55. Erratum 5's
§8 row stays; §8 gains the rows below it.

Lane heads measured, against `main` @ `5c0f4a399385992f5430936d2e03f48964866868`:
L1 `f188a9caed2d7bb612ed82168bbf17aba0a1e8e2`, L2a `d0603bc6c50ff5f4ee872c5c3e19b2413b055fd8`,
L2b `67e2240799a3c270de8f1cbc919498727a4480c1`, L2c `c6d7ec411a43a669d7ff899c58e50e796907056c`.
Each input is hashed with SHA-256 as `sdk_proof_bindings` hashes it: a whole file, or a
region as `source_region` cuts it. "=" means unchanged from `main`.

**SDK proof inputs that move.**

| Input | main | L1 | L2a | L2b | L2c |
|---|---|---|---|---|---|
| `claude_seat_transport.py` (whole file) | `8d9b6f4cb70d8f84b918e6b00c1b837542e55e80129e251e4bf186c7d7e4ddd2` | `429f5bb9bd24d3853e48b4b30845ec5f7583233021196105c83cfeebbd980d1e` | = | `1adb7847c242ace415cb31ba278bd8c62f12d5ffa9b6a48bf93367b6849e6b4f` | `ed4433fd0133276c63b79ef02ac64834f3f700dcf5925729bb1bf0a9b98244b4` |
| `seat_resource_caps.py` (whole file) | `17335330a18a01ebd422475011e10a748624ee43e1e3a48bec6dbc1fc02ef619` | = | = | `4fbceccb6cb6154f78fad483bb0b06717db9bd2125a4bda6d25761defbadebac` | `4fbceccb6cb6154f78fad483bb0b06717db9bd2125a4bda6d25761defbadebac` |
| `panel_invoker.py::_run_leg_with_liveness` (region) | `8d2545a1c4b00358b4fb2018cb51b1760ed09d5b53a53aeea40f895c07f650d2` | `39b6a3edad0b0dfb25af23deab036a0a7ace4aefbea41d4c491ed8eaea57ad35` | = | `39b6a3edad0b0dfb25af23deab036a0a7ace4aefbea41d4c491ed8eaea57ad35` | `2182661eed73fe10216b0bf0fc84a810dd0b795c507631c848f00c02af11ce1a` |
| `panel_invoker.py::launch_provider` (region) | `c49789cc4c780faf715637b8c4744315926e614e38bb23582cf53d003016402b` | = | = | `e98bfe11c785698180c5596ffb53665aa84c915ac92392bd66c110ad6fff96f9` | `e98bfe11c785698180c5596ffb53665aa84c915ac92392bd66c110ad6fff96f9` |

Which lane introduces each move:

- **L1:** `_run_leg_with_liveness` (the jailed-route grok gate) and `claude_seat_transport.py`.
- **L2a:** none. It moves no SDK proof input.
- **L2b:** `launch_provider` (the rehearsal spawn hook) and `seat_resource_caps.py` (the
  rehearsal `before_spawn` hook), and `claude_seat_transport.py` further. Its
  `_run_leg_with_liveness` region is L1's.
- **L2c:** `_run_leg_with_liveness` further (the board leg's egress and final check, §4.6)
  and `claude_seat_transport.py` further. Its `launch_provider` region and
  `seat_resource_caps.py` are L2b's.

Every other SDK proof input is byte-identical at all five commits.

**The proof lists are unchanged.** `SDK_PROOF_REGIONS`, `SDK_PROOF_FILES` and
`SDK_PROOF_ALIASES` are the same at `main` and at every lane head. `SDK_PROOF_REGIONS` holds
the same 80 regions: 56 in `panel_invoker.py`, 9 in `seat_jail.py`, 15 in `seat_uid.py`. No
region is added or removed.

**`SDK_PROOF_UNBOUND` classifications.** The only edit any lane makes to
`claude_seat_transport.py` is a pure insertion into `SDK_PROOF_UNBOUND`, with no line
removed. Names added for `panel_invoker.py`:

| Lane | Added |
|---|---|
| L1 | `_grok_gate_with_basis` |
| L2a | none (the file is unchanged) |
| L2b | `_caps_spawn_hook` |
| L2c | `_grok_leg_launch_egress`, `_grok_leg_final_check` |

Each lane head carries the names of the lanes it builds on. The dependency check stays
closed: every name a proof region reaches is still classified, as bound or as unbound, and
none is left unclassified.

**`seat_window.runtime_digest()` at each head.**

| Head | Value |
|---|---|
| main | `a13a4654d333a8b54380f7da16f58f8e59cabb4cdecd89af9fbb70734a12c28a` |
| L1 | `9ec9871dd179d6a6bd0f90b7c633c61873163baebf4a15198fecb5d62ab293b5` |
| L2a | `49802e12c7898a218b7e0b313481152339201630c67c14d43eea680191a2fddc` |
| L2b | `762046b8e677c5fb257a0beb9e9d1d33945ccb7e62e95297dd6f09422c5b560f` |
| L2c | `0aeb46fe260b0b74b205cb7ed2994db693132c99c8de7d5d0f43db6120f457cf` |

L2a's value moves from its own files — `proxy.mjs`, `seat_egress_proxy.py`, the `grok-review`
allow-list, and `panel_invoker.py` outside every proof region. Lane L3 is data only and
moves neither this digest nor any SDK proof input. The window requalification of §8 is
unchanged.

**No SDK receipt is required now.** `claude_seat_sdk.ADMITTED` is `False` on `main`, so the
transport gate requires none (erratum 5, Consiliency/agent-harness#2019). A future admission
must bind **every** SDK proof input as it then stands — all four above included — not the
values in this table.

Nothing else in the contract changes.

### Erratum 7 (2026-11-20) — publication redaction, and an accounting note on erratum 6

Source: the integrator's publication check and the coordinator's ruling.

**1. Redaction (wording only).** The plan, this contract and the plan's manifest entry land
in a public repository. They no longer name a private repository's issue, the private
location of the review records, or the host the measurement runs on. The replacements are
"a downstream board run", "the engagement's review records" and "the measurement host".
Fixture directory names keep their last path component only.

- No requirement, gate, grant, budget, schema, rule or acceptance criterion changes.
- No digest changes: the five fixture digests in the header, the binary, version and help
  digests, and every value in erratum 6 are as they were. They pin inputs and recorded
  lane outputs, none of which is one of the three edited files.
- The manifest entry pins no digest of the plan or of this contract, so nothing is
  re-stamped; only its `task_summary` wording changed.
- Where a rule said the measurement runs on a named host, it now says "the measurement
  host": the one review-seat host the owner's D4 grant names. The grant, not this document,
  identifies it.

**2. Accounting note on erratum 6.** Erratum 6's values were measured for each lane against
`main` @ `5c0f4a399385992f5430936d2e03f48964866868`. `main` has since moved two SDK proof
inputs by its own landed changes: `seat_resource_caps.py` (Consiliency/agent-harness#2019)
and `uv.lock` (Consiliency/agent-harness#2022). Values measured on an integrated tree
therefore differ from erratum 6's by exactly those changes of `main`; the movement
attributable to the lanes is exactly erratum 6's. No integrated or later `main` value is
recorded here, because that would pin an output against a moving `main`.

Nothing else in the contract changes.

### Erratum 8 (2026-11-21, revision r2) — grok 1.0.92: an immutable seat config, per-image tolerated refusals, closed path diagnostics

Source: the coordinator's ruling choosing a pinned local model entry, revised (r2) after plan review. None of the evidence below involved a live call:
- the D4 rehearsal of grok 1.0.92 under a budget-0 proxy, which was refused `unlisted_request` with nothing forwarded;
- one screened read of that rehearsal's record and its `provider.log` (the child's stdout and stderr). This is not the client's own log of item 5;
- an offline, credential-free observation of the same binary: seven launches in a network namespace with no route out, through a local recorder that forwarded nothing and answered 403 to every request. Launches 1–6 used a plain writable config file; launch 7 used the read-only projection of item 1. A separate launch with no grok proved the projection's mount behaviour. All are in the engagement's review records, `grok-offline-catalog-test/`.

The image is grok 1.0.92, sha256 `add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb`.

**Notation.** Each claim below is marked as one of three kinds:
- **[observed]:** seen in the offline launches or the rehearsal record;
- **[documented]:** taken from the documentation bundled in the 1.0.92 binary;
- **[inferred]:** concluded from what was observed, but not itself observed.

The list at the end covers the untested material claims. For each one it names the single offline launch that would confirm it. None of those launches has been run.

**What the evidence shows.**

- **Blocking [observed].** Without a local entry, 1.0.92 fetches its model list (`GET /v1/models`, twice). With that fetch refused, its catalog holds only the two built-in models. `grok-4.7` is not among them, so the client exits 1 with `unknown model id` before making any POST. That is why the rehearsal saw no inference request.
- **The rehearsal's six `<other>` GETs.**
  - The rehearsal record names no paths. The offline baseline (no local entry) made six GETs other than `/v1/settings`: `/v1/models` ×2, `/v1/bundle/archive`, `/`, `/v1/subagents/bundle` and `/v1/feedback/config`, all on `cli-chat-proxy.grok.com` [observed]. They are consistent with the record's six, but they cannot recover its original paths [inferred].
  - Only the model list blocks. Every request except `GET /` carries `authorization` and identity headers [observed].
- **With the seat config of item 1 (launches 6 and 7) [observed].**
  - There is no `/v1/settings` and no `/v1/models` request.
  - The effort warning is gone, and the inference body carries a `reasoning_effort` key. Its value was not logged.
  - The client reaches `POST /v1/chat/completions`, with model `grok-4.7`.
  - The remaining refused requests are four GETs and two `POST /v1/responses` on model `grok-4.6`. All came before the inference request, and the client went on past each of them.
  - **The order of the four GETs varied:** `/` came second in launch 6 and third in launch 7. The two POSTs came after all four GETs both times, and the inference request came last.
- **Two limits on this evidence.**
  - The recorder always answered 403, and the launches used the `review` argv. That a board launch behaves the same way is an expectation [inferred].
  - The two POSTs carry `input`, `tools` and `tool_choice` (key names observed), so they may carry content derived from the prompt. Their purpose and actual content are [inferred].

**1. The seat config and the fixed inputs (amends §4.4 "Home" and §5.1; adds a context input; lane E8-A).**

*1a. Content.*
- The grok seat's private home gets a harness-written `.grok/config.toml` holding exactly these 424 bytes, with sha256 `2984e0c368943bb6c1627146e413995df12cca5820e782adffcb052a9b761780` (`SEAT_CONFIG_SHA256`), and nothing else:

  ```toml
  [model."grok-4.7"]
  model = "grok-4.7"
  name = "grok-4.7 (pinned local entry)"
  base_url = "https://cli-chat-proxy.grok.com/v1"
  api_backend = "chat_completions"

  [[model."grok-4.7".reasoning_efforts]]
  value = "low"
  label = "Low Effort"

  [[model."grok-4.7".reasoning_efforts]]
  value = "medium"
  label = "Medium Effort"

  [[model."grok-4.7".reasoning_efforts]]
  value = "high"
  label = "High Effort"

  [features]
  remote_fetch = false
  ```

- **These exact bytes ran in launch 7 [observed].** Launch 6 ran a fragment whose parsed TOML value is equal; it differed only by comments and table order.

*Frozen fields and where each comes from.* A test pins each one.
- **The table key and `model`:** `grok-4.7`, equal to `MEASUREMENT_MODEL` (ruling D6), which is the board leg's model (§4.6).
- **`base_url`:** `https://` + `INFERENCE_HOST` + `/v1`. It is the client's documented default proxy base, and its host is that of the only `grok-review` allow row.
- **`api_backend`:** `chat_completions`. It is the documented default, and its endpoint is the allow row's path, `/v1/chat/completions`.
- **`reasoning_efforts`:** low, medium and high, as tested; `high` equals `MEASUREMENT_EFFORT`. Without these rows the client ignores `--reasoning-effort high` [observed].
- **`name`:** display text only.
- **`[features] remote_fetch = false`:** documented as "allow optional online model-catalog fetches (default: true; set false for firewalled/air-gapped deployments)".

*When it is projected.* `seat_profile` (grok branch) projects the config only when the profile composes with the `grok-review` egress proxy: the measurement, the rehearsal and the frozen-basis board leg. Every other grok profile composes byte-identically: the same mount arguments, environment and descriptors.

*1b. The projection is immutable (replaces r1's writable `--file`).*
- **The descriptor.** The bytes go into a sealed memfd from the existing helper `seat_jail.memfd_with`. It is called, not edited, and its SDK-bound region does not change. It is created with sealing allowed, written in full, sealed against write, grow, shrink and further sealing, and rewound to offset 0.
- **The mount.** The profile projects the memfd with exactly one triple: `--perms 0444 --ro-bind-data <fd> /home/phase-loop-seat/.grok/config.toml`. bubblewrap reads the descriptor while it sets up and bind-mounts the result read-only, so the child sees a read-only mount point. The CA file of §5.2 is already projected this way.
- **What the boundary refuses [observed in the launch without grok, from an unprivileged child under the same bwrap form].**
  - An append fails with `EACCES`.
  - A truncation and a `chmod` fail with `EROFS`.
  - A rename over the file, and an unlink of it, fail with `EBUSY`, even though the parent `.grok/` is writable.
  - `umount` is refused.
  - The bytes were unchanged afterwards.
  - Because a mount point cannot be replaced through its parent directory, a writable parent does not weaken it.
- **What the client does with it [observed, launch 7, with a file-call trace].**
  - Each launch, the client rewrites its config. In launch 7 it wrote a temporary file in `.grok/`, and `rename` of that file over `config.toml` returned `EBUSY`. The client removed the temporary file and went on: it reached the inference request with no `/v1/settings` and no `/v1/models`, exactly as in launch 6.
  - So the failed rewrite is not fatal. The `[marketplace]` line that r1 saw appended lands nowhere.
- **The client re-reads its policy layers throughout a launch [observed].** In a launch of about one second it opened `.grok/config.toml` 469 times, `.grok/requirements.toml` 555 times and `.grok/managed_config.toml` 440 times. With the config immutable, every one of those reads returns the pinned bytes.
- **Binding the descriptor bubblewrap consumes.** The final context check (§4.4 step 2) and `verify_measurement_context` (both retained) locate the one `--ro-bind-data` triple for `.grok/config.toml` in the composed mount arguments, and check the descriptor named there:
  - it is a memfd whose `F_GET_SEALS` is exactly those four seals;
  - its `fstat` size is 424;
  - its sha256, read with `os.pread`, equals `SEAT_CONFIG_SHA256`. The read must not consume the descriptor: a read that leaves the offset at EOF would hand bubblewrap an empty file, and a test refuses that helper;
  - its offset is 0 at handoff;
  - it is in the profile's `pass_fds` and not in its `keep_fds`;
  - it is owned by the profile's exit stack, so it stays open until the launch has exited and is closed after.
- **Mount normalisation.**
  - The destination must be exactly that string, and absolute and normalised (`posixpath.normpath` returns it unchanged).
  - No other mount operation of any kind may have a normalised destination equal to it or below it. That covers bind, ro-bind, dev-bind, file, bind-data, ro-bind-data, tmpfs, dir, symlink, remount-ro, chmod and the overlay forms.
  - Above it, only the home tmpfs and the `--dir` for `.grok` are allowed. No bind, tmpfs, symlink or overlay may be placed over `.grok/` or the home.
  - The home exception therefore admits this one mount and nothing else.
- **The digest is the effective configuration.** The file cannot change after the check, so the pre-launch digest is the configuration in force for the whole launch, re-reads included.
- **The home rule, amended.** §4.4 "Home" read "nothing but the projected `.grok/auth.json` and `.grok/agent_id`, plus the egress proxy projection of §5.2". It now reads "…plus the egress proxy projection of §5.2 and the read-only seat config of erratum 8, and nothing else".
  - **Refused**, each as `grok_tool_surface_unverified`: a missing config; a second mount at that path; differing bytes; an unsealed descriptor or wrong seals; a non-zero offset; a writable `--file` or a host bind at that path; a mount above it; an un-normalised destination; or any other added path.

*1c. The fixed inputs (`SEAT_FIXED_INPUTS`).*

These are the inputs that decide the inference route and body, the policy, and the offered tools. They must not change during a launch.
- **Derivation.** E8-A derives the tuple from the documentation bundled in 1.0.92 and from launch 7's file-call trace, records the derivation in the test that pins it, and starts from at least the entries below. Paths are relative to the seat home unless absolute.
- **Policy layers.**
  - `.grok/config.toml`;
  - `.grok/managed_config.toml` and `.grok/requirements.toml`;
  - `/etc/grok/managed_config.toml` and `/etc/grok/requirements.toml`;
  - `/etc/claude-code/managed-settings.json`. Erratum 1's exclusion of it from the child's view is preserved;
  - the managed-sync state: `.grok/managed_config_cache.json`, `.grok/managed_config.sig.json`, `.grok/managed_identity.sig.json` and `.grok/staged/managed_config_refresh.json`. Launch 7 shows the client reading or unlinking each [observed];
  - client caches that can carry configuration: `.grok/models_cache.json`, `.grok/experiments_state.json` and `.grok/campaigns_state.json` [observed read].
- **Discovery sources in the home.**
  - `.grok/` `skills`, `agents`, `plugins`, `installed-plugins`, `hooks`, `hooks-paths`, `disabled-hooks`, `workflows`, `lsp.json`, `sandbox.toml`, `trusted-plugins`, `trusted-hook-projects`, `trusted_folders.toml`, `mcp_preferences.json`, `mcp_credentials.json` and `settings.json`;
  - `.claude.json`, `.claude/`, `.cursor/`, `.agents/`, `.mcp.json` and `.config/grove/`.
- **Project discovery.** The pinned discovery set at the cwd, each `--add-dir` and their visible ancestors (§4.4), unchanged.
- **Environment and argv.** These are fixed by `exec` and cannot change.
- **Why project config cannot change the model mapping [documented].** A project `.grok/config.toml` contributes only `[mcp_servers]`, `[plugins]`, `[env]` and `[permission]`, so the model mapping can come only from the policy layers above.

*1d. How the boundary holds, by form.*
- **`.grok/config.toml`:** immutable in every form (1b).
- **`/etc` paths:** absent on the host at launch and outside every writable mount of the seat (§4.4, unchanged).
- **The other fixed inputs, in `review` and `sealed`: change is ruled out by the measured tool surface.**
  - Frozen-basis eligibility at use requires the receipt's admitted names to be a subset of the closed tuple `NON_MUTATING_TOOLS` = (`read_file`, `list_dir`, `grep`, `search_tool`). The empty set qualifies, which is `sealed`'s `--tools ""`.
  - Under such a surface the only writer in the seat is the client.
  - **Launch 7's trace shows the client's own writes in the home [observed]:**
    - the refused config rename;
    - three empty lock files (`.config-init.lock`, `managed_config.lock`, `installed-plugins/registry.lock`);
    - unlinks of the absent managed-sync files, which returned `ENOENT`;
    - its docs, sessions, log and worktree database.

    None of these adds content to a fixed input.
  - **Residual:** client writes after a *successful* model response were not observable offline. They are limited by egress: every non-inference request is refused, so no remote settings or managed sync can load.
- **The other fixed inputs, in `staged`: not bounded by this erratum, so `staged` is ineligible for the frozen basis at use.**
  - Its run and write tools can create any fixed-input path in the writable home and the staged tree. The client re-reads its policy layers continuously [observed], and it documents hot reload of skills, of project MCP configuration (watches on `<cwd>/` and `<cwd>/.grok/`) and of configuration.
  - Masking each creatable path with an immutable empty mount point is the candidate, but it is not adopted. The client unlinks its managed files at start [observed], and how it treats a read-only placeholder is untested.
  - So the §4.4 consumer audit gains a row: a board leg on the `staged` form, holding a frozen-basis receipt, is **ineligible**. It is refused `grok_tool_surface_unverified` at the final check.
  - `staged` may still be **measured**. The definitions artifact is written before the inference request [observed], and item 2's order rule disqualifies any later inference POST.
  - Admitting `staged` at use needs a later erratum, resting on an approved, no-egress launch of the masked projection.
- **Confirmation before a credentialed launch.** Launch 7 (authorised, no egress, the pinned bytes under `--ro-bind-data`, the `review` argv) settles the client's tolerance of the read-only projection. The remaining difference from production is composition: the tmpfs home, the CA file and the launch-owner composition. The hosted stand-in test of 1f closes it, and so does any binding rehearsal, which stops before a counted request.
- **No reload behaviour is relied on.** The design relies on immutability (`config.toml`) and on the absence of any writing tool (`review`, `sealed`), never on the client not reloading.

*1e. `context_digest` changes.*
- `grok_seat_context.v1` gains one field: `"seat_config": {"path": ".grok/config.toml", "sha256": "<SEAT_CONFIG_SHA256>", "projection": "ro-bind-data"}`, plus the `SEAT_FIXED_INPUTS` tuple and `NON_MUTATING_TOOLS`. The schema name is unchanged, as with erratum 2, so the digest value changes.
- Private history is not presumed empty. The failed D4 rehearsal exists, and any earlier frozen record is stale under the new value. It is never reused: its context and its runtime both differ.
- The argv forms and their digests do not change.

*1f. Falsifiers (lane E8-A).* Each refusal must refuse alone, at the final check and at the measurement check, with no launch.
- **Refusals:**
  - a profile with no config;
  - one byte changed;
  - a second mount at the path;
  - a writable `--file` at the path;
  - a host bind at the path;
  - a `--bind`, `--tmpfs` or `--symlink` over `.grok/`;
  - `.grok/./config.toml` and `//` forms;
  - an unsealed memfd, or one missing one seal;
  - a descriptor at EOF, or a hash helper that consumes it;
  - a wrong size;
  - a descriptor absent from `pass_fds`, or a different descriptor number;
  - a frozen-basis profile composed without the proxy;
  - a home holding `.grok/managed_config.toml` or `.grok/requirements.toml`;
  - a `staged` board leg on a frozen-basis receipt;
  - a `review` or `sealed` receipt whose admitted names leave `NON_MUTATING_TOOLS`.
- **Also:**
  - an ordinary grok profile (no egress proxy) is byte-identical to `main`'s;
  - `context_document` carries the fields, and `context_digest()` changes when any config byte changes;
  - **a hosted stand-in test through the real launcher (bubblewrap), part of BA-3.** A stand-in grok attempts an append, a truncation, a rename-over, an unlink and a `chmod` of `.grok/config.toml`, and reports each errno. It reads the sha256 at start and at exit, and both equal `SEAT_CONFIG_SHA256`. The board-leg stand-in of §4.6 still completes `sealed` and `review` with the child's home holding the projection plus this file.

**2. Per-image tolerated refusals, by cause and order (amends erratum 3, item 1; lane E8-B).**

- **A map keyed by image.** `TOLERATED_REFUSALS` becomes `TOLERATED_REFUSALS_BY_IMAGE`: a closed map from binary sha256 to a tuple of entries `(method, host, path, cause, order)`.
  - The key is the grant's pinned binary sha256 (§5.3), which every stage re-measures.
  - An image not in the map tolerates nothing.
  - The map is pinned by a test, and an entry needs an erratum here.
  - Within one image each `(method, host, path)` has exactly one entry, so it names one cause and one order.
- **1.0.89 (`a3dface51d9bdc71fd121e0481dd02d9b46a721f7a6b892f756480e9666eba1f`)** keeps erratum 3's three entries, with the causes the proxy has always written for them:

  | method | host | path | `cause` | order |
  |---|---|---|---|---|
  | `GET` | `cli-chat-proxy.grok.com` | `/v1/settings` | `rules` | any |
  | `CONNECT` | `x.ai` | — | `front` | any |
  | `CONNECT` | `storage.googleapis.com` | — | `front` | any |

  The two updater `CONNECT`s are refused at the tunnel front, by the proxy's CONNECT-authority check, which writes `cause` `front`. r1's blanket `rules` would have failed their existing updater controls.
- **1.0.92 (`add4d201…`)** has exactly these five:

  | method | host | path | `cause` | order | what it is |
  |---|---|---|---|---|---|
  | `GET` | `cli-chat-proxy.grok.com` | `/v1/bundle/archive` | `rules` | any | not identified; credentialed |
  | `GET` | `cli-chat-proxy.grok.com` | `/` | `rules` | any | not identified; no `authorization` |
  | `GET` | `cli-chat-proxy.grok.com` | `/v1/subagents/bundle` | `rules` | any | subagent definitions, by its name [inferred]; credentialed |
  | `GET` | `cli-chat-proxy.grok.com` | `/v1/feedback/config` | `rules` | any | the feedback system, by its name [inferred]; credentialed |
  | `POST` | `cli-chat-proxy.grok.com` | `/v1/responses` | `rules` | pre-inference | two calls on model `grok-4.6` |

- **Never tolerated, for either image.**
  - Any other cause: `inner_host`, `budget`, `shutdown`, or `front` for a non-CONNECT entry.
  - A `CONNECT` whose authority is not exactly `<host>:443`. The proxy's named channel matches only the literal port 443, so `0443` or another port is recorded under `<other>`.
  - Any `<other>` host or path, and any diagnostic label of item 3.
  - For 1.0.92: `/v1/settings`, `/v1/models` and both updater `CONNECT`s.
- **Order is defined by the proxy's decisions.**
  - An event's position is its place in the proxy's own event stream, which is the order the proxy wrote its decisions. It is not the client's send time.
  - "Pre-inference" means before the first allowed counted POST in a measurement, and before the first budget denial in a rehearsal.
  - A `POST /v1/responses` at or after that point disqualifies, as erratum 3 says of any further POST. The reason is that a later model call may rewrite the definitions artifact.
  - **The cost [inferred].** A reversal in the rehearsal costs zero requests. A reversed or extra post-turn POST in the pilot costs its one request and disqualifies it.
- **One predicate everywhere.** `tolerated(image, event, position)` is the only test, and these all use it:
  - `_classify`;
  - `_rehearsal_reason`;
  - `tolerated_summary`, which counts only events that pass it, so a late POST is never summarised as tolerated;
  - `_check_tolerated`, which now takes the image and validates a saved record against the map entry of that record's own `binary_sha256`;
  - result reload and aggregation.

  The record entry shape is unchanged (`method`, `host`, `path`, `count`), because one image's tuple fixes cause and order.
- **Refused only.**
  - None of these entries is ever allowed or forwarded, and none is a counted request (§5.3 counts allowed POSTs only). Nothing is added to the allow-list.
  - The proxy's `named` list for a grant is exactly that image's `(method, host, path)` entries (at most 16), so a match is verbatim.
- **Why the two POSTs are refused.** Forwarding them would send content that may derive from the prompt to a second inference route, which is neither measured nor counted.
- **Residual of normalised identity.** An entry matches the method, the host and the normalised URL `pathname`; the query is omitted.
  - So it cannot tell apart raw targets that normalise to the same pathname, or different purposes at the same method, host and path.
  - This affects classification only. The request is always denied, its body is discarded, and it has no effect on charging.
- **Counts.** Any number of each entry is tolerated, as in erratum 3, and recorded as `tolerated_refusals`, metadata only.
- **Not in the context.** The map is not part of `context_digest`, as erratum 3 said of its list: it qualifies a measurement and constrains no launch.
- **Falsifiers (lane E8-B).** Each runs for both images and for an unknown image, through the proxy's `named` list, the classifier, the rehearsal, the result, aggregation and reload.
  - The map is pinned, and each image's `named` list equals its entries.
  - An unknown image tolerates nothing.
  - On 1.0.89, the updater `CONNECT` denied with `front` is tolerated. The same authority on port `0443`, or carrying another cause, is not. `/v1/settings` denied with `inner_host` is not.
  - A 1.0.92 grant does not tolerate 1.0.89's entries, and a 1.0.89 grant does not tolerate 1.0.92's.
  - For 1.0.92, a rehearsal and a measurement each refuse on `/v1/settings`, `/v1/models`, `CONNECT x.ai`, an `<other>` path on the inference host, a diagnostic label, and a `POST /v1/responses` at or after the inference request. The late POST is absent from `tolerated_refusals`.
  - Mixed order: a GET after the inference request is tolerated, and a POST is not.
  - A saved 1.0.92 result validated against the 1.0.89 entry refuses.
  - A pilot with the five entries before its one allowed counted request is `measured`.

**3. Closed path diagnostics (replaces r1's templated paths; amends §5.2 and erratum 3; lane E8-C).**

- **No client-supplied path text.** r1's segment grammar is withdrawn. A lowercase segment can be a customer identifier, a credential fragment or prompt text. Every path on an allow-listed host that matches no rule, no named entry and no diagnostic stays `<other>`, as today.
- **A closed diagnostic table.** It is held identically in `seat_egress/proxy.mjs` and `seat_egress_proxy.py`, and a test compares the two. It is keyed by allow-list id. For `grok-review` it has exactly two rows:

  | method | host | path | recorded as |
  |---|---|---|---|
  | `GET` | `cli-chat-proxy.grok.com` | `/v1/settings` | `<diag:settings>` |
  | `GET` | `cli-chat-proxy.grok.com` | `/v1/models` | `<diag:models>` |

- **Bounds, identical for the producer and the reader.**
  - **Budgeted proxies only:** the measurement and the rehearsal. The label is written only for a denial with `cause` `rules`, and the event's `cause` is required.
  - **A named entry wins.** On a 1.0.89 grant, `/v1/settings` is named and is recorded verbatim, as today.
  - **The reader** (`seat_egress_proxy._valid_request_event`) accepts `<diag:LABEL>` only on a budgeted stream, for that row's host and method, with decision `deny` and `cause` `rules`. In a budgetless stream it refuses the stream.
- **A diagnostic decides nothing.**
  - It is not a path, and it can never equal a rule path or a named entry, since it begins with `<`.
  - It is in no tolerated map, and it never changes a status or a charge.
  - The same normalised-identity residual as item 2 applies.
- **Which record gets it.**
  - The rehearsal record's `observed` list does. That list is host-local in the grant directory, capped at 256 entries, and returned by the CLI.
  - **The measurement result record is unchanged.** It keeps its totals and tolerated entries only, so a disqualified pilot is `egress_refused` and names no path. No pilot field is added, and the aggregate is unaffected.
  - The rehearsal precedes the pilot and costs nothing, so the request is named there.
- **Scope.** Diagnostic rows exist only for an allow-listed host. A budgetless stream (every board leg, and the gemini and codex seats) is byte-identical, which is the §8 guard. The token-endpoint table is unchanged.
- **Falsifiers (lane E8-C).**
  - Each table row.
  - A planted all-letter path (`/v1/plantedwordzz`) and a planted segment (`/v1/users/plantedwordzz/token`) are recorded `<other>`. The test asserts that `plantedwordzz` is absent from the proxy stream, the rehearsal record's bytes and the CLI's captured output.
  - A query string never appears.
  - A budgetless proxy's stream is byte-identical for the same requests.
  - The reader refuses a label in a budgetless stream, for another host or method, on an allowed event, or without `cause`.
  - The existing gemini and codex egress tests pass unedited, and their allow-list digests are unchanged.

**4. Managed policy (confirms §4.4 "Managed config"; adds the home layers to item 1).**

- **Why it matters.** A managed grok setting overrides the user file for `remote_fetch` [documented: "Managed wins over the user file when both set"; requirements can pin it]. Of the three, this precedence and requirements pinning are untested. The native Linux paths match the bundled reference [documented].
- **The sources, and what closes each.**
  - **`/etc/grok/managed_config.toml` and `/etc/grok/requirements.toml`:** absent on the host and invisible to the child (`_check_managed_config`, unchanged).
  - **`$GROK_HOME/managed_config.toml` and `$GROK_HOME/requirements.toml`:** `GROK_HOME` is unset (`GROK_*` is forbidden), so these are in the seat's `.grok/`. They are fixed inputs (item 1c): absent at the final check, and not creatable in a form admitted at use (item 1d).
  - **Console-synced managed config (`features.managed_config`):** its route was not observed. Every request other than the inference POST is refused, so no remote policy can load whatever route it uses. If it uses a separate route, it is untolerated. If it shares a tolerated tuple, it cannot be told apart, but the 403 still loads nothing.
  - **Fleet settings from `/v1/settings`:** not fetched with `remote_fetch = false` [observed], and untolerated if fetched.
  - **`GROK_CONFIG`, `GROK_CONFIG_PATH` and every other `GROK_*` variable:** forbidden.
  - **A project `.grok/config.toml`:** the discovery set.
  - **macOS device management:** not present on a Linux seat.
- **Staging on the measurement host** is read-only, makes 0 calls, and is done before the grant opens.
  - It mirrors the launch guard's `lstat` semantics: a path counts as absent only on `FileNotFoundError` or `NotADirectoryError`. A dangling symlink, or any other access error, is treated as present and stops the staging.
  - It checks both `/etc/grok` files that way, and records whether `/etc/claude-code/managed-settings.json` exists. That file is allowed on the host; the final check proves it is hidden from the child.
  - The staging check is preliminary, and the code's launch check binds.
- **Falsifier (lane E8-A).** A dangling symlink at either `/etc/grok` path refuses, at staging and at launch. The existing `/etc/grok` rows stay, and the home rows are in 1f.

**5. The client log.**

- **What it holds [observed].** `.grok/logs/unified.jsonl` records `key_prefix`, the token's **last** 12 characters, 4–5 times per launch. stderr does not carry it, and no session file holds it or the identity fields.
- **The collector guarantee.**
  - No harness collector opens `unified.jsonl` or copies `.grok/logs`.
  - `.grok/logs` is never host-backed. The home check refuses any mount at or above `.grok/logs` other than the home tmpfs. The measurement's one sessions bind is the sibling `.grok/sessions`.
- **The redistribution control (the claim covers it).** A seat process can copy log text into a retained channel. `review` has `read_file`, so the model can read the log and echo it, and `staged` has a shell.
  - **Registration (E8-A, one insertion in the grok branch of `seat_profile`, which it owns).** For each copied credential value of at least 24 characters, the profile also registers its last 12 characters in the redactions and `scan_secrets`. That registration does not change the profile's mounts, environment or descriptors.
  - **The retained paths, and what covers each:**
    - **`provider.log`** (the child's stdout and stderr, written raw to a descriptor) is retained on a failed measurement or rehearsal. It is classified secret-bearing already (§5.9): private, mode 0600, with an expiry sidecar, never parsed or published, and deleted on a measured route or a passed rehearsal. A suffix in it does not change its class.
    - **The board's private leg logs, returned text and outputs** are redacted through the seat redactions, which now include the suffix. The `leg_exec.v1` record's scan includes it.
    - **The definitions artifact.** The measurement scans the raw bytes for every registered value, full or suffix, before it retains or extracts them. A hit is refused with a new measurement status, `artifact_refused` (E8-B): nothing is retained and no name is extracted. It is a host-local and evidence route status, not a public detail code.
    - **The writable host-backed sessions bind** is removed by the measurement's `finally` cleanup and by the existing abandoned-scratch purge.
- **Falsifier (lane E8-B), through real composed launches of a stand-in grok.** The stand-in writes a planted credential's 12-character suffix into `$HOME/.grok/logs/unified.jsonl`, and, in variants, copies it to stdout, stderr, a declared output, the definitions artifact and a file under `.grok/sessions`.
  - **A failed rehearsal, so `provider.log` is retained:** the suffix appears in `provider.log` only. A passed rehearsal deletes `provider.log` first, so it alone proves nothing.
  - **A measurement whose definitions carry the copy:** `artifact_refused`, with no raw copy.
  - **A measurement without that copy:** `measured`, and the suffix is absent from the output root, the grant directory, the host-local record root and the evidence.
  - **A board leg:** the suffix is absent from the private leg log, returned text, outputs, board artifacts and the `leg_exec.v1` record.
  - **Cleanup:** ordinary teardown removes the sessions scratch, and the abandoned-scratch purge removes a planted one. The writable board output and scratch trees are scanned too.
  - **A host bind:** a variant binding `.grok/logs` from the host refuses at the context check.

**6. Untested switches (not adopted).** These are documented but untested, so they are **not** added to the seat config. Each is a candidate for a later erratum, and each needs its own approved offline launch: the seat config plus the switch, expecting the named request to vanish.
- `features.feedback = false`, for `GET /v1/feedback/config`.
- `subagents.enabled = false`, for `GET /v1/subagents/bundle`. This rests on the request's name only. The `--no-subagents` flag would change the frozen argv.

No switch was found for `GET /v1/bundle/archive`, `GET /` or the `POST /v1/responses` pair.

**7. The rehearsal (erratum 4; amended for order, cause and runtime).**

For `add4d201…` with the seat config under a budget-0 proxy, the expected observation is below. The rows are in the proxy's decision order; the four GETs may come in any order [observed].

| method | host | path | decision | `cause` | expected count |
|---|---|---|---|---|---|
| `GET` | `cli-chat-proxy.grok.com` | `/v1/bundle/archive` | deny | `rules` | 0 or more (observed 1) |
| `GET` | `cli-chat-proxy.grok.com` | `/` | deny | `rules` | 0 or more (observed 1) |
| `GET` | `cli-chat-proxy.grok.com` | `/v1/subagents/bundle` | deny | `rules` | 0 or more (observed 1) |
| `GET` | `cli-chat-proxy.grok.com` | `/v1/feedback/config` | deny | `rules` | 0 or more (observed 1) |
| `POST` | `cli-chat-proxy.grok.com` | `/v1/responses` | deny | `rules` | 0 or more, all before the first budget denial (observed 2) |
| `POST` | `cli-chat-proxy.grok.com` | `/v1/chat/completions` | deny | `budget` | at least 1 (observed 1) |

- **It passes only when all of these hold:**
  - at least one denial of the exact allowed inference tuple with `cause` `budget`. Retries of it after a budget denial remain valid (erratum 4);
  - zero allowed events;
  - a complete observation with BA-1's proof;
  - every other event is a qualifying tolerated refusal (item 2).
- **Anything else fails it:** `/v1/settings`, `/v1/models`, `<other>`, a diagnostic label, a `CONNECT` (including 1.0.92's updater), a sign-in host, or a late POST. The client's exit status does not matter (expected 1).
- **Which failure is reported.** The reason is decided in this order, and the first that applies wins: an early refusal; `identity_changed`; `observation_incomplete`; `unlisted_request` (any allowed event, or any non-qualifying denial); `no_model_request`; `passed`. So a rehearsal missing its budget denial that also holds an unlisted request reports `unlisted_request`.
- **Runtime binding (E8-B).**
  - The rehearsal record gains `runtime_digest`.
  - `rehearsed()` requires it to equal the running `seat_window.runtime_digest()`, besides the image, the context and the route. A record without the field is stale, never `passed`.
  - Measurement results already carry `runtime_digest`, and aggregation requires one value (`_SHARED`). So the checkout and runtime are frozen from the rehearsal through aggregation, and drift stops the grant.
- **Falsifiers (lane E8-B).**
  - A missing budget denial (`no_model_request`).
  - The correct tuple denied by the wrong check, `inner_host` (`unlisted_request`).
  - A late auxiliary POST.
  - Mixed order.
  - Each disqualifier above.
  - A runtime change after a passed rehearsal makes it stale.
- **Limit.** A request the client makes only after a *successful* model response, such as a title refresh, cannot be seen offline or in a rehearsal. In the pilot it is either a tolerated GET or it disqualifies (`egress_refused`), at the cost of the pilot's one request.

**8. Pins, re-proof, lanes and stop rules.**

These pins move. The values are lane outputs, recorded after the fact as erratum 6 did, never targets here.

| Pin | E8-A | E8-B | E8-C |
|---|---|---|---|
| this contract | this erratum only; the manifest pins no digest of it | — | — |
| `seat_window.runtime_digest()` (every runtime source, all vendors) | moves | moves | moves |
| `context_digest` (§4.4) | moves (`seat_config`, `SEAT_FIXED_INPUTS`, `NON_MUTATING_TOOLS`) | does not move | does not move |
| window containment binding `proxy_sha256` (`seat_jail_qualification._PROXY_IMPLEMENTATION_SHA256`, both proxy files) | — | — | moves, as it did for lane L2a |
| measurement status vocabulary (`STATUSES`) | — | gains `artifact_refused` | — |
| `grok-review` allow-list content digest | does not move | does not move | does not move; a test holds it |
| `tests/data/seat_launch_references.json` | rows only if the projection adds a detected call site | none expected | none expected |
| Claude SDK proof inputs | none expected: `memfd_with` is called, not edited; `seat_profile` is not a proof region; a needed `SDK_PROOF_UNBOUND` insertion moves `claude_seat_transport.py` (whole file), as in erratum 6, and the lane determines whether a retained SDK proof needs refreshing | as E8-A | none expected |
| `tool_probe.v1` receipt schema, the five forms and their argv digests, the public detail codes | do not move | do not move | do not move |

Frozen receipt *content* changes with the new context.

**What each pin move costs, by vendor.** At this base, the only registered window is Gemini's W1 (`seat_profiles.GEMINI_WINDOW_DATA`). Its record carries both `runtime_digest` and the containment binding's `proxy_sha256`.
- **Gemini:** every lane makes its W1 record stale (`runtime_digest`), and E8-C does so a second time (`proxy_sha256`). The W1 window is requalified on the integrated head. That needs its own authority, and it cannot use any grok grant's budget.
- **Grok:** no window is registered. Every measurement record carries `runtime_digest`, so the new grant runs wholly on the integrated head (item 7). Earlier grant records are stale and never reused.
- **Codex:** no W1 registration exists at this base, so there is nothing to requalify. A later Codex W1 binds the head it is qualified on. Jail-qualification passes recorded by `seat_jail_qualification.qualify` are keyed by their own qualification key, which carries neither value [inferred from a code read; E8-C's report confirms it by test].
- **Claude:** jail-qualification passes, as for Codex [inferred; same confirmation]. SDK proof as in the table.
- **The historical reader is not a rollout gate.** The window record reader checks a record's coherence, which does not show that its evidence is current. The coordinator gates on each live record's `runtime_digest` and `proxy_sha256` against the integrated head's.

**Batching recommendation.**
- Land E8-A, E8-B and E8-C consecutively in one window.
- Then requalify Gemini W1 once, then open the next grok grant (item 9), on that same head.
- Any runtime-moving merge between the requalification and the grant's aggregation repeats the requalification and stops the grant.

**Re-proven on the merged head of the three lanes:**
- **hosted BA-3**, executed with no skipped case under `PHASE_LOOP_REQUIRE_GROK_EGRESS_NS=1` and recorded through `--hosted-check` with its run reference. It asserts the projected bytes through the real same-child board path, alongside the direct-denial and fixture-upstream checks, and it includes 1f's stand-in boundary test. BA-3 uses a stand-in;
- **the SDK proof binding tests** (`tests/test_seats_claude_order.py`, `tests/test_gemini_seat_mode_pin.py`), passing unedited. Any `SDK_PROOF_UNBOUND` insertion is recorded in that lane's report;
- **§8's must-not-move guards**, unedited.

**Lanes.** Each lane is code, with no live call. Each adds a CHANGELOG entry naming the pins it moves.
- **E8-A — the seat config, the fixed inputs and the context.**
  - **Code:** `grok_tool_surface.py`'s launch-context region (the constants through `verify_measurement_context`, **except** the tolerated map), the `seat_profile` grok branch in `panel_invoker.py` (projection and suffix registration), and the consumer-audit gate.
  - **Docs:** `docs/review-seats-readiness.md` (the Grok row's home holds a read-only seat config; `staged` is ineligible at use).
  - **Tests:** `tests/test_grok_tool_surface.py`, `tests/test_grok_board_leg_frozen_basis.py`, and two named sections in other lanes' files. In `tests/test_grok_measure_egress.py` it owns `test_the_grok_profile_carries_the_proxy_projection_and_nothing_else` and BA-3's exact-mount expectation. In `tests/test_grok_tool_surface_measure.py` it owns `test_the_sessions_keyword_adds_one_bind_and_nothing_else` and the bench's home-composition assertions. With the old exact-argv assertion, the new mount fails hosted BA-3.
- **E8-B — per-image tolerated refusals, the rehearsal, the runtime binding and the log falsifier.**
  - **Code:** the tolerated map and the measurement region of `grok_tool_surface.py`: `_classify`, `_rehearsal_reason`, `tolerated_summary`, `_check_tolerated`, the `named=` arguments of both proxy starts, the rehearsal record and `rehearsed()`, `STATUSES` and the definitions scan.
  - **Tests:** the rest of `tests/test_grok_tool_surface_measure.py`, plus a new `tests/test_grok_seat_log_retention.py`.
- **E8-C — closed path diagnostics.**
  - **Code:** `seat_egress/proxy.mjs` and `seat_egress_proxy.py`.
  - **Tests:** the rest of `tests/test_grok_measure_egress.py`. It also runs, one at a time, `tests/test_gemini_seat_egress_1170.py` and `tests/test_seat_egress_allowlist_codex.py`, unedited.
- **Order.**
  - **Development:** the three may proceed in parallel against these interfaces: the `tolerated(...)` predicate, the diagnostic table and the suffix registration.
  - **Landing:** E8-A, then E8-B, then E8-C. Each rebases onto the previous, with `CHANGELOG.md` union-resolved: main's text kept verbatim, and the lane's entry added above it.
- **Another plan holds a pin E8-A moves.** GROKROLL (`plans/phase-plan-v1-grokroll-GROKROLL.md`) lists `grok_tool_surface.context_digest()` as must-not-move for its own lanes (EC-GROKROLL-8, judged against its phase base), and its lanes may not edit `grok_tool_surface.py`.
  - Finish GROKROLL SL-0 (agent-harness#2050) before E8-A lands, if practical.
  - Otherwise the coordinator records the agreed comparison base for the remaining GROKROLL lanes. A branch rebase alone does not update that base. GROKROLL's forbidden-file diff and its context guard must still pass.
  - E8-B and E8-C move no pin GROKROLL holds, but they do move the global runtime keys.
- **Stop rules.** Any one of these stops the lane, and it reports:
  - a §8 must-not-move guard moves;
  - the `grok-review` allow-list digest moves;
  - `SDK_PROOF_REGIONS`, `SDK_PROOF_FILES` or `SDK_PROOF_ALIASES` changes, or an SDK proof region moves;
  - an ordinary grok profile composes differently;
  - the design needs a client behaviour that was not observed: a different config, a placeholder mount, or reliance on reload (that needs a new offline approval and an erratum, not a code change);
  - a test would need a live call or a real grok launch;
  - plan amendments start to outnumber implementation.

  Shared-host test limits apply: targeted files, serial, with a timeout. Full runs are left to hosted CI.

**9. The next owner grant** is specified by the jailed contract (`plans/artifacts/grok-jail-tool-surface-contract-v1.md`, `grok_jail_context.v1`), which targets the jailed composition. It is not specified here.

**The untested material claims, and the single offline launch that would confirm each (not run).** Some documented defaults already have corroborating observations, such as `remote_fetch` removing the fetches together with the effort rows. Those are not listed.

- **That `remote_fetch = false`, rather than the effort rows, removes `/v1/settings` and `/v1/models`.** The observation changed both at once. Confirming launch: the seat config without `[features]`, expecting both requests to return. Isolating the two changes is not an implementation prerequisite: the pinned file is exactly what was observed.
- **That a managed `remote_fetch = true` overrides it (item 4).** Confirming launch: the seat config plus `$GROK_HOME/managed_config.toml` setting it true, expecting both requests to return. The guard refuses that home either way, so this is not a prerequisite.
- **That read-only placeholder mounts at the creatable fixed inputs are tolerated (item 1d, `staged`).** Confirming launch: the seat config plus an empty read-only mount at each creatable path of `SEAT_FIXED_INPUTS`, expecting the inference request to be reached. It is a prerequisite only for a later erratum admitting `staged` at use.
- **The two switches of item 6:** one launch each, as stated there.
- **Console sync (item 4):** deliberately given no confirming launch. It is refused whatever its route.

Nothing else in the contract changes.
