# Detailed plan: publish phase-loop-runtime v0.7.14 for the headless agy fixes

## Task

Complete the narrow release tracked by Consiliency/agent-harness#432 without adding the Gemini 3.7 or Grok 4.6 default changes to its release candidate.

## Research summary

The planning base is `9231609f`; the published/runtime version remains 0.7.13.
Consiliency/agent-harness#324, Consiliency/agent-harness#325, and the
Consiliency/agent-harness#350 correction are ancestors of that base. The older
dotfiles execution plan froze base `5c211e7`, agy 1.1.10, and six v10 lifecycle
cardinalities that no longer describe main. On 2026-08-14 the attended host
reports agy 1.1.13, bwrap 0.6.1, and active agy processes; no cleanup or live
provider probe may run until those users finish and quiescence is proved.

This plan is the current-main amendment for the release. It preserves the old
plan's safety properties, signed-publication boundary, and attended canary, but
rebinds implementation to agy 1.1.13 and the current manifest. Draft
Consiliency/agent-harness#545 supersedes the stale partial
Consiliency/agent-harness#433 and must deliver the complete source boundary—not
only fail-closed command stubs—before the release candidate is frozen.

## Changes

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project].version` — change from 0.7.13 to 0.7.14 so built artifacts and the release tag agree.
- `[dependency-groups].test` — add `pytest>=8,<9`; regenerate `uv.lock` and use
  the locked group for the isolated-wheel test environment.

### `phase-loop-runtime/src/phase_loop_runtime/__init__.py` (modify)
- `__version__` — change to 0.7.14 in the same release commit.

### `RELEASE_PIN` (modify)
- Release pin — change to `v0.7.14` in the same commit as both package version sources.

### `CHANGELOG.md` (modify)
- v0.7.14 entry — enumerate only the merged headless agy review/canary fixes required by Consiliency/agent-harness#432 and explicitly defer model-default changes.

### Canary producer, reducer, and panel integration (modify)
- Reconcile Consiliency/agent-harness#433 into Consiliency/agent-harness#545.
  Install all six `agy-canary-*` commands and implement descriptor-bound private
  evidence sinks, cleanup recovery, bwrap namespace isolation, minimal HOME/XDG
  construction, customization masking, resolver/DNS self-test, strict read-only
  policy, staged-file read coverage, singleton Gemini seat/retry binding, and
  capture-aware private board serialization.
- Treat agy 1.1.13 as the current supported surface. Select `stream_json` only
  after an attended process produces a typed terminal event plus successful,
  content-reconstructed reads of both exact in-namespace staged files, accepted
  by the strict parser in ordered tool call/result pairs. A terminal-only or
  zero-call stream is incomplete and non-authorizing; no help-text-only
  capability claim is permitted. The composed production launch must rewrite
  the prompt and `agy --add-dir` operands to `/run/phase-loop-review` after
  bubblewrap hides the host `/tmp` stage, and an integration test must exercise
  that actual argv/prompt boundary rather than testing namespace tokens alone.
- `agy-canary-bootstrap-attest`, prepare, verify, and finalize must wrap and bind
  the actual committed bootstrap child, exact wheel/tag/handoff identities,
  settings lineage, board evidence, and final redacted proof. Test substitutes
  must be discriminating and cannot stand in for the attended gate.

### v10 live version/digest graph (modify)
- Update the live 0.7.13 assumption to 0.7.14 in the roadmap, canonical sidecar,
  fixture, and focused contract test; recompute roadmap/probes constants.
- Rebind all six active v10 plan frontmatters, dependent FABPUB/HARDEN payload
  seals, and manifest current-authority pointers. Current main has lifecycle
  counts `CONFORM=5`, `FABPUB=1`, `HARDEN=1`, `LEGIBLE=3`, `PROOFGATE=4`, and
  `REVIEWTRUTH=2`. Every `digest_rebind.plan_sha256` is validator-live because
  `plan_manifest.check()` compares all of them to the current plan bytes.
  Preserve every `reviewed_*`, `predecessor_*`, panel/audit digest, lifecycle
  structure, and non-enumerated roadmap digest as historical evidence.

### `docs/releases/outside-agent-release-handoff.md` (modify twice)
- Release PR — identify v0.7.14 and `publication_status=pending`; record exact
  candidate source/wheel evidence without inventing tag or registry facts.
- Post-publication handoff-only PR — record the release merge commit, signed tag
  object and peel, workflow/GitHub Release URLs, and exact PyPI artifact tuples
  only after independent live verification.

### `.github/workflows/publish-pypi.yml` (modify)
- Make pull requests that change the runtime or publication workflow execute a
  non-publishing build-and-verify lane. On a signed `v*` tag, check out the exact
  tagged commit, build one wheel/sdist set, verify that wheel in an isolated
  locked environment (including installed command/module ownership and the full
  suite), record SHA-256 tuples, upload that exact `dist/` as the workflow
  artifact, and pass the same artifact unchanged to trusted publishing.
- Gate the credentialed publish job on a tag ref. Never rebuild between the
  verified build job and `pypa/gh-action-pypi-publish`; post-publication PyPI
  comparison remains a detection/recording step, not the first proof of the
  bytes after an irreversible upload.

## Documentation impact

The changelog and release-evidence handoff are mandatory because the release gate requires an auditable mapping from the published artifacts to the merged agy fixes.

## Dependencies & order

1. Complete Consiliency/agent-harness#545 source and synthetic isolation tests.
   Do not run the attended cleanup/probe while any agy process remains active.
2. Independently review Consiliency/agent-harness#545, reconcile substantive
   dissent, require green CI, merge it, and close superseded draft
   Consiliency/agent-harness#433.
3. Rebase the v0.7.14 release branch onto that exact main landing. Apply version,
   lock, handoff-pending, and current authority-graph changes from a clean
   `/mnt/workspace/worktrees` worktree.
4. Build the wheel/sdist and run source, locked-wheel, full, clean-room, and
   isolated-consumer verification on the exact committed head. Exercise the
   publication workflow's dry-run build-and-verify lane and fill only the
   pre-publication artifact evidence that those commands actually produced.
5. Run an exact-head cross-vendor advisor board. Reconcile every substantive
   dissent and repeat affected/full checks and CI after every head change.
6. Merge only on green required CI. Reverify the exact merge commit from a fresh
   detached worktree, including direct ancestry of the Consiliency/agent-harness#545
   merge commit and tri-source version equality, then create and push a signed
   annotated `v0.7.14` tag. The tag workflow must verify and publish the same
   workflow artifact bytes from that exact tagged commit without rebuilding.
7. Verify trusted PyPI publication, explicitly create the GitHub Release, and
   merge a singleton handoff-only evidence PR whose tuples match live PyPI.
8. Only then stage the dotfiles pin and attended claw cleanup/probe/strict board
   lifecycle. Close Consiliency/agent-harness#432 only after publication and
   isolated-consumer proof; fleet convergence remains separately evidenced.

## Verification

```bash
git merge-base --is-ancestor <agent-harness-324-merge-sha> HEAD
git merge-base --is-ancestor <agent-harness-325-merge-sha> HEAD
git merge-base --is-ancestor <agent-harness-350-merge-sha> HEAD
git merge-base --is-ancestor <agent-harness-545-merge-sha> HEAD
python - <<'PY'
import pathlib, re, tomllib
root = pathlib.Path('.')
version = tomllib.loads((root / 'phase-loop-runtime/pyproject.toml').read_text())['project']['version']
init = (root / 'phase-loop-runtime/src/phase_loop_runtime/__init__.py').read_text()
runtime = re.search(r'^__version__\s*=\s*["\x27]([^"\x27]+)', init, re.M).group(1)
pin = (root / 'RELEASE_PIN').read_text().strip().removeprefix('v')
assert version == runtime == pin == '0.7.14', (version, runtime, pin)
PY
cd phase-loop-runtime
uv lock --check
PYTHONPATH=src:tests python -m pytest -q \
  tests/test_panel_gemini_no_command_preamble.py \
  tests/test_panel_leg_failure_diagnostic.py \
  tests/test_agy_canary_evidence.py
