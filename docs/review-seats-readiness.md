# Review seat readiness

IF-0-FIRSTSEAT-1 uses one row per vendor, remote route and runtime president
rung. Every row includes `id`, `vendor`, `route`, `claude_transport`,
`profile_digest`, `allowlist_id`, `allowlist_digest`, `tool_surface`,
`credential_lane`, `projection`, `host_classes`, `qualification_record`,
`live_evidence_digest`, `status`, `exception`, `expiry`, `renewal_record`,
`end_condition` and `interim_route`. President rows also include `rung`,
`tool_mode` and `bound_s`. Status is `candidate` until the window verifier admits
retained evidence. Changing a qualification key returns the row to `candidate`.

`seat-window qualify` is pending its production window supplier and fails closed
with `candidate`; this landing supplies the matrix and offline validators only.
No W1 evidence has been collected. LA-1, LA-2 and LA-3 remain owner gates.
Runtime and profile digests must come from the installed runtime on each host;
source-checkout tests do not establish host readiness.

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
| fable | native_fill_deferred | sealed | 300 | team, standard | candidate |
| fable | _launch_claude:print | sealed | 300 | team, standard | candidate |
| fable | _launch_claude:tui | sealed | 300 | team, standard | candidate |
| sol | _exec_leg:codex | sealed | 300 | team, standard | candidate |
| grok | _exec_leg:grok | sealed | 300 | team, standard | candidate |
| gemini | _launch_gemini | sealed | 300 | team, standard | candidate |

The bound is the default no-output setting on `bounded`; its configured value
must be finite, positive and at most 1800 seconds. `heartbeat_only` never has a
silence kill (OD-11). `phase-loop seat-window matrix` emits every schema field
for each vendor, remote and president row. Unmeasured fields are null, with
`candidate` status; remote rows remain `remote-pending`. No separate president
route is synthesized by the reducer.

Use the [window kit](../plans/evidence/seat-qualification/README.md) for every
candidate on a host. Records are private per operator. Mode 0600 does not isolate
an unconfined co-seat running as the same operator. W1 must measure isolation
between its two distinct operator accounts. Public account labels are opaque.
Reviews retain the T3 fallback under OD-10; offline checks do not close W1.
Expired exceptions cannot support a passing window. Renewal requires a new
owner record and matrix update; rerunning a command does not extend an expiry.
The pending window supplier must retain observation and staged-read receipts privately;
offline verification checks the measurement digest bindings. Installed-provider and attended
host validation remain required before any candidate status changes.
