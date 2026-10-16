# Proposed decision — subscription-proven Claude Agent SDK transport (Stage 3)

**Date:** 2026-10-15  
**Tracking:** Consiliency/agent-harness#1391  
**Status:** PROPOSED. This document records a candidate amendment, not a ratified ruling.  
**Predecessor:** [Stage 1 ruling and Stage 2 note](decision-claude-print-subscription-route-20261008.md).  
**Implementation proposal:** [Stage 3a detailed plan](detailed-claude-sdk-runner-20261015.md).

## 1. Evidence and scope

Anthropic's [subscription guidance](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan),
checked on 2026-10-15, continues to permit SDK and print usage against subscription
limits. It also describes a separate API-credit offering. Neither a successful
request nor a cost estimate proves which account pool was charged.

The [SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) still contains a
restriction on third-party products offering Claude subscription login without
prior approval. This proposal covers an operator driving their own authenticated
Claude Code installation. It does not establish permission to offer subscription
authentication to customers or resolve that documentation discrepancy.

The official Python SDK controls a local Claude Code subprocess. The proposed
exception is for that SDK with an explicitly selected installed CLI; it does not
admit the Anthropic Messages client, a custom inference loop, or a hosted agent.

Research baseline: agent-harness `0b8444e820aba08a27e68cb1ad0d2c9a0efe2d92`.
SDK input: [v0.2.167](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.167),
released 2026-10-14, commit `c10b52c674e5c709c7263544b38e8a5dad10e01d`.
These are inspected inputs, not constraints on future implementation history.

## 2. Proposed amendment by ID

The goal definitions stay in their source roadmaps. This record changes only the
following transport restrictions and preserves the remaining requirements.

| Reference | Proposed effect |
|---|---|
| EC-REVIEWTRUTH-18 | Add a narrow exception to its SDK exclusion for the official Claude Agent SDK driving the installed local Claude Code CLI with the conditions in section 3. Native-host deferral and verdict binding still apply. |
| EC-REVIEWTRUTH-16; EC-REVIEWTRUTH-14 | Preserve the capability and native-fill boundaries referenced by these IDs. SDK selection grants no additional review capability. |
| EC-REVIEWTRUTH-15 | Retain ratification before a changed transport is activated. This draft and a passing test suite are not ratification. |
| IF-0-DFCHCONTRACT-1 | Permit the additional runner route literal `claude_sdk` in the existing metadata envelope. Field names, route statuses, auth postures and billing postures stay unchanged. |
| IF-0-DFCHROUTE-1; IF-0-DFCHDEFAULT-1 | Stage 3a adds explicit `sdk` / `claude_sdk` selection only. Existing default selection and CI explicit-selection requirements remain in force. Default promotion requires a later qualified amendment. |
| IF-0-DFCHTELEMETRY-1 | Report SDK execution as `claude_sdk`, including its use of the local CLI. Never disguise it as Channel or Agent View. Keep their existing no-hidden-print guard. |

The current frozen route statement is
`phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/harness-capability-matrix.md:226-231`:

> Route is limited to `claude_channel`, `claude_agent_view`, or `claude_print`.

This proposal adds exactly one route literal, `claude_sdk`. It adds no status,
auth-posture or billing-posture literal. The existing envelope remains
`{route, session_id, event_id, status, text, artifacts, auth_posture, billing_posture, trust_state, permission_state, warnings, evidence_refs}`.

## 3. Conditions on the SDK exception

1. **Executable identity.** Resolve the operator's installed `claude` to an absolute
   executable path before connecting, record its version as metadata, and pass it
   as `ClaudeAgentOptions.cli_path`. Missing or unsupported CLI capability refuses
   the route. Never fall through to the SDK's bundled CLI discovery.
