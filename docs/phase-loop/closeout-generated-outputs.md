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
- **`command`**: the producer's argv, as a list or a shell-split string. It is not a
  shell line: `&&`, `;`, `|` and redirections are rejected, so declare one producer per
  command. `--record-outputs` runs it from the repository root. For the runner to
  observe it, it must equal, token for token, a command in the phase plan's
  `## Verification` list (or its `automation.suite_command`).
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

A declaration alone accepts nothing. A declared file counts only when an **observed
invocation of a producer whose globs cover it wrote it**, at the **current commit**, and
it still has the **same content digest**. The record is written to
`.phase-loop/generated-outputs/record.json`, which is runner state.

### How evidence is recorded

- **At closeout: every executor, every repo.** Run
  `phase-loop-closeout-audit --repo . --record-outputs`. It runs each declared producer
  in declaration order, observing each invocation separately. It records what each
  invocation wrote and then audits. With no declaration it does nothing extra, so the
  flag is safe to pass everywhere. The shipped execute-phase skills and runner prompt
  prescribe this form.
- **The runner's verification.** When the runner's verification runs a command that
  equals a declared producer's `command`, it observes that invocation the same way.
  A later audit at the same commit then passes without re-running anything. A
  recording failure never changes the verification outcome. It is printed to stderr
  and reported as `generated_outputs_record_error` in the runner's verification
  summary.

### What counts as written

- Each observed invocation is bracketed by a snapshot of the producer's own declared
  outputs, taken just before and just after it runs. A file counts as written by that
  producer if it is new, if its content changed, or if its mtime moved during the
  invocation.
- Nothing else is credited:
  - a file an undeclared command wrote, even in the same verification run;
  - a file that existed before and was only chmod-ed, linked or renamed;
  - a file whose producer exited non-zero. A failed invocation also withdraws that
    producer's earlier entries.
- The one thing that still passes is an explicit `touch` of an existing file by the
  producer itself, because that moves mtime.
- **Overlapping globs.** When two producers' globs both cover a file, it belongs to
  whichever producer wrote it last, regardless of declaration order.
- **Incremental and byte-identical producers.** An output the producer did not rewrite
  this time carries forward from the previous record. That happens only when the same
  producer ran successfully in this recording and the bytes are unchanged.
- **Commit binding.** The record is bound to `HEAD`. At the same commit, a recording
  extends the record, so a repair turn that re-runs one producer keeps the others'
  evidence. After a commit, for example in the next phase, the old record no longer
  counts until the producers run again.
- **Symlinks.** A symlink, or any path reached through a symlinked directory, is never
  recorded and never accepted. Its content lives wherever the link points.

A declared file stays `unknown_ignored`, with a reason printed beside it, when:

- no observed producer invocation wrote it;
- it changed after the recording;
- it is a symlink;
- no record exists;
- the record was taken at another commit;
- the record was made against another committed declaration.

Re-recording is always safe, because it re-runs the producers: an edited generated file
is regenerated, not laundered.

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
