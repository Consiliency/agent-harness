# Detailed plan: advisory roadmap registry status

## Task

Implement the owner's 2026-11-04 decision: `advisory` roadmaps are valid,
validated, tracked registry members, but cannot be selected or dispatched.
This is a standalone bounded change, not a roadmap phase with an EC goal.
Do not edit `specs/roadmap-status.json`, `specs/phase-plans-v12.md`, the SEATS
roadmap, or their plans. Adoption belongs to separate work on
agent-harness#1819 and agent-harness#1820. No runner redesign, registry migration,
roadmap resealing, skill changes, or package release is included.

## Research summary

`roadmap_lint.py` owns the status vocabulary, closed banner grammar, strict
manifest parser, exact Git-tracked path coverage, coherence, and declared-active
accessor. `discovery.py` routes selection through a common non-active rejection
gate, but its malformed-declaration detector lists only today's statuses.
`cli.py` validates an explicit roadmap independently of selection; execution
entry points use selection first. Evidence and plan-manifest reporting delegate
to the same coherence implementation rather than enumerating statuses.

### Consumer inventory and compatibility

All runtime paths below are under `phase-loop-runtime/src/phase_loop_runtime/`.

- `roadmap_lint.py`: `ROADMAP_STATUSES`, `_BANNER_PATTERNS`,
  `parse_roadmap_banner_status`, `parse_roadmap_status_manifest`,
  `_read_roadmap_status_sources`, `read_roadmap_status`,
  `validate_roadmap_status_coherence`, and `declared_active_roadmap`.
- `discovery.py`: `select_roadmap`, `_BANNER_DECLARATION_ATTEMPT`,
  `_banner_has_no_declaration`, `_return_selectable_roadmap`, and registry-backed
  discovery. The gate already rejects `banner_status != "active"`.
- `cli.py`: `validate-roadmap` explicitly calls coherence before normal content
  validation; implicit validation uses selection. `execute` and the shared
  run/resume/dry-run path select before dispatch. Keep those semantics unchanged.
- `legible_evidence.py`: `collect_roadmap_status`,
  `validate_roadmap_status_evidence`, and the roadmap-status section of evidence
  verification preserve records and validate their digests/coherence. No status
  enum is duplicated here; no implementation edit is needed.
- `runner.py`: evidence forwarding at collection, embedding, and registry-path
  consumption (around lines 9204, 9266, 9375) uses shared coherence validation;
  no implementation change is needed.
- `plan_manifest.py`: committed-tree scanning and reporting use the parser and
  coherent accessor; retain advisory paths in coverage. Plan lifecycle statuses
  are a separate vocabulary and must not gain `advisory`.
- `roadmap_ownership.py`: `resolve_roadmap` delegates to
  `declared_active_roadmap`; historical checks also validate coherence. Only its
  explanatory status list needs updating.
- Tests: `test_legible_roadmap_contract.py` contains banner, registry, eight-source
  selection and legacy controls; `test_legible_evidence.py` covers evidence;
  `test_legible_review_repairs.py` covers snapshots and drift;
  `test_phase_loop_roadmap_validate.py` covers CLI validation;
  `test_roadmap_ownership.py`, `test_discovery_hygiene_legacy.py`, and
  `test_validate_plan_doc_word_budget.py` consume registry fixtures. Preserve
  their historical fixtures and frozen assertions; add independent tests below.
- No standalone JSON Schema for `roadmap_status_manifest.v1` exists in this
  checkout (including the runtime schema directories and schema exporter).
  The executable schema is `parse_roadmap_status_manifest`.
- `README.md` documents roadmap selection. The only registry discussion found
  under `docs/` is the historical, superseded
  `docs/proposals/review-seat-sandbox.md`; leave that historical record intact.
  Extend the README registry discussion instead of rewriting frozen plans/specs.

### Contract decision

Retain `roadmap_status_manifest.v1`. This is an additive accepted-value change:
keys, record shape, sorted/exact coverage, single-active invariant, error types,
and evidence shape remain identical. Existing documents remain valid; older
runtimes fail closed on the unknown status, so adopting repositories must upgrade
before registering advisory entries. There is no transparent old-reader support.
No plan-manifest or evidence version bump is necessary.

