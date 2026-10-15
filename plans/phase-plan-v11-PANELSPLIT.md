---
phase_loop_plan_version: 1
phase: PANELSPLIT
roadmap: specs/phase-plans-v11.md
roadmap_sha256: d294c3bab92c995bda8266a12340c78a9d73c12a18919a47b2154ceb4555aba4
automation:
  suite_command: ["uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--extra", "visual", "--python", "3.14", "--locked", "python", "-m", "pytest", "phase-loop-runtime/tests", "-q"]
---

# PANELSPLIT: Split the Panel Invoker

## Context

Implement roadmap Phase 4 in one sequential writer lane. The current invoker has
15,207 lines; public consumers and tests import both public and private names from
it. The phase changes organization, preserving behavior, subscription transports,
authorization checks, prompt bytes, serialization, and test files except the
authorized location-only repairs below.

Canonical `.phase-loop/` exists and is authoritative. At planning, its v11 scope
contains a dispatch lock, with no state snapshot or event ledger available to
establish completion. Git is clean; no v11 phase plans or manifest rows exist.
Do not infer a blocker from absent snapshots or legacy `.codex/phase-loop/`.
PANELSPLIT has no phase dependencies.

EC-PANELSPLIT-4 is the roadmap's explicit exception to a new RED-test receipt.
Baseline and final runs use the existing suite with only the authorized relocation
repairs between runs. A failing baseline is an execution blocker, not permission
for other test edits, exclusions, or equivalent-failure acceptance.

## External Inputs

- **agent-harness#1583** — The roadmap amendment on
  `origin/claude/v11-roadmap-panelsplit-relocation` must land before this plan lands
  or executes. It resolves F006–F010 by authorizing location-only relocation
  repairs while retaining the 1,500-line facade cap. This branch includes the
  pending replacement so frontmatter binds the reviewed roadmap bytes; execution
  remains blocked until agent-harness#1583 lands. PANELSPLIT does not run
  concurrently with TESTLOOP or RUNTIME, per the roadmap's scope exception.
- **agent-harness#1203** — Frozen input `plans/phase-plan-v10-RATIFY.md` from
  `origin/codex/v10-ratify-plan-replay-20260930`, SHA-256
  `ed024cf069a7248a7f0fc6a6d6b22040827179ddbcfe3e9913dd8aea7f580eac`.
  Verify its bytes before use; a changed input requires renewed review.

## Interface Freeze Gates

- [ ] IF-0-PANELSPLIT-1 — Freeze the module/symbol map in
  `plans/artifacts/v11-PANELSPLIT-module-map.json`. Every pre-move public,
  imported, and monkeypatched facade name remains accessible through
  `phase_loop_runtime.panel_invoker`; function signatures, dataclass layouts,
  identity-sensitive sentinels, and effective late-bound lookups remain compatible.
  The map records each symbol's defining module, facade export, mutable-state
  owner, and carried-phase ownership. It is produced only after verification.
  For EC-PANELSPLIT-4 class (c), source visitors also accept facade-alias
  attribute calls; the prefix tripwire's asserted seven-name set is unchanged
  and its scan reads the facade plus every `panel/**/*.py`. Moved callers
  late-bind through the facade without module-dictionary synchronization.

Destination map, all under `phase-loop-runtime/src/phase_loop_runtime/panel/`:

| Module | Existing construction sites / responsibility |
|---|---|
| `__init__.py` | Package initialization, with no provider launch or authorization side effects |
| `president.py` | `PRESIDENT_LADDER`, `invoke_president`, ruling persistence and native president resume |
| `types.py` | `PanelRequest`, `PanelLegResult`, `PanelResult`, status normalization and seat outcomes |
| `verdict.py` | `terminal_verdict`, completion/classification and review landing policy |
| `redaction.py` | Detail-code vocabulary, credential redaction, private logs and failure diagnostics |
| `artifacts.py` | `_resolve_artifact`, brief pinning, context references and scratch reclamation |
| `seat_launch.py` | Seat filesystem/profile, identity, credentials, journal, `launch_owned`, `launch_provider`, `run_provider` |
| `broker.py` | Broker command builders, framing, environment and evidence |
| `claude_tui.py` | Transcript parsing, PTY session, trust handling and journal consumption |
| `native_fill.py` | `NativeAgentLegRequest`, `NativeLegFill`, fill validation and provenance |
| `leg_execution.py` | Liveness/process teardown, the Claude TUI leg adapter and `_exec_leg` |
| `claude_transport.py` | `_resolve_claude_transport`, `_panel_claude_route`, print argv, stream guard, session and leg adapter; isolates PANEL ownership. The transport seam from merged agent-harness#1575 is now an existing input to inventory before moving |
| `spawn.py` | `_default_spawn`, provider spawn, placement and injectable-execution detection |
| `board.py` | `invoke_panel`, `invoke_panel_request`, ordered legs and `invoke_board` |
| `findings.py` | Existing falsifier DTOs, parser and attachments; isolates EXECFIND ownership |
| `instructions.py` | Existing review/advisory prompt constants and `_mode_instructions`; isolates RATIFY ownership |

