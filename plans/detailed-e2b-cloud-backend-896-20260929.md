---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 3c61b270
related_issues: [agent-harness#896, agent-harness#1162, agent-harness#1165, agent-harness#1132, agent-harness#1161, agent-harness#999, agent-harness#1076, agent-harness#848]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_sandbox_e2b.py tests/test_sandbox_e2b_live.py tests/test_advisor_board_config.py tests/test_president_ladder_config.py tests/test_sandbox_placement.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: E2B cloud placement backend, plan 4a1 control plane (agent-harness#896, plan 4)

## Task

This is the first cloud adapter behind the vendor-neutral placement seam of agent-harness#896.

- **Normative seam.** The seam is the Contract section of plan 1a (agent-harness#1162, merged
  `f59ed953`, `plans/detailed-remote-sandbox-placement-896-20260929.md`). This plan cites it
  and does not restate it.
- **Maintainer decisions.** RD3, CD1–CD4 and E1 are as recorded on agent-harness#1162 and
  agent-harness#1165 (issuecomment-5905290928). This plan cites them. The only thing it adds is
  what they commit *this* plan to; see "Maintainer decisions".
- **Packaging.** The SDK is only the optional extra `[e2b]`. Nothing here is fleet-specific.

**Chain.** 1a → {1b, plan 2} → **4a1** → 4a2 → 4b.
- 1b is the execution driver, `_NONLOCAL_EXECUTION_DRIVER = True`, and the lease journal,
  heartbeat and reaper.
- Plan 2 is the configurable egress allowlist.
- Plan 3 (self-hosted) is not on this path.

**Bounded-plan split.** Board round hb1 (four seats) added the key-custody redesign, port and
resolver closure in the guest, the digest pin (E1), cleanup confirmation and the probe
controls. The adapter no longer fits one bounded plan. It is split three ways:
- **4a1 (this document, detailed): the control plane.**
  - lifecycle: create, renew, kill, confirmed release and the reaper binding;
  - key custody;
  - the `[e2b]` configuration and caps.

  It is qualified with a null workload and uploads no tree. It touches four source files
  (`pyproject.toml`, `sandbox_e2b.py`, `advisor_board/config.py`, `cli.py`) and has two
  concerns (lifecycle and custody/config).
- **4a2 (follow-on, specified below): image and guest.** The E1(b) digest-pinned template, the
  guest assets, the snapshot upload, and the in-guest egress and probe rows. That is when
  `commit` becomes complete.
- **4b (follow-on, outlined): a seat runs inside the VM.** It needs agent-harness#1132.

## Research summary

**E2B**, read 2026-09-29/30 from docs.e2b.dev and the `e2b` 2.51.0 wheel. The hb1 grok seat
re-fetched and confirmed every documented claim below.

- **Lifecycle.**
  - `Sandbox.create(template, timeout, metadata, envs, network, lifecycle, …)`, where
    `lifecycle` is `{"on_timeout": "kill"|"pause"}` and kill is the default
    ([auto-resume](https://docs.e2b.dev/sandbox/auto-resume.md)).
  - `set_timeout(t)` counts from now ([sandbox](https://docs.e2b.dev/sandbox.md)).
  - The maximum is 3600 s on Hobby and 86400 s on Pro
    ([sandbox-lifetime](https://docs.e2b.dev/faq/sandbox-lifetime.md)).
  - **Paused sandboxes are retained indefinitely**, with filesystem and memory
    ([persistence](https://docs.e2b.dev/sandbox/persistence)).
  - `Sandbox.list(query=SandboxQuery(metadata=…, state=[…]))` is paginated
    ([list](https://docs.e2b.dev/sandbox/list.md)).
  - `SandboxInfo` has no `build_id`.
- **Keys.** An API key is scoped to exactly one project, with no documented expiry or
  restriction ([projects](https://docs.e2b.dev/projects.md)).
  - The SDK falls back to `E2B_API_KEY` / `E2B_ACCESS_TOKEN` from the environment when no key
    is passed.
  - `E2B_DOMAIN` redirects where the key is sent.
  - `E2B_DEBUG` targets localhost and makes `kill()` a no-op (SDK source; not in the docs).
- **Billing.** Per second while running; creation is rate-limited; there is **no usage API**
  ([billing](https://docs.e2b.dev/billing.md)).
- **Network.** These facts bind 4a2 and are recorded here so that 4a1's configuration carries
  what 4a2 needs:
  - private and link-local ranges are always blocked;
  - `allow_out` beats `deny_out`;
  - domain rules cover ports 80 and 443, by Host header and SNI;
  - a connect can succeed even when denied;
  - `8.8.8.8` is auto-allowed once any domain rule exists
    ([internet-access](https://docs.e2b.dev/network/internet-access),
    [restrict-public-access](https://docs.e2b.dev/network/restrict-public-access)).
- **Templates.** `from_image("<ref>")` takes a Docker reference, and the docs show only tags.
  **Digest references (`repo@sha256:…`) are not documented**
  ([base-image](https://docs.e2b.dev/template/base-image.md), read 2026-09-30). `build_id` is
  an opaque id ([tags](https://docs.e2b.dev/template/tags.md)).

**Repo** at `input_base_commit`:
- **Optional extras.** Precedent: the `visual` extra (`phase-loop-runtime/pyproject.toml:64-73`),
  imported lazily.
- **Config.** `advisor_board/config.py` has closed key sets (`_KNOWN_TOP_KEYS`, line 54;
  `_reject_unknown`, around line 102) and the `_parse_agy` model.
- **Child environments.**
  - `panel_invoker._subscription_env` **preserves `E2B_API_KEY`**; the hb1 codex falsifier
    shows this.
  - The brokered allowlist `_broker_subscription_env` is separate.
  - `harness_env_signatures.child_executor_env` builds executor children.
- **Token storage precedent.** The agent-harness#1132 plan's D2 token file: 0600 under
  `$XDG_STATE_HOME/phase-loop/…`, opened `O_NOFOLLOW` and checked with `fstat`.
- **Tree digest.** `review_stage.review_tree_manifest_sha256` encodes paths as strict UTF-8, so
  a non-UTF-8 name raises `UnicodeEncodeError` (hb1 codex F007, reproduced). This binds 4a2.

## Board round hb1: dispositions

| Finding | Where it is resolved |
|---|---|
| Key scrub unreachable on fallback; key in the runtime env (all four seats) | 4a1 "Key custody", plus ask B1 of 1b |
| Port 80 open for `seat-cli` (codex F002, claude F003) | 4a2 egress row N9 and probes P16–P19 |
| Verified before the operation that produces it (codex F003, claude F005) | "Placement ordering", plus ask B2 of 1b |
| `egress_needs` from the global allowlist (codex F004) | the plan 2 dependency, plus ask A1 of plan 2 |
| Manifest pin missing from the closed schema (codex F005) | the 4a1 `[e2b]` keys |
| Paused accepted as cleanup (codex F006) | 4a1 "Release and cleanup confirmation" |
| Non-UTF-8 digest fixture (codex F007) | the 4a2 snapshot section |
| IPv6 and P13–P15 not built (claude F002) | 4a2 Changes |
| P15 recorded as `runtime_end_to_end` (claude F004) | now `backend_attested` |
| claude non-blocking F006–F021 | folded in where named |
| grok: `filesystem_confined` "always"; restated decisions | probe P20; citations |

## 4a1 design

### Placement ordering (the whole adapter; binds 4a2 and 4b)

1. **Before create, in two places.** Both refuse before any vendor call, with no sandbox
   created.
   - **The driver (1b, vendor-neutral).** It refuses if any of these hold:
     - `required_capabilities ⊄ capabilities()`;
     - `egress_needs` names a private allowlist that `capabilities()` lacks
       `private_allowlist` to serve;
     - the leg deadline exceeds `declaration().max_lifetime_s`.
   - **4a1, inside `commit` before `create`.** It refuses if any of these hold:
     - the key or environment checks fail;
     - the repo opt-out applies;
     - a cap is breached under the ledger lock.

     These refusals carry `e2b_*` codes.
2. **`commit` (4a2 completes it).**
   1. `create`.
   2. The gating probe rows. None of them needs the tree.
   3. If any required capability is not verified, kill with confirmation and refuse
      (`e2b_capability_unverified:<cap>`).
   4. **Only then** upload the tree, extract it and verify its digest.
3. **After `commit` (driver, 1b).** Re-check `required_capabilities ⊆ verified` as a backstop
   **before `execute`**. On a refusal, kill with confirmation.

In 4a1, `commit` is create plus the null workload (`commands.run("true")`) only. **No file of any
kind is uploaded.**

### Control-plane qualification (4a1's only admissible request)

4a1 verifies no confinement capability. Its `capabilities()` returns the **empty set**, and its
`declaration()` returns:
- `egress_residuals = ()`;
- `guest_control_env = {E2B_SANDBOX, E2B_SANDBOX_ID, E2B_TEMPLATE_ID}`;
- `max_lifetime_s = tier_max_lifetime_s`.

**Chosen fix: option (b).** Full qualification moves to 4a2. 4a1 proves only its control plane.
The reasons:
- 4a1 claims no capability it cannot verify;
- B2's required set stays mandatory for every review leg;
- there is still one driver path.

Option (a), a per-phase required set, was not chosen. It would add a phase switch to
vendor-neutral 1b driver code. Option (b) needs only a scope value that one entry point sets.

- **The qualification request** is built only by the B4 entry point
  `qualify_control_plane(...)`. Nothing else can construct one. It carries:
  - `qualification_scope = "control_plane"`;
  - the null workload, with no tree and no snapshot;
  - no `one_shot_secret`;
  - an **empty** `egress_needs`;
  - an **empty** `required_capabilities`.
- **Its sandbox is created with all egress denied**: `deny_out=["0.0.0.0/0"]`, no `allow_out`
  and `allow_public_traffic=False`. It therefore has no egress residual to declare.
- **The runtime records** `qualification_scope = "control_plane"` in the evidence.
  - Such a record never produces a `committed` snapshot receipt.
  - It never sets `sandbox_root_applied`, and it is never counted as a placement.
- **A review leg's request** always carries B2's non-empty required set. Against 4a1's empty
  `capabilities()`, the driver refuses it before create. Cloud placement for review legs
  therefore stays refused until 4a2's probes verify the set. There is also no `e2b` entry point
  until 4b.

### Key custody

A design requirement: **the E2B key is never present in the runtime's own process
environment.** Removing its name from a child's environment does not satisfy this on its own.

- **Where the key lives.** It is read at call time from an owner-only key file:
  - `[e2b] api_key_file`, default `$XDG_STATE_HOME/phase-loop/credentials/e2b`;
  - the file is 0600 and its directory 0700, both owned by the euid;
  - it is opened `O_NOFOLLOW` and checked with `fstat`. A failed check refuses with
    `e2b_key_file_unsafe`.

  This mirrors the agent-harness#1132 D2 token file, the local credential store the CD1 channel
  already uses.
- **How it is used.** The key is passed only as the SDK's `api_key=` argument, together with an
  explicit `domain=` from config. The key is never exported, never put in `os.environ`, and
  never passed to `envs`, `metadata`, a file write, a command line, a log or evidence.
- **Environment refusal.**
  - **Key in the environment.** The backend reads **B1's startup snapshot of the environment**,
    never the live `os.environ`. If either of **E2B's own** secret names (`E2B_API_KEY`,
    `E2B_ACCESS_TOKEN`) is present, it refuses with `e2b_key_in_environment` and never uses the
    value. Another vendor's secret in the snapshot does not refuse E2B.
  - **SDK overrides.** The backend refuses with `e2b_env_override` if **any** `E2B_*` name other
    than the three guest-control names is present. That covers `E2B_DEBUG` (F7), `E2B_DOMAIN`,
    `E2B_API_URL`, `E2B_SANDBOX_URL` and future SDK-steering variables. The names the SDK reads
    are checked against 2.51 at implementation time.
- **Vendor-neutral secret names (ask B1 of 1b).** The runtime reads `[sandbox] runtime_secret_env`
  from the user config **before any backend or plugin is constructed**, on every run and for
  every root.
  - The local child-env builders drop those names: `_subscription_env`,
    `_broker_subscription_env` and `child_executor_env`.
  - That holds on every path: an unset root, a local root, an unregistered or gated scheme, a
    missing extra, a plugin failure, and qualification.
  - The `[e2b]` parser (4a1) refuses a config whose `runtime_secret_env` lacks `E2B_API_KEY` and
    `E2B_ACCESS_TOKEN`. That check is itself config parsing, so it needs no plugin.
  - The user-level `[sandbox]` key closure belongs to **B1**, because 1b lands first. Otherwise a
    `[sandbox]` table would be rejected before 4a1 exists.
- **Presence notice.** When a configured secret name is found in the runtime's environment at
  start, the runtime records a typed notice. The key-file path is the only supported one.
- **Exceptions.**
  - An SDK exception text is scrubbed **with the key's value**, and with the values of the
    per-sandbox envd and traffic tokens, in their base64 and hex forms too. This happens at the
    backend call site, before `_redact_leg_text`, because the hb1 codex seat observed that
    `_redact_leg_text` alone does not remove them.
  - The typed error is re-raised `from None`, so a traceback cannot print the raw `__cause__`.
- **Key lifetime.** The backend keeps no `Sandbox` instance between calls, because one holds the
  key in its connection config. Each operation uses the SDK classmethods, with a fresh key-file
  read.
- **Writing the key file.** `phase-loop sandbox-e2b key set` reads the key with no echo and
  writes the file at 0600. Nothing reaches a transcript or the shell history.
- **Opt-out caveat.** Seats outside the seat jail run as the operator's uid and can read
  owner-only files, including the key file. That covers sandboxing disabled
  (`PHASE_LOOP_SANDBOX_DISABLE=1`) and the codex and grok routes until agent-harness#895. This
  is the accepted D1/D3 posture, and the capabilities card discloses it.
- **Jail binding.** The agent-harness#1132 jail must never bind
  `$XDG_STATE_HOME/phase-loop/credentials`. Its J1 mount set does not, and 4a1 adds a check that
  this stays so.
- **E2B CLI login.** A login through the E2B CLI stores credentials in `~/.e2b/config.json`, which
  is outside this design. The operator docs say that 4a1 needs no CLI login.
- **Evidence.** Nothing derived from the key is recorded: no hash, prefix or length.
  - 4a1's receipt `details` are a closed set: `project_label`, `domain`,
    `qualification_scope` and `e2b_template_ref` (a lookup handle).
  - `_details_for` serializes only these, as strings matching a fixed pattern.
  - 4a2 adds its keys, which were listed in round 1.
- **Live qualification** reads the key file. It never uses `export`.

### Per-principal isolation under one project key

Any holder of a project key can list, connect to and kill every sandbox in that project. The
`agent_harness_owner` metadata is **cooperative**. It scopes this runtime's reaper and is not a
security boundary.
- Isolation between principals exists only with one E2B project and key per principal. The
  operator docs say so, and the capabilities card discloses it.
- The runtime cannot detect a shared key and does not claim to.
- Evidence records `project_label`.

### Lifecycle

- **Create.**
  - `timeout = floor(min(lease_ttl_s, deadline_remaining))`. If that is ≤ 0, the leg is
    refused before create.
  - `lifecycle={"on_timeout": "kill", "auto_resume": False}`.
  - `envs={}`.
  - `network` always carries `allow_public_traffic=False`: a creation invariant, with the full
    rule set in 4a2.
  - `metadata` = `agent_harness_owner`, `round`, `leg`, `lease`, `runtime_version`.
  - 1b's journal entry is written and fsynced **before** create (the 1b rule).
- **No pause, ever.** No `on_timeout: "pause"`, `auto_resume`, `beta_pause`, resume-by-connect
  or `update_network`. `update_network` replaces the whole rule set, so a falsifier asserts it
  is never called.
- **Renew.** `renew(until)` sets `set_timeout(floor(min(lease_ttl_s, until - now)))` only while
  that value is **> 0**. `until` is the leg deadline, supplied by 1b's heartbeat.
  - Each extension is capped at one `lease_ttl_s`, so a dead owner's sandbox expires within one
    TTL of its last heartbeat, never at the leg deadline.
  - At ≤ 0 it kills with confirmation and never calls `set_timeout(0)`.
- **Lost create response.** If `create` raises or times out after the request was sent, `commit`
  lists by the `lease` metadata, kills every match with confirmation, and then re-raises.
- **Release and cleanup confirmation.**
  - `release` and `kill` call `kill()`. Deletion is confirmed when `get_info` returns not-found,
    **or** when the lease is no longer listed in **any** state.
  - **A paused or any other retained state is not cleanup.** It stays pending: 1b's journal
    entry is kept, and the reaper retries.
  - `kill() == False` (not found) counts as confirmed only when the follow-up confirmation agrees.
- **Reaper binding.**
  - 1b owns startup and periodic reaping. 4a1 supplies `list_owned`, which queries
    `SandboxQuery(metadata={"agent_harness_owner": id})` across **every page** and **every
    state**, and `kill`.
  - `available()` makes **no** network call and does not reap.
  - Liveness is 1b's `flock`, including a lease held by a concurrent leg in the **same**
    process. 1b locks an entry before it becomes visible, and deletes it only while holding the
    lock.
- **Caps (CD3).**
  - `max_concurrent_per_run`, `max_seconds_per_run` and `max_seconds_per_day` are checked
    before create. The count and the reservation are taken **under the ledger lock**.
  - Settlement is `max(end_at - started_at, local create-to-confirmed-kill)`.
  - The day ceiling is per local state dir. The operator docs name E2B's console spending limit
    as the backstop, because there is no usage API.

### `[e2b]` configuration (closed key set)

**Required:**

| Key | Meaning |
|---|---|
| `qualify_template` | the vendor template used for the control-plane qualification. It is a lookup handle for a shell-only image, the vendor's stock base template being enough, and it claims no confinement. |
| `domain` | the SDK domain, passed explicitly |
| `project_label` | evidence only |
| `tier_max_lifetime_s` | 3600 or 86400 |
| `lease_ttl_s` | at most the tier maximum, and at least 3 heartbeat intervals |
| `max_concurrent_per_run`, `max_seconds_per_run`, `max_seconds_per_day` | the CD3 caps |
| `eligible_legs` | a subset of `{"claude", "gemini"}` |

**Optional:** `api_key_file`.

**Added in 4a2, not accepted in 4a1:** `template` (`"<name>:<build_id>"`, a lookup handle only,
per E1), `template_manifest_sha256` (codex F005), `template_inputs_sha256` and
`max_snapshot_bytes`. Introducing them with their producer means operators never type
placeholder digests.

**Other rules:**
- **The secret-name set.** The user file's `[sandbox] runtime_secret_env` must include
  `E2B_API_KEY` and `E2B_ACCESS_TOKEN` whenever `[e2b]` is present.
- **The repo opt-out (CD2).** The repo file's `[sandbox] cloud = false` is honoured if it is
  present in **either** the base ref's blob **or** the reviewed tree.
  - An unreadable base blob refuses as a distinct case (`e2b_repo_opt_out_unreadable`): a
    missing or shallow ref, a git error, or malformed TOML.
  - The base ref comes from the request (ask B3), and is runtime-attested.

### Refusal codes

Codes go only in `PlacementUnavailable` reasons and in evidence. **No `_HARNESS_DETAIL_CODES`
member is added.** The set is closed:

| Area | Codes |
|---|---|
| Extra and configuration | `e2b_extra_missing`, `e2b_not_configured` |
| Key custody | `e2b_key_file_unsafe`, `e2b_key_in_environment`, `e2b_env_override` |
| Enablement | `e2b_repo_opted_out`, `e2b_repo_opt_out_unreadable`, `e2b_leg_ineligible` |
| Caps | `e2b_cap_concurrency`, `e2b_cap_run_seconds`, `e2b_cap_day_seconds` |
| Lifecycle and contract | `e2b_lease_exceeds_tier`, `e2b_capability_unverified:<cap>`, `e2b_sandbox_ref_invalid`, `e2b_cleanup_unconfirmed` |

4a2 adds its own snapshot, template and probe codes, including `e2b_template_unpinned`. The
driver's pre-create refusals carry 1b's vendor-neutral codes.

### Asks of plan 1b and plan 2

**Of plan 1b.** 4a1 stops at these; it does not work around them.
- **B1 A vendor-neutral secret-name set.**
  - `[sandbox] runtime_secret_env` is read before any backend is constructed.
  - All three local child-env builders drop the names on every run, and the runtime records the
    presence notice.
  - B1 also owns the user-level `[sandbox]` key closure and a **startup snapshot** of the
    environment, which the E2B refusal reads.
  - B1 owns a vendor-neutral **spawn-site sweep test**: every spawn path uses one of the scrubbed
    builders, and none inherits `os.environ`. 4a1's six-variant test is the E2B integration check
    on top of it.
  - This replaces the earlier `declaration().runtime_secret_env` ask, which failed on exactly
    the fallback paths.
- **B2 A required-capability set, and two checks.**
  - For a review leg, the driver derives `PlacementRequest.required_capabilities` from the
    request:
    - `inbound_closed`;
    - `private_ranges_unreachable`, or `private_allowlist` when `egress_needs` carries a
      private allowlist (a vendor-neutral rule, not one shaped around one backend);
    - `one_shot_secret_channel` when `one_shot_secret` is set.
  - Only B4's control-plane entry point may build a request with an empty required set, and
    only with `qualification_scope = "control_plane"`.
  - The driver runs the pre-create compatibility check and the post-`commit`, pre-`execute`
    `verified` check.
  - The set is passed to `commit`.
- **B3 `PlacementRequest.base_ref`.** It is runtime-attested, and used for the opt-out.

B2 and B3 amend 1a's `PlacementRequest` and the inputs to `commit`, so 1b lands them as explicit
CONTRACTS.md amendments.
- **B4 Driver functions the operator commands can call.** This includes
  `qualify_control_plane(...)`, the only builder of a `qualification_scope = "control_plane"`
  request. It runs through the same driver as every leg: journal, heartbeat, renewal, cleanup
  and reaper. It emits no snapshot `committed` receipt, and its records never count as applied.
  There is no parallel path.

**Of plan 2.**
- **A1 A per-location egress allowlist.** `egress_needs` is derived from the allowlist configured
  for the **selected location**, with an empty default.
  - Without it, the global inference allowlist makes every cloud request carry a private
    allowlist, and E2B must refuse it.
  - A cloud leg's egress is never broader than its `egress_needs`, and a private need is refused,
    never dropped.

The earlier `sni_destination_unchecked` ask is **withdrawn**. 4a2's in-guest IP pin closes that
residual in the guest.

## Changes (plan 4a1)

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project.optional-dependencies]` — add `e2b = ["e2b>=2.51,<3"]`, commented like `visual`:
  imported lazily, never a core dependency.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_e2b.py` (create)
- `E2BConfig` / `load_e2b_config()` — add — the validated `[e2b]` table.
- `_read_key_file(path)` — add — the owner-only, `O_NOFOLLOW` + `fstat` read at call time. The
  backend keeps no `Sandbox` instance between calls, and each operation re-reads the file.
- `_check_environment()` — add — the `e2b_key_in_environment` and `e2b_env_override` refusals.
- `E2BBackend.runtime_secret_env_names()` — add — a classmethod returning the module-level
  constant `{"E2B_API_KEY", "E2B_ACCESS_TOKEN"}`. It works without the SDK, which it never
  imports, and the `[e2b]` parser uses it for its secret-name check. It is a convenience only:
  the runtime's scrub reads config (B1), never this method.
- `E2BBackend` — add — 1a's `ExecutingBackend`.
  - Implemented: `available` (local checks only), `commit` (create plus the null workload in
    4a1), `release`, `renew`, `list_owned`, `kill`, `cancel`, `capabilities`, `declaration`.
  - `execute` and `wait` run the null workload only.
  - Never implemented: `prepare`.
  - `import e2b` happens only in `__init__`, and an `ImportError` becomes `e2b_extra_missing`.
- `_confirm_deleted(sandbox_ref)` — add — not-found in `get_info`, **or** absent from every state
  in `list_owned`. Paused never counts.
- `_validate_sandbox_ref` — add — 1a's charset. A mismatch is killed and refused.
- `CostLedger` — add — the locked per-run and per-day reservations and settlements.
- `_scrub_exception(exc, secrets)` — add — value-aware redaction of the key and the per-sandbox
  tokens, re-raised `from None`.
- `_details_for(receipt)` — add — the closed 4a1 `details` set.
- **No entry point in 4a1.** 4b adds the `e2b` entry point.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py` (modify)
- `_KNOWN_TOP_KEYS` — modify — add `"e2b"`. The user-level `"sandbox"` table and its closure come
  from 1b (B1).
- `_KNOWN_E2B_KEYS` / `_parse_e2b` / `load_e2b_section` — add — the table above, including
  the secret-name set check.
- `_KNOWN_REPO_TOP_KEYS` — modify — add `"sandbox"` (`{"cloud"}`).
- `repo_cloud_opt_out(repo_dir, base_ref)` — add — the union rule, with an unreadable base as a
  distinct result.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `sandbox-e2b` subparser — add — following the `add_parser` pattern around lines 424–451.
  - `qualify-control-plane` calls B4's `qualify_control_plane` to create, run `true`, renew,
    kill, confirm and check the reap. It uploads nothing and reads no repository path.
  - `key set` reads the key with no echo and writes the key file at 0600.
  - `reap` runs the reaper by hand through 1b.

### `phase-loop-runtime/tests/test_sandbox_e2b.py`, `tests/test_sandbox_e2b_live.py` (create); `tests/test_advisor_board_config.py` (modify)
- The falsifiers under "Verification".

## Documentation impact
- `docs/phase-loop/convergence-runtime.md` — modify — covers:
  - the `e2b://` location and the `[e2b]` keys;
  - the key file, and that environment variables are refused;
  - `[sandbox] runtime_secret_env`;
  - the refusal codes and the cap semantics;
  - one project per principal;
  - the console spending-limit backstop.
- `docs/advisor-board-capabilities-card.md` — modify — covers:
  - project-level key scope and cooperative owner metadata;
  - vendor retention after kill (logs), and the pause retention a key holder could trigger;
  - the opt-out caveat for seats outside the seat jail.
- `docs/phase-loop/convergence-runtime.md` — also — until 4b, **board legs never reach E2B**.
  There is no entry point, and 4a1's empty `capabilities()` refuses review legs, so an `e2b://`
  root falls back to local, or fails closed. 4a1 qualification is control-plane only.
- `phase-loop-runtime/README.md` — modify — `pip install 'phase-loop-runtime[e2b]'`, and the key
  file.
- `CHANGELOG.md` — modify — the extra and the operator commands. A new `.py` module drifts the
  agy pin set, so the next release cut requalifies agy.

## Dependencies & order
1. **Plan 1a's implementation PR**: the seam types, the registry, `prepare_local_stage` and the
   gate.
2. **Plan 1b**: the driver, the gate flip, the journal, heartbeat and reaper, and **asks
   B1–B4**.
3. **Plan 2**, with **ask A1**. Plan 2 is also a precondition of 4b: a real cloud leg must be
   able to carry an empty `egress_needs`.
4. **Within 4a1:**
   1. config and secret-name closure;
   2. key custody;
   3. ledger and caps;
   4. lifecycle and confirmation;
   5. CLI;
   6. the live test.

   Tests are written first and fail on the missing symbols (the RED receipt), and they land with
   the implementation.
5. 4a1 depends neither on agent-harness#1132 nor on 4a2.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_sandbox_e2b.py tests/test_sandbox_e2b_live.py tests/test_advisor_board_config.py \
  tests/test_president_ladder_config.py tests/test_sandbox_placement.py
python -c "import phase_loop_runtime.sandbox_e2b"   # without the extra: must succeed
```

The falsifiers below run against a fake `e2b` module with a virtual clock. Each is control-green,
and red under its named mutation.

**Key custody**, in `test_e2b_key_never_in_runtime_env` and `test_e2b_key_never_leaves_runtime`:
- **Environment refusal.** The key comes only from the file. With `E2B_API_KEY` in the
  environment, the backend refuses with `e2b_key_in_environment`, and the SDK constructor is never
  called.
- **Scan.** The key's sentinel value and its encodings appear in none of these:
  - the SDK call record's `envs`, `metadata` and command lines;
  - `caplog`, or the evidence;
  - a forced SDK exception whose text embeds the key;
  - `os.environ` after a full qualify run.

Mutations: read the key from the environment; `os.environ[...] = key`; pass `logger=`; redact
without the key's value.

**The secret names hold on every fallback path.** Run with `[sandbox] runtime_secret_env`
configured and a sentinel exported, over six variants: an unset root, a local root, `e2b://` with
the extra missing, `e2b://` with a failing plugin, `e2b://` gated off in 1a, and `qualify`. In each,
`_subscription_env()`, `_broker_subscription_env()` and `child_executor_env()` contain none of the
names. This is the hb1 codex falsifier, generalised. Mutation: read the names from the backend
`declaration()`.

**`[e2b]` requires the secret names.** A config that lacks them is a parse error before any
backend import. With `sys.modules["e2b"] = None`, `E2BBackend.runtime_secret_env_names()` still
contains `E2B_API_KEY` (hb1 sonnet falsifier). Mutation: skip the check, or import the SDK in the
classmethod.

**SDK steering.**
- With `E2B_DEBUG=1`, `E2B_DOMAIN`, or any other non-guest `E2B_*` name, the backend refuses with
  `e2b_env_override` and the create counter reads 0.
- A foreign vendor's secret in the startup snapshot does not refuse E2B.
- The refusal reads the snapshot: clearing `os.environ` after startup still refuses.

Mutations: a name list instead of the prefix rule; read the live `os.environ`.

**No paid sandbox outlives its lease** (`test_sigkilled_owner_sandbox_dies_within_lease`).
- Setup: `lease_ttl_s=120` and a leg deadline 3600 s away. The owner heartbeats once, then stops
  without `release`, which simulates SIGKILL.
- Assertions:
  - after the heartbeat, the remote timeout set is ≤ `lease_ttl_s`;
  - after `lease_ttl_s + 1` virtual seconds, a listing across every state is empty.
- Mutations:
  - `timeout=86400`;
  - `on_timeout="pause"`;
  - a heartbeat of `2 * lease_ttl_s`;
  - **renew passes `until - now` through uncapped**, which gives 3560 s and turns it red.

**Paused is not cleanup.**
- The fake `kill()` leaves the sandbox paused.
- `release` must report it pending and keep the journal entry, and the next reaper pass must
  kill it with confirmation.

Mutation: accept a non-running state.

**Lost create response.** The fake SDK creates the sandbox and then raises. `commit` lists by lease,
kills and confirms, then re-raises. Mutation: re-raise without listing.

**Renew at the edge.**
- With `until - now > lease_ttl_s`, the timeout set is exactly `lease_ttl_s`.
- With the remaining time at 0 or negative, `renew` kills with confirmation and never calls
  `set_timeout(0)`.
- A create whose computed timeout is ≤ 0 is refused before create.

Mutations: drop the `min`; clamp to 0.

**Reaper scope.** The fake SDK returns three pages of sandboxes:
- a paused dead lease;
- a live lease held by a second process;
- a live lease held by a concurrent leg in the same process;
- another owner's sandbox.

Only the dead lease is killed. Mutations: first page only; running state only; no owner filter;
pid liveness; no same-process lock.

**No `update_network`.** The call record never contains `update_network`, and every `create` carries
`allow_public_traffic=False`. Mutations: omit it on the `qualify` path; call `update_network`.

**Caps under lock.** Two concurrent legs against `max_concurrent_per_run=1` result in exactly one
create. Mutation: count outside the lock.

**Opt-out.**
- An opt-out present only in the base ref refuses the leg.
- An unreadable base ref refuses with `e2b_repo_opt_out_unreadable`.

Mutations: read only the working tree; treat unreadable as absent.

**Control-plane qualification is scoped, not a bypass.**
- `qualify_control_plane` uploads nothing, reads no repository path, creates with all egress
  denied, and runs through the driver. Its journal entry, heartbeat and confirmed kill are
  observed.
- Its record carries `qualification_scope = "control_plane"`, no snapshot `committed` receipt,
  and `sandbox_root_applied` false.
- A **board-shaped** review request against the 4a1 backend is refused by the driver before create
  (`required_capabilities ⊄ capabilities()`), with the create counter at 0.
- Only the B4 entry point can build an empty-required-set request.
- The `phase_loop_runtime.placement_backends` metadata has no `e2b` entry (restored).

Mutations: let a review request carry an empty required set; count a control-plane record as
applied; declare the entry point; pass the cwd.

**Evidence `details`.** Only the four 4a1 keys are serialized. Mutation: pass arbitrary backend
keys through.

**Jail binding.** The agent-harness#1132 J1 mount set contains no path under
`$XDG_STATE_HOME/phase-loop/credentials`. This is skipped until the jail module exists. Mutation:
add the bind.

**Contract binding.**
- There is no `prepare`.
- `available()` makes no socket call.
- A bad `sandbox_ref` is killed and refused.
- A backend `runtime_end_to_end` is recorded as `backend_attested` (1a's coercion).
- `import phase_loop_runtime` never imports `e2b`.

**Live qualification** (`test_sandbox_e2b_live.py`). It skips with the first applicable reason:
- `"E2B live qualification skipped: the e2b extra is not installed"`;
- `"E2B live qualification skipped: no E2B key file"`;
- `"E2B live qualification skipped: PHASE_LOOP_E2B_LIVE != 1"`;
- `"E2B live qualification skipped: no [e2b] section in the user config"`.

When it runs, it drives `qualify-control-plane` against the operator's project. That is a
control-plane record only; full qualification moves to 4a2. It records:
- create, renew, kill and confirmation;
- a SIGKILLed child, followed by zero leftover sandboxes after `lease_ttl_s` (120 s) plus 60 s;
- the billed seconds;
- the key sentinel scan of the record.

The maintainer supplies the key **file**, never an exported variable. CI never has it, so CI always
skips. The record is attached to the 4a1 PR as operational evidence.

Run on a tree left untouched for the duration.

## Acceptance criteria
- [ ] `test_e2b_key_never_in_runtime_env` passes on all six fallback variants (the sixth is
  control-plane qualification), and each named mutation turns it red. `os.environ` never contains the key after a qualify
  run.
- [ ] `test_sigkilled_owner_sandbox_dies_within_lease` (including the uncapped-renew mutation),
  the renew-edge test and the paused-is-not-cleanup falsifier pass. Each named mutation turns
  one of them red.
- [ ] The reaper-scope falsifier kills exactly the dead-lease sandbox across three pages. The
  same-process live lease and another owner's sandbox survive.
- [ ] With the fake SDK, the following each give their code with the create counter at 0:
  - each cap breach;
  - `E2B_DEBUG=1`;
  - a key in the environment;
  - a board-shaped review request, refused by the driver;
  - a base-only opt-out, and an unreadable base.

  With `e2b` absent, `import phase_loop_runtime.sandbox_e2b` succeeds and construction raises
  `e2b_extra_missing`.
- [ ] `test_sandbox_e2b_live.py` skips with exactly
  `"E2B live qualification skipped: no E2B key file"` when the key file is absent. The
  maintainer's live **control-plane** record is attached, carries
  `qualification_scope = "control_plane"`, and shows zero leftover sandboxes after the SIGKILL
  case.

## Follow-on: plan 4a2, image and guest (specified; its own bounded plan)

**Scope.**
- The E1(b) template.
- The guest assets: `probe.py`, `extract_tree.py`, `nft.rules` and `template_digest.py`.
- The snapshot upload.
- The full `commit` order.
- The in-guest egress rules and probe rows.
- `sandbox-e2b template build` and `qualify`.

**Files:** `sandbox_e2b_template.py`, `e2b_guest/*`, `sandbox_e2b.py` (`commit`), `cli.py`, and the
`pyproject.toml` package data.

**Dependencies:** 4a1.

### E1(b): pin the inputs by digest (maintainer decision, recorded)
- **The input lock.** `template_inputs.lock` is packaged. It records:
  - the base image **by OCI digest**;
  - every toolchain artifact by sha256, with Debian packages via `snapshot.debian.org` at a
    pinned timestamp and version, or as verified `.deb` hashes; install-by-name is not
    "fetched by hash";
  - the `claude` release artifact;
  - `agy` from the verified qualified artifact in
    `plans/evidence/qualified-provider-images.json`;
  - the sha256 of the build script and of every guest asset.
- **The pin.** `template_inputs_sha256` is the lock's digest. It is **runtime-specified input**,
  not verified content.
- **Rebuilds.** `template build` rebuilds only from the lock.
- **`name:build_id`** is a lookup handle, and never evidence.
- **Residual, stated.** E2B is trusted to build faithfully from the pinned inputs. The in-VM
  manifest re-hashes every toolchain binary at launch, and that is recorded as
  `backend_attested`.
- **If the builder rejects a digest-pinned base image.** Digest references are not documented.
  - 4a2's **first** task is a qualification build with `from_image("<repo>@sha256:<d>")`, whose
    result is recorded.
  - If it is rejected, 4a2 **stops**. Cloud placement stays refused, with
    `e2b_template_input_unpinnable`, and E1 goes back to the maintainer with the recorded
    result.
  - It **never** falls back to option (a) silently.
  - **Rejection is not the only trigger.** A builder might accept `repo@sha256:…` without
    honouring it, so every build, and every rebuild, also runs two checks:
    - **a negative control:** a well-formed but non-existent digest must fail the build;
    - **a positive check:** a fingerprint of the pinned base, taken in the VM, must equal the one
      computed locally from the image.

    If either check fails, 4a2 stops the same way.
- **Tying a placement to the lock.**
  - The template manifest carries the lock digest.
  - At launch, three digests must agree:
    - the one reported in the VM (`backend_attested`);
    - the configured `template_inputs_sha256`;
    - the installed runtime's packaged lock digest.

    Any disagreement refuses with `e2b_template_stale`.
  - `template build` writes a runtime-owned record: "sent lock L, received `build_id` B". That
    record is the only link the runtime itself observes.
  - The expected binary hashes derive from the lock, never from the build's own output.
- **4a2 configuration keys.** `template`, `template_manifest_sha256`, `template_inputs_sha256`
  and `max_snapshot_bytes` are introduced here, together with their producer, the `template
  build` command.

### Snapshot
- **The archive.** A deterministic tar is built from the revalidated local stage. The digest is
  computed **over the tar members actually uploaded**, and must equal `staged_tree_sha256`.
- **Upload.** One streamed `files.write`, **after** the gating probe rows. `git.clone` is never
  used.
- **Extraction** runs as `seat-tool`, with modes masked to the exec bit. The extractor refuses:
  - absolute paths and `..`;
  - hard links and devices;
  - a path that crosses an extracted symlink.
- **Non-UTF-8 names.** The reference digest raises on them (hb1 F007), so the stage cannot hold
  them today.
  - The drift fixture uses an exec bit and a symlink only.
  - A consistency test asserts that the reference digest and the guest copy **both refuse** a
    non-UTF-8 name, with the same typed error (`e2b_snapshot_unsupported_name`).
  - The operator docs list the limitation.
- **Guest assets** run as root-owned 0755 files, with `python3 -I` and cwd `/`. The start hook
  re-applies the root lock and the sudo removal.

### Egress and inbound (rows N1–N13; the in-guest rules live in `nft.rules`)

**`seat-cli`** has one allow rule in an `inet` table:
- output allowed: **tcp/443 to the `/etc/hosts`-pinned vendor addresses only**, plus loopback to
  the non-root listener set;
- everything else dropped: port 80, other IPs, ICMP, UDP, IPv6 except the pinned addresses, and
  the resolver IPs.

**`seat-tool`** has no non-loopback output.

**Loopback.** Every root-owned tcp and udp listener, IPv4 and IPv6, is enumerated at probe time
and dropped for both seat uids by nftables. Root-owned **unix sockets** are closed by file
permissions and mount layout instead, because nftables cannot filter them. P21 checks both.

| # | Requirement | E2B | In-guest | Probe |
|---|---|---|---|---|
| N1 | Vendor hosts on tcp/443 | domain rule | `seat-cli` accept rule | P7, with positive control |
| N2 | All else denied | `deny_out` 0/0 | default drop | P8 |
| N3 | Private and link-local ranges | always blocked | — | P9 |
| N4 | No DNS from seat uids | cannot: 8.8.8.8 is auto-allowed | drop 53 | P10, with a root-resolves control |
| N5 | No UDP or QUIC | cannot | drop UDP | P10 |
| N6 | Root listeners, envd included | secured envd only | drop the enumerated set | P6 (root reaches envd as control) and P21 |
| N7 | `seat-tool` has no network | cannot per uid | drop | P11 (`seat-cli` reaches the same host as control) |
| N8 | TLS confidentiality versus the vendor proxy | cannot | — | disclosed (CD2) |
| N9 | Port 80 closed | domain rules admit 80 | `seat-cli` tcp/443 only | P16, P17 (Host spoof on 80) |
| N10 | SNI bound to vendor IPs | not documented | IP pin | P13 |
| N11 | No IPv6 bypass | not documented | `inet` drop | P14, recording which rule counter fired |
| N12 | No unauthenticated inbound | `allow_public_traffic=False` | — | P15 |
| N13 | No DoH to resolver IPs, no ICMP | cannot | default drop | P18, P19 |

- **Probe controls.** Every negative row has a positive control in the same run. A failed control
  fails the row.
- **Missing rows.** A **missing** gating row refuses, exactly as a false one does.
- **P15.** It starts a guest listener. The request **with** the traffic token must echo a nonce,
  and the request **without** it must be refused. It runs in backend `commit`, so it is
  recorded as `backend_attested`.
- **P20** checks the mount table: no host-shared filesystem (virtiofs or 9p) and no writable
  system path. `filesystem_confined` enters `verified`, as `backend_attested`, only when P20 and
  the manifest check pass. It is never marked "always".
- **P4, P5 and P12** are measured and disclosed only. P5 never puts `seccomp_filtered` into
  `verified`.
- **Gating rows:** P1–P3, P6–P11 and P13–P21.
- **Residuals disclosed:**
  - a pinned vendor IP may also serve other hostnames on shared infrastructure;
  - vendor-side retention after kill;
  - whether the guest's loopback-bound ports are reachable through the vendor edge by a token
    holder. That is measured by a P15 variant and disclosed.

**Capabilities after 4a2** (1a vocabulary; every entry must be verified per placement):

| Capability | Recorded as | Condition |
|---|---|---|
| `private_ranges_unreachable` | `backend_attested` | P9 passed |
| `inbound_closed` | `backend_attested` (P15 runs in backend `commit`) | P15 passed, including the token echo |
| `filesystem_confined` | `backend_attested` | P20 and the manifest check passed |
| `seccomp_filtered` | never from P5 alone | 4b decides |
| `public_egress`, `private_allowlist`, `operator_custody`, `bounding_set_empty`, `resource_bounded` | never | — |

`declaration()` carries three things:
- `egress_residuals`: `resolver_allowed` and `udp_unfiltered_by_name`, both with
  `closed_in_guest=True`;
- `guest_control_env`: `{E2B_SANDBOX, E2B_SANDBOX_ID, E2B_TEMPLATE_ID}`;
- `max_lifetime_s`: `tier_max_lifetime_s`.

**4a2 changes, outlined:**
- `probe.py` — add — in `e2b_guest/`: rows P1–P21, each negative row with a positive control. P13, P14 and P15 are included, and a missing row counts as failed.
- `nft.rules` — add — in `e2b_guest/`: the `inet` rules for rows N1–N13. These were rows E1–E12 before hb1 renamed them. That includes the IPv6 drop, formerly E11, and N13 is new.
- `extract_tree.py` — add — in `e2b_guest/`: the refusing extractor and the digest copy.
- `template_digest.py` — add — in `e2b_guest/`: the manifest writer, which re-hashes every toolchain binary.
- `sandbox_e2b_template.py` — add — the build from `template_inputs.lock`.
- `sandbox_e2b.py` `commit` — modify — the order: create, then the gating probes, then kill-and-refuse or upload.

**4a2 acceptance, outlined.**
- The probe falsifiers above.
- The template-input qualification record, including the negative-control and fingerprint checks.
- The three-digest launch check.
- The drift test.
- **The full live qualification, moved here from 4a1.** It runs through the same driver with a
  review-shaped request whose required set is non-empty. Every gating row must pass and every
  required capability must be verified before any upload. This is the first record that may be
  counted as a placement.

## Follow-on: plan 4b, a seat runs inside the VM (outlined; its own bounded plan)

**Preconditions:**
- 4a2 has landed.
- agent-harness#1132 has landed: the J3 token pipe, D2 and D7.
- Plan 1b's driver has landed.
- Plan 2 has landed, with A1.

4b adds the `e2b` entry point.

**The CD1 in-VM layout.** This is what E2B allows, measured by the probe rows:
1. **Processes.**
   - root runs only envd and the packaged launcher. The launcher is started with
     `commands.run(..., user="root", stdin=True, timeout=0)`.
   - `seat-cli` runs the provider CLI.
   - `seat-tool` runs every command the CLI's tools execute.
   - Neither seat uid has a root path (P2).
2. **The one-shot credential.**
   - The local runtime writes the credential to the launcher's stdin (`send_stdin`, then
     `close_stdin`). It is never on disk and never in an environment.
   - **Claude (D2):** the launcher creates a pipe and passes its read end to `claude` as the only
     extra fd, named by `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`.
   - **Gemini (D7):** the launcher writes an access-token-only copy into a tmpfs directory owned
     by `seat-cli`, mode 0500 for the directory and 0400 for the file.
   - The credential never goes through `envs`, which E2B documents as not private in the OS.
3. **Tools under a separate uid.**
   - A packaged `tool-shell` wrapper passes argv and fds (`SCM_RIGHTS`) to the root launcher.
   - The launcher runs the command as `seat-tool` with a cleared environment in `/seat/tree`.
   - `hidepid=2` is set (P3).
   - Whether each CLI honours the shell override is 4b probe Q1/Q2. If it does not, the leg is
     refused with `e2b_tool_uid_unavailable`.
4. **Egress.** Rows N1–N13.
5. **Output.** The runtime ingests the output under the J10-equivalent checks and the token scan
   before anything becomes evidence.

**Residuals, disclosed:**
- **R1.** The agent-harness#1132 D3 residual applies unchanged, limited to the pinned vendor
  endpoints.
- **R2.** The vendor sees the tree and the credential in transit (N8). This is accepted under
  CD2.
- **R3.** The key is project-wide.
- **R4.** The measured gaps (P4, P5, P12) are published. A leg that needs one of them is refused.

**Other 4b items.**
- **Codex and grok** stay refused (`e2b_leg_ineligible`) until agent-harness#895.
- **Header injection** is at most a probed alternative, because CD1 settles the channel.
- **4b acceptance** includes 1a's non-local `sandbox_root_applied` rule.

## Maintainer decisions

The records on agent-harness#1162 (RD3, CD1–CD4) and agent-harness#1165 (E1:
issuecomment-5905290928) are cited, not restated. This plan's own commitments under them are:
- **CD2's per-repo opt-out** is implemented in 4a1.
- **CD1's one-shot channel** is realised in 4b, as described above. That settles the earlier M2:
  header injection is at most a probed alternative.
- **E1 (b)** is realised in 4a2. If the digest reference is rejected, 4a2 stops and E1 returns to
  the maintainer; the plan never falls back to (a).

Conventional defaults, stated and not asked:
- 4a1 ships no default cap numbers.
- The Gemini D7 copy in the VM is a tmpfs file.

No decision is open.

## Execution Policy

- execute: effort=high, reason=paid-resource lifecycle and credential custody on a new
  network-facing vendor integration
