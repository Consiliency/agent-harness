# Convergence runtime

The convergence runtime is a coordinator-owned, metadata-only substrate. Its
event log is placed below a coordinator root, never inside a repository's
`.phase-loop` directory. It writes one canonical JSON line per intent or
outcome, flushes and fsyncs before returning, accepts only a malformed final
crash record, and fails closed for earlier corruption.

Use `phase-loop train-status --event-log PATH` for transcript-free recovery.
This mode is read-only and does not require a legacy train roadmap. The
projection reports pending attempts and explicitly retains ambiguity rather
than treating it as success.

Reconciliation uses injected read-only Git, GitHub, provider, and registry
authority observations. A stale head, roadmap, base, dependency, or
verification-plan digest invalidates the state. Missing authority and mixed
event versions block reconciliation.

Codex, Claude, and outside-agent adapters run one bounded action with a
credential-stripped environment and return the shared result envelope. They do
not coordinate trains, publish, merge, release, or package. Advisor seat
outcomes store only identities, status, timestamps, and digests; raw reviewer
text is excluded. RUNTIME provides this substrate; INTEG owns DAG wiring and
BROKER alone owns mutation credentials.
