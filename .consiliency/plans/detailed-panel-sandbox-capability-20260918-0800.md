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

Placement model: **the panelist runs wherever its sandbox is.** The sandbox root is a
LOCATION, not just a path, and the seat executes there. This removes the remote-filesystem
problem entirely -- no NFS, no small-file I/O over the network, no venv-over-NFS fragility,
and nothing for Windows or macOS to support beyond the local default. It also makes
archival cheap: if sandboxes live on `ai`, archiving to `ai:/storage` is a local move.

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

### Sandbox layout and provenance

A sandbox is two directories with different lifetimes:

- `reviewed-tree/` — RECONSTRUCTIBLE. An **independent shallow git clone** at the pinned
  commit, never `--shared` and never a linked worktree, so it carries its own object store
  and no pointer into the live gitdir. Re-stageable at will.
- `work/` — IRREPRODUCIBLE. The panelist's own scratch: notes, probe scripts, partial
  findings. Never reaped while the sandbox lives; always archived.

That split is the same principle the retention policy uses, and it is what makes a stale
resume recoverable rather than destructive.

**Clone depth: 50**, measured on this repo rather than guessed:

| form | total | `.git` | commits reachable |
|---|---|---|---|
| full history | — | 111 MB | all |
| depth 50 | 34 MB | 14 MB | 634, back to 2026-05-21 |
| depth 20 | 34 MB | 14 MB | — |
| depth 1 | 29 MB | 8.3 MB | 1 |

Depth 50 costs the same as depth 20 and is **8x smaller than full history**, while giving a
panelist ~4 months of `git log`/`blame`/`diff`. Git is a small fraction of a used sandbox
(~34 MB against ~150-250 MB once a venv exists), so the tooling is close to free.

This reverses the earlier decision to exclude `.git`. That was right about not linking to the
LIVE gitdir and wrong about git generally: an independent clone gives the panelist history to
reason with, and makes a stale resume a `fetch` instead of a re-copy.

### Resuming an idle sandbox

On resume, compare the recorded source commit against the branch's current head:

- unchanged → resume as-is;
- moved → **re-stage `reviewed-tree/` at the new head, preserve `work/`, and hand the panelist
  the diff** between what it last saw and now.

A stale resume is not a cosmetic problem: a panelist reviewing vanished code produces confident,
well-cited, wrong findings — the exact cost this work exists to remove. `staged_tree_sha256` was
built as a tamper check and doubles as the staleness detector for free.

If the panelist edited `reviewed-tree/` itself (it is writable), those edits are experiments,
not deliverables: capture them as a patch into `work/` before re-staging and tell the panelist
where it went. Never silently discard, never attempt a merge.

### Platform support

Review isolation is **Linux-only today and already fails closed**: `backing.py:746` raises
"HARDEN review composition requires Linux", and `:512` refuses without an executable
`/usr/bin/bwrap`. Copying a tree and running a process in it is portable; filesystem
confinement and network egress control are not (`bwrap` vs deprecated `sandbox-exec` vs WFP --
three unrelated implementations).

Co-location resolves this without per-OS sandboxes: the coordinator's OS no longer determines
the sandbox's OS, so a macOS or Windows user points the root at a Linux host and gets full
isolation. The fleet has four Linux hosts.

Each sandbox therefore **declares what it actually enforced** into the review evidence — tree
isolated, network filtered, credentials scrubbed, filesystem confined. Policy default is to
REFUSE when a required property cannot be enforced, never to degrade silently. A sandbox that
claims network denial it cannot deliver is a fail-open in the evidence record.

### `phase-loop-runtime/src/phase_loop_runtime/review_stage.py` (modify)

- `stage_review_tree` — remove the read-only hardening; a sandbox must be writable. Stage via
  an independent `git clone --depth 50`, not a file copy.
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

- `PHASE_LOOP_SANDBOX_ROOT` — a LOCATION: bare path = local, `<host>:<path>` = that host.
  Default: system temp dir (**local**; no remote by default). The seat executes wherever
  this resolves to.
- `PHASE_LOOP_SANDBOX_FALLBACK_ROOT` — default: system temp dir (always local)
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

### Remote execution (when the root resolves to another host)

The seat's CLI is launched **on that host, in that directory**, over SSH — the transport the
fleet already uses everywhere else. The staged copy is made there; nothing is mounted back.

Deliberately NOT Dagger, despite it being this repo's CI offload mechanism
(`ci/offload-gate.sh`, `AGENT_REMOTE_HOST`): Dagger containers are ephemeral one-shot
environments, which is right for a CI suite and wrong here — a sandbox has to survive an idle
overnight so a panelist can be resumed against it with its context intact. That requirement is
what selects a persistent directory over a container.

Reaping and archiving run **on the host that owns the sandbox**, not from the coordinator.

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
- [ ] With a remote root configured, the seat's process runs ON that host, in that sandbox,
      and nothing is mounted back to the coordinator.
- [ ] A sandbox on a remote root is reaped and archived BY that host.
- [ ] An unreachable remote host costs one warning and a local run, within the probe timeout.

## Deferred, with reasons recorded

- **Docker Desktop containers as a portable sandbox.** Works on Linux, macOS and Windows, and
  a NAMED container persists across an idle overnight, so it avoids the ephemerality that ruled
  out Dagger. Deferred because co-location already gives cross-platform users full isolation via
  a remote Linux root, and a container runtime is a heavy new dependency. This is the fallback
  if remote-Linux roots prove awkward in practice. Tracked separately so the reasoning survives.

## Open question for the board

Whether the independent clone should be shallow (depth 50, as planned) or full history. The
measurements above argue for shallow; a seat that wants deep `blame` on old code may disagree.
Put this to the panelists explicitly in the round brief.

## Non-goals

- The `#848` layer store and dependency-acquisition pipeline (Phases 14-15). Internet access
  in the sandbox removes the immediate need.
- The v10 roadmap amendment — currently forbidden by the proposal's own fallback rule while a
  plan is `executing` (`agent-harness#889`).
- Triage of the 1,406 existing worktrees. Separate and more urgent for disk, unrelated to this.

## Execution Policy

- execute: effort=high, reason=security-boundary change on an attested launch surface
