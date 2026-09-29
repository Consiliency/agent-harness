---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 3c61b270
related_issues: [agent-harness#896, agent-harness#848, agent-harness#891, agent-harness#895, agent-harness#1132, agent-harness#1147, agent-harness#1161, agent-harness#1071, agent-harness#999, agent-harness#1102, agent-harness#1109, agent-harness#1140]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python -m pytest -q phase-loop-runtime/tests/test_remote_sandbox_location.py phase-loop-runtime/tests/test_remote_sandbox_transport.py phase-loop-runtime/tests/test_remote_sandbox_agent.py phase-loop-runtime/tests/test_remote_sandbox_lease.py phase-loop-runtime/tests/test_remote_sandbox_bounds.py phase-loop-runtime/tests/test_remote_sandbox_evidence.py phase-loop-runtime/tests/test_sandbox_policy.py phase-loop-runtime/tests/test_sandbox_retention.py phase-loop-runtime/tests/test_review_leg_sandbox.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: remote placement of review-seat sandboxes over authenticated HTTPS (agent-harness#896)

Status: first revision for board and president review. This is a planning artifact only: no
source file changes. Six design decisions (RD1–RD6) are open and belong to the maintainer; the
plan names options and a recommendation for each and rules none of them.

## Task

agent-harness#896: a configured remote sandbox root is probed and measured, then the sandbox
is staged and run locally anyway. Close that gap as a **general product feature**. Any operator
can point the runtime at a larger Linux host they control. The runtime then stages the
exact reviewed snapshot there, runs the seat there under confinement at least equal to the
local agent-harness#1132 jail, bounds its CPU, RAM, PIDs and disk, and cleans it up. The
local runtime keeps the outcome authority. If the remote is unavailable, the round falls back
to local with a recorded reason, or fails closed if the operator asked for that.

Motivation, for context only: hosts with little RAM and a tmpfs `/tmp` get OOM-killed by
seat processes (agent-harness#1147). Nothing below names a fleet host, path or address. Our
own deployment (grants, endpoint, tokens) is a separate, later, maintainer-gated step.

## Inputs observed at `input_base_commit`

These are inputs, not outputs.

- **Selection without placement.** `sandbox_policy.select_sandbox_root` returns a
  `SandboxRootChoice`. `panel_invoker._default_spawn` passes it only to
  `_record_sandbox_facts`, and stages with `review_stage.stage_review_tree(resolved_repo_dir,
  review_dir)` under a local `mkdtemp(prefix="pl-panel-")`. `ensure_staging_space` measures
  that local directory.
- **Evidence today.** `_record_sandbox_facts` computes
  `applied = root_choice.host is None and root_choice.path == staged_at.parent`. A remote root
  can therefore never be `applied`, and an unapplied choice carries
  `sandbox_root_unapplied_reason` naming agent-harness#896. The facts live in the
  `_SANDBOX_ROUND_FACTS` contextvar, and the function returns a reset token the caller must
  use.
- **SSH in product code.** `parse_location` reads `host:path` as remote.
  `_probe_root` and `_free_bytes_at` then spawn `ssh -o BatchMode=yes`. The
  consumer's host contract denies SSH, so this path always fails there.
- **Fleet address in product code.** `sandbox_policy._INFERENCE_ALLOW` hard-codes one private
  address on ports 8020 and 3131, and `EgressPolicy.allow` defaults to it. The consumer comment
  on agent-harness#896 names this; its supported route is HTTPS 443.
- **Two staging paths.** `review_stage.stage_review_tree` (board seats: shallow clone at
  HEAD overlaid with the working tree) and `launcher._stage_review_tree` (executor review
  legs: gitignore-aware copy without `.git`). The seat stage is bound by the authorization's
  `staged_tree_sha256` and re-checked by `advisor_board.backing._revalidate_staged_tree`.
- **Egress.** `sandbox_egress.isolated_network` holds a user+net namespace with
  `slirp4netns` and in-namespace `iptables`. `SEAT_RETAINABLE_CAPS = {"setfcap"}`, applied by
  `retain_bounding_caps`, is the only bounding-set exception (the agent-harness#999
  invariant, for the sandboxed codex seat's nested bwrap).
- **HARDEN broker.** `advisor_board/backing.py` runs the parent-side broker under
  `bwrap --unshare-all --clearenv` with the staged dir bound read-only. It requires Linux and
  `/usr/bin/bwrap`, and fails closed otherwise.
- **Executors.** `launcher.launch` execs `lease_supervisor.py` (agent-harness#1140, merged as
  agent-harness#1142). The supervisor is a subreaper that holds the lease until the executor
  tree is gone.
- **Retention.** `sandbox_retention` provides `mark_as_sandbox`, `discover` and `reap`
  (TTL, size ceiling, archive before reap).
- **Closed vocabulary.** `panel_invoker._HARNESS_DETAIL_CODES` (agent-harness#1102).
- **Pending, not on main.** Draft agent-harness#1161 (fixes agent-harness#1147) adds
  `sandbox_policy.staging_root()` (a disk-backed local staging root), relative caps, and
  `fill_child_tmp_env`. It deliberately does not reuse `PHASE_LOOP_SANDBOX_ROOT` for local
  placement, because this issue's evidence semantics hang on it.
- **Decided, not implemented.** The agent-harness#1132 plan
  (`plans/detailed-seat-sandbox-permissions-1132-20260928.md`) defines the seat jail, J1–J15,
  and D1–D8 (D8: a leased subordinate uid via `newuidmap`/`newgidmap`). Its implementation
  waits on agent-harness#1071. Under its D1, Claude and Gemini are jailed; codex and grok stay
  on their current routes with `seat_filesystem_unconfined` until agent-harness#895.
  *Planner's observation, not stated there:* the J14 filter denies `CLONE_NEWUSER`, which
  codex's own nested bwrap needs, so codex cannot simply enter that jail.

## Architecture: where the split is

One paragraph carries the design. **The local runtime keeps every decision; the remote agent
only executes.**

- **Local runtime keeps:** the public-entry authorization and its revalidation, bundle and
  brief rendering, round-level root selection, verdict parsing, the output token scan,
  every leg record and all evidence, and the retention *policy*.
- **Remote agent does:** receive the snapshot, verify its digest, build the jail, run the
  provider, and return the output bytes together with an attestation.

The remote agent is a new entry point, `phase-loop sandbox-agent serve`, in the **same wheel**.
It runs the same post-authorization leg-execution function the local path runs. This plan
factors that function out of `_default_spawn` as a named seam, taking a serializable leg
spec. Parity is therefore "the same code, a version handshake, and an attestation", not a
second implementation. The client refuses an agent whose runtime version differs from its own,
or whose jail profile digest has no recorded EC-EXECFIND-2 falsifier pass. The digest is
never compared with the client's own: a macOS or Windows client has no jail, and the J14
filter is built per host architecture.

- **Client side** stays OS-neutral, stdlib only (`http.client`, `ssl`). A macOS or Windows
  operator can use a remote Linux root. That is the co-location argument of agent-harness#891,
  now carried over HTTPS instead of SSH.
- **Agent side** is Linux-only and fails closed, exactly like the HARDEN broker.

**A request can never widen anything on the server.** This is a design rule, not a decision:
- The effective egress allowlist is the server's configured policy intersected with the
  client's request.
- Retainable capabilities are the server's `SEAT_RETAINABLE_CAPS`, whatever the request says.
- Resource limits are the server's maxima, clamped, never raised by a request.
- The server rejects unknown request fields.

## Invariants (each has a named falsifier in "Tests")

- **R1 Placement is real.** For a leg recorded as remote, the remote agent staged the snapshot
  and ran the provider, and the local spawn seam launched **zero** provider processes for
  that leg. For a leg recorded as local, no remote session exists for it.
- **R2 Exact snapshot.** The unit transferred is the staged review tree whose
  `review_tree_manifest_sha256` equals the authorization's `staged_tree_sha256`. It is not a bare
  commit SHA: the stage overlays the working tree. The client streams the tree built by
  the same selection logic as `stage_review_tree`. The agent recomputes the digest with the
  same function before any launch, and refuses on mismatch with
  `sandbox_remote_refused:snapshot_digest`. The client never stages a second, unbound copy.
- **R3 Confinement parity, per route.** A remote seat is at least as confined as the same
  leg's route run locally. For every route, these hold:
  - the egress namespace and policy, applied in the **remote** host's namespace;
  - no credential channel beyond the local route's declared set;
  - the agent-harness#1161 child-temp fill applied on the remote host.

  Per route:
  - **Jailed legs** (Claude, and Gemini if agent-harness#1132 L3 is in scope) get the
    agent-harness#1132 jail: J1–J4 and J10–J15, the subordinate uid, `CapBnd = 0`, and J3's
    credential channels.
  - **Codex and grok**, only if RD3 (ii) is chosen, keep their **current** route: `CapBnd`
    exactly `SEAT_RETAINABLE_CAPS` (`setfcap`) for codex, and empty for grok, and nothing
    wider. They also run under the principal's subordinate uid on the remote, which is
    strictly more confined than their local route under the operator's uid. They are **not**
    jailed, and their records keep `seat_filesystem_unconfined`.

  How the remote proves it is under "Attestation".
- **R4 Outcome authority stays local.** Remote output is **never** a receipt-class artifact
  by itself.
  - The local runtime ingests the returned bytes under J10-equivalent rules: regular bytes,
    a size cap, and the token scan. Only then does it build the leg record.
  - Remote-supplied facts are stored under `remote_attestation`, and no gate, verifier or
    closeout reads that field as satisfying a condition.
  - `verify_harden_evidence.py` keeps reporting EC-HARDEN-5 as UNMET on remote tooled
    records, as it does locally.
- **R5 Transport.** The only product transport is HTTPS with certificate verification:
  - A remote root is a URL: `PHASE_LOOP_SANDBOX_ROOT=https://<host>[:port]/<prefix>`.
  - `http://` is refused, except to a loopback address under an explicit test-only flag.
  - There is no option to disable verification. A custom CA bundle and an optional pinned
    server certificate fingerprint are the only knobs.
  - When a URL root is configured, the client never spawns `ssh`.
- **R6 Per-principal isolation.** Every request is authenticated to one principal (RD2).
  - One principal cannot list, read, cancel, reap or connect to another principal's
    sandboxes: the response is 403 or 404, with no existence oracle.
  - Seats of different principals, and concurrent seats of one principal, hold distinct
    subordinate uids.
  - Each principal's workspace is a private directory, mode 0700.
- **R7 Bounds.** Every remote seat runs in its own cgroup v2 scope, with `memory.max`,
  `memory.swap.max`, `pids.max` and `cpu.max` from the server's maxima, and a disk bound
  (RD5).
  - Exceeding a bound kills or refuses **that seat only**, and the leg ends with a typed code.
  - The agent and other seats survive.
- **R8 Lifecycle.** A remote seat lives only while its owner holds a lease.
  - **Heartbeat.** The client renews every `lease_ttl/3`. With no renewal for `lease_ttl`, the
    agent kills the seat's cgroup (`cgroup.kill`).
  - **Cancel.** An explicit DELETE kills the seat within the grace period.
  - **Journal.** The agent writes every lease to an on-disk journal, fsynced before the
    seat launches. On start it kills and reaps every scope and sandbox whose lease is not
    live. That covers an agent crash, an agent restart and a host reboot.
  - **Local owner.** On the local side the lease is held by the leg's own process, so local
    owner loss (SIGKILL, OOM, reboot) stops the heartbeat by construction.
- **R9 Remote retention.** The agent enforces its own free-space floor and total cap on its
  own filesystem, using `sandbox_retention` locally on that host.
  - Below the floor it refuses staging with `sandbox_remote_refused:below_floor`. That is
    before launch, so it falls back.
  - It reaps oldest-first over the cap, archiving `work/` before reaping.
  - The client never reaps remotely and never measures remote space itself.
- **R10 Honest evidence.** `sandbox_root_applied` and `sandbox_staged_at` state where the
  sandbox **ran** (see "Honest evidence"). The current record-only behaviour never regresses
  into naming a host that was not used.
- **R11 Recorded fallback, optional fail-closed.** See "Fallback". There is never a silent
  fallback, and never a relaunch after a remote provider launch.
- **R12 General product.** No product file names a fleet host, address, path, port or
  marker. A static test enforces it; see "Tests".

## Attestation: how the remote proves R3

The agent returns an attestation, collected **inside** the jail it just built, before the
provider launches. It runs the agent-harness#1132 J6/J15 identity probe through the exact jail
prefix and records:

- the uid and gid, and that they fall in the principal's partition;
- `CapPrm/CapEff/CapInh/CapAmb`, `CapBnd`, `NoNewPrivs`, and `Seccomp` with the filter digest;
- the in-jail `mountinfo` digest against J1, and the declared fd set;
- the `sandbox_egress.enforcement_report` for the remote namespace;
- the cgroup limit values read from inside the scope;
- the jail profile digest, the runtime version and the wheel `RECORD` digest.

The attestation is bound to a fresh client nonce and to the R2 snapshot digest.

**What the local runtime checks.** It refuses the leg, before trusting any output, unless
all of these hold:
- the version and wheel digest equal its own;
- the jail profile digest has a recorded EC-EXECFIND-2 falsifier pass (the obligation the
  agent-harness#1132 plan records);
- every field equals the expected value for the leg's route;
- the nonce and digest match.

**What this does not prove, stated plainly.** An attestation is the remote agent's *claim*
about a kernel the local runtime cannot observe. The trust root is the remote host's
operator and the authenticated channel (RD2), with the signing under RD4 if chosen.
That is why R4 holds: an attestation gates whether the leg may proceed, and is never a
receipt. The new residual adds to the agent-harness#1132 D3 residual under agent-harness#361,
and does not replace it:
- **Remote root.** Root on the remote host can read the seat credential, the snapshot and
  the output.
- **Agent compromise.** A compromised agent can lie in the attestation.

## Consumer prerequisites and their falsifiers

The agent-harness#896 consumer comment lists six prerequisites. Each maps to invariants and a
falsifier. Every falsifier has a control-green receipt and a named mutation that turns it red,
following the agent-harness#1132 convention.

| Prerequisite | Invariants | Falsifier (test) | Named mutation that must turn it red |
|---|---|---|---|
| Actual remote staging and execution receipts | R1, R2, R10 | A leg with a URL root yields a staging receipt (sandbox id, digest) and an execution receipt, and the local spawn seam counts zero provider launches. A pre-launch remote failure yields a local record with the fallback reason and no remote claim. | Record `applied=True` from the selection alone. Launch locally after a remote staging receipt. |
| Per-user auth and workspace | R6 | Principal A's credential gets 403/404 on B's sandbox for list, get, cancel, attach and reap. Two concurrent seats (same or different principal) show distinct attested uids. Workspace dirs are 0700 and owned per principal. | Drop the principal filter in the lookup. Lease the same uid twice. |
| CPU, RAM, PID and disk bounds | R7 | A fork bomb stops at `pids.max`. An allocator is OOM-killed in its scope while the agent and a sibling seat survive. A CPU spinner is throttled (`cpu.stat` `nr_throttled > 0`). A writer hits the disk bound. Each leg ends with its typed code. | Launch without the scope. Omit `pids.max`. Raise a limit from the request. |
| Exact authenticated transport | R5 | `http://` is refused. A wrong CA is refused. A fingerprint mismatch is refused. An unauthenticated request gets 401. With a URL root, the `subprocess` seam records no `ssh`. The live qualification record carries the peer address, port and TLS version actually used. | Set `check_hostname=False` or `CERT_NONE`. Fall through to the SSH probe. |
| Cancellation, owner loss and restart cleanup | R8 | DELETE kills within the grace period. SIGKILL of the client process leads to the scope being gone within `lease_ttl` plus grace. Killing the agent mid-seat and restarting it leaves no scope and no unjournaled directory. A lease journal entry is fsynced before launch. | The startup reaper skips journal entries. The heartbeat is renewed by a thread that outlives the leg. |
| Remote retention and free-space enforcement | R9 | Below the agent's floor, staging is refused with a typed code, and that becomes a local fallback with a reason. Over the cap, the oldest sandbox is reaped and its `work/` archived first. | Remove the floor check. Reap before archiving. |

The live half of each row, on a real target, is the qualification lane (L6). That lane uses
general tooling; this plan claims no numbers.

## Honest evidence

`_record_sandbox_facts` is extended, keeping its contextvar reset-token discipline:

- **New field `sandbox_placement`:** `local` or `remote`, per leg.
- **New fields `sandbox_remote_origin` and `sandbox_remote_sandbox_id`:** the URL
  origin only (never a credential or query), and the agent's id for the sandbox.
- **`sandbox_staged_at`:** for remote, `<origin>#<sandbox_id>:<agent-reported path>`. For
  local, it is unchanged.
- **`sandbox_root_applied`:**
  - For remote, it is true **iff** all of these hold: a staging receipt and an execution
    receipt are present for this leg, both carry the R2 digest, the attestation passed,
    and the local provider-spawn count is zero.
  - For local, it keeps today's rule.
- **`remote_attestation`:** stored beside the facts as a claim (R4).
- **`sandbox_root_unapplied_reason`:** stays whenever a root was selected and not used. Its
  text names the actual reason, not a fixed pointer to agent-harness#896.

**The legacy `host:path` form** keeps today's honest behaviour, record-only with
`applied=False`, until RD6 is ruled. It now also emits a typed notice
(`sandbox_remote_location_unsupported`), so the operator sees it and nothing is silent.

## Fallback

- **Selection.** Selection stays per round, as `select_sandbox_root`'s docstring requires. The
  URL probe is an authenticated `GET /v1/health`, bounded by the existing off-thread
  deadline. It returns the agent's version, profile digest and free space.
- **Default: local fallback, recorded.** If the probe fails or the agent refuses, the round
  goes local with `sandbox_root_fell_back=True`, a reason, and a typed notice
  `sandbox_remote_unavailable:<cause>`.
- **Local staging lands on agent-harness#1161's disk-backed `staging_root()`**, never on the
  RAM-backed temp dir. Without that, a fallback would bring back the tmpfs OOM that motivates
  this issue.
- **Per-leg, before launch.** A remote failure before the provider launches (a staging
  refusal, a digest mismatch, a failed attestation) sends **that leg** local, with its own
  reason.
- **After launch: no fallback.** A remote failure after the provider launched ends the leg
  with a code (`sandbox_remote_lost`, `sandbox_remote_bound_exceeded:<which>`,
  `sandbox_remote_owner_lost`). It never relaunches, locally or remotely. This matches
  agent-harness#1132 J7 step 6, and it avoids using a credential twice for one leg.
- **Fail closed.** `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED=1` refuses the leg with the same code
  instead of falling back.
- **Vocabulary.** All new codes join `_HARNESS_DETAIL_CODES`, and each has a delivery test.

## Dependency order

| Lane | Content | Can land before agent-harness#1132? |
|---|---|---|
| L0 | Falsifiers first, skip-guarded on their implementing symbols, with RED receipts. The R12 static test. | Yes |
| L1 | Remove the fleet address: `_INFERENCE_ALLOW` becomes `PHASE_LOOP_SANDBOX_EGRESS_ALLOW` (`host:port`, comma-separated, default empty). The fleet value moves to deployment config, a later maintainer-gated step. The URL location form and the RD6 notice. | Yes. It does not depend on agent-harness#1161 either. |
| L2 | Agent skeleton: `sandbox-agent serve`, TLS config, auth (RD2), version and profile handshake, `/v1/health`, principal workspaces, and the client library `remote_sandbox.py`. | Yes |
| L3 | Snapshot transfer and R2 verification; leases, heartbeat, journal, cancel and startup reaper (R8); cgroup scopes and bounds (R7, RD5); remote retention (R9). Proven with a **null workload**: a fixed, packaged probe program, not a provider, run under the same egress namespace and scope. | Yes |
| L4 | Evidence fields, fallback, fail-closed and notices. Local fallback onto `staging_root()`. | After agent-harness#1161 merges, for `staging_root()`. |
| L5 | Remote **jailed seat** launch through the factored leg-execution seam: the jail, the attestation and the credential channel (RD4). | **No.** It needs the shipped agent-harness#1132 jail, its profile digest and that digest's recorded EC-EXECFIND-2 pass. So it waits on agent-harness#1132, which waits on agent-harness#1071. It also needs the provider CLIs installed on the target at their qualified pins, with the agent-harness#1132 probes replayed there. |
| L6 | Qualification tooling: `phase-loop sandbox-remote qualify <url>` measures completion, cancellation, caller disconnect, agent restart, concurrent-principal isolation, latency and capacity, and writes a pinned record. The null-workload half runs after L3; the seat half after L5. | Partly |

What this means plainly:
- L0–L4 give a working, qualified remote *execution substrate* before agent-harness#1132.
- End-to-end remote seat execution cannot be claimed or qualified before agent-harness#1132
  lands.
- Codex and grok remote placement depends on RD3.

## Open maintainer decisions

These are prefixed RD so they do not collide with agent-harness#1132's D1–D8. None is ruled
here. The recommendation is the planner's, for the maintainer to accept or reject.

**RD1 Server process model on the remote host.**
- (a) **One agent per user**, as that user's systemd user service (lingering) on loopback or a
  Unix socket, behind the host's existing HTTPS reverse proxy.
  - OS-level separation between principals, with no multi-tenant code in the agent.
  - Each user's own subuid range serves their seats.
  - Cost: needs a remote account per user, and per-user routes at the proxy.
- (b) **One multi-tenant daemon** under a dedicated service account, with its subuid range
  partitioned per principal.
  - Simplest to operate, and it matches the consumer's "dedicated executor identity" wording.
  - Cost: an agent bug crosses tenants, and R6 rests on agent code instead of the OS.
- (c) **A socket-activated worker per request** (systemd `Accept=yes`) under a dedicated
  account.
  - No long-lived state.
  - Cost: leases, heartbeats and the reaper need a separate timer and a shared journal, which
    reintroduces the state it avoids.
- (d) **A container runtime** (agent-harness#891).
  - Portable.
  - Cost: it is still deferred for the reasons recorded there, and it would be a second
    isolation mechanism beside bwrap.

*Recommendation: (a).* The per-user OS identity makes R6 a kernel property rather than an
application one. Option (b) can be added later behind the same protocol.

**RD2 Authentication.**
- (a) **A per-principal bearer token**, issued on the remote by `sandbox-agent token issue`.
  - The agent stores only its hash. The client stores it 0600 and sends it only over verified
    TLS.
  - Works through any HTTPS proxy.
  - Cost: a bearer secret, so revocation and rotation are manual.
- (b) **mTLS client certificates.**
  - Strong, and nothing reusable crosses the wire.
  - Cost: most proxies terminate TLS and must forward the client identity, which is fragile to
    configure, and it adds certificate lifecycle work.
- (c) **An identity header from the fronting proxy** (OIDC or network identity), trusted only
  from loopback.
  - No secret in the runtime.
  - Cost: it is deployment-specific, and the agent's security then depends on proxy
    configuration it cannot check.
- (d) **SSH-key request signing** (`ssh-keygen -Y sign` over a nonce and the request digest),
  with no SSH transport.
  - Reuses existing keys, with replay-safe nonces.
  - Cost: key distribution to the agent, and new signing code.

*Recommendation: (a) for v1, with an optional pinned server fingerprint.* It is the smallest
thing that satisfies R5 and R6. Option (d) is a natural later hardening.

**RD3 v1 scope: workloads and legs.**
- **Workloads:**
  - (a) board seats only;
  - (b) seats plus read-only executor review legs (`launcher._stage_review_tree`);
  - (c) seats plus writing executors under `launcher.launch`, which return a patch.
    Option (c) needs a write-back and conflict model and remote executor credentials, and it
    interacts with the agent-harness#1140 lease supervisor.
- **Legs:**
  - (i) jailed legs only: Claude, and Gemini if agent-harness#1132 L3 is in scope. Parity is by
    construction.
  - (ii) Also codex and grok, on their **current** routes, under the principal's subordinate
    uid on the remote, with `CapBnd` exactly `SEAT_RETAINABLE_CAPS` for codex and empty for
    grok. This is strictly more confined than their local route, which runs as the operator.
    But it is **not** the agent-harness#1132 jail, and it inherits the
    `seat_filesystem_unconfined` label.

*Recommendation: workloads (a) with legs (ii).* Leaving codex and grok local leaves whatever
memory they use on the small host, and running them remote under a dedicated uid improves
their confinement rather than weakening it. Which seats dominate memory is measured in L6,
not assumed here. The
protocol carries a `workload` kind, so executors can follow in a separate plan.

**RD4 Seat credential delivery to the remote.**
- (a) **Forwarded per leg** over the authenticated channel into the J3 token pipe on the
  remote, and never written to remote disk by the agent.
  - The credential stays owned locally.
  - Cost: remote root can read it in transit through the agent.
- (b) **Remote-resident per-principal credential**, provisioned once by the user on the
  remote and stored 0600.
  - Nothing sensitive in each request.
  - Cost: a second copy to rotate and revoke, and it persists on a shared host.
- (c) **Inference stays local and only execution goes remote** (the agent-harness#848
  SBXEXEC split).
  - No credential leaves the local host, which also meets EC-HARDEN-5's credential clause.
  - Cost: SBXEXEC is proposal-only and a much larger body of work.

  *Signing sub-question:* whether the agent also signs the attestation with a key pinned by
  the client, so an archived record can be verified offline. Otherwise the record rests on the
  TLS channel alone.

*Recommendation: (a) now, with a signed attestation; (c) stays the long-term design under
agent-harness#848.*

**RD5 Disk bound mechanism.** A tmpfs with `size=` is RAM-backed, which defeats the purpose,
and unprivileged loop mounts are not possible.
- (a) **Filesystem project quotas** (XFS or ext4 `prjquota`) per sandbox.
  - A hard bound that returns ENOSPC.
  - Cost: root setup once per host, and the filesystem must support it.
- (b) **An agent watchdog** that measures `du` per sandbox on an interval and kills the scope
  over the bound.
  - No root.
  - Cost: overshoot is bounded only by write rate times the interval.
- (c) **An admin-provisioned filesystem per principal.**
  - A hard bound per principal, not per seat.
  - Cost: host setup, and the per-seat bound is still soft.

*Recommendation: (a) where available, with (b) as the recorded, typed degraded mode.* The
attestation reports which one applied, and the fail-closed flag refuses (b) if set.

**RD6 The legacy `host:path` (SSH) form.**
- (a) Keep it record-only, with the typed notice.
- (b) Implement an optional SSH adapter later, beside HTTPS.
- (c) Reject it as a configuration error.

*Recommendation: (a) in this plan and (b) as a separate follow-up only if someone asks.* SSH
must never be required.

**Host prerequisites, whatever is ruled.** These run as root on the remote host, by its
operator, never by the runtime or a lane:
- `uidmap` and a subuid/subgid range (the agent-harness#1132 D8 prerequisite);
- cgroup v2 delegation for the agent's user (`Delegate=yes`);
- the HTTPS proxy route and certificate;
- quotas, if RD5 (a) is chosen;
- the provider CLIs themselves, which are not in the wheel. agy must be at the qualified pin
  (agent-harness#1130 route-core), and the agent-harness#1132 probes (P1–P5) are replayed on
  that host before L5 claims it. The health handshake reports each CLI's version and image
  digest, and a mismatch with the qualified pin refuses that leg before launch.

## Changes

| File | Action |
|---|---|
| `phase_loop_runtime/sandbox_policy.py` | Parse the `https://` location. Replace `_INFERENCE_ALLOW` with `PHASE_LOOP_SANDBOX_EGRESS_ALLOW` (default empty). Add `remote_required()`. Add the authenticated health probe beside `_probe_root`. The SSH branches become the RD6 disposition. |
| `phase_loop_runtime/remote_sandbox.py` (new) | Client: TLS context (no insecure mode), auth header, the health probe, snapshot upload, lease heartbeat thread tied to the leg, attach and stream, cancel, attestation verification, and the typed error mapping. |
| `phase_loop_runtime/sandbox_agent.py` (new) | Server: routes (`/v1/health`, `/v1/sandboxes`, `/v1/sandboxes/{id}` with stage, launch, stream, heartbeat and DELETE), principal resolution (RD2), workspace, lease journal and startup reaper, cgroup scope and limits, per-principal uid partition, the retention loop, and the attestation. Linux only; fails closed. |
| `phase_loop_runtime/panel_invoker.py` | Named sites only: `_default_spawn` (placement branch, per-leg fallback, the zero-local-spawn counter), `_record_sandbox_facts` (the new fields and `applied` rule), `_HARNESS_DETAIL_CODES` (new codes), and the factored post-authorization leg-execution seam that both the local path and the agent call. |
| `phase_loop_runtime/review_stage.py` | A streaming snapshot writer that shares the selection logic and digest with `stage_review_tree`. |
| `phase_loop_runtime/sandbox_egress.py` | Consume the configured allowlist; the remote agent applies it intersected with its own policy. |
| `phase_loop_runtime/cli.py` | `sandbox-agent serve`, `sandbox-agent token issue/revoke` (if RD2 (a)), and `sandbox-remote qualify <url>`. |
| `scripts/verify_harden_evidence.py` | Report remote records; `remote_attestation` never satisfies a check (R4). |
| `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `docs/phase-loop/convergence-runtime.md`, `CHANGELOG.md` | The remote contract, the knobs, the residual, and the host prerequisites. |
| `tests/test_remote_sandbox_*.py` (new) | The falsifiers below. |

**Rebase notes.**
- `panel_invoker.py` is also touched by agent-harness#1161, #1071 and #1132; re-check
  `_default_spawn` and `_record_sandbox_facts` at rebase.
- A change to `panel_invoker.py` or `sandbox_policy.py` drifts the agy pin set, so the next
  release cut requalifies agy.

## Tests and falsifiers

Each test is a live test on the shipped module, with a control-green and a mutation-red
receipt. The agent tests run the real agent on loopback, with a test-only CA and the
loopback flag. Tests that need cgroup delegation or `newuidmap` skip, with a stated reason, on
a host without them, and the L6 live record covers them.

- `test_remote_sandbox_location.py`:
  - URL parsing; `http://` refused; the loopback test flag honoured only for loopback.
  - The `host:path` notice.
  - **R12 static test.** No product file under `phase_loop_runtime/` contains a private or
    CGNAT **host** address literal. Network addresses written as CIDRs (`10.0.0.0/8`,
    `100.64.0.0/10` and the like) and addresses inside `SLIRP_UPLINK_CIDR` (the slirp DNS
    `10.0.2.3`) are exempt. At `input_base_commit` the only code hits are the two
    `_INFERENCE_ALLOW` rows, so the control goes green once L1 lands. Mutation: reintroduce
    `_INFERENCE_ALLOW`.
- `test_remote_sandbox_transport.py`:
  - The R5 row of the prerequisite table.
  - The `ssh` spawn counter stays at zero.
  - Credential-leak checks: the token never appears in argv, logs or evidence (J3-style
    scan).
- `test_remote_sandbox_agent.py`:
  - The R2 digest refusal.
  - The R6 cross-principal matrix.
  - Unknown fields rejected; a request cannot widen the egress allowlist or `CapBnd`.
    Mutation: honour a request's cap list.
- `test_remote_sandbox_lease.py`: R8 (cancel, client SIGKILL, agent restart, journal
  fsync-before-launch).
- `test_remote_sandbox_bounds.py`: R7, per RD5.
- `test_remote_sandbox_evidence.py`:
  - R1, R4, R10, R11.
  - The `applied` truth table: every combination of receipt present or absent, digest match,
    attestation pass and local-spawn count.
  - Pre-launch fallback records local.
  - A post-launch loss never relaunches.
  - Fail-closed refuses.
  - `remote_attestation` alone never satisfies `verify_harden_evidence.py`.
- The existing suites `test_sandbox_policy.py`, `test_sandbox_retention.py` and
  `test_review_leg_sandbox.py`:
  - They stay green.
  - The goldens for an unconfigured root are byte-identical: with no remote configured, no
    probe runs and the record is unchanged.

## Acceptance

- [ ] Every falsifier above has control-green and mutation-red receipts against the shipped
  module, recorded in its lane and again at the final head. `automation.suite_command`
  passes at the PR head on a host with cgroup delegation and `uidmap`.
- [ ] Every agent-harness#896 acceptance item is met, with "host" read as the agent's host:
  - the root stages remotely or refuses, with no silent local staging;
  - the floor is checked on the filesystem that holds the sandbox;
  - egress is applied in the remote namespace;
  - reaping runs on the remote;
  - `applied` is true only for real placement.
- [ ] Each of the six consumer prerequisites has its falsifier, and an L6 live record against
  a real, general-purpose target. The record is produced by the product's qualify command,
  with no fleet specifics in the product.
- [ ] L5 lands only after agent-harness#1132, with the attestation checked against a jail profile
  digest that has a recorded EC-EXECFIND-2 pass.
- [ ] The remote residual is recorded in agent-harness#361, beside the agent-harness#1132 D3
  residual.
- [ ] RD1–RD6 are ruled by the maintainer before L2 (RD1, RD2), L3 (RD5) and L5 (RD3, RD4)
  start. RD6 is ruled before L1 merges.
- [ ] The plan and the implementation each pass a four-vendor board and a president.

## Non-goals

- Our fleet's deployment: endpoint, proxy route, tokens, the host prerequisites, and the
  consumer's network grant. That is a separate maintainer-gated step, after a release.
- Writing executors (RD3 (c)) and the SBXEXEC split (RD4 (c)); both need their own plans.
- The president seat. Container runtimes (agent-harness#891). Widening
  `SEAT_RETAINABLE_CAPS`, which is a security decision outside this plan.
- macOS or Windows *agents*. Clients on those platforms are in scope.
- Resuming an idle remote sandbox across a new lease. It can follow the resume design in
  `.consiliency/plans/detailed-panel-sandbox-capability-20260918-0800.md` once R8 exists.

## Execution Policy

- execute: effort=high, reason=a new network-facing service on the security boundary of an
  attested launch surface
