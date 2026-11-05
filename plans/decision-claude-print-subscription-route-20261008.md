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
## 4b. OD-3a: the jailed Claude transports, proposed 2026-11-04

**Status:** CANDIDATE — effective only upon the maintainer's merge of this section to `main`
after review, in its own reviewed PR that carries no other change (OD-3a, G1). Sections 1 to 8
above stay as written; this section amends §4a and §6 prospectively, for the scope below only.
Roadmap: `specs/phase-plans-seats-v1.md` (SEATS, agent-harness#1820), phase CLAUDE.

1. **Scope.** The existing tooled/pointer Claude seat inside its per-seat jail (§4a item 1).
   Capture and research seats, brokered and direct seats, and the president's Fable rung keep
   §2, §4 and §4a unchanged.
2. **Selection.** `PHASE_LOOP_PANEL_CLAUDE_ROUTE` selects `tui`, `print` or `sdk` for the jailed
   seat, through one seam (`claude_seat_transport`, IF-0-CLAUDE-1). `print` and `sdk` are
   selectable once their transport is admitted; `sdk` is admitted only in a later landing that
   cites this section and edits no record. A refused value launches nothing and never falls
   back. The shipped jailed default stays `tui` (§4a item 2) until an OD-3b section records a
   default and a separate landing ships it.
3. **The bake-off.** This section authorises the W0 bake-off of EC-CLAUDE-5 on the jailed seat:
   `print`, `sdk` and the T3 Code SDK-route control, under the phase plan's run plan, with its
   records landed in a reviewed PR.
4. **TUI last.** "TUI last" is operator selection only. No refusal and no terminal code of one
   transport launches another, the TUI included.
5. **Credential delivery.** Every jailed transport receives the credential only through the
   existing seat-token pipe (`CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`). For `sdk` the pipe is
   added to the inference spawn alone, by a repo-owned SDK transport, and the helper's copy is
   closed right after that spawn. The token never moves into the environment, the SDK options,
   argv or the seat home. Any other delivery for `sdk` needs its own ratified amendment.
6. **Login proof.** Every jailed transport launches only after the jailed login proof
   (IF-0-CLAUDE-4): caller-credential rejection, the subscription check on the same login
   context, and a single-use auth-status probe on the exact credential (agent-harness#1532).
7. **EC-REVIEWTRUTH-18 and Stage 3 §4.** EC-REVIEWTRUTH-18 is amended for the jailed seat's `sdk`
   route only: the official Agent SDK, running inside the jail with the system `claude` pinned
   as its CLI, is admitted for that route under the conditions in item 11. Stage 3 §4's review
   exclusion is lifted for that route only; every other SDK review use stays excluded, and the
   no-API-key, direct-HTTP, gateway and alternate-endpoint clause stays in force.
8. **Ratification order.** For every jailed-transport landing, EC-CLAUDE-4's content order
   replaces §4a item 9: a landing that admits a transport or changes the jailed default edits
   no decision record; its base tree already holds the section it cites, by that section's
   sha256; the PR that landed the section is merged; and an OD-3b value lands in its own PR
   before the change that ships it. `audit-order` checks this on every pull request. This is
   OD-3a's named departure from v11's EC-REVIEWTRUTH-15, which keeps the merge-ancestry form
   for every other landing.
9. **A default before its row window.** A default chosen by OD-3b may ship before its row
   window, provided the capabilities card says the default is chosen, runs on open egress until
   CLAUDENET exits, and awaits its row window (EC-CLAUDE-6).
10. **Open egress, a named exception.** The jailed Claude seat runs on open egress until
    CLAUDENET exits. This is a named exception for the jailed Claude seat only, under the
    roadmap's principle 3. Its expiry date is set in the switch landing (GL-6, OQ-8) and is
    renewable only by an owner record in the readiness matrix; an expired exception resolves
    degraded.
11. **Stage 3 §3 conditions on the jailed `sdk` route.** One row per condition.

    | Condition | Disposition on the jailed `sdk` route |
    |---|---|
    | 1. Executable identity | applies: the system `claude`, resolved to its native image, is the SDK `cli_path` at `/seat/bin/claude`; the SDK's bundled CLI is never projected or used |
    | 2. Subscription provenance | applies, through IF-0-CLAUDE-4 on the exact credential; personal Pro/Max scoping for `sdk` is put to the owner at G1 |
    | 3. Process environment | replaced by a named jail control: the jail's cleared environment and closed settings, plus `setting_sources=[]`, `strict_mcp_config=True` and the documented auto-memory disable |
    | 4. In-band evidence | applies: one `system/init` with `apiKeySource == "none"` for the run's session, read by the parent on the CLI's raw frames |
    | 5. Capabilities | replaced by a named jail control: parity with the jailed TUI command (tool universe, permission mode, settings, MCP and agents); neither the runner-CLI oracle nor the `allowed_tools` rule is imported |
    | 6. Lifecycle | replaced by a named jail control: the jailed seat's own seat-id lease, teardown and stall detection |
    | 7. Evidence limits | applies |

12. **Ownership (EC-CLAUDE-8).** Each responsibility has exactly one owner.

    | Responsibility | Owner |
    |---|---|
    | The jailed transport seam | SEATS CLAUDE |
    | Jailed-seat live qualification | SEATS CLAUDENET |
    | Jailed-default promotion | SEATS CLAUDE |
    | The mechanical module extraction of `panel_invoker.py` | v11 PANELSPLIT |

    §4a item 8's ownership of the jailed-seat move by PANELSPLIT/PANEL is superseded for the
    first three rows. A v11 roadmap amendment marks the affected EC-PANEL-6 items as consumed by
    EC-CLAUDE-1, EC-CLAUDE-4, EC-CLAUDE-6 and EC-CLAUDENET-1, and notes this section's departure
    from EC-REVIEWTRUTH-15.
13. **Experimental and unqualified.** Item 6 of §4a holds for every jailed transport until its
    row window: documentation and release notes call an explicit selection experimental and
    unqualified, and diagnostics alone never admit a result.
