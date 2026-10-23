# Amendment: skill-eval broad verification evidence

Status: **Evidence method accepted after owner-authorized manual review;
candidate verification pending.** AC5 remains **UNMET** and the original failed
lifecycle is preserved. [DRAFT agent-harness#1733](https://github.com/Consiliency/agent-harness/pull/1733)
must remain draft until actual candidate checks pass and readiness is reassessed.
Publication is authorized; merge authority is unchanged.

## Authority and precedence

The owner instructed “continue as recommended” and requested Opus/Gemini reviewers
through T3 Code, initially with Claude on Frontier, then explicitly switched
Claude to Regenesis after Frontier quota exhaustion. Frontier supplied no review.
The accepted recommendation
authorizes a narrow amendment accepting measured successful CI source-suite plus
Gate A evidence for broad verification, retaining failed local evidence, followed
by independent implementation review and readiness reassessment before merge.

The original [detailed plan](../detailed-skill-eval-20261015-0614.md) is retained
byte-for-byte, SHA-256
`dec674e831b818e91a0003ee52172228a341566c38bf2b497967f6027341f989`.
Following method acceptance, this amendment takes precedence **only** over that
plan's broad regression evidence requirement in `## Verification` (`make check`
and `make check-full`) and the corresponding evidence portion of its fifth
acceptance criterion. The entrypoint, allowlist, docs and other AC5 obligations
remain. All other acceptance criteria, experiment/rubric definitions, trial
budget, launch/observation contracts, side-effect limits and pending live
qualification remain unchanged. No original command is retrospectively a PASS.
This amendment pins observed inputs/evidence, never future commits or topology.

## Retained local outcome and follow-up ownership

The latest sealed local attempts remain failed:

- `taskset -c 0-3 make check`, with `TMPDIR=/tmp`: exit 2; 16 failed,
  13,581 passed, 649 skipped, one xfailed and 338 errors. Its copied-tree leg was
  blocked before execution by temporary-filesystem inode exhaustion.
- `taskset -c 0-3 make check-full`, same setting: exit 2; interrupted, partial
  main-suite result of 55 failed, 10,509 passed, 588 skipped, one xfailed and
  320 errors. Its subsequent copied-tree leg had 85 passed. Interruption and that
  partial coverage cannot establish full-suite success.

Earlier failed attempts and their original receipts also remain unchanged.
The latest artifact SHA-256 is
`1c6c7d8a15acde6ed560654dfcb4fbb1dcea2fdb46a3c82629e9d4a45064ecb8`;
its sealed log SHA-256 is
`da713fff4e8a434c3adf7873ed4dc870f710c86b529c38622d9babe63bf212f2`.
The executor retains these locally; no raw private logs are added to this public
amendment. Shared-root canary chown/proofgate mkdir assumptions, nested namespace
prerequisites, native executable dispatch portability, capacity and remaining
node-specific assertions require follow-up in their owning test/runtime or
environment scope. Limited paired controls establish only their selected
outcomes, not that every failure is baseline. No issue filing, host permission
change, skip weakening or repair outside the evaluator's scope is authorized.

## Historical measured CI evidence and command mapping

