# agent-harness codebase review — 2026-09-01

Full-codebase review of `Consiliency/agent-harness` at `d96f85a` (`phase-loop-runtime`
0.7.14). Every finding below was verified against the tree by reading the code; each
carries a `file:line` anchor (paths are relative to
`phase-loop-runtime/src/phase_loop_runtime/` unless stated). Findings are numbered
per section so they can be turned into issues one-for-one.

**Method.** AST metrics over the whole package (function sizes, nesting, exception
handling, subprocess/env inventory, import graph, comment density); a full local run of
the standalone suite; a broad-rule `ruff` survey; a wheel build; and targeted reads of
the hot spots surfaced by scouts covering every module group. Nothing in this document
is a style nit.

---

## 0. Executive summary

The runtime is unusually careful in places — atomic state writes (`state.py:22-36`),
flock-based dispatch locking with ancestry-aware re-entrancy (`dispatch_lock.py`),
timing-safe approval hashing, loopback-only sidecars, trusted-publishing release
workflows, a CI "suite gate" that cannot be satisfied by a skipped job, and zero
TODO/FIXME debt anywhere in shipped code. The suite is large (≈5,450 tests, 4,729 pass
locally) and the culture of narrating *why* in comments is real.

The same culture has produced the codebase's main liability: **accretion without
consolidation**. The core engine is one 13,015-line module whose main function is 3,884
lines with 52 parameters and nesting depth 11; ~2,100 lines of it exist to shepherd one
historical PR (`Consiliency/agent-harness#347`) and push to `main`; an 8,443-line opt-in
canary subsystem sits beside it; and cross-cutting behaviours (git topology capture,
event-ledger parsing, subprocess timeouts, exception policy, env-var defaults) are
re-implemented per call site rather than owned once. That is what makes the correctness
findings below possible: the same knob defaulting differently in two modules, a gate
registry with two stacked silent-disable paths, a lease store whose read-check-write is
not atomic, and 128 of 203 subprocess calls with no timeout.

**Twelve things I would do first** (details in the sections referenced):

| # | Action | Why | Ref |
|---|--------|-----|-----|
| 1 | Make gate failures *visible*: narrow `except Exception` in `load_builtin_closeout_validators` and `run_closeout_validators` to `ImportError`, and record a `gate_unavailable` finding instead of `continue`/`pass` | Two stacked fail-open paths can silently remove every closeout gate | G-1, G-2 |
| 2 | Reconcile `PHASE_LOOP_VERIFY_ENFORCE` default (`hard` in `closeout_validation.py:129`, `warn` in `runner.py:6551` / `train_runner.py`) into one resolver | Same env var, opposite meaning when unset | G-6 |
| 3 | Add a single `run_git()` helper with mandatory timeout and use it for the 128 untimed subprocess calls; start with the network-touching ones | A hung `git fetch`/`gh` freezes the orchestrator forever | C-1 |
| 4 | Cache `collect_git_topology` per run/HEAD; stop recomputing ~10 git subprocesses (+ possible `gh pr list`) on every `append_event`/`write_state` | Largest per-tick cost; 47 append sites in `runner.py` | E-1 |
| 5 | Extract the `_legible_*` PR-347 subsystem (`runner.py:7101-9216`) out of the engine — into its own module or, more likely, an archived script | Repo-specific ceremony with pinned SHAs shipped in the public wheel | A-2 |
| 6 | Fix `LeaseStore.acquire` TOCTOU (hold the flock across read → check → append) and the non-atomic `plan_manifest._write_manifest` | Both defeat the module's stated purpose under the parallel dispatch they exist for | S-1, S-2 |
| 7 | Catch a small set of expected exceptions in `cli.main()` and print a one-line error + exit code | Today only two exception types avoid a traceback | C-4 |
| 8 | Split `run_loop` along the seams already visible (dispatch / prepare / finalize / closeout / work-unit / delegation) — mechanically first, no behaviour change | 3,884-line function; every branch is untestable in isolation | A-1 |
| 9 | Document (and test) the developer prerequisites the suite silently assumes: full-history clone, `phase-loop` on PATH, `build` installed | 12 local failures: 11 environment, 1 product bug (C-11, the 4 `VerificationEvidenceHardening243Test` reds) | T-1 |
| 10 | Fix the `fab_delta.py` invalid escape sequences and add `-W error::DeprecationWarning` import smoke to CI | Will become a `SyntaxError` on a future Python | Q-6 |
| 11 | Stop the *whole-field* `suite_command` replacement (`_redact_validation_payload_in_place` / `_command_field_forbidden_kind`); do **not** narrow the shared `_FORBIDDEN_METADATA_PATTERNS` entry at `redaction.py:138` | On every real Linux/macOS install the `suite_command` evidence field is replaced by `<redacted:suite_command>`; 4 tests already red | C-11 |
| 12 | Make `phase-loop install --symlink` actually symlink (or rename the mode and stop reporting `mode: symlink`) | `_apply_action` ignores `mode`; the installer script relies on links that are never created | C-9 |

---

## 1. Shape of the codebase (measured)

| Metric | Value |
|--------|-------|
| Source (excl. `skills_bundle`) | 184 files, 118,200 lines; 128,192 incl. bundle |
| Tests | 439 files, 182,840 lines, 28 MB |
| Functions | 3,745; **55 over 150 lines, 19 over 300, 12 over 500** |
| Largest functions | `runner.run_loop` 3,884; `runner._prepare_phase_launch` 1,888; `train_runner._run_train_unfenced` 1,287; `runner._finalize_phase_launch` 1,158; `conformance.outside_agent_conform_evidence._validate_chronology` 1,154; `cli.build_parser` 743; `runner._perform_phase_closeout_impl` 741 |
| Max nesting depth | 11 (`run_loop`), 10 (`state_ops._monitor_status`, `_finalize_phase_launch`, `roadmap_assumptions._evaluate`) |
| `except Exception` / bare | **261**, of which **138** are silent (`pass`/`return`/`continue`) — `runner` 33, `train_runner` 31, `agy_canary_evidence` 23, `panel_invoker` 22 |
| `subprocess.*` calls | **203; 128 without `timeout=`**; 3 `shell=True` |
| Env vars read | 38 distinct (`PHASE_LOOP_*` mostly), none centrally documented |
| Function-level imports | 317 (`train_runner` 56, `cli` 48, `runner` 33) |
| Import 2-cycles | 13, incl. `panel_invoker↔runner`, `discovery↔plan_manifest`, `discovery↔plan_ir`, `legible_evidence↔verification_evidence`, `capability_registry↔launcher` |
| Logging | only 3 files use `logging`; `runner.py` uses `print(..., file=sys.stderr)` (11 sites) |
| Lint gate | `ruff` pyflakes only (`F`, `F841` ignored). No type checker in CI despite shipping `py.typed` |
| Wheel | 2.17 MB, 462 members, 7.2 MB uncompressed (17.5 % `skills_bundle`, 4.1 % `_contract_docs`) |
| Local suite | `4729 passed, 12 failed, 114 skipped, 603 deselected` in **14 m 25 s** serial (see §9) |
| Churn | 142 commits in Aug 2026; hottest files: `plans/manifest.json` (32/400), `CHANGELOG.md` (20) |

