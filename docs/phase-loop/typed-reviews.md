# T3 typed review host integration

The local `typed-review` service prepares and validates **NON_GATING** reviews
through the [frozen review coordinator](typed-review-contract.md). Host actions
are data: neither the Python service nor the CLI dispatches a provider, calls
MCP, launches a thread, or executes a finding. A trusted driving host performs
the indicated exposed T3 tool calls and relays their original observations.

This implementation uses `t3_host_attested.v1`. Original terminal identity and
relayed bytes are **HOST_ATTESTED**, not authenticated transport capture. T3's
observed `assistant_message` type covers both commentary and terminal output;
there is no terminal flag in this profile. An echoed request binding, successful
task, summary, or schema-only class parse cannot establish accepted content.
Only `ReviewCoordinator` validates content and creates records, using the real
local BAML worker and the request's saved source snapshot.

## Deployment and authority

Use a private directory on a local filesystem with SQLite locking, **outside
the dispatched checkout**, including after symlink resolution. The host must
exclude the reviewer from this state using its existing platform controls.
Directory mode 0700 and owner-only files do not exclude hostile code sharing the
host's UID. A shared checkout or a bare T3 worktree supplies no such exclusion.
The service checks placement and immutable scope; it does not authenticate the
caller or implement an operating-system isolation boundary.

The shipped `T3NonGatingPolicy` admits only HOST_ATTESTED, with empty governed
provenance, unusable-seat blocking and no deferred waiver. Policy identity is
fixed across charters and processes. A Python host may inject a
`CoordinatorPolicy`; the service retains its identity and rejects incompatible
authorization before coordinator request persistence. No policy JSON, token,
environment variable, reviewer field or CLI switch grants governed eligibility.
Governed admission requires separate reviewed integration.

The host scope contains exactly `parent_thread_id` and an existing absolute
`checkout` directory, canonically resolved. Both are frozen when the journal is
created. Reopening with another parent or checkout refuses. Only **shared,
pre-bound checkout** dispatch is supported. Generated worktree paths, runtime
overrides, wait mode, top-level thread launch and provider fallback are outside
this profile.

Every intake read requires a **non-null `thread.worktreePath`** resolving to the
frozen checkout. A null path stays `result_unavailable`; the service never guesses
the project root. Shared root-child behavior is a RENFORCE qualification question.

## CLI grammar

Run from the installed runtime, or use `python -m phase_loop_runtime.cli` in
place of `phase-loop` with the intended source tree on an absolute PYTHONPATH.

```text
phase-loop typed-review request    --state DIR --parent-thread ID --checkout DIR --input FILE
phase-loop typed-review prepare    --state DIR --parent-thread ID --checkout DIR --binding DIGEST --input FILE
phase-loop typed-review register   --state DIR --parent-thread ID --checkout DIR --binding DIGEST --input FILE
phase-loop typed-review intake     --state DIR --parent-thread ID --checkout DIR --binding DIGEST --input FILE
phase-loop typed-review resume     --state DIR --parent-thread ID --checkout DIR --binding DIGEST [--input FILE]
phase-loop typed-review correction --state DIR --parent-thread ID --checkout DIR --binding DIGEST --input FILE
```

Inputs must be regular, same-UID private JSON files with no group/other
permissions; use mode 0600. Input-file symlinks, duplicate keys, non-finite
numbers, invalid UTF-8 and over-limit files refuse. Preserve surrogate escapes
in tool observation JSON until complete item reassembly. The optional `resume`
input is parsed but conveys no parameters or authority; omit it.

Request input contains `charter`, `coordinator_key`, `subjects` and `seat`, plus
optional coordinator `purpose`, `lens`, `questions`, `evidence`, `function`,
`byte_limit` and `ledger`. `brief` and `source_snapshot` are not CLI input fields:
the charter supplies the canonical brief and the CLI saves local BAML sources.
Subject identities follow the frozen coordinator contract, including immutable
digests rather than mutable paths alone. Example charter:

