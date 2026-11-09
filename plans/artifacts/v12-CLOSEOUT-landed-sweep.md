# v12 CLOSEOUT: landed-input sweep — 2026-11-09

Inspected input: `a493c46cc` on `origin/main` (WORKER merge). All line citations
in the sweep table and inventories refer to that immutable input, before this
amendment. No output commit identity is prescribed. This is a static design
reconciliation, not runtime qualification or approval to build.

MATCH means a consumed boundary is compatible or explicitly prospective;
MISMATCH includes an omitted integration boundary. A MISMATCH marked STOP is
**not corrected** by guessing a design. Prospective output schemas and ownership
claims are inventoried separately below; their presence is not counted as a
passing implementation. The main table has **30 MATCH / 9 MISMATCH** rows.

AGENTS.md ratio diagnosis: the plans froze downstream integration before the
upstream implementations stabilized. LANEEXEC has already had multiple input/
activation amendments without its implementation. This sweep is one consolidated
factual amendment per phase. STOP items require a single coordinated disposition,
not repeated speculative plan edits. Review remains pending; no build or merge.

## Sweep table

| Plan/artifact line at input | Result | Consumed boundary | Landed code/evidence file:line | Disposition |
| --- | --- | --- | --- | --- |
| plans/phase-plan-v12-CLOSEOUT.md:23 | MISMATCH | Upstream landing state / scope | phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py:19 | FACT corrected: gates landed locally; codec remains unavailable. No public-v2 or activation proof. |
| plans/phase-plan-v12-CLOSEOUT.md:23 | MATCH | JOURNAL landed rev-5 identity, replay and bounded projection | phase-loop-runtime/src/phase_loop_runtime/run_status.py:118 | Available; exact consumed API and nullability inventory below. |
| plans/phase-plan-v12-CLOSEOUT.md:70 | MATCH | Planned v1-default selector is an extension, not a landed signature | phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py:202 | Current loader takes no arguments. SL-0 explicitly owns the change; do not call version= until implemented. |
| plans/phase-plan-v12-CLOSEOUT.md:72 | MATCH | Closed bytes intake and keyword-only definition | phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py:278 | validate_record(bundle, family, record: bytes, *, definition=None); v2 family remains planned. |
| plans/phase-plan-v12-CLOSEOUT.md:81 | MATCH | One-use consume signature remains unchanged | phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py:462 | PreparedLaunch -> LaunchInputs or Refused; current process-local token and fixture identity require v2 adaptation. |
| plans/phase-plan-v12-CLOSEOUT.md:184 | MISMATCH | Worker fixture identity versus external public-v2 identity | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:362 | C-S1/L-S1: WORKER reads top-level run_id/attempt_id/unit fields, public-v2 binds identity separately. No direct pass-through. |
| plans/phase-plan-v12-CLOSEOUT.md:196 | MISMATCH | Payload echo at actual JOURNAL writer | phase-loop-runtime/src/phase_loop_runtime/run_status.py:1338 | C-S1: no payload-echo argument; caller_context_sha256 commits only a digest. |
| plans/phase-plan-v12-CLOSEOUT.md:196 | MISMATCH | Fractional JCS echo domain | phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py:87 | C-S1: journal/projection strict integer domain is not public-v2 arbitrary echo domain. |
| plans/phase-plan-v12-CLOSEOUT.md:201 | MATCH | Actual last pre-spawn construction site is already SL-2 owned | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:427 | patch_return.py owns callback; base.py owns capture. New v2 material still needs integration. |
| plans/phase-plan-v12-CLOSEOUT.md:76 | MISMATCH | Production CLI is gated, not implemented public v2 | phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py:100 | FACT documented in frozen baseline; CLOSEOUT owns wiring. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:405 | MISMATCH | Historical receipt transition covers ENVELOPE but omits landed WORKER/JOURNAL | phase-loop-runtime/tests/test_supervised_worker_receipt.py:59 | C-S2; preserve historical bytes and define verification/collection transitions. |
| plans/phase-plan-v12-CLOSEOUT.md:196 | MATCH | Evidence may outlive streams; resolver checks attempt digest and retained bytes | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py:162 | present / retention_dropped / unknown; private retention accessor follow-up stays agent-harness#1960. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:184 | MATCH | No probes and lifecycle boundary | phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py:359 | Refused before chain; started helper failure -> finished/failed_to_start; v2 capture must preserve boundary. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:209 | MATCH | Readable unacknowledged full line differs from torn line | phase-loop-runtime/src/phase_loop_runtime/run_status.py:1296 | agent-harness#1954: no new reader marker. journal_complete=False / absent anchor remain uncertainty. |
| plans/phase-plan-v12-CLOSEOUT.md:295 | MISMATCH | Complete inventory / fixture / stamping ownership | phase-loop-runtime/tests/test_seat_reference_inventory.py:12 | C-S3; explicit additions need ownership decision. |
| plans/phase-plan-v12-CLOSEOUT.md:298 | MISMATCH | SCHEMA plan existence | plans/phase-plan-v12-SCHEMA.md:3 | FACT corrected; historical SCHEMA plan is present. |
| plans/phase-plan-v12-CLOSEOUT.md:65 | MATCH | Publisher/external trust roots remain unresolved | plans/artifacts/v12-CLOSEOUT-inputs.md:251 | C-S4; no fabricated evidence. |
| plans/phase-plan-v12-CLOSEOUT.md:118 | MATCH | Launch inventory must union with landed entries | phase-loop-runtime/tests/data/seat_launch_references.json:13 | Preserve WORKER rows; update scratch, trusted-helper and reference tests for new sites. |
| plans/phase-plan-v12-CLOSEOUT.md:118 | MATCH | JOURNAL/WORKER receipts exclude shared seat inventory | phase-loop-runtime/tests/test_supervised_worker_receipt.py:60 | agent-harness#1955; no new receipt may pin shared mutable inventory or CHANGELOG. |
| plans/phase-plan-v12-CLOSEOUT.md:118 | MISMATCH | Existing receipts still pin shared docs; WORKER pins shared adapter sources/tests | plans/evidence/supervised-worker/WORKER.md:1526 | Flag for coordinated historical verification; do not pin shared frequently changed files in new evidence. |
| plans/phase-plan-v12-CLOSEOUT.md:118 | MATCH | Jailed Codex remains SEATS-owned; no profile adoption by placement alone | phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py:13354 | Landed 0.7.31 seat route is not v2 WORKER route qualification. |
| plans/phase-plan-v12-CLOSEOUT.md:34 | MATCH | agy v2 catalog and release CLI are independent qualification inputs | phase-loop-runtime/scripts/verify_qualified_agy_image.py:320 | No consumed --source-only invocation exists in these plans. --release runs strict conformance, requires fresh report; no release here. |
| plans/phase-plan-v12-CLOSEOUT.md:287 | MATCH | Docs-accuracy landings preserved as integration baseline | docs/supervised-worker.md:8 | Do not restore pre-audit claims; public-v2/installed/live authority stays separate. |
| plans/phase-plan-v12-CLOSEOUT.md:287 | MATCH | Deferred issues remain separately owned | plans/artifacts/v12-WORKER-contract.md:196 | agent-harness#1954 and agent-harness#1960 do not authorize additional implementation in this sweep. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:34 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/admitted-launch-envelope.schema.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:35 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/admitted-launch-envelope.v2.schema.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:36 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/README.md:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:37 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/README.v2.md:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:38 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/SHA256SUMS:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:39 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/envelope.v2.apply.vectors.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:40 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/envelope.v2.canonical.vectors.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:41 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/envelope.v2.vectors.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:42 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/envelope.vectors.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:43 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/conformance/run-status.vectors.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:44 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/provenance.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:45 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/supervised-run/run-status.schema.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:46 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:core/schemas/version-skew-protocol.schema.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:47 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:pyproject.toml:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |
| plans/artifacts/v12-CLOSEOUT-inputs.md:48 | MATCH | Published input hash and Git blob | Consiliency/consiliency-contract@2b91ef85bfdc76239ae52806b3318513951543ab:package.json:1 | Fresh GitHub API bytes and blob identity compared with the frozen table; no repin. |

