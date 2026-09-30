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

- it is a regular `.md` file, not a symlink, at exactly that depth;
- `<harness>-<skill>` is a skill the installed harness ships;
- its YAML frontmatter has `from`, `timestamp`, `repo`, `repo_root`, `branch`,
  `branch_slug`, `commit`, `run_id` and `artifact`;
- `from` equals the directory name.

A hand-placed file under `.dev-skills/` is not trusted because of where it sits. The same
applies to a note with no frontmatter, or to a handoff filed under the wrong skill. All of
these stay `unknown_ignored`.

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
- **`command`**: the producer's argv, as a list or a shell-split string. It must match,
  token for token, a command in the phase plan's `## Verification` list (or its
  `automation.suite_command`). That match is how the runner knows the producer ran.
- **`outputs`**: repo-relative globs. `*` matches within one path segment and `**`
  matches any number of whole segments. Each glob **must start with a literal path
  segment**, so `**`, `*` and `*.js` are rejected. Globs may not use `..`, and may not
  claim `.git`, `.phase-loop`, `.codex` or `.dev-skills`.

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

A declaration alone accepts nothing. A declared file counts only when a recorded
producer run left it behind with the **same content digest** it has now. The record is
written to `.phase-loop/generated-outputs/record.json`, which is runner state:

- **Runner-driven phases.** When the runner's verification runs a command that equals a
  declared producer's `command`, it digests every file under that producer's globs at the
  end of the run and records them. A producer that exits non-zero records no files, so
  its outputs stay unknown.
- **Skill-driven phases, or any manual run.** Run
  `phase-loop-closeout-audit --repo . --record-outputs`. This runs every declared producer
  in declaration order, records their outputs, and then audits.

The snapshot is taken once, after the whole run. A later producer that rewrites an
earlier producer's output, for example two producers writing into `.cache/`, therefore
does not cause a mismatch.

A declared file still stays `unknown_ignored`, with a reason printed beside it, when:

- the recorded run did not produce it (it was hand-placed);
- it changed after the run;
- no record exists;
- the record was made against a different committed declaration.

### Threat model

The audit catches accidental and unaccounted-for outputs. It does not defend against a
local actor with write access to the worktree, who could forge the record as easily as
the outputs themselves.