Read the actual statements before moving each chunk; symbol names govern placement,
not historical line numbers. Preserve the facade's compatibility/policy surface;
do not assume wrappers suffice. Additional splits
inside the owned package are allowed only to eliminate a demonstrated ownership
collision; record them in the map before downstream planning.

## Lane Index & Dependencies

SL-0 — Mechanical extraction, ownership handoff and docs
  Depends on: (none)
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Mechanical extraction, ownership handoff and docs

- **Scope**: Move existing panel code behind the compatible facade, apply only the authorized location-only repairs, verify the existing suite, then publish exact downstream ownership and evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/panel/*.py`, `phase-loop-runtime/tests/**`, `plans/artifacts/v11-PANELSPLIT-module-map.json`, `plans/evidence/v11-PANELSPLIT/**`, `plans/phase-plan-v11-PANEL.md`, `plans/phase-plan-v11-REVIEWTRUTH.md`, `plans/phase-plan-v11-LEGLIFE.md`, `plans/phase-plan-v11-EXECFIND.md`, `plans/phase-plan-v11-RESIDUAL.md`, `plans/phase-plan-v11-RATIFY.md`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-PANELSPLIT-1`
- **Interfaces consumed**: `phase_loop_runtime.panel_invoker` (pre-existing), `phase_loop_runtime.plan_ir.parse_phase_plan_ir` (pre-existing), `phase_loop_runtime.discovery.validate_plan_verification_commands_for_intake` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Before any edits, inventory every tracked file under `phase-loop-runtime/tests/` by path and SHA-256, collected test node IDs, existing skips, facade exports/signatures, dataclass layouts, imported globals, patch targets and source-inspection constraints. Run the targeted command below, then the complete suite. Save runner-derived baseline metadata and the observed baseline revision for the relocation diff.
  - impl: Move definitions/constants into the mapped modules; preserve facade import paths and object identity. Resolve replaceable dependencies through the facade at call time, including same-chunk calls, constants, imported modules, mutable dictionaries and ContextVars. Do not copy patched bindings during import or synchronize module dictionaries around calls. Initialize canonical objects once; preserve public type module identity and the existing `_PRODUCTION_*`, `_REAL_*`, `_INVOKE_BOARD` and `_INVOKE_BOARD_PARAMS` relationships.
  - impl: Keep imports inert, preserve optional POSIX imports and avoid circular initialization. Re-export private seams as well as public names. Keep existing consumers unchanged. `_has_injected_review_execution_seam` must distinguish real code from patched controls exactly as before.
  - impl: Preserve the source-sensitive contracts in `test_skill_liveness_contract.py`: two frozen docstring occurrences remain in the facade, and its retry/backstop/teardown expressions still describe executable policy. Where necessary, extract the existing policy expressions into small facade helpers used by the moved implementations. Preserve wrapper signatures and docstrings. Do not spoof inspection, insert inert matching strings, duplicate implementations, or change timing arithmetic. Preserve function-source inspection used by `test_claude_delivery_refusal_1433.py`.
  - impl: Author `plans/evidence/v11-PANELSPLIT/relocation.py`, whose executable baseline scan implements EC-PANELSPLIT-4's predicate over `phase-loop-runtime/tests/`. Publish its output in the receipt; the allowed repair set equals that output, not a fixed list. Apply only classes (a)–(c). The scan floor includes `test_seat_reference_inventory.py` with its JSON fixture, `test_agent_cli_scratch_inventory_1147.py`, `test_the_real_launch_carries_the_prefix.py`, `harden_tdd_guard.py`, `test_skill_liveness_contract.py`, `test_advisor_board_backcompat.py`, `proofgate_tdd_guard.py` PG-A-PANEL, `test_train_invariants.py` F841, `test_placement_driver.py`, `test_cli_qualification_contract.py`, `test_sandbox_egress.py` and `test_seat_owner_notices.py`. Exclude sys.path-only `__file__.parents[1]` uses, unrelated path lists and synthetic fixtures; publish exclusions with reasons. The prefix visitor accepts facade-alias attribute calls without changing its asserted seven-name set. Preserve the unchanged `1433` live-frame/post-journal source-line contract.
  - verify: The script's `verify` mode recomputes baseline bytes with `git show <before.revision>:<path>` and compares them with the working tree under the frozen module map. Compare fixture row multisets; `INVENTORY`, `LAUNCH_COUNTS` and `PROVIDER_CALLS_WITHOUT_ENV` with projected path components; per-file count maps as sums over mapped destinations; every assertion's `ast.dump`; collected-node digests; and the baseline set of tests patching the facade, with all patch targets retained there. Fail on any difference, unclassified hunk or edit outside the scan output. Use computed values, never self-written `*_unchanged` booleans or a bare `git diff` exit code as proof. A pin outside all three repair classes stops the phase for the maintainer.
  - verify: The script's `regressions` mode runs all collectable files in the scan output, plus baseline-derived callers of repaired helpers. Include the 12 cited `review-leg-isolation` call-site nodes across `test_advisor_board_composition.py`, `test_advisor_board_cli_legacy.py` and `test_advisor_board_backing_omnigent.py`, and `test_proofgate_isolation.py` for PG-A-PANEL; record and assert their inclusion in the receipt. Run these alongside the targeted command below before the full suite.
  - verify: Run targeted regressions, then the identical full-suite command; compare the test inventory and collected-node digest with baseline. Check the facade line limit, public/dataclass compatibility, all discovered patch seams and production sentinel identities. Use existing patched production paths as positive controls; in disposable copies, bypass representative late lookups to confirm the existing tests fail, then restore. Cover board spawn, seat launch, Claude print/TUI, native fill, president, and mutable/constant seams.
  - impl: After extraction and verification, finalize the module map and create or update the five owned carried-phase plans PANEL, REVIEWTRUTH, LEGLIFE, EXECFIND and RESIDUAL through `codex-plan-phase`, referencing remaining v11 EC IDs and frozen v10 inputs. For RATIFY, consume its existing authored plan from agent-harness#1203 as a frozen input; migrate its ownership to concrete modules in the v11 plan without re-authoring its lanes, tasks or goals. Do not implement these phases. PANEL owns `claude_transport.py` (jailed seats move to print there); PANEL and REVIEWTRUTH may reuse modules in dependency order. LEGLIFE owns lifecycle/TUI/spawn modules; EXECFIND owns findings; RATIFY owns instructions/president policy; RESIDUAL claims only affected broker/redaction helpers. Refine extraction if remaining work crosses independent module owners; do not change goals or the DAG.
  - impl: Record explicit empty module lists for HARDEN, PRESROUTE and INTEG. HARDEN's remaining scope is evidence/sealing; PRESROUTE's is ledger closeout. INTEG composes train/broker paths through existing panel APIs; its v10 SL-1 facade claim is not carried forward. Any demonstrated panel-write requirement in these independent phases needs a scope decision, not silent facade ownership. Their plan authors consume these decisions; SL-0 does not write their plans.
  - verify: Validate the six owned downstream plans and compare parsed owned paths to the map using transitive roadmap dependencies. Check HARDEN, PRESROUTE and INTEG plans read-only when present; record absence without requiring their creation or imposing a new ordering. Reject facade claims, directory/package globs (including ancestor globs) and independent shared module claims. Run PARSCHED lint when available and the pairwise check below. Preserve concurrently authored plans.
  - impl: Last, reduce this lane's verified results into metadata-only evidence and the frozen map. Record `no_doc_delta`: README, CHANGELOG, release notes and onboarding remain accurate because public behavior and release inputs do not change; the module map documents internal ownership. Append only phase-specific manifest records through the manifest API. Prepare the landing/rebase notice for agent-harness#1284; the Claude transport seam and print-route plan already landed (agent-harness#1575, agent-harness#1446); the governed landing workflow announces the landing. Preserve other phases' rows and artifacts.

The sole lane owns all writes, so lane overlap is empty. Its terminal docs/evidence
steps consume its own earlier results in the listed order; no writer fanout or
separate reducer is authorized. Test ownership admits the scan-resolved set;
EC-PANELSPLIT-4 bounds every edit. All other tests and fixtures, snapshots,
lockfiles, package configuration, generated bundles and roadmap bytes remain untouched. In particular,
`phase-loop-runtime/tests/test_panel_invoker.py` stays read-only unless the
baseline scan proves it matches the predicate. Setuptools
already discovers packages under `src`.

## Execution Notes

Run from the repository root in an isolated assigned worktree. Use canonical
runner state and live Git status to resolve ownership before writes. Preserve
in-flight changes; the named Claude branches may land first or rebase after this
move, without adding a new phase dependency. No merge or announcement is performed
by this planning run.

Use normal governed plan/code review before landing, including cross-vendor
evidence for a Sol-authored plan. This artifact does not claim review ratification.
Executor/model/effort policy inherits existing configuration: CLI/operator
override, phase-plan policy, roadmap policy, Dispatch Hints, registry defaults.
No silent downgrade is allowed without explicit fallback or default inheritance.

Record `plans/evidence/v11-PANELSPLIT/verification.json` with `before` and
`after` objects (suite argv, exit code, collection SHA-256, test-file SHA-256
mapping, skip reasons), and compatibility/control outcomes derived from actual
runs. Include `before.revision`, scan output, exclusions, regression files and
`relocation_repairs` keyed by the repaired set, equal to the scan output.
The program independently recomputes each comparison and asserts unchanged
hashes outside that set. Record no credentials or raw provider payloads. The module-map JSON contains
`modules` (symbol inventories) and `carried_phase_modules` (the nine aliases
mapped to lists of exact repository-relative module paths). Empty lists are
explicit no-panel-write decisions, allowed only for HARDEN, PRESROUTE and INTEG.
Regenerate evidence after any source change; if TESTLOOP or another landing changes
test bytes on rebase, rerun both baseline and final receipts against that same base.
Baseline provenance is observed
at execution time, never a prescribed future commit.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none
- evidence paths: `plans/artifacts/v11-PANELSPLIT-module-map.json`, `plans/evidence/v11-PANELSPLIT/verification.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

Commands are shell-free argv after parsing; validate them through IF-0-VC-2
before execution. Run the targeted regression first and the full suite before
and after extraction. Existing host skips remain visible; do not add exclusions.
Script commands run after their lane-owned evidence artifacts exist. During
planning, validate every command with `validate_plan_verification_commands_for_intake`.

All commands use the locked Python 3.14 test environment in
`phase-loop-runtime/README.md`, including Pillow and packaging tools.
Baseline/final environments and argv match; green-baseline and test-edit
requirements remain.

- `uv run --quiet --project phase-loop-runtime --group test --extra visual --python 3.14 --locked python -m pytest phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_panel_invoker_spawn.py phase-loop-runtime/tests/test_panel_invoker_windows_import.py phase-loop-runtime/tests/test_panel_claude_print_route.py phase-loop-runtime/tests/test_panel_native_fill_183.py phase-loop-runtime/tests/test_advisor_board_golden.py phase-loop-runtime/tests/test_advisor_board_concurrency.py phase-loop-runtime/tests/test_advisor_board_static_import_862.py phase-loop-runtime/tests/test_skill_liveness_contract.py phase-loop-runtime/tests/test_claude_delivery_refusal_1433.py phase-loop-runtime/tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py phase-loop-runtime/tests/test_the_real_launch_carries_the_prefix.py -q`
- `uv run --quiet --project phase-loop-runtime --group test --extra visual --python 3.14 --locked python -m pytest phase-loop-runtime/tests -q`
- `uv run --quiet --project phase-loop-runtime --group test --extra visual --python 3.14 --locked python -c "from pathlib import Path; p=Path('phase-loop-runtime','src','phase_loop_runtime','panel_invoker.py'); assert len(p.read_text().splitlines()) <= 1500"`
- `uv run --quiet --project phase-loop-runtime --group test --extra visual --python 3.14 --locked python -c "import runpy,sys; from pathlib import Path; sys.argv=['relocation.py','regressions']; runpy.run_path(str(Path('plans','evidence','v11-PANELSPLIT','relocation.py')),run_name='__main__')"`
- `uv run --quiet --project phase-loop-runtime --group test --extra visual --python 3.14 --locked python -c "import runpy,sys; from pathlib import Path; sys.argv=['relocation.py','verify']; runpy.run_path(str(Path('plans','evidence','v11-PANELSPLIT','relocation.py')),run_name='__main__')"`
- `uv run --quiet --project phase-loop-runtime --group test --extra visual --python 3.14 --locked python -c "import itertools,json,os; from fnmatch import fnmatchcase; from pathlib import Path; from phase_loop_runtime.plan_ir import parse_phase_plan_ir,ROADMAP_PHASE_RE,_roadmap_phase_dependencies; m=json.loads(Path('plans','artifacts','v11-PANELSPLIT-module-map.json').read_text())['carried_phase_modules']; assert set(m)==set('HARDEN PRESROUTE INTEG PANEL REVIEWTRUTH LEGLIFE EXECFIND RESIDUAL RATIFY'.split()); optional=set('HARDEN PRESROUTE INTEG'.split()); assert all(m[a]==[] if a in optional else bool(m[a]) for a in m); r=Path('specs','phase-plans-v11.md').read_text(); deps=_roadmap_phase_dependencies(r,tuple(x.group('alias') for x in ROADMAP_PHASE_RE.finditer(r))); [deps.update({a:set(s).union(*(deps[b] for b in s)) for a,s in deps.items()}) for _ in range(len(deps))]; paths={a:Path('plans','phase-plan-v11-'+a+'.md') for a in m}; assert all(p.is_file() for a,p in paths.items() if a not in optional); ir={a:parse_phase_plan_ir(p) for a,p in paths.items() if p.is_file()}; assert all(not p.diagnostics for p in ir.values()); root=Path('phase-loop-runtime','src','phase_loop_runtime','panel'); targets={str(root.parent.joinpath('panel_invoker.py'))} | {str(p) for p in root.rglob('*.py')}; owned={a:{f for l in p.lanes for f in l.owned_files if f.rstrip(os.sep)==str(root) or f.startswith(str(root)+os.sep) or any(t.startswith(f.rstrip(os.sep)+os.sep) or fnmatchcase(t,f) for t in targets)} for a,p in ir.items()}; assert all(owned[a]==set(m[a]) for a in ir); assert all(Path(f).parent==root and Path(f).suffix=='.py' and Path(f).is_file() for files in m.values() for f in files); assert all(not (set(m[a]) & set(m[b])) for a,b in itertools.combinations(m,2) if a not in deps[b] and b not in deps[a])"`

## Acceptance Criteria

- [ ] EC-PANELSPLIT-4 — proven by `automation.suite_command` before/after and `relocation.py verify`, with baseline-derived scan and regression evidence; path-entered control: a disposable receipt copy with one projected count altered must be rejected by the same verifier, falsified by that altered count passing. The governing falsifier remains in the roadmap.
- [ ] EC-PANELSPLIT-1 — proven by `assert len(p.read_text().splitlines()) <= 1500` in the facade line-count command above; falsified by a physical line count above 1,500.
- [ ] EC-PANELSPLIT-2 — proven by the targeted regression command and `automation.suite_command`, with the recorded seam inventory; falsified by a moved production call bypassing a facade patch. Path-entered controls must reach the real board/launch/TUI/native-fill construction sites, and restored controls must pass.
- [ ] EC-PANELSPLIT-3 — proven by the `parse_phase_plan_ir` pairwise ownership command and PARSCHED lint when available, with explicit no-write decisions and read-only checks for independent plans when present. Path-entered control: a disposable downstream-plan copy with LEGLIFE's module added to EXECFIND must fail the same parser/check; falsified by that overlapping copy passing the check.

Completion requires all four referenced criteria and IF-0-PANELSPLIT-1; evidence
or downstream-plan work remaining is not completion. A planning closeout produces
no implemented IF gate.