## STOP decisions (not applied)

### C-S1

Frozen sentence: SL-2: "Own all six echo cases at the actual JOURNAL writer, with exact JCS numeric and __proto__ preservation."

Evidence: JOURNAL stores caller_context_sha256, not the payload; event accepts only a closed phrase and refs, and its strict parser rejects fractional numbers.

Options: Define an explicit echo storage/API extension owned by CLOSEOUT, or amend the requirement to an independently bound echo artifact.

Recommendation (not a decision): Define the echo artifact and writer integration with JOURNAL ownership explicitly before coding; do not put an arbitrary echo in event.message.

### C-S2

Frozen sentence: Artifact: "SL-1 and SL-3 edit files listed in the ENVELOPE receipt's source_hashes"; plan SL-2 edits run_status and patch_return.

Evidence: WORKER and JOURNAL now also compare live source and producer-node inventories; all three receipts pin shared documentation. WORKER additionally pins shared adapter sources/tests.

Options: Convert affected historical receipts to verification against recorded input blobs/whole-receipt seals, or produce new evidence under a coordinated receipt revision.

Recommendation (not a decision): Preserve historical bytes and outcomes, verify original inputs historically, and publish CLOSEOUT evidence separately. Exclude shared frequently changed files from new receipt pins under agent-harness#1955; name tests, fixtures and stamping companions in ownership.

