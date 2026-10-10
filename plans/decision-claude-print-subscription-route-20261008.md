# Decision note — subscription-proven `claude -p` route for Claude panel seats

**Date:** 2026-10-08
**Tracking:** Consiliency/agent-harness#1391
**Decided by:** the maintainer (graduated route: TUI → `claude -p` → transport seam → Agent SDK;
this note is Stage 1)
**Decision:** **A non-native Claude panel seat, and the president's Fable rung off Claude Code,
may run as headless `claude -p` — but only on in-band-proven subscription OAuth.** The PTY TUI
adapter stays as an opt-in fallback. API keys, the Agent SDK, direct HTTP and gateways stay
excluded.
**Status:** OPEN — in force once this record is merged to `main`.

## 1. Premise correction

The "never `claude -p`" statements rest on the premise that Anthropic was deprecating
subscription use of `claude -p` (`docs/research/model-routing-v2-integration.md`). That premise
no longer holds:

- Anthropic paused the deprecation on 2026-06-15.
- On 2026-10-07 its help-center article 15036540 ("Use the Claude Agent SDK with your Claude
  plan") reaffirmed that the Agent SDK and `claude -p` still draw on subscription limits.
- Local probe, Claude Code 2.1.293: `claude -p --output-format stream-json` emitted `system/init`
  with `apiKeySource: "none"` (subscription OAuth).
- Live smoke through the runtime on dev0: seat `OK`, `claude_route=print`,
  `claude_api_key_source=none`.

## 2. The ruling

For non-native Claude seats and the president Fable rung, the sentence "No direct `claude -p`" in
EC-REVIEWTRUTH-16 (V10 @ `9eb77a3d`) is superseded by:

- The seat may run as `claude -p --output-format stream-json` **only on proven subscription
  OAuth**: a `claude auth status` preflight, `system/init.apiKeySource == "none"` asserted
  in-band, never `--bare`, an env-scrubbed launch, and `--no-session-persistence`.
- The TUI stays as the opt-in fallback. `PHASE_LOOP_PANEL_CLAUDE_ROUTE` selects the route:
  `print` (default) or `tui`. Any other value fails as `panel_claude_route_invalid`; there is no
  silent fallback.
- Print-route failures are typed: `claude_print_subscription_unproven`,
  `claude_print_auth_drift`, `claude_print_stalled`.

## 3. What this amends, by ID

The goals are not restated here; their text stays where it is.

| ID | Effect of this ruling |
|---|---|
| EC-REVIEWTRUTH-16 | The `claude -p` sentence only. Everything else in the goal is unchanged. |
| EC-REVIEWTRUTH-18 | "TUI adapter" is read as "the subscription-proven Claude CLI adapter" (print by default, TUI fallback). Its no-API-key / SDK / direct-HTTP / gateway / alternate-endpoint clause **stays in force**. The Agent SDK is **not** admitted. |
| EC-PRESROUTE-2 | The Fable rung's default route off Claude Code is the brokered print session; `tui` selects the self-PTY session. |
| EC-PANEL-6 | Its route list includes the print route. |
| IF-0-PNLCLAUDE-1 | "Never API-key auth" stays. "Never `claude -p`" becomes the rule in section 2. `panel-claude.txt` is the TUI route's output channel; the print route returns the review in the stream-json `result` event. |
| EC-REVIEWTRUTH-14 | Unchanged. Native fill under Claude Code is not affected. |

## 4. EC-REVIEWTRUTH-15 ratification statement

No seat's tool posture widens, and no execution capability is added:

- Brokered seats: zero tools, as before.
- Direct seats: `Read,Write` narrows to `Read` only.
- Jailed, capture and research seats: unchanged, on the TUI.

The ratification is the maintainer merging this record to `main`. It must be an ancestor of the
first parent of the Stage 1b landing merge.

## 5. Relation to v10 and v11

v10 is not edited by this ruling. v11 (Consiliency/agent-harness#1394) is asked to cite this
record on the carried IDs: "as defined in V10 as amended by the 2026-10-08 `claude -p` ruling".

## 6. Open questions

Tracked on Consiliency/agent-harness#1391.
