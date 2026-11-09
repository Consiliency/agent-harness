# v13 LANEEXEC: landed binding and STOP decisions (re-plan, 2026-11-09)

Frozen artifact for `plans/phase-plan-v13-LANEEXEC.md` (re-plan). It has no word
cap. The wire contract stays `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`,
byte-identical at its existing pin, which agent-toolkit vendors by digest
(IF-XR-1). Nothing here adds, removes or renames a wire member, enum value,
code, verb or exit class, so `protocol_schema_sha256` is unchanged and no toolkit
repin follows.

Where this artifact binds an `x-*` semantic sentence of the wire artifact to the
landed code, it says so with the sentence's line, and this artifact governs that
sentence for execution. Each such binding narrows behavior toward fail-closed
outcomes the wire already expresses. A future protocol version folds them in.

## 0. Inputs (pins of existing bytes only)

| Input | Identity |
| --- | --- |
| Roadmap | `specs/phase-plans-v13.md`, sha256 `a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d` |
| LaneExec launch protocol v1 (unchanged) | `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, sha256 `bd0e6694e6df9e4ae0bc640c138645adf6b49e8f56aa3f5af7488107062676f3` |
| Placement process protocol v1 (unchanged) | `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256 `130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea` |
| Caps contract | `plans/seats-jailcore-caps-contract.md`, sha256 `e614d3855320fe4c8a1d8b9a335181b2c493da45510062d2f8432ee30c362445` |
| SEATS REMOTE contract | `plans/seats-remote-contract.md`, sha256 `1cea960ddd28ef5e1c4bf79083fa9f9938b2c99c2e29dbd937864944ca76d7e8` |
| Landed baseline inspected | `origin/main` at `a493c46ccf979231b1a3ae5b23ae678a801f0603`. Every `file:line` below refers to this tree. |
| Pre-build sweep | Consiliency/agent-harness#1963 head `cdecd32cf9b9e33cbcf7ddf07c44b4556c6ad074`, `plans/artifacts/v13-LANEEXEC-landed-sweep.md` |
| Upstream re-plans consumed | `plans/artifacts/v12-CLOSEOUT-landed-binding.md` (§3 C-S1, §4.1–§4.3) and `plans/artifacts/v13-PLACECLI-landed-binding.md` (§3, §4) |
| Cross-phase ownership | `plans/artifacts/v12-v13-replan-ownership.md` |

The agent-toolkit pins manifest and its 27 file hashes inside the wire artifact
were re-verified by the sweep (the manifest is delivered at
`8b9c0697733b3815baa556b1823a653d497ffa04`, naming source
`cd9174e326140dc27471ff3bfc8abdd056f6e7bd`).

## 1. What LANEEXEC must still deliver

Nothing of LANEEXEC has landed: no `launch_process_contract.py`,
`launch_snapshot.py`, `launch_return.py`, `launch_service.py`, `launch_routes.py`,
`lane_launch.py`, `launch_cli.py` or `agent-harness-launch` entry exists. All
five goals, EC-LANEEXEC-1 to EC-LANEEXEC-5, remain open.

Work-start gates (non-human, `blocker_class=upstream_phase_unmet`):

1. CLOSEOUT SL-1 and SL-2 merged on main: `prepare_launch_v2`, `discard_admission`, `AttemptBinding`, the §4.2 controller document for `supervised_worker_cli launch --envelope --result`, the `WorkerResult`-to-public-status mapping and the echo sidecar (CLOSEOUT binding
   §3–§4). CLOSEOUT acceptance (EC-CLOSEOUT-1) is not a gate.
2. PLACECLI merged on main, including errata-1 and its `PlacementLifecycle`,
   `ForwardTcpUnixBridge` and whole-config `config_sha256` (PLACECLI binding §4).

Dropped from the old plan: the IF-0-JAILCORE-4 gate on the caps contract §1a
tmpfs carve-out and its §7 (j) tests (STOP L-S3 removes the dependency); the
"v12 IF-0-WORKER-1 and IF-0-JOURNAL-1 landed" gate (landed; superseded by gate 1).

