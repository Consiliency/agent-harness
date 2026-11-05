# Phase roadmap v12 — Supervised patch-return worker

> # SUPERSEDED — ABSORBED INTO `specs/phase-plans-v11.md` (2026-11-04)
>
> ADVISORY ONLY: the registry accepts only active, delivered and superseded.
> This parser-required banner encodes non-selection, not delivery or actual
> absorption into v11. v11 remains active/selected. Activation needs a separate
> lifecycle decision; this repair makes no runtime or registry-code change.
> agent-harness#1824 will replace this interim banner and denial text with the
> real advisory status when its registry support lands.

## Context

agent-harness#1818 commissions a bounded worker and per-attempt runtime status.
This is a separate initiative from v11. This planning artifact grants no live
execution, route qualification, merge, or release authority. ENVELOPE is the
first detailed phase. Local fixture-based seam authoring may start now; public
contract publication gates authoritative acceptance, not work start.

## Architecture North Star

An injected validator admits a deployment-neutral envelope before any launch-chain
process. The supported worker is probe-free and consumes independently collected
qualification; collection precedes admission and is outside this phase.
A compatible patch-return extension uses
`convergence/adapters/base.py:run_bounded` and `codex.py:run_codex_adapter`.
The worker returns proposal bytes, baseline blob identities, proposal digest,
and attempt identity. The external controller owns patch, post-image, span,
grant and apply checks. The display consumer reads bounded status pages; it
does not create admission, work outcomes or evidence authority.

`ConvergenceResultEnvelope` currently holds only status, attempt_id and detail;
`run_bounded` discards stderr content and parses stdout as a convergence result.
WORKER must extend the shared bounded execution seam compatibly for proposal
capture, stream digests, timing and cancellation. Do not pretend these outputs
exist today or fork another process runner.

## Assumptions

- Consiliency/consiliency-contract publishes public-safe, language-neutral schema bytes
  and positive/negative vectors. Their exact wire keys govern implementation.
- Initial route: **standalone/undeclared**, only with no dependency requirement
  and no authority. Required sessions refuse with `task_unbound` for direct unleased calls,
  or `dependency_route_unwired` for a bound unwired route,
  before probes, credential/output effects or host execution. An envelope
  declaring a dependency cannot downgrade to standalone. A projected route
  requires separately planned integration; none is claimed here.
- Local filesystems and existing provider tooling suffice; no new service,
  database or credential is introduced. Installed-provider qualification is
  pending separate authorization; fixture success is not qualification.

## External Inputs

