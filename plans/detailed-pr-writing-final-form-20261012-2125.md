# Detailed plan: PR descriptions grounded in the final implementation

## Task

Adapt Matt Pocock's PR-writing principles into the existing detailed and interactive
phase execution flows. Descriptions should explain the final behavior, cite observed
verification, identify useful edit locations and material rollback constraints, and
remain current from draft through readiness and subsequent pre-merge changes.

This is one bounded change; the repeated provider source edits implement the same
workflow contract. Greenfield/spec extraction, train narrative generation,
broker-owned description updates, title APIs, and publication recovery changes are
follow-ups, not acceptance requirements here. No new review or merge gate is added.

## Research summary

`skills-src/` owns authored instructions; `phase-loop-skills/` and the runtime's
`skills_bundle/` are generated. The bundle builder copies shared reference directories
from the first providing harness, and installation carries them to all four providers.
The human publication adapter already accepts `pr_body` and `commit_message`; the
broker derives titles from commit subjects. Interactive phase execution creates early
drafts, but its publication-mode actions currently omit description refresh.

The upstream skill is https://github.com/mattpocock/skills/blob/main/skills/engineering/pr/SKILL.md.
Astra supported adaptation; Opus recommended artifact-based evidence, preservation of
machine-readable content, and explicit adapter arguments. The owner subsequently
required final-form reassessment at readiness and before merge after material changes.

## Changes

### Authored execution skills (modify)

For each provider in `claude`, `codex`, `gemini`, and `opencode`, modify
`skills-src/<provider>/<provider>-execute-detailed/SKILL.md` and
`skills-src/<provider>/<provider>-execute-phase/SKILL.md`:

- Detailed publication reads the shared reference, explicitly passes `pr_body` and
  `commit_message`, composes before transaction preparation, and preserves body bytes
  on retry. Correct the obsolete `--fill` description; broker publication stays owned
  by the existing adapter.
- Interactive phase publication reads the same reference through the installed skill
  resolver. Draft text states pending work honestly. Refresh agent-owned title/body
  against the final PR diff and current evidence before readiness and after material
  implementation, verification, or comparison-base changes before merge.
- Use explicit titles and body files for interactive creation/editing, preserve human
  additions and machine-readable trailers, and apply the current publication mode
  before any external mutation. No agent edits runner/broker-owned descriptions.

### Shared writing reference (create)

`skills-src/claude/claude-execute-detailed/references/pr-writing.md` contains a concise,
provider-neutral contract: problem/result; final-diff file and symbol locations;
observed/redacted verification and its limits; affected consumers and reversibility;
optional explanatory visuals; downstream template precedence; immutable retry bodies.
Locations use the actual revision, distinguish deletion/base locations, and never claim
parser-derived seams or exhaustive impact without supporting evidence.

### Publication actions and behavior tests (modify)

- `phase-loop-runtime/src/phase_loop_runtime/publication_mode.py`: retain the closed
  vocabulary `PUBLICATION_MODES = ("none", "draft-only", "ready")` and existing
  precedence. Extend action text for agent-owned description edits under publishing
  modes; prohibit edits under `none` and errors.
- `phase-loop-runtime/tests/test_publication_mode_1392.py`: exercise description edit
  before readiness, draft-only updates without readiness, no edits under none/errors,
  edits after later implementation changes, and edit failure withholding readiness.
- `phase-loop-runtime/tests/test_skills_canon_parity.py`: verify the shared reference
  reaches installed detailed skills for every provider and phase consumers resolve it.

### Documentation, generated distributions, and plan metadata (modify)

- `docs/branch-and-publication-flow.md`: document description content, refresh timing,
  and ownership, including the unchanged runner boundary.
- Regenerate `phase-loop-skills/` and packaged
  `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/` with the existing scripts.
- Refresh `phase-loop-runtime/tests/data/launchspec_golden/launchspec_golden.json` only
  for the intentional injected instruction changes; verify other launch fields remain
  identical to the input baseline.
- Append and update this detailed plan's entry in `plans/manifest.json` through the
  typed manifest helpers. Handoffs, reflections, and verification evidence are local
  workflow outputs; they are not publication source files.

## Documentation impact

The publication-flow document and installed skills describe the new behavior. CLI
flags, configuration schema, broker contracts, and parser dependencies do not change.

## Dependencies & order

Write plan and handoff, register the plan, mark executing, edit all sources, regenerate
both bundles, refresh the intentional launch-instruction golden, verify, then close
out. Use the isolated feature worktree; the primary checkout's pre-existing
`.pmcp/logs/gateway.log` is not an artifact of this plan and must not be committed.

## Verification

Use the existing project interpreter with `PYTHONPATH=src:tests` from
`phase-loop-runtime/`:

1. `python scripts/regenerate_skills_bundle.py` and `python scripts/sync_skills_bundle.py`.
2. `python -m pytest -q tests/test_publication_mode_1392.py tests/test_skills_canon_parity.py tests/test_skills_bundle_drift.py tests/test_skill_install_body_expansion.py`.
3. Refresh the launch golden with `PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1 python -m pytest -q tests/test_launchspec_golden.py`, compare against the input baseline, and rerun without regeneration.
4. `python -m pytest -q tests/test_phase_loop_build_bundle.py tests/test_publishing.py tests/test_launchspec_golden.py`.
5. `git diff --check` and inspect the complete source/generated diff and owned paths.

Record commands/results through `verification_evidence.run_verification`. Review the
writing reference and provider publication sections for content and ownership; no live
GitHub mutation is needed to validate lifecycle ordering.

## Acceptance criteria

- [ ] All four installed providers receive and resolve the same shared writing reference (installation/parity tests).
- [ ] Detailed publication explicitly supplies body and meaningful commit subject, with no `--fill` claim and stable retry bytes (source review, publishing tests).
- [ ] PR guidance grounds locations in the final diff, reports observed verification, and preserves templates, goal IDs, trailers, and human additions (source review).
- [ ] Interactive descriptions refresh before readiness and after material later changes; edit failure never proceeds to readiness (publication-mode scratch tests).
- [ ] None/error modes cause no push/create/edit/ready; draft-only refreshes remain drafts; runner/broker ownership stays intact (mode tests, source review).
- [ ] Generated distributions have byte parity and only intended injected instructions change in launch goldens (parity/drift, golden comparison/tests, diff check).