[Dispatch run 39004507757](https://github.com/Consiliency/agent-harness/actions/runs/39004507757)
is historical completed/success evidence on earlier source HEAD
`2dc68fcb326331d89bd4260897b8d964549ea469`. It ran from
2026-10-17T04:57:49Z to 2026-10-17T06:01:42Z with `chronology=false`.
The following are actual job-log summaries, not counts inferred from green badges.

| Execution | Observed result |
| --- | --- |
| [Source Python 3.10](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117314123842) | 13,932 passed, 652 skipped, one xfailed; copied LEGIBLE leg 85 passed |
| [Source Python 3.11](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117314123902) | 13,933 passed, 651 skipped, one xfailed; copied leg 85 passed |
| [Source Python 3.12](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117314123844) | 13,934 passed, 650 skipped, one xfailed; copied leg 85 passed |
| [Installed-wheel Gate A, Python 3.12](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117314123832) | 13,498 passed, 1,086 skipped, 603 deselected, one xfailed; `Gate A PASSED` |
| [Lint](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117314110261) | `All checks passed!` |

The [hosted fallback](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117325397865)
and [suite gate](https://github.com/Consiliency/agent-harness/actions/runs/39004507757/job/117325411060)
both succeeded. Offload and PR-only wheel-smoke jobs were expected skips; they
are not passing suites. Gate A's actual full-suite step succeeded.

The mapping below describes the earlier scripts/workflow at that exact SHA;
it is not coverage of the newly integrated candidate:
[local_check.py](https://github.com/Consiliency/agent-harness/blob/2dc68fcb326331d89bd4260897b8d964549ea469/phase-loop-runtime/scripts/local_check.py),
[test.yml](https://github.com/Consiliency/agent-harness/blob/2dc68fcb326331d89bd4260897b8d964549ea469/.github/workflows/test.yml)
and [Gate A](https://github.com/Consiliency/agent-harness/blob/2dc68fcb326331d89bd4260897b8d964549ea469/phase-loop-runtime/scripts/gate_a_cleanroom.sh).

| Local requirement | Observed CI counterpart and limits |
| --- | --- |
| `make check`: changed/importing tests against merge-base plus working changes; shared pyproject/conftest changes select the whole suite | The evaluator changes runtime pyproject, triggering whole-suite selection. Each dispatch matrix `Run standalone test suite` step runs the full standalone source suite, covering indirect imports that selection alone might miss. This is evidence substitution, not execution of the local selector. |
| `make check-full`: `--full` | Same full source-suite steps. Local flags are `-m not dotfiles_integration -q -p no:cacheprovider`, adding xdist `-n auto --dist loadfile --max-worker-restart=0` when installed. CI installs xdist 3.8.0 and uses the same marker/scheduling flags; CI output/cache verbosity differs. |
| Pinned lint | Local `uvx ruff@0.15.5 check .` and independent CI `lint (pyflakes)` use ruff 0.15.5 and root `ruff.toml` (`F`, ignoring `F841`). The lint job actually succeeded. |
| Clean local HOME/system PATH with source imports | Local runner uses a cached Python 3.10 environment and `env -i`; hosted source lanes use provisioned GitHub runner environments and `PYTHONPATH=src:tests`. They are not identical hosts/environments. Gate A adds an empty HOME, cleared environment, disabled user site and installed-wheel import checks. |
| Two LEGIBLE tests excluded from main leg | Both paths run `test_legible_roadmap_contract.py` and `test_legible_evidence.py` separately after copying tests and v10 roadmap outside Git. Local copied leg puts current `src` after copied tests on PYTHONPATH; CI copied leg uses installed production with tests-only PYTHONPATH. All three dispatch copied legs passed. Gate A separately exercises the broader installed-wheel copied suite. |
| Chronology selection | Default local commands omit `--with-chronology` and deselect the exact chronology node. This dispatch's explicit false input also deselects it in the 3.10 lane and Gate A; 3.11/3.12 always deselect it at this SHA. Job logs witness absence in 3.10 and Gate A junit. The retention guard passed, but does not prove the heavy node ran. That history proof remains outside this substitution, as it is outside default local commands. |
| Quarantine | Clean default local runs do not set `PHASE_LOOP_DESELECT_QUARANTINE=1`. Dispatch source lanes set it to `0`, and Gate A's clean environment omits it, so quarantined tests run. PR-only green results can deselect up to five marked nodes and cannot alone replace this dispatch. |
| Standalone boundary | Both intentionally exclude `dotfiles_integration`; this does not certify fleet/dotfiles assertions. Gate A also excludes four exact final-document nodes requiring external runner evidence and the chronology node, and applies existing CONFORM classification. Source coverage complements those omissions; Gate A alone is insufficient. Hundreds of reported skips/deselections are not claimed as executed assertions. |

The separate `PHASE_LOOP_REQUIRE_SEAT_OWNER=1` Linux-owner command remains
mandatory: prior evidence is 61 passed with zero skips, alongside 111 focused
feature, 46 packaging and seven inventory tests. These are prior focused
observations, not counts inferred from broad CI; general CI permits some
unsupported-host controls to skip. This amendment does not replace that no-skip
requirement or claim real Codex operational qualification/human blind calibration.

## Conditions for using the substitution

1. Bind evidence to the actual candidate: exact commit, comparison base and
   working overlay, with hashes of source, tests, fixtures, package/lock inputs,
   local-check/Gate A scripts, selection hooks, lint configuration and relevant
   workflows. Review the complete implementation/tests/fixture, not just totals.
2. Require actual successful relevant source and copied legs, lint and full
   installed-wheel Gate A, retaining exact run/job identities and exclusions.
   Review unexplained coverage gaps rather than treating aggregate green as proof
   that every assertion executed. Keep required Linux zero-skip controls separate.
3. Keep entrypoint/allowlist/docs and all other acceptance obligations, failed
   local artifacts, remaining owning-scope work and operational limits visible.
   Only a subsequent explicit acceptance reduction can use the reviewed
   substitution; do not rewrite original failed receipts or replay the failed
   lifecycle as executing/completed.
4. Recheck all six required PR checks on the publication head and obtain Gate A
   coverage bound to that candidate. This run proves the recorded SHA, not an
   unpublished amendment or a later merge. If bytes change, classify and verify
   the delta, refresh bindings and review as needed. Earlier CI never silently
   covers changed source/tests/fixtures/packaging/workflows; final-head CI pending
   stays pending. Docs-only deltas still require their relevant checks/review.

## Current canonical integration and evidence mapping

One fresh main snapshot, `a776e681b24f2f019c9908f91a0e97caf99ab5d6`,
was ordinarily merged into the owned candidate. It includes merged
agent-harness#1549 and agent-harness#1738. The observed integrated HEAD is
`8aecf2fdb7bb2468e4cfcb650585fae1ade4dda2`, with that snapshot as its
comparison/merge-base, plus this uncommitted proposed amendment. Both sides of
the adjacent CHANGELOG conflict were retained. Canonical Python 3.12 floor,
workflow, lock and reference/staging changes are preserved. This reconciliation
does not implement or take ownership of a foreign open change. The original
plan and all typed manifest rows/lifecycle history remain byte-identical to the
pre-merge candidate; the evaluator lifecycle remains failed.

Current mapping uses the landed
[local_check.py](https://github.com/Consiliency/agent-harness/blob/a776e681b24f2f019c9908f91a0e97caf99ab5d6/phase-loop-runtime/scripts/local_check.py),
[test.yml](https://github.com/Consiliency/agent-harness/blob/a776e681b24f2f019c9908f91a0e97caf99ab5d6/.github/workflows/test.yml),
[Gate A](https://github.com/Consiliency/agent-harness/blob/a776e681b24f2f019c9908f91a0e97caf99ab5d6/phase-loop-runtime/scripts/gate_a_cleanroom.sh),
and [chronology scope](https://github.com/Consiliency/agent-harness/blob/a776e681b24f2f019c9908f91a0e97caf99ab5d6/ci/chronology-scope.sh).
These four files match canonical main exactly in the integrated candidate.

| Current obligation | Current mapping and delta from historical evidence |
| --- | --- |
| Interpreter and dependency inputs | Runtime metadata is `>=3.12`; canonical `uv.lock` is retained. Local-check now provisions 3.12 rather than 3.10. Hosted and Dagger source coverage now use one 3.12 lane on every event. The historical three-lane run used older metadata, lock and interfaces and cannot satisfy this candidate's requirement. |
| Broad selection and source execution | `make check` still selects against merge-base plus working/untracked files; the evaluator's pyproject delta still selects the whole suite. `make check-full` requests full coverage. Current hosted source execution remains full standalone tests, `-m "not dotfiles_integration"`, xdist `-n auto --dist loadfile --max-worker-restart=0`, ignoring the two copied LEGIBLE files. Local uses `-q -p no:cacheprovider`; CI's verbosity/cache flags differ. Actual successful integrated-candidate CI is pending. |
| Isolation, imports and copied leg | Local remains clean HOME/system PATH with source imports. Hosted source uses provisioned runners and `PYTHONPATH=src:tests`; its two LEGIBLE files run outside Git with installed production and tests-only imports. Local's copied leg uses current source after copied tests. Gate A retains wheel installation, cleared environment/empty HOME, disabled user site and import checks. These are complementary environments, not identical commands. Integrated full Gate A and copied-leg results are pending. |
| Chronology and quarantine | Chronology ownership and junit move to 3.12 (`chronology-junit-py312`), alongside Gate A; default local commands still deselect the heavy node. A dispatch with `chronology=false` must witness its absence; the heavy history proof is outside this substitution. Dispatch source keeps quarantine enabled for execution (`PHASE_LOOP_DESELECT_QUARANTINE=0`), unlike PR-only deselection. Gate A omits the variable. |
| Exclusions and lint | `dotfiles_integration`, the two separately copied source files, and Gate A's existing final-document/CONFORM exclusions remain explicit. Skips are not executed assertions. Ruff stays 0.15.5 with root config. The 3.12 BAML I1 subset is now covered by the full 3.12 lane rather than a separate step. Historical green badges cannot establish any new candidate check. |
| Separate owned Linux boundary | `PHASE_LOOP_REQUIRE_SEAT_OWNER=1` and zero skips remain mandatory independently of general CI. Local interface validation must retain real no-read/known-read, non-Git stage, source-copy non-observation, inotify invalidation, inner-probe refusal/cleanup and feature-flag controls. Live Codex tool qualification and human blind calibration remain pending. |

Before Round-1 repair, the locked project environment was refreshed with
`uv sync --project phase-loop-runtime --python 3.12 --group test --extra visual --locked`.
Actual pre-repair integrated results were 111 focused feature tests, 61 required Linux tests
with zero skips, 46 packaging tests, seven classified launch-inventory tests,
and 89 upstream Python-floor/reference/entry-doc tests, all passed under project
Python 3.12.14. A freshly built and installed wheel passed import-origin,
`--help` and `validate` probes from outside the repository. Entry docs are clean;
lint and whitespace pass. Local docs freshness exits zero but reports
**skipped**, not a substantive freshness pass. The new frozen private packet
retains exact commands and sealed results. This bounded evidence does not
substitute for pending broad integrated source/installed CI. Historical failed
local receipts and earlier successful CI remain unchanged.

## Round-1 repair candidate and evidence binding

The integrated HEAD remains unchanged. The next candidate includes owned,
uncommitted evaluator/runner fixes, regression tests, guide/changelog updates and
this proposed amendment. These deltas enforce the existing malformed-stream,
packet-blinding and one-shot scoring contracts; they do not change the pilot
rubrics, allocation, decision rule, launch boundary or CI-substitution method.
The original plan, manifest rows/failed lifecycle and old frozen packet remain
unchanged. No additional main snapshot was merged.

Round-1 supplied no usable implementation approval: the Frontier Opus task failed
before reviewing due to quota; Gemini's conditional support for the amendment
method was followed by an identity-check failure and inaccurate source citations.
The repair records actual reproductions and responses for fresh parent-owned
independent review, without carrying either task as an approval.

Current bounded Python 3.12.14 evidence is 155 focused tests, 68 required Linux
tests with zero skips, 46 packaging tests, seven inventory tests and 89 upstream
integration checks, all passed. A fresh installed wheel passed outside-repository
import-origin, help and validation probes, with evaluator module bytes checked
against source. Dependency refresh, entry docs, lint and whitespace passed; docs
freshness exited zero with **skipped**, not substantive coverage. A first new
verification attempt refused at interpreter preflight before running commands;
that failed receipt is retained alongside the successful bounded artifact.

The old packet's saved diff still matches its recorded digest, but reproducing
its Git display changed only abbreviated index hashes (nine digits to eight),
so its verifier fails. It is retained unchanged as history. The new packet uses
explicit full-index Git serialization and independent exact source-byte hashes,
including owned working overlays and the new amendment. Its read-only verifier
checks the complete public diff under command-local abbreviation settings without
changing shared Git configuration. This binding repair supplies no retroactive
review verdict. Current broad source/full Gate A and final publication-head CI
remain pending; the bounded checks do not satisfy AC5.

## Accepted method and pending candidate verification

The preceding integration and repair sections retain their historical evidence.
Subsequent Opus Regenesis full review returned PARTIALLY AGREE with blocker B1;
its B1 delta review returned AGREE after cancellation repair and offline checks.
Gemini's final AGREE covers the prior repair candidate, with recorded citation
limitations; it does not approve the later B1 delta. The
[implementation review record](../reviews/skill-eval-implementation-20261017.md)
binds both review bases and their limits. The parent accepted this narrow evidence
method following the owner-authorized manual reviews; no successful runtime-board
invocation or exact-publication-head unanimity is claimed.

The B1 candidate's sealed bounded checks passed under Python 3.12.14: 14 selected,
161 focused, 74 required Linux controls with zero skips, 46 packaging, seven
inventory and 89 integration tests, plus installed-wheel entrypoint/import,
entry-doc, lint and whitespace checks. Docs freshness reported **skipped**.
The observed pre-fix result remains five failed and nine passed, including 48
subject calls instead of one. These results retain their exact review overlay;
they do not establish broad candidate success.

For publication, one further fresh main snapshot,
`3c001bf1d55654aa48709ebcbd0b5d9832234181` (agent-harness#1747), was reconciled
by ordinary merge. Its incoming delta changes only
`tests/test_advisor_board_static_import_862.py` under `phase-loop-runtime/` and
`plans/manifest.json`; no runtime or verification-workflow interface changes.
All reviewed evaluator source/tests/guide/changelog bytes are preserved. The
original plan and evaluator manifest row, including failed lifecycle, remain
unchanged; upstream manifest metadata is retained. Only this procedural amendment
and the implementation review record are new post-review documentation deltas.
Focused integration and documentation checks must record their bounded coverage;
fresh full source, copied-leg, lint and installed Gate A evidence is still required.

Current-candidate CI is **PENDING**: neither dispatch 39004507757 nor earlier
required checks cover the publication candidate. After authorized publication,
dispatch `test.yml` with `chronology=false`, bind the actual run to the published
head, and recheck all six required PR checks plus full installed Gate A. Dispatch
acceptance is not PASS. AC5 remains **UNMET** and lifecycle **failed** until an
explicit acceptance reduction has actual candidate-bound evidence. Do not replay
the original failed lifecycle as executing/completed. No readiness promotion,
workflow/policy change, live pilot or merge is authorized by this amendment.