```json
{
  "schema": "t3_host_charter.v1",
  "review_brief": "Inspect the frozen material, prior findings, responses and unresolved objections.",
  "host_scope": {
    "parent_thread_id": "actual-parent-thread",
    "checkout": "/absolute/existing/checkout"
  },
  "allow_correction": false
}
```

`allow_correction` defaults to false and must be boolean. Canonical charter
bytes are privately stored by digest before request construction. Orphan
charter storage grants no dispatch. Later operations resolve the same
digest-bound charter; they cannot append instructions, change scope or increase
the correction allowance. Lens-free and arbitrary-lens requests use the same
frozen result schema.

`prepare` accepts exactly `target` and `capabilities`. The host supplies a fresh
exposed `orchestrator_capabilities` result. Required true features are
`appOwnedSubagents`, `asyncPolling`, `threadManagement` and
`incrementalThreadRead`. The uniquely selected provider/model must be available
for child tasks without unresolved constraints, with cross-provider support when
applicable. Every declared model option requires an explicit supported value:
boolean options use booleans; select options use a declared ID. There is no
inheritance of mutable model options. The observed interaction mode is `default`.
Model option declarations must be a list (or absent/null for an optionless model).
Select choices must be a list of objects with unique nonblank bounded string IDs;
malformed lists or entries refuse before intent creation.

The capability snapshot must contain an exposed `runtimeMode`:
`approval-required`, `auto-accept-edits`, `auto`, or `full-access`. Its first saved
value is immutable for that intent. Re-preparation and correction require the
same mode; missing/unknown modes return `result_unavailable`, and changed modes
return `binding_mismatch` before a new correction reservation or action. Direct
`prepare` of a correction binding checks the original intent's mode and exact
provider/model/options, including after reservation commit but before intent
creation. Reopening cannot replace either saved value.

This binds **host-observed requested posture**, not effective child permission
attestation. Dispatch still omits a runtime override; T3 may step an inherited
mode down according to the provider. These relayed snapshots cannot establish
effective permissions or detect a host changing mode after preparation. `resume`
has no fresh capability input and returns the frozen action or local recovery;
the trusted host must maintain its authorized posture before executing an action.

The private action contains these actual `delegate_task` arguments:

```text
{
  task: exact saved build_request(binding).prompt,
  target: {providerInstanceId, model, options?},
  mode: "async", role: "review", isolation: "shared",
  interactionMode: "default",
  clientRequestId: "typed-review-v1-" + binding
}
```

The original and correction task strings must be UTF-8-byte-identical to their
saved BAML prompts. Do not append commentary or use the BAML placeholder HTTP
client. The host keeps the returned task ID. A correction is a fresh delegated
task with a distinct saved key, never a later message to the original child.

## Registration and intake files

A tool observation has exactly the following wrapper fields. `result` is the
verbatim structured tool-result JSON object; it is not a synthesized summary.
Use unprefixed tool names inside the wrapper.

```json
{
  "schema": "t3_tool_observation.v1",
  "tool": "task_status",
  "arguments": {"taskId": "actual-task-id"},
  "result": {}
}
```

Registration input has exactly `schema: "t3_registration.v1"`,
`request_binding`, `client_request_id`, `payload_digest`, `host_scope`, and
`observation`. The saved dispatch action supplies the key and payload digest.
The observation is `delegate_task` with arguments exactly matching the saved
payload, or a late `task_status` requesting the exact actual task ID. Its result
must contain nonblank `taskId`, `childThreadId`, `childRunId`, and the exact
requested `providerInstanceId` and `model`; null or different actual model
refuses. Registration freezes the original identity once. A late matching
registration can reconcile an unresolved intent; it never re-arms dispatch.

