---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 3c61b270
related_issues: [agent-harness#896, agent-harness#848, agent-harness#891, agent-harness#895, agent-harness#1132, agent-harness#1147, agent-harness#1161, agent-harness#1071, agent-harness#999, agent-harness#1102]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_sandbox_placement.py tests/test_sandbox_egress.py tests/test_sandbox_policy.py tests/test_sandbox_retention.py tests/test_seat_host_uid_1098.py tests/test_review_monitor_policy.py tests/test_harden_evidence_producer.py tests/test_review_stage_board_findings.py tests/test_sandbox_preamble.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: a vendor-neutral sandbox placement seam with honest placement evidence, local backend first (agent-harness#896, plan 1 of 4)

## Task

agent-harness#896: the runtime resolves a remote sandbox root, then stages and runs the sandbox
locally anyway. The maintainer's scope has three placement backends behind one interface:
- **local:** today's behaviour;
- **self-hosted remote:** an operator-chosen Linux host over authenticated HTTPS, with no SSH
  requirement;
- **cloud:** E2B first, with Modal, Daytona and others as adapters only.

All three must meet these binding rules:
- a general product, with no fleet names in product code;
- confinement parity with the agent-harness#1132 jail;
- a falsifier for each consumer prerequisite on agent-harness#896;
- honest `sandbox_root_applied` / `sandbox_staged_at`;
- a recorded local fallback, with a fail-closed option;
- the E2B SDK only as an optional extra.

**Bounded-plan threshold: this work must be split.** The whole design touches well over 8
source files and at least 5 distinct changes: the seam, the evidence, an HTTPS agent with
auth, leases and cgroups, a cloud adapter, and the egress configuration. This document is
**plan 1**, and covers only:
1. the vendor-neutral placement interface;
2. honest placement evidence built from receipts;
3. today's local path refactored behind the interface, with no behaviour change.

It also adds the recorded-fallback and fail-closed handling for backends that are configured
but not yet implemented. The follow-on plans are listed under "Follow-on plans" with their
scope, dependencies and open decisions.

## Research summary

**The placement steps in `panel_invoker._default_spawn`.** A recon pass mapped them, with
line numbers read at `input_base_commit`:
- scratch GC runs first (`_gc_stale_panel_scratch`, PI:8436);
- `mkdtemp("pl-panel-").resolve()` (PI:8446). The `.resolve()` is load-bearing, because it
  is the preimage of `provider_cwd_sha256` (PI:4495);
- `select_sandbox_root(fallback=review_dir)` (PI:8484). Its result is recorded and never used;
- `ensure_staging_space(review_dir)` (PI:8500);
- `stage_review_tree` (PI:8503), with the staged path tracked across the rename (PI:8508–8510);
- `mark_as_sandbox` (PI:8516);
- `_revalidate_staged_tree` (PI:8527), then `revalidate_review_isolation_authorization`
  (PI:8537);
- **only then** the egress namespace (PI:8542–8568);
- `_record_sandbox_facts(..., staged_at=...)` (PI:8573–8588), whose reset token goes on the
  egress `ExitStack`;
- cleanup in `finally` (PI:8866–8879): close egress, `remove_review_stage`, then `rmtree(base)`.

`_record_sandbox_facts` (PI:3506) computes
`applied = host is None and path == staged_at.parent`. The facts reach the leg record in only
one place: they are merged into the brokered evidence dict (`**_sandbox_evidence()`, around
PI:8693).

**Tests that pin the field names and the `applied` rule:**
- `tests/test_sandbox_egress.py`, around lines 139–676. It includes `sandbox_root_host == "ai"`
  as a fixture value, and a source-grep that the launch site calls `_record_sandbox_facts(` and
  `_SANDBOX_ROUND_FACTS.reset`, around lines 605–606;
- `tests/test_seat_host_uid_1098.py`, `tests/test_review_monitor_policy.py` and
  `tests/test_gemini_heartbeat_bootstrap.py`.

**Coupling that constrains the refactor:**
- `phase-loop-runtime/scripts/verify_harden_evidence.py` `verify_broker`, around line 2334,
  checks broker evidence against a **closed** key set that has no `sandbox_*` keys.
- `verify_broker_argv_paths`, around lines 327–352, requires the argv cwd to hash to
  `provider_cwd_sha256`, and the out dir to be a direct child of the cwd.
- `launcher._stage_review_tree` (`launcher.py:3166`) is a separate implementation and is out of
  scope here.
- `sandbox_policy.parse_location` treats `host:path` as remote, and `_probe_root` /
  `_free_bytes_at` spawn `ssh`.

**E2B facts**, from current docs read 2026-09-29, apply to plan 4 and are cited there.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (create)
- `PlacementRequest` — add — a frozen dataclass: the resolved repo, the authorization's
  `staged_tree_sha256`, the leg name, and the round id. It carries no vendor or transport
  fields, so no backend's API shape reaches the core types.
- `PlacementReceipt` — add — a frozen dataclass:
  - `kind` (`staged` | `executed`), `backend` (a registered name), `sandbox_ref` (an opaque
    string the backend chooses) and `snapshot_sha256`;
  - `attested_by` (`runtime` | `backend`), which is `runtime` only when this process performed
    the step itself;
  - `details`, a closed, backend-declared mapping for things like an image identity.
- `PlacedSandbox` — add — the backend name, the location string (for evidence only), the
  local tree path or `None`, the receipts, and the `enforced` capability declaration (below).
- `PlacementBackend` (a `Protocol`) — add — `name`, `available(timeout_s) -> Availability`,
  `place(request, review_dir) -> PlacedSandbox`, `release(placed)`, and
  `capabilities() -> frozenset[str]`.
  - The capability vocabulary is closed: `filesystem_confined`, `network_filtered`,
    `uid_isolated`, `bounding_set_empty`, `resource_bounded`, `credential_free`.
  - Each backend declares only what it enforces, so a later cloud adapter cannot over-claim by
    omission.
- `LocalBackend` — add — wraps **exactly** today's calls, in today's order: `ensure_staging_space`,
  `stage_review_tree`, the rename with the path tracked across it, and `mark_as_sandbox`.
  - `release` performs today's `remove_review_stage`.
  - It emits one `staged` receipt, `attested_by="runtime"`.
  - It does not move revalidation, egress or launch. Those stay in `_default_spawn` in their
    current order.
- `register_backend(scheme, factory)` / `resolve_backend(location)` — add — a registry keyed by
  location scheme. It holds only local in this plan. `https://` and cloud schemes resolve to
  **unregistered**, and later plans register them.
- `PlacementUnavailable(code, reason)` — add — the typed pre-launch failure every backend
  raises. It is the only path to a fallback.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `SandboxLocation` / `parse_location` — modify:
  - add a `scheme` field: `local`, `hostpath` (the legacy `host:path` form), or a URL scheme
    such as `https`, `e2b` or `modal`;
  - bare paths and Windows drive letters parse exactly as today;
  - `SandboxLocation.__str__` renders a URL location without any userinfo or query, so a
    credential can never reach evidence.
- `select_sandbox_root` — modify — a location whose scheme has **no registered backend** is not
  probed: no `ssh` and no network call. It falls back to local, with reason
  `"<scheme> placement backend not available in this runtime"` and a `RuntimeWarning`. The
  legacy `hostpath` probe and floor behaviour stay as they are today; follow-on plan 2 decides
  its disposition (RD6).
- `remote_required()` — add — reads `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED` in the same style
  as `sandbox_enabled()`. When it is true and the selection fell back, placement raises
  `PlacementUnavailable` instead of staging locally.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_default_spawn` — modify:
  - PI:8484–8516 become `resolve_backend(...)` then `backend.place(...)`. For local, this is a
    byte-for-byte equivalent call sequence.
  - `staged_tree_path` comes from `placed.local_tree`.
  - The `finally` calls `backend.release(placed)` in place of the direct `remove_review_stage`.
  - The mkdtemp and resolve, both revalidations, the egress acquisition, launch and
    `rmtree(base)` are unchanged, in the same order.
  - `PlacementUnavailable` under `remote_required()` refuses the leg before any provider effect.
- `_record_sandbox_facts` — modify — its signature takes the `PlacedSandbox`:
  - keeps every existing field, and `sandbox_root_host` keeps its current meaning;
  - adds `sandbox_placement_backend`, `sandbox_placement_receipts` (kinds and `attested_by`
    only, plus the `snapshot_sha256`) and `sandbox_placement_enforced` (the declared
    capabilities);
  - `sandbox_root_applied` becomes: a `staged` receipt from the **selected** backend exists
    **and** (local backend ⇒ today's `path == staged_at.parent` rule). For local this gives the
    same truth table as today. It can never be true for a backend that produced no receipt;
  - `sandbox_root_unapplied_reason` carries the fallback reason from `select_sandbox_root`
    instead of the fixed agent-harness#896 sentence, whenever one exists;
  - the contextvar reset-token discipline is unchanged.
- `_HARNESS_DETAIL_CODES` — modify — add exactly one fixed code,
  `"sandbox_placement_required_unavailable"`, raised as the exception message when
  `remote_required()` refuses. It flows through `_exception_failure`'s exact-equality branch
  (around PI:2508).

  **Frozen-vocabulary note.** The `detail` vocabulary is closed by the agent-harness#1102
  decision recorded at PI:2115–2130 ("`PanelLegResult.detail` is built ONLY from our own closed
  vocabulary … a HARNESS CODE — a fixed string this runtime itself emits
  (`_HARNESS_DETAIL_CODES`)"). This plan adds one member by the mechanism that comment defines.
  It adds no template, no parametrized code and no new category.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)
- `verify_broker` closed key set — modify, **conditionally**. The implementer first builds a
  sandboxed brokered record with today's code and runs the verifier on it.
  - If today's `sandbox_*` keys already reach `verify_broker`, add the three new keys beside
    them, and add a check that `sandbox_root_applied` is true only with a `staged` receipt.
  - If they never reach it, leave the verifier untouched and record that finding in the PR
    body.

  The recon could not settle which case holds (the facts are merged into `broker.evidence`,
  around PI:8693), so this plan does not assume either.

### `phase-loop-runtime/tests/test_sandbox_placement.py` (create)
- The falsifiers listed under "Verification", each with a named mutation.

### `phase-loop-runtime/tests/test_sandbox_egress.py` (modify)
- The source-grep, around lines 605–606 — modify — to accept the launch site's new
  `_record_sandbox_facts(` call shape. The existing assertions on `root_applied`, `staged_at`,
  `sandbox_root_host` and the unapplied reason are kept. The reason text is asserted by prefix
  only where it now carries the selection reason.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — document
  the placement seam and the three new evidence fields. State that `sandbox_root_applied` is
  receipt-derived, and that a backend's receipts with `attested_by="backend"` are claims and
  never receipt-class on their own.
- `docs/phase-loop/convergence-runtime.md` — modify:
  - `PHASE_LOOP_SANDBOX_ROOT` accepts URL-scheme locations that fall back with a recorded reason
    until their backend exists;
  - `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED` fails closed.
- `CHANGELOG.md` — modify — the placement seam, the new evidence fields and the fail-closed knob.
  A `panel_invoker.py` / `sandbox_policy.py` change drifts the agy pin set, so the next release
  cut requalifies agy; note that.

## Dependencies & order
1. **Rebase over agent-harness#1161 first**, if it has merged. It changes the local staging
   root (`staging_root()`), and `LocalBackend` must wrap whatever `_default_spawn` stages into
   at rebase time. If #1161 has not merged, land this first; #1161 then rebases onto
   `LocalBackend.place` as a one-site change.
2. `sandbox_placement.py` types and the `LocalBackend` wrapper come before `_default_spawn`
   consumes them.
3. The `sandbox_policy` scheme parse and `remote_required()` come before the `_default_spawn`
   fallback branch.
4. The verifier investigation comes before the evidence-field change is finalized.
5. Tests are written first with skip-guards on the new symbols, and each gets a RED receipt.

This plan does **not** depend on agent-harness#1132 or agent-harness#1071. It touches none of
their named `panel_invoker.py` sites except `_default_spawn` and `_record_sandbox_facts`;
re-check both at rebase.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_sandbox_placement.py tests/test_sandbox_egress.py tests/test_sandbox_policy.py \
  tests/test_sandbox_retention.py tests/test_seat_host_uid_1098.py \
  tests/test_review_monitor_policy.py tests/test_harden_evidence_producer.py \
  tests/test_review_stage_board_findings.py tests/test_sandbox_preamble.py \
  tests/test_panel_invoker_timeout_argv.py tests/test_panel_tui_workspace_trust_223.py
```

Falsifiers in `tests/test_sandbox_placement.py`. Each has a control-green receipt and a
named mutation that must turn it red:

- **Local equivalence.**
  - Record the call order of `ensure_staging_space`, `stage_review_tree`, rename,
    `mark_as_sandbox`, `_revalidate_staged_tree`, `revalidate_review_isolation_authorization`,
    `isolated_network` and `remove_review_stage` with and without the seam.
  - The sequences are identical, and so are the provider argv and `provider_cwd_sha256`.
  - Mutation: call `mark_as_sandbox` before the rename.
- **An unregistered scheme never probes.**
  - With `PHASE_LOOP_SANDBOX_ROOT=https://example.invalid/x` or `e2b://tpl`, a `subprocess` spy
    records no `ssh`, and a socket spy records no connect.
  - The leg stages locally with `sandbox_root_fell_back=True`, a reason naming the scheme, and
    `sandbox_root_applied=True` for the local receipt.
  - Mutation: route unknown schemes to `_probe_root`.
- **Receipt-derived `applied`.** A fake registered backend that returns a `PlacedSandbox`
  with no `staged` receipt yields `sandbox_root_applied=False` and an unapplied reason.
  Mutation: derive `applied` from the selection.
- **Fail closed.** `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED=1` with an unregistered scheme ends
  the leg with detail `sandbox_placement_required_unavailable`, with zero provider spawns
  (spawn-seam counter) and no local stage directory. Mutation: ignore `remote_required()`.
- **No credential in evidence.** `https://user:tok@host/p?k=v` is recorded as
  `https://host/p` in every sandbox field. Mutation: `str(location)` with userinfo.
- **Vocabulary.** The new code is a member of `_HARNESS_DETAIL_CODES`, and
  `_finalize_leg_detail` passes it through unchanged.

Edge cases:
- A Windows drive-letter root still parses as local.
- A `hostpath` root keeps today's probe and `applied=False` record, byte-identical.
- With nothing configured, no probe runs, and the goldens and argv tests above stay green.

Run the suite on a tree **left untouched** for its duration.

## Acceptance criteria
- [ ] With no `PHASE_LOOP_SANDBOX_ROOT`, the local-equivalence falsifier shows an identical
  placement call order, provider argv and `provider_cwd_sha256` before and after the seam.
  Every test file named in `automation.suite_command` passes.
- [ ] With `PHASE_LOOP_SANDBOX_ROOT=https://example.invalid/x`, the leg record shows the
  following, and the `ssh` and socket spies record zero calls:
  - `sandbox_placement_backend="local"`;
  - `sandbox_root_fell_back=True`, with a reason naming `https`;
  - a `staged` receipt with `attested_by="runtime"`.
- [ ] A fake backend that returns no `staged` receipt yields `sandbox_root_applied=False`.
  Mutating `applied` to derive from the selection turns
  `test_sandbox_placement.py::test_applied_requires_staged_receipt` red.
- [ ] With `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED=1` and an unregistered scheme, the leg ends
  with detail `sandbox_placement_required_unavailable` and the spawn-seam counter reads 0.

## Follow-on plans

Each is its own bounded detailed plan, written after the one before it lands. They are listed
here so the seam above is designed against them. They are not planned in detail here.

### Plan 2: egress allowlist without fleet addresses (small, independent)
- **Scope.** `sandbox_policy._INFERENCE_ALLOW` hard-codes one private address on ports 8020 and
  3131, which the consumer comment names. Replace it with `PHASE_LOOP_SANDBOX_EGRESS_ALLOW`
  (`host:port`, comma-separated, default empty). Add a static test: no private or CGNAT
  **host** address literal appears in product code. CIDR network constants and the slirp range
  are exempt.
- **Dependencies.** None; it can land before or after plan 1. Our fleet's value is set in
  deployment config later, as a maintainer-gated step.

### Plan 3: self-hosted remote backend over authenticated HTTPS
- **Scope.**
  - The agent: `phase-loop sandbox-agent serve`, in the same wheel and Linux-only. It fails
    closed. It is registered for `https://`.
  - The client: stdlib TLS with no insecure mode, and no `ssh` spawned.
  - A version and profile handshake.
  - Snapshot streaming. The agent recomputes `review_tree_manifest_sha256`, which must equal the
    authorization's `staged_tree_sha256`.
  - Per-principal workspaces, and a subordinate uid per seat.
  - A cgroup v2 scope per seat: `memory.max`, `pids.max`, `cpu.max`, and a disk bound (RD5).
  - A heartbeat lease with an fsynced journal, cancel, and a startup reaper for owner loss,
    agent restart and reboot.
  - The agent's own retention, floor and cap.
  - An attestation run inside the jail: the J6/J15 probe, the egress `enforcement_report`,
    cgroup values, and a nonce bound to the snapshot. It gates the leg but is never
    receipt-class.
  - The local runtime ingests output bytes under J10-equivalent checks and the token scan.
  - A qualification command, `sandbox-remote qualify <url>`.
- **Parity, per route.** Jailed legs (Claude, and Gemini if agent-harness#1132 L3 is in scope)
  get the full agent-harness#1132 jail. Codex and grok, only if RD3 (ii) is chosen, keep their
  current route: `CapBnd` exactly `SEAT_RETAINABLE_CAPS` (`setfcap`) for codex, and empty for
  grok. They run under a remote subordinate uid and keep `seat_filesystem_unconfined`.
- **Consumer prerequisites and their falsifiers:**

  | Prerequisite | Falsifier |
  |---|---|
  | Receipts | Staging and execution receipts are present, with zero local provider spawns. |
  | Per-user auth and workspace | Cross-principal list, get, cancel and reap are refused 403/404; concurrent seats have distinct uids. |
  | Bounds | A fork bomb stops at `pids.max`; an OOM kill stays inside the scope; the CPU is throttled; the disk bound is hit. |
  | Transport | `http://` is refused, a bad CA is refused, the `ssh` spawn count is 0, and the peer port is recorded. |
  | Cleanup | Cancel; client SIGKILL (the scope is gone within the TTL plus grace); agent restart (reaped from the journal). |
  | Retention | Below the floor, a typed refusal becomes a local fallback; over the cap, the oldest sandbox is reaped after `work/` is archived. |

- **Dependencies.**
  - It needs plan 1.
  - The substrate, qualified with a null workload, can land before agent-harness#1132.
  - Remote **jailed-seat** launch waits on agent-harness#1132, which waits on agent-harness#1071.
    It also needs the provider CLIs at their qualified pins on the target, with the #1132 probes
    replayed there.
  - Remote fallback lands on agent-harness#1161's disk-backed `staging_root()`.
- **Open decisions:** RD1–RD6 below.

### Plan 4: E2B cloud backend (first cloud adapter)
- **Scope.**
  - An `E2BBackend`, registered for the `e2b` scheme, in a lazily imported module.
  - The SDK is an optional extra, `phase-loop-runtime[e2b]`, following the existing `visual`
    extra pattern in `phase-loop-runtime/pyproject.toml`. The core install never imports `e2b`.
    The package is `e2b` on PyPI, version 2.51.0 on 2026-09-18, with 12 dependencies including
    httpx and protobuf ([pypi](https://pypi.org/project/e2b/),
    [pyproject](https://raw.githubusercontent.com/e2b-dev/E2B/main/packages/python-sdk/pyproject.toml)).
    Without the extra, the scheme is unregistered and plan 1's fallback applies.
- **Adapter rule.** Nothing E2B-specific enters `sandbox_placement.py`: no template, build,
  `allow_out` or timeout type. The E2B identity goes only into `PlacementReceipt.details`, under
  keys the adapter declares. A Modal or Daytona adapter is another `PlacementBackend`.

**Templates and image pinning.**
- The seat image is an E2B template built with the SDK `Template()` builder. The CLI
  `template init` is an alternative ([quickstart](https://docs.e2b.dev/template/quickstart)).
- `Template.build(...)` returns `BuildInfo(name, template_id, build_id)`
  ([build](https://docs.e2b.dev/template/build.md)).
- Tags can be moved, so the adapter pins `Sandbox.create("<name>:<build_id>")` and never a tag
  ([tags](https://docs.e2b.dev/template/tags.md)).
- E2B documents no content digest. The template therefore carries a runtime-written manifest
  with the hash of every toolchain binary and the CLI versions, built from the same pins as
  local seats. The in-VM attestation hashes it.
- Only `E2B_TEMPLATE_ID` is visible inside the VM
  ([env vars](https://docs.e2b.dev/sandbox/environment-variables.md)), and `SandboxInfo` has no
  `build_id`. So the receipt records the **requested** build id as `attested_by="runtime"`, and
  the manifest hash as `attested_by="backend"`, labelled as a claim.

**Snapshot upload with no credentials.**
- The adapter uploads the staged tree with `files.write_files` (a batch write)
  ([upload](https://docs.e2b.dev/filesystem/upload.md)).
- It never uses `sandbox.git.clone`, which could put credentials into the sandbox through
  `dangerouslyStoreCredentials` ([git](https://docs.e2b.dev/sandbox/git-integration.md)).
- The in-VM attestation recomputes the tree digest. A mismatch refuses the leg before launch.
- E2B documents no size limit, so plan 4 measures one.

**Egress: what E2B can and cannot enforce against our `sandbox_egress` policy.** E2B filters
at an egress proxy outside the VM, through `network={"allow_out", "deny_out"}` with IPs, CIDRs
and domains. `allow_internet_access=False` is equivalent to `deny_out=["0.0.0.0/0"]`
([internet access](https://docs.e2b.dev/sandbox/internet-access),
[network](https://docs.e2b.dev/network/internet-access.md)).

| Our guarantee | E2B | Behaviour |
|---|---|---|
| Deny RFC 1918, CGNAT, link-local and metadata | **Can**, by listing those CIDRs in `deny_out`. The docs do not state the default, so it is proven per sandbox, not assumed. | The pre-launch in-VM connect probe to each range must fail. If any connect succeeds, the leg is refused before launch. |
| Allow the public internet | **Can** (the default). | Probed: one public name resolves and a public host answers. |
| `host:port` allowlist into a private network | **Cannot**. Domain rules apply only on ports 80/443, there is no per-port rule, and "allow beats deny", so an allow entry would reopen a denied range. The operator's private network is unreachable from the cloud anyway. | A leg whose policy needs a non-empty private allowlist is refused cloud placement with a typed code, and falls back or fails closed per plan 1. |
| Loopback services unreachable | **Not applicable** in the same way. The VM's loopback holds only E2B's in-VM daemon, and none of the operator's services. | Recorded as a difference; nothing to enforce. |
| UDP/QUIC and DNS | **Partly.** QUIC is not domain-filtered, and domain rules auto-allow `8.8.8.8` for DNS. | The adapter uses CIDR rules only, never domain rules. The residual is recorded. |
| Enforcement authority | E2B's proxy, which the runtime cannot observe. | The in-VM probe result is `attested_by="backend"`, never receipt-class. |

**Confinement parity with the agent-harness#1132 jail.** Each sandbox is a Firecracker
microVM with its own kernel
([security](https://docs.e2b.dev/faq/security-and-compliance.md)). What it gives instead of
each jail item:

| Jail item | What E2B gives | Parity |
|---|---|---|
| Operator filesystem unreachable (J1/J2) | The VM holds none of the operator's files. | **Stronger** |
| No sibling access (J4) | One sandbox per seat, each its own VM. | **Stronger** |
| Subordinate uid (J15, D8) | The default user is `user` ([user](https://docs.e2b.dev/template/user-and-workdir.md)). Passwordless sudo is reported by third parties, not by E2B's docs. Inside the VM, a uid is not the boundary. | **Not equivalent.** The template can remove sudo and run the seat under a dedicated uid; the attestation proves it. |
| `CapBnd = 0` (J6, agent-harness#999) | Achievable inside the VM with `setpriv --bounding-set=-all`, if the template ships util-linux. | Achievable; probed per sandbox |
| Codex keeps `CAP_SETFCAP` for its nested bwrap | Depends on unprivileged user namespaces in the guest kernel (6.1 LTS, [how it works](https://docs.e2b.dev/template/how-it-works.md)). Not documented. | **Unknown.** Measured in plan 4; if absent, codex is refused cloud placement. |
| Seccomp J14 | Only if bwrap runs inside the guest. Not documented. | **Unknown**; measured |
| No credentials in the sandbox | The E2B API key is not among the documented in-VM variables. Seat CLIs need subscription credentials. | See CD1 |
| Code confidentiality | The tree, the output and any credential are visible to a third party (E2B). | **New residual.** See CD2 |
| Exact snapshot, local outcome authority | The same as plan 3. | Equal |

**Limits, cost and cleanup.**

| Plan tier | vCPU | RAM | Disk | Max lifetime |
|---|---|---|---|---|
| Hobby | 8 | 8 GiB | 10 GiB | 1 h |
| Pro | 8+ | 8+ GiB | 20+ GiB | 24 h |

- The defaults are 2 vCPU / 512 MiB and a 5-minute timeout, with kill on timeout. Billing is
  per second while a sandbox runs ([billing](https://docs.e2b.dev/billing.md),
  [lifetime](https://docs.e2b.dev/faq/sandbox-lifetime.md)).
- Paused sandboxes are kept until killed ([persistence](https://docs.e2b.dev/sandbox/persistence.md)).
- **How the adapter avoids leaking paid sandboxes:**
  - It **never** uses `on_timeout="pause"` or auto-pause.
  - It creates each sandbox with `timeout = lease_ttl` and extends it with `set_timeout` as the
    heartbeat. When the owner dies, E2B's own timer kills the VM whether or not the client is
    alive.
  - It tags every sandbox with metadata: owner id, round id, leg and runtime version
    ([metadata](https://docs.e2b.dev/sandbox/metadata.md)).
  - It runs a reaper at startup and periodically. The reaper uses
    `Sandbox.list(metadata={"phase_loop_owner": …})`
    ([list](https://docs.e2b.dev/sandbox/list.md)) and kills every sandbox with no live local
    lease.
  - It calls `kill()` in the backend's `release`.
- **Falsifiers.**
  - With a fake SDK: SIGKILL of the client leaves `list()` empty after `lease_ttl` plus grace.
    Mutations: create with a 24-hour timeout; `on_timeout="pause"`; the reaper skips the
    metadata filter.
  - Live, in the plan 4 qualification: the same, against a real project, with billed seconds
    recorded.
- **Cost caps** are a maintainer decision (CD3). E2B's own concurrency limits are 20 on Hobby,
  and from 100 on Pro.

**The E2B API key.**
- It is read only from the local runtime's environment (`E2B_API_KEY`) or a 0600 config file,
  and passed only to the SDK constructor.
- A falsifier scans every `commands.run` env, every uploaded byte, the evidence and the leg
  logs for the key.
- Keys are scoped to one project, with no per-key restriction documented
  ([projects](https://docs.e2b.dev/projects.md)). So the operator docs recommend a dedicated
  E2B project for harness sandboxes, which also bounds the blast radius and the plan limits.
- Evidence records the project name and never the key.
- Secured envd access (the `X-Access-Token`) stays on, the SDK v2 default
  ([secured access](https://docs.e2b.dev/sandbox/secured-access.md)).
- Public port exposure is not used. If it ever is, it uses `allow_public_traffic=False`
  ([restrict public access](https://docs.e2b.dev/network/restrict-public-access.md)).

**Evidence.**
- Receipts:
  - `staged`, with the sandbox id returned by `create`;
  - `executed`, from the command handle;
  - the requested `name:build_id`, the reported `E2B_TEMPLATE_ID`, the template-manifest hash
    and the in-VM egress probe result.
- `sandbox_root_applied` is true only when the `staged` and `executed` receipts share one
  sandbox id and the spawn-seam counter reads 0.
- Everything E2B reports is `attested_by="backend"`, and remote output is never receipt-class
  by itself. The local runtime ingests the bytes under J10-equivalent checks.

**Seat CLIs in E2B.** claude, codex and agy all need subscription credentials, which conflicts
with "no credentials in the sandbox". The options are CD1 below. E2B also documents secret
injection at its egress proxy ([network](https://docs.e2b.dev/network/internet-access.md)),
which keeps a secret out of the VM but not away from the vendor.

**Dependencies.**
- It needs plan 1.
- It needs plan 3's attestation checker, output ingestion and lease model, which are reused and
  not rebuilt. Plan 3's substrate lanes must land first.
- Any seat workload inside E2B also waits on agent-harness#1132, and on CD1.

## Open maintainer decisions (not ruled here)

RD numbers belong to plan 3 and CD numbers to plan 4; plan 1 needs none. Each recommendation
is the planner's.

- **RD1 Remote server process model.**
  - **(a) Recommended:** one agent per user, as a systemd user service behind the host's HTTPS
    proxy. Separation between principals is then enforced by the OS.
  - (b) One multi-tenant daemon under a dedicated account, with its subuid range partitioned.
    Simplest to run, but separation rests on agent code.
  - (c) A socket-activated worker per request. The leases and the journal need separate
    state.
  - (d) A container runtime, agent-harness#891, which is still deferred.
- **RD2 Remote authentication.**
  - **(a) Recommended:** a per-principal bearer token, with the server storing only its hash,
    and an optional server-certificate pin.
  - (b) mTLS. Proxies make it fragile.
  - (c) A proxy identity header. Deployment-specific.
  - (d) SSH-key request signing, without an SSH transport.
- **RD3 v1 scope.**
  - Workloads:
    - **(a) Recommended:** board seats only.
    - (b) plus read-only executor legs.
    - (c) plus writing executors.
  - Legs:
    - (i) jailed legs only.
    - **(ii) Recommended:** also codex and grok, on their current route under a remote
      subordinate uid.
- **RD4 How the seat credential reaches a self-hosted remote.**
  - **(a) Recommended:** forwarded per leg into the J3 token pipe, never persisted, plus a
    signed attestation.
  - (b) A remote-resident credential.
  - (c) Inference local and execution remote: the SBXEXEC design, agent-harness#848.
- **RD5 Disk bound.**
  - **(a) Recommended:** project quotas, with a watchdog as the typed degraded mode.
  - (b) A watchdog only.
  - (c) A filesystem per principal.
- **RD6 The legacy `host:path` SSH form.**
  - **(a) Recommended:** record-only, with a typed notice.
  - (b) An optional SSH adapter later.
  - (c) A configuration error.
- **CD1 Seat CLI credentials in the cloud.**
  - **(a) Recommended for v1:** cloud runs only **credential-free** workloads. That means reviewed
    code execution: the agent-harness#848 executor role, such as a seat's test and falsifier
    runs. Seat CLIs stay local or on a self-hosted remote.
  - (b) The CLI runs locally and only tool execution goes to E2B, through a harness-owned tool
    bridge. This is SBXEXEC, a larger design.
  - (c) A brokered credential proxy: the VM gets a short-lived, revocable capability, and a proxy
    the runtime controls injects the real credential. The proxy must be reachable from the cloud,
    and the subscription CLIs must support routing through it; neither is established.
  - (d) The credential is forwarded into the VM, or injected by E2B's egress proxy. The credential
    then leaves our custody to a third party. This contradicts "no credentials in the sandbox"
    for (d)-forwarded.
- **CD2 Acceptable confinement gaps in the cloud.** Code confidentiality toward the vendor, the
  in-VM uid not being a boundary, codex's `CAP_SETFCAP` nested sandbox where the guest cannot
  support it, and seccomp J14.
  - **(a) Recommended:** refuse cloud placement for any leg whose gap is not closed by
    measurement, and require a per-repository opt-in acknowledging vendor visibility.
  - (b) Accept the recorded gaps globally.
  - (c) Cloud only for public repositories.
- **CD3 Cost caps.**
  - **(a) Recommended:** per-run caps on concurrent cloud sandboxes and total sandbox-seconds,
    plus a per-day ceiling in the operator config. Exceeding a cap refuses before create, with a
    recorded reason, then falls back or fails closed.
  - (b) Rely on E2B's plan limits only.
  - (c) Per-run caps only.
- **CD4 Cloud opt-in granularity.**
  - **(a) Recommended:** off by default, enabled per run by configuration, with a per-seat
    allowlist of eligible legs.
  - (b) Per board preset.
  - (c) Per seat only.

## Execution Policy

- execute: effort=high, reason=refactor of the attested launch site and its evidence record; a
  behaviour-preserving seam whose falsifiers must prove byte-identical local placement