The closed vocabulary is explicit in `roadmap_lint.py:500–502`:
`ROADMAP_STATUS_SCHEMA = "roadmap_status_manifest.v1"` and
`ROADMAP_STATUSES = ("active", "delivered", "superseded")`.
Its protocol comment at lines 493–498 requires every registry value to agree
with the roadmap's own primary banner. The owner decision explicitly authorizes
adding `advisory` to this closed vocabulary; it would be false to claim this adds
no vocabulary. No other protocol vocabulary changes, including blocker classes,
plan lifecycle statuses, or evidence fields, are authorized.

Use exactly this additional line-3 grammar, with a valid ISO calendar date:

```markdown
> # ADVISORY — not runner-selected (2026-11-04)
```

Retain H1 on line 1, blank line 2, exactly one recognized declaration in the
leading banner, and existing ambiguity/date/placement rejection. Advisory is
matched as an anchored full line; prose such as `> ADVISORY ONLY:` is not a
second declaration. SEATS is now registered at `specs/phase-plans-seats-v1.md`
upstream on agent-harness#1820; neither it nor v12 is edited here. Advisory is
neither delivered nor superseded. It contributes to exact tracked coverage and
evidence, never to the active set. `selected_roadmap` must still identify the
sole active record; an advisory-only registry remains invalid. Explicit content
validation of an advisory roadmap succeeds only if all ordinary checks pass.
Later promotion requires a separate owner decision and a coherent update of its
banner, registry status, selected path, and previous active roadmap's disposition;
there is no automatic promotion or new transition command.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py` (modify)
- `ROADMAP_STATUSES`, `_BANNER_PATTERNS`, parser docstrings and lifecycle comment
  — add `advisory` and its exact dated grammar.
- Manifest/coherence functions — preserve existing active-only selection and
  coverage logic; advisory flows through the shared vocabulary and parser.
- `declared_active_roadmap` — guard its registry-absent singleton fallback against
  any advisory declaration attempt, including malformed or misplaced banners,
  raising `NonActiveSelectionError`. Preserve existing
  legacy and existing-status behavior; do not broaden this into a fallback
  refactor. Multi-candidate selection remains active-only.

### `phase-loop-runtime/src/phase_loop_runtime/discovery.py` (modify)
- `_BANNER_DECLARATION_ATTEMPT` — add `ADVISORY` so malformed advisory declarations
  cannot masquerade as banner-free legacy documents. Keep the common gate's
  active-only predicate and every existing return route.

### `phase-loop-runtime/src/phase_loop_runtime/roadmap_ownership.py` (modify)
- `resolve_roadmap` docstring — include lifecycle status `advisory` among recorded non-active
  statuses; no ownership behavior change beyond the shared accessor fix.

### `phase-loop-runtime/tests/test_advisory_roadmap_status.py` (create)
- Add standalone offline pytest cases using temporary Git repos with tracked
  synthetic `specs/phase-plans-v*.md` files. Avoid canonical roadmap hashes,
  dotfiles integration markers, external services and provider launches.
- Positive controls: all four statuses parse; active plus advisory passes
  registry/coherence and explicit CLI `validate-roadmap`; ordinary invalid
  roadmap content still fails. Advisory is retained by manifest reporting and
  evidence collection/revalidation with the correct banner digest.
- Old-reader compatibility: restrict the real parser to the prior three-value
  vocabulary and assert unknown advisory fails closed in parsing and selection;
  retain an old-status positive companion and prove no dispatch occurs.
- Negative controls: advisory selected path; missing, malformed, invalid-date,
  misplaced, duplicate or conflicting advisory banner; registry/banner mismatch;
  omitted advisory coverage. Assert typed errors and CLI nonzero where applicable.
- Exercise real `select_roadmap` source routes, following the eight-source fixture
  pattern in `test_legible_roadmap_contract.py`: explicit, authority, state,
  manifest, handoff, singleton-glob, manifest-disabled and completed-hatch.
  Test registry-present and absent cases where each source is reachable; use
  active companions and source reach assertions to prevent unrelated refusals
  from passing tests. Include malformed advisory with registry absent, declared
  active singleton rejection, and CLI run/resume/dry-run/execute rejection before
  any dispatcher/provider call (sentinel spies must remain uncalled).
- Evidence drift controls: alter advisory declaration or registry after collection
  and assert the existing digest/registry drift errors; test evidence verification
  retains and compares advisory records. Existing statuses and truly banner-free
  legacy selection remain positive/negative controls as currently defined.
- Mutation sensitivity: removal of enum entry or banner pattern kills acceptance;
  allowing non-active selection kills route/dispatch controls; removing ADVISORY
  from attempt detection kills malformed-legacy controls; skipping banner/coverage
  validation kills missing-banner/coverage controls; dropping advisory evidence
  kills record/digest assertions. No mutation-testing dependency is introduced.

### `README.md` (modify)
- Roadmap setup section — explain the four registry statuses, exact advisory
  banner, validation versus execution, coverage, upgrade requirement, and
  separately authorized coherent promotion.

### `CHANGELOG.md` (modify)
- `[Unreleased]` — record advisory support, honest banner, and selection exclusion.

## Documentation impact

The README and CHANGELOG satisfy CONTRIBUTING.md's documentation
and user-visible behavior requirements. No generated skill text or bundles
change. Historical registry descriptions remain historical; no frozen artifact
is amended. Six implementation files total, three small runtime-source edits.

## Dependencies & order

Write the offline controls first, then add the vocabulary/banner and two selection
protections, then document and verify. No external dependency or upstream landing
is needed. This planning run executes none of the commands below. This is a
standalone plan, not a runner phase; no `automation.suite_command` is applicable.
If subsequently adopted into a runner phase, bind command V1 as its effective
suite command before execution.

## Verification

Run from the repository root on Python 3.12+, after implementation. Setup (may
require dependency access): `uv sync --project phase-loop-runtime --group test --extra visual --locked`.
Tests themselves run offline. Define:

```sh
export PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests"
```

- V1: `phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_advisory_roadmap_status.py`
- V2: `phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_legible_roadmap_contract.py phase-loop-runtime/tests/test_legible_evidence.py phase-loop-runtime/tests/test_legible_review_repairs.py phase-loop-runtime/tests/test_phase_loop_roadmap_validate.py phase-loop-runtime/tests/test_roadmap_ownership.py phase-loop-runtime/tests/test_discovery_hygiene_legacy.py phase-loop-runtime/tests/test_validate_plan_doc_word_budget.py`
- V3: `make check`
- V4: `phase-loop-runtime/.venv/bin/python -m phase_loop_runtime.entry_doc_check --repo .`
- V5: `phase-loop-runtime/.venv/bin/python -m phase_loop_runtime.cli docs-audit --repo . --base origin/main --json`
- V6: `git diff --exit-code origin/main -- specs/roadmap-status.json specs/phase-plans-v12.md` and `git diff --name-only origin/main` to confirm only the enumerated implementation and planning artifacts changed (including no SEATS roadmap edit).
- V7: `phase-loop-runtime/.venv/bin/python -m phase_loop_runtime.cli validate-roadmap --repo . --roadmap specs/phase-plans-v11.md` with the source PYTHONPATH above.
- V8: `uv run ruff check .` with the pinned Ruff executable on PATH.
- V9: mutation-check every new test by removing its relevant guard; restore
  source bytes after each mutation and retain per-node failure evidence.
- V10: `make check-full` through the runtime verification-artifact writer,
  including the locked dependency refresh and the checks above in its log.

Before eventual merge, required CI checks are `suite gate`, `lint (pyflakes)`,
`chronology retention guard`, `docs-freshness audit`, `gitleaks`, and release
consistency `check`. If the new docs are read by tests, CONTRIBUTING.md also
requires Gate A dispatch: `gh workflow run test.yml --ref t3/roadmap-advisory-status -f chronology=false`.
That future network action is listed only; this task authorizes no push or dispatch.

## Acceptance criteria

- [ ] Advisory is valid in v1 with its honest dated banner and exact coverage;
  explicit CLI validation succeeds with valid content — V1.
- [ ] Advisory is never selected or dispatched, including legacy and escape-hatch
  routes; declared-active discovery excludes an advisory singleton — V1.
- [ ] Missing/malformed advisory banners, selected-advisory registries and
  registry/banner or coverage drift fail closed — V1.
- [ ] Evidence/reporting retain advisory and detect drift — V1 and V2.
- [ ] Existing active/delivered/superseded and legacy behavior remains unchanged;
  old registries need no migration — V1, V2 and V3.
- [ ] Current docs and CHANGELOG explain the new behavior, and adoption roadmaps
  are untouched — V4, V5 and V6.

## Open questions

None. Registration and promotion decisions for the two downstream roadmaps are
explicitly separate from this implementation.