## 2. Landed-interface table

"Use": **consume** (call unchanged), **extend** (the owning lane edits it),
**do not touch**.

| Landed site | Shape | Use |
| --- | --- | --- |
| `supervised_launch.py:366` | `prepare_launch(envelope_bytes, *, validator, decoder, config)` (fixture seam) | do not use; LANEEXEC uses CLOSEOUT's `prepare_launch_v2` |
| `supervised_launch.py:462` | `consume_admission(prepared)`; one-use token is process-local (`_TOKENS`, `:247`); LaneExec disposes through `discard_admission` | never called by LANEEXEC; the CLI consumes in its own process |
| `supervised_worker_cli.py:19`, `:72`, `:100` | production codec, `main`, `launch` gate | consume after CLOSEOUT; LANEEXEC never edits the CLI |
| `convergence/adapters/patch_return.py:29` | `PRODUCTION_LAUNCHER_COMMANDS` via `trusted_module_argv` | not the chain-root argv: it is the cancel command-line matcher (`trusted_module_argv(...)[1:]`); the chain root is built with `seat_uid.trusted_module_argv` (L-S1) |
| `patch_return.py:65`, `:80` | `ProposalReturn(status, proposal_bytes_digest, byte_length, baselines, locator)`, `WorkerResult(..., proposal, evidence_envelope_digest, journal_anchor, journal_complete)` | consume (L-S5) |
| `patch_return.py:92` | `CancelOutcome = cancelled \| already_terminal \| cancel_pending \| unknown_attempt \| owner_unverified \| owner_not_live` | consume (L-S4) |
| `patch_return.py:162` | `evidence_resolver(state_root)` | consume |
| `patch_return.py:221`, `:289` | `_audit`, `_paths` (private) | do not call (L-S5) |
| `patch_return.py:345`, `:382` | `run_patch_return` consumes admission and reserves the JOURNAL attempt itself | consume inside the CLI process (L-S2) |
| `patch_return.py:492` | non-completed termination → `withheld_incomplete` | consume (L-S5) |
| `patch_return.py:584` | `cancel_attempt(*, state_root, run_id=None, attempt_id=None, wait_seconds, launcher_commands)` | consume (L-S4) |
| `run_status.py:1165` | `reserve_attempt(...)` — permanent, independently durable | never called by LANEEXEC (L-S2) |
| `run_status_projection.py:271` | `attempt_status(root, attempt_id, *, observer)` incl. `unknown`, `stale_unknown`, nullable identity | consume (L-S4) |
| `seat_resource_caps.py:52`, `:221`, `:242` | whole `seat_resource_caps.v1` record, `load_caps`, `caps_sha256` | consume |
| `seat_resource_caps.py:247` | `_automatic_paths()` = `staging_root()` and the child scratch dir (private) | consume indirectly; not called (L-S3) |
| `seat_resource_caps.py:327`–`:339` | `_device_plan` refuses any anonymous filesystem, tmpfs included ("carve-out cleanup is not wired") | consume; no carve-out is used (L-S3) |
| `seat_resource_caps.py:350`, `:365` | `io_devices(caps)`, `readiness_code()` | consume |
| `seat_resource_caps.py:559` | `capped_popen(command, *, seat_key, **popen_kwargs)` — one capped parent per key, child-side readback | consume with key `laneexec:<client>:<reservation_id>`, called only by the detached supervisor; any exception keeps the claim (L-S3) |
| `sandbox_policy.py:806` | `staging_root()` | consume as the device witness for local attempt directories, never their location (L-S3) |
| `seat_uid.py:490` | `trusted_module_argv(module, *args)` | consume for every helper launch |
| `openshell_artifacts.py:72`, `:159`, `:445` | `Bound(end, cancelled)`, `safe_path(path)`, `check_binary_literals(patch, limits, bound)` | consume |
| `openshell_worker.py:398` | `landlock_manifest(rules, uid=10001, gid=10001)` | consume |
| `capability_registry.py:772` | `default_executor_for_work_unit(work_unit_kind, *, scheduler_assigned=False)` | consume before reserve; the file is unchanged and owned by no lane (coordinator ruling 2) |
| `runner.py:5969` | `launch_harness_lane_work_unit(...)` | extend (SL-4): the disabled-by-default placement site |
| `panel_invoker.py:4440` | `_NONLOCAL_EXECUTION_DRIVER = False` | do not touch |
| `panel_invoker.py:13354` | jailed Codex seat route | do not touch (L-S7) |
| `sandbox_placement.py`, `placement_lease.py`, `openshell_backend.py` | as left by PLACECLI (`PlacementLifecycle`, reservation journal) | extend (SL-3) after PLACECLI merges and the reservation-only walk exit (PLACECLI binding §2, §4.2); SL-3 performs every later step on a remote rung |
| `tests/data/seat_launch_references.json:13` | landed rows plus CLOSEOUT and PLACECLI rows | extend (SL-5) by union |