### C-S3

Frozen sentence: "Existing panel/launcher/review_stage and dependency-routing code remain unchanged"; "complete ownership list".

Evidence: New trusted launcher/inventory companions are not in CLOSEOUT ownership: tests/data/seat_launch_references.json and its three inventory tests, supervised_worker_local fixtures, and stamp_evidence_receipt.py/test_stamp_evidence_receipt.py. patch_return.py owns the actual spawn callback; it is already owned by SL-2.

Options: Authorize the precise companion additions and receipt-test integration, or keep those surfaces unchanged with production-path proof.

Recommendation (not a decision): Assign necessary launch inventories/fixtures to SL-2 and receipt tooling only if used; do not silently claim every omitted file.

### C-S4

Frozen sentence: "authenticated evidence publisher bindings" and "missing evidence remains blocked".

Evidence: The frozen artifact itself leaves board/president/controller/display trust roots unresolved.

Options: Obtain the producer-owned bindings and evidence, or revise acceptance through owner-approved roadmap amendment.

Recommendation (not a decision): Keep acceptance blocked; implementation cannot manufacture producer authority.

### X-S1

Frozen sentence: CLOSEOUT SL-0/SL-3 and PLACECLI SL-0/SL-3 own pyproject.toml, uv.lock, test_gate_a_wheel_isolation.py and shared docs.

Evidence: The v12/v13 plans do not declare a CLOSEOUT-to-PLACECLI serial edge for shared files.

Options: Order their integration or assign a shared preamble/reducer.