A **`task_status`-only first registration is a pure trusted-host assertion of
association** with the saved request. The status result exposes no echoed
`clientRequestId`, prompt or payload digest. Wrapper fields do not establish
observed request correlation or authentication. If the host cannot establish
the association, leave the intent unresolved. Null `delegate_task.childRunId`
refuses without registration; the host may later assert association using a
status observation with all non-null original identity fields. This version
does not accept a two-observation registration schema. Such a protocol could
cross-check launch task/thread against status, but would still trust the host
and would require a separately bounded, explicitly bound format. It cannot
recover a launch observation that was lost, so status-only mode remains supported.

Within one journal, registration atomically refuses `delivery_conflict` if any
task ID, child thread ID or original run ID is already bound to another request,
including an original and its correction. Concurrent first registrations share
the same transaction gate. Identical same-binding registration is idempotent.
Local refusal creates no content failure or correction allowance; the host may
register the correct unused identity on the still-unresolved intent.

Intake has exactly these fields:

```text
{
  schema: "t3_intake.v1",
  terminal: {
    schema: "t3_original_terminal.v1", profile: "t3_host_attested.v1",
    request_binding, host_scope, taskId, childThreadId, childRunId,
    itemId, position, updatedAt
  },
  completion: <original task_status observation>,
  timeline: [<t3_thread_read observation>, ...],
  text: [<selected-item t3_thread_read observation>, ...],
  evidence_digests: {<permitted handle>: <verified digest>}
}
```

`terminal` is a separate trusted-host attestation, not an extra field added to a
T3 tool result. Completion must identify the registered original run with
`status=completed` and `workState=result_available`. Original failure, unfinished
work or missing completion fields supply no candidate. Later-run success cannot
replace it. Later failure, running turns, questions and child work cannot reopen
an already completed original. Summary strings are unused: they lack a
completeness guarantee. `recentRuns` may corroborate original identity,
completion and provider/model, but cannot substitute for them.

Traverse `t3_thread_read` with `view=messages`, initially
`afterPosition=null`, following each actual `nextPosition` while `hasMore=true`.
Positions strictly increase and item IDs never repeat. Filtered position gaps
are allowed; skipping the returned cursor is not. The final page must be
nonempty with `hasMore=false` and `nextPosition` either null or exactly the
maximum position seen over the entire traversal. The non-null form is an
observed host behavior, not a universal schema guarantee.

After full traversal, the attested item must be the maximum-position local
provider `assistant_message` in the original run, with `createdBy=agent` and
completed status. An earlier commentary item cannot qualify when a later
original assistant item exists. Every page must match the frozen parent,
subagent relationship, child thread and checkout. Inherited, synthetic,
cross-run, ambiguous or moving items refuse.

Recover only that item's text. Start with its timeline text, then request its
`itemId` with `textOffset=previous nextTextOffset`. Offsets count **UTF-16 code
units**, not Python characters or UTF-8 bytes. Each truncated chunk must advance
by its exact unit length; the final chunk requires null `nextTextOffset`.
Stable item metadata includes IDs, position, run, source thread, visibility,
type, author/source, status, update time, message ID, title and optional subagent
ID. Never join different items. Genuine surrogate pairs may span JSON-escaped
chunks; final decoding must produce exact valid UTF-8. Unmatched surrogates and
U+FFFD immediately on either side of a chunk boundary refuse as uncertain.
Genuine U+FFFD away from a boundary is preserved. Reading may acknowledge
delivery; acknowledgement does not change accepted identity.

## Service API and durable recovery

`T3ReviewService(private_directory, *, host_scope, policy=None)` owns a private
journal beside the coordinator database. Its public operations are:

| Method | Inputs and result |
| --- | --- |
| `request(*, charter, **request_inputs)` | Frozen coordinator request; in-process callers supply `source_snapshot` |
| `prepare(binding, *, target, capabilities)` | Saved dispatch, recover or unresolved `HostAction` |
| `register(binding, registration)` | Original immutable registration metadata |
| `intake(binding, package)` | Coordinator content record after complete recovery |
| `resume(binding)` | Known-task recovery action or current local validation of saved delivery |
| `correction(original_binding, *, capabilities)` | Recover an existing reservation or reserve the charter's one permitted correction |