SCHEMA retains the frozen v1 intake from Consiliency/consiliency-contract
`93db4b4fcc4e3d40c62f6658b6a67b519c750491`, its inventory and false byte-pin
authority receipt (agent-harness#1838, agent-harness#1839). Its original dependency
bound remains scoped to that historical intake.

CLOSEOUT owns adoption of published admitted_launch_envelope.v2 at
`2b91ef85bfdc76239ae52806b3318513951543ab`, including retargeted pins/corpus,
codec and runtime reconciliation, and consiliency-contract>=0.7.0,<0.8.0.
`plans/artifacts/v12-CLOSEOUT-inputs.md` freezes independently verified per-file
SHA-256/blob IDs, corpus accounting and acceptance evidence requirements. This
is a successor intake, not a rewrite of SCHEMA's v1 receipt. It requires SCHEMA
implementation landing, as well as the existing WORKER/JOURNAL dependencies.

Vendor byte-identical public resources with provenance naming the full commit,
git blob ids and per-file sha256 from the owner-accepted expected inventory.
Fresh-fetch canonical protected main and verify git merge-base --is-ancestor;
record observed branch/protection evidence. Hash and parse identical captured
bytes offline; deny unlisted/remote resolution. Published provenance history is
hash-inventoried, not copied. No tag, registry release or upstream change is
assumed. CLOSEOUT vendors the pinned version declarations and enforces their
>=0.7.0,<0.8.0 window and exact byte identity, refusing drift. No pip/uv contract
package install, dependency/lock change or source override is planned; installed
package metadata cannot establish the vendored bundle's version or provenance.
No private path, repository, revision, dependency or source text enters public
artifacts. These are input pins, never pins of future harness outputs.

## Non-Goals

No OpenShell backend registration, live provider runs, autonomous merge, Stop
control, display implementation, private dependency, independent wire schema,
or controller-side patch validation. Native cancel remains in scope. No OS
sandbox claim or operational readiness claim follows from these plans.

## Cross-Cutting Principles

Every launch-determining input (instruction bytes or digest-bound reference,
argv, executable/wrapper identity, workspace source/baseline, tier, constraints
and timeout) must be covered by the envelope seen by the injected validator.
Read/hash/parse once; snapshot referenced instruction/baseline bytes and bind
their digests before admission. Launch uses that immutable admitted object,
never a re-read file, ambient environment, extra CLI flag or `caller_context`.
Trusted operator configuration may narrow inputs and supplies the closed argv
template; its identity and effective choices are included in admission.
No sandbox/approval/config-override argv tails are accepted.

The harness launch digest is SHA-256 over a domain-separated, deterministic,
length-delimited encoding of the raw-envelope SHA-256, canonical LaunchInputs
(including resolved executable/wrapper identities, effective template, timeout,
reference digests and trusted configuration/qualification digests), and attempt_id.
The validator sees both codec envelope digest and harness launch digest;
Admit and token consumption bind the latter. This is a local API digest, not a
new wire field. Trusted codec, qualification, template and configuration inputs
use the validator binding's uid/mode, outside-workspace/target and component-wise
no-follow checks. Same-login writers remain outside this trust guarantee.
Reference reads use dir_fd/O_NOFOLLOW at every component under declared roots,
reject traversal and non-regular files, and enforce per-file and aggregate caps
from trusted configuration before snapshotting; tests cover escape and overflow.

The closed local tier matrix is conservative. “Unsupported” means refuse when
required, never silently downgrade. Provider read-only behavior is not harness
span/command enforcement. Unknown tiers, constraints or cells are unsupported.

| Requested tier | write_scope | command_denial | network_denial | Tier eligibility |
| --- | --- | --- | --- | --- |
| provider_readonly_patch_return_audit | unsupported | unsupported | unsupported | Separate storage plus qualified provider read-only mode, proposal return and audit |
| post_write_audit_only | unsupported | unsupported | unsupported | Auditable workspace; detection only, including worktree/in-place |
| os_enforced | unsupported | unsupported | unsupported | Always refuse; reserved and unqualified |

Provider-tier eligibility requires an operator-owned qualification record
bound to the executable/wrapper digests, version and closed template, with a
demonstrated write-attempt refusal; argv flags alone prove nothing. Missing,
stale or mismatched evidence refuses the requested tier before worker launch.
The supported worker performs no qualification or identity probes before or
after admission. It consumes held evidence collected independently before
capture/admission; collection is outside this phase and cannot alter captured
material. Any future probing route requires a separate plan. Offline fixtures
do not establish installed eligibility.
A separate clone/copy has no shared object/ref storage, alternates, gitfile
pointing outside, hard-linked files/objects, or symlinks into protected storage;
use no-local/no-hardlinks copying and inspect the actual result. A worktree
cannot claim the provider tier. No same-login containment or network denial
is claimed; post-hoc tool-action detection is not prevention.

- Identity is the assignment digest, envelope digest, `run_id`, `attempt_id`,
  `target_unit_ids`, `readonly_neighbor_unit_ids` and snapshot/crosswalk reference.
  Retry requires fresh admission and a new attempt. Equal proposal digests are
  allowed with distinct, correct provenance; history is never relabelled.
- Preserve `caller_context` opaquely; require `redaction_posture`. The journal
  contains references/digests, not prompts, source, raw streams or secrets.
  Evidence belongs to its producer, with retention via `output_retention.py`
  (agent-harness#1783). Runtime completion never means work acceptance.
- Each implementation lane needs offline tests with production-path witnesses
  and mutation controls. A green test must become red when its production
  guard is removed. Capture multiple failures; flag proof cost exceeding about
  five minutes on one node. No commit counts or future-head pins.

Fixture development preserves the public field vocabulary: `schema`, `version`,
envelope/assignment digests, `run_id`, `attempt_id`, `target_unit_ids`,
`readonly_neighbor_unit_ids`, snapshot/crosswalk reference, workspace requirement,
tier/constraints, obligation references, dependency declaration, `caller_context`
and `redaction_posture`. Local fixtures are synthetic, labelled non-authoritative;
do not copy private schemas, vectors or prose. Extra launch-binding concepts
are harness-local immutable API members until the public schema can carry them.
No independent public wire schema is authored.

## Top Interface-Freeze Gates

- IF-0-SCHEMA-1 — Verified commit/sha256-pinned public schema/vector bundle and provenance.
- IF-0-ENVELOPE-1 — Injected admission and tier/route refusal boundary.
- IF-0-JOURNAL-1 — Durable journal, replay projection and bounded read API.
- IF-0-WORKER-1 — Bounded proposal-return lifecycle and evidence binding.
- IF-0-CLOSEOUT-1 — Exact-head checks, independent board and honest readiness record.

## Phases

### Phase 1 — Admitted launch boundary (ENVELOPE)

**Objective**

Bind a validated envelope to an honest, explicit execution tier and route.

**Exit criteria**

- [ ] EC-ENVELOPE-1 — The immutable read-once envelope binds every launch input above; validation precedes every launch-chain process; this worker performs no probes and consumes independently collected pre-admission qualification evidence. Only a typed single-use admit bound to the harness launch digest and attempt id can proceed; invalid, stale, exceptional, replayed, unavailable or non-admit verdicts refuse with zero worker/probe invocations.
- [ ] EC-ENVELOPE-2 — The closed tier matrix, workspace classification, qualification and standalone dependency guards refuse unsupported/unknown constraints, undemonstrable tiers and every `os_enforced` request before launch. Required sessions refuse before envelope reads or credential/output effects. `caller_context`, obligations and full attempt/unit identities survive unchanged in the admitted object.
- [ ] EC-ENVELOPE-3 — Labelled synthetic fixtures and path-entered mutations detect admission, launch-input, tier/workspace, validator-binding and dependency-guard bypasses; later pinned semantic vectors run through these production paths before acceptance.

**Scope notes**

Decompose into 3 lanes: admission/tier boundary with tests; dependent route
composition with tests; dependent documentation/evidence reducer. No provider CLI probes
run on this worker path, before or after admission. Freeze an injected Python callable protocol without importing its
implementation as a repository dependency. CLI binding comes only from operator-owned configuration outside
the target/workspace/envelope, verified by uid/mode and a trusted absolute
module location. No entry-point discovery, environment/cwd imports or allow-all
default. Missing binding refuses. Preserve workspace/repo-relative locator rules.
Resolve executable/wrappers before chdir, using only absolute nonempty PATH
entries or trusted paths; refuse paths under workspace, target or envelope-referenced roots and any
group/world-writable component. Provider eligibility requires qualification
SHA-256 matches; audit-only readiness discloses same-login write access to
user-owned executables. Bind
absolute realpaths/digests to admission; launch uses that same identity.
At token consumption recheck workspace classification/root device and inode,
and executable/wrapper digests; changed values refuse. WORKER repeats these
checks immediately before each chain spawn. Use descriptor execution where
supported; otherwise readiness discloses the residual check-to-exec window.

**Non-goals**

No interpretation of controller grants or obligation semantics.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py`
- `phase-loop-runtime/src/phase_loop_runtime/executable_dependency_startup.py`
- `phase-loop-runtime/tests/test_supervised_launch.py`
- `docs/supervised-worker.md`

**Depends on**

- (none)

**Produces**

- IF-0-ENVELOPE-1 — Injected admission and tier/route refusal boundary.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-worker.md`; evidence paths:
`plans/evidence/supervised-worker/ENVELOPE.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 2 — Attempt journal and projection (JOURNAL)

**Objective**

Provide authoritative attempt history and a replaceable replay projection.

**Exit criteria**

- [ ] EC-JOURNAL-1 — A locked single-writer journal outside the target uses validated single-component caller-supplied run/attempt ids, dir_fd-relative O_NOFOLLOW opens, verified uid/modes (0700 directories, 0600 files, no group/world write), drained/fsynced writes and chained rotation. Full line/writer identity and sequence rules reconcile to the pinned schema and `x-journal-rules` before acceptance.
- [ ] EC-JOURNAL-2 — Torn lines, unknown versions, foreign writers, sequence defects and identity-versus-key/path mismatches fail closed with pinned semantic diagnostics; missing journals/segments and ambiguous/unindexed attempts are unknown. Readers never repair or truncate.
- [ ] EC-JOURNAL-3 — Replay orders latest attempts only by a harness-owned append-only per-assignment admission index, never mtime, wall-clock or lexical order; binds writer identity and each attempt's seq/chain digest. Stale projections and absent/reused owner pid/start-time return pinned unknown/stale diagnostics, never running. Reservation is atomic under the per-assignment lock, appended and fsynced before any probe/launch; duplicate, terminal or crash-reserved attempt ids cannot be reused. The index is durable across processes/restarts, not just a process-local token.
- [ ] EC-JOURNAL-4 — Offline production-path mutations prove pinned page/message/event bounds, omission/retention disclosure, display text from a closed harness phrase set, and separation of runtime references from outcome/evidence joins. Prompt/source/secret sentinels in stdout, stderr and argv never reach journals, projections or pages; caller_context appears only by digest.

**Scope notes**

Decompose into 2 lanes: durable writer/reader plus tests; dependent projection,
paging and liveness plus tests. Reuse `convergence/event_log.py` durability
discipline, **not** its torn-tail truncation/ignore policy. Reuse
`convergence/status.py` replay-only pattern, not its train event types.
Segments `<attempt>/<nnnn>.jsonl` begin with previous-segment sha256 and last
seq; every `header`, `event`, `state`, `terminal` line carries `schema`,
`version`, `line_kind`, `seq`, identity and writer identity (harness id/version,
writer instance id, owner pid/process start time). `observed_at` is informational.
All enum names and numeric bounds are provisional fixture labels until the public
pin; acceptance matches its enums, required fields and `x-journal-rules`. Example
diagnostics include `journal_torn_line` and `attempt_provenance_mismatch`.
JOURNAL owns the admission index and reconciliation against runtime vector cases.
Same-login processes can forge a self-consistent chain: writer binding is not
authentication against them. Record that unsupported trust boundary in readiness.
Journal retention must preserve verifiable chains or explicitly report omitted
history without presenting a truncated chain as complete. No new listener/watch.

**Non-goals**

No display implementation or authority inferred from a cached projection.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/run_status.py`
- `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`
- `phase-loop-runtime/tests/test_run_status*.py`
- `docs/supervised-run-status.md`

**Depends on**

- (none)

**Produces**

- IF-0-JOURNAL-1 — Durable journal, replay projection and bounded read API.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-run-status.md`; evidence paths:
`plans/evidence/supervised-worker/JOURNAL.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 3 — Bounded patch-return worker (WORKER)

**Objective**

Compose admission and journals with the existing bounded adapter lifecycle.

**Exit criteria**

- [ ] EC-WORKER-1 — A compatible shared-seam extension returns bounded proposal bytes and baseline/proposal/attempt identities under the admitted workspace/tier policy, leaves application to the controller and keeps existing convergence callers compatible. The provider tier requires the separate storage defined above.
- [ ] EC-WORKER-2 — Launch uses only the immutable admitted inputs. Evidence binds prompt-free argv, instruction digest, exit, stream digests and timing to the envelope digest; standalone identity includes absolute executable realpath/sha256/version and wrapper-chain realpaths/sha256, excluding proof of a wrapper's entire loaded closure. Evidence also binds the harness launch digest. After consuming admission, WORKER durably reserves the caller-supplied validated attempt_id through JOURNAL before any chain spawn; reservation failure refuses with zero invocations. Until a trusted pinned public codec binding exists, the production CLI refuses codec_unavailable before probes; synthetic codecs are test-injection only. Codec bindings use validator-binding trust checks.
- [ ] EC-WORKER-3 — Native cancel is idempotent and targets only a verified owning launcher (pid plus process start time, supervised-launcher executable/command identity and a matching nonce in a harness-private 0600 file); the launcher holds the unreaped leader and reclaims its own group. Retry requires fresh admission/identity and preserves evidence. Lifecycle enums/termination fields follow the pinned schema; refusal never follows start, and natural process completion is never work acceptance.
- [ ] EC-WORKER-4 — Injected providers prove zero-spawn refusal and evidence binding; real offline subprocess sessions prove descendant/group cleanup, cancel races and failed start. Mutations cover malformed/oversized proposals, planted credentials, prompt secrecy, audit failure, retention, retry and required-session refusal. Tests replay one envelope sequentially and concurrently across processes, including restart after reservation, and assert at most one attempt launches. Test the installed CLI with no codec binding (zero probes), and forged cancel identity targeting an unrelated same-user process (zero signals). A setsid descendant test records the explicit escape limitation; no live-tool qualification is claimed.

**Scope notes**

Decompose into 3 lanes: shared bounded seam and regressions; dependent adapter
and lifecycle integration; dependent CLI/documentation reducer. Use a bounded
execution action, not review mode (review currently has different timeout and
isolation behavior). The unchanged `run_bounded` return cannot carry proposals: it drops stderr and
caps output at 64 KiB. Add a bounded proposal transport outside
`ConvergenceResultEnvelope`, with a larger action-specific cap and stream digests
(including stderr), preserving existing statuses/bounds for existing callers.
Whole-file `{path, content}` is not the proposal contract. Send instructions via
stdin, inherited fd or 0600 file, never argv; evidence stores only their digest.
Workers use base scrubbers, additionally dropping
`SSH_AUTH_SOCK`, `GIT_ASKPASS`, `SSH_ASKPASS` and git credential-helper overrides.
Plant vendor/GH tokens, agent socket and git/gh credential controls in tests.
On-disk git/gh credentials remain reachable by same-login processes: disclose it.

Native placement is `python -I -m phase_loop_runtime.supervised_worker_cli` with
`launch --envelope <path> --result <path>`, `status --run <id>|--attempt <id>`,
and `cancel --run <id>|--attempt <id>`. Use the trusted installed environment:
isolated Python excludes cwd, PYTHONPATH and user-site imports, including
transitive imports. Test shadowed stdlib and validator modules from workspace
cwd. It does not replace `phase-loop status`.
Envelope files require operator uid, regular-file/component-wise O_NOFOLLOW
opens and a configured byte cap; reject group/world write, and group/world read
when inline instructions are present. Test owner/mode, symlink and size refusals.
Explicit dependency classification keys are `supervised-launch`,
`supervised-status` and `supervised-cancel`; launch/cancel are unwired in required
sessions (agent-harness#1782). In-process launch refuses at classification before
reading the envelope. A separate exec loses session context and is standalone;
the envelope dependency declaration remains its only cross-exec guard.
Open --result outside the workspace with O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600,
using verified parent directories. Include terminal seq and chain-head digest
as a controller-held anchor. Freeze exit codes only after public reconciliation.

The launcher never kills a journal-supplied pgid. Without an OS descendant
boundary, a setsid child may escape: `finished` does not prove all descendants
gone or audit stability. The real subprocess test must expose that limitation
and clean up its own escapee. Required descendant containment refuses.
Before/after audit covers workspace plus protected source tree and refs;
unexplained changes or audit errors withhold the proposal and record failure.
Hash directly or use isolated trusted git configuration disabling system/global
config, hooks, fsmonitor, filters, textconv and external diff; never execute
workspace-controlled git configuration.

WORKER owns `output_retention.mark/prune` integration for dedicated evidence
directories: active before writes, sealed only after writers stop. Journal
segments/index live outside prune roots and are never pruned by this helper.
Pruned evidence keeps digest references and explicit `retention_dropped`
disclosure through JOURNAL pages; no incomplete chain appears complete.

**Non-goals**

No OS isolation, OpenShell registration, live run or controller scope checks.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`
- `phase-loop-runtime/tests/test_supervised_worker*.py`
- `phase-loop-runtime/tests/test_convergence_adapters.py`
- `phase-loop-runtime/src/phase_loop_runtime/output_retention.py` (reuse; call sites in worker)
- `phase-loop-runtime/tests/test_output_retention.py`

**Depends on**

- ENVELOPE
- JOURNAL

**Produces**

- IF-0-WORKER-1 — Bounded proposal-return lifecycle and evidence binding.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-worker.md`, `CHANGELOG.md`; evidence paths:
`plans/evidence/supervised-worker/WORKER.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 4 — Published schema intake (SCHEMA)

**Objective**

Establish the public byte-pin gate after seam implementation and before acceptance.

**Exit criteria**

- [ ] EC-SCHEMA-1 — Vendored schemas/resources/vectors match the canonical protected-branch commit and maintainer inventory (blob ids and sha256); absent, altered or unpinned inputs fail closed, with public provenance and no network resolution.
- [ ] EC-SCHEMA-2 — The production loader hashes/parses identical bytes and proves only JSON Schema pass/fail for both families' schema-valid/schema-invalid vectors, with path-entered digest/validation bypass controls. Every semantic-diagnostic vector is inventoried as unresolved `upstream_phase_unmet` for runtime proof, never counted as a schema pass.
- [ ] EC-SCHEMA-3 — A metadata-only receipt binds inputs, schema-only results and unresolved semantic vector ownership; checks launch-input coverage (instruction/reference, argv, executable/dependency identity, workspace source/baseline and timeout), tier-matrix basis, lifecycle, identity, projection and bounds. Inadequate schema coverage blocks the byte-pin gate pending upstream repair, never a local wire extension.

**Scope notes**

Interface-only phase; decompose into 3 lanes: public input intake and loader,
conformance/mutation tests, then dependent documentation reducer. Publication is a
prerequisite for this phase only, not authorization to change the upstream contract.
Freeze `supervised_contracts.py:load_contract_bundle` and `validate_record`;
the latter implements JSON Schema only, not a parallel semantic model. Retain
all semantic vectors for later ENVELOPE/JOURNAL/WORKER runtime reconciliation
in CLOSEOUT. Check (N), if triggered by package-data/changelog ownership in the
later plan, is a packaging heuristic: no release dispatch or reducer is needed.

**Non-goals**

No envelope launch, journal writer, provider process or independent schema.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`
- `phase-loop-runtime/tests/test_supervised_contracts*.py`
- `docs/supervised-worker-contracts.md`

**Depends on**

- WORKER

**Produces**

- IF-0-SCHEMA-1 — Verified commit/sha256-pinned public schema/vector bundle and provenance.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`,
`docs/supervised-worker-contracts.md`; evidence paths:
`plans/evidence/supervised-worker/SCHEMA.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 5 — Review and readiness closeout (CLOSEOUT)

**Objective**

Collect independently reviewable evidence without implying permission to run.

**Exit criteria**

- [ ] EC-CLOSEOUT-1 — All pinned semantic vectors pass through ENVELOPE/JOURNAL/WORKER production paths, consumer differences are reconciled, and no SCHEMA semantic intake item remains unresolved. The assessed content passes the live protected-main required check set, full-path supervised contract publication (contract=true) and dispatched Gate A, with exact observed head/run identities, and a T3 cross-vendor board covering correctness, red-team and adversarial review plus a separate president; unresolved findings block closeout.
- [ ] EC-CLOSEOUT-2 — A metadata-only readiness report distinguishes implemented/offline-tested capabilities, on-main evidence, installed-tool qualification, external conformance and live-use authority; unsupported/unknown items remain explicit with owners and blocked edges.

**Scope notes**

Reconciliation and evidence phase; decompose into 4 sequential lanes: pinned
intake/package preamble, v2 admission/capture, worker/journal reconciliation,
then the dependent review/readiness reducer. Landing is
maintainer-owned. The readiness mapping must distinguish admission, workspace/proposal,
tier, execution evidence, cancellation/tool qualification, journal, reviewed
main, local dependencies and shared-vector conformance. External controller
and display consumer reconciliation cannot be manufactured by harness fixtures.
The regression lane owns public-vector reconciliation in ENVELOPE/JOURNAL/WORKER
tests: all semantic-diagnostic cases must enter their production runtime paths
and match pinned expectations, with path-entered mutations. Bind observed results
to the SCHEMA inventory; unresolved `upstream_phase_unmet` entries block acceptance.
Update consumer code/tests/docs for any fixture-to-public differences by amendment,
including the trusted public codec binding in supervised_launch_binding.py.
The CLOSEOUT plan enumerates that complete touch set before execution.

The published v2 reconciliation supersedes provisional fixture semantics only
when their production obligations pass: RFC 8785 and safe-number intake,
ordinary __proto__ members, whole-envelope secret safety including opaque
caller_context, ancestor-safe tree capture, unique qualification for both tiers,
no interactive terminal, and the >=0.7.0,<0.8.0 version window. Preserve raw,
semantic and local launch digests as distinct commitments; bind public status to
local attempts without adding wire fields. Capture/recheck sources, cwd,
environment, helper transformations and exact per-run grants at the true spawn
boundary. The worker consumes held pre-admission qualification without probes;
one deadline covers the full chain, and helper failures after start are finished/failed_to_start, not refused.
Provider write_scope applies even with empty required_constraints; external
controller apply evidence is required, not fabricated by harness fixtures.
The earlier conservative matrix stays closed until the corresponding supported
v2 path and evidence exist; os_enforced and denial guarantees remain unsupported.

SCHEMA's historical byte_pin_authority and all bundle provenance flags stay false.
CLOSEOUT's evidence assessment is not read by runtime admission. Publisher status
provisional at this pin keeps it false; a separately reviewed non-provisional pin
and authenticated board/external publisher bindings are required for future true.
The hosted verifier then requires exact input/version bytes, full production
corpus/rule/identity/replay/lifecycle/evidence proof, independent reconciliation
and live required checks/reviews. Assessed content excludes only the CLOSEOUT
receipt; stamp ancestry/delta and post-landing content applicability are verified.
Any governing-content change invalidates prior authority. Missing prerequisites
block acceptance. Installed-tool qualification and live authority remain separate.

**Non-goals**

No live qualification, live monitoring acceptance, dispatch of a release or merge.

**Key files**

- `plans/evidence/supervised-worker/CLOSEOUT.md`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_launch*.py`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_envelope_v2.py`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_capture_v2.py`
- `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v2/`
- `phase-loop-runtime/pyproject.toml`
- `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/verify_supervised_v2.sh`
- `phase-loop-runtime/scripts/verify_supervised_v2_evidence.py`
- `.github/workflows/test.yml`, `.github/workflows/supervised-v2-evidence.yml`
- `phase-loop-runtime/tests/conftest.py`
- `phase-loop-runtime/src/phase_loop_runtime/run_status*.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/`
- `phase-loop-runtime/tests/test_supervised_*.py`
- `docs/supervised-worker-contracts.md`, `docs/supervised-worker.md`, `docs/supervised-run-status.md`
- `phase-loop-runtime/tests/test_run_status*.py`
- `phase-loop-runtime/tests/test_supervised_worker*.py`
- `docs/supervised-worker-readiness.md`

**Depends on**

- WORKER
- SCHEMA

**Produces**

- IF-0-CLOSEOUT-1 — Exact-head checks, independent board and honest readiness record.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-worker-readiness.md`, `docs/supervised-worker-contracts.md`,
`docs/supervised-worker.md`, `docs/supervised-run-status.md`; evidence paths:
`plans/evidence/supervised-worker/CLOSEOUT.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

## Phase Dependency DAG

```text
ENVELOPE → WORKER → SCHEMA → CLOSEOUT
JOURNAL → WORKER
WORKER → CLOSEOUT
```

## Execution Notes

ENVELOPE and JOURNAL may be planned and implemented now against synthetic
field-name fixtures, independently with disjoint ownership. WORKER consumes
their local frozen APIs without waiting for public bytes. These are work-start
edges, not authoritative conformance. No private schema/vector is vendored.
ENVELOPE/JOURNAL/WORKER phase completion and their IF gates are local seam
freezes based on the labelled fixtures. References to pinned behavior in their
ECs are final acceptance obligations discharged by CLOSEOUT, not prerequisites
for those local gates. Their receipts must list each deferred pinned obligation.
SCHEMA records the frozen v1 intake; its owner-authorized manual intake can
precede WORKER while the automatic DAG remains unchanged. CLOSEOUT waits for
SCHEMA implementation landing and the seam gates, then runs v2 reconciliation
and blocks acceptance until all pinned vectors
pass. Publication differences require consumer amendments, never local schema
invention. Qualification further needs reviewed main, external conformance
and installed-tool evidence; live use needs fresh admission and owner authority.
Advisory registry status prevents autonomous selection until an owner separately
activates this roadmap; it is not a public-contract blocker on manual authoring.
This task authorizes no delegated execution.
The roadmap may complete its scoped offline delivery while external/live edges
remain blocked and explicitly recorded. No fixture is a live receipt.

## Verification

Future plans must supply lane commands, negative controls and an effective
`automation.suite_command`, validated through IF-0-VC-2. Offline tests use fake
providers and no network. The authoritative whole-feature command and exact
V0–V3 membership are frozen in plans/phase-plan-v12-CLOSEOUT.md and its input
artifact; use its automation.suite_command through the source-pinned wrapper.
Hosted Gate A uses installed-wheel provenance, and evidence authentication uses
the separate network-permitted verifier. No second reduced suite is authoritative.

Use the repository's locked test environment and absolute source/test PYTHONPATH
per CONTRIBUTING.md. These future tests are not run during planning. Require the
live protected-main required check set plus full-path `supervised contract publication`,
Gate A and authenticated evidence verification. Maintainer dispatch:
`gh workflow run test.yml --ref <reviewed-branch> -f chronology=false`; verify
the run actually tested the observed reviewed head, including Gate A. Any
subsequent change invalidates that evidence. T3 board and president review the
same content/head. Runner-stamped evidence/amendments record external check
and review identities under `plans/evidence/supervised-worker/`; no prose proxy
can satisfy a gate without an explicit roadmap amendment. None is dispatched here.