2. **Subscription provenance.** Retain the caller-credential rejection and the
   login-backed subscription proof used by `launcher.run_auth_preflight` and
   `seat_credentials.login_subscription_proven`. Probe the credential context the
   SDK child will actually use as well; an unrelated seat's successful auth probe
   cannot establish that child's identity. Retain the CLI's own credential loading;
   do not copy a token into SDK options, argv or evidence.
3. **Process environment.** Start the SDK helper with an environment filtered by
   `scrub_subscription_env`, before importing or connecting the SDK. Remove inherited
   endpoint, API-key, helper and alternate-provider configuration through that shared
   filter. Do not mutate the threaded runner's `os.environ`. SDK `options.env` is an
   overlay, not an environment replacement, including for the SDK version probe.
4. **In-band evidence.** Require a `SystemMessage` with subtype `init` and
   `data.apiKeySource == "none"` before accepting output. Refuse missing or
   conflicting init evidence. Authentication, billing and organization-denial retry
   events interrupt and close the session and fail the run. Never request `--bare`.
5. **Capabilities.** Carry the selected model, effort, allowed/disallowed tools,
   generated settings, plugin, agents, MCP configuration, context, closeout schema
   and explicit approval posture across the adapter boundary. Do not inherit an
   SDK default that widens them. No fallback model or automatic transport fallback.
6. **Lifecycle.** Keep lease authority, process ownership, cancellation, descendant
   cleanup, heartbeat and stall detection in the runner's existing launch path.
   Only real SDK messages represent agent progress; synthetic keepalives must not
   prevent stall classification. Terminal success requires a successful SDK result
   and the existing action-specific output/closeout validation.
7. **Evidence limits.** Keep raw transcripts and completion content out of route
   metadata. Use `unknown` billing posture until provenance is checked, and
   `subscription_included` only with subscription evidence. That posture describes
   the authenticated route; it is not an account-ledger assertion. Keep the existing
   maintainer billing observation from agent-harness#1391; do not reopen it merely
   because the SDK reports a USD estimate.

## 4. First implementation and preserved boundaries

Stage 3a is an optional SDK installation extra and an explicit runner route for
solo authoring, execution and repair. Reject runner `review`, `subagent` and
`agent_team` SDK requests before launch. The helper is a trusted executor child;
it is not an admitted review-seat launch profile.

`PHASE_LOOP_PANEL_CLAUDE_ROUTE=sdk` continues to return
`panel_claude_transport_not_admitted`. Panel seats and the president's Claude rung
keep their current selector behavior. Native fill is unchanged. Activating SDK
review seats needs its own ownership, launch-profile and capability evidence.

PANELSPLIT/PANEL retain ownership of the jailed-seat move, the transport module
extraction and `_exec_claude_tui_leg` rename. This draft neither resolves nor
merges agent-harness#1568 or agent-harness#1583. SDK runner work has no dependency
on those PRs because it does not modify their panel-owned files.

Keep Channel, Agent View, print and the panel TUI fallback available. After the
explicit SDK route is qualified, a separate bounded promotion change can make it
the runner default and correct the runner's unconditional print billing label.
That correction must add actual print-route provenance enforcement; replacing
`usage_credit` with `subscription_included` solely by route name is insufficient.

## 5. Ratification and rollout order

1. Review this record and the implementation plan through the repository's
   governed review process. Bind findings to the reviewed artifact bytes; an
   understrength board cannot provide missing independent evidence.
2. Maintainer ratification and landing of this record precede SDK activation,
   consistently with EC-REVIEWTRUTH-15. Preserve the earlier ruling as history.
   Update v11's EC-REVIEWTRUTH-18 citation to name both records using the repository's
   roadmap amendment/seal process; do not rewrite frozen v10.
3. Implement and verify Stage 3a, including installed-package and credential-free
   subprocess tests, followed by a disposable live subscription qualification.
4. Consider default promotion and print billing correction on that evidence.

No implementation, CLI qualification, board approval, ratification or billing
measurement is claimed by this proposed record.
