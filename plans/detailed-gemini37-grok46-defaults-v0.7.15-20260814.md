# Detailed plan: adopt Gemini 3.7 Flash and Grok 4.6 defaults for v0.7.15

## Task

After v0.7.14 is published, update Agent Harness executor and advisor-board defaults to Gemini 3.7 Flash and Grok 4.6, verify the complete model-routing contract, and prepare the narrow v0.7.15 release.

## Research summary

Attended provider evidence establishes the explicit target ids
`gemini-3.7-flash-{low,medium,high}` and `grok-4.6`. Do not use `grok models`:
the installed Grok 1.0.3 CLI has no metadata-only `models` subcommand and would
interpret that token as a prompt. Current post-v0.7.14 `origin/main` must be
audited for the remaining `gemini-3.6-flash` and `grok-4.5` defaults across
executor profiles, the four-seat advisor-board fixture, presets, registries,
executable leg defaults, documentation, and goldens. `render_agy_model` already
accepts versioned Flash ids generically, so no new model parser is required; the
change must preserve base-model storage plus effort-suffixed rendering.

The post-v0.7.14 baseline is required to contain
`phase-loop-runtime/tests/proofgate_bootstrap_verifier.py` and
`phase-loop-runtime/tests/test_tdd_chronology.py`; both are present on the
current upstream main lineage. Fail the baseline preflight rather than inventing
Proofgate work if either is absent after the v0.7.14 landing.

The deliberately unchanged cells are part of the contract: Gemini planning/review stays on `pro`; Gemini heavy stays `gemini-3.1-pro-preview`; Gemini worker stays `gemini-3.5-flash-high`; Gemini lite stays `gemini-3.5-flash-lite`; Grok regular/lite stay `grok-4.3`/`grok-build-0.1`. Only Gemini implementer/regular moves to 3.7, and only Grok default/heavy (therefore its action, class, review, and advisor routes) moves to 4.6.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/profiles.py` (modify)
- `GEMINI_IMPLEMENTER_MODEL` and `GEMINI_REGULAR_MODEL` — move the stable Flash default from 3.6 to 3.7. Preserve `GEMINI_PRO_ROUTED_MODEL = "pro"`, `GEMINI_HEAVY_MODEL = "gemini-3.1-pro-preview"`, `GEMINI_WORKER_MODEL = "gemini-3.5-flash-high"`, and `GEMINI_LITE_MODEL = "gemini-3.5-flash-lite"`.
- `GROK_DEFAULT_MODEL`/inherited `GROK_HEAVY_MODEL` — move the default/heavy/review/implementation route from 4.5 to 4.6. Preserve `GROK_REGULAR_MODEL = "grok-4.3"` and `GROK_LITE_MODEL = "grok-build-0.1"`.
- Model-routing comments — update the live `agy models` and Grok capability rationale without introducing new tier vocabulary.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `DEFAULT_LEG_MODELS` and Gemini base fallback — render `gemini-3.7-flash-high` for the board leg, use the base `gemini-3.7-flash` only before effort rendering, and use `grok-4.6` verbatim.
- Retain the same-line `# model-id-source:` markers on the concrete panel defaults and base fallback; this file is outside the source-audit registry allowlist.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/{composition.py,fixtures.py,presets.py,registries.py}` (modify)
- Default seats, valid model/harness pairs, and preset seats — replace the old
  defaults atomically so composition, resolution, and golden fixtures cannot
  disagree. Add `gemini-3.7-flash` and `grok-4.6` as the new default registry
  entries while retaining `gemini-3.6-flash` and `grok-4.5` as explicit legacy
  model ids for backward-compatible authored boards. Add tests proving the old
  ids remain explicitly resolvable but are no longer selected by defaults.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/{harness_mapping.py,schema.py,CONTRACTS.md}` (modify)
- Examples and capability prose — update version examples while preserving the existing generic Gemini suffix renderer and Grok max-to-high effort clamp.

### `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py` (modify)
- Gemini implementation capability notes — identify 3.7 Flash as the live regular implementation model and retain the documented high-effort ceiling.
- Retain the same-line `# model-id-source:` markers on capability-note strings; this file is outside the source-audit registry allowlist.

