# CLOSEOUT v2 frozen inputs and reconciliation requirements

Planning observation for agent-harness#1818, 2026-11-05 UTC; not a runtime receipt.
Public source: https://github.com/Consiliency/consiliency-contract.git, immutable
commit `2b91ef85bfdc76239ae52806b3318513951543ab`; no tag is assumed.

## Independent input verification

Fresh-fetched canonical main into a scratch clone. GitHub branch metadata showed
main protected=true at the pinned revision; git merge-base --is-ancestor from
the revision to origin/main exited 0. Protection is an observation, not a signature
or an assertion about specific branch rules. Recheck during implementation.
Computed each SHA-256 directly from git show REV:path bytes and each Git blob ID
with git rev-parse REV:path. Exact file-set comparison and all twelve digest rows
match the owner-supplied root-verified inventory; no expected hash was generated
from a payload and then treated as its independent trust anchor.
Inventory document SHA-256:
`5503773ba3d74381fea852c0029a9fd6b136c9317ba5c64bd28b8633516bb21f`.
Its private location and historical preamble are intentionally not reproduced.
The explicit manifest row below governs, not the preamble's earlier review hash.

Ten SHA256SUMS payload rows match. Its first five lines equal the complete old
manifest bytes (SHA-256 `b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285`).
All five frozen v1 payloads match Git objects at
`93db4b4fcc4e3d40c62f6658b6a67b519c750491` byte-for-byte. The complete manifest and
provenance changed; never reuse their old whole-file hashes for v2.

Paths below are relative to the public repository. First twelve rows are the
published supervised-run inventory. Final three are independently hashed
version/package input evidence at the same commit, outside that inventory.

| Path | SHA-256 | Git blob ID |
| --- | --- | --- |
| `core/supervised-run/admitted-launch-envelope.schema.json` | `0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d` | `1abe40abbb1178295af86b3c6d64f9bffe5a0099` |
| `core/supervised-run/admitted-launch-envelope.v2.schema.json` | `6d6b2f89c55d160c2c132c29b3aa330a0a91c40ab017707040478a60b469194f` | `79d3d0f4bd3af1417e06e0f2255fa3f4e7749770` |
| `core/supervised-run/conformance/README.md` | `2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca` | `9051f4fcfa7bb91b896f3efe60b6a3b238545a75` |
| `core/supervised-run/conformance/README.v2.md` | `c6ab5d9da4707adf5dad9602b483b201a2dfe89f638ecba84129e0c477d72637` | `3409e2b7f9a8582af3796a82e1c15b7cb2c17fdb` |
| `core/supervised-run/conformance/SHA256SUMS` | `48904c259e4a1c24d3e841f56b6c2a84ce2cff32014cf573b3e41b34fac1f1fc` | `9bbcd0b8bc6449377b94debfe0568bfe6d685e07` |
| `core/supervised-run/conformance/envelope.v2.apply.vectors.json` | `57e0fd4d2e88c75bb8dfbab94448431ca3c752f6444febf1bd492323b044c078` | `24a46480c3d7384e929233e9713d923bc6e0809f` |
| `core/supervised-run/conformance/envelope.v2.canonical.vectors.json` | `f7f11c7667d12b0c876102781fdd5773074f5301f152a6d18be509894bc0e8f8` | `8111d2e6f75f6bdb68c48d2963f3c4649596cbe8` |
| `core/supervised-run/conformance/envelope.v2.vectors.json` | `e742d2774d410c2508405eaffed84575b992483da68c07f28591097d6ec5bc2f` | `2028d84f0b5be0d0c4dd6e8ec06ab377d2dd3c0b` |
| `core/supervised-run/conformance/envelope.vectors.json` | `876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f` | `4fcb908f0ed89f2206efc2fbf4c5a6c7bdbd7e56` |
| `core/supervised-run/conformance/run-status.vectors.json` | `5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730` | `4a156e4fbf56526d483f729c78b2e94eb6f48f93` |
| `core/supervised-run/provenance.json` | `f4b306fd7608c123d751225d02591e94654255fc688b5f84b777d2e896cf46f7` | `46bbff61b179b294ce2c481ccfc58a62c666e9b5` |
| `core/supervised-run/run-status.schema.json` | `5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30` | `8af75b390c1b6dcb5478ac16daec3bd38cb060d1` |
| `core/schemas/version-skew-protocol.schema.json` | `d77624c1975e896309c88a57b6e3690b3b24ab438873d0fb6873dd4924dd1c8f` | `b6f23cd9107b85f8db20804e0f9cc0d48613f930` |
| `pyproject.toml` | `0aee475b360d5c17673000c53fefd742ed88e4d6d4194bf9d77155e568ab5153` | `b0ae3eae3ed89c9629a203efe71bdfb895042e36` |
| `package.json` | `bd85b4e580d430983368749852a0e6e82e783e4464e7a0ed24996c4306e1e81c` | `04fc4ecc713ad2841c88a38e0409ff50ea602b51` |

