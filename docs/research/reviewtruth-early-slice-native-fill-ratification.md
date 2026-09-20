# REVIEWTRUTH early slice — native claude seat fill: maintainer ratification record

- record kind: disposition (EC-REVIEWTRUTH-15 form: a committed document whose commit must be an ancestor of the landing commit's first parent, cited by full SHA in the landing commit message; the landing is a two-parent merge)
- scope: the EARLY SLICE of v10 Phase 7 REVIEWTRUTH described in `plans/detailed-native-claude-seat-fill-396-20260920-1030.md` as landed on `main` by Consiliency/agent-harness#918 (the plan PR lands BEFORE this record — required by the stated merge order, not asserted as already done; cite it by that PR, never by a branch SHA) — EC-REVIEWTRUTH-14 ("Part of"; its EC-4 clause stays with the phase)
- issues: Consiliency/agent-harness#396 (the ruling), Consiliency/agent-harness#636 (the prose contradiction), Consiliency/agent-harness#405 (implementation tracker; stays open), Consiliency/agent-harness#906 (consumer: the train review)
- ratified by: the maintainer (ViperJuice). **The binding fact is git ancestry alone:** ancestry proves ORDERING (ratified-before), which is what EC-REVIEWTRUTH-15 requires of a record; this record is bound to PR-2 iff the commit that lands it on `main` is an ancestor of PR-2's first parent (`git merge-base --is-ancestor <this record's main commit> <PR-2 landing>^1`) and PR-2's two-parent landing commit cites that `main` commit by full SHA. The narrative context — the ruling restated as "use Claude native capabilities, not the TUI adapter", the choice of an early slice over running the phase in order, the note on Consiliency/agent-harness#396 — is decorative and not checkable from a trusted clone; nothing here relies on it.

## The ratified design (stated positively, per EC-REVIEWTRUTH-15 obligation (a))

1. Under Claude Code, the claude review seat — every claude model, TUI-policy models included — is filled by the driving session's native sub-agent. The runtime defers the seat as `UNAVAILABLE/under_claude_code` carrying a `NativeAgentLegRequest`, and counts the seat only once a fill whose verdict is bound to the exact staged artifact, resolved brief, board composition and seat has been supplied back (the emit → fill → invoke protocol).
2. **Capability posture: KEEP READ-ONLY.** The native fill runs in the driving session under the review posture in force today — read-only review of the staged bundle; no execution capability against the real tree; no new directory, remote, network or tool authority for any review seat. This record does NOT decide the agent-harness#398 leg-capability design (EC-REVIEWTRUTH-15's lane D question); it binds only that this slice encodes no posture change. A later posture change requires a new ancestor record.
3. Non-native hosts (codex, gemini, opencode) keep the self-PTY TUI adapter route for the claude seat, byte-neutral. No `claude -p`, SDK, API-key or alternate-endpoint route is introduced anywhere; a fill is data from the first-party session, never a launch.
4. The phase's assumption-probe CLASSIFIER (`roadmap_assumptions._classify_reviewtruth_transition`) and the flattener (`legible_evidence._flatten_reviewtruth_observation`) stay byte-identical (the observation function feeding them is what changes); an incomplete observation is typed and never a pass, a sealed sidecar or a classification.

## Gate waiver (scoped)

This slice executes ahead of the phase's recorded SCHED/HARDEN ordering gates (the 2026-08-19/20 gate notes on Consiliency/agent-harness#396; the waiver itself is dated 2026-09-20 in the header). The waiver covers this slice only: PR-0 (this record), PR-1 (RED tests, zero production change, gated by `PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`), PR-2 (implementation, two-parent landing citing this record). The remainder of REVIEWTRUTH — including EC-REVIEWTRUTH-1/-4's delivery classifier (SL-4 `gate_posture.py`), SL-0's full capability record and SL-1's frozen RED set — stays behind its gates.

## Which commit binds PR-2

This record binds by the commit that lands it on `main` (a two-parent merge of the PR that carries this file), not by any branch head. PR-2's landing commit message cites that `main` commit by full SHA; the ordering is plan (Consiliency/agent-harness#918) → this record → the RED test lane (Consiliency/agent-harness#920) → PR-2.

## Conformance obligation (EC-REVIEWTRUTH-15 obligation (b))

PR-2's merged implementation must match items 1–4 above. One falsifier arm per item, each checkable from the landed diff:

1. Item 1 — a claude seat under Claude Code that does not defer as `under_claude_code` with a `NativeAgentLegRequest`, or a fill counted as usable without the artifact, brief, composition and seat binding, or without a conforming terminal verdict.
2. Item 2 — any review-seat launch flag, directory, remote, network or tool authority grant, or route that widens the read-only review posture for any seat.
3. Item 3 — any change to the non-native hosts' claude-seat route (the self-PTY adapter, its trust gate, its scrubbing) or any `claude -p` / SDK / API-key / alternate-endpoint route.
4. Item 4 — any byte of `roadmap_assumptions._classify_reviewtruth_transition` or `legible_evidence._flatten_reviewtruth_observation` changed, or any consumer that turns an incomplete observation into a pass, a sealed sidecar or a classification.