Host actions expose `kind`, `request_binding`, `tool`, private `arguments` and
`payload_digest`. `metadata()` omits the arguments; `private_payload()` includes
them. A known task returns exactly `task_status({taskId: saved_task_id})`.
Production `REDISPATCH_CAPABLE` is **false**. The presence of `clientRequestId`
alone is not a durable deduplication guarantee. A fake-only true capability in
tests is explicitly synthetic and conveys no live dispatch permission.

| Boundary or outcome | Recovery behavior |
| --- | --- |
| Charter saved, request not committed | No dispatch; repeat the authorized request inputs |
| Coordinator request committed, intent absent | Identical request/key recovers its binding; prepare that binding |
| Intent committed but not offered | Resume offers that exact saved action once |
| Offered action, response lost or export interrupted | Remain unresolved; no new task, key, lineage or budget |
| Late original task registration | Host asserts saved association; validate supplied identities, then recover the known task |
| Journal registration committed before coordinator registration | Intake/resume repairs coordinator registration idempotently |
| Incomplete or uncertain recovery | No delivery/parse; recover authentic original observations within limits |
| Complete delivery committed before parse | Local resume parses saved bytes and saved BAML sources |
| Same complete delivery repeated | Current revalidation; unchanged accepted identity |
| Changed payload, registration or complete delivery | `delivery_conflict`; preserve first durable data |
| Correction reserved before intent | Recover the reservation; public prepare verifies original target and host mode before rebuilding its intent |
| Concurrent matching intake/reservation | One durable delivery/reservation; other calls reconcile it |
| Original invalid content | One correction only if the frozen charter permits it |
| Invalid or over-limit correction | Allowance exhausted, including after restart |
| Valid dissent or valid incomplete content | No correction or provider retry |
| Local BAML/bridge failure or SQLite lock timeout | Local recovery only; no provider retry |

Coordinator request and correction commits precede intent creation. Journal
intent state precedes returned dispatch data; immutable original registration
precedes coordinator registration; complete delivery precedes parsing. Stored
sources and current revalidation are required on replay, rather than trusting
an earlier usable record alone. An unchanged result retains record/standing
identity; current validation failure supplies no usable vote. A successful
correction is a substantive replacement linked to the original failure within
one lineage, not an independent extra vote or certified format-only repair.
Original brief, failure, response (or honest digest-only absence), findings,
prior responses and unresolved objections remain in the frozen context.

## Bounds, privacy and refusal vocabulary

| Profile bound | Limit |
| --- | --- |
| Complete recovered body | 2,097,152 UTF-8 bytes |
| Each serialized observation | 8,388,608 bytes |
| Retained intake/private JSON input | 25,165,824 bytes |
| Capability snapshot | 1,048,576 bytes |
| Saved prompt | 8,388,608 UTF-8 bytes |
| Identity string | 2,048 characters |
| Canonical envelope metadata | 32,768 bytes |
| Timeline pages / item-text pages | 128 / 256 |
| Unique timeline items | 4,096 |
| SQLite busy timeout | 60 seconds |

The coordinator's content limit is at most 1,048,576 UTF-8 bytes, potentially
lower in the request. An authentic complete oversized body within the adapter
ceiling reaches the coordinator unchanged for `limit_exceeded` with digest-only
coordinator storage. The adapter privately retains complete bytes for bounded
recovery. Above the adapter ceiling, return `result_unavailable`; do not
truncate, fabricate padding or claim a digest for unseen bytes. The envelope
contains the original body once and bounded original identity/completion
metadata, fitting `6 * body_bytes + 65536`. Volatile later-run summaries and
repeated pages stay out of this envelope.

