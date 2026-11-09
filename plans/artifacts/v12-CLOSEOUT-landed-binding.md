# v12 CLOSEOUT: landed binding and STOP decisions (re-plan, 2026-11-09)

Frozen artifact for `plans/phase-plan-v12-CLOSEOUT.md` (re-plan). It has no word
cap. It does not amend `plans/artifacts/v12-CLOSEOUT-inputs.md`, which stays the
frozen statement of external pins, corpus accounting, the seven adopted contract
decisions, the capture/apply/evidence boundaries, the frozen local interfaces,
trusted context and hosted verification. This artifact adds three things the old
plan could not know: the landed baseline it builds on, the decision for each STOP
item in the pre-build sweep, and the corrections the landed code forces on the
inputs artifact's statements about upstream state and test-group membership.
Where the two artifacts disagree about what has landed or which file a lane
owns, this artifact governs.

## 0. Inputs (pins of existing bytes only)

| Input | Identity |
| --- | --- |
| Roadmap | `specs/phase-plans-v12.md`, sha256 `98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5` |
| Frozen CLOSEOUT inputs (unchanged) | `plans/artifacts/v12-CLOSEOUT-inputs.md`, sha256 `b6fd84dc91b91236e72f4359ef7f0673c3a851ed2366d7ffdfc99ad10466e330` |
| Landed baseline inspected | `origin/main` at `a493c46ccf979231b1a3ae5b23ae678a801f0603` (v12 WORKER merge, Consiliency/agent-harness#1956). Every `file:line` below refers to this tree. |
| Pre-build sweep | Consiliency/agent-harness#1961 head `757fa734f9dbf1a7ec8e3e3916784464b7714699`, `plans/artifacts/v12-CLOSEOUT-landed-sweep.md` |
| WORKER contract | `plans/artifacts/v12-WORKER-contract.md`, sha256 `0ffce1ac29e82df9b1677c8861f94f15d203fc0720c35e3ce7fd083ba6beb415` |
| JOURNAL interface | `plans/artifacts/v12-JOURNAL-interface.md`, sha256 `6aa4c3325c3ec99516dc5da8f115b77affb332a8f70d3cdf700c98405a9ba791` |
| Cross-phase ownership | `plans/artifacts/v12-v13-replan-ownership.md` (this re-plan set) |

No future commit, commit count or merge topology is pinned anywhere in this
re-plan. The external consiliency-contract pins are those of the inputs
artifact, re-verified by the sweep (15 of 15 published hash/blob pairs matched).

## 1. What CLOSEOUT must still deliver

Nothing of CLOSEOUT has landed. The goals are EC-CLOSEOUT-1 and EC-CLOSEOUT-2 in
the roadmap; this table maps each remaining obligation to the landed state and
the owning lane.

| Obligation | Landed state at the baseline | Lane |
| --- | --- | --- |
| Vendored v2 resources, version declarations and v2 loader selector | Absent. `load_contract_bundle()` takes no argument (`supervised_contracts.py:202`). | SL-0 |
| Public v2 codec, capture and admission | Absent. Only the fixture seam `prepare_launch` exists (`supervised_launch.py:366`). | SL-1 |
| Production `launch` reaches the worker | Refuses `codec_unavailable` (`supervised_worker_cli.py:19`, `:100`) and then `codec_unwired` (`:101`). | SL-2 |
| Worker identity bound outside the envelope | The worker reads `run_id`, `attempt_id` and unit fields from the fixture envelope's top level (`patch_return.py:362`). | SL-2 |
| Exact `caller_context` echo (six `kind=echo` cases) | JOURNAL commits only `caller_context_sha256` (`run_status.py:1165`, `patch_return.py:360`). | SL-2 (C-S1) |
| Historical receipts stay valid while CLOSEOUT edits their files | All three landed receipts compare live bytes (§4). | SL-0, SL-1, SL-2 (C-S2) |
| External controller, display and publisher evidence | Absent; trust roots unresolved (inputs artifact "Authority transition"). | SL-3 records blocked (C-S4) |
| Readiness report and evidence verifier | Absent. | SL-3 |

Dropped from the old plan because it is done: the work-start gate on SCHEMA,
IF-0-WORKER-1 and IF-0-JOURNAL-1 (all landed with receipts); ENVELOPE's plan seal
and probe-handoff repair (made by the original CLOSEOUT planning change); the
"SCHEMA plan is absent" note (the plan is present).

## 2. Landed-interface table

Every touchpoint between CLOSEOUT and landed code. "Use" says how the lane may
touch it: **consume** (call unchanged), **extend** (the owning lane edits it) or
**convert** (test behavior changes, recorded outcomes do not).

| Landed site | Shape | Use |
| --- | --- | --- |
| `supervised_contracts.py:202` | `load_contract_bundle() -> ContractBundle` | extend (SL-0) to `load_contract_bundle(*, version="v1")`; v1 default and closure unchanged |
| `supervised_contracts.py:278` | `validate_record(bundle, family, record: bytes, *, definition=None) -> None` | extend (SL-0): v2 family only with a v2 bundle |
| `supervised_launch.py:29` | `Refused(reason)` | consume |
| `supervised_launch.py:160` | `trusted_bytes(path, *, excluded=())` | consume for trusted-file reads |
| `supervised_launch.py:169`–`:231` | `LaunchConfig`, `LaunchInputs`, `EnvelopeCapture`, `EnvelopeView`, `Admit`, `PreparedLaunch` (process-local one-use `_token`) | extend (SL-1): `PreparedLaunch` gains the immutable `AttemptBinding`; token stays process-local; SL-1 adds `discard_admission(prepared: PreparedLaunch) -> None`. It is idempotent: it removes the token from the process registry (`_TOKENS`, `:247`) and closes the held capture through its refusal/cancel path (inputs artifact, CapturedLaunch lifetime) without consuming it. A discarded `PreparedLaunch` refuses at `consume_admission`. |
| `supervised_launch.py:268` | `classify_workspace(workspace, target, tier)` | consume |
| `supervised_launch.py:366` | `prepare_launch(envelope_bytes, *, validator, decoder, config)` | keep as the offline fixture seam only; production never calls it |
| `supervised_launch.py:462` | `consume_admission(prepared) -> LaunchInputs \| Refused` | extend (SL-1): same signature, v2 recheck and spend-once |
| `supervised_launch_binding.py:24` | `_load_absolute(path, data) -> ModuleType` (module load from verified bytes) | consume; any new call site is an inventory row (C-S3) |
| `supervised_launch_binding.py:33` | `load_validator_binding(path, *, workspace, target)` | extend (SL-1) with `load_v2_binding` / `load_v2_context` |
| `supervised_worker_cli.py:19` | `_production_codec()` returns `None` | extend (SL-2): returns the installed v2 binding's codec |
| `supervised_worker_cli.py:72` | `main(argv=None, *, state_root=None)`; verbs `launch --envelope --result`, `status`, `cancel` | extend (SL-2): verbs unchanged; `launch` reads the §4.2 controller document; `status`/`cancel` unchanged |
| `supervised_worker_cli.py:97` | refuses `isolation_required` unless `sys.flags.isolated` | consume |
| `patch_return.py:29` | `PRODUCTION_LAUNCHER_COMMANDS` from `seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", "launch")` | consume; the production launcher prefix (agent-harness#1132, agent-harness#1957) |
| `patch_return.py:34`–`:92` | `WorkerSettings`, `WorkerAttemptIdentity`, `BaselineIdentity`, `ProposalReturn`, `JournalAnchor`, `WorkerResult`, `CancelOutcome` | consume; `WorkerAttemptIdentity` is now filled from `AttemptBinding` |
| `patch_return.py:162` | `evidence_resolver(state_root)` → present / retention_dropped / unknown | consume; its private-accessor follow-up stays agent-harness#1960 item 5 |
| `patch_return.py:221`, `:289` | `_audit`, `_paths` (private) | consume indirectly only; agent-harness#1960 item 1 stays separate |
| `patch_return.py:345` | `run_patch_return(prepared, *, config_bytes, state_root, cancel=None) -> WorkerResult`; consumes admission and reserves JOURNAL itself | extend (SL-2): identity from `prepared`'s `AttemptBinding`; echo sidecar before reserve |
| `patch_return.py:360`, `:362` | caller-context digest; identity from envelope top-level fields | extend (SL-2) |
| `patch_return.py:382` | `journal.reserve_attempt(...)` | consume; reservation stays worker-owned and permanent |
| `patch_return.py:427` | `before_spawn` callback inside `run_bounded_capture` | extend (SL-2): `recheck_launch_v2` runs here, at the true spawn boundary |
| `patch_return.py:492` | non-completed termination → `withheld_incomplete` | consume |
| `patch_return.py:584` | `cancel_attempt(*, state_root, run_id=None, attempt_id=None, wait_seconds, launcher_commands)` | consume |
| `convergence/adapters/base.py:289`, `:306`, `:329`, `:359` | `CaptureRequest`, `SpawnRefused`, `worker_child_environment`, `run_bounded_capture(request, *, before_spawn, cancel)` | extend (SL-2): `run_bounded_capture` gains a keyword-only parameter for the opaque spawn capability `consume_admission` returns (the held executable descriptor and the separate secret-delivery object of the inputs artifact's CapturedLaunch), so the final spawn owner applies them; `CaptureRequest` stays secret-free; the v2 path takes its environment from the capture, not `worker_child_environment`; refusal before chain and helper failure after start (finished/failed_to_start) are unchanged |
| `convergence/adapters/codex.py:17` | `run_codex_patch_return(prepared, *, config_bytes, state_root, cancel=None)` reads only `prepared.view.inputs.executable.path` and delegates to `run_patch_return` | consume unchanged: SL-1 keeps the `LaunchInputs` shape and the `consume_admission` signature, so no lane owns this file (coordinator ruling 2026-11-09) |
| `run_status.py:118`–`:181` | `AttemptIdentity`, `Units`, `WriterIdentity`, `Ref`, `Termination`, `TerminalRefusal`, `ResultBinding`, `Reservation`, `ChainHead` | consume; record schema unchanged |
| `run_status.py:337` | `_STATES = queued, running, cancelling, finished, refused` | consume |
| `run_status.py:825` | `open_journal_root(path, *, create, excluded=())` | consume |
| `run_status.py:913` | `make_ref(kind, data, locator)` | consume |
| `run_status.py:1165` | `reserve_attempt(root, identity, *, units, launch_digest, caller_context_sha256)` | consume |
| `run_status.py:1229`, `:1338` | `AttemptWriter.state/event/terminal/close`; `event(phrase, *, refs=())` accepts closed phrases only | consume; no new phrase, no payload in a message |
| `run_status.py:1296` | `_append`: a complete line is written before its fsync (`:1312-1317`) and stays readable if the fsync fails (agent-harness#1954) | consume; no reader marker is added here |
| `run_status.py:1415`, `:1872` | `open_writer`, `read_attempt` (nullable identity/units/writer) | consume |
| `run_status_projection.py:32` | display states incl. `finished (reason)` | consume |
| `run_status_projection.py:87` | strict integer domain for journal values | consume; echo bytes never pass through it (C-S1) |
| `run_status_projection.py:209`, `:271`, `:366`, `:472` | `project_assignment`, `attempt_status(..., *, observer)`, `read_page(..., *, evidence)`, `build_reader_view` | extend (SL-2): v2 reader view resolves the echo sidecar |
| `output_retention.py:106`, `:263` | `mark`, `prune` | consume unchanged |
| `seat_uid.py:490` | `trusted_module_argv(module, *args)` | consume for every helper launch |
| `panel_invoker.py:4440`, `:13354` | `_NONLOCAL_EXECUTION_DRIVER = False`; jailed Codex seat route (0.7.31) | do not touch; the seat route is not v2 worker route qualification |
| `phase-loop-runtime/scripts/stamp_evidence_receipt.py:16` | `stamp(receipt, *, repo)` re-hashes `source_hashes` | consume for CLOSEOUT's own receipt only; never run against a historical receipt |
| `phase-loop-runtime/scripts/verify_qualified_agy_image.py:320` | agy release verifier | not consumed; agy catalog is a separate qualification system |
| `tests/test_supervised_launch_receipt.py:49` | ENVELOPE receipt: live `source_hashes` equality | convert (SL-1, C-S2) |
| `tests/test_run_status_receipt.py:101` | JOURNAL receipt: live equality | convert (SL-2, C-S2) |
| `tests/test_supervised_worker_receipt.py:59`, `:70`, `:73` | WORKER receipt: live equality, node-set equality, control-set equality; already excludes `CHANGELOG.md` and the seat inventory (agent-harness#1955) | convert (SL-2, C-S2) |
| `tests/data/seat_launch_references.json:13` | landed WORKER rows | extend (SL-2) by union |
| `docs/supervised-worker.md:8` | docs-audit baseline | extend (SL-3) without restoring pre-audit claims |

The status and event closures, proposal statuses and nullability rules listed in
the sweep report's "Complete consumed local signatures" section apply unchanged.

## 3. STOP decisions

Each decision names the option chosen and the reason. The sweep's recommendation
is the default; a deviation says why.

### C-S1 — caller_context echo at the JOURNAL writer

**Chosen: an independently bound echo artifact (sweep option 2), stored outside the JOURNAL.** The JOURNAL record schema, `REF_KINDS`, phrases and strict parser stay unchanged; `run_status.py` is not edited; no echo enters `event.message` or an event ref (`plans/artifacts/v12-JOURNAL-interface.md` CLOSEOUT bullet: "compared by exact bytes, not through the journal writer").

- SL-2 adds `supervised_echo.py`: `write_echo(state_root, payload: bytes) -> str | EchoRefused` (returns the lowercase 64-hex SHA-256 of `payload`) and `read_echo(state_root, sha256: str) -> bytes | EchoRefused`. The payload is SL-1's `canonicalize_v2(caller_context)`. SL-2 reserves `caller_context_sha256 = sha256(payload)`, replacing the `rfc8785.dumps(_plain(...))` digest at `patch_return.py:360`.
- Storage: `<state_root>/echo/<sha256>`, a 0700 directory beside `<state_root>/journal`, never inside the journal root. It is written after `consume_admission` succeeds and before `reserve_attempt`: a temporary file in that directory, fsynced, linked to its final name without replacing, then a directory fsync. An existing file with equal bytes is adopted; unequal bytes refuse `echo_unavailable`. The payload is capped at the admitted envelope byte cap. CLOSEOUT deletes no echo file, and `output_retention` does not visit them.
- Readers take `caller_context_sha256` from `read_index(root, assignment_digest)` (`run_status.py:988`; `Reservation` has no such field), call `read_echo`, and verify the SHA-256 over the exact bytes. Only the v2 reader view resolves echoes, through its own byte encoder and never `json.dumps` of the projection mapping. v1 projections and existing journals read unchanged. The admitted JCS bytes are emitted verbatim; nothing is serialized a second time. A missing or mismatched file is `echo_unavailable`, and the v2 view refuses that record.
- The six `kind=echo` cases (including `S3-jcs-proto-echo-dropped` and `S2-jcs-echo-number-changed`) run through `run_patch_return` and the real writer and reader, comparing bytes. Failure injection covers: a crash between publication and reservation; a refused reservation that leaves an orphan; two concurrent writers of equal bytes.

Reason: the index entry already commits the digest, so a sidecar outside the journal adds the bytes without touching the closed record schema or the journal-root layout (`run_status.py:862-878`) that JOURNAL's receipt and tests freeze.

### C-S2 — historical receipts versus live files

**Chosen: preserve historical receipt bytes and outcomes and verify them
historically; publish CLOSEOUT evidence separately (sweep recommendation,
adopted).**

- SL-0 adds `phase-loop-runtime/tests/historical_receipts.py`, a helper with one
  check: a historical receipt's file bytes equal the seal in §6; its
  `runner_stamp.source_tree_digest` equals the SHA-256 of its own sorted
  `source_hashes`; every producer node and mutation control it records still
  exists in the current tree (subset, not equality), except the exact node IDs retired in §6; and its recorded outcomes are unchanged. Each check applies only to fields that receipt records: SCHEMA has no `source_hashes` or `runner_stamp`, so it is checked by seal and recorded outcomes; JOURNAL and WORKER record different node and control fields. Live-file equality is not part of the historical check.
- Each lane converts the receipt test whose sources it is about to edit, in the
  same lane, before its own edits: SL-0 the SCHEMA receipt test (whose
  historical-module and signature rules the inputs artifact already freezes; the
  helper adds only the §6 seal and the internal-digest check), SL-1
  `test_supervised_launch_receipt.py` (ENVELOPE), SL-2 `test_run_status_receipt.py`
  (JOURNAL) and `test_supervised_worker_receipt.py` (WORKER). A historical
  control that a lane removes or renames fails the subset check.
- No historical receipt is re-stamped. `stamp_evidence_receipt.py` is never run
  against SCHEMA, ENVELOPE, JOURNAL or WORKER.
- CLOSEOUT's own receipt pins only CLOSEOUT-exclusive sources, tests and the
  frozen artifacts. It pins none of the shared files listed in the ownership map,
  no `docs/*.md` file and nothing under `.github/workflows/` (owner rule,
  agent-harness#1955).

Reason: it keeps every recorded result verifiable without freezing source files
that CLOSEOUT must edit, and without rewriting history to pass.

### C-S3 — companion ownership

**Chosen: name the companions explicitly (sweep recommendation, adopted).**

- SL-2 owns `tests/data/seat_launch_references.json` and its three inventory
  tests, and records every new launch site or dynamic import made by SL-1 or
  SL-2 (for example a new `_load_absolute` call for the verified v2 module). Every
  helper launch uses `seat_uid.trusted_module_argv`; `-m` is never used.
- SL-2 owns `tests/fixtures/supervised_worker_local/**` and
  `tests/_run_status_vectors.py`.
- Receipt tooling is used, not owned: SL-3 stamps only CLOSEOUT's receipt with the
  landed `stamp_evidence_receipt.py` unchanged. A needed tool change is a STOP.
- `output_retention.py`, `supervised_dependency.py`,
  `executable_dependency_startup.py`, panel, launcher, review_stage and
  dependency-routing code stay unchanged regression inputs.

Reason: these are exactly the omitted companions the sweep found; nothing else
is claimed.

### C-S4 — external producer evidence and trust roots

**Chosen: keep acceptance blocked; the implementation never manufactures
producer authority (sweep recommendation, adopted).**

- SL-0 to SL-2 and SL-3's offline verifier can complete and merge.
  EC-CLOSEOUT-1 acceptance stays blocked until the external evidence exists: the
  13 controller application outcomes, the display-consumer reconciliation, the
  board, president and controller publisher bindings, and a non-provisional
  publisher status.
- `byte_pin_authority` and both bundle provenance flags stay false.
- The readiness report lists each missing item with its owner and blocked edge.
  While any producer binding is missing the phase closeout records
  `terminal_status=blocked`, `blocker_class=upstream_phase_unmet`,
  `human_required=false`: the bindings are produced outside this repository.

### X-S1 — CLOSEOUT/PLACECLI shared files

**Chosen: serial integration CLOSEOUT → PLACECLI → LANEEXEC**, recorded with the
complete map in `plans/artifacts/v12-v13-replan-ownership.md`.

## 4. Bindings the landed code forces (not STOP items, decided here)

### 4.1 Identity comes from `AttemptBinding`

The inputs artifact already defines `AttemptBinding` (assignment_digest, run_id,
attempt_id) as the controller's trusted request, separate from the envelope and
its opaque echo. SL-1 carries it in `PreparedLaunch`; SL-2 builds
`WorkerAttemptIdentity` from it and the v2 view, and stops reading identity from
envelope top-level fields. The fixture path keeps its current behavior for
offline tests only.

### 4.2 Controller hand-off to the production CLI

The CLI must learn the controller's `AttemptBinding` and per-attempt `ValidatorContext` without the envelope or a CLI flag supplying them (inputs artifact, "Trusted context": "Envelope bytes, caller_context and launch CLI flags cannot supply or override it"). The verbs stay exactly those of WORKER contract §6 and `specs/phase-plans-v12.md`: `supervised_worker_cli launch --envelope <file> --result <file>`. No flag is added.

The controller writes one per-attempt document at `<controller_root>/<h>.json`. `controller_root` is named by the trusted V2Binding operator configuration, and `h` is the lowercase hex SHA-256 of the exact envelope file bytes. The document is written once with `O_EXCL`; an existing document with equal bytes is reused, and unequal bytes refuse. The CLI computes `h` from the one envelope snapshot it already reads and opens only that path.

The document holds `h`, the `AttemptBinding`, the per-attempt `ValidatorContext` fields, and values for the per-attempt slots that the V2Binding `TrustedLaunchSpec` declares (local roots and argv slots). It cannot add or change any other `TrustedLaunchSpec` member, operator policy, issuer, epoch or revocation trust root, or codec selection.

It is read once through the landed single-descriptor read at `supervised_worker_cli.py:23-49` (`O_NOFOLLOW`, `fstat`, `st_uid == geteuid()`, byte cap, one read). That read additionally requires `mode & 0o077 == 0`, component-wise no-follow ancestors under `controller_root`, and a location outside the workspace, target and reference roots. A missing document, a mismatched `h` or any failed check refuses `binding_invalid` before any effect. This is the seam LANEEXEC's launch service uses (LANEEXEC STOP L-S1).

### 4.3 Local result to public status mapping

SL-2 freezes one total mapping from `WorkerResult` (state, termination, refusal, proposal status, `journal_complete`, anchor) and `attempt_status` display states to public status records valid against the pinned `run-status.schema.json` (`supervised_run_status.v1`; both intakes carry the same run-status bytes). It is a closed table in SL-2's tests. `runtime_state` values come only from `run_status_projection.RUNTIME_STATES` (`run_status_projection.py:32`); no JOURNAL state, display state or schema member is added. Every local refusal code maps to a schema-valid refusal record, never free text. A missing anchor with `journal_complete=False` maps to `unknown` and is never reported as acknowledged (agent-harness#1954 posture). LANEEXEC consumes this mapping, adds none of its own, and renders `unknown` as its wire `uncertain`.

### 4.4 Trusted launcher and the WORKER contract §6 note

The production launcher prefix is `seat_uid.trusted_module_argv(...)` including
the installation-root boot (agent-harness#1132, agent-harness#1957). The WORKER
contract §6 spelling `python -I -m …` is illustrative only. This artifact is the
CLOSEOUT amendment that agent-harness#1960 item 6 asks for; SL-3 states it in
`docs/supervised-worker-contracts.md`. Items 1 to 5 of agent-harness#1960 and
all of agent-harness#1954 stay with those issues.

### 4.5 Preserved boundaries

- The jailed Codex seat (agent-harness#1916) and per-seat caps
  (agent-harness#1895) are SEATS-owned. CLOSEOUT adopts neither, and placement
  or a seat route is never v2 route qualification.
- Unsupported routes keep refusing: os_enforced, interactive delivery,
  dependency routes, workspace-contained executables, audit-tier write_scope.
- The docs audit (Consiliency/agent-harness#1940, #1942, #1943) is the docs
  baseline; no pre-audit claim is restored.
- The agy v2 catalog and its verifier are not a v2 worker qualification receipt.

### 4.6 Manifest row

The manifest keeps one row per canonical plan file. The CLOSEOUT row stays
`v12-CLOSEOUT`; the re-plan appends a `replan` lifecycle event (superseded plan
hash, roadmap hash, sweep input) and adds this artifact and the ownership map to
its `frozen_inputs` beside the unchanged inputs-artifact seal. The publication
detector and hosted verifier compare that row's `frozen_inputs`; SCHEMA's row is
compared separately, as before.

## 5. Verification groups (supersedes the inputs artifact's membership list)

WORKER and JOURNAL landed test files the inputs artifact did not list. The
wrapper `phase-loop-runtime/scripts/verify_supervised_v2.sh` runs these groups;
"all" is their de-duplicated union, and the wrapper refuses unknown groups and
missing files.

- V0: `tests/test_supervised_contracts.py`, `tests/test_supervised_contracts_vectors.py`, `tests/test_supervised_contracts_mutations.py`, `tests/test_supervised_contracts_receipt.py`, `tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest`, `tests/test_ci_chronology_scope.py`, `tests/test_ci_offload_lock.py`
- V1: `tests/test_supervised_envelope_v2.py`, `tests/test_supervised_capture_v2.py`, `tests/test_supervised_launch.py`, `tests/test_supervised_launch_binding.py`, `tests/test_supervised_launch_route.py`, `tests/test_supervised_launch_mutations.py`, `tests/test_supervised_launch_receipt.py`
- V2: `tests/test_supervised_worker.py`, `tests/test_supervised_worker_cli.py`, `tests/test_supervised_worker_receipt.py`, `tests/test_run_status.py`, `tests/test_run_status_projection.py`, `tests/test_run_status_receipt.py`, `tests/test_convergence_adapters.py`, `tests/test_output_retention.py`, `tests/test_executable_dependency_startup.py`, `tests/test_stamp_evidence_receipt.py`, `tests/test_agent_cli_scratch_inventory_1147.py`, `tests/test_seat_launch_helpers_trusted.py`, `tests/test_seat_reference_inventory.py`
- V3: `tests/test_supervised_v2_readiness.py`

Paths are relative to `phase-loop-runtime/`. On shared hosts the groups run on
`ai` under the usual admission and PSI gates, never on dev0 (owner ruling).

## 6. Historical receipt seals

These are pins of committed bytes at the baseline, consumed by
`tests/historical_receipts.py`.

| Receipt | sha256 |
| --- | --- |
| `plans/evidence/supervised-worker/SCHEMA.md` | `2a8077d504d2f1d5a34b84fccec3062242c96de9c05a1d65944a824ee0be58b4` |
| `plans/evidence/supervised-worker/ENVELOPE.md` | `b65f0f6ec562c344da46d1c153c471db8955f45bed84b129cfe3e737e9b00b46` |
| `plans/evidence/supervised-worker/JOURNAL.md` | `a65626471966ef4fb412ac7063a3a9da8da6ca0d3f375e402418827a57768ae3` |
| `plans/evidence/supervised-worker/WORKER.md` | `978bbecfd4fedca8689a34b146396d9799a91b84d095069e536e5521650f7a26` |

**Retired historical nodes.** These are exempt from the subset check by exact ID only. Any other missing node fails, and a further retirement is a STOP.

| Receipt | Node | Lane | Reason |
| --- | --- | --- | --- |
| `plans/evidence/supervised-worker/WORKER.md` | `tests/test_supervised_worker_cli.py::test_isolated_cli_before_root[argv0-codec_unavailable]` | SL-2 | SL-2 wires the production codec, so `codec_unavailable` is no longer the isolated-CLI outcome. |
