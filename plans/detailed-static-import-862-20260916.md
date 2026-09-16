---
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      PHASE_LOOP_TDD_EXPECT_HARDEN=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_advisor_board_static_import_862.py
      phase-loop-runtime/tests/test_advisor_board_composition.py
      phase-loop-runtime/tests/test_advisor_board_presets.py
      phase-loop-runtime/tests/test_advisor_board_resolver.py
      phase-loop-runtime/tests/test_advisor_board_config.py
      phase-loop-runtime/tests/test_advisor_board_golden.py
      phase-loop-runtime/tests/test_convergence_runtime_imports.py;
      ruff check phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py
      phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py
      phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py
      phase-loop-runtime/tests/test_advisor_board_static_import_862.py;
      git diff --check
---

# Detailed plan: make static board imports independent of live review admission

## Task

Repair agent-harness#862 so importing the convergence runtime and its pure
subscription-environment scrubber works on macOS. Keep Linux-only admission for
live review composition, config loading and dispatch unchanged. This bounded
repair does not grant review execution on macOS or accept any V10 phase.

## Research summary

Input main is `a830620c6e048c2608750787ae02dc5e3b1310dc`. Both
`presets.CODE_REVIEW_BOARD` and `resolver._STANDIN_CODE_REVIEW` are static,
all-vendors-up snapshots built at import time. Each injects only `is_available`.
The existing composition predicate treats an absent `auth_ok` as requiring live
admission, although the subsequent auth callback is a pure pass-through.
`config.load_boards` already documents the supported static form: two explicit
injected probes. Its live path independently acquires admission before either
probe, and public dispatch independently requires operation-bound isolation.

Retained `baseline-r1/observations.json` proves the error on actual Mac mini
Python3.12.12 and a fresh Linux process using the Darwin policy value. All205
module hashes match input main. Linux imports succeed but unnecessarily acquire
composition authority for both snapshots. The diagnostics reject subprocess and
network effects; no provider, operational-install change or guard bypass occurred.

## Changes

### `phase-loop-runtime/tests/test_advisor_board_static_import_862.py` (create)

- Add discriminating fresh-process tests before production edits. Import the
  convergence package, backing scrubber, presets and resolver under Linux and
  Darwin policy values. Require zero composition-admission calls and zero
  subprocess/network effects during these static imports; verify actual source
  or installed module identities instead of accepting an already-cached import.
- Check both static snapshots retain the exact current ordered seat data and
  canonical default-board identity. Verify the scrubber still removes representative
  vendor keys and endpoint overrides without exposing their values.
- After successful imports under Darwin, explicitly test bare composition,
  availability-only injection, the actual registry-bound availability method with
  injected auth, an injected availability callback with `default_board_auth_ok`,
  and `load_boards` with two injected probes. Each must reject before executing
  availability/auth callbacks; the availability-only form must stay admitted to
  the live guard even though it is removed from the two static snapshots.
- Prove the unchanged isolation factory rejects the static board. For public
  `invoke_board`, use a real Git worktree as cwd/repo_dir and an explicit
  `ReviewLandingPolicy` requiring the four seats with `requires_president=False`.
  Do not supply `canonical_repo_authority`, `review_authorization`, `spawn`, or
  replacements for any factory/provider/spawn seam. Permit and count separately
  the single exact `git -C <repo> rev-parse --show-toplevel` metadata probe; reject
  all other subprocess/network effects. Require all four ordered seat results to
  be `UNAVAILABLE`, unusable, and have the exact detail
  `HARDEN review isolation requires a Linux review operation`. Another refusal
  reason cannot satisfy this control. Retained `public-refusal-r1.json` already
  proves this call shape on unchanged installed main under the Darwin policy.
- Retain Linux positive controls through the existing activated composition,
  config, preset, resolver and golden tests. Simulated Darwin tests establish
  policy behavior only; actual macOS installation evidence is required below.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py` (modify)

- `CODE_REVIEW_BOARD`: supply an explicit constant-true `auth_ok` alongside the
  existing constant-true availability callback. Both callbacks describe static
  catalog data and perform no auth or provider action. Preserve all board bytes.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py` (modify)

