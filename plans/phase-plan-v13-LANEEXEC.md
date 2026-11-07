---
phase_loop_plan_version: 1
phase: LANEEXEC
roadmap: specs/phase-plans-v13.md
roadmap_sha256: a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py tests/test_launch_snapshot.py tests/test_launch_return.py tests/test_launch_service.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_placement_lease.py tests/test_openshell_backend.py tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py tests/test_laneexec_receipt.py"]
---

# LANEEXEC: Generic placement launch service

## Context

This is Phase 2 of the advisory v13 roadmap. PLACECLI is planned. Its plan
landed as agent-harness#1853, and it stops at reservation, release/reap and the
bridge. LANEEXEC adds the one launch service that every approved client uses
after a reservation. agent-toolkit#54 already reserves through PLACECLI, but it
cannot run a remote Pi end to end until these launch inputs exist.

**Frozen artifact.** `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`,
sha256 `35e50428847ba44050eaea83fabe34da29b44ffb0b6bc8b26b1c854ba3eb6193`,
holds IF-0-LANEEXEC-1. It covers:

- the process entry `agent-harness-launch --client … launch|status|cancel|version`
  and its exit classes;
- the closed request and response records, which reuse the PLACECLI
  `Reservation` by `$id`;
- client routes and launch inputs;
- operator argv templates;
- snapshot construction and upload;
- the derivation of every admitted launch envelope v2 field;
- one exec, the per-reservation local cgroup, lifetime, bridge, status/cancel,
  release/reap interplay, return and evidence;
- activation defaults, the code vocabulary, in-process signatures and test
  obligations C1–C10.

This plan points at sections of the artifact and does not repeat them. The
artifact is read-only during execution. A needed change is an artifact
amendment, not a lane decision.

**Amendment (2026-11-07): toolkit pins manifest.** Coordinated with
Consiliency/agent-toolkit#71, the artifact now pins agent-toolkit through one
manifest, `x-contract-pins.toolkit_pins`, instead of a digest per file. The 17
role names are unchanged, and each one maps to its manifest entry. A missing
role fails closed. Test obligation C2 covers the checks, which SL-3.1 tests
with the other C2 refusals.

