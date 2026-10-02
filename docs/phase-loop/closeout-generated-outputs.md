# Closeout audit: declaring generated outputs

`phase-loop-closeout-audit --repo .` grades every **ignored** path in the worktree by who
produced it. It exits 0 only when every ignored path has a recognised producer. An ignored
file with no producer is `unknown_ignored` and blocks closeout (exit 1). This is
deliberate: git ignoring a path is never evidence that it is harmless
(agent-harness#186).

The audit recognises four producers:

| Bucket | What earns it |
|---|---|
| `runner_owned` | Runner state under `.phase-loop/` or `.codex/phase-loop/`, and **harness handoffs** (see below). |
| `tool_cache` | Toolchain directories such as `__pycache__/`, `.pytest_cache/`, `node_modules/`, `.venv/` and `*.egg-info/`. |
| `declared_output` | A build output your project **declares**, backed by a **recorded producer run** (see below). |
| `unknown_ignored` | Anything else. It blocks. |

When git collapses a wholly ignored directory into one entry (`!! dist/`), the audit
grades each ignored file inside it. The directory passes only if every one of those
files does.

## Harness handoffs

Workflow skills write handoffs to `.dev-skills/handoffs/<harness>-<skill>/<run_id>.md`
and `latest.md`. A file there counts as `runner_owned` only when it carries the handoff
contract itself:

- it is a regular `.md` file at exactly that depth, reached with no symlink on its path;
- `<harness>-<skill>` is a skill the installed harness ships;
- its YAML frontmatter has `from`, `timestamp`, `repo`, `repo_root`, `branch`,
  `branch_slug`, `commit`, `run_id` and `artifact`;
- `from` equals the directory name;
- `repo_root` resolves to the repository being audited;
- `commit` names a commit that exists in that repository.

Nothing else under `.dev-skills/` is trusted because of where it sits. That includes a
hand-placed note, a file with no frontmatter, a handoff filed under the wrong skill, and
a handoff copied from another checkout or repository. All of these stay
`unknown_ignored`. The contract is self-reported metadata, so see the threat model below.

## Declaring build outputs

Commit a file named `.phase-loop-generated-outputs.json` at the repository root:

```json
{
  "schema": "phase-loop.generated-outputs.v1",
  "producers": [
    {
      "name": "baml",
      "command": "npm run bootstrap:baml",
      "outputs": [".baml/**", "baml_sdk/**", "generated/baml/**"]
    },
    {
      "name": "test",
      "command": ["npm", "test"],
      "outputs": ["dist/**", ".cache/**"]
    }
  ]
}
```

- **`name`**: a unique lowercase identifier.
- **`command`**: the producer's argv, given as a list or as a shell-split string.
  Producers run without a shell, so shell syntax is rejected:
  - in a string, any unquoted control or redirection operator, even without spaces
    around it (`a&&b`, `build 2>/dev/null`, `x;y`), and any backtick or `$(...)`;
  - in a list, any element that is nothing but such an operator (`"|"`, `"&&"`);
  - in either form, a leading `NAME=value` assignment.

  Declare one producer per command. `--record-outputs` runs it from the repository
  root. For the runner to observe it, it must equal, token for token, a command in the
  phase plan's `## Verification` list (or its `automation.suite_command`).
- **`outputs`**: repo-relative globs. `*` matches within one path segment and `**`
  matches any number of whole segments. Each glob **must start with a literal path
  segment**, so `**`, `*` and `*.js` are rejected. Globs may not use `..`, and may not
  claim `.git`, `.phase-loop`, `.codex` or `.dev-skills`, in any letter case.

The v1 format is closed. Any other key, at the top level or on a producer, is an error,
so a field added in a later version cannot be silently misread by an older runtime.

The declaration is read from **`HEAD`**, so a declaration has no effect until it is
committed. An uncommitted, staged or ignored edit never widens what counts. A malformed
declaration makes the audit exit 2 ("cannot evaluate") instead of being skipped silently.

### Why a committed repo-root file

Build outputs belong to the project, not to one phase, so a per-phase plan field would
have to be repeated in every plan. The audit also runs with only `--repo`, which means
it needs a declaration it can find without a plan. Reading the declaration from `HEAD`
means it has been reviewed like any other change before it can make an ignored path
acceptable.

## Evidence: the producer record

A declaration alone accepts nothing. A declared file counts only when all of these
hold:

- an **observed invocation of a producer whose globs cover it created the file or
  changed its content**;
- that happened at the **current commit**, in the **current phase**;
- the file **still has the recorded content digest**.

The record is written to `.phase-loop/generated-outputs/record.json`, which is runner
state.

### How evidence is recorded

- **At closeout: every executor, every repo.** Run
  `phase-loop-closeout-audit --repo . --record-outputs`.
  - This is a **clean, observed rebuild**. First, every existing *ignored, untracked*
    file under a declared glob is moved aside. Tracked files and untracked-but-not-
    ignored files are never touched. Each declared producer then runs in declaration
    order, observed one invocation at a time, and the record is written. Finally the
    audit runs.
  - Because every output is re-created, a deterministic producer that writes the same
    bytes as last time earns provenance. A planted file, or an orphan the build no
    longer emits, is not in the worktree afterwards to ride along.
  - Moved files go to a timestamped directory under
    `.phase-loop/generated-outputs/displaced/`, and you can restore anything you meant
    to keep from there. Only the newest 5 such directories are kept; older ones are
    removed.
  - **Declare a producer's incremental state alongside its outputs.** That means
    `.tsbuildinfo`, build stamps, and so on. If the state is undeclared, a producer that
    skips work because its stamp says "up to date" emits nothing after the outputs
    were moved aside. The rebuild then leaves those outputs in `displaced/`.
  - Each producer is bounded by `PHASE_LOOP_VERIFY_TIMEOUT_SECONDS` (default 1200),
    the same limit the runner's verification uses. Zero, a negative value, NaN,
    infinity or an unparsable value is ignored in favour of the default. A producer
    runs in its own process group, and on timeout the whole group is killed, so no
    grandchild keeps writing. A producer that times out counts as failed.
  - With no declaration, the flag does nothing extra, so it is safe to pass
    everywhere. The shipped execute-phase skills and runner prompt prescribe this
    form.
  - The flag executes the commands the committed declaration names. That is the same
    trust level as the plan's verification commands. Don't pass it on a checkout you
    don't trust. A producer can also write tracked files, so check `git status`
    again after recording.
- **The runner's verification.** When the runner's verification runs a command that
  equals a declared producer's `command`, it observes that invocation the same way.
  It does **not** move anything aside. A later audit at the same commit and phase then
  passes without re-running anything. A recording failure never changes the
  verification outcome. It is printed to stderr and reported as
  `generated_outputs_record_error` in the runner's verification summary.

### What counts as written

- **Before and after snapshots.** Each observed invocation is bracketed by a snapshot
  of the producer's own declared outputs, taken just before and just after it runs.
  A file counts as written by that producer only if:
  - it is **new**, or
  - its **content digest changed** during the invocation.
- **Nothing else is credited:**
  - timestamps: `touch` and `utime` on an existing file;
  - mode, link or rename changes;
  - files an undeclared command wrote, even in the same verification run.
- **Failed producers.** A producer that exits non-zero gets no credit, and the failed
  invocation withdraws that producer's earlier entries.
- **Byte-identical regeneration.** On the runner path, a producer that rewrites
  identical bytes over a file no record attributes earns nothing. Use
  `--record-outputs`, whose clean rebuild re-creates the file.
- **Overlapping globs.** When two producers' globs both cover a file, it belongs to
  whichever producer wrote it last, regardless of declaration order.
- **Incremental producers.** An output that the producer did not rewrite this time
  carries forward from the previous record. That requires the same producer to have
  run successfully in this recording and the bytes to be unchanged. A second
  invocation of the same producer within one recording keeps the first one's writes.
  On the runner path only, an output the producer has stopped producing, but that
  nobody deleted, also carries forward. `--record-outputs` moves it aside instead.
- **Binding to commit and phase.** Each invocation records the `HEAD` it ran at. If
  `HEAD` moved during the invocation, or between it and the record being written,
  nothing is recorded.
  - The record is bound to that commit and to the **phase identity**. That identity
    is, in order:
    1. an explicit alias: the runner's live alias for its own verification, or
       `--phase ALIAS` on the command line;
    2. `PHASE_LOOP_PHASE_ALIAS`, which the runner's launcher stamps on every executor
       child with the phase it was dispatched for, overwriting any inherited value. A
       launch with no dispatched phase removes an inherited value instead;
    3. `PHASE_ALIAS`.
  - The phase identity is **never** read from `.phase-loop/state.json`. The runner
    writes that file only after a loop ends, so during a loop it names the previous
    phase.
  - With **no** phase identity, nothing is recorded and nothing is accepted: the audit
    blocks with "no phase identity". A manual run outside the runner passes
    `--phase ALIAS` to both the recording and the audit.
  - The runner's execute prompt names the phase on the audit command it prescribes
    (`--record-outputs --phase ALIAS`). That reaches Claude channel and agent-view
    sessions, which are not launched as child processes and so get no launcher
    environment. The execute-phase skills prescribe the command without `--phase`; an
    executor following only a skill, outside a runner-launched child, gets the
    fail-closed "no phase identity" block until it passes `--phase`.
  - At the same commit and phase, a recording extends the record, so a repair turn or
    relaunch that re-runs one producer keeps the others' evidence.
  - A different commit or phase starts empty. When the phase identity is supplied,
    another phase's evidence does not satisfy this one, even at the same commit.
  - The guarantee is only as good as the identity. An operator who sets the same
    `PHASE_LOOP_PHASE_ALIAS` for two phases, or passes the wrong `--phase`, defeats it.
- **Symlinks.** A symlink, or any path reached through a symlinked directory, is never
  recorded and never accepted. Its content lives wherever the link points.

A declared file stays `unknown_ignored`, with a reason printed beside it, when:

- no observed producer invocation wrote it;
- it changed after the recording;
- it is a symlink;
- no record exists;
- the record was taken at another commit or in another phase;
- the audit has no phase identity;
- the record was made against another committed declaration;
- the record entry is malformed.

**Caches.** Declare a tool cache only if its producer writes it. Its evidence then lasts
until something else writes to it.

### Threat model

The audit catches accidental and unaccounted-for outputs: files no declared producer
wrote, stale evidence from an earlier phase, links that point outside the repository,
and handoffs that belong to another checkout. It does not defend against a local actor
with write access to the worktree. Such an actor can forge the record or a handoff's
frontmatter as easily as the outputs themselves. It also does not defend against a
declared producer that deliberately writes something harmful. Declaring a producer
means trusting what it writes inside its globs.