Comment/docstring density is bimodal: `fab_delta` 2.38 narrative-lines per code line,
`roadmap_ownership` 1.01, `fab_gate` 0.86, `train_runner` 0.71 — versus `runner` 0.12,
`plan_manifest` 0.07, `observability` 0.03. See Q-1.

---

## 2. Architecture

**A-1. `runner.py` is eight subsystems in one module; `run_loop` is a 3,884-line function.**
`runner.py:1247-5133`. Signature alone is 52 parameters (`runner.py:1247-1300`). Inside it,
`_prepare_phase_launch` (`1652-3541`) and `_finalize_phase_launch` (`3541-4700`) are nested
closures that thread state through `nonlocal`s. Distinct responsibilities living here:
(a) the dispatch state machine, (b) work-unit scheduling (a *second* scheduler beside
phase dispatch), (c) closeout/commit mechanics incl. dirty classification and FAB
fast-forward commits, (d) branch-governance glue re-implemented over `pipeline_adapter/`,
(e) child delegation (`launch_delegated_child`, 304 lines), (f) repair/recovery
heuristics, (g) the legible PR-347 subsystem (A-2), (h) governed pre-merge/promotion.
`StateSnapshot(...)` is hand-built 11 times and `LoopEvent(...)` 47 times with ~15
kwargs each — a `blocked_snapshot(...)`/`emit(...)` helper pair would remove several
hundred lines outright.
*Recommendation:* split mechanically first (no behaviour change), in this order of
risk: (g) → (c)+(h) → (e) → (b) → (a). Introduce a `RunContext` dataclass to replace the
52-parameter signature. Target: no function over 200 lines in the engine.

**A-2. ~2,100 lines of one-PR bootstrap code are baked into the engine and shipped in the wheel.**
`runner.py:7101-9216` (`_legible_*`, `_run_legible_*`, `_seal_legible_*`,
`_recover_legible_*`). Hard-pinned constants at `runner.py:7170-7175`
(`_LEGIBLE_REFRESH_BASE/HEAD`, `_LEGIBLE_TESTS_LANDING`, `_LEGIBLE_PR_BODY_SHA256`,
`_LEGIBLE_CANDIDATE_PR_NUMBER = 430`); `gh pr view 347 --repo Consiliency/agent-harness`
(`7199`, `7772`, `7830`, `8242`); `git fetch origin refs/pull/347/head` (`7909`, `8131`);
`git push origin {server_merge}:refs/heads/main` (`8307`). The same repo-specific roadmap
is pinned elsewhere in the runtime: `roadmap_assumptions.py:30`
(`CANONICAL_ROADMAP_REL = "specs/phase-plans-v10.md"`), `fabpub_tdd_chronology.py:63`,
`runner.py:8783`. The legible subsystem also creates the `runner↔legible_evidence`
cycle (`legible_evidence.py:2012` imports `runner` inside a function).
*Recommendation:* move to `_legacy/legible_347.py` (or a `scripts/` one-off) with its
own tests; strip repo-specific constants from `roadmap_assumptions`/`fabpub_tdd_chronology`
behind explicit configuration. If the ceremony is genuinely complete, delete it and keep
the evidence in git history.

**A-3. `agy_canary_evidence.py` (8,443 lines) is an opt-in subsystem with its own HTTP
server, zip handling, `ctypes` `renameat2` binding (`2975-2998`), and 23 broad excepts,
referenced only from `panel_invoker.py` (3) and `cli.py` (5).** `cli.main()` inlines 90
lines of its command dispatch (`cli.py:1057-1148`) *before* the generic dispatcher.
*Recommendation:* extract to `phase_loop_runtime.canary` (or an optional extra /
separate distribution) behind the existing plugin seam; register its CLI commands via
`profile_commands` like the dotfiles profile already does.

**A-4. Three "TDD-chronology / proof" verticals overlap.** `fabpub_tdd_chronology.py`
(1,660 lines, hard-coded "owned paths is not exactly 25" at `440-447`, no `src/`
importer — CLI only), `conformance/outside_agent_conform_evidence.py` (1,722 lines, one
1,154-line function), and `legible_evidence.py` (2,232 lines) each walk git history to
prove ordering. They share no helper for commit-parent walks, canonical digests
(`fabpub_tdd_chronology.py:137-141` reimplements `verification_evidence._canonical_artifact_digest`,
currently byte-identical by luck of `ensure_ascii` defaults) or torn-line repair
(`fab_gate.py:412-421` is a self-described "DELIBERATE parallel copy" of
`train_ledger._repair_torn_trailing_line`).
*Recommendation:* one `git_history.py` (parents, blob hashes via a single
`cat-file --batch`) and one `canonical.py` (digest recipe) that all three import.

**A-5. Import cycles resolved by function-level imports (317 of them).** The 13 two-cycles
above are real design cycles, not accidents; `panel_invoker.py:2484` importing from
`runner` is the clearest sign the "panel" layer knows too much about the loop.
*Recommendation:* after A-1/A-2, add an import-linter contract (`importlinter`) so cycles
cannot regrow; permit function-level imports only for optional dependencies.

**A-6. Module-level mutable caches with `global` (17 sites).** `models.py:425-460`
(`_PROTECTED_CATEGORY_*`), `gate_posture.py:39-55` (never invalidated),
`capability_registry.py:675`, `executor_availability.py:62` (`_auth_cache`, unsynchronized
while `worker_pool.py:92` dispatches from a `ThreadPoolExecutor`), `agy_canary_evidence.py:5398,5432`.
*Recommendation:* `functools.lru_cache` on a pure loader with an explicit `cache_clear()`
for tests, or a per-run `Registry` object passed through `RunContext`.

---

## 3. Correctness & reliability

