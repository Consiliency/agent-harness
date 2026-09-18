# Detailed plan: executable review sandboxes for cross-vendor board seats

## Task

Give cross-vendor review seats a disposable sandbox they can actually work in: a writable
copy of the code under review, with shell and test execution, open internet, and a narrow
allowlist into the local inference stack — so a panelist can form a hypothesis, run it, and
report what it observed rather than what it guessed.

Then make sure those sandboxes are selected, sized, reaped and archived so they cannot fill
the disk.

Trust model, which drives every decision below: **the sandbox protects the reviewed tree,
not against the reviewer.** Panelists are trusted like the agent that writes the code. The
boundary exists so a reviewer can act freely without touching live state.

## Research summary

Established across board round 1 on `agent-harness#890` and the follow-up investigation:

- **The isolation for review legs is not where the bundle claimed.** `advisor_board/backing.py:551`
  runs `bwrap --unshare-all --clearenv` around a **fixed parent-generated posture probe**, not
  around a seat. Seats run in the parent via `_parent_infer` → `_exec_leg`.
- **Seats today can reach nothing.** Brokered codex launches with `--cd <out_dir>`,
  `--sandbox read-only`, and `shell_tool` in `_BROKER_CODEX_DISABLED_FEATURES`. Brokered
  gemini drops `--add-dir` entirely. `_render_broker_inline_prompt` documents that the
  provider gets "no path it can select, inspect, or mutate".
- **The one leg that can read `review_dir` never needed it.** `_claude_tui_command:2481`
  already appends `repo_dir` as an add-dir.
- **A read-only stage defeats the purpose.** `pytest` writes `__pycache__` and `.pytest_cache`
  before doing anything, so a `0o500` tree cannot host a test run.
- **Offline test runs work** given deps on disk (measured: suite passes with the network
  blackholed), but internet access removes the need for a prebuilt dependency layer.
- **Disk is the binding constraint.** claw is at 97% on both disks (7.2 GB free on `/`,
  15 GB on the workspace volume) with 1,406 worktrees. A used sandbox is ~150-250 MB
  (28 MB tree + ~94 MB venv + caches); four seats × 15 rounds ≈ 10-15 GB for one PR.
- **`ai` exposes more than inference.** `services.json` lists `qdrant` (~69 GB of user data)
  and `file_browser` alongside the models, unauthenticated on the tailnet. `ai_router:8020`
  fronts the models and answers `/v1/models`; `:3131` is discovery.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/review_stage.py` (modify)

- `stage_review_tree` — remove the read-only hardening; a sandbox must be writable.
- `_harden_modes` — delete. Its only purpose was the read-only posture, and it is the sole
  reason cleanup needed mode restoration.
- `remove_review_stage` — keep (still used for reaping), simplify now that modes are normal;
  retain the symlinked-root refusal.
- `review_tree_manifest_sha256` — keep. Its meaning is now explicitly "what the seat was
  handed", recorded before launch; it is not expected to match afterwards.
- `select_sandbox_root(configured, fallback, floor_bytes, probe_timeout_s)` — **add**.
  Bounded write-probe of `configured`; on hang/failure warn and use `fallback`; refuse
  (raise) if the chosen root is below `floor_bytes`. Returns the root and the reason, for
  evidence.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (create)

Single source for the knobs, all env-overridable, all defaulting to a working local setup:

- `PHASE_LOOP_SANDBOX_ROOT` — default: system temp dir (**local**; no remote by default)
- `PHASE_LOOP_SANDBOX_FALLBACK_ROOT` — default: system temp dir
- `PHASE_LOOP_SANDBOX_FLOOR_BYTES` — dev default **2 GiB**; production raised by config
- `PHASE_LOOP_SANDBOX_TTL_S` — default 24 h (matches the existing GC default)
- `PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES` — footprint ceiling, reaped oldest-first
- `PHASE_LOOP_SANDBOX_PROBE_TIMEOUT_S` — default 5 s
- `PHASE_LOOP_SANDBOX_ARCHIVE_DEST` — default unset (archiving off)
- `egress_allowlist()` — deny private space, allow public internet, allow `ai:8020` + `ai:3131`

When no remote root is configured there is **no probe and no fallback decision** — only the
floor check. Zero-config works on a laptop.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- `_default_spawn` — select the root via `select_sandbox_root`; stage writable; record the
  chosen root and the fallback reason in the leg evidence. Root choice is **sticky per round**,
  not per seat.
- `_brokered_codex_command` — **extract** from the inline `cmd` list. `--cd <staged_tree>`,
  drop `shell_tool` from the disabled set, sandbox scoped writable to the stage. Refuse a
  non-staged path.
- `_brokered_gemini_command` — **extract**. Add `--add-dir <staged_tree>`; allow execution.
  Refuse a non-staged path.
- `_render_broker_inline_prompt` — optional `staged_tree`; when present, name the path and
  state that it is a writable disposable copy, not the live checkout. Byte-identical output
  when absent.
- `_review_bytes` — already excludes the staged tree (keep; it is what preserves the timeout
  keystone).
- `_gc_stale_panel_scratch` — extend to the configured root(s); add the size ceiling; archive
  before reaping.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` (modify)

