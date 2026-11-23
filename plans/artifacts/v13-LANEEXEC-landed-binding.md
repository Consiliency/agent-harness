# v13 LANEEXEC: landed binding and STOP decisions (re-plan, 2026-11-09)

Frozen artifact for `plans/phase-plan-v13-LANEEXEC.md` (re-plan). It has no word
cap. The wire contract stays `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`,
byte-identical at its pin except for erratum LANEEXEC-v1-errata-1 (`x-errata`: one
template literal and the rule sentence that prescribes it), which agent-toolkit
vendors by digest (IF-XR-1). That erratum is the one toolkit repin. Nothing here
adds, removes or renames a wire member, enum value, code, verb or exit class, and
this artifact makes no wire change of its own. Erratum LANEEXEC-v1-errata-2 (§6) is a
plan and binding erratum only: it changes this artifact and the phase plan, never the
wire bytes, so the toolkit does not repin.

Where this artifact binds an `x-*` semantic sentence of the wire artifact to the
landed code, it says so with the sentence's member path, and this artifact governs that
sentence for execution. Each such binding narrows behavior toward fail-closed
outcomes the wire already expresses. A future protocol version folds them in.

## 0. Inputs (pins of existing bytes only)

| Input | Identity |
| --- | --- |
| Roadmap | `specs/phase-plans-v13.md`, sha256 `a5cd5f2bedbda38c99ad516113fd839dae8af6ea4482760e8efd18a5d413428d` |
| LaneExec launch protocol v1 with erratum LANEEXEC-v1-errata-1 | `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`, sha256 `da311638f2c5b92df5b1f2a917665b62c06aa10f80040bfa2504dcd78f42442a` |
| Placement process protocol v1 (unchanged) | `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`, sha256 `130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea` |
| Caps contract | `plans/seats-jailcore-caps-contract.md`, sha256 `e614d3855320fe4c8a1d8b9a335181b2c493da45510062d2f8432ee30c362445` |
| SEATS REMOTE contract | `plans/seats-remote-contract.md`, sha256 `1cea960ddd28ef5e1c4bf79083fa9f9938b2c99c2e29dbd937864944ca76d7e8` |
| Landed baseline inspected | `origin/main` at `a493c46ccf979231b1a3ae5b23ae678a801f0603` (re-plan). |
| Landed baseline re-inspected (LANEEXEC-v1-errata-2) | `origin/main` at `4dd77878afe58c429b01969c32c89b755a820002` (v0.7.40). Every `file:line` below refers to this tree. |
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
| `supervised_launch.py:379` | `prepare_launch(envelope_bytes, *, validator, decoder, config)` (fixture seam) | do not use; LANEEXEC uses CLOSEOUT's `prepare_launch_v2` |
| `supervised_launch.py:475` | `consume_admission(prepared)`; one-use token is process-local (`_TOKENS`, `:259`); LaneExec disposes through `discard_admission` | never called by LANEEXEC; the CLI consumes in its own process |
| `supervised_worker_cli.py:19`, `:74`, `:100` | production codec, `main`, `launch` gate | consume after CLOSEOUT; LANEEXEC never edits the CLI |
| `convergence/adapters/patch_return.py:29` | `PRODUCTION_LAUNCHER_COMMANDS` via `trusted_module_argv` | not the chain-root argv: it is the cancel command-line matcher (`trusted_module_argv(...)[1:]`); the chain root is built with `seat_uid.trusted_module_argv` (L-S1) |
| `patch_return.py:65`, `:80` | `ProposalReturn(status, proposal_bytes_digest, byte_length, baselines, locator)`, `WorkerResult(..., proposal, evidence_envelope_digest, journal_anchor, journal_complete)` | consume (L-S5) |
| `patch_return.py:92` | `CancelOutcome = cancelled \| already_terminal \| cancel_pending \| unknown_attempt \| owner_unverified \| owner_not_live` | consume (L-S4) |
| `patch_return.py:162` | `evidence_resolver(state_root)` | consume |
| `patch_return.py:221`, `:289` | `_audit`, `_paths` (private) | do not call (L-S5) |
| `patch_return.py:345`, `:347`, `:399` | `run_patch_return` consumes admission and reserves the JOURNAL attempt itself | consume inside the CLI process (L-S2) |
| `patch_return.py:522` | non-completed termination → `withheld_incomplete` | consume (L-S5) |
| `patch_return.py:614` | `cancel_attempt(*, state_root, run_id=None, attempt_id=None, wait_seconds, launcher_commands)` | consume (L-S4) |
| `run_status.py:1165` | `reserve_attempt(...)` — permanent, independently durable | never called by LANEEXEC (L-S2) |
| `run_status_projection.py:271` | `attempt_status(root, attempt_id, *, observer)` incl. `unknown`, `stale_unknown`, nullable identity | consume (L-S4) |
| `seat_resource_caps.py:55`, `:224`, `:245` | whole `seat_resource_caps.v1` record, `load_caps`, `caps_sha256` | consume |
| `seat_resource_caps.py:250` | `_automatic_paths()` = `staging_root()` and the child scratch dir (private) | consume indirectly; not called (L-S3) |
| `seat_resource_caps.py:330`–`:350` | `_device_plan` refuses any anonymous filesystem, tmpfs included ("carve-out cleanup is not wired", `:340`; agent-harness#2099) | consume; no carve-out is used (L-S3) |
| `seat_resource_caps.py:353`, `:368` | `io_devices(caps)`, `readiness_code()` | consume |
| `seat_resource_caps.py:650` | `capped_popen(command, *, seat_key, before_spawn=None, **popen_kwargs)` — one capped parent per key, child-side readback, a daemon reap thread that collects the parent (`:780`–`:786`) | consume with key `laneexec:<client>:<reservation_id>` and `before_spawn` never passed, called only by the detached supervisor; any exception keeps the claim (L-S3, §6 E2-1) |
| `sandbox_policy.py:807` | `staging_root()` = `resolve_staging().path` (`:768`), which may be RAM-backed or the `PHASE_LOOP_SANDBOX_STAGING_DIR` override | consume as the device witness for local attempt directories, never their location (L-S3, §6 E2-4) |
| `sandbox_policy.py:1275`; `sandbox_placement.py:2675` | `placement_state_root()`; `PlacementLifecycle.inventory` = that root `/ <client>` | consume: the client's LaneExec state directory lies under `PlacementLifecycle.inventory` (§6 E2-4) |
| `sandbox_placement.py:2530`, `:2584` | `openshell_route_state()`, `openshell_launch_refusal(config, *, workload, target_kind, providers, config_sha256, egress_sha256, route_state=None)` (agent-harness#2003) | consume (SL-3), the only openshell activation and egress check (§6 E2-2) |
| `seat_uid.py:490` | `trusted_module_argv(module, *args)` | consume for every helper launch |
| `openshell_artifacts.py:72`, `:159`, `:445` | `Bound(end, cancelled)`, `safe_path(path)`, `check_binary_literals(patch, limits, bound)` | consume |
| `openshell_worker.py:398` | `landlock_manifest(rules, uid=10001, gid=10001)` | consume |
| `capability_registry.py:772` | `default_executor_for_work_unit(work_unit_kind, *, scheduler_assigned=False)` | consume before reserve; the file is unchanged and owned by no lane (coordinator ruling 2) |
| `runner.py:6160` | `launch_harness_lane_work_unit(...)`, incl. `jevdrill_adapter` (agent-harness#2086) | extend (SL-4): the disabled-by-default placement site |
| `runner.py:4818`–`:4855` | the concurrent lane branch that calls `execute_lane_waves` | extend (SL-4): the wave guard (§6 E2-3) |
| `lane_wave_executor.py:110` | `execute_lane_waves(...)` (agent-harness#1978): launches writable lane workers through `run_phase_worker_pool` from resolved launch specs | do not touch (§6 E2-3) |
| `panel_invoker.py:4537` | `_NONLOCAL_EXECUTION_DRIVER = False` | do not touch |
| `panel_invoker.py:14106` | jailed Codex seat route | do not touch (L-S7) |
| `sandbox_placement.py`, `placement_lease.py`, `openshell_backend.py` | as left by PLACECLI (`PlacementLifecycle`, reservation journal) | extend (SL-3) after PLACECLI merges and the reservation-only walk exit (PLACECLI binding §2, §4.2); SL-3 performs every later step on a remote rung |
| `tests/data/seat_launch_references.json` | landed rows plus CLOSEOUT and PLACECLI rows | extend (SL-5) by union |

## 3. STOP decisions

### L-S1 — v2 admission seam

**Chosen: depend on CLOSEOUT; LANEEXEC adds no admission code (sweep
recommendation, adopted).** The wire sentence `x-envelope-construction.rule` ("admits it
through the v12 admission seam (supervised_launch.prepare_launch …)") binds to
CLOSEOUT's production seam:

- **Pre-claim check.** In the order position "envelope admission" (`x-launch-inputs.order`), LaunchService calls CLOSEOUT's `load_v2_binding`, `capture_launch_v2` and `prepare_launch_v2` in process on the captured envelope bytes. A refusal is `refused`, code `sandbox_launch_admission_refused`, with the pinned diagnostic and no claim. The `PreparedLaunch` is never consumed here; it is disposed through CLOSEOUT's `discard_admission` in a `finally`.
- **Authoritative admission.** After the claim, the supervisor writes the per-attempt controller document at the path CLOSEOUT binding §4.2 derives from the envelope bytes. It then starts exactly one chain root, `seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", "launch", "--envelope", …, "--result", …)`, through `capped_popen` for a local target (L-S3). The CLI re-admits the same bytes, consumes once and reserves the JOURNAL attempt. A CLI refusal there, or an inner WORKER refusal after it, is a failure after the first chain process: `finished`, termination `failed_to_start`, claim kept (`x-exec.after_start`; L-S4).
- **Status mapping.** LANEEXEC consumes CLOSEOUT's `WorkerResult`-to-v2 mapping
  (CLOSEOUT binding §4.3) and maps v2 states to the wire only through §3 L-S4.

### L-S2 — exec claim versus the permanent JOURNAL reservation

**Chosen: keep the JOURNAL reservation worker-owned and make the claim a single
durable write in the placement journal only (sweep option 2).** The sweep's
requirement (durable ordering, partial-failure recovery and fresh-attempt
behavior specified; two writes never called atomic) is met as follows. The wire
sentence `x-exec.one_exec` ("sets LeaseFlags.exec_claimed and reserves the
attempt_id through the v12 journal") is bound to:

1. The claim is one compare-and-set under the reservation's journal lock that
   sets `LeaseFlags.exec_claimed` and records the launch `request_id`. It does
   not touch the JOURNAL.
2. The JOURNAL attempt is reserved later, by `run_patch_return` inside the CLI,
   which is the first chain process.
3. Every claim rollback in `x-exec.claim_rollback` happens before the first chain
   process, so no JOURNAL reservation can exist when a claim is rolled back. A
   new `request_id` may therefore relaunch with the prepared
   `run_id` = `attempt_id` (`x-prepare.values`) without colliding with a
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
- **Location.** Each local attempt's execution tree, home, out and scratch directories live under the selected client's LaneExec state directory (`x-snapshot.upload` and `x-seed.provisioning`), in a 0700 per-reservation directory whose ancestors meet `x-seed.provisioning`'s ownership rule. These are the `x-argv-templates.slots` host paths.
- **Device rule.** At prepared-path verification (`x-launch-inputs.order`, pre-claim), each directory must have the same `st_dev` as `sandbox_policy.staging_root()`, the landed automatic path whose whole device `io_devices(load_caps())` plans. `staging_root()` is a device witness only; it never chooses a location. A tmpfs, any anonymous filesystem, or another device refuses with `sandbox_placement_capability_unmet`, zero invocations and no claim.
- **No carve-out in v1.** `x-local-cgroup.automatic_paths`'s "including the caps contract §1a tmpfs carve-out" is read as "excluding" until SEATS ships the carve-out; adopting it later needs no wire change. `readiness_code()` still checks both landed automatic paths (`seat_resource_caps.py:250`, `:368`), so a host whose staging root or child scratch directory is tmpfs refuses at the readiness steps.
- **Chain-start re-check.** After the claim and immediately before `capped_popen`, the supervisor repeats `readiness_code()`, the device rule, and a comparison of `caps_sha256(load_caps())` against the reservation's `seat_caps_sha256`. A failure is `x-exec.claim_rollback`'s chain-start caps re-check: nothing has started, the claim rolls back, and the code is `sandbox_placement_capability_unmet`.
- **`capped_popen` failures.** Any exception from `capped_popen` keeps the claim and yields `finished`, termination `failed_to_start`, code `sandbox_placement_capability_unmet` (`x-exec.claim_rollback`, "rollback is never inferred", and `x-local-cgroup.refusal`). The landed API raises one refusal for failures both before and after its helper starts (`seat_resource_caps.py:642`–`:646`, `:788`–`:797`).
- **Capped parent.** The detached supervisor calls `capped_popen` with key `laneexec:<client>:<reservation_id>` (`x-local-cgroup.parent`); the short-lived `agent-harness-launch` process never does. The supervisor waits on the returned process for the attempt's life. The landed collection is a daemon reap thread in the supervisor's process that waits on the child and then releases the parent (`seat_resource_caps.py:780`–`:786`), so the parent is collected when the child ends while the supervisor lives (§6 E2-1). Reaping a dead supervisor's attempt relies on parent-death SIGKILL (`x-lifetime.supervisor_death`) and reports the capped parent as `cleanup_pending`. LaneExec never reconstructs a private unit or cgroup name.
- LaneExec adds no `seat_resource_caps` API and calls none of its private functions. **ACTIVATE prerequisites** (SEATS-owned, not built here):
  - an expected-digest check inside `capped_popen`, which reloads caps at `:665`;
  - typed evidence of whether a failure came before or after the helper started;
  - kill/collect of a capped parent by key. `__all__` (`:798`–`:802`) exports neither. Filed as agent-harness#2098.
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
status record. LaneExec writes its terminal before it returns. Before the first chain process, that terminal is a pre-claim refusal or a claim rollback (`refused`). After it, the terminal is built from `WorkerResult` through CLOSEOUT §4.3. Every refusal at or after the first chain process is `finished`, termination `failed_to_start`, claim kept (`x-exec.after_start`). That includes the CLI's own refusal and an inner WORKER terminal `refused` written after `reserve_attempt` (`patch_return.py:397-399`). A result CLOSEOUT maps to `unknown` is recorded as `uncertain`. Readable JOURNAL bytes alone never establish acknowledgement. A following `status` reports what this table yields. It does not promise to tell a signalled cancel from a zero-signal one, because the two can race. The pure mapping functions live in
`launch_return.py` (SL-2) and are tested as closed tables.

### L-S5 — return for non-completed attempts

**Chosen: reuse WORKER's fail-closed withholding for `patch` and specify
`result` and `none` separately (sweep recommendation, adopted).** The wire
sentences `x-return.patch` and `x-return.termination` bind to:

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
refusal at any step through `pre_exec` (`x-launch-inputs.order`), claim, upload,
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

**Chosen: no repin for the grant spelling.** The PLACECLI bytes are unchanged;
the LANEEXEC bytes change only by erratum LANEEXEC-v1-errata-1, which does not
touch the grant rule. The envelope grant is derived by the field rule
`x-envelope-construction.fields["launch.grants.egress_policy_sha256"]` (bare 64 hex after the
`sha256:` prefix), which already governs; the PLACECLI `launch_binding` sentence
is non-normative on that spelling (PLACECLI binding §3 P-S2). This deviates from
the sweep (hold until an input revision is approved) for the reason recorded
there.

## 4. Cross-repo consequences

- agent-toolkit (IF-XR-1): members, verbs and exit classes are unchanged. The
  artifact digest and the local `template_sha256` change by erratum
  LANEEXEC-v1-errata-1, and the toolkit re-vendors once.
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

## 6. Erratum LANEEXEC-v1-errata-2 (2026-11-23): landed-code drift and readiness

This erratum covers the plan and this binding only. No wire byte, member, code, verb or exit
class changes, the `x-errata` member keeps its one entry, and agent-toolkit does not repin.
It re-anchors §2 to `origin/main` at `4dd77878afe58c429b01969c32c89b755a820002`. It also
binds five landed changes that came after the re-plan baseline (E2-1 to E2-5) and scopes
one unowned activation input (E2-6). Each item lists the lane that owns its tests. The
phase plan cites these items by ID.

### E2-1 — `capped_popen` after agent-harness#2033

**Landed.** The signature is `capped_popen(command, *, seat_key, before_spawn=None,
**popen_kwargs)` (`seat_resource_caps.py:650`). `before_spawn` is called once, after every
preflight check and immediately before the child is created (`:726`–`:728`). Collection
is a daemon reap thread in the caller's process. It waits on the child and then releases
the parent (`:780`–`:786`). Every refusal still raises one `SeatSandboxRefused`
(`:642`–`:646`, `:788`–`:797`), so the L-S3 failure reading is unchanged.

**Ruling: LaneExec never passes `before_spawn`.**

- The claim is durable before the supervisor calls `capped_popen`, and L-S3 keeps the
  claim on any exception from it. A "spawn reached" signal would change no outcome.
- The callback is untyped. It is not the typed before/after-helper-start evidence that
  activation requires (agent-harness#2098).
- An exception raised by the callback other than `OSError`, `ValueError` or
  `SubprocessError` propagates without the landed refusal and without releasing the
  parent, which `capped_popen` has already acquired.

**Rebinding of L-S3 "Capped parent".**

- The supervisor waits on the returned process for the attempt's life.
- While the supervisor lives, its reap thread collects the parent when the child ends.
- The thread is a daemon, so it would die with an exiting supervisor before it released
  the parent. After `wait()` returns, the supervisor therefore stays alive until every
  thread in `threading.enumerate()` that was not present immediately before its
  `capped_popen` call has ended, bounded by the attempt's release deadline. Its own
  renewal and bridge threads predate that call and are not waited on. It never names,
  joins by name or replaces the landed thread. On timeout it records the capped parent
  `cleanup_pending`.
- A dead supervisor's thread dies with it, so `x-lifetime.supervisor_death` still yields
  `cleanup_pending`. Kill and collect by key remain agent-harness#2098.

**SL-3.1 obligations.**

- The injected `capped_popen` fake records `before_spawn is None` on every call.
- A mutation that passes a callback fails.
- A supervisor killed after chain start reports its capped parent `cleanup_pending`,
  never collected.
- A supervisor whose child has ended does not exit while the reap thread runs. A
  mutation that exits immediately after `wait()` fails.
- A supervisor that runs its own long-lived thread, started before `capped_popen`, still
  exits promptly once the reap thread ends, and records no `cleanup_pending`.

### E2-2 — SL-3 zero-egress amendment (agent-harness#2003)

**Source of the ruling, quoted exactly.** agent-toolkit `docs/placement-consolidation.md`
at `b4f403dc66c15ad44ddeaccfa608573df499d4ee` (blob
`f4a0c094ea82ecb1d8a4a48e98c53b10910ab2cd`):

> **Owner egress ruling (2026-11-19).** The remote Pi sandbox gets zero direct network egress to
> model providers. Model traffic goes only over the link to the requester's credential proxy.
> agent-harness implements this as link-only providers (Consiliency/agent-harness#2003, below). The
> ruling is met in full only at ACTIVATE.

agent-harness#2003 (merge `0eac43f035afb42ae26d13649c5843fba2226d05`) records the same
decision. Its description says: "Zero egress is met only once a follow-up planning change
(the ACTIVATE goal plus a LANEEXEC SL-3 amendment), LANEEXEC's launch-service wiring and
ACTIVATE evidence land. No production code calls the new launch check yet." This section
is that LANEEXEC SL-3 amendment. The ACTIVATE goal is a separate roadmap amendment, not
made here and tracked by agent-harness#2104.

**Binding.**

- **When the check runs.** At the order position "activation" (`x-launch-inputs.order`),
  for every openshell target, `LaunchService` calls
  `sandbox_placement.openshell_launch_refusal(config, workload=…, target_kind="openshell",
  providers=…, config_sha256=…, egress_sha256=…)`.
- **What it is called with.** `config` is the effective configuration whose bytes
  `x-launch-inputs.config_binding` captured for this launch. The other values are the
  reservation's.
- **The only openshell check.** This call is the single implementation of the three
  conditions of `x-activation.remote` and of the link-only provider rule. LaneExec never
  re-derives the route state, never calls `openshell_route_state` directly, and never
  inspects provider endpoints itself.
- **Test seam.** `route_state` is injectable only at `build_launch_service`. Its default
  is the landed `openshell_route_state`.

**Result mapping.** Every result except `None` refuses with zero invocations and no
claim, before snapshot.

| Returned | LaunchResponse |
| --- | --- |
| `None` | continue |
| `sandbox_launch_input_mismatch` | `refused`, that code |
| `sandbox_launch_route_disabled` (route state not `enabled`, `unknown` included; a pi-runner provider that grants egress; a non-empty remote baseline; a declared name that is not a configured link-only provider) | `refused`, that code |
| `launch_input_unbound` | `refused`, code `sandbox_launch_admission_refused`, `admission_diagnostic` `launch_input_unbound` (the pinned diagnostic of `x-envelope-construction.fields["launch.grants.egress_policy_sha256"]`) |

**Consequences.**

- An admitted openshell `pi-runner` launch carries a grant with no rule. Its envelope
  binds that grant's digest, so model traffic can only use the credential-proxy link,
  through the bridge (IF-XR-3).
- L-S7 is unchanged. Under shipped defaults every openshell launch is still
  `sandbox_launch_route_disabled`, now by this check.
- The dormant reserve-time gate of agent-harness#2003 stays defence in depth. It is not
  this boundary.

**SL-3.1 obligations.**

- Each row of the table, entered through `build_launch_service` with a temporary operator
  configuration, including a configuration changed after reserve.
- An endpoint-form pi-runner provider refuses.
- The `unknown` route state refuses.
- The zero-effect counters of L-S6 hold.

**SL-3.3 mutations.** Each of these fails through a production path:

- skipping the call;
- calling it with a re-read configuration instead of the captured one;
- mapping `launch_input_unbound` to any other code;
- replacing it with a local route-state computation.

### E2-3 — the second writable-lane launch path (agent-harness#1978)

**Landed.** Production does not launch writable lanes through the site §2 named.

- `runner.py:4818`–`:4855` calls `lane_wave_executor.execute_lane_waves`
  (`lane_wave_executor.py:110`) for concurrent waves.
- That function starts writable lane workers through `run_phase_worker_pool`, from
  launch specs that `prepare_lane` builds in `runner.py`.
- `launch_harness_lane_work_unit` (`runner.py:6160`) has no production caller in the
  package.
- The serialized scheduler path only records work-unit state.

The wave path can therefore launch writable `lane_execute` units, and no proof that it
cannot is possible.

**Ruling: SL-4 owns both paths at `runner.py`.**

- **Placement disabled** (shipped default). Both paths keep their launch and argv
  byte-identical. The runner's wave `event` wrapper also records route `interim_local`
  for each wave lane, as `x-activation.lane_placement` requires.
- **Placement enabled.** The concurrent branch never calls `execute_lane_waves`. Before
  any lane worktree, reservation or spawn, it ends the wave `blocked`, reason
  `lane_placement_wave_unrouted`, with no fallback to the local pool or to serial
  dispatch. Writable lanes are placed only through `launch_harness_lane_work_unit` →
  `lane_launch.place_lane`.
- **Guard position and coverage.** The guard runs after the `jevdrill_adapter` and
  `lane_recovery_blocker` checks and after the capacity computation. `capacity.effective
  < 2` keeps its whole-phase serial outcome, which is outside SL-4. With capacity of at
  least 2 the guard blocks every concurrent dispatch. That includes plans that
  `execute_lane_waves` would have returned `serial` for (`no_verified_lanes`,
  `executor_pin_conflict`, `ownership_ambiguous`, `serial_selection`), a single-lane
  plan among them.
- **Out of scope.** Routing concurrent waves through `place_lane` is an ACTIVATE item
  (plan Deferred Items; agent-harness#2103).
- **Unchanged files.** `lane_wave_executor.py` and `worker_pool.py` are not edited.
- **`jevdrill_adapter` (agent-harness#2086).** The parameter is kept. With placement
  enabled, a call that passes an adapter refuses typed before reserve, because the
  adapter builds its own launch request.
- **Whole-phase dispatch.** A whole-phase serial dispatch is not a `lane_execute` work
  unit. It stays outside SL-4, as it was before this erratum.

**Falsifiers (SL-4.1, entered through the runner's dispatch).** Each of these fails the
test:

- with placement enabled and a concurrent wave of at least two ready lanes and
  capacity of at least two, `execute_lane_waves` is reached, a lane worktree is created,
  or the worker-pool spawn counter is not zero;
- with placement disabled, the wave's launch specs differ from those built without this
  change;
- with placement enabled and capacity of at least 2, a single-lane plan ends anything
  other than `blocked`;
- with placement enabled and capacity below 2, the dispatch ends anything other than its
  whole-phase serial outcome;
- an adapter call reserves.

A mutation that removes the guard must fail the first falsifier.

### E2-4 — `staging_root()` as device witness

**Landed.**

- `staging_root()` returns `resolve_staging().path` (`sandbox_policy.py:768`–`:808`).
- That path is the honoured `PHASE_LOOP_SANDBOX_STAGING_DIR` override, which may be
  RAM-backed, or a degraded fallback that may be RAM-backed.
- Under `PHASE_LOOP_SANDBOX_REFUSE_RAM=1`, `staging_root()` raises
  `SandboxRamBackedError`. That is a `RuntimeError`, which `readiness_code()` does not
  catch (`seat_resource_caps.py:368`–`:383`, via `_automatic_paths`).

**Confirmation: the L-S3 device rule still refuses both new cases.** The rule is read as
two checks, and both are required:

1. Each attempt directory's own filesystem is neither tmpfs nor any other anonymous
   filesystem (major device 0, ramfs included).
2. That directory's `st_dev` equals `staging_root()`'s.

The cases resolve as follows:

- **RAM-backed witness.** The attempt directory either shares the witness's anonymous
  device, which check 1 refuses, or has another device, which check 2 refuses.
  `readiness_code()` refuses independently, earlier in `x-launch-inputs.order`, because
  `_device_plan` refuses an anonymous automatic path.
- **Override to another block device.** Check 2 refuses.
- **Override on the attempt directory's block device.** This is admitted. It is correct,
  because `capped_popen` plans `io.max` on that same whole device.
- **An exception from `staging_root()` or `readiness_code()`.** This is
  `sandbox_placement_capability_unmet`, raised before the claim, or as the chain-start
  rollback in the supervisor. It is never an uncaught error.

**Which process is authoritative.** The supervisor's chain-start re-check runs in the
process that calls `capped_popen`, under that process's environment. Its result governs.
A witness that differs from the pre-claim one rolls the claim back
(`x-exec.claim_rollback`).

**Location.** The client's LaneExec state directory lies under
`PlacementLifecycle.inventory` (`placement_state_root()` `/ <client>`), which is derived
from the account home and no environment variable. The override can therefore change
only the witness, never a location.

**SL-3.1 obligations.**

- A tmpfs override with the attempt directory on the same tmpfs refuses. This case
  passes check 2 and must fail check 1.
- A tmpfs override with a block-backed attempt directory refuses.
- A block override on another device refuses.
- A block override on the same device is admitted.
- `PHASE_LOOP_SANDBOX_REFUSE_RAM=1` with a RAM-backed candidate refuses
  `capability_unmet`, with no claim and zero invocations.
- A witness that changes between prepare and chain start rolls the claim back.

Every case runs through `build_launch_service`, with `readiness_code` injected and
`staging_root` exercised for real through environment and mount fixtures. SL-3.3 adds a
mutation that keeps only check 2, which must fail.

### E2-5 — bookkeeping

**The panel.** The advisor-board panel on the re-plan returned AGREE-WITH-EDITS on
2026-11-09
(https://github.com/Consiliency/agent-harness/pull/1966#issuecomment-6744806830). Its
edits are applied in `6da287e181b9f3768e4f314f4e799b43e185b415`. The verdict reads: "A
coordinator delta check is enough; another board round is not needed." The coordinator
merged agent-harness#1966 after that commit.

**Work-start gates.** Both are met:

- the CLOSEOUT gate, by agent-harness#1970;
- the PLACECLI gate, by agent-harness#1971, agent-harness#1991 and agent-harness#2003.

**Manifest.** The `v13-LANEEXEC` row records this with `review_status`
`board_edits_applied_coordinator_delta_checked`, the same `board_edits_applied_*` shape
`v12-WORKER` uses, and one
appended, hand-written `committed` event (agent-harness#1968 is still open). The one
remaining gate is the separate execution authority the plan names.

**Frozen inputs.** Only this artifact's bytes change. Its pin in the manifest row is its
only pin site. Every other frozen input keeps its bytes and its seal.

### E2-6 — review-runner image (scoping only; nothing is built or pushed)

**Need.** `x-exec.route_entries.openshell` takes the landlock-exec helper path and digest
"from the pinned review-runner image, never from the request". ai-stack Unit 7
(ViperJuice/ai-stack#504) needs a distinct pinned image with platform and pull evidence.

**What exists.** `phase-loop-runtime/images/review-runner/Containerfile` already pins its
inputs:

- its base images by digest;
- the landlock-exec source revision and file hashes;
- the helper's output sha256;
- `linux/amd64`.

It copies `phase_loop_runtime` from the build context, so the image's identity also
depends on the agent-harness commit it is built from. No image digest, pin record or pull
evidence exists on main.

**What "pinned" means.** One record holds all of the following:

- the OCI image manifest digest (`sha256:…`), referenced as `<registry>/<repository>@<digest>`, never by tag;
- the platform `linux/amd64`, with the config digest of that platform's image;
- the agent-harness source commit and the Containerfile's sha256;
- the in-image helper path `/usr/libexec/agent-toolkit/landlock-exec` and its sha256;
- pull evidence: a pull by digest on the target host, then an inspection whose manifest
  digest, platform and helper sha256 equal the record.

**Consumer in LANEEXEC.** SL-3 reads the helper path and digest only from that record,
through the operator configuration. Until a record exists, tests use a fixture record.
LANEEXEC builds, pushes and pins nothing.

**RR-1, decided by the coordinator, 2026-11-22: option (c).** A small new phase in
parallel with LANEEXEC builds and pins the image and produces the pin record above, which
ACTIVATE consumes. Options (a) LANEEXEC SL-6 and (b) ACTIVATE readiness lane 1 were
rejected for the reasons recorded in the readiness audit.

**Owner grants the new phase needs.**

- the registry and repository, and push credentials;
- a build host and the build window;
- the image allowlist entry on ai-stack's side.