PYTHONPATH=src:tests python -m pytest -q
cd ..
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.plan_manifest check --repo .
python -m build --sdist --wheel --outdir /tmp/phase-loop-runtime-v0.7.14-dist phase-loop-runtime
(cd phase-loop-runtime && bash scripts/gate_a_cleanroom.sh)
python phase-loop-runtime/scripts/check_model_id_sources.py
git diff --check
```

The exact-candidate release run additionally creates a private venv, installs
`--group test --locked --no-install-project`, force-installs the built wheel,
runs the focused/full suites with `PYTHONPATH=tests` only, proves distribution
ownership for the canary modules and all six CLI commands, and compares the
sdist-derived wheel. After publication, install the downloaded PyPI wheel—not a
resolver or checkout—and compare its digest to PyPI and the merged handoff.

## Acceptance criteria

- [ ] The candidate contains Consiliency/agent-harness#324,
  Consiliency/agent-harness#325, Consiliency/agent-harness#350, and the complete
  reviewed Consiliency/agent-harness#545 source; it contains no Gemini 3.7/Grok
  4.6 default delta.
- [ ] All six canary commands are installed from the wheel; synthetic tests prove
  bwrap/minimal-HOME/customization/DNS/staged-read/singleton/private-sink
  boundaries, while the live agy 1.1.13 probe remains attended and fail-closed.
- [ ] `pyproject.toml`, `__version__`, `RELEASE_PIN`, and the lock root equal
  0.7.14/v0.7.14, and the locked pytest 8 group is used.
- [ ] The current manifest lifecycle structure is unchanged; only enumerated
  validator-live plan/roadmap/payload pointers move, historical evidence remains
  byte-identical, and `plan_manifest.check()` plus focused contract tests pass.
- [ ] Source-focused, locked pytest 8.x, full, Gate A, and exact-wheel suites pass
  on the exact candidate and are recorded without overstating the attended gate.
- [ ] Wheel and sdist build from the reviewed SHA and pass isolated-consumer checks, proven by `python -m build` plus the fresh-environment smoke.
- [ ] The tag workflow verifies the exact wheel/sdist artifact set it uploads and
  trusted-publishes, and the publish job cannot run for pull requests or manual
  non-tag dispatches.
- [ ] The exact head receives a usable independent advisor-board approval with no unresolved substantive dissent.
- [ ] Signed tag, GitHub Release, and PyPI artifacts all resolve to the reviewed release commit and matching hashes before Consiliency/agent-harness#432 is closed.