### `phase-loop-runtime/tests/` model-routing and advisor-board tests (modify)
- Update explicit old-default expectations in `test_phase_loop_execution_policy.py`, `test_phase_loop_launcher.py`, `test_model_tier_taxonomy.py`, `test_model_class_policy.py`, `test_grokexec.py`, `test_advisor_board_{backcompat,composition,golden,presets,registries,research}.py`, `test_panel_invoker_timeout_argv.py`, `test_panel_per_leg_model_66.py`, `test_grok_narrow_reject_231.py`, and `test_legible_review_repairs.py`.
- Add discriminating assertions for base `gemini-3.7-flash` plus `high` rendering exactly once, already-suffixed idempotence/conflict rejection, `grok-4.6` verbatim argv, and unchanged Grok regular/lite cells.
- `proofgate_bootstrap_verifier.py` — update `AUTHOR_MODEL` to `gemini-3.7-flash` because the verifier emits it as the governed author-model identity; run the protected chronology/Proofgate coverage that consumes that verifier rather than leaving a stale default in release evidence.
- Add a discriminating Proofgate assertion over the emitted candidate binding or
  evidence payload requiring `author_model == "gemini-3.7-flash"`; a test that
  checks only status, evidence kind, or decisiveness is not sufficient.

### `phase-loop-runtime/tests/data/launchspec_golden/launchspec_golden.json` (modify)
- Launch-spec golden — update the selected base and rendered Gemini defaults using the repository’s normal deterministic regeneration path, then review the diff. Do not hand-edit unrelated snapshots.

### `docs/advisor-board-capabilities-card.md`, `plans/design-model-tier-taxonomy.md`, and `CHANGELOG.md` (modify)
- Document the new four-seat defaults, rendered CLI ids, supported effort ceilings, unchanged lower-tier policy, and v0.7.15 release scope.
- Update the active tier-design table and liveness notes for Gemini regular 3.7 and Grok heavy 4.6. Do not rewrite historical v0.7.13 changelog entries or superseded plans/specifications merely because they record the former defaults.

### Release version and active authority surfaces (modify before exact-head verification)
- `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/src/phase_loop_runtime/__init__.py`, `phase-loop-runtime/uv.lock`, and `RELEASE_PIN` — bump together to 0.7.15/v0.7.15 after v0.7.14 is published, regenerate the lock, and require `uv lock --check`.
- Update the active v10 roadmap version assumption, mirrored probes/fixture/test,
  and validator-live digest graph from 0.7.14 to 0.7.15 using the same
  preservation rules as the v0.7.14 release: current/live pointers move;
  historical reviewed/predecessor/panel evidence stays byte-identical.
- Finalize these release surfaces before the focused/full/build/provider-smoke,
  CI, and advisor-board gates. Any later commit or automated documentation
  successor invalidates exact-head evidence and must rerun affected/full gates,
  CI, and the board before merge.

## Documentation impact

The capability card, active tier-design document, contracts/examples, changelog, and v0.7.15 release evidence must change because model ids are user-visible launch policy and exact review evidence. Historical plans/specifications and released changelog entries remain historical records; add the v0.7.15 changelog entry rather than retroactively editing v0.7.13.

## Dependencies & order

1. Block until v0.7.14 is published and Consiliency/agent-harness#432 is closed.
2. Capture metadata-only CLI evidence with `agy --version`, `agy --help`,
   `grok --version`, and `grok --help`, plus authoritative provider documentation
   for the requested ids. Do not invoke nonexistent discovery subcommands or
   treat help text as proof that an explicit model turn succeeds; never record
   OAuth tokens.
3. Create one implementation branch from the clean post-v0.7.14 `origin/main` OID; do not reuse a pre-release mainline that still reports an older package version.
4. Change profile and board source-of-truth values, then update all explicit fixtures, presets, registries, tests, goldens, docs, active tier design, governed author identity, synchronized release/lock surfaces, and active v10 version/digest graph. Run the model-id source audit to detect hidden duplicates.
5. Regenerate the launch-spec golden deterministically and review the narrow model-id diff before normal golden verification.
6. Run harmless explicit-model single-turn smokes for Gemini 3.7 Flash High and Grok 4.6 only after the code and metadata checks pass. Use isolated scratch directories and hard timeouts; record only executable/version, requested model id, exit status, and timing. Do not use default-model smokes, record response content, retain OAuth material, or send repository artifacts.
7. Run focused tests, complete suite, build, and the Gate A isolated-wheel consumer check.
8. Panel-review the exact fully versioned head across distinct vendors; reconcile dissent and rerun affected/full verification. Any head change restarts the exact-head CI/build/board gates.
9. Merge on green CI, publish signed v0.7.15 with explicit authorization, and verify registries/artifacts. Do not add an unreviewed release-version commit after approval.

