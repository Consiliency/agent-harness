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

## 4a. Amendment to §4, proposed 2026-10-20: the jailed Claude seat

**Status:** CANDIDATE — effective only upon maintainer-authorized merge of this section to
`main` after review. Section 4 above is the Stage 1b record and stays as written. This section
amends only its jailed-seat bullet, prospectively. Implementation candidate:
Consiliency/agent-harness#1740.

1. **Scope.** Only the existing tooled/pointer Claude seat inside its per-seat jail
   (agent-harness#1132). Capture and research seats stay on the TUI as §4 says: a selected
   `print` still resolves to the TUI for them. Brokered and direct seats and the president's
   Fable rung keep §2 unchanged.
2. **Default.** An unset or blank `PHASE_LOOP_PANEL_CLAUDE_ROUTE` keeps the jailed seat on the
   TUI. The §2 `print` default does not extend to it.
3. **Explicit selection.** `print` selects the print transport for the jailed seat; `tui`
   selects the TUI. The jailed seat now reads the selector, which it previously ignored: `sdk`
   fails as `panel_claude_transport_not_admitted` (§6) and any other value as
   `panel_claude_route_invalid` (§2). A refused value launches nothing and never falls back.
4. **Posture and credential delivery.** This amendment adds selectable print transport
   availability for the jailed seat; it does not authorize additional seat privileges or a
   wider tool surface. Jailed print must reuse the jailed TUI command's tools, settings,
   jail, staged clone and teardown, with headless `-p`, stream-json output, the prompt on
   stdin and `--no-session-persistence`. This proposal explicitly retains the existing
   seat-token pipe for the bounded experimental route. It does not adopt the pipe replacement
   proposed under the Stage 1b plan's out-of-scope Follow-ons (:170–172). Ratifying this
   section would approve that retained mechanism for this scope; no maintainer approval is
   claimed here. The historical terms citation is not a determination of current external
   terms or legal compliance.
5. **Admission and refusal remain required.** In a normal explicitly selected experimental
   print review, only one successful `result` event with a conforming verdict may supply the
   review, and only when all existing session, subscription, result, exit and verdict
   predicates hold. Jailed print launches only after the login-store subscription check and
   the separate single-use auth jail on the exact selected credential. It asserts
   `system/init.apiKeySource == "none"` in-band and never uses `--bare`. No transcript,
   output file or assistant turn is salvaged. Failures stay typed. EC-HARDEN-6 applies
   unchanged; this record does not establish implementation compliance on either jailed route.
6. **Experimental and unqualified.** The reviewed evidence contains no admitted live result
   on the jailed print route. The bounded live diagnostics recorded so far ended fail-closed (`DEGRADED`,
   `claude_print_result_unproven`); their cause is not established. Documentation and release
   notes call the selection experimental and unqualified, never a supported or qualified review
   route. Diagnostic observations alone never admit a result, and diagnostic-only runs do
   not supply an admitted review. The explicitly selected normal experimental review route
   is distinct from diagnostic-only operation and remains subject to item 5. Opt-in neither
   establishes qualification nor waives the live evidence required by item 7.
7. **A later qualified claim** needs, under separate authorization, an admitted result on the
   exact head being qualified that meets the qualification checks in
   `docs/advisor-board-capabilities-card.md` (valid untruncated diagnostics, exact model match,
   the expected staged-path digest with a completed Read, and the session, subscription,
   result, exit and verdict requirements). Making print the jailed default needs a further
   ratified amendment.
8. **Ownership.** PANELSPLIT/PANEL keep the jailed-seat move
   ([Stage 3 record](decision-claude-sdk-subscription-route-20261015.md) §4): its
   qualification, default promotion and the transport module extraction. This section admits
   only the explicit experimental selection, as a bounded interim exception that PANEL may
   absorb, supersede or withdraw. It sets no landing order relative to PANELSPLIT.
9. **Ratification order.** Per EC-REVIEWTRUTH-15, this section must be an ancestor of the
   first parent of the two-parent non-fast-forward landing merge that activates jailed
   print, and that landing commit's message cites the record commit by full SHA. Carrying this section only on the implementation branch does
   not satisfy that.

## 5. Relation to v10 and v11

v10 is not edited by this ruling. v11 (Consiliency/agent-harness#1394) is asked to cite this
record on the carried IDs: "as defined in V10 as amended by the 2026-10-08 `claude -p` ruling".

## 6. Note, 2026-10-13: Stage 2 names `sdk`

Consiliency/agent-harness#1575 adds the transport seam (`tui | print | sdk`). `sdk` is now a named
transport that is not admitted, so selecting it fails as `panel_claude_transport_not_admitted`
instead of the `panel_claude_route_invalid` that §2 names for "any other value". The rule §2 sets
is unchanged: a refused value fails closed and never falls back. The Agent SDK stays out until
EC-REVIEWTRUTH-18 is amended to admit it (Stage 3).

## 7. Open questions

Tracked on Consiliency/agent-harness#1391.

## 8. Stage 3 companion ruling, 2026-10-16

[The Stage 3 record](decision-claude-sdk-subscription-route-20261015.md) becomes
effective upon its maintainer-authorized merge after review. It adds only the
bounded official-SDK exception and explicit solo-runner rollout defined there.
Its conditions supersede this record's SDK exclusion for that scope only;
the panel `sdk` selector remains refused. Until that ratification, section 6
continues to apply without an SDK exception.