Recommendation (not a decision): Coordinator chooses an integration order; preserve each current main file and append manifest rows. Do not widen this plan-only sweep into execution.

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
| 118 | `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py` | `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py` |
| 118 | `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v2/**` | Proposed; no landed file |
| 118 | `phase-loop-runtime/pyproject.toml` | `phase-loop-runtime/pyproject.toml` |
| 118 | `phase-loop-runtime/uv.lock` | `phase-loop-runtime/uv.lock` |
| 118 | `phase-loop-runtime/MANIFEST.in` | `phase-loop-runtime/MANIFEST.in` |
| 118 | `phase-loop-runtime/tests/conftest.py` | `phase-loop-runtime/tests/conftest.py` |
| 118 | `phase-loop-runtime/tests/test_supervised_contracts*.py` | `phase-loop-runtime/tests/test_supervised_contracts.py`; `phase-loop-runtime/tests/test_supervised_contracts_mutations.py`; `phase-loop-runtime/tests/test_supervised_contracts_receipt.py`; `phase-loop-runtime/tests/test_supervised_contracts_vectors.py` |
| 118 | `phase-loop-runtime/scripts/verify_supervised_contract_publication.py` | `phase-loop-runtime/scripts/verify_supervised_contract_publication.py` |
| 118 | `.github/workflows/supervised-contract-intake.yml` | `.github/workflows/supervised-contract-intake.yml` |
| 118 | `.github/workflows/test.yml` | `.github/workflows/test.yml` |
| 118 | `phase-loop-runtime/scripts/gate_a_cleanroom.sh` | `phase-loop-runtime/scripts/gate_a_cleanroom.sh` |
| 118 | `phase-loop-runtime/scripts/verify_supervised_v2.sh` | Proposed; no landed file |
| 118 | `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` | `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` |
| 118 | `phase-loop-runtime/tests/test_ci_chronology_scope.py` | `phase-loop-runtime/tests/test_ci_chronology_scope.py` |
| 118 | `phase-loop-runtime/tests/test_ci_offload_lock.py` | `phase-loop-runtime/tests/test_ci_offload_lock.py` |
| 118 | `.gitleaks.toml` | `.gitleaks.toml` |
| 150 | `phase-loop-runtime/src/phase_loop_runtime/supervised_envelope_v2.py` | Proposed; no landed file |
| 150 | `phase-loop-runtime/src/phase_loop_runtime/supervised_capture_v2.py` | Proposed; no landed file |
| 150 | `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py` | `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py` |
| 150 | `phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py` | `phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py` |
| 150 | `phase-loop-runtime/tests/test_supervised_envelope_v2.py` | Proposed; no landed file |
| 150 | `phase-loop-runtime/tests/test_supervised_capture_v2.py` | Proposed; no landed file |
| 150 | `phase-loop-runtime/tests/test_supervised_launch*.py` | `phase-loop-runtime/tests/test_supervised_launch.py`; `phase-loop-runtime/tests/test_supervised_launch_binding.py`; `phase-loop-runtime/tests/test_supervised_launch_mutations.py`; `phase-loop-runtime/tests/test_supervised_launch_receipt.py`; `phase-loop-runtime/tests/test_supervised_launch_route.py` |
| 150 | `phase-loop-runtime/tests/fixtures/supervised_launch_local/**` | `phase-loop-runtime/tests/fixtures/supervised_launch_local/envelope.json` |
| 185 | `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py` | `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py` |
| 185 | `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py` | `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py` |
| 185 | `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py` | `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py` |
| 185 | `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py` | `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py` |
| 185 | `phase-loop-runtime/src/phase_loop_runtime/run_status.py` | `phase-loop-runtime/src/phase_loop_runtime/run_status.py` |
| 185 | `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py` | `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py` |
| 185 | `phase-loop-runtime/tests/test_supervised_worker*.py` | `phase-loop-runtime/tests/test_supervised_worker.py`; `phase-loop-runtime/tests/test_supervised_worker_cli.py`; `phase-loop-runtime/tests/test_supervised_worker_receipt.py` |
| 185 | `phase-loop-runtime/tests/test_run_status*.py` | `phase-loop-runtime/tests/test_run_status.py`; `phase-loop-runtime/tests/test_run_status_projection.py`; `phase-loop-runtime/tests/test_run_status_receipt.py` |
| 185 | `phase-loop-runtime/tests/test_convergence_adapters.py` | `phase-loop-runtime/tests/test_convergence_adapters.py` |
| 185 | `phase-loop-runtime/tests/test_executable_dependency_startup.py` | `phase-loop-runtime/tests/test_executable_dependency_startup.py` |
| 218 | `docs/supervised-worker-contracts.md` | `docs/supervised-worker-contracts.md` |
| 218 | `docs/supervised-worker.md` | `docs/supervised-worker.md` |
| 218 | `docs/supervised-run-status.md` | `docs/supervised-run-status.md` |
| 218 | `docs/supervised-worker-readiness.md` | Proposed; no landed file |
| 218 | `plans/evidence/supervised-worker/CLOSEOUT.md` | Proposed; no landed file |
| 218 | `phase-loop-runtime/tests/test_supervised_v2_readiness.py` | Proposed; no landed file |
| 218 | `phase-loop-runtime/scripts/verify_supervised_v2_evidence.py` | Proposed; no landed file |
| 218 | `.github/workflows/supervised-v2-evidence.yml` | Proposed; no landed file |
| 218 | `CHANGELOG.md` | `CHANGELOG.md` |

## Amendment seal

Artifact: `plans/artifacts/v12-CLOSEOUT-inputs.md`

Old sha256: `b6fd84dc91b91236e72f4359ef7f0673c3a851ed2366d7ffdfc99ad10466e330`

New sha256: `54abdc361af601f74e6459bbcf39787ef1bb4b9677ed8b98b275271baf9bed70`

