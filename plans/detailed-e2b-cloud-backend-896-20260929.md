---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 3c61b270
related_issues: [agent-harness#896, agent-harness#1162, agent-harness#1132, agent-harness#1161, agent-harness#999, agent-harness#1076, agent-harness#848]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_sandbox_e2b.py tests/test_sandbox_e2b_live.py tests/test_advisor_board_config.py tests/test_president_ladder_config.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: E2B cloud placement backend for board review seats (agent-harness#896, plan 4 of 4)

## Task

This is follow-on plan 4 of agent-harness#896: the first cloud adapter behind the vendor-neutral
placement seam.

- **The seam.** Plan 1 defines it. It is agent-harness#1162, head `f4b27401`, file
  `plans/detailed-remote-sandbox-placement-896-20260929.md` on branch
  `claude/896-remote-sandbox-plan`. This plan implements against that file and does not copy it.
- **The maintainer decisions.** They were recorded 2026-09-29 on agent-harness#1162 and are
  binding here:
  - RD3: board review seats only; no executors.
  - CD1: a seat login reaches the VM exactly as it reaches the local jail. It travels one-shot
    per leg. Egress is locked to that seat vendor's API. Short-lived or scoped tokens are used
    where the vendor supports them. The threat is the reviewed code running in the same VM.
  - CD2: vendor visibility is acceptable for every repository, and a per-repo opt-out exists.
    The in-VM uid boundary and the codex `CAP_SETFCAP` and seccomp gaps are measured and
    disclosed, never assumed.
  - CD3: per-run concurrency and sandbox-seconds caps, plus a per-day ceiling. A breach is
    refused before create, with a typed reason.
  - CD4: off by default. Cloud is enabled per run, with a per-seat allowlist of eligible legs.
- **Packaging.** The SDK is only the optional extra `[e2b]`, and nothing in the design is
  fleet-specific.

**Bounded-plan threshold: this plan must be split.** The whole adapter touches about 12 source
files and has five distinct concerns:
1. the substrate: lifecycle, leases and caps;
2. template pinning;
3. snapshot transfer;
4. the egress and in-guest firewall;
5. the seat launch inside the VM: credential channel, uid layout, PTY and output ingestion.

Concern 5 also has a hard dependency that does not exist yet (Finding F1). The split is:

- **Plan 4a (this document, detailed):** the E2B substrate, qualified with a null workload.
  Board legs cannot reach it.
- **Plan 4b (outlined under "Follow-on: plan 4b"):** a seat runs inside the VM.
  - The **CD1 in-VM layout is fixed in this document**, because 4a's guest probe measures
    every fact that layout relies on.

## Findings against plan 1 (stated precisely; the seam is not reshaped here)

- **F1 E2B can stage against the seam, but cannot run a seat against it.**
  - Plan 1's `PlacementBackend` has only `name`, `available`, `place(request, review_dir) ->
    PlacedSandbox`, `release` and `capabilities`.
  - `_default_spawn` keeps revalidation, egress and **the provider launch local**, and launches
    from `placed.local_tree`.
  - `PlacementReceipt.kind` includes `executed`, but no Protocol method produces it.
  - A backend that returns `local_tree=None` therefore has no defined launch path in plan 1.

  So 4b needs a remote-execution extension. Plan 3, the self-hosted HTTPS backend (not yet
  written), must supply it; this plan names only the minimum it binds to (see "Follow-on:
  plan 4b"). Until that extension exists, 4a **does not register** the `e2b` scheme with
  `register_backend`. Plan 1's "unregistered scheme" fallback, and its fail-closed branch
  under `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED`, stay in force for board legs. Only 4a's
  operator commands construct `E2BBackend` directly. Registering it earlier would place
  remotely and launch locally, which is exactly the agent-harness#896 defect.
- **F2 Private ranges are always blocked.** Plan 1 said "the docs do not state the default". E2B
  now documents that outbound traffic to 10/8, 100.64/10, 127/8, 169.254/16, 172.16/12 and
  192.168/16 is always blocked and "cannot be disabled"
  ([restrict-public-access](https://docs.e2b.dev/network/restrict-public-access.md), read
  2026-09-29). The pre-launch probe still proves it.
- **F3 A connect probe proves nothing.** "Blocked connections may appear successful from inside
  the sandbox" ([internet-access](https://docs.e2b.dev/network/internet-access.md), read
  2026-09-29). Plan 1 said the in-VM connect to each denied range "must fail", and a connect
  can appear to succeed even when blocked. So every egress probe here requires an
  application-level response: a TLS handshake that completes with the expected certificate
  name, or an HTTP status line. It never relies on `connect()` alone.
- **F4 CD1 needs domain rules, which plan 1 said the adapter would never use.**
  - Plan 1: "the adapter uses CIDR rules only, never domain rules".
  - CD1 locks egress to vendor API **hostnames**. E2B can express that only as
    `deny_out=["0.0.0.0/0"]` with domain entries in `allow_out`, and domain filtering works
    only on ports 80 and 443, by Host header and SNI ([internet-access], read 2026-09-29).
  - Once any domain rule exists, `8.8.8.8` is automatically allowed for DNS, outside the filter.
  - The adapter therefore uses domain rules, and closes the DNS and QUIC residuals **in the
    guest** (see the egress table). If it cannot, the leg is refused.
- **F5 Three variables, not one.** The VM sees `E2B_SANDBOX`, `E2B_SANDBOX_ID` and
  `E2B_TEMPLATE_ID`, also as files in `/run/e2b/`
  ([environment-variables](https://docs.e2b.dev/sandbox/environment-variables.md), read
  2026-09-29). Plan 1 said only `E2B_TEMPLATE_ID`. None is secret.
- **F6 `secure=` is contradictory.** SDK 2.51.0 calls it deprecated and ignored ("every sandbox
  secures envd access"), while [secured-access](https://docs.e2b.dev/sandbox/secured-access.md)
  (read 2026-09-29) says `secure=false` disables it. The adapter never passes `secure`. It
  treats secured envd as the only mode, and still probes envd reachability from the seat uids
  (row E6).
- **F7 `E2B_DEBUG` makes `kill()` a no-op.** SDK source: with `E2B_DEBUG` set, `kill()` is
  skipped and the SDK targets localhost. A cleanup path that trusts `kill()` would then leak
  paid sandboxes. The backend refuses to create when `E2B_DEBUG` is set.

## Research summary

**E2B**, read 2026-09-29 from docs.e2b.dev and the `e2b` 2.51.0 wheel. The wheel was
published 2026-09-18, requires Python ≥3.10, and is imported as `from e2b import Sandbox,
Template, SandboxQuery, SandboxState`.

- **`Sandbox.create`** takes `template, timeout, metadata, envs, allow_internet_access,
  network, lifecycle, …`.
- **Timeouts.** The default is 300 s. The maximum is 3600 s on Hobby and 86400 s on Pro
  ([sandbox-lifetime](https://docs.e2b.dev/faq/sandbox-lifetime.md)).
- **`set_timeout(t)`** sets the deadline to t seconds from now, and can extend or reduce it
  ([sandbox](https://docs.e2b.dev/sandbox.md)).
- **`lifecycle`** takes `{"on_timeout": "kill"|"pause", "auto_resume": bool}`; `"kill"` is the
  default ([auto-resume](https://docs.e2b.dev/sandbox/auto-resume.md)).
- **`Sandbox.list(query=SandboxQuery(metadata=…, state=[…]))`** pages through both running and
  paused sandboxes.
- **`SandboxInfo`** has `sandbox_id, template_id, name, metadata, started_at, end_at, state`,
  and **no `build_id`**.
- **Templates.**
  - `Template.build(...)` returns `BuildInfo(template_id, build_id, name, alias, tags)`.
  - `<template>:<build_id>` pins a build; tags can be moved
    ([tags](https://docs.e2b.dev/template/tags.md)).
  - E2B documents **no content digest**.
  - The guest kernel is 6.1.158 ([how-it-works](https://docs.e2b.dev/template/how-it-works.md)).
    The fc-kernels config sets `CONFIG_USER_NS`, `SECCOMP_FILTER` and `NF_TABLES` to `y`
    (source, not docs). **Runtime sysctls and binaries are not documented**, which is why
    probe P below exists.
- **Users and privilege.**
  - The default user is `user`
    ([user-and-workdir](https://docs.e2b.dev/template/user-and-workdir.md)).
  - Passwordless sudo is **not documented**, but examples rely on it
    ([docker example](https://docs.e2b.dev/template/examples/docker.md)).
  - The infra provisioning runs `passwd -d root` (e2b-dev/infra, source).
  - envd runs as `User=root` (e2b-dev/infra `envd.service.tpl`, source).
- **Commands and PTY.**
  - `commands.run(cmd, background, envs, user, cwd, stdin, timeout=60)`, with
    `send_stdin(pid, data)` / `close_stdin(pid)`; `timeout=0` removes the limit
    ([background](https://docs.e2b.dev/commands/background.md)).
  - `pty.create(size, user, cwd, envs, timeout)` and `pty.send_stdin` / `resize`
    ([pty](https://docs.e2b.dev/sandbox/pty.md)).
  - Per-command `envs` are "scoped to the command but are not private in the OS"
    ([environment-variables], read 2026-09-29).
- **Files.** `files.write(path, data|IO, user=…)` streams file objects. **No size limit is
  documented.**
- **Network.**
  - `allow_out` beats `deny_out`. Domains cannot be put in deny lists. QUIC is not
    domain-filtered.
  - `update_network` **replaces** the whole rule set.
  - "Per-host request transforms" inject headers from stored `Secret`s through a TLS-intercepting
    proxy whose CA is installed in the guest trust store
    ([secrets/inject](https://docs.e2b.dev/secrets/inject.md), public beta).
- **Billing.** Billed per second while a sandbox runs. Paused sandboxes are retained without
  limit.
  - Concurrency: 20 on Hobby, and 100–1,100 on Pro.
  - Creation: 1/s on Hobby, 5/s on Pro. A 429 comes with `Retry-After`.
  - There is **no usage API**, only a console budget
    ([billing](https://docs.e2b.dev/billing.md)).
- **API keys** are "scoped to exactly one project", with no documented expiry or restriction
  ([projects](https://docs.e2b.dev/projects.md)). The SDK logs only the method and URL, and
  only when a `logger` is passed. The key travels in `X-API-KEY`.

**Repo** (worktree off `origin/main` at `3c61b270`):
- **Optional extra.** The only extra is `visual` (`phase-loop-runtime/pyproject.toml:64-73`),
  and its import is guarded lazily (`models.py:1353-1354`).
- **Config.**
  - `advisor_board/config.py` holds the user file
    `$XDG_CONFIG_HOME/agent-harness/advisor-boards.toml` (`_user_config_path`, around line 243)
    and the repo file `.agent-harness/advisor-boards.toml` (`REPO_CONFIG_RELATIVE_PATH`,
    line 63).
  - Keys are closed by `_KNOWN_TOP_KEYS` (line 54), `_KNOWN_REPO_TOP_KEYS` and
    `_reject_unknown`, which is around line 102. A new section follows the model of
    `_parse_agy`.
  - The harness names are in `advisor_board/registries.py` `_HARNESS_SPECS`, around lines
    202–210.
- **Tree digest.** `review_stage.review_tree_manifest_sha256` (line 190) hashes each path's
  blob-or-link kind, **exec bit**, content sha256, length and path sha256. A per-file upload
  that drops modes or symlinks cannot reproduce it.
- **agy pin set.** `scripts/verify_qualified_agy_image.py` `actual_source_hashes()` hashes
  **every `*.py` in the package**. Any new module here therefore drifts the agy pin set, and
  forces agy requalification at the next release cut.
- **Leases.** `lease_store.py` handles path-set coordination leases and is **not** a sandbox
  lease journal. Plan 1's outline assigns the lease journal to plan 3.
- **Not yet in code.** No `live` pytest marker exists. The `seat_sandbox_refused:*` codes and
  the J3 token pipe exist only in the agent-harness#1132 plan.

## Design (plan 4a)

### Enablement, opt-out and eligible legs (CD4, CD2)

- **Off by default.**
  - Cloud placement is requested **per run**, by the plan 1 location
    `PHASE_LOOP_SANDBOX_ROOT=e2b://<config-profile>`.
  - It is refused unless the user file has an `[e2b]` table naming:
    - the template pin;
    - all three caps;
    - `eligible_legs`.
- **User file `[e2b]` keys** (closed set):
  - `template` (`"<name>:<build_id>"`; a bare tag is refused with `e2b_template_unpinned`);
  - `project_label` (evidence only);
  - `lease_ttl_s`;
  - `max_concurrent_per_run`, `max_seconds_per_run`, `max_seconds_per_day`;
  - `max_snapshot_bytes`;
  - `eligible_legs`.
- **`eligible_legs`** is a subset of the `_HARNESS_SPECS` names. In v1 only `claude` and
  `gemini` are accepted. `codex` and `grok` are rejected with a config error, because D1 leaves
  them unjailed locally, so "the same as the local jail" is undefined for them. Accepting a
  leg name in 4a admits nothing: board legs cannot reach the backend until 4b.
- **Repo opt-out: `[sandbox] cloud = false`** in `.agent-harness/advisor-boards.toml`.
  - The file is authored by the repository under review, so a PR could delete it.
  - The opt-out is therefore honoured if it is present in **either** the base ref's blob
    (`git show <base>:.agent-harness/advisor-boards.toml`) **or** the reviewed tree. A PR can
    add an opt-out but never remove one.
  - The refusal code is `e2b_repo_opted_out`.

### Refusal codes

Refusals flow through plan 1's `PlacementUnavailable(code, reason)`. They become a recorded
local fallback, or, under `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED`, plan 1's single detail code
`sandbox_placement_required_unavailable`. **No new `_HARNESS_DETAIL_CODES` member** is added,
and the E2B codes live only in the fallback reason and evidence. The codes are:

- extra and configuration: `e2b_extra_missing`, `e2b_not_configured`, `e2b_template_unpinned`;
- enablement: `e2b_repo_opted_out`, `e2b_leg_ineligible`;
- caps: `e2b_cap_concurrency`, `e2b_cap_run_seconds`, `e2b_cap_day_seconds`;
- lease: `e2b_lease_exceeds_tier`;
- environment: `e2b_debug_mode_refused`, `e2b_api_key_missing`;
- snapshot: `e2b_snapshot_too_large`, `e2b_snapshot_digest_mismatch`;
- template: `e2b_template_stale`;
- probe: `e2b_probe_failed:<row>`, where `<row>` is a closed set, the probe row ids P1–P12.

### The E2B API key

- **Where it may exist.**
  - It is read only from `E2B_API_KEY` in the local runtime's environment, and passed only as
    the SDK's `api_key=` argument.
  - It is never passed in `envs`, `metadata`, a file write, a command line, a log or evidence.
  - The backend never passes `logger=` to the SDK.
  - Evidence records `project_label` and the SHA-256 of the key's first 8 bytes. It never
    records the key itself.
- **Environment scrubbing.**
  - The in-VM environment is built from an explicit allowlist, never from `os.environ`.
  - `E2B_API_KEY` is removed from the environment of every local provider child. This matches
    how the existing sandbox env builders drop credentials; the implementer searches for the
    local child-env builder in `panel_invoker.py` and adds the key there.
- **Exceptions.** Before any SDK exception message is recorded, it is scrubbed through
  `_redact_leg_text` (`panel_invoker.py`, around line 2086).
- **Operator docs** recommend a dedicated E2B project for harness sandboxes, and a console
  spending limit.

### Template build and pinning

- **The build definition** is a packaged module, `sandbox_e2b_template.py`. From the same pins
  as local seats, it declares:
  - the Debian base;
  - `claude` at the version the local seat pins;
  - `agy` from the **verified qualified artifact**, whose hash must equal the record in
    `plans/evidence/qualified-provider-images.json`;
  - `nftables`, `util-linux` (`setpriv`), `bubblewrap` and `python3`;
  - the packaged guest assets: the probe, the tree digest and the archive extractor.
- **Hardening in the build.** The build definition locks root (`passwd -l root`) and removes
  `sudo` and the `user` sudoers entry. This counters the infra `passwd -d root`, and probe row
  P2 proves it. It also creates `seat-cli` and `seat-tool`, two unprivileged uids with no
  supplementary groups except a shared `seat-tree` group.
- **The template manifest.** The build writes `/opt/agent-harness/template-manifest.json`. It
  holds:
  - the runtime version;
  - the sha256 of the **guest-asset bundle**;
  - the sha256 and `--version` output of every toolchain binary.
- **Build command.** `phase-loop sandbox-e2b template build` runs `Template.build(...)` with
  `skip_cache=True` and prints `name:build_id` plus the expected manifest sha256. The operator
  copies both into `[e2b] template` (and `template_manifest_sha256`). The command writes to no
  repository file.
- **Launch-time check.**
  - Create uses `"<name>:<build_id>"`, never a tag.
  - The in-VM manifest hash is compared with the configured one, and the manifest's
    guest-asset sha256 with the installed runtime's own guest assets.
  - A mismatch is `e2b_template_stale`. A runtime upgrade that changes the guest assets
    therefore forces a rebuild; it can never run against old assets silently.
- **Requalification.**
  - Any change to a seat CLI pin, the build definition or the guest assets needs
    `template build` followed by `sandbox-e2b qualify` (see "Live qualification").
  - The new `sandbox_e2b*.py` modules are in the agy full pin set by construction
    (`actual_source_hashes`). **The next release cut therefore requalifies agy** under the
    existing recipe.
  - The release checklist gains one line: when the release changes a seat CLI pin or the guest
    assets, the maintainer rebuilds and requalifies the E2B template with the live key.
  - The template pin itself stays in operator config, because it belongs to an E2B project and
    is not a release pin.

### Snapshot upload

- **The archive.**
  - The runtime builds a deterministic uncompressed tar, in sorted order, from the plan 1
    local stage.
  - Entries carry mode bits and symlink targets, with owner and group 0 and mtime 0.
  - Before upload, the runtime recomputes `review_tree_manifest_sha256` over the stage. It must
    equal the authorization's `staged_tree_sha256`, which is runtime-attested; otherwise the
    code is `e2b_snapshot_digest_mismatch`.
- **Size.** Over `max_snapshot_bytes` is refused with `e2b_snapshot_too_large`. E2B documents
  no limit; the qualification measures the largest successful upload and records it.
- **Upload.**
  - The archive goes up as one streamed `files.write("/seat/in/tree.tar", fileobj,
    user="root")`. There is no `git.clone`, and no credential is ever given to git
    ([git-integration](https://docs.e2b.dev/sandbox/git-integration.md), read 2026-09-29).
  - It is extracted **as `seat-tool`**, into an empty `/seat/tree` (group `seat-tree`, 2770),
    by the packaged extractor. The extractor refuses absolute paths, `..`, hard links, device
    nodes, and any member whose path crosses a symlink it has already extracted. It then
    recomputes the digest with the packaged copy of `review_tree_manifest_sha256`.
  - The in-VM digest is a `backend` claim. A mismatch refuses before any launch.

### Lifecycle: no paid sandbox outlives its lease

- **Create.**
  - `create(template, timeout=lease_ttl_s, lifecycle={"on_timeout": "kill", "auto_resume":
    False}, metadata={...}, network={...}, envs={})`.
  - The metadata keys are `agent_harness_owner` (a random per-install id kept in the
    operator's XDG state dir), `round`, `leg`, `lease` and `runtime_version`.
  - `lease_ttl_s` must be ≤ the tier maximum (3600 s or 86400 s) **and** ≥ 3 heartbeat
    intervals. A leg deadline longer than the tier maximum is refused
    (`e2b_lease_exceeds_tier`), never truncated.
- **No pause.** The adapter never uses `on_timeout: "pause"`, `auto_resume`, `beta_pause` or
  `connect()`-to-resume.
- **Heartbeat.** Every `lease_ttl_s / 3`, the owner calls `set_timeout(lease_ttl_s)`. Because
  E2B measures from now, a dead owner stops extending and E2B's own timer kills the VM within
  `lease_ttl_s`. That holds with the client killed by SIGKILL.
- **Release.** `release()` calls `kill()` and then confirms that `get_info` returns not-found or
  a non-running state. `kill() == False` (not found) counts as success. Any other state is
  retried and then recorded.
- **Reaper.**
  - It runs at backend construction (runtime startup and restart) and before every create.
  - It lists `Sandbox.list(query=SandboxQuery(metadata={"agent_harness_owner": id},
    state=[running, paused]))` across all pages, and kills every sandbox whose `lease` has no
    live entry in the local lease journal.
  - Paused sandboxes are included, so a sandbox paused out of band is also reaped.
- **Lease journal.** 4a binds to plan 3's lease journal: `acquire`, `renew`, `release`,
  `live(owner)`, fsynced and append-only. If plan 3 has not landed, that is a precondition. 4a
  does not build a second journal.

### Cost caps (CD3)

All three caps are checked **before `create`**, and every one of them is mandatory: an absent
cap is `e2b_not_configured`.

- **`max_concurrent_per_run`.** The run's live leases are counted before create.
- **`max_seconds_per_run`.** The reservation is the leg deadline, rounded up to whole seconds.
  Settled usage is `end_at - started_at` from `get_info`, or the local create-to-kill-confirmed
  wall time, whichever is larger.
- **`max_seconds_per_day`.** A locked ledger in the operator XDG state dir, per UTC day, holds
  reservations and settlements.
- **Disclosure.** The day ceiling is per local state dir. An operator using several hosts on one
  E2B project also sets E2B's console spending limit as the backstop, because E2B exposes no
  usage API.

### Egress: what E2B can and cannot enforce

The required policy for a seat leg has four parts:
- the seat vendor's API hostnames on 443 only;
- no other destination;
- no DNS from seat uids;
- the envd port unreachable from seat uids.

The network config is `deny_out=["0.0.0.0/0"]`, `allow_out=[<vendor hostnames for the leg>]`,
`allow_public_traffic=False`. The hostnames per leg are **data measured by probe, never
guessed**. For `claude` and `gemini`, the implementer records them from the local
agent-harness#1132 P2/P4 runs, and 4b's live qualification proves a turn completes with exactly
that set. The null workload in 4a uses one test hostname.

| # | Requirement | E2B | In-guest control (template, root-owned) | If not provable |
|---|---|---|---|---|
| E1 | Vendor API hostnames on 443 only | **Can**: a domain rule by SNI/Host on 80/443 | none | refuse (`e2b_probe_failed:P7`) |
| E2 | Everything else denied, including IP-literal 443 | **Can**: `deny_out` 0/0 wins except for allowed domains | none | refuse (`P8`) |
| E3 | Private, CGNAT, link-local and metadata ranges | **Can**: always blocked, cannot be disabled (F2) | none | refuse (`P9`) |
| E4 | No DNS exfiltration | **Cannot**: `8.8.8.8` is auto-allowed once any domain rule exists | the local runtime resolves the vendor hostnames and writes `/etc/hosts`; nftables drops udp/tcp 53 for `meta skuid {seat-cli, seat-tool}` | refuse (`P10`) |
| E5 | No QUIC or other UDP around the filter | **Cannot** domain-filter QUIC | nftables drops all UDP from both seat uids | refuse (`P10`) |
| E6 | Seat uids cannot drive envd (root) on 49983 | **Partly**: secured access token on the API (F6) | nftables drops `lo` → 49983 for both seat uids | refuse (`P6`) |
| E7 | `seat-tool` (reviewed code) has no network at all | **Cannot** filter per uid | nftables drops all non-loopback output for `meta skuid seat-tool` | refuse (`P11`) |
| E8 | TLS confidentiality toward the vendor | **Cannot**: the egress-proxy CA is in the guest trust store | none | **disclosed** CD2 residual, not a refusal |
| E9 | Per-port rules outside 80/443 | **Cannot** (not documented) | none needed: E1/E2 allow 443 only | not applicable |

- **Where the rules live.** The in-guest rules are loaded by root at template start, and again
  before each leg by the root launcher. Neither seat uid can change them (P2 proves no root
  path).
- **How rows are proven.** Every row is proven by application-level evidence (F3), for example
  a TLS handshake to the vendor host succeeding and one to a public non-vendor host failing.
- **No partial pass.** A leg whose rows do not all pass is refused. The adapter never weakens
  the policy to get a leg through.

### Guest probe P (measurement for CD1 and CD2)

The probe runs as a packaged script, once per sandbox before any launch. It runs as each seat
uid and as root, and emits closed-schema JSON, which is recorded as `attested_by="backend"`.
Rows:

- **P1** uid, gid and groups of each seat uid.
- **P2** No root path from either seat uid: `sudo -n true`, `su -c true </dev/null`,
  setuid-root binaries outside an allowlist, writable `/etc` or `/opt/agent-harness`. Each of
  these must fail or be empty.
- **P3** `/proc` mounted with `hidepid=2`. `seat-tool` sees no `seat-cli` pid and cannot read
  `/proc/<cli>/environ|mem|fd`. Checked with a sleeper launched as `seat-cli`.
- **P4** `kernel.yama.ptrace_scope` and `kernel.unprivileged_userns_clone` /
  `user.max_user_namespaces`. Whether `bwrap --unshare-user` works as `seat-cli`.
- **P5** Seccomp: whether a filter can be installed (`bwrap --seccomp`), and the
  `Seccomp`/`NoNewPrivs` status fields.
- **P6** envd is unreachable from both seat uids: a request to `127.0.0.1:49983` gets no HTTP
  response.
- **P7–P11** Egress rows E1, E2, E3, E4/E5 and E7.
- **P12** Capabilities: `CapBnd`/`CapEff` of each seat uid's process. Whether `setpriv
  --bounding-set=-all` works. For CD2 disclosure: whether a nested bwrap with retained
  `CAP_SETFCAP` works. That is codex's local route (agent-harness#999); it is measured even
  though codex is ineligible in v1.

P1–P3, P6 and P7–P11 gate every leg. P4, P5 and P12 are **measured and disclosed** (CD2):
their values go into evidence and the operator docs, and gate only what 4b makes depend on
them.

### Receipts (plan 1 vocabulary; no new receipt kinds)

- **`staged` receipt** from `place()`:
  - `sandbox_ref`: the `sandbox_id` returned by create;
  - `attested_by="runtime"` for what the runtime itself sent: the requested `name:build_id` and
    the archive's local digest.
  - `details`, declared by the adapter: `e2b_template_ref` (requested),
    `e2b_template_id_reported`, `template_manifest_sha256_reported`, `snapshot_sha256_in_vm`
    and `probe`. Every `_reported` or in-VM value is `attested_by="backend"`.
- **Capabilities declared by `capabilities()`:** `filesystem_confined` and `credential_free`.
  They are declared only when the probe passes, and `network_filtered` only when P7–P11 pass.
  `uid_isolated` depends on P1–P3, and is declared only in 4b. `bounding_set_empty` and
  `resource_bounded` are **never declared** in 4a.
- **What decides the verdict.** Remote output is never receipt-class on its own. The local
  runtime keeps the verdict. `sandbox_root_applied` requires an `executed` receipt, so it can
  become true only in 4b.

## Changes (plan 4a)

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project.optional-dependencies]` — add `e2b = ["e2b>=2.51,<3"]`, with a comment in the style
  of `visual`: imported lazily, never a core dependency.
- `[tool.setuptools.package-data]` — add `"e2b_guest/*"` so the guest assets ship in the wheel.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_e2b.py` (create)
- `E2BConfig` / `load_e2b_config()` — add — the validated `[e2b]` table, through
  `advisor_board.config`.
- `E2BBackend` — add — plan 1's `PlacementBackend`: `available`, `place`, `release` and
  `capabilities`, as designed above. It also has `heartbeat(placed)` and `reap()`. `import
  e2b` happens only inside `E2BBackend.__init__`; an `ImportError` becomes `e2b_extra_missing`.
- `CostLedger` — add — the per-run and per-day reservations and settlements.
- `build_network_rules(leg_hosts)` / `resolve_hosts_for_guest(leg_hosts)` — add — the E1/E2
  config and the `/etc/hosts` payload.
- `build_tree_archive(stage) -> (path, sha256)` — add — the deterministic tar.
- **Not registered** with plan 1's `register_backend` (F1).

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_e2b_template.py` (create)
- `template_definition(pins)` — add — the `Template()` builder chain above.
- `guest_assets_sha256()` — add — the digest of the packaged `e2b_guest/` files.

### `phase-loop-runtime/src/phase_loop_runtime/e2b_guest/` (create; package data)
- `probe.py` — add — rows P1–P12, closed JSON schema.
- `extract_tree.py` — add — the refusing extractor, and the digest recomputed with a copy of
  `review_tree_manifest_sha256`'s algorithm.
- `nft.rules` — add — the E4–E7 rules.
- `template_digest.py` — add — writes and verifies the template manifest.

The guest assets use only the stdlib, because they run under the template's `python3`. A drift
test asserts that `extract_tree.py`'s digest function reproduces
`review_stage.review_tree_manifest_sha256` on a fixture tree holding an exec bit, a symlink and
a non-UTF-8 name.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py` (modify)
- `_KNOWN_TOP_KEYS` — modify — add `"e2b"`.
- `_KNOWN_E2B_KEYS` / `_parse_e2b` / `load_e2b_section` — add — follow the `_parse_agy` model:
  a closed key set, typed values, and `eligible_legs ⊆ {"claude", "gemini"}`.
- `_KNOWN_REPO_TOP_KEYS` — modify — add `"sandbox"` (`_KNOWN_SANDBOX_KEYS = {"cloud"}`).
- `repo_cloud_opt_out(repo_dir, base_ref)` — add — the union rule (base-ref blob **or** working
  tree).

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- A `sandbox-e2b` subparser — add — with three subcommands:
  - `template build` (prints the pin; writes no files);
  - `qualify` (the null-workload qualification: create, upload, probe, heartbeat, kill,
    reap-verify, and a printed JSON record);
  - `reap` (a manual reaper run).

  It follows the existing `add_parser` pattern around lines 424–451.

### `phase-loop-runtime/tests/test_sandbox_e2b.py` (create)
- These tests run against a fake `e2b` module injected into `sys.modules`. It records every
  call, and the lifecycle clock is virtual. The falsifiers are under "Verification".

### `phase-loop-runtime/tests/test_sandbox_e2b_live.py` (create)
- The gated live qualification (below).

### `phase-loop-runtime/tests/test_advisor_board_config.py` (modify)
- The `[e2b]` and repo `[sandbox]` key-closure tests, and the opt-out union rule.

## Documentation impact
- `docs/phase-loop/convergence-runtime.md` — modify — the `e2b://` location, the `[e2b]` and
  `[sandbox] cloud` keys, the refusal codes, the cap semantics and the multi-host
  spending-limit caveat. Also: 4a is qualification-only and board legs still fall back.
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — the E2B
  receipt `details` keys, and which of them are `backend` claims.
- `docs/advisor-board-capabilities-card.md` — modify — the CD2 disclosure: vendor visibility,
  E8, and where the P4/P5/P12 measured values are published.
- `docs/releases/` release checklist (the one used for agy requalification) — modify — add the
  E2B template rebuild and requalify line.
- `CHANGELOG.md` — modify — the `[e2b]` extra and the operator commands. New package `.py`
  files drift the agy full pin set, so the next release cut requalifies agy.
- `phase-loop-runtime/README.md` — modify — `pip install 'phase-loop-runtime[e2b]'`, and that
  the key is read only from `E2B_API_KEY`.

## Dependencies & order
1. **Plan 1 (agent-harness#1162) must land first**: `PlacementBackend`, `PlacementReceipt`,
   `PlacementUnavailable` and the scheme parse.
2. **Plan 3's lease journal must land first**, or be split out of plan 3 first. 4a does not
   build its own.
3. Within 4a, the order is:
   1. config keys, then the ledger and caps;
   2. the archive, digest and extractor, with the drift test;
   3. the template definition and guest assets;
   4. the backend lifecycle and reaper;
   5. the CLI;
   6. the live test.

   Tests are written first, skip-guarded on the new symbols, and each gets a RED receipt.
4. 4a does **not** depend on agent-harness#1132. 4b does.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_sandbox_e2b.py tests/test_sandbox_e2b_live.py \
  tests/test_advisor_board_config.py tests/test_president_ladder_config.py
python -c "import phase_loop_runtime.sandbox_e2b"   # without the extra installed: must succeed
```

Falsifiers in `test_sandbox_e2b.py`. Each has a control-green receipt and a **named mutation**
that must turn it red:

- **No paid sandbox outlives its lease.** `test_sigkilled_owner_sandbox_dies_within_lease`.
  - Setup: the fake SDK has a virtual clock and kills on timeout. After create, the owner
    thread is stopped with no `release`, which simulates SIGKILL.
  - Assertion: after `lease_ttl_s + 1` virtual seconds, `list(state=[running, paused])` is
    empty.
  - Mutations, each red:
    - (a) `timeout=86400` at create;
    - (b) `lifecycle={"on_timeout": "pause"}`;
    - (c) the heartbeat extends by `2 * lease_ttl_s`;
    - (d) the reaper drops the `paused` state filter. A companion test pauses a sandbox out of
      band, and the reaper must kill it;
    - (e) the reaper skips the metadata filter. A companion test asserts that another owner's
      sandbox is **not** killed.
- **E2B_DEBUG is refused.** With `E2B_DEBUG=1`, `place` raises `e2b_debug_mode_refused` and the
  create counter is 0. Mutation: drop the check.
- **Caps refuse before create.** For each of the three caps, the breach raises its code and the
  create counter stays 0. Mutation: check the cap after create.
- **Key redaction.** `test_e2b_api_key_never_leaves_runtime`.
  - Setup: `E2B_API_KEY` holds a sentinel.
  - Assertion: after a full place, probe and release, the sentinel and its standard, URL-safe
    and hex encodings appear in none of these:
    - the fake SDK's recorded `envs`, `metadata` and command lines;
    - the written bytes;
    - the evidence dict;
    - `caplog`;
    - the recorded exception text, including a forced SDK error whose message embeds the key.
  - Mutations, each red:
    - put the key into `envs`;
    - pass `logger=logging.getLogger()` to the SDK;
    - record the raw exception message without redaction.
- **No git clone, exact digest.** Upload uses exactly one `files.write` of the archive and never
  calls `git.clone`. The archive's recomputed digest equals `staged_tree_sha256`. Mutations:
  flip an exec bit in the archive, which gives `e2b_snapshot_digest_mismatch`; or upload file by
  file without modes, which reddens the drift test.
- **The extractor refuses** absolute paths, `..`, hard links and symlink traversal. Mutation:
  allow a member under an extracted symlink.
- **Egress table.** `build_network_rules` emits `deny_out ["0.0.0.0/0"]` and only the leg's
  hosts. A probe JSON with any of P6–P11 false refuses with `e2b_probe_failed:<row>`, and never
  retries with a weaker network. Mutation: drop `deny_out`.
- **Not registered.** `resolve_backend("e2b://x")` is still plan 1's unregistered fallback in
  4a. Mutation: register the backend.
- **Opt-out union.** An opt-out only in the base ref still refuses. Mutation: read only the
  working tree.
- **Extra absent.** With `e2b` hidden from `sys.modules`, construction raises
  `e2b_extra_missing`, and importing the core never imports `e2b`.

**Live qualification** (`test_sandbox_e2b_live.py`). The module skips with the first applicable
of these exact reasons:
- `"E2B live qualification skipped: the e2b extra is not installed"`;
- `"E2B live qualification skipped: E2B_API_KEY not set in the runtime environment"`;
- `"E2B live qualification skipped: PHASE_LOOP_E2B_LIVE != 1"`;
- `"E2B live qualification skipped: no [e2b] template pin in the user config"`.

When it runs, it drives `phase-loop sandbox-e2b qualify` against the real project. It asserts:
- the probe rows P1–P3 and P6–P11 pass, and P4, P5 and P12 are recorded;
- the digest round-trip;
- a client SIGKILL of a child qualify process leaves no sandbox with its lease id after
  `lease_ttl_s` (set to 120 s) plus 60 s;
- the billed seconds, recorded from `get_info`;
- the largest snapshot uploaded, recorded;
- the sentinel scan, run on the JSON record.

**How the maintainer supplies the key.** The maintainer exports `E2B_API_KEY` in the shell that
runs the test, from their secret store (in Claude Code: `! export E2B_API_KEY=…`), and sets
`PHASE_LOOP_E2B_LIVE=1`. The key is never written to a file in the repo. CI never sets it, so CI
always skips. The record is attached to the 4a PR as operational evidence.

Run the suite on a tree **left untouched** for its duration.

## Acceptance criteria
- [ ] `test_sandbox_e2b.py::test_sigkilled_owner_sandbox_dies_within_lease` passes. Each of
  mutations (a)–(e) turns it or its named companion red.
- [ ] `test_sandbox_e2b.py::test_e2b_api_key_never_leaves_runtime` passes. Each of its three
  named mutations turns it red.
- [ ] With the fake SDK, every cap breach, `E2B_DEBUG=1`, an unpinned template and a repo
  opt-out (base ref only) each raise their `e2b_*` code with the create counter at 0. With
  `e2b` absent, `import phase_loop_runtime.sandbox_e2b` succeeds and construction raises
  `e2b_extra_missing`.
- [ ] `resolve_backend("e2b://x")` returns plan 1's unregistered fallback, with no socket
  connect and no SDK import. The drift test shows `e2b_guest/extract_tree.py` reproduces
  `review_tree_manifest_sha256` on the exec-bit, symlink and non-UTF-8 fixture.
- [ ] `test_sandbox_e2b_live.py` skips with the exact reason
  `"E2B live qualification skipped: E2B_API_KEY not set in the runtime environment"` when
  the key is absent. The maintainer's live run is attached to the PR, and shows P1–P3 and
  P6–P11 passing and zero leftover sandboxes after the SIGKILL case.

## Follow-on: plan 4b, a seat runs inside the VM (outlined; its own bounded plan)

**Preconditions.**
- 4a has landed.
- agent-harness#1132 has landed: the J3 token pipe, D2 and D7.
- Plan 3 has supplied the remote-execution extension. The minimum 4b binds to is:
  - `launch(placed, argv, env, credential_channel, pty) -> handle`, plus `heartbeat`, `cancel`
    and `collect_output`;
  - an `executed` receipt;
  - a spawn-seam counter that proves zero local provider spawns.

  4b binds to whatever names plan 3 lands. It does not define its own.

**The CD1 in-VM layout.** This is what E2B actually allows, measured by probe P:

1. **Processes.**
   - root runs only envd (E2B's) and the packaged launcher. The launcher is started with
     `commands.run(..., user="root", stdin=True, timeout=0)`.
   - `seat-cli` runs the provider CLI.
   - `seat-tool` runs every command the CLI's tools execute, which is where the reviewed code
     runs.
   - Neither seat uid has a root path (P2).
2. **The one-shot credential channel.**
   - The local runtime sends the credential bytes over the launcher's **stdin stream**
     (`send_stdin`, then `close_stdin`, documented). This is the in-VM equivalent of the local
     pipe.
   - The launcher never writes the credential to disk or to any environment. It then does
     either of these:
     - **Claude (D2):** creates a pipe, writes the token, closes the write end, and execs
       `claude` as `seat-cli` with the read end as its only extra fd. The fd is named by
       `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, exactly the J3 mechanism.
     - **Gemini (D7):** writes the access-token-only copy into a **tmpfs** directory owned by
       `seat-cli`, mode 0500 for the directory and 0400 for the file, and points agy's config
       path at it. The local D7 route is a file in a read-only config dir, so "never a file on
       disk" is met by tmpfs only. It is a tmpfs file readable by `seat-cli` alone. **Stated
       tension, for maintainer confirmation (open decision M1).**
   - The credential is never carried in `envs`, because E2B documents those as "not private in
     the OS".
3. **Tool execution under a separate uid.**
   - The CLI's shell is a packaged `tool-shell` wrapper, running as `seat-cli`. It hands its
     argv and stdio fds (by `SCM_RIGHTS`) over a unix socket to the root launcher.
   - The launcher forks, calls `setresuid(seat-tool)`, clears the environment and execs
     `bash -c` in `/seat/tree`. Tool children therefore never inherit the CLI's fds or
     environment.
   - With `hidepid=2` (P3) and distinct uids, a tool child cannot read `/proc/<cli>/mem`,
     `environ` or `fd`.
   - **Whether the Claude CLI's Bash tool honours the shell override is a probe in 4b (Q1), not
     a design fact.** If it does not, Claude is refused cloud placement
     (`e2b_tool_uid_unavailable`), never run with tools under `seat-cli`. agy's tool execution
     path gets the same probe (Q2).
4. **Egress.**
   - Sandbox-wide, E1/E2 restrict egress to the vendor hosts.
   - In the guest, E7 gives `seat-tool` no network, and E4/E5 take DNS and UDP away from both
     uids. The vendor hosts are resolved locally into `/etc/hosts`.
5. **Output.** The runtime ingests the output under the J10-equivalent checks and the J3 token
   scan (`claude_seat_token_in_output` / `gemini_seat_token_in_output`). Only then can anything
   become evidence.

**Residual risk, disclosed and not claimed away.**
- **R1 The agent-harness#1132 D3 residual applies unchanged.** The CLI process itself holds
  the token. A prompt-injected CLI can use its own in-process tools (Read, WebFetch) to exfiltrate
  it to a **vendor** host (E1 allows those), for example into a message on another account. No
  uid boundary separates the CLI from its own memory.
- **R2 The vendor sees everything.** The token transits E2B's API, envd (root) and the
  TLS-intercepting egress proxy (E8). This is accepted under CD2 as a CI-provider-equivalent
  vendor.
- **R3 E2B's API key has no scoping.** It is project-wide, with no documented expiry. The
  containment is a dedicated project and a spending limit.
- **R4 Measured gaps.**
  - If P4 shows no unprivileged userns, or P12 shows no nested bwrap with `CAP_SETFCAP`, the
    codex route cannot run in the guest.
  - If P5 shows seccomp unavailable, J14 has no in-guest equivalent.
  - These are published in evidence and on the capabilities card (CD2). A leg that would need
    them is refused.

**Other 4b items.**
- **Codex and grok stay refused** (`e2b_leg_ineligible`) until agent-harness#895 defines their
  local jail. A later plan maps them.
- **Short-lived tokens.**
  - Claude uses the D2 `setup-token`; its scope and expiry are those P2 measures locally.
  - Gemini uses the D7 access-token-only copy, which has no refresh token.
  - No shorter-lived channel is assumed for either vendor.
  - E2B's "per-host request transforms" (header injection from stored secrets) would keep the
    token out of the VM entirely. But it stores the credential persistently with the vendor,
    and requires the CLI to start with a placeholder credential. **Open decision M2:** probe
    it as an alternative to the stdin channel, or rule it out.
- **4b acceptance** includes plan 1's `sandbox_root_applied` rule: the `staged` and `executed`
  receipts share one sandbox id, and the spawn-seam counter reads 0.

## Open maintainer decisions
- **M1 The Gemini D7 copy in the VM.** The recommendation is a tmpfs-only file readable solely
  by `seat-cli`. This is the closest equivalent of the local read-only config dir, but it is a
  file, not a pipe. The alternative is refusing Gemini in the cloud until agy accepts a
  credential by fd.
- **M2 E2B header injection versus the stdin channel.** The recommendation is to keep the
  stdin channel, which CD1 describes, and to record injection as a probed alternative only.
- **M3 Default cap values.** 4a ships **no** default numbers; every cap must be set, or cloud is
  refused. The alternative is conservative built-in defaults.

## Execution Policy

- execute: effort=high, reason=paid-resource lifecycle, credential-free-by-construction key
  handling, and an in-guest firewall whose every row gates a leg
