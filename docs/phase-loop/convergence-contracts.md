# Convergence contract freeze

The convergence-v1 FREEZE/BROKER/INTEG framing is historical input absorbed by
`specs/phase-plans-v10.md`. FREEZE published the typed contracts and BROKER
introduced the sole credential-capable mutation epoch; current work follows V10.

## Authority and invalidation

The versioned roadmap is authority for intent; the event log is authority for active
operation state; Git commits and PR heads are authority for implementation; merged SHAs
are authority for merged state; registries and manifests are authority for released state.
Transcripts and canonical `.phase-loop` metadata are recovery evidence only.

Verification and approval invalidate on `effective_code_changed`, `roadmap_changed`,
`base_sha_changed`, `dependency_sha_changed`, or `verification_plan_digest_changed`.

## Provider terminal outcome

After `provider_call_in_flight`, an operation exits only through observed terminal effect,
proven terminal no-effect with a non-late-commit guarantee, or durable ambiguous-outcome
blocking. Timeouts and human overrides do not turn ambiguity into progress.
`publish_committed_branch/github`, enabled by agent-harness#199, is the sole
`supported`/`automated` pair. All other enumerated pairs remain `human-executed`,
and unlisted pairs remain unavailable for dispatch.

## Failure taxonomy and fixtures

The metadata-only fixture set preserves fail-closed cases for crash, partition,
stale-worker, delayed-commit, mixed-version, exact-head, degraded-seat, ambiguous-outcome,
forged completion evidence, malformed envelopes, capability overclaim, stale or delayed
seat writes, and action-outside-bounds. Absent review sources and unavailable baseline
measurements are recorded as unavailable rather than inferred.

## Isolation and admission

Future work may run concurrently only with known evidence, disjoint owned paths, and
frozen shared interfaces. Same-repository mutation, topological merges, release
publication, overlap, and unknown evidence serialize. RUNTIME and BROKER share the single
seven-field `AdmissionRequest` fence rather than duplicate admission shapes.

## Broker epoch

`phase_loop_runtime.convergence.broker` is the only mutation boundary. Admission evaluates
policy and fencing under an inter-process lock, persists intent before provider dispatch,
then persists only observed terminal evidence. A supported provider pair may reach an
adapter; only `publish_committed_branch/github` currently qualifies. Other pairs
fail closed before mutation. Ambiguous outcomes permanently block the epoch across
restart and leave the owner unsealed.

Broker environment roles retain mutation credential keys only for the broker. Coordinator
and workers receive a stripped environment. The GitHub adapter rechecks repository branch
and HEAD, pushes the exact validated `<head_sha>:refs/heads/<branch>` without force,
and opens the requested draft posture
without a recommit. `publishing.py` may stage and commit locally, but delegates push/PR work
through `BrokerClient`.

## Publication confirmation observations

The supported pair permits confirmation observations within one uninterrupted
original adapter invocation. The adapter implements at most three rounds, with
waits of one then two seconds. The original invocation may attempt at most one
push and one PR creation, with no mutation retry.

Each round rechecks that the remote branch head equals the requested head.
A wait is eligible only after either:

- A valid empty JSON PR list.
- Exactly one PR object with a present, full lowercase hexadecimal `headRefOid`
  of 40 or 64 characters, matching the requested head's length but differing in
  value, while every other identity predicate passes: `baseRefName == request.base`,
  `headRepositoryOwner.login` equals the origin owner, `isCrossRepository is False`,
  the URL matches the origin repository under the existing URL predicate, and
  the URL equals `diagnostic_pr_url` when one was returned. Only head equality
  is excepted during these intermediate observations.

Missing or malformed values, mismatched remote heads, failed or unparsable reads,
multiple PRs, and every other identity mismatch are immediately
`outcome_ambiguous_blocked`. Exhaustion remains ambiguous with the final
observation's reason: `pr-list-empty` for an empty list or `pr-head-unconfirmed`
for an otherwise valid differing head, including mixed sequences. Success still
requires exact remote and PR head equality and the existing identity checks.
Pre-push proven-rejection rules, the non-late-commit guarantee, success/no-effect
evidence, idempotency, expected-version and revocation fields remain unchanged.

Refusal reasons are deliberately more precise: blank stdout is
`pr-read-unparsable`, not `pr-list-empty`; a missing or malformed differing head
is `pr-read-unparsable`, not `pr-head-unconfirmed`. Identity-invalid stale objects
receive `pr-base-unconfirmed`, `pr-head-repository-unconfirmed`,
`pr-url-unconfirmed` or `pr-url-readback-mismatch`, as applicable. None of these
refinements weakens terminal ambiguity.

Eligible observations emit WARNING diagnostics containing only the round,
classification and whether another round follows. Invalid observations emit
no such record. These stderr diagnostics contain no payload or request identity
and are not additional sealed evidence. There is no wait after round three.

This policy authorizes no restart or resume of a publication attempt, new
admission, terminal reversal, owner sealing, or lease reset. An ambiguous
operation stays permanently blocking and unsealed.

`WriterGenerationLease` uses nonce/generation ownership with no TTL or renewal.
More observations extend its held interval. DRAINING rejects append/effect
validation; the default 60-second quiescence wait raises without deleting leases
or authorizing migration. The round count and added sleeps bound neither external
command durations nor lease lifetime and establish no overall lease deadline.
The observation window is also the unsealed adapter-start-owner window: under
the unchanged FABPUB fence, a competing same-repository publish or same-head
retry that encounters it promotes the in-flight owner to permanent
`outcome_ambiguous_blocked`, so each added round widens that exposure. This
amendment does not relax that fence.

These observations are defensive under unverified possible read-visibility lag.
They rely on no asynchronous provider processing, visibility SLA or provider-effect
drain. Original PR-list bytes are missing; this amendment establishes no incident
cause or delayed mutation application and supplies no missing historical custody
evidence, HARDEN acceptance or downstream dispatch authority.