Vendor the eleven supervised-run resources other than provenance.json into
schemas/supervised-worker-v2/, retaining relative names and byte identity.
Inventory provenance.json by hash/blob only: its history text is outside the
runtime closure and is not copied. Name new local metadata harness-provenance.json.
Retain the separate original supervised-worker-v1 closure and SCHEMA receipt.
Neither schema loader may resolve unlisted or remote references. Also vendor the
three pinned version/package declaration files under version/ with their original
repository-relative paths, adding .pinned to pyproject.toml and package.json so
dependency-manifest detection by basename ignores them. They are inert metadata,
not an installable package.
The publisher provenance status is provisional; record that observed status,
its verified source digest and pointer without copying its history text.

## Corpus accounting

Preserve the complete public corpus, not the superseded draft's case count.
Admission v2: 255 cases (21 controls, 172 semantic negatives, 62 schema negatives).
Canonicalization: 30 number primitives, 26 domain rows, 28 documents, 4 alternates,
25 tree captures and 6 tree alternates. Apply: 13 applications and 7 journals.
Frozen v1: 16 envelope and 35 status cases. Counts are inventory observations;
case IDs, exact expected diagnostics/effects and schema pointers govern coverage.

Schema-only intake remains separate from production semantic proof. Inventory
all normative annotations, every x-semantic-rules entry, recursive x-journal-rules
entry and the ten named obligations in the SCHEMA artifact, including rules
with no vector. Carry forward identity-public-replay, evidence-producer-binding,
proposal-attempt-independence and lifecycle-process-result explicitly. Correct
SCHEMA's stale identity-journal-correlation premise: v2 requires caller_context;
it is opaque echo, never correlation or authority input. Preserve the old receipt
as history and record the correction in the new reconciliation ledger.

Expand RFC 6902 patches with RFC 6901 pointers and assert each edit took effect.
Honor rehash using public JCS, the first-reporting-stage diagnostic set, exact
schema-error instance_path/keyword sets (including type masking and anyOf), and
expected_effect subsets. Prototype-named members survive expansion. Runtime
cases must enter production consumer paths; a test-side semantic evaluator or
schema green result cannot discharge them. Producer reference tests are useful
input explanations, not harness or installed-route evidence.

## Seven adopted contract decisions

1. **Safe numbers:** validate raw tokens before lossy conversion and in-memory
   values before commitment. Every integer-valued number, including decimal and
   exponent spellings and caller_context, must be within ±9007199254740991.
   Reject nonfinite values, invalid UTF-8, duplicate decoded keys and lone
   surrogates. Preserve supported fractional binary64 values. Implement RFC 8785
   UTF-16 member ordering, ECMAScript number spelling and negative-zero handling.
   Serializer primitives outside the profile do not authorize their admission.
2. **Own members:** preserve __proto__ as ordinary data in parse, patch, JCS,
   environment and opaque echo paths; never omit it or consult inherited data.
3. **Whole-envelope secret safety:** inspect decoded names, nested values and
   arrays, including caller_context. Never redact, rewrite or drop echo to pass.
   Apply the complete pinned x-environment-commitment.no_secret_values_anywhere
   rule, including instructions, references, source-tree contents, environment
   policy and non-secret values, qualification evidence, templates and grants. Known-secret/hash
   controls are regressions, not proof against arbitrary derivation; trusted
   classification must establish suitability or refuse. Bind authorized source
   and presence, not value identity; same-source secret rotation leaves the
   envelope unchanged. A route requiring secret-value binding is unsupported.