- `ReviewIsolationAuthorization` — no new fields. `staged_tree_sha256` already carries the
  binding; its docstring is amended to say the tree is writable and the digest records the
  handed-over state.
- Egress policy applied at leg launch, from `sandbox_policy.egress_allowlist()`.

### `phase-loop-runtime/tests/test_broker_staged_tree_delivery.py` (rewrite)

The seven tests currently pin the read-only, no-execution design and are wrong. Replace with
the assertion that matters: **a seat runs a test inside the copy, gets a real result, and the
live tree is byte-identical afterwards**; plus negatives — no credentials visible, private
space unreachable, allowlisted endpoints reachable.

### New test files

- `test_sandbox_root_selection.py` — probe timeout does not hang; fallback warns; below-floor
  refuses rather than proceeding; sticky per round; no probe when unconfigured.
- `test_sandbox_retention.py` — TTL reaping; size-ceiling reaping oldest-first; archive runs
  **before** reap; reconstructible bulk never archived; session record never reaped.

## Documentation impact

- `docs/phase-loop/convergence-runtime.md` — document the sandbox posture and the knobs.
- `CHANGELOG.md` — the delivery change and the egress policy.

## Dependencies & order

1. `sandbox_policy.py` + `select_sandbox_root` (nothing depends on the old read-only posture).
2. Drop read-only hardening; fix the tests that assumed it.
3. Extract the two command builders (pure refactor, byte-identical output) — **land separately
   so the behavioural diff is reviewable on its own**.
4. Delivery: argv + prompt, behind the authorization.
5. Egress policy.
6. Retention + archive.

Steps 3 and 4 touch `panel_invoker.py`, which is `Key files` for HARDEN, REVIEWTRUTH, LEGLIFE
and GOVLEAN — all `committed`, none `executing`. That window is why this is landable now.

## Verification

```sh
PYTHONPATH=src:tests python -m pytest -m "not dotfiles_integration" \
  tests/test_broker_staged_tree_delivery.py tests/test_sandbox_root_selection.py \
  tests/test_sandbox_retention.py tests/test_review_stage_binding.py \
  tests/test_review_stage_board_findings.py -q

# the assertion that the old suite faked: a real run inside the sandbox
#   - stage a repo, run `pytest` in the copy, assert a real pass/fail came back
#   - assert the source tree's manifest digest is unchanged afterwards
#   - assert a connect to a private address fails and a connect to ai:8020 succeeds
```

Run the sweep on a tree **left untouched** for its duration — editing during a run breaks
`inspect.getsource` assertions and produces phantom regressions.

## Acceptance criteria

- [ ] A brokered codex seat and a brokered gemini seat each run a command inside the staged
      copy and return its real output.
- [ ] After a review round, the reviewed working tree's manifest digest is unchanged.
- [ ] From inside the sandbox: a private-space connect fails, `ai:8020` succeeds, a public
      internet host succeeds, and no provider API key is present in the environment.
- [ ] With no remote root configured, no probe is attempted and the sandbox is created locally.
- [ ] With a configured root that hangs, the round proceeds on the fallback within the probe
      timeout and records the reason.
- [ ] With both roots below the floor, the round refuses rather than filling the disk.
- [ ] A sandbox older than the TTL is reaped; its session record is archived first and survives.
- [ ] With no tree authorized, the brokered argv and prompt are byte-identical to today.

## Non-goals

- The `#848` layer store and dependency-acquisition pipeline (Phases 14-15). Internet access
  in the sandbox removes the immediate need.
- The v10 roadmap amendment — currently forbidden by the proposal's own fallback rule while a
  plan is `executing` (`agent-harness#889`).
- Running the whole panelist on `ai`. That is the right answer for a disk-constrained host and
  should reuse the existing CI offload, but it is a follow-on, not a path parameter.
- Triage of the 1,406 existing worktrees. Separate and more urgent for disk, unrelated to this.

## Execution Policy

- execute: effort=high, reason=security-boundary change on an attested launch surface
