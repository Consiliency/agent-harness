# REVIEWTRUTH early slice — native claude seat fill: maintainer ratification record

- record kind: disposition (EC-REVIEWTRUTH-15 form: a committed document whose commit must be an ancestor of the landing commit's first parent, cited by full SHA in the landing commit message; the landing is a two-parent merge)
- scope: the EARLY SLICE of v10 Phase 7 REVIEWTRUTH described in `plans/detailed-native-claude-seat-fill-396-20260920-1030.md` (Consiliency/agent-harness#918, ratified plan head `7946d7a5`) — EC-REVIEWTRUTH-14 ("Part of"; its EC-4 clause stays with the phase)
- issues: Consiliency/agent-harness#396 (the ruling), Consiliency/agent-harness#636 (the prose contradiction), Consiliency/agent-harness#405 (implementation tracker; stays open), Consiliency/agent-harness#906 (consumer: the train review)
- ratified by: the maintainer (ViperJuice), 2026-09-20, in the driving Claude Code session that authored #918, restating the standing ruling ("use Claude native capabilities, not the TUI adapter") and choosing "Ratify an early REVIEWTRUTH slice" over running the phase in order; recorded the same day on Consiliency/agent-harness#396

## The ratified design (stated positively, per EC-REVIEWTRUTH-15 obligation (a))

1. Under Claude Code, the claude review seat — every claude model, TUI-policy models included — is filled by the driving session's native sub-agent. The runtime defers the seat as `UNAVAILABLE/under_claude_code` carrying a `NativeAgentLegRequest`, and counts the seat only once a fill whose verdict is bound to the exact staged artifact, resolved brief, board composition and seat has been supplied back (the emit → fill → invoke protocol).
2. **Capability posture: KEEP READ-ONLY.** The native fill runs in the driving session under the review posture in force today — read-only review of the staged bundle; no execution capability against the real tree; no new directory, remote, network or tool authority for any review seat. This record does NOT decide the agent-harness#398 leg-capability design (EC-REVIEWTRUTH-15's lane D question); it binds only that this slice encodes no posture change. A later posture change requires a new ancestor record.
3. Non-native hosts (codex, gemini, opencode) keep the self-PTY TUI adapter route for the claude seat, byte-neutral. No `claude -p`, SDK, API-key or alternate-endpoint route is introduced anywhere; a fill is data from the first-party session, never a launch.
4. The phase's assumption probe (`roadmap_assumptions._classify_reviewtruth_transition`) and its flattener stay byte-identical; an incomplete observation is typed and never a pass, a sealed sidecar or a classification.

## Gate waiver (scoped)

This slice executes ahead of the phase's recorded SCHED/HARDEN ordering gates (the 2026-08-19/20 gate notes on Consiliency/agent-harness#396; the waiver itself is dated 2026-09-20 in the header). The waiver covers this slice only: PR-0 (this record), PR-1 (RED tests, zero production change, gated by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`), PR-2 (implementation, two-parent landing citing this record). The remainder of REVIEWTRUTH — including EC-REVIEWTRUTH-1/-4's delivery classifier (SL-4 `gate_posture.py`), SL-0's full capability record and SL-1's frozen RED set — stays behind its gates.

## Conformance obligation (EC-REVIEWTRUTH-15 obligation (b))

PR-2's merged implementation must match items 1–4 above. A reviewer may falsify this record by finding, in the landed diff, any review-seat launch flag, authority grant or route that widens the read-only posture, or any path that counts an unbound fill.