4. **Capture ancestry:** forbid a file/symlink ancestor at every proper prefix,
   independently of ordering and implicit directories; never traverse symlinks.
   Exclude root .git before descent, retain nested .git, hash raw link-target
   bytes, classify executability by any POSIX 0o111 bit, sort by UTF-8 path bytes,
   and refuse duplicates, invalid paths, absent modes or special objects. The
   existing selected-path review_stage digest is not the v2 tree commitment.
5. **Qualification:** both defined tiers need exactly one independently held
   matching record for tier/action/transport/ordered chain/template/qualification
   digests. Missing, null, duplicate or multiple matches refuse route_not_qualified
   before grant checks. No first-match or record union. Every applied grant's
   canonical_form and digest and each credential source need exact coverage;
   placeholder profile evidence cannot qualify a concrete expansion. Keep local
   ownership, host/profile and executable checks. os_enforced stays reserved.
6. **No interactive delivery:** PTY, prompt responses, paste framing and input
   after output refuse before any chain process. Supported stdin is the bound
   bytes once at start followed by EOF, or empty DEVNULL. A grant cannot override
   this exclusion. Existing panel PTY paths remain outside this worker.
7. **Version window:** v2 intake vendors only from the exact commit above and
   enforces >=0.7.0,<0.8.0 by reading verified version/pyproject.toml.pinned's
   project.version, version/package.json.pinned's version and the pinned version-skew
   schema's contract_version and compatible_ranges.contract/package constants
   (published spelling `>=0.7.0 <0.8.0`). Require agreement at 0.7.0,
   supported release syntax and the frozen range before exposing a bundle.
   Missing, malformed, unequal, out-of-window or digest-drifted declarations
   refuse manifest_invalid (digest mismatches remain digest_mismatch).
   Never infer the bundle version from installed distribution metadata.
   No new pip/uv install of the contract package, dependency upgrade, direct URL,
   source override, lock change or registry/tag release is planned. The existing
   consiliency-contract>=0.6.5,<0.7 dependency stays as it is for registry readers.
   It is a separate input: this window never applies to it, and v2 code never reads
   its bytes or metadata.
   Source and wheel tests read the same verified vendored bytes. Later source
   revisions, even with the same declared version, require a separately reviewed
   input amendment; compatibility is not byte provenance.

## Capture and launch boundary

Use a dedicated public-v2 codec adapter, not mutation of the frozen synthetic
exact-key fixture into a purported public record. Public semantic envelope JCS
SHA-256, raw byte SHA-256, domain-separated local launch digest and one-use
run/attempt identity remain distinct. Keep local run/attempt IDs outside the
public envelope and join them through the controller-held admission and public
status bindings, never caller_context. Preserve typed Admit and token consumption.

Capture the final outermost argv after rewriting, ordered executable/wrapper
identities, exact instruction/reference closure and lengths, source tree,
target map, effective worker cwd/environment, trusted policy and effective
per-run grants. Snapshot once and compare those same objects immediately at
launch, extending consume_admission beyond its present inode/executable checks.
Bind helper argv consumption, env transforms and cwd changes in the trusted
template. Outer spawn env/cwd contains only declared transformation inputs.
The declared discovery set is captured and enforced; undeclared discovery remains
an installed-route qualification obligation under the tier's stated limits,
not an offline same-login containment claim.

Sources map to workspace, declared_root or descriptor; keep physical paths and
FDs local. External references are captured/rechecked in place, never copied
into the source tree to fit the wire. Descriptor sources require a qualified
bound descriptor grant. An independent cwd maps through a granted view_root;
it does not redefine the source-tree commitment. Discovered cwd configuration
joins the reference closure. Unsupported mappings refuse without route fallback.