**Amendment (2026-11-07): Pi activation rulings (agent-harness#1899).** The
artifact freezes the three coordinator rulings given to agent-toolkit:

1. *`scratch_path`* (`x-scratch-path`). LaneExec reports the attempt's resolved
   absolute scratch directory in `LaunchResponse` and `StatusResponse`. On
   `pi-runner.openshell.v1` it is `<policy dir>/../scratch`. The shim puts
   exactly that value in the link hello, and remote-inner checks it against its
   own derivation. The requester never chooses it.
2. *Seed set* (`x-seed`). `LaunchRequest.seed` declares `{relpath, sha256,
   size}` entries, read from the per-client `seed_root`. The caps are 256
   entries, 16 MiB per entry and 64 MiB in total, and operators may only lower
   them. LaneExec verifies every digest and writes the files under `scratch/`
   before the one exec. Relpaths are confined, symlinks refuse, undeclared
   content never arrives, and there is no link seed-down step. Each entry is a
   `config` reference of the admitted envelope, so `envelope_digest` binds the
   set. The `config_sha256` binding is unchanged.
3. *Provisioning* (`x-seed.provisioning`). `scratch/` is created new, owned by
   the exec uid, mode 0700 and not a symlink, under trusted parents. A failure
   refuses with the one additive code `sandbox_launch_seed_refused` and a
   `seed_reason`.

Seed capture runs after the snapshot. Local provisioning runs after `pre_exec`
and before the exec claim. Openshell stages the set before the claim and sends
it in the one upload. No refusal holds a claim: an openshell provisioning
refusal before any byte is stored rolls the claim back
(`x-exec.claim_rollback`). Obligation C10 holds the tests. SL-0.1 runs its
schema cases, SL-1.1 its source cases and SL-3.1 the rest.

**Resolved toolkit gaps** (artifact `x-placecli-clarifications`):

1. *`TrailEntry.code` for `admitted`.* This is erratum PLACECLI-v1-errata-1,
   class a, applied to the PLACECLI artifact in this PR: `code` is null if and
   only if `outcome` is `admitted`. It is an erratum, not v2. The artifact's new
   `x-errata.version_rule` allows an erratum to correct a placeholder-only
   conditional or to specify unspecified behaviour. It allows no constant,
   member, verb, exit-class, code or policy-name change. The wire identity is
   `protocol_schema_sha256`, so a client pinned to the old bytes refuses
   cleanly. The roadmap, PLACECLI plan, SEATS REMOTE plan and manifest are
   re-pinned to the new bytes.
2. *Reserve replay after a timeout.* This is the same erratum, class b, as
   `x-placement-semantics.reserve_replay`:
   A replay runs in a fixed order:
   1. Identical-request check.
   2. If the attempt is settled, return the journaled bytes.
   3. Clock check. When `now >= settle_bound`, settle terminally without
      reconciliation: `timeout`, code `sandbox_placement_end_reached`, exit 20,
      and arm the `uncertain_cleanup` barrier. `settle_bound` is the journaled
      start plus the original `deadline_ms` plus `replay_settle_allowance_ms`
      (300000, the pinned transfer allowance).
   4. Otherwise, at most one bounded read-only reconciliation.

   The reconciling call itself journals and returns any settled result:
   `admitted` with exit 0, or `unreachable` with
   `sandbox_placement_operation_timeout` and exit 10. Only an indeterminate
   reconciliation returns `timeout` with `sandbox_placement_operation_timeout`
   and exit 20, and it creates nothing. Later replays return the journaled bytes
   with no target call. Reap is still not the retry path.

   The erratum's obligations R1–R3 and T1–T3 are executed by PLACECLI's
   lifecycle and CLI lanes. T3 is the cross-version check: a client pinned to
   the pre-erratum bytes refuses on `version` before any effect. The PLACECLI
   plan's SL-0, SL-1 and SL-3 test tasks name them.
3. *Lifetime past `ttl_s` = 3600.* There is no `renew` verb. The pinned envelope
   v2 caps `launch.stop.timeout_seconds` at 3600 and forbids any deadline change
   after admission. PLACECLI v1 forbids deadline fallback after admission, and
   the roadmap makes every attempt bounded and one-shot, so a renew could never
   lengthen an admitted attempt. The real failure, a lease lapsing while an
   attempt is live, is fixed inside the service. The detached attempt supervisor
   holds the lease lock and renews on a latest-success rule
   (`x-lifetime.liveness`):
   - after a confirmed heartbeat at `h`, the next renewal starts by `h + T/3`
     and is bounded by `T/3`;
   - with no confirmed renewal by `h + 2T/3`, the supervisor fences the attempt
     and kills its process group, so nothing executes at `h + T`;
   - timeout, rejection, a malformed reply, a lost acknowledgement and an
     unknown outcome all fail closed with `sandbox_launch_liveness_lost`;
   - when the supervisor dies, a parent-death kill ends a local attempt, and on
     `openshell` the lease lapses by `h + T`;
   - `ttl_s` below 45 refuses before snapshot.

   Renewal never touches the stored `Reservation` or the deadline.
4. *Local `pi-runner`.* `x-activation.local_pi_runner_launcher` ships as
   `toolkit_interim`. The toolkit's capped bwrap route stays the default until
   ACTIVATE (EC-LANEEXEC-5), and LaneExec refuses
   `sandbox_launch_local_route_interim` for that reservation. LaneExec-owned
   local launch (EC-LANEEXEC-3) is built and proven offline here. The switch is
   one config value, bound by `config_sha256` and reported by `version`. It flips
   only under the ACTIVATE three-part condition, and flipping back is the
   rollback.

agent-toolkit#54 also raised these, and the artifact settles them:

- launch inputs (`x-launch-inputs`);
- the caps schema (pinned below);
- the exit class for schema-invalid input: exit 70 with stdout absent and
  no effect. This is written into the erratum (class b, obligation T2) and
  stated for this CLI too.

**Pi launches (`x-argv-templates.pi_runner_templates`).**

- A `pi-runner` request names its reservation's resolved vector:
  `full-remote-pi-runner` on `openshell`, or `minimal-without-app` on local. A
  crossed pair refuses `sandbox_launch_input_mismatch` before any effect.
- Two concrete templates are frozen, and LaneExec selects one by target kind:
  - `pi-runner.openshell.v1` is the pinned toolkit engine's exact one exec:
    `landlock-exec --policy {manifest} -- <node> <remote_inner> --listen
    {relay_endpoint} --landlock {manifest} {manifest_digest}`. The guest
    endpoint is `127.0.0.1:17690`, which is the port the reservation's bridge
    forwards.
  - `pi-runner.local.v1` runs a fixed bwrap shape with an unshared network and
    `--die-with-parent`. `remote-inner` runs in stdio mode, and LaneExec relays
    it to one reservation-scoped 0600 link socket under `local_link_root`.
- The template hash is the SHA-256 of the record's RFC 8785 bytes, so a client
  recomputes it.
- Executable pins cover `remote-inner.mjs` and its closure, the image recipe and
  the helper.
- Both templates return `none`. There is one exec and no download, so the
  runner's output, a writer's included, travels over the client's own link.
- A phase-loop Pi lane therefore reaches LaneExec through the toolkit shim.
  `place_lane` selects the shim's agent-harness endpoint for that run, and
  phase-loop never speaks the link itself.

**Caps.** `seat_resource_caps.v1` from the pinned caps contract is the single
cap schema. LaneExec applies the whole effective record to one capped parent per
`(client, reservation_id)`, and child-side readback is the only proof. The v13
subset (`memory.max`, `cpu.weight`, `io.weight` and `io.max`) is documented in
the caps contract §6, and `seat_caps_sha256` sits inside `config_sha256`. A
missing delegation or controller maps to `sandbox_placement_capability_unmet`,
and nothing runs (`x-local-cgroup`).

**tmpfs scratch: decision.** This freeze adds a narrow carve-out, written as caps
contract §1a and amended in this PR. It is not a blanket major-0 exception. A
tmpfs automatic path is accepted only when all four conditions hold:

1. The filesystem type is `tmpfs` in both mountinfo and `fstatfs`
   (`TMPFS_MAGIC`); major 0 alone never qualifies.
2. `memory.max` read back.
3. Swap cannot carry the pages: `memory.swap.max` reads back `0`, or the host
   has no active swap area.
4. Carved-out content is removed before the capped parent is collected.

tmpfs pages are memory charged to `memory.max`, so they are bounded; swap is
the one path from tmpfs to disk, and condition 3 closes it. `ramfs`,
`devtmpfs`, overlay, NFS, FUSE and anonymous-device btrfs still refuse,
because they do real I/O that `io.max` cannot bound here. An `io_paths` entry
is never carved out. Caps contract §7 (j) and the host probe hold the tests;
JAILCORE SL-5 implements them in `seat_resource_caps.py`. LaneExec's automatic
paths are the attempt's execution tree, home, out and scratch
(`x-local-cgroup.automatic_paths`).

**Owner rulings in force.**

- `ai` is the only sandboxed-agent host. dev0 is not a host: no shipped
  configuration names it as a target, and local-launch proofs use fake
  cgroupfs/sysfs trees.
- Pressure gates stay EC-PLACECLI-5. LaneExec adds no pressure check.
- Remote writers carry `provider_readonly_patch_return_audit`. E2B stays parked.

**Other consumers.**

- SEATS REMOTE (`plans/phase-plan-v1-seats-REMOTE.md`) consumes this phase for
  `leg` seats. XR-3 is closed by `x-argv-templates.per_vendor_seat_templates`,
  `x-snapshot.full_mode` and `x-return.result`, and the REMOTE plan now records
  that.
- `leg` on `openshell` keeps the PLACECLI bridge (XR-1) through
  `x-bridge.attach`.

## External Inputs

The artifact's `x-contract-pins` carries every full digest and source revision.

- LaneExec launch protocol v1: the artifact named in Context.
- Placement process protocol v1 with PLACECLI-v1-errata-1:
  `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256
  `130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea`.
- `seat_resource_caps.v1`: `plans/seats-jailcore-caps-contract.md` with the §1a
  amendment this PR applies to the main digest. The new digest is sha256
  `e614d3855320fe4c8a1d8b9a335181b2c493da45510062d2f8432ee30c362445`.
- SEATS REMOTE: `plans/seats-remote-contract.md`, sha256
  `1cea960ddd28ef5e1c4bf79083fa9f9938b2c99c2e29dbd937864944ca76d7e8`.
- Admitted launch envelope v2 and run status at the roadmap-pinned
  consiliency-contract revision (`x-contract-pins.admitted_launch_envelope_v2`,
  `x-contract-pins.run_status`).
- agent-toolkit files through the pins manifest
  `harnesses/pi/contracts/pins.json` (`toolkit_pins.v1`, sha256
  `92dfdb186065d55d47a4aba3dd24836ca3005317222af2fb86624ae9db84965b`), whose
  source revision is `x-contract-pins.toolkit_pins.toolkit_commit`. At that
  revision, `writer-snapshot.mjs` and `cred-proxy.mjs` have the same bytes as at
  the roadmap-cited revision. All of these are design inputs that are read and
  never copied:
  - snapshot and placement: `writer-snapshot.mjs`, `policy.json`,
    `cred-proxy.mjs` and `docs/remote-placement.md`;
  - Pi template inputs: `remote-inner.mjs`, `link.mjs`, `exec-clean.mjs`,
    `remote-launch.mjs`, `landlock/manifest.mjs` and the `landlock/Dockerfile`
    helper recipe;
  - the engines `openshell-image.mjs`, `openshell-landlock.mjs`,
    `openshell-cli.mjs`, `openshell.mjs` and `loopback.mjs`;
  - the `image/Dockerfile` and `image/build-runner-image.mjs` runner-image
    recipe;
  - the other ten files of the 16-file `remote-inner.mjs` runtime closure,
    including `git-adapter.mjs` and `guest-bin/git`, under
    `remote_inner_closure:<path>` roles.

No future implementation SHA, commit count or landing topology is pinned.

## Interface Freeze Gates

- [ ] IF-0-LANEEXEC-1 — The artifact above, byte-equal in source-tree checks to
  the packaged copy. It covers the closed messages and the CLI; the client
  routes, the writer-route rule and executor resolution before reserve;
  template registration, the hash rule, the slots and the two concrete
  `pi-runner` templates; git/full snapshot construction, masks,
  limits and upload; the declared seed set, `scratch/` provisioning and the
  `scratch_path` report; envelope field derivation, including the egress grant from
  `Reservation.egress_sha256`; one exec claim and route entries; the
  per-reservation capped parent; the fixed deadline with fail-closed
  latest-success lease renewal; bridge attach and loss, and the local Pi link; status, cancel, release and reap
  interplay; patch, result and none return with bounded descriptors; and
  disabled activation defaults.

Production signatures freeze as listed in the artifact's `x-in-process-api`:
`decode_launch_request`, `encode_launch_response`, `build_launch_service`,
`LaunchService.launch|status|cancel`, `build_snapshot`, `build_seed`, `lane_launch.place_lane`,
`launch_cli.main` and `launch_cli.version_response`. Record fields come only from
the schema. Exceptions translate to closed codes `from None`. Input values,
returned bytes, policy bodies and credential material never enter messages,
diagnostics or evidence.

## Cross-Repo Gates

- [ ] IF-XR-1 (agent-toolkit, consumer) — The toolkit:
  - vendors this artifact by sha256 and refuses on a `version` mismatch;
  - launches `openshell` `pi-runner` reservations through `agent-harness-launch`
    with `pi-runner.openshell.v1`. Its link hello names `scratch_path` from
    `status` as its scratch directory and places every runner tree below it. It
    declares the initial `scratch/` content as `seed` under `seed_root`, sends no
    seed-down files and expects `result_kind` `none`. Under `laneexec` it connects to
    the `pi-runner.local.v1` link socket within 120 s;
  - keeps its capped bwrap launcher for local `pi-runner` while
    `local_pi_runner_launcher` is `toolkit_interim`. That route applies the full
    `seat_resource_caps.v1` record with readback, follows the caps contract §1a
    rule for tmpfs scratch, bounds the run by a non-null
    `expires_at` and releases on exit;
  - switches only under EC-ACTIVATE-4.
- [ ] IF-XR-2 (SEATS REMOTE XR-3, closed by this freeze) — Workload `leg` gets:
  - one registered template per vendor;
  - `full` snapshot under the size cap, masked by `planted_paths`;
  - action `review`, with one bounded `result` object and no patch;
  - in-process `pre_exec` (the vendor re-check) and `withhold` (the credential
    scan) hooks.
- [ ] IF-XR-3 (consumed) — The PLACECLI `ForwardTcpUnixBridge` for `pi-runner`
  and `leg` on `openshell`, unchanged.

Work-start gates (non-human, `blocker_class=upstream_phase_unmet`):

- PLACECLI implemented, including errata-1;
- EXT-WORKER (v12 IF-0-WORKER-1 and IF-0-JOURNAL-1);
- IF-0-JAILCORE-4 (`seat_resource_caps.py`) landed, including the caps contract §1a
  carve-out and its §7 (j) tests.

EXT-LAUNCHSITE and EXT-OPENSH are activation prerequisites; their offline
controls run here.

## Lane Index & Dependencies

SL-0 — Packaged launch contract and strict codec
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5
  Parallel-safe: no

SL-1 — Snapshot construction
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Bounded return and evidence
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-3 — Launch service, exec, local caps, lifetime and lifecycle interplay
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4, SL-5
  Parallel-safe: no

SL-4 — Phase-loop lane placement site
  Depends on: SL-0, SL-3
  Blocks: SL-6
  Parallel-safe: yes

SL-5 — Launch process CLI and launch inventories
  Depends on: SL-0, SL-3
  Blocks: SL-6
  Parallel-safe: yes

SL-6 — Documentation, receipt and spec reconciliation
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Packaged launch contract and strict codec

- **Scope**: Package the frozen artifact and expose a side-effect-free strict codec and typed records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_process_contract.py`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `phase-loop-runtime/tests/test_launch_process_contract.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`
- **Interfaces provided**: `decode_launch_request`, `encode_launch_response`, immutable launch records, packaged launch-v1 bytes
- **Interfaces consumed**: the frozen artifact; packaged PLACECLI process-v1 schema and records (PLACECLI SL-0); `jsonschema`, `referencing` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_launch_process_contract.py`, `tests/test_gate_a_wheel_isolation.py` | Obligation C1. Valid examples for all seven families. Path-entered negatives for every enum and conditional, including `RepoPath` grammar, the workload/action/result_kind pairs, refused→zero invocations and the snapshot_reason/admission_diagnostic pairing. Pi cases: one valid remote Pi request (openshell, `full-remote-pi-runner`, `none`) and one valid local Pi request (local, `minimal-without-app`, `none`). Both crossed policy/target pairs decode as schema-valid and are left to the SL-3 binding refusal, and `patch` with `pi-runner` is refused. The C10 schema cases: seed relpath grammar and length, a non-empty `seed` outside `pi-runner`, a `scratch` request member, the `seed_reason` pairing and the `scratch_path` presence rules. Packaged bytes equal the artifact. Reservation resolves through the PLACECLI `$id`. Installed-wheel load. | `V0` |
| SL-0.2 | impl | SL-0.1 | `launch_process_contract.py`, `contracts/placement/launch-v1.schema.json` | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 files | SL-0 tests | `V0`; mutating the packaged bytes while updating only a test expectation must still fail. |

### SL-1 — Snapshot construction

- **Scope**: Build git and full snapshots of a hostile source exactly as `x-snapshot` states, with no network and no source-repository git execution, and capture the declared seed set as `x-seed` states.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_snapshot.py`, `phase-loop-runtime/tests/test_launch_snapshot.py`, `phase-loop-runtime/tests/fixtures/launch-snapshot/**`
- **Interfaces provided**: `build_snapshot`, `SnapshotHandle` (execution tree, descriptor bytes, `SnapshotEvidence`); `build_seed`, `SeedHandle` (staged capture, references)
- **Interfaces consumed**: `Snapshot` record (SL-0); `openshell_artifacts.Bound`, `safe_path` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_launch_snapshot.py`, fixtures | Obligation C3 on generated temporary repositories: each inventory class; a self-contained `.git` with only B-reachable objects and none of the reference's excluded material; skip-worktree masks; the always-on secret matcher; full mode only where permitted; a non-work-tree root; each cap; a mid-copy mutation giving `source_changed`; each path rule; `untracked_input` for patch. The C10 source cases through `build_seed`: unsafe paths, each symlink position with an unopened sentinel, `not_regular_file`, digest and size mismatches, each cap, and undeclared files never opened. A planted hostile `.git/config` (hooks, fsmonitor, filter) must leave a marker unexecuted. | `V1` |
| SL-1.2 | impl | SL-1.1 | `launch_snapshot.py` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 files | SL-1 tests | `V1` |

### SL-2 — Bounded return and evidence

- **Scope**: Turn a terminated attempt into one bounded patch, result or none return plus metadata-only `LaunchEvidence`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_return.py`, `phase-loop-runtime/tests/test_launch_return.py`
- **Interfaces provided**: `collect_return`, `ReturnOutcome`, `LaunchEvidence` builder; signature `collect_return(attempt, kind, *, policy, withhold, bound) -> ReturnOutcome`
- **Interfaces consumed**: records (SL-0); v12 IF-0-WORKER-1 proposal transport and post-run audit (pre-existing after EXT-WORKER); `output_retention.mark/prune` (pre-existing); `openshell_artifacts.check_binary_literals` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_launch_return.py` | Obligation C8: patch cap, a masked path in a proposal, audit error and unexplained change withholding; `result.json` bound, duplicate keys, trailing data and `truncated: true`; `withhold` deleting bytes; 0700/0600 descriptors; return on cancelled and timed-out terminations; a raw-output sentinel never reaching a record or evidence. | `V2` |
| SL-2.2 | impl | SL-2.1 | `launch_return.py` | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 files | SL-2 tests | `V2` |

### SL-3 — Launch service, exec, local caps, lifetime and lifecycle interplay

- **Scope**: The one `LaunchService`, covering admission order, envelope construction and admission, exec claim, local and openshell route entries, the capped parent, the detached supervisor with internal lease liveness, bridge attach, status/cancel, and the release/reap hooks.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launch_service.py`, `phase-loop-runtime/src/phase_loop_runtime/launch_routes.py`, `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py`, `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py`, `phase-loop-runtime/tests/test_launch_service.py`, `phase-loop-runtime/tests/test_launch_local_caps.py`, `phase-loop-runtime/tests/test_launch_lifetime.py`, `phase-loop-runtime/tests/test_launch_release_reap.py`, `phase-loop-runtime/tests/test_sandbox_placement.py`, `phase-loop-runtime/tests/test_placement_lease.py`, `phase-loop-runtime/tests/test_openshell_backend.py`
- **Interfaces provided**: `build_launch_service`, `LaunchService`, `LaunchService.launch|status|cancel`, release/reap attempt hooks inside `PlacementLifecycle`
- **Interfaces consumed**: records (SL-0); `build_snapshot` (SL-1); `collect_return` (SL-2); `PlacementLifecycle`, `ForwardTcpUnixBridge`, the stored reservation journal (PLACECLI); `supervised_launch.prepare_launch`/`consume_admission`, `supervised_worker_cli launch|status|cancel`, journal API (v12); `seat_resource_caps.load_caps`, `caps_sha256`, `readiness_code`, `capped_popen` (IF-0-JAILCORE-4); `openshell_worker.landlock_manifest`, `panel_invoker._NONLOCAL_EXECUTION_DRIVER` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | SL-3 test files | Obligations C2, C4–C7 through `build_launch_service` with a fake coordinator, fake cgroupfs/sysfs and fake `systemd-run` (`real_seat_caps` marker). (1) Every refusal through `pre_exec` with zero snapshot, upload, envelope or invocation counters. (2) The egress grant equals the reservation digest's hex. (3) Exec claim order, rollback and the effective configuration digest (obligation C4). Refusals through `pre_exec` take no claim, and a new request_id then launches. The certain post-claim failures roll the claim back. An unknown upload, or a crash after the claim, keeps it. A changed referenced policy, mapping, threshold or cap record refuses `sandbox_launch_input_mismatch`. (4) Missing controllers each refuse capability_unmet, and the caps contract §1a cases hold on LaneExec's automatic paths: tmpfs is accepted only with `memory.max` and `memory.swap.max` read back, every other major-0 type refuses, and tmpfs content is removed before the parent is collected. (5) A readback mismatch gives finished/failed_to_start with no target marker. (6) Renewal on an injected clock. An attempt longer than `ttl_s` stays live through confirmed renewals, the next renewal starts by `h + T/3`, and the stored Reservation stays byte-identical. A renewal timeout, lost acknowledgement, rejection, malformed reply or lost connection each fences at exactly `h + 2T/3` and kills the group before `h + T`, with `sandbox_launch_liveness_lost`. Supervisor death ends a local chain and lets an openshell lease lapse. No re-admission overlaps a workload that may still run. `ttl_s` below 45 refuses before snapshot. (7) lifetime_exceeded ends the attempt timed_out. (8) Bridge loss ends it cancelled. (9) Cancel affects only the verified owner. (10) Release cancels a live attempt, then cleanup_pending. (11) Reap settles a dead supervisor in its own inventory only. (12) route_disabled is refused under the shipped defaults. (13) toolkit_interim refuses local `pi-runner`. (14) Both crossed Pi pairs refuse `sandbox_launch_input_mismatch` before effects. (15) Template selection is by target kind. The openshell and local Pi argv expand exactly to their frozen forms, with `relay_endpoint` as the single argument `127.0.0.1:17690`. The other target's template id, or a `template_sha256` mismatch, refuses before effects. The local link accepts one connection within 120 s, and no connection ends the attempt with `sandbox_launch_bridge_lost`. (16) The remaining C10 cases: seed references and `envelope_digest` binding, `source_changed` at recheck, `scratch/` mode, ownership and ancestor refusals on local, the openshell provisioning rollback and unknown result, the exact declared set on both targets, and the `scratch_path` echo in launch and status. | `V3` |
| SL-3.2 | impl | SL-3.1 | `launch_service.py`, `launch_routes.py`, `sandbox_placement.py`, `placement_lease.py`, `openshell_backend.py` | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 files | SL-3 tests | `V3`. Mutation controls, each failing through a production path: drop the capped parent, renew by rewriting the Reservation, skip the exec-claim journal, launch after `pre_exec` refuses, reach a coordinator under the shipped defaults, swallow a renewal failure, accept a non-canonical template record, and the four C10 seed mutations. |

### SL-4 — Phase-loop lane placement site

- **Scope**: Wire writable `lane_execute` units through `lane_launch.place_lane`, which is disabled by default, with the executor resolved before reserve and the `x-client-routes` mapping.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/lane_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/tests/test_phase_loop_lane_placement.py`, `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py`
- **Interfaces provided**: `lane_launch.place_lane`, `LaneLaunchOutcome` (route `interim_local` or a LaunchResponse)
- **Interfaces consumed**: `LaunchService` (SL-3); `PlacementLifecycle` (PLACECLI); `default_executor_for_work_unit` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | — | SL-4 test files | Obligation C9 through `launch_harness_lane_work_unit`. (1) `lane_placement` disabled leaves the existing launch and its argv byte-identical. (2) Enabled, a Pi lane starts its existing Pi executor with the toolkit shim's agent-harness endpoint selected for that run and never reserves `pi-runner` or speaks the link itself (a fake shim records the selection). Other executors reserve `agent-harness`/`implementation`. (3) Reducer, review, verify and closeout units never reach the site. (4) An executor or provider change after reserve refuses. (5) A typed refusal releases and does not fall back. | `V4` |
| SL-4.2 | impl | SL-4.1 | `lane_launch.py`, `runner.py`, `capability_registry.py` | — | — |
| SL-4.3 | verify | SL-4.2 | SL-4 files | SL-4 tests | `V4` |

### SL-5 — Launch process CLI and launch inventories

- **Scope**: Register `agent-harness-launch`, assemble it from the shared service, and record every new launch site, helper and dynamic import.
- **Owned files**: `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/src/phase_loop_runtime/launch_cli.py`, `phase-loop-runtime/tests/test_launch_cli.py`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `agent-harness-launch`, `launch_cli.main`, `launch_cli.version_response`; argv `agent-harness-launch --client … launch|status|cancel|version`
- **Interfaces consumed**: codec (SL-0); `build_launch_service` (SL-3)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | — | SL-5 test files | Spawn the installed entry and module path with isolated imports, controlled HOME/config and hostile selection variables. Assert the required `--client`, the exit classes (70 for schema-invalid input with stdout absent), one JSON line, empty ordinary stderr and no sentinel leakage. Assert `version` reports both protocol digests, `config_sha256`, `seat_caps_sha256`, `local_pi_runner_launcher`, `seed_root` and templates. Classify new rows: helpers launch via `seat_uid.trusted_module_argv`, never `-m`. | `V5` |
| SL-5.2 | impl | SL-5.1 | `launch_cli.py`, `pyproject.toml`, `uv.lock`, `seat_launch_references.json` | — | — |
| SL-5.3 | verify | SL-5.2 | SL-5 files | SL-5 tests | `V5` |

### SL-6 — Documentation, receipt and spec reconciliation (docs sweep)

- **Scope**: Publish the launch service and record evidence. Reconcile specs only through amendments.
- **Owned files**: `docs/placement-launch-service.md`, `docs/placement-process-cli.md`, `phase-loop-runtime/README.md`, `plans/evidence/placement/LANEEXEC.md`, `phase-loop-runtime/tests/test_laneexec_receipt.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: the public launch-service documentation and the IF-0-LANEEXEC-1 receipt
- **Interfaces consumed**: `decode_launch_request` (SL-0), `build_snapshot` (SL-1), `collect_return` (SL-2), `LaunchService` (SL-3), `lane_launch.place_lane` (SL-4), `agent-harness-launch` (SL-5)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | — | `tests/test_laneexec_receipt.py` | The closed receipt parser refuses missing or skipped-only results, stale artifact hashes, an enabled live route or a `laneexec` launcher default. | `V6` |
| SL-6.2 | docs | SL-6.1 | docs, README, catalog | Document messages, exit classes, routes, templates, snapshot modes and masks, the seed set and `scratch_path`, lifetime (no renew), caps, the interim local route and switch, and return. Also state that providers name egress only and credentials stay with the requester. Rescan the catalog. | — |
| SL-6.3 | docs | SL-6.2 | `CHANGELOG.md`, `.doc-decisions.json`, `plans/manifest.json`, evidence | Add one Unreleased entry. Write actual V0–V7 outcomes and hashes to the receipt. Append manifest lifecycle without editing frozen inputs. Record any freeze correction as a dated amendment request, never as an in-place edit. | — |
| SL-6.4 | verify | SL-6.3 | SL-6 files | receipt test | `V6`, then `V7` |

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-1: effort=high, reason=hostile-source snapshot construction
- SL-3: effort=high, reason=lifecycle ordering across lease and cgroup and journal
- SL-6: effort=low, reason=documentation and receipt reducer

## Execution Notes

- **Work-start gates**: PLACECLI (with errata-1), EXT-WORKER and
  IF-0-JAILCORE-4 must be landed, and their final APIs reconciled with the
  consumed names above. Until then the phase is planned but blocked with
  `blocker_class=upstream_phase_unmet` and `human_required=false`.
- **Cross-phase files**: SL-3 edits `sandbox_placement.py`, `placement_lease.py`
  and `openshell_backend.py`, which PLACECLI SL-1 owns. That is a serial edge,
  because LANEEXEC starts only after PLACECLI lands. SL-0 extends PLACECLI's
  `test_gate_a_wheel_isolation.py`, and SL-5 extends its CLI-adjacent
  inventories. If landed PLACECLI or v12 moves `PlacementLifecycle` or adds a
  shared CLI registry, amend ownership before execution.
- **Single-writer files**: `pyproject.toml`, `uv.lock` and
  `seat_launch_references.json` (SL-5); `runner.py` and
  `capability_registry.py` (SL-4); `plans/manifest.json`, `CHANGELOG.md` and
  `.doc-decisions.json` (SL-6). `uv.lock` stays byte-identical when the lock
  check agrees.
- **Known destructive changes**: none. Every lane is purely additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none. Nothing is exported from the package root, so no lazy `__getattr__` pattern is needed.
- **Package data**: `contracts/placement/**` is already package data. V7 checks
  the installed wheel.
- **Shared host**: before each command, check `uptime` and `/proc/pressure/io`.
  Wait if the 1-minute load is above 16 or IO full avg60 is above 10%. Run only
  targeted files, serially, with no xdist and no cache. Full suites and Gate A
  belong to hosted CI.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Not in this phase**:
  - live `ai` use, a registered OpenShell backend, any change to
    `_NONLOCAL_EXECUTION_DRIVER` or `policies.json`, enabling `lane_placement`,
    flipping `local_pi_runner_launcher`, E2B, and any toolkit change;
  - a new `--client` value for a standalone OpenCode/Claude/Codex harness
    (a PLACECLI protocol version).
- **Next command**: none until the work-start gates are verified. Then run
  `claude-execute-phase plans/phase-plan-v13-LANEEXEC.md` under separate
  execution authority.

## Acceptance Criteria

- [ ] EC-LANEEXEC-1 — proven by `V3`, `V4` and `V5` through `build_launch_service`, `place_lane` and the installed entry for every `x-client-routes` row; falsified by a path-entered reducer or review unit reaching `place_lane`, a provider or executor change after reserve, or a second launch for one reservation reaching the launch-chain counter.
- [ ] EC-LANEEXEC-2 — proven by `V1`, `V2` and `V3` (snapshot, envelope derivation, one exec, local caps before exec, return bounds); falsified by a path-entered omitted or mismatched egress grant, a crossed Pi policy/target pair or a non-selected Pi template reaching snapshot, an undeclared launch input entering argv, an undeclared or unverified seed file reaching `scratch/`, a target marker running before readback, a `not_armed` placed attempt, or a proposal over cap returned.
- [ ] EC-LANEEXEC-3 — proven by `V3` and `V5` (`pi-runner` identity and inventory, bridge only on `openshell`, local `bridge: null`, capability_unmet with nothing run, caller-scoped reap, inventory rows for agent-harness#1787 to agent-harness#1790 controls); falsified by a path-entered credential sentinel in the sandbox, template, environment, record or evidence, a local bridge, cross-inventory reap or an uncapped local start.
- [ ] EC-LANEEXEC-4 — proven by `V3` and `V4` fake-coordinator, egress-digest, headroom-refusal, bridge-loss, cancel, timeout, crash/restart and return mutations at the production construction sites; falsified by any coordinator connection under shipped configuration, a swallowed renewal failure or a target process alive at `h + T`, or by a test that replaces `build_launch_service` or `build_snapshot`.
- [ ] EC-LANEEXEC-5 — proven by `V4` (lane_placement disabled leaves the existing launch byte-identical) and `V3` (toolkit_interim refuses local `pi-runner` with zero invocations), plus the `V6` receipt showing both shipped defaults; falsified by a shipped `laneexec` or `enabled` default, or by the existing local route being removed.

## Verification

V0–V7 are execution-time commands, not run by this planning PR.

- V0: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_process_contract.py tests/test_gate_a_wheel_isolation.py`
- V1: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_snapshot.py`
- V2: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_return.py`
- V3: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_service.py tests/test_launch_local_caps.py tests/test_launch_lifetime.py tests/test_launch_release_reap.py tests/test_sandbox_placement.py tests/test_placement_lease.py tests/test_openshell_backend.py`
- V4: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_phase_loop_lane_placement.py tests/test_phase_loop_lane_harnesses.py`
- V5: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_launch_cli.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_launch_helpers_trusted.py tests/test_seat_reference_inventory.py`
- V6: `cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_laneexec_receipt.py`
- V7: build an installed wheel in the Gate-A shape of `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, then run V0 and V5 against it. Tests that read repo-only files skip when those files are absent. If landed packaging changes this shape, amend the exact command before execution.

At execution preflight, validate V0–V7 and the frontmatter suite through
`verification_evidence.validate_verification_commands` (IF-0-VC-2). Require
multiple-failure reporting, and flag proof cost when one node exceeds roughly
five minutes. Operational evidence (a live run) belongs to ACTIVATE and its
runner-stamped amendment. Proxy evidence needs a roadmap amendment.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json`, `docs/placement-launch-service.md`, `docs/placement-process-cli.md`
- evidence paths: `plans/evidence/placement/LANEEXEC.md`
- redaction posture: `metadata_only`
- downstream handling: `none`
