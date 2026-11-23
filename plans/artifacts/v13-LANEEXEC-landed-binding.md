# v13 LANEEXEC: landed binding and STOP decisions (re-plan, 2026-11-09)

Frozen artifact for `plans/phase-plan-v13-LANEEXEC.md` (re-plan). It has no word
cap. The wire contract stays `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`,
byte-identical at its pin except for erratum LANEEXEC-v1-errata-1 (`x-errata`: one
template literal and the rule sentence that prescribes it), which agent-toolkit
vendors by digest (IF-XR-1). That erratum is the one toolkit repin. Nothing here
adds, removes or renames a wire member, enum value, code, verb or exit class, and
this artifact makes no wire change of its own. Erratum LANEEXEC-v1-errata-2 (§6) is a
plan and binding erratum only: it changes this artifact and the phase plan, never the
wire bytes, so the toolkit does not repin. Errata LANEEXEC-v1-errata-3 (§7) and
LANEEXEC-v1-errata-4 (§8) are likewise plan and binding errata only. LANEEXEC-v1-errata-5 (§9) incorporates a frozen SL-8 resolutions artifact.

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
| Landed baseline re-inspected (LANEEXEC-v1-errata-3) | `origin/main` at `2441fa0d695f23dccf150660d277872a93b3ea16`. The `file:line` citations of §7 refer to this tree; §2 keeps its v0.7.40 anchors. |
| Landed baseline re-inspected (LANEEXEC-v1-errata-4) | `origin/main` at `8856634492df9dd55a6cac2dca65f48464fb9222`. §8 cites no `file:line`. |
| Integrated SL-8 input (§9) | `origin/main` at `f5ffefc50ccc582eeb8fee82368599c73d4c2121` |
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
| `sandbox_placement.py:2530`, `:2584` | `openshell_route_state()`, `openshell_launch_refusal(config, *, workload, target_kind, providers, config_sha256, egress_sha256, route_state=None)` (agent-harness#2003) | consume (SL-8, §7 E3-3), the OpenShell host activation and egress check alongside the client opt-in (§6 E2-2) |
| `seat_uid.py:490` | `trusted_module_argv(module, *args)` | consume for every helper launch |
| `openshell_artifacts.py:72`, `:159`, `:445` | `Bound(end, cancelled)`, `safe_path(path)`, `check_binary_literals(patch, limits, bound)` | consume |
| `openshell_worker.py:398` | `landlock_manifest(rules, uid=10001, gid=10001)` | consume |
| `capability_registry.py:772` | `default_executor_for_work_unit(work_unit_kind, *, scheduler_assigned=False)` | consume before reserve; the file is unchanged and owned by no lane (coordinator ruling 2) |
| `runner.py:6160` | `launch_harness_lane_work_unit(...)`, incl. `jevdrill_adapter` (agent-harness#2086) | extend (SL-4): the disabled-by-default placement site |
| `runner.py:4818`–`:4855` | the concurrent lane branch that calls `execute_lane_waves` | extend (SL-4): the wave guard (§6 E2-3) |
| `lane_wave_executor.py:110` | `execute_lane_waves(...)` (agent-harness#1978): launches writable lane workers through `run_phase_worker_pool` from resolved launch specs | do not touch (§6 E2-3) |
| `panel_invoker.py:4537` | `_NONLOCAL_EXECUTION_DRIVER = False` | do not touch |
| `panel_invoker.py:14106` | jailed Codex seat route | do not touch (L-S7) |
| `sandbox_placement.py`, `placement_lease.py`, `openshell_backend.py` | as left by PLACECLI (`PlacementLifecycle`, reservation journal) | extend after PLACECLI merges and the reservation-only walk exit (PLACECLI binding §2, §4.2): `sandbox_placement.py` by SL-3, `placement_lease.py` and `openshell_backend.py` by SL-9 (§7 E3-3); SL-9 performs every later step on a remote rung |
| `tests/data/seat_launch_references.json` | landed rows plus CLOSEOUT and PLACECLI rows | extend (SL-5) by union |

## 3. STOP decisions

### L-S1 — v2 admission seam

**Chosen: depend on CLOSEOUT; LANEEXEC adds no admission code (sweep
recommendation, adopted).** The wire sentence `x-envelope-construction.rule` ("admits it
through the v12 admission seam (supervised_launch.prepare_launch …)") binds to
CLOSEOUT's production seam:

- **Pre-claim check (rebound by LANEEXEC-v1-errata-3, §7 E3-1).** In the order position "envelope admission" (`x-launch-inputs.order`), LaunchService starts one short-lived isolated helper, `seat_uid.trusted_module_argv("phase_loop_runtime.launch_admission")`. The helper calls CLOSEOUT's `load_v2_binding`, `reconcile_v2_binding` (with this attempt's §4.2 controller document, held in memory), `activate_v2_binding`, the activated codec's `decode_v2` and `precheck_v2_admission`, then `capture_launch_v2` and `prepare_launch_v2` on the captured envelope bytes, then `discard_admission` in a `finally`. It reports only the outcome and the pinned diagnostic. A refusal is `refused`, code `sandbox_launch_admission_refused`, with that diagnostic and no claim. The `PreparedLaunch` is never consumed. The helper is not a launch-chain process and starts no target. §7 E3-1 gives the full binding.
- **Authoritative admission.** After the claim, the supervisor publishes the per-attempt controller document, the same bytes the helper admitted, at the path CLOSEOUT binding §4.2 derives from the envelope bytes. A failed publication keeps the claim, starts nothing, and is the crash-after-claim terminal of §7 E3-1: `finished`, termination `failed_to_start`, `worker_invocations` 0. It then starts exactly one chain root, `seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", "launch", "--envelope", …, "--result", …)`, through `capped_popen` for a local target (L-S3). Positive CLI re-admission, consumption and JOURNAL reservation require the independently verified adapter of §9. SL-8 proves real refusal on the landed representations. A CLI refusal there, or an inner WORKER refusal after it, is a failure after the first chain process: `finished`, termination `failed_to_start`, claim kept (`x-exec.after_start`; L-S4).
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
- **Chain-start re-check.** After the claim and immediately before `capped_popen`, the supervisor repeats `readiness_code()`, the device rule, and a comparison of `caps_sha256(load_caps())` against `seat_caps_sha256` from the captured configuration already matched to the reservation's config digest. A failure is `x-exec.claim_rollback`'s chain-start caps re-check: nothing has started, the claim rolls back, and the code is `sandbox_placement_capability_unmet`.
- **`capped_popen` failures.** Any exception from `capped_popen` keeps the claim and yields `finished`, termination `failed_to_start`, code `sandbox_placement_capability_unmet` (`x-exec.claim_rollback`, "rollback is never inferred", and `x-local-cgroup.refusal`). The landed API raises one refusal for failures both before and after its helper starts (`seat_resource_caps.py:642`–`:646`, `:788`–`:797`).
- **Capped parent.** The detached supervisor calls `capped_popen` with key `laneexec:<client>:<reservation_id>` (`x-local-cgroup.parent`); the short-lived `agent-harness-launch` process never does. The supervisor waits on the returned process for the attempt's life. The landed collection is a daemon reap thread in the supervisor's process that waits on the child and then releases the parent (`seat_resource_caps.py:780`–`:786`), so completion records a collection attempt (§6 E2-1). Verified descendant death and observed parent collection are separate positive gates (`x-lifetime.supervisor_death`). Reap records capped-parent `cleanup_pending` until collection is confirmed. LaneExec never reconstructs a private unit or cgroup name.
- LaneExec adds no `seat_resource_caps` API and calls none of its private functions. **ACTIVATE prerequisites** (SEATS-owned, not built here):
  - an expected-digest check inside `capped_popen`, which reloads caps at `:665`;
  - typed evidence of whether a failure came before or after the helper started;
  - kill/collect of a capped parent by key. `__all__` (`:798`–`:802`) exports neither. Filed as agent-harness#2098.
- **Unreadable caps record (coordinator ruling 1, 2026-11-09; `prepare` code rebound by LANEEXEC-v1-errata-4, §8 E4-1).** When `load_caps()` raises `CapsUnavailable`, every verb that places or launches fails closed for every target, with zero invocations and no claim: a fresh `prepare` refuses `sandbox_launch_refused`, exit 10, and `launch` refuses `sandbox_placement_capability_unmet`, exit 10. A `prepare` replay keeps the §8 E4-1 order: a settled replay with the same canonical body returns its stored response, and a lock timeout or `sandbox_placement_end_reached` takes precedence over the caps refusal. `status` and `cancel` act on existing records and keep working. `version` still exits 0 with a schema-valid response and empty stderr: `seat_caps_sha256` is the documented sentinel `sha256(b"seat_resource_caps_unavailable")`, also carried into `config_sha256` (PLACECLI binding §3 P-S1). `--help` prints one line naming the caps state and exits 0.

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
status record. LaneExec writes its terminal before it returns. Before the first chain process, that terminal is a pre-claim refusal or a claim rollback (`refused`), or a failed controller publication after the claim, which keeps the claim (`finished`, termination `failed_to_start`, `worker_invocations` 0; §7 E3-1). That last terminal is crash-after-claim recovery, not `x-exec.after_start`. After it, the terminal is built from `WorkerResult` through CLOSEOUT §4.3. Every refusal at or after the first chain process is `finished`, termination `failed_to_start`, claim kept (`x-exec.after_start`). That includes the CLI's own refusal and an inner WORKER terminal `refused` written after `reserve_attempt` (`patch_return.py:397-399`). A result CLOSEOUT maps to `unknown` is recorded as `uncertain`. Readable JOURNAL bytes alone never establish acknowledgement. A following `status` reports what this table yields. It does not promise to tell a signalled cancel from a zero-signal one, because the two can race. The pure mapping functions live in
`launch_return.py` (SL-2) and are tested as closed tables.

### L-S5 — return for non-completed attempts

**Chosen: reuse WORKER's fail-closed withholding for `patch` and specify
`result` and `none` separately (sweep recommendation, adopted).** The wire
sentences `x-return.patch` and `x-return.termination` bind to:

| `result_kind` | Rule |
| --- | --- |
| `patch` | From the verified WorkerResult handoff of §9, using `WorkerResult.proposal` only. `returned` → the bytes at the proposal `locator`, verified against `proposal_bytes_digest`, written to the ReturnDescriptor file; a baseline path (`ProposalReturn.baselines[].path`) under a snapshot mask → `sandbox_launch_audit_failed`, return null. `absent` → return null. `withheld_incomplete` (every non-completed termination, cancelled and timed-out included) → return null, no extra code; the termination already says why. `withheld_oversized`, `withheld_malformed` → `sandbox_launch_result_invalid`. `withheld_audit_error`, `withheld_unexplained_change`, `withheld_evidence_error` → `sandbox_launch_audit_failed`. A future trusted adapter binds the effective proposal cap. At cap zero a non-empty proposal yields `sandbox_launch_result_invalid`, null return and zero bytes copied. A verified absent proposal stays null (§9). |
| `result` | LaneExec reads `{out}/result.json` after the worker ends, for every terminal state whose out directory is reachable. `out` lies outside the execution tree, so the worker's audit never sees it. Read at most the smaller of the captured return cap and the frozen result ceiling, plus one oversize sentinel byte. At cap zero any non-empty result yields `sandbox_launch_result_invalid`, null return and zero bytes copied. Strict decoding applies; a failure is `sandbox_launch_result_invalid`. |
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
snapshot, upload, envelope or invocation counters" assertion. The isolated admission
helper of §7 E3-1 is counted only by the envelope-admission counter (§7 E3-1, "Counters").

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
configuration. The controller echoes the independently resolved list solely for reconciliation (§9). A local review seat never
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
- V3 (the four SL-3 lanes of §7 E3-3): `tests/test_launch_prepare.py`, `tests/test_launch_release_reap.py`, `tests/test_sandbox_placement.py`, `tests/test_launch_routes.py`, `tests/test_launch_service.py`, `tests/test_launch_admission.py`, `tests/test_launch_local_caps.py`, `tests/test_launch_lifetime.py`, `tests/test_launch_openshell.py`, `tests/test_placement_lease.py`, `tests/test_openshell_backend.py`. Each lane runs its own files as V3a to V3d (§7 E3-3).
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
- While the supervisor lives, its reap thread attempts collection when the child ends. Without positive confirmation the supervisor records cleanup_pending.
- The thread is a daemon, so it would die with an exiting supervisor before it released
  the parent. After `wait()` returns, the supervisor therefore stays alive until every
  thread in `threading.enumerate()` that was not present immediately before its
  `capped_popen` call has ended, bounded by the attempt's release deadline. Its own
  renewal and bridge threads predate that call and are not waited on. It never names,
  joins by name or replaces the landed thread. On timeout it records the capped parent
  `cleanup_pending`.
- A dead supervisor's thread dies with it, so `x-lifetime.supervisor_death` still yields
  `cleanup_pending`. Kill and collect by key remain agent-harness#2098.

**SL-3.1 obligations (now SL-8, §7 E3-3).**

- The injected `capped_popen` fake records `before_spawn is None` on every call.
- A mutation that passes a callback fails.
- A supervisor killed after chain start reports its capped parent `cleanup_pending`,
  never collected.
- A supervisor whose child has ended does not exit while the reap thread runs. A
  mutation that exits immediately after `wait()` fails.
- A supervisor that runs its own long-lived thread, started before `capped_popen`, still
  exits promptly once the reap thread ends, and clears capped-parent debt only on independently confirmed collection.

### E2-2 — SL-3 zero-egress amendment (agent-harness#2003; launch owner SL-8 since §7 E3-3)

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
  providers=…, config_sha256=…, egress_sha256=…, route_state=service.route_state)`.
- **What it is called with.** `config` is the effective configuration whose bytes
  `x-launch-inputs.config_binding` captured for this launch. The other values are the
  reservation's.
- **Host activation and egress.** On success SL-8 separately applies the captured client route opt-in (§9). This call implements the host
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

**SL-3.1 obligations (now SL-8, §7 E3-3).**

- Each row of the table, entered through `build_launch_service` with a temporary operator
  configuration, including a configuration changed after reserve.
- An endpoint-form pi-runner provider refuses.
- The `unknown` route state refuses.
- The zero-effect counters of L-S6 hold.

**SL-3.3 mutations (now SL-8, §7 E3-3).** Each of these fails through a production path:

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

**SL-3.1 obligations (now SL-8, §7 E3-3).**

- A tmpfs override with the attempt directory on the same tmpfs refuses. This case
  passes check 2 and must fail check 1.
- A tmpfs override with a block-backed attempt directory refuses.
- A block override on another device refuses.
- A block override on the same device is admitted.
- `PHASE_LOOP_SANDBOX_REFUSE_RAM=1` with a RAM-backed candidate refuses
  `capability_unmet`, with no claim and zero invocations.
- A witness that changes between prepare and chain start rolls the claim back.

Every case runs through `build_launch_service`, with `readiness_code` injected and
`staging_root` exercised for real through environment and mount fixtures (§7 E3-4). SL-8.3 adds a
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

**Consumer in LANEEXEC.** SL-9 (§7 E3-3) reads the helper path and digest only from that record,
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

## 7. Erratum LANEEXEC-v1-errata-3 (2026-11-23): isolated pre-claim admission and the SL-3 split

This erratum covers the plan and this binding only. No wire byte, member, code, verb or exit
class changes. The `x-errata` member keeps its one entry, agent-toolkit does not repin, and
no CLOSEOUT file is edited. It answers the SL-3 implementer's STOP and the coordinator's
rulings on it (2026-11-23). E3-1 rebinds the L-S1 pre-claim check, E3-2 records the
`ClientConfig` reading, E3-3 splits SL-3 into four lanes and re-homes its obligations, and
E3-4 settles where the E2-4 mount cases run. `file:line` citations refer to the errata-3
baseline of §0.

### E3-1 — pre-claim admission in an isolated helper

**Why the L-S1 sentence could not be met.**

- `prepare_launch_v2` refuses `binding_unavailable` unless the binding carries an agreement
  and an activated codec and validator (`supervised_launch.py:566`–`:568`).
- `load_v2_binding` returns a binding without an agreement (`supervised_launch_binding.py:118`).
  Only `reconcile_v2_binding` sets one (`:321`), and only `activate_v2_binding` (`:328`)
  loads the codec and validator.
- `load_v2_binding` (`:219`) and `activate_v2_binding` (`:332`) require `sys.flags.isolated`.
  The SL-4 runner and the SL-5 launch process are not `-I` interpreters, and activation
  executes operator codec and validator bytes, which CLOSEOUT confines to isolated Python.

**Ruling (coordinator, option a, with the agent-harness#2126 review edits).** The pre-claim
check runs in one short-lived isolated helper. CLOSEOUT is consumed unchanged.

**The helper.** It is the module `phase_loop_runtime.launch_admission` (SL-8, §E3-3). The
launch order starts it once for each launch that reaches the order position "envelope
admission":

- argv `seat_uid.trusted_module_argv("phase_loop_runtime.launch_admission")` with no further
  argument, never `-m`;
- stdin and stdout are pipes, and stderr is discarded;
- working directory `/`, and an environment of `PATH=/usr/bin:/bin` only, so no ambient
  variable, and no ambient credential, reaches it. CLOSEOUT capture can still read
  operator-declared secret files (`supervised_capture_v2.py:283`–`:303`), exactly as the
  chain root does;
- its own session; the launch process kills the whole group when the helper outlives the
  admission bound (300 s, injectable at `build_launch_service`) or when the launch is
  cancelled.

The helper is not a launch-chain process. It starts no target, creates or modifies no file,
takes no lock and is not started through `capped_popen`.

**The controller document: one serialization, two pipes.**

- LaunchService builds this attempt's CLOSEOUT §4.2 controller document once per launch
  request, before the helper starts. Its four members `h`, `attempt`, `context` and `slots`
  come from the captured envelope bytes (`h` is their SHA-256), the §9 assignment derivation, prepared run identity and independently managed context and allowed slots. It is serialized once, as `supervised_envelope_v2.canonicalize_v2` of that
  document. The identical bytes go to the helper before the claim and to the supervisor
  before provisioning for publication only after claim. Nothing re-derives them.
- The helper's stdin carries one frame and is then closed: an 8-byte big-endian length and
  the envelope bytes, then an 8-byte big-endian length and the controller bytes. Each part is
  at most 1048576 bytes, the CLI's envelope cap and `read_controller_snapshot`'s cap. A short
  read, a trailing byte or an over-cap length refuses.
- The helper never creates or modifies `<controller_root>/<h>.json`, including when a file
  with equal trusted bytes already exists there. Admission writes nothing in the LaneExec
  state directory and creates no temporary file.

**Publication after the claim.** The supervisor receives the controller bytes from the
launch process over its own stdin pipe, bounded by the same cap. Before opening the destination, the supervisor compares the full stdin payload's SHA-256 against the digest of the controller bytes sent to the helper, carried separately in the trusted supervisor launch arguments. Missing, short, oversized or mismatched payloads fail publication. The digest stays in the private supervisor invocation; the CLOSEOUT CLI and its arguments stay as landed. It publishes them under
CLOSEOUT §4.2's rules: the path `<controller_root>/<h>.json`, ancestors and ownership as
§4.2 and `read_controller_snapshot` require, mode 0600, created once with `O_EXCL |
O_NOFOLLOW`, written in full and fsynced with its parent. Reuse requires every trusted reader check including single link, exclusions, owner, mode and regular file, and a complete bounded read equal to these bytes. A short, truncated or longer file is unequal. If any
step fails after the exclusive create, the supervisor unlinks the file it created (matched
by device and inode), so a partial write can never be taken for an equal existing document.

A failed publication covers a refused create, an unequal existing document, a failure after
the exclusive create, and a pipe that delivers other bytes or too many. It is not one of
`x-exec.claim_rollback`'s closed failures, and no chain process has started, so
`x-exec.after_start` does not apply. It is bound to the crash-after-claim recovery of L-S1
and L-S4:

- The claim stays held, and no chain root and no target starts.
- The supervisor writes a durable, schema-valid terminal before it returns: `finished`,
  termination `failed_to_start`, `worker_invocations` 0.
- `status` replays that terminal. A later launch for the reservation refuses
  `sandbox_launch_exec_claimed`, and reap settles the reservation through cancel and
  release.

**Calls, in order, inside the helper.**

1. Decode the controller bytes as `supervised_envelope_v2.parse_v2(controller_bytes).value`.
   Build the `AttemptBinding` from `attempt`, and apply the checks `read_controller_snapshot`
   makes after its file walk (`supervised_worker_cli.py:186`–`:221`): the member sets, `h`
   equal to the envelope digest, the digest shapes, the timeout bound, the run and attempt
   identifiers, and exclusions that are directories. No private CLOSEOUT function is called.
2. `read_binding_locator(MANAGED_BINDING)`, the locator `reconcile_v2_binding` takes.
3. `load_v2_binding(MANAGED_BINDING, workspace=…, target=…, reference_roots=…)`, with the
   exclusions from `slots`.
4. `reconcile_v2_binding(locator, binding, controller=document, attempt=attempt)`.
5. `activate_v2_binding(agreed)`.
6. `active.codec.decode_v2(envelope_bytes, bundle=active.bundle)`. A `ValueError` refuses
   with diagnostic `envelope_schema_invalid`, the CLI's translation
   (`supervised_worker_cli.py:254`–`:257`).
7. `active.codec.precheck_v2_admission(decoded, context=active.context, spec=active.spec,
   attempt=attempt)`. A non-empty result refuses through the pinned mapping below
   (`supervised_envelope_v2.py:221`–`:224`; CLI `:258`–`:260`).
8. `capture_launch_v2(spec=active.spec, context=active.context, attempt=attempt)`.
9. `prepare_launch_v2(envelope_bytes, binding=active, capture=capture, attempt=attempt)`
   (`supervised_launch.py:557`–`:578`).
10. In a `finally`: `discard_admission` on any `PreparedLaunch`, and `close()` on a capture
    that no `PreparedLaunch` took.

Steps 6 and 7 come before capture, as they do in the CLI (`supervised_worker_cli.py:254`–`:268`).
An invalid envelope therefore refuses with its pinned diagnostic before any capture I/O, and
an operator-supplied codec's prefix rules govern even when capture would also fail. The
`PreparedLaunch` is never consumed, and the helper adds no admission rule of its own. The
chain root repeats steps 6 to 9 authoritatively and keeps the file-walk checks of
`read_controller_snapshot`. A refusal that only those file-walk checks would raise, or one
from a change between admission and chain start, comes after the first chain process, so it
is `finished`/`failed_to_start` with the claim kept (L-S1, L-S4).

**What the helper returns.** It writes one JSON line of at most 4096 bytes, its terminating newline included, and exits 0:
either `{"admitted":true}` or `{"admitted":false,"diagnostic":"<value>"}`. The value is,
in order:

- `envelope_schema_invalid` for a step-6 `ValueError`;
- otherwise the first entry of the precheck result, or of `Refused.diagnostics`, that is a
  member of the pinned PLACECLI `AdmissionDiagnostic` enum;
- otherwise `Refused.reason` when it is a member;
- otherwise `codec_unavailable`, the fallback for outcomes with neither. The closed enum has
  no value for a generic helper, binding or timeout failure.

An exception inside the helper yields `codec_unavailable`. No path, envelope or controller
byte and no exception text leaves the helper.

**How LaunchService reads it.** LaunchService reads at most 4097 bytes from the helper's
stdout. The 4097th byte is the overflow signal. On receiving it, LaunchService stops reading, kills the group and returns the fallback refusal. Only
exactly `{"admitted":true}` with exit status 0 admits. Every other outcome is `refused`,
code `sandbox_launch_admission_refused`, with no claim:

- a refusal line, with its value as `admission_diagnostic`;
- any other line, extra or over-long output, or a value outside the enum;
- a non-zero exit, a signal, the admission bound, a cancel, or a spawn failure.

All but the first carry `admission_diagnostic` `codec_unavailable`. The order then continues
as frozen: `recheck_before_start`, `pre_exec`, scratch provisioning, the claim and chain
start.

**Counters (L-S6).**

- The envelope-admission counter counts admission attempts: it is 1 for a launch that
  reaches the envelope admission stage, including a refusal there or at any later step, and
  0 for a refusal before it.
- A separate helper-spawn assertion counts successful helper spawns. A spawn failure is one
  admission attempt with zero spawns.
- The helper is never a launch-chain process, a worker invocation, a chain start or an
  upload. For every refusal through scratch provisioning, `worker_invocations` and the
  chain-start counter stay 0 even though the helper ran.
- The EC-LANEEXEC-1 falsifier "a second launch for one reservation reaching the
  launch-chain counter" does not count the helper.
- An idempotent replay (same `request_id` and body) makes no admission attempt. A relaunch
  under a new `request_id` after `claim_rolled_back` makes one. The helper is never retried
  within one launch.

**SL-5 launch-inventory rows.**

- One `host-helper` row, primitive `subprocess.Popen`, module `launch_exec`, for the helper
  start. Its argv is built only by `seat_uid.trusted_module_argv`, and the
  `test_seat_launch_helpers_trusted.py` no-`-m` scan covers the call site.
- `launch_admission` joins the modules that `test_seat_launch_helpers_trusted.py` proves
  resolve from the trusted installation in any working directory.
- The helper module has no launch primitive of its own. Any reference the static scan finds
  in it is added by union with its role.
- Operator codec and validator bytes execute only inside `activate_v2_binding` and the
  activated codec's calls, in the `-I` helper. No LaneExec module calls `_load_absolute` or
  `exec`.

**SL-8 obligations (V3c).** Every case is entered through `build_launch_service`:

- One successful helper spawn per admitted launch. Its argv equals
  `trusted_module_argv(...)`, carries `-I` and no `-m`, and the helper observes
  `sys.flags.isolated`.
- Admission refuses with no claim, under the L-S6 counters, for each of these: no binding;
  a controller disagreement at `reconcile_v2_binding`; an enum diagnostic from
  `prepare_launch_v2` carried through; a non-enum reason mapped to `codec_unavailable`; a
  helper crash; extra, malformed or over-long stdout, including exactly 4097 bytes with the writer still open; a non-zero exit; a spawn failure
  (one attempt, zero spawns); the admission bound; and a cancel.
- Precedence before capture. Each case returns the pre-claim diagnostic, with no capture
  attempted and no claim:
  - a malformed envelope with a capture that would also fail independently, giving
    `envelope_schema_invalid`;
  - a pinned prefix refusal with a capture that would also fail, giving that refusal;
  - a refusal that only a fixture codec's `precheck_v2_admission` raises, giving its
    diagnostic.
- `discard_admission` runs once on each path owning a prepared token. Close an acquired capture on refusal if the token did not take ownership.
- The helper never creates or modifies `<controller_root>/<h>.json`. This includes the
  case where a file with equal trusted bytes is already there, which keeps its inode, bytes
  and mtime.
- The bytes the supervisor publishes equal the bytes piped to the helper.
- Publication failures, one at a time: a refused create, an unequal existing document, a
  failure after the exclusive create (the partial file is removed and never reused), a pipe
  delivering different bytes of the same length, and an oversized pipe payload. Each keeps the claim and starts no chain root. Each writes the
  durable terminal `finished`/`failed_to_start` with `worker_invocations` 0, which `status`
  then replays.
- A credential sentinel in the launching process's environment never reaches the helper.

**SL-8.3 mutations.** Each fails through a production path:

- admitting in process instead of in the helper;
- skipping `reconcile_v2_binding`;
- capturing before `decode_v2` and `precheck_v2_admission`;
- writing the controller document before the claim;
- passing the controller document through a file;
- reusing a partially written document;
- reading a helper failure as admitted;
- counting the helper as a chain start.

### E3-2 — `ClientConfig` and the `launch` settings object (F1)

**Confirmed by the coordinator.**

- `ClientConfig` in `build_launch_service(client, *, config: ClientConfig)` is the captured
  `sandbox_policy.PlacementClientConfig` (`sandbox_policy.py:1247`).
- LaneExec reads its settings only from that configuration's free-form top-level `launch`
  object. `config_sha256` already covers the object (`sandbox_policy.py:1540`–`:1567`;
  PLACECLI binding §4.1), so `x-launch-inputs.config_binding` holds without change.

**Who defines the shape.** The wire artifact does not freeze the object's shape. SL-7
defines it in `launch_settings.py` as a strict, closed decoder:

- Its members are the operator values the contract names: the template registry and toolkit
  pins, the image allowlist, snapshot limits, seed limits and `seed_root`, activation values
  (`local_pi_runner_launcher`, `lane_placement`, route enablement), the return cap, the two
  lifetime budgets, and the reference to the review-runner image record (§6 E2-6).
- An absent `launch` object means the shipped defaults.
- An unknown member, a wrong type, or a value outside its frozen bound makes the
  configuration invalid, as PLACECLI treats an invalid client configuration.
- Operators may only lower the frozen limits and budgets.

SL-4, SL-5 and SL-8 read settings only through this decoder. SL-8 uses only landed workload-mode defaults (§9). SL-6 documents the shape in
`docs/placement-launch-service.md`.


### E3-3 — SL-3 split into four lanes, and the obligations re-homed

**Lane identifiers.** `validate_plan_doc.py` accepts only numeric `SL-N` identifiers, so the
coordinator's SL-3a to SL-3d are numbered as below. The SL-4, SL-5 and SL-6 identifiers,
which §6 cites, stay unchanged. In §3 to §6, "SL-3", "SL-3.1" and "SL-3.3" name the former
single SL-3 lane. Its launch-order work, including §6 E2-1, E2-2 and E2-4 and the
crossed Pi pair refusal SL-0 leaves to the binding step, now belongs to SL-8.

| Coordinator label | Lane | Scope | Owned files (under `phase-loop-runtime/` unless rooted) |
| --- | --- | --- | --- |
| SL-3a | SL-3 | `build_launch_service` and its seams; prepare, status, cancel; the lifecycle hooks: prepare record, claim compare-and-set and rollback, local heartbeat write, release, cancel and reap state transitions on journaled records, verified-owner handling | `src/phase_loop_runtime/launch_service.py`, `src/phase_loop_runtime/sandbox_placement.py`, `tests/test_launch_prepare.py`, `tests/test_launch_release_reap.py`, `tests/test_sandbox_placement.py` |
| SL-3b | SL-7 | the pure route mapping, templates, registration, and the `launch` settings decoder (E3-2) | `src/phase_loop_runtime/launch_routes.py`, `src/phase_loop_runtime/launch_settings.py`, `tests/test_launch_routes.py` |
| SL-3c | SL-8 | the common launch order through the claim on both routes, including pre-claim scratch staging, activation and the lifetime gate; the isolated admission helper (E3-1); the detached supervisor with local caps, local lifetime and the local route | `src/phase_loop_runtime/launch_exec.py`, `src/phase_loop_runtime/launch_admission.py`, `src/phase_loop_runtime/launch_supervisor.py`, `src/phase_loop_runtime/launch_lifetime.py`, `tests/test_launch_service.py`, `tests/test_launch_admission.py`, `tests/test_launch_local_caps.py`, `tests/test_launch_lifetime.py`, `.github/workflows/laneexec-mounts.yml` (E3-4); §9 assigns extensions of landed modules to their producer lanes |
| SL-3d | SL-9 | the openshell route after the claim, against the fake coordinator: storage and provisioning of the staged payload, the coordinator exec, bridge attach and loss, coordinator renewal, expiry and `lifetime_exceeded` | `src/phase_loop_runtime/launch_openshell.py`, `src/phase_loop_runtime/placement_lease.py`, `src/phase_loop_runtime/openshell_backend.py`, `tests/test_launch_openshell.py`, `tests/test_placement_lease.py`, `tests/test_openshell_backend.py` |

Owned files are disjoint. Each test file belongs to the lane in its row, and V3a to V3d run
exactly those files.

**Scheduling.**

- SL-3 and SL-7 run in parallel. `build_launch_service` stores the captured configuration.
  It does not decode settings or consult the route table, so construction, `prepare`,
  `status` and `cancel` operate before SL-7. Settings and activation calls happen only at
  the launch entry point (SL-8) and in `version_response` (SL-5).
- The reduced order is:
  - SL-1, SL-2 and SL-7 after SL-0;
  - SL-3 after SL-2;
  - SL-8 after SL-1, SL-3 and SL-7;
  - SL-9 after SL-8;
  - SL-4 and SL-5 after SL-9;
  - SL-6 after SL-4 and SL-5.
- A lane that names another lane's interface under "Interfaces consumed" also keeps a direct
  `Depends on` edge to it. The runtime lane IR fails closed without one
  (`missing_producer_dependency`, `plan_ir.py:498`). The docs reducer SL-6 also depends on
  every producer lane (`validate_plan_doc.py` check (M)). Those edges are implied by the
  order above and do not change it. Every other edge is removed.

**Lifetime.**

- The lifetime-budget check and the `ttl_s` floor run at the common pre-snapshot gate on
  both routes. They belong to SL-8.
- The local supervisor cannot run without renewal (`x-lifetime.liveness`: a local
  heartbeat is the durable journal and slot write). So the renewal clock, fencing, local
  renewal, local lifetime exhaustion and local supervisor death belong to SL-8 (V3c). An SL-3a precursor extends its durable write with the bounded confirmation and fence in §9.
- Coordinator renewal, its reply faults, coordinator expiry and `lifetime_exceeded`, remote
  supervisor death and remote non-overlap belong to SL-9 (V3d).

**Zero-egress (§6 E2-2).** This is the common order's activation decision, based on the
captured configuration, so it belongs to SL-8:

- The E2-2 entry-point tests run in V3c, together with the shipped-default mutation "reach
  a coordinator". Each asserts the refusal before the late-bound openshell entry, with zero
  coordinator calls.
- The coordinator-contacting controls run in V3d.

**The staging seam between SL-8 and SL-9.**

- SL-8 owns common pre-claim scratch staging on both routes. After the claim it passes the
  immutable staged payload and retained return path to SL-9's late-bound openshell entry, under the generation and lease protocol of §9.
- SL-9 owns what remote storage and provisioning return:
  - the confirmed-empty scratch provisioning result, with `scratch_unprovisioned`;
  - its rollback and relaunch;
  - upload results.
- A remote check that fails before the claim stays in SL-8 when it can be tested without
  the late-bound entry.
- Remote positive controls that actually upload and run belong to SL-9. These include the
  canonical root and relaunch after a refusal.

**Seams between the lanes.**

- `build_launch_service` (SL-3) provides caller-side seams. The detached entry reconstructs trusted defaults and the core accepts explicit in-process test effects (§9). The
  defaults are the landed functions. The seams are:
  - `capped_popen`, `load_caps` and `readiness_code`;
  - `route_state` (§6 E2-2);
  - the clock;
  - the admission bound (E3-1);
  - the placement lifecycle that PLACECLI tests already inject.
- `LaunchService.launch` (SL-3) is one call to `launch_exec.launch_attempt` (SL-8), imported
  at call time. The openshell entry after the claim (SL-8) is one call to `launch_openshell`
  (SL-9), also imported at call time.
- No test of an earlier lane enters a late-bound call. No production caller exists before
  SL-9 merges, because SL-4 and SL-5 start after it.
- SL-8 consumes the §9 precursor extensions from SL-2, SL-3a and SL-7 after their owner checks. Each keeps its assigned files.

**Verification.** V3 splits by lane: V3a (SL-3), V3b (SL-7), V3c (SL-8) and V3d (SL-9) run
their own lane's test files. V3 is their union (§5).

**Re-homing of the former SL-3.1.** Every obligation has exactly one owner:

| Obligation | Lane |
| --- | --- |
| C2 registration matrix (17 roles, the 16-file closure one file at a time, manifest form, image links, positive case) at `launch_routes.register_templates`, the one registration function, which no test double replaces | SL-7 |
| C2 production refusals through `build_launch_service`, one per refusal class, with zero snapshot reads, uploads, envelopes and invocations; the registration-to-start recheck | SL-8 |
| The pure route mapping: the L-S7 table as a closed function, template selection and argv expansion, naming the other target's template, a `template_sha256` mismatch, and the local template's LANEEXEC-v1-errata-1 form (E1, E2) | SL-7 |
| Production launch refusals: `route_disabled` under shipped defaults, `toolkit_interim` for local `pi-runner`, local `leg`/`qualification` always `route_disabled`, and crossed Pi pairs, each path-entered with zero invocations | SL-8 |
| C11 prepare values, idempotency, replay, clock, the refusals, cleanup on release and reap, races of prepare against release and reap, and the status echo schema | SL-3 |
| C11 launch echo, relaunch after rollback reusing the values, expiry between seed capture and claim, and two complete concurrent launches leaving one claim | SL-8 |
| The claim compare-and-set under a barrier; L-S4 status and cancel through the service on journaled records; release, cancel and reap state transitions at the lifecycle hook; verified-owner handling there; caller-scoped reap with other inventories invisible | SL-3 |
| Unreadable caps (coordinator ruling 1): `prepare` refuses and `status`/`cancel` keep working | SL-3 |
| Unreadable caps: `launch` refuses for every target | SL-8 |
| L-S6 stage-scoped counters; the bare-hex egress grant; claim order with a crash injected between each step, rollback only before the first chain process, relaunch under a new `request_id`, and claims kept after it (L-S2) | SL-8 |
| C4 on the common order and the local route: the paths echo and built-root checks, `not_armed`, recheck differences, configuration-digest cases, the chain-start caps re-check and `link socket` rollbacks | SL-8 |
| C4 on the remote route after the claim: an upload confirmed empty, an unknown upload, `duplicate_binding` | SL-9 |
| The chain root through `trusted_module_argv` and `capped_popen` with key `laneexec:<client>:<reservation_id>`; the controller document at its envelope-digest path only | SL-8 |
| Local attempt directories outside the state directory, on another filesystem or on tmpfs; the caps digest changed before chain start; `capped_popen` exceptions keeping the claim (L-S3); an inner WORKER refusal reported by launch and by `status` after restart (L-S4); a changed `launch` referent | SL-8 |
| C5 local caps | SL-8 |
| C6 lifetime budget and `ttl_s` floor on both routes; local clock boundaries, fencing, lifetime exhaustion and supervisor death | SL-8 |
| C6 on the fake coordinator: each reply fault, coordinator expiry and `lifetime_exceeded`, remote supervisor death letting the lease lapse, remote non-overlap, and a fenced lease not released early | SL-9 |
| C7 local end to end: cancel through the verified owner, release cancelling a live attempt and then `cleanup_pending`, and reap of a dead supervisor with capped-parent `cleanup_pending` evidence | SL-8 |
| C7 remote end to end: cancel, release and reap with coordinator and bridge evidence (there is no remote capped parent); bridge loss | SL-9 |
| C10 seed refusals before the claim, common scratch staging, local provisioning and ancestor cases, local `scratch_path` echo, and source lifetime | SL-8 |
| C10 remote storage and provisioning: the fake-coordinator path cases, confirmed-empty provisioning with `scratch_unprovisioned` and its rollback and relaunch, an unknown provisioning result, remote `scratch_path` echo, and the remote positive controls | SL-9 |
| §6 E2-1, E2-2 (entry point) and E2-4 obligations | SL-8 |
| §7 E3-1 obligations: the V3c tests that E3-1 lists, not a separate set | SL-8 |
| §6 E2-6: the helper path and digest read only from the fixture image record | SL-9 |

**Re-homing of the former SL-3.3 mutations.**

| Mutation | Lane |
| --- | --- |
| Drop the capped parent; skip the claim write at launch; launch after `pre_exec` refuses; roll back after the first chain process; accept a tmpfs attempt path; claim before `pre_exec`; hash the raw client configuration file | SL-8 |
| Reach a coordinator under shipped defaults (asserted before the late-bound entry, zero coordinator calls) | SL-8 |
| A compare-and-set that lets two claims through under the barrier; assign a new `run_id` on replay; skip the clock check before the journal read; leave the prepare record after reap | SL-3 |
| Accept a prefix-matched `tree_path`; accept a launch whose paths differ from the record | SL-8 |
| The C10 service mutation controls, each through `build_launch_service`: follow a symlink in the seed source, re-read seed bytes after capture, skip the size check, drop the manifest reference from `launch.references`, open an entry before the digest check. SL-1's existing seed-reader tests stay with SL-1. | SL-8 |
| Swallow a renewal failure with an injected local heartbeat-write fault | SL-8 |
| Swallow a renewal failure with an injected coordinator renewal fault | SL-9 |
| Roll back an unknown upload; upload from the source instead of the staged capture | SL-9 |
| §6 E2-1, E2-2 and E2-4 mutations, and the §7 E3-1 mutations (the V3c mutations listed there) | SL-8 |

### E3-4 — where the E2-4 mount cases run (F3)

**The five mount cases.** They live in SL-8's `tests/test_launch_local_caps.py`. The attempt
root and the `PHASE_LOOP_SANDBOX_STAGING_DIR` override are placed independently, so the
cross-device controls can be built:

| Case | Attempt root | Staging override | Expected |
| --- | --- | --- | --- |
| M1 | primary block | primary block (same device) | admitted |
| M2 | primary block | second block | `capability_unmet` |
| M3 | tmpfs | tmpfs (same) | `capability_unmet` (check 1) |
| M4 | primary block | tmpfs | `capability_unmet` |
| M5 | primary block | verified tmpfs alias with `PHASE_LOOP_SANDBOX_REFUSE_RAM=1` | observe real `staging_root()` raising `SandboxRamBackedError` before device comparison, then `capability_unmet`, no claim, zero invocations |

The witness-change case (§6 E2-4) needs no mount and stays an ordinary V3c case.

**Fixtures, discovered and never mounted.** No test mounts anything or calls `sudo`. The
cases read two variables:

- `PHASE_LOOP_TEST_TMPFS_DIR`: a writable directory whose filesystem is tmpfs by `statfs`
  magic.
- `PHASE_LOOP_TEST_SECOND_BLOCK_DIR`: a writable directory on a block device (major device
  not 0) other than the primary block device of the test's attempt root.

The test places the client's LaneExec state directory on the fixture filesystem through the
state-root seam that the other V3 tests use. When a variable is unset or its check fails, the
case skips with the exact reason `E2-4 mount fixture unavailable: tmpfs` or `E2-4 mount
fixture unavailable: second block device`. With `PHASE_LOOP_TEST_REQUIRE_MOUNTS=1` set, it
fails instead of skipping.

**Where they run.** SL-8 adds `.github/workflows/laneexec-mounts.yml`:

- It runs on `ubuntu-24.04` with Python 3.12 and the locked environment, and follows the
  repository's workflow tests (`test_python_floor_1546.py`).
- `ci/seat-caps-host.sh provision`, consumed unchanged, attaches its private loop-backed
  ext4 filesystem. A 0700 directory under `ci/seat-caps-host.sh mountpoint` is
  `PHASE_LOOP_TEST_SECOND_BLOCK_DIR`.
- Bind-mount a private 0700 tmpfs directory beneath trusted ancestors. Verify tmpfs there and set `PHASE_LOOP_TEST_TMPFS_DIR` to that alias for the witness and M3 attempt. Verify both block devices independently and assert M3 reaches check 1.
- It sets `PHASE_LOOP_TEST_REQUIRE_MOUNTS=1` and runs exactly the M1–M5 node IDs,
  serially, under `timeout 600`, writing a JUnit XML report. An always-run step uploads that report as the
  artifact `laneexec-mounts-junit`. The mount suite writes a JUnit testsuite property named
  `PHASE_LOOP_TEST_REQUIRE_MOUNTS` containing the effective setting observed by the mount
  fixture. SL-6 requires that property to equal `1` in the suite reporting M1–M5 and rejects
  a missing property or any other value. Separate `always()` steps unmount the tmpfs alias and run `ci/seat-caps-host.sh teardown`.
- Triggers: `workflow_dispatch`, kept so that receipt evidence can be produced at any head,
  and `pull_request` on these paths:
  - `phase-loop-runtime/src/phase_loop_runtime/launch_*.py`;
  - `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py`;
  - `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py`, the inventory hook;
  - `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps*.py`;
  - `phase-loop-runtime/tests/test_launch_local_caps.py`;
  - the workflow itself and `ci/seat-caps-host.sh`.

**Receipt gate (SL-6).** The SL-6 receipt is accepted only with all of the following, at
the receipt's head:

- a run of `laneexec-mounts` at exactly that head;
- its `laneexec-mounts-junit` artifact;
- that artifact showing each of M1–M5 as passed (not skipped, not errored);
- the testsuite property `PHASE_LOOP_TEST_REQUIRE_MOUNTS` equal to `1` in the suite
  reporting M1–M5; a missing property or any other value refuses. A pytest pass entry by
  itself does not record the effective environment.

A green job alone does not satisfy it. The receipt's head is an observed input at acceptance
time, not a pinned output.

**The gap, stated.** The workflow is not a required check. The `test.yml` pytest lanes and
Gate A provide no second block device, and shared hosts and V3 runs without the variables
skip these cases with the named reasons. So ordinary required CI still has no mount
regression gate. The SL-6 receipt gate above covers phase acceptance only. Making the
workflow required is a `CONTRIBUTING.md` change outside this phase.

## 8. Erratum LANEEXEC-v1-errata-4 (2026-11-23): caps-unreadable `prepare` code and the openshell runtime record

This erratum covers the plan and this binding only. No wire byte, member, code, verb or exit
class changes, the `x-errata` member keeps its one entry, agent-toolkit does not repin, and
§6 E2-6 is unchanged. It records two coordinator rulings of 2026-11-23 on implementer STOPs:
E4-1 from SL-3 (agent-harness#2138) and E4-2 from SL-7 (agent-harness#2134).

### E4-1 — `prepare` with an unreadable caps record

**Conflict.** L-S3 (coordinator ruling 1) had `prepare` refuse
`sandbox_placement_capability_unmet`. The `PrepareResponse` refused branch admits only
`sandbox_launch_refused`, `sandbox_launch_reservation_unknown`,
`sandbox_launch_reservation_mismatch`, `sandbox_launch_exec_claimed` and
`sandbox_launch_input_mismatch`, so that response would be schema-invalid.

**Ruling, per the frozen wire.** An independent reviewer confirmed it as the closest
wire-valid reading.

- When `load_caps()` raises `CapsUnavailable`, `prepare` refuses `sandbox_launch_refused`,
  state `refused`, `paths` null, exit 10, for every target.
- It reads no reservation state and allocates nothing: no new run, no `run_id`, no claim.
- It journals the response under its `request_id`, so the refusal is settled under
  `x-prepare.replay`. On a replay, any run id the attempt had already planned stays owned
  through a recorded cleanup entry.
- `launch` still refuses `sandbox_placement_capability_unmet`. `status`, `cancel`, `version`
  and `--help` keep the L-S3 behavior.

**Replays,** in the existing `x-prepare.replay` order:

- A replay whose canonical body differs from the journaled one refuses
  `sandbox_launch_refused` and journals nothing.
- A settled prepare (`prepared` or `refused`) replayed with the same canonical body returns
  its journaled response byte for byte, whatever the caps state is now.
- For an unsettled replay, the request-lock and frozen clock checks run first. A lock timeout
  still answers `timeout`, and a replay at its bound still settles
  `sandbox_placement_end_reached`. Only then does the caps gate run, before any reservation
  read or allocation, with the same generic refusal.

**Owners.** The §7 E3-3 row "Unreadable caps (coordinator ruling 1)" stays with SL-3 and now
reads this code. SL-3's tests also cover the settled and unsettled replay cases.

### E4-2 — the openshell runtime record

**Conflict.** `x-argv-templates.pi_runner_templates` reads the node path and digest, the
helper digest and the launcher and tree paths from the registered image's runtime manifest.
The pinned toolkit runtime manifest (`openshell-runtime.json`, RUNTIME_VERSION 3) does not
supply those values in that form:

- it records no node path or node digest;
- it names the helper digest differently;
- its launcher and tree layout differs.

**Ruling.**

- SL-7 defines a normalized runtime-record shape: helper, node, launcher with its files, and
  trees. Registration accepts one only through a test-only fixture seam that production
  callers never pass.
- Production openshell template registration stays closed. The template stays unregistered
  with the registration reason `runtime_unavailable` until reviewed, image-bound evidence
  supplies the node, helper and tree values.
- Image rows of the `launch` settings object (§7 E3-2) accept no `runtime` member. An image
  row that carries one makes the configuration invalid.
- This is an open input for SL-9 and ACTIVATE. It does not change E2-6, which stays SL-9's
  review-runner image record.

**Effect.** Under shipped defaults every openshell route is `route_disabled` before the
template step, so no runtime behavior changes. SL-7 owns the tests: the fixture positive
case, the production `runtime_unavailable` refusal, and the rejection of a `runtime` member.

## 9. Erratum LANEEXEC-v1-errata-5 — SL-8 on the integrated interfaces

`plans/artifacts/v13-LANEEXEC-errata-5-resolutions.md` is normative for SL-8.
The manifest seals both documents. The following decisions bind §§3, 6 and 7
and the corresponding SL-8 tasks on the integrated input in §0.

| Findings | Decision |
| --- | --- |
| 1, 3, 12 | Retain both policy digests. Require a reviewed worker projection for authoritative execution. Verify the actual local bind destination and use SL-1's default workload modes. |
| 2 | SL-3a defines LaneContext at the service boundary. SL-4 supplies it from trusted scheduler records for SL-8 admission to match. Process assignment uses the frozen derivation. Nonempty caller context narrows admission to independently evidenced suitability. The codec diagnostic is preserved. |
| 4 | SL-7 splits static route validation from activation for SL-8. Apply both the host gate and the captured client opt-in at activation. |
| 5, 6, 9 | SL-8 owns request election, generation-bound staging and the supervisor. SL-3a supplies the ordered locks, generation-scoped records, verified cancel client and teardown gates specified in the resolutions table. Provision the retained return parent while locked. Release the provisioning journal lock at claim. |
| 7, 8 | Freeze detached inputs and a bounded return-verdict channel. Check captured caps. Track descendant exit and observed collection independently. |
| 10 | Authoritative patch execution awaits a future acknowledged result handoff. SL-2 applies ordinary over-cap invalidation to both return kinds, including cap zero. |
| 11 | Use trusted mount aliases and an explicit RAM staging override in the hosted M1–M5 evidence. |
| 13 | Local Pi stays interim pending an admitted-child duplex handoff. Exercise the socket lifecycle with an offline stream. |

R1 and R2 remain binding. Shipped routes stay disabled. Only actual producer
evidence discharges the affected positive acceptance criteria. The wire and
toolkit pin retain the §0 identity.