Environment commitment is JCS of exactly {non_secret, secret_names}; sort the
names by UTF-16. Trusted policy classifies every effective worker variable and
credential source; unknown variables refuse. Treat a credential-bearing proxy
URL as wholly secret and bind its non-secret destination separately. Capture
and enforce the actual environment, including scrub/scratch policy, not a hash
of a different redacted map. Grants select raw_bytes or rfc8785 explicitly;
retain ordered policy rules and independently held per-run coverage.

The supported v12 worker starts no qualification/identity probes, before or after
admission. It consumes independently collected qualification evidence; collection
is separate, pre-admission work outside this phase and cannot alter its captured
material. The process.probes rows in the 21 controls describe that earlier collection:
the corpus adapter passes them to the contract check, and production never starts them.
Refusals cause zero auxiliary, chain and worker starts. A future route
that requires probes needs a separate plan consistent with the public ordering.
One monotonic deadline starts at the first launch-chain process and never restarts
at a helper. Bind seconds, deadline_action and config-based heartbeat/quiet
behavior; review not_armed semantics must match or the route refuses. Helper
failure after chain start is running → finished/failed_to_start, never refused.

## Apply, identity and evidence boundaries

Provider-tier write_scope is checked_before_apply even with empty constraints.
The external controller owns protected application: scope/target/baseline and
proposal digest checks, prohibited entry handling, all-or-nothing application
and audit. Harness exports bound proposals and verifies returned evidence, not
an independent controller implementation. Exercise all 13 application outcomes
through a production controller integration and independently supplied evidence;
a harness mock cannot certify that external edge. Missing evidence blocks
CLOSEOUT; do not invent a passing controller or weaken the required set.
Rejected proposals are work outcomes with valid running → finished termination
and result bindings. None of the defined tiers provides write_prevention,
command_denial or network_denial; grant qualification cannot relax the matrix.
Provider tier retains separate-copy storage. No automatic downgrade is allowed.

Preserve durable reservation before chain spawn, sequential/concurrent/restart
replay refusal, unique per-attempt evidence with equal proposal digests, envelope
and baseline identity, source-owned evidence resolution and status crosswalks.
Exercise torn tails, copied/foreign evidence, lifecycle combinations, projection
bounds, retention omission and cancellation/descendant limits through actual
JOURNAL/WORKER paths. Schema validity alone proves none of these obligations.

## Authority transition and evidence ledger

SCHEMA's receipt remains historical and false. Both versions' harness-provenance
metadata always retain byte_pin_authority=false. CLOSEOUT's receipt is a scoped
evidence assessment, never a runtime authorization input: no launch path reads
its boolean. Production still requires independent authority, suitability and
qualification for every attempt. The published provisional status keeps the v2
assessment false at this pin. A non-provisional successor needs a separately
reviewed input amendment, not a status rewrite. External evidence source and
board publisher bindings below are also unresolved acceptance prerequisites.
Thus true is unreachable in this revision; offline implementation may proceed
after the existing upstream gates. Acceptance does not require true: EC-CLOSEOUT-1
and EC-CLOSEOUT-2 can close with a validated false assessment, but stay blocked until
those bindings and their evidence exist.

SL-3 owns verify_supervised_v2_evidence.py, run by the network-permitted
supervised-v2-evidence workflow on hosted CI. Its metadata-only assessment,
including every negative verdict, is independently reproducible. It resolves
run/job/check IDs, repository, workflow identity, head, conclusion and downloaded
artifact SHA-256 through the authenticated GitHub API, not receipt assertions.
Read the live required check set from protected-main rules/branch protection;
unavailable requirements or evidence fail closed. Require that entire set plus
supervised contract publication, Gate A, and the separate evidence verifier.
Publication must have run its full comparison, with contract=true in the
API-resolved result artifact for the assessed content; no-op success is insufficient.

