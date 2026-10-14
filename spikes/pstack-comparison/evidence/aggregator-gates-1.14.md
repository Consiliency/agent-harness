# Aggregator admission gates: before/after on the reflection backlog (REPORT 1.14/1.15)

Tracking: agent-harness#1321. Change under test: the aggregator prompt with eight admission
gates, a ladder level on every recommendation, and the rule→enforcer registry as input.

## Follow-up corrections (2026-10-14)

The measurements below describe the original prompt, not a rerun of the corrected
version. agent-harness#1588 now incorporates the durable-pattern and speculative-routing
refinements from agent-harness#1587. It also supplies opaque source identifiers in every
bundle entry and preserves the ladder and rejected themes in every final plan template.
The original Claude aggregator did not receive repo/branch identity; its convergence
classifications below therefore do not establish source independence. Skill-read evidence
for a different target is absent, not proof that it was skipped (agent-harness#1586).
Six regression cases failed before the source/template fixes; behavioral A/B replication
still belongs to REPORT 2.1.

## Method

- Corpus: `python3 -m phase_loop_runtime.reflection_corpus collect --min-reflections 2` over
  every harness skill root on 2026-10-13. 535 reflections scanned, 393 admitted, 571 KB.
  Ready skills: `execute-detailed` (171), `plan-detailed` (90), `plan-phase` (46),
  `execute-phase` (35), `phase-roadmap-builder` (9). `advisor-board` (1) was below the
  threshold.
- One frontier aggregator per ready skill, as the planner's per-skill fan-out does, each
  given only that skill's bundle section. Every run had read-only access to `skills-src/`
  for the already-covered gate.
- **Baseline**: the prompt on `main` (three gates, no registry). **Gated**: this PR's prompt,
  with `rule_enforcement.md` appended. Same bundles, same model.
- The raw plans quote other repositories' reflections and are not committed. This file has
  counts and paraphrased examples only.

## Result

| Skill | Prose recommendations | Mechanism candidates | Rejected themes |
|---|---|---|---|
| execute-detailed | 18 → 4 | 9 → 10 | 0 → 10 |
| plan-detailed | 16 → 10 | 3 → 3 | 0 → 6 |
| plan-phase | 13 → 7 | 10 → 11 | 0 → 5 |
| execute-phase | 11 → 3 | 4 → 4 | 0 → 5 |
| phase-roadmap-builder | 9 → 4 | 3 → 5 | 0 → 1 |
| **Total** | **67 → 28** | **29 → 33** | **0 → 27** |

Every gated prose recommendation states its ladder level. Baseline recommendations have none.

Rejections by gate: specificity 7, convergence 5, already-covered 5, durability 4,
decision-changing 3, existing-skill-first 2, skill-was-used 1.

## Examples (paraphrased)

- **Registry routing.** A recurring plan-phase theme, owned files missing a test companion,
  matched the `plan-phase.owned-files-complete` row (`unenforced/gap`, agent-harness#1355). It
  became a mechanism candidate citing the row instead of a second prose rule.
- **durability.** Host and shell quirks (interpreter aliases, remote quoting, temp-dir quota)
  were dropped as drifting with infrastructure.
- **convergence.** Themes from a single repo's campaign, including two byte-identical
  reflections from one branch, were held below the bar.
- **decision-changing.** "Keep structural plan validation distinct from execution
  verification" was rejected: every supporting reflection already complied.
- **already-covered.** "Do not report a pass before the run finishes" was rejected: the
  executor skill already forbids a pass without the sealed verification artifact.
- **existing-skill-first / skill-was-used.** Review-round discipline raised in executor
  reflections was routed to its real home (advisor-board), not added to the executor skill.

## Limits

- One run per arm and skill. Run-to-run variance is unmeasured, so a single skill's delta
  could be noise; the direction is consistent across all five skills. REPORT 2.1 (blinded
  A/B with replication) is the real test and is out of scope here.
- The plans were read, not applied. Fewer recommendations is the intended effect, but whether
  the 28 survivors improve agent behaviour is not measured.
- The registry covers two skills and seven rules, so most themes hit "no row" and were
  levelled by judgment.
- Filtering defects in the corpus collector can still hide recurrence before the gates
  see it: agent-harness#1370 (boilerplate stripping and corpus-wide dedup) and
  agent-harness#1371 (an issue reference drops a whole reflection). The convergence gate
  inherits both.
