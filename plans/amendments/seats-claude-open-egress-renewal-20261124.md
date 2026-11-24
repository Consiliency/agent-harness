# FIRSTSEAT amendment for the jailed Claude open-egress renewal

**Owner approval recorded on 2026-11-24.** The owner chose “Renew until allowlist
lands (Recommended)” and authorized about 30 more days so boards and W1 can
continue while the Claude allowlist is finished and qualified.

Under principle 3 of the [SEATS roadmap](../../specs/phase-plans-seats-v1.md) and
OQ-8 of the [CLAUDE plan](../phase-plan-v1-seats-CLAUDE.md), this is the owner
renewal record for the shipped readiness matrix. It supersedes the original
Claude date of 2026-12-04T00:00Z cited in the roadmap and the
[CLAUDENET plan](../phase-plan-v1-seats-CLAUDENET.md).

The exclusive expiry is **2027-01-03T00:00Z**. Registration of the Claude
allowlist removes the exception sooner. The renewal covers the same jailed
Claude route under the existing admission rules and destination scope. Remote
Claude and the networkless SDK worker remain outside the exception. The
separate Gemini W1 owner-grant cutoff remains 2026-12-04T00:00Z. CLAUDENET
continues under EC-CLAUDENET-1 through EC-CLAUDENET-4
(agent-harness#1820 and agent-harness#1804).

## Digest and qualification impact

Frozen inputs, jail profiles, egress allowlists, proxy digests and SDK proof
inputs keep their existing bindings. The shipped matrix change moves the
seat-window runtime digest and release identity. Issue any unused row-window
grant for the new release identity before launching on that release. New
snapshots that include the Claude route carry the renewed expiry and renewal
record. Completed row-window evidence keeps its release-bound snapshot.
Any live W1 rollout evidence required on the new build needs that build's
runtime digest and separate W1 authority. In-flight Grok tool-surface
measurements must finish on their original runtime or be remeasured under
the existing grant rules before publication on the new runtime.
