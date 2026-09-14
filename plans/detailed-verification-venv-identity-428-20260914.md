# Detailed plan: preserve the selected verification environment

## Task

Repair the proven virtual-environment identity loss in agent-harness#428. An
explicitly selected environment must supply the interpreter, packages and pip
invocation used by native verification. This standalone tooling repair does not satisfy a
V10 exit criterion or close the broader environment-composition issue.

## Research summary

Input main is `d05a4c9c1a4256158b65fa4aa06675cbfaafb1ae`.
The original `verification_evidence.py` has SHA256
`1e877edbe355b0587dea9299e7b8d9b05c42646081543239e7382c9563c22b47`, identical to
the source used by the retained native reproduction. Its explicit venv command
finds an installed marker and passes; bare `python` through the generated shim
loses the marker and fails. A lexical symlink alone also loses environment
identity; an exec wrapper calling the lexical venv executable preserves it.

`_build_interpreter_shim` dereferences the selected executable before creating
bare-name links. `_resolve_suite_interpreter` also dereferences the path returned
to `_align_install_interpreter`, so pip refresh can target the base environment.
The existing guard test requires bare aliases to remain symlinks when supported.
The separate four redaction and three nested-discovery failures remain unresolved;
no parent shim exclusion, test amendment or privacy relaxation is part of this fix.

R3 execution is preserved, not replaced by this amendment: its local runtime
`e6458c9c2c35aa376581ad7d04844617fa10ac49c6e256890e61a404f7c579a6` passes 25 of
26 new tests. All 380 existing regression outcomes are unchanged (372 passed,
7 failed, 1 skipped), and six mutants fail their intended assertions. The complete
execution and surviving fixtures independently restored at private recovery commit
`1e67005891414775c7be928391b09ffee1c4be01`. The new test file is frozen at
`a3bc122132e19cf79b086986ce706185ff90dbe7410eccbe108f4d1294dfefe5` and must not change.

