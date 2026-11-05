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
Neither schema loader may resolve unlisted or remote references.

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
   Prohibit secret values and their derived digests in envelope commitments,
   argv, references, configuration, templates and grants. Known-secret/hash
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
7. **Version window:** declare consiliency-contract>=0.7.0,<0.8.0, update its
   conftest compatibility guard and lock together. Obtain the dependency from
   the exact published Git revision using an immutable direct reference and
   uv source/lock pin; retain exact-byte schema vendoring. Confirm distribution
   metadata is 0.7.0 and installed package contents correspond to that commit.
   Do not assume a registry release, floating main, tag or package-resource
   equivalence. Failure to resolve/build that source blocks implementation
   verification; it does not authorize restoring the old bound silently.

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
No late ambient variable, flag, config discovery or re-read may alter launch.

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

Qualification probes are auxiliary pre-admission work, never worker invocations.
The worker consumes held qualification; it need not launch probes. If a future
qualified route probes, do so before capture/admission, or recapture/revalidate
all affected material. Never call a worker a probe. Dependency/classification
refusals remain before probes or envelope/credential/output effects. One
monotonic deadline starts at the first chain process and never restarts at a
helper. Bind seconds, deadline_action and config-based heartbeat/quiet behavior;
review not_armed semantics must match the contract or the route refuses.
Admission refusal means zero chain processes; helper failure after start is
running → finished with failed_to_start, never refused.

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

SCHEMA's historical receipt stays byte_pin_authority=false. The new CLOSEOUT
receipt is false by default, with per-obligation status and owner. Only the
terminal reducer may emit true for the explicitly named v2 bundle after:

- fresh protected-main ancestry, per-file hash/blob and offline loader proof,
  separate manifest/provenance seals, installed wheel/package-byte comparison,
  and dependency-window/source-lock proof;
- complete corpus/rule/named-obligation accounting with production path witnesses,
  passing expected diagnostics/effects and independent per-guard bypass controls;
- public envelope-to-attempt, durable replay, lifecycle/process-result,
  baseline/proposal/evidence independence and external controller/consumer
  reconciliation evidence, with no unresolved upstream_phase_unmet row;
- six required CI checks, dispatched Gate A and the roadmap's independent board
  and president results bound to the observed reviewed content/head.

Record source pointer, case/control IDs, production symbol, outcome, owner,
resource digest, runner artifact digest and observed run/job/head for every row.
Reject missing/skipped-only outcomes, unverifiable artifacts or stale content.
Never store raw prompts/credentials/streams, private source paths or copied
producer history. A runner-stamped post-verification amendment records newly
observed evidence; it must not predict its own future commit or require a fixed
commit count. Preserve prior receipts and bind evidence to the content actually
tested. New changes invalidate affected claims. Gate and live authority are
separate: true does not qualify installed providers or authorize execution.

No unresolved contract-representation owner question remains. External evidence
and upstream phase delivery are explicit dependencies, not permissions requested
by this planning change. Live qualification, route expansion, release and merge
remain separately owned.
