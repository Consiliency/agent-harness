# Agent Harness — Team Onboarding

The **agent-harness** gives you our phase-loop workflow skills (roadmap → plan → execute,
plus one-off detailed planning and a skill editor) on your own machine. It's public and
standalone — **no VPN/tailnet, no 1Password, no shared pipeline, nothing from anyone's fleet.**

This is the canonical setup guide for people and their agents. Start with these
choices; use answers the operator has already supplied and ask for what is missing.

| Decision | What to establish |
|---|---|
| Machine and install surface | OS, per-user home, interactive harness skills or only the runtime CLI; on a fleet, repeat for each user/host. |
| Executor and authentication | Which installed provider CLI will do the work, which account it should use, and whether its own login/health check succeeds. Never copy credentials into a plan or report. |
| Governance | Whether autonomous work is permitted or independent review is required; preserve the target project's existing rules. |
| Authority | Who may approve, commit, push, merge and publish. Installing tools grants none of these permissions. Start with manual closeout. |

**Support boundaries:**

| Setup | What this guide covers |
|---|---|
| Linux / macOS | Public Bash installer and runtime baseline. Installer regression fixtures run on Linux; this is not a fresh macOS acceptance report. |
| Native Windows / WSL | Not validated by this guide. A Linux environment in WSL does not by itself prove provider or isolation support. |
| Single machine / fleet | Per-user installation on each host; no shared writable skill roots or credential distribution. Tailnet membership is optional. |
| Runtime only / interactive agent | Wheel-bundled skills serve the runtime; interactive agents need a separate install into their own skill root. |
| One provider / several providers | One authenticated executor can do autonomous work where allowed. Multiple accounts with the same vendor do not provide cross-vendor independence. |
| Isolated / governed review | Separate from installation. Requires the selected reviewers, authentication and supported sandbox/network isolation. Linux review isolation uses host facilities such as bubblewrap and namespaces; a successful macOS install does not certify that route. Refusals and unavailable seats remain failures to satisfy the gate. |