The remaining witness uses `a/link -> a/real/nested` and a pin through
`a/link/../chosen/bin/python`. Both direct lexical Python and R3's launcher choose
`a/chosen`, while the frozen witness requires `a/real/chosen`. The original direct
control used only the physical spelling. CPython v3.14.7 `Modules/getpath.py`
first makes the program path absolute and later finds `pyvenv.cfg` from it;
`Modules/getpath.c` performs lexical normalization during that absolutization.
The exact three observed controls and upstream source digests are retained under
`.phase-loop/diagnostics/venv-identity-428-20260914/symlink-dotdot-diagnosis/`.
The installed build's source identity is not inferred from an upstream tag.
R4 follows this recorded diagnosis: retain lexical discovery and log metadata,
but resolve traversable directory components containing `..` at every relevant
execution boundary, preserving the final executable symlink. This strengthens
the implementation to meet the unchanged physical-environment witness; it does
not change that witness to accept the other environment.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` (modify)

- `_interpreter_path` — return an absolute lexical path for a discovered
  executable, without following symlinks. Preserve its current discovery anchor;
  pass the shared anchored PATH explicitly to `shutil.which` for name lookup.
  Convert a relative result at discovery time so the
  version probe and execution use the same file even when their working directory
  differs. Do not reinterpret relative pins as a new repo-relative interface.
- Add a small PATH-anchoring helper, shared by `_interpreter_path`,
  `_interpreter_full_version` and `_run_process`, with explicit environment and
  anchor-directory inputs: convert relative and empty effective PATH entries to
  absolute lexical entries against that directory; preserve
  entry order, duplicates and absolute entries without resolving symlinks or
  collapsing `..`. For a missing PATH, preserve the current discovery default:
  `os.confstr("CS_PATH")`, falling back to `os.defpath` on `AttributeError` or
  `ValueError`, as `shutil.which` does. An explicitly empty PATH intentionally
  becomes the anchor directory in all three consumers, including discovery.
  This changes empty-PATH name discovery: the current `shutil.which(name)` finds
  nothing, while POSIX execution searches cwd. The explicit shared policy removes
  that mismatch; an unprobeable versioned executable found there must be shadowed.
  Do not mutate global environment or cwd. Use a full copied environment with
  this PATH, after the execution-directory conversion below, in repo-context version-probe subprocesses
  and, only when an interpreter shim is active, in verification subprocesses
  before prepending that shim. Discovery, probes and inherited command PATH use
  the calling process's cwd as anchor. Explicit leading `PATH=` assignments
  consumed by `_process_env_and_argv` instead anchor to the command's repository
  cwd, even when their value equals the inherited PATH. Identify those assignments
  from the consumed argv prefix; do not change the parser's return signature or
  parse shell payloads/arguments to an external `env` command. Other environment
  assignments do not turn inherited PATH into an override. Preserve entry order
  and prepend the shim after anchoring. Explicit overrides remain operator choices.
  This keeps the shadows-only `all_present_ok` branch's execution aligned with
  discovery even when caller directory A differs from target repository B.
  Normalization also covers versioned names that need no rejection wrapper.
  No-spec/no-pin command execution retains its existing environment behavior.
  Post-aggregate commands use the later invoking process's cwd for inherited
  PATH and the command's repository cwd for consumed overrides. The reused
  launcher's absolute target remains pinned, but no historical ambient PATH is
  reconstructed or newly guaranteed across processes. Add no artifact field.
- Add two small private execution-path helpers. For a selected interpreter,
  keep its absolute lexical path when its parent has no `..` component. When
  the parent contains `..` and is a traversable directory, resolve that parent
  directory and append the original final filename; never resolve the final
  executable symlink. For child PATH, apply the same directory-only conversion
  to each anchored entry containing `..`, retaining order, duplicates and all
  other entry strings. An absent or untraversable entry must remain unchanged,
  not become an existing search directory by collapsing `missing/..`. Directory
  conversion is based on the existing filesystem, not string-only normalization.
  Use the interpreter conversion for `_interpreter_full_version`'s argv[0],
  `_build_interpreter_shim`'s exec target, and pip alignment in
  `_align_install_interpreter`. Use the PATH conversion in version-probe and
  guarded `_run_process` environments, after the existing anchor selection and
  before shim prepending. Discovery and `SuiteInterpreter.interpreter` remain
  lexical, including the frozen symlink/`..` metadata assertions. Log metadata
  records the declared selection; aligned pip argv records its actual execution
  spelling. Their directory spelling can differ, but their selected environment
  must agree. This correction also covers unredirected versioned/bare names in
  `all_present_ok`, consumed PATH overrides and later-process commands. Preserve
  the existing no-spec/no-pin exception. It adds no guarantee against concurrent
  filesystem changes or historical PATH reconstruction. No environment variable,
  Python startup override, shell payload parser or new artifact field is added.
- `_build_interpreter_shim` — write one executable `_selected_python` launcher
  in the existing shim directory, using `/bin/sh` and `exec` with a correctly
  `shlex.quote`-escaped absolute execution target and unchanged `"$@"` forwarding.
  Point `python` and `python3` at this launcher using the existing symlink path;
  when symlinks are unavailable, write the same launcher bytes at each bare name.
  Never link either bare name directly to the venv Python executable. Preserve
  exit status and the exec process boundary. With `interpreter=None`, retain the
  existing shadows-only behavior and do not add bare redirects or a launcher.
  At discovery and resolver metadata, use a lexical cwd/path
  join without `resolve`, `realpath`, `abspath` or `normpath`; preserve symlink/`..`
  spelling. Shim construction applies the directory-only execution conversion
  above to that lexical selection. Before writing
  `_selected_python`, unlink an existing entry just as the existing shadow
  writers do; never write through a pre-existing symlink. Verify an outside
  sentinel is unchanged. Update the builder docstring as well as the dataclass.
- `_resolve_suite_interpreter` — retain the absolute lexical selected path in
  all three successful returns (explicit pin, already-satisfying bare interpreter,
  and automatic fallback). Keep the current selection order. The pip alignment
  consumer receives this lexical selection and applies the same directory-only
  execution conversion as the launcher and probe.
  Update the `SuiteInterpreter` documentation accordingly. With no explicit pin,
  preserve distinct satisfying `python`/`python3` alias choices and the existing
  metadata/pip preference for `python3`, then `python`. Do not claim one shared
  venv when those aliases differ; use an explicit pin when that guarantee is
  required. Login profiles and explicit command overrides can still select a
  different environment. This repair does not add shell-profile or shell/`env`
  argument parsing; it only identifies assignments the existing parser consumed.
- Preserve full-version and repo-context probing, malformed-spec rejection,
  below/above-bound rejection, present-but-unprobeable rejection, versioned-name
  shadow wrappers, login-shell rewriting and failure evidence. Do not alter
  `_nonsatisfying_shadow_names`, `_version_satisfies`, redaction or public signatures.
  The version probe adds the anchored/converted PATH environment and the
  directory-only conversion of its executable;
  its cwd, full-version query, timeout and failure handling remain unchanged.
  The existing vocabulary remains `SCHEMA_VERSION = 2` with
  `_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})`; no artifact field, schema,
  failure kind or exemption is added.

### `phase-loop-runtime/tests/test_verification_venv_identity_428.py` (retain frozen)

This file already exists with the SHA above. Its original native RED/control,
R3 failure and all fixtures remain authoritative historical outcomes. The
requirements below describe its original test-first scope, not permission to
recreate, edit, weaken or remove any of its 26 tests. R4 must pass all 26 unchanged.

Use real temporary venvs created by the selected Python, real subprocesses and
native `run_verification` artifacts. Keep venvs and logs in the retained pytest
basetemp; do not automatically delete them on failure. No network is needed.

- Create a venv without pip and a marker module in its own site-packages. Record
  a passing explicit-executable control. Prove both bare aliases and `bash -lc`
  preserve `sys.prefix`, `sys.base_prefix`, marker visibility, literal arguments
  and the selected executable. Test venv directory names containing spaces,
  quotes and literal shell metacharacters. Assert no interpolation side effect.
- Exercise the explicit-pin and automatic-fallback branches, and the
  already-satisfying PATH branch. For deterministic selection fixtures, control
  only the test's discovery candidates; run the selected venv and generated
  launcher as real subprocesses. Assert the reported lexical interpreter agrees
  with the executable used for pip alignment. Cover a relative discovered path
  with distinct discovery and target-repo directories.
- Add a native `all_present_ok` case with directory A and repository B each
  containing a different real venv at the same relative PATH entry. Require
  actual prefixes, marker visibility and pip alignment to select A. Exercise
  versioned aliases as well as both bare names, so anchoring only the latter
  cannot pass. Cover symlink-directory/`..` spelling
  and mixed satisfying bare aliases: preserve each alias's discovered venv and
  explicitly assert the documented metadata/pip preference. Retain a mutant
  that omits execution-side PATH anchoring; its two-directory control must fail
  on the intended identity assertion while the positive control succeeds.
- Cover empty and missing PATH with a satisfying absolute pin, rather than
  assuming either discovers the fixture venv through `all_present_ok`. For empty
  PATH, put a nominally satisfying but unprobeable versioned executable in A:
  require native shadow rejection and no suite-side candidate effect. A retained
  mutant using implicit `shutil.which(name)` must expose the discovery/execution
  mismatch after successful fixture setup. For missing PATH, verify the C-library
  default and Python fallback policy independently of the host's current PATH.
- Add a real delegated-interpreter fixture: a versioned wrapper in an absolute
  PATH directory delegates via a distinct name found in relative PATH entries
  under A and B. The delegate name must never be a shim alias or shadow. Each
  delegate runs its own real venv and records probe/execution prefix identity in
  per-case JSON. A native fallback run must probe and execute A consistently;
  a mutant omitting probe-side anchoring must expose B-probe/A-execution drift.
  Both positive setup and the intended identity failure must be demonstrated.
- Verify consumed explicit `PATH=` overrides use repository B, including an
  override byte-equal to inherited relative PATH; an unrelated leading assignment
  must leave inherited PATH anchored to A. Cover a fresh-process post-aggregate
  command from C: the selected launcher's absolute venv still wins for bare Python,
  inherited ambient PATH anchors to C and consumed overrides to B. Preserve the
  native artifact and log resealing checks. This does not promise historical
  ambient lookup or revalidate all names in a reused shim.
- Create a second venv with stdlib `ensurepip` provisioning. Run native env
  refresh using the existing `python -m pip --version` argv shape and a marker
  suite. Require its captured pip location, recorded aligned argv and suite
  prefix to name that same venv. This proves real pip selection, not a package
  installation or network action. Missing ensurepip is a prerequisite failure,
  not a skipped acceptance case.
- Force symlink creation to fail only in launcher construction and execute both
  fallback files using a metacharacter venv name. Assert prefix and marker
  visibility, literal argv forwarding and a nonzero target exit status. Compare
  both fallback files byte-for-byte with the launcher. Retain a double-quote
  interpolation mutant and prove the metacharacter witness rejects it for its
  actual side effect or identity failure after successful fixture setup.
  Keep the existing symlink-backed alias test unchanged.
- Exercise the unchanged fail-closed guard with an unsatisfiable pin and require
  that native verification executes neither env refresh nor suite. Verify a
  present-but-unprobeable versioned candidate remains shadowed and no-spec/no-pin
  resolution still adds no shim. Do not strip the outer runner's PATH or rely on
  an unauthenticated inherited-shim marker.
- Before the runtime edit, observe RED on the new identity/pip cases and the
  passing direct control, then freeze this new test file's hash. All original
  tests remain byte-identical. Temporary mutants that restore resolved-target
  launching or resolved pip metadata must fail the corresponding new tests;
  mutants live only in retained fixtures and never alter the candidate or frozen
  tests. A mutant failure counts only after confirming setup and its positive
  control completed, and must identify the intended identity assertion.
  Parse login-shell identity from a per-case JSON file written by the child,
  so incidental profile stdout cannot masquerade as malformed test evidence.

### `phase-loop-runtime/tests/test_verification_dotdot_execution_428.py` (create)

Add supplemental real-venv/native-artifact tests without changing the frozen
file. Every fixture, including failures, stays under a fresh retained basetemp.

- Reproduce both exact-lexical and physical direct invocations in a symlink/`..`
  fixture with distinct real venvs and marker paths. Record actual child JSON;
  do not infer venv identity from the shared base executable or fabricated versions.
- Use fixture-local `sitecustomize.py` startup records in the two real venvs
  to observe which environment native full-version probes and execution use.
  Preserve the actual full-version query and outputs. Require probe, both bare
  launchers, real `python -m pip --version` refresh and suite to select the
  physical directory reached by the declared path. Keep lexical discovery/log
  metadata and verify the actual aligned pip argv/location separately. Include
  a passing direct physical control and retained exact-lexical mismatch evidence.
- Cover relative and absolute PATH entries with symlink/`..` in `all_present_ok`,
  both bare aliases and an unshadowed versioned alias, with caller and repository
  directories different. Prove the physical environment survives all three
  consumers. Also exercise byte-equal consumed overrides and a later-process
  append with the reused pin and current inherited/override anchors; preserve
  native artifact/log resealing. Existing no-`..` cases stay unchanged.
- A PATH entry `missing/../existing-bin` must remain untraversable: conversion
  must not introduce a previously undiscovered executable. Cover a nominally
  satisfying but unprobeable versioned name in the existing-bin counterpart,
  assert no suite effect, and retain the corresponding native failure artifact.
  Include a positive traversable-directory control so unconditional rejection
  cannot pass. Check entry order, duplicates and unchanged no-`..` strings.
- Observe native supplemental RED against the retained R3 implementation before
  applying R4 source changes, then freeze the supplemental test hash. Run all
  original 26 tests unchanged alongside it. Retained mutants omitting each of
  the new probe, launcher, pip and child-PATH conversions must fail the intended
  identity/lookup assertion after successful setup and positive controls. Do not
  count a setup exception, missing prerequisite, skip or xfail as acceptance.

### `phase-loop-runtime/README.md` and `CHANGELOG.md` (modify)

Document that an explicit `automation.python` virtual-environment pin preserves
that environment for bare Python and pip refresh while still enforcing the
repository's Python constraints. Document relative PATH anchoring during guarded
discovery, verification and version probes, the deliberate empty-PATH discovery
change, preserved missing-PATH discovery default, repository-relative consumed
overrides and later-process anchors, the no-pin mixed-alias/profile limits,
and the R4 directory-only conversion for traversable `..` paths. Explain that
discovery/log metadata remains lexical while probe/launcher/pip and child PATH
use the physical directory spelling when needed, retaining the final executable
symlink; this deliberately differs from direct Python's lexical `..` behavior.
Absent/untraversable PATH entries are preserved, not collapsed into new candidates.
Document unchanged no-`..` entry strings
and remaining nested-test/redaction
limitations. Add an Unreleased entry
qualified with agent-harness#428. Do not claim a release, full-suite success or
completion of the dependency repair in agent-harness#841.

## Dependencies and order

1. Register the R4 amendment with native manifest/handoff helpers, commit only this
   plan and its owned manifest row, and obtain a fresh complete four-vendor plan
   review before supplemental tests or further implementation. Preserve the R3
   failed source/doc/test bytes and failed lifecycle event; do not manufacture
   a clean candidate or transfer its plan votes. The agent-harness#828 publication
   owner remains untouched.
2. Reverify the already provisioned owned `phase-loop-runtime/.venv` and locked test
   group on Python 3.14. Record the interpreter, uv version and selected runtime
   module hash. Confirm stdlib venv/ensurepip and `/bin/sh`/bash prerequisites.
   No dependency-manifest or frozen-contract change is planned.
3. Write only the supplemental tests; run native RED/control against the retained
   R3 source. The existing six-module R3 after-run is the R4 before baseline only
   while its exact source/test/dependency/environment inputs remain unchanged;
   otherwise refresh that baseline. Freeze the supplemental hash, implement the
   R4 source/doc delta, then run native GREEN of both frozen acceptance modules
   and the same complete existing guard inventory again. Preserve all outcomes.
4. Preserve every outcome and fixture, run exact-source four-vendor review,
   and encrypt/independently restore evidence before eligible publication or
   cleanup. Install the repaired runtime into an owned environment, verify its
   source hashes and repeat the native identity/pip controls using that installed
   copy with source checkout paths removed from PYTHONPATH before relying on it.
   No global or fleet replacement is implicit.

## Verification

Use `uv sync --project phase-loop-runtime --group test --python 3.14 --locked`,
with `UV_PROJECT_ENVIRONMENT` bound to this worktree's lexical absolute venv.
Invoke native `verification_evidence.run_verification` with that same project
refresh, an absolute lexical venv `python_pin` and the following effective suite:

```yaml
automation:
  suite_command:
    - env
    - PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
    - phase-loop-runtime/.venv/bin/python
    - -m
    - pytest
    - -q
    - --junitxml=.phase-loop/diagnostics/venv-identity-428-20260914/red/junit.xml
    - --basetemp=/tmp/ah428-venv-red-20260914
    - phase-loop-runtime/tests/test_verification_venv_identity_428.py
    - phase-loop-runtime/tests/test_verification_dotdot_execution_428.py