Board reports are private inputs; use metadata-only board-verdicts.json and
president-verdict.json in a hosted board-evidence artifact, identifying seats,
providers, verdicts, reviewed head/content identity and report digests. A T3 landing
board also records vendors, author independence and any president stand-in. These
artifacts and this repository are public: a security or containment failure keeps its
code and detail in the private record and owner summary (OD-10), and its public row
shows only a neutral unavailable outcome and the replacing seat. A plan
amendment must name the authorized publisher, repository/workflow or detached
signature trust root and immutable artifact identity before these are trusted.
For external controller apply (all 13 cases) and display reconciliation, the
owning controller/display maintainers must supply similarly authenticated
producer evidence from a producer-owned repository/workflow or signature root
outside the harness implementer's write authority. Those identities are not yet
established here. Missing identities/evidence are unresolved upstream_phase_unmet;
SL-2 outputs external_evidence_intake, never manufactures the external results.
V3 checks offline structure/negative cases; it cannot itself authorize true.

Content identity is SHA-256 of RFC 8785 over sorted [path, git-mode, blob-OID]
rows from git ls-tree -r of the assessed tree, excluding exactly
plans/evidence/supervised-worker/CLOSEOUT.md. No code, workflow, plan, input seal,
readiness documentation or other path is excluded. The hosted verifier requires
the tested head to be an ancestor of a proposed evidence-stamp commit and their
entire delta to be confined to that one path, with equal content identities.
It checks all required CI/Gate A/board/president evidence against the tested
content. The verification job's artifact carries its own run identity from the
runner/API; it does not require a self-referential artifact digest. A later
read-only assessment resolves and hashes that artifact. Path-entered controls
prove that a governing-content change invalidates the assessment.

A receipt names tested head, content identity, governing file digests and the
stamp head as observed externally; it never embeds a predicted own commit ID.
After landing, an on-main verifier checks content identity and the recorded
pre-merge ancestry/delta proof. Squash landing is accepted only with identical
non-evidence content and API-confirmed PR/merge correspondence; it is not a
claim that the tested head is an ancestor of a squash commit. Any subsequent
non-evidence change makes the old assessment inapplicable, reports effective
false and requires fresh evidence. Consumers must validate applicability, never
read a historical true boolean as current. No fixed trailing-commit count.

Each row records source pointer, case/control ID, production symbol, outcome,
owner, resource digest and authenticated artifact/run/job/head identity. Include
all schema rules, SCHEMA named obligations, replay, lifecycle/process result,
proposal/baseline/attempt evidence independence and consumer reconciliation.
Missing/skipped-only or unresolved outcomes block acceptance. No raw prompts,
credentials, streams, private source paths or copied producer history are stored.
Installed qualification, live use, route expansion, release and merge remain
separate authority; no immediate owner decision is requested by this repair.

## Frozen local interfaces

These signatures and closed results supplement the phase plan; none are wire fields.
JSONValue means a recursively immutable JSON tree; ParsedV2 carries that tree and
its exact raw bytes, and V2Envelope additionally carries schema validation and
raw/public-JCS digests. Secret-free types have no ambient lookup or lazy re-read.

