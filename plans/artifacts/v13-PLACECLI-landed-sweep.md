# v13 PLACECLI: landed-input sweep — 2026-11-09

Inspected input: `a493c46cc` on `origin/main` (WORKER merge). All line citations
in the sweep table and inventories refer to that immutable input, before this
amendment. No output commit identity is prescribed. This is a static design
reconciliation, not runtime qualification or approval to build.

MATCH means a consumed boundary is compatible or explicitly prospective;
MISMATCH includes an omitted integration boundary. A MISMATCH marked STOP is
**not corrected** by guessing a design. Prospective output schemas and ownership
claims are inventoried separately below; their presence is not counted as a
passing implementation. The main table has **17 MATCH / 5 MISMATCH** rows.

AGENTS.md ratio diagnosis: the plans froze downstream integration before the
upstream implementations stabilized. LANEEXEC has already had multiple input/
activation amendments without its implementation. This sweep is one consolidated
factual amendment per phase. STOP items require a single coordinated disposition,
not repeated speculative plan edits. Review remains pending; no build or merge.

## Sweep table

| Plan/artifact line at input | Result | Consumed boundary | Landed code/evidence file:line | Disposition |
| --- | --- | --- | --- | --- |
| plans/phase-plan-v13-PLACECLI.md:28 | MISMATCH | Upstream landing state / scope | phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py:19 | FACT corrected: gates landed locally; codec remains unavailable. No public-v2 or activation proof. |
| plans/phase-plan-v13-PLACECLI.md:29 | MATCH | JOURNAL landed rev-5 identity, replay and bounded projection | phase-loop-runtime/src/phase_loop_runtime/run_status.py:118 | Available; exact consumed API and nullability inventory below. |
| plans/phase-plan-v13-PLACECLI.md:121 | MATCH | New service API reserve/release/reap all require cancelled keyword | phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:445 | Planned wrapper; not a landed JOURNAL method. New signatures remain as frozen. |
| plans/phase-plan-v13-PLACECLI.md:7 | MATCH | Separate new console script and delegated legacy reap | phase-loop-runtime/src/phase_loop_runtime/cli.py:1099 | Existing maintenance path remains reducer-owned; process entry remains future. |
| plans/artifacts/v13-PLACECLI-contract-v1.schema.json:100 | MISMATCH | egress grant uses bare 64 hex, reservation uses sha256: prefix | plans/artifacts/v13-LANEEXEC-contract-v1.schema.json:509 | FACT corrected; fetched upstream v2 $defs.sha256 confirms bare hex. P-S2 coordinated repin required. |
| plans/phase-plan-v13-PLACECLI.md:63 | MISMATCH | Full landed cap record/controllers exceed the described minimum | phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:52 | P-S1; whole record required including cpu_max_percent, pids_max and io_max. |
| plans/phase-plan-v13-PLACECLI.md:179 | MATCH | Readiness is fail-closed | phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:365 | None or seat_resource_caps_unavailable; map explicitly to capability_unmet. No workload starts during reserve. |
| plans/phase-plan-v13-PLACECLI.md:63 | MISMATCH | Readiness is not per-attempt path and lifetime proof | phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:247 | P-S1; current two automatic paths differ from LANEEXEC four paths. |
| plans/phase-plan-v13-PLACECLI.md:180 | MATCH | Policy resolution does not activate routes | phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py:4440 | Retain false driver and no live coordinator registration. |
| plans/phase-plan-v13-PLACECLI.md:124 | MATCH | New bridge API keyword-only cancelled; close returns flags | phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:48 | Future bridge wrapper; retain remote pi-runner/leg only and bridge null otherwise. |
| plans/phase-plan-v13-PLACECLI.md:168 | MATCH | Editable source pins explicitly runtime_equality false | phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:264 | All four local input hashes match baseline; BAML and policies remain equality inputs. |
| plans/phase-plan-v13-PLACECLI.md:162 | MATCH | Launch inventory must union with landed entries | phase-loop-runtime/tests/data/seat_launch_references.json:13 | Preserve WORKER rows; update scratch, trusted-helper and reference tests for new sites. |
| plans/phase-plan-v13-PLACECLI.md:162 | MATCH | JOURNAL/WORKER receipts exclude shared seat inventory | phase-loop-runtime/tests/test_supervised_worker_receipt.py:60 | agent-harness#1955; no new receipt may pin shared mutable inventory or CHANGELOG. |
| plans/phase-plan-v13-PLACECLI.md:162 | MISMATCH | Existing receipts still pin shared docs; WORKER pins shared adapter sources/tests | plans/evidence/supervised-worker/WORKER.md:1526 | Flag for coordinated historical verification; do not pin shared frequently changed files in new evidence. |
| plans/phase-plan-v13-PLACECLI.md:162 | MATCH | Jailed Codex remains SEATS-owned; no profile adoption by placement alone | phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py:13354 | Landed 0.7.31 seat route is not v2 WORKER route qualification. |
| plans/phase-plan-v13-PLACECLI.md:74 | MATCH | agy v2 catalog and release CLI are independent qualification inputs | phase-loop-runtime/scripts/verify_qualified_agy_image.py:320 | No consumed --source-only invocation exists in these plans. --release runs strict conformance, requires fresh report; no release here. |
| plans/phase-plan-v13-PLACECLI.md:232 | MATCH | Docs-accuracy landings preserved as integration baseline | docs/supervised-worker.md:8 | Do not restore pre-audit claims; public-v2/installed/live authority stays separate. |
| plans/phase-plan-v13-PLACECLI.md:232 | MATCH | Deferred issues remain separately owned | plans/artifacts/v12-WORKER-contract.md:196 | agent-harness#1954 and agent-harness#1960 do not authorize additional implementation in this sweep. |
| plans/artifacts/v13-PLACECLI-contract-v1.schema.json:48 | MATCH | Input pin placement_contract_baml | phase-loop-runtime/src/phase_loop_runtime/baml_src/placement_contract.baml:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-PLACECLI-contract-v1.schema.json:52 | MATCH | Input pin sandbox_placement | phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-PLACECLI-contract-v1.schema.json:57 | MATCH | Input pin policy_vectors | phase-loop-runtime/src/phase_loop_runtime/contracts/placement/vectors/policies.json:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |
| plans/artifacts/v13-PLACECLI-contract-v1.schema.json:61 | MATCH | Input pin placement_driver_defaults | phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml:1 | Existing bytes match the frozen input; runtime_equality=False remains a planning baseline, not a future-output pin. |