## Verification

```bash
cd phase-loop-runtime
uv lock --check
PYTHONPATH=src:tests PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1 \
  python -m pytest -q tests/test_launchspec_golden.py
PYTHONPATH=src python -m pytest -q -p pytest_asyncio.plugin \
  tests/test_phase_loop_execution_policy.py \
  tests/test_phase_loop_launcher.py \
  tests/test_model_tier_taxonomy.py \
  tests/test_model_class_policy.py \
  tests/test_grokexec.py \
  tests/test_advisor_board_backcompat.py \
  tests/test_advisor_board_composition.py \
  tests/test_advisor_board_golden.py \
  tests/test_advisor_board_presets.py \
  tests/test_advisor_board_registries.py \
  tests/test_advisor_board_research.py \
  tests/test_panel_invoker_timeout_argv.py \
  tests/test_panel_per_leg_model_66.py \
  tests/test_grok_narrow_reject_231.py \
  tests/test_legible_review_repairs.py \
  tests/test_launchspec_golden.py \
  tests/test_tdd_chronology.py
PYTHONPATH=src python -m pytest -q -p pytest_asyncio.plugin
python scripts/check_model_id_sources.py
PYTHONPATH=src:tests python -m pytest -q tests/test_model_id_source_guard.py
PYTHONPATH=src:tests python -m pytest -q tests/test_launchspec_golden.py
git diff -- tests/data/launchspec_golden/launchspec_golden.json
git diff --check
bash scripts/gate_a_cleanroom.sh
cd ..
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .
python -m build --sdist --wheel --outdir /tmp/phase-loop-runtime-v0.7.15-dist phase-loop-runtime
git diff --check
```

`scripts/check_model_id_sources.py` tokenizes every Python file under `src/phase_loop_runtime`. Concrete IDs are allowed only in `profiles.py` and the advisor-board registry files (`composition.py`, `fixtures.py`, `presets.py`, `registries.py`, `resolver.py`), or on a source line with a trailing `# model-id-source:` marker. It excludes comments/docstrings and does not scan tests, JSON, or Markdown. Preserve the required markers rather than extending the allowlist for this narrow default update.

Provider smokes must use explicit `gemini-3.7-flash-high` and `grok-4.6`, a harmless one-turn prompt, isolated output directories, timeouts, and metadata-only evidence recording executable/version, requested model identity, exit status, and timing—not response content, repository artifacts, OAuth material, or credentials. They are validation of explicit provider support only and must not be used to discover or silently accept a changed default.

## Acceptance criteria

- [ ] Execute/repair and regular-tier Gemini routes store `gemini-3.7-flash`, while Pro and worker/lite routes remain unchanged, proven by focused routing tests.
- [ ] Gemini high effort renders exactly `gemini-3.7-flash-high` with no duplicated suffix, proven by launcher and harness-mapping tests.
- [ ] Grok default/heavy/action/advisor routes use `grok-4.6`, while regular/lite taxonomy cells remain unchanged, proven by tier and Grok argv tests.
- [ ] Default board composition, executable leg defaults, fixtures, presets, and goldens agree byte-for-byte; legacy `gemini-3.6-flash` and `grok-4.5` remain explicitly resolvable but are never selected as defaults, proven by board backcompat/golden/source-audit tests.
- [ ] The governed Proofgate author identity reports `gemini-3.7-flash`, proven by a discriminating emitted-`author_model` assertion in the protected chronology/Proofgate coverage; no release-evidence default remains at 3.6.
- [ ] Explicit live-provider smokes succeed for both new model ids and record metadata-only evidence.
- [ ] Focused suite, complete suite, source audit, deterministic golden regeneration/recheck, build, Gate A isolated consumer, and required CI all pass on the exact reviewed head.
- [ ] A distinct-vendor advisor board reaches the repository-required agreement threshold with zero unresolved substantive dissent.
- [ ] `pyproject.toml`, `__version__`, `uv.lock`, `RELEASE_PIN`, and the active v10 version/digest graph all identify 0.7.15 on the exact reviewed head; historical evidence fields remain byte-identical and `plan_manifest.check()` passes.
- [ ] v0.7.15 tag, GitHub Release, PyPI artifacts, and installed isolated consumer all resolve to the reviewed model-default commit before downstream pin adoption begins.
