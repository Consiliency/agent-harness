# phase-loop-runtime

The harness-neutral **phase-loop** orchestration runtime and CLI. It drives the
roadmap → plan → execute workflow by dispatching each phase to whatever harness you
choose (Claude / Codex / Gemini / Grok / OpenCode / Pi); the runtime itself makes no model calls.
Part of the public [`agent-harness`](https://github.com/Consiliency/agent-harness)
monorepo (Apache-2.0).

## Install

Version 0.7.27 requires Python 3.12+ (agent-harness#1549). The host-side jail helpers
remain 3.10-compatible, but a governed-review falsifier node importing the runtime
under an older host interpreter ends in `error` and remains a blocking receipt.
All twelve shipped agy members have renewed live qualification on the revised
source. Exact-candidate package and compatibility checks remain release-cut gates;
qualification evidence and historical runtime smoke limitations are recorded in the
[release handoff](https://github.com/Consiliency/agent-harness/blob/main/docs/releases/outside-agent-release-handoff.md).

Most users should use the repo's installer (it also installs the workflow skills):

```sh
git clone https://github.com/Consiliency/agent-harness
agent-harness/install-agent-harness.sh --harness claude
```

To install just this runtime package directly:

```sh
pip install phase-loop-runtime              # latest compatible release
pip install phase-loop-runtime==0.7.27      # …or pin an exact version
```

To pin a specific tag from source instead, substitute a tag from
[Releases](https://github.com/Consiliency/agent-harness/releases):

```sh
uv tool install "git+https://github.com/Consiliency/agent-harness@<TAG>#subdirectory=phase-loop-runtime"
```

This exposes four console scripts: `phase-loop` and `codex-phase-loop` (both calling
`phase_loop_runtime.cli:main`), `phase-loop-closeout-audit` (the closeout
ignored-output audit) and `roadmap-ownership` (the roadmap-ownership preflight). The
canonical protocol document ships in the wheel as package data
(from `src/phase_loop_runtime/_contract_docs/phase-loop/protocol.md`); an older copy is also
installed to `share/phase-loop-runtime/protocol/protocol.md`.

## Optional Claude SDK runner

Install `phase-loop-runtime[claude-sdk]` and explicitly select
`PHASE_LOOP_CLAUDE_ROUTE=sdk` to use the official Python SDK with your installed
Claude Code CLI. Current defaults and the Channel, Agent View, print and panel TUI
routes remain available. Select one of those existing routes to roll back.

The initial SDK route supports Linux with working unprivileged Bubblewrap
namespaces and a locally stored personal Pro/Max Claude Code login. Review actions,
team execution, Team/Enterprise, profiles, cached remote policy and unknown login
contexts are refused before authentication. SDK panel selection remains refused.
Missing CLI capability, dependency or provenance produces a refusal with no
automatic fallback. The helper preserves CLI loading of the selected login.

Configuration is inspected before connecting and frozen in private read-only
mounts shared by the auth probe and inference. Project settings currently support
permission rules and hooks; project allow rules and hooks require stored project
trust. Other project keys require a different route. User
settings and inspectable host-managed policy are preserved. Initial instruction
snapshots support plain instruction files and flat, unconditional rules. The selected
user `CLAUDE.md` may be linked and may explicitly import user files, including a
linked `AGENTS.md`, to four import edges. Capture is limited to 32 MiB of total
reads and 256 visits, including repeats, on known local filesystems. These files
are included once as private,
immutable UTF-8 instructions. Relative imports through links require the logical
and resolved parent paths to identify the same file. Simple unquoted paths are
supported, with `~/` bound to the selected HOME. Quote-wrapped paths stay literal;
escaped spaces and ambiguous import or cross-block code-span syntax refuse the route.
Canonical inline `@path` examples remain literal. Fenced or indented code containing
import candidates, and inline spans containing whitespace before `@`, refuse.
Backtick blocks
containing an import candidate combined with escaped backticks, HTML, brackets,
indentation, pipes or possible URLs refuse before probes. Underscore-adjacent and
escaped `@` candidates also refuse before dependency reads.
The optional extra pins `markdown-it-py==4.2.0` for CommonMark block source maps,
including container fences and HTML boundaries. Scanning uses original source
ranges with CR/LF line normalization, retaining reference definitions and entity
spellings. It never discovers imports from rendered text. In candidate-bearing
files, raw fence syntax mixed with HTML blocks, line-start HTML-like syntax or
reference markers refuses. Fences require both a parser-proven explicit closing
line and a compatible raw closer with trailing spaces only; native-like interior
closers refuse. Candidate-bearing inline blocks with backticks inside a code span
or any multiline span also refuse, even when the candidate is outside that span.
Candidate-free multiline examples remain supported; separate paragraphs may import
files normally. For inline ambiguity checks, a candidate anywhere in the enclosing
run of non-blank lines applies to every parsed block in that run. Only lines made
of spaces and tabs separate runs; raw list and quote prefixes remain non-blank.
A run containing a candidate and any backtick refuses if it also contains `<`,
`[` or `]`, including in an initial HTML block or a different parsed block.
This conservative boundary avoids native link/title carriers across block joins.
Separate unrelated link/HTML examples from imports with a real blank line.
Fenced code and supported
inline spans are masked with spaces, preserving separators; ordinary inline
matching stays within one parsed block. Unmatched backticks and ambiguous inline
contexts refuse. This remains a bounded subset; CommonMark parsing alone does not
establish equivalence with native Claude.
Native CLI inspection shows dialect differences and tight-list import behavior
that conflict with some documented code exclusions. The guards define a bounded
supported subset, rather than complete native Markdown compatibility.
The existing raw HTML/reference handling and complete-byte snapshots do not emulate
native comment or frontmatter stripping.
The complete snapshot, including project files and rules, must fit 64 KiB of UTF-8
without embedded NUL characters for the SDK's command-line argument. Changed files
or aliases during capture refuse rather than mixing versions. Project imports,
path-scoped rules, descendant instructions, project or ancestor AGENTS.md contexts,
and linked project instruction trees require an existing route. The explicit user
`config/AGENTS.md` dependency remains user context when HOME is a project ancestor;
unreferenced config files gain no exception. The SDK route refuses unsupported layouts
before connecting. Email addresses and ordinary Markdown separators
remain literal instruction content.
Uninspectable policy refuses the route. Memory and subscription MCP
connectors are disabled, and the existing permission and supervisor policies apply.
Route metadata reports subscription provenance, rather than an account charge.

The [ratified Stage 3a plan](https://github.com/Consiliency/agent-harness/blob/main/plans/detailed-claude-sdk-runner-20261015.md)
requires synthetic transport and installed-package checks plus a non-skipped live
qualification receipt before activation is considered qualified. The dependency
extra is optional for every other route.

## Contributor test environment

From the repository root, install the declared test tools and visual extra, then
run the packaging and visual-evidence tests with the project environment:

```sh
uv sync --project phase-loop-runtime --group test --extra visual --python 3.14 --locked
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_outside_agent_contract_drift.py phase-loop-runtime/tests/test_visual_avatar_evidence_validator.py
```

The test group supplies package build/install tools and the pinned SDK for
credential-free transport tests; pytest is a runtime dependency. Ordinary installs
without the SDK extra do not install the SDK. The visual extra supplies Pillow
for image decoding. Both are opt-in. The native
repository-wide interpreter guard includes the dagger subproject's Python 3.14
floor, which is separate from this runtime package's Python 3.12 minimum and CI's
interpreter matrix. These commands verify the two selected files; they do not
establish complete CI equivalence, behavior without Pillow, full-suite acceptance
or production readiness.

## Python verification environments

An explicit `automation.python` pin to a virtual environment preserves that
environment for bare `python`/`python3` commands and Python pip refresh. The
interpreter still must satisfy the repository's `requires-python` constraints.
The verification shim uses an exec launcher so interpreter symlinks retain their
venv identity and installed packages.

During guarded discovery, version probes and verification, relative or empty PATH
entries anchor to the invoking process's working directory. This deliberately
changes empty-PATH discovery to search that directory. Missing PATH retains the
C-library discovery default (with Python's default fallback); guarded execution
uses that same default instead of its previous trailing-empty cwd search. Entry
order and duplicates remain intact. Leading `PATH=` overrides
consumed by the verification command parser anchor to the target repository,
including overrides equal to the inherited value. Shell payloads and external
`env` arguments are not parsed. Execution without a constraint or pin is unchanged.

Discovery and log metadata preserve the lexical interpreter selection. For
execution, traversable directory components containing `..` are resolved before
version probes, launchers, pip refresh and guarded child PATH lookup. The final
Python executable symlink is retained. This preserves the physical virtual
environment reached through a symlink/`..` path, even when direct Python startup
would normalize that spelling to another environment. Recorded pip argv uses
the execution spelling while the log retains the declared selection. Missing,
looping, non-directory or inaccessible entries retain their original spelling;
they cannot become new search directories through normalization. Absolute PATH
entries without `..` keep their exact strings, including repeated separators.

Post-aggregate commands reuse the absolute pinned launcher, while inherited PATH
anchors to the later invoking process's directory and consumed overrides to the
repository. They do not reconstruct historical PATH or revalidate every name in
a reused shim. Without an explicit pin, distinct satisfying `python` and `python3`
aliases keep their environments; metadata and pip prefer `python3`, then `python`.
Login profiles and explicit overrides can select another environment. Known
nested-discovery and diagnostic-redaction test failures remain separate work under
agent-harness#428; this repair does not establish full-suite success or completion
of agent-harness#841's dependency repair.

## Publication source audit

Normal FABPUB publication can distinguish an existing Python implementation such
as `credentials.py` from a credential artifact (Consiliency/agent-harness#893).
The path must be owned, regular Python source in both the frozen parent and staged
tree, parse and compile without warnings, and contain a top-level function or class. New files,
data-only files, symlinks, `.env*` and `.key` names do not receive this exception.
Other source languages remain subject to the existing filename guard.

The complete staged blob is scanned with pinned `detect-secrets` 1.5.0 built-in
detectors. Repository configuration, inline suppressions, filter exemptions and
online verification are not consulted. Findings and scanner failures block the
exception without printing matched data. Parsing/compilation warnings reject the
candidate rather than rendering source lines. No candidate code is executed.
This heuristic scan is not proof that
arbitrary or obfuscated secrets are absent; source review is still required.

Metadata-only evidence (parent/tree and blob identifiers, content hash and policy
version) is retained in the local publication checkpoint and checked again on
recovery against the frozen Git objects. The existing FABPUB tree binding and
transaction identity are unchanged. Legacy and prebuilt publication do not gain
the source exception; there is no caller-controlled path allowlist.

Fresh FABPUB publication refuses unstaged or untracked workspace changes with
`publication_workspace_invalid` before creating a transaction or advancing the
branch. Private plan, verification and handoff files under the .dev-skills
directory must be Git-ignored: `phase-loop init` adds the /.dev-skills/ rule to
`.gitignore`, or a local Git info/exclude rule can keep this setup out of
committed source. The publisher
does not add ignore rules or suppress workspace changes itself.

If a previous attempt already committed and then refused, repair the workspace
and retry the same normal publication with its original plan and verification
artifact. The exact committed transaction resumes without another commit.
Conflicted transactions refuse before staging; switching to prebuilt mode does
not repair a normal transaction. Authority and recovery checks still apply.

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

## Local Gemini model preference

The shipped Gemini planning and review defaults use Gemini 4 Argon. To use that
family for all local Gemini role defaults, add this to the environment that runs
`phase-loop`:

```sh
export PHASE_LOOP_GEMINI_MODEL=gemini-4-argon
```

Use a registered canonical base model without an effort suffix. The runtime
preserves action and seat effort: executor policy normalizes unsupported max
requests to high, and the default review board keeps medium. Explicit task models,
plan/roadmap model pins and configured board seats take precedence. Other providers,
subscription authentication and sandbox admission retain their existing behavior.
Invalid preferences fail without model fallback. Unsetting the variable restores
the shipped role defaults, including regular/lite Flash routing. This setting
does not change the standalone `agy` CLI's own local configuration.

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
phase-loop install --harness codex --source <path-to>/phase-loop-skills --copy --dry-run
phase-loop install --harness codex --source <path-to>/phase-loop-skills --copy --apply
```

These commands install copies and replace existing managed skill directories.
Back up customizations before applying. See [Team onboarding](https://github.com/Consiliency/agent-harness/blob/main/docs/TEAM-ONBOARDING.md)
for provider prerequisites, governance choices and the first-run check.

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

A failed `run-train` on a repository with no partition receipt leaves an empty
`<git-common-dir>/phase-loop-fabpub-broker-v1/run-train-writer.lock` behind.
The probe treats that file as runtime lock residue, not inventory state, only
when it is a regular, 0-byte, singly linked file owned by the operator; the
sealed inventory is identical with or without it. Anything else under that name
(content, a directory, a socket or FIFO, a symlink, a hardlink, a foreign owner)
is refused, as is a namespace root that is a symlink (dangling or not) or not a
directory. The refusal names the entry and what it is. It is not runtime residue:
inspect it, and remove it yourself only after confirming it is not yours, then
re-run the probe. The runtime never deletes it. The probe classifies the
namespace through one descriptor opened without following symlinks and refuses
if the root is replaced while it is inspected. These checks keep an honest
operator from mis-sealing; they are not a boundary against the operator's own
account, since a same-uid actor who can rewrite the namespace can already forge
broker state directly. Apply always holds every repository's writer lock, creating it if
absent, from before its re-probe until it returns, and refuses while a
`run-train` or another apply holds it. Never delete broker files to clear a
refusal.

Before apply, stop every `run-train` on the host, not only those for the named
repositories: the drain counts live `run-train` processes host-wide. A train that
starts during apply waits behind the writer lock, is counted as live, and makes
apply fail after DRAINING with `WriterGenerationBlocked`. To recover, stop the
trains and re-run the same `--apply --inventory <same file>`; that resumes the
sealed bootstrap and must not be preceded by a new probe. Until the resume
completes, trains in those repositories obtain generation leases but no
admission or provider effects.

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

The `phase-loop-closeout-audit --repo .` command grades **ignored** paths by producer. It
accepts harness handoffs that carry the handoff contract, and a project's declared build
outputs backed by a recorded producer run. Declare those outputs in a committed
`.phase-loop-generated-outputs.json`; anything else still blocks. See
`docs/phase-loop/closeout-generated-outputs.md` (agent-harness#1139).

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