Do not select autonomous mode just to pass a required governed gate, silently
substitute a reviewer, or claim a review from a successful installation. The public
CLI currently composes its board; `--board`, `--seats` and a TOML `default_board`
are not supported CLI configuration controls. The manifest ratification override
helper is not wired into the production gate. Guided configuration, these controls
and broader portability are tracked in
[agent-harness#927](https://github.com/Consiliency/agent-harness/issues/927).

## Install (pick your harness)

Cross-platform (macOS / Linux). Replace `claude` with `codex`, `gemini`, or `opencode`:

```sh
# clone-then-run (you can read the script first):
git clone https://github.com/Consiliency/agent-harness
agent-harness/install-agent-harness.sh --harness all   # all four harnesses (or claude|codex|gemini|opencode)

# …or the one-liner:
curl -fsSL https://raw.githubusercontent.com/Consiliency/agent-harness/main/install-agent-harness.sh | bash -s -- --harness claude
```

Pin a specific release for the whole team with `--ref vX.Y.Z` — take the version from the
[releases page](https://github.com/Consiliency/agent-harness/releases/latest). Omit `--ref`
and the installer resolves the current release itself.

This guide targets current releases. Historical tags without `RELEASE_PIN` or
`phase-loop install --copy` need a version-specific setup procedure.

**Prereqs:** git, `curl` (the installer uses it to resolve the release pin, and the one-liner
form is delivered by it), and your harness CLI already installed (Claude Code / Codex / Gemini
/ OpenCode). The installer brings everything else (it installs `uv` if you don't have it).

Run the chosen provider's own login and a small health check before real execution.
`doctor` reports tool/credential discovery; it does not prove a working provider login.
The runtime needs no login of its own, but model execution still does.

The installer keeps its release checkout at `~/.local/share/agent-harness`
(`AGENT_HARNESS_HOME` overrides it). This is separate from the clone you ran the
script from. An existing destination must be a clean standalone checkout of the
configured repository. Files, symlinks, linked worktrees, unrelated checkouts and
dirty checkouts are refused before installing packages. Choose an absent destination
instead of deleting existing work.

Keep this checkout dedicated to the installer: updates use shallow fetches and
detach HEAD at the requested ref. Do not point `AGENT_HARNESS_HOME` at a development
checkout whose branch or history you want to keep working on.

An update also refuses checkout if the new ref would overwrite an ignored local
file. Installation is not transactional: after any failure, check the runtime
version and skills again before use; a package install may already have succeeded.

Skills are **copies**, expanded for the selected harness. Reruns replace the managed
skill directories, including edits inside them; back up local customizations first.
To inspect those destinations before applying, use an already installed runtime:

```sh
phase-loop install --harness claude --source agent-harness/phase-loop-skills --copy --dry-run --json
```

That source path is for clone-then-run. After a one-liner install, use
`"$HOME/.local/share/agent-harness/phase-loop-skills"` instead, or the bundle under
your chosen `AGENT_HARNESS_HOME`. Use a bundle matching the installed release.

For the runtime only, use `uv tool install phase-loop-runtime` or install into your
own Python environment with `pip install phase-loop-runtime`. To pin it, use
`uv tool install 'phase-loop-runtime==X.Y.Z'`, replacing `X.Y.Z` with a published
version. `consiliency-harness` is a dependency shim with its own version and a
runtime minimum; pin the engine directly for reproducible installations.

> **On the `curl … | bash` one-liner:** a pipeline reports the exit status of its *last*
> command, so if the download fails, `bash` receives empty input and exits `0`. The
> installer's own `set -euo pipefail` never gets to run, because it was never fetched. If you
> are scripting this, prefer the clone-then-run form, or fetch to a file and check that fetch
> before executing it. A mid-transfer drop is worse than a failed one: bash receives a
> **prefix** of the script and partially executes it.

## Verify the install (agents: parse this)

The harness is usually installed **by an agent**, so the success signal is a machine-readable
payload, not the installer's console output:

```sh
phase-loop doctor --json
```

It emits the versioned `phase-loop-doctor.v1` schema:

```json
{"schema": "phase-loop-doctor.v1",
 "summary": "18/18 tools present; BOM 3 current / 1 stale / 2 unknown (0 gating-stale)",
 "tools": [{"name": "git", "present": true, "authed": null, "unlocks": "version control"}]}
```

**What to assert, and what not to.**

- `schema == "phase-loop-doctor.v1"` — **the CLI runs.** Assert it rather than grepping the
  installer's output. It does *not* prove the whole install: the installer places a CLI
  **and** your harness's skills, and this field speaks only for the CLI.
- **`install_surfaces[]` is the skills half.** Find the entry with
  `surface == "interactive-harness-skills"` for your harness and require
  `status == "present"` (`partial` / `missing` mean the skill files aren't where the
  harness will look). Without this an install with missing interactive skills still
  reports `schema` and exit 0.
- **Never infer the verdict from `schema` alone.** Stdout stays pure, parseable JSON *even
  when the command fails*, so the payload still carries `schema == "phase-loop-doctor.v1"`
  alongside a non-zero exit (diagnostic on stderr). For the plain command shown above the two
  agree, so checking both is merely redundant — but the moment you add a flag that can fail,
  such as `--fail-on-stale`, `schema` stops tracking the verdict and an installer asserting
  only `schema` reports success over a failure. Check the exit code because it is the verdict,
  not because `schema` is unreliable.
- Exit `0` from a plain `doctor --json` means the report was produced. It is **not** a claim
  that every tool is present — read `tools[]` for that.
- `--fail-on-stale` exits non-zero **only** on a `stale` verdict among the *gating*
  (repo-owned) targets.
- **Do not treat `unknown` as failure.** The BOM degrades every unreachable registry to
  `unknown` by design, so an offline or network-restricted host reports `unknown` and still
  exits `0`. Failing on `unknown` will make your installer red on a healthy machine.

**The whole pass condition, in one place** — copy this rather than assembling it from the
bullets above. **It depends on which install you ran**, so pick the matching surface line:

> **installed** = the installer itself exited `0`
> *(under the `curl … | bash` one-liner the pipeline's exit is **bash's**, not the
> installer's — see the caveat above; scripted installs should clone-then-run)*
> **and** `phase-loop doctor --json` exited `0`
> **and** `schema == "phase-loop-doctor.v1"`
> **and** the matching `install_surfaces[]` entry has `status == "present"`:
>
> | how you installed | required surface |
> |---|---|
> | `pip install` / `uv tool install` only | `wheel-bundled-skills` |
> | `install-agent-harness.sh --harness <one>` | `interactive-harness-skills` for **that** harness |
> | `install-agent-harness.sh --harness all` | `interactive-harness-skills` for **all four** |
>
> `unknown` BOM verdicts are **not** failures.
>
> **Custom skill roots — the two env vars behave differently, and conflating them will
> make you dismiss a real failure.**
>
> - `AGENT_HARNESS_SKILL_DEST` is **installer-only, and only honored for a SINGLE
>   harness** — `--harness all` ignores it and installs to the default roots. `doctor`
>   never reads it either, so a good single-harness install to a custom destination reads
>   `missing` / `partial`. That one *is* a false red. Bridge it **only for a
>   single-harness install**, passing the **literal path** you installed to:
>   `PHASE_LOOP_SKILL_BUNDLE=/your/custom/root phase-loop doctor --json`, then assert your
>   harness's entry. Do **not** write `"$AGENT_HARNESS_SKILL_DEST"` unless it is still
>   set in *this* shell — a command-scoped assignment on the installer line does not
>   persist, and an empty value is ignored by the resolver, which silently drops you back
>   to the default roots. After `--harness all`, do **not** bridge — but if
>   `PHASE_LOOP_SKILL_BUNDLE` is already exported in your shell it redirects **all four**
>   harness probes to that one path regardless of how you installed, so clear it for the
>   check: `PHASE_LOOP_SKILL_BUNDLE= phase-loop doctor --json` (an empty value is ignored
>   by the resolver, which is exactly what restores the defaults; works in `sh`, `bash`
>   and `zsh`).
> - `PHASE_LOOP_SKILL_BUNDLE` is **honored by `doctor`** — it probes *that* path, not the
>   defaults. So `missing` / `partial` under it is a **true finding about the root you
>   pointed at**, and must not be waved away as a default-root artifact.

**Two things the pass condition deliberately does not include.**

- **Pin currency is not install success.** `--fail-on-stale` compares gating pins against the
  registry's *latest*; a floor legitimately lags latest, so a healthy install can exit
  non-zero under that flag. Run it if you want to know whether your pins are current — that
  is a **separate question** from whether the install worked, and treating it as install
  failure will red a working machine.
- **`doctor` inspects state, not the run that produced it.** It cannot tell a fresh install
  from a stale one that was already there, so a *failed upgrade* over a working older install
  still satisfies every clause above. That is why the installer's own exit code is the first
  conjunct, and why you should verify the version you asked for actually landed
  (`phase-loop --version`) on **any update or re-run**, not only when you pinned a
  `--ref`. The silent case: an unpinned one-liner update whose download fails exits `0`,
  doctor stays green against the *old* install, and nothing was updated.

A missing `phase-loop` on `PATH` is the one failure that surfaces before any of this — see
Troubleshooting below.

## First run in your project

Use a clean disposable project for the first preview. The runner executes a roadmap;
it does not ingest a repository and invent requirements. Author
`specs/phase-plans-v1.md` first (see the repository's example for the format), or ask
your harness's `phase-roadmap-builder` skill to produce one. Review the roadmap and
its automation commands before execution.

From that project's root, replace `P1` with an actual phase alias and `codex` with
your chosen installed executor:

```sh
phase-loop validate-roadmap specs/phase-plans-v1.md
phase-loop dry-run --repo . --roadmap specs/phase-plans-v1.md --phase P1 --executor codex --closeout-mode manual
```

Validation is read-only. The preview launches no provider and performs no closeout,
but writes local `.phase-loop` state/events. Check its exit status and output; it
does not verify authentication or give review approval.

Once the operator has authorized execution, a bounded first run is:

```sh
phase-loop run --repo . --roadmap specs/phase-plans-v1.md --phase P1 --executor codex --max-phases 1 --closeout-mode manual
```

This launches the executor and can edit the project. Manual closeout prevents the
runner's automatic commit/push; it is not a sandbox for commands in the roadmap or
executor instructions. Keep those within the agreed authority too. Without an
explicit closeout mode, `run` defaults to pushing completed work.

Add `--governed` when your project requires independent review; the default is
autonomous unless `PHASE_LOOP_RUN_MODE=governed` is set. Governance is a requirement
to satisfy, not a setting to relax when a reviewer is unavailable.

## What you get

- The `phase-loop` runtime CLI (and `codex-phase-loop`).
- These workflow skills installed into your harness's skill root
  (`~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills`, or
  `~/.config/opencode/skills`):
  - **phase-roadmap-builder** — turn a plan/conversation into a phased roadmap
  - **plan-phase** — architect one phase into parallel swim-lanes
  - **execute-phase** — run a phase's lanes to completion
  - **plan-detailed** — a single bounded change, no roadmap overhead
  - **execute-detailed** — implement that bounded plan
  - **advisor-board** — cross-vendor review (also installed as **advisor-panel**)
  - **run-train** — coordinate a cross-repo release train
  - **task-contextualizer** — brief a subagent
  - **phase-loop** — drive the loop end-to-end
  - **skill-editor** / **skill-improvement-planner** — author/refine skills

## Use it (standalone — no pipeline required)

In your harness, invoke the skills like any other slash-command/skill, e.g. in Claude Code:

```
/claude-phase-roadmap-builder   # → produces specs/phase-plans-v1.md
/claude-plan-phase P1           # → plans/phase-plan-v1-P1.md
/claude-execute-phase P1        # → runs the lanes
```

(Codex/Gemini/OpenCode use their own prefixes.) Some installed Claude/Gemini/OpenCode
skill instructions still name Codex paths for their own state or helpers. Installation
presence does not prove those workflows are portable: when a path points at the wrong
harness, stop that step and report it instead of creating a parallel Codex skill root.
Final installed-path corrections are tracked in
[agent-harness#927](https://github.com/Consiliency/agent-harness/issues/927).

For a small one-off change, use `…-plan-detailed`. The runtime orchestrates the
selected executor; that executor and review providers make external calls.
Governed-pipeline integration is optional.

## Update / pin / uninstall

- **Update:** `git pull` in your clone **first**, then re-run the installer. Re-running a
  stale clone does **not** update you: `resolve_ref` trusts the clone's own sibling
  `RELEASE_PIN` before consulting the remote, so it re-installs the same old ref. (The
  `curl … | bash` one-liner has no local pin and does resolve the current release — but
  see the pipeline-exit caveat above before scripting it.)
- **Update (pip / uv install):** `uv tool upgrade phase-loop-runtime` — or `pip install -U
  phase-loop-runtime`. Name the **engine**, not `consiliency-harness`: that shim pins a
  floor (`phase-loop-runtime>=0.6.1`), so upgrading the shim can leave the old engine in
  place and report success.

  **`uv tool upgrade` only moves you if the stored requirement is UNPINNED.** The
  deciding factor is what uv recorded, not who ran the install. Check it:

  ```sh
  grep requirements ~/.local/share/uv/tools/phase-loop-runtime/uv-receipt.toml
  ```

  A bare `{ name = "phase-loop-runtime" }` upgrades normally. Anything pinned —
  `specifier = "==0.7.13"`, or a `git+…@vX.Y.Z` URL — is re-resolved to **the same
  version**, so `uv tool upgrade` reports success and moves nothing. That covers the
  installer script (it installs from a tag-pinned URL) **and** a hand-run pinned install
  such as `uv tool install "git+…@<TAG>#subdirectory=phase-loop-runtime"`, which
  `phase-loop-runtime/README.md` documents. To advance a pinned install, re-install at the
  new ref or re-run the installer — see the two bullets above.
- **Pin a version:** `--ref vX.Y.Z` (everyone on the same release).
- **Uninstall:** `uv tool uninstall phase-loop-runtime` removes a uv-installed
  engine. For interactive skills, inspect the `--copy --dry-run --json` action list
  above using the same harness, source and destination as your install. Back up
  customizations and remove only those enumerated managed destinations. These are
  directories, not symlinks; a `*-phase-*` glob also misses several skills. Preserve
  unrelated skills and user configuration. Automated uninstall/migration remains
  part of agent-harness#927.

## Troubleshooting

- **`phase-loop: command not found`** — make sure `~/.local/bin` is on your `PATH`
  (the installer puts the CLI there); open a new shell or `hash -r`.
- **Already have a `phase-loop` on PATH?** Check which one wins with
  `command -v phase-loop` and `phase-loop --version`.

Repo + issues: <https://github.com/Consiliency/agent-harness> · Apache-2.0.