## 3. STOP decisions

### L-S1 — v2 admission seam

**Chosen: depend on CLOSEOUT; LANEEXEC adds no admission code (sweep
recommendation, adopted).** The wire sentence at artifact line 493 ("admits it
through the v12 admission seam (supervised_launch.prepare_launch …)") binds to
CLOSEOUT's production seam:

- **Pre-claim check.** In the order position "envelope admission" (artifact line 252), LaunchService calls CLOSEOUT's `load_v2_binding`, `capture_launch_v2` and `prepare_launch_v2` in process on the captured envelope bytes. A refusal is `refused`, code `sandbox_launch_admission_refused`, with the pinned diagnostic and no claim. The `PreparedLaunch` is never consumed here; it is disposed through CLOSEOUT's `discard_admission` in a `finally`.
- **Authoritative admission.** After the claim, the supervisor writes the per-attempt controller document at the path CLOSEOUT binding §4.2 derives from the envelope bytes. It then starts exactly one chain root, `seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", "launch", "--envelope", …, "--result", …)`, through `capped_popen` for a local target (L-S3). The CLI re-admits the same bytes, consumes once and reserves the JOURNAL attempt. A CLI refusal there, or an inner WORKER refusal after it, is a failure after the first chain process: `finished`, termination `failed_to_start`, claim kept (artifact line 525; L-S4).
- **Status mapping.** LANEEXEC consumes CLOSEOUT's `WorkerResult`-to-v2 mapping
  (CLOSEOUT binding §4.3) and maps v2 states to the wire only through §3 L-S4.

### L-S2 — exec claim versus the permanent JOURNAL reservation

**Chosen: keep the JOURNAL reservation worker-owned and make the claim a single
durable write in the placement journal only (sweep option 2).** The sweep's
requirement (durable ordering, partial-failure recovery and fresh-attempt
behavior specified; two writes never called atomic) is met as follows. The wire
sentence at artifact line 518 ("sets LeaseFlags.exec_claimed and reserves the
attempt_id through the v12 journal") is bound to:

1. The claim is one compare-and-set under the reservation's journal lock that
   sets `LeaseFlags.exec_claimed` and records the launch `request_id`. It does
   not touch the JOURNAL.
2. The JOURNAL attempt is reserved later, by `run_patch_return` inside the CLI,
   which is the first chain process.
3. Every claim rollback in artifact line 519 happens before the first chain
   process, so no JOURNAL reservation can exist when a claim is rolled back. A
   new `request_id` may therefore relaunch with the prepared
   `run_id` = `attempt_id` (artifact line 257) without colliding with a
   permanent reservation. The prepare record and its values stay as frozen.
4. Any failure at or after the first chain process keeps the claim. The JOURNAL
   may hold a reserved, terminal or no attempt: status reads it by `attempt_id`
   and maps through L-S4; a claim with no JOURNAL attempt and no verifiably live
   supervisor is `uncertain`. Restart never rolls a claim back; reap settles it
   through cancel and release, and later launches refuse
   `sandbox_launch_exec_claimed`.
5. Tests show the ordering with a crash injected between each pair of steps.

### L-S3 — local caps paths and the tmpfs carve-out

**Chosen: revise LANEEXEC to the supported block-backed route (sweep option 2).** This deviates from the sweep, which recommended keeping LANEEXEC blocked. Reason: the route meets EC-LANEEXEC-2 and EC-LANEEXEC-3 with the landed public API and removes the IF-0-JAILCORE-4 §1a carve-out prerequisite from implementation. Three caps API gaps remain. They are bound conservatively below, and they gate activation of a local route, not this phase.
- **Location.** Each local attempt's execution tree, home, out and scratch directories live under the selected client's LaneExec state directory (artifact lines 471 and 482), in a 0700 per-reservation directory whose ancestors meet line 482's ownership rule. These are the `x-argv-templates.slots` host paths.
- **Device rule.** At prepared-path verification (artifact line 252, pre-claim), each directory must have the same `st_dev` as `sandbox_policy.staging_root()`, the landed automatic path whose whole device `io_devices(load_caps())` plans. `staging_root()` is a device witness only; it never chooses a location. A tmpfs, any anonymous filesystem, or another device refuses with `sandbox_placement_capability_unmet`, zero invocations and no claim.
- **No carve-out in v1.** Artifact line 529's "including the caps contract §1a tmpfs carve-out" is read as "excluding" until SEATS ships the carve-out; adopting it later needs no wire change. `readiness_code()` still checks both landed automatic paths (`seat_resource_caps.py:247`, `:365`), so a host whose staging root or child scratch directory is tmpfs refuses at the readiness steps.
- **Chain-start re-check.** After the claim and immediately before `capped_popen`, the supervisor repeats `readiness_code()`, the device rule, and a comparison of `caps_sha256(load_caps())` against the reservation's `seat_caps_sha256`. A failure is artifact line 519's chain-start caps re-check: nothing has started, the claim rolls back, and the code is `sandbox_placement_capability_unmet`.
- **`capped_popen` failures.** Any exception from `capped_popen` keeps the claim and yields `finished`, termination `failed_to_start`, code `sandbox_placement_capability_unmet` (artifact lines 519, "rollback is never inferred", and 533). The landed API raises one refusal for failures both before and after its helper starts (`seat_resource_caps.py:636-670`).
- **Capped parent.** The detached supervisor calls `capped_popen` with key `laneexec:<client>:<reservation_id>` (artifact line 531); the short-lived `agent-harness-launch` process never does. The supervisor waits on the returned process for the attempt's life, so the landed in-process collection (`:655-659`) stops the parent. Reaping a dead supervisor's attempt relies on parent-death SIGKILL (artifact line 540) and reports the capped parent as `cleanup_pending`. LaneExec never reconstructs a private unit or cgroup name.
- LaneExec adds no `seat_resource_caps` API and calls none of its private functions. **ACTIVATE prerequisites** (SEATS-owned, not built here):
  - an expected-digest check inside `capped_popen`, which reloads caps at `:569`;
  - typed evidence of whether a failure came before or after the helper started;
  - kill/collect of a capped parent by key. `__all__` (`:673-677`) exports neither.
- **Unreadable caps record (coordinator ruling 1, 2026-11-09).** When `load_caps()` raises `CapsUnavailable`, every verb that places or launches fails closed: `prepare` and `launch` refuse `sandbox_placement_capability_unmet`, exit 10, for every target, with zero invocations and no claim. `status` and `cancel` act on existing records and keep working. `version` still exits 0 with a schema-valid response and empty stderr: `seat_caps_sha256` is the documented sentinel `sha256(b"seat_resource_caps_unavailable")`, also carried into `config_sha256` (PLACECLI binding §3 P-S1). `--help` prints one line naming the caps state and exits 0.

### L-S4 — status and cancel mapping

**Chosen: a total local-to-wire mapping onto the existing closed vocabulary; no
new wire value (sweep recommendation, adopted).** Zero-signal outcomes are never
reported as a successful cancellation.

| Local observation (first matching row) | Wire result |
| --- | --- |
| No launch record for the id in the `--client` inventory | status / cancel `unknown_attempt`, exit 10 |
| The LaneExec launch record holds a terminal LaunchResponse | status that response |
| No LaneExec terminal; JOURNAL display `queued`, `running` or `cancelling` | status the same state |
| No LaneExec terminal; a JOURNAL terminal of any kind, `unknown`, `stale_unknown`, null identity, or a held claim with no JOURNAL attempt | status `uncertain` |
| `cancel_attempt` → `cancelled` / `already_terminal` | cancel the same, exit 0 |
| → `cancel_pending` | cancel `cancel_pending`, exit 20 |
| → `unknown_attempt` with no LaneExec claim | cancel `unknown_attempt`, exit 10 |
| → `unknown_attempt` while LaneExec holds a claim, `owner_unverified`, `owner_not_live` | cancel `cancel_pending`, exit 20; no signal is sent; the local outcome is journaled in the LaneExec launch record and evidence |

Status exit classes are those of the wire artifact's `x-cli` for a returned
status record. LaneExec writes its terminal before it returns. Before the first chain process, that terminal is a pre-claim refusal or a claim rollback (`refused`). After it, the terminal is built from `WorkerResult` through CLOSEOUT §4.3. Every refusal at or after the first chain process is `finished`, termination `failed_to_start`, claim kept (artifact line 525). That includes the CLI's own refusal and an inner WORKER terminal `refused` written after `reserve_attempt` (`patch_return.py:397-399`). A result CLOSEOUT maps to `unknown` is recorded as `uncertain`. Readable JOURNAL bytes alone never establish acknowledgement. A following `status` reports what this table yields. It does not promise to tell a signalled cancel from a zero-signal one, because the two can race. The pure mapping functions live in
`launch_return.py` (SL-2) and are tested as closed tables.

### L-S5 — return for non-completed attempts

**Chosen: reuse WORKER's fail-closed withholding for `patch` and specify
`result` and `none` separately (sweep recommendation, adopted).** The wire
sentences at artifact lines 566 and 571 bind to:

| `result_kind` | Rule |
| --- | --- |
| `patch` | From `WorkerResult.proposal` only. `returned` → the bytes at the proposal `locator`, verified against `proposal_bytes_digest`, written to the ReturnDescriptor file; a baseline path (`ProposalReturn.baselines[].path`) under a snapshot mask → `sandbox_launch_audit_failed`, return null. `absent` → return null. `withheld_incomplete` (every non-completed termination, cancelled and timed-out included) → return null, no extra code; the termination already says why. `withheld_oversized`, `withheld_malformed` → `sandbox_launch_result_invalid`. `withheld_audit_error`, `withheld_unexplained_change`, `withheld_evidence_error` → `sandbox_launch_audit_failed`. The worker's `proposal_cap` is set no higher than the LaneExec cap. |
| `result` | LaneExec reads `{out}/result.json` after the worker ends, for every terminal state whose out directory is reachable. `out` lies outside the execution tree, so the worker's audit never sees it. Bounds and strict decoding as frozen; a failure is `sandbox_launch_result_invalid`. |
| `none` | Return null. |

"Return runs for every terminal state" holds as: the return step runs and yields
a descriptor or null with the code above. The `withhold` predicate applies to
returned bytes of either kind. `_audit` and `_paths` are never called and no
WORKER helper is refactored; agent-harness#1960 items 1 and 5 stay with that
issue.

### L-S6 — zero-effect assertions by stage

**Chosen: scope the assertions by stage (sweep recommendation, adopted).** For a
refusal at any step through `pre_exec` (artifact line 252 order), claim, upload,
scratch-provisioning and chain-start counters are zero. Snapshot, seed-capture
and envelope-admission counters equal one exactly when the refusal happens at or
after that step, and zero before it. This replaces the old plan's flat "zero
snapshot, upload, envelope or invocation counters" assertion.

### L-S7 — supported routes and qualification

**Chosen: define a per-action route mapping now and qualify none of it here; the
initial integration is the offline-proven subset (sweep options 1 and 2
combined).** Routes stay disabled and jail profile boundaries are preserved, as
the sweep recommended.

| Route (workload, action, result_kind) | Target | Owner of the qualification record | Shipped behavior |
| --- | --- | --- | --- |
| `implementation`, `execution`, `patch` | local | ACTIVATE | `lane_placement` disabled; when enabled, admission refuses `route_not_qualified` until a record exists |
| `pi-runner`, `execution`, `none` | local | ACTIVATE | `toolkit_interim` refuses `sandbox_launch_local_route_interim` |
| `pi-runner`, `execution`, `none` | openshell | ACTIVATE | `sandbox_launch_route_disabled` |
| `leg` / `qualification`, `review`, `result` | openshell | SEATS (REMOTE) | `sandbox_launch_route_disabled` |
| `leg` / `qualification`, `review`, `result` | local | SEATS launcher, outside LaneExec | always `sandbox_launch_route_disabled` from LaneExec |

The route key for a qualification record is CLOSEOUT's complete public route key
(tier `provider_readonly_patch_return_audit`, action, transport, ordered
executable chain, template and qualification digests). LaneExec ships no record.
Tests construct records only at the trusted-file seam of a temporary operator
configuration, never in shipped configuration or a controller document. A local review seat never
launches through LaneExec, so the jailed seat path and its profiles stay the only
local seat route; LaneExec never calls `seat_jail` or the jailed Codex route.

### L-S8 — the PLACECLI byte pin (same item as PLACECLI P-S2)

**Chosen: no repin.** Both v13 wire artifacts keep their bytes. The envelope
grant is derived by the field rule at `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json` line 509 (bare 64 hex after the
`sha256:` prefix), which already governs; the PLACECLI `launch_binding` sentence
is non-normative on that spelling (PLACECLI binding §3 P-S2). This deviates from
the sweep (hold until an input revision is approved) for the reason recorded
there.

## 4. Cross-repo consequences

- agent-toolkit (IF-XR-1): wire, digests and exit classes are unchanged.
  Behavioral narrowing it can observe: zero-signal cancels return
  `cancel_pending` (exit 20) where the old text could not say; non-completed
  `patch` attempts return null (not used by `pi-runner`, which takes `none`).
- SEATS REMOTE (IF-XR-2): `leg` and `qualification` stay disabled until SEATS
  supplies route qualification records; local review seats stay with the SEATS
  launcher.
- PLACECLI (IF-XR-3): the bridge is consumed unchanged.

## 5. Verification groups

Paths are relative to `phase-loop-runtime/`. Groups run on `ai` under the
admission lock and PSI gates, serially, `timeout 900`, no xdist, no cache
provider; dev0 runs plan validators only.

- V0: `tests/test_launch_process_contract.py`, `tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest`
- V1: `tests/test_launch_snapshot.py`
- V2: `tests/test_launch_return.py`
- V3: `tests/test_launch_service.py`, `tests/test_launch_local_caps.py`, `tests/test_launch_lifetime.py`, `tests/test_launch_release_reap.py`, `tests/test_sandbox_placement.py`, `tests/test_placement_lease.py`, `tests/test_openshell_backend.py`
- V4: `tests/test_phase_loop_lane_placement.py`, `tests/test_phase_loop_lane_harnesses.py`
- V5: `tests/test_launch_cli.py`, `tests/test_agent_cli_scratch_inventory_1147.py`, `tests/test_seat_launch_helpers_trusted.py`, `tests/test_seat_reference_inventory.py`
- V6: `tests/test_laneexec_receipt.py`
- V7: an installed wheel built the way `scripts/gate_a_cleanroom.sh` does, then V0 and V5 against it; tests reading repo-only files skip when those files are absent.
