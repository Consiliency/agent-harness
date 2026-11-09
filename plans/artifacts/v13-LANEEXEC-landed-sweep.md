# v13 LANEEXEC: landed-input sweep — 2026-11-09

Inspected input: `a493c46cc` on `origin/main` (WORKER merge). All line citations
in the sweep table and inventories refer to that immutable input, before this
amendment. No output commit identity is prescribed. This is a static design
reconciliation, not runtime qualification or approval to build.

MATCH means a consumed boundary is compatible or explicitly prospective;
MISMATCH includes an omitted integration boundary. A MISMATCH marked STOP is
**not corrected** by guessing a design. Prospective output schemas and ownership
claims are inventoried separately below; their presence is not counted as a
passing implementation. The main table has **16 MATCH / 12 MISMATCH** rows.

AGENTS.md ratio diagnosis: the plans froze downstream integration before the
upstream implementations stabilized. LANEEXEC has already had multiple input/
activation amendments without its implementation. This sweep is one consolidated
factual amendment per phase. STOP items require a single coordinated disposition,
not repeated speculative plan edits. Review remains pending; no build or merge.

## Sweep table

| Plan/artifact line at input | Result | Consumed boundary | Landed code/evidence file:line | Disposition |
| --- | --- | --- | --- | --- |
| plans/phase-plan-v13-LANEEXEC.md:316 | MISMATCH | Upstream landing state / scope | phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py:19 | FACT corrected: gates landed locally; codec remains unavailable. No public-v2 or activation proof. |
| plans/phase-plan-v13-LANEEXEC.md:316 | MATCH | JOURNAL landed rev-5 identity, replay and bounded projection | phase-loop-runtime/src/phase_loop_runtime/run_status.py:118 | Available; exact consumed API and nullability inventory below. |
| plans/phase-plan-v13-LANEEXEC.md:409 | MISMATCH | v2 consumer expects a landed compatible admission seam | phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:366 | L-S1: required validator/decoder/config keyword-only; fixture codec, no public-v2 binding. |
| plans/phase-plan-v13-LANEEXEC.md:317 | MISMATCH | Base caps landed but tmpfs prerequisite is unimplemented | phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:337 | FACT documented; L-S3 remains blocked. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:529 | MISMATCH | io_devices has no per-attempt path override | phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:247 | FACT documented; L-S3 owns decision on public API/lifetime. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:518 | MISMATCH | Atomic placement claim plus irreversible JOURNAL reservation | phase-loop-runtime/src/phase_loop_runtime/run_status.py:1165 | L-S2; independent writes and worker-owned reservation cannot satisfy this directly. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:49 | MISMATCH | Rollback/relaunch reuses prepared identity while journal claim is permanent | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:382 | L-S2; define fresh attempt or reservation handoff, no release API. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:555 | MISMATCH | Unknown/stale projection and extra local cancel outcomes omitted | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:92 | L-S4; no invented state mapping. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:571 | MISMATCH | Cancelled/timed-out proposals are withheld by WORKER | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:492 | L-S5; public return policy needs decision. |
| plans/phase-plan-v13-LANEEXEC.md:414 | MISMATCH | Zero snapshot/envelope counters through pre_exec contradict order | phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:366 | L-S6; snapshot/admission precede pre_exec per frozen x-launch-inputs.order. |
| plans/phase-plan-v13-LANEEXEC.md:394 | MISMATCH | Private audit/proposal helpers are not a public return API | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:221 | L-S5; no refactor ownership assigned silently. |
| plans/phase-plan-v13-LANEEXEC.md:217 | MISMATCH | Review/none/patch routes require distinct supported worker mapping | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py:359 | L-S7; preserve profile boundaries and disabled defaults. |
| plans/phase-plan-v13-LANEEXEC.md:381 | MATCH | Bound(deadline, cancelled), safe_path(path), binary-literal checker available | phase-loop-runtime/src/phase_loop_runtime/openshell_artifacts.py:72 | Consumed artifact utilities remain available; signature inventory below. |
| plans/phase-plan-v13-LANEEXEC.md:442 | MATCH | Trusted helper boot explicitly required | phase-loop-runtime/src/phase_loop_runtime/seat_uid.py:490 | agent-harness#1132; preserve landed install-root prefix, never substitute -m. |
| plans/phase-plan-v13-LANEEXEC.md:423 | MATCH | Executor resolved before reserve; lane_execute remains insertion site | phase-loop-runtime/src/phase_loop_runtime/capability_registry.py:772 | No second model/provider choice after reservation. |
| plans/phase-plan-v13-LANEEXEC.md:59 | MATCH | Prepare/seed/overlay are declared new work, not supplied by WORKER | phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py:74 | CLI currently launch/status/cancel only; separate agent-harness-launch entry still planned. |
| plans/phase-plan-v13-LANEEXEC.md:365 | MATCH | Launch inventory must union with landed entries | phase-loop-runtime/tests/data/seat_launch_references.json:13 | Preserve WORKER rows; update scratch, trusted-helper and reference tests for new sites. |
| plans/phase-plan-v13-LANEEXEC.md:365 | MATCH | JOURNAL/WORKER receipts exclude shared seat inventory | phase-loop-runtime/tests/test_supervised_worker_receipt.py:60 | agent-harness#1955; no new receipt may pin shared mutable inventory or CHANGELOG. |
| plans/phase-plan-v13-LANEEXEC.md:365 | MISMATCH | Existing receipts still pin shared docs; WORKER pins shared adapter sources/tests | plans/evidence/supervised-worker/WORKER.md:1526 | Flag for coordinated historical verification; do not pin shared frequently changed files in new evidence. |
| plans/phase-plan-v13-LANEEXEC.md:365 | MATCH | Jailed Codex remains SEATS-owned; no profile adoption by placement alone | phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py:13354 | Landed 0.7.31 seat route is not v2 WORKER route qualification. |
| plans/phase-plan-v13-LANEEXEC.md:223 | MATCH | agy v2 catalog and release CLI are independent qualification inputs | phase-loop-runtime/scripts/verify_qualified_agy_image.py:320 | No consumed --source-only invocation exists in these plans. --release runs strict conformance, requires fresh report; no release here. |
| plans/phase-plan-v13-LANEEXEC.md:468 | MATCH | Docs-accuracy landings preserved as integration baseline | docs/supervised-worker.md:8 | Do not restore pre-audit claims; public-v2/installed/live authority stays separate. |
| plans/phase-plan-v13-LANEEXEC.md:468 | MATCH | Deferred issues remain separately owned | plans/artifacts/v12-WORKER-contract.md:196 | agent-harness#1954 and agent-harness#1960 do not authorize additional implementation in this sweep. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:55 | MATCH | Input pin placement_process_v1 | plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:72 | MATCH | Input pin policy_vectors | phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:76 | MATCH | Input pin seat_resource_caps | plans/seats-jailcore-caps-contract.md:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:82 | MATCH | Input pin seats_remote_contract | plans/seats-remote-contract.md:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:86 | MATCH | Toolkit delivered manifest plus all 27 listed source files | Consiliency/agent-toolkit:harnesses/pi/contracts/pins.json:1 | The pinned manifest is delivered at 8b9c0697733b3815baa556b1823a653d497ffa04; its toolkit_commit names source cd9174e326140dc27471ff3bfc8abdd056f6e7bd. Validate manifest hash/length separately from all source-file hashes. The source commit need not contain its own later-generated manifest. |

## STOP decisions (not applied)

### L-S1

Frozen sentence: x-envelope-construction.rule: "admits it through the v12 admission seam (supervised_launch.prepare_launch ...)".

Evidence: prepare_launch is fixture-shaped; supervised_worker_cli launch refuses codec_unavailable; CLOSEOUT owns public-v2 capture/admission.

Options: Depend on CLOSEOUT, or explicitly transfer a bounded public-v2 integration slice with ownership/receipt changes.

Recommendation (not a decision): Add a CLOSEOUT prerequisite rather than duplicate admission; coordinator must settle the dependency and the local-to-v2 WorkerResult mapping.

### L-S2

Frozen sentence: x-exec.one_exec: "one durable compare-and-set ... sets LeaseFlags.exec_claimed and reserves the attempt_id through the v12 journal".

Evidence: JOURNAL reservation is permanent and independently durable; run_patch_return consumes then reserves internally. No API accepts a pre-reserved attempt, and failure may leave claims. prepare reuses its run_id/attempt_id after rollback.

Options: Introduce a coordinated reservation handoff/recovery protocol, or retain worker-owned reservation and revise claim/rollback ordering and attempt IDs.

Recommendation (not a decision): Specify durable ordering, partial-failure recovery and fresh-attempt behavior before build; do not wrap two writes and call them atomic.

### L-S3

Frozen sentence: "IF-0-JAILCORE-4 ... including the caps contract §1a carve-out"; x-local-cgroup automatic paths.

