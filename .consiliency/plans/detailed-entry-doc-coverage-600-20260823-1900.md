# Detailed plan: close the entry-doc check's two coverage gaps (Consiliency/agent-harness#600)

## Task

A stale install pin (`--ref v0.1.5`, six minors behind) reached `main` in `docs/TEAM-ONBOARDING.md` — the file we hand new teams — and the entry-doc check could not see it. Close both reasons it was invisible.

## Research summary

Read `entry_doc_check.py` and `test_entry_doc_check.py` at `eb1e410b`.

**Gap 1 — flag-form pins are unmatched.** Arm 2 has two regexes: `_GIT_REF_PIN_RE` (`github.com/owner/repo@ref`) and `_URL_TAG_PIN_RE` (`/releases/tag/`, `/tree/`, `/archive/refs/tags/`). The second exists precisely because *"a different GRAMMAR for one clock, not a different clock"* — the same reasoning applies to `--ref vX` and `AGENT_HARNESS_REF=vX`, which are **the installer's own documented interface** and therefore the spelling most likely to appear in install docs.

**Gap 2 — the onboarding docs are not in `ENTRY_DOCS`.** The tuple holds six package/repo front doors; `docs/TEAM-ONBOARDING.md` and `docs/outside-worker-quickstart.md` are entry points by function but not package long-descriptions.

**The sequencing concern in Consiliency/agent-harness#600 is softer than it states, and this is the key finding.** That issue says adding non-package docs "may need the two roles separated first." Checked: `check_entry_doc_coverage` computes `covered = set(entry_docs)` and flags any package README **not** in it — a one-directional subset test. `test_entry_doc_check.py:186` asserts the same direction (`assertLessEqual(declared, set(ENTRY_DOCS))`). **There is no inverse assertion**, so growing the tuple keeps both green.

So the role conflation is a **legibility** defect, not a correctness blocker. That means the two changes are independent and the doc-set widening is cheap. It also means the separation is worth doing anyway — for intent, and to guard a future tightening (someone adding "every entry doc must be a package long-description" would break on day one).

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/entry_doc_check.py` (modify)

- `_FLAG_REF_PIN_RE` — **add** — match `--ref <ref>` and `AGENT_HARNESS_REF=<ref>`, reusing the existing ref character class. Same clock, third grammar; the module comment on `_URL_TAG_PIN_RE` already argues this case.
- `check_pin_freshness` — **modify** — scan the new regex alongside the existing two, routing hits through the **same** release-namespace comparison and the **same** placeholder grammar. No second notion of freshness.
- `ENTRY_DOCS` — **modify** — add `docs/TEAM-ONBOARDING.md`, `docs/outside-worker-quickstart.md`.
- `PACKAGE_LONG_DESCRIPTION_DOCS` — **add** — the six existing package/repo front doors, as their own named tuple.
- `ENTRY_DOCS` — **modify** — define as `PACKAGE_LONG_DESCRIPTION_DOCS + ONBOARDING_DOCS` so the two roles are visible in the source rather than inferred.
- `check_entry_doc_coverage` — **modify** — reconcile against `PACKAGE_LONG_DESCRIPTION_DOCS`, not the union. Behaviour is identical today (subset test over a superset); it stops being accidental.

### `phase-loop-runtime/tests/test_entry_doc_check.py` (modify)

- `test_flag_form_pin_stale_is_caught` — **add** — `--ref v0.1.5` against a release namespace at `v0.7.13` produces a `stale_pin` finding. **This is the Consiliency/agent-harness#600 regression test**: it must fail against today's code.
- `test_flag_form_pin_placeholder_is_silent` — **add** — `--ref vX.Y.Z` and `--ref <TAG>` produce nothing. Guards the live `TEAM-ONBOARDING.md`, which uses the metavariable.
- `test_env_form_pin_stale_is_caught` — **add** — `AGENT_HARNESS_REF=v0.1.5` likewise.
- `test_flag_form_pin_ignores_non_release_refs` — **add** — `--ref main` / `--ref HEAD` are not release claims and must stay silent.
- `test_coverage_reconciles_against_package_docs_only` — **add** — a package README absent from `PACKAGE_LONG_DESCRIPTION_DOCS` is still flagged even when the onboarding docs are present, pinning that the split did not weaken the arm.
- Line 186 subset assertion — **modify** — retarget to `PACKAGE_LONG_DESCRIPTION_DOCS`, which is what it actually means.

## Documentation impact

- `CHANGELOG.md` — **modify** — public-surface change (the check now fails builds it previously passed). The docs-audit gate blocks a public-surface change with no entry, so this is required, not optional.
- `docs/TEAM-ONBOARDING.md` — **none** — already uses `--ref vX.Y.Z` since Consiliency/agent-harness#602. It becomes the positive control: it must stay green.

## Dependencies & order

1. Flag-form regex + `check_pin_freshness` first, with its tests. Independently valuable and carries the real defect.
2. `ENTRY_DOCS` split second. Ordering matters: doing (2) first would widen the doc set **before** arm 2 can see flag pins, so the newly-covered docs would be scanned by a check still blind to the thing that made them worth covering.
3. Run against the live repo before pushing — widening the doc set can surface pre-existing findings in the newly-covered files, which must be triaged as real or suppressed **deliberately**, never by narrowing the change.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest tests/test_entry_doc_check.py -q
PYTHONPATH=src python -m phase_loop_runtime.entry_doc_check          # live repo, must be OK
PYTHONPATH=src python -m phase_loop_runtime.entry_doc_check --file docs/TEAM-ONBOARDING.md
```

Mutation checks, each must fail **exactly** its claiming test:

- Drop `_FLAG_REF_PIN_RE` from the scan → `test_flag_form_pin_stale_is_caught` fails.
- Point the coverage arm back at the union → `test_coverage_reconciles_against_package_docs_only` fails.
- Restore `--ref v0.1.5` in a scratch copy of `TEAM-ONBOARDING.md` → the live run goes red. **This is the whole point**: it is the exact string that shipped, and it must now be catchable.

## Acceptance criteria

- [ ] `--ref v0.1.5` in any `ENTRY_DOCS` file produces a `stale_pin` finding; verified by restoring the string that actually shipped.
- [ ] `--ref vX.Y.Z` and `--ref <TAG>` produce no finding — the live `TEAM-ONBOARDING.md` stays green.
- [ ] `AGENT_HARNESS_REF=v0.1.5` is caught; `--ref main` is not.
- [ ] `docs/TEAM-ONBOARDING.md` and `docs/outside-worker-quickstart.md` are scanned by all arms.
- [ ] A package long-description missing from `PACKAGE_LONG_DESCRIPTION_DOCS` is still flagged, with the onboarding docs present.
- [ ] Each mutation above fails exactly its claiming test and nothing else.

## Execution Policy

- execute: effort=medium, reason=two regexes and a tuple split, but the placeholder-grammar interaction and pre-existing findings in newly-covered docs need care.

## Roadmap ownership

Checked before planning. `entry_doc_check.py` appears in **no** phase's `Key files` in `specs/phase-plans-v10.md` — unowned, no authorization bar, no conflict with the concurrent agent (on `codex/v10-conform-plan-repair`, touching `conformance/`).
