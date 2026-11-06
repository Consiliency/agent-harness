# Seat window kit — IF-0-FIRSTSEAT-2

`seat-window qualify` implements the frozen I-15 production orchestration, but its
live W1 owner gate is deliberately closed. Until a reviewed source change records
owner approval, it returns `window_owner_approval_required` before preflight,
authentication, storage or any provider launch. Matrix, offline verification,
reviewed export and probe-tools are implemented; no fixture or source-checkout run
opens the live gate.

W1 is an attended owner window, not a source-checkout test. Do not execute it
until LA-1 host administration and managed release, LA-2 logins under each
account, and LA-3 attendance are recorded. Run sequentially on two distinct
team-host accounts and one standard host. All four vendors' availability and
subscription auth are preflighted under each account before board launch.
A composition refusal blocks that attempt for LA-2 remediation.

```
phase-loop seat-sandbox qualify
phase-loop seat-egress install
phase-loop seat-window probe-tools --vendor grok
phase-loop seat-window qualify --window W1 --monitoring-policy bounded
phase-loop seat-window verify --window W1
phase-loop seat-window export --window W1 --reviewed \
  --output plans/evidence/seat-qualification/W1.json
```

`seat_window.v1` holds the window, opaque context/account identifiers, host
class, all selected candidate row identifiers, parent-computed runtime/profile/
allowlist digests, board identity and admission, canonical Gemini review and
staged-read tool receipt, exec-record digest, co-seat disclosures, account
isolation observation, containment and observed egress measurements and their
digests. Missing, unavailable, stale or failed measurements cannot support
`done-local`. Static configuration reports are not observations.

Containment fields cover credential scope, refresh detection and planted project
settings, hooks, MCP servers and provider overrides. Egress fields cover allowed
and refused proxy requests and direct DNS/IP controls. Measurements run in each
context and must bind the installed qualification key as each leg ends.

Qualify and probe write only to private operator storage. Verify reads retained
records offline. Export alone may write reviewed, passing, closed-field metadata
here, after owner review. Records containing hostnames, usernames, absolute paths,
tokens or free-text observations are not public exports. A non-passing record
leaves a neutral `candidate` status and follows OD-10 privately.

No fixture receipt is live evidence. No W1 run or export has been performed.

After explicit owner approval, `qualify` performs preflight and attendance/host-readiness
checks, builds the nested input, runs help and either plugin validation or the
`plugin_json` fallback, then the tree/runtime controls. If the frozen definition
probe requires launch 4, each credentialed control runs exactly once; a no-write
`home` baseline is final and is not replayed. Measured, expired-copy and board
launches follow on the same qualification input. A composition refusal ends the
attempt. Otherwise containment is copied only from `reduce_containment`, and the
reducer's private observation and `owner-summary-W1-*.json` (including counted and
uncounted-home lookup totals) are retained separately. The attended workflow uses
`--attended`, `--host-class team|standard`
and reciprocal `--peer-record PATH` observations under two real accounts.
Never substitute a same-account file for that check.

The following describes the record and reduction contract for future collection.
Each context is retained as an exclusive 0600 `window-W1-*.json` file in the
operator's private `agent-harness/seat-records` state directory. For reduction,
the owner assembles reviewed private copies from all contexts in an owner-only
directory, including the referenced `leg-*.json`, `window-read-*.json` and
`window-observation-*.json` source receipts, then supplies one `--record PATH`
per context to `verify` and `export`. All records and sources must share that
0700 directory; each file must be 0600 and owned by the reducing operator.
With no `--record`, these commands select the local window records. Export also
requires `--reviewed --output plans/evidence/seat-qualification/W1.json`.
No incomplete record is exported, and a non-passing result exits nonzero.

The offline reducer requires two distinct operator IDs on the same team host
and a separate standard host. It checks unique opaque context/account labels,
qualification keys and context identities against retained source bindings,
receipt digests, complete candidate selection, canonical review and
staged-read observations, co-seat disclosures and each measurement separately.
Records expire after 30 days; named exceptions have their own earlier expiry.
Missing producer observations remain unavailable and leave the row `candidate`.
The verifier reads each retained source, reconciles its content with the window
measurements and staged-tree identity, and checks its digest. A digest-shaped
value or a passing checklist without its matching source cannot qualify a row.
The definition probe is separate from row qualification; a non-passing result
does not admit a Grok launch. No fixed version list supplies a passing receipt.
`probe-tools` reports separate `execute`, `workflow`, `review`, `sealed` and `staged` form results.
Use `--model` and `--effort` to select configured forms; defaults match the
runtime's default model and high effort. Installed-version measurements remain required.

The orchestration consumes the frozen lane-A and lane-D producer interfaces.
Offline fixture receipts exercise validation only and cannot qualify a host.
Missing producer interfaces, observations or source receipts leave the window
unqualified. No live W1 run or reviewed export has been performed.