Evidence: Landed caps explicitly refuse tmpfs; automatic paths are staging_root and child scratch, not the attempt execution tree/home/out/scratch. No public automatic-path or retained-parent lifetime API exists.

Options: Complete the prerequisite with a public per-attempt paths/lifetime API, or revise the LANEEXEC requirements to the supported block-backed route.

Recommendation (not a decision): Keep this prerequisite blocked and assign the caps API/cleanup work explicitly; do not change the caps contract or bypass refusal here.

### L-S4

Frozen sentence: x-status-cancel and StatusResponse / CancelResponse closed enums.

Evidence: attempt_status can be unknown/stale_unknown with diagnostic and nullable identity; cancel_attempt additionally returns owner_unverified/owner_not_live. CancelResponse has no such values.

Options: Define a total local-to-wire mapping using existing uncertain/refusal surfaces where possible, or revise the protocol vocabulary.

Recommendation (not a decision): Freeze mapping for every local outcome and keep zero-signal refusals distinguishable; do not turn them into a successful cancellation.

### L-S5

Frozen sentence: x-return: "Return runs for every terminal state" and "bounded proposal bytes ... unchanged".

Evidence: WORKER only returns proposals on completed/exit-0/complete-streams; other terminations yield withheld_incomplete. Audit and path validation are private helpers.

Options: Accept WORKER withholding and map statuses, or introduce an owned bounded return API for cancelled/timed-out attempts and result/none routes.

Recommendation (not a decision): Reuse fail-closed withholding for patch and specify result/none separately, subject to coordinator approval.

### L-S6

Frozen sentence: SL-3.1: "Every refusal through pre_exec with zero snapshot, upload, envelope or invocation counters."

Evidence: x-launch-inputs.order places snapshot and admission before recheck and pre_exec; the claimed zero snapshot/envelope effects cannot hold for late refusal.

Options: Scope the zero-effect assertion by stage, or reorder admission/pre_exec with new semantics.

Recommendation (not a decision): Scope assertions by stage while retaining zero claim/upload/chain starts through pre_exec; this changes a verification contract and needs a decision.

### L-S7

Frozen sentence: x-client-routes writer_route; x-envelope-construction enforcement; per_vendor_seat_templates.

Evidence: LANEEXEC spans execution and review while current WORKER capture accepts its fixture/local patch-return path; SEATS jailed Codex/profile activation is separate and not public-v2 qualification.

Options: Define per-action supported-route mappings and qualification inputs, or narrow initial integration to a qualified subset.

Recommendation (not a decision): Keep routes disabled, preserve jail profile boundaries, and define route mappings under CLOSEOUT/SEATS ownership before build.

### L-S8

Frozen sentence: "The artifact is read-only during execution" and PLACECLI byte pin.

Evidence: PLACECLI factual correction has a new digest on its independent draft; LANEEXEC/SEATS REMOTE/external clients still pin the old bytes.

Options: Coordinate input repins after reviewed PLACECLI amendment, or hold LANEEXEC.

Recommendation (not a decision): Hold until input revision is approved; no future SHA or stacked dependency is invented.

## Complete consumed local signatures and record fields

These are the landed shapes, including keyword-only separators, required nullable
fields and defaults. Availability is not a v2 adapter or a wire-status mapping.
JOURNAL/WORKER integration remains subject to the STOPs above.