| Owner | Signature | Result / failure |
| --- | --- | --- |
| SL-0 supervised_contracts | load_contract_bundle(*, version: str = "v1") -> ContractBundle | Only v1/v2; otherwise ContractError(selector_invalid). v1 default/closure unchanged. |
| SL-0 supervised_contracts | validate_record(bundle: ContractBundle, family: str, record: bytes, *, definition: str | None = None) -> None | Existing closed ContractError codes/selectors; add v2 family only with v2 bundle. No semantics. |
| SL-1 supervised_envelope_v2 | parse_v2(raw: bytes) -> ParsedV2; canonicalize_v2(value: JSONValue) -> bytes | Both enforce the v2 domain; invalid input raises ContractError(record_json_invalid), with no payload in error/chain. |
| SL-1 supervised_envelope_v2 | decode_v2(raw: bytes, *, bundle: ContractBundle) -> V2Envelope | Calls parse_v2 and validate_record; only public v2; existing ContractError codes. |
| SL-1 supervised_launch_binding | load_v2_context(binding: Path, *, workspace: Path, target: Path, reference_roots: tuple[Path, ...]) -> ValidatorContext | Refused | Trusted snapshot or code-only refusal; never derives authority from envelope/caller arguments. |
| SL-1 supervised_launch_binding | load_v2_binding(path: Path, *, workspace: Path, target: Path, reference_roots: tuple[Path, ...]) -> V2Binding | Refused | Reads trusted operator configuration, including TrustedLaunchSpec, and calls load_v2_context. Code-only refusal; envelope content never selects it. |
| SL-1 supervised_capture_v2 | capture_launch_v2(*, spec: TrustedLaunchSpec, context: ValidatorContext, attempt: AttemptBinding) -> CapturedLaunch | Refused | Captures declared material once; failures map to launch_input_unbound or the pinned first-stage diagnostic. |
| SL-1 supervised_envelope_v2 | validate_v2_admission(envelope: V2Envelope, *, context: ValidatorContext, capture: CapturedLaunch, attempt: AttemptBinding) -> V2Decision | Immutable admitted flag and ordered diagnostic tuple; exact first reporting stage of pinned x-evaluation-order, no token/spawn. |
| SL-1 supervised_launch | prepare_launch_v2(raw: bytes, *, binding: V2Binding, capture: CapturedLaunch, attempt: AttemptBinding) -> PreparedLaunch | Refused | Executes public validation then trusted Validator(view); requires typed Admit(local_digest, attempt_id), issues one-use token only on both successes. |
| SL-1 supervised_capture_v2 | recheck_launch_v2(capture: CapturedLaunch, *, context: ValidatorContext) -> None | Refused | Compares every commitment with held material, returns no replacement inputs; failure permanently invalidates capture. |
| SL-1 supervised_launch | consume_admission(prepared: PreparedLaunch) -> LaunchInputs | Refused | Existing signature; v2 rechecks and spends once, returns only admitted secret-free input view with an opaque spawn capability. |

V2Decision diagnostics are the finite pinned schema/semantic diagnostic set;
local binding failures use binding_unavailable, binding_invalid, codec_unavailable,
launch_input_unbound, route_not_qualified or grant_unqualified. Existing token,
typed-Admit and dependency preflight refusals remain code-only with their current
reasons. Preserve the complete diagnostic tuple in local result metadata, while
Refused.reason uses its first code; map local codes into schema-valid status
refusal records with a tested closed mapping, never free-text substitution.

AttemptBinding is immutable (assignment_digest, run_id, attempt_id) from the
controller's trusted admission request. It is separate from public envelope and
opaque echo, checked against ValidatorContext and durably reserved by JOURNAL.
TrustedLaunchSpec is an operator-produced immutable final route specification
containing the declared local roots, exact chain/argv, delivery, cwd, target map,
classified environment, grants and policy bindings described above. The CLI
obtains it from V2Binding's trusted configuration, never envelope-selected code.

CapturedLaunch owns bounded byte snapshots, held read descriptors and immutable
secret-free commitments for one attempt. It lives until one consume/spawn or
refusal/cancel, then closes descriptors and revokes its capability; it cannot be
serialized, copied to another attempt or reused. Secret values stay in a separate
non-dataclass opaque delivery object accessible only by the final spawn owner;
it has no value-bearing repr, asdict, validator-view or evidence exposure. Neither
public nor local launch digest includes secret values or their derived hashes.
Both bind authorized source/presence and non-secret inputs. A same-source rotation
leaves both digests unchanged. Explicit controls cover every normative secret
location and absence from repr, errors, validator views and evidence.

## Trusted context, qualification and production entry

ValidatorContext is a frozen operator/controller-held document with
expected_assignment_digest, expected_snapshot_ref, expected_crosswalk_ref,
timeout_max_seconds, qualified_routes, policy_epoch, revoked_record_ids and
caller_context_suitability. Use component-wise no-follow regular-file reads,
operator uid, private mode, byte caps, and exclusion of workspace, protected target
and reference roots for this document and every referenced record. Read/hash/parse
one snapshot. Envelope bytes, caller_context and launch CLI flags cannot supply
or override it. Missing/malformed context refuses; real trusted-file tests cover
foreign assignment and stale snapshot with pinned diagnostics.