**C-1. 128 of 203 subprocess calls have no timeout; several touch the network.**
Network: `runner.py:7607, 7907, 8129, 8235, 8257, 8318` (`git fetch origin main`, the
same line six times, `check=True`), `runner.py:7827-7837` / `7196-7224` (`gh pr view`),
`runner.py:8328-8347` (30× `gh pr view` in a 1 s polling loop — a single wedge blows the
30 s budget), `cross_repo_channel.py:225-234` (`git fetch`/`checkout`, `check=True`, the
train's upstream-injection primitive), `train_runner.py:1017-1019` (`git fetch` in
`_fab_delta_readmit`), `claude_agent_view.py:223,275,304,365,380,395,427` (all seven
`claude` CLI calls incl. `attach` with `stdout=PIPE`), `launcher.py:1948`
(`run_auth_preflight`, `shell=True`, no timeout — contrast `executor_availability.py:66-72`
which does the same probe with a 10 s timeout and a comment explaining why).
Local but unbounded: `git_ops.py:57-64,79-88`, `git_discipline.py:305-312`,
`plan_manifest.py:1538-1553` (history walks), `legible_evidence.py:211,218` (base `_git`
helpers), `tdd_receipts.py:202` (runs the phase's own RED test command with no bound),
`fab_canonical.py:410-507` (the 300 s `cat-file --batch` timeout only applies in
`finally`, after blocking `readline()`/`read()` return).
*Recommendation:* one `git_ops.run_git(repo, *args, timeout=..., check=...)` returning a
typed result; forbid raw `subprocess.run(["git", ...])` via a ruff `banned-api` rule.
Add a `TimeoutExpired` regression test for one network path.

**C-2. `except Exception` is the default exception policy (261 sites, 138 silent).**
Representative: `runner.py:437-449` swallows `AttributeError` from a refactor the same
as "git absent"; `closeout_validators.py:191-195` (see G-1); `consiliency_layout.py:377,397`
(`pass`, no comment); `doctor.py` 11 sites. Most are individually justified in comments,
which is precisely the problem: the justification ("degrade gracefully") is repeated per
site instead of being a policy with a log line.
*Recommendation:* adopt `logging` package-wide (one `_LOGGER.debug(..., exc_info=True)`
inside every degrade path), narrow to `(OSError, subprocess.SubprocessError, ValueError)`
where that is what is expected, and enable ruff `BLE001` with per-site `noqa` reasons.

**C-3. `governed_premerge.py:495` `seen_block = True` is dead** (the only `F841` in the
tree). Terminal reason is classified from `last_reason` alone (`504-515`), so a run with
real block findings that ends on a structural hold reports the structural reason. Already
tracked as `Consiliency/agent-harness#341` — but `F841` is disabled repo-wide because of
it, which is backwards: fix the bug, enable the rule.

**C-4. `cli.main()` converts only two exception types into clean errors.**
`cli.py:1149-1184` catches `AmbiguousRoadmapError` and `RoadmapAuthorityError`; the
`status`/`run` path at `1535-1538` catches only `AmbiguousRoadmapError`. `FileNotFoundError`
(missing roadmap), `SupersededRoadmapStateError`, `DispatchLockContention`,
`subprocess.CalledProcessError` (from every `check=True` fetch in C-1), and
`KeyboardInterrupt` reach the user as tracebacks with exit 1. Exit codes are otherwise
inconsistent (0/1/2 chosen per command).
*Recommendation:* a `PhaseLoopError(exit_code)` base class; `main()` catches it plus
`KeyboardInterrupt` (130) and `BrokenPipeError`; document the exit-code table.

**C-5. `PHASE_LOOP_VERIFY_ENFORCE` has opposite defaults in two modules.** See G-6.

**C-6. Roadmap parsing is regex-first and self-documents its own regressions.**
`roadmap_lint.py:70-73` `PHASE_HEADING_RE` requires exactly `### Phase N — Name (ALIAS)`;
`roadmap_ownership.py:283-286` records that lower-casing `phase` or using `:` instead of
an em-dash silently dropped a phase (owners `['RELEASE'] -> []`, preflight `1 -> 0`), and
`141-154` admits a U+FEFF indent still evades the guard. `goal_coverage.py:100-103`
`_ACCEPTANCE_SECTION_RE` rejects `## Acceptance Criteria (Phase 3)`. `discovery.py`,
`plan_manifest.py`, `plan_ir.py`, `roadmap_*.py` each carry their own markdown slicing.
*Recommendation:* one tolerant, tested roadmap parser (`roadmap_parser.py`) producing a
typed document; every consumer reads the typed document. (`roadmap_lint.py:200-207`
already emits a lint-level `invalid phase heading` error for near-miss headings; the gap
is the per-consumer slicing, not the lint.)

**C-7. `worker_pool.py`/`executor_availability.py` race on a cold cache** (`_auth_cache`
read/write without a lock from threads). Benign today (duplicate probe), documented
nowhere.

**C-8. `baml_modular.py:268-310` derives JSON Schema by regex-scanning raw `.baml`
text** (`_function_return_type`, `_class_fields`, `_enum_literal_map`) instead of using
BAML's compiler output; any unmatched syntax degrades to `BamlValidationError` at call
time. The `baml-py` pin (`>=0.222,<0.223`) is what keeps this safe.
*Recommendation:* check in the generated `baml_client` (or validate schemas against
`BamlRuntime` at import) and add a test that every `.baml` function's schema round-trips.

**C-9. `phase-loop install --symlink` never creates a symlink.** `skill_install.py:134-145`
`_apply_action` validates nothing about `mode`, always `rmtree`/`unlink`s the destination
and `shutil.copytree`s; `mode` only influences the *planned* label (`126-131`). There is
no `symlink_to`/`os.symlink` in `skill_install.py`, `cli.py` or `launcher.py`. Since
`symlink` is the CLI default (`cli.py:1498`) and `install-agent-harness.sh:140-141` passes
`--symlink` explicitly ("so the --symlink skill links never dangle"), every install
reports `mode: symlink` and produces copies; a pre-existing real symlink is replaced by a
copy on the next `--apply`. `tests/test_phase_loop_skill_install.py:87-104` asserts
`.exists()` but never `.is_symlink()`. Note that overlays and `_rewrite_skill_name`
mutate `SKILL.md`, so a true symlink cannot carry per-harness overlays — decide whether
"symlink" should mean "symlink the unmodified skill dirs and write only the rewritten
`SKILL.md`", or retire the mode and stop advertising it.

**C-10. `SupersededRoadmapStateError` is never caught (and never imported) by the CLI.**
`discovery.py:412-428` raises it for a stale `.phase-loop/state.json` after a roadmap
flip; `cli.py` imports only `AmbiguousRoadmapError`. `select_roadmap` is called at
`cli.py:1270, 1401, 1420, 1431, 1536, 2457, 3871, 4173`; a missing roadmap
(`discovery.py:460-461` `FileNotFoundError`) tracebacks from all of them
(`phase-loop --repo /nonexistent status` reproduces). `discovery.resolve_repo`
(`362-368`) swallows the `git rev-parse` failure, so a bad `--repo` falls through instead
of failing fast. Same root cause as C-4.

**C-11. Redaction destroys the `suite_command` evidence field on ordinary machines.**
`redaction.py:138` `absolute_private_path` matches any `/home/…` or `/users/…` path;
`_command_field_forbidden_kind` (`461-471`) consults it first and
`_redact_validation_payload_in_place` (`443-444`) then replaces the **whole** field with
`<redacted:suite_command>`. Reproduced: `apply_diagnostics_redaction({"suite_command":
[sys.executable, "-m", "pytest", "-q"]})` → `'<redacted:suite_command>'` whenever the venv
is under `$HOME` — i.e. on essentially every Linux/macOS developer or self-hosted CI box.
This undermines the auditability that `redaction.py`'s `#243`/`#269` history is trying to
protect, and is why four `VerificationEvidenceHardening243Test` tests are red locally.
`install_status.py:79-86` carries the same `/home/`,`/Users/` forbidden-substring
assumption (inert today). See X-5 for the fix.

---

## 4. Gates and fail-open paths

The evidence gates are the product's differentiator, so their fail-open paths matter
more than anywhere else.

**G-1. A crashing validator is invisible.** `closeout_validators.py:191-195`:
```python
for fn in tuple(_VALIDATORS):
    try:
        produced = fn(ctx) or ()
    except Exception:
        continue
```
Tested as intended behaviour (`tests/test_closeout_validator_hook.py:112-115`: a raising
validator still yields `terminal_status == "complete"` *under `PHASE_LOOP_REVIEW=block`*).
No warn finding, no log line.
*Fix:* append `ReviewFinding(code="gate_crashed", severity=<block under block mode>)`
and log with `exc_info`.

**G-2. A broken gate module vanishes from the registry.** `closeout_validators.py:307-338`
wraps each built-in import (`doc_delta_validator`, `verification_evidence_validator`,
`visual_evidence_validator`, `visual_avatar_evidence_validator`, `fab_gate`) in
`except Exception: pass`. The docstring's justification is "an incremental checkout
missing a module" — that is `ImportError`, not `Exception`. `fab_gate.py:168-217` pulls a
long import list from four modules; any `AttributeError` there silently removes the FAB
gate. No test asserts the expected five are registered after load.
*Fix:* `except ImportError`, log at WARNING, and add
`assert set(registered_closeout_validators()) ⊇ BUILTINS` to the suite.

**G-3. Default posture is `warn`; under `warn` every finding is rewritten to `warn`.**
`closeout_validators.py:33-34,197`. Documented ("autonomy-first"), but it means every
gate in this section enforces nothing unless `PHASE_LOOP_REVIEW=block` is exported.
Worth confirming block mode is actually set on the paths that matter (CI, governed runs).

**G-4. The FAB gate is dormant by its own docstring** (`fab_gate.py:1876-1881`: "no live
producer writes `fab_gate_inputs`… this validator is inert in practice TODAY");
`fab_gate_validator` returns `[]` when inputs are absent (`1927-1935`). ~2,000 lines of
fail-closed logic currently unreachable in a real run. Decide: wire it or shelve it.

**G-5. The pixel-decode visual gate is switched on by the executor's own self-report.**
`visual_avatar_evidence_validator.py:131-159`: real decode runs only when the terminal
payload sets `visual_render_declared`; otherwise a non-escalatable `warn` (`140-144`).
*Fix:* derive "this phase renders visuals" from the roadmap/plan, not from the
executor's output.

**G-6. Same env var, opposite defaults.** `closeout_validation.py:127-129` treats unset
`PHASE_LOOP_VERIFY_ENFORCE` as **`hard`**; `runner.py:6551` and `train_runner.py:1972`
treat it as **`warn`**. Whichever module runs decides whether verification is enforced.
*Fix:* one `enforcement.verify_enforce_mode()`; grep-guard against direct `os.environ`
reads of the name.

**G-7. The generic verification gate checks for a truthy string, not an artifact.**
`verification_evidence_validator.py:22-36` (`_has_verification_artifact`) passes on any
non-empty `verification_artifact_path` or even `artifact_paths["root"]`, while the RG
gate at `closeout.py:340-401` actually loads and hash-seals the artifact. Two checks for
one concept (`closeout.py:620-633` vs `verification_evidence_validator.py:22-49`).
*Fix:* make the generic validator call `validate_verification_artifact`.

**G-8. `closeout_evidence_audit.py:25-45`** returns `skipped` for any commit message that
doesn't match the two narrow claim regexes, and `_claim_matches_evidence` (`73-90`)
accepts a shared stem or any ≥4-char token appearing anywhere in the diff. Fine as an
advisory; too loose to be a `block` gate (it does block once opted in via frontmatter,
`runner.py:12084-12094`).

**G-9. `.phase-loop/evidence-audit.yaml` can disable tiers/detectors and is loaded straight
from the working tree** (`evidence_audit_config.py:51-97`) with no "not git-tracked" rule
like `fab_provenance` has. Confirm whether a reviewed diff can modify it; if so a phase can
switch off its own audit.

**G-10. `dispatch_lock.py`** — checked closely; sound. flock + live-PID ancestry means a
stale holder cannot be mistaken for self.

---

## 5. Concurrency and state

**S-1. `LeaseStore.acquire` is check-then-act without a lock across the check.**
`lease_store.py:424-486`: `project_all(read events)` → conflict scan → `_append_raw_event`
(flock covers only the append, `386-397`). Two parallel acquirers over overlapping scopes
can both be granted. No concurrency test exists (`test_lease_store*.py` are sequential).
*Fix:* take `LOCK_EX` on the events file for the whole acquire/renew/release; add a
two-process race test.

**S-2. Non-atomic and unlocked read-modify-write of state files.**
`plan_manifest.py:429-435` `_write_manifest` is a plain `write_text` (contrast
`state.py:28-36`, `state_degradation.py:120-128` which use `mkstemp` + `os.replace`);
`plan_manifest.py:178-282` (`append_entry`, `update_lifecycle`), `state.py:121-158`
(`write_work_unit_state`), `state_degradation.py:77-98` are load → mutate → write with no
lock. `events_migration.py:35-89` reads the ledger, rewrites a copy, `os.replace`s it —
any event appended concurrently via `events._append_jsonl` (O_APPEND) in between is lost.
*Fix:* an `atomic_json.update(path, fn)` helper (flock + mkstemp + replace) used by all
five; refuse to migrate while a dispatch lock is held by another PID.

**S-3. Ledger is re-parsed ≥6× per loop tick and grows unbounded.** `events.read_events`
(`events.py:76-89`) is a full read + `json.loads` per line, no cache. `reconcile()`
(`reconcile.py:36-491`, itself 455 lines) calls it at `129, 749, 846, 974, 1014`;
`runner.detect_stuck_loop` (`6264`) again. Only `archive-state` shrinks the file.
*Fix:* parse once per tick into a `Ledger` object passed to `reconcile`; consider a
rolling index (byte offset + count) persisted beside the ledger.

**S-4. Global caches under threads** — see A-6 / C-7.

---

## 6. Security

Posture is good overall. Checked and OK: no `pull_request_target`; `permissions:` scoped in
every workflow; trusted publishing (`id-token: write`) for both PyPI packages; the CI
suite gate cannot be satisfied by skipped jobs; `hmac.compare_digest` for approval
hashes; TLS enforced for non-loopback broker URLs (`task_message_broker_client.py:68-69`);
`doctor.py:89` registry lookups carry a timeout; the sidecar binds loopback and verifies
the peer is loopback (`claude_channel_sidecar.py:87,667`); the plugin env vars
(`PHASE_LOOP_PROFILE_PLUGINS`, `PHASE_LOOP_SKILL_SOURCE_PLUGINS`) are equivalent in trust
to `PYTHONPATH`, and a broken plugin is logged, not fatal (`cli.py:246-266`); `.gitleaks`
runs in CI.

**X-1 (medium). Sidecar write surface is half-authenticated.** `claude_channel_sidecar.py:744-792`:
`register`, `state`, `hook`, `permission/request` never call `sidecar.authenticate()`;
`message`, `permission/verdict`, `reply`, `status` do. `register_session` (`401-424`)
overwrites an existing session's `trust_state`/`auth_posture`; `update_session_state`
(`435-449`) can force `channel_health = "ready"`, which `preflight()` (`554-560`) trusts.
All `GET`s (`704-739`) — full event/message history — are unauthenticated. Loopback-only
limits this to any local user/process, which on shared CI hosts is not nothing.
*Fix:* authenticate every mutating endpoint (the local hook can carry the token via
env), and gate reads too.

**X-2 (medium). Unbounded request body.** `claude_channel_sidecar.py:797-801` reads
`Content-Length` bytes with no cap; `json.loads` is non-strict (duplicate keys last-wins)
while the broker path deliberately uses `decode_strict_json` (`task_message_broker.py:30-42`).
*Fix:* cap at e.g. 1 MiB; share the strict decoder.

**X-3 (low). `shell=True` probes.** `executor_availability.py:66` (constant probe strings,
10 s timeout — fine), `launcher.py:1948` (constant strings, **no timeout**),
`observability.py:1072` (operator-configured notification command, 30 s — fine, but
should be `shlex.split` + list form).

**X-4 (low). Replay window on approvals.** `task_message_resolver.resolve()` has no
consumption tracking beyond `max_source_age_seconds` (900 s); a resolved approval can be
re-resolved by a second caller inside that window. Confirm callers treat it as
idempotent by design, or add a consumed-set keyed by the RFC 8785 digest.

**X-5 (fix for C-11). Whole-field replacement, not the pattern, is the defect.**
`redaction.py:138` is one entry in `_FORBIDDEN_METADATA_PATTERNS` (`redaction.py:35`),
which is shared by three consumers: the fatal `metadata_redaction_diagnostic` closeout
gate (`redaction.py:593-611`, called from `closeout.py:711`), the diagnostics
`raw_tail`/`argv` drop (`redaction.py:319`), and `_command_field_forbidden_kind`
(`461-471`). Narrowing that pattern would stop redacting home-rooted stderr excerpts on
their way into `events.jsonl`, `state --json` and prompts — the widening that
`#243`/`#269` reverted — and even a "username-only" redaction still leaks every other
path component (`/home/<redacted>/private-client/venv/bin/python`). Leave the pattern
alone. Fix the *consumer*: `_redact_validation_payload_in_place` (`443-444`) must not
replace the whole argv because one token matched; replace the matching token with a
placeholder (or the interpreter with a stable alias such as `<python>`) and keep the
rest of the command. Add a test with `sys.executable` under a fake `/home/x` venv that
asserts the command survives *and* that no `/home/x` component is present.

**X-6 (low). Installer footguns.** `install-agent-harness.sh:129` `rm -rf "$HOME_DIR"`
where `HOME_DIR` is `AGENT_HARNESS_HOME` (user-set; if pointed at an existing non-clone
directory it is wiped); `126-127` a failed `fetch` falls back to a stale `FETCH_HEAD`
silently; `109` `curl … | sh` for `uv` with no checksum (industry-standard, but worth a
`--version` pin). `skill_install._apply_action` (`skill_install.py:134-140`) `rmtree`s any
existing directory with the target name in `~/.claude/skills` without an ownership
marker.

**X-7 (info). CI pins.** First-party actions use major tags (`@v4`, `@v5`);
`pypa/gh-action-pypi-publish@release/v1` is a floating branch in the publish workflow.
Pin to SHAs (the org action already is).

---

## 7. Efficiency

**E-1. Git topology is recomputed on every ledger write.** `events.append_event`
(`events.py:23-30`) and `state.write_state` (`state.py:22-25`) call
`attach_git_topology` → `collect_git_topology` (`git_topology.py:17-70`): `branch`,
`rev-parse HEAD`, **two `git status`** walks, upstream ×2, ahead/behind ×2, default
remote, base ref ×2, plus `for-each-ref` and a **`gh pr list` network call** whenever HEAD
matches a remote ref and `PHASE_LOOP_PR_URL` is unset (`187-208`). Nothing pre-populates
`git_topology`, and `runner.py` has 47 `LoopEvent(` sites. On a large repo this is the
dominant per-tick cost.
*Fix:* compute once per (run, HEAD, index mtime) and reuse; never call `gh` from an
event append.

**E-2. Ledger re-parse** — S-3.

**E-3. Per-file subprocess fan-out.** `runner.py:11027-11101` `_detect_dirty_renames`:
one `git rev-parse HEAD:<path>` per deletion and one `git hash-object` per untracked
candidate — O(deletions × untracked) processes; should be one `cat-file --batch-check`
and one `hash-object --stdin-paths`. `worktree_index.py:213-241,265-286`: one `git log` +
one `merge-base --is-ancestor` per (path × worktree). `_proc_cpu.group_cpu_ticks`
(`_proc_cpu.py:35-57`) scans all of `/proc` on every liveness tick.

**E-4. Polling with fixed sleeps.** `runner.py:8328-8347` (1 s × 30, each a `gh`
subprocess), `claude_channel_sidecar.py:581-592` (0.25 s GET of *all* session events for
up to 60 s ≈ 240 round-trips per `send_and_wait`), `panel_invoker` (5 sleep sites).
Prefer server-side long-poll / `since=` cursors and exponential backoff.

**E-5. Test wall-clock.** 14 m 25 s serial locally; hosted CI runs three interpreter
lanes at up to 100 min each plus a 100-min clean room. One test takes 166 s
(`test_outside_agent_redaction_separation.py::…digest_tracks_only_captured_bytes`); the
deselected chronology node ~40 min. See T-4 for `xdist`.

---

## 8. Code quality and maintainability

**Q-1. Narrative comments have replaced structure.** `fab_delta.py` has 2.4 lines of
prose per line of code; `fab_gate.py`'s module docstring is lines 1-157; per-site
justifications for `except Exception` repeat the same rationale hundreds of times. The
prose is valuable *history* but it is where the code's contracts now live, and prose
cannot be tested. Move the durable parts into typed contracts (dataclasses/enums,
assertions, tests named after the invariant) and cite issues in one line.

**Q-2. Copy-pasted vendor branches.** `panel_invoker._exec_leg` (`3579-4111`, 533
lines): codex (`3657-3766`), gemini (`3767-3997`), grok (`3998-4107`) each hand-roll the
same `for _attempt in range(2)` / liveness / soft-empty / capture skeleton; Claude has its
own 211-line `_exec_claude_tui_leg`. `invoke_board` (`4979-5546`) is 568 lines.
*Fix:* a `LegRunner` strategy with per-vendor hooks (`argv`, `classify_output`).

**Q-3. Tests reach into private seams.** 255 `monkeypatch.setattr(mod, "_…")` calls across
23 files plus 85 direct `module._name = …` assignments across 35 files; `panel_invoker`
alone exposes ~30 patched private names (`_exec_leg`, `_default_spawn`, `_leg_auth_ok`,
timing constants…). Only `spawn=` is a public seam.
*Fix:* inject `ProcessSpawner`, `Clock`, `GitClient`, `RegistryLoader` explicitly; keep
monkeypatching for genuinely external things.

**Q-4. Duplicated concepts with acknowledged drift risk.** `docs_surfaces.py:1-19`
("a third copy here is the accepted trade"); `fab_gate.py:412-421`
(torn-line repair copy); `verification_evidence_validator` vs `closeout` (G-7);
`PHASE_LOOP_VERIFY_TIMEOUT_SECONDS` read independently in `cli`, `runner`,
`train_runner`; `PHASE_LOOP_VERIFY_ENFORCE` (G-6). 38 env vars with no single registry.
*Fix:* `settings.py` with typed accessors and one doc table generated from it.

**Q-5. Lint ceiling is low.** Only pyflakes; a survey with `B,UP,SIM,PERF,C4,PIE,RUF,PLW`
reports: `PLW1510` ×53 (`subprocess.run` without `check`), `B904` ×12 (`raise` without
`from` inside `except`), `SIM105` ×28, `PERF203` ×25 (try/except in loop), `PLW0603` ×17,
`RUF100` ×46 (stale `noqa`), plus 688 `UP006`/229 `UP045`/137 `UP037` that are
auto-fixable modernisations. `B023` hits in `panel_invoker` (`3925-3946`, `4537-4548`) are
false positives (`_capture_mutation` invokes the lambda synchronously) — add a comment or
bind explicitly. No `mypy`/`pyright` runs anywhere although `py.typed` is shipped.
*Fix:* enable `B`, `PLW1510`, `BLE001`, `RUF100` now (fix or `noqa` with reason); run
`ruff --fix` for `UP`; add `mypy --strict` on a growing allow-list starting with `models`,
`state`, `events`, `lease_store`, `dispatch_lock`.

**Q-6. Invalid escape sequences in non-raw docstrings.** `fab_delta.py:125` and `:657`
(``^\.(?:/.*)?$``) — `python -W error::DeprecationWarning -c "import phase_loop_runtime.fab_delta"`
raises `SyntaxError` today. Future CPython turns this into a hard error. Add `-W error` import smoke to CI.

**Q-7. Dead or test-only modules** (zero importers in `src/`): `roadmap_reseal.py`
(reached only via `importlib.import_module` in one test), `fleet_metrics_export.py`,
`declared_identity.py` (only test adapters), `fabpub_tdd_chronology.py` (CLI only),
`roadmap_representation_check.py` (1 test ref), `planner_validation.py` (1),
`reflection_sync.py` (1), `entry_doc_check.py` (1,279 lines, 12 refs — CI script). Decide
per module: wire, move to `scripts/`, or delete.

**Q-9. The two plugin seams have opposite failure semantics.** A broken
`phase_loop_runtime.profile_commands` plugin is logged and skipped (`cli.py:246-266`,
"must not break the CLI"); a broken `phase_loop_runtime.skill_sources` plugin raises
`SkillSourcePluginError` on every invocation (`skill_inventory.py:124-132`). Same
structure, same origin, opposite contracts — pick one and document it.

**Q-10. Flag oddities.** `--observe` (`cli.py:195,357`) is a documented no-op (only
`--no-observe` is read, `cli.py:1688`). `pipeline_adapter/flag.py:6-21` reads
`PHASE_LOOP_BRANCHGOV_ENABLE` with two deliberately opposite polarities
(`!= "false"` vs `== "true"`); intentional per its docstring, but exactly the kind of
thing a normalising refactor will "fix" — encode both semantics as named enum values.

**Q-8. `logging` vs `print`.** Three files use `logging`; the engine prints to stderr.
Operators cannot set a level, and the plugin loader's `_LOGGER.warning` only reaches the
console via Python's last-resort handler. Configure a package logger in `cli.main()`.

---

## 9. Test suite

**T-1. The suite has undocumented environment prerequisites (12 local failures: 11
environment, 1 product defect).**
- Full history: `test_validate_plan_doc_proofgate.py` (4), `test_goal_coverage.py` (1)
  read `plans/*.md` at pinned historical SHAs of *this* repo (`4e7dbf41…`, `0196f19c…`,
  `5328694a…`) — they fail on any shallow clone. This is the "pin your own history"
  pattern `AGENTS.md` warns plans against, applied to tests.
- Product defect, not a prerequisite: `test_verification_evidence.py::VerificationEvidenceHardening243Test`
  (4) fail whenever `sys.executable` is under `/home`. That is C-11 — the runtime
  discards the evidence field — so these four count as one product bug (fix per X-5),
  not as a developer setup requirement.
- Host state (post-dates this snapshot): tests that reach `default_fabpub_authority_root()`
  or the agy canary's `inventory_customizations()` read `~/.local/state/phase-loop/…`
  and `AGY_*`/`GEMINI_*`/`XDG_*` env from the developer's host; tracked as
  Consiliency/agent-harness#779.
- PATH: `test_fabpub_shared_epoch.py:2962-2963` requires `shutil.which("phase-loop")`.
- Tooling: `test_outside_agent_contract_drift.py` requires `build` + `setuptools`.
- `test_acceptance_falsifier_contract.py` mutation baselines (2 of 9) fail for the same
  reasons (`baseline_failed`, `verification_evidence.py:1290-1292`).
*Fix:* a `tests/README.md` + `conftest` that *skips with a reason* when a prerequisite is
absent (`pytest.skip("needs full history")`), and a `make test-prereqs` check.

**T-2. Scale and shape.** 183 K test lines for 128 K source lines; single files up to
354 KB (`test_outside_agent_conform_evidence.py`), 304 KB (`test_agy_canary_evidence.py`),
260 KB (`test_tdd_chronology.py`), 222 KB (`proofgate_bootstrap_verifier.py`). 603 tests
carry `dotfiles_integration` and are *always* deselected in this public repo — they are
dead weight here (move them to the private fleet repo, or gate on a fixture that exists).
`conftest.py` mutates `os.environ` at import (`PHASE_LOOP_PROFILE_PLUGINS`,
`PHASE_LOOP_SKILL_SOURCE_PLUGINS`) — order-sensitive global state.

**T-3. Environment coupling inside tests.** `sys.executable` used 259× in 51 files;
real-repo git commands (`rev-parse HEAD`, `git log`) 238× in 47 files; `time.sleep` 57×
in 15 files (`test_phase_loop_launcher.py` 9); plus the private-seam patching in Q-3.
The "TDD guard" / "conform canonical" machinery (`*_tdd_guard.py`, `proofgate_*`,
`_outside_agent_canonical.py`) tests the tests' own history — high ceremony for the
value; the 40-minute chronology node is the extreme case.

**T-4. Parallelism.** `pytest-xdist` is not used. Blockers: module-level env mutation in
`conftest.py`, tests that `chdir`/touch the real repo, global caches (A-6). Once those are
fenced (`monkeypatch.setenv`, `tmp_path` repos, `cache_clear` fixtures), `-n auto` should
cut the 14-minute local run to ~3-4 and the hosted lanes proportionally.

Additional xdist blocker: `verification_evidence.execute_proofgate_mutation_manifest`
(`1259-1266`) does `git worktree add`/`remove --force` against the shared `.git`, so
parallel proofgate tests would race on worktree metadata.

**T-6. Test infrastructure that tests itself.** `tests/conftest.py:146-163` installs a
`pytest_pyfunc_call` hook that, in "canonical mode", *discards the test body* for every
node in `CONFORM_MIGRATED_EXISTING_NODE_IDS` and dispatches to a table in
`tests/_outside_agent_canonical.py:3077` (3,161 lines) — reading a test no longer tells
you what runs. The 17 non-`test_*` helper modules total ~17,000 lines
(`proofgate_bootstrap_verifier.py` 4,660; `proofgate_tdd_guard.py` 2,291;
`harden_tdd_guard.py` 1,437). `guard_proofgate_nodeid`, `run_proofgate_contract` and
`emit_mutation_observable` are defined twice (`proofgate_tdd_guard.py`,
`proofgate_content_tdd_adapter.py`), and the pinned grandfather OIDs are duplicated
byte-for-byte at `proofgate_tdd_guard.py:240-241` / `proofgate_content_tdd_adapter.py:675-676`.
One live network call exists (`test_release_pin_autotrack.py:113`, skips offline — fine).
Untested shipped code: the four identical
`skills_bundle/*-execute-phase/scripts/audit_lane_file_touches.py` (788 lines, zero refs).
*Recommendation:* collapse the two proofgate adapters into one, replace the body-swap
hook with parametrised tests over the canonical table, and pin OIDs in one constant.

**T-5. Coverage is not measured.** No `coverage`/`pytest-cov` anywhere; with 55
functions over 150 lines it is not possible to know which branches of `run_loop` are
exercised. Add coverage reporting (no threshold at first) to make the split in A-1
measurable.

---

## 10. CI/CD, packaging, release

**P-1. Version is not single-sourced.** `phase-loop-runtime/pyproject.toml` (0.7.14),
`RELEASE_PIN` (v0.7.14), `CHANGELOG.md`, and `consiliency-harness/pyproject.toml`
(**0.6.1**, dep `phase-loop-runtime>=0.6.1`). README says "Pin a release with
`pip install consiliency-harness==X.Y.Z`", but the shim's version is not in lockstep
with the engine and its floor is `>=0.6.1`, so pinning the shim does **not** pin the
engine. Either bump the shim per release with `==` (release-consistency should check
it) or document that only `phase-loop-runtime==X.Y.Z` pins.

**P-2. Missing script referenced by packaging and tests.**
`pyproject.toml:124`, `tests/test_phase_loop_runtime_package_data.py:19,88` and
`tests/_contract_docs.py:7` cite `scripts/sync_runtime_package_data.py`, which does not
exist in this repo (it lived in the private fleet repo). The `_contract_docs/**` drift
guard (`test_bundle_is_byte_identical_to_canonical_sources_when_in_tree`) therefore
always skips here — 14 frozen contract docs (4 % of the wheel) have no reachable source
of truth. Either vendor the canonical docs into this repo and add the script, or declare
`_contract_docs` canonical here.

**P-3. Skills triple-copy is justified and guarded** (`skills-src/` → `phase-loop-skills/`
via `regenerate_skills_bundle.py` + `skills-parity.yml`; → `skills_bundle/` via
`sync_skills_bundle.py` + drift test; verified in sync today). Consider generating
`skills_bundle` at wheel-build time (a `setuptools` build hook) so only two copies are
committed.

**P-4. CI cost.** Fork path: 3 interpreter lanes × ≤100 min + clean room ≤100 min +
retention guard; eligible path: one 120-min offload. Two lanes (3.11, 3.12) run nearly
the same suite as 3.10 minus one node. With T-4 in place, run the full matrix only on
`main`/nightly and one lane on PRs.

**P-5. Wheel contents are reasonable** (2.17 MB). `_test_fixtures/**` (15 KB) and
`deploy/*.service` (1 KB) are harmless; `skills_bundle/**` (1.26 MB) is the price of the
no-dotfiles install. `uv.lock` is committed in `phase-loop-runtime/` — fine, but CI
installs with `pip`, so it is not what CI tests.

**P-6. `ruff.toml` at root explains it must not be `pyproject.toml` because several
modules key behaviour on a root `pyproject.toml`'s presence** (`verification_evidence.resolve_install_command`,
`doctor._contract_floor`, `docs_surfaces`, `fleet_map`, `repo_validation`). That is a
fragile signal — use an explicit marker (`[tool.phase-loop]` table or `.phase-loop/repo.toml`).

---

## 11. Docs and repository hygiene

**D-1. Repo weight that is not load-bearing.** `plans/` 2.9 MB (95 files; one 627 KB
file; `plans/manifest.json` 308 KB and the most-churned file in the repo), `specs/`
532 KB, `CHANGELOG.md` 337 KB with a 373-line `[Unreleased]` section since 0.7.14,
`spikes/` 76 KB, `reflections/`, `.consiliency/`, `.phase-loop/`. `plans/` and `specs/`
are referenced by 19 runtime modules (mostly as this repo's own roadmap — A-2) and by the
history-pinned tests (T-1). Once A-2 and T-1 land, archive completed plans under
`plans/archive/` (or a separate branch) and split `CHANGELOG.md` by minor version.

**D-2. README claims to verify.** "Pin a release with `pip install consiliency-harness==X.Y.Z`"
(P-1). `phase-loop run` "needs a roadmap … exits with `no specs/phase-plans-v*.md roadmap
found`" — true, but the runtime also silently *pins* `specs/phase-plans-v10.md` in three
modules (A-2), which the README does not say. The env-var surface (38 vars) is documented
piecemeal across `docs/`; generate one table from `settings.py` (Q-4).

**D-3. `AGENTS.md` is good** and short; keep it that way. Consider adding the developer
prerequisites from T-1 and the exception/timeout policy from C-1/C-2 as one-liners.

---

## 12. Prioritised plan

Ownership caveat: `runner.py`, `panel_invoker.py`, `legible_evidence.py` and the other
engine files named below are roadmap-owned by in-flight v10 phases — check
`specs/phase-plans-v10.md` `## Phases` → `Key files` (LEGIBLE, SCHED, HARDEN, RUNTIME,
GOVLEAN, among others) before opening a PR against them; A-1/A-2/Q-3 in particular wait for those
phases to close.

**Now (days; no behaviour change or strictly safer):**
G-1, G-2, G-6, C-3 (fix + re-enable `F841`), C-1 for network calls only, X-2 body cap,
Q-6 escapes, T-1 skip-with-reason, P-1 shim pin, Q-5 enable `B`/`PLW1510`/`RUF100`.

**Next (weeks; mechanical refactors under the existing suite):**
E-1 topology cache, S-3 single ledger parse, S-1/S-2 locking helper, C-4 CLI error
policy, A-2 legible extraction, A-3 canary extraction, Q-3 seams for `panel_invoker`
(then Q-2 vendor strategy), T-4 xdist readiness, T-5 coverage.

**Later (a quarter; architectural):**
A-1 split `run_loop` behind `RunContext`, A-4/C-6 shared git-history + roadmap parser,
Q-4 `settings.py`, A-5 import-linter, mypy allow-list growth, G-4 decision on FAB,
G-5 roadmap-declared visual phases, D-1 archive plans/specs, P-3 build-time bundle.

Guardrails to keep the gains: a ruff `banned-api` for raw `subprocess.run(["git"…])`,
import-linter contracts, `-W error` import smoke, a registered-validators assertion,
coverage trend, and a function-length ratchet (fail CI if any function grows past its
current size in the split modules).

---

## Appendix A — local test run

`PYTHONPATH=src:tests pytest -m "not dotfiles_integration" --deselect <chronology node>
--ignore tests/test_legible_roadmap_contract.py --ignore tests/test_legible_evidence.py`
on Python 3.11.15, shallow clone, venv under `/home`:

`12 failed, 4729 passed, 114 skipped, 603 deselected, 31 warnings in 865.75s`

| Failure | Cause class |
|---------|-------------|
| `test_validate_plan_doc_proofgate.py` ×4, `test_goal_coverage.py` ×1 | pinned historical SHAs; shallow clone |
| `test_verification_evidence.py::VerificationEvidenceHardening243Test` ×4 | product defect C-11: `sys.executable` under `/home` → whole-field `suite_command` redaction |
| `test_fabpub_shared_epoch.py::…legacy_writer_quiescence…` | `phase-loop` not on PATH |
| `test_outside_agent_contract_drift.py::…sdist_and_wheel…` | `build`/`setuptools` absent |
| `test_acceptance_falsifier_contract.py::…command_coverage` | 2 mutation baselines `baseline_failed` (same env causes) |

Slowest: 166 s, 37 s, 19 s, 15 s, 13 s (all subprocess/git-heavy).

## Appendix B — modules with zero `src/` importers

`advisor_board` (pkg root), `cli`, `declared_identity`, `doc_delta_validator`,
`docs_audit`, `docs_surfaces`, `doctor`, `dotfiles_profile_plugin`, `entry_doc_check`,
`fabpub_capability`, `fabpub_tdd_chronology`, `fabreadmit_capability`,
`fleet_metrics_export`, `gate_posture`, `pipeline_adapter`, `plan_pin_lint`,
`planner_validation`, `proof_stages`, `reflection_sync`, `repo_validation`,
`roadmap_ownership`, `roadmap_representation_check`, `roadmap_reseal`, `route_policy`,
`skill_sources_plugin`, `tdd_receipts`, `train_runner`, `verification_evidence_validator`,
`visual_avatar_evidence_validator`, `visual_evidence_validator`. (Several are legitimate
entry points or validators registered by side effect; the rest are Q-7 candidates.)

## Appendix C — environment variables read by the runtime (38)

`AGENT_HARNESS_HOME`, `DOCS_AUDIT_PUSH_BEFORE`, `DOTFILES_MACHINE_ID`, `GITHUB_BASE_REF`,
`GITHUB_HEAD_REF`, `GITHUB_REF`, `HOME`, `OUTSIDE_AGENT_SPEC_ROOT`,
`PHASE_LOOP_ACCEPTANCE_ENFORCE`, `PHASE_LOOP_ALLOW_HELD_DISPATCH`,
`PHASE_LOOP_ALLOW_LANE_IR_OVERRIDE`, `PHASE_LOOP_ALLOW_STALE_ROADMAP_PLAN`,
`PHASE_LOOP_BASE_REF`, `PHASE_LOOP_BRANCHGOV_ENABLE`, `PHASE_LOOP_CALLER_RUN_ID`,
`PHASE_LOOP_CONCURRENT_REAL_EXEC`, `PHASE_LOOP_DISCOVERY_ALLOW_COMPLETED`,
`PHASE_LOOP_DISPATCH_LOCK`, `PHASE_LOOP_HARNESS`, `PHASE_LOOP_MANIFEST_DISABLED`,
`PHASE_LOOP_PARALLEL_DISPATCH`, `PHASE_LOOP_PIPELINE_MODE`, `PHASE_LOOP_PR_BASE_REF`,
`PHASE_LOOP_PR_HEAD_REF`, `PHASE_LOOP_PR_URL`, `PHASE_LOOP_PROFILE_PLUGINS`,
`PHASE_LOOP_RECONCILE_GIT_REALITY`, `PHASE_LOOP_RUNNER_REPO_ROOT`,
`PHASE_LOOP_SKILL_BUNDLE`, `PHASE_LOOP_SKILL_SOURCE_PLUGINS`, `PHASE_LOOP_SOURCE_BUNDLE`,
`PHASE_LOOP_TARGET_PUSH_REF`, `PHASE_LOOP_TRUST_EXECUTOR_EVIDENCE`,
`PHASE_LOOP_VERIFY_ENFORCE` (two defaults — G-6), `PHASE_LOOP_VERIFY_REDACT_DIAGNOSTICS`,
`PHASE_LOOP_VERIFY_TIMEOUT_SECONDS` (three readers), `SSH_AUTH_SOCK`, `XDG_CONFIG_HOME`.
(`PHASE_LOOP_REVIEW` and `PHASE_LOOP_CONSILIENCY_GATES` are read via helpers and not
counted above.)