Manifest row: `v12-CLOSEOUT-amend-landed-sweep`; prior rows remain unchanged.

## Exact amended text (old → new)

The following diff is restricted to plan/frozen-input sentences and their seal;
STOP recommendations are not applied as design changes.

```diff
diff --git a/plans/artifacts/v12-CLOSEOUT-inputs.md b/plans/artifacts/v12-CLOSEOUT-inputs.md
index 1333c4ea5..7caaa51db 100644
--- a/plans/artifacts/v12-CLOSEOUT-inputs.md
+++ b/plans/artifacts/v12-CLOSEOUT-inputs.md
@@ -462,3 +462,51 @@ these tested source/wheel routes only; other install routes remain unqualified.
 - V3: `phase-loop-runtime/tests/test_supervised_v2_readiness.py`

 All is the deduplicated union above; the wrapper refuses unknown groups and missing files.
+
+## Landed integration baseline — 2026-11-09 factual amendment
+
+Read `v12-CLOSEOUT-landed-sweep.md` before execution. SCHEMA, JOURNAL revision 5
+and WORKER have landed; this does not discharge their deferred public-v2 work.
+The production CLI's `_production_codec()` still returns None. The local call is
+`run_patch_return(prepared, *, config_bytes: bytes, state_root: Path,
+cancel: threading.Event | None = None) -> WorkerResult` in
+`convergence/adapters/patch_return.py`. It consumes admission itself, reserves
+JOURNAL itself, and reads the local fixture's top-level run/attempt/unit fields;
+those are not public-v2 envelope fields. Its final `before_spawn` callback runs
+inside `run_bounded_capture`. Do not consume its one-use token twice.
+
+The production launcher prefix is
+`seat_uid.trusted_module_argv("phase_loop_runtime.supervised_worker_cli", "launch")`,
+including the installation-root boot. WORKER contract §6's illustrative `python
+-I -m` spelling is not the production helper launch rule (agent-harness#1132,
+agent-harness#1957, agent-harness#1960). Preserve trusted helper identity and
+update all three launch/scratch/reference inventories for any new entry.
+
+JOURNAL's `reserve_attempt(root, identity, *, units, launch_digest,
+caller_context_sha256)` takes every named keyword. `open_journal_root` requires
+`create=`; status/cancel use False. `open_writer(root, reservation, *, limits=...)`
+returns a writer or JournalRefused. `state(state, *, worker_invocations)`,
+`event(phrase, *, refs=())` and `terminal(state, *, worker_invocations, termination,
+refusal, result_binding)` return ChainHead or JournalRefused; terminal's nullable
+arguments are still required. `close()` is idempotent. `read_attempt` may return
+None identity/units/writer. `attempt_status(root, attempt_id, *, observer=...)`
+adds liveness only for verified nonterminal history. `read_page(root, request:
+bytes, *, evidence)` requires assignment_digest, page_size 1..100 and nullable
+cursor; preserve its diagnostics and nullable next_cursor. Evidence resolution
+returns present, retention_dropped or unknown. A readable terminal is not an
+acknowledged append or work acceptance: missing anchor with journal_complete=False
+retains uncertainty (agent-harness#1954). WORKER emits only the closed JOURNAL
+phrases and digest refs; the digest of caller_context is not an echo payload API.
+
+The landed WORKER and JOURNAL receipts compare their source_hashes to live
+files. ENVELOPE does too; its original historical-receipt conversion requirement
+above remains pending. WORKER and JOURNAL exclude the shared seat inventory;
+new receipts must not pin it, CHANGELOG.md or other shared frequently changed
+surfaces. Existing shared documentation pins and the transition of historical
+receipt verification require the sweep's coordinator disposition. Preserve all
+recorded outcomes and receipt bytes while that decision is pending.
+
+The agy v2 record/catalog is a separate qualification system, not a v2 worker
+qualification receipt. Its verifier has no --source-only flag; --release runs
+strict conformance itself and requires a fresh --conformance-report output path.
+No release, route activation or qualification collection is authorized here.
diff --git a/plans/phase-plan-v12-CLOSEOUT.md b/plans/phase-plan-v12-CLOSEOUT.md
index f1886eff8..07f39efaa 100644
--- a/plans/phase-plan-v12-CLOSEOUT.md
+++ b/plans/phase-plan-v12-CLOSEOUT.md
@@ -18,13 +18,11 @@ roadmap amendment makes its v2 intake and version-window scope explicit, preserv
 the DAG/advisory status and SCHEMA v1 history. The supported worker is explicitly
 probe-free; ENVELOPE's future WORKER handoff and roadmap seal are reconciled.

-Work-start gate: SCHEMA implementation agent-harness#1839 must land with the
-reviewed agent-harness#1838 plan and IF-0-SCHEMA-1 receipt; a plan merge alone is
-insufficient. Also require IF-0-WORKER-1 and IF-0-JOURNAL-1. They are upstream
-interfaces, not claims about today's tree. Until then status is blocked,
-blocker_class=upstream_phase_unmet, human_required=false. Reconcile actual landed
-APIs and file ownership before execution; amend this plan if they differ. Do not
-freeze a predicted merge SHA or mutate SCHEMA's receipt to accelerate adoption.
+SCHEMA, IF-0-WORKER-1 and IF-0-JOURNAL-1 have landed. Their receipts establish
+the recorded local scope, not public-v2 or installed-provider qualification.
+The pre-build sweep is `plans/artifacts/v12-CLOSEOUT-landed-sweep.md`; its STOP
+items require coordinator decisions before execution. Preserve SCHEMA history
+and resolve the receipt and JOURNAL echo boundaries without widening lane scope.

 No implementation, tests, provider runs, external review dispatch, upstream edit,
 release or merge is performed by this planning PR. Execution stays sequential.
@@ -37,7 +35,8 @@ The sole new contract revision is the untagged Consiliency/consiliency-contract
 publication pinned by full commit in the artifact below. Per-file SHA-256/blob IDs,
 independent verification, corpus counts and detailed requirements are frozen in
 `plans/artifacts/v12-CLOSEOUT-inputs.md`; the manifest frozen_inputs extension
-seals that artifact. Read it in full before implementation. Publication ACK is
+seals that artifact. Its sha256 is `54abdc361af601f74e6459bbcf39787ef1bb4b9677ed8b98b275271baf9bed70`.
+Read it in full before implementation. Publication ACK is
 not runtime evidence. SCHEMA's original v1 inputs remain separately pinned.

 Vendor the eleven approved v2 resources, retaining all five frozen v1 payloads
@@ -293,14 +292,13 @@ panel/launcher/review_stage and dependency-routing code remain unchanged; their
 routes are not adopted. New modules are auto-discovered; no __init__ export is
 needed. No skill text/bundle is edited. If upstream WORKER/JOURNAL introduces
 additional companions or snapshots, enumerate them by amendment before work.
-The archived SCHEMA artifact/receipt retain their original input hashes. Rebase
-integration must refresh its plan's roadmap_sha256 against the final roadmap
-and validate it before execution; it is absent on this branch. ENVELOPE's plan
-seal and probe handoff are repaired here. CLOSEOUT owns a new path-keyed input
+The archived SCHEMA artifact/receipt retain their original input hashes. SCHEMA's plan is now present; its historical roadmap seal and receipt remain
+inputs, not files to rewrite during CLOSEOUT. ENVELOPE's plan seal and probe
+handoff were repaired by the original CLOSEOUT planning change. CLOSEOUT owns a new path-keyed input
 seal; historical receipt verification uses its recorded module blob.

-Next phase: CLOSEOUT — blocked pending landed SCHEMA and WORKER/JOURNAL gates.
-Next command: none until upstream gates are verified; then
+Next phase: CLOSEOUT — blocked pending the sweep STOP decisions.
+Next command: none until those decisions are recorded; then
 `codex-execute-phase plans/phase-plan-v12-CLOSEOUT.md` under separate execution authority.

 ## Spec Closeout Plan
```

## Validator results on dev0

- validate_plan_doc.py: PASS; one existing (N) release-shaped reducer warning.
- plan_pin_lint.find_plan_pin_violations: PASS, zero findings.
- plan_manifest check --repo .: PASS, canonical=67, registered=67, unregistered=0.
- test_legible_roadmap_contract.py: **1 failed, 63 passed in 39.82s**. The failing node is
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