qualified_routes is a list, not a keyed map: preserve duplicates. Each record
contains record_id, issuer_id, policy_epoch, valid_from, expires_at, evidence
references/digests, the complete public route key, exact grant form/digest map,
credential_sources and the observed version of each chain entry. The worker runs no
probes, so EC-WORKER-2's version identity comes from this held record. The independent trusted policy fixes accepted issuer
identity, current epoch, time basis and revoked IDs. Require all records readable,
well-formed, current, unrevoked and evidence-bound; any invalid record refuses the
whole store, never skips a row. Then require exactly one matching route. Evidence
must resolve to an approved qualification collector's authenticated record, not
local assertion booleans. Provider proof includes demonstrated read-only refusal,
proposal attribution, apply and audit limits; audit-tier proof includes actual
before/after audit, error handling, result attribution and its detection-only
limits. Missing installed evidence remains unqualified. Collection is not in scope.

caller_context_suitability defaults to empty-object-only in trusted policy.
Nonempty payloads require an independent per-attempt attestation binding exact
JCS payload digest, assignment, attempt, trusted issuer and current policy epoch;
absence/mismatch refuses launch_input_unbound. Generic secret checks still apply
and echo stays opaque. The corpus test adapter explicitly provides positive
attestations for controls; the same cases without that input refuse through the
production binding. This never treats a successful scanner as suitability proof.

Production CLI always selects the installed v2 binding from trusted operator
configuration; envelope contents cannot choose a legacy decoder. V2Binding holds
that context, public codec bundle and validator, with module absolute paths,
verified wheel/module digests and current approved input seal outside the three
excluded roots. Isolated imports must match that approved implementation set.
Fixture-shaped records, public v1 and non-public codecs refuse at production entry.
Legacy prepare_launch/decoder injection remains available only to offline tests.

Every control has separate contract-level verdict and supported-route verdict
with reason in the ledger. v2 provider write_scope opens only with authenticated
apply/qualification evidence, including empty required_constraints; without it
the provider route refuses. Audit-tier write_scope stays unsupported. Dependency,
workspace-contained executable and interactive routes stay closed; affected
controls are not counted as end-to-end launch passes. Unresolved runtime proof
continues to block CLOSEOUT, not pressure a route expansion. SL-2 owns all six
kind=echo cases through the real JOURNAL writer, with exact JCS bytes including
S3-jcs-proto-echo-dropped and S2-jcs-echo-number-changed.

## Corpus parsing and SCHEMA compatibility

Resource hashes seal original bytes before parsing. Parse allowlisted *.vectors.json
as corpus containers with duplicate-key/nonfinite rejection but lossless number
tokens and escaped scalar strings, retaining raw token slices so deliberately
invalid fixture values survive extraction. This private extractor has no public
record API path and cannot emit an admissible ParsedV2. No normalization/replacement
of invalid fixtures is allowed. Schemas, provenance and production record intake
remain strict. Feed extracted raw cases to production parse_v2 and extracted
values to its in-memory boundary; both must independently reject invalid domains.
Share the v2 binary64/domain logic with validate_record for the v2 family, checking
raw and rounded integer range, including fractional tie/exponent forms. v1 intake
keeps its documented original behavior. Generalize ECMA-262 pattern semantics for
every pattern in the verified schema; final-LF controls cover digest, ID and commit
patterns, with production-entry controls. Never edit producer pattern bytes.

SL-0 updates historical receipt checks to verify SCHEMA module hashes against the
recorded historical Git blob, not the current changed module. Its receipt bytes
remain untouched. SL-1 and SL-3 edit files listed in the ENVELOPE receipt's
source_hashes, so SL-1 makes test_supervised_launch_receipt.py pin that receipt's
whole-file SHA-256, read from the base ref before SL-1's first edit, and stop
comparing its rows with live files. Its source_tree_digest, outcome and mutation
checks stay, and no lane changes the ENVELOPE receipt's bytes. Replace the blanket import ban with an exact production allowlist
(supervised_envelope_v2, supervised_capture_v2, supervised_launch_binding), retaining
all other exclusions; callers pass validated bundles rather than import elsewhere.
Update the signature assertion for the explicit v1-default keyword; retain false
harness-provenance enforcement for both versions. CLOSEOUT frozen_inputs uses the
same path-keyed {path: {sha256}} shape as SCHEMA; readers reject other shapes.

## Hosted verification surfaces

