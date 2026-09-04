# phase-loop-runtime

The harness-neutral **phase-loop** orchestration runtime and CLI. It drives the
roadmap → plan → execute workflow by dispatching each phase to whatever harness you
choose (Claude / Codex / Gemini / OpenCode); the runtime itself makes no model calls.
Part of the public [`agent-harness`](https://github.com/Consiliency/agent-harness)
monorepo (Apache-2.0).

## Install

Most users should use the repo's installer (it also installs the workflow skills):

```sh
git clone https://github.com/Consiliency/agent-harness
agent-harness/install-agent-harness.sh --harness claude
```

To install just this runtime package directly:

```sh
pip install phase-loop-runtime              # latest compatible release
pip install phase-loop-runtime==0.7.14      # …or pin an exact version
```

To pin a specific tag from source instead, substitute a tag from
[Releases](https://github.com/Consiliency/agent-harness/releases):

```sh
uv tool install "git+https://github.com/Consiliency/agent-harness@<TAG>#subdirectory=phase-loop-runtime"
```

This exposes two console scripts — `phase-loop` and `codex-phase-loop` — both calling
`phase_loop_runtime.cli:main`. The canonical protocol document ships in the wheel as
package data and is also installed to `share/phase-loop-runtime/protocol/protocol.md`.

## Roadmap validation

Lint a phase-plan roadmap spec (required headings, unique aliases, acyclic dependency
DAG, IF-gate reconciliation, lane-count hints) via the always-installed runtime:

```sh
phase-loop validate-roadmap specs/phase-plans-v1.md
# module form — only when phase_loop_runtime is on the ACTIVE python's path (a pip
# install into your env); under `uv tool install` isolation use the console command:
python3 -m phase_loop_runtime.roadmap_lint specs/phase-plans-v1.md
```

Both wrap `phase_loop_runtime.roadmap_lint` (the single source of truth). Exit 0 =
clean; non-zero prints each issue on stderr.

## Attended agy canary evidence

The six `phase-loop agy-canary-*` commands are an opt-in, attended evidence
pipeline for the Gemini/`agy` review seat. They never add an Antigravity allow
rule or use a permission-bypass flag. `agy-canary-clean-settings` is the sole
writer for removing the historical `command(pwd)` rule; it requires a direct,
mode-0700 child of `/tmp`, a quiescent settings tree, and an exclusive maintenance
lock. The later probe, prepare, verify, and finalize steps fail closed until an
attended agy 1.1.13 `stream-json` schema probe has selected a complete authority.
That probe and every capture-enabled Gemini launch use `/usr/bin/bwrap`, a fresh
`/tmp`, `/run`, and `/proc`, the fixed `/run/phase-loop-review` stage mapping,
and a reducer-generated minimal HOME. A missing effective namespace, active
customization source, unsupported stream schema, or absent direct bootstrap
attestation blocks the canary rather than falling back to the operator HOME.

When `PHASE_LOOP_AGY_CANARY_EVIDENCE_DIR` is set, `advisor-board --json` consumes
that variable before spawning any seat. The complete board JSON must be written
through `--agy-canary-private-board-name <basename>` into that private directory;
stdout contains only the redacted ledger binding. Capture requires exactly one
resolved Gemini seat and retains the two staged review inputs using descriptor
relative, no-follow writes. A normal board has no new output field or capture work.

## Workflow skills bundle

The runtime also installs the harness-neutral workflow-skills bundle. The skill
sources live in the [`phase-loop-skills/`](https://github.com/Consiliency/agent-harness/tree/main/phase-loop-skills)
directory of the monorepo,
with unprefixed base directories and optional `_overrides/<harness>/` overlays.

```sh
phase-loop install --harness codex --source <path-to>/phase-loop-skills --symlink --dry-run
phase-loop install --harness codex --source <path-to>/phase-loop-skills --symlink --apply
```

Path resolution is provided by `phase_loop_runtime.skill_paths`, which keeps handoffs
repo-local, preserves harness-specific reflection roots, and documents the default
install roots for Claude, Codex, Gemini, and OpenCode.

## Zero-history FABPUB bootstrap

When FABPUB is active on a host that has no compatible legacy run-train broker
ledger, create its persistent authority with a read-only probe followed by an
explicit apply:

```sh
phase-loop fabpub-bootstrap --probe \
  --inventory /secure/operator/fabpub-probe.json \
  --worktree /path/to/repo \
  --legacy-root /path/to/declared/ledger/broker \
  --search-root /path/to/workspaces \
  --historical-evidence-root /path/to/standalone/receipt

phase-loop fabpub-bootstrap --apply \
  --inventory /secure/operator/fabpub-probe.json \
  --confirm-zero-history
```

The default authority is
`$XDG_STATE_HOME/phase-loop/fabpub/authority-v1`, falling back to
`~/.local/state/phase-loop/fabpub/authority-v1`. Override it with
`PHASE_LOOP_FABPUB_AUTHORITY_ROOT` or `--authority-root` during the probe.
Receipts created by apply retain that custom authority location for later
fresh-process validation; keep the environment override configured when
onboarding repositories that were not named by the original probe.
Apply is irreversible and refuses changed bytes, symlinks, live allocator
state, held generation leases, or an authority owned by another bootstrap.

Inventory completeness is bounded to the named worktrees, explicit and
environment-declared legacy roots, historical-evidence roots, and hashed broker
directories directly beneath `.train-ledger` directories under each
`--search-root`. The confirmation attests that no compatible allocator exists
outside that inspected universe.
Standalone historical receipts are hashed and left in place; they are not
silently adopted as current allocator authority.

## Closeout ownership gate & operator break-glass

When a phase verifies green but the executor touched files outside the plan's declared
owned-files globs, the **graduated closeout gate** classifies the beyond-ownership
remainder (`closeout_classifier.classify_unowned_path`):

- SAFE classes (`docs`, `plans`, `handoffs`, `config_nonsource`) auto-commit as a
  recorded `soft` exception.
- UNSAFE classes (`source`, `ci`, `secrets`, `lockfile`) block with
  `closeout_scope_violation`.

The operator escape is `phase-loop run --phase <P> --closeout-allow-unowned "<reason>"`
(also valid on `resume`/`dry-run`; reason required and non-empty; `--phase` required,
bounding the override to a single phase). It folds the `source`/`ci`/`lockfile`
remainder into the closeout commit as a recorded `break_glass` exception carrying the
reason. **`secrets` are never break-glassable** — a `.env*`/`*.pem`/`secrets/**` path
blocks regardless of the reason. See `protocol.md` → "Closeout Exceptions".

The closeout verdict is runner-authoritative: when the runner rejects a child's
closeout, the persisted `terminal-summary.json` reflects the runner's blocking verdict
(the child's self-reported `complete`/`passed` is not overlaid back), preventing a
stale "complete" summary from reconcile-skipping the work on the next run.

## Conformance library (one library, two roles)

`phase_loop_runtime.conformance` is the named, stable, importable surface for the
deterministic `.consiliency/` conformance evaluator. It is a re-export (not a
re-implementation) of the same function the actor already runs, so an **external
CR-fence** — in gp CI, a git-host pre-merge check, anywhere — can import and run
the identical check:

```python
from phase_loop_runtime.conformance import scan_consiliency_gates

verdict = scan_consiliency_gates("/path/to/repo")   # {"status": "passed" | "warn" | "blocked" | "skipped", "gates": {...}, ...}
```

The surface also exposes the pure cores (`evaluate_git_discipline`,
`self_heal_partition`, `evaluate_governance_scope`) for consumers that already
hold the injected facts.

**Two roles, one library.** This is meant to be mounted BOTH as the actor-side
self-check (a pre-PR sanity pass the author runs locally) AND as the
authoritative CR-fence (the real validator). The actor-side result is **never
authoritative** — the fence always re-runs the check itself. Because it is the
same function versioned with the same `consiliency_contract` dependency, the honest
actor sees exactly the verdict the fence will; a stale or dishonest actor result
simply does not matter.

**Scope.** The surface spans the shape + governance tier and the certificate /
projection / outside-agent tiers it re-exports (see the module docstring for the
authoritative tier list). Authority and provenance *verification* remain out of
scope, delegated downstream.

### `consiliency-ingest --check-only`

`--check-only` decouples "run the check" from "is this repo adopted". It is
strictly read-only (never shapes; ignores `--adopt`). It makes the exit code
verdict-significant so a pre-PR actor is never misled into reading a no-op — or a
failing verify — as a pass:

| Repo state | mode | exit |
|---|---|---|
| adopted, verify clean (or `warn`) | `verify` | `0` |
| adopted, gate scan `blocked` | `verify` | `1` |
| un-adopted (no `.consiliency/manifest`) | `not-adopted` | `3` |
| usage error | — | `2` |

The plain (non-`--check-only`) path is unchanged — it keeps the silent green
`skipped` no-op on an un-adopted repo and its existing exit `0`.
