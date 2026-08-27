# Convergence runtime

The convergence runtime is a coordinator-owned, metadata-only substrate: a
durable event log, reconciliation against exact live state, bounded provider
adapters, and a ledger-only recovery projection. RUNTIME provides this
substrate; INTEG owns DAG wiring and the broker alone owns mutation
credentials.

## Event log durability

The log lives below a coordinator root, never inside a repository's
`.phase-loop` directory, and holds one canonical JSON line per intent or
outcome, bounded to 64 KiB per record.

One append is durable before the call returns:

- the payload is written with a **fully drained** write loop, so a short write
  can never commit a truncated record;
- the file is `fsync`-ed, and the parent directory is `fsync`-ed as well
  whenever the append is what created the directory entry — a POSIX directory
  entry is not durable until its directory is synced;
- an **exclusive `flock` serializes writers across processes**, not merely
  across threads, and the whole read/decide/write sequence happens under that
  one lock, so two coordinators appending concurrently cannot interleave a
  check with the other's write.

## Corruption and torn records

Only the **final** record may be torn, because only the final record can be an
interrupted in-progress append.

- A reader tolerates a malformed final record and is otherwise byte-neutral: it
  repairs nothing, so `train-status` can never change the log it is inspecting.
- The next **append** truncates a torn final record under the same exclusive
  lock, so the new record lands on a clean boundary instead of being
  concatenated onto a half-written line.
- Malformed content **before** the final record is real corruption. It is
  reported and never repaired away.

## Replay

Replay is exact-key: `(train_id, node_id, attempt_id, epoch)` governs the
intent/outcome fold and the pending-attempt set.

- An outcome requires a prior intent under the same exact key.
- An identical replay is idempotent; a same-key record whose payload differs is
  rejected, because the log will not hold two answers for one key.
- `last_event_offset` is the **zero-based** durable-record index, and `-1` when
  the log is empty.
- Replay order decides the fold: the last durable event of either kind per
  `node_id` is that node's recovered state.
- Mixed schema/model versions, mixed train identities, epoch regression,
  conflicting duplicates, an outcome without an intent, and an ambiguous
  provider outcome are each recorded as a **distinct** ambiguity, so a caller
  can tell which remedy applies rather than reading one merged string.

## Reconciliation, and replay-derived validity versus live authority

This distinction is the one an operator is most likely to get wrong.

`TrainStatusSnapshot.verification_valid` and `approval_valid` are
**replay-derived ledger facts**. They report what the recorded outcomes
claimed. They are not fresh authority, they are not re-checked against the
world, and they must never be read as a live gate. The JSON field names are
unchanged for existing consumers and carry exactly this replay-derived meaning;
the human render labels them as replay-derived in words.

**Live authority lives only in a fresh `ReconciliationVerdict`.** It alone
carries the authority binding, the metadata-only observations, the
non-secret blocker reason, `checked_at`, and the invalidation triggers.

Every reconciliation decision re-probes all four domains — Git, GitHub,
provider, and registry — from scratch. A cached observation is never authority.
Authority is selected across the frozen split:

| Authority | Selected when |
| --- | --- |
| `EVENT_LOG` | an attempt is still in flight, or the state cannot be decided |
| `REGISTRY_MANIFEST` | a release is observed or ledgered |
| `MERGED_SHA` | a merge is observed or ledgered |
| `GIT_HEAD` | an implementation or PR head is observed or ledgered |
| `ROADMAP` | intent only |

Reconciliation **fails closed**, returning a blocked verdict naming the domain
rather than raising, when a required probe is absent, errors, returns nothing,
returns a non-mapping, or declares itself stale — and likewise for an ambiguous
or unidentifiable ledger. Each changed-code, roadmap, base, dependency, and
verification-plan trigger is emitted at most once per decision. A registry,
merge, or head observation that **disagrees** with the ledgered value fires an
invalidation trigger; a domain that reports nothing about a field has observed
nothing, which is not a divergence. Any non-valid verdict clears the
replay-derived verification and approval evidence for the action.