SL-0 extends gate_a_cleanroom.sh's sparse allowlist with the CLOSEOUT artifact,
receipt, plan, manifest, verification scripts and coupled assertions. Missing
mandatory inputs fail, never skip. The GateAConformEvidenceScopeTest class in
test_gate_a_wheel_isolation.py asserts the closure and installed-wheel imports. Source suites and Gate A both verify the
vendored version declarations and exact resource bytes in their own interpreter;
no contract-package install or environment workaround is introduced.

The publication detector explicitly includes both vendor roots, the version/
metadata, supervised_contracts.py, supervised_envelope_v2.py,
supervised_capture_v2.py, test_supervised_contracts.py (v2 anchor assertions),
this artifact, .gitleaks.toml, package-data/MANIFEST configuration, uv.lock
(as a drift surface, not a new v2 pin), test.yml, Gate A, and both verification
scripts/workflows. Compare the v12-CLOSEOUT frozen_inputs mapping separately from
v12-SCHEMA. A gitleaks exception requires an exact inert fixture path and exact
rule; no broader allowance. Base-ref policy requires a reviewed plan-only input
amendment to land before implementation can use changed source pins/seals.
A diff changing the CLOSEOUT artifact or seal together with vendor bytes, pins,
anchors or loader fails. SL-0's first vendoring may add vendor bytes and anchor
literals only when they equal the artifact and seal already on the trusted base ref;
any later anchor change follows the same rule. Compare old identities from the trusted base ref;
protected-main ancestry alone cannot authorize a new input revision. The current
repair changes plans only. Receipt authority requires the authenticated full-path
publication artifact, not detector success alone.

SL-0 owns verify_supervised_v2.sh, the explicit runner wrapper for V0–V3/all.
It resolves the repo root from its own location, cd's there, requires the checkout's
locked phase-loop-runtime/.venv/bin/python, sets absolute source/test PYTHONPATH,
and asserts module provenance before exec of timeout 900 (1800 for all) ... -m pytest -q
-p no:cacheprovider with the phase plan's enumerated group. The locked environment has
no pytest-xdist and uv.lock stays unchanged, so the wrapper passes no -n flag and runs
serially. test.yml has no such environment today; SL-0 adds a step that installs uv and
runs uv sync --project phase-loop-runtime --group test --extra visual --locked before
calling the wrapper. The wrapper itself does no installs or dynamic whole-repo
discovery. Isolated child tests explicitly insert and assert that
same source root. Gate A uses its clean-room installed interpreter and asserts
wheel provenance instead; it never imports production from the sparse source.
Record interpreter/module paths and byte proof with outcomes. Readiness names
these tested source/wheel routes only; other install routes remain unqualified.

### Verification group membership

- V0: `phase-loop-runtime/tests/test_supervised_contracts.py`, `phase-loop-runtime/tests/test_supervised_contracts_vectors.py`, `phase-loop-runtime/tests/test_supervised_contracts_mutations.py`, `phase-loop-runtime/tests/test_supervised_contracts_receipt.py`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest`, `phase-loop-runtime/tests/test_ci_chronology_scope.py`, `phase-loop-runtime/tests/test_ci_offload_lock.py`
- V1: `phase-loop-runtime/tests/test_supervised_envelope_v2.py`, `phase-loop-runtime/tests/test_supervised_capture_v2.py`, `phase-loop-runtime/tests/test_supervised_launch.py`, `phase-loop-runtime/tests/test_supervised_launch_binding.py`, `phase-loop-runtime/tests/test_supervised_launch_route.py`, `phase-loop-runtime/tests/test_supervised_launch_mutations.py`, `phase-loop-runtime/tests/test_supervised_launch_receipt.py`
- V2: `phase-loop-runtime/tests/test_supervised_worker.py`, `phase-loop-runtime/tests/test_run_status.py`, `phase-loop-runtime/tests/test_run_status_projection.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`, `phase-loop-runtime/tests/test_output_retention.py`, `phase-loop-runtime/tests/test_executable_dependency_startup.py`
- V3: `phase-loop-runtime/tests/test_supervised_v2_readiness.py`

All is the deduplicated union above; the wrapper refuses unknown groups and missing files.