## STOP decisions (not applied)

### P-S1

Frozen sentence: Artifact x-placement-semantics.local_cgroup_execution: "memory.max, cpu.weight and either io.weight or an io.max bandwidth cap".

Evidence: Landed seat_resource_caps.v1 requires the whole record, including CPU quota, pids and both IO settings; readiness_code checks availability but io_devices discovers only seat staging/scratch.

Options: Use the complete landed caps record/readiness plus workload-specific path validation, or define a separate placement caps adapter.

Recommendation (not a decision): Reuse the full record and explicitly define reservation-time readiness versus launch-time per-path readback. Coordinator must approve that integration contract.

### P-S2

Frozen sentence: "Any changed external bytes require reviewed repinning before execution."

Evidence: Correcting the egress grant spelling changes the PLACECLI schema digest, which is pinned by the v13 roadmap, LANEEXEC artifact/plan, SEATS REMOTE and external toolkit consumers.

Options: Land a coordinated repin set including consumer acknowledgments, or hold this factual amendment until the coordinator assigns that set.

Recommendation (not a decision): Hold execution and coordinate repins; these independent draft branches do not silently rewrite another phase or assume future commits.

### X-S1

Frozen sentence: PLACECLI and CLOSEOUT share packaging, wheel-test and documentation surfaces.

Evidence: No explicit cross-roadmap serial integration edge is declared.

Options: Choose serial integration or a shared owner.

Recommendation (not a decision): Choose serial integration before build; no ownership reassignment is made here.

## Complete consumed local signatures and record fields

These are the landed shapes, including keyword-only separators, required nullable
fields and defaults. Availability is not a v2 adapter or a wire-status mapping.
JOURNAL/WORKER integration remains subject to the STOPs above.