## Adapter bounds

Codex, Claude, and outside-agent adapters each perform one bounded,
non-coordinating action and return only the frozen `ConvergenceResultEnvelope`.
They do not coordinate trains, publish, merge, release, or package, and they
import no coordinator, publisher, or broker effect path.

- **Identity is exact.** `argv[0]` must name the expected provider executable
  exactly; a prefix match would admit a look-alike such as `codex-rogue`.
- **Version binding.** The seven-field `AdmissionRequest` is preserved and its
  expected-version predicate must be genuinely nonempty — a whitespace-only
  predicate is truthy but binds nothing, and is rejected.
- **Environment.** The child inherits only what survives the two pure scrubbers,
  the subscription scrubber and the mutation-credential stripper, so no
  mutation credential, vendor API key, or endpoint escape reaches it.
- **Time and process group.** The child runs in its own session and a timeout
  kills the whole process group, so a provider's forked helpers cannot outlive
  the bound. The result is `degraded`.
- **Argv, cwd, and output** are bounded; only a bounded prefix of stdout is
  parsed.
- **Unparseable, non-object, unknown-status, truncated, or non-zero-exit
  results are never reported as success.** An outside-agent run is admitted only
  behind a passing conformance verdict — a missing submission blocks rather
  than defaulting permissive, because there is nothing to validate.

## Metadata-only redaction

Nothing in this substrate carries provider text, reviewer prose, credentials,
or environment values.

- Adapter envelopes carry a **fixed** metadata-only diagnostic phrase, so a
  secret the provider printed cannot be laundered into a result.
- Reconciliation observations are reduced to the exact bounded fields a
  decision reads — an allow-list, so a probe that grows a new field cannot
  silently widen what is retained — and a blocker reason never interpolates a
  probe backend's own message.
- Advisor seat outcomes store only identities, status, timestamps, and digests.

## Recovering state after a restart

    phase-loop train-status --event-log PATH [--json]

This mode is read-only, requires no legacy train roadmap, and is mutually
exclusive with `--train`. It reconstructs from the ledger alone: no runner
cache, working tree, or side artifact is consulted, so identical durable events
render identical bytes before and after a restart. Pending attempts are
qualified by node, so two nodes sharing an attempt id stay distinguishable.
Ambiguity is retained and reported rather than treated as success, and an
**absent log fails closed** — unknown state is not an empty successful train.

The legacy `phase-loop train-status --train FILE` ledger view is unchanged in
both bytes and semantics.

## Ownership

RUNTIME owns the event log, reconciliation, the three adapters, the status
projection, and the `train-status --event-log` mode. It creates no advisor seat
outcomes — REVIEWTRUTH owns seat lifecycle persistence — and performs no
credential-bearing broker effect. INTEG owns DAG coordination and downstream
refresh; FABPUB/FABREADMIT and RELEASE own merge, release, and publication. The
event log is written only by the coordinator, and only below a coordinator
root.

## INTEG coordinator contract

`run_train` may receive a credential-free `CoordinatorRuntime` containing the
train identity, coordinator root, canonical roadmap digest, workspace identity,
supported event/transition/invalidation versions, exact authority probes, and a
`BrokerClient` boundary. The coordinator records intent before an admitted
action and outcome afterward; the event log, then exact live authority, takes
precedence over legacy-ledger projections.

Every action is reconciled before dispatch. Missing or conflicting Git,
GitHub, provider, or registry authority; unknown versions; stale fences;
missing digest-bound verification; stale approval; and ambiguous provider
outcomes block without a provider call. Independent repositories can overlap
only after the persisted isolation predicate approves disjoint non-empty owned
paths and frozen shared interfaces. Merges and release publication serialize.

After an upstream merge, downstream channels are refreshed to the exact merged
SHA, prior verification and approval are invalidated, the bound suite produces
digest-addressed evidence, and only then can the broker admit republish or
review. A conflict is typed and resumable; autonomous runs still stop at
`drafts_open`.