```

The displayed argv is the shape; R3's named RED paths are retained and must not
be reused. Use fresh `red-r4`, `control-r4`, `green-r4` and corresponding fixture
names. Before each run, render distinct native
run directories, JUnit files and fresh short real `/tmp`
basetemps for RED, control, GREEN, mutants and installed-runtime controls. No
acceptance test may skip or xfail. Validate each native artifact; expected RED
must remain a nonzero artifact, never converted to a passing native result.

Derive the regression inventory using `rg -l` over the tests tree for
`_interpreter_path|_build_interpreter_shim|_resolve_suite_interpreter|_align_install_interpreter|_interp_shim|_interpreter_full_version|_run_process|python_pin|SuiteInterpreter|suite interpreter:|automation\.python|_append_verification_command`.
At the input head the expanded inventory includes:
`test_verification_interpreter_guard_221.py`,
`test_suite_interpreter_satisfies_requires_python.py`,
`test_verification_evidence.py`, `test_cr_fixes_pr220.py` and
`test_legible_evidence.py` and `test_legible_review_repairs.py`.
Rerun the expanded search before RED and include any
additional matching module; this inventory is not a future fixed test-count gate.
Run all matching modules unchanged through native verification before and after
implementation. Compare collected node IDs and per-node JUnit
outcomes; allow no newly failing node or lost passing node. The three known
inherited-shim cases and four redaction cases may remain failed and must be reported as such, with their
original full artifacts intact. This comparison is regression evidence, not a
green suite. Any unexpected failure or changed failure cause blocks source
closeout until explained and reviewed. A newly failing resolved-symlink-shape
assertion is a blocking owning-lane finding, not authorization to amend that test.
Never exclude, weaken or rewrite those
frozen tests to manufacture a passing result.

Run `git diff --check`, native manifest validation and native `docs-audit` against
the actual candidate. Verify all existing tests, dependency files, unchanged
guard functions and artifact vocabulary hashes remain unchanged. The only
version-probe changes are its PATH environment and directory-only executable
conversion; inspect its AST delta accordingly. The source/contract vocabulary
still matches the quoted constants above; no new failure kind or field is added.
The canonical packaged runtime/verification contract was searched for a promise
that bare aliases link directly to the interpreter; none was found. Preserve
that contract's bytes. This bounded repair
does not justify rerunning the expensive repository-wide suite.

Execution may write only its owned source/doc/test/plan/manifest boundary,
ignored `.phase-loop/diagnostics/venv-identity-428-20260914/**`, native handoff and
reflection paths, owned venv and explicitly recorded temporary fixtures.

## Acceptance criteria

- [ ] Native RED/control proves the selected environment is lost before repair;
  the frozen R3 test file and all original test hashes remain unchanged, and
  supplemental R4 RED is observed before freezing its hash and changing source.
- [ ] The complete new native suite passes without skips, including both aliases,
  login shell, selection branches, lexical paths, real pip refresh, argument/exit
  behavior, symlink fallback and directory-only execution conversion; both frozen
  acceptance modules pass and retained mutants fail for the intended reason.
- [ ] The complete existing guard-suite comparison has no new failing or lost
  passing node; unchanged safety controls pass. Remaining inherited-shim failures
  remain explicitly failed and do not imply agent-harness#428 acceptance.
- [ ] Native docs/manifest validation and diff/hash checks pass; source review
  converges on the exact candidate; encrypted evidence independently restores.
- [ ] The owned installed runtime matches the reviewed source and passes native
  identity and pip controls before use. Publication and roadmap acceptance remain
  subject to their existing independent gates.