The journal retains original bounded registration and delivery observations,
exact body/envelope, capability snapshot, evidence map and integrity digests.
Unaccepted observation files remain host-owned inputs. There is no total
database quota; limits apply per operation. Journal transactions use
`BEGIN IMMEDIATE` and `synchronous=FULL`. The directory is mode 0700; databases
and exported `action-<sha256>.json` payloads are owner-only. Exports are explicit,
exclusive and fsynced. Reusing an exact existing artifact is not permission to
dispatch it again.

Success stdout is `t3_cli_result.v1`, `ok=true`, with coordinator metadata or
host-action metadata and a relative private action filename. It never includes
raw task arguments, prompts, review bodies, summaries or raw exception text.
An unresolved action can be a successful CLI operation without being a usable
review. Refusal uses the same schema, `ok=false`, a closed `rejection_code`, and
exit 1. CLI argument errors use ordinary argument-parser diagnostics.
Residual ordinary local exceptions, including coordinator database-open failures,
map to `result_unavailable` at the CLI adapter boundary without raw diagnostics or
a provider retry. `SystemExit` and `KeyboardInterrupt` are not converted.

| Code/outcome | Meaning |
| --- | --- |
| `binding_mismatch` | Charter, scope, policy, target, identity or evidence mismatch; content binding errors are coordinator outcomes |
| `result_unavailable` | Unsupported profile/capability, incomplete/ambiguous/mutable/over-ceiling recovery, missing state, lock failure or unavailable correction |
| `delivery_conflict` | Same key or consumed attempt with different data |
| `invalid_json`, `schema_mismatch`, `semantic_mismatch`, content `binding_mismatch`, `limit_exceeded` | Invalid content may permit the original lineage's single correction |
| `baml_unavailable`, `baml_parse_failed`, `baml_changed_value` | Local worker/bridge recovery only |
| `result_incomplete` | Valid incomplete review supplies no usable vote and no correction |

These are the frozen coordinator codes, not new legacy panel detail/blocker
enums. Existing unusable/DEGRADED and `panel_nonconforming` compatibility remains
with downstream consumers. Legacy verdict vocabulary and executor closeout
acceptance are unchanged. Review bodies are JSON only; appending legacy verdict
markers does not make them valid.

## Evidence boundaries

`test_review_t3.py`, `test_review_t3_faults.py` and `test_review_t3_cli.py`
exercise synthetic host transport observations through production service/CLI
entry points. Positive controls invoke the local BAML worker. The identity
mutation omits exactly the completion `childRunId` comparison in a test-only AST
copy of production recovery, retaining the candidate and every other gate. The
timeline control falsely marks the selected page complete; the text control
ignores its truncation/next-offset signal. Each lets its matching negative reach
real BAML parsing, while an unrelated negative still refuses. These synthetic
completion controls use complete JSON bytes with false incomplete metadata;
they prove sensitivity to those metadata gates, not recovery of unseen bytes.
The independent identity, traversal, UTF-16 and mutable-item negative matrices
remain the broader gate coverage. Gateway and reservation controls separately
detect a cached parse result and a missing durable reservation. No production
test-only bypass switch exists.
The fault suite consumes every frozen `typed_review_lineage_replay.v1` scenario,
including retained failures, oversized correction, replacement links, restart
and refused additional reservation. The fixture's distinct reserve/recover
operations use public coordinator APIs where service `correction` intentionally
combines those operations; actual dispatch/intake/replay use the adapter.

These tests are not an actual admitted T3 route, deployment qualification or
EC-RENFORCE-2 evidence. RT3 independent implementation review and final sealed
verification remain separate completion requirements. N9-R3 falsifier
structural validity stays with the RPANEL governed gate; typed acceptance
does not execute attachments. EC-EXECFIND-2 remains carried and open. No panel
SDK, roster/authentication, president route, quorum or landing authority is
changed by this host bridge.

Live root-child paths, explicit null final text offsets on untruncated terminal
items, and whether delivery acknowledgement changes `updatedAt` remain RENFORCE
qualification questions. The profile refuses uncertainty; synthetic tests do
not resolve these host semantics.