| Code file:line | Signature or fields |
| --- | --- |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:44` | `IoMax: rbps: int; wbps: int; riops: int; wiops: int` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:52` | `SeatResourceCaps: schema: Literal['seat_resource_caps.v1']; memory_max_bytes: int; cpu_weight: int; cpu_max_percent: int; io_weight: int; io_max: IoMax; io_paths: tuple[str, ...]; pids_max: int` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:221` | `def load_caps() -> SeatResourceCaps:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:242` | `def caps_sha256(caps: SeatResourceCaps) -> str:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:350` | `def io_devices(caps: SeatResourceCaps) -> tuple[str, ...]:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:365` | `def readiness_code() -> str \| None:` |
| `phase-loop-runtime/src/phase_loop_runtime/seat_resource_caps.py:559` | `def capped_popen(command, *, seat_key: str, **popen_kwargs) -> 'subprocess.Popen[bytes]':` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:205` | `PlacementUnavailable: ` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:228` | `PlacementCancelled: ` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:251` | `EgressNeeds: allow: tuple[tuple[str, int], ...] = (); @classmethod` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:264` | `PlacementRequest: leg: str; round_id: str; repo: str; snapshot_sha256: str; deadline_s: float \| None; egress_needs: EgressNeeds; one_shot_secret: bool = True; workload: str = 'leg'; required_capabilities: frozenset[str] = frozenset(); root: 'sandbox_policy.SandboxRootChoice \| None' = None; owner_id: str = ''; lease_id: str = ''` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:295` | `BackendReceipt: step: str; sandbox_ref: str; snapshot_sha256: str` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:309` | `PlacementReceipt: step: str; sandbox_ref: str; snapshot_sha256: str; attested_by: str; _seal: object = field(default=None, repr=False, compare=False); workload: str = 'leg'; @classmethod; def to_dict(self) -> dict[str, str]:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:355` | `Declaration: egress_residuals: tuple[tuple[str, bool], ...] = (); guest_control_env: tuple[str, ...] = (); max_lifetime_s: float \| None = None` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:372` | `Prepared: review_dir: Path; local_tree: Path; snapshot_sha256: str; sandbox_ref: str; receipt: PlacementReceipt` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:383` | `PlacedSandbox: backend: str; sandbox_ref: str; staged_at: str; receipts: tuple[PlacementReceipt, ...]; verified: Mapping[str, str]` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:393` | `OperationBound: timeout_s: float; cancelled: threading.Event` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:403` | `ExecSpec: workload: str; request: bytes = field(repr=False); deadline_s: float \| None; must_end_within_s: float \| None; output_cap_bytes: int` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:428` | `ExecResult: sandbox_ref: str; exit_status: int; result: bytes = field(repr=False); truncated: bool` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:436` | `ExecProgress: sandbox_ref: str; seq: int` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:445` | `PlacementBackend: name: str; def capabilities(self) -> frozenset[str]:; def declaration(self) -> Declaration:; def available(self, request: PlacementRequest) -> bool:; def commit(self, prepared: Prepared, request: PlacementRequest, bound: OperationBound \| None=None) -> 'BackendReceipt \| PlacedSandbox \| None':; def release(self, prepared: Prepared, bound: OperationBound \| None=None) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:468` | `ExecutingBackend: def endpoint(self, root: 'sandbox_policy.SandboxRootChoice') -> tuple[str, int] \| None:; def admit(self, request: PlacementRequest, bound: OperationBound) -> None:; def execute(self, sandbox_ref: str, spec: ExecSpec, bound: OperationBound) -> BackendReceipt:; def wait(self, sandbox_ref: str, wait_s: float) -> 'ExecResult \| ExecProgress':; def cancel(self, sandbox_ref: str, bound: OperationBound) -> None:; def renew(self, sandbox_ref: str, until_s: float, bound: OperationBound) -> None:; def list_owned(self, owner_id: str, bound: OperationBound) -> Sequence[tuple[str, str]]:; def kill(self, lease_id: str, bound: OperationBound) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:505` | `def verified_from_backend(backend: PlacementBackend, claimed: Mapping[str, str]) -> dict[str, str]:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:524` | `LocalBackend: def capabilities(self) -> frozenset[str]:; def declaration(self) -> Declaration:; def available(self, request: PlacementRequest) -> bool:; def commit(self, prepared: Prepared, request: PlacementRequest, bound: OperationBound \| None=None) -> None:; def release(self, prepared: Prepared, bound: OperationBound \| None=None) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:558` | `def is_local(backend: object) -> bool:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:563` | `def register_backend(scheme: str, backend: PlacementBackend, codes: Mapping[str, str] \| None=None) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:620` | `def backend_for_scheme(scheme: str) -> PlacementBackend \| None:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:635` | `def resolve_backend(choice: 'sandbox_policy.SandboxRootChoice') -> PlacementBackend:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:646` | `def prepare_local_stage(repo: Path, review_dir: Path, *, floor_bytes: int, mark: Path) -> Prepared:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:682` | `def applied_rule(*, backend: object, host: str \| None, path: Path \| str, staged_at: Path \| str, receipts: Sequence[PlacementReceipt], authorization_sha256: str \| None, local_spawns: int) -> tuple[bool, str \| None]:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:731` | `LegPlacement: def record_backend_receipt(self, receipt: BackendReceipt \| None) -> None:; def record_runtime(self, step: str) -> PlacementReceipt:; def receipts_for(self, local_spawns: int) -> list[PlacementReceipt]:; def staged_at(self) -> str:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1002` | `def lifetime_sufficient(remaining_s: float, floor_s: float, *, settings: sandbox_policy.PlacementDriverSettings \| None=None) -> bool:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1015` | `def lifetime_at_floor(remaining_s: float, floor_s: float) -> bool:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1021` | `PlacementDecision: outcome: str; trail: tuple[Mapping[str, object], ...]; code: str \| None = None; placement: 'LegPlacement \| None' = None; tooled_route_required: bool = False; notices: tuple[str, ...] = (); local_reservation: LocalReservation \| None = field(default=None, repr=False); pending_local_reservation: LocalReservationPending \| None = field(default=None, repr=False)` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1220` | `LocalHeadroom: memory_available_bytes: int \| None; load_per_cpu_percent: float \| None; live_sandboxes: int \| None; observed_monotonic: float; def admits(self, settings: sandbox_policy.PlacementDriverSettings) -> bool:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1250` | `LocalReservation: token: str = field(repr=False)` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1260` | `LocalReservationPending: def inspect(self) -> tuple[str, LocalReservation \| None]:; def wait(self, timeout_s: float) -> tuple[str, LocalReservation \| None]:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1294` | `LocalAdmission: handle: LocalReservation \| None; reading: LocalHeadroom \| None` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:1940` | `def place(rungs: Sequence['sandbox_policy.SandboxRootChoice'], last_rung: str, prepared: Prepared, request_for: Callable[['sandbox_policy.SandboxRootChoice'], PlacementRequest], open_lease: Callable[[str \| None, 'sandbox_policy.SandboxRootChoice'], object], *, preflight: Callable[[], str \| None], seal: Callable[[PlacementRequest], 'ExecSpec \| None'], driver_enabled: bool, cancelled: threading.Event, settings: sandbox_policy.PlacementDriverSettings \| None=None, local_capacity: Callable[[], LocalHeadroom \| None] \| None=None, local_admit: Callable[[sandbox_policy.PlacementDriverSettings, OperationBound], LocalAdmission] \| None=None, local_release: Callable[[LocalReservation], None] \| None=None) -> PlacementDecision:` |
| `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py:2026` | `def run_placed(placement: 'LegPlacement', *, on_progress: Callable[[ExecProgress], None] \| None, cancelled: threading.Event) -> ExecResult:` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:106` | `def owner_id() -> str:` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:212` | `def openshell_journal_kind(entry, lease_id):` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:241` | `JournalEntryRefusal: ` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:255` | `ReaperContextRefusal: ` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:263` | `LiveLeaseBackend: @abstractmethod` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:275` | `JournalReapingBackend: @abstractmethod; @abstractmethod` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:287` | `Lease: @property; @property; def attach_transport(self, adapter: object) -> tuple[bool, str \| None]:; def mark_dispatch(self, adapter: object, operation: str) -> None:; def record_coordinator(self, adapter: object, **fields: object) -> None:; def record_transport_ref(self, adapter: object, sandbox_ref: str) -> None:; def fence(self) -> None:; def validate_live_binding(self, adapter: object) -> None:; def confirm_commit_ref(self, adapter: object, sandbox_ref: str) -> None:; def record_sandbox_ref(self, sandbox_ref: str) -> None:; def note_killed(self) -> None:; def abandon(self) -> None:; def clear(self) -> None:; def heartbeat(self, renew: Callable[[], object], interval_s: float) -> Callable[[], None]:` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:504` | `def open_lease(backend_name: str \| None, root: object) -> Lease:` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:554` | `def recover_lease(lease_id: str) -> Lease:` |
| `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py:576` | `def reap(backends: Callable[[str], object], bound: 'sandbox_placement.OperationBound', *, on_refusal=None) -> dict[str, tuple[str, ...]]:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py:36` | `StageBinding: workspace: str; owner_id: str; lease_id: str; generation: str; source_sha256: str` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py:44` | `StageAdapter: def validate_configuration(self) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py:56` | `WorkerAdapter: image_sha256: str; def validate_configuration(self) -> None:; def create_request(self):; def exec_request(self, wire: bytes, end_s: float):; def validate_native(self, identity: Identity, envelope: bytes, bound: Bound) -> None:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py:90` | `OpenShellBackend: def capabilities(self):; def declaration(self):; def available(self, request):; def endpoint(self, root):; def bind_live_lease(self, lease):; def admit(self, request, bound):; def commit(self, prepared, request, bound=None):; def seal(self, request):; def execute(self, sandbox_ref, spec, bound):; def wait(self, sandbox_ref, wait_s):; def kill(self, lease_id, bound):; def cancel(self, sandbox_ref, bound):; def list_owned(self, owner_id, bound):; def release(self, prepared, bound=None):; def renew(self, sandbox_ref, until_s, bound):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py:29` | `MTLSConfig: endpoint: str; owner_cn: str; local_owner_id: str; ca_pem: bytes = field(repr=False); client_cert_pem: bytes = field(repr=False); client_key_pem: bytes = field(repr=False); receive_limit_bytes: int; connect_timeout_s: float; def target(self):; def validate(self, local_owner_id):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:17` | `ForkJournalRefusal: ` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:22` | `def refuse_fork_entries():` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:42` | `def outstanding(values):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:49` | `JournalSession: ` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:221` | `JournalStream: def cancel(self):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:249` | `ReaperAdapter: def validate_reaper_context(self):; def kill_journaled(self, owner_id, lease_id, entry, bound):; def list_owned(self, owner_id, bound):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py:325` | `OpenShellCleanupBackend: def kill(self, lease_id, bound):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:24` | `TransportError: ` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:33` | `UnsupportedCapability: ` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:39` | `StreamResult: exit_code: int; stdout: bytes = field(repr=False); stderr: bytes = field(repr=False)` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:62` | `def validate_wire(kind, value):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:79` | `CallerAllowance: def remaining(self):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:125` | `CoordinatorError: ` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:131` | `CoordinatorClient: def validate_create(self, body, binding):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:455` | `def exec_request_id(lease, attempt):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:462` | `StockExecChannel: def bind_lease(self, lease, sandbox_id, *, local_owner_id):; def invalidate_lease(self, lease):; def close(self):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py:507` | `StockExecSession: def invalidate(self):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:39` | `WorkerRequest: identity: Identity; task: str; tests: tuple[str, ...]; must_end_within_s: float; token: bytes = field(repr=False); expires_at: float` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:71` | `def seal_request(bundle: SourceBundle, *, nonce: str, generation: str, image_sha256: str, task: str, tests: tuple[str, ...], must_end_within_s: float, login_store: bytes, request_cap: int) -> tuple[Identity, bytes]:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:97` | `def read_request(wire: bytes, bundle: SourceBundle, request_cap: int) -> WorkerRequest:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:127` | `Launch: argv: tuple[str, ...]; cwd: Path; env: dict[str, str]; stdin: bytes = field(repr=False); pass_fds: tuple[int, ...]` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:136` | `ProviderResult: exit_status: int; stdout: bytes = field(repr=False); stderr: bytes = field(repr=False); quiescent: bool` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:143` | `IsolatedRuntime: provider_program: tuple[str, ...]; def provider(self, launch: Launch, bound: Bound, cap: int) -> ProviderResult:; def test(self, work: Path, home: Path, tests: tuple[str, ...], bound: Bound, cap: int) -> bool:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:160` | `def run_worker(wire: bytes, bundle: SourceBundle, *, expected_identity: Identity, request_cap: int, runtime: IsolatedRuntime \| None, scratch_parent: Path, cancelled) -> bytes:` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:343` | `def review_policy():` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:349` | `def stock_policy_digest(policy):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:398` | `def landlock_manifest(rules, uid=10001, gid=10001):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:437` | `def load_document(bundle, run_id):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:447` | `def validate_load(value, bundle, run_id):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:452` | `def preflight_worker(bundle, create, *, task, tests, deadline_s, request_cap, generation, dependency_required=False, exec_request=None):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:485` | `def guest_rules(mapping):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:497` | `def verify_helper_metadata():` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:516` | `def load_restrict_exec(wire, bundle, *, request_cap, bound, execute=None, restricted_argv=None, reclaims=()):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:571` | `def worker_evidence(bundle, nonce, *, exec_claimed, reclaims=()):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:582` | `def bundle_from_envelope(wire, cap):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:604` | `def helper_failure_code(stderr):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:619` | `def unwrap_worker_result(wire, bundle, identity):` |
| `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py:642` | `def main():` |

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
| 162 | `phase-loop-runtime/src/phase_loop_runtime/placement_process_contract.py` | Proposed; no landed file |
| 162 | `phase-loop-runtime/src/phase_loop_runtime/contracts/placement/process-v1.schema.json` | Proposed; no landed file |
| 162 | `phase-loop-runtime/tests/test_placement_process_contract.py` | Proposed; no landed file |
| 162 | `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` | `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` | `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` | `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` | `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py` | `phase-loop-runtime/src/phase_loop_runtime/openshell_backend.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py` | `phase-loop-runtime/src/phase_loop_runtime/openshell_channel.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py` | `phase-loop-runtime/src/phase_loop_runtime/openshell_journal.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py` | `phase-loop-runtime/src/phase_loop_runtime/openshell_transport.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py` | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py` |
| 174 | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml` | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/placement-driver.defaults.toml` |
| 174 | `phase-loop-runtime/tests/test_placement_lifecycle_process.py` | Proposed; no landed file |
| 174 | `phase-loop-runtime/tests/test_sandbox_placement.py` | `phase-loop-runtime/tests/test_sandbox_placement.py` |
| 174 | `phase-loop-runtime/tests/test_sandbox_policy.py` | `phase-loop-runtime/tests/test_sandbox_policy.py` |
| 174 | `phase-loop-runtime/tests/test_placement_driver.py` | `phase-loop-runtime/tests/test_placement_driver.py` |
| 174 | `phase-loop-runtime/tests/test_placement_ladder_model.py` | `phase-loop-runtime/tests/test_placement_ladder_model.py` |
| 174 | `phase-loop-runtime/tests/test_placement_lease.py` | `phase-loop-runtime/tests/test_placement_lease.py` |
| 174 | `phase-loop-runtime/tests/test_openshell_backend.py` | `phase-loop-runtime/tests/test_openshell_backend.py` |
| 174 | `phase-loop-runtime/tests/test_openshell_channel.py` | `phase-loop-runtime/tests/test_openshell_channel.py` |
| 174 | `phase-loop-runtime/tests/test_openshell_journal.py` | `phase-loop-runtime/tests/test_openshell_journal.py` |
| 174 | `phase-loop-runtime/tests/test_openshell_transport.py` | `phase-loop-runtime/tests/test_openshell_transport.py` |
| 174 | `phase-loop-runtime/tests/test_advisor_board_config.py` | `phase-loop-runtime/tests/test_advisor_board_config.py` |
| 186 | `phase-loop-runtime/src/phase_loop_runtime/placement_bridge.py` | Proposed; no landed file |
| 186 | `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py` | `phase-loop-runtime/src/phase_loop_runtime/openshell_worker.py` |
| 186 | `phase-loop-runtime/tests/test_placement_bridge.py` | Proposed; no landed file |
| 186 | `phase-loop-runtime/tests/test_openshell_worker.py` | `phase-loop-runtime/tests/test_openshell_worker.py` |
| 186 | `phase-loop-runtime/tests/_openshell_channel_server.py` | `phase-loop-runtime/tests/_openshell_channel_server.py` |
| 186 | `phase-loop-runtime/tests/fixtures/placement-cli/**` | Proposed; no landed file |
| 198 | `phase-loop-runtime/pyproject.toml` | `phase-loop-runtime/pyproject.toml` |
| 198 | `phase-loop-runtime/uv.lock` | `phase-loop-runtime/uv.lock` |
| 198 | `phase-loop-runtime/src/phase_loop_runtime/placement_cli.py` | Proposed; no landed file |
| 198 | `phase-loop-runtime/src/phase_loop_runtime/cli.py` | `phase-loop-runtime/src/phase_loop_runtime/cli.py` |
| 198 | `phase-loop-runtime/tests/test_placement_cli.py` | Proposed; no landed file |
| 198 | `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py` | `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py` |
| 198 | `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py` | `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py` |
| 198 | `phase-loop-runtime/tests/test_seat_reference_inventory.py` | `phase-loop-runtime/tests/test_seat_reference_inventory.py` |
| 198 | `phase-loop-runtime/tests/data/seat_launch_references.json` | `phase-loop-runtime/tests/data/seat_launch_references.json` |
| 198 | `phase-loop-runtime/README.md` | `phase-loop-runtime/README.md` |
| 198 | `docs/placement-process-cli.md` | Proposed; no landed file |
| 198 | `plans/evidence/placement/PLACECLI.md` | Proposed; no landed file |
| 198 | `CHANGELOG.md` | `CHANGELOG.md` |
| 198 | `.doc-decisions.json` | `.doc-decisions.json` |
| 198 | `plans/manifest.json` | `plans/manifest.json` |

## Complete prospective schema inventory

Every definition below is reproduced from the inspected frozen input, including
all fields, required lists, refs, nullability, enums and conditional rules. These
are new process protocols, **not** the existing worker CLI JSON. Package loaders
and services do not exist at the inspected input. No absent future API is called
a landed match. The manual table identifies the consumed-code disagreements;
these inventories preserve the rest of the reviewed wire contract unchanged.

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

Artifact: `plans/artifacts/v13-PLACECLI-contract-v1.schema.json`

Old sha256: `130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea`

New sha256: `dbd74a1c33130b3ac1690508828eb3fff5939ad0bdcd517c0be21defebcf7708`

Manifest row: `v13-PLACECLI-amend-landed-sweep`; prior rows remain unchanged.

## Exact amended text (old → new)

The following diff is restricted to plan/frozen-input sentences and their seal;
STOP recommendations are not applied as design changes.

```diff
diff --git a/plans/artifacts/v13-PLACECLI-contract-v1.schema.json b/plans/artifacts/v13-PLACECLI-contract-v1.schema.json
index 8ad3869c4..395a2d0d4 100644
--- a/plans/artifacts/v13-PLACECLI-contract-v1.schema.json
+++ b/plans/artifacts/v13-PLACECLI-contract-v1.schema.json
@@ -97,7 +97,7 @@
     "registry": "The selected per-client operator configuration chooses an operator-owned provider allowlist, either directly or by reference to a reviewed artifact under contracts/placement/vectors/. config_sha256 binds the chosen name-to-endpoint mapping. An unknown name, a name not permitted for the selected client or workload, or a name not permitted by the resolved target policy_vector refuses before any capacity probe, coordinator call or lease effect with outcome refused and code sandbox_placement_provider_refused.",
     "effective_egress": "For every target, the effective egress set is exactly the resolved policy_vector baseline union the allowlisted endpoint set for each declared provider, with duplicates removed, and contains nothing else. The same provider resolution and effective set apply to local sandboxes. The request never carries a hostname, URL, endpoint or inline egress rule.",
     "digest": "Reservation.providers records the declared names. Reservation.egress_sha256 is sha256: plus the lowercase hex SHA-256 of the UTF-8 RFC 8785 serialization of the effective egress grant after provider names and endpoint/rule records are sorted lexicographically and duplicates are removed. No credential or credential-derived value enters the grant or digest.",
-    "launch_binding": "LANEEXEC must set admitted_launch_envelope.v2 launch.grants.egress_policy_sha256 to {canonical_form: rfc8785, sha256: Reservation.egress_sha256} and refuse launch_input_unbound if the reservation providers, resolved grant and digest do not agree. This binds the effective set into the launch envelope without adding provider or model fields to that external contract.",
+    "launch_binding": "LANEEXEC must set admitted_launch_envelope.v2 launch.grants.egress_policy_sha256 to {canonical_form: rfc8785, sha256: the 64 hex digits of Reservation.egress_sha256 after the sha256: prefix} and refuse launch_input_unbound if the reservation providers, resolved grant and digest do not agree. This binds the effective set into the launch envelope without adding provider or model fields to that external contract.",
     "credentials": "The placement service holds no model-provider key, token or refresh token, and none enters a sandbox. Model connection bytes go to the requester's credential proxy over the admitted client link; a remote link uses the reservation bridge, while a local launcher uses the same requester-owned proxy boundary in process and keeps Reservation.bridge null. The sandbox holds placeholders only. The Pi reference is Consiliency/agent-toolkit commit 9304a5b92c8c409473ca3d2182557b8592697476, harnesses/pi/sandbox/cred-proxy.mjs and docs/remote-placement.md. Other multi-vendor harnesses, including OpenCode, provide the same requester-owned boundary.",
     "target_clearance": "An owned-host target such as ai needs the generic egress-and-credential probe receipt for the resolved set. A third-party target such as E2B additionally needs a current OD-7 clearance for every declared provider; one missing clearance refuses that target with sandbox_placement_provider_refused. E2B remains disabled until its separate activation gates pass."
   },
diff --git a/plans/phase-plan-v13-PLACECLI.md b/plans/phase-plan-v13-PLACECLI.md
index 45e52f01e..70d0f0aa6 100644
--- a/plans/phase-plan-v13-PLACECLI.md
+++ b/plans/phase-plan-v13-PLACECLI.md
@@ -16,7 +16,7 @@ implements the process boundary that agent-toolkit can consume without importing
 agent-harness Python. The frozen input is
 `plans/artifacts/v13-PLACECLI-contract-v1.schema.json` with erratum
 PLACECLI-v1-errata-1 (its `x-errata` member), sha256
-`130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea`.
+`dbd74a1c33130b3ac1690508828eb3fff5939ad0bdcd517c0be21defebcf7708`.
 The artifact fixes the stable console entry, required client/config flag,
 version response, exact message shapes, code vocabularies, target-bound policy
 and provider names, reservation egress digest, two isolated identities/inventories,
@@ -25,12 +25,11 @@ lifecycle semantics. It is read-only during
 execution; a needed contract change routes back through a roadmap/artifact
 amendment.

-Implementation has a non-human work-start gate: v12 IF-0-WORKER-1 and
-IF-0-JOURNAL-1 must be implemented and landed, and their final APIs must be
-reconciled with this plan. Until then PLACECLI is planned but blocked with
-`blocker_class=upstream_phase_unmet`, `human_required=false`. This is not a live
-activation gate and does not prevent black-box fixture preparation in a later
-authorized execution; the phase still lands as one coherent disabled feature.
+v12 IF-0-WORKER-1 and IF-0-JOURNAL-1 have landed with local receipts.
+`plans/artifacts/v13-PLACECLI-landed-sweep.md` records the consumed boundaries
+and the remaining STOP decisions; landing alone does not authorize public-v2
+launch or live activation. Execution waits for those decisions; the phase
+still lands as one coherent disabled feature.

 The process boundary is `agent-harness-placement --client
 agent-toolkit|agent-harness reserve|release|reap|version`. The flag is required,
@@ -242,8 +241,8 @@ source changes in this phase. If landed v12
 worker adds a shared CLI registry or companion snapshots, reconcile and amend the
 complete ownership list before execution.

-This phase is PLACECLI. Execution is blocked pending landed v12 IF-0-WORKER-1 and
-IF-0-JOURNAL-1. Next command: none until those upstream gates are verified; then
+This phase is PLACECLI. Execution is blocked pending the sweep STOP decisions.
+Next command: none until those decisions are recorded; then
 `codex-execute-phase plans/phase-plan-v13-PLACECLI.md` under separate execution
 authority. The following roadmap phase is LANEEXEC; this PR does not plan it.

```

## Validator results on dev0

- validate_plan_doc.py: PASS; one existing (N) release-shaped reducer warning.
- plan_pin_lint.find_plan_pin_violations: PASS, zero findings.
- plan_manifest check --repo .: PASS, canonical=67, registered=67, unregistered=0.
- test_legible_roadmap_contract.py: **1 failed, 63 passed in 38.51s**. The failing node is
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