| Code file:line | Signature or fields |
| --- | --- |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:118` | `AttemptIdentity: assignment_digest: str; envelope_digest: str; run_id: str; attempt_id: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:126` | `Units: target_unit_ids: tuple[str, ...]; readonly_neighbor_unit_ids: tuple[str, ...]; snapshot_ref: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:133` | `WriterIdentity: harness_id: str; harness_version: str; writer_instance_id: str; owner_pid: int; process_start_time: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:142` | `Ref: kind: str; sha256: str; locator: str \| None` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:149` | `Termination: reason: str; signal: str \| None; by: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:156` | `TerminalRefusal: reason: str; constraint: str \| None; tier: str \| None` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:163` | `ResultBinding: envelope_digest: str; run_id: str; attempt_id: str; proposal_bytes_digest: str \| None; evidence_envelope_digest: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:172` | `Reservation: identity: AttemptIdentity; units: Units; index_seq: int; entry_sha256: str; writer: WriterIdentity` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:181` | `ChainHead: segment_index: int; segment_sha256: str; last_seq: int` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:210` | `JournalRefused: code: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:236` | `AttemptRead: attempt_id: str; identity: AttemptIdentity \| None; units: Units \| None; writer: WriterIdentity \| None; lines: tuple[bytes, ...]; state: str \| None; terminal: TerminalRecord \| None; chain_head: ChainHead \| None; diagnostics: tuple[str, ...]; display: str` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:825` | `def open_journal_root(path: Path, *, create: bool, excluded: tuple[Path, ...]=()) -> JournalRoot \| JournalRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:898` | `def process_start_identity(pid: int) -> str \| None:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:913` | `def make_ref(kind: str, data: bytes, locator: str \| None) -> Ref:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:1038` | `def resolve_run(root: JournalRoot, run_id: str) -> tuple[str, ...] \| JournalRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:1165` | `def reserve_attempt(root: JournalRoot, identity: AttemptIdentity, *, units: Units, launch_digest: str, caller_context_sha256: str) -> Reservation \| JournalRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:1229` | `AttemptWriter: def state(self, state: str, *, worker_invocations: int) -> ChainHead \| JournalRefused:; def event(self, phrase: str, *, refs=()) -> ChainHead \| JournalRefused:; def terminal(self, state: str, *, worker_invocations: int, termination: Termination \| None, refusal: TerminalRefusal \| None, result_binding: ResultBinding \| None) -> ChainHead \| JournalRefused:; def close(self) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:1415` | `def open_writer(root: JournalRoot, reservation: Reservation, *, limits: JournalLimits=DEFAULT_LIMITS) -> AttemptWriter \| JournalRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status.py:1872` | `def read_attempt(root: JournalRoot, attempt_id: str) -> AttemptRead:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:45` | `ProjectionResult: projection: dict \| None; unknown_attempts: tuple[tuple[str, tuple[str, ...]], ...]; diagnostics: tuple[str, ...]` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:52` | `AttemptStatus: attempt_id: str; state: str \| None; display: str; termination: Termination \| None; refusal: TerminalRefusal \| None; result_binding: ResultBinding \| None; chain_head: ChainHead \| None; diagnostics: tuple[str, ...]; identity: AttemptIdentity \| None = None; units: Units \| None = None` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:68` | `PageResult: page: dict; next_cursor: str \| None; diagnostics: tuple[str, ...]` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:209` | `def project_assignment(root, assignment_digest: str) -> ProjectionResult:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:271` | `def attempt_status(root, attempt_id: str, *, observer: ProcessObserver=proc_observer) -> AttemptStatus:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:366` | `def read_page(root, request: bytes, *, evidence: EvidenceResolver) -> PageResult \| JournalRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:472` | `def build_reader_view(row: Mapping, status: AttemptStatus, *, work_outcome=None, evidence=None) -> Mapping \| JournalRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:169` | `LaunchConfig: config_path: Path; template_path: Path; qualification_path: Path \| None = None` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:183` | `LaunchInputs: instruction: bytes; instruction_digest: str; baseline: bytes; baseline_digest: str; argv: tuple[str, ...]; executable: ExecutableIdentity; wrappers: tuple[ExecutableIdentity, ...]; workspace: str; target: str; workspace_class: str; root_device: int; root_inode: int; tier: str; constraints: tuple[str, ...]; timeout: int; config_digest: str; template_digest: str; qualification_digest: str` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:205` | `EnvelopeCapture: raw_bytes: bytes; raw_digest: str; envelope: Mapping` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:212` | `EnvelopeView: envelope: Mapping; envelope_digest: str; raw_digest: str; launch_digest: str; inputs: LaunchInputs` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:221` | `Admit: launch_digest: str; attempt_id: str` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:231` | `PreparedLaunch: view: EnvelopeView; admit: Admit; _token: object = field(default_factory=object, repr=False)` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:366` | `def prepare_launch(envelope_bytes: bytes, *, validator: Validator, decoder: Callable[[EnvelopeCapture], tuple[Mapping, str]], config: LaunchConfig) -> PreparedLaunch \| Refused:` |
| `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:462` | `def consume_admission(prepared: PreparedLaunch) -> LaunchInputs \| Refused:` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:34` | `WorkerSettings: proposal_cap: int; audit_entry_cap: int; audit_byte_cap: int; environment_allow: frozenset[str]; retention_days: int \| None; reference_roots: tuple[Path, ...]` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:44` | `WorkerAttemptIdentity: assignment_digest: str; envelope_digest: str; launch_digest: str; raw_digest: str; run_id: str; attempt_id: str; target_unit_ids: tuple[str, ...]; readonly_neighbor_unit_ids: tuple[str, ...]; snapshot_ref: str; caller_context_sha256: str` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:58` | `BaselineIdentity: path: str; git_blob_sha1: str \| None; sha256: str \| None` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:65` | `ProposalReturn: status: str; proposal_bytes_digest: str \| None; byte_length: int; baselines: tuple[BaselineIdentity, ...]; locator: str \| None` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:74` | `JournalAnchor: terminal_seq: int; chain_head_sha256: str` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:80` | `WorkerResult: identity: WorkerAttemptIdentity \| None; state: str; termination: journal.Termination \| None; refusal: str \| None; worker_invocations: int; proposal: ProposalReturn \| None; evidence_envelope_digest: str \| None; journal_anchor: JournalAnchor \| None; journal_complete: bool` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:96` | `def default_state_root() -> Path:` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:345` | `def run_patch_return(prepared, *, config_bytes: bytes, state_root: Path, cancel: threading.Event \| None=None) -> WorkerResult:` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:584` | `def cancel_attempt(*, state_root: Path, run_id: str \| None=None, attempt_id: str \| None=None, wait_seconds: float=CANCEL_WAIT_SECONDS, launcher_commands: tuple[tuple[str, ...], ...]=PRODUCTION_LAUNCHER_COMMANDS) -> CancelOutcome:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:44` | `IoMax: rbps: int; wbps: int; riops: int; wiops: int` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:52` | `SeatResourceCaps: schema: Literal['seat_resource_caps.v1']; memory_max_bytes: int; cpu_weight: int; cpu_max_percent: int; io_weight: int; io_max: IoMax; io_paths: tuple[str, ...]; pids_max: int` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:221` | `def load_caps() -> SeatResourceCaps:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:242` | `def caps_sha256(caps: SeatResourceCaps) -> str:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:350` | `def io_devices(caps: SeatResourceCaps) -> tuple[str, ...]:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:365` | `def readiness_code() -> str \| None:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:559` | `def capped_popen(command, *, seat_key: str, **popen_kwargs) -> 'subprocess.Popen[bytes]':` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py:289` | `CaptureRequest: attempt_id: str; argv: tuple[str, ...]; cwd: Path; timeout_seconds: int; stdin: bytes; proposal_cap: int; environment: Mapping[str, str]` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py:306` | `SpawnRefused: reason: str` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py:329` | `def worker_child_environment(allow: frozenset[str]) -> dict[str, str]:` |
| `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py:359` | `def run_bounded_capture(request: CaptureRequest, *, before_spawn: Callable[[], SpawnRefused \| None], cancel: threading.Event) -> BoundedCapture \| SpawnRefused:` |
| `phase-loop-runtime/src/phase_loop_runtime/output_retention.py:106` | `def mark(root: Path, run: str, state: str, *, owner_pid: int \| None=None) -> dict:` |
| `phase-loop-runtime/src/phase_loop_runtime/output_retention.py:263` | `def prune(root: Path, *, days: int \| None=None, apply: bool=False, now: float \| None=None) -> list[str]:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_artifacts.py:72` | `Bound: end: float; cancelled: Callable[[], bool] = field(repr=False, compare=False); def check(self) -> float:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_artifacts.py:159` | `def safe_path(path: str) -> str:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_artifacts.py:445` | `def check_binary_literals(patch: bytes, limits: Limits, bound: Bound):` |

Status/event closure: JOURNAL `queued`, `running`, `cancelling`, `finished`,
`refused`; display additionally `unknown`, `stale_unknown` and finished reasons
`completed`, `cancelled`, `timed_out`, `failed_to_start`. See
`phase-loop-runtime/src/phase_loop_runtime/run_status.py:54` and
`phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:31`.
WORKER cancellation additionally returns `owner_unverified`, `owner_not_live`;
proposal statuses are `returned`, `absent`, `withheld_incomplete`,
`withheld_oversized`, `withheld_audit_error`, `withheld_unexplained_change`,
`withheld_malformed`, `withheld_evidence_error`. Closed emitted events are
`cancellation requested`, `attempt evidence bound`, `proposal bytes captured`,
`workspace audit failed; proposal withheld`, `proposal withheld`; only evidence
and proposal events carry their digest refs. See `patch_return.py:345–581`.
A nullable result_binding still requires an evidence digest when present; a
nullable identity/writer must be guarded before dereference. Local outcomes are
not extra keys in the closed public journal schema.

## Every owned file / companion claim

Existing files are serial integration inputs, not permission to overwrite another
phase. New files/globs remain proposed deliverables. This enumerates every owned
path in the input plan; shared receipt and cross-phase exceptions are above.

| Plan line | Owned path/glob | Input tree matches (empty means proposed) |
| --- | --- | --- |
| 365 | `phase-loop-runtime/src/phase_loop_runtime/launch_process_contract.py` | Proposed; no landed file |
| 365 | `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/launch-v1.schema.json` | Proposed; no landed file |
| 365 | `phase-loop-runtime/tests/test_launch_process_contract.py` | Proposed; no landed file |
| 365 | `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` | `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` |
| 379 | `phase-loop-runtime/src/phase_loop_runtime/launch_snapshot.py` | Proposed; no landed file |
| 379 | `phase-loop-runtime/tests/test_launch_snapshot.py` | Proposed; no landed file |
| 379 | `phase-loop-runtime/tests/fixtures/launch-snapshot/**` | Proposed; no landed file |
| 393 | `phase-loop-runtime/src/phase_loop_runtime/launch_return.py` | Proposed; no landed file |
| 393 | `phase-loop-runtime/tests/test_launch_return.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/src/phase_loop_runtime/launch_service.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/src/phase_loop_runtime/launch_routes.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` | `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` |
| 407 | `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` | `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` |
| 407 | `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py` | `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py` |
| 407 | `phase-loop-runtime/tests/test_launch_service.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/tests/test_launch_local_caps.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/tests/test_launch_lifetime.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/tests/test_launch_release_reap.py` | Proposed; no landed file |
| 407 | `phase-loop-runtime/tests/test_sandbox_placement.py` | `phase-loop-runtime/tests/test_sandbox_placement.py` |
| 407 | `phase-loop-runtime/tests/test_placement_lease.py` | `phase-loop-runtime/tests/test_placement_lease.py` |
| 407 | `phase-loop-runtime/tests/test_openshell_backend.py` | `phase-loop-runtime/tests/test_openshell_backend.py` |
| 421 | `phase-loop-runtime/src/phase_loop_runtime/lane_launch.py` | Proposed; no landed file |
| 421 | `phase-loop-runtime/src/phase_loop_runtime/runner.py` | `phase-loop-runtime/src/phase_loop_runtime/runner.py` |
| 421 | `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py` | `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py` |
| 421 | `phase-loop-runtime/tests/test_phase_loop_lane_placement.py` | Proposed; no landed file |
| 421 | `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py` | `phase-loop-runtime/tests/test_phase_loop_lane_harnesses.py` |
| 435 | `phase-loop-runtime/pyproject.toml` | `phase-loop-runtime/pyproject.toml` |
| 435 | `phase-loop-runtime/uv.lock` | `phase-loop-runtime/uv.lock` |
| 435 | `phase-loop-runtime/src/phase_loop_runtime/launch_cli.py` | Proposed; no landed file |
| 435 | `phase-loop-runtime/tests/test_launch_cli.py` | Proposed; no landed file |
| 435 | `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py` | `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py` |
| 435 | `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py` | `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py` |
| 435 | `phase-loop-runtime/tests/test_seat_reference_inventory.py` | `phase-loop-runtime/tests/test_seat_reference_inventory.py` |
| 435 | `phase-loop-runtime/tests/data/seat_launch_references.json` | `phase-loop-runtime/tests/data/seat_launch_references.json` |
| 449 | `docs/placement-launch-service.md` | Proposed; no landed file |
| 449 | `docs/placement-process-cli.md` | Proposed; no landed file |
| 449 | `phase-loop-runtime/README.md` | `phase-loop-runtime/README.md` |
| 449 | `plans/evidence/placement/LANEEXEC.md` | Proposed; no landed file |
| 449 | `phase-loop-runtime/tests/test_laneexec_receipt.py` | Proposed; no landed file |
| 449 | `CHANGELOG.md` | `CHANGELOG.md` |
| 449 | `.doc-decisions.json` | `.doc-decisions.json` |
| 449 | `.claude/docs-catalog.json` | `.claude/docs-catalog.json` |
| 449 | `plans/manifest.json` | `plans/manifest.json` |

## Complete prospective schema inventory

Every definition below is reproduced from the inspected frozen input, including
all fields, required lists, refs, nullability, enums and conditional rules. These
are new process protocols, **not** the existing worker CLI JSON. Package loaders
and services do not exist at the inspected input. No absent future API is called
a landed match. The manual table identifies the consumed-code disagreements;
these inventories preserve the rest of the reviewed wire contract unchanged.

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:615 — RepoPath

```json
{"type":"string","pattern":"^(?!\\.{1,2}(/|$))(?!.*/\\.{1,2}(/|$))(?!.*//)(?!.*/$)[^/\\u0000-\\u001f\\u007f\\\\:][^\\u0000-\\u001f\\u007f\\\\:]{0,4095}$","description":"A relative_path under the pinned envelope v2 x-locator-grammar: '/'-separated, every segment non-empty and neither '.' nor '..', no leading, trailing or repeated '/', no ':', backslash or control character, NFC. x-snapshot.path_rules adds the reference's writer-path rules. Invalid input is refused, never normalized."}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:620 — CwdPath

```json
{"anyOf":[{"const":"."},{"$ref":"#/$defs/RepoPath"}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:630 — AbsolutePath

```json
{"type":"string","pattern":"^/[^\\u0000\\r\\n]{1,4095}$"}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:634 — TemplateId

```json
{"type":"string","pattern":"^[a-z][a-z0-9._-]{0,63}$"}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:638 — SnapshotMode

```json
{"enum":["git","full","git_overlay"]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:645 — SnapshotReason

```json
{"enum":["not_a_work_tree","dirty_source","untracked_input","too_large","unsupported_repository","nested_repository","unsafe_path","source_changed","mode_unpermitted","mask_outside_root","timeout"]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:660 — SeedReason

```json
{"enum":["unsafe_path","symlink","seed_root_untrusted","not_regular_file","manifest_invalid","image_link_conflict","digest_mismatch","too_large","source_changed","timeout","scratch_unprovisioned"]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:675 — LaunchAction

```json
{"enum":["execution","review"]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:681 — ResultKind

```json
{"enum":["patch","result","none"]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:688 — LaunchCode

```json
{"enum":["sandbox_launch_refused","sandbox_launch_reservation_unknown","sandbox_launch_reservation_mismatch","sandbox_launch_exec_claimed","sandbox_launch_input_mismatch","sandbox_launch_image_refused","sandbox_launch_template_refused","sandbox_launch_writer_route_refused","sandbox_launch_route_disabled","sandbox_launch_local_route_interim","sandbox_launch_lifetime_unbounded","sandbox_launch_snapshot_refused","sandbox_launch_seed_refused","sandbox_launch_admission_refused","sandbox_launch_pre_exec_refused","sandbox_launch_upload_refused","sandbox_launch_bridge_lost","sandbox_launch_liveness_lost","sandbox_launch_result_invalid","sandbox_launch_result_withheld","sandbox_launch_audit_failed"]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:713 — LaunchResultCode

```json
{"oneOf":[{"$ref":"#/$defs/LaunchCode"},{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/PlacementCode"}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:723 — Snapshot

```json
{"type":"object","additionalProperties":false,"required":["root","mode","masks","mask_dirs","cwd"],"properties":{"root":{"$ref":"#/$defs/AbsolutePath"},"mode":{"$ref":"#/$defs/SnapshotMode"},"masks":{"type":"array","maxItems":256,"uniqueItems":true,"items":{"$ref":"#/$defs/RepoPath"}},"mask_dirs":{"type":"array","maxItems":256,"uniqueItems":true,"items":{"$ref":"#/$defs/RepoPath"}},"cwd":{"$ref":"#/$defs/CwdPath"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:761 — SeedEntry

```json
{"type":"object","additionalProperties":false,"required":["relpath","sha256","size"],"properties":{"relpath":{"$ref":"#/$defs/RepoPath","maxLength":1024,"pattern":"^(?!.*[^/]{256})"},"sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"size":{"type":"integer","minimum":0,"maximum":16777216},"executable":{"type":"boolean","default":false}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:789 — SeedDeclaration

```json
{"type":"object","additionalProperties":false,"required":["manifest_sha256","entries","total_bytes"],"properties":{"manifest_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"entries":{"type":"integer","minimum":1,"maximum":4096},"total_bytes":{"type":"integer","minimum":0,"maximum":67108864}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:813 — SeedManifest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","entries"],"properties":{"schema":{"const":"laneexec.seed.manifest.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"entries":{"type":"array","minItems":1,"maxItems":4096,"uniqueItems":true,"items":{"$ref":"#/$defs/SeedEntry"}}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:839 — SeedLimits

```json
{"type":"object","additionalProperties":false,"required":["max_entries","entry_max_bytes","max_bytes","manifest_max_bytes"],"properties":{"max_entries":{"type":"integer","minimum":0,"maximum":4096},"entry_max_bytes":{"type":"integer","minimum":0,"maximum":16777216},"max_bytes":{"type":"integer","minimum":0,"maximum":67108864},"manifest_max_bytes":{"type":"integer","minimum":0,"maximum":1048576}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:871 — PreparedPaths

```json
{"type":"object","additionalProperties":false,"required":["run_id","scratch_path","tree_path"],"properties":{"run_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"scratch_path":{"$ref":"#/$defs/AbsolutePath"},"tree_path":{"$ref":"#/$defs/AbsolutePath"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:891 — PrepareRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation","snapshot_root","caller_context"],"properties":{"schema":{"const":"placement.launch.prepare.request.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Reservation"},"snapshot_root":{"$ref":"#/$defs/AbsolutePath"},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:919 — PrepareResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","state","code","paths","caller_context"],"properties":{"schema":{"const":"placement.launch.prepare.response.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"state":{"enum":["prepared","refused","timeout"]},"code":{"oneOf":[{"$ref":"#/$defs/LaunchResultCode"},{"type":"null"}]},"paths":{"oneOf":[{"$ref":"#/$defs/PreparedPaths"},{"type":"null"}]},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"state":{"const":"prepared"}},"required":["state"]},"then":{"properties":{"code":{"type":"null"},"paths":{"$ref":"#/$defs/PreparedPaths"}}}},{"if":{"properties":{"state":{"const":"refused"}},"required":["state"]},"then":{"properties":{"code":{"enum":["sandbox_launch_refused","sandbox_launch_reservation_unknown","sandbox_launch_reservation_mismatch","sandbox_launch_exec_claimed","sandbox_launch_input_mismatch"]},"paths":{"type":"null"}}}},{"if":{"properties":{"state":{"const":"timeout"}},"required":["state"]},"then":{"properties":{"code":{"enum":["sandbox_placement_operation_timeout","sandbox_placement_end_reached"]},"paths":{"type":"null"}}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1050 — Instructions

```json
{"oneOf":[{"type":"object","additionalProperties":false,"required":["source"],"properties":{"source":{"const":"none"}}},{"type":"object","additionalProperties":false,"required":["source","path"],"properties":{"source":{"const":"snapshot"},"path":{"$ref":"#/$defs/RepoPath"}}},{"type":"object","additionalProperties":false,"required":["source","base64"],"properties":{"source":{"const":"inline"},"base64":{"type":"string","maxLength":43692,"pattern":"^[A-Za-z0-9+/]*={0,2}$"}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1100 — Command

```json
{"type":"object","additionalProperties":false,"required":["template_id","template_sha256"],"properties":{"template_id":{"$ref":"#/$defs/TemplateId"},"template_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1116 — LaunchRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation","workload","image_digest","policy_vector","providers","command","action","result_kind","snapshot","instructions","seed","paths","timeout_seconds","caller_context"],"properties":{"schema":{"const":"placement.launch.request.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Reservation"},"workload":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Workload"},"image_digest":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Sha256Digest"},"policy_vector":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/PolicyVector"},"providers":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/ProviderNames"},"command":{"$ref":"#/$defs/Command"},"action":{"$ref":"#/$defs/LaunchAction"},"result_kind":{"$ref":"#/$defs/ResultKind"},"snapshot":{"$ref":"#/$defs/Snapshot"},"instructions":{"$ref":"#/$defs/Instructions"},"seed":{"oneOf":[{"type":"null"},{"$ref":"#/$defs/SeedDeclaration"}]},"paths":{"oneOf":[{"$ref":"#/$defs/PreparedPaths"},{"type":"null"}]},"timeout_seconds":{"type":"integer","minimum":1,"maximum":3600},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"workload":{"const":"pi-runner"}},"required":["workload"]},"then":{"properties":{"policy_vector":{"enum":["full-remote-pi-runner","minimal-without-app"]},"action":{"const":"execution"},"result_kind":{"const":"none"},"paths":{"$ref":"#/$defs/PreparedPaths"}}}},{"if":{"properties":{"workload":{"const":"implementation"}},"required":["workload"]},"then":{"properties":{"action":{"const":"execution"},"result_kind":{"const":"patch"},"seed":{"type":"null"}}}},{"if":{"properties":{"workload":{"enum":["leg","qualification"]}},"required":["workload"]},"then":{"properties":{"action":{"const":"review"},"result_kind":{"const":"result"},"seed":{"type":"null"}}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1290 — ReturnDescriptor

```json
{"type":"object","additionalProperties":false,"required":["kind","format","path","sha256","byte_length","directory_mode","file_mode","base_commit"],"properties":{"kind":{"enum":["patch","result"]},"format":{"enum":["worker_proposal_bytes","json_object"]},"path":{"$ref":"#/$defs/AbsolutePath"},"sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"byte_length":{"type":"integer","minimum":0,"maximum":67108864},"directory_mode":{"const":"0700"},"file_mode":{"const":"0600"},"base_commit":{"oneOf":[{"type":"string","pattern":"^([0-9a-f]{40}|[0-9a-f]{64})$"},{"type":"null"}]}},"allOf":[{"if":{"properties":{"kind":{"const":"patch"}},"required":["kind"]},"then":{"properties":{"format":{"const":"worker_proposal_bytes"},"base_commit":{"type":"string"}}}},{"if":{"properties":{"kind":{"const":"result"}},"required":["kind"]},"then":{"properties":{"format":{"const":"json_object"},"byte_length":{"maximum":1048576},"base_commit":{"type":"null"}}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1395 — InventoryCounts

```json
{"type":"object","additionalProperties":false,"required":["tracked","untracked","ignored","omitted","masked","special"],"properties":{"tracked":{"type":"integer","minimum":0},"untracked":{"type":"integer","minimum":0},"ignored":{"type":"integer","minimum":0},"omitted":{"type":"integer","minimum":0},"masked":{"type":"integer","minimum":0},"special":{"type":"integer","minimum":0}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1433 — SnapshotEvidence

```json
{"type":"object","additionalProperties":false,"required":["mode","content_sha256","base_commit","input_commit","overlay_sha256","inventory_sha256","masks_sha256","counts","byte_total"],"properties":{"mode":{"$ref":"#/$defs/SnapshotMode"},"content_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"base_commit":{"oneOf":[{"type":"string","pattern":"^([0-9a-f]{40}|[0-9a-f]{64})$"},{"type":"null"}]},"input_commit":{"oneOf":[{"type":"string","pattern":"^([0-9a-f]{40}|[0-9a-f]{64})$"},{"type":"null"}]},"overlay_sha256":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},{"type":"null"}]},"inventory_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"masks_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"counts":{"$ref":"#/$defs/InventoryCounts"},"byte_total":{"type":"integer","minimum":0}},"allOf":[{"if":{"properties":{"mode":{"const":"git_overlay"}},"required":["mode"]},"then":{"properties":{"overlay_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"}}},"else":{"properties":{"overlay_sha256":{"type":"null"}}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1529 — LaunchEvidence

```json
{"type":"object","additionalProperties":false,"required":["snapshot","launch_digest","template_sha256","image_digest","policy_digest","egress_sha256","transport_id","caps_sha256","bridge_attached","stdout_sha256","stderr_sha256","exit_status","duration_ms","renewals"],"properties":{"snapshot":{"oneOf":[{"$ref":"#/$defs/SnapshotEvidence"},{"type":"null"}]},"launch_digest":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},{"type":"null"}]},"template_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"image_digest":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Sha256Digest"},"policy_digest":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Sha256Digest"},"egress_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Sha256Digest"},"transport_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"caps_sha256":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},{"type":"null"}]},"bridge_attached":{"type":"boolean"},"stdout_sha256":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},{"type":"null"}]},"stderr_sha256":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},{"type":"null"}]},"exit_status":{"oneOf":[{"type":"integer","minimum":-255,"maximum":255},{"type":"null"}]},"duration_ms":{"type":"integer","minimum":0},"renewals":{"type":"integer","minimum":0}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1639 — LaunchResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","attempt_id","state","code","snapshot_reason","seed_reason","admission_diagnostic","termination","worker_invocations","envelope_digest","scratch_path","tree_path","return","evidence","caller_context"],"properties":{"schema":{"const":"placement.launch.response.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"attempt_id":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},{"type":"null"}]},"state":{"enum":["finished","refused","uncertain"]},"code":{"oneOf":[{"$ref":"#/$defs/LaunchResultCode"},{"type":"null"}]},"snapshot_reason":{"oneOf":[{"$ref":"#/$defs/SnapshotReason"},{"type":"null"}]},"seed_reason":{"oneOf":[{"$ref":"#/$defs/SeedReason"},{"type":"null"}]},"admission_diagnostic":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/AdmissionDiagnostic"},{"type":"null"}]},"termination":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Termination"},{"type":"null"}]},"worker_invocations":{"type":"integer","minimum":0,"maximum":1},"envelope_digest":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},{"type":"null"}]},"scratch_path":{"oneOf":[{"$ref":"#/$defs/AbsolutePath"},{"type":"null"}]},"tree_path":{"oneOf":[{"$ref":"#/$defs/AbsolutePath"},{"type":"null"}]},"return":{"oneOf":[{"$ref":"#/$defs/ReturnDescriptor"},{"type":"null"}]},"evidence":{"oneOf":[{"$ref":"#/$defs/LaunchEvidence"},{"type":"null"}]},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"state":{"const":"refused"}},"required":["state"]},"then":{"properties":{"code":{"$ref":"#/$defs/LaunchResultCode"},"termination":{"type":"null"},"worker_invocations":{"const":0},"return":{"type":"null"},"scratch_path":{"type":"null"},"tree_path":{"type":"null"}}}},{"if":{"properties":{"state":{"const":"finished"}},"required":["state"]},"then":{"properties":{"attempt_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"termination":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Termination"},"envelope_digest":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"evidence":{"$ref":"#/$defs/LaunchEvidence"},"snapshot_reason":{"type":"null"},"admission_diagnostic":{"type":"null"},"scratch_path":{"$ref":"#/$defs/AbsolutePath"},"tree_path":{"$ref":"#/$defs/AbsolutePath"}}}},{"if":{"properties":{"state":{"const":"uncertain"}},"required":["state"]},"then":{"properties":{"code":{"enum":["sandbox_placement_lost_after_launch","sandbox_placement_operation_timeout","sandbox_launch_upload_refused"]},"return":{"type":"null"},"snapshot_reason":{"type":"null"},"admission_diagnostic":{"type":"null"}}}},{"if":{"properties":{"code":{"const":"sandbox_launch_snapshot_refused"}},"required":["code"]},"then":{"properties":{"snapshot_reason":{"$ref":"#/$defs/SnapshotReason"}}},"else":{"properties":{"snapshot_reason":{"type":"null"}}}},{"if":{"properties":{"code":{"const":"sandbox_launch_seed_refused"}},"required":["code"]},"then":{"properties":{"seed_reason":{"$ref":"#/$defs/SeedReason"}}},"else":{"properties":{"seed_reason":{"type":"null"}}}},{"if":{"properties":{"code":{"const":"sandbox_launch_admission_refused"}},"required":["code"]},"then":{"properties":{"admission_diagnostic":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/AdmissionDiagnostic"}}},"else":{"properties":{"admission_diagnostic":{"type":"null"}}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:1984 — StatusRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","launch_request_id","caller_context"],"properties":{"schema":{"const":"placement.launch.status.request.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"launch_request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:2012 — StatusResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","launch_request_id","state","launch","run_id","scratch_path","tree_path","caller_context"],"properties":{"schema":{"const":"placement.launch.status.response.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"launch_request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"state":{"enum":["queued","running","cancelling","finished","refused","uncertain","unknown_attempt"]},"launch":{"oneOf":[{"$ref":"#/$defs/LaunchResponse"},{"type":"null"}]},"run_id":{"oneOf":[{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},{"type":"null"}]},"scratch_path":{"oneOf":[{"$ref":"#/$defs/AbsolutePath"},{"type":"null"}]},"tree_path":{"oneOf":[{"$ref":"#/$defs/AbsolutePath"},{"type":"null"}]},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"state":{"enum":["finished","refused","uncertain"]}},"required":["state"]},"then":{"properties":{"launch":{"$ref":"#/$defs/LaunchResponse"}}},"else":{"properties":{"launch":{"type":"null"}}}},{"if":{"properties":{"state":{"enum":["queued","running","cancelling"]}},"required":["state"]},"then":{"properties":{"scratch_path":{"$ref":"#/$defs/AbsolutePath"},"run_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"tree_path":{"$ref":"#/$defs/AbsolutePath"}}}},{"if":{"properties":{"state":{"const":"unknown_attempt"}},"required":["state"]},"then":{"properties":{"scratch_path":{"type":"null"},"run_id":{"type":"null"},"tree_path":{"type":"null"}}}},{"if":{"properties":{"state":{"const":"finished"}},"required":["state"]},"then":{"properties":{"run_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"scratch_path":{"$ref":"#/$defs/AbsolutePath"},"tree_path":{"$ref":"#/$defs/AbsolutePath"}}}}]}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:2207 — CancelRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","launch_request_id","deadline_ms","caller_context"],"properties":{"schema":{"const":"placement.launch.cancel.request.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"launch_request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"deadline_ms":{"type":"integer","minimum":1,"maximum":30000},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:2241 — CancelResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","launch_request_id","state","caller_context"],"properties":{"schema":{"const":"placement.launch.cancel.response.v1"},"request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"reservation_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/OpaqueId"},"launch_request_id":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/RequestId"},"state":{"enum":["cancelled","already_terminal","cancel_pending","unknown_attempt"]},"caller_context":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:2278 — TemplateSummary

```json
{"type":"object","additionalProperties":false,"required":["template_id","template_sha256","workload"],"properties":{"template_id":{"$ref":"#/$defs/TemplateId"},"template_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"workload":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Workload"}}}
```

### plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:2298 — LaunchVersionResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","client","protocol_schema_sha256","placement_protocol_schema_sha256","config_sha256","seat_caps_sha256","local_pi_runner_launcher","local_link_root","seed_root","seed_limits","templates"],"properties":{"schema":{"const":"placement.launch.version.response.v1"},"client":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/Client"},"protocol_schema_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"placement_protocol_schema_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"config_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"seat_caps_sha256":{"$ref":"https://github.com/Consiliency/agent-harness/plans/artifacts/v13-PLACECLI-contract-v1.schema.json#/$defs/HexSha256"},"local_pi_runner_launcher":{"enum":["toolkit_interim","laneexec"]},"local_link_root":{"oneOf":[{"$ref":"#/$defs/AbsolutePath"},{"type":"null"}]},"seed_root":{"oneOf":[{"$ref":"#/$defs/AbsolutePath"},{"type":"null"}]},"seed_limits":{"oneOf":[{"$ref":"#/$defs/SeedLimits"},{"type":"null"}]},"templates":{"type":"array","maxItems":64,"items":{"$ref":"#/$defs/TemplateSummary"}}},"allOf":[{"if":{"properties":{"seed_root":{"type":"null"}},"required":["seed_root"]},"then":{"properties":{"seed_limits":{"type":"null"}}},"else":{"properties":{"seed_limits":{"$ref":"#/$defs/SeedLimits"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:208 — Sha256Digest

```json
{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:212 — HexSha256

```json
{"type":"string","pattern":"^[0-9a-f]{64}$"}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:216 — RequestId

```json
{"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:220 — OpaqueId

```json
{"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:224 — ProviderName

```json
{"type":"string","pattern":"^[a-z][a-z0-9_-]{0,63}$","description":"Operator-configured provider-name key only. Dots, slashes and colons are excluded; the value is never interpreted as a hostname, URL, endpoint or model name."}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:229 — ProviderNames

```json
{"type":"array","minItems":1,"maxItems":16,"uniqueItems":true,"items":{"$ref":"#/$defs/ProviderName"}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:238 — Timestamp

```json
{"type":"string","format":"date-time"}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:242 — CallerContext

```json
{"type":"object","maxProperties":16,"propertyNames":{"pattern":"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"},"additionalProperties":{"oneOf":[{"type":"string","maxLength":512},{"type":"integer","minimum":-9007199254740991,"maximum":9007199254740991},{"type":"boolean"},{"type":"null"}]}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:268 — LocalHeadroomConfig

```json
{"type":"object","additionalProperties":false,"required":["memory_available_bytes_minimum_floor","memory_available_total_ram_fraction_minimum","load_per_cpu_percent_maximum_exclusive","io_pressure_full_avg10_percent_maximum_exclusive","memory_pressure_some_avg10_percent_maximum_exclusive","live_sandboxes_maximum_exclusive","observation_age_seconds_maximum"],"properties":{"memory_available_bytes_minimum_floor":{"type":"integer","minimum":0},"memory_available_total_ram_fraction_minimum":{"type":"number","minimum":0,"maximum":1},"load_per_cpu_percent_maximum_exclusive":{"type":"number","minimum":0,"maximum":100},"io_pressure_full_avg10_percent_maximum_exclusive":{"type":"number","minimum":0,"maximum":100},"memory_pressure_some_avg10_percent_maximum_exclusive":{"type":"number","minimum":0,"maximum":100},"live_sandboxes_maximum_exclusive":{"type":"integer","minimum":1},"observation_age_seconds_maximum":{"type":"number","minimum":0}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:315 — Workload

```json
{"enum":["leg","qualification","implementation","pi-runner"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:323 — PolicyVector

```json
{"enum":["minimal-with-app","minimal-without-app","full-remote-pi-runner"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:330 — Client

```json
{"enum":["agent-harness","agent-toolkit"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:336 — TargetKind

```json
{"enum":["local","openshell","e2b"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:343 — AdmissionOutcome

```json
{"enum":["admitted","at_capacity","refused","unreachable","timeout"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:352 — AdmissionReason

```json
{"enum":["no_capacity","pressure","fairness_wait","reserved_for_other_client","recovering","telemetry_stale","slice_unbounded","untracked_vms","ledger_restored","internal"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:366 — CoordinatorErrorCode

```json
{"enum":["at_capacity","owner_mismatch","not_enrolled","unknown_lease","fenced","expired","lifetime_exceeded","digest_mismatch","duplicate_binding","snapshot_expired","invalid_request","workload_unsupported","deadline_exceeded","unavailable"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:384 — PlacementCode

```json
{"enum":["sandbox_placement_required_unavailable","sandbox_placement_driver_unavailable","sandbox_placement_ref_invalid","sandbox_placement_capability_undeclared","sandbox_placement_plugin_unavailable","sandbox_placement_backend_unregistered","sandbox_placement_unreachable","sandbox_placement_budget_spent","sandbox_placement_at_capacity","sandbox_placement_capacity_exhausted","sandbox_placement_refused","sandbox_placement_code_invalid","sandbox_placement_operation_timeout","sandbox_placement_capability_unmet","sandbox_placement_release_unconfirmed","sandbox_placement_local_release_unconfirmed","sandbox_placement_not_enrolled","sandbox_placement_identity_mismatch","sandbox_placement_provider_refused","sandbox_placement_workload_unsupported","sandbox_placement_lost_after_launch","sandbox_placement_end_reached"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:410 — ResultCode

```json
{"oneOf":[{"$ref":"#/$defs/CoordinatorErrorCode"},{"$ref":"#/$defs/PlacementCode"}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:420 — AdmissionDiagnostic

```json
{"enum":["envelope_schema_invalid","envelope_digest_mismatch","authority_foreign","authority_baseline_stale","locator_not_repo_relative","raw_output_in_record","dependency_digest_required","workspace_source_inconsistent","executable_chain_invalid","baseline_reference_required","target_map_outside_scope","tier_unqualified","route_not_qualified","constraint_unsupported","workspace_not_separate_copy","grant_unqualified","stop_policy_unbounded","timeout_over_declared_max","launch_instructions_mismatch","launch_reference_mismatch","launch_argv_mismatch","launch_executable_mismatch","launch_workspace_mismatch","launch_environment_mismatch","launch_policy_mismatch","launch_timeout_mismatch","launch_input_unbound","task_unbound","dependency_route_unwired","codec_unavailable"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:454 — RunState

```json
{"enum":["finished","refused"]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:460 — Termination

```json
{"type":"object","additionalProperties":false,"required":["reason","signal","by"],"properties":{"reason":{"enum":["completed","cancelled","timed_out","failed_to_start"]},"signal":{"type":["string","null"],"maxLength":32},"by":{"enum":["worker","harness","operator"]}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:493 — PlacementTarget

```json
{"type":"object","additionalProperties":false,"required":["name","kind","rank"],"properties":{"name":{"$ref":"#/$defs/OpaqueId"},"kind":{"$ref":"#/$defs/TargetKind"},"rank":{"type":"integer","minimum":0,"maximum":255}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:515 — TrailEntry

```json
{"type":"object","additionalProperties":false,"required":["target","outcome","code","reason"],"properties":{"target":{"$ref":"#/$defs/OpaqueId"},"outcome":{"$ref":"#/$defs/AdmissionOutcome"},"code":{"oneOf":[{"$ref":"#/$defs/ResultCode"},{"type":"null"}]},"reason":{"oneOf":[{"$ref":"#/$defs/AdmissionReason"},{"type":"null"}]}},"allOf":[{"if":{"properties":{"outcome":{"const":"admitted"}},"required":["outcome"]},"then":{"properties":{"code":{"type":"null"}}},"else":{"properties":{"code":{"$ref":"#/$defs/ResultCode"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:581 — LeaseFlags

```json
{"type":"object","additionalProperties":false,"required":["reserved","create_settled","ready","exec_claimed","fenced","destruction_observed","cleanup_pending","barrier_confirmed","expired"],"properties":{"reserved":{"type":"boolean"},"create_settled":{"type":"boolean"},"ready":{"type":"boolean"},"exec_claimed":{"type":"boolean"},"fenced":{"type":"boolean"},"destruction_observed":{"type":"boolean"},"cleanup_pending":{"type":"boolean"},"barrier_confirmed":{"type":"boolean"},"expired":{"type":"boolean"}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:625 — ForwardTcpUnixBridge

```json
{"type":"object","additionalProperties":false,"required":["kind","service_name","socket_path","directory_mode","socket_mode","lifetime"],"properties":{"kind":{"const":"forward_tcp_unix"},"service_name":{"$ref":"#/$defs/OpaqueId"},"socket_path":{"type":"string","pattern":"^/[^\\u0000\\r\\n]{1,4095}$"},"directory_mode":{"const":"0700"},"socket_mode":{"const":"0600"},"lifetime":{"const":"reservation"}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:658 — Reservation

```json
{"type":"object","additionalProperties":false,"required":["schema","reservation_id","workload","target","transport_id","image_digest","policy_vector","policy_digest","providers","egress_sha256","client","inventory","rank_policy","lease_id","expires_at","config_sha256","bridge"],"properties":{"schema":{"const":"placement.reservation.v1"},"reservation_id":{"$ref":"#/$defs/OpaqueId"},"workload":{"$ref":"#/$defs/Workload"},"target":{"$ref":"#/$defs/PlacementTarget"},"transport_id":{"$ref":"#/$defs/OpaqueId"},"image_digest":{"$ref":"#/$defs/Sha256Digest"},"policy_vector":{"$ref":"#/$defs/PolicyVector"},"policy_digest":{"$ref":"#/$defs/Sha256Digest"},"providers":{"$ref":"#/$defs/ProviderNames"},"egress_sha256":{"$ref":"#/$defs/Sha256Digest"},"client":{"$ref":"#/$defs/Client"},"inventory":{"$ref":"#/$defs/Client"},"rank_policy":{"enum":["agent_executor","seats_single_target"]},"lease_id":{"oneOf":[{"$ref":"#/$defs/OpaqueId"},{"type":"null"}]},"expires_at":{"oneOf":[{"$ref":"#/$defs/Timestamp"},{"type":"null"}]},"config_sha256":{"$ref":"#/$defs/HexSha256"},"bridge":{"oneOf":[{"$ref":"#/$defs/ForwardTcpUnixBridge"},{"type":"null"}]}},"allOf":[{"if":{"properties":{"workload":{"const":"pi-runner"}},"required":["workload"]},"then":{"properties":{"client":{"const":"agent-toolkit"},"inventory":{"const":"agent-toolkit"},"rank_policy":{"const":"agent_executor"}}}},{"if":{"properties":{"workload":{"enum":["leg","qualification","implementation"]}},"required":["workload"]},"then":{"properties":{"client":{"const":"agent-harness"},"inventory":{"const":"agent-harness"},"rank_policy":{"const":"seats_single_target"}}}},{"if":{"properties":{"workload":{"enum":["pi-runner","leg"]},"target":{"properties":{"kind":{"const":"openshell"}},"required":["kind"]}},"required":["workload","target"]},"then":{"properties":{"bridge":{"$ref":"#/$defs/ForwardTcpUnixBridge"}},"if":{"properties":{"workload":{"const":"pi-runner"}}},"then":{"properties":{"policy_vector":{"const":"full-remote-pi-runner"}}}}},{"if":{"properties":{"workload":{"const":"pi-runner"},"target":{"properties":{"kind":{"const":"local"}},"required":["kind"]}},"required":["workload","target"]},"then":{"properties":{"bridge":{"type":"null"},"policy_vector":{"const":"minimal-without-app"}}}},{"if":{"not":{"properties":{"workload":{"enum":["pi-runner","leg"]},"target":{"properties":{"kind":{"const":"openshell"}},"required":["kind"]}},"required":["workload","target"]}},"then":{"properties":{"bridge":{"type":"null"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:904 — ReserveRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","workload","ttl_s","image_digest","policy_vector","providers","deadline_ms","caller_context"],"properties":{"schema":{"const":"placement.reserve.request.v1"},"request_id":{"$ref":"#/$defs/RequestId"},"workload":{"$ref":"#/$defs/Workload"},"ttl_s":{"type":"integer","minimum":1,"maximum":3600},"image_digest":{"$ref":"#/$defs/Sha256Digest"},"policy_vector":{"$ref":"#/$defs/PolicyVector"},"providers":{"$ref":"#/$defs/ProviderNames"},"deadline_ms":{"type":"integer","minimum":1,"maximum":900000,"description":"Budget for the whole reserve walk, in milliseconds. The cap is admit_wait_s plus transfer_allowance_s from the pinned driver defaults (600s + 300s). Each coordinator RPC uses a shorter deadline that does not exceed the remaining budget."},"caller_context":{"$ref":"#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"workload":{"const":"pi-runner"}},"required":["workload"]},"then":{"properties":{"policy_vector":{"const":"full-remote-pi-runner"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:972 — ReserveResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","outcome","code","reason","reservation","trail","caller_context"],"properties":{"schema":{"const":"placement.reserve.response.v1"},"request_id":{"$ref":"#/$defs/RequestId"},"outcome":{"$ref":"#/$defs/AdmissionOutcome"},"code":{"oneOf":[{"$ref":"#/$defs/ResultCode"},{"type":"null"}]},"reason":{"oneOf":[{"$ref":"#/$defs/AdmissionReason"},{"type":"null"}]},"reservation":{"oneOf":[{"$ref":"#/$defs/Reservation"},{"type":"null"}]},"trail":{"type":"array","minItems":1,"maxItems":16,"items":{"$ref":"#/$defs/TrailEntry"}},"caller_context":{"$ref":"#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"outcome":{"const":"admitted"}},"required":["outcome"]},"then":{"properties":{"code":{"type":"null"},"reason":{"type":"null"},"reservation":{"$ref":"#/$defs/Reservation"}}},"else":{"properties":{"code":{"$ref":"#/$defs/ResultCode"},"reservation":{"type":"null"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1075 — ReleaseRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation","deadline_ms","caller_context"],"properties":{"schema":{"const":"placement.release.request.v1"},"request_id":{"$ref":"#/$defs/RequestId"},"reservation":{"$ref":"#/$defs/Reservation"},"deadline_ms":{"type":"integer","minimum":1,"maximum":30000},"caller_context":{"$ref":"#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1105 — ReleaseResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","reservation_id","state","code","flags","caller_context"],"properties":{"schema":{"const":"placement.release.response.v1"},"request_id":{"$ref":"#/$defs/RequestId"},"reservation_id":{"$ref":"#/$defs/OpaqueId"},"state":{"enum":["released","cleanup_pending","unknown_reservation","rejected"]},"code":{"oneOf":[{"$ref":"#/$defs/PlacementCode"},{"type":"null"}]},"flags":{"$ref":"#/$defs/LeaseFlags"},"caller_context":{"$ref":"#/$defs/CallerContext"}},"allOf":[{"if":{"properties":{"state":{"const":"released"}},"required":["state"]},"then":{"properties":{"code":{"type":"null"},"flags":{"properties":{"cleanup_pending":{"const":false},"barrier_confirmed":{"const":true}}}}},"else":{"properties":{"code":{"$ref":"#/$defs/PlacementCode"}}}},{"if":{"properties":{"state":{"const":"cleanup_pending"}},"required":["state"]},"then":{"properties":{"flags":{"properties":{"cleanup_pending":{"const":true},"barrier_confirmed":{"const":false}}}}}},{"if":{"properties":{"state":{"const":"unknown_reservation"}},"required":["state"]},"then":{"properties":{"code":{"const":"sandbox_placement_refused"},"flags":{"properties":{"reserved":{"const":false},"cleanup_pending":{"const":false},"barrier_confirmed":{"const":true}}}}}},{"if":{"properties":{"state":{"const":"rejected"}},"required":["state"]},"then":{"properties":{"code":{"const":"sandbox_placement_refused"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1262 — InventoryReapResult

```json
{"type":"object","additionalProperties":false,"required":["client","inventory","examined","destroyed","pending","code"],"properties":{"client":{"$ref":"#/$defs/Client"},"inventory":{"$ref":"#/$defs/Client"},"examined":{"type":"integer","minimum":0},"destroyed":{"type":"integer","minimum":0},"pending":{"type":"integer","minimum":0},"code":{"oneOf":[{"$ref":"#/$defs/PlacementCode"},{"type":"null"}]}},"allOf":[{"if":{"properties":{"client":{"const":"agent-harness"}},"required":["client"]},"then":{"properties":{"inventory":{"const":"agent-harness"}}}},{"if":{"properties":{"client":{"const":"agent-toolkit"}},"required":["client"]},"then":{"properties":{"inventory":{"const":"agent-toolkit"}}}}]}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1340 — ReapRequest

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","scope","deadline_ms","max_items","caller_context"],"properties":{"schema":{"const":"placement.reap.request.v1"},"request_id":{"$ref":"#/$defs/RequestId"},"scope":{"const":"caller_inventory"},"deadline_ms":{"type":"integer","minimum":1,"maximum":30000},"max_items":{"type":"integer","minimum":1,"maximum":1000},"caller_context":{"$ref":"#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1376 — ReapResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","request_id","state","inventories","caller_context"],"properties":{"schema":{"const":"placement.reap.response.v1"},"request_id":{"$ref":"#/$defs/RequestId"},"state":{"enum":["complete","cleanup_pending"]},"inventories":{"type":"array","minItems":1,"maxItems":1,"items":{"$ref":"#/$defs/InventoryReapResult"}},"caller_context":{"$ref":"#/$defs/CallerContext"}}}
```

### plans/artifacts/v13-PLACECLI-contract-v1.schema.json:1412 — VersionResponse

```json
{"type":"object","additionalProperties":false,"required":["schema","client","protocol_schema_sha256","config_sha256","local_headroom"],"properties":{"schema":{"const":"placement.version.response.v1"},"client":{"$ref":"#/$defs/Client"},"protocol_schema_sha256":{"$ref":"#/$defs/HexSha256"},"config_sha256":{"$ref":"#/$defs/HexSha256"},"local_headroom":{"$ref":"#/$defs/LocalHeadroomConfig"}}}
```

## Amendment seal

Artifact: `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`

Old sha256: `bd0e6694e6df9e4ae0bc640c138645adf6b49e8f56aa3f5af7488107062676f3`

New sha256: `a9ae6355056b373c5746ef50920f6a4dab4981b7d55f59d4176c240cdd22f40c`

Manifest row: `v13-LANEEXEC-amend-landed-sweep`; prior rows remain unchanged.

## Exact amended text (old → new)

The following diff is restricted to plan/frozen-input sentences and their seal;
STOP recommendations are not applied as design changes.

```diff
diff --git a/plans/artifacts/v13-LANEEXEC-contract-v1.schema.json b/plans/artifacts/v13-LANEEXEC-contract-v1.schema.json
index 7ef500206..48c9d522e 100644
--- a/plans/artifacts/v13-LANEEXEC-contract-v1.schema.json
+++ b/plans/artifacts/v13-LANEEXEC-contract-v1.schema.json
@@ -490,7 +490,7 @@
     "toolkit": "The toolkit shim reads scratch_path from status and puts exactly that value in the link hello as its scratch directory. It never derives or substitutes another value. On openshell, remote-inner checks it against its own derivation from its --landlock policy path and ends the run on a difference before it opens any tree."
   },
   "x-envelope-construction": {
-    "rule": "LaneExec builds one admitted launch envelope v2 from one capture and admits it through the v12 admission seam (supervised_launch.prepare_launch with the trusted validator and codec binding). Admission refusal is state refused, code sandbox_launch_admission_refused with the pinned AdmissionDiagnostic, and placement never relabels it.",
+    "rule": "LaneExec builds one admitted launch envelope v2 from one capture and admits it through the v12 admission seam (supervised_launch.prepare_launch with the trusted validator and codec binding). Admission refusal is state refused, code sandbox_launch_admission_refused with the pinned AdmissionDiagnostic, and placement never relabels it. The landed prepare_launch requires keyword-only validator, decoder and config and currently consumes a local fixture, while the production CLI refuses codec_unavailable. This is a proposed v2 integration, not a capability supplied by the landed WORKER gate; resolve the sweep dependency STOP before execution.",
     "fields": {
       "assignment_digest": "the in-process lane caller's assignment digest; for a process client the SHA-256 of the RFC 8785 LaunchRequest with caller_context removed",
       "units": "the in-process lane caller's units; for a process client target_unit_ids [launch:<request_id>], no neighbours, snapshot_ref the inventory_sha256 and crosswalk_ref the SHA-256 of the RFC 8785 repository identity",
@@ -526,7 +526,7 @@
   },
   "x-local-cgroup": {
     "scope": "Every placed LOCAL workload: pi-runner under laneexec, implementation, and any local leg or qualification. Seat launches outside placement stay with the SEATS launcher (XREQ-SEATS-LOCAL-CGROUP-1).",
-    "automatic_paths": "For a LaneExec local launch, the caps contract's automatic paths are the attempt's execution tree, home, out and scratch directories. Each resolves through seat_resource_caps.io_devices, including the caps contract §1a tmpfs carve-out. The operator io_paths entries keep their own rule.",
+    "automatic_paths": "For a LaneExec local launch, the caps contract's automatic paths are the attempt's execution tree, home, out and scratch directories. Each resolves through seat_resource_caps.io_devices, including the caps contract §1a tmpfs carve-out. The operator io_paths entries keep their own rule. The landed io_devices(caps) discovers staging_root and child scratch internally; it accepts no automatic-path argument and currently refuses the tmpfs carve-out. Integration and cleanup ownership remain a sweep STOP.",
     "record": "The effective seat_resource_caps.v1 record from the pinned caps contract §2 sources, through seat_resource_caps.load_caps. LaneExec applies the whole record. The v13-required subset is memory.max, cpu.weight and both io.weight and io.max, which satisfies 'either'. seat_caps_sha256 = caps_sha256(effective caps) is part of the canonical host configuration hashed as config_sha256.",
     "parent": "One transient capped parent cgroup per (client, reservation_id), created before the first chain process. Its key is laneexec:<client>:<reservation_id>, passed to seat_resource_caps.capped_popen. Every process of the attempt is a descendant of it, a second independent capped parent for the same live reservation refuses, and the parent is collected after the attempt is reaped.",
     "proof": "Child-side readback through the trusted seat_resource_caps_enter helper of the pinned caps contract §4 is the only evidence. Any absent or differing value ends the launch before the target runs.",
diff --git a/plans/phase-plan-v13-LANEEXEC.md b/plans/phase-plan-v13-LANEEXEC.md
index eb13aa468..5d8060818 100644
--- a/plans/phase-plan-v13-LANEEXEC.md
+++ b/plans/phase-plan-v13-LANEEXEC.md
@@ -18,7 +18,7 @@ after a reservation. agent-toolkit#54 already reserves through PLACECLI, but it
 cannot run a remote Pi end to end until these launch inputs exist.

 **Frozen artifact.** `plans/artifacts/v13-LANEEXEC-contract-v1.schema.json`,
-sha256 `bd0e6694e6df9e4ae0bc640c138645adf6b49e8f56aa3f5af7488107062676f3`,
+sha256 `a9ae6355056b373c5746ef50920f6a4dab4981b7d55f59d4176c240cdd22f40c`,
 holds IF-0-LANEEXEC-1. It covers:

 - the process entry `agent-harness-launch --client … prepare|launch|status|cancel|version`
@@ -313,9 +313,12 @@ diagnostics or evidence.
 Work-start gates (non-human, `blocker_class=upstream_phase_unmet`):

 - PLACECLI implemented, including errata-1;
-- EXT-WORKER (v12 IF-0-WORKER-1 and IF-0-JOURNAL-1);
-- IF-0-JAILCORE-4 (`seat_resource_caps.py`) landed, including the caps contract §1a
-  carve-out and its §7 (j) tests.
+- EXT-WORKER has landed (v12 IF-0-WORKER-1 and IF-0-JOURNAL-1), with
+  local fixture scope; public-v2 admission and lifecycle adaptation remain
+  unresolved as recorded in `plans/artifacts/v13-LANEEXEC-landed-sweep.md`;
+- IF-0-JAILCORE-4 base caps have landed; the caps contract §1a tmpfs
+  carve-out still refuses in `seat_resource_caps.py`, so that prerequisite
+  and its §7 (j) acceptance remain unmet.

 EXT-LAUNCHSITE and EXT-OPENSH are activation prerequisites; their offline
 controls run here.
```

## Validator results on dev0

- validate_plan_doc.py: PASS; one existing (N) release-shaped reducer warning.
- plan_pin_lint.find_plan_pin_violations: PASS, zero findings.
- plan_manifest check --repo .: PASS, canonical=67, registered=67, unregistered=0.
- test_legible_roadmap_contract.py: **1 failed, 63 passed in 38.27s**. The failing node is
  `test_assumption_probe_mutation_and_positive_control[LEGIBLE-A3-REVIEWTRUTH-TRANSITION]`;
  the live positive control returns observation_unavailable / authority_missing
  at test_legible_roadmap_contract.py:1934. This same failure is recorded in the
  input v12-WORKER-journal-sweep.md. It remains a failure, not a passing check.
- The contract-floor check also emitted ContractFloorUnverified; installed
  metadata does not prove ownership of the source-imported runtime. No governance
  configuration or dependency metadata was altered to suppress either result.
- Planner literal validation, diff whitespace and append-only manifest checks: PASS.
- Headroom inspected before every narrow command; serial pytest under timeout
  900, no xdist and no cache provider. No interruption, build, full suite,
  live provider, Gate A dispatch, review dispatch or merge occurred.

All 15 published CLOSEOUT input hash/blob pairs and the delivered toolkit
manifest plus its 27 file hashes were independently checked (43/43 matches).
Local frozen input hashes match the inspected tree. The new draft seals do not
claim that downstream consumers have adopted these bytes.