- `_STANDIN_CODE_REVIEW`: make the same explicit static-callback change. Preserve
  resolver behavior and the existing live catalog injection path.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py` (modify)

- `compose_review_board` docstring only: state that import-time snapshots pass
  both callbacks explicitly. Preserve every executable statement, especially
  `_uses_production_composition_probe` and authorization acquisition/revalidation.
  Mechanically strip only true leading docstrings from main/candidate ASTs,
  require equal ASTs, canonicalize their formatting, and compare compiled code
  objects with optimization disabled. This preserves assertions and exception
  handling while avoiding line-table differences from documentation edits.

### `docs/phase-loop/convergence-runtime.md` and `CHANGELOG.md` (modify)

- Document pure imports separately from Linux-only review execution and record
  agent-harness#862. Do not claim general macOS adapter qualification; older
  macOS interpreter process-lifecycle support remains separately unresolved.

## Dependencies & order

Use an owned worktree, native typed plan registration and four-vendor plan
review. Observe and retain RED plus positive controls for the additive tests;
obtain tests-first review before the two production-call changes. Frozen HARDEN
and RUNTIME tests, guards, capability markers and provider policies remain exact.
Then run native verification, qualify installed wheels on Linux and real macOS,
and obtain fresh source and final-candidate reviews before native publication.
Land only after required exact-head CI passes; adopt qualified merged code.
Retain failed sessions and verify private recovery before normal cleanup.

## Documentation impact

The public runtime guide and changelog describe the import behavior and its limits.
No protocol vocabulary, schema, public signature or seat configuration changes.
`advisor_board/CONTRACTS.md:66–90`, IF-0-ABDFREEZE-3, remains binding:
“Auth = active env scrubbing” and “Claude Fable/Opus = subscription TUI only”.
The factory guards, live availability/auth gates and exact-model TUI route remain
unchanged; static catalog construction supplies no executable authority.

## Verification

- `PHASE_LOOP_TDD_EXPECT_HARDEN=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_advisor_board_static_import_862.py`
- `ruff check phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py phase-loop-runtime/src/phase_loop_runtime/advisor_board/resolver.py phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py phase-loop-runtime/tests/test_advisor_board_static_import_862.py`
- `git diff --exit-code a830620c6e048c2608750787ae02dc5e3b1310dc -- phase-loop-runtime/tests ':!phase-loop-runtime/tests/test_advisor_board_static_import_862.py' phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `python3 -c 'import ast,subprocess; from pathlib import Path; p="phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py"; trees=[ast.parse(subprocess.check_output(["git","show","a830620c6e048c2608750787ae02dc5e3b1310dc:"+p])),ast.parse(Path(p).read_text())]; [setattr(n,"body",n.body[1:]) for t in trees for n in ast.walk(t) if isinstance(n,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Constant) and isinstance(n.body[0].value.value,str)]; assert ast.dump(trees[0])==ast.dump(trees[1]); assert compile(ast.unparse(trees[0]),p,"exec",dont_inherit=True,optimize=0)==compile(ast.unparse(trees[1]),p,"exec",dont_inherit=True,optimize=0)'`
- `git diff --check`

Run these and the frontmatter suite through native `run_verification`, retaining
JUnit, logs, explicit interpreter identity and fixtures. Build the exact candidate
wheel, install it into fresh owned Linux and Mac mini environments using the
locked dependencies, and run fresh-process import and live-refusal checks with
source PYTHONPATH absent. Verify all installed runtime module hashes against the
reviewed candidate. Retain the actual Mac platform/interpreter and remote export
paths; no OS shim counts as that host control. Local native verification must run
and verify the remote receipt and stamp `installed-macos-r1/verification.json`.
An unavailable Mac host leaves that acceptance item unmet. Required CI provides
the broader supported Linux interpreter matrix without weakening frozen tests.

## Acceptance criteria

- [ ] Fresh static imports and scrubber access work on Linux and actual macOS
  without composition admission or subprocess/network effects, proven by the new
  tests and the installed Linux/macOS native verification artifacts.
- [ ] Unsupported live composition/config/dispatch remains fail-closed before
  provider effects, while Linux auth/admission positive controls still pass,
  proven by the new refusal cases and the activated frontmatter suite.
- [ ] Existing board identities, ordered seat data, protocols, frozen tests and
  executable admission guards remain unchanged, proven by regression/golden
  tests, the frozen-path diff, the compiled-code comparison command and the
  reviewed production diff. A docstring-only control must compare equal and a
  deliberate guard mutation must compare unequal before accepting that checker.
- [ ] The exact reviewed implementation passes native checks and required CI,
  is installed and verified after merge, and has retained successful and failed
  evidence before cleanup. This does not replace historical phase evidence.
