# Review seat readiness

IF-0-FIRSTSEAT-1 uses one row per vendor, remote route and runtime president
rung. Every row includes `id`, `vendor`, `route`, `claude_transport`,
`profile_digest`, `allowlist_id`, `allowlist_digest`, `tool_surface`,
`credential_lane`, `projection`, `host_classes`, `qualification_record`,
`live_evidence_digest`, `status`, `exception`, `expiry`, `renewal_record`,
`end_condition` and `interim_route`. President rows also include `rung`,
`tool_mode` and `bound_s`. The documentation reducer changes a row to
`done-local` only when that row is observed in the `standard` context of a
passing W1 set: one run on the designated seat host, a standard host, under its
one operator account (OD-12). Unobserved vendor, remote and president rows retain
their prior status. `done-team` is a later status for a row also qualified on a
shared team host under two operator accounts; no reducer path emits it, and no
EC, gate or window requires it.

`seat-window qualify` now implements the frozen per-context launch, board and
containment-reduction sequence. Live use remains closed: it returns
`window_owner_approval_required` before preflight or a provider call until an
owner-approved source change opens W1. No W1 evidence has been collected. LA-1,
LA-2 and LA-3 remain owner gates.
Runtime and profile digests must come from the installed runtime on the
designated seat host; source-checkout tests do not establish host readiness.

| Row | Route | Status | Named exception | Expiry / end condition |
| --- | --- | --- | --- | --- |
| Claude | local | candidate | open egress | 2026-12-04 UTC or CLAUDENET exit, whichever is first |
| Gemini | jailed | candidate | none | W1 required |
| Codex | local | candidate | unconfined | 2026-12-04 UTC or CODEX exit, whichever is first |
| Grok | local | candidate | unconfined | 2026-12-04 UTC or GROK exit, whichever is first |
| Pi | local | candidate | none | PI window required |
| Claude remote | remote | remote-pending | none | REMOTE activation |
| Gemini remote | remote | remote-pending | none | REMOTE activation |
| Codex remote | remote | remote-pending | none | REMOTE activation |
| Grok remote | remote | remote-pending | none | REMOTE activation |
| Pi remote | remote | remote-pending | none | REMOTE activation |

President inventory is supplied by `PresidentInvoke`. These are the current
runtime-named entries; sealed provider routes remain in the inventory.

| Rung | Runtime route | Tool mode | Bound (seconds) | Host classes | Status |
| --- | --- | --- | ---: | --- | --- |
| fable | native_fill_deferred | sealed | 300 | standard | candidate |
| fable | _launch_claude:print | sealed | 300 | standard | candidate |
| fable | _launch_claude:tui | sealed | 300 | standard | candidate |
| sol | _exec_leg:codex | sealed | 300 | standard | candidate |
| grok | _exec_leg:grok | sealed | 300 | standard | candidate |
| gemini | _launch_gemini | sealed | 300 | standard | candidate |

The bound is the default no-output setting on `bounded`; its configured value
must be finite, positive and at most 1800 seconds. `heartbeat_only` never has a
silence kill (OD-11). `phase-loop seat-window matrix` emits every schema field
for each vendor, remote and president row. Unmeasured fields are null, with
`candidate` status; remote rows remain `remote-pending`. No separate president
route is synthesized by the reducer.

Use the [window kit](../plans/evidence/seat-qualification/README.md) for every
candidate on a host. Records are private per operator. Mode 0600 does not isolate
an unconfined co-seat running as the same operator. W1 runs under one operator
account, so its record has no peer observation; the two-account check stays only
as offline validation for `done-team`. Public account labels are opaque.
Reviews retain the T3 fallback under OD-10; offline checks do not close W1.
Expired exceptions cannot support a passing window. Renewal requires a new
owner record and matrix update; rerunning a command does not extend an expiry.
Qualification retains reducer observation, egress, leg-exec and staged-read receipts
privately. The owner summary is private-only and is neither selected by verification nor
exported. Offline verification checks board input, delivered-turn and measurement digest
bindings. Installed-provider and attended host validation remain required before any
candidate status changes.
