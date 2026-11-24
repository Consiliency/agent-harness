# Review seat readiness

IF-0-FIRSTSEAT-1 uses one row per vendor, remote route and runtime president
rung. Every row includes `id`, `vendor`, `route`, `claude_transport`,
`profile_digest`, `allowlist_id`, `allowlist_digest`, `tool_surface`,
`credential_lane`, `projection`, `host_classes`, `qualification_record`,
`live_evidence_digest`, `status`, `exception`, `expiry`, `renewal_record`,
`end_condition` and `interim_route`. President rows also include `rung`,
`tool_mode` and `bound_s`. The documentation reducer changes a row to
`done-local` only when that row is the window vendor's own row (Gemini for W1) and is
observed in the `standard` context of a passing W1 set: one run on the designated
seat host, a standard host, under its one operator account (OD-12). A co-seat's exec
record on the board never qualifies its row. Every other vendor, remote and president
row retains its prior status. `done-local` verification, reduction and export ignore team
contexts. `done-team` is a later status for a row also qualified on a shared team
host under two operator accounts; a later `done-team` validator owns the retained
team fields and peer observations, no reducer path emits that status, and no EC,
gate or window requires it.

`seat-window qualify` now implements the frozen per-context launch, board and
containment-reduction sequence. Live use opens only under an owner grant. A reviewed
source change sets `seat_window.OWNER_W1_GRANT_SHA256` and `OWNER_W1_PACKET_SHA256`. The
grant digest names the first line of one private grant file, which the operator mints on the
designated host in a fixed admission directory (`mint_w1_grant`). That line binds the host,
a start window, the Gemini vendor, the `standard` context, exactly one attempt and the
approved packet. No start is allowed at or after 2026-12-04T00:00Z, nor later than 10800 s
before the grant or the cutoff ends. The attempt appends a hash-chained line to the grant
file under a lock and writes a witness beside it before preflight; a preflight refusal still
uses it. Missing or disagreeing attempt evidence refuses further attempts. Without
a usable grant, `qualify` returns `window_owner_approval_required` before preflight or a
provider call, and today no grant digest is set. No W1 evidence has been collected. LA-1,
LA-2 and LA-3 remain owner gates.
Runtime and profile digests must come from the installed runtime on the
designated seat host; source-checkout tests do not establish host readiness.

| Row | Route | Status | Named exception | Expiry / end condition |
| --- | --- | --- | --- | --- |
| Claude | jailed | candidate | open egress | 2027-01-03T00:00Z or CLAUDENET exit, whichever is first |
| Gemini | jailed | candidate | none | First post-TEAMHOST row window (agent-harness#1903) |
| Codex | jailed | candidate | none | Row window or owning phase exit |
| Grok | local | candidate | unconfined | 2026-12-04 UTC or GROK exit, whichever is first |
| Pi | local | candidate | none | PI window required |
| Claude remote | remote | remote-pending | none | REMOTE activation |
| Gemini remote | remote | remote-pending | none | REMOTE activation |
| Codex remote | remote | remote-pending | none | REMOTE activation |
| Grok remote | remote | remote-pending | none | REMOTE activation |
| Pi remote | remote | remote-pending | none | REMOTE activation |

The Claude row's `renewal_record` names the
[2026-11-24 owner approval](../plans/amendments/seats-claude-open-egress-renewal-20261124.md).
Registering the Claude allowlist removes the exception from the matrix. The separate W1
grant cutoff above still applies.

Grok's tool probe (`phase-loop seat-window probe-tools --vendor grok`) has two bases,
and each row reports its `basis`. A build whose `--help` advertises `--list-tools` is
listed; no installed build does, 1.0.89 included. Any other build needs a frozen surface
measured for its exact binary digest and route argv digest, from the shipped catalog or a
host-local record, and that basis holds only inside the `grok_seat_context.v1` launch
context: a fresh seat home that holds, besides the projection, one harness-written
`.grok/config.toml` with pinned bytes, mounted read-only from a sealed descriptor (a local
entry for the measurement model, and the client's remote catalog fetch switched off;
contract erratum 8), with none of the other pinned policy and discovery inputs in the
seat's view, the allow-listed environment, no managed grok configuration
and no Claude Code managed settings in the seat's view, no tool-discovery path visible in
the reviewed tree, vendor-only `grok-review` egress and
the launch-owner review composition. The board review leg (the `sealed`, `staged` and
`review` forms) is wired to that context. The `staged` form is ineligible at use under that
context (its tools can write the home), so a `staged` leg on a frozen-basis receipt is
refused before it launches; it can still be measured. A grok leg on a frozen-basis receipt runs in the
`grok-review` proxy-only namespace its leg holds, and is checked after composition against
that namespace and proxy. There is no fallback to a broader namespace. Until the
owner-gated measurement has run, every grok route stays `grok_tool_surface_unverified`.
Each new grok binary digest fails closed until it is measured, and each measurement needs
an owner grant
(`plans/artifacts/grok-tool-surface-contract-v1.md` §6). The measurement is
`phase-loop seat-window measure-tools --vendor grok`, run on the measuring host by the
contract's §5.10 procedure: a binding `--rehearse` stage first runs the pilot's launch
under a zero-budget proxy, a durable grant ledger caps the counted requests (one per
launch, at most 7 per grant), and only `--aggregate` writes the host-local record.

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
account, so its record has no peer observation; two-account coverage belongs to
later `done-team` validation. Public account labels are opaque.
Reviews retain the T3 fallback under OD-10; offline checks do not close W1.
Expired exceptions cannot support a passing window. Renewal requires a new
owner record and matrix update; rerunning a command does not extend an expiry.
Qualification retains reducer observation, egress, leg-exec and staged-read receipts
privately. The owner summary is private-only and is neither selected by verification nor
exported. Offline verification checks board input, delivered-turn and measurement digest
bindings. Installed-provider and attended host validation remain required before any
candidate status changes.
